# TrialBox: text mining, hardware and serving assessment

Prepared 2026-11-15 for the owner. Read-only. Code references are `file:line` at committed HEAD `ca6e0f0f9`
(branch `claude/trialbox-plan-v4-oxn56n`, the checkout at `/home/user/Auto-GPT/trialbox`; it is not named `master`).
The working tree also has **uncommitted edits by another worker** (engine.py, excerpts.py, screen_cascade.py,
model.py) that add "skip S2b when the window fits" (marked D-910 in the code). This report treats them as in progress,
not shipped. Models are named generically: **the judge** (26B-total / ~4B-active MoE, NVFP4, 18.8 GB of weights),
**the verifier** (9B dense, AWQ 4-bit, 9.1 GB), **the embedder** (multilingual sentence encoder, ~2.3 GB fp32).
Weight sizes are the summed safetensors in `deploy/measured/serving_config.rtxpro6000.json`.

**Labels.** Each figure is one of these:
- **[M]**: measured, in the repository or the caller's PoC-1 facts.
- **[W]**: web source, with URL and access date 2026-11-15.
- **[E]**: my estimate, with the arithmetic shown.
- **[U]**: could not verify.

## 0. Three corrections to the starting picture

1. **The PoC cloud GPU is an RTX PRO 6000, not an L4 or L40S.** The PoC-1 VM `tb-gpu-sim` is a GCP
   `g4-standard-48` (`deploy/gcp/complete-run.sh:3,786`), and its serving record names an "NVIDIA RTX PRO 6000
   Blackwell Server Edition", 97,887 MiB, driver 580.178.04, CUDA 13.0 [M] (`deploy/measured/serving_config.rtxpro6000.json`).
   So the baseline already ran on the target card. The PoC was slow because of the pipeline, not the hardware.
2. **The job was not bound by the GPU.** Of the 1,275 s, about 960 s was CPU sentence embedding in S2b, and the GPU
   sat idle through it (`note-preprocessing-review.md` §1). The ~1,010 judge calls took the other ~300 s.
   - "43 per minute" is the call count divided by the whole job's wall time (1,010 / 1,275 s × 60 = 47.5).
   - While calls were in flight, the rate was about 3.2 per second (p50 3.45 s with about 11 in flight) [M/E].
   - The same card in the G-3 run gave 4.39–4.61 calls/s at 16 in flight, p50 2.7–2.8 s, GPU 62–76 % mean [M]
     (`docs/plan/measurements/g3-2026-11-13/report.md:330-345`; that folder is marked SUPERSEDED as product
     evidence, but its throughput figures are still a measurement of this card and flags).
3. **The embedding fixes are already at HEAD but unmeasured.** HEAD carries D-900: the embed service loads once,
   caps input at 512 tokens, batches by tokens, and SCREEN embeds each sentence once (`TB_EMBED_CACHE_VECTORS`,
   `libs/tb_common/config.py:573-577`; `services/embed_service/embedder.py:118,166-168`). The uncommitted D-910
   work skips S2b where it cannot change the prompt. PoC-1 ran at `1157c9bfa`, which is **not an ancestor of HEAD**.
   The first action is a re-run, not new hardware.

## Part 1: What text mining the cascade already does (before any LLM)

### 1.1 Inventory, from the code

