# TB-PLAN-07 Tests worth running on the cloud GPU VM: what each proves, the batches, the cost

| Field | Value |
| --- | --- |
| Date | 2026-11-12 |
| Owner | Changfu Kuo |
| Status | Proposed. Nothing here was run. Every launch needs a rehearsed commit (`make rehearse`) and the owner's yes on its `--estimate`. |
| Code read | `origin/master` at `514ae9b`; G1 records on branch `claude/g1-results-2026-11` (PR #291) |
| Data | Synthetic or public only |

How to read it. §1 is the decision in one page. §2 is the catalogue of tests. §3 is the batching and the order. §4 is
what runs without the card. §5 is the gaps that block a test. §6 is the first batch and the rest.

## 0. The numbers everything is derived from (OD-10)

| Number | Value | Source |
| --- | --- | --- |
| VM | `tb-gpu-sim`, g4-standard-48, one RTX PRO 6000 (96 GB), asia-east1-a; one VM in all (`GPUS_ALL_REGIONS = 1`) | RUNBOOK §11 |
| Price | spot US$2.74/h; on demand US$8.22/h (3x) | `tools/complete_run.py` `PRICE_PER_HOUR` |
| Start and setup | 0.5 h per launch (0.25 boot with both models, 0.25 setup) | `BOOT_HOURS`, `SETUP_HOURS` |
| Hospital part, 50,000 patients | 17,960 s (5.0 h); screening 8,584 s of it | G1 attempt 2, `hospital-ja.json` |
| Note-stage patient | 6.3 s with the pair; criterion check 0.3 s; canary 300 s; `public_e2e` 1,303 s | VALIDATION §3, `complete_run.py` |
| Peak card memory, both models, 32k context, 16 sequences | 62,592 MiB of 97,887 (64 %) | G1 `gpu_peak.json` |
| Spot pre-emption | 1 in about 11.5 spot hours (one observation; thin) | G1 attempts 1 and 2 |
| Hard cap of a launch | `ceil(estimate x 1.3)` hours | D-141 |
| A hospital shard runs on demand | yes | D-468 |

All hours and US$ below are the driver's `--estimate` on master where a part exists, and arithmetic from the table
above where it does not (marked "est."). Costs are card time; the cap of each launch is given in §6.

## 1. Decision summary

1. **Split what is left of G1 into three launches, not one.** With one VM, D-468 prices the *whole* run on demand as
   soon as one hospital part is in it: the remaining 10.2 h would cost US$83, not US$28. Launch the spot parts
   alone (US$14) and `hospital-zh-TW` alone on demand (US$45).
2. **Front-load a bounded 5,000-patient launch** (1.1 h, US$9 on demand or US$3 spot). It is the cheapest test in
   this plan and the most informative: it proves the five driver fixes (A1 to A5) and D-468 on the real VM, and it
   settles G1 B1 (D-470 shows the cause is the real chart reader, not the patient count, so 5,000 patients are enough).
3. **Add five things to the G1 run before it is rehearsed** (§3.1): the serving metrics per part, `public-en`, the
   injection suite as a part, the tripwire count per part, the profile bench at more than one concurrency. Together
   about 1.0 h and US$2.7 of spot time. They share the G1 serving configuration, so they cost no second start.
4. **Anything that changes the serving configuration needs its own launch** (context length, sequences, memory
   share, quantisation, the 32 GB cap): the VM script fixes `--max-model-len 32768 --max-num-seqs 16` and the memory
   shares. One sweep launch, 2.5 h, US$7 spot, after the gap of §5 X-4 is closed.
5. **Do not buy the 500,000-patient proof on the card.** A hospital part scales to 50 h (US$137 spot, US$410 on
   demand), a part cannot resume inside itself, and ingest holds the hospital in memory until T-692. The data plane
   at 500k is a CPU test (§4); the model time is linear in note-stage patients and is extrapolated from the 50k
   measurement, then checked once by a screen-only run when T-689 and T-694 are merged.
6. **Nightly ingest, lake rebuild, backup and the memory caps need no card.** The driver's parts run in one process
   without the compose caps, so the G1 run does not test them at all. They belong to the scale gate (T-687) on a
   CPU VM at about US$0.60/h.
7. **`hospital-zh-TW` at 50,000 is the least proof per dollar in G1** (US$45 for a second language of a scale
   already shown; the language itself is covered by `public-zh-TW` and the scenarios for US$2). It stays in the
   first batch because T-004 names it; the owner may move it to the B200 (ledger row B1, no cloud cost) and spend
   the US$45 on the sweep, the qualification record and the box install instead. **Owner decision D-A.**

## 2. The catalogue

Risk: of losing the launch's money or of a result nobody can use. "Share" = can run in a G1 launch (same serving
configuration); "Own" = needs its own launch. Hours exclude the 0.5 h start and setup of a launch.

