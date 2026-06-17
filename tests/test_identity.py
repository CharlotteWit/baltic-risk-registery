"""
test_identity.py — proves that identity change detection ignores cosmetic
case/spacing differences but still catches genuine renames/reflaggings.

Run:  py tests/test_identity.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from identity import (normalize_identity_value, group_identity_history,
                      recent_changes, current_value, display_name, is_valid_imo)

CUTOFF = "2026-03-18T00:00:00+00:00"


def test_normalize_ignores_case_and_spacing():
    assert normalize_identity_value("name", "NS Silver") == normalize_identity_value("name", "ns  silver ")
    assert normalize_identity_value("name", "SILVER") == normalize_identity_value("name", "Silver")
    assert normalize_identity_value("imo_number", "IMO9332810") == "9332810"
    assert normalize_identity_value("flag", " RU ") == "ru"
    print("PASS: case/spacing/format normalised consistently")


def test_casing_variant_is_not_a_change():
    # 'Silver' seen in Feb, 'SILVER' seen in June -> SAME name, no recent change.
    rows = [
        {"value": "Silver", "origin_dataset": "ca", "first_seen": "2026-02-24T00:00:00"},
        {"value": "SILVER", "origin_dataset": "ua", "first_seen": "2026-06-09T00:00:00"},
    ]
    groups = group_identity_history(rows, "name")
    assert len(groups) == 1, f"expected 1 group, got {len(groups)}"
    assert recent_changes(groups, CUTOFF) == [], "a pure casing variant was wrongly flagged as a change"
    print("PASS: 'Silver' vs 'SILVER' is one value, not a recent change")


def test_genuine_rename_is_a_change():
    rows = [
        {"value": "GRINCH", "origin_dataset": "gb", "first_seen": "2025-07-21T00:00:00"},
        {"value": "TRANSFORMER", "origin_dataset": "ua", "first_seen": "2026-06-15T00:00:00"},
    ]
    groups = group_identity_history(rows, "name")
    assert len(groups) == 2
    changes = recent_changes(groups, CUTOFF)
    assert [g["variants"] for g in changes] == [["TRANSFORMER"]], changes
    print("PASS: genuine rename to 'TRANSFORMER' is detected as a recent change")


def test_single_value_is_never_a_change():
    rows = [{"value": "9248801", "origin_dataset": "eu", "first_seen": "2026-05-01T00:00:00"}]
    groups = group_identity_history(rows, "imo_number")
    assert recent_changes(groups, CUTOFF) == [], "a lone IMO should not count as a change"
    print("PASS: a single IMO value is not reported as a change")


def test_current_value_is_latest_known():
    # Ship 2 shape: SOKOLO appeared after Oman Pride / Lydya N -> SOKOLO is current.
    rows = [
        {"value": "OMAN PRIDE", "origin_dataset": "ofac", "first_seen": "2025-03-13T00:00:00", "last_seen": "2026-06-16T00:00:00"},
        {"value": "LYDYA N", "origin_dataset": "csl", "first_seen": "2025-03-13T00:00:00", "last_seen": "2026-06-16T00:00:00"},
        {"value": "SOKOLO", "origin_dataset": "ua", "first_seen": "2026-06-09T00:00:00", "last_seen": "2026-06-16T00:00:00"},
    ]
    groups = group_identity_history(rows, "name")
    cur = current_value(groups)
    assert cur["variants"] == ["SOKOLO"], cur
    print("PASS: current name = latest known (SOKOLO), not the OpenSanctions caption")


def test_display_name_prefers_mixed_case():
    rows = [{"value": "OMAN PRIDE", "origin_dataset": "a", "first_seen": "2025-01-01T00:00:00"},
            {"value": "Oman Pride", "origin_dataset": "b", "first_seen": "2025-01-01T00:00:00"}]
    g = group_identity_history(rows, "name")[0]
    assert display_name(g) == "Oman Pride", display_name(g)
    print("PASS: display_name prefers the readable mixed-case variant")


def test_imo_check_digit():
    assert is_valid_imo("9332810")        # real IMO (P. FOS)
    assert is_valid_imo("8227238")        # real IMO (Karpinskiy)
    assert is_valid_imo("IMO9332810")     # prefix tolerated
    assert not is_valid_imo("9332811")    # wrong check digit
    assert not is_valid_imo("12345")      # too short
    assert not is_valid_imo("")           # empty
    print("PASS: IMO check-digit validation accepts real IMOs, rejects malformed")


if __name__ == "__main__":
    test_normalize_ignores_case_and_spacing()
    test_casing_variant_is_not_a_change()
    test_genuine_rename_is_a_change()
    test_single_value_is_never_a_change()
    test_current_value_is_latest_known()
    test_display_name_prefers_mixed_case()
    test_imo_check_digit()
    print("\nAll identity tests passed.")
