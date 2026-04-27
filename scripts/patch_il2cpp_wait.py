#!/usr/bin/env python3
"""
Binary patch the original arm64-v8a.so so the overlay UI thread waits for the
host app's Unity IL2CPP runtime to come up (libil2cpp.so loaded *and*
il2cpp_domain_get() returning non-null) before doing anything else. Mirrors
the source-level fix in src/runtime/Il2CppRuntime.cpp for the case where you
want to ship the original obfuscated binary instead of rebuilding from
scratch.

What it does:

    1. Appends a small RX code-cave to the .so containing a
       pthread-start-routine wrapper. Pseudocode:

           void* wrapper(void* arg) {
               for (;;) {
                   void* h = dlopen("libil2cpp.so", RTLD_NOLOAD);
                   if (h) {
                       auto get = (Il2CppDomain*(*)())dlsym(h, "il2cpp_domain_get");
                       if (get && get() != nullptr) {
                           return original_overlay_thread_main(arg);
                       }
                   }
                   sleep(1);
               }
           }

       The wrapper calls dlopen, dlsym and sleep through the binary's
       existing PLT entries, and tail-calls the original `overlay_thread_main`
       at file offset 0x54300 once the runtime is ready.

    2. Adds a new PT_LOAD program header (RX) covering the code cave. The
       existing PT_GNU_STACK entry (marker only, no real mapping) is
       repurposed to avoid resizing the program-header table.

    3. Patches the two instructions in `OverlayModule::postAppSpecialize`
       (file offset 0x57440 / 0x57448) that set `pthread_create`'s
       `start_routine` argument from `0x54300` to `wrapper`.

Inputs/outputs are file paths; nothing here touches anything in /proc.

Layout assumption: file size is < 0x140000 and the second LOAD ends below
virtual address 0x140000 (verified for the supplied binary). The new LOAD
goes at vaddr 0x140000 / file offset 0x120000, both page (0x10000) aligned.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# ELF helpers (small subset, just enough for in-place edits)
# ---------------------------------------------------------------------------

ELF64_EHDR = "<16sHHIQQQIHHHHHH"
ELF64_PHDR = "<IIQQQQQQ"

PT_LOAD = 1
PT_GNU_STACK = 0x6474E551
PF_X, PF_W, PF_R = 1, 2, 4


def parse_phdrs(buf: bytearray) -> tuple[int, int, list[list[int]]]:
    e_phoff   = struct.unpack_from("<Q", buf, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", buf, 0x36)[0]
    e_phnum   = struct.unpack_from("<H", buf, 0x38)[0]
    assert e_phentsize == struct.calcsize(ELF64_PHDR), e_phentsize

    phdrs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        phdrs.append(list(struct.unpack_from(ELF64_PHDR, buf, off)))
    return e_phoff, e_phentsize, phdrs


def write_phdr(buf: bytearray, e_phoff: int, e_phentsize: int, idx: int,
               phdr: list[int]) -> None:
    struct.pack_into(ELF64_PHDR, buf, e_phoff + idx * e_phentsize, *phdr)


# ---------------------------------------------------------------------------
# AArch64 instruction encoders
# ---------------------------------------------------------------------------

def _signed(v: int, bits: int) -> int:
    mask = (1 << bits) - 1
    return v & mask


def enc_b(pc: int, target: int) -> int:
    """Unconditional branch B <imm26>, range +/- 128 MB."""
    diff = target - pc
    assert -(1 << 27) <= diff < (1 << 27), f"B out of range: {diff:#x}"
    assert diff & 3 == 0
    imm26 = _signed(diff >> 2, 26)
    return 0x14000000 | imm26


def enc_bl(pc: int, target: int) -> int:
    """BL <imm26>, range +/- 128 MB."""
    diff = target - pc
    assert -(1 << 27) <= diff < (1 << 27), f"BL out of range: {diff:#x}"
    assert diff & 3 == 0
    imm26 = _signed(diff >> 2, 26)
    return 0x94000000 | imm26


def enc_cbz(pc: int, target: int, reg: int) -> int:
    diff = target - pc
    assert -(1 << 20) <= diff < (1 << 20)
    imm19 = _signed(diff >> 2, 19)
    return 0xB4000000 | (imm19 << 5) | reg  # CBZ Xn


def enc_cbnz(pc: int, target: int, reg: int) -> int:
    diff = target - pc
    assert -(1 << 20) <= diff < (1 << 20)
    imm19 = _signed(diff >> 2, 19)
    return 0xB5000000 | (imm19 << 5) | reg  # CBNZ Xn


def enc_adr(pc: int, target: int, reg: int) -> int:
    """ADR Xreg, #imm21 (PC-relative byte offset)."""
    diff = target - pc
    assert -(1 << 20) <= diff < (1 << 20), f"ADR out of range: {diff:#x}"
    immlo = diff & 3
    immhi = (diff >> 2) & ((1 << 19) - 1)
    return 0x10000000 | (immlo << 29) | (immhi << 5) | reg


