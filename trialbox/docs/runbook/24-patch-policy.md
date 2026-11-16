# 24. Patch policy

**Reader:** hospital IT and Aimedics.

*T-635, D-390. Who patches what, how fast, and how a patch is checked. The split is the IT pack's (A.6 and A.7): the
hospital patches the host, Aimedics patches TrialBox.*

**Drill (T-213b):** `test_runbook_24_patch_window` (Docker drill: a host package update in a window by these steps;
before and after, `doctor` has no FAIL and the pair canary passes; a held driver package is not upgraded).

## The host system

*Default until the owner answers (TB-DR-09 Q1):* the Japan box runs a bare Ubuntu LTS (or the Spark's own Ubuntu-based
system on that form). Windows with WSL2 only when the hospital asks for it in writing; this page then applies to the
WSL2 Linux and the hospital's own Windows patching covers the rest. CGMH runs TrialBox in containers on its shared
server: the hospital patches the server and the platform, and only the TrialBox images row below applies (§17).

## Who, what, how fast

| What | Who | Normal | Critical (known exploited, or CVSS 9 and above, reachable on the box) |
| --- | --- | --- | --- |
| host OS security updates | hospital IT | monthly, in the hospital's announced window | within 14 days |
| container runtime (Docker) | hospital IT, with Aimedics told first | with the OS, after the canary passes on the acceptance box | within 14 days |
| GPU driver and CUDA | Aimedics decides, hospital IT applies | held (D-373 driver hold); changed only by a change request (`docs/validation/change-control.md`) | change request within 14 days |
| TrialBox images, models, rulesets | Aimedics, by signed release (§5) | each release | a security release within 14 days of a fix being available |
| firmware (BIOS, BMC, disk) | hospital IT, with the supplier | yearly, or as the supplier says | as the supplier says |

The box has no route to the internet (A.3). OS packages come through the hospital's own mirror or update server, or
as an offline bundle on media: an OS patch bundle from Aimedics is applied with `tools/apply_update.sh ospatch
<bundle>` (T-634, D-408; SECURITY §1).

## A patch window, step by step

1. Hospital IT tells the site administrator. No TrialBox update in the same window.
2. Before: `trialbox doctor --env-file deploy/.env` and a backup by hand (`python3 -m tools.trialbox backup`).
3. Hold the driver: `apt-mark showhold` lists the NVIDIA packages; never `apt full-upgrade` past the hold.
4. Apply the OS updates. Reboot if the kernel or Docker changed: `systemctl stop trialbox` first.
5. After: the egress unit and the stack start (D-377); `trialbox doctor` has no FAIL; run the pair canary (`trialbox
   selftest` on the box). A canary that fails after a patch: roll the patch back with hospital IT and open a P1
   ticket (§21).
6. Write the window, the packages and the result in the hospital's change record.

## What Aimedics watches

Aimedics follows the security notices of the base images, Python packages and model servers the release pins
(`deploy/images.lock`, the supply-chain job of `.github/workflows/trialbox-supply-chain.yml`), and the host
distribution's notices for the packages TrialBox needs (Docker, the NVIDIA driver). A notice that touches a site is
sent to both sites' tier 1 within 2 working days, with what to do.
