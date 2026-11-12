# D-469 The ruleset compiler never writes the source `rulesets/` folder

- **Task:** G1 bug B3 (`docs/plan/measurements/g1-2026-11-11/BUGS.md`)
- **PR:** this branch (`fix/g1-B3-compiler-never-writes-source-rulesets`)
- **Date:** 2026-11-12
- **Status:** accepted (owner's order)

## Decision

1. **One default.** With no `TB_RULESETS_DIR`, `Env.rulesets_path` is `<TB_DATA_DIR>/rulesets`. It used to be the
   checkout's `rulesets/` in code, while the settings table declared `/data/rulesets`: the two now agree (on a box,
   `TB_DATA_DIR` is `/data`).
2. **The source folder is a seed, read-only to the product.** `tb_common.ruleset.SEED_RULESETS` is the shipped
   folder (`/app/rulesets` in the images). The criteria compiler's repository copies it into the working copy the
   first time that folder is empty (as before). The console and the orchestrator, which only read, call
   `seed_working_copy` once at start: it copies the shipped rulesets only into a folder that holds no ruleset, never
   touches one that holds any, and does nothing where the folder is not writable (the read-only mounts).
3. **Where the line is.** Product services (console, orchestrator, criteria compiler, `criteria_compiler.import_ruleset`,
   all through `rulesets_path`) never write the source folder. The developer tools `tools.build_rulesets
   --check/--recompile`, `tools.build_scenario_ruleset` and `tools.goldens` regenerate the committed rulesets on
   purpose and keep writing the source tree, by naming it explicitly (`--out`, default `rulesets/`). Tests copy the
   folder (`tests.rulesets_guard.copy_rulesets`); the guard in `tests/conftest.py` still fails any test that changes it.
4. **Boxes keep their rulesets.** Every compose file and platform manifest already sets
   `TB_RULESETS_DIR=/data/rulesets` for the three services, on the `rulesets-data` volume; an explicit value wins,
   so a box that holds compiled rulesets reads and writes the same volume after the update. Nothing is copied over
   an existing folder.

## Test

`tests/unit/test_g1_b3_rulesets_default.py`: the default is under the data folder; the declared and the code default
agree; a compile on the default folder leaves the checkout (every file, inode and time) as it was.
