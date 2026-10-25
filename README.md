# OBD-II Code Reader (Python + ELM327 Bluetooth)

Reads and clears engine fault codes via a Bluetooth ELM327 dongle.

## Hardware
- ELM327 Bluetooth Classic dongle (paired in Windows first)
- Car with OBD-II port (all petrol 2001+/diesel 2004+ in EU/US), ignition ON

> iPhone users: iOS blocks Bluetooth Classic — use a BLE 4.0 or WiFi ELM327 instead
> and use the Flutter/Web variant. This Python app targets Windows + Bluetooth Classic.

## Setup
```bat
pip install -r requirements.txt
```

## Find your COM port
```bat
py src/main.py --list-ports
```
Pair the dongle in Windows Bluetooth settings first, then look in
Device Manager > Ports (COM & LPT) for e.g. `Standard Serial over Bluetooth link (COM4)`
— use the **outgoing** one. Common baud rates: 38400, 115200. In the GUI the
port box offers **Auto** (library scans), the detected ports, or type one
manually; `--port` omitted in the CLI also means auto.

## Project layout
```
DefaultProject/
  README.md
  requirements.txt
  PyCache/          <- Python bytecode cache (set PYTHONPYCACHEPREFIX=PyCache
                       to keep .pyc files here instead of __pycache__ folders)
  logs/             <- session logs, auto-saved on GUI shutdown as
                       Make_Model_Year_YYYYMMDD_HHMMSS.log
  src/
    main.py         <- thin CLI dispatcher (run from root: py src/main.py ...)
    gui.py          <- Tkinter GUI shell, pages, handlers (py src/gui.py ...)
    ui/             <- visual layer (pure Tkinter/ttk, no extra dependencies)
      theme.py          palette, fonts, ttk styles
      widgets.py        cards, nav rail, gauges, trend charts, toggle, tables
    features/       <- one module per function area, all executed from main.py
      obd_core.py       connection, VIN/compatibility, engine DTCs, live data
      im_readiness.py   I/M monitors
      abs_module.py     ABS/chassis codes + probing
      tpms_module.py    TPMS codes/pressures/registration
      obd_client.py     facade composing OBDClient (used by the GUI)
      vehicle_db.py     top-10 brands x top-10 models, WMI prefixes
```
All commands below run from the project root, e.g. `py src/main.py --demo --read`.

## Try without a car (demo)
```bat
py src/main.py --demo --vin --read --abs-read
py src/gui.py --demo
```
Demo uses a sample 2018 Toyota VIN, so the Connect page shows the Toyota profile.

## Real car — CLI
```bat
py src/main.py --port COM4 --read --im
py src/main.py --port COM4 --live
py src/main.py --port COM4 --monitor --interval 1 --count 60 --log drive.csv
py src/main.py --port COM4 --clear
```
`--im` shows I/M readiness (Mode 01 PID 01): READY / NOT READY per monitor.
`--mode06` shows monitor test values vs limits (catches faults before codes set).
`--freeze` shows the Mode 02 snapshot stored with the DTC.
`--ecu-info` shows full Mode 09 (VIN, calibration IDs, CVNs — spot a remap).
`--health` runs everything and writes a PDF report into `logs/`.
`--monitor` streams live PIDs continuously, optional CSV log.
`--clear` sends Mode 04 (clears codes + turns off check-engine light, resets I/M).
If baud fails, retry: `--baud 38400` or `--baud 115200`.

## Connect page + compatibility (top-10 brands)
On launch the app opens on **Connect**. Press **Connect & detect vehicle**: it
reads the VIN (Mode 09 PID 02, standard on every car) and sets the reader
profile — make, year, protocol hint, ABS path. Covered brands (WMI-based detect
+ top-10 model picker on the Connect page, all OBD-II years via standard
year-code decode):
Toyota, Volkswagen, Ford, Honda, Nissan, Hyundai, GM, Kia, Mercedes, BMW
(see `vehicle_db.py`). Other makes fall back to a working generic profile.
The model is user-confirmed from the list — VIN VDS blocks aren't standardised,
so the app never guesses it. If the VIN itself is unreadable (some cars/adapters
reject Mode 09 PID 02), the app says Unknown and you set make/model/year
manually on the Connect page (`--make/--model/--year` in CLI) — it never substitutes the
demo identity on a real car. Toyota cars additionally get the 7B0 ABS-module
attempt plus a raw Mode 21 PID 82 ATF-temp probe (scaling must be verified per
model). `py src/main.py --port COM4 --vin [--model Corolla]` prints the same in CLI.

## TPMS
```bat
py src/main.py --port COM4 --tpms-read
py src/main.py --port COM4 --tpms-live
```
`--tpms-read` scans generic Modes 03/07/0A for known sensor/transmitter codes
(C075x/C076x/C077x, C211x, B2872). Live per-corner pressures have no standard
OBD-II PID, so `--tpms-live` only returns real data once your exact model's
Mode 22/UDS address is added to `TPMS_PRESETS` (documented shape, no guessed
entries) — otherwise it explains the options. `--tpms-raw "22 XXXX"
--tx-header <hdr>` queries with your documented values. Sensor registration /
relearn always needs the car's own procedure (owner's manual) or brand tooling.
Target pressures are on the door-jamb sticker, not in the app, since they vary
by trim/load.

