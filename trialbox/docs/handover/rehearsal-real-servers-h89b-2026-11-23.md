# H-89b: the rehearsal with real servers on the remaining shipped profiles, a rehearsal box only

**Reader:** the integrator and the people who build TrialBox

Lane H, 2026-11-23. HIGH-RISK: it loosens, under the rehearsal mark only, what the installer accepts. The owner's
ruling: every shipped profile is tested on the bench. The integrator's rulings for the remaining four (7088891993),
built in their order; this page follows H-89's (docs/handover/rehearsal-real-servers-h89-2026-11-22.md) and amends
D-1087 (no new decision number was given).

## Pull request body (draft)

Of the four profiles H-89 left closed, two are opened here: the 32 GB profile on one slice of a split card, and the
Windows host path. dgpu48 and gb10 stopped on an existing test (below): opening either changes what it asserts.

### The four rows

Steps 1 and 2 of H-89's page (reload the driver; the engine probe, as root, into the root-owned folder) come first
for every row; the probe is taken on the same card or slice the install names.

| Profile | Opened | Its memory cap on the bench | The bench's command form (step 3) | What the bench's row does NOT prove |
| --- | --- | --- | --- | --- |
| dgpu48 (48 GB) | stopped | - | - | the 48 GB class's older architecture (no FP8 or FP4 kernels) is not proved by the bench; and nothing yet, the profile is not opened |
| gb10 (128 GB unified) | stopped | - | - | "x86 stand-in: memory budget only": the class's Arm CPU and unified memory; and nothing yet, the profile is not opened |
| rtx5090 (32 GB), a split card's slice | yes | the profile's 0.81 of 32,607 MiB, scaled to the slice's own memory: on a slice of 89,600 MiB, 0.294 each (26,343 MiB, one server awake at a time) | `sudo python3 tools/engine_probe.py run --gpu-index 1:0 --out /var/lib/trialbox/rehearsal/engine-probe.json`, then `sudo deploy/install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu rtx5090 --gpu-index 1:0 --engine-probe /var/lib/trialbox/rehearsal/engine-probe.json --yes` | a 32 GB card's own memory bandwidth, its compute and the sleep swap's timing on it; the slice forms of nvidia-smi on the bench's card (H89b-01, H89b-02) |
| Windows host (WSL2) | yes, the passthrough | the named profile's, as on a Linux host | inside WSL2: `sudo deploy/box-install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu rtx5090 --gpu-index 1 --engine-probe /var/lib/trialbox/rehearsal/engine-probe.json` | not verified until a WSL2 host exists (ring 1): the WSL2 kernel, its GPU path and the Windows entry; box-install.ps1 passes none of the options (H89b-03) |

### 1. dgpu48: stopped

The ruling: open it for the rehearsal only, held to 48 GB, with the refusal byte-identical outside the mark. Stopped
before any change: tests/unit/test_rehearsal_real_servers_h89.py lines 1044-1050,
`test_the_profiles_not_opened_are_refused_by_name[dgpu48]`, asserts that under the mark
(`--rehearsal --rehearsal-real-servers --gpu dgpu48 --gpu-index 1 --engine-probe F`) the install exits 1 with "the
dgpu48 profile is not opened for a rehearsal with real servers". Opening the profile changes what that test asserts,
which needs the integrator's ruling. The lines to change once ruled: deploy/install.sh line 153 (the `dgpu48|gb10)`
refusal in the H-89 block) and line 295 (the profile case, cards 24-5 and 24-6, which must stay byte-identical
without the mark), and tools/rehearsal_real.py `OPENED` (a `budget_mib` of 49,140 and the dgpu48 compose file's
utilisations).

### 2. gb10: stopped

