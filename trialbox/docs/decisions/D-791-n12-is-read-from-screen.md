# D-791 N-12 is read from SCREEN

- **Task:** blocker 3 of lane G's first real-model accuracy run (the split agreed on #639, 2026-11-15)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-343 (N-12 gates on the unadjusted figure)

## Decision

The N-12 evidence `tools/qualify.py` reads comes from SCREEN, the product path, not from the benchmark prompt path
(`tools.trec_ct_eval`). `tools/n12_screen.py` reads the score files of lane G's product-path run
(`tools.public_accuracy`: SCREEN through the gateway on the TREC CT sets, scored by ids after the run) and writes
the evidence: `passed`/`ok`, `basis: "unadjusted"`, `source: "screen"`, `head`, the English TREC eligible pairs and
those the box excluded, the rate with a Wilson 95 % interval and the exact one-sided 95 % upper bound, the pairs
never answered, the sets and each input file's sha256. It passes when the rate is at most 5 % and the run answered at
least 90 % of the eligible pairs; a run that answered less is no evidence (`complete: false`).

The split: lane A2 writes the evidence (this tool); lane D points `qualify`'s `EVIDENCE_STEPS["n12"]` at it and
refuses evidence without `source: "screen"`; lane G runs SCREEN on the TREC sets (the owner's yes for the run).

## Not changed

The contract with lane G's score files: `set` names an English TREC set when it starts with `trec`, and
`pairs.rows` carries `lang`, `gold`, `n`, `excluded` and `unanswered` per cell, as `tools.public_accuracy.score`
writes them.

## Test

`tests/unit/test_n12_screen.py`.
