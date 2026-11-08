# TB-DS-20 Build map (the living page)

| Field | Value |
| --- | --- |
| Document | TB-DS-20 Build map |
| Version | 1.3 |
| Date | 2026-11-07 |
| Owner | Changfu Kuo (Aimedics); kept current by Claude while building |
| Status | **Living.** This is the one page kept current during the build. TB-DS-01..19 are frozen as reference (TB-REV-006f §4.4). Build decisions go into the code's `docs/DECISIONS.md` as D-nnn entries, not into TB-DS revisions. |
| Plan | `SIMPLE-PLAN.md` (five steps, each one pull request) |
| Review | TB-REV-006f (`06f-final-design-review.md`), findings F6-01..F6-30; TB-REV-006g document-quality audit (Q-36, Q-37) |
| Version rule | Living build document: issued at 1.0; the owner's merge of a step PR that uses it is its approval (TB-DS-12 §6). |

### Approvals

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Prepared | Claude (for Aimedics) | Prepared | 2026-11-07 |
| Approved | Changfu Kuo, product owner | By merge of the first step PR (TB-DS-12 §6) | — |

## 1. The rule

During the build nothing is a gate except `e2e_simple` (step 5) and the TrialGPT benchmark not getting worse. Everything is built and tested on synthetic and public data. Items that matter only when a hospital uses real patient data are tagged **H** and wait for that day. Items for later are tagged **L**. Nothing was deleted from the reference documents.

| Tag | Meaning | Count in TB-DS-01 v0.12 §3 |
| --- | --- | --- |
| S0 | Built today; kept working by the existing tests | 57 |
| S1 | Step 1 Feasibility | 36 |
| S2 | Step 2 List and mail | 58 |
| S3 | Step 3 REDCap | 17 |
| S4 | Step 4 Homes, command field, languages | 35 |
| S5 | Step 5 End-to-end test and demo | 9 |
| H | Hospital stage, real patient data | 229 |
| L | Later | 155 |
| — | Withdrawn rows, St W (FR-SCR-09, FR-SEC-11, NFR-USAB-02, NFR-COMP-02, NFR-COMP-08) | 5 |
| | **Total §3 rows (FR, NFR, DR, IR)** | **601** |

How the counts are made: `python3 tools/gen_trace.py --counts` (run from any directory) counts every row of TB-DS-01 §3 whose first cell is an FR-, NFR-, DR- or IR- ID by the first tag in its Pri cell, and counts rows with St W as withdrawn (the SC column is skipped in the FR-SEC table). Split rows (letter suffixes, "(split from …)") follow their root row's tag, and rows named in §2 by their root ID include their split rows (for example FR-SCR-07 includes 07d–07f, FR-UI-01 includes 01a). Re-run the command after any SRS change; the table above is its output for v0.11.

Each SRS priority cell keeps its old tag as "(was M1)" and so on. Default rule used for re-tagging: built → S0; named below → its step; old M1 not named → H; old M2 or C → L; security controls (FR-SEC) → H.

## 2. The five steps

Every step is one pull request. "Done" means: the demo path works, the listed test passes, and the benchmark has not got worse.

