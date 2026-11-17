# D-989 Provenance on every model output: each answer names its model, prompt, inputs, time and confirmer, and one query finds every record a version touched

- **Task:** the owner's ruling D-1037 (2026-11-16, #639; `OWNER-RULINGS-2026-11-16.md`, #897). Every model-derived answer must carry its provenance: the judge's, the verifier's, the extraction's and the pre-fill's. Provenance means which model and prompt version produced it, which inputs (their hashes), when, and which person confirmed it. One query must answer "which records did model or prompt version X influence" in under a minute. It must build on the audit chain and the D-908 judged-pair store's key, not on a new store. The HL7 "AI Transparency on FHIR" guide is a reference to read, not a dependency.

  **Date:** 2026-11-16. **Status:** reserved; this is a design, and the build comes after the P1b safety and compiler cards.

## What exists today (origin/master 9d5853f)

- **Every model call is already recorded.** `LlmResult` carries prompt_id, prompt_version, prompt_sha, the served model, build_sha, input_sha and output_sha (`tb_common/llm.py`). Each call writes `llm.call`, and the gateway writes `llm.gateway.call` with call_id, prompt_sha, model_sha and build_id (`gateway/core.py`). The chain's `ts` is the time.
- **The records do not point back to those calls:**
  - **Judge and verifier:** the cascade's evidence keeps call_id, build_sha and prompt (`engine.py`), but drops prompt_sha. On the SCREEN path, `build_sha` is filled with the model's name (`screen_cascade.py`). The candidate list's per-criterion evidence has no provenance at all; only the list-level `judging.judge_model` and `judging.verifier_model` exist.
  - **Extraction:** `ir_extract`'s provenance is thrown away; only `.criteria` is kept (`criteria_compiler/service.py`). The IR's `review` holds `{status, by, at, comment}`.
  - **Pre-fill:** an EDC draft's version is `{snapshot}|crf_prefill_vN`, with no model, prompt sha or build (`edc/prefill.py`).
- **Confirmations exist but name no call:** `pi_marks`, `excluded_review`, a ruleset's `approved_by/at`, and an EDC draft's `decided_by/at` with `decision`.
- **The chain has no index.** The console's audit browser scans day files, and the journal has only its `seq` key. So "every record of prompt X" is a scan of every event.

## Decision

**1. One provenance block, carried by reference.** A record that holds a model-derived answer carries `prov`, a list of call ids, never a copy of the details.
- A call id resolves to its `llm.call` and `llm.gateway.call` events in the chain. Those events already hold model, build, prompt id, version and sha, the input and output hashes, and the time.
- This card adds `build_sha` to `llm.call`; it is missing today.
- An answer reused from the judged-pair store (D-908) names the call that first produced it. The store's row gains that `call_id`, and the key already pins prompt sha, build sha, excerpt-set hash and criterion, so the reused answer's provenance is the original call's, exactly.

**2. Each output gets its pointer, and the gaps are closed:**
- **Judge and verifier:** the cascade's evidence keeps `prompt_sha`, and SCREEN passes the real `build_sha`. The candidate list's per-criterion evidence gains `prov` (the call ids of the judge and, where it ran, the verifier). This is a schema change to `candidate_list.schema.json`, and the models are regenerated.
- **Extraction:** each extracted criterion's IR gains `provenance: {calls: [call_id...]}` (the part's call, or the halves' calls, D-981). A person's later edit keeps the field and adds the edit to `review`, so the field always says where the text came from.
- **Pre-fill:** each EDC draft field from a model gains `prov`. Mapped, non-model fields carry none, which is itself the answer "no model".

**3. Who confirmed it.** Every existing confirmation writes one audit event `ai.confirmed`, `{record_kind, record_ref, calls, by, decision}`. The confirmations are: a PI mark or excluded review on a patient with model evidence, a ruleset's approval of extracted criteria, and an EDC draft's decision.
- `decision` is one of confirmed, changed or rejected.
- A model answer nobody confirmed is reported as unconfirmed, never inferred as confirmed.

**4. The query: an index derived from the chain, not a new store.** Two kinds of event feed it:
- the `llm.call` events;
- a new `ai.used` event, `{call_id, record_kind, record_ref}`, written where a model answer becomes part of a record: a candidate-list verdict, an IR criterion, an EDC draft field, a judged-pair reuse.

When the audit drain copies these events into the chain, it also writes two append-only tables:

