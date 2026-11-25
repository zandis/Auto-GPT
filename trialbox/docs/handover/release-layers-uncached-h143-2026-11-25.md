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

- **Build the layer afresh on the release path only.** Both Dockerfiles declare `ARG UPGRADE_STAMP=` just before the
  upgrade step. A changed build argument misses the cache for every `RUN` after it. `make release-images` runs
  `make images demo-bundle` with `UPGRADE_STAMP` set to the build's own UTC time in nanoseconds, a value no cache
  holds. That reruns the upgrade layer of trialbox-py and the demo image, and so every image built on trialbox-py.
  `make images` and `make demo-bundle` alone pass no stamp, so dev builds keep their cache.
  `make release-bundle` now lists `release-images` before `release-gates`. Under that goal, `release-gates` also
  waits for `release-images`, so `-j` cannot scan before the build. Run alone, `release-gates` still scans what is
  on the host (CI's gate job builds fresh and is unchanged).
- **Record the fixed versions and refuse an older one.** `deploy/images.lock` gains `security_floors`. For
  trialbox-py, -backup, -jvm, -embed and -demo it gives the lowest libzstd1 (1.5.7+dfsg-1+deb13u1) and zlib1g
  (1:1.3.dfsg+really1.3.1-1+deb13u1). These are the versions the db image already pins and holds.
  `tools/supply_chain/floors.py` reads each image's SBOM (the Debian purls, with the epoch from its qualifier) and
  compares in dpkg's order. `release.run_gates` adds its refusals to the image's errors. A package below the floor,
  or missing, fails the image. A lock without floors fails the whole record (`floor_errors`). No caller can switch
  it off. Raise a floor when a newer fix is needed; never lower one.

## What was run

- `tests/unit/test_release_layers_uncached_h143.py`, 21 tests: on the branch, 21 passed.
  Copied onto master c3a5b2b2: it fails at collection (no `floors`). With only `floors.py` and the lock copied in,
  7 fail: the three gate tests, the dry-run build, the bundle order and the two Dockerfile checks.
  The gate tests use a stand-in SBOM and stand-in scanners.
- The image and lock tests and the policy set (the card's two greps, `.py` files only) and the touched files'
  tests: see the pull request for the counts as root and as an ordinary user under CI's conditions.
- `make lint`, `make guard`, `make cross-card`, and the CLAUDE.md checks: see the pull request.
- No shell script changed, so shellcheck had nothing to check.

## Not verified

- **No image was built here.** The session has no Docker daemon. So the real rebuild of the upgrade layer under
  `make release-images`, next to a dev build that reuses it, is not shown here. `make -n` shows the stamp on the
  trialbox-py and demo builds of the release path and on no build of `make images`. That the floors match what a
  fresh build installs is not shown here either. The bench's next release run and CI's image jobs show both.
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

Lane D's files, lane H's for this card under the integrator's ruling: `deploy/docker/python.Dockerfile`,
`deploy/images.lock`, `tools/supply_chain/release.py`, `tools/supply_chain/floors.py` (new). Also `demo/Dockerfile`
and the `images`, `demo-bundle`, `release-gates` and `release-bundle` lines of `Makefile`.

Findings: `release-layers-uncached-h143-2026-11-25/findings.json` (H143-01 to H143-03).
