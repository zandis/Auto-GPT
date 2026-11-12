# TB-DR-10 The plan itself: is TB-PLAN-05 v1.2 realistic against today's state?

| Field | Value |
| --- | --- |
| Date | 2026-11-10 (Tue; W1 day 2 of the plan's clock) |
| Code read | `origin/master` at `ca8f287`; the 14 open PR branches by `git diff` and `git merge-tree` only (no checkout) |
| Documents read | `docs/plan/25-master-plan.md` (v1.2; §1 to §4, §6, §7, §11 line by line; §5, §8 to §10, §12 to §15 by headings and searches), `26-status-2026-11-10.md`, `25-vmp.md`, `25-traceability.csv` (status column), `reviews/2026-11-09-master-plan-independent-review.md`, `reviews/2026-11-09-assessment-and-tasks.md` (§1.4, §2.2, §3, §4), the critical register TB-REG-01 (§1, §5, §7.5), the two IRB amendment drafts, `snomed-inquiry.md` |
| Method | Read the plan against the status and the owner facts of 11-10; recompute the calendar (weekdays, working days per country); back-schedule each non-code chain from its hard date; measure merge throughput and PR sizes from git; compute a file-conflict matrix of the open PRs (real three-way merges) and of the open cards' "May touch" lists |
| What was run | `git log origin/master --merges --since=2026-11-01`; `git diff --shortstat/--name-only <merge-base> <branch>` for PRs #64, #66, #68, #70, #71, #73, #75, #76, #78, #80, #82, #83, #85, #86; `git merge-tree --write-tree` for each PR against master and for each PR pair (91 pairs); a Python date script (weekdays, working days with JP and TW holidays); a parser over the 67 cards' "May touch" and "Size" fields. Scripts and outputs: the session scratchpad, folder `plan-realism/` (`matrix.py`, `matrix.out`, `cards.py`, `cards.json`) |
| What was not run | No tests, no Docker, no GPU. No site fact was checked with a hospital: every IRB, contract, IT and vendor lead time below is a reviewer estimate with its reasoning, not a quote. The 2027 public-holiday calendars of Taiwan (DGPA) and Japan (Cabinet Office) were **not** looked up online; dates marked "confirm" rest on the holiday rules as I know them. Hardware prices and stock were not checked |

## 1. Summary

The plan is a good document and a wrong schedule. Its own sentence is right: "Six chains decide the dates. None is code." Today five of the six chains have not started, one (IRB) started ten days early, and three owner facts changed under it (one spot GPU, the owner's B200 instead of a rented one, a new PoC gate). The code is ahead; the calendar is behind.

Verdict: **CGMH 2027-04-28 is reachable only if the HIS export build starts before the IRB approval and the contract (it is planned in parallel but will run in series), and the contract chain starts this month. Japan 2027-05-13 has zero float on three chains (contract, hardware, feed notes) and sits one working week after Golden Week and six weeks after the fiscal-year turnover.** At P50 lead times both dates hold with 0 to 4 weeks of float; at P90 both miss by 2 to 6 weeks. TB-PLAN-06 should keep the two dates as targets, name a fallback date per site now, and move four decisions earlier.

Counts: **Blocker 5, Critical 5, High 20, Medium 17, Low 4 (51 findings, PLAN-001 to PLAN-051).**

Top 5:

1. **PLAN-001 (Blocker)** The true critical path at CGMH is IRB approval → HIS export build → tier 3 notes; the plan runs them in parallel. In series the float is −0 to −6 weeks.
2. **PLAN-002 (Blocker)** Contracts not engaged at either site. Latest start for the plan's own "2 to 4 months" was W1; at 4 months the CGMH hard date 03-12 is already missed by a week, Japan 03-26 has 2 weeks.
3. **PLAN-003 (Blocker)** One person holds every role that decides, signs, pays, hosts and reviews (owner, sponsor, Study A PI, CGMH steward, Aimedics operations, contract counter-party insider, B200 owner, cloud and repository admin). No deputy, no conflict-of-interest ruling, no named second human on the safety core.
4. **PLAN-004 (Blocker)** Gate G1 and every later model-level check now queue on one spot GPU (about 9 h per 50k run, pre-emptible). The plan still says "parallel capped VMs". No pre-emption budget, no GPU-hour queue.
5. **PLAN-005 (Blocker)** The new PoC gate has no place in the plan: no entry and exit criteria, no date, no data rule for what a clinician may type into a hosted demo, and the console still says "excluded" 132 times, which the plan itself forbids.

## 2. Findings

Severity follows the brief. "PoC path = yes" means a clinician on the hosted demo would meet it, or the PoC cannot be held without it.

### 2.1 Critical path and dates

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-001 | Blocker | **CP-4 and CP-5 are in series at CGMH, not parallel.** The plan lets the 資訊室 HIS team build an identified, all-department, nightly export with notes from W2, while the IRB amendment that permits that data use is approved in December to February and the contract is signed 02-26 to 03-12. A hospital IT team does not spend hours on an identified extract for a vendor before the approval and an internal work order exist. In series: approval P50 12-22 + 3 months build (the plan's own number) = tier 3 on about 03-22 (plan: 03-19); P90 02-12 + 4 months = June. | by reading: plan §4.3 CP-5 "3 to 4 months for a hospital HIS team", "W2 (scope), W4 (signed dates)"; §4.0 tier dates 02-12, 03-05, 03-19; WS-11.10 has no hospital owner yet (CR-092, status §1 "Behind") | (a) This week the owner files the internal HIS work request **under the existing approval** for tier 1 (the PI's own department, structured data), so the build of the export mechanism starts now; tiers 2 and 3 are switched on when the amendment is approved. (b) TB-PLAN-06 draws CP-4 → CP-5 as one chain with the dependency shown. (c) A named HIS owner and a first weekly check-in by 11-20, or the CGMH fallback date is announced at G1. | registered CR-092 (owner missing); the series dependency is new | no |
| PLAN-002 | Blocker | **Contracts: the latest start has passed or passes this month.** Plan: 2 to 4 months, drafts on the hospitals' templates by 11-20, with legal by W2. Fact 11-10: not engaged. Back-schedule: CGMH signed by 03-12 → start by 01-12 (2 mo), 12-12 (3 mo), **11-12 (4 mo)**, with the Lunar New Year week lost in February. Japan signed by 03-26 → 01-26 (2 mo), **11-26 (4 mo)**; a first contract with a foreign vendor that touches identified data is more often 4 to 6 months, and it lands in 年度末. | by reading: plan §4.3 CP-3, WS-10.1, WS-11.1 acceptance "contract draft … with legal by W2"; status §1 "Behind", §5 item 3 | The owner sends the request for each hospital's template and names the hospital-side signer **this week**; TB-PLAN-06 records the start date as evidence at G0. For Japan see PLAN-009 (fiscal year). For CGMH see PLAN-003 (related-party review adds weeks). | registered CR-091; latest-start arithmetic is new | no |
| PLAN-006 | Critical | **Japan hardware has no float and can gain four weeks for free.** Order 01-08 → on site and registered 03-12 is 9 weeks; the plan's own lead time is "8 to 9 weeks from the order", through Lunar New Year if the box is pre-installed at Aimedics in Taiwan (W15), then shipping and customs. The 01-08 date exists only to wait for a 14-night Spark benchmark that needs arm64 images (card T-214, planned W6 to W9) and a Spark that is "not confirmed" bought. | by reading: plan §1.6, §4.2 W7 "14-night run begins", W15, §4.3 CP-1; status §4 row 11-13; card T-214 in wave 2 | Decide the form **by 12-18 from numbers already in hand**: the G1 run gives tokens per second and pairs per hour on the RTX PRO 6000; the Spark's published throughput for a 26B model is a fraction of that. If the estimate fails the "screening night fits with 30 % headroom" threshold by a wide margin, order Form B in December and keep the Spark (if bought) as the PoC and demo machine. This removes T-214, WS-14.9 and the two-device IQ from the go-live path (about 12 sessions) and files the device registration before 年末年始. | new | no |
| PLAN-007 | Critical | **Hospital IT is not engaged; at P90 the latest start is this week.** CGMH: first meeting → security review and scan (est. 4 to 10 weeks) → namespace, MIG partition, storage, network policy (1 to 4 weeks, plan) must end 02-26. Back-schedule with the New Year week: P50 start 12-25, P90 start **11-13**. Japan: the device cannot be registered until its form is known (01-08), leaving 9 weeks for a review that can take 4 to 12 with a monthly 医療情報システム委員会. | by reading: plan §4.3 CP-2 "2 to 6 weeks each, some in series", "first meetings by 11-20"; WS-11.1 "the IT meeting by W3"; status §1 | Book both first meetings by 11-20 with the IT pack draft as it is; at Japan file the registration for Form B in December (PLAN-006). Record the meeting date as G0 evidence. | registered CR-090 (hospital-side actions, OD-10) | no |
| PLAN-008 | High | **The amendments were filed (good) before the design was stable (risk).** Filed 11-10 from drafts dated 11-09 v0.1. The same day the owner decided break-glass access for the vendor's administrator (#74). Neither draft mentions break-glass. The PoC may also change the design. A second amendment costs another 4 to 8 weeks and would hit the hard dates. | by a run: `grep -c -i 'break-glass\|緊急存取\|ブレークグラス' docs/plan/sites/irb-amendment-*.md` → 0 and 0; drafts' header "Version 0.1 draft (2026-11-09)"; status §2.3 "T-309 break-glass (owner decision #74)" | Diff the filed text against decisions D-144 to D-207 and #74 now; if break-glass or any later change is outside the filed text, send a supplement **before** the first committee meeting, not after approval. Add a rule to TB-PLAN-06: no design change that widens data use after 11-30 without the PI's check against the filed text. | new | no |
| PLAN-009 | High | **Japan's fiscal year turns on 04-01, in the middle of Japan IQ/OQ (03-22 to 04-09).** Staff rotate (医療情報部, the trial office, residents, CRCs), the 病院長 or the committee chair may change, contracts and budgets are per 年度. The Japan hard date 03-26 is in the busiest week of the year; a contract that starts 04-01 is the normal shape. The VMP must be signed "by each IT lead" before IQ; a new IT lead on 04-01 re-opens it. The plan lists holidays but not the turnover. | by reading: plan §4.0 rows 03-22 to 04-09 and 03-26; `25-vmp.md` §8; a search of the plan for "年度", "fiscal", "rotation" finds only unrelated lines | Ask Makoto now who rotates. Plan the Japan contract to take effect 04-01 with the signature circulated in February; move "OQ on real data" to start 04-01 or later (see the corrected calendar); sign the VMP with the people who will be there in April; train after the orientation week. | new | no |
| PLAN-010 | High | **"Two weeks of slack per site" does not exist on the calendar.** CGMH: PQ ends Fri 04-23, G6 is the same day, go-live Wed 04-28 (2 working days later). Japan: PQ ends Wed 05-12, G6 the same day, go-live Thu 05-13 (0 days). | by reading: plan §4.4 "two weeks of slack between the end of each PQ and the go-live" and "keeps two weeks of slack per site"; §4.0 rows 04-23, 04-28, 05-12, 05-13 | State the truth: float 2 days and 0 days. Either shorten PQ on purpose or name the fallback dates now (PLAN-014). | new | no |
| PLAN-011 | High | **"Four weeks of PQ" is 18 and 19 working days, and Japan's PQ is cut in two by Golden Week with only 5 working days after it.** CGMH 03-29 to 04-23: 18 working days if 04-05 and 04-06 are both off. Japan 04-12 to 05-12: 19 working days counting Fri 04-30 (a working day between holidays, when many staff take leave), 13 before the break and 5 after. A deviation found before the break cannot be closed and re-run after it. | by a run (date script): `CGMH PQ 03-29..04-23 wd 18`; `JP PQ 04-12..05-12 wd 19`; `JP wd 05-06..05-12 5` | Write PQ length in working days (proposal: 18 at CGMH, 18 at Japan) and define which PQ journeys must be run after the break. | new | no |
| PLAN-012 | High | **CGMH go-live day is followed by a probable three-day weekend, and the first two weeks overlap Japan's Golden Week and Japan's last PQ week.** If Labour Day (Sat 05-01) is compensated on Fri 04-30, the first morning mail is Thu 04-29 and the hospital is then closed three days. The plan says "Labour Day … one day". The same owner is CGMH PI and steward in hypercare (04-28 to 05-12) and approver of Japan's G6 on 05-12. | by reading: plan §4.0 row 04-28; rule PR-06 in §4.0; §4.5 "hypercare rota by name"; the holiday rule is from memory → **confirm** with the DGPA 2027 calendar | Confirm 04-30. If it is off, either go live Mon 04-26 (PQ then ends Thu 04-22) or accept and staff 04-29 by name. Name a deputy for Japan's G6 (PLAN-003). | new | no |
| PLAN-013 | Medium | **Holiday facts to correct or confirm.** (a) Lunar New Year: the plan has 02-05 to 02-10; if 小年夜 (Thu 02-04) is a holiday the break is 02-04 to 02-10, seven days. (b) 清明: the plan pauses PQ on Mon 04-05 only; Children's Day falls on Sun 04-04 and is normally compensated, so Tue 04-06 (or Fri 04-02) is likely off. (c) Fri 2026-12-25 (行憲紀念日) is not on the calendar. (d) Japan's 年末年始 at hospitals is 12-29 to 01-03, which the plan has; committees often hold no meeting from mid-December to mid-January. (e) Header says "Japan Fri 2027-05-14"; §1.4, §4.0 and §4.1 say Thu 05-13. | by reading: plan line 14 vs lines 52, 425, 442; §4.0; items (a) to (c) are from the holiday rules as I know them → **confirm** | Put the calendar in one data file (`docs/plan/calendar.yaml`) with a source URL per holiday and a test that every date in the plan has the weekday the plan prints. Fix the header. | P-35 in TB-ASSESS-01 registered item (e); the rest new | no |
| PLAN-014 | High | **No fallback date is named.** The plan says a late chain moves the date "week for week" and the scope never moves. It names no second date, so a slip will be discovered at G4, when rooms, CRCs and trainers are booked. | by reading: plan §4.4 "Fallback" column: "move week for week" | Name them now: CGMH fallback **Wed 2027-05-19** (PQ extended, clear of Dragon Boat on Wed 06-09 by 14 working days; confirm); Japan fallback **Thu 2027-05-27**. Decision points: at G1 (12-04) for chains not started, at G2 (01-08) for IRB and hardware, at G3 (02-26) for contract and tier 1. | new | no |
| PLAN-015 | Medium | **Go-live order and gap.** 15 days between the two go-lives, with Golden Week inside, means the Japan release cannot learn from CGMH's first week (the release is frozen from G3, and Japan's G6 is before CGMH hypercare ends). | by reading: plan §4.0, §4.2 W25 to W27 | Keep the order. Add one rule: a Severity-1 finding in CGMH hypercare week 1 stops Japan's go-live automatically; the owner lifts the stop in writing. | new | no |
| PLAN-016 | Medium | **§7.3 and other rows still carry the February calendar.** "IQ, appliance (Japan, W10, half a day)" and "IQ, hospital platform (CGMH, W10, one day)" while §4.0 has IQ in W19 to W20. | by reading: plan lines 738 to 739 vs 416 to 417 | Rewrite §7.3 from the calendar data file. | new | no |

### 2.2 The changed owner facts

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-004 | Blocker | **One spot GPU breaks WS-02.1, WS-02.6 and every "re-run with the pair".** The plan's G1 is "split across parallel VMs"; its G1 mitigation is "parallel capped VMs". Fact: quota 1, spot only; the 50k run is about 9 h on a VM that can be pre-empted at any minute. The same single GPU must also serve: the short run, the profile-cost and embedding tests ("both VMs"), the judge bake-off with the 31B challenger (#64), `qualify` after every prompt or model change (T-012, T-101), the injection suite against the pair (T-208), the G1 re-run on the release (W17) and the PoC if it shows live model output. That is at least 6 long runs before G3 with no queue and no budget of attempts. | by reading: plan WS-02.1, WS-02.6, §4.2 W4 and W17, §4.4 row G1; status §4 row 12-04 "about 9 h"; brief owner facts | (a) Rewrite WS-02.1 for one VM: stage-level checkpoints, `--resume` proven by a **forced pre-emption in the rehearsal**, a stated budget of three attempts (11-24, 11-27, 12-01) before 12-04. (b) Use the owner's B200 for the 50k functional run (no pre-emption, no cost) and keep the spot VM for the `rtxpro6000` tier record (serving record, canary, N-12, 5k): G1 = G1-functional + G1-tier. (c) Keep a GPU-hour ledger in the status file: run, hours, who waits. | registered CR-069/CR-070 (G1 never passed, quota); the single-GPU queue is new | yes (if the PoC shows live results) |
| PLAN-017 | Critical | **G1b on the owner's B200 is a different test from the one the plan wrote, and nothing says how an agent reaches that machine.** WS-02.7 is a cloud VM that agents drive with `gcloud`, with "a MIG instance matching the partition requested from CGMH". The owner's B200: where is it, who operates it, can it be put in MIG mode, which driver and CUDA, may a cloud agent session reach it? If the owner must run each step by hand, G1b costs owner hours that the capacity check does not have. If it stands inside CGMH's network it falls under CP-2. The MIG profile CGMH will grant is still unknown (survey question 51), so "the same profile" cannot be claimed. | by reading: plan WS-02.7, §4.1 G1b "with the MIG profile CGMH will grant", WS-11.8 "serving record from the cloud B200 qualification as the entry condition"; card T-114 "needs the rental window"; brief owner facts | Rewrite WS-02.7 / T-114: an offline bundle and one script the owner (or a named operator) runs, which writes the `shared-quota` record and a host fingerprint (GPU, driver, CUDA, MIG layout); qualify on **two** MIG layouts (the smallest that fits the pair and one larger) so CGMH's answer is covered either way; state in the record that the host is not CGMH's. Make the same machine the standing acceptance cluster for WS-14.8, WS-13.9 and T-319 (it removes CR-071 for the CGMH form). | new | no |
| PLAN-018 | High | **The plan's hardware and money lines are stale.** §1.4 "Rent a cloud B200 in weeks 3 to 5"; W3 "cloud B200 rental window opens 11-23"; WS-14.1 "rent an RTX PRO 6000 workstation from W2 as the acceptance box" (not ordered; identity, hardening and pentest pass 1 in W6 depend on it); WS-14.8 "or the rented cloud B200"; G1 budget "about US$50 … parallel VMs". | by reading: plan lines 56, 139, 144, 311, 313, 399, 452 to 455; status §1 "Behind: the Spark and the rental" | TB-PLAN-06 rewrites §1.4 rows "B200 qualification", "Japan hardware", "Interim hosting"; decides whether the rental workstation still exists (if not, pentest pass 1 and Windows hardening T-210 have no hardware before the Japan box arrives in February: say so and move them). | new | no |
| PLAN-005 | Blocker | **The PoC gate is not in the plan.** No gate between G0 and G1 (or G1 and G2) names two clinicians, a hosted demo, three languages and three roles. Missing: entry criteria, exit criteria, a decision rule for a bad result, who the two clinicians are, what build they see, whether results are live or pre-computed, and what happens to their feedback. Without them the PoC is a demo, and a demo that goes badly re-opens scope in December. | by a run: `grep -c -i 'PoC\|hosted demo' docs/plan/25-master-plan.md` → 1 (WS-02.5, hygiene only); status file → 0 | Add gate **GP** (§4 below) with a PoC work item (WS-19) and cards (§6). | new | yes |
| PLAN-019 | Critical | **A clinician can type or upload real patient text into a cloud-hosted demo.** The console takes pasted chart text and PDF charts (CASE jobs, chart upload). The data rule forbids real data in a PoC; nothing technical stops it on the hosted demo. | by reading: plan WS-01.7 "A PDF chart with CJK text stores its facts" (upload exists); WS-13.10 covers the repository, CI and logs, not demo input; brief "Never real patient data in … a PoC" | On the hosted demo: switch chart upload and free-text chart paste off behind a flag, or accept only the built-in synthetic charts; a banner in three languages ("demonstration data only; do not enter patient information"); one line in the PoC protocol that each clinician signs; the identifier scan run over the demo's stored input after each session. | new | yes |
| PLAN-020 | High | **The PoC would show clinicians words the plan forbids and behaviour that no gate has proved.** "Excluded / 除外 / 排除" appear 132 times in the console and the rename (T-116) is planned for W6 to W7. The stub can never exclude a patient, so a stub-backed PoC shows no "criteria not matched" case; the real pair has never passed G1. | by reading: TB-ASSESS-01 P-33 (132 occurrences, 0 of the new words), P-34 (b); card T-116 in wave 2 slot A; CR-003, CR-069 | Pull T-116 into the PoC prerequisites. Load the PoC site from the **G1 short run's stored results** (real pair, 5,000 synthetic patients) so no live GPU is needed during a session and model exclusions are visible. | card T-116 covers (move earlier); registered CR-003/CR-069 | yes |
| PLAN-021 | Medium | **Is the PoC research?** If the two clinicians' answers are only product feedback, no committee is needed. If they are to be reported as evidence (usability, time saved), the clinicians are participants. The plan has no line either way, and the owner is the PI. | by reading: no PoC text in the plan; WS-16.2 (workload baseline) is the nearest item | Record in DECISIONS: the PoC is formative product evaluation on synthetic data, not research; nothing from it is published or used as a claim (RSK-34). | new | yes |
| PLAN-022 | Medium | **IRB filed early is not yet evidence.** The plan's acceptance is "filed by 11-20 with a receipt"; the status file (written 09:00 UTC) still says "filing is the owner's". No receipt number, committee, meeting date or submission deadline is recorded anywhere. Without the meeting dates CP-4's float cannot be computed. | by reading: plan WS-10.10, WS-11.11 acceptance; status §4 row 11-20 | Record per site: date filed, receipt id, review type (expedited or full board), next meeting date, the date an answer is expected. No patient data is involved, so this can live in `docs/plan/sites/`. | new | no |

### 2.3 Gates

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-023 | High | **G0 has no evidence and is due in three days.** "The W1 actions started" names seven actions; none has an artefact, a date or a signer. The status file reports them "not confirmed done". A gate that cannot fail is not a gate. | by reading: plan §4.1 G0; status §4 row 11-13 | A gate record per gate: `docs/validation/gates/G<n>.md` with one row per criterion: measure, evidence path or reference, result, signer, date. `docs/validation/` does not exist today. G0 is re-held on 11-13 as "G0 of TB-PLAN-06" with the seven actions each marked done (with the date) or dated. | new | no |
| PLAN-024 | High | **G1 and G2 are "decided by … the safety-core engineer", who is to be named "by design freeze" (G2).** G1 cannot be signed as written; G2 is the gate at which its own signer is first named. | by reading: plan §4.1 rows G1, G2 "Decided by"; WS-17.5 "named by design freeze"; `25-vmp.md` §8 "(to be named by design freeze)" | Name an interim independent reader for G1 (any engineer or clinician who is not the owner) or change G1's signer honestly to "the owner alone, residual recorded". Make "engineer named and under contract" a G1 exit criterion, not a G2 one. | registered CR-080 / OD-9 (no second reader); the gate-signer contradiction is new | no |
| PLAN-025 | Medium | **G1's criteria are measurable; three are missing.** Present: false exclusions 0, precision ≥ 0.90, recall ≥ 0.70, `unprocessed = 0`, VMs `TERMINATED`. Missing: (a) which commit (a tag or sha on master, with CI green); (b) wall time and pre-emptions (needed for PLAN-006's hardware estimate and for night-window sizing); (c) the register condition: no open Blocker on the screening path at the commit that runs (CR-001, CR-002, CR-005 to CR-007 change what the run measures). | by reading: plan WS-02.1 acceptance; TB-REG-01 §1.2 items 1 to 3 | Add the three to G1. Hold G1 on a commit that contains fix groups D-275 and D-276. | new | no |
| PLAN-026 | Medium | **G1b's criterion cannot be evaluated**: "the MIG profile CGMH will grant" is unknown until survey question 51 is answered and the partition is "confirmed in writing" on 01-08, four weeks after G1b. | by reading: plan §4.1 G1b; WS-11.1 "confirmed in writing by W8" | See PLAN-017: qualify two layouts; G1b passes on the record; the match with CGMH's layout is checked at G2. | new | no |
| PLAN-027 | High | **G2 lists about 15 conditions and no evidence; several cannot be met by 01-08 at the current state.** FS per workstream (17 documents; card T-215 is wave 2, not started), URS approved by two clinicians, the matrix in enforce mode (all 264 rows are "planned"), the Spark decision (PLAN-006), both surveys signed (no contact confirmed), the engineer and second reviewer named, identity "on the rental workstation" (no rental), and the status file's own addition: every Blocker and Critical of the register closed. | by a run: `awk` over `25-traceability.csv` status column → 264 `planned`, 0 other; by reading: plan §4.1 G2; status §1 "Target" | Split G2 into G2a "platform freeze" (code and CI items, evidence = merged PRs and CI) and G2b "site and people freeze" (surveys, hardware order, names, VMP draft), each with its record. Let the generator write `status` and `evidence` from merged work so "enforce mode" means something. | new | no |
| PLAN-028 | Medium | **G3 "every code item merged" has no list.** The plan's WS rows, the 67 cards, 86 open register rows and this deep review's cards are four lists. | by reading: plan §4.1 G3; TB-ASSESS-01 §4.1; TB-REG-01 §7.5 | One backlog file generated from the cards (id, WS, gate, state, PR); G3 passes when its "gate ≤ G3" rows are all merged and the register has 0 open Blocker, Critical and High. | new | no |
| PLAN-029 | Medium | **G4 to G6 are well specified** (protocols, thresholds, non-waivable list), but G6's signers include the same person three times (owner, CGMH steward, Study A PI) and "both PIs"; see PLAN-003. | by reading: plan §4.1 G6, §4.5; `25-vmp.md` §2 | Add the deputy and the COI ruling to the G6 non-waivable list. | new | no |

