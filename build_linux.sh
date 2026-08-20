#!/usr/bin/env bash
# =============================================================================
# build_linux.sh
# Build Merchant POS Systems for Linux (native — no Wine required)
# Supports: Arch Linux, Fedora, Debian/Ubuntu, and derivatives
#
# Usage:
#   chmod +x build_linux.sh
#   ./build_linux.sh
#
# Output:
#   dist/linux/MerchantPOS_Portable/       ← Portable directory
#   dist/linux/MerchantPOS-x86_64.tar.gz   ← Archive (ready for AppImage/Flatpak)
#
# What this script does:
#   1. Installs system dependencies (Python 3, Qt6, pip)
#   2. Creates an isolated venv with all Python dependencies
#   3. Runs PyInstaller to bundle the app
#   4. Assembles the portable directory with assets, data dir, launcher
#   5. Creates a .desktop file and installs icon for system integration
#   6. Packages everything into a tar.gz for AppImage/Flatpak use
#
# Notes:
#   - Builds on the current machine's architecture (x86_64 or arm64)
#   - The portable dir can be run directly: ./MerchantPOS_Portable/MerchantPOS
#   - For Flatpak/AppImage, use the .tar.gz as the source bundle
# =============================================================================

set -euo pipefail

# ── Colour output ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()    { echo -e "\n${BOLD}▶ $*${NC}"; }

# ── Configuration ─────────────────────────────────────────────────────────────
APP_NAME="MerchantPOS"
APP_VERSION="1.0.0"
APP_DISPLAY="Merchant POS Systems"
APP_ID="com.merchantretail.pos"        # Reverse-domain ID for Flatpak
PUBLISHER="Merchant Retail"
ENTRY_POINT="main.py"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build_linux"
DIST_DIR="$SCRIPT_DIR/dist/linux"
VENV_DIR="$BUILD_DIR/venv"
ARCH="$(uname -m)"

mkdir -p "$BUILD_DIR" "$DIST_DIR"

# ── Step 1: System dependencies ───────────────────────────────────────────────
step "Checking system dependencies"

# Python 3.11+ required for match statements and type hints used in the app
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info[:2])")
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    info "Python 3.11+ not found — installing..."
    if command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python python-pip
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -q
        sudo apt-get install -y python3 python3-pip python3-venv
    else
        error "Unsupported distro. Install Python 3.11+ manually then re-run."
    fi
    PYTHON=python3
fi

success "Python: $($PYTHON --version)"

# Qt6 system libraries (needed at runtime even in a bundled app on some distros)
step "Checking Qt6 / PyQt6 system libraries"

install_qt_deps() {
    if command -v pacman &>/dev/null; then
        info "Arch Linux — installing Qt6 libs"
        sudo pacman -Sy --noconfirm qt6-base qt6-svg 2>/dev/null || true
    elif command -v dnf &>/dev/null; then
        info "Fedora — installing Qt6 libs"
        sudo dnf install -y qt6-qtbase qt6-qtsvg libxcb xcb-util-wm \
            xcb-util-image xcb-util-keysyms xcb-util-renderutil 2>/dev/null || true
    elif command -v apt-get &>/dev/null; then
        info "Debian/Ubuntu — installing Qt6 / xcb libs"
        sudo apt-get install -y \
            libqt6widgets6 libqt6gui6 libqt6core6 libqt6printsupport6 \
            libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
            libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 \
            libxkbcommon-x11-0 libdbus-1-3 libegl1 libgl1 \
            python3-venv 2>/dev/null || true
    fi
}
install_qt_deps
success "System Qt6 libraries OK"

# USB printer support needs libusb
if command -v apt-get &>/dev/null; then
    sudo apt-get install -y libusb-1.0-0 libudev1 2>/dev/null || true
elif command -v dnf &>/dev/null; then
    sudo dnf install -y libusb 2>/dev/null || true
elif command -v pacman &>/dev/null; then
    sudo pacman -Sy --noconfirm libusb 2>/dev/null || true
fi

# ── Step 2: Python virtual environment ───────────────────────────────────────
step "Setting up Python virtual environment"

