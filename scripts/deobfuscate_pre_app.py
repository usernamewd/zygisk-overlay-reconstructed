#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
"""
Emulate pre_app_specialize_impl (file offset 0x57464, 2084 bytes) under
Unicorn-engine and dump every memory region that the function writes to as
bytes + ASCII. The OLLVM string-encryption pass in this binary materialises
each decrypted string by storing literal qwords onto the stack and then
XOR-ing them in place; both the literal and the post-XOR contents land in the
write trace, which lets us recover whatever string the function compares
against without ever running the .so on a real device.

Usage:
    python3 scripts/deobfuscate_pre_app.py [path/to/arm64-v8a.so]
        [--func-offset 0x57464] [--func-size 0x824]

Default function is pre_app_specialize_impl. Emulation skips JNI calls and
external libc helpers by stubbing them out at the BL/BLR site (we just return
plausible values: pointers come back as canned valid addresses, length-style
queries come back as small positive integers).
"""

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path

from elftools.elf.elffile import ELFFile

from unicorn import (
    Uc,
    UC_ARCH_ARM64,
    UC_MODE_ARM,
    UC_HOOK_MEM_WRITE,
    UC_HOOK_CODE,
    UC_PROT_ALL,
)
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_X8, UC_ARM64_REG_X19, UC_ARM64_REG_X29, UC_ARM64_REG_X30,
    UC_ARM64_REG_SP, UC_ARM64_REG_PC, UC_ARM64_REG_NZCV,
    UC_ARM64_REG_TPIDR_EL0,
)

# ---------------------------------------------------------------------------
# Memory layout
# ---------------------------------------------------------------------------
IMAGE_BASE = 0x100000   # matches Ghidra's default for this binary
STACK_BASE = 0x70000000
STACK_SIZE = 0x100000
HEAP_BASE  = 0x80000000
HEAP_SIZE  = 0x100000
EXTRA_BASE = 0x90000000  # canned strings (nice_name argument, app_data_dir)
EXTRA_SIZE = 0x10000
TLS_BASE   = 0xa0000000  # fake TLS (read by `mrs xN, tpidr_el0` for canary)
TLS_SIZE   = 0x10000


def load_elf(path: Path):
    """Map the ELF's PT_LOAD segments into Unicorn-friendly chunks."""
    with path.open("rb") as f:
        elf = ELFFile(f)
        segments = []
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            vaddr = seg["p_vaddr"] + IMAGE_BASE
            size  = seg["p_memsz"]
            data  = seg.data()
            if len(data) < size:
                data = data + b"\x00" * (size - len(data))
            segments.append((vaddr, size, data))
        return segments


def page_align(addr, size, page=0x1000):
    base = addr & ~(page - 1)
    end  = (addr + size + page - 1) & ~(page - 1)
    return base, end - base


def map_segments(uc: Uc, segments):
    mapped = []
    for vaddr, size, data in segments:
        base, msize = page_align(vaddr, size)
        try:
            uc.mem_map(base, msize, UC_PROT_ALL)
        except Exception:
            pass
        uc.mem_write(vaddr, data[:size])
        mapped.append((base, msize))
    return mapped


