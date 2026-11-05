# hospital_sim: the TrialBox pipeline at hospital scale

`tools/hospital_sim.py`. `scale` runs the real in-process path (`tools/cascade_e2e.py`) on generated hospitals of
growing size and records time, funnel, model calls and invariant checks (`results/scale.json`). `project` combines
that funnel with the TREC error rates and the AUDIT.md share into a yearly projection with 95 % ranges
(`results/project_<patients>.json`). Synthetic patients only.
