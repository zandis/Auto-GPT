# HS-1: the hospital's one command (2026-11-23)

**Reader:** the people who build TrialBox: lane H, lane K, the integrator and the independent reviewer. Findings for
builders, so in one language.

Card HS-1 of the hospital-simple-install design (`docs/plan/design/hospital-simple-install.md`, section 5 row 1;
sections 2.1 step 1, 2.5, 2.6, 2.7). Findings in the register's `--add-from` form:
`hs1-one-command-2026-11-23/findings.json`. No decision number was given. The integrator ruled on HS1-01 and HS1-05
(below); a decision record, if one is wanted, is the integrator's to number.

## What IT types

On a supervised PoC with synthetic data:

```
sudo bash /media/<stick>/install
```

On a site's own hardware, the delivery sheet's one line, with stock Ubuntu tools only:

```
sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ "$a" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX
```

It copies the launcher to a private file, prints the first 24 hex digits of that copy's sha256 and waits. Only
after `yes` does it run that copy, with the stick's folder as its one argument. Nothing from the stick runs before
the code is compared with the sheet.

## The delivery sheet

`tools/make_bundle.sh` writes, beside the bundle, `install` and `vendor_ed25519.pub`, the public half of the
signing key. It pins the key's fingerprint inside `install` as it writes it, and it refuses to finish if the pin is
not there. It prints, for the sheet:

