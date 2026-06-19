"""
map_report.py — M6: a local map of the region with vessels coloured by risk band.
Clicking a vessel opens its evidence sheet (every current fact with its source URL
and retrieved_at, plus the inferences that fired), with facts and inferences
visually separated.

Plots vessels that have BOTH a last-known AIS position and a risk score. Output is
a single self-contained HTML file (exports/map.html) — open it in a browser.

Robustness: uses plain Leaflet layers (no MarkerCluster plugin) and OpenStreetMap
tiles, and strips control characters from popup content, so one odd value can't
break the whole page's JavaScript. The initial view is fitted to the AIS bounding
boxes from config/geofences.yaml (the area we actually monitor), which are also
drawn faintly.

Colours: red high, orange elevated, green low (assessed), grey insufficient data
(scored low only because we have no build year and no list membership — absence of
evidence, not a safety judgement).
"""

import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import folium
import yaml

import db
from identity import group_identity_history, current_value, display_name

OUT = Path(__file__).resolve().parents[2] / "exports" / "map.html"
RULES = Path(__file__).resolve().parents[2] / "rules.yaml"
GEOFENCES = Path(__file__).resolve().parents[2] / "config" / "geofences.yaml"
BAND_COLOR = {"high": "red", "elevated": "orange", "low": "green",
              "insufficient": "gray", "assist": "blue"}
# SAR / military / law-enforcement: shown as blue dots with a tiny popup only —
# they are response/assist vessels, not environmental-risk subjects, so they get
# no score sheet (only their presence + type matters when something happens).
ASSIST_TYPES = {"sar", "military", "law_enforcement"}


def esc(s):
    """HTML-escape and strip control chars so no popup can break the page JS."""
    return html.escape(re.sub(r"[\x00-\x1f\x7f]", " ", str(s)))


def rule_descr():
    return {x["id"]: x["description"] for x in
            yaml.safe_load(RULES.read_text(encoding="utf-8"))["rules"]}


def ais_bounds():
    """[[lat_min, lon_min], [lat_max, lon_max]] union of the AIS bounding boxes,
    plus the individual boxes for drawing."""
    boxes = yaml.safe_load(GEOFENCES.read_text(encoding="utf-8"))["bounding_boxes"]
    lat_min = min(b["lat_min"] for b in boxes.values())
    lat_max = max(b["lat_max"] for b in boxes.values())
    lon_min = min(b["lon_min"] for b in boxes.values())
    lon_max = max(b["lon_max"] for b in boxes.values())
    return [[lat_min, lon_min], [lat_max, lon_max]], boxes


def vessel_name(conn, imo):
    rows = conn.execute("SELECT value, origin_dataset, first_seen, last_seen FROM identity_history "
                        "WHERE imo=? AND field='name'", (imo,)).fetchall()
    cur = current_value(group_identity_history(rows, "name")) if rows else None
    return display_name(cur) if cur else ""


def vessel_type(conn, imo, fallback=None):
    """Latest registry vessel_type fact; else the AIS type category; else 'unknown'."""
    vt = conn.execute("SELECT value FROM facts WHERE imo=? AND field='vessel_type' "
                      "AND value IS NOT NULL ORDER BY retrieved_at DESC LIMIT 1", (imo,)).fetchone()
    return vt["value"] if vt else (fallback or "unknown")


def evidence_html(conn, imo, descr, insufficient=False):
    sc = conn.execute("SELECT total_score, band FROM risk_scores WHERE imo=?", (imo,)).fetchone()
    name = esc(vessel_name(conn, imo) or "(name unknown)")
    band = sc["band"] if sc else "?"
    score = sc["total_score"] if sc else "?"
    if insufficient:
        color, label = "gray", "INSUFFICIENT DATA"
    else:
        color, label = BAND_COLOR.get(band, "gray"), esc(str(band)).upper()

    vtype = esc(vessel_type(conn, imo))

    parts = [
        "<div style='font-family:sans-serif;font-size:12px;max-height:340px;overflow:auto'>",
        # sticky header — IMO / name / type stay pinned while the sheet scrolls
        "<div style='position:sticky;top:0;background:#ffffff;z-index:3;"
        "padding:2px 0 5px;border-bottom:2px solid #888'>"
        f"<div style='font-size:14px'><b>IMO {esc(imo)}</b></div>"
        f"<div style='font-size:13px'><b>{name}</b></div>"
        f"<div>Type: {vtype}</div>"
        f"<div>Risk score <b>{esc(score)}</b> &nbsp;"
        f"<span style='background:{color};color:white;padding:1px 6px;border-radius:3px'>"
        f"{label}</span></div>"
        "</div>",
    ]
    if insufficient:
        parts.append("<div style='color:#666;margin-top:3px'><i>Low score reflects "
                     "MISSING DATA (no build year and not on any list), not a safety "
                     "assessment.</i></div>")

    facts = db.current_profile(conn, imo)
    parts.append("<div style='margin-top:6px;background:#e8f0fe;padding:3px 5px;"
                 "font-weight:bold'>FACTS (source-reported)</div>")
    if facts:
        parts.append("<table style='border-collapse:collapse;width:100%'>")
        for f in facts:
            val = esc(f["value"]) if f["value"] is not None else "(unknown)"
            src = esc(f["source_id"] or "")
            url = esc(f["source_url"] or "")
            ret = esc((f["retrieved_at"] or "")[:10])
            link = f"<a href='{url}' target='_blank'>{src}</a>" if url else src
            parts.append(
                f"<tr><td style='color:#555;padding-right:6px'>{esc(f['field'])}</td>"
                f"<td><b>{val}</b></td><td style='padding-left:6px'>{link} <i>{ret}</i></td></tr>")
        parts.append("</table>")
    else:
        parts.append("<i>no facts stored</i>")

    flags = conn.execute("SELECT rule_id, weight, evidence FROM risk_flags "
                         "WHERE imo=? AND triggered=1 ORDER BY weight DESC", (imo,)).fetchall()
    parts.append("<div style='margin-top:6px;background:#fde8e8;padding:3px 5px;"
                 "font-weight:bold'>INFERENCES (computed — risk rules that fired)</div>")
    if flags:
        parts.append("<table style='border-collapse:collapse;width:100%'>")
        for fl in flags:
            ev = json.loads(fl["evidence"])
            ev_short = esc(", ".join(f"{k}={v}" for k, v in ev.items()
                                     if k in ("age", "built_year", "lists", "current_flag",
                                              "new_values", "reason", "declared_destination"))[:120])
            parts.append(
                f"<tr><td><b>{esc(fl['rule_id'])}</b> +{esc(fl['weight'])}</td>"
                f"<td style='padding-left:4px'>{esc(descr.get(fl['rule_id'],''))[:46]}"
                f"<br><span style='color:#777'>{ev_short}</span></td></tr>")
        parts.append("</table>")
    else:
        parts.append("<i>no risk rules fired</i>")

    parts.append("</div>")
    return "".join(parts)


