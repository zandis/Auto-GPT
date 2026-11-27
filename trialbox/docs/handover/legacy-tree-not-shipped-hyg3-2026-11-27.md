# HYG3: the top-level legacy tree is not in the release build or its SBOM inputs

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** hygiene item 3 of the open-tool audit (integrator, comment 7211450855 on #1504): exclude the top-level
  legacy code from the release build and the SBOM inputs; a test that no shipped image contains it; delete nothing
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Change:** one guard test, `tests/unit/test_legacy_tree_not_shipped.py`; no build file changed
- **Findings:** [`legacy-tree-not-shipped-hyg3-2026-11-27/findings.json`](legacy-tree-not-shipped-hyg3-2026-11-27/findings.json)
  (HYG3-01 to HYG3-03)

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

## Review round (#1583, R1 to R6, after one design consult)

Consult decision: every recognised build line yields one verified, resolved context; an unresolved one fails. Named
contexts, `--from` sources, the release closure and the `SC_IMAGES` assignments are all read. Test file only; no
Makefile, Dockerfile or compose change.

- Every parser takes text, so each regression case feeds a planted string.
- R1: `COPY`/`ADD --from` and `RUN --mount from=` must name a stage of the file (or a stage index);
  `--build-context name=value` and compose `build.additional_contexts` (list or mapping) must resolve inside
  `trialbox/` unless the value is a URL.
- R2: each build's context is resolved from the folder the line runs in, moved by each `cd`; a `cd` to a non-literal,
  a `-` context or a URL context fails.
- R3: a make reference stays one word; the context is the one literal positional; any other bare make variable must be
  one of `PLATFORM_ARG`, `BUILD_ARGS`, `CA_SECRET`, `OCI_LABELS`, `NO_CACHE_ARG`, each asserted to hold flags and
  their values only, with no `--build-context`. Recognised builds equal verified contexts on every recipe line.
- R4: the closure of `make release-images` (prerequisites and `$(MAKE)` goals) is walked: the targets with a build
  recipe are exactly `images` and `demo-bundle`, and the only script it calls that builds is
  `deploy/build_db_image.sh`. `images-multiarch` is read too.
- R5: `SC_IMAGES` and `SC_OWN_IMAGES` have one `?=` assignment each; `SC_IMAGES` reads as it does today and
  `SC_OWN_IMAGES` is the tags of the release builds and the database script's tag. Make is not run.
- R6: the `trialbox`-prefix assertion is gone; a top-level `trialbox-notes.md` is legacy like any other name.

Not covered: an environment override of a `?=` variable (`SC_IMAGES`, `SC_OWN_IMAGES`) at release time (HYG3-03).

Each case planted in the work tree and reverted, old guard (d599b8aa) against the new one: P1 `COPY --from=legacy`,
P2 `--build-context legacy=..`, P3 compose `additional_contexts: [legacy=../..]`, P4 `cd .. && docker build .`,
P5 `docker build -f Dockerfile $(IMAGE_CONTEXT)` beside the good builds, P6 `release-images: extra-image` with a
build of `..`, P7 `SC_IMAGES += dir:../legacy`: the old guard passed each (10 passed), the new one failed each. P8 a
tracked top-level `trialbox-notes.md`: the old guard failed on it, the new one passes.
