"""
ais_types.py — maps the AIS "ship type" code (ITU-R M.1371, the field broadcast
in AIS ShipStaticData messages) to the coarse categories we filter on in M3.

IMPORTANT HONESTY NOTE (state this to the user):
The AIS ship-type code is COARSE. It only distinguishes "Tanker" (80-89) and
"Cargo" (70-79) as broad buckets. It CANNOT, on its own, tell a crude-oil tanker
from a chemical or LNG tanker, nor a bulk carrier from a general-cargo ship. Those
fine distinctions come from registry data (e.g. OpenSanctions/Equasis vessel_type
facts), not from AIS. So at the AIS stage we keep tankers and cargo ships, drop
clearly-irrelevant types, and keep unknown/other for later size-based triage.
"""

# We DROP only the categories below; EVERYTHING else is kept. Per the user's
# assessment (2026-06-17): keep all tankers (any cargo can be an environmental
# threat), keep unknown/other (triage later by size), keep HSC (40-49, triage
# later), and keep military/noncombatant, law-enforcement and SAR because these
# may interact with vessels in trouble at sea (proximity analysis later — see
# TODO.md and the README "Why these vessels are included" section).
EXCLUDE_CATEGORIES = {"fishing", "tug", "sailing", "pleasure", "passenger", "service"}

# Kept categories, for reference/documentation.
INCLUDE_CATEGORIES = {"tanker", "cargo", "unknown", "other", "hsc",
                      "military", "law_enforcement", "sar"}


def should_store(category):
    """Keep everything except the explicitly excluded categories."""
    return category not in EXCLUDE_CATEGORIES


def category_for_type(code):
    """Return our category for an AIS ship-type code (int or None)."""
    if code in (None, ""):
        return "unknown"
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "unknown"
    if c == 0:                return "unknown"          # 0 = not available
    if 1 <= c <= 29:          return "other"            # reserved + wing-in-ground
    if c == 30:               return "fishing"
    if c in (31, 32):         return "tug"              # towing
    if c in (33, 34):         return "service"          # dredging / diving ops
    if c == 35:               return "military"
    if c == 36:               return "sailing"
    if c == 37:               return "pleasure"
    if 38 <= c <= 39:         return "other"            # reserved
    if 40 <= c <= 49:         return "hsc"              # high-speed (mostly passenger)
    if c == 50:               return "service"          # pilot vessel
    if c == 51:               return "sar"              # search & rescue
    if c == 52:               return "tug"
    if c in (53, 54, 58):     return "service"          # port tender / anti-poll / medical
    if c == 55:               return "law_enforcement"
    if c in (56, 57):         return "other"            # local / spare
    if c == 59:               return "military"         # noncombatant
    if 60 <= c <= 69:         return "passenger"
    if 70 <= c <= 79:         return "cargo"
    if 80 <= c <= 89:         return "tanker"
    if 90 <= c <= 99:         return "other"
    return "unknown"


# Human-readable mapping, for showing the user before relying on it.
MAPPING_TABLE = [
    ("80-89", "Tanker (incl. crude/products/chemical/LNG/LPG)", "tanker", "KEEP"),
    ("70-79", "Cargo (incl. bulk & general cargo)",             "cargo",  "KEEP"),
    ("0 / missing", "Not available",                            "unknown", "KEEP (tag)"),
    ("1-29, 38-39, 56-57, 90-99", "Reserved / WIG / other",     "other",  "KEEP (tag)"),
    ("40-49", "High-speed craft",                               "hsc",    "KEEP"),
    ("35, 59", "Military / noncombatant",                       "military", "KEEP"),
    ("55",    "Law enforcement",                                "law_enforcement", "KEEP"),
    ("51",    "Search & rescue",                                "sar",    "KEEP"),
    ("60-69", "Passenger / ferries / cruise",                   "passenger", "drop"),
    ("36",    "Sailing",                                        "sailing", "drop"),
    ("37",    "Pleasure craft",                                 "pleasure", "drop"),
    ("30",    "Fishing",                                        "fishing", "drop"),
    ("31,32,52", "Tug / towing",                                "tug",    "drop"),
    ("33,34,50,53,54,58", "Service (dredge/dive/pilot/tender/medical)", "service", "drop"),
]


def print_mapping():
    print("AIS ship-type code -> category mapping (ITU-R M.1371):")
    print(f"  {'codes':22s} {'meaning':46s} {'category':16s} action")
    for codes, meaning, cat, action in MAPPING_TABLE:
        print(f"  {codes:22s} {meaning:46s} {cat:16s} {action}")
    print("\n  NOTE: AIS gives only coarse 'tanker'/'cargo' buckets — crude vs"
          " chemical vs LNG, or bulk vs general cargo, come from registry data, not AIS.")


if __name__ == "__main__":
    print_mapping()