def mini_popup(text):
    return folium.Popup(f"<div style='font-family:sans-serif;font-size:12px'>{text}</div>",
                        max_width=240)


def build(conn):
    descr = rule_descr()
    bounds, boxes = ais_bounds()
    built = {x["imo"] for x in conn.execute(
        "SELECT DISTINCT imo FROM facts WHERE field='built_year' AND value IS NOT NULL")}
    listed = {x["imo"] for x in conn.execute("SELECT DISTINCT imo FROM list_membership")}

    rows = conn.execute(
        """SELECT p.imo, p.lat, p.lon, p.type_category, s.band, s.total_score
           FROM positions p
           JOIN (SELECT imo, MAX(timestamp) mt FROM positions WHERE source_id='aisstream'
                 AND imo IS NOT NULL GROUP BY imo) last
             ON p.imo=last.imo AND p.timestamp=last.mt AND p.source_id='aisstream'
           JOIN risk_scores s ON s.imo=p.imo
           GROUP BY p.imo""").fetchall()

    m = folium.Map(tiles="OpenStreetMap", zoom_control=True)
    m.fit_bounds(bounds)                          # open fitted to the AIS monitoring area

    # the monitored bounding boxes as thin orange rectangles
    for name, b in boxes.items():
        folium.Rectangle([[b["lat_min"], b["lon_min"]], [b["lat_max"], b["lon_max"]]],
                         color="orange", weight=1, fill=False,
                         tooltip=f"AIS zone: {name}").add_to(m)

    groups = {k: folium.FeatureGroup(name=k, show=True).add_to(m)
              for k in ("high", "elevated", "low", "insufficient", "assist")}
    counts = {k: 0 for k in groups}

    for r in rows:
        imo = r["imo"]
        name = esc(vessel_name(conn, imo) or "")
        tcat = r["type_category"]
        # classify how to DISPLAY this vessel (assist type overrides everything)
        if tcat in ASSIST_TYPES:
            key = "assist"
            popup = mini_popup(f"<b>IMO {esc(imo)}</b> {name}<br>Type: {esc(tcat)}"
                               "<br><i>response/assist vessel — not scored for environmental risk</i>")
        elif imo not in built and imo not in listed:
            key = "insufficient"
            vtype = esc(vessel_type(conn, imo, r["type_category"]))
            popup = mini_popup(f"<b>IMO {esc(imo)}</b><br>{name or '(name unknown)'}<br>"
                               f"Type: {vtype}<br>Score: <i>insufficient information available</i>")
        elif r["band"] in ("high", "elevated"):
            key = r["band"]
            popup = folium.Popup(evidence_html(conn, imo, descr, False), max_width=360)
        else:  # low, assessed
            key = "low"
            vtype = esc(vessel_type(conn, imo, r["type_category"]))
            popup = mini_popup(f"<b>IMO {esc(imo)}</b><br>{name}<br>Type: {vtype}<br>"
                               f"score {esc(r['total_score'])} — <i>no increased environmental risk</i>")
        color = BAND_COLOR[key]
        radius = 3 if key == "assist" else 5   # assist vessels are less important -> smaller
        folium.CircleMarker(
            location=[r["lat"], r["lon"]], radius=radius,
            color=color, fill=True, fill_color=color, fill_opacity=0.8,
            popup=popup, tooltip=f"IMO {imo} — {key}",
        ).add_to(groups[key])
        counts[key] += 1

    legend = ("<div style='position:fixed;bottom:20px;left:20px;z-index:9999;background:white;"
              "padding:8px;border:1px solid #999;font-family:sans-serif;font-size:12px'>"
              "<b>Vessel marker</b><br>"
              "<span style='color:red'>&#9679;</span> high risk (full sheet)<br>"
              "<span style='color:orange'>&#9679;</span> elevated (full sheet)<br>"
              "<span style='color:green'>&#9679;</span> low — no increased risk<br>"
              "<span style='color:gray'>&#9679;</span> limited information<br>"
              "<span style='color:blue'>&#9679;</span> SAR / military / police (assist)<br>"
              "<i>click a red/orange vessel for its evidence sheet</i></div>")
    m.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl(collapsed=False).add_to(m)
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
