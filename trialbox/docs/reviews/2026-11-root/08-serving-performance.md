# Root review 08: GPU serving and performance (lane J, card B-8, 2026-11-17)

**Reader:** the owner (a clinician) first, then the builders and whoever writes plan 9's next revision.

**The owner's words:** "Performance can become better; GPU serving, my most concern."

**What this review did.** No GPU is on this machine. Everything GPU-side is read from the code, from the stored launch
P2b (branch `integrator/p2b-artefacts` at `2bcf5ca9`, read with `git archive`, not merged), from the earlier GPU
records kept under `docs/plan/measurements/`, and from public sources opened today. Every figure from the traces was
recomputed here by small read-only scripts (section 10 gives each command and its output). Root review 01 sections 3
and 6 are not repeated; this review goes under them and corrects two of their weights.

**Marks.** Every claim carries one: **[M n]** measured here (entry n of section 10), **[R file:line]** read,
**[S link]** a public source opened 2026-11-17, **[O]** opinion. "Superseded" marks a GPU record that lane G's
validation reset (`docs/plan/measurements/validation-reset-2026-11-14.md`) bars as evidence of the shipped product;
it is used here only for the shape of a curve, never as a product figure.

---

## Summary (one page, plain words)

**What is good enough today.**

- **Screening a night is fast enough for a mid-size hospital, and the model is almost all of it.** In P2b, 500
  pathology reports were judged by both models (1,020 calls) in 324 s, of which the model calls were 319 s
  [M 1, M 4]. The night's model time scales with the number of note questions, not with the number of patients.
  Filters decide most patients before any model is asked.
- **The serving design is sound.** Two models, both resident on the card, a single gateway in front, and slots, a
  breaker and timeouts that nest [R `services/gateway/load.py:1-25`; `libs/tb_llm/timeouts.py:1-20`]. Nothing here
  argues for another engine for release 1.0 [O].

**What is not good enough.**

1. **The card is mostly idle.** The engine never had more than about five requests running on average. It used at
   most 7 % (judge) and 12 % (verifier) of its cache. The card ran at under half its power [M 7, superseded run, same
   engine and flags]. The bottleneck is how many questions the product sends at once, not the GPU.
2. **One model answer is written at about 37 tokens a second.** [M 3] That is slow for this card. The likely cause
   is that CUDA graphs are off (`--enforce-eager`) [R `deploy/docker-compose.rtxpro6000.yml:70,83`; O]. It hurts
   reading a protocol most, because each part's answer is about 900 tokens long.
3. **Reading a protocol is mostly not the model.** In sigir, a protocol took about 194 s of a stream. Of those,
   about 52 s were model calls and 8 s were screening. **117 s fell between the last compile call and the first
   screening call**, with no model working [M 5]. Root review 01 said the compile's CPU side "does not matter to
   the user". It does: it is the largest share.
4. **The judged-pair store finds nothing from one night to the next.** Its key holds the index date, which changes
   every night [R `docs/plan/measurements/pair-store-2026-11-17.md:62`].
5. **The records cannot answer basic questions.** P2b kept neither the per-call duration nor whether it ran the
   shipped serving or the owner's "tuned" exception. The gateway already writes duration, queue wait and tokens per
   call [R `services/gateway/core.py:1012-1016`], but the launch keeps only counts
   [R `tools/public_accuracy/onbox.py:249-290`].

**Five changes that matter most** (in this order; each is a card in section 7):

1. **Keep what the gateway already measures** (S, no GPU). Store the per-call duration, queue wait and tokens, plus
   the engine's own metrics and the serving mode, in every launch. Every later decision needs them.
2. **CUDA graphs on** (S, after run G-1). This is expected to speed up the 37-token-a-second answer writing several
   times [O]. The repository already has the switch (`--serving tuned`) [R `deploy/gcp/box-run.sh:129`].
3. **Send more questions at once.** Let the product keep 48 to 64 questions in flight per model instead of 16, and
   raise `--max-num-seqs` to match (M). The cache room is already there [M 7].
4. **Find the 117 s between compile and screen, and cut it** (M, no GPU). Profile APPROVE and the hand-over on the
   stub. Run the protocol's compile parts and `concept_map` calls side by side, not one after another [M 5, R
   `services/criteria_compiler/service.py:498`].
5. **Make the judged-pair store survive the night.** Key it on the note set and the window's dates, not the index
   date, for criteria that are not time-sensitive (M; the accuracy risk is in section 3).

**What it costs.** The free part is code: cards 08-1 to 08-9 need no GPU. The paid part is five runs on the spot VM,
G-1 to G-5. Together they take about 12 VM hours: about US$33 at the spot rate of US$2.74 an hour, or US$99 on
demand [R `tools/complete_run.py:1636-1640`; O]. Each run needs your yes (section 8). **Prefix caching is not where
the time goes**: a judge call spends about 3 % of its time reading the prompt [M 7]. Root review 01's G-2 drops down
the list.

---

## 1. Where the time goes today

### 1.1 Per call type, from the P2b traces

P2b: one RTX PRO 6000 (96 GB) VM, vLLM `v0.32.0` by digest, judge and verifier resident at 0.40 and 0.20 of the card,
16 sequences each [R `deploy/docker-compose.rtxpro6000.yml:59-98`]. The traces hold one timestamp per call, written
after the answer, and no duration [M 1]. Tokens below use TrialBox's own estimator, `tb_llm.budget.estimate_tokens`
[R `libs/tb_llm/budget.py:1-45`]. Calibrated against the engine-reported totals in the screen reports, the estimate
is within 15 %: engine/estimate 0.85 in and 0.95 out on sigir, 1.05 and 1.13 on tcga [M 1].

| Call (prompt, model) | Calls | Tokens in, median / p95 | Tokens out, median / p95 / max | Out tokens in all | Answer whitespace | Cache hits |
| --- | --- | --- | --- | --- | --- | --- |
| `ir_extract@4`, judge | 200 (sigir) | 1,135 / 1,455 | 832 / 1,959 / 3,025 | 180,188 | 21 % of characters | 1 |
| `concept_map@2`, judge | 676 (sigir) | 351 / 1,007 | 12 / 38 / 138 | 9,615 | 17 % | 51 |
| `judge@5`, judge, sigir | 325 | 614 / 748 | 79 / 128 / 164 | 27,073 | 15 % | 0 |
| `judge@5`, verifier, sigir | 44 | 641 / 861 | 107 / 152 / 165 | 4,852 | 16 % | 0 |
| `judge@5`, judge, tcga | 501 | 1,290 / 3,152 | 95 / 139 / 196 | 48,933 | 13 % | 0 |
| `judge@5`, verifier, tcga | 477 | 1,274 / 2,990 | 104 / 173 / **1,078** | 55,302 | 15 % | 0 |

[M 1] What the rows say:

