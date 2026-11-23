# H-97: the first-run code in no journal or file others read; a PRODUCTION box rotates its exposed passphrase

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-23. Card H-97 (High, keys), HIGH-RISK: an independent review reads it before it rides. Built to the
integrator's ruling 7101844662 on findings H96-09 (part A) and H96-04 (part B, decision D-1092). It builds on H-96
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
(`--audit-dir`, else `TB_AUDIT_DIR`), refused before anything is read or written without one, and after the keys
are re-wrapped it writes `keys.rotate_kek`: who (the user it runs as and the kernel's login uid, never a variable the
caller sets), when, the box's host name, the environment, the old and the new KEK ids, `D-1092`. Never a value. The
rc1 table's row says so; its message, its sites and every other refusal are unchanged. RUNBOOK §23's rotation
section (still a section, no new number) says a PRODUCTION box rotates itself, with the audit folder, and that every
other rotation stays refused there.

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
`tools/keys.py` (rotate-kek), the tests named under "Changed assertions", and the hospital pages
(`docs/handover/hospital-install.en.md`, `.ja.md`, `.zh-TW.md`, step 7).

## Findings

In `first-run-code-h97-2026-11-23/findings.json` (H97-01 to H97-08): the code in the journal and the issue file
(fixed), the rehearsal that has no first-run step (not run), the screen of a desktop box and a VM's console, a
terminal's scrollback and sudo's I/O log, boxes before H-97, rotate-kek on PRODUCTION (fixed, D-1092), the host's
append to the audit folder beside the audit writer (not run), and the WSL2 window (not run).

## Questions

1. Part A changes tests that asserted the code on the output (the list above). They are read as covered by ruling
   7101844662, whose rule they contradict; does the integrator agree?
2. The rotation on PRODUCTION is audited only there; on DEV, TEST and VALIDATION rotate-kek writes no event (as
   before). Should every rotation be the same audit event?
