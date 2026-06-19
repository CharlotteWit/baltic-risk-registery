"""
refresh.py — the single command that updates everything and rebuilds the outputs.

Pipeline:
  1. OpenSanctions   — refresh sanctioned-vessel facts + list membership (M1/M2).
  2. Wikidata        — re-check every IMO for a matching item, refresh its facts.
  3. AIS             — pull fresh live positions for a bounded time (M3).
  4. Age-risk        — for AIS-sighted vessels with no build year, query Wikidata,
                       then apply the early R1 age flag (M1b).
  5. Risk engine     — recompute every rule, score and band for every vessel (M5).
  6. Map + export    — rebuild exports/map.html and the sourced CSV/JSON (M6/M7).

Usage:
  py src/refresh.py
Environment:
  REFRESH_AIS_SECONDS   how long to listen for AIS (default 180; 0 = skip AIS)
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

import db
from connectors import opensanctions, wikidata, ais_stream
import age_risk_monitor
from inference import risk_engine
from report import map_report, export


def main():
    load_dotenv()
    conn = db.init_db()
    os_key = (os.getenv("OPENSANCTIONS_API_KEY") or "").strip()
    ais_key = (os.getenv("AISSTREAM_API_KEY") or "").strip()
    ais_secs = int(os.getenv("REFRESH_AIS_SECONDS", "180"))

    print("[1/6] OpenSanctions facts + lists...")
    if os_key:
        opensanctions.ingest(conn, os_key)
    else:
        print("      skipped (no OPENSANCTIONS_API_KEY)")

    print("[2/6] Wikidata facts (all IMOs)...")
    with conn:
        conn.execute("DELETE FROM facts WHERE source_id=?", (wikidata.SOURCE_ID,))
    imos = [r["imo"] for r in conn.execute("SELECT DISTINCT imo FROM facts")]
    wikidata.ingest(conn, imos)

    print(f"[3/6] Live AIS for {ais_secs}s...")
    if ais_key and ais_secs > 0:
        asyncio.run(ais_stream.run(conn, ais_key, ais_secs, max_messages=100000))
    else:
        print("      skipped (no AISSTREAM_API_KEY or REFRESH_AIS_SECONDS=0)")

    print("[4/6] Age-risk (Wikidata for AIS-sighted + R1)...")
    age_risk_monitor.run_once(conn)

    print("[5/6] Risk engine (recompute all scores)...")
    stats = risk_engine.run(conn)
    print(f"      scored {stats['scored']} vessels: {stats['by_band']}")

    print("[6/6] Rebuild map + sourced export...")
    map_report.build(conn)
    allimos = [r["imo"] for r in conn.execute(
        "SELECT imo FROM risk_scores ORDER BY total_score DESC")]
    export.write_csv(conn, allimos)
    export.write_json(conn, allimos)

    print("\nRefresh complete. Outputs in exports/: map.html, vessels.csv, vessels.json")


if __name__ == "__main__":
    main()
