# TB-PLAN-07 Plan v7: the re-planned task list after the deep review of 2026-11-12

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-07 |
| Date | 2026-11-12 |
| Owner | Changfu Kuo (Aimedics) |
| Status | **Proposed.** It replaces the task lists and the order of work of `28-master-plan-v6.md` (TB-PLAN-06) and `31-master-plan-v6.1-addendum.md` (TB-PLAN-06.1) once the owner accepts it. The owner decisions OD-10 to OD-21 and D-311 are unchanged and win over this file. |
| Basis | The deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/` (TB-DR2-00 to TB-DR2-13), on `master` at `514ae9b`. Finding ids below (PLAN-, ARCH-, ENG-, JRN-, UX-, LLM-, PERF-, DIN-, LIFE-, EDC-, STD-, OPS-, HW-) are that review's. |
| Dates held | CGMH go-live **Wed 2027-04-28**. Japan go-live **Thu 2027-05-13**. |

Rules kept in this plan: no IRB, COI or steward-approval step; no development gate or sign-off (D-311); no fixed
limit that is not derived from hardware, measured speed or data size, or declared as a setting with a reason
(OD-10). Milestones below are build dates, not gates. Sizes: S up to 1 day, M 2 to 4 days, L 1 to 2 weeks of one
session. Card ids `T-nnn` are those of TB-PLAN-06 and 06.1; `NEW-<AREA>-n` are named in the area file of the review
and get a `T-` number when started; where a `NEW-` id here and the area file differ, the finding id beside it rules.

## 1. What changed since v6.1, in ten lines

1. v6 and v6.1 hold 237 cards: 149 are done by code and test, 10 are half done, 78 are missing. At 3 to 4 parallel
   sessions the remaining work is about 285 session-days against 210 to 280 available to 2027-02-26 (PLAN-003). The
   plan does not fit unless scope is cut. Section 3 cuts about 85 session-days.
2. The build that ships has never run on a GPU (HW-001). G1 measured hand-started model servers, one call at a time
   (HW-006, PERF-007), on a synthetic hospital about 16 times thinner than a real one (PERF-002). No throughput,
   capacity or accuracy claim rests on the product yet.
3. A PRODUCTION box cannot start: the embed service has no embedder in any image (ENG-003, HW-002), the installer
   stops at the backup step (OPS-003), and there is no path to a qualified model pair on a site box (HW-003, LLM-005).
4. One model's answer still excludes a patient on four paths (PLAN-001), and the excerpt builder can show the models
   a family-history fact under the past-history heading (LLM-001).
5. Real feeds will break quietly: a Republic-of-China date is read as the year 1150 (DIN-001; fix in PR #323),
   ICD-9-CM years in Taiwan are tagged ICD-10-CM (STD-001), common Japanese unit spellings are not read (STD-004,
   DIN-009), unmapped codes vanish uncounted (DIN-006).
6. The night does not scale or survive: 0.33 MB of memory per patient at ingest (PERF-001), a full reload every
   night (PERF-006), a restart re-runs jobs from zero (ARCH-001), and a restart during ingest leaves the night
   half-published (ARCH-002, PERF-008).
7. The merge gate does not gate: master is unprotected and the nightly end-to-end jobs have been red since 11-10
   (ENG-001, ENG-002).
8. REDCap write-back has never met a real REDCap, and the simulator accepts what REDCap refuses (EDC-001); on a
   repeating instrument it writes into a person's own instance (EDC-002).
9. A new box is seeded with eight rulesets already approved and scheduled (LIFE-001), while a new study made by a
   person cannot get its first approval in the console at all (JRN-001).
10. Much is sound and stays: the unit suite (3,541 of 3,570 reached tests pass; failures are this machine's missing
    jars), the unit conversion fix, the pair's "unknown on any fault" rule, the audit hash chain, accessibility and
    the three language catalogues.

## 2. Decisions this plan needs from the owner (each with a default the plan assumes)

| # | Decision | Default assumed here | Why now |
| --- | --- | --- | --- |
| Q1 | The hardware form for both sites | **One dedicated box: Ubuntu 24.04, one RTX PRO 6000 (96 GB)**, compose set `docker-compose.yml + secrets + rtxpro6000 + identity + box`, installed by `box-install.sh`. The CGMH B200 is the owner's bench only. DGX Spark, RTX 5090, two-device, Kubernetes, Windows are parked. | It is the only form ever measured (HW table). Delivery is 9 to 13 weeks; the order date is the critical path (PLAN-004). |
| Q2 | Order one reference box now | Yes, this week, same class as Q1 | Every install, drill, capacity and power-cut test needs it (HW §8, OPS §7) |
| Q3 | The embedder in release 1 | In, pinned (bge-m3), in the lake image; if its PRODUCTION start test is not green by 2026-12-04, release 1 ships without note retrieval by embedding and says so | ENG-003, HW-002, LLM-002 |
| Q4 | REDCap at go-live | **Copy-assist mode at both sites.** The API send is a per-study switch turned on after EDC-001 to EDC-008 | EDC §6 |
| Q5 | A real REDCap test project | The owner provides one per site, or a local install under the institution's consortium licence, with four tokens (EDC §8) | Nothing else closes EDC-001 |
| Q6 | One lake source | `omop`; the legacy flatten, the nightly HAPI load and CQL-on-the-box are removed (CQL stays as a CI differential) | PLAN-008, STD-006, STD-010, ARCH-015 |
| Q7 | Scope dated after go-live | The list of section 3.2 | PLAN-003, PLAN-015 |
| Q8 | The first CGMH data source | The CGRD read connection only (T-731, one connector); the other four connectors after go-live | PLAN-005 |
| Q9 | Disk unlock on the box | TPM-sealed key with a printed recovery copy held by the box owner | HW-010, OPS-001 |

## 3. What is dropped, frozen or merged

### 3.1 Dropped or removed from the product

| Item | Verdict | Evidence |
| --- | --- | --- |
| Legacy lake source (flatten) after the flip to `omop` | drop | PLAN-008, STD-006 |
| HAPI FHIR server and the 105 JVM jars on the box; the nightly FHIR load | off the box; kept as CI jobs (T-306 widened, NEW-PERF-6) | STD-010, ARCH-015 |
| CQL as a run-time engine | CI differential only (T-711) | STD-010 |
| The v1 evaluation path as a second engine | removed at the end of T-709/T-710 (NAV and the re-check call the cascade) | ENG §5, ARCH §5.4 |
| `services/deliverables` | drop or move under `tools/` | PLAN §5.1 |
| `tracestore`, `registry` as services | merge into the gateway | PLAN §5.1 |
| `embed-service` as its own container when it runs the lake's image | merge into the data process | ARCH §5.10 |
| `StepStore`/`Dispatcher` (schema `wf`) | use it for T-689, or delete it; no third option | ARCH-004 |
| `deploy/topology_a`, `deploy/pgbackrest/Dockerfile`, `deploy/windows` in the bundle, `site_params.yaml`, the second `settings.example.yaml` | drop | OPS §5, ARCH-013 |
| `tools/` in every service image (68,000 lines) | out of the image | ARCH-012 |
| Traceability CSV (273 rows, all "planned") and its CI job | drop, or regenerate from tests (NEW-STD-3) after go-live | STD-003, PLAN-016 |
| Root Auto-GPT tree (`autogpt/`, root `Dockerfile`, `requirements.txt`) | remove from the repository | ENG §5 |
| The steps of TB-PLAN-06 that D-311 and the owner's rules struck (IRB, counsel, sign-off, G4 to G6, GP-0 to GP-2) | delete from the text | PLAN-010 |

### 3.2 Frozen: stays as built, no new card before go-live

Opportunity feed and hub (T-741 to T-745); the phone app and use from outside (T-732, T-733); the profile and
research cards (T-203c, T-311a/b, T-312, T-313, T-314, T-316a/c); the patient twin's new layers; mail intake;
`channels`; four of the five connectors of T-731; visits and deviations beyond what exists; more close-out;
the data core's own capture as an EDC of record (it stays a working aid; its trail is made append-only, EDC-009);
Kubernetes (`deploy/platform`), shared-quota, two-device, RTX 5090, GB10 forms (out of the per-PR CI as well);
the model bake-off tools and the 19 MB of evaluation corpora (moved to the fetch cache); T-711; T-717, T-718, T-721
until T-715 is in refuse mode; T-697, T-698, T-700 (except the `list_jobs(limit=500)` calls), T-701.

## 4. The merged critical path

Working days from 2026-11-13 (Taiwan calendar): 40 to 2027-01-08, 70 to 2027-02-26, 110 to 2027-04-28, 118 to
2027-05-13.

| # | Step | Cards and findings | Ends | Depends on |
| --- | --- | --- | --- | --- |
| 1 | The gate gates: branch protection, nightly green, unit job in shards | T-007, ENG-001, ENG-002, T-747 (#306), T-653 | Fri 2026-11-20 | — |
| 2 | Hardware decided; reference box ordered | Q1, Q2, NEW-PLAN-2 | Fri 2026-11-20 | owner |
| 3 | One model never excludes; one decision function; one excerpt builder that keeps headings and negation | T-707 (#307), T-708 (#311), T-709, T-710, NEW-LLM-1 | Fri 2026-11-27 | — |
| 4 | The screening job survives an outage and a restart | T-689 (#309), ARCH-001, NEW-ARCH-1 | Fri 2026-11-27 | — |
| 5 | A PRODUCTION box starts and holds a qualified pair: embedder image, installer to the wizard, vendor qualification record shipped and promoted at install, chat template pinned | ENG-003, HW-002, HW-003, HW-004, HW-005, OPS-003, OPS-004, LLM-005, LLM-007 | Fri 2026-12-04 | Q3 |
| 6 | The measuring harness measures the product: concurrency from the serving record, calls/s, tokens/s, p50/p95, GPU utilisation; dense synthetic profile | NEW-PERF-1, HW-006, PERF-002, T-687 | Fri 2026-12-04 | — |
| 7 | **The product-on-GPU run** (replaces "G1 attempt 3"): real bundle, `box-install.sh`, record, canary, 50,000-patient screen at 1/4/8/16/32 in flight, power cycle | section 7.1, tests G-1 to G-9 | Fri 2026-12-11 | 3 to 6 |
| 8 | Capacity statement and hardware note; **both site boxes ordered** | T-667, T-734 | **Fri 2026-12-18** | 7 |
| 9 | `publish(night)`; ingest and rebuild in streams; nightly deltas | T-723 (#314), T-692 (#304), T-726, PERF-001, PERF-006 | Fri 2027-01-15 | 4 |
| 10 | The CGRD connector with its mapping step; the date, code and unit repairs for real feeds | T-731 (CGRD only), section 5 lane E wave 1 and 2 | Fri 2027-01-22 | 9 |
| 11 | Reference box installed from a wiped disk by the handbook; update, backup, restore-on-a-second-machine, power-cut drills | T-730 (split in five), T-213b, NEW-OPS-1, HW-010, HW-012 | Fri 2027-01-29 | 2, 5 |
| 12 | The acting person is a fact the callee checks; opt-out erasure in every store; generations | T-712 (#308), T-714 (#312), T-715, T-716, T-719, T-206b (#278), T-727, T-728 (#313), T-724, T-725 | Fri 2027-02-12 | 9 |
| 13 | Feature complete: lifecycle repairs, outputs in three languages, EDC copy-assist repairs, accuracy set per language measured on the box | sections 5 and 7 | **Fri 2027-02-26** | 3 to 12 |
| 14 | Site boxes delivered (9 weeks P50: 2027-02-19; 13 weeks P90: 2027-03-19), installed, connected, mapping content done on a real extract, first real night | T-315b, T-315c, T-735, NEW-DIN-17 | CGMH Fri 2027-03-26; Japan Fri 2027-04-09 | 8, 10, 11 |
| 15 | Real-data dry run, the journeys of T-315a on the site's box, training with the guides in zh-TW and ja, acceptance | T-317, `docs/runbook/06-go-live-acceptance.md` | CGMH Fri 2027-04-16; Japan Fri 2027-04-30 | 14 |
| 16 | Go-live | | CGMH Wed 2027-04-28; Japan Thu 2027-05-13 | 15 |

Float (PLAN §6.1): steps 3 to 8 have +1 week to the order date if the run of step 7 passes the first time and −2
weeks if it must be repeated. Hardware for CGMH has +2 weeks at P50 delivery and −2 weeks at P90 (清明 falls in
step 15). Japan has +4 weeks at P50 and 0 at P90 (fiscal-year turnover on 04-01, Golden Week 04-29 to 05-05).
**The binding date of the whole plan is the box order on 2026-12-18.** If step 7 slips, order on the measured
RTX PRO 6000 figure of 2026-11-11 (62.6 of 95.6 GiB used) and correct the capacity statement after.

## 5. Waves and lanes for parallel sessions

At most four sessions at a time, one card each. The lanes touch different folders so that sessions do not collide.
A card merges only after its own unit job is green (v6.1 §5.6 stays).

| Lane | Owns (folders) | Must not touch |
| --- | --- | --- |
| **A. Decision and model** | `services/matching`, `services/criteria_compiler`, `services/guard`, `libs/tb_llm`, `eval/`, `tests/property` | `deploy/`, `services/adapter` |
| **B. Night and capacity** | `services/adapter` (pipeline, not mapping), `services/lake`, `services/orchestrator` (jobs, scheduler, clients), `tools/trialbox/backup.py` | `services/console`, `services/matching` |
| **C. Trust and console** | `services/console`, `services/orchestrator/app.py` routes, `libs/tb_common` (auth, erasure, roles), `deploy/docker/*roles*` | `services/lake`, `services/matching` |
| **D. Box, serving and operations** | `deploy/`, `tools/` (install, qualify, complete_run, support), `services/gateway`, `services/embed_service`, `docs/runbook`, `docs/handover` | `services/console` pages |
| **E. Data input, standards, EDC** | `services/adapter/mapping`, `services/adapter/sources`, `services/datacore`, `services/omop`, `services/edc`, `services/rc_bridge`, `services/rc_sim`, `catalogue/`, reports | `services/orchestrator` |

### Wave 0: 2026-11-13 to 2026-11-20. Small and certain; land the open pull requests

| Lane | Cards | Size |
| --- | --- | --- |
| all | Merge or close the open pull requests #304 to #315, #278, #262; merge #323 (DIN-001) and #324 (OPS-002) | — |
| C | T-007 branch protection with the CI jobs as required checks (ENG-001) | S |
| D | Nightly green: `TB_ENV=TEST` for the test stack's embed service, the public-data fetch, random order to completion (ENG-002); a red nightly is the next day's first card | M |
| A | LLM-001 stop-gap: a clipped note never gives a final "not met" (`engine.py:618`) | S |
| A | NEW-LIFE-1: no pre-approved ruleset on a VALIDATION or PRODUCTION box (LIFE-001) | S |
| B | NEW-PERF-2 / NEW-ARCH-1: on 409 the orchestrator follows the running ingest (PERF-008, ARCH-002) | S |
| B | NEW-PERF-3: a built-but-not-promoted night is not "passed"; a snapshot dated after today is refused (PERF-009) | S |
| C | NEW-JRN-1: a new study gets its first approval in the console; the journeys never write the database directly (JRN-001) | S |
| C | NEW-JRN-2: the opt-out register takes a chart number or the whole pseudonym, never a prefix, and says when nobody matched (JRN-002, DIN-003) | S |
| C | ENG-004: the console reads `optout.effective()` (merged charts); with T-708 | S |
| C | NEW-ARCH-18: every store's schema is on its service's role list, with an enumerating test (ARCH-021) | S |
| D | NEW-OPS-8: `trialbox-ops.timer` enabled; stale health facts turn red (OPS-009). NEW-STD-2: signed audit heads on a timer and in `doctor` (STD-002, LIFE-010) | S, S |
| E | NEW-DIN-6, -7, -8: unmapped codes counted nightly; unknown status stays unknown; first night needs its required tables (DIN-006, DIN-007, DIN-008) | S, S, S |
| E | EDC-010 (XML-illegal characters refused), EDC-009 (append-only trigger on `datacore.history`), EDC-003 (a `multi` item held) | S, S, S |

### Wave 1: 2026-11-23 to 2026-12-04. The decision path, a box that starts, a harness that measures

| Lane | Cards | Size |
| --- | --- | --- |
| A | T-709 one status function; T-710 one excerpt builder with NEW-LLM-1 (windows keep their heading and negation scope; the budget from the build's context) | M, M |
| A | NEW-LIFE-2: the weekly re-check covers every structured criterion and brings excluded patients back (LIFE-003, LIFE-004); goldens move | M |
| B | T-689 on `StepStore`: lease, attempts, recorded steps; a restart resumes (ARCH-001) | L |
| B | T-687 scale gate with the dense profile (about 500 records and 40 notes per patient) under the compose memory caps; its lint covers every timeout and `LIMIT`, not only those above 60 s (PERF-002, PLAN-012) | L |
| C | T-714 (#312), T-712 (#308), then T-715 in report mode | M, S, L starts |
| D | Embedder pinned, in the image with hashed extras, PRODUCTION start test (ENG-003, HW-002) | M |
| D | Qualification path: licence step accepts `none-in-source` (HW-004); vendor record shipped in the bundle and promoted by the installer (HW-003, LLM-005); chat template hashed and passed (HW-005); context written into the pin, null context refused in PRODUCTION (LLM-007) | S, M, S, S |
| D | Installer reaches the wizard: backup step without a mail relay is a FAIL line, not a stop (OPS-003); the real `install.sh` in `make rehearse-box` and in CI (OPS-004) | S, M |
| D | NEW-PERF-1: `complete_run` sets `TB_SCREEN_LLM_CONCURRENCY` from the serving record and records calls/s, tokens/s, p50/p95, GPU utilisation (HW-006, PERF-007, LLM-012) | S |
| E | NEW-DIN-1 rest: ROC and era dates as declared column types. NEW-STD-1: ICD-9-CM years in Taiwan (STD-001). NEW-STD-4 / DIN-009: unit spellings (`IU/L`, `×10^3/µL`, `mL/分/1.73m2`, `秒`). NEW-STD-5: NHI drug code to ATC in the nightly path | S, M, S, S |
| E | NEW-DIN-3: the opt-out desk checks the patient is known; the chart-number rule is asked at install (DIN-003) | S |

### Wave 2: 2026-12-07 to 2026-12-18. The product on a GPU; the order

| Lane | Cards | Size |
| --- | --- | --- |
| D + cloud session | The product-on-GPU run (section 7.1); then T-667, T-734 from its numbers; the vLLM image move in the same GPU session (ENG-013: 337 accepted findings lapse 2026-12-10) | run, S, M, M |
| A | NEW-LLM-2: the retrieval lexicon from the compiled ruleset in the site's language; the pinned embedder in SCREEN (LLM-002) | L |
| A | NEW-LLM-3/4: the PHI tripwire stops refusing ordinary zh-TW and ja criteria and reads full-width digits, katakana names and Japanese insurance numbers (LLM-003, LLM-004) | M |
| B | T-723 (#314) `publish(night)`; T-692 (#304) streams, the build as its own process (PERF-001) | L, L |
| C | T-715 router by router, lifecycle first; NEW-ARCH-3 the console leaves the orchestrator's stores | L, M |
| E | NEW-EDC-1: conformance run on a real REDCap recorded as cassettes; the simulator made as strict (EDC-001); needs Q5 | M |
| E | NEW-DIN-4, -5: SS-MIX2 version key with the day; ICD-10 in the first PRB-3 triple (DIN-004, DIN-005) | S, S |

### Wave 3: 2027-01-04 to 2027-01-29. The reference box; real connections; erasure

| Lane | Cards | Size |
| --- | --- | --- |
| D | The reference box from a wiped disk: `box-prepare.sh`, the Linux media with the NVIDIA driver, name resolution, a time source, disk unlock with a recovery copy (HW-010, HW-012, OPS-001, OPS-005, OPS-006, OPS-007); T-730 as five cards (message path and sign-in banner, backup target and key ceremony, health checks for night, clock and GPU, locked-box page, quiet-hour updates) | L, 5 × M |
| D | T-735 the owner's handbook and IT's one page; the IT pack rewritten to the box (OPS-011, HW-013) | L |
| B | T-726 the night runner with nightly deltas (`since` the last published generation) (PERF-006); T-724, T-725 generations; backup: incremental, lake lock for the listing only, append-only files (PERF-010, PERF-011, ENG-011) | M, M, M, M |
| C | T-715 refuse mode; T-716; T-719; T-206b (#278) on T-727's registry; T-728 (#313) | —, M, M, M, S |
| E | T-731 the CGRD connector and its mapping step; NEW-DIN-2 only if a FHIR-fed site is planned | L |
| A | NEW-LLM-6: the accuracy set per language and stratum (long notes, negation, family history, era dates, labs; about 200 gold exclusions each), with a calibration table and paraphrased injection (LLM-006, LLM-009, LLM-011); measured on the reference box | L |
| A | NEW-LIFE-3: protocol structure (groups, phases, warnings); two real public protocols (an RA trial, an early-AD trial) as fixtures (LIFE-002) | M, M |

### Wave 4: 2027-02-01 to 2027-02-26. Feature complete

| Lane | Cards | Size |
| --- | --- | --- |
| B | T-694 batches; T-702, T-703, T-695; the 500,000-patient night as an incremental night with a stated capacity, refused with an estimate when it does not fit (HW-007, OD-10) | L, L, S, M |
| C | Lifecycle repairs: the screening log keeps numbered rows on opt-out (LIFE-005); a study closes only when empty (LIFE-006); the SAE clock is off until the study's rule set is confirmed, mail at entry and daily (LIFE-007, LIFE-008); retention hold by study state (LIFE-009, T-305c); reason for change and append-only trails (LIFE-011) | S, S, M, S, M |
| C | Journeys: the PI may start a request from the page (JRN-003); the EDC item map saves at the dictionary's size (JRN-005); the privacy office reaches the one-patient report (JRN-006); a consent date after today is refused (JRN-007); the monitor's page is linked and shows built-in forms (JRN-008); the journey set covers approval, SAE, visits, close, EDC sign and the monitor visit (NEW-JRN-20). UI: the mark bar on the desktop (UX-001); session expiry keeps the note (UX-007); per-user language; week-list latency after a box measurement (UX-010) | S to M each |
| E | Outputs: PDF glyph fallback (UX-002); localised, printable workbooks (UX-003); a BOM on every CSV; one decoder for every text upload with Shift_JIS and Big5 cases (UX-004) | M, M, S, S |
| E | EDC in copy mode: source-changed flag (EDC-004); the human's correction read back (EDC-005); retire a removed item (EDC-006); era and ROC dates in prefill | M, M, S, S |
| D | T-317 guides in ja and zh-TW served from Help; acceptance gains capacity and power-cycle criteria | M, S |
| all | Burn down the `KNOWN` table of expected failures, one card per line (ENG-005); raise the mutation floor after each complete nightly (ENG-006) | L, split |

### Wave 5: 2027-03-01 to go-live. Sites; fixes only

Site boxes installed (T-315b), connected, mapped on a real extract with the per-study code-coverage report as the
exit (NEW-DIN-17), the first real night, the dry run (T-315c), the journeys on the site's box, training, acceptance.
No new feature card starts in this wave. The API send to REDCap (whole-instance writes, checkbox columns, per-record
fallback, attempt ledger: EDC-002, EDC-003, EDC-007, EDC-008) is built here only if wave 4 ended on time; otherwise
it is the first work after go-live.

## 6. What "done" means for a card in this plan

A card is **accepted** when its acceptance test exists, could fail, and runs in a required CI job; "merged" is
counted apart (PLAN-014). Nine merged cards are reopened as not accepted: T-004, T-012a, T-114, T-650, T-652,
T-206a, T-212c, T-656, T-664. Status is generated from the registry and the pull requests, not written by hand
(NEW-PLAN-5, S).

## 7. What must be measured

### 7.1 On the GCP GPU VM (owned by the cloud-run session; this plan sends it the list)

Thresholds come from the night window and the data size, not from a fixed figure. With an 8-hour night, 50,000
patients × 5 studies needs at least 1.66 pair calls per second and 500,000 × 1 study needs 3.3 (LLM §7).

| Id | Test | Record | Pass |
| --- | --- | --- | --- |
| G-1 | Chat template identity: the template the compose file passes against the weights folder's own; token identity on 20 prompts | sha256 of both; differing tokens | identical, or the accuracy runs are repeated with the shipped one |
| G-2 | The real offline bundle → `box-install.sh` → first-run wizard answers only → `pin_model --install rtxpro6000` on real folders → full `qualify` → `--promote`; serving capture; vLLM host RSS | manifests, the qualification record, minutes per step, every stop | PRODUCTION resolves `judge` and `verifier` to promoted builds; no step needed a shell beyond the installer |
| G-3 | SCREEN on 50,000 synthetic patients (ja, then zh-TW) at 1, 4, 8, 16, 32, 48 sequences in flight; vLLM `/metrics` and `nvidia-smi` every 10 s | calls/s, tokens/s, p50/p95 latency, GPU utilisation and memory, breaker openings; the candidate list per setting | the candidate list is identical at every setting; calls/s at the chosen setting meets the window above |
| G-4 | Eager start on and off; the structured-output backend named; guided decoding overhead | calls/s each way; schema failures | no schema failure; the faster setting is the profile |
| G-5 | Real against estimated token counts through `/tokenize` on 200 ja and 200 zh-TW excerpts | the ratio's p50, p95, max | the budget uses the measured ratio; no sized prompt is refused |
| G-6 | The whole night at 50,000 with the dense profile under the default memory caps: ingest, rebuild, screen, backup | seconds and peak memory per step; OOM kills | no kill; the night fits the window; else the capacity statement says what fits |
| G-7 | Pair verdicts on the clipped against the whole note for the LLM-001 cases (family history under the wrong heading; a denied list without its lead-in) | verdict per case, before and after NEW-LLM-1 | 0 exclusions on a clipped note |
| G-8 | Compile two real public protocols (RA, early AD) with the production judge | class split, `needs_review`, `time_sensitive` per criterion | no extension-phase line active without a warning; alternative diagnosis groups not flattened to AND |
| G-9 | Restart and outage inside a 16-way screen: `docker restart` of the orchestrator, the adapter and the judge; a power cycle | final job state, calls repeated, whether `CURRENT` moved, seconds to healthy | the job resumes; no call is paid twice beyond the in-flight ones; nothing is half-published |
| G-10 | The vLLM image move: the 54-case pair canary and the qualification on the new image | 54/54, schema failures, calls/s against G-3 | 54/54; speed within the run-to-run spread of G-3 |
| G-11 | The embedder in PRODUCTION: start, RSS, chunks per second on 50,000 patients' notes | seconds, memory, chunks/s | the index builds inside the night window |

### 7.2 On the owner's hardware

| Id | Where | Test | Pass |
| --- | --- | --- | --- |
| P-1 | Reference RTX PRO 6000 box | Timed install from a wiped disk by the handbook only | first sign-in with no step the owner cannot do |
| P-2 | same | G-2, G-3 and G-6 repeated on the Workstation Edition card | capacity statement within its stated spread of the VM's |
| P-3 | same | Restore on a second machine at 50,000 patients with the recovery copy of the key | pseudonyms equal; the measured time becomes the stated RTO |
| P-4 | same | Thermal, power and noise soak for one full night; a power cut during a night job | no throttle that breaks the window; the box returns unattended and the job resumes |
| P-5 | same | Week-list and mark latency at about 80 and 400 listed patients, with and without a running job | recorded; the limit is derived from it |
| P-6 | Real REDCap (Q5) | The nine tests R1 to R9 of `10-redcap-edc.md` §8 | each by its own rule |
| P-7 | CGMH, one day of the real export; Japan, one month of real SS-MIX2 | `tools/mapping_check.py`: date formats, unmapped codes, unit spellings, duplicates, repeated order numbers | the per-study code-coverage report (NEW-DIN-17) |
| P-8 | Windows with Japanese and Traditional-Chinese locale | Open the four CSV/XLSX downloads in Excel; print preview of the screening log | no mojibake; the log prints on A4 |
| P-9 | B200 (bench only), Spark (only if bought) | B-1 to B-5, S-1 to S-6 of `13-final-build-hardware-install.md` §8 | not on the critical path |

## 8. What the dates rest on

1. The box order by 2026-12-18, and so the run of section 7.1 by 2026-12-11.
2. Scope: the cuts of section 3. Without them the code does not reach 2027-02-26.
3. The CGRD connection starting in December behind T-723.
4. A real REDCap from the owner, or copy-assist is the go-live form (it is the default here).
5. Real extracts from both sites by mid-March for the mapping content; the review found that every date, code and
   unit defect so far was invisible on synthetic data.

## 9. Change history

| Date | Change |
| --- | --- |
| 2026-11-12 | First draft from the deep review of 2026-11-12. |