| Stage / technique | What it does | Where (HEAD) |
|---|---|---|
| S0 population | SQL: an encounter in the lookback; consent opt-outs removed | `cascade/engine.py:297-306`, `tb_common/optout.py` |
| **S1 compiled SQL** ("standard conversion for easy ones") | Every structured or mixed criterion (age, sex, ICD-10 / ATC / LOINC ValueSets, lab thresholds, windows) is IR→SQL on coded data, three-valued, no model | `engine.py:1-12, 94-95` (FILTERED / JUDGED); compiler `criteria_compiler/compile_sql` |
| Terminology and value sets | ICD-10-CM (TW), NHI drug→ATC, LOINC (TW), NHI orders, departments, synonyms as Parquet; WHO↔CM bridge; JP YJ→ATC (57 rows), MEDIS 標準病名 and JLAC10→LOINC loaders; a terminology release hash checked at run | `criteria_compiler/terminology/mapper.py:1-5,148,397`; `resolver.py:1-20`; `tb_common/refdata_jp.py:1-6,158,193`; `refdata_tw.py:1-3,140,255`; `refdata_src/*.csv` |
| Clinical synonyms for the name matcher | ja 70 rows, zh-TW 42 rows (concept-name → canonical) | `tb_common/refdata_src/ja_clinical_synonyms.csv`, `zh_tw_clinical_synonyms.csv` |
| Lab values (coded rows) | Number parser with flags (H/L/↑/高), censored values (`<0.3`, `0.3未満`), non-numbers (`陰性`) → unknown; UCUM spellings; unit conversion only within one kind; mismatch → unknown, never a fail (D-130, D-275, D-418) | `tb_common/labvalue.py:1-30,51,195,282`; `tb_common/labunit.py:1-30,174,213` |
| Derived values | BMI, eGFR (CKD-EPI 2021 and JSN), DAS28 with unit conversion | `tb_common/derived.py:1-10,214,284-315` |
| Dates | ISO, 和暦 eras, 民國 years, 年月日, one module | `tb_common/dates.py:1-6,52,64,83,149`; `sitesetup/messy.py:81-99` |
| Suspected diagnosis (疑い) | FHIR `verificationStatus` provisional/differential/unconfirmed and SS-MIX2 疑い are never coded (D-142) | `lake/flatten.py:167-169,227,759`; `matching/proposed.py:11-13,40` |
| Note read and normalisation | Notes in the window, newest first; NFKC + whitespace fold; a lower-cased copy per sentence, once per note | `engine.py:309-313, 316-328`; `cascade/judge.py:243-248` |
| Sentence split | CJK stops, `!?`, line ends, English full stops with an abbreviation guard and a label rule | `matching/excerpts.py:47,52,60-95` |
| Section / heading cues | Bracketed headings (【既往歴】, [Family history]) and lone symbol-led lines are kept as context when a note is clipped, so a list is never shown without its heading. **Used only for clipping, not for deciding** | `excerpts.py:130-150, 153+` |
| **S2 lexicon** | Substring match of the criterion's terms in the window sentences; a hit routes the pair to S3 with the hit notes first | `engine.py:713-779` (hit at 755-756) |
| The S2 lexicon itself | Unless a site table is given (SCREEN gives none), it is a **31-entry hand table** of English words with zh-TW/ja equivalents (gout, RA, TB, hepatitis, cancer, EGFR …) | `orchestrator/scenarios/terms.py:11-66`; `engine.py:286-293` |
| CAS-13 certified absence | A criterion certified for zero-hit absence can be decided at S2 with no model | `engine.py:142, 768-777` |
| **S2b semantic screen** | Embeds query + every window sentence; cosine; top-5 ranks the excerpts. In SCREEN (`absence_semantics=False`) every pair still goes to S3 | `engine.py:817-900`; `cascade/s2b_semantic.py:84-107`; `screen_cascade.py:614` |
| Excerpt builder (D-479) | Whole notes within a token budget, evidence first, clipped around evidence; `left_out` counted (D-276) | `excerpts.py:282-297` |
| Span check (CAS-16) | The judge's quote must match an excerpt character for character | `judge.py:251+` |
| Negation (charts → proposed facts) | Rule-based negation for ja, zh, en, clause-bounded (なし, 否定, 認めず, 否認, 未見, no/denies/ruled out), heading and family-history reach. **Used only on chart-upload facts, not in the SCREEN cascade** | `sitesetup/charts.py:181-266, 329` (D-657) |
| Negation (criteria text) | A negated exclusion question is rewritten to the positive form and flagged | `criteria_compiler/ir_extract/polarity.py:47,53`; `postprocess.py:175-213` |
| Hedging / history | **Only in the judge prompt text**: "suspected, possible, rule out → unknown; resolved → history" | `libs/tb_llm/prompts/judge_v5.md` (system) |
| Retrieval elsewhere | BM25 + dense fusion for registry matching, CJK bigram tokens in the lake | `matching/registry_match/retrieval.py:1-40`; `lake/textproc.py:1-48` |
| PHI mask | A length-keeping mask in the embed service; a rules pass for notes | `embed_service/app.py`; `tb_common/phi_guard.py` |

**Verdict.** The structured side already has strong classical machinery: SQL, terminologies, unit-safe labs, dates
and derived scores. **The note side has almost none.** Every SCREEN note pair with any note in its window goes to
the judge (then the verifier). The things the owner names (negation, temporality, experiencer, value extraction
from text, concept matching, dedup) are either absent from the cascade or exist only on the chart-upload path.

### 1.2 The safety rules each technique must respect

- **D-131 / D-135** (`docs/DECISIONS.md:1798, 2061`; `matching/proposed.py:1-25`):
  - A fact read from a chart by a model is *proposed*. It lives only in `site_fact`, which the compiled SQL never
    reads.
  - A proposed fact can only turn a decided answer into `unknown` (reason `proposed_fact`).
  - Once a coordinator confirms it, it counts as coded data and may exclude.
- **D-478** (`docs/decisions/D-478-one-status-function.md`): `answer_of` lets a note answer say `no` only when four
  things hold:
  - it is final;
  - its basis is `pair` (two different models);
  - its confidence reaches the threshold;
  - the run may exclude on notes.
  The basis values are `coded | pair | single | person`. There is no `rule` basis.
- **Consequence for classical NLP.** Without a new decision, a regex or classifier result has the status of a proposed
  fact. It may:
  - (a) widen to unknown;
  - (b) choose excerpts;
  - (c) skip a model call only where the model's answer could not change the outcome.

  It may **not** exclude or mark "met" on its own. Letting a qualified deterministic extractor decide needs a
  **new D-number** (a `rule` basis, qualified like a code mapping, with per-language precision on labelled data). That
  is owner decision O-1 below.

### 1.3 Gap list: classical techniques that would settle "easy" items without an LLM

Cost key: S < 1 week; M = 1–3 weeks; L > 3 weeks.

