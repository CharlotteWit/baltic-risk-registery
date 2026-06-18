# Baltic & North Sea Environmental-Risk Vessel Register

A locally-run program that maintains a **fully-sourced** database of tankers in the
Baltic Sea, Danish Straits and North Sea, scores them on environmental and safety
risk using transparent rules, and produces per-vessel evidence sheets where every
fact links back to its source. See `CLAUDE.md` and `PROJECT_BRIEF.md` for the full
design and the non-negotiable provenance rules.

## What's built so far

**M1 — sanctions/vessel ingestion with provenance (working)**
- `src/db.py` — the SQLite schema (sources, facts, positions, list_membership,
  port_calls, risk_flags, risk_scores, identity_history). The `facts` table is
  append-only so a vessel's identity history is preserved.
- `src/provenance.py` — the **provenance gate**: the only sanctioned way to write a
  fact. It refuses any value lacking a source_id, source_url, and a valid UTC
  timestamp. "Unknown" is recorded with a real source, never guessed.
- `src/connectors/opensanctions.py` — pulls the ~1,900 sanctioned VESSEL entities
  from the live OpenSanctions API and stores every value as a sourced fact. The
  `source_url` is the public OpenSanctions entity page (spot-checkable in a
  browser). Vessels with no usable IMO are skipped (not guessed); vessels with
  multiple/odd IMO numbers are flagged ("zombie IMO" anomaly).
- `src/connectors/opensanctions_history.py` — populates `identity_history` with
  DATED observations of each vessel's IMO/flag/name from the OpenSanctions
  `/statements` API. The dates (`first_seen`/`last_seen`) are the source's own.
- `src/identity.py` — change detection for IMO/flag/name. Treats case/spacing-only
  differences as the same value, so only **genuine** renames/reflaggings count as
  changes; raw values are always preserved verbatim.
- `rules.yaml` — the transparent risk rules (R1–R10) and score bands.
- `config/geofences.yaml` — region bounding boxes and Russian oil terminals.
- `tests/` — `test_provenance.py` (sourceless data is refused) and
  `test_identity.py` (casing variants are not false changes; real renames are caught).
- `scripts/show_vessel.py` — prints a vessel's facts + dated identity-change
  tracking, each value with its source URL and retrieval time.

_Still to come: the official EU consolidated-list connector (EU vessel sanctions
are already captured via OpenSanctions in the meantime, cited to the EU datasets)._

**M2 — cross-source reconciliation (working)**
- `src/report/reconcile.py` — shows, per IMO, which core authorities list a vessel
  (EU, OFAC, UK, GUR, UN) and surfaces the **disagreements** (e.g. 431 vessels are
  on GUR but not on the EU list). Prints a summary + sample tables and writes the
  full matrix to `exports/reconciliation.csv`. Includes IMO check-digit validation.
- GUR = OpenSanctions `ua_war_sanctions` (war-sanctions.gur.gov.ua), confirmed via
  the dataset's publisher URL. **KSE is not available via OpenSanctions** — its own
  connector is parked in `TODO.md`; the report states the gap rather than hiding it.
- `scripts/show_membership.py` — spot-check one vessel's list membership + sources.
- `tests/test_reconcile.py` — membership matrix and disagreement detection.

Run it:
```
py src/report/reconcile.py
py scripts/show_membership.py 8227238
```

### Which name/flag is "current"? (the naming rule)
A vessel often carries many names across the lists. We store **all** of them as
facts. The single operative name/flag shown to a user is **the latest known** —
the value with the most recent `first_seen` (when it first appeared in any list).
This usually reflects what the vessel is actually using now, because shadow-fleet
vessels rename to shed a flagged identity. It is treated as a **DERIVED inference**
(shown separately from facts), because `first_seen` is a proxy for the real rename
date. The real-time ground truth is the name broadcast over **AIS** (arrives in M3).

## Additional fact source: Wikidata (tertiary)

`src/connectors/wikidata.py` queries the Wikidata SPARQL endpoint by "IMO ship
number" (P458) for every IMO in our database and stores any build year, ship
type, owner/operator, gross tonnage and names it finds. It is registered as a
**tertiary, crowd-edited source (CC0), lower confidence** than OpenSanctions or
the EU list, and every Wikidata fact says so. Because `facts` is append-only, a
Wikidata value never overwrites a primary value — both are stored as dated rows,
so a reader can see where they agree or disagree. IMOs with no Wikidata item get
nothing written (left unknown). Wikidata has no deadweight property, so deadweight
is never set from this source. Wikidata is part of `src/refresh.py`.

```
py src/connectors/wikidata.py        # batch over all known IMOs
py scripts/show_wikidata.py 9175078  # show a vessel's Wikidata facts vs primary
```

## Early risk preview: rule R1 (vessel age > 20)

`src/age_risk.py` + `src/age_risk_monitor.py` are a working preview of the full
M5 risk engine — just one rule for now, applied continuously to vessels seen via
AIS. When a vessel is sighted (and passed the ship-type filter), if we have no
build year for its IMO from any source we query Wikidata for it; once a build
year is known, vessels over 20 years old get a `risk_flags` row (`rule_id='R1'`,
weight 3) whose evidence points to the exact build-year fact used. This is what
lets us flag old, high-risk vessels that are **not** on any sanction list.

