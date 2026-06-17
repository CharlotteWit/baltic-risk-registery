"""
refresh.py — the regular refresh routine for the deterministic fact sources.

Runs in order:
  1. OpenSanctions  — refresh sanctioned-vessel facts + list membership (M1/M2).
  2. Wikidata       — re-check every IMO in the database for a matching item and
                      refresh its facts (Part 1). New vessels added since last
                      refresh are therefore checked automatically.

NOT run here (they are long-running / live and started separately):
  * the live AIS feed (connectors/ais_stream.py),
  * the continuous age-risk monitor (age_risk_monitor.py), which also triggers
    Wikidata lookups for AIS-sighted vessels not yet in our facts.

Usage:  py src/refresh.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from connectors import opensanctions, wikidata


def main():
    conn = db.init_db()

    key = (os.getenv("OPENSANCTIONS_API_KEY") or "").strip()
    if key:
        print("[1/2] Refreshing OpenSanctions facts + lists...")
        opensanctions.ingest(conn, key)
    else:
        print("[1/2] Skipping OpenSanctions (no OPENSANCTIONS_API_KEY in .env)")

    print("[2/2] Refreshing Wikidata facts for all IMOs in the database...")
    with conn:
        conn.execute("DELETE FROM facts WHERE source_id=?", (wikidata.SOURCE_ID,))
    imos = [r["imo"] for r in conn.execute("SELECT DISTINCT imo FROM facts")]
    stats = wikidata.ingest(conn, imos)
    print(f"  Wikidata: {stats['matched']} of {stats['queried']} IMOs matched, "
          f"{stats['facts']} facts.")

    print("\nRefresh complete.")


if __name__ == "__main__":
    main()
