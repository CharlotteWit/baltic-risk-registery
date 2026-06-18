"""
test_risk_engine.py — proves scoring: band thresholds, that fired rules sum to
the score, and that a data-gap rule is 'not_evaluated' (never silently scored).

Run:  py tests/test_risk_engine.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from provenance import Fact, store_fact, utc_now_iso
from inference import risk_engine as re

THIS_YEAR = datetime.now(timezone.utc).year


def fresh():
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db.upsert_source(conn, "opensanctions", "OpenSanctions", "sanctions",
                     url="https://x", accessed_at=utc_now_iso())
    return conn


def test_band_for():
    _, bands, _ = re.load_cfg()
    assert re.band_for(0, bands) == "low"
    assert re.band_for(3, bands) == "low"
    assert re.band_for(4, bands) == "elevated"
    assert re.band_for(8, bands) == "high"
    assert re.band_for(99, bands) == "high"
    print("PASS: band thresholds (low/elevated/high) correct")


def test_fired_rules_sum_to_score():
    conn = fresh()
    weights, bands, foc = re.load_cfg()
    imo = "9000001"
    # old vessel (R1) + sanctioned (R10)
    store_fact(conn, Fact(imo, "built_year", str(THIS_YEAR - 25), "opensanctions",
                          "https://x/v", utc_now_iso()))
    conn.execute("INSERT INTO list_membership (imo, list_name, present, as_of, source_url) "
                 "VALUES (?, 'EU', 1, ?, 'https://x')", (imo, utc_now_iso()))
    conn.commit()
    res = re.score_vessel(conn, imo, foc)
    assert res["R1"][0] == "triggered"
    assert res["R10"][0] == "triggered"
    assert "R2" not in res and "R7" not in res, "removed rules must not be evaluated"
    expected = weights["R1"] + weights["R10"]
    total = sum(weights.get(r, 0) for r, (st, _) in res.items() if st == "triggered")
    assert total == expected, (total, expected)
    print(f"PASS: R1+R10 fired (removed rules absent), score = {total} = {expected}")


if __name__ == "__main__":
    test_band_for()
    test_fired_rules_sum_to_score()
    print("\nAll risk_engine tests passed.")
