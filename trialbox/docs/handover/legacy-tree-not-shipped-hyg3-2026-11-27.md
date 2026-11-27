# HYG3: the top-level legacy tree is not in the release build or its SBOM inputs

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** hygiene item 3 of the open-tool audit (integrator, comment 7211450855 on #1504): exclude the top-level
  legacy code from the release build and the SBOM inputs; a test that no shipped image contains it; delete nothing
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Change:** one guard test, `tests/unit/test_legacy_tree_not_shipped.py`; no build file changed
- **Findings:** [`legacy-tree-not-shipped-hyg3-2026-11-27/findings.json`](legacy-tree-not-shipped-hyg3-2026-11-27/findings.json)
  (HYG3-01 to HYG3-02)

## Files outside the card

None. The card's own: the test, this page and its findings.

## What was found first

The subject was already built. Every shipped image is built from a context inside `trialbox/`: `make images`,
`images-multiarch` and `demo-bundle` build from `.` or `deploy/docker` with `trialbox/` as the working folder,
`deploy/build_db_image.sh` changes to `trialbox/` first, every compose `build.context` resolves inside `trialbox/`,
and the CI image jobs run with `working-directory: trialbox`. A Docker context cannot reach above itself, so no file
of the legacy tree can enter an image. The SBOM inputs are the images of `SC_IMAGES` and the lock's SBOM, built from
`deploy/requirements.lock`; the licence report (`make licences`) reads only those SBOMs in `dist/sbom/`; the
bundle's host tree is packed with `--root` at `trialbox/`. The legacy tree stays in the repository and its history;
nothing was deleted.

## The test

It reads, and never builds: the build commands of the three release targets and their contexts, the database image
script, every compose file's build contexts, the `COPY`/`ADD` sources of every Dockerfile of
`RELEASE_DOCKERFILES`, the scanned image list against the Dockerfiles, the SBOM inputs of `lock-env`, `lock-sbom`,
`release-gates` and `licences`, and the root of the bundle's host tree.

## What ran

- The test on the base with only the test added: 10 passed, because the property already holds.
- To show it bites, three edits made by hand in the work tree and reverted: the `jvm` image's context set to `..`
  and a `COPY` from the parent folder added to `python.Dockerfile`: 2 failed (the `images` context case and the
  Dockerfile case); the top-level `requirements.txt` added to the `licences` inputs: 1 failed (the SBOM case).
- The checks of CLAUDE.md and the policy set: see the pull request.

## Not verified

- No image was built and no image's file list was read; the test reads the build inputs only.
- Commands outside the release targets (drills, the proof-of-concept script, cloud scripts) were not read by the
  test; they build no shipped image.
