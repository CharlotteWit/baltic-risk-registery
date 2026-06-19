"""
export.py — M7: sourced CSV and JSON export.

Every value a vessel carries is exported WITH the source URL it came from and the
UTC time it was retrieved, so a journalist could verify any row from the file
alone. The score and the rules that produced it are included too, each traceable.

Outputs:
  exports/vessels.csv  — one row per vessel; for each key field a value column
                         plus <field>_source and <field>_retrieved columns.
  exports/vessels.json — richer: full current-fact list (with source + timestamp),
                         list memberships, and the risk flags that fired.

We export every scored vessel. The "current value" of a field is the most
recently retrieved fact for it (the append-only facts table preserves history).
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
from identity import group_identity_history, current_value, display_name

CSV_OUT = Path(__file__).resolve().parents[2] / "exports" / "vessels.csv"
JSON_OUT = Path(__file__).resolve().parents[2] / "exports" / "vessels.json"

# fields shown as value + source + retrieved columns in the CSV
KEY_FIELDS = ["name", "flag", "built_year", "vessel_type",
              "gross_registered_tonnage", "mmsi", "ais_destination"]


def current_name(conn, imo):
    rows = conn.execute("SELECT value, origin_dataset, first_seen, last_seen FROM identity_history "
                        "WHERE imo=? AND field='name'", (imo,)).fetchall()
    cur = current_value(group_identity_history(rows, "name")) if rows else None
    return display_name(cur) if cur else ""


def gather(conn, imo):
    """Assemble everything we know about one vessel, with provenance."""
    facts = db.current_profile(conn, imo)            # latest fact per field (+ source/url/time)
    by_field = {f["field"]: f for f in facts}
    sc = conn.execute("SELECT total_score, band FROM risk_scores WHERE imo=?", (imo,)).fetchone()
    lists = [r["list_name"] for r in conn.execute(
        "SELECT DISTINCT list_name FROM list_membership WHERE imo=? ORDER BY list_name", (imo,))]
    flags = conn.execute("SELECT rule_id, weight, evidence FROM risk_flags "
                         "WHERE imo=? AND triggered=1 ORDER BY weight DESC", (imo,)).fetchall()
    return by_field, facts, sc, lists, flags


def write_csv(conn, imos):
    cols = ["imo", "current_name", "risk_score", "band", "on_lists", "fired_rules"]
    for f in KEY_FIELDS:
        cols += [f, f"{f}_source", f"{f}_retrieved"]
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for imo in imos:
            by_field, _facts, sc, lists, flags = gather(conn, imo)
            row = [imo, current_name(conn, imo),
                   sc["total_score"] if sc else "", sc["band"] if sc else "",
                   "; ".join(lists),
                   "; ".join(f"{fl['rule_id']}(+{fl['weight']})" for fl in flags)]
            for f in KEY_FIELDS:
                r = by_field.get(f)
                if r:
                    row += [r["value"], r["source_url"], r["retrieved_at"]]
                else:
                    row += ["", "", ""]
            w.writerow(row)
    return CSV_OUT


def write_json(conn, imos):
    out = []
    for imo in imos:
        by_field, facts, sc, lists, flags = gather(conn, imo)
        out.append({
            "imo": imo,
            "current_name": current_name(conn, imo),
            "risk_score": sc["total_score"] if sc else None,
            "band": sc["band"] if sc else None,
            "lists": lists,
            "facts": [{"field": f["field"], "value": f["value"],
                       "source_id": f["source_id"], "source_url": f["source_url"],
                       "retrieved_at": f["retrieved_at"]} for f in facts],
            "risk_flags": [{"rule_id": fl["rule_id"], "weight": fl["weight"],
                            "evidence": json.loads(fl["evidence"])} for fl in flags],
        })
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSON_OUT


def main():
    conn = db.connect()
    imos = [r["imo"] for r in conn.execute(
        "SELECT imo FROM risk_scores ORDER BY total_score DESC")]
    write_csv(conn, imos)
    write_json(conn, imos)
    print(f"Exported {len(imos)} vessels.")
    print(f"  CSV : {CSV_OUT}")
    print(f"  JSON: {JSON_OUT}")
    print("\nEvery field column in the CSV has a matching _source (URL) and _retrieved (UTC) column.")


if __name__ == "__main__":
    main()
