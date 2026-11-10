# TB-DR-00 Deep review of 2026-11-10: index

| Field | Value |
| --- | --- |
| Document ID | TB-DR-00 |
| Date | 2026-11-10 |
| Ordered by | Changfu Kuo (owner) |
| Code read | `origin/master` at `ca8f287`; open PRs #64 to #86 by their branches where a reviewer needed them |
| Method | Twelve reviewers in parallel, one per area, plus a task inventory. Six ran the system (the console in a browser as every role and language, the data flow hop by hop, the full test suite, the stub model stack, the checkers of the data standards, the dependency look-ups). One lead assembled the index, the PoC plan and TB-PLAN-06. |
| Outputs | This folder; `docs/plan/27-poc-plan.md` (TB-POC-01); `docs/plan/28-master-plan-v6.md` (TB-PLAN-06) |
| Rule kept | Review and plan only: no product code, test or configuration was changed and nothing was merged. Synthetic and public data only. No cloud spending, no GPU. |

## 1. The files

Counts are findings by severity as each file's tables give them. A finding that repeats a row of the critical-issues register (TB-REG-01, PR #73) is marked "registered CR-nnn" in its file and is not new work.

| File | Area | Prefix | Run or read | Findings | Blocker | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `01-fit-to-owner-intent.md` | Fit to the owner's intent; requirements trace | FIT | read | 27 | 0 | 1 | 15 | 10 | 1 |
| `02a-ux-clinical-journeys.md` | UI/UX and the clinic pipeline: PI, sub-investigator, CRC, in ja, zh-TW, en | UX | **run** (616 page loads, 183 timed tasks) | 41 | 3 | 0 | 7 | 17 | 14 |
| `02b-role-journeys-authz.md` | Non-clinical roles; role × route matrix (228 routes × 7 identities) | ROLE | **run** | 28 | 2 | 1 | 9 | 9 | 7 |
| `03-llm-serving-stack.md` | The LLM serving stack | LLM | **run** (stub, gateway; no GPU) | 46 | 1 | 3 | 15 | 23 | 4 |
| `04-engineering-quality.md` | Software engineering quality; the full suite | ENG | **run** | 36 | 0 | 0 | 7 | 22 | 7 |
| `05a-data-standards.md` | Data and interoperability standards | STD | **run** (checkers) | 35 | 1 | 0 | 9 | 18 | 7 |
| `05b-regulatory-standards.md` | Regulatory, GxP, privacy, quality system | REG | read | 32 | 0 | 3 | 13 | 14 | 2 |
| `06-data-flow-governance.md` | Data schema and governance; the data-flow trace | DATA | **run** | 25 | 0 | 2 | 9 | 11 | 3 |
| `07-trial-lifecycle.md` | The trial lifecycle end to end; site trial types | LIFE | read, small runs | 29 | 1 | 0 | 16 | 12 | 0 |
| `08-dependency-currency.md` | Library and component currency (201 Python packages, images, jars, weights) | DEP | **run** (look-ups) | 28 | 0 | 1 | 7 | 10 | 10 |
| `09-operations.md` | Operations and hosting | OPS | read, small runs | 77 | 3 | 0 | 26 | 40 | 8 |
| `10-plan-realism.md` | The plan itself | PLAN | read | 51 | 5 | 5 | 20 | 17 | 4 |
| `11-task-inventory.md` | Inventory of 67 cards, 115 register rows, 14 open PRs | — | read, git | — | | | | | |
| **All** | | | | **455** | **16** | **16** | **153** | **203** | **67** |

## 2. The reading in ten lines

