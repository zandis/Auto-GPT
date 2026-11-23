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

Under the owner's ruling 7092087958 a PoC box stops for four things only. This refusal protects a key and stands on
every box, a PoC box too: RUNBOOK §16 and §23 say so. The lane H lead asks the integrator to confirm it.

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
12. tests/unit/test\_host\_baseline.py::test\_no\_tpm\_fails\_unless\_the\_passphrase\_back\_end\_is\_chosen\[extra1-file-FAIL],
    now `[extra1-file-WARN]` (the back end alone chooses the WARN; the passphrase is not read there)
13. `tests/unit/test_rehearsal_workflow.py::test_validation_settings_reach_the_installer`
14. `tests/unit/test_nightly_restic.py::test_a_passphrase_kek_and_no_kek_are_not_covered` (its set-up)
15. `tests/unit/test_restic_password.py::test_a_passphrase_kek_has_no_shares_and_gets_no_copy` (its set-up)

## Files outside the card

Named by the ruling but perhaps another lane's: `tools/keys.py` (rotation; bodies only, new options and the
refusal), `tools/network_sheet.py`. Not named by the ruling: `deploy/check_host.sh` (it read `TB_KEK_PASSPHRASE`),
`docs/runbook/23-key-inventory-and-the-lost-box-list.md` (the rotation section), `docs/security/10-key-ceremony-and-escrow.md`
(it showed the environment form for rotation), and the tests of the list above outside lane H's own files.

## Findings

In `kek-passphrase-h96-2026-11-23/findings.json` (H96-01 to H96-10): the fault itself (High), the runbook tool's
`-e` on docker exec's command line, the boxes installed before H-96, rc1's refusal of rotate-kek on a PRODUCTION box,
the passphrase's place in a container's environment, the unit invariant's cut, an old test's name, the one-time
values in the install log (High), the first-run code in the journal and /etc/issue.d, and the rehearsal artifacts.

## Questions

1. The rotation page is a new section of §23, not a page of its own number (a RUNBOOK number needs the integrator's
   row). Does the integrator want its own number?
2. rc1 refuses rotate-kek on a PRODUCTION box (H96-04): may a PRODUCTION box whose passphrase was exposed rotate it
   under rc1, or is it made again?
3. `test_installers_reject_passphrase_file_input` (H96-07): rename or retire it under this ruling?
4. The first-run code under `trialbox-firstrun.service` is in the journal and in a world-readable `/etc/issue.d/`
   file (H96-09): change the unit to show it on the console only, in this card or a card of its own?
