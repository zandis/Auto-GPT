# The 48 GB host run's own compose project and image tag (card H-75, 2026-11-22)

**Reader:** the integrator and the people who build TrialBox

Lane H. Findings H75-01 to H75-04 ([findings JSON](host-run-own-project-2026-11-22.json)). Rides after H-74
([its page](host-run-bench-exception-2026-11-22.md); this card is its finding H74-03, part B). The run sheet:
`docs/plan/measurements/48gb-measuring-run-2026-11-19.md` section 10.2. Decision: D-1356.

## Pull request body (draft)

**H-75: the 48 GB host run takes its own compose project and image tag, so it runs beside an installed box without
touching any of the box's objects (D-1356).**

- `tools/measure48-host.sh --project NAME --image-tag TAG` (default: both from the run id, lower-cased; never
  `trialbox`). The compose project, its containers, networks and volumes, and the images `trialbox-py`, `trialbox-jvm`
  and `trialbox-postgres` of the run carry them. Refused in one line (exit 2): a project `trialbox*`, a tag `1.0.0` or
  `16-1`.
- The preflight (H-72's "any `trialbox-*` image refuses" relaxed): an installed box's objects and images may be there
  (a note); the run's own project's objects and its tag's images must not exist yet; the stub's host ports
  (`TB_HOST_*_PORT`) must be free, a taken one named with its variable. At the end the run removes its own containers,
  networks, volumes and the three images of its tag (`docker image rm`, never `-f`), and nothing else.
- Six files of other lanes, bodies only (the rulings of 2026-11-22 04:31 and 06:21 UTC): every box name the run needs
  follows a variable with today's value as the default (`TB_COMPOSE_PROJECT`, `TB_DB_IMAGE`, `TB_IMAGE`). With nothing
  set, `docker compose config` of `docker-compose.yml`, `+ docker-compose.test.yml` and `+ docker-compose.poc.yml`
  (profiles stub, test, gpu) renders byte-identical to master's files (56,669, 61,691 and 63,302 bytes; compared by
  hand once), and a test compares the render with the files' literal `trialbox` form.
- `deploy/poc.sh` builds images of other names by its own `docker build` path with `--build-arg BASE_IMAGE`, never
  `make images` (whose tags are the box's); the Makefile and the Dockerfiles are unchanged.
- **Tests:** `tests/unit/test_measure48_host_own_names_h75.py`, 24 tests. **Ten tests of H-67's
  `tests/unit/test_measure48_host_h67.py` now fail** (below): they assert the box's fixed names and H-72's refusal.
  Their assertions are not changed here; a question to the integrator (H75-01).

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
| `tools/measure48-host.sh` | `--project`, `--image-tag`; their checks; exports `TB_COMPOSE_PROJECT`, `TB_IMAGE`, `TB_JVM_IMAGE`, `TB_EMBED_IMAGE`, `TB_DOCPARSER_IMAGE` (the run's `trialbox-py:<tag>`), `TB_DB_IMAGE` and `POSTGRES_IMAGE` (`trialbox-postgres:<tag>`); unsets `COMPOSE_PROJECT_NAME` (H75-04); the preflight's objects and images of the run's names, the box's as a note, the stub's ports (H75-02); the end removes the run's own images; `records/head.json` and `records/docker-objects.json` carry `project` and `image_tag` |
| `deploy/docker-compose.yml` | `name: ${TB_COMPOSE_PROJECT:-trialbox}`; the five networks `${TB_COMPOSE_PROJECT:-trialbox}-net`, `-model-net`, `-model-backend`, `-egress`, `-console` |
| `deploy/docker-compose.test.yml` | `${TB_COMPOSE_PROJECT:-trialbox}-hostnet` |
| `deploy/build_db_image.sh` | `-t "${TB_DB_IMAGE:-trialbox-postgres:16-1}"` |
| `deploy/poc.sh` | `IMAGE_DB` from `TB_DB_IMAGE`; the volume check `${TB_COMPOSE_PROJECT:-trialbox}_lake-data`; other image names build by its own path on `BASE_IMAGE` (the build inputs fetched on the host when it has Maven, curl and fontTools, else in the builder container, as before) (H75-03) |
| `tools/dgpu48.py` | `PROJECT` from `TB_COMPOSE_PROJECT`, `BACKEND_NET` from it, `PY_IMAGE` from `TB_IMAGE` (the canary and the pin tool) |
| `tools/measure48-vm.sh` | the canary's network and image, the servers' container names from `TB_COMPOSE_PROJECT` and `TB_IMAGE` |

No further file fixes a box name the run needs: `tools/ballast48.py`, `tools/ballast.py`, `tools/measure48_vm.py`,
`tools/engine_probe.py`, `tools/canary.py`, `tools/complete_run.py`, `tools/fetch_run_data.py` and
`deploy/docker-compose.dgpu48.yml` and `docker-compose.poc.yml` name none (grep). `docker-compose.identity.yml`'s
`trialbox-edge` is not on the run's path.

## The ten H-67 tests that fail (H75-01)

`tests/unit/test_measure48_host_h67.py`: `test_the_preflight_passes_and_changes_nothing`,
`test_each_preflight_refusal_is_named_and_nothing_changes` (three cases: a box container, a box volume, two box
images), `test_sigterm_mid_run_ends_the_steps_and_removes_what_the_run_made`,
`test_an_installed_boxs_images_refuse_the_run_and_are_left_as_they_were`,
`test_a_full_pass_runs_s05_to_s14_on_the_chosen_card_and_leaves_nothing`,
`test_the_cap_ends_the_steps_and_cleans_up_without_powering_anything_off`,
`test_a_failure_at_s07_ends_cleanly_with_its_reason`,
`test_the_stop_line_interrupts_the_runs_measure_and_no_other_process_of_that_name`. They pass on the H-74 base
(fd2fcedc). The cause: the rig's stand-in stub and servers make objects under the fixed box names (`trialbox_db`,
`trialbox-net`, `trialbox-llm-service-1`, `trialbox-py:1.0.0`), which the run now treats as the box's and leaves; and
the assertions name them, H-72's refusal and its words.

**question:** a ruling to change those assertions to the run's own names: the stand-in follows `TB_COMPOSE_PROJECT`
and the tags (as `OwnRig` in the new test file does), the names asserted become `t1-net`, `t1_db`,
`t1-llm-service-1`, `trialbox-py:t1` (removed, no longer "made and kept"), the three box refusals become the run's
own names' refusals (as in the new file), and `test_an_installed_boxs_images_refuse_the_run_...` is replaced by the
new full run beside a box.

## Files outside the card

`deploy/docker-compose.yml`, `deploy/docker-compose.test.yml`, `deploy/poc.sh`, `deploy/build_db_image.sh`,
`tools/dgpu48.py`, `tools/measure48-vm.sh`: bodies only, by the rulings of 2026-11-22 04:31 and 06:21 UTC. No
interface of an existing caller changes; with nothing set, every name and command is master's.

## Not verified

Nothing ran on a real Docker daemon, card or host: compose was rendered (it needs no daemon); poc.sh, the build
script, the VM script's functions and the host run ran against stand-ins of `docker`. Not run for real: poc.sh's own
build path with `BASE_IMAGE` (the Dockerfiles take it, read), `docker image rm` of the run's tag, the builder image's
fetch on a host without Maven, the port probe against a real box's console.
