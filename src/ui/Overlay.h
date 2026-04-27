// SPDX-License-Identifier: ISC
#pragma once

namespace overlay::ui {

// pthread entry; matches the binary's UI thread spawned in postAppSpecialize.
// @ 0x54300 in the original (~9.8 KB OLLVM-flattened).
void* overlay_thread_main(void*);

} // namespace overlay::ui
