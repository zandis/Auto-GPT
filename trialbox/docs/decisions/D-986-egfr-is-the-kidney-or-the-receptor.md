# D-986 "egfr" is the kidney's eGFR or the growth factor receptor; the line decides which

- **Task:** a side finding of D-983 (#639, 2026-11-16), which the integrator ruled one disambiguation card together with D-956's.
  - `orchestrator.scenarios.terms` mapped every "egfr" to the epidermal growth factor receptor ("EGFR", 表皮生長因子受體).
  - So a kidney line ("eGFR < 30 mL/min") retrieved notes about the receptor in S2 and in the note query, and never 腎絲球過濾率.
  - D-956 found the same name confusion in extraction: the model copied the derived score `egfr` onto an FEV1/FVC ratio. Its own check ("the line names the score") matched "EGFR mutation" as eGFR because it ignores case. #875 carries that half: there, capitals "EGFR" do not name the kidney's score.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`terms.egfr_sense(word, text)`):
  - The line decides first. A kidney word (mL/min, creatinine, renal, kidney, CKD, glomerular, dialysis, 腎, クレアチニン) or a comparison with a number ("EGFR < 30") makes it the kidney's. An oncology word (mutation, exon, TKI, tyrosine kinase, growth factor, NSCLC, lung cancer, L858R, T790M, del19, amplification, 變異/変異/突變, 受體/受容体, 肺癌) makes it the receptor's.
  - When both or neither appear, the spelling decides: capitals "EGFR" is the receptor, anything else ("eGFR", "egfr") the kidney.
  - "ACE inhibitor" and "angiotensin receptor blocker" are not oncology words: they sit beside the kidney's eGFR.
  - A kidney line's keywords are eGFR, 腎絲球過濾率, 腎小球濾過率, 糸球体濾過量; a receptor line's stay EGFR, 表皮生長因子受體.
- **Test:** `tests/unit/test_egfr_sense.py`.
- **Not in this card:** the site lexicon (`extra`), which a site writes itself.