| # | Technique | What it decides | Accuracy risk | Cost | Plugs in at | Fit with D-131/135/478 |
|---|---|---|---|---|---|---|
| T1 | **ConText / NegEx-style** cues: negation, hypothetical, historical, family (experiencer), for ja (なし, 否定, 疑い, 既往, 家族歴), zh (否認, 無, 疑似, 家族史) and en. Reuse the D-657 rules in `sitesetup/charts.py:189-266` | Marks each lexicon hit as affirmed / negated / uncertain / other-person / historical | Medium: rule cues miss long-range scope; ja/zh have no open ConText rule set (medspaCy lists no ja/zh, see §W) | M (port D-657 rules into S2, plus a test corpus per language) | S2 hit filter (`engine.py:755-766`) and the excerpt ranker | Allowed for routing and widening: an affirmed hit for an exclusion stays an LLM pair. A pair whose only hits are negated, family or hypothetical can stay with the LLM (safe) or, under O-1, become "no mention". Never an exclusion |
| T2 | **Section detection** (既往歴, 現病歴, 家族歴, 診断, 所見, Impression, Diagnosis, PMH) | Ties a mention to its section: family-history section ⇒ experiencer ≠ patient; plan or differential ⇒ uncertain | Low–medium: site templates vary; a per-site header list is needed | S–M (extend `_is_heading`, `excerpts.py:130-150`, to a labelled sectioniser) | Before S2; feeds T1 and the ranker | Safe (routing only) |
| T3 | **Values from note text** (ECOG/PS, TNM pT/pN/M, stage, grade, HER2 0–3+, EGFR/ALK status, LVEF %, lab "Cr 1.2 mg/dL"), unit-normalised with the existing `labvalue.parse` / `labunit.conversion` | Compares a number with the criterion threshold | Low for templated pathology text, medium for free text; units and dates must be bound to the right test | M (per analyte: regex + unit + date binding + a gold set) | A new S1.5 "note facts" step before S2 | Today: a **proposed fact** (widen only; also an evidence pointer and a confirm task for a coordinator). Under O-1, a qualified extractor could decide value criteria |
| T4 | **Medication normalisation** (brand/generic/kana/kanji → ATC; YJ in JP, NHI code in TW) | Medication-history criteria from note text | Low with a curated list; JP YJ→ATC has only 57 rows today (`refdata_src/jp_yj_atc.csv`) | M (load the full NHI ATC table, already a refdata item, and a JP 薬価基準 YJ list [U: licence]) | T3's step; S2 lexicon expansion | As T3. RxNorm adds little for JP/TW (US-centric) |
| T5 | **Dictionary concept matching**: QuickUMLS / medspaCy (en), MeCab or SudachiPy + MANBYO/J-MeDic (ja), jieba (zh) + the existing synonym CSVs | Replaces the 31-word S2 table with ICD-10-anchored synonyms per criterion ValueSet | Medium: dictionary recall, abbreviation ambiguity (RA is flagged ambiguous in both CSVs) | M–L | S2 lexicon (`lexicon_terms`, `engine.py:286`) | Safe (routing). Licences below |
| T6 | **Copy-forward dedup**: hash of normalised sentences or notes | Shows each repeated note once; embeds once | Low if only exact duplicates; near-duplicate (MinHash) needs care with D-276 `left_out` | S | Excerpt builder; S2b input | Safe if the judge still sees source offsets (CAS-16) |
| T7 | **Embedding retrieval + cross-encoder reranker** on stored vectors (`vec/` is built but unused) | Better evidence ranking; with a certified threshold, "no mention" | Medium: recall must be certified (CAS-13); halfvec ≠ fp32 vectors (D-449) | M | S2b (`vec.s2b`, D-449) | Ranking is safe. Absence-deciding needs CAS-13 certification per criterion |
| T8 | **Small classifier / fine-tuned encoder** for frequent criterion types (e.g. "active malignancy", "pregnancy", "HBV/HCV status", "prior therapy X") | Pass / fail / unknown per pair | Medium–high: needs labelled site data per language; drift | L | Before S3, as a router or a third opinion | Today: router only (a confident "no mention" saves calls; a confident "fail" still goes to the pair). As a third opinion that can **block** a pair's exclusion: safe and allowed |
| T9 | **Persist extracted facts and judged pairs** (CAS-5 cache; NOTE_NLP-style fact table with provenance) | Reuse across runs and trials; confirmed facts move to S1 | Low if keyed as `note-preprocessing-review.md` §2 says; refusals never stored | M | `engine.py:367,1036-1055` (in-run cache today); new `judged` schema | Fits D-478 if the raw verdict is stored and `answer_of` is re-applied on read. Confirmed facts are the D-131 path to "no LLM next time" |

**Licence fit for on-prem (commercial box).**
- **Safe:**
  - medspaCy: MIT, latest 1.3.1 of 2024-11-21, languages listed en/fr/nl/es/pl/pt/it/de, no ja/zh [W:
    github.com/medspacy/medspacy].
  - QuickUMLS code: MIT [W: github.com/Georgetown-IR-Lab/QuickUMLS].
  - SudachiPy: Apache-2.0, but that repository was archived on 2023-03-09 and work continues as Sudachi.rs [W:
    github.com/WorksApplications/SudachiPy].
  - jieba: MIT [W: github.com/fxsjy/jieba].
  - TEI: Apache-2.0 [W: github.com/huggingface/text-embeddings-inference].
- **Needs a decision:**
  - QuickUMLS **requires an NLM UMLS licence** to build its index (same source). Its Japanese and Chinese content is
    thin [U], so it is not a fit for ja/zh notes.
  - CKIP Transformers is **GPL-3.0** [W: github.com/ckiplab/ckip-transformers]: avoid on a sold box, or isolate it as a
    separate program after legal review.
  - The MANBYO dictionary licence is **[U]**. NAIST now points to "JMED-DICT mini" as open and commercially usable
    [W: sociocom.naist.jp/manbyo-dic-en/].
  - The MeCab and Sudachi dictionary licences were not re-verified [U].
