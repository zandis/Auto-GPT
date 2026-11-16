# D-961 every engine.py mutant runs, so the floor can be raised on a whole score

- **Task:** ENG-006, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/ENG-006-every-engine-mutant-runs`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

The first complete nightly (2026-11-15) scored 63.3 %, but engine.py's shard ran out of its 200 minutes with 114
mutants not run, which the score leaves out.

1. `tools/mutation.py --part K/N` runs every N-th mutant of the selected targets from the K-th, in a stable order. The
   parts' reports merge into exactly the whole run: no mutant twice; an accepted mutant of another part is not
   called stale, and one really gone is reported once (by part 1).
2. The nightly runs engine.py in two shards (`--part 1/2`, `--part 2/2`); `mutation-score` expects four reports.
3. The floor stays 60 until a whole night is measured; it is then raised to that night's score, not to 63.3.

## Test

`tests/unit/test_mutation_tool.py`: a real run on a small tree, with parts 1/2 and 2/2 merged equal to the whole run;
the stale list; `--part 3/2` refused. `tests/unit/test_nightly_quality_workflow.py` pins the two parts and the four
reports.
