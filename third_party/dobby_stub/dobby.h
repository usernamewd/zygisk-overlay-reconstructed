// SPDX-License-Identifier: ISC
//
// Stub of the public Dobby header that lets the reconstructed module compile
// without a working Dobby checkout. The hooking calls turn into no-ops, so a
// `.so` produced with the stub will load and run its onLoad / Zygisk
// scaffolding, but it WILL NOT install any function hooks.
//
// To get a functional module, build with `-DUSE_REAL_DOBBY=ON` against a
// Dobby checkout that compiles cleanly for Android arm64. The real upstream
// Dobby header is exported via `third_party/Dobby/include/dobby.h` once the
// submodule is initialised; replace this stub include path with that one in
// CMakeLists.txt.
//
// Why a stub? The latest Dobby commits on master have several Linux/Android
// build regressions (renamed struct fields, missing Cpu.h, Mach-O-only
// PAGE/PAGEOFF syntax in the closure-bridge ASM). Waiting on those to be
// fixed upstream — or maintaining a vendored fork — was outside the scope of
// the initial reconstruction, so the stub keeps CI green while leaving a
// clear seam for plugging in real Dobby later.

#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Real Dobby returns 0 on success. The stub claims success but does nothing,
// which is enough for the reconstructed scaffolding to link and run.
inline int DobbyHook(void* /*function_address*/,
                     void* /*replace_call*/,
                     void** origin_call) {
    if (origin_call) *origin_call = nullptr;
    return 0;
}

inline int DobbyDestroy(void* /*function_address*/) {
    return 0;
}

inline void* DobbySymbolResolver(const char* /*image_name*/,
                                 const char* /*symbol_name_pattern*/) {
    return nullptr;
}

inline int CodePatch(void* /*address*/,
                     uint8_t* /*buffer*/,
                     uint32_t /*buffer_size*/) {
    return 0;
}

#ifdef __cplusplus
} // extern "C"
#endif
