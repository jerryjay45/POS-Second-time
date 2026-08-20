# Merchant POS Systems

A full-featured, open-source Point of Sale application for retail businesses, built with Python and PyQt6. Designed for multi-terminal deployments, thermal receipt printing, and offline-first operation with optional PostgreSQL sync.

> **This project was built entirely with the assistance of [Claude](https://claude.ai), an AI assistant made by Anthropic. All architecture decisions, code, bug fixes, and documentation were produced through a collaborative conversation between the developer and Claude AI.**

---

## Features

### Cashier
- Barcode and name product search
- Three simultaneous cart sessions
- Cash, card, and split payment support
- Miscellaneous (unlisted) item entry
- Price check without adding to cart
- Configurable quick-cash amount buttons
- Void sales with supervisor PIN authorisation
- Thermal receipt printing with configurable copies

### Supervisor
- Product management — add, edit, delete, search
- Product groups with configurable profit margins
- Case product linking (carton ↔ single unit)
- Price group aliases (multi-barcode products)
- Two-tier discount levels with minimum quantity thresholds
- Stock tracking and adjustment history
- Void and refund processing with reason logging
- Session reports and Z-reports
- Shelf price label printing
- Quick keys (F1–F8) configuration

### Manager
- All supervisor features, plus:
- User account management (cashier / supervisor / manager roles)
- Business information and receipt header/footer editing
- GCT (tax) rate configuration
- DBF stock file import (from legacy POS systems)
- Thermal and normal printer configuration with test print
- PostgreSQL sync configuration (multi-terminal)
- Discount level and product group administration

### System
- First-time setup wizard with terminal identity assignment
- Offline-first — fully functional without a network connection
- Four isolated SQLite databases (products, checkout, users, config)
- WAL journal mode for safe concurrent access
- Salted password hashing
- Configurable UI zoom
- Receipts saved as plain-text files as a backup trail
- Multi-theme support (dark, amber, green, midnight)

---


## Architecture

```
merchant-pos/
├── main.py                  # Entry point
├── config.py                # Paths and global constants
├── core/
│   ├── db_products.py       # Products, groups, stock, discount levels
│   ├── db_checkout.py       # Receipts, sessions, refunds
│   ├── db_users.py          # Users, roles, login sessions
│   └── db_config.py         # Business info, settings, quick keys
├── ui/
│   ├── setup_wizard.py      # First-time setup
│   ├── login_window.py      # Login screen
│   ├── cashier/             # Cashier interface and dialogs
│   ├── supervisor/          # Supervisor tabs and tools
│   ├── manager/             # Manager settings and import tools
│   └── shared/              # Reusable widgets and theme
└── utils/
    ├── thermal_printer.py   # ESC/POS thermal printer driver
    ├── normal_printer.py    # A4/Letter printer via QPrinter
    ├── print_manager.py     # Print routing and receipt dispatch
    └── receipt_formatter.py # Plain-text receipt layout (42-char)
```

**Databases** (stored in `data/`)

| File | Contents |
|---|---|
| `products.db` | Products, groups, price groups, stock, discount levels |
| `checkout.db` | Receipts, receipt items, refunds, cashier sessions |
| `users.db` | User accounts, roles, login sessions |
| `config.db` | Business info, settings, quick keys |

---

## Requirements

- Python 3.11 or later
- PyQt6 6.9+

**Optional**
- `dbfread` — DBF stock file import
- `python-escpos` — USB thermal printer support
- `pyserial` — serial (RS-232) thermal printer support
- `pyusb` — USB device access
- `psycopg2-binary` — PostgreSQL sync

---

## Installation

### Run from source

```bash
git clone https://github.com/your-org/merchant-pos.git
cd merchant-pos
python3 -m venv venv
source venv/bin/activate
pip install PyQt6 dbfread python-escpos pyserial pyusb psycopg2-binary
python3 main.py
```

### Build — Linux (native)

```bash
chmod +x build_linux.sh
./build_linux.sh
# Output: dist/linux/MerchantPOS_Portable/
```

### Build — Windows (cross-compile from Linux via Wine)

```bash
chmod +x build_windows.sh
./build_windows.sh
# Output: dist/windows/MerchantPOS_Portable/
#         dist/windows/MerchantPOS_Setup.exe  (if Inno Setup available)
```

---

## First-Time Setup

On first launch with no database present, a setup wizard will guide you through:

1. Business name, address, phone, and tax ID
2. Terminal ID — a short unique code for this machine (e.g. `T01`, `MAIN`, `COUNTER2`). Used as a prefix on all receipt numbers (`T01-0001`, `T01-0002`) to prevent collisions across multiple terminals.
3. Tax rate and currency symbol
4. Manager account username and password
5. Printer configuration

All of these can be changed later from the Manager dashboard.

---

## Multi-Terminal Setup

Each POS computer is a terminal. Terminals operate independently and sync with a central PostgreSQL server.

- Every terminal gets a unique Terminal ID at setup
- Receipt numbers are prefixed with the terminal ID — no collisions
- Products and prices sync bidirectionally — a change on any terminal propagates to all others via PostgreSQL
- Receipts and sessions sync one-way to PostgreSQL as a central record
- If the PostgreSQL server is unreachable, each terminal continues operating normally on its local SQLite databases and queues changes for sync when the connection is restored

PostgreSQL connection details are configured in Manager → Settings → PostgreSQL.

---

## Printer Support

| Connection | How to configure |
|---|---|
| Network (TCP/IP) | Enter IP address, e.g. `192.168.1.100` or `192.168.1.100:9100` |
| Serial (RS-232) | Enter port, e.g. `COM3` (Windows) or `/dev/ttyUSB0` (Linux) |
| USB | Leave blank for auto-detect, or enter `USB001`. Set VID:PID in Advanced if needed. |
| Normal (A4/Letter) | Select from the OS printer list in Manager → Settings → Printers |

The USB VID:PID can be found in Device Manager on Windows or with `lsusb` on Linux. Format: `0416:5011`.

On Linux, the build script installs udev rules for common thermal printer vendor IDs automatically. If your printer is not detected, add its vendor ID to `/etc/udev/rules.d/99-merchantpos-printer.rules`.

---

## DBF Stock Import

The Manager → Import tab supports importing products from legacy `.dbf` stock files (dBase III format, commonly used by older POS systems). The file is expected to be named `stock.dbf` (any case) in a folder you select. The folder is remembered for future imports.

Fields imported: product name, barcode, selling price, cost, GCT flag, group, discount levels, and quantity on hand (if stock tracking is enabled).

---

## Roles

| Role | Access |
|---|---|
| Cashier | Cashier dashboard only |
| Supervisor | Cashier + supervisor tools (products, reports, void/refund, labels) |
| Manager | All supervisor access + settings, user management, import, sync |

---

## License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

This is required because the application uses **PyQt6**, which is itself licensed under GPL-3.0. Any application that distributes PyQt6 must also be GPL-3.0 licensed (or hold a commercial PyQt6 license from Riverbank Computing).

You are free to:
- Use, study, and modify the source code
- Distribute the application
- Build on this project

Under the condition that:
- Any distributed version (modified or unmodified) must also be released under GPL-3.0
- The source code must be made available to anyone who receives the binary

See [LICENSE](LICENSE) for the full license text, or visit [gnu.org/licenses/gpl-3.0](https://www.gnu.org/licenses/gpl-3.0.html).

> If you need to distribute a closed-source version of this software, you must purchase a commercial PyQt6 license from [Riverbank Computing](https://riverbankcomputing.com/commercial/pyqt).

---

## Built with AI

This project was designed and written with the assistance of **Claude**, an AI assistant made by Anthropic. The development process involved an extended conversation covering:

- Architecture design and database schema
- Feature implementation across all modules
- Bug diagnosis and fixing
- Multi-terminal receipt number strategy
- Printer driver implementation (thermal, serial, USB, A4)
- Build system (Linux and Windows cross-compile scripts)
- License selection

The human developer provided the domain knowledge, requirements, testing feedback, and direction. Claude provided the code, architectural reasoning, and technical implementation.

This README was also written by Claude.

---

## Contributing

Pull requests are welcome. For major changes, open an issue first to discuss what you would like to change.

Please ensure any changes are tested against both the Linux and Windows builds before submitting.

---

## Acknowledgements

- [PyQt6](https://riverbankcomputing.com/software/pyqt/) — Qt6 bindings for Python
- [dbfread](https://github.com/olemb/dbfread) — DBF file reader
- [python-escpos](https://github.com/python-escpos/python-escpos) — ESC/POS thermal printer library
- [PyInstaller](https://pyinstaller.org/) — Python application bundler
- [Claude by Anthropic](https://claude.ai) — AI assistant used throughout development