## Manually set TPMS sensor IDs
```bat
py src/main.py --port COM4 --tpms-register 1A2B3C4 2B3C4D5 3C4D5E6 4D5E6F7
```
(Or the TPMS page → enter the 4 IDs → Register IDs.) IDs are 7–8 hex digits from the
sensor bodies or scan-tool printout, must be unique per corner, ignition ON /
engine OFF. The write runs only from a verified routine in
`TPMS_REGISTER_PRESETS` for your exact make/model/year — with none present the
app refuses and tells you what's needed instead of sending guessed bytes to an
ECU. No verified routine ships yet (none is publicly documented for generic
adapters), so on a real car today this validates your IDs and points at the
next step: brand tooling or the model's documented routine.

## Toyota ABS blink codes (pre-2010 models, e.g. 2007 Camry)
When the ABS module rejects electronic reads (probe shows 0x11 rejections),
Toyota's DLC3 jumper procedure still works — no scan tool needed:
1. Ignition OFF. At the OBD port, jumper terminals **Tc (13) to CG (4)**
   (a paperclip works; pin numbers are molded into the connector).
2. Ignition ON, engine OFF. Count the ABS light blinks: 2-digit codes,
   e.g. blink-blink-pause-blink = 21. Write down all codes shown.
3. Commonly reported wheel-speed codes: 31/32/33/34 (one per corner —
   confirm corner mapping in the service manual for your year).
4. Clear (after repair): with the jumper in, press the brake pedal **8+ times
   within 5 seconds** — light should switch to steady/blink-normal.
This is the documented Toyota procedure for this era; the app's electronic
ABS path remains for models whose module answers it.

## ABS codes — CLI
```bat
py src/main.py --port COM4 --abs-read
py src/main.py --port COM4 --abs-clear
```
`--abs-read` filters chassis (C-code) faults out of Modes 03/07/0A — this works
on many cars, but some makes gate the ABS module behind a proprietary
header/PID. `--abs-probe` shows exactly what the module says back
(data / rejection / silence). For advanced use, `--abs-raw "19 02 FF"
--tx-header 7B0` (with your make's documented values) talks to the ABS ECU
directly; see `ABS_PRESETS` in `src/features/abs_module.py`. `--atf` reads
Toyota ATF temp raw (Mode 21 PID 82, scaling varies). `--abs-clear` uses
Mode 04, which clears the ABS light
on most cars — if the light stays on, the fault is still present or your
make needs a dealer-level routine.

## Real car — GUI
```bat
py src/gui.py
```
The window is a dark dashboard: a **navigation rail** on the left, a page header
with the live connection pill (and a **DEMO** badge in demo mode), card-based
content, and a docked **Session Log** pane at the bottom that you can resize by
dragging the sash. All five pages are built at launch and reachable from the
rail: **Connect** (COM port, Connect & detect, vehicle identity card with
make/year/model pickers), **Engine** (fault codes, Mode 06, freeze frame, ECU
info, health report, realtime gauges/charts + live PID table), **ABS**,
**I/M Readiness**, and **TPMS**. The rail also shows the detected vehicle, VIN
and protocol, and every action reports into the log pane.
Connecting auto-detects the vehicle and jumps to the Engine page.
On every shutdown the log is saved to `logs/` automatically, named
`Make_Model_Year_YYYYMMDD_HHMMSS.log`
(e.g. `Toyota_Camry_2007_20261001_143022.log`, `Unknown_…` when unset).
Demo drive cycle: `py src/gui.py --demo` simulates idle → accelerate → cruise → decel
so gauges/charts visibly move without a car.

## Packaging (Windows .exe)
```bat
pip install pyinstaller
py -m PyInstaller OBDReader.spec
```
Produces `dist/OBDReader-GUI.exe` (windowed) and `dist/OBDReader-CLI.exe`
(console) — single files, no Python install needed on the target PC (~40 MB
total: 22 MB GUI + 18 MB CLI). Notes:
- Rebuild after any code change; `build/` is a regenerable cache (safe to delete).
- The GUI exe writes its session logs to `logs/` next to the .exe (frozen-aware path).
- Bluetooth pairing is still done in Windows Settings — the exe cannot pair for you.
- First launch may be slow (one-file unpack) and Windows SmartScreen/antivirus
  may flag the unsigned exe: unblock in file properties or sign it.
- Verified: CLI exe runs all demo commands; GUI exe launches and stays up.

## Files
- `src/main.py` — thin CLI dispatcher (parses args, connects, calls each module's `run_*`)
- `src/features/obd_core.py` — connection, VIN/compatibility, engine DTCs, live data,
  Mode 06, freeze frame, Mode 09
- `src/features/health_report.py` — one-click PDF health report into `logs/`
- `src/features/im_readiness.py` — I/M monitors
- `src/features/abs_module.py` — ABS/chassis codes, probing
- `src/features/tpms_module.py` — TPMS codes/pressures/registration
- `src/features/obd_client.py` — facade composing `OBDClient` (used by the GUI)
- `src/features/vehicle_db.py` — top-10 brands × top-10 models, WMI prefixes
- `src/gui.py` — Tkinter GUI shell: sidebar navigation, page headers, feature pages,
  handlers, and the worker→UI queue pump
- `src/ui/theme.py` — design system: dark palette, fonts, ttk styles
- `src/ui/widgets.py` — reusable widgets: `Card`, `NavItem`, `PageStack`, `Gauge`,
  `TrendChart`, `Toggle`, striped table helpers

## Troubleshooting
- `No COM ports`: dongle not paired — re-pair, check outgoing vs incoming port.
- `ELM Error / Not Connected`: wrong baud, ignition OFF, or wrong COM port.
  Try other baud rates, ignition ON (engine off), reseat dongle.
- `No data`: protocol auto-detect failed — try `--protocol 6` (CAN 11/500, common
  for 2008+ cars) or check fuse for OBD port.
