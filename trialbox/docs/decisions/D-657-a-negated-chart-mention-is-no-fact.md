# D-657 A negated chart mention is never the patient's proposed diagnosis

- **Task:** SCR-04, negation (lane G's deep review of 2026-11-13, High), routed by the owner through the integrator
- **PR:** this branch (`agent/SCR-04-chart-fact-negation`), built on #501's head (`ac2bdebb`), which changes the
  same file
- **Date:** 2026-11-14
- **Status:** proposed (merges on a green train)
- **Builds on:** D-135 (a chart fact is only proposed until a coordinator confirms it), D-142 (a suspected diagnosis
  is not a confirmed one), D-359 (PRODUCTION serves the newest qualified prompt version)

## Context

The chart reader (`chart_facts`) proposes facts, each with the verbatim quote it came from. A quote such as
"悪性腫瘍なし" ("no malignancy") came back as an ordinary proposed condition (C80.1); one Confirm tap then excluded
the patient. Production relied on the prompt alone: the only deterministic negation list was in the stub, and the
`chart_facts` schema has no field for negation. Confirmed by running before the change:
`tests/unit/test_chart_fact_negation.py`, 19 of 29 cases wrong. The adversarial review broke the first version
in both directions (a whole-quote fallback dropped real diagnoses; cues not anchored to the clause end; missing
forms); the test now holds 40 negated and 21 kept cases.

## Decision

`sitesetup.charts.normalise` drops a condition fact whose own term is negated in its own clause of the quote:

- a negation after the term that ends its clause: "なし", "無し", "無い", "無", "ない", "なかった", "ありません",
  "ではない", "認めず", "認めない", "認められない", "否定的", "陰性", "(-)", "（なし）", "は特になし", "の既往なし",
  "ruled out", "absent", "negative", "- no";
- or a negation right before the term, or before a list joined by "or" / "nor" / 及 / 或: "no", "no known", "no
  history of", "not", "never had", "denies", "negative for", "without", "free of", "否認", "未見", "沒有", "無";
- a clause boundary (。、,;, a sentence's full stop, a new line, "but", "しかし") stops a negation, so
  "糖尿病なし、高血圧あり" keeps 高血圧 and "breast cancer, no recurrence" keeps the cancer;
- a cue that does not end its clause is no negation: "高血圧なし→あり", "痛風(-)→(+)", "痛風否定できず",
  "C型肝炎 陰性化", "高血圧ないし糖尿病", "糖尿病がないとは言えない" keep the fact; so does a word that only looks
  negative ("非小細胞肺癌", "無症候性高尿酸血症") and "no chest pain and gout" ("and" does not carry the negation);
- the term must be negated at every mention. A term the quote does not hold (the model's own wording or language)
  binds no negation: the fact stays proposed and a person reads the quote.

Known limit: a term the model shortened so that 無 stands right before it ("症候性" inside "無症候性脳梗塞") is read
as negated. "rule out" and "r/o" are a suspected diagnosis, SCR-04's third part, not a negation.

It works with the prompt PRODUCTION serves today (no schema or prompt change).

## Not changed

Fields for negation, subject (the patient or a relative) and certainty in the `chart_facts` schema and prompt, as
the review proposes, change what the qualified prompt must return: a new prompt version that PRODUCTION serves only
once it is qualified on the model pair (D-359), which needs a GPU run (the owner's yes). Family history and a
suspected diagnosis are cards of their own (SCR-04's other two parts).

## Test

`tests/unit/test_chart_fact_negation.py`: 40 negated quotes (Japanese, English, Chinese) give no fact; 21 quotes of
the patient's own diagnosis (a negated neighbour, a negative-looking word, a cue that does not end its clause)
stay proposed facts; 5 quotes that do not hold the term keep the fact for a person.
