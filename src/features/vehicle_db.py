"""Compatibility database: popular makes, their common models, support notes.

Honest design notes (read before extending):
- WMI prefixes below are standard ISO assignments and reliably identify MAKE.
- MODEL cannot be reliably decoded from the VIN's VDS block without huge
  per-make tables, so the app detects make+year from the VIN and asks the
  user to confirm the model from the list. Never guess the model.
- ABS module headers/PIDs are make- and often model/year-specific. Only
  verified entries in ABS_PRESETS (abs_module.py) are attempted automatically;
  everything else uses the generic C-code scan. Do NOT add a preset unless
  you have a documented source for it.

Every make is treated the same way: the make/year come from the VIN, the
model is user-confirmed, and the generic OBD-II path works on any car.
"""

BRANDS: dict[str, dict] = {
    "Toyota": {
        "wmi": ["JT", "4T", "5T", "2T", "SB1", "MR0"],
        "models": ["Corolla", "RAV4", "Camry", "Tacoma", "Highlander", "Hilux",
                   "Land Cruiser", "Prius", "Yaris Cross", "Tundra"],
        "notes": "Full engine/I-M/live support. ABS via generic C-code scan; module-specific access needs brand tooling.",
    },
    "Volkswagen": {
        "wmi": ["WVW", "3VW", "1VW", "9BW"],
        "models": ["Golf", "Passat", "Polo", "Tiguan", "Jetta", "T-Roc",
                   "Atlas", "ID.4", "up!", "Touran"],
        "notes": "Full engine/I-M/live support. ABS module usually needs VAG tooling (e.g. VCDS); generic C-code scan included.",
    },
    "Ford": {
        "wmi": ["1F", "2F", "3F", "WF0", "NM0"],
        "models": ["F-Series", "Escape / Kuga", "Explorer", "Focus", "Fiesta",
                   "Ranger", "Mustang", "Edge", "Transit", "Bronco"],
        "notes": "Full engine/I-M/live support. Ford ABS often lives on MS-CAN (adapter-dependent); generic C-code scan included.",
    },
    "Honda": {
        "wmi": ["JH", "19X", "2H", "5J6", "SHS", "3H"],
        "models": ["Civic", "Accord", "CR-V", "Fit / Jazz", "HR-V", "Pilot",
                   "Odyssey", "Ridgeline", "Insight", "Passport"],
        "notes": "Full engine/I-M/live support. Honda ABS/SRS codes often need Honda tooling; generic C-code scan included.",
    },
    "Nissan": {
        "wmi": ["JN", "1N", "3N", "5N", "SJN"],
        "models": ["Altima", "Sentra", "Rogue / X-Trail", "Leaf", "Qashqai",
                   "Pathfinder", "Frontier / Navara", "Maxima", "Murano", "Patrol"],
        "notes": "Full engine/I-M/live support. Nissan ABS often needs brand tooling (Consult); generic C-code scan included.",
    },
    "Hyundai": {
        "wmi": ["KMH", "5NM", "KM8"],
        "models": ["Elantra", "Sonata", "Tucson", "Santa Fe", "Accent", "Kona",
                   "Palisade", "Ioniq 5", "Veloster", "Grandeur / Azera"],
        "notes": "Full engine/I-M/live support. ABS via generic C-code scan; module-specific access needs brand tooling.",
    },
    "GM": {
        "wmi": ["1G", "2G", "3G", "KL"],
        "models": ["Silverado", "Equinox", "Malibu", "Cruze", "Traverse", "Tahoe",
                   "Colorado", "Camaro", "Spark", "Suburban"],
        "notes": "Full engine/I-M/live support. GM often exposes C-codes in generic Mode 03 — good ABS hit rate via generic scan.",
    },
    "Kia": {
        "wmi": ["KNA", "5XY", "KND"],
        "models": ["Sportage", "Sorento", "Forte / Cerato", "Rio", "Telluride",
                   "Soul", "Optima / K5", "Carnival", "Niro", "Stonic"],
        "notes": "Full engine/I-M/live support. ABS via generic C-code scan; module-specific access needs brand tooling.",
    },
    "Mercedes": {
        "wmi": ["WDB", "WDC", "WDD", "4JG"],
        "models": ["C-Class", "E-Class", "S-Class", "GLC", "GLE", "A-Class",
                   "GLA", "G-Class", "CLA", "Sprinter"],
        "notes": "Full engine/I-M/live support. Mercedes modules (incl. ABS/ESP) usually need XENTRY-level tooling; generic C-code scan included.",
    },
    "BMW": {
        "wmi": ["WBA", "WBS", "4US", "5UX", "5YM"],
        "models": ["3 Series", "5 Series", "X3", "X5", "X1", "7 Series",
                   "4 Series", "2 Series", "X7", "i4"],
        "notes": "Full engine/I-M/live support. BMW modules (incl. DSC/ABS) usually need ISTA-level tooling; generic C-code scan included.",
    },
}


def protocol_hint(year: int | None) -> str:
    """Rough protocol expectation from model year (all OBD-II cars)."""
    if year is None:
        return "OBD-II (protocol auto-detect)"
    if year < 1996:
        return "pre-OBD-II — generic reader unlikely to work"
    if year == 2007:
        return "transitional year: CAN or ISO/KWP depending on make (auto-detect decides)"
    if year < 2008:
        return "likely ISO 9141-2 / KWP2000 / J1850 (slower, some PIDs missing)"
    return "likely CAN 11-bit 500k (full PID support expected)"


def brand_info(make: str) -> dict | None:
    return BRANDS.get(make)
