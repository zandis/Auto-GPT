# Model change protocol

*Card T-649b, decision D-343. Closes REG-032 (with `docs/validation/ai-governance.md` for REG-006 and REG-030).*

This protocol works like a predetermined change control plan (the FDA PCCP guidance, used as a model only). It lists
the model changes we can foresee and gives each one a fixed test and a fixed threshold. It also covers the impact
check, rollback and who is told. Every test is an automated check. D-311 applies: no person signs a change, and
nothing waits for a reviewer. A change ships when its checks pass and its CI is green.

The tool is `trialbox eval qualify` (`tools/qualify.py`, D-313). It writes a record to `eval/qualification/` that
follows `schemas/qualification_record.schema.json`. Every record cites this protocol in its `change_protocol` field:
the path, the sha256 of this file and the change id (`--change MC-n`). A record that has no citation fails the
schema, so `qualify --check` refuses it. `tests/unit/test_model_change_protocol.py` checks this file against the code:
the change ids, the step names and every number in the threshold table.

## 1. What a change is

A model change is any change that can alter what the judge or the verifier answers for the same input. The pair is
the judge (Gemma 4 26B-A4B) and the verifier (Qwen3.5-9B) behind `tb-gateway`. A note answer excludes a patient only
when both say "fail". The coded filters and FEAS have no model, and the goldens cover them
(`docs/VALIDATION.md` §1).

A build in `models/registry.yaml` is immutable (MOD-7). New weights, a new revision or a new quantisation make a new
`build_id`. A prompt text is immutable too: a new text is a new registered version (`libs/tb_llm/prompts/registry.yaml`,
D-300).

## 2. Foreseen changes

Each row is a change id that `--change` accepts. "Full qualify" means that all 14 steps of `tools.qualify.STEPS` run
and pass on the target profile. A step that is missing counts as failed. The thresholds of each step are in §3.

