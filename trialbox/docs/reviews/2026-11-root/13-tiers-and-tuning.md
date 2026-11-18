# Root review 13: four hardware tiers, each its own product shape, and tuning of every aspect (lane J, B-14, 2026-11-18)

**Reader:** the owner (a clinician) first, then the builders and whoever writes plan 10.

**The owner's words (2026-11-18):** "The tuning needs to be started, not just GPU serving but all aspects." "For the 4
tiers, no GPU, 5090, Spark, 6000 Pro, need separate tuning, not just performance but also the entire architecture,
flow and smoothness." Performance and GPU serving are "my most concern".

**What this review did.** It starts where root review 08 (`origin/agent/B8-root-serving`) stopped. 08 tuned one box,
the RTX PRO 6000, and wrote its runs G-0 to G-7. This review does not repeat them; it cites them by id. It goes under
them (memory arithmetic per tier, the engine each tier can run, the shape of the product on each) and across them (the
rest of the box: ingest, database, console, start-up, backup, update). Nothing was run on a GPU or in a cloud. On this
shared 4-core machine one small thing was measured (start-up import time and memory of each service); everything else
is read from the repository at master `7da6edd38`, from P2b's stored sets (branch `integrator/p2b-artefacts`, read
with `git archive`, not merged), or opened at the maker's page on 2026-11-18.

**Marks.** **[M n]** measured here (section 14 gives the command); **[R file:line]** read in the repository (paths from
`trialbox/`); **[S link]** a public source opened 2026-11-18; **[S2 link]** a secondary public source (a retailer, a
blog, a forum) opened 2026-11-18, weaker than a maker's page; **[O]** opinion, with the reasoning; "not verified" where a
source could not be opened. Review ids: 01, 05, 06, 07, 08, 10 are the root reviews; plan 9 rev 2 is
`docs/plan/46-…` on `origin/agent/B11-plan-9-rev-2`.

The four tiers in this document: **A** no GPU (a CPU server or workstation); **B** one GeForce RTX 5090 (32 GB);
**C** NVIDIA DGX Spark (GB10, 128 GB unified memory, Arm CPU); **D** one RTX PRO 6000 Blackwell (96 GB), Workstation
Edition (600 W) or Max-Q (300 W).

---

## 0. One page for the owner

**What is true today.**

- The repository sells three boxes, not four. `--tier small|medium|large` means 5090, Spark and RTX PRO 6000
  [R `tools/tiers.py:41`; `docs/runbook/01-install-a-new-site.md:9-11`]. A machine without a GPU is not a tier: the
  installer falls into "stub" mode and says "structured criteria only … note criteria wait for a GPU or a pinned cloud
  model" [R `deploy/install.sh:197,202`]. In PRODUCTION the stub model is refused [R `models/routing.yaml:28-33`], so
  a GPU-less hospital can screen coded criteria and nothing else, and cannot read a new protocol at all.
- The three GPU tiers differ only in a few serving numbers (context 8k / 16k / 32k, sequences 4 / 8 / 16, sleep swap on
  the 5090) [R the three compose files]. Everything else (the night plan, the console, the database settings, the
  embedder on the CPU, the queue sizes, what the user sees when the model is slow) is the same on every tier. That is
  the gap the owner names: **the tiers are knob sets, not product shapes.**
- **Only one tier was ever measured.** The RTX PRO 6000 (Server Edition, in the cloud) has a serving record and P2b's
  traces [R `deploy/measured/README.md:10`]. The 5090 was imitated by capping that card to 32 GB,
  never run on a real 5090 [R `deploy/docker-compose.rtx5090.yml:22-27`]. The Spark profile says `status: unmeasured`
  [R `deploy/gb10-profile.yaml:13`]. The CPU tier has no profile.

**What each tier is, in one line each** (section 3 gives the arithmetic) [O unless marked]:

| Tier | What it should be sold as | Nightly screening (600 beds, 15 studies, typical) | Reads a new protocol on the box |
| --- | --- | --- | --- |
| A, no GPU | "Coded screening, and notes for small hospitals overnight" | 33 h of model time today: **does not fit**; coded criteria only, or a small hospital | yes, slowly (minutes per protocol), only if a CPU model is added |
| B, RTX 5090 | "A small-hospital box"; a poor buy in Japan today (see below) | 1.6 h today, 0.5 h tuned | **no** (8k context); protocols read elsewhere |
| C, DGX Spark | "A quiet, low-power box for a small or mid-size hospital", once measured | 2.8 h today, 0.8 h tuned (estimates) | yes, about 1 to 2 minutes a protocol |
| D, RTX PRO 6000 | "The head-hospital box": the reference | 0.5 h today, 0.2 h tuned | yes, under a minute of model time |

**The five changes that matter most** (each is a card in section 11):

1. **Make tier A a real tier** (13-1): a `cpu` profile with its own compose file, a CPU model server for the judge (the
   mixture-of-experts judge reads only ~4B of its 26B parameters a token, so it suits a CPU far better than the dense
   verifier does), and rulesets compiled at another box and shipped signed. Until then the sales sheet must say "coded
   criteria only" for a GPU-less site.
2. **Tune each tier's serving from its own measurement, not by copying the RTX PRO 6000 flags** (13-4 to 13-8): on the
   5090, 16 sequences instead of 4 and a test of both models resident at 8k (no swap); on the Spark, 32k context
   (memory allows it) and CUDA graphs; on the RTX PRO 6000, 08's G-1 and G-2, plus the Max-Q's 300 W cap measured.
3. **One place where the tier decides the product's behaviour** (13-2): a tier record (sequences, context, which roles
   run on the box, the night plan, what the console promises) read by the gateway, the scheduler and the console, so
   that the console tells a 5090 user "protocols are read at the head hospital" instead of failing.
4. **Measure the rest of the box, not only the GPU** (13-10 to 13-16): the console has no per-page timing at all
   [M 3: no `Server-Timing` or timing middleware anywhere]; idle memory, start-up, backup, restore and update have
   never been timed on real hardware [R 07 §3, rows 4.4 and 5].
5. **Validate each tier separately, once** (13-17): the qualification command already takes `--profile`
   [R `tools/qualify.py:1-10`]; it has only ever been run for `rtxpro6000`.

**Buying advice for the first site (Japan).** The first site (a general hospital in Japan) is a hospital of about 500 to 600 beds — the owner to confirm (section 9). Buy **tier D,
the RTX PRO 6000 Max-Q (300 W)** in a workstation from a maker that fits and supports it, as plan v7 already says
[R `docs/plan/33-plan-v7.md:91`]. The card alone is listed at about **¥2.50 million** in Japan today [S2 kakaku.com].
A Spark costs about **¥1.05 million** [S2] and a 5090, today, about **¥1.24 million** at the cheapest Japanese shop
[S2] — a 5090 now costs more than a Spark and gives less (32 GB, no protocol reading). **Do not sell tier B in Japan at
today's prices** [O].

**What it costs.** The cards are code (free). The paid runs of section 8 add about US$40 (spot) to 08's US$33, for a
total near US$75 spot or about US$160 on demand, well inside the US$500 cap. A Spark cannot be rented in any cloud
checked [S runpod.io/pricing; O]: it must be bought (about US$4,699 [S NVIDIA forum]) or borrowed; that is an owner
decision outside the cap (section 12, decision 3).

---

## 1. What the repository already says about tiers