| Step | You can see | Requirements | Screens | Done when | Not in this step |
| --- | --- | --- | --- | --- | --- |
| **1 Feasibility** | Paste criteria → report with a funnel, on the synthetic hospital | FR-FEAS-01a/b/c, 02, 03, 04a–i, 05, 06, 07, 11; FR-ING-01, 02, 08a/b, 12; FR-DEID-01, 11b; **FR-SYN-01..04** (synthetic hospital, TB-DS-21); FR-OPS-12 (on-demand schedule in DEV) | S2 input, S3 report (with Refresh in step 2), S4 study list | Demo: open S2, paste the GOUT-COH criteria, get the S3 funnel on 5,000 synthetic patients in JA. Test: FEAS e2e (exists) plus generator gold check. 500,000-patient generation runs once on the demo VM. | Sponsor release FR-FEAS-08 (H); FR-FEAS-09/10 (L); external k = 10 (H) |
| **2 List and mail** | Approve criteria on one page → patient list → PI mail before clinic, CRC daily summary | FR-FEAS-12 (one page, one Approve), FR-FEAS-13 (Refresh); FR-SCR-01, 02a/b, 03, 05, 06, 07 (incl. replace a mark), 10a/b/c, 11, 12; FR-STUDY-01, 02, 08, 09 (registries get a cohort list, no contact step); FR-NOTIF-01, 02, 09 (N1 clinic-day list, N2 CRC digest); FR-UI-05, 06, 17 (no scores or model names on clinical screens); FR-MAIL-02..04; FR-AUTH-13 (only the investigator approves); FR-REP-09 (research-office yearly counts) | S5 patient sheet, S6 marks, S7 list, S20 approval (one page), S18 PI list mail | Demo: approve GOUT-COH and one trial ruleset, open the list, mark three patients, receive N1 and N2 in Mailpit. Test: console tests + SCREEN tests. Benchmark: SIGIR lost pairs ≤ baseline + 1 (N-11). | Ethics gate FR-STUDY-06 (setting, off in DEV); "Ask treating doctor" routing FR-SCR-07b/07c (L); comparison log FR-SCR-13 (H); N3, N4, budgets, quiet hours, snooze, deputy (H) |
| **3 REDCap** | TrialBox reads consent, enrolment, screen-fail and withdrawal from REDCap into the screening log | FR-RC-01, 02, 03a, 09, 10, 14, 15, 16, **FR-RC-17 simulator** (TB-DS-08 §4.4); FR-STUDY-07 (S21 cut to three sections); FR-PLAT-10 (token and test only) | S21 study set-up (3 sections), S36 REDCap connection (token + test) | Demo: link the fixture project by `tb_screening_no`, change a status in the simulator, see it in the log next morning (or on Run now). Test: ICD-04 conformance on two fixture projects. | External Module, writes, DET (L); MRN link mode (H) |
| **4 Homes, command field, languages** | One home per role, a header command field on every page, Japanese, Chinese and English everywhere | FR-UI-01 (home = role work list; header field), 04a, 14, 15, 16, 18, 19; FR-CHAT-01..06 (parser = mail grammar); FR-I18N-01..04; FR-JP-01, 02, 08; FR-PLAT-04, 08, 12 (Cancel + Retry), 14 (search in the header field), 17, 19 | S16 PI home, S8 CRC home, S13 admin (tabs: health, jobs S26, data sources S24), S3 viewer/cro, S22 My account, S29 Help panel, S37 Notices received; header field replaces S1 and S28 | Demo: sign in as each of the five roles in three languages on desktop and phone. Test: browser walk (exists on branch) + command test set ≥ 95 % right, 0 % wrong. First task: rebase `38d93ce` onto master and merge it. | S17 reconciliation (L); S19 beyond day and time (H); the other platform pages (H/L) |
| **5 End-to-end and demo** | `e2e_simple` green on every build; a demo link on the cloud VM; TrialGPT parity; real-card measurement | FR-OPS-11 `e2e_simple` (TB-DS-04 §3.4.1); FR-REP-01, 02; FR-AUD-01a/b/e; NFR-PERF-08, 09 (N-11, N-12); FR-MOD-10 (real 5090 fit measured) | — | `e2e_simple` passes in CI; demo VM started on request; N-11 passes in EN, JA and zh-TW (zh-TW ≤ 2 provisional) and N-12 passes; the run records its serving configuration (card, vLLM version, max-model-len, max-num-seqs, eager flag, memory fractions, model-file sha256); the 32 GB fit result is written into TB-DS-02 ADR-03. | `e2e_full` (three sites, hub, GUID), pentest, IQ/OQ/PQ (H/L) |

## 3. Decisions taken in this pass (from TB-REV-006f)

