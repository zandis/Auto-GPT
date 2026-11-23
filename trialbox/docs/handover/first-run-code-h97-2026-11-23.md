# H-97: the first-run code in no journal or file others read; a PRODUCTION box rotates its exposed passphrase

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-23. Card H-97 (High, keys), HIGH-RISK: an independent review reads it before it rides. Built to the
integrator's ruling 7101844662 on findings H96-09 (part A) and H96-04 (part B, decision D-1092), and to 7102655419
on the review of H-96's L-2 (part C). It builds on H-96
(PR #1398, not merged when this was written). Synthetic codes and passphrases only; no real host, address or key is
named here. The refusals of part A are the PoC list's fifth stop (a secret read from or written to a place others can
read) and are marked "H-94 (5)": they stand on every box.

## Part A: the first-run wizard's one-time code

**The fault (H96-09).** `deploy/box-install.sh` `show_code` printed the code on stdout and, outside WSL2, wrote it to
`/etc/issue.d/trialbox-firstrun.issue` for the box's screen. At a prepared box's first boot `trialbox-firstrun.service`
runs the script with `StandardOutput=journal+console`, so the code was in the system journal (root and the `adm`
group read it), and the issue file is readable by every local user. Where the file went was a caller's variable
(`TB_ISSUE_DIR`).

**Now.** `show_code` makes the code and shows it once:

