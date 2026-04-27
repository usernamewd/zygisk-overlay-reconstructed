# Magisk 26.4 IL2CPP timing crash — root cause + fix

## Crash that prompted this

```
pid: 1600, tid: 1664, name: >>> com.google.android.apps.turbo <<<
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x38
backtrace:
  #00 libil2cpp.so + 0x111b760
  #01 libil2cpp.so + 0x111e340
  #02 libil2cpp.so + 0x111e518
  #03 libil2cpp.so + 0x115cb5c
  #04 libil2cpp.so + 0x212b960
  #05 libnative.so + 0x154610
  #06 libc __pthread_start
  #07 libc __start_thread
```

Process: `com.embress.slclassic` (Unity 2019.4.22f1, IL2CPP backend, arm64).
Magisk: 26.4 (Zygisk API v4). On Magisk 30.0+ (v5) the same module ran
without crashing.

## Root cause

`libnative.so + 0x154610` maps to file offset `0x54610` in the original
`arm64-v8a.so`, which is **inside `overlay_thread_main`** (file offset
`0x54300`, 9.8 KB OLLVM-flattened) — about 0x310 bytes in. So the overlay UI
thread is the caller into IL2CPP at the moment of the crash.

`SIGSEGV @ fault addr 0x38` is a null-pointer dereference of an offset-`+0x38`
field. In Unity 2019 IL2CPP that pattern is a null `Il2CppDomain*` /
`Il2CppImage*` being passed into a class/method lookup helper which then
reads e.g. `image->assembly` at `+0x38`.

**Why null on 26.4 but populated on 30.0+:** Zygisk module attachment
timing differs between the two Magisk versions. v4 (26.4) hooks the zygote
specialize path earlier than v5+, so by the time the module's
`postAppSpecialize` fires `pthread_create(overlay_thread_main, …)`, the
host app's `libil2cpp.so` is loaded but `il2cpp_init()` / domain creation
has not finished. The original obfuscated `overlay_thread_main` only
busy-waited on `eglGetCurrentContext()` (which goes non-null much earlier
in Unity startup) and then unconditionally called `il2cpp_*` exports. On
v5+ those calls happened to land just after the runtime came up, so it
"worked".

## The fix (this repo)

Implemented in `src/runtime/Il2CppRuntime.{h,cpp}` and called from
`src/ui/Overlay.cpp::overlay_thread_main`.

`overlay::il2cpp::Runtime::WaitForRuntime()`:

1. Polls `dlopen("libil2cpp.so", RTLD_NOLOAD | RTLD_LAZY)` every 50 ms.
2. Once that returns a handle, resolves `il2cpp_domain_get` and calls it.
3. Only declares the runtime "ready" when the returned `Il2CppDomain*` is
   non-null.
4. Blocks until ready or until a configurable timeout (default 60 s).

Two additional hardenings are wired in alongside the wait:

* `pthread_setname_np(self, "zygisk-overlay")` so the UI thread shows up
  with a recognisable name in tombstones / `ps -T` instead of inheriting
  whatever zygote set on its caller (which is what produced the
  `>>> com.google.android.apps.turbo <<<` thread name in the original
  tombstone).

* `JavaVM::AttachCurrentThread` from inside the spawned thread, since the
  `JNIEnv*` captured in `onLoad` is only valid for the zygote main thread.
  The `JavaVM*` itself is shared; `Module::onLoad` now calls
  `env->GetJavaVM(&s_vm_)` and exposes it via
  `OverlayModule::GetJavaVM()`. The UI thread builds a stack-allocated
  `JniAttachment` guard that attaches lazily and detaches in its
  destructor.

## What this does and does not fix

| Crash class                                                  | Fixed by Flavor 3 |
|--------------------------------------------------------------|-------------------|
| Null `Il2CppDomain` / `Il2CppImage` from early IL2CPP lookup | YES               |
| JNI calls from unattached UI thread                          | YES               |
| Hooks installed before target library is dlopened            | NO (separate; would need analogous wait in `Hooks.cpp`) |
| Bugs inside `draw_menu_contents()` or the hook bodies        | NO (still TODO sites) |

If the actual menu/hook code (which we couldn't statically recover from
the obfuscated original) does its own IL2CPP queries, it should call
`overlay::il2cpp::Runtime::Get().Resolve<...>(...)` instead of `dlsym`-ing
the symbols directly — that helper returns nullptr until WaitForRuntime
has succeeded, so individual lookups also can't outrun the runtime.

## Why this is the right place to fix it

The user's working module on Magisk 30.0+ is in fact relying on luck.
Putting the wait in our code makes both Magisk 26.4 and 30+ safe and
removes the reliance on injection-time ordering. A "modified Magisk" fork
that backports the 30.x timing into 26.4 would also fix this, but at the
cost of every user having to flash a custom Magisk — strictly worse
ergonomics.

## Binary-patch path for the original .so

If you can't or don't want to rebuild from source (e.g. the menu/hook
bodies in the original obfuscated binary are still your shipping copy and
nothing in this repo replaces them), the same logical fix is also
delivered as a **binary patch** of the original `.so`.
`scripts/patch_il2cpp_wait.py` produces a modified copy that:

1. Adds a small RX code-cave (one page, `vaddr=0x140000`,
   `file_offset=0x120000`) by repurposing the existing `PT_GNU_STACK`
   program-header slot into a new `PT_LOAD`. No file relayout, no section
   header changes, no resigning of any sort needed.

2. Writes an aarch64 wrapper into the cave equivalent to:

   ```c
   void* wrapper(void* arg) {
       for (;;) {
           void* h = dlopen("libil2cpp.so", RTLD_NOLOAD);
           if (h) {
               auto get = (void* (*)())dlsym(h, "il2cpp_domain_get");
               if (get && get() != NULL)
                   return overlay_thread_main(arg);   // tail-call, vaddr 0x54300
           }
           sleep(1);
       }
   }
   ```

   `dlopen`, `dlsym`, `sleep` are reached through the existing PLT entries
   in the binary (`0xcaf0`, `0xc9c0`, `0xc870` respectively); no new
   imports are added.

3. Patches `OverlayModule::postAppSpecialize` at file offset `0x57440` /
   `0x57448` so the third argument to `pthread_create` (the
   `start_routine`) points to `wrapper` instead of the original
   `overlay_thread_main` at `0x54300`. The two patched instructions are:

   ```
   0x57440:  adrp x2, 0x140000
   0x57448:  add  x2, x2, #0x0
   ```

CI builds the patched `.so` and a Magisk-flashable zip on every push to
`devin/**`; see the `libarm64-v8a-patched-*` and
`zygisk-overlay-patched-module-*` artifacts.

The wrapper adds a `dlopen`/`dlsym`/`sleep`-loop overhead **once**, on the
spawned UI thread, before the first frame. Steady-state cost is zero —
the original `overlay_thread_main` runs untouched after the wait
succeeds.
