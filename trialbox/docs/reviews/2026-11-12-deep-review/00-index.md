# TB-DR2-00 Deep review of 2026-11-12: index

| Field | Value |
| --- | --- |
| Document ID | TB-DR2-00 |
| Date | 2026-11-12 |
| Ordered by | Changfu Kuo (owner) |
| Code read | `master` at `514ae9b`; the open pull requests #262, #278, #304 to #315 by their titles only |
| Method | Thirteen reviewers in parallel, one per area, each reading the code and running what runs on a 4-core machine with no GPU and no Docker daemon. One lead assembled this index and plan v7. |
| Outputs | This folder; `docs/plan/33-plan-v7.md` (TB-PLAN-07); two small fix pull requests (#323, #324) |
| Rules kept | Synthetic and public data only. No secret read or printed. No cloud resource touched. No product code changed on this branch. No IRB, COI or steward-approval step and no development gate proposed (D-311). Fixed limits judged by OD-10. |

## 1. The files

Each finding in a file has an id, a severity, evidence (file:line, a run, or a screenshot), impact, a fix, a card
and a PoC / go-live flag. Ids restart at 001 per file; findings of the review of 2026-11-10 are cited as "DR1".

| File | Area | Prefix | Run or read | Findings | Blocker | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `01-plan-vs-build.md` | Plan against the build; what to drop | PLAN | read; card-by-card check of 237 cards; `tests/property` run | 18 | 5 | 2 | 7 | 3 | 1 |
| `02-architecture.md` | Architecture and best practice | ARCH | **run** (restart and role experiments over real HTTP and PostgreSQL) | 21 | 0 | 0 | 7 | 10 | 4 |
| `03-code-quality-se.md` | Code quality and software engineering | ENG | **run** (3,570 unit tests reached, lint, property) | 20 | 1 | 3 | 5 | 6 | 5 |
| `04-user-journeys.md` | User journeys, role by role | JRN | **run** (`e2e-simple`, the console in a browser) | in progress | | | | | |
| `05-ui-ux.md` | UI/UX; ja, zh-TW, en | UX | **run** (355 page loads, 3 roles × 3 languages × 2 widths) | 23 | 0 | 0 | 6 | 11 | 6 |
| `06-llm.md` | LLM use, serving and platform | LLM | **run** (stub, gateway, tripwire, budget; no GPU) | 19 | 2 | 0 | 5 | 11 | 1 |
| `07-performance-scale-robustness.md` | Performance, scale, robustness | PERF | **run** (up to 8,000 synthetic patients; restart and backup experiments) | 36 | 2 | 4 | 17 | 10 | 3 |
| `08-data-input.md` | Data input mechanisms | DIN | **run** (11 scripts against the real parsers) | 23 | 1 | 2 | 8 | 11 | 1 |
| `09-trial-lifecycle.md` | Trial lifecycle | LIFE | **run** (`e2e_simple`, state machine, SAE clock, audit tampering, real-protocol compile) | 22 | 0 | 1 | 10 | 10 | 1 |
| `10-redcap-edc.md` | REDCap and EDC automation | EDC | **run** (31 scripted cases against the simulator and the EDC) | 22 | 0 | 2 | 8 | 10 | 2 |
| `11-standards.md` | Standards | STD | **run** (17 standards test files, checkers, probes) | 21 | 0 | 0 | 6 | 10 | 5 |
| `12-maintenance-operations.md` | Maintenance and operations | OPS | read, small runs (`bash -n` on 48 scripts; key, bundle, health runs) | 22 | 1 | 2 | 9 | 7 | 3 |
| `13-final-build-hardware-install.md` | Final build, hardware, tuning, installation | HW | read, dry runs, memory arithmetic from the two measurement files | 20 | 3 | 0 | 9 | 6 | 2 |
| **All** | | | | 267 + JRN | 15 | 16 | 97 | 105 | 34 |

The same defect seen from two areas keeps both ids and is counted in both files; section 4 lists the pairs.

## 2. The reading in twelve lines

1. **The engine is sound on synthetic data and the build is not yet a product a site can run.** `e2e-simple` passes;
   3,541 of the 3,570 unit tests reached pass (the 15 failures are this machine's missing jars and fonts); lint is
   clean. But a PRODUCTION box cannot start (no embedder in any image), the box installer stops before its wizard,
   and no path leads to a qualified model pair on a site box.
2. **Nothing measured so far is the product.** G1 used hand-started model servers, synthetic weight pins, one model
   call at a time, on a hospital about 16 times thinner than a real one. Throughput, capacity and accuracy are
   unknown for the build that ships.
3. **One model can still exclude a patient** on four of the paths, and the excerpt builder can change what a note
   says (a family-history fact shown under the past-history heading; a denied list without its lead-in).
4. **Real feeds will be wrong quietly**: ROC dates read as the year 1150, ICD-9-CM years tagged ICD-10-CM, common
   Japanese units unread, unmapped local codes dropped uncounted, a first night with a missing table passed.
5. **The DR1 unit Blocker is fixed** (creatinine 88 µmol/L no longer leaves as 88 mg/dL; 46 unit pairs and 51 lab
   values checked, none wrong). So are the cross-role fallback (LLM-002), the fake-weights pin (LLM-007), the
   session without a second factor (ROLE-001) and the missing-feed night (DATA-001, except the first night).
6. **The night neither scales nor survives**: 0.33 MB per patient in memory at ingest (16.7 GB at 50,000 against
   caps of 6 and 8 GB), a full reload every night, a restart that re-runs jobs from zero or leaves the night
   half-published, a backup of 100 to 430 GB a night at real density.
7. **The merge gate does not gate**: master is unprotected, a pull request was merged 37 minutes before its unit job
   failed, and the nightly end-to-end jobs have been red since 2026-11-10.
8. **REDCap write-back has never met a real REDCap**; the simulator accepts what REDCap refuses, and on a repeating
   instrument TrialBox fills a person's own instance.
9. **A new box is seeded with eight approved, scheduled rulesets** written in the project chat.
10. **Operations**: the default key sealing has no recovery copy (a dead mainboard loses every backup); the support
    bundle leaked four kinds of password (fixed in #324); no alert reaches a person on a box without a mail relay.
11. **The plan does not fit** at full scope: about 285 session-days against 210 to 280 to 2027-02-26. With the cuts
    of plan v7 §3 it has about two weeks of float. The binding date is the site box order on 2026-12-18.
12. **Accessibility and language are good**: axe-core finds 0 violations on 355 page loads; 2,841 keys × 3 languages
    with none missing and no simplified characters. The gaps are in the files that leave the screen (PDF glyphs,
    English workbooks) and legacy encodings.

## 3. The top findings

"By a run" means the reviewer reproduced it on this tree.

| # | Finding | Severity | Evidence | Fix (plan v7 wave) | Flag |
| --- | --- | --- | --- | --- | --- |
| 1 | **HW-001, PERF-007, HW-006.** The build that ships has never run on a GPU; G1's only throughput figure is one call at a time. | Blocker | `13-…` §4; `07-…` §4; `deploy/gcp/complete-run-vm.sh:278-295` | the product-on-GPU run (wave 2, §7.1 G-2, G-3) | Go-live both |
| 2 | **ENG-003, HW-002.** A PRODUCTION box cannot start the embed service: no embedder is pinned and none is in an image. | Blocker | by a run; `embed_service/embedder.py:127,199-211` | wave 1, lane D | Go-live both |
| 3 | **HW-003, LLM-005, HW-004.** No model pair can become `champion` on a site box: no qualification record exists or ships; the judge cannot pass both the pin and the licence step. | Blocker | by a run; `eval/qualification/`, `tools/qualify.py:470-479` | wave 1, lane D | Go-live both |
| 4 | **PLAN-001.** One model's answer still excludes on SCREEN v1, NAV, CASE and the MICROBATCH re-tier. | Blocker | by a run (`tests/property`: 8 strict expected failures) | T-707 to T-710 (waves 0, 1) | PoC |
| 5 | **LLM-001.** The excerpt clip stitches non-adjacent sentences and drops the heading and the negation; `left_out` stays 0. | Blocker | by a run; `matching/cascade/engine.py:599-622` | stop-gap wave 0; NEW-LLM-1 with T-710 | PoC |
| 6 | **DIN-001.** A ROC date `1150501` is read as the year 1150; `640715` as 6407. The night passes. | Blocker | by a run; `adapter/mapping/engine.py` `_parse_date` | **#323** (stop-gap); ROC and era types in wave 1 | Go-live TW |
| 7 | **PERF-001, PERF-002, PERF-006.** Ingest and rebuild hold the hospital in memory (0.33 MB per patient); no scale gate; every night is a full reload. | Blocker / Critical | measured at 1k to 8k patients; `lake/store.py:810-812`, `scheduler.py:280` | T-687, T-692, T-726 (waves 1 to 3) | Go-live both |
| 8 | **OPS-003, OPS-004.** The box installer dies at the backup step before the wizard; the real installer is exercised nowhere. | Blocker | by a run of `backup-install`; rest by reading | wave 1, lane D | Go-live both |
| 9 | **ENG-001, ENG-002.** Master is unprotected; the nightly compose, e2e and browser jobs are red. | Critical | `gh api` (`protected: false`); CI history | wave 0 | PoC |
| 10 | **LIFE-001.** A new box holds eight approved rulesets that NAV and COHORT run on hospital data. | Critical | by a run in PRODUCTION; `tb_common/ruleset.py:238` | NEW-LIFE-1 (wave 0) | Go-live both |
| 11 | **EDC-001, EDC-002.** No run against a real REDCap; a repeating instrument gets TrialBox's values in a person's instance. | Critical | by 31 scripted cases; `edc/service.py:471-484` | copy-assist at go-live; NEW-EDC-1 (wave 2) | Go-live both |
| 12 | **DIN-002, DIN-003, ENG-004.** Opt-out does not hold: FHIR-fed patients have no pid-map row; the desk registers unknown chart numbers; a merged chart still shows on the console. | Critical | by runs | waves 0 and 1; FHIR package only if a FHIR site is planned | Go-live both |
| 13 | **OPS-001, HW-010.** The TPM-sealed key has no recovery copy; no disk-unlock design passes `check_host` and restarts unattended. | Critical / High | by a run of `tools.keys`; `seal_keys.sh:58-70` | wave 3, lane D | Go-live both |
| 14 | **ARCH-001, ARCH-002, PERF-008.** A restart re-runs every interrupted job from zero; a restart during ingest fails the job while the adapter publishes. | High | by runs over real HTTP | T-689, NEW-PERF-2 (waves 0, 1) | Go-live both |
| 15 | **STD-001, STD-004, DIN-006, DIN-009.** ICD-9-CM years tagged ICD-10-CM; `IU/L` and `×10^3/µL` unread; unmapped codes dropped with no count. | High | by runs | wave 0 and 1, lane E | Go-live TW / JP |
| 16 | **LLM-002, LLM-003.** Note retrieval works only for the demo vocabulary (32 English words; a hash embedder in SCREEN); the PHI tripwire refuses 12 of 20 ordinary zh-TW criteria. | High | by runs | NEW-LLM-2, -3 (wave 2) | PoC |
| 17 | **STD-002, LIFE-010.** Signed audit heads are never made on a box: truncation plus a rewritten head verifies PASS. | High | by a run | NEW-STD-2 (wave 0) | Go-live both |
| 18 | **PLAN-003, PLAN-004, PLAN-005.** The scope does not fit; the hardware form is undecided and unordered; the CGRD data path is a 43-line reader. | Blocker | `01-…` §4, §6 | plan v7 §2 (Q1, Q2, Q7, Q8), §4 | Go-live both |

## 4. The same root seen from several areas

| Root | Ids |
| --- | --- |
| Measured things are not the product | HW-001, HW-006, PERF-007, LLM-012, PERF-002, LLM-006 |
| The embedder | ENG-003, HW-002, LLM-002 |
| No qualified pair | HW-003, HW-004, HW-005, LLM-005, LLM-007 |
| Restart and the night's state | ARCH-001, ARCH-002, ARCH-003, PERF-008, PERF-009 |
| Signed heads never scheduled | STD-002, LIFE-010 |
| One lake source; HAPI on the box | PLAN-008, STD-006, STD-010, ARCH-015 |
| Opt-out across identities | DIN-002, DIN-003, ENG-004, LIFE-005, PLAN-006 |
| Units and their spellings | STD-004, DIN-009 |
| Encodings at upload | UX-004, EDC (dictionary), DIN |
| The installer | OPS-003, OPS-004, HW-012, UX-011 |
| OD-10 offenders | ARCH-020 (16 rows), PERF §6, PLAN-012, ENG-005 (`FULL_RECORD_MAX_CANDIDATES = 100`), HW-007 (`SCREEN_MAX_PAIRS=20000`) |

## 5. The review of 2026-11-10: what is fixed

Each file has the table for its area. In short, verified in code or by a run:

- **Fixed:** STD-001 (the lab unit), LLM-002 (cross-role fallback), LLM-007 (fake weights pinned), ROLE-001,
  ROLE-005, ROLE-008, ROLE-010, ROLE-011, DATA-001 (except the first night), DATA-002, DATA-003, DATA-004, STD-020 to
  STD-022 (Japanese feeds), DEP-001, DEP-003, DEP-006, 25 of 29 lifecycle findings, 8 of 10 standards Blockers and
  Highs, 11 of 29 operations Blockers and Highs, most of the novice-path findings.
- **Partly:** DATA-005, STD-030, STD-042, UX-001, UX-002, UX-009, nine operations rows, LLM-001 (G1 half done).
- **Open:** old ENG-005 (branch protection), ENG-022 (two engines), ENG-023 (guard fails open), LIFE-027
  (retention), UX-003 and UX-021, OPS-004, OPS-051, OPS-062, OPS-063, DEP-012 (now ENG-003), about 33 of the 118
  Blocker, Critical and High rows of the critical-issues register (CR-027, CR-038, CR-060, CR-069 among them), and
  27 of the 36 findings of the scale review of 2026-11-11.
- **Out of scope by the owner's rule:** the IRB, COI and approval rows (REG-001, -002, -007 to -010 and the like).

## 6. Small fixes made, each in its own pull request with a test that failed first

| PR | Finding | Change |
| --- | --- | --- |
| #323 | DIN-001 (Blocker) | The compact date form needs eight digits; a year before 1850 is refused as a date of another calendar. 7 new cases, 6 failed before. |
| #324 | OPS-002 (Critical) | The support bundle redacts `*_PASS`, `*_PW_*` and passphrase values. |

Every other small, certain fix is listed in its file's "Small certain fixes" section and in plan v7 wave 0. They
were not made here because they touch files that open pull requests are changing (the opt-out reads with T-708,
the 409 follow with T-723) or need a run this machine cannot do.

## 7. What was not run

No GPU: no real model, no vLLM, no throughput or accuracy figure of our own. No Docker daemon: no image build, no
compose stack, no installer end to end, no egress test. No real REDCap, no vendor SS-MIX2 file, no real hospital
extract, no licensed vocabulary. The HL7 validator and the CQL translator were not run (jars not fetched on the
shared machine). Nothing above 8,000 synthetic patients; the scaling figures are fits and are marked so. `make
backup-drill`, `make data-scan` and `make security-scan` did not complete under the machine's load. Screen readers,
real phones, real Excel and Safari were not used. Timings were taken on a shared machine under load and are upper
bounds. The tests that need a GPU or the owner's hardware are in plan v7 §7.
