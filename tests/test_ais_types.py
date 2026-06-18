"""
test_ais_types.py — locks in the AIS ship-type -> category mapping and the
keep/drop decision agreed with the user.

Run:  py tests/test_ais_types.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from ais_types import category_for_type, should_store


def test_categories():
    assert category_for_type(80) == "tanker"
    assert category_for_type(89) == "tanker"
    assert category_for_type(70) == "cargo"
    assert category_for_type(0) == "unknown"
    assert category_for_type(None) == "unknown"
    assert category_for_type(95) == "other"
    assert category_for_type(45) == "hsc"
    assert category_for_type(35) == "military"
    assert category_for_type(59) == "military"
    assert category_for_type(55) == "law_enforcement"
    assert category_for_type(51) == "sar"
    assert category_for_type(60) == "passenger"
    assert category_for_type(30) == "fishing"
    assert category_for_type(31) == "tug"
    print("PASS: ship-type codes map to the expected categories")


def test_keep_drop_decision():
    # Kept: tankers, cargo, unknown/other, military, law enforcement, SAR.
    for cat in ("tanker", "cargo", "unknown", "other",
                "military", "law_enforcement", "sar"):
        assert should_store(cat), f"{cat} should be KEPT"
    # Dropped: passenger, sailing, pleasure, fishing, tug, service, hsc.
    for cat in ("passenger", "sailing", "pleasure", "fishing", "tug", "service", "hsc"):
        assert not should_store(cat), f"{cat} should be DROPPED"
    print("PASS: keep/drop matches the agreed selection (SAR/military kept, HSC dropped)")


if __name__ == "__main__":
    test_categories()
    test_keep_drop_decision()
    print("\nAll ais_types tests passed.")