### 2.4 Capacity

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-030 | High | **The plan's capacity check measures the wrong thing.** It compares 324 agent sessions with "4 to 6 agents × 80 days". Observed: agents are not the limit. On 11-09 and 11-10 the integrator merged 18 and 20 pull requests a day (first-parent merges; median about 2,500 added lines and 26 to 40 files each). The same two days produced a register of 115 Blocker, Critical and High rows, 86 still open. Merge speed outran verification. | by a run: `git log origin/master --first-parent --since=2026-11-01` per day → 3, 7, 9, 18, 20; `git diff --shortstat` per merge (e.g. #77 9,466+, #61 8,974+, #58 7,077+, #62 5,722+); TB-REG-01 §7.5 | Replace §4.6 with the model in §5 below: verified merges per day, owner hours per week, GPU hours, and finding inflow vs fix rate. | new | no |
| PLAN-031 | Critical | **The owner's hours are spent before any code review.** The plan gives the owner 14 h a week and assumes site work falls "mostly after G3". The six chains are all owner work now. My count for 11-10 to 12-25 (7 working weeks): WS-11.1 engage and contract 14 h, WS-11.2 survey 6, WS-11.10 HIS export 10, WS-11.11 IRB follow-up 8, WS-11.12 second reviewer 4, half of WS-15.1 to 15.3 about 13, WS-13.6 privacy documents 4, WS-16.1 Study A 5, the engineer search 6, the G1b runs on his own B200 8, the PoC (prepare, two clinicians, review) 10, reading this review and approving TB-PLAN-06 8, run approvals and branch protection 3: **about 100 h, or 14 h a week, with zero left for the "about 155 hours" of build review** the plan counts on. He is also "the Aimedics operations person … until then Changfu". | by reading: plan §3 "Who the humans are", Totals paragraph, §4.6; R cells of WS-11, WS-15, WS-16; my additions are marked | Say it in the plan. Then: (a) name the Aimedics operations person now (orders, contracts, insurance, pentest booking): this is the cheapest hire in the plan; (b) the safety-core engineer from December, not "by G2"; (c) delegate the survey to the trial office and IT (the plan already says so); (d) the owner reviews one page per decision, never diffs. | registered CR-080 (review); the hour count is new | no |
| PLAN-032 | High | **Remaining agent work fits, with margin, only if the inflow of findings stops growing.** Cards: 67 = 104.5 sessions by the cards' own sizes (S 0.5, M 1, L 2.5). Done 8 cards (8 sessions); in open PRs 5 (8); running 4 (7); partly merged 2 (3.5); **not started 48 (78 sessions)**. Add: register rows not inside a card (about 25 sessions: nine fix groups plus owner-independent rows), this deep review (unknown; assume 40 to 80), site configuration and documents (about 20). Total to G3: **about 170 to 210 sessions**. Working days to G3: 72 (Taiwan) or 65 (minus both countries' holidays). At a verified rate of 3 to 4 merges a day (PLAN-030), capacity is 195 to 290. It fits at P50 and fails at P90. | by a run: `cards.py` → `done 8 … 8; inpr 5 … 8.0; running 4 … 7.0; partly 2 … 3.5; notstarted 48 … 78.0; all 104.5`; date script → `TW wd to G3 02-26 72 … union-holiday wd 65` | Hold a code-finding budget: after TB-PLAN-06, new Medium and Low findings go to a post-go-live list by default; only Blocker, Critical and High enter the G3 backlog. Review the count weekly in the status file. | new | no |
| PLAN-033 | High | **One integrator is a single point of failure and the queue is already stale.** 14 PRs are open with about 55,000 added lines (about 26,000 without #71, which is superseded, and #80's catalogue data). 9 of 14 conflict with master today; 9 are 49 to 105 commits behind. Every merge makes the others staler. | by a run: `matrix.out` "VS MASTER": #66, #68, #76, #80 conflict on `docs/DECISIONS.md`; #75, #82, #83 on `libs/tb_contracts/generated/models.py`; #85 on `docs/RUNBOOK.md`; #71 on 35 files; `behind=` 15, 15, 96, 105, 37, 96, 72, 60, 49, 91, 49, 49, 49 | Land T-002 first (decisions as files) and stop committing the generated `models.py` by hand (regenerate in CI and at merge). Merge in the order of §7.3. Name a second integrator session with the same rules, or a written hand-over, so the queue survives one session ending. | registered P-31, P-39 (TB-ASSESS-01), CR-077; the measured queue is new | no |
| PLAN-034 | Medium | **Session-to-session dependencies are held in one status file updated "at G1".** Four sessions hand back to the integrator this week (critical-issues, seven tasks, wave 1, this review). The next status update is 3.5 weeks away. | by reading: status header "the next update is due at G1"; §3 | Weekly status (Fridays), generated where possible (cards, PRs, register counts, GPU ledger, owner chains). | new | no |
| PLAN-035 | Medium | **The 324-session and 388.5-hour totals no longer describe the work.** Cards say about 105 sessions; the plan says 324; the difference is explained in TB-ASSESS-01 as "the plan's generosity". Two numbers for one thing will be quoted against each other. | by reading: plan Totals; TB-ASSESS-01 §4.1 last paragraph | TB-PLAN-06 keeps one number: the backlog file's. | new | no |

### 2.5 Risks, single points of failure, scope

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-003 | Blocker | **Bus factor 1 and an unruled conflict of interest.** One person is: vendor owner and approver; Study A sponsor and PI; CGMH employee, site PI, site contact and data steward; holder of the cloud project, the repository admin rights, the G1b B200 and the purse; negotiator of a contract between his company and his hospital; signer of the residual risks. RSK-47 covers only validation independence (a second reviewer co-signs) and claims residual P1. RSK-14 names a human safety-core owner who does not exist. There is no risk row for "the owner is unavailable for three weeks", no deputy for any role, and no COI ruling from CGMH (a related-party contract normally needs one before 法務 will proceed, which sits on CP-3). | by reading: plan §3 "Who the humans are"; §6 RSK-14, RSK-47; `25-vmp.md` §2; TB-REG-01 OD-2 (Study A COI), OD-9; `grep` of the plan and site documents for 利益衝突 / 利益相反 / "conflict of interest" → 0 | (a) A written COI disclosure to CGMH and its ruling, requested this week (it gates the contract). (b) Someone other than the owner signs the contract for Aimedics or for the CGMH side of the project. (c) A deputy per role in the plan: an independent co-investigator for Study A, a CGMH steward who is not the owner for go-live decisions, a second repository and cloud admin, a second person who can run the B200. (d) New risk rows RSK-53 and RSK-54 (§6). | registered CR-087 / OD-2 (Study A only), CR-080; the contract COI, the deputy list and the missing risk row are new | no |
| PLAN-036 | High | **A hospital security review may refuse the verifier because of its origin.** The verifier (Qwen3.5-9B) is a PRC-origin model. Taiwan restricts PRC-made information products in government bodies, and critical-infrastructure hospitals often follow the same line in vendor reviews. The plan dates "a second model pair for a non-PRC-model tier" to P2 "only on a written request". If 資訊室 asks in January, qualifying a new verifier needs a full `qualify` cycle on the single GPU. The survey and the IT pack do not ask the question. | by reading: plan §1.3, WS-18.5; by a run: `grep -c -i 'PRC\|陸製' site-survey.md it-security-pack.md` → 0, 0. Whether CGMH applies such a rule is **unknown** | Ask both sites this month (one survey line). Keep a non-PRC verifier candidate in the judge bake-off harness (#64) so a record exists before G2. | new | no |
| PLAN-037 | High | **The Japan box: who buys it, where, and who owns it.** The plan has "order → build → ship → customs → device registration" with Aimedics as buyer and a pre-install at Aimedics. Not covered: buying in Japan (domestic warranty and on-site service) vs importing (the power supply needs the PSE mark; radios need 技適; an importer of record; consumption tax; export rules for high-end GPUs leaving Taiwan to be checked); who owns the asset inside the hospital (a free loan normally needs the hospital's 無償貸借 or 寄附 procedure, which is its own approval chain). | by a run: case-sensitive `grep -c 'PSE\|電気用品\|技適'` in the plan → 1 hit that is not about this; `grep -c '無償\|寄附\|借用\|貸与'` in plan, survey, IT pack → 0; by reading: plan §4.3 CP-1, WS-14.1 | Decide: bought in Japan from a domestic vendor, delivered to the site or to Makoto, installed from the offline media on site. Add survey questions: asset ownership and the loan procedure. Add the chain to CP-1 with its own latest start. | new | no |
| PLAN-038 | High | **"Full scope" is not defined per site, so nobody can say whether a slip breaks it.** §1.1 lists nine items "at both sites", but several cannot apply to both: Windows/WSL2 hardening (Japan only), shared-host isolation and the KEK unseal (CGMH only), SS-MIX2 and JLAC10 (Japan), NHI codes and ROC dates (CGMH), REDCap ("where the pilot studies use it"). "Used with real patients … not demonstrated" cannot hold for the SAE clock (needs an SAE), monitor SDV (needs a monitoring visit), opt-out (needs an opt-out), break-glass. | by reading: plan §1.1 and its last paragraph; WS-11.4; WS-13.2; WS-13.9 | Define full scope per site in a table (§8 below): **installed, qualified (OQ) and switched on**, plus **used in PQ** where a real event exists, plus **drilled** where it does not. | new | no |
| PLAN-039 | High | **Work that can be dated later without changing what a user sees on go-live day.** These are built but off, or run on synthetic sites only, or are internal: setpoints and the gap finder (flags off by default), the clinician view of them (flag off until the regulatory views exist), Studies C and D drafts, the consortium (WS-09: synthetic sites only), HAPI out of the nightly path (internal), WebAuthn and AD (already a 60-day item), Define-XML and the ISF bundle, the 500k projection, 157 phenotype definitions (already later), the two-device form if Form B is chosen (PLAN-006), specialty templates beyond the pilot studies' specialties. Together about 30 to 35 sessions and several risk rows (RSK-08, RSK-11). The plan's rule "no item ships dark" blocks this even where the item ships **off**. | by reading: plan WS-05.5 "flags off by default", WS-05.6 "behind a flag off by default", WS-09 "on synthetic sites", §4.4 row G3 "no item ships dark"; cards T-313, T-314, T-316, T-306, T-214 | Ask the owner (§10 Q4). Recommended: date T-313, T-314, T-316 and T-306 to the first post-go-live release; keep "patients like me", profiles and prefill in. This also shortens the IRB text that must be approved before PQ. | new | no |
| PLAN-040 | High | **The register's closure target is not in the plan and is not credible as dated.** Status: "every Blocker and Critical fixed by G2 prep (end of November), every High by G2 (01-08)". 18 Blocker and 6 Critical are open; 17 rows belong to the owner and the hospitals (contracts, IRB, feeds, hardware) and cannot close in November. | by reading: status §1; TB-REG-01 §1.1 owner table, §5 OD-10 | Split the target: code rows (Blocker, Critical by 11-27 = PoC freeze; High by G2) and owner or site rows (each with its chain's date). Put both in the gate records. | new | no |
| PLAN-041 | Medium | **Licences: SNOMED is not on the critical path; say so, and decide the fallback now.** The inquiry is drafted, not sent. Typical: MLDS registration and an affiliate licence answer in 1 to 4 weeks; a written fee quote can take longer. The plan already stores `*_concept_id = 0` without SNOMED, so go-live does not need it. MedDRA is not mentioned anywhere although the product has an SAE register and CTCAE data; if any pilot study or sponsor expects MedDRA-coded terms, the subscription (MSSO, and JMO for MedDRA/J) is a further lead time. Whether either country now holds a national SNOMED licence was "checked on 2026-11-09: neither"; I could not re-check. | by reading: `snomed-inquiry.md` header; plan WS-03.4, WS-15.3; by a run: `grep -c -i meddra` in plan, survey, IT pack → 0 | Send the SNOMED inquiry this week; record "go-live without SNOMED" as the default. Add one survey line: do the pilot studies need MedDRA-coded AE terms in TrialBox? If no, write "TrialBox stores verbatim terms; coding stays in the sponsor's system". | new | no |
| PLAN-042 | Medium | **Sponsor acknowledgement letters are a hidden chain.** Prefill is switched on per study only after the sponsor acknowledges in writing; letters are "drafted W6, sent W10". Sponsors answer in months. Full scope includes prefill "confirmed on a real record" in PQ. | by reading: plan §1.4 row "Sponsor acknowledgement", §4.2 W6 and W10, §4.1 G5 | Choose the PQ prefill study now: an investigator-initiated study whose sponsor is the site (the acknowledgement is then internal). Add the chain as CP-7. | new | no |
| PLAN-043 | Medium | **Pentest, insurance and counsel are not booked and have lead times.** Pentest pass 1 in W6 on a rental that does not exist; pass 2 on 03-01 to 03-12 needs a firm booked 6 to 8 weeks ahead; E&O and cyber insurance "bound before real data" (quotes 2 to 6 weeks); counsel letters in two countries. | by reading: plan §4.2 W1 "the pentest firm booked; insurance quotes", W6; WS-15.2; status §1 "Behind" | Add each to the owner-chain tracker with a latest start: pentest firm by 12-18; insurance quotes by 01-15; counsel engaged by 11-27 (it gates the contract annexes). | new | no |
| PLAN-044 | Medium | **Study A cannot start as planned and its PI is the vendor.** "Submitted when the first real snapshot exists" (about 03-19) with 740 to 1,040 clinician reader hours to fund; the register lists design Blockers (CR-095) and the COI (CR-087). It is a G6 checklist item ("Study A submitted at CGMH"). | by reading: plan WS-16.1, §4.5; TB-REG-01 rows CR-087, CR-095 | Keep "submitted" as the G6 item but make the independent co-investigator and the funding line G2b conditions. | registered CR-087, CR-095 | no |
| PLAN-045 | Low | **Hypercare ends 05-28 for both sites**, two weeks after Japan's go-live but four after CGMH's; the 5 % blind re-entry sample runs three months with no named owner after hypercare. | by reading: plan §4.0 last row; WS-16.4 | Name the owner of the weekly samples per site through August. | new | no |

### 2.6 The plan as a document

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-046 | High | **The traceability matrix says nothing has happened.** All 264 rows are `planned` although ten work items are merged. The plan promises "status … until a run writes passing, failing or waived". | by a run: status column of `25-traceability.csv` → `264 planned` | `gen_traceability.py` reads a small evidence file per WS item (PR, test path, date). | new | no |
| PLAN-047 | Medium | **Cards name files that do not exist, so the declared-file conflict check under-reports.** Six open cards may touch `tools/trialbox_doctor.py`; the file is `tools/trialbox/doctor.py` (already changed by PRs #68, #71, #85). | by a run: `ls tools/trialbox_doctor.py` → no such file; `ls tools/trialbox/doctor.py` → exists; `cards.py` → T-109, T-113, T-210, T-211, T-214, T-319 | Regenerate the cards' paths against master when TB-PLAN-06 is written; a lint that every "May touch" path exists or is marked "new". | new | no |
| PLAN-048 | Medium | **T-104 (the Postgres image) has no PR of its own and travels inside two others.** #82 (T-105) and #83 (T-111) share 14 files and conflict on 10 of them: `db.Dockerfile`, `images.lock`, `db-init/20-extensions.sh`, `tb_common/db.py`, `orchestrator/db_pg.py`, `test_migrations.py`, the D-204 decision file. | by a run: `matrix.out` row 82/83 `14/10`; "TOP FILES" lines listing `[82, 83]` | Land T-104 alone first; rebase #82 and #83 on it. Rule: a card's branch never carries another open card's commits. | new | no |
| PLAN-049 | Low | **#71 is dead weight in the queue**: 39 files, 10,134 lines, 35 conflicts with master, superseded by #77; its remaining fixes are to be "ported". | by a run: `matrix.out` "VS MASTER 71 1 35"; status §2.5 | Close #71 now; open the port as a small new PR. | new | no |
| PLAN-050 | Low | **The status file was stale within hours** (#81, #79, #65 merged after it was written; the IRB filing and the quota refusal are not in it). | by a run: `git log` shows `aa62b3c` (#81), `2d25240` (#79), `ca8f287` (#65) after the status commit `4a092dc` (#84) | Generate the PR and card tables; hand-write only the owner-chain rows. | new | no |
| PLAN-051 | Low | **The plan's risk register has no project-risk scale.** RSK-26 and RSK-27 use "S2 (to the project)" on a patient-harm scale and have no residual S. Schedule risks then look smaller than a wrong label. | by reading: plan §6 header and rows RSK-26, RSK-27 | Keep §6 for harm (ISO 14971). Add a short project-risk table with its own scale (weeks of slip). The delta in §6 below marks which table each row belongs to. | new | no |

## 3. Corrected calendar with gates

Targets kept: CGMH Wed 2027-04-28, Japan Thu 2027-05-13. Today is Tue 2026-11-10: 169 days (24 weeks + 1 day) to CGMH, 184 days (26 weeks + 2 days) to Japan; 112 Taiwan working days and 120 Japan working days. Dates marked ◆ are new or moved. "Confirm" = holiday to check against the official 2027 calendar.

| Date | Day | What | Evidence that closes it | Note |
| --- | --- | --- | --- | --- |
| 2026-11-10 | Tue | IRB amendments filed at both sites (done, 10 days early) | receipt id, review type, next meeting date per site (PLAN-022) | compare the filed text with #74 (PLAN-008) |
| ◆ 11-13 | Fri | **G0 of TB-PLAN-06**: plan approved; each owner chain has a start date or a dated promise | gate record G0 | COI disclosure sent to CGMH; HIS work request filed under the existing approval; contract templates requested from both hospitals; IT meetings requested; operations person and engineer search started |
| ◆ 11-20 | Fri | Latest P50 start for CP-2 and CP-3 at both sites; survey ① answers; second reviewer proposed; SNOMED inquiry sent; Spark: bought or dropped | owner-chain tracker | if contracts are not with hospital legal by 11-27, announce the fallback dates at G1 |
| 11-23 | Mon | 勤労感謝の日 (Japan) | | |
| ◆ 11-24, 11-27, 12-01 | | G1 attempt windows on the single spot VM (9 h each); the 50k functional run on the owner's B200 in the same fortnight | GPU ledger | three attempts budgeted |
| ◆ 11-27 | Fri | **PoC build freeze**: T-116 wording, PoC-path Blocker and Critical fixes (fix groups D-270 to D-278 and this review's PoC rows), demo hardening, upload off, pre-computed results loaded | tag `poc-1` on master, CI green | |
| 11-30 to 12-11 | | workload baseline at both sites (kept) | | needs the site contacts: at risk |
| ◆ 12-01 | Tue | PoC internal dry run by the owner in three languages and three roles | checklist | |
| 12-04 | Fri | **G1** (functional on the B200 + tier record on the spot VM) | gate record G1 with commit, wall time, pre-emptions, register condition | decision point 1 for fallback dates |
| ◆ 12-08 to 12-11 | Tue to Fri | **GP PoC sessions** with the two clinicians (earliest realistic: Wed 12-02, see below) | signed PoC protocol, task results, feedback forms | |
| 12-11 | Fri | **G1b** on the owner's B200, two MIG layouts | `shared-quota` record with host fingerprint | |
| ◆ 12-14 | Mon | **GP exit review** | gate record GP; a triaged list: fix before G2 / before G3 / after go-live | |
| ◆ 12-18 | Fri | **Japan hardware decision and order (moved from 01-08)**; Japan device registration filed; pentest firm booked | order confirmation; registration receipt | Form B unless the Spark estimate passes |
| 12-25 | Fri | 行憲紀念日 (Taiwan; confirm) | | |
| 12-29 to 01-03 | | 年末年始 (Japan); 01-01 both | | committees quiet mid-December to mid-January |
| 2027-01-08 | Fri | **G2a platform freeze, G2b site and people freeze** | two gate records | decision point 2; engineer and second reviewer already named (moved to G1) |
| 01-11 | Mon | 成人の日 (Japan) | | |
| ◆ 02-04 to 02-10 | | Lunar New Year (Taiwan; 小年夜 02-04, confirm) | | plan had 02-05 to 02-10 |
| 02-11 | Thu | 建国記念の日 (Japan) | | |
| 02-12 | Fri | Tier 1 at both sites | adapter report | only if the HIS build started in November (PLAN-001) |
| 02-23 | Tue | 天皇誕生日 (Japan) | | |
| 02-26 | Fri | **G3 feature complete** | gate record G3 from the backlog file; register 0 open B/C/H | decision point 3 |
| 03-01 | Mon | 和平紀念日 observed (Taiwan) | | |
| 03-01 to 03-12 | | pentest pass 2; G1 re-run on the release (one GPU: book it) | | |
| 03-12 | Fri | **Hard date CGMH**: contract, DPA, amendment approved; Japan box on site and registered | | |
| 03-15 to 03-26 | | **G4 CGMH** IQ, OQ, five nights, tier 3 on 03-19, dry run 03-22 to 03-26 | | 03-22 is a holiday in Japan only |
| 03-22 to 03-31 | | **G4 Japan** IQ on synthetic data and test projects | | 年度末: keep the load on the site light |
| ◆ 04-01 | Thu | **Japan contract and DPA in force (hard date moved from 03-26)**; new fiscal year; staff turnover | | signatures circulated in February |
| ◆ 04-01 to 04-09 | | Japan OQ on the second real sample, dry run and blind re-entry | | plan had the dry run 04-05 to 04-09 |
| 03-29 to 04-23 | | **G5 CGMH PQ**: 18 working days | | ◆ 04-05 and probably 04-06 off (confirm) |
| 04-12 to 05-12 | | **G5 Japan PQ**: 13 working days before Golden Week, 5 after (04-30 is a thin day) | | name the journeys to run after the break |
| 04-23 | Fri | **G6 CGMH** | | 2 working days before go-live |
| **04-28** | Wed | **CGMH go-live** | | ◆ Fri 04-30 probably off (confirm); if so consider Mon 04-26 |
| 04-29 to 05-05 | | Golden Week (Japan): 04-29, 05-03, 05-04, 05-05 | | |
| 05-12 | Wed | **G6 Japan** | | 0 days before go-live |
| **05-13** | Thu | **Japan go-live** | | |
| ◆ 05-19 / 05-27 | Wed / Thu | **Named fallback dates** CGMH / Japan | | used only by a dated owner decision |

### 3.1 The PoC gate (GP, "G0.5")

| Field | Proposal |
| --- | --- |
| Purpose | Two clinicians (one per site language) work the synthetic screening flow as PI, sub-investigator and CRC in the hosted demo, in ja, zh-TW and en, and say whether the flow is usable and what is wrong. It is formative product evaluation, not research and not validation. |
| Entry | (1) tag `poc-1` on master with CI green; (2) no open Blocker or Critical on the PoC path (register and deep review rows marked "PoC path = yes"); (3) the forbidden words gone from the console (T-116); (4) site-local "today" fixed (#86 or D-270); (5) the hosted demo boots from the pinned commit over TLS with TOTP, per-IP lockout, upload and free chart text off, the banner on (PLAN-019); (6) the demo site holds the G1 short run's stored results (real pair, 5,000 synthetic patients) or, failing that, is labelled "stub results"; (7) accounts for each clinician in each role; (8) the script: about ten tasks per role with expected results, a feedback form, a severity scale; (9) an internal dry run passed; (10) the decision record that the PoC is not research (PLAN-021). |
| Exit | Every task attempted by both clinicians; task completion ≥ 80 % without help; 0 findings rated "would cause a wrong patient decision"; every finding triaged into "before G2", "before G3", "after go-live" by the owner on 12-14; no scope item added without a dated plan change. |
| If it fails | A second round is held 01-12 to 01-15 on tag `poc-2`; G2a still freezes the platform on 01-08; only screen-flow items move. The go-live dates do not move because of the PoC. |
| Earliest realistic date | **Wed 2026-12-02.** Reasons: this review closes 11-11 to 11-12; TB-PLAN-06 and the PoC cards exist by 11-13; ten working days (11-16 to 11-27, Japan off on 11-23) are the least in which T-116 (132 strings in three languages plus a native read), the PoC-path fixes of nine fix groups and the demo hardening (T-119, not started) can merge through one integrator whose queue holds 14 PRs; one day of dry run; then the first session. |
| Recommended date | **Tue 12-08 to Fri 12-11**, exit review Mon 12-14. Reasons: G1 is 12-04 and uses the same integrator and the only GPU; after G1 the demo can show real-pair results that passed a gate; the week still precedes the Japanese year-end and leaves three working weeks to fold the feedback into G2. |
| Latest useful date | Fri 12-18. After that the feedback cannot reach the design freeze. |

## 4. The recomputed critical path, with float per chain

Durations are estimates (P50 / P90) with the reasoning in §2. "Need by" is the plan's hard date. "Latest start" = need-by minus duration, minus one week where the chain crosses 年末年始 or Lunar New Year. Float is counted from **today (11-10)** because none of the chains except IRB has started. Negative float means the date is already missed at that duration.

| Chain | Need by | Duration P50 / P90 | Latest start P50 / P90 | Float P50 / P90 | State today | Critical? |
| --- | --- | --- | --- | --- | --- | --- |
| **CGMH-A: IRB approval → HIS export build → tier 3 notes** (series, PLAN-001) | tier 3 on 03-19 | IRB 6 / 13 wk, then build 13 / 17 wk | (IRB filed 11-10) | **−0.5 wk / −11 wk** | IRB filed; build has no owner | **Yes: the critical path** |
| CGMH-A′: the same with the build started now under the existing approval | tier 1 02-12; tier 3 03-19 | build 13 / 17 wk; tiers switched on at approval | build start 12-11 / 11-13 | +4 wk / 0 | not started | Yes |
| CGMH-B: COI ruling → contract and DPA (CP-3) | 03-12 | 13 / 20 wk incl. the ruling | 12-04 / 10-16 | **+3.5 wk / −3.5 wk** | not engaged | Yes |
| CGMH-C: IT security review → namespace, MIG, storage, policy (CP-2, CP-1) | ready 02-26 | 9 / 15 wk | 12-25 / 11-13 | +6.5 wk / +0.5 wk | not engaged | Near |
| CGMH-D: IRB amendment alone (CP-4) | 03-12 | 6 / 13 wk | filed | +11.5 wk / +4.5 wk | filed 11-10 | No (but it feeds A) |
| CGMH-E: G1b record (owner's B200) | 01-08 (entry to WS-11.8) | 3 / 6 wk (T-012, #85, owner time) | 12-18 / 11-27 | +5.5 wk / +2.5 wk | T-012 not started | No |
| **Japan-A: hardware decision → order → build → delivery → registration** (CP-1) | on site 03-12 | 9 / 13 wk from the order | order 01-08 / 12-04 | **0 / −5 wk** on the plan's 01-08 order; **+3 wk / −2 wk** with the order on 12-18 | Spark not confirmed bought | **Yes** |
| **Japan-B: contract and DPA** (CP-3) | 03-26 (proposed 04-01) | 17 / 26 wk | 11-27 / 09-25 | **+2.5 wk / −6.5 wk** | not engaged | **Yes** |
| Japan-C: IT review and device registration (CP-2) | 03-12 | 9 / 15 wk, cannot start before the form is known | 01-08 / 11-27 | 0 / −6 wk on the plan; +3 wk / −3 wk with 12-18 | not engaged | Yes |
| Japan-D: IRB amendment (CP-4) | 03-26 | 13 / 19 wk (monthly meeting, conditions, the director's permission) | filed | +6.5 wk / +0.5 wk | filed 11-10 | Near |
| Japan-E: feed tier 3, notes through the vendor (CP-5) | 03-26 | 8 / 20 wk (a paid vendor change needs a quote, approval and an order at year-end) | 01-22 / 11-06 | +10 wk / −0.5 wk | unknown until survey 26 and 35 | Unknown: answer by 11-20 |
| People: safety-core engineer named and working (CP-6) | G1 (proposed), G2 (plan) | 4 / 8 wk to find | 12-11 / 11-13 for G2 | +4.5 wk / +0.5 wk | search not confirmed started | Near |
| People: owner hours (PLAN-031) | every week | 14 h a week needed for chains alone | now | 0 | saturated | **Yes** |
| Code to G3 (PLAN-032) | 02-26 | 170 / 210 sessions vs 195 to 290 capacity | running | +2 wk / −1 wk | ahead of plan | No at P50 |
| Sponsor acknowledgement for the PQ prefill study (CP-7, PLAN-042) | PQ start 03-29 / 04-12 | 8 / 20 wk | 02-01 / 11-09 | +12 wk / 0 | not started | Avoid by choosing an IIT |

Reading. The plan's CP-1 to CP-6 are the right chains but the wrong shape. The critical path is non-code at both sites. At CGMH it is **amendment → export build → notes**, with the contract close behind. In Japan it is **hardware and contract together**, each with zero P50 float, squeezed between year-end, the fiscal-year turnover and Golden Week. Code is not critical at P50. The owner's hours are the resource every chain shares.

Latest start dates in one line each, for the owner's diary:

- This week (by 11-13): COI disclosure; HIS work request under the existing approval; contract templates requested at both sites; first IT meeting requested at CGMH; engineer and operations-person search.
- By 11-20: contract drafts with CGMH legal; Makoto's answers on survey 26, 35, 50 and on who rotates on 04-01; Spark bought or dropped.
- By 11-27: Japan contract request with the hospital; T-012 `qualify` merged; counsel engaged.
- By 12-18: Japan hardware ordered and registration filed; pentest firm booked; G1b done.

## 5. Capacity model

| Resource | Supply | Demand to G3 (02-26) | Reading |
| --- | --- | --- | --- |
| Agent sessions | not a limit (several sessions in parallel; 111 non-merge commits on 11-09 alone) | 170 to 210 sessions (PLAN-032) | fits |
| Integrator: verified merges | observed peak 18 to 20 a day (unverified: 115 register rows followed); sustainable with a rebase, the full suite and an adversarial read: 3 to 4 a day × 65 to 72 working days = **195 to 290** | 170 to 210, plus re-merges after conflicts (9 of 14 open PRs conflict today) | fits at P50 with about 15 % margin; fails if conflicts stay at today's rate or a second review wave lands in January |
| Open queue today | 14 PRs, about 55,000 added lines (26,000 reviewable), 9 conflicting with master | at 3 to 4 a day: 4 to 5 working days to drain, during which no new card should open on the hot files | drain before starting wave 2 |
| Owner (one person) | 14 h a week (plan) | about 14 h a week on the non-code chains alone to 12-25 (PLAN-031); G6 and hypercare overlap in May | **over-committed: no build review capacity** |
| Second clinician (Makoto) | 14 h a week (plan), minus year-end | survey, contract, IT, feed, IRB follow-up in Japan; PoC session; URS approval | probably full; unknown, ask |
| Safety-core human review | 0 today (nobody named) | every change to the six safety-core files, `authz`, the prefill path; G1 signature | **uncovered until named** |
| GPU: one RTX PRO 6000 spot VM | 1 VM, pre-emptible; about 9 h per 50k run | at least 6 long runs before G3 (short run, G1 up to 3 attempts, profile and embedding tests, 31B bake-off, injection suite on the pair, release re-run) plus `qualify` on every prompt or model change | serial; about 60 to 90 GPU-hours; fits only with a ledger and with the B200 taking the 50k runs |
| GPU: the owner's B200 | 1 machine, operator = the owner (assumed) | G1b on two MIG layouts; the 50k functional runs; the acceptance cluster drills | fits if a second operator exists; otherwise it draws on the owner's hours |
| CI and the shared build machine | 4 cores, 15 GB, several sessions | full suite per merge | unknown wall time; measure and print it in the status file |
| Finding inflow | 115 Blocker/Critical/High rows in one review day; this deep review adds more | fix rate so far 21 of 115 in a day | inflow > outflow this week; needs the budget rule of PLAN-032 |

Card arithmetic (from the cards' own Size fields, S 0.5 / M 1 / L 2.5 sessions): 67 cards = 104.5 sessions. Done: 8 cards (T-001, T-003, T-005 to T-008, T-110, T-117). In open PRs: 5 (T-101, T-105, T-111, T-113, T-118). Running: 4 (T-004, T-102, T-104, T-115). Partly merged: 2 (T-109, T-207). Not started: 48 (3 S, 24 M, 21 L = 78 sessions).

## 6. Risk register delta (ISO 14971 style, as the plan's §6)

Scales as the plan: S1 to S4 for harm, P1 to P4. Rows marked (project) carry no patient harm; their "S" is given as weeks of slip, as PLAN-051 proposes.

### 6.1 New rows

| ID | Hazard | Harm | S | P | Controls (proposed) | Verified by | Residual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RSK-51 (project) | The only cloud GPU is one pre-emptible VM; a 9-hour run is cut, or several model-level checks queue behind each other | G1 slips; qualification after a prompt or model change is skipped or done on a short set | 1 to 3 weeks | P4 | stage checkpoints and `--resume` proven by a forced pre-emption in the rehearsal; three budgeted attempts; the 50k functional run on the owner's B200; a GPU-hour ledger; no champion without a full record (WS-02.2) | TST-G1, the rehearsal case | P2 |
| RSK-52 | The qualification host (the owner's B200) differs from CGMH's partition (driver, CUDA, MIG layout, tenants), so the `shared-quota` record does not predict the hospital platform | PQ cannot start, or a silently degraded judge at CGMH | S3 | P3 | host fingerprint in the record; two MIG layouts qualified; re-measure at IQ (already WS-11.8); `doctor --platform` compares the fingerprint and warns | TST-MOD-01, TST-IQ-03 | S3 P1 |
| RSK-53 (project) | The owner is unavailable for two weeks or more (illness, clinical duty, travel). He alone approves, pays, signs, operates the B200, administers the cloud project and the repository, and is the CGMH steward and PI | every chain stops; after go-live: no steward for nights, conflicts, opt-outs, key unseal | 2 weeks or more; after go-live S3 (opt-out or SAE reminder not handled) | P3 | a named deputy per role; a second admin on the cloud project and the repository; a second B200 operator; the KEK shares already 2-of-3; the hypercare rota without the owner in at least one slot | TST-DOC-01 (role table), a tabletop "owner away" | P2 / S3 P1 |
| RSK-54 | Conflict of interest: the vendor's owner is the hospital's physician, site PI, steward and Study A PI and negotiates the hospital's contract with his own company | contract delayed or void; IRB finding; Study A not credible; supervision of the processor (PDPA, APPI) not exercised | S3 | P4 | written disclosure and CGMH's ruling before legal review; a different signer; an independent co-investigator who controls the Study A reading; the second reviewer (RSK-47); the ruling filed in the IRB pack and the DPA | TST-DOC-01 | S3 P2, co-signed by CGMH |
| RSK-55 | A clinician enters or uploads real patient information into the cloud-hosted PoC demo | privacy breach before any contract; the IT pack's promise broken | S4 | P3 | upload and free chart text off on the demo; banner in three languages; signed PoC protocol; identifier scan of stored input after each session; the demo destroyed and rebuilt after the PoC | TST-SEC-10 extended to demo input; a planted-identifier test | S4 P1 |
| RSK-56 | The PoC misleads: clinicians judge accuracy from synthetic patients or stub answers, or a poor session re-opens the scope without a rule | wrong confidence (either way); churn before design freeze | S2 | P3 | the PoC states what it can and cannot show; results from the gated G1 run; exit criteria and triage rule fixed before the sessions (GP) | gate record GP | S2 P1 |
| RSK-57 | The IRB text filed on 11-10 no longer matches the product (break-glass by the vendor's administrator, PoC changes, later decisions) | processing outside the approval (as RSK-25, RSK-42) or a second amendment that misses the hard date | S4 | P3 | diff of filed text vs decisions now; supplement before the first meeting; a freeze on data-use changes after 11-30 unless the PI checks the filed text; the per-study gate on the candidate view (WS-06.5) extended to break-glass | TST-DOC-01 | S4 P1 |
| RSK-58 (project) | The hospital's export build does not start until the amendment is approved and the contract is signed | tiers 1 to 3 late by the length of the approval; go-live slips | 4 to 12 weeks | P3 | start the mechanism under the existing approval for the PI's department; a named HIS owner; weekly check-in; the fallback date announced at G1 if no owner | owner-chain tracker | P2 |
| RSK-59 (project) | Japan's fiscal-year turnover on 04-01 during IQ/OQ: staff rotate, signers change, contracts and budgets restart | signatures repeated; training lost; the contract waits for the new year | 1 to 3 weeks | P3 | contract in force 04-01 by design; VMP signed by April's people; light on-site load 03-22 to 03-31; training after orientation week | gate record G4 Japan | P2 |
| RSK-60 (project) | Hospital IT refuses a PRC-origin model in its security review | the verifier must be replaced and re-qualified on one GPU | 3 to 6 weeks | P2 | ask in the survey now; keep a non-PRC verifier candidate measured in the bake-off harness | TST-MOD-01 on the candidate | P1 |
| RSK-61 (project) | The Japan box is imported or lent without the marks and procedures a Japanese hospital requires (PSE, 技適, importer, asset loan procedure, on-site warranty) | registration refused; the box cannot be plugged in | 2 to 6 weeks | P3 | buy in Japan from a domestic vendor; the survey asks the asset and loan procedure; hardware form decided 12-18 | TST-IQ-01 | P1 |
| RSK-62 | One integrator and a stale queue: a wrong conflict resolution in a hot file (`console/app.py`, generated models, compose, migrations) lands unnoticed; or the session ends with 14 PRs open | a regression in a safety or privacy path (as RSK-14) | S4 | P3 | decisions as files; generated files regenerated, never hand-merged; one card per PR (PLAN-048); the merge order of §7.3; goldens and the CI gate (merged); a second integrator hand-over note | TST-CI-01, TST-GOLD-01 | S4 P1 |
| RSK-63 (project) | Findings arrive faster than fixes (115 rows in a day; a deeper review in progress) and the gate "0 open Blocker/Critical" is waived to keep dates | known defects shipped into PQ | S3 | P3 | the finding budget (PLAN-032); the register condition in every gate record; code Blockers closed by the PoC freeze | gate records | S3 P1 |
| RSK-64 (project) | CGMH hypercare, Japan PQ's last week, Japan's G6 and go-live fall in the same 15 days, across Golden Week, on one owner | a CGMH incident or a Japan deviation goes unhandled | S3 | P3 | the automatic stop rule (PLAN-015); deputies (RSK-53); journeys to re-run after the break named in the PQ protocol | TST-PQ-01 | S3 P1 |

### 6.2 Changed rows

| ID | Change | Reason |
| --- | --- | --- |
| RSK-14 | Initial stays S4 P3; **the residual S4 P1 cannot be claimed** until CODEOWNERS names a human and branch protection enforces it. Until then residual S4 P2 | no CODEOWNERS file exists; CR-080 open; the engineer is unnamed |
| RSK-16 | Add "spot pre-emption" to the hazard; controls: single VM, no parallel fan-out | quota 1, spot only |
| RSK-25 | P2 → **P3** initial | the amendment is filed while contracts are not engaged: the pressure to "just read a sample" grows; keep the hard rule |
| RSK-26 | P3 → **P4** initial; residual P2 → P3 unless the order moves to 12-18 | no order, no Spark confirmed, zero float (PLAN-006) |
| RSK-27 | P3 → **P4** initial; residual P2 → P3 | hospital IT not engaged at either site |
| RSK-43 | Control text: "the cloud B200 qualification" → "qualification on the owner's B200 with a host fingerprint and two MIG layouts" | owner fact; see RSK-52 |
| RSK-45 | Residual S3 P2 → **S3 P3** until a hospital owner and signed tier dates exist | PLAN-001 |
| RSK-46 | Correct the facts: probable day off Fri 04-30 after CGMH go-live; Japan "05-14" → 05-13; add the fiscal-year turnover as RSK-59 | PLAN-012, PLAN-013 |
| RSK-47 | Residual S3 P1 → **S3 P2**; widen from "validation independence" to refer to RSK-54 | the second reviewer is not named; the contract and Study A conflicts are outside this row |
| RSK-49 | Add: the decision can be made by estimate on 12-18; the 14-night bench run becomes optional | PLAN-006 |

## 7. File-conflict matrix

### 7.1 Open pull requests against master (by a run; `git merge-tree`)

| PR | Branch | Size (files, +lines) | Commits behind master | Conflicts with master today |
| --- | --- | --- | --- | --- |
| #64 | `…/project-thread-4bwqoc-t7` (bake-off harness) | 4, +1,505 | 0 | none |
| #66 | `…-t4` (IT admin screens) | 35, +2,332 | 15 | `docs/DECISIONS.md` |
| #68 | `…-t3` (box-install rehearsal) | 54, +3,192 | 15 | `docs/DECISIONS.md` |
| #70 | `agent/T-118-wave1-leftovers` | 36, +1,818 | 96 | none |
| #71 | `…/wave0-goldens-review-fixes` | 39, +10,134 | 105 | **35 files** (superseded by #77) |
| #73 | `…/tb-critical-register` | 1, +888 | 37 | none |
| #75 | `agent/T-101-prompt-registry` | 32, +1,664 | 96 | `libs/tb_contracts/generated/models.py` |
| #76 | `…-t2` (Japan reference data) | 26, +3,482 | 72 | 5: `docs/DECISIONS.md`, `libs/tb_common/refdata.py`, `refdata_tw.py`, `tests/unit/test_refdata_tw.py`, `tools/refdata_fetch.py` |
| #78 | `…/tb-image-vulns` | 1, +35 | 60 | none |
| #80 | `…-t6` (catalogue) | 19, +18,820 | 49 | `docs/DECISIONS.md` |
| #82 | `agent/T-105-vocabulary-schema` | 37, +2,918 | 91 | 3: `docs/DATA.md`, generated `models.py`, `services/criteria_compiler/app.py` |
| #83 | `agent/T-111-update-safety` | 28, +4,174 | 49 | generated `models.py` |
| #85 | `agent/T-113-shared-quota-platform` | 34, +3,504 | 49 | `docs/RUNBOOK.md` |
| #86 | `…/tb-fix-site-today` | 19, +504 | 49 | none |

### 7.2 Pairwise matrix (cell = files both PRs change / files that conflict in a direct three-way merge of the two branches)

A conflict count also includes a conflict either branch already has with master. #71 is left out of the reading (it conflicts with everything through master).

| | 64 | 66 | 68 | 70 | 73 | 75 | 76 | 78 | 80 | 82 | 83 | 85 | 86 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **64** | – | 2/2 | 2/2 | 0/0 | 0/0 | 0/1 | 1/5 | 0/0 | 1/1 | 0/3 | 1/1 | 1/1 | 1/0 |
| **66** | | – | 4/2 | 1/0 | 0/0 | 0/1 | 1/1 | 0/0 | 1/1 | 2/2 | 2/1 | 2/2 | 5/0 |
| **68** | | | – | 0/0 | 0/0 | 0/1 | 1/1 | 0/0 | 1/1 | 2/2 | **6/3** | 4/2 | 1/0 |
| **70** | | | | – | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 1/1 | 0/0 | 0/0 | 0/0 |
| **73** | | | | | – | 0/1 | 0/1 | 0/0 | 0/0 | 0/2 | 0/1 | 0/0 | 0/0 |
| **75** | | | | | | – | 0/0 | 0/0 | 0/0 | 1/1 | 1/1 | 0/0 | 0/0 |
| **76** | | | | | | | – | 0/1 | 1/1 | 2/1 | 0/1 | 0/1 | 2/1 |
| **78** | | | | | | | | – | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| **80** | | | | | | | | | – | 0/0 | 0/0 | 0/0 | 1/0 |
| **82** | | | | | | | | | | – | **14/10** | 0/0 | 1/1 |
| **83** | | | | | | | | | | | – | 1/0 | 0/0 |
| **85** | | | | | | | | | | | | – | 0/0 |

Files touched by the most open PRs:

| File | PRs |
| --- | --- |
| `docs/DECISIONS.md` | 6: #64, #66, #68, #76, #80, #86 |
| `docs/RUNBOOK.md` | 5: #64, #66, #68, #83, #85 |
| `deploy/docker-compose.yml` | 5: #66, #68, #71, #82, #83 |
| `Makefile` | 4: #68, #71, #82, #83 |
| `services/sitesetup/service.py` | 3: #66, #70, #82 |
| `services/console/app.py` | 3: #66, #71, #86 |
| `tools/trialbox/__main__.py` | 3: #66, #68, #85 |
| `tools/trialbox/doctor.py` | 3: #68, #71, #85 |
| `libs/tb_contracts/generated/models.py` | 3: #75, #82, #83 |
| `tools/apply_update.sh`, `tools/trialbox/update.py`, `tools/verify_update.py` | 2 each: #68, #83 |
| `services/console/auth.py`, `home.py`, `step4.py` | 2 each: #66, #86 |
| the Postgres image set (`db.Dockerfile`, `images.lock`, `db-init/20-extensions.sh`, `tb_common/db.py`, `orchestrator/db_pg.py`, `test_migrations.py`, `test_db_image.py`, `backup_drill.py`, `DATA.md`, D-204) | 2 each: #82, #83 (T-104 carried twice, PLAN-048) |

Files that conflict in the most pairs: `docs/DECISIONS.md` (15 pairs), generated `models.py` (15), `services/console/app.py` (13, mostly through #71), `deploy/docker-compose.yml` (10), `Makefile` (9).

### 7.3 Proposed merge order for the open queue

1. Clean and small: **#86** (site-local today; PoC prerequisite), **#78**, **#64**, **#70**, **#73**.
2. **T-002** (decisions as files) and the rule "generated `models.py` is regenerated at merge". This removes two of the three hot conflicts for everything after.
3. **T-104 alone** as its own PR, then **#82** and **#83** rebased on it (#82 first: it changes `criteria_compiler`, a safety-core path, and needs the longer review).
4. **#85**, then **#68** (shares `doctor.py`, `__main__.py`, `egress.py` with #85 and the update tools with #83), then **#66** (shares console files with #86).
5. **#75**, **#76**, **#80** (each now conflicts only on the decision log or generated models, gone after step 2).
6. Close **#71**; port its six fixes as one new small PR.

### 7.4 Open cards: declared files ("May touch"), 59 cards not yet merged

Shared paths, by a run of `cards.py` over TB-ASSESS-01 §3 (a path is counted when a card names it):

| Path | Cards | Reading |
| --- | --- | --- |
| `docs/DATA.md` | 11: T-009, T-104, T-105, T-107, T-112, T-201, T-203, T-204, T-206, T-207, T-305 | the next `DECISIONS.md`: split by section file or generate |
| `docs/USER_GUIDE.md` | 8: T-102, T-112, T-115, T-116, T-205, T-206, T-216, T-310 | same |
| `docs/SECURITY.md` | 7: T-102, T-103, T-109, T-208, T-210, T-211, T-212 | same |
| the doctor tool (declared as `tools/trialbox_doctor.py`; real path `tools/trialbox/doctor.py`) | 6: T-109, T-113, T-210, T-211, T-214, T-319 | one check per card: make checks plug-ins in their own files |
| `services/adapter/` | 5 to 7: T-105, T-106, T-112, T-118, T-210, T-305, T-306 | `pidmap.py` is safety core (T-105, T-210) |
| `authz_matrix.yaml` | 4: T-102, T-303, T-309, T-314 | T-102 must land first; the others append rows |
| `services/omop/load.py` | 4: T-201, T-202, T-206, T-305 | order: T-106 → T-201 → T-206 → T-202 → T-305 |
| `services/sitesetup/` | 4: T-105, T-118, T-202, T-320 | #66, #70, #82 already overlap here |
| `services/datacore/` | 4 to 7: T-112, T-206, T-216, T-302, T-303, T-304, T-314 | new modules mostly; watch the store migrations (P-32) |
| `docs/VALIDATION.md` | 4: T-012, T-213, T-215, T-317 | |
| `services/console/` (directory level) | 22 cards | the wave slots A to E of TB-ASSESS-01 handle this; `app.py` one `include_router` line each |
| `libs/tb_common/` (directory level) | 16 cards | mostly different modules; `db.py` and `config.py` are the shared ones |
| `services/omop/` (directory level) | 11 cards | |
| `services/orchestrator/` (directory level) | 11 cards | includes `scenarios/screen.py` (safety core) for T-203, T-204 |
| `services/console/edc_pages.py`, `tests/unit/test_edc.py`, `tests/console/test_edc_pages.py` | 2 each: T-115, T-205 | T-115 first |
| `deploy/docker-compose*.yml` | T-104, T-108, T-212, T-306 | already hot in the open PRs |

The cards' own matrices (TB-ASSESS-01 §4.2, §4.3) are sound for code files. They miss the three shared documents above and the doctor tool, and they were written before PRs #64 to #86 existed, so the admin screens (#66), install rehearsal (#68) and reference data (#76) are not in them (TB-ASSESS-01 said so itself: P-41).

## 8. What "full scope" should mean per site

Proposal for TB-PLAN-06 §1.1. Three levels: **Used** (a real case in PQ), **Drilled** (a test record or synthetic event at OQ or PQ, because a real event cannot be ordered), **Not applicable**.

| Scope item (plan §1.1) | CGMH | Japan |
| --- | --- | --- |
| 1 Whole-hospital screening on the site's feed with the real pair | Used; feed = the HIS export, tiers 1 to 3; NHI codes, ROC dates | Used; feed = SS-MIX2 plus notes by the vendor route; JLAC10, MEDIS |
| 2 Delegation, candidate view, referral | Used (at least one referral through a treating physician) | Used |
| 3 OMOP core, lake exported from it, provenance, conflicts, vocabulary | Used (flag on); conflicts: at least one resolved by the steward | Used |
| 4 Profiles: cited page, twin, annotations, vectors, "patients like me" | Used for study patients | Used |
| 4 Setpoints and gap finder | **Built, off** at go-live (recommended: dated to the first later release, PLAN-039) | same |
| 5 REDCap prefill under GAMP 5 | Used on one study whose sponsor acknowledgement is on file (choose an IIT); else copy-assist Drilled | Used (REDCap is in use at the site) |
| 6 Steward role, data-operations console, statistics page | Used | Used |
| 7 Catalogue and specialty templates | Used: the templates of the pilot studies' specialties; the others loaded | same |
| 8 Opt-out, IRB/ICF warnings, delegation-log comparison, SAE clocks, reminder card, inputs for accountability, TMF, invoicing | Opt-out and SAE: Drilled unless a real one occurs; the rest Used | same |
| 9 Platform: MFA, backups, signed audit heads, release identity, SBOM | Used. AD: local accounts allowed with AD within 60 days (plan). Windows/WSL2 hardening: **Not applicable**. Shared-host isolation, KEK unseal: Used | Used. Windows/WSL2 hardening, BitLocker: Used. Shared-host isolation: **Not applicable**. Two-device form: Not applicable if Form B |
| Monitor SDV, break-glass | Drilled | Drilled |
| Consortium | Not in the pilot's real-data scope (synthetic two-box test only; may be dated later) | same |

## 9. What is good (keep)

- The sentence "Six chains decide the dates. None is code." and the rule that a late chain moves that site's date and never the scope quietly.
- The hard dates on the calendar (03-12, 03-26) and the non-waivable list in the VMP §6.
- The data-handling rule and "agents work from the schema and code lists only"; it also frames the PoC correctly.
- IQ before contract and IRB on synthetic data; OQ on a second sample; the dry run and blind re-entry as PQ entry.
- The tiered feed with tier 3 as a go-live condition; the readiness page that shows the loaded tier.
- The risk register's form (hazard, harm, controls with plan items, verification, residual) and the co-signature of residual risks by site PIs.
- Qualifying the B200 before touching CGMH's platform (the owner's machine makes this better, not worse).
- The cards' "May touch / Must not touch" fields and the console slot scheme.
- Continuous merging behind flags with goldens as the merge gate.

## 10. TB-PLAN-06: rewrite vs carry over

| Section of TB-PLAN-05 v1.2 | Verdict | What changes |
| --- | --- | --- |
| Header (Clock, Status) | **Rewrite** | one Japan date (Thu 05-13); state of 11-10; supersedes v1.2 |
| §1.1 Scope | **Rewrite** | per-site definition (§8 above); "Used / Drilled / Not applicable" |
| §1.2 Intended use | Carry over | add the PoC banner text |
| §1.3 Not in the pilot | Carry over, **add** | items dated later if the owner accepts PLAN-039 |
| §1.4 Decisions table | **Rewrite** rows | IRB (filed 11-10), B200 qualification (owner's machine), cloud GPU (one spot VM), Japan hardware (decision 12-18), interim hosting (date passed), new rows: PoC gate, fallback dates, deputies |
| §1.5, §1.6 Japan hardware | **Rewrite** | decision by estimate on 12-18; thresholds kept as the acceptance of whichever form is installed |
| §2 From plan v4 | Replace | a short "from v1.2 to TB-PLAN-06" table |
| §3 WBS conventions, "Who the humans are", review rule | **Rewrite** | owner hours (PLAN-031); operations person and engineer dates; deputies |
| WS-01, WS-03 to WS-09 | Carry over | update "done / in PR" states from the backlog file; no content change |
| WS-02 (G1, qualification) | **Rewrite** | 02.1 single VM plus B200; 02.5 demo hardening as a PoC prerequisite; 02.6 serial on one GPU; 02.7 owner's B200; 02.8 optional after 12-18 |
| WS-10, WS-11 | **Rewrite dates and dependencies**, keep the items | 10.1/11.1 start evidence and COI; 10.10/11.11 filed, add the supplement check; 11.10 the series dependency and the start under the existing approval; 10.x fiscal year; asset ownership |
| WS-12 | Carry over, **add** | gate records; the register as an input to every gate; traceability status from evidence |
| WS-13 | Carry over, **add** | PoC demo input control (13.10) |
| WS-14 | **Rewrite** 14.1, 14.8, 14.9, 14.4 | no rental (or decide); the owner's B200 as the acceptance cluster; two-device only if Form A |
| WS-15 | Carry over, **add** | COI ruling; MedDRA question; insurance and counsel latest starts |
| WS-16 | Carry over, **add** | independent co-investigator as a G2b condition |
| WS-17 | Carry over | T-002 items moved to this week |
| **New WS-19** | **New** | the PoC: build freeze, script, sessions, exit review |
| Totals | **Regenerate** | one number from the backlog file |
| §4.0 Calendar | **Rewrite** | §3 above, from a data file with a weekday test |
| §4.1 Gates | **Rewrite** | G0 re-held; GP added; G1 signer and three criteria; G1b on two layouts; G2 split; evidence column |
| §4.2 Week by week | **Rewrite** | W2 to W9 at least |
| §4.3 Critical path | **Rewrite** | §4 above: chains per site, series dependencies, float, latest starts, CP-7 |
| §4.4 Honest risk per gate | **Rewrite** | real float; named fallback dates and decision points |
| §4.5 G6 checklist | Carry over, **add** | deputy and COI ruling as non-waivable |
| §4.6 Capacity | **Rewrite** | §5 above |
| §5 URS | Carry over | PoC feedback enters as change requests |
| §6 Risk register | Carry over, **add and change** | §6 above; a project-risk table beside the harm table |
| §7 Validation | Carry over; **fix §7.3** | stale "W10" labels |
| §8 Test strategy | Carry over, **add** | the PoC as a formative level (not validation); the forced pre-emption rehearsal |
| §9 Security and privacy | Carry over | |
| §10 Release | Carry over | check for rental and cloud B200 mentions |
| §11 Site playbook | **Rewrite the week column** | from the new calendar |
| §12 Operating model | Carry over | |
| §13 Questions | Carry over as record, **add** | §12 below |
| §14 Answers to the independent review | Carry over unchanged (a record) | |
| §15 Change history | Add the entry | |
| `25-vmp.md` | Carry over; **edit §2, §8** | deputy; signers who are there in April; engineer named by G1 |
| `25-traceability.csv` | Regenerate | with status and evidence |

## 11. Proposed task cards for TB-PLAN-06

| Id suggestion | Goal | Files it touches | Acceptance tests | Depends on | Size | PoC prerequisite |
| --- | --- | --- | --- | --- | --- | --- |
| T-401 Plan calendar as data | One file of dated milestones and holidays (JP, TW) with sources; the plan's §4.0, §7.3 and §11 week columns generated from it | new `docs/plan/calendar.yaml`, new `tools/gen_calendar.py`, `tests/unit/test_gen_calendar.py` | the test fails when a printed weekday is wrong, when a milestone falls on a listed holiday of its site, or when a go-live is within the plan's holiday rule; PQ lengths printed in working days | — | S | no |
| T-402 Gate records | A record per gate with criterion, measure, evidence, result, signer, date; G0 and GP first | new `docs/validation/gates/G0.md`, `GP.md`, `G1.md` … and a template; `tools/doclint.py` (a check that every gate in the plan has a record file) | doclint fails on a gate without a record or a criterion without an evidence cell | — | S | yes (GP record) |
| T-403 Owner-chain tracker | One table of the non-code chains per site: step, owner, started (date), evidence, need-by, latest start, float; updated weekly in the status file | new `docs/plan/owner-chains.md` (no patient data, no personal contact details) | every chain of §4 has a row; a row without a start date after its latest start is printed in the status file's first screen | — | S | no |
| T-404 Backlog file | One generated list: cards, WS item, gate, state, PR, register rows and deep-review rows attached | new `docs/plan/backlog.csv`, new `tools/gen_backlog.py`, test | the totals in the plan come from this file; G3's condition is computable (`--gate G3 --open` prints 0 to pass) | T-002 | M | no |
| T-405 PoC pack (new WS-19) | Protocol and script per role and language, ten tasks each with expected results, feedback form, severity scale, the "not research" decision, accounts, the session checklist | new `docs/poc/` (protocol, script en/ja/zh-TW, forms), a decision file | an internal dry run completes every task on tag `poc-1`; the two native readers sign the ja and zh-TW scripts | T-116, T-406, #86 | M | yes |
| T-406 Hosted demo for the PoC | Demo profile: upload and free chart text off behind a flag, banner in three languages, pinned commit, TLS, TOTP, per-IP lockout, stored G1 short-run results loaded, identifier scan of stored input, destroy-and-rebuild script | reuse **T-119** (cloud hygiene remainder) and add: the demo flag in `app.flag`, a banner template and its i18n file, `deploy/gcp/` demo script, `tools/data_scan` run over demo input, tests | with the flag on, upload and paste routes return the refusal page in the page's language; a planted chart number in a demo field is reported by the scan; the demo boots only from the tag | T-119, #81 (merged) | M | yes |
| T-116 (existing) "Criteria not matched", forbidden words, footer | **Move from wave 2 to this fortnight**; add: the ja and zh-TW native read before the PoC | as the card | as the card, plus the walk's forbidden-word check green on the PoC tag | #86 | L | yes |
| T-004 (existing) G1 run | Add: single-VM plan; a **forced pre-emption in the rehearsal** that proves `--resume` at each stage; three budgeted attempts; wall time and pre-emptions in the report; the 50k functional run on the owner's B200 | as the card, plus `tests/rehearsal/` case | the rehearsal kills the stand-in VM at three stages and the run completes with identical results; the G1 record names commit, hours, pre-emptions | fix groups D-275, D-276 | M | no (yes if live results are shown) |
| T-114 (existing) B200 qualification | **Rewrite**: an offline bundle and one script for the owner's B200; host fingerprint; two MIG layouts; no `gcloud` | as the card minus `deploy/gcp/b200-qualify.sh`; new `tools/` script and RUNBOOK section | the record validates against its schema and carries the fingerprint; `doctor --platform` warns when the host differs from the record | T-012, #85 | M | no |
| T-407 Land T-104 alone | The Postgres image and checksummed migrations as their own PR; #82 and #83 rebased on it | the T-104 file set (listed in §7.2) | #82 and #83 no longer share a changed file after the rebase (`git diff --name-only` intersection empty) | — | S | no |
| T-002 (existing) decisions as files, CODEOWNERS | **Do now**; add: generated `models.py` regenerated in CI and at merge, never hand-merged; `DATA.md`, `USER_GUIDE.md`, `SECURITY.md` split into section files or generated (11, 8 and 7 cards touch them) | as the card, plus the three documents' layout | a merge of two branches that each add a decision, a data-table row and a contract model has no conflict | — | M | no |
| T-408 Japan hardware decision note | From the G1 numbers: pairs per hour on the RTX PRO 6000, the estimate for the Spark, the night-window check against each §1.6 threshold; a recommendation for 12-18 | new `docs/plan/measurements/japan-hardware-estimate.md` | each threshold has a number, its source and pass or fail | T-004 | S | no |
| T-409 Traceability status from evidence | `gen_traceability.py` fills `status` and `evidence` from a per-item evidence file | `tools/gen_traceability.py`, its test, `docs/plan/25-traceability.csv` | the ten merged items show `passing` with a PR and a test path; `--check` fails on a merged item without evidence | T-404 | S | no |
| T-410 Card path lint | Every "May touch" path exists on master or is marked "new" | the card file of TB-PLAN-06, `tools/doclint.py` | the lint reports `tools/trialbox_doctor.py` today | — | S | no |

## 12. Questions only the owner can decide

| # | Question | Recommended answer |
| --- | --- | --- |
| Q1 | Where is your B200, can it run MIG, and who besides you can operate it? May an agent session reach it, or do you run a script by hand? | A script you or a named operator runs; no inbound access from cloud sessions. Name a second operator. Use it for G1b, the 50k functional runs and as the acceptance cluster. |
| Q2 | Do you accept deciding the Japan hardware form on 12-18 from an estimate, instead of 01-08 from a 14-night bench run? | Yes. Form B unless the estimate clearly passes. It buys three to four weeks on the chain with zero float. |
| Q3 | Do you accept the per-site definition of "full scope" in §8 (Used, Drilled, Not applicable)? | Yes. It is what the plan can prove. |
| Q4 | May setpoints, the gap finder, the clinician view of them, the consortium work and "HAPI out" be dated to the first release after go-live? They are off, synthetic-only or internal on go-live day. | Yes. About 30 sessions and two S4 risks leave the go-live path; nothing a user sees on day one changes. |
| Q5 | Will you disclose the conflict of interest to CGMH in writing this week and let someone else sign the contract and lead the Study A reading? | Yes. Without the ruling the contract chain is likely to stall in legal review. |
| Q6 | Can the HIS team start the export mechanism now under the existing approval for your own department? | Yes; ask this week. It is the difference between float +4 weeks and −0.5 weeks on the CGMH critical path. |
| Q7 | Who are the two PoC clinicians, and do you accept the GP entry and exit criteria and the week of 12-08? | The two site leads or their delegates; yes; sessions 12-08 to 12-11, review 12-14. |
| Q8 | Do you accept naming fallback dates now (CGMH 05-19, Japan 05-27) with decision points at G1, G2 and G3? | Yes. A named fallback is cheaper than a surprise at G4. |
| Q9 | Should the Japan contract be planned to take effect on 04-01 (new fiscal year), with real-data OQ starting that day? | Ask Makoto; probably yes. |
| Q10 | Who is the Aimedics operations person, from when? | Someone other than you, from December. |

## 13. Assumptions

1. The two go-live dates and "full scope" are fixed targets; I did not propose moving them, only fallbacks.
2. Lead times for IRB, contracts, IT review, HIS and vendor work are my estimates from how such offices usually work in Taiwan and Japan. No site was asked. P50 and P90 are judgement, not statistics.
3. The amendments were filed on 11-10 with text close to the 0.1 drafts in `docs/plan/sites/`. I did not see the filed versions.
4. "The owner's own B200" is a machine he controls that is not CGMH's shared server. If it is inside CGMH's network, PLAN-017 becomes part of CP-2.
5. Aimedics is based in Taiwan and has no Japanese entity. If it has one, PLAN-037 is smaller.
6. Taiwan's 2027 holidays follow the current rules (compensatory days for holidays on weekends; 小年夜 and 12-25 as holidays). They must be confirmed from the official calendar.
7. A "session" is as the cards define it; the sustainable verified merge rate of 3 to 4 a day for one integrator is my assumption, set well below the observed 18 to 20 because that rate was followed by 115 serious findings.
8. The Spark's throughput relative to the RTX PRO 6000 is assumed to be a fraction (one quarter to one third); T-408 replaces the assumption with numbers.
9. Pairwise conflict counts come from direct three-way merges of branch heads as of the `git ls-remote` at about 18:00 on 11-10; they change with every merge.
