"""Show captured AIS destinations and how the gazetteer classifies them by direction."""
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db
from inference.eastbound_transit import classify_destination

conn = db.connect()
rows = conn.execute("SELECT DISTINCT value FROM facts WHERE field='ais_destination' "
                    "AND value IS NOT NULL").fetchall()
total = conn.execute("SELECT COUNT(*) c FROM facts WHERE field='ais_destination'").fetchone()["c"]
print(f"ais_destination facts: {total}  ({len(rows)} distinct values)")
counts = Counter(classify_destination(r["value"])[0] for r in rows)
print("classification by direction:", dict(counts))
print("\nexamples (declared -> class):")
for r in rows[:20]:
    cls, tok = classify_destination(r["value"])
    print(f"   {r['value'][:30]:30s} -> {cls}")