- **scispaCy** (en, biomedical) is Apache-2.0 [U: not re-fetched]. It adds little for ja/zh notes.

### 1.4 How many of the measured judge calls could be removed

- **Where the calls come from.** PoC-1 is 500 patients × 1 note criterion, about 1,010 calls. The verifier runs only
  on a decided judge answer (`engine.py` S4), so this is about 505 judge + about 505 verifier calls: the judge
  decided nearly every pair. In a one-report-per-patient set (TCGA) the note nearly always mentions the topic.
- **Under today's rules (no O-1), inside one run:**
  - T1, T2, T5 and T7 can remove only pairs whose window has **no affirmed mention**. The judge is told not to
    infer from absence, so for those pairs it answers unknown anyway.
  - With the judge deciding ~all pairs, that share is small: **about 0–10 % of calls [E]**.
  - T6 removes about 0 % here (one report per patient).
  - The real saving inside this run is the ~960 s of S2b, not calls.
- **Across runs:**
  - T9 (CAS-5 cache) removes up to **~100 % of calls on a re-run** at the same index date and with the same notes.
  - CAS-7 targets > 80 % hit.
  - Confirmed facts (D-131) move a criterion to S1 permanently.
- **With O-1** (a qualified `rule` basis for templated value criteria such as TNM, stage, ECOG, HER2 or a numeric lab
  in a report): **about 30–60 % of value-type pairs [E]**, LLM as fallback when the extractor is unsure. This is not
  measured. It needs a labelled set per language, and precision at least that of the pair: the pair wrongly blocked
  1 of 250 eligible patients [M].
- **Accuracy upside of classical NLP.** T1 and T2 used as a **veto**, widening a pair's "fail" to unknown when the only
  evidence is negated, family or hypothetical, are allowed by D-478 and can only lower wrong blocks. Cost: a few of the
  83 % catches may go to review [E].

## Part 2: Hardware

### 2.1 Specifications (all [W], accessed 2026-11-15)

| | RTX PRO 6000 Blackwell **Server Ed.** (the PoC card) | RTX PRO 6000 Blackwell **Workstation Ed.** | DGX Spark (GB10) | RTX 5090 |
|---|---|---|---|---|
| Memory | 96 GB GDDR7 ECC | 96 GB GDDR7 ECC | 128 GB LPDDR5x unified (64 GB OEM option) | 32 GB GDDR7 |
| Bandwidth | **1,597 GB/s** | **1,792 GB/s** | **273 GB/s** (256-bit) | **1,792 GB/s** (28 Gbps, 512-bit) |
| FP8 / FP4 | FP8 2 PFLOPS; FP4 4 PFLOPS | FP4 4,000 TOPS (sparse) | FP4 1 PFLOP (sparse) | 3,352 "AI TOPS"; FP4 yes |
| Power | up to 600 W, configurable | 600 W | 240 W PSU; GB10 TDP 140 W | 575 W |
| Multi-GPU | PCIe Gen5; no NVLink listed; **MIG up to 4** | MIG stated for the Max-Q variant only (WS unclear) | 2 units over one QSFP cable (ConnectX-7, 200 Gb/s) = 256 GB; 4 need a switch | PCIe only [U: NVLink absence not stated on the page] |
| Price | in-server price [U]; GCP g4-standard-48 on-demand **US$4.50/h** (Google pricing page via search); repo uses spot **US$2.74/h** [M] | launch ≈ US$8,565 (TweakTown); NVIDIA marketplace US$13,250 → **US$16,000** (2026 reports); US street low US$11.7k (Jul) to US$17.1k (29 Oct 2026) | US$3,999 → **US$4,699** from 2026-02-23 (NVIDIA forum; Tom's Hardware); a later **US$6,950** for 128 GB is reported [U] | MSRP US$1,999; street **US$4,300–9,400** (Aug–Oct 2026 reports) [U: secondary sites] |

Sources:
- nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/
- nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/
- nvidia.com/en-us/products/workstations/dgx-spark/
- nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5090/
- techpowerup.com/review/nvidia-geforce-rtx-5090-founders-edition
- cloud.google.com/products/compute/pricing/accelerator-optimized
- forums.developer.nvidia.com/t/2-23-2026-price-change-announcement/361713
- tomshardware.com (DGX Spark +18 %)
- implicator.ai (US$6,950)
- thundercompute.com/blog/nvidia-rtx-pro-6000-pricing
- gpuprix.com; letsdatascience.com
- guru3d.com; tweaktown.com (5090 street prices)

### 2.2 What the pair needs, and whether it fits

- **Judge:** 18.8 GB of weights [M]; KV about 110 KiB per token [M].
  - The KV figure comes from fit.json: 10.19 GiB → 96,930 tokens (`docs/plan/measurements/gpu-run-2026-11-08/fit.json`).
- **Verifier:** 9.1 GB of weights [M]; KV about 45 KiB per token (the compose comment; the fit gives 19.88 GiB →
  459k tokens, ≈ 45 KiB).
- **Prompt size:** a SCREEN call is about 1,040 tokens in and out [M: G-3 4,580 tok/s ÷ 4.39 calls/s]. The output is a
  short JSON (verdict, reason ≤ 300 chars, quote ≤ 400 chars; `schemas/llm_judge_output.schema.json`), so about
  100–250 generated tokens [E].

| Box | Profile in repo | Fits both resident? | KV room at that profile | Measured? |
|---|---|---|---|---|
| PRO 6000 (96 GB) | `docker-compose.rtxpro6000.yml`: judge 0.40, verifier 0.20, 32k context, 16 seqs, both resident | **Yes** [M]: 62,574 MiB used; ~40 % of the card idle | judge ~180k tokens, verifier ~200k ⇒ **~170 SCREEN calls in flight by memory** [E] | **Yes**: serving record 2026-11-08; G-3 throughput 2026-11-13 |
| DGX Spark (128 GB unified) | `docker-compose.gb10.yml`, `gb10-profile.yaml`: 0.30 + 0.15, 16k, 8 seqs, both resident; driver held at 580.142 | **Yes on paper** [E]: 28 GB weights + KV in ~58 GB | ample | **No**: `gb10-profile.yaml` says `status: unmeasured`; no Spark run |
| RTX 5090 (32 GB) | `docker-compose.rtx5090.yml`: 8k context, 4 seqs, **sleep-mode swap** (one model awake) | **No** side by side (~35 GiB needed, measured on a PRO 6000 capped to 32 GB) [M] | judge awake: ~7 GiB KV ≈ 65k tokens [M: fit "sleep-swap" 7.34 GiB → 69,836 tokens] | **Partly**: emulated by capping a PRO 6000; never on a physical 5090 |

### 2.3 Decode speed: the memory-bandwidth bound

**Method.** At small batch, one decode step reads the active weights once, so tokens/s ≤ bandwidth ÷ bytes per step.

**Bytes per step.**
- Judge: about 3.8–4B active of 26B. At the build's ~0.72 bytes per parameter (18.8 GB ÷ 26B, because embeddings and
  attention are not FP4), that is **~2.8 GB per step** [E].
