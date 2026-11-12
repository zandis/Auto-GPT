# D-494 Plan v7.1: the owner's nine answers; the site machine is a Windows workstation with TrialBox in WSL2

- **Task:** none (the plan itself; `docs/plan/33-plan-v7.md`, TB-PLAN-07, version 7.1)
- **PR:** #325 (`claude/deep-review-2026-11-12`)
- **Date:** 2026-11-12
- **Status:** accepted; the owner's own answers of 2026-11-12 to the nine questions of plan v7 section 2
- **Builds on:** D-311 (no development gates), D-454 (plan v6.1, OD-10 to OD-16), D-421 (Windows with WSL2),
  D-466 (the box installer), D-434 (copy-assist), D-408 (host baseline)
- **Changes:** D-421 point 2, one line (a TPM-only BitLocker protector); D-408's "Ubuntu 24.04 as the host system
  until the owner answers" (the owner has answered)

## Context

Plan v7 asked the owner nine questions, Q1 to Q9, each with a default. The owner answered all nine on 2026-11-12.
Three answers change the plan: the hardware form, REDCap at go-live, and who provides the REDCap test instance.

## The answers, word for word, and the reading applied

| # | Question | The owner's answer | Reading |
| --- | --- | --- | --- |
| Q1 | The hardware form for both sites | "Windows workstation not Linux, because they may need to use the workstation" | The site machine is a Windows workstation that site staff also use as a desktop |
| Q2 | Order one reference box now | "Ok, give me ref" | Yes; the plan gives a reference configuration to quote |
| Q3 | The embedder in release 1 | "Yes" | The default holds: in, pinned |
| Q4 | REDCap at go-live | "Go live" | The API send is live at go-live, not copy-assist only |
| Q5 | A real REDCap test project | "You install redcap and run" | We install a local test instance and run R1 to R9 on it |
| Q6 | One lake source | "Ok" | The default holds: `omop` only |
| Q7 | Scope dated after go-live | "ok, but best all comprehensive" | The list stays after go-live; every item on it gets a dated wave |
| Q8 | The first CGMH data source | "Ready" | The CGRD read connection is ready on the owner's side |
| Q9 | Disk unlock on the box | "ok" | The default holds, in its Windows form |

## Decision

1. **The site machine (Q1).** One Windows workstation per site: Windows 11 Pro for Workstations or Enterprise, one
   RTX PRO 6000 Blackwell 96 GB. Site staff also use it as a desktop. TrialBox runs in WSL2 (Ubuntu 24.04). The
   bare Ubuntu box is the parked alternative, dated after go-live.
2. **Docker Engine inside WSL2, not Docker Desktop.** Docker Desktop needs a paid subscription for organisations
   over 250 staff or US$10M revenue, and hospitals are.
3. **The GPU** reaches the containers through the Windows NVIDIA driver and the NVIDIA Container Toolkit in WSL2.
   The Linux NVIDIA driver is never installed inside WSL2. The Windows driver's version is part of the serving
   record.
4. **The Linux stack is reused whole.** `deploy/box-install.sh`, `deploy/install.sh`, the first-run wizard and the
   compose set run unchanged inside WSL2. A Windows installer, `deploy/windows/box-install.ps1`, prepares Windows
   and WSL2 and then calls them. `deploy/windows` (T-210a, D-421) is kept and extended; plan v7's verdict to drop it
   from the bundle is reversed.
5. **The card is shared with a desktop user, by a stated rule.** While TrialBox serves, a desktop user may run
   office work, a browser, video calls and the console, and may not run another compute job on the card. The rule
   rests on the measured free memory (about 33 of 95.6 GiB) and is corrected from the measurement P-11. Desktop
   staff use standard accounts; the box owner holds the administrator account and the WSL2 distribution.
6. **Unlock (Q9).** BitLocker on every drive, opened by the TPM, the recovery key printed and held by the box
   owner. WSL2's virtual disk lives on the BitLocker data drive. D-421 point 2 refused a TPM-only protector on the
   system drive; for the box that line becomes a setting, `bitlocker_unlock`: `tpm` (the default: the workstation
   returns after a restart with nobody there) or `tpm_pin` (a person at every restart). The other lines of D-421
   stand: hibernation off, `swap=0`, the page file on encrypted drives only, Remote Desktop off.
7. **No capacity claim for WSL2 yet.** Every figure so far is from Linux. The first WSL2 figure comes from the
   reference workstation (plan section 7.2, P-10 to P-15). The memory and processor share of WSL2 is computed from
   the installed hardware and one declared setting, the desktop's share (OD-10). The hardware order of 2026-12-18
   does not wait for the WSL2 figure; that figure can change the capacity statement, not the order.
8. **The reference workstation (Q2)** is quoted to plan section 2.2 by local resellers in Taiwan and Japan. The
   plan names no price.
9. **REDCap (Q4, Q5).** The API send is live at go-live. EDC-001 to EDC-008 are on the go-live path. We run our
   own REDCap test instance and the tests R1 to R9 on it. REDCap can be downloaded only by a consortium partner
   with its login, so the owner, or the institution's REDCap administrator, supplies the release zip once, at the
   path the installer reads. The zip is never committed, never in a bundle, never in CI. Copy-assist (D-434) stays
   as the fallback per study: the per-study switch is unchanged.
10. **After go-live (Q7).** Every item plan v7 froze has a dated wave (plan section 3.3, waves 6 to 11). None is
    left undated.
11. **CGRD (Q8).** T-731, the CGRD connector only, starts in wave 0. Nothing read from the connection enters the
    repository (synthetic data only).
12. **Unchanged (Q3, Q6):** the embedder in, pinned; one lake source, `omop`.

## Consequences

- New cards: NEW-WIN-1 to NEW-WIN-9 and NEW-EDC-0 (plan sections 2.3 and 2.4). About 36 session-days are added;
  the plan now needs four sessions in every wave.
- Plan section 4: the reference workstation's order moves to 2026-11-27 and its install to 2027-02-19; new steps
  2a, 8a, 10a, 10b, 11a. The go-live dates (CGMH 2027-04-28, Japan 2027-05-13) and the site order of 2026-12-18
  are held.
- A stolen workstation with a TPM-only protector starts to a running stack. What still stands between it and the
  data: the Windows sign-in and the console's sign-in. A site that does not
  accept this sets `tpm_pin` and accepts a person at every restart.
- WSL2 has no TPM device, so the site keys cannot be sealed as on Linux. Until NEW-WIN-8 lands, the box plan falls
  back to a passphrase typed after every restart, and an unattended restart does not bring the stack back.

## Open

- Whether the two NVMe drives are 4 TB each or 4 TB together; the plan asks for 4 TB or more each.
- Which REDCap version each site runs; the zip must be that version.
- Whether the owner's nine answers also accept plan v7 as a whole. The plan's status stays "proposed" until the
  owner says so.
