# H-89b: the rehearsal with real servers on the remaining shipped profiles, a rehearsal box only

**Reader:** the integrator and the people who build TrialBox

Lane H, 2026-11-23. HIGH-RISK: it loosens, under the rehearsal mark only, what the installer accepts. The owner's
ruling (7087828219): every shipped profile is tested on the bench. The integrator's rulings for the remaining four
(7088891993), built in their order, each in its own commit. This page follows H-89's
(docs/handover/rehearsal-real-servers-h89-2026-11-22.md) and amends D-1087 (no new decision number was given: an
amendment section on the record). An earlier worker's three commits (the slice, the Windows path, a page) were read,
checked and taken where sound.

## Pull request body (draft)

The four profiles H-89 left closed are opened under the mark, and only there: the 48 GB draft, the 128 GB
unified-memory class as an x86 stand-in, the 32 GB profile on a split card's slice, and the Windows host path. Item 5
(a real-servers case in the container rehearsal) is not built: a row below says why.

### The rows

Steps 1 and 2 of H-89's page (reload the driver; the engine probe, as root, into the root-owned folder) come first for
every row; the probe is taken on the same card or slice the install names. `<bundle>` is the release's bundle;
`P` is `/var/lib/trialbox/rehearsal/engine-probe.json`.

| Profile | Opened | Its memory cap on the bench (a card of 183,359 MiB) | The bench's command form (step 3) | What the bench's row does NOT prove |
| --- | --- | --- | --- | --- |
| dgpu48 (48 GB) | yes, under the mark | its overlay's 0.57 and 0.27 of 49,140 MiB, both resident: 0.152 and 0.072 (27,870 + 13,201 MiB; the card check asks 41,073 MiB free) | `sudo deploy/install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu dgpu48 --gpu-index N --engine-probe P --yes` | the 48 GB class's older architecture (no FP8 or FP4 kernels): the bench's card runs the pair's 4-bit formats natively, a card of that class does not; its memory figures are carried from the 96 GB card, unmeasured |
| gb10 (128 GB unified) | yes, under the mark, on an x86_64 host only | its overlay's 0.30 and 0.15 of 131,072 MiB (128 GiB, the class's nominal memory), both resident: 0.214 and 0.107 (39,238 + 19,619 MiB; 58,859 MiB free) | `sudo env TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu gb10 --gpu-index N --engine-probe P --yes` | "x86 stand-in: memory budget only": the class's Arm CPU, its unified memory shared with the box's other services, its pinned driver and the arm64 images |
| rtx5090 (32 GB), a split card's slice | yes, under the mark | the profile's 0.81 of 32,607 MiB scaled to the slice's own memory: on a slice of 89,600 MiB, 0.294 each (26,342 MiB, one server awake at a time) | `sudo python3 tools/engine_probe.py run --gpu-index N:M --out P`, then `sudo env TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu rtx5090 --gpu-index N:M --engine-probe P --yes` | a 32 GB card's own bandwidth, compute and the sleep swap's timing on it; the slice forms of nvidia-smi and docker on the bench's card (H89b-01, H89b-02) |
| Windows host (WSL2) | the passthrough, under the mark | the named profile's, as on a Linux host | inside WSL2: `sudo deploy/box-install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu <profile> --gpu-index N --engine-probe P` | not verified until a WSL2 host exists (ring 1): the WSL2 kernel, its GPU path and the Windows entry (box-install.ps1 passes none of the options: H89b-03) |
| item 5: the container rehearsal's real-servers case | not built (a row) | - | - | see "Item 5" below: the install with the real-servers flags through the bundle load and the signed re-run is held by unit tests only (H-89c's test_rehearsal_real_servers_signed_rerun_h89.py), not by `rehearse (validation)` |

`TB_ACCEPT_UNMEASURED_GPU=1` in the gb10 and slice rows: neither profile has a shipped serving record
(deploy/measured/ holds the rtxpro6000 record only), so install.sh's record step (deploy/install.sh, "has no measurement on its own card") needs the
unmeasured trial boot's switch, on a rehearsal box only, as before; the whole-card rtx5090 row of H-89 needs it too
(H89b-06). dgpu48 needs none: it has no measurement rule at all, and its own H-89b block says so (below).

