# H-96: the KEK passphrase from a root-only file or stdin, never the environment (F-45)

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-23. Finding F-45 (High, keys), HIGH-RISK: an independent review reads it before it rides. Built to
the integrator's ruling 7094934985. F-47 rides in the same card (one line in RUNBOOK §20). Synthetic passphrases
only; no real host, address or key is named here.

## The fault

The install test on a real host gave the KEK passphrase as the installers' help and RUNBOOK §16 showed it:
`sudo --preserve-env=TB_KEK_PASSPHRASE ... deploy/install.sh ...`. sudo logs a variable it keeps with its value, as
an `ENV=` part of its journal line, and root and the `adm` group read the journal. The passphrase was in clear text
in a log.

## What is built

**Two ways in, and only two** (install.sh, box-install.sh where it runs install.sh, seal_keys.sh, and tools.keys for
init, unseal and rotation):

| Option | What it takes |
| --- | --- |
| `--kek-passphrase-file FILE` | one line of a regular file, not a link, owned by the user that runs the script (root on a box), mode 0600; a full path for the installers. Refused otherwise, before anything is loaded or written. Removed once the keys are sealed |
| `--keep-kek-passphrase-file` | keeps that file (the box rehearsal's first install keeps it for the reinstall) |
| `--kek-passphrase-stdin` | one line on stdin; at a terminal it is asked twice with the echo off |
| `--kek-passphrase-fd N` | install.sh's own hand-on: the signed re-run, and box-install.sh to install.sh (below) |

tools.keys takes `--passphrase-file`, `--passphrase-stdin`, `--new-passphrase-file`, `--new-passphrase-stdin` and
`--keep-passphrase-files` (rotate-kek reads the old line first, then the new one, when both come on stdin). The
bootstrap passes the installer's options after `--` as before.

**The environment is refused on every path, sudo or not.** `TB_KEK_PASSPHRASE` or `TB_KEK_NEW_PASSPHRASE` with a
value in the caller's environment stops install.sh, box-install.sh, bootstrap.sh, seal_keys.sh and every tools.keys
command (rotation too) with exit 2, before anything is read or written, and the message names the file form and
says the value given is to be treated as exposed (RUNBOOK §23, "Rotate the KEK passphrase"). The value is never
printed. An empty variable is dropped, not refused.

**Inside the scripts** the value lives in a shell variable (`KP_VALUE`) that is never exported. It goes on only by a
pipe: from install.sh to seal_keys.sh's stdin, from seal_keys.sh to the keys command's stdin (on the host's python3,
or in the trialbox-py image through `docker run -i`'s stdin, as before), and from the box's first-run answers (tmpfs)
to seal_keys.sh. It is never an argument, never in a sudo environment, never written to a file other than the
operator's own root-only one.

**The signed re-run.** install.sh's first run reads a stdin passphrase once, before the bundle loads, and runs the
signed release's installer with `--kek-passphrase-fd 8` and the line on a pipe at fd 8 (bash process substitution;
the terminal stays the re-run's stdin, so its question still works). A file passphrase goes on by the file's name and
is read again by the re-run. box-install.sh hands install.sh the same pipe at fd 8, or the file's name.

**Held together.** install.sh and box-install.sh are copied alone into many test folders and run from the stick's
tree, so a sourced helper would break them: the functions (`kp_refuse_env`, `kp_read_file`, `kp_read_stdin`,
`kp_check_value`, `kp_remove_file`) are one block inlined in install.sh, box-install.sh and seal_keys.sh, and a test
holds the three copies equal (as the bundle fingerprint's three copies are held). The bootstrap, which runs before any
TrialBox file is on the machine, carries its own copy of the refusal.

**The host check** (deploy/check_host.sh) no longer reads `TB_KEK_PASSPHRASE`: `TB_KEK_BACKEND=passphrase` alone
chooses the passphrase back end's WARN for a missing TPM.

**The rehearsal** (tools/rehearse_box): the driver writes its synthetic passphrase into a root-only file in the box
by docker exec's stdin (never `-e`). The install phase first shows the real install.sh refuses the environment form
(exit 2, nothing loaded), then installs under a stand-in sudo that logs its command line and environment as sudo does,
with `--kek-passphrase-file ... --keep-kek-passphrase-file`, and asserts the passphrase is in no sudo log line, no
argument, no deploy/.env and no box container's configuration; the reinstall phase installs again without the keep
option and asserts the file is gone and the same. tools/runbook_install.py's no-tpm lift writes its throwaway
passphrase to a root-only file by stdin and names it with `--kek-passphrase-file`.

**Pages.** RUNBOOK §1 (a machine without a usable TPM), §16 (the unattended box install), §20 step 7 (F-47), §23 (a new
section, "Rotate the KEK passphrase"), SECURITY §10 (rotation without a terminal), the installers' header comments,
deploy/hardening/hardening.example.conf, the network sheet (tools/network_sheet.py and the regenerated sheets: the row
is now "KEK passphrase: a root-only file or stdin"), and the hospital's page in three languages (step 4: type the
passphrase only on the set-up page, never in the terminal). The page shows only the file or stdin form.

**F-47** (RUNBOOK §20 step 7): only a box that is the whole machine has its disks sanitized; on a shared host the box's
volumes and folders are removed, never the disks. RUNBOOK §20 is English only.

## The refusal on a proof-of-concept box

The integrator confirmed it (7095256773): a secret read from or written to a place others can read is the PoC
list's fifth stop, and this card's refusals are that stop. They stay dies on every box and are marked "H-94 (5)"
where they stop; install.sh's six are rows of the H-94 inventory (docs/handover/poc-stops-h94-2026-11-23.md).

## Where the passphrase still lives

- In memory, while the installer or the rotation runs, and in the pipe to the seal step.
- In the operator's root-only file until the keys are sealed (or longer with the keep option).
- A box set up on its first-run page: in the owner's answers in `/run/trialbox-firstrun` (tmpfs) until the apply step
  has sealed the keys (services/console/firstrun.py says the apply step removes that file).
- `/run/trialbox/kek` (tmpfs) holds the KEK derived from it, not the passphrase.
- In a process environment inside the box: the adapter and the orchestrator would take `TB_KEK_PASSPHRASE` from the
  stack's environment (deploy/docker-compose.secrets.yml clears it for every other service), and the nightly audit
  signer is handed it by name (tools/trialbox/audit_heads.py line 44, `PASSED`; left as it is). Nothing gives it a value
  since H-96 (the installers refuse it, deploy/.env refuses it: tools/settings_wizard.py `NEVER_IN_ENV_FILE`). A value
  someone sets there by hand would be in that container's configuration on disk (`docker inspect`, root only); no log
  this card knows of records a container's environment. Not run on a box (H96-05).

## The one-time values in the install log (7097514776)

**Where the log is and how the values reached it.** install.sh writes no log file of its own. Two callers keep its
output: deploy/box-install.sh runs it through `tee deploy/site/box/install.log`, and the box rehearsal keeps it as its
step log (`logs/NN-install.log`, uploaded as the rehearsal job's artifact). In the box's unattended form (an owner's
answers file, TB_BOX=0) and in the IT form, install.sh's accounts step printed console.cli's output on its stdout:
`bootstrap-admin`'s generated first password ("password (shown once)") and `enrol-code admin`'s enrolment code. So both
were in install.log and in the rehearsal's step log. **The administrator's first password takes the same path as the
enrolment code and is treated the same way** (H96-08).

**Now.** install.sh's accounts step gathers both into one text and shows it once: on stdout only when stdout is a
terminal (the IT form typed by hand); else on the controlling terminal (box-install.sh run from a terminal: its
install.log holds the line "shown on this terminal only" and neither value); with no terminal at all (a rehearsal's
`docker exec` without `-t`, a driver), in `/root/trialbox-admin-first-sign-in` (the home root's passwd entry names,
mode 0600, made new with an exclusive create; a link or anything but a regular file at its name is refused with a FAIL
line, never followed), which the output names but never prints, with how to read it once and remove it. No variable of
the caller decides where a value goes: no knob names the terminal and HOME is not read (the lead's review on #1398). A failed `enrol-code` keeps its FAIL line; its own output goes with the password, not to the log. RUNBOOK §1
and §16 say so.

**Proved by:** `tests/unit/test_one_time_values_h96.py` (7 tests) runs the real accounts step of install.sh (cut from
the file) with a stand-in `docker compose` printing synthetic values as console.cli prints them, and with the caller's
`TB_ONCE_TTY` exported at a world-readable file and HOME at another folder (both receive nothing, in every test):
through a tee as box-install.sh runs it from a terminal (a pty as the controlling terminal: the values on the screen,
not in the log), in a new session with no terminal (the 0600 file in the passwd home; an old file replaced; a planted
link refused, not followed), stdout on a pty (both shown once), and `enrol-code` exiting 2 or 1. The rehearsal
(tools/rehearse_box/box.sh, install and reinstall phases) keeps the real installer's output, checks the root-only file
and that none of its values (read with `grep -F -f`, never printed) is in that output, the stand-in sudo's log or
deploy/.env, then removes the file. Not run here (no Docker).

**Mutants (the accounts step):** 12 planted, 11 caught by that file: stdout always, no terminal branch, a knob naming
the terminal, HOME naming the file, no umask, no link refusal, no removal before the write, a failed or a good code
echoed to the output, the text printed instead of shown, the terminal copy also on stdout. One survived: `set -C` removed. It guards only the moment between the removal and the write (a
link planted then), which a single-threaded test cannot reach.

**Other one-time values.**
- The first-run wizard's one-time code (box-install.sh `show_code`) is not in install.log (the tee covers the install
  step only), but under `trialbox-firstrun.service` (`StandardOutput=journal+console`) it is in the system journal,
  and outside WSL2 it is in `/etc/issue.d/` for the screen (lane D's #368), a file any local user reads. It works once
  and is voided after five wrong codes. Not changed here: the box's screen is that service's only display, and the
  WSL2 window path cannot be tried in this session (H96-09, question 4).
- deploy/poc.sh prints the PoC administrator's password on stdout and keeps no log. deploy/gcp/box_vm.py (another
  lane's) redacts its log's password lines; with no terminal there the values now go to the root-only file.
- `console.cli add-user`, `reset-password` and `reset-totp` typed by an operator print to that operator's terminal.

The refusals of this card are the PoC list's fifth stop (7095256773: a secret read from or written to a place others
can read) and are named "H-94 (5)" in their comments.

## Tests

The card's file: `tests/unit/test_kek_passphrase_file_h96.py`, 47 tests.

**The invariant test:**
`tests/unit/test_kek_passphrase_file_h96.py::test_no_passphrase_in_a_sudo_log_an_argument_or_an_environment_through_the_signed_rerun`
(three cases: the file, the file kept, stdin). Under a stand-in sudo that logs its arguments and environment as sudo
does, the real install.sh's first run, the bundle load (H-89's stand-in loader), the run from the signed release and
the real seal step leave the synthetic passphrase in no sudo log line, no argument of sudo, docker or python3, no
environment the stand-ins saw, no output and no deploy/.env; the keys are sealed under exactly that passphrase by the
signed run; the file is removed after sealing, or kept when asked. The signed copy cuts the steps between the re-run
and the site keys (settings, compose, TLS): the rehearsal runs them whole (H96-06).

Also: a file that is a link, not the runner's, not 0600, of two or three lines, or not a regular file is refused by
seal_keys.sh, install.sh, box-install.sh and tools.keys; the environment form is refused by install.sh,
box-install.sh, bootstrap.sh, seal_keys.sh and tools.keys (init, unseal, rotate-kek, status) for both variables; a
relative path is refused by the installers; the file is removed after sealing and kept with the keep option; a failed
seal keeps it; a box with a KEK and no open KEK is opened from the file; the terminal form asks twice with the echo
off; rotation takes the old and the new passphrase from files or from stdin (a wrong old one changes nothing); the
three copies of the functions are equal; no script exports the value or puts it on a command line; the runbook tool
writes its file by stdin.

**Mutants:** 22 planted on the new checks, 22 caught (each by a test of this file): the link, owner, mode and
one-line checks (all three copies); the refusal's body (all three copies) and its call in install.sh, box-install.sh
and seal_keys.sh; the bootstrap's refusal; tools.keys' refusal, its rotation variable, its link, owner and mode checks
and its removal; seal_keys.sh's removal and its keep option; the hand-on at fd 8; the signed run given the passphrase
in its environment; seal_keys.sh giving the keys command the passphrase in an environment and as an argument; a
relative path. One more planted mutant survived and was equivalent (the line count beside the trailing-line test,
which already implies at most one line): that redundant half was removed from the code.

### Changed assertions (ruling 7094934985)

Each asserted or set up the environment form; each now uses the file or stdin form (15 tests):

1. `tests/unit/test_seal_keys_order.py::test_an_unusable_tpm_is_found_first_and_the_fix_is_named`
2. `tests/unit/test_seal_keys_order.py::test_the_passphrase_path_without_a_hardening_conf`
3. `tests/unit/test_seal_keys_order.py::test_the_sealed_files_belong_to_the_services_user`
4. `tests/unit/test_seal_keys_order.py::test_seal_keeps_the_inherited_passphrase_out_of_its_output`
5. `tests/unit/test_install_faults_review_round.py::test_the_image_fallback_takes_the_passphrase_on_stdin_never_in_the_container_environment`
6. `tests/unit/test_install_faults_review_two.py::test_a_passphrase_with_a_line_break_is_refused_before_sealing` (3 cases)
7. `tests/unit/test_install_faults_review_two.py::test_the_network_sheet_says_where_the_passphrase_never_is` (the row's
   name and its words: the operator's root-only file is the one file it may be in)
8. `tests/unit/test_install_faults_runbook.py::test_unattended_runbook_and_help_pass_only_the_exported_name`
9. `tests/unit/test_kek.py::test_passphrase_init_then_wrap_and_unseal`
10. `tests/unit/test_key_ceremony.py::test_a_passphrase_box_gets_a_record_marked_not_a_site_ceremony`
11. tests/console/test\_box\_install\_rehearsal.py::test\_without\_a\_tpm\_the\_passphrase\_comes\_from\_the\_environment\_never\_the\_file,
    renamed `..._comes_from_a_root_only_file_never_the_environment` (the environment form now refused, exit 2)
12. tests/unit/test\_host\_baseline.py::test\_no\_tpm\_fails\_unless\_the\_passphrase\_back\_end\_is\_chosen: in the
    form the integrator ruled (7102655419, L-3): a host with no TPM and the back end only named (nothing sealed
    under it) is a FAIL on PRODUCTION (rows 2 and 4, master's FAIL and WARN) and, on a TEST box, a WARN with
    exactly one line of `deploy/site/poc-stops.jsonl` (a new row); no row is listed on PRODUCTION. The test gained
    the box's environment as a parameter
13. `tests/unit/test_rehearsal_workflow.py::test_validation_settings_reach_the_installer`
14. `tests/unit/test_nightly_restic.py::test_a_passphrase_kek_and_no_kek_are_not_covered` (its set-up)
15. `tests/unit/test_restic_password.py::test_a_passphrase_kek_has_no_shares_and_gets_no_copy` (its set-up)

## The review round (7102655010; the integrator's ruling 7102655419)

**M-1 (Medium): the file was checked by its name and its folder never.** Now, in the shared KEK-INPUT block (the three
copies stay one) and in tools.keys:
- the file's folders, as their real paths (`cd -P`/`pwd -P`; `os.path.realpath`): the file's own folder and every
  folder above it up to `/` must be owned by root (the user that runs this) and writable by no one else; above the
  file's own folder a shared folder with the sticky bit is allowed (`/tmp`: no one else can rename what is root's
  there), the file's own folder never;
- the file is opened once and checked on that open file: in the shell `exec 7<` then `stat -L /dev/fd/7` (type,
  owner, mode, number of names, device and inode) and read with `read <&7`, the rest counted with `wc -c <&7`; the
  shell cannot open without following a link, so the name must still be that very file (`stat` of the name: not a
  link, the same device and inode). No python3 helper was needed: `/dev/fd/7` is the open file, not the name.
  tools.keys opens with `O_NOFOLLOW` and checks with `fstat` (type, owner, mode 0600, `st_nlink == 1`);
- the file is removed with `rm -f` (unlink: a link is taken away, never what it names), never `shred`;
- the value is read once per script: install.sh reads the file in its first run and hands the value to the run from
  the signed release at fd 8 with the file's real path for removal only (`--kek-passphrase-remove`, the installer's
  own), and to the seal step on stdin; install.sh removes the file once the keys are sealed. box-install.sh checks the
  file and passes its real path to install.sh (L-1); seal_keys.sh run alone reads it itself.

**The race, as the review ran it:** `test_kek_passphrase_review_h96.py::test_the_swap_race_never_reads_another_value_in_the_shell`
and `..._in_tools_keys` exchange the file's name (renameat2 RENAME_EXCHANGE, in a loop) with another value while the
real code reads it. Shell, 300 reads: in a folder others can write, 0 accepted (300 refused); in a 0700 folder with a
link swapped in, 0 accepted the other value (34 the operator's, 266 refused). tools.keys, 3000 reads: 0 and 0 of 3000;
0 accepted the other value (1178 the operator's, 1822 refused). The link at removal:
`test_a_link_at_removal_is_taken_away_never_what_it_names` (the file a link names keeps every byte) and
`test_seal_keys_refuses_a_file_in_a_folder_others_can_write_and_touches_nothing`. Root-owned folders of another uid
are not built by the tests (they run as a user, as CI does); a folder others can write stands for it.

**L-1 (Low): fd 8 in the file form.** box-install.sh opens fd 8 only for a passphrase from stdin and keeps no copy of a
file's value (`test_box_install_opens_fd_8_only_for_a_passphrase_from_stdin` [file, stdin]); the invariant now also
asserts no child of the run from the signed release holds fd 8 open.

**L-2 (Low): the environment form outside the named paths** (`libs/tb_common/kek.py` `load_kek`,
`tools/trialbox/audit_heads.py` `PASSED`, `tools/trialbox/backup_schedule.py`) is not this card's: it goes to card
H-97 (the integrator's ruling 7102655419).

**L-3 (Low), ruled:** deploy/check_host.sh: no TPM with the back end only named is a WARN and one line of the PoC list
on a PoC box (through tools/trialbox/stops.py, where the box's recorded environment decides, never a caller's
variable), a FAIL on every other box; keys already sealed under the passphrase stay a WARN, not listed (master's row).
Changed assertion 12 is in that form.

**Also:** a uid with no passwd entry (getent exits 2 under pipefail) no longer stops the install: the one-time values
are then not kept, and a warning says how to get new ones
(`test_one_time_values_h96.py::test_with_no_terminal_and_no_passwd_entry_nothing_is_kept_and_the_install_goes_on`).
**Found by the rehearsal after the merge of master (H-94 part 1):** install.sh's host check step tees its output to
/dev/fd/8; when the install's output is a file (box-install.sh's install.log, the rehearsal's step log) that is the
same file opened again, and `tee` without `-a` emptied it, so every line before the host check was lost (here the line
naming the one-time values' file, so the rehearsal's check failed). Now `tee -a`
(`test_kek_passphrase_review_h96.py::test_the_host_check_step_keeps_what_the_install_wrote_before_it_in_a_log_file`,
which fails without `-a`). The line is H-94's; it is named under the files outside the card.

**Mutants (the review round):** 26 planted (the shared block's changed in all three copies alike), 25 caught: the
folder checks (writable, sticky own folder, the walk up, the owner; shell and tools.keys), one name, the
name-and-descriptor comparison, a read by the name again, shred again, the rest of the file, the opened file's owner,
O_NOFOLLOW, the mode, the files removed after a failure, control characters, fd 8 left open, fd 0-9, the file kept
after sealing, box-install's fd 8 and --answers, check_host's FAIL and its list line, and getent's exit. One
survived and is equivalent: the shell's "is a link" case after the open (the check before the open and the
name-and-descriptor comparison each refuse a link already).

The review's mutation survivors each have a test now: a mode of 0400 or 0700, the files kept after a failed rotation,
a carriage return or a tab on stdin and in a file, `--kek-passphrase-fd` 0 to 2, box-install's passphrase options
without `--answers`, and fd 8 left open (the invariant).

## Files outside the card

Named by the ruling but perhaps another lane's: `tools/keys.py` (rotation; bodies only, new options and the
refusal), `tools/network_sheet.py`. Not named by the ruling: `deploy/check_host.sh` (it read `TB_KEK_PASSPHRASE`),
`docs/runbook/23-key-inventory-and-the-lost-box-list.md` (the rotation section), `docs/security/10-key-ceremony-and-escrow.md`
(it showed the environment form for rotation), and the tests of the list above outside lane H's own files. In the
review round: `docs/handover/poc-stops-h94-2026-11-23.md` (six rows of install.sh's H-96 stops, kept (5): the
inventory's count must match the marks), `tests/unit/test_host_baseline.py` (assertion 12, ruled), and in install.sh
H-94's host check line (`tee -a`, above).

## Findings

In `kek-passphrase-h96-2026-11-23/findings.json` (H96-01 to H96-14): the fault itself (High), the runbook tool's
`-e` on docker exec's command line, the boxes installed before H-96, rc1's refusal of rotate-kek on a PRODUCTION box,
the passphrase's place in a container's environment, the unit invariant's cut, an old test's name, the one-time
values in the install log (High), the first-run code in the journal and /etc/issue.d, the rehearsal artifacts, and the review round's M-1, L-1,
L-2 (card H-97) and L-3.

## Questions

1. Answered (7101844662): the rotation section of RUNBOOK §23 is enough.
2. Answered (7101844662): yes, a PRODUCTION box with an exposed passphrase may run rotate-kek under rc1 (D-1092),
   audited, file or stdin only; the change is card H-97's, not this card's.
3. `test_installers_reject_passphrase_file_input` (H96-07): rename or retire it under this ruling? (waits)
5. L-3: the ruling's words "a host with no TPM may WARN only outside PRODUCTION" read generally would also make a
   PRODUCTION box whose keys are already sealed under the passphrase a FAIL (master's row, kept a WARN here). This card
   read it as assertion 12's case (the back end only named); does the integrator want the general form?
4. Answered (7101844662): the first-run code (H96-09) is card H-97's.
