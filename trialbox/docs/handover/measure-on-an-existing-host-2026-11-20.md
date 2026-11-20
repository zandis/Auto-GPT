# The 48 GB run on an existing host, one card of several (card H-67, 2026-11-20)

**Reader:** the people who build TrialBox, and the session that will drive the run on an existing host

Lane H. Findings H67-01 to H67-03 ([findings JSON](measure-on-an-existing-host-2026-11-20.json)). The commands and
what the host needs: the run sheet, `docs/plan/measurements/48gb-measuring-run-2026-11-19.md` section 10.

## What was asked

The 48 GB measuring run may move from a rented VM to an existing host with eight large cards (183,359 MiB each, an
older driver: 575 against the rented run's 580, no NVIDIA runtime registered with Docker yet). Two things:

- the ballast must not depend on the card's size, and must use one card chosen by index;
- steps s05 to s14 must run against a checkout on that host, with no VM, no driver install, no reboot, no bucket.

Nothing runs there until the owner says so. Everything here is proved on stand-ins.

## The target, as the code defines it

Unchanged in meaning: nvidia-smi's `memory.free` on the chosen card at `TARGET_MIB` = 49,140 MiB (the class's
`memory_total_mib` in `deploy/dgpu48-profile.yaml`), within `TOLERANCE_MIB` = 512 MiB (plan 10's rule, not tied to
any card). That is the free a 48 GB card of the class offers before anything starts.

What the ballast holds comes from the card's own figures as read: total - used - reserved - 49,140
(`tools/ballast.py` `hold_mib`). ballast48's view counts memory from the card's own total and the driver's reserve
as read at the check. No total is written in the code (a test reads both files for the two card totals).

A card that cannot offer the target refuses with its numbers: `card-too-small` when its total is below the target,
or when total minus the driver's reserve is not above it; `card-is-the-target` when it is within 512 MiB of it.

## One card of several

- `--gpu-index N` chooses the card (the ballast's `--gpu` takes it too). Every nvidia-smi question carries `-i N`:
  the card's figures, its compute processes, and every question lane J's measure asks through ballast48's view.
  Other cards are never read or touched.
- The card's UUID is taken at the first read, or given (`--gpu-uuid`, from the host form's preflight), and checked at
  every later read. A different card at that index is refused (`card-changed`): the hold releases, the view answers
  nothing, `during` says so.
- Other processes on the chosen card refuse the hold, named by count and memory only (a shared machine). A process
  on another card does not matter.
- The holder runs with `--gpus device=<UUID>` and `NVIDIA_VISIBLE_DEVICES=<UUID>`.
- The two model servers: the overlay asks Docker for `count: 1`, which takes whichever card Docker lists first.
  ballast48 now writes `gpu-pin.yml` in the option's folder (`device_ids: [<UUID>]` with compose's `!override`) and
  adds it after the overlay to every compose command of the measure. It proves the pin twice. Before the start:
  compose's resolved configuration (`docker compose ... config --format json`) of the very files and environment
  of the start must give each server exactly that card. After it: each container's device request
  (`docker inspect`) must be exactly that UUID. A failure before the start starts nothing. A failure after it stops
  the servers. Either way the measure is refused (exit 2, which ends the ladder), and lane J's summary is still marked
  "by ballast" and "REFUSED". `verifier-flag` proves the recreated verifier the same way.
- A record made under the ballast stays "by ballast" and never a tier record: every guard is kept. The UUID is never
  written to a packed record.

## The host form

`tools/measure48-host.sh preflight|run --gpu-index N --run-dir DIR [--weights-dir DIR] [--pull] [--no-o]`.

**Why a new entry, not a `--host` form of the VM script.** The VM script is a start-up script: one metadata file,
run as root at every boot. Its top level reads the metadata, sets the cost cap's systemd timer and holds the
power-off. A `--host` switch would need guards throughout it, and the self-stop would stay reachable code in the
host form. So the VM script now has a shared part first: definitions only, the step functions s05 to s14 and their
machinery. A `return` follows when `TB_M48_FUNCTIONS_ONLY=1`. The host script sources it and stops there: the VM's
power-off, reboot, driver and metadata code is not even defined in the host form (a test checks this). The VM keeps
its behaviour: its 23 rehearsal cases pass unchanged. One change reaches the VM too: the stop line's SIGINT goes to
the tool among the step's own processes only. Before, it went to every process on the machine whose command line
matched (`pgrep -f`). On the VM nothing else matches; side by side under `pytest -n auto` the VM's stop-line case
interrupted the SIGTERM case's stand-in once (`test_sigterm_saves_but_does_not_end_the_run_and_the_next_boot_resumes`
returned 0, not 143).

What differs on a host is small and named in the host script:
- s05: the stub's volumes only, never a prune;
- s06: no pull without `--pull`;
- s09: no apt; the venv, node and Chromium go in the run folder;
- the release and the stop line's SIGINT reach this run's own processes only.

The steps run in a child shell, so a signal reaches the script at once. SIGINT, SIGTERM and the cap's watchdog all
end the same way: the steps' processes are stopped, the servers come down, the ballast is released, the run's
Docker objects are removed, and the records are packed into `DIR/out`.

## Proven, and not

Proven on stand-ins (no card, no Docker daemon, no compose, not root):
- `tests/unit/test_ballast_any_card_h67.py`, 23 cases: totals of 97,887, 183,359 and small cards; reserved memory 0
  and non-zero; one card of eight; another process on the chosen card or on another; a UUID that changes; the holder's
  pin; the servers' pin proven, unproven before the start, and wrong after it; the recreated verifier; the plan CLI;
- `tests/unit/test_measure48_host_h67.py`, 28 cases: the preflight passing and each refusal; a full pass; a failure
  at s07; SIGTERM mid-run; the cap reached; the stop line, which spares a same-named process that is not the run's; the VM's self-stop not defined in the host form; no forbidden command in
  the script.

Not verified:
- compose's resolved JSON for `!override` and `device_ids`, and the shape of Docker's device request, on a real
  compose and daemon. A different shape refuses the measure; it never passes it.
- The driver 575 reading of `memory.free` and its reserve on the large card.
- The holder and the servers on a card other than index 0.
- The screen's tools installed in a run folder (uv, node, Playwright without `--with-deps`) on the host's system.
- Whether the stub's ports (8090, 8025 on 127.0.0.1) are free there.

## Existing tests changed

None. The VM script's text slices that tests read (`tool()` up to the next section line, the SIGINT block, the
Docker and toolkit lines) are kept. The H-66 tests pass with their literal totals unchanged: the code no longer
assumes them, and the tests still model the rented card.
