# recall_cert

The simulation behind the recall certificate's anytime-validity claim (spec v4 §10.14, SAFE-16; App. F).

A stratum's true elusion rate is p. Each month 40 excluded patients are audited and the bound is re-issued, for 12
months. A ledger *misses* if its printed 95 % upper bound fell below p at any look. The suite runs every look
**through the recall ledger** (`services/orchestrator/recall/`): the month's draws are appended, the backend is closed,
and the next look resumes the `ConfidenceSequence` from its stored canonical-JSON state.

```bash
PYTHONPATH=libs:services:. python -m orchestrator.recall.sim --config eval/suites/recall_cert/config.yaml
```

| p | repeated Clopper–Pearson | confidence sequence | gate |
| --- | --- | --- | --- |
| 0.02 | 0.097 | 0.003 | CS ≤ 0.05 and CP > 0.05 |
| 0.005 | 0.000 | 0.000 | — |

The numbers equal the in-memory reference (`python -m tools.recall_sim`, seed 11), because a resumed sequence is the
uninterrupted one, byte for byte. Data: synthetic Bernoulli draws only. Runtime: a few minutes on 4 cores.

Not yet in this suite (SAFE-16, MS2): planted misses per stratum near the decision boundary, importance-weighted
draws, certificate-level coverage and ≥ 1,000 seeds nightly.
