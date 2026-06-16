# CLAUDE.md — Baltic & North Sea Environmental-Risk Vessel Register

You are helping build a **reliable, fully-sourced register of high-risk tankers**
transiting the Baltic Sea, the Danish Straits and the North Sea, scored on
**environmental and safety grounds** (not on sanctions status alone). The person
directing you is **not a professional programmer** — they have basic Python.
Explain what you are doing in plain language, and tell them exactly what to run.

## The mission in one sentence
Make high-risk shipping more visible using only verifiable, traceable public data,
so the output can be cited by journalists, NGOs and officials without fear of error.

## Non-negotiable rules (do not violate these, ever)

1. **Provenance on every datum.** No value enters the database without a source.
   Every stored fact must carry: the value, a `source_id`, the `source_url` or API
   endpoint it came from, and a `retrieved_at` UTC timestamp. If you cannot attach a
   source, do not store the value — store `NULL` and mark the field `unknown`.

2. **No invented data. No hallucinated facts. Ever.** If a source is missing,
   unavailable, or ambiguous, say so and leave the field empty. Never fill a gap
   with a plausible guess. Never estimate a vessel's age, flag, owner or position
   from "general knowledge." Real source or nothing.

3. **The LLM is not in the runtime fact path.** You (Claude) write the pipeline code.
   The *running program* must not call any language model to produce facts about
   specific vessels. All facts come from deterministic connectors to real data
   sources. (If we ever add LLM-assisted summarising, it may only summarise records
   already retrieved and must cite their `source_id` — never free-generate.)

4. **Facts and inferences are different things, stored differently.**
   - A **fact** is something a source reports: "built 2004 (source: Equasis)",
     "AIS position at 57.1N, 18.4E at 2026-06-15T08:00Z (source: aisstream)".
   - An **inference** is something we computed: "called at Ust-Luga (inferred from
     position history)", "risk band: high (computed from rules)".
   Inferences live only in the `port_calls` and `risk_flags`/`risk_scores` tables,
   and every inference must reference the underlying facts/positions it was built
   from. The user interface must show facts and inferences as visibly distinct.

5. **Report behaviour, not intent.** State what a vessel *did* ("called at port X on
   date Y per AIS"). Never assert in stored data or UI that a company or port "is
   complicit," "collaborates with sanctions evasion," or knows anything. That is a
   legal liability and not something our data can prove. Let users draw conclusions.

6. **Respect terms of service and the law.**
   - Allowed: OpenSanctions API/bulk data (free for non-commercial), the official
     EU consolidated sanctions list, KSE and GUR public lists, aisstream.io free AIS.
   - Do **not** scrape VesselFinder, MarineTraffic, Kpler, or any site whose ToS
     forbids automated access. If a data need can only be met by scraping a
     ToS-protected site, stop and tell the user — do not do it.
   - Treat Equasis carefully: respect its terms; prefer manual/respectful access.

7. **Every risk score is transparent and explainable.** No black-box scoring.
   The score is a sum of explicit, documented rules read from a config file. Any
   score the program shows must be expandable into "flagged because: rule R3 (flag
   changed within 12 months) [evidence: fact #1234, source …]".

## Engineering conventions
- Language: Python 3. Keep dependencies minimal and well-known (e.g. `requests`,
  `websockets`, `pandas` or `duckdb`/`sqlite3`, `folium` for the map). Avoid exotic
  libraries.
- Storage: a single local SQLite (or DuckDB) file. No cloud, no external database.
- Secrets: API keys come from a `.env` file (use `python-dotenv`). Never hard-code
  a key. Never commit `.env`. Add it to `.gitignore`.
- After each milestone: write a short README note on what was built, add a couple of
  simple tests, and `git commit` with a clear message.
- Time: store all timestamps in UTC, ISO-8601.
- When you finish a task, **show the user 2–3 real example records and the exact
  source URL + timestamp for each field**, so they can spot-check against the live
  source. If you cannot show provenance for a result, the task is not done.

## What to do at the start of every session
Read this file and `PROJECT_BRIEF.md`. If anything conflicts or is ambiguous, ask
before writing code. Prefer small, verifiable steps over large leaps.

## Tone with the user
They are smart but not a programmer. Before asking them to run anything, say what it
does and what they should expect to see. If something fails, give them the exact
command to copy, not a paragraph of theory.
