# Zygisk Overlay – reconstructed source tree

Reconstruction of `arm64-v8a.so` (1 170 536 bytes, ELF aarch64, stripped,
OLLVM-obfuscated user code).  The original binary is preserved verbatim under
`reverse_engineering/original_arm64-v8a.so`.

## What the original binary is

A Zygisk module that injects a Dear ImGui (OpenGL ES 3) overlay into a target
Android process. Confirmed from the binary itself:

| Component | Evidence |
|-----------|----------|
| Zygisk module API v4 (Magisk 26.x) | `zygisk_module_entry` export, `api_version=4` literal in entry stub at file off `0x56984`. The vendored module-API header under `third_party/zygisk/zygisk.hpp` is the v4 release from `topjohnwu/zygisk-module-sample`. |
| Dear ImGui **1.92.2** | string `Dear ImGui 1.92.2 (19220)` in `.rodata` |
| `imgui_impl_opengl3` backend | string `imgui_impl_opengl3`, `#version 300 es`, full `ImGui_ImplOpenGL3_*` symbols |
| Dobby (jmpews/Dobby) | `DobbyHook`, `CodePatch`, `FunctionInlineReplaceRouting`, `ARM64InstructionRelocation`, `MemoryArena`, all source-path strings `/Users/runner/work/Dobby/Dobby/...` |
| Dobby logging module | `log_set_level`, `log_switch_to_syslog`, `log_switch_to_file`, `log_internal_impl` (calls `__android_log_vprint(4, "Dobby", …)`) |
| `fake_dlopen` linker bypass | string `fake_dlopen_with_path` |
| Built with Android NDK | `clang version 7.0.0/7.0.2`, libc++ namespace `std::__ndk1` |

NEEDED libraries: `liblog libandroid libEGL libGLESv2 libGLESv3 libc libm libdl`.
SONAME: `libarm64-v8a.so`.

## Repository layout

```
src/
  zygisk_module/Module.{h,cpp}   # OverlayModule + REGISTER_ZYGISK_MODULE
  hooks/Hooks.{h,cpp}            # pre_app_specialize gating + Dobby wiring
  ui/Overlay.{h,cpp}             # ImGui render thread (entered from postAppSpecialize)
  util/Log.h                     # Thin __android_log wrapper (NOT Dobby's logger)

third_party/
  imgui/                         # vendored as submodule, pinned to v1.92.2
  Dobby/                         # vendored as submodule (master)
  zygisk/zygisk.hpp              # Zygisk module API v4 header (Magisk 26.x)
  dobby_stub/dobby.h             # header-only no-op Dobby (CI default)

reverse_engineering/
  original_arm64-v8a.so          # the input artifact, untouched
  all_functions_decompiled.c     # Ghidra headless decompile of all 1298 functions
  function_index.json            # addr -> {name, size, signature}
  strings_dump.txt               # `strings -n 8` of the binary

CMakeLists.txt                   # primary build (works under NDK toolchain)
Android.mk                       # alternative ndk-build manifest
docs/RECONSTRUCTION_NOTES.md     # what was recovered, what was inferred, what is still TODO
```

## Building

You need Android NDK r25+ (or Android Studio with NDK installed):

```sh
git submodule update --init --recursive
cmake -B build -S . \
    -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK/build/cmake/android.toolchain.cmake \
    -DANDROID_ABI=arm64-v8a \
    -DANDROID_PLATFORM=android-26 \
    -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

The default target package is `com.embress.slclassic`. Override at configure
time with `-DOVERLAY_TARGET_PACKAGE=other.package.name` if needed.

Output is `build/libarm64-v8a.so`. To package as a Magisk/Zygisk module:

```
zygisk-overlay.zip
├── module.prop
├── post-fs-data.sh
└── zygisk/
    ├── arm64-v8a.so          # the build output
    └── armeabi-v7a.so        # not produced here; original is arm64-only
```

## What was reconstructed vs. inferred vs. left as TODO

See [`docs/RECONSTRUCTION_NOTES.md`](docs/RECONSTRUCTION_NOTES.md) for the full
breakdown. Short version:

* **Recovered 1:1**: the Zygisk module entry stub, the 5 vtable methods, the
  4 trampoline functions, the Dobby + logging + libc++ scaffolding (which is
  exactly upstream code), the ImGui + imgui_impl_opengl3 (vendored from
  upstream at the matching version).
* **Recovered structurally** (right shape, function bodies are skeletons):
  the package-name gating, the Dobby hook installation pattern, the
  postAppSpecialize → pthread_create → ImGui render loop sequence.
* **Not recoverable from a stripped + OLLVM-obfuscated binary alone**: the
  exact target package string, the list of hook addresses inside the target
  app, and the menu widget code. These are typed up as documented TODO sites
  with explicit references back to the Ghidra decompile.
