### 10.6 M6 — Consent, enrollment tracking and forecast ledger

**Conventions for §10.6–§10.12.** Each module has the same layout: purpose, inputs and outputs, LLM roles, requirements,
acceptance metrics, and the disposition of its v3 IDs. Role names are those of the §8 role table, and §8 governs if a
name differs. "Class" is the data class (D0–D4) of the data the role is shown. The gateway enforces it (§8). D3 and D4
never reach an external model, in any topology. Milestones (R column) follow §20. Where a v3 requirement keeps its
text, it keeps its ID and only its milestone is re-planned against §20. v3 R0, R1a, R1b, R2, R3 and R4 correspond
roughly to MS0, MS1, MS2, MS4, MS5 and MS6, and some rows move earlier where the v4 plan needs them sooner (for
example FR-M7-11, the blinding firewall, at MS1). Targets marked *(target)* are acceptance targets, not measured results.

**Purpose.** M6 keeps the per-study participant pipeline, from the first pre-screening hit to randomisation or exit. It
tracks IRB-approved consent versions and re-consent. It forecasts accrual against target with stated intervals, and it
stores every forecast that the box, the PI or the sponsor ever issued, so that each one can be scored against what
actually happened. M6 is the record of the site's *operational* pipeline only. It never records eligibility
determinations, randomisation arms or consent signatures. Those stay in the sponsor's EDC/IRT and in the hospital's
document system (§2 non-goals).

**Why.** Tufts CSDD (2013; 150 trials, more than 16,000 sites) found that 11 % of activated sites enrol nobody, 37 %
under-enrol, 39 % meet target and 13 % exceed it (secondary source). PI enrolment forecasts score a Brier of 0.38
(PLoS One 2022, doi:10.1371/journal.pone.0262862). No published work reports a prospectively calibrated site-level
forecast. The closest model result is Deep Poisson-Gamma, a retrospective study-duration model with an MAE of 7.52
months (arXiv 2507.23607, preprint). Reify/OneStudyTeam already tracks enrolment at 1,800–2,700 sites (trade press),
but it does no EHR screening. M6 differs from it in two ways: its pipeline starts at the EHR-derived pre-screen hit,
and its forecasts are scored in the open.

**Inputs and outputs.**

| Dir. | Item | Source or target | Class |
| --- | --- | --- | --- |
| In | G3 decisions, candidate tier and evidence references | M4/M5 (§10.4, §10.5) | D3 |
| In | G4 state lines (reply grammar, Hermes proposal, decision sheet, review page) | CRC, PI | D3 |
| In | Recruitability model and feasibility projection | M3 (§10.3) | D1 (aggregate) |
| In | CTMS or IRB enrolment exports, read-only | L0 file contract (§5) | D4 → L3 → D3 |
| In | Consent versions (`CONSENT GZQO v3.0 effective 2026-09-15`, or IRB letter import) | CRC, IRB | D1 |
| In | PI estimate and sponsor target | reply line at feasibility; Study Card | D1 |
| Out | Pipeline in the Study Card; FHIR `ResearchSubject` on the L5 read API | Study Card (§6); delegated staff | D3 |
| Out | Monday status digest; monthly portfolio report | CRC/PI; research office | D3 internal; D1 |
| Out | Accrual-pack data (§12) | sponsor, after G2 | D1 |
| Out | Forecast-ledger rows and scores | research office; M3 site history; feasibility-pack calibration plot | D1 |

**LLM roles.** No model computes a number in M6.

| Role | Use in M6 | Class | Route |
| --- | --- | --- | --- |
| `classify_intent` | Turns free-text state messages ("P0156 signed ICF v3 today") into a G4 proposal | D3 (carries pids) | on-prem only |
| `draft_narrative` | Commentary for the accrual pack and the portfolio report, written through placeholders | D1 (aggregates) | per routing policy; cloud only in topology C |

**Requirements.**

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M6-1 | Pipeline states: `prescreened → contacted → consented → screened → randomized`. Exits: `declined`, `screen_failed(reason)`, `not_contactable`, `withdrawn`. Transitions after `prescreened` MUST be G4 approvals (by reply line or sheet). | T | MS3 |
| FR-M6-2 | The Monday status email per study MUST show the pipeline, reasons, forecast p10/p50/p90 against target, an early warning when p50 < 80 % of plan for two consecutive weeks, and what is due this week (§10.7). | T | MS4 |
| FR-M6-3 | A monthly portfolio report for the research office MUST rank studies by risk of under-enrollment, using the hierarchical forecast. | T | MS4 |
| FR-M6-4 | The box SHOULD import enrollment from the hospital CTMS or IRB system (read-only) and reconcile it with its pipeline, listing mismatches. | T | MS5 |
| FR-M6-5 | Site history (consent rate, screen-fail rate, time to first patient per area) MUST be derived from closed studies and feed FR-M3-3. | T | MS4 |
| FR-M6-6 | **Consent versioning.** The Study Card tracks IRB-approved consent versions. When a new version becomes effective, the box MUST list enrolled participants who need re-consent and track the G4 approval of each re-consent. | T | MS4 |
| FR-M6-7 | **Forecast scoring.** At feasibility, the PI's own enrollment estimate MAY be recorded (one reply line). At close, the box scores the box forecast and the PI estimate (Brier/CRPS) for the research office. | T | MS4 |
| FR-M6-8 | **Structured exit reasons.** `screen_failed` MUST carry one or more criterion ids of the bound ruleset version, or `other` with text. `declined` MUST carry a decline code: D01 not interested, D02 visit burden, D03 travel, D04 family decision, D05 prefers standard of care, D06 other with text. `withdrawn` MUST carry W01 consent withdrawn, W02 investigator decision, W03 lost to follow-up, or W04 other with text. These reasons feed the screen-fail Pareto (§12), the criterion library's precision history (§10.1) and the ever-excluded enrollee check (SAFE). | T | MS3 |
| FR-M6-9 | **Transition validation.** Only the transitions of FR-M6-1 are accepted. Dates MUST NOT lie in the future and MUST be monotonic along a participant's path. A transition sent by a person whose delegation or training has lapsed MUST be refused (FR-M7-4), and the reply MUST say why. A correction MUST be a new event with reason `correction` that references the event it corrects; no event is ever edited. | T | MS3 |
| FR-M6-10 | **FHIR view.** The pipeline MUST be exposed as FHIR R4 `ResearchSubject` resources with this status mapping: prescreened → `potential-candidate`; contacted → `candidate`; consented → `pending-on-study`; screened → `screening`; randomized → `on-study`; screen_failed → `ineligible`; declined and not_contactable → `not-registered`; withdrawn → `withdrawn`. The value `ineligible` is written only from an investigator's G4 line, and the box MUST NOT write `eligible`. | T | MS4 |
| FR-M6-11 | **Accrual forecast.** Before the first consent, the forecast MUST use the recruitability model of M3 as its prior. After activation, it MUST be a per-study Poisson–Gamma accrual model (Anisimov & Fedorov, Stat Med 2007), updated monthly with actuals in the Bayesian manner of Gajewski et al. (Stat Med 2008). Outputs: p10/p50/p90 cumulative enrolment per month and P(target reached by planned end). The computation MUST be seeded and byte-reproducible, and the method and parameters MUST be printed in every output. | T, A | MS4 |
| FR-M6-12 | **Forecast ledger.** Every forecast issued MUST be stored as an immutable ledger row. This covers the feasibility-pack projection, each monthly re-forecast, portfolio rankings, the PI estimate and the sponsor target, with fields `forecast_id, study, issuer (model version, or PI/sponsor), issued_at, horizons, quantiles, inputs_hash, snapshot_id, ruleset_version`. A protocol amendment creates new rows, and no row is ever edited. Code: `services/tracking/ledger.py`. | T | MS1 |
| FR-M6-13 | **Scoring.** At every 3-month horizon and at close, the box MUST score each ledger issuer: CRPS for the cumulative count at each horizon, Brier for "target reached by planned end", and a PIT histogram. Once ≥ 5 studies have closed, the site's calibration plot MUST be available to the feasibility pack (§12). | T | MS4 |
| FR-M6-14 | **Re-consent.** When an amendment changes the ICF, the box MUST open one G4 re-consent task per affected participant, due at the participant's next scheduled visit (playbook parameter). A participant still on the superseded version after that visit MUST be listed as a deviation candidate (FR-M7-31). The count of such participants is the consent-version-lag KRI (FR-M7-25). | T | MS4 |
| FR-M6-15 | **Consent event capture.** A consent event MUST record the ICF version, the date, the person who obtained consent (who MUST be delegated for consent in the delegation log), a legally-authorised-representative flag and "copy given: yes/no". The signed ICF stays in the hospital document system. The box stores only its location and hash in the ISF index (FR-M7-10). | T | MS4 |
| FR-M6-16 | **Provenance of each participant.** Every pipeline entry MUST link to the candidate record that produced it (run id, ruleset version, tier, evidence ids), or carry `source: external_referral | clinic_direct`. The share of randomised participants the box did not find MUST be reported monthly as a blind-spot metric, alongside the SAFE ever-excluded check. | T | MS3 |
| FR-M6-17 | **Competing allocation.** When a person is G3-confirmed for two or more recruiting studies, the digest MUST list the conflict to the PIs concerned, together with the site allocation rule from the playbook (for example a PI priority list). The box MUST NOT choose the study. | T | MS4 |
| FR-M6-18 | **Representativeness tracking.** Enrolled participants against the eligible pool, in coarse categories (age band, sex, and others the site configures), with small-cell suppression and rounding (§7), for the accrual pack (§12). | T | MS4 |

**Acceptance metrics.**

| Metric | Target | Measured by |
| --- | --- | --- |
| Randomised participants matched at CTMS/IRB reconciliation | ≥ 0.99 per month *(target)* | FR-M6-4 report |
| State messages turned into correct G4 proposals | ≥ 0.98 on the bilingual intent set (§16) | `intent_ml` suite |
| Illegal transitions accepted | 0 | property tests on the state machine |
| Forecast calibration after ≥ 10 closed studies | slope 0.8–1.2; empirical p10–p90 coverage 0.70–0.90 *(target)* | FR-M6-13 |
| Box forecast compared with the PI estimate | box CRPS ≤ PI CRPS on the same studies *(target)* | FR-M6-13 |
| Monday digest delivered by 09:00 local time | ≥ 99 % of Mondays | outbox timestamps |

**Disposition of v3 IDs.** FR-M6-1…7 are kept. **Code.** `services/tracking/` (`pipeline.py`, `consent.py`,
`forecast.py`, `ledger.py`, `reconcile.py`, `fhir_research_subject.py`). The pipeline and ledger tables are defined in §6.

---

### 10.7 M7 — Start-up and conduct (deterministic lifecycle engine with playbooks)

