# Three Low follow-ups of lane H: the 64 GB Spark and the two-device limits (2026-11-19)

**Reader:** the people who build TrialBox: lane H and the integrator. For builders, so in one language.

Card H-61 closes three Low findings in one change. All three are fixed in commit
d5d75cdc98dd47b7582532cc6abdeec1c88cf640. Each finding's state is set in its own findings file. The register picks
the states up at its next `--sync-states`. No decision was needed: D-1335 binds the first two.

Tests: `tests/unit/test_three_low_follow_ups.py`. On master 12 of its 13 tests fail. The one that passes on master
checks that a 128 GB host and unknown memory still pass. All 13 pass after the change.

## H10E5-02: a gb10 record on a 64 GB host

Finding: [`tier-c-by-memory-2026-11-19/findings.json`](tier-c-by-memory-2026-11-19/findings.json).
`tools/serving_config.measured_for(rec, "gb10")` now reads the host's memory too. Under 96 GiB the host is the 64 GB
class, and nothing of that class is measured (D-1335). So the gb10 record does not count there, and the reason says
so. The rule is the one `deploy/gpu_profile.sh memory-class` uses: `MemTotal` in kB, below 100663296 is the small
class, and unknown memory is not refused.

- The memory comes from a parameter, `mem_kib`. Its default reads `/proc/meminfo`. No other profile reads it.
- The `measured` command takes `--mem-kib`.
- `tools/tiers.py` passes the memory it read or was given.
- `tools/tier_record.py` passes unknown memory. It checks a record, not the machine it runs on.
- Two existing tests in `tests/unit/test_hardware_profiles.py` called the rule for gb10 and would have read this
  machine's memory. They now pass unknown memory. Their assertions are unchanged.

## H10E5-03: `check_host.sh --gb10` on a 64 GB host

Finding: the same file. `deploy/check_host.sh` with `--gb10` (or `--gpu gb10`) now prints a FAIL line on a host
under 96 GiB, with `--gpu-only` and in the full check. The reason has the same sense as install.sh's refusal: the
64 GB class, nothing measured, none guessed (card 10E-5, D-1335), and install with `--mode stub`. It uses
`gpu_profile.sh memory-class`. `TB_TEST_MEM_KIB` stands in for `MemTotal` in tests, as in install.sh. Unknown memory
prints nothing new. The existing `--gb10` tests (`tests/unit/test_images_lock.py`, and `run_check_host` in the
runbook's install-commands test) now give a 128 GB stand-in, so they do not read this machine's memory.

## H58-03: the limits lint and the two-device stacks

Finding: [`hardening-follow-ups-2026-11-19/findings.json`](hardening-follow-ups-2026-11-19/findings.json).
`tests/unit/test_compose_limits.py` now lints the two-device stacks (`TWO_DEVICE_STACKS`). It also checks that
every compose file under deploy/, subfolders included, is in a linted stack. `tests/unit/test_container_hardening.py`
reads the same list, so the two stacks are written once. The rendered check gives the two-device stacks
documentation addresses (RFC 5737), as the hardening test does.

The lint then named the `link` service in both two-device files. It had no `pids_limit` and no `tb.watchdog` label.
That was a plain omission: every other service of the same image takes `pids_limit: 512` and `tb.watchdog: restart`
from `x-py` in `docker-compose.yml`. Both were added. No figure was invented: 512 is that default, not a
measurement. The link's memory cap (1g, unmeasured, D-373) is unchanged.

## What was and was not run

No GPU, no Docker daemon, no Spark. The memory figures are synthetic. `docker compose config` ran for every stack,
the two-device ones included. Not shown: a check on a real 64 GB Spark, or that the link starts under its new pids
cap.
