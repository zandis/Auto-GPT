# Audit C: lane G's machinery and records against the latest tree (2026-11-14)

Read-only audit. Latest tree: `origin/train/17` = `0c8e1211` (contains master `5ff9f813` = train 15, train 16, train
17). Lane G branches read with `git show`: `lg/batch6` (head now `ab6f5213`; the brief's `73bb84e0` is three commits
back), `lg/batch7` (`befe8e6b`), `lg/batch8` (now `40c5e5c6`, which merges `origin/train/17`: the only lane G branch
on the latest tree; nothing has run on it). Nothing was started, nothing paid, no file in any worktree changed.

## 0. The answer in five lines

1. **Lane G validates its own harness, not the shipped box.** Every paid run so far started two vLLM containers from
   lane G's own VM script, ran an in-process copy of the box inside one Python process (`tools/complete_run.py`), and
   graded it with lane G's own checks. No run has ever used the bundle, the installer, the compose stack, the
   memory caps, model-guard, the production embedder, `pin_model`, `trialbox eval qualify` or the pinned chat template.
2. **The model server lane G runs is not the one the box ships.** The shipped compose starts the judge with the
   developer's chat template (`--chat-template`, D-392, since 2026-11-11) and the vLLM image by digest. Lane G's
   script passes neither. Lane G's own G-1 test (2026-11-12) found the server's rendering differs on every prompt with
   a system turn, which is every judge call; the plan's rule says the accuracy runs must then be repeated with the
   shipped template. Lane G kept running without it.