| What | Where | What it says |
| --- | --- | --- |
| The tier names | [R `tools/tiers.py:1-24,41-46`] | `small` = `rtx5090` ("one RTX 5090 (32 GB), small sites"), `medium` = `gb10` (DGX Spark), `large` = `rtxpro6000` ("head hospitals"). A tier installs only from a measured serving record of its own uncapped card; "there is no override" |
| The card-to-profile rule | [R `deploy/gpu_profile.sh:10-38`] | MIG → `shared-quota`; B200 without MIG refused; **any aarch64 host with a GPU → `gb10`** (line 34); "RTX PRO 6000" → `rtxpro6000`; 5090 or RTX PRO 4500 → `rtx5090`; 4090 or 3090 → `rtx4090` (judge alone, never excludes); anything else → `default` |
| No GPU | [R `deploy/install.sh:196-203`] | `MODE=stub` when `nvidia-smi` finds no card; "structured criteria only (FEAS, NAV, COHORT)". The stub endpoint serves DEV and TEST only [R `models/routing.yaml:28-33`] |
| The profile label | [R `deploy/install.sh:591-593`] | `P-PRO6000`, `P-GB10`, `P-5090`; **a stub (CPU) box is labelled `P-GB10`** (the `*)` branch) |
| The CPU model mode | [R `libs/tb_common/config.py:249-250,757`] | `TB_LLM_MODE` accepts `llamacpp`, but no compose file, profile or client branch uses it (grep finds only the config lines) [M 4] |
| RTX PRO 6000 | [R `deploy/docker-compose.rtxpro6000.yml:1-22,68-70,81-83,98`] | "the box for the Japan head hospital and CGMH"; judge 0.40, verifier 0.20, 32k, 16 sequences each, `--enforce-eager`, both resident |
| Spark | [R `deploy/docker-compose.gb10.yml:1-38,57-60,86-89,127,137`; `deploy/gb10-profile.yaml:13-94`] | the pair resident at 16k, 8 sequences, 0.30 + 0.15; driver held at 580.142; a memory limit per service (sum about 117 GiB plus an 8 GiB OS reserve); seven decision-gate rows, all `result: null` |
| 5090 | [R `deploy/docker-compose.rtx5090.yml:1-40,104-109,134-137,178`] | sleep swap, one model awake, 8k, 4 sequences, 0.81 each; "protocol reading (ir_extract) needs 16-32k and runs on the cloud route behind the PHI guard or on a larger box"; measured only on a capped RTX PRO 6000 |
| Two-device Spark form | [R `docs/runbook/08-two-device.md:5`; `deploy/gb10-profile.yaml:58-62`] | the Spark holds the gateway and the models; a CPU workstation holds the rest |
| The reference workstation | [R `docs/plan/33-plan-v7.md:85-95`] | a tower workstation with the RTX PRO 6000 Workstation Edition (600 W) or Max-Q (300 W), 16+ cores, 192-256 GB ECC, two 4 TB NVMe, TPM 2.0, WSL2 |
| The GPU ledger | [R `docs/plan/gpu-ledger.md:10-33`] | one spot RTX PRO 6000 VM and the owner's B200; no 5090, Spark or CPU run queued |
| Lane G's hardware review | [R `docs/handover/lane-g-2026-11-16/review-textmining-hardware-serving.md:152-255`] | specs and street prices of 2026-11-15; bandwidth ceilings; SCREEN throughput per box, mostly [E] estimates. This review re-opens the maker pages and goes further |
| Capacity statement | [R 07 §4.3; plan 9 rev 2 9i] | none exists (T-667) |
| Review 08 | [R 08 §4.3, §4.4] | per-box rates as estimates; a GPU-less box: "an estimate, not measured", run G-6 |

**Summary of the repository's position** [O]: the tier mechanism (detect, refuse unmeasured, pick an override) is
careful. What a tier *means* for the product stops at the model server's flags.

---

## 2. The four machines, from the makers' pages

Opened 2026-11-18. "Not on the page" means the maker's page did not state it.

| | A: CPU server / workstation | B: GeForce RTX 5090 | C: DGX Spark | D: RTX PRO 6000 Workstation Ed. | D: RTX PRO 6000 Max-Q |
| --- | --- | --- | --- | --- | --- |
| Memory for the model | system RAM (DDR5) | 32 GB GDDR7 [S nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5090/] | 128 GB LPDDR5x coherent unified, or 64 GB (OEM partners only) [S nvidia.com/en-us/products/workstations/dgx-spark/] | 96 GB GDDR7 ECC [S nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/] | 96 GB GDDR7 ECC [S …/rtx-pro-6000-max-q/] |
| Memory bandwidth | per socket: channels x MT/s x 8 bytes; a 12-channel DDR5-4800 socket is about 460 GB/s, a 2-channel DDR5-5600 desktop about 90 GB/s [O, arithmetic] | 512-bit; bandwidth not on NVIDIA's page; 1,792 GB/s [S2 tomshardware.com review; lttlabs.com] | **273 GB/s**, 256-bit [S] | 1,792 GB/s [S] | 1,792 GB/s [S] |
| CPU | x86 (AVX-512 recommended for vLLM CPU [S vLLM docs]) | host's | 20 Arm cores: 10 Cortex-X925 + 10 Cortex-A725 [S] | host's | host's |
| FP4 | – | 3,352 "AI TOPS" [S] | 1 PFLOP sparse FP4 [S] | 4,000 TOPS sparse FP4 [S] | 3,511 TOPS sparse FP4 [S] |
| Power | host's (a 1-socket server: opinion 300-500 W) | 575 W card; 1,000 W system PSU [S] | 240 W PSU; GB10 TDP 140 W [S] | 600 W [S] | **300 W** [S] |
| Cooling, size | rack or tower | – | 150 x 150 x 50.5 mm, 1.2 kg [S] | "Double Flow Through", dual slot [S] | "Active", dual slot [S] (blower or not: not on the page) |
| MIG | – | – | – | not confirmed on the page [S] | up to 4 instances [S] |
| Software | any Linux | any Linux | DGX OS (Ubuntu-based); NVIDIA lists playbooks for vLLM, SGLang, llama.cpp and NIM [S build.nvidia.com/spark] | any Linux | any Linux |
| Storage, network | – | – | up to 4 TB NVMe, self-encrypting; ConnectX-7 200 Gb/s, 10 GbE [S] | – | – |

**Prices** (list or street; each with its date):

| | United States | Japan |
| --- | --- | --- |
| A | a cloud stand-in: GCP c3d-standard-60 (AMD Genoa) US$2.72/h on demand, about US$0.58/h spot [S2 calculator.holori.com, snapshot 2026-07-20] | per the server bought; not verified |
| B | MSRP US$1,999 (lane G, 2026-11-15) [R lane G review:163]; street US$4,300 to 9,400 [S2 same] | lowest in-stock **¥1,239,000** on 2026-11-17 [S2 gazlog.jp/entry/gpu-daily-charts/] |
| C | US$3,999 raised to **US$4,699** from 2026-02-23 [S forums.developer.nvidia.com/t/2-23-2026-price-change-announcement/361713]; a 64 GB model "from US$4,999" announced 2026-10 [S2 monoist.itmedia.co.jp] | ELSA ONLINE **¥1,045,000** tax included; NTTPC ¥893,200 but new orders suspended; PC Koubou ¥984,980 out of stock (checked 2026-10-16) [S2 issoh.co.jp/tech/details/9498/] |
| D Workstation Ed. | US$13,250 [S2 tomshardware.com]; NVIDIA's US store US$16,000, marked unavailable [S2 igorslab.de] | ¥1,630,600 at one retailer (date not stated) [S2 via search, not opened]; not verified |
| D Max-Q | not opened | **¥2,499,980** lowest of 5 shops [S2 kakaku.com/item/K0001715624/; date inferred 2026-11-18] |

**What the numbers say** [O]: decode speed on all four is set mostly by memory bandwidth. B and D have the same
bandwidth (1,792 GB/s), so B is D with a third of the memory. C has 1/6.6 of D's bandwidth and 1.3x its memory. A
server CPU has about a quarter of D's bandwidth, a desktop CPU about a twentieth.

---

## 3. Each tier as a whole product shape

The model pair is the same on B, C and D: the judge (a 26B mixture-of-experts model with about 4B parameters active a
token, NVFP4, weights 17.1 GiB) and the verifier (a dense 9B model, AWQ 4-bit, weights 7.5 GiB); a note criterion
excludes only when both agree [R `deploy/docker-compose.rtxpro6000.yml:6-14`]. KV cache per token: judge about
110 KiB, verifier about 45 KiB [R same, lines 11-14, from the fit run]. Call sizes from P2b [R 08 §1.1]: a judge call
is a median 1,290 tokens in and 95 out (p95 3,152 and 139); an `ir_extract` part 1,135 in and 832 out (max 3,025).

### 3.1 Tier A: no GPU

**Memory arithmetic** [O]: the judge as a 4-bit GGUF build is about 16 to 17 GB of RAM; the verifier as AWQ about
7.5 GiB (vLLM CPU) or as a 4-bit GGUF about 5.5 GB. KV at 8k context and 4 slots is under 4 GB for the judge. The
services' memory limits in the base compose sum to about 45 GiB [R `deploy/docker-compose.yml:24-472`, each
`mem_limit`]. **64 GB is the floor, 128 GB comfortable.** Memory is never the limit on tier A; bandwidth and cores are.

**Engine.** Two candidates, both offline:

| Engine | What it gives here | Against | Source |
| --- | --- | --- | --- |
| llama.cpp `llama-server` | MIT; schema-constrained JSON, and the OpenAI wrapper form `{"type": "json_schema", "json_schema": {...}}` "is also accepted" — the exact form TrialBox sends [R `libs/tb_llm/client.py:152-153`]; parallel slots (`-np`), continuous batching on by default, prompt cache on by default | GGUF builds of both models: a model change, requalification, and a licence check of who made the GGUF | [S github.com/ggml-org/llama.cpp tools/server/README.md, lines 178-179, 225, 1465; LICENSE "MIT"] |
| vLLM CPU | the same engine and API as the GPU tiers; AWQ runs on x86, so **the verifier's own AWQ weights could run unchanged**; prebuilt image `vllm/vllm-openai-cpu` | needs AVX-512 for full features (AMD Zen 4 or later); NVFP4 is not in its list, so the judge cannot run on it as shipped; quantisations listed: AWQ, GPTQ, INT8 W8A8 only | [S github.com/vllm-project/vllm docs/getting_started/installation/cpu.md, "Which quantization configs"; cpu.x86.inc.md lines 10, 147, 164] |

**Recommendation** [O]: the judge under llama.cpp (GGUF made by TrialBox from the original weights, so provenance is
ours), the verifier under vLLM CPU on its shipped AWQ weights if the G-6 run shows it is not slower than llama.cpp.
Pin the CPU image by digest, as every other image is [R `deploy/images.lock`].

