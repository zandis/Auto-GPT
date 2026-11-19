# Launch P2b's stored verdicts, cells only (card 10A-3)

`ladder_cells.json` is taken from launch P2b's stored sets (run `box-20261117T073759Z-57263236`, the hand-over
branch `integrator/p2b-artefacts` at `2bcf5ca9`, `sigir.tgz`, `jmed.tgz`, `tcga.tgz`): for each protocol, the
compiled criteria (id and text) and, for its patients, the tier and one letter per criterion for the stored verdict
and basis (`codes` names them; `-` is a criterion with no verdict), counted per distinct row. It keeps no patient
id, no chart number, no note, no quote and no gold label. Used by `tests/unit/test_ladder_report_2026_11_18.py`,
which runs the ladder report on it and checks it against root review 15's rung table (section 2.2).

The sigir data is public: SIGIR 2016 (NCBI TrialGPT, `eval/criterion_ml/LICENSE.NCBI`), with protocol text from
ClinicalTrials.gov. The jmed protocols are the set's own two (JMED-Personas-100k by Sociocom (NAIST),
`huggingface.co/datasets/sociocom/JMED-Personas`, licensed CC BY 4.0). The tcga set is TCGA-Reports (Columbia),
Mendeley DOI 10.17632/hyg5xkznpx.1, licensed CC BY 4.0. Keep these attributions with any copy.
