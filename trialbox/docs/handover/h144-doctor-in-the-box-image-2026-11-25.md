# H144: the doctor's image checks run in the box image, and a loose services/ is named

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-144, High and ring 0 (the integrator's 7159322336 items 2 and 3, ruling 7159506328; the lead's go with
  one choice, posted on #1504: a loose folder is named, not removed; the integrator's three additions 7159790789:
  a network only where a check needs one, only what a check reads with no secret back, release_tree a WARN unless a
  host command would import the folder).
- **Date:** 2026-11-25
- **Decision:** [D-1463](../decisions/D-1463-the-doctors-image-checks-run-in-the-box-image-and-a-loose-folder-is-named.md)
- **Findings:** [`h144-doctor-in-the-box-image-2026-11-25/findings.json`](h144-doctor-in-the-box-image-2026-11-25/findings.json)
  (H144-01 to H144-06)
- **Files outside the card** (one assertion, named for the lead): `tests/unit/test_trialbox_doctor.py`'s
  `test_default_install_passes` holds the exact set of the doctor's check names; it gains `release_tree`, as each
  new check's card has added its name there.
- **Files:** `tools/trialbox/doctor.py` (`IMAGE_CHECKS`, `needs_image`, `image_part`, `run`'s merge, the new
  `release_tree` check), the new `tools/trialbox/doctor_image.py`, `tools/trialbox/__main__.py` (`doctor --only`,
  the hand-off, no `services/` on the installed path), `tools/host_tree.py` (`IMAGE_ONLY`, `install_folder`,
  `loose`, `loose_note`), `tools/trialbox/update.py` (`_name_loose`), runbook §5, the new test
  `tests/unit/test_doctor_in_image_h144.py`.

## 1. What failed

The walk updated the box to c3a5b2b2 (rc 0, 16 of 16 healthy). `trialbox doctor` on the host then ran 41 checks and
17 FAILed. 16 were import errors on the host's own Python (the standard library and PyYAML, install.sh HOST-PYTHON):

| Missing | Checks |
| --- | --- |
| pydantic (`tb_common.config`, `tb_contracts`) | topology, env_class_ceiling, named_choices, note_block, chartno_rule, db_passwords, wsl2_memory, update_window, backup_speed |
| httpx and the services' code | judge_route |
| the services' code (`services/`) | routing_perimeter, perimeter_addresses, phi_tripwire, channel_engine, registry_pins, terminology |

Four of them (routing_perimeter, perimeter_addresses, judge_route, registry_pins) also read `models/routing.yaml` or
`models/registry.yaml`. The signed host tree carries `deploy`, `tools`, `libs` and `schemas` only
(`host_tree.TOP_DIRS`), so neither file is in a release on the host. The 17th, `audit_heads`, is the box's own
setting (no off-box anchor folder).

**Reproduced at master c3a5b2b2** (the test's own box: this repository's host tree installed twice, R1 then R2, run
by the installed wrapper on a Python where pydantic, httpx and every `services/` package cannot be imported): 41
checks, 15 import-error FAILs, no image run. `note_block` did not reach its import on this synthetic box's settings.

## 2. Which checks run where (read from the image)

- The 16 checks above (`doctor.IMAGE_CHECKS`) run in one-off containers of the box's own image. The image
  (`deploy/docker/python.Dockerfile`) carries `/app/services`, `/app/models`, `/app/libs` and the locked libraries.
- Every other check runs on the host, as before: the engine, systemd, the clock, the key custody, the backup
  schedule, the anchor folders, the hold after a restore, the release tree.
- The container (`tools/trialbox/doctor_image.py`):
  - is the box file's `TB_IMAGE` and `TB_DOCKER`, never a caller's;
  - runs with `--pull never`, `--cap-drop ALL` and `no-new-privileges`;
  - has a network only where a check needs one (`doctor_image.NETWORK`). `perimeter_addresses` runs in its own
    container on the box's model network (`<project>-model-net`), resolving each endpoint as the gateway does; the
    other 15 only read files and run with `--network none`. A network that is not there (the box is not running) is
    that check's FAIL, naming the engine's answer;
  - mounts only what the checks read, read-only: the box's deploy folder at `/app/deploy`, with its secret and data
    folders covered by an empty read-only folder (`doctor_image.HIDDEN`: secrets, keys, backups, updates,
    pgbackrest, models, ops, logs, refdata); the release tree its links point to at `/app/current`; the code
    systems' volume;
  - takes the settings by `--env-file` only, so no value is on a command line;
  - every value of a secret-named setting (`doctor_image.SECRET_NAME`) is replaced by `[redacted]` in each verdict
    and in any error text that comes back, before anything is printed.
- What the container cannot see is handed in, as check_host.sh hands it: the running containers' `docker inspect`
  on standard input (it holds passwords: a pipe) and the pid map's row (no secret).
- It answers `doctor --only NAMES --json`. Its verdicts join the host's in `CHECKS` order (`doctor.run(image=...)`).
- **Never a pass, never a skip.** A container that cannot start, answers nothing that parses, or leaves a check
  out: each unanswered check is a FAIL that says why. An import error inside it is that check's own FAIL.
- **When** (`doctor.needs_image`): never inside the image; always from an installed release tree (its
  `HOST-SHA256SUMS`); from a source checkout only when its interpreter lacks what the checks import or the checkout
  lacks `models/`. So CI and a developer's checkout run every check in place, as before.

## 3. A loose services/ or models/ (named, never removed)

- `host_tree.IMAGE_ONLY` (services, models, rulesets, catalogue, eval): the image's folders the host tree does not
  carry. A copy in the install folder is not the release's.
