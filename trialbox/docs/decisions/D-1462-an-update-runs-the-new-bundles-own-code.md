# D-1462 An update runs the new bundle's own code; the installed box gives only the trust and its data

- **Card:** H-124 (lane H), the integrator's rulings 7128338428, 7131272906, 7132081597, 7132484063, 7133378239,
  7135119782 and 7136231344, after H-121's finding H121-06. Page:
  `docs/handover/h124-update-code-from-the-bundle-2026-11-24.md`. · **Date:** 2026-11-24
- **Problem:** `tools/apply_update.sh` ran the installed release's `tools.trialbox update`. A fault in the installed
  release's update code could be mended only by a reinstall: the MVP walk's box could never update (7125822972).
- **Decision:**
  - **What stays the installed box's.** `tools/apply_update.sh` itself, the verifier (`tools/verify_update.py`), the
    vendor key and the start guard. A bundle never vouches for itself. The vendor key is the installed key file alone
    (`deploy/keys`, or `deploy/updates/trust.json`): a file of its own, root's or the running user's. Whether the
    verifier runs in the box's image, and which image, are the box's `deploy/.env`'s. A caller's `TB_VENDOR_PUBKEY`,
    `TB_VERIFY_IN_DOCKER` and `TB_PY_IMAGE` are unset unread.
  - **What runs from the bundle.** The checked host tree is unpacked into the update's own 0700 stage, fsynced
    before it is named. Its `deploy/` is one link to the box's own, so the box's settings, keys and records are used.
    That tree's `tools.trialbox update` then runs the preflight, backup, rollback point, apply, migrate, check and
    automatic rollback. The output and the audit events `update.applied` and `update.rolled_back` (`update_code`)
    name the code that ran; the update decides that from where its own file is.
  - **A bundle without a host tree.** PRODUCTION refuses it, saying why and what to do. A PoC box warns, lists it and
    runs the installed code. A signed model pack (H-95) runs the installed code on every box and says why. The
    installed verifier refuses a model pack holding a host tree, code, a script or pickle weights.
  - **Space.** The verifier's space to stage counts the host tree twice (the tar and its unpacked copy), against the
    file system that holds TMPDIR. The load's peak bound allows twice the host tree, read from the signed manifest.
  - **A passphrase box** updates in place, with `--kek-passphrase-file FILE` or `--kek-passphrase-stdin` (the
    installers' KEK-INPUT functions); the KEK is unsealed by a pipe before the key check.
  - **The lifecycle review's Highs** (lane LR), each reproduced at master:
    - LR-9: the box does not start while an update's marker stands.
    - LR-17: install.sh's load takes the next release on a loaded, never-started box.
    - LR-12: `close <bundle> --restored REASON` closes an update whose rollback failed, once the box's audit log
      holds the restore and the host tree is back.
- **Limit:** only a box whose installed `apply_update.sh` has this decision gains it. A box on an older release runs
  its own update code once more; the walk's box needs its bootstrap reinstall.
- **Not decided here:** the rehearsal that updates from release N-1 (H-123); the KEK file the services can read after
  `unseal` (LR-4, H-133); the restore naming an update's marker (H-129).
