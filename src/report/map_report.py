"""
map_report.py — M6: a local map of the region with vessels coloured by risk band.
Clicking a vessel opens its evidence sheet (every current fact with its source URL
and retrieved_at, plus the inferences that fired), with facts and inferences
visually separated.

Plots vessels that have BOTH a last-known AIS position and a risk score. Output is
a single self-contained HTML file (exports/map.html) — open it in a browser.

Honesty: facts (source-reported) and inferences (computed by us) are shown in two
clearly different sections, per the project's facts-vs-inferences rule. Every fact
links to the source it came from and shows when it was retrieved.
"""

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import folium
from folium.plugins import MarkerCluster
import yaml

import db
from identity import group_identity_history, current_value, display_name

OUT = Path(__file__).resolve().parents[2] / "exports" / "map.html"
RULES = Path(__file__).resolve().parents[2] / "rules.yaml"
# green 'low' = evaluated and genuinely low; grey 'insufficient' = scored low ONLY
# because we have no age and no list data for it (absence of evidence, not safety).
BAND_COLOR = {"high": "red", "elevated": "orange", "low": "green", "insufficient": "gray"}


def rule_descr():
    return {x["id"]: x["description"] for x in
            yaml.safe_load(RULES.read_text(encoding="utf-8"))["rules"]}


def vessel_name(conn, imo):
    rows = conn.execute("SELECT value, origin_dataset, first_seen, last_seen FROM identity_history "
                        "WHERE imo=? AND field='name'", (imo,)).fetchall()
    cur = current_value(group_identity_history(rows, "name")) if rows else None
    return display_name(cur) if cur else ""


def evidence_html(conn, imo, descr, insufficient=False):
    """Build the popup: header + FACTS section + INFERENCES section."""
    sc = conn.execute("SELECT total_score, band FROM risk_scores WHERE imo=?", (imo,)).fetchone()
    name = html.escape(vessel_name(conn, imo) or "(name unknown)")
    band = sc["band"] if sc else "?"
    score = sc["total_score"] if sc else "?"
    if insufficient:
        color, label = "gray", "INSUFFICIENT DATA"
    else:
        color, label = BAND_COLOR.get(band, "gray"), html.escape(str(band)).upper()

    parts = [
        f"<div style='font-family:sans-serif;font-size:12px;max-height:340px;overflow:auto'>",
        f"<div style='font-size:14px'><b>IMO {imo}</b> &nbsp; {name}</div>",
        f"<div>Risk score <b>{score}</b> &nbsp;"
        f"<span style='background:{color};color:white;padding:1px 6px;border-radius:3px'>"
        f"{label}</span></div>",
    ]
    if insufficient:
        parts.append("<div style='color:#666;margin-top:3px'><i>Low score reflects "
                     "MISSING DATA (no build year and not on any list), not a safety "
                     "assessment.</i></div>")

    # --- FACTS (source-reported) ---
    facts = db.current_profile(conn, imo)
    parts.append("<div style='margin-top:6px;background:#e8f0fe;padding:3px 5px;"
                 "font-weight:bold'>FACTS (source-reported)</div>")
    if facts:
        parts.append("<table style='border-collapse:collapse;width:100%'>")
        for f in facts:
            val = html.escape(str(f["value"]) if f["value"] is not None else "(unknown)")
            src = html.escape(f["source_id"] or "")
            url = f["source_url"] or ""
            ret = html.escape((f["retrieved_at"] or "")[:10])
            link = f"<a href='{html.escape(url)}' target='_blank'>{src}</a>" if url else src
            parts.append(
                f"<tr><td style='color:#555;padding-right:6px'>{html.escape(f['field'])}</td>"
                f"<td><b>{val}</b></td><td style='padding-left:6px'>{link} <i>{ret}</i></td></tr>")
        parts.append("</table>")
    else:
        parts.append("<i>no facts stored</i>")

    # --- INFERENCES (computed by us) ---
    flags = conn.execute("SELECT rule_id, weight, evidence FROM risk_flags "
                         "WHERE imo=? AND triggered=1 ORDER BY weight DESC", (imo,)).fetchall()
    parts.append("<div style='margin-top:6px;background:#fde8e8;padding:3px 5px;"
                 "font-weight:bold'>INFERENCES (computed — risk rules that fired)</div>")
    if flags:
        parts.append("<table style='border-collapse:collapse;width:100%'>")
        for fl in flags:
            ev = json.loads(fl["evidence"])
            ev_short = html.escape(", ".join(f"{k}={v}" for k, v in ev.items()
                                             if k in ("age", "built_year", "lists", "current_flag",
                                                      "new_values", "reason", "declared_destination"))[:120])
            parts.append(
                f"<tr><td><b>{fl['rule_id']}</b> +{fl['weight']}</td>"
                f"<td style='padding-left:4px'>{html.escape(descr.get(fl['rule_id'],''))[:46]}"
                f"<br><span style='color:#777'>{ev_short}</span></td></tr>")
        parts.append("</table>")
    else:
        parts.append("<i>no risk rules fired</i>")

    parts.append("</div>")
    return "".join(parts)


