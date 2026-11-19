# D-1343 Every Dockerfile is linted, and each image gets three configuration scans (10G-41)

- **Task:** lane H, card 10G-41 (plan 10 track G; review 21 OT-3; decision 115 of plan 10, ruled "ok"). · **Date:** 2026-11-19
- **Decision:**
  - **hadolint on every Dockerfile under `trialbox/`**, eight today (the review counted 6: the six images; the
    REDCap test server and the rehearsal host are linted too). The three that gate today keep gating exactly as on
    master: `deploy/docker/python.Dockerfile`, `deploy/docker/jvm.Dockerfile` and `demo/Dockerfile` in the CI
    `images` job at `warning` (D-206), hadolint 2.12.0 by digest; `make ci`'s line is unchanged. The other five,
    `deploy/docker/{backup,embed,db}.Dockerfile`, `deploy/redcap-test/Dockerfile` and
    `tools/rehearse_box/host.Dockerfile` (the Makefile's `HADOLINT_REPORT`), are linted **report-only** by `make
    hadolint-report` in the same job's next step: findings in the job summary and the `hadolint-report` artifact,
    never a failure of the job or of `make ci`.
  - **No hadolint ignore is added** (the owner's rule: no scan allow-list entry). Each rule a newly linted file
    breaks is an open finding with its file and line (`docs/handover/dockerfile-and-image-scanners-2026-11-19.md`)
    until it is fixed in the Dockerfile; an ignore already on master may be moved onto its instruction, not added.
  - **Three tools per image** in the image gates' `images` job (trialbox-images.yml), on each image of
    `SC_OWN_IMAGES` (py, backup, jvm, embed, postgres, demo), after the release gates: hadolint on the Dockerfile
    it was built from (JSON); Trivy `--scanners secret,misconfig` on the image and `--image-config-scanners
    secret,misconfig` on its configuration, with the checks bundle embedded in the pinned binary
    (`--skip-check-update`); Dockle (CIS Docker image checks). And `trivy config` over `deploy/docker` and `demo`.
    `make image-scan` (`python -m tools.supply_chain image-scan`) writes each report as JSON, `index.json` and
    `summary.md` to `build/image-scan`; the summary goes to the job summary and the folder into the job's
    artifact with the gate record (90 days).
  - **Pinned as the other scanners are:** Trivy 0.76.2 as today; Dockle 0.4.15 as its release archive with the
    sha256 the project publishes for amd64 and arm64 (`tools/supply_chain/scanners.py`, fetched by `make scanners`;
    an archive whose sum differs is refused). No install script, no `latest`; every action stays pinned to a commit.
  - **Report-only for four weeks.** The step is `continue-on-error` and the command exits 0 whatever it finds; a
    tool that fails is written into the summary. It cannot turn a train red. Third-party images (HAPI FHIR, vLLM,
    the mail servers) are not given these three tools: their configuration is not ours to change; the
    vulnerability gate covers them as before.
- **hadolint report-only from:** 2026-11-19
  - The five files of `HADOLINT_REPORT` stay report-only until their findings (H10G41-01 to H10G41-04) are closed;
    each then moves to the gating loop by a pull request of lane H, never with an ignore.
- **Gating from:** 2026-12-17
  - From that date the `images` job runs `make image-scan IMAGE_SCAN_ARGS="--fail-at HIGH"` without
    `continue-on-error`: a Trivy secret or misconfiguration finding of HIGH or CRITICAL on any of our images, or a
    Trivy scan that did not run, fails the job. Each finding is fixed, or accepted in a ledger entry of the
    allow-list form (reason, owner, review date within 90 days; review 21 §5.2) by a decision, never by an ignore
    file. Dockle stays report-only in CI (its FATAL blocks at the release checklist, review 21 §5.2); hadolint
    gates on its three files as above. The switch is a pull request by lane H on or after the date; nothing turns it on by itself.
- **Not proved here:** no Docker daemon where this was made. hadolint, Trivy and Dockle were not run on any
  Dockerfile or image; the findings are the rules read from the files (basis hypothesis), and the CI `images` job's
  report step is the first hadolint run on the five newly linted files. The workflow has not run: shown are the YAML
  parse of both workflows and the tests below.
- **Held by:** `tests/unit/test_image_config_scans.py` (the eight Dockerfiles in the tree are the gating three and
  the report-only five; the CI loop is the three, the report step reads the five and cannot fail; no new ignore;
  every image of `SC_OWN_IMAGES` is scanned from its Dockerfile; the images job runs the scan report-only after the
  release gates and keeps its folder; Dockle pinned for both platforms; both dated lines exist; the summary and the
  `--fail-at HIGH` logic on fixtures).
