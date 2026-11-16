# D-918 The validation figures are defined on the product path

- **Task:** plan 37's "validation figures" row (each set's measured figure against its validation figure: N-12, TREC, MedTxt, with lane A2), and lane G's validation reset of 2026-11-14 (items for `docs/VALIDATION.md:70` and the 2026-11-08 results files). Lane A2's backlog, card 2 (#639, 2026-11-16). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **What a figure is.** Each validation figure is measured on the product path: the set is screened as a site by SCREEN, through the gateway, on the installed box, and scored by ids after the run.
    - "Excluded" means listed under criteria not matched, by a coded record or a note answer both models gave.
    - An unknown, a review or a candidate is "not excluded".
    - "Unanswered" means no answer at all.
  - **N-11** (SIGIR, 79 eligible pairs per language): eligible pairs excluded, at most 5 / 4 / 2 (EN / JA / zh-TW), as before.
  - **N-12** (TREC CT 2021/22, English): eligible pairs excluded ÷ eligible pairs, unadjusted (D-343), at most 5 %, with `tools.n12_screen`'s rules on evidence (D-826): at least 400 eligible pairs, at most 10 % unanswered.
  - **MedTxt (ja).** The gated figure is the false block: negative-tagged findings that excluded ÷ negative findings. Recall on positive findings, exclusion on suspicious findings and hallucinated blocks are reported, not gated. **The gate is the owner's decision**; none is set.
  - **Earlier figures.** The 2026-11-08 figures (N-11 4/2/1, N-12 9.4 %, the PRO 6000 canary and `public_e2e`, MedTxt) were measured on the benchmark prompt through a one-boot script. They stay as history and are marked so in `docs/VALIDATION.md` §3 and at the top of their results files. They are no gate result.
- **Test:** none: a documentation decision. `docs/VALIDATION.md` §3 is the reference the integrator's measurement pass reports against.
