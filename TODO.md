# Deferred / parked items

Things we consciously put on hold. Revisit before calling the project "finished".
(Claude will remind the user about these at a natural checkpoint, e.g. once the
M-series milestones are complete.)

## Data sources to add
- [ ] **Official EU consolidated-list connector** — pull the EU's own
      machine-readable list directly (currently EU vessel sanctions are captured
      *via OpenSanctions*, cited to the EU datasets). Verify the live endpoint
      before coding; fall back to OpenSanctions if access is fiddly.
- [ ] **Equasis** — ship particulars (age, class, history). Manual/respectful
      use only; set aside for now, may add later.
- [ ] **Direct GUR crawl (fallback only)** — if OpenSanctions' GUR coverage
      proves insufficient, add a polite crawl of war-sanctions.gur.gov.ua.
      (KSE is deliberately excluded from this project — no accessible dataset.)

## Data-quality enhancements
- [ ] **GISIS IMO verification** — check IMO numbers against the IMO authority's
      own registry to flag "zombie"/fraudulent IMOs. Confirm GISIS terms of use
      before any automated access.
- [ ] **Apply "latest known name" as the default label everywhere** a single
      vessel name is needed (listings, exports, map labels), reusing
      `identity.current_value`.

## Data sources to add (continued)
- [ ] **Port-call facts for R8c** — we currently store no "called at port X"
      facts, so the R8c external-fact check (Novorossiysk / Kozmino / Murmansk)
      has nothing to surface. The GUR per-vessel pages list port calls; ingesting
      those as structured `port_call`/`last_port` facts would populate R8c.

## Scoring decisions (later)
- [ ] **`insufficient_data` band** — ~2,569 vessels score 0 only because we have
      no age and no list membership for them ("unknown", not "low risk"). Decide
      whether to add a distinct band/flag so absence-of-evidence isn't shown as
      low risk. (User is thinking about it.)

## Analysis (later)
- [ ] **Military / law-enforcement / SAR proximity analysis** — these vessel
      types are kept in the feed. Later, analyse their proximity to or
      interaction with monitored vessels (e.g. responding to a vessel in trouble,
      an incident, or an at-sea transfer) as a contextual signal — without
      asserting intent.

## Notes
- AIS (M3), port calls (M4), risk engine (M5), map (M6), export (M7) are the
  normal milestone roadmap — not parked, just upcoming.
