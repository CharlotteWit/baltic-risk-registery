"""
ais_vessels.py — list every vessel captured from the live AIS feed (i.e. those
that passed the ship-type selection), and show whether each is in our sanction
registry, plus its registry name and age.

Clarifies the M3 result: the ship-type filter is what removes vessels; the
sanction cross-check only LABELS them. Most captured vessels are ordinary
traffic kept by the type filter and simply not on any sanction list.

Columns: mmsi, imo, in_sanction_registry, name (registry, latest-known), built_year,
age, type_category, ais_ship_type, last position + time.
Registry-only fields (name/built_year/age) are left blank for vessels not in the
registry — we never guess them.
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
from identity import group_identity_history, current_value, display_name

AIS_SOURCE = "aisstream"
EXPORT_PATH = Path(__file__).resolve().parents[2] / "exports" / "ais_vessels.csv"
THIS_YEAR = datetime.now(timezone.utc).year


def latest_positions(conn):
    """One row per MMSI: its most recent AIS position (with imo/type if known)."""
    return conn.execute(
        """SELECT p.* FROM positions p
           JOIN (SELECT mmsi, MAX(timestamp) mt FROM positions WHERE source_id=?
                 GROUP BY mmsi) last
             ON p.mmsi=last.mmsi AND p.timestamp=last.mt
           WHERE p.source_id=?
           GROUP BY p.mmsi""", (AIS_SOURCE, AIS_SOURCE)).fetchall()


def registry_name(conn, imo):
    rows = conn.execute("SELECT value, origin_dataset, first_seen, last_seen "
                        "FROM identity_history WHERE imo=? AND field='name'", (imo,)).fetchall()
    cur = current_value(group_identity_history(rows, "name")) if rows else None
    return display_name(cur) if cur else ""


def built_year_and_age(conn, imo):
    years = []
    for r in conn.execute("SELECT DISTINCT value FROM facts WHERE imo=? AND field='built_year' "
                          "AND value IS NOT NULL", (imo,)):
        try:
            years.append(int(r["value"]))
        except (TypeError, ValueError):
            pass
    if not years:
        return "", ""
    oldest = min(years)                       # conservative: oldest reported build year
    shown = "/".join(str(y) for y in sorted(set(years)))
    return shown, THIS_YEAR - oldest


def build_rows(conn):
    rows = []
    for p in latest_positions(conn):
        imo = p["imo"]
        in_reg = imo is not None
        name = registry_name(conn, imo) if in_reg else ""
        built, age = built_year_and_age(conn, imo) if in_reg else ("", "")
        rows.append({
            "mmsi": p["mmsi"], "imo": imo or "",
            "in_sanction_registry": "yes" if in_reg else "no",
            "name": name, "built_year": built, "age": age,
            "type_category": p["type_category"] or "",
            "ais_ship_type": p["ais_ship_type"] if p["ais_ship_type"] is not None else "",
            "last_lat": round(p["lat"], 4), "last_lon": round(p["lon"], 4),
            "last_time": p["timestamp"],
        })
    # Registry matches first, then by MMSI.
    rows.sort(key=lambda r: (r["in_sanction_registry"] != "yes", r["mmsi"]))
    return rows


def is_over_20(r):
    return isinstance(r["age"], int) and r["age"] > 20


def write_csv(rows):
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cols = ["mmsi", "imo", "in_sanction_registry", "name", "built_year", "age",
            "over_20", "type_category", "ais_ship_type", "last_lat", "last_lon", "last_time"]
    with open(EXPORT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            row = dict(r)
            row["over_20"] = "yes" if is_over_20(r) else ""
            w.writerow({c: row.get(c, "") for c in cols})


def print_table(rows):
    hdr = (f"{'MMSI':10s} {'IMO':9s} {'reg':4s} {'name':16s} {'built':9s} "
           f"{'age':4s} {'type':9s} {'AIScode':7s}")
    print(hdr)
    for r in rows:
        mark = " *>20" if is_over_20(r) else ""
        print(f"{r['mmsi']:10s} {str(r['imo']):9s} {r['in_sanction_registry']:4s} "
              f"{(r['name'] or '')[:16]:16s} {str(r['built_year']):9s} {str(r['age']):4s} "
              f"{r['type_category']:9s} {str(r['ais_ship_type']):7s}{mark}")


def main():
    conn = db.connect()
    rows = build_rows(conn)
    in_reg = [r for r in rows if r["in_sanction_registry"] == "yes"]
    not_reg = [r for r in rows if r["in_sanction_registry"] == "no"]
    by_cat = defaultdict(int)
    for r in rows:
        by_cat[r["type_category"]] += 1

    # Keep-rule: in registry, OR (not in registry AND age > 20). Non-registry
    # vessels have no age source, so the second clause can never fire — stated
    # openly rather than silently dropping them.
    kept = [r for r in rows if r["in_sanction_registry"] == "yes" or is_over_20(r)]
    not_reg_over20 = [r for r in not_reg if is_over_20(r)]
    not_reg_age_unknown = [r for r in not_reg if r["age"] == ""]

    print(f"Total distinct vessels captured from AIS (passed type filter): {len(rows)}")
    print(f"  IN sanction registry: {len(in_reg)}   NOT in registry: {len(not_reg)}")
    print("\nBy kept type category:")
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {cat or '(none)':14s} {n}")

    print(f"\n=== KEPT (in registry, OR not-in-registry & age > 20): {len(kept)} vessels ===")
    print_table(sorted(kept, key=lambda r: (r["in_sanction_registry"] != "yes",
                                            -(r["age"] if isinstance(r["age"], int) else 0))))

    print(f"\nNon-registry vessels older than 20: {len(not_reg_over20)}")
    print(f"Non-registry vessels with UNKNOWN age (no build-year source — AIS does "
          f"not broadcast build year): {len(not_reg_age_unknown)}")
    print("  -> the 'age > 20' rule cannot include these without a ship-particulars"
          " source (e.g. Equasis, parked in TODO.md).")

    write_csv(rows)
    print(f"\nFull table ({len(rows)} vessels) written to: {EXPORT_PATH}")


if __name__ == "__main__":
    main()
