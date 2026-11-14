# The remaining work, split by lane (2026-11-14)

Plan v7.3 (`33-plan-v7.md`) stays the plan; this page says who does what next. It is re-cut when the six proof runs
pass or every lane has finished its queue below, whichever comes first. Channels: `36-how-sessions-talk.md`.

## Principles

1. The milestone is a working version: the six proof runs R1 to R6 pass. Cards serve them; dates do not gate work.
2. Order inside every queue: safety defects, then what blocks an R, then the next plan card. Never idle.
3. Accommodate the site as it is (Windows 10 PCs, CGRD's own date forms and codes); the product adapts, the site does not.
4. Measure with the real models before calling anything done; optimize only after R1 to R6 pass.
5. One owner per file area; a cross-lane edit is a small card by the owning lane, asked for on the inbox (#593).

## Proof runs and who closes them

| Run | What passes | Closed by | Waits on |
| --- | --- | --- | --- |
| R1 | Nightly green three nights in a row | D (CI, nightly), B2 (scale job) | first night on train 15's code: 2026-11-14 19:22 UTC |
| R2 | A production box starts from the real installer and signed bundle | G builds the bundle and rehearses; D owns installer and gates | vLLM waiver typed in lane D's session |
| R3 | P-0: the Windows installer end to end on a real PC | W (NEW-WIN-10), then the owner's PC | NEW-WIN-10 |
| R4 | D-502 matrix: every data set, real models, en, ja, zh-TW | G | train 16; the owner's yes on the matrix cost |
| R5 | One CGRD day read, mapped and screened | E, with the first-look session | the owner attaching columns.json, day.json, answers.md |
| R6 | REDCap R1 to R9 on our instance | E (NEW-EDC-1, P-6) | the owner's REDCap zip |

## Queues

Sizes: S under half a day, M one to two days, L more. Items in order.

### Lane A2: screening, criteria compiler, rulesets, guard

| Card | What | Why now | Size |
| --- | --- | --- | --- |
| D-780.. records | Records for #578, #582, #586, #589 | registry complete | S |
| #589 | SCREEN uses the box's embed service, after lane C2's `CALLERS` line | R4: note criteria otherwise "not evaluated" | S |
| NEW-LLM-6 | (wave 3) as in the plan | R4 accuracy | M |
| CGRD codes | Value sets that never match CGRD's NHI local codes, from the first-look deep review | R5 | M |
| P-6/P-8 follow-ups | The verifier's label of the other criterion type (with D) | R4 accuracy | S |
| ENG-005 share | Burn down `KNOWN` lines in screening | quality | split |

### Lane B2: lake, OMOP, synthetic hospital, scale, masking

| Card | What | Why now | Size |
| --- | --- | --- | --- |
| D-744 | English phone form in `phi_guard` | safety | S |
| D-745 | Dates of birth, postal addresses, labelled chart numbers survive the mask (found on real CGRD notes) | safety | M |
| Deep-review masking | Every other shape the first-look review finds | safety | M |
| T-694 | Night batches | 500k night | L |
| T-702, T-703, T-695 | The 500,000-patient night as an incremental night | scale | L, L, S |
| HW-007 | Capacity stated; a night that does not fit is refused with an estimate | scale | M |

### Lane C2: console, accounts, roles, audit, site setup

| Card | What | Why now | Size |
| --- | --- | --- | --- |
| train 16 fix | Journeys' `InprocBackend` has no `orch` (#590) | train 16 | S |
| #589 line | `CALLERS`: embed service accepts the orchestrator | R4 | S |
| NEW-LIFE-2, NEW-LIFE-18 | (wave 3) | lifecycle | M, M |
| LIFE-005 to LIFE-009 | Log keeps numbered rows on opt-out; study closes only empty; SAE clock and mails; retention hold | lifecycle | M each |
| JRN-003, 005 to 008 | PI starts a request; EDC map size; privacy office report; future consent date refused; monitor page | journeys | S to M |

### Lane D: image, installer, backup, CI, nightly, supply chain

| Card | What | Why now | Size |
| --- | --- | --- | --- |
| vLLM waiver | CVE-2026-128089 entry, on the owner's typed yes | R2, image gate | S |
| Nightly reds | Read each night's result, fix or route | R1 | S per night |
| R2 support | Commands and help for lane G's bundle build | R2 | S |
| Gateway defects | `contexts()` swallows a failed `/v1/models`; timeout has no structured flag | R4 honesty | S, S |
| T-730, T-735 | (wave 3) | ops | M, M |
| T-317 | Guides in ja and zh-TW from Help; acceptance gains capacity and power-cycle criteria | go-live | M, S |
| ENG-006 | Raise the mutation floor after each complete nightly | quality | split |

### Lane E: CGRD and HIS adapters, mapping, EDC and REDCap

| Card | What | Why now | Size |
| --- | --- | --- | --- |
| R5 mapping | Map CGRD from columns.json and day.json; visit numbers do not join (0 of 1.5M): find the join | R5 | M |
| Deep-review data | Types, encodings, ROC dates, empty strings the first-look review finds | R5 | M |
| NEW-EDC-1 | Recorded answers of our REDCap test instance | R6 | M |
| T-667 | (wave 2) | EDC | M |
| EDC-007, EDC-008 | (wave 3) | EDC | M, M |
| EDC-004 to 006, era/ROC prefill | Source changed; correction read back; retire an item; ROC dates | EDC | M, M, S, S |
| UX-003, CSV BOM, UX-004 | Workbooks; BOM; one decoder with Shift_JIS and Big5 | outputs | M, S, S |
| P-6 | R1 to R9 on our instance | R6 | run |

### Lane W: Windows

| Card | What | Why now | Size |
| --- | --- | --- | --- |
| NEW-WIN-10 | Windows 10 22H2 supported: build 19045 accepted; console through a port-forward under NAT (D-503) | R3 | M |
| P-0 sheet | Windows 10 lines; stage-1 media builds from master | R3 | S |
| P-0 answers | Every "no" line the owner sends back | R3 | S each |
| P-10 to P-15 | On the reference workstation when it arrives | wave 4 | runs |

### Lane G: cloud runs, measurement, bundle, performance

| Item | What | Why now | Cost |
| --- | --- | --- | --- |
| #592 | Batch 6: D-497, corrected scenario checks, public_site resolved diseases | after train 16 | none |
| D-502 cost table | Every data set × language × part, one table for one yes | R4 | none |
| R2 bundle | Build and sign on lane G's runner (key in Secret Manager), rehearse the production start | R2 | owner's yes |
| Demo VM | Ready to start the moment the owner sends two addresses | 2026-11-17 | ~US$4, yes given |
| D-502 matrix | Run once after train 16, B14 and the masking fixes | R4 | owner's yes |
| NEW-PERF-1 (#333) | Concurrency from the serving record; calls/s, tokens/s, p50/p95, GPU use | R4, optimization | none to build |
| G-1, G-4 repeats; G-3 full curve; G-6, G-9, G-10, G-11 | Plan section 7.1 | 12-11 run | owner's yes |
| Profiling | Where a night's time goes at 50k (ingest, rebuild, screen, backup); top three costs with numbers | optimization | with G-6 |

### Integrator

| Item | What |
| --- | --- |
| Trains | One whenever a `train-ready:` line waits; settle cross-card reds on the train; land on green |
| Inbox | Answer #593 questions; route findings to the owning lane |
| Records | Number owner rulings (D-502, D-503); keep this page and the handover true |
| Nightly | Read each night with lanes B2 and D; report to the owner |
| Review PRs | #499, #504, #506, #509, #503 onto trains, the owning lanes reconciling conflicts |

### First-look session (the owner's computer; counts only, data stays there)

| Item | What | Waits on |
| --- | --- | --- |
| `--day` rerun | The date fix proved on the real export | the owner's yes in that session |
| Deep review | The data path against the real export (mask, reader, dates, joins, codes) | the owner's yes; Opus now, Fable after 2026-11-19 |
| Database run | The same two commands on CGRD itself | the DBA's read-only account |
| P-0 | On this PC, on G:/H:/I:, after NEW-WIN-10 | NEW-WIN-10; the owner's go-ahead |

## The critical path to the working version

| By | What |
| --- | --- |
| 2026-11-15 | Trains 16 and 17 land; first nightly on train 15's code read; vLLM waiver in; D-502 cost table to the owner |
| 2026-11-17 | Demo on lane G's VM |
| 2026-11-20 | R5 first CGRD day mapped; D-744/D-745 on master; NEW-WIN-10 on master; R2 bundle built; D-502 matrix run (R4) |
| 2026-11-21 | R1: three green nights; R3: P-0 on the owner's PC |
| 2026-11-27 | REDCap zip and workstation order (owner); R2 production start rehearsed |
| 2026-12-11 | GPU run on the product; R6 if the zip arrived |
| 2026-12-18 | Binding order |

## Optimization, after R1 to R6 pass

| What | Measure | Owner |
| --- | --- | --- |
| Throughput | calls/s and tokens/s per setting (NEW-PERF-1, G-3 curve) | G, A2 |
| Night window at 50k and 500k | time per stage (profiling, G-6) | G, B2 |
| Memory | OMOP loader, lake snapshot open, WSL2 share on the workstation | B2, W |
| Accuracy | each set against its validation figure (N-12, TREC, MedTxt) | A2, G |
| Install time | factory Windows to first sign-in (P-1) | W, D |

## Risks, absorbed without asking the site to change

| Risk | How it is absorbed |
| --- | --- |
| Windows 10 at sites | NEW-WIN-10; end of support noted as a site risk, not a refusal |
| CGRD's own codes, dates, joins | the mapping and reader adapt (lane E, A2), measured on the real export |
| Masking gaps in real notes | B2 cards, re-measured by the first-look session after each |
| No read-only database account yet | work from the export; the database run is a five-minute rerun later |
| Model or image advisories | waiver with a review date; vLLM move with G-10 |