- `doctor`'s new `release_tree` check WARNs on an installed box while one is there. It names each folder and the
  command that removes it (`sudo rm -rf -- ...`). It FAILs only when the command's own import path holds the folder
  (a caller's PYTHONPATH, as in the runbook's module run): run so, a host command would import it. Otherwise no host
  command imports it: the per-command test holds that (section 4). PASS on a source checkout; WARN inside the image
  (the install folder is not seen there).
- The update names it at its end (`update: note (H-144): ...`) and leaves it. Runbook §5 says what to do.
- The installed entry (`tools/trialbox/__main__.py`) no longer puts `<root>/services` on its path. An installed root
  is the release folder, which has no `services/`, so this changes nothing on a box. The guard that matters is
  `needs_image`: from an installed tree, the image's checks never run here.

## 4. Each host command's imports

- The test holds every command `launch.COMMANDS` runs on the host (24) to the modules `__main__` loads for it
  (`HOST_ENTRY`). For each, loading those modules reaches no `services/` package and no library beyond the standard
  library and PyYAML. All 24 pass today, so this guards against a regression.
- A function's own import runs only when that function does. A static count of those imports reaches pydantic,
  httpx and most of `services/` from nearly every command, through function-level imports in `tools/` (93 files
  in `tools/` import a services package). Which of those paths a host command really takes is not shown. That is
  H144-03, a follow-up, not a claim of this card.

## 5. The tests (`tests/unit/test_doctor_in_image_h144.py`, 37)

- **The invariant:** `test_h144_the_installed_doctor_on_a_hosts_own_python_reports_every_checks_own_verdict`.
  - Setup: the installed wrapper of a box made from this host tree (R1, then R2), on a Python without pydantic,
    httpx or the services' code.
  - It asserts that no check's verdict is an import error, and that the 16 are answered by two runs of the box
    image: 15 with `--network none` and `perimeter_addresses` on the box's model network. Both runs use the hand-off's
    options, with `secrets/` and `updates/` covered, and no secret is on a command line or in the output.
  - At master it fails (15 import errors, no image run).
- The image refused by the engine: each of the 16 is a FAIL naming the engine's answer, and no check is a SKIP.
- The integrator's test: a stale `services/` (whose `gateway` raises when imported) and a `models/` planted after
  the update.
  - The run is the runbook's module form from the install folder, with `services/` on PYTHONPATH and every library
    importable.
  - `release_tree` FAILs (that run's PYTHONPATH holds the folder), naming both folders and the command. The stale
    code is never imported, and both folders are left in place.
  - The installed wrapper on the same box (its own path only) WARNs the same folders.
- A network that is not there: `perimeter_addresses` FAILs naming it; the other 15 still answer.
- A check in the image that prints a secret setting's value: the doctor shows `[redacted]`; the value is nowhere in
  the output.
- The update's note, the merge's order, a check the image did not answer, `IMAGE_ONLY` against the Dockerfile, and
  the per-command imports (24).

**Mutants** (six planted, six caught):

1. The hand-off dropped (`needs_image` always False). 5 of the 34 fail: the invariant, the missing network, the
   stale folder, the secret, and the refused image.
2. An unrun check reported as SKIP. 3 fail: the unanswered check, the missing network, and the refused image.
3. The plain fallback "the libraries import, so run here" (`needs_image` from the import test alone). 5 fail, and
   the stale `services/` is imported.
4. Redaction off. 1 fails: the secret.
5. Every check with no network (`NETWORK` empty). 3 fail: the invariant, the missing network, and the stale folder.
6. The secret and data folders not covered (`HIDDEN` unused). 1 fails: the invariant.

A fourth mutant, which disabled only the installed-tree rule, is not caught. A release folder never has `models/`,
so the `models/` rule sends the checks to the image anyway: the installed-tree rule is defence in depth.

## 6. The four recurring finding types

- **Ctrl-C or SIGTERM:** the doctor only reads. The container is `--rm`. A signal ends the run with nothing written.
- **Files written in place:** none. The doctor writes no file on these paths. The update's note is a line of output.
- **Value sets and date windows:** not in this code.
- **A caller's environment:** the runtime and the image are the box file's (`launch.box_file`). The decision to go
  to the image rests on the release tree's own `HOST-SHA256SUMS` and the interpreter, never on a variable.

## 7. Not verified

- The bench host and a real box image: the container was a stand-in that runs this checkout as `/app`.
- The box rehearsal: its doctor phase on an installed box now takes the image path. Not run (H144-06).
- The model network's name on a real box (`<project>-model-net`, as `launch` names it for `eval`): shown only with
  the stand-in engine (H144-04).

## 8. OCR's review of #1512 (7162740417)

- **1512-4 (Medium), CI's two red unit shards:** the runbook text first sat at §5's lines 49-63 and moved the lines
  `tools/planted_faults.py` and the restore drill's committed `findings.json` pin. It is now its own section at the
  end of the page, after every pinned and cited line (c5c57359). Nothing that pins or cites a page-05 line was
  touched; the diff to that page only adds lines after its last one.
- **1512-1 (Low):** the update's note no longer names anything in a source checkout (`_name_loose` asks
  `host_tree.install_folder` first, as `release_tree` does). Test: `test_ocr_1512_1_...`.
- **1512-2 (Low):** an image part that cannot even be prepared (a deploy folder this user may not search) is each
  image check's FAIL with the reason, never a traceback. Test: `test_ocr_1512_2_...`; its refusal is a stand-in, so it
  runs as root and as an ordinary user.
- **1512-3 (Low):** each container is named (`tb-doctor-<pid>-<network>`); one that reaches `TIMEOUT_S` is removed
  (`rm -f`) and the check's FAIL says so. Test: `test_ocr_1512_3_...` (an engine stand-in that times out).
- Each of the three tests fails at c5c57359's code and passes after.
