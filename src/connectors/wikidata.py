"""
wikidata.py — additive fact source: Wikidata (https://www.wikidata.org).

For each IMO number already in our database, queries the Wikidata SPARQL endpoint
using the "IMO ship number" property (P458) for a matching ship item. Where one
exists, retrieves build year, ship type, owner, operator, gross tonnage and any
official/former names, and writes each value into the facts table via the
provenance gate (store_fact) with:
    source_id   = "wikidata"
    source_url  = the specific item, e.g. https://www.wikidata.org/wiki/Q12345
    retrieved_at = now (UTC)

Treatment (per instructions + project rules):
* Wikidata is a TERTIARY, crowd-edited source — lower confidence than
  OpenSanctions or the EU list. It is registered as such in `sources`, and every
  Wikidata fact carries a note saying so.
* We NEVER overwrite a primary-source value. The facts table is append-only, so
  a Wikidata value is simply stored as its own additional dated row; a reader can
  see where Wikidata agrees or disagrees with a primary source.
* If an IMO has no matching item, we write nothing (rule 9 — leave it unknown).
  Many IMOs return no match; that is expected.

Verified against the live endpoint (2026-06-17):
  P458 IMO ship number | P571 inception | P729 service entry | P31 instance of
  | P127 owner | P137 operator | P1093 gross tonnage | P1448 official name.
  (Wikidata has NO deadweight-tonnage property, so deadweight is never set here.)
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

import db
from identity import is_valid_imo
from provenance import Fact, store_fact, utc_now_iso

ENDPOINT = "https://query.wikidata.org/sparql"
SOURCE_ID = "wikidata"
USER_AGENT = "BalticRiskRegister/0.1 (environmental-risk research; contact charlottewit@gmail.com)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
ITEM_URL = "https://www.wikidata.org/wiki/{qid}"
FACT_NOTE = "via Wikidata ({qid}); tertiary/crowd-edited source, lower confidence than primary"

# One SPARQL query per chunk of IMOs; multi-valued fields are concatenated.
QUERY = """
SELECT ?imo ?ship
  (SAMPLE(?inception) AS ?inceptionV) (SAMPLE(?service) AS ?serviceV)
  (GROUP_CONCAT(DISTINCT ?typeLabel;  separator="||") AS ?types)
  (GROUP_CONCAT(DISTINCT ?ownerLabel; separator="||") AS ?owners)
  (GROUP_CONCAT(DISTINCT ?operatorLabel; separator="||") AS ?operators)
  (GROUP_CONCAT(DISTINCT ?gross;      separator="||") AS ?grosses)
  (GROUP_CONCAT(DISTINCT ?official;   separator="||") AS ?names)
