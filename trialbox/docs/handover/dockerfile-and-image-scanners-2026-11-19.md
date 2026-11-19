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
| `Makefile` | `HADOLINT_GATING` (the 3 the CI job gates on, unchanged) and `HADOLINT_REPORT` (the other 5); target `hadolint-report` (report-only, exit 0); `HADOLINT_IMAGE`; `IMAGE_SCAN_IMAGES` (each image of `SC_OWN_IMAGES` with its Dockerfile); target `image-scan`; `make ci`'s hadolint line unchanged |
| `trialbox-ci.yml`, job `images` | the gating loop unchanged (3 files); a next step `make hadolint-report` on the other 5, `continue-on-error`, into the job summary and the `hadolint-report` artifact |
| `trialbox-images.yml`, job `images` | after the release gates: `make image-scan`, `continue-on-error`, its summary into the job summary and `build/image-scan` into the job's artifact |
| `tools/supply_chain/image_scan.py`, `image-scan` command | per image: hadolint (JSON) on its Dockerfile, Trivy `--scanners secret,misconfig` and `--image-config-scanners secret,misconfig` (embedded checks, `--skip-check-update`), Dockle; `trivy config` on `deploy/docker` and `demo`; reports, `index.json`, `summary.md`; exit 0 unless `--fail-at HIGH` |
| `tools/supply_chain/scanners.py` | Dockle 0.4.15, the release archives for amd64 and arm64 with the published sha256 (both archives fetched and checked here); `make scanners` fetches it with Syft and Trivy |
| Dockerfiles | only `embed.Dockerfile` (report-only, not one of the 3 gating files): `--no-cache-dir` (the base already sets `PIP_NO_CACHE_DIR=1`), and its SC2086 pragma, already on master, moved onto its RUN. No hadolint ignore is added anywhere (the owner's rule: no scan allow-list entry); `db`, `backup` and `tools/rehearse_box/host.Dockerfile` are as on master |
| `tests/unit/test_image_config_scans.py` | the tree is the gating 3 and the report-only 5; the CI loop is the 3 and the report step cannot fail; no ignore beyond master's; every pragma sits on an instruction; every own image scanned from its Dockerfile; the images job's step report-only and kept; Dockle pinned; D-1343's dated line; the parsing, summary and `--fail-at HIGH` on fixtures |

The five newly linted Dockerfiles are report-only from **2026-11-19** until their findings (H10G41-01 to -04) are
closed (D-1343, "hadolint report-only from:"). The image scan is report-only until **2026-12-17** (D-1343, "Gating
from:"), then it fails the job on a Trivy secret or misconfiguration finding of HIGH or CRITICAL. Each switch is a
pull request (H10G41-07).

## hadolint rules expected, by rule (read from the files, not run)

| Rule | Level | Where | State |
| --- | --- | --- | --- |
| DL3008 | warning | `deploy/docker/db.Dockerfile:46` (ca-certificates), `tools/rehearse_box/host.Dockerfile:24` | open (H10G41-01, -03) |
| DL4006 | warning | `deploy/docker/db.Dockerfile:36, 38, 39, 61`, `deploy/docker/backup.Dockerfile:36, 44, 45` | open (H10G41-02) |
| SC2046 | warning | `deploy/docker/backup.Dockerfile:44` | open (H10G41-04) |
| DL3006 | warning | `deploy/docker/db.Dockerfile:21` | open (H10G41-04) |
| DL3042 | warning | `deploy/docker/embed.Dockerfile:26` | fixed: `--no-cache-dir` (H10G41-05) |
| SC2086 | info | `deploy/docker/embed.Dockerfile:26` | the pragma already on master moved onto the RUN (H10G41-05) |

No ignore was added for any of them; their files are linted report-only. `deploy/redcap-test/Dockerfile` (lane E's,
never built here) is read as passing and was not changed.

## What was and was not run

- Run: the card's unit tests; the YAML parse of both workflows; `make -n image-scan`; the repository checks
  listed in the pull request.
- **Not run:** hadolint (fetching and running its binary was refused in this session), Trivy's secret and
  misconfiguration scanners and Dockle (no Docker daemon, no images). The workflows have not run. The first
  hadolint run on the five newly linted Dockerfiles is the CI `images` job's report-only step; a rule not read here
  shows there and becomes a finding (H10G41-06).
