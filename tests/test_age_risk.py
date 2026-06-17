"""
test_age_risk.py — proves rule R1 (age > 20) fires correctly, is idempotent, and
its evidence points to the built_year fact used. No network (flag_r1 only).

Run:  py tests/test_age_risk.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
import age_risk
from provenance import Fact, store_fact, utc_now_iso

THIS_YEAR = datetime.now(timezone.utc).year


def fresh():
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db.upsert_source(conn, "opensanctions", "OpenSanctions", "sanctions",
                     url="https://www.opensanctions.org", accessed_at=utc_now_iso())
    db.upsert_source(conn, "wikidata", "Wikidata", "reference",
                     url="https://www.wikidata.org", accessed_at=utc_now_iso())
    return conn


def add_built_year(conn, imo, year, source_id, url):
    store_fact(conn, Fact(imo, "built_year", str(year), source_id, url, utc_now_iso()))


def test_old_vessel_is_flagged_and_idempotent():
    conn = fresh()
    old = str(THIS_YEAR - 26)
    add_built_year(conn, "9000001", old, "opensanctions",
                   "https://www.opensanctions.org/entities/x/")
    flagged, info = age_risk.flag_r1(conn, "9000001")
    assert flagged and info["age"] == 26
    n1 = conn.execute("SELECT COUNT(*) c FROM risk_flags WHERE imo='9000001'").fetchone()["c"]
    age_risk.flag_r1(conn, "9000001")            # run again
    n2 = conn.execute("SELECT COUNT(*) c FROM risk_flags WHERE imo='9000001'").fetchone()["c"]
    assert n1 == 1 and n2 == 1, "R1 should flag once, not duplicate"
    print("PASS: vessel >20y flagged R1 exactly once (idempotent)")


def test_young_vessel_not_flagged():
    conn = fresh()
    add_built_year(conn, "9000002", str(THIS_YEAR - 5), "opensanctions", "https://x/")
    flagged, info = age_risk.flag_r1(conn, "9000002")
    assert not flagged and info["age"] == 5
    assert conn.execute("SELECT COUNT(*) c FROM risk_flags").fetchone()["c"] == 0
    print("PASS: vessel <=20y is not flagged")


def test_evidence_points_to_fact_and_prefers_primary():
    conn = fresh()
    old = str(THIS_YEAR - 30)
    add_built_year(conn, "9000003", old, "wikidata", "https://www.wikidata.org/wiki/Q1")
    add_built_year(conn, "9000003", old, "opensanctions", "https://os/x/")
    age_risk.flag_r1(conn, "9000003")
    ev = json.loads(conn.execute("SELECT evidence FROM risk_flags WHERE imo='9000003'").fetchone()["evidence"])
    assert ev["built_year_source"] == "opensanctions", "should prefer primary source for the flag"
    assert ev["built_year_fact_id"], "evidence must reference the built_year fact"
    print("PASS: R1 evidence points to the built_year fact and prefers the primary source")


if __name__ == "__main__":
    test_old_vessel_is_flagged_and_idempotent()
    test_young_vessel_not_flagged()
    test_evidence_points_to_fact_and_prefers_primary()
    print("\nAll age_risk tests passed.")