**Purpose.** M7 runs the site's obligations for a study from selection to close-out. It covers IRB and contract
milestones, delegation and training, visit windows, safety clocks, IP and kit logistics, participant reimbursement
reminders, retention, risk indicators, essential-record completeness, monitor and DSMB support, and the sponsor-query
SLA. M7 is where coordinators spend their time, and the v3 coverage there was one line per stage (R3-39). Every M7
behaviour is a **calendar item** (`calendar_item`, §6). Calendar items are computed by a deterministic engine from four
inputs: the Study Card, the schedule of activities (SoA), the delegation log, and hospital playbooks
(`site/playbooks/*.yaml`). **Scheduling, clocks, reminders and KRIs use no model time.** LLM roles appear in only
three places:
- extracting playbook *parameters* from documents, with G1 confirmation;
- drafting documents;
- summarising untrusted inbound sponsor mail in a quarantined extractor.

**The playbook model.** A playbook is versioned YAML, validated against `schemas/playbook.schema.json`. The product
ships the defaults, the hospital edits copies in Git through the admin (FR-M7-1), and each study binds one playbook
version per stage at G1. The excerpt below is illustrative.

```yaml
# site/playbooks/conduct.default.yaml
playbook: conduct
version: 2.1.0
params:                                  # bound per study at G1; values here are defaults
  sae_to_sponsor_hours: 24               # from the protocol
  sae_to_irb: {working_days: 7}          # from the hospital IRB SOP; the site sets it
  query_sla_working_days: 5              # from the CTA
  kit_expiry_warn_days: 30
tasks:
  - id: visit_window
    for_each: planned_visit              # from the SoA schedule (FR-M7-17)
    when: {event: window_open, offset: -3d}
    owner: role:CRC
    due: {event: window_close}
    remind: [-3d, 0d, {event: window_close, offset: -1d}]
    closes_on: [{encounter_in_window: true}, {reply: "VISIT <pid> <visit> done <date>"}]
    on_overdue: {deviation_candidate: visit_out_of_window}
  - id: sae_sponsor_clock
    when: {event: sae_awareness}
    owner: role:PI
    due: {offset_hours: "${sae_to_sponsor_hours}"}
    remind: ["50%", "90%"]
    closes_on: [{reply: "SAE-SENT <sae_id> sponsor <datetime>"}]
    escalate: [role:SubI, role:research_office]
```

A calendar item moves through `planned → open → due → overdue → done | waived(reason, role) | cancelled`. Its key is
`(study, playbook_id, task_id, occurrence_key)`, so evaluating the playbook again never duplicates an item. The engine
runs daily, and it also runs on events: a Study Card change, an amendment, an HL7 v2 ADT or SIU message, a G4
transition, or a document indexed.

**Inputs and outputs.**

| Dir. | Item | Source or target | Class |
| --- | --- | --- | --- |
| In | Study Card, bound playbooks, SoA (USDM v4, HL7 Vulcan SoA `PlanDefinition`, M11 SoA table, or extracted) | §6; M1 | D1 |
| In | Delegation log and training records (XLSX/CSV contract) | research office | D1 (staff data) |
| In | Encounters, orders, appointments, ADT; hospital-flagged events | L5 snapshot, HL7 v2 (§5) | D3 |
| In | Pharmacy dispensing log, IP receipts and returns, temperature-alarm feed (CSV/email/syslog contracts) | pharmacy | D3 / D1 |
| In | EDC query report export; sponsor and monitor e-mails | sponsor systems via CRC; CDR-converted mail | D3 |
| Out | Reminders, clocks, task lists, checklists, packs, IRB packages, KRI tables | CRC, PI, pharmacist, research office | D3 internal |
| Out | KRIs and start-up durations to the digest, the site-performance pack (§12) and site history | §12; M3 | D1 |

**LLM roles.**

| Role | Use in M7 | Class | Route |
| --- | --- | --- | --- |
| `extract_soa` | SoA, lab manual, ICF payment table and CTA SLAs from PDF/DOCX into playbook parameters; always confirmed at G1 | D1 | per routing policy |
| `draft_document` | IRB form text, continuing-review narrative, CAPA wording | D1 (aggregates only, no pids) | per routing policy |
| `summarise_external` | Quarantined, tool-less summary of sponsor and monitor e-mails into action items and queries | D3 (mail may name sponsor subject ids) | on-prem only |
| `judge`, `second_opinion` | Refresh of the screening-visit checklist with the screening anchor (FR-M7-18) | D3 | on-prem only |

