# SPDX-License-Identifier: ISC
#
# Alternative ndk-build manifest for the same target. Use either CMake (top
# level) OR ndk-build with this file; do not mix them.

LOCAL_PATH := $(call my-dir)

# -- Dear ImGui static lib --------------------------------------------------
include $(CLEAR_VARS)
LOCAL_MODULE := imgui
LOCAL_SRC_FILES := \
    third_party/imgui/imgui.cpp \
    third_party/imgui/imgui_draw.cpp \
    third_party/imgui/imgui_tables.cpp \
    third_party/imgui/imgui_widgets.cpp \
    third_party/imgui/imgui_demo.cpp \
    third_party/imgui/backends/imgui_impl_opengl3.cpp
LOCAL_C_INCLUDES := \
    $(LOCAL_PATH)/third_party/imgui \
    $(LOCAL_PATH)/third_party/imgui/backends
LOCAL_CPPFLAGS := -std=c++17 -DIMGUI_IMPL_OPENGL_ES3=1 -fvisibility=hidden
include $(BUILD_STATIC_LIBRARY)

# -- The module .so itself --------------------------------------------------
include $(CLEAR_VARS)
LOCAL_MODULE := arm64-v8a
LOCAL_SRC_FILES := \
    src/zygisk_module/Module.cpp \
    src/hooks/Hooks.cpp \
    src/ui/Overlay.cpp
LOCAL_C_INCLUDES := \
    $(LOCAL_PATH)/third_party/zygisk \
    $(LOCAL_PATH)/third_party/Dobby/include \
    $(LOCAL_PATH)/third_party/imgui \
    $(LOCAL_PATH)/third_party/imgui/backends
LOCAL_CPPFLAGS := -std=c++17 -fvisibility=hidden -fvisibility-inlines-hidden \
    -DOVERLAY_TARGET_PACKAGE=\"com.embress.slclassic\"
LOCAL_STATIC_LIBRARIES := imgui dobby
LOCAL_LDLIBS := -llog -landroid -lEGL -lGLESv2 -lGLESv3
LOCAL_LDFLAGS := -Wl,--gc-sections -Wl,--exclude-libs,ALL
include $(BUILD_SHARED_LIBRARY)