1. The screening engine works end to end on synthetic data: the unit suite passes (2,261 tests with the jars present; 90.8 % line coverage), `make e2e-simple` passes, the backup restores, the data-handling scan is clean, and no patient identifier was found in any log, mail or export the reviewers produced.
2. It is not yet a product a clinician can be handed. Of 92 user requirements, 13 are done, 43 partial, 33 missing, 3 contradicted (TB-DR-01).
3. Three defects can give a wrong screening answer with no sign: the lab unit (STD-001), the judge answered by the verifier's model (LLM-002), a partial feed published as a good night (DATA-001).
4. Identity has a hole: a password alone opens a session through the API route even with the second factor on (ROLE-001).
5. The hosted demo cannot be used for the PoC as it is: it does not start from a clean build, loses all work at a restart, shares one password, accepts pasted charts, and has no feedback control.
6. Japan's real trial type (early Alzheimer's disease) has no scenario; CGMH's (rheumatoid arthritis) has no trial ruleset.
7. The IRB amendments filed on 2026-11-10 and the hospital IT pack state controls as present that are not built (REG-010, FIT-005, OPS-040).
8. The dates are set by the hospitals. At CGMH the approval, the export build and the notes tier run in series (float −0.5 to −11 weeks unless the build starts now); contracts are not engaged; one person holds eight roles.
9. The Python dependencies are in good order; the risks are in the Java jars, the GPU images, the model weights and the build tool.
10. The fastest safe PoC is a hosted demo with twelve working days of prerequisites: freeze Fri 2026-11-27, sessions Tue 12-08 to Fri 12-11.

## 3. The top findings

New means "not in TB-REG-01". "By a run" means the reviewer reproduced it.

| # | Finding | Severity | New | Evidence | Fix (card in TB-PLAN-06 §6) |
| --- | --- | --- | --- | --- | --- |
| 1 | **LLM-002.** When the judge server errors, the gateway answers the judge role from the verifier's build; the verifier then confirms itself and the pair reports agreement with 0 failures. Install default. | Critical | new | by a run; `03-llm-serving-stack.md` | T-601, with fix group D-276: no cross-role fallback; a failed role is "unknown"; the build id travels in the response |
| 2 | **STD-001.** The adapter never reads a lab row's own unit; it stamps the lookup's unit and factor (creatinine 88 µmol/L leaves as 88 mg/dL). The engine-side fix of CR-001 cannot see it. | Blocker | fix in PR #70, not merged | by a run; `05a-data-standards.md` | merge #70; T-613 |
| 3 | **DATA-001.** The nightly ingest has no completeness check: a missing or empty feed table passes, becomes the served snapshot, and older good snapshots are pruned. | Critical | new | by a run (2,837 lab rows dropped; feasibility 13 → 0); `06-data-flow-governance.md` | T-611 |
| 4 | **ROLE-001.** `POST /api/v1/session` gives a session on a password alone with TOTP on; the token works as the console cookie for the admin pages. | Blocker | new | by a run; `02b-role-journeys-authz.md` | T-505 (wave P) |
| 5 | **OPS-001, ROLE-002, UX-001, UX-002, ROLE-003.** The demo image does not start from a clean build (jars in a git-ignored folder; Secure-cookie seeding fails), needs about 1.9 GB at start against a documented 250 MB, and wipes all work at each restart. | Blocker | new | by runs in three reviews | T-501, T-509 (wave P) |
| 6 | **REG-010, FIT-005, OPS-040.** The filed IRB amendments and the IT pack state unbuilt controls as fact (opt-out within minutes, daily signed audit heads, admin without patient data, break-glass, step-up signing). No register ties each promise to code and a test. | Critical | new | `05b-regulatory-standards.md`, `01-…`, `09-…` | T-641; owner question Q-14 |
| 7 | **LIFE-001, LIFE-002.** No Alzheimer's ruleset, synthetic archetype or Japanese protocol; no RA trial ruleset. The PoC cannot show the sites' real trial types. | Blocker / High | new | `07-trial-lifecycle.md` §3 | T-503, T-504 (wave P) |
| 8 | **PLAN-001, PLAN-002, PLAN-003.** The CGMH critical path is in series with negative float; contracts are past or at their latest start; the owner is the single person in eight roles with an unruled conflict of interest. | Blocker | new | `10-plan-realism.md` §4 | TB-PLAN-06 §3; Q-08, Q-11 |
| 9 | **REG-014, OPS-004, PLAN-019, UX-006.** A tester can paste or upload real chart text into the hosted demo; there is no acknowledgement; there is no in-product feedback. | Critical / Blocker | new | by a run (UX), by reading (REG, OPS) | T-502, T-510 (wave P) |
| 10 | **DATA-004, DATA-005.** A missing site key is silently re-created, every pseudonym changes and opt-outs are lost; chart-number cleaning differs per entry point, so an opt-out can silently do nothing. | High | new | by a run; `06-data-flow-governance.md` | T-612 |
| 11 | **FIT-003.** The PI cannot start a feasibility, screening or case run; only the coordinator and admin can. | High | new | `01-…`; `auth.py:177-179` | T-512; Q-04 |
| 12 | **ROLE-005, ROLE-008, ROLE-011.** An external SMO coordinator can lift any opt-out; any investigator can make themselves PI of a study with no PI; a CRO with no study list sees every study. | High | new | by a run | wave 1 authorisation cards |
| 13 | **STD-020 to STD-022, STD-042.** Japanese feeds: half-width kana and Shift_JIS abort the night; deleted results count; no Japanese qualitative result is mapped; no YJ-to-ATC source. | High | new | by a run (STD-020) | wave 2 data cards |
| 14 | **LLM-007, DEP-007, DEP-008.** The install pins whatever file is in the model folder (a 16-byte fake passed); the judge weights carry an old chat template; the verifier weights come from a personal account with squashed history. | High | new | by a run (LLM-007) | wave 1 and dependency batch 2 |
| 15 | **OPS-050, LLM-027.** CGMH's shared B200: the platform kind is unknown, the request must be two MIG instances, and there is no backup, log, update or restore for that form. | Blocker | registered CR-084 (extended) | `09-operations.md` §2.10 | T-113, T-114 rewritten; Q-12 |

