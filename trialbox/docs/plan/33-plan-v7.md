# TB-PLAN-07 Plan v7: the re-planned task list after the deep review of 2026-11-12

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-07 |
| Date | 2026-11-12 |
| Version | 7.1 (2026-11-12): the owner's nine answers folded in (D-494) |
| Owner | Changfu Kuo (Aimedics) |
| Status | **Proposed.** It replaces the task lists and the order of work of `28-master-plan-v6.md` (TB-PLAN-06) and `31-master-plan-v6.1-addendum.md` (TB-PLAN-06.1) once the owner accepts it. The owner decisions OD-10 to OD-21 and D-311 are unchanged and win over this file. The nine questions of section 2 were answered by the owner on 2026-11-12 (`docs/decisions/D-494-plan-v7-owner-answers-windows-box.md`). |
| Basis | The deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/` (TB-DR2-00 to TB-DR2-13), on `master` at `514ae9b`. Finding ids below (PLAN-, ARCH-, ENG-, JRN-, UX-, LLM-, PERF-, DIN-, LIFE-, EDC-, STD-, OPS-, HW-) are that review's. |
| Dates held | CGMH go-live **Wed 2027-04-28**. Japan go-live **Thu 2027-05-13**. |

Rules kept in this plan: no IRB, COI or steward-approval step; no development gate or sign-off (D-311); no fixed
limit that is not derived from hardware, measured speed or data size, or declared as a setting with a reason
(OD-10). Milestones below are build dates, not gates. Sizes: S up to 1 day, M 2 to 4 days, L 1 to 2 weeks of one
session. Card ids `T-nnn` are those of TB-PLAN-06 and 06.1; `NEW-<AREA>-n` are named in the area file of the review
and get a `T-` number when started; where a `NEW-` id here and the area file differ, the finding id beside it rules.
`NEW-WIN-n` and `NEW-EDC-0` are named in this file (v7.1, sections 2.3 and 2.4).

## 1. What changed since v6.1, in ten lines

1. v6 and v6.1 hold 237 cards: 149 are done by code and test, 10 are half done, 78 are missing. At 3 to 4 parallel
   sessions the remaining work is about 285 session-days against 210 to 280 available to 2027-02-26 (PLAN-003). The
   plan does not fit unless scope is cut. Section 3 cuts about 85 session-days.
2. The build that ships has never run on a GPU (HW-001). G1 measured hand-started model servers, one call at a time
   (HW-006, PERF-007), on a synthetic hospital about 16 times thinner than a real one (PERF-002). No throughput,
   capacity or accuracy claim rests on the product yet.
3. A PRODUCTION box cannot start: the embed service has no embedder in any image (ENG-003, HW-002), the installer
   stops at the backup step (OPS-003), and there is no path to a qualified model pair on a site box (HW-003, LLM-005).
4. One model's answer still excludes a patient on four paths (PLAN-001), and the excerpt builder can show the models
   a family-history fact under the past-history heading (LLM-001).
5. Real feeds will break quietly: a Republic-of-China date is read as the year 1150 (DIN-001; fix in PR #323),
   ICD-9-CM years in Taiwan are tagged ICD-10-CM (STD-001), common Japanese unit spellings are not read (STD-004,
   DIN-009), unmapped codes vanish uncounted (DIN-006).
6. The night does not scale or survive: 0.33 MB of memory per patient at ingest (PERF-001), a full reload every
   night (PERF-006), a restart re-runs jobs from zero (ARCH-001), and a restart during ingest leaves the night
   half-published (ARCH-002, PERF-008).
7. The merge gate does not gate: master is unprotected and the nightly end-to-end jobs have been red since 11-10
   (ENG-001, ENG-002).
8. REDCap write-back has never met a real REDCap, and the simulator accepts what REDCap refuses (EDC-001); on a
   repeating instrument it writes into a person's own instance (EDC-002).
9. A new box is seeded with eight rulesets already approved and scheduled (LIFE-001), while a new study made by a
   person cannot get its first approval in the console at all (JRN-001).
10. Much is sound and stays: the unit suite (3,541 of 3,570 reached tests pass; failures are this machine's missing
    jars), the unit conversion fix, the pair's "unknown on any fault" rule, the audit hash chain, accessibility and
    the three language catalogues.

## 2. The owner's nine decisions (asked in v7, answered 2026-11-12, D-494)

| # | Decision | Default v7 assumed | The owner's answer | What the plan does |
| --- | --- | --- | --- | --- |
| Q1 | The hardware form for both sites | One dedicated box, Ubuntu 24.04, one RTX PRO 6000 (96 GB) | "Windows workstation not Linux, because they may need to use the workstation" | **Changed.** One Windows workstation per site (Windows 11 Pro for Workstations or Enterprise), one RTX PRO 6000 Blackwell 96 GB. Site staff also use it as a desktop. TrialBox runs in WSL2 (Ubuntu 24.04) with Docker Engine inside WSL2. The bare Ubuntu box is the parked alternative. Sections 2.2 and 2.3. |
| Q2 | Order one reference box now | Yes, this week | "Ok, give me ref" | **Yes.** The reference configuration is section 2.2. Quotes are asked from local resellers in Taiwan and Japan. This plan names no price. |
| Q3 | The embedder in release 1 | In, pinned (bge-m3), in the lake image; if its PRODUCTION start test is not green by 2026-12-04, release 1 ships without note retrieval by embedding and says so | "Yes" | Default holds. |
| Q4 | REDCap at go-live | Copy-assist at both sites; the API send later | "Go live" | **Changed.** The API send to REDCap is live at go-live. EDC-001 to EDC-008 are on the go-live path. Copy-assist stays as the fallback per study. Section 2.4. |
| Q5 | A real REDCap test project | The owner provides one per site | "You install redcap and run" | **Changed.** We install a local REDCap test instance and run R1 to R9 on it (NEW-EDC-0). The owner, or the institution's REDCap administrator, supplies the release zip once. Section 2.4. |
| Q6 | One lake source | `omop`; the legacy flatten, the nightly HAPI load and CQL-on-the-box are removed (CQL stays as a CI differential) | "Ok" | Default holds. |
| Q7 | Scope dated after go-live | The list of section 3.2 | "ok, but best all comprehensive" | The list of section 3.2 stays after go-live. **Every item on it now has a dated wave** (section 3.3). None is left undated. |
| Q8 | The first CGMH data source | The CGRD read connection only (T-731, one connector) | "Ready" | The CGRD read connection is ready on the owner's side. T-731 starts in wave 0 and wave 1. The other four connectors are dated in section 3.3. |
| Q9 | Disk unlock on the box | TPM-sealed key with a printed recovery copy held by the box owner | "ok" | Default holds, in its Windows form: BitLocker with the TPM, the printed recovery key held by the box owner, WSL2's virtual disk on the BitLocker volume (NEW-WIN-8). |

### 2.1 What the answers change, in eight lines

1. The site machine is a Windows workstation that staff also use. TrialBox is a guest on it, in WSL2.
2. The Linux stack is reused whole inside WSL2. A Windows installer and eight more Windows cards are added
   (section 2.3).
3. No WSL2 number exists. Every throughput and capacity figure so far is from Linux. The first WSL2 figure comes
   from the reference workstation (section 7.2, P-10 to P-15).
4. The hardware order does not wait for that figure. The workstation is the same class under either system. What
   the figure can change is the capacity statement, not the order.
5. The REDCap API send moves from "after go-live" onto the go-live path, with a test instance we run ourselves.
6. The CGRD connector starts five weeks earlier. Mapping defects on real data show in December, not in March.
7. Added work: about 30 session-days for the Windows form, 3 for the REDCap instance, 6 for the send path, less
   about 3 for the Linux media and `box-prepare.sh` that the parked form keeps. Net about 36. The work left was
   about 200 session-days after the cuts of section 3; it is now about 236, against 210 to 280 available. It fits
   at four sessions. It does not fit at three.
8. The go-live dates are held. The reference workstation's order moves one week, to 2026-11-27, for the quotes.

### 2.2 The reference workstation (Q2): what to ask the resellers to quote

One machine now, the same configuration for each site later. Quotes come from local resellers in Taiwan and Japan.
This plan invents no price. Each quote must state the delivery date; that date replaces the 9 to 13 weeks assumed
in section 4.

| Part | Ask for | Why |
| --- | --- | --- |
| Form | A tower workstation from a maker that sells the card fitted and supported. Examples to quote: Dell Pro Max Tower T2, HP Z8 Fury G5, Lenovo ThinkStation P5 or PX | One supplier for the machine and the card; ECC memory; a board with a TPM |
| Graphics card | One NVIDIA RTX PRO 6000 Blackwell, 96 GB: the Workstation Edition (600 W) or the Max-Q edition (300 W). Not the Server Edition (no fan of its own). MIG off | The only card measured (62.6 of 95.6 GiB used by the pair on 2026-11-11). The Max-Q is quieter beside staff; its speed against the 600 W card is measured by P-2 |
| Processor | 16 cores or more | WSL2 gets a share of the cores in `.wslconfig`; the desktop user keeps the rest |
| Memory | 192 to 256 GB, ECC | WSL2 gets a share set in `.wslconfig` and the desktop user needs the rest. The share is computed from the installed memory (NEW-WIN-3), not written here |
| Drives | Two NVMe drives of 4 TB or more: one holds Windows and the desktop user's files, the other holds WSL2's virtual disk (lake, models, databases) | The data never shares a drive with the desktop's files; both drives under BitLocker |
| Security chip | TPM 2.0, on | BitLocker (Q9) |
| Power supply | 1,000 W or more with the 600 W card | The whole machine is near 900 W at full load |
| Power in the room | A UPS sized for the whole machine; a circuit that carries it at 100 V (Japan) or 110 V (Taiwan) | A power cut during a night job (P-4) |
| System | Windows 11 Pro for Workstations or Enterprise, in the site's language | WSL2, BitLocker, update policy |
| Network | Wired Ethernet | The console is served to the site's own network |
| Backup target | A second machine's share or an outside drive, not inside the workstation | Section 2.3, NEW-WIN-7 |

The 600 W card under a night batch gives off about 3,000 BTU an hour and is audible. The workstation now sits where
staff sit. The night batch runs when they are away; the day's load (chat, one patient at a time) is light. P-4
records the noise and heat at a desk.

### 2.3 The Windows form (Q1, Q9)

Rules of the form:

1. Windows 11 Pro for Workstations or Enterprise. TrialBox runs in WSL2, Ubuntu 24.04, with systemd on.
2. Docker Engine is installed inside WSL2. Docker Desktop is not used: it needs a paid subscription for
   organisations over 250 staff or US$10M revenue, and hospitals are.
3. The GPU reaches the containers through the Windows NVIDIA driver and the NVIDIA Container Toolkit in WSL2. The
   Linux NVIDIA driver is never installed inside WSL2. The Windows driver's version is part of the serving record.
4. The lake, the models and the databases live in WSL2's virtual disk on the BitLocker data drive. They never live
   under `/mnt/<drive>`, the slow shared path.
5. The box owner holds the Windows administrator account and the WSL2 distribution. Desktop staff sign in with
   standard accounts. A standard account cannot stop another account's WSL2 or read its disk file.
6. **What a desktop user may run while TrialBox serves:** office work, a browser, video calls, the TrialBox
   console. **What a desktop user may not run:** another model server, training, rendering, a game, or any other
   compute job on the card. The reason is measured: the pair holds 62.6 of 95.6 GiB, about 33 GiB is free, and the
   display and the desktop take from that. P-11 measures it and the rule is corrected from P-11. A health line
   reads, on the Windows side, the card memory held by programs outside TrialBox and turns red when the models'
   share is at risk (NEW-WIN-6).
7. A restart at any hour is safe. The stack returns with nobody signed in, and a running job resumes (T-689, G-9,
   P-13). Sleep and hibernation stay off (D-421).
8. BitLocker on every drive, opened by the TPM, so the workstation returns after a restart with nobody there. The
   recovery key is printed and held by the box owner. This changes one line of D-421, which refused a TPM-only
   protector; a TPM with a PIN stays as a setting for a site that wants a person at every restart (NEW-WIN-8).

What is reused inside WSL2 and what is replaced:

| Piece | Verdict in the Windows form |
| --- | --- |
| `deploy/box-install.sh`, `deploy/install.sh`, the first-run wizard, `tools/box` (T-729, D-466) | **Reused unchanged.** `box-install.ps1` calls `box-install.sh` inside WSL2 |
| The compose set `docker-compose.yml + secrets + rtxpro6000 + identity + box` | **Reused unchanged** |
| The systemd units and timers (`trialbox-ops.timer`, `trialbox-firstrun.service`, the backup schedule, the watchdog) | **Reused**; they need systemd on in `/etc/wsl.conf` |
| `deploy/check_host.sh` | **Reused**; on a WSL2 kernel it runs the Windows checks by itself (D-421) |
| `deploy/windows/` (`host_facts.ps1`, `wsl2_policy.py`, `preflight.ps1`, `register_keepalive.ps1`, `wslconfig.example`; T-210a, D-421) | **Reused and extended.** v7 dropped it from the bundle; that verdict is reversed (section 3.1) |
| `docs/handover/OFFLINE-MEDIA.md` (the Windows layout), `docs/handover/WINDOWS-INSTALL-CHECKLIST.md` | **Reused, rewritten to the box form** (the owner at the keyboard, no tiers): NEW-WIN-9 |
| `tools/apply_update.sh` and the offline Ubuntu patch bundles | **Reused** for the Ubuntu packages inside WSL2; Windows itself is patched by Windows Update (NEW-WIN-5) |
| The backup tool and the restore drill (T-691, T-213b) | **Reused**; the target paths are new (NEW-WIN-7) |
| `box-prepare.sh` (not yet written) and the Linux media with the Linux NVIDIA driver (HW-010, OPS-005, OPS-006) | **Replaced** by `box-install.ps1` and the Windows media. Kept for the parked Ubuntu form (section 3.3) |
| Disk encryption by LUKS, `deploy/hardening/luks_policy.py`, `deploy/hardening/disk-unlock.sh` (D-408) | **Replaced** by BitLocker (NEW-WIN-8) |
| The site keys sealed to a Linux TPM device (`deploy/hardening/seal_keys.sh`, KEK `tpm`) | **Replaced.** WSL2 has no TPM device. Today the box plan falls back to a passphrase typed after every restart, which breaks rule 7. NEW-WIN-8 adds a Windows-held key |
| The input firewall at the network edge (`deploy/hardening/apply.sh`, nftables) | **Replaced at the edge** by Windows Firewall rules (NEW-WIN-4); kept inside WSL2 |
| The one-time first-run code on the box's own screen (`/etc/issue.d`) | **Replaced**: the installer's own window shows it (NEW-WIN-1) |
| The locked-box page of T-730 | **Replaced** by a handbook page for the BitLocker recovery screen |

The Windows cards. A sixth lane, W, owns `deploy/windows` (section 5).

| Card | What | Size | Wave |
| --- | --- | --- | --- |
| **NEW-WIN-1** | `deploy/windows/box-install.ps1`, the installer for Windows. From the offline media it checks the edition and virtualisation, enables WSL2, imports the Ubuntu 24.04 image onto the data drive, turns systemd on, installs Docker Engine and the NVIDIA Container Toolkit inside WSL2, proves a container sees the card, refuses a Linux NVIDIA driver, then runs `box-install.sh` inside WSL2 and shows the first-run code in its own window. It continues by itself after the restart that enabling WSL2 needs. Accepted by a parse and unit job for the PowerShell in CI and a full run on a Windows 11 PC with an NVIDIA card (P-0) | L | 1 to 2 |
| **NEW-WIN-2** | Start without a person: the task at boot of `register_keepalive.ps1` starts WSL2, and systemd inside starts Docker and the stack. Test: restart, nobody signs in, the console answers from another PC | S | 2 |
| **NEW-WIN-3** | `.wslconfig` written by `tools/box plan` from the installed memory and cores and one declared setting, the desktop's share (OD-10: no number written in the installer). `swap=0`. The virtual disk's size limit raised to the data drive's size. A `doctor` line that the sum of the compose memory caps and the model servers' measured host memory fits WSL2's share, and a test that the models load and answer under it | M | 2 |
| **NEW-WIN-8** | Unlock: BitLocker with the TPM on every drive, the recovery key printed for the box owner, a `bitlocker_unlock` setting (`tpm`, or `tpm_pin` as D-421 had it) that `wsl2_policy.py` reads. A key back end for the site keys held by Windows and handed to WSL2 by the boot task; the mechanism is chosen by a test under that task's own sign-in type, because a task that stores no password may not open a user's protected store | M | 2 |
| **NEW-WIN-4** | The console on the site's network: WSL2 mirrored networking with a firewall rule for the console port only, or a port proxy that the boot task refreshes; the one that passes P-14 is kept. Windows Firewall admits the site's own network only. The TLS name and the network sheet follow | M | 3 |
| **NEW-WIN-5** | Windows Update: an update window as a declared setting, placed outside the night from the night's measured length; no restart outside it; drivers not taken from Windows Update, so the NVIDIA driver stays the measured one; the driver and WSL2 versions in `doctor`, red when they differ from the serving record. Standard users cannot shut the workstation down | M | 3 |
| **NEW-WIN-6** | The card shared with the desktop: the health line of rule 6; the driver set not to spill model memory into system memory; standard accounts for desktop staff; the rule in the handbook in en, ja, zh-TW | M | 3 |
| **NEW-WIN-7** | Backup and restore from WSL2: the target is outside the virtual disk (the hospital's share mounted inside WSL2, or an outside BitLocker drive); the step limits come from the measured speed of that path (`TB_BACKUP_MIN_MBPS`, D-455); restore on a second machine is `box-install.ps1` then the restore; an export of the WSL2 distribution is not a backup | M | 3 |
| **NEW-WIN-9** | The Windows media and the two handover documents rewritten to the box form; the owner's handbook (T-735) written for Windows | M | 3 |

### 2.4 REDCap: our own test instance, and the send live at go-live (Q4, Q5)

REDCap is not open source. Only a consortium partner can download it, with its own login. So one thing comes from
the owner, or from the institution's REDCap administrator, once: **the release zip**, in the version the sites run.
It is placed at the path the installer reads (the setting `TB_REDCAP_ZIP`, by default a file under
`deploy/site/redcap/`, a folder the repository ignores). The zip is never committed, never in a bundle and never in
CI. The instance runs under the supplying institution's licence. Everything else is ours.

| Card | What | Size | Wave |
| --- | --- | --- | --- |
| **NEW-EDC-0** | A local REDCap test instance: a compose file with PHP and MariaDB that unpacks the supplied zip, installs REDCap, builds the test project from `tests/edc_kit.py` and the repeating and longitudinal set (one checkbox, one `date_dmy`, one `number_1dp` field), makes the four tokens (export and import; export only; a user bound to a DAG; an expired user) and a user who may lock a form. Synthetic data only. One command runs R1 to R9 and writes the record | M | 1 |
| NEW-EDC-1 | The conformance run on that instance, recorded as cassettes that CI replays; the simulator made as strict (EDC-001) | M | 2 |
| EDC-008, EDC-007, EDC-002, EDC-003 | A true attempt ledger; per-record fallback and a read of the lock before the write; whole-instance writes on a repeating instrument; checkbox columns | S, S, S, M | 3 |
| EDC-005, EDC-004, EDC-006 | The person's correction read back (after EDC-008); the source-changed flag; retire a removed item | M, M, S | 4 |
| P-6 | R1 to R9 pass on the repaired code on our instance; then once on each site's own REDCap test project in wave 5, because a site's version and settings may differ | run | 4, 5 |

The switch per study stays as built (D-434): `on` sends through the API, `copy` is copy-assist and writes nothing
to REDCap. A study whose REDCap project fails R1 to R9 at its site stays on `copy`. `erase_hidden` stays off until
R6 shows REDCap's branching equal to ours. EDC-011, EDC-012 and EDC-018 are dated in section 3.3.

## 3. What is dropped, frozen or merged

### 3.1 Dropped or removed from the product

| Item | Verdict | Evidence |
| --- | --- | --- |
| Legacy lake source (flatten) after the flip to `omop` | drop | PLAN-008, STD-006 |
| HAPI FHIR server and the 105 JVM jars on the box; the nightly FHIR load | off the box; kept as CI jobs (T-306 widened, NEW-PERF-6) | STD-010, ARCH-015 |
| CQL as a run-time engine | CI differential only (T-711) | STD-010 |
| The v1 evaluation path as a second engine | removed at the end of T-709/T-710 (NAV and the re-check call the cascade) | ENG §5, ARCH §5.4 |
| `services/deliverables` | drop or move under `tools/` | PLAN §5.1 |
| `tracestore`, `registry` as services | merge into the gateway | PLAN §5.1 |
| `embed-service` as its own container when it runs the lake's image | merge into the data process | ARCH §5.10 |
| `StepStore`/`Dispatcher` (schema `wf`) | use it for T-689, or delete it; no third option | ARCH-004 |
| `deploy/topology_a`, `deploy/pgbackrest/Dockerfile`, `site_params.yaml`, the second `settings.example.yaml` | drop | OPS §5, ARCH-013 |
| `deploy/windows` | **kept and extended** (v7.1: v7 dropped it from the bundle; the site machine is now Windows, section 2.3) | D-494 |
| `tools/` in every service image (68,000 lines) | out of the image | ARCH-012 |
| Traceability CSV (273 rows, all "planned") and its CI job | drop now; regenerated from tests (NEW-STD-3) in wave 7 (section 3.3) | STD-003, PLAN-016 |
| Root Auto-GPT tree (`autogpt/`, root `Dockerfile`, `requirements.txt`) | remove from the repository | ENG §5 |
| The steps of TB-PLAN-06 that D-311 and the owner's rules struck (IRB, counsel, sign-off, G4 to G6, GP-0 to GP-2) | delete from the text | PLAN-010 |

### 3.2 Frozen: stays as built, no new card before go-live; each item is dated in section 3.3

Opportunity feed and hub (T-741 to T-745); the phone app and use from outside (T-732, T-733); the profile and
research cards (T-203c, T-311a/b, T-312, T-313, T-314, T-316a/c); the patient twin's new layers; mail intake;
`channels`; four of the five connectors of T-731; visits and deviations beyond what exists; more close-out;
the data core's own capture as an EDC of record (it stays a working aid; its trail is made append-only, EDC-009);
the bare Ubuntu box form (v7.1; its installer stays in use inside WSL2); Kubernetes (`deploy/platform`),
shared-quota, two-device, RTX 5090, GB10 forms (out of the per-PR CI as well);
the model bake-off tools and the 19 MB of evaluation corpora (moved to the fetch cache); T-711; T-717, T-718, T-721
until T-715 is in refuse mode; T-697, T-698, T-700 (except the `list_jobs(limit=500)` calls), T-701.

### 3.3 After go-live: every frozen item has a wave (Q7)

The owner wants the coverage whole. So nothing of section 3.2 is left undated. Each wave is four weeks at the same
four sessions. These are build dates, not gates. A fix for a live site comes before any of them. An item with an
open pull request lands when it is green; it does not wait for its wave.

| Wave | Dates | Items |
| --- | --- | --- |
| 6. Trust, capacity and EDC, the rest | 2027-05-17 to 2027-06-11 | T-717 (#332), T-718 (with `datacore` after `edc`), T-721; T-697, T-698, T-700 (the rest), T-701; T-711 (#319); EDC-011, EDC-012, EDC-018 and the Medium and Low rows of the EDC table; `erase_hidden` on, if R6 was equal |
| 7. Data sources | 2027-06-14 to 2027-07-09 | The other four connectors of T-731 (a REDCap project as a read source on the cassettes of NEW-EDC-1, the team's own database, an EMR feed, uploaded sheets); NEW-DIN-2 (a FHIR-fed site); mail intake; `channels`; the traceability table regenerated from tests (NEW-STD-3) |
| 8. Trial conduct | 2027-07-12 to 2027-08-06 | Visits and deviations beyond what exists; the rest of close-out; the data core's own capture: made an EDC of record, or kept a working aid, decided here on what the first studies used |
| 9. Profile and research | 2027-08-09 to 2027-09-03 | T-203c, T-311a, T-311b, T-312, T-313, T-314, T-316a, T-316c; the patient twin's new layers |
| 10. Outside the hospital | 2027-09-06 to 2027-10-01 | T-732 (use from outside as a site setting), T-733 (the phone app); the opportunity feed and hub, T-741 to T-745 |
| 11. Other hardware forms and tools | 2027-10-04 to 2027-10-29 | The bare Ubuntu box (`box-prepare.sh`, the Linux media, LUKS unlock: HW-010, OPS-005, OPS-006); DGX Spark (GB10); RTX 5090; two-device; shared quota; Kubernetes. Each goes back into the per-PR CI when it has a measured serving record on its own hardware. The model bake-off tools and the evaluation corpora |

## 4. The merged critical path

Working days from 2026-11-13 (Taiwan calendar): 40 to 2027-01-08, 70 to 2027-02-26, 110 to 2027-04-28, 118 to
2027-05-13.

| # | Step | Cards and findings | Ends | Depends on |
| --- | --- | --- | --- | --- |
| 1 | The gate gates: branch protection, nightly green, unit job in shards | T-007, ENG-001, ENG-002, T-747 (#306), T-653 | Fri 2026-11-20 | — |
| 2 | Hardware decided (D-494): a Windows workstation. Quotes asked from resellers in Taiwan and Japan on Fri 2026-11-13 to section 2.2; **reference workstation ordered** | Q1, Q2, NEW-PLAN-2 | Fri 2026-11-27 (v7: 11-20) | owner |
| 2a | The REDCap release zip from the owner; our test instance up with its project and four tokens | Q5, NEW-EDC-0 | zip Fri 2026-11-27; instance Fri 2026-12-04 | owner |
| 3 | One model never excludes; one decision function; one excerpt builder that keeps headings and negation | T-707 (#307), T-708 (#311), T-709, T-710, NEW-LLM-1 | Fri 2026-11-27 | — |
| 4 | The screening job survives an outage and a restart | T-689 (#309), ARCH-001, NEW-ARCH-1 | Fri 2026-11-27 | — |
| 5 | A PRODUCTION box starts and holds a qualified pair: embedder image, installer to the wizard, vendor qualification record shipped and promoted at install, chat template pinned | ENG-003, HW-002, HW-003, HW-004, HW-005, OPS-003, OPS-004, LLM-005, LLM-007 | Fri 2026-12-04 | Q3 |
| 6 | The measuring harness measures the product: concurrency from the serving record, calls/s, tokens/s, p50/p95, GPU utilisation; dense synthetic profile | NEW-PERF-1, HW-006, PERF-002, T-687 | Fri 2026-12-04 | — |
| 7 | **The product-on-GPU run** (replaces "G1 attempt 3"), on the Linux VM: it proves the installer that runs inside WSL2 and gives the Linux baseline for P-10. Real bundle, `box-install.sh`, record, canary, 50,000-patient screen at 1/4/8/16/32 in flight, power cycle | section 7.1, tests G-1 to G-9 | Fri 2026-12-11 | 3 to 6 |
| 8 | Capacity statement (the Linux figure, marked "not yet the site's form") and hardware note; **both site workstations ordered** to section 2.2 | T-667, T-734 | **Fri 2026-12-18** | 7 |
| 8a | The Windows form built and rehearsed on a Windows 11 PC with an NVIDIA card, before the reference workstation arrives: the installer, start without a person, `.wslconfig`, unlock and keys | NEW-WIN-1, NEW-WIN-2, NEW-WIN-3, NEW-WIN-8, P-0 | Fri 2027-01-08 | 5 |
| 9 | `publish(night)`; ingest and rebuild in streams; nightly deltas | T-723 (#314), T-692 (#304), T-726, PERF-001, PERF-006 | Fri 2027-01-15 | 4 |
| 10a | The CGRD connector reads the real connection (ready, Q8); its mapping check runs on the owner's side; the date, code and unit repairs for real feeds | T-731 (CGRD only), section 5 lane E waves 0 to 2, P-7 (CGMH part) | Fri 2026-12-18 | — |
| 10b | The first whole night from CGRD through `publish(night)` | T-731, T-723 | Fri 2027-01-22 | 9, 10a |
| 11 | Reference workstation delivered (9 weeks P50: 2027-01-29; 13 weeks P90: 2027-02-26), installed from factory Windows by `box-install.ps1` and the handbook; **WSL2 measured against Linux** (P-10 to P-15); update, backup, restore-on-a-second-machine, restart and power-cut drills | T-730 (split in five), T-213b, NEW-OPS-1, NEW-WIN-4 to NEW-WIN-9, HW-012 | Fri 2027-02-19 (v7: 01-29) | 2, 5, 8a |
| 11a | The REDCap API send repaired against our instance: conformance cassettes and a strict simulator, then the ledger, per-record fallback, whole-instance writes, checkbox columns | NEW-EDC-1 (Fri 2026-12-18), EDC-008, EDC-007, EDC-002, EDC-003 | Fri 2027-01-29 | 2a |
| 12 | The acting person is a fact the callee checks; opt-out erasure in every store; generations | T-712 (#308), T-714 (#312), T-715, T-716, T-719, T-206b (#278), T-727, T-728 (#313), T-724, T-725 | Fri 2027-02-12 | 9 |
| 13 | Feature complete: lifecycle repairs, outputs in three languages, the EDC send and copy-assist repairs with R1 to R9 passed on our instance (EDC-004, EDC-005, EDC-006, P-6), accuracy set per language measured on the workstation, the capacity statement restated for WSL2 from P-10 | sections 5 and 7 | **Fri 2027-02-26** | 3 to 12 |
| 14 | Site workstations delivered (9 weeks P50: 2027-02-19; 13 weeks P90: 2027-03-19), installed by `box-install.ps1`, connected, mapping content done on a real extract, first real night; R1 to R9 once on each site's own REDCap test project | T-315b, T-315c, T-735, NEW-DIN-17 | CGMH Fri 2027-03-26; Japan Fri 2027-04-09 | 8, 10, 11 |
| 15 | Real-data dry run, the journeys of T-315a on the site's box, training with the guides in zh-TW and ja, acceptance | T-317, `docs/runbook/06-go-live-acceptance.md` | CGMH Fri 2027-04-16; Japan Fri 2027-04-30 | 14 |
| 16 | Go-live | | CGMH Wed 2027-04-28; Japan Thu 2027-05-13 | 15 |

Float (PLAN §6.1): steps 3 to 8 have +1 week to the order date if the run of step 7 passes the first time and −2
weeks if it must be repeated. Hardware for CGMH has +2 weeks at P50 delivery and −2 weeks at P90 (清明 falls in
step 15). Japan has +4 weeks at P50 and 0 at P90 (fiscal-year turnover on 04-01, Golden Week 04-29 to 05-05).
**The binding date of the whole plan is the box order on 2026-12-18.** If step 7 slips, order on the measured
RTX PRO 6000 figure of 2026-11-11 (62.6 of 95.6 GiB used) and correct the capacity statement after.

What the Windows form does to the float (v7.1):

- The order of 2026-12-18 does not wait for a WSL2 number. The workstation is the same under either system. If
  P-10 shows WSL2 slower than Linux, the capacity statement says what fits in the night (OD-10). The bare Ubuntu
  form stays the alternative for a site that needs the Linux figure.
- Step 11 has +1 week to feature complete at P50 delivery and −3 weeks at P90. The Lunar New Year holiday falls
  inside it. Each week the order of step 2 slips past 2026-11-27 moves step 11 by a week.
- At P90 the site workstations (P50 2027-02-19) arrive before the reference one. Then the first site workstation
  is the reference: P-10 to P-15 run on it, and the CGMH install date holds only because step 8a rehearsed the
  installer on another Windows PC.
- Step 8a is the guard. Without it the first run of `box-install.ps1` on real hardware is in February.
- The REDCap path (2a, 11a) has four weeks between its last repair and feature complete. It starts only when the
  zip arrives; each week the zip is late moves 11a by a week, and a study goes live on `copy` if 11a is not done.

## 5. Waves and lanes for parallel sessions

At most four sessions at a time, one card each. The lanes touch different folders so that sessions do not collide.
v7.1 adds lane W. It is a sixth lane, not a fifth session: with about 236 session-days against 280, every wave
needs all four sessions.
A card merges only after its own unit job is green (v6.1 §5.6 stays).

| Lane | Owns (folders) | Must not touch |
| --- | --- | --- |
| **A. Decision and model** | `services/matching`, `services/criteria_compiler`, `services/guard`, `libs/tb_llm`, `eval/`, `tests/property` | `deploy/`, `services/adapter` |
| **B. Night and capacity** | `services/adapter` (pipeline, not mapping), `services/lake`, `services/orchestrator` (jobs, scheduler, clients), `tools/trialbox/backup.py` | `services/console`, `services/matching` |
| **C. Trust and console** | `services/console`, `services/orchestrator/app.py` routes, `libs/tb_common` (auth, erasure, roles), `deploy/docker/*roles*` | `services/lake`, `services/matching` |
| **D. Box, serving and operations** | `deploy/` (not `deploy/windows`), `tools/` (install, qualify, complete_run, support), `services/gateway`, `services/embed_service`, `docs/runbook`, `docs/handover` | `services/console` pages |
| **E. Data input, standards, EDC** | `services/adapter/mapping`, `services/adapter/sources`, `services/datacore`, `services/omop`, `services/edc`, `services/rc_bridge`, `services/rc_sim`, `catalogue/`, reports, the REDCap test instance | `services/orchestrator` |
| **W. The Windows form** (v7.1) | `deploy/windows`, the Windows media, `docs/handover/OFFLINE-MEDIA.md`, `docs/handover/WINDOWS-INSTALL-CHECKLIST.md`; its changes to `tools/box` and the key back end go as small cards of their own, agreed with lanes D and C | `deploy/*.sh`, the compose files |

### Wave 0: 2026-11-13 to 2026-11-20. Small and certain; land the open pull requests

| Lane | Cards | Size |
| --- | --- | --- |
| all | Merge or close the open pull requests #304 to #315, #278, #262; merge #323 (DIN-001) and #324 (OPS-002) | — |
| owner | Ask the resellers in Taiwan and Japan for quotes to section 2.2 (Fri 2026-11-13). Fetch the REDCap release zip in the sites' version (by Fri 2026-11-27) | — |
| C | T-007 branch protection with the CI jobs as required checks (ENG-001) | S |
| D | Nightly green: `TB_ENV=TEST` for the test stack's embed service, the public-data fetch, random order to completion (ENG-002); a red nightly is the next day's first card | M |
| A | LLM-001 stop-gap: a clipped note never gives a final "not met" (`engine.py:618`) | S |
| A | NEW-LIFE-1: no pre-approved ruleset on a VALIDATION or PRODUCTION box (LIFE-001) | S |
| B | NEW-PERF-2 / NEW-ARCH-1: on 409 the orchestrator follows the running ingest (PERF-008, ARCH-002) | S |
| B | NEW-PERF-3: a built-but-not-promoted night is not "passed"; a snapshot dated after today is refused (PERF-009) | S |
| C | NEW-JRN-1: a new study gets its first approval in the console; the journeys never write the database directly (JRN-001) | S |
| C | NEW-JRN-2: the opt-out register takes a chart number or the whole pseudonym, never a prefix, and says when nobody matched (JRN-002, DIN-003) | S |
| C | ENG-004: the console reads `optout.effective()` (merged charts); with T-708 | S |
| C | NEW-ARCH-18: every store's schema is on its service's role list, with an enumerating test (ARCH-021) | S |
| D | NEW-OPS-8: `trialbox-ops.timer` enabled; stale health facts turn red (OPS-009). NEW-STD-2: signed audit heads on a timer and in `doctor` (STD-002, LIFE-010) | S, S |
| E | NEW-DIN-6, -7, -8: unmapped codes counted nightly; unknown status stays unknown; first night needs its required tables (DIN-006, DIN-007, DIN-008) | S, S, S |
| E | EDC-010 (XML-illegal characters refused), EDC-009 (append-only trigger on `datacore.history`), EDC-003 (a `multi` item held) | S, S, S |
| E | T-731 starts (Q8: the CGRD read connection is ready): the connection checked from the owner's side, one day read by `tools/mapping_check.py` | S |

### Wave 1: 2026-11-23 to 2026-12-04. The decision path, a box that starts, a harness that measures

| Lane | Cards | Size |
| --- | --- | --- |
| A | T-709 one status function; T-710 one excerpt builder with NEW-LLM-1 (windows keep their heading and negation scope; the budget from the build's context) | M, M |
| A | NEW-LIFE-2: the weekly re-check covers every structured criterion and brings excluded patients back (LIFE-003, LIFE-004); goldens move | M |
| B | T-689 on `StepStore`: lease, attempts, recorded steps; a restart resumes (ARCH-001) | L |
| B | T-687 scale gate with the dense profile (about 500 records and 40 notes per patient) under the compose memory caps; its lint covers every timeout and `LIMIT`, not only those above 60 s (PERF-002, PLAN-012) | L |
| C | T-714 (#312), T-712 (#308), then T-715 in report mode | M, S, L starts |
| D | Embedder pinned, in the image with hashed extras, PRODUCTION start test (ENG-003, HW-002) | M |
| D | Qualification path: licence step accepts `none-in-source` (HW-004); vendor record shipped in the bundle and promoted by the installer (HW-003, LLM-005); chat template hashed and passed (HW-005); context written into the pin, null context refused in PRODUCTION (LLM-007) | S, M, S, S |
| D | Installer reaches the wizard: backup step without a mail relay is a FAIL line, not a stop (OPS-003); the real `install.sh` in `make rehearse-box` and in CI (OPS-004) | S, M |
| D | NEW-PERF-1: `complete_run` sets `TB_SCREEN_LLM_CONCURRENCY` from the serving record and records calls/s, tokens/s, p50/p95, GPU utilisation (HW-006, PERF-007, LLM-012) | S |
| E | NEW-DIN-1 rest: ROC and era dates as declared column types. NEW-STD-1: ICD-9-CM years in Taiwan (STD-001). NEW-STD-4 / DIN-009: unit spellings (`IU/L`, `×10^3/µL`, `mL/分/1.73m2`, `秒`). NEW-STD-5: NHI drug code to ATC in the nightly path | S, M, S, S |
| E | NEW-DIN-3: the opt-out desk checks the patient is known; the chart-number rule is asked at install (DIN-003) | S |
| E | T-731 the CGRD connector: the read side and its mapping step on the real connection (to wave 2). Nothing read from it enters the repository | L starts |
| E | NEW-EDC-0: our REDCap test instance from the owner's zip, with its project, four tokens and the R1 to R9 command (section 2.4) | M |
| W | NEW-WIN-1: `box-install.ps1` (to wave 2) | L starts |

### Wave 2: 2026-12-07 to 2026-12-18. The product on a GPU; the order

| Lane | Cards | Size |
| --- | --- | --- |
| D + cloud session | The product-on-GPU run (section 7.1); then T-667, T-734 from its numbers; the vLLM image move in the same GPU session (ENG-013: 337 accepted findings lapse 2026-12-10) | run, S, M, M |
| A | NEW-LLM-2: the retrieval lexicon from the compiled ruleset in the site's language; the pinned embedder in SCREEN (LLM-002) | L |
| A | NEW-LLM-3/4: the PHI tripwire stops refusing ordinary zh-TW and ja criteria and reads full-width digits, katakana names and Japanese insurance numbers (LLM-003, LLM-004) | M |
| B | T-723 (#314) `publish(night)`; T-692 (#304) streams, the build as its own process (PERF-001) | L, L |
| C | T-715 router by router, lifecycle first; NEW-ARCH-3 the console leaves the orchestrator's stores | L, M |
| E | NEW-EDC-1: conformance run on our REDCap instance (NEW-EDC-0) recorded as cassettes; the simulator made as strict (EDC-001) | M |
| E | T-731: the CGRD mapping step ends; P-7's CGMH part gives the first code-coverage report | L ends |
| W | NEW-WIN-1 ends with a full run on a Windows 11 PC with an NVIDIA card (P-0); NEW-WIN-2 start without a person; NEW-WIN-3 `.wslconfig` from the hardware; NEW-WIN-8 unlock and keys | L ends, S, M, M |
| E | NEW-DIN-4, -5: SS-MIX2 version key with the day; ICD-10 in the first PRB-3 triple (DIN-004, DIN-005) | S, S |

### Wave 3: 2027-01-04 to 2027-01-29. The reference box; real connections; erasure

| Lane | Cards | Size |
| --- | --- | --- |
| D | The reference workstation from factory Windows by `box-install.ps1`: the Windows media, name resolution, a time source (HW-012, OPS-001, OPS-005, OPS-006, OPS-007; `box-prepare.sh` and the Linux media go with the parked Ubuntu form). T-730 as five cards (message path and the first-run code in the installer's window, backup target and key ceremony, health checks for night, clock and GPU, the BitLocker recovery page, updates in the window of NEW-WIN-5). When the workstation arrives: P-1 to P-5 and P-10 to P-15 | L, 5 × M, runs |
| W | NEW-WIN-4 the console on the site's network; NEW-WIN-5 Windows Update and restarts; NEW-WIN-6 the card shared with the desktop; NEW-WIN-7 backup and restore paths; NEW-WIN-9 media and handover documents | 5 × M |
| D | T-735 the owner's handbook and IT's one page; the IT pack rewritten to the box (OPS-011, HW-013) | L |
| B | T-726 the night runner with nightly deltas (`since` the last published generation) (PERF-006); T-724, T-725 generations; backup: incremental, lake lock for the listing only, append-only files (PERF-010, PERF-011, ENG-011) | M, M, M, M |
| C | T-715 refuse mode; T-716; T-719; T-206b (#278) on T-727's registry; T-728 (#313) | —, M, M, M, S |
| E | T-731 on `publish(night)`: the first whole night from CGRD (step 10b) | M |
| E | The REDCap send: EDC-008 a true attempt ledger; EDC-007 per-record fallback and the lock read first; EDC-002 whole-instance writes; EDC-003 checkbox columns | S, S, S, M |
| A | NEW-LLM-6: the accuracy set per language and stratum (long notes, negation, family history, era dates, labs; about 200 gold exclusions each), with a calibration table and paraphrased injection (LLM-006, LLM-009, LLM-011); measured on the reference box | L |
| A | NEW-LIFE-3: protocol structure (groups, phases, warnings); two real public protocols (an RA trial, an early-AD trial) as fixtures (LIFE-002) | M, M |

### Wave 4: 2027-02-01 to 2027-02-26. Feature complete

| Lane | Cards | Size |
| --- | --- | --- |
| B | T-694 batches; T-702, T-703, T-695; the 500,000-patient night as an incremental night with a stated capacity, refused with an estimate when it does not fit (HW-007, OD-10) | L, L, S, M |
| C | Lifecycle repairs: the screening log keeps numbered rows on opt-out (LIFE-005); a study closes only when empty (LIFE-006); the SAE clock is off until the study's rule set is confirmed, mail at entry and daily (LIFE-007, LIFE-008); retention hold by study state (LIFE-009, T-305c); reason for change and append-only trails (LIFE-011) | S, S, M, S, M |
| C | Journeys: the PI may start a request from the page (JRN-003); the EDC item map saves at the dictionary's size (JRN-005); the privacy office reaches the one-patient report (JRN-006); a consent date after today is refused (JRN-007); the monitor's page is linked and shows built-in forms (JRN-008); the journey set covers approval, SAE, visits, close, EDC sign and the monitor visit (NEW-JRN-20). UI: the mark bar on the desktop (UX-001); session expiry keeps the note (UX-007); per-user language; week-list latency after a box measurement (UX-010) | S to M each |
| E | Outputs: PDF glyph fallback (UX-002); localised, printable workbooks (UX-003); a BOM on every CSV; one decoder for every text upload with Shift_JIS and Big5 cases (UX-004) | M, M, S, S |
| E | EDC, send and copy: source-changed flag (EDC-004); the human's correction read back (EDC-005); retire a removed item (EDC-006); era and ROC dates in prefill; then R1 to R9 on our instance (P-6) | M, M, S, S, run |
| W + D | If the reference workstation arrived in this wave: P-10 to P-15, then the capacity statement restated for WSL2 and rule 6 of section 2.3 corrected from P-11 | runs, S |
| D | T-317 guides in ja and zh-TW served from Help; acceptance gains capacity and power-cycle criteria | M, S |
| all | Burn down the `KNOWN` table of expected failures, one card per line (ENG-005); raise the mutation floor after each complete nightly (ENG-006) | L, split |

### Wave 5: 2027-03-01 to go-live. Sites; fixes only

Site workstations installed by `box-install.ps1` (T-315b), connected, mapped on a real extract with the per-study
code-coverage report as the exit (NEW-DIN-17), the first real night, the dry run (T-315c), the journeys on the
site's workstation, training, acceptance. No new feature card starts in this wave.

The API send to REDCap is live at go-live (Q4). Its repairs ended in waves 3 and 4. Here R1 to R9 run once on each
site's own REDCap test project, with tokens the site's REDCap administrator makes. A study whose project passes goes
live with the switch `on`; a study whose project does not stays on `copy` until its line is fixed.

The first work after go-live is wave 6 of section 3.3.

## 6. What "done" means for a card in this plan

A card is **accepted** when its acceptance test exists, could fail, and runs in a required CI job; "merged" is
counted apart (PLAN-014). Nine merged cards are reopened as not accepted: T-004, T-012a, T-114, T-650, T-652,
T-206a, T-212c, T-656, T-664. Status is generated from the registry and the pull requests, not written by hand
(NEW-PLAN-5, S).

## 7. What must be measured

### 7.1 On the GCP GPU VM (owned by the cloud-run session; this plan sends it the list)

Thresholds come from the night window and the data size, not from a fixed figure. With an 8-hour night, 50,000
patients × 5 studies needs at least 1.66 pair calls per second and 500,000 × 1 study needs 3.3 (LLM §7).
The VM is Linux. Its numbers are the Linux baseline; the site's form is measured by P-10 (section 7.2).

| Id | Test | Record | Pass |
| --- | --- | --- | --- |
| G-1 | Chat template identity: the template the compose file passes against the weights folder's own; token identity on 20 prompts | sha256 of both; differing tokens | identical, or the accuracy runs are repeated with the shipped one |
| G-2 | The real offline bundle → `box-install.sh` → first-run wizard answers only → `pin_model --install rtxpro6000` on real folders → full `qualify` → `--promote`; serving capture; vLLM host RSS | manifests, the qualification record, minutes per step, every stop | PRODUCTION resolves `judge` and `verifier` to promoted builds; no step needed a shell beyond the installer |
| G-3 | SCREEN on 50,000 synthetic patients (ja, then zh-TW) at 1, 4, 8, 16, 32, 48 sequences in flight; vLLM `/metrics` and `nvidia-smi` every 10 s | calls/s, tokens/s, p50/p95 latency, GPU utilisation and memory, breaker openings; the candidate list per setting | the candidate list is identical at every setting; calls/s at the chosen setting meets the window above |
| G-4 | Eager start on and off; the structured-output backend named; guided decoding overhead | calls/s each way; schema failures | no schema failure; the faster setting is the profile |
| G-5 | Real against estimated token counts through `/tokenize` on 200 ja and 200 zh-TW excerpts | the ratio's p50, p95, max | the budget uses the measured ratio; no sized prompt is refused |
| G-6 | The whole night at 50,000 with the dense profile under the default memory caps: ingest, rebuild, screen, backup | seconds and peak memory per step; OOM kills | no kill; the night fits the window; else the capacity statement says what fits |
| G-7 | Pair verdicts on the clipped against the whole note for the LLM-001 cases (family history under the wrong heading; a denied list without its lead-in) | verdict per case, before and after NEW-LLM-1 | 0 exclusions on a clipped note |
| G-8 | Compile two real public protocols (RA, early AD) with the production judge | class split, `needs_review`, `time_sensitive` per criterion | no extension-phase line active without a warning; alternative diagnosis groups not flattened to AND |
| G-9 | Restart and outage inside a 16-way screen: `docker restart` of the orchestrator, the adapter and the judge; a power cycle | final job state, calls repeated, whether `CURRENT` moved, seconds to healthy | the job resumes; no call is paid twice beyond the in-flight ones; nothing is half-published |
| G-10 | The vLLM image move: the 54-case pair canary and the qualification on the new image | 54/54, schema failures, calls/s against G-3 | 54/54; speed within the run-to-run spread of G-3 |
| G-11 | The embedder in PRODUCTION: start, RSS, chunks per second on 50,000 patients' notes | seconds, memory, chunks/s | the index builds inside the night window |

### 7.2 On the owner's hardware

| Id | Where | Test | Pass |
| --- | --- | --- | --- |
| P-0 | Any Windows 11 PC with an NVIDIA card (the rental workstation of D-421), before the reference workstation arrives | `box-install.ps1` end to end with a small model; restart with nobody signed in; whether WSL2 runs from the boot task | the console answers from another PC after the restart; every stop of the installer recorded |
| P-1 | Reference RTX PRO 6000 workstation (Windows 11, WSL2) | Timed install from factory Windows by `box-install.ps1` and the handbook only | first sign-in with no step the owner cannot do |
| P-2 | same | G-2, G-3 and G-6 repeated in WSL2 on the card edition bought (Workstation Edition or Max-Q) | the capacity statement for the site's form; its difference from the VM's is explained by P-10 |
| P-3 | same | Restore on a second machine at 50,000 patients with the recovery copy of the key | pseudonyms equal; the measured time becomes the stated RTO |
| P-4 | same | Thermal, power and noise soak for one full night, noise read at a desk beside it; a power cut during a night job | no throttle that breaks the window; the workstation returns with nobody signed in and the job resumes |
| P-5 | same | Week-list and mark latency at about 80 and 400 listed patients, with and without a running job | recorded; the limit is derived from it |
| P-6 | Our REDCap test instance (NEW-EDC-0), then each site's own test project | The nine tests R1 to R9 of `10-redcap-edc.md` §8 | each by its own rule |
| P-7 | CGMH, one day of the real export; Japan, one month of real SS-MIX2 | `tools/mapping_check.py`: date formats, unmapped codes, unit spellings, duplicates, repeated order numbers | the per-study code-coverage report (NEW-DIN-17) |
| P-8 | Windows with Japanese and Traditional-Chinese locale | Open the four CSV/XLSX downloads in Excel; print preview of the screening log | no mojibake; the log prints on A4 |
| P-9 | B200 (bench only), Spark (only if bought) | B-1 to B-5, S-1 to S-6 of `13-final-build-hardware-install.md` §8 | not on the critical path |
| P-10 | Reference workstation | **WSL2 against Linux.** G-3 at the chosen setting and the whole night of G-6, three ways: on the GCP Linux VM (section 7.1), on this workstation started once from Linux on an outside disk before BitLocker is turned on, and in WSL2. Record calls/s, tokens/s, p50/p95, GPU utilisation, peak memory, seconds per night step, disk read and write speed of the virtual disk | the candidate list is identical three ways; calls/s in WSL2 meets the night window of section 7.1, else the capacity statement says what fits; the two ratios (card edition, WSL2) are written into the statement |
| P-11 | same | **The desktop in use while serving.** G-3 at the chosen setting while a signed-in standard user runs a browser with video, an office suite and a video call; then while that user starts a second GPU program Record calls/s, p95 and card memory by program, with and without the desktop | the candidate list is identical; calls/s still meets the window; rule 6 of section 2.3 is rewritten from the figures; the health line turned red for the second GPU program |
| P-12 | same | **`.wslconfig` fit.** The models load and the dense night of G-6 runs under the share NEW-WIN-3 computed, with a desktop user signed in. Record peak memory in WSL2, free memory in Windows, kills | no kill in WSL2; Windows keeps the desktop's declared share |
| P-13 | same | **Restart with nobody there.** A Windows Update restart inside the update window and one forced during a night job; nobody signs in. Record seconds until the console answers from another PC, the job's final state, driver and WSL2 versions before and after | the stack returns by itself; the job resumes; the versions equal the serving record |
| P-14 | same | **The site's network.** The console opened by the workstation's name from another PC under each networking form of NEW-WIN-4, after a restart; a port scan from that PC. Record the ports that answer | the console port only, in the form kept |
| P-15 | same | **Backup and restore from WSL2.** A full backup at 50,000 patients to each target path of NEW-WIN-7; P-3's restore on a second Windows machine. Record MB/s per path and minutes to restore | the backup fits its window at the measured speed; the restore time is the stated RTO |

## 8. What the dates rest on

1. The box order by 2026-12-18, and so the run of section 7.1 by 2026-12-11.
2. Scope: the cuts of section 3. Without them the code does not reach 2027-02-26.
3. The CGRD connection, ready on the owner's side (Q8): the connector reads it from wave 0, and its first whole
   night waits for T-723.
4. The REDCap release zip from the owner by 2026-11-27. With it the API send is live at go-live. Without it
   nothing closes EDC-001, and copy-assist is the go-live form for every study.
5. Real extracts from both sites by mid-March for the mapping content; the review found that every date, code and
   unit defect so far was invisible on synthetic data. CGMH's connection is ready (Q8), so its mapping starts
   in December; Japan's extract is still needed by mid-March.
6. The reference workstation ordered by 2026-11-27. It gives the first WSL2 figure. Until it runs, every
   capacity figure is a Linux figure and says so.
7. Four sessions in every wave. At three the plan of v7.1 does not fit (section 2.1, line 7).

## 9. Change history

| Date | Change |
| --- | --- |
| 2026-11-12 | First draft from the deep review of 2026-11-12. |
| 2026-11-12 | **v7.1.** The owner answered Q1 to Q9 (D-494). The site machine is a Windows workstation that staff also use; TrialBox runs in WSL2 with Docker Engine inside it (sections 2.2, 2.3; cards NEW-WIN-1 to NEW-WIN-9; lane W). `deploy/windows` is kept. The REDCap API send is live at go-live, on our own test instance (section 2.4; NEW-EDC-0; EDC-001 to EDC-008 in waves 2 to 4). T-731 starts in wave 0. Every frozen item has a dated wave after go-live (section 3.3, waves 6 to 11). Section 4: step 2 to 2026-11-27, step 11 to 2027-02-19, new steps 2a, 8a, 10a, 10b, 11a. Section 7.2: P-0 and P-10 to P-15. Go-live dates and the order of 2026-12-18 unchanged. |