- Verifier: dense, **~9.1 GB per step** [E].

**Single-stream ceilings [E]:**

| | PRO 6000 Server (1,597) | PRO 6000 WS / 5090 (1,792) | Spark (273) |
|---|---|---|---|
| Judge ceiling | ~570 tok/s | ~640 tok/s | **~98 tok/s** |
| Verifier ceiling | ~175 tok/s | ~197 tok/s | **~30 tok/s** |

- **Real figure on the Spark:** a community run of the judge family (NVFP4, vLLM, marlin MoE backend) measured
  **~52 tok/s single stream** and 115 tok/s aggregate at 3 parallel requests [W:
  ai-muninn.com blog, "DGX Spark part 7" (the URL names the model; omitted here); published 2026-04-05, updated 2026-06-21]. That is about
  53 % of the ceiling, which confirms the Spark is bandwidth-bound.
- **The verifier on a Spark is the slowest link.** The dense model at 273 GB/s has a ceiling of ~30 tok/s per stream.
  Batching helps, because the weights are read once per step for the whole batch.
- **Same model, Spark vs PRO 6000:** a 35B-class ~3B-active NVFP4 MoE reached 268 output tok/s on a Spark against
  1,053 on an RTX PRO 6000 (4 sequences, decode-heavy) [W: forums.developer.nvidia.com/t/…/371810, 2026-05-31]. That is
  a **~3.9× gap**, close to the 1,597/273 = 5.8× bandwidth ratio once compute and overheads are counted.

### 2.4 SCREEN throughput per box (500 patients × 1 note criterion, ~1,010 calls)

Baseline PoC-1 [M]: 1,275 s ⇒ **~1,410 patients/hour per criterion**.

| Box | Judge-call phase | Embedding (S2b) | SCREEN total | Patients / hour |
|---|---|---|---|---|
| PRO 6000, PoC-1 as run (`1157c9bfa`) | ~300 s [M] | ~960 s CPU [M] | 1,275 s [M] | **1,410** [M] |
| PRO 6000, HEAD + D-910, 16 in flight | 1,010 ÷ 4.5/s ≈ **225 s** [E from G-3 M] | ≈ 0 when the window fits (TCGA) [E]; D-900 caps the rest | **~240–320 s** [E] | **~5,600–7,500** [E] |
| PRO 6000, + CUDA graphs, 32–48 in flight | ~7–10 calls/s ⇒ **100–145 s** [E: G-3 scaled ~linearly c1→c16 (0.39→4.5/s) with p50 only +20 %; GPU 62–76 %] | ≈ 0 | **~120–170 s** [E] | **~10,500–15,000** [E] |
| PRO 6000 Workstation Ed. | ~10 % faster than Server Ed. at the same flags (1,792 vs 1,597 GB/s) [E] | same | same ±10 % | same ±10 % |
| DGX Spark, profile as written (8 in flight) | 1,010 calls, about 4–6× the PRO 6000 time ⇒ **~900–1,400 s** [E: §2.3 ratio] | S2b on a 20-core ARM CPU [U: unmeasured]; ≈ 0 with D-910 | **~950–1,500 s** [E] | **~1,200–1,900** [E] |
| DGX Spark, tuned (marlin MoE, CUDA graphs, 16–32 in flight, speculative) | ~500–800 s [E: the community +35–45 % MTP gain was on another model, U] | ≈ 0 | **~550–850 s** [E] | **~2,100–3,300** [E] |
| RTX 5090, profile as written (4 in flight, sleep swap, two-phase) | 1,010 ÷ 1.43/s [M: G-3 c4] ≈ 700 s + one swap (~4 s [M]) + canary; **two-phase re-runs S2/S2b up to 3 rounds** (`twophase.py:47`) | up to ×3 without the D-900 memo; ≈ 0 with D-910 | **~750–800 s** with D-910 [E] | **~2,300–2,400** [E] |
| RTX 5090, 16 in flight (KV allows ~65k tokens ≈ 16 × 1.2k with room) | ~250–300 s [E: bandwidth equals the PRO 6000 WS] + swap | ≈ 0 | **~300–350 s** [E] | **~5,000–6,000** [E] |

