# TB-DR2-01 Plan vs build

| Field | Value |
| --- | --- |
| Document ID | TB-DR2-01 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (the review branch, same tree as master) |
| Plan read | `docs/plan/28-master-plan-v6.md` (TB-PLAN-06), `31-master-plan-v6.1-addendum.md` (TB-PLAN-06.1), `32-trial-opportunity-feed.md`, `27-poc-plan.md`, `backlog.csv`, `calendar.yaml`, `gpu-ledger.md`, `measurements/g1-2026-11-11/`, `measurements/b200-g1b/G1b.md` |
| Run | `git log` (the clone is shallow: 51 commits, PRs #248 to #305); a script that looks up every card id of v6 and v6.1 in `docs/decisions/REGISTRY.md`, the decision files, `services/ libs/ tools/ tests/` and the commit subjects; `python -m tools.gen_calendar --check` and `--span`; `tb_common.erasure.owed()`; 8 test files without a database (`-m nodb`: 38 passed, 8 strict expected failures, 185 s); line counts and import counts per service, compose file, tool and eval suite |
| Only read | the three previous review files, the critical-issues register, the plan text. Hardware, hospitals, contracts and the owner's diary cannot be checked from the tree |
| Limits | No GitHub access: open pull requests are not visible (`git branch -r` shows `origin/master` only). The database tests could not start here (the scratch root's parent directory is mode 700 for the `postgres` user), so every run above is a no-database run. "Done" for a card means: a merged decision row or code and a test that name the card were found; about 25 cards were opened and read, the rest rest on that lookup |

## 1. Reading in ten lines

1. Of the 185 cards of v6, **139 are on master, 9 are on master with their acceptance not met or their run not done, 37 are not built.** The addendum's "143 merged, 8 in a pull request, 34 not started" was right on its day; two of its eight pull requests (#262 T-207, #278 T-206b) are still not on master.
2. Of the 52 cards of v6.1, **10 are merged** (T-690, T-691, T-705, T-706, T-713, T-720, T-722, T-727, T-729, T-737), 1 is half (T-688), **41 are not started**. The decision, trust and night lanes, which v6.1 calls the structure, have landed only their tests and their small cards.
3. **The safety defect v6.1 was written for is still on master.** Run today: 8 strict expected failures in `tests/property/` show one model's answer excluding a patient on SCREEN v1, NAV, CASE and the MICROBATCH re-tier. The cards that close them (T-707, T-709, T-710) are not started and have no date.
4. **G1 has not passed.** The run of 2026-11-11 ended FAILED: 216 of 238 checks, 21 of 24 parts never ran (zh-TW hospital, backup, update, scale, embed, profile). The real pair has now screened one 50,000-patient hospital in Japanese; nothing else. The next attempt has no date.
5. **G1b has not been run** (`G1b.md`: "not run"). The GPU ledger shows every run "queued" with dates from the old plan, although two G1 attempts ran yesterday.
6. **The plan no longer has a critical path.** D-311 struck the gates and the owner chains; OD-18 dropped the PoC dates; v6.1 added 52 cards with no dates. What is left dated is four milestones in `calendar.yaml`. Nobody can read from the plan what must be true on which day for 2027-04-28.
7. **By the plan's own sizes the remaining work is about 285 session-days against 210 to 280 worker-days to G3** (70 working days, three or four workers). Float is zero to negative before this review's findings are added. v6.1 §7 reaches "no float" with arithmetic that does not hold (94 cards at 2 to 3 a day is 6 to 9 weeks, not 14).
8. **Two documents disagree on what CGMH runs on.** v6: a shared B200 partition in the hospital, qualified by G1b. v6.1 (OD-11, §4.4): a dedicated box; the shared-host form is frozen. No card orders or sizes the CGMH box. The Japan order date of 12-18 waits on G1 numbers that do not exist.
9. **On 2026-11-12 the trial-opportunity feed (T-740) and an admin retry (T-746, in no plan document) were built** while the above was open. The feed has five more open cards, one of them a new hosted service.
10. The tree carries much that no go-live requirement needs: 16 compose files for 6 hardware forms of which none is qualified with the real pair, a Kubernetes tree, a Windows path, two lake sources, three criteria engines, 21 MB of eval corpora, 68,000 lines of tools. Section 5 lists what to freeze or drop.

## 2. Card-by-card status

Method: a card is **done** when `REGISTRY.md` has a `merged` decision row naming it (column "evidence": the D-number) or, where a card needs no decision, code and a test naming it were found ("grep"). **half** = on master, acceptance not met or the run it exists for not done. **missing** = no code. **not needed** = struck by D-311 or absorbed. Merge commits are named where the shallow log reaches (PR #248 onward).

### 2.1 Totals

| Block | Cards | done | half | missing |
| --- | --- | --- | --- | --- |
| v6 wave P (§6.2.3) | 23 | 22 | 1 | 0 |
| v6 wave 1 (§6.2.4) | 25 | 19 | 5 | 1 |
| v6 wave 2 (§6.2.5) | 56 | 49 | 3 | 4 |
| v6 wave 3 (§6.2.6) | 72 | 46 | 0 | 26 |
| v6 wave 4 (§6.2.7) | 3 | 1 | 0 | 2 |
| v6 wave L (§6.2.8) | 6 | 2 | 0 | 4 |
| **v6 total** | **185** | **139** | **9** | **37** |
| v6.1 wave D decision (T-705 to T-711) | 7 | 2 | 0 | 5 |
| v6.1 wave T trust (T-712 to T-721) | 10 | 2 | 0 | 8 |
| v6.1 wave G night (T-722 to T-728) | 7 | 2 | 0 | 5 |
| v6.1 wave C capacity (T-687 to T-704, less T-699) | 17 | 2 | 1 | 14 (2 absorbed) |
| v6.1 wave B box (T-729 to T-736) | 8 | 1 | 0 | 7 |
| v6.1 small (T-737 to T-739) | 3 | 1 | 0 | 2 |
| **v6.1 total** | **52** | **10** | **1** | **41** |
| Opportunity feed (file 32: T-740 to T-745) | 6 | 1 | 0 | 5 |
| Outside every plan file | T-746 | 1 | | |

### 2.2 v6 cards that are done (grouped; evidence = merged decision)

| Wave | Card (decision) |
| --- | --- |
| P | T-002 (D-306), T-501, T-502 (D-328), T-503, T-504 (D-321), T-505a (D-320), T-505b (D-330), T-506 (D-351), T-507 (D-309), T-508 (D-332), T-509 (D-330), T-510 (D-331), T-511 (D-398), T-512 (D-349), T-513 (D-329), T-514 (D-362), T-515 (D-323), T-516 (D-385), T-613a (D-322), T-617a (D-342), T-671 (grep), T-672 (grep) |
| 1 | T-601 (D-333; `models/routing.yaml:221,228` `fallback: none`; `test_gateway_no_fallback.py` passed today), T-611 (D-312; `test_feed_completeness.py` passed), T-612 (`test_site_key.py` passed), T-613b (D-334; `test_lab_units_per_row.py` passed), T-615b, T-012b (D-358), T-674 (D-392), T-673 (D-348), T-113b (D-409), T-102a (D-366), T-102b (D-380), T-309 (D-430, #253), T-119 (D-423), T-669 (D-352), T-655 (D-319), T-659 (D-370), T-651 (nightly workflow `trialbox-nightly-quality.yml`), T-653, T-654 (`docs/validation/problems.csv`, `soup.csv`) |
| 2 | T-600 (D-337), T-603 (D-357), T-604 (D-388), T-605 (D-431, #256), T-606 (D-359), T-208 (D-346), T-101b (D-318), T-607 (D-429, #248), T-602 (D-277), T-106 (D-339), T-106b, T-105b, T-202 (D-384), T-201 (D-426), T-305a (D-383), T-112a (D-427, #249), T-112b (D-443, #265), T-614 (D-314), T-615a, T-616 (D-400), T-102c (D-425), T-103 (D-438, #259), T-116 (D-351), T-310a (D-446, #268), T-621 (D-364), T-622 (D-386), T-115 (D-368), T-205 (D-391), T-302a (D-399), T-110b (D-340), T-117b (D-274), T-108a (D-360), T-108b (D-377), T-111b (`test_update_safety.py:933`), T-631 (D-367), T-632 (D-382), T-634 (D-408), T-210a (D-421), T-210b (D-347), T-212a (D-369), T-212b (D-437, #263), T-633 (D-416), T-213a (D-410), T-214 (D-373), T-104b (D-371), T-215 (D-344), T-643 (D-363), T-011 (`tools/synth_site_from_schema.py`), T-617b (D-342) |
| 3 | T-203a (D-439, #261), T-203b (D-449, #275; flag `vec.s2b` off), T-204 (D-440, #260), T-608 (D-445, #267), T-609 (flag `notes.reading`), T-109b (D-447, #269), T-107 (D-353), T-307 (D-375), T-610, T-618 (D-317), T-619a (D-417), T-619b (D-396), T-619c (D-418), T-659b (D-381), T-305b (D-403), T-302b (D-414), T-302c (D-434, #272), T-302d (D-435, #270), T-303 (D-436, #273), T-310b (D-395), T-623 (D-387), T-624 (D-397), T-629 (D-415), T-620 (D-407), T-108c (D-401), T-108d (D-389), T-209a (D-379), T-209b (D-405), T-209c (D-406), T-210c (D-354), T-211a (D-355), T-211b (D-394), T-211c (D-451, #274), T-212d (D-450, #276), T-319 (D-432, #255), T-635 (D-390), T-318 (D-411), T-649b (D-343, then T-737), T-649c (`docs/validation/soa.csv`), T-315a (D-448, #271), T-657 (D-444, #266), T-658, T-676 (D-372), T-677 (D-393), T-684 (D-361), T-685 (D-402) |
| 4, L | T-628 (D-413), T-316b (D-419), T-679 (`backlog.csv`, 12 rows) |

### 2.3 v6 cards that are half

| Card | Plan status | Real status | Evidence |
| --- | --- | --- | --- |
| T-004 G1 on one spot VM | wave 1, due 12-04 | half: the driver, resume and collect are built and fixed (#293, #296, #299, #300, #301); **the run failed** | `measurements/g1-2026-11-11/report-partial.md`: "FAILED: 216 of 238 checks … 21 part(s) crashed or never ran" |
| T-012a `qualify` | merged (D-313) | half: the tool is there (`tools/qualify.py`, 1,220 lines); no qualification record of the real pair exists in the tree | `eval/qualification/` holds 3 small files; no record under `docs/plan/measurements/` |
| T-114 G1b on the owner's B200 | merged (D-428) | half: bundle, script and record format built; **not run** | `measurements/b200-g1b/G1b.md`: "Status: not run"; ledger row B2 "queued" |
| T-650 safety-core property tests | merged | half: `hypothesis` is now in `pyproject.toml:70` and `uv.lock` (T-737), CI job `property` exists (`trialbox-ci.yml:283`); the properties that matter are expected failures (PLAN-001) | run today: 8 xfailed |
| T-652 equivalence gate and decision table | merged | half: `services/matching/verdict.py` is imported by `criteria_compiler/equivalence/gate.py:19` only; no engine and no scenario calls it | `grep -rn 'matching.verdict\|status_of' services` |
| T-206a opt-out worker v1 | merged (D-441, #264) | half: the register is read on the screening paths; erasure is owed in 60 stores | `tb_common.erasure.owed()` returns 60 entries today |
| T-212c one database role per service | merged | half (not re-checked here): v6.1 §4.3 says writers are owners and the console is in the EDC owner group; T-720 (#285) closed the signature part, T-718 is not started | v6.1 §4.3; `REGISTRY.md` D-461 |
| T-656 one site time zone | merged | half per v6.1 §4.3 (the audit log names a zone of its own); waits for T-708 | not re-checked |
| T-664 GPU ledger | wave P | half: the file exists and is wrong | `docs/plan/gpu-ledger.md`: S2a "planned 2026-11-24 … queued"; two attempts ran on 11-11 |

### 2.4 v6 cards that are missing

| Card | What | Size | Needed for go-live? |
| --- | --- | --- | --- |
| T-207 | screening reads stored derived rows; rulesets pin definition versions | M | yes (CR-066). Said to be in PR #262; not on master, branch not visible |
| T-206b | erasure and retention after opt-out | M | **yes** (CR-027). Said to be in PR #278; not on master |
| T-216 | missing data as "unknown with a reason" | M | yes (CR-007 rest, CR-013); waits for T-709 |
| T-667 | hardware decision note from G1 numbers | S | **yes**, it gates both hardware orders; waits for a G1 that passes |
| T-637 | capacity model from G1 | S | yes; same wait (v6.1 turns it into T-734) |
| T-682 | export ledger and watermark | S | yes for a site that exports (privacy); waits for T-715 |
| T-675 | heavy extras (docling, embed, OCR) in an image or removed | M | yes if notes are embedded on the box |
| T-301a | PI pages: prioritised list, feasibility and approval pages | L | yes (CR-086, FIT-024) |
| T-304a | statistics page | M | scope item 6 says "Used" |
| T-305c | retention with a hold per study | M | yes (records) |
| T-315b, T-315c | install and dry-run protocols and tooling | M, M | **yes**: it is the only content of the weeks after G3 |
| T-317 | documents made true; role guides in ja and zh-TW | M | yes |
| T-213b | box drills on real hardware | L | yes; re-scoped to the box by v6.1 §4.2 |
| T-320a, T-320b | EMR launch link; site set-up leftovers | M, M | site asks decide |
| T-625, T-626 | cross-study view; outside-medication checks and contact outcomes | M, M | T-626 yes (FIT-012: concomitant-drug criteria cannot be decided without it) |
| T-681, T-683, T-686, T-638, T-310c | privacy-office requests; session robustness; role and operations polish; override report | S to M | T-681 before real data; the rest later |
| T-203c, T-311a, T-311b, T-312, T-313, T-314, T-316a, T-316c | "patients like this one", cited profile page, Study C/D drafts, annotations, setpoints and gap finder, restricted clinician view, consortium two-box test, de-identified export | 2 L, 5 M, 1 S | **no**: section 5 proposes after go-live |
| T-301b, T-304b, T-304c, T-627 | reminder card and `.ics`; EXTRACT and Define-XML; ISF bundle and invoice report; Study A tooling | 3 M, 1 L | no for the day of go-live |
| T-306, T-678 | HAPI out of the nightly path; dependency batch 4 | M, M | T-306: see section 5; T-678 is dated after June 2027 |

### 2.5 v6.1 cards

| Card | Plan status | Real status | Evidence |
| --- | --- | --- | --- |
| T-705 path-independence test | first | done | D-459, #283; `tests/property/test_path_independence.py` (815 lines), passed today with its named exceptions |
| T-706 judge-in-the-loop property | first | done as a test; **its 8 expected failures are the open defects** | D-460, #286; run today |
| T-707 pool rows bound to version and basis | after T-706 | missing | xfail "H1 … T-707" |
| T-708 the decision context | | missing | no `opted_out(` lint; no module |
| T-709 one `status_of` | | missing | `grep status_of services` finds nothing |
| T-710 one excerpt builder | | missing | xfails "H4 … T-710" |
| T-711 three-engine boundary table (`differential` job) | | missing | no `differential` job in `trialbox-ci.yml` |
| T-712 database passwords out of the shared `env_file` | first, S | missing | no test or decision names it |
| T-713 callers per route | first, S | done | D-464, #288; `services/orchestrator/route_callers.yaml` |
| T-714 real-box fixture | | missing | |
| T-715 actor assertion v3 | L | missing | `services/orchestrator/callers.py:20` "are T-715's"; `by:` still a body or query field at `app.py:386,492,551,783` |
| T-716, T-717, T-718, T-719, T-721 | | missing | no code |
| T-720 version-1 EDC signatures refused | first, S | done | D-461, #285 |
| T-722 one lock for rebuild and hold | first, S | done | D-462, #284 |
| T-723 `publish(night)` | L | missing | D-472 says T-690 "uses T-723's state" but T-723 does not exist |
| T-724, T-725, T-726 | | missing | |
| T-727 erasure registry | | done (the registry and the enumerating test; the clears are owed) | D-465, #289; `test_erasure_registry.py` passed; 60 owed |
| T-728 as-of export keeps tombstones; restore reports late opt-outs | first, S | missing | named only in comments |
| T-687 scale gate and limit lint | **"first card of the wave"** | missing | no workflow job, no lint; `tests/unit/test_polled_jobs.py:582` mentions its shape |
| T-688 estimate and heartbeat of the cloud run | before the next G1 | half | #299 (measured 5.0 h per hospital part), #300; no heartbeat card closed |
| T-689 screening job survives an outage and a restart | before the next G1, L | missing | D-456 `reserved` |
| T-690 rebuild and ingest as polled jobs | | done | D-472, #302 |
| T-691 backup without a pause | | done | D-455, #303 |
| T-692 ingest and rebuild in streams | L, a blocker of the scale review | missing | |
| T-693 to T-698, T-700 to T-703 | | missing (T-696 absorbed by T-710, T-704 by T-726) | D-457, D-458 `reserved` |
| T-729 box installer and wizard | L | done | D-466, #290; `deploy/box-install.sh`, `tools/box/` |
| T-730 the box looks after itself | L | missing | |
| T-731 data connectors | L, one PR each | missing; a 43-line read-only SQL source exists (`services/adapter/sources/cgrd_sql/source.py`); the wizard prints "its connector and mapping step are on the box (T-731)" (`tools/box/plan.py:317-321`) | |
| T-732 to T-736 | | missing | |
| T-737 N-12 unadjusted; `hypothesis`; `property` job | S | done | D-463, #287 |
| T-738, T-739 | S, S | missing | |
| T-740 opportunity feed, hub page, sample | file 32 | done | D-467, #282 (1,301 lines with its test) |
| T-741 to T-745 | file 32 | missing ("open") | |
| T-746 admin retry of a failed scheduled job | **in no plan file** | done | D-474, #305 |

## 3. Status of the previous review's findings

### 3.1 `10-plan-realism.md` (PLAN-001 to PLAN-051 of 2026-11-10)

"Not needed" = the owner's rule D-311 removed the step the finding was about. Old ids are written `old PLAN-nnn` where they could be confused with this file's ids.

| Old id | Severity | Now | Evidence |
| --- | --- | --- | --- |
| old PLAN-001 CGMH approval, export build and notes in series | Blocker | **open, changed shape.** The IRB link is struck (D-311 B23). The data source is now CGRD by a read connection (OD-14); the connector (T-731) and `publish` (T-723) are not built; v6 §3.1 still shows the HIS-export chain | v6 §3.1 row CGMH-A′; section 2.5 |
| old PLAN-002 contracts not engaged | Blocker | not visible from the tree; no longer tracked (D-311 B19 struck the owner chains). v6 §3.1 rows Japan-B and CGMH-C still print float counted from 11-10 | v6 §3.1, §3.2 |
| old PLAN-003 bus factor 1 and conflict of interest | Blocker | not needed (D-311 B8, B19); OD-17 settles who reviews the box owner in the product (T-736, missing) | v6.1 §8 |
| old PLAN-004 one spot GPU | Blocker | **partly.** Sharding and an on-demand VM for the hospital parts exist (D-468, #301); the run still failed and the next is undated | `BUGS.md` A3 |
| old PLAN-005 PoC gate not in the plan | Blocker | fixed in v6, then dropped: OD-18 removes the PoC dates; `27-poc-plan.md` and v6 §2 still carry them | v6.1 §8 |
| old PLAN-006 Japan hardware has no float | Critical | **open and worse**: the decision moved to 12-18 "from measured G1 numbers"; there are none | v6 §2.1; section 4, PLAN-004 |
| old PLAN-007 hospital IT not engaged | Critical | changed: OD-13 reduces IT to an address and a data connection; no card states what is asked of CGMH IT or when | v6.1 §1 |
| old PLAN-017 G1b on the owner's B200 undefined | Critical | partly: defined and built (T-114), not run; the access design (T-739) is missing | `G1b.md` |
| old PLAN-019 real text into the hosted demo | Critical | fixed in code (T-502, D-328, flag `demo.mode`) | `libs/tb_common/flags.py:98` |
| old PLAN-031 the owner's hours | Critical | not needed as a tracked item (D-311 B19); still true | |
| old PLAN-008, PLAN-022 amendments | High, Medium | not needed (D-311 B23) | |
| old PLAN-009 Japan fiscal year | High | open as a fact; G4 is struck, so no row carries it | v6 RSK-59 |
| old PLAN-010, PLAN-011, PLAN-012, PLAN-013 slack and holidays | High, High, High, Medium | fixed as data: `calendar.yaml` holds verified holidays; `gen_calendar --check` passes ("4 milestones, 34 days off, ok"). v6 §2.2 still says "confirm" on dates the data file has verified | run today |
| old PLAN-014 no fallback date | High | owner decided none (Q-09) | v6 §1.4 |
| old PLAN-018 stale hardware and money lines | High | **open in a new form** (PLAN-004, PLAN-009 below) | |
| old PLAN-020 PoC words | High | fixed (T-506, T-116); the route `/studies/{rs}/excluded` remains as an old path | `services/console/home.py:889` |
| old PLAN-023, PLAN-024, PLAN-027, PLAN-028, PLAN-029 gates and signers | High, Medium | not needed (D-311 B1, B3, B9, B10, B28) | v6 §0.1 |
| old PLAN-025, PLAN-026 G1 and G1b criteria | Medium | partly: the report names commit, wall time and pre-emptions; the two MIG layouts are in `G1b.md` | |
| old PLAN-030, PLAN-032, PLAN-035 capacity measured wrongly | High, High, Medium | **open.** v6.1 §7 repeats the fault with new numbers (PLAN-003 below) | |
| old PLAN-033 one integrator, stale queue | High | improved: the queue of 14 is drained; at most 4 pull requests are outside master (#262, #278, #298, #304) | PR numbers in `git log` |
| old PLAN-034, PLAN-050 status file stale | Medium, Low | **open**: `26-status-2026-11-10.md` is two days and 60 merges old; no generated status exists | |
| old PLAN-036 PRC-origin verifier | High | open; a second verifier candidate is registered, not measured (ledger S4 "queued") | `gpu-ledger.md` |
| old PLAN-037 who buys the Japan box | High | open | |
| old PLAN-038 full scope per site | High | fixed in v6 §1.2; now out of date against OD-11 and OD-14 | |
| old PLAN-039 work that can be dated later | High | **open**: the owner kept it all for go-live (Q-06); 12 of those cards are missing today (section 2.4) | |
| old PLAN-040 register closure target | High | not needed as a gate (D-311 S5); see 3.4 for the real state | |
| old PLAN-041 to PLAN-045 | Medium, Low | owner matters; not tracked | |
| old PLAN-046 traceability matrix says "planned" | High | **open**: 273 of 273 rows `planned` | `docs/plan/25-traceability.csv`, counted today |
| old PLAN-047, PLAN-048, PLAN-049 | Medium, Low | fixed (the queue is merged) | |
| old PLAN-015, PLAN-016, PLAN-021, PLAN-051 | Medium, Low | PLAN-016, PLAN-021 fixed; PLAN-015, PLAN-051 open, low value | |

### 3.2 `11-task-inventory.md`

It is an inventory, not a list of findings. Its four results, checked:

| Result of 2026-11-10 | Now |
| --- | --- |
| 67 cards, 48 not started | replaced by v6's 185; section 2 is the count today |
| Decision-number collisions (§E) | fixed: `REGISTRY.md`, one file per decision; D-448 to D-451 collided once more on 11-12 and were renumbered (v6.1 §3) |
| Card text names files that do not exist (§C.4) | not re-checked |
| Items with no card (§F) | attached in v6 §6.2.9. **New orphans today:** T-746 (built, in no plan file); T-630 (cited in v6 §0.4 and the ledger, has no row; v6.1 makes it T-739); `REGISTRY.md` D-278 and D-282 to D-289 still `reserved` for fix groups that will not come |

### 3.3 `01-fit-to-owner-intent.md`

| Old id | Severity | Now | Evidence |
| --- | --- | --- | --- |
| FIT-005 filed IRB text ahead of the code | Critical | not needed (D-311 B23); files archived | `docs/plan/sites/archive/` |
| FIT-001 traceability does not trace | High | open (273 `planned`); the ritual is struck (B15), the file is still shipped | counted today |
| FIT-002 the monitor cannot monitor | High | fixed (T-303, D-436, #273) | |
| FIT-003 the PI cannot start a run | High | fixed (T-512, D-349) | |
| FIT-022 no steward role | High | fixed (T-102b, D-380; T-309, D-430) | |
| FIT-004 profiles absent | High | partly: twin (T-204) and vector store (T-203a, T-203b, flag off) are built; cited page, "patients like this one", annotations, setpoints, gap finder and clinician view are missing | `tests/console/test_twin_api.py:79` "empty until T-313" |
| FIT-017 data-operations, statistics, export ledger, catalogue | High | partly: data-operations (T-112a, T-112b) and catalogue (T-107) built; statistics page (T-304a) and ledger (T-682) missing | |
| FIT-018 clinical conflicts page | High | fixed (T-201, `services/console/conflicts_page.py`) | |
| FIT-012 outside-medication checks | High | open (T-626 missing) | |
| FIT-009 consent record | High | fixed (T-302a, D-399) | |
| FIT-007 not-matched list safeguards | High | fixed (T-310a, D-446, #268) | |
| FIT-006 words against the intended use | High | fixed; the statement is in the footer | `templates/base.html:54` |
| FIT-016 Study A cannot be run | High | open (T-627 missing) | |
| FIT-023 opt-out on lists only | High | partly (T-206a done; 60 erasure obligations owed) | run today |
| FIT-024 list not prioritised; unknown names no item | High | open (T-301a, T-216 missing) | `grep next_visit services/console/home.py`: nothing |
| FIT-025 SAE banner and office copy | High | fixed (D-277, T-602) | `services/console/saerecord.py:659` |
| FIT-020, FIT-027 break-glass; sub-investigator | Medium | fixed (T-309; T-505b) | |
| FIT-015, FIT-019, FIT-026 | Medium | fixed (T-302c, T-302d; T-657; T-101b) | |
| FIT-008 contact outcomes | Medium | partly (some outcomes found in `home.py`; T-626 missing) | |
| FIT-010, FIT-013, FIT-014 reminder card; CRC minutes; invoice and ISF | Medium | open (T-301b, T-304c missing) | greps empty |
| FIT-011 EMR link | Medium | partly: the reveal path accepts `via="emr"`; no link, no site setting | `tests/console/test_reveal_paths.py:380` |
| FIT-021 | Low | fixed | |

### 3.4 Critical-issues register (TB-REG-01)

Count. The register's last table (update 2) has 118 Blocker, Critical and High rows: 28 fixed, 28 in a pull request, 62 open. v6 §6.3 maps 88 of them to closers. Looked up today (a row counts as closed when every closing card or fix group has a merged decision; this is a lookup, not a re-test of 88 rows):

| Severity | all closers merged | closers merged, an owner part left | part merged | nothing merged | Rows in v6 §6.3 |
| --- | --- | --- | --- | --- | --- |
| Blocker | 7 | 3 | 2 | 8 (6 of them owner or hospital rows) | 20 |
| Critical | 4 | 0 | 2 | 0 | 6 |
| High | 44 | 3 | 8 | 7 | 62 |
| **Total** | **55** | **6** | **12** | **15** | **88** |

With the 30 rows the register already had as fixed or that v6 does not map, about **85 of 118 are closed on master, about 33 are open or partly open**; 10 of the open ones are process rows that D-311 removed.

Every Blocker and Critical row:

| Row | Severity | Problem (short) | Now | Evidence |
| --- | --- | --- | --- | --- |
| CR-001 | Blocker | lab compared without its unit | fixed | D-275; `compile_sql/generator.py:26,53,248`; `test_lab_units_per_row.py` passed today |
| CR-002 | Critical | the two-model rule accepts one model twice | fixed for the pair check | D-276; `test_two_model_identity.py` passed today |
| CR-003 | Critical | the stub cannot disagree; rules untested | partly: `tests/judge_kit.py` reads its text; its use shows 8 open defects | run today |
| CR-016 | Blocker | chart numbers in the audit chain | fixed going forward (D-272); the old chain is owner decision OD-7 | registry |
| CR-017 | Critical | oldest reveal route unguarded | fixed: one reveal path (T-103, D-438); the route still exists at `console/app.py:1500` as "a thin handler over the one reveal path" (read, not re-tested) | |
| CR-024 | Blocker | permission sprawl, no steward | fixed (T-102a, b, c; D-366, D-380, D-425) | |
| CR-027 | Critical | opt-out worker and erasure | **partly: 60 stores owed** | `erasure.owed()` |
| CR-032 | Blocker | real data before an agreement | rule only; the demo refuses uploads (T-502) | |
| CR-033 | Blocker | no second factor, no OIDC, no TLS | fixed (D-192, D-193, D-279, T-505a, T-109b); `doctor` fails without MFA in PRODUCTION | |
| CR-034 | Blocker | e-signature is a password the admin saw | fixed (`must_change`, `console/auth.py:17,136`; D-281) | |
| CR-041 | Blocker | keys in clear; Windows checks | fixed in code (T-210a, b, c); the Windows path is now outside the box form (v6.1 §4.4) | |
| CR-045 | Critical | image vulnerabilities | partly; not re-scanned here | |
| CR-049 | Critical | UTC date bug | fixed (#86) | register update 2 |
| CR-060 | Blocker | OMOP as store of record; default `legacy` | **open**: `lake.source` default is still `legacy` | `libs/tb_common/flags.py:104-106` |
| CR-062 | Blocker | EDC prefill controls | fixed in code (T-115, T-205, T-302b, T-720); never run on a real REDCap | |
| CR-069 | Blocker | G1 has not passed | **open** | `report-partial.md` |
| CR-080 | Blocker | no second reader | not needed (D-311 B10); `.github/CODEOWNERS` exists as information | |
| CR-084 | Blocker | shared-host install | fixed in code (T-113, T-113b, T-633); frozen as the second form | |
| CR-088 to CR-093 | Blocker | feeds unknown, box not ordered, IT, contracts, export owner, calendar | owner rows, not visible; CR-088, CR-089 and CR-092 are the substance of PLAN-004 and PLAN-005 below | |
| CR-095 | Blocker | Study A protocol | not needed as a card (T-010 struck) | |
| CR-097 to CR-101 | Blocker | already fixed on 11-10 | fixed | register §3 |
| CR-113 | Critical | cloud run without cap or watchdog | fixed and exercised by two real runs | `BUGS.md` |
| CR-121 | Critical | microbatch tier without the note-block decision | **open in another form**: the re-tier still turns one model's stored answer into an exclusion | xfail H1 (T-707), run today |
| CR-122 | Critical | the gateway answers the judge with the verifier | fixed | `test_gateway_no_fallback.py` passed today |

Also still open among the Highs, and material: **CR-038** (the orchestrator takes the acting person from the request; fix group D-278 never landed, its registry row is still `reserved`; T-715 is its heir and is missing), CR-066 (T-207), CR-007 and CR-013 (T-216), CR-030 (T-314), CR-068 (profiles), CR-086 (T-301a).

## 4. Findings

Severity as the brief defines it. "Flag" says which milestone the finding stands in front of.

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLAN-001 | Blocker | **One model's answer still excludes a patient on four paths, and the cards that fix it have no date and no owner.** v6.1 names this as root cause S1 and puts its cure "then" after the small cards. Only the two tests landed. | Run today: `pytest tests/property -m nodb` → 8 xfailed: `screen_v1-ranked_out`, `screen_v1-index_lost`, `screen_cascade-lexicon`, `nav-ranked_out`, `nav-index_lost` (T-710); `nav-single`, `case-single` (T-709); `microbatch-retier_after_single` (T-707) | A wrong exclusion, silently, with real models. Any accuracy number measured before the fix (G1 of 11-11 included) is a first reading only, as v6.1 §7 says | Make T-707, T-708, T-709, T-710 the first lane of plan v7 with dates; no G1 re-run counts before they are in | T-707 (S), T-708 (M), T-709 (M), T-710 (M) | Go-live both, PoC |
| PLAN-002 | Blocker | **G1 has not passed and nothing dates the next attempt.** Attempt 1 failed on a fixed limit, attempt 2 was pre-empted after one hospital part. 21 parts have never run with the real pair: the zh-TW hospital, both public-data parts, every source scenario, backup, update, scale, embed, profile. | `measurements/g1-2026-11-11/report-partial.md` lines 6 to 50; `BUGS.md` A1 to A5; `gpu-ledger.md` (all rows "queued") | Every later step waits on it: the capacity statement, both hardware decisions, the model pair's fitness in Chinese | Date attempt 3 after T-688 and T-689 (v6.1 §3.4 says so) and after PLAN-001's lane; write the two attempts into the ledger with hours and cost | T-004, T-688 (S), T-689 (L) | Go-live both |
| PLAN-003 | Blocker | **The remaining work does not fit before G3 at the owner's worker allowance, and v6.1's capacity line is wrong.** By the plans' own sizes (S 1, M 3, L 7.5 session-days): 37 v6 cards ≈ 121 days; 41 v6.1 cards ≈ 165 days (T-731 counted as four connectors); total ≈ 285. Supply to Fri 2027-02-26: 70 working days × 3 to 4 workers = 210 to 280. v6.1 §7 says "94 cards are about 8 to 10 working weeks at 2 to 3 merges a day. That is the whole time to G3": 94 ÷ 2.5 is 38 days; the time to G3 is 70 days (14 weeks). It counts merges, not the days a card takes. | sizes from v6 §6.2 and v6.1 §3; `gen_calendar --span TW 2026-11-12 2027-02-26` → 70 | Float is 0 to −75 session-days before the findings of this review (13 files) and the G1 bug list are added. G3 slips or scope goes, and the plan says neither | Cut scope by the list in section 5 (about 80 session-days) and re-plan by session-days per lane, not by merge count | NEW-PLAN-1 "Plan v7: one dated lane table, capacity in session-days" (S) | Go-live both |
| PLAN-004 | Blocker | **Nobody has decided what hardware CGMH goes live on, and the Japan order waits on numbers that do not exist.** v6 §1.4: CGMH hosts on its shared B200, G1b qualifies that. v6.1 OD-11 and §4.4: a site runs a dedicated box; the shared-host form "is not developed further". No card sizes, orders or receives a CGMH box. T-667 and T-734 need a passing G1 (PLAN-002) measured after PLAN-001. v6's own lead time is 9 weeks P50, 13 weeks P90 from the order. | v6 §1.4 row 2, §3.1 row Japan-A; v6.1 §1 OD-11, §4.4; section 2.4 (T-667 missing) | Chain today: T-688/T-689 → G1 → decision lane → re-measure → T-667 → order → delivery → install. With an order in the week of 2027-01-11, delivery is mid-March (P50) or mid-April (P90): **float to CGMH go-live +5 weeks / −1 week; to Japan +7 / +1**, before any install or data work on the box | Decide the form now from what is measured (one RTX PRO 6000 screened 50,000 patients' note stage in about 5 h); order one workstation of that class for Aimedics at once as the reference box; let T-667 confirm or change the site orders by 12-18 | T-667, T-734; NEW-PLAN-2 "CGMH hardware form and order" (S) | Go-live both |
| PLAN-005 | Blocker | **The path by which CGMH's real data enters the box is not built and not on a dated chain.** OD-14 makes the source a read connection to CGRD plus uploads. T-731 (L, one PR per connector) is not started and depends on T-723 (L, not started). What exists is a 43-line SQL reader and a wizard warning. v6 §3.1 still shows the HIS-export chain with "tier 1 on 02-12". | `services/adapter/sources/cgrd_sql/source.py`; `tools/box/plan.py:317-321`; section 2.5 | No real-data dry run at CGMH is possible until T-723 → T-731 (CGRD) → a mapping done on the box. Two L cards in series is 3 to 4 weeks of one session before the site sees its own data | Put T-723 and the CGRD connector at the head of the night lane; build the other four connectors after go-live unless Japan needs one (SS-MIX2 exists) | T-723 (L), T-731 (L) | Go-live TW |
| PLAN-006 | Critical | **After an opt-out the patient's data stays in 60 stores.** The registry (T-727) lists them honestly; the clears (T-206b) are in a pull request that is not on master and that this clone cannot see. | Run today: `tb_common.erasure.owed()` → 60 entries; no `(#278)` in `git log` | An opted-out patient remains in lake snapshots, vectors, the twin, EDC drafts, backups: the first thing a privacy office tests | Land T-206b on T-727's registry; then T-728 | T-206b (M), T-728 (S) | Go-live both |
| PLAN-007 | Critical | **The trust lane has not started; the acting person is still taken from the request.** CR-038 has been open since 11-10; its fix group D-278 never landed and its registry row is still `reserved`. T-715 (L) and the five cards behind it are missing; T-712 (S, "first") is missing. | `services/orchestrator/app.py:386,492,551,783`; `REGISTRY.md:125`; section 2.5 | Any holder of a service token can act as any person; audit rows name whoever the body says | T-712 now; T-714 → T-715 in report mode before G2 | T-712 (S), T-714 (M), T-715 (L) | Go-live both |
| PLAN-008 | High | **Two lake sources are still alive and the default is the one that is not the store of record.** Go-live scope item 3 says "OMOP core … flag on". The default is `legacy`; the goldens and e2e run both. | `libs/tb_common/flags.py:104-106`; `tools/goldens.py:3-4`; `tools/e2e_simple.py:1473` | Every screening change is built and tested twice; the G1 numbers belong to whichever source the run used; CR-060 stays open | One card: flip the default to `omop`, run G1 on it, delete the legacy flatten path and its goldens | NEW-PLAN-3 "One lake source: default `omop`, legacy removed" (M) | Go-live both |
| PLAN-009 | High | **The plan documents contradict each other and the tree** (list in 4.1). | 4.1 | A worker session that reads v6 builds toward dates and forms that the owner has dropped | Plan v7 as one file; v6, v6.1, file 32 and the PoC plan marked superseded | NEW-PLAN-1 | Go-live both |
| PLAN-010 | High | **IRB, counsel, sign-off and gate steps that the owner's rule removed are still live text in v6** (list in 4.2). | 4.2 | They read as work to do | Delete them in v7 | NEW-PLAN-1 | Go-live both |
| PLAN-011 | High | **Work outside the go-live path was built on 2026-11-12 while Blockers were open.** T-740 (feed, sponsor dashboard, 1,301 lines with tests) and T-746 (in no plan file). File 32 opens five more cards: a job type, a steward page, a hub service with sponsor accounts (L), a CGRD run for sale, a price sheet. | #282, #305; `docs/plan/32-trial-opportunity-feed.md` §3 | About 15 session-days more if continued; a second product (the hub) with its own accounts and hosting | Freeze T-741 to T-745 until after both go-lives; move them to `backlog.csv` | T-741 to T-745 | Later |
| PLAN-012 | High | **The test of OD-10 does not exist, and the plan itself sets fixed limits.** T-687 is "the first card of the wave"; T-690 and T-691 landed without it. In the plan text: T-687's lint looks only at "every `timeout=` above 60 s" (a 59 s limit passes); D-445 (T-608) fixes 5 s, 180 s, 210 s, 240 s, 64 in flight, 16 slots as defaults with no derivation; T-108a's memory caps are constants (`TB_MEM_*:-2g`, `4g`, `48g`) whatever the host; v6 §1.4 and §2.2 still plan "about 9 hours per 50k run" against a measured 5.0 h for one hospital part. | v6.1 §3.4 row T-687; `libs/tb_common/config.py:504-514`; `deploy/docker-compose.yml:99,131`; commit `be92929` | The next fixed limit that cuts a night is found on site, as on 11-11 | Build T-687 before any other capacity card; its lint covers every timeout and every `LIMIT`, with the reason list; derive the gateway budget from the serving record | T-687 (L), T-703 (S) | Go-live both |
| PLAN-013 | High | **The weeks after G3 have no content.** D-311 struck G4 to G6. The cards that would fill 41 working days at CGMH and 50 in Japan are missing: T-315b, T-315c (install and dry-run tooling), T-317 (documents, role guides in ja and zh-TW), T-213b (drills on real hardware), T-730, T-735. | section 2.4, 2.5; `gen_calendar --span` | The first install on site becomes the first rehearsal | A lane "site readiness" in v7 with these six cards, starting in January on the reference box of PLAN-004 | T-315b, T-315c, T-317, T-213b, T-730, T-735 | Go-live both |
| PLAN-014 | High | **Nine merged cards are counted as done although their purpose is not met** (section 2.3): T-652's decision table is called by no engine; T-114 and T-012a have no record; T-004's run failed; the ledger is wrong. v6.1 §4.3 lists four of them; the count of "143 merged" includes all. | section 2.3 | The plan's progress number overstates by the cards that matter most | v7 counts "accepted" apart from "merged" | NEW-PLAN-1 | Go-live both |
| PLAN-015 | Medium | **Profile and research items the review of 11-10 proposed to date later are still go-live scope (Q-06) and are all missing**: T-203c, T-311a, T-311b, T-312, T-313, T-314, T-316a, T-316c ≈ 31 session-days; go-live day shows them with flags off (v6 §1.2 row 4b). | section 2.4 | 11 % of the remaining budget for features nobody sees on the day | Ask the owner once more with PLAN-003's number beside it | T-313 and the seven others | Later |
| PLAN-016 | Medium | **Dead process tooling stays in the tree and in CI**: `docs/plan/25-traceability.csv` (273 rows, all `planned`), `tools/gen_traceability.py` and the CI job `trace`, `tools/doclint.py`. D-311 made them warnings. | counted today; `trialbox-ci.yml:130` | A job that cannot fail and a file that says nothing has happened | Delete the CSV and the job, or generate status from test results in one S card; not both states | NEW-PLAN-4 "Traceability: generate or delete" (S) | Later |
| PLAN-017 | Medium | **Open pull requests cannot be seen from the tree, and the plan describes them as done.** v6.1 §4.1: #262 "(done)", #275 "(done)", #278. #275 is merged; #262 and #278 are not. #298 and #304 are unknown. PR #291 (G1 measurements) **is merged** (`d6667ef`). | PR numbers in `git log` | T-207 and T-206b are counted as built | A generated status page: card, PR, state, from the host's API | NEW-PLAN-5 "Generated status: cards, PRs, register" (S) | Later |
| PLAN-018 | Low | `backlog.csv` (12 rows) still words three items as approval steps ("ethics-approved templates", "the hospital's approval", "MOHW approval"); `calendar.yaml` prints G1 on 12-04 and G1b on 12-11 as if nothing had happened. | the two files | small | reword in v7 | NEW-PLAN-1 | Later |

### 4.1 PLAN-009: statements contradicted by the tree or by a later decision

| Where | Says | Fact |
| --- | --- | --- |
| v6 header | "Status: Proposed … once the owner approves it at G0 (Fri 2026-11-13)" | G0 is struck (D-311 B3); v6.1 was approved 11-12 |
| v6 §2.1, §2.2, §2.3; `27-poc-plan.md` (whole file) | GP-0 tag `poc-1` on 11-27, GP-1 12-01, sessions 12-08 to 12-11 | OD-18 dropped the dates; neither file mentions OD-18 (`grep -c OD-18` → 0); `git tag` is empty |
| v6 §1.4, §3.1 | CGMH on a shared B200; the HIS export, tiers 1 to 3 | OD-11 (a box), OD-14 (CGRD read connection) |
| v6 §3.1 | floats "counted from 2026-11-10" for 16 chains, 8 struck | no chain has been recounted; the struck rows are still printed |
| v6 §6.2.1 | fix groups D-271 to D-281 "not pushed" | all merged except D-278 (`REGISTRY.md:117-128`) |
| v6 §6.4, §6.5 | merge order and conflict matrix of 14 open PRs | the queue is merged; 300 lines of dead text |
| v6 §1.4, §2.2 | "about 9 hours per 50k run"; attempts on 11-24, 11-27, 12-01 | measured 5.0 h per hospital part (#299); two attempts ran 11-11 |
| v6.1 §4.1 | #262 "(done)" | T-207 is not on master |
| v6.1 §4.3 | "T-650 (`hypothesis` not in the lock)" | in `pyproject.toml:70` and `uv.lock` since #287 |
| v6.1 §7 | 143 merged, 8 in a PR, 34 not started; "94 to build" | today 148 on master (9 of them half), 37 missing; with v6.1 and file 32: 83 to build |
| v6.1 §3.4 | T-690 "uses T-723's state, not its own" | T-690 is merged (#302); T-723 does not exist |
| v6 §12 | version 1.1 adds file 32, cards T-740 to T-745 | v6.1 does not know file 32; T-746 is in no file |
| `gpu-ledger.md` | every run "queued" | PLAN-002 |
| `calendar.yaml` header | "Milestones are build milestones only" with G2 "Platform freeze (design freeze)" on 01-08 | no document says what G2 means after v6.1 |

### 4.2 PLAN-010: steps to delete (owner's rules: no IRB, COI, steward-approval or development-gate steps)

| v6 line (approx.) | Text | Do |
| --- | --- | --- |
| §2.2 row 2026-11-10 | "IRB amendments filed at both sites (done)" | delete |
| §2.2 rows 03-01 to 05-12 | pentest pass 2 booking; "Hard date CGMH: contract, DPA, amendment approved"; G4 CGMH, G4 Japan, G5 CGMH PQ, G5 Japan PQ, G6 CGMH, G6 Japan | delete the G4 to G6 rows (struck in §2.1 but still in the calendar table); keep install and dry-run as work (PLAN-013) |
| §2.1 GP-1 | "final in ja and zh-TW after a native read" with "Decided by" columns | drop the column |
| §4 row Makoto | "IRB follow-up; … URS approval" | delete |
| §5.1 RSK-70 | "Verified by: counsel's read" | reword as a document check |
| §6.2 T-318 | "the legal-basis memo of T-646 is filed here once counsel signs" | delete the clause (T-646 is struck) |
| §6.2 T-628 | "the procedure is signed by each trial office" | reword: the procedure exists and is drilled |
| §6.2 T-314 | "until the regulatory consultant's opinion" | delete the wait (T-647 to T-649a struck) |
| §6.2.9 | "WS-15.*: owner and counsel (T-646, T-649a) … tracked in T-663" | delete (all three struck) |
| §6.3 coverage rows CR-087 to CR-096, FIT-005, REG-007, PLAN-003, PLAN-024 | "owner: COI disclosure by 11-13", "counsel engaged by 11-27", "supplement to the IRBs", "name the safety-core engineer", "counsel signs" | delete the rows' closers; mark the rows "not on the plan (D-311)" |
| §6.5 (c) lane 1E | "T-641 and T-646 first; both are on the critical path of the IRB supplement and counsel" | delete |
| §8.3 checklist | "legal-basis memo is signed by counsel … before any real sample"; "gap note … signed by the owner"; "record inventory is signed by each trial office"; "VMP v1.1 is signed by all nine roles before IQ" | delete the signing clauses; keep the document where the product needs it |
| §8.4 rows 2, 3, 5, 7 | corrections to the filed IRB amendments | delete (archived) |
| §10.4 Q-17 | "the IRB cover note (Q-14) says so" | delete |
| `27-poc-plan.md` §9 title and §9.2 | "Sign-off"; the committee sentence in assumption 6 | rename; keep the on-screen acknowledgement only |
| `backlog.csv` BL-003, BL-005 | "ethics-approved templates", "the hospital's approval", "MOHW approval" | reword as product capability |

Not to delete: the IRB-text gate on study set-up (T-310b), ICF version against the IRB's version (T-302a), IRB reference per criteria version (T-621) and the steward's accept of a held night (T-723) are product functions for the site's trials, not steps of this project.

## 5. What to drop or simplify

LOC = Python lines unless said. "Importers" = files outside the component that import it (`services/ libs/ tools/`), then test files. Verdicts: keep / freeze (stays, no new card, out of the per-PR test load where possible) / drop / merge into X.

### 5.1 Services (26 under `services/`, 103,000 lines)

| Component | LOC | Importers / tests | Go-live requirement? | Verdict |
| --- | --- | --- | --- | --- |
| `opportunity_hub` (+ `orchestrator/scenarios/opportunity.py` 170, `tb_common/opportunity.py`, `tools/opportunity_feed.py` 209, test 585) | 218 + 2 static files | 1 / 2 | no (revenue idea of 11-12) | **freeze**; T-741 to T-745 to the backlog; do not start the hub service (T-743, L) |
| `deliverables` (analytics, disclosure, figures, pack, render) | 1,925 | 1 (`tools/cascade_e2e.py` only) / 3 | no: no service imports it | **drop** or move under `tools/`; it is a report pack for one tool |
| `channels` (command grammar, language detect) | 420 | 4 (console) / 5 | chat-style commands are not in the nine scope items | freeze; merge the one used function (`detect_language`) into the console if the rest is unused on a site |
| `mail_gateway` (intake, outbound, admin, store) | 1,513 | 2 / 10; in 6 compose files | outbound morning mail: yes. Inbound intake by mail: BL-001, after go-live | keep outbound; **freeze intake** (v6.1 T-713 already narrows its callers) |
| `model_guard` | 218 | 0 / 6; in 4 compose files | yes: it is the only door to vLLM | keep |
| `tracestore` | 267 | 2 (gateway) / 6 | T-605 turned prompt text off in PRODUCTION: it stores hashes and sizes only | **merge into gateway** (one table, no service surface) |
| `registry` (model alias → build over HTTP) | 609 | 12 / 16; 2 compose files | the gateway needs the map, not an HTTP service | merge into gateway as a file read; keep `registry.yaml` |
| `llm_stub` | 776 | 13 / 32 | test only | keep; make every safety test use `tests/judge_kit.py` (v6.1 §5.2), then shrink the stub's personas |
| `rc_sim` + `rc_bridge` | 576 + 786 | 8 + 8 / 15 + 14 | REDCap prefill is scope item 5 | keep; the simulator is the only REDCap ever run against (CR-062): one run on a real REDCap is worth more than new simulator code |
| `edc` (own EDC) | 4,010 | 4 / 15 | "its own EDC" is in scope | keep; no new features before go-live |
| `omop` + legacy flatten in `lake` | 5,106 + 2,758 | 11, 32 / 23, 69 | scope item 3 | **one source** (PLAN-008): drop the legacy path after the flip |
| `datacore` | 4,151 | 28 / 31 | yes | keep |
| `vec` + `embed_service` | 714 + 269 | 7, 23 / 6, 53 | scope item 4a; S2b flag `vec.s2b` is off and "not turned on before T-724" | **freeze behind the flag**; no T-203c before go-live; the on-the-fly S2b path stays the one path until G1 measures the store |
| `patient_profile` (twin) + `console/twin_api.py` | 475 | 3 / 4 | 4a "Used for study patients"; the twin's research layers are `null` until T-313 | freeze as built; no new layers before go-live |
| `criteria_compiler`: three engines (Python reference, SQL, CQL with Java jars, `tools/cql_local/`) | 4,980 | 31 / 57 | SQL screens; CQL is a second opinion that needs a JVM image, the translator jars and HAPI's model | keep SQL and the Python reference; **freeze CQL as a CI-only differential** (T-711), not on the box. This removes the JVM image from the box's bundle |
| HAPI FHIR server (compose service, 5 GB cap) | image | read by `lake/store.py`, `adapter/load_fhir.py`, `datacore/fhir.py`, the CQL translator | only the legacy lake source and CQL need it at night; T-306 "HAPI out of the nightly path" is missing | **drop from the box** together with the legacy source and CQL-on-box: one card instead of T-306 |
| `sitesetup`, `doc_parser`, `guard`, `gateway`, `adapter`, `matching`, `orchestrator`, `console` | 3,570; 612; 540; 2,300; 7,454; 4,107; 19,005; 36,227 | — | yes | keep. The console is 36,000 lines in one process: no split before go-live (BL-004 is right) |

### 5.2 Deploy

| Component | Size | Used by | Go-live requirement? | Verdict |
| --- | --- | --- | --- | --- |
| 16 compose files: base, `box`, `secrets`, `identity`, `monitoring`, `test`, `testbench`, `acceptance`, `poc`, and hardware `rtxpro6000`, `rtx5090`, `gb10`, `shared-quota`, `two-device/spark`, `two-device/workstation`, `platform/docker-compose.platform.yml` | 1,800 lines | CI runs base and `identity` only | one box form per site | **keep** base + `box` + `secrets` + `identity` + `monitoring` + `test` + the one hardware file of the ordered box. **Freeze** `rtx5090`, `gb10`, two-device, `shared-quota` until a site orders that form. **Drop** `poc.yml`, `poc.sh`, `poc.ps1` when OD-18's PoC-on-a-box is planned (the hosted demo form is gone) |
| `deploy/platform/` (Kubernetes base, overlays, kind scripts) | 33 files, 2,409 lines; `tools/trialbox/platform.py`, `platform_day2.py`, `tests/platform/` | not in CI's per-PR jobs | no (v6.1 §4.4) | **freeze**, and take it out of "stay in CI": an untested frozen form is honest, a half-tested one costs every refactor of T-715 and T-718 |
| `deploy/windows/` | 7 files, 823 lines | T-210a | no (v6.1 §4.4: a box is Linux) | **drop** from the release bundle; keep in git history |
| `deploy/gcp/` | 14 files, 2,501 lines | G1 driver | development tool | keep until G1 passes; nothing new |
| `deploy/hardening/`, `systemd/`, `pgbackrest/`, `identity/` | 1,500 lines | the box | yes | keep |
| `demo/`, `site/` + `tools/build_site.py` (1,970 lines), `netlify.toml` | 2.5 MB | `make` target; public marketing site | no | **move out of the product repository** or freeze; it is in every data scan and lint run |

### 5.3 Tools (115 files in `tools/`, 68,000 lines with sub-folders) and eval (22 folders, 21 MB)

| Component | LOC | Used by | Verdict |
| --- | --- | --- | --- |
| Tools with no Makefile, CI or tool caller: `catalogue_verify` 1,142, `validation_figures` 731, `gpu_sizing` 360, `ad_eval` 357, `make_protocol_docs` 312, `parity_replay` 269, `onepager` 267, `build_scenario_ruleset` 250, `vec_parity` 239, `make_cohort_docs` 226, `export_spec` 168, `phi_synth_eval` 154, `manual_funnel` 143, `judge_eval` 129, `parser_compare` 113, `gen_score_defs` 107, `command_score` 68, `phi_synth_gen` 63 | 5,100 | a unit test each, or none (`validation_figures`, `vec_parity`, `make_cohort_docs`) | **freeze** in a folder `tools/research/` excluded from the unit job; **drop** the three with no test |
| `gen_traceability`, `doclint` | — | CI `trace`, `docs` as warnings | drop or make real (PLAN-016) |
| `scenarios` 2,068, `e2e_simple` 2,019, `complete_run` 1,596, `cascade_e2e` 718, `public_e2e` 1,056, `cgmh_demo`, `list_demo`, `role_demo`, `demo` | 8,500 | five end-to-end drivers over the same flow | **merge toward two**: `e2e_simple` (CI) and `complete_run` (the measured run); T-315a's journeys already replace the demo walkers |
| `judge_bakeoff` 997, `bakeoff_live` 627, `mlbench` 524 + `mlbench_tasks/`, `trialgpt_compare` 454, `trec_ct_eval` 473 | 3,100 | model selection research | freeze; the pair is chosen; only the second-verifier bake-off (ledger S4) is on the plan |
| `eval/trialgpt_compare` (81 files, 3.1 MB), `eval/trec_ct` (6.4 MB), `eval/bakeoff` (5.8 MB), `eval/open_cohorts` (2.1 MB), `eval/medtxt` (1.2 MB), `eval/criterion_ml`, `eval/chia`, `eval/synthea`, `eval/vec_parity`, `eval/chat`, `eval/canary_local` | 19 MB | 0 Makefile targets, 0 CI jobs (only `ad` and `injection` are named in workflows) | **freeze**: move the corpora out of the working tree into the `.cache` fetchers that BL-009 to BL-011 already describe; keep `eval/qualification`, `eval/injection`, `eval/ad`, `eval/parity`, `eval/omop_parity`, `eval/phi_synth`, `eval/suites` |

### 5.4 Plan and process

| Item | Verdict |
| --- | --- |
| Four live plan files (v6 1,956 lines, v6.1, file 32, the PoC plan) plus `25-master-plan.md`, which v6 says still carries seven sections "unchanged" | **merge into one v7** of a few hundred lines: scope, the lane table with dates, capacity, the drop list. Everything else archived |
| v6 §6.3 coverage table (300 lines), §6.4, §6.5, §6.7, §8.4 | drop (history) |
| `docs/validation/problems.csv` (49 rows: 41 open, 8 fixed) beside the register, the two deep reviews and `BUGS.md` | keep it as **the one** list; fold the others into it once, by script |
| Two problem-severity scales and two registers of decisions (`DECISIONS.md` frozen log + files) | keep as is; no work |

Estimated saving against PLAN-003 if the "no" rows of section 2.4, T-732, T-733, T-741 to T-745, four of five connectors and the frozen forms are dated after go-live: **about 80 to 90 session-days**, which brings the total inside 3 workers × 70 days with about two weeks of float.

## 6. What the plan must change (inputs to plan v7)

### 6.1 The critical path from today

Working days (Taiwan calendar, `gen_calendar --span`): to 2027-01-08: 40; to G3 2027-02-26: 70; to CGMH go-live 2027-04-28: 110; Japan to 2027-05-13: 118.

| # | Step | Cards | Size | Earliest end | Depends on |
| --- | --- | --- | --- | --- | --- |
| 1 | One model never excludes; one decision function; one excerpt builder | T-707, T-708, T-709, T-710 | S, M, M, M (≈ 10 days, one lane) | Fri 2026-11-27 | — |
| 2 | The screening job survives an outage; estimate and heartbeat | T-688 rest, T-689 | S, L | Fri 2026-11-27 (parallel lane) | — |
| 3 | G1 attempt 3 on the fixed code, both hospitals, all parts, lake source `omop` | T-004, NEW-PLAN-3 | run + M | Fri 2026-12-04 | 1, 2 |
| 4 | Hardware note and capacity statement; **both box orders** | T-667, T-734, NEW-PLAN-2 | S, M, S | Fri 2026-12-18 | 3 |
| 5 | Reference box at Aimedics (ordered now, same class as measured) installed from the installer; drills | T-729 (done), T-730, T-213b | L, L | Fri 2027-01-29 | order this week |
| 6 | `publish(night)` then the CGRD connector with its mapping step | T-723, T-731 (CGRD only) | L, L | Fri 2027-01-15 | — |
| 7 | Actor assertion and its dependants | T-712, T-714, T-715, T-716, T-719 | S, M, L, M, M | Fri 2027-01-29 | — |
| 8 | Erasure clears; generations | T-206b, T-728, T-724, T-725, T-726 | M, S, M, M, M | Fri 2027-02-05 | 6 |
| 9 | Scale gate, then streams and batches | T-687, T-692, T-694, T-702, T-703, T-695 | L, L, L, L, S, M | Fri 2027-02-19 | 3 |
| 10 | G3: feature complete = steps 1 to 9 plus the "yes" rows of section 2.4 | T-207, T-216, T-301a, T-305c, T-626, T-675, T-681, T-682 | ≈ 25 days | Fri 2027-02-26 | |
| 11 | Site boxes delivered (9 weeks P50 from 12-18: 02-19; 13 weeks P90: 03-19), installed, connected to CGRD / SS-MIX2, mapping done, first real night | T-315b, T-315c, T-735, T-317 | M × 4 | CGMH 2027-03-26 (P50) | 4, 5, 6 |
| 12 | Real-data dry run and the journeys of T-315a on the site's box | — | 3 weeks | CGMH 2027-04-16 | 11 |
| 13 | Go-live | | | CGMH Wed 2027-04-28; Japan Thu 2027-05-13 | |

Float, counted from today:

| Chain | Float P50 | Float P90 | Note |
| --- | --- | --- | --- |
| Decision lane → G1 attempt 3 (steps 1 to 3) | +1 week to the 12-18 order date | **−2 weeks** if attempt 3 fails once more (two of two have) | the binding chain this month |
| Hardware for CGMH (step 4 → 11) | +2 weeks | **−2 weeks** (delivery 03-19, three weeks of step 12 end 04-30 with 清明 inside) | no card exists for it today (PLAN-004) |
| Hardware for Japan | +4 weeks | 0 | fiscal-year turnover on 04-01 and Golden Week 04-29 to 05-05 sit in steps 11 and 12 |
| CGRD connector (step 6 → 11) | +5 weeks | +2 weeks | only if it starts this month; behind two L cards |
| Code to G3 at full v6 + v6.1 scope | **−1 to −3 weeks** at 3 workers | worse | PLAN-003 |
| Code to G3 with section 5's cuts | +2 weeks | 0 | |

Not on the critical path, and to be dated after go-live in v7: everything in the last two rows of the table in 2.4 except T-626; T-711; T-717, T-718, T-721 (after T-715 is in refuse mode); T-732, T-733; four of the five connectors; T-697, T-698, T-700, T-701; T-741 to T-745; the shared-host, Windows and two-device forms; GP-0 to GP-2 as gates (OD-18: one PoC on the reference box after step 5, dated then).

### 6.2 Changes, as a list

1. **One plan file (v7).** A lane table with a date per card for the next four weeks and a week per card after that; capacity in session-days per lane; "accepted" counted apart from "merged". (NEW-PLAN-1, S)
2. **Order of work.** Decision lane and T-689 first; then G1; nothing else is "first". The addendum's step 2 list (T-712, T-728, T-738) runs beside it; T-687 before T-692.
3. **Hardware.** A card that states the form per site and the order dates; a reference box ordered now. (NEW-PLAN-2, S)
4. **One lake source.** (NEW-PLAN-3, M; before G1 attempt 3 if it fits in step 2's two weeks, else right after and G1's release re-run measures it.)
5. **Site readiness lane** from January: T-730, T-213b, T-315b, T-315c, T-735, T-317; dependency: the reference box.
6. **Scope decision for the owner**, with the number: about 31 session-days of profile and research items (PLAN-015) and about 50 more in section 5 against a float of −1 to −3 weeks.
7. **Delete** the steps of 4.2 and the stale text of 4.1; update the GPU ledger with the two attempts of 11-11 (hours, pre-emptions, cost).
8. **Stop new numbers outside the plan**: T-746 gets a row; file 32 moves to the backlog.
9. **Generated status** (NEW-PLAN-5, S) so that "which PRs are open" and "which cards are accepted" are read, not written.

## 7. Needs GCP / owner hardware

| Test | Command and inputs | Record | Pass |
| --- | --- | --- | --- |
| G1 attempt 3 | `deploy/gcp/complete-run.sh` on the commit that has T-707 to T-710, T-689 and `TB_LAKE_SOURCE=omop`; 50,000 synthetic patients, ja and zh-TW; hospital parts on the on-demand VM (D-468) | checks passed of 238; parts that ran of 24; wall time per part; pre-emptions; model exclusions true / false / missed per language; pairs per hour; cost | every part ran; false exclusions 0 in both languages; the 8 expected failures of `tests/property` gone from the commit |
| G1b on the owner's B200 | RUNBOOK §11; `python -m tools.b200_qualify` with the offline bundle; both MIG layouts | `g1b-record.json`, host fingerprint, note-stage seconds p50 / p95 per layout | the record validates against `schemas/b200_qualification_record.schema.json`; needed only if a site keeps the shared-host form (PLAN-004) |
| Reference box | `deploy/box-install.sh` on the ordered workstation with only the wizard's answers; one synthetic 50,000-patient night; `doctor` | install time; night wall time; peak memory per service against its cap; patients per night | the night ends inside the site's night window with no cap raised by hand; this is T-734's input |

## 8. Small certain fixes

No product-code fix of a few lines closes a finding of this file; the High-or-worse findings are missing cards. Document fixes that are certain:

1. `docs/plan/gpu-ledger.md` rows S2a and S2b: state "run 2026-11-11, failed (drain limit)" and "run 2026-11-11 to 11-12, 5.5 h, pre-empted once, partial (`measurements/g1-2026-11-11/`)"; planned dates of S1, S3, B1 cleared. Test that fails first: none exists; add to `tests/unit/test_backlog.py` a check that a ledger row with a past planned date is not "queued".
2. `docs/decisions/REGISTRY.md:125,129`: D-278 and D-282 to D-289 from `reserved` to `unused` (the fix-group session ended on 11-10); CR-038's heir is T-715. `python -m tools.decisions_index --check` stays green.
3. `docs/plan/31-master-plan-v6.1-addendum.md` §4.1 row #262: "(done)" → "open, not on master"; §4.3: strike "T-650 (`hypothesis` not in the lock)"; §7: the counts of section 2.1 of this file.

## 9. What is good

- The registry of decisions works: 124 of v6's cards can be traced to one merged decision file each in seconds, and the count agreed with the addendum's.
- v6.1 is the most accurate plan document the project has had: its five root causes are confirmed by today's run, and its tests (T-705, T-706) make the open defects visible as strict expected failures that cannot be forgotten.
- The three "silent wrong answer" defects of the last review are closed and their tests pass today: the gateway's cross-role fallback, the feed-completeness gate, units per row.
- `calendar.yaml` with verified holidays and a `--span` counter replaced guesswork; this file's working-day numbers come from it.
- G1's failures were written down the same day with cause, cost and fix (`BUGS.md`), and five of them were fixed within a day.
- The erasure registry tells the truth about what is owed instead of claiming it.

## 10. What was not checked

- The 139 "done" cards: only that a merged decision or named code and test exist. About 25 were opened. Whether each card's acceptance holds is the other twelve reviewers' subject.
- The 85 High rows of the register one by one; the table in 3.4 is a lookup through v6 §6.3.
- Open pull requests (#262, #278, #298, #304): invisible here.
- Anything outside the repository: the hospitals, contracts, the owner's B200, hardware orders, cloud cost.
- Database-backed tests: could not start in this session's scratch root.
- The session-day estimate uses the plans' own S/M/L sizes; no card was re-sized.
- Lead times for hardware are v6's (9 / 13 weeks); no vendor was asked.
