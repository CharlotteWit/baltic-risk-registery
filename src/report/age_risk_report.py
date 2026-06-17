"""
age_risk_report.py — the Part-2 "show me" view.

Reports, for vessels observed via AIS:
  * how many now have a known build year, broken down by source
    (sanctions-list/primary facts vs Wikidata),
  * how many are flagged over 20 years old (rule R1),
  * one full evidence trail for a flagged vessel:
    AIS sighting -> Wikidata built_year fact (with item URL) -> risk flag.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db


def ais_imos(conn):
    return [r["imo"] for r in conn.execute(
        "SELECT DISTINCT imo FROM positions WHERE imo IS NOT NULL AND source_id='aisstream'")]


def built_year_sources(conn, imo):
    rows = conn.execute("SELECT DISTINCT source_id FROM facts WHERE imo=? AND "
                        "field='built_year' AND value IS NOT NULL", (imo,)).fetchall()
    return {r["source_id"] for r in rows}


def main():
    conn = db.connect()
    imos = ais_imos(conn)
    primary, wikidata_only, none = [], [], []
    for imo in imos:
        srcs = built_year_sources(conn, imo)
        if srcs - {"wikidata"}:
            primary.append(imo)
        elif "wikidata" in srcs:
            wikidata_only.append(imo)
        else:
            none.append(imo)

    flagged = {r["imo"] for r in conn.execute(
        "SELECT DISTINCT imo FROM risk_flags WHERE rule_id='R1' AND triggered=1")}
    flagged_ais = [i for i in imos if i in flagged]

    print("=" * 74)
    print("PART 2 — AIS-triggered build year + early R1 age flag")
    print("=" * 74)
    print(f"AIS-observed vessels with a known IMO: {len(imos)}")
    print(f"  build year known: {len(primary) + len(wikidata_only)}")
    print(f"    - from sanctions-list / primary facts: {len(primary)}")
    print(f"    - from Wikidata only:                  {len(wikidata_only)}")
    print(f"  build year still unknown:                {len(none)}")
    print(f"\nFlagged R1 (over 20 years old): {len(flagged_ais)} of the AIS-observed vessels")

    # Full evidence trail — prefer a vessel flagged via a Wikidata-sourced build year.
    trail_imo = None
    for imo in flagged_ais:
        fl = conn.execute("SELECT evidence FROM risk_flags WHERE imo=? AND rule_id='R1' "
                          "AND triggered=1 ORDER BY flag_id DESC LIMIT 1", (imo,)).fetchone()
        if fl and json.loads(fl["evidence"]).get("built_year_source") == "wikidata":
            trail_imo = imo
            break
    if trail_imo is None and flagged_ais:
        trail_imo = flagged_ais[0]

    if trail_imo:
        print("\n" + "-" * 74)
        print(f"FULL EVIDENCE TRAIL — IMO {trail_imo}")
        print("-" * 74)
        pos = conn.execute("SELECT lat, lon, sog, timestamp, type_category, ais_ship_type "
                           "FROM positions WHERE imo=? AND source_id='aisstream' "
                           "ORDER BY timestamp DESC LIMIT 1", (trail_imo,)).fetchone()
        print("1) AIS SIGHTING (entered a monitored region):")
        print(f"     {pos['timestamp']}  lat {pos['lat']:.4f}, lon {pos['lon']:.4f}  "
              f"sog {pos['sog']} kn  type={pos['type_category']} (code {pos['ais_ship_type']})")
        by = conn.execute("SELECT fact_id, value, source_id, source_url, note FROM facts "
                          "WHERE imo=? AND field='built_year' ORDER BY source_id", (trail_imo,)).fetchall()
        print("2) BUILD YEAR FACT(S):")
        for r in by:
            print(f"     fact #{r['fact_id']}  built_year={r['value']}  source={r['source_id']}")
            print(f"        {r['source_url']}")
            if r["note"]:
                print(f"        note: {r['note']}")
        fl = conn.execute("SELECT flag_id, rule_id, weight, evidence, evaluated_at FROM risk_flags "
                          "WHERE imo=? AND rule_id='R1' AND triggered=1 ORDER BY flag_id DESC LIMIT 1",
                          (trail_imo,)).fetchone()
        ev = json.loads(fl["evidence"])
        print("3) RESULTING RISK FLAG:")
        print(f"     flag #{fl['flag_id']}  rule {fl['rule_id']} (weight {fl['weight']})  "
              f"at {fl['evaluated_at']}")
        print(f"     age {ev['age']} (built {ev['built_year']}) > 20  "
              f"-> based on built_year fact #{ev['built_year_fact_id']} "
              f"from {ev['built_year_source']}")
        print(f"     {ev['source_url']}")


if __name__ == "__main__":
    main()
