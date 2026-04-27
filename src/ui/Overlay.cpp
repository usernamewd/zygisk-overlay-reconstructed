// SPDX-License-Identifier: ISC
//
// Reconstructed ImGui overlay render loop.
//
// The binary statically links:
//   - Dear ImGui 1.92.2  (string `Dear ImGui 1.92.2 (19220)` + full backend)
//   - imgui_impl_opengl3 (#version 300 es, GLES3 path)
//
// The render thread (`@ 0x54300` in the binary) follows the canonical
// imgui_impl_opengl3 pattern:
//
//   1. Wait for the target app to create its EGL context (poll
//      eglGetCurrentContext()).
//   2. ImGui::CreateContext(), ImGui::StyleColorsDark(),
//      ImGui_ImplOpenGL3_Init("#version 300 es").
//   3. Loop: build io->DisplaySize from glGetIntegerv(GL_VIEWPORT); call
//      ImGui::NewFrame(); draw the menu; ImGui::Render(); save GL state;
//      ImGui_ImplOpenGL3_RenderDrawData(); restore GL state.
//
// We provide the canonical scaffold here; the per-app menu widgets that the
// original module drew are not statically recoverable (they are emitted from
// the OLLVM-obfuscated front-end code), so a placeholder demo window is
// rendered. Replace `draw_menu_contents()` with whatever the real overlay
// should display.

#include "Overlay.h"

#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <jni.h>
#include <pthread.h>
#include <unistd.h>

#include "../../third_party/imgui/imgui.h"
#include "../../third_party/imgui/backends/imgui_impl_opengl3.h"

#include "../runtime/Il2CppRuntime.h"
#include "../util/Log.h"
#include "../zygisk_module/Module.h"

namespace overlay::ui {

using overlay::OverlayModule;

namespace {

bool wait_for_egl_context() {
    for (int tries = 0; tries < 60; ++tries) {
        if (eglGetCurrentContext() != EGL_NO_CONTEXT) return true;
        sleep(1);
    }
    return false;
}

void draw_menu_contents() {
    // Placeholder UI. The original module's menu (toggles for the target
    // app's gameplay tweaks) is not statically recoverable from the
    // obfuscated binary; reconstruct it from your project's spec.
    if (ImGui::Begin("Overlay")) {
        ImGui::Text("Reconstructed scaffold");
        ImGui::Separator();
        ImGui::TextDisabled("Replace draw_menu_contents() with your menu.");
    }
    ImGui::End();
}

void update_display_size() {
    GLint vp[4]{};
    glGetIntegerv(GL_VIEWPORT, vp);
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize             = ImVec2(static_cast<float>(vp[2]),
                                        static_cast<float>(vp[3]));
    io.DisplayFramebufferScale = ImVec2(1.f, 1.f);
}

} // namespace

// JNIEnv attachment guard for the spawned UI thread. The JNIEnv we receive in
// onLoad lives on the zygote main thread; calling JNI from a different thread
// without AttachCurrentThread tears down the runtime. We attach lazily here
// (some configurations don't ever need JNI from the UI thread, in which case
// the cost is one nullptr check per frame) and detach on thread exit.
struct JniAttachment {
    JNIEnv* env = nullptr;
    bool    attached = false;

    explicit JniAttachment(JavaVM* vm) {
        if (vm == nullptr) return;
        // Already attached? GetEnv with the version we used at onLoad.
        jint rc = vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);
        if (rc == JNI_OK) return;
        if (rc == JNI_EDETACHED) {
            JavaVMAttachArgs args{JNI_VERSION_1_6, "ZygiskOverlayUI", nullptr};
            if (vm->AttachCurrentThread(&env, &args) == JNI_OK) {
                attached = true;
                return;
            }
        }
        env = nullptr;
        log::error("UI thread could not attach to JavaVM (rc=%d)", static_cast<int>(rc));
    }

    ~JniAttachment() {
        if (attached) {
            // Best-effort detach. If the VM is already gone (e.g. process is
            // tearing down) DetachCurrentThread returns an error that's fine
            // to ignore.
            if (auto vm = OverlayModule::GetJavaVM()) {
                vm->DetachCurrentThread();
            }
        }
    }
};

void* overlay_thread_main(void*) {
    log::info("overlay UI thread started");

    // Identify ourselves in tombstones / `ps -T` so it's obvious which thread
    // belongs to the module instead of inheriting whatever name zygote used.
    pthread_setname_np(pthread_self(), "zygisk-overlay");

    // 1. Attach to the JavaVM so any JNI use later in this thread is legal.
    JniAttachment jni(OverlayModule::GetJavaVM());
    (void)jni;

    // 2. Wait for the host app's EGL context to come up.
    if (!wait_for_egl_context()) {
        log::error("EGL context never became current; aborting UI thread");
        return nullptr;
    }

    // 3. Wait for libil2cpp.so + il2cpp_domain_get() to be valid before we
    //    let any IL2CPP-aware menu/hook code touch the runtime. On Magisk
    //    26.4 (Zygisk v4) the module is injected early enough that the
    //    IL2CPP runtime hasn't finished initialising yet — calling into it
    //    is what produced the SIGSEGV at libil2cpp.so+0x111b760 / fault
    //    addr 0x38 (null Il2CppDomain). On Magisk 30+ the timing happens to
    //    fall outside that window, which is why the same code "worked" on
    //    30+ but crashed on 26.4. Gating here makes both versions safe.
    if (!il2cpp::Runtime::Get().WaitForRuntime()) {
        log::warn("IL2CPP runtime never became ready; UI will still draw, "
                  "but any il2cpp_* lookups in draw_menu_contents() will be "
                  "no-ops. Did the host app actually load libil2cpp.so?");
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;          // disable imgui.ini writeback
    ImGui::StyleColorsDark();
    ImGui_ImplOpenGL3_Init("#version 300 es");

    for (;;) {
        update_display_size();

        ImGui_ImplOpenGL3_NewFrame();
        ImGui::NewFrame();
        draw_menu_contents();
        ImGui::Render();

        // GL state save -- matches the save/restore block visible in the
        // original render thread.
        GLint last_program; glGetIntegerv(GL_CURRENT_PROGRAM, &last_program);
        GLint last_texture; glGetIntegerv(GL_TEXTURE_BINDING_2D, &last_texture);
        GLint last_array_buffer; glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &last_array_buffer);
        GLint last_vertex_array; glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &last_vertex_array);

        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

        glUseProgram(last_program);
        glBindTexture(GL_TEXTURE_2D, last_texture);
        glBindBuffer(GL_ARRAY_BUFFER, last_array_buffer);
        glBindVertexArray(last_vertex_array);

        usleep(16'000); // ~60 FPS soft cap; matches the polling cadence of
                        // the original UI thread.
    }
}

} // namespace overlay::ui