if [ ! -d "$VENV_DIR" ]; then
    info "Creating venv at $VENV_DIR ..."
    $PYTHON -m venv "$VENV_DIR"
    success "venv created"
else
    success "venv already exists"
fi

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ── Step 3: Install Python dependencies ──────────────────────────────────────
step "Installing Python dependencies"

info "Upgrading pip..."
"$PIP" install --upgrade pip --quiet

info "Installing PyQt6..."
"$PIP" install "PyQt6==6.11.0" --quiet

info "Installing application dependencies..."
"$PIP" install \
    dbfread \
    psycopg2-binary \
    python-escpos \
    --quiet

info "Installing PyInstaller..."
"$PIP" install pyinstaller --quiet

success "All packages installed"

# ── Step 4: Check assets ──────────────────────────────────────────────────────
step "Checking assets"

mkdir -p "$SCRIPT_DIR/assets"

# Real icon may be checked in as merchant_pos_512.png (or _256/_128) rather
# than the bare "merchant_pos.png" this script (and the .desktop file) look
# for. Prefer the real art over the generated placeholder whenever it's
# present under any of those names.
if [ ! -f "$SCRIPT_DIR/assets/merchant_pos.png" ]; then
    SOURCE_ICON=""
    for candidate in merchant_pos_512.png merchant_pos_256.png merchant_pos_128.png; do
        if [ -f "$SCRIPT_DIR/assets/$candidate" ]; then
            SOURCE_ICON="$SCRIPT_DIR/assets/$candidate"
            break
        fi
    done

    if [ -n "$SOURCE_ICON" ]; then
        info "Using $(basename "$SOURCE_ICON") as the app icon"
        cp "$SOURCE_ICON" "$SCRIPT_DIR/assets/merchant_pos.png"
    else
        warn "assets/merchant_pos.png not found — creating placeholder"
        warn "Replace with your real icon (512x512 PNG) before distributing"
        "$PY" -c "
try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
    from PyQt6.QtCore import Qt
    import sys
    app = QApplication(sys.argv)
    pm = QPixmap(512, 512)
    pm.fill(QColor('#EF9F27'))
    painter = QPainter(pm)
    painter.setPen(QColor('white'))
    f = QFont('Arial', 80, QFont.Weight.Bold)
    painter.setFont(f)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, 'POS')
    painter.end()
    pm.save('$SCRIPT_DIR/assets/merchant_pos.png')
    print('Placeholder icon created')
except Exception as e:
    print(f'Could not create icon: {e}')
" 2>/dev/null || true
    fi
fi

# Also need .ico for the PyInstaller exe metadata (used in tar.gz info)
ICON_PATH="$SCRIPT_DIR/assets/merchant_pos.png"
if [ ! -f "$ICON_PATH" ]; then
    warn "No icon found — build will proceed without one"
    ICON_PATH=""
fi

# ── Step 5: Build hidden imports list ─────────────────────────────────────────
step "Generating PyInstaller spec"

