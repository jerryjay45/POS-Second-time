#!/usr/bin/env bash
# =============================================================================
# build_windows.sh
# Cross-compile Merchant POS Systems for Windows 10/11 from Linux
# Supports: Arch Linux, Fedora, Debian/Ubuntu
#
# Usage:
#   chmod +x build_windows.sh
#   ./build_windows.sh
#
# Output:
#   dist/windows/MerchantPOS_Portable/     ← Portable folder (no installer)
#   dist/windows/MerchantPOS_Setup.exe     ← Inno Setup installer (if ISCC found)
#
# Requirements installed automatically:
#   - Wine (64-bit Windows environment)
#   - Python 3.11 for Windows (downloaded automatically)
#   - All Python dependencies installed into Wine Python
#   - PyInstaller (installed into Wine Python)
#   - Inno Setup 6 (optional, for .exe installer)
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
PUBLISHER="Merchant Retail"
ENTRY_POINT="main.py"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build_win"
DIST_DIR="$SCRIPT_DIR/dist/windows"
WINE_PREFIX="$BUILD_DIR/wine_prefix"

WIN_PYTHON_VERSION="3.11.9"
WIN_PYTHON_URL="https://www.python.org/ftp/python/${WIN_PYTHON_VERSION}/python-${WIN_PYTHON_VERSION}-amd64.exe"
WIN_PYTHON_INSTALLER="$BUILD_DIR/python-${WIN_PYTHON_VERSION}-amd64.exe"
WIN_PYTHON_EXE="$WINE_PREFIX/drive_c/Python311/python.exe"

INNO_URL="https://jrsoftware.org/download.php/is.exe"
INNO_INSTALLER="$BUILD_DIR/inno_setup.exe"
INNO_EXE="$WINE_PREFIX/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe"

mkdir -p "$BUILD_DIR" "$DIST_DIR"

# ── Step 1: Install Wine ──────────────────────────────────────────────────────
step "Checking Wine installation"

if command -v wine &>/dev/null; then
    success "Wine already installed: $(wine --version)"
else
    info "Installing Wine..."
    if command -v pacman &>/dev/null; then
        info "Arch Linux detected"
        sudo pacman -Sy --noconfirm wine wine-mono wine-gecko
    elif command -v dnf &>/dev/null; then
        info "Fedora detected"
        sudo dnf install -y wine
    elif command -v apt-get &>/dev/null; then
        info "Debian/Ubuntu detected"
        sudo dpkg --add-architecture i386
        sudo apt-get update -q
        sudo apt-get install -y wine wine64 wine32
    else
        error "Unsupported distro. Install Wine manually then re-run."
    fi
    success "Wine installed: $(wine --version)"
fi

# ── Step 2: Set up Wine prefix ────────────────────────────────────────────────
step "Setting up Wine prefix (64-bit Windows)"

export WINEPREFIX="$WINE_PREFIX"
export WINEARCH=win64
export WINEDEBUG=-all   # suppress Wine debug noise

if [ ! -f "$WINE_PREFIX/system.reg" ]; then
    info "Initialising Wine prefix at $WINE_PREFIX ..."
    wineboot --init 2>/dev/null || true
    sleep 4
    success "Wine prefix ready"
else
    success "Wine prefix already exists"
fi

# ── Step 3: Install Windows Python 3.11 ──────────────────────────────────────
step "Installing Windows Python $WIN_PYTHON_VERSION into Wine"

if [ ! -f "$WIN_PYTHON_EXE" ]; then
    if [ ! -f "$WIN_PYTHON_INSTALLER" ]; then
        info "Downloading Python $WIN_PYTHON_VERSION for Windows..."
        curl -L --progress-bar -o "$WIN_PYTHON_INSTALLER" "$WIN_PYTHON_URL"
        success "Downloaded"
    fi
    info "Installing Python into Wine (takes ~1 minute)..."
    wine "$WIN_PYTHON_INSTALLER" /quiet InstallAllUsers=1 \
        TargetDir='C:\Python311' PrependPath=1 2>/dev/null || true
    sleep 6
    if [ -f "$WIN_PYTHON_EXE" ]; then
        success "Python $WIN_PYTHON_VERSION installed"
    else
        error "Python installation failed — $WIN_PYTHON_EXE not found"
    fi
