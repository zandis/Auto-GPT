# D-621 `doctor` holds every service to the chart-number rule the pid map was built with

- **Task:** DOCTOR-CHARTNO (given to lane D by the integrator on 2026-11-12, from the review of lane E's #399)
- **PR:** this branch (`agent/DOCTOR-chartno-rule-in-every-service`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-301 (`tb_common.chartno`), D-579 (the installer asks the rule and writes `TB_CHARTNO_RULE`),
  D-595 (the adapter records the rule beside the site key and refuses a night under another)

## Context

The adapter records the chart-number rule in the pid map and refuses a night under another rule. Other processes
make pseudonyms too, each under its own `TB_CHARTNO_RULE`, without asking the pid map: the orchestrator's
`/setup/pseudonym` (site set-up, the opt-out desk), candidates, scenarios, the data core API, `tools/keys.py`. A
container that runs with another rule than the adapter is not noticed: an opt-out could be registered under a
pseudonym the feed never produces.

## Decision

1. **A `doctor` check, `chartno_rule`.** It reads the rule each service of the box is started with, from the
   box's compose files rendered with the box's values and from the environment of the containers that run now
   (the readings the `db_passwords` check already makes), and the rule the pid map recorded for the site. A
   service is one of ours when it is started with `TB_SITE_ID`; the database, the FHIR store, the model servers
   and the TLS front are not judged. No rule and `asis` are the same rule; spelling does not matter.
2. **FAIL** when two services differ, a rule cannot be read, or the services' rule is not the pid map's. The line
   names the services and both rules and says what it means: an opt-out or a set-up sheet filed by such a service
   gets a pseudonym the feed never produces. **WARN** when the pid map cannot be read. On a box that may hold real
   data (VALIDATION, PRODUCTION) the check is a FAIL when the services were not read at all (no `--env-file`).
3. **One place.** `TB_CHARTNO_RULE` comes from `deploy/.env` through the env file of every service of ours; a test
   holds that no compose file sets it for one service.

## Consequences

- A container started before the rule was written to `.env` fails the check until it is started again, which is
  what should happen: it would file pseudonyms under the old rule. This needs the running containers to be read
  (see the review below).
- **Not closed here:** the processes still do not ask the pid map when they make a pseudonym; `doctor` finds a
  difference when it is run (the install, the nightly checks), not at the moment of the opt-out. The host tool
  `tools/keys.py` runs outside the containers under the caller's environment and is not judged. The Kubernetes
  path (`doctor --platform`) reads no compose files and gets the WARN or FAIL of item 2.
- `tests/unit/test_trialbox_doctor.py` lists every check of a default run; the new name is added there.

## After the adversarial review (2026-11-12)

The first version was right for what its tests handed it and blind on a box: the host check runs `doctor` in a
container with no network and no docker, so neither the running containers nor the pid map were read, and the
rendered compose files alone cannot differ (one env file). It then passed, or warned for ever.

- **`deploy/check_host.sh` hands both in.** The environment of the project's running containers goes to the
  doctor's container through a pipe (`docker inspect` on standard input: it holds passwords and is never written
  to a file), and the pid map's row for the site (fingerprint and rule; no secret) as a setting, read with `psql`
  in the box's database container.
- **A PASS no longer says what was not read.** Containers not read, or the pid map not asked or not readable, is
  "NOT CHECKED" in the line and a WARN in VALIDATION and PRODUCTION. "The same as the pid map" and "no night has
  recorded a rule" are said only when the pid map was asked.
- **No service judged** (none started with `TB_SITE_ID`) is a FAIL on such a box, not "asis in 0 services".
- **A pid map row with a key and no rule** is a WARN: the adapter has not adopted a rule (D-595), so the rule the
  patients were loaded under is not known.
- One test runs the real base compose file through the real rendering.
- **Open:** two containers of one service leave one read (`running_config` keys by service); an inline comment
  after the rule in `.env` reads as part of the rule and fails the check (compose may strip it; not verified);
  jobs started with `docker compose run -e` are not containers of the stack and are not judged.
- **Not run here:** the new lines of `check_host.sh` (Docker is not running on the build machine, no shellcheck).
  The `shell` job and the next box rehearsal are their first run.