| Table | Columns | Indexes |
|---|---|---|
| `provenance.model_calls` | call_id, model, build_sha, prompt_id, prompt_version, prompt_sha, at | build_sha, prompt_sha, (prompt_id, prompt_version), model |
| `provenance.model_uses` | call_id, record_kind, record_ref, at | call_id |

Properties:
- "Which records did X influence" is one indexed join: milliseconds at tens of millions of rows, well under the minute. The console's audit page gains this as a search, steward and admin only, because the answer names patients.
- The tables are rebuildable. `tools.trialbox provenance --rebuild` rebuilds them from the chain, and `--check` diffs them against it (the doctor runs the check). The chain stays the one source of truth: if the index and the chain disagree, the chain wins and the doctor fails.
- A `record_ref` names the record as the console and the erasure registry already do: (ruleset, pid, job, crit), (ruleset, version, crit), (draft id, field). The patient is named only by the pseudonym the chain already uses, never a chart number or free text: the chain is not erased.

**5. Erasure.** On opt-out, `provenance.model_uses` rows that name the patient are deleted, following the erasure registry's rule for the journal. The chain is append-only and keeps its events, as every other audit event does today. The judged-pair rows are already deleted on opt-out (D-908).

**6. Export.** Mapping `prov` to FHIR (Provenance with an AI device, per the HL7 AI Transparency on FHIR guide) is a later export. The fields above are chosen so the mapping is direct (agent = the model build, entity = the input hashes, recorded = the time, the confirmer as a second agent). Nothing depends on the guide.

## The integrator's reading (2026-11-16, #639): accepted as designed

1. The search is on the console's audit page, for steward and admin, and on the CLI.
2. An S1 answer from SQL alone carries an explicit empty `prov`: "no model" is stated, not inferred from absence.

One condition, part of the decision:

- **Pseudonyms only.** Every `record_ref` written to the chain (`ai.used`, `ai.confirmed`) names a patient only by the pseudonym the chain already uses, never a chart number or free text, because the chain is not erased.

**Build order:**
1. The gap-closing: `prompt_sha` in the cascade's evidence, the real `build_sha` on SCREEN, `build_sha` on `llm.call`, the extraction's and the pre-fill's pointers.
2. Then the index (`provenance.model_calls`, `provenance.model_uses`, rebuild and check) and the search.

## Step 1 as built (2026-11-16)

- **Every answer names its call.** `LlmResult` gains `call_id`, and the `llm.call` event records it beside the new
  `build_sha`. Through the gateway the id is the gateway's own (`tb.call_id`, the id of its `llm.gateway.call`). A
  direct call (DEV only: PRODUCTION refuses a model client without the gateway) has no gateway record, so its id is
  `direct-<first 16 hex of the output sha>`. It is derived from the answer, so a re-run's records stay the same.
- **Judge and verifier:** the cascade's evidence keeps `prompt_sha`. SCREEN's reply carries the real `build_sha`
  (it was the model's name) and the real call id (it was a prefix of the answer's hash). A judged-pair row written
  before this card has no call id; its reuse keeps the hash prefix, as before, which no `llm.call` names.
- **Extraction:** IR 1.3.0 adds `provenance: {calls: [...]}` (`CriterionProvenance`). Each extracted criterion
  names its part's call, the retry's call for a line asked again, or its half's call for a part asked in halves
  (D-981). A line left to a person has no field: no model wrote it. An approved criterion reused by an incremental
  compile keeps its own field. The v3 IR carries the same list (`Provenance.calls`), and the v1 to v3 round trip
  stays lossless.
- **Not in this step:**
  - **The pre-fill pointer** is in `services/edc` (lane E). It is handed over through the integrator: each model
    draft field takes `prov: [result.call_id]`.
  - **The concept-map calls** (`concept_map`), which choose a criterion's codes, are not yet in the criterion's
    `calls`. They come with the index, where `ai.used` names them per value set.

## Step 2a as built (2026-11-17): the candidate list's verdicts name their calls

- **`criterion_verdict.prov`** (candidate list 1.5.0): the call ids the answer rests on. A pair's answer names the
  judge's call and the verifier's, also behind an "unknown" the two disagreed on (both answers made it). A reused
  judged pair names the call it first came from (the stored `LlmResult` keeps its `call_id`). A verifier that did not
  answer adds no call.
