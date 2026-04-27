# Reconstruction notes

This file documents how each part of the reconstructed source maps back to the
stripped binary at `reverse_engineering/original_arm64-v8a.so`. All addresses
below are file offsets in the original `.so`. Ghidra was loaded with the
default ELF image base of `0x100000`, so a binary file offset of `0xABCD`
corresponds to Ghidra address `0x10ABCD`.

## High-level shape

| Region (file offset) | Contents |
|----------------------|----------|
| `0x00cf10 – 0x056000` | libc++ + libc++abi static (NDK `std::__ndk1` namespace), exception-handling helpers (`__cxa_*`, `__dynamic_cast`, `__gxx_personality_v0`). Statically linked, not user code. |
| `0x056984 – 0x057cb8` | **User Zygisk-module scaffolding** (entry, 5 vtable methods, 4 trampolines). Reconstructed in `src/zygisk_module/Module.cpp`. |
| `0x057cb8 – 0x058070` | **User helper functions** referenced from the trampolines (small lambdas + `pre_app_specialize_impl` continuation). |
| `0x054300 – 0x056984` | **User ImGui render thread** (~9.8 KB). Reconstructed structurally in `src/ui/Overlay.cpp`; per-app menu code is OLLVM-obfuscated and not recoverable as readable source. |
| `0x058000 – 0x094000` | Mixed user code + libc++ template instantiations (lots of `std::__hash_table`, `std::vector`, `std::string` from the NDK libc++). |
| `0x094000 – 0x09c000` | **Dobby + Dobby's logging module**. Verified via every Dobby source-path string and the exported `DobbyHook`, `CodePatch`, `log_*` symbols. Use upstream Dobby as a drop-in. |
| `0x09c000 – 0x0c0000` | More libc++ instantiations + ImGui's freestanding helpers. |
| `0x0c0000 – 0x0e0000` | **Dear ImGui core** (`imgui.cpp`, `imgui_draw.cpp`, `imgui_widgets.cpp`, `imgui_tables.cpp`, `imgui_demo.cpp`). Statically linked. |
| `0x0e0000 – 0x0eb000` | **`imgui_impl_opengl3`** backend. |

## File-by-file mapping

### `src/zygisk_module/Module.cpp`

* `zygisk_module_entry` ↔ `0x56984` (4-byte branch then 308-byte body at
  `0x56988`). The body is the literal expansion of upstream
  `REGISTER_ZYGISK_MODULE` macro from `zygisk.hpp`:
  - two `__cxa_guard_acquire`/`release` pairs (static `OverlayModule`, static
    `module_abi`),
  - field stores `mov w9, 4 ; … ; stp x9, x10, [x8] ; stp q0, q1, [x8, 0x10]`
    that materialise `module_abi{api_version=4, impl=&module, preApp=…,
    postApp=…, preServer=…, postServer=…}`,
  - indirect call to `*(table+8)` = `registerModule`,
  - on success, indirect call to `*module->vptr[0]` = `onLoad`.
* `OverlayModule::onLoad`           ↔ `0x57368` (8 bytes, two stores).
* `OverlayModule::preAppSpecialize` ↔ `0x57370` (172 bytes).
* `OverlayModule::postAppSpecialize` ↔ `0x5741c` (64 bytes,
  `pthread_create` of `0x54300`).
* `pre_app_specialize_trampoline`   ↔ `0x57c88`.
* `post_app_specialize_trampoline`  ↔ `0x57c94`.
* `pre_server_specialize_trampoline` ↔ `0x57ca0`.
* `post_server_specialize_trampoline` ↔ `0x57cac`.
* `preServerSpecialize` / `postServerSpecialize` ↔ `0x5745c` / `0x57460`,
  both 4-byte `ret` stubs (we just inherit the no-op default).

### `src/hooks/Hooks.cpp`

* `pre_app_specialize_impl` ↔ `0x57464` (2 084 bytes, OLLVM CFF + opaque
  predicates + stack-XOR string-encoded literals). The encryption math
  reduces to a no-op at runtime because the controlling .bss globals
  `0x12d288 / 28c / 290 / 294 / 498` start zero-initialised and are not
  written before this function runs. The encoded byte tuples on the stack
  (e.g. `0xde8ed7d3dbd1db00, 0xb2eecfce, 0xc3ad`) are therefore the literal
  comparison targets; however they are non-printable, which is consistent
  with either an additional outer transformation we did not find, or the
  obfuscation pass having been parametrised at a build step we can't see.
  Bottom line: the **target package name string is not statically
  recoverable**. The reconstructed file accepts it through the build define
  `OVERLAY_TARGET_PACKAGE`.

* `install_native_hooks()` ↔ inferred from the Dobby usage pattern. Every
  hook site in the binary uses
  `DobbyHook(addr, replace, &orig)` (export at `0x94fe8`); see
  `reverse_engineering/all_functions_decompiled.c` for the call sites. The
  exhaustive hook table is **not statically recoverable** without knowing the
  target app's symbol set.

### `src/ui/Overlay.cpp`

* `overlay_thread_main` ↔ `0x54300` (9 860 bytes, OLLVM-flattened). The
  recoverable structure is:
  1. busy-poll `eglGetCurrentContext()` until non-null,
  2. one-shot `ImGui::CreateContext` + `ImGui_ImplOpenGL3_Init("#version 300 es")`,
  3. per-frame: read `glGetIntegerv(GL_VIEWPORT)` into `io.DisplaySize`,
     `ImGui::NewFrame`, build menu, `ImGui::Render`, save GL state,
     `ImGui_ImplOpenGL3_RenderDrawData`, restore GL state.
* The per-app menu widgets emitted between `NewFrame` and `Render` are
  obfuscated on top of the same opaque-predicate scheme that the gating
  function uses; they are present but not recoverable as readable source.
  We render a placeholder window so the build is functional.

### `src/util/Log.h`

* The four logging exports `log_set_level / log_switch_to_syslog /
  log_switch_to_file / log_internal_impl` (file offsets `0x95214 / 0x95220 /
  0x95230 / 0x95268`) are **Dobby's** logging module, not user code. They
  appear as exports because Dobby was statically linked with default
  visibility. They are not provided by us; pulling Dobby in as a static lib
  brings them along.
* `util/Log.h` is just a thin `__android_log_vprint` wrapper for the
  reconstructed user code itself.

## Statically-linked third party — exact upstream version match

| Library | Where in binary | Upstream pin |
|---------|-----------------|--------------|
| Dear ImGui | `0xc0000-0xe0000` core, `0xe0000-0xeb000` opengl3 backend | `ocornut/imgui` tag `v1.92.2` (matches the embedded `Dear ImGui 1.92.2 (19220)` string) |
| Dobby | `0x094000-0x09c000` | `jmpews/Dobby` master (matches the build-host source paths) |
| Zygisk header | n/a (header-only) | `topjohnwu/Magisk` `native/src/core/zygisk/api.hpp` (compatible with both v4 and v5 module ABIs; the binary declares v4) |

## What CANNOT be recovered from the binary alone

These items would need either runtime tracing of the running module, or full
symbolic execution of the OLLVM-obfuscated code paths:

1. **Target package name** (`OVERLAY_TARGET_PACKAGE`).
2. **Hook table** — the exact `(library, symbol-or-offset)` tuples that the
   module hooks inside the target app.
3. **Menu contents** — what `draw_menu_contents()` actually drew.
4. **Game-side memory pokes / structure offsets** that the hooks read or
   write.

For each, we ship a clearly-marked TODO at the corresponding source location
with a back-reference to the original-binary file offset, so a follow-up
session that has access to runtime traces can fill them in incrementally.
