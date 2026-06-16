# Getting-started pack — Baltic & North Sea Environmental-Risk Register

This file has three parts:
1. One-time setup (things you do before opening Claude Code)
2. The project brief (the design Claude Code should follow — data model, risk rules, sources)
3. The milestone prompts (paste these into Claude Code one at a time, in order)

Keep this file and `CLAUDE.md` together in your project folder.

---

## PART 1 — One-time setup

You only do this once. None of it is "real" programming — it's installing tools and
getting keys.

### 1.1 Install Claude Code
The friendliest option for a non-programmer is the **native installer** (no Node.js
needed) or the **Claude desktop app**, which lets you use Claude Code without the
terminal. Check the official instructions and pick one:
- Official docs: https://docs.claude.com/en/docs/claude-code/overview
- Native installer (macOS/Linux): run `curl -fsSL https://claude.ai/install.sh | bash`
- Windows (PowerShell): `irm https://claude.ai/install.ps1 | iex`
- (Alternative: if you prefer npm and have Node.js 18+, `npm install -g @anthropic-ai/claude-code`. Do not use `sudo`.)

You will need a paid Claude/Anthropic account to use it. If anything is unclear,
the desktop app route avoids the terminal almost entirely.

### 1.2 Make a project folder
Create an empty folder, e.g. `baltic-risk-register`. Put `CLAUDE.md` and this
`PROJECT_BRIEF.md` inside it. Open Claude Code "in" that folder (the docs show how;
in the desktop app you pick the folder).

### 1.3 Get your free API keys (register before the session)
- **OpenSanctions**: register at https://www.opensanctions.org/api/ — free for
  non-commercial use. Copy your API key somewhere safe.
- **aisstream.io**: sign in at https://aisstream.io/ (GitHub login) and create a free
  API key for live AIS.
- (Optional later) **Equasis**: free account at https://www.equasis.org — used
  manually for ship particulars; respect its terms.

You will NOT paste these keys into chat. Claude Code will set up a `.env` file and you
paste them into that file once.

### 1.4 Get the starting vessel lists
- Keep the sanctionsmap.eu PDF you already have (a fallback reference).
- The official EU consolidated list (machine-readable) is far better than the PDF —
  Claude Code will fetch it.
- The KSE shadow-fleet list and the Ukrainian GUR catalogue (war-sanctions.gur.gov.ua)
  are public references Claude Code will pull in.

That's the whole setup. Everything below is done *by Claude Code* while you direct it.

---

## PART 2 — Project brief (the design Claude Code follows)

### 2.1 What we are building
A locally-run program that maintains a database of tankers in the Baltic/North Sea
region, scores each on environmental and safety risk using transparent rules, shows
them on a map, and produces a per-vessel "evidence sheet" where every single fact
links back to its source and the time it was retrieved. It also flags where the
different sanction/shadow-fleet lists disagree with each other.

### 2.2 Geographic scope (approximate — Claude Code can refine)
- Baltic Sea: roughly latitude 53.5–66, longitude 9–30
- Danish Straits (key chokepoint): roughly latitude 54.5–58, longitude 9.5–13
- North Sea: roughly latitude 51–61, longitude -4–9
aisstream.io accepts bounding boxes, so we subscribe to these regions plus our
specific watch-list of IMO/MMSI numbers.

### 2.3 The data model (the heart of the "no hallucination" design)
The key idea: store facts in a normalised **facts table** so every value is traceable.

- `sources` — one row per data source.
  Columns: `source_id`, `name`, `type` (sanctions / list / registry / psc / ais),
  `url`, `license`, `accessed_at`.

- `facts` — one row per (vessel, field, value). This is the core table.
  Columns: `imo`, `field` (e.g. `built_year`, `flag`, `name`, `insurer`,
  `vessel_type`), `value`, `source_id`, `source_url`, `retrieved_at`.
  → Every fact is independently traceable. A "vessel profile" is just a query that
  gathers the latest fact per field, each still carrying its source.

