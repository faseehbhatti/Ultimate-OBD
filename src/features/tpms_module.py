"""TPMS faults, live pressures, sensor-ID registration. Executed from main.py via run_tpms."""

from __future__ import annotations

from features.obd_core import DTC, vehicle_key

# TPMS fault codes readable via generic Modes 03/07/0A on many cars.
# Corners/sensor numbers vary by make — descriptions stay generic on purpose.
# Only well-established codes are listed; live pressures are make-specific
# (see TPMS_PRESETS + read_tpms_live()).
TPMS_DTC_DESCRIPTIONS = {
    "C0750": "Tire pressure sensor fault, front axle (corner varies by make)",
    "C0755": "Tire pressure sensor fault (corner varies by make)",
    "C0760": "Tire pressure sensor fault, rear axle (corner varies by make)",
    "C0765": "Tire pressure sensor fault (corner varies by make)",
    "C0775": "Tire pressure monitoring system fault",
    "C2111": "TPMS transmitter ID not received (make-specific definition — check your service manual)",
    "C2112": "TPMS transmitter ID not received (make-specific definition — check your service manual)",
    "C2113": "TPMS transmitter ID not received (make-specific definition — check your service manual)",
    "C2114": "TPMS transmitter ID not received (make-specific definition — check your service manual)",
    "C2115": "TPMS transmitter ID not received (make-specific definition — check your service manual)",
    "B2872": "Tire pressure sensor fault (body code — definition varies by make)",
}
TPMS_CODES = frozenset(TPMS_DTC_DESCRIPTIONS)

# TPMS sensor-ID registration routines, keyed "make-model-year" (lowercase).
# EMPTY ON PURPOSE: writing IDs uses undocumented per-model routines, and a
# wrong routine can leave the TPMS ECU needing dealer recovery. Only add an
# entry you have verified from a service manual or a captured brand-tool
# session for that exact model/year. Documented shape:
# TPMS_REGISTER_PRESETS = {
#   "example-make-example-model-2020": {
#     "tx_header": "7E1",
#     "session": "10 03",          # enter extended diagnostic session
#     "write_tpl": "...",          # command template, {FL} {FR} {RL} {RR} = sensor IDs
#     "write_expect": "6E",        # expected positive-response prefix (spaces ignored, uppercase)
#     "verify_tpl": "...",         # optional read-back command template (or None)
#     "restore": "10 01",          # back to default session
#     "source": "service manual, section ...",
#   },
# }
TPMS_REGISTER_PRESETS: dict[str, dict] = {}


def parse_tpms_id(raw: str) -> str:
    """
    Validate/normalize one TPMS transmitter ID.
    Some makes use 7 hex digits (e.g. '1A2B3C4'), others use 8.
    Returns uppercase ID without spaces. Raises ValueError naming the problem.
    """
    s = (raw or "").strip().upper().replace(" ", "").replace("-", "")
    if s.startswith("0X"):
        s = s[2:]
    if len(s) not in (7, 8) or any(c not in "0123456789ABCDEF" for c in s):
        raise ValueError(f"'{raw}' is not a valid sensor ID (need 7 or 8 hex digits)")
    return s


# Live tire pressures have NO standard OBD-II PID — every make uses its own
# Mode 22 / UDS address. Shape for future verified entries (do NOT guess):
# TPMS_PRESETS = {"example-make-example-model-2020": {"tx_header": "7E1", "pid": "XXXX",
#                 "decoder": "...", "source": "service manual / verified"}}
TPMS_PRESETS: dict[str, dict] = {}