### 1. dgpu48: opened under the mark

* **The profile step.** deploy/install.sh's refusal of the draft (cards 24-5, 24-6) stays where it was; it now reads
  `dgpu48) [ "$REAL_SERVERS" = 1 ] || die "dgpu48 is a DRAFT, ..."`, and the list of names after it accepts dgpu48 on
  the same condition. `REAL_SERVERS` is 1 only with `--rehearsal --rehearsal-real-servers` on the command line (an
  environment variable never sets it), and the H-89 block has by then checked the rest.
* **The cap.** tools/rehearsal_real.py `OPENED["dgpu48"]`: deploy/docker-compose.dgpu48.yml's own utilisations on
  49,140 MiB, scaled by tools/ballast.py `util_on`; both resident (no swap), so the card check asks for their sum.
* **The later steps, under the mark only.** The overlay is the box's compose file; the box is labelled
  `TB_PROFILE=P-DGPU48-UNMEASURED` (the label the overlay gives its gateway); the pair is pinned as the 96 GB profile's
  (`pin_model --install rtxpro6000`: the overlay serves the same weights folders, and tools/pin_model.py has no dgpu48
  pair, which test_dgpu48_draft holds); the verifier is named as for every pair profile. The record step says, on a
  rehearsal box only, "the dgpu48 profile is a DRAFT, UNMEASURED 48 GB profile with no serving record".
* **Without the mark.** Master's bytes in five forms (named, a plain rehearsal, a low driver, by `TB_GPU_PROFILE`, with
  the measuring run's switch), with and without every rehearsal sign planted; run against master's own installer
  (371c9857) in this session too: the same in all six forms tried.

### 2. gb10: opened under the mark, an x86 stand-in

* **The pins.** deploy/docker-compose.gb10.yml pins every service it names to `platform: linux/arm64` (line 40, the
  `*arm` anchor). The overlay is not changed. Under the mark on an x86_64 host, the box's own compose override
  (deploy/site/rehearsal-real-servers.yml, written by tools/rehearsal_real.py, already the last compose file of a
  real-servers box) sets `platform: linux/amd64` on each of those services (`platform_services` reads them from the
  overlay); on an aarch64 host nothing is overridden; on any other host the write step refuses.
