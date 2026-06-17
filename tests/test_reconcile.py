"""
test_reconcile.py — proves the M2 reconciliation matrix correctly reflects which
lists include a vessel (and therefore where they disagree).

Run:  py tests/test_reconcile.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from report import reconcile


def fresh_db():
    conn = db.connect(":memory:")
    conn.executescript(db.SCHEMA)
    return conn


def add(conn, imo, list_name):
    conn.execute(
        "INSERT INTO list_membership (imo, list_name, present, as_of, source_url) "
        "VALUES (?, ?, 1, '2026-06-16T00:00:00+00:00', 'https://example.org')",
        (imo, list_name))


def test_matrix_and_disagreement():
    conn = fresh_db()
    add(conn, "9000001", "EU")
    add(conn, "9000001", "GUR")     # on EU and GUR
    add(conn, "9000002", "GUR")     # on GUR only -> disagreement, and GUR-not-EU
    add(conn, "9000003", "OFAC")
    add(conn, "9000003", "EU")
    conn.commit()

    matrix = reconcile.build_matrix(conn)
    assert matrix["9000001"] == {"EU", "GUR"}
    assert matrix["9000002"] == {"GUR"}

    gur_not_eu = [imo for imo, l in matrix.items() if "GUR" in l and "EU" not in l]
    assert gur_not_eu == ["9000002"], gur_not_eu
    print("PASS: membership matrix and 'on GUR but not EU' disagreement are correct")


if __name__ == "__main__":
    test_matrix_and_disagreement()
    print("\nAll reconcile tests passed.")