def enc_adrp(pc: int, target_page: int, reg: int) -> int:
    """ADRP Xreg, target_page (page = high bits, 4K-aligned)."""
    diff = (target_page & ~0xFFF) - (pc & ~0xFFF)
    diff_pages = diff >> 12
    assert -(1 << 20) <= diff_pages < (1 << 20), f"ADRP out of range: {diff:#x}"
    immlo = diff_pages & 3
    immhi = (diff_pages >> 2) & ((1 << 19) - 1)
    return 0x90000000 | (immlo << 29) | (immhi << 5) | reg


def enc_add_imm(rd: int, rn: int, imm12: int) -> int:
    assert 0 <= imm12 < (1 << 12)
    return 0x91000000 | (imm12 << 10) | (rn << 5) | rd  # ADD Xd, Xn, #imm12


def enc_movz_imm(rd: int, imm16: int, hw: int = 0) -> int:
    """MOVZ Xd, #imm, LSL #(16*hw)."""
    assert 0 <= imm16 < (1 << 16) and 0 <= hw < 4
    return 0xD2800000 | (hw << 21) | (imm16 << 5) | rd


def enc_mov_xzr(rd: int) -> int:
    """MOV Xd, XZR (alias of ORR Xd, XZR, XZR)."""
    return 0xAA1F03E0 | rd


def enc_blr(reg: int) -> int:
    return 0xD63F0000 | (reg << 5)


