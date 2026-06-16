# Baltic & North Sea Environmental-Risk Vessel Register

A locally-run program that maintains a **fully-sourced** database of tankers in the
Baltic Sea, Danish Straits and North Sea, scores them on environmental and safety
risk using transparent rules, and produces per-vessel evidence sheets where every
fact links back to its source. See `CLAUDE.md` and `PROJECT_BRIEF.md` for the full
design and the non-negotiable provenance rules.

## What's built so far

**M1 (in progress) — project foundation**
- `src/db.py` — the SQLite schema (sources, facts, positions, list_membership,
  port_calls, risk_flags, risk_scores). The `facts` table is append-only so a
  vessel's identity history (renames, reflagging) is preserved.
- `src/provenance.py` — the **provenance gate**: the only sanctioned way to write a
  fact. It refuses any value lacking a source_id, source_url, and a valid UTC
  timestamp. "Unknown" is recorded with a real source, never guessed.
- `rules.yaml` — the transparent risk rules (R1–R10) and score bands.
- `config/geofences.yaml` — region bounding boxes and Russian oil terminals.
- `tests/test_provenance.py` — proves sourceless data is refused.

_Still to come in M1: the OpenSanctions and EU consolidated-list connectors that
populate the facts table. These will be added once Python is installed so their
output can be verified against the live sources (per the project's rule that every
result must be spot-checkable)._

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

Run the provenance tests:
```
py tests/test_provenance.py
```

## Data sources

| Source | Role | Notes |
|---|---|---|
| OpenSanctions | Backbone: sanctions, KSE, PSC detentions | Free non-commercial; API key in `.env` |
| EU consolidated sanctions list | Primary official sanctions | Machine-readable |
| KSE shadow-fleet list | Analytical reference | Accessed via OpenSanctions; cited to original KSE report |
| Ukrainian GUR catalogue | Shadow-fleet reference | Polite one-time crawl; no bulk API |
| aisstream.io | Live AIS positions | Used from M3 |
| Equasis | Ship particulars | Set aside for now; manual/respectful use if added later |
