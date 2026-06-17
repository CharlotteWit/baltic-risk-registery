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
- [ ] **Direct KSE PDF / GUR crawl** — if/when OpenSanctions coverage proves
      insufficient, add the original KSE report parse and the polite GUR
      catalogue crawl (war-sanctions.gur.gov.ua) as primary sources.

## Data-quality enhancements
- [ ] **GISIS IMO verification** — check IMO numbers against the IMO authority's
      own registry to flag "zombie"/fraudulent IMOs. Confirm GISIS terms of use
      before any automated access.
- [ ] **Apply "latest known name" as the default label everywhere** a single
      vessel name is needed (listings, exports, map labels), reusing
      `identity.current_value`.

## Notes
- AIS (M3), port calls (M4), risk engine (M5), map (M6), export (M7) are the
  normal milestone roadmap — not parked, just upcoming.