**Expected speed** (opinion — to be measured in runs A-1 and G-6):

| Machine | Judge call (1,290 in, 95 out) | Verifier call (1,274 in, 104 out) | Pair calls a second | Basis |
| --- | --- | --- | --- | --- |
| Desktop, 16 cores, 2-channel DDR5 | prefill ~150 tok/s → 8.6 s; decode ~15 tok/s → 6.3 s; **~15 s** | prefill ~100 tok/s → 12.7 s; decode ~10 tok/s → 10 s; **~23 s** | **~0.05** (about 190 calls an hour) | a 30B-A3B mixture-of-experts at 12 to 17 tok/s on desktop CPUs [S2 r/LocalLLaMA via lr.eu.psf.lt; forum.radxa.com]; the dense model from bandwidth: 90 GB/s ÷ 5.5 GB a token x 0.6 [O] |
| Server, 1 socket, 12-channel DDR5, 32+ cores | ~4 s | ~6 s | **~0.2** (about 700 an hour) | about 63 tok/s for a 30B-A3B mixture-of-experts on an EPYC 9454P [S2 runaihome.com, underlying run not confirmed]; prefill scales with cores [O] |

**The ladder on tier A** (05 §3a): everything below the large model runs as on D: S0 and S1 rules, S2 keywords, S2b
embedder (already on the CPU on every tier [R `deploy/docker-compose.gb10.yml:137`]). What moves down because the tier
is weak [O]:

- **Note criteria with a certified recall** (05 §3b-A, CAS-13) answer from S2's "zero hits" without the judge. This is
  the risky direction (05 says so); on tier A it is the only way to screen notes overnight for a large hospital, so
  each certificate must exist before a tier-A site may use it.
- **Fixed-form facts by rules** (05 §3b-B: ECOG, NYHA, ejection fraction, smoking, pregnancy) before the model.
- **Protocols compiled elsewhere** (the vendor or the head hospital's tier D box) and shipped as a signed ruleset in the
  bundle, which the install already loads [R `deploy/install.sh:21,273,280`]; the site's investigator still approves.
  There is no box-to-box ruleset export today [M 4: no export or import function besides the bundle].
- **The pair rule stays.** A single CPU model never excludes [R 08 §4.4]; if only the judge runs, note answers send to
  review (`TB_NOTE_BLOCK=never`, as on the 24 GB profile [R `deploy/install.sh:482`]).

**What tier A answers with no model at all.** In sigir's 104 public protocols the compiler classed 1,165 criteria:
282 structured (24 %), 293 mixed (25 %), 93 note (8 %), 497 human (43 %) [R 01 §3 row 10, M 8]. With no model,
structured criteria run fully, the coded half of mixed criteria runs and the rest waits, note criteria wait, and human
criteria go to a person as on every tier [O]. So **about a quarter of criteria are fully answered by rules alone, and
about half are at least partly answered**, if the protocol was compiled somewhere. Terminology without a model resolves
204 of 1,501 concepts today; with full code systems loaded that share rises on every tier alike [R 06 §3.6]. In the
one large run on record, rules removed all but 1,193 of 30,369 patients in scope (3.9 %) before any model call [R 05
§3a; `docs/plan/measurements/g1-2026-11-11/README.md:21-26`].

**Night and interactivity:** nightly only for notes; coded screening interactive. **Batch:** 2 to 4 slots per model
(CPU prefill is compute-bound, so more slots share the same cores) [O]. **Context:** 8k (screening calls fit; a CPU
`ir_extract` at 16k if protocols are read on the box). **Structured output:** JSON schema through llama.cpp's grammar
[S]. **Power, noise, heat:** a 1-socket server, 300 to 500 W, rack noise [O]; a desktop is quiet.

**What tier A CANNOT do** (for the sales sheet): a first load of note criteria at any size above a small hospital
(section 4); an interactive "check this patient's notes now" (tens of seconds a call, queued behind the night); chart
summaries, consent explanations and other model-written text at a usable speed; reading a new protocol on the box
unless a CPU judge is installed (then minutes a protocol).

### 3.2 Tier B: one RTX 5090 (32 GB)

**Memory arithmetic.** 32,607 MiB = 31.8 GiB [R `docker-compose.rtx5090.yml:30`].

| Layout | Budget | KV room | Calls in flight by memory (median 1.4k / p95 3.3k tokens) | State |
| --- | --- | --- | --- | --- |
| Judge awake alone (today) | 0.81 x 31.8 = 25.8 GiB; weights 17.1 | 7.34 GiB = 69,836 tokens [R lane G review:193, fit "sleep-swap"] | ~50 / ~21; **the profile runs 4** [R rtx5090.yml:105] | measured on a capped RTX PRO 6000 |
| Both resident at 8k | 17.1 + 7.5 = 24.6 GiB weights + two CUDA contexts (~1 to 1.5 GiB each) | about 4 to 5 GiB for both: judge ~2.5 GiB = ~24k tokens, verifier ~1.5 GiB = ~35k | judge ~7 at p95; an 8k sequence needs 0.86 GiB (judge), 0.35 GiB (verifier) | **"does not fit (verifier short of KV cache)"** at the split tried on 2026-11-08 [R rtx5090.yml:24-25]; another split (judge 0.62, verifier 0.30) not tried [O] |

**What to tune** [O]:

1. **Sequences 4 → 16** while the judge is awake: memory allows ~21 even at p95 calls. Lane G estimated the SCREEN of
   500 patients x 1 note criterion falls from about 750 s to about 300 s [R lane G review:233-234, E].
2. **Try both resident at 8k, 6 to 8 sequences each** (run B-2). If it fits, the two-phase rounds go: today
   `two_phase` re-runs the screening function in up to 3 rounds on a swap profile [R `services/orchestrator/twophase.py:4-26,48`],
   and the console's chat gets "busy, try again" during the verifier pass [R rtx5090.yml:20].
3. **Or the verifier on the CPU** (vLLM CPU runs AWQ [S]): the verifier is asked on undecided or "fail" judge answers
   only (in tcga 477 of 501 pairs, in sigir 44 of 325 [R 08 §1.1]); on a filter-first night that is a few hundred CPU
   calls, which a server CPU carries (3.1). The GPU then holds the judge alone, awake, with ~7 GiB of KV.
4. CUDA graphs as on D (08 G-1), once the D result is in.

**Engine:** vLLM, as D (same Blackwell consumer architecture; the image is the same digest [R rtx5090.yml:47]).
**Expected speed:** today about 1 call a second (one model at a time, 4 in flight; 1.43 calls a second was measured at
4 in flight on the capped stand-in [R lane G review:233, M there]); tuned about 3.5 [O]. **Context 8k** limits
`ir_extract` (needs 16k to 32k) [R rtx5090.yml:33-34]: **protocols are read elsewhere.** **Power:** 575 W card, a
1,000 W PSU [S]: a gaming tower's noise and heat in a hospital office [O]. **Price:** see section 2; in Japan it now
costs more than a Spark.

**What tier B CANNOT do:** read a protocol on the box; answer a console note check while the verifier pass runs (on
the swap layout); first loads beyond a 300-bed hospital in one night (section 4); ECC memory (consumer card; not on
the page, so not verified).

### 3.3 Tier C: DGX Spark (GB10)

**Memory arithmetic** [R `deploy/gb10-profile.yaml:16-55`; O]: judge 0.30 x 128 = 38.4 GB, verifier 0.15 = 19.2 GB.
After weights and contexts: judge ~19 GiB of KV (~180k tokens), verifier ~10 GiB (~230k tokens): the same room as D.
**Memory is not the limit; bandwidth is.** 32k context costs 3.4 GiB a judge sequence at full length, so **16k is a
choice, not a necessity**: 32k would let the Spark read long protocol parts exactly as D does [O]. The services'
limits sum to about 117 GiB plus an 8 GiB OS reserve [R gb10-profile.yaml:21,40-55], which fits 128 GB with little
spare. **The 64 GB OEM Spark [S] would match the same `gb10` profile** (any aarch64 GPU host does
[R `deploy/gpu_profile.sh:34`]) and over-commit its memory by half: a finding (card 13-6).

**Engine on Arm and unified memory.** NVIDIA documents vLLM, SGLang, llama.cpp and NIM for the Spark [S
build.nvidia.com/spark]. The repository uses the official vLLM v0.32.0 arm64 image "built for CUDA 13 and sm_120,
which runs on the GB10's sm_121 … To be confirmed on a Spark (T-214)" [R `deploy/docker-compose.gb10.yml:46-49`], and
holds the driver at 580.142 because later 580.x builds regressed vLLM on GB10 [R gb10-profile.yaml:23-31]. Keep
vLLM (one engine across B, C, D) [O].

**Expected speed.** Bandwidth ceiling for a single sequence: judge ~98 tok/s, verifier ~30 tok/s [R lane G review:206-209,
E]. Public measurements on a Spark:

| Model, engine | Batch 1 decode | Batched | Prefill | Source |
| --- | --- | --- | --- | --- |
| 8B dense FP8, SGLang | 20.5 tok/s | 368 tok/s at batch 32 | ~7,990 tok/s | [S lmsys.org/blog/2025-10-13-nvidia-dgx-spark/] |
| 20B mixture-of-experts MXFP4, Ollama | 49.7 tok/s | – | 2,053 tok/s | [S same] |
| 120B mixture-of-experts MXFP4, llama.cpp | 45.9 (stock DGX OS) to 60.6 tok/s | – | 1,737 to 1,956 tok/s at 2,048 | [S github.com/ggml-org/llama.cpp/discussions/16578] |
| The judge's family, NVFP4, vLLM | ~52 tok/s | 115 tok/s at 3 parallel | – | [R lane G review:211-213, citing a blog; S2] |

So [O]: a verifier call (104 out) at batch 8 to 16 is ~1 to 2 s of decode; a judge call ~1 s; prefill of 1,290 tokens
~0.2 to 0.6 s. Pair rate today (eager, 8 sequences) about **0.6 calls a second**, tuned (graphs, 16 to 32 sequences)
about **2**; lane G estimated 4 to 6 times D's SCREEN time as written [R lane G review:231-232]. An `ir_extract`
protocol (about 1,760 answer tokens) ~35 to 70 s of decode [O]: **the Spark reads protocols on the box.**

**Embedder.** On the Spark's Arm CPU, unmeasured [R gb10-profile.yaml:83-86, row `embeddings`]. The P2b-era S2b took
about 960 s of CPU for 500 patients before D-910 [R lane G review:23,227]. On C the embedder should move to the GPU side
of unified memory (no copy cost) once it has its own image [R `deploy/docker-compose.gb10.yml:135-137`, ENG-003; O].

**Power, noise, heat:** 240 W supply, 140 W chip, a 15 cm box [S]: the only tier that sits on a desk in a ward office
without a server room [O]. **Price:** ¥1.05 million [S2].

**What tier C CANNOT do (until measured):** any promise at all — the profile is `unmeasured` and every decision-gate
row is empty [R gb10-profile.yaml:13,66-94]; a first load of a 1,200-bed hospital in under a week (section 4); run the
64 GB variant on today's profile; take driver updates outside a signed bundle [R gb10.yml:26-28].

### 3.4 Tier D: one RTX PRO 6000 (96 GB)

**Memory arithmetic.** 97,887 MiB; the pair holds 62,574 MiB today [R `deploy/measured/serving_config.rtxpro6000.json`, `memory_used_mib`]. Judge
pool ~180k tokens, verifier ~200k [R rtxpro6000.yml:11-14]; at most 12 % ever used [R 08 §1.5]. At 64 sequences x 1.4k
tokens the judge needs ~90k tokens; at 64 x 3.3k (p95) ~211k, more than 180k. **Raise the judge to 0.50 and the
verifier to 0.25** when 08's G-2 sets 48 to 64 sequences: +9.6 GiB judge KV (~+90k tokens), and 25 GiB still free for
graphs and the embedder [O].

**Engine, quantisation, pair:** as 08 §2 (vLLM, NVFP4 + AWQ, two models). Not repeated.

**Expected speed:** 3.06 calls a second today [R 08 M 4]; 9 a target after 08's P1 and G-1 [R 08 §4.1, O]. One
`ir_extract` part at 36.8 tok/s today [R 08 M 3].

**Workstation Edition or Max-Q** [O]: the same bandwidth, half the power. Today's peak was 293 W [R 08 §1.5], so the
Max-Q would not have slowed P2b. After tuning (more sequences, graphs) the card works harder; the 300 W cap may then
cost some speed. Run D-2 measures it with a 300 W power limit on the cloud card. In a hospital office the 600 W card
heats a room like a small heater [O]; the Max-Q also supports MIG (4 instances) [S], which could hard-split judge and
verifier (unmeasured with this pair [R lane G review:248]).

**What tier D CANNOT do:** serve several hospitals' first loads at once (one site per box; 08 §4.2: 500,000 patients x
30 studies first load is days); run the B200's MIG platform layout (that is `deploy/platform`).

