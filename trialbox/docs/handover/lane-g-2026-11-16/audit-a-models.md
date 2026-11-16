# Audit A: everything where a model answers (2026-11-14)

Read-only audit of the latest integrated tree `/home/user/Auto-GPT/.claude/worktrees/latest/trialbox` at
`0c8e1211` (origin/train/17: master 5ff9f813 + train 16 + train 17). Lane G's unmerged work read from git:
`lg/batch6` (73bb84e0, merge base d4c22a8c, 228 commits behind HEAD), `lg/batch7` (befe8e6b), `lg/batch8` (ab6f5213,
already merged with train/17). Nothing was run, nothing was changed. "Not verified" means I did not check it.

## 0. The answer in ten lines

1. **No accuracy figure the repo quotes today was measured on what ships on the latest tree.** Not one.
2. N-11 and N-12 (VALIDATION §3) were measured with a **different prompt** (`tools/mlbench.py` SYSTEM, a 4-label
   whole-note task), sent **straight to vLLM** (no gateway, no cascade, no retrieval, no clipping, no masking), with
   the **quantised folder's own chat template** (the box ships the developer's template), on 2026-11-08. N-12's 9.4 %
   is a projection (`hospital_sim project`) from a per-criterion rate, with a stub-derived share of criteria.
3. The real-model runs that do use the product path (hospital 5k/50k, public-ja/zh-TW, G-7, G-8, the canary) are all
   on commits **before** NEW-LLM-2 (#582: retrieval), SCR-01/03 (#567/#570), OUTAGE (#576), SCR-18 (#578), B14 (#586),
   chart negation/family history (#572/#573), English phones (D-744) and the note mask (D-745). Every one also ran
   with the folder's chat template (`deploy/gcp/complete-run-vm.sh:346-362` passes no `--chat-template`).
4. **In PRODUCTION nothing is qualified.** Every deployed build is `candidate` (`models/registry.yaml:116-176`), no
   qualification record exists, every hardened prompt (judge v5, ir_extract v3, chart_facts v2 ...) has
   `qualification: null`, so a production box serves the old baseline prompts **without the injection paragraph**
   (D-359) and its gateway refuses an unqualified champion. That is "no model": the pair has never been qualified.
5. On the latest tree SCREEN still ranks note sentences with `HashEmbedder` (`screen_cascade.py:411,440`), and since
   NEW-LLM-2 a note criterion with no lexicon term is "not evaluated" and **never reaches the judge**. #589 (the embedder in
   SCREEN) is not merged. Any run before #589 measures a screening path that asks the models less than it will.
6. Gold that truly exists today: generator-planted truth on synthetic template notes (ja/zh-TW/en), MedTxt-CR/RR
   certainty tags (real ja, CC BY 4.0), TREC CT and SIGIR pair labels (en; NIST/physician), 54 canary cases. **No
   real zh-TW clinical text of any kind. No gold for protocol extraction. No gold for retrieval. No calibration.**
7. The latest screening path needs, at minimum: a gated accuracy set per language and stratum through the product
   judge + verifier (NEW-LLM-6), a protocol-extraction gold set, a coded-mapping gold for the first site's local codes,
   and one real `trialbox eval qualify` record on the shipped serving configuration.
8. Lane G's cost table plans to spend money re-running the stale paths (N-12 one-boot script, mlbench TREC scenario,
   N-11 translations, MedTxt mlbench, MIMIC on the stub) and has **no row with a cost** for the accuracy set or for
   qualify. It is also built on a stale base: it says D-744/D-745 are not on train 17; they are (f641b879, 4150aa8f).
9. Lane G changed two failing checks so they pass against the old 2026-11-08 non-product answers (TREC: 12 of 50
   eligible lost now "PASS"). That turns a validation into a regression check against a failing baseline.
10. The first paid step should be one run on the shipped serving config: G-1 (chat template), then `qualify` with
    the real pins and the prompt set the owner decides to ship, on a tree with #589. Throughput curves come later.

## 1. What the latest repo does here (map)

