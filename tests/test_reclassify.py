"""
test_reclassify.py — proves the single sanctioned overwrite: a position stored as
'unknown' is corrected to the real type once learned this session; an already-known
type is never overwritten; a late-learned excluded type drops the rows.

Run:  py tests/test_reclassify.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from provenance import utc_now_iso
from connectors.ais_stream import reclassify_pending


def fresh():
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db.upsert_source(conn, "aisstream", "aisstream.io", "ais",
                     url="https://aisstream.io", accessed_at=utc_now_iso())
    return conn


def add(conn, mmsi, category, code=None):
    cur = conn.execute(
        "INSERT INTO positions (mmsi, lat, lon, sog, cog, nav_status, timestamp, "
        "source_id, confidence, ais_ship_type, type_category) "
        "VALUES (?, 60.0, 26.0, 0.0, 0, '0', '2026-06-18T10:00:00+00:00', 'aisstream', "
        "'normal', ?, ?)", (mmsi, code, category))
    return cur.lastrowid


def test_unknown_upgraded_to_known():
    conn = fresh()
    p1 = add(conn, "111", "unknown")
    p2 = add(conn, "111", "unknown")
    rec, drp = reclassify_pending(conn, [p1, p2], "tanker", 80)
    assert (rec, drp) == (2, 0)
    rows = conn.execute("SELECT type_category, ais_ship_type FROM positions WHERE mmsi='111'").fetchall()
    assert all(r["type_category"] == "tanker" and r["ais_ship_type"] == 80 for r in rows)
    print("PASS: 'unknown' positions upgraded to the learned type (tanker)")


def test_known_value_never_overwritten():
    conn = fresh()
    pc = add(conn, "222", "cargo", 70)            # already a real type
    rec, drp = reclassify_pending(conn, [pc], "tanker", 80)
    assert (rec, drp) == (0, 0)                    # guarded by WHERE type_category='unknown'
    row = conn.execute("SELECT type_category FROM positions WHERE position_id=?", (pc,)).fetchone()
    assert row["type_category"] == "cargo", "a known value must NOT be overwritten"
    print("PASS: an already-known type is never overwritten")


def test_late_excluded_type_drops_rows():
    conn = fresh()
    p = add(conn, "333", "unknown")
    rec, drp = reclassify_pending(conn, [p], "passenger", 60)   # excluded category
    assert (rec, drp) == (0, 1)
    assert conn.execute("SELECT COUNT(*) c FROM positions WHERE mmsi='333'").fetchone()["c"] == 0
    print("PASS: late-learned excluded type drops the earlier 'unknown' rows")


def test_unknown_code_is_noop():
    conn = fresh()
    p = add(conn, "444", "unknown")
    assert reclassify_pending(conn, [p], "unknown", 0) == (0, 0)
    print("PASS: learning 'unknown' again is a no-op")


if __name__ == "__main__":
    test_unknown_upgraded_to_known()
    test_known_value_never_overwritten()
    test_late_excluded_type_drops_rows()
    test_unknown_code_is_noop()
    print("\nAll reclassify tests passed.")