### 3.5 The four shapes side by side

| | A | B | C | D |
| --- | --- | --- | --- | --- |
| Models on the box | CPU judge (and verifier if fast enough), or none | pair, one awake (today); pair resident or verifier on CPU (proposed) | pair resident | pair resident |
| Protocol reading | elsewhere, or CPU judge (minutes) | elsewhere | on box | on box |
| Context | 8k (16k for `ir_extract`) | 8k | 16k → **32k** proposed | 32k |
| Sequences (judge / verifier) | 2-4 slots | 4 → **16** / 16 | 8 → **16-32** | 16 → **48-64** (08 G-2) |
| Embedder | CPU (competes with the CPU model: schedule apart) | CPU | CPU → GPU proposed | CPU → GPU proposed (25 GiB free) |
| Reranker | none (the `rerank` role is declared [R `models/routing.yaml:106`] but no service serves it [M 4]) | none | none | none |
| Screening mode | nightly for notes | nightly; interactive only when the judge is awake | nightly + interactive lane | nightly + interactive lane (08-8) |
| Ladder emphasis | rules, terminology, certified zero-hit answers, rules for fixed-form facts | rules first; the large model for notes | as D, fewer calls a second | as designed (05) |

---

## 4. The night, per hospital size and tier

Formula: model hours = patients in scope x studies x share screened that night x calls per patient and study ÷ calls a
second ÷ 3,600 [R 08 §4.1]. Inputs [O unless marked]: patients in scope = 100 per bed (a two-year window of
in- and outpatients; the site must give its own figure, section 13); open studies 5 / 15 / 30 for 300 / 600 / 1,200
beds; delta night = 3 % of patients new or booked [R 08 §4.2]; calls per patient and study: light 0.065
[R `docs/plan/measurements/g3-50k-2026-11-13/capacity_inputs.json`, superseded run], typical 0.22 (6,704 calls for
30,369 patients in scope in the 50,000 run [R 05 §3a], superseded), heavy 0.5 [R 08 §4.1, O]. Calls a second
(today / tuned): A desktop 0.05, A server 0.2, B 1.0 / 3.5, C 0.6 / 2.0, D 3.06 / 9 [sections 3.1-3.4; only D's 3.06
is measured]. A night's usable window is 5.6 h (8 h x 0.7) [R 08 §4.1]. [M 2]

**Delta night, model hours** (today / tuned; A has one figure):

| Beds | Load | Calls | A desktop | A server | B | C | D |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 300 | light | 292 | 1.6 | 0.4 | 0.1 / 0.0 | 0.1 / 0.0 | 0.0 / 0.0 |
| 300 | typical | 990 | 5.5 | 1.4 | 0.3 / 0.1 | 0.5 / 0.1 | 0.1 / 0.0 |
| 300 | heavy | 2,250 | **12.5** | 3.1 | 0.6 / 0.2 | 1.0 / 0.3 | 0.2 / 0.1 |
| 600 | light | 1,755 | **9.8** | 2.4 | 0.5 / 0.1 | 0.8 / 0.2 | 0.2 / 0.1 |
| 600 | typical | 5,940 | **33.0** | **8.2** | 1.6 / 0.5 | 2.8 / 0.8 | 0.5 / 0.2 |
| 600 | heavy | 13,500 | **75.0** | **18.8** | 3.8 / 1.1 | **6.2** / 1.9 | 1.2 / 0.4 |
| 1,200 | light | 7,020 | **39.0** | **9.8** | 1.9 / 0.6 | 3.2 / 1.0 | 0.6 / 0.2 |
| 1,200 | typical | 23,760 | **132** | **33.0** | **6.6** / 1.9 | **11.0** / 3.3 | 2.2 / 0.7 |
| 1,200 | heavy | 54,000 | **300** | **75.0** | **15.0** / 4.3 | **25.0** / **7.5** | 4.9 / 1.7 |

Bold: does not fit the 5.6 h window.

**First load** (every patient once; model hours, today / tuned, and nights at 5.6 h):

| Beds | Load | Calls | B | C | D |
| --- | --- | --- | --- | --- | --- |
| 300 | typical | 33,000 | 9.2 / 2.6 h (2 / 1 nights) | 15.3 / 4.6 h (3 / 1) | 3.0 / 1.0 h (1 / 1) |
| 600 | typical | 198,000 | 55 / 15.7 h (10 / 3) | 92 / 27.5 h (17 / 5) | 18.0 / 6.1 h (4 / 2) |
| 1,200 | typical | 792,000 | 220 / 63 h (40 / 12) | 367 / 110 h (66 / 20) | 72 / 24 h (13 / 5) |

Tier A at 600 beds typical: 1,100 h on a desktop, 275 h on a server: **a first load of note criteria is not a product
on tier A** [O].

**What it means** [O]:

- On B, C and D the delta night fits every size once tuned, except C and B at 1,200 beds heavy. The first load is the
  real difference between tiers: it is the day-one experience (section 7).
- On A, notes fit a delta night only at 300 beds light or typical on a server. Everything else needs the ladder to
  move down (3.1) or rulesets that avoid note criteria.
