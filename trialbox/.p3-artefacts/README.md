# Launch P3: the run's stored sets, report and replay (not for master)

**Reader:** the people who build TrialBox

Run `box-20261117T153147Z-15108f46` on master `15108f46` (train 76, with the two fixes of launch P2b), 2026-11-17,
15:32 to 17:57 UTC: validation mode, sets `jmed:300`, `tcga:500`, `sigir` (3 streams), key v2, tag m4.
`replay.txt` and `replay.json` are `tools.public_accuracy.replay` on the run folder, from master `ee1961e5`.

Level (a), the verdicts as stored: wrongly excluded 3 of 407 (jmed 0 of 330, tcga 0 of 50, sigir 3 of 27); all three
are in the label-conflict class of D-1067 item 8 (`sigir-201422` on two age lines, `sigir-20154` on INC-06), so 0
without that class. Pathology: excluded 378 of 450, 0 wrong, lost 0 of 50. Protocols failing: 0 of 69. The sigir
set did not finish inside its 7,200 s: 38 of 104 protocols were not run for the time budget.

Public data only (SIGIR 2016, NCBI TrialGPT; JMED-Personas, CC BY 4.0; TCGA-Reports, CC BY 4.0). Never merged.
