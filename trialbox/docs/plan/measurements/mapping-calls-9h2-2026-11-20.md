# Mapping calls and unmapped criteria, counted offline, 2026-11-20 (card 9h-2, D-1350)

**Reader:** the integrator, lane A2 (the compiler and its mapper) and lane E (terminology)

Card 9h-2 of plan 9 revision 2 (`docs/plan/46-plan-9-rev-2-2026-11-17.md`, band 9h; root review 06, T6-2) asks for
`tools.terminology_coverage --model-calls` and a mode that compiles again on stored outputs with no model. Lane H took
over draft #1244 after its second review (head `6ce361cf`) and started again from master: the draft's replay copied the
compiler's alignment into the tool, and most of the review's findings were differences from the compiler. This record
gives the method, the inputs and the figures. Nothing here is a product default.

## 1. Method

`tools/terminology_replay.py`, run through `tools.terminology_coverage`. No model, no GPU, no network: the input is
read as JSON. Its tests fail on any socket connect (`tests/unit/test_h9h2_mapping_calls_offline.py`).

- **Each record is kept to its study** (`tb.study_id`, D-1350). A record with a missing or empty study id is counted
  in `no_study_id` and answers nothing.
- **`recorded`**: every stored `concept_map` record lands in one study bucket (or `no_study_id`) and in one outcome:
  `mapped` (a reply the model client accepts, with a code), `unmapped` (accepted, no code), `invalid` (no output, or
  one the client refuses). The buckets sum to the total and the total is the record count, or the tool refuses.
- **`simulated`** (`--model-calls`): each concept the study's accepted `ir_extract` replies drafted (demographic
  ones left out) is mapped by today's `Terminology.map`. A stand-in for the model counts each call by domain. It
  answers a call only with a recorded reply of the same study to the same call (concept, domain, candidate codes).
  Otherwise the call is `not_recorded`.
- **`replay`** (`--replay`): each study compiled again through `tools.public_accuracy.rerun.recompile` (the compiler's
  own `Compiler.compile`), with a model that answers from that study's accepted replies only. Its criteria flagged
  `concept_unmapped` are counted. A study with a call not recorded, or not compiled, counts as unknown (`null`), and
  so does the total. With `--answers`, the run's own stored count is given beside it.

## 2. Inputs

The only recorded public data in the tree with `concept_map` calls is launch P1b's replay slice (card H-4, D-1111):

| File | sha256 |
| --- | --- |
| `tests/fixtures/public_accuracy_p1b/replay_slice.json` | `e009e2db968cdab1fa8b33759a21029f44526d3663b0cb127aad80f060b193bb` |

It holds seven sigir protocols (SIGIR 2016 and ClinicalTrials.gov text) and two jmed protocols (JMED-Personas,
synthetic). The attributions are in the fixture folder's README. The commands, on this branch:

```
python -m tools.terminology_coverage tests/fixtures/public_accuracy_p1b/replay_slice.json --set sigir --model-calls
python -m tools.terminology_coverage tests/fixtures/public_accuracy_p1b/replay_slice.json --set sigir --replay \
    --answers tests/fixtures/public_accuracy_p1b/replay_slice.json
```

The same two commands were run with `--set jmed`. All four outputs are in `mapping-calls-9h2-2026-11-20/report.json`.

## 3. Figures (shown)

**Recorded `concept_map` calls.**

| Set | Records | Calls counted | Mapped | Unmapped | Invalid | No study id | By domain |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sigir | 21 | 21 | 0 | 21 | 0 | 0 | condition 17, observation 3, procedure 1 |
| jmed | 2 | 2 | 1 | 1 | 0 | 0 | condition 1, observation 1 |

**Calls today's mapper makes on the drafted concepts.**

| Set | Extraction records | Refused | Concepts drafted | Resolved | Model calls | Not recorded |
| --- | --- | --- | --- | --- | --- | --- |
| sigir | 6 | 1 | 27 | 10 | 7 (observation 5, condition 2) | 7 |
| jmed | 2 | 0 | 2 | 1 | 0 | 0 |

The refused sigir record is SM2NCT02378311's: the run stored no output for it (its FEAS failed in `ir_extract`).
Today's mapper asks the model 7 times on sigir's drafted concepts, against the 21 calls the run made. None of the 7 has
a recorded reply to the same candidate list: the candidates changed since P1b.

**Criteria flagged `concept_unmapped`.**

| Set | Ruleset | Compiled again | Criteria | Today | Stored by the run |
| --- | --- | --- | --- | --- | --- |
| sigir | SM2NCT00277680 | yes | 10 | 3 | 4 |
| sigir | SM2NCT00493103 | yes | 2 | 2 | 0 (FEAS failed in the run: no draft) |
| sigir | SM2NCT00606840 | yes | 10 | 1 | 1 |
| sigir | SM2NCT01260883 | yes | 8 | 2 | 4 |
| sigir | SM2NCT01723137 | yes | 6 | 0 | 0 |
| sigir | SM2NCT02378311 | no (no `ir_extract` reply stored) | 0 | unknown | 0 |
| jmed | MM2JMED-DM | yes | 2 | 1 | 1 |
| jmed | MM2JMED-HT | yes | 2 | 0 | 0 |

So jmed's total is 1 today and 1 stored. sigir's total today is unknown, because one study did not compile again. The
five that did compile give 8, and the run stored 9 for all seven. In the re-compile, every `concept_map` call found
its own study's recorded reply (`not_recorded` 0 in every study).

## 4. What this record does not show

- **The card's P2b proof is not run** (finding H9H2-02). The proof is 676 `concept_map` calls ± 10 % on P2b sigir and
  the 416 `concept_unmapped`. The archives are on the unmerged branch `integrator/p2b-artefacts`, and this card used
  only the tree. The command takes a P2b `work/raw-traces.json` and `work/answers.json` as they are.
- **The default replay of `rerun` still pools** (finding H9H2-01). `rerun.ReplayModel` answers `concept_map` from every
  study's replies, with a loose match. 9h-2 does not use it. The H-26 compile report does, and its re-compiled figures
  were not measured again here.
- How each review finding of #1244 is closed is in the pull request text and in the test names.
