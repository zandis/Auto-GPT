# TrialBox

*Owner: Product owner. Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

TrialBox is a box a hospital owns. It finds patients for clinical trials in the hospital's own data, and it helps the
site run the trial after that. Nothing leaves the box unless the site says so.

- A coordinator pastes a protocol. The investigator approves the criteria. The box counts the patients who fit.
- Each night it screens the patients. Rules in SQL go first. Then two local models read the notes. A note answer
  excludes a patient only when both models agree on a quote.
- The investigator and the coordinator work through a list on a desktop or a phone, in Japanese, Chinese or English.
- The site records consent, enrolment, visits, adverse events and deviations in TrialBox's own forms, and can sync
  them two-way with REDCap or a spreadsheet.
- Every step goes into a hash-chained audit log.

All patient data in this repository is synthetic or public. No real patient record is here.

## The eight documents

| Document | For | What |
| --- | --- | --- |
| [README](README.md) | everyone | this page: what TrialBox is, how to try it, the map |
| [Architecture](docs/ARCHITECTURE.md) | builders, hospital IT | services, stores, data and rule paths, models |
| [Runbook](docs/RUNBOOK.md) | the site's IT | install, update, back up, operate, fix, GPU runs |
| [Security and compliance](docs/SECURITY.md) | security officers | hardening, secrets, network, audit, laws |
| [Data and integration](docs/DATA.md) | hospital IT, data owners | sources, mapping, REDCap, open data and licences |
| [Validation and evidence](docs/VALIDATION.md) | owner, reviewers | the gates, the tests, the measured numbers |
| [User guide](docs/USER_GUIDE.md) | PIs, CRCs, admins | roles, daily tasks, help in ja, zh-TW and en |
| [Decisions](docs/DECISIONS.md) | everyone | every choice (D-nnn), append-only |

Records that are not maintained: `docs/reviews/` (reviews), `docs/plan/` (plans and the design set),
`docs/research/` (research), `spec/v4/` (the v4 specification) and `spec/archive/` (older specifications).

## Try it (no GPU, no Docker)

You need Python 3.12 and `uv`.

```sh
cd trialbox
make venv                 # .venv with the pinned dependencies
make e2e-simple           # the build gate: about 2 minutes, prints PASSED
make demo                 # the whole flow seeded, console on http://127.0.0.1:8080
python -m tools.public_e2e --dir /tmp/tb-public --lang ja      # the same path on public notes
python -m tools.complete_run --dir /tmp/tb-complete            # every stage, ja and zh-TW, with screenshots
```

`make demo` prints one password for the five accounts (`admin`, `crc`, `pi`, `cra`, `viewer`), or uses
`TB_DEMO_PASSWORD` when set and then prints nothing. The data is a
5,000-patient synthetic hospital with notes in Japanese, Chinese and English.

With Docker, `deploy/poc.sh` (or `make poc`) runs the whole box with test mail servers on synthetic data
([Runbook §9](docs/RUNBOOK.md#9-proof-of-concept-with-docker)).

## Install at a site

Read the [Runbook](docs/RUNBOOK.md). In short: harden the host ([Security](docs/SECURITY.md)), then
`sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml`. The installer refuses a tier whose
card has no measured serving record.

## Repository map

| Path | What |
| --- | --- |
| `services/` | console, orchestrator, gateway, mail_gateway, criteria_compiler, doc_parser, adapter, lake, embed_service, datacore, sitesetup, matching, deliverables, registry, guard, tracestore, rc_bridge, rc_sim, llm_stub, channels |
| `libs/` | `tb_contracts` (models generated from `schemas/`), `tb_common` (config, audit, db, service tokens, crypto, LLM client, retention), `tb_llm`, `tb_testkit` |
| `schemas/` | JSON Schemas, the one source of every contract |
| `rulesets/` | approved demo rulesets: GZQO (trial), GOUT-COH and RA-COH (cohorts), RA-BIO and ONC-OSI (NHI) |
| `deploy/` | compose files per GPU profile, `install.sh`, `network.sh`, `check_host.sh`, measured serving records, Windows preflight, GCP scripts |
| `tools/` | the gates and drills (`e2e_simple`, `public_e2e`, `complete_run`, `backup_drill`, `update_drill`), the synthetic hospital, the walk, the CLI `tools/trialbox` |
| `tests/` | unit, console, testbench, integration, e2e, LLM |
| `eval/` | measured results: model gate, TREC, public data, GPU runs |
| `docs/handover/` | the printed network sheet (en, ja, zh-TW), offline media, Windows checklist |
