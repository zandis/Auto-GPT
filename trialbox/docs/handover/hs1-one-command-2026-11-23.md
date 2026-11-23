# HS-1: the hospital's one command (2026-11-23)

**Reader:** the people who build TrialBox: lane H, lane K, the integrator and the independent reviewer. Findings for
builders, so in one language.

Card HS-1 of the hospital-simple-install design (`docs/plan/design/hospital-simple-install.md`, section 5 row 1;
sections 2.1 step 1, 2.5, 2.6, 2.7). Findings in the register's `--add-from` form:
`hs1-one-command-2026-11-23/findings.json`. No decision number was given. A decision may be needed for the
fingerprint's form (finding HS1-05) and for the launcher's own trust (finding HS1-01).

## What IT types

```
sudo bash /media/<stick>/install
```

No option. `tools/make_bundle.sh` now writes two more files beside the bundle: `install` (a copy of
`deploy/launcher.sh`) and `vendor_ed25519.pub`, the public half of the signing key. It prints the key's fingerprint
for the delivery sheet. The launcher, in order:

1. finds the stick's files beside itself (exactly one bundle, the bootstrap, its `.sig`, the key), or stops;
2. shows the key's fingerprint (the first 24 hex digits of the sha256 of the key's DER form, in groups of four) and
   asks for `yes` or `no`. Only `yes` (or `y`) goes on. `no`, any other text, an empty line or a closed standard
   input stops, with nothing changed;
3. copies the bootstrap and the key to a private folder, checks the bootstrap's signature there with openssl, and
   runs that copy with `--box`. A wrong or missing signature stops, with nothing changed.

`deploy/bootstrap.sh --box` does what it did, then runs `deploy/box-install.sh` instead of `deploy/install.sh`. The
bootstrap's own bundle check with the same key is kept. Its line about the key now shows the same fingerprint.
`deploy/box-install.sh` is unchanged: the box form already plans from the hardware with no `--tier` and no
`--answers`. The longer forms (RUNBOOK §1's command, the bootstrap's `--pub ... -- <options>`, `box-install.sh`'s
flags) work as before. `tools/windows_media.py` is unchanged: the Windows media has its own double-click launcher.

The launcher's lines are plain English. The deploy scripts' text does not go through a catalogue today. HS-5 owns
that move.

## The tests

`tests/unit/test_hs1_one_command.py`, 18 tests (10 functions). The fake host is the real `deploy/box-install.sh` in a signed host
tree, with a hardware fixture and a stand-in inner install that stops after the plan. Keys are made in the test's
temp root.

| Test | What it proves |
| --- | --- |
| `test_a_run_with_only_the_sticks_path_reaches_the_plan` | The design's first test: the plan's answers are written and the inner install gets the plan's flags |
| `test_a_no_to_the_fingerprint_stops_with_nothing_changed` | The design's second test, for `no`, `n`, an empty line, other text and a closed standard input: every file under the test's root is the same |
| `test_a_wrong_signature_stops_with_nothing_changed` | **The invariant for the review.** Another key, a bootstrap changed after signing, an empty `.sig`, no `.sig` |
| `test_a_bundle_signed_by_another_key_still_stops_in_the_bootstrap` | The bootstrap's own bundle check is kept |
| `test_the_fingerprint_is_one_definition_in_the_launcher_the_bootstrap_and_the_bundle_builder` | One fingerprint line in the three files |
| `test_the_bootstrap_shows_the_same_fingerprint` | The bootstrap prints it; without `--box` it runs `install.sh` as before |
| `test_the_launcher_takes_no_option`, `test_a_stick_without_one_release_stops` | No flag is taken; a stick with two bundles or no key stops |
| `test_the_launchers_messages_are_plain_with_one_action_each` | No setting, D number, RUNBOOK section or flag on the screen; one action per stop |
| `test_make_bundle_puts_the_launcher_and_the_key_on_the_stick` | The builder's lines |

Ten mutants were planted in the launcher and the bootstrap (no signature check, any answer taken, a closed input
taken, no `--box`, another fingerprint length, an option taken, two bundles taken, no bundle check, the temp folder
kept, `--box` ignored). All ten were caught.

## What HS-2 must supply

Nothing is passed through for the tier or an answers file: the box form plans from `tools.box detect`. HS-2 adds
the confirmation screen, the no-GPU line, the key back end from the TPM and the time zone. The launcher takes no
flag. HS-2's detection goes in `deploy/box-install.sh` and `tools/box/plan.py`, not in the launcher.

## Findings

| Id | Severity | Claim | Basis |
| --- | --- | --- | --- |
| HS1-01 | High | The launcher on the stick is not signed. A swapped stick can carry another launcher, key and bootstrap, and show the genuine fingerprint. The paper code protects only an honest launcher | hypothesis |
| HS1-02 | Low | The bootstrap's `exec` skipped its EXIT trap. Every run left its temp folder, with the unpacked host tree, behind. Fixed here | shown |
| HS1-03 | Medium | A bare machine with no Docker still stops in `box-install.sh` with a message that names `box-prepare.sh ... --pub`. Row 53's second half is not removed by this card | shown |
| HS1-04 | Low | RUNBOOK §1 still writes only the long command. The runbook page is outside this card's files | shown |
| HS1-05 | Low | The fingerprint's form (96 bits, 24 hex digits) was chosen here without a decision | not stated |

## Not run, not verified

No real stick, no root, no Docker. The full `tools/make_bundle.sh` was not run: it needs Docker to export images.
Its new lines are checked by text and by the fingerprint test. The launcher was not run from a Windows double-click.
