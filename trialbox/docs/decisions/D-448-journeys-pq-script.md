# D-448 The journeys as the PQ script: one automated journey per role, on the in-process box, with the re-run list after a long break

- **Task:** T-315a (`docs/plan/28-master-plan-v6.md` §6.2, part a of T-315)
- **PR:** this branch (`agent/T-315a-journeys-pq-script`)
- **Date:** 2026-11-11
- **Status:** proposed
- **Closes:** WS-12.4 (the journeys part), RSK-64 (the re-run list after Golden Week)
- **Builds on:** D-311 (no development gates: no signer, no gate record), T-508 (the PoC scripts walked in process,
  `tests/integration/test_poc_scripts.py`), D-425 (T-102c, every page asks `permit`), D-380 (T-102b roles), D-430
  (break-glass), D-426 (clinical conflicts), T-611 (held nights), T-115 (EDC prefill)

## Decision

1. **The journeys are data plus one walk.** `tests/e2e/journeys/journeys.yaml` holds one journey per console role
   (administrator, steward, coordinator, PI, sub-investigator, monitor, viewer, privacy office) on the synthetic
   Taiwan site (`tw`, Asia/Taipei). Each step has what the person does and what the screen must show; a site walks
   the same steps by hand. `test_journeys.py` walks every step in the file's `walk` order (one site day across the
   roles) and checks each expected result through the console's pages, as the person would. D-311: the journeys are
   automated tests that double as the script; there is no signer field and no gate record.
2. **The in-process box, in the `unit` job.** The site is built as the PoC host builds it (`tools.feas_demo`,
   `tools.cgmh_demo`, `tools.list_demo`), but as a working site: demo mode off, one issued account per role, each
   set up at its first sign-in with the second factor and its own password. No docker, no network, stub model.
   The walk is one test (one site build, about two minutes); no new CI job.
3. **The topics of the card are a checked list.** Sign-in with the second factor (every journey starts with it),
   protocol to approved criteria, a screening run to a candidate list, approach, referral through the treating
   doctor, consent, EDC prefill to review (drafts only: nothing reaches REDCap), opt-out off every list and the next
   run, a break-glass grant and its steward review, a conflict resolved by the steward, a held feed night on the
   readiness page. A test fails when a topic or a console role has no step.
4. **Languages from the catalogues.** A language-sensitive step names `langs`; its text is taken from the console's
   catalogue in en, ja and zh-TW and must be the language's own text (not the English fallback) and on the page.
5. **Not on master yet: an expected failure with its card.** Such a step carries `expected_failure: {card, why}`. It
   runs and must fail; when it passes, the walk fails and asks that card to remove the mark. A card named must be a
   card of the plan. Today: J-STW-04 (the data-operations page, T-112b), J-MON-03 (the monitor page on the real data
   core, T-303), J-PRV-03 (the opt-out worker clears the lake, T-206a).
6. **The re-run list after a long break** (RSK-64) is `tests/e2e/journeys/rerun_after_break.yaml`: the journeys a
   site re-runs on the first working day after five or more days away (Golden Week, the Lunar New Year), each with
   its reason. A test holds that it names only existing journeys or steps.

## Consequences

- The PoC script steps of T-508 are reused, not copied: a change to a page changes one step function.
- The conflict of J-STW-03 is written as the nightly OMOP load writes it, because the journey site serves the
  legacy lake; detection itself is tested in `tests/unit/test_omop_core.py`.
- The held night of J-ADM-02 is a real adapter run (`run_ingest`) on the site's lake with the lab table missing.

## Open

- A Japan-flavour site (`jp`, AD-MAB and NEUR-COH) is not walked: its PI, sub-investigator and coordinator steps are
  walked by the PoC scripts (T-508); a `jp` journey file costs a second site build (about two more minutes).
- The printable protocol per journey is T-315b's.
