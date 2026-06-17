"""Show Wikidata-sourced facts for a few matched vessels, alongside the
primary-source value for the same field (to see agreement/disagreement).
Usage: py scripts/show_wikidata.py [IMO ...]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import db

conn = db.connect()
imos = sys.argv[1:]
if not imos:
    # auto-pick 3 vessels with the richest Wikidata data
    imos = [r["imo"] for r in conn.execute(
        "SELECT imo, COUNT(*) c FROM facts WHERE source_id='wikidata' "
        "GROUP BY imo ORDER BY c DESC LIMIT 3")]

total = conn.execute("SELECT COUNT(DISTINCT imo) FROM facts").fetchone()[0]
matched = conn.execute("SELECT COUNT(DISTINCT imo) FROM facts WHERE source_id='wikidata'").fetchone()[0]
print(f"Wikidata match: {matched} of {total} IMOs in our database got at least one match\n")

for imo in imos:
    wd = conn.execute("SELECT field, value, source_url, note FROM facts "
                      "WHERE imo=? AND source_id='wikidata' ORDER BY field, value", (imo,)).fetchall()
    if not wd:
        print(f"=== IMO {imo}: no Wikidata facts ===\n"); continue
    url = wd[0]["source_url"]
    print(f"=== IMO {imo}  (Wikidata: {url}) ===")
    for r in wd:
        # show the primary-source value for the same field, if any, for comparison
        prim = conn.execute(
            "SELECT value, source_id FROM facts WHERE imo=? AND field=? "
            "AND source_id!='wikidata' ORDER BY retrieved_at DESC LIMIT 1", (imo, r["field"])).fetchone()
        cmp = f"   [primary {prim['source_id']}={prim['value']}]" if prim else "   [no primary value]"
        print(f"  {r['field']:24s} = {str(r['value'])[:30]:30s}{cmp}")
    print()
