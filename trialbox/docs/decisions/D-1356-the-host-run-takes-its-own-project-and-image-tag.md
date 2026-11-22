# D-1356 The 48 GB host run takes its own compose project and image tag (H75)

- **Task:** lane H, card H-75 (the integrator's order of 2026-11-20 08:18 UTC; rulings of 2026-11-22 04:31,
  06:21 and 08:41 UTC: bodies only in six files of other lanes and `tools/network_sheet.py`) · **Date:** 2026-11-22
- **Status:** proposed (row reserved; the integrator flips it when merged)
- **Builds on:** H-67 (the host form), H-72 (its preflight), H-74 (the bench exception), card 24-2 (one database build)

## Decision

1. The box's Docker names the 48 GB run needs follow compose's own project and one tag variable, with today's value
   as the default, and no box setting (`TB_*`) is read or declared for them (the integrator's ruling of 2026-11-22
   08:41 UTC). Compose's project (`-p`, or `COMPOSE_PROJECT_NAME`, which compose also gives the file's
   interpolation; default `trialbox`, the file's `name:`) names its five fixed networks (`<project>-net`,
   `-model-net`, `-model-backend`, `-egress`, `-console`), the stub overlay's `<project>-hostnet`, `tools/dgpu48.py`
   `PROJECT` and `BACKEND_NET`, the volume `deploy/poc.sh` checks (`<project>_lake-data`) and the servers' containers
   in `tools/measure48-vm.sh` (`<project>-llm-service-1`, ...). `TRIALBOX_IMAGE_TAG`, when set, is the tag of
   `trialbox-postgres` that `deploy/build_db_image.sh` builds (its literal `-t trialbox-postgres:16-1` kept for the
   box) and `deploy/poc.sh` checks, and of `trialbox-py` for the canary and the pin tool in `tools/dgpu48.py` and the
   VM script. `tools/network_sheet.py` reads a network name's default. With nothing set, `docker compose config`
   renders byte-identical to master and every command is master's.
2. `deploy/poc.sh` builds images of names other than `trialbox-py:1.0.0` and `trialbox-jvm:1.0.0` by its own
   `docker build` path, on the given base (`--build-arg BASE_IMAGE`), never through `make images` (whose tags are the
   box's). The Makefile and the Dockerfiles are unchanged.
3. `tools/measure48-host.sh --project NAME --image-tag TAG` (defaults from the run id) sets those variables; the
   project `trialbox*` and the tags `1.0.0` and `16-1` are refused; it sets compose's existing image variables to its
   tag. H-72's refusal of any `trialbox-*` image is replaced by a stronger rule: the box's images, containers, volumes
   and networks are never built over, tagged, stopped or removed by a host run (an invariant test compares the box's
   lists before and after); the run's own names must not exist yet; at the end the run removes its own objects and
   the images of its own tag.