**Requirements.**

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M7-1 | **Playbooks.** A YAML playbook per stage (start-up, conduct, close) defines tasks, owners (role), due rules (relative to study events), reminders and document templates. The hospital edits playbooks through Git via the admin. The defaults ship with the product. | T | MS4 |
| FR-M7-2 | **IRB package pre-fill.** From the protocol digest and Study Card, the box MUST pre-fill the hospital IRB application template (DOCX) fields it can source, list the rest, and track continuing-review (持續審查) and final-report due dates. | T | MS4 |
| FR-M7-4 | **Delegation and training.** The box MUST track delegation-log entries, GCP training certificates and their expiry. It reminds the CRC 30 days before expiry and blocks gate approvals by people whose delegation or training has lapsed. | T | MS4 |
| FR-M7-5 | **Visit windows.** For enrolled participants, visit due dates and windows MUST be computed from the SoA and the randomisation date. The CRC is reminded before a window opens and before it closes. Likely deviations (visit outside window, missed procedure, detected from hospital encounters and orders) are listed for CRC confirmation. | T | MS5 |
| FR-M7-6 | **Deviation log and CAPA.** Confirmed deviations MUST be logged with category, root cause and CAPA owner and date. Approval is a Level B signature (FR-SIG-1). The log is exportable for the sponsor and the IRB. | T | MS5 |
| FR-M7-7 | **Safety clocks.** When the CRC records a suspected SAE (`SAE P0156 2026-10-17 <one line>`), the box MUST start the **site's** clocks, labelled by owner: investigator to sponsor (per protocol, typically 24 h), and investigator to IRB (per hospital IRB SOP). The sponsor's 7/15-day clocks to TFDA are the sponsor's obligation; the box records them only for information. It reminds the owner at 50 % and 90 % of each clock and records completion. | T | MS4 |
| FR-M7-8 | **Hospital-flagged events.** For enrolled participants, the box MUST list new ED visits, admissions and critical lab values **already flagged by hospital systems**, within one ingest cycle, as items for investigator review. The box does not grade or attribute events (§15). | T | MS5 |
| FR-M7-9 | **Monitoring-visit pack.** Before a monitor visit (`MONITOR GZQO 2026-11-04`), the box MUST assemble: source packets per participant and visit (M8), the deviation log, open queries, the delegation log and the ISF index. | T | MS5 |
| FR-M7-10 | **ISF index.** The box MUST keep an investigator site file index per E6(R3) essential-record categories, with document versions and locations (the documents stay in the hospital's document system). | T | MS4 |
| FR-M7-11 | The box MUST NOT access treatment-arm data or IRT unblinding fields. | T, I | MS1 |
| FR-M7-13 | **Engine determinism.** The same Study Card, playbooks, SoA, delegation log and event stream MUST produce the same calendar items, byte for byte. `trialbox playbook simulate <study> --from <date> --to <date>` MUST print the items, reminders and escalations for a period without sending anything. | T | MS4 |
| FR-M7-14 | **Playbook validation.** Binding a playbook (G1) MUST fail on: a schema violation; an unknown event; an owner role absent from the delegation log; cyclic dependencies; a reminder after its due time; or a template that references a missing field. A change to a bound playbook takes effect only after the study is bound again. Default playbooks shipped with a release are G5 objects. | T | MS4 |
| FR-M7-15 | **Calendars and time.** Clocks in hours MUST use elapsed time in UTC and be displayed in Asia/Taipei (or the site zone). Clocks in working days MUST use the site holiday calendar (`site/calendars/<country>_<year>.yaml`). An admin MAY add ad-hoc closure days (for example typhoon days), with an audit record. Every clock MUST state whether it is calendar or working time, and the source of its deadline (protocol section, SOP id, CTA clause). | T | MS4 |
| FR-M7-16 | **Escalation and waiver.** Each task MUST have an escalation chain: owner, then backup (from the delegation log), then PI, then research office, at playbook thresholds. Waiving an item MUST require a reason and a role allowed by the playbook. Safety clocks MUST NOT be waivable. They can only be reassigned or closed by an attributable reply. | T | MS4 |
| FR-M7-17 | **SoA ingestion.** The visit schedule (visits, windows, procedures, kits, samples, payments) MUST be built from USDM v4.0 or HL7 Vulcan Schedule of Activities STU1 `PlanDefinition`/`ActivityDefinition` when the sponsor provides them. Otherwise it is built from the M11 SoA table, or extracted by `extract_soa` from PDF/DOCX. An extracted schedule MUST be confirmed at G1 before any reminder is computed from it. | T | MS4 |
| FR-M7-18 | **Screening-visit eligibility checklist.** For a scheduled screening visit, the box MUST render a per-criterion worksheet for the bound ruleset version. Each line holds: the criterion text (protocol language and site language); the box's latest evaluation (`met`, `not_met`, `potential:data_gap`, `potential:uncertain`, `unknown`) with verified quotes, values and dates; the recency of that evidence against the IR v3 `screening` anchor (the scheduled visit date); and a "to verify at screening" list (labs or procedures the protocol requires within N days of screening or randomisation). The evaluation MUST be refreshed (S1–S4, on-prem) the evening before the visit. The investigator column MUST be empty. The box MUST NOT pre-tick it or compute an overall verdict. The header MUST read "Pre-filled from records for investigator verification — not an eligibility determination" (§15). The output is PDF and DOCX, with an optional FHIR `QuestionnaireResponse` (`status = in-progress`). The playbook sets how it is signed: `wet` or `g6`. | T | MS5 |
| FR-M7-19 | **IP accountability prompts.** From the SoA and the pharmacy dispensing log, the box MUST remind the pharmacist and CRC to reconcile dispensed, returned and on-hand IP at each dispensing visit and monthly. It MUST flag a dispensing record with no visit encounter that day, a dispensing visit with no dispensing record, and IP lots within the expiry warning. Kit numbers are opaque strings. The box MUST NOT hold kit-to-arm mappings, randomisation lists or IRT data. An L1 data contract (§5) MUST reject any column whose name or content profile matches the arm/treatment blocklist (FR-M7-11). | T | MS5 |
| FR-M7-20 | **Temperature excursions.** An alarm from the hospital's storage-monitoring feed, or a reply `TEMP <study> <unit> <start> <max> <duration>`, MUST open an acknowledgement task for the pharmacist (playbook clock, default 24 h *(est.)*). It MUST also open a sponsor-notification task per the pharmacy manual, and remind staff not to dispense affected lots until the sponsor gives a disposition. These are reminders only. The box blocks nothing in pharmacy systems. | T | MS5 |
| FR-M7-21 | **Lab kits.** The box MUST hold kit inventory per type and lot, entered by reply (`KIT <study> <type> <qty> exp <date>`) or CSV. It MUST project demand for the next 8 weeks from scheduled visits and the SoA. It MUST remind the CRC to reorder when projected stock falls below demand plus a safety stock, and warn before kit expiry (default 30 days). | T | MS5 |
| FR-M7-22 | **Sample logistics.** For each visit with samples, the box MUST produce a task list from the SoA and lab manual: collection, processing time limit, storage temperature class, shipment window and courier days. It MUST remind the CRC before the shipment window closes and log shipments by reply. Lab-manual parameters extracted by `extract_soa` are confirmed at G1. | T | MS5 |
| FR-M7-23 | **Participant reimbursement reminders.** Per-visit amounts MUST come from the IRB-approved ICF (G1-confirmed). When a visit is done, the box opens a "process reimbursement" task. An item older than 30 days (playbook parameter) escalates. The box MUST NOT execute payments. It MUST NOT accept or store bank-account data: a message matching account patterns is redacted at intake and the sender is told why. Monthly totals per study go to research finance as an aggregate. | T | MS5 |
| FR-M7-24 | **Retention and visit adherence.** The box MUST flag missed-visit risk for each enrolled participant from appointment data. Rules: no appointment booked for the next visit 7 days before its window opens; ≥ 2 no-shows in the last 12 months of HIS appointments; or the last two visits at a window edge. A calibrated risk model MAY replace the rules per site, as a learned parameter (§8) under G5. The output is an internal CRC call list. The box never contacts participants (§2). | T | MS5 |
| FR-M7-25 | **RBQM key risk indicators.** The box MUST compute the KRIs in the table below per study, weekly. It MUST show amber and red KRIs in the Monday digest, and feed the site-performance pack (§12). Thresholds are playbook parameters. These are site self-monitoring indicators. They are not the sponsor's quality tolerance limits under E6(R3), and must not be labelled as such. | T | MS4 |
| FR-M7-26 | **ISF/TMF completeness.** The essential-records list MUST be encoded in `site/isf/essential_records.e6r3.yaml`, from ICH E6(R3) Annex 1, Appendix C. Each row has an id, title, phase (before, during, after), applicability condition (for example "if IP", "if local lab"), owner, expiry rule (CV, GCP certificate, lab accreditation, normal ranges, insurance certificate), and an optional TMF Reference Model artefact number. The box MUST report completeness per phase, list missing, expired and soon-expiring records, and remind owners. QA MUST verify the encoding against the guideline text at installation. | T, I | MS4 |
| FR-M7-27 | **DSMB support listings.** For studies where the hospital is the sponsor (IIT), or where a DSMB asks for site data through the PI, the box MUST produce deterministic listings: enrolment and disposition, deviations, withdrawals, the SAE log, and hospital-flagged events (FR-M7-8). Seriousness, causality and expectedness columns are filled only by the investigator. The listings MUST carry no treatment-arm information. Release outside the site is G2. | T | MS5 |
| FR-M7-28 | **IRB e-submission package.** For initial review, amendments, continuing review, SAE and safety reports, and the final report, the box MUST assemble: the pre-filled forms (FR-M7-2); the attachments drawn from the ISF index at their current approved versions; a checksum manifest; and a submission checklist. The package is rendered by a site adapter (`services/lifecycle/irb_adapters/<site>.py`) in the IRB system's import format where one exists, and as a ZIP of DOCX/PDF plus a checklist otherwise. A person uploads it. The box records submission and approval dates from reply lines or imported IRB letters. | T | MS4 |
| FR-M7-29 | **Sponsor-query SLA tracking.** Queries MUST be registered from three sources: EDC query-report exports (CSV), forwarded sponsor mail (summarised by `summarise_external`), and monitor follow-up letters. Each query has an id, source, opening date, due date (CTA working days), owner and status. The box reminds the owner at 50 % and 90 % of the SLA, links an answer draft (FR-M8-4), and reports query age as a KRI. | T | MS5 |
| FR-M7-30 | **Safety clocks by owner (extends FR-M7-7).** (a) A clock starts at the investigator-awareness time on the `SAE` line. If none is given, the reply time is used and labelled as such. (b) Follow-up-report clocks follow the protocol. (c) A SUSAR or safety letter from the sponsor opens an IRB-submission clock per the IRB SOP, and an ISF filing task. (d) Pregnancy-exposure reports open their protocol clock. (e) Every clock shows its owner and the source of its deadline, and it closes only by an attributable reply. (f) Clocks survive restarts and rollbacks (FR-WF-4). Hospital-flagged admissions from HL7 v2 ADT reach the investigator the same day (§5). | T | MS4 |
| FR-M7-31 | **Deviation-candidate rules.** A versioned catalogue (`site/playbooks/deviation_rules.yaml`) MUST include at least: visit outside its window; protocol procedure missing at a visit; study-specific order dated before the consent date; participant on a superseded ICF after the re-consent visit; dispensing by a person not delegated for IP; a protocol-required lab outside its window before dosing. Every candidate goes to the CRC for confirmation. Only confirmed ones enter the log (FR-M7-6). | T | MS5 |
| FR-M7-32 | **Start-up tracker.** Milestone dates MUST be recorded per study: feasibility received, selected, IRB submitted, IRB approved, CTA draft received, budget agreed, CTA signed, SIV, activation, first participant in. Durations MUST feed site history (FR-M6-5) and the site-performance pack. ASCO/AACI reported an average of 7 months from first contact to first patient enrolled (CRI 2020 abstract), which is the reference comparison. | T | MS4 |
| FR-M7-33 | **Patient-facing text.** The box MAY prepare staff-facing drafts of IRB-approved patient messages (visit reminders, retention calls) only by filling approved templates. It MUST NOT send anything to participants, and MUST NOT generate free text for participants. | T, I | MS4 |

**KRI catalogue (FR-M7-25).** All thresholds are default values *(est.)*, set per site.

| KRI | Definition | Amber | Red |
| --- | --- | --- | --- |
| Visit-window adherence | visits in window ÷ visits due (90 days) | < 0.95 | < 0.90 |
| Deviation rate | confirmed deviations per 10 participant-visits | > 0.5 | > 1.0 |
| Important deviations | count in the last 90 days | ≥ 1 | ≥ 3 |
| Query rate | queries per participant-visit (EDC export) | > 2 | > 4 |
| Query age | median working days open | > 5 | > 10 |
| SAE reporting lateness | site sponsor-clocks closed after deadline, 90 days | > 0 | > 1 |
| Consent-version lag | participants on a superseded ICF after the re-consent visit | ≥ 1 | ≥ 3 |
| Critical data missing | critical fields with no source ÷ required (M8 gap report) | > 0.02 | > 0.05 |
| Screen-fail rate | observed minus the feasibility assumption | > +10 pts | > +20 pts |
| Enrolment against forecast | actual ÷ p50 plan | < 0.8 for 2 weeks | < 0.6 |
| ISF completeness | required records present and current | < 0.98 | < 0.95 |
| Gate backlog | open G3/G4/G6 items older than 48 h | ≥ 1 | ≥ 5 |

**Acceptance metrics.**

| Metric | Target | Measured by |
| --- | --- | --- |
| Reminders sent before their scheduled time plus 15 min | ≥ 99.5 % | outbox and timer logs |
| Safety clocks lost or duplicated under kill/restart and rollback | 0 | FR-WF-1 and FR-WF-4 tests |
| KRI values against hand-computed fixtures | 100 % exact | `kri` unit suite |
| Checklist lines with evidence or an explicit "to verify" entry | 100 % | checklist renderer tests |
| Extracted SoA parameters changed at G1 | reported, trend down *(descriptive)* | G1 diffs |
| CRC time on reminders, logistics and ISF tracking | −30 % against the pre-go-live time-and-motion baseline *(target, est.)* | §16 time-and-motion |

**Disposition of v3 IDs.** FR-M7-1, 2, 4–11 are kept. FR-M7-3 (coverage analysis) moved to M10 as FR-M10-4.
FR-M7-12 (line of therapy) is now part of IR v3 (§6, §10.1). **Code.** `services/lifecycle/` (`engine.py`,
`playbook.py`, `calendar.py`, `clocks.py`, `kri.py`, `isf.py`, `ip.py`, `logistics.py`, `reimbursement.py`,
`retention.py`, `checklist.py`, `irb_package.py`, `irb_adapters/`, `sponsor_queries.py`, `dsmb.py`, `deviations.py`).

---

### 10.8 M8 — Data abstraction, eSource/eCRF pre-fill, SDV packets and EDC query drafts

**Purpose.** M8 cuts transcription and source-data-verification work. It produces pre-filled eCRF files in which every
value carries lineage, one-page source packets that a monitor can verify against, discrepancy lists between the EDC
and the source, and drafted answers to sponsor queries. People enter data in the EDC. The box never does (FR-M8-6).

**Evidence and competition.**
- *Structured EHR→EDC transfer works.* A multi-study, multi-site assessment found a manual transcription error rate of
  8.23 % (95 % CI 7.79–8.70) against 0 % (0.00–0.03) for direct transfer (AMIA Joint Summits 2026, PMID 42317828).
- *REDCap CDIS, multisite.* Set-up took 15–26 h per site. 764 persistent errors in 4,404 fields were avoidable, and
  51 min were saved per participant (J Biomed Inform 2026, doi:10.1016/j.jbi.2026.105060).
- *Phase I oncology.* An embedded EHR→EDC tool handled 11,342 data points across 955 CRFs at 37 s per CRF, and 89 % of
  the data points were labs (ESMO Real World Data and Digital Oncology 2025).
- *Narrative fields have no prospective eCRF-level validation.* Retrospective LLM abstraction reached 99 % concordance
  for recurrence, 96 % for HER2 and 91 % for stage on 100 breast-oncology patients (Stanford, preprint). A ChatGLM eCRF
  study reached 77.1 % accuracy on free text, against 99.6 % for manual entry (Eur Heart J Digital Health). Flatiron's
  VALID framework sets out how AI-extracted data should be validated (JCO CCI 2026).
- *Competitors.* REDCap CDIS and Veeva's eSource inside SiteVault (a FHIR-based EHR→EDC path presented in April 2026,
  trade press; SiteVault is free to sites for up to 20 studies, trade press) occupy structured transfer where a FHIR
  endpoint exists.

**Consequences for the design.**
- Structured domains carry the proven error reduction, so they use rule extractors only, with no model.
- Narrative fields have no prospective evidence, so model proposals are always marked "needs review" and carry
  verified quotes.
- TrialBox differs from FHIR-only tools in five ways: HIS views and HL7 v2 sources that have no FHIR server,
  code-mixed narrative fields, SDV packets, EDC reconciliation, and query drafts.
- TrialBox does not compete on transfer into the EDC.

**Field classes.**

