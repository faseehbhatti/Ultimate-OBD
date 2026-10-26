"""ABS / chassis DTCs, module probing. Executed from main.py via run_abs."""

from __future__ import annotations

import time

from features.obd_core import COMMON_DTC_DESCRIPTIONS, DTC, vehicle_key

# Descriptions for common ABS/chassis (C0xxx) codes. Corner assignment
# (FL/FR/RL/RR) varies by make — descriptions stay generic on purpose.
ABS_DTC_DESCRIPTIONS = {
    "C0035": "Left Front Wheel Speed Sensor Circuit",
    "C0040": "Right Front Wheel Speed Sensor Circuit",
    "C0045": "Left Rear Wheel Speed Sensor Circuit",
    "C0050": "Right Rear Wheel Speed Sensor Circuit",
    "C0110": "ABS Pump Motor Circuit",
    "C0121": "ABS Valve Relay Circuit",
    "C0131": "ABS Pressure Circuit",
    "C0161": "Brake Switch / Stop Lamp Switch Circuit",
    "C0221": "Wheel Speed Sensor Signal Erratic (corner varies by make)",
    "C0222": "Wheel Speed Sensor Signal Missing (corner varies by make)",
    "C0235": "Rear Wheel Speed Signal Erratic",
    "C0236": "Rear Wheel Speed Signal Missing",
    "C0242": "PCM Indicated Traction Control Malfunction",
    "C0245": "Wheel Speed Sensor Frequency Error",
    "C0265": "EBCM Relay Circuit",
    "C0267": "ABS Pump Motor Circuit Open",
    "C0268": "ABS Pump Motor Circuit Shorted",
    "C0550": "ABS ECU Internal Malfunction",
    "C0561": "Traction Control System Disabled (invalid data)",
    "C0710": "Steering Position Signal Malfunction",
    "C0800": "ABS Device Power Circuit Low/High",
    "U0121": "Lost Communication With ABS Control Module",
    "C1201": "Engine Control System Malfunction (often set alongside ABS codes)",
    "C1210": "Yaw Rate Sensor Zero Point / Circuit — calibration or sensor",
    "C1223": "ABS Control System Malfunction",
    "C1241": "Low Battery Positive Voltage to ABS ECU — check 12V battery/charging",
    "C1246": "Master Cylinder Pressure Sensor Malfunction",
    "C1310": "HV System Malfunction Reported in Skid ECU — check hybrid system codes",
    "C1336": "Zero Point Calibration Undone, Yaw/Deceleration Sensor — calibrate; common after battery disconnect",
    "C1345": "Linear Solenoid Valve Offset Learning Undone — perform learning procedure",
}

# UDS/KWP negative-response codes (NRC) for probe verdicts.
NRC_DESCRIPTIONS = {
    "10": "general reject", "11": "service not supported",
    "12": "sub-function not supported", "13": "bad message length/format",
    "22": "conditions not correct (e.g. wrong ignition state)",
    "24": "request sequence error (a setup step is missing)",
    "31": "request out of range", "33": "security access denied",
    "35": "invalid key", "36": "too many attempts", "37": "try again later",
    "70": "upload/download not accepted", "72": "programming failure",
    "73": "wrong block sequence", "78": "response pending",
    "7E": "sub-function not supported in this session",
    "7F": "service not supported in this session",
}


def decode_negative_response(reply: str) -> str | None:
    """
    If reply is a single-frame negative response ('7E9 03 7F 03 11'),
    return 'rejected Mode 03: service not supported'. Else None.
    Never raises.
    """
    try:
        b = "".join(str(reply).split()).upper()
        i = b.find("7F")
        if i < 0 or len(b) < i + 6:
            return None
        svc, nrc = b[i + 2:i + 4], b[i + 4:i + 6]
        what = NRC_DESCRIPTIONS.get(nrc, f"code 0x{nrc}")
        return f"rejected service 0x{svc}: {what}"
    except Exception:
        return None


