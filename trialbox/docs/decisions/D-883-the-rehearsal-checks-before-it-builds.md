# D-883 the box rehearsal checks its Trivy database and disk before it builds

- **Task:** I-7 (rehearse.sh preconditions), the integrator's I-7 list on #639
- **PR:** this branch (`agent/I-7c-rehearse-checks-before-it-starts`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

`make rehearse-box`'s first step runs `python -m tools.rehearse_box.preflight`: the Trivy `db` and `java-db` the
release gates read (`vulns.db_problems`, at most 7 days old; else "run `make trivy-db`"), and at least
`TB_REHEARSE_MIN_FREE_GB` (default 30, an estimate, not a measurement) free for the work dir and for Docker's root
when it is a local folder. Before, both failed in the media step or the load, half an hour in.

## Test

`tests/unit/test_rehearse_preflight.py`: before, the module did not exist (6 errors); after, 6 passed.
