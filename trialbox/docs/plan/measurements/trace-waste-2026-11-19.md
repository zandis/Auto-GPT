# Wasted model calls in launch P2b and P3, counted from the stored traces, 2026-11-19 (card H-40)

**Reader:** the integrator, and the lanes that own the judge, the verifier and the compiler's extraction

The question: do the box's two models waste calls the way small models do in thinking mode (an answer that runs to
the token limit, an answer that repeats itself, an answer outside the schema), so that a weight edit of the kind in
"Sparks of Weight-Space Programming" would have something to fix?

**The answer (shown, on these records).** The judge model (`j-workhorse`) wasted no answered call in either launch:
0 of 2,443 answered calls were cut, looped or fell outside their schema; its only waste is 10 `ir_extract` calls
that timed out with no text. The verifier (`v-verifier`) wasted 5 of 521 answered calls on P2b and 4 of 101 on P3,
all on tcga, all one pattern: after a JSON string closes it repeats a carriage return and two spaces until the
answer stops, so the JSON never closes; the 4 on P3 are 4 of P2b's 5, given the same input. That is too few, in too narrow
a pattern, for a weight edit to have much to fix; what wastes time is the timeouts and a whitespace loop of one model.

## The records and the command

Launch P2b is run `box-20261117T073759Z-57263236` (branch `integrator/p2b-artefacts`, folder
`trialbox/.p2b-artefacts/`, branch head `2bcf5ca9`); launch P3 is run `box-20261117T153147Z-15108f46`
(`integrator/p3-artefacts`, `trialbox/.p3-artefacts/`, head `7b2d96a8`). Each set's `.tgz` holds
`work/raw-traces.json`: one record per model call the gateway answered (`span` `chat`) or refused (`span`
`refusal`). Neither branch is merged, nothing from them is copied here beyond the figures quoted, and the data is
public: SIGIR 2016 (NCBI TrialGPT), JMED-Personas (CC BY 4.0), TCGA-Reports (CC BY 4.0).

Every figure on this page comes from one command per launch, run from `trialbox/` with no model, GPU or network
(`P2B` and `P3` are the two artefact folders, read with `git archive` into a scratch folder outside the repository):

```
python -m tools.public_accuracy.waste P2B/jmed.tgz P2B/sigir.tgz P2B/tcga.tgz --json waste-p2b.json
python -m tools.public_accuracy.waste P3/jmed.tgz P3/sigir.tgz P3/tcga.tgz --json waste-p3.json
```

`tools.public_accuracy.waste` is new (this card; its test is `tests/unit/test_h40_waste_count_2026_11_19.py`). It
prints the table below per set; the JSON has the same counts per model and per model and prompt.

## What the traces do not record

- **The finish reason.** No trace says whether the model stopped at `max_tokens`, at its end token or at a stop
  string. "Cut" below is a rule on the text, not the server's word.
- **Tokens.** The gateway's ledger keeps each call's tokens; the stored sets do not hold the ledger. Tokens here are
  `tb_llm.budget.estimate_tokens` of the text, which over-estimates (D-645).
- **Each call's time.** A trace keeps one timestamp, when it was written after the answer. No start time, no
  latency. The share of model time is therefore given by a proxy (below), and the timeouts by the gateway's setting.
- **What a timed-out call would have said.** A refusal keeps no text.

## The rules

- **Cut (ended at the token limit):** the text is not JSON and the JSON parser ran off its end (the error is at or
  past the last non-blank character, or a string never closes). The looser bound, **at cap**, is an estimated token
  count of at least 90 % of the prompt's `max_tokens` (`judge@5` and `concept_map@2`: 1,024; `ir_extract@4`: 8,192).
- **Loop (the output repeats):** some block of 1 to 256 characters follows itself back to back so that the repeated
  stretch covers at least 64 characters and holds at least 4 copies. A JSON list of different criteria repeats its
  keys, never one block back to back, so it is not a loop.
- **Outside the schema:** the text is not JSON, or it fails the prompt's registered output schema (`jsonschema`, null
  read as absent, as the gateway's `_schema_ok` checks it). Every prompt in these traces has a registered schema
  (`schema_unknown` 0 in both JSON files).
- **Timeout:** a refused call whose upstream kinds hold `timeout`; it returned no text.
- **Repair:** a call whose messages hold an earlier assistant answer: the caller asked again.
- **Flagged:** cut, loop or outside the schema. **Token share:** the flagged calls' estimated output tokens over the
  model's, in that set; the proxy for the share of model time, since decoding dominates a long answer.

## The counts

Calls are all traces of that model in that set (answered and refused). From `waste-p2b.json` and `waste-p3.json`,
`sets.<set>.by_model.<alias>`:

