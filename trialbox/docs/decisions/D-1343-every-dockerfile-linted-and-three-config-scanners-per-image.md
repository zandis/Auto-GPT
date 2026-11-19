# D-1343 Every Dockerfile is linted, and each image gets three configuration scans (10G-41)

- **Task:** lane H, card 10G-41 (plan 10 track G; review 21 OT-3; decision 115 of plan 10, ruled "ok"). · **Date:** 2026-11-19
- **Decision:**
  - **hadolint on every Dockerfile under `trialbox/`**, eight today: `deploy/docker/{python,backup,jvm,embed,db}.Dockerfile`,
    `demo/Dockerfile`, `deploy/redcap-test/Dockerfile`, `tools/rehearse_box/host.Dockerfile` (the review counted 6:
    the six images; the REDCap test server and the rehearsal host are linted too). One list, the Makefile's
    `DOCKERFILES`, read by `make ci`; the CI `images` job (trialbox-ci.yml) loops over the same eight. It gates at
    `warning`, as since D-206, with the same hadolint 2.12.0 image by digest. A rule a Dockerfile breaks on purpose
    is an inline `# hadolint ignore=` directly above the instruction with its reason in the comment above it (the
    form of D-206); each new one is also a finding (`docs/handover/dockerfile-and-image-scanners-2026-11-19.md`).
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
- **Gating from:** 2026-12-17
  - From that date the `images` job runs `make image-scan IMAGE_SCAN_ARGS="--fail-at HIGH"` without
    `continue-on-error`: a Trivy secret or misconfiguration finding of HIGH or CRITICAL on any of our images, or a
    Trivy scan that did not run, fails the job. Each finding is fixed, or accepted in a ledger entry of the
    allow-list form (reason, owner, review date within 90 days; review 21 §5.2) by a decision, never by an ignore
    file. Dockle stays report-only in CI (its FATAL blocks at the release checklist, review 21 §5.2); hadolint
    already gates. The switch is a pull request by lane H on or after the date; nothing turns it on by itself.
- **Not proved here:** no Docker daemon where this was made. hadolint, Trivy and Dockle were not run on any
  Dockerfile or image; the ignores added are the rules read from the files, and the CI `images` job of the pull
  request is the first hadolint run on the five newly linted files. The workflow has not run: shown are the YAML
  parse of both workflows and the tests below.
- **Held by:** `tests/unit/test_image_config_scans.py` (the eight Dockerfiles in the tree, the Makefile list and the
  CI loop are one set; every image of `SC_OWN_IMAGES` is scanned from its Dockerfile; the images job runs the
  scan report-only after the release gates and keeps its folder; Dockle pinned for both platforms; this line's date
  exists; the summary and the `--fail-at HIGH` logic on fixtures).
