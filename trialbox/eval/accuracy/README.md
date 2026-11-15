# The note accuracy set (NEW-LLM-6, D-784)

Synthetic notes in ja, zh-TW and en, generated from a seed by `tools/accuracy_set.py`; no patient data. The set is
not committed: `MANIFEST.json` pins it (seed, size, sha256, counts per language), and
`tests/unit/test_accuracy_set.py` checks that the generator still gives that set.

    python -m tools.accuracy_set generate cases.jsonl
    python -m tools.accuracy_set run cases.jsonl answers.json      # on the box: both models through the gateway
    python -m tools.accuracy_set score cases.jsonl answers.json --out report.json

A report placed here holds counts, rates and intervals only. See the module's text for the strata and the scoring.