- **Latency.** The traces have no per-call latency. The best proxies are below. One `ir_extract` part takes a
  median 24 s, at **36.8 tokens a second** for one sequence (10th to 90th percentile 32.6 to 42.6). This comes from
  77 consecutive parts of one protocol, which the compiler asks one after another [M 3; R
  `services/criteria_compiler/service.py:498`]. One `concept_map` takes 0.47 s (577 consecutive pairs) [M 3]. In
  tcga, 16 threads each asked the judge and then the verifier for one pair. 501 pairs in 319 s gives, by Little's
  law, about 10 s a pair, or about 5 s a call [M 4; O, derived].
- **Throughput achieved.** tcga: 1,020 calls in 319 s, which is 3.2 calls a second, 4,733 prompt tokens a second
  and 368 answer tokens a second for the two models together [M 4]. sigir: a median of 11 calls a minute and at
  most 44 [M 1].
- **Retries and failures.** sigir had 7 `ir_extract` parts the gateway gave up on. Each was asked again in 2 or 3
  parts [R sigir `services.log`, 7 lines; M 2]. In tcga, 2 judge failures and 45 disagreements were recorded
  [R tcga screen report, `judging`]. The two cut-off verifier replies are the 1,078-token maximum above. The
  answer cap is 1,024 tokens [R `libs/tb_llm/prompts/judge_v5.md:6`].
- **Repeated requests** were 52 in sigir, out of 1,245 [M 1]. The gateway's response cache served 51 of them as
  `concept_map` hits, plus one `ir_extract` hit.

### 1.2 Model time, prompt overhead, queue and product: the shares

| Share | Value | How known |
| --- | --- | --- |
| Prefill (reading the prompt) in a judge call | about 3 %: time to first token 0.06 to 0.09 s of a 2.7 to 3.2 s call | [M 7] superseded run, same engine and flags |
| Decode (writing the answer) in a judge call | about 97 %; 23 to 26 ms a token per sequence, at 1 and at 16 in flight | [M 7] |
| Queue in the engine | 0.2 to 6 ms a call | [M 7] |
| Queue at the gateway's slots (`slot_wait_ms`) | recorded per call, **not kept by any launch** | [R `services/gateway/core.py:775-776,1015`] |
| Repeated system text in prompts | judge 25 % (tcga) to 58 % (sigir) of prompt characters; `ir_extract` 71 %; `concept_map` 44 % | [M 1] |
| Shared prefix reachable by a prefix cache | judge 27 to 62 %; `ir_extract` 73 %; `concept_map` 56 % | [M 1] |
| Model share of SCREEN (tcga) | 319 of 324 s, 98.5 % | [M 4] |
| Model share of one protocol's journey (sigir) | about 60 of 194 s, about 31 % | [M 5] |

The conclusion [O]: the shared prefix is large, but prefill is only about 3 % of a call, so prefix caching can save
at most a few percent of model time. **Decode speed and the number of sequences in flight decide the night.**

### 1.3 Waterfall: one protocol (sigir, 104 protocols, 3 streams)

Per protocol, mean, from the traces, the run's progress record and the driver's log [M 5]:

```
FEAS compile  |== first ir_extract part ~24 s ==|== rest of compile 28 s (1.9 ir_extract, 6.5 concept_map) ==|
APPROVE + hand-over                                                     |======== 117 s, no model call ========|
SCREEN                                                                                                  |= 8 s =|
total about 177 s against 194 s observed (6,710 s x 3 streams / 104)
```

- `ir_extract` decode is about 46 s of the 52 s of compile model time. `concept_map` is 676 calls but only about
  3 s a protocol: 54 % of the calls and about **4 % of the compile's model time** [M 1, M 3]. Root review 01's
  B1-M2 (cut `concept_map` with code systems at install) still saves calls and reviewer work, but it is not a GPU
  saving [O].
- **The 117 s** (median 118, p95 179) is measured from the last FEAS call to the first SCREEN call [M 5]. In it:
  the APPROVE job, which calls no model but recompiles; the mail round trip; and the driver's 5 s polls
  [R `tools/public_accuracy/onbox.py:139-155`]. One protocol's log shows APPROVE "compiling" from 08:09:27 to at
  most 08:10:53 [R sigir `box-calls.log` lines 20-41]. In tcga, APPROVE took 30 s for one criterion
  (08:02:53 to 08:03:23) [R tcga `box-calls.log`]. **Which part of APPROVE costs the time was not verified.**

### 1.4 Waterfall: one screening night (tcga: 500 patients, one note criterion, both models)

```
08:02:40 FEAS (1 ir_extract)  |= 11 s =|
08:02:53 APPROVE                        |=== 30 s, no model ===|
08:03:25 SCREEN S0-S2b                                          |4 s|
08:03:29 S3 judge + verifier, 16 threads                            |============ 319 s, 1,020 calls ============|
08:08:51 lists written, fetched                                                                                |1 s|
```

[R tcga `box-calls.log`; M 4] In this set S2 found no keyword hit and S2b let every pair through, so every patient
reached the models [R tcga screen report, `stages`]. It is the all-note worst case. The synthetic 50,000-patient run
of 2026-11-13 (superseded) asked 3,226 calls for 50,000 patients in one study. That is 0.065 calls per patient and
study, with 725 s of model time in a 2,986 s run [R `docs/plan/measurements/g3-50k-2026-11-13/capacity_inputs.json`].

### 1.5 Concurrency achieved against the engine's capacity, and memory

The only run with engine metrics scraped is lane G's G1 run of 2026-11-12. It is superseded: no chat template,
image by tag, an old commit. It has the same engine version and the same `--enforce-eager` and `--max-num-seqs 16`.
It ran the same 336 judge and about 290 verifier calls at four in-flight settings [M 7]:

| In flight (product) | Part wall s | Judge running, mean / max | KV cache used, max (judge / verifier) | GPU util mean | Power max | Judge e2e mean | Judge TTFT mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1,744 | 1.0 / 1 | 0.6 % / 1.1 % | 33 % | 211 W | 2.72 s | 0.061 s |
| 4 | 757 | 1.8 / 4 | 2.0 % / 3.7 % | 49 % | 254 W | 2.78 s | 0.084 s |
| 16 | 512 | 4.5 / 16 | 5.0 % / 8.3 % | 33 % | 288 W | 3.00 s | 0.091 s |
| 48 | 485 | 5.6 / 16 | 7.1 % / 11.5 % | 32 % | 293 W | 3.16 s | 0.075 s |

- **Per-sequence speed barely falls with load.** A call took 2.72 s alone and 3.16 s with up to 16 running. The
  engine has room for many more sequences at almost no cost per sequence [M 7; O].
- **At 48 in flight the engine still ran 16 at most.** `--max-num-seqs 16` and the gateway's 16 slots cap it
  [R `services/gateway/load.py:25`]. The product's mean in flight stayed near 5, because each thread asks the judge
  and then waits for the verifier [R `services/matching/cascade/judge.py:258-266`].
