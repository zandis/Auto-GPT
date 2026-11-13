# D-644 The cascade's gateway judge sends no record id to a model

- **Task:** the finding recorded for lane A, "the PHI tripwire refuses harmless text: 5 of 85 judge calls on
  synthetic notes; about 0.6 % of random hex markers" (handover of 2026-11-12, section 5); lane B's dense scale run
  added 1 of 17
- **PR:** this branch (`agent/NEW-LLM-3-tripwire`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)

## What was measured first

On train 5, with the scale kit's dense synthetic hospital (`tools.synth` 300 patients, `tb_testkit.scale.densify`:
12,100 notes, 40.3 a patient), the guard with the settings' chart-number pattern. Shapes only.

| What the tripwire read | Refused |
| --- | --- |
| each dense note's text | 0 of 12,100 |
| judge prompts (judge v5; GZQO and RA-JAK note and mixed criteria) with excerpts of date, note type, text | 0 of 960 |
| the same prompts with each excerpt's document id (a keyed hash, 32 hex characters) | 100 of 960 (10.4 %) |
| a random hex token alone: 12, 16, 32, 64 characters | 0.57 %, 0.67 %, 1.9 %, 4.0 % |

Every hit was inside an id: twelve digits in a row (read as a My Number; `ID_NUMBER` when the check digit fails,
`JP_MY_NUMBER` when it happens to pass) or "0" and nine or ten digits (read as a phone number).

## Cause

`matching.cascade.judge.GatewayJudge.judge` passed the cascade's excerpts whole. Each carries `did`, the
document's id, so the id was rendered into the prompt. The scale gate, `tools/cascade_e2e` and the cloud runs use
`GatewayJudge`. The product's SCREEN asks through `NoteJudge`, which sends date, note type and text only: it never
sent the id and was not refused for it.

## Decision

`GatewayJudge` sends the same three fields (`judge.SHOWN`). A record id has no place in a model prompt, whatever a
tripwire thinks of it. The caller's excerpts are not changed: the quote check still reads the id from them. No
tripwire pattern is changed: the tripwire refused what it is there to refuse.

## What this does not do

- LLM-003's own case (a label word such as `病人`, `患者`, `受試者` followed by a character that is also a surname, in
  zh-TW and ja criteria) is not touched: this measurement did not meet it. It stays with NEW-LLM-3/4 and its
  tokeniser measurement (plan section 3.4).
- A digit run in the middle of a longer letter-and-digit token still counts as a phone or an ID number. Any other
  prompt that carries a hex id would be refused at the rates above; whether such a run should count is a recall
  question for NEW-LLM-3/4.

## Test

`tests/unit/test_gateway_judge_no_record_id.py`: the rendered prompt holds the three fields and no id; two ids the
tripwire refuses alone do not get the call refused; the caller's excerpts keep their id.
