# H-118: the unsealed KEK goes to the box's own place, never a caller's TB_KEK_FILE (1457-6)

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

Lane H, 2026-11-24. The review of #1457, finding 1457-6 (Low; comment 7122962689). The integrator's rulings
7125021924 (the place is fixed; the assertion of `test_the_sealed_files_belong_to_the_services_user` may change) and
7125341668 (seven further assertions on the same two terms; scope: the sealing script; the command line's environment
fallback is card H-119). Synthetic keys only; no TPM was used.

## The fault

`deploy/hardening/seal_keys.sh` took the place of the unsealed KEK from the caller's environment:
`KEK_FILE="${TB_KEK_FILE:-$RUN_DIR/kek}"`. With `TB_KEK_FILE=/etc/trialbox.kek` the plain KEK was written to
persistent disk, beside the TPM-sealed one, and D-887's hand-over (`chown "$OWNER" "$KEK_FILE" "$(dirname
"$KEK_FILE")"`) gave that folder, `/etc`, to the services' user.

## What is built

`seal_keys.sh` writes the unsealed KEK to `$RUN_DIR/kek` every time. On a box that is `/run/trialbox/kek`, a tmpfs,
the place the boot unit `trialbox-unseal.service` writes and the services read. In tests `TB_HOST_ROOT` puts the
host's root under a temporary folder, as it does for every path in the script. A caller's `TB_KEK_FILE` is not used,
and one line says so when it names another place. The box's own value is still exported to the keys commands and
passed to the image (`-e TB_KEK_FILE`). When the keys commands run in the image (a host whose python3 has no
`cryptography`), the image is given `/run/trialbox-seal` too, once the run has made it (review of #1482, 1482-1, below).
D-887's hand-over therefore only ever gives the box's own `/run/trialbox` to
the services' user.

Out of this card (ruling 7125341668): `tools.keys` keeps its explicit `--out`. Its fallback to the environment in
`runtime_kek_path` (unseal, escrow unseal, rotate-kek's runtime update) is card H-119.

## The plain KEK's own folder (#1457's last review, 1457-9)

`seal_keys.sh` made the plain KEK (`kek.new`, the copy that exists only while a TPM seal runs) in `/run/trialbox`.
D-887's hand-over gives that folder to the services' user, so a host process of that user could put a link at the
name. #1457 removed any name there under the host lock and stopped shredding through a link; what remained was a race
between that check and the write. `kek.new` is now made in `/run/trialbox-seal`, which the run makes under the host
lock with mode 0700 and never hands over. If the name is a link, another user's folder, or a folder open to others, the
run is refused and nothing changes. The owner is compared with the shell's own (`/proc/$$`), not `id`.

Tests (each fails on master's script, eeb1e4f):
- `test_the_plain_kek_is_made_in_a_folder_of_its_own_never_handed_over`: the sealing stand-in records the folder of
  the KEK it seals: `/run/trialbox-seal`, this user's, 0700; nothing is left there; the hand-over never names it.
- `test_a_seal_folder_that_is_not_this_runs_own_is_refused_and_nothing_changes[a link|open to others]`.

- `test_a_seal_folder_that_is_not_this_runs_own_is_refused_and_nothing_changes[another user's]`: mode 0700 but
  another owner (a stand-in `stat` says so, as an ordinary user cannot make one).
- `test_a_link_at_the_old_place_is_never_written_through`: a link left at `/run/trialbox/kek.new` is neither written
  nor shredded through, and stays as it was.

The tests that named the old place, under the integrator's ruling 7138516776 ("keep and add twins, do not move"):

| Test | Old | New |
| --- | --- | --- |
| `test_host_baseline.py::test_seal_keys_wraps_the_plain_keys_under_a_tpm_sealed_kek` | no `run/trialbox/kek.new` | kept, and a twin: no `run/trialbox-seal/kek.new` |
| `test_seal_keys_signal_h111.py` `_sealed_and_done` (every test that finishes a seal) | no `run/trialbox/kek.new` | kept, and a twin for `run/trialbox-seal/kek.new` |
| `test_seal_keys_signal_h111.py::test_a_second_signal_during_the_clean_up_leaves_no_plain_kek` | no `run/trialbox/kek.new` | kept, and a twin for `run/trialbox-seal/kek.new` |
| `test_seal_keys_signal_h111.py::test_the_kek_opened_from_the_credential_is_never_written_through_a_link` | the link planted at `run/trialbox/kek.new` | planted at `run/trialbox-seal/kek.new` (setup moved); asserts unchanged |
| `test_seal_keys_signal_h111.py::test_a_fresh_seal_never_writes_or_shreds_the_kek_through_a_link` | links planted in `run/trialbox` | planted in `run/trialbox-seal`, made 0700 as the run makes it (setup moved); asserts unchanged |

The old place keeps its own case (`test_a_link_at_the_old_place_is_never_written_through`, above).

Mutants, each caught: `kek.new` back in `/run/trialbox` (4 tests); the mode check removed; the owner check removed;
the caller's `TB_KEK_FILE` put back. The link test alone (`[ -L ]`) is not caught when removed: `stat` without `-L`
reports a link's own mode, 0777, so the mode check refuses a link as well. It stays as the plain statement of intent.
The review of #1482 found two more not caught by those tests: `! -d` removed (equivalent: `mkdir -p` on a non-folder
fails first under `set -e`), and the traps set before the folder check (not equivalent: 1482-2, below; now caught).

## Who reads TB_KEK_FILE

| Where | What it is | Changed |
| --- | --- | --- |
| `deploy/hardening/seal_keys.sh` | it decided where the unsealed KEK is written: a caller's variable | yes: the box's own place |
| `tools/keys.py` `runtime_kek_path` | where `unseal` and `rotate-kek` write when `--out` is not given: a caller's variable | no: H-119 |
| `libs/tb_common/kek.py` `kek_sources`/`load_kek` | where a service looks for the KEK; declared in `config.py`; nothing in the compose files sets it, so the services use the default | no: a reader |
| `tools/trialbox/audit_heads.py` (`PASSED`, and the mount at line 211) | passed on to the audit container, and the KEK's folder mounted read-only | no: a reader |
| `tools/trialbox/backup_schedule.py:1127`, `tools/trialbox/box_restore.py:259` | passed on where the KEK is opened | no: readers |
| `tools/rehearse_box/box.sh:715` | the restore rehearsal's own place | no: a reader |
| the trusted unit `trialbox-unseal.service` | writes `/run/trialbox/kek` by `--out`; does not read the variable | no |
| tests | fixtures for the readers above; the seal tests' `TB_KEK_FILE` is now the caller's, and ignored | eight assertions, below |

## The eight assertions, old and new

Each moves only the KEK's location, from the caller's `TB_KEK_FILE` to the fixed place. Nothing else it asserts
changes.

| Test | Old | New |
| --- | --- | --- |
| `test_seal_keys_order.py::test_the_sealed_files_belong_to_the_services_user` (root only) | `env["TB_KEK_FILE"] = tmp/run/kek`; `kek.json`, the wrapped keys, `tmp/run/kek` and `tmp/run` belong to uid 10001, owner only | `kek_dir = tmp/host/run/trialbox` (the box's place, no `TB_KEK_FILE` given); `kek.json`, the wrapped keys, `kek_dir/kek` and `kek_dir` belong to uid 10001, owner only |
| `test_seal_keys_order.py::test_the_tpm_path_seals_then_wraps` | `tmp/kek.runtime` == the credential | `tmp/host/run/trialbox/kek` == the credential |
| `test_seal_keys_order.py::test_the_passphrase_path_without_a_hardening_conf` | `tmp/kek.runtime` is 32 bytes | `tmp/host/run/trialbox/kek` is 32 bytes |
| `test_kek_passphrase_file_h96.py::test_no_passphrase_in_a_sudo_log_an_argument_or_an_environment_through_the_signed_rerun[file]` | the passphrase derives `tmp/kek.runtime` | it derives `<host root>/run/trialbox/kek` |
| the same, `[file-kept]` | as above | as above |
| the same, `[stdin]` | as above | as above |
| `test_kek_passphrase_file_h96.py::test_the_file_is_removed_after_sealing_and_kept_when_asked` | `tmp/kek.runtime` derives from the passphrase; removed (a restart); the re-run writes it again | the same, at `tmp/host/run/trialbox/kek` |
| `test_install_faults_review_round.py::test_the_image_fallback_takes_the_passphrase_on_stdin_never_in_the_container_environment` | the passphrase derives `tmp/kek.runtime` | it derives `tmp/host/run/trialbox/kek` |

## Tests

`tests/unit/test_seal_keys_kek_place_h118.py` collects 10 tests: the 4 below, the 5 of the plain KEK's own folder
(above) and the 1482-2 test (below). `tests/unit/test_seal_keys_image_mounts_ocr1482.py` has 1 (1482-1, below). The 4
below each fail on the script before this card and on the mutant that puts the variable back
(`KEK_FILE="${TB_KEK_FILE:-$RUN_DIR/kek}"`):

- `test_a_callers_kek_file_never_decides_where_the_unsealed_kek_goes[tpm]` and `[passphrase]`: nothing at the
  caller's place; the KEK at the box's place, owner only, opening the keys; the line says the variable is not used.
- `test_a_rerun_unseals_to_the_box_place_too`: the `kek.json` branch (a restart) unseals to the box's place.
- `test_no_callers_folder_is_handed_to_the_services_user`: with stand-ins for `id -u` (root) and `chown`, D-887 asks
  for the box's `/run/trialbox` and its `kek`, and never for anything under the caller's folder.

## Review of #1482 (OCR, comment 7143739346, at 2e5d5ad)

- **1482-1 (Medium, fixed).** On a host whose python3 has no `cryptography`, the keys commands run in the image, which
  was given `$SECRETS` and `$RUN_DIR` but not `/run/trialbox-seal`. `keys init --kek-in .../kek.new` then failed on
  every TPM seal, and every re-run failed the same way (the keys stayed plain, the credential placed). Master was not
  affected (`kek.new` sat in the mounted `$RUN_DIR`). Fixed with the review's patch: `tool` mounts the seal folder only
  once `arm` has made it, because an engine makes a missing `-v` source as root's 0755, which the next `arm` refuses.
  Test (the review's): `test_seal_keys_image_mounts_ocr1482.py::test_the_tpm_path_seals_wraps_and_unseals_through_the_image`,
  with an engine stand-in that hides every path no `-v` covers. It fails without the mount and passes with it.
- **1482-2 (Low, fixed).** The folder check runs before the clean-up trap is set; nothing pinned that order. With the
  traps set first, a refused link to another folder would have its `kek.new` shredded through it. Test (the review's):
  `test_seal_keys_kek_place_h118.py::test_a_refused_seal_folder_removes_nothing_through_it`. It fails under that mutant.
- **1482-3 (Low, fixed).** This page gave the test count as 4 and did not name the seal folder among the image's
  mounts; H118-01 was `open` in the findings file though fixed here. All three are corrected.
- For D-1461's one owner rule: `/run/trialbox-seal` is root's only (0700). Neither D-887's hand-over nor H-133's owner
  rule reaches it.

## Not verified

- A real TPM, and a real box's `/run`.
- A real container engine: that it makes a missing `-v` source as root's 0755 (why the seal folder is mounted only
  once it exists) is from the engine's documented behaviour; the stand-in cannot show it.
- `tools.keys`' environment fallback (H-119).
