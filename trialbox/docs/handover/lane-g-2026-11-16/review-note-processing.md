# Note preprocessing, embedding and per-patient reuse: review for the integrator

Repo `trialbox`, branch `claude/lane-g-box-accuracy`, HEAD d44e3978a. This was a read-only review. None of the files
below changed between the measured commit 1157c9bf and HEAD (`git diff --stat` is empty), so every line number below
is also the code that ran on the box.

## 0. The pipeline as it runs in SCREEN (file:line)

| Step | What happens | Where |
|---|---|---|
| Ingest (lake rebuild) | Notes go into the lake `document` table. Each note is cut into 500-character windows with 100-character overlap (not sentence-aware). The rebuild embeds every new window into `embed_cache.duckdb (sha, model, FLOAT[1024])`, which is content-addressed: only windows whose hash is new get embedded. Only the v1 path reads these vectors (`/chunks/search`). | `lake/textproc.py:32-48`; `lake/store.py:1503-1555` |
| Ingest (vector store) | `vec/` has a sentence-aware chunker (500/100), a PHI mask and a pgvector store: `embedding(sha, model, halfvec)` and `note_chunk`. **No product code calls it.** Its only callers are `tools/vec_parity.py:173` and `tools/backup_drill.py:496`. | `vec/chunker.py:19-21`; `vec/store.py:35-45`; `vec/index.py:83` |
| S0/S1 | Population and compiled SQL. The SCREEN index date is the run date (`index_mode="single"`). | `engine.py:398-400`; `screen_cascade.py:507-528` |
| Note read | `NOTES_SQL` reads every note in the window, 1,000 patients per batch. Each note is split into sentences once, and an NFKC-lowercased copy is kept. | `engine.py:309-313, 644-660, 317-328`; `screen_cascade.py:438` |
| Cleaning | There is none beyond whitespace/NFKC normalisation (`judge.norm`, `judge.py:403`) and the length-keeping PHI mask applied inside the embed service (`embed_service/app.py:51`). Headers, template lines and copy-forward duplicates all reach the embedder and the judge. | |
| Sentence split | Splits on CJK and Latin stops, line breaks and English full stops. **There is no maximum sentence length**: a pathology report line with no punctuation becomes one "sentence" of any length. | `matching/excerpts.py:92-95` |
| S2 lexicon | Substring match of approved terms in each window sentence. A hit sends the pair to S3, with the hit sentences as evidence. | `engine.py:713-794` (hits at 760-770) |
| S2b | For **each zero-hit (patient, criterion) pair**, `screen()` embeds `[query, *every window sentence]` in a single call. The same patient's sentences are therefore embedded again for every zero-hit criterion, and the query again for every patient. Cosine is computed in pure Python. | `engine.py:817-836`; `s2b_semantic.py:84-107` |
| S2b effect in SCREEN | `absence_semantics=False` (`screen_cascade.py:522`), so **every** zero-hit pair with sentences goes to S3 whatever its score (`engine.py:870`). The index-sweep score is held back under the public prior with a real model (`engine.py:838-851`, D-783). The route margin (`engine.py:878`) is never read. The ranking only sets the order in which the excerpt builder offers notes, and the builder **re-sorts what it shows newest-first** (`excerpts.py:323`). So when the whole window fits the budget, the ~16 min of S2b changes nothing in any prompt. Its other uses are the in-run cache key (`sentence_set`) and the stage-log counts. | |
| Embed client | `HttpEmbedder` posts 64 texts per request, and the 1024 floats per text come back as JSON lists. `_Served` stops the job if the model changes. | `embedder.py:192-214`; `screen_cascade.py:155-205` |
| Embed service | One uvicorn worker running a sync `def` endpoint, so FastAPI's thread pool can encode several requests at once. The model is CPU fp32 sentence-transformers with `batch_size=64` and **no `max_seq_length` override**, so the weights' own limit applies (8,192 tokens for this family). torch uses every core per request. There is no lock around the lazy load (`app.py:22-26`). In PRODUCTION (`TB_ENV` unset counts as PRODUCTION, `config.py:308-311`) the model is loaded at import (`app.py:42-43`), so the per-request double load can only happen on a box that runs with TB_ENV≠PRODUCTION. `/healthz` also calls `embedder()` (`app.py:29-32`). The image is CPU-only torch (`deploy/docker/embed.Dockerfile`); `mem_limit ${TB_MEM_EMBED:-4g}` is at `docker-compose.yml:197`. | `embed_service/app.py`; `embedder.py:169-189` |
| Excerpts | One builder (D-479) offers whole notes, the evidence notes first, inside a budget equal to the served context ×SAFETY − fixed prompt − `max_tokens` (taking the smaller of judge and verifier). An evidence note longer than half the budget is clipped around its evidence. Every note not shown in full counts in `left_out` (D-276). | `excerpts.py:282-326`; `evaluate.py:302-319`; `tb_llm/budget.py:65`; `engine.py:672-711` |
| S3/S4 judge | The prompt carries `criterion_text`, `note_question`, `index_date` and the excerpts (date, type, text only). The answer is schema-checked, then the span is checked character for character (CAS-16). The pair goes to the verifier on a decided answer. | `judge.py:241-337, 340-386, 411-435` |
| Two-phase | On swap profiles (`TB_MODEL_SWAP=sleep`, the rtx5090 overlay) `two_phase` calls **the whole `run_cascade` again** in each round, up to `MAX_ROUNDS=3`. The judge's answers are memoised (`MemoClient`, in memory), but S2/S2b and their embeddings are recomputed every round. | `twophase.py:47, 263-266`; `screen_cascade.py:530` |