**Bottleneck per box:**
- **PRO 6000 (the PoC card):** the pipeline (serial CPU S2b ahead of S3) and a 16-call cap. The card ran at 62–76 %
  and 40 % of its memory was idle. Bandwidth is not the limit at today's load.
- **DGX Spark:** **273 GB/s unified memory for decode** [W, verified on nvidia.com]. The verifier (dense) suffers most.
  Prefill of ~1k-token prompts is also compute-bound on the smaller GPU [U]. The unified memory is shared with
  Postgres, HAPI, DuckDB and the embedder (`gb10-profile.yaml` memory table). Fit is not the problem; speed is.
- **RTX 5090:** **32 GB capacity**, which forces the sleep swap, 8k context (smaller excerpt budget, so more `left_out`
  and more unknowns), and two-phase re-computation. Its bandwidth equals the PRO 6000 Workstation's. Street price is
  now a large part of the PRO 6000's price [W/U].

**What each can do, in one line:**
- **PRO 6000:** the reference box. It runs both models at 32k, protocol reading on the box, and 5–10× today's SCREEN
  rate with no new hardware. MIG (up to 4) can hard-split judge and verifier if isolation is wanted [U: MIG with this
  pair unmeasured].
- **Spark:** a quiet, low-power box at roughly 1–2k patients per hour per criterion. Nightly SCREEN of a 5k-patient
  site is fine; 50k is a long night [E]. It is unmeasured, its driver is pinned, and its price is rising.
- **5090:** works only with swapping and 8k context. It needs a physical-card measurement before sale (D-112), and its
  street price no longer makes it cheap.

## Part 3: Serving

### 3.1 What the box runs now [M]

Source: `docker-compose.rtxpro6000.yml:52-82`; `deploy/measured/serving_config.rtxpro6000.json`.

- **Engine and model:**
  - vLLM `v0.32.0` pinned by digest (D-348). vLLM v0.32.0 was released 2026-10-18 and v0.33.0 on 2026-11-02 is the
    latest [W: github.com/vllm-project/vllm/releases]. **The engine is current.**
  - Judge: NVFP4 (publisher quantisation), `--max-model-len 32768`, `--max-num-seqs 16`, `--gpu-memory-utilization
    0.40`, `--enforce-eager`, `kv_cache_dtype auto`, multimodal off, pinned chat template.
  - Verifier: AWQ 4-bit, 32768, 16 seqs, 0.20, `--enforce-eager`, thinking off.
  - Two servers on one GPU, both resident (`TB_MODEL_SWAP=off`); the verifier starts after the judge is healthy.
    The 5090 uses `--enable-sleep-mode` with one swap per run (`rtx5090.yml:103-136`).
- **Flags left at vLLM defaults:** no flag for prefix caching, chunked prefill, async scheduling, speculative
  decoding, `max-num-batched-tokens` or the structured-output backend. The repo's own review says the backend is
  "auto, not named" (`docs/reviews/2026-11-12-deep-review/06-llm.md:87`).
- **Request side:**
  - Sampling: temperature 0, seed 20261025 (`models/routing.yaml:17`).
  - Every judge call sends a `json_schema` `response_format` (`cascade/judge.py:133`; the gateway refuses one without
    it, `gateway/core.py:499-501`), so **guided JSON is already on**.
  - `max_tokens` 1024 (`judge_v5.md`).
  - Concurrency: `TB_SCREEN_LLM_CONCURRENCY` = max-num-seqs (16), with a ceiling of 64 in code
    (`orchestrator/jobs.py:351-358`).
- **Embedder:** CPU, fp32, a separate FastAPI service. Cards are forbidden in its overlays
  (`tests/unit/test_embed_review.py:92`, per the review).

### 3.2 Against the current state of the art (docs checked 2026-11-15)

