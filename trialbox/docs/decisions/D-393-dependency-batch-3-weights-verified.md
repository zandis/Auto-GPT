# D-393 Dependency batch 3 and model weights verified beyond install

- **Task:** T-677, dependency batch 3, the patch window (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-677-dep-batch3-weights-verify`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** LLM-008, LLM-009 (the `/v1/models` part), DEP-020 (the HAPI part: checked, no newer image), DEP-025,
  DEP-026 (the record; the site's version is still to be read), DEP-028 (the monthly refresh)
- **Builds on:** D-348 (`deploy/images.lock`), D-142 and T-012b (site pins, the expected weights), D-177 (the model
  key), D-377 (systemd units)

## Context

The weights were hashed against their pins only at install (`pin_model --verify-all` in `install.sh`). The vLLM
containers re-read the disk at every restart, and nothing checked again: not the gateway, not `doctor`, not an update
(LLM-008). The gateway's served-model echo check cannot see wrong weights, because vLLM copies the request's `model`
into its answer (LLM-009). The monthly lock refresh, the image digests, axe-core and Playwright, and the sites' REDCap
versions were due in the same patch window (DEP-020, DEP-025, DEP-026, DEP-028).

## Decision

1. **`doctor --verify-all`.** A new `weights` check hashes every pinned build's weights against its pin
   (`pin_model.verify_all`, models folder `TB_MODELS_DIR`, default `deploy/models`). `--verify-all` adds it to the full
   doctor; `--weights` runs it alone. It is opt-in because it reads tens of GB.
2. **A flag the gateway reads.** A FAIL writes `weights_changed.json` beside the site pins (`deploy/site`, mounted
   read-only in the gateway at `/etc/trialbox/site`; `TB_WEIGHTS_FLAG` moves it). A pass removes it. While it exists
   the gateway refuses every model call `weights_changed` (HTTP 403, audited) and `/healthz` is unhealthy.
3. **When it runs.** Every night at 01:30 site time, before the scheduled runs, and ten minutes after boot
   (`trialbox-weights.timer`, `deploy/check_weights.sh`: the box's Python image with no network). In an update's
   check step, before the health wait, so a mismatch rolls the update back; a rollback runs it again to clear the
   flag. By hand: `trialbox doctor --verify-all`.
4. **`/v1/models` against the pin.** A gateway built from the environment asks each on-box server a pinned build is
   served on, before it serves the first call and then every hour (every 30 seconds while a server has not answered).
   The served name's `root` (vLLM's `--model` path) must be the pin's `weights.model_dir`, and `max_model_len` must not
   be below the build's `context_length`. A mismatch refuses every call `model_mismatch` until a later check passes. A
   server that does not answer yet is not a mismatch (vLLM loads for minutes). A `root` that is not an absolute path
   (the stub reports the served name) is not compared.
5. **The lock refresh.** `uv lock --upgrade` with the CI's uv (0.13.7), then `make lock`'s export. Ten packages moved,
   all minor or patch: annotated-doc, datamodel-code-generator, docling, docling-slim, faker, fastapi,
   markdown-it-py, pypdf, soupsieve, sqlglot. None was pinned back.
6. **Images.** Every third-party tag and the db base were read from Docker Hub on 2026-11-11. Every index digest
   equals the lock's, so none moved. HAPI `v8.12.0-2` is still the newest 8.x image. `images.lock` records the check
   (`checked`). vLLM stays at v0.32.0: moving it is a model change.
7. **Browser test tools.** axe-core moves from 4.10.2 to 4.14.0. The npm tarball's sha512 was checked against the
   registry. The vendored file's sha256 is recorded in `tools/package.json`, with Playwright 1.63.0, and
   `tools/package-lock.json` holds both with their integrity hashes. CI installs from that lock with `npm ci`. The walk
   always injects the vendored file, never a copy from `node_modules`.
8. **REDCap.** The connector's majors are now described as accepted, not tested. RUNBOOK §6 has a table of each
   site's REDCap version (`content=version`), to fill in before go-live.

## Consequences

- A swapped or edited weight file stops model calls at the next timer run, update or doctor run, instead of being
  served until the next install. A server started on another folder, or with a shorter context than the pin, is
  refused at gateway start.
- The flag lives in the site folder. A site that moves `TB_SITE_DIR` still works: `check_weights.sh` mounts that
  folder.
- `tests/unit/test_weights_verified.py` shows a swapped weight file refused at start, a `/v1/models` mismatch refused
  by the gateway, the timer and the update order, and the browser lock.

## Remains

- Reading each site's REDCap version, and one test against a REDCap sandbox (DEP-026).
- The hourly re-check finds a change in what is served. It does not re-hash weights; that is the nightly timer's job.
- The model guard reporting the manifest hash of the folder it fronts (LLM-009, longer term).