- **Memory.** The pair holds 62.6 of 95.6 GiB [R `deploy/measured/serving_config.rtxpro6000.json`,
  `memory_used_mib` 62,574]. The judge's KV pool is about 180,000 tokens and the verifier's about 200,000
  [R `deploy/docker-compose.rtxpro6000.yml:11-14`]. The most ever used was 12 %. Neither memory nor context length
  constrains anything today [O].
- **Power.** The card never passed 293 W. The reference workstation may be the 300 W Max-Q edition
  [R `docs/plan/33-plan-v7.md:91`]. Today that cap would not bind; after tuning it might. G-4 measures it [O].

### 1.6 What the records lack, and how cheap the fix is

The gateway's audit record already holds `tokens_in`, `tokens_out`, `latency_ms`, `slot_wait_ms`, `retries` and
`cache` per call [R `services/gateway/core.py:1012-1023`]. The launch reads that audit only to count calls by prompt
[R `tools/public_accuracy/onbox.py:249-290`]. So root review 01's G-4 is not a code change in the gateway. It is a
change to what the launch keeps: about 20 lines in `onbox.py`, plus a scrape of the engine's `/metrics` like the G1
harness's `vllm.csv`. The launch must also print its serving mode, `shipped` or `tuned`. P2b's stored sets do not say
which one it ran [R `docs/plan/measurements/p2b-review-2026-11-17.md:304-305`]. Card 08-1.

---

## 2. The serving configuration, flag by flag

### 2.1 The flags of the shipped profiles

