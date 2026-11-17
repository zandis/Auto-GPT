# Launch P2b: the run's stored sets, report and replay (not for master)

**Reader:** the people who build TrialBox

Run `box-20261117T073759Z-57263236` on master `57263236` (train 68), 2026-11-17, 07:38 to 10:02 UTC on the GPU box:
validation mode, steps dev and acc, sets `jmed:300`, `tcga:500` and `sigir` (3 streams), key v2, tag m3.

- `jmed.tgz`, `tcga.tgz`, `sigir.tgz`: each set as the driver stored it (`built/`, `work/`).
- `report.md`, `summary.json`, `acc-score.json`: the run's own report and scores.
- `replay.txt`, `replay.json`: `tools.public_accuracy.replay` on the run folder, from master `2f29b90b` plus train 71.

What the replay prints at level (a), the verdicts as the launch stored them:

1. Eligible patients wrongly excluded: 4 of 420 without the conflicted pairs, 5 of 424 with them; all in sigir (4 of 40).
   The target is none.
2. Pathology: excluded 379 of 450, 0 wrong, lost 0 of 50. The target is 384 of 450.
3. Protocols failing: 3 of 107 (2.8 %), all in screen judging; 0 before SCREEN. The target is fewer than one in ten.

Level (b) was not run: the run's record names no index day.

The data is public: SIGIR 2016 (NCBI TrialGPT; see `eval/criterion_ml/LICENSE.NCBI`) with protocol text from
ClinicalTrials.gov; JMED-Personas-100k by Sociocom (NAIST), CC BY 4.0; TCGA-Reports (Columbia), Mendeley DOI
10.17632/hyg5xkznpx.1, CC BY 4.0. Keep those attributions with any fixture made from it. It holds no hospital data.
This branch is a hand-over between sessions and is never merged.
