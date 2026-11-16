# D-658 A relative's diagnosis in a chart is never the patient's proposed diagnosis

- **Task:** SCR-04, family history (lane G's deep review of 2026-11-13, High), routed by the owner through the
  integrator
- **PR:** this branch (`agent/SCR-04-chart-fact-family-history`), stacked on the negation card (D-657,
  `agent/SCR-04-chart-fact-negation`, with its review fixes), itself built on #501's head
- **Date:** 2026-11-14
- **Status:** proposed (merges on a green train)
- **Builds on:** D-135 (a chart fact is only proposed until a coordinator confirms it), D-657 (the negation guard and
  its clause rule), D-359 (PRODUCTION serves the newest qualified prompt version)

## Context

A chart quote such as "家族歴：母 乳癌" (family history: mother, breast cancer) came back from the chart reader as
the patient's own proposed C50.9; one Confirm tap then excluded the patient. Production relied on the prompt; the
schema has no field for whose diagnosis it is. A quote-level word check alone is too crude: "乳癌（2019年）、母：
糖尿病" holds 母 and the patient's own cancer. Confirmed by running before the change:
`tests/unit/test_chart_fact_family_history.py`, 14 of 22 cases wrong. The adversarial review broke the first version
in both directions (a relative anywhere in the clause dropped the patient's own diagnosis; a heading outlived an
empty section or a new heading; missing relative words); the test now holds 37 relatives' and 30 own cases.

## Decision

`sitesetup.charts.normalise` drops a condition fact only where it is plainly a relative's at every mention; anything
less stays proposed and a person reads the quote (a dropped fact is invisible, a kept one is reviewed):

- a relative right before the term, with only separators, 罹患 / 患 / 患有, or "had" / "has" / "with" / "w/" between
  ("母：糖尿病", "父が大腸癌", "祖母の高血圧", "姐姐乳癌", "母亲患乳癌", "Mother had breast cancer", "Uncle w/ MI",
  "Sister (deceased) – breast cancer"), unless the clause also names the patient ("Patient and his father have
  gout"); or "<term> in father" right after it;
- or a family history heading (家族歴, 家族史, family history, family hx, fam hx, FHx, "Family:") in the term's own
  clause, or in the clause before when that clause ends with a relative ("Family history: mother, breast cancer");
- an empty heading ("家族歴：なし", "特記事項なし", "无", "none", "noncontributory", "negative"), another heading
  ("既往歴：", "现病史：", "Dx:", "PMH"), or the patient as subject (本人, patient, personal, she, he) ends a heading's
  reach, as does any clause boundary;
- "FH:" is no heading (it is also familial hypercholesterolemia); 子 is no relative (子宮癌); a one-character
  relative needs a separator after it (母乳); a term in Latin letters matches a whole word only ("MI" is not in
  "Family"; this holds for the negation guard too);
- a term the quote does not hold binds no relative: the fact stays for a person.

Known limits, kept for a person: "痛風（父）", "母、痛風" without a heading, a relative named after the term other than
"in <relative>".

It works with the prompt PRODUCTION serves today (no schema or prompt change).

## Not changed

A `subject` field in the schema and prompt needs a qualified prompt (D-359; a GPU run, the owner's yes). A suspected
diagnosis ("肺癌の疑い") is SCR-04's third part, a card of its own.

## Test

`tests/unit/test_chart_fact_family_history.py`: 37 relatives' diagnoses (Japanese, Chinese, English) give no fact;
30 quotes of the patient's own diagnosis (beside a relative, after an empty or ended family heading, with the
patient as subject, a term the quote lacks) stay proposed facts.
