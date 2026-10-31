#!/bin/sh
# XDG_DATA_HOME is ~/.var/app/com.merchantretail.pos/data inside the Flatpak sandbox
export MERCHANTPOS_HOME="${MERCHANTPOS_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/merchantpos}"
mkdir -p "$MERCHANTPOS_HOME"
exec python3 /app/share/merchantpos/main.py "$@"