**What is cached.** (a) Lake chunk vectors, persistent, used by v1 only. (b) The `vec` embedding table, persistent but never filled by product code. (c) `_Run.cache`: an in-memory dict per run, keyed on `[pid, canonical_hash, sentence_set, role, lo, hi]` (`engine.py:367, 1033`). It also stores refusals (`engine.py:1055`, any reply). (d) `MemoClient`: in memory, per job, keyed on the prompt variables (`twophase.py:56-60`). (e) `_JOB_EMBEDDER`: the embedder probe, per job. **Nothing about a patient's notes or verdicts survives the job.**

**Next SCREEN of the same or another trial.** Every step runs again: the notes are re-read and re-split, every zero-hit pair is re-embedded and every routed pair is re-judged. This is the spec's own gap. CAS-5 (`spec/v4/04_architecture_llm_hermes.md:243`) requires a persistent judgement cache, "reused across studies and runs", keyed with prompt@version and model build sha and carrying `origin_call_id`. CAS-6's dirty set (`spec/v4/05_…:278`) is not implemented either; grep finds nothing under `services/` or `libs/`.

**Notes→facts.** The design exists only on paper: `docs/reviews/2026-11-09-design-patient-data-and-roles.md` §2.5 (lines 373-395) describes a NOTE_NLP row plus `tb_fact_provenance` (model, prompt version, confidence, note id, quote offset, trust). The code has `sitesetup.fact` (`sitesetup/store.py:31-37`), which keeps pid, domain, code, value, day, status and quote, but no model, prompt, confidence or offset. It is filled from uploaded charts and mirrored into the lake's `site_fact`. The D-131/D-135 rule (`matching/proposed.py:1-25`) means a proposed fact can only widen an answer to unknown. No code extracts facts from lake notes during SCREEN.

## 1. Chunk, embed, reassemble: done, partly done or missing?

**Partly done, but on the paths SCREEN does not use.** Chunking with embedding at ingest exists twice: in the lake's duckdb cache and in the `vec` store. "Reassemble" also exists: `vec/s2b.py:119` maps chunk scores back onto the cascade's sentences. SCREEN, however, takes the on-the-fly sentence path. It has no length cap, no token-aware split and no reuse, and it runs whether or not its result can change the prompt. The judge side already does the owner's "assemble within a fixed budget" (D-479).

