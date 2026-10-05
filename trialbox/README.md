# TrialBox

TrialBox is an on-prem appliance driven by e-mail. It compiles eligibility rules (clinical-trial protocols, Taiwan
NHI reimbursement rules, alliance cohort definitions) into **auditable, deterministic patient screens** over the
hospital's own data.

- Nothing to log into: send `FEAS GZQO` to the box and a feasibility report comes back.
- Patient lists go only to internal recipients, encrypted.
- Every output file is hashed into an append-only audit chain.
- SQL and CQL are generated from templates and checked against each other (≥ 98 % equivalence) before a ruleset can
  be approved. LLMs only extract criteria from documents and judge free-text notes, through schema-constrained
  calls.

| What | Command (mail subject) | You get |
| --- | --- | --- |
| Feasibility | `FEAS GZQO` (+ protocol PDF the first time) | funnel PDF + XLSX, enrolment simulation |
| Approve a compiled protocol | reply with the filled `review.xlsx` | approved ruleset (git tag) |
| Screening | `SCREEN GZQO version=1.0.0` | candidate workbook (encrypted) + summary PDF; weekly `this_week_visit1.xlsx` |
| NHI navigation | `NAV RA-BIO dept=RHEU` | likely-eligible / renewal / doc-gap / maybe-ineligible lists, application drafts, TWPAS bundles |
| NHI submission | `SUBMIT ONC-OSI pid=… bundle=<NAV job>` (physicians) | ClaimResponse (dry run by default) |
| Cohort tables | `COHORT GOUT-COH` | alliance CSV, report, ClinicalTrials.gov trial simulation; `COHORT MERGE` at the alliance root |

## 10-minute quickstart (synthetic data, no GPU)

Prerequisites: Docker 27+ with compose, Python 3.12 and `uv`, about 15 GB of disk. Runs on Linux x86_64 and on
macOS. On macOS, set `TB_LLM_MODE=stub` (the default in `.env.example`).

```sh
cd trialbox
make venv                      # .venv with the pinned dependencies
make images                    # fetches fonts + HL7 validator + CQL translator + FHIR packages, builds 2 images
make up-test                   # whole box + stub LLM + GreenMail (IMAP 3143/SMTP 3025) + MailHog (8025)
curl -s -X POST localhost:8016/run -H 'Content-Type: application/json' -d '{"source":"csv"}'   # ingest site A
.venv/bin/python tools/send_test_mail.py "FEAS GZQO"
```

Open <http://127.0.0.1:8025>. Within a few seconds MailHog shows "Received …", then "Done …" with the
feasibility PDF and XLSX for the GZQO retatrutide gout protocol on the 600 synthetic patients.

Next, try:
```sh
.venv/bin/python tools/send_test_mail.py "SCREEN GZQO version=1.0.0"        # encrypted list; password in a 2nd mail
.venv/bin/python tools/send_test_mail.py "NAV RA-BIO dept=RHEU" --sender nurse-rheu@hospa.test
.venv/bin/python tools/send_test_mail.py "COHORT GOUT-COH"
```

Run the checks a contributor runs:
```sh
make lint test                 # ruff, mypy --strict, ~270 unit + in-process tests (no services needed)
make test-integration          # against the running test stack (HAPI, validator, mail)
make test-e2e                  # every scenario by e-mail
```

## Deploying a real site

Follow **`docs/RUNBOOK.md`**:
1. Harden the host (`docs/HARDENING.md`: LUKS + TPM, swap off, `deploy/check_host.sh`).
2. Run `python -m tools.settings_wizard`.
3. Copy a mapping template from `services/adapter/mapping/templates/` and check it with `tools/mapping_check.py`.
4. Bring the stack up: `docker compose --profile gpu up -d`, with `-f docker-compose.gb10.yml` on NVIDIA GB10.
5. Apply the egress rules: `deploy/network.sh apply`.
6. Run the §11.2 go-live acceptance with `tools/acceptance.py`.

No code changes are needed for a new site.

## Repository map

| Path | What |
| --- | --- |
| `SPEC.md` | the specification (v1.0) |
| `docs/` | `PLAN.md`, `ARCHITECTURE.md` (as built), `DECISIONS.md` (every choice and deviation), `PROGRESS.md` (phase log + evidence), `RUNBOOK.md`, `HARDENING.md`, `BENCH.md` |
| `schemas/` → `libs/tb_contracts` | JSON Schemas (the contracts) → generated pydantic v2 models (`make contracts`) |
| `libs/tb_common` | config, audit chain, LLM gateway, PHI guard, routing, crypto, deterministic outputs, … |
| `services/` | mail_gateway, orchestrator (scenarios + reports), criteria_compiler, doc_parser, adapter, lake, embed_service, llm_stub |
| `rulesets/` | approved rulesets shipped with the box: GZQO (trial), RA-BIO + ONC-OSI (NHI), GOUT-COH + RA-COH (cohort) |
| `deploy/` | compose files (x86, test, GB10), Dockerfiles, `settings.example.yaml`, `network.sh`, `check_host.sh` |
| `tools/` | fixtures, ruleset build, bench, acceptance, wizard, mapping check, update signing/applying, audit verify, … |
| `tests/` | unit, integration (in process + services), e2e (mail), LLM, fixtures (synthetic hospitals A/B, protocols, onboarding) |

All patient data in this repository is synthetic (`tools/make_fixtures.py`, 600 + 520 patients). ClinicalTrials.gov
records in the cassettes are fictional (`NCT990000xx`, titled `[SYNTHETIC]`).
