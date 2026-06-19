"""
risk_engine.py — M5: the transparent risk-scoring engine.

Reads the weights/bands from rules.yaml, evaluates each rule per vessel against
REAL stored evidence, writes every fired rule to risk_flags (with the source
behind it), and writes a total score + band per vessel to risk_scores. Fully
recomputable: re-running clears and rebuilds.

Every rule returns one of three states, and the engine is explicit about all
three (no silent zeros):
  * triggered      — the condition is met (counts toward the score)
  * not_triggered  — we have the data and the condition is NOT met
  * not_evaluated  — we lack the data to judge (does NOT count; reason recorded)

What our current data can and cannot evaluate (the honest part — see the printed
summary and the README):
  EVALUABLE : R1/R1b (age), R3 (flag change), R4 (name change), R5 (FoC flag),
              R6 (PSC detention list), R10 (sanctions listing).
  DATA-GAP  : R2 (no insurer data), R7 (AIS gaps — our capture is intermittent,
              so a gap is indistinguishable from us not listening), R9 (loitering
              /STS — same reason), R8 (Russian-terminal calls — no AIS coverage
              there). R8d (eastbound transit) is evaluated but rarely fires for
              the same coverage reason.

R8d flags are produced by eastbound_transit.py; this engine refreshes them, then
owns every other rule's flags.
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
import db
from provenance import utc_now_iso
from identity import (group_identity_history, current_value, recent_changes,
                      display_name)
from age_risk import choose_built_year_fact, _year, THIS_YEAR
from inference import eastbound_transit

RULES_PATH = Path(__file__).resolve().parents[2] / "rules.yaml"

# list_membership names that indicate a Port State Control detention/ban (R6)
DETENTION_LISTS = {"tokyo_mou_detention", "ext_tokyo_mou_psc", "black_sea_mou_detention",
                   "paris_mou_banned", "abuja_mou_detention", "ext_abuja_mou_psc"}
# list_membership names that count as a sanctions listing (R10)
SANCTION_LISTS = {"EU", "OFAC", "UK", "GUR"}

TRIG, NOT, NA = "triggered", "not_triggered", "not_evaluated"
# vessel_type substrings that mean "carries oil/crude/gas/chemicals" (R11)
TANKER_KEYWORDS = ("tanker", "oil", "crude", "gas", "chemical", "lng", "lpg", "petroleum")
ONE_YEAR_AGO = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(timespec="seconds")


def load_cfg():
    r = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    weights = {x["id"]: int(x["weight"]) for x in r["rules"]}
    bands = r["bands"]
    foc = {str(f).strip().lower() for f in r.get("foc_flags", [])}
    return weights, bands, foc


def band_for(score, bands):
    for b in bands:
        if b["min"] <= score <= b["max"]:
            return b["name"]
    return "unknown"


def _identity_rows(conn, imo, field):
    return conn.execute(
        "SELECT value, origin_dataset, first_seen, last_seen, source_url FROM identity_history "
        "WHERE imo=? AND field=?", (imo, field)).fetchall()


def score_vessel(conn, imo, foc):
    """Return {rule_id: (state, evidence_dict)} for every rule, from real data."""
    out = {}

    # --- R1 / R1b : age (mutually exclusive) ---
    fact = choose_built_year_fact(conn, imo)
    if not fact:
        out["R1"] = (NA, {"reason": "no built_year fact from any source"})
        out["R1b"] = (NA, {"reason": "no built_year fact from any source"})
    else:
        year = _year(fact["value"]); age = THIS_YEAR - year
        ev = {"built_year": year, "age": age, "built_year_fact_id": fact["fact_id"],
              "source": fact["source_id"], "source_url": fact["source_url"]}
        out["R1"] = (TRIG if age > 20 else NOT, ev)
        out["R1b"] = (TRIG if 15 <= age <= 20 else NOT, ev)

    # --- R3 / R4 : flag / name change within 12 months ---
    for rule, field in (("R3", "flag"), ("R4", "name")):
        rows = _identity_rows(conn, imo, field)
        if not rows:
            out[rule] = (NA, {"reason": f"no dated {field} history"})
            continue
        groups = group_identity_history(rows, field)
        rc = recent_changes(groups, ONE_YEAR_AGO)
        if rc:
            out[rule] = (TRIG, {"since": ONE_YEAR_AGO,
                                "new_values": [g["variants"] for g in rc],
                                "first_seen": [g["first_seen"] for g in rc],
                                "source_url": rows[0]["source_url"]})
        else:
            out[rule] = (NOT, {"distinct_values": len(groups)})

    # --- R5 : flag-of-convenience flag ---
    frows = _identity_rows(conn, imo, "flag")
    cur = current_value(group_identity_history(frows, "flag")) if frows else None
    if not cur:
        out["R5"] = (NA, {"reason": "no flag data"})
    else:
        code = cur["key"]
        out["R5"] = ((TRIG if code in foc else NOT),
                     {"current_flag": code, "foc": code in foc})

    # --- R6 : PSC detention list membership ---
    drows = conn.execute(
        "SELECT list_name, as_of, source_url FROM list_membership WHERE imo=? AND list_name IN (%s)"
        % ",".join("?" * len(DETENTION_LISTS)), (imo, *DETENTION_LISTS)).fetchall()
    any_list = conn.execute("SELECT 1 FROM list_membership WHERE imo=? LIMIT 1", (imo,)).fetchone()
    if drows:
        out["R6"] = (TRIG, {"lists": [r["list_name"] for r in drows],
                            "as_of": drows[0]["as_of"], "source_url": drows[0]["source_url"],
                            "note": "membership in a PSC detention/ban list (proxy; precise <24mo date not held)"})
    else:
        out["R6"] = (NOT if any_list else NA,
                     {"reason": None if any_list else "no list_membership for this vessel"})

    # --- R8d : eastbound transit (owned by eastbound_transit; read its flag) ---
    fl = conn.execute("SELECT evidence FROM risk_flags WHERE imo=? AND rule_id='R8d' AND triggered=1",
                      (imo,)).fetchone()
    out["R8d"] = ((TRIG, json.loads(fl["evidence"])) if fl else (NOT, {"reason": "no east-exit observed"}))

    # --- R10 : sanctions listing ---
    srows = conn.execute(
        "SELECT DISTINCT list_name, source_url FROM list_membership WHERE imo=? AND list_name IN (%s)"
        % ",".join("?" * len(SANCTION_LISTS)), (imo, *SANCTION_LISTS)).fetchall()
    if srows:
        out["R10"] = (TRIG, {"lists": [r["list_name"] for r in srows], "source_url": srows[0]["source_url"]})
    else:
        out["R10"] = (NOT if any_list else NA, {"reason": None if any_list else "not in any list"})

    # --- R11 : carries oil / crude / gas / chemicals (tanker) ---
    vtypes = [r["value"] for r in conn.execute(
        "SELECT DISTINCT value FROM facts WHERE imo=? AND field='vessel_type' AND value IS NOT NULL",
        (imo,))]
    ac = conn.execute("SELECT type_category FROM positions WHERE imo=? AND source_id='aisstream' "
                      "AND type_category IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (imo,)).fetchone()
    ais_cat = ac["type_category"] if ac else None
    is_tanker = (any(any(kw in v.lower() for kw in TANKER_KEYWORDS) for v in vtypes)
                 or ais_cat == "tanker")
    has_type = bool(vtypes) or (ais_cat and ais_cat != "unknown")
    if is_tanker:
        out["R11"] = (TRIG, {"vessel_type": vtypes, "ais_category": ais_cat})
    elif has_type:
        out["R11"] = (NOT, {"vessel_type": vtypes, "ais_category": ais_cat})
    else:
        out["R11"] = (NA, {"reason": "no vessel type known"})

    # --- R12 : three or more distinct names on record ---
    nrows = _identity_rows(conn, imo, "name")
    if not nrows:
        out["R12"] = (NA, {"reason": "no name history"})
    else:
        ngroups = group_identity_history(nrows, "name")
        if len(ngroups) >= 3:
            out["R12"] = (TRIG, {"names": [g["variants"][0] for g in ngroups], "count": len(ngroups)})
        else:
            out["R12"] = (NOT, {"count": len(ngroups)})
    return out


def run(conn):
    weights, bands, foc = load_cfg()
    now = utc_now_iso()
    eastbound_transit.detect(conn)                 # refresh R8d flags (owned there)
    with conn:
        conn.execute("DELETE FROM risk_flags WHERE rule_id != 'R8d'")
        conn.execute("DELETE FROM risk_scores")

    imos = [r["imo"] for r in conn.execute(
        "SELECT imo FROM facts UNION SELECT imo FROM positions WHERE imo IS NOT NULL")]
    stats = {"vessels": 0, "scored": 0, "by_band": {}, "na_counts": {}}

    for imo in imos:
        res = score_vessel(conn, imo, foc)
        stats["vessels"] += 1
        total = 0
        with conn:
            for rule, (state, ev) in res.items():
                if state == NA:
                    stats["na_counts"][rule] = stats["na_counts"].get(rule, 0) + 1
                if state == TRIG:
                    total += weights.get(rule, 0)
                    if rule == "R8d":
                        continue            # already stored by eastbound_transit
                    conn.execute(
                        "INSERT INTO risk_flags (imo, rule_id, triggered, evidence, weight, evaluated_at) "
                        "VALUES (?, ?, 1, ?, ?, ?)",
                        (imo, rule, json.dumps(ev), weights.get(rule, 0), now))
            band = band_for(total, bands)
            conn.execute("INSERT INTO risk_scores (imo, total_score, band, computed_at) "
                         "VALUES (?, ?, ?, ?)", (imo, total, band, now))
        stats["by_band"][band] = stats["by_band"].get(band, 0) + 1
        stats["scored"] += 1
    return stats


def show(conn, imo):
    weights, bands, foc = load_cfg()
    res = score_vessel(conn, imo, foc)
    sc = conn.execute("SELECT total_score, band FROM risk_scores WHERE imo=?", (imo,)).fetchone()
    name = ""
    frows = _identity_rows(conn, imo, "name")
    if frows:
        cur = current_value(group_identity_history(frows, "name"))
        name = display_name(cur) if cur else ""
    print(f"\n{'='*72}\nVESSEL IMO {imo}  {name}")
    if sc:
        print(f"SCORE: {sc['total_score']}  BAND: {sc['band'].upper()}")
    print('='*72)
    descr = {x["id"]: x["description"] for x in yaml.safe_load(RULES_PATH.read_text(encoding='utf-8'))["rules"]}
    for rule in ("R1", "R1b", "R3", "R4", "R12", "R5", "R11", "R6", "R8d", "R10"):
        state, ev = res[rule]
        w = weights.get(rule, 0)
        mark = {"triggered": f"FIRED  +{w}", "not_triggered": "  -  ", "not_evaluated": " n/a "}[state]
        print(f"  [{mark:9s}] {rule:4s} {descr.get(rule,'')[:52]}")
        if state == "triggered":
            print(f"             evidence: {json.dumps(ev)[:160]}")
        elif state == "not_evaluated":
            print(f"             not evaluated: {ev.get('reason','')}")


def main():
    conn = db.init_db()
    print("Scoring all vessels...")
    stats = run(conn)
    print(f"\nScored {stats['scored']} vessels.")
    print("Band distribution:", stats["by_band"])
    print("Rules NOT evaluable (data gaps), # vessels affected:")
    for rule in sorted(stats["na_counts"]):
        print(f"  {rule}: {stats['na_counts'][rule]}")
    top = conn.execute("SELECT imo, total_score FROM risk_scores ORDER BY total_score DESC LIMIT 1").fetchone()
    if top:
        show(conn, top["imo"])


if __name__ == "__main__":
    main()