**Where the time goes, about 960 s of the 1,275 s job.** It is all on-the-fly S2b embedding of `query + window sentences` per zero-hit pair. That work is repeated once per criterion for the same sentences (×k, where k is the number of zero-hit note criteria per patient), runs at fp32 on the CPU, and includes long unpunctuated "sentences". The S2b stage is serial and runs before any S3 call, so the GPU sits idle for those 16 min. The ~1,010 judge calls take the remaining ~300 s (median 3.45 s each, about 11 in flight).

**Where the memory goes.** The weights take ~2.3 GB. Each forward pass also builds attention tensors of batch × 16 heads × L² × 4 B per layer (estimate, for this model family). At batch 64 that is ~0.27 GB at L=256, ~1.07 GB at L=512 and ~4.3 GB at L=1024. Long inputs plus the thread pool letting requests overlap explain the death at 4 GB. The 2.76 GiB peak measured at 16 GB was sampled, so it can miss short spikes.

**Fixes, ranked by gain against effort.** Section 3 has the file:line for each.

1. **Skip S2b when the window fits the excerpt budget (SCREEN only).** Compute `Σ note_tokens(window)` first. If it fits, route the pair to S3 with `keep={}` and no embedding, then record `s2b: "not needed: window fits"`. The prompt is byte-identical, because the builder sorts newest-first anyway. Gain: most of the ~960 s on TCGA, where one report per patient is far under a 16k budget. Lane G must measure the share of windows that fit. Effort: small.
2. **Embed each sentence once per run.** Memoise vectors by `(model, sentence_hash)` in `BatchEmbedder` or `screen()`, embed the query once per criterion, and compute cosine as a numpy dot product (the vectors are already normalised). Gain on what is left of S2b: about (k−1)/k, plus template lines that repeat across patients. Also memoise across two-phase rounds (up to 3× on swap profiles).
3. **Harden the embed service.** Set `max_seq_length` to 512 (256 for sentence input). Split longer inputs into token windows, then reassemble by max similarity per sentence; this is the owner's chunk/reassemble step. Batch by tokens, not by count. Allow one encode at a time (a lock or semaphore) and set torch to the container's CPU count. Load once, under a lock, in the lifespan. Gain: bounded memory, so 4 GB becomes safe, and no 33 s single requests. Effort: small. Vectors of inputs ≤ cap are unchanged.
4. **Persistent judgement cache (CAS-5).** See section 2. Gain: a same-day or same-index-date rerun saves up to ~300 s and ~1,010 calls. Across trials it pays only where criterion and prompt text are identical.
5. **Turn on vectors at ingest (vec.s2b).** Wire `vec.index.index_snapshot` into the nightly publish so SCREEN embeds only the query. This is gated on the D-429 refit and the D-449 parity work. Note that the store is `halfvec` (fp16), so stored and on-the-fly similarities are not bit-equal.
6. **Text cleaning.** Exact de-duplication of identical sentences before embedding is safe and free once fix 2 is in. Copy-forward notes (same text hash) can be shown once with all their dids, without counting them as left out. Boilerplate removal (signature, disclaimer and page-header lines from a per-site list) should apply **only to ranking and embedding input, never to the judge text**. CAS-16 checks the quote against the excerpt, and the audit needs offsets into the source note. Gain on the TCGA job is small (one report per patient); it matters for daily-note clinics.
7. **Lower precision or the GPU.** bf16, or ONNX int8, on the CPU should give about 2× on memory and 2-3× on speed (estimate). The vectors change, so this needs a re-pin (D-429), a parity run and a threshold refit. Moving to the GPU next to vLLM means a CUDA image (`embed.Dockerfile` is CPU-only, and `tests/unit/test_embed_review.py:92` forbids cuda in the overlays), a device reservation (deep review R9) and memory taken from the model pair. The gain is large, but this is an owner decision. After fixes 1-3, neither option is needed for the measured job.
8. **Pipelining.** Start S3 on note batch *n* while S2b runs on batch *n+1*, to fill the GPU during S2b. This becomes moot once fix 1 lands.

