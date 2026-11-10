# D-340 Release identity and bundle gates

- **Task:** T-110b (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-110b-release-bundle`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** CR-046, CR-081, OPS-017, OPS-018 (bundle side); ENG-007, ENG-013, ENG-014, ENG-024 (CI helper images);
  ENG-015 in part (OCI labels, the image digest in `release.json`)

## Context

`tools/make_bundle.sh --gates` was optional: without it a bundle was built with a warning (CR-046, OPS-018). Nothing
named a release: every image was `1.0.0`, there was no `release.json`, no tag rule and no changelog (CR-081), although
`verify_update.py` (T-111, D-210) already refuses a bundle with images and no `release.json` agreeing with
`images.lock`. The default image list dropped `trialbox-postgres` (T-104) and carried the test mail servers (OPS-017).
The image vulnerability gate ran in report mode for every third-party image (ENG-007). The translator jars, FHIR
packages and fonts were downloaded without a pinned sum (ENG-013). CI tested on Java 21 by a literal in five places
(ENG-014). CI pulled three helper containers by tag (ENG-024).

## Decision

1. **The version has one place**, `[project] version` in `pyproject.toml`. `python -m tools.release version` prints it,
   `python -m tools.release tag` prints the tag `trialbox-v<version>` (the pattern the image workflow runs on).
   `make images` labels every image with the version and commit (`org.opencontainers.image.*`) and passes the commit
   to `trialbox-py` as `TB_REVISION`. `CHANGELOG.md` holds what changed per version. Image tags stay `1.0.0` for now.
2. **No bundle without its checks.** `make_bundle.sh` exits 2 without `--gates` or `--release-seq`; it keeps the
   `bundle-check` of local image ids, and `tools/release.py build` applies the same rule again to the config digest
   inside each saved archive (the image the box will load). An image not in a passing record of at most seven days,
   or one that passed only in report mode, stops the build before anything is signed.
3. **`release.json`** (`schemas/release.schema.json`, format `trialbox-release/1`) is written by `tools/release.py`
   from the bundle's own files: version, release id and sequence, source commit (and whether the tree had changes)
   and tag, the gate record's sha256, every image (tag in the archive, config digest, source reference, platform,
   archive, SBOM and its sha256) and every payload file with its sha256 and size. The release's `images.lock` is
   `deploy/images.lock` with each digest filled, plus every other image of the bundle, so `verify_update.py` finds the
   two agreeing. The image SBOMs, the lock SBOM, the licence report, the SBOM index and the gate record ride inside
   the signed bundle under `sbom/`, with `NOTICE` (the third-party notices; no separate `THIRD_PARTY_NOTICES.md`) and
   `CHANGELOG.md`. After signing, `tools/release.py check` re-reads the bundle and fails when a payload file is not
   named, a sum differs, or an image archive or its SBOM is missing; the bundle is then removed.
4. **What a bundle carries.** By default every image of `deploy/docker-compose.yml` under the profiles `stub` and
   `gpu`: `trialbox-py`, `trialbox-jvm`, `trialbox-postgres`, HAPI FHIR and vLLM. Never the test file's mail servers.
   `trialbox-postgres` joins the images the gates scan (`SC_OWN_IMAGES`).
5. **The image gate blocks for every image a bundle can carry.** Report mode is left for MailHog and GreenMail only
   (test only, never in a bundle). An allow-list vulnerability entry may name an `image:` repository and then
   accepts the finding in that image only. The 52 open findings of HAPI FHIR and vLLM of 2026-11-10 are such entries,
   each dated `review_by: 2026-12-10`; a new finding blocks.
6. **Build downloads are pinned.** Maven runs with strict checksums and the copied jars must match
   `tools/jvm-deps.sha256` exactly (no missing, extra or changed jar, cached or fresh); FHIR package tarballs must
   match `tools/fhir-packages.sha256`; the fonts come from one google/fonts commit and must match their sums.
7. **One Java version**, in `trialbox/.java-version`. Every `setup-java` step reads it (`java-version-file`); a unit
   test fails when the JRE image's major version differs or a workflow names a version of its own.
8. **CI helper containers by digest**: actionlint, hadolint and the Python echo server of the identity smoke test.

## Not done here

- The vLLM image is still referenced by tag in the compose files (CR-044); the bundle records its digest.
- `apt-get upgrade` stays in `python.Dockerfile` until the base digest moves with a gate run (ENG-015 rest).
- The identity images (Caddy, Authelia) are not in the default bundle list; the identity profile's bundle is T-631's.
- No tag is pushed by a tool; the tag is made by hand from `make release-tag` when a release is cut.

## Consequences

`make release-bundle BUNDLE_ARGS="--key ... --id ... --release-seq N --out ..."` is the one way to a bundle. The
image workflow fails on any new HAPI or vLLM finding, and on all of them after 2026-12-10 unless the images move. A
pom change regenerates `tools/jvm-deps.sha256` in the same pull request.
