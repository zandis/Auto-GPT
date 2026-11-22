# H-89: the install walk with real model servers on the bench host, a rehearsal box only

**Reader:** the integrator and the people who build TrialBox

Lane H, 2026-11-22. HIGH-RISK: it loosens three install refusals, for a rehearsal box only. The integrator's ruling of
2026-11-22 13:55 UTC: go, after H-86, independent review before the line.

## Pull request body (draft)

The bench host (whole B200-class cards, NVIDIA driver 575, below deploy/images.lock `gpu.driver_min` 580.65.06, never
to be upgraded) could not install with the real model servers at all. This card opens the install there, and only on
a rehearsal box, with one explicit command line.

### The bench's command lines, in order

1. Reload the driver first: on driver 575 the forward-compatibility path leaks driver memory per CUDA context (H-74's
   caution). Then read the free memory of the one card chosen, here card 1:

       sudo systemctl stop docker && sudo rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia && sudo modprobe nvidia && sudo systemctl start docker
       nvidia-smi -i 1 --query-gpu=name,mig.mode.current,memory.free,memory.total --format=csv

2. The engine probe on that one card (never all):

       python3 tools/engine_probe.py run --gpu-index 1 --out ~/tb-engine-probe.json
       chmod go-w ~/tb-engine-probe.json

3. The install, on an empty box:

       sudo deploy/install.sh trialbox-<version>.tar --rehearsal --rehearsal-real-servers --gpu rtxpro6000 \
           --gpu-index 1 --engine-probe ~/tb-engine-probe.json --yes

With `--gpu-index N` the probe runs on that one card (`--gpus device=N`) and records that card's facts and two one-way
ids (sha256 digests, no UUID or machine id in the file): the card's and this host's (/etc/machine-id). The install
then requires the probe to be at most 7 days old.

### What changes for a site: nothing

Without `--rehearsal` the three new options are refused at argument parsing, one line each, exit 2, before anything
is checked or written. Without the options every line of the installer runs as on master: the invariant test below
compares the bytes and the exit code of each refusal with and without everything planted, and they were compared
with master's own installer (97048772e0bb) in this session: identical in all nine cases.

### What "the mark is present" means

All of: `--rehearsal` and `--rehearsal-real-servers` on this install's command line, and the box may be a rehearsal
box (`tools/rehearsal_real.py` `box_problems`: deploy/.env TB_ENV none, DEV or TEST, or VALIDATION with both
deploy/site/rehearsal.json and TB_REHEARSAL=1; no site install without the mark). It is judged BEFORE the GPU check
(install.sh passes the rehearsal state down to deploy/check_host.sh and tools/images_lock.py as explicit arguments,
and images_lock.py judges the box again itself): the driver check runs before the mark file is written, and the
refusal must stay where it is for a site. A hand-made rehearsal.json opens nothing: without `--rehearsal` the
installer refuses that box (as on master); with it, a PRODUCTION or unmarked VALIDATION box is refused before the GPU
check. The full REHEARSAL block of master (the volumes, the stand-ins file) then runs as before, before anything loads.

### The three steps, under the mark only

1. **The driver.** check_host.sh `--gpu-only --gpu rtxpro6000 --rehearsal-real-servers --engine-probe F --gpu-index N`
   reads that card's driver, compute capability and model; `tools/images_lock.py host` then turns the driver FAIL
   into `WARN ... rehearsal: driver below the minimum (found 575..., minimum 580.65.06) ...; not valid for a site`
   only when H-74's check passes: `tools/measure48_vm.py bench_exception`, the ONE implementation (pass with
   pinned+compat or pinned+libs, the compatibility libraries seen, this card, this driver, the lock's pinned image,
   digest not mismatched). Anything else: master's FAIL line, plus one line per reason. The probe's recorded
   environment (`verdict.env`) goes to llm-service and llm-verifier, read from the probe file, and only when the
   driver is below the minimum.
2. **The card.** `--gpu rtxpro6000` must be named; `--gpu-index N` names one whole card. Refused: no card at that
   index, MIG on (current or pending), less free memory than the pair needs. The overlay asks for a device with
   `count: 1` (the first card); deploy/site/rehearsal-real-servers.yml replaces that (`!override`) for both servers
   with `device_ids: ["<that card's UUID>"]`. The overlay's serving arguments are not changed.
