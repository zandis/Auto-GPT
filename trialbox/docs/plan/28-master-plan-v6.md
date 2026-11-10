# TB-PLAN-06 Master plan v6: a clinician PoC in four weeks, two hospitals live in spring 2027

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-06 |
| Version | 1.0 (draft for the owner's approval) |
| Date | 2026-11-10 |
| Owner | Changfu Kuo (Aimedics) |
| Status | **Proposed.** It replaces `25-master-plan.md` (TB-PLAN-05 v1.2) as the working plan once the owner approves it at G0 (Fri 2026-11-13). Until then TB-PLAN-05 v1.2 stays in force. |
| Basis | The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/`, TB-DR-00 to TB-DR-11); TB-PLAN-05 v1.2; the status file `26-status-2026-11-10.md`; TB-ASSESS-01 (67 cards); the critical-issues register TB-REG-01 (PR #73); the owner's facts of 2026-11-10 (§1.4). |
| Code read | `origin/master` at `ca8f287` |
| What carries over unchanged | TB-PLAN-05 v1.2 §1.2 (intended use), §5 (URS outline), §7 (validation plan, with the `25-vmp.md`), §9 (security and privacy plan), §10 (release), §12 (operating model), §14 (answers to the independent review). They are not repeated here. Where this plan and TB-PLAN-05 differ, this plan wins. |
| Companion | `27-poc-plan.md` (TB-POC-01): the PoC design, procedures, scripts and feedback loop. |

How to read it. §1 is the scope and what changed. §2 is the gates and the calendar, with the PoC as a new early gate. §3 is the critical path. §4 is capacity. §5 is the risk delta. §6 is the reorganised task list as cards, with the conflict matrix. §7 is the test strategy. §8 is the standards compliance matrix. §9 is the dependency upgrade plan. §10 is the questions for the owner. §11 lists the assumptions this plan makes where the owner's request was silent.

## 1. Scope

### 1.1 The one-page reading of the deep review

Twelve reviewers looked at the product from twelve sides on 2026-11-10; six of them ran it. The index (`docs/reviews/2026-11-10-deep-review/00-index.md`) has every finding. The reading that shapes this plan:

1. **The engine works on synthetic data; the product around it is not yet a product a clinician can be handed.** `make e2e-simple`, the backup drill and the restore pass. But none of the nine scope items of TB-PLAN-05 §1.1 is fully done: of 92 user requirements, 13 are done, 43 partial, 33 missing and 3 contradicted (TB-DR-01).
2. **Several defects can produce a wrong screening answer without any sign.** A lab value keeps the lookup's unit, not its own (STD-001; the fix is in PR #70, not merged). When the judge server fails, the gateway answers for the judge with the verifier's model, which then agrees with itself (LLM-002, new). A night with a missing feed file passes and becomes the served snapshot (DATA-001, new). These three, with the register's Blockers, are the first work after the PoC prerequisites.
3. **The hosted demo cannot be given to the two clinicians as it is.** It does not start from a clean build (OPS-001, ROLE-002). A password alone opens a session even with the second factor on (ROLE-001). All roles share one password. A tester can paste or upload real chart text (REG-014, OPS-004). Japan's real trial type, early Alzheimer's disease, has no ruleset, no synthetic patients and no Japanese protocol (LIFE-001).
4. **What was told to the IRBs and to hospital IT is ahead of the code.** The amendments filed on 2026-11-10 and the IT pack state as fact controls that are not built (REG-010, FIT-005, OPS-040). This is the largest non-code risk the review found, and it is new.
5. **The dates are set by the hospitals, not by code**, as TB-PLAN-05 said. But the chains are tighter than it showed. At CGMH the IRB approval, the HIS export build and the notes tier run in series, not in parallel (PLAN-001). Contracts are not engaged and their latest start has passed or is days away (PLAN-002). The owner is the only person in eight roles (PLAN-003).
6. **The Python dependency set is in good order** (176 of 201 current, no advisory). The risks are in the Java jars, the GPU images, the model weights and the build tools (TB-DR-08).

### 1.2 What goes live (unchanged in content, defined per site)

The nine scope items of TB-PLAN-05 §1.1 stay. "Full scope" was never defined per site, so a gate could not test it. This plan defines it with three levels: **Used** (a real case during PQ), **Drilled** (a test record or a synthetic event at OQ or PQ, because a real event cannot be ordered), **Not applicable**.

| Scope item | CGMH (go-live Wed 2027-04-28) | Japan (go-live Thu 2027-05-13) |
| --- | --- | --- |
| 1 Whole-hospital screening on the site's feed with the real model pair | Used. Feed: the HIS export, tiers 1 to 3; NHI codes; ROC dates | Used. Feed: SS-MIX2 plus notes by the vendor route; JLAC10; MEDIS masters |
| 2 Delegation, candidate view, referral | Used (at least one referral through a treating physician) | Used |
| 3 OMOP core, lake exported from it, provenance, conflicts, vocabulary | Used (flag on); at least one conflict resolved by the steward | Used |
| 4a Profiles: cited page, twin, annotations, vectors, "patients like me" | Used for study patients | Used |
| 4b Setpoints and gap finder | Built, **off** at go-live (owner question Q-06) | the same |
| 5 REDCap prefill under GAMP 5 | Used on one study whose sponsor acknowledgement is on file (choose an investigator-initiated study); otherwise copy-assist, Drilled | Used |
| 6 Steward role, data-operations console, statistics page | Used | Used |
| 7 Catalogue and specialty templates | Used: the templates of the pilot studies' specialties | the same |
| 8 Opt-out, IRB and ICF warnings, delegation-log comparison, SAE clocks, reminder card, inputs for accountability, TMF, invoicing | Opt-out and SAE: Drilled unless a real one occurs; the rest Used | the same |
| 9 Platform: MFA, backups, signed audit heads, release identity, SBOM | Used. Shared-host isolation and key unseal: Used. Windows/WSL2 hardening: Not applicable | Used. Windows/WSL2 hardening and disk encryption: Used. Shared-host isolation: Not applicable |
| Monitor source-data verification, break-glass | Drilled | Drilled |
| Consortium | Synthetic two-box test only | the same |

### 1.3 What is new in scope

| New item | Why | Where |
| --- | --- | --- |
| **The clinician PoC (gate GP)** | The owner wants Dr Makoto and Dr Wenn testing soon. Their feedback must reach the design freeze. | §2, `27-poc-plan.md`, cards T-501 to T-516 |
| **A commitments register** | Every promise in the filed IRB amendments, the IT pack and the opt-out notices is listed with the code and test that keeps it, or is corrected by a supplement before the first committee meeting. No real data until every row is green. | T-641; G2 and G4 entry |
| **Feed completeness as a safety function** | A partial night must stop, not publish. | T-611 |
| **The gateway never answers one role with another role's model** | The two-model check is the product's main safety argument. | T-601 (with fix group D-276) |
| **Site study catalogue** | The plan never recorded which studies each PI runs. The PoC and PQ need it. | owner question Q-02; T-503, T-504 |
| **Deputies and a conflict-of-interest ruling** | One person holds eight roles. | §3, §5 (RSK-53, RSK-54), Q-08 |

### 1.4 The owner's facts of 2026-11-10 and their effect

| Fact | Effect on the plan |
| --- | --- |
| Go-live: CGMH Wed 2027-04-28, Japan Thu 2027-05-13, full scope | Unchanged targets. Named fallback dates are proposed (Q-09). TB-PLAN-05's "Fri 2027-05-14" header for Japan is corrected to Thu 05-13. |
| CGMH hosts on its own shared B200 | WS-11.8 stays. PR #85 needs two MIG instances where the plan asked for one (LLM-027, OPS-067): the request to CGMH changes. The platform kind (Kubernetes, Slurm, plain Docker) is still unknown (OPS-066): asked in the first IT meeting. |
| The owner's own B200 does the G1b qualification (not a cloud B200) | Card T-114 is rewritten: an offline bundle and one script the owner or a named operator runs; a host fingerprint in the record; two MIG layouts. No rental cost. A new risk: the host differs from CGMH's (RSK-52). |
| The GCP project has one GPU; the increase was refused | G1 runs on one RTX PRO 6000 spot VM: about 9 hours per 50k run, with pre-emption. No parallel fan-out. A GPU ledger queues the six or more long runs before G3. The 50k functional run moves to the owner's B200 where possible (T-004). Register row CR-070 is closed as moot. |
| Japan gets one box; the DGX Spark benchmark decides its form | Kept. The Japan hardware chain has zero float at the planned order date of 01-08 (PLAN-006). The plan proposes deciding on 12-18 from measured G1 numbers and a short Spark run (Q-05). The Spark compose file pins an image built for a different chip (DEP-003): fixed before the benchmark. |
| IRB amendments submitted 2026-11-10 | Ten days ahead of plan. New work: compare the filed text with the code and with owner decision #74 and send a supplement before the first meeting (T-641, REG-010). The Japan text was written on the ethical guidelines before their 2026 amendment (REG-002): check. |
| Contracts and hospital IT not engaged | Behind. They are now the critical path with the feeds (§3). Start dates this week are in §3.2. |
| Data rule: synthetic and public data only | Kept everywhere. The PoC adds a technical control: the hosted demo refuses uploads and pasted chart text, shows a banner and holds an acknowledgement (T-502). |
| Steward is a separate role; admin sees patient data only by break-glass | Not built yet: admin still reveals chart numbers and exports them (ROLE-010, CR-023, CR-029). T-102 and T-309 are in wave 1. In the PoC the admin account is the owner's only. |
| Safety invariants | Unchanged, and each gets a property test (§7). LLM-002 breaks the two-model invariant today. |

### 1.5 Not in the pilot

As TB-PLAN-05 §1.3. Proposed additions, all off or synthetic-only on go-live day, to be dated to the first release after go-live if the owner agrees (Q-06): setpoints and the gap finder and the clinician view of them; consortium work beyond the synthetic two-box count test; taking HAPI out. About 30 agent sessions and two S4 risks leave the go-live path.

## 2. Gates and dates

### 2.1 Gates

Each gate gets a record file (`docs/validation/gates/<gate>.md`, card T-661) with criterion, measure, evidence, result, signer and date. A gate without its record is not passed. Every gate record states the register condition: the count of open Blocker, Critical and High rows in TB-REG-01 and in the deep review on that day.

| Gate | What must be true | Planned | Decided by |
| --- | --- | --- | --- |
| **G0 Plan v6 approved** | The owner approves this plan and answers §10. Each owner chain of §3 has a start date or a dated promise. The open PR queue has a merge order (§6.4). | Fri 2026-11-13 | Changfu |
| **GP-0 PoC build freeze** | Tag `poc-1` on master, CI green. No open Blocker or Critical on the PoC path (§6.2, wave P). The hosted demo boots from the tag by digest, over HTTPS, with per-tester accounts and a second factor. Uploads and chart paste are refused. The banner and the acknowledgement are on. In-product feedback works. The site scenarios are loaded in ja and zh-TW. | Fri 2026-11-27 | Changfu, the integrator |
| **GP-1 PoC dry run** | The owner walks every task of both scripts in three languages. Every task completes. The data-handling statement and acknowledgement are final in ja and zh-TW after a native read. | Tue 2026-12-01 | Changfu |
| **G1 The 50k run** | As TB-PLAN-05, changed: one spot VM with a proven resume after a forced pre-emption; the 50k functional run on the owner's B200; LLM-002 fixed first, or the run does not count; the gate record names the commit, the wall time and the pre-emptions. | Fri 2026-12-04 | Changfu, the safety-core engineer |
| **GP PoC sessions** | Both clinicians complete their scripts (`27-poc-plan.md` §5). Exit: every task attempted by both; at least 80 % of tasks completed without help; no finding rated "would cause a wrong patient decision" left without a fix card; every finding triaged. | Tue 2026-12-08 to Fri 12-11; exit review Mon 12-14 | Changfu, Makoto, Wenn |
| **G1b B200 qualified** | The `shared-quota` record from the owner's B200, two MIG layouts, with the host fingerprint. | Fri 2026-12-11 | Changfu |
| **Japan hardware decision** | Form A or B chosen from the numbers; the order placed; device registration filed. | Fri 2026-12-18 (moved from 01-08; Q-05) | Changfu, Makoto |
| **G2a Platform freeze** | As TB-PLAN-05 G2 for the platform items. Added: every Blocker and Critical row closed; the commitments register has no red row; the PoC findings rated "before G2" closed; the traceability matrix shows status from evidence, not "planned". | Fri 2027-01-08 | Changfu, the safety-core engineer |
| **G2b Site and people freeze** | Both surveys signed; feed tiers dated with a named hospital owner; contracts with hospital legal at both sites; the safety-core engineer, the CGMH second reviewer and the deputies named; the conflict-of-interest ruling on file. | Fri 2027-01-08 | Changfu, Makoto |
| **GP-2 PoC with real models** (optional, recommended) | Two weeks on the owner's B200 behind the same front door, synthetic data, the real pair. The clinicians judge note reading. Only after G1 and G1b. | Tue 2027-01-12 to Fri 01-22 | Changfu |
| **G3 Feature complete** | As TB-PLAN-05. Added: 0 open Blocker, Critical or High rows; the backlog file prints 0 open cards for G3. | Fri 2027-02-26 | as TB-PLAN-05 |
| **G4 IQ/OQ per site** | As TB-PLAN-05. Japan real-data OQ starts when the contract is in force (proposed 04-01, Q-10). | CGMH 03-15 to 03-26; Japan 03-22 to 04-09 | as TB-PLAN-05 |
| **G5 PQ / UAT** | As TB-PLAN-05. | CGMH 03-29 to 04-23; Japan 04-12 to 05-12 | as TB-PLAN-05 |
| **G6 Readiness review** | As TB-PLAN-05 §4.5. Added to the non-waivable list: the commitments register green; a named deputy for the steward; the conflict-of-interest ruling. | CGMH Fri 2027-04-23; Japan Wed 2027-05-12 | as TB-PLAN-05 |
| **Go-live** | | **CGMH Wed 2027-04-28; Japan Thu 2027-05-13** | |

### 2.2 Calendar

Holidays marked "confirm" were not checked against the official 2027 calendars (T-662 puts the calendar in a data file with a weekday test).

| Date | Day | What |
| --- | --- | --- |
| 2026-11-10 | Tue | IRB amendments filed at both sites (done). Deep review closed. |
| 11-13 | Fri | **G0.** This week: the conflict-of-interest disclosure to CGMH; the HIS work request under the existing approval; contract templates requested at both hospitals; first IT meetings requested; the search for the safety-core engineer and an operations person started; the list of each PI's studies (Q-02). |
| 11-16 to 11-27 | | Wave P: the PoC prerequisites (§6.2). The open PR queue drained in the order of §6.4. |
| 11-20 | Fri | Latest P50 start for contracts and IT review at both sites. Survey ① answers. The supplement to the amendments, if the comparison finds differences (T-641). |
| 11-23 | Mon | 勤労感謝の日 (Japan) |
| 11-24, 11-27, 12-01 | | G1 attempt windows on the one spot VM (about 9 h each); three attempts budgeted. |
| **11-27** | Fri | **GP-0 PoC build freeze**, tag `poc-1`. |
| 11-30 | Mon | The hosted demo is up; accounts issued; the statement sent to the testers. |
| **12-01** | Tue | **GP-1 dry run** by the owner. |
| 12-02 or 12-03 | | Optional guided first look: 30 minutes per clinician on a call, the owner drives, to settle language and scope before the hands-on week. |
| **12-04** | Fri | **G1.** Decision point 1 for the fallback dates. |
| **12-08 to 12-11** | Tue to Fri | **GP PoC sessions.** |
| 12-11 | Fri | **G1b** on the owner's B200. |
| **12-14** | Mon | **GP exit review**: the triaged list. |
| 12-18 | Fri | Japan hardware decision and order; registration filed; pentest firm booked. Last useful day for a second PoC session before the year end. |
| 12-25 | Fri | 行憲紀念日 (Taiwan; confirm) |
| 12-29 to 2027-01-03 | | 年末年始 (Japan) |
| **2027-01-08** | Fri | **G2a and G2b.** Decision point 2. |
| 01-11 | Mon | 成人の日 (Japan) |
| 01-12 to 01-22 | | GP-2: the PoC with real models on the owner's B200 (optional). |
| 02-04 to 02-10 | | Lunar New Year (Taiwan; confirm 02-04) |
| 02-11 | Thu | 建国記念の日 (Japan) |
| 02-12 | Fri | Feed tier 1 at both sites (only if the CGMH export build started in November) |
| 02-23 | Tue | 天皇誕生日 (Japan) |
| **02-26** | Fri | **G3.** Decision point 3. |
| 03-01 to 03-12 | | Pentest pass 2; the G1 re-run on the release (book the one GPU). |
| 03-12 | Fri | Hard date CGMH: contract, DPA, amendment approved. Japan box on site and registered. |
| 03-15 to 03-26 | | G4 CGMH: IQ, OQ, five nights; tier 3 on 03-19; dry run 03-22 to 03-26. |
| 03-22 to 03-31 | | G4 Japan IQ on synthetic data (年度末: light load on the site). |
| 04-01 | Thu | Japan contract and DPA in force (proposed; new fiscal year, staff rotate). |
| 04-01 to 04-09 | | Japan OQ on the second real sample; dry run; blind re-entry. |
| 03-29 to 04-23 | | G5 CGMH PQ (18 working days; 清明 04-05, probably 04-06: confirm). |
| 04-12 to 05-12 | | G5 Japan PQ (13 working days before Golden Week, 5 after). |
| 04-23 | Fri | G6 CGMH. |
| **04-28** | Wed | **CGMH go-live.** (Fri 04-30 may be a day off in Taiwan: confirm; if so consider Mon 04-26.) |
| 04-29 to 05-05 | | Golden Week (Japan) |
| 05-12 | Wed | G6 Japan. |
| **05-13** | Thu | **Japan go-live.** |
| 05-19 / 05-27 | | Proposed named fallback dates, CGMH / Japan. Used only by a dated owner decision (Q-09). |

### 2.3 Weeks to the PoC, day by day

| Days | Build (agent sessions) | Owner |
| --- | --- | --- |
| Wed 11-11 to Fri 11-13 | Merge #86, #78, #64, #70, #73 (clean and small). T-002 (decisions as files, number registry). T-501 starts (demo boots). | G0. The answers of §10, above all Q-01 (testers), Q-02 (study lists), Q-03 (hosting cost). The five chain starts of §3.2. |
| Mon 11-16 to Fri 11-20 | T-501, T-502, T-505, T-506, T-510 (the demo, PoC mode, accounts, wording, feedback). T-503 and T-504 start (the AD and RA scenarios). Fix groups D-270 to D-278 merge as they finish. T-601 (gateway). | Read the ja and zh-TW wording of T-506 (Makoto, Wenn or a native reader). Contracts and IT requests sent. |
| Tue 11-24 to Fri 11-27 | T-503, T-504 finish. T-507 (labels in ja and zh-TW). T-508 (scripts and forms). T-509 (hosting scripts). Freeze on Fri. | Approve the hosting cost. Approve the statement. Invite the testers; book the sessions. |
| Mon 11-30, Tue 12-01 | Deploy; smoke; the dry run's fixes only. | Dry run. Issue accounts. |
| Wed 12-02 to Fri 12-04 | G1. No PoC change except a dry-run Blocker. | Optional first look. G1. |
| Tue 12-08 to Fri 12-11 | A session on call for each PoC session (fix nothing live; log). G1b. | The sessions. |
| Mon 12-14 | Triage into cards. | GP exit review. |

## 3. The critical path

### 3.1 The chains, with float

The chains are those of TB-PLAN-05 §4.3, redrawn per site with their real dependencies (TB-DR-10 §4). Durations are estimates (P50 / P90); no hospital office was asked. Float is counted from 2026-11-10. Negative float means the date is already missed at that duration.

| Chain | Need by | Duration P50 / P90 | Float P50 / P90 | State today | Critical |
| --- | --- | --- | --- | --- | --- |
| **CGMH-A** IRB approval → HIS export build → tier 3 notes, in series | tier 3 on 03-19 | IRB 6 / 13 wk, then build 13 / 17 wk | **−0.5 wk / −11 wk** | IRB filed; the build has no owner | **Yes** |
| CGMH-A′ the same, with the export mechanism started now under the existing approval for the PI's own department | tier 1 02-12; tier 3 03-19 | build 13 / 17 wk | +4 wk / 0 | not started | Yes |
| **CGMH-B** conflict-of-interest ruling → contract and DPA | 03-12 | 13 / 20 wk | +3.5 wk / −3.5 wk | not engaged | Yes |
| CGMH-C IT security review → namespace, MIG, storage, network policy | 02-26 | 9 / 15 wk | +6.5 wk / +0.5 wk | not engaged | Near |
| CGMH-D IRB amendment alone | 03-12 | 6 / 13 wk | +11.5 wk / +4.5 wk | filed 11-10 | No (it feeds A) |
| CGMH-E G1b record on the owner's B200 | 01-08 | 3 / 6 wk | +5.5 wk / +2.5 wk | T-012 not started | No |
| **Japan-A** hardware decision → order → delivery → registration | on site 03-12 | 9 / 13 wk from the order | 0 / −5 wk with the order on 01-08; **+3 wk / −2 wk with the order on 12-18** | Spark not confirmed bought | **Yes** |
| **Japan-B** contract and DPA | 03-26 (proposed 04-01) | 17 / 26 wk | +2.5 wk / −6.5 wk | not engaged | **Yes** |
| Japan-C IT review and device registration | 03-12 | 9 / 15 wk; cannot start before the form is known | 0 / −6 wk; +3 / −3 with 12-18 | not engaged | Yes |
| Japan-D IRB amendment | 03-26 | 13 / 19 wk | +6.5 wk / +0.5 wk | filed 11-10 | Near |
| Japan-E notes tier through the EMR vendor | 03-26 | 8 / 20 wk | +10 wk / −0.5 wk | unknown until the survey answers | Unknown: answer by 11-20 |
| People: the safety-core engineer | G1 (proposed) | 4 / 8 wk to find | +4.5 wk / +0.5 wk | search not confirmed started | Near |
| People: the owner's hours | every week | about 14 h a week on the chains alone until 12-25 | 0 | saturated | **Yes** |
| Code to G3 | 02-26 | 170 to 210 sessions against 195 to 290 verified merges | +2 wk / −1 wk | ahead of TB-PLAN-05 | No at P50 |
| Sponsor acknowledgement for the PQ prefill study | PQ start | 8 / 20 wk | +12 wk / 0 | not started | Avoided by choosing an investigator-initiated study |
| **The PoC** (new) | sessions 12-08 | 12 working days of wave P | +1 wk to the latest useful date 12-18 | starts at G0 | Yes for GP only; it does not move a go-live |

Reading. The critical path is not code at either site. At CGMH it is amendment → export build → notes, with the contract close behind. In Japan it is hardware and contract together, squeezed between the year end, the fiscal-year turnover on 04-01 and Golden Week. The owner's hours are the one resource every chain shares.

### 3.2 Latest starts, for the owner's diary

- **By Fri 11-13:** the conflict-of-interest disclosure to CGMH; the HIS work request under the existing approval (Q-11); contract templates requested at both hospitals; the first IT meeting requested at CGMH; the engineer and operations-person searches; the PIs' study lists (Q-02).
- **By Fri 11-20:** contract drafts with CGMH legal; Makoto's answers on the notes route, the private cloud and who rotates on 04-01; the Spark bought or dropped; the supplement to the amendments if needed.
- **By Fri 11-27:** the Japan contract request with the hospital; T-012 `qualify` merged; counsel engaged.
- **By Fri 12-18:** the Japan hardware ordered and its registration filed; the pentest firm booked; G1b done.

### 3.3 The tracker

One table, `docs/plan/owner-chains.md` (card T-663), holds each chain's steps with the start date, the evidence, the need-by date and the float. The status file prints, on its first screen, any chain past its latest start with no start date. It holds no patient data and no personal contact details.

## 4. Capacity

| Resource | Supply | Demand to G3 | Reading |
| --- | --- | --- | --- |
| Agent sessions | several in parallel; not a limit | 170 to 210 sessions for the cards of §6 | fits |
| The integrator: verified merges | sustainable 3 to 4 a day with a rebase, the full suite and an adversarial read: 195 to 290 to G3 | 170 to 210, plus re-merges after conflicts | fits at P50 with about 15 % margin; fails if conflicts stay at today's rate (9 of 14 open PRs conflict with master) |
| The open queue today | 14 PRs, about 55,000 added lines | 4 to 5 working days to drain | drain in the order of §6.4 before a wave-2 card opens on a hot file |
| The owner | 14 h a week (plan) | about 14 h a week on the non-code chains to 12-25, plus the PoC (about 12 h in the three PoC weeks) | **over-committed.** The plan needs an operations person from December (Q-08) and delegates build review to the safety-core engineer and to agent adversarial review |
| Makoto | 14 h a week (plan) | survey, contract, IT, feed, IRB follow-up; the PoC (about 4 h); URS approval | probably full: ask |
| Wenn | not in TB-PLAN-05 | the PoC (about 4 h); later PQ | ask at the invitation |
| Safety-core human review | 0 today (nobody named; no CODEOWNERS) | every change to the six safety-core files, `authz`, the prefill path; the G1 signature | **uncovered until named** |
| GPU: one RTX PRO 6000 spot VM | 1 VM, pre-emptible | at least 6 long runs before G3: the short run, G1 (up to 3 attempts), the profile and embedding tests, the 31B bake-off, the injection suite on the pair, the release re-run | serial, 60 to 90 GPU-hours; fits only with a ledger (T-664) |
| GPU: the owner's B200 | 1 machine; operator = the owner (assumed) | G1b on two MIG layouts; the 50k functional runs; the acceptance drills; GP-2 | fits if a second operator exists (Q-12) |
| The shared build machine and CI | 4 cores, 15 GB | the full suite per merge | measured in TB-DR-04; print the wall time in the status file |
| Wave P (to the freeze, 12 working days) | 36 to 48 verified merges | 25 cards, 13 queued PRs and up to 11 fix groups: 49 merges | **over.** Before the freeze merge only what the PoC path needs (the clean PRs, T-002, six fix groups, the 25 cards: 36 merges); drain the rest in the week of 11-30 (§6.6) |
| Findings | this review adds 455 rows of all severities to the register's 115 | the fix rate so far is about 20 rows a day | inflow is above outflow this week. Rule: after G0, a new review wave opens only at a gate; between gates the register only shrinks |

## 5. Risks

TB-PLAN-05 §6 stays the risk file. The rows below are added or changed (ISO 14971 style: S1 to S4 for harm, P1 to P4; project rows give weeks of slip). The review also found that two risk files on two scales exist and that some residual risks are claimed at P1 for controls that are not built (REG-028): card T-644 makes one file, with a residual only where the control has a passing test.

### 5.1 New rows

| ID | Hazard | Harm | S | P | Controls | Verified by | Residual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RSK-51 (project) | The only cloud GPU is one pre-emptible VM | G1 slips; qualification after a prompt or model change is skipped | 1 to 3 wk | P4 | resume proven by a forced pre-emption in the rehearsal; three budgeted attempts; the 50k functional run on the owner's B200; the GPU ledger | the rehearsal case; TST-G1 | P2 |
| RSK-52 | The qualification host (the owner's B200) differs from CGMH's partition | PQ cannot start, or a silently degraded judge at CGMH | S3 | P3 | host fingerprint in the record; two MIG layouts; re-measure at IQ; `doctor --platform` compares | TST-MOD-01, TST-IQ-03 | S3 P1 |
| RSK-53 (project) | The owner is away for two weeks or more. He alone approves, pays, signs, runs the B200, administers the cloud project and the repository, and is steward and PI | every chain stops; after go-live no steward for opt-outs, conflicts, key unseal | 2 wk or more; S3 after go-live | P3 | a named deputy per role; a second admin on the cloud project and the repository; a second B200 operator; the hypercare rota without the owner in one slot | a tabletop "owner away" | P2 / S3 P1 |
| RSK-54 | Conflict of interest: the vendor's owner is the hospital's physician, site PI, steward and Study A PI | contract delayed or void; an IRB finding; Study A not credible; no real supervision of the processor | S3 | P4 | written disclosure and CGMH's ruling before legal review; a different signer; an independent co-investigator for the Study A reading; the second reviewer | the ruling on file | S3 P2 |
| RSK-55 | A clinician enters or uploads real patient information into the hosted PoC | a privacy breach before any contract | S4 | P3 | uploads and chart paste refused in demo mode; banner; the acknowledgement; an identifier scan of stored input after each session; the demo destroyed after the PoC | a planted-identifier test (T-502) | S4 P1 |
| RSK-56 | The PoC misleads: clinicians judge accuracy from synthetic patients or stub answers; or one poor session re-opens the scope | wrong confidence either way; churn before the freeze | S2 | P3 | the script says what the PoC can and cannot show; stub results are labelled; exit criteria and the triage rule are fixed before the sessions; real models only in GP-2 | the GP record | S2 P1 |
| RSK-57 | The IRB text filed on 11-10 and the IT pack promise controls that are not built, or no longer match the product | processing outside the approval; a second amendment that misses the hard date; loss of the hospital's trust | S4 | P3 | the commitments register (T-641); a supplement before the first meeting; no real data while a row is red; a freeze on data-use changes unless the PI checks the filed text | G2 and G4 entry | S4 P1 |
| RSK-58 (project) | The hospital's export build waits for the amendment and the contract | tiers late by the length of the approval | 4 to 12 wk | P3 | start the mechanism under the existing approval; a named HIS owner; weekly check-in; the fallback date announced at G1 if there is no owner | the tracker | P2 |
| RSK-59 (project) | Japan's fiscal-year turnover on 04-01 during IQ and OQ | signatures repeated; training lost | 1 to 3 wk | P3 | contract in force 04-01 by design; light on-site load 03-22 to 03-31; training after orientation week | G4 Japan record | P2 |
| RSK-60 (project) | Hospital IT refuses a PRC-origin model | the verifier is replaced and re-qualified on one GPU | 3 to 6 wk | P2 | ask in the survey now; keep a second verifier candidate measured in the bake-off harness | TST-MOD-01 on the candidate | P1 |
| RSK-61 (project) | The Japan box lacks the marks and procedures a Japanese hospital requires (PSE, importer, asset loan, on-site warranty) | registration refused | 2 to 6 wk | P3 | buy in Japan from a domestic vendor; ask the asset procedure in the survey | TST-IQ-01 | P1 |
| RSK-62 | One integrator and a stale queue: a wrong conflict resolution in a hot file lands unnoticed | a regression in a safety or privacy path | S4 | P3 | decisions as files; generated files regenerated, never hand-merged; one card per PR; the merge order of §6.4; goldens; the CI gate | TST-CI-01, TST-GOLD-01 | S4 P1 |
| RSK-63 (project) | Findings arrive faster than fixes and a gate's register condition is waived to keep a date | known defects shipped into PQ | S3 | P3 | the register condition in every gate record; review waves only at gates | the gate records | S3 P1 |
| RSK-64 (project) | CGMH hypercare, Japan PQ's last week, Japan's G6 and go-live fall in 15 days across Golden Week, on one owner | an incident or deviation goes unhandled | S3 | P3 | deputies; the journeys to re-run after the break named in the PQ protocol | TST-PQ-01 | S3 P1 |
| RSK-65 | The gateway answers the judge role with the verifier's model when the judge fails, and the pair reports agreement (LLM-002) | a wrong exclusion or inclusion passes the two-model check | S4 | P3 | no cross-role fallback; a failed role is "unknown"; the response carries the serving build and the pair check compares builds (T-601, with D-276) | a fault-injection test on the stub and on the pair | S4 P1 |
| RSK-66 | A night with a missing or empty feed table is published and older good snapshots are pruned (DATA-001) | patients silently lose data; candidates vanish or wrong exclusions appear | S4 | P3 | a completeness gate before publish (table present, volume within a band of the last good night); keep the last good snapshot; the readiness page shows the refusal (T-611) | a fault-injection test per table | S4 P1 |
| RSK-67 | The site key file is missing and a new key is made silently; every pseudonym changes and opt-outs are lost (DATA-004) | an opted-out patient is screened | S4 | P2 | never create a key outside the install ceremony; the ingest refuses when the key fingerprint differs from the stored one (T-612) | a test that removes the key | S4 P1 |
| RSK-68 | A lab row keeps the lookup's unit, not its own (STD-001); Japanese qualitative results are unmapped (STD-022) | a wrong numeric comparison; criteria never decided | S4 | P3 | read the row's unit and convert or mark unknown (PR #70, then T-613); a qualitative map for ja | the unit matrix test; the mapping coverage report | S4 P1 |
| RSK-69 | The demo or the product is reachable with a password alone through the API session route (ROLE-001) | account takeover of an admin | S3 | P3 | the API session route enforces the second factor; a per-IP throttle (T-505) | a test with TOTP on | S3 P1 |
| RSK-70 (project) | Rules change during the build: Japan's GCP ordinance for E6(R3) (planned April 2027, not confirmed) and the amended ethical guidelines (apply 2026-12-01) | documents and notices written on old text | 1 to 4 wk | P3 | an impact note per change (T-642); the Japan notice and amendment checked against the new text | counsel's read | P1 |

### 5.2 Changed rows

| ID | Change | Reason |
| --- | --- | --- |
| RSK-14 | The residual S4 P1 cannot be claimed until CODEOWNERS names a human and branch protection enforces it; until then S4 P2 | no CODEOWNERS file; the engineer is unnamed |
| RSK-16 | Add spot pre-emption; controls: one VM, no parallel fan-out | quota of 1 |
| RSK-25 | Initial P2 → P3 | the amendment is filed while contracts are not engaged: pressure to "just read a sample" grows. The hard rule stays. |
| RSK-26, RSK-27 | Initial P3 → P4 | no order; hospital IT not engaged |
| RSK-43 | "the cloud B200 qualification" → "qualification on the owner's B200 with a host fingerprint and two MIG layouts" | owner fact |
| RSK-45 | Residual S3 P2 → S3 P3 until a hospital owner and signed tier dates exist | PLAN-001 |
| RSK-47 | Residual S3 P1 → S3 P2 until the second reviewer is named | |
| RSK-49 | The decision may be made on 12-18 from measured numbers; the 14-night bench run becomes the acceptance of the chosen form | PLAN-006 |

## 6. The task list

This section replaces the card list of TB-ASSESS-01 §4 as the working backlog. A card of TB-ASSESS-01 that is still open keeps its id and its contract: the words "as TB-ASSESS-01" mean "read that card in `docs/reviews/2026-11-09-assessment-and-tasks.md`; nothing changes in this field". Only the changes are written here. New cards take the numbers T-501 upward. The backbone is the verified inventory TB-DR-11 (`docs/reviews/2026-11-10-deep-review/11-task-inventory.md`).

State on 2026-11-10: TB-DR-04 (engineering quality) arrived after the tables below were generated. Its cards are T-650 to T-654 and the additions listed at the head of wave 1 (§6.2.4); its Blocker, Critical and High rows are in the short table there, not in the generated coverage table of §6.3.

### 6.1 Rules for cards and sessions

1. **One card = one pull request = one agent session.** A card that needs two PRs is split with a letter (T-102a, T-102b). A session takes one card, on a branch `agent/<card id>-<slug>`, and stops when the PR is open and green.
2. **A card's contract** has seven fields, the columns of §6.2: goal; files it touches; acceptance tests; depends on; size (S ≤ 1 day, M 2 to 4 days, L 1 to 2 weeks of one session); closes (finding and register ids). A session may not touch a file outside its list. If it must, it stops and asks the integrator, who updates the card first.
3. **Decisions are files.** One decision = one file `docs/decisions/D-nnn-<slug>.md`. The number comes from `docs/decisions/REGISTRY.md`; the integrator adds the row before the branch is cut. Nobody appends to `docs/DECISIONS.md` after T-002 merges.
   - New numbers start at **D-300**. First rows: D-300 prompt registry (PR #75, renumbered from its D-201), D-301 vocabulary schema (PR #82, renumbered from its D-205), D-302 permission matrix (T-102a), D-303 OMOP schema name and D-304 dual write (T-106), D-305 `qualify` (T-012a).
   - **D-270 to D-289 stay with the critical-issues fix groups.** TB-ASSESS-01 §5.1 item 7 ("the integrator allocates from D-270") is struck.
   - Collisions: **D-201** stays test isolation (master); PR #75 takes D-300. **D-205** stays committed goldens (master); PR #82 takes D-301. **D-204** is T-104's: one file, from the PR #83 version; PR #82 drops its copy. A number belongs to whoever has it on master. Reservations D-208 to D-262 of the old cards stay valid; reservations D-190 to D-207 are void.
4. **Generated files are regenerated, never hand-merged:** `libs/tb_contracts/generated/models.py`, `docs/plan/25-traceability.csv`, the goldens under `tests/golden/`, the decisions index, later `docs/plan/backlog.csv`. On a conflict: take master's copy, run the generator, commit the result. CI job `contracts` fails when the committed file differs from the generator's output.
5. **Hot documents** (`docs/DECISIONS.md`, `docs/RUNBOOK.md`, `docs/DATA.md`, `docs/USER_GUIDE.md`, `docs/SECURITY.md`): until T-669 splits them into section files, a card adds a new section file or a new decision file and one index line. RUNBOOK section numbers are given by the integrator (§12 is identity on master; §14 is claimed three times in open PRs and is re-given at merge).
6. **The shared machine** has 4 cores and 15 GB. Every session runs `make check-disk` at start and `make clean-tmp` at end. **One full `pytest` at a time**: the integrator's. A card session runs targeted tests only (`.venv/bin/python -m pytest path::test -p no:cacheprovider -n 0`) with `TB_SCRATCH` and `TB_TEST_ROOT` set to its own folder, and its own port range.
7. **Every card ends with the data-handling scan** (`tools/data_scan.py`, CI job `data-scan`): synthetic and public data only, no real name or identifier in code, tests, logs, screenshots or documents.
8. **Path corrections** to the old cards (TB-DR-11 §C.4). `tools/trialbox_doctor.py` is `tools/trialbox/doctor.py`; `tools/trialbox.py` is `tools/trialbox/__main__.py` (cards T-012, T-108, T-109, T-113, T-117, T-209, T-210, T-211, T-214, T-319). T-213's new tool is `tools/acceptance_env.py`, because `tools/acceptance.py` exists (D-83). There is no migrations directory until T-104 lands: a card that adds a table waits for T-104 or rebases on it. T-668 adds a lint for card paths.
9. **Safety-core rule.** Changes to matching, the criteria engines, the guard, `authz` and the prefill path need the human reviewer named in CODEOWNERS (owner action OD-9). Only one safety-core PR is in review at a time (§6.5 c).
10. **Fix groups.** D-270 to D-281 are held by the critical-issues session. No card here redoes them. Where a deep-review finding extends a fix group, the row says "tell fix group"; the integrator passes the finding id to that session.

### 6.2 The cards

Reading the tables. "Closes" lists every finding or register row the card closes or helps to close; "(part)" or a named half means another card or a fix group closes the rest (§6.3 shows all closers). Order inside a wave is the proposed start order.

**A note on wave 1.** The brief for this section put every remaining Blocker and Critical in wave 1 (G1 Fri 2026-12-04, G1b 12-11). Five of them are builds of one to two weeks that depend on other cards: CR-060 (T-106, T-202), CR-062 (T-115, T-302b), CR-027 and DATA-022 (T-206a, T-206b), CR-041 and OPS-061 (T-210a to c), OPS-050's day-2 half (T-633). They **start** in wave 1 where their dependencies allow and are **due at G2a** (Fri 2027-01-08), which is the gate that asks for every Blocker and Critical row closed (§2.1). They are listed in wave 2.

#### 6.2.1 Fix groups in progress elsewhere (not cards)

| Fix group | Register rows it closes | State | Deep-review findings to tell the fix group |
| --- | --- | --- | --- |
| FG D-270 | CR-049, CR-050 (DI-1, DI-2) | **PR #86**, clean against master | UX-003, UX-020 (digest time), STD-016 (rest goes to T-656) |
| FG D-271 | CR-051, CR-052, CR-053 | not pushed | DATA-001 (T-611 builds on the same lines of `pipeline.py`), DATA-007 |
| FG D-272 | CR-016, CR-054, PV-9 (PX-3) | not pushed; old chain needs owner decision OD-7 | DATA-021, DATA-013 (pseudonyms in audit events and erasure) |
| FG D-273 | CR-017, CR-018, CR-019, CR-020, CR-021, CR-022, CR-055, PV-15 (PX-4, PX-5, PX-7, PX-8) | not pushed | ROLE-010, ROLE-016, FIT-023 |
| FG D-274 | CR-056, CR-057 | not pushed | OPS-045, DI-10, DI-11 (T-117b takes what is left) |
| FG D-275 | CR-001, CR-005, CR-006, CR-007, CR-115, S-11 | not pushed | DATA-016, STD-021 (OBX-11 status), UX-008 (same output record), S-12, D-190 (`Observation.status`) |
| FG D-276 | CR-002, CR-003, CR-004 | not pushed | LLM-002 and LLM-003 (T-601: agree who edits `evaluate.py` first), LLM-004, LLM-005, LLM-016, LLM-044, LLM-032, UX-007, S-13 |
| FG D-277 | CR-008, CR-009, CR-010, CR-011 | not pushed | LIFE-022, LIFE-023, FIT-025, UX-005, UX-028, S-16 (T-602 takes what is left) |
| FG D-278 | CR-026, CR-038 | not pushed | FIT-023 |
| FG D-279 | CR-033 (rest), CR-034, CR-116, CR-117, SEC-9 (P-1, P-2, P-7) | not pushed | ROLE-001 (new route in the same file: T-505a), ROLE-004, ROLE-006, OPS-003, REG-025 |
| FG D-280 | CR-023, CR-029 (PX-6; the register's "CR-027" in its §7.3 is a slip for CR-029) | not pushed | FIT-020, FIT-022, ROLE-010, DATA-025 (T-102b and T-309 take what is left) |
| FG D-281 | CR-035, CR-036, SEC-6, SEC-7 (P-3 to P-6) | not pushed | LIFE-021, REG-021 (signature meaning text), STD-060 |

Seven open Blocker or Critical rows rest on unpushed fix groups alone (CR-001, CR-002, CR-003, CR-016, CR-017, CR-033 rest, CR-034). The integrator asks the critical-issues session for a pushed branch per group by Mon 2026-11-16, so that each can be read.

#### 6.2.2 Where each TB-ASSESS-01 card went (all 67)

| State | Cards |
| --- | --- |
| Merged, closed | T-001, T-003, T-005, T-006 (its 50k files move to T-004), T-007, T-008 (review-fix residue: T-655) |
| In an open PR (merge order in §6.4) | T-101 (#75; follow-up T-101b), T-104 (own PR, cut from #83; follow-up T-104b), T-105 (#82; follow-up T-105b), T-111 (#83; follow-up T-111b), T-113 (#85; follow-up T-113b), T-118 (#70; follow-ups T-613a, T-613b, T-615b) |
| Partly merged; the residue is now a card | T-109 → closed; residue to FG D-279 and T-109b · T-110 → **T-110b** · T-117 → **T-117b** · T-207 → T-207 (rest) |
| Work in progress, kept | T-004 (integrator; rewritten, takes T-009's measurement records) · T-102 (critical-issues session holds the first slice as FG D-280 and D-273; split T-102a, b, c) · T-115 (as FG D-281; the rest is the merged card T-115) |
| Not started, unchanged contract | T-011, T-107, T-202, T-204, T-208, T-303, T-312, T-317, T-319 |
| Not started, contract changed (the row says how) | T-002, T-010, T-103, T-106, T-116 (PoC part to T-506), T-119, T-201, T-205, T-214, T-215, T-216, T-307, T-309, T-314, T-318 |
| Rewritten | T-114 (the owner's B200), T-309 (owner decision OD-5), T-205 (what the fix groups leave) |
| Split | T-012 (a, b) · T-102 (a, b, c) · T-108 (a to d) · T-112 (a, b) · T-203 (a, b, c) · T-206 (a, b) · T-209 (a, b, c) · T-210 (a, b, c) · T-211 (a, b, c) · T-212 (a to d) · T-213 (a, b) · T-301 (a, b) · T-302 (a to d) · T-304 (a, b, c) · T-305 (a, b, c) · T-310 (a, b, c; SAE part to T-602) · T-311 (a, b) · T-315 (a, b, c) · T-316 (a, b, c) · T-320 (a, b) |
| Merged into another card | T-009 → T-004 (records) and T-607 (embedder decision) · T-308 → T-311a (same page file) · the record half of T-205 → T-115 · T-306 → T-305b, unless dated after go-live (wave L, owner Q-06) |
| After go-live if the owner agrees (Q-06) | T-313, T-316b, T-316c, T-306 |

#### 6.2.3 Wave P: PoC prerequisites, due at the freeze Fri 2026-11-27

The list matches `27-poc-plan.md` §7. T-505 is one card there; here it is two PRs (T-505a in the console, T-505b in the demo tools) so that they can run in two lanes. T-613 is two PRs (T-613a here, T-613b in wave 1). T-617 is two PRs (T-617a here, T-617b in wave 2). The open PRs #86, #70 and #78 are wave-P prerequisites too; they are in §6.4.

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Closes (finding and CR ids) |
| --- | --- | --- | --- | --- | --- | --- |
| **T-002** | Decisions as files; one number registry (`docs/decisions/REGISTRY.md`, new numbers from D-300); CODEOWNERS, CONTRIBUTING, LICENSE. as TB-ASSESS-01, plus: the six pending tail entries of the open PRs become files at merge; `decisions_index.py --check` in CI job `docs`; the rule "generated files are regenerated, never hand-merged" written into CONTRIBUTING and checked in CI job `contracts` | as TB-ASSESS-01 (`docs/decisions/*`, `tools/decisions_index.py`, `CONTRIBUTING.md`, `.github/CODEOWNERS`, `LICENSE`) plus `.github/workflows/trialbox-ci.yml` (one step) | as TB-ASSESS-01; plus: a duplicate number across `DECISIONS.md` and `docs/decisions/` fails; a file with no REGISTRY row fails; a merge of two branches that each add a decision and a contract model has no conflict | queue step 1 merged (#86, #64, #70, #73) | M | CR-077, CR-080 (file part; the named human is owner action OD-9), PLAN-033 (part), PLAN-024 (part) |
| **T-671** | Dependency batch 0, build tools: uv ≥ 0.13.4 in CI and `lock.py`; pip-audit, Syft, Trivy bumps with sums; the seven GitHub Actions to current majors by SHA; `renovate.json`; sha256 of `validator_cli.jar` pinned (§9 batch 0 a–d, g) | `.github/workflows/trialbox-*.yml`, `tools/supply_chain/{lock,scanners}.py`, `pip-audit.in/.lock`, `renovate.json`, `tools/fetch_jvm_deps.sh` | `uv --version` in CI ≥ 0.13.4; `uv lock --check`, `make lock-check`, `allowlist-check` pass; a tampered validator jar fails the fetch | none | S | DEP-006, DEP-017, DEP-018, DEP-019, DEP-024 |
| **T-672** | Finish PR #78 (dependency batch 0 e, f): translator jars bumped incl. `opentelemetry-api`, `commons-compress`, `junit` excluded; JVM image on Temurin 21 by digest; image gate to block mode for the jvm and demo images | `services/criteria_compiler/compile_cql/translator/pom.xml`, `deploy/docker/jvm.Dockerfile`, `tools/supply_chain/release.py`, `deploy/security/known-image-findings.md` | CQL and validator tests pass; Trivy block mode PASS on jvm and demo images; OSV on the classpath shows 0 HIGH/CRITICAL | PR #78 branch; T-671 | S | CR-045 (own-image part), DEP-001, DEP-002, DEP-015, OPS-018 (part) |
| **T-501** | Demo image starts from a clean build and fits its host: jars and a pinned `FHIRHelpers-4.0.1.cql` in the image (`demo-bundle: jvm-deps`); Secure-cookie seeding fixed; memory and start time measured and written in the README and `render.yaml`; plain error when the translator is absent; image without `docs/reviews`; temp-root marker; a CI job that builds from a fresh checkout and signs in | `demo/Dockerfile`, `demo/README.md`, `render.yaml`, `Makefile` (`demo-bundle`), `tools/demo.py` (seed call only), `services/criteria_compiler/service.py` (one function), `.github/workflows/trialbox-ci.yml` (one job), `.dockerignore` | CI: fresh clone → image build → container starts with no `-e` → `/login` answers → each seeded account signs in; peak RSS and first-answer time within the README's numbers; compiling changed criteria without jars gives a named error, not a traceback | T-672 (jars) | M | OPS-001, ROLE-002, ROLE-003, UX-001, LIFE-005, OPS-005, OPS-007, OPS-009, OPS-077, ROLE-028 |
| **T-505a** | Identity for the demo, console half: `POST /api/v1/session` enforces the second factor; API tokens not valid as cookies. Forced first password change and the per-IP sign-in throttle come from fix group D-279 (P-1, CR-116); if D-279 is not merged by Fri 11-20 this card takes both by agreement with that session | `services/console/home.py` (session route), `services/console/auth.py`, `identity.py`, `tests/console/` | with `TB_CONSOLE_MFA=totp` a password alone gets 401 on the API route; first sign-in forces a change; 30 wrong tries from one IP are slowed and do not lock a named tester out | FG D-279 (same files: land after it or by agreement) | S | ROLE-001, ROLE-006, OPS-003 (lock-out part), CR-033 (API route part) |
| **T-505b** | Per-tester accounts for the demo: an accounts file (not in the image), TOTP enrolment, a sub-investigator account, a delegation log seeded per demo study (PI, sub-investigator, CRC with different ticks), account default language, persistence switch (`--keep`, data volume, no wipe at restart) | `tools/demo.py`, `tools/feas_demo.py`, `tools/role_demo.py`, `tools/list_demo.py`, `tests/inproc_box.py`, `demo/README.md` | two named investigator accounts per site, separate passwords; restart keeps accounts, marks and feedback; the sub-investigator gets 403 on Approve and on Approach where the log has no tick; ja and zh-TW testers land in their language | T-501, T-505a | M | ROLE-004, OPS-002, UX-040, UX-002 (persistence), OPS-006, FIT-027, ROLE-008 (seed half; the code half is T-102b), LIFE-006 |
| **T-502** | Demo (PoC) mode behind an audited flag: uploads and chart paste refused with a page in the user's language; banner in ja, zh-TW, en on every page; acknowledgement gate at first sign-in stored as audit event `demo.ack`; non-device footer; `tools/data_scan` run over stored demo input | `services/console/demo_guard.py` (new), upload and paste routes in `services/console/app.py` and `sitesetup` pages (guard call only), `templates/_demo_banner.html` (new), `i18n_demo.py` (new), `templates/base.html` (one include), `libs/tb_common/flags.py` (one flag) | a walk posts to every input and upload route with the flag on: all refused; banner present on all pages in three languages; one `demo.ack` per tester; a planted chart number in a demo field is reported by the scan | T-505a (order on `app.py`) | M | REG-014, OPS-004, PLAN-019, REG-015 (gate half), DATA-015 (non-device line on exported files), CR-032 (PoC control only) |
| **T-506** | Wording for the PoC (the PoC part of T-116): "criteria not matched" in the three titles, headline and tier label; "likely eligible" renamed; forbidden-word list `libs/tb_common/wording.py` with a walk check; intended-use footer from one statement source; ja and zh-TW clinical wording pass (verdict words, CRC term, referral words, opt-out page terms, "approached") read by a native reader | `libs/tb_common/wording.py` (new), `services/console/i18n.py`, `i18n_review.py`, `i18n_team.py`, `i18n_identity.py`, `i18n_flags.py`, `templates/base.html` (footer) | the walk finds no "excluded", 除外, 排除 on PI and CRC pages; the footer shows the statement in the user's language; a catalogue test bans the old variants; a ja and a zh-TW reader sign the 40 clinical strings | PR #86; T-502 (order on `base.html`) | M | CR-078 (PoC part), FIT-006, PLAN-020, REG-017, REG-020, UX-017, UX-018, UX-019, ROLE-023, ROLE-024, ROLE-026, ROLE-027 |
| **T-507** | ja and zh-TW criterion labels and criterion text beside the English for the PoC rulesets; label editor made a required step on approval; the stub judge answers ja and en notes (personas for disagreement stay with fix group D-276); a "test model" label on stub results | `services/console/i18n_team.py`, `i18n_review.py`, approval page label editor, `rulesets/*/labels.*` (PoC rulesets), `services/llm_stub/handlers.py`, `services/llm_stub/cassettes/` | walk: no English token outside an allow-list on ja and zh-TW clinical pages; the PoC studies give note results in ja, zh-TW and en; DEV pages label the test model | T-506; T-503, T-504 (labels of the new rulesets); FG D-276 (`handlers.py`) | M | LLM-045, UX-009, LIFE-004, LLM-044 (demo-answer half) |
| **T-503** | Japan scenarios. J1: early Alzheimer's anti-amyloid trial (AD-MAB): a synthetic `ad` archetype with Japanese notes, a Japanese demo site (Asia/Tokyo), ja protocol, ruleset built with the current compiler, cassette, expected results. J2: NEUR-COH registry scripted. The two design lines that call GZQO the Alzheimer study corrected | `tools/synth/` (generator, `rates.yaml`, `notes_ja.py`, catalogue), `tools/make_protocol_docs.py`, `rulesets/AD-MAB/`, `rulesets/NEUR-COH/`, `services/llm_stub/cassettes/ir_extract/`, `tests/fixtures/protocols/` | recount equals the gold; amyloid status unknown gives "needs information", never "not matched"; `list_demo --lang ja` on AD-MAB exits 0; synth rate checks pass; no Chinese note text on the ja site | none (owner Q-02 confirms the study list) | L | LIFE-001, UX-004, LIFE-003 |
| **T-504** | CGMH scenarios. T2: RA-JAK as an interventional trial (ruleset, protocol document, two planted states). T1: a GZQO amendment step (amend, approve, see the changed list). T3: a registry with a REDCap prefill step. Scripted in zh-TW | `rulesets/RA-JAK/`, fixtures, cassette, `tools/demo.py` scenario script (after T-505b); its `tools/synth/` commit (zoster, VTE) lands after T-503 | SQL and CQL agree 100 % on the test patients; planted candidates listed in zh-TW; the amend-and-approve walk passes in the container in three languages | T-503 (`tools/synth/`), T-505b (`tools/demo.py`) | M | LIFE-002, LIFE-010 (PoC part) |
| **T-613a** | Recompile the shipped rulesets with the current compiler (family expansion), after PR #70 is merged; goldens regenerated once; CI drift check. This is the wave-P part of T-613 | `rulesets/*` (the five shipped), `tools/build_rulesets.py`, `tests/golden/*` (regenerated), CI step | each ruleset's value sets equal the compiler's output for the pinned release; a patient coded `M06.09` is included by RA-BIO INC-01; the PI reads the diffs | PR #70 merged; T-503 (same area) | S | STD-040, STD-001 (with PR #70) |
| **T-510** | In-product feedback: flag, comment and rating per screen in three languages; stored with path, language, role, time; export to issues (CSV); no patient-example field, a visible "no patient details" line | `services/console/feedback.py` (new), store table, `templates/_feedback.html` (new), `i18n_feedback.py` (new), `templates/base.html` (one include) | an entry from any page is stored; CSV export; the planted-identifier scan of T-502 covers the comment field; one test per language | T-502 (order on `base.html`) | M | UX-006 |
| **T-512** | The PI can start FEAS, SCREEN and CASE on own study (sub-investigator needs the `run` tick), pending owner Q-04; lists show "data as of"; the investigator can refresh feasibility | `libs/tb_common/authz.py` (`can_request`), `services/console/home.py`, `team.py`, orchestrator job authorisation table | PI starts FEAS and SCREEN on own study and is refused elsewhere; limits hold; "data as of" on four pages | owner Q-04; FG D-273 and D-280 (same files: land after them) | S | FIT-003, FIT-U01 |
| **T-513** | One demo clock: the demo day is the real day in the site's time zone; no page shows a date after today; the morning digest shows site time | `tools/list_demo.py`, `tools/e2e_simple.py` (fixture date shift), demo fixtures | no page shows a date after "today"; EDC drafts the visit date the participant page shows; week and not-matched pages show the same run date | PR #86 (CR-049, CR-050); T-505b | S | UX-003, UX-020 |
| **T-515** | Test-model results are labelled; recorded real-pair opinions (agree and disagree cases) shown where the G1 short run has them | demo fixtures with recorded opinions, `templates/_criteria.html`, `templates/week.html` (label only) | at least one listed patient shows first and second check with quotes and one shows a disagreement; DEV pages label the test model | T-507 (templates, same lane); G1 short-run results; fix group D-276 (tell) | S | UX-007 |
| **T-514** | A coded criterion row shows value, unit, date and code on the patient page and the not-matched list | matching output record (value, unit, date, code per criterion), `templates/_criteria.html`, `templates/excluded.html` | no met / not met row without a value or a quote; tests in ja, zh-TW, en | T-515 (templates); fix group D-275 (tell: same output record) | M | UX-008 |
| **T-516** | Workflow fixes on the PoC path: the screening log agrees with the participant page after a consent save; a referral after an approach pauses the approach; the sub-investigator sees why an action is absent; IRB approval date and consent version seeded; no implied consent on the PoC path | `services/console/home.py`, `team.py`, `templates/_mark.html`, `templates/team_candidate.html`, screening-log state, demo seed (two values) | the cases as tests; an enrolment without a consent record is held; walk at 390 px in three languages | T-512 (same files), T-514 (templates) | M | UX-011, UX-013, UX-015, UX-014, LIFE-019 (PoC part) |
| **T-511** | Remaining PoC-path UX fixes from TB-DR-02a not covered by T-513 to T-516: help examples name the tester's own study; the referral form's select text; EDC review shows words, not codes | `services/console/i18n_help.py`, referral form template, `templates/edc_review.html` | walk test on the three pages in ja and zh-TW | T-516 (templates) | S | UX-016, UX-010, UX-029 (help half) |
| **T-509** | PoC hosting scripts: VM, Caddy with TLS, a front door before `/login`, image by digest from tag `poc-1` (no build on the VM), daily snapshot, purge script, destroy-and-rebuild | `deploy/gcp/poc-host.sh` (new), `deploy/gcp/hosted-demo-startup.sh`, `demo/README.md` (hosting section) | the URL without a front-door session never shows `/login`; data survives a restart; purge leaves no volume; rebuild from the tag takes one command | T-501, T-505b; owner Q-03 (cost) | M | OPS-008, OPS-003 (front door), UX-002 (always-on host) |
| **T-508** | PoC pack `docs/poc/`: protocol, scripts per role and language (ten tasks each with expected results), forms, severity scale, data-handling statement and acknowledgement (ja, zh-TW after a native read), the "not research" decision, notice on the testers' own data, session checklist, a two-page guide and a named contact | `docs/poc/**` (new), one decision file | an internal dry run completes every task on tag `poc-1`; the two native readers sign the ja and zh-TW scripts | T-506 (words), T-503, T-504 (scenarios) | M | PLAN-005, REG-015, REG-013, PLAN-021, UX-029 |
| **T-617a** | Third-party NOTICE for the hosted demo (LOINC, UCUM and the other sources), shown on an About page. PoC part of T-617 | `NOTICE` (new), About page (own template) | NOTICE lists every source the image ships, with version and obligation | none | S | STD-044 (PoC part) |
| **T-661** | Gate records: a template and `docs/validation/gates/G0.md`, `GP-0.md`, `GP-1.md`, `GP.md`, `G1.md`; each states the register condition; `doclint` fails on a gate without a record | `docs/validation/gates/*` (new), `tools/doclint.py` (one check) | doclint fails on a gate without a record or a criterion without an evidence cell | none | S | PLAN-023, PLAN-027 (part), PLAN-040 (part), PLAN-025, PLAN-026, PLAN-029 |
| **T-663** | Owner-chain tracker `docs/plan/owner-chains.md`: step, owner, started, evidence, need-by, latest start, float; no patient data, no personal contact details | `docs/plan/owner-chains.md` (new) | every chain of §3.1 has a row; a chain past its latest start with no start date is printed on the status file's first screen | none | S | PLAN-023 (part), PLAN-022, PLAN-042, PLAN-043; tracks owner rows CR-088, CR-089, CR-090, CR-091, CR-092, PLAN-001, PLAN-002, PLAN-007 |
| **T-664** | GPU ledger `docs/plan/gpu-ledger.md`: the queue of long runs on the one spot VM and on the owner's B200, hours, pre-emptions, cost | `docs/plan/gpu-ledger.md` (new) | the six runs of §4 are queued with a date; each finished run has its record path | none | S | PLAN-004 (part), CR-070 (closed as moot; ledger replaces the quota ask) |

#### 6.2.4 Wave 1: to G1 Fri 2026-12-04 and G1b Fri 2026-12-11

Safety fixes first: T-601 must be in the commit of the G1 run. T-601, T-641 and T-012a start in wave P's weeks (§2.3) and are counted here.

**Cards from TB-DR-04 (engineering and test quality).** The file has no Blocker and no Critical; none is a PoC prerequisite (the code passes every case its surviving mutants describe; the gaps are in the tests).

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Wave | Closes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **T-650** | Close the safety-core test gaps: property tests for the invariants of §7.4; unit tests that kill all 28 mutants of TB-DR-04 §3.3 (5 survive every gate today; 2 are caught only by the goldens); unit tests for the cascade's exclusion paths | `tests/unit/test_safety_properties.py` (new), `tests/unit/test_one_rule.py`, `test_code_coverage.py`, `test_mixed_and_polarity.py`, `pyproject.toml` (hypothesis in the test group; lock regenerated) | the 28 mutants are killed by unit tests; the properties pass at 200 examples in the PR job and 5,000 nightly | none | M | 1 | ENG-018, ENG-019, ENG-020, ENG-021 |
| **T-652** | A CQL/SQL equivalence gate that cannot pass empty: a criterion with 0 patients compared fails; a minimum sample size; a disagreement that changes direction blocks at any rate; one decision table for structured verdicts shared by the engines | `services/criteria_compiler/equivalence/gate.py`, `service.py`, `services/matching/verdict.py` (new), new unit tests | an empty CQL result fails approval; `gate.py` ≥ 95 % covered; the parity property is green | T-650; CR-115's fix | M | 1 | ENG-016, ENG-022 |
| **T-651** | Mutation testing nightly on the safety-core files and a coverage ratchet in the unit job | CI nightly job, a mutation tool config, `pyproject.toml` (`[tool.coverage]`) | nightly mutation score ≥ 90 % on the safety core; CI fails on a package drop of more than 0.5 point; safety-core files ≥ 95 % line and 90 % branch | T-650 | S | 2 | ENG-029 and the mutation gate |
| **T-653** | Test hygiene and the missing jobs: `make test` green from a clean clone (the jars are a prerequisite of the target); pure tests run without PostgreSQL; random order and no network nightly; the compose tests (HAPI CQL, mail, e2e, the walk) run in a nightly job; a performance regression gate on the stub at 5k | `Makefile`, `tests/conftest.py`, `pyproject.toml`, `.github/workflows/trialbox-e2e.yml`, `tools/bench.py` baseline | clean-clone `make test` green (today 21 fail, 20 of them for the missing jars); 20 consecutive green runs; one green compose run a night; a regression of more than 20 % fails the nightly | T-672 (jars) | M | 2 | ENG-017, ENG-026, ENG-027, ENG-028, ENG-030, ENG-031 and the Mediums of TB-DR-04 §2.3 |
| **T-654** | Lifecycle records: the software safety classification (the screening core as internal Class B), the SOUP list, the development plan, a problem-resolution log (Issues enabled, or `docs/validation/problems.csv`), a pull-request template; secret scanning and a static security scan in CI | `docs/validation/` (new files), `.github/PULL_REQUEST_TEMPLATE.md`, CI jobs, `pyproject.toml` (ruff rules) | signed by the owner and the safety-core engineer; a planted fake key fails CI; every register row has a tracked entry | T-002 | M | 2 | ENG-001, ENG-003, ENG-004, ENG-008, ENG-010, ENG-011 |

Additions to existing cards from TB-DR-04: **T-007** takes ENG-005 and ENG-006 (master is not protected today: the API shows no required checks; the owner sets branch protection and the supply-chain jobs report on every PR). **T-666** takes ENG-002 (no test names a TST or URS id; the 370 SRS ids are not linked to the 92 URS). **T-110b** takes ENG-007, ENG-013, ENG-014, ENG-015 and ENG-024 (image gates in report mode; build downloads unverified; two Java versions). **T-104** takes ENG-032 (downgrade and checksum mismatch refused). **T-102** takes ENG-012 (no function over 200 lines in the console). The remaining Mediums and Lows of TB-DR-04 go to T-653 or the wave-3 polish card of their area.

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Closes (finding and CR ids) |
| --- | --- | --- | --- | --- | --- | --- |
| **T-601** | The gateway never answers a role with another role's model: per-route `fallback` flag (none on patient routes); one retry on the same build; no fallback on 400/404; build id and `X-TB-Fallbacks` in the response; `tb_llm` raises on an unexpected alias; `doctor` fails when the gateway would refuse the judge. The pair's build comparison itself is fix group D-276 | `services/gateway/core.py`, `policy.py`, `models/routing.yaml`, `libs/tb_llm/client.py`, `services/orchestrator/scenarios/evaluate.py`, `tools/trialbox/doctor.py` (one check) | fault injection on the stub: judge down gives `unknown` with `failures >= 1`, never agreement; judge 400 gives `prompt_too_long` or `upstream_failed`, never another alias; a mutation that removes the build comparison fails a test | FG D-276 (coordinate; tell fix group); before PR #75 rebases (`gateway/core.py`); before T-004 | M | LLM-002, LLM-003, LLM-006, LLM-004 (gateway half), CR-002 (gateway half) |
| **T-613b** | Units read per row after PR #70: the row-unit check extended to the JP template and `unit_defaults` in shipped mappings; a unit and conversion table (30 pairs); `mapping_check` lists unit pairs and raw qualitative values; one normaliser for qualitative results in ja, zh-TW, en. Wave-1 part of T-613 (T-613a recompiles the rulesets in wave P) | `services/adapter/mapping/engine.py`, `jp_core/ssmix2_site.yaml`, `templates/*.yaml`, `libs/tb_common/labvalue.py`, `tools/mapping_check.py` | µmol/L creatinine through CSV and SS-MIX2 gives no value and reason `unit_mismatch`; 30 conversion pairs tested; 20 spellings (陰性, 陽性, …) read as positive, negative or unknown; goldens unchanged in meaning | PR #70 merged; FG D-275 (SQL generator half: tell fix group DATA-016) | M | STD-001 (rest), STD-002, STD-022, CR-001 (adapter half) |
| **T-611** | Feed completeness gate before publish: a table must be present and its volume within a band of the last good night; DQD `fail` holds; a held night never becomes `CURRENT`, never prunes the last good snapshot, writes no OMOP tombstones; orphans of a vanished patient row and duplicate source keys counted; the readiness page shows the refusal | `services/adapter/pipeline.py`, `services/adapter/sources/*`, `libs/tb_common/retention.py`, `services/omop/load.py` (hold check), settings schema | the four bad feeds of the TB-DR-06 trace are held; a 15 % drop holds; one fault-injection test per table | FG D-271 (same lines of `pipeline.py`: land after it) | M | DATA-001, DATA-009, DATA-017 |
| **T-612** | The site key is never created outside the install ceremony; the ingest refuses when the key fingerprint differs from the stored one; `doctor` reports it | `libs/tb_common/crypto.py`, `services/adapter/pidmap.py` (key load), `deploy/install.sh` (ceremony step), `tools/trialbox/doctor.py` (one check) | a test removes the key: the second night is refused and no pseudonym changes; opt-outs survive | T-611 (order in the adapter) | S | DATA-004 |
| **T-615b** | HIS CSV reader: encodings through the one detector of PR #70 (Big5/CP950, Shift_JIS/CP932) with quarantine; any ingest exception writes `ingest.failed`; delta mode filters on the source's change time, not the clinical date | `services/adapter/sources/csv/source.py`, `cgrd_sql`, `services/adapter/pipeline.py` (exception path) | a Big5 and a CP932 HIS CSV load equal to the UTF-8 twin; a broken file is quarantined and the night continues; a late-arriving old result is picked up by `--since` | PR #70; T-611 | S | DATA-003, DATA-008 |
| **T-004** | Run 5 and G1, rewritten for one spot VM: a forced pre-emption in the rehearsal proves `--resume` at three stages; three budgeted attempts; wall time and pre-emptions in the report; the 50k functional run on the owner's B200; 50k goldens committed; Tesseract run for real. T-009 is merged into this card: the measured-embedder and profile-cost records are part of the run record | as TB-ASSESS-01 plus `tests/rehearsal/` (pre-emption case), `docs/validation/gates/G1.md`, `tests/golden/*` (50k) | as TB-ASSESS-01; plus: the rehearsal kills the stand-in VM at three stages and results are identical; the G1 record names commit, hours, pre-emptions; the run does not count unless T-601 is in the commit | T-601; FG D-275, D-276; T-664; owner OK per run | M | CR-069, LLM-001, PLAN-004, LLM-025 (first number) |
| **T-012a** | `trialbox eval qualify` and the qualification record (as TB-ASSESS-01, first half). Steps added: schema enforcement, repeat-run determinism, longest prompt per profile, log marker, licence file check, pair mode of PR #64's gate through the gateway, the two throughput numbers | `tools/qualify.py` (new), `tools/trialbox/__main__.py` (one subcommand), `schemas/qualification_record.schema.json`, `eval/qualification/`, RUNBOOK §11 (section file) | as TB-ASSESS-01; plus: a record missing any step is `failed` | PR #64, PR #75; due merged by Fri 11-27 (§3.2) | M | CR-079 (qualify half), LLM-029, LLM-020, LLM-021, LLM-031, LLM-030 |
| **T-012b** | `champion` only through `qualify`: install pins `candidate`; expected weight hash and revision per build; the 16-byte folder is refused; a PRODUCTION gateway refuses a champion without a record; admin models page shows the record | `services/registry/registry.py`, `models/registry.yaml`, `tools/pin_model.py`, `services/gateway/policy.py` (one rule), admin models page | trust-on-first-use test fails closed; PRODUCTION gateway returns a named refusal for an unqualified champion | T-012a, T-601 | M | LLM-007, LLM-029 (control half), CR-079 |
| **T-674** | Model provenance (dependency batch 2, models first): own copy or own quantisation of the verifier with source, revision, manifest sha256 and licence file; judge chat template from the publisher at a pinned revision, passed with `--chat-template`; Gemma 4 31B challenger build added and its bake-off run queued in the GPU ledger; a second verifier candidate measured (RSK-60) | `models/registry.yaml`, `models/cards/*`, compose `command:` blocks, `tools/pin_model.py` (template files in the manifest), `tools/serving_config.py` | no `null` revision in a deployed build; the serving record names the template sha; canary and N-12 pass | T-012b (same registry file); owner Q on the verifier copy | M | DEP-007, DEP-008, DEP-009, PLAN-036 (candidate half; the survey question is the owner's) |
| **T-673** | Dependency batch 1, third-party images: `deploy/images.lock` as the one digest list; vLLM by digest (same version as the G1 run); the Spark image replaced by an image built for its chip; `check_host.sh` arch check and FAIL on a driver below the image's CUDA need; MailHog replaced by Mailpit; structured-output backend in the serving record | `deploy/docker-compose*.yml`, `deploy/images.lock`, `deploy/check_host.sh`, `deploy/install.sh` (read the lock) | no image by tag; `check_host` fails on a low driver and on an arch mismatch; compose integration test | T-104 (owns `images.lock`) | M | DEP-003, DEP-004, DEP-005, DEP-021, LLM-010, CR-045 (third-party part) |
| **T-113b** | Follow-up to PR #85 (T-113): registry builds and a pin job for `shared-quota`; `serving_config` rule keyed on the MIG profile; `gpu_profile.sh` knows a B200; model key and guard in the platform manifests; `doctor --platform` checks "MIG instance, not time-sliced" and "server refuses a call without the key"; the pack and survey say two MIG instances | `deploy/platform/**`, `deploy/gpu_profile.sh`, `models/registry.yaml` (profile rows), `tools/serving_config.py`, `tools/trialbox/{doctor,platform}.py` | with one slice `doctor --platform` fails with a clear reason; with two it passes on the kind cluster | PR #85, PR #68, T-012a, T-674 | M | LLM-011, LLM-027, LLM-028, OPS-067, CR-084 (rest) |
| **T-114** | G1b on the owner's B200, rewritten: an offline bundle and one script the owner or a named operator runs (no `gcloud`, no rental); host fingerprint in the record; two MIG layouts; `doctor --platform` warns when the host differs from the record | `tools/b200_qualify.sh` (new; replaces `deploy/gcp/b200-qualify.sh`), `tests/rehearsal/`, `eval/qualification/`, `docs/plan/measurements/b200-*/`, RUNBOOK section file | the record validates against its schema and carries the fingerprint; both layouts recorded; gate record `G1b.md` filled | T-012a, T-113b, T-004, T-674; owner Q-12 (operator) | M | PLAN-017, LLM-011 (measured half), LLM-025 (B200 number), OPS-071, CR-089 (supports) |
| **T-102a** | One permission function `permit` and `authz_matrix.yaml` with the three wrappers (as TB-ASSESS-01, first third); the role × route matrix of TB-DR-02b regenerated as a test | `libs/tb_common/authz.py`, `authz_matrix.yaml`, wrappers in `services/console/auth.py` | as TB-ASSESS-01 for `permit`; the generated matrix equals the design table | FG D-273, FG D-280 (same lines: after them); T-512 | M | CR-024 (first third), ROLE-009 (model half) |
| **T-102b** | Roles: steward, privacy office, monitor grant, IT administrator without patient data; opt-out and staff register kept only by steward or privacy; CRO and SMO accounts must name studies; delegation bootstrap closed (no PI named = nobody acts as PI); SMO and admin cannot set IRB dates silently; role descriptions and menus generated from the matrix. First slice is fix group D-280: this card takes what it leaves | `authz_matrix.yaml`, `services/console/{auth,team,app,home}.py`, i18n role names (own file) | admin sees no patient row; tests for ROLE-005, ROLE-008, ROLE-011, ROLE-015, ROLE-018; the monitor grant refuses a non-enrolled subject | T-102a; FG D-280; owner decision #74 | M | CR-023, CR-024, FIT-022, FIT-002 (grant half), ROLE-005, ROLE-008, ROLE-009, ROLE-010, ROLE-011, ROLE-015, ROLE-018, DATA-025 |
| **T-309** | Break-glass, rewritten to owner decision OD-5 (reason, one patient or one job, 60 minutes, steward review); merged with fix group D-280: this card is the page, the review list and the one rule for admin and non-admin readers. The old contract (second person, 24-hour grant) is void | `services/console/breakglass.py` (new), `authz_matrix.yaml` (rows), templates and i18n (own files) | a grant expires at 60 minutes; every use is in the steward's review list; one rule tested for admin and for a non-admin reader | T-102b; FG D-280; owner Q on FIT-020 | M | CR-029, FIT-020, ROLE-010 (break-glass half) |
| **T-119** | Cloud hygiene remainder: door key not by metadata or plain HTTP, port 80 closed, hosted-demo secrets in Secret Manager; real weight pins on the VM; serving-record capture rehearsed (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-004 (first attempt done); T-509 (shares `hosted-demo-startup.sh`: after it) | M | CR-048 |
| **T-641** | Commitments register `docs/validation/commitments.csv`: every promise in the filed IRB amendments, the IT pack and the opt-out notices with the code and test that keeps it, or a correction; the differences between the two amendments and owner decision #74 listed; a supplement drafted before the first committee meeting; CI fails when a promise sentence has no row | `docs/validation/commitments.csv` (new), `tools/gen_traceability.py` (one check), `docs/plan/sites/*` (supplement draft) | 22 IRB rows exist; no red row at G2a; the generator fails on a promise with no row | none (start in wave P week 1; supplement due 11-20) | M | REG-010, FIT-005, OPS-040 (register half), REG-011, PLAN-008 |
| **T-636** | IT pack truth table: every control line marked "today" or "at IQ" with a test id or a card; ja, zh-TW, en in one table; the 去識別化 wording corrected; two MIG instances; one host system named (decision from T-634) | `docs/plan/sites/it-security-pack.md`, `tools/doclint.py` (one check) | doclint fails on a control line with neither; the ja and zh-TW columns have the same rows as en | T-641; PR #85 merged (same file) | S | OPS-040, OPS-062 (document half), CR-090 (wording half) |
| **T-646** | Legal-basis memo inputs per site (study type × processing step); the sentence "personal information, not 仮名加工情報"; three rewritten opt-out notices covering the whole-hospital repository; the retention conflict stated. Counsel completes and signs | `docs/plan/sites/legal-basis-<site>.md` (new), TB-TMPL-01 §4 | counsel's signature on file; the notice covers amendment items 1 to 7 | T-642; counsel engaged (owner) | M | REG-007, REG-008, REG-009, REG-012 |
| **T-642** | Impact notes for rule changes: Japan's amended ethical guidelines (apply 2026-12-01) and the GCP ordinance amendment for E6(R3); MHLW guideline v7.0; the Taiwan PDPA amendment; a watch list with source, checked date and owner | `docs/validation/regulatory-watch.md` (new), `docs/SECURITY.md` §7 (citations) | each row has a source, a checked date and an owner; doclint fails when a date is older than 90 days | none | S | REG-001, REG-002, REG-003, REG-004 |
| **T-010** | Study A protocol v0.3 and intended use v0.3 (as TB-ASSESS-01): the PI named, the conflict-of-interest line, the wording; an independent co-investigator for the reading named by the owner | as TB-ASSESS-01 | as TB-ASSESS-01 | T-506 (words); owner signs | S | CR-087, CR-095 (PI, COI and wording only; the rest is the owner's re-read), PLAN-044 |
| **T-662** | Calendar as data: `docs/plan/calendar.yaml` (milestones, JP and TW holidays with sources) and a generator with a weekday test | `docs/plan/calendar.yaml`, `tools/gen_calendar.py`, `tests/unit/test_gen_calendar.py` | the test fails on a wrong weekday, on a milestone on a holiday of its site, and prints PQ lengths in working days | none | S | PLAN-013, PLAN-016, PLAN-011 (check half), PLAN-012 (check half) |
| **T-667** | Japan hardware decision note from the G1 numbers: pairs per hour, the Spark estimate, the night-window check against each threshold; a recommendation for 12-18 | `docs/plan/measurements/japan-hardware-estimate.md` (new) | each threshold has a number, its source and pass or fail | T-004 | S | PLAN-006 (agent half; the decision and order are the owner's, Q-05), PLAN-037 (inputs) |
| **T-668** | Card path lint: every "Files it touches" path of §6 exists on master or is marked "new" | `tools/doclint.py` (one check), the card file | the lint reports `tools/trialbox_doctor.py` if it reappears | T-002 | S | PLAN-047 |
| **T-669** | Hot documents as section files: `docs/DATA.md`, `docs/USER_GUIDE.md`, `docs/SECURITY.md`, `docs/RUNBOOK.md` split into one file per section with a generated index; RUNBOOK section numbers reserved in one table | `docs/{DATA,USER_GUIDE,SECURITY,RUNBOOK}.md` and their new section folders, `tools/doclint.py` | two branches that each add a RUNBOOK section and a data-table row merge with no conflict | T-002; the queue of §6.4 drained (PRs #64, #66, #68, #83, #85 edit RUNBOOK) | M | PLAN-033 (part), OPS-073 |
| **T-655** | Port the six review fixes of closed PR #71: failed flag commit recorded; rebuild source log; 503 on a dead flag store; reads create nothing; third night; `--write` needs both sources | `libs/tb_common/flags.py`, `services/console/admin_flags.py`, `tools/omop_parity.py`, `tools/goldens.py` | one test per fix, taken from #71 | #71 closed; FG D-271 (shares `tools/omop_parity.py`: after it) | S | CR-051 (part), PLAN-049 |
| **T-659** | Decision: one ingest stack (`services/adapter` or `services/dataplat`); what moves (contracts, quarantine, publish gate, MPI as alias table, lineage) and what is deleted | one decision file | the decision names the path in compose and the removal card (T-659b) | owner question (TB-DR-06 Q1); T-611 | S | DATA-002 (decision half) |

#### 6.2.5 Wave 2: to G2a and G2b Fri 2027-01-08 (design freeze)

Every High that changes design, and the large Blocker builds that are due at G2a.

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Closes (finding and CR ids) |
| --- | --- | --- | --- | --- | --- | --- |
| **T-600** | PHI pass on note text (FR-DEID-01): names, phones and chart numbers masked before chunks, full-text search and embeddings; the lake keeps the original under the `phi` label only | `libs/tb_common/phi_guard.py`, `services/lake/flatten.py` (note path), `services/embed_service/` (input), `services/doc_parser/` | planted identifiers in synthetic notes are absent from chunks, the FTS index and embedding inputs; screening results unchanged on the goldens | PR #70 (`phi_guard.py`); before T-203a | M | CR-028, DATA-020 |
| **T-603** | Context-aware budgets: the gateway exposes the context per alias and refuses over-long prompts before dispatch; callers size excerpts, full record, chart and retry from it; a note over the budget is flagged, not skipped; the cache skips cut-off or invalid answers and keys on `max_tokens` | `services/gateway/{core,app}.py`, `libs/tb_llm/client.py`, `libs/tb_common/llm.py`, `services/orchestrator/scenarios/evaluate.py`, `services/matching/cascade/engine.py`, `services/sitesetup/charts.py`, stub (context-limit persona) | per profile (8k, 16k, 32k) the longest prompt of each role is accepted by a stub that enforces the limit; a skipped note raises a flag on the candidate | T-601; FG D-276 (CR-004: tell fix group) | M | LLM-015, LLM-016, LLM-017, LLM-018, LLM-024, LLM-005 (cut half), CR-004 (flag half) |
| **T-604** | The perimeter is checked: the gateway exits in PRODUCTION when a perimeter URL is not a box address; `EGRESS_EXTRA` outside the table refused; addresses re-resolved; `LlmClient` refuses to build without a gateway in PRODUCTION; step confirmation header | `services/gateway/{app,policy}.py`, `deploy/egress.py`, `tools/trialbox/doctor.py` (one check), `libs/tb_common/llm.py`, `tests/integration/test_egress.py` | a gateway case in `make test-egress`; the three refusals as tests | T-108b (egress persistence), T-603 (same files) | M | LLM-036, LLM-037, LLM-038, LLM-043 |
| **T-605** | Prompt text out of stores: the trace store off for D3 text by default in PRODUCTION, 7-day retention with a scheduled prune; schema-violation audit detail without model output; vLLM told not to log requests; only allow-listed fields go upstream | `services/tracestore/{store.py,tracestore.yaml}`, `services/gateway/core.py`, `libs/tb_common/llm.py`, compose `command:` lines | planted-marker test finds no note text in `trace` or the audit detail; an 8-day trace is deleted under an injected clock | T-604; owner ruling on existing trace rows | S | LLM-040, LLM-041, LLM-042, LLM-019, REG-012 (trace part) |
| **T-606** | Injection hardening: every prompt gets a new registered version with the "text is data" rule; a planted-instruction screen in the guard; protocol text passes the PHI tripwire | prompt files through the registry of PR #75 (new versions), `services/guard/`, `services/doc_parser/`, ruleset approval page (one warning) | the screen flags the test set; three public protocols per language pass without a tripwire refusal; new versions qualified | PR #75, T-012a, T-208 | M | LLM-034, LLM-035 |
| **T-208** | Prompt-injection and false-positive suite (as TB-ASSESS-01); the trace store keeps no note text for the suite | as TB-ASSESS-01 | as TB-ASSESS-01 | PR #75, T-012a | M | LLM-034 (suite half) |
| **T-101b** | Follow-up to PR #75 (T-101): the approved ruleset pins prompt and vocabulary versions; a prompt or terminology change puts the study in "approval needed"; SCREEN keeps the old pin until re-approval | `libs/tb_llm/prompt_registry.py`, ruleset manifest schema, approval page (state only) | a prompt change marks the study; SCREEN keeps the old pin | PR #75, PR #82 | S | FIT-026, LLM-033 |
| **T-607** | Embedder under control: the wizard writes a mode the service accepts; `hash` refused in PRODUCTION; embedder weights pinned and verified; decision record with the criterion "safetensors from the publisher" (the embedder half of old T-009) | `tools/settings_wizard.py`, `services/embed_service/*`, `models/registry.yaml` (one build), `tools/pin_model.py`, one decision file | wizard output starts the service; `pin_model` succeeds on the chosen embedder | T-004 (measured embedder), T-674 | S | LLM-013, LLM-014, DEP-010 |
| **T-207** | Derived-data rest (as TB-ASSESS-01, what #59 left): screening reads stored rows; rulesets pin definition versions; the batch is scheduled; eGFR under-18 rule | as TB-ASSESS-01 (`libs/tb_common/derived.py`, `services/omop/derived_rows.py`, manifest schema, SQL generator derived templates) | as TB-ASSESS-01 | FG D-275 (owns the same templates: after it), T-106, T-201 | M | CR-066 |
| **T-216** | Missing data as the normal case: `missing_reason` per item, shown with who can answer (as TB-ASSESS-01); the feasibility sweep does not hard-exclude on unknown | as TB-ASSESS-01 | as TB-ASSESS-01 | T-116, T-112a; FG D-275 (CR-007) | M | CR-013, CR-007 (page half), FIT-024 (reason half) |
| **T-602** | SAE card (takes the SAE part of T-310 and what fix group D-277 leaves): write-path hook instead of sync on page GET; the 24-hour report counted in hours; clock rules per study from named sets, with the regulator from the site's country; expectedness and unblinding fields; the banner names the rule and who confirmed it; copy to the trial office mailbox; acknowledge on the case page | `services/datacore/lifecycle.py` (SAE part), `saerecord.py`, `services/console/sae_pages.py`, `templates/sae_case.html`, `forms.csv` (additive), study set-up page (one field) | +23 h not overdue, +25 h overdue; two studies, two clocks; clocks 0 raises an alert; regulator clock off for "expected" | FG D-277 (same files: after it) | M | CR-012, LIFE-022, LIFE-023, LIFE-024, FIT-025, UX-005, UX-028, CR-011 (leftovers) |
| **T-106** | OMOP second slice (as TB-ASSESS-01): the adapter writes the CDM, partitions, timings. Starts in wave 1 when T-104 lands; due G2a | as TB-ASSESS-01 | as TB-ASSESS-01 | T-104, PR #82, T-611 | L | CR-060 (first half), CR-061 (part) |
| **T-106b** | OMOP additions: all 39 CDM 5.4 tables; rows routed by concept domain; visit end; standard value concepts; an older snapshot never becomes `CURRENT`; every lake row has source table, row hash, ingest time, mapping version | `services/omop/{schema,load}.py`, `services/lake/{store,flatten}.py`, `services/adapter/mapping/engine.py` (provenance fields) | 39 tables exist; parity identical; one run of the OHDSI DQD recorded; out-of-order night test | T-106 | M | STD-031, STD-032, STD-033, STD-018, DATA-007, DATA-010 |
| **T-105b** | Follow-up to PR #82 (T-105): Athena loader with allow-list and version; `Maps to` for drugs; standard concept ids for conditions, drugs, procedures; edition map applied by date; honest DQD status; real URIs; one chart-number normaliser used at every entry point | `services/omop/{vocab_load,vocab,dqd}.py`, adapter edition call, `libs/tb_common/chartno.py` callers | with a test Athena extract ATC-coded drug rows get RxNorm ingredient ids; three chart-number spellings give one pid; an opt-out of an unknown number is flagged | PR #82, T-104 | M | STD-030, STD-034, STD-041, STD-045, DATA-005, CR-061 (vocabulary half) |
| **T-202** | Lake exported from OMOP: parity in CI, flag flip (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-106, T-106b | M | CR-060 (second half) |
| **T-201** | Clinical conflicts detected; conflicts page for the steward over `tb_conflict`; a conflict is not withdrawn when one source goes silent; the existing trial-value page renamed (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-202, T-102b, T-116 | L | CR-061 (conflicts half), FIT-018, DATA-011 |
| **T-305a** | Snapshot pinning pulled forward from T-305: every job is pinned to a snapshot; a snapshot-age check | `services/lake/store.py`, `services/orchestrator/jobs.py` (pin field) | a job started before a publish finishes on its own snapshot; a stale snapshot is refused | T-106b (`lake/store.py`) | M | CR-063 |
| **T-112a** | Data-operations: the `dataops` schema, batch states and the adapter hook (as TB-ASSESS-01, first half) | `services/datacore/dataops.py` (new), `services/adapter/` (one hook) | as TB-ASSESS-01 | T-102b, T-611 | M | CR-067 (first half), FIT-017 (schema half) |
| **T-614** | Japan ICD-10 as ICD-10: the right system URI, WHO-only categories in the groupers, the MEDIS target kept when not in ICD-10-CM | `jp_core/ssmix2_site.yaml`, `services/adapter/sources/ssmix2/source.py`, `services/adapter/validate/jpcore.py`, compiler grouper table | `E14.9`, `I64`, `F00.1` records make the matching criteria true or unknown, never false; `jpcore` 0 errors | PR #82 | M | STD-010 |
| **T-615a** | SS-MIX2 reader hardening: encodings with quarantine, OBX-11 status, OBX-2, time fallback, PID-30 death flag, repetitions, ORC-5; one bad row is rejected and counted, the table continues; hard cases written by `ssmix2_export` | `services/adapter/sources/ssmix2/*`, `services/adapter/pipeline.py` (row reject), `tools/ssmix2_export.py`, fixtures | the five byte patterns load or are quarantined; a `D` result is a tombstone; PID-30 `Y` marks deceased | T-614 (same files), FG D-275 (status use) | L | STD-020, STD-021, STD-023, STD-025, STD-013 (SS-MIX2 half), CR-015 (supports) |
| **T-616** | Inbound FHIR contract: the subset read is documented and widened; `deceasedBoolean`; `medicationReference`; offsets kept; an Observation with a period only; unread elements counted in the ingest report | `services/lake/flatten.py`, `services/adapter/mapping/engine.py`, `services/omop/load.py`, DATA section file | `deceasedBoolean` removes the patient from the base cohort; parity identical | T-106b | M | STD-013 (FHIR half), STD-012, STD-014, STD-015 |
| **T-206a** | Opt-out worker v1 (as TB-ASSESS-01, core): the worker, the register read on every path; the line "FEAS counts read it" is removed (fix group D-278 owns it) | `libs/tb_common/optout.py`, `services/datacore/optout_worker.py` (new), `services/omop/load.py` (one call) | as TB-ASSESS-01 | T-112a; FG D-273, D-278 | M | CR-027, CR-019 (rest), CR-026 (rest), DATA-022, FIT-023 |
| **T-102c** | Call-site migration to `permit` by page group (last third of T-102): 54 inline checks, the team fallback removed; page and API give the same answer | `services/console/{app,home,team}.py` and page modules, one PR per page group | no inline role check left (grep test); ROLE-017 test | T-102b | L | CR-024 (last third), CR-018 (long term), ROLE-017 |
| **T-103** | One reveal path for every chart-number reveal (as TB-ASSESS-01); a written reason required for "other"; rate limits in the store | as TB-ASSESS-01 | as TB-ASSESS-01 | T-102c (same handlers) | M | CR-024 (reveal), CR-017 (long term), ROLE-016 |
| **T-116** | Wording, the rest after T-506: every i18n file, report writers, mail templates and the orchestrator through the forbidden-word check (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-506, T-010 | M | CR-078, FIT-006 (rest) |
| **T-310a** | Weekly PI sample of ten not-matched patients with a counter; send-back re-enters the PI list; the not-matched list hidden by default in PRODUCTION until the site's check passes (first part of T-310) | `services/orchestrator/` weekly job, `services/console/app.py` (not-matched routes), `templates/excluded.html`, a `tuned_patients` table | sample of ten recorded; a sent-back patient returns to the PI list; hidden by default in PRODUCTION | T-116, T-102c | M | CR-014, FIT-007, UX-032 |
| **T-112b** | Data-operations console page and `/api/v1/data/*` (as TB-ASSESS-01, second half); the readiness page names the loaded feed tier | dataops page and i18n (own files), `/api/v1/data/*` router (new), `/site` readiness (one block) | as TB-ASSESS-01 | T-112a, T-102c | M | CR-067, FIT-017 (console half), ROLE-022 (ingest history) |
| **T-682** | Export watermark and ledger: every console download has a `flow.export` row and a stamp that matches it; workbooks and notices inside the flow ledger | `libs/tb_common/flowledger.py`, console export routes (one call each), report renderers | every download route has a ledger row (route-walk test); the file's stamp equals the row | T-102c | S | DATA-015, DATA-023 |
| **T-621** | Amendment handling: effective date and IRB reference per criteria version; the version on every mark; the re-screen list after an amendment (a relaxed criterion returns a set-aside patient with the reason); visit-schedule versions | `services/criteria_compiler/service.py`, `libs/tb_common/ruleset.py`, manifest schema, `services/console/approval.py`, `studies.py`, `sitestore.py` (additive column), `services/datacore/lifecycle.py` (schedule), i18n (own file) | a version with a future effective date is not used; the planted set-aside patient returns; two schedule versions judged by visit date | T-101b (manifest schema), T-602 (`lifecycle.py`) | L | LIFE-009, LIFE-010, LIFE-012, LIFE-011 |
| **T-622** | Study state and identifiers: state machine (start-up, open, paused, closed); registry ids (jRCT, Taiwan, NCT), sponsor, protocol number, SIV date; jobs and mails follow the state | `services/console/sitestore.py`, `study_setup.py`, `services/orchestrator/scheduler.py`, `notify.py`, templates and i18n (own files) | a paused study gives no list and no mail; jRCT and Taiwan ids validate and print on the log | T-621 (`sitestore.py`) | M | LIFE-008, LIFE-013 |
| **T-115** | EDC prefill controls, merged card (T-115 + the record half of T-205 + what fix group D-281 leaves): E-12, E-14 to E-16, E-23; plain-text REDCap version call; validation types and formatting; ODM XSD test in CI; a real-REDCap cassette run; `https` only | as TB-ASSESS-01 plus `services/rc_bridge/client.py`, `services/rc_sim/app.py`, `services/datacore/{forms,export}.py` | as TB-ASSESS-01; plus: plain-text version accepted; `xmllint` passes on both exporters; cassettes from a test project replay green | FG D-281, T-104; a REDCap sandbox (owner) | L | CR-062 (first half), CR-036 (rest), LIFE-021, STD-060, STD-061, STD-062 |
| **T-205** | Second factor at signing, rewritten: fix groups D-279 and D-281 do the step-up and the lock; this card adds signing for a directory (OIDC) account and a neutral, correct signature meaning text; the shared token cannot forge `reauth-` | `services/edc/service.py` (`ODM_MEANING`), `services/console/edc_pages.py` (signing branch), `i18n_edc.py` | TST-EDC-04 passes for local and OIDC accounts; a unit test pins the meaning text in three languages | T-115; FG D-279, D-281 | S | CR-035 (rest), CR-034 (signing part), REG-025, REG-021 (text half) |
| **T-302a** | Consent record (first part of T-302): ICF version list per study checked against the IRB's version; history rows; no implied consent; date-order checks; the re-consent worklist; one way to record consent | `services/datacore/lifecycle.py` (consent part), `forms.csv` (additive), `services/console/team.py` (ICF list), templates and i18n (own files) | an enrolment without a consent record is held with an alert; a visit before consent is flagged; a new ICF version lists the subjects to re-consent | T-602 (`lifecycle.py`), T-516 | M | FIT-009, LIFE-018, LIFE-019, UX-012 |
| **T-648** | Source and copy rule for prefill and the Part 11 / ER/ES assessment: the source statement; the monitor's path; clause-by-clause assessment; draft answers to the PMDA EDC management sheet; the sponsor letter template | `docs/validation/part11-ers.md` (new), `docs/validation/source-and-copies.md` (new) | no "open" row in the assessment at G3; the sponsor letter quotes the source statement | T-205, T-215 | M | REG-021, REG-024 |
| **T-110b** | Release identity and bundle gates (the unbuilt half of T-110): `tools/release.py`, `release.json` and its schema, version from one place, tag, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`, about page; `make_bundle.sh --gates` mandatory; SBOMs inside the signed bundle; no test mail servers in a hospital bundle | `tools/release.py` (new), `schemas/release.schema.json`, `tools/make_bundle.sh`, `pyproject.toml` (version), about page (own router), `CHANGELOG.md` | a bundle without gates cannot be built; `release.json` in the bundle names every image digest and SBOM; the about page shows the release | PR #68 (edits `make_bundle.sh`), T-104; before T-111b | M | CR-046, CR-081, OPS-018, OPS-017 |
| **T-117b** | Backup wiring (the unbuilt half of T-117): install installs the cron; an alert route is required in PRODUCTION; `doctor` checks the backup age and the off-box target; Docker-side run; WAL archiving on by default; settings and `.env` in the backup; restore writes an audit row and keeps a copy; one point in time | `deploy/install.sh` (cron step), `deploy/backup/*.cron`, `tools/trialbox/{doctor,backup,backup_schedule}.py` | rehearsal: after install the cron exists and the first backup runs; `doctor` FAILs on a missing off-box target; a restore leaves an audit row | FG D-274 (same files: after it), PR #66 (backup-check command), PR #68 (`install.sh`) | M | CR-058, DATA-024, OPS-028, OPS-046, OPS-048 |
| **T-108a** | Operations in code, part a (of T-108): compose limits (`mem_limit`, `pids_limit`), health checks, a watchdog that restarts an unhealthy service with an audit line | `deploy/docker-compose*.yml` | a stopped vLLM health endpoint leads to a restart and an audit line; every service has limits (lint) | T-673 (compose), T-104 | M | CR-082, OPS-029 |
| **T-108b** | Operations in code, part b: systemd units; egress table persisted across a reboot; the stack starts after a host restart | `deploy/systemd/*` (new), `deploy/{install,network}.sh`, `deploy/egress.py` | reboot test in the rehearsal: egress closed before the first container starts | T-108a; PR #68, PR #85 (`egress.py`) | M | CR-043, OPS-049, OPS-064 (restart half) |
| **T-111b** | Follow-up to PR #83 (T-111): update refused while a job runs or in the night window; lake format check on rollback; vendor key custody (passphrase or token) and a compromise drill; staging not in `/tmp` | `tools/trialbox/update.py`, `tools/sign_bundle.py`, RUNBOOK §5 (section file) | update refused while a job runs; rollback after a lake format change leaves a box that screens | PR #83, T-110b | S | CR-047 (rest), OPS-020, OPS-021, OPS-022, OPS-023, OPS-025 |
| **T-631** | Host tree in the signed release: compose files, host tools and configuration ship in the bundle and change by update; `/opt/trialbox/current` names the release | `tools/make_bundle.sh`, `tools/verify_update.py`, `tools/trialbox/update.py`, `deploy/install.sh`, `docs/handover/OFFLINE-MEDIA.md` | drill: an update that changes a compose variable takes effect and rolls back; a changed compose byte on the media is refused | T-111b, T-110b | M | OPS-010, OPS-020 (host tree) |
| **T-632** | Site inputs and a finished install: mapping folder and feed mount; the installer ends with TLS on, cron files installed, the enrolment code printed, an `https://` URL that answers; the answers-file example works; the network sheet renders every overlay; install names the judge model | `deploy/docker-compose.yml` (adapter mounts), `services/adapter/cli.py` (mapping lookup), `tools/settings_wizard.py`, `deploy/install.sh`, `tools/network_sheet.py`, `tests/fixtures/onboarding/*` | the rehearsal installs with a mapping not in the image and ingests from a mounted folder; every RUNBOOK §1 command runs in a test | T-631, T-117b (`install.sh` order), PR #68 | M | OPS-011, OPS-013, OPS-012, OPS-014 |
| **T-634** | Host baseline: one host system decided and written in all three documents; disk unlock that fails outside the hospital (no TPM-only unlock); sealed site keys at install; input firewall; SSH; offline OS patch bundles; a stricter `check_host` | `deploy/hardening/` (new), `deploy/check_host.sh`, `deploy/install.sh`, `tools/apply_update.sh` (`ospatch`), SECURITY §1 (section file), one decision file | on the rental box a moved disk does not unlock; `check_host` FAILs on plain site keys; an OS patch bundle applies and the canary passes | T-632 (`install.sh` order), T-210b (key code); owner answer on the host system | M | OPS-043, OPS-024, OPS-062, OPS-052, OPS-015 |
| **T-210a** | Windows/WSL2 hardening, part a (of T-210): preflight checks for BitLocker, swap, hibernation, Windows Update restarts; `check_host --wsl2` | `deploy/windows/*`, `deploy/check_host.sh` (wsl2 branch) | as TB-ASSESS-01 | T-634 (`check_host.sh` order); T-111 (PR #83), T-113 (PR #85) | M | CR-041 (first third), OPS-061 |
| **T-210b** | Keys under a KEK and unseal, part b: `kek.py`, key loading in the adapter, `tools/keys.py`, a key inventory, rotation for every key, `doctor` check | `libs/tb_common/kek.py` (new), `services/adapter/pidmap.py` (key load), `tools/keys.py` (new), `tools/trialbox/doctor.py` (one check), `tools/apply_update.sh` | as TB-ASSESS-01 | T-612 (key load), T-111b | M | CR-041 (second third), OPS-058 |
| **T-212a** | Boundary, part a (of T-212): mail boundary. Chart-number spreadsheets no longer mailed as a password zip (after owner decision OD-1); link mode can deliver files; mail authentication fails closed | `services/mail_gateway/*`, mail templates | the default is not `zip`; a failed mail auth sends nothing | owner decision OD-1 | M | CR-025 |
| **T-212b** | Boundary, part b: the gateway routes on a verified caller, not a self-declared header; role rights bound to the verified service; the model key in `secrets rotate` and in a secret file | `services/gateway/core.py`, `models/routing.yaml`, `tools/trialbox/secrets*.py`, compose secrets | a doc-parser token cannot use role `judge`; rotate: old key refused, new key works | T-605 (`gateway/core.py`), PR #68 | M | CR-040, LLM-039 |
| **T-212c** | Boundary, part c: one PostgreSQL role per service with least rights, `CREATEDB` dropped; HAPI token | `deploy/docker/db-init/*`, `deploy/docker-compose.yml` (role env), each store's connection settings | a service role cannot read another service's schema (test per role) | T-104, T-108a (compose order) | M | CR-037 |
| **T-633** | Platform day-2 for CGMH's shared host: backup, restore, logs, audit archive, update and rollback for the namespace form; block storage for the database; the platform questionnaire (Kubernetes, Docker, Slurm); where patient data lives and who can read it | `deploy/platform/` (CronJobs, an update overlay), `tools/trialbox/platform.py`, `tests/platform/`, RUNBOOK §14 (section file), `docs/plan/sites/site-survey.md` (three questions) | on the kind cluster: a backup file appears on the share claim, a wipe and restore pass, a digest update and its rollback pass, `doctor --platform` fails when no backup job exists | T-113b, T-210b | L | OPS-050 (rest), OPS-068, OPS-069, OPS-066 (questionnaire; the answer is CGMH's), OPS-070 |
| **T-213a** | Acceptance environment (first part of T-213): `deploy/docker-compose.acceptance.yml` and the tool, named `tools/acceptance_env.py` because `tools/acceptance.py` exists | `deploy/docker-compose.acceptance.yml` (new), `tools/acceptance_env.py` (new) | the environment starts with the identity overlay on the owner's B200 or the rental box | T-108a, T-109 (merged part), PR #83, T-117b | M | CR-071 (first half), OPS-051 (run half) |
| **T-214** | arm64 builds, `gb10` profile measured, two-device link (as TB-ASSESS-01); our own or a mirrored arm64 vLLM image with an SBOM; a dated driver-hold decision; memory limits on the Spark. A short Spark run before 12-18 if the Spark exists | as TB-ASSESS-01 (`tools/trialbox/doctor.py`, not `tools/trialbox_doctor.py`) | as TB-ASSESS-01 | the Spark; T-012a, T-110b, T-673 | L | OPS-063, OPS-019, CR-089 (supports) |
| **T-104b** | Database base and major (dependency batch 2, data plane): Debian 13 base, PostgreSQL major decided by the owner, pgvector and PGroonga pinned, pgBackRest pinned from PGDG; one PostgreSQL major for the db image, the demo and CI | `deploy/docker/db.Dockerfile`, `demo/Dockerfile` (one line), CI workflow (one line), `deploy/images.lock` | `pg_config --version` equal in the db image, the demo and CI; T-104's acceptance still passes | T-104; owner question on the major; before any site data | M | DEP-013, DEP-014, DEP-027 |
| **T-675** | Heavy extras in an image: a `trialbox-ml` image from a second hashed lock (docling, embed, OCR) or the code paths removed; `TB_EMBED_MODE` set in compose | `pyproject.toml`, `tools/supply_chain/lock.py`, `deploy/docker/ml.Dockerfile` (new), `deploy/docker-compose.yml`, `Makefile` | import test in the image; pip-audit over both locks; doc-parser converts a fixture PDF | T-673, T-607 | M | DEP-012 |
| **T-656** | Site time zone as one setting: `site.tz` with no code default; `doctor` fails when the mapping zone, `TB_TZ` and the host zone differ; the log day follows the site | `libs/tb_common/config.py`, callers of the `Asia/Taipei` literal, `tools/trialbox/doctor.py` (one check) | no `Asia/Taipei` literal outside settings and tests; the mismatch fails `doctor` | PR #86 (D-270) | S | STD-016, OPS-036, OPS-056 |
| **T-215** | QMS-lite records, change classes, FS, VMP (as TB-ASSESS-01); `docs/validation/` layout; VMP sections named in REG-027 and the standards position (IEC 62304, 82304-1, ISO 13485); staged roll-out procedure; evidence that would survive a sponsor audit | as TB-ASSESS-01 plus `docs/plan/25-vmp.md` | as TB-ASSESS-01; VMP v1.1 signed before IQ | T-002, T-007 (merged) | M | REG-027, REG-029, REG-030, OPS-026, CR-096 (QMS-lite part), PLAN-027 (FS part) |
| **T-643** | Record inventory: every GxP record the box makes or holds (screening log, delegation-log copy, consent checks, SAE register, prefill audit …) with owner, retention, source or copy; generated into the release record | `docs/validation/record-inventory.md` (new), `tools/gen_traceability.py` (one check) | every record type in the code has a row (test over the store modules) | T-215 | M | REG-022 |
| **T-644** | One risk file on one scale: plan §5 and TB-DS-11 merged; control status from tests; missing hazards; a residual only where the control has a passing test; a project-risk scale | `docs/validation/risk-register.md` (new), `tools/gen_traceability.py` (one check) | the generator fails when a residual rests on a control not verified; RSK-03 and H-03 agree | T-215 | M | REG-028, REG-018, PLAN-051 |
| **T-665** | Backlog file: one generated list of cards with gate, state, PR, register rows and deep-review rows; the plan's totals and the status file come from it; `--gate G3 --open` prints 0 to pass | `docs/plan/backlog.csv` (new), `tools/gen_backlog.py` (new), test | the totals of §6.6 equal the file; G3's condition is computable | T-002, T-668 | M | PLAN-028, PLAN-032, PLAN-034, PLAN-035, PLAN-040, PLAN-050, PLAN-030 (measure half) |
| **T-666** | Traceability status from evidence: the matrix generated from test markers and a per-item evidence file; IRB, intended-use, Study A and owner-decision rows added | `tools/gen_traceability.py`, `tools/trace_check.py` (new), `tests/**` markers, `docs/plan/25-traceability.csv` (generated) | the ten merged items show `passing` with a PR and a test path; the tool fails on a URS with no test and on an unknown id | T-665, T-641 | M | FIT-001, PLAN-046 |
| **T-011** | Synthetic site built from a schema and code lists (as TB-ASSESS-01); the data-scan limits revisited once the sites state their formats | as TB-ASSESS-01 | as TB-ASSESS-01 | none | M | CR-015 (supports), CR-088 (supports) |
| **T-617b** | Licence register as data (rest of T-617): `docs/licences/register.csv`; a build fails when a shipped data file has no row; SNOMED remnants removed; model licence rows verified and enforced; ATC permission asked | `docs/licences/register.csv` (new), the three SNOMED-bearing files, `models/registry.yaml` (licence rows), CI step | the build check; `qualify` refuses a build with no licence file | T-617a, T-012a | S | STD-044, LLM-012, DEP-011, PLAN-041 |

#### 6.2.6 Wave 3: to G3 Fri 2027-02-26 (feature complete)

All remaining Highs; the Mediums; the Lows in one polish card per area. Findings from the PoC sessions rated "before G3" are added here at the GP exit review (Mon 2026-12-14) under new numbers of the right block.

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Closes (finding and CR ids) |
| --- | --- | --- | --- | --- | --- | --- |
| **T-203a** | Vector store and chunker in pgvector (part a of T-203) | `services/vec/*` (new), `services/embed_service/`, `tools/backup_drill.py` | as TB-ASSESS-01 | T-104, T-600, T-607 | M | CR-068 (vectors), FIT-004 (part) |
| **T-203b** | S2b retrieval reads the vector store behind a flag (part b; safety core) | `services/lake/store.py` (one function), `services/orchestrator/scenarios/screen.py` (S2b call) | as TB-ASSESS-01; goldens unchanged with the flag off | T-203a, T-305a | M | CR-068 (part) |
| **T-203c** | "Patients like this one" page (part c) | neighbours page and i18n (own files) | as TB-ASSESS-01 | T-203b, T-102c | M | CR-068 (part), FIT-004 (part) |
| **T-204** | The twin: `tb_patient_profile` v1 and its API (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-102c, T-106 | M | CR-068 (twin), FIT-004 (part) |
| **T-608** | Gateway under load and the LLM Mediums: one timeout budget across the three layers, an open breaker on `/readyz` within 60 s, `model_busy` in under 1 s; the judge schema validated on every path; `bakeoff.py` and `judge_eval.py` say what they do not measure; stub token counts labelled | `services/gateway/{core,app}.py`, `libs/tb_llm/client.py`, `tools/bakeoff.py`, `tools/judge_eval.py` | mock server that never answers: no thread exhaustion at 100 parallel calls | T-603, T-212b | M | LLM-023, LLM-022, LLM-032, LLM-046 |
| **T-609** | Model misbehaviour procedure: one switch that turns note reading off; a report of the runs and patients a given model build touched; the RUNBOOK page and its drill | `libs/tb_common/flags.py` (one flag), `tools/trialbox/` (new `model_report.py`), RUNBOOK section file | the switch stops note-stage calls within one job step; the report lists the planted runs | T-012b, T-209a | M | OPS-042 |
| **T-109b** | Identity leftovers after fix group D-279 (T-109 is closed): breached-password list, password history, `doctor` fails without MFA in PRODUCTION, WebAuthn in the console, assertion replay window | `services/console/{auth,identity}.py`, `tools/trialbox/doctor.py` (one check) | `doctor` FAILs in PRODUCTION without MFA; a replayed assertion is refused | FG D-279, T-102c | M | CR-033 (rest) |
| **T-107** | Catalogue loaded as data; items page (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-105b, PR #75, PR #80 | M | CR-067 (catalogue half) |
| **T-307** | Catalogue gaps and the instrument copyright register, shrunk to what PR #80 leaves (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-107, PR #80; owner | M | — |
| **T-610** | Japan and Taiwan code maps at scale: YJ ingredient prefix in drug value sets and an ingredient-to-ATC table; JLAC10 analyte and material suggestions; NHI maps into the adapter look-up | compiler value-set model, `services/adapter/sources/ssmix2/source.py`, `libs/tb_common/refdata_jp.py`, `services/sitesetup/mapping.py` | on a site-shaped synthetic master of 2,500 ingredients 95 % of order lines resolve; unmapped codes listed by volume in the ingest report | PR #76, T-105b, T-615a | L | STD-042, STD-043, STD-024 |
| **T-618** | Reference data remainder (WS-08.8) after PR #76: full CT.gov download, NHI service-code fetcher and full drug list, 2014-code mapping at ingest, withdrawing a source, jRCT, the P0 baseline lists still missing | `libs/tb_common/refdata*.py`, `tools/refdata_fetch.py` | each list has a version, a source and a fetch test from a cassette | PR #76 | M | — |
| **T-619a** | Standards conformance in CI: TW Core slices with TW Core code systems and an offline rule file; JP Core 1.2.0 diff; HL7 validator job; the five rulesets translated and evaluated through CQL with the pinned jars, with a UTC-edge case and the comparator on censored values | `tw_core/demo_his.yaml`, `tools/jpcore_rules.py`, `twcore_rules.json` (new), CI workflow, `services/criteria_compiler/equivalence` | HL7 validator with TW Core 1.0.0 on 200 resources: 0 errors; SQL and CQL agree on the equivalence fixture | T-616, T-672 | M | STD-011, STD-017, STD-070 |
| **T-619b** | AE grading and CDASH IE / DS: CTCAE grade and version on the AE form; MedDRA position decided; IE and DS tags fed from the screening log; the CDISC coverage stated | `services/datacore/builtin/forms.csv`, `services/edc/{cdash,mapping}.py`, i18n (own file) | an oncology study shows grade 1 to 5 with the version; the ODM export carries IE rows for a screen failure | T-115, T-623 | M | STD-050, STD-051, STD-063 |
| **T-659b** | One ingest stack, the removal: the path not chosen in T-659 is deleted from compose and the tree; what it had (contracts, quarantine, MPI alias table, lineage) lives in the kept path | `services/adapter/` or `services/dataplat/`, compose | one ingest path in compose; the T-611 fault tests still pass | T-659, T-611, T-106b | M | DATA-002 |
| **T-206b** | Opt-out, erasure and retention (rest of T-206): after an opt-out and a worker run the erasure inventory of TB-DR-06 §3.5 holds no row of the pid except the audit decision's form; retention table for the core patient stores; no name or national ID kept in the demo mapping; source delete has an erase path | `services/orchestrator/scenarios/retention.py`, `services/adapter/pidmap.py`, `services/omop/`, `libs/tb_common/derived_store.py`, `services/lake/`, `services/vec/` | the inventory test; retention table enforced | T-206a, T-203a; owner question on audit rows | M | CR-027 (rest), DATA-022, DATA-012, DATA-013, DATA-014 |
| **T-305b** | All-history back-fill and batched publish (part b of T-305) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-106b, T-202, T-305a | L | CR-061 (back-fill half) |
| **T-305c** | Retention (part c of T-305) with a hold per study and a per-study retention period | as TB-ASSESS-01 plus settings schema | an open study's 400-day-old output survives; a closed study's is kept for its period | T-305b, T-622 | M | LIFE-027 |
| **T-316a** | Consortium, synthetic two-box test: signed counts with complementary suppression so differencing cannot recover a small cell; opt-out changes no outbound count (part a of T-316) | `tools/signed_counts.py` (new), `services/orchestrator/scenarios/cohort.py`, `services/deliverables/disclosure.py` | the differencing test (37/34) cannot recover 3 | T-304a, T-206a | M | CR-031 (counts part), DATA-006 |
| **T-619c** | Data and standards Mediums and polish, one PR per sub-topic | as each finding names | as each finding names | T-106b, T-616 | M | DATA-016 (what PR #70 and FG D-275 leave) |
| **T-301a** | Product completeness, PI pages (first half of T-301): the PI list prioritised; feasibility and approval pages; help | PI list, feasibility and approval templates and i18n | as TB-ASSESS-01 | T-116, T-103 | L | CR-086, FIT-024 (priority half) |
| **T-301b** | Product completeness, patient side (second half of T-301): reminder card, `.ics`, "window closes in 2 days", phone pages | patient and phone templates and i18n, `services/orchestrator/lifecycle`, `tools/visit_card.py` (new) | as TB-ASSESS-01 | T-301a | M | FIT-010 |
| **T-302b** | REDCap arms, events, repeating instruments; calculated fields; "erase hidden values" (part b of T-302) | `services/edc/*`, `services/rc_sim/` | as TB-ASSESS-01 | T-115, T-205 | L | CR-062 (rest), LIFE-021 (arms half) |
| **T-302c** | Copy-assist page and a plain-file route, audited (part c of T-302) | copy-assist page (own files), `services/datacore/` | as TB-ASSESS-01; copy-assist is audited | T-302b | M | FIT-015 |
| **T-302d** | ODM import and sponsor readers; sponsor column mapping of the screening log (part d of T-302) | `services/edc/odm.py`, sponsor reader modules | as TB-ASSESS-01 | T-302b | M | — |
| **T-303** | Monitor SDV page (as TB-ASSESS-01): access to enrolled subjects only, limited to the cited record items | as TB-ASSESS-01 | as TB-ASSESS-01; the monitor tests of FIT-002 | T-102b, T-205, T-648 | M | FIT-002, ROLE-012, LIFE-026 |
| **T-304a** | Statistics page with study scope (part a of T-304) | `services/datacore/stats.py` (new), stats page | as TB-ASSESS-01 | T-112b, T-201, T-207 | M | FIT-017 (statistics) |
| **T-304b** | EXTRACT and Define-XML (part b of T-304) | `tools/extract.py` (new), export writers | as TB-ASSESS-01 | T-304a | M | FIT-017 (export list) |
| **T-304c** | Audit CSV, ISF bundle with a hashed index, invoice-ready activity report, CRC minutes per candidate (part c of T-304) | export writers, report modules under `services/console` and `services/deliverables` | activity report totals equal the screening log; the bundle index lists every file with a hash | T-304a, T-623 | M | FIT-013, FIT-014 |
| **T-310b** | IRB-text gate on the study set-up page (second part of T-310) | study set-up page | as TB-ASSESS-01 | T-622 | S | — |
| **T-310c** | Override report (third part of T-310) | `services/orchestrator/` report | as TB-ASSESS-01 | T-310a | S | — |
| **T-311a** | Cited profile page, code (as TB-ASSESS-01); the specialty templates of T-308 are built in this card's slot on the same page file | as TB-ASSESS-01 plus `i18n_profile.py`, `tb_specialty_template` | as TB-ASSESS-01 and T-308's | PR #75, T-203b, T-204, T-208, T-004, T-116, T-107 | L | CR-068 (profile page), FIT-004 (part) |
| **T-311b** | Study C and D protocol drafts (the document half of T-311) | protocol drafts under `docs/plan/` | as TB-ASSESS-01 | T-311a; owner | S | — |
| **T-312** | Physician annotations (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-204, T-201, T-109b, T-311a | M | CR-068 (annotations) |
| **T-314** | Restricted clinician view (as TB-ASSESS-01), without phenotype, derived scores or per-criterion eligibility until the regulatory consultant's opinion | as TB-ASSESS-01 | as TB-ASSESS-01; the clinician role gets 404 on those routes | T-102c, T-311a, T-649a | M | CR-030, REG-016 |
| **T-320a** | EMR launch link (split from T-320: it is a reveal, safety core) | `services/sitesetup/*`, reveal path of T-103 | the link passes through the one reveal path and is audited | T-103 | M | FIT-011 |
| **T-320b** | Site set-up limits, work log, admin leftovers after PR #66 (rest of T-320) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-301a, PR #66 | M | — |
| **T-623** | Pre-screen log and screen-failure detail: every mark is a pre-screen row; the failed criterion id and version on the row | `services/console/screening_log.py`, `services/datacore/lifecycle.py`, `forms.csv` (additive), templates and i18n | three marks give three pre-screen rows and one log row | T-621 | M | LIFE-015, LIFE-016 |
| **T-624** | Screening cadence: new in-scope patients enter in every weekly run and after ingest for booked patients | `services/orchestrator/scenarios/microbatch.py`, `scheduler.py` | the Tuesday-to-Friday case in the e2e stage; night budget respected | T-305a | M | LIFE-014 |
| **T-625** | Cross-study view of one patient and the "other study" proposed fact | `services/console/{studies,home,team}.py`, templates, i18n | the planted shared patient shows the flag; no study name leaks to a reader without rights | T-102c | M | LIFE-029 |
| **T-626** | Outside-medication checks (medication review, NHI MediCloud, お薬手帳) recordable as proposed facts; contact outcomes as URS-CRC-05; contact-attempt limit | `services/console/sitestore.py`, `i18n_step2.py`, `forms.csv`, `services/matching/proposed.py` (new sources) | a recorded check appears as a proposed fact and never counts until confirmed; a fourth attempt is refused at a limit of three | T-102c | M | FIT-012, FIT-008 |
| **T-627** | Study A tooling: a frozen record with hashes; an as-of SCREEN equal to a SCREEN on a snapshot built to that date; four frames per study; no quote in any frame | `tools/trialbox/study.py` (new), lake as-of filter, `tuned_patients` | the four checks on the synthetic site | T-310a, T-305a | L | FIT-016 |
| **T-629** | Site realities: a death record removes the patient from Approach lists; study type selects the SAE table; a numeric chart-number column is refused at import; the other safety-relevant unstated needs of TB-DR-01 §4 | `services/console/home.py`, candidates pages, `saerecord.py`, study set-up, adapter import checks | one test per need | T-602, T-616; site surveys | L | FIT-U03, FIT-U04, FIT-U06, FIT-U08, FIT-U09 |
| **T-620** | Trial lifecycle Mediums: deviations proposed from the facts the box holds; randomisation fields; treating-physician artefact for a referral | `services/datacore/lifecycle.py`, `forms.csv`, referral templates | as each finding names | T-623 | M | LIFE-017, LIFE-020, LIFE-025, UX-034 |
| **T-108c** | Operations in code, part c: mail outbox; a send key cannot stay in `sending`; `mail resolve` command; per-recipient limits | `services/mail_gateway/*`, `tools/trialbox/__main__.py` (one subcommand) | as TB-ASSESS-01 | T-212a | M | CR-085 |
| **T-108d** | Operations in code, part d: job cancel, breaker, declared config list, log caps sized from G1, `logrotate` files | `services/orchestrator/jobs.py`, `libs/tb_common/config.py`, `tests/unit/test_config_declared.py`, `tools/trialbox/logs.py` | as TB-ASSESS-01; a full SCREEN night leaves no log gap | T-108b | M | OPS-034, OPS-037 |
| **T-209a** | Monitoring, part a (of T-209): `/metrics` and thresholds; one health line in the morning mail and a daily health mail; disk, certificate days, canary, backup-verified age | `libs/tb_common/metrics.py` (new), `/metrics` routers, `deploy/docker-compose.monitoring.yml` (new) | red health line when the canary failed, the backup is old, a disk is over 85 % or the certificate ends within 30 days (frozen-clock tests) | T-108a, T-117b | M | OPS-027, OPS-030, OPS-031, OPS-032, OPS-047 |
| **T-209b** | Support bundle (part b) | `tools/support_bundle.py` (new) | as TB-ASSESS-01; no patient data in the bundle (data scan) | T-209a | M | — |
| **T-209c** | Admin screens remainder after PR #66 (part c): backup and update tiles; links to `/ops/identity` and `/ops/flags`; third-party logs kept apart; unused-account report | `services/console/admin_*`, `templates/admin.html` | admin reaches unlock in two clicks from `/admin` | PR #66, T-209a | M | ROLE-021, ROLE-022, OPS-035, OPS-059 |
| **T-210c** | Encrypt `phi` outputs and uploads under the KEK (part c of T-210) | `libs/tb_common/kek.py` callers, output and upload writers | as TB-ASSESS-01 | T-210b | M | CR-041 (last third) |
| **T-211a** | Audit integrity, part a (of T-211): signed heads and off-box anchors, on top of fix group D-272; NTP out of sync is a FAIL | `libs/tb_common/audit.py`, `tools/audit_verify.py`, `tools/trialbox/doctor.py` (one check) | as TB-ASSESS-01 | FG D-272, T-210b | M | CR-042 (signing), CR-054 (rest), DATA-021, OPS-055 |
| **T-211b** | One audit writer (part b) | audit-writer service or role split, the six writers | as TB-ASSESS-01 | T-211a, T-212c | M | CR-042 (one writer) |
| **T-211c** | Audit browser (part c) for privacy office and steward only: filters, per-patient report, verify, translated labels | audit page and i18n (own files) | crc gets 403; one patient's reveals found in two steps; verify shows the chain state | T-211a, T-102c | M | ROLE-013 |
| **T-212d** | Boundary, part d: SSRF guard, scrubber rule on, gitleaks in CI, secrets out of `env_file`, mTLS position recorded | `libs/tb_common/{http,logging}.py`, CI workflow, compose secrets | as TB-ASSESS-01 | T-212b, T-212c | M | OPS-057 |
| **T-319** | Shared-host isolation drills; platform KEK variant (as TB-ASSESS-01); extends `tests/platform/` of PR #85, does not create it; noisy-neighbour measurement | as TB-ASSESS-01 | as TB-ASSESS-01 | T-633, T-210b, T-213a | M | CR-094 (isolation part), OPS-069 (drill half) |
| **T-635** | Operations documents: support model, supervised remote session, DR with measured RPO and RTO, key inventory and "box lost" list, patch policy, leavers, the missing RUNBOOK pages. The incident plan is T-318 | RUNBOOK section files, `docs/DEVELOPING.md` (new), `docs/plan/sites/` (support sheet ja and zh-TW) | each page names its drill in T-213b; a tabletop record per site | owner answers (TB-DR-09 Q1, Q2, Q5, Q6); T-669 | M | OPS-038, OPS-039, OPS-044, OPS-074, CR-096 (support part) |
| **T-637** | Capacity model from the G1 run: patients per night, disk per patient-year, backup size per tier and site; `gpu_sizing.py` refreshed with B200 and MIG rows; a `doctor` forecast warning | `tools/capacity.py` (new), `tools/gpu_sizing.py`, `tools/trialbox/doctor.py` (one check) | the table for the 50,000-patient run equals the measured run within 15 % | T-004, T-114 | S | OPS-072, LLM-026, LLM-025 (table) |
| **T-638** | Operations Mediums and polish, one PR per sub-topic | as each finding names | as each finding names | T-632, T-634 | M | OPS-016, OPS-033, OPS-060, OPS-076 |
| **T-318** | Privacy documents, incident plan with severity scale, roles, clocks and six cases, one-pager (as TB-ASSESS-01); the legal-basis memo of T-646 is filed here once counsel signs | as TB-ASSESS-01 | as TB-ASSESS-01 | T-116, T-209a, T-646 | M | OPS-041, CR-096 (incident plan), REG-007 (filing), REG-009 (filing) |
| **T-647** | ICH E6(R3) §4 table and three procedures: audit-trail review, downtime, training; loose citations corrected | `docs/validation/e6r3-section4.md` (new), RUNBOOK section files, role guides | each clause names a control and a test; the procedures are in the OQ script | T-211c, T-215 | M | REG-023, REG-005, REG-026 |
| **T-649b** | AI governance note (GMLP, Taiwan AI Basic Act, Japan guideline) and a model change protocol; N-12 reported unadjusted | `docs/validation/{ai-governance,model-change-protocol}.md` (new), `docs/VALIDATION.md` §3 | the protocol names each foreseen change with its test and threshold; T-012a's record cites it | T-012a, PR #75 | M | REG-006, REG-032 |
| **T-649c** | Statement of applicability: ISO 27001 Annex A map (product, vendor, hospital), reused in the IT pack | `docs/validation/soa.csv` (new), `it-security-pack.md` §A.9 | 93 rows, each with "applies" and evidence or a reason | T-210b, T-636 | M | REG-031 |
| **T-315a** | Journeys as the PQ script (part a of T-315), with the re-run list after Golden Week | `tests/e2e/journeys/` (new), CI coverage | as TB-ASSESS-01 | T-116, T-102c, T-115 | M | — |
| **T-315b** | IQ/OQ/PQ protocols (part b) | `docs/validation/protocols/` (new) | as TB-ASSESS-01 | T-315a, T-215 | M | — |
| **T-315c** | Dry-run tooling (part c) | `tools/dryrun.py` (new) | as TB-ASSESS-01 | T-315a | M | — |
| **T-657** | API twin check: every state-changing page route has an `/api/v1` twin or is on a short exemption list; the API checks the session before the body | `tests/console/` (new test), console routes | the route-walk test | T-102c | M | FIT-019, ROLE-019, ROLE-020 |
| **T-658** | Dev loop: `make e2e-simple` passes on a fresh root; missing jars named at start; restore runbook names the refdata pack; random-order nightly job; tools' temp defaults under `TB_SCRATCH` | `Makefile`, `tools/e2e_simple.py`, RUNBOOK restore section file | `make e2e-simple` on a fresh `TB_TEST_ROOT` | none | S | DATA-018, DATA-019 |
| **T-676** | FHIR package set: fetched by the settings version; TWPAS per CGMH's answer; extensions and terminology aligned; a decision superseding D-63 | `tools/fetch_fhir_packages.py`, `tools/fetch_jvm_deps.sh`, `deploy/settings.example.yaml`, one decision file | TWPAS validation tests on the chosen version; settings version = cached version | CGMH's answer | S | DEP-016 |
| **T-677** | Dependency batch 3, patch window before G3: monthly lock refresh; digest refreshes; the next HAPI image; axe-core with its sha256 and the Playwright version in a lock; REDCap version per site; weights verified beyond install (`--verify-all` in `doctor`, before each scheduled run, after an update; the gateway compares `/v1/models` with the pin) | `uv.lock`, `deploy/images.lock`, `tools/trialbox/doctor.py`, `services/gateway/app.py` (start check) | the full suite, e2e, the update drill and the gates; a swapped weight file is refused at start | T-673, T-012b | M | LLM-008, LLM-009, DEP-020 (HAPI part), DEP-025, DEP-026, DEP-028 |
| **T-681** | Privacy-office requests: access, erasure and disclosure requests with legal clocks per country; a disclosure log; a per-patient report of exports | `services/console/privacy.py` (new), flow ledger | a request is logged, the due date shown, the per-patient report lists exports | T-206b, T-682, T-102b | M | ROLE-014 |
| **T-683** | Session and network robustness: an expired session returns to the same patient with the note kept; a network drop keeps the form | `services/console/auth.py` (`next=`), `templates/base.html` script | the two cases as browser tests | T-102c | S | UX-021, UX-022 |
| **T-684** | Clinical UX Mediums: layout (CJK line breaking, `:lang()` font stacks, sticky mark bar, the week page's first screen), registry page words, keyboard path | `console.css`, `templates/week.html`, `_mark.html`, registry templates | screenshot tests ja and zh-TW; no one-character wrapping in pills and buttons | T-116 | M | UX-037, UX-023, UX-025 |
| **T-686** | Roles and admin Mediums and polish | as each finding names | as each finding names | T-102c | M | ROLE-007, ROLE-025 |
| **T-685** | Clinical UX polish (Lows) | as each finding names | as each finding names | T-684 | S | UX-031, UX-030, UX-035, UX-033, UX-024, UX-026, UX-027, UX-038, UX-036, UX-039, UX-041 |

#### 6.2.7 Wave 4: site work, IQ/OQ/PQ and documents after G3

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Closes (finding and CR ids) |
| --- | --- | --- | --- | --- | --- | --- |
| **T-213b** | Docker drills as code (second part of T-213): the first real signed bundle installed from media; every RUNBOOK page as a drill; RPO and RTO measured with 50,000 patients; sign-in with the hospital directory; a Defender run with the exclusion list; a dry vulnerability scan; a physical RTX 5090 record if that tier is sold | `tests/integration/test_acceptance_drills.py` (new), RUNBOOK section files (numbers) | as TB-ASSESS-01; the measured numbers written into the IT pack | T-213a, T-631, T-632; hardware | L | CR-071, OPS-045, OPS-051, OPS-053, OPS-054, OPS-065 |
| **T-317** | Documents made true; role guides in ja and zh-TW; re-review (as TB-ASSESS-01) | as TB-ASSESS-01 | as TB-ASSESS-01 | T-004, T-301b; after G3 | M | — |
| **T-628** | Close-out and decommissioning procedure per site (final freeze of the logs, archive, NIST 800-88 purge with a certificate) | RUNBOOK section file, `docs/plan/sites/` | the procedure is signed by each trial office before G6 | T-635 | S | LIFE-028, OPS-075 |
| **T-649a** | Regulatory views: a consultant engaged in each country, packs sent, routes verified, `regulatory-views.md`; the risk file's wording checked against the second Japanese question | `docs/validation/regulatory-views.md` (new), TB-IU-01 §4 | both requests sent by 2027-01-29 (start in wave 2); a G6 check reads the file | T-116; owner | S | REG-019, REG-016 (opinion half) |

#### 6.2.8 Wave L: later, dated after go-live

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | Closes (finding and CR ids) |
| --- | --- | --- | --- | --- | --- | --- |
| **T-313** | Setpoints and gap finder, flags off (as TB-ASSESS-01). After go-live if the owner agrees (Q-06); if not, wave 3 | as TB-ASSESS-01 | as TB-ASSESS-01 | T-207, T-204, T-208, T-311a | L | CR-068 (setpoints; re-rated by Q-06) |
| **T-316b** | Code-map registry (part b of T-316). After go-live if the owner agrees (Q-06); if not, wave 3 | `tools/codemap_release.py` (new), `services/omop/vocab.py` | as TB-ASSESS-01 | T-105b | M | CR-031 (code-map part; re-rated by Q-06) |
| **T-316c** | De-identified export (part c of T-316). Same condition | `tools/deid_*` | as TB-ASSESS-01 | T-316a, T-204 | M | CR-031 (export part; re-rated by Q-06) |
| **T-306** | HAPI out of the nightly path (as TB-ASSESS-01). The inventory merges it into T-305; §1.5 dates it after go-live (Q-06); if the owner says no it joins T-305b | as TB-ASSESS-01 | as TB-ASSESS-01 | T-202, T-305b | M | — |
| **T-678** | Dependency batch 4: Python 3.14, DuckDB 2.x on a copy of the lake, HL7 validator 7.x with `cql-to-elm` and HAPI, vLLM moves each with requalification | lock files, images | as dependency batch 2 for anything that touches data or models | after 2027-06 | M | DEP-020, DEP-022, DEP-023 |
| **T-679** | Deferred table kept visible: WS-18.1 to WS-18.7; public-corpus runs not done (D-141); accept-without-edit weekly report (D-160); sponsor feasibility questionnaire filler | `docs/plan/backlog.csv` rows | each row has an earliest date | T-665 | S | LIFE-007 |

#### 6.2.9 Items that had no owner in the older sources, now attached

| Source | Item | Now in |
| --- | --- | --- |
| Register §6 Medium list | S-12 feasibility sweep hard-excludes | T-216 (and tell FG D-275) |
| | S-13 the S4 verifier cannot disagree | FG D-276 (tell) |
| | S-14 no snapshot-age check | T-305a |
| | S-15 lake zone from `TB_TZ`; DI-14 other time-zone slips | T-656 (after PR #86) |
| | S-16 SAE with clocks 0 is quiet | T-602 |
| | S-17 Observation dated by period only | T-616 |
| | PV-12 N1/N2 patient rows tagged aggregate; PV-16 workbooks outside the flow ledger | T-682 |
| | PV-17 pseudonyms in URLs | T-686 |
| | PV-10, PV-11, PV-18 scrubber, mail bodies, link mode | T-212d, T-212a |
| | PV-13 trace store keeps note text | T-605 |
| | PV-14 office counts ignore study scope | T-304a |
| | SEC-8 | T-211a · SEC-11 mail auth fails open: T-212a · SEC-14 REDCap client accepts `http://`: T-115 · SEC-15 self-entered PI: T-102b · SEC-16 shared token forges `reauth-`: T-205 · SEC-17 assertion replay: T-109b |
| | DI-10, DI-11, DI-12 restore audit, one point in time, settings in the backup | T-117b · DI-13 source delete: T-206b |
| | CR-116, CR-117, CR-118 | FG D-279; CR-118's Low list: T-109b · CR-119: T-206a · CR-120: T-207 |
| Status file §2.5 | #71 remaining review fixes | T-655 |
| | Gemma 4 31B in the judge bake-off | T-674 (build and run queued in T-664) |
| | P0 baseline data | PR #76, then T-618 |
| TB-DR-11 §F.2 | WS-02.5 hosted-demo hardening | T-501, T-502, T-505a, T-505b, T-509 · WS-08.8 reference data: T-618 · WS-15.*: owner and counsel (T-646, T-649a) · WS-16.2 baseline: owner, due 11-30, tracked in T-663 · WS-17.3 training: T-317, T-647 |
| TB-DR-11 §F.3 | The five follow-up PRs with no card | #64, #66, #68, #76, #80 keep their PR numbers as ids; order in §6.4; their leftovers: T-012a (#64), T-209c and T-320b (#66), T-632 and T-212b (#68), T-618 and T-610 (#76), T-107 and T-307 (#80) |
| `DECISIONS.md` "Not done" blocks (TB-DR-11 §F.4) | D-111 | T-600 |
| | D-112, D-124 a physical RTX 5090 record | T-213b |
| | D-113, D-122, D-130, D-142 CQL path and the comparator | T-619a |
| | D-114 mTLS on the internal network | T-212d (position recorded) |
| | D-122, D-137, D-142 Japan completeness | T-615a, T-610; real masters are the owner's (CR-015) |
| | D-129, D-134 calculated fields, schedule versions, erase hidden values | T-302b, T-621 |
| | D-135 Tesseract never run for real | T-004 |
| | D-138 secrets in `deploy/.env`; installer default | T-212d, T-632 |
| | D-140, D-172 | T-618 |
| | D-141 public corpora not run; D-160 accept-without-edit report | T-679 (wave L) |
| | D-142 `doctor` and the judge refusal; `X-TB-Step` | T-601, T-604 |
| | D-143 SAE clock per study; "approached" in two words; rate limits in memory | T-602, T-506, T-103 |
| | D-146 mail limit per sender; investigator cannot refresh feasibility | T-108c, T-512 |
| | D-149 `unit_defaults` | T-613b |
| | D-150 weight pins on the VM, serving-record capture | T-119 |
| | D-186 | T-110b · D-188: T-117b · D-190 eGFR under 18: T-207 · D-192: T-109b · D-201 file leftovers: T-658 · D-203 scan limits: T-011 · D-205 50k goldens: T-004 |
| TB-PLAN-05 WS-18 | WS-18.1 to WS-18.7 (deferred by design) | T-679 keeps the table visible; no build card |

### 6.3 Coverage check

Every open Blocker, Critical and High row of the register TB-REG-01 (88 open of 115; the 27 fixed rows CR-039, CR-044, CR-064, CR-065, CR-072 to CR-076 and CR-097 to CR-114 are left out) and every Blocker, Critical and High finding of the deep review (prefixes FIT, UX, ROLE, LLM, STD, REG, DATA, LIFE, DEP, OPS, PLAN; ENG is missing, see §6.2.4). "Closed by" names, in this order: a fix group or open PR, an owner action, then the cards. The table is generated from the "Closes" column of §6.2, so a row here and a card there cannot disagree.

Rows: 266 (Blocker 35, Critical 22, High 209).

| Source id | Severity | Closed by |
| --- | --- | --- |
| CR-001 | Blocker | FG D-275; PR #70 (T-118); T-613b |
| CR-002 | Critical | FG D-276; T-601 |
| CR-003 | Critical | FG D-276 |
| CR-004 | High | FG D-276; T-603 |
| CR-005 | High | FG D-275 |
| CR-006 | High | FG D-275 |
| CR-007 | High | FG D-275; T-216 |
| CR-008 | High | FG D-277 |
| CR-009 | High | FG D-277 |
| CR-010 | High | FG D-277 |
| CR-011 | High | FG D-277; T-602 |
| CR-012 | High | T-602 |
| CR-013 | High | T-216 |
| CR-014 | High | T-310a |
| CR-015 | High | owner: obtain a vendor SS-MIX2 sample (survey ①, by 11-20); T-615a, T-011 |
| CR-016 | Blocker | FG D-272; owner decision OD-7 for the old chain |
| CR-017 | Critical | FG D-273; T-103 |
| CR-018 | High | FG D-273; T-102c |
| CR-019 | High | FG D-273; T-206a |
| CR-020 | High | FG D-273 |
| CR-021 | High | FG D-273 |
| CR-022 | High | FG D-273 |
| CR-023 | High | FG D-280; T-102b |
| CR-024 | Blocker | T-102a, T-102b, T-102c, T-103 |
| CR-025 | High | owner decision OD-1, then T-212a |
| CR-026 | High | FG D-278; T-206a |
| CR-027 | Critical | T-206a, T-206b |
| CR-028 | High | T-600 |
| CR-029 | High | FG D-280; T-309 |
| CR-030 | High | T-314 |
| CR-031 | High | T-316a, T-316b, T-316c |
| CR-032 | Blocker | owner: no real data before the DPA; T-005 (merged); T-502 |
| CR-033 | Blocker | FG D-279; T-505a, T-109b |
| CR-034 | Blocker | FG D-279; T-205 |
| CR-035 | High | FG D-281; T-205 |
| CR-036 | High | FG D-281; T-115 |
| CR-037 | High | T-212c |
| CR-038 | High | FG D-278 |
| CR-040 | High | T-212b |
| CR-041 | Blocker | T-210a, T-210b, T-210c |
| CR-042 | High | T-211a, T-211b |
| CR-043 | High | T-108b |
| CR-045 | Critical | PR #78; owner OD-4; T-672, T-673 |
| CR-046 | High | T-110b |
| CR-047 | High | PR #83 (T-111); T-111b |
| CR-048 | High | T-119 |
| CR-049 | Critical | PR #86 (FG D-270) |
| CR-050 | High | PR #86 (FG D-270) |
| CR-051 | High | FG D-271; T-655 |
| CR-052 | High | FG D-271 |
| CR-053 | High | FG D-271 |
| CR-054 | High | FG D-272; T-211a |
| CR-055 | High | FG D-273 |
| CR-056 | High | FG D-274 |
| CR-057 | High | FG D-274 |
| CR-058 | High | T-117b |
| CR-059 | High | T-104 (own PR, §6.4) |
| CR-060 | Blocker | T-106, T-202 |
| CR-061 | High | PR #82 (T-105); T-106, T-105b, T-201, T-305b |
| CR-062 | Blocker | T-115, T-302b |
| CR-063 | High | T-305a |
| CR-066 | High | T-207 |
| CR-067 | High | T-112a, T-112b, T-107 |
| CR-068 | High | T-203a, T-203b, T-203c, T-204, T-311a, T-312, T-313 |
| CR-069 | Blocker | T-004 |
| CR-070 | High | closed as moot (quota refused); plan on one GPU; T-664 |
| CR-071 | High | owner: hardware for the drills; T-213a, T-213b |
| CR-077 | High | T-002 |
| CR-078 | High | T-506, T-116 |
| CR-079 | High | PR #75 (T-101) for prompts; T-012a, T-012b |
| CR-080 | Blocker | owner OD-9: name the second reader and turn on branch protection; T-002 |
| CR-081 | High | T-110b |
| CR-082 | High | T-108a |
| CR-083 | High | T-104 (own PR, §6.4) |
| CR-084 | Blocker | PR #85 (T-113); T-113b |
| CR-085 | High | T-108c |
| CR-086 | High | T-301a |
| CR-087 | High | owner OD-2 signs; T-010 |
| CR-088 | Blocker | owner: site surveys signed, feed owner named (G2b); T-663, T-011 |
| CR-089 | Blocker | owner: Japan box decision and order by 12-18 (Q-05); T-663, T-114, T-214 |
| CR-090 | Blocker | owner: first IT meetings requested by 11-13; T-663, T-636 |
| CR-091 | Blocker | owner: contract templates requested by 11-13; counsel engaged by 11-27; T-663 |
| CR-092 | Blocker | owner: HIS work request and a named export owner by 11-13 (Q-11); T-663 |
| CR-093 | Blocker | owner: re-read the row; dates are now 04-28 and 05-13 (§2), fallback dates Q-09 |
| CR-094 | High | owner: pentest firm booked by 12-18; accuracy on real records at PQ; T-319 |
| CR-095 | Blocker | owner: re-read of the revised protocol; T-010 |
| CR-096 | High | owner: counsel view and licences; T-215, T-635, T-318 |
| CR-115 | High | FG D-275 |
| FIT-001 | High | T-666 |
| FIT-002 | High | T-102b, T-303 |
| FIT-003 | High | T-512 |
| FIT-022 | High | FG D-280; T-102b |
| FIT-004 | High | T-203a, T-203c, T-204, T-311a |
| FIT-017 | High | T-112a, T-112b, T-304a, T-304b |
| FIT-018 | High | T-201 |
| FIT-012 | High | T-626 |
| FIT-009 | High | T-302a |
| FIT-007 | High | T-310a |
| FIT-005 | Critical | owner: supplement to the IRBs if the comparison finds differences (by 11-20); T-641 |
| FIT-006 | High | T-506, T-116 |
| FIT-016 | High | T-627 |
| FIT-023 | High | FG D-273, FG D-278; T-206a |
| FIT-024 | High | T-216, T-301a |
| FIT-025 | High | FG D-277; T-602 |
| UX-001 | Blocker | T-501 |
| UX-002 | Blocker | T-505b, T-509 |
| UX-003 | High | PR #86; T-513 |
| UX-004 | High | T-503 |
| UX-006 | Blocker | T-510 |
| UX-007 | High | FG D-276 (stub personas); GP-2 with real models; T-515 |
| UX-040 | High | T-505b |
| UX-008 | High | T-514 |
| UX-009 | High | T-507 |
| UX-011 | High | T-516 |
| ROLE-001 | Blocker | T-505a |
| ROLE-002 | Blocker | T-501 |
| ROLE-003 | Critical | T-501 |
| ROLE-004 | High | FG D-279 (forced change); T-505b |
| ROLE-005 | High | T-102b |
| ROLE-008 | High | T-505b, T-102b |
| ROLE-009 | High | T-102a, T-102b |
| ROLE-010 | High | FG D-280, FG D-273; in the PoC no admin account is issued; T-102b, T-309 |
| ROLE-011 | High | T-102b |
| ROLE-012 | High | T-303 |
| ROLE-013 | High | T-211c |
| ROLE-014 | High | T-681 |
| LLM-001 | Blocker | T-004 |
| LLM-002 | Critical | T-601 |
| LLM-003 | High | T-601 |
| LLM-004 | Critical | FG D-276; T-601 |
| LLM-005 | High | FG D-276; T-603 |
| LLM-007 | High | T-012b |
| LLM-011 | High | PR #85 (part); T-113b, T-114 |
| LLM-013 | High | T-607 |
| LLM-015 | High | T-603 |
| LLM-016 | High | FG D-276; T-603 |
| LLM-025 | High | T-004, T-114, T-637 |
| LLM-027 | High | PR #85; owner: ask CGMH for two MIG instances; T-113b |
| LLM-029 | High | T-012a, T-012b |
| LLM-034 | High | T-606, T-208 |
| LLM-036 | High | T-604 |
| LLM-039 | High | PR #68; T-212b |
| LLM-040 | High | T-605 |
| LLM-044 | Critical | FG D-276; T-507 |
| LLM-045 | High | T-507 |
| STD-001 | Blocker | PR #70 (T-118); T-613a, T-613b |
| STD-010 | High | PR #82 (part); T-614 |
| STD-013 | High | T-615a, T-616 |
| STD-020 | High | T-615a |
| STD-021 | High | FG D-275 (status half); T-615a |
| STD-022 | High | T-613b |
| STD-030 | High | T-105b |
| STD-040 | High | T-613a |
| STD-042 | High | owner: a real YJ master from the site (CR-015); T-610 |
| STD-060 | High | T-115 |
| REG-001 | High | T-642 |
| REG-002 | High | T-642 |
| REG-007 | Critical | counsel signs (owner engages by 11-27); T-646, T-318 |
| REG-008 | High | T-646 |
| REG-009 | High | T-646, T-318 |
| REG-010 | Critical | owner: supplement, as FIT-005; T-641 |
| REG-014 | Critical | T-502 |
| REG-015 | High | T-502, T-508 |
| REG-016 | High | T-314, T-649a |
| REG-021 | High | T-205, T-648 |
| REG-022 | High | T-643 |
| REG-023 | High | T-647 |
| REG-024 | High | T-648 |
| REG-025 | High | T-205 |
| REG-027 | High | T-215 |
| REG-028 | High | T-644 |
| DATA-001 | Critical | T-611 |
| DATA-002 | High | T-659, T-659b |
| DATA-003 | High | PR #70 (part); T-615b |
| DATA-004 | High | T-612 |
| DATA-005 | High | PR #82 (chartno); T-105b |
| DATA-006 | High | T-316a |
| DATA-020 | High | T-600 |
| DATA-021 | High | FG D-272; T-211a |
| DATA-022 | Critical | FG D-273 (earlier paths); T-206a, T-206b |
| DATA-024 | High | T-117b |
| DATA-025 | High | T-102b |
| LIFE-001 | Blocker | T-503 |
| LIFE-002 | High | T-504 |
| LIFE-005 | High | T-501 |
| LIFE-008 | High | T-622 |
| LIFE-009 | High | T-621 |
| LIFE-010 | High | T-504, T-621 |
| LIFE-013 | High | T-622 |
| LIFE-014 | High | T-624 |
| LIFE-015 | High | T-623 |
| LIFE-018 | High | T-302a |
| LIFE-019 | High | T-516, T-302a |
| LIFE-021 | High | FG D-281; T-115, T-302b |
| LIFE-022 | High | T-602 |
| LIFE-023 | High | T-602 |
| LIFE-026 | High | T-303 |
| LIFE-027 | High | T-305c |
| LIFE-029 | High | T-625 |
| DEP-001 | Critical | PR #78; T-672 |
| DEP-003 | High | T-673 |
| DEP-004 | High | T-673 |
| DEP-005 | High | T-673 |
| DEP-007 | High | T-674 |
| DEP-008 | High | T-674 |
| DEP-012 | High | T-675 |
| DEP-006 | High | T-671 |
| OPS-001 | Blocker | T-501 |
| OPS-002 | High | T-505b |
| OPS-003 | High | T-505a, T-509 |
| OPS-004 | High | T-502 |
| OPS-010 | High | T-631 |
| OPS-011 | High | T-632 |
| OPS-013 | High | T-632 |
| OPS-018 | High | PR #78 (part); T-672, T-110b |
| OPS-020 | High | PR #83; T-111b, T-631 |
| OPS-024 | High | T-634 |
| OPS-027 | High | T-209a |
| OPS-028 | High | T-117b |
| OPS-038 | High | owner: support model and people; T-635 |
| OPS-039 | High | owner: remote-access fallback agreed with each hospital; T-635 |
| OPS-040 | High | T-641, T-636 |
| OPS-041 | High | T-318 |
| OPS-042 | High | T-609 |
| OPS-043 | High | T-634 |
| OPS-045 | High | FG D-274 (restore defects); T-213b |
| OPS-049 | High | T-108b |
| OPS-050 | Blocker | PR #85; T-633 |
| OPS-051 | High | owner: DNS name, certificate and directory lead time asked in the first IT meeting; T-213a, T-213b |
| OPS-061 | Blocker | T-210a |
| OPS-062 | High | owner: decide the host system; T-636, T-634 |
| OPS-063 | High | owner: buy or drop the Spark by 11-20; T-214 |
| OPS-066 | High | owner: ask CGMH the platform kind in the first IT meeting; T-633 |
| OPS-067 | High | PR #85; T-113b |
| OPS-068 | High | T-633 |
| OPS-069 | High | owner: CGMH answers who administers the shared storage; T-633, T-319 |
| PLAN-001 | Blocker | owner: start the export mechanism under the existing approval (Q-11); TB-PLAN-06 §3.1 chain CGMH-A′; T-663 |
| PLAN-002 | Blocker | owner: contract requests this week (§3.2); T-663 |
| PLAN-006 | Critical | owner: decide and order on 12-18 (Q-05); T-667 |
| PLAN-007 | Critical | owner: first IT meetings by 11-13 (§3.2); T-663 |
| PLAN-008 | High | owner: supplement before the first meeting; T-641 |
| PLAN-009 | High | TB-PLAN-06 §2.2 and RSK-59; owner Q-10 |
| PLAN-010 | High | TB-PLAN-06 §2.2 (real float shown); owner Q-09 |
| PLAN-011 | High | TB-PLAN-06 §2.2 (working days); T-662 |
| PLAN-012 | High | TB-PLAN-06 §2.2, RSK-64; owner confirms 04-30; T-662 |
| PLAN-014 | High | TB-PLAN-06 §2.2 (05-19 / 05-27); owner Q-09 |
| PLAN-004 | Blocker | TB-PLAN-06 §1.4, RSK-51; T-664, T-004 |
| PLAN-017 | Critical | T-114 |
| PLAN-018 | High | TB-PLAN-06 §1.4 (text replaced) |
| PLAN-005 | Blocker | TB-PLAN-06 §2.1 (gates GP-0, GP-1, GP); `27-poc-plan.md`; T-508 |
| PLAN-019 | Critical | T-502 |
| PLAN-020 | High | T-506 |
| PLAN-023 | High | owner: G0 evidence; T-661, T-663 |
| PLAN-024 | High | owner: name the safety-core engineer (Q-08); G1 signer in §2.1; T-002 |
| PLAN-027 | High | T-661, T-215 |
| PLAN-030 | High | TB-PLAN-06 §4 (capacity by verified merges); T-665 |
| PLAN-031 | Critical | owner: operations person from December (Q-08); TB-PLAN-06 §4 |
| PLAN-032 | High | TB-PLAN-06 §4 rule (review waves only at gates); T-665 |
| PLAN-033 | High | TB-PLAN-06 §6.4 (merge order), RSK-62; T-002, T-669 |
| PLAN-003 | Blocker | owner: COI disclosure by 11-13; deputies (Q-08); RSK-53, RSK-54 |
| PLAN-036 | High | owner: ask in the survey; RSK-60; T-674 |
| PLAN-037 | High | owner: buy in Japan from a domestic vendor; RSK-61; T-667 |
| PLAN-038 | High | TB-PLAN-06 §1.2 |
| PLAN-039 | High | TB-PLAN-06 §1.5; owner Q-06 |
| PLAN-040 | High | TB-PLAN-06 §2.1 (register condition in every gate record); T-661, T-665 |
| PLAN-046 | High | T-666 |

**Not covered by any card, fix group or open PR.** No engineering row is uncovered. The rows below have no card because the action is the owner's alone, or because this plan's own text closes them:

| Source id | Severity | Owner action or plan text |
| --- | --- | --- |
| CR-093 | Blocker | owner: re-read the row; dates are now 04-28 and 05-13 (§2), fallback dates Q-09 |
| PLAN-009 | High | TB-PLAN-06 §2.2 and RSK-59; owner Q-10 |
| PLAN-010 | High | TB-PLAN-06 §2.2 (real float shown); owner Q-09 |
| PLAN-014 | High | TB-PLAN-06 §2.2 (05-19 / 05-27); owner Q-09 |
| PLAN-018 | High | TB-PLAN-06 §1.4 (text replaced) |
| PLAN-031 | Critical | owner: operations person from December (Q-08); TB-PLAN-06 §4 |
| PLAN-003 | Blocker | owner: COI disclosure by 11-13; deputies (Q-08); RSK-53, RSK-54 |
| PLAN-038 | High | TB-PLAN-06 §1.2 |
| PLAN-039 | High | TB-PLAN-06 §1.5; owner Q-06 |

Rows with an owner action **and** a card that tracks or supports it (the card cannot close the row alone): CR-015, CR-032, CR-080, CR-087, CR-088, CR-089, CR-090, CR-091, CR-092, CR-094, CR-095, CR-096; FIT-005, REG-007, REG-010; OPS-038, OPS-039, OPS-051, OPS-062, OPS-063, OPS-066, OPS-069; LLM-027; STD-042; PLAN-001, PLAN-002, PLAN-006, PLAN-007, PLAN-008, PLAN-023, PLAN-024, PLAN-036, PLAN-037. Each is a row of the owner-chain tracker (T-663).

Three rows depend on owner question Q-06: CR-068 (setpoints part, T-313) and CR-031 (code-map and export parts, T-316b, T-316c). If the owner dates them after go-live, the gate record of G3 must carry the owner's dated decision that re-rates those parts; otherwise the three cards return to wave 3.

Medium and Low findings: every one of the deep review is in the "Closes" column of a card, or in a per-area card (T-608, T-619c, T-620, T-638, T-684, T-685, T-686), or closed by this plan's text (FIT-021, PLAN-015, PLAN-045, PLAN-048). The generator found none unattached.

### 6.4 The open PR queue: merge order

From TB-DR-10 §7.3 and TB-DR-11 §D. Fourteen PRs are open; nine conflict with master today. One full test run and one adversarial read per merge.

| Step | PR | Card | What it needs first | Why here |
| --- | --- | --- | --- | --- |
| 1 | **#86** | FG D-270 (site-local "today") | rebase (49 behind); no conflict | PoC prerequisite; closes CR-049, CR-050 |
| 1 | **#64** | judge bake-off harness | nothing (rebased, ready) | T-012a calls it |
| 1 | **#70** | T-118 (unit of a lab row, encoding detector, dates) | rebase (96 behind); no conflict; **goldens regenerated once after it** | PoC prerequisite; STD-001 |
| 1 | **#73** | register TB-REG-01 (one document) | nothing | documents only |
| 1 | **#78** | T-672 (jars) | it is "WIP, untested": T-672 finishes it; merge when CQL and validator tests pass | PoC prerequisite (the demo image carries the jars) |
| 2 | — | **T-002** | step 1 merged; its tail entries become files | removes the `DECISIONS.md` conflict for #66, #68, #76, #80 and fixes the rule for generated `models.py` |
| 3 | — | **T-104 as its own PR**, cut from the PR #83 version (commits `ffe1a8c6` and `a5296bc6`), decision file D-204 | T-002 | #82 and #83 carry two versions of it and share 14 files |
| 4 | **#82** | T-105 (vocabulary schema, chart-number normaliser) | rebase on T-104; drop its T-104 commit and its D-204 file; decision renumbered D-205 → **D-301**; regenerate models | touches `criteria_compiler` (safety core): the longer review |
| 5 | **#83** | T-111 (update safety) | rebase on T-104; regenerate models | closes CR-047 |
| 6 | **#85** | T-113 (`shared-quota`, `doctor --platform`) | rebase; RUNBOOK section number from the integrator; its hand-made `deploy/platform/release.json` is marked a stand-in until T-110b | closes CR-084; T-113b and T-114 wait for it |
| 7 | **#68** | box-install rehearsal, keyed model servers | rebase on #83 and #85 (shares `doctor.py`, `__main__.py`, `egress.py`, the update tools) | T-632 and T-212b build on it |
| 8 | **#66** | IT admin screens | rebase on #86 and #68 (console files, compose, `__main__.py`); after the PoC freeze if the window is short | T-209c and T-320b are re-cut after it |
| 9 | **#75** | T-101 (prompt registry) | T-601 merged first (`gateway/core.py`); decision renumbered D-201 → **D-300** (28 references); regenerate models | T-606, T-208, T-101b wait for it |
| 10 | **#76** | Japan reference data | resolve the four refdata files against merged #65 | T-610, T-618 wait for it |
| 11 | **#80** | catalogue completion | rebase (49 behind) | T-107, T-307 wait for it |
| — | **#71** | **close** | superseded by merged #77; its six remaining review fixes are ported by T-655 | 39 files, conflicts in 13 or more |

Fix groups D-271 to D-281 merge as they are pushed, each rebased by its own session on the queue's head. Two orders matter: FG D-275 after #70 (one golden regeneration each), and FG D-273, D-279, D-280 before T-102a, T-505a and T-512 (same console and `authz` lines).

### 6.5 The conflict matrix

#### (a) Hot files and the rule for each

| File or directory | Who touches it | Rule |
| --- | --- | --- |
| `docs/DECISIONS.md` | 6 open PRs, every fix group | frozen after T-002; decisions are files (§6.1 rule 3) |
| `docs/RUNBOOK.md`, `DATA.md`, `USER_GUIDE.md`, `SECURITY.md` | 5 PRs, about 25 cards | add a section file; T-669 splits them; section numbers from the integrator |
| `libs/tb_contracts/generated/models.py`, `docs/plan/25-traceability.csv`, `tests/golden/*` | #75, #82, #83; any card adding a schema; #70, FG D-275, T-613a, T-106 for goldens | regenerate, never hand-merge; **one golden regeneration in flight at a time**, called by the integrator |
| `deploy/docker-compose.yml` and overlays | #66, #68, #82, #83; T-104, T-108a, T-212c, T-632, T-673, T-675 | one compose PR in flight; order T-104 → T-673 → T-108a → T-212c → T-632 → T-675; new overlays are new files |
| `deploy/install.sh`, `deploy/check_host.sh`, `deploy/egress.py` | #68, #85; T-108b, T-117b, T-612, T-631, T-632, T-634, T-210a | one at a time; order T-612 (one step) → T-117b → T-108b → T-631 → T-632 → T-634 → T-210a |
| `Makefile`, `.github/workflows/trialbox-ci.yml` | #68, #82, #83; many cards | a card adds one target or one job in its own block; no reordering; rebase before merge |
| `services/console/app.py` | #66, #86; FG D-272, D-273; T-102c, T-103, T-310a, T-502 | a new page is a new router module plus one `include_router` line; edits to existing handlers follow lane order (PB in wave P, 1C, 2C) |
| `services/console/auth.py`, `home.py`, `team.py`, `libs/tb_common/authz.py`, `authz_matrix.yaml` | #66, #86; FG D-273, D-279, D-280; T-505a, T-512, T-516, T-102a to c, T-103 | **the critical-issues session owns them until D-273, D-279 and D-280 are merged**; then one card at a time in this order: T-505a → T-512 → T-516 → T-102a → T-102b → T-309 → T-102c → T-103. Matrix rows are append-only for later cards |
| `services/console/i18n*.py`, `templates/*`, `base.html` | #66, #76; T-506, T-507, T-116 and every page card | a feature brings its own `i18n_<feature>.py` and templates; `base.html` takes one include per card, in lane order; while T-506 (wave P) or T-116 (wave 2) is open, no other card edits an existing i18n file |
| `services/edc/*`, `services/console/edc_pages.py` | #86; FG D-279, D-281; T-115, T-205, T-302a to d | one owner at a time: FG D-281 → T-115 → T-205 → T-302b |
| `services/datacore/lifecycle.py` | FG D-277; T-602, T-302a, T-621, T-623 | lane 2D order: FG D-277 → T-602 → T-302a → T-621 (schedule part) → T-623 |
| `services/criteria_compiler/compile_sql/generator.py` and the other safety-core files | #82; FG D-275; T-207, T-216, T-514, T-614 | safety-core queue (§6.5 c); FG D-275 first |
| `services/gateway/core.py`, `libs/tb_llm/client.py` | #75; T-601, T-603, T-604, T-605, T-212b, T-608 | one at a time, in that order; #75 rebases after T-601 |
| `services/adapter/pipeline.py`, readers, `mapping/engine.py` | #70; FG D-271, D-275; T-611, T-613b, T-615a, T-615b, T-616 | lane 1B then 2B order; FG D-271 before T-611 |
| `services/omop/load.py`, `services/lake/store.py` | FG D-271; T-106, T-106b, T-202, T-201, T-206a, T-305a, T-203b | lane 2B order: T-106 → T-106b → T-202 → T-201 → T-206a; T-305a after T-106b |
| `services/sitesetup/service.py` | #66, #70, #82; FG D-271, D-273; T-202, T-320b | after the queue; then T-202 |
| `libs/tb_common/db.py`, `services/orchestrator/db_pg.py`, `deploy/docker/db-init/*` | #82, #83; FG D-274; T-104, T-212c, T-104b | T-104 first; any card adding a table rebases on it |
| `tools/trialbox/doctor.py`, `tools/trialbox/__main__.py` | #68, #85; about 15 cards | one function or one subcommand per card, registered in a list at the end of the file; no other edits |
| `tools/trialbox/update.py`, `tools/verify_update.py`, `tools/apply_update.sh`, `tools/make_bundle.sh` | #68, #83; FG D-274; T-110b, T-111b, T-631, T-634 | order #83 → #68 → T-110b → T-111b → T-631 → T-634 |
| `tools/trialbox/backup.py`, `backup_schedule.py` | #66; FG D-274; T-117b | FG D-274 → #66 → T-117b |
| `tools/synth/`, `rulesets/` | T-503, T-504, T-613a, T-011, T-507 | a ruleset is its own folder; `tools/synth/` generator: T-503 first, T-504's commit after it, T-011 in wave 2 |
| `tools/demo.py`, `tools/list_demo.py`, `demo/` | T-501, T-505b, T-513, T-504, T-515, T-516 | lane PA order: T-501 → T-505b → T-513; the scenario and seed lines of T-504, T-515, T-516 land after T-505b |
| `docs/plan/sites/it-security-pack.md` | #85; T-636, T-633, T-649c | #85 → T-636 → the others add rows |

#### (b) Card × area matrix for waves P, 1 and 2

Areas: **CA** console app and routers · **TI** console templates and i18n · **AZ** authz · **SC** safety core (matching, criteria engines, guard) · **GW** gateway, `tb_llm`, the stub · **AD** adapter · **OL** omop, lake, datacore · **ED** edc and the lifecycle store · **SS** sitesetup · **OR** orchestrator · **DC** deploy and compose · **DM** `demo/` and the demo tools · **TT** `tools/trialbox` (doctor, update, backup) · **CI** CI and Makefile · **SY** synth generators and rulesets · **DO** the eight documents · **PP** `docs/poc`, `docs/plan`, `docs/validation`.

**W** = the card edits existing shared files of the area. **w** = the card only adds its own new files there, or one named function, one include line, one job (the append rules of (a) apply). Two cards may run at the same time unless both have **W** in one area.

| Card | Lane | CA | TI | AZ | SC | GW | AD | OL | ED | SS | OR | DC | DM | TT | CI | SY | DO | PP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T-002 | PF |  |  |  |  |  |  |  |  |  |  |  |  |  | w |  | **W** | w |
| T-671 | PA |  |  |  |  |  |  |  |  |  |  |  |  |  | w |  |  |  |
| T-672 | PA |  |  |  |  |  |  |  |  |  |  | w |  |  | w |  |  |  |
| T-501 | PA |  |  |  | w |  |  |  |  |  |  |  | **W** |  | w |  |  |  |
| T-505a | PB | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-505b | PA |  |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |
| T-502 | PB | **W** | w |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-506 | PC |  | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-507 | PC |  | **W** |  |  | w |  |  |  |  |  |  |  |  |  | w |  |  |
| T-503 | PD |  |  |  |  | w |  |  |  |  |  |  |  |  |  | **W** |  |  |
| T-504 | PE |  |  |  |  |  |  |  |  |  |  |  | w |  |  | w |  |  |
| T-613a | PD |  |  |  |  |  |  |  |  |  |  |  |  |  | w | **W** |  |  |
| T-510 | PB | w | w |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-512 | PB | **W** |  | **W** |  |  |  |  |  |  | **W** |  |  |  |  |  |  |  |
| T-513 | PA |  |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |
| T-515 | PC |  | **W** |  |  |  |  |  |  |  |  |  | w |  |  |  |  |  |
| T-514 | PC |  | **W** |  | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-516 | PS | **W** | **W** |  |  |  |  |  |  |  |  |  | w |  |  |  |  |  |
| T-511 | PS |  | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-509 | PA |  |  |  |  |  |  |  |  |  |  | **W** | w |  |  |  |  |  |
| T-508 | PF |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-617a | PF | w |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-661 | PF |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-663 | PF |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-664 | PF |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-601 | 1A |  |  |  |  | **W** |  |  |  |  | **W** |  |  | w |  |  |  |  |
| T-613b | 1B |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |  |  |
| T-611 | 1B |  |  |  |  |  | **W** | **W** |  |  |  |  |  |  |  |  |  |  |
| T-612 | 1B |  |  |  |  |  | **W** |  |  |  |  | w |  | w |  |  |  |  |
| T-615b | 1B |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |  |  |
| T-004 | 1F |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-012a | 1A |  |  |  |  | w |  |  |  |  |  |  |  | w |  |  |  |  |
| T-012b | 1A | w |  |  |  | **W** |  |  |  |  |  |  |  |  |  |  |  |  |
| T-674 | 1D |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-673 | 1D |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-113b | 1D |  |  |  |  |  |  |  |  |  |  | **W** |  | **W** |  |  |  |  |
| T-114 | 1F |  |  |  |  |  |  |  |  |  |  |  |  | w |  |  |  | w |
| T-102a | 1C | w |  | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-102b | 1C | **W** | w | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-309 | 1C | w | w | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-119 | 1D |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-641 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-636 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-646 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-642 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w | w |
| T-010 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-662 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-667 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-668 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-669 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **W** |  |
| T-655 | 1B | w |  |  |  |  |  | w |  |  |  |  |  |  |  |  |  |  |
| T-659 | 1E |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-600 | 2A |  |  |  | **W** |  |  | w |  |  |  |  |  |  |  |  |  |  |
| T-603 | 2A |  |  |  | **W** | **W** |  |  |  | w | **W** |  |  |  |  |  |  |  |
| T-604 | 2A |  |  |  |  | **W** |  |  |  |  |  | w |  | w |  |  |  |  |
| T-605 | 2A |  |  |  |  | **W** |  |  |  |  |  | w |  |  |  |  |  |  |
| T-606 | 2A | w |  |  | **W** | w |  |  |  |  |  |  |  |  |  |  |  |  |
| T-208 | 2A |  |  |  |  | w |  |  |  |  |  |  |  |  |  |  |  |  |
| T-101b | 2A | w |  |  | w | w |  |  |  |  |  |  |  |  |  |  |  |  |
| T-607 | 2A |  |  |  |  | w |  |  |  |  |  |  |  | w |  |  |  |  |
| T-207 | 2A |  |  |  | **W** |  |  | w |  |  |  |  |  |  |  |  |  |  |
| T-216 | 2A |  | w |  | **W** |  |  | w |  |  |  |  |  |  |  |  |  |  |
| T-602 | 2D | w | w |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |
| T-106 | 2B |  |  |  |  |  | w | **W** |  |  |  |  |  |  |  |  |  |  |
| T-106b | 2B |  |  |  |  |  | **W** | **W** |  |  |  |  |  |  |  |  |  |  |
| T-105b | 2B |  |  |  |  |  | w | **W** |  |  |  |  |  |  |  |  |  |  |
| T-202 | 2B |  |  |  |  |  |  | **W** |  | **W** |  |  |  |  | w |  |  |  |
| T-201 | 2B | w | w |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |  |
| T-305a | 2B |  |  |  |  |  |  | **W** |  |  | w |  |  |  |  |  |  |  |
| T-112a | 2B |  |  |  |  |  | w | w |  |  |  |  |  |  |  |  |  |  |
| T-614 | 2B |  |  |  | **W** |  | **W** |  |  |  |  |  |  |  |  |  |  |  |
| T-615a | 2B |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |  |  |
| T-616 | 2B |  |  |  |  |  | **W** | **W** |  |  |  |  |  |  |  |  | w |  |
| T-206a | 2B |  |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |  |
| T-102c | 2C | **W** |  | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-103 | 2C | **W** |  |  |  |  |  |  |  |  | w |  |  |  |  |  |  |  |
| T-116 | 2C |  | **W** |  |  |  |  |  |  |  | w |  |  |  |  |  |  |  |
| T-310a | 2C | **W** | **W** |  |  |  |  |  |  |  | w |  |  |  |  |  |  |  |
| T-112b | 2C | w | w |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-682 | 2C | **W** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| T-621 | 2C | **W** | w |  | **W** |  |  |  | w |  |  |  |  |  |  |  |  |  |
| T-622 | 2C | **W** | w |  |  |  |  |  |  |  | w |  |  |  |  |  |  |  |
| T-115 | 2D |  |  |  |  |  |  |  | **W** |  |  |  |  |  | w |  |  |  |
| T-205 | 2D |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |
| T-302a | 2D | w | w |  |  |  |  |  | **W** |  |  |  |  |  |  |  |  |  |
| T-648 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-110b | 2E | w |  |  |  |  |  |  |  |  |  | **W** |  |  | w |  |  |  |
| T-117b | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  | **W** |  |  |  |  |
| T-108a | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-108b | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-111b | 2E |  |  |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |
| T-631 | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  | **W** |  |  |  |  |
| T-632 | 2E |  |  |  |  |  | w |  |  |  |  | **W** |  |  |  |  |  |  |
| T-634 | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  | w |  |
| T-210a | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-210b | 2E |  |  |  |  |  | w |  |  |  |  | w |  | **W** |  |  |  |  |
| T-212a | 2E |  |  |  |  |  |  |  |  |  | w | w |  |  |  |  |  |  |
| T-212b | 2A |  |  |  |  | **W** |  |  |  |  |  | w |  | w |  |  |  |  |
| T-212c | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  |  |  |  |  |  |
| T-633 | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  | **W** |  |  |  | w |
| T-213a | 2E |  |  |  |  |  |  |  |  |  |  | w |  |  |  |  |  |  |
| T-214 | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  | w | w |  |  |  |
| T-104b | 2E |  |  |  |  |  |  |  |  |  |  | **W** | w |  | w |  |  |  |
| T-675 | 2E |  |  |  |  |  |  |  |  |  |  | **W** |  |  | w |  |  |  |
| T-656 | 2E |  |  |  |  |  | w | w |  |  |  |  |  | **W** |  |  |  |  |
| T-215 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  | w |  |  | w |
| T-643 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-644 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-665 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | w |
| T-666 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  | w |  |  | w |
| T-011 | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **W** |  |  |
| T-617b | 2F |  |  |  |  |  |  |  |  |  |  |  |  |  | w |  |  | w |

#### (c) Parallel lanes

A lane is an ordered queue of cards. Cards in different lanes of the same wave never both write (**W**) the same area; the generator checked every pair. Inside a lane the cards run in the order shown. A long lane may be staffed by two sessions at once only on cards whose file lists are disjoint (T-668 checks this) and that do not depend on each other; the lanes marked † need that to meet their gate.

**Wave P**

| Lane | Writes (W) | Cards in order | Sessions |
| --- | --- | --- | --- |
| PA demo build and hosting | DC, DM | T-671 → T-672 → T-501 → T-505b → T-513 → T-509 | 4.5 |
| PB console code and authz | CA, AZ, OR | T-505a → T-502 → T-510 → T-512 | 3.0 |
| PC words, labels, evidence | TI, SC | T-506 → T-507 → T-515 → T-514 | 3.5 |
| PD Japan scenarios and rulesets | SY | T-503 → T-613a | 3.0 |
| PE CGMH scenarios | — | T-504 | 1.0 |
| PF plan, PoC pack, records | DO | T-002 → T-508 → T-617a → T-661 → T-663 → T-664 | 4.0 |

Serial points in wave P:

- **T-002 first.** Nothing else of wave P merges before it, except the step-1 PRs of §6.4.
- **T-516 then T-511 are the serial tail.** They write console code (lane PB's area) and templates (lane PC's area). They start when T-512 (PB) and T-514 (PC) are merged.
- **T-504** writes only its own ruleset folder and scenario script; its `tools/synth/` commit lands after T-503 and its `tools/demo.py` lines after T-505b.
- **T-507** needs the rulesets of T-503 and T-504 for their labels: it starts on the existing rulesets and adds the new labels last.
- **Goldens:** #70, then T-613a, then FG D-275: one regeneration each, never two open.
- T-503 (L) is the longest single card of the wave: it starts on day 1 (Mon 11-16) or the Japan scenario is late.

**Wave 1**

| Lane | Writes (W) | Cards in order | Sessions |
| --- | --- | --- | --- |
| 1A LLM serving and qualification | GW, OR | T-601 → T-012a → T-012b | 3.0 |
| 1B adapter and feed | AD, OL | T-613b → T-611 → T-612 → T-615b → T-655 | 3.5 |
| 1C authz and roles | CA, AZ | T-102a → T-102b → T-309 | 3.0 |
| 1D images, models, platform | DC, TT | T-674 → T-673 → T-113b → T-119 | 4.0 |
| 1E documents and plan | DO | T-641 → T-636 → T-646 → T-642 → T-010 → T-662 → T-667 → T-668 → T-669 → T-659 | 6.5 |
| 1F GPU runs | — | T-004 → T-114 | 2.0 |

Serial points in wave 1:

- **T-601 before T-004.** The G1 run does not count without it (§2.1).
- **Lane 1C starts only when FG D-273 and FG D-280 are merged** (the critical-issues session owns those files until then). If they are not merged by Mon 11-30, T-102a starts on `permit` and the matrix only, in new files.
- **T-612** adds one step to `install.sh` and one `doctor` check: it merges between lane 1D's cards, not during one.
- **T-012b and T-674** both edit `models/registry.yaml`: T-012b first.
- **T-114** is a run on the owner's B200: it needs T-012a, T-113b and T-674 merged and the owner or the named operator present.
- Lane 1E is documents only and can be staffed by two sessions (T-641 and T-646 first; both are on the critical path of the IRB supplement and counsel).

**Wave 2**

| Lane | Writes (W) | Cards in order | Sessions |
| --- | --- | --- | --- |
| 2A† safety core and LLM | SC, GW, OR | T-600 → T-603 → T-604 → T-605 → T-606 → T-208 → T-101b → T-607 → T-207 → T-216 → T-212b | 9.5 |
| 2B† data plane | SC, AD, OL, SS | T-106 → T-106b → T-105b → T-202 → T-201 → T-305a → T-112a → T-614 → T-615a → T-616 → T-206a | 15.5 |
| 2C† console, authz, study model | CA, TI, AZ, SC | T-102c → T-103 → T-116 → T-310a → T-112b → T-682 → T-621 → T-622 | 10.5 |
| 2D EDC and lifecycle store | ED | T-602 → T-115 → T-205 → T-302a | 5.0 |
| 2E† deploy, release, operations | DC, TT | T-110b → T-117b → T-108a → T-108b → T-111b → T-631 → T-632 → T-634 → T-210a → T-210b → T-212a → T-212c → T-633 → T-213a → T-214 → T-104b → T-675 → T-656 | 20.0 |
| 2F validation documents and tools | SY | T-648 → T-215 → T-643 → T-644 → T-665 → T-666 → T-011 → T-617b | 7.5 |

Serial points in wave 2:

- **The safety-core queue.** These cards write safety-core files from three lanes and are reviewed by the one human reviewer, one at a time, in this order: FG D-275 (if still open) → T-600 → T-603 → T-614 → T-606 → T-207 → T-216 → T-621. A lane does not wait idle: it runs its next non-safety-core card while its safety-core card is queued.
- **T-106 → T-106b → T-202 → T-201 → T-206a** is one chain on `omop/load.py`; T-207 waits for T-201; T-616 and T-305a wait for T-106b. Lane 2B is the long pole of the wave (15.5 sessions): T-614, T-615a and T-112a run beside the chain in a second session.
- **Lane 2E** has 20 sessions of work on one area. It runs as two tracks with the file orders of (a): track 1 release and update tools (T-110b → T-111b → T-631 → T-632 → T-634 → T-210a), track 2 compose, backup, keys, platform (T-117b → T-108a → T-108b → T-212c → T-210b → T-633), and the single-file cards (T-212a, T-213a, T-104b, T-675, T-656, T-214) between them.
- **T-116 owns every existing i18n file while it is open** (about three days). Page cards of lanes 2B to 2D bring their own i18n module and are not blocked.
- **T-602 → T-302a → T-621** share `services/datacore/lifecycle.py`.
- **T-212b** is in lane 2A because it writes the gateway; its compose secret is one line under the compose rule.

#### (d) Who owns what while other sessions are alive

| Session | Owns (nobody else writes these until it hands them back) | Hands back when |
| --- | --- | --- |
| **The integrator** | master; the merge order of §6.4; `docs/decisions/REGISTRY.md` (gives numbers); RUNBOOK section numbers; the one full test run; every regeneration of `models.py`, the traceability CSV and the goldens; the status file; T-004 and the GPU ledger (T-664); closing #71 | never; a deputy is named under Q-08 |
| **The critical-issues session** | fix groups D-270 to D-281 and the numbers D-270 to D-289; while a group is open, the files its register rows cite: `services/console/{app,auth,home,team}.py` reveal, delegation and opt-out handlers and `libs/tb_common/authz.py` (D-273, D-280); `services/console/auth.py`, `identity.py` sign-in and step-up (D-279); `services/edc/*`, `edc_pages.py` (D-281); `libs/tb_common/audit.py`, `orchestrator/core.py` audit writes (D-272); `services/adapter/pipeline.py` promote and hold, `sitesetup/service.py`, `tools/omop_parity.py` (D-271); `tools/trialbox/backup*.py`, restore (D-274); the SQL and CQL generators (D-275); `orchestrator/app.py` pair rule, `services/llm_stub` personas (D-276); SAE code in `datacore/lifecycle.py` (D-277); FEAS basis and `datacore_api.py` (D-278) | each group, when its PR is merged. It pushes a branch per group by Mon 11-16 so that others can rebase |
| **Sessions of open PRs** (#64 to #86) | their branch only; they rebase when the integrator calls their step | merge |
| **Wave-P card sessions** | the files of their card, in their lane's order; T-505a and T-512 touch files the critical-issues session owns and need its word first | merge, or the freeze |
| **The safety-core human reviewer** (to be named, OD-9) | approval of any PR that touches the safety-core files, `authz` and the prefill path | — |
| **The owner** | the answers of §10; owner decisions OD-1, OD-2, OD-4, OD-7, OD-9; every row marked "owner" in §6.3; the B200 runs | — |
| **Deep-review sessions** | nothing: they wrote review files only and are closed | closed |

Three collisions to settle at G0, because two sessions believe they hold the same work: (1) T-102: the critical-issues session holds it as "WIP"; this plan gives it the fix-group slice (D-273, D-280) and gives T-102a, b, c to new sessions afterwards. (2) T-115: held as FG D-281; the merged card T-115 starts when D-281 is merged. (3) Forced password change and the sign-in throttle: FG D-279, not T-505a, unless D-279 is late (the rule is in the T-505a row).

### 6.6 Totals

Sessions: S = 0.5, M = 1, L = 2.5. A card is one verified merge, except T-102c (one PR per page group, about four) and the per-area Mediums cards (one PR per sub-topic, about three each).

| Wave | Cards | S | M | L | Sessions | Other merges in the window | Working days | Capacity at 3 to 4 verified merges a day | Reading |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P (to Fri 11-27) | 25 | 12 | 12 | 1 | 20.5 | 13 queue PRs (§6.4) + up to 11 fix groups = 24 | 12 | 36 to 48 | **Over**: 25 + 24 = 49 merges against 36 to 48. See below |
| 1 (to Fri 12-11) | 27 | 10 | 17 | 0 | 22.0 | what slipped from wave P (about 8); T-650 to T-654 when TB-DR-04 arrives | 10 | 30 to 40 | 27 + 8 = 35 or more against 30 to 40: fits only at the upper rate, and only if TB-DR-04 adds few cards |
| 2 (to Fri 01-08) | 60 | 8 | 44 | 8 | 68.0 | T-102c as 4 PRs (+3); PoC findings rated "before G2" | 18 | 54 to 72 | 60 + 3 = 63 or more against 54 to 72: fits at 3.5 a day; 68 sessions of agent work need 6 lanes with two sessions on four of them |
| 3 (to Fri 02-26) | 73 | 8 | 58 | 7 | 79.5 | Mediums cards as several PRs (about +12); PoC findings rated "before G3"; re-merges | 30 | 90 to 120 | 73 + 12 = 85 against 90 to 120: fits, with a margin of about 5 % at 3 a day and 40 % at 4 a day |
| 4 (after G3) | 4 | 2 | 1 | 1 | 4.5 | site work is mostly not merges | — | — | not limited by merges; limited by hardware and the sites |
| L (after go-live) | 6 | 1 | 4 | 1 | 7.0 |  | — | — | 6 cards, 7 sessions leave the go-live path if the owner agrees (Q-06) |

Totals: **195 cards, 201.5 sessions**; to G3 185 cards and 190.0 sessions (the plan's §4 estimate is 170 to 210 sessions against 195 to 290 verified merges). Working days: wave P is the 12 days of §3.1 (from Mon 11-16, less Mon 11-23 in Japan, with the days from G0); wave 1 is Mon 11-30 to Fri 12-11; wave 2 is Mon 12-14 to Fri 01-08 less 12-25 and 01-01; wave 3 is Mon 01-11 to Fri 02-26 less the Lunar New Year week.

**Wave P does not fit as a whole, and the plan should say which merges wait.** The PoC path needs, of the 24 other merges, only #86, #70, #78 (as T-672), T-104 with #82 (for nothing on the PoC path: they can wait), and the fix groups whose files wave-P cards touch (D-273, D-279, D-280; D-275 and D-276 for what the PoC shows). Proposal:

1. Before the freeze: the step-1 PRs, T-002, and FG D-270, D-273, D-275, D-276, D-279, D-280 (11 merges) with the 25 wave-P cards: **36 merges in 12 days**, which is 3 a day.
2. After the freeze, in the week of the dry run and G1 (Mon 11-30 to Fri 12-04), when the PoC build is frozen and merges go to master only: T-104, #82, #83, #85, #68, #66, #75, #76, #80 and FG D-271, D-272, D-274, D-277, D-278, D-281. T-113b and T-114 then wait for #85 until about 12-02, which leaves G1b (12-11) seven working days: tight, and the first thing to watch.
3. First to drop from the freeze if a day is lost, in this order: T-511 (small fixes), T-617a (may land by the dry run), T-515's recorded opinions (keep the label), T-613a for the rulesets the PoC does not show, T-512 if Q-04 is not answered.

Agent sessions are not the limit in any wave. The limits are the integrator's verified merges (3 to 4 a day), the one human reviewer for the safety-core queue (not yet named), and in wave P the two files the critical-issues session owns.


### 6.7 Old suggestions and their new ids

Several review files proposed cards under their own ids, and four files used T-401 to T-410 for different things. The map:

| Review | Old suggestion | New id |
| --- | --- | --- |
| TB-DR-01 | FIT-C1 "Trace that traces" | T-666 (matrix), T-641 (IRB rows) |
| | FIT-C2 "PoC words" | T-506 |
| | FIT-C3 "PI may run" | T-512 |
| | FIT-C4 "Demo delegation seed" | T-505b |
| | FIT-C5 "CRC completeness" | T-626 (FIT-008, FIT-012), T-302a (FIT-009), T-301b (FIT-010) |
| | FIT-C6 "Not-matched gate and weekly sample" | T-310a |
| | FIT-C7 "Study A tooling" | T-627 |
| | FIT-C8 "Outputs for the office" | T-304c (FIT-013, FIT-014), T-302c (FIT-015) |
| | FIT-C9 "API twin check" | T-657 |
| | FIT-C10 "Site realities" | T-629; FIT-U01 in T-512 |
| | FIT-C11 "Tiered export on the readiness page" | T-112b |
| | T-102 (add), T-309 (add), T-101 and T-105 (add) | T-102b and T-303; T-309; T-101b and T-105b |
| TB-DR-02a | T-POC-01 | T-501 |
| | T-POC-02 | T-501, T-505b, T-509 |
| | T-POC-03 | T-510 |
| | T-POC-04 | T-505b, T-503, T-504 |
| | T-POC-05 | T-513 |
| | T-POC-06 | T-515 |
| | T-UX-01 | T-514 |
| | T-UX-02 | T-507 |
| | T-UX-03 | T-506 |
| | T-UX-04 | T-516 |
| | T-UX-05 | T-683 |
| | T-UX-06 | T-602 |
| | T-UX-07 | T-684 |
| | T-UX-08 | T-310a |
| TB-DR-02b | T-109 (add) | T-505a (with FG D-279); leftovers T-109b |
| | T-DEMO-1 | T-501, T-505b |
| | T-102 (add) | T-102a, T-102b, T-102c |
| | T-211 (add) | T-211c |
| | T-PRV-1 | T-681 |
| | T-209 (add) | T-209c |
| | T-317 (add) | T-506 (the PoC pages), T-686 (the rest) |
| TB-DR-03 | T-LLM-01 | T-601 |
| | T-LLM-02 | T-603 |
| | T-012 (add) | T-012a, T-012b |
| | T-113 / T-114 (add) | T-113b, T-114, T-637 (`gpu_sizing`) |
| | T-LLM-03 | T-604 |
| | T-LLM-04 | T-605 |
| | T-LLM-05 | T-507 (demo answers), FG D-276 (personas), T-608 (token counts) |
| | T-LLM-06 | T-606 |
| | T-LLM-07 | T-607 |
| | T-LLM-08 | T-608 |
| | PR #68 follow-up | T-212b |
| TB-DR-05a | T-118 (add) | T-613b |
| | T-STD-01 | T-614 |
| | T-STD-02 | T-615a |
| | T-STD-03 | T-613b |
| | T-STD-04 | T-616 |
| | T-STD-05 | T-619a |
| | T-105 (add) | T-105b |
| | T-106 (add) | T-106b |
| | T-STD-06 | T-613a |
| | T-STD-07 | T-610 |
| | T-STD-08 | T-617a, T-617b |
| | T-STD-09 | T-619b |
| | T-115 (add) | T-115 |
| | T-STD-10 | T-656 |
| | T-STD-11 | T-619a |
| TB-DR-05b | TB6-REG-01 | T-642 |
| | TB6-REG-02 | T-646 (filed through T-318) |
| | TB6-REG-03 | T-641 (commitments), T-643 (record inventory) |
| | TB6-REG-04 | T-647 |
| | TB6-REG-05 | T-648; the meaning text in T-205 |
| | TB6-REG-06 | T-648; OIDC signing in T-205 |
| | TB6-REG-07 | T-649a |
| | TB6-REG-08 | T-502 (demo mode), T-505b (accounts), T-508 (statement), T-509 (purge) |
| | TB6-REG-09 | T-644 |
| | TB6-REG-10 | T-649c |
| | TB6-REG-11 | T-649b |
| | TB6-REG-12 | T-605 |
| | T-116 (add), T-314 (add), T-215 (add) | T-506; T-314; T-215 |
| | T-EDC-04 (as cited in the standards matrix, §8) | this is test TST-EDC-04, not a card: T-205 |
| TB-DR-06 | T-121 | T-611 |
| | T-122 | T-612 (key), T-105b (chart-number spellings) |
| | T-118 (add) | T-615b; DATA-016 to FG D-275 |
| | T-106 (add) | T-106b |
| | T-112 (add) | T-201 (the steward's conflicts page) |
| | T-316 (add) | T-316a |
| | T-206 (add) | T-206a, T-206b |
| | T-123 | T-682; the non-device line on files in T-502 |
| | T-124 | T-659, T-659b |
| | T-001x | T-658 |
| TB-DR-07 | T-401 (scenario J1) | T-503 |
| | T-402 (scenario T2) | T-504 |
| | T-403 (PoC demo pack) | T-503 (J2), T-504 (T1, T3), T-507 (labels), T-505b (`subpi`, delegation logs), T-501 (jars) |
| | T-404 (amendment handling) | T-621; the PoC step in T-504 |
| | T-405 (study state and identifiers) | T-622 |
| | T-406 (pre-screen log) | T-623 |
| | T-302 (add) | T-302a; the PoC part of LIFE-019 in T-516 |
| | T-310 (add) | T-602 |
| | T-407 (screening cadence) | T-624 |
| | T-305 (add) | T-305c |
| | T-408 (cross-study view) | T-625 |
| | T-409 (close-out document) | T-628 (procedure), T-626 (contact limit), T-620 (randomisation fields) |
| TB-DR-08 | T-110 (add) | T-671 |
| | T-DEP-1 | T-672 |
| | T-DEP-2 | T-673 |
| | T-104 (add) | T-104b |
| | T-DEP-3 | T-674 |
| | T-009 (add) | T-607 |
| | T-DEP-4 | T-675 |
| | T-DEP-5 | T-676 |
| | batches 3 and 5 of its §3.1 | T-677, T-678 |
| TB-DR-09 | T-401 (PoC hosting pack) | T-501, T-502, T-505b, T-509 |
| | T-402 (host tree in the signed release) | T-631 |
| | T-403 (site inputs and a finished install) | T-632 |
| | T-108 (add) | T-108a, T-108d, T-117b (alert route), T-656 (host time zone) |
| | T-111 (add) | T-111b |
| | T-209 (add) | T-209a, T-209c |
| | T-404 (operations documents) | T-635; the incident plan in T-318; decommissioning in T-628 |
| | T-405 (platform day-2) | T-633 |
| | T-406 (pack truth table) | T-636 |
| | T-407 (capacity model) | T-637 |
| | T-408 (host baseline) | T-634 |
| | T-213 (add), T-214 (add) | T-213b; T-214 |
| TB-DR-10 | T-401 (plan calendar as data) | T-662 |
| | T-402 (gate records) | T-661 |
| | T-403 (owner-chain tracker) | T-663 |
| | T-404 (backlog file) | T-665 |
| | T-405 (PoC pack) | T-508 |
| | T-406 (hosted demo for the PoC) | T-502, T-505a, T-509 |
| | T-116, T-004, T-114, T-002 (changes) | T-506 and T-116; T-004; T-114; T-002 and T-669 |
| | T-407 (land T-104 alone) | §6.4 step 3 |
| | T-408 (Japan hardware decision note) | T-667 |
| | T-409 (traceability status from evidence) | T-666 |
| | T-410 (card path lint) | T-668 |
| TB-DR-11 | "T-110b", "T-117b" | T-110b, T-117b (kept) |
| | new card for CR-028 | T-600 |
| | CR-037 per-service roles | T-212c |
| TB-DR-04 | (file not present on 2026-11-10) | T-650 to T-654 reserved |


## 7. Test strategy to industrial standard

TB-PLAN-05 §8 stays as the list of test ids (TST-…). This section sets the levels, the tools, the thresholds, the gates and the evidence, in the frame of an IEC 62304-style lifecycle applied as good practice to a product that is not a medical device, and of GAMP 5 for the validation at each site. The measured state of today's suite is in TB-DR-04 (`docs/reviews/2026-11-10-deep-review/04-engineering-quality.md`); §7.8 carries its numbers.

### 7.1 Classification and what it drives

| Part | Class (62304 style, by the harm a failure could contribute to) | Consequence |
| --- | --- | --- |
| **Safety core**: the criteria engines (Python, SQL, CQL), matching and the screening scenario, the pair logic and the gateway's role routing, the guard, the unit and value handling in the adapter, the pseudonym map, the opt-out worker, `authz`, the EDC prefill path, the audit chain | C-like: a failure can wrongly drop or keep a patient, breach privacy or corrupt a research record | detailed design note per unit; unit tests with branch coverage and mutation thresholds; property tests; human approval of every change (CODEOWNERS); the six safety-core files are never changed in the same PR as anything else |
| **Clinical workflow**: console pages, tasks, referral, consent record, SAE register, exports | B-like | unit and integration tests; journey tests per role and language; authorisation matrix test |
| **Platform**: install, update, backup, identity, monitoring | B-like for data loss and privacy; otherwise A-like | drills as tests; IQ scripts |
| **Tools and demo** | A-like | smoke tests; the demo boot test in CI |

### 7.2 Levels

| Level | What | Tools | Where it runs | Evidence |
| --- | --- | --- | --- | --- |
| L0 Static | lint, types, forbidden words, doclint, the contract check, the data-handling scan, secret scan, dependency audit, licence check, Dockerfile lint, shell lint | ruff; a type checker in strict mode on the safety core first, then service by service; `tools/doclint.py`; `tools/data_scan`; pip-audit and OSV; hadolint; shellcheck; a secret scanner; a static security scanner (bandit or semgrep rules for SQL building, subprocess, deserialisation, path handling) | every PR | CI logs; SARIF kept 90 days |
| L1 Unit | pure logic, no network; database-free where possible | pytest with xdist; coverage with branches | every PR | junit XML; the coverage report |
| L1p Property | the safety invariants as properties over generated patients and criteria (§7.4) | hypothesis, with a fixed seed in CI and a nightly run with a fresh seed and more examples | every PR (short), nightly (long) | the falsifying example is committed as a regression test |
| L1m Mutation | the safety core's tests are strong enough to kill a changed rule | a mutation tool (mutmut or cosmic-ray) on the safety-core modules only | nightly; on every PR that touches the safety core | mutation score per module; survivors listed |
| L2 Integration | services against a real Postgres; the adapter on each feed form; the three engines on the same cases; REDCap exchange against recorded real answers, not only the simulator | pytest with the per-branch test root (D-201); recorded cassettes | every PR for the touched service; all on master | junit XML |
| L2d Differential | Python, SQL and CQL engines must agree on every case, including impossible values and unknowns; OMOP path against the lake path | a differential harness over the property generators and the goldens | every PR that touches an engine; nightly | the disagreement list must be empty |
| L3 System | `make e2e-simple`; the goldens; the complete run's stub parts; the testbench; fault injection (a judge down, a table missing, a key missing, a full disk, a pre-empted VM) | the in-process box; the compose test stack; the rehearsal | every PR (`e2e-simple`, goldens); nightly (the rest) | the run report; goldens identical |
| L3j Journeys | the 37 journeys per role and language in a browser, with the authorisation matrix (every route as every role) and the accessibility check | Playwright; axe-core; the role × route matrix of TB-DR-02b kept as a test | nightly; before every release | screenshots; the matrix file; 0 unexpected "allowed" |
| L3s Security | the pentest's automated part; the egress test; the second-factor test on every sign-in route; rate limits; headers; the upload guard | scripted checks; the egress unit | nightly; before every release | the report |
| L3p Performance | the night window at 5k and 50k; page loads p95; restore time (RTO) and backup age (RPO) measured, not claimed | the bench tools; the backup drill | weekly; at each gate | numbers with the host fingerprint |
| L4 Model qualification | the pair through the gateway on the gated sets per language; wrong exclusions; agreement; injection suite; the bake-off against the challenger | `trialbox eval qualify`; the bake-off harness | at G1, G1b, on every model, prompt or serving change, and on the release | the qualification record with builds, hashes and the commit |
| L5 Acceptance | IQ, OQ, PQ per site by an independent executor and witness; the dry run and blind re-entry | the VMP's protocols | G4, G5 | signed records |
| L0f Formative | the clinician PoC (GP, GP-2) | `27-poc-plan.md` | December, January | the GP record. **Not validation evidence.** |

### 7.3 Thresholds

| Measure | Safety core | Clinical workflow | Platform, tools |
| --- | --- | --- | --- |
| Line coverage | ≥ 95 % | ≥ 85 % | ≥ 70 % |
| Branch coverage | ≥ 90 % | ≥ 75 % | — |
| Mutation score | ≥ 85 % at G2, ≥ 90 % at G3; every surviving mutant of an "unknown never excludes" or "proposed never counts" rule is a Blocker | — | — |
| Property tests | every invariant of §7.4 has one; 0 failing | — | — |
| Engine agreement | 100 % on the differential set | — | — |
| Type checking | strict, 0 errors | 0 errors at the agreed level | — |
| Flaky tests | 0 tolerated: a test that fails and passes on re-run is quarantined by an issue within a day and fixed or deleted within a week; it is never skipped to get a green build | the same | the same |
| Skips | every skip names its reason and its issue; the count is printed in CI and may not grow without review | | |
| Authorisation matrix | 0 routes allowed that the matrix file says are denied | | |
| Accessibility | 0 serious or critical axe findings on the journey pages | | |

Thresholds are ratchets: CI fails when a number falls below the last merged value, and the value in the file only goes up.

### 7.4 The safety invariants as properties

| Invariant | Property (for any generated patient, ruleset and feed) |
| --- | --- |
| Unknown never excludes | Removing any fact from a patient never turns a "kept" patient into "not matched". Setting any fact to unknown never produces "not matched" on that criterion. |
| Proposed facts never count | Adding proposed (unconfirmed) facts never changes any criterion result. |
| Units | A value converted to another valid unit gives the same result. A value with a missing or unreadable unit gives unknown, never a comparison. |
| Impossible values | An impossible value (negative age, a date in the future, a lab value outside physical limits) gives unknown in all three engines. |
| Engines agree | The Python, SQL and CQL engines return the same result on the same input. |
| The pair | A result counts as "both agreed" only when two different builds answered. A failed or missing answer of either role gives unknown. |
| Excerpts | Cutting a record to the context budget never turns unknown or kept into "not matched". |
| Opt-out | An opted-out patient never appears in any list, export, vector result or count, whatever the order of ingest and opt-out. |
| Pseudonyms | The same chart number in any accepted spelling gives the same pseudonym; a different site key never passes the ingest. |
| Feed completeness | A night with a missing, empty or collapsed table is never published. |
| Idempotence | Ingesting the same feed twice changes nothing; re-running an older night never moves the served date backwards. |
| Authorisation | No role reads a route its row of the matrix denies; the page and the API give the same answer. |
| Audit | Removing, changing or truncating any audit line fails verification. |
| phi_on_box | No code path sends a patient field to a host outside the box's allow-list; the destination is checked at the gateway, not by a label. |

### 7.5 CI gates and branch protection

Required on every PR to master: `lint`, `types`, `contracts`, `unit` (with the coverage ratchet), `property` (short), `e2e-simple`, `goldens`, `data-scan`, `lock`, `docs`, `shell`, `images`, `demo-boot` (new: the demo starts from a clean clone and answers the sign-in page), `authz-matrix` (new), `decisions` (new: no duplicate decision number), and `mutation` and `differential` when the diff touches the safety core. Nightly on master: the long property run, the journeys, security, fault injection, the complete run's stub parts; a red nightly opens an issue and blocks the next release tag, not the next PR.

Branch protection (the owner sets it): the required checks above; one approving review; a CODEOWNERS file that names the safety-core engineer for the safety-core files, `authz`, the prefill path, the migrations and the CI workflow; no force-push; linear history or merge commits by the integrator only.

### 7.6 Traceability and records

- `25-traceability.csv` is generated with **status and evidence from the tests**, not typed: each URS row lists its test ids, and CI fills "passing", "failing" or "no test". A merged item with no evidence fails the check (card T-666). Today all 273 rows say "planned".
- Each test that verifies a requirement or a risk control carries its id as a marker (`@pytest.mark.tst("TST-…")`); the generator reads the junit XML.
- The SOUP list is the SBOM plus the model weights and images, with the version, the licence and the known-anomaly check (the advisory scan) at each release.
- Problem resolution: one register (TB-REG-01 with the deep review's rows attached); every row has a severity, an owner, a card and a closing test. A gate record states the open counts.
- Change control after G3: only fixes with a linked row; each fix re-runs the levels its diff touches, by rule, and the release record lists them.
- Validation documents live under `docs/validation/` (gate records, protocols, the signed VMP); the folder does not exist today.

### 7.7 Test data

Synthetic and public only. The generators are versioned and seeded; each archetype (gout, RA, oncology, general, and the new Alzheimer's archetype) carries planted truth for positive, negative, negated and absent states in ja, zh-TW and en. Fault feeds (a missing table, a wrong encoding, half-width kana, a unit never seen, duplicated and deleted rows) are fixtures, not ad hoc. Real REDCap answers are recorded once from a hospital's empty test project with synthetic records (owner question in TB-DR-05a) and replayed.

### 7.8 Where the suite stands today

Measured on 2026-11-10 at `ca8f287` (TB-DR-04 §3 and §8; 4 cores, 3 workers).

| Measure | Today | Target (§7.3) |
| --- | --- | --- |
| `make test` from a clean clone | 2,236 passed, 21 failed, 12 skipped in 16.5 minutes. 20 failures are the CQL translator jars missing from the git-ignored cache; with the jars present all 2,261 pass | green from a clean clone (T-653) |
| Coverage of the product code | 90.8 % line, 81.3 % branch | safety core ≥ 95 % / 90 %; ratchet elsewhere |
| `make lint`, `make e2e-simple` (128.6 s, 19 stages), goldens, `lock-check`, `allowlist-check`, the backup drill | pass | stay green |
| Mutation experiment on the safety core (28 hand-made mutants of the two invariants and their neighbours) | 21 killed by the unit tests, 2 only by the goldens, **5 survive every gate** (undated or index-date proposed facts; unreadable rows with no date or no code) | all killed by unit tests (T-650); ≥ 90 % nightly |
| Property-based tests | none | every invariant of §7.4 |
| The CQL/SQL equivalence gate | passes with 0 patients compared; allows 2 % of disagreements that flip eligibility; 22 % unit coverage; HAPI runs in no CI job | T-652; the compose job nightly |
| Traceability | 273 of 273 rows "planned"; no test names a TST or URS id | status from evidence (T-666) |
| Branch protection on master | none: no required checks, no required review | §7.5 (T-007; the owner) |
| Problem-resolution log | GitHub Issues are disabled | T-654 |
| Software safety classification, SOUP list | none | T-654 |

The targeted suites the other reviewers ran passed (166 adapter and OMOP tests, 141 gateway and model tests, the console tests). `make data-scan` is clean on this branch. The details, per-service coverage and the full command table are in TB-DR-04.

### 7.9 Order of work

1. Now (wave P and 1): the demo boot test; the second-factor test on every sign-in route; the authorisation matrix as a test; the property tests for "unknown never excludes", "proposed never counts", units and the pair; the differential harness; the fault-injection tests for the judge down and the missing table.
2. By G2: coverage and mutation ratchets on the safety core; strict types on the safety core; CODEOWNERS and branch protection; traceability from evidence; the journeys nightly.
3. By G3: thresholds met everywhere; the recorded REDCap exchange; performance numbers with fingerprints; the release's qualification record.

## 8. Standards compliance matrix

Sources: `docs/reviews/2026-11-10-deep-review/05a-data-standards.md` (TB-DR-05a, findings STD-nnn) and `05b-regulatory-standards.md` (TB-DR-05b, findings REG-nnn). Dependency and model findings (DEP-nnn, LLM-nnn) are cited only where a claim rests on them. CR-nnn rows are the critical-issues register (PR #73).

How to read the tables.

- **Conformance today**: **full** = meets the standard's rules for the part used, with evidence; **partial** = sound in the main, known gaps; **nominal** = the name or the shape is used, the rules are not met or no artefact would satisfy an auditor; **absent** = not in the code or the documents. Today no row is "full".
- **Version targeted**: what the code or the documents target, then the current version where the reviews looked it up on 2026-11-10. **[W]** = web look-up of that day, mostly secondary sources. **[T]** = training knowledge, not re-checked. "not verified" is kept as the reviews wrote it.
- **Needed by**: PoC (code freeze 2026-11-27) / G2 (2027-01-08) / G3 (2027-02-26) / go-live (CGMH 2027-04-28, Japan 2027-05-13) / later. The reviews gave a date for few rows. Where they gave none, the date here is a proposal by the rule of TB-DR-10: Blocker and Critical code rows by the PoC freeze, High by G2, Medium and Low by G3, site and licence rows by go-live. The lead should confirm each.
- **Owner**: agent (the build), owner (Changfu Kuo, with a consultant where named), site (PI, trial office, IT, privacy office), counsel. TB-DR-05b's "software" is written "agent" here. TB-DR-05a named no owner; the owner there is read from the fix card.
- Neither review was read by a lawyer or a regulatory consultant. This matrix is not legal advice.

### 8.1 Data and interoperability standards

| Standard | Version targeted | Where used (code/doc) | Conformance today | Main gaps (finding ids) | Licence or legal status | Needed by | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HL7 FHIR R4 (base) | 4.0.1 | `services/adapter/mapping/engine.py`, `tw_core/demo_his.yaml` (emit); `services/lake/flatten.py` (read); `adapter/validate/validator.py`; `adapter/sources/fhir_bulk` | partial | Emit is valid on 5,000+ synthetic resources. Read is a narrow subset (STD-014). A death flag without a date is not read (STD-013, High). Offset date-times lose their time (STD-015). Therapy period sits in `dispenseRequest.validityPeriod` (STD-012; related CR-007). Site time zone defaults to `Asia/Taipei` in about 20 places (STD-016). Card T-STD-04, T-STD-10. | CC0, no action | G2 (STD-013); G3 (rest) | agent |
| TW Core IG | 1.0.0 (built 2025-12-10; latest on the registry, checked 2026-11-10) | profile URLs in `tw_core/demo_his.yaml`; `tools/fetch_fhir_packages.py`; HL7 validator when a JRE is present | nominal | Profiles are claimed; TW Core's own code systems are not used; no slice is filled; no offline profile check as Japan has (STD-011). Card T-STD-05. | CC0-1.0 (package.json) | G3 | agent |
| JP Core IG | 1.1.0 (profiles dated 2022-09-26). Current: 1.2.0 (2024-12-30); JP-CLINS uses 1.1.2-clinsa | `jp_core/ssmix2_site.yaml`, `adapter/validate/jpcore.py`, `jp_core_rules.json`, `tools/jpcore_rules.py` | partial (good) | 0 errors on 1,441 synthetic resources; rules reproducible from the pinned package. One version behind (STD-017). ICD-10 system URI wrong for Japan (STD-010). MEDIS 病名 OID unverified. Encounter end and status emitted but not read (STD-018). Card T-STD-05. | No licence field in the package; JAMI terms to confirm | G3 (target version: owner question 4, stay on 1.1.0 for go-live) | agent; site (which version its FHIR plans use) |
| SS-MIX2 standardized storage | 仕様書 v1.2 (v1.2h cited for PRB-13) | `adapter/sources/ssmix2/{hl7,source}.py`, `tools/ssmix2_export.py` | partial | Layout, versions, delete flag and 9 message types are read. Encoding too strict, one bad file stops the night (STD-020, High). OML-11 read too simply: OBX-11, OBX-2, sample time (STD-021, High). No Japanese qualitative result mapped (STD-022, High). PID, PRB, ORC details (STD-023). One bad row stops its table (STD-025). No vendor file ever read (CR-015). Card T-STD-02, T-STD-03. | Specification public (JAHIS / SS-MIX 普及推進コンソーシアム) | G2 (code); go-live (confirmed on the first vendor file, CR-015) | agent; site (vendor file) |
| SS-MIX2 extended storage | same | `source.py:_documents`, `document_text` | partial | Text, HTML, PDF, DOCX; encodings guessed (PR #70 adds one detector). No CDA / 診療情報提供書 parsing; scans have no text. Card T-STD-02. | same | G3 | agent |
| HL7 v2.5 | 2.5 subset | `ssmix2/hl7.py` | partial | First repetition only; no sub-components; OBX-2 and OBX-11 unread; time zone dropped; MSH-18 trusted (STD-020, STD-021, STD-023). Card T-STD-02. | HL7 free | G2 | agent |
| OMOP CDM | 5.4 (DDL of tag v5.4.2, pinned by sha256) | `services/omop/*`, `tools/omop_parity.py`, `lake/source.py` | nominal to partial | DDL exact and pinned. 24 of 39 tables (STD-032). Standard concepts are 0 for conditions, drugs and procedures and cannot be filled by the current rule (STD-030, High). Routing by resource type, not by domain (STD-031). DQD is a subset (STD-032). Field details (STD-033). Not the store of record yet (CR-060). Cards T-105 (add), T-106 (add). | Apache-2.0 (DDL) | G2 (STD-030 and the honest wording); G3 (rest) | agent; owner (wording, question 1) |
| OMOP vocabularies (Athena) | none loaded | `omop/vocab.py` (14 seeded concepts); PR #82 `vocab_load.py` (no Athena) | absent | No load path; no version in `cdm_source`; no vocabulary governance (STD-034). Cards T-105 (add), WS-15.3. | Athena: account and per-vocabulary terms. SNOMED part needs the affiliate licence in Japan and Taiwan. CPT4 needs UMLS. Shipping a bundle inside an update is redistribution and is not cleared (STD-034). | G3 (loader with allow-list); go-live (licence rows cleared) | agent; owner (licences) |
| LOINC | not recorded (2.82 is current, released 2026-02-24) | lab look-ups (`*_to_loinc.csv`), `terminology/src/loinc_tw.csv`, `catalogue/items.csv` (213 codes), `edc/cdash.py`, rulesets | partial | All check digits valid. Sample maps only (14 rows per site template). No release pinned (PR #82 adds a pin). No LOINC notice in the product (STD-044). Card T-STD-08. | Free; notice and version statement required: missing | PoC (notice: a hosted demo is distribution); G3 (release pin) | agent |
| JLAC10 | site's own release | `jp_core/jlac10_to_loinc.csv`, `adapter/licensed.py`, `jpcore.py` shape check | partial | OID correct. 14 sample rows marked `verify`. Full 17-character match only (STD-043). Material table doubtful (STD-024). Card T-STD-07. | JSLM; site loads its own copy | G3 (code); go-live (site master loaded) | agent; site |
| JLAC11 | — | name alias `JC11` only | absent | Shape check is JLAC10's (STD-024). Card T-STD-07. | JSLM | later (decide with the site; survey question) | site; agent |
| NHI lab codes (Taiwan) | NHIA PAS IG 1.3.0 ConceptMap (PR #65, merged) | `libs/tb_common/refdata_tw.py`; site set-up suggestions | partial | Reference map exists; the nightly adapter reads only the site's own CSV (STD-043). Card T-STD-07. | CC0-1.0 (package) | G3 | agent |
| SNOMED CT | none (v1 ships without, Q-22) | system URI declared; 3 files hold a few codes (STD-044) | absent (by decision) | Blocks OMOP standard conditions (STD-030). Remnant codes and descriptions in three files (STD-044). Cards WS-15.3, T-STD-08. | Japan and Taiwan are not members (repo's check, 2026-11-09): affiliate licence through MLDS; inquiry TB-LIC-01 ready, not sent | PoC (remnants removed or register row); later (licence) | owner; agent |
| ICD-10-CM | US FY2026 full list (FY2027 in effect since 2026-10-01) | `terminology/src/icd10cm_2026.csv.gz`, value sets, `jpcore.py`, adapter | partial | No edition handling: Taiwan used the 2014 edition to 2024-12-31 and the 2023 edition after (STD-041). The five shipped rulesets hold short exact code lists from before the family expansion (STD-040, High, on the PoC path). URI and version hygiene (STD-045). Cards T-105 (add), T-STD-06. | Public domain (CMS / NCHS) | PoC (STD-040, card T-STD-06); G3 (editions) | agent; owner (clinical read of the ruleset diffs) |
| ICD-10-PCS | — | TW Core names it; code uses NHI order codes | absent | Procedures are NHI order codes with a TrialBox URI (STD-011). Card T-STD-05. | Public domain | later | agent |
| ICD-10 (WHO 2013, Japan) with MEDIS 標準病名 | site's MEDIS release | `ssmix2/source.py:_icd`, `adapter/licensed.py`, `byomei_to_icd10.csv` | nominal | Handled as ICD-10-CM; WHO-only codes become unknown (STD-010, High). Cards T-105 (add), T-STD-01. | WHO ICD-10: commercial use needs a WHO licence. MEDIS masters: 使用許諾 (WS-15.3), site loads its own. Permission letters not yet asked (STD-044). | G2 (code); go-live (letters) | agent; owner (letters); site |
| ATC | not recorded | `terminology/src/atc.csv`, value sets, `medicationCodeableConcept` | partial | Codes correct in shape; no DDD; no version (STD-045). Card T-STD-08. | WHOCC terms restrict commercial copying and distribution (the reviewer's reading; to confirm with WHOCC). Not cleared (STD-044). | PoC (register row; ask WHOCC now, owner question 5); go-live (answer or codes-only fallback) | owner |
| YJ / HOT (Japan) | site's own release | `ssmix2/source.py:drug_codes`, `jp_core/yj_to_atc.csv`, `licensed.py` | partial | OIDs correct. No YJ to ATC source at scale; most Japanese orders will be unreadable to drug criteria (STD-042, High). Card T-STD-07. | MEDIS HOT master: 使用許諾 | G2 | agent; owner (pharmacist review, source licence) |
| NHI drug codes (Taiwan) | data.gov.tw 23715 (PR #65) | `refdata_tw.py`, `nhi_drug.csv` (synthetic), `nhi-drug` URI | partial | URI is TrialBox's own, not TW Core's `medication-nhi-tw` (STD-011). Card T-STD-05. | Open Government Data License 1.0 | G3 | agent |
| MedDRA, MedDRA/J | — (current release not verified in the review) | nowhere (AE term is free text) | absent | Not stated that coding is the sponsor's task (STD-050). Owner question 3. | MSSO subscription (fee by revenue); MedDRA/J through JMO | G3 (statement in DATA.md and the IRB pack); later (coding, if ever) | owner |
| CTCAE | — (v5.0 of 2017 and v6.0 of 2025 both in use; a study names its version) | nowhere (severity is mild / moderate / severe) | absent | No grade, no version per study (STD-051; on the PoC path for an oncology demo study). Card T-STD-09. | Free (NCI) | G3 (PoC: optional) | agent |
| UCUM | not recorded | `valueQuantity.system/code`, look-up `ucum` column, catalogue units | partial | The adapter never reads the row's own unit: a wrong value leaves with a correct-looking unit (STD-001, Blocker, in PR #70; root cause of CR-001 at the adapter). No validator, no conversion (STD-002). No UCUM notice (STD-044). Cards T-118 (PR #70), T-STD-08. | Free with notice: missing | PoC (STD-001 merge; notice); G3 (conversion table) | agent |
| CDISC ODM-XML | 1.3.2 (v2.0 exists since 2023; REDCap reads 1.3.x) | `services/edc/odm.py`, `services/datacore/export.py` | partial (good) | EDC export validates against the CDISC XSD. Rule-level gaps: `SDSVarName`, units, `Length`, no XSD test in the suite (STD-062). No ODM import. The signature `LegalReason` claims Part 11 (REG-021, see 8.2 and 8.4). Card T-115 (add). | Free to implement | G3 | agent |
| CDISC CDASH | "v2" tags, 13 variables | `services/edc/cdash.py`, `edc/mapping.py` | nominal | Variable names right; no IE, AE, EX, DS; no unit variables (STD-063). Card T-STD-09. | Free | G3 | agent |
| CDISC SDTM, Define-XML, Controlled Terminology | — | nowhere | absent | Not needed by a site tool in v1; state it (STD-063). No card; document only. | Free (CT through NCI EVS) | G3 (the out-of-scope statement in DATA.md) | agent |
| REDCap API | majors 14, 15, 16 (REDCap release lines not verified online, DEP-026) | `services/rc_bridge/*`, `datacore/sources.py`, `rc_sim` | partial | Version call parses plain text as JSON and fails at first contact (STD-060, High). Field types (STD-061). Arms and repeats refused (CR-062). Never run on a real REDCap (CR-062); the "tested on" comment is not true (DEP-026). Card T-115 (add). | REDCap is licensed to non-profit institutions only: the vendor cannot hold one; a site sandbox is needed (owner question 2) | G2 (STD-060); go-live (one recorded run on a real test project) | agent; owner and site (sandbox) |
| REDCap data dictionary, ODM import/export, e-signature, locking | CSV dictionary in and out | `datacore/forms.py` | partial | Dictionary: 7 validation types (STD-061). REDCap's own ODM project file is not read. REDCap has no lock or e-signature API method in core; TrialBox signs on its side. Cards T-115, T-205. | as above | G3 | agent |
| CQL | CQL with FHIR 4.0.1 model, FHIRHelpers 4.0.1, cql-to-elm 5.4.0 | `criteria_compiler/compile_cql`, `rulesets/*/cql` | partial | Generated, never hand-written; ELM committed. Unit and comparator ignored (CR-001, CR-098 note, CR-115). Date taken in the value's own offset (STD-070). Translation and evaluation not run in the review. Card T-STD-11. | Free (HL7); translator Apache-2.0 | G3 | agent |
| FHIR Clinical Reasoning | HAPI CR 8.12 | CQL evaluation path | nominal | Value sets are local JSON with `http://trialbox.local` URLs; no `Library` / `Measure` packaging checked (STD-045). Card T-STD-11. | Free | G3 | agent |

### 8.2 Regulatory, GxP, privacy and quality-system standards

| Standard | Version targeted | Where used (code/doc) | Conformance today | Main gaps (finding ids) | Licence or legal status | Needed by | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ICH E6(R3) §4.3 computerised systems | "E6(R3)" without a date in the repository. Principles and Annex 1 adopted 2025-01-06; consolidated Step 4 text with Annex 2 adopted 2026-06-16 [W secondary; T for 2025] | `docs/plan/25-vmp.md`; plan §7; `docs/SECURITY.md` §7 (one sentence) | partial | No clause-by-clause table; training and failure procedures not written; VMP unsigned (REG-023, REG-027). Edition not named (REG-005). Cards TB6-REG-04, T-215. | Guideline; binding through each country's GCP rules | G3 (table and procedures); go-live (in the OQ script) | agent + owner |
| ICH E6(R3) §4.2 data life cycle | same | audit chain `libs/tb_common/audit.py`; EDC `decision` table; migration protocol (plan WS-12.6) | partial | No audit-trail review procedure; transfer validation not written as such (REG-023, REG-024); CR-042, CR-054, CR-055 open. Cards TB6-REG-04, T-211. | same | G3 | agent |
| ICH E6(R3) essential records (Appendix C) | same | screening log (`services/console/screening_log.py`); ISF bundle planned (T-304) | nominal | No record inventory; no system-of-record decision per record (REG-022). Card TB6-REG-03. | same | G3 (inventory); go-live (signed by each trial office) | owner + site |
| ICH E6(R3) source records, certified copies (§2.12, glossary) | same | EDC citation and quote (`services/edc/store.py`); sponsor acknowledgement switch | partial | The lake is an uncertified copy; the signature meaning says "checked against the cited hospital record" (REG-024). Cards TB6-REG-05, T-303. | same | G3 (meaning text and rule); go-live (sponsor letter) | agent + site; owner (question 4) |
| ICH E6(R3) investigator oversight, delegation (§2.3) | same | delegation-log copy with monthly comparison (D-147); signing needs a log entry (`services/console/edc_pages.py:267`) | partial | The rule is skipped on sibling pages (CR-018). Card T-102. | same | G2 | agent |
| Japan GCP ordinance (GCP省令) and guidance | "J-GCP", no version. Amendment for E6(R3): promulgation planned late September 2026, **application planned April 2027** [W trade press of 2026-08-05; promulgation not confirmed on 2026-11-10] | plan §9.3 "Trial records" row; SAE register D-191 | nominal | No assessment of the amendment; terms (治験参加者) and principles not checked (REG-001). Card TB6-REG-01. | Ministerial ordinance; amendment pending, falls inside the Japan PQ and go-live | go-live (gap note signed and read by the Japan PI before the Japan IQ) | owner + site |
| Taiwan GCP (藥品優良臨床試驗作業指引) | not mentioned in the repository. TFDA pre-announced a revised text for E6(R3) on 2026-02-24; final text not found [W] | — | absent (not mapped) | Not on any watch list (REG-005). Card TB6-REG-01. | Draft; final text not found | G3 (on the watch list) | owner |
| 21 CFR Part 11 | current (unchanged; FDA Q&A guidance of October 2024 [T]) | `services/edc/store.py` (signature row: printed name, role, meaning, time, `content_sha`); re-authentication `edc_pages.py:263`; TST-EDC-04 planned | partial | Manifestation is there. Binding is an unkeyed hash; no record lock; the administrator has seen the password; directory (SSO) accounts cannot sign (CR-034, CR-035, CR-036; REG-025). The export claims Part 11 with no assessment (REG-021). Cards T-115, T-205, TB6-REG-06. | US regulation. TB-DS-16 §6 says it applies "not now" | PoC (neutral `LegalReason` text, REG-021); G3 (assessment with no open row) | agent |
| Japan ER/ES guideline, PMDA EDC management sheet | 薬食発第0401022号, 2005-04-01; current sheet [T] | the same code; `LegalReason` text in `services/edc/odm.py:123` | nominal | No ER/ES assessment; no draft answers to the EDC management sheet (REG-021). Card TB6-REG-06. | MHLW notice | G3 | agent + owner |
| Taiwan electronic records (電子簽章法; EMR 辦法; GCP source rules) | 2024; 2022-07-18 revision [T] | plan §9.3; on-premises design | partial | TrialBox is not an EMR, so most clauses bind the hospital; the contract clauses the EMR 辦法 asks for are not drafted (CR-091). WS-15.2. | In force | go-live | owner + site |
| EU GMP Annex 11 (reference) | 2011; a revision and a new Annex 22 (AI) in draft since 2025 [T] | VMP §7 periodic review; supplier assessments planned | partial (reference only) | No business-continuity text; no audit-trail review (REG-023). Card TB6-REG-04. | Reference only | G3 | agent |
| APPI: 要配慮個人情報, purpose of use, security measures | 2020 and 2021 amendments in force since 2022-04-01; three-year review continues [T] | plan §9.3; `docs/SECURITY.md` §7; legal-basis memo planned (WS-13.6) | nominal | The memo does not exist; the basis is one sentence (REG-007, Critical). Cards T-318, TB6-REG-02. | In force | go-live (memo on file **before any real sample**) | counsel; owner + site |
| APPI: 仮名加工情報 (Art. 41) | in force | plan §9.3 row 1; `docs/SECURITY.md:160` | nominal | The box re-identifies by design, so its data is ordinary personal information; the documents blur this (REG-008). Card TB6-REG-02. | In force | G2 (the sentence in the memo, the 開示書 and the IRB text) | owner; counsel |
| APPI: 委託 and cross-border (Art. 25, 28) | in force | "Aimedics never holds patient data"; no remote access; DPA planned | partial | True for patient data on the box. Not addressed for testers' and users' own personal data in the hosted demo (REG-013). Card TB6-REG-08. | In force | PoC (tester statement, hosting region) | owner |
| MHLW 安全管理ガイドライン | v7.0, notice dated 2026-06-29 (one source says published 07-15) [W secondary] | TOTP (`services/console/totp.py`, D-192); IT pack §A.4, §A.8a | partial | Server-OS second factor and the v7.0 clause map are missing; step-up and password history not built (REG-003; CR-033 open part). Cards T-109, T-210, TB6-REG-01. | Guideline in force | G3 (clause map and controls) | agent |
| MIC/METI provider guideline | v2.0 (March 2025) reported as current [W secondary; not confirmed on a ministry page] | outline in TB-DS-16 §7; WS-15.5 | nominal | The 開示書 and SLA are not written. WS-15.5. | Guideline | go-live | owner |
| Japan ethical guidelines (生命・医学系指針) | Repository cites "(2023)". Amended by notice of 2026-08-27, **applies 2026-12-01** [W, MEXT press page] | `docs/plan/sites/irb-amendment-japan.md`; notice template TB-TMPL-01 §4.1 | partial | Written against the old text; the notice omits the new functions (REG-002, REG-009). Cards TB6-REG-01, TB6-REG-02. | In force; new text from 2026-12-01 | G2 (comparison note before the December committee meeting; notices rewritten); go-live (no notice published before T-206 passes) | owner + site |
| 臨床研究法 | 2024 amendment in force 2025-05-31 [T] | not mapped | absent | Say per study type which regime applies (REG-007). Card TB6-REG-02. | In force | go-live (in the legal-basis memo) | owner + site; counsel |
| Taiwan PDPA (Art. 6, 8, 9, 12, 27) | Repository says "2025 amendment pending". Amendment promulgated 2025-11-11; effective date to be set by the Executive Yuan; no formal PDPC start date found [W secondary] | plan §9.3; CGMH amendment item 4 | nominal | "Care relationship plus IRB approval" is not an Art. 6 item by itself; the amendment status is stale (REG-004, REG-007). Card TB6-REG-02. | In force; amendment promulgated, effective date pending | go-live (memo before any real sample) | counsel; owner + site |
| Taiwan 人體研究法 | in force (Art. 12, Art. 19) [T] | CGMH amendment; `docs/SECURITY.md:172` | partial | Destruction at study end against a whole-hospital repository and a 10-year audit is not reconciled (REG-012). Card TB6-REG-02. | In force | go-live | counsel; owner + site |
| Taiwan EMR and off-site rules; 資安法 | 2022; 2025 | on-premises; IT pack §A.6; survey question 50 | partial | Site answers and contract clauses outstanding (CR-088 to CR-091). Owner actions. | In force | go-live | owner + site |
| Device status, Japan (該当性ガイドライン) | 2021-03-31, partly revised 2023-03-31; no later revision found [W] | `docs/plan/intended-use.md` (TB-IU-01 v0.2); TB-DS-16 | partial | Statement not shown in the product (CR-078). The clinician own-patient view and the verdict words weaken it (REG-016, REG-017). Risk-file wording undercuts it (REG-018). No written view requested; route unverified (REG-019). Two statement texts (REG-020). Cards T-116, T-314, TB6-REG-07. | Guideline; non-device position is the vendor's own, no authority answer yet | PoC (labels and statement, T-116); G2 (requests sent by 2027-01-29 per TB6-REG-07); go-live (reply on file) | agent + owner |
| Device status, Taiwan (醫療器材管理法 Art. 3, 46; 醫用軟體分類分級參考指引) | Act in force 2021-05-01; guideline version not verified (also "not verified" in TB-DS-16 §5.1 since 2026-11-07) [T; search found nothing newer] | the same | partial | Guideline version still unverified; no 屬性 inquiry filed (REG-019). Card TB6-REG-07. | Act in force; inquiry form and fee left to a consultant not yet engaged | G2 (request sent by 2027-01-29); go-live (the amendments promise the view "before formal use") | owner |
| GAMP 5 | "GAMP 5", edition not stated. Second edition, July 2022; ISPE GAMP AI guide 2025 [T] | `docs/plan/25-vmp.md`; plan §7; `25-traceability.csv` | partial | VMP unsigned; 273 of 273 matrix rows "planned"; `docs/validation/` does not exist; model pair put in category 3 or 4 (REG-027). Cards T-215, T-315. | Industry guide (ISPE) | G3 (matrix shows passing rows for every H function); go-live (VMP v1.1 signed before IQ) | agent + owner + site |
| ISO 14971 | "ISO 14971 style". 2019, with ISO/TR 24971:2020 [T] | TB-DS-11 (5×5, matrix, benefit-risk, feedback table); plan §6 (4×4, no matrix) | partial | Two files on two scales that disagree; residuals P1 for controls not built; seven hazards missing; 0 of 50 controls verified (REG-028, REG-018). Cards T-215, TB6-REG-09. | Voluntary for a non-device | G3 | agent + owner |
| IEC 62304 | "62304-light". 2006 + Amd 1:2015 [T] | "62304-light records" for the profile module (WS-12.1; TB-IU-01 C12 "partly") | nominal | No class stated; the five records do not exist; the SBOM is not a SOUP list; model weights are SOUP too (REG-029). Card T-215. | Voluntary for a non-device | G3 | agent |
| IEC 82304-1 | 2016 [T] | not used (two older reviews only) | absent | Decide: adopt as the voluntary frame or record why not (REG-029; owner question 6). Card T-215. | Voluntary | G2 (decision) | owner |
| ISO 13485 | 2016 [T] | commercial review §5.6 | not needed now | Needed only if a module takes a device route; write the trigger (REG-029). No card now. | Voluntary; mandatory on a device route | later | owner |
| ISO/IEC 27001 Annex A; ISO 27799 | 27001 and 27002: 2022 (Amd 1:2024) [T]. 27799: 2016; a 2025 edition expected or published, not confirmed [T, uncertain] | `docs/SECURITY.md`; WS-15.7 "27001 path"; ASVS and CIS planned | nominal | No statement of applicability; no control map; SECURITY.md §1 describes LUKS on Ubuntu while the appliance is Windows with BitLocker "post-platform" (REG-031). Cards T-210, TB6-REG-10. | Voluntary; no certificate sought | G3 (statement of applicability); go-live (reused in the IT pack and the 開示書) | agent + owner |
| GMLP (10 principles) | FDA, Health Canada, MHRA, October 2021; IMDRF N88 final 2025 [T] | gates of `docs/VALIDATION.md` §3; Study A protocol | partial | No mapping; one reference standard rests on label checks by an AI assistant, not a clinician (REG-030, REG-006). Card TB6-REG-11. | Guiding principles | G3 | agent + owner |
| FDA PCCP guidance (as a model for change control) | Final; one source dates the current text 2025-08-18, first final December 2024 [W secondary; T] | qualify command (T-012, not built), prompt registry (PR #75), change class CC1 | partial | No single model change protocol; no rule for telling sites and sponsors (REG-032). Cards T-012, T-101, TB6-REG-11. | US guidance, used as a model only | G2 (protocol exists before the pair is frozen) | agent |
| FDA CDS guidance (reference) | Revised final, January 2026 (sources give 01-06 and 01-29) [W secondary] | not used | reference only | none for the pilot | US guidance | later | owner |
| Japan AI事業者ガイドライン | v1.2, 2026-03-31 (adds AI agents); AI推進法 2025 [W secondary; T] | not addressed | absent | One-page mapping for the hospital (REG-006). Card TB6-REG-11. | Guideline (soft law) | G3 | owner |
| Taiwan AI Basic Act (人工智慧基本法); TFDA AI/ML guidance | Act in force 2026-01-14; risk classification framework by MODA dated 2026-07-07 [W]. TFDA guidance version unverified [T] | not addressed | absent | One-page mapping; ask CGMH whether its AI governance body must review (REG-006). Card TB6-REG-11. | In force | G3 (note); go-live (site answer) | owner + site |
| EU AI Act (reference) | In force 2024-08-01; staged application [T] | note planned in TB-DS-16 | reference only | none for the pilot | EU regulation; not high-risk unless a device or an Annex III use | later | owner |
| Audit trail in code | n/a | `libs/tb_common/audit.py`, `tools/audit_verify.py`; signed heads planned (WS-13.4) | partial | Truncation not detected (by a run; CR-054); unkeyed chain (CR-042); state before audit (CR-055); chart numbers in the log (CR-016); EDC trail tables outside the chain (CR-036); clock only a warning (REG-026). Card T-211. | Required by E6(R3) §4.2, Part 11, ER/ES | G2 | agent |
| Trace store | n/a | `services/tracestore/store.py`, `tracestore.yaml` | partial | 90 days in code against "7 days in PRODUCTION" in the plan and the data-handling rule; no scheduled prune (REG-012; PV-13; LLM-040 rates it High). Card TB6-REG-12. | Promise made in TB-SITE-03 | G2 | agent |
| SAE register (D-191) | n/a | `services/console/saerecord.py` | partial | Design is right (office log stays the record); open defects CR-008 to CR-012. Fix group FG-H / D-277. | GCP SAE reporting rules of each site | G2 | agent |
| Pre-screen and screening log | n/a | `services/console/screening_log.py` | partial | Works; cites the wrong E6(R3) section (REG-005); delegation and opt-out gaps (CR-018, CR-019). Cards T-102, T-206. | E6(R3) Appendix C | G2 | agent |

### 8.3 What must be true at go-live per standard

A short checklist. Each line is a test or a document on file, not a statement of intent. It is read at G4 before real data and again at each site's go-live check.

**Data and interoperability**

- [ ] **Units (UCUM).** PR #70 is merged and extended to the Japan (OBX-6) and SQL templates. A µmol/L creatinine through CSV and through SS-MIX2 gives no value and reason `unit_mismatch` (STD-001, STD-002).
- [ ] **FHIR R4.** The supported-subset table is in DATA.md. `deceasedBoolean` and PID-30 exclude a patient from the base cohort. Offset times are kept. Unread elements are counted in the ingest report (STD-013, STD-014, STD-015).
- [ ] **TW Core.** Either the slices are filled with TW Core's code systems and the HL7 validator gives 0 errors on 200 resources, or `meta.profile` is dropped and the documents say "FHIR R4, TW Core code systems not used" (STD-011).
- [ ] **JP Core.** `jpcore` gives 0 errors with the WHO ICD-10 URI for Japan. The target version (1.1.0 for go-live) is confirmed with the Japan site (STD-010, STD-017).
- [ ] **SS-MIX2 and HL7 v2.5.** The five byte patterns load or are quarantined without stopping the night. A `D` result is a tombstone. Qualitative results in ja, zh-TW and en read as positive, negative or unknown. Each point is confirmed on the first real vendor file and written into the JP mapping README (STD-020 to STD-023, STD-025; CR-015).
- [ ] **OMOP CDM 5.4.** All 39 tables exist. Documents call the store "OMOP CDM 5.4 tables with source concepts; standard concepts for measurements, units and, after T-105, drug ingredients". The DQD report is named "TrialBox DQD subset" and shows the three checks as `fail (accepted): no SNOMED licence`. One run of the real OHDSI DQD is recorded (STD-030, STD-032).
- [ ] **Vocabularies.** The Athena loader refuses vocabularies off the allow-list and records `vocabulary_version`. Each loaded vocabulary has a licence register row (STD-034).
- [ ] **Code lists.** The five shipped rulesets equal the current compiler's output for the pinned release; the PI has read the diffs (STD-040). The Taiwan edition map is applied by record date (STD-041). Japan: at least 95 % of the last year's order lines resolve to an ingredient on the site's own drug master (STD-042). Site masters (MEDIS, JLAC10, HOT) are loaded by the site with version and hash.
- [ ] **Licences and notices.** NOTICE and the About page list every source with version and obligation (LOINC, UCUM first). No SNOMED description ships without the affiliate licence. The WHOCC answer on ATC is on file, or names are removed (STD-044). See §9.4.
- [ ] **CDISC ODM and CDASH.** Both exporters pass `xmllint` against the ODM 1.3.2 XSD in CI. DATA.md states that SDTM, Define-XML and Controlled Terminology are out of scope (STD-062, STD-063).
- [ ] **REDCap.** The version call accepts plain text. The ICD-04 list has run once against a real REDCap test project and the cassettes replay green. Each site's REDCap version is recorded (STD-060, STD-061; CR-062; DEP-026).
- [ ] **MedDRA and CTCAE.** DATA.md and the IRB pack say AE terms are verbatim and MedDRA coding is the sponsor's or the data centre's. An oncology study shows a CTCAE grade with its version (STD-050, STD-051).
- [ ] **CQL.** SQL and CQL agree on the equivalence fixture, including the UTC-edge case, with the pinned jars in CI (STD-070).

**Regulatory, GxP, privacy, quality system**

- [ ] **Legal basis (APPI, PDPA, 人體研究法, 臨床研究法, ethical guidelines).** The per-site legal-basis memo is signed by counsel and named in the DPA **before any real sample**. The study set-up page shows the regime per study (REG-007). The sentence "personal information, pseudonymised as a security measure; not 仮名加工情報" is in the memo, the 開示書 and the IRB text (REG-008).
- [ ] **Notices.** The three opt-out notices cover amendment items 1 to 7 and the 2026-12-01 guideline text; the privacy office has signed them; none is published before T-206 (opt-out worker) passes (REG-002, REG-009).
- [ ] **Commitments register.** Every promise in TB-SITE-02, 04, 05 and the notices has a row that reads "built and tested". VMP §6 lists this as not waivable (REG-010).
- [ ] **Regulatory watch.** `docs/validation/regulatory-watch.md` exists; no checked date is older than 90 days. The gap note on the amended GCP ordinance is signed by the owner and read by the Japan PI before the Japan IQ (REG-001, REG-003, REG-004, REG-005).
- [ ] **ICH E6(R3).** The §4 clause table and the three procedures (audit-trail review, downtime, training) are in the OQ script (REG-023). The record inventory is signed by each trial office (REG-022). The source-and-copy rule is written and the signature meaning says what the CRC really checked (REG-024).
- [ ] **Part 11 and ER/ES.** TST-EDC-04 passes for a local account and through the OIDC flow. The clause-by-clause assessment has no open row. Until then the export carries the neutral text (REG-021, REG-025; CR-034, CR-035, CR-036).
- [ ] **Audit trail.** Signed heads are kept off the box; dropping the newest events fails verification; the clock check is a failure, not a warning; the EDC trail heads are written into the chain nightly (REG-026; CR-054, CR-042, CR-055, CR-016).
- [ ] **Retention.** One retention table per site. The trace store keeps 7 days in PRODUCTION with a scheduled prune and a test (REG-012).
- [ ] **MHLW v7.0 and the IT pack.** The clause map names a control or "hospital" for every relevant clause, including the server-OS second factor (REG-003).
- [ ] **Device status.** The intended-use statement is on every surface from one source file. No tier or label reads as a decision about a person. The clinician role gets 404 on phenotype and derived-score routes. Both written-view requests were sent by 2027-01-29 and the route, date and reply are in `docs/validation/regulatory-views.md` (REG-016 to REG-020; CR-078).
- [ ] **GAMP 5.** VMP v1.1 is signed by all nine roles before IQ. `docs/validation/` exists. The traceability matrix takes its status from test results and shows passing rows for every H function (REG-027).
- [ ] **ISO 14971.** One risk file on one scale. No residual below the initial rests on a control that is not "verified" with a test id (REG-028).
- [ ] **IEC 62304, IEC 82304-1, ISO 13485.** The one-page standards position is on file: class for the profile module, the five records with paths, 82304-1 adopted or declined with a reason, the 13485 trigger (REG-029).
- [ ] **ISO 27001.** The statement of applicability has 93 rows, each with "applies" and evidence or a reason. SECURITY.md §1 describes the deployment form the site really has (REG-031).
- [ ] **AI governance (GMLP, PCCP model, Japan guideline v1.2, Taiwan AI Basic Act).** The AI governance note and the model change protocol exist; T-012's record cites the protocol; N-12 is reported unadjusted; CGMH has answered whether its AI governance body reviews the system (REG-006, REG-030, REG-032).
- [ ] **PoC only (before the first tester signs in).** Demo mode closes paste and uploads; the banner is on every page in three languages; each tester has an own account and a stored acknowledgement; the hosting region is Tokyo or Taiwan (REG-013, REG-014, REG-015).

### 8.4 Claims to withdraw or reword now

These are places where the product or a document says, or implies, a conformance that is not there. Each can be fixed by a wording change now, before the control itself is built. File and line are as the reviews cite them.

| # | Claim today | Where (file:line as cited) | Why it is not true | Reword to, or action | Finding | When |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Every signature in the ODM export is stamped "21 CFR Part 11 electronic signature; ER/ES guideline (Japan)" | `services/edc/odm.py:123` | No Part 11 or ER/ES assessment exists; TB-DS-16 §6 says Part 11 applies "not now"; CR-034, CR-035, CR-036 are open | "Electronic signature of the person named; see the site's validation summary", pinned by a unit test, until TST-EDC-04 passes and the assessment is signed | REG-021 | PoC freeze |
| 2 | IRB amendments and the IT security pack state controls as present: opt-out removal "within minutes"; audit chain "signed daily with a copy on the hospital's share"; "The administrator sees no patient data"; break-glass by a second person; "every view is logged ... and is rate-limited"; re-authentication before a reveal, an export and a signature | `docs/plan/sites/irb-amendment-cgmh.md` items 4, 8, 10 and §A.4; `docs/plan/sites/irb-amendment-japan.md` items 8, 10; `docs/plan/sites/it-security-pack.md` §A.4, §A.8a; `docs/SECURITY.md:90` (step-up not built) | CR-027, CR-042, CR-054, CR-023, CR-029, CR-018, CR-022 are open; WS-13.4 is planned | Mark each such sentence "in build; verified at OQ before any patient data is used". Send the cover note of owner question 1 with the commitments register (`docs/validation/commitments.csv`) | REG-010 | now (amendments were submitted 2026-11-10) |
| 3 | Amendment item 2: profiles are "read by research staff only". Item 1: names and IDs "never enter the database". Item 11 carries the old statement ("does not alert clinicians, does not contact patients") and promises a written regulatory view "before formal use" | `docs/plan/sites/irb-amendment-cgmh.md:59-69`; `docs/plan/intended-use.md:16`; `docs/plan/25-master-plan.md:38`; `docs/SECURITY.md:123-124` | Item 6 gives a treating physician the record, timeline, phenotype and eligibility layers; the pid map holds chart numbers and the audit log holds them in clear (CR-016); TrialBox sends SAE and deadline alerts to investigators; no view has been requested | An erratum sheet per site: the clinician view as a separate, later, switch-off item; the v0.2 statement; "identifiers are kept only in an encrypted map on the same server"; the date the views are requested | REG-011, REG-019 | G2 |
| 4 | The repository is described with 仮名加工情報 ("supports feasibility") and "pseudonymised" in a way that reads as the APPI category | `docs/plan/25-master-plan.md` §9.3 rows 1 and 6; `docs/SECURITY.md:160`; `docs/plan/intended-use.md:18` | The box reveals chart numbers by design, so the data is ordinary personal information | "The repository is personal information (要配慮個人情報 / special-category data), pseudonymised as a security measure; it is not 仮名加工情報 or de-identified data" | REG-008 | G2 |
| 5 | Opt-out notice: "お申し出の後は利用しません"; scope described as "counting and listing candidates" only; item 8 "(公告位置)" still a placeholder | `docs/plan/design/14-ethics-pack.md:113-135`; both amendments, item 8 | Opt-out is not honoured on five paths and the removal worker is not built (CR-019, CR-027); the notice omits the repository, the language model, the vector index, profiles, cross-department views, steward access and retention | Rewrite the three notices for the amended scope and the 2026-12-01 guideline. Do not publish before T-206 passes | REG-009 | G2 (text); go-live (publication) |
| 6 | Screening headline and tier label say "likely eligible" (ja 適格の可能性が高い, zh-TW 可能符合) and "excluded" | `services/console/i18n.py:129,151,508,530,877,899` | The intended-use statement says TrialBox "does not decide whether a patient is eligible"; labelling is the first leg of the device argument | Tier "may meet the criteria" (ja 条件に合う可能性, zh-TW 可能符合條件); add the phrases to the forbidden-word check (T-116) | REG-017; CR-078 | PoC freeze |
| 7 | Two intended-use statement texts are in use; the IRB drafts and the IT pack carry shortened forms | `docs/plan/25-master-plan.md:38`; `docs/plan/intended-use.md:16`; `docs/plan/sites/it-security-pack.md:16` | The plan text is the old one; TB-IU-01 v0.2 changed it | One source file in three languages; documents and the footer generated from it; doclint checks the copies | REG-020 | PoC freeze (with T-116) |
| 8 | Signature meaning: "I checked each value against the **cited hospital record**" | `services/edc/service.py:52-53` (`ODM_MEANING`) | The CRC confirms against the quote TrialBox shows, from TrialBox's uncertified copy; no step tells the CRC to open the EMR | "checked against the record passage shown, copied from the hospital record on <snapshot date>", accepted in the sponsor letter; or link the EMR location and keep the meaning | REG-024 | G3 |
| 9 | Risk file wording: S4 is "a wrong exclusion that denies treatment access"; RSK-03 is S2 in the plan and S4 in TB-DS-11 H-03 | `docs/plan/25-master-plan.md:661,667`; `docs/plan/design/11-risk-management.md:57-65,141`; `docs/plan/design/16-regulatory-position.md` §3.2 | The non-device reasoning says a wrong list "could delay a patient's chance to join a study"; both cannot be the basis | Write the malfunction analysis the guideline asks for; align the two scales | REG-018, REG-028 | G3 |
| 10 | "ISO 14971" risk file, "IEC 62304 light records", "GAMP 5 (categories 4 and 5)", "27001 path" named as the plan's frame | plan frame line and WS-12.1 of `docs/plan/25-master-plan.md`; `docs/plan/intended-use.md:49`; `docs/plan/25-vmp.md` (63 lines; §8 empty); `docs/SECURITY.md:13-30,154` | Nominal today: 0 of 50 risk controls verified; the five 62304 records do not exist; 273 of 273 matrix rows "planned"; no statement of applicability | In TB-PLAN-06 and the site packs, write "planned to" or "in the style of" with the date each artefact is due; never "validated under" or "conforms to" before the evidence exists | REG-027, REG-028, REG-029, REG-031 | now (in TB-PLAN-06 itself) |
| 11 | `docs/SECURITY.md` §1 describes LUKS on Ubuntu as "the host" | `docs/SECURITY.md:13-30,154`; `docs/plan/sites/it-security-pack.md` §A.2, §A.5 | The appliance is Windows 11 with WSL2 and BitLocker, which SECURITY calls "post-platform work"; the hospital reads both | Rewrite §1 per deployment form when T-210 lands; until then add one line saying which form each site gets | REG-031 | G3 |
| 12 | Law and guideline citations are stale: ethical guidelines "(2023)"; Taiwan PDPA "amendment pending"; "72 h to subjects per the draft rules"; 医師法 §24 given as the reason for 5-year mail logs; "J-GCP" with no version | `docs/SECURITY.md:161`; `docs/SECURITY.md:171`; `docs/plan/25-master-plan.md` §9.3 "Breach notification" row, WS-13.5; `docs/SECURITY.md:139`; `docs/SECURITY.md:165` | Guidelines amended 2026-08-27, apply 2026-12-01 [W]; PDPA amendment promulgated 2025-11-11, effective date pending [W]; the 72 h clock cannot be confirmed; 医師法 §24 is about clinical records | Cite current versions with a "confirmed on" date; carry breach clocks as site parameters; fix the mail-log reason | REG-001, REG-002, REG-004, REG-012 | G2 |
| 13 | The screening-log module cites ICH E6(R3) "§2.8 / Appendix C" | `services/console/screening_log.py:3` | §2.8 of Annex 1 is informed consent [T] | "Appendix C (essential records)"; name the E6(R3) edition once, in the VMP | REG-005 | G3 |
| 14 | Trace retention "7 days in PRODUCTION" in the plan and the data-handling rule | `services/tracestore/tracestore.yaml:2`; `docs/plan/sites/data-handling-rule.md` §2 "Log scrubbing"; plan RSK-12 | The code keeps 90 days and no scheduled prune was found | Build it (TB6-REG-12). Until then the documents say "90 days today; 7 days from release <n>" | REG-012; LLM-040 | G2 |
| 15 | N-12 gate result reported as "audit-adjusted" | `docs/VALIDATION.md:79-80` | The adjustment rests on a label sample checked by an AI assistant, not by a clinician | Report N-12 unadjusted as the gate figure, the adjusted figure as a note, until a clinician repeats the sample | REG-030 | G2 |
| 16 | Resources carry TW Core profile URLs in `meta.profile` | `adapter/mapping/tw_core/demo_his.yaml:8-22`; `adapter/validate/validator.py:185-202` | TW Core's code systems are not used and no slice is filled; open slicing lets it pass | Fill the slices (recommended), or drop `meta.profile` for TW and state "FHIR R4, TW Core code systems not used" | STD-011 | G3 |
| 17 | The store is called "OMOP CDM"; the DQD note says standard concepts are 0 "until the Athena bundle is loaded"; the report is called "DQD" | `services/omop/dqd.py:16-18`; `services/omop/vocab.py:278-290`; DATA.md, the SNOMED letter (`docs/plan/snomed-inquiry.md`) and the site pack | Conditions and drugs stay 0 after an Athena load too; the check is a 226-check re-implementation; 24 of 39 tables | "OMOP CDM 5.4 tables with source concepts; standard concepts for measurements and units only"; DQD status `fail (accepted): no SNOMED licence`; name it "TrialBox DQD subset" | STD-030, STD-032 | G2 |
| 18 | Japanese diagnoses are emitted with the ICD-10-CM system URI | `adapter/mapping/jp_core/ssmix2_site.yaml:16`; `tw_core/demo_his.yaml:118`; `ssmix2/source.py:314-326, 412` | Japan's diagnoses are WHO ICD-10 (2013) through MEDIS 標準病名 | Emit `http://hl7.org/fhir/sid/icd-10` for Japan (T-STD-01) | STD-010 | G2 |
| 19 | "v1 ships without SNOMED CT" | `mimic/tables/icu_item_to_snomed.csv`; `services/omop/vocab.py` operator concepts; `reports/twpas_bundle.py` route code; `docs/plan/snomed-inquiry.md` (not sent) | Three files hold SNOMED codes, two with descriptions | Remove the descriptions or wait for the affiliate licence; give each remnant a register row | STD-044 | PoC freeze (T-STD-08) |
| 20 | Plan WS-08.8 promises "NOTICE lists every source" | product root (no NOTICE or third-party file found) | LOINC and UCUM both require their notice and, for LOINC, the version; a hosted demo is distribution | Build the register and NOTICE (T-STD-08) before the demo is opened | STD-044 | PoC freeze |
| 21 | ODM `SDSVarName` carries CDASH names as if SDTM variables (`BRTHDAT`, `VSDAT`, `VISDAT`); CDASH tags called "v2" | `services/edc/odm.py:89-105`; `services/edc/cdash.py:19-33` | They are not SDTM variables; CDASH coverage is 13 variables with no IE, AE, EX, DS | `SDSVarName` only for true SDTM names, else `Alias Context="CDASH"`; state the CDISC scope in DATA.md | STD-062, STD-063 | G3 |
| 22 | REDCap client comment: majors 14, 15, 16 are "LTS lines the connector is tested on" | `services/rc_bridge/client.py:17,123-129`; `docs/plan/design/08-interface-control.md:44` | The tests run only against `rc_sim`; no real REDCap was ever called (CR-062) | "accepted" until a real instance is tested | DEP-026; STD-060 | G2 |
| 23 | Compose comment says the Spark image is a "GB10 build … sm_121" | `deploy/docker-compose.gb10.yml:37-38,61` | The pinned image's config says `TORCH_CUDA_ARCH_LIST=10.3a` (DGX Station), by a registry look-up; not run on a Spark | Replace the image (see §9); correct the comment | DEP-003 | before G1 |
| 24 | Model registry licence rows say "terms to confirm" and `verified: false`, yet install pins the build as `champion`; the registry comment says such a build must not pass `candidate` | `models/registry.yaml:7-8,89,99,104` | No code reads `licence.verified`; the model cards read on 2026-11-10 declare Apache-2.0 or MIT | Record the licence check as a file per build; `qualify` refuses `champion` without it | LLM-012; DEP-011; CR-096 | G2 |

Not on the list on purpose: honest "not done" lists in `docs/SECURITY.md`, the SAE register's statement that the office log is the record, and TB-IU-01's split between "consultant's opinion" and "authority's written answer". The reviews ask that these stay as they are.

## 9. Dependency upgrade plan

Sources: `docs/reviews/2026-11-10-deep-review/08-dependency-currency.md` (TB-DR-08, findings DEP-nnn) and the model, vLLM, chat-template and pin items of `03-llm-serving-stack.md` (TB-DR-03, findings LLM-nnn). Versions, dates and advisories are as those reviews looked them up on 2026-11-10. Nothing here was re-checked. "not verified online" is kept where the reviews wrote it.

The state in one line: the Python lock is in very good shape (176 of 201 packages at the latest stable release, no advisory on any pin, `pip-audit` clean on the runtime lock). The risk sits outside it: the JVM jars, the GPU serving images, the model weights and the build tools.

What the reviews did not run: no Docker pull or build, no Trivy or Syft scan (image findings come from `deploy/security/known-image-findings.md` of 2026-11-10), no GPU, no vLLM, no real model.

### 9.1 State

| Component group | Current | Latest (2026-11-10) | Advisories | Action | Batch |
| --- | --- | --- | --- | --- | --- |
| Python packages, runtime lock (73 in `deploy/requirements.lock`) | all at latest except `duckdb` and `duckdb-extension-fts` 1.5.5 | DuckDB 2.0.0 (2026-10-21), FTS 2.0.0 (2026-11-01) | none (OSV; `pip-audit` "No known vulnerabilities found") | keep; monthly lock refresh; DuckDB 2.x after go-live (change list and storage format of 2.0 not verified) (DEP-023) | 3 (refresh), 4 (DuckDB) |
| Python packages, extras and dev (128 outside the runtime lock) | `docling` 2.149.0, `huggingface-hub` 1.33.0, `semchunk` 3.2.5, `isort` 8.0.1, CUDA wheels one minor behind (bound by `torch` 2.15.0) | `docling` 2.150.0, `huggingface-hub` 2.4.0, `semchunk` 4.1.1, `isort` 9.0.2 | none (OSV). Outside the `pip-audit` gate. Installed in **no** image (DEP-012) | decide per extra: a `trialbox-ml` image from a second hashed lock, or drop the code path; lock an OCR engine if OCR stays (DEP-012, DEP-028; LLM-013) | 2 |
| Python runtime | 3.12.16 on Debian 13 (digest 2026-11-05) | 3.12.16; 3.14.10 is the active line | none; 3.12 is security-only, ends 2028-10-31 | keep through go-live; 3.14 after (DEP-022) | 4 |
| Build tool uv | 0.11.32 (CI and `tools/supply_chain/lock.py`) | 0.13.7 | **CRITICAL GHSA-hq85-5cpj-mr62 / PYSEC-2026-4321** (compromised CA root in the bundled trust store; fixed 0.13.4) | move to ≥ 0.13.4 everywhere; re-run `uv lock` (DEP-006) | 0 |
| Scanners and audit tools | Syft 1.56.0, Trivy 0.75.0, pip-audit 2.9.0 | 1.57.1, 0.76.2, 2.10.1 | none | bump with their sha256 sums (DEP-024) | 0 |
| GitHub Actions (seven, pinned by SHA) | checkout v4.4.0, setup-uv v5.4.2, setup-java v4.9.1, cache v4.3.0, upload-artifact v4.6.2, setup-qemu v3.7.0, setup-buildx v3.12.0; all `node20` | v7.0.1, v10.3.3, v6.2.0, v6.1.0, v7.0.2, v4.4.0, v4.4.1 | none. Node 20 retirement on hosted runners: not verified online | move each to its current major by SHA in one PR (DEP-018) | 0 |
| Update bot | none (`.github/dependabot.yml` and `renovate.json` absent) | — | digests age silently | adopt the policy of §9.3 (DEP-019) | 0 (config), 3 (running) |
| CQL translator classpath (`cql-to-elm-cli` 5.4.0 + 102 transitive jars) | HL7 FHIR core 6.9.4.1, `jackson-databind` 2.21.1, `commons-beanutils` 1.9.3, `ucum` 1.0.8, `guava` 33.2.1, `httpcore5` 5.1.3 | fixes at 6.9.10 / 6.9.12, 2.21.7 and others; `cql-to-elm` 5.5.0 (kept at 5.4.0 with HAPI 8.12 on purpose) | **20 vulnerable jars, one CRITICAL** (CVE-2026-55471 XXE), many HIGH. PR #78 leaves three MODERATE (`opentelemetry-api` 1.60.1, `junit` 4.7 on the runtime classpath, `commons-compress` 1.24.0) | merge PR #78 after its tests, plus the three residuals; gate to block mode (DEP-001, DEP-002; CR-045) | 0 |
| JRE in the JVM image | Temurin 17.0.20.1 (digest 2026-10-02); CI uses Java 21 | 17.0.21 / 21.0.13 / 25.0.5 | October 2026 Java CPU missing; Temurin 17 ends 2027-10-31 | `eclipse-temurin:21-jre` by digest (DEP-015) | 0 |
| HL7 validator CLI | 6.10.4 (2026-09-30); downloaded hash never compared | 7.0.5 (2026-11-05, new major) | none in OSV for the core artifact; fat jar not scanned | pin sha256 now (DEP-017); 7.x after go-live (DEP-020) | 0 (hash), 4 (7.x) |
| HAPI image | `hapiproject/hapi:v8.12.0-2` (2026-10-02) | same image (Maven has 8.12.1) | 24 fixable image findings (CR-045) | take the next image that clears them; moves with `cql-to-elm` (DEP-020) | 3 |
| vLLM (x86, RTX PRO 6000 / RTX 5090 / default) | `vllm/vllm-openai:v0.32.0`, **tag only, no digest**, CUDA 13.0.2 | v0.33.0 (2026-11-02; TB-DR-03 read the releases page as "v0.33.0 (rc3, 2 Nov)") | 29 fixable HIGH/CRITICAL image findings; OSV none for vLLM 0.32.0 | pin `v0.32.0@sha256:befccf0e…` in one `deploy/images.lock`; any version move needs requalification (DEP-004; LLM-010; CR-044, CR-045) | 1 |
| vLLM (DGX Spark) | `eugr/spark-vllm:station-20261001@sha256:f5700f…`, a personal account's build for `10.3a` (DGX Station), not GB10 | official `vllm/vllm-openai` arm64, or a `12.1a` build | not scanned; wrong target. Not run on a Spark | replace; arch check in `check_host.sh --gb10` (DEP-003; owner question Q2) | 1 |
| NVIDIA driver (host) | GB10: exactly 580.142 checked; RTX PRO 6000 and B200 unchecked; no B200 profile | R580 line or newer needed by CUDA 13 images | — | `check_host.sh` fails on a low driver; requirement written into the CGMH IT request; B200 profile or note (DEP-005; LLM-011) | 1 (check), 2 (B200 profile) |
| Judge weights | `nvidia/Gemma-4-26B-A4B-NVFP4`, `revision: null`, `sha256: null`; chat template of 2026-05-07; no `--chat-template` | upstream Google template fixed 2026-07-15, tokenizer config 2026-07-20 (`google/gemma-4-26B-A4B-it` rev `4d7ae4984b7d`) | none; judge prompts may render with the old template | pin revision and manifest; template and tokenizer config from upstream; pass `--chat-template`; re-run canary and N-12 (DEP-007; LLM-007) | 2 (before the G1b run) |
| Verifier weights | `cyankiwi/Qwen3.5-9B-AWQ-4bit` (personal account; history squashed 2026-07-21), `revision: null`, `sha256: null` | no official Qwen 9B quantisation | none; provenance weak (CR-097 for the hashes) | own quantisation of `Qwen/Qwen3.5-9B` rev `c20223623576` with the public recipe, or a mirrored copy at rev `e4d2d39cede8` (DEP-008; LLM-012; owner question Q3) | 2 |
| Judge challenger (Gemma 4 31B) | no registry build | `google/gemma-4-31B-it-qat-w4a16-ct` (2026-06-04); `nvidia/Gemma-4-31B-IT-NVFP4` (2026-07-13, licence tag "other") | — | add a candidate build; prefer Google's QAT checkpoint (DEP-009; LLM-011) | 2 |
| Embedder | `BAAI/bge-m3` (path only; pickle weights only, which `pin_model` refuses); not in the registry; wizard writes a mode the service refuses | `Qwen/Qwen3-Embedding-0.6B` rev `97b0c614be4d` (safetensors, 1024-d) | — | add "safetensors from the publisher" to the T-009 decision; register and pin like a model (DEP-010; LLM-013, LLM-014) | 2 |
| Guard candidate | `openai/gpt-oss-safeguard-20b`, revision null | rev `8a11e17b25c9` (2026-01-14) | — | pin if deployed | 2 |
| PostgreSQL image | `postgres:16-alpine` 16.15, Alpine 3.24.2, digest of 2026-09-17; cannot take pgvector (CR-083) | 16.15 on Alpine 3.24.4; 17.11; 18.6 | 30 image findings (CR-045); PG 16 ends 2028-11-09 | refresh the digest now; new Debian 13 image with PostgreSQL 17 or 18 in T-104 (DEP-013; owner question Q1) | 1 (digest), 2 (new image) |
| PostgreSQL major across demo, CI, compose | compose 16.15; demo 17 (not verified online); CI whatever `ubuntu-latest` installs | one declared major | — | `TB_PG_MAJOR` used by all three; CI runner pinned (DEP-014) | 2 |
| pgvector, PGroonga | not deployed | 0.8.7 (2026-10-31); 4.1.0 (2026-10-09) | none known | pin in T-104 | 2 |
| pgBackRest | Alpine package 2.58.0, unpinned | 2.60.0 | none known | pinned from PGDG in T-104 (DEP-027) | 2 |
| Caddy, Authelia | 2.11.9; 4.39.28 | same | OSV none | keep | — |
| Test mail servers | MailHog v1.0.1 (abandoned since 2020); GreenMail 2.1.3 | Mailpit; GreenMail 2.1.15 (2026-10-25) | 1,590 and 16 image findings (CR-045); test-only | replace MailHog with Mailpit; GreenMail 2.1.15 by digest (DEP-021) | 1 |
| FHIR packages | TWPAS 1.2.0 cached from the npm mirror, settings default 1.2.5; extensions `5.3.0-ballot-tc1`; terminology 7.0.1; TW Core 1.0.0; JP Core 1.1.0 | TWPAS 1.3.0; extensions 5.4.0; terminology 7.5.0; TW Core and JP Core current (1.1.1-rc exists) | none | fetch from packages.fhir.org by the settings version; TWPAS per the CGMH answer; new decision superseding D-63 (DEP-016) | 2 |
| Build downloads without a pinned hash | validator jar, FHIR tarballs (no `dist.integrity` check), Noto fonts from branch `main`, Maven jars (no checksum policy) | — | a tampered file would pass | sha256 for the jar; npm integrity in a packages lock; fonts by commit and sha256; Maven `-C` (DEP-017) | 0 (jar), 2 (rest) |
| Front-end and test tools | axe-core 4.10.2 (vendored, test-only); Playwright version not pinned in the repo | axe-core 4.14.0 | none; no third-party JS in the console or the site | bump axe-core with its sha256; record the Playwright version in a small `package.json` and lock (DEP-025) | 3 |
| REDCap (site side) | accepts majors 14, 15, 16; sites' versions not recorded | not verified online (the vendor site needs a login) | — | record each site's version; one test on a REDCap sandbox (DEP-026; STD-060) | 3 |

Hard end dates inside the study period: Temurin 17 ends 2027-10-31 (closed by Batch 0). Debian 12 LTS ends 2028-06-30. Python 3.12 ends 2028-10-31. PostgreSQL 16 ends 2028-11-09 (closed by Batch 2 if the major moves).

### 9.2 The batches, in order

Effort: S ≤ 1 day, M 2 to 4 days, L 1 to 2 weeks of one agent session. A batch merges only with the test evidence named. Every batch ends with the release record of T-110 (`release.json`): the lock diff, the SBOM per image, the `pip-audit` and Trivy reports, OSV on the JVM classpath.

Note on numbering. TB-DR-08 §3.1 numbers its batches 0 to 5 against other dates. The table below regroups the same items onto the plan's gates. The mapping is in the last column.

| Batch | Deadline | Exact items | Findings | Test evidence required to merge | Effort | TB-DR-08 batch |
| --- | --- | --- | --- | --- | --- | --- |
| **0 Build tools and JVM** | before the PoC freeze, **2026-11-27** | (a) uv → ≥ 0.13.4 in CI, `lock.py UV_VERSION` and the dev machines; `uv lock` re-run (no package change expected). Until merged, run uv with `--native-tls` / `UV_SYSTEM_CERTS`. (b) pip-audit 2.10.1; Syft 1.57.1 and Trivy 0.76.2 with their sums. (c) The seven GitHub Actions to their current majors by SHA, one PR. (d) `renovate.json` committed per §9.3. (e) PR #78 merged, plus `opentelemetry-api` ≥ 1.67.0, `commons-compress` ≥ 1.26, `junit` excluded from the translator dependency. (f) JVM image on `eclipse-temurin:21-jre` by digest. (g) sha256 of `validator_cli.jar` pinned next to `VALIDATOR_VERSION`. | DEP-006, DEP-024, DEP-018, DEP-019 (config), DEP-001, DEP-002, DEP-015, DEP-017 (jar); CR-045 (own-image part) | `uv --version` in CI ≥ 0.13.4; `uv lock --check`, `make lock-check`, `allowlist-check` pass; `pip-audit` gate PASS; every workflow green once and no `node20` action left; the Renovate dashboard issue opens. CQL unit tests (`tests/unit/test_cql_*`), the validator sample test and the e2e build gate pass in the rebuilt image; `java -version` in the image equals CI; OSV on the resolved classpath shows 0 HIGH/CRITICAL; the Trivy gate runs in **block** mode for trialbox-jvm and trialbox-demo (`VULN_REPORT_ONLY` loses both); a tampered validator jar fails the fetch | M (T-110 add) + S (T-DEP-1) | 0 and 1 |
| **1 Third-party images** | before G1, **2026-12-04** | (a) `deploy/images.lock` as the one digest list, referenced by every compose file. (b) vLLM `v0.32.0@sha256:befccf0e…` (the version the G1 run uses; no version change). (c) The Spark image replaced by the official `vllm/vllm-openai` arm64 image by index digest, or a `12.1a` build by digest with a dated exception; the comment corrected. (d) `check_host.sh`: arch check for `--gb10`; FAIL when the driver major is below the image's CUDA requirement. (e) The driver and CUDA requirement written into the CGMH IT request. (f) `postgres:16-alpine` digest refreshed. (g) MailHog replaced by Mailpit; GreenMail 2.1.15 by digest. (h) The structured-output backend recorded in the serving record. | DEP-004, DEP-003, DEP-005 (check), DEP-021, DEP-019 (stale digests); LLM-010; CR-044, CR-045 (third-party part) | `grep -E 'image:.*vllm' deploy/*.yml` shows only digests and the bundle refuses a mismatch; the Trivy gate per image; the compose integration test; `check_host.sh` on a host with driver 575 fails with a plain message and fails on an arch mismatch; on the GPU VM a canary only (no version change, so no requalification). The Spark part is proved later: the Spark benchmark's serving record names the image digest and `torch.cuda.get_device_capability()` | M (T-DEP-2) | 2 |
| **2 Data plane and models** | before design freeze G2, **2027-01-08**. The model items go first, before the G1b qualification run (about four weeks before G2 per TB-DR-10) | **Models.** (a) Expected weight-manifest sha256 and upstream revision for every released build in the committed registry or `release.json`; `pin_model --install` refuses weights that differ; one hash format in `pin_model` and `serving_config`; install pins `candidate`, `champion` only through `qualify`. (b) Judge: `chat_template.jinja` and `tokenizer_config.json` from the Google repository at a pinned revision, stored with the site pin and entered in the weight manifest; `--chat-template` passed. (c) Verifier: own quantisation or mirrored copy (Q3), with source repository, revision, manifest sha256 and licence file. (d) Gemma 4 31B challenger build added. (e) Embedder decision with the safetensors criterion; embedder registered and pinned; the wizard writes a mode the service accepts. (f) Registry builds and a pin step for the B200 / shared-quota profile; B200 compose profile or note. (g) Licence file per build; rows set `verified: true` with URL, revision and date. **Data plane.** (h) T-104 `db` image on Debian 13 with PostgreSQL 17 or 18 (Q1), pgvector 0.8.7, PGroonga 4.1.0, pgBackRest pinned from PGDG. (i) One PostgreSQL major (`TB_PG_MAJOR`) in the db image, the demo and CI; CI runner pinned to `ubuntu-24.04`. (j) FHIR packages from packages.fhir.org by the settings version; TWPAS per the CGMH answer; extensions 5.4.0; terminology to the version TW Core 1.0.0 declares; decision superseding D-63. (k) `trialbox-ml` image from a second hashed lock (docling, embed, OCR), or the extras and their code paths removed; `TB_EMBED_MODE` set in compose. (l) Remaining build-download hashes: npm `dist.integrity` in a packages lock; fonts by commit and sha256; Maven strict checksums. | DEP-007, DEP-008, DEP-009, DEP-010, DEP-011, DEP-012, DEP-013, DEP-014, DEP-016, DEP-017 (rest), DEP-027, DEP-005 (B200 profile); LLM-007, LLM-011, LLM-012, LLM-013, LLM-014; CR-083, CR-096, CR-097 | **Models:** no `null` revision for any build a site profile deploys; a folder holding one 16-byte file is refused by `--install`; `pin_model --verify-all` passes; the serving record names the template sha256 and a test renders one judge prompt and compares it with the upstream template's output; the judge canary and N-12 pass; the G1b qualification record per build (WS-02.2) names image digest, template sha and weight manifest; `trialbox eval qualify` can run the challenger by build id; `pin_model --build <embedder>` succeeds and the wizard's output starts the embed service. **Data plane:** T-104's acceptance plus `SELECT version()` showing the chosen major; `backup_drill` passes on the new image; goldens unchanged (`make goldens-check`); a CI step prints `pg_config --version` and fails on a mismatch; TWPAS validation tests pass on the chosen version and `twpas_version` in settings equals the cached package; `docker run trialbox-ml python -c "import docling, sentence_transformers"` passes and `pip-audit` covers both locks; a tampered tarball or font fails the fetch | M (T-DEP-3) + L (T-012, existing, upper end) + S (T-009 add, T-LLM-07) + M (T-104 add) + S (T-DEP-5) + M (T-DEP-4) + M (T-113 / T-114 add) | 3 |
| **3 Patch window** | before G3, **2027-02-26** | (a) Monthly lock refresh: patch and minor inside the lock only. (b) Image digest refreshes. (c) The next HAPI image that clears its findings, with `cql-to-elm` kept aligned. (d) axe-core 4.14.0 with its sha256; the Playwright version recorded in a `package.json` and lock under `tools/`. (e) Each site's REDCap version recorded; the client comment reworded to "accepted"; one test on a REDCap sandbox before go-live. (f) Weights verified beyond install: `--verify-all` in `trialbox doctor`, before each scheduled screening run and after an update; the gateway compares `/v1/models` `root` and `max_model_len` with the pin at start and hourly. **Nothing** that changes a model, vLLM or the DB major. | DEP-019 (running), DEP-020 (HAPI part), DEP-025, DEP-026, DEP-028; LLM-008, LLM-009 | The full test suite, e2e, the update drill and the gates; release notes list every changed package; a changed weight file sets `weights_changed` and the gateway refuses the build | S per monthly refresh; S (DEP-025, DEP-026); S to M (LLM-008, LLM-009; the review gave no size) | 4 |
| **Freeze** | from G3 **2027-02-26** to go-live (CGMH 2027-04-28, Japan 2027-05-13), held to two weeks after the Japan go-live (2027-05-27) | Security fixes only: a fixable HIGH or CRITICAL that is reachable, or any CRITICAL. Each fix is its own signed bundle. | — | The failing advisory's test or scan, the full suite, the update drill; the owner and the security owner sign | — | "Freeze" |
| **4 After go-live** | from 2027-06 | Python 3.14 (before 2028). DuckDB 2.x, tested on a copy of the lake (open old files, FTS index rebuild, goldens unchanged). HL7 validator 7.x together with `cql-to-elm` and HAPI. vLLM moves, each with requalification. Temurin 21 → 25 later. | DEP-020, DEP-022, DEP-023 | As Batch 2 for anything that touches data or models | M each (the review sizes the Python move M; the others carry no size) | 5 |

Two points for the lead.

1. **Freeze start.** TB-DR-08 proposes a patch window from 2027-01-08 to 2027-03-26 and a freeze from 2027-03-29 (four weeks before the CGMH go-live) to 2027-05-27, plus one week before each gate run. This section starts the freeze at G3 as instructed. That is four weeks stricter. If the lead prefers the review's dates, Batch 3 runs to 2027-03-26.
2. **DEP-005 and DEP-017 are split.** TB-DR-08's batch table closes both in its batch 3. Card T-DEP-2 puts the driver check with the image work and card T-110 puts the download hashes with the build tools. Here the cheap part of each goes early (driver check in Batch 1, validator jar hash in Batch 0) and the rest stays in Batch 2.

### 9.3 Standing policy

**Update bot.** Renovate. It handles `uv.lock`, Dockerfiles, compose files, GitHub Actions and Maven. Through regex managers it also handles `VALIDATOR_VERSION`, `scanners.py`, `fetch_fhir_packages.py` and the `${VAR:-image@sha256}` defaults. Dependabot is the fallback if Renovate cannot be installed on the repository.

Config sketch (`renovate.json` at the repository root, scoped to `trialbox/`), as TB-DR-08 §3.2 gives it:

| Setting | Value |
| --- | --- |
| `extends` | `config:recommended`, `:pinDigests`, `helpers:pinGitHubActionDigests` |
| `dependencyDashboard` | `true` |
| `lockFileMaintenance` | enabled; schedule "before 6am on the first Monday of the month" |
| Group "python-runtime" | packages in `deploy/requirements.lock`; monthly |
| Groups "python-dev", "actions", "jvm" (translator pom and validator) | monthly |
| `vllm/vllm-openai`, `eugr/*`, model files, the `postgres` major | enabled, `automerge: false`, label `requalify`; never merged without WS-02.2 |
| Major updates | separate PRs, label `major` |
| `vulnerabilityAlerts` | enabled, "at any time", label `security`; `osvVulnerabilityAlerts: true` |
| Automerge | none anywhere. Every change is reviewed and appears in the release record. |

**Cadence.** Monthly batch PRs. Security alerts: within 7 days for a reachable HIGH or CRITICAL, 30 days for the rest. Allow-list entries keep their 180-day `review_by`.

**Who approves.**

| Change | Approver |
| --- | --- |
| Every dependency PR and every allow-list change | the security owner (to be named, OD-4) |
| Anything touching vLLM, model weights, a chat template, the DB major or the six safety-core files | the safety-core engineer co-approves |
| The release record | the owner signs |
| Opening and testing the PRs | an agent may; an agent never merges them |

**Freeze windows.** From G3 (2027-02-26) to two weeks after the Japan go-live (2027-05-27): security fixes only, through a signed bundle. The same rule holds for one week before each gate run (G1b, G2, G3). For later sites: from four weeks before a go-live to two weeks after.

**Model-weight pin and hash rule.**

- Every build a site profile deploys has, in the committed registry or `release.json`: the source repository, the upstream revision, the weight-manifest sha256 made by `tools/pin_model.py`, and the licence file. No `null` (DEP-008; LLM-007).
- `pin_model --install` compares the folder with the expected manifest and refuses a difference. Install pins `candidate`. Only `trialbox eval qualify` moves a build to `champion`, and a PRODUCTION gateway refuses a champion without a qualification record (LLM-007; CR-079; card T-012).
- The chat template and the tokenizer config are part of the weight manifest. The serving record names the template sha256 (DEP-007).
- Pickle weights (`.bin`, `.pt`) and Python files stay refused. A model that ships only pickle weights is converted once to safetensors in a recorded step, and the converted manifest is pinned (DEP-010).
- Weights are verified at install, in `trialbox doctor`, before each scheduled screening run and after an update. A mismatch makes the gateway refuse the build (LLM-008).
- A change of weights, quantisation, chat template, vLLM version or structured-output backend is a model change. It needs `qualify` and the model change protocol (LLM-010; REG-032).
- The embedder follows the same rule as the two models (LLM-014).

**Digest pinning for images.**

- Every image, own or third-party, is referenced by index digest from one file, `deploy/images.lock`. No compose file names an image by tag alone (DEP-004; CR-044).
- The bundle and the installer refuse an image whose digest is not in the list.
- A community or personal-account image is allowed only with a dated exception and its digest (DEP-003; owner question Q2).
- Renovate refreshes digests monthly. Each refresh PR gives the reason to move and passes the Trivy gate for that image (DEP-019).
- Build downloads follow the same idea: a pinned sha256 or integrity value for each jar, tarball and font; a tampered file fails the fetch (DEP-017).

**An emergency CVE during the freeze or PQ.**

1. Triage by the security owner: is the advisory fixable, and is the vulnerable code reachable in TrialBox? A reachable HIGH or CRITICAL, or any CRITICAL, is in scope during the freeze. Anything else waits for Batch 4.
2. The fix is one change, alone in its own signed bundle. No other update rides with it.
3. Evidence before release: the failing advisory's test or scan now passing, the full suite, the update drill.
4. The owner and the security owner sign. The safety-core engineer co-signs if the fix touches vLLM, weights, a chat template, the DB major or a safety-core file; such a fix is a model or data change and needs its qualification record.
5. Target time: 7 days for a reachable HIGH or CRITICAL.
6. The release record lists the advisory, the changed package and the evidence.

Open point: the reviews do not say which PQ steps, if any, are repeated at a site after such a bundle. The VMP's change classes (plan §7.5) should answer it. Until then the plan should state that the impact assessment for each emergency bundle names the PQ steps to repeat, and that the CGMH independent second reviewer co-signs it.

### 9.4 Licence register items

One register as data (`docs/licences/register.csv`, card T-STD-08): standard or component, version, source, licence, obligation, who holds it, evidence. It is rendered into `NOTICE` / `THIRD_PARTY_NOTICES` and the console's About page. A build fails when a shipped data file has no register row. The "by when" dates below are proposals where the reviews gave none; the PoC date is the reviews' own (a hosted demo is distribution).

| Item | What is needed | State today | By when | Who | Finding |
| --- | --- | --- | --- | --- | --- |
| LOINC | Notice text and the version statement in the product | No NOTICE file; no release pinned (PR #82 adds a pin) | PoC freeze 2026-11-27 | agent | STD-044 |
| UCUM | Notice | Missing | PoC freeze | agent | STD-044 |
| ATC (codes and names) | Written permission from WHOCC to ship in a commercial product; else ship codes only and take names from the open NHI and site lists | Not asked. The restriction is the reviewer's reading of the WHOCC copyright notice, to confirm in writing | Ask now; register row by the PoC freeze; answer or fallback by go-live | owner | STD-044; owner question 5 (TB-DR-05a) |
| SNOMED CT | Affiliate licence through MLDS for Japan and Taiwan (neither is a member, per the repository's check of 2026-11-09). Until then no SNOMED content ships | Inquiry TB-LIC-01 ready, not sent. Three files hold SNOMED codes, two with descriptions | Remnants removed or rowed by the PoC freeze; licence later | owner (inquiry); agent (remnants) | STD-044, STD-030 |
| Athena vocabulary bundle | Account and per-vocabulary terms; SNOMED part needs the affiliate licence; CPT4 needs UMLS; shipping a bundle inside a signed update is redistribution and is not cleared | No load path; no register row | G3 (allow-list and rows); go-live (cleared) | owner; agent | STD-034 |
| WHO ICD-10 (Japan) | WHO licence for commercial use | Permission letter not asked | go-live | owner | STD-044 |
| MEDIS masters (標準病名, HOT), JLAC10 / JLAC11 (JSLM) | 使用許諾 (WS-15.3). The site loads its own release; TrialBox never ships them | Site-loaded by design; letters not yet asked | go-live | owner; site | STD-044 |
| YJ ingredient-to-ATC table | A source whose licence allows building and shipping the table (about 2,500 ingredients); version and sha256 as reference data | No source chosen | G2 (with T-STD-07) | owner; agent | STD-042 |
| MedDRA, MedDRA/J | MSSO subscription (fee by revenue); MedDRA/J through JMO. Needed only if TrialBox ever codes AEs | Not held; recommended not to code in v1 | later; the "not coded here" statement by G3 | owner | STD-050 |
| CTCAE | Free (NCI). Record the version per study | Not used | G3 | agent | STD-051 |
| TW Core, TWPAS, NHI lab map; HL7 FHIR packages | CC0 / CC0-1.0. Register row only | Reference data of PR #65 is registered with source, licence, version and sha256 | G3 | agent | TB-DR-05a §2; DEP-016 |
| NHI drug codes (data.gov.tw 23715) | Open Government Data License 1.0: attribution row | Registered (PR #65) | G3 | agent | TB-DR-05a §2 |
| JP Core package | Licence not stated in the package; JAMI terms to confirm ("JP Core licence not read here" in TB-DR-08) | Open | go-live (Japan) | owner | TB-DR-05a §2; TB-DR-08 §2.7 |
| CDISC ODM XSD, CDASH, Controlled Terminology | Free to implement; the XSD goes under `tests/fixtures/odm/` | No row | G3 | agent | STD-062 |
| REDCap | Licensed to non-profit institutions only. The vendor cannot hold one. A site sandbox (one empty test project and an API token on the site's test server) is needed | Not asked | Ask this month; one recorded run before go-live | owner; site | STD-060; owner question 2 (TB-DR-05a) |
| Model weights: Gemma 4 26B-A4B (NVIDIA NVFP4), Gemma 4 31B, Qwen3.5-9B (AWQ), bge-m3 or Qwen3-Embedding, gpt-oss-safeguard-20b | Model cards read 2026-11-10 declare Apache-2.0 (MIT for bge-m3). Keep the licence file in the weight folder so it enters the manifest; record who checked, date, URL and text hash per build; counsel confirms once (WS-15.6). `nvidia/Gemma-4-31B-IT-NVFP4` carries licence tag "other": prefer Google's own checkpoint | Registry rows say "terms to confirm", `verified: false` | G2 (with T-DEP-3 and T-012) | agent; counsel | DEP-011, DEP-009; LLM-012; CR-096 |
| Verifier and embedder origin | Not a licence but a disclosure: the verifier is quantised by a community account from a PRC developer's model; the embedder is from a PRC institute. Name the origin in the site IT pack; decide before G2 whether both hospitals accept it | Open | G2 | owner; site | LLM-012; owner question Q3 (TB-DR-03) |
| Python runtime packages | 8 LGPL packages and one dual-licensed (dulwich, Apache branch taken) are in `deploy/supply-chain-allowlist.yaml`. MPL-2.0 (certifi, tqdm, pathspec) is file-level and unmodified. No GPL or AGPL in the runtime image. Notices only | Allow-listed; checks pass | G3 (notices generated in the release, T-110) | agent | TB-DR-08 §2.7 |
| NVIDIA CUDA wheels (proprietary EULA) | Only if a `trialbox-ml` image is built: the EULA terms go into `THIRD_PARTY_NOTICES` | Extras only; in no image today | G2 (with T-DEP-4) | agent | DEP-012; TB-DR-08 §2.7 |
| Third-party images | Temurin: GPLv2 with Classpath Exception. Groonga inside PGroonga: LGPL-2.1. PostgreSQL, pgvector, PGroonga: PostgreSQL licence. Caddy, Authelia, HAPI, vLLM, GreenMail: Apache-2.0. pgBackRest, MailHog: MIT. **All from training knowledge, not verified online in the review.** None blocks on-premises redistribution of unmodified images; all go into the notices | No notices file | G3 (T-110); verify each licence at the source first | agent | TB-DR-08 §2.7 |
| Community Spark vLLM image (`eugr/*`) | No stated vouching party; "community" licence. Use only with a dated exception, or replace by the official image | In the Spark compose file | before G1 (Batch 1) | owner (Q2) | DEP-003 |
| Fonts: Noto Sans TC / JP | SIL OFL 1.1 (the script fetches `OFL.txt`). Embedding subsets in reports is allowed. Notice row | Fetched from branch `main`, unpinned | G2 (with the font hash, Batch 2) | agent | DEP-017; TB-DR-08 §2.7 |
| axe-core (vendored, test-only) | MPL-2.0; row only | Vendored 4.10.2 | G3 | agent | DEP-025 |

## 10. Questions for the owner

Only decisions that are truly the owner's. Each has a recommended answer; if the owner says nothing by G0, the plan proceeds on the recommendation and records it as an assumption. The review files hold further questions of detail (each file's "Questions" section); those are settled by the recommendation unless the owner objects.

### 10.1 For the PoC (answers wanted by Fri 2026-11-13)

| # | Question | Recommended answer |
| --- | --- | --- |
| Q-01 | Do Dr Makoto and Dr Wenn test themselves, about four hours each in the weeks of 11-30 and 12-07? Who facilitates the sessions? | Yes, themselves, as PI and sub-investigator, with a facilitated CRC part. The owner facilitates, or names one person who speaks the tester's language or English. |
| Q-02 | Which studies does each PI run today (type, phase, area, EDC)? Is Dr Wenn's field rheumatology? The repository says early Alzheimer's disease for Japan and rheumatology for CGMH and nothing more. | Send the one-table study list to both this week. Until it returns, build the Alzheimer's trial and the RA trial scenarios; they match the documents. |
| Q-03 | Do you approve a small cloud cost for the PoC host: one VM in `asia-east1`, about US$110 a month for two months, plus a domain name? | Yes. The free plan cannot run the demo. Your own machine behind a tunnel is the same-day fallback only. |
| Q-04 | May the PI start feasibility, screening and case runs? Today only the coordinator and the admin can. | Yes, for the PI on the PI's own studies; a separate tick for sub-investigators; the daily limits unchanged. |
| Q-07 | Is the PoC product evaluation (not research)? What do the clinicians sign? Does counsel read the statement? | Yes, product evaluation, recorded as a decision. They sign the acknowledgement only. Counsel reads the one-page statement once; no confidentiality agreement beyond it unless you want one. |
| Q-13 | May the PoC show note results from recorded real-model answers of the G1 short run (synthetic patients), with a label? Do you want step 2 (real models on your B200, January)? | Yes to both. |

### 10.2 For the dates

| # | Question | Recommended answer |
| --- | --- | --- |
| Q-05 | Do you accept deciding the Japan hardware form on 12-18 from the measured G1 numbers and a short Spark run, not on 01-08 after a 14-night bench run? | Yes. The one-box workstation unless the numbers clearly pass for the Spark. It buys three to four weeks on a chain with zero float. The 14 nights become the acceptance of the chosen form. |
| Q-06 | May setpoints, the gap finder, the clinician view of them, consortium work beyond the synthetic two-box test, and taking HAPI out be dated to the first release after go-live? | Yes. All are off, synthetic-only or internal on go-live day. About 30 sessions and two S4 risks leave the go-live path. |
| Q-08 | Will you disclose the conflict of interest to CGMH in writing this week, let someone else sign the contract and lead the Study A reading, and name deputies (steward, B200 operator, repository and cloud admin) and an operations person from December? | Yes. Without the ruling the contract chain is likely to stall in legal review; without deputies every chain stops when you are away. |
| Q-09 | Do you accept named fallback dates now (CGMH Wed 05-19, Japan Thu 05-27) with decision points at G1, G2 and G3? | Yes. A named fallback is cheaper than a surprise at G4. The targets do not change. |
| Q-10 | Should the Japan contract be planned to take effect on 04-01 (the new fiscal year), with real-data OQ from that day? | Ask Makoto; probably yes. |
| Q-11 | Can the CGMH HIS team start the export mechanism now, under the existing approval, for your own department? | Yes; ask this week. It is the difference between +4 weeks and −0.5 weeks of float on the CGMH critical path. |
| Q-12 | Where is your B200, can it run MIG, and who besides you can operate it? May an agent session reach it? | A script you or a named operator runs; no inbound access from cloud sessions. Name a second operator. Ask CGMH for two MIG instances (about 45 GB and 23 GB) and qualify those exact sizes on your machine. |

### 10.3 For what was promised and what is claimed

| # | Question | Recommended answer |
| --- | --- | --- |
| Q-14 | The amendments filed on 11-10 and the IT pack describe controls as present that are not built (opt-out "within minutes", daily signed audit heads, admin without patient data, break-glass, step-up signing). Do you tell the committees and IT now? | Yes: a short cover note now, "the controls marked * are in build and are verified at OQ before any patient data is used", with the commitments register. If a function is not ready at go-live, its flag stays off and the committee is told in writing. |
| Q-15 | Do you engage regulatory consultants in Japan and Taiwan this month for the non-device position, and keep the treating physician's own-patient view built last and switched off until their opinion? | Yes to both. The computed layers in that view are the weakest point of the non-device argument. |
| Q-16 | When the judge model is down during a night, what should happen? | Note judging stops for that run; those patients go to review as "unknown" with a visible alert. The verifier never stands in for the judge. |
| Q-17 | Should prompts and answers of patient calls be stored at all? Today the trace store keeps note text for 90 days by default. | No by default. A 24-hour audited debug switch only. |
| Q-18 | Which ingest stack is the product: the one that runs on the box (`adapter`) or the governed one that only tests use (`dataplat`)? | One stack. Move the contracts, the publish gate and the patient index of `dataplat` into the box's path before real data; do not ship two that make different pseudonyms. |
| Q-19 | The verifier weights come from a personal account, quantised by a third party; the verifier and the embedder are of PRC origin. Is that acceptable to both hospitals? | Make the quantised build yourselves from the official weights with a recorded recipe and hash; name the origin in the IT pack; ask both hospitals now; keep a second verifier candidate measured. |
| Q-20 | Break-glass for the admin: a second person before access, or a steward review after? Which time limit? | No second person; 60 minutes; the steward and the PI are told at once; steward review within 7 days. A second person only for a non-admin reveal outside the user's own lists. |
| Q-21 | The repository is public, master is not protected, and GitHub Issues are disabled. Do you protect master now, enable a problem log, and move TrialBox to its own private repository before site material and the PoC feedback arrive? | Protect master this week with the required checks of §7.5. Enable Issues, or keep `docs/validation/problems.csv`. Yes to a private repository of its own; until then nothing that names a tester, a host or a hospital contact is committed. |

### 10.4 The owner's answers of 2026-11-10

Given by the owner the same day, after reading the summary of this plan. They are decisions; the cards that waited on them may start.

| # | Answer | Effect |
| --- | --- | --- |
| Q-01 | **Yes.** Dr Makoto and Dr Wenn test themselves, about four hours each; the owner facilitates. | `27-poc-plan.md` §5 and §8 stand as written. |
| Q-02 | **Yes.** The assumed trial types are confirmed: early Alzheimer's disease for Japan, rheumatoid arthritis for CGMH. | T-503 and T-504 build the scenarios as proposed. The one-table study list (phase, EDC, registry) is still sent to both PIs; it no longer blocks the PoC. |
| Q-03 | **Approved.** The PoC host: one small cloud VM for two months (about US$110 a month, a price from memory to be checked at order) and a domain name. | T-509 may create it at the freeze. Each paid step is still shown to the owner before it runs. |
| Q-04 | **Yes.** The PI may start feasibility, screening and case runs on the PI's own studies. | T-512 is no longer pending; a separate tick for sub-investigators; daily limits unchanged. |
| Q-07 | **Yes.** The PoC is product evaluation, not research. The clinicians sign the acknowledgement only. | Recorded as a decision file by T-508 (number from the registry). Counsel reads the statement once. |
| Q-13 | **Yes** to both: recorded real-model answers may be shown with a label; step 2 (GP-2, real models on the owner's B200, January) is wanted. | T-515 stands; GP-2 is planned, after G1 and G1b. |
| Q-21 | **Protect master.** | The owner sets branch protection with the required checks of §7.5 (T-007). Agent sessions cannot change repository settings. The owner did not decide on a private repository or on enabling Issues: both stay open, and until decided nothing that names a tester, a host or a hospital contact is committed, and the problem log is `docs/validation/problems.csv` (T-654). |

Q-05, Q-06, Q-08 to Q-12 and Q-14 to Q-20 are not answered yet. The plan proceeds on their recommendations and records each as an assumption until the owner decides.

## 11. Assumptions this plan makes where the request was silent

The owner's request left these unsaid. Each is filled as stated; any of them can be overturned at G0.

| # | Unsaid | Assumed |
| --- | --- | --- |
| A-01 | Who decides that the PoC may start | The owner alone, at GP-0 and GP-1, on the go/no-go list of `27-poc-plan.md` §8.1. |
| A-02 | What "soon" means | Hands-on sessions in the week of 2026-12-08, with an optional guided first look on 12-02 or 12-03. Earlier is not safe: the demo does not start from a clean build, a password alone opens a session, and Japan's trial type has no scenario. |
| A-03 | The testers' time, devices and language | About four hours each; their own PC and phone; their own language; no installation. |
| A-04 | Whether the PoC may cost anything | A small cloud cost is acceptable if the owner approves it (Q-03). This review spent nothing and started no GPU. |
| A-05 | Whether PoC feedback can change the scope | Not by itself. It becomes cards for G2, G3 or after go-live; new scope needs a dated plan change. |
| A-06 | Which trial types are "the two sites' real trial types" | Early Alzheimer's disease (Japan) and rheumatoid arthritis (CGMH), from the design documents; to be confirmed (Q-02). |
| A-07 | Whether the PoC needs ethics review | No: product evaluation with clinicians as advisers, no patient data. Recorded as a decision (Q-07). |
| A-08 | Whether "full scope" means every feature used with a real patient on day one | No: Used, Drilled or Not applicable per site (§1.2). |
| A-09 | Whether the go-live dates may move | They are fixed targets. This plan names fallbacks and decision points but moves nothing. |
| A-10 | Who integrates | The integrator session keeps testing and merging. This review changed no product code and merged nothing. |
| A-11 | The fix groups D-270 to D-281 | They stay with their session. This plan lists them so nothing is lost and attaches new findings to them (LLM-002 to D-276). |
| A-12 | Card numbering | Existing cards keep their ids. New cards are T-501 onward (wave P) and T-601 onward. New decisions take numbers from D-300 through a registry; D-270 to D-289 stay with the fix groups. |
| A-13 | The severity scale | Blocker: patient safety, privacy breach, data loss, or it stops the PoC or go-live. Critical: a wrong result or a serious compliance gap with no workaround. High: fix before go-live. Medium: should fix. Low: polish. |
| A-14 | Lead times of hospital offices | Estimates from how such offices usually work in Taiwan and Japan. No office was asked. |
| A-15 | The repository's visibility | Public today (TB-DR-04 checked the API): no tester names, addresses, host names or session recordings enter it. |
| A-16 | The owner's B200 | A machine he controls, outside CGMH's network, that can run MIG. If it is inside CGMH's network, its use is part of the IT chain. |
| A-17 | Legal and regulatory statements in the review | The reviewers' reading, partly from secondary sources and marked where not confirmed online. Not legal advice: counsel and the regulatory consultants confirm (Q-15). |

## 12. Change history

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-11-10 | First issue (with the owner's answers to Q-01 to Q-04, Q-07, Q-13 and Q-21 of the same day, §10.4), from the deep review of 2026-11-10. Adds the PoC gate (GP-0, GP-1, GP, GP-2); redraws the critical path per site with float; defines "full scope" per site; reorganises the task list (wave P to wave L) with a conflict matrix; adds the standards compliance matrix, the dependency upgrade plan and the test strategy; lists the questions for the owner. |