```
py src/age_risk_monitor.py           # single pass; --loop to run continuously
py src/report/age_risk_report.py     # build-year coverage by source + R1 flags
```

## M4 — Port calls at Russian Baltic terminals

`src/inference/port_calls.py` infers port calls from AIS history: a vessel inside
a terminal's circular zone (`config/geofences.yaml`) at low speed (≤1 kn) for a
sustained run is recorded in `port_calls` as an inference, tagged by tier, with a
method note and the exact `position_id`s used.

- **R8a (major):** Primorsk, Ust-Luga
- **R8b (secondary):** Vysotsk, Vyborg, St. Petersburg (Great Port), Kaliningrad
- **R8c (external only):** Novorossiysk, Kozmino, Murmansk are outside our AIS
  coverage — never inferred from our positions. We only surface them from an
  external port-call fact, clearly marked `external-fact`. (We store no such
  facts yet, so R8c is currently empty — see `TODO.md`.)

```
py src/inference/port_calls.py    # disabled by default (see below); RUN_PORT_CALLS=1 to force
py scripts/diag_zones.py          # positions per zone (coverage check)
```

### Russian-terminal coverage limitation (important — we tried, and recorded why)

We built and verified the port-call detector, then tried to run it against live
AIS for all six terminals. It found **zero** calls — and we traced exactly why:
the **free aisstream (terrestrial-receiver) network has no coverage in Russian
coastal waters.** Across 52,000+ captured positions the **easternmost is ~26.85 E**,
while every terminal is further east (Ust-Luga 28.4, Primorsk 28.7, Vyborg/Vysotsk
~28.6, St. Petersburg 30.2); Kaliningrad has zero positions too. We briefly
extended the bounding box east to test this, confirmed the dead zone, and trimmed
`baltic_sea` `lon_max` back to **27.0** so we don't subscribe to waters that never
report.

This is a **data-source limitation, not a code bug.** The detector is unit-tested
(`tests/test_port_calls.py`) and demonstrably fires on real berthed vessels where
we *do* have coverage (e.g. Rotterdam, Gdynia, IJmuiden). Because detection at the
Russian terminals will always return 0 with this source, **AIS inference here is
disabled by default** (`AIS_INFERENCE_ENABLED = False` in `port_calls.py`); the
logic is **kept, not discarded**, in case a covered source (e.g. satellite AIS) is
added later. To see these terminals we would instead need satellite AIS (paid) or
external port-call facts — the R8c approach (see `TODO.md`).

## Eastbound transit & declared-destination cross-check (rule R8d)

The AIS connector now captures each vessel's self-declared **Destination** from
`ShipStaticData` and stores it as a dated fact (`ais_destination`) — what the
vessel *said*, never a verified call.

`src/inference/eastbound_transit.py` then looks for vessels that **leave our
coverage at the eastern edge** (last position near ~27 E, in the Gulf-of-Finland
latitude band, moving eastbound) and cross-checks the declared destination **by
direction**: a port *west* of the edge (Rotterdam, but also Kaliningrad, Helsinki,
Riga…) cannot be reached by exiting east. When the declaration is **contradicted**
(declared west, exited east) or **unknown/blank**, we record a low-confidence
inference — rule **R8d**, weight 1 — *"transited toward the eastern Gulf of Finland
(Russian/Finnish/Estonian ports) — not a confirmed call"*, alongside the declared
destination. A *consistent* eastern declaration (e.g. `RUULU`) needs no inference.

Honest framing, baked in:
- **"East" is not "Russia."** The eastern Gulf is shared with Finland (Kotka/
  Hamina) and Estonia (Sillamäe/Narva); we say "eastern Gulf", never "docked in
  Russia".
- **Low confidence** (weight 1, tunable in `rules.yaml`): AIS can be spoofed and an
  edge position may be transit, not a true exit.
- **Coverage:** the free AIS feed barely reaches the eastern edge, so real events
  are rare — but the declared-destination capture works everywhere.

```
py src/inference/eastbound_transit.py
```

## M5 — The transparent risk engine

`src/inference/risk_engine.py` reads the weights/bands from `rules.yaml`, evaluates
every rule per vessel against real stored evidence, writes each fired rule to
`risk_flags` (with the source behind it), and writes a total score + band to
`risk_scores`. Fully recomputable; change a weight in `rules.yaml`, re-run, and the
scores change (verified).

It is explicit about three states per rule — `triggered`, `not_triggered`,
`not_evaluated` — so a gap is never a silent zero.

**Active rules and weights (calibrated 2026-06-18):**
- **R1 age > 20 → 5**, **R1b age 15–20 → 3** — age weighs highest (an old hull is
  the core spill risk on its own, sanctioned or not).
- **R6 PSC detention/ban → 2** — these ships were actually inspected and detained.
- **R3 flag change, R4 name change, R5 FoC flag, R10 sanctions listing → 1 each**
  — context all pointing to the same shadow-fleet scenario.
