// SPDX-License-Identifier: ISC
//
// Implementation of overlay::il2cpp::Runtime — see Il2CppRuntime.h for the
// rationale.

#include "Il2CppRuntime.h"

#include <chrono>
#include <dlfcn.h>
#include <thread>

#include "../util/Log.h"

namespace overlay::il2cpp {

namespace {

// Forward-declare just the IL2CPP entry points we touch here, so we don't have
// to vendor the full il2cpp-api headers. Symbol shapes match Unity 2019.4.x.
struct Il2CppDomainOpaque;
using Il2CppDomain = Il2CppDomainOpaque;

using il2cpp_domain_get_fn = Il2CppDomain* (*)();

constexpr const char* kIl2CppSoName = "libil2cpp.so";

// Try to acquire a handle to libil2cpp.so without forcing a load — we want to
// piggy-back on the host's own load, not race it. RTLD_NOLOAD returns nullptr
// if the library isn't already in the process; once Unity has loaded it, this
// returns a valid handle.
void* TryGetIl2CppHandle() {
    return dlopen(kIl2CppSoName, RTLD_NOLOAD | RTLD_LAZY);
}

} // namespace

Runtime& Runtime::Get() {
    static Runtime instance;
    return instance;
}

bool Runtime::WaitForRuntime(int timeout_ms) {
    if (ready_.load(std::memory_order_acquire)) return true;

    using clock = std::chrono::steady_clock;
    const auto deadline = clock::now() + std::chrono::milliseconds(timeout_ms);

    log::info("waiting for libil2cpp.so + il2cpp_domain_get()...");

    while (clock::now() < deadline) {
        void* h = TryGetIl2CppHandle();
        if (h) {
            auto domain_get = reinterpret_cast<il2cpp_domain_get_fn>(
                dlsym(h, "il2cpp_domain_get"));
            if (domain_get) {
                Il2CppDomain* domain = domain_get();
                if (domain != nullptr) {
                    il2cpp_handle_ = h;
                    ready_.store(true, std::memory_order_release);
                    log::info("libil2cpp.so runtime is up; domain=%p", domain);
                    return true;
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    log::error("libil2cpp.so runtime not up after %d ms; giving up", timeout_ms);
    return false;
}

void* Runtime::ResolveSymbol(const char* name) {
    if (!ready_.load(std::memory_order_acquire) || il2cpp_handle_ == nullptr) {
        return nullptr;
    }
    return dlsym(il2cpp_handle_, name);
}

} // namespace overlay::il2cpp