3. **The record.** On master an existing record is checked against the profile's card name, not this host's card
   (finding H89-01): there is no record refusal to loosen when the shipped record is present. Under the mark the
   install now says it: `install: warning: rehearsal: ... : the record ... was measured on NVIDIA RTX PRO 6000 ...,
   the servers run on card 1, NVIDIA B200`, behind `rehearsal_only` (TB_ACCEPT_UNMEASURED_GPU's rule).

### The memory the pair needs

The record (deploy/measured/serving_config.rtxpro6000.json) measured 62,574 MiB used on a 97,887 MiB card: the judge
at `--gpu-memory-utilization 0.40` and the verifier at 0.20, 32k context each. vLLM's fractions are of the whole card
it is given: on a B200 of 183,359 MiB the pair asks for 0.60 of it, 110,016 MiB (the rest is KV cache beyond the
record's). The card check requires the larger of the two figures free and names both.

### What the box says

deploy/site/rehearsal-real-servers.json beside rehearsal.json: the driver found and the minimum, the card found and
the profile's card, the probe file's sha256, the form and environment used, `valid_for_a_site: false`, and the words
"rehearsal: driver below the minimum, not this profile's card, not valid for a site". The installer's summary ends
with `REHEARSAL BOX:` and the words; `trialbox doctor`'s rehearsal line is a WARN with the words; the host check's
driver line is a WARN with them when run with the rehearsal arguments (run plainly it FAILs, as for a site). The
console's banner shows "VALIDATION REHEARSAL" from TB_REHEARSAL (services/console/app.py `environment_banner`); it
cannot show the words without a console change: a question, not an edit.

### Never a PRODUCTION box without a new install

Found and closed: (a) an install re-run without the options on a box with the record or the compose file: refused
(new, independent of rehearsal.json); (b) `--rehearsal --environment PRODUCTION`: refused (as before, now also before
the GPU check); (c) a hand edit of TB_ENV to PRODUCTION, with or without the mark and TB_REHEARSAL removed, then an
install's or an update's start: refused by a guard that runs before every pre-start and db-up step
(tools/trialbox/prestart.py `_rehearsal_guard`, `rehearsal_real.start_refusal`; a guard, not a step, so the steps
list and its floor are unchanged); (d) doctor FAILs the same boxes. The record and the compose file (also found
through COMPOSE_FILE) are signs of their own: removing rehearsal.json by hand is not enough. Open: the boot start
(systemd ExecStartPre deploy/settings_guard.sh, not lane H's file) does not run the guard (finding H89-02, a question).

### What a rehearsal with real servers proves, and does not

Proves, when the bench runs it: the install walk end to end with the pinned engine image serving the real pair, on a
card and driver that are not a site's: the bundle, the settings, the pins, `doctor --serving`, the console. Does not
prove: anything about a site's card or driver (the forward-compatibility path, the driver memory leak), the
rtxpro6000 profile's performance or context on its own card, or a qualification. It is not valid for a site.

### Tests

* THE INVARIANT: `test_without_the_mark_the_three_refusals_are_byte_identical` in `tests/unit/test_rehearsal_real_servers_h89.py`
  (nine cases: the driver; a whole B200, a MIG B200, b200-no-mig, shared-quota, dgpu48, arm64-dgpu named, an unknown
  profile; a card not the profile's), plus `test_without_the_mark_the_record_step_is_as_before` (no record, no record
  with TB_ACCEPT_UNMEASURED_GPU=1, a record of another card, the profile's record).
* The changed assertion (ruled): `test_the_install_path_has_no_bench_exception` in
  `tests/unit/test_measure48_host_bench_h74.py` now looks for H-74's words OUTSIDE the blocks marked `REHEARSAL-REAL-SERVERS (H-89)` in deploy/check_host.sh,
  deploy/install.sh and tools/images_lock.py, requires each file to name that block, and requires the rehearsal path's
  own names (`rehearsal-real-servers`, `rehearsal_real`, `--engine-probe`) nowhere outside it. Its other assertions
  (the bench option refused by check_host.sh and images_lock.py, a low driver still FAILs) are unchanged.

## Decision D-1087 (the record: docs/decisions/D-1087-a-rehearsal-box-may-run-the-real-servers-on-another-card.md)

Under the rehearsal mark only, and with an explicit command line, the install may run the real model servers of the
rtxpro6000 profile on one whole card of another model and on a driver below the lock's minimum, when an engine probe
of that card, driver and pinned image passed with a forward-compatibility form. The box records it, says it is not
valid for a site, and can never start as PRODUCTION; a site's install is unchanged.

## Mutation pass

35 mutants planted, one at a time, in the source; the H-89 and H-74 test files run; the source put back. 34 caught.
The one that survived (`{ true || ... }` in check_host.sh's whole-arguments check) was equivalent (the shell's
precedence kept the refusal); planted again as the check removed, it is caught. Planted: the mark check dropped at
the driver (the box check), the card (the block's guard) and the record (`rehearsal_only`); the new options accepted
without `--rehearsal`; the profile not required; the card check dropped; the independent record check dropped; an
operator's TB_COMPOSE_OVERRIDE accepted; `--environment PRODUCTION` accepted early; the summary line missing; the
first card's name taken instead of the named card's; images_lock: a WARN whatever the probe says, partial arguments
taken; the box rule: PRODUCTION allowed, VALIDATION without the mark allowed, ignored by the allowance; the probe's
card, driver and image checks loosened (H-74's function); MIG allowed; memory not checked; the need without vLLM's
fractions; `count: all` for the device; the probe's environment not passed, or passed with a good driver; the start
guard: PRODUCTION with the mark allowed, the real-servers record without a whole box allowed, the record not a sign,
dropped from prestart; the doctor's words missing, the record not a mark; the card fact dropped from the words; the
record written without the mark. Two tests were added for survivors found while planning (the card named by index is
the one judged; the summary line).

## Findings

In `rehearsal-real-servers-h89-2026-11-22/findings.json` (`--add-from` form).

## Review round 1 (#1370 at 0f6cb619, "fix first"), as ruled

* **H1, the boot path:** deploy/settings_guard.sh (the systemd unit's ExecStartPre) now runs
  `python3 -m tools.rehearsal_real start` when the box carries a rehearsal sign (deploy/site/rehearsal.json, the
  real-servers record or compose file, TB_REHEARSAL or TB_REHEARSAL_REAL_SERVERS in deploy/.env); a box without one
  is not asked and behaves byte for byte as before (a test with a failing python3 on PATH).
* **M1, the probe's environment:** only the passing form's named variables reach the model servers
  (`tools/engine_probe.py TESTS`: pinned+compat exactly NVIDIA_DISABLE_REQUIRE=1 and the compatibility switch;
  pinned+libs NVIDIA_DISABLE_REQUIRE=1 and an LD_LIBRARY_PATH that starts with the compatibility folder, plain folders
  only). Anything else (LD_PRELOAD, a changed value) refuses the driver allowance; nothing is written.
* **M2, the probe file:** the card's one-way id and this host's must match, `digest_matches` must be true (missing is
  refused), at most 7 days old, owned by root or the installer and not group- or world-writable. H-74's check is
  unchanged; these are this card's own (`rehearsal_real._probe_problems`).
* **L1:** `rehearsal_real.env_file` reads `export NAME=` and an unquoted value's trailing ` # ...` as compose does.
* **L2:** the H-74 guard test also requires every H-89 block closed and H-74's compatibility words nowhere in the
  three files, blocks included.
* **L5:** the console's banner says "VALIDATION REHEARSAL: rehearsal: driver below the minimum, not this profile's
  card, not valid for a site" when deploy/.env has TB_REHEARSAL_REAL_SERVERS=1 (written by the installer under the
  mark) on a rehearsal box.
* **L3 (row H89-05):** deploy/site/rehearsal.json is checked for existing only (as on master); forging it needs root
  on a DEV, TEST or VALIDATION box, and a PRODUCTION box refuses it.
* **L4 (row H89-06):** with pinned+libs the probe's recorded LD_LIBRARY_PATH (the compatibility folder, then the
  image's own value as the probe saw it) replaces the image's value instead of being put in front of it: to be
  checked on the bench.

Mutants of this round: 15 planted (the boot guard dropped and asked always; the allow-list dropped, extra names
allowed, the libs path loosened; the card id, host id, digest, age, mode and owner checks dropped; `export` not read;
the banner's sentence cut; the deploy/.env sign ignored); 15 caught (one planted twice: its first form was malformed).
The invariant was compared again with master 7dcba1be's own installer: identical in all nine cases.

### Files outside the card (ruled: bodies only)

`deploy/settings_guard.sh` (the boot guard), `services/console/app.py` (`environment_banner`, the sentence),
`tools/engine_probe.py` (`--gpu-index`, the one-way ids `card_id` and `host_id`; without the option as before).