- **R8d eastbound transit → 1** (low confidence; rarely fires — coverage).

**Removed** (cannot evaluate with our data, so deleted rather than silently zeroed):
R2 (no insurer data), R7 (AIS gaps — uncollectable), R8 (Russian-terminal calls —
no AIS coverage), R9 (loitering — not reliably definable).

```
py src/inference/risk_engine.py    # score everyone + show the top vessel's breakdown
```

_Caution when reading bands: a score of 0 can mean "evaluated and low" OR "we have
almost no data" — absence of evidence is not low risk. ~2,569 scored vessels are
AIS-discovered with no age and no listing, so their score-0 is really
"insufficient data" (a dedicated band for this is still open for decision)._

_M5 part 2 (size-distribution analysis to decide a minimum-size rule) is still to
do — it needs AIS `Dimension` capture, not yet implemented._

## M6 — Map & evidence sheets

`src/report/map_report.py` builds a local Leaflet map (`exports/map.html`) of
vessels that have both a last-known AIS position and a risk score, coloured by
band (red = high, orange = elevated, green = low) and clustered per band. Clicking
a vessel opens its evidence sheet in the popup, with two clearly separated
sections. Colours: **red** high, **orange** elevated, **green** low *(assessed —
we have age and/or list data and it's low)*, **grey** *insufficient data* (scored
low ONLY because we have no build year and no list membership — absence of
evidence, not a safety judgement). Sections:
- **FACTS (source-reported)** — current value per field, each with a clickable
  link to its source and the retrieval date.
- **INFERENCES (computed)** — the risk rules that fired, their weight and evidence.

```
py src/report/map_report.py
start exports\map.html        # opens in your browser (Windows)
```

(The generated `exports/map.html` is gitignored — rebuild it from the DB anytime.)

This project tracks vessels that could pose an **environmental threat to the
Baltic and North Sea**. The live AIS feed (M3) therefore keeps:

- **All tankers** (AIS codes 80–89). We deliberately keep *every* tanker, not just
  crude-oil carriers — products, chemical and gas (LNG/LPG) cargoes can all be an
  environmental hazard if a vessel is old, poorly maintained or uninsured.
- **All cargo ships** (70–79), including bulk and general cargo.
- **Unknown / "other" / reserved types** (code 0, missing, and the miscellaneous
  ranges). We keep these for now rather than discarding them; a vessel can be
  triaged out later based on its size or registry data. Keeping them avoids
  throwing away something that might matter.
- **Military, noncombatant, law-enforcement and search-and-rescue vessels**
  (35, 51, 55, 59). We keep these not as risk subjects themselves but because they
  **may interact with vessels in trouble at sea** — responding to a breakdown,
  spill, collision or other incident. Their presence near a monitored vessel can
  be a useful contextual signal, which we may analyse later (see `TODO.md`).

It **drops** vessel types that are not relevant to this environmental-risk scope:
passenger ships/ferries, high-speed craft (40–49, dropped 2026-06-18), sailing and
pleasure craft, fishing vessels, tugs/towing, and port-service craft (pilots,
tenders, dredgers, etc.).

The selection is by behaviour and vessel category only. It is **not** an
assertion that any vessel or operator is doing anything wrongful — it simply
decides what to watch for potential environmental risk.

## Setup

1. **Install Python 3** (3.10+). On Windows, download from https://www.python.org/downloads/.
   On this machine, use the `py` launcher to run Python (plain `python` may hit the
   Windows Store stub).
2. Install dependencies:
   ```
   py -m pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and paste your API keys into it. `.env` is
   gitignored and must never be committed.

## How to run (so far)

Create the database and list its tables:
```
py src/db.py
```

Ingest sanctioned vessels (needs OPENSANCTIONS_API_KEY in `.env`):
```
py src/connectors/opensanctions.py            # vessel facts (~30s)
py src/connectors/opensanctions_history.py    # dated IMO/flag/name history (~6-8 min)
```

Show a vessel's evidence with sources and identity-change tracking:
```
py scripts/show_vessel.py 9288851
```

Run the tests:
```
py tests/test_provenance.py
py tests/test_identity.py
```

_Note: on Windows, prefix with `$env:PYTHONIOENCODING="utf-8"` if non-English
characters (e.g. French vessel-type text) show as `?` in the console — the stored
data is UTF-8 regardless; it's only a console display issue._

## Data sources

| Source | Role | Notes |
|---|---|---|
| OpenSanctions | Backbone: sanctions, KSE, PSC detentions | Free non-commercial; API key in `.env` |
| EU consolidated sanctions list | Primary official sanctions | Machine-readable |
| KSE shadow-fleet list | Analytical reference | Accessed via OpenSanctions; cited to original KSE report |
| Ukrainian GUR catalogue | Shadow-fleet reference | Polite one-time crawl; no bulk API |
| aisstream.io | Live AIS positions | Used from M3 |
| Equasis | Ship particulars | Set aside for now; manual/respectful use if added later |