# Per-vehicle starting points for talking to the ABS ECU directly.
# These are NOT guaranteed for your car: headers/PIDs differ by model/year.
# How to fill in yours: service manual, extended-PID list, or sniff with
# probe_abs_module(). Mode 19 02 = UDS "read DTCs by status".
# Keyed "make-model-year" (lowercase), same as vehicle_key() in obd_core.
# EMPTY ON PURPOSE — only add an entry you have verified for that vehicle.
# Documented shape:
# ABS_PRESETS = {
#   "example-make-example-model-2020": {
#       "tx_header": "7E1", "dtc_cmd": "19 02 FF",
#       "source": "service manual / verified",
#   },
# }
ABS_PRESETS: dict[str, dict] = {}


# Manufacturer-specific live values (e.g. transmission/ATF temperature) have
# no standard OBD-II PID. Keyed "make-model-year"; empty on purpose — a wrong
# guess can decode garbage. Documented shape:
# TRANSMISSION_PRESETS = {
#   "example-make-example-model-2020": {
#       "pid": "21A0", "tx_header": "7E1",
#       "source": "service manual / verified",
#   },
# }
TRANSMISSION_PRESETS: dict[str, dict] = {}


class ABSMixin:
    # ---------- ABS (chassis) DTC read / clear ----------
    # Honest scope note: generic OBD-II Mode 03 exposes powertrain codes and,
    # on many cars, also chassis (C0xxx) ABS codes. Dedicated ABS-module
    # access (Mode 22 / UDS 19) is make/model-specific — see ABS_PRESETS and
    # query_abs_raw() for the extension path.
    def read_abs_dtcs(self) -> tuple[list[DTC], dict]:
        """
        Best-effort ABS read: pulls Modes 03/07/0A and filters chassis codes
        (C0xxx-C3xxx). On cars that gate ABS behind a proprietary module this
        returns empty with a note — use query_abs_raw() with your make's
        header/PID (see ABS_PRESETS).
        """
        if self.demo:
            return list(self._demo_abs_dtcs), {
                "source": "demo", "scanned": ["03", "07", "0A"],
                "note": "demo ABS data",
            }
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd

        seen: dict[str, DTC] = {}
        sources: list[str] = []

        def _add(code: str, desc: str = ""):
            if not code.startswith("C") or code in seen:
                return
            if not desc:
                desc = ABS_DTC_DESCRIPTIONS.get(code, COMMON_DTC_DESCRIPTIONS.get(code, ""))
            seen[code] = DTC(code, desc)

        def _collect(cmd, tag: str):
            if cmd is None:
                return
            try:
                # Skip commands the car flagged unsupported at connect.
                if not self.connection.supports(cmd):
                    return
                r = self.connection.query(cmd)
            except Exception:
                return
            if r.is_null():
                return
            sources.append(tag)  # ECU answered (even if it reports zero codes)
            v = r.value
            # FREEZE_DTC (01 02) is a single tuple, the rest are lists.
            if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
                items = [v]
            else:
                items = list(v or [])
            for t in items:
                code = t[0] if isinstance(t, tuple) else str(t)
                desc = t[1] if isinstance(t, tuple) and len(t) > 1 else ""
                _add(code, desc)

        _collect(obd.commands.GET_DTC, "03-confirmed")
        _collect(obd.commands.GET_CURRENT_DTC, "07-pending")
        _collect(obd.commands.FREEZE_DTC, "01-02-freeze")
        _collect(getattr(obd.commands, "PERMANENT_DTC", None), "0A-permanent")

        # Verified per-vehicle preset: additionally ask the ABS ECU directly.
        preset = ABS_PRESETS.get(vehicle_key(self.profile))
        if preset and preset.get("dtc_cmd"):
            for code in self._module_dtcs(preset):
                _add(code)
            tag = f"module-{preset.get('tx_header') or 'default'}"
            if tag not in sources:
                sources.append(tag)

        if not seen and not sources:
            note = ("ECU did not answer any generic mode — check ignition ON, "
                    "retry, or re-seat the dongle. (An engine read in the same "
                    "session tells you whether the link itself is alive.)")
        elif not seen:
            note = ("ECU answered generic modes but reported zero codes. With the "
                    "ABS light on, the codes are almost certainly inside the ABS "
                    "module — run Probe Module and paste the raw replies.")
        else:
            note = f"{len(seen)} ABS/chassis code(s) reported by the ECU."
        info = {"source": "OBD " + ("/".join(sources) if sources else "no response"),
                "scanned": sources, "note": note}
        return list(seen.values()), info


    def _module_dtcs(self, preset: dict) -> list[str]:
        """
        Ask the ABS ECU for DTCs using a verified ABS_PRESETS entry for this
        vehicle, via the library's own per-command header support. Returns []
        on NO DATA / errors. Never raises.
        """
        try:
            import obd
            from obd.decoders import dtc as dtc_decoder
            from obd.protocols import ECU
            cmd = obd.OBDCommand(
                "ABS_MODULE_DTC", "ABS module DTC",
                preset["dtc_cmd"].replace(" ", "").encode(),
                0, dtc_decoder, ecu=ECU.ALL,
                header=preset["tx_header"].encode())
            r = self.connection.query(cmd, force=True)
            if r.is_null():
                return []
            return [t[0] for t in (r.value or []) if isinstance(t, tuple)]
        except Exception:
            return []


    def read_atf_temp(self) -> dict:
        """
        Manufacturer-specific transmission/ATF temperature (Mode 21/22 raw).

        Only returned when a verified TRANSMISSION_PRESETS entry exists for
        this vehicle. Scaling varies by model, so the raw reply is shown for
        comparison with the dash/brand tool.
        """
        if self.demo:
            return {"supported": True, "raw": "21 A0 -> 7E8 04 61 A0 1A 0B (...)",
                    "demo_C": 78.5, "note": "demo value; verify scaling on a real car"}
        if not self.is_connected():
            raise ConnectionError("Not connected.")
        preset = TRANSMISSION_PRESETS.get(vehicle_key(self.profile))
        if not preset:
            return {"supported": False,
                    "note": ("No verified transmission-temperature preset for this "
                             "vehicle. Add one to TRANSMISSION_PRESETS using your "
                             "documented Mode 21/22 PID and header.")}
        try:
            raw = self.query_module(preset["pid"], tx_header=preset.get("tx_header"))
            return {"supported": True, "raw": raw,
                    "note": "Raw response. Scaling varies by model — compare with "
                            "the dash/brand tool before trusting a conversion."}
        except Exception as e:
            return {"supported": False, "note": f"Query failed ({e})"}


    def clear_abs(self) -> dict:
        """
        Attempt ABS lamp reset via Mode 04 (same bus command as engine clear).
        On most cars this also clears ABS C-codes and the ABS light; some
        makes require their own tool/routine. Returns {ok, warning}.
        """
        if self.demo:
            self._demo_abs_dtcs = []
            self._demo_dtcs = []  # Mode 04 clears everything in demo too
            return {"ok": True, "warning": "demo: ABS codes cleared"}
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd
        r = self.connection.query(obd.commands.CLEAR_DTC)
        if r.is_null():  # cheap clones sometimes drop the first request — retry once
            time.sleep(1.0)
            r = self.connection.query(obd.commands.CLEAR_DTC)
        ok = not r.is_null()
        return {"ok": ok,
                "warning": ("If the ABS light stays on, the fault is still present or your "
                            "make needs a module-specific clear (dealer-level tool). "
                            "Also note: Mode 04 resets I/M readiness to NOT READY.")}


    def probe_abs_module(self, header: str | None = None,
                         commands: tuple[str, ...] = ("03", "19 02 FF", "18 00 FF 00")) -> dict:
        """
        Diagnostic probe: send ABS read commands straight at the module header
        and report verdicts — real data vs explicit rejection (7F…) vs silence.
        The KWP2000 '18 00 FF 00' candidate is included because mid-2000s ECUs
        often speak KWP2000 rather than UDS; all attempts are read-only.
        Default header comes from an ABS_PRESETS entry for this vehicle, else
        7E1 (the usual second CAN diagnostic address).
        """
        if self.demo:
            return {"header": header or "7E1", "answered": True,
                    "attempts": [{"cmd": "03", "reply": "(demo) 7E9 06 43 02 C0 35 00 C0 11 00",
                                  "data": True}],
                    "note": "demo reply"}
        if not self.is_connected():
            return {"header": header or "?", "answered": False, "attempts": [],
                    "note": "Not connected."}
        preset = ABS_PRESETS.get(vehicle_key(self.profile), {})
        hdr = header or preset.get("tx_header") or "7E1"
        attempts: list[dict] = []
        answered = False
        for cmd in commands:
            try:
                reply = self.query_abs_raw(cmd, tx_header=hdr)
            except Exception as e:
                reply = f"ERROR: {e}"
            flat = "".join(str(reply).split()).upper()
            neg = decode_negative_response(reply)
            if neg is not None:
                verdict = neg  # module alive, explicitly refusing this service
                has_data = False
            else:
                has_data = bool(flat) and "NODATA" not in flat and "ERROR" not in flat
                verdict = "data" if has_data else "silent (NO DATA)"
            answered = answered or has_data
            attempts.append({"cmd": cmd, "reply": str(reply),
                             "data": has_data, "verdict": verdict})
        if answered:
            note = "Module answered with data — re-run ABS read to decode it."
        elif any("rejected" in a["verdict"] for a in attempts):
            note = (f"Module at {hdr} is ALIVE but rejects these services. It needs "
                    "its model-specific routine (often KWP2000-based on mid-2000s "
                    "cars) — check the service manual for your model/year.")
        else:
            note = (f"Header {hdr} is silent on this car (all NO DATA). The ABS ECU "
                    "needs a different header/PID for this model/year — check the "
                    "service manual or a model-specific forum, then use the raw box.")
        return {"header": hdr, "answered": answered, "attempts": attempts, "note": note}


