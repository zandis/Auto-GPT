# D-709 The site set-up when the hospital's lake cannot be asked: a saved change is answered as saved, and the pages say "could not be read"

- **Task:** NEW-SITE-2 (the integrator's order of 2026-11-13; what D-672 left open in the site set-up and the
  orchestrator)
- **PR:** this branch (`agent/NEW-SITE-2-lake-down-in-site-setup`), stacked on NEW-B-31 (#527, D-672); the two
  land together
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-672 (the lake client's `snapshot()` raises when the lake is not healthy), D-403 / D-472 (the
  site's publish in batches and as a polled job), D-131 (the readiness page), D-442 (the derive status)

## The problem

D-672 is right: a lake that cannot say which snapshot it serves is no longer read as an empty lake. It opened
three places, each of which also went wrong before for a lake that could not be reached at all:

1. **A change that was saved answered 500.** An upload, a chart, a code map and a resolve store their rows and
   write their audit event, then publish. The publish asks the lake and raised; the route answered 500. The
   person saw a failure, tried again, and the box held the sheet twice. For an upload it was worse: its own audit
   event (`setup.input`) is written after the publish and was never written.
2. **The readiness answer read "could not be asked" as "nothing".** `feed_loaded` answered None (the page: no
   feed section), `unknown_share` `(0, 0)` (no unknown codes), `scores_unverified` None (the scores are
   verified); and `readiness`, `patient_check` and `feasibility` themselves raised, so the three routes answered
   500.
3. **The derive status** showed no current snapshot, and the health line then read "derive batch finished".

## The decision

- **A saved change is answered as saved** (`SiteSetup._saved`). The four savers publish through it; when the lake
  cannot be asked (`LAKE_DOWN`: a `ServiceError`, which `LakeUnhealthy` is, or an `httpx` error: no answer), the
  answer carries `publish: waits_for_lake`, an audit event `setup.publish_waits` says so, and nothing more is
  done. The change publishes with the next tick (`flush`, every minute and after each job) or the next change,
  because what waits is the difference between the facts and the last publish. Any other error goes on.
- **A person who presses Publish still gets the error**: "saved, waiting" would be untrue of what they asked.
- **The readiness answer asks the lake once** and says `lake_unread` when it could not: the first item of the
  patients question is `patients.lake_unread`, the question is amber (not red "no patients", not green), no feed
  tier is named, and what the set-up's own store holds (proposed facts, unmapped codes, checks) is still
  answered. The three readers raise a lake's failure again instead of answering "nothing".
- **The patient check and the counts** answer `lake_unread` (no patients listed, no count, and not "needs a bulk
  input") instead of 500.
- **The console's pages say it** in English, Japanese and Traditional Chinese: the readiness item, the counts
  section and the patient check ("could not be read just now ... open this page again in a few minutes").
- **The derive status** carries `lake_unread`, and the health line says the lake could not be asked which
  snapshot it serves, as a warning, where it said "finished".

## What it does not do

- **No notice on the page that took the change.** The sheet, chart, code and people pages say what they said
  ("read", "saved"), which is true; that the publish waits is said by the readiness page and by the answer of the
  set-up route (`publish: waits_for_lake`). A line on each of those four pages is a later card if wanted.
- **The same file sent twice on purpose is still two inputs**, as before. What this card removes is the reason
  for a second try (the 500).
- A re-read of a sheet with new column roles goes the same way (it publishes through the same function).
- `decide` (confirm, correct, reject a fact) does not publish by itself and is unchanged.
- A lake that goes away between the readiness answer's first question and a later one of the same answer: the
  later reader's part is left out, and the next call says `lake_unread`.
- The other answers of the lake's client that D-672 lists as open (`promote`, `generation`, `site_in_sync`,
  `hold`) are lane B2's.

## Files outside the console

- `services/sitesetup/service.py`, `services/sitesetup/readiness.py` (placed with this lane by the integrator);
- `services/orchestrator/setup_api.py` (two routes), `services/orchestrator/derive.py` (the status);
- `libs/tb_common/metrics.py` (`check_derive`: one branch);
- `tests/unit/test_lake_client_snapshot.py` (lane B2's list of callers): the four entries D-672 marked OPEN, and
  `readiness`, now say what they do.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`SiteSetup.publish` and `flush` are unchanged and do the waiting; `LakeUnhealthy` is D-672's; the readiness list
of the page renders the new item by its key as it renders the others. One small function is added
(`SiteSetup._saved`) and one tuple (`LAKE_DOWN`).

## Dropped (D-311)

No sign-off step.
