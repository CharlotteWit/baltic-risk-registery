"""Show a vessel's list membership with the source URL behind each, for
spot-checking the M2 reconciliation.  Usage: py scripts/show_membership.py 8227238"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db

conn = db.connect()
for imo in sys.argv[1:]:
    print(f"\n=== IMO {imo} — list membership ===")
    rows = conn.execute(
        "SELECT list_name, present, as_of, source_url FROM list_membership "
        "WHERE imo=? ORDER BY list_name", (imo,)).fetchall()
    if not rows:
        print("  (no membership rows)")
    for r in rows:
        print(f"  {r['list_name']:12s} present={r['present']}  "
              f"as_of={r['as_of'][:10]}  {r['source_url']}")