def dump_writes(writes, label="WRITES"):
    """Coalesce contiguous byte writes into runs and pretty-print."""
    if not writes:
        return
    # writes: dict[address] -> byte
    addrs = sorted(writes.keys())
    runs = []
    cur_start = addrs[0]
    cur_bytes = [writes[cur_start]]
    for a in addrs[1:]:
        if a == cur_start + len(cur_bytes):
            cur_bytes.append(writes[a])
        else:
            runs.append((cur_start, bytes(cur_bytes)))
            cur_start = a
            cur_bytes = [writes[a]]
    runs.append((cur_start, bytes(cur_bytes)))

    print(f"=== {label}: {len(runs)} run(s) ===")
    for start, data in runs:
        # only show runs containing >= 4 printable ASCII bytes anywhere
        ascii_blob = "".join(
            chr(b) if 0x20 <= b < 0x7f else "." for b in data
        )
        if len(data) < 2:
            continue
        print(f"  0x{start:010x}  len={len(data):4}  "
              f"hex={data[:64].hex()}{'...' if len(data) > 64 else ''}")
        print(f"                          ascii={ascii_blob[:80]}"
              f"{'...' if len(ascii_blob) > 80 else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary", nargs="?",
                    default="reverse_engineering/original_arm64-v8a.so")
    ap.add_argument("--func-offset", type=lambda s: int(s, 0), default=0x57464)
    ap.add_argument("--func-size",   type=lambda s: int(s, 0), default=0x824)
    ap.add_argument("--max-instr",   type=int, default=2_000_000)
    args = ap.parse_args()

    path = Path(args.binary)
    if not path.exists():
        print(f"ERR: binary not found: {path}", file=sys.stderr)
        return 1

    func_va = IMAGE_BASE + args.func_offset
    func_end = func_va + args.func_size

    print(f"[+] binary       = {path}  ({path.stat().st_size} bytes)")
    print(f"[+] func va      = 0x{func_va:x}")
    print(f"[+] func size    = 0x{args.func_size:x}  -> end 0x{func_end:x}")

    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)

    # Map the binary
    segments = load_elf(path)
    map_segments(uc, segments)

    # Map stack + heap + canned-strings region.
    uc.mem_map(STACK_BASE, STACK_SIZE, UC_PROT_ALL)
    uc.mem_map(HEAP_BASE,  HEAP_SIZE,  UC_PROT_ALL)
    uc.mem_map(EXTRA_BASE, EXTRA_SIZE, UC_PROT_ALL)
    uc.mem_map(TLS_BASE,   TLS_SIZE,   UC_PROT_ALL)
    # Stack canary lives at tpidr_el0+0x28 on aarch64 bionic. Pick any non-zero
    # value; the function compares it against itself before returning so the
    # exact value doesn't matter.
    uc.reg_write(UC_ARM64_REG_TPIDR_EL0, TLS_BASE)
    uc.mem_write(TLS_BASE + 0x28,
                 b"\xde\xad\xbe\xef\xca\xfe\xba\xbe")

    # Canned argument strings: pretend the app called us with these.
    nice_name_addr    = EXTRA_BASE + 0x100
    app_data_dir_addr = EXTRA_BASE + 0x800
    fake_jnienv_addr  = EXTRA_BASE + 0x1000

    uc.mem_write(nice_name_addr,    b"com.embress.slclassic\x00")
    uc.mem_write(app_data_dir_addr,
                 b"/data/data/com.embress.slclassic\x00")

    # Initial register state. Args (per the reconstructed signature):
    #   x0 = JNIEnv*           (we use a dummy non-null pointer)
    #   x1 = nice_name         (NUL-terminated)
    #   x2 = app_data_dir
    sp = STACK_BASE + STACK_SIZE - 0x1000
    uc.reg_write(UC_ARM64_REG_SP,  sp)
    uc.reg_write(UC_ARM64_REG_X29, sp)        # frame pointer
    uc.reg_write(UC_ARM64_REG_X30, 0xdeadbeef) # sentinel return address
    uc.reg_write(UC_ARM64_REG_X0,  fake_jnienv_addr)
    uc.reg_write(UC_ARM64_REG_X1,  nice_name_addr)
    uc.reg_write(UC_ARM64_REG_X2,  app_data_dir_addr)

    # Bucket writes by destination region for nicer dumps later.
    writes_stack = {}
    writes_bss   = {}
    writes_other = {}

    def hook_write(uc, access, address, size, value, _user):
        # value is signed; convert to unsigned bytes
        v = value & ((1 << (size * 8)) - 1)
        bs = v.to_bytes(size, "little")
        for i, b in enumerate(bs):
            a = address + i
            if STACK_BASE <= a < STACK_BASE + STACK_SIZE:
                writes_stack[a] = b
            elif IMAGE_BASE <= a < IMAGE_BASE + 0x300000:
                writes_bss[a] = b
            else:
                writes_other[a] = b
        return True

    uc.hook_add(UC_HOOK_MEM_WRITE, hook_write)

    # Code-trace hook: skip every BL/BLR (external function call) by emulating
    # "return zero / a small positive value" without descending into the
    # callee. This keeps emulation tractable for an OLLVM-flattened function
    # full of helpers that read .bss values.
    instr_count = [0]
    last_pc = [0]
    skipped_calls = [0]
    visited_bls = set()

    def hook_code(uc, address, size, _user):
        instr_count[0] += 1
        last_pc[0] = address
        if instr_count[0] >= args.max_instr:
            print(f"[!] hit instruction cap ({args.max_instr}); stopping at "
                  f"0x{address:x}")
            uc.emu_stop()
            return
        if address >= func_end + 0x10000 or address < IMAGE_BASE:
            print(f"[!] PC out of region: 0x{address:x}; stopping")
            uc.emu_stop()
            return
        # Read the instruction; if it's BL/BLR, fake the return.
        try:
            ins = struct.unpack("<I", uc.mem_read(address, 4))[0]
        except Exception:
            return
        # BL  imm  : 100101 imm26      (top 6 bits 0x25)
        # BLR Xn   : 1101011000111111000000 Rn 00000  (mask 0xfffffc1f, val 0xd63f0000)
        is_bl  = (ins >> 26) == 0b100101
        is_blr = (ins & 0xfffffc1f) == 0xd63f0000
        if is_bl or is_blr:
            skipped_calls[0] += 1
            visited_bls.add(address)
            # set x0 = 0 so callers see a "null pointer" / zero result, then
            # advance past the call instruction.
            uc.reg_write(UC_ARM64_REG_X0, 0)
            uc.reg_write(UC_ARM64_REG_PC, address + 4)
        # SVC #0 -> stop (we don't expect any in this function)
        elif ins == 0xd4000001:
            print(f"[!] SVC at 0x{address:x}; stopping")
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook_code)

    # Run.
    print("[+] starting emulation")
    try:
        uc.emu_start(func_va, 0xdeadbeef, count=args.max_instr)
    except Exception as e:
        print(f"[!] emulation stopped: {e}  pc=0x{last_pc[0]:x}  "
              f"instr={instr_count[0]}  skipped_calls={skipped_calls[0]}")
    else:
        print(f"[+] emulation finished  pc=0x{last_pc[0]:x}  "
              f"instr={instr_count[0]}  skipped_calls={skipped_calls[0]}")

    # Dump writes per region.
    dump_writes(writes_stack, "STACK WRITES")
    dump_writes(writes_bss,   "BSS / IMAGE WRITES")
    dump_writes(writes_other, "OTHER WRITES")

    # Specifically scan the stack writes for any contiguous ASCII run of
    # length >= 4 — that's where the decrypted strings will surface.
    print("\n=== ASCII runs in stack writes (>= 4 chars) ===")
    addrs = sorted(writes_stack.keys())
    if addrs:
        run_start = None
        run = []
        for a in addrs + [None]:
            b = writes_stack[a] if a is not None else None
            if (a is not None and run_start is not None
                    and a == run_start + len(run)
                    and 0x20 <= b < 0x7f):
                run.append(b)
            else:
                if run_start is not None and len(run) >= 4:
                    print(f"  0x{run_start:010x}  "
                          f"{bytes(run).decode('ascii', errors='replace')!r}")
                if a is not None and 0x20 <= b < 0x7f:
                    run_start = a
                    run = [b]
                else:
                    run_start = None
                    run = []

    return 0


if __name__ == "__main__":
    sys.exit(main())