else
    success "Windows Python already installed"
fi

WINE_PY="wine $WIN_PYTHON_EXE"
WINE_PIP="wine $WIN_PYTHON_EXE -m pip"

# Verify Wine Python works
$WINE_PY --version 2>/dev/null && success "Wine Python OK" || error "Wine Python not working"

# ── Step 4: Install Python dependencies ──────────────────────────────────────
step "Installing Python dependencies into Wine Python"

info "Upgrading pip..."
$WINE_PIP install --upgrade pip --quiet 2>/dev/null

info "Installing PyQt6..."
$WINE_PIP install "PyQt6==6.11.0" --quiet 2>/dev/null

info "Installing application dependencies..."
$WINE_PIP install \
    dbfread \
    psycopg2-binary \
    pywin32 \
    python-escpos \
    --quiet 2>/dev/null

info "Installing PyInstaller..."
$WINE_PIP install pyinstaller --quiet 2>/dev/null

success "All packages installed"

# ── Step 5: Create assets directory and placeholder icon ─────────────────────
step "Checking assets"

mkdir -p "$SCRIPT_DIR/assets"

# Create a simple placeholder .ico if none exists
# (replace assets/merchant_pos.ico with your real icon before building)
if [ ! -f "$SCRIPT_DIR/assets/merchant_pos.ico" ]; then
    warn "assets/merchant_pos.ico not found — creating placeholder"
    warn "Replace with your real icon before distributing"
    # Create a minimal 16x16 ICO using Python + Pillow (if available)
    python3 -c "
try:
    from PIL import Image
    img = Image.new('RGBA', (64, 64), (239, 159, 39, 255))
    img.save('$SCRIPT_DIR/assets/merchant_pos.ico', format='ICO',
             sizes=[(16,16),(32,32),(48,48),(64,64)])
    print('Placeholder icon created')
except Exception as e:
    print(f'Could not create icon: {e}')
" 2>/dev/null || true
fi

ICO_PATH="$SCRIPT_DIR/assets/merchant_pos.ico"
ICO_WIN=$(winepath -w "$ICO_PATH" 2>/dev/null || echo "Z:\\${ICO_PATH//\//\\\\}")
# Escape backslashes so they survive the heredoc expansion below
ICO_WIN_ESC="${ICO_WIN//\\/\\\\}"

# ── Step 6: Build hidden imports list ────────────────────────────────────────
step "Generating PyInstaller spec"

