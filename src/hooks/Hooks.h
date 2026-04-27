// SPDX-License-Identifier: ISC
#pragma once

#include <jni.h>

namespace overlay::hooks {

// Set by `pre_app_specialize_impl` if the current process matches the target
// package list. Read by `OverlayModule::postAppSpecialize` to decide whether
// to spawn the UI thread.
bool injection_enabled();

// @ 0x57464  (FUN_00157464, 2084 bytes, OLLVM control-flow flattened)
//
// Original responsibility (recovered from data flow + strings):
//   1. Compare the JNI-decoded `nice_name` against an obfuscated table of
//      target Android package name(s). The package strings are stored on the
//      stack as XOR-encrypted byte tuples (e.g. `0xde8ed7d3dbd1db00,
//      0xb2eecfce, 0xc3ad`) and decrypted in-place with a runtime constant
//      derived from a handful of zero-initialised .bss globals
//      (DAT_22d288, 28c, 290, 294, 298, 498) via the formula
//        v = (ucvtf(D298) - 2*ucvtf(D288)) * K * (uvar - D294)
//      where `uvar = (D28c + 7) / D290`. Because D290 starts at zero, `uvar`
//      degenerates to zero and the math collapses, leaving the stack bytes
//      unchanged at runtime; the obfuscation pass is therefore effectively a
//      structural decoy in static analysis.
//   2. If the decoded name matches the target, save `(env, app_data_dir)` to
//      a singleton, set `injection_enabled() = true`, and call
//      `install_native_hooks()` to wire up Dobby hooks against the target
//      app's native libraries.
//
// The exact target-package string and the names of the hooked symbols cannot
// be recovered statically without runtime trace data; both are emitted as
// `OVERLAY_TARGET_PACKAGE` and `OVERLAY_HOOK_SYMBOLS` build-time defines so
// that downstream operators can fill them in.
void pre_app_specialize_impl(JNIEnv* env,
                             const char* nice_name,
                             const char* app_data_dir);

// Installs the inline hooks against the target process. Reconstructed from
// the Dobby usage pattern in the binary (every hook site goes through
// `DobbyHook(addr, replace, &orig)`).
void install_native_hooks();

} // namespace overlay::hooks
