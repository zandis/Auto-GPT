# The bench host's driver exception, and the run's own project and image tag (card H-74, 2026-11-22)

**Reader:** the integrator and the people who build TrialBox

Lane H. Findings H74-01 to H74-04 ([findings JSON](host-run-bench-exception-2026-11-22.json)). Rides after H-72
([its page](host-run-own-names-2026-11-22.md)). The run sheet:
`docs/plan/measurements/48gb-measuring-run-2026-11-19.md` section 10.2.

## Pull request body (draft)

**H-74: the 48 GB host run may go on the bench host's 575 driver under a named, recorded bench exception; the run's
own project and image tag are not built (a question).**

- `tools/measure48-host.sh --bench-driver-exception forward-compat --engine-probe FILE`: an option only (no default,
  no environment variable). Below `deploy/images.lock` `gpu.driver_min` the preflight passes only when the engine
  probe's result (`tools/engine_probe.py`) passed with a forward-compatibility form of the pinned image
  (`pinned+compat` or `pinned+libs`), with the image's compatibility libraries seen inside, on this card's model, this
  driver and the lock's pinned image (`tools/measure48_vm.py bench-exception`). s08 then serves with that form
  (`ballast48 measure --engine FORM`). The preflight, `records/head.json`, `records/bench-exception.json`, `host.log`
  and `out/BENCH-EXCEPTION.txt` say "bench exception: driver <found> with the forward-compatibility path; not valid
  for an install", with the found driver and the minimum. Without the option, H-72's refusal is unchanged.
- `deploy/check_host.sh`, `deploy/install.sh` and `tools/images_lock.py` are unchanged; a test proves they have no
  such option (check_host.sh: "unknown option", images_lock: "unrecognized arguments", a 575 driver still FAIL).
- **Not built:** `--project` and the run's own image tag (H74-03): the database image's tag is fixed in
  `deploy/build_db_image.sh`, a file outside the ruling's four. A question to the integrator, below.

The bench host's commands (an existing host, an installed box, driver 575; card N; nothing else changes):

    cd <clean checkout>/trialbox
    # once, the engine probe on that card (the engine image already there is left in place)
    python3 tools/engine_probe.py run --only pinned,pinned+compat,pinned+libs --gpu-args '--gpus "device=N"' \
        --out ~/tb-engine-probe.json
    # reload the driver (or reboot) just before the run: the caution below
    tools/measure48-host.sh preflight --gpu-index N --run-dir <run folder> --weights-dir <weights folder> \
        --bench-driver-exception forward-compat --engine-probe ~/tb-engine-probe.json
    tools/measure48-host.sh run --gpu-index N --run-dir <run folder> --weights-dir <weights folder> \
        --bench-driver-exception forward-compat --engine-probe ~/tb-engine-probe.json

