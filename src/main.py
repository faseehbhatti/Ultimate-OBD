"""CLI dispatcher: parses args, connects, executes feature modules.

Each function lives in its own module; main.py only routes:
  obd_core     --vin/--make/--model/--year, --read, --clear, --live, --monitor
  im_readiness --im
  abs_module   --abs-read, --abs-clear, --abs-raw, --abs-probe, --atf
  tpms_module  --tpms-read, --tpms-live, --tpms-raw, --tpms-register

Example:  py src/main.py --demo --read --im
"""

from __future__ import annotations

import argparse
import sys

from features.abs_module import run_abs
from features.health_report import run_health
from features.im_readiness import run_im
from features.obd_client import OBDClient, list_serial_ports
from features.obd_core import (run_ecuinfo, run_engine, run_engine_clear, run_freeze,
                               run_live, run_mode06, run_monitor, run_vin)
from features.tpms_module import run_tpms


def cmd_list_ports():
    ports = list_serial_ports()
    if not ports:
        print("No COM ports found. Pair your ELM327 in Windows Bluetooth first,")
        print("then check Device Manager > Ports (COM & LPT) for outgoing COM port.")
    else:
        print("Available ports:")
        for p in ports:
            print(f"  {p}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read / clear car OBD-II fault codes (ELM327).")
    ap.add_argument("--port", help="COM port, e.g. COM4. Omit for auto-detect.")
    ap.add_argument("--baud", type=int, default=None, help="e.g. 38400 or 115200. Omit for auto.")
    ap.add_argument("--protocol", default=None, help="OBD protocol id, e.g. 6 for CAN 11/500. Usually omit (auto).")
    ap.add_argument("--demo", action="store_true", help="Demo mode, no car needed.")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--vin", action="store_true", help="Read VIN and show detected compatibility profile.")
    ap.add_argument("--model", default=None, help="Confirm model from brand top-10 list, e.g. --model Corolla.")
    ap.add_argument("--make", default=None, help="Manually set make when VIN is unreadable, e.g. --make Toyota.")
    ap.add_argument("--year", type=int, default=None, help="Manually set model year, e.g. --year 2007.")
    ap.add_argument("--read", action="store_true", help="Read stored DTCs.")
    ap.add_argument("--clear", action="store_true", help="Clear DTCs / turn off MIL.")
    ap.add_argument("--live", action="store_true", help="Show live sensor data once.")
    ap.add_argument("--im", action="store_true", help="Show I/M readiness monitors (Mode 01 PID 01).")
    ap.add_argument("--mode06", action="store_true", help="Show Mode 06 monitor test results.")
    ap.add_argument("--freeze", action="store_true", help="Show freeze-frame snapshot (Mode 02).")
    ap.add_argument("--ecu-info", action="store_true", help="Show full Mode 09 info (VIN, CALID, CVN).")
    ap.add_argument("--health", action="store_true", help="One-click health report PDF into logs/.")
    ap.add_argument("--monitor", action="store_true", help="Continuously monitor live data.")
    ap.add_argument("--abs-read", action="store_true", help="Read ABS/chassis (C-code) faults.")
    ap.add_argument("--abs-clear", action="store_true", help="Clear ABS codes via Mode 04.")
    ap.add_argument("--abs-raw", default=None,
                    help="Advanced: raw ABS-module command, e.g. '19 02 FF'.")
    ap.add_argument("--abs-probe", action="store_true",
                    help="Probe the ABS module header directly and show raw replies.")
    ap.add_argument("--atf", action="store_true",
                    help="Toyota ATF temp via Mode 21 PID 82 (raw, scaling varies).")
    ap.add_argument("--tpms-read", action="store_true", help="Read TPMS fault codes.")
    ap.add_argument("--tpms-live", action="store_true", help="Show live tire pressures (preset/unsupported info).")
    ap.add_argument("--tpms-raw", default=None,
                    help="Advanced: raw TPMS-module command, e.g. '22 XXXX'.")
    ap.add_argument("--tpms-register", nargs=4, metavar=("FL", "FR", "RL", "RR"),
                    help="Manually set TPMS sensor IDs, e.g. --tpms-register 1A2B3C4 2B3C4D5 3C4D5E6 4D5E6F7.")
    ap.add_argument("--tx-header", default=None,
                    help="Advanced: CAN header for --abs-raw, e.g. 7B0.")
    ap.add_argument("--interval", type=float, default=1.0, help="Monitor poll interval in seconds (default 1.0).")
    ap.add_argument("--count", type=int, default=0, help="Monitor samples to take (0=infinite, Ctrl+C to stop).")
    ap.add_argument("--log", default=None, help="CSV file to log monitor samples, e.g. drive.csv.")
    args = ap.parse_args(argv)

    if args.list_ports:
        cmd_list_ports()
        return 0

    if not (args.read or args.clear or args.live or args.im or args.monitor
              or args.abs_read or args.abs_clear or args.abs_raw or args.vin or args.model
              or args.make or args.year
              or args.tpms_read or args.tpms_live or args.tpms_raw or args.tpms_register
              or args.abs_probe or args.atf
              or args.mode06 or args.freeze or args.ecu_info or args.health):
        ap.print_help()
        print("\nTip: start with  py src/main.py --demo --read")
        return 2

    client = OBDClient(demo=args.demo)
    try:
        print(client.connect(port=args.port, baudrate=args.baud, protocol=args.protocol))
    except Exception as e:
        print(f"CONNECT FAILED: {e}", file=sys.stderr)
        return 1

    try:
        steps = [
            (args.vin or args.model or args.make is not None or args.year is not None, run_vin),
            (args.read, run_engine),
            (args.live, run_live),
            (args.im, run_im),
            (args.monitor, run_monitor),
            (args.tpms_read or args.tpms_live or args.tpms_raw or args.tpms_register, run_tpms),
            (args.abs_read or args.abs_raw or args.abs_probe or args.abs_clear or args.atf, run_abs),
            (args.mode06, run_mode06),
            (args.freeze, run_freeze),
            (args.ecu_info, run_ecuinfo),
            (args.health, run_health),
            (args.clear, run_engine_clear),
        ]
        for want, run in steps:
            if want:
                rc = run(client, args)
                if rc:
                    return rc
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
