"""
age_risk_monitor.py — runs the early R1 age-risk pipeline CONTINUOUSLY over
vessels observed via AIS.

Each pass:
  1. Find every IMO seen in the positions table (an AIS sighting in a monitored
     region; positions only ever contains kept ship-type categories).
  2. For any such vessel with no built_year from any source, query Wikidata
     (batched for efficiency — same connector, AIS-triggered instead of
     sanctions-list-triggered).
  3. Apply rule R1 (age > 20) to every vessel that now has a build year.

Run a single pass (default) or loop with --loop (interval AGE_RISK_INTERVAL secs),
so it keeps flagging new vessels as they are sighted.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import age_risk
from connectors import wikidata


def ais_sighted_imos(conn):
    return [r["imo"] for r in conn.execute(
        "SELECT DISTINCT imo FROM positions "
        "WHERE imo IS NOT NULL AND source_id='aisstream'")]


def run_once(conn):
    imos = ais_sighted_imos(conn)
    missing = [i for i in imos if not age_risk.built_year_facts(conn, i)]
    if missing:
        print(f"  {len(missing)} AIS-sighted vessels lack a build year -> querying Wikidata...",
              flush=True)
        wikidata.ingest(conn, missing, chunk_size=100, polite_delay=0.6)
    flagged = 0
    for imo in imos:
        f, _ = age_risk.flag_r1(conn, imo)
        if f:
            flagged += 1
    return {"ais_vessels": len(imos), "needed_wikidata": len(missing), "r1_flagged": flagged}


def main():
    conn = db.init_db()
    loop = "--loop" in sys.argv
    interval = int(os.getenv("AGE_RISK_INTERVAL", "60"))
    while True:
        s = run_once(conn)
        print(f"pass: {s['ais_vessels']} AIS-sighted vessels | "
              f"{s['needed_wikidata']} needed Wikidata | {s['r1_flagged']} flagged R1 (>20yo)",
              flush=True)
        if not loop:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
