# V1, the qualification, made ready, 2026-11-17 (card H-28)

**Reader:** the integrator, who launches V1 and rules on the questions of section 7; the lanes that own a gap card

Plan 8 (`docs/plan/44-plan-8-2026-11-17.md`, sections 3 and 5) calls V1 "the single piece of work that most others
wait for": V2 and V11 start only after it, and the signed bundle, V10 and V17 follow them. This page lists what V1
asks of `trialbox eval qualify`, what `qualify` does on master today, and a card for each gap. With H-19 (the record
named by the installed commit) and H-15's plan (`docs/plan/measurements/qualify-plan-2026-11-17.md`) it ends in the
launch sheet of the qualification run, in the form of H-7's sheet (`docs/plan/measurements/launch-sheet-2026-11-17.md`).

Nothing was launched and no model was called. Every command quoted was run in this branch's container, on master
`3f6a02ecc703582667ad2027233043f870ca8790` (train 75), with the stub model where a model was needed; output is
trimmed, not edited. **Shown** means a command here printed it. **Hypothesis** means it was found by reading code and
not run. No gate below is called met or passed: only a launch on real weights can show that (D-1064).

## 1. What V1 asks, and what master does

Plan 8 names V1's content in section 5a ("The full `qualify`: serving record, licence, schema, longest prompt, the
self-test per language, the pair gate, the extraction step, the injection suite"), its place ("a box installed from
the signed bundle, on the GPU VM; then on the reference workstation"), its record ("in `eval/qualification/`, named
in the prompt registry and the release record"), its entry and exit in section 5b ("the extraction step, the
per-language thresholds and the injection step are in `qualify`; the rule sets are ready to re-pin"; done when
"`qualify --check` answers 'qualifies' for PRODUCTION"), and release criterion 2 in section 3 ("every approved rule
set pins those prompts"). The table has one row for each.

The 15 steps of `qualify` are `STEPS` in `tools/qualify.py`. `finalize` makes the record `failed` unless every one
of them is in it and `passed`, so a step V1 does not name (the three evidence steps, for instance) still decides
the record.

"Blocks" means the qualification run cannot give a record that `qualify --check --environment PRODUCTION` accepts
until the card lands. "Weakens" means the run can give that record, but V1's exit or its use at a site is not reached.

| # | Plan 8 asks | `qualify` on master (file:function; record field; the test that holds it) | Gap | Lane | Card, size | Blocks or weakens |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Serving record | `tools/qualify.py:step_serving_record`; `steps.serving_record.detail` holds `git_head`, `git_dirty`, `driver`, `cuda`, `gpu`, `routing_version`, `registry_version`, `prompt_registry_version`, `prompts`, `model_server_image`, `chat_template_sha256`; fails on unknown code, a dirty tree, no driver. Tests: `tests/unit/test_qualify.py`, `tests/unit/test_qualify_code_identity.py`, `tests/unit/test_qualify_host_gpu.py`, `tests/unit/test_qualify_in_the_image.py` | On the driver's route the record's code is `image:<id>` (`tools/code_identity.py:head`), which no evidence file can name (H-15 F1); H-19 replaces it by the installed commit. Separately, `chat_template_sha256` is null on the driver's route (hypothesis, item 1b below) | H | H-19 (in flight), S; QUALIFY-TEMPLATE-PIN, S | H-19 blocks (through the evidence gates, row 9). The template: weakens (the record cannot be shipped) |
| 2 | Licence | `tools/qualify.py:step_licence`; `steps.licence.detail.<role>` with `name`, `verified`, `register`, `file` (and `file_sha256` or `text`); the register is `docs/licences/register.csv` through `tools/licence_register.py:model_problems`. Tests: `tests/unit/test_qualify.py` (the `hw004` cases), `tests/unit/test_licence_register.py` | None found. The register half is clean offline (section 2); the weight-folder half needs the weights | – | – | – |
| 3 | Schema | `tools/qualify.py:step_schema`; every prompt of the active set once, with the adversarial line of `eval/qualification/schema_probes.yaml`; `steps.schema.detail` `probes`, `sent`, `valid`. Tests: `tests/unit/test_qualify.py` (`a_missing_schema_probe…`, `a_schema_violation…`) | None in the code. Which prompts the active set holds is a ruling: plan 8 section 8c removes "from the 'must qualify' set" any prompt the release does not use, and the active set has 13 | Int | SHIPPED-PROMPT-SET, S | Weakens (calls spent on prompts that do not ship) |
| 4 | Longest prompt | `tools/qualify.py:step_longest_prompt` with `longest_prompts`; `steps.longest_prompt.detail.roles` (`tokens_needed`, `result`) against the judge build's `context_length`. Tests: `tests/unit/test_qualify.py` (`the_longest_prompt_is_sized…`, `…must_fit…`) | None | – | – | – |
| 5 | The self-test per language | `tools/qualify.py:step_canary` calls `services/orchestrator/selftest.py:run_selftest`; `steps.canary.detail` has `ok`, `cases`, `models`, `pair`, `problems`, and no language. The thresholds (`MIN_ANSWERED`, `MAX_FLIPS`, `MIN_ACCURACY`, `MAX_PAIR_WRONG`) apply to the 54 cases pooled (`check_model`). Tests: `tests/unit/test_trialbox_selftest.py`, `tests/unit/test_canary_gate.py` | The thresholds are pooled: a model that fails Japanese passes (shown, section 2) | A2 | SELFTEST-PER-LANGUAGE (full review G6), S | Blocks (plan 8 section 5b names it in V1's entry) |
| 6 | The pair gate | `tools/qualify.py:step_pair_gate` with `run_pair` and `tools/judge_bakeoff.py:metrics`; `steps.pair_gate.detail` `items`, `asked`, `exclusions`, `wrong_exclusions`, `no_answer`, `checks`. Per gated source (synthetic, medtxt: `GATED`): wrong exclusions at most 2 %, at least 20 exclusions, at least 50 answered, no answer at most 10 %. Tests: `tests/unit/test_qualify.py`, `tests/unit/test_h14_qualify_progress_2026_11_17.py` (the heartbeat and the driver's progress line) | None in the code. Time only: `planted_defect` runs the whole pair set again (H-15 F3) | A2 with a ruling | DEFECT-SAMPLE, S (only if the integrator wants it) | – |
| 7 | The extraction step | No step. `tools/ir_extract_canary.py:score` scores a version's answers on the 110 lines of `eval/qualification/ir_extract_v4_canary.jsonl` (D-984) and is called by no step. `ir_extract@4` is in the active set, so `schema` checks its output's shape, not its content. Test of the scorer: `tests/unit/test_ir_extract_v4.py` | No `extraction` step and no threshold (full review M-2, G2) | A2 | QUALIFY-EXTRACTION, S; then QUALIFY-EXTRACTION-DRIVER (lane H: the step's name in `QSTEPS` of `deploy/gcp/box-install-run.sh` and in the rehearsal's stand-in), S | Blocks (plan 8 section 5b) |
| 8 | The injection suite | `tools/qualify.py:step_injection` with `tools/injection_eval.py`; the 70 cases of `eval/injection/cases.yaml`; `steps.injection.detail` `attacks`, `changed`, `false_positives`, `by_language`, `checks`; the locator called as the document parser (caller doc-parser). Tests: `tests/unit/test_injection_suite.py`, `tests/unit/test_injection_hardening.py` | None. 0 changed facts is absolute, so a pooled check is also per language | – | – | – |
| 9 | (required by `finalize`) the evidence steps `n12`, `public_e2e`, `goldens` | `tools/qualify.py:step_evidence`: a JSON file with `passed` or `ok` true and `head` equal to the record's code; `n12` also `basis: unadjusted`, `source: screen`. Test: `tests/unit/test_qualify.py` (`evidence_at_this_head…`), `tests/unit/test_qualify_n12_from_screen.py` | (a) `tools/public_e2e.py` writes `result.json` with no `passed`, `ok` or `head` (shown, section 2). (b) `tools/goldens.py` writes no result file. (c) `tools/n12_screen.py` needs the score of a TREC CT 2021/22 run (`SETS = {"trec"}`) of at least 400 eligible pairs at the same commit: a paid accuracy launch before V1 | A2 (a, b); Int and H (c) | PUBLIC-E2E-RESULT, S; GOLDENS-RESULT, S; N12-BEFORE-V1, L (a launch) | All three block |
| 10 | (required by `finalize`) `pin`, `log_marker`, `determinism`, `throughput`, `planted_defect` | `step_pin`, `step_log_marker`, `step_determinism`, `step_throughput`, `step_planted_defect` in `tools/qualify.py`. Tests: `tests/unit/test_qualify.py`, `tests/unit/test_g1_b3_qualify_marker.py`, `tests/unit/test_champion_qualify.py` | None | – | – | – |
| 11 | "A box installed from the signed bundle, on the GPU VM" | The driver can install a VALIDATION box only from a bundle signed with a throwaway key (`deploy/gcp/box-run.sh` sets `tb-vendor-pub` to `r2/<id>/throwaway-signing-key.pub` in validation mode, with no option to name another key). A production start installs a PRODUCTION box, where qualify's calls have no route (D-823 point 4; shown, section 2): its 08 step can only fail | (a) Whether a validation-built bundle of the release commit is "the signed bundle" is a ruling (question 1). If it is not, a VALIDATION start must take a vendor-signed bundle. (b) Production mode's 08 to 11 cannot pass | H | VALIDATION-FROM-RELEASE, S (only if ruled); PRODUCTION-08, S | (a) blocks only if ruled so. (b) neither: a trap for a G-2 launch |
| 12 | The record "in `eval/qualification/`" | `tools/qualify.py:main` writes to `OUT_DIR` = `eval/qualification/`; the driver copies it out of `$TB/qualify-out`. D-569 ships it from `deploy/qualification/<profile>/` (`deploy/qualification/README.md`), where no record is yet | Two places, both written by hand from the run's record. No gap in the code | Int | (with the release PR) | – |
| 13 | "Named in the prompt registry" | `libs/tb_llm/prompt_registry.py:check_qualification` wants, per prompt, `qualification: {record, sha256}` pointing at a JSON file under `libs/tb_llm/prompts/qualification/` that names `prompt`, `sha256`, `schema_sha256`. That folder does not exist, and no tool writes such a file from a qualify record (searched in `tools/`, `libs/`, `services/`, `deploy/`) | A writer from the record's `steps.serving_record.detail.prompts` to one file per prompt, and the registry rows | Int with A2 | PROMPT-QUAL-FILES, M | Blocks V1's exit and criterion 2, not the run |
| 14 | "Every approved rule set pins those prompts" | All eight `rulesets/*/manifest.yaml` say `judge_prompt: judge_v4`; the active set qualifies `judge@5`. `PromptRegistry.pin_drift` lists the drift | Re-approval of the eight rule sets on the qualified versions | Int | RULESET-REPIN, S | Blocks criterion 2, not the run |
| 15 | "Named in … the release record" | `tools/release.py` writes `release.json`; it names no qualification record (no field, by reading). The record rides in the bundle's host tree under `deploy/qualification/`, covered by the signature (D-569) | `release.json` (and V18's release record) names the record and its sha256 | D | RELEASE-NAMES-RECORD, S | Weakens (V18) |
| 16 | "`qualify --check` answers 'qualifies' for PRODUCTION" | `tools/qualify.py:check_record` recomputes status, body sha256 and profile and refuses a stub or synthetic record for PRODUCTION (shown, section 2). It does not read `git_head` (H-15 F4) | Nothing ties the record's commit to the release that ships it | D | RECORD-COMMIT-CHECK, S | Weakens |
| 17 | (the record keeps its meaning) the model server image | `steps.serving_record.detail.model_server_image` from `deploy/images.lock`; `pin_model --promote-shipped` refuses a record taken with another image | The vulnerability waiver of the model server image lapses on 2026-12-10 (plan 8, item F1 of the full review). A new image means a new record | D | the waiver card of plan 8 section 4 (F1), S | Weakens: a timing risk |
| 18 | "Then on the reference workstation" | – | The hardware is not in hand (plan 8 section 10) | Int | (V10) | Not part of the first run |

**1b. The chat template on the driver's route (hypothesis).** `step_serving_record` takes `chat_template_sha256`
from `pinned_template_sha256`, which reads `TB_REGISTRY_OVERRIDE` or else `deploy/site/registry.site.yaml` under the
code's root. In the driver's qualify container the root is `/app`; `img_tool` mounts the box's `deploy/` at `/d`,
and `d_qualify` (`deploy/gcp/box-install-run.sh`) passes no `TB_REGISTRY_OVERRIDE`. The image does not copy
`deploy/site/` (`deploy/docker/python.Dockerfile`). So the field would be null, and `pin_model --promote-shipped`
refuses such a record ("the record does not name the judge's chat template", `tools/pin_model.py`). The offline stub
record has the field null for the same reason (section 2), which is consistent with this reading, not proof of the
box. The fix is one line of lane H's driver (`-e TB_REGISTRY_OVERRIDE=/d/site/registry.site.yaml` in `d_qualify`),
listed as a card and not made here.

**1c. Two findings about H-15's findings, on master today.** F2 (the checkpoint counted heartbeats as gates) is
fixed: `prog_qualify` in `deploy/gcp/box-install-run.sh` counts each gate once, held by
`tests/unit/test_h14_qualify_progress_2026_11_17.py`. F5 (no qualify rows in the estimate; no qualify group) and F7
(production mode's 08 is a plain `need`) still hold; F7 matters less than row 11(b), since production mode's 08
cannot pass at all.

## 2. What needs a GPU launch, and what was shown offline here

| # | Item | Needs the GPU launch for | Shown offline here |
| --- | --- | --- | --- |
| 1 | Serving record | the driver, CUDA, the code named by the installed commit, the image and template as the box has them | the stub record's fields; H-19's naming (below) |
| 2 | Licence | the licence file in the verifier's weight folder | both builds' registry and register rows clean |
| 3 | Schema | the real pair's answers | all 12 probes valid on the stub; one prompt not probed on the stub |
| 4 | Longest prompt | the answer, not cut, no retry | the size estimate fits the profile's context |
| 5 | Self-test per language | the real pair's 54 answers | the pooled threshold passes a model at 10 of 18 in one language |
| 6 | Pair gate | everything (2,986 items on the box, H-15) | 300 synthetic items through the stub (medtxt is not fetched offline) |
| 7 | Extraction | everything, once the step exists | the scorer's tests |
| 8 | Injection | the real pair | 56 attacks, 0 changed facts, 0 of 14 false positives on the stub |
| 9 | Evidence steps | n12 needs a paid accuracy launch; public_e2e and goldens are free | the gates refuse an image-named record and public_e2e's file as written |
| 11 | The box | the install | the D0 route per environment; the preflight of a validation start |

The commands, each run from `trialbox/` after `make venv`, with what they printed:

**The whole `qualify` on the stub** (1 min 21 s wall):

```
TB_ENV=TEST TB_CANARY_GATE=off PYTHONPATH=libs:services:. .venv/bin/python -m tools.trialbox \
    eval qualify --profile ci --stub --out <folder>
qualify: pin: passed
qualify: serving_record: passed
qualify: licence: passed
qualify: schema: passed
qualify: longest_prompt: passed
qualify: log_marker: passed
qualify: canary: passed (... the stub's known canary result (judge 18/54, verifier 18/54 correct, 0 decided wrong by the pair))
qualify: pair_gate: 300/300 items answered (18 s)
qualify: pair_gate: passed
qualify: determinism: passed
qualify: throughput: passed
qualify: injection: passed (56 attacks, 0 changed facts; 0/14 false positives)
qualify: n12: passed (wiring only (--stub))
qualify: public_e2e: passed (wiring only (--stub))
qualify: goldens: passed (wiring only (--stub))
qualify: planted_defect: passed (the planted defect was caught)
# rc 0
```

Read from that record: `status: passed`, `qualifies_production: false`, 15 steps; `git_head` the checkout's commit;
13 prompts in `serving_record.detail.prompts` (assist@2, chart_facts@2, classify_intent@3, concept_map@2,
consent_explain@2, consent_translate@2, consent_verify@2, crf_prefill@2, draft_doc@2, ie_locate@2, ir_extract@4,
judge@5, profile_summary@2); `schema`: 12 probes, 12 sent, 12 valid, `not_probed_on_stub: ["profile_summary@2"]`;
`injection.detail.by_language` en 26, ja 15, zh-TW 29; `pair_gate.detail.sources: ["synthetic"]`, 300 items, 0
wrong exclusions; `chat_template_sha256: null`.

**The record against PRODUCTION, and against its own profile:**

```
PYTHONPATH=libs:services:. .venv/bin/python -m tools.qualify --check <record> --profile ci --environment PRODUCTION
refused: synthetic weights or a stub run cannot qualify a PRODUCTION champion
does not qualify                                                   # rc 1
PYTHONPATH=libs:services:. .venv/bin/python -m tools.qualify --check <record> --profile ci
qualifies                                                          # rc 0
```

**The self-test's thresholds are pooled.** A fake judge (no model) answers every case right except eight Japanese
cases with a decided truth, where it says "unknown" (an abstention, never a flip). Script:
`services/orchestrator/selftest.py:check_model` on the 54 cases of `services/orchestrator/canary/judge_canary.jsonl`
(18 per language), run as `TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python <script>`:

```
pooled: correct 46 of 54 = 0.852 flips 0 answered 54 -> model ok: True
  en: 18/18 = 1.000 (MIN_ACCURACY 0.85)
  ja: 10/18 = 0.556 (MIN_ACCURACY 0.85)
  zh-TW: 18/18 = 1.000 (MIN_ACCURACY 0.85)
```

So a model right on 10 of 18 Japanese cases passes the self-test, and with it qualify's `canary` step. This is the
gap of row 5, shown.

**The evidence gates.** `tools/qualify.py:step_evidence` called on files written here, with the record's code set as
`git_head()` would give it, and `tools/code_identity.py:head` called on a folder with no git:

```
1. master code_identity.head (image, no tree): ('image:sha256:abab...ab', False)
2. H-19 code_identity.head (TB_CODE_COMMIT): ('0123456789abcdef0123456789abcdef01234567', False)
   H-19 with a malformed commit: ('unknown', True)
3. n12 (head = commit), record code = image id: ('failed', 'evidence n12.json is from 0123456789ab, not this HEAD')
4. n12 (head = commit), record code = that commit: ('passed', '')
5. public_e2e result.json as written: ('failed', 'evidence public_e2e.json does not say passed')
6. no --evidence for goldens: no --evidence goldens=<result.json>
```

Line 2 is H-19's `tools/code_identity.py`, read from `origin/claude/lane-h-19-installed-commit` (`e1c6d864`) and
loaded beside master's; it is not on master. Line 5 uses the keys `tools/public_e2e.py` writes into `result.json`
(`feas`, `screen`, `cohort_members`, `seconds`, `site`, `terminology_missed`, `swap`, `judging`, `canary`). The commit
is a placeholder.

**Licence, pin and longest prompt for the shipped profile** (`rtxpro6000`), offline, by role (no build named):
`tools/qualify.py:profile_builds`, `tools/licence_register.py:model_problems`, `longest_prompts` and `_estimate`,
run with `TB_ENV=VALIDATION`:

```
judge: status=candidate weights_sha256_pinned=True context=32768 licence_verified=True register_row=True licence_file=none-in-source register_problems=0
verifier: status=candidate weights_sha256_pinned=True context=32768 licence_verified=True register_row=True licence_file=a file in the weight folder register_problems=0
two different builds: True
longest judge (judge@5): about 27563 tokens needed by the estimate; context 32768; fits: True
longest chart_facts (chart_facts@2): about 27848 tokens needed by the estimate; context 32768; fits: True
```

The estimate is the product's own (`tb_llm.budget.estimate_messages`), not the server's tokenizer; whether the
server agrees is what the launch shows.

**Qualify's calls have a route in VALIDATION only** (`gateway.policy.RoutingPolicy.candidates` on
`models/routing.yaml`, topology A, profile P-PRO6000):

```
VALIDATION judge D0: route qualify, 3 candidate(s)
VALIDATION second_opinion D0: route qualify, 3 candidate(s)
VALIDATION extract_criteria D0: route protocol, 2 candidate(s)
PRODUCTION judge D0: refused (Refusal: no route for role=judge class=D0 topology=A env=PRODUCTION)
PRODUCTION second_opinion D0: refused (Refusal: no route for role=second_opinion class=D0 topology=A env=PRODUCTION)
PRODUCTION extract_criteria D0: route protocol, 2 candidate(s)
```

The `extract_criteria` line says the new extraction step would have a route in VALIDATION as the compiler's role.

**The validation-check and the preflights** (free; no cloud call):

```
PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run validation-check
  "qualify's calls (class D0, tools/qualify.py)": { ... "route": "qualify" ... }, "can_run": true, "blockers": []   # rc 0
deploy/gcp/box-run.sh --preflight --mode validation --steps start --release-id val-3f6a02ecc703 \
    --commit 3f6a02ecc703582667ad2027233043f870ca8790 \
    --qualify-evidence "n12=gs://BUCKET/q/n12.json public_e2e=gs://BUCKET/q/public_e2e.json goldens=gs://BUCKET/q/goldens.json"
preflight: ok     the steps are known
preflight: ok     the launch's options would hold on the VM (filter, tag, streams, budgets, commit)
preflight: ok     the metadata builds (every key the steps need, no key-like value)
preflight: every free check passed (nothing was uploaded or started; ...)          # rc 0
deploy/gcp/box-run.sh --preflight --mode validation --steps build --release-id val-3f6a02ecc703 --release-seq 1 \
    --commit 3f6a02ecc703582667ad2027233043f870ca8790
preflight: FAILED the source bundle is proved (D8): --src-bundle FILE is needed: ...
box-run: refused (no VM started): the preflight failed ...                        # rc 6
```

The build preflight fails here only because this checkout is shallow and no source bundle was made (H-15 section 4:
after `git fetch --unshallow`, `tools.box_run src-bundle` gave `"ok": true`).

**The driver's rehearsal** (the VM script unchanged, the box a stand-in):

```
bash tests/rehearsal/box-run/rehearse-box-run.sh happy qualify-timebox acc-qualify-fails
rehearse-box-run: all cases passed: happy qualify-timebox acc-qualify-fails       # rc 0
```

**The tests that hold `qualify` and what it reads:**

```
TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest -q -n 4 -p no:cacheprovider \
    tests/unit/test_qualify.py tests/unit/test_box_qualify.py tests/unit/test_qualify_code_identity.py \
    tests/unit/test_qualify_host_gpu.py tests/unit/test_qualify_in_the_image.py tests/unit/test_qualify_n12_from_screen.py \
    tests/unit/test_champion_qualify.py tests/unit/test_g1_b3_qualify_marker.py tests/unit/test_h14_qualify_progress_2026_11_17.py \
    tests/unit/test_injection_suite.py tests/unit/test_ir_extract_v4.py tests/unit/test_trialbox_selftest.py \
    tests/unit/test_canary_gate.py tests/unit/test_installed_commit.py tests/unit/test_prompt_registry.py \
    tests/unit/test_licence_register.py
291 passed, 12 warnings in 101.97s
```

What none of this shows: any model's answer, any time on the box, the licence file in a weight folder, the medtxt
items, the install from a bundle, H-19's driver lines on a real box.

## 3. The gap cards in order

| Card | Lane | Size | Waits for | Touches |
| --- | --- | --- | --- | --- |
| Rulings: questions 1 to 4 of section 7 | Int | – | – | – |
| QUALIFY-EXTRACTION | A2 | S | question 4 (the threshold) | `tools/qualify.py` (`STEPS`, a step), its schema, `tests/unit/test_qualify.py` |
| SELFTEST-PER-LANGUAGE | A2 | S | – | `services/orchestrator/selftest.py`, its tests; it is also the box's nightly gate |
| PUBLIC-E2E-RESULT | A2 | S | – | `tools/public_e2e.py`: a result with `passed` and `head` |
| GOLDENS-RESULT | A2 | S | – | `tools/goldens.py`: `--check` writes a result with `passed` and `head` |
| H-19, finished and merged | H | S | its decision number: H-19's branch files its decision as D-1134, which master already gives to H-18 | the driver, `tools/code_identity.py` |
| QUALIFY-TEMPLATE-PIN | H | S | – | `d_qualify` in `deploy/gcp/box-install-run.sh` (one line) |
| PRODUCTION-08 | H | S | – | production mode's 08 to 11 in `deploy/gcp/box-install-run.sh`: left out and said, or refused |
| VALIDATION-FROM-RELEASE | H | S | question 1 | `deploy/gcp/box-run.sh`: a validation start that takes the vendor's public key |
| QUALIFY-GROUP | H | M | – | a step group that runs 08 to 12 on a box already installed, with its estimate rows (H-15 F5) |
| QUALIFY-EXTRACTION-DRIVER | H | S | QUALIFY-EXTRACTION | `QSTEPS` in `deploy/gcp/box-install-run.sh`, `tests/rehearsal/box-run/standins/box.py` |
| SHIPPED-PROMPT-SET | Int | S | – | `libs/tb_llm/prompts/registry.yaml` (which prompts stay active) |
| RELEASE-NAMES-RECORD | D | S | – | `tools/release.py`, `schemas/release.schema.json` |
| RECORD-COMMIT-CHECK | D | S | H-19 | `tools/qualify.py:check_record`, `tools/pin_model.py` |
| DEFECT-SAMPLE | A2 | S | the integrator wants it (H-15 question 6) | `tools/qualify.py:step_planted_defect` |
| N12-BEFORE-V1 | Int, H | L (a paid launch) | question 2; every card above that changes code merged; commit C frozen | a TREC CT 2021/22 accuracy launch at C |
| The qualification run (V1) | Int | – | all of the above that block | section 4 |
| PROMPT-QUAL-FILES | Int, A2 | M | a passing record | `libs/tb_llm/prompts/qualification/`, `libs/tb_llm/prompts/registry.yaml`, a writer |
| RULESET-REPIN | Int | S | PROMPT-QUAL-FILES | `rulesets/*/manifest.yaml`, by re-approval |

**In parallel, now:** the four A2 cards touch four different files and can run at once. Lane H's driver cards
(QUALIFY-TEMPLATE-PIN, PRODUCTION-08, VALIDATION-FROM-RELEASE, QUALIFY-GROUP) touch the same two driver files as
H-19: one session after another, or one card. Lane D's two cards and the integrator's prompt-set ruling are
independent of all of them.

**In series:** QUALIFY-EXTRACTION, then QUALIFY-EXTRACTION-DRIVER. Everything that changes code, then commit C is
frozen. Then N12-BEFORE-V1 and the two free evidence files at C. Then the qualification run at C. Then
PROMPT-QUAL-FILES and RULESET-REPIN, and the record copied into `deploy/qualification/rtxpro6000/` in the release's
pull request (D-569).

**The serial chain, then:** rulings, then four S cards in parallel with lane H's driver cards in a row, then a
paid N-12 launch, then the paid V1 launch. The evidence is tied to one commit, so any code change after C means new
evidence and a new run.

## 4. The launch sheet of the qualification run

### 4.1 What differs from H-15's plan

| H-15 | Now |
| --- | --- |
| A `dev` launch, the stack from the commit's tree | A `start` launch from a bundle of commit C. H-19 reads `deploy/updates/installed.json`; a `dev` box has none, so with evidence given the driver stops before qualify (H-19's `code_commit record`; by reading) |
| F1: no record could pass the evidence gates | Closed by D-994 (merged) and H-19 (not merged): the record names C |
| F2: the checkpoint counted heartbeats | Fixed on master (section 1c) |
| 15 steps | 16 once QUALIFY-EXTRACTION lands |
| The `dev` cap, 3 h (175 minutes on the VM) | The `start` cap, 4 h (`GROUP_CAP_HOURS["start"]` in `tools/box_run.py`; the VM's own `tb-max-minutes` 4 x 60 - 5 = 235 minutes = 14,100 s) |

### 4.2 Pre-flight list (all free, in this order)

1. Every card of section 3 that blocks is merged; C is the master commit after them. A full clone (`git fetch
   --unshallow`), `git status` clean at C.
2. The validation-check: `PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run validation-check` prints
   `"can_run": true`, a `qualify` route for qualify's D0 calls and `"blockers": []`.
3. The offline `qualify` at C (the command of section 2) prints 16 `passed` lines with the extraction step, and the
   `--check` against PRODUCTION refuses the stub record. A failure here costs nothing.
4. The source bundle: `PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run src-bundle --commit C --out
   /path/src.bundle`, then the same with `--check /path/src.bundle`: both `"ok": true`.
5. The evidence at C:
   - `public_e2e.json` and `goldens.json`, made at C by the forms PUBLIC-E2E-RESULT and GOLDENS-RESULT give; each
     says `passed` (or `ok`) true and `head` C;
   - `n12.json`: `PYTHONPATH=libs:services:. .venv/bin/python -m tools.n12_screen <the trec score.json> --out n12.json`
     in a checkout at C, from the TREC CT 2021/22 run at C (N12-BEFORE-V1). It must say `passed: true`, `basis:
     unadjusted`, `source: screen`, `head` C, and at least 400 eligible pairs;
   - each uploaded to the run bucket; the `gs://` addresses go into `--qualify-evidence`.
6. Each preflight of section 4.3, with `--preflight` after `box-run.sh`: every line `ok`, rc 0. Exit 6 is a failed
   preflight.
7. The estimates of section 4.4 posted on #639 with the worst case and the running total (D-505), and the owner's yes.

### 4.3 The command lines, once the gaps are closed

The build, if the integrator rules that a validation build of C is the signed bundle V1 needs (question 1):

```
deploy/gcp/box-run.sh --mode validation --steps build --release-id val-<C12> --release-seq 1 \
  --commit <C> --src-bundle /path/src.bundle --no-wait
```

If the ruling is the vendor-signed bundle, the build is a production build (`--steps build --release-id <id>
--release-seq <n> --commit <C> --key-version <N>`), and the start below needs VALIDATION-FROM-RELEASE, whose option
does not exist yet.

The qualification run:

```
deploy/gcp/box-run.sh --mode validation --steps start --release-id val-<C12> --commit <C> \
  --qualify-evidence "n12=gs://<bucket>/<path>/n12.json public_e2e=gs://<bucket>/<path>/public_e2e.json goldens=gs://<bucket>/<path>/goldens.json" \
  --no-wait
deploy/gcp/box-run.sh --collect <run id> --follow
```

- No `--qualify-args` and no `--qualify-timebox`: every item, and a record. A cut run (`--items`) is not V1's record
  (H-15 section 5).
- `--mode validation`: a VALIDATION box, where qualify's calls have a route. Never production mode for V1 (row 11b).
- With QUALIFY-GROUP merged, the N-12 launch and this one can share one install: the N-12 launch as `--steps
  start,acc --only trec --skip 08-qualify`, then this step group on the same box. Without it, two installs.

### 4.4 Estimate, worst case and the stop line

US$2.74 a VM hour, spot (`tools/complete_run.py`). The driver's own estimate, run here:

```
deploy/gcp/box-run.sh --estimate --mode validation --steps start
  VM start                                     900  constant
  01 fetch the bundle, sha256, manifest    unknown
  02 installer (install.sh --answers ...)  unknown   of which the model servers ready 199 measured
  03 the box says VALIDATION               unknown
  04-06 pin, serving record, G-1 identity  unknown
  07 pair canary                               124  measured
  08 trialbox eval qualify (full)          unknown  never run on real weights
  09-12 promote, resolve, doctor           unknown
  known part 0.34 h (US$0.93 spot); 6 step(s) unmeasured, bounded by the cap: 4 h = US$10.96 spot / US$32.88 on demand
deploy/gcp/box-run.sh --estimate --mode validation --steps build
  known part 0.65 h (US$1.79 spot); 4 step(s) unmeasured, bounded by the cap: 2 h = US$5.48 spot / US$16.44 on demand
deploy/gcp/box-run.sh --estimate --mode validation --steps start,acc --only trec
  trec: TREC CT 2021+2022, 1,225 pairs balanced (en)   5292-30636
  known part 1.81 to 8.85 h (US$4.96 to US$24.25 spot); 7 step(s) unmeasured, bounded by the cap: 16 h = US$43.84 spot
```

H-15's qualify figures, reused with three corrections:

| Part of 08 | H-15 | Here | Why |
| --- | --- | --- | --- |
| Gates 1 to 7 | 300 s at most | 300 s at most | measured bound (L8), unchanged |
| pair_gate, 2,986 items | 3,051 to 4,500 s | the same | unchanged |
| determinism, 400 items | 409 to 603 s | the same | a projection, unchanged |
| injection, 70 cases | 285 to 337 s | the same | a projection, unchanged |
| planted_defect | 3,271 to 4,760 s | the same | a projection, unchanged |
| extraction, 110 lines | – | 450 to 1,060 s | new; a projection: 110 calls at the canary's rate (54 cases in 220 to 260 s), to twice that for the longer answers of `ir_extract`. Not measured |
| **Qualify, all** | 7,316 to 10,500 s | **7,766 to 11,560 s** | |
| Around 08 | `dev`: 1,639 s and 07g's 180 to 240 s | `start`: 900 s boot, 199 s model servers, 124 to 260 s canary, and the install, **not measured** (call it U) | the route changed |

So the run is 1,223 + U + 7,766 s at the low rate, and 1,359 + U + 11,560 s at the high one. Under the VM's 14,100 s:

- at the low rate it fits if the install takes at most about 5,100 s (85 minutes);
- at the high rate it fits only if the install takes at most about 1,180 s (20 minutes). The install of a bundle
  has never been timed on this VM; H-15's `dev` bring-up (02, 281 s) is not the same work.

| | VM hours | US$ spot |
| --- | --- | --- |
| The build launch | at most 2 (its cap) | at most 5.48 |
| The N-12 launch (start and trec) | 1.81 to 8.85 known, plus the unmeasured | 4.96 to 24.25; cap 43.84 |
| The qualification launch, low | 2.5 + U | 6.9 + U at US$2.74 an hour |
| **Worst case of the qualification launch** | 4 (its cap; the VM powers off at 235 minutes) | **10.96** |
| Worst case of all three | 2 + 16 + 4 = 22 | 60.28 |

Against the money: H-15 quoted the integrator's running total of 2026-11-17 05:35 UTC, at most US$117.7 of US$200.
This card did not read #639 again; the integrator posts the current figure before the launch (D-505).

**The stop line** (the integrator reads it on the checkpoints, `logs/08-qualify.checkpoints.jsonl`, and the step
log's `qualify: pair_gate: n/2986 items answered` lines). The run fits only if the pair runs keep a rate r with

    r >= 6,372 / (14,100 - T0 - 1,657)

where 6,372 is two pair sets and determinism (2 x 2,986 + 400 items), 1,657 s is injection, the defect's canary and
the extraction at their high figures (337 + 260 + 1,060), and T0 is the VM's elapsed seconds when the pair gate
begins (read from the run's checkpoints). At 1,500 s into the pair gate:

| T0 (VM seconds when the pair gate starts) | Rate needed | Items answered at 1,500 s, at least |
| --- | --- | --- |
| 2,500 | 0.64 a second | about 960 |
| 3,500 | 0.71 | about 1,070 |
| 4,500 | 0.80 | about 1,200 |
| 5,500 | 0.92 | about 1,380 |

Fewer than that: stop with `deploy/gcp/box-run.sh --stop`; the run will not finish under the cap, and a cut 08 leaves
no record. B8 measured 0.979 items a second at 4 in flight (H-15 section 3). The owner's rule (stop more than 50 %
over the estimate) falls after the cap at every T0 above, so the cap decides first.

H-15's own line (1,240 items at 1,500 s) was for a `dev` launch under a 3 h cap; with the extraction step it would be
about 1,310 to 1,430. It does not apply to a `start` launch.

### 4.5 What the record must contain to pass the three evidence gates unchanged (with H-19)

- `git_head` is C, the 40-hex commit of `deploy/updates/installed.json` (`commit`, with `dirty: false`), passed by
  H-19's `code_commit` as `TB_CODE_COMMIT` (D-994, D-1134 on H-19's branch). Not `image:…` and not `unknown`.
- `steps.serving_record.detail.git_dirty` is false; `detail.code_image` (H-19) names the image beside it.
- Each of `steps.n12`, `steps.public_e2e`, `steps.goldens` has `detail.mode: "evidence"`, `detail.head` equal to C,
  and the file's sha256; `steps.n12.detail.basis: "unadjusted"` and `detail.source: "screen"`.
- The bundle was built without `--allow-dirty` (a validation build is: `d_sign_throwaway` passes none), so the
  installer records `dirty: false`.
- For the record's use beyond the run: `chat_template_sha256` equal to the judge's pin (QUALIFY-TEMPLATE-PIN) and
  `model_server_image` equal to `deploy/images.lock` of the release (row 17).

### 4.6 What would stop the run

- `TB-CODE-COMMIT-REFUSED` (H-19): `installed.json` missing, `dirty` not false, `commit` missing, null or malformed.
  With evidence given this is a STOP before qualify starts.
- An evidence file that cannot be fetched (`need "fetching qualify evidence …"`).
- Qualify writing no record: "the qualification wrote no record (exit N)".
- The VM's cap (235 minutes) or the cloud's (4 h): 08 ends with no record. A spot pre-emption: `--resume <run id>`
  runs 08 again from its first gate; give `--qualify-evidence` again (H-15 section 7).
- The idle watchdog (20 minutes) is fed by the card's use in validation mode; not a risk there (H-15).
- The integrator, on the stop line of section 4.4.
- Not a stop: a failed gate. In validation mode it is a result (D-511), the record is `failed`, and 09 and 10 promote
  nothing.

## 5. Not shown

- Any answer of the real pair: schema, longest prompt, canary, pair gate, determinism, injection, extraction,
  planted defect. Every time on the box.
- The install of a bundle on the GPU VM, and its time (U of section 4.4).
- H-19's driver lines on a box: read on its branch, its `code_identity` loaded here; not merged, not run on a VM.
- That `chat_template_sha256` is null on the driver's route (section 1b): read, not run in the image.
- The medtxt items (not fetched offline) and the 2,986-item count (H-15's, from B8).
- The extraction step's time and its threshold: the step does not exist.
- The N-12 launch's cost beyond the driver's estimate, and whether it reaches 400 eligible English pairs.
- That a resume of an N-12 launch made with `--skip 08-qualify` would run 08 with `--qualify-evidence` given on the
  resume: not read far enough to say; QUALIFY-GROUP is the route this page relies on.
- The running total on #639.
- The second run on the reference workstation.

## 6. Defects found in lane H's own driver files

Listed as cards, not fixed here:

- QUALIFY-TEMPLATE-PIN: `d_qualify` passes no `TB_REGISTRY_OVERRIDE`, so the record's `chat_template_sha256` would
  be null (one line; hypothesis, section 1b).
- PRODUCTION-08: production mode runs 08 against a PRODUCTION gateway that refuses qualify's D0 calls (shown,
  section 2), as a plain `need`: every production `start` launch stops at 08 unless it is skipped.
- VALIDATION-FROM-RELEASE: `box-run.sh` has no option to name the public key of a validation start.
- QUALIFY-EXTRACTION-DRIVER: `QSTEPS` must follow `STEPS` once the extraction step exists, or `prog_qualify` names
  the wrong next gate.

## 7. Questions for the integrator

1. Is a validation build of the release commit (signed with a throwaway key on the VM, "not a release") the "signed
   bundle" V1 asks for, or must V1's box be installed from the vendor-signed bundle? The second needs
   VALIDATION-FROM-RELEASE, a production build with the vendor key, and a release-gates pass (the driver's build
   estimate notes that `make release-gates` failed at the end on the model server's CVE in CI run 43602503189).
2. N-12 at the same commit needs a TREC CT 2021/22 accuracy launch before V1 (US$4.96 to US$24.25 known, cap
   US$43.84). Plan 8 puts V2 after V1. Should N-12's launch come first as its own launch, should the V1 record take
   N-12 from V2 by a changed rule, or should `n12` leave V1's record? The last two are a rule change and need a
   decision.
3. Which prompts does release 1.0 ship (plan 8 section 8c)? The run qualifies the 13 of the active set.
4. The extraction step's threshold: every one of the 110 lines (the exit code of `tools/ir_extract_canary.py`), or a
   share?
5. H-19's branch files its decision as D-1134; master's registry gives D-1134 to H-18. H-19 needs another number
   from lane H's range before it merges.
