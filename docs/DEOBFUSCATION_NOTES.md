# Deobfuscation notes (`pre_app_specialize_impl`)

This documents what the Unicorn-engine harness in
`scripts/deobfuscate_pre_app.py` produced when emulating the OLLVM-obfuscated
gating function at file offset `0x57464` (Ghidra `FUN_00157464`, 2 084 bytes).

## TL;DR

* The harness successfully runs the function: 2 857 instructions execute and
  the function returns cleanly to the sentinel return address.
* But: **none of the encrypted byte blobs decrypt to readable strings under
  emulation alone**. The XOR-decryption math depends on five `.bss` globals
  (`DAT_22d288`, `_28c`, `_290`, `_294`, `_298` — and `_498` for an opaque
  predicate) that are initialised **outside** this function, in a different
  code path that the harness currently stubs out.
* The script is left in as a starting point; the rest of this note documents
  exactly what's needed to take the next step.

## What the function looks like

The function decrypts a fixed 23-byte blob located at `.rodata` offset
`0xc5d5c` and `0xc5d6b` (loaded with `ldr q0, [x9]; ldur x9, [x9, 0xf]` and
stored on the stack with `str q0, [sp, 0x10]; stur x9, [sp, 0x1f]`):

```
0xc5d5c..0xc5d76 (23 bytes, all non-printable):
  00 da d5 d6 92 d8 d3 dd b2 a4 b1 b0 ea b6 aa a4 a4 a8 b9 b8 a5 ae ce
```

The decryption loop body, lifted from the Ghidra decompile, is per-byte:

```c
m_i = (char)(int)((ucvtf(D298) - 2*ucvtf(D288))
                  * K_i
                  * (uVar - D294));
blob[i] = m_i + blob[i] + (m_i & blob[i]) * -2;        // == blob[i] ^ m_i
```

`K_i` is one of ~16 distinct double-precision multipliers stored at
`0xc5910..0xc5990` (values `184.0, 185.0, 186.0, ..., 189.0` in roughly
ascending order, with a couple of out-of-range constants mixed in). The
control flow is OLLVM-flattened so each byte position references a different
`K_i` via opaque predicates of the form `D288 + D498*M_i == 3` (where `M_i`
is a per-position constant: `0xc, 0x12, 0x18, 0x1b, 0x1e, 0x21, 0x24, ...`).

## Confirmed shape of the decryption

Working backwards from the known target (`com.embress.slclassic`) gives the
required XOR mask per byte:

```
position  enc  expect  m_i = enc XOR expect
   0       00    'c'      0x63
   1       da    'o'      0xb5
   2       d5    'm'      0xb8
   3       d6    '.'      0xf8
   4       92    'e'      0xf7
   5       d8    'm'      0xb5
   6       d3    'b'      0xb1
   7       dd    'r'      0xaf
   8       b2    'e'      0xd7
   9       a4    's'      0xd7
  10       b1    's'      0xc2
  11       b0    '.'      0x9e
  12       ea    's'      0x99
  13       b6    'l'      0xda
  14       aa    'c'      0xc9
  15       a4    'l'      0xc8
  16       a4    'a'      0xc5
  17       a8    's'      0xdb
  18       b9    's'      0xca
  19       b8    'i'      0xd1
  20       a5    'c'      0xc6
  21       ae    \0       0xae
```

So the mask sequence we need to reproduce is:
`63 b5 b8 f8 f7 b5 b1 af d7 d7 c2 9e 99 da c9 c8 c5 db ca d1 c6 ae`.

Per the formula above, this mask must equal `(char)(int)((D298-2*D288) *
K_i * (uVar-D294))`. With the multipliers `K_i` known (constant table at
`0xc5910`), the unknowns are the four globals `D288`, `D294`, `D298`, and
the value of `uVar = (D28c+7)/D290 if D290!=0 else 0`. Concretely:

* `(D298 - 2*D288)` is a constant scalar `S`.
* `(uVar - D294)` is another constant scalar `T`.
* `m_i = (char)(S * T * K_i)` for each `i`.

Given that `m_i / K_i` should be approximately the same scalar `(S*T)` for
every byte, the values of `K_i` and the order in which they're applied per
byte position can be back-solved from the mask sequence. **This is the
follow-up step I'd recommend if you want a clean static recovery without
ever running the binary on a real device.**

## Why the current emulator harness doesn't pop the strings

The `.bss` globals stay zero in the harness because:

1. The single `INIT_ARRAY` entry (`0xcf1c`, 52 bytes) only initialises a
   `std::string` object at `0x12d310` — none of the obfuscation globals.
2. The only writes to `D288 / D298` in the binary are:
   * `0x5c78c` — `str x9, [x?, 0x288]` inside `FUN_0015c5a0` (~580 bytes).
   * `0x74bb8` and `0x77fa4` — `str d1` / `str w9` to `[x?, 0x298]` inside
     larger user-helper functions.
   These functions are reached via call paths the harness deliberately
   stubs out (`UC_HOOK_CODE` rewrites every `BL`/`BLR` to "set x0=0; pc+=4"
   so emulation stays linear and tractable).

To make the strings drop out, the harness needs one of:

* **Option A** (easy, fragile): pre-set `D288 / D290 / D294 / D298` to the
  values that solve the algebraic relation above, before calling
  `pre_app_specialize_impl`. This requires solving the relation once.
* **Option B** (more work, more general): drop the BL/BLR stubbing, map a
  fake PLT region for the external symbols (`__stack_chk_*`, `dlopen`,
  `pthread_*`, JNI methods), and let the binary's own static-libc++ /
  Dobby code run normally. Then the chain that initialises the globals
  fires for free.
* **Option C** (cheap, narrow): just brute-force search the 4-tuple
  `(D288, D290, D294, D298)` over a sensible range (each byte 0..255), call
  the decryption inline in Python, and accept any tuple that produces 22+
  printable ASCII bytes ending in `\0`. This is `~256^3 ≈ 16M` configs, a
  few minutes on one CPU.

All three are within reach; the script is structured so that any of them
can be plugged in by replacing the `# pre_app_specialize_impl` setup block.
