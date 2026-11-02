# Ultimate OBD

OBD-II reader for any car. Read/clear codes, live data, I/M readiness. Works with Bluetooth/USB ELM327.

## Setup

- ELM327 adapter (Bluetooth Classic/USB)
- OBD-II car, ignition ON
- Python 3.10+ on Windows

> iOS blocks Bluetooth Classic. Use BLE/Wi-Fi ELM327.

```bat
pip install -r requirements.txt
py src/main.py --list-ports
```

Use outgoing COM port from Device Manager > Ports (COM & LPT), e.g. `COM4`. Baud auto-detects (38400/115200).

```bat
py src/gui.py --demo
py src/gui.py
```

CLI:
```bat
py src/main.py --demo --read --im
py src/main.py --port COM4 --read --im
```

### Build
```bat
pip install pyinstaller
py -m PyInstaller OBDReader.spec
```
Produces `dist/OBDReader-GUI.exe` and `dist/OBDReader-CLI.exe`.

### Troubleshooting
- No COM ports: pair adapter, use outgoing port.
- Can't connect: wrong baud/port/ignition OFF. Try 38400/115200.
- No data: try `--protocol 6` or check OBD fuse.

## How it works

### Connect
VIN read via Mode 09 PID 02 where possible. Pick make/model/year if unreadable. Unknown makes use generic profile.

### Reads
- Engine: DTCs (03/07/0A), MIL, freeze frame (02), Mode 06, Mode 09
- Live PIDs, I/M readiness (01 PID 01)
- ABS C-codes + module probe
- TPMS codes; live pressures/ID writes need per-vehicle preset
- Health report PDF in `logs/`

### Presets
Standard PIDs/codes work on all cars. Manufacturer-specific (ABS module access, live TPMS, trans temp) needs documented header/PID in preset tables; never guessed.

### CLI
| Command | Does |
| --- | --- |
| `--read` / `--clear` | Read / clear engine codes + MIL |
| `--live` / `--monitor` | Snapshot / continuous live data |
| `--monitor --log drive.csv` | Stream to CSV |
| `--im` | I/M readiness |
| `--mode06` / `--freeze` / `--ecu-info` | Monitor tests / freeze frame / Mode 09 |
| `--health` | PDF report to `logs/` |
| `--abs-read` / `--abs-probe` / `--abs-clear` | ABS codes / raw probe / clear |
| `--abs-raw "19 02 FF" --tx-header 7E1` | Raw module query |
| `--tpms-read` / `--tpms-live` / `--tpms-raw` | TPMS codes / pressures / raw |
| `--tpms-register FL FR RL RR` | Write sensor IDs (preset required) |
| `--atf` | Trans temperature (preset required) |
| `--vin [--make X --model Y --year N]` | Detect / set vehicle |

`--clear` and `--abs-clear` reset I/M readiness.

### Layout
```
src/
  main.py       CLI
  gui.py        GUI
  ui/           theme, widgets, fonts
  features/     OBD, IM, ABS, TPMS, report, vehicle DB
logs/           session logs, PDFs
```

### Logs
Auto-saved on exit: `Make_Model_Year_YYYYMMDD_HHMMSS.log`. Demo mode simulates driving.