* **The host check.** deploy/check_host.sh's `gb10_stand_in` holds only with `--rehearsal-real-servers` (which only
  install.sh's rehearsal hands it) and `uname -m` x86_64: it WARNs "GB10 profile on x86_64: x86 stand-in: memory budget
  only (a rehearsal with real servers, not valid for a site)" in place of the FAIL, and the card, driver and image are
  judged as for every real-servers box (the probe's allowance). Without the rehearsal arguments it FAILs "GB10 profile
  on x86_64" as before; on an aarch64 host the rehearsal arguments with gb10 are refused as before.
* **What the box says.** The record's words end "(x86 stand-in: memory budget only)", and it keeps
  `platform_override` (the services, the platform, why).
* **Unchanged.** The 64 GB class is refused under the mark too (D-1335); the overlay's memory limits and utilisations
  are the class's own.

### 3. rtx5090 on a split card's slice: opened under the mark

* **The form.** `--gpu-index N:M` names slice M of card N, as `docker run --gpus device=N:M` names it. The 32 GB
  profile only: another profile on a slice is refused (install.sh, and tools/rehearsal_real.py again). Refused too: a
  card that is not split (MIG off, or only pending), a slice the card does not list, and any other form (`1:`, `:0`,
  `1:0:0`, `1,0`). A whole card with MIG on is refused as before.
* **The memory query.** tools/rehearsal_real.py `slice_query`: the slice's UUID from `nvidia-smi -L`, its own free and
  total memory from `nvidia-smi -q -x -i N` (the MIG device's `fb_memory_usage`). The card check asks for the
  profile's cap scaled to the slice's total; a slice smaller than the cap (a 1g slice of 22,400 MiB) is refused.
* **The probe.** `tools/engine_probe.py run --gpu-index N:M` runs on that slice and records the slice's own one-way id
  as `card_id`; every trust check of H-89 holds for the slice unchanged: card id (a probe of the whole card or of
  another slice is refused), host id, digest matched, age, owner and mode, read once and never through a link.
* **The pin.** deploy/site/rehearsal-real-servers.yml pins both servers to the slice by its own UUID; the record says
  `slice_of_a_split_card: true` and `index: "N:M"`.

### 4. The Windows host path (WSL2): the passthrough, not verified

deploy/box-install.sh takes `--rehearsal-real-servers`, `--gpu`, `--gpu-index` and `--engine-probe` under the mark
only (both `--rehearsal` and `--rehearsal-real-servers` on its command line) and hands them on to install.sh after the
plan's own flags, so the named profile wins over the detected one; install.sh then judges them as on a Linux host.
Without the mark each option is the unknown option it is on master (the same line, exit 2), and without the options
the line handed to install.sh is master's, byte for byte. Not verified until a WSL2 host exists (ring 1).

### Item 5: the container rehearsal's real-servers case, a row

Not built: it needs more than a small change to the rehearsal, and one of the changes is a refusal this card keeps.
tools/rehearse_box/box.sh lines 38-39 install with `TB_COMPOSE_OVERRIDE=.../standins.yml` (the model stand-ins) and
`--tier large`; under `--rehearsal-real-servers` install.sh refuses both (deploy/install.sh line 158, "no tier
install"; line 164, the caller's override, which the card keeps unchanged). A stand-in engine needs a second way to
put a compose file in front of the real servers (a design choice), and the job would also need a stand-in nvidia-smi
answering the per-card queries, a stand-in probe owned by root in a root-owned folder, a profile with its pins on the
rehearsal media's placeholders, and the record step's switch. The bundle load and the signed re-run with the
real-servers flags are held by H-89c's unit tests (tests/unit/test_rehearsal_real_servers_signed_rerun_h89.py).

### Never without the mark

* H-89's invariant `test_without_the_mark_the_three_refusals_are_byte_identical` passes untouched.
* For each newly opened profile a test holds master's bytes without the mark, with and without every rehearsal sign
  planted: `test_dgpu48_without_the_mark_is_masters_refusal_byte_for_byte`,
  `test_gb10_without_the_mark_is_masters_refusal_byte_for_byte` and
  `test_gb10_the_host_check_keeps_failing_it_on_x86_outside_the_rehearsal`, `test_without_the_mark_a_slice_is_as_on_master`,
  `test_the_windows_path_without_the_options_is_as_on_master` and `test_the_windows_path_refuses_the_options_without_the_mark`.
* Unchanged: never on PRODUCTION (the box rule, the start check, the boot guard), the completion mark, the caller's
  override refusal, never by an environment variable alone.
* Changed assertion (ruling 7088891993, confirmed by the lead): `test_the_profiles_not_opened_are_refused_by_name`
  refused `[dgpu48, gb10]` under the mark; it now refuses `[rtx4090, b200]` (a shipped profile not opened and an
  unknown name), each by name. The dgpu48 and gb10 commits narrowed it on the way; the commit after them restores it.

### Tests

tests/unit/test_rehearsal_real_servers_profiles_h89b.py (dgpu48, gb10): accepted under the mark and held to the
class's cap; a card short of the cap refused; the record and the override written; the later steps (pins, label,
compose file, the record step's line); without the mark master's bytes; the host check outside the rehearsal.
tests/unit/test_rehearsal_real_servers_h89b.py (the slice, the Windows path): the slice accepted and held to its cap;
the pin by the slice's UUID; the probe's trust checks on a slice; the slice refusals; without the mark as on master;
the engine probe's slice form; the Windows path's passthrough and its refusals.

## Mutation pass

Planted one at a time in the source, the subject test files run, the source put back. The list and the count are in
the report to the lead.

## Findings

In `rehearsal-real-servers-h89b-2026-11-23/findings.json` (`--add-from` form).

### Files outside the card (bodies only)

`tools/engine_probe.py` (`--gpu-index` takes `N:M`; `host_facts` records a slice's id); `deploy/box-install.sh` (the
passthrough); `deploy/check_host.sh` (the gb10 stand-in branch); the dgpu48 lines of `deploy/install.sh` (cards 24-5,
24-6). Each change is a branch taken under the rehearsal mark only. The overlays (deploy/docker-compose.dgpu48.yml,
deploy/docker-compose.gb10.yml) are read, not changed.
