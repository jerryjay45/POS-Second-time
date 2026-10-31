#!/bin/sh
mkdir -p "${MERCHANTPOS_HOME:-$HOME/.local/share/merchantpos}"
exec python3 /app/share/merchantpos/main.py "$@"