def enc_stp_pre(rt1: int, rt2: int, rn: int, imm: int) -> int:
    """STP Xt1, Xt2, [Xn, #imm]! (pre-indexed, 64-bit)."""
    assert -512 <= imm <= 504 and imm % 8 == 0
    imm7 = _signed(imm // 8, 7)
    return 0xA9800000 | (imm7 << 15) | (rt2 << 10) | (rn << 5) | rt1


def enc_ldp_post(rt1: int, rt2: int, rn: int, imm: int) -> int:
    """LDP Xt1, Xt2, [Xn], #imm (post-indexed, 64-bit)."""
    assert -512 <= imm <= 504 and imm % 8 == 0
    imm7 = _signed(imm // 8, 7)
    return 0xA8C00000 | (imm7 << 15) | (rt2 << 10) | (rn << 5) | rt1


# ---------------------------------------------------------------------------
# Wrapper assembly
# ---------------------------------------------------------------------------

# Layout (offsets from wrapper start, all 4-byte instructions or 8-byte data):
#
#   +0x00   stp x19, x30, [sp, #-0x10]!
#   +0x04   mov x19, x0                   ; save thread arg
#   loop_top:
#   +0x08   adr x0, str_libil2cpp
#   +0x0C   movz x1, #4                   ; RTLD_NOLOAD
#   +0x10   bl dlopen_plt
#   +0x14   cbz x0, do_sleep
#   +0x18   adr x1, str_il2cpp_domain_get
#   +0x1C   bl dlsym_plt
#   +0x20   cbz x0, do_sleep
#   +0x24   blr x0                         ; call il2cpp_domain_get()
#   +0x28   cbnz x0, ready
#   do_sleep:
#   +0x2C   movz x0, #1
#   +0x30   bl sleep_plt
#   +0x34   b loop_top
#   ready:
#   +0x38   mov x0, x19
#   +0x3C   ldp x19, x30, [sp], #0x10
#   +0x40   b overlay_thread_main_orig    ; tail-call (=0x54300)
#   +0x44   .balign 4
#   +0x44   "libil2cpp.so\0"             (13 bytes, padded)
#   +0x54   "il2cpp_domain_get\0"        (18 bytes, padded)


def assemble_wrapper(*, base_vaddr: int,
                     plt_dlopen: int, plt_dlsym: int, plt_sleep: int,
                     overlay_thread_main: int) -> bytes:
    insns: list[int] = []

    # Resolve relative labels
    def _at(off: int) -> int:
        return base_vaddr + off

    LOOP_TOP    = 0x08
    DO_SLEEP    = 0x2C
    READY       = 0x38
    STR_PKG     = 0x44
    STR_DOMAIN  = STR_PKG + 16    # 0x54

    # +0x00: stp x19, x30, [sp, #-0x10]!
    insns.append(enc_stp_pre(19, 30, 31, -16))
    # +0x04: mov x19, x0
    insns.append(0xAA0003F3)  # encoded directly
    # +0x08: adr x0, str_libil2cpp
    insns.append(enc_adr(_at(0x08), _at(STR_PKG), 0))
    # +0x0C: movz x1, #4
    insns.append(enc_movz_imm(1, 4))
    # +0x10: bl dlopen
    insns.append(enc_bl(_at(0x10), plt_dlopen))
    # +0x14: cbz x0, do_sleep
    insns.append(enc_cbz(_at(0x14), _at(DO_SLEEP), 0))
    # +0x18: adr x1, str_il2cpp_domain_get
    insns.append(enc_adr(_at(0x18), _at(STR_DOMAIN), 1))
    # +0x1C: bl dlsym
    insns.append(enc_bl(_at(0x1C), plt_dlsym))
    # +0x20: cbz x0, do_sleep
    insns.append(enc_cbz(_at(0x20), _at(DO_SLEEP), 0))
    # +0x24: blr x0
    insns.append(enc_blr(0))
    # +0x28: cbnz x0, ready
    insns.append(enc_cbnz(_at(0x28), _at(READY), 0))
    # +0x2C: movz x0, #1  (sleep 1 second)
    insns.append(enc_movz_imm(0, 1))
    # +0x30: bl sleep
    insns.append(enc_bl(_at(0x30), plt_sleep))
    # +0x34: b loop_top
    insns.append(enc_b(_at(0x34), _at(LOOP_TOP)))
    # +0x38: mov x0, x19  (restore thread arg)
    insns.append(0xAA1303E0)  # mov x0, x19
    # +0x3C: ldp x19, x30, [sp], #0x10
    insns.append(enc_ldp_post(19, 30, 31, 16))
    # +0x40: b overlay_thread_main_orig
    insns.append(enc_b(_at(0x40), overlay_thread_main))

    code = b"".join(struct.pack("<I", w) for w in insns)
    assert len(code) == STR_PKG, (len(code), STR_PKG)

    # Append literal strings
    pkg = b"libil2cpp.so\0"
    pkg_padded = pkg + b"\0" * (16 - len(pkg))
    domain = b"il2cpp_domain_get\0"
    domain_padded = domain + b"\0" * ((4 - len(domain) % 4) % 4)

    return code + pkg_padded + domain_padded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CAVE_FILE_OFFSET = 0x120000   # page-aligned, well past existing file end
CAVE_VADDR       = 0x140000   # page-aligned, well past existing memory map
CAVE_SIZE        = 0x1000     # one page

# Target-binary addresses (file == vaddr in this DSO since first LOAD vaddr=0)
ADRP_X2_OFFSET   = 0x57440    # `adrp x2, 0x54000` in postAppSpecialize
ADD_X2_OFFSET    = 0x57448    # `add  x2, x2, #0x300`
OVERLAY_FN_VADDR = 0x54300    # original overlay_thread_main

PLT_DLOPEN  = 0xc7d0   # determined below from .rela.plt
PLT_DLSYM   = 0xc7d0
PLT_SLEEP   = 0xc7d0


def find_plt_for(elf_bytes: bytes, sym_names: dict[str, int]) -> dict[str, int]:
    """Return symbol_name -> PLT entry virtual address."""
    # Parse .dynsym/.dynstr to map symbol name -> dynsym index
    # Then scan .rela.plt for entries pointing at .got slots; PLT entry index
    # in .rela.plt corresponds to PLT stub at .plt + 32 + 16*index for arm64
    # Android (the first 32 bytes are the PLT0 lazy-resolver header).
    import struct as _s

    e_shoff   = _s.unpack_from("<Q", elf_bytes, 0x28)[0]
    e_shentsize = _s.unpack_from("<H", elf_bytes, 0x3a)[0]
    e_shnum   = _s.unpack_from("<H", elf_bytes, 0x3c)[0]
    e_shstrndx = _s.unpack_from("<H", elf_bytes, 0x3e)[0]

    shdrs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        sh = _s.unpack_from("<IIQQQQIIQQ", elf_bytes, off)
        shdrs.append(sh)

    shstrtab_offset = shdrs[e_shstrndx][4]

    def _sec_name(sh):
        ofs = shstrtab_offset + sh[0]
        end = elf_bytes.index(b"\0", ofs)
        return elf_bytes[ofs:end].decode()

    by_name = {_sec_name(sh): sh for sh in shdrs}

    dynsym  = by_name[".dynsym"]
    dynstr  = by_name[".dynstr"]
    relaplt = by_name[".rela.plt"]
    plt     = by_name[".plt"]

    dynsym_off = dynsym[4]
    dynstr_off = dynstr[4]

    def _sym_name(idx):
        ent = _s.unpack_from("<IBBHQQ", elf_bytes, dynsym_off + idx * 24)
        st_name = ent[0]
        end = elf_bytes.index(b"\0", dynstr_off + st_name)
        return elf_bytes[dynstr_off + st_name:end].decode()

    rela_off  = relaplt[4]
    rela_size = relaplt[5]
    rela_count = rela_size // 24

    # arm64 Android: .plt has 32-byte header, then 16-byte stubs
    # (verified empirically against this binary above).
    plt_vaddr = plt[3]
    plt_stub_base = plt_vaddr + 32

    found = {}
    for i in range(rela_count):
        ent = _s.unpack_from("<QQq", elf_bytes, rela_off + i * 24)
        r_offset, r_info, _ = ent
        sym_idx = r_info >> 32
        name = _sym_name(sym_idx)
        if name in sym_names:
            found[name] = plt_stub_base + i * 16
    return found


def patch(input_path: Path, output_path: Path) -> None:
    buf = bytearray(input_path.read_bytes())

    # Resolve PLT entries for the symbols our wrapper calls.
    plts = find_plt_for(bytes(buf), {"dlopen": 0, "dlsym": 0, "sleep": 0})
    for needed in ("dlopen", "dlsym", "sleep"):
        if needed not in plts:
            sys.exit(f"PLT entry for {needed!r} not found in {input_path}")
    plt_dlopen = plts["dlopen"]
    plt_dlsym  = plts["dlsym"]
    plt_sleep  = plts["sleep"]
    print(f"PLT dlopen={plt_dlopen:#x} dlsym={plt_dlsym:#x} sleep={plt_sleep:#x}")

    # Pad file to CAVE_FILE_OFFSET with zeros, then append wrapper bytes.
    if len(buf) > CAVE_FILE_OFFSET:
        sys.exit(f"input file is larger than CAVE_FILE_OFFSET={CAVE_FILE_OFFSET:#x}")
    buf.extend(b"\0" * (CAVE_FILE_OFFSET - len(buf)))

    wrapper = assemble_wrapper(
        base_vaddr=CAVE_VADDR,
        plt_dlopen=plt_dlopen, plt_dlsym=plt_dlsym, plt_sleep=plt_sleep,
        overlay_thread_main=OVERLAY_FN_VADDR,
    )
    print(f"wrapper size: {len(wrapper)} bytes")
    buf.extend(wrapper)
    buf.extend(b"\0" * (CAVE_SIZE - len(wrapper)))

    # Add a new PT_LOAD program header by repurposing PT_GNU_STACK.
    e_phoff, e_phentsize, phdrs = parse_phdrs(buf)
    gnu_stack_idx = None
    for i, p in enumerate(phdrs):
        if p[0] == PT_GNU_STACK:
            gnu_stack_idx = i
            break
    if gnu_stack_idx is None:
        sys.exit("PT_GNU_STACK header not found; cannot add new PT_LOAD without resizing phdr table")

    # phdr fields: p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align
    new_phdr = [
        PT_LOAD,
        PF_R | PF_X,
        CAVE_FILE_OFFSET,
        CAVE_VADDR,
        CAVE_VADDR,
        CAVE_SIZE,
        CAVE_SIZE,
        0x10000,
    ]
    write_phdr(buf, e_phoff, e_phentsize, gnu_stack_idx, new_phdr)
    print(f"replaced PT_GNU_STACK at phdr index {gnu_stack_idx} with new RX PT_LOAD "
          f"vaddr={CAVE_VADDR:#x} size={CAVE_SIZE:#x}")

    # Patch postAppSpecialize: redirect start_routine to our wrapper.
    new_adrp = enc_adrp(ADRP_X2_OFFSET, CAVE_VADDR, 2)
    cave_lo12 = CAVE_VADDR & 0xFFF
    new_add  = enc_add_imm(2, 2, cave_lo12)
    struct.pack_into("<I", buf, ADRP_X2_OFFSET, new_adrp)
    struct.pack_into("<I", buf, ADD_X2_OFFSET,  new_add)
    print(f"patched postAppSpecialize@{ADRP_X2_OFFSET:#x}: "
          f"adrp x2,{CAVE_VADDR:#x}; add x2,x2,#{cave_lo12:#x}")

    output_path.write_bytes(buf)
    print(f"wrote {output_path} ({len(buf)} bytes)")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args(argv)

    patch(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
