# D-1356 The 48 GB host run takes its own compose project and image tag (H75)

- **Task:** lane H, card H-75 (the integrator's order of 2026-11-20 08:18 UTC; rulings of 2026-11-22 04:31 and
  06:21 UTC: bodies only in six files of other lanes) · **Date:** 2026-11-22
- **Status:** proposed (row reserved; the integrator flips it when merged)
- **Builds on:** H-67 (the host form), H-72 (its preflight), H-74 (the bench exception), card 24-2 (one database build)

## Decision

1. The box's Docker names the 48 GB run needs follow variables, with today's value as the default:
   `TB_COMPOSE_PROJECT` (default `trialbox`) names the compose project (`deploy/docker-compose.yml` `name:`), its five
   fixed networks (`<project>-net`, `-model-net`, `-model-backend`, `-egress`, `-console`), the stub overlay's
   `<project>-hostnet`, `tools/dgpu48.py` `PROJECT` and `BACKEND_NET`, the volume `deploy/poc.sh` checks
   (`<project>_lake-data`) and the servers' containers in `tools/measure48-vm.sh` (`<project>-llm-service-1`, ...).
   `TB_DB_IMAGE` (default `trialbox-postgres:16-1`) is the tag `deploy/build_db_image.sh` builds and `deploy/poc.sh`
   checks; `TB_IMAGE` (already compose's) is also the canary's and the pin tool's image in `tools/dgpu48.py` and the
   VM script. With nothing set, `docker compose config` renders byte-identical to master and every command is master's.
2. `deploy/poc.sh` builds images of names other than `trialbox-py:1.0.0` and `trialbox-jvm:1.0.0` by its own
   `docker build` path, on the given base (`--build-arg BASE_IMAGE`), never through `make images` (whose tags are the
   box's). The Makefile and the Dockerfiles are unchanged.
3. `tools/measure48-host.sh --project NAME --image-tag TAG` (defaults from the run id) sets those variables; the
   project `trialbox*` and the tags `1.0.0` and `16-1` are refused. H-72's refusal of any `trialbox-*` image is
   relaxed: an installed box's objects and images may be present and are never built over, tagged or removed; the
   run's own names must not exist yet; at the end the run removes its own objects and the images of its own tag.
