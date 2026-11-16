# D-964 the traceability table is made from the tests and the run's results

- **Task:** NEW-STD-3, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/NEW-STD-3-traceability-from-the-tests`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

STD-003: the old matrix had 273 rows, all "planned", from a superseded plan.

1. A test declares what it proves with the existing `@pytest.mark.req`. `tests/conftest.py` puts the ids in its report
   and, with `TB_TRACE_OUT=FILE` (`make test TRACE=FILE`), writes one JSON line per such test: node id, result, ids
   (under xdist the controller writes once).
2. `tools/traceability.py` maps the ids through TB-DS-01 Appendix D (Design and Retired rows included) and writes
   `traceability.md` (per requirement: tests, passed, failed, skipped, verdict; then unmapped ids and mapped ids no
   test cites), `traceability.csv` and `summary.md`.
3. The unit shards write a trace; the `unit` job renders the table as the `traceability` artifact and its summary.
4. A report, never a gate (D-311): the step continues on error and the tool exits 0 with a failing requirement (2 only
   on unreadable input). JSON lines, not JUnit XML: the security scan flags `xml.etree` (B314) and no waiver is
   added.

## Test

`tests/unit/test_traceability.py`: Appendix D parsing; the table and verdicts with exit 0; exit 2 on bad input; the
shipped SRS parses; a real nested run records marked tests with their results; the CI wiring is non-gating. A sample
run: 202 traced tests, 25 requirements, 22 passing, 3 skipped only, 0 unmapped.