class TPMSMixin:
    # ---------- TPMS ----------
    # Honest scope: TPMS *fault codes* are readable via generic Modes 03/07/0A
    # on many cars (C075x/C076x/C077x, C211x, B2872). Live per-corner pressures
    # have NO standard OBD-II PID — each make uses its own Mode 22 / UDS
    # address (see TPMS_PRESETS). Sensor registration / relearn always needs
    # brand tooling or the car's own relearn procedure (owner's manual).
    def _preset_key(self) -> str:
        """'make-model-year' lookup key for TPMS presets (lowercase, skips blanks)."""
        return vehicle_key(self.profile)

    def read_tpms_dtcs(self) -> tuple[list[DTC], dict]:
        """Scan generic Modes 03/07/0A and keep known TPMS fault codes."""
        if self.demo:
            return list(self._demo_tpms_dtcs), {
                "source": "demo", "scanned": ["03", "07", "0A"],
                "note": "demo TPMS data",
            }
        if not self.is_connected():
            raise ConnectionError("Not connected. Call connect() first.")
        import obd
        seen: dict[str, DTC] = {}
        sources: list[str] = []

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
                if code not in TPMS_CODES:
                    continue
                desc = t[1] if isinstance(t, tuple) and len(t) > 1 else ""
                seen.setdefault(code, DTC(code, desc or TPMS_DTC_DESCRIPTIONS[code]))

        _collect(obd.commands.GET_DTC, "03-confirmed")
        _collect(obd.commands.GET_CURRENT_DTC, "07-pending")
        _collect(obd.commands.FREEZE_DTC, "01-02-freeze")
        _collect(getattr(obd.commands, "PERMANENT_DTC", None), "0A-permanent")
        if not seen and not sources:
            note = "ECU did not answer any generic mode — check ignition ON and retry."
        elif not seen:
            note = ("No TPMS codes in generic response — sensors may simply be healthy, "
                    "or your make hides TPMS behind a proprietary module.")
        else:
            note = f"{len(seen)} TPMS code(s) via generic OBD."
        info = {"source": "generic Modes " + ("/".join(sources) if sources else "no response"),
                "scanned": sources, "note": note}
        return list(seen.values()), info


    def read_tpms_live(self) -> dict:
        """
        Per-corner live pressures. Only real readings from a verified preset
        are returned; otherwise {supported: False} with guidance. Pressures
        themselves are always on the door-jamb sticker / owner's manual.
        """
        if self.demo:
            import random
            out = {k: round(v + random.uniform(-0.3, 0.3), 1)
                   for k, v in self._demo_tpms_live.items()}
            return {"supported": True, "source": "demo", "psi": out,
                    "note": "demo pressures"}
        if not self.is_connected():
            raise ConnectionError("Not connected.")
        key = self._preset_key()
        preset = TPMS_PRESETS.get(key)
        if not preset:
            return {"supported": False,
                    "note": ("Live TPMS pressures need your exact model's Mode 22 / UDS "
                             f"address (no entry for '{key}'). Use the raw query box with "
                             "your make's documented PID, or a brand tool. Target pressures "
                             "are on the door-jamb sticker.")}
        try:
            raw = self.query_module(preset["pid"], tx_header=preset.get("tx_header"))
            return {"supported": True, "source": key, "raw": raw,
                    "note": f"Raw response ({preset.get('source', 'preset')}); "
                            "decode per your model's documented layout."}
        except Exception as e:
            return {"supported": False, "note": f"Preset query failed: {e}"}


    def register_tpms_ids(self, ids: dict[str, str]) -> dict:
        """
        Manually set the 4 TPMS transmitter IDs in the car.

        ids: {"FL": "1A2B3C4", "FR": "...", "RL": "...", "RR": "..."}
             (7 or 8 hex digits each, from the sensor body / scan-tool printout)

        Safety design:
        - IDs are strictly validated before anything touches the car.
        - Demo mode simulates the write (clearly labeled).
        - On a real car the write runs ONLY from a verified entry in
          TPMS_REGISTER_PRESETS for the profiled make/model/year. Without one
          the function REFUSES and explains what is needed — it never sends
          guessed bytes to an ECU.
        - Ignition ON, engine OFF. Wrong IDs = TPMS fault light; re-check with
          read_tpms_dtcs() afterwards.

        Returns {"ok", "ids", "steps" | "error"}.
        """
        corners = ("FL", "FR", "RL", "RR")
        norm: dict[str, str] = {}
        problems: list[str] = []
        for c in corners:
            try:
                norm[c] = parse_tpms_id(ids.get(c, ""))
            except ValueError as e:
                problems.append(f"{c}: {e}")
        if problems:
            return {"ok": False, "ids": None,
                    "error": "Invalid sensor ID(s): " + "; ".join(problems)}
        if len(set(norm.values())) != 4:
            return {"ok": False, "ids": None,
                    "error": "IDs must be unique per corner (duplicates found). "
                             "Copy each ID exactly from its sensor."}

        if self.demo:
            self._demo_tpms_ids = dict(norm)
            return {"ok": True, "ids": norm,
                    "steps": ["demo: validated 4 unique IDs",
                              "demo: simulated write to TPMS ECU",
                              "demo: simulated read-back OK"],
                    "note": "demo only — nothing was written to a car"}

        if not self.is_connected():
            return {"ok": False, "ids": None, "error": "Not connected."}
        key = self._preset_key()
        preset = TPMS_REGISTER_PRESETS.get(key)
        if not preset:
            return {"ok": False, "ids": norm,
                    "error": ("No verified ID-registration routine for "
                              f"'{key or 'unknown car'}'. To add one I need your exact "
                              "make/model/year plus the documented routine (service manual "
                              "or a captured brand-tool session: header, session, write "
                              "command, expected reply). See TPMS_REGISTER_PRESETS.")}
        log: list[str] = []
        try:
            hdr = preset.get("tx_header")
            sess = preset.get("session")
            if sess:
                log.append(self._reg_step(sess, preset.get("session_expect"), hdr, "session"))
            write_cmd = preset["write_tpl"].format(**norm)
            log.append(self._reg_step(write_cmd, preset.get("write_expect"), hdr, "write"))
            if preset.get("verify_tpl"):
                verify_cmd = preset["verify_tpl"].format(**norm)
                log.append(self._reg_step(verify_cmd, preset.get("verify_expect"), hdr, "verify"))
            return {"ok": True, "ids": norm, "steps": log,
                    "note": "IDs written. Drive above ~40 km/h for 10+ min so the ECU "
                            "learns the sensors, then re-check with TPMS read."}
        except Exception as e:
            return {"ok": False, "ids": norm,
                    "error": f"Registration failed partway ({e}). Steps so far: {log}. "
                             "IDs may be partially written — do NOT drive on unchecked "
                             "pressures; retry or use brand tooling."}
        finally:
            try:
                if preset.get("restore"):
                    self.query_module(preset["restore"], tx_header=hdr)
            except Exception:
                pass


    def _reg_step(self, cmd: str, expect_prefix: str | None, hdr: str | None,
                  label: str) -> str:
        """Send one registration step; raise on unexpected reply."""
        resp = self.query_module(cmd, tx_header=hdr)
        flat = "".join(str(resp).split()).upper()
        if expect_prefix:
            want = "".join(expect_prefix.split()).upper()
            if not flat.startswith(want):
                raise RuntimeError(f"{label}: unexpected reply '{resp}' (wanted '{expect_prefix}')")
        return f"{label}: '{cmd}' -> '{resp}'"