| Finding | Decision |
| --- | --- |
| F6-03 | The ethics gate is the site setting `ethics_gate`: off with `TB_ENV=DEV` or `TEST`, on by default in `PRODUCTION`. The S21 ethics section shows only when it is on. |
| F6-04 | TOTP, the TOTP step-up, the `auditor` role, the breached-password file, the monthly access report, the pentest and the TB-DS-03 §15.1 go-live list are H. Built login, roles, scopes, expiry, lockout, sessions and CSRF stay (S0). Tap budgets no longer count TOTP. |
| F6-06 | The home is the role work list. The chat box is a header command field on every page; it also searches. S1 and S28 are no longer screens. The tiles become the "More" menu. |
| F6-07 | Ruleset approval is one page with one **Approve all** by the investigator. Codes are folded under each row; a coordinator may pre-tick them (own audit event). A re-approval shows **Changes since vN**. |
| F6-08 | Platform pages in the build: S22, S24, S26, S29, S37 (plus S36 token test in step 3). The rest: H, or L for S27 archive, S30 About and print views. CLI tools stay the admin path. |
| F6-09 | Step 2 builds two mails: N1 (PI list on clinic days, Monday fallback) and N2 (CRC digest). The other notice features are H. |
| F6-10 | Registries (RA-BIO, RA-COH, GOUT-COH) get a cohort list in step 2: new members, no contact step. Reconciliation is L. |
| F6-11 | Pilot measurement (chart review, SUS, NASA-TLX, time-motion, comparison log, pilot metrics report) is H. The build measures TrialGPT parity and `e2e_simple` only. |
| F6-12 | "One RTX 5090" is a target, not a fact: both models resident took 35 GiB on 6 November (mostly vLLM pre-allocation; weights 17.1 + 7.5 GiB) on an RTX PRO 6000 capped to 5090 limits, against the card's 32 GB, and the swap controller does not exist. Measured in step 5 (FR-MOD-10). |
| F6-13 | `e2e_simple` (one site, stub model, REDCap simulator) is the only build gate. `e2e_full` is H/L. |
| F6-14 | Study and notification settings live in the orchestrator store; the console edits them through the orchestrator API (TB-DS-07 updated). |
| F6-19 | Five roles in the build: admin, coordinator, investigator, viewer, cro. `auditor` and the research-office `office` flag are H. |
| F6-20 | Translations stay in the Python catalogues (`i18n.py`, `i18n_home.py`) with the every-key-every-language test. No JSON move. |
| F6-22 | `confidence` and the judge model name leave `patient.html` in step 2, in the same pull request as the mark vocabulary. |
| F6-23 | Branch `claude/project-thread-0iudms` (`38d93ce`) is behind master by PR #19 and PR #21. Rebase onto master, re-run `tests/console`, merge as the first pull request of step 4 (or of step 2 if S5 needs it first). |
| F6-24 | Consent explainer: draft (built) plus the on/off setting only. Approved-file hash, sponsor approval and automatic go-live (FR-CON-06, 08, 09, 10) are H. |
| F6-26 | Command phrasings are written by the builder; site staff add phrasings at install (H). |
| F6-27 | Four small functions added: replace or withdraw a mark (FR-SCR-07), Retry a failed job (FR-PLAT-12), Changes since vN on S20 (FR-FEAS-12), Refresh a feasibility report (FR-FEAS-13). |
| F6-30 | The night schedule is a setting; DEV runs on demand (FR-OPS-12). |
| F6-29 | Step 4 ships the proposed JA and zh-TW mark labels from TB-DS-09 §6; native review of the labels (OQ-14) is H. |
| §5 note | FR-REP-09 (research-office yearly counts export) is in step 2, not H. |

## 4. Where the decks differ from the design (fix the decks later)

The two decks shown to Dr Higuchi (`trialbox-deck/trial-ready-cohort-AD.pptx`, `trialbox-introduction.pptx`) differ from the design on these points. The design decision is given; the deck should be corrected at its next revision.

| # | Deck says | Design decision |
| --- | --- | --- |
| 1 | Intro b1: weekly PI list "every Monday" | PI list on each clinic day, with Monday as the fallback when clinic days are unknown (keep the design). |
| 2 | Intro b1 step 2: the investigator "signs off the sheet once per protocol version" | Agrees with the new one-page approval (F6-07). The deck is right; the design changed to match. |
| 3 | Intro b1 note: "Steps 1 to 3 need no GPU" | Counts need no GPU card, but the criteria draft uses the local model. Correct the note to "counts need no GPU card; the criteria draft uses the local model". |
| 4 | Intro b2: four homes plus a "study office" home (slide 6) | Five roles in the build; the study-office home is H. |
| 5 | Intro c3, AD d1: the pair does not fit a 5090 yet (35 GB) | Agrees with F6-12. The design now says the same; SIMPLE-PLAN softened to "target". |
| 6 | AD b2: five-step lifecycle; intro b1: six steps | The built six-step bar (`_steps.html`) is the procedure bar in the product; SIMPLE-PLAN's five steps are the build order; TB-DS-17 §4 stays the detailed cycle. |

## 5. Hospital stage, in one place

When a hospital chooses to use real patient data, these switch on, in this order: TOTP; `ethics_gate` on; the hospital's own data source and code mapping; the opt-out page; backup and test restore; the IQ/OQ/PQ check (TB-DS-15); the two-page description for the PI (TB-TMPL-01 §0). The two-phase pilot (BD-16) and its measurement apply only if the hospital wants a formal pilot. Everything tagged H in TB-DS-01 is the full list.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 1.0 | 2026-11-07 | Claude for Aimedics | First issue from TB-REV-006f: tags, five steps with done-when lines, decisions F6-03..F6-30, deck differences, hospital-stage list. |
| 2 | 1.1 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-36/Q-37: tag counts regenerated from TB-DS-01 v0.10 (480 rows; count rule stated; command `python3 -c` over §3 rows of `01-SRS.md` matching `^\| (FR\|NFR\|DR\|IR)-`, first tag of Pri); split-row rule; version rule and approvals block; Seq column. |
| 3 | 1.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R (R-33) and TB-REV-006f §8 (L8-05): counts regenerated from TB-DS-01 v0.11 with `tools/gen_trace.py --counts` (600 rows), named as the method; TB-DS-04 §3.4a → §3.4.1; step 5 done-when adds zh-TW and the recorded serving configuration; F6-12 line in GiB with the 6 Nov card stated. |
| 4 | 1.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §F: counts regenerated from TB-DS-01 v0.12 with `tools/gen_trace.py --counts` (FR-SEC-05a added: H 229, total 601). |