- `positions` — AIS pings.
  Columns: `imo`, `mmsi`, `lat`, `lon`, `sog` (speed), `cog` (course),
  `nav_status`, `timestamp`, `source_id`.

- `list_membership` — which lists include a vessel (for reconciliation).
  Columns: `imo`, `list_name` (EU / OpenSanctions / KSE / GUR / UK / OFAC),
  `present` (true/false), `as_of`, `source_url`.

- `port_calls` — INFERRED. Columns: `imo`, `port`, `country`, `arrival`,
  `departure`, `method_note` (how it was inferred), `evidence` (refs to positions).

- `risk_flags` — INFERRED. Columns: `imo`, `rule_id`, `triggered` (true/false),
  `evidence` (refs to facts/positions), `weight`, `evaluated_at`.

- `risk_scores` — INFERRED, recomputable. Columns: `imo`, `total_score`, `band`,
  `computed_at`.

### 2.4 The risk-scoring rules (transparent, stored in a config file)
Weights below are a **starting point** — illustrative, to be calibrated. They live in
a `rules.yaml` (or `.json`) file so anyone can read and adjust them. The environmental
framing is deliberate: an old, uninsured tanker scores high whether or not it is
sanctioned.

| Rule | Condition | Weight |
|------|-----------|--------|
| R1 | Vessel age over 20 years | +3 |
| R1b | Vessel age 15–20 years | +2 |
| R2 | No recognised International Group P&I insurer / unknown insurer | +3 |
| R3 | Flag changed within last 12 months | +2 |
| R4 | Name changed within last 12 months | +1 |
| R5 | Flag is a high flag-of-convenience-risk flag | +1 |
| R6 | Paris MoU (or other PSC) detention in last 24 months | +2 |
| R7 | AIS gap over N hours while inside a monitored zone | +2 |
| R8 | Recent call at a Russian oil terminal (Primorsk, Ust-Luga, Novorossiysk, Kozmino) | +2 |
| R9 | Loitering pattern consistent with ship-to-ship transfer | +2 |
| R10 | Listed by EU / OFAC / UK / KSE / GUR | +3 |

Bands (illustrative): 0–3 low, 4–7 elevated, 8+ high. Every score must be expandable
into the list of rules that fired and the evidence behind each. Document the source of
each rule's data (e.g. R6 from Paris MoU records, R1 from Equasis build year).

### 2.5 Data sources (and how to treat them)
- **OpenSanctions** (API + bulk CSV/JSON): sanctions, IMO numbers, "shadow fleet" tag,
  AND Port State Control detention lists (Paris/Tokyo/Black Sea MoU). Backbone. Free
  non-commercial.
- **Official EU consolidated sanctions list**: primary sanctions, machine-readable.
- **KSE shadow-fleet list**: the de facto reference set (cite as analytical source).
- **Ukrainian GUR catalogue**: public shadow-fleet/sanctioned vessels.
- **aisstream.io**: free live AIS via websocket. The position source.
- **Equasis**: ship particulars (age, flag, class, history) — manual/respectful use.
- **Forbidden**: scraping VesselFinder, MarineTraffic, Kpler, or any ToS-protected site.

### 2.6 Honest limitations to keep visible in the product
- AIS can be spoofed by the very ships we watch, so a position is evidence, not proof;
  gaps and impossible jumps are themselves signals, stored with low confidence.
- Ownership is deliberately opaque; we report what public data shows and mark the rest
  unknown.
- The lists disagree; we surface the disagreement rather than picking a "truth."
- "Pattern, not a verdict" — the tool informs human judgement, it does not accuse.

---

## PART 3 — Milestone prompts (paste one at a time, in order)

Run these in sequence. After each, do the **check** before moving on. If a check
fails, tell Claude Code what's wrong rather than continuing.