def run_tpms(client, args) -> int:
    """--tpms-read / --tpms-live / --tpms-raw / --tpms-register. Returns exit code."""
    import sys
    if args.tpms_read:
        print("\nTPMS fault codes:")
        try:
            tdtcs, tinfo = client.read_tpms_dtcs()
            print(f"  ({tinfo.get('source')}) {tinfo.get('note')}")
            if not tdtcs:
                print("  No TPMS codes found via generic OBD.")
            else:
                for d in tdtcs:
                    print(f"  {d.code}  {d.description}")
        except Exception as e:
            print(f"TPMS READ FAILED: {e}", file=sys.stderr)
            return 1
    if args.tpms_live:
        print("\nLive tire pressures:")
        try:
            t = client.read_tpms_live()
            if t.get("supported") and t.get("psi"):
                for k, v in t["psi"].items():
                    print(f"  {k}: {v}")
            else:
                print(f"  {t.get('note')}")
                if t.get("raw"):
                    print(f"  raw: {t['raw']}")
        except Exception as e:
            print(f"TPMS LIVE FAILED: {e}", file=sys.stderr)
            return 1
    if args.tpms_raw:
        print(f"\nRaw TPMS query '{args.tpms_raw}'"
              + (f" @ {args.tx_header}" if args.tx_header else "") + ":")
        try:
            print(client.query_module(args.tpms_raw, tx_header=args.tx_header))
        except Exception as e:
            print(f"TPMS RAW FAILED: {e}", file=sys.stderr)
            return 1
    if args.tpms_register:
        fl, fr, rl, rr = args.tpms_register
        print(f"\nRegistering TPMS IDs: FL={fl} FR={fr} RL={rl} RR={rr}")
        print("Ignition ON, engine OFF. IDs must come from the sensor bodies / scan printout.")
        if not args.demo:
            ans = input("Type YES to write IDs to the TPMS ECU: ").strip()
            if ans != "YES":
                print("Aborted.")
                return 0
        res = client.register_tpms_ids({"FL": fl, "FR": fr, "RL": rl, "RR": rr})
        if res["ok"]:
            print("Registration accepted.")
            for s in res.get("steps", []):
                print(f"  {s}")
            print(res.get("note", ""))
        else:
            print(f"FAILED: {res['error']}", file=sys.stderr)
            return 1
    return 0
