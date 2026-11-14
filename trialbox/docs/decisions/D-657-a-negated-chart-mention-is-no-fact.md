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
`tests/unit/test_chart_fact_negation.py`, 19 of 29 cases wrong.

## Decision

`sitesetup.charts.normalise` drops a condition fact whose own term is negated in its own clause of the quote:

- a negation after the term ("なし", "無し", "認めず", "否定", "陰性", "(-)", "の既往なし", "ruled out") or right before
  it ("no", "no history of", "denies", "negative for", "without", "否認", "未見", "沒有", "無");
- a clause boundary (。、,;, a new line, "but", "しかし") stops a negation, so "糖尿病なし、高血圧あり" keeps 高血圧
  and "breast cancer, no recurrence" keeps the cancer;
- a word that only looks negative is no cue unless it stands right before the term: "非小細胞肺癌" and
  "無症候性高尿酸血症" stay facts;
- the term must be negated at every mention; a term the quote does not hold (the model's own wording) is judged on
  the whole quote, and only a quote that is one negated clause is dropped.

It works with the prompt PRODUCTION serves today (no schema or prompt change).

## Not changed

Fields for negation, subject (the patient or a relative) and certainty in the `chart_facts` schema and prompt, as
the review proposes, change what the qualified prompt must return: a new prompt version that PRODUCTION serves only
once it is qualified on the model pair (D-359), which needs a GPU run (the owner's yes). Family history and a
suspected diagnosis are cards of their own (SCR-04's other two parts).

## Test

`tests/unit/test_chart_fact_negation.py`: 18 negated quotes (Japanese, English, Chinese) give no fact; 10 quotes of
the patient's own diagnosis next to a negated neighbour or a negative-looking word stay proposed facts; a term the
quote does not hold is judged on the whole quote.
