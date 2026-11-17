# D-1123 A live session on the GPU VM: the owner walks one public protocol on the installed box with the served models

- **Task:** lane H, card H-11 (design only; nothing is built or launched by this card); amended by card H-13
  (the session built) after the integrator's ruling, section "Ruled by the integrator, 2026-11-17"
- **PR:** this branch (`claude/lane-h-11-gpu-session-design`), from master `fae5c1f7` (train 65); the amendment on
  `claude/lane-h-13-live-session`
- **Date:** 2026-11-17
- **Status:** proposed (the integrator ruled on its eight questions; the integrator flips the status)
- **Builds on:** D-505 and D-516 (the budget and the launch rule), D-1062 (steps mode), D-1063 (the acting role),
  D-776 (the one-time link), D-423 (443 only, no secret in metadata), D-1036, D-515, D-506, D-775

## Context

Before the pilot the owner wants to click through one real protocol end to end with the served models, not the
demo's stub (`docs/handover/demo-2026-11-17.md` "What is real and what is not"). The steps-mode preview VM (D-1062)
gives every click from the first step but keeps the stub model. The GPU VM runs the served pair, but only unattended:
`deploy/gcp/box-run.sh` drives FEAS, APPROVE and SCREEN by mail (`docs/handover/gpu-vm-handover-2026-11-16.md`
section 4.8), and no person signs in. Sources below are that hand-over ("GPU hand-over", section) and the scripts.

## Decision (proposed)

### 1. Purpose and scope

1. One sitting, at most three hours of the owner's time, on the GPU VM `tb-gpu-sim` with the box installed by the
   direct route (GPU hand-over 4.4) from the master commit the integrator names, the served pair and embedder.
2. The owner walks one public protocol: the text of one ClinicalTrials.gov record, pasted in the console. Paste,
   compile (FEAS), read and approve the criteria, SCREEN over the public sets already on the box's lake (tcga
   pathology reports, jmed: GPU hand-over 4.8, built by `53-acc-data` and `54-acc-ingest`), then read the candidate
   list and the report.
3. It is not a measurement, and **nothing from this session is evidence**: no score is run, its figures go in no
   evidence page and support no target (D-515: evidence stays on its two commits). It is never a hospital box and never reaches one (D-1036). It is synthetic or public
   text only (handover rule 1, `docs/plan/38-handover-2026-11-15.md`).

### 2. How the installed box is reached

1. **TLS on tcp:443 only.** The box's own Caddy listens on 443 while the stack runs (GPU hand-over T16), with the
   box's local CA (`deploy/secrets/tls/caddy-root.crt`, `box-install-run.sh` `tb-console-cacert`). The browser warns
   once, as on the demo VM (`demo-2026-11-17.md` "Before you start"). The root's SHA-256 is written beside the links,
   as `demo-vm-boot.sh` prints it on the serial line, so the owner can compare it.
2. **The firewall, today a gap.** The project's `default-allow-ssh` reaches the GPU VM from any address, and its tag
   `tb-gpu-door` opens tcp:443 to one source range of an earlier door; the GPU VM has no deny rule (GPU hand-over T16).
   The session adds what `demo-vm.sh` does (`up`, `rules_check`): a deny-all rule on a session tag and one allow rule,
   tcp:443 from the owner's own address range only (`TB_DEMO_ALLOW`'s form, never `any`). No rule for port 80 (D-423
   item 4; nothing on the box listens on 80 from outside: the old servers bind loopback only, GPU hand-over T9).
3. **No SSH for the owner.** `block-project-ssh-keys=TRUE` in the metadata and sshd stopped at boot, as
   `demo-vm-boot.sh` does (its header, "no SSH"). The integrator needs none: the driver uses the bucket and the serial
   port (GPU hand-over section 3).
4. **One-time links (D-776).** The box opens each account with the product's enrolment code
   (`UserStore.open_by_code`, as `demo-vm-boot.sh` `people()`), with `TB_CONSOLE_PUBLIC_URL=https://<address>` so the
   link names the box. The codes go to one private bucket object only, never to metadata, the serial port or a log.
   The integrator reads it once with a `links` command that deletes it (`demo-vm.sh links`) and gives the owner his
   line in the integrator's own session, never on a PR, in a comment or in a file (GPU hand-over section 3, "Healthy").

### 3. The environment, the accounts and the roles (rewritten after the ruling)

