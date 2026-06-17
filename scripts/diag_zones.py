"""Diagnostic: how many AIS positions fall within each terminal zone, and of
those how many are slow (<=1kn) and IMO-known? Explains why detection fired or not."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db
from inference.port_calls import load_terminals, haversine_km

conn = db.connect()
pos = conn.execute("SELECT imo, lat, lon, sog FROM positions WHERE source_id='aisstream'").fetchall()
print(f"total aisstream positions: {len(pos)}")
for t in load_terminals():
    inzone = [p for p in pos if haversine_km(p["lat"], p["lon"], t["lat"], t["lon"]) <= t["radius_km"]]
    slow = [p for p in inzone if p["sog"] is not None and p["sog"] <= 1.0]
    slow_imo = [p for p in slow if p["imo"]]
    print(f"  {t['name']:28s} ({t['tier']}): in-zone={len(inzone):4d}  slow<=1kn={len(slow):3d}  "
          f"slow&IMO={len(slow_imo):3d}")
