"""
age_risk.py — an early, working PREVIEW of the M5 risk engine: just rule R1
("vessel age over 20 years", weight 3). Applied continuously to vessels we
observe via AIS.

For a given IMO:
  1. ensure_built_year(): if we have NO built_year fact from any source, query
     Wikidata for it (never overwriting a primary-source value).
  2. flag_r1(): once a built_year is known (any source), compute the age; if it
     is over 20 years, write a risk_flags row (rule_id='R1', triggered=1,
     weight=3) whose evidence points to the exact built_year fact used.

Idempotent: a vessel is flagged R1 at most once. The full engine (all rules,
bands, recompute-on-config-change) comes in M5; this is one rule, live now.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from connectors import wikidata
from provenance import utc_now_iso

R1_WEIGHT = 3
R1_THRESHOLD = 20
THIS_YEAR = datetime.now(timezone.utc).year


def built_year_facts(conn, imo):
    return conn.execute(
        "SELECT fact_id, value, source_id, source_url FROM facts "
        "WHERE imo=? AND field='built_year' AND value IS NOT NULL", (imo,)).fetchall()


def _year(value):
    m = re.search(r"\d{4}", value or "")
    return int(m.group(0)) if m else None


def ensure_built_year(conn, imo):
    """If no built_year fact exists from any source, query Wikidata for it.
    Returns ('existing'|'wikidata'|'none')."""
    if built_year_facts(conn, imo):
        return "existing"
    wikidata.lookup_one(conn, imo)
    return "wikidata" if built_year_facts(conn, imo) else "none"


def choose_built_year_fact(conn, imo):
    """Pick the built_year fact to base R1 on: prefer a primary source over the
    tertiary Wikidata, then the oldest year (conservative). Returns row or None."""
    rows = built_year_facts(conn, imo)
    if not rows:
        return None
    def key(r):
        tier = 1 if r["source_id"] == "wikidata" else 0   # primary first
        return (tier, _year(r["value"]) or 9999)
    return sorted(rows, key=key)[0]


def has_r1_flag(conn, imo):
    return conn.execute("SELECT 1 FROM risk_flags WHERE imo=? AND rule_id='R1' "
                        "AND triggered=1", (imo,)).fetchone() is not None


def flag_r1(conn, imo):
    """Apply rule R1. Returns (flagged: bool, info: dict|None). Idempotent."""
    fact = choose_built_year_fact(conn, imo)
    if not fact:
        return False, None
    year = _year(fact["value"])
    if year is None:
        return False, None
    age = THIS_YEAR - year
    info = {"built_year": year, "age": age, "source_id": fact["source_id"],
            "source_url": fact["source_url"], "fact_id": fact["fact_id"]}
    if age <= R1_THRESHOLD:
        return False, info
    if has_r1_flag(conn, imo):
        info["already_flagged"] = True
        return True, info
    evidence = json.dumps({
        "rule": "R1", "condition": f"age > {R1_THRESHOLD}",
        "built_year": year, "age": age, "built_year_fact_id": fact["fact_id"],
        "built_year_source": fact["source_id"], "source_url": fact["source_url"],
    })
    with conn:
        conn.execute(
            "INSERT INTO risk_flags (imo, rule_id, triggered, evidence, weight, evaluated_at) "
            "VALUES (?, 'R1', 1, ?, ?, ?)", (imo, evidence, R1_WEIGHT, utc_now_iso()))
    return True, info


def process_imo(conn, imo):
    """Full per-vessel pipeline: ensure build year (Wikidata if needed), flag R1."""
    src = ensure_built_year(conn, imo)
    flagged, info = flag_r1(conn, imo)
    return {"imo": imo, "built_year_source": src, "flagged": flagged, "info": info}
