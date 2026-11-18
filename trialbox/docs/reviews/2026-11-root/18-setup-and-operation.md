# Root review 18: setting up and running the box in a hospital whose IT team is small (lane J, job B20, 2026-11-18)

**Reader:** the owner first (section 0, one page), then lane D (installer, bundle, operations), lane C2 (console
pages), lane J (Japanese pages) and the integrator (the cards of section 8 for plan 10, the decisions of section 9).

**The owner's words (2026-11-18).** "This is on prem, so the IT probably not that strong, so setting up cannot be too
complicated." He also ruled that the first site receives the complete release, not a cut of it ("I want it complete,
it's difficult to track all not done features"), and that the site questionnaire goes through the hospital's IT
department.

**What was analysed:** master `273b1e149`: `deploy/` (the two installers, the bootstrap, the media preparation, 13
compose files, 12 systemd units, cron, hardening, backup, update), `tools/trialbox` (29 commands), `tools/box`,
`tools/settings_wizard.py`, the console's first-run, operations and health pages, the 35 runbook pages and the
hand-over pages. Commands that need no stack were run from a sparse checkout with the main checkout's `.venv`
(section 11). No box was started, no image built, nothing installed. Public sources were opened on 2026-11-18
(section 12).

**What this page does not repeat (and goes under):** review 01 (the system by layer), 07 (IQ/OQ at the site; card
B7-16 `trialbox validate --stage iq`), 10 (packaging, update, backup as code: section 5; AQ-25 health page), 12 (the
site profile and the questionnaire, section 9), 13 (the installer choosing a tier profile, section 5.3; start-up never
timed, section 7.2), 16 (the documents a Japanese IT department asks for, section 4.1; the update path, section 2.4;
hardening), plan 10 (its cards are cited by id: 10B-19, 10E-1, 10E-15, 10G-13 ...). The first site is "the first site
(a general hospital in Japan)"; it is not named.

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[M n]** | Measured: row n of section 11 gives the command and the number |
| **[R]** | Read: the file and line follow in backticks |
| **[S n]** | Source: row n of section 12 (link, date opened, licence or terms) |
| **[rev NN]** | Taken from review NN (or plan 10 as [P10]) with that review's own mark |
| **[O]** | Opinion: this page's judgement, to be argued with |
| **not verified** | Could not be checked here; section 13 lists each |

---

## 0. One page for the owner

**Is setting up simple enough for a small hospital IT team today? No, but most of the parts that would make it simple
already exist; they are not joined, not in Japanese and never run on real hardware.**

What is good [R; O]:

- There is already an **appliance-style path**: `deploy/box-install.sh --prepare` lets Aimedics install the box
  before shipping; at the site the box shows a one-time code on its screen, and the owner finishes in a **browser
  wizard** of about 16 answers, in Japanese, English or Chinese (`deploy/box-install.sh:1-35`;
  `services/console/firstrun.py:1-20`) [R; M 7].
- Updates are **signed, checked, backed up first and rolled back automatically** on failure, and can be scheduled for
  the quiet hour from the console's Operations page [R `docs/runbook/05-updates-backup-restore-secrets.md:5-27`].
- Backups are encrypted to a key the box does not hold, and a **restore drill into scratch databases** exists
  (`trialbox restore-drill`) [R `05-updates-backup-restore-secrets.md:162-173`].
- The box needs **no internet**; a hospital's firewall opens one port inward (443) [R
  `docs/handover/it-one-page.ja.md`].

What is not good enough for the first site [M; R; O]:

1. **The path a Japanese hospital would actually follow is the IT form, and it is long.** From a bare machine to the
   first screened list a person meets about **30 steps across five people**, **44 settings questions in English**
   with **Taiwan defaults** (report language Chinese, Taiwan mapping, Taiwan retention), **three files written or
   edited by hand**, **about seven keys or secrets** to create and hold, **about ten typed commands** and **about 44
   pages** of English runbook (section 1) [M 3, M 4, M 5].
2. **Several wrong answers are silent.** Leave the report language at its default and a Japanese hospital gets
   Chinese reports and Taiwan's retention periods; the SS-MIX2 source cannot be chosen in either wizard; backups go
   to the box's own disk unless someone edits `deploy/.env` by hand (section 1.8) [R].
3. **Operations need a terminal.** The console can back up, check, verify and apply an update. Everything else that
   matters (the health check `doctor`, the restore drill, restore, keys, certificates, moving, decommissioning) is a
   root command in English. The health page does not notice a data feed that stops (section 2) [R; M 2].
4. **The operations drills are promised, not built.** The runbook names 14 drills that "prove" each procedure; 1
   exists (section 2.3) [M 6]. No restore has ever been timed; nothing after key sealing has run on a real GPU
   machine with the real installer [R].
5. **The operator is thin.** In Japan "0" is the most common number of full-time IT staff a hospital reports; a
   500-bed hospital has a median of 4 and leans on its chart vendor; only about 1 in 10 uses the government's
   responsibility-split form; half keep an offline backup (section 3) [S 1, S 2, S 3].

**The five changes that matter most** (section 8 has the cards):

1. **Deliver the first site a vendor-prepared machine** and fill its answers before shipping from the IT
   questionnaire (a signed "site seed"), so the site does eight things in a browser, edits no file and types no
   command (SO-2, SO-3; decision SO-D1).
2. **A live preflight inside the wizard**, in Japanese: name, certificate, time server, the backup share, the audit
   share, the data feed, mail, TPM, disk, GPU; green or red with what to do (SO-3, SO-4).
3. **Japanese defaults and a Japanese operator's page**: the wizard knows a Tokyo site; `doctor`, the daily duties and
   the update, backup and restore steps are in Japanese and on the console (SO-1, SO-5, SO-10).
4. **Update, restore rehearsal and key ceremonies as guided console pages** with a USB stick inserted at the box and
   two people present, so the hard steps stay hard on purpose but stop being terminal work (SO-7, SO-8, SO-13).
5. **A capability page** ("what this site has: installed, switched on, working, validated, not yet available, and
   why") fed by the same records `doctor` and the tier record use, so "complete" is shown, not argued (SO-11, SO-12;
   section 6).

**What it costs.** Code: about 9 S, 10 M and 3 L cards (section 8). Money: one clean-VM follow of the box form for
about US$0.34 (no GPU) inside the cap [R `docs/plan/measurements/runbook-install-2026-11-17.md:196-200`]; a spare
prepared box in Japan if decision SO-D8 says yes (the price of a second workstation, not priced here); the support
partner (plan 10 decision 69) does the on-site day.

---

## 1. Today's set-up, measured as a hospital IT person meets it

### 1.1 Three ways to install, and which one a Japanese hospital meets

| Form | Entry | Who it was built for | What it asks | Ever run on real hardware? |
| --- | --- | --- | --- | --- |
| **IT form** | the bootstrap from the USB stick, then `deploy/install.sh --tier <t> --answers site.yaml` [R `docs/runbook/01-install-a-new-site.md:27-36`] | "Aimedics and hospital IT" [R `01-install-a-new-site.md:3`] | the settings wizard's 44 questions (or an answers file), plus the start question and three more when missing [R `tools/settings_wizard.py:51-115`; `deploy/install.sh:668`] [M 4] | The bundle verified and loaded and the keys made on a GPU VM; it stopped at TPM sealing; "nothing after key sealing has ever run on a real box" [R `docs/handover/installer-first-contact-2026-11-15.md`]. In a container it reaches a started stack (H-24), except the embedder in no-GPU mode (open) [R `runbook-install-2026-11-17.md:5-13`] |
| **Box form** | `box-prepare.sh` (offline packages from the media), then `box-install.sh` (or `--prepare` before shipping), then a browser wizard on a one-time code [R `deploy/box-prepare.sh:1-20`; `deploy/box-install.sh:1-35`] | "set up by its owner, with no shell knowledge and no question an IT department would be asked" [R `box-install.sh:2-3`] | about 16 answers in three languages [M 7] | In the rehearsal container only (`tools/rehearse_box`); no record of a real machine found [R; **not verified** beyond a search of `docs/`] |
| **Windows form** | `deploy/windows/box-install.ps1` (1,425 lines) under WSL2 [M 5] | the owner's own PC (P-0) | as the box form | P-0 rehearsal pages exist [R `docs/handover/P-0-windows-rehearsal.md`] |

[O] The box form is the right base for a hospital with a small IT team; it was designed for a research lead as
"owner" (OD-13), so it hides the very questions a Japanese 情報システム部門 must answer (network, certificate,
shares, the feed). The IT form asks them all, in English, with Taiwan defaults. The first site needs the box form's
experience with the IT form's questions answered **before** the box arrives, from the questionnaire.