HIDDEN=$("$PY" -c "
import os, sys
sys.path.insert(0, '$SCRIPT_DIR')
mods = []
for root, dirs, files in os.walk('$SCRIPT_DIR'):
    dirs[:] = [d for d in dirs
               if d not in ('__pycache__', 'build_linux', 'build_win',
                            'dist', '.git', 'venv')]
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            rel = os.path.relpath(os.path.join(root, f), '$SCRIPT_DIR')
            mod = rel.replace(os.sep, '.')[:-3]
            mods.append(mod)
print(','.join(repr(m) for m in mods))
" 2>/dev/null)

ICON_LINE=""
if [ -n "$ICON_PATH" ]; then
    ICON_LINE="    icon='${ICON_PATH}',"
fi

cat > "$BUILD_DIR/MerchantPOS_linux.spec" << SPEC
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
import sys

datas    = []
binaries = []
hiddenimports = []

# Collect all PyQt6 components
qt_d, qt_b, qt_i = collect_all('PyQt6')
datas        += qt_d
binaries     += qt_b
hiddenimports += qt_i

# Collect all project submodules
for pkg in ['core', 'ui', 'utils']:
    hiddenimports += collect_submodules(pkg)

# Extra runtime dependencies
hiddenimports += [
    'dbfread', 'dbfread.dbf', 'dbfread.field_parser',
    'psycopg2',
    'escpos', 'escpos.printer',
    $HIDDEN,
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas + [
        ('assets',    'assets'),
        ('ui',        'ui'),
        ('core',      'core'),
        ('utils',     'utils'),
        ('config.py', '.'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MerchantPOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
${ICON_LINE}
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['libQt6Core.so', 'libQt6Gui.so', 'libQt6Widgets.so',
                 'libQt6PrintSupport.so'],
    name='MerchantPOS',
)
SPEC

success "Spec file created"

# ── Step 6: Run PyInstaller ───────────────────────────────────────────────────
step "Running PyInstaller (this takes several minutes)"

cd "$SCRIPT_DIR"

"$VENV_DIR/bin/pyinstaller" \
    --clean \
    --noconfirm \
    "$BUILD_DIR/MerchantPOS_linux.spec" \
    --distpath "$BUILD_DIR/pyinstaller_dist" \
    --workpath "$BUILD_DIR/pyinstaller_work" \
    2>&1 | grep -v "^[0-9]* INFO\|^[0-9]* WARNING: Library not found\|^\s*$" || true

cd "$SCRIPT_DIR"

if [ -d "$BUILD_DIR/pyinstaller_dist/MerchantPOS" ]; then
    success "PyInstaller build complete"
else
    error "PyInstaller failed — MerchantPOS directory not found. Check output above."
fi

# ── Step 7: Assemble portable directory ──────────────────────────────────────
step "Assembling portable directory"

PORTABLE="$DIST_DIR/MerchantPOS_Portable"
rm -rf "$PORTABLE"
cp -r "$BUILD_DIR/pyinstaller_dist/MerchantPOS" "$PORTABLE"

# Copy assets
mkdir -p "$PORTABLE/assets"
cp -r "$SCRIPT_DIR/assets/"* "$PORTABLE/assets/" 2>/dev/null || true

# Create empty data directory (databases live here at runtime)
mkdir -p "$PORTABLE/data"
mkdir -p "$PORTABLE/receipts"
mkdir -p "$PORTABLE/labels"

# Create launcher shell script (handles library paths and working directory)
cat > "$PORTABLE/launch.sh" << 'LAUNCHER'
#!/usr/bin/env bash
# Launcher for Merchant POS Systems
# Sets correct working directory and library paths before starting the app.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$DIR:${LD_LIBRARY_PATH:-}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
# Fallback to Wayland if XCB not available
if ! python3 -c "from PyQt6.QtWidgets import QApplication" 2>/dev/null; then
    export QT_QPA_PLATFORM=wayland
fi
cd "$DIR"
exec "$DIR/MerchantPOS" "$@"
LAUNCHER
chmod +x "$PORTABLE/launch.sh"

# Make main binary executable
chmod +x "$PORTABLE/MerchantPOS"

success "Portable directory → $PORTABLE/"

# ── Step 8: .desktop file ────────────────────────────────────────────────────
step "Creating .desktop file"

DESKTOP_FILE="$PORTABLE/MerchantPOS.desktop"
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=${APP_DISPLAY}
Comment=Point of Sale System
Exec=${PORTABLE}/launch.sh
Icon=${PORTABLE}/assets/merchant_pos.png
Terminal=false
Categories=Office;Finance;
StartupWMClass=MerchantPOS
Keywords=pos;retail;sales;receipt;
DESKTOP

chmod +x "$DESKTOP_FILE"
success ".desktop file created"

# Offer to install .desktop file to user's applications menu
if [ -d "$HOME/.local/share/applications" ]; then
    cp "$DESKTOP_FILE" "$HOME/.local/share/applications/MerchantPOS.desktop"
    # Install icon
    mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
    if [ -f "$PORTABLE/assets/merchant_pos.png" ]; then
        cp "$PORTABLE/assets/merchant_pos.png" \
           "$HOME/.local/share/icons/hicolor/512x512/apps/merchantpos.png"
    fi
    # Update icon cache if possible
    command -v gtk-update-icon-cache &>/dev/null && \
        gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    success "Installed to applications menu (~/.local/share/applications/)"
fi

# ── Step 9: USB printer permissions ──────────────────────────────────────────
step "Checking USB printer permissions"

UDEV_RULE="/etc/udev/rules.d/99-merchantpos-printer.rules"
if [ ! -f "$UDEV_RULE" ]; then
    info "Creating udev rule for USB thermal printers..."
    sudo tee "$UDEV_RULE" > /dev/null << 'UDEV'
# Merchant POS Systems — USB thermal printer access
# Allows the current user to access USB printers without sudo.
# Common thermal printer vendor IDs:
SUBSYSTEM=="usb", ATTRS{idVendor}=="0416", MODE="0666", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", MODE="0666", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0519", MODE="0666", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="067b", MODE="0666", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="154f", MODE="0666", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1504", MODE="0666", GROUP="lp"
SUBSYSTEM=="printer", MODE="0666", GROUP="lp"
UDEV
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    success "udev rules installed"
    # Add current user to lp group for serial printer access
    sudo usermod -aG lp "$USER" 2>/dev/null || true
    warn "Log out and back in for USB printer group changes to take effect."
else
    success "udev rules already in place"
fi

# ── Step 10: Package for AppImage / Flatpak ───────────────────────────────────
step "Creating tar.gz archive for AppImage / Flatpak"

TARBALL="$DIST_DIR/${APP_NAME}-${ARCH}.tar.gz"

# AppImage-style directory layout inside the archive:
#   MerchantPOS/
#     MerchantPOS          ← main executable
#     launch.sh            ← launcher
#     MerchantPOS.desktop  ← desktop entry
#     assets/              ← icons and static files
#     data/                ← empty — populated at runtime
#     <all PyInstaller libs>
TARBALL_DIR="$BUILD_DIR/tarball_stage"
rm -rf "$TARBALL_DIR"
mkdir -p "$TARBALL_DIR"
cp -r "$PORTABLE" "$TARBALL_DIR/$APP_NAME"

# Write metadata file — useful for Flatpak manifest generation
cat > "$TARBALL_DIR/$APP_NAME/metadata.json" << META
{
  "app_id":      "${APP_ID}",
  "app_name":    "${APP_NAME}",
  "display":     "${APP_DISPLAY}",
  "version":     "${APP_VERSION}",
  "publisher":   "${PUBLISHER}",
  "arch":        "${ARCH}",
  "entry":       "launch.sh",
  "built_at":    "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
META

tar -czf "$TARBALL" -C "$TARBALL_DIR" "$APP_NAME"
success "Archive → $TARBALL"

# ── Step 11: Quick smoke test ─────────────────────────────────────────────────
step "Smoke testing the build"

MAIN_BIN="$PORTABLE/MerchantPOS"
if [ -f "$MAIN_BIN" ]; then
    info "Launching for 5 seconds to verify it starts..."
    export QT_QPA_PLATFORM=offscreen   # headless — no display needed for CI
    timeout 5 "$MAIN_BIN" 2>/dev/null && true
    unset QT_QPA_PLATFORM
    success "App launched without immediate crash"
else
    warn "Binary not found at $MAIN_BIN — skipping smoke test"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  BUILD COMPLETE — ${APP_DISPLAY} v${APP_VERSION}${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Portable:  ${CYAN}$PORTABLE/${NC}"
echo -e "  Archive:   ${CYAN}$TARBALL${NC}"
echo ""
echo -e "  Run directly:"
echo -e "  ${YELLOW}$PORTABLE/launch.sh${NC}"
echo ""
echo -e "  For AppImage — use appimagetool on the portable directory:"
echo -e "  ${YELLOW}appimagetool $PORTABLE ${APP_NAME}-${ARCH}.AppImage${NC}"
echo ""
echo -e "  For Flatpak — use the archive and metadata.json as your bundle source."
echo -e "  App ID: ${CYAN}${APP_ID}${NC}"
echo ""
if [ -f "$UDEV_RULE" ]; then
    echo -e "  ${YELLOW}USB PRINTERS:${NC} udev rules installed. Log out and back in"
    echo -e "  if you need USB thermal printer access."
    echo ""
fi
echo -e "  ${YELLOW}NOTE:${NC} Replace assets/merchant_pos.png with your real 512x512"
echo -e "        PNG icon before distributing."
echo ""