| Class | Examples | Extractor | Review rule |
| --- | --- | --- | --- |
| S structured | labs, vitals, demographics, orders, dispensed drugs | rule (SQL over L5), UCUM conversion | pre-filled; CRC confirms per form |
| D derived | BMI, eGFR (CKD-EPI 2021), QTcF, age at visit | versioned calculator library (IR v3, §6) | pre-filled; formula shown |
| T temporal or multivariable | "concomitant medication started since last visit", "worst grade in the cycle" | rule where expressible; else `abstract_field` | "needs review" unless rule-derived (FR-M8-2) |
| N narrative | ECOG from notes, AE verbatim term, medical history, tumour response text | `abstract_field` with ≤ 3 verified spans | always "needs review" |

**Inputs and outputs.**

| Dir. | Item | Source or target | Class |
| --- | --- | --- | --- |
| In | Form definitions: CDISC ODM v2.0 study metadata, CDASHIG v2.3 domain specs, REDCap data dictionary CSV, EDC bulk-load XLSX/CSV templates | sponsor, CRC | D1 |
| In | Participant × visit list | M6, M7 | D3 |
| In | L5 snapshot (structured data, canonical text, sentence index) | §5 | D3 |
| In | EDC data export (ODM `ClinicalData` or CSV), EDC query report, forwarded queries | CRC | D3 |
| Out | Pre-fill files per participant and visit (ODM v2.0 `ClinicalData`, the template format, FHIR `Bundle` *(optional)*) | delegated CRC only | D3 |
| Out | Source packets, gap report, discrepancy list, query drafts | CRC, monitor (on site) | D3 |
| Out | Retrospective de-identified datasets with data dictionary and QC report | approved researcher | D2 |

**LLM roles.**

| Role | Use in M8 | Class | Route |
| --- | --- | --- | --- |
| `concept_select` | Proposes field → canonical-concept mapping from terminology-service hits (FR-M8-1) | D1 (form metadata) | per routing policy |
| `abstract_field` | T/N field values with multi-span evidence | D3 | on-prem only |
| `draft_query_answer` | Answer drafts for EDC queries | D3 | on-prem only |
| `summarise_external` | Extracts query text from forwarded sponsor mail | D3 | on-prem only |

**Requirements.**

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M8-1 | Given a target form (CDASH/ODM v2 form definition, or an EDC bulk-upload XLSX template), the box MUST map fields to canonical data (confirmed once per form by the CRC) and produce a pre-filled file per participant and visit. | T | MS5 |
| FR-M8-2 | Every pre-filled value MUST carry lineage: source record, timestamp, transformation, extractor (rule or model) and confidence. Temporal, multivariable or free-text-derived fields are marked "needs review" unless rule-derived. | T | MS5 |
| FR-M8-3 | **SDV source packets.** For each pre-filled value, a one-page source excerpt (lab line, note sentence with the quote highlighted, document id, date). The CRC certifies a packet with a Level B signature, and monitors verify against it. | T | MS5 |
| FR-M8-4 | **EDC query drafts.** The CRC forwards or pastes a sponsor query (`QUERY GZQO P0156 <text>`). The box drafts an answer from source data with citations, for the CRC to edit and enter in the EDC. | T | MS5 |
| FR-M8-5 | A critical-field gap report MUST list required fields with no source data per participant and visit. | T | MS5 |
| FR-M8-6 | The box MUST NOT submit to an EDC; humans upload. Files go only to delegated internal recipients. | T | MS5 |
| FR-M8-8 | **Form ingestion.** The box MUST load ODM v2.0 study metadata, CDASHIG v2.3-based specifications, REDCap data dictionaries and EDC template files. It MUST pin the CDISC Controlled Terminology version per study, and keep the form's edit checks (range, required, unit, code list) for validating pre-filled values. A field-map confirmation is a G1 object of kind `field_map`. | T | MS5 |
| FR-M8-9 | **Extractor assignment.** S and D fields MUST be filled by rules only. T and N fields MAY use `abstract_field`, under these conditions: at most 3 evidence spans; every quote verified byte-for-byte against canonical text (§6); the assertion rules agree (ML-6); the value passes the form's edit checks. If any check fails, the field is left empty with reason `unverifiable`. | T | MS5 |
| FR-M8-10 | **Visit-relative selection.** Each mapped field MUST declare a window relative to the visit date and a selection rule (`nearest`, `worst`, `first`, `last`, `all`). A tie or conflict between sources MUST yield "needs review" with all candidates listed. | T | MS5 |
| FR-M8-11 | **Units, codes, dates.** Values MUST be converted to the form's unit through UCUM. Coded values are mapped to the form's code list. Partial dates follow ODM v2.0 rules. ROC and Japanese-era dates are normalised (ML-3). A failed conversion leaves the field empty with a reason. | T | MS5 |
| FR-M8-12 | **EDC reconciliation (self-SDV).** From a read-only EDC export, the box MUST compare entered values with source-derived values and list discrepancies with packet references before each monitoring visit. The CRC records an outcome per discrepancy (`edc_corrected`, `source_wins`, `accepted_difference` with reason). The count of discrepancies found is reported per 1,000 fields as "errors prevented". | T | MS5 |
| FR-M8-13 | **Source changed after certification.** If a late or corrected source record (§5) changes a value in a certified packet, the packet MUST be marked "source changed after certification" and a task opened for the CRC. A certified packet is never changed silently. A new packet version needs a new G6 certification. | T | MS5 |
| FR-M8-14 | **Retrospective datasets (replaces FR-M8-7).** Bulk abstraction for an approved cohort MUST require an IRB reference. It produces a D2 dataset that meets the de-identification standard and the re-identification risk check of §7, together with a data dictionary and a QC report. The QC report includes per-field agreement against a double-abstracted sample (≥ 50 records or 10 %, whichever is larger). Release follows the Five Safes checklist (§7). | T | MS5 |
| FR-M8-15 | **Query drafts, constraints (extends FR-M8-4).** A draft MUST cite packet or evidence ids and pass `numbers_match` and citation verification (§8). If no source is found, it MUST say so, using approved wording ("not available in source documents as of <snapshot date>"). It MUST NOT propose a value without a source. Each draft is linked to its SLA item (FR-M7-29). | T | MS5 |
| FR-M8-16 | **Per-form gate.** Before a form's pre-fill reaches a CRC, the `abstract_field` suite MUST run on a gold sample for that form: ≥ 30 participant-visits double-abstracted by two CRCs at the first site, then 10 per new form. It MUST meet these floors: S/D agreement ≥ 0.99, T/N agreement ≥ 0.90, quote verification 100 %. A failing field is switched to "manual only". | T | MS5 |

**Acceptance metrics.**

| Metric | Target | Reference point |
| --- | --- | --- |
| S/D field accuracy against double manual abstraction | ≥ 0.99 | direct transfer 0 % against 8.23 % manual error |
| N-field proposals accepted unchanged by the CRC | ≥ 0.80 *(target)* | no prospective benchmark exists |
| Machine pre-fill time per CRF | median ≤ 60 s *(est.)* | 37 s per CRF (ESMO RWD 2025) |
| CRC minutes saved per participant (time-and-motion) | ≥ 30 *(target)* | 51 min (REDCap CDIS) |
| Set-up per new form after the first study | ≤ 8 h *(target)* | 15–26 h per site (CDIS) |
| SDV minutes per visit reported by the CRA | −30 % *(target)* | none published |
| Discrepancies found per 1,000 fields (EDC reconciliation) | reported *(descriptive)* | 764 / 4,404 fields (CDIS) |

**Disposition of v3 IDs.** FR-M8-1…6 are kept. FR-M8-7 is replaced by FR-M8-14. **Code.** `services/abstraction/`
(`formdef.py`, `fieldmap.py`, `extract.py`, `select.py`, `lineage.py`, `sdv_packet.py`, `edc_reconcile.py`,
`query_draft.py`, `gaps.py`, `retro_dataset.py`).

---

### 10.9 M9 — Close-out, reporting and learning

**Purpose.** M9 closes a study cleanly and keeps what the site learned:
- the close-out checklist;
- financial reconciliation;
- the final IRB report draft;
- registry deadlines;
- the archive bundle;
- the retrospective that feeds site history and the criterion library.

It also drafts investigator-initiated-trial (IIT) protocols from a concept sheet, using the ICH M11 template. This is
where lessons from closed studies become the next protocol.

**Inputs and outputs.**

| Dir. | Item | Source or target | Class |
| --- | --- | --- | --- |
| In | `STUDY <id> closed` and primary-completion date | PI, CRC | D1 |
| In | Study Card, pipeline, forecast ledger, calendar, deviation log, recall certificates, audit trail | M6, M7, SAFE, §6 | D1/D3 |
| In | Budget table and CTA payment schedule; payments received (finance CSV); reimbursements | M10, finance, M7 | D1 |
| In | IIT concept sheet (DOCX or e-mail) | PI | D1 |
| Out | Archive bundle (PDF/A-3 + JSON, checksums) | hospital archive / WORM | D3 |
| Out | Retrospective, site history, library updates | research office; M3; §10.1 | D1 |
| Out | Final IRB report draft; registry reminders and results-table drafts | CRC, PI | D1 |
| Out | Financial reconciliation report | research finance | D1 (aggregate) / D3 (per-visit, internal) |
| Out | IIT protocol draft (DOCX, M11 structure), USDM v4.0 JSON, criteria as FHIR `EvidenceVariable` | PI; IRB after G2 | D1 |

**LLM roles.**

| Role | Use in M9 | Class | Route |
| --- | --- | --- | --- |
| `draft_document` | IRB final-report narrative; IIT protocol sections | D1 | per routing policy (topology C allows cloud for D1 under policy) |
| `draft_narrative` | Retrospective commentary through placeholders | D1 (aggregates) | per routing policy |
| `extract_criteria`, `concept_select` | IIT eligibility through match-then-draft from the criterion library | D1 | per routing policy |

