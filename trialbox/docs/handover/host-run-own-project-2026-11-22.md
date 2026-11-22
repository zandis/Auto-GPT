# The 48 GB host run's own compose project and image tag (card H-75, 2026-11-22)

**Reader:** the integrator and the people who build TrialBox

Lane H. Findings H75-01 to H75-05 ([findings JSON](host-run-own-project-2026-11-22.json)). Rides after H-74
([its page](host-run-bench-exception-2026-11-22.md); this card is its finding H74-03, part B). The run sheet:
`docs/plan/measurements/48gb-measuring-run-2026-11-19.md` section 10.2. Decision: D-1356.

## Pull request body (draft)

**H-75: the 48 GB host run takes its own compose project and image tag, so it runs beside an installed box without
touching any of the box's objects (D-1356).**

- `tools/measure48-host.sh --project NAME --image-tag TAG` (default: both from the run id, lower-cased; never
  `trialbox`). The compose project, its containers, networks and volumes, and the images `trialbox-py`, `trialbox-jvm`
  and `trialbox-postgres` of the run carry them. Refused in one line (exit 2): a project `trialbox*`, a tag `1.0.0` or
  `16-1`.
- The preflight: H-72's refusal "any `trialbox-*` image refuses" is replaced by a stronger statement, not dropped (the
  integrator's ruling of 2026-11-22 08:41 UTC): the box's images, containers, volumes and networks are never built
  over, tagged, stopped or removed by a host run. An installed box's objects and images may be there (a note); the run's own project's objects and its tag's images must not exist yet; the stub's host ports
  (`TB_HOST_*_PORT`) must be free, a taken one named with its variable. At the end the run removes its own containers,
  networks, volumes and the three images of its tag (`docker image rm`, never `-f`), and nothing else.
- Six files of other lanes and `tools/network_sheet.py`, bodies only (the rulings of 2026-11-22 04:31, 06:21 and
  08:41 UTC): every box name the run needs follows compose's own project (`-p`, `COMPOSE_PROJECT_NAME`) or
  `TRIALBOX_IMAGE_TAG`, with today's value as the default. No box setting (`TB_*`) is read or declared for it; the run
  sets compose's existing image variables (`TB_IMAGE`, `TB_JVM_IMAGE`, `TB_EMBED_IMAGE`, `TB_DOCPARSER_IMAGE`,
  `POSTGRES_IMAGE`) to its tag. With nothing set, `docker compose config` of `docker-compose.yml`,
  `+ docker-compose.test.yml` and `+ docker-compose.poc.yml` (profiles stub, test, gpu) renders byte-identical to
  master's files (56,669, 61,691 and 63,302 bytes; compared by hand), and a test compares the three renders with the
  files' literal `trialbox` form.
- `deploy/build_db_image.sh` keeps the literal `-f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1` for the box;
  the run's tag replaces that pair only when `TRIALBOX_IMAGE_TAG` is set (ruling 4, its first choice:
  `test_image_config_scans.py` untouched). `tools/network_sheet.py` reads a network name's `${VAR:-default}` as its
  default: the three sheets are byte-identical to master's.
- `deploy/poc.sh` builds images of other names by its own `docker build` path with `--build-arg BASE_IMAGE`, never
  `make images` (whose tags are the box's); the Makefile and the Dockerfiles are unchanged.
- **Tests:** `tests/unit/test_measure48_host_own_names_h75.py`, 31 tests, among them the invariant
  `test_the_boxs_objects_and_images_are_never_touched_by_a_run` (seven ways: a full pass, a failure at s07, SIGTERM,
  the cap, and the planted box project and box tags refused; the box's lists of containers, networks, volumes and
  images identical before and after; a run that removes a box image fails it in all four run endings, checked once by
  hand). H-67's ten cases in `tests/unit/test_measure48_host_h67.py` move to the run's own names (ruling 1): its
  stand-in follows the project and tag, the H-72 refusal test is replaced by the invariant.

The bench host's commands (an existing host with an installed box, driver 575; card N; H-74's exception):

    cd <clean checkout>/trialbox
    # once, the engine probe on that card (the engine image already there is left in place)
    python3 tools/engine_probe.py run --only pinned,pinned+compat,pinned+libs --gpu-args '--gpus "device=N"' \
        --out ~/tb-engine-probe.json
    # reload the driver (or reboot) just before the run (H74-04)
    tools/measure48-host.sh preflight --gpu-index N --run-dir <run folder> --weights-dir <weights folder> \
        --run-id m48h-bench1 --project m48h-bench1 --image-tag m48h-bench1 \
        --bench-driver-exception forward-compat --engine-probe ~/tb-engine-probe.json
    tools/measure48-host.sh run --gpu-index N --run-dir <run folder> --weights-dir <weights folder> \
        --run-id m48h-bench1 --project m48h-bench1 --image-tag m48h-bench1 \
        --bench-driver-exception forward-compat --engine-probe ~/tb-engine-probe.json

