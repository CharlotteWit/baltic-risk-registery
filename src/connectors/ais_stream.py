"""
ais_stream.py — M3 live AIS feed from aisstream.io (free websocket), filtered by
AIS ship type.

Connects to aisstream.io, subscribes to the Baltic / Danish Straits / North Sea
bounding boxes from config/geofences.yaml, and stores incoming PositionReport
messages in the `positions` table with their UTC timestamp and source_id.

Ship-type filtering (per M3 brief + user's selection, see ais_types.py / README):
* We also subscribe to ShipStaticData messages, which carry the AIS ship-type
  code and the broadcast IMO. From these we learn each MMSI's category. We KEEP
  tankers, cargo, unknown/other, high-speed craft, and military/law-enforcement/
  SAR (kept for proximity context). We DROP passenger, sailing, pleasure,
  fishing, tugs and port-service craft.
* Static data is broadcast less often than positions, so a ship's type may be
  unknown when its first positions arrive. Those are stored tagged 'unknown'
  (kept). At the end of the run we delete positions for any MMSI we have since
  learned is an excluded type — so the stored set stays clean.

Honesty notes:
* AIS is evidence, not proof (spoofing, gaps). We store what arrives, verbatim.
* AIS ship-type is coarse: it cannot distinguish crude vs chemical vs LNG tankers
  — that comes from registry data, not AIS.
* aisstream caps FiltersShipMMSI at 50, far below our ~1,900 watch-list, so we
  subscribe to the regions (no MMSI filter) and flag watch-list matches by
  MMSI/IMO. Tracking watch-list vessels OUTSIDE the regions would need batched
  subscriptions — deferred (see TODO.md).

API verified live 2026-06-17:
  PositionReport:  MetaData.{MMSI, time_utc}; Message.PositionReport.{Latitude,
                   Longitude, Sog, Cog, NavigationalStatus}
  ShipStaticData:  Message.ShipStaticData.{Type, ImoNumber, Name}
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets
import yaml
from dotenv import load_dotenv

import db
from provenance import utc_now_iso
from ais_types import category_for_type, should_store, EXCLUDE_CATEGORIES

WS_URL = "wss://stream.aisstream.io/v0/stream"
SOURCE_ID = "aisstream"
GEOFENCES = Path(__file__).resolve().parents[2] / "config" / "geofences.yaml"


def load_boxes():
    cfg = yaml.safe_load(GEOFENCES.read_text(encoding="utf-8"))
    return [[[b["lat_min"], b["lon_min"]], [b["lat_max"], b["lon_max"]]]
            for b in cfg["bounding_boxes"].values()]


def load_watchlist(conn):
    """Build MMSI->IMO and the set of watch-list IMOs from stored facts."""
    mmsi_to_imo, imos = {}, set()
    for r in conn.execute("SELECT imo, value FROM facts WHERE field='mmsi' AND value IS NOT NULL"):
        mmsi_to_imo[str(r["value"]).strip()] = r["imo"]
    for r in conn.execute("SELECT DISTINCT imo FROM facts"):
        imos.add(r["imo"])
    return mmsi_to_imo, imos


def normalize_time(time_utc):
    """aisstream time '2026-06-17 07:28:50.957... +0000 UTC' -> ISO UTC string."""
    if isinstance(time_utc, str) and len(time_utc) >= 19:
        try:
            dt = datetime.strptime(time_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            pass
    return utc_now_iso()


async def run(conn, api_key, seconds, max_messages, progress_every=500):
    boxes = load_boxes()
    mmsi_to_imo, watch_imos = load_watchlist(conn)
    db.upsert_source(conn, SOURCE_ID, "aisstream.io", "ais", url="https://aisstream.io",
                     license="aisstream.io free tier (live AIS)", accessed_at=utc_now_iso())

    sub = {"APIKey": api_key, "BoundingBoxes": boxes,
           "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}

    mmsi_cat, mmsi_code = {}, {}          # learned from ShipStaticData
    stats = {"received": 0, "stored": 0, "dropped_type": 0, "static_seen": 0,
             "watchlist_hits": 0, "distinct_mmsi": set()}
    start = time.monotonic()
    print(f"Connecting to aisstream; listening {seconds}s over {len(boxes)} regions "
          f"(watch-list: {len(watch_imos)} IMOs)...", flush=True)

    async with websockets.connect(WS_URL, max_size=None) as ws:
        await ws.send(json.dumps(sub))
        while time.monotonic() - start <= seconds and stats["stored"] < max_messages:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            stats["received"] += 1
            mt = msg.get("MessageType")
            meta = msg.get("MetaData", {})
            mmsi = str(meta.get("MMSI", "")).strip()

            if mt == "ShipStaticData":
                stats["static_seen"] += 1
                sd = msg.get("Message", {}).get("ShipStaticData", {})
                mmsi_cat[mmsi] = category_for_type(sd.get("Type"))
                mmsi_code[mmsi] = sd.get("Type")
                imo = str(sd.get("ImoNumber") or "").strip()
                if imo in watch_imos and mmsi not in mmsi_to_imo:
                    mmsi_to_imo[mmsi] = imo       # learn MMSI<->IMO from AIS itself
                continue

            if mt != "PositionReport":
                continue
            pr = msg.get("Message", {}).get("PositionReport", {})
            lat, lon = pr.get("Latitude"), pr.get("Longitude")
            if lat is None or lon is None:
                continue
            category = mmsi_cat.get(mmsi, "unknown")
            if not should_store(category):
                stats["dropped_type"] += 1
                continue
            imo = mmsi_to_imo.get(mmsi)
            if imo:
                stats["watchlist_hits"] += 1
            stats["distinct_mmsi"].add(mmsi)
            conn.execute(
                """INSERT INTO positions (imo, mmsi, lat, lon, sog, cog, nav_status,
                       timestamp, source_id, confidence, ais_ship_type, type_category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', ?, ?)""",
                (imo, mmsi, lat, lon, pr.get("Sog"), pr.get("Cog"),
                 str(pr.get("NavigationalStatus")), normalize_time(meta.get("time_utc")),
                 SOURCE_ID, mmsi_code.get(mmsi), category))
            stats["stored"] += 1
            if stats["stored"] % progress_every == 0:
                conn.commit()
                print(f"  ...stored {stats['stored']} (dropped {stats['dropped_type']} by type, "
                      f"{stats['watchlist_hits']} watch-list hits)", flush=True)
    conn.commit()

    # Cleanup: drop positions for MMSIs we have since learned are excluded types
    # (they were stored as 'unknown' before their static data arrived).
    excluded_mmsi = [m for m, c in mmsi_cat.items() if c in EXCLUDE_CATEGORIES]
    removed = 0
    for m in excluded_mmsi:
        cur = conn.execute("DELETE FROM positions WHERE mmsi=? AND source_id=? AND "
                           "type_category='unknown'", (m, SOURCE_ID))
        removed += cur.rowcount
    conn.commit()
    stats["cleanup_removed"] = removed
    stats["distinct_mmsi"] = len(stats["distinct_mmsi"])
    return stats