### 2.1 Parts the driver has today

| Id | Test | Proves | Unblocks | Driver | Hours | US$ spot / on demand | Risk | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | Bounded launch, 5,000 patients | the fixed driver on the real VM (A1 to A5, D-468, TLS door); B1's cause from the stage-12 evidence of D-470 | every later launch; D-470 (owner rules); T-207 | `--patients 5000 --only install,hospital-ja,scenario-gateway,scenario-emr-fhir --no-wait` | 0.61 | 1.67 / 5.01 | Low | report PASSED or stage 12 alone failed with its per-patient evidence present; VM `TERMINATED`; no secret version left |
| G-02 | The 12 scenario parts | every data entry form with the pair: SS-MIX2, FHIR, Excel, chart paste, chart files with real Tesseract (D-135), REDCap, IT dump, registry, MIMIC, MedTxt, TREC, the gateway probe | T-004; T-317 | `--only` the 12 `scenario-*` tags | 3.36 | 9.21 / 27.62 | Medium: chart-paste and emr-ssmix2 are the long ones (0.68, 0.64 h); a pre-emption loses one part at most | every part PASSED; no direct fallback |
| G-03 | `public-ja`, `public-zh-TW` | the public walk with the pair in both site languages | T-004; qualification evidence (`public_e2e`) | `--only public-ja,public-zh-TW` | 0.72 | 1.97 / 5.92 | Low | PASSED at the run's HEAD |
| G-04 | `embed` bench | two embedders on ja and zh-TW notes: throughput, card memory, retrieval quality, halfvec size at 1,024 dims | T-607's decision record; T-203a/b (which embedder the vector store is built with) | `--parts g1,embed` | 0.25 | 0.69 / 2.06 | **High until T-688**: the bench runs in a container the heartbeat does not see (G1-4); a download over 20 min powers the VM off | both models compared; at least 20 queries per language |
| G-05 | `profile` bench | tokens in and out, seconds per patient, GPU-hours per 1,000 profiles through the gateway | T-311a chain (is a nightly profile affordable), T-204, T-637, T-734 | `--parts g1,profile` | 0.33 | 0.90 / 2.71 | Low | every summary cites only its patient's facts; the gateway answered |
| G-06 | `hospital-zh-TW`, 50,000 | the zh-TW hospital end to end at scale; a second 50k timing; B1 again at scale | T-004 (G1 complete), T-637, T-667, T-734 (within 15 % of a measured run) | `--only install,prepare,hospital-zh-TW` (on demand, D-468) | 4.99 | 13.67 / 41.02 | High on spot (a pre-emption loses the part); Low on demand | 20 stages; no false model exclusion against note truth; inside the 480 min limit |

### 2.2 Tests that need a small addition (§5)

