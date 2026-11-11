# Functional specification index (FS-01 to FS-17)

*Card T-215 (deep review PLAN-027 FS part; TB-ASSESS-01 WS-12.2). Decision D-344. Status: living; a pull request that
adds or changes a workstream's pages, APIs or rules updates its row.*

One functional specification per workstream: FS-nn belongs to workstream WS-nn of TB-PLAN-05. The `fs` column of
`docs/plan/25-traceability.csv` names these ids; `tests/unit/test_validation_records.py` checks that every id used
there has a row here and that every path in a row exists.

A row does not restate the requirement text. It names **where the function is specified and built**: the pages, the
APIs and modules, and the rules (decisions and rule files). The requirement text is TB-PLAN-05 §5; the behaviour in
detail is the design set (`docs/plan/design/`) and the decisions.

| FS | Workstream | Pages (console templates) | APIs and modules | Rules and design |
| --- | --- | --- | --- | --- |
| FS-01 | WS-01 Platform hardening | `services/console/templates/home_crc.html`, `services/console/templates/overview.html` | `services/console/app.py`, `services/orchestrator/` | `docs/ARCHITECTURE.md`; `docs/plan/design/02-architecture.md` |
| FS-02 | WS-02 Gate G1 and model qualification | none | `services/gateway/`, `libs/tb_llm/`, `tools/trialbox/eval.py` | `models/registry.yaml`; D-313 (`docs/decisions/D-313-qualify.md`); `docs/VALIDATION.md` |
| FS-03 | WS-03 Data core, vocabulary, provenance, conflicts | `services/console/templates/data_conflicts.html`, `services/console/templates/data_sources.html` | `services/datacore/`, `services/omop/`, `services/adapter/` | `docs/DATA.md`; `docs/plan/design/07-data-dictionary.md`; `docs/plan/design/10-terminology-mapping.md` |
| FS-04 | WS-04 Clinical item catalogue and derived scores | `services/console/templates/data_entry.html` | `libs/tb_common/derived.py`, `libs/tb_common/scores.py` | `libs/tb_common/score_defs.json`; `tools/gen_score_defs.py` |
| FS-05 | WS-05 Profile, twin, vectors | `services/console/templates/patient.html` | `services/embed_service/`, `services/lake/` | intended-use condition C12 (`docs/plan/intended-use.md`) |
| FS-06 | WS-06 Roles, delegation, referral, candidate view, opt-out | `services/console/templates/team_candidates.html`, `services/console/templates/team_referrals.html`, `services/console/templates/site_optouts.html`, `services/console/templates/users.html` | `libs/tb_common/authz.py`, `libs/tb_common/optout.py`, `services/console/team.py`, `services/matching/` | `docs/SECURITY.md`; `docs/plan/design/09-ui-ux-spec.md` |
| FS-07 | WS-07 EDC prefill, trial records, REDCap | `services/console/templates/edc.html`, `services/console/templates/edc_review.html`, `services/console/templates/screening_log.html`, `services/console/templates/sae_worklist.html` | `services/edc/`, `services/rc_bridge/`, `services/console/screening_log.py`, `services/console/saerecord.py` | `docs/plan/design/08-interface-control.md` |
| FS-08 | WS-08 Data operations, import and export, storage | `services/console/templates/admin_ops.html`, `services/console/templates/jobs.html` | `services/adapter/`, `services/lake/`, `libs/tb_common/feedguard.py` | D-312 (`docs/decisions/D-312-feed-completeness-gate.md`); `docs/RUNBOOK.md` |
| FS-09 | WS-09 Consortium | `services/console/templates/reports.html` | `services/deliverables/`, `libs/tb_common/smallcell.py` | `docs/DATA.md` |
| FS-10 | WS-10 Site onboarding, Japan | `services/console/templates/site_wizard.html`, `services/console/templates/site_ready.html` | `services/sitesetup/`, `services/adapter/mapping/` | `docs/plan/design/15-site-acceptance-protocol.md` |
| FS-11 | WS-11 Site onboarding, CGMH | `services/console/templates/site_wizard.html` | `services/sitesetup/`, `deploy/platform/` | `docs/RUNBOOK.md` §17 (on a hospital platform) |
| FS-12 | WS-12 Validation and quality system | none | `tools/gen_traceability.py`, `tools/doclint.py` | `docs/plan/25-vmp.md`; this folder |
| FS-13 | WS-13 Security and privacy | `services/console/templates/login_totp.html`, `services/console/templates/identity_admin.html`, `services/console/templates/audit.html` | `services/console/auth.py`, `services/guard/`, `libs/tb_common/audit.py`, `libs/tb_common/phi_guard.py` | `docs/SECURITY.md`; `docs/plan/design/03-security-privacy.md` |
| FS-14 | WS-14 Release and deployment | none | `tools/trialbox/update.py`, `tools/apply_update.sh`, `tools/trialbox/doctor.py`, `tools/trialbox/backup.py` | `docs/RUNBOOK.md` §5; `change-control.md` (this folder) |
| FS-15 | WS-15 Commercial and legal | `services/console/templates/about.html` | none | `docs/plan/design/16-regulatory-position.md` |
| FS-16 | WS-16 Evidence (Study A) | none | `tools/funnel_compare.py` | `docs/plan/study-a-protocol.md` (a draft; T-010 struck by D-311 B25) |
| FS-17 | WS-17 Documentation, training, support | `services/console/templates/help.html` | `services/sitesetup/help.py` | `docs/USER_GUIDE.md`; `qms-lite.md` §3 (this folder) |