| Step | What answers | Prompt served in PRODUCTION (TEST/DEV) | Path | Evidence |
| --- | --- | --- | --- | --- |
| Protocol ingest: locate I/E | judge build, role `extract_criteria` | `ie_locate@1` (`@2`) | doc-parser -> gateway | `registry.yaml`, `v1_roles.yaml` |
| Criteria extraction to IR | judge build | `ir_extract@2` (`@3`) | criteria-compiler -> gateway | `registry.yaml:93-110` |
| Concept choice | judge build, `concept_select` | `concept_map@1` (`@2`) | criteria-compiler -> gateway | same |
| Compile to SQL/CQL; uncompilable -> human/note (B14 fixed) | no model | - | `criteria_compiler/service.py`, `postprocess.py` | #586 (0113d140) |
| S1 coded filters (exclude without a model; coverage rule turns unknown code systems into `unknown`) | no model, but its inputs come from ir_extract + concept_map | - | `matching/coverage.py` | file header |
| S2 lexicon on notes; S2b ranking | **HashEmbedder**; the embedder not wired into SCREEN | - | `screen_cascade.py:411,430,440`; `engine.py:681-690` | #582 merged, #589 not |
| Clip excerpts (keeps heading and lead-in, D-641) | no model | - | `engine.py` `excerpt_set` | NEW-LLM-1 |
| Note mask before the model (D-744 phones, D-745 DOB/address/chart labels) | no model | - | `guard` / `phi_guard` | 12077db3 ... 52cba46e |
| S3 note judge | the judge family 4 26B-A4B NVFP4 (`j-workhorse`) | `judge@4` (rulesets pin `judge_v4`, `rulesets/*/manifest.yaml`) (`@5`) | orchestrator -> gateway | `prompt_registry.py:381-395` |
| S3 agreement | the verifier model AWQ (`v-verifier`), excludes only when both say fail | same prompt (D-300) | `matching/cascade/judge.py:182-225` | |
| Pair canary (54 cases) at start and before each night | both | judge prompt as served | `orchestrator/canary_gate.py` | `judge_canary.jsonl` |
| Chart facts (pasted/uploaded charts; negation D-657, family history D-658 in post-processing) | judge build, `abstract_field` | `chart_facts@1` (`@2`) | sitesetup -> gateway | #572, #573 |
| EDC prefill | judge build | `crf_prefill@1` (`@2`) | edc -> gateway | |
| Front desk | `f-frontdesk` (judge weights) | `classify_intent@2` (`@3`), free-form `frontdesk_converse` | converse-native -> gateway | `routing.yaml` |
| Consent explain/translate/verify, draft docs, assist, profile summary | judge build (verifier checks consent) | all `@1` (`@2`) | gateway | |
| Guided decoding | vLLM structured output, backend `auto` | - | gateway sends schema | P3: 1 of 64 off-schema |
| Embedder | the embedder `e-embed-1`, candidate | - | embed service (SVC-EMBED c2875b12 accepts orchestrator) | not in SCREEN yet |
| Qualify | 15 steps incl. pair_gate, determinism, injection, n12 | - | `tools/qualify.py:101-117` | **never run on real weights** |

