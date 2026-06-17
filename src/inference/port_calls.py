"""
port_calls.py — M4: infer port calls at Russian Baltic terminals from AIS
position history, and surface externally-stated calls (R8c) without inference.

Inference (R8a/R8b): a vessel is "in" a terminal when its position is within the
terminal's circular zone AND its speed over ground is at/below a low threshold
(stopped, berthed or anchored — not transiting). A run of such positions lasting
at least a minimum dwell (or enough pings) is recorded as a port call in
`port_calls`, tagged with the terminal's tier, a method note, and the exact
position_ids that triggered it. This is an INFERENCE, stored separately from
facts and always traceable to the positions used.

R8c (Novorossiysk / Kozmino / Murmansk): these are outside our AIS coverage, so
we NEVER infer them from our own positions. Instead we scan `facts` for an
external source already stating such a call and surface it, clearly marked
'external-fact', never as our own inference.

Honesty notes:
* AIS can be spoofed and has gaps; a detected call is evidence, not proof.
* Thresholds (speed, dwell, gap) are explicit and tunable below — no hidden logic.
* Detection only applies to positions whose IMO is known (so a call can be
  attributed to a vessel); unidentified traffic is not turned into port calls.
"""

import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

import db

GEOFENCES = Path(__file__).resolve().parents[2] / "config" / "geofences.yaml"
AIS_SOURCE = "aisstream"
INFERRED_TAG = "AIS-inferred"          # marks rows this module creates (for clean re-runs)

# AIS-inferred detection at the Russian terminals is DISABLED by default. The free
# aisstream network has no coverage in Russian coastal waters (confirmed
# 2026-06-17: easternmost position ~26.85 E; all six terminals are further east,
# and Kaliningrad has zero positions too), so detection here will always return 0.
# We keep the logic (and its tests) intact for the future — e.g. if a covered
# source such as satellite AIS is ever added. Force a run with RUN_PORT_CALLS=1.
AIS_INFERENCE_ENABLED = False

# --- tunable detection thresholds (explicit, no hidden logic) ---
SPEED_MAX_KN = 1.0       # at/below this = stopped/berthed/anchored, not transiting
MIN_DWELL_MIN = 15       # a run must span at least this many minutes ...
MIN_PINGS = 3            # ... OR contain at least this many in-zone positions
MAX_GAP_HOURS = 6        # split a run into separate calls if pings are >this apart

EXTERNAL_PORTS = ["Novorossiysk", "Kozmino", "Murmansk"]


def load_terminals():
    cfg = yaml.safe_load(GEOFENCES.read_text(encoding="utf-8"))
    return cfg["russian_baltic_terminals"]


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def detect(conn, speed_max=SPEED_MAX_KN, min_dwell_min=MIN_DWELL_MIN,
           min_pings=MIN_PINGS, max_gap_hours=MAX_GAP_HOURS):
    """Infer port calls and (re)write them to port_calls. Returns a summary."""
    terminals = load_terminals()
    # Clean rebuild of AIS-inferred calls so re-runs don't duplicate.
    with conn:
        conn.execute("DELETE FROM port_calls WHERE method_note LIKE ?", (INFERRED_TAG + "%",))

    imos = [r["imo"] for r in conn.execute(
        "SELECT DISTINCT imo FROM positions WHERE imo IS NOT NULL AND source_id=?",
        (AIS_SOURCE,))]
    stats = {"vessels_checked": len(imos), "calls": 0, "by_tier": {}}

    for imo in imos:
        rows = conn.execute(
            "SELECT position_id, lat, lon, sog, timestamp FROM positions "
            "WHERE imo=? AND source_id=? ORDER BY timestamp", (imo, AIS_SOURCE)).fetchall()
        for term in terminals:
            # positions that are inside the zone AND slow
            inside = [r for r in rows
                      if r["sog"] is not None and r["sog"] <= speed_max
                      and haversine_km(r["lat"], r["lon"], term["lat"], term["lon"]) <= term["radius_km"]]
            if not inside:
                continue
            # cluster into separate calls on large time gaps
            cluster = [inside[0]]
            clusters = [cluster]
            for prev, cur in zip(inside, inside[1:]):
                gap_h = (_parse(cur["timestamp"]) - _parse(prev["timestamp"])).total_seconds() / 3600
                if gap_h > max_gap_hours:
                    cluster = [cur]
                    clusters.append(cluster)
                else:
                    cluster.append(cur)
            for cl in clusters:
                span_min = (_parse(cl[-1]["timestamp"]) - _parse(cl[0]["timestamp"])).total_seconds() / 60
                if span_min < min_dwell_min and len(cl) < min_pings:
                    continue
                pos_ids = [r["position_id"] for r in cl]
                method = (f"{INFERRED_TAG}: {len(cl)} positions inside {term['radius_km']}km of "
                          f"{term['name']} at sog<={speed_max}kn over {span_min:.0f} min")
                with conn:
                    conn.execute(
                        "INSERT INTO port_calls (imo, port, country, tier, arrival, departure, "
                        "method_note, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (imo, term["name"], term["country"], term["tier"],
                         cl[0]["timestamp"], cl[-1]["timestamp"], method, json.dumps(pos_ids)))
                stats["calls"] += 1
                stats["by_tier"][term["tier"]] = stats["by_tier"].get(term["tier"], 0) + 1
    return stats


