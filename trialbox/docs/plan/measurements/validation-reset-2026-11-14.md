# Lane G validation reset (2026-11-14)

For the owner. One plan from three read-only audits (models, data, lane G's own machinery), each claim checked again
on the latest tree: `origin/train/17` at `0c8e1211` (it holds master `5ff9f813`, train 16 and train 17). A claim I
could not check is marked **not verified**. Where the audits disagreed, section 0 says which is right and why.

The owner's order: validate the latest repo, as shipped, with the real models. Old things are understood, then
stopped and removed.

**The short answer.** No figure the repo quotes today was measured on what ships. Every paid run so far served the
models with lane G's own script (not the shipped compose), ran the box inside one Python process with a stand-in
embedder, and ran on a commit that lacks trains 15 to 17. No model pair has ever been qualified, so a production box
today serves only the old baseline prompts. This branch stops paying for the old path: the driver now refuses such a
launch, every old results folder says SUPERSEDED, and two old one-boot scripts are gone. The next paid run must be
the shipped box installed from the signed bundle (Stage 0).

## 0. Disagreements settled

| Question | Audit figures | What the tree says | Verdict |
| --- | --- | --- | --- |
| Lane G's VM spend so far | US$5.48 (cost table, the owner's figure), US$20.22 (cost table note), about US$59 (audit C) | The results folders record (VM hours x US$2.74 an hour spot): G1 2026-11-11 about 6 h + 5.5 h = US$31.5; G1 2026-11-12 attempt 1 US$3.50 (hours not kept) + attempt 2 1.33 h US$3.70; g3 1.99 h US$5.45; g3-50k 2.0 h US$5.48; g7 0.39 h US$1.07; g5-g8 0.8 h US$2.19; g8 0.2 h US$0.55; public 2.0 h US$5.48 (folder on `lg/batch6` only). Recorded hours 20.21 h x 2.74 = US$55.38, plus the US$3.50 with no hours = **US$58.88**; the folders' own rounded figures add to **US$58.92**. | **About US$59** is right for lane G (2026-11-11 to 11-14). US$20.22 is only the six results from 2026-11-13 on; US$5.48 is the public run alone. Not counted: the 2026-11-08 runs before lane G existed (runbook 11 and `real-data-e2e-report.md` record about US$1.50 + US$2.30 + US$4.9). |
| Did G-1 (chat template) ever run? | A and the cost table: never. C: ran 2026-11-12, failed. | `g1-2026-11-12/parts/chat-template.json`: run `20261112T165042Z-931a0f79`, 3 of 5 checks. The template texts differ by hash (`ae53464b...` passed, `94899c0f...` the folder's) but give identical token ids on 20 prompts; the judge server, started **without** `--chat-template`, renders one token more than the reference tokenizer at the end of every system turn (5 prompts listed, first difference at token 22). | **C is right.** G-1 ran and failed. It did not run on the shipped serving, so whether the shipped template changes answers is **not known**. |
| Are D-744 / D-745 in train 17? | Cost table: no. A, B, C: yes. | D-744 (#598, `4150aa8f`) and D-745 (#599, `f641b879`) are ancestors of `0c8e1211`. | **Yes.** The cost table read an older train 17. |
| Was N-11 a card run? | A: yes, 2026-11-08, bench prompt. B: recorded answers, not a card run. | Commit `ac5bbdbb` (2026-11-08): "SIGIR N-11 on the card in EN, JA, zh-TW", through `tools/trialgpt_compare.py`, which sends `tools/mlbench.py`'s prompt straight to the servers. `parity_replay` replays those recordings. | **A is right.** A card run, but on the bench prompt, not the product path. |

## 1. What ships on the latest tree

| Thing | Shipped (latest tree) | Evidence |
| --- | --- | --- |
| Judge | Gemma 4 26B-A4B NVFP4, build `gemma-4-26b-a4b-it-rtxpro6000`, alias `j-workhorse`, status **candidate**; expected revision `a19cfe00`, manifest `5e5bef7a...` | `models/registry.yaml:116-143` |
| Verifier | Qwen3.5-9B AWQ 4-bit, build `qwen3.5-9b-rtxpro6000`, alias `v-verifier`, status **candidate**, thinking off; revision `e4d2d39c`, manifest `869b5253...` | `models/registry.yaml:146-172` |
| Serving | vLLM `v0.32.0@sha256:befccf0e...`; judge with `--chat-template` (the developer's file, sha256 `ae53464b...`, D-392, D-567); 32k context, 16 sequences, eager, 0.40 / 0.20 of the card, host memory cap 48g each, behind model-guard | `deploy/docker-compose.rtxpro6000.yml:32,58-86`; `models/registry.yaml:133-138` |
| Qualification | No real build is champion (the only champions are the stubs). `eval/qualification/` holds no record. `trialbox eval qualify` has never run on real weights. | `models/registry.yaml:48-95`; `ls eval/qualification` |
| Prompts served in PRODUCTION | The newest version with a qualification: baseline imports `judge@4`, `ir_extract@2`, `chart_facts@1`, `concept_map@1`, `ie_locate@1`, `classify_intent@2`, `crf_prefill@1`, `draft_doc@1`, `consent_*@1`, `assist@1`, `profile_summary@1`. Rulesets pin `judge_v4`. | `libs/tb_llm/prompt_registry.py:381-395`; `libs/tb_llm/prompts/registry.yaml`; `rulesets/*/manifest.yaml` |
| Prompts awaiting qualification | 13 versions with the "text is data" injection paragraph (T-606, D-359): `judge@5`, `ir_extract@3`, `chart_facts@2`, `concept_map@2`, `ie_locate@2`, `classify_intent@3`, `crf_prefill@2`, `draft_doc@2`, `consent_*@2` (3), `assist@2`, `profile_summary@2`: all `qualification: null`, refused in PRODUCTION | `libs/tb_llm/prompts/registry.yaml:157-279` |
| Cascade | S1 coded filters (no model) -> S2 lexicon -> S2b retrieval -> S3 judge + verifier through the gateway; a note excludes only when both say fail. Since #582 (NEW-LLM-2) a note criterion with no lexicon term and only the hash embedder is "not evaluated" and never reaches the judge. | `services/matching/cascade/engine.py:128-132,356-363` |
| Embedder | `embed-service` (CPU, cap 4g) ships; the embed service accepts the orchestrator (#596, `c2875b12`). SCREEN itself still ranks with `HashEmbedder`. | `deploy/docker-compose.yml:170-191`; `services/orchestrator/scenarios/screen_cascade.py:411,440` |
| #589 (SCREEN uses the embed service) | **Not merged** on train 17 (no `(#589)` merge in its log). **Owner's ruling: merged before the accuracy runs.** | `git log origin/train/17` |
| Masking | Note mask v3: D-744 (English phones, #598) and D-745 (birth dates, addresses, chart labels, #599) | `docs/decisions/D-744*`, `D-745*` |
| Canary | 54 one-sentence cases (18 per language) at start and before each night | `services/orchestrator/canary/judge_canary.jsonl` |
| Vendor serving record | `deploy/measured/serving_config.rtxpro6000.json`, captured 2026-11-08 by the one-boot script: image by tag, no chat template. `install.sh` accepts it; the registry's expected manifests cite it. | file; `install.sh:422` |

**Owner's rulings of 2026-11-14 (decided, not open):** (1) the prompt set that ships is **v5** (`judge@5` and the
other T-606 versions); the first real-model run on the shipped box qualifies v5. (2) **#589** is merged before the
accuracy runs. (3) **zh-TW gold**: the owner asks the CGRD session and the integrator to arrange real hospital cases
rewritten by clinicians. Lane G never handles source records; only rewritten, non-identifying text and labels may
reach the repo (standing rule: synthetic or public data only). The route is to be confirmed by the integrator.

## 2. What lane G's runs tested, against the shipped box

| # | Shipped box | Lane G's VM runs (`deploy/gcp/complete-run-vm.sh`, `tools/complete_run.py`) | Evidence |
| --- | --- | --- | --- |
| D1 | judge with `--chat-template` (developer's file) | no `--chat-template`: the folder's template | `complete-run-vm.sh:343-362`; G-1 failed (section 0) |
| D2 | vLLM image by digest | `vllm/vllm-openai:v0.32.0` by tag | `complete-run-vm.sh:144` |
| D3 | weights from pinned folders, manifest checked by `pin_model` | Hugging Face cache on a kept disk; only "the folder exists" | `complete-run-vm.sh:320-323` |
| D4 | model-guard in front of both servers | nginx adding the key | `complete-run-vm.sh:273-289` |
| D5 | every service a container with a memory cap | one Python process per part (in-process gateway, orchestrator, lake), no caps | `deploy/docker-compose.yml:17-191`; `tools/scenarios.py:154-201` |
| D6 | the embed service (after #589, in SCREEN) | `HashEmbedder` | `tests/inproc_box.py:23,209`; `tools/scenarios.py:530-537` |
| D7 | `TB_ENV=PRODUCTION` everywhere | process `TB_ENV=DEV`, the in-process gateway PRODUCTION | `complete-run-vm.sh:510`; `tools/scenarios.py:283` |
| D8 | the db image (PostgreSQL 16 with its extensions) | apt PostgreSQL on Ubuntu 24.04 (equality **not verified**) | `complete-run-vm.sh:452` |
| D9 | installed from the signed bundle by the installer and wizard | `git archive` of the operator's HEAD | `complete-run.sh` launch block |
| D10 | prompts gated by qualification; v5 to ship | PRODUCTION's baseline prompts (v4 ...); v5 never run on real models | section 1 |
| D11 | TREC as a product site would screen it | `scenario-public-trec`: the bench prompt straight to the servers | `tools/scenarios.py:2030-2093` |
| D12 | (no MIMIC part on a box) | `scenario-public-mimic`: the in-process stub; the MIMIC demo has no notes | `tools/scenarios.py:1873-1934` |

## 3. Every existing result

"Behind" counts commits to `0c8e1211`. Every commit below lacks all of: #567, #570, #576, #578, #582 (train 15);
#586, #572, #573, #591 (train 16); #596, #598, #599, #595 (train 17). Checked with `git merge-base --is-ancestor`.

| Result | Date, commit | Path tested | Verdict now | What overtook it |
| --- | --- | --- | --- | --- |
| N-11, SIGIR pairs lost 4/2/1 of 79 (VALIDATION §3) | 2026-11-08, `ac5bbdbb` | bench prompt straight to the servers; ja/zh-TW are translations | not the product path | product prompt, cascade, mask, chat template |
| N-12, TREC 9.4 % unadjusted, fail (VALIDATION §3) | 2026-11-08, commit not recorded | bench prompt; one-boot script; projected with a stub-derived share | not the product path | as above |
| Canary judge 54/54, verifier 49/54 (VALIDATION §3) | 2026-11-08 | product judge prompt of the day; one-boot serving | stale | D1-D10; newer: 53/54 pair on `c25cea6b` and the public run on `02858674` |
| `public_e2e --lang en` 98/98 in 1,303 s (VALIDATION §3) | 2026-11-08 | product path of the day; no truth labels (plumbing) | stale | all trains since |
| `gpu-run-2026-11-08`, `-08b` | 2026-11-08 | fit, canary, filter-first (bench prompt), swap | stale / not product | as above |
| `g1-2026-11-11` (50k ja hospital) | 2026-11-11, `986d91c9`, never on master (1,986 behind) | in-process box, lane G serving | stale | D1-D10, all trains |
| `g1-2026-11-12` (G-1 failed, G-3 5k) | 2026-11-12, `931a0f79`, never on master (1,314 behind) | same | stale; **G-1 finding open** | same |
| `g3-2026-11-13` (5k at 1/4/16) | 2026-11-13, `2b9eec74` (1,026 behind) | same | stale | same |
| `g3-50k-2026-11-13` (50k at 16; 463 exclusions, 0 false, on template notes) | 2026-11-13, `c25cea6b` (636 behind) | same; hash embedder; uncapped | stale; never capacity, never accuracy | same |
| `g7-2026-11-13` (clipped vs whole, 2 notes) | 2026-11-13, `c25cea6b` | lane G's own verdict mapping | stale | same; D-745 |
| `g5-g8-2026-11-14` (tokens; 2 protocols) | 2026-11-14, `0e9be8a5` (487 behind) | lane G serving | stale | same |
| `g8-2026-11-14` (2 protocols, B14) | 2026-11-14, `cb850470` (483 behind) | compiler through the in-process gateway | stale | #586 fixes B14 |
| `public-2026-11-14` (`lg/batch6` only) | 2026-11-14, `02858674` (229 behind) | public ja/zh-TW (product path of the day), MedTxt, TREC (bench prompt) | stale; TREC not product | all trains since |
| Stub gates (suites, `e2e_simple`, complete run 662/662, walk) | various | stub by design | current as wiring, never model evidence | - |

Each results folder now has `SUPERSEDED.md` and a first line in its README saying so.

## 4. Retired now, and to retire next

### 4.1 Retired on this branch (`claude/lane-g-validation-reset`)

| What | How |
| --- | --- |
| Paid launches that are not product evidence | `complete-run.sh` refuses (exit 8, after the read-only checks, before any upload or start) when the VM script's serving differs from the shipped compose (chat template, image digest, weight revisions) or the plan holds `scenario-public-trec` / `scenario-public-mimic` (`tools/product_evidence.py`). `--not-product-evidence` launches anyway; plan.json, the run report and the results reader then list every reason. Today every launch is refused: the VM script differs in all three. |
| The claim that `capacity_inputs.json` feeds T-667, T-637, T-734 | removed from `deploy/gcp/results_report.py`; its output now carries `product_evidence` |
| `deploy/gcp/gpu-fit-test.sh` | deleted (one-boot fit test of 2026-11-08; its `fit.json` stays) |
| `deploy/gcp/gpu-swap-run.sh`, `tools/wake_check.py` | deleted (one-boot swap run; the product's swap is untouched) |
| `deploy/gcp/gpu-pro6000-run.sh` | kept with a "not for validation" banner (see 4.2) |
| Estimate constants (`HOSPITAL_MEASURED`, `PUBLIC_SECONDS`, the scenario seconds) | labelled "cost estimate only, never capacity or product evidence" |
| Nine results folders, the lane G plan of 2026-11-12, the findings note, the 2026-11-08 real-data notes | marked SUPERSEDED |
| Runbook 11's rows that present the 2026-11-08 runs and the 5.0 h hospital part as current | reworded; a reset paragraph at the top |

No test was removed. Two hygiene tests drop the deleted scripts from their lists and keep checking the others; the
direct-model-call allow-list drops the deleted script's entry. The rehearsal and the driver's plumbing tests now set
`TB_NOT_PRODUCT_EVIDENCE=1`, since they test plumbing.

### 4.2 To retire next (needs another lane, or a replacement first)

| What | Why it cannot go now | Owner |
| --- | --- | --- |
| The VM script's own serving block (`complete-run-vm.sh:266-367`) and the in-process box on the card | it is the only path the driver has; replace with the installed compose on the VM (Stage 0) | G (driver), D (compose) |
| `scenario-public-trec`, `scenario-public-mimic` | the rehearsal case `run-a` runs `scenario-public-trec` (`tests/rehearsal/rehearse.sh:61`, `check.py:41,210`), and `tests/unit/test_cloud_run.py:185-198` tests its data fetch; refused for paid runs now. Replace TREC with a TREC site screened through SCREEN | G with A2 |
| `deploy/gcp/gpu-pro6000-run.sh` | it took the vendor record that `install.sh` and `models/registry.yaml` cite; `docker-compose.rtxpro6000.yml:20` and `deploy/measured/README.md:10` name it | D (record), G (capture on the installed box) |
| `deploy/gcp/gpu-sim-startup.sh` (the VM's usual startup script: starts a 32 GB-capped pair at every boot) | `complete-run.sh:344` puts it back after every run; `test_g1_hardening_2026_11_13.py:331` checks that | G |
| `capture-serving-config.sh` | `install.sh:422` names it as how a site's record is taken | D |
| `tools/trec_ct_eval.py` as the `n12` evidence of `trialbox eval qualify` | `tools/qualify.py:119` | A2, D |
| `lg/batch6` commit `73bb84e0` (TREC and MedTxt checks loosened after they failed) and `lg/batch7`'s G-8 fixtures copied from model output | not merged; must not reach a train as they are | G (withdraw), A2 (review any check change) |
| The D-502 cost table (scratchpad, not in the repo) | built on an old train 17 and on paths retired above | G (withdrawn; this plan replaces it) |

### 4.3 Other lanes' files that quote stale figures as current (not changed here)

| File:line | What is wrong | Owner |
| --- | --- | --- |
| `docs/VALIDATION.md:69` | N-11 4/2/1: bench prompt, not the product path | integrator (doc), A2 (gate) |
| `docs/VALIDATION.md:70` | N-12 9.4 %: bench prompt, one-boot script | integrator, A2 |
| `docs/VALIDATION.md:71-72` | canary 54/54 and `public_e2e` 98/98: 2026-11-08 serving, before every train | integrator |
| `docs/VALIDATION.md:124` | "First hosted-model run" 2026-10-25: API era | integrator |
| `deploy/measured/serving_config.rtxpro6000.json` | the vendor record lacks the chat template and the image digest the compose ships | D |
| `deploy/measured/README.md:10`, `deploy/docker-compose.rtxpro6000.yml:20` | name the one-boot script as where the record comes from | D |
| `tools/qualify.py:119` | `n12` evidence from the bench-prompt path | A2, D |
| `eval/trec_ct/results/n12_deployed_2026-11-08.md`, `eval/parity/gpu-run-2026-11-08-pro6000/README.md` | no "not the product path" note | A2 |
| `docs/plan/37-remaining-work-split.md:99,102,104,109,136,138` | D-502 cost table and matrix as planned; NEW-LIFE-18 "from the G-8 compiles"; validation figures N-12/TREC/MedTxt as the yardstick | integrator |
| `docs/plan/gpu-ledger.md:38` | "Spot VM: 0 runs, 0 cost": about US$59 was spent | integrator |
| `docs/plan/32-gcp-test-plan.md:67,85,92` | G-02 counts TREC and MIMIC as runs with the pair; G-15 names the deleted scripts; G-22 a 500k screen-only run on the harness | integrator, G |
| `docs/decisions/D-468-g1-hospital-parts-no-preemption.md:15-27` | premise "a hospital part takes 5 h" from `g1-2026-11-11` | integrator |

## 5. The validation the repo needs, ranked by risk

Ranked as the owner asked: a wrong screening answer on a real hospital's notes; losing eligible patients; a data
path breaking per site format; capacity; install and upgrade. **Cost:** only a measured or driver figure is given;
the spot VM is US$2.74 an hour (results folders). No stage below has a driver yet, so **none is costed yet**.

| Stage | What it proves | Preconditions | Lane G builds (no cost) | The paid run | Cost |
| --- | --- | --- | --- | --- | --- |
| **0. Shipped box on the VM** | the shipped box serves the shipped pair; the first qualification record, so PRODUCTION serves v5 | signed bundle from a pushed integration head (R2); vLLM waiver (lane D); `box-install-run.sh` fixed (`--answers`, a job API) and given a cloud driver; #589 merged (ruling 2) | box-install driver and `make rehearse-box` on the exact bundle (other worker, `lg/batch8`); the record of what ran (section 6) | bundle -> installer -> wizard -> `pin_model` -> serving record taken again -> **G-1 on the shipped template** -> pair canary -> `trialbox eval qualify` with v5 (ruling 1) -> promote -> `doctor` | not yet costed |
| **1. Accuracy on the product path** | wrong exclusions and lost eligible patients, per language and stratum | Stage 0 passed; gold frozen with a sha | the item builder that turns gold into sites screened by SCREEN; the calibration table; the report per stratum | the accuracy sets below through SCREEN on the installed box; injection (70 cases + paraphrases); TREC eligible-loss through S1 then the pair; protocols with gold (G-8 after B14) | not yet costed |
| **2. Data paths per site format** | each format reads, maps and screens on the installed box | Stage 0; non-circular samples (not TrialBox's own export read back) | parts that drive the installed box's ingest | SS-MIX2, FHIR (TW Core, JP Core), CGRD-style CSV, Excel / Shift_JIS / Big5, REDCap, chart files with Tesseract, `ci-en` (#591), 5,000 each | not yet costed |
| **3. Capacity under production caps** | the night fits; the Linux figure for T-667 | Stage 0; T-692 (ingest memory); for 500k: T-694, T-702, T-703 | parts on the installed box; NEW-PERF-1 from the gateway audit | G-3 at 4, 8, 16 (twice, restart between); G-6 dense night at 50k with backup; G-11 the embed service building the index at 50k; an incremental night; 500k only when it is the real incremental night | not yet costed |
| **4. Outage, upgrade, backup, air-gapped** | the box survives and recovers | job API; a second bundle (N+1) and a bad one | parts for each | G-9 restart and power cycle mid-night (#576's give-up rule); update N -> N+1 and roll back a bad one; G-10 image move; backup and restore at 50k; a night with egress denied | not yet costed |

### 5.1 Gold: what exists, what must be made, by whom

| Set | Language | Exists | Must be made | Who |
| --- | --- | --- | --- | --- |
| Strata set (NEW-LLM-6): negation, family history, past/treated vs current, suspected, long notes over the clip, era dates, labs in text, abbreviations; ~200 gold exclusions + ~200 non-exclusions per stratum | ja | MedTxt-CR/RR text (CC BY 4.0) and certainty tags | criterion-level labels; "treated" relabelled | A2 with a Japanese clinician |
| same | zh-TW | **nothing**: no real zh-TW clinical text in the repo | real cases rewritten by clinicians, non-identifying, with labels (ruling 3); route to be confirmed by the integrator | integrator, CGRD session, A2 |
| same | en | SIGIR physician labels with evidence sentence ids (`eval/criterion_ml`); TREC qrels | strata labels; a clinician re-audit of a TREC sample (D-343) | A2 |
| Eligible-loss set | en | TREC eligible pairs (~1,200) and SIGIR (79+) | an item builder on the product path | A2 (builder), G (run) |
| Protocol extraction gold (boundaries, class, logic, concepts) | en, ja, zh-TW | 2 public protocols, no gold | ~10 protocols per language | A2 with a research coordinator |
| Chart facts gold (has / had / denied / suspected / relative) | ja, zh-TW, en | ja tags only | ~150 charts per language | A2 |
| Injection | all | `eval/injection/cases.yaml` (70) | ~30 paraphrased plants per language | A2 |
| Front desk | all | `eval/chat` (30 x 3, API era) | a tool that runs it through the gateway | C2 |
| Synthetic hospital | ja, zh-TW, en | generator truth | plumbing and capacity only, never accuracy | B2 |

Calibration (the 0.5 and 0.75 floors) comes from Stage 1's answers. Determinism (P4: the list differs between runs)
is a `qualify` step in Stage 0.

## 6. Working rules from now on

1. **One source of code.** Launch only from a pushed integration head (master or the current train) with a passed
   rehearsal of that same commit (`make rehearse`, and `make rehearse-box` once it exists). Never from an `lg/*`
   branch or a scratch merge.
2. **One serving setup.** Models are served only by the installed compose of that bundle. The driver refuses
   anything else (this branch); `--not-product-evidence` is for plumbing runs and marks every result.
3. **Every result names what it ran:** commit, bundle id and sha256, image digests, weight manifests, chat template
   sha256, served prompt id@version per role, embedder build, memory caps. A folder without these is not evidence.
4. **Results expire.** A result is superseded when any of these change after its commit:
   `libs/tb_llm/prompts/registry.yaml` (served versions), `services/matching`, `services/gateway`, `services/guard`,
   `libs/tb_common/phi_guard.py`, `services/criteria_compiler`, `deploy/docker-compose*.yml`, `deploy/images.lock`,
   `models/registry.yaml`. Only non-superseded results may be quoted.
5. **Lane G does not grade itself.** Pass rules are fixed before the run. A check changed after a failed run counts
   only after review by lane A2 (accuracy) or B2 (data).
6. **One test list.** Plan 32's G-01..G-23 and plan v7's G-1..G-11 use the same names for different tests; use plan
   v7's and rename plan 32's.

## 7. Decisions needed from the owner, and asks per lane

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | The budget basis: about US$59 spent by lane G, not US$5.48 | Count US$58.92 as spent; set the remaining budget from that |
| 2 | No paid run until Stage 0 can run (bundle, waiver, box driver) | Yes: the harness has nothing left to prove on a GPU |
| 3 | The 2026-11-17 demo (stub model) | Show it, with a visible note that the answers are not the model's |
| 4 | Whether matching should read a condition's clinical status and abatement (today it does not) | Ask lane A2 for a ruling before the strata set is labelled |
| 5 | Chia's licence (`eval/DATASETS.yaml` states two different ones) | Lane A2 settles it before Chia feeds extraction gold |

| Lane | Asks |
| --- | --- |
| A2 | merge #589 (ruling 2); the NEW-LLM-6 gold per language and stratum (ja, en; zh-TW once ruling 3's text arrives); extraction gold; review every check lane G changed after a failure (`73bb84e0`); re-point `qualify`'s `n12` evidence |
| B2 | the strata generators only for plumbing; non-circular site-format samples; mask measured on real-model traffic after Stage 0 |
| C2 | the front-desk set through the gateway |
| D | `--answers` (or another way) for the wizard in `box-install.sh`; a job API for SCREEN; the vLLM waiver; re-take the vendor serving record from the installed compose and drop the one-boot script from its provenance |
| E | REDCap and CGRD formats as Stage 2 samples |
| Integrator | update VALIDATION §3 and §4, plan 37, the GPU ledger and D-468 (section 4.3); confirm the zh-TW route (ruling 3); keep `lg/batch6`'s `73bb84e0` and `lg/batch7`'s fixtures off the trains |
| G | Stage 0's driver with the other worker; withdraw the cost table; retire 4.2's items as their replacements land |

## 8. What lane G got wrong

1. It paid to test its own copy of the box, not the shipped one: its own vLLM servers, one Python process, the stand-in embedder.
2. It found the chat-template difference (G-1, 2026-11-12) and kept running without the shipped template; its cost table then said G-1 had never run.
3. It kept paths that are not the product in its plan: TREC on the bench prompt, MIMIC on the stub, N-12 on a one-boot script.
4. It loosened two failing checks after they failed (`73bb84e0`) and froze a failing compile as fixtures (`lg/batch7`).
5. It costed volume (500k, throughput curves, the same data once per console language) and gave the accuracy set and qualification no row.
6. It counted results from branches that never reached master, and costed the plan on an old train 17.
7. It reported US$5.48 spent when its own folders record about US$59, and let `capacity_inputs.json` claim to feed the capacity statement.
8. It never named the real blocker: no pair has ever been qualified, so a production box serves only the old prompts.
