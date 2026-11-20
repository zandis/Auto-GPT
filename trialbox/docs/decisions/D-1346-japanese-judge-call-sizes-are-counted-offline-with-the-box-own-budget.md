# D-1346 Japanese judge-call sizes are counted offline with the box's own excerpt budget

- **Task:** lane H, plan 10 row 10E-38 (review 19, card 19-19, run O-6, acceptance A6). The integrator's ruling of
  2026-11-19 sent the card to lane H after draft pull request #1222 did not pass its review. The lane H lead's
  rulings bind it: no GPU, no paid or cloud call; the judge's own tokenizer, offline, or else an estimate said to be
  one; synthetic Japanese charts only; a tier value is read only when measured (D-1322).
- **Date:** 2026-11-20
- **Status:** proposed
- **Builds on:** D-479 (one excerpt builder), D-276 (a cut window is not final), D-645 (one token estimate),
  D-905 (copies of a note), D-1322

## Context

Review 19 found that no Japanese judge call had ever been sized: the call sizes every review used were English. It
asked for run O-6: the synthetic Japanese hospital through SCREEN at the site box's 8k context and at the head box's
32k, and the share of calls the 8k context cuts. A6 accepts at most two points above the 32k control.

#1222 built that run as a capture on a live box (gateway, ballast container, GPU). Its review found three High and
six Medium findings, all in that capture. This workspace has no GPU and no Docker daemon, so its record held zero
judge calls.

Whether a call is cut does not need a model. The cascade sizes each prompt before it is sent: the excerpt budget is
the models' context, less a safety share, the fixed prompt and the answer (`tb_llm.budget.text_budget`). The one
excerpt builder (`matching.excerpts.build`) shows whole notes while they fit and counts each note it skips or clips
as `left_out`. Both use the box's token estimate, never a tokenizer.

## Decision

1. O-6 is counted offline by `tools/ja_call_sizes.py`. It generates the synthetic Japanese hospital
   (`tools.synth_hospital`, `JP=ja:1.0`, from a seed), ingests each site through `tools.ingest_local`, and runs
   SCREEN's cascade over every shipped ruleset once for each arm. Only the judge is a stand-in. It sizes the excerpts
   through `NoteJudge.excerpt_budget` and `LlmClient.text_budget`, given the context of the arm's registered judge and
   verifier builds (`models/registry.yaml`). It records each call and answers "unknown".
2. A call is cut when the cascade marks its criterion in `notes_over_budget` (`left_out` above 0). The share is the
   box's own code on these charts at these contexts. The judge's tokenizer plays no part in it.
3. The call sizes in the record are the box's estimate. The judge's tokenizer is not in the repository and not
   installed, and no other tokenizer is used in its place. The record carries `tokenizer.true_count: false` and the
   ratio of the judge's count to the estimate on the repository's measured Japanese excerpts
   (`tests/fixtures/llm/token_counts_cjk.json`: 0.53 to 0.91 on 200 excerpts).
4. A6 is computed unrounded from the two shares. It is reported, not tuned toward. It is not judged when an arm made
   no judge call, or when the arms asked different questions.
5. The record is filed as a measurement of card 10E-38 (`docs/handover/ja-call-sizes-2026-11-20/record.json`). It is
   no tier value.

## Consequences

- On 5,000 synthetic patients (8,781 notes, all Japanese), 352 judge calls were made in each arm. None was cut at 8k
  or at 32k, so A6 passes at +0 points. The largest call was 2,855 estimated tokens, 35 % of 8,192.
- That says the box's 8k budget holds these synthetic charts. It does not say that real Japanese charts fit. The
  synthetic notes are short, and six of the eight rulesets asked the judge nothing on them (findings H10E38-01 and
  H10E38-02).
- The true token count of a Japanese judge call is still open (H10E38-03). It needs the judge's tokenizer, on the
  integrator's GPU session or with the tokenizer file added to the repository.
- #1222's capture code is not carried. Its findings are answered in the card's page.
