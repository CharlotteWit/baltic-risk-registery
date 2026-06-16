"""
show_vessel.py — print a vessel's stored data with FULL provenance so a
non-programmer can spot-check each value against the live source.

Two clearly separated sections:
  1. FACTS — current sourced values (name, flag, built year, etc.), each with the
     source URL and the time we retrieved it.
  2. IDENTITY CHANGE TRACKING — dated history of IMO number / flag / name from the
     source's own statement dates, with anything first observed in the last
     3 months marked as a recent change.

Usage:
  py scripts/show_vessel.py                 # 3 example vessels (richest histories)
  py scripts/show_vessel.py 9332810 ...     # specific IMO numbers
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db
from identity import group_identity_history, recent_changes

RECENT_DAYS = 90  # "last 3 months"


def show(conn, imo, cutoff_iso):
    facts = conn.execute(
        "SELECT field, value, source_id, source_url, retrieved_at "
        "FROM facts WHERE imo=? ORDER BY field, value", (imo,)
    ).fetchall()
    if not facts:
        print(f"\n=== IMO {imo}: no facts stored ===")
        return

    by_field = {}
    for r in facts:
        d = by_field.setdefault(r["field"], {"values": [], "url": r["source_url"],
                                             "src": r["source_id"], "ts": r["retrieved_at"]})
        if r["value"] is not None:
            d["values"].append(r["value"])

    print(f"\n{'='*80}\nVESSEL  IMO {imo}")
    lists = conn.execute("SELECT DISTINCT list_name FROM list_membership WHERE imo=? "
                         "ORDER BY list_name", (imo,)).fetchall()
    if lists:
        print("On lists:", ", ".join(l["list_name"] for l in lists))
    print('='*80)

    print("\n--- FACTS (source-reported) ---")
    for field in sorted(by_field):
        info = by_field[field]
        val = " | ".join(info["values"]) if info["values"] else "(unknown)"
        print(f"\n  {field}: {val}")
        print(f"      source    : {info['src']}")
        print(f"      source_url: {info['url']}")
        print(f"      retrieved : {info['ts']}")

    # --- Identity change tracking (dated, from source statement history) ---
    # Case/spacing differences are treated as the SAME value, so only genuine
    # renames/reflaggings count as changes (raw values still shown verbatim).
    print("\n--- IDENTITY CHANGE TRACKING (IMO / flag / name, source-dated) ---")
    print("    (case/spacing-only differences are NOT counted as changes)")
    any_recent = False
    for field in ("imo_number", "flag", "name"):
        rows = conn.execute(
            "SELECT value, origin_dataset, first_seen, last_seen, source_url "
            "FROM identity_history WHERE imo=? AND field=? ORDER BY first_seen", (imo, field)
        ).fetchall()
        if not rows:
            print(f"\n  {field}: (no dated history available)")
            continue
        groups = group_identity_history(rows, field)
        recent = recent_changes(groups, cutoff_iso)
        recent_keys = {g["key"] for g in recent}
        if recent:
            any_recent = True
        changed = len(groups) > 1
        tag = ""
        if field == "imo_number" and changed:
            tag = "  <-- MULTIPLE IMO NUMBERS (identity anomaly)"
        elif changed:
            tag = "  <-- value changed over time"
        print(f"\n  {field}: {len(groups)} distinct value(s){tag}")
        for g in groups:
            mark = "  ** NEW in last 3 months **" if g["key"] in recent_keys else ""
            shown = " / ".join(g["variants"])  # raw variants, verbatim
            ds = ", ".join(g["datasets"]) or "n/a"
            print(f"      - {shown}  first observed {g['first_seen']}{mark}")
            print(f"          via list(s): {ds}")
        if recent:
            new_disp = [" / ".join(g["variants"]) for g in recent]
            print(f"      => {field} CHANGE in last 3 months: new value(s) {new_disp} "
                  f"(per source first_seen; proxy for change date, not exact)")
    if not any_recent:
        print("\n  (No IMO/flag/name value was first observed within the last 3 months.)")


def main():
    conn = db.connect()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat(timespec="seconds")
    print(f"'Last 3 months' cutoff (UTC): {cutoff_iso}")
    imos = sys.argv[1:]
    if not imos:
        imos = [r["imo"] for r in conn.execute(
            "SELECT imo, COUNT(*) c FROM identity_history GROUP BY imo "
            "ORDER BY COUNT(DISTINCT value) DESC, c DESC LIMIT 3").fetchall()]
    for imo in imos:
        show(conn, imo, cutoff_iso)


if __name__ == "__main__":
    main()