| Id | Change | Foreseen now | Test | Threshold |
| --- | --- | --- | --- | --- |
| MC-0 | First qualification of a pair on a profile | the deployed pair on `rtxpro6000`; the `ci` stub pair | full qualify | every step passes (§3) |
| MC-1 | New version of a registered prompt | the injection rule in every prompt (T-606); the judge's negated-exclusion rule (`eval/trec_ct/AUDIT.md`) | full qualify; then the registry entry's `qualification.record` names the new record, and the prompt registry checks it at load in PRODUCTION | every step passes; the prompt registry raises no `prompt_unqualified` |
| MC-2 | New weights for a deployed model: new revision, new quantisation or own copy | the verifier as our own quantisation or a mirrored copy (T-674); a pinned upstream revision in place of `revision: null` | `pin_model --build <id> --verify`; full qualify on the new `build_id` | `--verify` exits 0; every step passes; `pin` sees the new weight hash in every answer |
| MC-3 | New chat template or tokenizer config | the Gemma template and tokenizer config from upstream with `--chat-template` (DEP-007) | full qualify; `serving_record` records the change | every step passes |
| MC-4 | Judge replaced by another model | the Gemma 4 31B challenger (T-674, PR #64 bake-off) | `tools.judge_bakeoff` on the challenger alone; full qualify of the new pair | the bake-off gate passes; every step passes |
| MC-5 | Verifier replaced by another model | a second verifier candidate (T-674, RSK-60) | full qualify of the new pair | every step passes; `pin` refuses a pair that is one build |
| MC-6 | Serving engine change: vLLM image, version or server flags | a vLLM upgrade; KV cache dtype; context length | `serving_config validate <file>`; full qualify | `validate` lists no gap; every step passes |
| MC-7 | New hardware profile or GPU layout | the B200 with two MIG instances (T-113b, T-114); `gb10`; `shared-quota` | `serving_config measured <gpu> <file>`; full qualify with `--profile <new>` | `measured` says yes; every step passes on that profile |
| MC-8 | Routing or call settings: alias map, sampling, `max_tokens`, cache | a change to `models/routing.yaml` | full qualify | every step passes; `determinism` shows 0 cache hits |

Anything else that can change an answer is a new row with its own id. It goes in this table, in `CHANGE_TYPES` in
`tools/qualify.py` and in the test, all in the same pull request. Until it has a row, `qualify --change` refuses the
id. Guard and embedder builds do not decide exclusions and are outside this protocol. Their own checks cover them
(`doctor`, the injection suite of T-208).

## 3. Thresholds

These are the thresholds of the full qualify. Each one is in code, and the test reads the numbers from the code.

| Step | Threshold | Where in code |
| --- | --- | --- |
| `pin` | the gateway lists both aliases; every answer carries the pinned build; the judge and the verifier are two builds | `step_pin` |
| `serving_record` | git HEAD, driver, CUDA and the active prompt set with their sha256 are recorded | `step_serving_record` |
| `licence` | each build's licence row is verified, and the weight folder holds a licence file | `step_licence` |
| `schema` | 100 % of prompts answer valid JSON on the first attempt and are not cut off | `step_schema` |
| `longest_prompt` | the longest prompt plus `max_tokens` fits the profile's context and gets an answer | `step_longest_prompt` |
| `log_marker` | 0 copies of the planted marker in gateway audit files, process logs or server logs | `step_log_marker` |
| `canary` | per model, at least 95 % answered, at least 85 % correct and at most 1 flip; at most 0 cases decided wrong by the pair | `orchestrator.selftest` |
| `pair_gate` | per gated source, wrong exclusions at most 2 % of exclusions, at least 20 exclusions, at least 50 answered and at most 10 % with no answer | `tools.judge_bakeoff.GateConfig` |
| `determinism` | 0 changed exclusions over two runs at concurrency 16; 0 cache hits | `step_determinism` |
| `throughput` | reported only; no threshold (LLM-025) | `step_throughput` |
| `n12` | TREC CT eligible pairs wrongly dropped, **unadjusted**, at most 5 %; the evidence must say `"basis": "unadjusted"` | `step_evidence` |
| `public_e2e` | every check of `tools.public_e2e` passes at this git HEAD | `step_evidence` |
| `goldens` | `make goldens-check` is identical at this git HEAD | `step_evidence` |
| `planted_defect` | the same pair with every decided verdict flipped fails both the canary and the pair gate | `step_planted_defect` |

N-12 gates on the raw figure. The audit-adjusted figure rests on a label sample that an AI assistant checked, not a
clinician. It may be shown as a note, never as the gate (REG-030, D-343).

For PRODUCTION, `qualify --check <record> --profile <p> --environment PRODUCTION` must also answer "qualifies". It
refuses an edited record, a record of another profile, synthetic weights and stub runs. A champion is set only through
that check (T-012b).

## 4. Impact check

The impact check is computed from the record. No one writes it by hand.

- **Which builds.** `builds` in the record names the `build_id`, the weight hash and the revision of each role.
- **Which prompts.** `serving_record` lists the active prompt set with each text and schema sha256. Approved rulesets
  pin their prompt versions (D-318), so a new prompt version does not change an approved ruleset's SCREEN until the
  ruleset is approved again with the new pin.
- **Which sites.** The profile in the record names the hardware. Each site runs one profile.
- **Which jobs.** A job record names the prompt `id@version` it ran with (D-300), and the gateway's audit names the
  build of each answer. The jobs before and after a change can be told apart.

## 5. Rollback

- **Weights, template, engine, profile (MC-2 to MC-7).** Pin the previous champion build again with
  `tools/pin_model.py`. Its record still passes `qualify --check`, because records are never edited and builds are
  immutable. If the check refuses it, nothing is rolled back to it.
- **Prompt (MC-1).** The previous version stays in the registry and keeps resolving for every job and every ruleset
  pin that names it. Rolling back means registering the earlier text as the newest version. It needs the same
  qualification as a new one.
- **Routing (MC-8).** Revert the change to `models/routing.yaml` and redeploy.

A rollback is a change too. It runs the same full qualify before it serves, unless the earlier record for that exact
build and profile still passes `--check`.

## 6. Who is told

Telling people is for information only. No step waits for a reply (D-311).

| Who | When | What |
| --- | --- | --- |
| the site's users | the change is deployed | the admin models page shows the champion and its record (T-012b) |
| a sponsor whose study uses CRF prefill | a change to a prompt or model that the prefill uses | the record id and the change id |
| the IRB | never for a model change | the IRB texts name no model and no prompt, on purpose, so that a qualified change does not alter an approved text |

## 7. Evidence

The evidence for a change is its qualification record: one file in `eval/qualification/` per run, kept in git. The
record has hashes, counts and codes only, with no note text, prompt or answer. Its `change_protocol` field cites this
file by sha256, so a later edit to this protocol is visible against older records.