- **Protocol reading per tier** (one protocol, about 1.9 `ir_extract` parts and 6.5 `concept_map` calls [R 08 M 5]):
  D 52 s of model time today (graphs: about 20 s); C about 1 to 2 min; A desktop about 3 min with a CPU judge
  (1,760 answer tokens at ~15 tok/s plus prefill), server about 1 min; B not on the box [O]. The compile's CPU side,
  the 117 s of 08 §1.3, is the same on every tier and dominates on D.
- The part-size rule assumes 40 tokens a second [R 08 P11; `services/criteria_compiler/service.py:127`]. At 15 tok/s
  on a CPU every part times out and is split again: **the rate must come from the tier's serving record** (card 13-9).

---

## 5. Architecture differences by tier

### 5.1 Where the model is

| Tier | The large model | When there is no model at all |
| --- | --- | --- |
| A | **absent by default; a CPU judge as an option; or "remote within the hospital"**: a tier-A box may point its `serving` endpoint at a GPU box elsewhere in the same hospital network (the endpoint zone `perimeter` already covers "the attested tenant" [R `models/routing.yaml:11-12,34-40`]) | coded criteria and terminology (3.1: about a quarter fully, half partly); note criteria wait with a named outage [R 08 §4.4]; protocols arrive compiled |
| B | on the card, one awake | as A, after the breaker opens [R `services/gateway/load.py:5-10`] |
| C | on the box | as A |
| D | on the card | as A |

"Remote within the hospital" is the multicenter answer too [O]: a group's head hospital on tier D compiles each
protocol once; partner hospitals on A, B or C receive the approved ruleset through the signed bundle and approve it
locally. The bundle path exists; a box-to-box path does not (card 13-3).

### 5.2 Queueing, back-pressure and what the user sees

Today, on every tier [R]: an endpoint takes as many calls as its server runs sequences; an interactive call waits
0.5 s for a slot, then gets `model_busy` [R `services/gateway/load.py:3-5,25-26`]; a breaker opens after 5 failures
[R same, lines 6-10,27-28]; each role has a degraded mode — the judge `deterministic_only`, protocol roles `queue` or
`manual`, the embedder `s2b_off` [R `models/routing.yaml:87-114`].

Per tier, what should differ [O]:

| | A | B | C | D |
| --- | --- | --- | --- | --- |
| Interactive note check | not offered; "queued for tonight" with the expected time | offered while the judge is awake; on the verifier pass "the model is busy until about HH:MM" (not "try again") | offered; 2 reserved slots (08-8) | offered; 2 reserved slots |
| Protocol upload | "sent to the head hospital / vendor for reading; you will be told when it is back" | same as A | read on the box, progress per part | read on the box, progress per part |
| Night overrun | the night budget [R `services/orchestrator/scenarios/microbatch.py:30`] sized from the tier's rate, and the console shows "first load: night 3 of 11" | same | same | same |
| Degraded banner | permanent "notes are not read on this box" unless a CPU model is installed | on model failure | on model failure | on model failure |

### 5.3 One compose profile per tier, chosen by the installer

Today: B, C, D have an override each; A has none (the base file with the stub, which PRODUCTION refuses). Proposed
(card 13-1, 13-2) [O]:

- `docker-compose.cpu.yml`: `llm-service` and `llm-verifier` as CPU model servers behind `model-guard`, pinned by
  digest; memory limits from a `cpu-profile.yaml` sized like `deploy/gb10-profile.yaml`; `TB_PROFILE=P-CPU`
  (today a CPU box says `P-GB10` [R `deploy/install.sh:592`]).
- `deploy/gpu_profile.sh` adds `cpu` when no card is found and the host has AVX-512 or 64 GB+, and splits `gb10` by the
  memory it finds (128 GB / 64 GB).
