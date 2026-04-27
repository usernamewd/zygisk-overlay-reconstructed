// SPDX-License-Identifier: ISC
//
// Reconstruction of the Zygisk module class and entry point from the binary.
// Cross-references to the stripped .so are written as `// @ <ghidra_addr>`
// comments. See `reverse_engineering/all_functions_decompiled.c` for the full
// Ghidra dump and `reverse_engineering/function_index.json` for the address ->
// (size, signature) mapping.

#include "Module.h"

#include <cstring>
#include <pthread.h>

#include "../hooks/Hooks.h"
#include "../ui/Overlay.h"
#include "../util/Log.h"

namespace overlay {

JavaVM* OverlayModule::s_vm_ = nullptr;

// @ 0x57368
// Recovered: simply stores api & env onto the module instance, exactly as
// expected for the trivial onLoad implementation in `zygisk-module-sample`.
//
// We additionally cache the JavaVM* so the overlay UI thread (spawned in
// postAppSpecialize) can AttachCurrentThread before making any JNI call.
void OverlayModule::onLoad(zygisk::Api* api, JNIEnv* env) {
    api_ = api;
    env_ = env;
    if (env != nullptr) {
        env->GetJavaVM(&s_vm_);
    }
}

// @ 0x57370
// Recovered: reads `args->nice_name` and `args->app_data_dir` via
// JNIEnv::GetStringUTFChars (api->v?->???? at offset +0x548 in the binary's
// `module_abi` vtable layout, which corresponds to JNIEnv::GetStringUTFChars
// in the standard JNI v1.6 jni_native_interface table), passes them to the
// per-process gating routine, then ReleaseStringUTFChars.
void OverlayModule::preAppSpecialize(zygisk::AppSpecializeArgs* args) {
    const char* nice_name    = nullptr;
    const char* app_data_dir = nullptr;
    if (args->nice_name) {
        nice_name = env_->GetStringUTFChars(args->nice_name, nullptr);
    }
    if (args->app_data_dir) {
        app_data_dir = env_->GetStringUTFChars(args->app_data_dir, nullptr);
    }

    hooks::pre_app_specialize_impl(env_, nice_name, app_data_dir); // @ 0x57464

    if (nice_name) {
        env_->ReleaseStringUTFChars(args->nice_name, nice_name);
    }
    if (app_data_dir) {
        env_->ReleaseStringUTFChars(args->app_data_dir, app_data_dir);
    }
}

// @ 0x5741c
// Recovered: if the gating decision (set by pre_app_specialize_impl) says we
// should inject into this process, spawn the overlay UI thread.
//
// The binary uses a global `ui_thread_handle` pthread_t (file off 0x12d490).
// The thread function lives at file off 0x54300 (Ghidra FUN_00154300, ~9.8 KB
// of OLLVM-flattened code that boils down to: sleep, eglGetCurrentContext,
// ImGui::NewFrame, draw the overlay, ImGui::Render, restore GL state).
void OverlayModule::postAppSpecialize(const zygisk::AppSpecializeArgs* args) {
    (void)args;
    // The condition byte at module+0x18 is set by pre_app_specialize_impl when
    // the package name matched the target. Replicating that behaviour:
    if (!hooks::injection_enabled()) {
        return;
    }
    static pthread_t tid;
    pthread_create(&tid, nullptr, ui::overlay_thread_main, nullptr); // @ 0x54300
}

} // namespace overlay

// ---------------------------------------------------------------------------
// zygisk_module_entry  @ 0x56984
//
// The binary's entry is the standard template from upstream `zygisk.hpp`:
//
//     extern "C" [[gnu::visibility("default")]] void
//     zygisk_module_entry(zygisk::api_table* table, JNIEnv* env) {
//         static OverlayModule m;
//         static zygisk::module_abi abi(&m);
//         if (!table->registerModule(table, &abi)) return;
//         m.onLoad(&api_proxy, env);
//     }
//
// The decompiler shows the two `__cxa_guard_acquire`/`release` pairs (one for
// the static module instance, one for the static module_abi) and then the
// indirect call through `*(table+8) = registerModule`. The success branch
// invokes the module's onLoad (vtable[0]).
//
// `REGISTER_ZYGISK_MODULE` from upstream zygisk.hpp expands to the exact same
// scaffolding, so we use the macro and let it emit the same code.
// ---------------------------------------------------------------------------
REGISTER_ZYGISK_MODULE(overlay::OverlayModule)
