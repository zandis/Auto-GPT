# TB-PLAN-04 Plan v4: the standalone platform

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-04 |
| Version | 1.0 |
| Date | 2026-11-08 |
| Owner | Changfu Kuo (Aimedics) |
| Author | Claude (Fable), lead architect and independent reviewer |
| Status | Approved by the owner 2026-11-08 12:45 (all four decisions as recommended). Living. Replaces TB-PLAN-03 §10 steps 8–11. |
| Basis | `origin/master` 195ea47 (PR #30, steps 0–7); D-112 to D-122; TB-PLAN-03 v0.3 §11; TB-REC-02; the unmerged step-8 work at `plan-8-local` 8a6df59; the review of 2026-11-08 (3.3/5) |
| Rules | No development gates: build and measure on synthetic and public data. Simple plans. Full platform before any formal trial. |

## 1. Verdict

Steps 0–7 did what they said: the five blockers of the review are fixed in code with tests (54 step tests pass on the merged tree), the pair swap is measured with answers checked after a wake, the canary gates exclusions, there is one judge path with coded reasons, the pages are in the reader's language, the lists can be worked through, Hermes and MinIO are gone, and Japan has an SS-MIX2 reader, the full ICD-10-CM and delta loads. The build is now about a 4 and the architecture is right. Three things are still wrong for the platform the owner wants: the box the two first sites will run on (RTX PRO 6000) has no profile and the installer would start it without the pair; the trial data TrialBox itself creates still lives in four SQLite files beside two Postgres databases, so there is no standalone data core yet and no backup; and the Spark profile still names gpt-oss-120b as the judge, against the measured choice. The remaining work is one data core in Postgres, importers with two-way sync for REDCap and spreadsheets (one-way for EMRs), built-in forms, the trial lifecycle on the list-and-task model, and a hardware profile for every box we sell. Nine steps, about 10 weeks of one builder.

## 2. Steps 0–7: keep and fix

**Keep (solid, tested, measured).** Fail-closed code families (D-113); service token and actor header (D-114); two-model rule tested on both paths, min confidence (D-115, D-118); one swap per run, hold and release, wake checks, answers after a wake equal resident (D-116); pair canary gates `may_block`, shown on the admin tile (D-117); one `judge_excerpts`, 16 reason codes with words (D-118); refusal table, note keys, Markdown-free mail, ASCII check in the walk, 422/0 on head (D-119); ready vs needs-information lists, both quotes, S3 explains the list, two-tap outcome, translated labels (D-120); Hermes, front door, relay and MinIO removed, one Postgres server, timers in the box, JP PHI scrubbing, secure-cookie guard (D-121); SS-MIX2 reader with a 400-patient test equal to the CSV funnel, JP mapping template, 98,186-code ICD-10-CM, delta loads (D-122).

**Fix (weak or only partly done).**

| # | Gap | Where | Fix in step |
| --- | --- | --- | --- |
| F1 | No RTX PRO 6000 profile. `install.sh` maps the owner's reference card to `default` (one base model, no pair); the 5090 record demands a real 5090; `docker-compose.gb10.yml` still serves gpt-oss-120b as judge at 64k. | `deploy/install.sh:61–70`, `deploy/docker-compose.gb10.yml:41–45` | 1 |
| F2 | Seven stores: HAPI Postgres, `trialbox_wf` Postgres (steps, outbox), orchestrator SQLite (jobs, candidates), study store SQLite (REDCap link, records), console site store SQLite (marks, outcomes, labels, numbers), console auth SQLite, DuckDB lake, filesystem objects. No backup or restore. | `services/*/db.py`, `studystore.py`, `sitestore.py`, `auth.py` | 2 |
| F3 | The CQL path still reads enumerated lists; D-113 fail-closed exists only in SQL; the equivalence fixtures have no off-list codes. | D-113, D-122 "not done" | 6 |
| F4 | Orchestrator reads stay open on the internal network; no rate limit on reveal. | D-114 "not done" | 6 |
| F5 | JP adapter output still carries TW Core profile URLs; no JP Core resource set; ADT-52, OMP-11/12 and extended-storage documents unread. | D-122 "not done" | 7 |
| F6 | N-12 (TREC) not measured on the deployed files; the pair canary has run on the card once. | report §6 | 6 |
| F7 | REDCap is read-only on master; the write-back and the data core exist only as unmerged WIP (8a6df59) with no API tests and no page. | `plan-8-local` | 3 |

**The step-8 WIP (8a6df59): keep the design, change where it lives.** The design is right and should be kept as is: a REDCap data dictionary becomes FHIR Questionnaires; one `value` row per (study, record, event, field) with who changed it and when; per-field ownership (TrialBox or one source); every change in `history`; conflicts listed, never forced, resolved by a person; one `Source` protocol for REDCap, a spreadsheet and a FHIR bundle; identifiers dropped and chart numbers pseudonymised at import; write-back only of TrialBox-owned fields. Change three things: (1) the tables go into the `trialbox_wf` Postgres database, not a ninth file `datacore.db`; (2) the record key is one rule, written down: screening number first, pseudonym (HMAC of the chart number with the site key) second, otherwise the row is refused and listed, never guessed; (3) merge it only with API tests and the three pages (Sources, Conflicts, Forms) of step 3.

## 3. Design under the standalone decision

**One data core, two kinds of data.** TrialBox holds two things that have different owners and lifecycles. *Clinical facts* come from the hospital (EMR, SS-MIX2, CGRD views, FHIR export); TrialBox only reads them. They stay where they are today: HAPI (FHIR R4, JP Core / TW Core, CQL) and the DuckDB lake the engine runs on. *Trial facts* are created at the site (marks, consent, enrolment, visits, CRF answers, AEs, deviations, screening numbers, people, settings) and TrialBox owns them. They all go into one Postgres database, `trialbox_wf`, in plain relational tables: the data core. Form definitions are FHIR Questionnaires (so REDCap dictionaries and FHIR SDC both map onto them); CRF answers are rows, not QuestionnaireResponse documents, because a long table is what REDCap, ODM export and a conflict list need. FHIR QuestionnaireResponse is an export, generated on request. HAPI stays exactly what it is: the clinical store and the CQL engine. Never two stores of record for the same fact.

**Importers and sync.** Every source implements `pull` and `push`. Ownership is per field and per study. A source-owned field changing at the source is taken; if TrialBox had a different value, that is a conflict. A TrialBox-owned field is pushed when it changed; a different value appearing at the source is a conflict. Conflicts are a list a person works through, like the PI list. Sync direction is a property of the source, not a global rule: REDCap and a PI's spreadsheet are two-way; EMR, SS-MIX2, CGRD and the FHIR export are **one-way in**, because TrialBox must never write to a hospital record system. The two-way sources sync on the box's own timer (03:00, as the REDCap read does today) and on a button.

**Built-in capture, REDCap as an optional source.** TrialBox ships its own forms (screening log, consent, enrolment, visit, adverse event, deviation, withdrawal) in three languages, with type and range checks, a small branching-logic subset and a visible change history. A site with a REDCap project attaches it, imports its dictionary and hands REDCap the fields it owns. No REDCap External Module, no bundled REDCap: the licence forbids it and the box does not need it.

**Lifecycle for the pilot.** Candidate → approached → consented → enrolled → on study → completed / withdrawn / screen-fail; a schedule of visits with windows (due, open, overdue); CRC visit list and visits in the morning mail; AE and deviation entries; PI enrolment report; exports (CDISC ODM 1.3, REDCap CSV, XLSX). **Later, not in this plan:** randomisation, drug accountability, monitoring and SDV, eConsent signatures, a patient-facing portal, sponsor EDC connectors.

**Drop or simplify.** Drop gpt-oss-120b from the Spark profile (the pair runs resident there). Drop the Strix Halo and "5090 + Spark linked" options. Move OMOP export and the LINE/Teams nudge to after the pilot. The Medplum question is closed (TB-REC-02). Keep the v1 evaluator untouched (it serves NAV and CASE). Keep the 18 → 8 document merge, but as the last step and no bigger than it is.

## 4. Steps

Sizes: S ≤ 1 day, M 2–4 days, L 1–2 weeks. One pull request per step; done means the check passes in CI or on the card.

| # | Step | Result | Done-check | Size |
| --- | --- | --- | --- | --- |
| 1 | **Hardware profiles that match the boxes we sell** | `--gpu rtxpro6000` (pair resident, 32k, no swap, auto-detected), `gb10` re-pointed to the measured pair (resident, 16k), `rtx5090` unchanged; a serving record taken on an uncapped PRO 6000 | `install.sh` auto-detects a PRO 6000 and starts the pair; `serving_config measured rtxpro6000` passes; `public_e2e` 94/94 and the pair canary pass on the card (≈ US$6 GPU) | M |
| 2 | **One trial database, backed up** | Orchestrator, study store, site store and auth move from SQLite into `trialbox_wf`; `trialbox backup` and `trialbox restore` cover Postgres (both databases), the lake, objects and the audit | `grep sqlite3.connect services libs` finds nothing; CI restores a backup on the demo image and `e2e_simple` passes on the restored box | L |
| 3 | **Data core and importers** (merges 8a6df59 as changed in §2) | Data-core tables in `trialbox_wf`; REDCap, spreadsheet and FHIR-bundle sources; write-back of TrialBox-owned fields; pages: Sources, Conflicts, Forms; API tests | New `e2e_simple` stage: REDCap off → entries made in TrialBox → REDCap attached → sync pushes TrialBox's fields → a REDCap-side edit of a TrialBox field is listed as a conflict → resolved → pushed; a sheet with a name column imports with the column dropped and the chart number pseudonymised | L |
| 4 | **Built-in data capture** | Seven default forms in ja / zh-TW / en; entry page with type, range and required checks and a branching subset; change history view; ODM 1.3 and REDCap CSV export | A CRC enters a consent and a visit on a 390 px phone in ja; the history shows the edit; the ODM export re-imports into `rc_sim` with every value equal; the walk stays at 0 failures | L |
| 4b | **Easy for novices** (D-133, added 2026-11-08) | The novice UX review's blockers and highs: one-time password out of the URL, "not suitable" needs a reason and has undo, outcomes only after the PI's OK; phone patient sheet with sticky mark bar, 44 px targets, compact headers; set-up wizard and guided REDCap link; one plain vocabulary in en/ja/zh-TW; sign-in lockout and error pages that say what to do | Walk with axe-core: 0 serious/critical, all targets ≥ 44 px, no English on ja/zh-TW pages; tap counts per core task at or below the review's targets | M |
| 5 | **Trial lifecycle v1** | Subject state machine; schedule of events per study (defined in TrialBox or imported from REDCap arms/events); visit windows; CRC visit list; visits in N1/N2; AE and deviation entries; enrolment report | New `e2e_simple` stage: enrolled → visit due → overdue → done → AE logged → withdrawn; screening log, enrolment report and REDCap read-back agree on every count | L |
| 5b | **Site setup and data harmonization** (D-131, D-132; added 2026-11-08; novice users, imperfect data) | Readiness page (trial, patients, trial records: green / amber / red with what's missing); chart upload one by one (text, Word, PDF, scans with OCR, pasted EMR text) with LLM extraction into *proposed* facts beside their quotes; CRC confirm or correct in one tap; once-per-site local code mapping; patients from several inputs joined by pseudonym | New `e2e_simple` stage: a site set up from a protocol, a CSV feed, a sheet and two uploaded charts; a proposed fact only sends to "needs information" until confirmed, then counts; the readiness page goes green. D-132: setup wizard, ask-the-box assistant, templates and practice site, safe auto-fixes listed (era/民國 dates, full-width, units, merged cells) and a "please check" list for the rest; a site can start with a protocol and pasted charts only | L |
| 6 | **Screening engine finish** | SQL is the only runtime engine; CQL kept for the compile-time equivalence gate (decision 3); fixtures with off-list codes; orchestrator reads behind the token; reveal rate limit; N-12 on the card | Equivalence gate green on off-list fixtures; `GET /jobs` without the token → 401; N-12 recorded in `eval/parity` (≈ US$4 GPU) | M |
| 7 | **Japan completeness** | JP Core profiles on adapter output, validated on a sample at ingest; loader for licensed MEDIS / JLAC10 / YJ files; ADT-52, OMP-11/12; extended-storage documents | Synthetic SS-MIX2 hospital → JP Core `$validate` passes on the sample; a licensed-file loader test with a 10-row sample; GOUT-COH funnel unchanged | M |
| 8 | **Handover** | `install.sh --tier small\|medium\|large` from measured records only; one-page network, port and secret sheet; update path exercised on the demo image; log retention | Install refuses an unmeasured tier; `apply_update` on the demo VM then `e2e_simple` passes; the sheet lists every listening port | M |
| 9 | **Complete-platform run and documents** | One scripted run on the PRO 6000 over the 50k synthetic hospital and the public site through every stage of §5, ja and zh-TW; walk re-run; documents merged 18 → 8; independent re-review | Run report with a screenshot per stage from head; doclint clean; each of the eight documents ≥ 4.5 and the build ≥ 4.5 by the review's yardstick | M |

Order: 1 → 2 → 3 → 4 → 4b → 5 → 5b strictly (each needs the one before). 6 and 7 run in parallel with 3–5. 8 and 9 last. About 10 weeks of one builder, under US$15 of GPU time.

## 5. What "complete platform" means

The box is complete when, on synthetic and public data, with no person from Aimedics present, a site can: install from the signed bundle on any of the three measured boxes; import its hospital data (SS-MIX2, CGRD, FHIR) nightly; paste a protocol and approve criteria with labels in its language; run screening with the pair and the canary gate; work the PI and CRC lists on a desktop and a phone in ja or zh-TW; record consent, enrolment, visits, AEs and deviations in TrialBox's own forms; attach a REDCap project or a spreadsheet and sync it two-way with conflicts listed; receive the morning mail from the box's own timer; export ODM, REDCap CSV and XLSX; back up and restore; update; and show an auditor the hash-chained log for every step above. Step 9 proves all of it in one run; until that run is green the platform is not complete.

## 6. Owner decisions (approved 2026-11-08 12:45, all as recommended)

| # | Decision | Approved answer |
| --- | --- | --- |
| 1 | Where CRF answers live: TrialBox's own Postgres tables (FHIR Questionnaire for the form, rows for the answers, FHIR export on request), or HAPI QuestionnaireResponse as the store of record. | **Own tables.** REDCap dictionaries, ODM export and the conflict list are row-shaped; HAPI stays the clinical store and CQL engine. Two stores of record for one fact is the thing to avoid. |
| 2 | Sync direction for hospital systems: one-way in only, or allow TrialBox to write to the EMR / SS-MIX2 / CGRD. | **One-way in.** TrialBox never writes a hospital record. Two-way is for REDCap and spreadsheets. |
| 3 | The CQL path: make it fail closed like SQL (keep two runtime engines), or declare SQL the only runtime engine and keep CQL only in the compile-time equivalence gate. | **SQL only at runtime, CQL in the gate.** One engine to test; the gate keeps its value. |
| 4 | Lifecycle scope for v1: the list in §3, or add randomisation. | **The list in §3.** Randomisation, drug accountability, SDV, eConsent and a patient portal come after the first pilot has run on the platform. Spark stays a measured profile but is measured only when a site orders one. |

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-08 | Claude (Fable) for Aimedics | First draft from the review of PR #30, the step-8 WIP at 8a6df59 and the owner's standalone decision. |
| 2 | 1.0 | 2026-11-08 | Claude for Aimedics | Owner approved all four decisions: CRF answers in own Postgres tables; hospital systems one-way in, two-way only REDCap/spreadsheets; SQL only runtime engine with CQL in the gate; v1 lifecycle scope as §3, Spark measured on order. Step 6 wording fixed to decision 3. Starter prompt: STARTER-PROMPT-plan-v4.md. |
| 3 | 1.1 | 2026-11-08 | Claude for Aimedics | Step 5b added (owner, D-131): site setup and data harmonization. |
| 4 | 1.2 | 2026-11-08 | Claude for Aimedics | Step 5b widened (owner, D-132): novice users and imperfect data. |
| 5 | 1.3 | 2026-11-08 | Claude for Aimedics | Step 4b added (owner, D-133): easy for novices. |
