"""
eastbound_transit.py — infer "transited toward the eastern Gulf of Finland" when
a vessel leaves our coverage at the eastern edge, and cross-check it against the
vessel's self-declared AIS Destination.

Logic:
  * An east-exit event = a vessel whose LAST observed position is near the eastern
    coverage edge, in the Gulf-of-Finland latitude band, moving eastbound. (Our
    box only borders open sea on the east in that corridor.)
  * We classify the vessel's latest declared AIS Destination by DIRECTION, not
    nationality: a port WEST of the eastern edge (~27 E) cannot be reached by
    exiting east — so "declared west + exited east" is a contradiction (the
    declaration is provably inconsistent with observed behaviour). A blank/
    unrecognised destination is 'unknown'.
  * When the declaration is CONTRADICTED or UNKNOWN, we write an inference:
    "transited toward the eastern Gulf of Finland" (rule R8d, low confidence),
    recording the declared destination alongside it. We never assert a Russian
    dock — only the observed eastbound transit. A consistent eastern declaration
    needs no inference: the declared eastern port already speaks for itself.

Honesty / caveats (kept visible):
  * The eastern Gulf is shared by Russia, Finland (Kotka/Hamina) and Estonia
    (Sillamae/Narva) — "east" is NOT "Russia". We say "eastern Gulf", not "Russia".
  * Low confidence: AIS can be spoofed; an east-edge position may be transit, not
    a true exit. Weight is small and tunable in rules.yaml (R8d).
  * Coverage: the free AIS feed barely reaches the eastern edge, so real events
    are rare (see README port-call coverage note).
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
import db
from provenance import utc_now_iso

RULES = Path(__file__).resolve().parents[2] / "rules.yaml"
AIS_SOURCE = "aisstream"

# --- east-exit detection thresholds (explicit, tunable) ---
EDGE_LON = 26.5          # "near the eastern edge" (coverage ends ~26.85, box 27.0)
GULF_LAT = (59.0, 60.8)  # the only latitudes where our east edge borders open sea
EAST_COG = (30, 150)     # course over ground considered "eastbound" (degrees)
MIN_SOG = 2.0            # must be moving (not anchored at the edge)

# Destination gazetteer: token (UPPERCASE, name or UN/LOCODE) -> approx longitude.
# Classification is by direction relative to the eastern edge (~27 E):
#   lon > 27  -> 'east' (reachable by exiting east: eastern Gulf of Finland)
#   lon < 27  -> 'west' (NOT reachable by exiting east -> contradiction)
# Editable; unmatched destinations are treated as 'unknown' (never guessed).
DEST_GAZETTEER = {
    # eastern Gulf of Finland (east of the edge) -> consistent with an east-exit
    "UST-LUGA": 28.4, "UST LUGA": 28.4, "RUULU": 28.4,
    "PRIMORSK": 28.7, "RUPRI": 28.7,
    "VYSOTSK": 28.6, "RUVYS": 28.6,
    "VYBORG": 28.7, "RUVYB": 28.7, "RUVYG": 28.7,
    "ST PETERSBURG": 30.2, "ST.PETERSBURG": 30.2, "SAINT PETERSBURG": 30.2,
    "PETERSBURG": 30.2, "RULED": 30.2, "BRONKA": 29.8, "RUBKA": 29.8,
    "HAMINA": 27.2, "FIHMN": 27.2, "KOTKA": 26.95, "FIKTK": 26.95,
    "SILLAMAE": 27.7, "EESIL": 27.7, "NARVA": 28.0, "KUNDA": 26.5,
    # west / south of the edge -> a vessel exiting EAST cannot be going here
    "KALININGRAD": 20.4, "RUKGD": 20.4, "BALTIYSK": 19.9,
    "HELSINKI": 24.9, "FIHEL": 24.9, "TALLINN": 24.7, "EETLL": 24.7, "MUUGA": 25.0,
    "RIGA": 24.1, "LVRIX": 24.1, "VENTSPILS": 21.6, "LIEPAJA": 21.0,
    "KLAIPEDA": 21.1, "LTKLJ": 21.1, "GDANSK": 18.7, "PLGDN": 18.7,
    "GDYNIA": 18.5, "PLGDY": 18.5, "STOCKHOLM": 18.1, "GOTHENBURG": 11.9, "SEGOT": 11.9,
    "COPENHAGEN": 12.6, "DKCPH": 12.6, "KIEL": 10.1, "DEKEL": 10.1,
    "ROTTERDAM": 4.5, "NLRTM": 4.5, "AMSTERDAM": 4.9, "NLAMS": 4.9,
    "ANTWERP": 4.4, "BEANR": 4.4, "HAMBURG": 10.0, "DEHAM": 10.0,
    "BREMERHAVEN": 8.6, "WILHELMSHAVEN": 8.1, "LE HAVRE": 0.1, "IMMINGHAM": -0.2,
}


def r8d_weight(default=1):
    try:
        rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
        for r in rules.get("rules", []):
            if r.get("id") == "R8d":
                return int(r.get("weight", default))
    except Exception:
        pass
    return default


def classify_destination(dest):
    """Return ('east'|'west'|'unknown', matched_token_or_None). Direction is
    relative to the eastern edge (~27 E)."""
    if not dest or not dest.strip():
        return "unknown", None
    d = dest.upper()
    d_collapsed = re.sub(r"[^A-Z0-9]", "", d)   # 'NL RTM' / 'NL-RTM' -> 'NLRTM'
    # longest token match wins (avoid short tokens matching inside longer strings)
    for token in sorted(DEST_GAZETTEER, key=len, reverse=True):
        tok_collapsed = re.sub(r"[^A-Z0-9]", "", token)
        if token in d or (len(tok_collapsed) >= 5 and tok_collapsed in d_collapsed):
            return ("east" if DEST_GAZETTEER[token] > 27.0 else "west"), token
    return "unknown", None


def _eastbound(cog):
    return cog is not None and EAST_COG[0] <= cog <= EAST_COG[1]


def latest_destination(conn, imo):
    row = conn.execute(
        "SELECT fact_id, value, retrieved_at FROM facts WHERE imo=? AND field='ais_destination' "
        "ORDER BY retrieved_at DESC LIMIT 1", (imo,)).fetchone()
    return row


def detect(conn, weight=None):
    """Find east-exit events and flag contradicted/unknown declarations as R8d."""
    weight = weight if weight is not None else r8d_weight()
    with conn:
        conn.execute("DELETE FROM risk_flags WHERE rule_id='R8d'")
    imos = [r["imo"] for r in conn.execute(
        "SELECT DISTINCT imo FROM positions WHERE imo IS NOT NULL AND source_id=?", (AIS_SOURCE,))]
    stats = {"vessels": len(imos), "east_exits": 0, "flagged": 0,
             "by_reason": {"contradiction": 0, "unknown": 0, "consistent": 0}}

    for imo in imos:
        last = conn.execute(
            "SELECT position_id, lat, lon, sog, cog, timestamp FROM positions "
            "WHERE imo=? AND source_id=? ORDER BY timestamp DESC LIMIT 1", (imo, AIS_SOURCE)).fetchone()
        if not last:
            continue
        at_edge = (last["lon"] >= EDGE_LON and GULF_LAT[0] <= last["lat"] <= GULF_LAT[1]
                   and last["sog"] is not None and last["sog"] >= MIN_SOG and _eastbound(last["cog"]))
        if not at_edge:
            continue
        stats["east_exits"] += 1

        dfact = latest_destination(conn, imo)
        dest = dfact["value"] if dfact else None
        cls, token = classify_destination(dest)
        if cls == "east":
            reason = "consistent"          # declared eastern port matches behaviour
        elif cls == "west":
            reason = "contradiction"       # declared a port west of us but exiting east
        else:
            reason = "unknown"             # blank/unrecognised destination
        stats["by_reason"][reason] += 1

        if reason == "consistent":
            continue                       # declared eastern port already speaks for itself

        note = ("transited toward the eastern Gulf of Finland (Russian/Finnish/Estonian "
                "ports) — NOT a confirmed call; ")
        if reason == "contradiction":
            note += f"declared destination {dest!r} is WEST of the exit and cannot be reached eastbound"
        else:
            shown = repr(dest) if dest else "UNKNOWN/blank"
            note += f"declared destination {shown} could not be confirmed"
        evidence = json.dumps({"rule": "R8d", "event": "east_exit", "reason": reason,
                               "declared_destination": dest, "destination_class": cls,
                               "exit_position_id": last["position_id"],
                               "exit_lat": last["lat"], "exit_lon": last["lon"],
                               "exit_cog": last["cog"], "exit_time": last["timestamp"],
                               "destination_fact_id": dfact["fact_id"] if dfact else None})
        with conn:
            conn.execute(
                "INSERT INTO risk_flags (imo, rule_id, triggered, evidence, weight, evaluated_at) "
                "VALUES (?, 'R8d', 1, ?, ?, ?)", (imo, evidence, weight, utc_now_iso()))
        stats["flagged"] += 1
    return stats


def main():
    conn = db.init_db()
    print("Detecting eastbound-transit events and cross-checking declared destinations...")
    stats = detect(conn)
    print(f"  IMO-known vessels: {stats['vessels']}")
    print(f"  east-exit events:  {stats['east_exits']}  (by reason: {stats['by_reason']})")
    print(f"  R8d flags written: {stats['flagged']}")
    for r in conn.execute("SELECT imo, evidence FROM risk_flags WHERE rule_id='R8d' LIMIT 5"):
        ev = json.loads(r["evidence"])
        print(f"   IMO {r['imo']}: {ev['reason']} | declared={ev['declared_destination']!r} "
              f"| exit {ev['exit_lat']:.2f}N {ev['exit_lon']:.2f}E")


if __name__ == "__main__":
    main()
