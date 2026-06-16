"""
opensanctions.py — pulls sanctioned/maritime VESSEL entities from the live
OpenSanctions API and writes every value into the facts table WITH provenance.

How this honours the project rules:
* Every fact is stored via provenance.store_fact, so it cannot exist without a
  source_id, a real source_url (the public OpenSanctions entity page, which you
  can open in a browser), and a UTC retrieved_at timestamp.
* We invent nothing. If a vessel has no usable IMO number we skip it (and count
  it) rather than guessing one. Multiple/odd IMO numbers are flagged, not merged
  silently (the "zombie IMO" problem).
* OpenSanctions aggregates many underlying lists. We record WHICH datasets named
  each vessel in list_membership, and note them on every fact, so the chain of
  custody (value -> OpenSanctions -> original list) stays visible.

API shape (verified live against the running API on 2026-06-16):
  GET https://api.opensanctions.org/search/sanctions?schema=Vessel&limit=&offset=
  Header: Authorization: ApiKey <key>
  -> { total:{value}, results:[ {id, properties:{field:[values]}, datasets:[...]} ] }
  Public entity page (used as source_url): https://www.opensanctions.org/entities/<id>/
"""

import os
import re
import sys
import time
from pathlib import Path

# Make src/ importable whether run as a module or directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dotenv import load_dotenv

import db
from provenance import Fact, store_fact, utc_now_iso

BASE = "https://api.opensanctions.org"
SCOPE = "sanctions"          # the OpenSanctions collection of sanctioned entities
SOURCE_ID = "opensanctions"
ENTITY_URL = "https://www.opensanctions.org/entities/{id}/"

# OpenSanctions Vessel property -> our facts.field name.
FIELD_MAP = {
    "name": "name",
    "previousName": "previous_name",
    "flag": "flag",
    "pastFlags": "past_flag",
    "buildDate": "built_year",            # normalised to a 4-digit year
    "type": "vessel_type",
    "tonnage": "tonnage",
    "grossRegisteredTonnage": "gross_registered_tonnage",
    "deadweightTonnage": "deadweight_tonnage",
    "mmsi": "mmsi",
    "country": "country",
    "callSign": "call_sign",
}

# Map well-known OpenSanctions dataset ids to friendly list names for
# list_membership. Anything not in this map is recorded under its raw id so
# nothing is lost; M2 refines KSE/GUR specifically.
DATASET_TO_LIST = {
    "eu_journal_sanctions": "EU",
    "eu_sanctions_map": "EU",
    "eu_fsf": "EU",
    "us_ofac_sdn": "OFAC",
    "us_ofac_cons": "OFAC",
    "gb_fcdo_sanctions": "UK",
    "gb_hmt_sanctions": "UK",
    "ua_war_sanctions": "UA_war_sanctions",
    "ua_nsdc_sanctions": "UA_NSDC",
}


def normalize_imo(raw):
    """Return a clean 7-digit IMO string, or None if it is not a valid IMO."""
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 7 else None


def year_of(build_date):
    """Extract a 4-digit year from values like '2007' or '2004-12-15'."""
    m = re.search(r"\d{4}", build_date or "")
    return m.group(0) if m else None


def fetch_vessels(api_key, page_size=100, polite_delay=0.3, max_pages=100):
    """Page through every Vessel entity in the sanctions collection.

    Returns (entities, reported_total). Raises requests.HTTPError on a bad
    response so failures are loud, never silently partial.
    """
    headers = {"Authorization": f"ApiKey {api_key}"}
    entities, offset, reported_total = [], 0, None
    for _ in range(max_pages):
        params = {"schema": "Vessel", "limit": page_size, "offset": offset}
        r = requests.get(f"{BASE}/search/{SCOPE}", params=params,
                         headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        reported_total = data.get("total", {}).get("value")
        results = data.get("results", [])
        entities.extend(results)
        offset += page_size
        if not results or (reported_total is not None and offset >= reported_total):
            break
        time.sleep(polite_delay)
    return entities, reported_total


def ingest(conn, api_key, retrieved_at=None):
    """Fetch vessels and store every value as a sourced fact. Returns a summary."""
    retrieved_at = retrieved_at or utc_now_iso()

    db.upsert_source(
        conn, SOURCE_ID, "OpenSanctions", "sanctions",
        url="https://www.opensanctions.org",
        license="CC-BY-NC 4.0 (free for non-commercial use)",
        accessed_at=retrieved_at,
    )

    entities, reported_total = fetch_vessels(api_key)

    stats = {"entities": len(entities), "reported_total": reported_total,
             "facts": 0, "vessels_with_imo": 0, "skipped_no_imo": 0,
             "multi_imo": 0, "list_rows": 0}

    for e in entities:
        eid = e.get("id")
        props = e.get("properties", {})
        datasets = e.get("datasets", []) or []
        entity_url = ENTITY_URL.format(id=eid)
        note = "via OpenSanctions; datasets: " + ",".join(datasets) if datasets else "via OpenSanctions"

        # --- Identify the vessel by IMO (no IMO -> we cannot key it; skip & count) ---
        raw_imos = props.get("imoNumber", []) or []
        valid_imos = sorted({normalize_imo(x) for x in raw_imos} - {None})
        if not valid_imos:
            stats["skipped_no_imo"] += 1
            continue
        imo = valid_imos[0]
        stats["vessels_with_imo"] += 1
        if len(valid_imos) > 1:
            stats["multi_imo"] += 1
            note += f" | NOTE: multiple IMO numbers reported {valid_imos} (possible identity anomaly)"

        # Record each reported IMO number as a fact (so anomalies are visible).
        for one in valid_imos:
            store_fact(conn, Fact(imo, "imo_number", one, SOURCE_ID, entity_url, retrieved_at, note))
            stats["facts"] += 1

        # --- Store every mapped property value as its own sourced fact ---
        for prop, field in FIELD_MAP.items():
            values = props.get(prop, []) or []
            seen = set()
            for v in values:
                out = year_of(v) if field == "built_year" else v
                if out is None or out in seen:
                    continue
                seen.add(out)
                store_fact(conn, Fact(imo, field, out, SOURCE_ID, entity_url, retrieved_at, note))
                stats["facts"] += 1

        # --- Record list membership from the datasets that named this vessel ---
        for ds in datasets:
            list_name = DATASET_TO_LIST.get(ds, ds)  # friendly name or raw id
            conn.execute(
                """INSERT INTO list_membership (imo, list_name, present, as_of, source_url)
                   VALUES (?, ?, 1, ?, ?)""",
                (imo, list_name, retrieved_at, entity_url),
            )
            stats["list_rows"] += 1
        conn.commit()

    return stats


def main():
    load_dotenv()
    key = (os.getenv("OPENSANCTIONS_API_KEY") or "").strip()
    if not key:
        sys.exit("No OPENSANCTIONS_API_KEY found in .env — add it and retry.")
    conn = db.init_db()
    print("Fetching sanctioned vessels from OpenSanctions (this takes ~30s)...")
    stats = ingest(conn, key)
    print("\nDone. Summary:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