| Topic | State of the art | TrialBox now | Gain for SCREEN | Risk / evidence needed |
|---|---|---|---|---|
| Engine | vLLM V1 engine; 0.33.0 latest [W] | 0.32.0 | ~0 from the upgrade alone | MC-6 qualify; low value now |
| **CUDA graphs** | Default (`--enforce-eager` defaults to False; eager "disables CUDA graphs and torch.compile") [W: docs.vllm.ai engine_args] | **Eager on every profile**, never measured against graphs (review R-89/A-17, LLM-013) | Largest at small batch; reports range from 1–13 % to 1.3–2.5× [W, mixed quality] ⇒ **~10–40 % on decode here [E]** | MC-6: one serving record + full qualify; memory for graphs is ample on the PRO 6000, tight on the 5090 |
| **Concurrency** | Continuous batching; KV paged | 16 in flight; KV room for ~170 | ~1.5–2× calls/s at 32–48 [E] | MC-6/MC-8; G-3 showed **the candidate list changed with the in-flight count** (1–2 patients at c1/c4/c16) [M] ⇒ a determinism check is needed first |
| **Determinism** | `VLLM_BATCH_INVARIANT=1` (beta): output independent of batch size and order; CC ≥ 8.0; tested model list includes the verifier's family, **not the judge's**; "may impact performance" [W: docs.vllm.ai/en/latest/features/batch_invariance.html] | Not used | Makes the c1 vs c16 differences go away, if it works for both models | Measure on SM120 [U]; MC-6 |
| Prefix caching | Block-hash APC; v0.31 keeps sliding-window KV **out** of prefix caching [W: releases] | Default (not set) [U: whether it is on by default could not be confirmed from the docs page] | Small: the shared prefix (system + criterion text) is ~30–40 % of a ~1k-token prompt; prefill is not the bottleneck; the judge family uses sliding-window layers [U] | Moving `note_question` and `index_date` ahead of `excerpts` (the template sorts keys, `tb_common/llm.py:65`) is MC-1 |
| Quantisation | FP8 / NVFP4 on Blackwell; NVFP4 KV extended to SM12x in 0.32 [W] | Judge NVFP4 (already native FP4); verifier AWQ (int4 weights, 16-bit activations); KV `auto` | FP8 KV: more KV room (not needed on the PRO 6000), small speed gain; a verifier NVFP4 build: speed [E] | MC-2 (new weights) or MC-6 (KV dtype); parity on the gate sets |
| **Speculative decoding** | EAGLE/EAGLE-3, MTP, n-gram (GPU n-gram on Model Runner V2 in 0.32), suffix; "theoretically lossless up to numerical precision", greedy tested equal; best at low QPS [W: docs.vllm.ai speculative_decoding] | Off | The quote is **copied from the prompt**, so n-gram / suffix speculation fits this output well; ~1.2–1.6× per-call latency at low batch [E], less at high batch | MC-6; parity of verdicts and quotes; check interaction with guided JSON [U: docs silent] |
| Structured output | xgrammar or guidance; `auto` default; the `guided_json` field is deprecated in favour of `structured_outputs` / `response_format` [W: docs.vllm.ai structured_outputs] | `response_format` json_schema, backend auto | Pinning: G-4 measured guided on p50 2.24 s / p95 **9.39 s**, off p50 1.79 / p95 3.89 [M]; off gave 64/64 schema failures | Name the backend (xgrammar) and measure its p95 tail; MC-6 |
| SGLang / TensorRT-LLM | Strong alternatives | Not used; the repo chose "keep vLLM, do not add a second stack" (`docs/reviews/2026-11-09-component-review-layer1.md:123`; `05-open-source-reuse.md:217`) | Uncertain on SM120/SM121 and these two models [U] | A full MC-6/MC-7 cycle on every profile: **not worth it now** |
| Multi-LoRA (judge and verifier on one base) | Supported in vLLM | Two different bases | Saves ~9 GB and one server | **Breaks D-478's `pair` basis** ("two different models agreed"; `pin` refuses a pair that is one build, MC-5). **Do not.** |
| Embedder on GPU | vLLM pooling runner (`/v1/embeddings`, `/rerank`) [W: docs.vllm.ai pooling_models]; TEI 1.9 has experimental SM120 and SM121 images [W: TEI README] | CPU fp32 | After D-900/D-910 the S2b load is small on TCGA-like data; it matters for daily-note sites | Vectors change ⇒ D-429 re-pin, D-449 parity, threshold refit; lift the overlay test |
| Sleep / swap (5090) | `--enable-sleep-mode` levels 1/2 | Level 1, swap ~0.3–3.7 s [M] | Fine; the waste is in `two_phase` re-running S2/S2b per round | Product code (memoise across rounds; D-900 helps) |

### 3.3 Serving changes, ranked by gain ÷ risk

Every change below except S1 is a model change under `docs/validation/model-change-protocol.md`:
MC-6 (engine/flags), MC-1 (prompt), MC-2 (weights). Each needs:
- pinned weights;
- a serving record (`tools/serving_config.py measured`);
- a full qualify with its **determinism step (0 cache hits)**;
- the canary;
- parity of the candidate list on the G1 sets;
- a D-number.

| Rank | Change | Expected gain on the job | Risk | Evidence needed |
|---|---|---|---|---|
| S1 | **Re-measure PoC-1 at HEAD with D-910 merged** (no model change) | 1,275 → ~250–320 s [E] | None | Same 500×1 job; stage log `not_embedded`; identical candidate list |
| S2 | Concurrency 16 → 32 (then 48), same card | judge phase −30–50 % [E] | Medium: list drift seen across in-flight counts [M] | G-3 curve at 16/32/48; list identity; p95 |
| S3 | Drop `--enforce-eager` on the PRO 6000 | −10–40 % decode time [E] | Low–medium (start time, memory) | Serving record + qualify (A-17 already asks for it) |
| S4 | Name the structured-output backend; measure the p95 tail | removes the 9.4 s p95 tail [M→E] | Low | G-4 rerun per backend |
| S5 | Batch-invariant mode, if S2 shows drift | determinism, not speed | Medium (beta; the judge family is untested) | c1 = c16 = c32 lists identical |
| S6 | n-gram / suffix speculative decoding | −15–35 % per-call latency [E] | Medium | Verdict, quote and span (CAS-16) identical on the gate sets |
| S7 | Embedder on the GPU (vLLM pooling) | big only where S2b still runs | High (refit) | D-429/D-449 parity, threshold refit |

