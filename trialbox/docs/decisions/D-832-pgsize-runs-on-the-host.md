# D-832 pgsize runs on the host's python3; a failed sizing says so

- **Task:** I-1 of the independent examination of the bundle and installer path (2026-11-15, #639): a regression on
  master since train 24
- **PR:** this branch (`agent/I-1-pgsize-on-the-host`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-751 (T-703, pgsize), D-831 (HOST_PY_MODULES)

## Decision

1. `tools/trialbox/pgsize.py` is standard library only: it keeps its own copy of `TB_LAKE_QUERY_LIMITS`'s default
   (a test keeps it equal to `DECLARED`) instead of importing `tb_common.config` (pydantic, jsonschema, ...), which
   the host's python3 lacks. On a clean Ubuntu 24.04 host install.sh stopped there.
2. The memcaps, pgsize and TLS checks hang `|| die` on the pipe itself: under `set -e` and `pipefail` a failing pipe
   ended the script before the old `[ "${PIPESTATUS[0]}" = 0 ] || die` line, so the operator saw only a traceback.
   A test now fails any PIPESTATUS read outside `set +e` (inside a function: at every call).
3. A test runs the host steps that need no Docker (pgsize, memcaps, bootwait, the image lock check, the anchor
   overlay, the secrets) in a bare interpreter with PyYAML alone, so a lazy import fails the test. The steps that
   need Docker are left to the rehearsal job (I-8).

## Test

`tests/unit/test_host_python_runs.py`: before, pgsize failed with "No module named 'tb_common'" and the die and
default checks failed; after, all pass.