- **"No model" is stated:** a coded answer (S1's SQL), a person's check and a criterion nobody evaluated carry
  `prov: []`. Absent means a row stored before the field.
- **The verifier's call is no longer lost:** the note judge's `NoteResult` and the cascade's `JudgeReply` carry every
  call of the pair (`calls`), and the cascade's evidence keeps them (`calls` beside `call_id`). An outcome stored
  before this step still names its `call_id`, which the verdict reads.
- **Next (step 2b, 2c):** the `ai.used` and `ai.confirmed` events at the write points, then the index tables, their
  rebuild and check, and the search. The drain writes the index, so its database role needs INSERT on the two tables;
  the grant is in the role script (`deploy/docker/db-init/30-service-roles.sh`, lane D) and goes over through the
  integrator with that card.

## Step 2b as built (2026-11-17): the two events

- **`tb_common.provenance`** writes them; the `ai` family joins the families every role that hosts a model call may
  send through the journal (`audit_writer._SHARED`, and the compiler's own list).
  - `ai.used {record_kind, record_ref, calls}`: one event per record with its calls listed (the index writes a row per
    call); nothing for a record no model answered, whose `prov: []` already says so.
  - `ai.confirmed {record_kind, record_ref, calls, by, decision}`, `decision` one of confirmed, changed, rejected.
  - `record_ref` takes only the registry's parts (ruleset, version, job, pid, crit, valueset, draft, field), each a
    short token (letters, digits, `_ . : @ -`): free text or a space is refused, and a patient is a pseudonym.
- **Written today:**
  - the compiler: `ai.used` for each criterion a model extracted (`criterion`, ruleset, version, crit), and
    `ai.confirmed` for each decision the review sheet sends on one (approve: confirmed, edit: changed, reject:
    rejected), when the sheet arrives;
  - SCREEN and MICROBATCH: `ai.used` for each verdict a model answered (`verdict`, ruleset, version, job, pid,
    crit); MICROBATCH for the rows it read on the job, a carried row having been recorded when it was read.
- **Handed over (through the integrator), with the helper to call:** the PI mark and the excluded review on a patient
  with model evidence (`ai.confirmed`, `verdict`; the console), and the EDC draft field and its decision (`ai.used`
  and `ai.confirmed`, `edc_field`; lane E).
- **Next (step 2c):** the index tables from these events and `llm.call`, their rebuild and check, and the search.

## Step 2c as built (2026-11-17): the index, its check and the search

- **`tb_common.provenance_index`:** `INDEX_SQL` creates `provenance.model_calls` (from `llm.call`: call id, model,
  build, prompt id, version and sha) and `provenance.model_uses` (from `ai.used` and `ai.confirmed`: the call, the
  record's kind and reference, the pseudonym when the record names one, the event, and a confirmation's decision and
  person). Each row keeps its chain line's hash, so a line written twice is one row and the check is line by line.
- **The drain** writes a record's rows right after its chain line, only when the tables are installed; a failed
  index write is logged and never stops the drain (the chain is the record).
- **`trialbox provenance --check | --rebuild | --search`:** the search is one join by model, build, prompt sha, or
  prompt id and version. The doctor's `provenance_index` check fails when the index and the chain differ (the
  chain wins: rebuild), warns when the tables are not installed, and says NOT CHECKED with no database.
- **Erasure (point 5):** `provenance_index.erase` deletes a patient's use rows; a rebuild leaves opted-out
  patients out, and the check does not report them missing. The chain keeps its events (D-394). The opt-out worker
  calls it once the role script grants its role DELETE: until then the registry's `outside:provenance_index` entry is
  on the erasure owed list (card D-989).
- **Schema:** the tables live in a schema of their own, `provenance`, not the journal's `audit` (only
  `audit.append` writes there), owned by `audit_writer` like the journal.
- **Lane D (through the integrator):** the role script runs `INDEX_SQL` beside `JOURNAL_SQL` and grants the drain's
  role INSERT and SELECT, the console's and the orchestrator's roles SELECT, and the opt-out worker's role DELETE
  on `provenance.model_uses` (and USAGE on the schema). Until then the drain writes no index and the doctor warns.
- **The console's search page is lane C2's** (the integrator's ruling): it calls `provenance_index.search(con, *, model,
  build_sha, prompt_sha, prompt_id, prompt_version, limit)`; the CLI is built here. Still to come: the concept-map
  calls per value set.
