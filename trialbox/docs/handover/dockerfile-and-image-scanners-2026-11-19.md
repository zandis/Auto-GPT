# hadolint on every Dockerfile, three configuration scans per image (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the integrator, the security owner. Findings for builders, so in
one language.

Plan 10 row 10G-41 (review 21 OT-3; plan 10 decision 115, ruled "ok"), decision D-1343. Findings in the register's
`--add-from` form: `dockerfile-and-image-scanners-2026-11-19/findings.json`.

## What existed

- hadolint 2.12.0 (the image by digest) in the CI `images` job of `trialbox-ci.yml`, gating at warning since D-206,
  on 3 Dockerfiles: `deploy/docker/python.Dockerfile`, `deploy/docker/jvm.Dockerfile`, `demo/Dockerfile`.
- `make ci` ran hadolint on 4 (the 3 and `deploy/docker/backup.Dockerfile`) when a hadolint binary was installed.
- Trivy 0.76.2 (pinned sha256, `tools/supply_chain/scanners.py`) ran only the vulnerability scanner, in the release
  gates (`make release-gates`, `trialbox-images.yml`). No secret or misconfiguration scanner, no Dockle.

## What changed

| Where | Change |
| --- | --- |
| `Makefile` | `DOCKERFILES` (all 8 under `trialbox/`), read by `make ci`'s hadolint line; `HADOLINT_IMAGE`; `IMAGE_SCAN_IMAGES` (each image of `SC_OWN_IMAGES` with its Dockerfile); target `image-scan` |
| `trialbox-ci.yml`, job `images` | the hadolint loop covers the same 8 Dockerfiles (gating at warning, as before) |
| `trialbox-images.yml`, job `images` | after the release gates: `make image-scan`, `continue-on-error`, its summary into the job summary and `build/image-scan` into the job's artifact |
| `tools/supply_chain/image_scan.py`, `image-scan` command | per image: hadolint (JSON) on its Dockerfile, Trivy `--scanners secret,misconfig` and `--image-config-scanners secret,misconfig` (embedded checks, `--skip-check-update`), Dockle; `trivy config` on `deploy/docker` and `demo`; reports, `index.json`, `summary.md`; exit 0 unless `--fail-at HIGH` |
| `tools/supply_chain/scanners.py` | Dockle 0.4.15, the release archives for amd64 and arm64 with the published sha256 (both archives fetched and checked here); `make scanners` fetches it with Syft and Trivy |
| Dockerfiles | comments only, except `--no-cache-dir` in `embed.Dockerfile` (the base already sets `PIP_NO_CACHE_DIR=1`): ignores with reasons in `db.Dockerfile`, `backup.Dockerfile`, `tools/rehearse_box/host.Dockerfile`; the misplaced SC2086 pragma of `embed.Dockerfile` moved onto its RUN |
| `tests/unit/test_image_config_scans.py` | the tree, the Makefile list and the CI loop are one set; every pragma sits on an instruction; every own image scanned from its Dockerfile; the images job's step report-only and kept; Dockle pinned; D-1343's dated line; the parsing, summary and `--fail-at HIGH` on fixtures |

Report-only until **2026-12-17** (D-1343, "Gating from:"), then the scan fails the job on a Trivy secret or
misconfiguration finding of HIGH or CRITICAL. The switch is a pull request (H10G41-07).

## hadolint rules expected, by rule (read from the files, not run)

| Rule | Level | Where | Done |
| --- | --- | --- | --- |
| DL3008 | warning | `db.Dockerfile:53` (ca-certificates), `host.Dockerfile:27` | ignore with reason (H10G41-01, -03) |
| DL4006 | warning | `db.Dockerfile:43`, `backup.Dockerfile:40, 48, 49` | ignore with reason (H10G41-02) |
| SC2046 | warning | `backup.Dockerfile:48` | ignore with reason, on purpose (H10G41-04) |
| DL3006 | warning | `db.Dockerfile:23` | ignore with reason, digest via ARG (H10G41-04) |
| DL3042 | warning | `embed.Dockerfile:26` | fixed: `--no-cache-dir` (H10G41-05) |
| SC2086 | info | `embed.Dockerfile:26` | the existing pragma moved onto the RUN (H10G41-05) |

`deploy/redcap-test/Dockerfile` (lane E's, never built here) is read as passing; it was not changed.

## What was and was not run

- Run: the card's unit tests; the YAML parse of both workflows; `make -n image-scan`; the repository checks
  listed in the pull request.
- **Not run:** hadolint (fetching and running its binary was refused in this session), Trivy's secret and
  misconfiguration scanners and Dockle (no Docker daemon, no images). The workflows have not run. The first
  hadolint run on the five newly linted Dockerfiles is the pull request's own CI `images` job, which gates: a rule
  not read here turns it red and is triaged there (H10G41-06).
