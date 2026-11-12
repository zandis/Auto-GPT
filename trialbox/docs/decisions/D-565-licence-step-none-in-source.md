# D-565 The qualification's licence step for weights whose source has no licence file

- **Task:** HW-004 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md`, wave 1, lane D; finding HW-004 of
  `docs/reviews/2026-11-12-deep-review/13-final-build-hardware-install.md`)
- **PR:** this branch (`agent/HW-004-licence-none-in-source`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-342 (the licence register; its note on the judge's repository is replaced here), D-392 (provenance
  of a build: `provenance.licence_file`, the chat template beside the weight folder), T-012b (the expected manifest:
  the digest of every visible file of the weight folder), T-617b (the licence step reads the register)
- **Read by:** HW-003 and LLM-005 (the vendor qualification record), lane G (the first real qualification)

## Context

`qualify` failed a build whose weight folder holds no licence file. The judge's source repository has none
(`provenance.licence_file: none-in-source`), and the build's expected manifest is the digest of every visible file
of that source. D-342 told the operator to put the licence text into the weight folder before `qualify`. That
changes the manifest, and `pin_model` then refuses the folder. So the judge could pass the pin or the licence step,
never both, and the first real qualification would have failed on step `licence` after the GPU hours were spent.

## Decision

1. **A build whose registry row says `provenance.licence_file: none-in-source` is checked against its register
   row, not against a file in the weight folder.** The row must be there, be `cleared` (the existing rule), name
   the build's revision in its `version` (exactly one full revision, the build's) and a source URL in its
   `evidence`. The step's detail says
   `file: none in source (register row)`. No weight folder is needed for this build's licence check.
2. **The licence text rides beside the weight folder, outside the manifest**, as the chat template does:
   `<models root>/licences/<weight folder's name>/LICENSE` (any of the step's licence file names). The bundle takes
   everything under the models root, so it ships. When the file is there the step records its path and sha256, and
   refuses a text that is not the one the register row checked (when the row holds a text hash). When it is not
   there the step passes and the detail says `text: null`: the register row is the evidence of the licence. The
   file answers the row's obligation "keep the licence text with the weights"; that it is in a release bundle is
   not checked by this step (open, named in the pull request).
3. **Every other build is checked as before**: a licence file in the weight folder, equal to the register's text
   when the row holds its hash. A build whose row names a licence file (`{path, sha256}`) and whose folder has
   none still fails.
4. The register row's note and D-342's instruction ("the operator puts the Apache 2.0 text in the weight folder")
   are replaced by "beside the weight folder".

5. **The layout.** "Beside" means the flat `<models root>/<folder>` layout of `deploy/models`. The folder given is
   resolved first (a link's own name is not used). When the folder is a model cache's snapshot
   (`.../snapshots/<revision>`), the text is not looked for: a `licences` folder there would be read as a snapshot
   by `tools/serving_config.py`. An empty text file is refused.

## Consequences

- The judge passes both the pin and the licence step with the publisher's folder unchanged.
- Two assertions of `tests/unit/test_qualify.py` described the old rule for the judge (a failure for the missing
  file). They now hold the same failure for the verifier, whose row names a licence file, and the new rule for the
  judge.
- No setting, no limit, no new store.
