"""
identity.py — helpers for reasoning about a vessel's identity history
(IMO number / flag / name) WITHOUT inventing anything.

The raw values stay exactly as the source reported them (stored in
identity_history). These helpers only decide what counts as the "same" value for
change detection, so that purely cosmetic differences — UPPER vs lower case,
extra spaces — are NOT mistaken for a real rename or reflagging. A genuine new
name/flag still shows up as a change.
"""

import re


def is_valid_imo(value):
    """True if `value` is a well-formed 7-digit IMO number per its check digit.

    IMO rule: multiply the first 6 digits by 7,6,5,4,3,2, sum them; the last
    digit of that sum must equal the 7th digit. This catches malformed or
    non-IMO identifiers, but does NOT prove the number belongs to a real ship
    (that needs the IMO registry — see GISIS verification in TODO.md)."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 7:
        return False
    checksum = sum(int(digits[i]) * (7 - i) for i in range(6))
    return checksum % 10 == int(digits[6])


def normalize_identity_value(field, value):
    """Return a comparison key for a value. Display still uses the raw value;
    this is only for deciding whether two values are 'the same'.

    - imo_number: digits only (so 'IMO9332810' == '9332810')
    - flag:       trimmed, lower-cased (codes are already canonical)
    - name:       trimmed, internal whitespace collapsed, lower-cased
                  (so 'NS Silver', 'NS  SILVER ' and 'ns silver' all match)
    """
    if value is None:
        return None
    v = str(value)
    if field == "imo_number":
        return re.sub(r"\D", "", v)
    if field == "flag":
        return v.strip().lower()
    if field == "name":
        return re.sub(r"\s+", " ", v).strip().lower()
    return v.strip()


def _get(row, key):
    """Read a key from either a sqlite3.Row or a plain dict; None if absent."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def group_identity_history(rows, field):
    """Collapse identity_history rows for one field into distinct values.

    `rows` is any iterable of mappings with 'value', 'origin_dataset',
    'first_seen' and (optionally) 'last_seen'. Returns a list of groups sorted by
    earliest first_seen:
        {key, variants: [raw...], first_seen, last_seen, datasets: [...]}
    Values that differ only by case/spacing land in the same group.
    """
    groups = {}
    for r in rows:
        key = normalize_identity_value(field, r["value"])
        g = groups.setdefault(key, {"key": key, "variants": set(),
                                    "firsts": [], "lasts": [], "datasets": set()})
        g["variants"].add(r["value"])
        if _get(r, "first_seen"):
            g["firsts"].append(r["first_seen"])
        if _get(r, "last_seen"):
            g["lasts"].append(r["last_seen"])
        if _get(r, "origin_dataset"):
            g["datasets"].add(r["origin_dataset"])
    out = [{
        "key": g["key"],
        "variants": sorted(g["variants"]),
        "first_seen": min(g["firsts"]) if g["firsts"] else None,
        "last_seen": max(g["lasts"]) if g["lasts"] else None,
        "datasets": sorted(g["datasets"]),
    } for g in groups.values()]
    out.sort(key=lambda x: x["first_seen"] or "")
    return out


def current_value(groups):
    """The 'latest known' value for a field — our rule for the operative
    name/flag (the one most likely current on the water).

    This is an INFERENCE, not a fact: we pick the value with the most recent
    `first_seen` (when it first appeared in any list — a proxy for when the
    vessel adopted it). Ties break toward the value corroborated by more lists,
    then deterministically by name. The real-time ground truth is AIS (M3).

    Returns the chosen group dict (with .variants/.first_seen/.datasets), or None.
    """
    if not groups:
        return None
    return max(groups, key=lambda g: (g["first_seen"] or "",
                                      len(g["datasets"]),
                                      g["variants"][0] if g["variants"] else ""))


def display_name(group):
    """A single readable label for a chosen group (prefers a mixed-case variant
    over an ALL-CAPS one when both exist, since the data carries both)."""
    if not group or not group["variants"]:
        return None
    mixed = [v for v in group["variants"] if v != v.upper()]
    return (mixed or group["variants"])[0]


def recent_changes(groups, cutoff_iso):
    """Return the groups that represent a genuine change first observed on/after
    cutoff_iso. Requires more than one distinct value (a lone value is the vessel's
    only known identity, not a change)."""
    if len(groups) <= 1:
        return []
    return [g for g in groups if g["first_seen"] and g["first_seen"] >= cutoff_iso]