# Collect all project modules for hidden imports
HIDDEN=$(python3 -c "
import os, sys
sys.path.insert(0, '$SCRIPT_DIR')
mods = []
for root, dirs, files in os.walk('$SCRIPT_DIR'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', 'build_win', 'dist', '.git')]
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            rel = os.path.relpath(os.path.join(root, f), '$SCRIPT_DIR')
            mod = rel.replace(os.sep, '.')[:-3]
            mods.append(mod)
print(','.join(repr(m) for m in mods))
" 2>/dev/null)

ASSETS_WIN=$(winepath -w "$SCRIPT_DIR/assets" 2>/dev/null || echo "Z:${SCRIPT_DIR//\//\\}\\assets")
DATA_WIN=$(winepath -w "$SCRIPT_DIR/data"   2>/dev/null || echo "Z:${SCRIPT_DIR//\//\\}\\data")

cat > "$BUILD_DIR/MerchantPOS.spec" << SPEC
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas    = []
binaries = []
hiddenimports = []

# Collect all PyQt6 components
qt_d, qt_b, qt_i = collect_all('PyQt6')
datas     += qt_d
binaries  += qt_b
hiddenimports += qt_i

# Collect all project submodules
for pkg in ['core', 'ui', 'utils']:
    hiddenimports += collect_submodules(pkg)

# Extra runtime dependencies
hiddenimports += [
    'dbfread', 'dbfread.dbf', 'dbfread.field_parser',
    'psycopg2',
    'win32print', 'win32api', 'win32con', 'win32timezone',
    'escpos', 'escpos.printer',
    $HIDDEN,
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas + [
        ('assets',   'assets'),
        ('ui',       'ui'),
        ('core',     'core'),
        ('utils',    'utils'),
        ('config.py','.'),
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
    strip=False,
    upx=True,
    console=False,
    icon='${ICO_WIN_ESC}',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','Qt6PrintSupport.dll'],
    name='MerchantPOS',
)
SPEC

cp "$BUILD_DIR/MerchantPOS.spec" "$SCRIPT_DIR/MerchantPOS.spec"
success "Spec file created"

# ── Step 7: Run PyInstaller ───────────────────────────────────────────────────
step "Running PyInstaller via Wine (this takes several minutes)"

cd "$SCRIPT_DIR"

PYINSTALLER_EXE="$WINE_PREFIX/drive_c/Python311/Scripts/pyinstaller.exe"
if [ ! -f "$PYINSTALLER_EXE" ]; then
    error "pyinstaller.exe not found at $PYINSTALLER_EXE"
fi

wine "$PYINSTALLER_EXE" \
    --clean \
    --noconfirm \
    MerchantPOS.spec \
    2>&1 | grep -v "^Traceback\|^  File\|^\s*$\|^WARNING: lib\|^[0-9]* INFO" | tail -40

rm -f "$SCRIPT_DIR/MerchantPOS.spec"

# Move output
if [ -d "$SCRIPT_DIR/dist/MerchantPOS" ]; then
    rm -rf "$DIST_DIR/MerchantPOS_Portable"
    mv "$SCRIPT_DIR/dist/MerchantPOS" "$DIST_DIR/MerchantPOS_Portable"
    success "Portable build → $DIST_DIR/MerchantPOS_Portable/"
else
    error "PyInstaller failed — dist/MerchantPOS not found. Check output above."
fi

# Copy assets and create data dir
mkdir -p "$DIST_DIR/MerchantPOS_Portable/assets"
mkdir -p "$DIST_DIR/MerchantPOS_Portable/data"
mkdir -p "$DIST_DIR/MerchantPOS_Portable/receipts"
mkdir -p "$DIST_DIR/MerchantPOS_Portable/labels"
cp -r "$SCRIPT_DIR/assets/"* "$DIST_DIR/MerchantPOS_Portable/assets/" 2>/dev/null || true
success "Assets copied"

# ── Step 8: Inno Setup installer (optional) ───────────────────────────────────
step "Creating Windows installer (optional)"

if [ ! -f "$INNO_EXE" ]; then
    info "Installing Inno Setup..."
    if [ ! -f "$INNO_INSTALLER" ]; then
        curl -L --progress-bar -o "$INNO_INSTALLER" "$INNO_URL"
    fi
    wine "$INNO_INSTALLER" /VERYSILENT /SUPPRESSMSGBOXES 2>/dev/null || true
    sleep 5
fi

if [ -f "$INNO_EXE" ]; then
    PORTABLE_WIN=$(winepath -w "$DIST_DIR/MerchantPOS_Portable" 2>/dev/null \
        || echo "Z:${DIST_DIR//\//\\}\\MerchantPOS_Portable")
    OUTPUT_WIN=$(winepath -w "$DIST_DIR" 2>/dev/null \
        || echo "Z:${DIST_DIR//\//\\}")
    ICO_PORTABLE_WIN=$(winepath -w "$DIST_DIR/MerchantPOS_Portable/assets/merchant_pos.ico" 2>/dev/null \
        || echo "Z:${DIST_DIR//\//\\}\\MerchantPOS_Portable\\assets\\merchant_pos.ico")

    cat > "$BUILD_DIR/installer.iss" << ISS
[Setup]
AppName=${APP_DISPLAY}
AppVersion=${APP_VERSION}
AppVerName=${APP_DISPLAY} v${APP_VERSION}
AppPublisher=${PUBLISHER}
DefaultDirName={autopf}\\${APP_NAME}
DefaultGroupName=${APP_DISPLAY}
AllowNoIcons=yes
OutputDir=${OUTPUT_WIN}
OutputBaseFilename=${APP_NAME}_Setup_v${APP_VERSION}
SetupIconFile=${ICO_PORTABLE_WIN}
UninstallDisplayIcon={app}\\assets\\merchant_pos.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
PrivilegesRequired=admin
DisableProgramGroupPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "${PORTABLE_WIN}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\\${APP_DISPLAY}";           Filename: "{app}\\MerchantPOS.exe"; IconFilename: "{app}\\assets\\merchant_pos.ico"
Name: "{group}\\Uninstall ${APP_DISPLAY}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\\${APP_DISPLAY}";     Filename: "{app}\\MerchantPOS.exe"; IconFilename: "{app}\\assets\\merchant_pos.ico"; Tasks: desktopicon

[Dirs]
Name: "{app}\\data";     Permissions: users-modify
Name: "{app}\\receipts"; Permissions: users-modify
Name: "{app}\\labels";   Permissions: users-modify

[Run]
Filename: "{app}\\MerchantPOS.exe"; Description: "{cm:LaunchProgram,${APP_DISPLAY}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\\data"
Type: filesandordirs; Name: "{app}\\receipts"
Type: filesandordirs; Name: "{app}\\labels"
ISS

    ISS_WIN=$(winepath -w "$BUILD_DIR/installer.iss" 2>/dev/null \
        || echo "Z:${BUILD_DIR//\//\\}\\installer.iss")

    info "Compiling installer..."
    wine "$INNO_EXE" "$ISS_WIN" 2>/dev/null || warn "Inno Setup had warnings"

    INSTALLER="$DIST_DIR/${APP_NAME}_Setup_v${APP_VERSION}.exe"
    if [ -f "$INSTALLER" ]; then
        success "Installer → $INSTALLER"
    else
        warn "Installer not found at expected path — check $DIST_DIR"
    fi
else
    warn "Inno Setup not available — skipping installer creation"
    warn "Install manually from https://jrsoftware.org/isdl.php"
fi

# ── Step 9: Quick Wine test ───────────────────────────────────────────────────
step "Testing portable build in Wine"

TEST_EXE="$DIST_DIR/MerchantPOS_Portable/MerchantPOS.exe"
if [ -f "$TEST_EXE" ]; then
    info "Launching in Wine for 5 seconds to verify it starts..."
    timeout 5 wine "$TEST_EXE" 2>/dev/null && true
    success "App launched without immediate crash"
else
    warn "EXE not found at $TEST_EXE"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  BUILD COMPLETE — Merchant POS Systems v${APP_VERSION}${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Portable:  ${CYAN}$DIST_DIR/MerchantPOS_Portable/${NC}"
[ -f "$DIST_DIR/${APP_NAME}_Setup_v${APP_VERSION}.exe" ] && \
echo -e "  Installer: ${CYAN}$DIST_DIR/${APP_NAME}_Setup_v${APP_VERSION}.exe${NC}"
echo ""
echo -e "  To test manually in Wine:"
echo -e "  ${YELLOW}WINEPREFIX=$WINE_PREFIX wine \"$TEST_EXE\"${NC}"
echo ""
echo -e "  ${YELLOW}NOTE:${NC} Replace assets/merchant_pos.ico with your real app icon"
echo -e "        before distributing."
echo ""
