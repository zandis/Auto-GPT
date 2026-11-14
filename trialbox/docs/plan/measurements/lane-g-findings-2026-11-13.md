# Lane G findings of 2026-11-13, for the integrator

Synthetic data only. Three paid runs on one RTX PRO 6000 VM (spot), about US$7 in all:

| Run | Commit | What | Folder |
| --- | --- | --- | --- |
| `20261113T044219Z-2b9eec74` | 2b9eec74 (master d48c153c + lane G batch 1) | 5,000 patients, ja and zh-TW, 1 / 4 / 16 calls in flight, G-4, G-5, G-7 | `g3-2026-11-13/` |
| `20261113T072836Z-70087268` | 70087268 | G-7, G-4: failed at set-up after 11 minutes (finding B6) | none: no results |
| `20261113T081311Z-c25cea6b` | c25cea6b (master 96f955f0, trains 4 and 5 in) | G-7 and G-4 again | `g7-2026-11-13/` |

Later runs: the 50,000-patient run (section 2) and `20261113T231557Z-0e9be8a5` (0e9be8a5, D-645 in: G-5 and G-8;
0.8 VM hours, about US$2.19 at the spot price; folder `g5-g8-2026-11-14/`) and `20261114T014216Z-cb850470`
(cb850470, B13 fixed: G-8 only; VM up 01:42 to 01:54 UTC, about 0.2 VM hours, about US$0.55; folder `g8-2026-11-14/`).

## 1. Product findings

### P1. LLM-001 on real models: a clipped note excluded a patient (before D-479 and D-641); gone on master

- **Before** (run `20261113T044219Z`, without D-479 and D-641). Case `LLM-001-zh-TW-denied-list`: the note holds
  `病人否認下列病史：` and under it `肺結核。`. The clip kept `肺結核。` and dropped the line above. Judge and verifier
  both answered that the patient has it, the pair agreed, and the final outcome was "not met (final)". On the whole
  note both answered correctly. Case `LLM-001-ja-family-history`: `肺結核。` only under `【家族歴】`; the clip dropped
  the heading and both models answered "has it"; only a missing quote kept the outcome at "review".
- **After** (run `20261113T081311Z`, master 96f955f0). Both notes are clipped (3,958 and 3,965 characters whole,
  1,349 and 1,429 shown). The clip keeps `【家族歴】` and `病人否認下列病史：`, and each clipped note counts as left
  out. zh-TW: judge and verifier both answer that the patient does not have it, quoting the denial line; final
  "met", as on the whole note. ja: both abstain; final "review", as on the whole note. No final "not met" from a
  clipped note.
- **Limit of this evidence.** Two synthetic notes, one run each.
- Evidence: `g3-2026-11-13/parts/g7-clipped.json` and `g7-2026-11-13/parts/g7-clipped.json`, block `clipped.cases`.

### P2. The token estimate ran low for zh-TW (lane D: the budget's SAFETY); resolved on master with D-645

