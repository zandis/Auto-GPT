# D-466 The box installer and the first-run wizard

- **Task:** T-729 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.5, wave B: the box)
- **PR:** this branch (`agent/T-729-box-installer-wizard`)
- **Date:** 2026-11-12
- **Status:** accepted for the parts built here; the real-box run is T-213b's (see "What only a real box proves")
- **Owner decisions:** OD-10 (no fixed limit not derived from the hardware), OD-11 (a dedicated box: a GPU
  workstation or a DGX Spark), OD-12 (the owner is the data steward and, by default, the administrator), OD-13 (the
  audience is the owner, not hospital IT; two forms: a box prepared by Aimedics, one installer for hardware the site
  bought), OD-14 (five kinds of data source)
- **Builds on:** T-632 / D-382 (site inputs, TLS on, the finished install), T-214 / D-373 (the GB10 forms), T-634 /
  D-408 (host baseline, sealed keys), T-210b / D-347 (the KEK), D-192 (TOTP), D-176 (the box-install rehearsal),
  D-315 (one site zone), D-360 (memory caps)

## Survey: what an install asks today, and who can answer it

Read on master `fff16fe4`: `deploy/install.sh`, `tools/settings_wizard.py` (41 questions), `deploy/check_host.sh`,
`deploy/gpu_profile.sh`, the three GPU overlays, `deploy/hardening/` (`seal_keys.sh`, `hardening.example.conf`),
`deploy/identity/` (Caddyfile, TLS modes), RUNBOOK §1, §12 and §16, `tools/rehearse_box/`.