Stopped on the same test, `test_the_profiles_not_opened_are_refused_by_name[gb10]` (line 1044). Besides it:
deploy/check_host.sh line 49 refuses the rehearsal arguments with `--gpu gb10` (`[ "$GB10" = 0 ]`, lane H's block),
and deploy/docker-compose.gb10.yml line 40 pins every service to `platform: linux/arm64` (the `*arm` anchor; the
overlay is not lane H's file). The host check keeps FAILing "GB10 profile on x86_64" outside the rehearsal.

### 3. rtx5090 on a split card's slice: opened

* **The form.** `--gpu-index N:M` names slice M of card N, as `docker run --gpus device=N:M` names it. The 32 GB
  profile only: `--gpu rtxpro6000 --gpu-index 1:0` is refused (install.sh, and tools/rehearsal_real.py again). Refused
  too: a card that is not split (MIG off, or only pending), a slice the card does not list, and any other form
  (`1:`, `:0`, `1:0:0`, `all`). A whole card with MIG on is refused as before.
* **The memory query.** tools/rehearsal_real.py `slice_query`: the slice's UUID from `nvidia-smi -L`, its own free
  and total memory from `nvidia-smi -q -x -i N` (the MIG device's `fb_memory_usage`), read as text. The card check
  asks for the profile's cap scaled to the slice's total (tools/ballast.py `util_on`); a slice smaller than the cap
  (a 1g slice of 22,400 MiB) is refused for memory.
* **The probe.** `tools/engine_probe.py run --gpu-index N:M` runs on that slice and records the slice's own one-way
  id as `card_id` (and `gpu_index` "N:M"); the card's facts (name, driver, compute capability) are card N's. Every
  trust check of H-89 holds unchanged for the slice: card id (a probe of the whole card or of another slice is
  refused), host id, digest matched, age, owner and mode, read once and never through a link.
* **The pin.** deploy/site/rehearsal-real-servers.yml pins both servers to the slice by its own UUID
  (`device_ids: ["MIG-..."]`); the record says `slice_of_a_split_card: true` and `index: "N:M"`.

### 4. The Windows host path (WSL2): opened, not verified

deploy/box-install.sh takes `--rehearsal-real-servers`, `--gpu`, `--gpu-index` and `--engine-probe` with
`--rehearsal` only, and hands them on to install.sh after the plan's own flags (so the named profile wins over the
detected one). install.sh then judges them as on a Linux host. Not with `--prepare` or `--answers` (as before for a
rehearsal). Not verified until a WSL2 host exists (ring 1); the PowerShell entry passes none of them.

### Without the mark

* install.sh: `--gpu-index` and `--engine-probe` without `--rehearsal --rehearsal-real-servers` are refused at
  argument parsing as on master; the rtx5090 profile on a split card without the options runs as on master. The test
  holds master's exit code and last line, and compares the bytes with and without a passing slice probe and every
  rehearsal sign planted; run against master's own installer (b6e51e9f) in this session: the same in all six cases.
* box-install.sh: without the new options, the line handed to install.sh is master's, byte for byte (run against
  master's box-install.sh too). With them and without `--rehearsal`: refused, exit 2, nothing run (master said
  "unknown option": H89b-04).
* H-89's invariant `test_without_the_mark_the_three_refusals_are_byte_identical` passes untouched.

### Tests

tests/unit/test_rehearsal_real_servers_h89b.py: the slice accepted under the mark and held to its cap; the pin by
the slice's UUID; the probe's trust checks on a slice; the slice refusals; without the mark as on master; the engine
probe's slice form; the Windows path's passthrough, its form without the options, and its refusals.

## Mutation pass

Planted one at a time in the source, the H-89 and H-89b test files run, the source put back: see the report.

## Findings

In `rehearsal-real-servers-h89b-2026-11-23/findings.json` (`--add-from` form).

### Files outside the card (bodies only)

`tools/engine_probe.py` (`--gpu-index` takes `N:M`; `host_facts` records a slice's id), `deploy/box-install.sh`
(the passthrough, a rehearsal-only branch).
