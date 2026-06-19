"""Explain one vessel's score in full. Usage: py scripts/debug_score.py 9187631"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db
from inference import risk_engine

imo = sys.argv[1] if len(sys.argv) > 1 else "9187631"
conn = db.connect()

print("=== built_year facts ===")
for r in conn.execute("SELECT value, source_id, retrieved_at FROM facts WHERE imo=? AND field='built_year'", (imo,)):
    print(" ", dict(r))
print("=== vessel_type facts ===")
for r in conn.execute("SELECT value, source_id FROM facts WHERE imo=? AND field='vessel_type'", (imo,)):
    print(" ", dict(r))
print("=== NAME history (identity_history) ===")
for r in conn.execute("SELECT value, origin_dataset, first_seen FROM identity_history WHERE imo=? AND field='name' ORDER BY first_seen", (imo,)):
    print(" ", dict(r))
print("=== FLAG history ===")
for r in conn.execute("SELECT value, origin_dataset, first_seen FROM identity_history WHERE imo=? AND field='flag' ORDER BY first_seen", (imo,)):
    print(" ", dict(r))
print("=== list_membership ===")
for r in conn.execute("SELECT DISTINCT list_name FROM list_membership WHERE imo=?", (imo,)):
    print(" ", r["list_name"])
print()
risk_engine.show(conn, imo)