### 1.2 Prerequisites a person must provide before the first command (IT form)

| # | Prerequisite | Who | Where it is said | Needs the internet? |
| --- | --- | --- | --- | --- |
| P1 | Ubuntu 24.04 LTS installed, on LUKS2 with TPM2 (or Tang) unlock, swap off | hospital IT | [R `01-install-a-new-site.md:95`]; disk unlock "hospital IT's, once, at OS install" [R `deploy/install.sh:31-33`] | the OS image; no after |
| P2 | Docker Engine 27+ and its compose plugin, nftables, `python3-yaml`, `python3-cryptography`, `curl`, `cron`, `openssl` | hospital IT | [R `01-install-a-new-site.md:95-98`] | yes, or the hospital's mirror; the box form brings them on the media (`box-prepare.sh`) [R `box-prepare.sh:11-13`] |
| P3 | NVIDIA driver and container toolkit, held at a version | hospital IT | [R `01-install-a-new-site.md:98-99`] | as P2 |
| P4 | A fixed address and an internal DNS name | hospital IT | [R `docs/handover/it-one-page.ja.md` §1] | no |
| P5 | A certificate from the hospital's CA for that name, or Caddy's own CA with its root pushed to every clinic PC by group policy | hospital IT | [R `01-install-a-new-site.md:81-83`; `docs/runbook/12-identity-and-tls.md`] | no |
| P6 | Firewall: 443 in from clinic PCs; NTP (UDP 123) to the hospital's time server | hospital IT | [R `it-one-page.ja.md` §3] | no |
| P7 | An SMB or NFS share for off-box backups, mounted at boot | hospital IT | [R `05-updates-backup-restore-secrets.md:89-94`] | no |
| P8 | A second share or folder for the signed audit heads, mounted at boot **before Docker**, readable by the console's user | hospital IT | [R `docs/runbook/02-daily-operation.md` "The console reads the same folders"] | no |
| P9 | The feed folder holding the hospital's **first export** before the first command (for the first site: a read-only copy or mount of the SS-MIX2 storage) | hospital IT, the chart vendor | [R `01-install-a-new-site.md:78-81`] | no |
| P10 | Mail relay and the MTA's `authserv-id` (optional, but mailed requests are refused without it) | hospital IT | [R `01-install-a-new-site.md:121-123`; M 2 `mail_auth`] | no |
| P11 | The vendor's public key, received apart from the stick, placed at a path | IT, from Aimedics | [R `01-install-a-new-site.md:27-32`] | no |
| P12 | A site folder with `site.yaml` (the wizard's keys) and the site's mapping YAML | IT with the data steward | [R `01-install-a-new-site.md:74-77`] | no |

Count: **12 prerequisites**, 10 of them hospital IT's [R; counted here]. The IT one-page tells IT it is asked "only
three things" (an address, the data connections, the firewall) [R `it-one-page.ja.md:3-4`]; that page is true of the
box form, not of the IT form's §1 [O].

### 1.3 From a bare machine to the first screened list (IT form), step by step

Counted from §1, §5, §6, §12 and the new-study walk; each row is one thing a person must do [R; counted here].

| # | Step | Who | Terminal or browser |
| --- | --- | --- | --- |
| 1-12 | Prerequisites P1 to P12 above | IT (10), Aimedics (1), IT and steward (1) | OS installer, terminal |
| 13 | The one command: `openssl pkeyutl -verify ...` then the bootstrap with `--tier` and `--answers` (one typed line of about 230 characters) [R `01-install-a-new-site.md:32`] | IT | terminal |
| 14 | Answer "Start the stack now? [Y/n]" and, when missing, three more questions [R `install.sh:668`; `01-install-a-new-site.md:52-55`] | IT | terminal |
| 15 | Copy the printed administrator password and enrolment code (shown once) [R `01-install-a-new-site.md:39-40`] | IT | terminal |
| 16 | Edit `deploy/.env`: off-box backup target, anchor folder, log and audit archive folders, patient count (`TB_SITE_PATIENTS`, "before the first install") [R `install.sh:663-665`; `01-install-a-new-site.md:57-61`; `02-daily-operation.md`] | IT | editor |
| 17 | Re-run the installer so the anchors are mounted and the backup schedule picks up the target [R `02-daily-operation.md`; `05-...:95-102`] | IT | terminal |
| 18 | Make the backup key pair with IT, private key to a USB stick, into a sealed envelope; re-run `backup-install` [R `05-...:74-76, 95-102`] | IT and administrator | terminal |
| 19 | Check the mapping against an export with a `docker run` line of about 300 characters [R `01-install-a-new-site.md:124-129`] | steward | terminal |
| 20 | First ingest by hand, then read the report from inside the container [R `01-install-a-new-site.md:139-143`] | steward | terminal |
| 21 | `deploy/check_host.sh`: no FAIL [R `01-install-a-new-site.md:144`] | IT | terminal |
| 22 | `trialbox doctor --env-file deploy/.env`: no FAIL [R §22 step 6] | IT | terminal |
| 23 | Make the accounts: each coordinator, investigator, steward gets an enrolment code; each sets a password and an authenticator [R `docs/runbook/03-accounts.md:5-12`] | administrator, each user | browser |
| 24-34 | A new study to its first list: 11 steps by four roles (protocol, criteria, PI approval, steward's dry run of the not-matched check, IRB text record, run) [R `docs/handover/new-study-walk.en.md` steps 1-11] | coordinator, PI, steward, administrator | browser |
| 35 | Restore drill before go-live acceptance [R `05-...:172-173`; `docs/runbook/06-go-live-acceptance.md`] | IT with the key | terminal |

**Count:** 35 rows, about **30 distinct actions** once the prerequisites are grouped, by **five people** (IT,
Aimedics, steward, administrator, the trial team) [counted here]. Steps 13 to 22 and 35 are terminal work as root.

### 1.4 Decisions the installer asks

| Form | Questions | Language | Defaults that fit Japan? |
| --- | --- | --- | --- |
| IT form, settings wizard | **44** [M 4] | English, except the ClinicalTrials.gov question in three languages [R `settings_wizard.py:118-131`] | No: report language `zh-TW` [R `settings_wizard.py:55`]; mapping `mapping/tw_core/demo_his.yaml` [R `:68`]; MRN `^\d{8}$` [R `:69`]; TWPAS and an NHI code asked [R `:84-87`]; the source question offers `csv | cgrd_sql | fhir_bulk` [R `:63`] though the schema also allows `ssmix2` [R `schemas/settings.schema.json:130-135`]; time zone has no default (good, D-315) [R `:54`] |
| IT form, installer | 1 to 4 (start; and `ctgov_mode`, `tls_hostname`, `sae_office_mailbox` when missing) [R `01-install-a-new-site.md:52-55`] | English | – |
| Box form, first-run wizard | about **16 answers** after the code: site name, time zone, language, owner's name, user name, mail, password, authenticator code, box name, backup kind and disk or share, data source kind, chart-number rule (kind, width), KEK passphrase (no TPM) [M 7] | en, ja, zh-TW (80 messages each) [M 7] | Partly: choosing "EMR feed (SS-MIX2)" sets a CSV source and says the connector and mapping step come later on the box [R `tools/box/plan.py:452-460`]; TLS is Caddy's own CA by default [R `plan.py:502`] |

### 1.5 Files a person writes or edits by hand

| File | Today | For whom |
| --- | --- | --- |
| `site.yaml` (answers) | written by hand in the IT form, 44 keys, English keys [R `settings_wizard.py:51-115`]; the box form writes it from the wizard [R `tools/box/plan.py`] | IT form only |
| the site mapping `mapping/<...>/<site>.yaml` with its lab lookup | copied from a template and edited by hand [R `01-install-a-new-site.md:124-129`]; the box form defers it (T-731) [R `plan.py:413-416`] | both forms |
| `deploy/.env` | edited for backup targets, anchors, log folders, patient count, log caps, mail ids, SSO headers, monitoring [R `02-daily-operation.md`; `05-...`; `01-...:148-151`; `15-operations-screens.md` "Optional monitoring overlay"] | both forms after install |
| TLS certificate and key files | placed by hand (hospital mode) [R `docs/runbook/12-certificate-renewal.md:13-17`] | both |
| `deploy/watchdog/maintenance` | a JSON written by hand to hold services still [R `05-...:110-112`] | operations |

The product reads **519 declared `TB_*` settings** [M 3]; the runbooks name **191** of them [M 3]. A hospital IT
person never needs most of them [O]; but the runbooks send him to `deploy/.env` for at least nine [R, rows above].

### 1.6 Secrets and keys a person must create or hold

| # | Secret | Made by | Held by | Interface |
| --- | --- | --- | --- | --- |
| K1 | Disk unlock (LUKS recovery passphrase; TPM, Tang or TPM+PIN) | IT at OS install | IT | OS installer, `deploy/hardening/disk-unlock.sh` [R] |
| K2 | KEK for the site keys (TPM seal, Shamir shares or a passphrase) | the installer or `python -m tools.keys` | key stewards [R `docs/runbook/23-key-inventory-and-the-lost-box-list.md`] | terminal |
| K3 | Backup private key | `trialbox backup-keygen` | IT, sealed envelope [R `05-...:74-76`] | terminal |
| K4 | pgBackRest cipher (point-in-time restore) | `backup-install` | the box, and a copy "with the backup key" [R `05-...:144-148`] | terminal |
| K5 | Vendor public key | Aimedics | the box, received apart from the stick [R `01-...:27-32`] | file |
| K6 | TLS key (hospital mode) | IT | the box [R `12-certificate-renewal.md`] | file |
| K7 | First administrator's password and enrolment code | the installer, printed once | the administrator [R `01-...:39-40`] | terminal, then browser |

Plus each user's password and authenticator (browser) and the hospital's mail credentials (in `deploy/.env`) [R
`05-...:291-293`]. Service tokens and database passwords are made by the box itself (`secrets init`) [R `05-...:280-290`].

### 1.7 Commands typed and pages to read

- **Commands.** §1 holds 28 commands; the measured follow ran 4 of them on the path, with 24 "not needed" by the
  runbook's own reasons [R `runbook-install-2026-11-17.md:45-46`]. Adding the hand edits and checks of section 1.3
  (re-run, `backup-keygen`, `check_host`, `doctor`, the restore drill, the report read), a careful IT person types
  **about ten** root commands, three of them over 200 characters [counted here; O].
- **The command-line tool** has **29 sub-commands**, each named in English [M 1]; `doctor` has 16 options [M 1].
- **Pages.** The 35 runbook files hold 43,753 words; the sections whose reader is the owner, IT or Aimedics (§1 to
  §7, §12, §15, §20 to §25 and their parts) hold **21,993 words, about 44 pages** at 500 words a page [M 5]. **5 of
  2,611** non-empty runbook lines contain any Japanese, all of them quoted terms [M 5]. The Japanese pages an IT person
  gets are the one-page, the network sheet, the owner's Windows pages, desktop use and the new-study walk [R
  `docs/handover/*.ja.md`].

### 1.8 Where a wrong choice is silent

| # | Choice | What happens | How loud today | Evidence |
| --- | --- | --- | --- | --- |
| W1 | Report language left at its default in the IT wizard | a Japanese site's reports in Chinese; retention defaults from "tw" (mail logs 2,555 days instead of 1,825) | silent | [R `settings_wizard.py:55, 432-433`; `02-daily-operation.md` "Mail logs"] |
| W2 | The source type (IT wizard) | SS-MIX2 not offered in the question text; a person picks `csv` | silent | [R `settings_wizard.py:63`] |
| W3 | "EMR feed" in the box wizard | becomes a CSV source with "set up later" | a warning line | [R `plan.py:458-460`] |
| W4 | Backup target not edited | backups on the box's own disk; the run "fails and stays red" in PRODUCTION | red tile after the fact; the install itself completes | [R `install.sh:665`; `05-...:93-94`] |
| W5 | Backup alert route `health-page` | nobody is mailed; "someone must open the health tab every working day" | a `doctor` WARN | [R `05-...:100-102`] |
| W6 | Chart-number rule left empty | `asis`; leading zeros significant; cannot be changed once patients are loaded | a warning | [R `settings_wizard.py:243-250`; `01-...:65-72`] |
| W7 | Caddy's own CA (box default) | every clinic PC needs the root pushed; personal devices never work | a wizard warning | [R `plan.py:502`; `01-...:82-83`] |
| W8 | Anchor share not mounted at boot | the console does not start | loud, but at the next reboot, not at install | [R `02-daily-operation.md` "The console reads the same folders"] |
| W9 | `TB_SITE_PATIENTS` not set | memory caps not compared with the hospital's size | a `doctor` WARN | [M 2 `memory_caps`] |
| W10 | Host time zone not the site's | records near midnight move a day | a `doctor` FAIL (good) | [M 2 `site_tz`] |

### 1.9 What needs the internet

On the box: nothing, except ClinicalTrials.gov when the hospital chooses "live" [R `install.sh:57-59`]. Before the box:
the OS and its packages in the IT form (P2, P3), unless the hospital has a mirror; the box form carries them on the
media [R `box-prepare.sh:11-13`]. On the vendor's side: building images needs Docker Hub, Maven Central and GitHub [R
`01-...:100-103`]. [O] For a closed hospital network the box form's offline media is the only form that needs nothing
from outside the hospital.