| Question or decision today | Asked by | Who can answer | The box form |
| --- | --- | --- | --- |
| Tier / `--gpu` profile / `--mode gpu\|stub` | install flags | nobody (a fact of the machine) | derived: `deploy/gpu_profile.sh` on the detected card; the owner only confirms the hardware shown |
| Site id (`site_id`, upper case) | wizard | nobody (an internal key) | derived from the site name (a hash when it has no Latin letters) |
| Site name | wizard | owner | asked in the first-run wizard |
| Time zone (`tz`, no default, D-315) | wizard | owner | asked (the host's zone offered); the host is set to it at apply |
| Report language (`locale`) | wizard | owner | asked (en, ja, zh-TW) |
| Box contact mail | wizard | owner | the owner's own mail address |
| Internal mail domains, intake mailbox, allowed senders, physicians, reviewers | wizard | IT (domains, mailbox) / owner (people) | derived from the owner's mail address; the mail intake is an optional IT step (one page, T-735); people are added on the box |
| Alliance boxes, cohort rulesets, alliance root | wizard | owner, later | defaults (none); set on the box later |
| HIS source type, source path, feed folder, DSN variable, mapping file, MRN pattern | wizard | IT (path, DSN) / nobody (mapping) | the owner picks one of OD-14's kinds (or "later"); the folder and the DSN variable are fixed by the box; the mapping is a box mapping stating the site's zone until T-731's mapping step; the read connection's address and account are the one thing IT gives |
| Consent registry type and path | wizard | IT | default `none`; T-731 |
| Departments, practitioners | wizard | owner, later | none at first; the steward's pages |
| LLM gpu/stub | wizard | nobody | derived from the profile |
| Cloud LLM, TWPAS, NHI code | wizard | owner/IT, rare | defaults off |
| Attachment encryption, console URL for mail links | wizard | nobody / IT | `link` and `https://<box name>` |
| SMTP and IMAP hosts, ports, user; MTA authserv-id | wizard | IT | empty: the box works without mail; mail is an optional IT step (T-730 tells the owner another way) |
| TLS host name (`tls_hostname`) | wizard, then install.sh prompt | IT (a DNS name) | the box's name the owner picks, `.local` added (mDNS); a DNS name from IT later is optional |
| TLS mode (`hospital` default in the wizard; `internal` written by install.sh only when a name is typed at its prompt, never asked) | wizard / install.sh | IT | **resolved here**: the box is `internal` with the owner's box name, explicitly; `hospital` is IT's optional step |
| Certificate and key files | wizard | IT | none (internal CA) |
| Retention rules and days | wizard | nobody (law of the country) | derived from the zone (Japan's for Asia/Tokyo, else Taiwan's) |
| ClinicalTrials.gov offline/live | wizard and install.sh | owner/IT | offline (D-140's default); changeable on the box |
| `TB_ACCEPT_UNMEASURED_GPU` (no serving record) | env | Aimedics | unchanged: the owner cannot accept an unmeasured card; Aimedics measures (prepared image) or decides in a supervised session |
| Memory caps (`TB_MEM_*`) | compose defaults | nobody | derived from the RAM (OD-10), the compose defaults as proportions |
| Service passwords, tokens, model key | generated | nobody | unchanged (generated) |
| First administrator (`bootstrap-admin`, printed password, enrolment code) | install.sh | nobody chooses: printed | the first-run wizard: the owner chooses the password and adds the authenticator; no password is printed |
| Clinic ranges for 443, SSH, KEK back end, Tang URLs (`hardening.conf`) | a file filled in with IT | IT | derived: the box's own network from its address, SSH off, KEK `tpm` where the board has one, else a passphrase the owner sets in the wizard; Tang is the IT-managed form (T-634) |
| Disk unlock (LUKS + TPM + Tang) | IT at OS install | IT | not changed here (see Open) |
| Backup key (`backup-keygen` with IT), backup targets, alert route | IT | IT / owner | the owner picks a second disk or a share (or later) in the wizard; the target and the owner's mail as the alert address are derived; the key ceremony is T-730's |
| Feed folder exists, cron files, systemd units, egress rules, network sheet | install.sh | nobody | unchanged (install.sh) |

So of 41 wizard questions and about 10 install-time decisions, the owner can answer 7; the rest are facts of the
machine, defaults, or IT's, and IT's are now optional except the read connection of a database source (OD-13).

## Decision

1. **One answers schema** (`libs/tb_common/box_answers.py`, standard library only): site name, time zone, language,
   the owner (name, user name, mail), the box's name, the backup destination (`second_disk` from the detected
   disks, `share` by address, or `later`) and the data source kind (OD-14's five as an enum, plus `later`). The
   password, the second factor and the passphrase never enter the schema: the console checks them.
   `owner_accounts()` is the one seam for duties (T-736): today it returns the owner as `steward` and
   `<name>-admin` as `admin`, one password and one authenticator, because a console account has one role and the
   administrator reads no patient data (D-280).
2. **One plan function** (`tools/box/plan.py`, standard library only, runs on the host before any image exists):
   answers + detected hardware (`detect()`: `nvidia-smi`, `/proc/meminfo`, `lsblk`, `ip`, the TPM device) give the
   settings wizard's answers file, the extra `.env` lines (`env_extra`, declared `TB_*` names only, which
   `tools/settings_wizard.py` now accepts), the install flags and the site files (`site/hardening.conf`, the box
   mapping). The profile comes from `deploy/gpu_profile.sh` (one rule). Memory caps (OD-10): the RAM less a tenth
   (at least 4 GiB) and the fixed small caps is shared out in the proportions of the compose files' own
   `TB_MEM_*` defaults; when they do not fit every cap shrinks by one factor; below half the machine is refused
   (the services were never measured there); with room to spare the services grow and the model servers keep
   their default. The Spark's caps are its profile (`deploy/gb10-profile.yaml`), so nothing is derived for `gb10`.
3. **TLS on a box is `internal` with the owner's box name**, set explicitly in the answers (`tls_mode: internal`,
   `tls_hostname: <name>.local`). The IT-managed path keeps its own rule (wizard default `hospital`).
