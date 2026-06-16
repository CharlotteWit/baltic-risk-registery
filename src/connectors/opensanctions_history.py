"""
opensanctions_history.py — populates identity_history with DATED observations of
each vessel's IMO number, flag, and name, taken from the OpenSanctions
/statements API. The dates (first_seen/last_seen) are the source's own and are
stored verbatim — nothing here is generated or estimated.

This is what lets us answer "did this vessel's IMO/flag/name change in the last
3 months?" with evidence: a value whose earliest first_seen falls inside the
window is a newly-observed value for that field.

Per-entity statement queries are used because the bulk (collection-wide) query
times out on the server. ~1,900 small requests with a polite delay.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dotenv import load_dotenv

import db
from provenance import store_identity_observation, utc_now_iso
from connectors.opensanctions import (
    BASE, SOURCE_ID, ENTITY_URL, fetch_vessels, normalize_imo,
)

# OpenSanctions statement prop -> our identity_history.field
IDENTITY_PROPS = {"imoNumber": "imo_number", "flag": "flag", "name": "name"}


def fetch_statements(api_key, canonical_id, page_size=500, timeout=60):
    """Return all statements for one entity (paged if needed)."""
    headers = {"Authorization": f"ApiKey {api_key}"}
    out, offset = [], 0
    while True:
        params = {"canonical_id": canonical_id, "limit": page_size, "offset": offset}
        r = requests.get(f"{BASE}/statements", params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        out.extend(results)
        total = (data.get("total") or {}).get("value", 0)
        offset += page_size
        if not results or offset >= total:
            break
    return out


def ingest_history(conn, api_key, polite_delay=0.15, progress_every=200):
    retrieved_at = utc_now_iso()
    entities, _ = fetch_vessels(api_key)          # reuse the verified vessel fetch
    stats = {"entities": len(entities), "observations": 0, "vessels": 0, "errors": 0}

    for i, e in enumerate(entities, 1):
        eid = e.get("id")
        props = e.get("properties", {})
        valid_imos = sorted({normalize_imo(x) for x in (props.get("imoNumber") or [])} - {None})
        if not valid_imos:
            continue                               # no key -> consistent with facts ingest
        imo = valid_imos[0]
        entity_url = ENTITY_URL.format(id=eid)

        try:
            statements = fetch_statements(api_key, eid)
        except requests.RequestException:
            stats["errors"] += 1
            time.sleep(polite_delay)
            continue

        stored_for_vessel = 0
        for st in statements:
            field = IDENTITY_PROPS.get(st.get("prop"))
            if not field:
                continue
            raw = st.get("value")
            if field == "imo_number":
                value = normalize_imo(raw) or raw   # keep anomalies visible, don't drop
            else:
                value = raw
            if value is None or not str(value).strip():
                continue
            store_identity_observation(
                conn, imo=imo, field=field, value=value,
                source_id=SOURCE_ID, source_url=entity_url,
                origin_dataset=st.get("dataset"),
                first_seen=st.get("first_seen"), last_seen=st.get("last_seen"),
                retrieved_at=retrieved_at,
            )
            stored_for_vessel += 1

        if stored_for_vessel:
            stats["vessels"] += 1
            stats["observations"] += stored_for_vessel
        if i % progress_every == 0:
            print(f"  ...processed {i}/{len(entities)} vessels "
                  f"({stats['observations']} observations so far)", flush=True)
        time.sleep(polite_delay)

    return stats


def main():
    load_dotenv()
    key = (os.getenv("OPENSANCTIONS_API_KEY") or "").strip()
    if not key:
        sys.exit("No OPENSANCTIONS_API_KEY found in .env — add it and retry.")
    conn = db.init_db()
    print("Fetching dated identity history (IMO/flag/name) from OpenSanctions statements...")
    print("This makes ~1,900 small requests with a polite delay (~6-8 min).")
    stats = ingest_history(conn, key)
    print("\nDone. Summary:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