### 1.10 What a person sees: `doctor`, the wizards, in English and Japanese

Run here on a checkout in PRODUCTION mode with the example settings (no stack) [M 2]: 37 checks, 21 PASS, 8 WARN, 8
FAIL, all in English, each line naming settings (`TB_SAE_OFFICE_MAILBOX`, `TB_MAIL_AUTHSERV_ID`,
`TB_AUDIT_ANCHOR_TARGETS`), decision numbers (D-736, D-562) and a command to run. Samples:

```text
FAIL  note_block   TB_NOTE_BLOCK=both_agree but no verifier configured: SCREEN runs single-model and falls back to never-exclude (D-97); ...
FAIL  site_tz      the site's time zone differs: site.tz Asia/Taipei, mapping tz (demo_his.yaml) Asia/Taipei, host zone Etc/UTC; ...
WARN  mail_auth    no TB_MAIL_AUTHSERV_ID: every mailed FEAS or SCREEN request is refused until the hospital MTA's authserv-id is set ...
```

`doctor` has no Japanese output and no console page [R `tools/trialbox/doctor.py`; `services/console/ops_pages.py:39-45`].
The settings wizard and `install.sh --help` are English [M 4, M 8]. The first-run wizard and the Operations page are
in three languages (`services/console/i18n_firstrun.py`, `i18n_ops.py`) [R]. The hardware detection runs with the
host's own Python and returned the facts the box form plans from (CPU, memory, disks, TPM, time zone) [M 9].

### 1.11 The set-up in numbers

| Measure | IT form | Box form | Source |
| --- | --- | --- | --- |
| Prerequisites before the first command | 12 | about 6 (machine, address, name, shares, feed, key) | 1.2 [R] |
| Distinct actions to the first screened list | about 30, five people | about 10 to the console, then the study's 11 | 1.3 [R; counted] |
| Questions | 44 + up to 4 | about 16 | [M 4, M 7] |
| Files written or edited by hand | 3 (answers, mapping, `.env`) | 2 (mapping later, `.env`) | 1.5 [R] |
| Secrets and keys to hold | 7 | 7 | 1.6 [R] |
| Root commands typed | about 10 | 3 to 4 (prepare, install, then `.env` and keys) | 1.7 [R; O] |
| Runbook to read (owner, IT, Aimedics sections) | about 44 pages, English | same | [M 5] |
| Silent wrong choices | 10 rows in 1.8 | 5 of them | 1.8 [R] |
| Internet needed at the site | OS packages, unless a mirror | none | 1.9 [R] |
| Ever run end to end on real hardware | no | no | 1.1 [R] |

---

## 2. Operation today

### 2.1 Daily and weekly duties

| When | Duty | Where a person looks | Console or terminal |
| --- | --- | --- | --- |
| Every working morning | the health line at the top of the coordinators' 07:00 mail; the daily health mail to administrators [R `15-operations-screens.md` "Where it shows"] | mail | – |
| Every working day, if no mail | open the health tab ("someone must open the health tab every working day") [R `05-...:100-102`] | `/admin` | console |
| After a red line | `trialbox doctor --env-file deploy/.env`, `ops status`, the troubleshooting table [R `21-support-...` "Who answers"] | terminal | terminal |
| Quarterly | restore drill with the key from the envelope, typed on the host [R `05-...:162-173`]; the DR list checked [R §22 "The quarterly drill"] | terminal | terminal |
| Monthly | host OS patches by hospital IT, driver held [R `24-patch-policy.md`] | terminal | terminal |
| Yearly | `secrets rotate` [R `05-...:283`]; certificate renewal (hospital mode) [R `12-certificate-renewal.md`] | terminal | terminal |
| After the first full night | re-size log caps from `COVERAGE.json` [R `02-daily-operation.md` "Log gaps"] | `.env` | terminal |

The health page is built from eight check functions: model self-test, opt-out worker, derived scores, backup, backup
verified, disks, certificate, desktop GPU [R `libs/tb_common/metrics.py:158-284`]. **It has no check that the data feed
arrived** (the last good ingest, its rows, its gate) [R, same lines]; review 10 asked for it (AQ-25) [rev 10].

