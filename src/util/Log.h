// SPDX-License-Identifier: ISC
//
// The binary exports four logging symbols that come from Dobby's built-in
// logging module (see Dobby/source/logging/logging.cc upstream):
//   log_set_level          @ 0x95214
//   log_switch_to_syslog   @ 0x95220
//   log_switch_to_file     @ 0x95230
//   log_internal_impl      @ 0x95268    -> __android_log_vprint(4, "Dobby", ...)
//
// We do NOT shadow Dobby's symbols here. We provide a small C++ wrapper for
// the module's own log lines that uses the same Android log tag conventions
// as the decompilation suggests.
#pragma once

#include <android/log.h>

#define OVERLAY_LOG_TAG "ZygiskOverlay"

namespace overlay::log {
inline void info (const char* fmt, ...) __attribute__((format(printf, 1, 2)));
inline void warn (const char* fmt, ...) __attribute__((format(printf, 1, 2)));
inline void error(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

inline void info(const char* fmt, ...) {
    va_list ap; va_start(ap, fmt);
    __android_log_vprint(ANDROID_LOG_INFO, OVERLAY_LOG_TAG, fmt, ap);
    va_end(ap);
}
inline void warn(const char* fmt, ...) {
    va_list ap; va_start(ap, fmt);
    __android_log_vprint(ANDROID_LOG_WARN, OVERLAY_LOG_TAG, fmt, ap);
    va_end(ap);
}
inline void error(const char* fmt, ...) {
    va_list ap; va_start(ap, fmt);
    __android_log_vprint(ANDROID_LOG_ERROR, OVERLAY_LOG_TAG, fmt, ap);
    va_end(ap);
}
} // namespace overlay::log
