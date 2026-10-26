# Ultimate OBD — OBD-II Code Reader (Python + ELM327)

Read and clear fault codes, watch live data, and check emissions readiness on
any OBD-II car (petrol 2001+ / diesel 2004+ in the EU/US). It works with a
Bluetooth or USB ELM327 adapter and treats every make the same way: the
standard OBD-II path is always available, and optional per-vehicle presets let
you add manufacturer-specific data when you have a documented source.

## Startup and installation

### What you need
- An ELM327 adapter (Bluetooth Classic or USB)
- Any OBD-II car, ignition ON
- Python 3.10+ on Windows (Tkinter is bundled with Python)

> iPhone: iOS blocks Bluetooth Classic. Use a BLE or Wi-Fi ELM327 instead.
> This app targets Windows with a Bluetooth Classic or USB adapter.

### Install
```bat
pip install -r requirements.txt
```

### Find the adapter
Pair the dongle in Windows Bluetooth settings, then list the ports:
```bat
py src/main.py --list-ports
```
Use the **outgoing** COM port shown in Device Manager > Ports (COM & LPT),
e.g. `COM4`. Common baud rates are 38400 and 115200; omit `--baud` to
auto-detect.

### Run
```bat
py src/gui.py --demo      :: interface with no car connected
py src/gui.py             :: connect to a real car
```
CLI equivalents (run from the project root):
```bat
py src/main.py --demo --read --im
py src/main.py --port COM4 --read --im
```
`--port` can be omitted to let the library scan for the adapter.

### Build a Windows .exe (optional)
```bat
pip install pyinstaller
py -m PyInstaller OBDReader.spec
```
This produces `dist/OBDReader-GUI.exe` and `dist/OBDReader-CLI.exe`. Rebuild
after code changes; `build/` is a regenerable cache. The GUI writes session
logs to `logs/` next to the executable.

### If it won't connect
- **No COM ports** — the dongle isn't paired. Re-pair it and confirm you are
  using the outgoing port.
- **ELM Error / Not Connected** — wrong baud, wrong port, or ignition OFF.
  Try `--baud 38400`, then `--baud 115200`, and reseat the dongle.
- **No data** — protocol auto-detect failed. Try `--protocol 6` (CAN 11/500,
  common on 2008+ cars) or check the fuse for the OBD socket.

## How it works

### Connect and identify
The GUI opens on **Connect**. **Connect & detect vehicle** reads the VIN
(Mode 09 PID 02, standard on every OBD-II car) and decodes make and year. The
model is user-confirmed from the make's model list because VIN model blocks
aren't standardised. If the VIN is unreadable, set make/model/year manually —
the app never substitutes a fake identity. Makes outside the built-in list
fall back to the same generic profile, so no car is locked out.

### What the app reads
- **Engine** — stored, pending and permanent DTCs (Modes 03/07/0A), MIL state,
  freeze frame (Mode 02), Mode 06 monitor tests, and ECU calibration IDs/CVNs.
- **Live data** — standard PIDs such as RPM, speed, coolant, load, fuel trims,
  MAF, fuel level and voltage. Gauges and charts live on the Engine page; the
  CLI can stream samples to CSV.
- **I/M readiness** — which emissions monitors have completed since the last
  code clear (Mode 01 PID 01).
- **ABS/chassis** — C-codes exposed through the generic modes, plus a module
  probe that reports raw replies: data, explicit rejection, or silence.
- **TPMS** — known TPMS fault codes from the generic modes. Live per-corner
  pressures and sensor-ID registration have no standard OBD-II PID, so they
  only run from a verified per-vehicle preset.
- **Health report** — a PDF summary written to `logs/`.

### Generic first, presets for the rest
Everything standardised — engine codes, live PIDs, readiness, freeze frame,
Mode 06 and Mode 09 — works on every car. Anything manufacturer-specific —
ABS module access, live TPMS pressures, transmission temperature — needs a
documented header/PID for the exact make/model/year. Those live in empty
preset tables (`ABS_PRESETS`, `TRANSMISSION_PRESETS`, `TPMS_PRESETS`,
`TPMS_REGISTER_PRESETS`), so the app never sends guessed bytes to an ECU.
Add an entry only when you have a service-manual or captured-tool source.

### CLI reference
| Command | What it does |
| --- | --- |
| `--read` / `--clear` | Read stored engine codes / clear codes and the MIL |
| `--live` / `--monitor` | One live-data snapshot / continuous streaming |
| `--monitor --log drive.csv` | Stream live data and log it to CSV |
| `--im` | I/M readiness monitors |
| `--mode06` / `--freeze` / `--ecu-info` | Monitor tests / freeze frame / Mode 09 |
| `--health` | Full PDF health report into `logs/` |
| `--abs-read` / `--abs-probe` / `--abs-clear` | ABS C-codes / raw probe / ABS clear |
| `--abs-raw "19 02 FF" --tx-header 7E1` | Send a documented raw module query |
| `--tpms-read` / `--tpms-live` / `--tpms-raw` | TPMS codes / pressures / raw query |
| `--tpms-register FL FR RL RR` | Write four sensor IDs (preset required) |
| `--atf` | Transmission temperature (preset required) |
| `--vin [--make X --model Y --year N]` | Detect or set the vehicle profile |

`--clear` and `--abs-clear` send Mode 04, which also resets I/M readiness to
NOT READY. Fix or record the fault first.

### Files and layout
```
Ultimate-OBD/
  README.md
  requirements.txt
  OBDReader.spec        PyInstaller build definition
  logs/                 session logs and PDF health reports
  src/
    main.py             CLI dispatcher
    gui.py              Tkinter GUI shell and page handlers
    ui/                 theme and reusable widgets
    features/
      obd_core.py       connection, VIN/profile, engine DTCs, live data
      im_readiness.py   I/M monitors
      abs_module.py     ABS codes, probe, per-vehicle presets
      tpms_module.py    TPMS codes, pressures, sensor registration
      health_report.py  PDF report
      obd_client.py     facade composing the client used by the GUI
      vehicle_db.py     make/model list and WMI prefixes
```

### Logs
The GUI saves the session log automatically on shutdown as
`Make_Model_Year_YYYYMMDD_HHMMSS.log` (e.g. `Honda_Civic_2007_20261001_143022.log`;
`Unknown_*` when the vehicle is unset). Demo mode simulates idle, acceleration,
cruise and deceleration, so gauges and charts move without a car.