**Requirements.**

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M9-1 | Registry deadlines for hospital-sponsored studies (IIT): registration ids, results-posting due dates (42 CFR 11 where the study is an applicable clinical trial; otherwise WHO/ICMJE practice of 12 months after primary completion), and reminders. | T | MS5 |
| FR-M9-2 | Retrospective at close: feasibility estimate versus actual, screen-fail reasons, criteria with the most rejections, recall certificates over time, forecast score. Stored as site history. | T | MS5 |
| FR-M9-3 | Archive export: Study Card, rulesets, packets, approvals and signatures with manifestations, decisions, recall certificates and the audit trail, as PDF/A plus JSON with checksums. Retention defaults are named (§7). | T | MS5 |
| FR-M9-4 | Final IRB report draft (DOCX) from the Study Card and pipeline. | T | MS5 |
| FR-M9-5 | **Financial reconciliation.** Monthly during conduct and finally at close, the box MUST compute, per budget line and per participant-visit: expected (completed visits and procedures from M7 × the budget table, screen-fail fees, start-up and pass-through items), invoiced, and received. It MUST list unbilled items, overdue receivables, unpaid participant reimbursements, and NHI-billing conflicts from M10 (FR-M10-7). Computation is deterministic. The per-visit detail is D3 and internal; the summary is D1. | T | MS5 |
| FR-M9-6 | **Close-out playbook.** The `close` playbook MUST cover at least: final query resolution; IP reconciliation and return or destruction confirmation; ISF completeness for the "after" phase (FR-M7-26); the final IRB report (due within the IRB's period, a site parameter; CGMH approval letters state 3 months, secondary source); archive; start of the retention clock; revocation of monitor and study accounts; and the close-out visit. | T | MS5 |
| FR-M9-7 | **Registry obligations (extends FR-M9-1).** For IITs, the box MUST check that registration happened before the first enrolment (ICMJE). Results posting is due within 1 year of the primary completion date (42 CFR Part 11 for applicable clinical trials; EU CTR Art. 37 where EU sites take part, which is 6 months for paediatric trials). Taiwan posting obligations are *(uncertain)* and are a site parameter. Reminders go out at 90, 30 and 7 days. A participant-flow table is drafted from the pipeline. A person posts the results. | T | MS5 |
| FR-M9-8 | **IIT protocol drafting (ICH M11).** From a concept sheet, the box MUST draft a DOCX that follows the ICH M11 template structure (Step 4, 19 Nov 2025). Rules: (a) eligibility is drafted match-then-draft from the criterion library, and each draft criterion is run through M3 against the site population, printing a computable-count band; (b) an SoA skeleton is drafted from the concept sheet's visits; (c) statistical sections are placeholders. The model MUST NOT compute a sample size. A deterministic calculator for two-arm proportion and mean comparisons MAY fill one, with formula and inputs printed, for statistician sign-off; (d) the model MUST NOT generate literature references, only `[REF NEEDED: <claim>]` placeholders; (e) every generated paragraph is marked "draft — AI-assisted, requires investigator authorship". The PI confirms each section (G1, object kind `iit_protocol_draft`). Release to the IRB is G2. | T | MS6 |
| FR-M9-9 | **Machine-readable IIT outputs.** The IIT draft MUST also be exported as USDM v4.0 JSON (study design, SoA, eligibility) and its criteria as FHIR R4 `EvidenceVariable` compiled from IR v3, so the protocol enters M1 without re-extraction. | T | MS6 |
| FR-M9-10 | **Learning at close.** Screen-fail reasons, PI rejection reasons and recall-ledger outcomes MUST update the criterion library's precision and computability history (§10.1) and the site priors of the recruitability model (§10.3). The SAFE ever-excluded enrollee check runs as part of CloseWorkflow. | T | MS4 |
| FR-M9-11 | **Retention and hold.** Each archived record class MUST get its retention period from the site retention table (§15), starting at close. Legal hold MUST suspend deletion. Archive readability (open, render, checksum) MUST be re-verified after any storage migration. | T | MS5 |

**Acceptance metrics.**

| Metric | Target |
| --- | --- |
| Archive bundles that pass `trialbox archive verify` (checksums, PDF/A validation, audit-chain continuity) | 100 % |
| Registry and IRB final-report deadlines missed for studies in the box | 0 |
| Reconciliation lines matching hand-checked fixtures | 100 % |
| IIT drafts with any model-generated reference or sample size | 0 (test) |
| IIT draft sections accepted by the PI with minor edits | ≥ 0.6 *(target, est.)* |

**Disposition of v3 IDs.** FR-M9-1…4 are kept. **Code.** `services/closeout/` (`retrospective.py`, `archive.py`,
`finance.py`, `registry_deadlines.py`, `iit_protocol.py`, `samplesize.py`, `usdm_export.py`).

---

### 10.10 M10 — NHI navigation, NHI-aware recruitment and coverage analysis

**Purpose.** M10 carries over v1 NAV: TWPAS prior-authorisation bundles, their validation and the NHI CQL pre-check. It
adds two things. First, NHI reimbursement facts become recruitment signals. Second, it computes the coverage analysis
(standard of care versus research-only) **at feasibility**, so that the budget is right before negotiation. The NHI Act
excludes trial-related items from coverage. The article number is *(uncertain)*; the research note points to Art. 51
and it must be verified. Research items therefore must never reach an NHI claim.

**Inputs and outputs.**

| Dir. | Item | Source or target | Class |
| --- | --- | --- | --- |
| In | NHI medical-service fee schedule (全民健康保險醫療服務給付項目及支付標準), drug reimbursement rules (藥品給付規定), editions | NHIA publications, loaded through the terminology service (§5) | D0 |
| In | Hospital fee schedule and overhead rates | finance | D1 |
| In | SoA (M7), protocol indication | M1, M7 | D1 |
| In | The hospital's own TWPAS submission history; claims or billing feed *(optional)* | L0 contracts | D3 |
| Out | TWPAS bundles, pre-check results (v1) | NAV users | D3 |
| Out | Coverage analysis and draft CTA budget (XLSX) | research office; sponsor after G2 | D1 |
| Out | NHI phenotype atoms for IR `claim` criteria; aggregate NHI context for the feasibility pack | M1, M3, §12 | D3 → aggregate D1 |
| Out | Billing-guard alerts | research office | D3 |

**LLM roles.**

| Role | Use in M10 | Class | Route |
| --- | --- | --- | --- |
| `concept_select` | Chooses NHI fee codes for SoA procedures among terminology-service hits; never from model memory | D1 | per routing policy |
| `extract_criteria` | Turns reimbursement-rule clauses into IR `claim` atoms (for example "biomarker test required", "renewal every 6 months") | D0 | any approved route |
| v1 NAV roles | unchanged from v1 | as v1 | on-prem |

**Requirements.**

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M10-1 | v1 NAV, TWPAS bundle generation, validation and pre-check MUST keep working unchanged on IR v3 rulesets. | T | MS1 |
| FR-M10-2 | TWPAS packages are updated to the IG version NHIA requires at go-live, with the official pre-check when published. | T | MS4 |
| FR-M10-3 | **NHI-aware recruitment.** IR `claim` atoms MUST support prior-authorisation outcomes and renewal windows (for example a biologic renewal at risk), as phenotype signals for trials of alternatives. These are aggregate-reported in feasibility. | T | MS4 |
| FR-M10-4 | **Coverage analysis at feasibility (replaces FR-M7-3).** During FeasibilityWorkflow, each SoA procedure MUST be mapped to an NHI fee code and classified as `soc` (NHI-payable for the indication under the payment rules, at a frequency no higher than routine care) or `research_only` (sponsor-paid). A case the rules cannot settle is `undetermined` and goes to the research office. Each classification MUST cite the rule clause and edition it relies on. The research office confirms the mapping at G1 (object kind `coverage_analysis`). | T | MS4 |
| FR-M10-5 | **Editions.** Fee-schedule and drug-reimbursement-rule editions MUST be versioned, with effective dates. Every coverage analysis and every `claim` atom records the edition it used. A new edition triggers a diff of open coverage analyses for the research office. | T | MS4 |
| FR-M10-6 | **Budget draft.** The box MUST produce a draft CTA budget table: research-only items × hospital unit cost × overhead (site parameter), per visit and in total, plus screen-fail and start-up lines, mapped to the sponsor's budget template where one is supplied. Release to the sponsor is G2. | T | MS4 |
| FR-M10-7 | **Billing guard.** Where a claims or billing feed is connected, the box MUST compare orders for enrolled participants against the `research_only` items of the study and alert the research office before the claim-submission cut-off, citing the order and the budget line. The box MUST NOT edit or hold claims. | T | MS5 |
| FR-M10-8 | **Opt-out.** Signals derived from NHI data (TWPAS history, MediCloud queries, FR-M0-12) MUST honour the patient's `nhi_secondary_use` consent scope (§7), which reflects the opt-out that followed Constitutional Court Judgment 111-Hsien-Pan-13. | T | MS4 |
| FR-M10-9 | **IG pinning.** The TWPAS IG version (v1.2.3 published; CI builds 1.2.5–1.2.6 at the time of writing) and the NHI CQL pre-check IG version MUST be pinned per release. Moving to a new version is a G5 change with the fixture bundles re-validated. | T, I | MS4 |

**Acceptance metrics.**

| Metric | Target |
| --- | --- |
| TWPAS fixture bundles passing the official validator and pre-check | 100 % |
| Coverage-analysis lines accepted by the research office without change | ≥ 0.80 *(target, est.)* |
| Planted research-only orders missed by the billing guard | 0 |
| Budget drafts accepted by sponsors without structural rework | reported per study *(descriptive)* |

**Disposition of v3 IDs.** FR-M10-1…3 are kept. **Code.** `services/nhi/` (`nav.py` and `twpas.py`, moved from
`services/orchestrator/scenarios/`, plus `coverage.py`, `fee_schedule.py`, `budget.py`, `billing_guard.py`,
`claim_signals.py`).

---

### 10.11 M11 — Networked research

**Purpose.** M11 connects the box to research networks without moving patient-level data. It has five parts:
- an OMOP CDM 5.4 endpoint for local OHDSI tools;
- federated feasibility answers protected by a privacy accountant and pairwise-cancelling masks;
- exchange of alliance language packs;
- a responder for national and alliance request networks (TACTC, TNet);
- standing trial-ready cohorts.

The v1 quarterly COHORT tables keep working.

**Inputs and outputs.**

| Dir. | Item | Source or target | Class |
| --- | --- | --- | --- |
| In | Alliance or network request: ruleset JSON, CIRCE JSON, FHIR `Group` + `EvidenceVariable`, or questionnaire | alliance root, network mailbox | D1 |
| In | L5 OMOP schema and snapshot | §5 | D3 |
| In | Peer language packs (signed) | alliance members | D1 |
| Out | Masked noisy cell vectors (member to root); rounded totals (root to requester) | alliance root; requester | D1 |
| Out | OMOP read-only endpoint; OHDSI study-package outputs (aggregate) | local OHDSI tools; network after G2 | D3 local / D1 out |
| Out | Signed language packs; trial-ready cohort counts | alliance | D1 |

**LLM roles.** Compilation of a request uses the M1 roles (`extract_criteria`, `concept_select`, D1) when the request
arrives as text or a questionnaire. Federated computation, noise, masks and rounding use no model.

**Federated answer protocol (normative).** There are *n* ≥ 3 members, each with a pairwise seed s_ij. The seeds are
agreed at onboarding by X25519 key agreement between the members' alliance certificates, with HKDF-SHA-256 applied, and
are rotated yearly. For a round r and a cell k:
1. Member i computes its true count c_ik on its current snapshot.
2. It draws two-sided geometric noise η_ik with scale exp(−ε_cell/Δ), with Δ = 1 for counts. The PRNG is seeded by
   (member secret, query hash, quarter). The same query in the same quarter therefore returns the *same* noisy value
   and costs no new ε.
3. It sends y_ik = c_ik + η_ik + Σ_{j>i} PRF(s_ij, r, k) − Σ_{j<i} PRF(s_ji, r, k), mod 2^64.
4. The root sums the y_ik mod 2^64, so the masks cancel. It reads the result as a signed integer, which gives
   Σc + Ση. It applies small-cell suppression and controlled rounding (§7) to the total only.
5. The root never sees a member's value unmasked. If a member drops out, the round is aborted and issued again with a
   new round id to the members that responded. Their cached noisy values are reused, so the new round costs no
   additional ε.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M11-1 | v1 quarterly cohort tables and alliance merge MUST keep working. | T | MS1 |
| FR-M11-3 | **Federated feasibility with a privacy accountant.** A member box answers an alliance query (same ruleset, aggregate) by adding calibrated geometric noise to each cell on top of controlled rounding. Members also add **pairwise-cancelling masks**: each pair of members shares a seed at onboarding, so the masks cancel in the sum at the alliance root. The root sees only the noisy total; each member's noise budget ε is accounted per requester per quarter. | T | MS5 |
| FR-M11-4 | Trial-ready cohorts: standing cohort definitions with consented-to-contact patients, refreshed each snapshot, reported in aggregate. | T | MS5 |
| FR-M11-5 | **OMOP endpoint (replaces FR-M11-2).** The L5 OMOP CDM 5.4 schema (§5) MUST be exposed read-only on the hospital network to OHDSI tools (ATLAS/WebAPI, Achilles, DQD, CohortGenerator). Access is limited to named users with an approved project (IRB reference). Row-level results stay inside. Aggregate outputs leave only through the accountant, rounding and G2. Patient-level extracts go only through FR-M8-14. | T | MS5 |
| FR-M11-6 | **Protocol conformance.** Members MUST implement the federated answer protocol above. The protocol MUST refuse to run with fewer than 3 responding members. Masks MUST be derived per (round, cell) and never reused. The accountant MUST refuse a query whose ε charge would exceed the requester's quarterly budget (a site parameter; default ε = 1.0 per requester per quarter *(est.)*). | T | MS5 |
| FR-M11-7 | **Equivalence across members.** A request carried as CIRCE JSON or FHIR `EvidenceVariable` MUST be compiled to IR v3 and pass the CQL ≡ SQL equivalence gate locally. A criterion seen for the first time needs a local G1 confirmation. A member whose compile fails answers `not_computable` for the affected cells. It does not substitute an approximation. | T | MS5 |
| FR-M11-8 | **Standing release policy.** A research office MAY approve a standing G2 policy: a named requester, query classes, a per-quarter ε ceiling, and an expiry of ≤ 90 days. Answers within the policy are released without a per-answer G2 and are listed in the monthly report. Anything outside the policy needs a normal G2. | T | MS5 |
| FR-M11-9 | **Per-member breakdown.** Per-site counts are released only as a separate, unmasked, G2-approved answer from that member, charged to its own accountant. The root MUST NOT ask for them inside a masked round. | T | MS5 |
| FR-M11-10 | **Alliance language packs (transport for ML-12).** An export MUST be signed with the site's Ed25519 key. It MUST contain only approved lexicon rows with rounded support at or above the pack threshold, and de-identified assertion exemplars that have passed the PHI guard (§7). Each row carries its origin site and pack version. An import goes through G0. | T | MS5 |
| FR-M11-11 | **Network responder.** Adapters (`services/network/responders/tactc.py`, `tnet.py`) MUST turn a network request into a FEAS request, and package the G2-released answer in the network's format. The networks' request and answer formats are *(uncertain)* until obtained from them. Until then, the fallback is `QFILL` on the network's questionnaire. | T | MS5 |
| FR-M11-12 | **Root transparency.** A box acting as alliance root MUST publish to all members, per round: the query hash, the responding members, the ε charged per member, and the released total. It stores no member value. | T | MS5 |

**Acceptance metrics.**

| Metric | Target |
| --- | --- |
| Mask cancellation over 10^5 random rounds (property test) | exact |
| ε budget exceeded in accountant property tests and the differencing-attack suite | never |
| ATLAS cohort counts compared with box SQL counts for 20 definitions on Synthea | identical |
| OHDSI DQD on the L5 OMOP schema | no failed checks in blocking categories (§5) |
| Alliance request to released answer | ≤ 2 working days; ≤ 1 day under a standing policy *(target)* |

**Disposition of v3 IDs.** FR-M11-1, 3 and 4 are kept. FR-M11-2 is replaced by FR-M11-5. **Code.** `services/network/`
(`omop_endpoint.py`, `federated.py`, `masks.py`, `root.py`, `language_packs.py`, `responders/`, `trial_ready.py`). The
accountant lives in `libs/tb_common/privacy/accountant.py` (§7).

---

### 10.12 Agent behaviours (FR-AG)

**Principle.** The agent is proactive, but within fixed bounds:
- The orchestrator decides **when** something happens (durable timers and events).
- Deterministic code decides **what is due** and **how it ranks**.
- LLM roles only classify intent and **draft** text.
- Hermes **converses and delivers**.

Nobody but a named human decides a gate. This split puts the R3-26 conflicts out of reach: Hermes' own schedules,
approvals and memory never touch regulated work.

**Responsibility split.**

| Concern | Orchestrator workflows | Hermes front door (§9) | Native channel engine |
| --- | --- | --- | --- |
| Schedules, timers, clocks | owns (`timers`, FR-WF-4) | none (cron and unattended modes denied) | none |
| What is due; next-best-action ranking | deterministic code | displays | displays |
| Content of regulated messages | pre-rendered, DLP-checked, in outbox rows | delivers verbatim | delivers verbatim |
| Conversation and clarification | parses confirmed requests | multi-turn; proposes | one numbered round, then proposes |
| Approvals | intake parses replies; signing page | relays the reply verbatim; never approves | relays |
| Data access | T0–T3 tools under policy | front-door MCP tools only (T0/T1, no PHI) | none |
| Model calls | through the gateway, per role | through the gateway, on-prem alias | `classify_intent` through the gateway |

**Proactive behaviours by lifecycle stage.** Stages follow §3.

| Stage | Behaviour | Trigger (workflow) | LLM role, class | Channel | Gate |
| --- | --- | --- | --- | --- | --- |
| 0 Connect | Publish-gate failure and DQ scorecard to the steward; weekly lexicon proposals | IngestPublish, Onboard | none | email | G0 for overrides and lexicon |
| 1 Ask | Understanding email with numbered questions and defaults | Compile, FEAS | `extract_criteria`, `concept_select` D1 | email, Teams | G1 |
| 1 Ask | Protocol answers on request | `ASK` via Hermes | `answer_protocol` D1 | Hermes | none |
| 2 Answer | Feasibility pack, filled questionnaire, coverage budget, draft cover e-mail | FEAS | `map_questionnaire`, `draft_narrative` D1 | email | G2 |
| 3 Find | Clinic-day packet; "N candidates waiting" nudge without PHI | PreScreen | `judge`, `second_opinion` D3 on-prem | email; Teams/LINE count only | G3 |
| 3 Find | Five-minute review questions | ActiveLearn | none new | email | none |
| 4 Track | Monday digest: pipeline, forecast, early warning, red/amber KRIs, top-3 actions | Track | `draft_narrative` D1 *(optional)* | email; Teams summary | G2 for sponsor copies |
| 5 Run | Reminders and clocks; screening checklist; monitor pack; query drafts; deviation candidates | Lifecycle, Abstract | `draft_query_answer`, `abstract_field` D3 on-prem; `draft_document` D1 | email (internal); Teams/LINE nudge without PHI | G6 for regulated records |
| 6 Close | Close checklist; finance reconciliation; IRB final-report draft; registry reminders; retrospective | Close | `draft_document`, `draft_narrative` D1 | email | G2 for external parts |
| All | Admin copilot: health anomalies, queue and budget alerts, bench and evaluation summaries, proposed runbook steps | admin schedule | Hermes admin role D1 | CLI/TUI | G5 for any change |

**Requirements.**

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-AG-1 | Free-text requests MUST become proposals that the sender confirms before any workflow with an external effect starts (§3). | T | MS1 |
| FR-AG-3 | Status answers MUST come from the Study Card only, never from model memory. | T | MS1 |
| FR-AG-4 | The agent MUST refuse and explain when a request exceeds the sender's permissions. It MUST NOT reveal to a non-delegated user whether a named patient exists. | T | MS1 |
| FR-AG-5 | Every agent action MUST be attributable: `actor_type=agent`, `on_behalf_of`, request id, workflow id. | T | MS1 |
| FR-AG-7 | `HELP` returns the commands the sender may use, in their language, with examples. | T | MS1 |
| FR-AG-8 | **Clarification (replaces FR-AG-2).** Under Hermes, the agent MAY hold a multi-turn clarification of up to 5 turns (site parameter) before proposing. Under the native engine it asks at most one numbered round. In both cases the proposal lists every default applied, and defaults never bypass a gate (criteria defaults still pass G1). | T | MS1 |
| FR-AG-9 | **Next best action (replaces FR-AG-6).** Every digest MUST end with the recipient's top three items across their studies. Each item's score is `w_class × 1/(1 + hours_to_deadline/24)`, with default weights: running safety clock 100; gate due 80; visit window closing 60; red KRI 50; expiring training or essential record 40; query SLA 40; kit or IP expiry 30; reimbursement 20. Ties are broken by deadline, then study id. Weights are versioned parameters (`site/agent/nba_weights.yaml`, G5). The ranking is deterministic and covered by fixtures. | T | MS4 |
| FR-AG-10 | **Message budget.** Each recipient gets at most one digest per day (default weekly, `DIGEST daily|weekly|off`), plus gate and clock messages. Other nudges are coalesced to one per channel per 4 h, and held during quiet hours (22:00–07:00 local, a site parameter). Safety-clock reminders at 50 % and 90 % are exempt. A message that requires no action is not sent (§3). | T | MS4 |
| FR-AG-11 | **Message anatomy.** Every proactive message MUST state what is due, why (the source item), the action line, the deadline, and how to mute that message class. Recipients cannot mute safety clocks and gate requests; these can only be reassigned through the delegation log. | T | MS4 |
| FR-AG-12 | **Channel classes.** LINE and Teams nudges MUST carry no PHI: counts and item titles only, with no pid, name or date of birth. Outbound DLP (§14) blocks any violation and falls back to e-mail. Internal e-mail MAY carry pids (D3) within the hospital domain, with encrypted attachments (§14). | T | MS4 |
| FR-AG-13 | **Drafting discipline.** Every LLM draft MUST be labelled as a draft. Its footer carries the role, model build and prompt version (§8). Numbers come from placeholders filled by code. The draft MUST pass `numbers_match` and citation verification before delivery. A failing draft is withheld, and the item is delivered without it, together with the reason. | T | MS1 |
| FR-AG-14 | **Limits.** The agent MUST NOT contact patients. It MUST NOT send to an external recipient except through a G2-released outbox row addressed to the recipient named in the confirmed request. It MUST NOT create, move or cancel a regulated schedule, and it MUST NOT approve. | T, I | MS1 |
| FR-AG-15 | **Aggregate analyst.** Hermes answers research-office questions only through T1 aggregate tools via the accountant (§7). It refuses patient-level questions and states the data cut and snapshot id in every answer. | T | MS4 |
| FR-AG-16 | **Timeline harness.** A simulated 12-month study timeline (`tests/agent/timeline/`) MUST show that every due item produces exactly the expected reminder set at the expected times, with identical results under `channels.engine: hermes` and `native`. | T | MS4 |

**Acceptance metrics.** Proposal accuracy (intent and parameters) ≥ 0.95 on the bilingual set (§16). The NBA top three
contains the item a CRC panel ranks first in ≥ 0.80 of digests *(target)*. Zero PHI reaches LINE or Teams in DLP tests.
Proactive messages per CRC per week are reported, with ≤ 15 as the target *(est.)*. Mute rate per message class is
reported.

**Disposition of v3 IDs.** FR-AG-1, 3, 4, 5 and 7 are kept. FR-AG-2 is replaced by FR-AG-8 and FR-AG-6 by FR-AG-9.
**Code.** `services/agent/` (`nba.py`, `digest.py`, `proposals.py`, `messages.py`); Hermes integration per §9.

---

## 11. Workflows and gates

### 11.0 Durability and exactly-once sends

Workflows run inside the orchestrator as PostgreSQL durable steps with an outbox. This is kept from v3 (§4 ADRs). The v3
tables keep their rules. v4 adds `timers`, `inbox` and step leases.

| Table | Columns (main) | Rule |
| --- | --- | --- |
| `jobs` | v1 columns + `workflow`, `workflow_version`, `priority`, `pass_class`, `data_classes` | One row per request or scheduled run |
| `steps` | `job_id, step, input_hash, output_ref, state, attempts, started, finished, lease_owner, lease_until` | A step whose `(job_id, step, input_hash)` has a `done` row is never executed again; replay reads `output_ref` |
| `gates` | gate fields (§6) | A workflow waiting on a gate polls its row; only intake writes decisions |
| `outbox` | `msg_id, idempotency_key, job_id, kind, to, channel, payload_ref, state(pending/sending/sent/uncertain), attempts, smtp_response` | Sends are rows, not calls |
| `timers` (new) | `timer_id, job_id, calendar_item_id, fire_at_utc, kind, payload_ref, state(armed/fired/cancelled), fired_at` | Every reminder, clock threshold and gate timeout is a timer row; firing is idempotent per `timer_id` |
| `inbox` (new) | `channel, channel_message_id, received_utc, sender, body_sha256, job_id, verdict` | Inbound messages are deduplicated on `(channel, channel_message_id)` before intake runs |

**The outbox makes sends exactly-once.** A step that sends mail, posts a nudge or writes a release only **enqueues** an
outbox row, in the same transaction as its step result. A single sender worker per channel then delivers it:
1. It marks the row `sending`.
2. It delivers with the `Message-ID` (or channel idempotency key) derived from the idempotency key.
3. It marks the row `sent`, or `uncertain` if the answer is lost.

`uncertain` rows are never resent automatically (v1 D-86). The research office is told, and a person decides. Object
writes are content-addressed, so a repeated write is a no-op. Hermes, when enabled, is a delivery channel for outbox rows
(§9). It never writes outbox rows itself.

### 11.1 Gate catalogue

Assurance levels A, A2, A+ and B are defined in §3. Hermes MAY deliver a gate request and relay a reply verbatim to
intake. It never decides a gate (§9).

| Gate | Objects | Who decides | Meaning recorded | Default assurance | Timeout behaviour |
| --- | --- | --- | --- | --- | --- |
| G0 | Site mapping, Atlas configuration, lexicon diff, imported language pack, data-contract change, quarantine release or reconciliation override (§5) | Data steward | "I confirm this mapping, lexicon or data release reflects the source system" | A | reminders at 3 and 7 days; the quarantined batch stays unpublished |
| G1 | Ruleset version; M8 field map; playbook binding and extracted SoA, logistics and payment parameters; coverage analysis; IIT draft sections | CRC; PI for high-risk studies; research office for coverage analysis | "I confirm this is represented as intended" | A | reminders at 1 and 3 days |
| G2 | External release: feasibility, accrual and site-performance packs, questionnaires, budget draft, DSMB listings, federated answers, IIT protocol to the IRB; standing release policies (FR-M11-8) | PI or research office | "I approve release of these results to <recipient>" | A | reminder at 1 day; at the sponsor deadline the packet is withdrawn and the requester told |
| G3 | Candidate decision | PI or delegated sub-investigator | "Confirm / reject for pre-screening follow-up" (never "eligible") | A | none; undecided candidates roll into the next packet |
| G4 | Pipeline transition, consent event, re-consent | CRC or PI | "Participant <state> on <date>" | A | none |
| G5 | Change to production: model, prompt, exemplar bank, lexicon, threshold, rule, routing or egress policy, Hermes release, skills, shipped default playbooks, IG versions, privacy parameters, NBA weights | System owner + QA | "Change validated per evaluation report <id>" | B (A2 until FR-SIG-3 ships) | none; no change without decision |
| G6 | Regulated record: deviation approval and CAPA, SDV source-packet certification, screening checklist where `signing: g6`, certified copies, close-out attestations | Investigator or CRC per playbook | Per record type | B (A+ only with a documented site risk acceptance) | reminders at 1 and 3 days; escalation to the PI at 5 days; no automatic action |

### 11.2 Workflow catalogue

Each workflow is a module `services/orchestrator/workflows/<name>.py`. It declares its steps, the data class of each
step (FR-WF-8) and its gates.

| Workflow | Module | Trigger | Key steps | Gates | LLM roles (class) | R |
| --- | --- | --- | --- | --- | --- | --- |
| IngestPublishWorkflow | §5 | source batch, CDC micro-batch, HL7 v2 group | L0 land → L1 validate and reconcile → L2 standardise → L3 pseudonymise → L4 curate → publish gate → L5 pointer switch → `snapshot_ready` | G0 for overrides | none | MS0 |
| IdentityWorkflow | §5 | ADT A40 merge, erasure request, correction | MPI merge or tombstone → dirty set → re-evaluation | G0 for erasure confirmation | none | MS2 |
| OnboardWorkflow | M0 | install, new source, schema change | connect → profile → propose mapping → lexicon mining → workbook → apply → re-profile | G0 | `propose_mapping` (D1, schema only) | MS0 |
| CompileWorkflow | M1 | protocol or amendment | library match-then-draft → IR v3 → equivalence gate → amendment diff → re-evaluate open candidates → consent re-versioning flag | G1 | `extract_criteria`, `concept_select` (D1) | MS1 |
| FeasibilityWorkflow | M3, M10 | `FEAS` confirmed, network request | §11.3 | G1, G2 | D1; D3 on-prem for the sample | MS1 |
| PreScreenWorkflow | M4 | `snapshot_ready` nightly; weekly per study; SIU micro-batch | §11.4 | G3 | `judge`, `second_opinion` (D3) | MS2 |
| MatchWorkflow | M5 | `MATCH`, tumour-board list | §11.5 | none (G3 if referred to a study) | `judge` (D3); retrieval models | MS2 (open studies), MS4 (registry) |
| RecallAuditWorkflow | SAFE | monthly per recruiting study | seeded samples per stratum → S4 re-evaluation → blinded CRC questions → confidence-sequence update → certificate → demotions | none (QA report) | `second_opinion` (D3) | MS2 |
| ActiveLearnWorkflow | M4 | weekly per CRC | choose ≤ 10 most informative judgements → yes/no questions with quotes → labels → calibration set and exemplar bank | none | none new | MS3 |
| TrackWorkflow | M6 | Mondays; monthly | reconcile pipeline → forecast → ledger rows → warnings and KRIs → NBA → digest | G2 for sponsor copies | `draft_narrative` (D1) | MS4 |
| LifecycleWorkflow | M7 | daily; Study Card, ADT, SIU, G4 and document events | evaluate playbooks → create or advance calendar items → arm timers → reminders → clocks → deviation candidates → KRIs | G1 (binding), G6 where a playbook says so | `extract_soa` (D1), `summarise_external` (D3) | MS4 |
| AbstractWorkflow | M8 | form + participant-visits; `QUERY`; pre-monitoring | field map → extract with lineage → validate → gap report → packets → EDC reconciliation | G1 (`field_map`), G6 (certification) | `abstract_field`, `draft_query_answer` (D3) | MS5 |
| CloseWorkflow | M9 | `STUDY <id> closed` | close playbook → retrospective → SAFE ever-excluded check → finance reconciliation → library and prior update → archive bundle → IRB final-report draft | G2 for external parts | `draft_document`, `draft_narrative` (D1) | MS5 |
| FederatedAnswerWorkflow | M11 | alliance or network request | compile (local G1 if new) → count → noise (cached) → mask → send → root sum → round → publish | G1, G2 or standing policy | M1 roles (D1) | MS5 |
| ChangeWorkflow | §8 | proposed G5 change | evaluation suites → bench → shadow comparison → recall re-establishment plan (SAFE) → report | G5 | evaluation only | MS0 |
| BakeoffWorkflow | §8, §16 | registry `candidate` builds; operator | §11.7 | none (output feeds G5) | all roles on D0 via OpenRouter routes | MS1 |
| ShadowPassWorkflow | §8 | nightly | replay the night's S3/S4 items on `shadow` builds → agreement and abstention statistics → no output to users | none | shadow builds (D3, on-prem only) | MS2 |
| RollbackWorkflow | §18 | operator, or an automatic trigger defined in §18 | §11.7 | retrospective G5 record | none | MS0 |
| ValidationReplayWorkflow | §16 | install, then quarterly | replay closed studies as of their recruitment start → capture reports (§16) | none | as production, recorded | MS1 |

### 11.3 FeasibilityWorkflow

```
start(request: FEAS confirmed via intake or tb.submit_request)                deterministic
 ├─ ensure_study_card · parse_document (CDR-converted input)                  doc-parser; D1
 ├─ guard classifiers (injection, policy) on protocol text                    guard roles; D1
 ├─ library_match → extract_criteria[J] match-then-draft (day pass)           LLM D1, recorded
 ├─ extract_criteria[V] (night pass) → reconcile with library and J           LLM D1; deterministic diff
 ├─ concept_select over terminology-service hits → compile IR v3              deterministic + LLM D1
 ├─ filter classes (SAFE-1) · zero-hit eligibility from lexicon_recall        deterministic
 ├─ equivalence_gate (CQL ≡ SQL on atoms + sample)                            deterministic; failure → listed
 ├─ outbox: understanding email + criteria workbook
 ├─ ⏸ G1 (A)
 ├─ cascade S0–S2, S2b on population · stratified sample                      SQL, lexicon, embeddings; D3
 ├─ S3[J] (night pass 1) · S4[V] (night pass 2) on the sample                 LLM D3 on-prem, budgeted, cached
 ├─ estimates (Wilson) · recruitability model · forecast-ledger row (M6)      deterministic
 ├─ competing trials · investigators · coverage analysis + budget (M10)       D0/D1; ⏸ G1 coverage (A)
 ├─ map_questionnaire[J]                                                      LLM D1
 ├─ accountant check → controlled rounding → render feasibility pack (§12)    deterministic
 ├─ draft_narrative[J] → numbers_match + citation verification                LLM D1 (aggregates)
 ├─ outbox: pack to requester
 ├─ ⏸ G2 (A)
 └─ outbox: release to the named recipient; privacy ledger; Study Card timeline; lineage id
```

D1 steps MAY use a cloud route in topology C, only where the routing policy permits it (sponsor consent for protocol
text, §8). Every D3 step is on-prem. If the run fails the equivalence gate, it does not stop: the understanding email
lists the criteria that failed, and those criteria are computed as `unknown`.

### 11.4 PreScreenWorkflow

```
snapshot_ready | weekly per study | SIU micro-batch (same-day appointments: S0–S2, S3 if budget allows)
 scope = appointments(next 14 d) ∪ watchlist flips due ∪ dirty set ∪ (weekly: study scope)
 ├─ S0 consent scopes and opt-outs · S1 structured (SQL, all recruiting rulesets) · CQL verify sample (5 %)
 ├─ S2 lexicon pre-filter + rescue sweep + assertion rules
 ├─ S2b semantic pre-filter for zero-hit pairs (exclude only where lexicon recall ≥ 0.98)
 ├─ sentence-set judgement cache lookup · dirty-set filter
 ├─ S3[J] lazy, ordered, short-circuit (night pass 1)       budgeted; unfinished items carried, never dropped
 ├─ S4[V] would-be strong + abstained (night pass 2)
 ├─ tiers (strong, potential:data_gap, potential:uncertain, …) · multi-span evidence · flip dates
 ├─ routing to the appointment owner · competing-allocation flags (FR-M6-17)
 ├─ attach latest recall certificate · render decision sheet + consolidated evidence PDF
 ├─ outbox: one packet per practitioner per clinic day; Teams/LINE count nudge (no PHI)
 ├─ ⏸ G3 per candidate (async; sheet, reply lines, review page)
 └─ G4 handoff to M6 · calibration update · exemplar bank · rejection-rate flags
```

### 11.5 MatchWorkflow (both directions)

Trial → patients is PreScreenWorkflow. MatchWorkflow serves patient → trials:

```
MATCH <mrn…> (delegated clinician) | tumour-board list for date D (night before)
 ├─ authorise: sender delegated for the patient's department; vault lookup MRN → pid (purpose logged)   D4 → D3
 ├─ open studies: evaluate all recruiting rulesets for the pid (cascade S0–S4, shared cache)            D3 on-prem
 ├─ registry trials: patient summary (on-prem) → retrieval over the local ClinicalTrials.gov index
 │     (BM25 + dense, TrialGPT-port retrieval) → criterion-level judge (same prompt, evidence schema)   D3 on-prem; index D0
 ├─ rank: open studies first, then registry trials labelled "not open at this site", with criteria met / unmet / unknown
 ├─ outbox: summary to the requester (internal e-mail; board packet for D)
 └─ optional: "refer to study <id>" reply → G3 candidate for that study's PI
```

A patient summary never leaves the perimeter. Registry text is D0, and the patient side is D3. MatchWorkflow creates no
pipeline state. A referral enters M6 only through G3.

### 11.6 IngestPublishWorkflow

```
batch_arrived(source, batch) | cdc_microbatch | hl7v2_group
 ├─ L0 land: immutable write; manifest {source, extract_time, rows, bytes, sha256, schema_fingerprint}
 ├─ L1 validate: contract, keys, referential integrity, control-total reconciliation, DQ rules, drift
 │    └─ blocking failure or reconciliation delta over threshold (§5) → quarantine; outbox: steward notice; STOP
 │       (T−1 stays current; release only by G0 override)
 ├─ L2 standardise: FHIR R4 (TW Core) + OMOP CDM 5.4; terminology service; UCUM; canonical text; language tags
 ├─ L3 pseudonymise: MPI merge table; pid service; vault separation; de-identified zone variants
 ├─ L4 curate: snapshot T candidate; FTS, embedding and sentence-hash indexes
 ├─ publish gate: DQ scorecard thresholds, coverage, reconciliation report → sign snapshot manifest
 ├─ L5 serve: atomic pointer switch to T; OpenLineage events; FHIR Provenance
 └─ emit snapshot_ready{T, dirty set} → PreScreen, Lifecycle (events), Track, Abstract (changed sources)
```

Thresholds, contracts and controls per stage are normative in §5. This workflow only orders them and guarantees that a
quarantined batch never becomes a published snapshot.

### 11.7 Bake-off, rollback, change and audit workflows

- **BakeoffWorkflow** runs `tools/bakeoff.py` against registry builds with status `candidate`. Tasks: criterion
  extraction (en, zh), judge (the 1,015 NCBI annotations plus zh/ja/code-mixed variants), intent classification,
  assertion, date and number normalisation, protocol Q&A. Settings are fixed prompts and schemas, temperature 0, and
  three seeds. The workflow reports per-task metrics with bootstrap CIs, cost and latency per 1,000 items, and a
  composite score with per-language floors. The gateway accepts only D0 on the OpenRouter routes and refuses the step
  otherwise. The report is stored in the registry. Status changes (`candidate → shadow → champion`) follow §8. No
  results exist yet (the API key is pending), and none are assumed here.
- **RollbackWorkflow** carries out the §18 procedures, which are normative. It runs for each change class: bundle,
  model/prompt/lexicon/threshold, ruleset, snapshot, channel, cloud route and whole site. The common steps are:
  1. freeze: pause passes and the outbox at the next step boundary;
  2. switch the pointer to the previous validated unit;
  3. recompute the dirty set;
  4. regenerate affected artefacts, marked "regenerated";
  5. verify per §18;
  6. resume the outbox;
  7. open a post-rollback review task due within 5 working days.

  Timers and clocks are not cancelled by a rollback (FR-WF-4). In-flight jobs finish on their pinned workflow version
  or are cancelled with a reason (FR-WF-7).
- **ChangeWorkflow** gathers G5 evidence. RecallAuditWorkflow and ValidationReplayWorkflow are specified by SAFE and
  §16. The workflow layer only guarantees their durability and seeding.

### 11.8 Requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-WF-1 | Kill -9 of the orchestrator at any point of FEAS, SCREEN or a gate MUST resume with no duplicate step and **exactly one** delivered message per outbox row (test: kill loop over every step boundary, with MailHog counting deliveries). | T | MS1 |
| FR-WF-2 | Gates time out into reminders: G0 at 3 and 7 days; G1 at 1 and 3 days; G2 at 1 day, then at the sponsor deadline the packet is **withdrawn** and the requester told; G3 candidates roll into the next packet; G4 has no timeout. | T | MS1 |
| FR-WF-3 | **Step identity.** `input_hash` MUST cover the step inputs, the workflow version, the code SHA and, where a model is involved, the model SHA, prompt version, routing-policy version and snapshot id. A replay with equal hashes MUST reproduce byte-identical outputs from recorded results (§13). | T | MS0 |
| FR-WF-4 | **Durable timers.** Reminders, clock thresholds and gate timeouts MUST be `timers` rows, armed in the same transaction as the item that needs them. A timer fires at least once; its handler is idempotent per `timer_id`; it survives restarts, failover and rollbacks. Test: kill loop and clock jumps around 50 % and 90 % thresholds with zero lost or duplicate reminders. | T | MS1 |
| FR-WF-5 | **Inbound deduplication.** Every inbound message (e-mail, Teams, LINE, Hermes relay) MUST be written to `inbox` and deduplicated before intake runs. A duplicate never creates a second job or a second approval. | T | MS1 |
| FR-WF-6 | **Hermes boundary.** Requests from Hermes MUST arrive only through the front-door MCP tool `tb.submit_request` and become jobs like any other request. Gate replies relayed by Hermes MUST be byte-for-byte the sender's text and are parsed by deterministic intake (§3, §9). | T | MS1 |
| FR-WF-7 | **Versioning.** A job MUST finish on the workflow version it started with, unless an explicit migration is registered for that version pair. Rolling back the bundle MUST NOT orphan in-flight jobs: each one either continues on its pinned version or is cancelled with a reason and a notice. | T | MS1 |
| FR-WF-8 | **Declared classes.** Every step MUST declare the data classes it reads and sends to a model. The gateway rejects a model call whose class exceeds the declaration. A CI check fails if a workflow step lacks a declaration. | T, I | MS0 |
| FR-WF-9 | **Concurrency.** Workers MUST claim steps with leases (`SELECT … FOR UPDATE SKIP LOCKED`, heartbeat, expiry). A step whose lease expires is retried with the same `input_hash`. Only one model pass per GPU profile runs at a time (§4). | T | MS0 |
| FR-WF-10 | **Kill switches.** A per-module switch in the admin control plane MUST pause that module's workflows at the next step boundary and hold their outbox rows. Safety-clock timers keep firing to their owners unless the system owner explicitly overrides, and the override is audited. | T | MS1 |
| FR-WF-11 | **Budget exhaustion.** When a pass or monthly budget is exhausted, remaining items MUST be carried to the next pass with their order kept and flagged in the manifest. They are never dropped, and their tier stays `potential:uncertain` until judged. | T | MS1 |
| FR-WF-12 | **Lineage.** Every workflow run MUST emit OpenLineage run events (§5). Every released artefact carries a lineage id that resolves to source batch → snapshot → ruleset or field map → run → file. | T | MS1 |
| FR-WF-13 | **Gate hygiene.** Gate objects are hash-bound. A change to an object supersedes its open gate and sends a fresh request (FR-SIG-2). The gate backlog (open G3, G4 and G6 items older than 48 h) is a KRI on the admin control plane and in the digest. | T | MS1 |
| FR-WF-14 | **G6 timeouts.** G6 requests are reminded at 1 and 3 days and escalated to the PI at 5 days. G5 has no timeout. Neither is ever satisfied or bypassed by a timeout. | T | MS2 |
| FR-WF-15 | **Quarantine never publishes.** In IngestPublishWorkflow, no path may switch the L5 pointer to a snapshot whose L1 validation had a blocking failure, unless a G0 override for that batch exists. Test: planted defects (0.5 % row drop, schema drift, key violations) on Synthea batches. | T | MS0 |
| FR-WF-16 | **Workflow tests.** Every workflow in §11.2 MUST have a kill-loop test, a replay test (byte-identical outputs from recorded results) and a gate-path test. All three are traced with `@req` to this section (§17). | T | MS1 |