## 4. PoC prerequisites in one place

The list, with cards and sizes, is `docs/plan/27-poc-plan.md` §7. Blockers and Criticals on the PoC path: UX-001, UX-002, UX-006, ROLE-001, ROLE-002, ROLE-003, OPS-001, REG-014, PLAN-019, LIFE-001, STD-001. None may be open at the freeze (Fri 2026-11-27).

## 5. What is good and should not be changed

Each file has a "What is good" section. The points several reviewers made independently: unknown is shown differently from "not met" and says it does not exclude; "not suitable" needs a reason and every mark has Undo; the EDC review shows every value with its source and never drafts unknown as "no"; the error pages; zh-TW and ja use the right clinical vocabulary; the governed backup and restore; the data-handling scan in CI; the plan's rule that a late chain moves a site's date and never the scope quietly; the cards' "may touch / must not touch" fields.

## 6. What was not run

No GPU: no real model, no vLLM, no latency or structured-output check; cost and latency figures are estimates. No Docker daemon: no image build, no compose stack, no `install.sh`, no egress test, no image scan (image findings come from the repository's own scan file of 2026-11-10). No real REDCap, no vendor SS-MIX2 file, no licensed vocabulary. No hospital office was asked: every lead time is an estimate. Legal and regulatory readings come partly from secondary sources and are marked where not confirmed; they are not legal advice. Screen readers, real phones and Safari were not used. Each file states its own limits.

## 7. How to use this review

1. The owner reads this index, `27-poc-plan.md` and §1 to §3 and §10 of `28-master-plan-v6.md`, and answers the questions at G0 (Fri 2026-11-13).
2. The integrator takes §6 of TB-PLAN-06 as the backlog: wave P first, in the lanes of §6.5.
3. The critical-issues session receives the findings that extend its fix groups (the rows marked "tell fix group" in §6.2 of TB-PLAN-06; LLM-002 first).
4. Every finding has an id, a severity, evidence and a fix proposal in its file. The coverage table (TB-PLAN-06 §6.3) shows which card closes each Blocker, Critical and High.
