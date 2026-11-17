# D-1132 The session step: a named environment, the public sets, its heartbeat, its stop, its accounts closed

- **Task:** lane H, card H-13 (SESSION-STEP of D-1123 section 7)
- **PR:** this branch (`claude/lane-h-13-live-session`)
- **Date:** 2026-11-17
- **Status:** proposed; a DEV session is refused today for a product reason (item 2), reported to the integrator
- **Builds on:** D-1123 (amended after the ruling), D-1063 and D-877 (the acting role), D-1120 (this boot's ready
  line), D-505 and D-516 (the launch rule), D-823 (VALIDATION routes the box's pair)

## Decision

1. **A step group `session`**, with `dev` only: `deploy/gcp/box-run.sh --mode validation --steps dev,session`. Dev's
   own steps are kept: the commit's images, its tree, the direct route 02 to 07g. Qualify and what follows it are
   left out by `tb-skip`, each said in its part. Then the session's steps, in this order:

   | Step | What it does |
   | --- | --- |
   | `50` to `54` | the acc group's own steps for the public sets jmed and tcga (Run A's sizes) |
   | `53h-session-hospital` | the synthetic hospital: the scale gate's generator, 200 patients by default (`--session-synth`), merged into the same feed |
   | `51s-session-env` | the box's environment set to the named one |
   | `55-session-egress` | the box's own egress rules, D-1131 |
   | `56-session-accounts` | the accounts and the links, D-1133 |
   | `57-session-open` | the session |
   | `58-session-close` | the accounts disabled |

   Nothing from a session is evidence. No score is run. `records/session.json` says so, and holds no code and no
   pasted text.
