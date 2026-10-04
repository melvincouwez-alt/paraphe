#!/bin/bash
# gala headless on a private D-Bus session, then run the command against it.
gala --headless --wayland --wayland-display=paraphe-test --virtual-monitor 1280x860 --no-x11 > "${T:-/tmp}/paraphe-gala.log" 2>&1 &
G=$!
for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/paraphe-test" ] && break; sleep 0.2; done
WAYLAND_DISPLAY=paraphe-test GDK_BACKEND=wayland "$@"
kill $G; wait $G 2>/dev/null
