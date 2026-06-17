"""
test_port_calls.py — proves M4 port-call inference: a slow vessel inside a
terminal zone is detected with the right tier and its evidence points to the
exact positions; a transiting (fast) vessel and a vessel elsewhere are not.

Run:  py tests/test_port_calls.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from provenance import utc_now_iso
from inference import port_calls

# Primorsk centre (R8a) from config; Ust-Luga is also R8a.
PRIMORSK = (60.334642, 28.716569)


def fresh():
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db.upsert_source(conn, "aisstream", "aisstream.io", "ais",
                     url="https://aisstream.io", accessed_at=utc_now_iso())
    return conn


def add_pos(conn, imo, lat, lon, sog, ts):
    conn.execute(
        "INSERT INTO positions (imo, mmsi, lat, lon, sog, cog, nav_status, timestamp, "
        "source_id, confidence) VALUES (?, '1', ?, ?, ?, 0, '5', ?, 'aisstream', 'normal')",
        (imo, lat, lon, sog, ts))


def test_berthed_vessel_detected_with_tier_and_evidence():
    conn = fresh()
    # 5 slow pings right at Primorsk over 20 minutes.
    times = ["2026-06-17T10:00:00+00:00", "2026-06-17T10:05:00+00:00",
             "2026-06-17T10:10:00+00:00", "2026-06-17T10:15:00+00:00",
             "2026-06-17T10:20:00+00:00"]
    for t in times:
        add_pos(conn, "9000001", PRIMORSK[0], PRIMORSK[1], 0.1, t)
    conn.commit()
    stats = port_calls.detect(conn)
    assert stats["calls"] == 1, stats
    row = conn.execute("SELECT * FROM port_calls WHERE imo='9000001'").fetchone()
    assert row["port"] == "Primorsk" and row["tier"] == "R8a", dict(row)
    ev = json.loads(row["evidence"])
    assert len(ev) == 5, ev
    pos_ids = {r["position_id"] for r in conn.execute("SELECT position_id FROM positions WHERE imo='9000001'")}
    assert set(ev) == pos_ids, "evidence must point to the exact positions used"
    print("PASS: berthed vessel -> Primorsk call (tier R8a), evidence = the 5 positions")


def test_transiting_vessel_not_detected():
    conn = fresh()
    for t in ["2026-06-17T10:00:00+00:00", "2026-06-17T10:05:00+00:00", "2026-06-17T10:10:00+00:00"]:
        add_pos(conn, "9000002", PRIMORSK[0], PRIMORSK[1], 12.0, t)   # fast = transiting
    conn.commit()
    port_calls.detect(conn)
    assert conn.execute("SELECT COUNT(*) c FROM port_calls WHERE imo='9000002'").fetchone()["c"] == 0
    print("PASS: fast-transiting vessel in the zone is NOT a port call")


def test_slow_vessel_elsewhere_not_detected():
    conn = fresh()
    for t in ["2026-06-17T10:00:00+00:00", "2026-06-17T10:05:00+00:00", "2026-06-17T10:10:00+00:00"]:
        add_pos(conn, "9000003", 55.0, 18.0, 0.1, t)                  # middle of the Baltic
    conn.commit()
    port_calls.detect(conn)
    assert conn.execute("SELECT COUNT(*) c FROM port_calls WHERE imo='9000003'").fetchone()["c"] == 0
    print("PASS: slow vessel far from any terminal is NOT a port call")


if __name__ == "__main__":
    test_berthed_vessel_detected_with_tier_and_evidence()
    test_transiting_vessel_not_detected()
    test_slow_vessel_elsewhere_not_detected()
    print("\nAll port_calls tests passed.")