def run_abs(client, args) -> int:
    """--abs-read / --abs-raw / --abs-probe / --abs-clear / --atf. Returns exit code."""
    import sys
    if args.abs_read:
        print("\nABS / chassis codes:")
        try:
            adtcs, ainfo = client.read_abs_dtcs()
            print(f"  ({ainfo.get('source')}) {ainfo.get('note')}")
            if not adtcs:
                print("  No ABS C-codes found via generic OBD.")
            else:
                for d in adtcs:
                    print(f"  {d.code}  {d.description}")
        except Exception as e:
            print(f"ABS READ FAILED: {e}", file=sys.stderr)
            return 1
    if args.abs_raw:
        print(f"\nRaw ABS query '{args.abs_raw}'"
              + (f" @ {args.tx_header}" if args.tx_header else "") + ":")
        try:
            print(client.query_abs_raw(args.abs_raw, tx_header=args.tx_header))
        except Exception as e:
            print(f"ABS RAW FAILED: {e}", file=sys.stderr)
            return 1
    if args.abs_probe:
        print("\nProbing ABS module (raw replies):")
        try:
            probe = client.probe_abs_module(header=args.tx_header)
            print(f"  header: {probe['header']}")
            for a in probe["attempts"]:
                print(f"  [{a.get('verdict', 'data' if a['data'] else 'no data')}] "
                      f"{a['cmd']} -> {a['reply']}")
            print(f"  {probe['note']}")
        except Exception as e:
            print(f"ABS PROBE FAILED: {e}", file=sys.stderr)
            return 1
    if args.abs_clear:
        print("\nABS clear uses Mode 04 (same as engine clear).")
        print("Ignition ON, engine OFF. Fix/note the cause first.")
        if not args.demo:
            ans = input("Type YES to confirm ABS clear: ").strip()
            if ans != "YES":
                print("Aborted.")
                return 0
        res = client.clear_abs()
        print("ABS clear sent." if res["ok"] else "ABS clear got no response.")
        print(res["warning"])
    if args.atf:
        print("\nTransmission/ATF temperature (manufacturer-specific raw PID):")
        try:
            t = client.read_atf_temp()
            print(f"  supported: {t.get('supported')}")
            if t.get("raw"):
                print(f"  raw: {t['raw']}")
            print(f"  {t.get('note')}")
        except Exception as e:
            print(f"ATF FAILED: {e}", file=sys.stderr)
            return 1
    return 0