### 2.2 Each event, as an operator meets it

| Event | Steps today | What goes wrong silently | Console shows | Needs a terminal |
| --- | --- | --- | --- | --- |
| **Backup** | automatic nightly 04:45, hourly status, off-box target required in PRODUCTION [R `05-...:95-129`] | an on-box-only target (W4); the alert route `health-page` with nobody looking (W5) | Backups tile, age, red after 36 h; "Back up now"; "Check the newest backups" [R `15-...`] | key making; restore drill |
| **Restore** | 9 steps with three items from three holders (file, private key, reference pack), stop services, `restore`, re-apply listed events, release the hold [R `05-...:175-233`; §22] | a missing reference pack exits 3; events after the backup must be re-done by a steward (exit 4) | nothing until the restore ends | **all of it** |
| **Restore rehearsal** | `restore-drill` into scratch databases, at least every 90 days [R `05-...:162-173`] | none rehearsed on hardware; "No restore has been measured yet" [R §22 "The numbers"] | "Backup verified" turns red after 100 days [R `15-...`] | yes (key typed) |
| **Update (offline bundle)** | IT copies the `.tar` into `deploy/updates/incoming`; verify; apply now or in the quiet hour; automatic backup and rollback [R `services/console/i18n_ops.py:75-78`; `05-...:5-27`] | a `--no-backup` path exists [rev 16 §2.4]; after some releases a role script must be run by hand [R `05-...:251-258`] | verify, apply, schedule, history, rollback points | copying the bundle; a manual rollback is "apply the previous release's bundle" [R `15-...`] |
| **Adding a user** | Users page; enrolment code shown once; a second person confirms where one exists [R `03-accounts.md:5-12`] | – | yes | no |
| **Adding a study** | 11 steps by four roles [R `new-study-walk.en.md`] | – | yes | no |
| **A data source goes quiet** | the night's ingest gate holds a bad night (D-271) [rev 10 §5.1]; an empty or unchanged export: **not verified** | no health line for feed freshness [R `metrics.py`] | Jobs page | to read the ingest report [R `01-...:141-143`] |
| **Disk filling** | warn 70 %, red 85 %; 6-step clean-up list [R `04-disk-full.md`] | – | Disk line | yes (`df`, prune) |
| **Certificate expiry** | warn 45 days, red 30; replace the files, `check-tls`, recreate Caddy [R `12-certificate-renewal.md`] | a new internal CA root after a lost volume must be pushed to every PC again [R same, "Internal CA"] | Certificate line | yes |
| **Model service failing** | canary before the night; note reading held; §19 model hold [R `02-daily-operation.md`; §19] | – | Model self-test line | `selftest`, `doctor` |
| **Power cut** | a week ahead: backup, `systemctl stop trialbox`, shutdown; after: unlock (Tang or passphrase), unseal KEK if not TPM, `doctor` [R `22-planned-power-cut.md`] | an unplanned cut: the box waits at the LUKS prompt off the hospital network [R same] | – | yes |
| **Moving to a new address** | 6 steps; `.env` edit, `check-tls`, network sheet again [R `22-moving-the-box.md`] | – | network sheet | yes |
| **Replacing a failed machine** | install from media, unseal KEK from shares, restore; "Aimedics keeps one loaner box", RTO 5 working days as a target [R `22-replacing-hardware.md`; §22] | the RTO is a target; no loaner exists in Japan [O, not verified] | – | yes |
| **Decommissioning** | `decommission-plan` (changes nothing) and the steps of §20 [R `docs/runbook/20-close-out-and-decommissioning.md`; M 1] | – | – | yes |
| **Remote help** | the hospital's own screen share from a hospital PC, hospital person at the keyboard, no Aimedics access, the ticket is the record [R `21-support-...` "The supervised remote session"] | no `support.session` audit event; the administrator can still open patient pages (until T-102) [R same, rules 3 and 5] | – | yes (the session shows a terminal) |

**Count** [counted here]: of 15 events, the console carries 4 end to end (backup, user, study, the update once the
file is on the box), 4 partly (disk, certificate, model, update copy), and 7 are terminal only (restore, rehearsal,
quiet feed diagnosis, power cut, moving, replacing, decommissioning).

### 2.3 Are the operations procedures ever rehearsed?

Each operations page names a "Drill (T-213b)" test that proves it. **14 are named; 1 exists**
(`test_runbook_19_model_hold`) [M 6]. The other 13 (disk full, GPU fault, morning mail, certificate renewal,
decommission, support session, moving, power cut, replacing hardware, timed restore, lost box, patch window, leaver)
are not in `tests/` [M 6]. The CI backup drill proves a restore is correct on a small set, "not how long it takes" [R
§22 "The numbers"]. [O] The procedures read well and are untested; a site that follows one on a bad day is the first to
run it.

---

## 3. Who the operator is: a Japanese private general hospital's 情報システム部門

### 3.1 Size and skills, from public surveys

| Fact | Number | Source |
| --- | --- | --- |
| Hospitals whose system work is done by **full-time** in-house staff | under 200 beds 27.9 %; 200 to 499 beds 60.0 %; 500 beds and over 83.3 % | JAMI and MEDIS-DC survey, 2015, 596 of 4,000 sampled hospitals answered (15 %) [S 1, table 10] |
| Full-time system staff, where any | median 1 (under 200 beds), 2 (200 to 499), **4 (500 and over; quartiles 2 to 6)** | same, table 11 [S 1] |
| Hospitals using **contracted** (委託) staff | 8.0 % / 28.3 % / **60.6 %** by the same bands | same, table 10 [S 1] |
| Full-time staff in the IT department (5,736 hospitals answering, FY2025) | **"0人が最頻値"**: zero is the most common answer, falling year on year | MHLW G-MIS survey, survey period 2026-03-09 to 04-24 [S 2, p. 4] |
| Two-factor authentication on the medical-information system | about 10 %; 24 % plan it by FY2027; reasons: the system does not support it, budget | same [S 2, p. 9] |
| The tri-ministry **role-division checklist** (役割分担確認表) | known by about 44 %; used by under 10 % | same [S 2, p. 8] |
| Who a hospital consults on cyber matters | over 60 % name the **vendor** (事業者); larger hospitals more often their own staff | MHLW survey FY2023, published 2024-06-10 [S 3, p. 6] |
| Offline backup of the chart | about 50 % of hospitals that back up | same [S 3, p. 17] |
| BCP procedures tested by a drill | about 30 % to 50 % of hospitals with a BCP | same [S 3, p. 19] |
| The questions MHLW asks every hospital each year | CISO, IT staff count, MDS/SDS used, BCP and drill, asset list, patching, two factors, **USB media restricted**, roles in contracts, backups and offline copies | survey form, 2024-12-27 [S 4] |

**For a hospital of about 500 to 600 beds** (the first site's size [P10]) [O, from S 1 to S 4]: a department of
perhaps two to six full-time people, half or more of the day-to-day work done by contracted engineers of the chart
vendor or an integrator, a manager who is also the hospital's CISO, a closed clinical network with internet separation,
USB media under a written rule, changes in announced windows with a change record, and a habit of asking the chart
vendor first. The 2015 numbers are old and the response rate low; the 2026 survey publishes the staff counts as a chart
whose figures were not readable as text here (**not verified** beyond "0 is the mode").

### 3.2 What they will and will not do [O, from S 1 to S 5 and reviews 11, 12, 16]

| They will | They will not, or only with a change request |
| --- | --- |
| Give an address, a DNS name, a certificate, a firewall rule, an NTP server | Install and patch a Linux host they do not otherwise run, by command line |
| Mount a share read-only for a feed, and give a share for backups | Edit YAML or `.env` files, or keep a box's settings in their heads |
| Hold an envelope with a key, and attend a ceremony | Type a 300-character `docker run` line |
| Fill a 開示書, MDS/SDS and a 責任分界表 sent by the vendor [rev 16 §4.1] | Accept a vendor VPN or standing remote access after the Osaka incident (below) |
| Run a quarterly check if the console asks for it, in Japanese | Read 44 pages of English runbook |
| Bring a USB stick through the hospital's media procedure | Let an unknown USB stick into the clinical network without a 持込申請 [O; the survey asks about USB restriction, S 4] |

### 3.3 Remote maintenance and updates under the rules

- The MHLW security guideline 第7.0版 (2026-06) asks that **remote maintenance be logged** and the **responsibility
  split documented**, and two-factor authentication at the next renewal from 令和9年4月1日 [rev 11 row "第7.0版"].
- The MIC/METI provider guideline 第2.0版 puts a vendor in scope as soon as a maintenance or remote-maintenance
  contract exists; the FAQ (draft) counts remote maintenance written into service terms [rev 16 J2, J2a].
- The Osaka 急性期・総合医療センター incident of 2022-10-31 entered through a **VPN appliance placed for remote
  maintenance** of a food-service vendor's system; the chart servers came back after 43 days and full care after 73;
  the report's first cause is "外部接続（リモートメンテナンス）の管理不備" and it names the "閉域網神話" (the myth that a
  closed network is safe) [S 5].
