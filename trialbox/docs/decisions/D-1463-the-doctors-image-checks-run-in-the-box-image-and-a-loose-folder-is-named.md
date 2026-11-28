# D-1463 The doctor's image checks run in the box image, and a loose services/ or models/ is named (H-144)

- **Task:** lane H, card H-144 (the integrator's 7159322336, items 2 and 3, and ruling 7159506328)
  · **Date:** 2026-11-25
- **Status:** reserved for H-144 (the integrator flips the row when merged)
- **Builds on:** D-176 (a site host has no pydantic: check_host.sh runs the doctor in the box image), D-1089 (every
  host command brings its own environment, `tools/trialbox/launch.py`), D-570 (the signed host tree), D-1091 (the
  five stops of a PoC box)

## Context

The walk updated the box to c3a5b2b2. `trialbox doctor` on the host ran 41 checks and 17 FAILed. 16 were import
errors on the host's own Python: no pydantic, no httpx, no `services/` on the path. Four of them also needed
`models/routing.yaml` or `models/registry.yaml`, which the signed host tree (`TOP_DIRS`: deploy, tools, libs,
schemas) does not carry. And the install folder still held a `services/` from before the signed host tree: no
update replaces or checks it.

## Decision

1. **Read from the image, not packed.** The checks of `doctor.IMAGE_CHECKS` (16 when this was decided; 18 since H-137's
   `trusted_proxy` and `mail_tls` joined, ruling 7169948573; 19 on the system join with M2's `terminology_tables`) run
   in one one-off container of the box's own image (`tools/trialbox/doctor_image.py`). The image carries the services' code, `models/` and the
   locked libraries; packing them into the host tree would need those libraries on the host's Python.
2. **The container** is the box file's image and runtime, `--pull never`, `--cap-drop ALL`, no new privileges. A
   network only for a check that needs one (the integrator's 7159790789): `perimeter_addresses` runs on the box's
   own model network, as the gateway resolves; the other 15 only read files and run with `--network none`. A
   network that is not there is that check's FAIL, saying so. Only what a check reads, read-only: the box's deploy
   folder with its secret and data folders covered by an empty folder (`doctor_image.HIDDEN`), the release tree, the
   code systems' volume; the settings by `--env-file`. What it cannot see is handed in as check_host.sh hands it: the
   running containers' `docker inspect` on standard input, the pid map's row. Every value of a secret-named setting
   is replaced by `[redacted]` in what comes back, before it is printed.
3. **Never a pass, never a skip.** An import error in the image is that check's FAIL with the module. A container
   that cannot start, answers nothing that parses or leaves a check out makes each unanswered check a FAIL with
   the reason. The host's and the image's verdicts are one list, in `CHECKS` order.
4. **When.** Never inside the image. Always from an installed release tree (its `HOST-SHA256SUMS`), so a loose
   `services/` a caller's PYTHONPATH reaches is never imported. From a source checkout, only when its interpreter
   lacks what the checks import or the checkout lacks `models/`.
5. **A loose folder is named, never removed.** `host_tree.IMAGE_ONLY` (services, models, rulesets, catalogue, eval)
   found in the install folder: `doctor`'s `release_tree` WARNs, naming each and the command that removes it, and
   FAILs only when the command's own import path holds it (the integrator's 7159790789: no host command imports it,
   the per-command test holds that); the update names it at its end. An update never removes what it did not make, and the folder may hold an operator's
   own change (the lead's ruling on #1504). The installed entry no longer puts `services/` on its path.

## Consequences

- A host's `trialbox doctor` reports each check's own verdict. It needs the box image and its runtime; without
  them the checks of `doctor.IMAGE_CHECKS` are FAILs that say so.
- A host command that imports a service package or a library beyond PyYAML at load time fails a test per command
  (`tests/unit/test_doctor_in_image_h144.py`). What a function imports when it runs is not covered by that test
  (H144-03).