On a host with an installed box the preflight still refuses (H-72: the box's images and objects), until part B.

## Why a 575 driver is refused (for the owner)

The engine image is vLLM v0.32.0's CUDA 13.0.2 build; `deploy/images.lock` says its config holds
`NVIDIA_REQUIRE_CUDA=cuda>=13.0` and `VLLM_ENABLE_CUDA_COMPATIBILITY=0`, "so the host driver must be R580 or newer"
(580.65.06): on 575 the container toolkit refuses to create the container, or the engine's CUDA refuses the driver,
before a model loads (`tools/engine_probe.py`'s `REQUIRE` and `DRIVER`). Below 580 it can run only through the
image's forward-compatibility libraries (`/usr/local/cuda/compat`), which root review 24 (from NVIDIA's pages) says
work on select data-centre and professional cards only; the tree has no run on a 575 driver, so only the probe on the
bench card can tell.

## Part A: what was built

| Where | What |
| --- | --- |
| `tools/measure48-host.sh` | `--bench-driver-exception forward-compat` and `--engine-probe FILE` (either alone is a usage error); in the preflight's driver check, below the minimum: the exception's check, or H-72's refusal as before; the option with a driver at or above the minimum is refused; the records and `out/BENCH-EXCEPTION.txt` |
| `tools/measure48_vm.py` | `bench_exception()` and `bench-exception`: the minimum read from `deploy/images.lock`; the probe's schema, verdict (`pass` with `pinned+compat` or `pinned+libs`, the pinned engine), the passing form's compatibility libraries, its driver, its card model and its pinned reference (digest matching); `records/bench-exception.json` on the allow-list |
| `tools/measure48-vm.sh` | s08 and s13 pass `${ENGINE[@]}` to `ballast48 measure` (unset on the VM: its command lines are unchanged) |
| `tests/unit/test_measure48_host_bench_h74.py` | 19 tests: the run under the exception and its words in every record; the refusal without the option (also with look-alike variables set); seven probes that do not grant it; the option where none is needed; its usage; the helper; the install path has no exception |

**G1b's record (H74-01).** The order names it as the mechanism. It is not in the tree: G1b has not run
(`docs/plan/measurements/b200-g1b/G1b.md`, "Status: not run"), and nothing in the tree records the engine image on a
575 driver. The tree's one mechanism for a driver below the image's need is the engine probe's two forms of the pinned
image, which `tools/dgpu48.py` already serves (`engine_from_probe`, `--engine`); the exception uses exactly those and
invents nothing.

**The run may still not start at s08 (H74-02).** `ballast48 measure --engine FORM` takes dgpu48's fixed environment
for the form, not the probe's; the probe's forms also set `NVIDIA_DISABLE_REQUIRE=1`, which s08 does not. Whether the
toolkit creates the container on 575 without it is unproven; the preflight says so. A question to lane J.

**Caution (H74-04), in the sheet and the preflight.** The server's session reported (2026-11-22, not measured here):
the forward-compatibility path on driver 575 leaks driver memory per CUDA context; after many starts the card refuses
new contexts; a driver reload fixes it. The run starts one context for the ballast (held to the end) and two servers
for each ladder option tried (up to three), stage O's verifier and s13's option: about 6 to 10 server starts. That is
not "many", but a leak that grows over them gives each later option less free memory than the first had: a later
option could fail, or show a smaller cache, for the leak and not its settings. Reload the driver before the run, and
read a later option against the first's `free_at_peak_mib`.

## Part B: not built (H74-03)

The ruling (2026-11-22 04:31 UTC) allows bodies in four files. The run's own image tag needs two more:

- `deploy/build_db_image.sh`: the one build of the database image (card 24-2: "two callers, so the command cannot
  drift") ends `-t trialbox-postgres:16-1`, with no variable. `deploy/poc.sh` builds the database image only through
  it; an extra `-t` from poc.sh would tag both, and the fixed tag would be built over an installed box's.
- `make images` (the `Makefile`, poc.sh's first build path) tags `trialbox-py:1.0.0`, `trialbox-jvm:1.0.0`,
  `trialbox-embed:1.0.0`, `trialbox-backup:1.0.0` and the database image fixed. poc.sh could avoid it by its second
  path (the build commands in poc.sh, with `--build-arg BASE_IMAGE`), within the four files.
- `deploy/docker-compose.test.yml`, the stub's overlay: `name: trialbox-hostnet`.

Byte-identical defaults can be kept in all four files of the ruling (the project's networks by
`${…:-trialbox}-net`, the image tags by variables, `dgpu48.PROJECT` and `BACKEND_NET`, the VM script's container
names); `docker compose config` renders here without a daemon, so the comparison with master's render is possible.
But without the database image the run's own tag cannot be honoured, and relaxing H-72's image refusal would let s05
build over an installed box's database image. So nothing of part B was changed, and a host with an installed box stays
refused.

**question:** a go for `deploy/build_db_image.sh` (its tag from a variable, `trialbox-postgres:16-1` by default) and
`deploy/docker-compose.test.yml` (the host network's name from the project, `trialbox-hostnet` by default), bodies
only; then part B in the six files.

## Files outside the card

- `tools/measure48-vm.sh` (part A): the `${ENGINE[@]}` array on two `ballast48 measure` lines and one comment line;
  empty on the VM. The other three of the ruling's four (`deploy/docker-compose.yml`, `deploy/poc.sh`,
  `tools/dgpu48.py`) are not changed.

## Not verified

Nothing ran on a real card, Docker daemon or host; everything is on stand-ins. No engine probe has run on a 575 driver;
whether the bench card supports the forward-compatibility path, whether s08 starts the servers without
`NVIDIA_DISABLE_REQUIRE=1`, and the size of the leak per context are unknown. Stage O's `verifier-flag` recreates the
verifier from `down.json`'s command and environment; that it keeps the compatibility form was read, not run.
