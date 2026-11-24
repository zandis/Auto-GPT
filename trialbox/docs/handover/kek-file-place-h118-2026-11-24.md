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
passed to the image (`-e TB_KEK_FILE`). D-887's hand-over therefore only ever gives the box's own `/run/trialbox` to
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

Mutants, each caught: `kek.new` back in `/run/trialbox`; the folder check removed; its link test removed; its mode
test removed; the caller's `TB_KEK_FILE` put back.

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

`tests/unit/test_seal_keys_kek_place_h118.py` has 4 tests. Each fails on the script before this card and on the
mutant that puts the variable back (`KEK_FILE="${TB_KEK_FILE:-$RUN_DIR/kek}"`):

- `test_a_callers_kek_file_never_decides_where_the_unsealed_kek_goes[tpm]` and `[passphrase]`: nothing at the
  caller's place; the KEK at the box's place, owner only, opening the keys; the line says the variable is not used.
- `test_a_rerun_unseals_to_the_box_place_too`: the `kek.json` branch (a restart) unseals to the box's place.
- `test_no_callers_folder_is_handed_to_the_services_user`: with stand-ins for `id -u` (root) and `chown`, D-887 asks
  for the box's `/run/trialbox` and its `kek`, and never for anything under the caller's folder.

## Not verified

- A real TPM, and a real box's `/run`.
- `tools.keys`' environment fallback (H-119).
