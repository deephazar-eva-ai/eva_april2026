#!/bin/bash
set -e

# Start D-Bus so that UI applications (like gnome-calculator) can connect
export DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --session --fork --print-address)
# Persist the address so subprocesses spawned by uv run can discover it
echo "$DBUS_SESSION_BUS_ADDRESS" > /tmp/dbus-session-address

# Clean stale LibreOffice lock files that prevent proper file loading
find /home -name '.~lock.*#' -delete 2>/dev/null || true
find /data -name '.~lock.*#' -delete 2>/dev/null || true

# Set the display port
export DISPLAY=:99

# Start the virtual framebuffer in the background
Xvfb $DISPLAY -screen 0 1920x1080x24 > /dev/null 2>&1 &

# Enable Accessibility (AT-SPI) so cua-driver can see the UI tree
export GNOME_ACCESSIBILITY=1
export GTK_MODULES=gail:atk-bridge
export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
export QT_ACCESSIBILITY=1

# Force LibreOffice to use GTK3 VCL plugin — required for AT-SPI to expose
# internal widgets (cells, dialogs, menus). Without this, only the top-level
# window frame is visible (elements=1).
export SAL_USE_VCLPLUGIN=gtk3

# Wait a moment to ensure Xvfb has started
sleep 1

# Launch a lightweight window manager — AT-SPI ignores elements in windows
# without proper focus/stacking management. openbox provides this.
openbox &
sleep 0.5

# Explicitly launch the accessibility bus
/usr/libexec/at-spi-bus-launcher --launch-immediately &
sleep 2

# Discover and persist the AT-SPI bus address (separate from session bus!)
# at-spi-bus-launcher stores it in the AT_SPI_BUS X11 root window property
AT_SPI_ADDR=$(xprop -root -notype AT_SPI_BUS 2>/dev/null | sed 's/AT_SPI_BUS = "\(.*\)"/\1/')
if [ -n "$AT_SPI_ADDR" ] && [ "$AT_SPI_ADDR" != "AT_SPI_BUS:  not found." ]; then
    echo "$AT_SPI_ADDR" > /tmp/at-spi-bus-address
    echo "[entrypoint] AT-SPI bus: $AT_SPI_ADDR"
fi

# If the command is passed without 'uv run', we can prefix it
if [ "$1" = "uv" ]; then
    exec "$@"
else
    # Default to running flow.py in the code directory
    cd /app/code
    exec uv run flow.py "$@"
fi
