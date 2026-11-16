# D-898 the box installs unattended from the owner's answers file

- **Task:** BOX-ANSWERS, lane D backlog item 5. The integrator said yes on #639 (2026-11-16): "the hospital install is
  unattended". It comes from lane G's audit: `box-install-run.sh` passes `--answers`, which `box-install.sh:40`
  refused.
- **PR:** this branch (`agent/BOX-ANSWERS-the-box-installs-unattended`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

1. `deploy/box-install.sh <bundle> --answers owner.json` takes the owner's answers from a JSON file instead of the
   first-run wizard. These are the first-run form's fields, flat or nested, as `tb_common.box_answers.parse` reads
   them, with `environment` set to PRODUCTION or VALIDATION. There is no question (`--yes` is implied), no one-time
   code and no wait.
2. The plan is made from those answers (`tools.box plan --owner`) instead of the provisional ones. A VALIDATION box is
   therefore made by one command: the plan carries `TB_ENV` (D-822).
3. The install runs in the IT form (`TB_BOX=0`). It makes the first administrator, whose password and enrolment code
   are printed once, as every non-box install does. The owner's own account, with its password and second factor, is
   made by a person in the console afterwards. A password cannot be part of an unattended file.
4. Checked before anything is written, so a refusal changes nothing:
   - the file is JSON;
   - it holds no `password`, `password2`, `totp`, `kek`, `kek2` or `kek_passphrase`: a secret never goes in a file;
   - the answers parse;
   - on a board without a usable TPM, `TB_KEK_PASSPHRASE` is set in the command's environment (12 characters or
     more). The keys are then sealed at the install (no deferred seal) under the plan's `KEK_BACKEND=passphrase`.
5. After the install: the host's time zone from the answers, the `applied` mark (a later `--firstrun` asks nothing
   again), the stack restart, the backup schedule and the host check, as after the wizard. The last line says to sign
   in as admin with what was printed.
6. `--answers` with `--prepare`, `--rehearsal` or `--firstrun` is refused (exit 2). A prepared image is answered at
   the site's first boot; a rehearsal box is TEST.
7. RUNBOOK §16 says the same.

## Test

`tests/console/test_box_install_rehearsal.py` runs the real script with stand-ins for the inner install, compose and
the host check:

- An unattended VALIDATION install: the plan is from the file, the install runs with `TB_BOX=0`, there is no code and
  no issue file, the last line is printed, and the `applied` mark is set.
- A file with a password or passphrase, or one that does not parse, changes nothing.
- Without a TPM, the passphrase comes from the environment, the keys are sealed at the install, and the passphrase is
  never printed.
- The refused combinations.

The existing box-install tests still pass.
