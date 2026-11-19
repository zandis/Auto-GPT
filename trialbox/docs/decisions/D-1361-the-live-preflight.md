# D-1361 The live preflight: one check list, in doctor, the terminal wizard and the first-run page (10K-3)

- **Task:** lane K, plan 10 row 10K-3 (review 18 SO-3: "live preflight in the first-run wizard and in `doctor` ...
  each line with the next action in three languages"). · **Date:** 2026-11-19
- **Decision:**
  - **One list, as data:** `libs/tb_common/preflight.py` (`ITEMS`): nine checks, each with a stable id, a group
    (network, storage, hospital data, hardware) and its label and next action in en, ja and zh-TW. The ids are the
    names of the checks that answer them: `name_cert`, `clock` (doctor's own `check_clock`), `backup_share`,
    `audit_share`, `feed`, `mail_relay`, `disk`, `tpm_tang`, `gpu_tier`. The same file holds the time-out's action,
    the action for an id it does not know and the summary line. Standard library only, so the console and the
    host's `python3` read it. `tools/text_keys.py` checks every one of these texts in the three languages
    (`preflight_problems`, run by `make lint`): they are outside the console's catalogue because the host prints them
    too. 10K-5 and 10K-18 read this list; a text is never written anywhere else.
  - **The checks:** `tools/trialbox/preflight.py`, one function per id. They reuse what exists: the clock is
    `doctor.check_clock`; the certificate is the console's `console.identity.check_tls`; the backup targets are
    parsed and classified by `backup_schedule`, and an audit folder's place by the same `target_kind` (the mount
    table, not the device number); the audit folders by `anchors.plan`; the tier record by `tb_common.tier_value`'s
    path and `TB_PROFILE` rule; a card's name by `deploy/gpu_profile.sh`'s rule (the card's name contains one of the
    record's `card_names`: "RTX 5090 D" is a 5090 there too); the TPM by `tools.box.plan.tpm_usable`; free space by
    `deploy/check_host.sh`'s rule (below 10 % FAIL, below 20 % WARN) on its path, Docker's data root, and the deploy
    folder.
  - **Read-only, no internet, bounded:** nothing is written by a check. Writability is asked of the file system
    (`os.access`) and readability judged from modes (`lstat`); the name is resolved by the hospital's resolver; the
    mail relay's greeting is read (over TLS on port 465) and `QUIT` sent; a Tang server's port is opened and closed.
    Each check runs in a thread of its own, waited for 20 s, and the whole run has 70 s: a check that does not finish
    (a hard-mounted share that hangs, a resolver that does not answer) is a red line whose detail starts with
    `timed out` and whose action is the time-out's, never green. The installer wraps the process in
    `timeout -k 5 90` (`TB_BOX_PREFLIGHT_S`) and removes an earlier `preflight.json` first, so a run that fails or is
    stopped leaves no stale lines and never holds the code back. The feed's walk stops at 200,000 files or after
    15 s and says so (amber when stopped by time). Every probe is injectable (`Probes`).
  - **What each one says:**
    - `name_cert`: red when there is no name (PRODUCTION), it does not resolve, it resolves only to loopback or
      link-local addresses (`/etc/hosts`, nss-myhostname: no record in the hospital's DNS), it resolves to an address
      that is not this box's (`ip -j addr`; loopback and link-local dropped on both sides), or the certificate fails
      `check_tls` (not valid now, another name, a key that is not its own). Amber for a hospital certificate that signed itself, and when this box's addresses cannot be
      read. A `.local` name not answered yet is amber before the owner's answers are applied (the box takes the name
      then, OPS-005) and red once `deploy/site/box/applied` is there.
    - `clock`: as `doctor`.
    - `backup_share`: red when no target is set, one is not mounted or not writable, or none is off the box.
    - `audit_share`: red when no share is set (PRODUCTION), a folder is not mounted, is on the box's own disks, the
      box cannot add the nightly signed head, or the box's root may write a signed head. The modes may also allow
      what a write-once share refuses (the box's root owns the heads and may chmod them; the folder is writable and
      not sticky, or root's, so a head could be removed and replaced): that is not visible from here, so it is amber
      with "confirm the share is write-once", never green. Green needs heads that are not root's, not writable, in a
      sticky folder that is not root's; an owner that is the box's root or the user root-squash maps it to (nobody,
      65534) is amber too, since that owner may chmod or remove. The advice is a write-once (WORM) share: root-squash
      alone cannot make the line green.
    - `feed`: counted, never read. Readability is judged for the services' user (uid and gid 10001, the images'
      `tb`) from mode and ownership, not as root; a link is not followed and counts as not readable, and so does a
      folder the walk cannot enter. Red when the folder is missing, empty, or holds anything not readable.
    - `mail_relay`: red when it does not answer or does not greet with 220; amber when none is set.
    - `disk`: the worse of Docker's data root and the deploy folder.
    - `tpm_tang` says what the box really uses. The KEK (`deploy/hardening/seal_keys.sh`: `KEK_BACKEND`, tpm when
      nothing says) is tpm, shamir or passphrase: tpm on a usable TPM 2.0 is green, tpm without one red, shamir or
      passphrase amber (people open the keys at each start), any other word red (the seal step refuses it). The disk
      unlock (`deploy/hardening/disk-unlock.sh`) with `TANG_URLS` needs the TPM and one Tang server answering, both:
      red otherwise; without `TANG_URLS` the line says the disk is not bound to Tang. Tang never protects the KEK.
    - `gpu_tier`: every card is compared; red when none matches the record (name, memory within 3 %), no card
      answers, the record cannot be read, or the host has less than 95 % of the record's minimum memory; amber when
      a second card does not match or the host's memory cannot be read (said on the line).
  - **The tier record's stated values are compared whatever their basis.** D-1322's "measured only" rule is for a
    reader that tunes a running value; this check asks whether the machine is the one the record is about.
  - **In `doctor`:** `python -m tools.trialbox doctor --preflight [--lang ja] [--json] [--out FILE]` runs the list
    alone; a line that is not green has its next action under it, a FAIL is red on a terminal; `--json` adds the
    group and the texts in every language; `--out` writes the first-run page's file. Exit 1 on a FAIL. `--lang` and
    `--out` without `--preflight` are refused. Plain `doctor` is unchanged. RUNBOOK §1 step 8 names the command.
  - **In the terminal wizard:** `tools/settings_wizard.py --preflight [--lang]` runs the list on the files it has
    just written and prints it in the report language; exit 1 on a red line. Off unless asked.
  - **On the console's first-run page:** the page checks nothing itself. `deploy/box-install.sh` runs
    `doctor --preflight --out` with the host's `python3` (`TB_BOX_PREFLIGHT` names another python; the tests use it)
    before it shows the code and writes `preflight.json` (owner-only, given to the console's user) into the
    first-run folder; the answers page shows each line (red, amber, green) with the action in the page's language and
    when it ran. An id the page does not know, or a status it does not know, is red ("call the box's supplier").
    Without the file the page says the checks have not run. The lines are shown only after the one-time code. A host
    without `python3-yaml` writes no file and the installer says so. **The page's lines are a snapshot taken before
    the owner's answers** (the backup and anchor folders, the feed are often not chosen yet); nothing re-runs them
    after the apply until the console's doctor page (10K-5); `doctor --preflight` does it by hand.
- **Limits:** no chain check to the hospital's CA exists: a hospital certificate from an unknown CA passes
  `check_tls` and is shown with its notes (only one that signed itself is amber); a follow-up card.
- **Not in this card:** the backup and anchor folder choice in the wizard and PRODUCTION's refusal to finish without
  them (10K-4); `doctor` on the console (10K-5); the IT one-page generated from the list (10K-18).
- **Held by:** `tests/unit/test_preflight.py` (a ready box all green; one fixture per failure reason, 38 of them, each
  a red line with its ja action; the amber cases; a hanging check and the run's budget; the feed's time bound; port
  465; the command line run once; `--lang`/`--out` refused alone; the terminal wizard; `text_keys` sees a missing
  text; the checks write nothing), `tests/console/test_firstrun_preflight.py` (a fixture per check: a red line with
  its ja action on the page; every language; amber; no file; not before the code; a hostile or broken file; a
  time-out), `tests/console/test_box_install_rehearsal.py` (the installer writes the file through `TB_BOX_PREFLIGHT`,
  mode 0600, owner 10001; a hanging preflight is stopped, the code is shown, no stale file),
  `tests/unit/test_runbook_install_commands.py` (RUNBOOK §1's command runs).
