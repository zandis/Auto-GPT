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
the evidence: `passed`/`ok`, `basis: "unadjusted"`, `source: "screen"`, `head`, the served models, the English
TREC CT 2021/22 eligible pairs and those the box excluded, the rate with the exact 95 % interval and one-sided upper
bound, the pairs never answered and those left to a person, and each input file's sha256. It passes when the rate is
at most 5 % (the point estimate, as D-343 reports it) and the run answered at least 90 % of the eligible pairs.

It is no evidence unless each score file carries a `run` block of a real run at this checkout's HEAD (`head`,
`models`, `stub: false`), names the TREC set (`trec`) once, holds whole counts that add up per row, and the files
reach 400 eligible pairs (at 5 %, an exact interval within about ±2.2 points; the 2026-11-08 baseline had 1,700).
TREC 2023 (today's ClinicalTrials.gov criteria) does not count without a decision of its own.

The split: lane A2 writes the evidence (this tool); lane D points `qualify`'s `EVIDENCE_STEPS["n12"]` at it and
refuses evidence without `source: "screen"`; lane G runs SCREEN on the TREC sets (the owner's yes for the run).

## Not changed

The contract with lane G's score files: `pairs.rows` carries `lang`, `gold`, `n` and the cells `excluded`, `listed`,
`open` and `unanswered`, as `tools.public_accuracy.score` writes them. The `run` block is new: lane G adds it to
`score.json` (asked on #639); until then no score file is evidence.

## Test

`tests/unit/test_n12_screen.py`.
