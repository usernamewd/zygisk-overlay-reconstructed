// SPDX-License-Identifier: ISC
//
// Reconstructed from the stripped, OLLVM-obfuscated arm64-v8a.so.
//
// The on-disk binary exports `zygisk_module_entry` and contains a Zygisk
// `ModuleBase` subclass with the following layout (verified from Ghidra):
//
//   vtable[0] = onLoad(Api*, JNIEnv*)               file off 0x57368
//   vtable[1] = preAppSpecialize(AppSpecializeArgs*) file off 0x57370
//   vtable[2] = postAppSpecialize(...)               file off 0x5741c
//   vtable[3] = preServerSpecialize(...)             file off 0x5745c (empty)
//   vtable[4] = postServerSpecialize(...)            file off 0x57460 (empty)
//
// `zygisk_module_entry` (file off 0x56984) constructs a `module_abi` with
// api_version=4 (matching ZYGISK_API_VERSION 4 from Magisk v26.x; the resulting
// .so still loads under newer Magisk versions because v5+ remains backward
// compatible with v4 modules). Then it calls api->registerModule(...) and, on
// success, dispatches `onLoad`.

#pragma once

#include "../../third_party/zygisk/zygisk.hpp"

namespace overlay {

// Subclass of zygisk::ModuleBase. The five virtual methods correspond 1:1 with
// the five vtable slots in the binary.
class OverlayModule : public zygisk::ModuleBase {
public:
    void onLoad(zygisk::Api* api, JNIEnv* env) override;
    void preAppSpecialize(zygisk::AppSpecializeArgs* args) override;
    void postAppSpecialize(const zygisk::AppSpecializeArgs* args) override;
    // pre/postServerSpecialize are intentionally unimplemented; the binary's
    // slots are 4-byte stubs that just `ret`.

private:
    zygisk::Api* api_  = nullptr;
    JNIEnv*      env_  = nullptr;
};

} // namespace overlay
