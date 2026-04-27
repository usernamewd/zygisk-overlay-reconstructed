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
# Dobby (vendored as submodule under third_party/Dobby)
# ---------------------------------------------------------------------------
set(DOBBY_BUILD_SHARED_LIBRARY OFF CACHE BOOL "" FORCE)
set(DOBBY_BUILD_STATIC_LIBRARY ON  CACHE BOOL "" FORCE)
set(DOBBY_GENERATE_SHARED      OFF CACHE BOOL "" FORCE)
set(DOBBY_DEBUG                OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/Dobby EXCLUDE_FROM_ALL)

# ---------------------------------------------------------------------------
# The module .so itself
# ---------------------------------------------------------------------------
add_library(arm64-v8a SHARED
    src/zygisk_module/Module.cpp
    src/hooks/Hooks.cpp
    src/ui/Overlay.cpp
)

target_include_directories(arm64-v8a PRIVATE
    third_party/zygisk
    third_party/Dobby/include
)

target_link_libraries(arm64-v8a
    PRIVATE imgui dobby
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