## Ranked action list (at most 12)

Gains are on the measured job (500 × 1, 1,275 s) unless stated.

| # | What to do | Expected gain | Cost | Risk | Owner decision? |
|---|---|---|---|---|---|
| 1 | Merge the in-progress D-910 (skip S2b when the window fits) and **re-run PoC-1 at HEAD** (D-900 already in); record stage times | 1,275 s → **~250–320 s** (≈4–5×) [E] | S, ~1 GPU-hour (US$2.74–4.50) | Low: the prompt is byte-identical by construction | No |
| 2 | Measure concurrency 16/32/48 with list identity and p95 (G-3 extension); fix the drift seen at c1/c4/c16 first | judge phase 225 s → ~120–150 s [E] | S | Medium (determinism) | No for the measurement; **yes** for a new serving record (MC-6, D-number) |
| 3 | Measure and drop `--enforce-eager` on the PRO 6000 (review A-17 / R-89) | −10–40 % decode [E] | S | Low–medium | **Yes** (MC-6) |
| 4 | Port the D-657 negation rules plus a section/heading tagger into S2 as **ConText-style hit labels** (ja/zh/en), used to (a) rank evidence and (b) **veto** a pair's "fail" whose only evidence is negated, family or hypothetical (widen to unknown) | Fewer wrong blocks (today 1/250) [E]; calls −0–10 % [E] | M | Low: it can only widen | No for the veto (allowed by D-478); **yes** if it is ever used to skip calls |
| 5 | Build the persistent judged-pair cache (CAS-5) and fix the in-run key (text sha + excerpt hash; never store refusals) | Re-runs: up to −100 % of ~1,010 calls (CAS-7 > 80 % target) | M | Medium (provenance, audit bypass) | **Yes** (new schema, D-number) |
| 6 | Value extraction from note text (TNM / stage / ECOG / HER2 / labs with `labvalue` / `labunit`; medications → ATC/YJ/NHI) written as **proposed facts** with offsets; coordinators confirm; confirmed facts move the criterion to S1 next time | Later runs: those criteria leave the LLM entirely [E] | M–L | Low under D-131 (widen only) | No (fits D-131/135) |
| 7 | **O-1:** decide whether a qualified deterministic extractor may *decide* templated value criteria (`rule` basis, per-language precision ≥ the pair's on labelled data) | −30–60 % of value-type pairs [E] | L (labelled sets, qualify) | High if precision is not proven | **Yes** (changes D-478) |
| 8 | Replace the 31-entry S2 table with ValueSet-anchored synonyms (the existing ja/zh CSVs, MANBYO/JMED-DICT after a licence check, jieba / Sudachi.rs tokens) | Better routing and evidence; CAS-13 absence certification becomes possible | M | Low (routing only) | Licence sign-off: **yes** (MANBYO [U], no GPL) |
| 9 | Name the structured-output backend and measure its p95; then trial n-gram / suffix speculative decoding | p95 tail 9.4 s → ~4 s [M→E]; −15–35 % latency [E] | S each | Medium | **Yes** (MC-6) |
| 10 | Spark: run the unmeasured `gb10-profile.yaml` decision gate with marlin MoE, graphs and 16+ in flight before selling it; expect ~1–3k patients/h | Sets a real Spark figure | S–M (one Spark; US$4,699–6,950 [W/U]) | Medium (driver hold, SM121 kernels) | **Yes** (owner decision 4: measure only when a site orders) |
| 11 | 5090: raise max-num-seqs 4 → 16 within its KV, memoise S2/S2b across `two_phase` rounds, measure on a physical card | ~750 → ~300–350 s [E] | S–M | Medium (32 GB, 8k context ⇒ more unknowns) | **Yes** (MC-7; consider dropping the tier on price) |
| 12 | Keep vLLM; no SGLang/TRT-LLM switch; no LoRA pair on one base; move the embedder to the GPU only if daily-note sites show S2b still costs minutes after #1 | avoids churn | — | — | No (record as a note) |

**Bottom line.**
- The measured 1,275 s was **75 % CPU embedding that could not change the prompt**. It was not the GPU and not the
  LLM.
- HEAD plus the in-progress D-910 should give ~4–5× on the same RTX PRO 6000. Concurrency and CUDA graphs add another
  ~1.5–2×. Both are model changes under MC-6.
- Classical NLP is mostly missing on the note side. Under D-131/D-478 it can route, rank, veto and propose, and it can
  remove calls on re-runs (cache, confirmed facts). Removing calls within a run beyond ~10 % needs owner decision O-1.
- The PRO 6000 is the right box. The Spark is bandwidth-bound at 273 GB/s (~4–6× slower than the PRO 6000) [E/W].
  The 5090 is capacity-bound at 32 GB.