def show_last_known(conn, n=5):
    print(f"\n--- Last-known position for up to {n} vessels (watch-list first) ---")
    rows = conn.execute(
        """SELECT p.* FROM positions p
           JOIN (SELECT mmsi, MAX(timestamp) mt FROM positions WHERE source_id=?
                 GROUP BY mmsi) last
             ON p.mmsi=last.mmsi AND p.timestamp=last.mt
           WHERE p.source_id=?
           ORDER BY (p.imo IS NULL), p.timestamp DESC LIMIT ?""",
        (SOURCE_ID, SOURCE_ID, n)).fetchall()
    for r in rows:
        tag = f"IMO {r['imo']} (watch-list)" if r["imo"] else "(not on watch-list)"
        code = r["ais_ship_type"] if r["ais_ship_type"] is not None else "n/a"
        print(f"  MMSI {r['mmsi']}  {tag}")
        print(f"      lat {r['lat']:.4f}, lon {r['lon']:.4f}  sog {r['sog']} kn  course {r['cog']}")
        print(f"      AIS ship-type code: {code}  ->  category: {r['type_category']}")
        print(f"      time {r['timestamp']}  source={r['source_id']}")


def main():
    load_dotenv()
    key = (os.getenv("AISSTREAM_API_KEY") or "").strip()
    if not key:
        sys.exit("No AISSTREAM_API_KEY found in .env — add it and retry.")
    seconds = int(os.getenv("AIS_SECONDS", "150"))
    max_messages = int(os.getenv("AIS_MAX", "20000"))
    conn = db.init_db()
    stats = asyncio.run(run(conn, key, seconds, max_messages))
    print("\nDone. Summary:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    show_last_known(conn)


if __name__ == "__main__":
    main()
