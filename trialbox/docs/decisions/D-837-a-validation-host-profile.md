# D-837 a VALIDATION box on a plain VM: the environment answer and the poc host profile

- **Task:** I-6 of the independent examination of the bundle and installer path (2026-11-15, #639)
- **PR:** this branch (`agent/I-6-a-validation-host-profile`), stacked on D-836's
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-127 (PRODUCTION by default), D-822 (the VALIDATION box), D-836 (TB_KEK_BACKEND)

## Decision

1. `install.sh --environment DEV|TEST|VALIDATION|PRODUCTION` sets `TB_ENV` after the settings wizard; a `TB_ENV`
   written into deploy/.env before the wizard is kept (the wizard rewrote the file and D-127 made the box PRODUCTION);
   an answer that contradicts the box's own `TB_ENV`, or a rehearsal that is not TEST, stops the install.
2. One declared setting, `TB_HOST_PROFILE` (`site`, default; `poc`): a proof of concept or validation run on a plain
   VM. Under `poc` the host-facility checks WARN and are listed: check_host.sh's TPM, LUKS, sealed keys, firewall,
   SSH, cron and egress table; doctor's `key_custody` and `anchor_mount` (one `host_profile` line lists them).
   install.sh keeps the profile in deploy/.env, skips the systemd units by default (`TB_SYSTEMD=0`) and, with no
   usable TPM and no `TB_KEK_BACKEND`, leaves the keys unsealed with a note. `poc` on PRODUCTION is a FAIL in doctor
   and check_host.sh and stops install.sh. `registry_pins` (no champion yet) is not relaxed: qualifying the pair is
   what the run is for.
3. `TB_BOX_DEFER_SEAL` and `TB_SYSTEMD` are declared, with their reasons.

## Test

`tests/unit/test_host_profile.py` runs the install.sh blocks, check_host.sh's baseline (through
test_host_baseline's box) and doctor.run: before, 12 failed; after, all pass.
