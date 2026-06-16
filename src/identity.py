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


def group_identity_history(rows, field):
    """Collapse identity_history rows for one field into distinct values.

    `rows` is any iterable of mappings with 'value', 'origin_dataset',
    'first_seen'. Returns a list of groups sorted by earliest first_seen:
        {key, variants: [raw...], first_seen, datasets: [...]}
    Values that differ only by case/spacing land in the same group.
    """
    groups = {}
    for r in rows:
        key = normalize_identity_value(field, r["value"])
        g = groups.setdefault(key, {"key": key, "variants": set(),
                                    "firsts": [], "datasets": set()})
        g["variants"].add(r["value"])
        if r["first_seen"]:
            g["firsts"].append(r["first_seen"])
        if r["origin_dataset"]:
            g["datasets"].add(r["origin_dataset"])
    out = [{
        "key": g["key"],
        "variants": sorted(g["variants"]),
        "first_seen": min(g["firsts"]) if g["firsts"] else None,
        "datasets": sorted(g["datasets"]),
    } for g in groups.values()]
    out.sort(key=lambda x: x["first_seen"] or "")
    return out


def recent_changes(groups, cutoff_iso):
    """Return the groups that represent a genuine change first observed on/after
    cutoff_iso. Requires more than one distinct value (a lone value is the vessel's
    only known identity, not a change)."""
    if len(groups) <= 1:
        return []
    return [g for g in groups if g["first_seen"] and g["first_seen"] >= cutoff_iso]
