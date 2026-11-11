# D-348 Third-party images: one digest list, a GPU host check, Mailpit

- **Task:** T-673, dependency batch 1, third-party images (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-673-images-lock`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** DEP-003, DEP-004, DEP-005, DEP-021, LLM-010; CR-045 (third-party part, with the open findings below)
- **Builds on:** D-204 (`deploy/images.lock` for the built db image), D-176 (images only from the bundle), D-186

## Context

The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/08-dependency-currency.md`,
`03-llm-serving-stack.md`) found: vLLM pulled by tag in four compose files (DEP-004, LLM-010); the Spark compose
file pinning a community vLLM build for the DGX Station, `sm_103a`, not the GB10 (DEP-003); no check that the host
driver can run a CUDA 13 image outside the GB10 profile (DEP-005); MailHog, abandoned since 2020, amd64 only and with
1,590 image findings, in the test profile (DEP-021).

## Decision

1. **One list.** `deploy/images.lock` gets a `third_party` section beside D-204's `images`: one entry per image the
   box pulls as published (vLLM, HAPI, Caddy, Authelia, GreenMail, Mailpit). Each entry has `image`
   (repository:tag), `digest` (the multi-arch index digest read from the registry), `platforms` (each platform's
   manifest digest) and `variables` (the compose variables that name it). The `images` section and its readers
   (release check, update path) are unchanged.
2. **No image by tag.** Every compose file writes a third-party image as `${VAR:-image@digest}`, equal to the lock.
   `tools/images_lock.py check-compose` checks it (stdlib only). `deploy/install.sh` runs it before
   `docker compose up` (a site's own `TB_COMPOSE_OVERRIDE` is not checked). A unit test reads every
   `deploy/docker-compose*.yml`; a compose test renders each overlay with `docker compose config --images`.
3. **vLLM** stays at `v0.32.0`, the release of the measured G1 run, now by index digest
   `sha256:befccf0e…5b34`. The lock records each platform's CUDA architectures (amd64: 7.5 to 12.0; arm64: 8.0 to
   12.0), the CUDA version 13.0.2 and the lowest driver, 580.65.06 (the image sets `NVIDIA_REQUIRE_CUDA=cuda>=13.0`
   and `VLLM_ENABLE_CUDA_COMPATIBILITY=0`). Moving this entry is a model change: requalify first.
4. **The Spark** runs the same official image (its arm64 manifest). Its `sm_120` code runs on the GB10's `sm_121`
   (same major, older minor). The community `eugr/spark-vllm` Station build is gone. To be confirmed on a Spark
   (T-214).
5. **The host check.** `deploy/check_host.sh` checks the host against the locked vLLM image when a GPU profile is
   given (`--gpu <profile>`, `--gb10`) or `TB_LLM_MODE=vllm` is set. It FAILs when the image has no build for the
   host's architecture, when the driver is below `driver_min`, or when no CUDA architecture of the build runs on the
   GPU's compute capability. A site that set its own vLLM image gets a WARN. `--gpu-only` runs only these checks.
   `install.sh` runs them in GPU mode before it loads the bundle and stops on a FAIL. The GB10 driver pin (exactly
   580.142) stays.
6. **Structured output.** No backend flag is set; vLLM's default, `auto`, serves structured output. The lock names
   it (`gpu.structured_outputs_backend`), and the serving record (`tools/serving_config.py capture`) records
   `structured_outputs_backend` (from the flag, or `auto`) and the image's registry digests (`image_digests`).
7. **Mailpit replaces MailHog** in the test profile: `axllent/mailpit:v1.33.1` by digest, amd64 and arm64. Same
   ports (SMTP 1025, web 8025). The service keeps the network alias `mailhog` and the port variable
   `TB_HOST_MAILHOG_PORT`, so an older `deploy/.env` still works. The e2e tests read Mailpit's API
   (`tests/stack.py outbound_mail`). Mailpit is not in report mode: its vulnerability gate blocks. `SC_AMD64_ONLY`
   is empty.
8. **GreenMail** moves from 2.1.3 to 2.1.15, by digest.

## Consequences

- A tag-only image, or a digest the lock does not hold, fails `make test` and stops an install.
- A GPU box on an R575 or older driver stops at install with a plain message, before anything is loaded.
- `tools/image_pins.py` now also resolves `VLLM_IMAGE` on the overlay2 image store (it is digest-pinned).
- Not in this decision: the release bundle refusing a lock mismatch (`tools/make_bundle.sh`, T-110b), the platform
  `release.json` vLLM digest (T-110b), the GCP run scripts that still name `vllm/vllm-openai:v0.32.0` by tag, a
  `b200` profile, and moving vLLM, HAPI or GreenMail out of report mode (their findings need a scan).