2. **The environment is a named option of the driver**: `--session-env dev` (the integrator's ruling, the default)
   or `--session-env validation`. `51s-session-env` sets `TB_ENV` in `deploy/.env`, the box's own declared setting
   (D-127), and `TB_CONSOLE_PUBLIC_URL`. It then recreates every service but the two model servers. The box is
   never PRODUCTION. Its environment from before the session is put back at the close.
   - **What the box itself does in DEV with the served models, read from this tree:** it refuses them.
     `models/routing.yaml` gives DEV a D0 ceiling, so the compile's D1 calls and the screen's D3 judge get
     `class_not_allowed_in_env` (`services/gateway/policy.py` `RoutingPolicy.candidates`).
   - A call relabelled D0 goes to `dev-public`: the stub, then `j-workhorse` at the external `openrouter` endpoint.
     The embedder has no DEV build at all (`dev-stub`).
   - And `deploy/egress.py` opens `openrouter.ai:443` to the gateway in DEV.
   - So `tools/box_run.py session-check --env DEV` refuses. A DEV launch stops for free with exit 9 and names each
     file and rule.
   - On the VM, `52-acc-routes` asks the box's own gateway the same and stops with `TB-ACC-BLOCKED`.

   Nothing is built around it. The routing change is the routing table's owner's, and is a question to the
   integrator. With `--session-env validation` the check passes: VALIDATION routes the box's pair, D-823, and its
   egress table opens nothing.
3. **The accounts follow the environment** (D-1123 section 3):
   - DEV: one account per person, with the roles it may act in. This uses lane C2's boot tool `console.steps_roles`
     with its acting flag (D-877). The default is `owner:coordinator+investigator+steward+admin`.
   - VALIDATION: one account per role, since D-1063 item 3 forbids the acting role there.
   - Names carry the run's stamp (`owner-s11170600`): the kept disk holds every earlier session's disabled accounts.
4. **Its heartbeat.** The watchdog's 20 minutes would cut a person reading a page. So while the session is open the
   step keeps the heartbeat itself, without any change to the console:
   - it reads the box's own Caddy access log (`docker compose logs caddy`) once a minute;
   - it counts the requests from an outside address (`box_vm.py session-requests`). The VM's own probes and the
     box's networks are not counted;
   - it keeps the heartbeat while one came within `tb-session-idle-minutes` (60);
   - with none for that long, it ends early.
5. **Its stop.** The window ends at the earlier of:
   - the start plus `--session-hours` (1 to 3);
   - the VM's cost cap less ten minutes, so 58 runs before the cap fires.

   Behind it, as for every box run: the cap timer at `tb-max-minutes`, and the cloud's `--max-run-duration` with
   STOP. A session launch's cap is the bring-up's high bound plus its hours, rounded up (D-1123 section 4): 4 h for
   three hours, US$10.96 spot worst case (`tools/box_run.py launch_cap_hours`). There is no extension. A session cut
   by a pre-emption or a power cut is never opened again: more time is a new launch with new accounts and new links
   (D-1123 4.4).
6. **The ready line carries the boot id** (D-1120's rules). Each boot of a session run makes a random 16-hex id and
   prints:
   - `TB-SESSION-BOOT boot=<id> started=<t>` first;
   - `TB-SESSION-READY boot=<id> at=<t> stop=<t>` when it opens;
   - `TB-SESSION-NOT-READY boot=<id> ...` when it ends without opening;
   - `TB-SESSION-END boot=<id> ...` when the accounts are closed.

   `box-run.sh --session-status <run>` reads the whole serial buffer page by page. It counts only this boot's lines:
   the id with `--boot-id`, else the boot stamped after `lastStartTimestamp` (`session_vm.py boot-state`).
7. **Closed at the end and at the next boot.** `58-session-close` closes the session. So does any way the run ends,
   and the next boot of any run on the disk, before any step and before anything is served (the re-review's A): the
   box's Caddy, its only door (it alone publishes 443), is stopped, the console comes up without it, and the accounts
   are disabled. Only then does any step bring the whole stack up. A run of any kind stops there
   (`TB-SESSION-ACCOUNTS-OPEN`) when they cannot be closed so; there is no second try once the stack is up. The
   close:
   - disables the accounts (`UserStore.disable`: off, sessions ended);
   - takes their extra roles back and switches the acting flag off while the box is still a test box. A VALIDATION
     console refuses to start with either on record (D-877);
   - puts the box's settings back, its address (`TB_CONSOLE_PUBLIC_URL`) and its environment, then recreates every
     service that reads them but Caddy, always: a VALIDATION session on a VALIDATION box changed the address only
     (the re-review's F).

   The names wait in a root-only file on the disk until they are disabled. A close that cannot reach the console
   says `TB-SESSION-ACCOUNTS-OPEN` and is tried again at the next boot.

   Every session run that booted on the disk is listed there too. Once no session account is open on the disk, each
   listed run gets its `CLOSED` marker, even one that never opened an account (a refusal, a stop before 56, a cut):
   the driver keeps the door's deny until it says "closed" (the re-review's C). Step 56 sets its own run's marker to
   "open" before it opens any account (copied over it: the VM's gcloud reads secrets and copies, nothing else).
8. **The estimate** (`--estimate --steps dev,session [--session-hours N]`): the bring-up rows with their sources
   (D-1123 section 5), the owner's hours at the driver's constant, the cap, the worst case, spot and on demand. The
   running total is the integrator's figure, posted beside it (D-505).

9. **Never in part, never resumed** (the security review's findings 1 and 2; the refusal was chosen over a resume
   that would rebuild the door). A session's skip is its own (08 to 12), never the operator's, and nothing is redone:
   `tools/box_run.py session_values` refuses any other `--skip`, any `--redo` and `--only` (exit 6), and the VM's
   preflight refuses a skip of any step 50 to 58 and a `tb-redo`. A session run is never resumed: `--resume` of
   it is refused (exit 2), and the VM refuses a `tb-retry` on a session run, or on any run that opened a session on
   that disk. More time is a new launch (D-1123 4.4).
10. **SSH as it was** (finding 5). Ubuntu 24.04 starts sshd from `ssh.socket`. A session boot stops and masks both
    `ssh.socket` and `ssh.service`. It records what `systemctl is-enabled` and `is-active` said of each before
    (`records/sshd-before.txt`), and checks that nothing listens on tcp:22; if something does, there is no session.
    The next boot that is no session unmasks both and enables and starts what was enabled and active before.
11. **What cannot close by itself** (finding 6).
    - While the accounts are open, the console's and Caddy's restart policy is `no` (`docker update`; no compose
      file is changed), so they do not come back by themselves at a boot before the close runs. The close puts
      `unless-stopped` back. A policy that cannot be set stops step 56 before any account is opened (the
      re-review's E).
    - The close writes `CLOSED` beside the links. Until it exists, `--stop` keeps the deny-all and the tag
      (D-1130 item 7), and `--collect` and `--session-status` say "accounts not confirmed closed".
    - A run that is no session stops (`TB-SESSION-ACCOUNTS-OPEN`) when a session's accounts are still open after
      its second try.
    - What the driver cannot close: a manual start of the VM after the driver put the plain startup script back
      (`gpu-sim-startup.sh`) runs no close. The deny-all keeps the VM unreachable from outside until a box run's
      boot closes the accounts.
12. **What a session leaves on the disk** (findings 10 and 11). The close removes any code file left by a cut, and
    puts back the box's `TB_CONSOLE_PUBLIC_URL` (or removes it if there was none) along with `TB_ENV`. Every
    ingest (54) starts from an empty `acc/` feed folder, so a later accuracy run never ingests a table of the
    session's synthetic hospital. The rehearsal case `session-then-acc` holds both.
13. **The settings validated** (finding 8): `tb-session-code-hours` 1 to 72, `tb-session-idle-minutes` 1 to 999, in
    the VM's preflight. Names are at most 22 characters at the driver (finding 9: the VM adds a 10-character stamp).
    Steps given in any order take the direct route.

## Held by

`tests/unit/test_h13_session_driver.py`: the cap and the window, the launch's options, the session-check in both
environments, the status of this boot only.

The rehearsal cases (in `tests/unit/test_g1_box_install_run.py`):

- `session`: DEV, the happy path;
- `session-stop`: VALIDATION; asked 600 minutes, it closes before the cap fires;
- `session-cut`: a power cut in the session; the next boot closes it and never opens it again;
- `session-dev-refused`: the box refuses DEV at 52, before any data or account;
- `session-skip`, `session-resume`: refused at the VM's preflight, no account, no link;
- `session-ssh`: something still on tcp:22, no session;
- `session-then-acc`: a session, then an accuracy launch on the same disk: SSH back as it was, the address put back,
  `CLOSED` written, the feed holding only the accuracy run's own sets;
- `session-close-fails`: a cut, then the console cannot be asked at the next boot: the run stops before any step, the
  box's Caddy never came up on that boot, no `CLOSED` marker;
- `session-update-fails`: the restart policy cannot be set: no account, no link, the run's `CLOSED` marker written.

Every session case checks its `CLOSED` marker; `session-cut` checks that the next boot disabled the accounts with
Caddy down; `session` and `session-stop` that the console was recreated on the box's own address after the close.

## Not verified

Nothing ran on a real VM. Not known:

- whether the console can make the owner the PI of a new study on a box with no seed (D-1123 3.6);
- whether the synthetic hospital's practitioner rows sit well beside the public sets' in one feed (their headers
  match, checked here; their chart numbers do not overlap);
- whether Caddy's access log carries `client_ip` as the box's Caddy version writes it;
- whether the console's container finds `console.steps_roles` on its path as the session's snippet imports it.