Shipped serving config (P-PRO6000): `deploy/docker-compose.rtxpro6000.yml:62-85`: vLLM v0.32.0 by digest, judge with
`--chat-template` (developer's file, sha `ae5346...`, D-567), both `--max-num-seqs 16 --enforce-eager`, util 0.40/0.20,
verifier thinking off. The VM driver starts the same flags **minus `--chat-template`** and with the image by tag.

Languages: ja (real text only MedTxt; synthetic hospital JP style), zh-TW (synthetic TW style only), en (TREC, SIGIR,
synthetic `ci-en` NEW-B-42, never run on a model).

## 2. Inventory

Class: CURRENT / STALE / STUB / MISSING as defined in the brief. "Last real-model run" = date + commit, or never.

### 2.1 Figures in docs/VALIDATION.md

| Figure (where) | Last real-model run | Pair / prompt / path | Class | What overtook it | Action | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| N-11 eligible SIGIR pairs lost 4/2/1 of 79 (§3, `eval/parity/replay.json`) | 2026-11-08, commit not recorded (folder committed 0dc8dc7b) | deployed pair, **mlbench prompt**, direct to vLLM, folder chat template; ja/zh-TW are TrialBox translations | STALE | product judge prompt, cascade, clipping, mask, chat template | Retire as the gate figure; re-point N-11 to `judge_bakeoff`/`qualify pair_gate` with the product prompt on SIGIR (en) | A2 (gate), G (run) |
| N-12 9.4 % unadjusted, fail (§3, `eval/trec_ct/results/n12_deployed_2026-11-08.md`) | 2026-11-08 (commit 9673fa69 records it; run commit not recorded) | same as N-11; `deploy/gcp/gpu-pro6000-run.sh` (no `--chat-template`); then **projected** with `hospital_sim project` (stub-measured llm share) | STALE | as above; the projection constant is from stub runs | Retire the projection; measure eligible pairs lost at pair level through the product path (S1 age/sex + product judge on excerpts) | A2, G |
| N-12 adjusted 3.1 % (note) | same | AI-assistant label audit, not a clinician (D-343) | STALE | - | Keep as a note only until a clinician repeats the sample | A2 |
| Pair canary judge 54/54, verifier 49/54, 0 wrong (§3) | 2026-11-08; **newer**: 2026-11-14 commit 02858674 (judge 53-54, verifier 49, 0 decided wrong, public run) | product judge prompt (v4 then; v4 now in PRODUCTION) through the box | CURRENT path, STALE commit and chat template | D-745 mask, chat template | Update VALIDATION to the newest; re-run on the shipped config | G |
| `public_e2e --lang en` with the pair, 98/98, 1,303 s (§3) | 2026-11-08, commit not recorded | product path, folder template | STALE | #582, #567, #570, #572/#573, D-744/D-745; and it has **no truth labels** (all listed patients tier review) | Re-run; state that it is a wiring figure, not accuracy | G |
| Gates table (§1): suites, e2e_simple, public_e2e ja 112/112, complete run 662/662 | stub | stub model by design | STUB (legitimate as wiring) | - | Keep, but the table must say "no model answered" next to each | D |
| Hospital scale table and "18,480 calls, 1.2 GPU hours a year" (§4) | stub | stub; projection | STUB / estimate | measured 50k run (c25cea6b) exists | Replace the call counts with measured ones; mark the projection as a model | G |
| "First hosted-model run" 2026-10-25, 8 of 79 lost (§4) | 2026-10-25 OpenRouter | hosted models, mlbench prompt | STALE (API era) | everything since | Retire from VALIDATION (history only) | A2 |
| MIMIC open-data test (§5) | never with a model; no notes in the demo | - | not a model figure | - | Keep as data-path test; drop from any model matrix | E |
| Complete-run scenario matrix (§7), 2026-11-09 | stub | stub | STUB (legitimate) | - | Keep as wiring | G |

### 2.2 Real-model measurement folders (`docs/plan/measurements/`)

| Item | Commit, date | What it exercises | Class | Overtaken by | Action |
| --- | --- | --- | --- | --- | --- |
| `gpu-run-2026-11-08`, `-08b` (filter_first, canary, public_e2e, swap) | not recorded, 2026-11-08 | mlbench prompt (filter_first); product prompt (canary, public_e2e) | STALE | all fixes since; chat template | Archive as history |
| `g1-2026-11-11`, `g1-2026-11-12` (hospital ja 50k: 464 exclusions, 0 false) | 931a0f79 etc. | product path; prompt version not recorded; generator-template notes, one study (GZQO), 2 note criteria | STALE | #582 (retrieval), #567, #570, D-745 | Re-run on latest; accept only as plumbing |
| `g3-2026-11-13` (5k ja/zh-TW at 1/4/16) | 2b9eec74 (1,026 commits behind HEAD) | throughput + G-4/5/7 | STALE | D-641/D-479, D-645, #582 | Keep throughput as history |
| `g3-50k-2026-11-13` (50k ja/zh-TW at 16) | c25cea6b (636 behind) | product path, 627/628 listed, canary 53/54 | STALE | #582, #567, #570, #576, #578, D-744/5 | Re-run |
| `g7-2026-11-13` (clipped vs whole, 2 synthetic notes) | c25cea6b | product clip + pair | CURRENT path, STALE commit; n=2 | D-745 | Fold into the accuracy set (long-note stratum) |
| `g5-g8-2026-11-14` (G-5 tokens) | 0e9be8a5 | tokenizer counts | CURRENT enough (no answers involved) | chat template could change token counts slightly | Keep |
| `g8-2026-11-14` (2 protocols compiled) | cb850470 (483 behind), before B14 | product compile path, `ir_extract@2` (PRODUCTION env) | STALE | B14 (#586) | Re-run; extend to 20-30 protocols with gold |
| `public-2026-11-14` (lg/batch8 only): public-ja/zh-TW 130/130; MedTxt 2/3; TREC 0/2 | 02858674, before train 15 | public-ja/zh-TW and MedTxt: product path; **TREC: mlbench prompt straight to vLLM** (`tools/scenarios.py:2090`) | public/MedTxt: STALE commit; TREC: STALE path | #567, #570, #572, #573, #576, #578, #582, #586, D-744/5 | Re-run public and MedTxt; retire TREC scenario's private path |

### 2.3 Evaluation tools and data (`eval/*`, `tools/*`)

| Item | Last real-model run | Class | Evidence | Action | Owner |
| --- | --- | --- | --- | --- | --- |
| `tools/mlbench.py` + `eval/criterion_ml` (1,015 SIGIR pairs, en + 3 translations) | 2026-11-08 local pair; earlier OpenRouter | STALE (own prompt, own client, whole note) | `mlbench.py:49-62` | Retire as validation; keep only as model-shopping tool; keep the data (physician labels + evidence ids are useful gold, see §4) | A2 |
| `tools/trec_ct_eval.py` | 2026-11-08 | STALE (mlbench prompt; candidate "negation" amendment "not yet in judge_v3.md") | `trec_ct_eval.py:6,57,295` | Re-point: TREC items through `judge_bakeoff` source `trec_ct` (product prompt) with the S1 age/sex filter first | A2, G |
| `tools/medtxt_eval.py`, `eval/medtxt/results` | 2026-11-07 OpenRouter | STALE (API era, mlbench prompt) | `medtxt_eval.py:63` "Same prompt and client as mlbench" | Retire the figure; the items live on in `judge_bakeoff` source `medtxt` (product prompt) | A2 |
| `tools/trialgpt_compare.py`, `eval/trialgpt_compare/results/raw` | 2026-11-08 | STALE (comparison harness; NCBI prompt vs mlbench prompt) | header | Retire as validation (research history) | A2 |
| `tools/parity_replay.py` | replays 2026-11-08 recordings | STALE (replays a stale path; N-12 via projection) | header lines 74-90 | Re-point to records from the product path | A2 |
| `tools/open_cohorts_eval.py`, `eval/open_cohorts` | 2026-11-05 OpenRouter | STALE | DATASETS, dates | Retire as figures; keep data fetchers (SIGIR full cohort, TREC 2023) as candidate gold | A2 |
| `tools/ad_eval.py`, `eval/ad` (AD slice, router) | 2026-11-05 OpenRouter | STALE | header | Retire figure; AD trials remain a needed stratum (AD-MAB ruleset) | A2 |
| `tools/bakeoff.py`, `bakeoff_live.py`, `eval/bakeoff` | 2026-10-25 hosted | STALE (LLM-030: hosted, cannot choose box weights) | header lines 340-342 | Retire as evidence | A2 |
| `tools/judge_bakeoff.py` | **never on the real pair** | CURRENT path (product judge prompt, `NoteJudge.judge_excerpts`, parser) | header lines 1-20 | This is the right harness; run it via `qualify pair_gate` | G |
| `tools/qualify.py` (`trialbox eval qualify`) | **never on real weights**; `eval/qualification` has no record | CURRENT path; but its `n12` step takes `trec_ct_eval` evidence (stale path) | `qualify.py:101-122,1005-1011` | Run it (G-2). Re-point `n12` evidence to the product path | G (run), A2/D (n12 step) |
| `tools/judge_eval.py` + `tests/fixtures/llm/judge_set.jsonl` | stub only | STUB (legitimate: "wiring test", says so) | header; fixture last changed 2026-10-04 | Keep as wiring; regenerate the set from the current generator (not verified whether it drifted) | A2 |
| `tools/injection_eval.py` + `eval/injection/cases.yaml` (70 cases) | stub only | STUB (legitimate in CI); **no real-model run**; paraphrased plants not built | header | Run through `qualify injection` on the real pair, with the prompt set that will ship | G, A2 |
| `tools/canary.py` / `canary_gate` (54 cases) | 2026-11-14, 02858674 | CURRENT path; STALE commit; smoke test only (0 of ~36 decided gives an upper bound near 8 %) | public report | Keep; do not quote as accuracy | G |
| `tools/cascade_e2e.py` | never with the pair | STUB (in-process gateway over the stub; can point at a real gateway, never done) | header lines 249-265 | Keep for wiring; MIMIC scenario has no notes: drop from model matrix | E, G |
| `tools/public_e2e.py` | 2026-11-08 (en pair); 2026-11-14 (ja/zh-TW in complete run) | CURRENT path, no truth labels | `public_e2e.py:454-470` checks plumbing only | Keep as wiring; add truth if used for accuracy | G |
| `tools/g_probes.py` G-4 decoding | 2026-11-13 c25cea6b | private call by design (D-497: straight to the judge server to switch guided decoding) | lg/batch8 f0d775c0 | Legitimate as a probe; do not count as screening evidence | G |
| G-5 tokens | 0e9be8a5 | CURRENT enough | findings P2 | Keep | G |
| G-7 clipped | c25cea6b | CURRENT path, n=2 | findings P1 | Fold into accuracy set | G, A2 |
| G-8 protocols | cb850470 pre-B14 | STALE | findings §5 | Re-run, then gold | G, A2 |
| NEW-LIFE-18 fixtures `tests/fixtures/public_protocols_g8/` (lg/batch7 befe8e6b) | copies cb850470 output | STALE and self-referential: the model's own pre-B14 answer becomes "the expected class split" | commit message | Do not merge as expected values; make a human-labelled gold instead | G, A2 |
| `tools/chat_template_check.py` (G-1) | **never** | MISSING run | cost table "not in any measurement folder" | Run first | G |
| `tools/bench_embed.py`, `bench_profile.py` | never on the card | MISSING (speed only, no accuracy) | cost table §4.2 | Later | G |
| Retrieval accuracy (which sentence the judge sees) | never | MISSING | `screen_cascade.py:411` hash embedder | Needs a set with evidence-sentence gold (§4) | A2 |
| `eval/chat/results.json` (front desk, 30 x 3) | 2026-11-07 hosted `the judge model` via a one-off survey script; no tool in the repo produces it | STALE (API era, before `classify_intent@3`, before the f-frontdesk build) | `eval/DATASETS.yaml:79-83`; no tool references it | Re-run the 30 requests through the f-frontdesk build on the gateway; write the tool | C2 (front desk), G |
| `tools/phi_synth_eval.py`, `eval/phi_synth` | 2026-11-07 (regex + hosted model) | STALE for masking (before D-744/D-745); no model on the product path | header | Re-measure the mask after D-744/D-745 (lane B2's area) | B2 |
| Chia (`eval/chia`, `tools/chia_routes.py`); `criteria_extract_public` suite | 2026-11-05 OpenRouter; loader disabled | STALE; licence contradiction: `DATASETS.yaml:133` says CC BY 4.0, `:58` says "licence unconfirmed, loader disabled" | DATASETS | Owner/A2 settle licence; then it can feed extraction gold (en only) | A2 |
| `tools/hospital_sim.py` projection constants (llm share, criteria per trial, q) | stub | STALE estimate constants feeding N-12 | `parity_replay.py:81-83` | Replace with measured shares from the latest 50k run | G |
| `deploy/gcp/gpu-pro6000-run.sh` (one-boot script) | 2026-11-08 | STALE: outside `make rehearse` (D-150), no `--chat-template` | cost table row N-12; script line 62-73 | Retire | G |
| `deploy/gcp/complete-run-vm.sh` serving start | every VM run | STALE config: no `--chat-template` (lines 343-362) | compose `rtxpro6000.yml:66` has it | Pass the registry's template, or start from the shipped compose | G |
| `tests/llm` (needs a real model) | not verified | not verified | VALIDATION §1 | - | - |

### 2.4 Product features with no real-model validation (MISSING)

| Feature | Why it matters | Evidence |
| --- | --- | --- |
| Qualification record for any pair; `--promote`; PRODUCTION gateway start | without it a production box routes no model | `registry.yaml` all `candidate`; `eval/qualification` has no record; deep review LLM-005 |
| The hardened prompt set (judge@5, ir_extract@3, chart_facts@2, classify_intent@3, ...) | the injection paragraph never runs in PRODUCTION until qualified | `registry.yaml` `qualification: null`; `prompt_registry.py:381-395` |
| Shipped chat template (developer's) | every VM result used the folder's template | `complete-run-vm.sh:346`; G-1 never run |
| Real zh-TW clinical text, any task | first site (CGRD) is Taiwanese | no such data in repo (cost table §4.1 agrees) |
| Retrieval with the embedder in SCREEN; recall of the deciding sentence per language | decides what the judge sees | #589 not merged; G-11 never |
| Protocol extraction accuracy (ir_extract, concept_map, ie_locate) on real protocols, en/ja/zh-TW | S1 coded exclusions come from it and exclude **without** the two-model rule (`coverage.py` header) | G-8 = 2 protocols, pre-B14, no gold |
| Groups/phases (NEW-LIFE-2) | wave 3, not built | plan 37 |
| Chart facts in zh-TW; "had vs has" status | no status field; matching does not read status (NEW-IR-STATUS, lg/batch8 findings P6) | `sitesetup/store.py` fact columns |
| Certainty (suspected) on chart facts | MT-01: 11 conditions from 疑い mentions, unchanged | public-2026-11-14 report |
| Negation and family history in the **judge** path with real notes | #572/#573 are chart-fact post-processing only | commit stats |
| Era dates (和暦, 民國), lab thresholds in notes, abbreviations, code-mixed zh-TW/en | deep review LLM-006 list | never measured |
| Calibration of confidence floors (0.5, 0.75) | thresholds are constants | LLM-009 |
| Determinism (P4: list hash takes two values) | same input, different list | qualify `determinism` never run |
| Injection on the real pair; paraphrased plants | D-359 | stub only |
| Front desk on the f-frontdesk build; EDC prefill; consent explainer quality | patient-facing or record-writing text | no real-model eval (consent only plumbing in public_e2e stage 7) |
| English hospital (`ci-en`, NEW-B-42) | D-502 | never |

## 3. Retire list

| Retire | Whose | Replace with |
| --- | --- | --- |
| N-11 and N-12 as computed today (mlbench prompt, direct to vLLM, projection) in VALIDATION §3 and `parity_replay` | A2 (gate), lane D (doc) | Pair-level figures from `qualify pair_gate` / `judge_bakeoff` on the shipped config, product prompt, S1 filter first |
| `qualify` `n12` evidence from `tools.trec_ct_eval` | A2/D | evidence produced by the product path |
| `scenario-public-trec` in `tools/scenarios.py:2032-2093` (mlbench straight to the model) and lane G's "corrected" bound against N-12's recorded answers (lg/batch6 73bb84e0) | G | a TREC part that goes through the box (or `judge_bakeoff` trec_ct) with truth from qrels, gate from the decision, not from the old run |
| `deploy/gcp/gpu-pro6000-run.sh` (N-12 one-boot) | G | a driver part on the rehearsed path |
| `scenario-public-mimic` as a model row in D-502 (stub, no notes) | G | none needed for models; keep as data-path test |
| `tools/medtxt_eval.py`, `open_cohorts_eval.py`, `ad_eval.py`, `trialgpt_compare.py`, `bakeoff*.py` results as validation figures | A2 | keep fetchers/data; figures come from `judge_bakeoff` sources |
| `eval/chat/results.json` as front-desk evidence | C2 | a tool that runs the set through the gateway |
| "First hosted-model run" paragraph in VALIDATION §4 | D | history note |
| NEW-LIFE-18 fixtures copied from model output (lg/batch7) as expected values | G | human-labelled extraction gold |
| Every real-model folder before HEAD as "current" evidence (g1, g3, g3-50k, g7, g8, public-2026-11-14, gpu-run-2026-11-08/b) | G | mark superseded in each README; re-run |
| Cost table `d502-cost-table.md` | G | rebuilt on 0c8e1211 with the order in §4 |

## 4. Needed validation data and runs, ranked

Ranked by the brief's order: wrong screening answer on real notes; then losing eligible patients; then data-path
breakage per site format; then capacity; then install/upgrade.

### 4.1 Preconditions before any accuracy run (no cost)

| # | What | Why | Owner |
| --- | --- | --- | --- |
| P1 | Owner decides which prompt set ships: baseline (judge@4 ...) or hardened (judge@5 ...). Rulesets pin judge@4; qualifying @5 triggers re-approval (pin drift) | an accuracy figure on the wrong prompt is waste | owner, A2 |
| P2 | #589 merged (the embedder in SCREEN) or the owner accepts lexicon-only as what ships | today many ja/zh-TW note criteria never reach the judge | A2, C2 |
| P3 | VM servers start with the shipped flags (`--chat-template`, image by digest) | otherwise results do not transfer | G |
| P4 | Every record names prompt id@version and sha per role (LLM-005 item 3) | today no folder says which prompt ran | G, D |
| P5 | Gold sets below exist and are frozen with a sha before the run | no gold, no accuracy | A2 + clinician |

### 4.2 Data sets

| Rank | Data set | Language | Size (minimum) | Labels / gold | Who makes it | Licence | Exists today? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | First-site real notes, criterion x patient items for the site's first studies | zh-TW + en code-mixed (CGRD) | 200 gold exclusions + 200 gold non-exclusions, over >= 10 criterion types | clinician at the site, per item: pass/fail/unknown + the deciding sentence | site clinician / CRC, A2 specifies | site data; never leaves the site | **No.** Must run where the data is (not verified whether the owner's machine can host the pair) |
| 2 | NEW-LLM-6 strata set, ja: MedTxt-CR/RR with criterion-level labels | ja (real) | per stratum ~200 exclusions + ~200 non: negation, suspected, past/treated vs current, family history, long notes over the clip, era dates, lab values in text | corpus tags are a start; "treated" needs relabel (MedTxt tags treated disease "negative", lg/batch8 P6) | A2 + a Japanese clinician to review | CC BY 4.0 | partly (tags only) |
| 3 | NEW-LLM-6 strata set, zh-TW | zh-TW + en code-mix | same strata, ~200/200 each | written by a Taiwanese clinician-style author, **not** the generator's templates | A2 commissions | own | **No public real zh-TW text exists** |
| 4 | NEW-LLM-6 strata set, en | en | ~200/200 per stratum | TREC CT 2021/22 qrels (pair level, noisy) + SIGIR physician criterion labels with evidence sentence ids (`eval/criterion_ml`) | A2; a clinician re-audits a TREC sample (D-343) | NIST / public domain | yes (labels); product-path answers no |
| 5 | Eligible-patient loss set (pair level): TREC eligible pairs (1,200) + SIGIR eligible pairs (79+) through S1 age/sex filter then product judge | en | existing 1,700 pairs | qrels | A2 builds the item builder on the product path | as above | data yes, path no |
| 6 | Protocol extraction gold: criterion boundaries, class (structured/note/mixed/human), logic, concepts, groups/phases | en (CT.gov), ja (jRCT), zh-TW (Taiwan protocols) | 10 protocols per language to start (~300 criteria), incl. the 8 committed rulesets' sources and NCT02629159, NCT03887455 | human labels | A2 + a clinical research coordinator | CT.gov public; jRCT public (licence not verified); zh-TW source not verified | **No** |
| 7 | Coded mapping gold for the site's local codes (NHI local, 保険病名) | zh-TW, ja | the site's top codes by volume | mapping labels | E, A2 | site | No (R5 work) |
| 8 | Retrieval gold: the deciding sentence per item | all three | reuse rows 2-5 (each item carries its evidence sentence) | from the same labelling | A2 | as rows 2-5 | SIGIR en only |
| 9 | Chart facts gold | ja (MedTxt), zh-TW (row 3 charts), en | ~150 charts per language | per mention: has / had / denied / suspected / relative | A2 | as rows 2-3 | ja tags only |
| 10 | Injection: `eval/injection/cases.yaml` + 30 paraphrased plants per language (NEW-LLM-11) | all three | 70 + 90 | facts unchanged | A2 | own | 70 yes, paraphrases no |
| 11 | Front desk: 30 requests x 3 languages + paraphrases | all three | 90+ | expected tool call | C2 | own | yes (needs a tool) |
| 12 | Synthetic hospital (planted truth), 50k ja/zh-TW, 5k en | all three | as built | generator truth | B2 | generated | yes: plumbing and capacity only, not accuracy |

### 4.3 Runs on the GPU VM that prove it (in this order)

| Order | Run | Proves | Gate |
| --- | --- | --- | --- |
| 1 | G-1 chat template check on the shipped template | that VM results transfer to the box | identical, else everything after uses the developer file |
| 2 | `trialbox eval qualify --profile rtxpro6000` with real pins (G-2), shipped compose, the chosen prompt set, `pair_gate` sources = rows 2-5 (+ synthetic), `determinism`, `injection` (row 10), `schema`, `longest_prompt` | the pair answers safely per language and stratum; a record exists so PRODUCTION routes | wrong exclusions <= 2 % with upper 95 % bound reported per language and stratum; 0 changed exclusions on repeat; 0 changed facts on attacks |
| 3 | Calibration table from step 2's answers (10 bins per model and language) | the floors 0.5 / 0.75 mean something | floors chosen from it and recorded |
| 4 | Eligible-loss run (row 5) through S1 + product judge | losing eligible patients | N-12 recomputed on the product path, unadjusted |
| 5 | G-8 on row 6's protocols, after B14 | extraction and compile, and that nothing crashes | per-criterion class agreement and logic agreement with gold, reported |
| 6 | Chart scenarios on row 9 (MedTxt + zh-TW charts) | negation / family history / certainty / had-vs-has | 0 proposed facts on denials and relatives |
| 7 | Hospital 50k ja/zh-TW and 5k en on the latest tree | data path and capacity at size | as today's checks |
| 8 | Front desk set (row 11) on f-frontdesk | intake routing | pass rate per language |
| 9 | G-3 throughput curve, 500k | capacity | after accuracy, not before |
| On site | Row 1 on the site's box (or the owner's machine) | the top risk itself | as step 2 |

## 5. What lane G got wrong (blunt)

1. **It costed the wrong tree.** The table reads "a local scratch merge of origin/train/16 (633993ca) and lg/batch6"
   and states D-744 and D-745 are in neither train 16 nor train 17. Both are on `0c8e1211` (f641b879 #599, 4150aa8f
   #598). Lane G's base is 228 commits behind the latest tree.
2. **It plans to pay for paths that are not the product.** N-12 "old one-boot script" (no chat template, mlbench
   prompt), `scenario-public-trec` (its own report says "an evaluation path, not the box"), N-11 on mlbench with
   translated notes, MedTxt eval on mlbench, and MIMIC on the stub (no notes, so a model can prove nothing there).
3. **Every VM run used a serving config that does not ship.** `complete-run-vm.sh` never passes `--chat-template`.
   G-1, the check that would show whether this matters, has never been run, yet it is costed as a "repeat".
4. **It moved the goalposts.** After TREC lost 12 of 50 eligible pairs and MedTxt proposed facts on negative
   mentions, lane G rewrote the checks (lg/batch6 73bb84e0) so TREC passes when it is no worse than the 2026-11-08
   recordings (17.4 % lost raw, 24 % on these pairs) and MedTxt skips "treated" mentions. A failing validation became
   a passing regression check against a failing, non-product baseline.
5. **Self-referential gold.** NEW-LIFE-18 (lg/batch7) commits the model's own pre-B14 compile as the expected output.
6. **Volume over truth.** About US$100 of the US$145 plan goes to throughput curves and 500k runs (L4, L6-L12), while
   the accuracy set (NEW-LLM-6), the qualify record (G-2) and injection have no cost and no part. "Every data set in
   three languages" counted rows, not questions answered: `public-zh-TW` is the zh-TW console over en+ja notes and is
   counted as zh-TW coverage.
7. **"No model" was never named as the blocker.** No pair is qualified; production serves unqualified-nothing or the
   old prompts. Lane G's queue puts R2 first but the cost table treats qualify as "unknown, inside R2".
8. **Records do not say which prompt ran.** Open since the 2026-11-12 deep review (LLM-005), still true in every
   folder (no `judge@N` in any report.json checked).
9. **Measuring before the screening path settles.** NEW-LLM-2's first step changed which criteria reach the judge;
   #589 is still open. A D-502 run now measures a temporary retrieval state.

## 6. Open questions

1. Which prompt set ships: baseline (@4/@2/@1) or hardened (@5/@3/@2)? Not decided anywhere I found.
2. Will #589 (the embedder in SCREEN) land before the matrix? If not, is lexicon-only screening what ships?
3. Where can the first site's gold be run? Its notes never leave the site; the GPU is on the cloud VM. Not verified.
4. Is there any licensed real zh-TW clinical text (public or under agreement)? None found in the repo.
5. Chia licence: `eval/DATASETS.yaml` contradicts itself (lines 58 and 133).
6. Does the chat template change answers? Unknown until G-1 runs.
7. Which commit ran the 2026-11-08 figures? Not recorded in the files.
8. Do the TREC losses fall on criteria the box's S1 filter decides first (2 of 12 are age lines, lg/batch8 P7)? Only a
   product-path run answers this.
9. `tests/llm` (real-model tests): when last run, not verified.
10. Does the chart-fact model need a had/has status field (NEW-IR-STATUS)? A product question for A2 and E.