def build(conn):
    descr = rule_descr()
    rows = conn.execute(
        """SELECT p.imo, p.lat, p.lon, p.timestamp, s.band, s.total_score
           FROM positions p
           JOIN (SELECT imo, MAX(timestamp) mt FROM positions WHERE source_id='aisstream'
                 AND imo IS NOT NULL GROUP BY imo) last
             ON p.imo=last.imo AND p.timestamp=last.mt AND p.source_id='aisstream'
           JOIN risk_scores s ON s.imo=p.imo
           GROUP BY p.imo""").fetchall()

    # vessels we cannot really assess: no build year AND not on any list
    built = {x["imo"] for x in conn.execute(
        "SELECT DISTINCT imo FROM facts WHERE field='built_year' AND value IS NOT NULL")}
    listed = {x["imo"] for x in conn.execute("SELECT DISTINCT imo FROM list_membership")}

    m = folium.Map(location=[58.0, 18.0], zoom_start=5, tiles="cartodbpositron")
    # separate cluster per band so high-risk stays visible; grey = insufficient data
    clusters = {b: MarkerCluster(name=f"{b}").add_to(m)
                for b in ("high", "elevated", "low", "insufficient")}
    counts = {b: 0 for b in clusters}
    for r in rows:
        imo = r["imo"]
        insufficient = imo not in built and imo not in listed
        key = "insufficient" if insufficient else r["band"]
        if key not in clusters:
            continue
        color = BAND_COLOR[key]
        popup = folium.Popup(evidence_html(conn, imo, descr, insufficient), max_width=360)
        folium.CircleMarker(
            location=[r["lat"], r["lon"]], radius=5,
            color=color, fill=True, fill_color=color, fill_opacity=0.8,
            popup=popup,
            tooltip=f"IMO {imo} — {key} ({r['total_score']})",
        ).add_to(clusters[key])
        counts[key] += 1

    legend = ("<div style='position:fixed;bottom:20px;left:20px;z-index:9999;background:white;"
              "padding:8px;border:1px solid #999;font-family:sans-serif;font-size:12px'>"
              "<b>Risk band</b><br>"
              "<span style='color:red'>&#9679;</span> high<br>"
              "<span style='color:orange'>&#9679;</span> elevated<br>"
              "<span style='color:green'>&#9679;</span> low (assessed)<br>"
              "<span style='color:gray'>&#9679;</span> insufficient data<br>"
              "<i>click a vessel for its evidence sheet</i></div>")
    m.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl().add_to(m)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT))
    return counts


def main():
    conn = db.connect()
    counts = build(conn)
    print("Map written to:", OUT)
    print("Vessels plotted by band:", counts)
    print(f"\nOpen it in your browser:\n  start {OUT}")


if __name__ == "__main__":
    main()
