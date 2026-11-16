# Launch P1b, sigir: the run's stored drafts and answers (not for master)

**Reader:** the people who build TrialBox

`sigir.tgz` is the accuracy set as the driver stored it for run `box-20261116T074927Z-3b2f5e38` on commit
`3b2f5e38` (lane G's driver with master train 44). It holds `built/gold`, `built/site-provenance` and `work/`
(`answers.json` with each protocol's FEAS state, error, draft criteria and per-patient verdicts; `screen/`,
`raw-traces.json`, `gateway-audit.json`, `services.log`, `box-calls.log`).

The data is the public SIGIR 2016 set (NCBI TrialGPT; see `eval/criterion_ml/LICENSE.NCBI`) and protocol text from
ClinicalTrials.gov. It holds no hospital data. This branch is a hand-over between sessions and is never merged;
fixtures made from it go into `tests/` in the usual small form.
