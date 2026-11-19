# D-1361 The live preflight: one check list, in doctor, the terminal wizard and the first-run page (10K-3)

- **Task:** lane K, plan 10 row 10K-3 (review 18 SO-3: "live preflight in the first-run wizard and in `doctor` ...
  each line with the next action in three languages"). · **Date:** 2026-11-19
- **Decision:**
  - **One list, as data:** `libs/tb_common/preflight.py` (`ITEMS`): nine checks, each with a stable id, a group
    (network, storage, hospital data, hardware) and its label and next action in en, ja and zh-TW. The ids are the
    names of the checks that answer them: `name_cert`, `clock` (doctor's own `check_clock`), `backup_share`,
    `audit_share`, `feed`, `mail_relay`, `disk`, `tpm_tang`, `gpu_tier`. Standard library only, so the console and
    the host's `python3` read it. A later card (the console's doctor page, the IT one-page) reads this list; a text
    is never written anywhere else.
  - **The checks:** `tools/trialbox/preflight.py`, one function per id, run fail closed (a check that raises is a
    FAIL). They reuse what exists: the clock is `doctor.check_clock`; the certificate is the console's own
    `console.identity.check_tls`; the backup targets are parsed and classified by `backup_schedule`
    (`config`, `classify`: off the box or not); the audit folders by `anchors.plan`; the tier record by
    `tb_common.tier_value`'s path and `TB_PROFILE` rule; the TPM by `tools.box.plan.tpm_usable`; free space by
    `deploy/check_host.sh`'s rule (below 10 % FAIL, below 20 % WARN).
  - **Read-only, no internet:** nothing is written by a check. Writability is asked of the file system
    (`os.access`); the name is resolved by the hospital's resolver; the mail relay's greeting (220) is read and the
    connection closed; a Tang server's port is opened and closed. Every probe is injectable (`Probes`), so the tests
    use no network and no hardware.
  - **What each one fails on:** the name does not resolve or the certificate does not pass `check_tls`; no name in
    PRODUCTION (a `.local` name that does not resolve yet is a WARN: the box takes and answers it at its apply,
    OPS-005) · the clock as `doctor` judges it · no backup target, a target not mounted or not writable, or none
    off the box · no audit share in PRODUCTION, a folder not there, on the box's own disk (same device as `/` or the
    deploy folder), not writable for the nightly signed head, or a signed head the box's root may write (judged only
    when running as root and once a head exists; otherwise a WARN that says so) · the feed folder not there, not
    readable, empty or with unreadable files · the mail relay set and not greeting · free space below 10 % ·
    `KEK_BACKEND=tpm` without a usable TPM 2.0, or Tang servers set and none answering · a tier record whose card
    name, card memory (3 %) or host memory (95 % of the minimum) the machine does not match, or no card answering.
  - **The tier record's stated values are compared whatever their basis.** D-1322's "measured only" rule is for a
    reader that tunes a running value; this check asks whether the machine is the one the record is about (card
    names and memory are declared), so a declared value is the right comparison and no running value changes.
  - **The feed is counted, never read:** the number of readable files under the feed folder (stopping at 200,000);
    no file is opened and no name is printed, stored or shown.
  - **In `doctor`:** `python -m tools.trialbox doctor --preflight [--lang ja] [--json] [--out FILE]` runs the list
    alone; each line that is not green has its next action under it, a FAIL is red on a terminal; `--json` adds the
    group and the texts in every language; `--out` writes the first-run page's file. Exit 1 on a FAIL. Plain
    `doctor` is unchanged (its checks, output and JSON).
  - **In the terminal wizard:** `tools/settings_wizard.py --preflight [--lang]` runs the list on the files it has
    just written and prints it in the report language; exit 1 on a red line. Off unless asked: the wizard's questions
    and answers files are as before.
  - **On the console's first-run page:** the page checks nothing itself (the console cannot see the host's clock,
    disks, TPM or shares). `deploy/box-install.sh` runs `doctor --preflight --out` with the host's `python3` before it
    shows the code and writes `preflight.json` (owner-only, given to the console's user) into the first-run folder;
    the answers page shows each line (red, amber, green) with the action in the page's language and when it ran.
    Without the file the page says the checks have not run. The lines are shown only after the one-time code (they
    name shares and host names). A host without `python3-yaml` writes no file and the installer says so. The set-up
    is never stopped by the preflight.
- **Not in this card:** the backup and anchor folder choice in the wizard and PRODUCTION's refusal to finish without
  them (10K-4); `doctor` on the console (10K-5); the IT one-page generated from the list (10K-18).
- **Held by:** `tests/unit/test_preflight.py` (a fixture per failing check: a red line with its ja action; a ready
  box all green; the command line run once; the terminal wizard), `tests/console/test_firstrun_preflight.py` (a
  fixture per failing check: a red line with its ja action on the page; every language; no file; not before the code).