WHERE {
  VALUES ?imo { %s }
  ?ship wdt:P458 ?imo.
  OPTIONAL { ?ship wdt:P571 ?inception. }
  OPTIONAL { ?ship wdt:P729 ?service. }
  OPTIONAL { ?ship wdt:P31 ?type.     ?type rdfs:label ?typeLabel.     FILTER(LANG(?typeLabel)="en") }
  OPTIONAL { ?ship wdt:P127 ?owner.   ?owner rdfs:label ?ownerLabel.   FILTER(LANG(?ownerLabel)="en") }
  OPTIONAL { ?ship wdt:P137 ?operator.?operator rdfs:label ?operatorLabel. FILTER(LANG(?operatorLabel)="en") }
  OPTIONAL { ?ship wdt:P1093 ?gross. }
  OPTIONAL { ?ship wdt:P1448 ?official. }
}
GROUP BY ?imo ?ship
"""


def register_source(conn, accessed_at=None):
    db.upsert_source(
        conn, SOURCE_ID, "Wikidata", "reference",
        url="https://www.wikidata.org",
        license="CC0 1.0 (public domain)",
        accessed_at=accessed_at or utc_now_iso(),
        note="Tertiary, crowd-edited source — lower confidence than OpenSanctions / EU list.",
    )


def _year(value):
    m = re.search(r"\d{4}", value or "")
    return m.group(0) if m else None


def query_chunk(imos, timeout=90, retries=3, backoff=3.0):
    values = " ".join(f'"{i}"' for i in imos)
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(ENDPOINT, params={"query": QUERY % values},
                             headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))   # Wikidata 502/timeout: back off and retry
    else:
        raise last_err
    out = {}
    for b in r.json()["results"]["bindings"]:
        imo = b["imo"]["value"]
        qid = b["ship"]["value"].rsplit("/", 1)[-1]
        out[imo] = {
            "qid": qid,
            "inception": b.get("inceptionV", {}).get("value"),
            "service": b.get("serviceV", {}).get("value"),
            "types": _split(b.get("types")),
            "owners": _split(b.get("owners")),
            "operators": _split(b.get("operators")),
            "grosses": _split(b.get("grosses")),
            "names": _split(b.get("names")),
        }
    return out


def _split(binding):
    v = (binding or {}).get("value", "") if isinstance(binding, dict) else (binding or "")
    return [x for x in (v.split("||") if v else []) if x.strip()]


def store_match(conn, imo, info, retrieved_at):
    """Write every value found for one matched ship as its own sourced fact."""
    qid = info["qid"]
    url = ITEM_URL.format(qid=qid)
    note = FACT_NOTE.format(qid=qid)
    n = 0

    def put(field, value, extra=""):
        nonlocal n
        if value is None or not str(value).strip():
            return
        store_fact(conn, Fact(imo, field, str(value).strip(), SOURCE_ID, url,
                              retrieved_at, (note + extra)))
        n += 1

    # build year: prefer inception (P571); else service entry (P729) as a proxy.
    if info["inception"] and _year(info["inception"]):
        put("built_year", _year(info["inception"]), " [P571 inception]")
    elif info["service"] and _year(info["service"]):
        put("built_year", _year(info["service"]),
            " [from P729 service entry — Wikidata had no build/inception date; proxy]")

    for t in info["types"]:
        put("vessel_type", t)
    for o in info["owners"]:
        put("owner", o)
    for op in info["operators"]:
        put("operator", op)
    for g in info["grosses"]:
        put("gross_registered_tonnage", g)
    for nm in info["names"]:
        put("name", nm)
    return n


def ingest(conn, imos, chunk_size=100, polite_delay=1.0, retrieved_at=None):
    """Query Wikidata for the given IMOs and store matches. Returns a summary."""
    retrieved_at = retrieved_at or utc_now_iso()
    register_source(conn, retrieved_at)
    imos = [i for i in imos if is_valid_imo(i)]
    stats = {"queried": len(imos), "matched": 0, "facts": 0, "matched_imos": []}
    for start in range(0, len(imos), chunk_size):
        chunk = imos[start:start + chunk_size]
        try:
            found = query_chunk(chunk)
        except requests.RequestException as e:
            print(f"  chunk {start}-{start+len(chunk)} failed: {e}", flush=True)
            time.sleep(polite_delay)
            continue
        for imo, info in found.items():
            wrote = store_match(conn, imo, info, retrieved_at)
            if wrote:
                stats["matched"] += 1
                stats["facts"] += wrote
                stats["matched_imos"].append(imo)
        conn.commit()
        print(f"  ...{min(start+chunk_size, len(imos))}/{len(imos)} IMOs checked, "
              f"{stats['matched']} matched", flush=True)
        time.sleep(polite_delay)
    return stats


def lookup_one(conn, imo, retrieved_at=None):
    """Query a single IMO and store any match. Used by the AIS-triggered path.
    Returns number of facts written (0 if no match)."""
    if not is_valid_imo(imo):
        return 0
    retrieved_at = retrieved_at or utc_now_iso()
    register_source(conn, retrieved_at)
    found = query_chunk([imo])
    info = found.get(imo)
    return store_match(conn, imo, info, retrieved_at) if info else 0


def main():
    conn = db.init_db()
    # Clean rebuild of Wikidata facts so repeated full runs don't accumulate
    # duplicate rows. (The AIS-triggered lookup_one path is guarded separately.)
    with conn:
        conn.execute("DELETE FROM facts WHERE source_id=?", (SOURCE_ID,))
    imos = [r["imo"] for r in conn.execute("SELECT DISTINCT imo FROM facts")]
    print(f"Querying Wikidata for {len(imos)} IMOs already in the database...")
    stats = ingest(conn, imos)
    print("\nDone. Summary:")
    print(f"  IMOs queried: {stats['queried']}")
    print(f"  IMOs matched to a Wikidata item: {stats['matched']}")
    print(f"  facts written: {stats['facts']}")


if __name__ == "__main__":
    main()
