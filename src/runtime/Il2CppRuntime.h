// SPDX-License-Identifier: ISC
//
// Helpers for safely interacting with a Unity IL2CPP runtime from a Zygisk
// module thread. Encapsulates two pieces of "wait for the host to be ready"
// machinery that the original obfuscated overlay_thread_main got wrong on
// Magisk 26.4 (Zygisk v4) and which caused a SIGSEGV inside libil2cpp.so:
//
//   * `WaitForRuntime()` — blocks until libil2cpp.so is dlopened *and*
//     `il2cpp_domain_get()` returns non-null. On v4 the module gets injected
//     earlier in app startup than on v5, so any unguarded call into IL2CPP
//     before this point dereferences half-initialised globals (the observed
//     null deref at offset +0x38 is the Il2CppDomain → root-domain field).
//
//   * `Resolve<T>(name)` — typed dlsym wrapper that only succeeds once
//     WaitForRuntime() has fired.
//
// Pattern in our overlay_thread_main:
//
//     auto& rt = il2cpp::Runtime::Get();
//     rt.WaitForRuntime();   // blocks until libil2cpp is fully up
//     auto class_from_name = rt.Resolve<decltype(&il2cpp_class_from_name)>("il2cpp_class_from_name");
//     ...
//
// The original binary just called the il2cpp_* exports unconditionally and
// relied on lucky timing.

#pragma once

#include <atomic>

namespace overlay::il2cpp {

class Runtime {
public:
    // Singleton accessor.
    static Runtime& Get();

    // Returns true once libil2cpp.so is loaded AND its runtime is initialised
    // enough that `il2cpp_domain_get()` returns a non-null Il2CppDomain*. Polls
    // every 50 ms; gives up after `timeout_ms` (default 60 s) and returns
    // false. Safe to call from any thread.
    bool WaitForRuntime(int timeout_ms = 60'000);

    // Looks up an exported symbol from libil2cpp.so. Returns nullptr if the
    // runtime hasn't come up yet (call WaitForRuntime() first) or if the
    // symbol is missing. Caller is expected to reinterpret_cast to the
    // appropriate function type.
    void* ResolveSymbol(const char* name);

    template <typename Fn>
    Fn Resolve(const char* name) {
        return reinterpret_cast<Fn>(ResolveSymbol(name));
    }

    // Cheap test that just asks "is the runtime *currently* up?" without
    // waiting. Useful for skip-this-frame checks inside the render loop.
    bool IsReady() const { return ready_.load(std::memory_order_acquire); }

private:
    Runtime() = default;
    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;

    void* il2cpp_handle_ = nullptr;
    std::atomic<bool> ready_{false};
};

} // namespace overlay::il2cpp
