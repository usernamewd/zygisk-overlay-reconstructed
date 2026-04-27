# SPDX-License-Identifier: ISC
#
# CMakeLists.txt for the reconstructed Zygisk overlay module.
#
# Produces a `libarm64-v8a.so` whose NEEDED set, exports, and class layout
# mirror the stripped binary in reverse_engineering/original_arm64-v8a.so:
#   NEEDED:  liblog libandroid libEGL libGLESv2 libGLESv3 libc libm libdl
#   SONAME:  libarm64-v8a.so
#   exports: zygisk_module_entry  (+ Dobby's log_*, DobbyHook, CodePatch when
#            Dobby is statically linked with default visibility)
#
# Drive this from Android Studio / Gradle's externalNativeBuild, or from the
# raw NDK toolchain:
#
#   cmake -B build -S . \
#     -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK/build/cmake/android.toolchain.cmake \
#     -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \
#     -DCMAKE_BUILD_TYPE=Release
#   cmake --build build -j

cmake_minimum_required(VERSION 3.22)
project(zygisk_overlay CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ---------------------------------------------------------------------------
# Dear ImGui 1.92.2 (vendored unchanged in third_party/imgui)
# ---------------------------------------------------------------------------
add_library(imgui STATIC
    third_party/imgui/imgui.cpp
    third_party/imgui/imgui_draw.cpp
    third_party/imgui/imgui_tables.cpp
    third_party/imgui/imgui_widgets.cpp
    third_party/imgui/imgui_demo.cpp
    third_party/imgui/backends/imgui_impl_opengl3.cpp
)
target_include_directories(imgui PUBLIC
    third_party/imgui
    third_party/imgui/backends
)
target_compile_definitions(imgui PUBLIC IMGUI_IMPL_OPENGL_ES3=1)

# ---------------------------------------------------------------------------
# Dobby (real submodule under third_party/Dobby OR header-only stub).
#
# Latest Dobby master has several Linux/Android arm64 build regressions
# (renamed RuntimeModule.base->load_address mismatch, missing core/arch/Cpu.h
# in code-patch-tool-posix.cc, Mach-O-only PAGE/PAGEOFF syntax in the
# closure_bridge_arm64.asm). To keep CI deterministic, the default uses a
# header-only stub that exposes the same `DobbyHook`/`CodePatch`/etc. API as
# no-ops. Switch on the real Dobby with `-DUSE_REAL_DOBBY=ON` once you have
# a Dobby checkout/fork that builds cleanly on Android.
# ---------------------------------------------------------------------------
option(USE_REAL_DOBBY "Build against the vendored Dobby submodule (default: header stub)" OFF)

if(USE_REAL_DOBBY)
    set(DOBBY_BUILD_SHARED_LIBRARY OFF CACHE BOOL "" FORCE)
    set(DOBBY_BUILD_STATIC_LIBRARY ON  CACHE BOOL "" FORCE)
    set(DOBBY_GENERATE_SHARED      OFF CACHE BOOL "" FORCE)
    set(DOBBY_DEBUG                OFF CACHE BOOL "" FORCE)
    add_subdirectory(third_party/Dobby EXCLUDE_FROM_ALL)
    set(DOBBY_INCLUDE_DIR third_party/Dobby/include)
    set(DOBBY_LINK_TARGET dobby)
else()
    add_library(dobby_stub INTERFACE)
    target_include_directories(dobby_stub INTERFACE third_party/dobby_stub)
    set(DOBBY_INCLUDE_DIR third_party/dobby_stub)
    set(DOBBY_LINK_TARGET dobby_stub)
endif()

# ---------------------------------------------------------------------------
# The module .so itself
# ---------------------------------------------------------------------------
add_library(arm64-v8a SHARED
    src/zygisk_module/Module.cpp
    src/hooks/Hooks.cpp
    src/ui/Overlay.cpp
    src/runtime/Il2CppRuntime.cpp
)

target_include_directories(arm64-v8a PRIVATE
    third_party/zygisk
    ${DOBBY_INCLUDE_DIR}
)

target_link_libraries(arm64-v8a
    PRIVATE imgui ${DOBBY_LINK_TARGET}
            log android EGL GLESv2 GLESv3
)

# Match the original binary's link flags as closely as possible.
target_compile_options(arm64-v8a PRIVATE
    -Wall -Wextra -fvisibility=hidden -fvisibility-inlines-hidden
)
target_link_options(arm64-v8a PRIVATE
    -Wl,--gc-sections -Wl,--exclude-libs,ALL
)

# Target Android package the module injects into. Override at configure time
# via -DOVERLAY_TARGET_PACKAGE=... if needed.
if(NOT DEFINED OVERLAY_TARGET_PACKAGE)
    set(OVERLAY_TARGET_PACKAGE "com.embress.slclassic")
endif()
target_compile_definitions(arm64-v8a PRIVATE
    OVERLAY_TARGET_PACKAGE="${OVERLAY_TARGET_PACKAGE}")