1. **What the session is.** The owner looking at the product, not a validation record. **Nothing from this session
   is evidence**: no figure, page, list or record of it supports a target, a measurement or a release, and no
   evidence page names it (D-515). The session's record (`records/session.json`), its links object and the owner's
   line all say so in those words. The console's own pages cannot say it without a product change (no setting puts a
   line on every page; the demo banner of D-328 belongs to `demo.mode`, which refuses the paste the walk needs):
   that is a question to lane C2, below.
2. **The DEV environment, with the served models** (the integrator's answer 2). The box runs `TB_ENV=DEV`, so
   D-1063's acting role is allowed there (its item 3 forbids it on VALIDATION and PRODUCTION only). The walk needs
   four roles: coordinator, investigator, the PI who approves criteria (runbook 11, "Which accounts": approving
   criteria is PI-only), and the steward or administrator for the study's set-up.
3. **One sign-in per person, with the acting role.** Lane C2's build of D-1063 is on master: D-877, the boot tool
   `python -m console.steps_roles` and `services/console/acting.py` (the flag `steps.acting_role`, the switch
   `POST /role`, audited `role.acting`). The session opens each person's account with that tool (the first role is
   the account's own, the others are the roles it may act in; one one-time enrolment code each) and switches the
   flag on as the tool does (audited, actor `console:steps-roles`). The default is one person, the owner:
   `owner:coordinator+investigator+steward+admin`. Every permission is the acting role's own (D-1063 item 2), so the
   separation of duties of a real box is not claimed for this box.
4. **What the box does in DEV today, read from this tree.** The box's routing policy (`models/routing.yaml`, read by
   the gateway's own `RoutingPolicy`) does not route the served pair in DEV: DEV's ceiling is D0, so the compile's
   calls (D1) and the screen's judge (D3) are refused (`class_not_allowed_in_env`); a call relabelled D0 goes to the
   route `dev-public`, whose candidates are the stub and `j-workhorse` at the external bake-off endpoint
   (`openrouter`, zone `dev_public`), never the box's own servers; the embedder (`e-embed@embed`) has no DEV route
   at all. And `deploy/egress.py` opens that external endpoint to the gateway when `TB_ENV` is DEV. So a DEV box with
   the served pair is a combination the box refuses, and the one way to force it (relabelling the data D0) would
   point the pasted text at an external endpoint. The session does not build around it: the driver asks the same
   policy for free before anything is paid (`tools/box_run.py session-check`) and refuses a DEV session while the
   policy says so, naming the file and the rule. This is the build's stop for a product change, reported to the
   integrator (a DEV route for the box's own pair, perimeter only, and no DEV-only external endpoint opened by the
   egress table; the routing table's owner).
5. **The environment is a named option of the driver**: `--session-env dev` (the ruling, the default) or
   `--session-env validation`. In VALIDATION the box routes the served pair (D-823) and the acting role cannot
   exist, so the session falls back to one account per role, as this design first proposed
   (`owner-crc:coordinator,owner-inv:investigator,owner-stw:steward,owner-adm:admin`). The fallback is taken only
   when the integrator names it; the integrator ruled DEV, so it is a question, not a default. The day the routing
   change lands, `session-check` passes for DEV and the same launch gives one sign-in with no other change.
6. Whether the console can make the owner's account the PI of a new study on a box with no demo seed is not verified
   here. The demo VM's PI is a seeded account (runbook 11).
7. **Removed at the end.** The 400 GiB disk is kept between launches (lane G README, section 1), so the accounts would
   outlive the session. The session's last step disables them (`UserStore.disable`: the account off, its sessions
   ended) before power-off, and the next boot of any box run on the disk disables any session account still open
   before any step runs and before anything is served (the box's Caddy down, D-1132 item 7). An unused code expires
   after its hours (D-776).

### 4. The hard stop

1. Three locks, all existing: the cloud's `--max-run-duration` with `--instance-termination-action=STOP`
   (`box-run.sh`, its header's item 3); the VM's own cap timer at `tb-max-minutes` (`box-install-run.sh`, "the VM stops
   itself"); the watchdog (GPU hand-over section 8). The session's group cap is the bring-up plus three hours, rounded
   up to whole hours: 4 h.
2. **The watchdog would cut a quiet owner.** It powers off after `tb-idle-minutes` (20) with no heartbeat, and its
   heartbeats are a log growing, disk I/O, the card busy or a job changing state (GPU hand-over section 8). An owner
   reading a page for 20 minutes makes none. The session step needs its own heartbeat (a console request in the last
   20 minutes) or the idle rule off for that step only; the cap and the cloud's limit stay.
3. **What the owner sees.** The page stops answering. His line states the stop time in UTC, as the demo's sheet states
   its 12-hour stop (`demo-2026-11-17.md`). No in-page countdown exists; none is proposed.
4. **No extension inside a session.** More time is a new launch: its estimate, worst case and running total posted
   first and the owner's yes (D-505 item 2), new accounts and new links.

### 5. Cost

| Item | Basis | Hours | US$ |
| --- | --- | --- | --- |
| VM boot | GPU hand-over section 11, row 1 | 0.25 | 0.69 |
| Images and tree (b01 to b03, d04) | GPU hand-over 4.3 and 11 row 1 | 0.11 | 0.30 |
| Stack, wizard, pins, serving, G-1, canary (02 to 07) | GPU hand-over 11 row 1 | 0.15 | 0.41 |
| The canary through the box's gate (07g) | GPU hand-over 4.6: 3 to 4 min | 0.07 | 0.19 |
| Public data built and ingested (53, 54) | 0.03 h for jmed; 0.40 h for all sets (GPU hand-over 4.8) | 0.03 to 0.40 | 0.08 to 1.10 |
| **Bring-up before the owner can click** | the rows above | **0.61 to 0.98** | **1.67 to 2.69** |
| The owner's session | three hours | 3.00 | 8.22 |
| **Estimate** | | **3.61 to 3.98** | **9.89 to 10.91** |
| **Worst case: the 4 h cap** | US$2.74 an hour, spot (`tools/complete_run.py` `PRICE_PER_HOUR`) | 4.00 | 10.96 |

- **Per hour:** US$2.74, spot; on demand is taken as three times that, US$8.22 (D-468), not re-checked (GPU
  hand-over section 4). On demand, the 4 h cap is US$32.88.
- **While stopped:** the GPU disk bills US$1.913 a day, US$58.20 a month, whether or not a session runs (GPU
  hand-over section 12). The session adds nothing stopped.
- **Model load:** the step times above include the loads measured on those launches; the healthy wait allows up to
  20 minutes (`tb-healthy-minutes`); a longer load is not stated in the hand-over.
- **Spot pre-emption** (GPU hand-over T13): the page stops answering, the VM stays off until a `--resume`. The
  integrator tells the owner in its session that it was pre-empted, with the hours used. A resume is a new costed
  start (section 4, item 4).
- **Running total:** US$110.16 spent of the owner's US$200 cap (`42-plan-2026-11-16.md` section 3). At its worst case
  the session brings it to US$121.12, before the confirming launch, which is not costed here.

### 6. What must never be possible, and the check before the link is given

| Must never | Mechanism | Check before the owner gets a link |
| --- | --- | --- |
| Real patient data | No hospital adapter: the synthetic site's answers (`deploy/gcp/validation-site-answers.yaml`); the VM is in the cloud with no route to a hospital network. The paste and upload paths are open (steps mode needs them, D-1062 item 2), so the rule is told, with the first sign-in's acknowledgement (D-1062 item 4) | The lake holds only the public sets' ingest (`54-acc-ingest` record); the owner's line says "public text only" |
| PRODUCTION | `03-wizard` stops unless the box says VALIDATION (`box-install-run.sh` `step_venv_env`); the session then sets the named environment, DEV or VALIDATION, never PRODUCTION (D-1132) | `03-wizard` and `51s-session-env` done in `state.json` |
| A secret in metadata | `tools/box_run.py metadata` refuses a key-like value; `--preflight` checks it (GPU hand-over 4.0) | the preflight's exit 0; `instances describe` lists only `tb-*` names and the startup script |
| A secret on the serial port | Codes go to the private object only (as `demo-vm-boot.sh`); installer lines are masked (`box_vm.py redact`) | the serial output has no `enrol#` and no code-shaped line |
| Port 80 or any port but 443 | The deny-all and the one 443 rule (section 2); sshd off | the rules listed on the network reach the VM by tcp:443 only (`demo_vm.py rules-check`'s logic) |
| A public bucket | Not stated in the hand-over whether public access prevention is on | the bucket's IAM policy names no `allUsers` or `allAuthenticatedUsers` |
| The session outliving its stop | Section 4's three locks | `instances describe` shows `maxRunDuration` and `STOP`; the cap timer's line in the serial log |
| The pasted text leaving the box | The served models are on the box; the gateway's tripwire bears only on routes that leave it (D-506). The egress table is not applied on the direct route: only `install.sh` runs `deploy/network.sh apply` (its line 733) | `deploy/network.sh apply` run at bring-up and `check_host.sh`'s egress line PASS |

### 7. What it reuses, and the new pieces

**Reused unchanged:** `box-run.sh` (preflight, estimate, metadata, `--max-run-duration`, `--collect`, `--stop` and
`reset_vm`); the `dev` route, steps b01 to b03 and d04 and the direct bring-up 02 to 07 with 07g (GPU hand-over 4.3 to
4.6); `53-acc-data` and `54-acc-ingest` for the public data; the watchdog and cap timer; from `demo-vm.sh` and
`demo-vm-boot.sh`, the firewall pair and `rules_check`, the people's codes, the `links` command, the sshd stop.

**New, each a future card (sizes as plan v7.3's S, M):**

1. **SESSION-DOOR (S):** the deny-all and tcp:443 rules on a session tag from the owner's ranges, sshd off,
   `block-project-ssh-keys`; `--stop` removes the tag and the rules.
2. **SESSION-EGRESS (S):** `deploy/network.sh apply` on the direct route, and `check_host.sh`'s egress line kept.
3. **SESSION-STEP (M):** a `session` group (cap 4 h): accounts by enrolment code, `TB_CONSOLE_PUBLIC_URL`, the codes'
   object, the console heartbeat for the watchdog, the accounts disabled at the end and at every later boot.
4. **SESSION-LINKS (S):** `box-run.sh --links <run id>`: print once, delete, the root's SHA-256 and the stop time.

### 8. Risks and alternatives

- **Risks.** The PI role on a box with no seed is unverified (3.3). The idle watchdog (4.2). The disk keeps the
  session's study and console records after it; the next run's tags (`--acc-rs-tag`) avoid a clash (GPU hand-over T3).
  A spot pre-emption ends the sitting. A box from current master may fail bring-up; that costs the hours to the stop.
- **A. The steps-mode preview VM (D-1062).** Every click, the stub model, a CPU VM. Free of GPU hours, but the
  criteria read from notes are the stub's, not the served pair's.
- **B. A recorded run.** The owner's chosen protocol run unattended by the existing acc path (FEAS, APPROVE, SCREEN by
  mail), the owner reading the collected screen JSON and report afterwards. No door and no accounts, about the
  bring-up plus one SCREEN; no clicking.
- **C. This live session.** The only one that shows the served pair in the console the pilot will use.
- **Recommendation.** C, built as the four cards of section 7, launched once they are on master, after the
  owner's yes on the posted estimate. Until then, A for the clicks and B for the pair's answers on his protocol.

## Ruled by the integrator, 2026-11-17

The integrator's answers on PR #639 (2026-11-17 05:35 UTC), as given:

1. Is the session wanted as designed (option C)? **Yes, option C, built.**
2. Four accounts on the VALIDATION box, or D-1063 on this box? **"Neither as asked. The session box runs in the DEV
   environment with the served models: it is the owner looking, not a validation record, so D-1063's acting role is
   allowed there and he gets one sign-in per person. Change the design to say so, and say plainly on the session's
   pages and in its record that nothing from it is evidence."** Section 3 is rewritten for it; its item 4 is what the
   box does in DEV today.
3. Spot or on demand? **Spot.**
4. The same US$200 cap as the confirming launch? **Yes, the same US$200 cap.**
5. The owner's line given in the integrator's own session? **Yes.**
6. Which public set? **Both tcga and jmed, and the synthetic hospital.**
7. The four cards of section 7 to lane H? **Yes, the four cards are lane H's.**
8. Option B first? **No** (the steps-mode preview has been running since 2026-11-17); a recorded run only if the
   owner names a protocol.

The four cards are built as D-1130 (SESSION-DOOR), D-1131 (SESSION-EGRESS), D-1132 (SESSION-STEP) and D-1133
(SESSION-LINKS).

## Questions for the integrator (answered above)

1. Is the session wanted as designed (option C), yes or no?
2. Four accounts on the VALIDATION box (recommended), or ask the owner to rule D-1063 onto this box?
3. Spot (US$10.96 worst case) or on demand (US$32.88 worst case, no pre-emption)?
4. Does the session draw on the same US$200 cap as the confirming launch, yes or no?
5. Is the owner's line given in the integrator's own session, yes or no (else name the channel)?
6. The public set the owner screens over: tcga only, jmed only, or both?
7. Should the four cards of section 7 go to lane H, yes or no (else name the lane)?
8. Option B first, before any live session, yes or no?

## Not verified

Nothing was run: no cloud call, no launch. The firewall rules' state is the hand-over's of 2026-11-16, not read
again. Whether the console can name a new study's PI without a seed, and the bucket's public access setting, are not
stated in the hand-over. The step times are lane G's measurements on earlier commits.
