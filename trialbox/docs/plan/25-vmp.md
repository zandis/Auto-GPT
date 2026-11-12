# TB-VMP-01 Validation master plan for the TrialBox pilot (GAMP 5)

| Field | Value |
| --- | --- |
| Document ID | TB-VMP-01 |
| Version | 1.1 (2026-11-10, card T-215, decision D-344). Replaces 1.0 (draft for signature, 2026-11-09) |
| System | TrialBox, release line of TB-PLAN-05 and TB-PLAN-06, at CGMH (containers on the hospital's B200 platform) and at the Japan site (appliance) |
| Plan | `docs/plan/28-master-plan-v6.md` (TB-PLAN-06) wins over `docs/plan/25-master-plan.md` (TB-PLAN-05) §7 and §8, which hold the detail |
| Records | `docs/validation/` (layout in its `README.md`) |
| Signatures | none. D-311 removed the signature table of v1.0 and every signer of a development step (§9) |

## 0. What D-311 changed

Building, testing, deploying and sharing TrialBox use synthetic or public data only and need no gate record, no signer
and no named human reviewer (D-311, TB-PLAN-06 §0). This plan therefore has two parts:

* **Always.** The development records of `docs/validation/` are kept as the work happens, by the pull request that
  does the work: the change class, the tests, the problem log, the SOUP list, the release record. CI is the check.
* **Only when TB-PLAN-06 §0.3 item 2 applies** (EDC prefill writes into a sponsor's regulated trial record). Then the
  formal IQ, OQ and PQ of TB-PLAN-05 §7.3 return for that site and that study, with the roles of §2 and the
  protocols of card T-315b (`docs/validation/protocols/`). Until then the install check (`doctor`) and the recount
  test run as automated tests (D-311 B28) and no IQ, OQ or PQ record is made.

## 1. Purpose, scope and the frame

This plan states how TrialBox is shown fit for its intended use (`docs/plan/intended-use.md`) and how it stays fit
after a change. It covers the software TrialBox ships (GAMP 5 category 5), the configured products it runs on
(categories 3 and 4), the hospital platform it runs in at CGMH (categories 1 and 4, owned by the hospital) and the
site configuration (mapping, rules, settings). It does not cover the hospital's EMR, REDCap or sponsor EDCs.

**Edition.** GAMP 5 Second Edition (ISPE, July 2022), with the ISPE GAMP guide on artificial intelligence (2025) for
the model sub-system (§5). ICH E6(R3) is cited as the consolidated Step 4 text of 2026-06-16 (principles and
Annex 1 of 2025-01-06, Annex 2 of 2026-06-16). The standards TrialBox follows as good practice and those it does not
are in `docs/validation/standards-position.md`.

**Risk-based assurance.** Rigour follows the GxP impact of each function (§3), not one level for all. A function with
no GxP impact is assured by the CI suite and unscripted testing; a high-impact function gets scripted tests at several
levels, property and mutation tests where it is in the screening core, and, under §0.3 item 2, a scripted OQ step.
GAMP 5 Second Edition calls this critical thinking; the FDA's guidance on computer software assurance says the same.

## 2. Regulated user and responsibilities

Under GCP the **regulated user is the site**: the hospital and the investigator answer for the computerised systems
they use for a trial (ICH E6(R3) Annex 1, data governance and computerised systems). The **vendor** (Aimedics)
supplies the system and the evidence: the development records, the release record, the supplier information and,
under §0.3 item 2, the executed protocols. The sponsor answers for its own EDC.

| Role | Answers for | Under D-311 |
| --- | --- | --- |
| Site (hospital and investigator) | deciding to use TrialBox for a trial task; its own procedures; accepting a release at the site | no development step; acts only when real data is read |
| Vendor (Aimedics) | the software, its records, the release record, the supplier assessments, support | the records are written by the pull requests and CI |
| Sponsor | its EDC and its monitoring | only where prefill writes to its EDC (§0.3 item 2) |
| Platform owner (CGMH IT) | the B200 host and the namespace, category 1 and 4 | recorded as a supplier (`docs/validation/supplier-assessments.md`) |

There is no named approver, executor, witness or co-signer for development. Where §0.3 item 2 applies, the executor
of an IQ or OQ step is not the author of the change it tests; that is the only independence rule kept.

## 3. GxP assessment per function

Impact: **H** a failure can change what the research team does for a patient, put a wrong value into a trial record
or expose a patient; **M** a failure loses or delays work, or misstates a count, and is caught by the next step;
**L** a failure is cosmetic or confined to a tool. The H functions are those of TB-DS-04 §2.2 and TB-PLAN-05 §7.2.

| Function | Code | GxP relevance | Impact | Assurance |
| --- | --- | --- | --- | --- |
| Eligibility screening (cascade, criteria engines, unknowns) | `services/matching/`, `services/criteria_compiler/`, `services/orchestrator/scenarios/` | supports the investigator's screening; the site screens again before consent | H | unit, property, mutation and engine-agreement tests; goldens; `e2e-simple`; model qualification (§5) |
| Note-based exclusion (the model pair) | `services/gateway/`, `libs/tb_llm/`, `models/registry.yaml` | as above; a wrong "not matched" drops a candidate | H | `trialbox eval qualify` record per build; canary; N-11 and N-12 gates |
| PHI scrubbing and the guard | `services/guard/`, `services/model_guard/`, `libs/tb_common/phi_guard.py` | privacy of trial subjects and patients | H | unit and property tests; the data scan; egress tests |
| Reveal, roles and sign-in | `libs/tb_common/authz.py`, `services/console/auth.py` | who sees identified data; attributable actions | H | the authorisation matrix test; second-factor tests |
| Audit chain | `libs/tb_common/audit.py`, `tools/audit_verify.py` | ALCOA+ for every action | H | tamper tests; daily head verification |
| EDC prefill and copy-assist | `services/edc/`, `services/console/edc_pages.py` | writes values into a trial record | H | contract tests on the simulator; blind re-entry under §0.3 item 2 |
| Opt-out propagation | `services/orchestrator/`, `services/lake/` | a patient's choice | H | the opt-out property test |
| OMOP and lake parity | `services/omop/`, `services/lake/` | the data the screen reads | H | parity report; feed-completeness gate (D-312) |
| Screening log, SAE register, consent record | `services/console/screening_log.py`, `services/console/saerecord.py` | essential records support (E6(R3) Appendix C) | M | unit and journey tests; exports compared with the source |
| Research profile (C12) | the profile module | research staff only (class A) | M | unit tests; classification review if a clinician ever sees it |
| Data-ops pages, statistics, feasibility counts | `services/console/data_pages.py`, `services/console/ops_pages.py` | counts are re-checked by the site | M | unit tests; the known-cohort recount |
| Mail, reports, deliverables | `services/mail_gateway/`, `services/deliverables/` | notification only; no record | L | unit tests; no PHI in mail test |
| Install, update, backup | `tools/trialbox/`, `deploy/` | data loss would lose records | M | `doctor`; update and restore drills as tests |
| Demo, bench and evaluation tools | `tools/demo.py`, `tools/bench.py` | none | L | smoke tests |

The internal 62304-style class of each path is in `docs/validation/software-safety-classification.md`; this table is
about GxP impact and does not repeat it.

## 4. Deliverables

| Deliverable | Where | Kept by |
| --- | --- | --- |
| User requirements | TB-PLAN-05 §5 | the plan |
| Functional specification, per workstream | `docs/validation/functional-spec.md` | the pull request that changes a workstream's pages, APIs or rules |
| Design specification | `docs/ARCHITECTURE.md` and `docs/plan/design/` | as now |
| Risk file | TB-PLAN-05 §6 and TB-DS-11 (one file on one scale was struck, D-311 B18) | the plan |
| Traceability matrix | `docs/plan/25-traceability.csv`, generated by `tools/gen_traceability.py`; a warning in CI (D-311 S7) | the generator |
| Development records (62304-style) | `docs/validation/` | the pull requests |
| Change records | the pull request, with its change class (`docs/validation/change-control.md`) | the pull request |
| Release record | `docs/validation/release-records/<version>.md` | the release step |
| Supplier assessments | `docs/validation/supplier-assessments.md` | the pull request that adds or upgrades a supplier |
| IQ, OQ, PQ protocols and executed records | `docs/validation/protocols/` (card T-315b) | only under §0.3 item 2 |

## 5. The model sub-system

The model pair is **not** category 3 or 4 in effect. The weights are bought-in (SOUP, in `docs/validation/soup.csv`),
but the prompts, thresholds, the two-model rule, the excerpt budget and the routing are TrialBox's own, so the
sub-system is custom (category 5) and has its own life cycle:

1. **Specify.** The judge and verifier tasks, the prompt versions in the prompt registry (D-300), the thresholds.
2. **Qualify.** `trialbox eval qualify` (D-313) runs the gated sets per language through the gateway and writes the
   qualification record: builds, hashes, commit, results. A build without a passing record is not `champion`.
3. **Release.** The release record names the qualified pair. A change to weights, quantisation, serving version,
   prompt text, threshold or routing is change class CC1 (`docs/validation/change-control.md`).
4. **Monitor.** The canary nightly, the weekly drift chart, the quarterly drift check (canary, N-12, the public set).
5. **Retire.** A retired build keeps its qualification record and its hash in the release record that last shipped it.

## 6. Deviations and corrective actions

A **deviation** is a test, check or step that did not give its expected result, or a procedure not followed.

1. It is a row in `docs/validation/problems.csv` (the problem log of card T-654): what happened, where, the class of
   the path, the severity.
2. **Severity.** Under D-311 S5 a release is blocked only by an open wrong-answer, data-loss or security problem.
   Anything else is recorded and fixed in a later release.
3. **Corrective action.** A fix pull request names the row; the row names the fix PR and the test that now verifies
   it. A row is closed only with that test.
4. **Preventive action.** When the same cause appears twice, the row says what changes in the process (a new test,
   a CI check, a rule in `docs/validation/development-plan.md`).
5. Under §0.3 item 2 a deviation in an executed protocol is also written in that protocol, with its row number.

## 7. Retirement and data migration

* **Retiring a release.** The release record stays; the images stay pinned by digest in the release that shipped
  them; going back to it is the previous bundle applied with `--allow-downgrade` (audited; `docs/RUNBOOK.md` §5).
* **Migrating data** (a new host, a new schema, the interim cloud to the box): by backup and restore; the migration
  is verified by the record counts, the audit-chain verification and the known-cohort recount before and after; the
  pre-migration backup is kept for the retention period.
* **Retiring TrialBox at a site.** The site receives an export of its records (screening log, consent records, SAE
  register, audit chain with its verification), the box's keys are destroyed after the export is confirmed, and the
  retirement is written in the last release record.

## 8. Frozen release, change control and periodic review

OQ and PQ, when they apply, run on a frozen release identified by `release.json`. Change control, the change classes
CC1 to CC6 and the staged roll-out are in `docs/validation/change-control.md`. After go-live a six-monthly periodic
review (and one after any incident) reads the problem log, the drift chart, the qualification records, the open
changes and the supplier list, and writes its outcome in the next release record. It has no signer.

## 9. Removed from v1.0 by D-311

* The signature table (nine roles) and "signed before any IQ step" (D-311 B1, B14, B28).
* The independent CGMH second reviewer and the steward's co-signature (D-311 B8, B24).
* The approver, executor and witness roles for development; the safety-core engineer as co-approver (D-311 B10).
* The validation summary report signed per site and the G4 to G6 ritual at CGMH (D-311 B28).
* The non-waivable list of v1.0 §6 as a development gate. The items about real data (security measures, a
  breach-notice plan) are TB-PLAN-06 §0.3 item 1 and apply from the first read of real data.