If the preflight names a taken port (the box's console on 8090, for one), put the variable it names before both
commands: `TB_HOST_CONSOLE_PORT=18090 tools/measure48-host.sh ...`.

## What was built

| Where | What |
| --- | --- |
| `tools/measure48-host.sh` | `--project`, `--image-tag`; their checks; exports `COMPOSE_PROJECT_NAME` (compose's `-p`) and `TRIALBOX_IMAGE_TAG`, and sets compose's existing `TB_IMAGE`, `TB_JVM_IMAGE`, `TB_EMBED_IMAGE`, `TB_DOCPARSER_IMAGE` (the run's `trialbox-py:<tag>`) and `POSTGRES_IMAGE` (`trialbox-postgres:<tag>`); the preflight's objects and images of the run's names, the box's as a note, the stub's ports (H75-02); the end removes the run's own images; `records/head.json` and `records/docker-objects.json` carry `project` and `image_tag` |
| `deploy/docker-compose.yml` | `name: trialbox` unchanged (compose's `-p` overrides it); the five networks `${COMPOSE_PROJECT_NAME:-trialbox}-net`, `-model-net`, `-model-backend`, `-egress`, `-console` |
| `deploy/docker-compose.test.yml` | `${COMPOSE_PROJECT_NAME:-trialbox}-hostnet` |
| `deploy/build_db_image.sh` | the literal `-f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1` kept; `-t trialbox-postgres:$TRIALBOX_IMAGE_TAG` instead only when that is set |
| `deploy/poc.sh` | `IMAGE_DB` `trialbox-postgres:$TRIALBOX_IMAGE_TAG` when set; the volume check `${COMPOSE_PROJECT_NAME:-trialbox}_lake-data`; other image names build by its own path on `BASE_IMAGE` (the build inputs fetched on the host when it has Maven, curl and fontTools, else in the builder container, as before) (H75-03) |
| `tools/dgpu48.py` | `PROJECT` from `COMPOSE_PROJECT_NAME`, `BACKEND_NET` from it, `PY_IMAGE` `trialbox-py:$TRIALBOX_IMAGE_TAG` (the canary and the pin tool) |
| `tools/measure48-vm.sh` | the canary's network and image, the servers' container names from `COMPOSE_PROJECT_NAME` and `TRIALBOX_IMAGE_TAG` |
| `tools/network_sheet.py` | a network's `name:` read through its `interpolate` (the default of `${VAR:-default}`) |

No further file fixes a box name the run needs: `tools/ballast48.py`, `tools/ballast.py`, `tools/measure48_vm.py`,
`tools/engine_probe.py`, `tools/canary.py`, `tools/complete_run.py`, `tools/fetch_run_data.py` and
`deploy/docker-compose.dgpu48.yml` and `docker-compose.poc.yml` name none (grep). `docker-compose.identity.yml`'s
`trialbox-edge` is not on the run's path.

## The rulings of 2026-11-22 08:41 UTC (H75-01, H75-05)

1. H-67's ten cases: moved to the run's own names (`t1-net`, `t1_db`, `t1-llm-service-1`, `trialbox-py:t1`, removed
   at the end); the stand-in stub and servers follow `COMPOSE_PROJECT_NAME` and `TRIALBOX_IMAGE_TAG`; the refusal
   cases name the run's own objects and tag. `test_an_installed_boxs_images_refuse_the_run_and_are_left_as_they_were`
   is replaced by the invariant (a comment in its place names it).
2. `TB_COMPOSE_PROJECT` and `TB_DB_IMAGE` are gone: compose's own `COMPOSE_PROJECT_NAME` (what `-p` sets; compose
   gives it to the file's interpolation too, so the networks follow `-p` as well) and `TRIALBOX_IMAGE_TAG`.
   `libs/tb_common/config.py` is unchanged and `test_config_declared.py` passes.
3. `tools/network_sheet.py`: one line; the committed sheets are unchanged and `test_network_sheet.py` passes.
4. `deploy/build_db_image.sh`: the first choice (the literal line kept for the box); `test_image_config_scans.py` is
   untouched and passes.

## Files outside the card

`deploy/docker-compose.yml`, `deploy/docker-compose.test.yml`, `deploy/poc.sh`, `deploy/build_db_image.sh`,
`tools/dgpu48.py`, `tools/measure48-vm.sh`, `tools/network_sheet.py`: bodies only, by the rulings of 2026-11-22
04:31, 06:21 and 08:41 UTC. No
interface of an existing caller changes; with nothing set, every name and command is master's.

## Not verified

Nothing ran on a real Docker daemon, card or host: compose was rendered (it needs no daemon); poc.sh, the build
script, the VM script's functions and the host run ran against stand-ins of `docker`. Not run for real: poc.sh's own
build path with `BASE_IMAGE` (the Dockerfiles take it, read), `docker image rm` of the run's tag, the builder image's
fetch on a host without Maven, the port probe against a real box's console.
