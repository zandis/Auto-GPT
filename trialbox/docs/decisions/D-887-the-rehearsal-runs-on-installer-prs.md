# D-887 the box rehearsal runs in CI, by hand and on installer pull requests, in two variants

- **Task:** I-8 (the integrator's answer on #639, 2026-11-15: no schedule, D-511 stands)
- **PR:** this branch (`agent/I-8b-the-rehearsal-runs-on-installer-prs`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

1. `.github/workflows/trialbox-rehearse-box.yml` runs `make rehearse-box` on `workflow_dispatch` and on a pull request
   that touches the installer path; never on a schedule. Two legs: `test` (the rehearsal as it is) and `validation`.
2. `TB_REHEARSE_VARIANT=validation`: the passphrase KEK with no TPM, `TB_HOST_PROFILE=poc`, a root-owned `deploy/site`,
   and a second install of the same bundle (`reinstall`: continues, keeps `kek.json`). The box stays TEST, where the
   model stand-ins are honoured (D-726); the environment name VALIDATION itself is not rehearsed.
3. install.sh seals the site keys on any box whose installer environment names `TB_KEK_BACKEND` (before: a DEV or
   TEST box only with a hardening.conf, which also sets the firewall and SSH).

## Test

`tests/unit/test_rehearsal_workflow.py`: before, 6 failed; after, 6 passed. The workflow itself proves the run.
