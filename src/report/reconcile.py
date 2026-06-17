"""
reconcile.py — M2 cross-source reconciliation.

Shows, per vessel (IMO), which sanctioning authorities list it, and surfaces the
DISAGREEMENTS between lists rather than picking a single "truth". Prints a
readable summary + sample tables to the console and writes the full matrix to
exports/reconciliation.csv.

Honesty notes:
* We only report list membership we actually have. KSE is NOT available via
  OpenSanctions, so it is absent here (tracked in TODO.md). Its absence is stated,
  not hidden.
* The vessel name shown is the DERIVED "latest known" name (an inference), purely
  for readability. Membership itself is fact (list_membership rows are sourced).
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
from identity import group_identity_history, current_value, display_name, is_valid_imo

# The core authorities we reconcile across. Each maps to the list_name(s) stored
# in list_membership that represent it. (KSE intentionally absent — see TODO.md.)
CORE_LISTS = ["EU", "OFAC", "UK", "GUR", "UN"]

EXPORT_PATH = Path(__file__).resolve().parents[2] / "exports" / "reconciliation.csv"


def build_matrix(conn):
    """Return {imo: set(core lists it is on)} restricted to CORE_LISTS."""
    matrix = defaultdict(set)
    rows = conn.execute(
        "SELECT DISTINCT imo, list_name FROM list_membership WHERE list_name IN (%s)"
        % ",".join("?" * len(CORE_LISTS)), CORE_LISTS
    ).fetchall()
    for r in rows:
        matrix[r["imo"]].add(r["list_name"])
    return matrix


def current_names(conn):
    """{imo: latest-known display name} computed once for all vessels."""
    rows = conn.execute(
        "SELECT imo, value, origin_dataset, first_seen, last_seen "
        "FROM identity_history WHERE field='name'").fetchall()
    by_imo = defaultdict(list)
    for r in rows:
        by_imo[r["imo"]].append(r)
    out = {}
    for imo, rs in by_imo.items():
        cur = current_value(group_identity_history(rs, "name"))
        out[imo] = display_name(cur) if cur else ""
    return out


def reconcile(conn):
    matrix = build_matrix(conn)
    names = current_names(conn)
    summary = {lst: 0 for lst in CORE_LISTS}
    consensus = partial = singleton = 0
    for imo, lists in matrix.items():
        for lst in lists:
            summary[lst] += 1
        if len(lists) == len(CORE_LISTS):
            consensus += 1
        elif len(lists) == 1:
            singleton += 1
            partial += 1
        else:
            partial += 1
    return matrix, names, summary, consensus, partial, singleton


def print_report(conn, sample=12):
    matrix, names, summary, consensus, partial, singleton = reconcile(conn)
    total = len(matrix)

    print("=" * 78)
    print("M2 CROSS-SOURCE RECONCILIATION")
    print("Core lists compared:", ", ".join(CORE_LISTS),
          "   (KSE not in OpenSanctions — see TODO.md)")
    print("=" * 78)
    print(f"\nVessels on at least one core list: {total}")
    for lst in CORE_LISTS:
        print(f"  {lst:5s}: {summary[lst]}")
    print(f"\nAgreement:")
    print(f"  on ALL {len(CORE_LISTS)} core lists (consensus): {consensus}")
    print(f"  on SOME but not all (disagreement):     {partial}")
    print(f"    of which on only ONE core list:       {singleton}")

    bad_imo = sorted(imo for imo in matrix if not is_valid_imo(imo))
    print(f"\nData-quality: keys failing IMO check-digit validation: {len(bad_imo)}"
          + (f"  e.g. {bad_imo[:5]}" if bad_imo else "  (all keys are well-formed IMOs)"))

    def members_str(lists):
        return " ".join(("[%s]" % l if l in lists else " . " ) for l in CORE_LISTS)

    # The brief's check (KSE-vs-EU analog): on GUR but NOT on EU.
    gur_not_eu = sorted(imo for imo, l in matrix.items() if "GUR" in l and "EU" not in l)
    print(f"\n--- DISAGREEMENT EXAMPLE: on GUR but NOT on EU  ({len(gur_not_eu)} vessels) ---")
    print(f"  {'IMO':9s} {'  '.join(CORE_LISTS)}   name (latest known, derived)")
    for imo in gur_not_eu[:sample]:
        print(f"  {imo:9s} {members_str(matrix[imo])}   {names.get(imo,'')}")

    # Another angle: on OFAC but NOT on EU.
    ofac_not_eu = sorted(imo for imo, l in matrix.items() if "OFAC" in l and "EU" not in l)
    print(f"\n--- on OFAC but NOT on EU  ({len(ofac_not_eu)} vessels) ---")
    for imo in ofac_not_eu[:sample]:
        print(f"  {imo:9s} {members_str(matrix[imo])}   {names.get(imo,'')}")

    write_csv(matrix, names)
    print(f"\nFull matrix written to: {EXPORT_PATH}")


def write_csv(matrix, names):
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPORT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["imo", "current_name_derived"] + CORE_LISTS +
                   ["num_core_lists", "disagreement"])
        for imo in sorted(matrix):
            lists = matrix[imo]
            cells = [1 if l in lists else 0 for l in CORE_LISTS]
            disagree = 0 < len(lists) < len(CORE_LISTS)
            w.writerow([imo, names.get(imo, "")] + cells + [len(lists), int(disagree)])


def main():
    conn = db.connect()
    print_report(conn)


if __name__ == "__main__":
    main()