**Resolved.** On 0e9be8a5 (D-645: G-5 measures the product's current token estimate), run
`20261113T231557Z-0e9be8a5` gives a worst real / estimated ratio of 0.9143 for ja, 0.9355 for zh-TW and 0.9888 for
en (the budget's estimator). The worst, 0.9888, times the probe's 5 % margin is 1.038, which fits 1 / SAFETY =
1.176: SAFETY may stay 0.85. All 200 excerpts of each language were counted.

| Language | Estimator | n | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- |
| ja | budget | 200 | 0.7273 | 0.8000 | 0.9143 |
| ja | prompt | 200 | 0.9018 | 0.9622 | 0.9743 |
| zh-TW | budget | 200 | 0.8317 | 0.8972 | 0.9355 |
| zh-TW | prompt | 200 | 0.9392 | 0.9707 | 0.9792 |
| en | budget | 200 | 0.8429 | 0.9208 | 0.9888 |
| en | prompt | 200 | 0.9494 | 0.9716 | 0.9819 |

The cascade's estimator gives the same figures as the budget's in every row. Evidence:
`g5-g8-2026-11-14/g5-tokens.json`, block `tokens.per_language`, and `g5-g8-2026-11-14/report.md`.

**Before D-645** (run `20261113T044219Z`). Real tokens (the judge server's `/tokenize`) divided by the product's estimate, 200 synthetic excerpts per language.
SAFETY is 0.85, so the budget allows a ratio of 1 / 0.85 = 1.176; with the probe's 5 % margin the worst ratio fits
only if SAFETY is 0.7857 or lower.

| Language | Estimator | n | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- |
| ja | budget | 200 | 0.7477 | 0.8443 | 0.9412 |
| ja | cascade | 200 | 0.7530 | 0.8571 | 0.9697 |
| ja | prompt | 200 | 0.9398 | 1.0028 | 1.0188 |
| zh-TW | budget | 200 | 0.8577 | 0.9552 | 1.1111 |
| zh-TW | cascade | 200 | 0.9064 | 1.0159 | 1.2121 |
| zh-TW | prompt | 200 | 0.9806 | 1.0140 | 1.0320 |

English was not measured: G-5 covers ja and zh-TW only. Evidence: `g3-2026-11-13/parts/g5-tokens.json`, block
`tokens.per_language`.

### P3. Guided decoding on: 1 of 64 judge answers outside the judge schema, in both runs (lane D: serving)

The failing answer ended normally (`finish_reason` stop, 71 completion tokens) and holds other field names
(`verdict`, `reason`) than the judge schema's. It was not cut at the token limit: on that call the schema was not
enforced. The structured-output backend is `auto` (not named by a flag). Evidence:
`g7-2026-11-13/parts/g4-decoding.json`, `decoding.guided_on.schema_failure_examples`.

With guided decoding off, 64 of 64 answers fail the schema only because each is wrapped in a Markdown code fence; the
JSON inside is the judge schema. Guided decoding must stay on. At 16 in flight it gave 3.58 calls/s on and 4.73 off
(1.77 and 2.50 in the first run, which ran next to other parts' set-up).

### P4. The screening list changes between runs of the same hospital (lane A)

Six runs of the same 5,000 patients (ja and zh-TW at 1, 4, 16 in flight) list the same 55 patients, but one or two
patients change tier between runs, so the list's sha256 takes two values (`6e78c71cd0bf`, `72d3513176a1`). It does
not follow the calls in flight: the same value appears at 1 and at 16. Evidence:
`g3-2026-11-13/parts/hospital-*/screen-list.json`.

### P5. Stage 12 "site set-up and data harmonization": 22 of 23, in all six hospital parts (lanes A and E)

The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" fails as
in run `20261112T165042Z` (B1 there). Evidence: `g3-2026-11-13/failed-checks.json`.

### B14. A model answer whose logic names a concept it did not list fails the whole protocol (criteria-compiler lane)

A product defect found by G-8 (run `20261114T014216Z-cb850470`); lane G changes no product code. Suggested owner:
the criteria-compiler lane.

- **Input.** The `ir_extract` answer has a structured (or mixed) criterion whose logic atom names a concept, e.g.
  `{"domain": "observation", "concept": "CDR score", "value": {"op": ">=", "num": 0.5}}`, that is not among that
  answer's `concept_candidates`. The schema cannot forbid it (`ExtractedAtom.concept`: "name of a concept in
  concept_candidates" is a description, not a constraint), and the production judge did it on NCT03887455 (the CDR
  lines).
- **Wrong behaviour.** `services/criteria_compiler/ir_extract/postprocess.py:142` (`postprocess`) sees it and
  raises `CompileError("ValueSet VS_CDR_SCORE has no concept candidate")`, which `postprocess.py:150` turns into a
  warning and the `logic_invalid` flag, but the atom keeps the undefined value set and the criterion stays
  `structured`. `Compiler.compile` (`services/criteria_compiler/service.py:572`) then calls `demote_uncompilable`,
  which renders the criterion (`service.py:266`, `CqlGenerator.render`, `compile_cql/generator.py:294`
  `_obs_value` -> `ValueSets.is_component_set`) and reaches `ValueSets.codes`
  (`services/criteria_compiler/terminology/mapper.py:427`): `KeyError: 'ValueSet VS_CDR_SCORE not defined for
  ruleset G8P2'`. `demote_uncompilable` catches only `CompileError` (`service.py:268`), so the `KeyError` leaves
  `compile`; the app's `/compile` (`app.py:100`) catches only `CompileFailed`, so on a box the requester gets an
  HTTP 500 ("internal error") and no draft: every other criterion of the protocol is lost. The same code path runs
  in `approve` (`service.py:746` to `777`, `build_artifacts` catches only `CompileError` too, `service.py:295`).
- **Expected.** As for any other uncompilable structured criterion (stress test #24, D-98): the criterion goes to
  `human` with `needs_review` and `compile_error` (a `mixed` one to `note`), with a warning naming the concept, and
  the rest of the protocol compiles. For example `ValueSets.codes` / `url` raise `CompileError` for an unknown
  name, or `postprocess` sets the atom's value set to `NONE` / demotes the criterion when it raises "has no concept
  candidate".
- **Not a probe defect.** G-8 calls the product's own entry, `criteria_compiler.service.Compiler.compile`, with
  the parsed protocol, as the box's `/compile` does (`app.py:100`; the orchestrator's `trials.py:72` and
  `review.py:89` reach it through `CompilerHttp.compile`). No step of the box defines value sets before
  `codes()`: they come only from `postprocess` (one per concept candidate, mapped or not, plus derived ones).
  The box's terminology (`resolver.terminology`) and CQL translator differ from G-8's, but neither defines a value
  set for a concept the model did not list, and the crash comes before the translator.
- **Reproduction** (no model, no GPU). G-8's `compile_protocol` with a stub client whose `ir_extract` answer is the
  atom above and, for one line, no concept candidates: `KeyError: 'ValueSet VS_CDR_SCORE not defined for ruleset
  SYNP1'`, raised at `service.py:572` -> `service.py:266` -> `generator.py:294` -> `mapper.py:452` ->
  `mapper.py:427`, the run's stack. With the candidate listed the same protocol compiles (the criterion flagged
  `concept_unmapped`, `needs_review`).
- **G-8 itself.** The failed protocol is a failed row (its error) and the other protocol is still measured; a test
  pins that (`test_g8_records_a_protocol_that_does_not_compile_and_measures_the_other`). The run kept no raw model
  answer, so which CDR line named the concept is not recorded.

## 2. Throughput (G-3), main SCREEN only

| Calls in flight | ja calls/s | zh-TW calls/s |
| --- | --- | --- |
| 1 | 0.385 | 0.388 |
| 4 | 1.435 | 1.432 |
| 16 | 4.391 | 4.613 |

The main SCREEN of 5,000 patients makes about 245 calls, so the window at 16 in flight is under one minute. The
figures above are from run `20261113T044219Z`. One run per setting: no repeats, no restart of the servers between
settings.

### The 50,000-patient run (`20261113T085509Z-c25cea6b`, 16 in flight)

Results: `g3-50k-2026-11-13/`. 2.0 VM hours, about US$5.48 at the spot price.

| | ja | zh-TW |
| --- | --- | --- |
| Whole part, seconds | 2,986 | 2,991 |
| Main SCREEN calls | 3,226 | 3,217 |
| Main SCREEN calls/s | 4.447 | 4.558 |
| Main SCREEN p50 / p95, seconds | 3.2 / 5.1 | 3.2 / 5.0 |
| Mean calls in flight | 15.79 | 15.73 |
| Model calls in the part, refused | 6,568, 0 | 6,550, 0 |
| Candidates listed | 627 | 628 |
| Canary: pair correct of 54, decided wrong | 53, 0 | 53, 0 |
| Checks passed | 227/228 | 227/228 |

- The rate at 16 in flight holds over a 12-minute window: 4.4 to 4.6 calls/s, as at 5,000 patients.
- Of the ja part's 2,986 s, the main SCREEN's model calls take 725 s (about a quarter); the part's other model
  calls take 969 s; the rest, 1,292 s, is loading, coded screening and the other stages with no model call. All
  model calls together are about 57 % of the part (zh-TW: 706 + 959 of 2,991 s). A night window must count the
  whole part, not the main SCREEN alone (deep review OPS13-13).
- The failed check in each part is P5 (stage 12). G-7 passed. G-4 and G-5 failed as in P2 and P3; this commit is
  before D-645.
- The estimate before this run was 3.14 h for each hospital part; the part took 0.83 h. The estimator now reads
  these measured parts (B10).

## 3. Driver and probe defects (lane G's own)

| # | Defect | State |
| --- | --- | --- |
| B1 | `--no-wait` exited 0 when the VM's start was refused | fixed, with a test |
| B2 | G-4 kept only counts, not the failing answers | fixed, with tests |
| B3 | a spot stockout at start was not retried | fixed: `TB_START_RETRIES`, `TB_START_RETRY_SECONDS` |
| B4 | the refusal over an uncollected run did not name `--discard-previous` for a run collected elsewhere | fixed |
| B5 | no repeats per setting, no restart between settings | repeats built (`--repeats N`), with tests; no restart between settings, and the report says so |
| B6 | `playwright install --with-deps` ran apt without the dpkg lock wait; run `20261113T072836Z` ended at TB-SETUP-FAILED | fixed, with a test |
| B7 | in bucket mode the VM stayed up about five minutes after the last collect, until `--stop` | fixed: the VM powers off after its last upload went through; rehearsed |
| B8 | the results reader took its rates from the whole part, not the main SCREEN | fixed, with a test |
| B9 | G-5 does not measure English | fixed: English measured in run `20261113T231557Z` (P2) |
| B10 | the estimate for a 50,000-patient part was 3.8 times the measured time | fixed: the estimate reads the measured parts of both runs and names them |
| B11 | a bucket name left in the VM's metadata by an earlier run was read by a later door-mode run | fixed, with a test |
| B12 | a Node.js download cut short was kept on the disk and broke the next set-up | fixed: fetched again, with a test |
| B13 | G-8 compiled the public protocols with the run's model client, which calls the gateway as the orchestrator; the orchestrator may not use `extract_criteria`, so in run `20261113T231557Z` both protocols ended `CompileFailed: ir_extract: ... gateway refused ir_extract: role_not_allowed` | fixed, with a test: G-8 calls as `criteria-compiler` with that service's token, as the box's compiler does; the gateway policy is unchanged |

## 4. Asked of other lanes

1. Lane A: two public protocols under `tests/fixtures/public_protocols/`, so that G-8 can run.
2. Lane D: the gateway's audit records each call's slot wait.
3. Lane D: `tools/e2e_simple.py` `Stage.check` cuts check detail at 300 characters.
4. Lane D: name the structured-output backend in the serving record and look at P3.
5. The criteria-compiler lane: B14 (an undefined value set fails the whole protocol instead of one criterion).

## 5. G-8: public protocols compiled with the production judge

Run `20261114T014216Z-cb850470` (cb850470, G-8 only, after the B13 fix; the gateway answered all 33 calls, none
refused). VM up 01:42 to 01:54 UTC: about 0.2 VM hours, about US$0.55 at the spot price. 2 of 3 checks passed;
folder `g8-2026-11-14/`.

| Protocol | Result | Criteria | structured / note / mixed / human | needs_review | time_sensitive |
| --- | --- | --- | --- | --- | --- |
| NCT02629159 (rheumatoid arthritis) | compiled | 10 | 1 / 7 / 1 / 1 | 7 | 0 |
| NCT03887455 (early Alzheimer's disease) | failed: `KeyError: 'ValueSet VS_CDR_SCORE not defined for ruleset G8P2'` | - | - | - | - |

- **NCT02629159.** No extension-phase line active without a warning (it has none); the one "at least one of the
  following" group (`G8P1-INC-06`, `G8P1-INC-07`) is not flattened to AND. 11 concepts could not be mapped; 7
  criteria are flagged for review, each with the compile warning that moved it (the coded pre-check dropped, the
  notes decide it, or human review).
- **NCT03887455.** The compile failed as a whole: the model's logic named a concept ("CDR score") it did not list
  as a concept candidate, and the compiler crashed instead of sending that criterion to review (B14, a product
  defect, criteria-compiler lane). So the two checks on the extension phase and alternative groups were measured on
  NCT02629159 only; the extension-phase check, the one NCT03887455 was chosen for, is not measured yet.
- Evidence: `g8-2026-11-14/g8-protocols.json` (`protocols.protocols`), `g8-2026-11-14/report.md`.
- Still to measure: NCT03887455 after B14 is fixed (one short run, `complete_run.py --only g8-protocols`).
