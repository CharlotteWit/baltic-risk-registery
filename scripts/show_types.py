"""Overview of ship types currently in the register (kept by the AIS filter)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db

conn = db.connect()
codemap = {"tanker": "80-89", "cargo": "70-79", "unknown": "0 / missing",
           "other": "1-29,38-39,56-57,90-99", "hsc": "40-49",
           "military": "35,59", "law_enforcement": "55", "sar": "51"}

total = conn.execute("SELECT COUNT(DISTINCT mmsi) FROM positions WHERE source_id='aisstream'").fetchone()[0]
print("Distinct vessels in the register (kept by the AIS ship-type filter):\n")
print(f"{'category':18s} {'vessels':>8s}   AIS codes")
for r in conn.execute("SELECT type_category cat, COUNT(DISTINCT mmsi) n FROM positions "
                      "WHERE source_id='aisstream' GROUP BY type_category ORDER BY n DESC"):
    cat = r["cat"] or "(none)"
    print(f"{cat:18s} {r['n']:8d}   {codemap.get(cat, '')}")
print("-" * 42)
print(f"{'TOTAL':18s} {total:8d}")

known = conn.execute("SELECT COUNT(DISTINCT mmsi) FROM positions WHERE source_id='aisstream' "
                     "AND ais_ship_type IS NOT NULL").fetchone()[0]
print(f"\nVessels whose specific AIS ship-type code was actually received: {known}")
print("(the rest are tagged 'unknown' until they broadcast static data — kept, not dropped)")

print("\nFor reference, dropped types (NOT in the register): "
      "passenger/ferry (60-69), fishing (30), tug (31/32/52), sailing (36), "
      "pleasure (37), service/pilot/dredger (33/34/50/53/54/58).")
