// SPDX-License-Identifier: ISC
//
// Reconstructed Dobby-based hook installation.
//
// The binary statically links Dobby (jmpews/Dobby) and uses its public
// `DobbyHook` / `CodePatch` entry points. The exported `log_*` helpers
// (log_set_level, log_switch_to_syslog, log_switch_to_file, log_internal_impl)
// are part of Dobby's own logging module and are surfaced as exports because
// Dobby was statically linked with default visibility.
//
// Dobby is included as a git submodule under `third_party/Dobby`.

#include "Hooks.h"

#include <atomic>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>

// Resolved by CMake to either the real Dobby submodule header
// (third_party/Dobby/include) or the header-only stub
// (third_party/dobby_stub). Either way the public API surface is the same.
#include <dobby.h>
#include "../util/Log.h"

// The target Android package this module is meant to inject into.
// Build-time overridable via -DOVERLAY_TARGET_PACKAGE=...
#ifndef OVERLAY_TARGET_PACKAGE
#define OVERLAY_TARGET_PACKAGE "com.embress.slclassic"
#endif

namespace overlay::hooks {

namespace {

std::atomic<bool> g_injection_enabled{false};

// Container for the original (pre-hook) function pointers. Replicates the
// `static void* orig_*` pattern that appears throughout the decompilation.
struct OrigTable {
    // Add fields per hook site; the reconstructed binary's hook sites are
    // marked in reverse_engineering/all_functions_decompiled.c with the
    // `DobbyHook(target, replace, &orig)` calling convention.
};
OrigTable g_orig{};

} // namespace

bool injection_enabled() {
    return g_injection_enabled.load(std::memory_order_acquire);
}

// Looks up a symbol by name inside an already-loaded .so. The binary uses
// the standard `dlsym(RTLD_DEFAULT, ...)` flow plus a fallback that walks
// /proc/self/maps to handle libraries loaded via the linker's namespace
// isolation (Android Q+). The fallback is the well-known "fake_dlopen_with_path"
// helper whose symbol leaks into the export table of the binary.
void* resolve_symbol(const char* lib_basename, const char* symbol) {
    if (void* handle = dlopen(lib_basename, RTLD_NOW | RTLD_NOLOAD)) {
        if (void* sym = dlsym(handle, symbol)) {
            return sym;
        }
    }
    // TODO(reconstruction): the binary additionally uses a custom maps-based
    // symbol resolver (see reverse_engineering/all_functions_decompiled.c
    // around 0x6c000-0x70000). Drop in your preferred KittyMemory /
    // fake_dlopen replacement here if `dlopen` returns nullptr.
    return nullptr;
}

// Installs the inline hooks. The reconstructed binary's hook table cannot be
// recovered exhaustively from a stripped + obfuscated build; it must be
// re-derived from the target app's symbol set. The wiring below is the
// canonical pattern used at every hook site in the binary.
void install_native_hooks() {
    // Example template — replace with the actual hook list once known.
    //
    // void* target = resolve_symbol("libtarget.so", "TargetSymbol");
    // if (target) {
    //     DobbyHook(target,
    //               reinterpret_cast<dobby_dummy_func_t>(&hk_TargetSymbol),
    //               reinterpret_cast<dobby_dummy_func_t*>(&g_orig.TargetSymbol));
    // }

    log::info("install_native_hooks: TODO (see reverse_engineering/ for the "
              "list of hook call sites in the original binary)");
}

void pre_app_specialize_impl(JNIEnv* env,
                             const char* nice_name,
                             const char* app_data_dir) {
    (void)env;
    (void)app_data_dir;

    // The original binary compares `nice_name` against an XOR-encoded package
    // table. Because the table's runtime decryption math collapses to a no-op
    // (see Hooks.h commentary), the encoded bytes are the comparison target;
    // however, those bytes are non-printable and the actual ASCII package
    // name cannot be recovered without instrumented runtime data.
    //
    // Drop in the target package name via the build define.
    if (!nice_name || std::strcmp(nice_name, OVERLAY_TARGET_PACKAGE) != 0) {
        return;
    }

    g_injection_enabled.store(true, std::memory_order_release);
    install_native_hooks();
}

} // namespace overlay::hooks
