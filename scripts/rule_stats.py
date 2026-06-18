"""How often each rule actually fires, and the data-coverage reality, for the
weight reassessment."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db
from inference.risk_engine import load_cfg

conn = db.connect()
weights, bands, foc = load_cfg()
total = conn.execute("SELECT COUNT(*) c FROM risk_scores").fetchone()["c"]
print(f"vessels scored: {total}\n")
print(f"{'rule':5s} {'wt':>2s}  {'fired':>6s}   description")
descr = {r['rule_id']: None for r in []}
import yaml
rules = yaml.safe_load((Path(__file__).resolve().parents[1] / 'rules.yaml').read_text(encoding='utf-8'))['rules']
d = {x['id']: x['description'] for x in rules}
for rid in ("R1", "R1b", "R3", "R4", "R5", "R6", "R8d", "R10"):
    n = conn.execute("SELECT COUNT(*) c FROM risk_flags WHERE rule_id=? AND triggered=1", (rid,)).fetchone()["c"]
    print(f"{rid:5s} {weights.get(rid,0):>2d}  {n:>6d}   {d.get(rid,'')[:50]}")

print("\nband distribution:")
for r in conn.execute("SELECT band, COUNT(*) c FROM risk_scores GROUP BY band ORDER BY c DESC"):
    print(f"  {r['band']:10s} {r['c']}")

# 'insufficient data' proxy: no built_year AND not on any list
nodata = conn.execute("""SELECT COUNT(*) c FROM risk_scores s WHERE total_score=0
   AND NOT EXISTS (SELECT 1 FROM facts f WHERE f.imo=s.imo AND f.field='built_year')
   AND NOT EXISTS (SELECT 1 FROM list_membership l WHERE l.imo=s.imo)""").fetchone()["c"]
print(f"\nscore-0 vessels with NO age and NO list membership (really 'insufficient data'): {nodata}")
