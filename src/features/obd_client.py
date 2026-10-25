"""Backward-compatible facade: everything now lives in feature modules.

obd_core     - connection, VIN/compatibility, engine DTCs, live data
im_readiness - I/M monitors
abs_module   - ABS / chassis codes + probing
tpms_module  - TPMS codes, pressures, sensor-ID registration
Used by main.py (dispatcher) and gui.py."""

from __future__ import annotations

from features.abs_module import (ABS_DTC_DESCRIPTIONS, ABS_PRESETS, ABSMixin)
from features.im_readiness import IMReadinessMixin
from features.obd_core import (COMMON_DTC_DESCRIPTIONS, DTC, OBDClientCore, decode_vin,
                               extract_vin_from_raw, list_serial_ports, to_float)
from features.tpms_module import (TPMS_DTC_DESCRIPTIONS, TPMS_PRESETS,
                                  TPMS_REGISTER_PRESETS, TPMSMixin, parse_tpms_id)
from features.vehicle_db import BRANDS, brand_info, protocol_hint


class OBDClient(IMReadinessMixin, ABSMixin, TPMSMixin, OBDClientCore):
    """Full reader: core + I/M + ABS + TPMS."""


__all__ = [
    "OBDClient", "OBDClientCore", "DTC", "list_serial_ports", "to_float",
    "decode_vin", "extract_vin_from_raw", "COMMON_DTC_DESCRIPTIONS",
    "IMReadinessMixin", "ABSMixin", "TPMSMixin",
    "ABS_DTC_DESCRIPTIONS", "ABS_PRESETS", "TPMS_DTC_DESCRIPTIONS",
    "TPMS_PRESETS", "TPMS_REGISTER_PRESETS", "parse_tpms_id",
    "BRANDS", "brand_info", "protocol_hint",
]