| How the script runs | Where the code goes | What the output (a log, the journal) says |
| --- | --- | --- |
| stdout is a terminal (typed at the box, or over SSH with a terminal) | that terminal, once | the code, on the terminal only |
| stdout piped, a controlling terminal (the Windows installer's window under WSL2: wsl-setup.sh tees the output) | the controlling terminal | "shown on this terminal only" |
| no terminal at all (the service at boot, a background run) | the virtual console `/dev/tty0`, written directly (the box's screen; not a serial console a hypervisor may log), and `/root/trialbox-firstrun-code` | the file's name and `sudo cat` it; never the code |

The file is in the home the passwd entry of the user that runs the script names (root's: `/root`), never `HOME`. It
is made new for each code (removed, then created with `umask 077` and `set -C`: mode 0600); a link or anything but a
regular file at its name is refused, never followed (H-94 (5)). A voided code (five wrong codes) is replaced in the
file; the file is removed when the owner's answers are in. With no terminal, no screen and no file the script stops
and says to run it on a terminal (H-94 (5)). `TB_ISSUE_DIR` is gone: no variable of the caller names where the code
goes. An earlier version's `/etc/issue.d/trialbox-firstrun.issue` is removed when the first run starts. The unit
keeps `StandardOutput=journal+console` for the rest of the output (the address, the progress); its comment says
where the code is.

**How the person at the box gets it** (RUNBOOK §16, "Where the one-time code is"):

- a physical console at the first boot: on the screen, and in `/root/trialbox-firstrun-code`;
- WSL2: in the Windows installer's window;
- a headless box, or one whose screen shows a graphical login: over SSH, `sudo cat /root/trialbox-firstrun-code`;
- hospital IT typing the stick's line (the hospital pages, step 7): on that terminal; the pages now say the code is
  shown there only and kept in no log, so the window stays open until the owner has finished. The pages name no path
  or command (their own test), so the file is on runbook 16 only.

**The harnesses that read the code** now read the root-only file: the cloud box run (`deploy/gcp/box-install-run.sh`,
the wizard step; `box_vm.py` parses the same text) and its local rehearsal (`tests/rehearsal/box-run`: a `getent`
shim names the "VM"'s root home, `TB_ISSUE_DIR` dropped from `boot.sh`). Neither was run in this session.

**The rehearsal** (`tools/rehearse_box`): box.sh runs `deploy/install.sh` (and its bundle, reinstall and drills), never
`box-install.sh --firstrun`, so there is no first-run step to check on the real path there. No step was invented
(H97-02, not run).

## Part B: rotate-kek on a PRODUCTION box (D-1092)

**The fault (H96-04).** rc1 refuses the key ceremonies on a PRODUCTION box (R22-34), `rotate-kek` among them, so a
box sealed under a passphrase that sudo had logged could not rotate it; RUNBOOK §23 sent it to the vendor.

**Now** (`docs/decisions/D-1092-a-production-box-rotates-its-exposed-passphrase.md`). `tools.keys rotate-kek` still
asks rc1 first; on a refusal it goes on only when the box is sealed under a passphrase, the new KEK is a passphrase
(`--backend passphrase`), the new passphrase comes from `--new-passphrase-file` or `--new-passphrase-stdin` (H-96's
forms; the environment is refused by every command already), and no escrow set is made. It needs the audit folder
(`--audit-dir`, else `TB_AUDIT_DIR`), refused before anything is read or written without one; it writes
`keys.rotate_kek_started` before any key file changes and, once `kek.json` names the new KEK, `keys.rotate_kek`: who (the user it runs as and the kernel's login uid, never a variable the
caller sets), when, the box's host name, the environment, the old and the new KEK ids, `D-1092`. Never a value. The
rc1 table's row says so; its message, its sites and every other refusal are unchanged. RUNBOOK §23's rotation
section (still a section, no new number) says a PRODUCTION box rotates itself, with the audit folder, and that every
other rotation stays refused there.

**Every rotation is audited** (the integrator's ruling 7114085298, after the first review). Every `rotate-kek`, on
every box, writes `keys.rotate_kek` (who, when, the box, its environment, the two KEK ids and the new back end; never a
value) and is refused without its audit folder, before anything is read or written (after the check for a key
rotation cut short, which keeps its own words). `rule` is `D-1092` for the PRODUCTION exception, `7114085298`
elsewhere. RUNBOOK §23's and SECURITY §10's rotation commands name the audit folder. Test:
`tests/unit/test_rotate_exposed_passphrase_h97.py::test_every_rotation_on_a_poc_box_is_an_audit_event` (DEV, TEST and
VALIDATION by the box's deploy/.env; the passphrase and the file back end). Mutants: 3 planted (no refusal without a
folder; audited on PRODUCTION only; the environment not recorded), 3 caught. Set-ups changed under that ruling (an
audit folder given; nothing they assert changed): `tests/unit/test_kek.py::test_rotate_kek_rewraps_every_key_and_the_old_shares_stop_working`,
`tests/unit/test_restic_password.py::test_after_rotate_kek_the_copy_waits_for_new_escrow_shares`,
`tests/unit/test_objstore_sealed.py::test_custody_lists_the_object_key_once_made_and_rotate_kek_keeps_objects_readable`,
`tests/unit/test_key_escrow.py::test_the_ceremony_record_lists_the_set_and_the_doctor_warns_on_an_older_or_unrecorded_set`,
`tests/unit/test_sign_keys_kek.py::test_rotate_kek_rewraps_both_signing_keys_and_the_readers_open_them`,
`tests/unit/test_kek_passphrase_file_h96.py::test_rotation_takes_the_old_and_the_new_passphrase_from_files_or_stdin`.

## Part C: no path takes the passphrase from a caller's environment

The review of H-96 (L-2) and the integrator's 7102655419 name this card as the follow-up: H-96 refused
`TB_KEK_PASSPHRASE` in the installers, the seal step and `tools.keys`, and three paths still honoured it.

**The start path, read first.** A passphrase box opens its KEK at every start by `tools.keys unseal` (the passphrase
typed, or `--passphrase-file` / `--passphrase-stdin`), which writes the KEK to `/run/trialbox/kek`; every service and
host tool's `load_kek` reads that file first. The environment branch was reached only with no KEK file, and its one
real user was `tools.keys` itself, which hands `load_kek` a mapping holding the value it read from a file or stdin.
That path is unchanged (the lead was told before the change).

**Now.**
- `libs/tb_common/kek.py` `load_kek`: when the passphrase would be derived and the process environment holds
  `TB_KEK_PASSPHRASE`, it refuses (`KekError`, H-96's words, never the value), whatever mapping it was handed (the
  process environment or a copy of it). A mapping `tools.keys` built is still taken. The KEK file is still read first.
- `tools/trialbox/audit_heads.py`: `PASSED` no longer names `TB_KEK_PASSPHRASE`, so the signer's container never gets
  `-e TB_KEK_PASSPHRASE`; it opens the KEK from the unsealed file it mounts, as before.
- `tools/trialbox/backup_schedule.py`: the restic key step no longer forwards it (only `TB_KEK_FILE`). A passphrase
  KEK has no custodians' shares, so that step never makes a restic key for one; the forward was dead there.

**What relied on the environment branch.** Nothing in the tree or the runbooks tells an operator to export the
variable any more: the installers' and runbook 16's `read -rs TB_KEK_PASSPHRASE` is a shell variable of root's own
`bash -c`, written to the root-only file and never exported. RUNBOOK §23's "Where the passphrase still is" said the
adapter and the orchestrator would take it from the stack's environment and the signer was handed it by name: it now
says nothing takes it from an environment, and never to export it. The decision records D-347, D-836 and D-898
describe the environment form as it was; they are history and are left as written (H-96 and this card supersede
them).

**Tests:** `tests/unit/test_kek_env_refused_h97.py` (10): the library refuses an exported value (handed the process
environment, a copy, or a copy with the value) and never prints it, and `tools.keys`'s mapping still opens it; an
empty variable (the compose file's `TB_KEK_PASSPHRASE: ""`) is neither a refusal nor a passphrase, the box is locked
as before; with the KEK file present `load_kek` returns that file's bytes exactly whatever the environment holds
(unset, empty, the passphrase, another value); `tools.keys` builds its mapping only from the file or stdin (a caller's
value is refused before any command runs, an empty one adds nothing); the signer's command line and the environment
its docker command runs with hold neither the name nor the value; the restic step forwards none from `deploy/.env`,
and an exported one is refused at the key's load. Mutants: 5 planted, 4 caught; the survivor (a second guard on the mapping
being the process environment) was equivalent to the refusal above it and was removed from the code.

## Part D: keys already sealed under the passphrase, on a host with no TPM

The integrator's ruling 7104745003 (H-96's L-3). `deploy/check_host.sh` showed a WARN for a host with no TPM whose
site keys are already sealed under the passphrase (`kek.json`), on every box. Now they follow the rule H-96 gave the
back end only named: on a PoC box (the box's recorded environment, `deploy/.env` as compose reads it, through H-96's
`poc_list` and `tools/trialbox/stops.py`; never a caller's variable) a WARN listed in `deploy/site/poc-stops.jsonl` as
`check_host.sh/no-tpm-sealed`; on any other box a FAIL. Both name the action: reseal the site keys under a TPM (on a
board with one, rotate the KEK to the TPM back end, SECURITY §10); the doctor's line of the PoC list carries it.
`tests/unit/test_host_baseline.py::test_no_tpm_fails_unless_the_passphrase_back_end_is_chosen` holds both rows, a
caller's `TB_ENV=TEST` on a PRODUCTION box (still a FAIL), and the action on the FAIL line and the doctor's line.
In H-96's final form, a PoC box whose list line cannot be written is a WARN that says it was NOT listed and names the
action, never a FAIL (`tests/unit/test_host_baseline.py::test_sealed_keys_without_a_tpm_say_when_the_poc_list_line_was_not_written`).
Mutants: 3 planted (always a WARN; no action named; the unwritten line read as a FAIL), 3 caught.

## The review of #1429 (F1 to F10)

The review (fix first: B audited but with gaps) and the lead's relay of 7114889379. Each fix has its own test.

- **F1, the audit event after the rotation.** `keys.rotate_kek_started` (who, when, the box, its environment, the
  old KEK id, the back end, the rule) is written before any key file changes, after the journal; if it cannot be
  written (a full or read-only volume, a broken anchor) the journal is removed and the rotation is refused, nothing
  changed. `keys.rotate_kek` (the done event, with the new KEK id) follows the commit; if it cannot be written the
  journal stays and `status --audit-dir` writes it. Tests:
  `tests/unit/test_rotate_kek_safety_h97.py::test_a_rotation_whose_started_event_cannot_be_written_is_refused` (the
  real `AuditFull`), `::test_a_done_event_not_written_keeps_the_journal_and_status_writes_it`,
  `::test_the_append_as_another_user_that_fails_refuses_the_rotation`; the invariant of part B now checks the
  started event comes first.
- **F2, the day's file made by root.** Run as root against an audit folder another user owns (the console's 10001),
  `tools.keys.append_audit` makes the append in a child process started as that user and group with no other
  groups (`subprocess.run(user=, group=, extra_groups=[])`; the event comes on stdin). A file it creates is that
  user's. Test: `::test_as_root_the_append_is_made_by_the_audit_folders_owner` (stood in: the child runs as the test's
  user and the identity asked for is recorded). Probe as root, no stand-in: a folder owned by 10001 whose chain was
  made the day before; after the rotation the new day file, `.lock` and `HEAD.json` are 10001's and an append as
  10001 succeeds. RUNBOOK §23 says so. The escrow events (`escrow-shares`, `unseal --from-escrow`, an escrow set made
  by `rotate-kek --escrow-out`) still append as the caller: H97-12.
- **F3, any folder.** The audit folder must hold the box's chain (`HEAD.json` with a head); an empty folder is
  refused, nothing changed. Test: `tests/unit/test_rotate_exposed_passphrase_h97.py::test_without_an_audit_folder_or_with_a_wrong_old_passphrase_nothing_changes`.
- **F4, a kill between the renames.** A journal in the secrets folder (`kek-rotation.json`: the step, the key names,
  the two KEK ids; no key) is written first (`staging`), then committed (`committing`) once every new file is
  written and synced. The next `status --audit-dir` or `rotate-kek`, under the lock, rolls a `staging` rotation back
  (the staged files and any temporary file of a write cut short removed; `keys.rotate_kek_rolled_back`) or finishes a
  `committing` one (the remaining renames, `kek.json` last; `keys.rotate_kek` with `resumed`). Without the audit
  folder it does nothing, and custody (so `status`, `check` and doctor) names the journal as a problem with the
  command. RUNBOOK §23, "A rotation cut short". Test, a kill at each step:
  `::test_a_kill_at_any_step_leaves_keys_that_open_and_the_next_command_finishes_or_rolls_back[status]` and
  `[rotate-kek]`: the rotation runs in a child process killed (`os._exit`, no clean-up) at each of its 10 writes
  in turn (the journal, the started event's anchor, two staged keys, `kek.json.next`, the commit, two renames,
  `kek.json`, the done event's anchor); after each, the keys open under the KEK `kek.json` names (old or new, both
  seen), nothing staged or temporary is left, and the chain says which. Also
  `::test_a_rotation_cut_short_is_a_custody_problem_until_finished`. A kill between the done event and the journal's
  removal gives a second `keys.rotate_kek` (with `resumed`) when it is finished: said here, not prevented.
- **F5, no lock.** `rotate-kek` holds an exclusive, non-blocking `flock` on the secrets folder itself (no file is
  added) for the whole rotation and its resume; a second one is refused, nothing changed. `status` takes it only to
  resume. Tests: `::test_a_second_rotation_while_one_runs_is_refused` and `::test_two_rotations_at_once_never_lose_a_key`
  (two processes started together, five rounds: at most one rotates, every key opens under `kek.json`'s KEK). The
  other key commands that write the folder (`init`, `wrap`, `rotate`, `seal-objects`) do not take the lock: H97-13.
- **F6, re-wrap is not re-key.** RUNBOOK §23 says the data keys stay the same, so the old passphrase and a copy of
  the wrapped files from before the rotation still open them, and names the re-key step (`rotate pid_map`, and each
  other key by its inventory rule).
- **F7.** `tests/unit/test_host_baseline.py::test_no_tpm_fails_unless_the_passphrase_back_end_is_chosen`: three rows
  added, a caller's `TB_ENV=DEV` and `VALIDATION` on a PRODUCTION box with the keys sealed, and `DEV` with the back end
  only named: each a FAIL, never listed. The reviewer's M13 (a caller's `TB_ENV=DEV` decides PoC) is caught by two.
- **F8.** `tests/unit/test_rehearsal_poc_stops_h97.py::test_the_rehearsal_passes_only_the_expected_poc_stop` (7 rows):
  the function is taken from `box.sh` as it is and run in bash with the TPM paths pointed at the test's folder. M12
  (any other stop accepted) is caught by three rows.
- **F9, the terminal write unchecked.** The write to `/dev/tty` is the check: when it fails the code goes to the
  screen and the root-only file, and with neither the run stops and says so (as before). Tests:
  `tests/unit/test_first_run_code_h97.py::test_a_terminal_write_that_fails_falls_through_to_the_screen_and_file` (the
  run in an orphaned background process group on a pty with `tostop`: `/dev/tty` opens and every write fails with
  EIO) and `::test_a_terminal_that_hung_up_never_swallows_the_code` (under nohup, the terminal hung up; there the
  kernel drops the controlling terminal, so `/dev/tty` does not open either: this one does not tell the two forms
  apart, the first does).
- **F10.** A trap removes the code file on EXIT, HUP, INT and TERM while the run waits, and is cleared once the
  answers are in. Test: `::test_a_first_run_stopped_while_it_waits_leaves_no_code_file[SIGTERM|SIGHUP|SIGINT]` (exit
  143, 129, 130; no file).

**Master 3945782a (H-94 part 2) merged after the fixes.** H-94 replaced `check_host.sh`'s `poc_list` with the
shared STOP-OR-WARN helper; part D's branch now asks `tb_poc_box` and writes its line with `tb_stop_list`, in the
form of the no-TPM branch beside it (same words, same key, same FAIL and WARNs; the host-baseline tests pass
unchanged, M13 re-planted in `tb_poc_box` is caught by the same two rows). H-94's page gains one row: the first-run
code's kept stop (5) in `box-install.sh` (its count test counts H-97's line), and the three signal exits of the F10
trap are marked `H-94 not a stop`.

**Mutants for the review:** 13 planted, 13 caught. `tools/keys.py` (9): the started event's failure ignored; no
started event; the done event's failure drops the journal; every append as root; any folder taken; no journal; no
commit step; a cut-short rotation always rolled back; no lock (caught by the held-lock test only: the five rounds of
two processes did not lose a key under it in that run). `deploy/box-install.sh` (2): the terminal write unchecked;
no trap. M12 (`box.sh`) and M13 (`check_host.sh`).

## Tests

**Part A, the invariant:**
`tests/unit/test_first_run_code_h97.py::test_the_code_never_reaches_the_journal_or_a_file_others_read` (on and off
WSL2). The real `box-install.sh --firstrun` runs as the service runs it (a new session, no terminal, stdout and stderr
to a file: the journal stand-in), with the caller's `TB_ISSUE_DIR` exported at a folder every user reads and `HOME`
at another folder. The code read from the root-only file is not in the journal stand-in; the file is mode 0600, a
regular file owned by the runner; a voided code is replaced and neither code is in the journal; the old knob's folder
and HOME receive nothing. The same file: at a terminal (a pty as stdout) the code is on it once and no file is made;
with the output piped and a controlling terminal (the WSL2 window's form) the code is on the terminal and not in the
piped log; a planted link is refused and not followed; no line writes `/etc/issue.d` or reads `TB_ISSUE_DIR`.
`tests/console/test_box_install_rehearsal.py` and `tests/console/test_firstrun_folders_10k4.py` now take the code from
the root-only file (no terminal), and the full flow there shows the file removed once the answers are in.

**Part B, the invariant:**
`tests/unit/test_rotate_exposed_passphrase_h97.py::test_a_production_box_rotates_its_exposed_passphrase_and_the_rotation_is_audited`
(file and stdin; TB_ENV unset and PRODUCTION): the keys open under the new passphrase, one `keys.rotate_kek` event
holds who, when, the box and the two KEK ids, and neither passphrase is in the audit folder or the output. Beside it,
`test_the_neighbouring_ceremonies_stay_refused_on_a_production_box`: on the same PRODUCTION box, rotate-kek to the
file, shamir and kms back ends, with an escrow set, and with the new passphrase from neither form, and the ceremony
record, escrow shares, restic key and pid map rotation: each refused with rc1's words, nothing changed, no audit
event. Also: a box not sealed under a passphrase is refused; no audit folder (or a missing one) and a wrong old
passphrase change nothing; a caller's `TB_ENV=DEV` on a box whose `deploy/.env` says PRODUCTION neither widens nor
skips the rule. `tests/unit/test_rc1_refusal_sites.py::test_no_key_ceremony_on_a_production_box` is unchanged and
passes (its rotate-kek is `--backend file`).

### Changed assertions (ruling 7101844662)

1. tests/console/test\_box\_install\_rehearsal.py::test\_under\_wsl2\_the\_code\_is\_on\_the\_output\_and\_no\_issue\_file\_is\_written
   asserted the code on the output; with
2. tests/console/test\_box\_install\_rehearsal.py::test\_off\_wsl2\_the\_code\_is\_on\_the\_output\_and\_on\_the\_boxs\_screen
   (the code on the output and in the issue file), it is now
   `tests/console/test_box_install_rehearsal.py::test_on_or_off_wsl2_the_code_is_never_on_the_output_and_no_issue_file_is_written`
   (both values of the switch): the code in the root-only file, never on the output, no issue file.
3. The same file's helper `_until_code` waited for the code on the output; it now waits for the line that says where
   the code is. Its users: `test_the_installer_writes_the_preflight_for_the_first_run_page`,
   `test_a_preflight_that_hangs_never_holds_the_code_back` (their own assertions unchanged).
4. The same file's `_tree` (and so `test_a_box_installs_from_the_installer_with_only_the_wizards_answers`,
   `test_the_prepared_image_stops_before_the_wizard`, `test_a_stopped_install_stops_the_box_installer`,
   `test_a_box_installs_unattended_from_the_owners_answers_file`) and
   `tests/console/test_firstrun_folders_10k4.py::test_a_production_box_does_not_finish_its_set_up_until_its_folders_are_right`:
   the code's place is the root-only file (a stand-in getent names the test's home; the runs have no terminal) instead
   of `TB_ISSUE_DIR`'s file; their assertions are otherwise the same.
5. `TB_ISSUE_DIR` dropped from the environments of `tests/unit/test_hs1_one_command.py` and
   `tests/unit/test_install_refuses_unsafe_folders_10k4.py` (it no longer names anything; no assertion changed).

No test asserted that rotate-kek with a passphrase is refused on a PRODUCTION box, so part B changed none.

### Changed assertion (ruling 7104745003, part D)

8. `tests/unit/test_host_baseline.py::test_no_tpm_fails_unless_the_passphrase_back_end_is_chosen`, row
   `[extra5-passphrase-PRODUCTION-WARN]` (the keys sealed under the passphrase, PRODUCTION): a WARN on master, now
   `[extra5-passphrase-PRODUCTION-FAIL]`; two rows added (the same on TEST: a listed WARN; a caller's TB_ENV=TEST on
   PRODUCTION: a FAIL), and the listed key is checked for both the named and the sealed back end.

9. The box rehearsal (tools/rehearse\_box/box.sh, install and reinstall phases; H-94's check) required an empty PoC
   list. With part D the rehearsal box (no TPM, keys sealed under the passphrase, a VALIDATION box) lists exactly
   `check_host.sh/no-tpm-sealed`, which the ruling requires. The check now expects exactly that line on a box with no
   TPM (it fails when it is missing), fails on any other line, and requires doctor's `poc_stop` line for it, with its
   action, in that install's own output. Both rehearse jobs of PR #1429 showed the line and doctor's line on the real
   path (head 15d0d36f, before this check expected them): that is part D's real-path check.

### Changed assertions (ruling 7102655419, part C)

6. `tests/unit/test_audit_heads_nightly.py::test_on_a_site_box_the_signer_sees_the_audit_volume_read_only_and_the_event_goes_to_the_journal`
   asserted the signer is handed `TB_KEK_PASSPHRASE` by name; it now asserts the name is not there either.
7. `tests/unit/test_restic_password.py::test_a_passphrase_kek_has_no_shares_and_gets_no_copy`: its set-up exported
   `TB_KEK_PASSPHRASE` for "the library's own path"; it now hands the value in a mapping, as `tools.keys` does.

**H96-07 left as it is.** `tests/unit/test_install_faults_runbook.py::test_installers_reject_passphrase_file_input`
keeps its name (no ruling to rename or retire it); H96-07 stays open.

**Mutants:** 22 planted on the new checks, 20 caught by the card's tests. Part A (13): the code on stdout always, also
on stdout from the terminal branch, also on stdout with no terminal, no umask, no link refusal, no removal before the
write, HOME naming the file, the old knob's file kept, the file not removed after the answers, a group-readable file,
no stop when there is no place (caught as a non-root user, CI's case: a root host writes the console and goes on).
Part B (9): every rotate-kek let through, any back end, an escrow set, any passphrase form, any old back end, no audit
folder needed, no audit event, a passphrase in the event, no "who". Two survived and are equivalent: the text echoed
on the journal line (it is emptied before that line), and `set -C` removed (it guards only a link planted between
the removal and the write, which a single-threaded test cannot reach; H-96's survivor too).

## Files outside the card

Bodies only: `deploy/gcp/box-install-run.sh` and `deploy/gcp/box_vm.py` (the cloud box run: the root-only file in
place of the issue file; a docstring), `tests/rehearsal/box-run/standins/boot.sh` and the new
`tests/rehearsal/box-run/shims/getent`, `libs/tb_common/rc1_refusals.py` (the key ceremonies row's words),
`tools/keys.py` (rotate-kek), `libs/tb_common/kek.py` (`load_kek`'s body and module text),
`tools/trialbox/audit_heads.py` (`PASSED`), `tools/trialbox/backup_schedule.py` (one line), `deploy/check_host.sh`
(part D; H-96's file), the tests named under "Changed assertions", and the hospital pages
(`docs/handover/hospital-install.en.md`, `.ja.md`, `.zh-TW.md`, step 7). For the review: `libs/tb_common/kek.py`
(`ROTATION_JOURNAL` and one custody problem), `tests/unit/test_host_baseline.py` (three rows), and the set-ups of
the six tests under 7114085298 above, four of which now seed the audit chain (`test_kek`, `test_objstore_sealed`,
`test_sign_keys_kek`, `test_kek_passphrase_file_h96`; nothing they assert changed), and
`docs/handover/poc-stops-h94-2026-11-23.md` (one row in its box-install.sh table).

## Findings

In `first-run-code-h97-2026-11-23/findings.json` (H97-01 to H97-15; H97-11 to H97-15 from the review of #1429): the code in the journal and the issue file
(fixed), the rehearsal that has no first-run step (not run), the screen of a desktop box and a VM's console, a
terminal's scrollback and sudo's I/O log, boxes before H-97, rotate-kek on PRODUCTION (fixed, D-1092), the host's
append to the audit folder beside the audit writer (not run), the WSL2 window (not run), the environment form outside the installers (fixed, part C), and keys sealed under the passphrase without a TPM
(fixed, part D).

## Questions

1. Part A changes tests that asserted the code on the output (the list above). They are read as covered by ruling
   7101844662, whose rule they contradict; does the integrator agree?
2. (Answered by ruling 7114085298: every rotation is audited.)
3. `status` now writes when given the audit folder and a rotation was cut short (it finishes or rolls it back, as
   the lead's relay asked); without the folder it only reports. Should the doctor's own check do the same, or keep
   reporting only (as now)?
4. H97-12 and H97-13 (the escrow events still appended as the caller; the other key commands without the lock) are
   left for a card of their own. Agreed?