Engine documentation: vLLM latest developer docs and the v0.32.0 guide, both opened 2026-11-17
[S https://docs.vllm.ai/en/latest/configuration/engine_args/; S https://docs.vllm.ai/en/v0.32.0/usage/v1_guide/].

| Setting | RTX PRO 6000 (reference) | Spark (gb10) | RTX 5090 | What it does (docs) | Change |
| --- | --- | --- | --- | --- | --- |
| `--enforce-eager` | on, both servers [R `docker-compose.rtxpro6000.yml:70,83`] | on [R `docker-compose.gb10.yml:59,88`] | on | "Whether to always use eager-mode PyTorch"; true disables CUDA graphs [S engine_args]. The default compile level is `-O2` and the graph capture size is capped at 512 [S engine_args] | **Drop it** if G-1 shows the gain with unchanged answers. The 37-tokens-a-second decode of one sequence is where graphs help most [O]. The cost is longer start-up and some memory for graphs; there is 33 GiB free [R serving record] |
| `--max-num-seqs` | 16 each | 8 | 4 | "Maximum number of sequences to be processed in a single iteration" [S engine_args] | **48 to 64 on the reference card** (KV used at most 12 % [M 7]); the gateway's slots follow it from the serving record [R `services/gateway/load.py:1-6`]. Decide in G-2 |
| `TB_SCREEN_LLM_CONCURRENCY` | = judge seqs (16) [R `docker-compose.rtxpro6000.yml:98`] | 8 | 4 | the cascade's threads; each thread holds one pair, judge then verifier [R `services/orchestrator/jobs.py:351-357`] | **2 x seqs**, so both servers stay full (card 08-3) |
| `--gpu-memory-utilization` | 0.40 + 0.20 | 0.30 + 0.15 | 0.81 each, swapped | the fraction of the whole card for weights plus KV [S engine_args] | keep; the KV room is ample [O] |
| `--max-model-len` | 32,768 | 16,384 | 8,192 | context per sequence | keep: `ir_extract` needs 1.5k in plus up to 8k out [M 1; R `libs/tb_llm/prompts/ir_extract_v4.md:6`] |
| Prefix caching | not on the command line; the serving record does not capture it [R `deploy/measured/serving_config.rtxpro6000.json`] | same | same | APC is enabled with `enable_prefix_caching=True`; **the docs opened do not state the default**. For hybrid (Mamba-type) models a cache hit resumes only at a block boundary (`align` mode) [S https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/]. The v0.32.0 guide says prefix caching "is not yet supported" for the Mamba and hybrid models it lists [S v1_guide v0.32.0] | **State it explicitly** (`--enable-prefix-caching`) and record it. Expected gain is small (prefill about 3 % [M 7]). Read the hit rate from `/metrics` in every run (card 08-1); a separate paid A/B only if the hit rate is low. Whether the verifier's architecture is one the guide lists was **not verified** |
| Structured output | `json_schema` on every non-free-form role [R `libs/tb_llm/client.py:242-245`]; backend `auto` [R `deploy/docker-compose.yml:417-418`] | same | same | backends xgrammar and guidance; `auto` "will try to choose an appropriate backend based on the details of the request"; lm-format-enforcer deprecated in v0.33.0, removed in v0.35.0 [S https://docs.vllm.ai/en/latest/features/structured_outputs/] | keep `auto`; record which backend served (the serving record's job). The docs opened name no whitespace switch, so **compact answers** (21 % of `ir_extract` answer characters are whitespace [M 1]) come from the prompt or the schema, card 08-6 |
| `--scheduling-policy` | default `fcfs` | same | same | `priority`: "requests are handled based on given priority (lower value means earlier handling)" [S engine_args] | **`priority`**, with the gateway sending a lower value for interactive roles (card 08-8) |
| `--kv-cache-dtype` | `auto` [R serving record] | same | same | fp8 and nvfp4 options exist [S engine_args] | keep `auto`: KV is not short, and a change is an accuracy risk with no gain [O] |
| `--async-scheduling` | not set | | | "helps to avoid gaps in GPU utilization" [S engine_args]; its default is not shown | test in G-2 only if utilisation stays low after the seqs change [O] |
| Speculative decoding | off | | | `--speculative-config`; v0.32.0 added "a GPU n-gram speculator with variable-length drafts" [S https://github.com/vllm-project/vllm/releases] | **G-5**: 38 % of `ir_extract` answer characters and 44 to 49 % of judge answers are runs of 20 or more characters copied from the prompt [M 6]. That is what prompt-lookup (n-gram) drafting proposes. Speed only; the output distribution is unchanged in principle [O] |
| Sleep swap | off | off | on, one model awake | vLLM sleep mode, behind model-guard [R `docker-compose.rtx5090.yml:13-20`] | keep for 32 GB cards |
| `--limit-mm-per-prompt` 0 | on | on | on | no image or audio memory reserved | keep |

### 2.2 Quantisation, the pair, context

- **Quantisation.** Both models are already 4-bit: the judge NVFP4 and the verifier AWQ
  [R `deploy/docker-compose.rtxpro6000.yml:6-7`]. There is nothing to gain from going lower, and a known accuracy
  risk. QAT 4-bit was tried and rejected for broken JSON [R `deploy/docker-compose.rtx5090.yml:24-27`]. **No change** [O].
- **Two models on one card, or one model with two prompts.** The pair rule refuses the same build twice as a second
  opinion [R `libs/tb_common/pair.py:73-74`]. One model with two prompts would therefore remove the safety the
  verifier gives. **Keep two models** [O]. The verifier waits on the judge in each thread (1.5). The cure is more
  threads, not one model.
- **Context against memory.** At 64 sequences of 2,000 tokens, the judge needs about 128,000 tokens of KV. Its pool
  holds about 180,000 [R compose comment; O]. The verifier's pool is larger. 32k context stays.

### 2.3 The engine version

The pin is v0.32.0 (2026-10-18). v0.33.0 came out on 2026-11-02 and v0.34.0 on 2026-11-16
[S https://github.com/vllm-project/vllm/releases; 03 §5]. Relevant to this box since the pin [S releases page]:

- v0.32.0 itself fixed three advisories: GHSA-4hhp-h66f-j5j7 (chat-template resource exhaustion),
  GHSA-q97c-p368-75c4 and GHSA-frvg-qw88-hww9.
- v0.33.0: "FlashInfer GDN prefill checkpoints for Qwen3-Next / Qwen3.5" (the verifier's family); a fix to "Gemma 4
  encoder graphs" (the judge's family); lm-format-enforcer deprecated.
- v0.34.0: "breakable CUDA graphs" for Qwen3.5 with 3.0 to 8.8 % lower decode inter-token latency; NVFP4 MoE speed-ups
  on Blackwell (shown for data-centre parts; SM120 cards such as the RTX PRO 6000 are **not named**).

Recommendation [O]: run G-1 on v0.32.0 first, so the flag is decided on the qualified engine. Then move to the
current release once (G-4, with plan 9's 9g-10 and its requalification). Do not move twice.

### 2.4 Engines for an offline hospital box (beyond root review 03 §5)

| Engine | Licence | Maturity | Structured output | Two models | Offline, phones home | Switching cost from today | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| vLLM (pinned) | Apache-2.0 [03] | multi-company; weekly releases | xgrammar, guidance [S structured_outputs] | one server per model, as built | `VLLM_NO_USAGE_STATS=1` is set [R `docker-compose.rtxpro6000.yml:39`] | none | **keep**; tune the flags |
| SGLang | Apache-2.0 [03] | v0.5.23 (03) | constrained decoding (03) | one server per model | not verified | new serving record, a new sleep path for 32 GB cards (vLLM's `/sleep` endpoints are wired into model-guard [R `deploy/docker-compose.rtx5090.yml:58-59`]), requalification | **learn from**; its strength is radix prefix caching, which is not where the time goes here [M 7] |
| llama.cpp | MIT [03] | build tags, very active (03) | GBNF and JSON schema (03) | one model per process (a multi-model router was not verified) | runs fully offline [O] | GGUF builds of both models, which are a model change; requalification; a new serving record | **the GPU-less box's engine** (section 4.4), not the GPU box's |
| TensorRT-LLM | Apache-2.0 [S https://github.com/NVIDIA/TensorRT-LLM] | NVIDIA; 1.4.0rc4 on the page today | guided decoding mentioned in a blog title only [S same] | per-engine builds | not verified (the NGC container terms were not opened) | engine builds per card type; support for the RTX PRO 6000 is not named on the page; NVIDIA-only | **ignore for 1.0**: the highest switching cost for a gain G-1 may get inside vLLM [O] |
| TGI | Apache-2.0 | "now in maintenance mode" (03) | – | – | – | – | **ignore** |

---

## 3. Product-side changes that cut model work

| # | Change | Share it addresses | Accuracy risk | State today |
| --- | --- | --- | --- | --- |
| P1 | **More pairs in flight**: threads = 2 x seqs; raise seqs (2.1) | throughput: engine running 4.5 to 5.6 of 16 [M 7]; calls a second at fixed per-call speed scale with sequences | none: same calls, same answers (the `determinism` step checks at 16 [R `tools/qualify.py:33-34`]) | 16 threads, 16 seqs |
| P2 | **Judge and verifier side by side** in a thread | halves a pair's wall time | none in the answer. It costs verifier calls on undecided judge answers: 5 % more in tcga (24 of 501), but 86 % in sigir (281 of 325 judge answers undecided) [M 1] | serial [R `judge.py:262-266`]. **Not recommended**: P1 gets the same gain with no extra calls [O] |
| P3 | **Compile parts side by side**: `ir_extract` parts and `concept_map` calls of one protocol in parallel | `ir_extract` decode is about 46 s of a protocol's 52 s compile model time; 1.9 parts a protocol (p95 4); 577 `concept_map` calls in sequence [M 3, M 5] | none: each part is asked alone already; answers are matched by line text [R `service.py:481-492`] | sequential loop [R `service.py:498`] |
| P4 | **Shared cacheable prefix**: put `note_question` beside `criterion_text`, before the excerpts | judge prompts 27 to 62 % shared today [M 1]; prefill about 3 % of a call [M 7] | a prompt version, so the pair gate runs again | keys are sorted, so `note_question` and `index_date` come after the excerpts [R `libs/tb_llm/prompts/judge_v5.md:22`]. **Low value; fold into the next prompt version only** [O] |
| P5 | **Compact JSON answers** | answer tokens: `ir_extract` 180,188 to 149,781 (17 % fewer), judge 4.5 %, verifier 3 to 4 % [M 1]; compile time drops about in step with them [O] | schema-checked either way; a prompt version | answers indented (`{\n "verdict"`) [M 1] |
| P6 | **Answer cap** for the judge prompt from 1,024 to 384 tokens, with the gateway's one length retry kept | p95 answer 173 tokens, max 1,078 [M 1]; a runaway answer costs about 28 s of decode, twice | a cap below a real answer gives a length retry; 384 is above the p95 x 2 [O] | 1,024 [R `judge_v5.md:6`] |
| P7 | **Judged-pair store across nights**: key on the excerpt-set hash and the window's absolute dates, not the index date, for criteria not flagged `time_sensitive` | hit rate across nights today 0 by design [R `pair-store-2026-11-17.md:62`]; a re-run at the same index date would find 93.6 % [R same, table (b)] | the prompt shows `index_date`; a model can read "within 6 months" against it. Reuse only when the excerpt set is identical and the criterion is not time-relative; the audit sample (CAS-8) stays live [R `services/orchestrator/judged_store.py:1-30`; O] | keyed with index date |
| P8 | **Skip unchanged patients** (the delta night) | the night's share; the MICROBATCH already screens only new and booked patients plus a weekly re-check [R `services/orchestrator/scenarios/microbatch.py:1-30`] | none | screening delta exists; ingest delta is plan 8 row 9 (not landed) |
| P9 | **Early exit on a decisive exclusion; order by cost and selectivity** | – | – | **done**: CAS-3 orders by exclusion power over expected tokens and stops at a hard exclusion [R `services/matching/cascade/engine.py:1267,1308`] |
| P10 | **The ladder** (05): rules, terms, small model, then large | every S3 pair; the largest lever on calls (05 J5-6) | 05's | plan 9 9c-1, 9c-8 |
| P11 | **Part size from the measured rate** | 7 parts given up and re-asked in sigir [M 2]; the size rule assumes 40 tokens a second [R `service.py:127`], and 36.8 was measured [M 3] | none | after G-1, set `TB_EXTRACT_RATE_PER_S` from the record (larger parts, fewer calls) |
| P12 | **A configuration refusal is not an outage** (the 30-minute wait) | a missing token stalls each job 30 min [01 M 16] | none | open: still 503 into `GatewayDown` [R `libs/tb_llm/client.py:274`; `libs/tb_common/service_auth.py:496`]; plan 9 card 9d-9 |
| P13 | **An interactive lane**: two slots per endpoint kept for interactive roles; engine `priority` scheduling | a console "one-patient check" during the night gets `model_busy` after 0.5 s today [R `services/gateway/load.py:26`] | none | none: one pool of 16 slots, and 4 job workers x 16 threads compete for it [R `services/orchestrator/app.py:133`] |

**The night, scheduled** [O]: with P1 and P13, the gateway keeps `seqs - 2` slots for batch and 2 for people. The
night's jobs fill the batch slots (4 workers x 2 x seqs threads). A person's call goes first in the engine's queue
(`priority`). The GPU stays full while nobody waits more than one decode step for a slot.

---

## 4. Capacity model

### 4.1 Formula

```
model hours per night = N x S x d x c x (1 - h) / r / 3600
  N  patients in scope            S  studies screened that night
  d  share of patients screened that night (1 at first load; the delta otherwise)
  c  model calls per patient and study on a full screen (judge plus verifier; set by S0-S2b filters and criteria)
  h  judged-pair store hit share (0 across nights today, section 3 P7)
  r  calls a second the pair sustains on the box
fits the night when model hours + CPU hours <= window x usable share (0.7 in lane G's inputs
  [R docs/plan/measurements/g3-50k-2026-11-13/capacity_inputs.json])
```

Inputs: `c` = 0.065 for a filter-first study (the synthetic 50,000, superseded; the only measured value)
[R `g3-50k-2026-11-13/capacity_inputs.json`]. `c` = 0.5 for a note-heavy study [O; tcga's all-note criterion gave
2.04 calls a patient for one criterion, M 4]. `r` = 3.06 today [M 4]. 9 is a target after P1 and G-1, and 18 a
stretch [O, estimates that G-2 and G-4 replace].

### 4.2 Table: model hours per night on the reference card (RTX PRO 6000, 96 GB)

Each cell is hours at r = 3.06 / 9 / 18 calls a second. "Delta 3 %" assumes 3 % of patients are new or booked in a
night [O]. [M 8]

| Patients | Studies | Night | Filter-first: calls | hours (today / target / stretch) | Note-heavy: calls | hours (today / target / stretch) |
| --- | --- | --- | --- | --- | --- | --- |
| 20,000 | 10 | first load | 13,000 | 1.2 / 0.4 / 0.2 | 100,000 | 9.1 / 3.1 / 1.5 |
| 50,000 | 10 | first load | 32,500 | 3.0 / 1.0 / 0.5 | 250,000 | 22.7 / 7.7 / 3.9 |
| 50,000 | 30 | first load | 97,500 | 8.9 / 3.0 / 1.5 | 750,000 | 68.1 / 23.1 / 11.6 |
| 50,000 | 30 | delta 3 % | 2,925 | 0.3 / 0.1 / 0.0 | 22,500 | 2.0 / 0.7 / 0.3 |
| 200,000 | 30 | first load | 390,000 | 35.4 / 12.0 / 6.0 | 3,000,000 | 272 / 93 / 46 |
| 200,000 | 30 | delta 3 % | 11,700 | 1.1 / 0.4 / 0.2 | 90,000 | 8.2 / 2.8 / 1.4 |
| 500,000 | 10 | delta 3 % | 9,750 | 0.9 / 0.3 / 0.2 | 75,000 | 6.8 / 2.3 / 1.2 |
| 500,000 | 30 | first load | 975,000 | 88.5 / 30.1 / 15.0 | 7,500,000 | 681 / 232 / 116 |
| 500,000 | 30 | delta 3 % | 29,250 | 2.7 / 0.9 / 0.5 | 225,000 | 20.4 / 6.9 / 3.5 |

What it means [O]:

- **Nightly (delta).** Today's card already carries a 500,000-patient hospital with 30 filter-first studies
  (2.7 h). With note-heavy studies it carries about 200,000 patients today (8.2 h is over a 5.6 h usable window), and
  500,000 after the target rate (6.9 h, about at the edge).
- **First load.** It is the problem at every size above 50,000. At 500,000 x 30 studies, a first load is 3.7 days
  of model time today and 1.3 days at the target. The night budget already spreads it over nights, and says so
  [R `microbatch.py`, "Night budget"]. The capacity statement must give first-load days, not hours.
- **The CPU side** at 50,000 is ingest 805 s plus the cascade (01 §6.1) and APPROVE per new study (section 1.3).
  At 500,000 the full reload of ingest is the limit (01), not the GPU.

### 4.3 Smaller and larger boxes

| Box | What runs on it | r (calls a second), estimate | Supports nightly (filter-first, 30 studies, delta 3 %) |
| --- | --- | --- | --- |
| RTX 5090 or RTX PRO 4500, 32 GB | one model awake, sleep swap, 4 seqs, 8k context; **no protocol reading on the box** [R `docker-compose.rtx5090.yml:13-35`] | about 1 [O: one model at a time; G1's 4-in-flight curve, superseded] | about 300,000 patients filter-first; note-heavy about 60,000 [O] |
| RTX PRO 6000, 96 GB (reference) | as above | 3.06 today; 9 target | 500,000 filter-first; 200,000 note-heavy today |
| Spark class (gb10), 128 GB unified | both resident, 8 seqs, 16k [R `docker-compose.gb10.yml:57-60`] | not measured; the unified memory's bandwidth is far below the RTX PRO 6000's, so decode is slower [O, not verified] | measure before quoting |
| Two RTX PRO 6000, or a B200 as two MIG instances (the owner's) | one model per card or instance [R `deploy/gpu_profile.sh:8-16`] | about 2 x the reference [O] | first loads twice as fast |

### 4.4 The GPU-less box

What it does today [R 01 §3.4]: coded criteria (S0, S1) run, note criteria wait and then stop with a named outage,
and no new protocol can be read. A CPU serving path (llama.cpp, MIT) for the verifier-sized model is
**an estimate, not measured** [O]: about 5 to 15 answer tokens a second and 100 to 300 prompt tokens a second on
16 cores. A judge call (1,500 in, 100 out) then takes about 15 to 35 s, which is 100 to 240 calls an hour. That
covers a delta night of a small hospital (20,000 x 10 studies, about 400 filter-first calls). It does not cover a
first load, and not protocol reading (900-token answers at 5 to 15 tokens a second, minutes a part). A single model
may also never exclude [R `judge.py`, D-97 branch at `services/matching/cascade/engine.py:1235`]. Run G-6 measures it on a CPU machine
at no cloud cost.

---

## 5. The measurement plan

Rules: the repository's own driver, public sets only, each run decides one question, and every run is a decision
with its estimate (section 8). The rate is US$2.74 an hour spot and US$8.22 on demand
[R `tools/complete_run.py:1636-1640`]. VM start is 0.25 h [R `tools/complete_run.py:1684`]. The driver prints its
own figure free first (`--estimate`). Today it prints a 2 h cap (US$5.48) for `--steps acc --only sigir`, and 5 h
(US$13.70) for `start,acc --only tcga:500` [M 9]. Runs go in this order: each needs the one before.

| Run | Hypothesis | Commands (from `trialbox/`, after `--estimate`) | Metrics | Pass (decides) | Duration; cost spot (on demand) |
| --- | --- | --- | --- | --- | --- |
| G-0 (free) | the launch keeps per-call duration, queue wait, tokens, the serving mode and engine metrics | card 08-1 merged; then any launch | `latency_ms`, `slot_wait_ms`, tokens per call; `/metrics` every 10 s: running, waiting, KV %, prefix hits, TTFT; `TB-SERVING` line | the fields present in the stored set | code only |
| G-1 | CUDA graphs speed up single-sequence decode at least 2x with the same answers | `deploy/gcp/box-run.sh --mode validation --steps start,acc --release-id val-<commit12> --only sigir --serving shipped`, then the same with `--serving tuned`; compare with `python -m tools.public_accuracy.replay` | `ir_extract` tokens a second per sequence (today 36.8 [M 3]); protocol stream time; verdict changes | decode up to at least 2x and 0 changed exclusions → drop `--enforce-eager` (9g-9) | 2 x about 2.75 h; about US$15 (US$45) |
| G-2 | at 48 to 64 seqs, with threads at 2 x seqs, the pair sustains at least 9 calls a second | tcga:500 with a driver option for seqs and threads apart from graphs (card 08-2), at 16/16, 48/96 and 64/128 | calls a second; p50/p95 latency; `slot_wait_ms`; KV %; power | the highest calls a second with p95 at most 2x the 16-seq p95 and no breaker opening → the profile's seqs (08-3) | one launch, about 1.5 h; about US$4 (US$12) |
| G-3 | the 117 s between compile and screen is CPU, not a wait | none paid: profile APPROVE on the stub (`python tools/bench.py --tasks compile`, cProfile), then confirm in G-1's G-0 records | APPROVE seconds; where they go | less than 15 s a protocol after the fix (card 08-4) | free |
| G-4 | the night at 50,000 on the decided configuration and the current engine | box with G-1 and G-2's settings and vLLM's current release: `python tools/bench.py --tasks screen,ingest --ingest-patients 50000 --llm-url <the box's gateway>` with `nvidia-smi dmon -s pum -d 5` beside it, then plan 8's V1 qualification on the same box | model and CPU hours of the night; calls a second; power (whether 300 W would bind); qualification answers | the capacity statement's figures; V1 passes → engine update (9g-10) | about 3 h with qualification; about US$8 (US$25) |
| G-5 | n-gram speculative decoding speeds up `ir_extract` at least 1.3x with identical answers at temperature 0 | as G-1 tuned, sigir, with `--speculative-config` set to the engine's n-gram method in the override | decode tokens a second; acceptance rate; answers identical | at least 1.3x and identical → add to the profile | about 2.75 h; about US$8 (US$23) |
| G-6 | a CPU box can answer a delta night of a small hospital | the verifier-sized model under llama.cpp on a 16-core machine, through the gateway's `qualify --steps pair_gate,throughput` | calls an hour; pair-gate scores | at least 100 calls an hour and the gate → a "CPU notes" profile | owner's machine; no cloud cost |
| G-7 | the reference workstation under WSL2 equals the VM within 15 % | P-2 of the hardware plan: the standing benchmark (5.1) on the delivered card | the same metrics as G-2 | within 15 % → the capacity statement holds for the site's form | on the delivered card; no cloud cost |

In all, G-1, G-2, G-4 and G-5 are about 12 VM hours: about US$33 spot or US$99 on demand [O]. That is about twice
plan 9's "about 6 h" for V23, because it adds G-2 and G-5 and drops 01's prefix-caching A/B. Whether one launch can
switch `--serving` between two sets without a reinstall was **not verified**. If it can, G-1 costs one start, not two.

### 5.1 The standing serving benchmark

`tools/servebench` (card 08-7) replays a fixed set of prompts through the gateway. The set: 200 `judge@5` prompts and
40 `ir_extract@4` prompts drawn from the public P2b traces, stored with their attributions
[R `.p2b-artefacts` README: SIGIR (NCBI), TCGA-Reports CC BY 4.0]. It replays at 1, 16 and 2 x seqs in flight and
prints calls a second, tokens a second, p50/p95 latency, TTFT, decode tokens a second per sequence, KV %, prefix hit
%, `slot_wait_ms` p95 and verdict changes.

| Where | When | Gate |
| --- | --- | --- |
| Stub, CI nightly | every night beside `make bench-gate` | the harness runs; the **gateway's own overhead per call** (stub) p95 at most 50 ms; more than 20 % over the baseline fails, as the bench gate does [R `tools/bench.py:15-22`] |
| GPU box, at qualification (`tools/qualify.py`, beside `throughput` [R `tools/qualify.py:1037`]) | install, every engine or model change, G-7 | single-sequence decode at least 0.85 x the record; calls a second at 2 x seqs at least 0.85 x the record; 0 changed exclusions; written into the serving record |

Today's `throughput` step records seconds and fails only when nothing was timed [R `tools/qualify.py:1037-1056`];
it has no threshold. The floors above come from the first G-1 and G-2 records, not from this page [O].

---

## 6. CPU-side performance beyond root review 01

### 6.1 Root review 01's fixes, checked against master `8778394f`

| 01 fix | State on master | Refined here |
| --- | --- | --- |
| B1-F1 failing `pandas` probes (about a tenth of the stub night) | not landed: no `sys.modules` entry for `pandas` anywhere [M 10] | keep first: S, about 10 s of a 94 s stub night (01 M 23) |
| B1-S1 NDJSON copy (16 % of ingest) | not landed; plan 9 card 9d-1 [R `docs/plan/45-plan-9-2026-11-17.md:314`] | keep; the larger ingest win at 500,000 |
| B1-F2 recall grid in Python | not landed: `_lambda` still per call [R `libs/tb_common/recall.py:79`] | keep |
| B1-F3 prefix expansion | not landed: no `bisect` in the mapper [M 10] | keep; it is part of APPROVE's compile and so of the 117 s (1.3) [O] |
| Row mapper (41 % of ingest) | not landed | keep "not now" (01 §6.2) |

### 6.2 What the traces add

- **APPROVE and the hand-over: the largest CPU share a user waits on.** 117 s a protocol in sigir and 30 s for one
  criterion in tcga [M 5; R tcga `box-calls.log`]. Root review 01 profiled `build_rulesets --check` at 12 s
  profiled for 8 rulesets (01 M 24). So the 117 s is mostly not that compile. Candidates are terminology loading per
  job, HAPI or CQL work, mail and queue polling, and three streams contending. None is verified. Card 08-4 profiles
  it on the stub.
- **Database round trips in the cascade.** The judged-pair store makes about three statements per model call: a
  read, an opt-out check and a write [R `services/orchestrator/judged_store.py:124-235`]. At about 1 ms each against
  a 3 to 10 s call, they are not a cost [O].
- **Serialisation and logging per call.** The gateway writes an audit line and a full trace (prompt and answer) per
  call [R `services/gateway/core.py:950-1031`]. On the stub, 153 judge calls cost 15.9 s profiled, with the
  in-process HTTP included (01 M 19). That is about 0.1 s a call profiled. The standing benchmark's stub gate
  (5.1) holds it.
- **The client is synchronous** (one `httpx.Client` per caller; threads give the concurrency)
  [R `libs/tb_llm/client.py:177`]. At 128 threads per job that is still fine for I/O-bound waits [O]. It needs
  no change before G-2 shows otherwise.

### 6.3 A performance budget per stage that CI can gate

On the stub at 5,000 patients (the bench gate's shape), scaled by the gate's calibration loop. "Now" is the baseline
of 2026-11-10 [R `tools/bench_baseline.json`]; "after" is the budget once the named fixes land [O].

| Stage | Now (baseline) | Budget after fixes | Fixes | Gate |
| --- | --- | --- | --- | --- |
| Synthetic data | 2.5 s | 2.5 s | – | +20 % (exists) |
| Ingest and lake | 58.0 s | 40 s | B1-F1, B1-S1, B1-F4 | +20 % over the new baseline |
| Cascade S0 to S5 | 14.7 s | 12 s | B1-F1 | same |
| Pack, certificate, outputs | 18.4 s | 10 s | B1-F2 | same |
| APPROVE of one protocol (new) | not measured | 15 s on the stub (GZQO) | card 08-4 | new line in the gate |
| Compile check (`build_rulesets --check`, new) | about 12 s profiled (01 M 24) | 6 s | B1-F3 | new line |
| Gateway overhead per stub call (new) | about 0.1 s profiled (01 M 19) | 50 ms p95 | – | servebench stub (5.1) |
| Peak memory | 1,871 MB | 1,871 MB | – | +20 % (exists) |

---

## 7. Cards for plan 9's next revision

| Card | What | Size | Lane (guess) | Waits for | Proof |
| --- | --- | --- | --- | --- | --- |
| 08-1 | The launch keeps the gateway's per-call `latency_ms`, `slot_wait_ms`, tokens, retries and cache (no text); scrapes the engines' `/metrics` every 10 s; prints `TB-SERVING` and the served flags into the stored set. Replaces 9g-8's gateway change | S | G (driver) + A2 | – | a stub launch's stored set holds the fields; `onbox` test |
| 08-2 | The driver sets graphs, seqs and threads separately (`--serving` takes `graphs=on,seqs=64,threads=128`), not only the bundled "tuned" | S | G | – | the override file written per option, tested |
| 08-3 | The profile's seqs and threads from G-2; gateway slots from the serving record; threads = 2 x seqs | S | D | G-2 | the serving record; servebench at qualification |
| 08-4 | Profile APPROVE and the FEAS-to-SCREEN hand-over on the stub; fix what dominates (expected: terminology load per job, prefix expansion B1-F3) | M | A2 | – | APPROVE under 15 s on the stub; G-1's G-0 records show the gap |
| 08-5 | Compile parts and `concept_map` calls side by side within a protocol, at most the gateway's free slots | M | A2 | 08-1 | stub test of order-independent results; G-1's records: compile wall time |
| 08-6 | Compact JSON answers (schema unchanged; prompt version up) for `ir_extract`, `judge`, `concept_map`; judge answer cap 384 | S | H | – | the pair gate unchanged; answer tokens down 17 % on the `ir_extract` replay |
| 08-7 | `tools/servebench`: the standing serving benchmark (5.1), stub nightly, GPU at qualification, thresholds written into the serving record | M | D + G | 08-1 | nightly line; the qualification step fails a planted slow server |
| 08-8 | An interactive lane: two slots per endpoint reserved for interactive roles; `--scheduling-policy priority` with a lower priority value for them | M | A2 + D | 08-3 | a console check during a stub night answers within the interactive limit |
| 08-9 | Judged-pair store across nights for non-time-sensitive criteria: key on excerpt-set hash and absolute window dates | M | A2 | owner decision 4 | a replay of two nights of the synthetic hospital: hits above 50 % on unchanged patients, 0 changed verdicts on the audit sample |
| 08-10 | Drop `--enforce-eager` on the decided profiles; `TB_EXTRACT_RATE_PER_S` from the record (part size) | S | D | G-1 | G-1's record; V1 |
| 08-11 | Engine update to the current release with requalification (with 9g-10) | S + run | D | G-1, G-2 | G-4 and V1 |
| 08-12 | n-gram speculative decoding in the profile, if G-5 passes | S | D | G-5 | G-5's record |
| 08-13 | Stage budgets of 6.3 in the bench gate (APPROVE, compile check, gateway overhead lines) | S | B2 | 08-4 | the gate fails a planted slow stage |
| 08-14 | The capacity statement (T-667) restated with this formula: first-load days and nightly hours per hospital size and box | S | G | G-4 | the statement cites G-4 |
| 08-15 | A "CPU notes" profile (llama.cpp verifier-sized model), only if G-6 passes; a single model never excludes | L | D | G-6, owner decision 5 | G-6 |

Counts: S 9 (08-1, 08-2, 08-3, 08-6, 08-10, 08-11, 08-12, 08-13, 08-14), M 5 (08-4, 08-5, 08-7, 08-8, 08-9),
L 1 (08-15). The plan-9 cards this changes: 9g-8 is replaced by 08-1; 9g-9 becomes 08-10; V23 becomes section 5's
list. 9d-9 (P12) stays as written.

---

## 8. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | **Run G-1** (CUDA graphs, sigir twice): about 5.5 VM hours, about US$15 spot (US$45 on demand) | **Yes, first**, after 08-1 and 08-2 are merged, so the run records what it measures |
| 2 | **Run G-2** (seqs and threads, tcga:500): about 1.5 h, about US$4 (US$12) | Yes, right after G-1 |
| 3 | **Run G-4** (the 50,000 night and qualification on the current engine): about 3 h, about US$8 (US$25); and **G-5** (speculative decoding): about 2.75 h, about US$8 (US$23) | G-4 yes; G-5 only if G-1 leaves `ir_extract` the compile's bottleneck |
| 4 | **Reuse a judged answer across nights** for a criterion that is not time-sensitive, when the notes it read are byte-identical (card 08-9). It changes D-908's key | Yes, with the audit sample always asked live |
| 5 | **The GPU-less box**: does a site without a GPU get note screening by a CPU model (slow, single model, never excludes), or does it stay "coded criteria only"? | Measure G-6 on your own machine first (no cost); decide after |
| 6 | **The reference hardware**: the RTX PRO 6000 Workstation Edition (600 W) or the Max-Q (300 W). Today's peak was 293 W [M 7]; after tuning the Max-Q's cap may bind | **Keep the order open between the two until G-4** reports the power under the tuned night; if G-4 peaks above 300 W, choose the Workstation Edition unless noise rules it out |
| 7 | **The engine stays vLLM** for 1.0; no SGLang, TensorRT-LLM or TGI A/B is paid for | Yes |

---

## 9. Order (what waits for what)

1. 08-1 and 08-2 (code, free). Then 08-4, 08-5 and 08-6 (code, free; their stub proofs).
2. G-1, then G-2 (paid, owner's yes). Then 08-10 and 08-3.
3. G-4 on the current engine with requalification (08-11). Then 08-14, the capacity statement.
4. G-5 only if needed. G-6 and G-7 on owned hardware. 08-7 and 08-8 alongside.

---

## 10. Measurement log

Scripts are in the session's scratch folder (not committed). Each reads only the public P2b stored sets, extracted
with `git archive 2bcf5ca9 trialbox/.p2b-artefacts trialbox/deploy/measured` and `tar -xzf` of `sigir.tgz`,
`tcga.tgz` and `jmed.tgz`. Run with `python3 -I`; outputs are kept under `/var/tmp/trialbox-0/b8/`.

| # | Command (script: what it does) | Result |
| --- | --- | --- |
| 1 | `traces.py <p2b> libs/tb_llm/budget.py`: per prompt and model, the counts, the estimated tokens in and out (median, p95, max, sum), the answer whitespace, the compact-JSON answer tokens, the system share, the shared prefix with the previous call and with any of the last 50 calls, completions per minute, duplicates; and the estimator against the screen reports' engine tokens | the table of 1.1; sigir 1,245 calls in 6,710 s; tcga 979 in 363 s; calibration engine/estimate in 0.854, out 0.946 (sigir), in 1.051, out 1.125 (tcga) |
| 2 | sigir `services.log`, the WARNING lines of `criteria-compiler` | 7 "the gateway gave up on the answer; asking it again in 2 or 3 parts"; `gateway-audit.json`: `upstream_failed` 7 |
| 3 | `decode.py`: consecutive calls of one job; for `ir_extract` to `ir_extract` with more than 300 answer tokens, answer tokens / gap | 77 pairs: 36.8 tokens/s median (p10 32.6, p90 42.6), gap 23.9 s, 925 tokens; `concept_map` consecutive gap 0.47 s (577 pairs) |
| 4 | tcga `progress.json` `screen_metrics`; trace span of the judge calls | 1,020 calls, 1,509,865 in, 117,284 out, wall 323.8 s; judge calls 08:03:29 to 08:08:48 (319 s) |
| 5 | `waterfall.py`: per sigir protocol, the FEAS trace span, the gap from the last FEAS call to the first SCREEN call, the screen wall | ir 1.9, cm 6.5 a protocol; FEAS span mean 28.3 s; gap mean 116.6 s, median 117.8, p95 178.8 (81 protocols); screen wall mean 8.3 s |
| 6 | `copyshare.py`: share of answer characters inside runs of 20 or more characters found verbatim in the prompt | `ir_extract` 0.377; judge 0.441; verifier 0.491; `concept_map` 0.113 |
| 7 | G1 2026-11-12 (superseded) `parts/hospital-ja@c{1,4,16,48}.json` `metrics` and `vllm.csv`, `gpu.csv` read with `csv` | the table of 1.5; judge prompt tokens 280,906 / 335 requests (c1), TTFT mean 0.061 s, e2e 2.72 s |
| 8 | `capacity.py`: the formula of 4.1 over N, S and d | the table of 4.2 |
| 9 | `python -m tools.box_run estimate --steps acc --mode validation --only sigir` and `--steps start,acc --only tcga:500` (main checkout's interpreter; free, no cloud call) | sigir: cap 2 h = US$5.48 spot / US$16.44 on demand; tcga: cap 5 h = US$13.7 / US$41.1 |
| 10 | `grep` on master `8778394f` for `sys.modules` `pandas` entries and for `bisect` in `services/criteria_compiler/terminology/mapper.py` | none of either |
| 11 | `inputws.py`: judge, `ir_extract`, `concept_map` prompt JSON blocks pretty against compact | input saving 0.8 % (tcga judge), 3.5 % (sigir judge), 13 % (`ir_extract`, `concept_map`) |

---

## 11. What this document did not verify

- **Any figure on a GPU.** Nothing was run on a GPU. Every rate after a change (9 and 18 calls a second, the "several
  times" from CUDA graphs, the CPU serving rates) is an estimate until G-1, G-2, G-4 and G-6 run.
- **Whether P2b ran the shipped serving or the owner's "tuned" exception.** Its stored sets do not say. If it ran
  tuned, CUDA graphs were on in P2b, and the 36.8 tokens a second is not the eager figure. G-0 settles this for
  every later launch.
- **Per-call latency.** It was derived from consecutive timestamps and from Little's law, not measured. The G1 run
  that measured it is superseded (another chat-template setting, an old commit).
- **What the 117 s between compile and screen consists of.** Card 08-4 profiles it.
- **The engine's prefix-caching default** for these two models at v0.32.0. The documentation opened does not state
  it, and the v0.32.0 guide excludes some hybrid models. The verifier's place on that list was not checked.
- **Whether xgrammar in v0.32.0 lets the server forbid whitespace in JSON.** The docs opened name no such switch.
- **Support for the RTX PRO 6000 (SM120) in the NVFP4 MoE speed-ups** of v0.33 and v0.34. The notes name
  data-centre Blackwell only.
- **The release notes' later sections** (the page was read to 100,000 of about 209,000 characters). Advisories after
  v0.32.0 may exist beyond what was read.
- **The Spark-class box's decode rate, and WSL2's overhead on the reference workstation.**
- **The token counts.** They are TrialBox's estimator, within 15 % of the engine's on the two sets checked, not the
  models' tokenizers. No model or tokenizer was downloaded.
- **Licences and terms of the NGC containers for TensorRT-LLM, and SGLang's telemetry.** Not opened.
