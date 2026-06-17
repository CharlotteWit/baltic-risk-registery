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