| Launch | Set | Model | Calls | Timeout | Cut | At cap | Loop | Outside schema | Repair | Flagged | Token share |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| P2b | jmed | judge | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 % |
| P2b | sigir | judge | 1,201 | 7 | 0 | 0 | 0 | 0 | 19 | 0 | 0.0 % |
| P2b | sigir | verifier | 44 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 % |
| P2b | tcga | judge | 502 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0.0 % |
| P2b | tcga | verifier | 477 | 0 | 5 | 2 | 5 | 5 | 0 | 5 | 5.5 % |
| P3 | jmed | judge | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 % |
| P3 | sigir | judge | 727 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 % |
| P3 | sigir | verifier | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 % |
| P3 | tcga | judge | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 % |
| P3 | tcga | verifier | 67 | 0 | 4 | 2 | 4 | 4 | 0 | 4 | 28.7 % |

"Judge" is the alias `j-workhorse`; it answers `ir_extract@4`, `concept_map@2` and `judge@5`. "Verifier" is
`v-verifier`; it answers `judge@5` only. Every timeout is `ir_extract@4`; every repair is `judge@5`. Token totals
(estimated): P2b tcga verifier 3,044 of 55,302 flagged; P3 tcga verifier 2,724 of 9,489.

**Sensitivity of the loop rule.** The grid of (stretch, copies) = (16, 2), (32, 3), (64, 4), (128, 8), (256, 16) gives
the same counts in every row (`loop_<span>x<reps>` in the JSON): 5 and 4 for the tcga verifier, 0 everywhere else.
The verifier's loops are long (940 to 4,055 characters of one 3-character block) and the judge's answers hold no
back-to-back repeat even 16 characters long, so the count does not hang on the threshold.

## What the flagged calls are (shown)

- **One pattern.** All 9 flagged calls are the verifier on tcga's `judge@5`. In each, after the `quote` field (8
  calls) or the `reason` field (1 call), the model writes a carriage return and two spaces again and again, 313 to
  1,351 times, and the answer stops with the JSON open. (Corrected by H-49: the loop starts after that string value
  has closed, between JSON tokens, not inside the string; see `verifier-constrained-decoding-2026-11-19.md`.) Cut, loop and outside the schema are the same
  calls in every row.
- **The same input, the same loop.** P3's 4 are 4 of P2b's 5 (the same text, character for character, from the
  same prompt at temperature 0). In each launch two of them are a second call on the same question whose answer ran
  to about 4,200 characters against about 1,200 for the first: the caller asked again with more room
  (`tb_llm.budget.retry_max_tokens`), and the model filled the room with the same loop.
- **At cap is 2 of the 5.** The two longer answers reach the 90 % bound by the estimate; the shorter three stop at
  about 300 estimated tokens. Whether those three stopped at the server's token limit (whitespace may tokenize to
  fewer tokens than the estimate says) is not in the records.
- **The judge's repairs are not schema failures.** The 19 repairs on P2b sigir and the 1 on P2b tcga follow an
  answer that is inside the schema (0 outside the schema for the judge): the caller asked again for another reason
  of its own. P3 has none.

## The timeouts

10 `ir_extract@4` calls, all on sigir (7 on P2b, 3 on P3), timed out with no text. The compiler then asked again in 2
or 3 smaller parts (`work/services.log`: "the gateway gave up on the answer; asking it again in 3 parts", once per
timeout logged on P3). Their time is not recorded; by the gateway's code each one waited at least its read timeout,
`TB_GATEWAY_UPSTREAM_READ_S`, 180 s by default (`tb_llm.timeouts.UPSTREAM_READ_S`), and at most the call budget,
210 s (`CALL_BUDGET_S`). The run's value of that setting is not in the stored sets. On P3 that is 540 s to 630 s of
one stream's time in a set that ran 6,851 s on three streams; the answers that followed in parts were all JSON in
the schema. Whether the timed-out answer was looping toward its 8,192-token cap or only long is not recorded: a
**hypothesis**, not a finding.

## So

- **For the judge model, no.** On these two launches it ran to no cap, repeated nothing and left no schema. The weight
  edit would have nothing here to fix on its answered calls.
- **For the verifier, one narrow pattern.** 9 calls, one input class (tcga pathology reports, `judge@5`), one
  whitespace loop inside a JSON string. A grammar that forbids a raw carriage return inside a JSON string (or the
  schema-constrained decoding the serving stack offers) addresses it without touching weights; that is the serving
  lane's choice, not this card's.
- **The timeouts are the larger waste in time**, and the records cannot say what the model was doing in them. A
  launch that kept the ledger's tokens and latency per call (or the finish reason in the trace) would answer it.

## Not shown

- The finish reason, the tokens and the time of any call (not recorded; see above).
- What the 10 timed-out calls would have returned.
- Any launch other than P2b and P3.

## Findings

The page's three findings (H40-01 to H40-03) are in `trace-waste-2026-11-19/findings.json`, in the form
`python -m tools.findings_register --add-from` reads. They are not rows of the register; lane V adds them.