4. **The first-run wizard** is `/login/first-run` in the console (`services/console/firstrun.py`, en, ja, zh-TW,
   checked against `tb_common.wording`). It is part of the sign-in surface (no session, no role: no `permit` row,
   and the role and wording walks skip `/login/*` as before). It opens only when `TB_FIRSTRUN_DIR` names the
   first-run folder (`/run/trialbox-firstrun`, tmpfs, `deploy/docker-compose.box.yml`), the folder holds a live
   one-time code (`tb_common.firstrun`: about 79 bits, only its hash kept, five wrong codes void it), and the box has
   no account; it answers 404 otherwise. The code is shown by the installer on the box's own screen, so the person
   at the box is the one who makes the first account: the code plays the part the administrator's enrolment code
   plays for every later account (D-192), and the owner adds the authenticator in the wizard with a code from it. A
   password is never printed. The answers go to the tmpfs folder (0600) for the installer's apply step; the code is
   used up when the accounts exist. Audited as `console.first_run` (a wrong code, and the accounts made).
5. **The installer entry** is `deploy/box-install.sh`, a thin script over `install.sh`: it detects the hardware,
   shows it and asks one question (is this the machine?), plans with provisional answers, runs `install.sh` with the
   plan's flags and answers file (`TB_BOX=1`: the box overlay, no `bootstrap-admin`; `TB_BOX_DEFER_SEAL=1` on a board
   without a TPM, so the keys are sealed at apply under the owner's passphrase), makes the one-time code, prints the
   address and the code, writes them to `/etc/issue.d/` (the box's console screen), and waits for the wizard. Then
   it applies (`python -m tools.box apply` in the image: settings rewritten from the owner's answers, the owner's
   lines merged into `deploy/.env` with the install's passwords kept, the host's zone set, the keys sealed when
   deferred) and runs `install.sh` again from the signed tree. `--prepare` is the prepared-image form: the same
   steps, stopping before the code; `--firstrun` (run once at the site's first boot by
   `trialbox-firstrun.service`) makes the code and goes on.
6. **The IT-managed and shared-host paths are unchanged** (v6.1 §4.4): `install.sh` without `TB_BOX` behaves as
   before; the settings wizard without `env_extra` writes the same files.

## What only a real box proves (for the owner's rental-workstation run, T-213b)

- the bundle loads and the stack starts from `box-install.sh` on a real workstation and on a Spark (no Docker
  daemon here);
- the detected hardware (`nvidia-smi` of a real card, `lsblk` with a second disk, `ip`, `/dev/tpmrm0`) matches the
  machine, and the confirmation screen is what the owner sees;
- `https://<name>.local` resolves from a team computer (mDNS) and Caddy's internal certificate is accepted once its
  root is installed (the download page is T-735's);
- the wizard on a phone and a PC, the code from the box's screen (`/etc/issue.d`), the apply step's restart, the
  sign-in over HTTPS and `trialbox doctor` passing afterwards (backup needs the second disk mounted: T-730);
- the TPM seal and unseal across a reboot, and the passphrase path on a board without a TPM;
- the derived memory caps under a real night (T-687's scale gate measures them).

## Open (not built here)

- Mounting (and, with the owner's confirmation, formatting) the chosen second disk, mounting a share and its
  credentials, the backup key ceremony and the message path to the owner: T-730.
- Disk unlock on a box: the host check FAILs a disk the TPM alone opens (D-408), which is IT's form with Tang. A box
  needs its own rule (TPM plus a PIN the owner types, or the passphrase): a decision for T-730/T-735 with the owner.
- The owner's two accounts become one account with both duties, or the administrator goes to another person: T-736
  changes `owner_accounts()` and the role matrix (OD-17).
- The root certificate download for the team's computers and the owner's set-up page: T-735.
- A card with no serving record cannot be installed by the owner (D-112 stays): the Spark has no vendor record yet.
  T-734's measured statement, or Aimedics measuring before shipping, closes it.