- the vendor key's fingerprint: the first 24 hex digits of the sha256 of the key's DER form, in six groups of four
  (96 bits; the integrator's ruling on HS1-05). The launcher and the bootstrap show it in the same form;
- the launcher's code: the first 24 hex digits of the sha256 of the stick's `install`, in the same form;
- the sheet's line above, and the stick's label, `TRIALBOX`, with no space.

## What the launcher does

`deploy/launcher.sh` is read whole before any of it runs: its body is a function, called on the file's last line.
In order:

1. it finds the stick's files (exactly one bundle). It refuses a link, a file that is not a plain file, and a stick
   path with a space or a glob sign;
2. it copies the bootstrap, its `.sig` and the key to a private folder (0700), at most 256 KiB each. Only these copies
   are used from here on;
3. the copied key's fingerprint must equal the pin, or it stops before the question. It shows the fingerprint and
   asks for `yes` or `no`. Only `yes` (or `y`) goes on. `no`, any other text, an empty line or a closed standard
   input stops, with nothing changed;
4. it checks the copied bootstrap's signature with the copied key and runs that copy with `--box`. A wrong or missing
   signature stops, with nothing changed.

`deploy/bootstrap.sh --box` does what it did, then runs `deploy/box-install.sh` instead of `deploy/install.sh`. The
bootstrap's own bundle check with the same key is kept. It shows the same fingerprint. It also refuses a bundle path
with a space or a glob sign before it writes anything. The update step (`tools/apply_update.sh`) refuses such a path
too, but only after the tree is unpacked. `deploy/box-install.sh` is unchanged: the box form already plans from the
hardware with no `--tier` and no `--answers`. The longer forms (RUNBOOK §1's command, the bootstrap's
`--pub ... -- <options>`, `box-install.sh`'s flags) work as before. `tools/windows_media.py` is unchanged: the
Windows media has its own double-click launcher.

The launcher's lines are plain English. The deploy scripts' text does not go through a catalogue today. HS-5 owns
that move.

## The tests

`tests/unit/test_hs1_one_command.py`. The fake host is the real `deploy/box-install.sh` in a signed host tree, with
a hardware fixture and a stand-in inner install that stops after the plan. The stick's `install` is written by
`tools/make_bundle.sh`'s own lines. Keys are made in the test's temp root.

| Test | What it proves |
| --- | --- |
| `test_a_run_with_only_the_sticks_path_reaches_the_plan` | The design's first test |
| `test_a_no_to_the_fingerprint_stops_with_nothing_changed` | The design's second test: `no`, `n`, an empty line, other text, a closed standard input |
| `test_a_wrong_signature_stops_with_nothing_changed` | **The invariant for the review.** Another key, a bootstrap changed after signing, an empty `.sig`, no `.sig` |
| `test_a_line_written_into_install_during_the_prompt_does_not_run` | M1: the stick's `install` appended to, or rewritten in place, while the question waits |
| `test_the_sticks_files_swapped_during_the_prompt_are_not_what_runs` | M2: another key's bootstrap, `.sig` and key swapped in while the question waits |
| `test_openssl_reads_only_the_private_copies` | M2: every file openssl fingerprints or checks is a private copy |
| `test_the_private_copies_are_private_and_gone_after` | The private folder is 0700 and removed |
| `test_a_key_other_than_the_pinned_one_stops_before_the_question` | HS1-01: a whole other set on the stick is refused by the pin |
| `test_a_launcher_without_its_pin_and_a_key_that_cannot_be_read_stop` | An unpinned launcher and an unreadable key stop |
| `test_a_link_or_a_large_file_on_the_stick_stops_with_nothing_changed` | L1, for each of the three files |
| `test_a_stick_path_with_a_space_stops_before_anything_changes` | L2, in the launcher and in the bootstrap |
| `test_the_sheets_line_runs_the_copy_only_after_its_code_is_confirmed` | The sheet's line, as make_bundle prints it |
| `test_a_bundle_signed_by_another_key_still_stops_in_the_bootstrap` | The bootstrap's bundle check is kept |
| The fingerprint, option, stick, message and make_bundle tests | One fingerprint line in three files; no flag; plain lines with one action |

The rewrite-in-place case fails against the launcher at `3dd8f5b0` and passes now. 23 mutants were planted: the
review's 8 (each `$stick` for a private copy, `chmod 0777`, the unreadable-key stop in place of the old length check)
and 15 more. 22 were caught. The survivor splits the last line (`main "$@"` and `exit $?` on two lines): bash had
already buffered the last line, so a rewrite of the file did not reach it.

## What HS-2 must supply

Nothing is passed through for the tier or an answers file: the box form plans from `tools.box detect`. HS-2 adds
the confirmation screen, the no-GPU line, the key back end from the TPM and the time zone, in
`deploy/box-install.sh` and `tools/box/plan.py`, not in the launcher.

## Findings

| Id | Severity | Claim | Basis | State |
| --- | --- | --- | --- | --- |
| HS1-01 | High | The stick's launcher is code from the stick. Ruled: accepted for a supervised PoC on synthetic data. The anchor is the sheet: the launcher's code beside the key's fingerprint, and the launcher pins the key | shown | open |
| HS1-02 | Low | The bootstrap's `exec` skipped its EXIT trap, so every run left its temp folder behind | shown | fixed |
| HS1-03 | Medium | A bare machine with no Docker still stops in `box-install.sh` with a message that names `box-prepare.sh ... --pub` | shown | open |
| HS1-04 | Low | RUNBOOK §1 still writes only the long command | shown | open |
| HS1-05 | Low | The fingerprint's form. Ruled: 96 bits in six groups of four, the same on the sheet and the screen | shown | fixed |
| HS1-06 | Medium | M1: bash read the launcher from the stick as it ran, so a line written in during the question ran after the signature check | shown | fixed |
| HS1-07 | Medium | M2: no test held the copy, then verify, then run order. 8 of 8 of the review's mutants survived | shown | fixed |
| HS1-08 | Low | L1: the launcher copied the stick's files whole, links followed, before any check | hypothesis | fixed |
| HS1-09 | Low | L2: a stick path with a space was refused by the update step only after the tree was unpacked | shown | fixed |

## Not run, not verified

No real stick, no real `sudo`, no desktop automount, no root, no Docker. The full `tools/make_bundle.sh` was not
run: it needs Docker. Its pin, sheet and line are run by the tests from its own lines. The sheet's line was run
without `sudo` and with the test's paths. L1 was not run with a file of several GB. Nothing was run on Windows.
