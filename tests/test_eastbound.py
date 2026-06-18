"""
test_eastbound.py — proves the eastbound-transit inference:
  * destination classification by DIRECTION (west/east/unknown),
  * a west declaration + east exit => contradiction => R8d flag,
  * an unknown/blank declaration + east exit => R8d flag,
  * a consistent eastern declaration => NO flag (it speaks for itself),
  * a vessel NOT exiting east => no event.

Run:  py tests/test_eastbound.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from provenance import Fact, store_fact, utc_now_iso
from inference import eastbound_transit as et


def fresh():
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db.upsert_source(conn, "aisstream", "aisstream.io", "ais",
                     url="https://aisstream.io", accessed_at=utc_now_iso())
    return conn


def add_last_pos(conn, imo, lat, lon, sog, cog, ts="2026-06-18T10:00:00+00:00"):
    conn.execute(
        "INSERT INTO positions (imo, mmsi, lat, lon, sog, cog, nav_status, timestamp, "
        "source_id, confidence) VALUES (?, '1', ?, ?, ?, ?, '0', ?, 'aisstream', 'normal')",
        (imo, lat, lon, sog, cog, ts))


def set_dest(conn, imo, dest):
    store_fact(conn, Fact(imo, "ais_destination", dest, "aisstream",
                          "https://aisstream.io", utc_now_iso(), "self-declared"))


def test_classification():
    assert et.classify_destination("ROTTERDAM")[0] == "west"
    assert et.classify_destination("KALININGRAD")[0] == "west"   # Russian but WEST of us
    assert et.classify_destination("RUULU")[0] == "east"
    assert et.classify_destination("UST-LUGA")[0] == "east"
    assert et.classify_destination("")[0] == "unknown"
    assert et.classify_destination("FOR ORDERS")[0] == "unknown"
    print("PASS: destination classified by direction (Kaliningrad=west, Ust-Luga=east)")


def test_west_declaration_is_contradiction():
    conn = fresh()
    add_last_pos(conn, "9000001", 60.0, 26.7, 10.0, 90)   # at east edge, eastbound, moving
    set_dest(conn, "9000001", "ROTTERDAM")
    conn.commit()
    et.detect(conn)
    row = conn.execute("SELECT evidence FROM risk_flags WHERE imo='9000001' AND rule_id='R8d'").fetchone()
    assert row, "expected an R8d flag"
    ev = json.loads(row["evidence"])
    assert ev["reason"] == "contradiction" and ev["declared_destination"] == "ROTTERDAM"
    print("PASS: declared Rotterdam + exiting east => contradiction => R8d flag")


def test_unknown_declaration_flagged():
    conn = fresh()
    add_last_pos(conn, "9000002", 60.1, 26.6, 9.0, 80)
    conn.commit()                                          # no destination at all
    et.detect(conn)
    ev = json.loads(conn.execute("SELECT evidence FROM risk_flags WHERE imo='9000002'").fetchone()["evidence"])
    assert ev["reason"] == "unknown"
    print("PASS: blank destination + exiting east => R8d flag (reason unknown)")


def test_consistent_eastern_declaration_not_flagged():
    conn = fresh()
    add_last_pos(conn, "9000003", 60.0, 26.7, 10.0, 90)
    set_dest(conn, "9000003", "RUULU")                     # Ust-Luga, east — consistent
    conn.commit()
    et.detect(conn)
    assert conn.execute("SELECT COUNT(*) c FROM risk_flags WHERE imo='9000003'").fetchone()["c"] == 0
    print("PASS: consistent eastern declaration (RUULU) => no R8d flag")


def test_not_exiting_east_no_event():
    conn = fresh()
    add_last_pos(conn, "9000004", 55.0, 18.0, 12.0, 270)   # mid-Baltic, westbound
    set_dest(conn, "9000004", "ROTTERDAM")
    conn.commit()
    et.detect(conn)
    assert conn.execute("SELECT COUNT(*) c FROM risk_flags WHERE imo='9000004'").fetchone()["c"] == 0
    print("PASS: vessel not at the eastern edge => no event")


if __name__ == "__main__":
    test_classification()
    test_west_declaration_is_contradiction()
    test_unknown_declaration_flagged()
    test_consistent_eastern_declaration_not_flagged()
    test_not_exiting_east_no_event()
    print("\nAll eastbound tests passed.")