## 2. Persisting structured results per patient

**Two stores, different trust levels.**

**(A) A judged-pair store: the CAS-5 cache.** It belongs in the trial database as a new schema `judged`, owned like `derived` (D-126) and modelled on `tb_common/derived_store.py`. That module already has the patterns needed: fingerprint, supersede and never update in place, a flag-gated read, and only ever taking a decided answer away (`matching/stored_scores.py`).

- One row per (pid, role, key). The **key** must be the hash of the exact prompt inputs: canonical criterion hash **plus the sha of `criterion_text` and `note_question`**, `index_date`, and the excerpt set (date, type and text sha of each shown note, the clip marks, the mask version). Add the prompt `id@version` and sha (D-300), the model build sha, and the rule version for the response schema. Two traps make this necessary:
  - `canonical_hash` drops free text and reduces the note question to its key (`tb_contracts/criterion_ir.py:642-650`), so two trials with different wording would share a hash.
  - Since D-479 the judge reads the **whole window**, so the spec's sentence-set key would wrongly reuse an answer after a new note arrives. The in-run key at `engine.py:1033` has the same flaw within a run.
- **Value:** verdict, confidence, quote, quote_date, the verified span (did, start, end, sentence_hash), reason, `left_out`, `refused`, tokens, `origin_call_id` (the gateway audit or tracestore id), the snapshot, the job, and the time.
- **Invalidation is by the key, never by a timer.**
  - A new or changed note in the window, a change in the mask, or a change in the lexicon or threshold that changes the excerpts gives a new excerpt hash.
  - A changed criterion or wording gives a new criterion or text hash.
  - A model or prompt change gives a new build or prompt sha.
  - For a terminology release: a ValueSet change already changes the canonical hash. Also add the terminology and lexicon release to the key, because it changes S2 routing.
  - Erasure deletes by pid (`tb_common/erasure.py`, as `vec.store.delete_patient` does).
  - The index date is part of the prompt, so a daily SCREEN at `run_date` misses across days. Reuse across days needs a decision on index-date-free criteria; FEAS at fixed month-ends would hit.
- **Safety:**
  - Never store refusals, schema-invalid answers, outage results or "no judge" results: they must be asked again. Today's in-run cache keeps them.
  - Store each role's answer separately and run `combine()` (`tb_common.pair`, D-118) again on read. A pair basis needs both builds to be pinned now, otherwise the basis is `single`.
  - Store the raw verdict, never a status, and re-apply `decision.answer_of` / `status_of` with the job's `Policy` (D-478, D-477). A cached "not met" therefore excludes only when final (`left_out=0`), from a pair, above the threshold and allowed to block; "needs review never excludes" holds unchanged. Abstentions stay abstentions.
  - The **recall certificate**'s S4 or audit samples (`certificate.py`, SAFE-10..14) must bypass the cache. Otherwise the audit grades the cache against itself.
  - Each patient trace and the D3 outputs record `cached_from: origin_call_id, job` so an auditor reaches the original call.
  - Shadow or eval outputs never write to the store (spec 04:748).
  - The read sits behind an audited flag like `derived.stored_read`.

**(B) Extracted facts: notes→facts.** These go into §2.5's `tb_fact_provenance` and NOTE_NLP. Until that exists, extend `sitesetup.fact` with model build, prompt version, confidence, note did, offset and note text sha, and mirror the result into lake `site_fact` with `basis=proposed`.

- **What they can do:** by D-131/D-135 a proposed fact can **only widen to unknown**, never decide or exclude, until a person confirms it. A confirmed fact then becomes a coded row that S1 decides on the next run. That confirmed path is the durable "no need to fully screen again" for known criteria.
- **What they cannot do:** they cannot stand in for the judge on unconfirmed note criteria.
- **Use for speed:** they can serve as evidence pointers that pick the excerpts (as S2 hits do).
- **Invalidation:** a fact is superseded when its source note's text sha changes, and re-extracted when the model or prompt changes; the old row is kept with `superseded_by`.
- **Conflicts:** a conflict with a coded record follows §2.6 (the coded record stays authoritative).

