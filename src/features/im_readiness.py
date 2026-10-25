"""I/M readiness (Mode 01 PID 01). Executed from main.py via run_im."""

from __future__ import annotations

# I/M readiness monitor names (Mode 01 PID 01), per SAE J1979
BASE_MONITORS = [
    "MISFIRE_MONITORING",
    "FUEL_SYSTEM_MONITORING",
    "COMPONENT_MONITORING",
]
SPARK_MONITORS = [
    "CATALYST_MONITORING",
    "HEATED_CATALYST_MONITORING",
    "EVAPORATIVE_SYSTEM_MONITORING",
    "SECONDARY_AIR_SYSTEM_MONITORING",
    "OXYGEN_SENSOR_MONITORING",
    "OXYGEN_SENSOR_HEATER_MONITORING",
    "EGR_VVT_SYSTEM_MONITORING",
]
COMPRESSION_MONITORS = [
    "NMHC_CATALYST_MONITORING",
    "NOX_SCR_AFTERTREATMENT_MONITORING",
    "BOOST_PRESSURE_MONITORING",
    "EXHAUST_GAS_SENSOR_MONITORING",
    "PM_FILTER_MONITORING",
    "EGR_VVT_SYSTEM_MONITORING",
]

# Pretty labels for the GUI/CLI
MONITOR_LABELS = {
    "MISFIRE_MONITORING": "Misfire",
    "FUEL_SYSTEM_MONITORING": "Fuel System",
    "COMPONENT_MONITORING": "Components",
    "CATALYST_MONITORING": "Catalyst",
    "HEATED_CATALYST_MONITORING": "Heated Catalyst",
    "EVAPORATIVE_SYSTEM_MONITORING": "Evaporative System",
    "SECONDARY_AIR_SYSTEM_MONITORING": "Secondary Air",
    "OXYGEN_SENSOR_MONITORING": "O2 Sensor",
    "OXYGEN_SENSOR_HEATER_MONITORING": "O2 Heater",
    "EGR_VVT_SYSTEM_MONITORING": "EGR / VVT",
    "NMHC_CATALYST_MONITORING": "NMHC Catalyst",
    "NOX_SCR_AFTERTREATMENT_MONITORING": "NOx / SCR",
    "BOOST_PRESSURE_MONITORING": "Boost Pressure",
    "EXHAUST_GAS_SENSOR_MONITORING": "Exhaust Gas Sensor",
    "PM_FILTER_MONITORING": "PM Filter",
}


def _pretty_monitor(name: str) -> str:
    return MONITOR_LABELS.get(name, name.replace("_", " ").title())

class IMReadinessMixin:
    # ---------- I/M readiness (Mode 01 PID 01) ----------
    def im_readiness(self) -> dict:
        """
        Returns dict:
          { mil, dtc_count, ignition_type, monitors: [{name,label,available,complete}],
            incomplete, unsupported, ready (bool), ready_str }
        ready = all available monitors complete.
        """
        if self.demo:
            mons = []
            # Realistic demo: 1 incomplete (EVAP), 2 unsupported
            for n in BASE_MONITORS + SPARK_MONITORS:
                if n in ("HEATED_CATALYST_MONITORING", "SECONDARY_AIR_SYSTEM_MONITORING"):
                    mons.append({"name": n, "label": _pretty_monitor(n),
                                 "available": False, "complete": False})
                elif n == "EVAPORATIVE_SYSTEM_MONITORING":
                    mons.append({"name": n, "label": _pretty_monitor(n),
                                 "available": True, "complete": False})
                else:
                    mons.append({"name": n, "label": _pretty_monitor(n),
                                 "available": True, "complete": True})
            incomplete = [m["label"] for m in mons if m["available"] and not m["complete"]]
            return {"mil": True, "dtc_count": len(self._demo_dtcs),
                    "ignition_type": "spark", "monitors": mons,
                    "incomplete": incomplete,
                    "unsupported": [m["label"] for m in mons if not m["available"]],
                    "ready": len(incomplete) == 0,
                    "ready_str": "READY" if not incomplete else f"NOT READY ({len(incomplete)} incomplete)"}

        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd
        r = self.connection.query(obd.commands.STATUS)
        if r.is_null():
            raise RuntimeError("ECU did not respond to I/M readiness (01 01).")
        s = r.value  # Status object with MIL, DTC_count, ignition_type, <MONITOR> attrs
        ignition = str(getattr(s, "ignition_type", "unknown"))
        names = list(BASE_MONITORS)
        names += COMPRESSION_MONITORS if ignition == "compression" else SPARK_MONITORS
        mons = []
        for n in names:
            t = getattr(s, n, None)
            avail = bool(getattr(t, "available", False))
            comp = bool(getattr(t, "complete", False))
            # Unavailable monitors count as N/A, not incomplete
            mons.append({"name": n, "label": _pretty_monitor(n),
                         "available": avail, "complete": comp if avail else False})
        incomplete = [m["label"] for m in mons if m["available"] and not m["complete"]]
        return {"mil": bool(getattr(s, "MIL", False)),
                "dtc_count": int(getattr(s, "DTC_count", 0)),
                "ignition_type": ignition, "monitors": mons,
                "incomplete": incomplete,
                "unsupported": [m["label"] for m in mons if not m["available"]],
                "ready": len(incomplete) == 0,
                "ready_str": "READY" if not incomplete else f"NOT READY ({len(incomplete)} incomplete)"}


    def format_im(self, im: dict) -> str:
        """Pretty multi-line string for CLI/GUI log."""
        lines = [f"I/M Readiness: {im['ready_str']}  (ignition: {im.get('ignition_type')}, "
                 f"MIL: {im.get('mil')}, DTCs: {im.get('dtc_count')})"]
        for m in im["monitors"]:
            if not m["available"]:
                st = "N/A (unsupported)"
            else:
                st = "Complete [OK]" if m["complete"] else "INCOMPLETE [ ]"
            lines.append(f"  {m['label']:<22} {st}")
        if im.get("incomplete"):
            lines.append("Drive cycle needed for: " + ", ".join(im["incomplete"]))
            lines.append("Note: clearing codes resets I/M to NOT READY until drive cycle completes.")
        return "\n".join(lines)


def run_im(client, args) -> int:
    """--im. Returns process exit code."""
    import sys
    print()
    try:
        print(client.format_im(client.im_readiness()))
    except Exception as e:
        print(f"I/M FAILED: {e}", file=sys.stderr)
        return 1
    return 0