# Only facts that genuinely DENOTE a port call count for R8c — NOT vessel names,
# owners or registries that merely contain a port's name (e.g. a ship called
# "Murmansk", or "Gazpromneft Murmansk"). We currently store no such facts, so
# R8c correctly surfaces nothing; this is wired for when port-call facts are
# ingested (e.g. GUR per-vessel pages — see TODO.md).
PORT_CALL_FIELDS = {"port_call", "recent_port", "last_port", "port_of_call", "call_port"}


def detect_external(conn):
    """R8c: surface externally-stated calls at out-of-range ports, ONLY from
    facts whose field denotes a port call. Never inferred from our positions."""
    found = []
    with conn:
        conn.execute("DELETE FROM port_calls WHERE method_note LIKE 'external-fact%'")
    if not PORT_CALL_FIELDS:
        return found
    rows = conn.execute(
        "SELECT fact_id, imo, field, value, source_id, source_url FROM facts WHERE field IN (%s)"
        % ",".join("?" * len(PORT_CALL_FIELDS)), tuple(PORT_CALL_FIELDS)).fetchall()
    for r in rows:
        for port in EXTERNAL_PORTS:
            if port.lower() in (r["value"] or "").lower():
                with conn:
                    conn.execute(
                        "INSERT INTO port_calls (imo, port, country, tier, arrival, departure, "
                        "method_note, evidence) VALUES (?, ?, 'Russia', 'R8c', NULL, NULL, ?, ?)",
                        (r["imo"], port,
                         f"external-fact: stated by {r['source_id']} (NOT an AIS inference)",
                         json.dumps({"fact_id": r["fact_id"], "source_url": r["source_url"]})))
                found.append((r["imo"], port, r["fact_id"]))
    return found


def show(conn, per_tier=3):
    for tier in ("R8a", "R8b"):
        rows = conn.execute(
            "SELECT * FROM port_calls WHERE tier=? AND method_note LIKE ? "
            "ORDER BY departure DESC LIMIT ?", (tier, INFERRED_TAG + "%", per_tier)).fetchall()
        print(f"\n=== {tier} inferred port calls (showing up to {per_tier}) ===")
        if not rows:
            print("  (none detected in current position history)")
        for r in rows:
            ev = json.loads(r["evidence"])
            print(f"  IMO {r['imo']}  {r['port']}")
            print(f"     arrival {r['arrival']}  departure {r['departure']}")
            print(f"     {r['method_note']}")
            print(f"     evidence position_ids: {ev[:8]}{'...' if len(ev) > 8 else ''}")
    ext = conn.execute("SELECT * FROM port_calls WHERE tier='R8c'").fetchall()
    print(f"\n=== R8c external-fact flags ({len(ext)}) ===")
    if not ext:
        print("  (no external facts in our data state a call at Novorossiysk/Kozmino/Murmansk)")
    for r in ext[:per_tier]:
        print(f"  IMO {r['imo']}  {r['port']}  [{r['method_note']}]")


def main():
    import os
    conn = db.init_db()
    if not (AIS_INFERENCE_ENABLED or os.getenv("RUN_PORT_CALLS")):
        print("AIS-inferred port-call detection is DISABLED.")
        print("Reason: the free aisstream network has no coverage in Russian coastal waters,")
        print("so R8a/R8b detection always returns 0 (see README). The detector is retained")
        print("and unit-tested; set RUN_PORT_CALLS=1 to run it anyway (e.g. with a covered")
        print("AIS source in future).")
        ext = detect_external(conn)   # cheap, correct, still useful
        print(f"R8c external-fact flags (from stored port-call facts, if any): {len(ext)}")
        return
    print("Detecting AIS-inferred port calls at Russian Baltic terminals...")
    stats = detect(conn)
    print(f"  vessels checked: {stats['vessels_checked']}  calls: {stats['calls']}  "
          f"by tier: {stats['by_tier']}")
    ext = detect_external(conn)
    print(f"  R8c external-fact flags: {len(ext)}")
    show(conn)


if __name__ == "__main__":
    main()
