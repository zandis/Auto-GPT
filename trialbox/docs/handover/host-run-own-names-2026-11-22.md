# The host run's names, its driver check, and pglocal's start lock (card H-72, 2026-11-22)

**Reader:** the integrator and the people who build TrialBox

Lane H. Findings H72-01 to H72-03 ([findings JSON](host-run-own-names-2026-11-22.json)). The run sheet:
`docs/plan/measurements/48gb-measuring-run-2026-11-19.md` section 10.2.

## Pull request body (draft)

**H-72: the 48 GB host run's preflight refuses an installed box's images and a low driver; pglocal.ensure is locked
across processes.**

- `tools/measure48-host.sh` preflight: refused when any `trialbox-*` image is on the host (the stub, s05, builds and
  tags images of those names and would replace an installed box's); refused when the card's driver is below
  `deploy/images.lock`'s `gpu.driver_min` (580.65.06, the CUDA 13 engine image), with the found and the needed driver
  named. Two new refusals, two new tests, one fixture change (the rig's driver moves to 590.44.01; no assertion
  changes).
- `tools/pglocal.py`: `ensure()` holds an exclusive `flock` on `<root>/.ensure.lock` across its check and start; a
  running server is reused before the lock. A test releases six processes at once: one initdb, one start, one URL.
- **Not built (question to the integrator):** `--project <name>` and the run's own image tag. They need changes in
  files outside this card (below). Until then a host with an installed box is refused, not shared.
- **Not built:** a 96 GB option for the host form (below).

## What was asked

The integrator, 2026-11-20 08:18 UTC: the host form gets `--project <name>`, the stub's images take the run's own tag,
both refused when equal to `trialbox`, the preflight checks images, the same in a 96 GB host sheet. 07:32 UTC: the
preflight checks the host's driver against what the engine image's CUDA needs. 15:07 UTC: the `tools/pglocal.ensure`
start race, a cross-process lock.

## Part A: what was built

| Check | Before | Now |
| --- | --- | --- |
| the box's images (`trialbox-*`) on the host | not checked; s05 would build over them | refused, the images named |
| the driver against the engine image | read and recorded, a note when not on the 580 branch, "no minimum is set" | `tools/images_lock.py host --driver <read>`: refused below `gpu.driver_min`; the found and the needed driver named; the 580-branch note kept |

The minimum is on master already: `deploy/images.lock` `third_party.vllm.gpu.driver_min` = 580.65.06 (CUDA 13.0.2;
the lock's note: "the host driver must be R580 or newer"), which `deploy/check_host.sh` and `deploy/install.sh` use
through the same tool. The engine image of the run (`tools/engine_probe.py` `pinned_ref`) is that same lock entry. The
existing host's 575 driver is now refused at the preflight (H72-02).

`LINE_S` (the card's item 5) is not removed: shellcheck calls it unused because it does not follow the sourced file,
but `gate()` in `tools/measure48-vm.sh` reads it (`--line-s "$LINE_S"`); removing it would make every stage gate
without a stop line. shellcheck's warnings on the script are the same eleven SC2034 as on master, all of this kind.

## Part A: what was not built, and why

`--project <name>` and the run's own image tag cannot be built in `tools/measure48-host.sh` alone. The names are fixed
in files other lanes own (and in the VM script the host form sources):

- `deploy/docker-compose.yml`: `name: trialbox`; the networks have fixed names (`trialbox-net`, `trialbox-model-net`,
  `trialbox-model-backend`, `trialbox-egress`, `trialbox-console`), which `COMPOSE_PROJECT_NAME` does not change. The
  images do follow variables (`TB_IMAGE`, `TB_JVM_IMAGE`, `TB_EMBED_IMAGE`, `POSTGRES_IMAGE`).
- `deploy/poc.sh`: builds with a fixed tag (`docker build ... -t trialbox-py:1.0.0`); `IMAGE_DB=trialbox-postgres:16-1`
  takes no variable.
- `tools/dgpu48.py`: `PROJECT = "trialbox"` (its count of the servers by the compose label), `BACKEND_NET`, and the
  canary's and the pin tool's `trialbox-py:1.0.0`.
- `tools/measure48-vm.sh`: `trialbox-llm-service-1`, `trialbox-llm-verifier-1`, the canary's network and image.

A `--project` that changed only the host script's names would start the servers under one project while dgpu48 and the
screen look for them under `trialbox`: a run that fails at s08. So the safe part was built (the refusal above) and the
rest is a question.

## 96 GB

Not built. No form selects a 96 GB run: `tools/measure48-vm.sh`, `tools/measure48_vm.py` and
`deploy/gcp/measure48-run.sh` are the 48 GB run only (the ballast's `--target-mib 49140`, dgpu48's 48 GB ladder in s08,
`fetch_weights --profile rtxpro6000`). A 96 GB card needs no ballast, and its measurement is `tools/serving_config.py
capture` on the `rtxpro6000` profile's compose overlay, not dgpu48's ladder. That is a different s07 and s08, more than
an option: what is missing is a 96 GB step set (no ballast, the rtxpro6000 overlay pinned to the chosen card, the
capture) and a sheet for it.

## Part B: pglocal.ensure

Not fixed on master before this card. `ensure()` now checks for a running server first (no lock), then takes an
exclusive `flock` on `<root>/.ensure.lock` and checks again before any initdb or start. The kernel lets the lock go
when its holder dies. `_is_cluster_dir` knows the lock file, so `--gc` still recognises a cluster folder whose initdb
failed. `tests/unit/test_pglocal_ensure_lock_h72.py` fails with the lock taken out (checked once by hand).

## Not verified

Nothing ran on a real card, Docker daemon or host; everything is on stand-ins. The driver check is shown against the
lock's figure, not against a real 575 or 580 host.
