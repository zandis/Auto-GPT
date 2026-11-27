# INT-S-C: an unknown verdict carries no confidence, no quote and no quote date

**Reader:** the people who build TrialBox: the integrator and the lane leads. Findings for builders, so in one
language.

- **Card:** INT-S-C (ring 0, card C of the sorting assessment)
- **Date:** 2026-11-25
- **Tests:** `tests/unit/test_unknown_carries_nothing.py`

## The fault

When the judge answers `unknown` it often fills placeholders: the quote "unknown", the quote date `0000-01-01` and
confidence 1.0. On master:

- `no_sentinel_date` (`libs/tb_common/llm.py`, `LlmClient._chat_json`; `services/matching/cascade/judge.py`,
  `GatewayJudge.judge`) turns the date into null, so the reply is a valid `unknown`. Nothing else is cleared.
- The note judge's `postprocess` (`services/orchestrator/scenarios/evaluate.py`) returned
  `NoteResult("unknown", 1.0, "<filler>", ...)`: it checks the quote of a decided answer only.
- `note_verdict` (v1 path: NAV, MICROBATCH, CASE) and `verdict_of` (`services/orchestrator/scenarios/screen_cascade.py`,
  cascade path) copied that confidence into the stored `Evidence`; `note_verdict` copied the filler quote too.
- `candidate_xlsx.render` printed `confidence 1.00` in the cell's comment of an unknown.

The confidence never reached a tier (`matching.decision.answer_of` reads an `unknown` before any confidence), so this
is what the investigator saw and what the answer store held, not a status.

## The change

- `tb_common.llm.unknown_carries_nothing(reply)`: a reply whose verdict is `unknown` gets null quote, quote date,
  certainty, experiencer and time, and confidence 0.0 (the schema's number field stays a number). Any other reply is
  returned as it is. It runs where a reply is accepted: after `no_sentinel_date` in `LlmClient._chat_json` and in
  `GatewayJudge.judge`, and at the top of `postprocess` (a reply that never passed through the client).
- `note_verdict` and `verdict_of` write no confidence for a verdict that is `unknown` (also one a decided answer was
  sent to review as), and `note_verdict` no quote or date for an abstention. A decided answer sent to review keeps its
  quote, as before.
- `candidate_xlsx.render` prints a confidence only for a verdict that is not `unknown`, so a row stored before this card
  reads the same.
- The prompt, the schema and the handling of `pass` and `fail` are unchanged.

## Not done

- Rows already stored keep their confidence in the answer store; only the workbook reads them without it.
- `tools/judge_eval.py` still maps an invalid reply to `unknown` without a count (card E of the assessment).
