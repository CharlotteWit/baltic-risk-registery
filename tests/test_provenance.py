"""
test_provenance.py — proves the two non-negotiable rules are enforced by code:
  * a fact WITHOUT a source is refused (rule #1),
  * a fact WITH full provenance is stored and round-trips correctly.

Run from the project root with:   python -m pytest tests/ -v
(or simply:                        python tests/test_provenance.py )
"""

import sys
from pathlib import Path

# Allow importing from src/ when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db
import provenance
from provenance import Fact, ProvenanceError, store_fact, store_unknown, utc_now_iso


def fresh_db():
    """An in-memory database with the schema and one registered source."""
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db.upsert_source(conn, "test_src", "Test Source", "sanctions",
                     url="https://example.org", license="test", accessed_at=utc_now_iso())
    return conn


def test_fact_without_source_is_refused():
    conn = fresh_db()
    bad = Fact(imo="9999999", field="flag", value="Panama",
               source_id="", source_url="", retrieved_at=utc_now_iso())
    try:
        store_fact(conn, bad)
    except ProvenanceError:
        print("PASS: sourceless fact was refused")
        return
    raise AssertionError("FAIL: a fact without a source was stored — rule #1 broken")


def test_fact_without_timestamp_is_refused():
    conn = fresh_db()
    bad = Fact(imo="9999999", field="flag", value="Panama",
               source_id="test_src", source_url="https://example.org/x",
               retrieved_at="not-a-timestamp")
    try:
        store_fact(conn, bad)
    except ProvenanceError:
        print("PASS: fact with invalid timestamp was refused")
        return
    raise AssertionError("FAIL: a fact with a bad timestamp was stored")


def test_well_sourced_fact_round_trips():
    conn = fresh_db()
    ts = utc_now_iso()
    good = Fact(imo="9263727", field="built_year", value="2004",
                source_id="test_src", source_url="https://example.org/vessel/9263727",
                retrieved_at=ts, note="example")
    fid = store_fact(conn, good)
    assert fid is not None
    row = conn.execute("SELECT * FROM facts WHERE fact_id=?", (fid,)).fetchone()
    assert row["imo"] == "9263727"
    assert row["value"] == "2004"
    assert row["source_url"].startswith("https://")
    assert row["retrieved_at"] == ts
    print("PASS: well-sourced fact stored and retrieved with its provenance intact")


def test_unknown_still_requires_a_source():
    conn = fresh_db()
    # The honest 'unknown' path still needs a real source we actually checked.
    fid = store_unknown(conn, "9263727", "insurer",
                        source_id="test_src", source_url="https://example.org/vessel/9263727")
    row = conn.execute("SELECT * FROM facts WHERE fact_id=?", (fid,)).fetchone()
    assert row["value"] is None and row["note"] == "unknown"
    print("PASS: 'unknown' was recorded WITH a source, not guessed")


if __name__ == "__main__":
    test_fact_without_source_is_refused()
    test_fact_without_timestamp_is_refused()
    test_well_sourced_fact_round_trips()
    test_unknown_still_requires_a_source()
    print("\nAll provenance tests passed.")
