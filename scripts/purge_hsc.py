"""One-off: remove HSC positions from the register (HSC dropped 2026-06-18)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db

conn = db.connect()
with conn:
    n = conn.execute("DELETE FROM positions WHERE type_category='hsc'").rowcount
print("deleted hsc positions:", n)
remaining = conn.execute(
    "SELECT COUNT(DISTINCT mmsi) c FROM positions WHERE type_category='hsc'").fetchone()["c"]
print("hsc vessels remaining:", remaining)