| Id | Test | Proves | Unblocks | What must be added | Hours | US$ spot / on demand | Share or own | Risk | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-07 | Serving metrics per part | tokens per second, time to first token, queue time, KV-cache use, prefix-cache hits, for each real workload | T-667, T-637, T-734 (pairs per hour, patients per night) | X-5: scrape both servers' `/metrics` before and after each part into the part result | 0 | 0 | Share | Low | each model part carries the counters |
| G-08 | `public-en` | the English walk with the pair: third language | multilingual claim; T-317 | X-2: the driver passes `--langs` | 0.36 est. | 0.99 / 2.96 | Share | Low | PASSED |
| G-09 | Injection and false-positive suite on the pair | 80 cases of `eval/injection/cases.yaml` against the real models, not the stub | T-208 (ledger S5), T-606, T-311a | X-3: part `injection` (`tools.injection_eval` through the gateway) | 0.2 est. (80 cases x 2 models x about 4 s) | 0.55 / 1.64 | Share | Low | no planted instruction obeyed; false positives under the suite's own limit; the obeying stub still fails (control) |
| G-10 | PHI tripwire rate on real model traffic | hits per 1,000 gateway calls over 50k synthetic patients in ja and zh-TW; every hit read (true or false) | LLM-15; the D0 to D2 routes; T-606 | X-3: each part result carries the gateway's `phi_tripwire` refusals by kind | 0 | 0 | Share | Low | a number with its denominator; no call relabelled; false hits listed by kind |
| G-11 | Concurrency of the judge | seconds per patient and tokens per second at 1, 4, 16 and 32 parallel calls on the G1 serving configuration | T-667, T-734; the orchestrator's worker count as a derived setting (OD-10, F-31) | X-6: `--profile-workers` and `--profile-patients` reach the VM; the bench runs once per value (100 patients each) | 0.4 est. | 1.10 / 3.29 | Share (up to 16 sequences; 32 shows the queue) | Low | a curve; the knee named |
| G-12 | Forced pre-emption and resume on the real VM | a pre-empted spot launch keeps its finished parts and runs only the rest (A1), with the re-computed cap | T-004's "forced pre-emption"; trust in spot for every later launch | X-12: `--simulate-preempt-after N` (Compute's simulated maintenance event on a spot VM; to verify) | 0.4 est. (one more start and setup) | 1.10 / n.a. | Share (the spot launch) | Medium: the simulate call is unverified here | finished parts kept; one resume; report PASSED |
| G-13 | Serving sweep | context length 8k, 16k, 32k, 64k; sequences 4, 16, 32; the memory share (KV cache) at each: card memory, throughput, refusals for length | T-710 (the excerpt budget from the context), T-667, T-734, F-11, F-13; `serving_config` per profile | X-4: serving settings from metadata and a `sweep` mode that restarts the servers and runs one fixed workload (G-05 at 100 patients, 100 TREC pairs) | 2.0 est. (8 configurations x 0.25 h: 5 min load, 10 min work) | 5.48 / 16.44 | **Own** | Medium: a configuration that does not load must be skipped, not end the run | each configuration: loaded or refused with the reason, peak memory, pairs per hour; one recommended setting with its number |
| G-14 | Quantisation and the challenger build | the judge at its release quantisation against the challenger build and one other quantisation, on the frozen item set | T-674 (ledger S4), Q-19, RSK-60 | weights on the VM disk (a download: X-9); `tools.judge_bakeoff --base-url` per build, run by the sweep mode of X-4 | 2.5 est. (0.5 download, 2 builds x 1.0) | 6.85 / 20.55 | **Own** (may share the sweep launch) | Medium: disk space in `/models`; licence rows first | the bake-off report with intervals; a build wins only outside the interval |
| G-15 | The 32 GB-capped pair (the 5090 stand-in) with sleep-mode swap | the consumer-card form still fits and what it costs in pairs per hour | T-667 (Japan hardware note, due 12-18), OD-11 | none: `deploy/gcp/gpu-fit-test.sh`, `gpu-swap-run.sh`, then `tools/trec_ct_eval.py` | 1.5 (0.6 + 0.85 measured on 11-08) | 4.11 / 12.33 | **Own** (older one-boot scripts; fold into X-4) | Low | fits under 32 GB; N-12 inside the gate |
| G-16 | Qualification record for the card | N-12 (TREC), `public_e2e`, goldens, MedTxt (real ja), `mlbench` in ja, zh-TW and en, canary: one `passed` record | promotion of the pair (D-358); T-114's cloud twin; multilingual accuracy with intervals | X-3: part `qualify` that runs the evidence steps and `trialbox eval qualify --profile rtxpro6000` | 2.0 est. (N-12 0.85; MedTxt 0.38; mlbench 1,015 pairs x 3 x 2 x 0.3 s = 0.5; steps 0.3) | 5.48 / 16.44 | Share or own | Low | the record says `passed`; each language's agreement with its interval |
| G-17 | Embedder refit at scale | S2b with the pinned embedder against the hash path at 50k notes: parity, minutes, vectors' size | T-203b (the flag), T-607, F-23 (2.9 h of one core with the hash embedder) | X-3: part `vec` (`tools.vec_parity` with the `hf` backend on the card and pgvector on the VM) | 0.5 est. | 1.37 / 4.11 | Share | Medium: pgvector on the VM is new in setup | parity report inside its limit; minutes per 50k notes |
| G-18 | Model-pair re-measure after the decision-path cards | the same verdicts or the named, intended differences after T-707, T-709, T-710 | T-707, T-709, T-710 (merge evidence); the cascade golden with a recorded pair (TB-PLAN-06.1 §5.2) | none beyond X-2; needs the recordings kept (X-11) | 2.8 (public x3 1.08, TREC 0.32, MedTxt 0.38, two 5,000-patient hospitals 1.0) | 7.67 / 23.02 | **Own**, after the cards merge | Low | no patient excluded that the full record keeps; differences only from the named table |
| G-19 | Box install with real images | the installer and first-run wizard (T-729) on a clean disk with the real vLLM image and weights: `doctor`, the canary, one 500-patient screen, under the compose memory caps (the model server at 48 GB) | T-729, T-213b, T-730, T-735; OD-11, OD-13 | X-10: `deploy/gcp/box-install-run.sh` (the VM script's fail-safe frame around the installer) | 1.5 est. (image pull, install, canary 300 s, screen) | 4.11 / 12.33 | **Own** (the box owns ports and the card) | Medium: first run of a new script; rehearse it | wizard answers only; HTTPS sign-in; `doctor` green; canary passed |
| G-20 | A box night at 50,000 with the pair | ingest, rebuild, screen, backup as the installed box runs them, under the caps, with the real models: T-687 with a real pair | T-687 (its real-model twin), T-690, T-691, T-692, T-726, T-734 | G-19's script plus a 50k load; needs T-692 (ingest needs 16 to 17 GB against 6 to 8 GB caps today) | 5.0 est. (screening 2.4 h measured; rebuild 805 s; ingest and backup the rest) | 13.70 / 41.10 | **Own**, later | High before T-692 and T-689 | the night ends inside its window; no container killed for memory; the backup restores |
| G-21 | Interactive latency under the night's load | a CASE or front-desk call's latency while a screen fills the batch | T-734 (what a box can carry by day), OD-15 | a small load script; shares G-20 or the sweep | 0.5 est. | 1.37 / 4.11 | Share with G-13 or G-20 | Low | p50 and p95 with and without the batch |
| G-22 | 500,000: screen only | the model time is linear: 9,200 note-stage patients x 6.3 s | T-687 at 500k, T-734 | T-689 (the job survives a restart), T-694; a lake built on a CPU VM and copied by bucket | 16.1 est. | 44.11 / 132.34 | **Own**, last | High: one job of 16 h on spot | pairs per hour within 15 % of the 50k figure |
| G-23 | G1 on the release | the whole run again on the release commit | ledger S6; G3 | none | 16.15 as three launches (three starts) | 104.40 (two hospital launches on demand 90.24, the rest spot 14.16) | Own | as G1 | PASSED |

## 3. Batching

### 3.1 Add to the G1 run now, before the rehearsal

These share the G1 serving configuration and each is a small change the rehearsal can cover in `run-a`.

| Add | Gap | Card time | Why now |
| --- | --- | --- | --- |
| Serving metrics per part (G-07) | X-5 | 0 | It turns every part already paid for into a throughput measurement. Without it T-667 and T-734 need a second run. |
| Tripwire count per part (G-10) | X-3 (result field only) | 0 | 50k patients of traffic is the only large denominator there will be. |
| `public-en` (G-08) | X-2 | 0.36 h | Third language for US$1. |
| Injection suite as a part (G-09) | X-3 | 0.2 h | Ledger row S5 for US$0.55 instead of its own launch (0.5 h start alone is US$1.37). |
| Profile bench at 1, 4, 16, 32 workers (G-11) | X-6 | 0.4 h | The concurrency curve on the exact G1 configuration. |
| Keep the pair's answers (recordings) of the public and TREC parts | X-11 | 0 | The cascade golden of TB-PLAN-06.1 §5.2 needs them; a later run would cost again. |

Also before the rehearsal, no card time: **T-688's heartbeat fix (G1-4)**, or `embed` must be the last part of its
launch so that a watchdog power-off loses nothing else; and **X-1**, so the bounded launch can run on spot.

Not for the G1 run: anything that restarts the model servers (G-13, G-14, G-15), the box (G-19, G-20), and the
re-measure (G-18, which waits for its cards).

### 3.2 The order (riskiest and most informative first)

| # | Launch | Tests | Model | Hours | US$ | Why here |
| --- | --- | --- | --- | --- | --- | --- |
| L1 | bounded, 5,000 | G-01 | on demand (D-468) or spot with X-1 | 1.11 | 9.09 (spot 3.04) | proves the driver before any long launch; settles B1 |
| L2 | the spot parts | G-02, G-03, G-04, G-05 + G-07 to G-12 | spot | 5.17 + 1.36 = 6.53 | 17.89 | most parts per dollar; a pre-emption loses one short part; the forced pre-emption (G-12) is done here |
| L3 | `hospital-zh-TW`, 50,000 | G-06 | on demand | 5.49 | 45.12 | long and single; only after L1 and L2 show the driver holds |
| L4 | serving sweep | G-13, G-15, G-21, G-14 if the weights are there | spot | 0.5 + 2.0 + 1.5 + 0.5 (+2.5) = 4.5 (7.0) | 12.33 (19.18) | a failed configuration loses 15 minutes |
| L5 | qualification record | G-16, G-17 | spot | 0.5 + 2.5 = 3.0 | 8.22 | after the sweep fixes the serving settings: the record is of those settings |
| L6 | box install | G-19 | spot | 2.0 | 5.48 | after T-729's rehearsal passes with X-10 |
| L7 | re-measure | G-18 | spot (with X-1) | 3.3 | 9.04 | after T-707, T-709, T-710 merge |
| L8 | a box night at 50k | G-20 | on demand (one 2.4 h job) | 5.5 | 45.21 | after T-692 and T-689 |
| L9 | 500k screen only | G-22 | spot after T-689 | 16.6 | 45.48 | last; only if the owner wants the number measured, not extrapolated |
| L10 | G1 on the release | G-23 | mixed | 16.15 | 104.40 | before G3 |

**Totals.** L1 to L3 (G1 complete, with the additions): 13.13 h, **US$72.10** (US$66.05 with L1 on spot). L4 to L7:
12.8 h, US$35.07 (US$41.92 with G-14). L1 to L7: about 26 h, **about US$107 to 114**. L8 to L10 are another
US$195 and are decided later. The ledger's budget before G3 is 60 to 90 GPU-hours; L1 to L10 is about 64 h.

## 4. Cheaper without the card

| Test | Where | Cost | Note |
| --- | --- | --- | --- |
| G1 B1 on the stub at 500 and 5,000 | done (D-470) | 0 | passes; the real reader is the difference, hence G-01 |
| The driver, pre-emption, resume, door, watchdog | `make rehearse` (`CASES=preempt` for A1) | 0, about 1 h | required before every launch |
| The stub parts of the complete run at 50,000 (walk, backup, update, scale) | a CPU VM | about US$0.60/h (e2-standard-16, 64 GB: four times the demo VM's US$0.15/h); 2 h est., US$1.20 | today they run on the driver's host after the collect; a 50k stub run was killed for memory in a session (D-470). See X-7. |
| The scale gate T-687: nightly ingest, rebuild, screen, backup at 50k under the compose caps, slow model stand-in | a CPU VM nightly (64 GB until T-692; a 16 GB CI runner after it) | US$0.60/h x about 4 h = US$2.40 a night; 0 in CI after T-692 | this is the proof of F-01, F-02, F-05 (T-690, T-691, T-692), not G1 |
| Backup and restore at 50k; the lake rebuild (805 s); memory caps; update, stop and boot (T-695) | the same CPU VM, compose | in the US$2.40 | no model needed; `tools/vllm_standin.py` answers |
| The data plane at 500k (ingest, rebuild, backup size, F-25, F-26) | a CPU VM with 128 GB (e2-highmem-16, about US$0.80/h est.) and a 1 TB disk | about 12 h est., US$10 | after T-692; before it ingest needs about 160 GB |
| PHI tripwire rate of the recognisers on `eval/phi_synth` (ja, zh-TW, en) | CI (`tools/phi_synth_eval.py ... regex`) | 0 | the guard is regular expressions; only the rate on real model traffic (G-10) needs the run |
| Vector parity with the hash embedder; the injection suite on the stub; the canary wiring | CI (exists) | 0 | the card adds only the real models |
| Box install with stand-ins (`tools/rehearse_box`) | CI or a session | 0 | G-19 adds the real images and weights |
| Tesseract on scanned charts | any CPU | 0 | it also runs for real inside G-02 (`--ocr tesseract`) |
| Capacity table, Spark estimate (`tools/gpu_sizing.py`, T-637, T-667) | arithmetic from G-07, G-11, G-13 | 0 | no run of its own |
| G1b on the B200, two MIG layouts | the owner's machine (T-114) | 0 cloud | not a cloud test |

CPU prices are derived from the RUNBOOK's demo-VM figure and are to be confirmed on the pricing page before a
launch. `PREEMPTIBLE_CPUS = 0`: a spot CPU VM draws on the regular CPU quota.

## 5. Gaps that block a test

| Id | Gap | Blocks | Fix | Size |
| --- | --- | --- | --- | --- |
| X-1 | `provisioning()` makes any shard with a hospital part on demand, also a 0.5 h part at 5,000 patients, and with one VM the whole run | L1 on spot; G-18 | `--provisioning auto|spot|standard`; `auto` is on demand only for a part longer than a declared setting (2 h: at 1 pre-emption in 11.5 h the expected loss of a 2 h part, US$0.5, is under its on-demand premium, US$11) | S |
| X-2 | The driver has no `--langs`; `LANGS` is ja and zh-TW | G-08 | pass `--langs` (metadata `tb-langs`); an estimate row per language | S |
| X-3 | No parts for the injection suite, the qualification record, the vector parity; no tripwire count in a part result | G-09, G-10, G-16, G-17 | parts `injection`, `qualify`, `vec` in `BENCH_PARTS` with estimate rows and a `run-a` case each; the gateway's refusals by reason in every part result | M (one card; three small PRs) |
| X-4 | The VM script fixes the serving settings (`--max-model-len 32768 --max-num-seqs 16`, shares 0.40 and the verifier's) | G-13, G-14, G-15, G-21 | settings from metadata with today's values as defaults and their reasons; a `sweep` mode: a list of configurations, restart, the serving check, one fixed workload, a serving record each; a configuration that fails to load is recorded and skipped | M (card) |
| X-5 | No vLLM `/metrics` in the results | G-07 | the `--after-part` hook saves both servers' `/metrics`; the report shows the difference per part | S |
| X-6 | `--profile-workers`, `--profile-patients` do not reach the VM | G-11 | metadata `tb-profile-workers` (a list), one bench per value | S |
| X-7 | The collect runs walk, backup, update and scale at the run's `--patients` on the driver's host | a PASSED G1 report from a small session | `--collect --stub-on <host>` or `--no-stub` plus a CPU-VM step that writes the same part files | S |
| X-8 | G1-4 (T-688): the heartbeat does not see the embed container | G-04 | T-688 as written; until then `embed` last in its launch | S (card exists) |
| X-9 | No rule for new weights on the VM disk (free space, hash, licence row) | G-14 | `tools/pin_model.py --install` on the VM in setup, refused without a register row; 50 GB free is already a pre-flight | S |
| X-10 | No fail-safe script that installs a box on the VM | G-19, G-20 | `deploy/gcp/box-install-run.sh`: the watchdog, cap and door of `complete-run-vm.sh` around `deploy/install.sh` and the wizard's answers file; a rehearsal case | M (card; T-213b's cloud half) |
| X-11 | Not confirmed that a run keeps the pair's raw answers | G-18's golden | keep the gateway's recordings of the public and TREC parts in `results.tgz` (synthetic and public text only) | S |
| X-12 | No forced pre-emption on the real VM | G-12 | `--simulate-preempt-after N` in the driver; verify the Compute call on a spot VM in `--dry-run` first | S |
| X-13 | A part cannot resume inside itself (G1-2); the failure share is checked after the job (G1-3) | G-20, G-22 | T-689 as written | card exists |

X-1, X-2, X-5, X-6 and the result field of X-3 are one small pull request and belong before the G1 rehearsal.

## 6. Recommendation

### 6.1 First batch (US$66 to 68; about US$60 with decision D-A)

| Launch | Command (after `make rehearse` passes on the commit) | Hours | US$ | Cap |
| --- | --- | --- | --- | --- |
| L1 | `deploy/gcp/complete-run.sh --patients 5000 --only install,hospital-ja,scenario-gateway,scenario-emr-fhir --no-wait` | 1.11 | 9.09 on demand; 3.04 with `--provisioning spot` (X-1) | 2 h, US$16.44 |
| L2 | `deploy/gcp/complete-run.sh --patients 50000 --parts g1,embed,profile --only install,prepare,<the 12 scenario tags>,public-ja,public-zh-TW,embed,profile --no-wait`; with the additions: `--langs ja,zh-TW,en`, `injection`, the workers list, `--simulate-preempt-after 3` | 5.17 as it is; 6.53 with the additions | 14.16; 17.89 | 7 h, US$19.18; 9 h, US$24.66 |
| L3 | `deploy/gcp/complete-run.sh --patients 50000 --only install,prepare,hospital-zh-TW --no-wait` | 5.49 | 45.12 on demand | 8 h, US$65.76 |

Total: **US$68.4** as the driver stands, **US$66.1** with the additions and L1 on spot (L2 grows, L1 shrinks). To
hold US$60 exactly, take decision D-A: run L3 at 5,000 patients (1.0 h, US$8.21) and leave the 50k zh-TW hospital
to the B200. The batch is then **US$31.5 to 35.2** (US$23.7 with X-1 and the additions) and L4, L5 and L6 (US$26.03) fit in
the same US$60.

Stop rules: L2 starts only when L1's report is read. L3 starts only when L2 is collected and the VM is
`TERMINATED`. A launch whose report is FAILED for a product reason is not repeated; the finding goes to its card.

### 6.2 The rest

L4 to L7 (US$35 to 42) as their gaps close: X-4 for L4, X-3 for L5, X-10 for L6, the three decision-path cards for
L7. L8 to L10 (US$195) wait for T-692, T-689 and the release. Each finished launch fills its row in
`docs/plan/gpu-ledger.md`.

### 6.3 Decisions for the owner

| Id | Question | Recommendation |
| --- | --- | --- |
| D-A | `hospital-zh-TW` at 50,000 on the cloud (US$45), or at 5,000 on the cloud and 50,000 on the B200 | 5,000 on the cloud now; 50,000 on the B200 (ledger B1) |
| D-B | Keep D-468 for every hospital part, or only for parts over 2 h (X-1) | only over 2 h |
| D-C | The 500k proof: measured on the card (US$45 to 137) or CPU data plane plus extrapolated model time | CPU plus extrapolation; L9 only if a site asks |
| D-D | The five additions to the G1 run (§3.1), about US$2.7 | yes, in one pull request before the rehearsal |