- The first site's chart vendor maintains its systems by its own staff over a closed IP network with remote login [rev
  12 row S8].

[O] Consequence for TrialBox: **no standing remote access** (as D-967 already rules), updates arrive on media through
the hospital's media procedure, and every support session is started by the hospital and leaves an audit record the
hospital can hand to its auditor. Today the first two hold; the record is "the ticket" only [R `21-...` rule 5].

---

## 4. How good on-premises products make this simple

Sources opened 2026-11-18 [S 6 to S 14]. "Take" means a pattern TrialBox can copy in its own code without adding a
runtime dependency.

| # | Product or pattern | What it is | Licence | What TrialBox could take | Cost [O] |
| --- | --- | --- | --- | --- | --- |
| A1 | Replicated Troubleshoot: **preflight checks and support bundles** | vendor-written checks run by the operator before install; a redacted support archive after [S 6] | Apache-2.0 [S 6] | The idea as data: one list of checks, each with "what to do", run by the wizard before install and by `doctor` after; the support bundle exists already (T-209b) | M (SO-3, SO-5) |
| A2 | k3s **air-gap install** | one binary, an image archive dropped in a folder, the install script with `INSTALL_K3S_SKIP_DOWNLOAD=true`; upgrades replace the archive and rerun [S 7] | Apache-2.0 (**not verified** on this page) | Already the shape of the bundle; take "upgrade = drop the archive and rerun the same command" as the operator's whole model | – |
| A3 | Nextcloud All-in-One | one `docker run`, then a **browser interface** for set-up; backups "completely managed from the AIO interface, including backup creation, backup restore, backup integrity check"; daily backup then automatic update [S 8] | AGPL-3.0 [S 8] | Restore and integrity check as console pages; "backup first, then update" (exists) | M (SO-8) |
| A4 | Home Assistant OS | an appliance OS with **A/B system slots via RAUC**, a read-only compressed root, the slot marked good after the supervisor starts [S 9]; updates from the settings page; no documented USB update [S 10] | not stated on the page (**not verified**) | Long term: an appliance OS image with A/B slots for the host; near term: mark a release "good" only after the canary and `doctor` pass (exists for the stack) | L, 1.1 (decision SO-D3) |
| A5 | RAUC | signed A/B update bundles for embedded Linux, X.509 signatures, recovery systems [S 11] | LGPL-2.1 [S 11] | Only if the host becomes an appliance image (SO-D3); not for 1.0 | L |
| A6 | GitLab Omnibus | **all settings in one file** (`/etc/gitlab/gitlab.rb`), applied by `gitlab-ctl reconfigure` [S 12] | MIT (CE) (**not verified** on this page) | One site file that holds every site answer, exportable and re-applied (today: answers + `.env` + mapping + settings) | M (SO-14) |
| A7 | Proxmox VE installer | ISO with a graphical installer asking disk, zone, password and e-mail, network; an **answer file** for an automated install [S 13] | not stated on the page (**not verified**) | The site seed: the vendor writes the answers before shipping; the box runs them unattended (the box form's `--answers` exists, D-898) | S (SO-2) |
| A8 | Cockpit | a web console for a Linux server, started on demand by systemd socket activation, on the server itself [S 14] | LGPL-2.1+ [S 14] | The pattern, not the product: host facts (disks, services, updates) shown in the browser so IT never needs SSH; TrialBox's ops runner already writes host facts each minute | – |
| A9 | Synology DSM web assistant; TrueNAS configuration file download and upload | browser set-up of an appliance; one configuration file to save and load | proprietary; TrueNAS: **not verified** (page did not render) | Configuration export and import (SO-14) | – |
| A10 | Medical-device service modes | a service mode entered on site, logged, with patient data hidden while service staff look | **not verified** (no public manual opened) | A console "support session" switch the hospital turns on: patient pages closed to the administrator, an audit event at start and end (SO-15) | S |
| A11 | Phone-home-free assistance | the hospital starts a one-time screen share from its own approved tool (TrialBox's rule today, D-967) | – | Keep; add the audit record and the patient-page lock (SO-15) | S |

[O] Nothing here needs a new runtime dependency for 1.0. The patterns to take are four: **answers written before
shipping**, **checks with "what to do" run live in the browser**, **backup, restore rehearsal and update as pages**,
**one site file**. An immutable A/B host OS is the long-term form and a 1.1 decision.

---

## 5. A target: from the box arriving to the first screened list

### 5.1 The counted procedure (proposal)

**Targets** [O]: on site, **at most 8 steps**, **no file edited by hand**, **no command typed**, **every question
answered before shipping from review 12's questionnaire plus a one-page network form**, **every page and message in
Japanese**, **under two hours** to the first list on coded criteria (excluding the first load of history, which the
console shows as "night 1 of N" [rev 13 §7.1]).

| Step | Where | Who | What happens | Exists today? |
| --- | --- | --- | --- | --- |
| 0 (before shipping) | vendor | Aimedics, from IT's answers | IT answers the questionnaire [rev 12 §9.1] and a network form (address, name, certificate, shares, feed path, NTP, mail relay). Aimedics prepares the box (`box-install.sh --prepare`), writes a **signed site seed** with those answers, runs a 24-hour burn-in and the IQ pre-run, and records the box's serial and the seal | `--prepare` yes [R `box-install.sh:6`]; seed, burn-in, IQ pre-run no |
| 1 | machine room | IT, support partner | Rack, power, network cable; feed share reachable | – |
| 2 | the box's screen | IT | Power on; the screen shows the address and a one-time code | yes [R `box-install.sh:20-22`] |
| 3 | a staff PC | IT | Open `https://<name>`, type the code | yes [R `firstrun.py:1-20`] |
| 4 | wizard: "この病院" | IT | The seed's answers shown for confirmation; **the preflight runs live**: name and certificate, NTP, backup share writable, audit share writable and not writable by the box's root, feed readable with a count, mail relay, disk, TPM or Tang, GPU and tier record; each red line says what to do, in Japanese | partly (hardware detect [M 9]); the live checks no |
| 5 | wizard: "管理者" | administrator, steward | Two accounts with authenticators (steward and administrator) | yes [R `box_answers.py` `owner_accounts`] |
| 6 | wizard: "鍵" | two named people | Backup key written to the USB stick inserted at the box and printed as a paper record for the envelope; KEK sealed by the site's preset (TPM+PIN or Tang), shares printed when chosen; each an audit event | no (terminal today) |
| 7 | wizard: "データ" | steward | The SS-MIX2 reader in count-only mode: counts per type and per day, quarantined rows, unmapped codes; the site profile's coverage lines [rev 12 §9.3 step 2] | no (waits 10B-1, 10B-6, 10B-19) |
| 8 | wizard: "確認" | IT | The capability page (section 6) and `doctor` as one Japanese page; "restore rehearsal now" into scratch with the key stick; then the console opens | no |

The first study then follows plan 10's target of 5 steps and 3 hand-offs (10D-22) [P10]. The first list on coded
criteria comes within the first hour; note criteria follow the night [rev 13 §7.2].

**Per tier** [O, from rev 13 §7.2]: identical steps 0 to 8. Tier A (no GPU) shows "notes are not read on this box" as
a status at step 8, never an error (10E-17); tiers B to D show model warm-up as "models loading, about N minutes"
(13-15) and the first note-checked list after the first night (B, C) or about 1.2 hours (D).

### 5.2 The browser wizard and what it asks

| Wizard question | Answered from | Asked on site? |
| --- | --- | --- |
| Site name, time zone, language, retention country | questionnaire, site details | no: seed, confirmed |
| Console name, address, certificate | network form | no: seed; the certificate file placed by Aimedics or uploaded at step 4 |
| Backup share, audit-head share, log share | network form | no: seed; checked live |
| Feed path and kind (SS-MIX2 standardised, extended) | questionnaire items 4, 5, 22 [rev 12 §9.1] | no: seed; counted live |
| Chart-number rule | questionnaire item 7 and a sample [rev 12 §9.2] | no: seed |
| Mail relay and authserv-id | network form | no: seed |
| Owner, administrator, steward | the hospital's names | **yes** (people, passwords, authenticators) |
| Key custody preset (TPM+PIN, Tang, shares) and holders | the hospital's security policy [rev 16 §2.8] | **yes** (two people present) |
| Tier | the machine ordered (decision 32) | no: detected and checked against the tier record (10E-1) |

### 5.3 The delivered form for the first site

| | Vendor-prepared machine (recommended) | Install on the hospital's own machine |
| --- | --- | --- |
| Who installs the OS, Docker, the driver | Aimedics, from the offline media, before shipping | hospital IT (P1 to P3) |
| Steps on site | 8 (section 5.1) | about 30 (section 1.3) |
| Matches the GPU's measured serving record | yes, by construction (tier rule, D-138) [R `01-...:13-16`] | only if the card is the measured one |
| IQ evidence | pre-run at the vendor, repeated on site | all on site |
| Hospital procurement | a "device with software" purchase; the hospital may still prefer its usual hardware maker | the hospital's usual maker and maintenance |
| Hardware maintenance | the maker's on-site warranty, arranged by Aimedics or the support partner | the hospital's existing contract |

[O] Recommend the **vendor-prepared machine**, bought from a maker with Japanese on-site warranty, configured by
Aimedics (or the support partner in Japan) from the seed, so the hospital's change board approves one device and one
document set (review 16's pack) rather than a build procedure.

### 5.4 Who does what

| Activity | Hospital IT (情報システム部門) | Support partner in Japan (plan 10 decision 69) | Aimedics |
| --- | --- | --- | --- |
| Questionnaire and network form | answers; with the chart vendor for the feed | collects, explains in Japanese | turns answers into the seed |
| Delivery and step 1 to 8 | network, power, shares, envelope | on site with IT | prepares, seals, ships; on the phone |
| Daily | reads the morning health line in Japanese | first month: checks the Operations page each morning [R `21-...` "First month"] | tier 2 |
| Update | brings the stick through the media procedure; clicks verify and schedule; files the change record | runs it with IT on the first two releases | builds, signs, writes the ja release note and change-impact sheet |
| Backup | owns the share and the envelope | – | – |
| Restore rehearsal | quarterly, from the console, two people | attends the first | reads the recorded times |
| Host OS patches | applies Aimedics' signed OS patch bundle in its window (SO-19), or its mirror | – | builds the OS patch bundle monthly |
| Replacing a failed machine | moves the network, keeps the share | brings the prepared spare; runs "restore this site" | keeps the spare current |

### 5.5 What must stay hard on purpose, and how to make it safe instead of easy

| Hard thing | Why it stays hard | How to make it safe [O] |
| --- | --- | --- |
| Key custody (backup key, KEK, shares) | the box must not be able to read its own backups; a lost box must not open | A guided ceremony page with two named people present, the key written only to a stick inserted at the box and to paper, each step an audit event; never a key on the screen of a remote session |
| Role assignment | the delegation log and the steward's confirmation are what make lists lawful (D-719) | Keep the second person; show who is waiting on whom on the administrator's home |
| The audit chain and its anchor | a root user must not rewrite history [rev 16 §2.5] | The preflight refuses an anchor share the box's root can overwrite; the capability page shows the newest signed head's age |
| Downgrade, `--no-backup`, gates off in PRODUCTION | each removes a safety | Refused in PRODUCTION without a written reason (10G-3), and never offered as a button |
| The data source's legal footing | the IRB and the purpose-of-use line come first [rev 11] | The wizard's step 7 counts only; lists wait for the gates (they exist: `TB_IRB_TEXT_GATE`, `TB_NOT_MATCHED_GATE`) [R `02-daily-operation.md`] |

---

## 6. Completeness tracking: the capability page

**The problem.** The owner wants the complete release and finds it "difficult to track all not done features". Today
the box can say its version and release id (`/about`) [R `services/console/templates/about.html`], its flags
(`/ops/flags`) and its health (eight checks); `doctor` says 37 things in English [M 2]. Nothing says, in one place,
what this site has and what it does not, and why.

**The proposal: one page, `/admin/capabilities`, "この施設で使える機能", in three languages.** One row per capability;
the columns are states, each read from a record that already exists or is already carded:

| Column | Meaning | Fed by |
| --- | --- | --- |
| In this release | the capability is in the signed release | a **capability registry** shipped in the bundle (new: `catalogue/capabilities.yaml`: id, name in three languages, module per review 10, the plan cards that deliver it, the tier it needs, the evidence that proves it) and `release.json` |
| Installed | its images, models and data packs are on the box | the bundle's install record (`deploy/updates/installed.json`) [R `05-...:69`] |
| Switched on | its settings, flags and profile allow it here | settings, `tb_common.flags`, the tier record (10E-1), the site profile (10B-6) |
| Configured | what it needs from the site is filled (a source, a mapping's coverage, a mailbox) | the site profile's coverage lines (10B-6), `doctor` checks |
| Working now | its checks pass now | `doctor --json` and the health checks |
| Validated here | its IQ/OQ step and, for model capabilities, the tier's qualification record exist | `trialbox validate` records (B7-16), the qualification record per tier (10E-16) |
| Not available, because | one reason: "this tier" (a CPU box and note criteria), "a decision" (plan 10 decision n), "not built yet" (card id), "not applicable at this site" (a reason) | the registry and the tier record |

**Rules** [O]: a capability in the release is never hidden; "not built yet" names the card; "complete" for the first
site means every row is either *validated here* or *not available because of a tier or a decision the owner made*,
never *not built yet*. The page exports as a signed PDF and CSV for the owner, the hospital's change board and a
sponsor's supplier audit.

**How plan 10's cards map to it.** Each card in plan 10's tracks that delivers something a user or operator sees
gets a capability id in a new column (internal cards, such as a refactor, get "none"). A check in CI (S, SO-12) fails
when a release-scope card has no capability id, or when a capability names a card that is not in the plan. The same
registry, rendered across the repository rather than one box, is the owner's tracking table: every capability,
which cards it waits for, and whether its proving test exists. [O] This makes the owner's ruling checkable: the first
site receives the complete release, and the page shows exactly which parts are working, validated, or waiting.

Example rows (illustrative, not measured):

| Capability | In release | Installed | On | Configured | Working | Validated here | Not available because |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SS-MIX2 standardised storage reader | yes | yes | yes | coverage 92 % labs | yes | IQ step 7 | – |
| Note criteria (two-model agreement) | yes | yes | no | – | – | – | tier A: no GPU on this box |
| Study package import (multicentre) | yes | yes | no | – | – | – | decision 47 not ruled |
| EDC module | no | – | – | – | – | – | release criterion 26 (C-11) |

---

## 7. Gap table: what the product does today / what is needed / evidence

| # | Area | Today | Needed | Evidence |
| --- | --- | --- | --- | --- |
| G1 | Install form for Japan | IT form: 12 prerequisites, about 30 actions, 44 English questions; box form built for an owner, never on real hardware | Vendor-prepared box filled from a seed; 8 site steps, no file, no command | 1.1 to 1.3 [R; M 4, M 7] |
| G2 | Japanese defaults | report language zh-TW, Taiwan mapping and retention, SS-MIX2 not offered | A Japan site is Japanese by default; SS-MIX2 offered | [R `settings_wizard.py:55, 63, 68, 432-433`] |
| G3 | Preflight | host checks after install (`check_host`, `doctor`) in English | Live checks in the wizard with "what to do", in Japanese | [M 2]; section 4 A1 |
| G4 | Settings outside the wizard | backup target, anchors, logs, patient count in `.env` by hand | All in the wizard and the seed | [R `install.sh:663-665`] |
| G5 | Health page | 8 checks; no feed freshness | Feed freshness, jobs waiting, audit lag (with AQ-25) | [R `metrics.py:158-284`] |
| G6 | `doctor` | terminal, English, setting names | Console page, three languages, plain words and the next action | [M 2] |
| G7 | Update | copy into a folder as root; manual rollback = apply the old bundle | Detected on an inserted stick; verify, schedule, "return to the previous release" | [R `i18n_ops.py:75-78`; `15-...`] |
| G8 | Restore and rehearsal | terminal; never timed | Console rehearsal with the key stick, times recorded per box | [R §22] |
| G9 | Drills | 1 of 14 named drills exists | Each procedure has a drill, or its name is removed | [M 6] |
| G10 | Japanese operator text | 5 of 2,611 runbook lines | One Japanese operator's page; ja §1, §5, §22 summaries | [M 5] |
| G11 | Keys | `backup-keygen`, `tools.keys` in the terminal | Guided two-person ceremony pages | [R `05-...:74-76`] |
| G12 | Site configuration | answers, mapping, `.env`, settings, certificate in five places | One exportable, re-appliable site file | 1.5 [R] |
| G13 | Remote help record | the ticket; no audit event; administrator may still see patients | A support-session switch with audit and a patient-page lock | [R `21-...` rules 3, 5] |
| G14 | Completeness | `/about` version; flags; health | Capability page and registry | section 6 [R] |
| G15 | Spare and replacement | "one loaner box" as a default; RTO target 5 working days, unmeasured | A prepared spare in Japan and a "restore this site" path | [R `22-replacing-hardware.md`] |
| G16 | IT one-page | says IT is asked three things | Generated from the preflight's list, true for the form delivered | [R `it-one-page.ja.md:3-4`; 1.2] |

---

## 8. Cards, written for plan 10

Ids `SO-n`. S a day or less, M a few days, L a week or more (estimates). Lanes as plan 10 names them (a guess).

| Id | What | Size | Lane | Waits for | Proved by |
| --- | --- | --- | --- | --- | --- |
| SO-1 | Japan defaults in both wizards: time zone `Asia/Tokyo` makes `ja` the report language and `jp` retention unless changed; `ssmix2` offered as a source; the Taiwan mapping and NHI questions only for a Taiwan site | S | D, J | – | A wizard test: a Tokyo answer set with no language gives `ja`, `jp`, and offers SS-MIX2 |
| SO-2 | The **site seed**: one signed file of the network form and questionnaire answers, made by Aimedics before shipping; the box form reads it and shows it for confirmation; each wizard question names its questionnaire item | M | D, J | 10B-19 | A prepared box with a seed asks only people and keys |
| SO-3 | **Live preflight** in the first-run wizard and in `doctor`: DNS name and certificate, NTP, backup share writable, anchor share writable and not by the box's root, feed readable with a count, mail relay, disk, TPM or Tang, GPU against the tier record; each line with the next action in three languages | M | D, C2 | 10E-1 | A fixture per failing check shows a red line with its action, in ja |
| SO-4 | Backup, anchor and log folders chosen in the wizard; PRODUCTION install refuses to finish with on-box-only backups or an unmountable anchor | S | D | SO-3 | The install test exits before "finished" in both cases |
| SO-5 | `doctor` on the console (administrator), grouped, in three languages, with the next action; the support bundle as a button | M | C2, J | SO-3 | Page test; every check has en, ja, zh-TW text |
| SO-6 | Health: last good ingest per source, rows in and held, jobs waiting and the oldest, audit drain lag (merge with AQ-25) | S | D | – | Stop the feed in a fixture: the line turns red the next morning |
| SO-7 | Update from a stick inserted at the box (a read-only host mount unit), verify, schedule; "return to the previous release" button; a Japanese release note and change-impact sheet in each bundle | M | D, C2, J | – | Drill: insert, verify, apply in the quiet hour, roll back; the change sheet lists the change classes |
| SO-8 | Restore rehearsal from the console: key on a stick inserted at the box, two people named, into scratch databases; times recorded per box; RTO and RPO on the capability page | M | D, C2 | 10E-15 | A timed rehearsal record on the stub box; a failed key shows red |
| SO-9 | Build the 13 missing T-213b drills, or remove their names from the runbook pages | L | D | – | `tests/` holds each name the runbook cites; doclint fails a name with no test |
| SO-10 | A Japanese operator's page (daily, weekly, quarterly, yearly, what to do on red) and ja summaries of §1, §5, §22; read by the clinician and IT readers | M | J | 10G-14 | Readers' sign-off; doclint counts ja coverage |
| SO-11 | **Capability registry and page** (section 6), fed by `release.json`, the install record, flags, the tier record, the site profile, `doctor --json` and validation records; export as signed PDF and CSV | M | C2, D | 10E-1, 10B-6, B7-16 | A tier A fixture shows note criteria as "not available: tier"; the export verifies by hash |
| SO-12 | A capability id column in plan 10's tables and a CI check: every release-scope card maps to a capability or "none" | S | Int, J | SO-11 | The check fails on a planted card without an id |
| SO-13 | Key ceremony pages: backup key to stick and paper, KEK preset, shares printed, two people, audited | M | D, C2 (C2 decides roles) | SO-3 | A ceremony test writes no key to the database or logs; the audit lists both names |
| SO-14 | One site file: export and import of answers, settings, site profile, mapping, network values, encrypted to the backup key; "restore this site" on a prepared spare | M | D | 10B-6 | A spare restored from the file and a backup equals the original by `doctor` and counts |
| SO-15 | Support-session switch: the hospital person turns it on, patient pages closed to every role during it, `support.session` start and end events, auto-end after 2 hours | S | C2 (decides) | T-102 | Page test: a patient page refused during a session; two audit events |
| SO-16 | SS-MIX2 as the wizard's data step: count-only reader report and coverage lines shown at step 7 | S | B2, C2 | 10B-1, 10B-2, 10B-19 | The synthetic Japanese hospital's storage gives counts per type on the page |
| SO-17 | **A stranger follows the box form** on a clean machine from power-on to the coded first list: steps, questions, typed commands, minutes, recorded like H-22 | M | H, D | SO-1 to SO-4 | A follow record meeting section 5.1's counts; about US$0.34 on a no-GPU VM [R `runbook-install-2026-11-17.md:196-200`] |
| SO-18 | The IT one-page generated from the preflight's check list, per delivered form | S | J | SO-3 | doclint compares the page with the list |
| SO-19 | Host OS patches as a signed monthly OS bundle (`apply_update.sh ospatch` exists) with the driver hold, applied from the console in the patch window | M | D | SO-7 | A patch bundle applied and rolled back on the rehearsal host |
| SO-20 | An operator's calendar on the administrator's home: restore rehearsal due, certificate end, yearly rotation, patch window, in ja | S | C2 | SO-8 | Frozen-clock test |
| SO-21 | Silent choices guarded: chart-number rule must be chosen in PRODUCTION; `health-page` alert route needs a named person; internal CA needs IT's confirmation that the root is pushed | S | D | – | Wizard tests for each |
| SO-22 | Vendor preparation line: `--prepare`, 24-hour burn-in, IQ pre-run, seal and shipment record; the first real-hardware run of the box form on the delivered workstation | L | D, G | SO-2, decision 32 | The record of one prepared box; IQ repeated on site gives the same result |

**Count:** 22 cards: 9 S (SO-1, 4, 6, 12, 15, 16, 18, 20, 21), 11 M (SO-2, 3, 5, 7, 8, 10, 11, 13, 14, 17, 19), 2 L
(SO-9, 22).

**What waits for what:** SO-1 → SO-2 → SO-3 → SO-4, SO-5, SO-13, SO-18 → SO-17 (the follow). 10E-1 → SO-3, SO-11.
10B-6 → SO-11, SO-14. 10B-1, 10B-2, 10B-19 → SO-16. SO-7 → SO-19. SO-8 → SO-20. SO-11 → SO-12. T-102 → SO-15.
Decision 32 and SO-2 → SO-22. **First fifteen beside plan 10:** SO-1, SO-6, SO-21 (S, need nothing) now; SO-3 after
10E-1; SO-11 skeleton now (its registry needs no other card) [O].

**Merges with existing cards:** SO-6 with AQ-25 (review 10); SO-8's measurement with 10E-15; SO-10 with 10G-14
(runbooks in ja); SO-17 extends H-22/H-24's follower to the box form.

---

## 9. Decisions only the owner can make

| # | Decision | Recommendation | Cost | Waits on it |
| --- | --- | --- | --- | --- |
| SO-D1 | Delivered form for the first site: a vendor-prepared machine, or TrialBox installed on the hospital's own machine | **Vendor-prepared**, bought from a maker with Japanese on-site warranty, prepared by Aimedics or the support partner from the seed | the machine (decision 32); preparation time | SO-2, SO-22 |
| SO-D2 | Who is the box's administrator day to day | Hospital IT (情報システム部門) as administrator; the research office's person as data steward; the support partner as on-site first line in the first month | partner contract (decision 69) | SO-10, 5.4 |
| SO-D3 | Host OS for 1.0 | Ubuntu 24.04 prepared by Aimedics, patched by Aimedics' signed monthly OS bundle applied by IT in its window (SO-19); an immutable A/B appliance OS considered for 1.1 | none for 1.0 | SO-19 |
| SO-D4 | Remote help | Keep D-967: no standing access, the hospital starts its own screen share; add the console's support-session switch and audit record | none | SO-15 |
| SO-D5 | Certificate for the first site | The hospital's certificate (its CA), required in the seed; Caddy's own CA only for a pilot | none | SO-2, SO-3 |
| SO-D6 | "Complete" is defined by the capability page | Yes: every release capability is validated here, or not available because of the tier or your ruling, never "not built yet" | none | SO-11, SO-12 |
| SO-D7 | Restore rehearsal | Quarterly into scratch from the console with two people; a full restore onto the spare once a year | staff time | SO-8 |
| SO-D8 | A prepared spare box in Japan (TB-DR-09 Q5) | Yes, held by the support partner, so a failed machine is back in days, not the supplier's lead time | a second workstation | 5.4, SO-14 |

---

## 10. What the first site must supply

Through the hospital's IT department, as the owner ruled; synthetic or blank content only.

| # | Item | From | For |
| --- | --- | --- | --- |
| 1 | The questionnaire of review 12 §9.1 answered, plus a one-page network form: fixed address, DNS name, certificate request route, NTP server, mail relay and authserv-id, the backup share, the audit-head share (not writable by the box), the log share | 情報システム部門 | SO-2, SO-3 |
| 2 | The feed: a read-only copy or mount of the SS-MIX2 storage and who maintains it (the chart vendor's engineer) | IT with the chart vendor | step 7, SO-16 |
| 3 | The hospital's media procedure (USB 持込申請) and whether an update may arrive on a stick or must come through a share | IT | SO-7 |
| 4 | Change-control habits: the change form, announced windows, who approves a vendor update | IT | SO-7, SO-19 |
| 5 | Remote-maintenance rules: allowed tool, logging, who may start a session | IT | SO-15, decision SO-D4 |
| 6 | Key custody: who holds the envelope; TPM+PIN or Tang (is there a Tang server?); two named people for ceremonies | IT, the security officer | SO-13 |
| 7 | Rack, power (100 V outlet rating), UPS, the yearly electrical inspection date (法定点検) | IT, facilities | step 1; §22 power cut |
| 8 | Who operates: the department's full-time and contracted staff, and whether the chart vendor's engineers are on site | IT | decision SO-D2 |
| 9 | The hospital's preferred hardware maker and its warranty terms | IT, purchasing | decisions SO-D1, 32 |
| 10 | The BCP's target RTO for a research system | IT | SO-8, 10E-15 |

---

## 11. Measurement log

All from `trialbox/` of a sparse checkout at master `273b1e149`, with `/home/user/Auto-GPT/trialbox/.venv/bin/python`
(written `PY`) and `PYTHONPATH=libs:services:.`; outputs under `/var/tmp/trialbox-0/b20/m/`.

| # | Command | Result |
| --- | --- | --- |
| M 1 | `PY -m tools.trialbox --help`; `PY -m tools.trialbox doctor --help` | 29 sub-commands; `doctor` 16 options |
| M 2 | `TB_ENV=PRODUCTION PY -m tools.trialbox doctor --settings deploy/settings.example.yaml` | 37 checks: 21 PASS, 8 WARN, 8 FAIL; exit 1; English only |
| M 3 | `grep -o '"TB_[A-Z0-9_]*"' libs/tb_common/config.py \| sort -u \| wc -l`; the same over `docs/runbook docs/RUNBOOK.md` | 519 declared settings; 191 named in the runbooks |
| M 4 | `grep -c '^    ("' tools/settings_wizard.py`; `PY -m tools.settings_wizard --help` | 44 questions; help in English |
| M 5 | `wc -w` over `docs/runbook/*.md docs/RUNBOOK.md`, and over §1 to §7, §12, §15, §20 to §25; a Python count of lines with kana or kanji; `wc -l deploy/windows/box-install.ps1` | 43,753 words in 35 files; 21,993 words (about 44 pages); 5 of 2,611 non-empty lines with Japanese; 1,425 lines |
| M 6 | `grep -rho "test_runbook_[a-z0-9_]*" docs`; `grep -rl "def test_runbook_" tests` | 14 operations drills named (T-213b); 1 defined (`test_runbook_19_model_hold`) |
| M 7 | `grep -o 'name="[a-z_]*"' services/console/templates/firstrun.html`; the catalogues of `services/console/i18n_firstrun.py` | 19 form names: 16 answers besides the code, the form token and the page-language switch; 80 messages each in en, ja, zh-TW |
| M 8 | `bash deploy/install.sh --help \| wc -l` | 39 lines, English |
| M 9 | `python3 -m tools.box detect --deploy deploy` (the host's own Python, standard library) | JSON of arch, CPUs, memory, disk, GPU, TPM, disks, host name and zone; on this machine no GPU and no TPM |

Not run: any installer, `check_host.sh`, a box, a backup or a restore (they need root, Docker or a stack).

---

## 12. Sources

| # | Source | Opened | Licence or terms |
| --- | --- | --- | --- |
| S 1 | 日本医療情報学会, 医療情報システム開発センター: 医療機関における情報システムの運用・管理に携わる人材に関する実態調査報告書, 2015-08, https://www.jami.jp/wp-content/uploads/2023/11/reporthumres_2015.pdf (tables 10, 11) | 2026-11-18 | publisher's report; quoted for figures only |
| S 2 | 厚生労働省 医政局: 「病院における医療情報システムのサイバーセキュリティ対策に係る調査」の結果について (FY2025 survey, 5,736 of 8,102 hospitals, marked 未定稿), https://www.mhlw.go.jp/content/10808000/001703608.pdf (pp. 3, 4, 8, 9, 10) | 2026-11-18 | government publication (MHLW site terms) |
| S 3 | 厚生労働省: 同調査の結果, 第22回 医療等情報利活用WG 資料3, 2024-06-10, https://www.mhlw.go.jp/content/10808000/001262033.pdf (pp. 6, 17, 19) | 2026-11-18 | as S 2 |
| S 4 | 厚生労働省 事務連絡 to 日本病院会, 令和6年度 調査について（依頼）, 2024-12-27, with the question list and answer guide, https://hospital.or.jp/site/news/file/1735199543.pdf | 2026-11-18 | as S 2 |
| S 5 | 大阪急性期・総合医療センター 情報セキュリティインシデント調査報告書 概要, 調査委員会, 2023-03-28, https://www.gh.opho.jp/pdf/reportgaiyo_v01.pdf | 2026-11-18 | the hospital's public report |
| S 6 | replicatedhq/troubleshoot, https://github.com/replicatedhq/troubleshoot | 2026-11-18 | Apache-2.0 |
| S 7 | K3s air-gap install, https://docs.k3s.io/installation/airgap | 2026-11-18 | documentation; product licence not on the page |
| S 8 | nextcloud/all-in-one README, https://github.com/nextcloud/all-in-one (first 100,000 characters read) | 2026-11-18 | AGPL-3.0 |
| S 9 | Home Assistant OS developer docs, https://contributors.home-assistant.io/os/operating-system/ | 2026-11-18 | not stated on the page |
| S 10 | Home Assistant, common tasks for the OS, https://www.home-assistant.io/common-tasks/os/ | 2026-11-18 | not stated |
| S 11 | RAUC, https://rauc.io/ | 2026-11-18 | LGPL-2.1 |
| S 12 | GitLab Omnibus configuration, https://docs.gitlab.com/omnibus/settings/configuration/ | 2026-11-18 | documentation; CE licence not on the page |
| S 13 | Proxmox VE installation, https://pve.proxmox.com/wiki/Installation | 2026-11-18 | not stated on the page |
| S 14 | Cockpit project, https://cockpit-project.org/ | 2026-11-18 | LGPL-2.1+ |

Tried and not readable: the 日本医療法人協会 notice `https://ajhc.or.jp/siryo/20241227cyber.pdf` (a two-page cover
letter), TrueNAS configuration pages (did not render), Flatcar update strategies (did not render), bootc (404 on the
docs site; the repository says Apache-2.0 or MIT, update source not stated).

---

## 13. What this document did not verify

- **Real hardware.** No installer was run here. Whether the box form (prepare, first run, apply) works on a real
  machine with a TPM, systemd and a GPU is unknown; the only real-hardware record stops at key sealing (2026-11-15).
- **The step counts of section 1.3 and the targets of section 5.1** are counted by reading the runbooks, not timed;
  SO-17 is the measurement.
- **A quiet data feed**: what the adapter does with an unchanged or empty export folder was not read in full.
- **The 2026 survey's staff-count chart**: only "0 is the mode" is in the text layer; the percentages by bed size are in
  an image. The 2015 survey is old and had a 15 % response rate. Nothing about the first site's own IT department
  is known here; section 10 asks.
- **Rule texts**: the 第7.0版 guideline, the provider guideline and its FAQ are cited from reviews 11 and 16, not
  re-opened here. Whether a support-session audit record satisfies the guideline's remote-maintenance logging is an
  opinion.
- **Licences** marked "not stated" or "not verified" in section 4 (k3s, Home Assistant OS, GitLab CE, Proxmox,
  TrueNAS, Synology, medical-device service modes) were not checked against licence files.
- **Costs**: the prepared spare, the maker's warranty and the partner's on-site day are not priced.
- **The EDC** was not read (D-1060); nothing here concerns its set-up.