**Sentence vectors** need no new safety rule. A persistent store keyed by `(sha(norm(sentence)), model)` gives identical vectors, if it is kept in float32 (the lake's duckdb cache format) rather than the vec store's halfvec. It can live behind the lake service (D-378: only the lake reads `vec`) or as a bounded LRU inside the embed service.

## 3. Ranked fix list for the integrator

| # | Fix | file:line | Expected saving on the measured job | Risk | Touches | Owner |
|---|---|---|---|---|---|---|
| 1 | In SCREEN (`absence_semantics=False`), skip S2b embedding when the window fits `budget_of(c)`; route with `keep={}`, `sentence_set`=hash of the window note shas; trace "S2b not needed" | `engine.py:817-836, 870-878` | ~600-900 s of 1,275 s (lane G to confirm the fit share); embed load ~0 | Low: prompt byte-identical (`excerpts.py:323`); stage-log counts change | D-449, D-783, D-781, D-479, CAS-12 | product |
| 2 | Per-run sentence-vector memo `(model, sentence_hash)`; query once per criterion; numpy dot | `s2b_semantic.py:43-58, 84-107`; `engine.py:359` | the rest of S2b ÷k; 2-3× on swap profiles (`twophase.py:263-266`) | Low: same vectors | CAS-15 batch count (`batches` semantics) | product |
| 3 | Embed service: `max_seq_length` cap, token-window split with max-reassemble, token-budget batches, one encode at a time, torch threads = cgroup CPUs, locked lifespan load | `embedder.py:176-189`; `embed_service/app.py:19-26, 46-51`; `docker-compose.yml:197` | No more OOM at 4 GB (peak ≈ weights + ≤1 GB); no 33 s requests | Low for inputs ≤ cap; long inputs score differently | D-429, D-563, ENG-003 | product |
| 4 | Persistent judged-pair store (section 2A), behind a flag; fix the in-run key (add text sha and excerpt hash; drop refusals) | `engine.py:367, 1030-1056`; new schema next to `tb_common/derived_store.py` | Rerun at the same index date: up to ~300 s and ~1,010 calls → ~0; cross-trial only for identical prompts | Medium: provenance, audit bypass, pair rebuild | CAS-5, D-478, D-118, D-300, SAFE-10..14, D-126 | product |
| 5 | Index note vectors at publish (`index_snapshot`), then vec.s2b after the refit | `vec/index.py:131-142`; `screen_cascade.py:120-153` | SCREEN embeds queries only (~1 per pair); ingest takes the cost once | Medium: halfvec parity, refit gate | D-449, D-429, T-203b | product |
| 6 | Excerpt builder: show copy-forward duplicates once (text sha), not left out; ranking-only boilerplate list | `excerpts.py:282-326`; `excerpts.py:92-95` | Small on TCGA; tokens_in down in daily-note sites | Medium: the D-276 left_out rule | D-479, D-276, CAS-16 | product |
| 7 | bf16 or ONNX int8 CPU, or GPU embedder | `embed.Dockerfile`; `embedder.py:180`; `tests/unit/test_embed_review.py:92` | 2-3× S2b speed (est.), about half the memory | High: re-pin, parity, refit | D-429, D-563, R9 | product (owner decision) |
| 8 | Measure: zero-hit pairs, sentences per pair, sentence token lengths (p50/p99/max), unique-sentence share, share of windows that fit the budget, embed RSS at 1 s, rerun hit rate | lane G tooling | Gives numbers for fixes 1-3 | None | none | lane G |
| 9 | Rerun the same job twice once fix 4 lands; record the hit rate against CAS-7's > 80 % target | lane G tooling | Proves fix 4 | None | CAS-5/CAS-7 | lane G |

**Order:** do 1 and 3 first (small changes that remove both the time and the OOM), then 2, then 4. Do 5 and 7 only after the refit decision.
