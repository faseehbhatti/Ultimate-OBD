"""OBD core: connection, VIN/compatibility, engine DTCs, live data.
Executed from main.py via run_vin / run_engine / run_engine_clear /
run_live / run_monitor."""

from __future__ import annotations

import time
from dataclasses import dataclass

from features.vehicle_db import BRANDS, brand_info, protocol_hint


@dataclass
class DTC:
    code: str
    description: str

def to_float(v) -> float | None:
    """Best-effort numeric parse of a live PID value ('1234.5 rpm' -> 1234.5)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:  # pint Quantity
        return float(v.magnitude)
    except Exception:
        pass
    import re
    m = re.search(r"-?\d+(\.\d+)?", str(v))
    return float(m.group(0)) if m else None


# Small fallback descriptions for common codes (used in Demo mode / if lib lacks desc)
COMMON_DTC_DESCRIPTIONS = {
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0301": "Cylinder 1 Misfire Detected",
    "P0171": "System Too Lean (Bank 1)",
    "P0172": "System Too Rich (Bank 1)",
    "P0420": "Catalyst System Efficiency Below Threshold (Bank 1)",
    "P0442": "Evaporative Emission System Leak Detected (small leak)",
    "P0455": "Evaporative Emission System Leak Detected (large leak)",
    "P0401": "Exhaust Gas Recirculation Flow Insufficient Detected",
    "P0118": "Engine Coolant Temperature Circuit High Input",
    "P0128": "Coolant Thermostat (Coolant Temp Below Thermostat Regulating Temp)",
    "P0131": "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 1)",
    "P0141": "O2 Sensor Heater Circuit Malfunction (Bank 1, Sensor 2)",
    "P0404": "Exhaust Gas Recirculation Circuit Range/Performance",
    "P0500": "Vehicle Speed Sensor Malfunction",
    "P0562": "System Voltage Low",
    "P0700": "Transmission Control System Malfunction",
    "C0035": "Left Front Wheel Speed Sensor Circuit",
    "B0020": "Left Side Airbag Deployment Control",
    "U0100": "Lost Communication With ECM/PCM",
}

# ---------- VIN / compatibility ----------
# WMI (first 2-3 VIN chars) -> make. Built from vehicle_db (make list)
# plus common extras. Extend WMIs in vehicle_db.py, not here.

WMI_MAKES: dict[str, str] = {}
for _brand, _info in BRANDS.items():
    for _wmi in _info["wmi"]:
        WMI_MAKES[_wmi] = _brand
# Makes outside the top 10 (generic profile, still fully usable):
WMI_MAKES.update({
    "JF": "Subaru", "4S": "Subaru",
    "JM": "Mazda", "JL": "Mitsubishi",
    "1C": "Stellantis", "2C": "Stellantis", "3C": "Stellantis",
    "5YJ": "Tesla", "7SA": "Tesla", "YV1": "Volvo",
})

# VIN year code (char 10), standard 30-year cycle.
YEAR_CODES = {
    "A": (1980, 2010), "B": (1981, 2011), "C": (1982, 2012), "D": (1983, 2013),
    "E": (1984, 2014), "F": (1985, 2015), "G": (1986, 2016), "H": (1987, 2017),
    "J": (1988, 2018), "K": (1989, 2019), "L": (1990, 2020), "M": (1991, 2021),
    "N": (1992, 2022), "P": (1993, 2023), "R": (1994, 2024), "S": (1995, 2025),
    "T": (1996, 2026), "V": (1997, 2027), "W": (1998, 2028), "X": (1999, 2029),
    "Y": (2000, 2030), "1": (2001, 2031), "2": (2002, 2032), "3": (2003, 2033),
    "4": (2004, 2034), "5": (2005, 2035), "6": (2006, 2036), "7": (2007, 2037),
    "8": (2008, 2038), "9": (2009, 2039),
}


def vehicle_key(profile: dict) -> str:
    """'make-model-year' lookup key for per-vehicle presets (lowercase, blanks skipped)."""
    parts = [(profile.get("make") or "").lower(), (profile.get("model") or "").lower(),
             str(profile.get("year") or "")]
    return "-".join(x for x in parts if x)


def generic_profile(make: str, year: int | None, *, vds: str = "", wmi: str = "",
                    models: list[str] | None = None, model: str | None = None,
                    note: str = "") -> dict:
    """One profile shape for every car — no per-make special cases."""
    return {
        "make": make, "year": year, "vds": vds, "wmi": wmi,
        "models": list(models or []), "model": model,
        "mode": "generic",
        "abs": "generic",
        "abs_mode": "generic C-code scan (Modes 03/07/0A)",
        "protocol": protocol_hint(year),
        "note": note,
    }


def extract_vin_from_raw(raw: str) -> str | None:
    """
    Pull a 17-char VIN out of a raw multi-frame 0902 reply, e.g.
      '7EA 10 14 49 02 01 4A 54 4E / 7EA 21 42 ... / 7EA 22 ...'
    Strips ISO-TP frame headers (7EX + PCI) and the '49 02 count' prefix,
    then takes 17 VIN-charset bytes. Returns None if not found. Never raises.
    """
    import re
    try:
        payload: list[int] = []
        for line in str(raw).splitlines():
            # Drop a leading ECU address token like "7E8"/"7EA" if present
            # (packed '7EA1014...' or spaced '7EA 10 14 ...' alike)
            line = re.sub(r"^\s*7E[0-9A-Fa-f]", "", line)
            pairs = re.findall(r"[0-9A-Fa-f]{2}", line)
            bs = [int(b, 16) for b in pairs]
            if not bs:
                continue
            pci = bs[0]
            if (pci & 0xF0) == 0x10 and len(bs) >= 2:  # first frame: PCI is 2 bytes
                payload += bs[2:]
            elif (pci & 0xF0) in (0x20, 0x00) and len(bs) >= 1:  # consec./single: 1 byte
                payload += bs[1:]
            else:
                payload += bs
        # Payload should now start with 49 02 <count> <17 VIN bytes>
        for i in range(len(payload) - 19):
            if payload[i] == 0x49 and payload[i + 1] == 0x02:
                cand = bytes(payload[i + 3:i + 20]).decode("ascii", "ignore")
                if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", cand):
                    return cand
        return None
    except Exception:
        return None


def decode_vin(vin: str) -> dict:
    """Decode a 17-char VIN into {vin, make, year, vds, wmi}. Never raises."""
    import datetime
    import re
    vin = (vin or "").strip().upper()
    out = {"vin": vin, "make": "Unknown", "year": None, "vds": "", "wmi": ""}
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        out["note"] = "not a valid 17-char VIN"
        return out
    out["wmi"] = vin[:3]
    out["vds"] = vin[3:9]
    for ln in (3, 2):
        if vin[:ln] in WMI_MAKES:
            out["make"] = WMI_MAKES[vin[:ln]]
            break
    yc = vin[9]
    if yc in YEAR_CODES:
        now = datetime.date.today().year
        cands = sorted(YEAR_CODES[yc], reverse=True)
        out["year"] = next((c for c in cands if c <= now + 1), cands[-1])
    return out

def list_serial_ports() -> list[str]:
    """Return list of available COM ports e.g. ['COM3', 'COM4']."""
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []

class OBDClientCore:
    # Synthetic VIN used in Demo mode — structurally valid, assigned to no
    # real manufacturer. Demo mode shows a neutral sample vehicle.
    DEMO_VIN = "1DEM00000J0000000"


    def __init__(self, demo: bool = False):
        # Deferred imports: these live in feature modules to avoid cycles.
        from features.abs_module import ABS_DTC_DESCRIPTIONS
        from features.tpms_module import TPMS_DTC_DESCRIPTIONS
        self.demo = demo
        self.connection = None  # python-OBD connection
        self.port: str | None = None
        self.vin: str | None = None
        self.profile: dict = {"make": "Unknown", "mode": "generic", "note": "not detected yet"}
        self._demo_dtcs = [
            DTC("P0300", COMMON_DTC_DESCRIPTIONS["P0300"]),
            DTC("P0420", COMMON_DTC_DESCRIPTIONS["P0420"]),
        ]
        self._demo_abs_dtcs = [
            DTC("C0035", ABS_DTC_DESCRIPTIONS["C0035"]),
            DTC("C0110", ABS_DTC_DESCRIPTIONS["C0110"]),
        ]
        self._demo_tpms_dtcs = [
            DTC("C0750", TPMS_DTC_DESCRIPTIONS["C0750"]),
        ]
        self._demo_tpms_live = {
            "FL (psi)": 32.1, "FR (psi)": 31.8, "RL (psi)": 32.4, "RR (psi)": 32.0,
        }
        self._demo_tpms_ids: dict[str, str] | None = None

    # ---------- connect ----------
    def connect(self, port: str | None = None, baudrate: int | None = None,
                protocol: str | None = None, timeout: int = 30) -> str:
        """Connect to ELM327 adapter. Returns status string."""
        if self.demo:
            self.port = "DEMO"
            time.sleep(0.3)
            return "Connected (DEMO mode — no real car)"

        try:
            import obd
        except ImportError as e:
            raise RuntimeError(
                "python-OBD not installed. Run: pip install -r requirements.txt"
            ) from e

        # python-OBD: baudrate + protocol optional, fast=False is more reliable for BT
        kwargs: dict = {"fast": False, "timeout": timeout}
        if port:
            kwargs["portstr"] = port
        if baudrate:
            kwargs["baudrate"] = baudrate
        if protocol:
            kwargs["protocol"] = protocol  # e.g. "6" = ISO 15765-4 CAN 11/500

        self.connection = obd.OBD(**kwargs)
        self.port = port or str(self.connection.port_name())

        status = str(self.connection.status())
        if status in ("Not Connected", "ELM Error"):
            raise ConnectionError(
                f"Could not connect on {self.port} (status={status}). "
                "Check: 1) dongle paired in Windows Bluetooth, "
                "2) correct COM port, 3) car ignition ON, 4) try baud 38400 or 115200."
            )
        return f"Connected on {self.port} (status={status})"


    def is_connected(self) -> bool:
        if self.demo:
            return self.port == "DEMO"
        return self.connection is not None and self.connection.is_connected()


    def disconnect(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
        self.port = None

    # ---------- VIN + compatibility ----------
    def read_vin(self) -> str:
        """Read VIN via Mode 09 PID 02 (standard on all OBD-II cars)."""
        if self.demo:
            self.vin = self.DEMO_VIN
            return self.vin
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd
        r = self.connection.query(obd.commands.VIN)
        if r.is_null():
            # Fallback: forced raw 0902 (bypasses the support filter), parsed
            # as ISO-TP multi-frame — this is what some older ECUs require.
            raw = self.query_module("09 02")
            vin = extract_vin_from_raw(raw)
            if not vin:
                raise RuntimeError(f"ECU did not return a VIN (raw: {raw[:120]})")
            self.vin = vin
            return vin
        v = r.value
        if isinstance(v, bytes):
            v = v.decode("ascii", "ignore")
        vin = "".join(c for c in str(v).strip().upper() if c.isalnum())
        if len(vin) != 17:
            raise RuntimeError(f"ECU returned malformed VIN: {v!r}")
        self.vin = vin
        return vin


    def detect_compatibility(self, vin: str | None = None, model: str | None = None) -> dict:
        """
        Connect-page routine: decode VIN -> set self.profile so the rest of the
        app adapts to the car. Make+year come from the VIN (reliable); model is
        user-confirmed from the make's model list since VIN VDS blocks aren't
        standardised. Never raises: unknown cars fall back to the same generic
        profile every make uses. The synthetic demo VIN is used ONLY in demo
        mode — a real car with an unreadable VIN gets Unknown, never a fake identity.
        """
        vin = vin or self.vin
        if self.demo and (not vin or vin == self.DEMO_VIN):
            self.vin = self.DEMO_VIN
            self.profile = generic_profile(
                "Demo", 2018, wmi="1DE", models=[], model="Sample car",
                note="Demo mode — synthetic vehicle, no real car connected.")
            return self.profile
        if not vin:
            self.vin = None
            self.profile = generic_profile(
                "Unknown", None,
                note=("VIN unreadable on this car/adapter (Mode 09 PID 02 unsupported). "
                      "Set make/model/year manually below — nothing was auto-detected."))
            return self.profile
        d = decode_vin(vin)
        self.vin = d["vin"]
        info = brand_info(d["make"])
        models = list(info["models"]) if info is not None else []
        chosen = model if model in models else None
        note = (info["notes"] if info is not None else
                "Generic profile: engine codes + I/M + live data fully supported; "
                "ABS via generic C-code scan.")
        self.profile = generic_profile(d["make"], d["year"], vds=d["vds"],
                                       wmi=d["wmi"], models=models, model=chosen,
                                       note=note)
        return self.profile


    def set_model(self, model: str) -> dict:
        """Confirm the model from the make's model list. Ignores unknown names."""
        if model in self.profile.get("models", []):
            self.profile["model"] = model
        return self.profile


    def set_manual_vehicle(self, make: str, model: str | None = None,
                           year: int | None = None) -> dict:
        """
        Manually identify the car (used when the VIN is unreadable).
        make must be a brand in vehicle_db; model must be in its model list;
        year 1980-2039 or None. Raises ValueError on bad input. Keeps any
        already-read VIN for reference and marks the profile manual.
        """
        import datetime
        info = brand_info(make)
        if info is None:
            raise ValueError(f"Unknown make '{make}'. Choices: {', '.join(sorted(BRANDS))}")
        if model is not None and model not in info["models"]:
            raise ValueError(f"Unknown model '{model}' for {make}. "
                             f"Choices: {', '.join(info['models'])}")
        if year is not None and not (1980 <= int(year) <= datetime.date.today().year + 1):
            raise ValueError(f"Year '{year}' out of range 1980..{datetime.date.today().year + 1}")
        self.profile = generic_profile(
            make, int(year) if year is not None else None,
            vds=self.profile.get("vds", "") if self.profile.get("make") == make else "",
            wmi=self.profile.get("wmi", "") if self.profile.get("make") == make else "",
            models=list(info["models"]), model=model,
            note=info["notes"] + " (Vehicle set manually — VIN unreadable.)")
        return self.profile


    def profile_summary(self) -> str:
        p = self.profile
        model = p.get("model") or "(select model on the Connect page)"
        return (f"VIN: {self.vin or '-'}  |  Make: {p.get('make')}  |  "
                f"Year: {p.get('year') or '-'}  |  Model: {model}  |  Profile: {p.get('mode')}\n"
                f"Protocol: {p.get('protocol')}\n"
                f"ABS path: {p.get('abs_mode')}\n{p.get('note', '')}")

    # ---------- DTC read / clear ----------
    def read_dtcs(self) -> tuple[list[DTC], dict]:
        """
        Returns (stored_dtcs, info_dict).
        info_dict has keys: mil (bool), dtc_count (int), pending, permanent.
        """
        if self.demo:
            return list(self._demo_dtcs), {
                "mil": True, "dtc_count": len(self._demo_dtcs),
                "pending": [], "permanent": [],
                "note": "demo data",
            }

        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")

        import obd

        def _query(cmd):
            if cmd is None:
                return None
            try:
                # Skip commands the car flagged unsupported at connect —
                # querying them just logs noise and returns null.
                if not self.connection.supports(cmd):
                    return None
                r = self.connection.query(cmd)
            except Exception:
                return None
            if r.is_null():
                return None
            return r.value

        def _as_list(v) -> list:
            # GET_DTC/GET_CURRENT_DTC decode to a list; FREEZE_DTC (01 02)
            # decodes to a single (code, desc) tuple — normalize both.
            if not v:
                return []
            if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
                return [v]
            return list(v)

        stored = _as_list(_query(obd.commands.GET_DTC))
        pending = _as_list(_query(obd.commands.GET_CURRENT_DTC))  # Mode 07
        freeze = _as_list(_query(obd.commands.FREEZE_DTC))  # Mode 01 PID 02
        # Permanent DTCs (Mode 0A) — only in newer python-OBD versions
        permanent = _as_list(_query(getattr(obd.commands, "PERMANENT_DTC", None)))

        status = _query(obd.commands.STATUS)  # has MIL + dtc_count
        mil = bool(getattr(status, "MIL", False)) if status else False
        dtc_count = int(getattr(status, "DTC_count", len(stored))) if status else len(stored)

        def _to_dtc(t) -> DTC:
            code = t[0] if isinstance(t, tuple) else str(t)
            desc = t[1] if isinstance(t, tuple) and len(t) > 1 else ""
            if not desc:
                desc = COMMON_DTC_DESCRIPTIONS.get(code, "")
            return DTC(code, desc)

        return ([_to_dtc(t) for t in stored],
                {"mil": mil, "dtc_count": dtc_count,
                 "pending": [str(x[0] if isinstance(x, tuple) else x) for x in pending + freeze],
                 "permanent": [str(x[0] if isinstance(x, tuple) else x) for x in permanent]})


    def clear_dtcs(self) -> bool:
        """Send Mode 04 Clear DTCs. Returns True on success."""
        if self.demo:
            self._demo_dtcs = []
            return True
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd
        r = self.connection.query(obd.commands.CLEAR_DTC)
        # Null response means the ECU/adapter gave no answer.
        return not r.is_null()

    # ---------- raw module queries (any ECU header) ----------
    def query_abs_raw(self, cmd: str, tx_header: str | None = None) -> str:
        """
        ABS-named entry point for raw ECU queries, e.g.
          query_abs_raw("19 02 FF", tx_header="7E1")
        Delegates to query_module(); kept under this name because callers
        think in terms of the ABS module. Wrong headers just yield NO DATA,
        they don't harm the car.
        """
        if self.demo:
            return "(demo) 59 02 FF C0 35 00 ..."
        if not self.is_connected():
            raise ConnectionError("Not connected.")
        return self.query_module(cmd, tx_header=tx_header)

    def _raw_command(self, cmd: str, tx_header: str | None = None):
        """Build a raw-text OBDCommand for any mode/PID + header. Never sends."""
        import obd
        from obd.decoders import raw_string
        from obd.protocols import ECU
        compact = "".join(cmd.split()).upper()
        if not compact or any(c not in "0123456789ABCDEF" for c in compact):
            raise ValueError(f"'{cmd}' is not a hex OBD command (e.g. '03', '19 02 FF')")
        return obd.OBDCommand(
            f"RAW_{compact}", f"raw {compact}", compact.encode(), 0,
            raw_string, ecu=ECU.ALL, header=(tx_header or "7E0").encode())

    # Alias: query_module() also serves TPMS, SRS, ... — query_abs_raw()
    # above is the same call kept under its historical ABS name.
    def query_module(self, cmd: str, tx_header: str | None = None) -> str:
        """
        Send a raw command to any ECU header using the library's per-command
        header support (set/restored automatically per query), e.g.
          query_module("19 02 FF", tx_header="7E1")
        You need your make/model's documented header + command.
        """
        if self.demo:
            return "(demo) OK"
        if not self.is_connected():
            raise ConnectionError("Not connected.")
        r = self.connection.query(self._raw_command(cmd, tx_header), force=True)
        if r.is_null():
            return "(no data)"
        return str(r.value)


    LIVE_PIDS = [
        ("RPM (rpm)", "RPM"),
        ("Speed (km/h)", "SPEED"),
        ("Coolant (C)", "COOLANT_TEMP"),
        ("Intake air (C)", "INTAKE_TEMP"),
        ("Engine load (%)", "ENGINE_LOAD"),
        ("Throttle (%)", "THROTTLE_POS"),
        ("MAF (g/s)", "MAF"),
        ("Intake press (kPa)", "INTAKE_PRESSURE"),
        ("Timing adv (deg)", "TIMING_ADVANCE"),
        ("STFT B1 (%)", "SHORT_FUEL_TRIM_1"),
        ("LTFT B1 (%)", "LONG_FUEL_TRIM_1"),
        ("Fuel level (%)", "FUEL_LEVEL"),
        ("Voltage (V)", "CONTROL_MODULE_VOLTAGE"),
        ("Run time (s)", "RUN_TIME"),
        ("Dist since clear (km)", "DISTANCE_SINCE_DTC_CLEAR"),
    ]


    def live_data(self, pids: list[str] | None = None) -> dict:
        """Fetch live PIDs. pids = optional subset of labels from LIVE_PIDS. Missing PIDs skipped."""
        if self.demo:
            import math as _m
            import random
            import time as _t
            t = _t.time()
            # Simulated drive cycle: idle -> accelerate -> cruise -> decel (60s loop)
            # so the realtime dashboard visibly moves instead of sitting at 0 km/h.
            ph = (t % 60.0) / 60.0
            if ph < 0.15:  # idle
                speed = 0
                throttle = 13 + random.random() * 2
            elif ph < 0.45:  # accelerating to ~80 km/h
                k = (ph - 0.15) / 0.30
                speed = 80 * k + random.random() * 2
                throttle = 25 + 15 * _m.sin(k * _m.pi) + random.random() * 3
            elif ph < 0.75:  # cruise with small waves
                speed = 78 + 5 * _m.sin(t / 2.5) + random.random() * 2
                throttle = 22 + 3 * _m.sin(t / 3.0) + random.random() * 2
            else:  # decel back to idle
                k = (ph - 0.75) / 0.25
                speed = max(0, 80 * (1 - k) + random.random() * 2)
                throttle = 14 + random.random() * 3
            rpm = 750 + speed * 28 + 120 * abs(_m.sin(t / 3)) + random.random() * 40
            load = min(95, 17 + throttle * 1.6 + random.random() * 3)
            data = {
                "RPM (rpm)": round(rpm, 0),
                "Speed (km/h)": round(max(0, speed), 0),
                "Coolant (C)": 88 + round(3 * _m.sin(t / 30), 1),
                "Intake air (C)": 35,
                "Engine load (%)": round(load, 1),
                "Throttle (%)": round(throttle, 1),
                "MAF (g/s)": round(2.6 + load * 0.28 + random.random() * 0.4, 2),
                "Intake press (kPa)": int(30 + load * 0.5),
                "Timing adv (deg)": round(10 + random.random() * 6, 1),
                "STFT B1 (%)": round(random.uniform(-3, 3), 1),
                "LTFT B1 (%)": round(1.6 + _m.sin(t / 20), 1),
                "Fuel level (%)": 62.0,
                "Voltage (V)": round(13.8 + random.random() * 0.4, 1),
                "Run time (s)": int(t % 10000),
                "Dist since clear (km)": 145,
            }
            if pids:
                data = {k: v for k, v in data.items() if k in pids}
            return data
        if not self.is_connected():
            raise ConnectionError("Not connected.")
        import obd
        wanted = self.LIVE_PIDS
        if pids:
            wanted = [w for w in self.LIVE_PIDS if w[0] in pids]
        out: dict = {}
        for label, cmd_name in wanted:
            cmd = getattr(obd.commands, cmd_name, None)
            if cmd is None:
                continue
            try:
                resp = self.connection.query(cmd)
                if not resp.is_null():
                    v = resp.value
                    # Format pint quantities nicely, else str()
                    try:
                        out[label] = f"{v.magnitude:.1f}" if hasattr(v, "magnitude") else str(v)
                    except Exception:
                        out[label] = str(v)
            except Exception:
                continue
        # Fallback: ELM voltage (AT RV) often works when CONTROL_MODULE_VOLTAGE doesn't
        if "Voltage (V)" not in out:
            try:
                resp = self.connection.query(obd.commands.ELM_VOLTAGE)
                if not resp.is_null():
                    out["Voltage (V)"] = str(resp.value)
            except Exception:
                pass
        return out


    def stream_live(self, interval: float = 1.0, count: int = 0,
                    callback=None, logfile: str | None = None,
                    stop_event=None) -> str | None:
        """
        Poll live_data() + I/M every `interval` sec.
        count=0 means infinite until stop_event is set.
        callback(sample_dict) called each tick. Optionally append CSV to logfile.
        Returns logfile path (or None).
        """
        import csv
        import datetime
        writer = None
        fh = None
        fieldnames: list[str] | None = None
        if logfile:
            fh = open(logfile, "w", newline="", encoding="utf-8")
        try:
            n = 0
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                if count and n >= count:
                    break
                sample = self.live_data()
                sample["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
                # Attach I/M summary every 10th sample (cheap on bus)
                if n % 10 == 0:
                    try:
                        im = self.im_readiness()
                        sample["IM_ready"] = im["ready_str"]
                    except Exception:
                        pass
                if fh is not None:
                    if fieldnames is None:
                        fieldnames = list(sample.keys())
                        writer = csv.DictWriter(fh, fieldnames=fieldnames)
                        writer.writeheader()
                    # New keys appearing after the CSV header was written
                    # (e.g. IM_ready) -> extend gracefully
                    for k in sample:
                        if k not in fieldnames:
                            fieldnames.append(k)
                    writer.writerow({k: sample.get(k, "") for k in fieldnames})
                    fh.flush()
                if callback is not None:
                    callback(sample)
                n += 1
                if stop_event is not None:
                    if stop_event.wait(interval):
                        break
                else:
                    time.sleep(interval)
        finally:
            if fh is not None:
                fh.close()
        return logfile


    # ---------- Mode 06 / freeze frame / Mode 09 ----------
    # Curated MID list: the monitors that matter on almost every car.
    MODE06_MIDS = [
        ("Catalyst B1", "MONITOR_CATALYST_B1"),
        ("O2 sensor B1S1", "MONITOR_O2_B1S1"),
        ("O2 heater B1S1", "MONITOR_O2_HEATER_B1S1"),
        ("EGR B1", "MONITOR_EGR_B1"),
        ("EVAP 0.020in", "MONITOR_EVAP_020"),
        ("Fuel system B1", "MONITOR_FUEL_SYSTEM_B1"),
        ("Misfire (general)", "MONITOR_MISFIRE_GENERAL"),
        ("Secondary air 1", "MONITOR_SECONDARY_AIR_1"),
    ]

    FREEZE_PIDS = [
        ("RPM (rpm)", "DTC_RPM"),
        ("Speed (km/h)", "DTC_SPEED"),
        ("Coolant (C)", "DTC_COOLANT_TEMP"),
        ("Engine load (%)", "DTC_ENGINE_LOAD"),
        ("Intake air (C)", "DTC_INTAKE_TEMP"),
        ("MAF (g/s)", "DTC_MAF"),
        ("Throttle (%)", "DTC_THROTTLE_POS"),
        ("Timing adv (deg)", "DTC_TIMING_ADVANCE"),
        ("STFT B1 (%)", "DTC_SHORT_FUEL_TRIM_1"),
        ("LTFT B1 (%)", "DTC_LONG_FUEL_TRIM_1"),
        ("Fuel status", "DTC_FUEL_STATUS"),
        ("Intake press (kPa)", "DTC_INTAKE_PRESSURE"),
        ("Fuel pressure (kPa)", "DTC_FUEL_PRESSURE"),
        ("Voltage (V)", "DTC_CONTROL_MODULE_VOLTAGE"),
        ("Run time (s)", "DTC_RUN_TIME"),
    ]

    @staticmethod
    def _qty_str(q) -> str:
        """Format a pint quantity ('12.3 volt') or fall back to str()."""
        try:
            return f"{q.magnitude:.3g} {q.units}"
        except Exception:
            return str(q)

    def read_mode06(self) -> dict:
        """
        Mode 06 on-board monitor test results. Returns
        {mids: [{mid, tests: [{tid, name, value, limit_min, limit_max, passed}]}], checked}.
        Never raises on bus errors — unanswered MIDs are simply skipped.
        """
        if self.demo:
            return {"checked": 3, "mids": [
                {"mid": "Catalyst B1", "tests": [
                    {"tid": 1, "name": "Catalyst monitor bank 1",
                     "value": "0.42 ratio", "limit_min": "0 ratio",
                     "limit_max": "0.75 ratio", "passed": True}]},
                {"mid": "Misfire (general)", "tests": [
                    {"tid": 12, "name": "Misfire counts",
                     "value": "3 count", "limit_min": "0 count",
                     "limit_max": "50 count", "passed": True}]},
                {"mid": "EVAP 0.020in", "tests": [
                    {"tid": 58, "name": "Small leak test",
                     "value": "0.9 pascal", "limit_min": "0 pascal",
                     "limit_max": "0.5 pascal", "passed": False}]},
            ]}
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd
        mids = []
        for label, cmd_name in self.MODE06_MIDS:
            cmd = getattr(obd.commands, cmd_name, None)
            if cmd is None:
                continue
            try:
                if not self.connection.supports(cmd):
                    continue
                r = self.connection.query(cmd)
            except Exception:
                continue
            if r.is_null():
                continue
            tests = []
            for t in (getattr(r.value, "tests", None) or []):
                try:
                    passed = bool(t.passed)
                except Exception:
                    passed = False
                tests.append({"tid": getattr(t, "tid", None),
                              "name": str(getattr(t, "name", "") or getattr(t, "desc", "")),
                              "value": self._qty_str(getattr(t, "value", None)),
                              "limit_min": self._qty_str(getattr(t, "min", None)),
                              "limit_max": self._qty_str(getattr(t, "max", None)),
                              "passed": passed})
            if tests:
                mids.append({"mid": label, "tests": tests})
        return {"checked": len(mids), "mids": mids}

    def format_mode06(self, m: dict) -> str:
        """Pretty multi-line string for CLI/GUI log."""
        if not m["mids"]:
            return ("Mode 06: no monitor data returned (ECU may not support it, "
                    "or the adapter blocked the query).")
        n_fail = sum(1 for mid in m["mids"] for t in mid["tests"] if not t["passed"])
        lines = [f"Mode 06 monitor tests ({m['checked']} MIDs, {n_fail} failing):"]
        for mid in m["mids"]:
            for t in mid["tests"]:
                flag = "PASS" if t["passed"] else "FAIL <<"
                lines.append(f"  [{flag}] {mid['mid']} / {t['name']}: "
                             f"{t['value']}  (limits {t['limit_min']}..{t['limit_max']})")
        if n_fail:
            lines.append("Failing tests point at developing faults — often before any DTC sets.")
        return "\n".join(lines)

    def read_freeze_frame(self) -> dict:
        """
        Mode 02 freeze-frame snapshot + the DTC that triggered it.
        Returns {trigger, pids, note}. Never raises on bus errors.
        """
        if self.demo:
            return {"trigger": "P0300",
                    "pids": {"RPM (rpm)": "3120", "Speed (km/h)": "68",
                             "Coolant (C)": "91", "Engine load (%)": "72.5",
                             "STFT B1 (%)": "8.6", "LTFT B1 (%)": "6.2",
                             "Fuel status": "Closed loop"},
                    "note": "demo snapshot"}
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd

        def _one(cmd):
            try:
                if not self.connection.supports(cmd):
                    return None
                r = self.connection.query(cmd)
            except Exception:
                return None
            return None if r.is_null() else r.value

        trig = _one(obd.commands.FREEZE_DTC)
        trigger = trig[0] if isinstance(trig, tuple) else (str(trig) if trig else None)
        pids: dict = {}
        for label, cmd_name in self.FREEZE_PIDS:
            cmd = getattr(obd.commands, cmd_name, None)
            if cmd is None:
                continue
            v = _one(cmd)
            if v is None:
                continue
            try:
                pids[label] = f"{v.magnitude:.3g}" if hasattr(v, "magnitude") else str(v)
            except Exception:
                pids[label] = str(v)
        note = ("No freeze data stored (no DTC has triggered a snapshot)."
                if not trigger and not pids else
                "Snapshot of engine conditions when the DTC set.")
        return {"trigger": trigger, "pids": pids, "note": note}

    def format_freeze(self, f: dict) -> str:
        """Pretty multi-line string for CLI/GUI log."""
        lines = [f"Freeze frame (trigger: {f.get('trigger') or 'none stored'})"]
        if not f["pids"]:
            lines.append("  " + f.get("note", ""))
        else:
            for k, v in f["pids"].items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def read_ecu_info(self) -> dict:
        """
        Full Mode 09: VIN + calibration IDs + CVNs. Returns
        {vin, cal_ids, cvns, note}. Never raises on bus errors.
        """
        if self.demo:
            return {"vin": self.DEMO_VIN, "cal_ids": ["DEMO-CALID-1", "DEMO-CALID-2"],
                    "cvns": ["DEMO-CVN-1"],
                    "note": "demo values — compare CVN against stock to spot a tune"}
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd

        def _one(cmd):
            try:
                if not self.connection.supports(cmd):
                    return None
                r = self.connection.query(cmd)
            except Exception:
                return None
            return None if r.is_null() else r.value

        def _strs(v) -> list[str]:
            if v is None:
                return []
            items = list(v) if isinstance(v, (list, tuple)) else [v]
            out = []
            for it in items:
                if isinstance(it, bytes):
                    it = it.decode("ascii", "ignore")
                s = str(it).strip().strip("\x00")
                if s:
                    out.append(s)
            return out

        try:
            vin = self.read_vin()
        except Exception:
            vin = self.vin
        return {"vin": vin,
                "cal_ids": _strs(_one(obd.commands.CALIBRATION_ID)),
                "cvns": _strs(_one(obd.commands.CVN)),
                "note": ("Compare CALID/CVN against stock values for your model — "
                         "a mismatch means the ECU has been remapped.")}

    def format_ecu_info(self, e: dict) -> str:
        """Pretty multi-line string for CLI/GUI log."""
        lines = [f"ECU info (Mode 09):  VIN {e.get('vin') or '-'}"]
        lines.append("  Calibration IDs: " + (", ".join(e["cal_ids"]) if e["cal_ids"] else "(unanswered)"))
        lines.append("  CVNs: " + (", ".join(e["cvns"]) if e["cvns"] else "(unanswered)"))
        lines.append("  " + e.get("note", ""))
        return "\n".join(lines)

    def raw(self, cmd_str: str) -> str:
        """Send a raw AT/OBD command, e.g. 'AT RV', '03', '010C'. For debugging."""
        if self.demo:
            return "(demo) OK"
        if not self.is_connected():
            raise ConnectionError("Not connected.")
        if cmd_str.strip().upper().startswith("AT"):
            elm = getattr(self.connection, "interface", None)
            if elm is None:
                raise RuntimeError("This python-OBD version exposes no ELM interface")
            return str(elm.send_and_parse(cmd_str))
        return self.query_module(cmd_str)


def run_vin(client, args) -> int:
    """--vin / --model / --make / --year. Returns process exit code."""
    import sys
    try:
        print(f"\nVIN: {client.read_vin()}")
    except Exception as e:
        print(f"\nVIN unreadable: {e}")
    if args.make is not None:
        try:
            client.set_manual_vehicle(args.make, model=args.model, year=args.year)
        except ValueError as e:
            print(f"Invalid manual vehicle: {e}", file=sys.stderr)
            return 2
    else:
        client.detect_compatibility(model=args.model)
    if args.model and not client.profile.get("model"):
        print(f"(model '{args.model}' not in the model list for "
              f"{client.profile.get('make')}; use one of: "
              f"{', '.join(client.profile.get('models', []))})")
    print(client.profile_summary())
    return 0


def run_engine(client, args) -> int:
    """--read. Returns process exit code."""
    dtcs, info = client.read_dtcs()
    print(f"\nMIL on: {info.get('mil')}   DTC count (ECU): {info.get('dtc_count')}")
    if info.get("pending"):
        print(f"Pending: {', '.join(info['pending'])}")
    if info.get("permanent"):
        print(f"Permanent: {', '.join(info['permanent'])}")
    if not dtcs:
        print("No stored fault codes.")
    else:
        print(f"\nStored codes ({len(dtcs)}):")
        for d in dtcs:
            print(f"  {d.code}  {d.description}")
    return 0


def run_engine_clear(client, args) -> int:
    """--clear. Returns process exit code."""
    dtcs, _ = client.read_dtcs()
    print(f"\n{len(dtcs)} stored code(s) will be erased (Mode 04).")
    print("Only do this AFTER fixing / noting the cause. Ignition must be ON, engine OFF is safest.")
    if not args.demo:
        ans = input("Type YES to confirm clear: ").strip()
        if ans != "YES":
            print("Aborted.")
            return 0
    ok = client.clear_dtcs()
    print("Clear command sent." if ok else "Clear may have failed (no response).")
    dtcs2, _ = client.read_dtcs()
    print(f"Codes now: {len(dtcs2)}")
    return 0


def run_live(client, args) -> int:
    """--live. Returns process exit code."""
    print("\nLive data:")
    for k, v in client.live_data().items():
        print(f"  {k}: {v}")
    return 0


def run_monitor(client, args) -> int:
    """--monitor. Returns process exit code."""
    print(f"\nMonitoring every {args.interval}s"
          + (f" ({args.count} samples)" if args.count else " (Ctrl+C to stop)")
          + (f" -> logging {args.log}" if args.log else ""))
    print("timestamp | RPM | Speed | Coolant | Load | STFT B1 | LTFT B1 | V")
    try:
        def _show(s):
            print(f"{s.get('timestamp')} | {s.get('RPM (rpm)')} | "
                  f"{s.get('Speed (km/h)')} | {s.get('Coolant (C)')} | "
                  f"{s.get('Engine load (%)')} | {s.get('STFT B1 (%)')} | "
                  f"{s.get('LTFT B1 (%)')} | {s.get('Voltage (V)')}"
                  + (f" | {s.get('IM_ready')}" if s.get("IM_ready") else ""))
        client.stream_live(interval=args.interval, count=args.count,
                           callback=_show, logfile=args.log)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def run_mode06(client, args) -> int:
    """--mode06. Returns process exit code."""
    import sys
    print()
    try:
        print(client.format_mode06(client.read_mode06()))
    except Exception as e:
        print(f"MODE 06 FAILED: {e}", file=sys.stderr)
        return 1
    return 0


def run_freeze(client, args) -> int:
    """--freeze. Returns process exit code."""
    import sys
    print()
    try:
        print(client.format_freeze(client.read_freeze_frame()))
    except Exception as e:
        print(f"FREEZE FAILED: {e}", file=sys.stderr)
        return 1
    return 0


def run_ecuinfo(client, args) -> int:
    """--ecu-info. Returns process exit code."""
    import sys
    print()
    try:
        print(client.format_ecu_info(client.read_ecu_info()))
    except Exception as e:
        print(f"ECU INFO FAILED: {e}", file=sys.stderr)
        return 1
    return 0
