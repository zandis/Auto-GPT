# D-833 install.sh run again with the installed bundle continues

- **Task:** I-2 of the independent examination of the bundle and installer path (2026-11-15, #639)
- **PR:** this branch (`agent/I-2-a-rerun-of-the-installed-bundle-continues`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-210 (anti-rollback), D-367 (the second run from the signed tree)

## Decision

1. `tools/verify_update.py` takes the very bundle that is installed (same `release_seq`, same manifest sha256 as
   `installed.json`) as a repeat: no refusal, no downgrade, `repeat: true` in the summary. `main_apply` already
   answers it "already installed; nothing to do", so install.sh run again goes on from where it stopped. Before, any
   re-run after the first load died with "release_seq 1 is not above the installed 1", although install.sh says
   "Re-running is safe" and advises a re-run.
2. Another bundle under the same `release_seq`, an older one, or a key rotation bundle is refused as before; an
   older one still needs `--allow-downgrade REASON`.

## Test

`tests/unit/test_install_rerun.py`, through `apply_update.sh --dry-run` on a root of its own as well as `verify`:
before, the repeat cases failed with the reviewers' message; after, all pass.