3. **Every real-model result is of an old commit.** The newest run (public data, `02858674`, 2026-11-14 05:05) lacks all
   of train 15 (#567, #570, #576, #582 and 23 more), train 16 (#586 B14, #572, #573, #591 ...) and train 17 (#598 D-744,
   #599 D-745, #596, #595). All nine results folders say FAILED.
4. **Some "real-model" numbers do not touch the product path at all.** TREC (the scenario and N-12) uses the bench
   prompt of `tools/mlbench.py` straight to the model servers: no gateway, no product judge prompt, no cascade, no
   two-model decision. MIMIC runs on the stub. The hospital screen uses the hash embedder, which the product (since
   #582) treats as "no retrieval".
5. **To make every paid run a run of the product:** stop the private serving block and the in-process box as
   validation; build the signed bundle from the integration head; install it on the VM with the shipped installer and
   compose; qualify and promote with `trialbox eval qualify`; drive the installed box only through its own interfaces;
   date-stamp and expire every result by commit, bundle and served prompt versions.

## 1. What the latest repo does here (map)

### 1.1 What the shipped box runs (latest tree)

| Thing | Shipped box (latest tree) | Evidence |
| --- | --- | --- |
| Judge | `llm-service`: vLLM `v0.32.0@sha256:befccf0e...`, `--model /models/<judge>` (pinned build `<judge profile>`, NVFP4, revision `a19cfe00`, manifest `5e5bef7a...`), `--chat-template` developer file sha256 `ae53464b...`, 32k, 16 seqs, eager, 0.40, mem cap 48g, behind model-guard | `deploy/docker-compose.rtxpro6000.yml:52-63`, `models/registry.yaml:116-143`, `deploy/images.lock:49-87` |
| Verifier | `llm-verifier`: same image, `/models/<verifier>` (revision `e4d2d39c`, manifest `869b5253...`), thinking off, 0.20, cap 48g | compose `:65-78`, registry `:146-172` |
| Gateway | `gateway` container, `TB_PROFILE P-PRO6000`, `TB_MODEL_SWAP off`, mem 2g | compose `:80-83`, `deploy/docker-compose.yml:317` |
| Orchestrator | own container, `TB_SCREEN_LLM_CONCURRENCY = JUDGE_MAX_SEQS (16)`, mem 4g | compose `:85-88` |
| Prompts in PRODUCTION | newest **qualified** version only: judge **v4**, chart_facts **v1**, ir_extract **v2**, concept_map v1. All T-606 versions (judge v5, chart_facts v2, ir_extract v3 and nine more, with the "text is data" injection paragraph) have `qualification: null` and are refused in PRODUCTION. No qualification record exists. | `libs/tb_llm/prompts/registry.yaml:120-137, 157-269`; `libs/tb_llm/prompt_registry.py:382-394, 521-545` |
| Embedder | `embed-service` image `trialbox-embed:1.0.0` (CPU), pinned weights at `/models/embedder`, lake `TB_LAKE_EMBEDDER: http` | `deploy/docker-compose.yml:170-191` |
| Screening without a semantic embedder | since #582 (train 15, NEW-LLM-2): a note criterion with no lexicon term and only the hash embedder is "not evaluated" | `services/matching/cascade/engine.py:130-132, 358-362, 681-688` |
| Install | bundle -> `deploy/install.sh` / `box-install.sh` -> wizard -> `pin_model --install` -> `trialbox eval qualify` -> promote | plan v7 §7.1 G-2; `tools/trialbox/__main__.py:38-41` |
| Vendor serving record | `deploy/measured/serving_config.rtxpro6000.json`, captured **2026-11-08** by `gpu-pro6000-run.sh`: no chat template, image by tag only. It is the record `install.sh` accepts. | file, commit `05da2fda` |

### 1.2 What lane G's driver runs on the VM (identical on `lg/batch6` and in the latest tree for the serving part)

| Driver part | What it actually runs | Code path |
| --- | --- | --- |
| Code to the VM | `git archive HEAD` of whatever checkout the operator stands in; sha256 checked on the VM. No check that HEAD is on master or a train, pushed, or rehearsed. | `deploy/gcp/complete-run.sh:809-818` (batch6) |
| Model serving | its own `docker run` of `vllm/vllm-openai:v0.32.0` (tag, no digest), HF repo ids from a kept disk's HF cache (revision not checked), **no `--chat-template`**, `--api-key`, nginx in front (no model-guard), no host memory cap | `complete-run-vm.sh:147, 266-367` |
| Weights check | only "the folder exists"; the captured serving record is not compared with `registry.yaml` `expected`; published records say `weight_pins: synthetic`; `README`: "Card: not in the folder" | `complete-run-vm.sh:323-325`; `tools/serving_config.py:304-344`; `tools/scenarios.py:204-214` |
| The box | one Python process per part: in-process gateway (`TestClient(create_app(...))`), in-process orchestrator and lake, apt PostgreSQL, **hash embedder**, process `TB_ENV=DEV` with the gateway's env set to PRODUCTION; no containers, no caps | `tools/scenarios.py:154-201, 278-322`; `tools/e2e_simple.py:709`; `complete-run-vm.sh:538-544` |
| `install` part | reads two serving records and `tiers.resolve`; installs nothing | `tools/complete_run.py` `part_install` |
| `hospital-<lang>` | `e2e_simple` on the synthetic hospital through the in-process gateway (PRODUCTION prompt versions) | `part_hospital` |
| `public-<lang>` | `public_e2e` console path, the public-data site built by lane G's `tools/public_site.py` | |
| `scenario-*` | `tools/scenarios.py`: SS-MIX2, FHIR, Excel, chart paste/files, REDCap, IT dump, registry, gateway probe through the in-process gateway; **TREC**: `mlbench.judge` with `mlbench.SYSTEM` straight to both servers (`sc_trec`, `tools/scenarios.py:2030-2075`); **MIMIC**: `tools.cascade_e2e` over the in-process **stub** (`:1873-1934`) | |
| G-1 `chat-template` | compares the passed template with the folder's and the server's `/tokenize` | `tools/chat_template_check.py` |
| G-4 `g4-decoding`, G-5 `g5-tokens` | direct calls to the judge server (bypasses the gateway on purpose), PRODUCTION judge prompt v4 | `tools/g_probes.py:293-430` |
| G-7 `g7-clipped` | product clip and `NoteJudge` through the gateway, but evidence picked with lane G's own lexicon and the verdict mapped by lane G's own `final_outcome`, not the product's decision function | `g_probes.py:431-560` |
| G-8 `g8-protocols` | `Compiler.compile` with the judge through the gateway as `criteria-compiler` | `g_probes.py` |
| walk, backup, update, scale | skipped on the VM (`--skip`); run on the driver's host on the stub | `complete-run-vm.sh:542` |
| Rehearsal (`make rehearse`) | the real driver and VM script in a container; `vllm_standin.py` answers with `llm_stub` | `tests/rehearsal/rehearse.sh:1-30` |
| Box run (G-2, G-9, G-10) | `deploy/gcp/box-install-run.sh`: the right target, never run; `d_wizard` passes `--answers`, which `deploy/box-install.sh:40` refuses; `tools.screen_job` does not exist; no cloud driver | `box-install-run.sh:378-387` |
| Demo VM | CPU VM, stub model by design (`TB_LLM_MODE=stub` fixed; real model refused) | `deploy/gcp/demo-vm.sh:23`, `demo-vm-boot.sh:14, 98, 143` |

### 1.3 Every difference between lane G's VM and the shipped box (each one a finding)

| # | Shipped box | Lane G VM | Effect on what a run proves |
| --- | --- | --- | --- |
| D1 | judge with `--chat-template` (developer file, D-392) | no `--chat-template` (folder's own) | G-1 (2026-11-12, `g1-2026-11-12/parts/chat-template.json`) FAILED: server ids differ from the reference on every system-turn prompt (first difference at token 22, one token longer). Every judge answer lane G recorded is on a rendering the box does not ship. |
| D2 | image by digest `befccf0e...` | `vllm/vllm-openai:v0.32.0` tag, local copy | identity with the shipped image not verified |
| D3 | weights from pinned folders, manifest checked by `pin_model` | HF cache on a kept disk, revision not checked, records not committed | identity with `expected` manifest not verified |
| D4 | model-guard in front of both servers | nginx adding the key | model-guard's route filtering never exercised |
| D5 | gateway, orchestrator, lake, adapter, db, embed, console as containers with memory caps (`docker-compose.yml:17-448`) | one Python process per part, no caps | capacity, OOM and restart behaviour of the box never measured; G-3 figures are uncapped in-process figures |
| D6 | real embedder (`embed-service`, CPU) | `HashEmbedder` | S2b retrieval never real; after #582 the product says "not evaluated" for some note criteria on the hash path |
| D7 | `TB_ENV=PRODUCTION` everywhere | process `TB_ENV=DEV`, gateway env PRODUCTION | PRODUCTION-only refusals (e.g. #566 opt-out, `prompt_unqualified` at start) not exercised by the box side |
| D8 | PostgreSQL 16 db image with its extensions | apt PostgreSQL on Ubuntu 24.04 | not verified equal |
| D9 | installed by bundle and installer | `git archive` of the operator's HEAD | the install, wizard and update paths never run on the card |
| D10 | prompts gated by qualification | probes and parts use PRODUCTION versions (v4/v1/v2) | consistent with today's box, but the T-606 versions that must ship have never been run on real models and never qualified |

## 2. Inventory

Class: CURRENT, STALE, STUB (L = legitimate, N = not legitimate when counted), MISSING. "Last real-model run" is the
date and commit of the newest result on the card; "never" if none.

### 2.1 Driver and scripts

| Item | Where | Last real-model run | Class | Evidence | Action | Owner lane |
| --- | --- | --- | --- | --- | --- | --- |
| Complete-run driver (launch, caps, door, collect) | `deploy/gcp/complete-run.sh` | 2026-11-14 `02858674` | STALE as validation; fine as plumbing | packs operator's HEAD, no integration-head check (`:809-818`) | keep plumbing; re-point (section 4.2): refuse a HEAD that is not a pushed integration commit with a passed rehearsal; launch the box-install path | G |
| VM serving block | `complete-run-vm.sh:147, 266-367` | same | STALE (private serving) | D1 to D4 | retire; replace with the installed box's compose (`docker compose -f docker-compose.yml -f docker-compose.rtxpro6000.yml --profile gpu`) | G (D owns the compose) |
| In-process box (`hospital-*`, `public-*`, `scenario-*`) | `tools/complete_run.py`, `tools/scenarios.py`, `tools/e2e_simple.py` | hospital 2026-11-13 `c25cea6b` (50k), public 2026-11-14 `02858674` | STALE as GPU validation; CURRENT as a free local gate on the stub | D5 to D8 | keep for laptop/CI; on the card, re-point to drive the installed box through its console/API and jobs | G |
| `install` part | `complete_run.part_install` | 2026-11-13 | STALE (misnamed) | installs nothing | rename "serving-record check"; real install is G-2 | G |
| `scenario-public-trec` | `tools/scenarios.py:2030-2075` | 2026-11-14 `02858674` FAILED 0/2 | STALE + private path | `mlbench.SYSTEM` prompt, direct to servers; no gateway, no judge prompt, no cascade | retire as product evidence; re-point to the cascade (SCREEN of TREC patients as a site, PRODUCTION prompt, two-model decision) | G with A2 |
| `scenario-public-mimic` | `tools/scenarios.py:1873-1934` | never | STUB (N if counted) | `cascade_e2e` over the stub | do not count; re-point to the card's gateway, or drop from the GPU plan (no notes in MIMIC demo: VALIDATION §5) | G |
| `scenario-public-medtxt` | `sc_medtxt` | 2026-11-14 `02858674` FAILED | STALE | pre-#572/#573; hash embedder; check relaxed by lane G after the failure (P6) | re-run on the product path after an independent review of the relaxed check | G, review A2 |
| Other scenarios (ssmix2, fhir, excel, chart-paste, chart-files, redcap) | `tools/scenarios.py` | fhir 2026-11-12 `931a0f79`; the rest: not verified (no folder holds them) | STALE | in-process box | re-point to installed box ingest paths | G with B2/E |
| it-dump, registry, gateway probe | same | no model / 2026-11-12 | not model tests | no model calls | run on CPU in CI, not on a paid GPU VM | G |
| G-1 chat template | `tools/chat_template_check.py` | 2026-11-12 `931a0f79` **FAILED 3/5** | CURRENT test, ignored result | `g1-2026-11-12/README.md:37-49` | run on the shipped compose (with `--chat-template`); the D-502 cost table wrongly says it was never run | G |
| G-4 decoding | `g_probes.run_g4` | 2026-11-13 `c25cea6b` (failed 1 check) | STALE | direct to server on private serving; 1/64 schema failure | re-run on shipped serving; keep direct calls (legitimate for this probe) | G |
| G-5 tokens | `g_probes.run_g5` | 2026-11-13 `0e9be8a5` passed | STALE (pre-D1 fix) | private serving, no chat template: token counts depend on the template | re-run once on shipped serving | G |
| G-7 clipped | `g_probes.run_g7` | 2026-11-13 `c25cea6b` passed | STALE + partly private | lane G's own `final_outcome` and lexicon | re-point to the product decision function (T-708) | G |
| G-8 protocols | `g_probes` | 2026-11-14 `cb850470` FAILED (B14) | STALE | #586 fixes B14 | re-run on the installed box's compiler | G |
| Run metrics, results reader | `tools/run_metrics.py`, `deploy/gcp/results_report.py` | n/a | CURRENT as code | | must also record commit, bundle id, served prompt versions, weight manifest, image digest, chat template sha | G |
| Rehearsal | `tests/rehearsal/*`, `tools/vllm_standin.py` | n/a | STUB (L) | stub answers; rehearses plumbing only | keep; add rehearsal of the box-install path (`make rehearse-box`) as the gate for every paid launch | G |
| Box-install run | `deploy/gcp/box-install-run.sh` | never | MISSING (right target, broken) | `--answers` refused (`box-install.sh:40`); `tools.screen_job` absent; no cloud driver | fix the interface with lane D; write its driver; make it the main paid run | G with D |
| One-boot scripts | `gpu-pro6000-run.sh`, `gpu-sim-startup.sh`, `gpu-fit-test.sh`, `gpu-swap-run.sh`, `capture-serving-config.sh` | 2026-11-08 (N-12, fit, serving record) | STALE | no chat template, tag image, ssh tunnel, outside `make rehearse`; 5090/sleep configs are wave 11 (plan v7 line 237) | retire to `deploy/gcp/legacy/` with a banner; stop using `gpu-pro6000-run.sh` for N-12 (the cost table plans to) | G |
| Demo VM | `deploy/gcp/demo-vm*.sh`, `demo_vm.py` | stub by design | STUB (L as a demo) | `demo-vm.sh:23` | keep for the 2026-11-17 demo; label every page and the run sheet "stub model, not validation" | G |
| D-502 cost table | scratchpad `d502-cost-table.md` | n/a | STALE | read `train/17` as `ee1fa363`, so says D-744/D-745 are missing (they are in `0c8e1211`: #598, #599); costs the harness, not the product; plans N-12 on the old script; says G-1 never ran (it did, and failed) | withdraw; replace with a plan of product runs (section 4) | G |

### 2.2 Records under `docs/plan/measurements/` and VALIDATION claims

All commits below are before train 15 (`5ff9f813`). Stale-making PRs common to all: train 15 #567 (C44/C4A
malignancy), #570 (undated labs), #576 (poisoned call gives up), #582 (NEW-LLM-2 no retrieval), #565 (coded values per
row), #560 (delta night applies chart merges); train 16 #586 (B14), #572 (negation), #573 (family history), #591
(ci-en), #584, #588; train 17 #598 (D-744 English phones masked), #599 (D-745 birth dates, addresses, chart labels
masked), #596 (SVC-EMBED), #595 (GW-SIGNALS). Also D-392 chat template (2026-11-11) for everything run without it.

| Record | Date, commit | What it measured | Verdict | Extra reasons stale | Still quoted by | Action |
| --- | --- | --- | --- | --- | --- | --- |
| `gpu-run-2026-11-08/` | 2026-11-08, commit not recorded | fit, canary 54, filter-first, public_e2e en | mixed | before D-392, T-606, all trains | VALIDATION §3 (canary 54/54, public 98/98 in 1,303 s); `complete_run.py` PUBLIC_SECONDS, restart seconds | mark superseded; remove from VALIDATION §3 |
| `eval/trec_ct/results/n12_deployed_2026-11-08.md` (N-12) | 2026-11-08 | TREC CT 9.4 % unadjusted, FAIL | FAIL | bench prompt (`mlbench`), not the product path | VALIDATION §3 gate row; runbook 11 line 29; cost table row 6 | mark "bench prompt, not product"; replace with N-12 on the product path |
| VALIDATION §3 N-11 | replay of recorded answers | SIGIR 79 pairs per language | | recorded answers, not a card run; ja/zh-TW are translations | VALIDATION §3 | mark as replay; not a model gate |
| VALIDATION §4 scale and bench | stub, 4-vCPU laptop | hospital_sim, bench | | not the card; says itself "the model share must be measured on the reference box" | VALIDATION §4 | keep, labelled; no card capacity claim exists |
| VALIDATION §7 complete run | 2026-11-09 stub | 662/662 | | stub, pre-trains | VALIDATION §1, §7 | keep as stub gate, re-run on head |
| `g1-2026-11-11/` | 2026-11-11 `986d91c9` (branch `g1/rehearsed-2026-11-11`, never on master: 1,986 commits behind) | 50k ja screen, 5.0 h | partial | drain fix era; single-stream | D-468 ("a hospital part takes 5 h": spot vs on demand); runbook 11 line 31 | superseded; D-468's premise gone |
| `g1-2026-11-12/` | 2026-11-12 `931a0f79` (branch `fix/g1-canary-rehearsal`, never on master) | G-1, G-3 at 1/4/16/48 on 5k | FAILED | | lane G findings | superseded; **keep G-1's finding open** |
| `g3-2026-11-13/` | `2b9eec74` (lane G batch 1 on master `d48c153c`) | 5k ja/zh-TW, 1/4/16; G-4, G-5, G-7 | FAILED | | `HOSPITAL_MEASURED` estimates; tests `test_g3_repeats_2026_11_13.py` | superseded |
| `g7-2026-11-13/` | `c25cea6b` | G-7, G-4 | FAILED | | lane G findings P1, P3 | superseded |
| `g3-50k-2026-11-13/` | `c25cea6b` | 50k ja/zh-TW at 16: 4.45/4.56 calls/s, 2,986/2,991 s | FAILED | uncapped in-process; hash embedder | `capacity_inputs.json` (says T-667, T-637, T-734 read it); `HOSPITAL_MEASURED`; runbook 11 line 210; cost table | superseded; **must not feed T-667 or HW-007** |
| `g5-g8-2026-11-14/` | `0e9be8a5` | G-5, G-8 | FAILED | | findings P2, B14 | superseded |
| `g8-2026-11-14/` | `cb850470` | G-8 (B14) | FAILED | #586 fixes it | findings B14 | superseded |
| `public-2026-11-14/` (on `lg/batch6` only, not in latest tree) | `02858674` | public ja/zh-TW, MedTxt, TREC | FAILED (2 of 4) | TREC bench prompt; check relaxed after | lane G findings P6-P8; `MEDTXT_/TREC_SECONDS`; cost table | do not merge as evidence; keep as estimate input only |
| `backfill-2026-11-11.md` | 2026-11-11 laptop | adapter RSS | | not lane G's card work; pre-#574 OMOP loader in batches | | lane B2 to re-date |
| `real-data-e2e-*.md`, `real-e2e-PROVENANCE.md` | 2026-11-08, branch `realdata-local` (never pushed) | public site walk | | local branch | | mark historical |
| `b200-g1b/G1b.md` | not run | | | | | keep as template |
| `lane-g-plan-2026-11-12.md` | 2026-11-12 | plan | | overtaken by plan 37 | | mark superseded |
| `lane-g-findings-2026-11-13.md` | 2026-11-13/14 | findings | | P1, P2, B14 fixed on master; P3, P4, P5 open | plan 37 (P4 card) | keep open items; move fixed ones to "closed" |

No product code reads a lane G figure (searched `tools/night_length.py`, `scale_gate.py`, `gpu_sizing.py`,
orchestrator). The capacity statement T-667 and the HW-007 refusal are not written yet: good, nothing to unwind there.

### 2.3 The plan's G items, judged against the latest repo

Note: plan 32 numbers its tests G-01 to G-23 and plan v7 §7.1 numbers G-1 to G-11 with **different meanings** (plan
32 G-09 is injection, plan v7 G-9 is restart/outage). The cost table mixes both. Use one list.

| Item (plan v7 §7.1) | Still the right test? | What must change |
| --- | --- | --- |
| G-1 chat template | yes, and it already failed | run on the shipped compose; if still different, repeat every accuracy figure with the shipped template (plan's own rule) |
| G-2 bundle -> install -> wizard -> pin -> qualify -> promote | **yes: the most important one, never run** | fix `box-install-run.sh` (`--answers`, `screen_job`), write its driver; this becomes the base of every other run |
| G-3 curve 1..48 at 50k | yes, but only on the installed box under caps | 32 and 48 only measure the gateway queue (16 slots): drop or keep one; repeats only after the box run works |
| G-4 decoding | yes, small | on shipped serving; eager on/off needs restarts (not done) |
| G-5 tokens | yes, small | re-run once on shipped template |
| G-6 night at 50k dense under caps | yes | needs T-692 (ingest 16-17 GB vs 6-8 GB caps) and the installed box |
| G-7 clipped | yes | product decision function, not lane G's |
| G-8 protocols | yes; fixtures now NEW-LIFE-18 (`lg/batch7`) | on installed compiler; more protocols (the pilot's own studies) |
| G-9 restart/outage | yes | needs a job API (`screen_job` does not exist) and the installed box |
| G-10 vLLM image move | yes (ENG-013, CVE waiver) | on the installed box |
| G-11 embedder in PRODUCTION | yes | the `embed` bench (two embedders in the vLLM image on GPU) is not it; measure `embed-service` (CPU, 4g cap) building the index at 50k |
| plan 32 G-02 "12 scenarios with the pair" | partly obsolete | MIMIC is stub; TREC is a bench prompt; it-dump/registry need no card |
| plan 32 G-13/G-14/G-15 (sweep, quantisation, 5090) | not now | 5090/GB10 are wave 11 (plan v7 line 237) |
| plan 32 G-16 qualification record | yes: same as G-2's qualify | it is the gate that lets the T-606 prompts ship |
| plan 32 G-22 500k screen only | no as written | HW-007 needs the incremental night (T-694, T-702, T-703: not built); a screen-only 500k on the harness proves nothing about the box |

New tests the latest repo needs (MISSING): qualify/promote of the T-606 prompts; upgrade and rollback bundle to bundle
on the card; backup and restore at 50k on the installed box; air-gapped operation (VM egress denied after install);
outage of a model server mid-night with #576's give-up rule; masking (D-744/D-745) measured on real-model traffic
(tripwire refusals per 1,000 calls); English site (`ci-en`, #591) end to end; multi-site (two sites, two languages, one
box) on the installed box; wizard answers only; NEW-PERF-1 numbers recorded from the installed gateway's audit.

## 3. Retire list

| What | Why | How | Whose |
| --- | --- | --- | --- |
| `complete-run-vm.sh` serving block (`:266-367`) as the way to serve models for validation | private serving (D1 to D4) | replace by the installed compose; until then every result it makes is labelled "lane G serving, not the shipped box" | G |
| GPU runs of the in-process box (`--model pair` on the VM) as validation | D5 to D8 | stop paying for them; keep `complete_run --model stub` as a free gate | G |
| `scenario-public-trec`, `tools/trec_ct_eval.py` on the pair, N-12 via `gpu-pro6000-run.sh` | bench prompt, no gateway, no cascade | stop; mark N-12 2026-11-08 "bench prompt"; rebuild TREC as a site screened by the box | G, A2 |
| `scenario-public-mimic` in any "with the pair" claim | stub | remove from the GPU plan | G |
| `gpu-pro6000-run.sh`, `gpu-sim-startup.sh`, `gpu-fit-test.sh`, `gpu-swap-run.sh`, `capture-serving-config.sh` | old one-boot scripts, no fail-safe, no chat template | move to `deploy/gcp/legacy/` with "superseded by box-install-run" | G |
| `deploy/measured/serving_config.rtxpro6000.json` (2026-11-08) | does not describe the shipped serving (no chat template, no digest) yet `install.sh` trusts it | re-capture from the installed compose on the card; lane D commits it | G captures, D owns |
| All nine results folders as current evidence | old commits, private serving | move to `docs/plan/measurements/archive/` with a SUPERSEDED header naming the PRs; repoint `tests/unit/test_g3_repeats_2026_11_13.py`, `test_g1_results_report.py` to copies under `tests/fixtures/` | G |
| `public-2026-11-14/` on `lg/batch6` | not yet merged; measured old commit | do not merge as evidence; keep only as estimate input | G |
| `HOSPITAL_MEASURED`, `PUBLIC_SECONDS`, `MEDTXT_/TREC_SECONDS` | estimates from the harness | keep only as cost estimates, labelled; never as capacity | G |
| `capacity_inputs.json` files | name T-667, T-637, T-734 as readers | delete the claim; nothing feeds T-667 until G-3/G-6 on the installed box | G, D |
| VALIDATION §3 rows (N-11 replay, N-12, canary, public en 2026-11-08) | old config, bench prompt, replay | mark stale with date and reason; replace with the qualify record | owner of VALIDATION (integrator), A2 |
| D-468 (hospital launches on demand) | premise "a hospital part takes 5 h" from `g1-2026-11-11` | supersede when the new run plan exists | integrator |
| D-502 cost table | false premises (section 2.1) | withdraw | G |
| The relaxed MedTxt check (P6) and the `public_site.py` status change | lane G changed the grader after a failure | independent review by lane A2 before any re-run counts | A2 |

## 4. Needed validation data and runs, ranked

### 4.1 Data the latest repo needs (top-down, independent of what exists)

| Rank | Risk | Data set | Language | Size | Gold, who | Licence | Exists today? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | wrong screening answer on real notes | NEW-LLM-6 accuracy set: per language and stratum (long notes, negation, family history, era dates, labs, suspected vs confirmed, treated past disease) with gold exclusion per criterion | ja, zh-TW, en | ~200 gold exclusions per language and stratum (plan 37) | clinicians via lane A2; two readers + adjudication | synthetic or authored: own | no (gold not written) |
| 1 | same, on real text | MedTxt-CR untranslated with its certainty markup as partial gold, reviewed by a clinician for "had vs has" | ja | 148 reports | corpus + A2 review | CC BY 4.0 | yes (data); gold rule disputed (P6) |
| 1 | same, at the real sites | first-look runs on the owner's machine on the real CGRD export and SS-MIX2 month, counts only | zh-TW, ja | one night | site clinicians sample | stays on site | planned (plan 37 first-look) |
| 2 | losing eligible patients | TREC CT 2021/22 screened by the product (cascade, two-model decision) | en | 1,700 pairs | NIST qrels | NIST terms | data yes; product path no |
| 2 | same | pair canary and `trialbox eval qualify` evidence set for the PRODUCTION prompts (judge v5, chart_facts v2, ir_extract v3 ...) | en, ja, zh-TW | qualify's own | A2 | own | runner exists; never run |
| 2 | same | zh-TW clinical text | zh-TW | ≥ 200 notes | clinicians | own | **none exists**: `public-zh-TW` is the zh-TW console over en+ja notes |
| 3 | data path per site format | installed-box ingest of SS-MIX2, FHIR, CGRD-style CSV, Excel/CSV (Shift_JIS, Big5), REDCap, chart files (OCR) | ja, zh-TW, en (#591) | 5k each | generator truth | synthetic | generators yes; installed-box path no |
| 4 | capacity | dense synthetic profile 50k (and 500k once the incremental night exists) | ja, zh-TW | 50k / 500k | n/a | synthetic | 50k yes; dense G-6 no |
| 5 | install/upgrade | two signed bundles (N and N+1), a bad N+1 | n/a | ~12 GB each | n/a | own | not built (R2) |

### 4.2 Paid runs that prove it, in order (each on the installed box, never on the harness)

| Order | Run | Proves | Precondition |
| --- | --- | --- | --- |
| 0 | Free: `make rehearse-box` and `rehearse-box-run.sh` on the exact bundle | plumbing | `box-install-run.sh` fixed (`--answers`, `screen_job`), cloud driver written |
| 1 | **Box install on the card** (G-2): bundle -> installer -> wizard -> pin -> serving capture -> G-1 on the shipped template -> pair canary -> `trialbox eval qualify` -> promote -> `doctor` | the shipped box serves the shipped pair; new vendor serving record; first qualification record | R2 bundle from the integration head (train 17 or later), vLLM waiver |
| 2 | Accuracy on the installed box: NEW-LLM-6 set, MedTxt-CR, TREC (as sites, through SCREEN) with the promoted prompts; G-7, G-8 | ranks 1-2 | gold from A2; masking (D-744/745) already in `0c8e1211` |
| 3 | Data paths on the installed box: each format at 5k, three languages where a generator exists | rank 3 | B2/E generators for en-style SS-MIX2, FHIR, REDCap |
| 4 | Capacity under caps: G-3 at 4, 8, 16 (x2, restart between), G-6 dense night at 50k with backup, G-11 embedder | rank 4; T-667's Linux figure | T-692 |
| 5 | Outage and upgrade: G-9 restarts and power cycle mid-night; bundle N -> N+1 update, bad N+1 rolled back; G-10 image move; backup and restore at 50k; air-gapped (egress denied) night | rank 5 | job API; second bundle |
| later | HW-007 500k incremental night | the 500k statement | T-694, T-702, T-703 built |

### 4.3 How lane G must work (process)

1. **One source of code.** A paid run is launched only from a commit that is the head of `master` or the current
   train, pushed, and built into a signed bundle. The driver refuses otherwise (`git merge-base --is-ancestor`,
   `git ls-remote`), and refuses a commit without a passed `make rehearse`/`rehearse-box` record for that same sha.
   Lane G's own changes reach that commit through a train first; no run from `lg/*` or a scratch merge.
2. **One serving setup.** The VM serves models only through the installed compose of that bundle. Any private
   `docker run` of vLLM is for an experiment named as such (G-4 style), never for a result counted as validation.
3. **Every result names what it ran.** Commit, bundle id and sha256, image digests, weight manifests, chat template
   sha, served prompt versions per id, embedder build, compose memory caps. A results folder without these is not
   evidence.
4. **Results expire.** A result is superseded when any of these change after its commit: `libs/tb_llm/prompts/registry.yaml`
   served versions, `services/matching`, `services/gateway`, `services/guard`, `libs/tb_common/phi_guard.py`,
   `services/criteria_compiler`, `deploy/docker-compose*.yml`, `deploy/images.lock`, `models/registry.yaml`. A CI
   check (like doclint) writes SUPERSEDED into the folder's header, naming the PRs; VALIDATION may quote only
   non-superseded results.
5. **Lane G does not grade itself.** Pass rules and checks of a run are fixed before the run; a change to a check after
   a failure is reviewed by lane A2 (accuracy) or B2 (data) before the re-run counts.
6. **One test list.** Merge plan 32's G-01..G-23 into plan v7 §7.1's G-1..G-11 numbering (or rename plan 32's to X-).

## 5. What lane G got wrong (blunt)

1. It built and kept paying for a parallel box. The plan said the GPU run is "the product-on-GPU run ... Real bundle,
   `box-install.sh`" (plan v7 line 301) and "the measuring harness measures the product" (line 300). Lane G ran its
   own in-process copy instead, every time.
2. It found the chat-template difference (G-1, 2026-11-12) and then ran six more paid runs without the shipped
   template. Its D-502 cost table says G-1 was never measured.
3. It reported TREC failures (D2, D3) and planned N-12 again on a bench prompt that the product does not use.
4. It counted runs on lane G branches as results: `986d91c9` and `931a0f79` never reached master; later runs were lane G
   batches 228 to 1,026 commits behind today's tree.
5. It changed the grader after failures (MedTxt P6: the check and the public site data), and plans to re-run against
   the changed grader.
6. Its cost plan (US$200 spot) is a matrix of harness runs, including 500k "screen only" on the harness, G-3 at 32/48
   (which only measure a gateway queue), MIMIC on a stub, it-dump/registry with no model on a GPU VM, and the old
   N-12 script. It states D-744/D-745 are missing from train 17; they are in it (#598, #599).
7. It let `capacity_inputs.json` claim to feed T-667, T-637, T-734 from uncapped, hash-embedder, pre-train numbers.
8. Recorded VM spend in its own folders is about US$59 (G1 11-11 US$31.5, G1 11-12 US$7.20, g3 5.45, g7 1.07, g3-50k
   5.48, g5-g8 2.19, g8 0.55, public 5.48, plus one failed set-up), against the US$5.48 the cost table takes as spent.
   Every one of those nine results says FAILED or partial.
9. The box-install path that would test the product has sat unrunnable (`--answers`, `screen_job`, no driver) while
   money went to the harness.

## 6. Open questions (not verified here)

| # | Question | Who |
| --- | --- | --- |
| 1 | Which revision of the weights and which vLLM image digest are on the VM's kept disk? (records not committed) | G, by reading the last `serving_config.rtxpro6000.live.json` |
| 2 | Does the chart reader (sitesetup) in the in-process box ask for PRODUCTION prompt versions like the gateway client does? (P6 cites `chart_facts_v2`, PRODUCTION serves v1) | G |
| 3 | How many of the 20 G-1 prompts differ (the part lists at most five)? | G |
| 4 | Budget basis: US$5.48 spent, or about US$59? | owner |
| 5 | Can `trialbox eval qualify` run on the VM today, and what evidence does it need (N-12 on which path)? | D, A2 |
| 6 | Who writes zh-TW clinical text with gold, and under what licence? | owner, A2 |
| 7 | Will lane D accept `--answers` in `box-install.sh`, or must the box-run feed the wizard another way? | D |
| 8 | Is the apt PostgreSQL on the VM the same major and extensions as the db image? | G |
| 9 | Should the 2026-11-17 demo (stub) be shown with a note that answers are not the model's? | owner |
