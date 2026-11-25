# A release that builds its security-upgrade layers afresh (2026-11-25)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-143 (High) is item 1 of the integrator's 7158498985 on #639. The signed bundle at master c3a5b2b2 failed its
release gate on the bench host. Four images still held libzstd1 1.5.7+dfsg-1 (CVE-2026-124851): trialbox-py,
trialbox-backup, trialbox-jvm and trialbox-embed. CI builds fresh, so it passed.

## The fault

The four images get Debian's security fixes only through the unpinned `apt-get upgrade` of
`deploy/docker/python.Dockerfile` (D-23: no new package, no pin). Backup, jvm and embed are built `FROM trialbox-py`.
The demo image has the same step (`demo/Dockerfile`). Nothing in the step's text changes from day to day, so a
builder's cache keeps the layer from the day it was first built. `make release-bundle` did not build images at all.
It gated whatever images were on the host, and on the bench those came from an older cache. The gates then found
the old library, as they should, but nothing on the release path had built it afresh. Nothing held the package to the
fixed version either.

## The change

- **Build afresh on the release path only.** `make release-images` first pulls, by digest, every outside base that
  the six Dockerfiles pin. Those are the python, temurin, golang and postgres bases (one `docker pull` loop,
  `$(PLATFORM_ARG)` when given). It then runs `make images demo-bundle` with `--no-cache` on every build: py, backup,
  jvm, embed, db and demo. It does not pass `--pull`. The walk (the integrator's 7159322336) showed that
  `--no-cache --pull` together cannot work. `--pull` sends the `FROM trialbox-py` of backup, jvm and embed to a
  registry, which refuses it. `make images` and `make demo-bundle` alone add neither, so dev builds keep their cache.
  `make release-bundle` now lists `release-images` before `release-gates`. Under that goal, `release-gates` also
  waits for `release-images`, so `-j` cannot scan before the build. Run alone, `release-gates` still scans what is
  on the host. CI's gate job builds fresh and is unchanged.
- **Record the fixed versions and refuse an older one.** `deploy/images.lock` gains `security_floors`. For
  trialbox-py, -backup, -jvm, -embed and -demo it gives the lowest libzstd1 (1.5.7+dfsg-1+deb13u1) and zlib1g
  (1:1.3.dfsg+really1.3.1-1+deb13u1). These are the versions the db image already pins and holds.
  `tools/supply_chain/floors.py` reads each image's SBOM (the Debian purls, with the epoch from its qualifier) and
  compares in dpkg's order. `release.run_gates` adds its refusals to the image's errors. A package below the floor,
  or missing, fails the image. A lock without floors fails the whole record (`floor_errors`). No caller can switch
  it off. Raise a floor when a newer fix is needed; never lower one.

## What was run

- `tests/unit/test_release_layers_uncached_h143.py`, 20 tests: on the branch, 20 passed.
  Copied onto master c3a5b2b2, it fails at collection (no `floors`). With only `floors.py` and the lock copied in,
  5 fail: the three gate tests, the pull-then-build test and the bundle order. The dev-cache test passes on both, as
  it should. The pull-then-build test reads `make -n release-images`. It fails if the pull step goes, if it misses a
  digest-pinned base, if it comes after a build, if a build lacks `--no-cache`, or if a build has `--pull`.
  The gate tests use a stand-in SBOM and stand-in scanners.
- The image and lock tests, the policy set (the card's two greps, `.py` files only) and the touched files' tests:
  the counts are in the pull request, as root and as an ordinary user under CI's conditions.
- `make lint`, `make guard`, `make cross-card` and the CLAUDE.md checks: see the pull request.
- No shell script changed, so shellcheck had nothing to check.

## Not verified

- **No image was built here.** The session has no Docker daemon. So the real pull and the uncached rebuild under
  `make release-images`, next to a dev build that reuses its cache, are not shown here. `make -n` shows the pull, then
  `--no-cache` on all six release builds and on none of `make images`. The walk (7159322336) showed that an uncached
  build has the fixed libzstd1 in all four images and passes the gate. That the floors match what a fresh build
  installs is not shown here. The bench's next release run shows it.
- The floor check reads the SBOM's Debian components. An SBOM tool that wrote Debian packages in another form
  would read as "missing" and fail closed, not pass.

## The side item: the local secret-scan match

The report was a key-shaped match in `eval/bakeoff/results/2026-10-25/predictions_*.csv`, line 697, found locally
but not in CI. It does not reproduce on the committed files here. With the locked scanner, the scan of every tracked
file finds 6, all accepted. With every plugin on, those prediction files give 0 findings. The scan reads the working
tree, and `tools/bakeoff_live.py` writes `predictions_*.csv` into its `--out` folder. So a local re-run of the
bake-off into that dated folder, or a scanner from outside the lock, is the likely difference (H143-03,
hypothesis). On the bench, `git status` on that folder and the scanner's version would settle it. The ten prediction
files are tracked results of a public-data run. Whether they stay in the repository is the eval owner's call, not
this card's. Nothing was changed for it.

## Files outside the card

Lane D's files, lane H's for this card under the integrator's ruling: `deploy/images.lock`,
`tools/supply_chain/release.py`, `tools/supply_chain/floors.py` (new). Also the `images`, `demo-bundle`,
`release-gates` and `release-bundle` lines of `Makefile`, and its new `release-images`. No Dockerfile changed.

Findings: `release-layers-uncached-h143-2026-11-25/findings.json` (H143-01 to H143-03).