- `tools/tiers.py` adds the tier `basic` = `cpu`, measured like the others (a serving record of its own machine class).
- One **tier record** (YAML, beside the serving record) holds what the rest of the product reads: sequences, context,
  roles on the box, protocol route, night budget, interactive lane, console promises. Today these live in four places
  (compose comments, `install.sh`, `load.py`'s `SLOTS = 16`, the microbatch budget).

### 5.4 Validation per tier (review 07)

**Is each tier validated separately? Today: no.** The machinery is per profile: a tier installs only on a serving
record of its own uncapped card [R `tools/tiers.py:1-7`], and `qualify` runs pin, schema, longest prompt, canary,
pair gate, determinism, throughput and injection for a named profile [R `tools/qualify.py:1-50`]. It has been run for
`rtxpro6000` only [R `deploy/measured/README.md:10`]. The audit and validation story is the same
on every tier by design (the same prompts, the same gate, the same record) [O].

**What separate validation costs** [O]: per tier, one qualification (about 2 to 3 h on the box: the pair gate,
determinism at the tier's concurrency, the 54-case canary) plus V1's accuracy replay on the tier's serving. The
accuracy changes per tier for three reasons only: context (8k cuts excerpts, so more "left out" and more unknowns
[R lane G review:242]), the engine (vLLM vs llama.cpp numerics) and the quantisation (GGUF on A). B and C use the same
weights and engine as D, so their qualification is short; A is a model change and needs the full model change
protocol [R `docs/validation/model-change-protocol.md`]. Costs in section 8.

---

## 6. Tuning of every aspect, with the measurement for each

"Today" is the best number on record; "target" is opinion. Each row names the card (section 11) and the run that
proves it (section 8). Rows marked "08" are 08's and not repeated here.

| Aspect | Today | Target | How | Card / run |
| --- | --- | --- | --- | --- |
| Ingest, SS-MIX2 per message | 12,496 FHIR resources in 14 s, about 740 a second, 4 cores [R 01 §1.3] | same per core; report per connector | bench `ingest` per source type; per-message histogram in the ingest report | 13-10 / S-8 |
| Ingest, one night | 98.8 s for 5,001 patients [R 01 §2]; 805 s at 50,000 [R 01 §6] | 50,000 in under 600 s on D's host | 01's B1-S1, B1-F1; row mapper per 01 | 01 / S-8 |
| Ingest on Arm (C) and on A's CPU while the CPU model runs | not measured | inside the night with the model idle | schedule ingest before the model's window on A; measure arm64 | 13-12 / C-2, A-1 |
| PostgreSQL settings by RAM | sized from `TB_MEM_DB` by PGTune rules: shared_buffers 1/4, effective_cache_size 3/4 [R `tools/trialbox/pgsize.py:1-20`]; `work_mem` and `max_connections` not sized [R `deploy/docker-compose.yml:95-107`] | `TB_MEM_DB` per tier (4 GiB base [R `docker-compose.yml:135`], 8 GiB on C [R gb10.yml:150]; 16 to 32 GiB on D's 192 GB host) and `work_mem` from it | tier record sets `TB_MEM_DB` | 13-11 / S-6 |
| Hot query plans | not on record | every hot query an index scan; plans stored | `pg_stat_statements` on the 50k nightly; `EXPLAIN (ANALYZE, BUFFERS)` of the top 10 | 13-11 / S-6 |
| Connection handling | one connection per store under a lock, no pool [R `libs/tb_common/db.py:10-19`]; the judged-pair store makes ~3 statements a model call [R 08 §6.2] | fine at 3 calls a second; at D's 9 to 18 calls a second ~27 to 54 serialised statements a second: measure the lock wait | time the store lock in G-2 | 13-11 / G-2 |
| Vacuum | autovacuum defaults; no setting found [M 4] | default is right for this size [O]; watch dead tuples on the trace and audit tables | `pg_stat_user_tables` in the 50k nightly | 13-11 / S-6 |
| Lake (DuckDB) | 40 % of `TB_MEM_LAKE` per worker [R `docker-compose.yml:184`]; 6 GiB on C | by tier from RAM | tier record | 13-11 |
| Compile of a protocol (model) | 52 s a protocol [R 08 §1.3] | 20 s (D, graphs); per tier in 4 | 08 G-1, G-5; 08-5 | 08 |
| The 117 s between compile and screen | mean 116.6 s [R 08 M 5] | under 15 s | 08-4 (profile APPROVE on the stub) | 08 / S-7 |
| Candidate pre-filter | rules left 1,193 of 30,369 (3.9 %) for the model [R 05 §3a]; tcga's all-note criterion: 500 of 500 reached the model [M 1]; jmed: 594 → 0 model calls (no note criteria) [M 1] | a pre-filter report per study per night: patients removed by S0, S1, S2, S2b before any call | the funnel already exists per screen report [M 1]; surface it per tier in the console | 13-13 |
| Prompt construction and prefix reuse | prefill ~3 % of a judge call on D [R 08 M 7] | on A and C prefill is a larger share (compute-bound) [O]: prefix caching matters there | llama.cpp `cache_prompt` (on by default [S]); vLLM prefix caching stated on C | 13-7 / C-1, A-1 |
| Gateway overhead per call | ~0.1 s profiled on the stub [R 08 §6.2] | 50 ms p95 | 08-7 | 08 |
| Gateway slots | `SLOTS = 16` constant, else the serving record [R `services/gateway/load.py:1-6,25`] | from the tier record | 13-2 | 13-2 |
| Judge / verifier pair | serial in a thread [R 08 P2]; two-phase rounds on B [R `twophase.py:48`] | threads = 2 x seqs (08 P1); on B both resident or verifier on CPU | B-1, B-2 | 13-5 |
| Answer length | judge cap 1,024 tokens [R 08 P6] | 384; on A and C every answer token costs more | 08-6 | 08 |
| Result writing | not timed separately; "pack, certificate, outputs" 18.4 s at 5,000 [R 08 §6.3] | 10 s | 01 B1-F2 | 01 |
| Embedder (S2b) | CPU on every tier [R gb10.yml:137]; ~960 s for 500 patients before D-910 [R lane G review:23,227] | GPU on C and D; on A scheduled apart from the CPU model | own GPU image (ENG-003) | 13-8 / C-1, D-1 |
| Console page time, ten pages | **no per-page timing exists** [M 3] | p95 server time under 300 ms on every tier at 50k patients [O] | a timing middleware writing `Server-Timing`; walk `/home`, `/jobs`, `/pilot/jobs/{job_id}`, `/pilot/case`, `/pilot/protocol`, `/pilot/registry/{ruleset}`, `/audit/patients/{pid}`, `/data/items`, `/reports`, `/admin/ops` [R route list in `services/console/*.py`] | 13-14 / S-1 |
| Console payload | static assets 108 KB in all [M 3] | page HTML under 100 KB gzipped; on phones (09) | measure in the same walk | 13-14 / S-1 |
| Start-up, Python side | import of each service's app: 0.6 to 1.5 s, 66 to 148 MB RSS each [M 5] | not the problem | – | – |
| Start-up, whole box | model servers allowed 600 to 900 s to become healthy [R gb10.yml:72,118]; GPU bundle load "10-20 minutes" [R `deploy/install.sh:280`]; never timed end to end | power-on to "ready" under 15 min on D; stated per tier | time each healthcheck from `docker compose up`; CUDA graph capture adds to it (08) | 13-15 / S-3 |
| Idle memory per service | caps known [R compose files]; never measured at idle [R gb10-profile.yaml:40-56, all `null`] | measured per tier, caps set from peaks | `docker stats --no-stream` after an idle hour | 13-15 / S-2, C-1 |
| Backup and restore time | drills green on CI runners; "no restore timed on real hardware" [R 07 §3 row 5] | RPO and RTO stated per tier | the restore drill on the 50k stub, timed; then on the delivered box | 13-16 / S-4 |
| Update time | drill green on CI [R 07 §3] | stated per tier, with the model reload | time `apply_update` on the stub and on a GPU box | 13-16 / S-5 |

---

## 7. Flow and smoothness

### 7.1 Where the user waits without progress

| Wait | Who | How long (D today) | Progress shown? | Proposed |
| --- | --- | --- | --- | --- |
| Protocol upload → draft criteria | coordinator | ~52 s model + parts in sequence [R 08 §1.3] | not per part [O, not verified in the console] | "part 2 of 3 read" per `ir_extract` part (13-14) |
| APPROVE → first screen | investigator, coordinator | 117 s mean [R 08 M 5] | none known | fix (08-4), then a step list |
| First load | everyone, day one | hours to days (section 4) | the night budget message only [R `microbatch.py:691-714`] | "first load: 1,840 of 60,000 patients, about 3 more nights" on the home page |
| A note check from the console | coordinator | 3 s on D; `model_busy` after 0.5 s if the night fills the slots [R 08 P13] | an error | the interactive lane (08-8); on A and B a queued promise with a time |
| Model start after a reboot | admin | up to 15 min [R gb10.yml:72,118] | a health page | "models loading, about N minutes" |
| Update | admin | not timed | not verified | timed per tier (13-16) |

### 7.2 First run per tier: power-on to the first screened patient list

[O; each step's time from the cited source where one exists]

| Step | A | B | C | D |
| --- | --- | --- | --- | --- |
| Install the bundle | 10-20 min [R install.sh:280] | same | same | same |
| Models ready | CPU model: a few minutes [O] | two loads + sleep + wake [R rtx5090.yml:21-27] | up to 15 min [R gb10.yml:72,118] | about 10 min [O] |
| First ingest (60,000 patients) | ~16 min [R 01: 805 s at 50,000, scaled] | same | Arm: not measured | same as A |
| First protocol | arrives compiled; approve | arrives compiled; approve | read on box, 1-2 min + 117 s | read on box, ~1 min + 117 s |
| First list (coded criteria) | minutes | minutes | minutes | minutes |
| First list including notes (600 beds, 1 study, typical) | ~1 night per 13,200 patients on a server [O] | ~3.7 h today | ~6 h today | ~1.2 h today |

**Recommendation** [O]: on every tier the first list the user sees is the coded one, within the first hour, marked
"notes not yet read"; the note-checked list follows. Day one must not look empty.

### 7.3 The night plan

Today: ingest 02:00 daily, MICROBATCH Monday 03:00 and after every ingest for new booked patients, NAV Monday 03:30,
COHORT monthly, retention 05:00 [R `deploy/settings.example.yaml:32`; `services/orchestrator/scheduler.py:1-6`].

Proposed per tier [O]:

| Time | A | B | C and D |
| --- | --- | --- | --- |
| 00:00-02:00 | embedder increment (CPU) | embedder | embedder (GPU on C, D) |
| 02:00 | ingest | ingest | ingest |
| ~02:20 | rules S0-S2b for all studies | same | same |
| ~02:30-06:00 | CPU model on the delta's note pairs, highest-priority study first; stop at 06:00 | judge pass, swap, verifier pass (or both resident) | pair at full concurrency; first-load slices fill the rest of the night |
| 06:00-08:00 | backup | backup | backup |
| Day | no model calls except queued protocol reading (A with CPU judge) | judge awake for the console | interactive lane |

### 7.4 A protocol added at 10:00: candidates the same day?

| Tier | Path | Same day? |
| --- | --- | --- |
| D | upload 10:00 → read on box (~3 min with the 117 s) → investigator approves → SCREEN on demand: coded list in minutes; note criteria at 9 calls a second tuned, a 600-bed typical study (60,000 x 0.22 = 13,200 calls) in ~25 min | **yes**, by late morning [O] |
| C | same, read in ~4 min; notes at ~2 calls a second: ~1.8 h | **yes**, early afternoon |
| B | protocol sent to the head hospital or vendor for reading (hours, depends on people); then coded list at once; notes on B: ~1 h tuned (13,200 at 3.5/s) | **coded list yes if the ruleset returns by afternoon; notes that night** |
| A | as B for the protocol; coded list at once; notes tonight within the night budget | **coded list only** |

---

## 8. The run list

Rules: nothing here was run; each run needs the owner's yes; rates from the repository (GCP spot RTX PRO 6000 at
US$2.74/h, on demand US$8.22/h [R `tools/complete_run.py:1636-1640` via 08 §5]) or the source given. 08's G-0 to G-7
come first and are not repeated; this list is what each other tier adds. Free runs (S-*) use the stub on CI or the
integrator's machine.

| # | Tier | Machine (stand-in) | Command (from `trialbox/`) | Duration | Cost spot (on demand) | Yields |
| --- | --- | --- | --- | --- | --- | --- |
| S-1 | all | stub stack | after card 13-14: `make up-test`, then a walk of the ten pages of section 6 with `curl -w '%{time_total} %{size_download}'`, 20 times each, at 5,000 and 50,000 synthetic patients | 1 h | free | server time p50/p95 and bytes per page |
| S-2 | all | stub stack | `docker stats --no-stream` after an idle hour, then after a 5,000-patient night | 2 h | free | idle and peak memory per service |
| S-3 | all | stub stack | time `docker compose up --wait` from cold, per service health time from `docker inspect` | 0.5 h | free | start-up per service |
| S-4 | all | stub stack, 50,000 patients | a backup, then `trialbox restore-drill <backup file> --key <key>` [R `tools/trialbox/restore_drill.py:1-4`], each timed | 1 h | free | backup and restore minutes (RTO) |
| S-5 | all | stub stack | the update drill from release N-1 (`tools/apply_update.sh`), timed | 1 h | free | update minutes |
| S-6 | all | stub, scale-50k nightly | `pg_stat_statements` on; `EXPLAIN (ANALYZE, BUFFERS)` of the top 10 by total time; `pg_stat_user_tables` | 1 h | free | hot plans, missing indexes, dead tuples |
| S-7 | all | stub | 08's G-3 (profile APPROVE) | 1 h | free | the 117 s by part |
| S-8 | all | stub | `python tools/bench.py --tasks ingest --ingest-patients 20000`, once per source type (CSV, SS-MIX2, FHIR files) | 1.5 h | free | ingest per connector and per message |
| D-1 | D | GCP spot RTX PRO 6000 | 08's G-1, G-2, G-4, G-5, with the judge at 0.50 and the verifier at 0.25 added as a G-2 point, and the embedder on the GPU (after 13-8) | 12 h | US$33 (US$99) [R 08 §5] | the tuned D rate; KV use at 64 seqs |
| D-2 | D (Max-Q) | same VM, `nvidia-smi -pl 300` | G-2's best setting, tcga:500, at 300 W and uncapped: `deploy/gcp/box-run.sh --mode validation --steps acc --only tcga:500 --serving <G-2 best>` with `nvidia-smi dmon -s pu -d 5` beside it | 1.5 h | US$4 (US$12) | calls a second at 300 W vs uncapped; whether the Max-Q costs speed. Whether this card accepts a 300 W limit is not verified |
| B-1 | B | GCP VM, card capped to 32 GB (the existing stand-in, `deploy/gcp/gpu-sim-startup.sh` [R `docs/runbook/11-cloud-runs.md:39`]) | tcga:500 with the 5090 profile at 4 and at 16 judge sequences | 2 h | US$5.5 (US$16) | B's calls a second today and tuned |
| B-2 | B | same | the capped stand-in with the 5090 overlay and `TB_MODEL_SWAP=off`, `JUDGE_GPU_MEM_UTIL=0.62`, `VERIFIER_GPU_MEM_UTIL=0.30`, 8 sequences each (the 2026-11-08 fit script named in lane G's audit is no longer in `deploy/gcp/`); then the canary, `python3 -m tools.trialbox selftest` | 1 h | US$2.7 (US$8) | whether the pair fits without the swap |
| B-3 | B | a physical RTX 5090 (RunPod secure cloud, US$1.39/h [S runpod.io/pricing]) — a new vendor: owner decision 4 | vLLM with the 5090 flags; `python -m tools.trialbox eval qualify --profile rtx5090 --gateway-url …` with public data only | 4 h | ~US$6 + storage | the first real-card serving record (D-112); capping and the real card compared |
| C-1 | C | **no cloud stand-in**: a bought or loaned Spark (owner decision 3). Capping a cloud card does not imitate 273 GB/s | `make spark-e2e`; `qualify --profile gb10`; tcga:500 at 8 and 16 to 32 sequences, eager and graphs, 16k and 32k; `docker stats` against `nvidia-smi` for the unified-memory peaks | 2 days | US$0 on a loan; US$4,699 if bought | gb10-profile's seven gate rows; C's real rate |
| C-2 | C (Arm CPU side) | GCP Axion (c4a, Arm) VM, no GPU | build the arm64 images (`make images PLATFORM=linux/arm64`); `python tools/bench.py --gate` at 5,000 on arm64 | 3 h | about US$5 to 10 (price not verified) | ingest, lake and cascade speed on Arm |
| A-1 | A | GCP c3d-standard-60 (Genoa, AVX-512) [S2 holori] | llama.cpp `llama-server` with a 4-bit GGUF of the judge (made from the original weights), vLLM CPU with the verifier's AWQ weights; replay 200 judge and 40 `ir_extract` prompts of P2b through the gateway (08-7's set); `llama-bench` at 8, 16, 30 threads | 4 h | US$2.4 (US$11) | A-server calls a second; protocol minutes; answers vs D |
| A-2 | A | the owner's own workstation (08's G-6) | as A-1 | 4 h | free | A-desktop rate |
| A-3 | A | GCP Intel Xeon with AMX (c4 family) | as A-1, judge only | 2 h | about US$5 (on demand, not verified) | whether AMX prefill changes the choice of server |
| V-B, V-C, V-A | B, C, A | the boxes above | V1 accuracy replay and qualification per tier (5.4) | 3 h each | inside B-3, C-1, A-1 | the per-tier validation record |

**Order:** S-1 to S-8 (free) and 08's G-0 first; then D-1, D-2; then B-1, B-2 (cheap, decide the B layout); then A-1
and A-2; B-3 only if tier B is still offered after section 9; C-1 when a Spark is in hand.

**Total paid, against the US$500 cap:** D-1 US$33, D-2 US$4, B-1 US$5.5, B-2 US$2.7, B-3 US$6, C-2 up to US$10, A-1
US$2.4, A-3 US$5: **about US$69 spot, about US$170 on demand** [O, sums of the rows]. The Spark (C-1), if bought, is
outside the cap.

---

## 9. Buying advice for the first site (Japan)

**The site's size.** The first site (a general hospital in Japan) is a hospital of about 500 to 600 beds — the owner
to confirm. This review uses the 600-bed row of section 4.

**The arithmetic for 600 beds** (section 4, typical load, 15 studies): delta night D 0.5 h today; C 2.8 h; B 1.6 h;
A server 8.2 h (does not fit). First load: D 4 nights today, 2 tuned; C 17 nights today, 5 tuned; B 10 / 3.

**Recommendation** [O]: **tier D, the RTX PRO 6000 Max-Q (300 W)**, fitted by the workstation's maker
(plan v7's list: Dell Pro Max Tower T2, HP Z8 Fury G5, Lenovo ThinkStation P5 or PX [R `docs/plan/33-plan-v7.md:89-91`]).
Reasons: it is the only measured card; it reads protocols on the box (the head hospital of a multicenter group must);
it carries the first load in days, not weeks; 300 W keeps an office cool and quiet; MIG is available on the Max-Q [S].
Run D-2 before the order is final; if the 300 W cap costs more than 20 % of the tuned rate, the Workstation Edition
(600 W) is the alternative, with a server room.

| Option | Card or box price in Japan | Availability | For the first site |
| --- | --- | --- | --- |
| D, Max-Q | ¥2,499,980 card, lowest of 5 shops [S2 kakaku.com] + the workstation (not priced here) | listed at 5 shops | **recommended** |
| D, Workstation Ed. | ¥1,630,600 at one retailer, date unknown [S2, not opened] | not verified | alternative after D-2 |
| C, Spark | ¥1,045,000 tax included (ELSA ONLINE); NTTPC suspended; PC Koubou out of stock (2026-10-16) [S2 issoh.co.jp] | thin | a partner hospital, after C-1 |
| B, RTX 5090 | ¥1,239,000 lowest in stock (2026-11-17) [S2 gazlog.jp] | in stock | **no**: costs more than a Spark, cannot read protocols |
| A, CPU server | per the server | – | partner hospitals' coded screening only |

---

## 10. Gap table

| What the product does today | What is needed | Evidence |
| --- | --- | --- |
| Three GPU tiers; a GPU-less box is "stub", refused in PRODUCTION | tier A as a product: CPU profile, compiled rulesets shipped, honest promises | [R `tools/tiers.py:41`; `install.sh:202`; `routing.yaml:28-33`] |
| `TB_LLM_MODE=llamacpp` accepted, unused | a CPU model server profile behind model-guard | [R `config.py:249`; M 4] |
| A CPU box labelled `P-GB10` | `P-CPU` | [R `install.sh:592`] |
| Any aarch64 GPU host is `gb10` with 128 GB limits | split by memory (64 GB OEM Spark) | [R `gpu_profile.sh:34`; `gb10-profile.yaml:40-55`; S NVIDIA Spark page] |
| Tier knobs in compose comments, `install.sh`, `load.py`, microbatch | one tier record read by gateway, scheduler, console | [R the four files] |
| 5090: 4 sequences though memory allows ~21 | 16; test both resident | [R rtx5090.yml:105; lane G fit] |
| Spark at 16k "to save memory" it has | 32k, after C-1 | [R gb10.yml:57; O] |
| Part size assumes 40 tok/s on every tier | rate from the tier's record | [R `service.py:127`] |
| Embedder on the CPU on every tier | GPU on C and D | [R gb10.yml:135-137] |
| No reranker served | decide: serve one on D, or drop the role | [R `routing.yaml:106`; M 4] |
| No per-page console timing | Server-Timing middleware and a page budget | [M 3] |
| Idle memory, start-up, restore, update never timed on hardware | timed per tier | [R 07 §3; gb10-profile.yaml `null` peaks] |
| Qualification run for one profile | one per tier sold | [R `qualify.py:1-10`; measured README] |
| No box-to-box ruleset path | head hospital compiles, partners approve | [M 4; R install.sh:21] |
| Console shows errors where the tier lacks a capability | tier-aware wording and a "first load: night N of M" status | [R 08 P13; O] |

---

## 11. Cards for plan 10

| Card | What | Size | Lane (guess) | Waits for | Proof |
| --- | --- | --- | --- | --- | --- |
| 13-1 | Tier A profile: `docker-compose.cpu.yml` (CPU model servers behind model-guard, digests pinned), `cpu-profile.yaml` memory limits, `gpu_profile.sh` → `cpu`, `tiers.py` tier `basic`, `TB_PROFILE=P-CPU` | L | D | A-1, decision 1 | install on a CPU VM reaches a qualified box; the stub stays DEV/TEST only |
| 13-2 | The tier record: sequences, context, roles on box, protocol route, night budget, interactive lane, console promises; read by gateway slots, scheduler and console | M | D, A2 | – | a test that every tier record is complete and every reader uses it; `SLOTS = 16` gone |
| 13-3 | Ruleset hand-over between boxes: an approved ruleset exported signed by a head-hospital box, imported and approved at a partner (same signature chain as the bundle) | M | A2, D | owner decision 2 | a partner stub box screens with a ruleset compiled on another |
| 13-4 | B: judge sequences 4 → 16 and screen concurrency to match; the swap kept until B-2 | S | D | B-1 | B-1's record |
| 13-5 | B: both resident at 8k (if B-2 fits), else verifier on vLLM CPU; two-phase only where still needed | M | D, A2 | B-2 | B-1 re-run: no swap; canary green |
| 13-6 | C: split `gb10` by memory; a `gb10-64` profile or a refusal for the 64 GB Spark | S | D | – | `gpu_profile.sh` test with a 64 GB host; limits fit |
| 13-7 | C: 32k context, CUDA graphs, 16-32 sequences, prefix caching stated; gate rows filled | S | D | C-1 | gb10-profile.yaml `status: measured` |
| 13-8 | Embedder on the GPU on C and D (its own image, ENG-003) | M | D | D-1 | S2b time on the 50k night; memory record |
| 13-9 | `TB_EXTRACT_RATE_PER_S` and part size from the tier's serving record (all tiers, not only D: 08-10) | S | A2 | A-1, C-1 | a CPU replay with no part given up |
| 13-10 | Ingest report per connector and per message (count, seconds, p95 per message) | S | E | – | S-8 |
| 13-11 | PostgreSQL per tier: `TB_MEM_DB`, `work_mem`, `max_connections` from the tier record; `pg_stat_statements`; the store-lock wait timed | M | B2 | S-6 | S-6 plans; G-2 lock wait under 5 ms p95 |
| 13-12 | Night plan per tier (section 7.3) in `settings.schedule` defaults by tier | S | A2 | 13-2 | the scheduler test per tier |
| 13-13 | Pre-filter report per study per night: patients removed at each stage before any model call, in the console | S | A2, C2 | – | the report on the 50k nightly |
| 13-14 | Console timing: Server-Timing middleware, the ten-page walk, a budget (p95 300 ms server time) in the nightly; progress for protocol parts and the first load | M | C2 | – | S-1 in the nightly; a planted slow page fails |
| 13-15 | Start-up and idle memory measured per tier and written into the profile records; memory caps from measured peaks | S | D | S-2, S-3, C-1 | records filled |
| 13-16 | Backup, restore and update timed per tier; RTO and RPO stated | S | D | S-4, S-5 | the drill record |
| 13-17 | Qualify each tier sold: `qualify --profile` for rtx5090, gb10 and cpu; V1 replay per tier | M | G | B-3, C-1, A-1 | three records beside `rtxpro6000`'s |
| 13-18 | Tier-aware console wording: what the tier cannot do (protocol route, interactive checks, first-load nights) shown as status, never as an error | M | C2 | 13-2 | a test per tier of the home page text |
| 13-19 | The sales sheet per tier from section 3's "cannot do" lists and section 4's table, restated after the runs | S | owner, G | runs | the sheet cites the records |
| 13-20 | Tier D memory split 0.50 / 0.25 when sequences rise to 48-64 | S | D | D-1 | the serving record; KV peak under 70 % |

Counts: S 11 (13-4, 13-6, 13-7, 13-9, 13-10, 13-12, 13-13, 13-15, 13-16, 13-19, 13-20), M 8 (13-2, 13-3, 13-5, 13-8,
13-11, 13-14, 13-17, 13-18), L 1 (13-1).

---

## 12. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | **Is "no GPU" a tier we sell?** If yes, with a CPU model (notes for small hospitals overnight, protocols in minutes) or with no model (coded criteria only, rulesets shipped)? | Yes, as "coded screening plus overnight notes for small sites", **after A-1 and A-2**; until then sell it as "coded criteria only" |
| 2 | **The multicenter shape:** may a head hospital's box compile a protocol and send the approved ruleset to partner boxes (each partner's investigator approves again)? | Yes: it is how A and B sites get protocols, and it matches "trials are always multicenter" |
| 3 | **Buy or borrow a DGX Spark** to measure tier C (about US$4,699 / ¥1.05 million; outside the US$500 cap) | Borrow first (NVIDIA Japan or a reseller); buy only if a partner hospital wants tier C |
| 4 | **A second cloud vendor for one run** (a physical 5090 on RunPod, about US$6; public data only) | Only if tier B stays on the price list; otherwise skip B-3 |
| 5 | **Keep tier B on the price list?** In Japan a 5090 costs more than a Spark today and cannot read protocols | **Drop B from Japan's price list**; keep the profile for sites that already own a 5090 |
| 6 | **The first site's card:** Max-Q (300 W) or Workstation Edition (600 W) | Max-Q, unless D-2 shows more than 20 % loss at 300 W |
| 7 | **Certified "zero hits" answers** (05 §3b-A) on tier A for note criteria with a recall certificate | Yes for exclusions only, each certificate reviewed; never for inclusions |

---

## 13. What the owner or the first hospital must supply

1. **The patient population, as counts only:** in- and outpatients seen in each of the last two years, new patients a
   day, admissions a day, and the share of patients with notes in the electronic record. No patient data. (Replaces
   the 100-patients-a-bed assumption of section 4.)
2. **Open and planned studies:** how many, and for 3 to 5 typical ones the public protocol (ClinicalTrials.gov or
   jRCT number), so the light / typical / heavy split is the site's.
3. **The machine room:** whether a server room exists, power per outlet (100 V / 15 A in Japan: a 600 W card plus host
   approaches it [O]), noise rules for the office where the box would sit, and network rules (offline or not).
4. **The site's existing hardware**, if any (a GPU workstation, a server with AVX-512), for runs A-2 and G-7.
5. **Purchasing route and lead time** in Japan for the chosen workstation (a quote from the maker, with delivery date;
   plan v7 asks the same [R `docs/plan/33-plan-v7.md:85-86`]).
6. **The night window**: from when to when the hospital's information system may be read, and when the box must be
   idle (backups of the hospital's own systems).
7. **A synthetic sample export** of the hospital's SS-MIX2 storage (the vendor's format, made-up content), to time
   ingest per message on the real format (S-8). Whether the vendor is Software Service, Inc. is **not confirmed**.

---

## 14. Measurement log

Scripts in `/var/tmp/trialbox-0/B14-tiers/` (not committed); run with `python3 -I` on this shared 4-core machine.

| # | Command | Result |
| --- | --- | --- |
| 1 | `funnel.py <p2b>/x`: sum of each screen report's `funnel` per stored set (P2b, `git archive` of `integrator/p2b-artefacts`) | jmed: 2 reports, S0 594, S1 524, S3 0 (no model call); tcga: S0 500, S1 500, S3 500, S4 121; sigir: 101 reports, S0 102, S1 89, S3 78 |
| 2 | `night.py`: the formula of section 4 over the inputs printed there | the tables of section 4 |
| 3 | `grep -rln -i -E 'server-timing|Server-Timing|page_time|render_ms' services/console libs tools`; `du -sh services/console/static` | no match; 108 KB |
| 4 | `grep -rn llamacpp`, `grep -rln rerank`, `grep -rn -i 'export_ruleset|ruleset export|import'`, `grep -rn -E 'autovacuum|VACUUM'` over `libs services tools deploy` (tests excluded) | `llamacpp` only in `libs/tb_common/config.py`; `rerank` only in `models/routing.yaml`; no box-to-box ruleset function; no vacuum setting |
| 5 | `imptime.py`: each service's `app` module imported in a fresh interpreter with the main checkout's venv, best of 2 (load average 6.2 to 6.8) | console 0.95 s / 124 MB; orchestrator 1.12 / 123; gateway 0.72 / 75; criteria_compiler 1.01 / 136; adapter 0.76 / 79; lake 0.93 / 145; mail_gateway 0.74 / 78; doc_parser 0.63 / 66; embed_service 0.58 / 66 |

---

## 15. What this document did not verify

- **Every rate on A, B and C.** Only D's 3.06 calls a second is measured, on the Server Edition in a cloud VM. The CPU
  rates rest on secondary benchmarks of other models; the Spark rates on public runs of other models and lane G's
  estimates; the 5090 on a capped RTX PRO 6000.
- **The RTX 5090's bandwidth** is not on NVIDIA's page; 1,792 GB/s is from reviews.
- **Japanese prices** are from retailers and blogs (kakaku.com, gazlog.jp, issoh.co.jp), on the dates given; the
  Workstation Edition's Japanese price was not opened. Tax inclusion on kakaku.com was not legible.
- **The first site's bed count**: about 500 to 600 beds, for the owner to confirm.
- **Whether the cloud RTX PRO 6000 Server Edition accepts a 300 W power limit** (run D-2's premise).
- **Whether vLLM CPU runs this verifier's architecture** (a hybrid model); the docs list quantisations, not this model.
- **Whether the Max-Q is a blower card**, and the noise of any of the four in dB: not on the makers' pages.
- **A GCP Arm or Intel AMX price**; the Genoa price is from an aggregator.
- **How the console shows protocol-part progress today**; the table in 7.1 says "not verified".
- **That a Spark can be rented** anywhere; RunPod lists none; other clouds were not checked.
- **What the 117 s is made of** (08-4 measures it) and every row of section 6 marked "not timed".
- **The services' memory at idle in containers**: section 14 row 5 is the import alone, outside Docker, not a running
  service.