### M0 — Orientation (no code yet)
> Read CLAUDE.md and PROJECT_BRIEF.md in this folder. In plain language, summarise
> back to me the provenance contract and the data model in your own words, list any
> ambiguities or risks you see, and propose the project's file/folder structure.
> Do not write any code yet — wait for my go-ahead.

**Check:** Does its summary match the rules? Does it correctly say the LLM is not in
the runtime fact path? Resolve any ambiguity it raises before continuing.

### M1 — Sanctions & lists ingestion with provenance
> Set up the project: create the SQLite database with the schema from the brief, a
> `.env` for keys, and `.gitignore`. Then build a connector that pulls the EU
> consolidated sanctions list and the OpenSanctions maritime/vessel data, and writes
> each value into the `facts` table with its source_id, source_url and retrieved_at.
> Deduplicate vessels by IMO. Tell me exactly what to run and what I should see.

**Check:** Ask: "Show me 3 vessels and, for each field, the exact source URL and
timestamp." Spot-check one IMO against the live OpenSanctions website.

### M2 — Cross-source reconciliation
> Now ingest the KSE shadow-fleet list and the Ukrainian GUR catalogue into
> `list_membership`. Build a report that shows, per IMO, which lists include the
> vessel and where the lists disagree. Output it as a table I can read.

**Check:** Pick one vessel on KSE but not on the EU list (or vice versa) and confirm
the report flags the disagreement.

### M3 — Live AIS feed
> Connect to the aisstream.io websocket using my key from .env. Subscribe to the
> Baltic, Danish Straits and North Sea bounding boxes in the brief, plus our watch-list
> of IMO/MMSI numbers. Store incoming positions in the `positions` table with
> timestamps and source_id. Run it for a few minutes and show me the last-known
> position for 5 vessels.

**Check:** Are positions arriving with real timestamps? Does one match what a public
tracker shows for the same ship right now (rough sanity check only)?

### M4 — Port calls & Russian terminals
> From the position history, infer port calls (a vessel inside a port zone at low
> speed for a sustained period). Flag calls at Russian oil terminals (Primorsk,
> Ust-Luga, Novorossiysk, Kozmino). Store these in `port_calls` as inferences with a
> method note and references to the positions used. Show me recent Russian-terminal
> calls with their evidence.

**Check:** For one flagged call, can it show the positions that triggered it?

### M5 — The transparent risk engine
> Implement the risk-scoring engine. Read the weights from `rules.yaml` matching the
> table in the brief. Compute a score and band per vessel, storing each fired rule in
> `risk_flags` with its evidence. Show me one vessel's score fully broken down into
> the rules that fired and the source behind each.

**Check:** Does every point in the score trace to a rule and a sourced fact? Change a
weight in `rules.yaml`, re-run, and confirm the score changes accordingly.

### M6 — Map & evidence sheets
> Build a local map (folium/Leaflet) of the region, with vessels coloured by risk
> band. Clicking a vessel opens an "evidence sheet" listing every fact, its source URL
> and retrieved_at, with facts and inferences visually separated. Tell me how to open
> it in my browser.

**Check:** Open it, click a high-risk vessel, and confirm each claim links to a source.
Confirm facts and inferences look clearly different.

### M7 — Sourced export & refresh
> Add a CSV and JSON export where every field has accompanying source and retrieved_at
> columns. Add a single refresh script that updates sanctions/lists and pulls fresh
> AIS, and a short README explaining how to run everything. Commit to git.

**Check:** Open the CSV in a spreadsheet — is there a source and timestamp next to each
fact? Could a journalist verify a row from it alone?

---

## How to verify Claude Code without being a programmer
- The magic question after every milestone: **"Show me 3 real examples and the exact
  source URL and timestamp for each field."** If it can't, the step isn't done.
- Pick one example and open the source website yourself to confirm it's real.
- If Claude Code ever shows data without a source, stop and remind it of rule #2.
- Commit after every working milestone so you can always go back.
