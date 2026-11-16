# D-989 Provenance on every model output: each answer names its model, prompt, inputs, time and confirmer, and one query finds every record a version touched

- **Task:** the owner's ruling of 2026-11-16, which the integrator calls D-537 (#639). Every model-derived answer must carry its provenance: the judge's, the verifier's, the extraction's and the pre-fill's. Provenance means which model and prompt version produced it, which inputs (their hashes), when, and which person confirmed it. One query must answer "which records did model or prompt version X influence" in under a minute. It must build on the audit chain and the D-908 judged-pair store's key, not on a new store. The HL7 "AI Transparency on FHIR" guide is a reference to read, not a dependency.

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
| `audit.model_calls` | call_id, model, build_sha, prompt_id, prompt_version, prompt_sha, at | build_sha, prompt_sha, (prompt_id, prompt_version), model |
| `audit.model_uses` | call_id, record_kind, record_ref, at | call_id |

Properties:
- "Which records did X influence" is one indexed join: milliseconds at tens of millions of rows, well under the minute. The console's audit page gains this as a search, steward and admin only, because the answer names patients.
- The tables are rebuildable. `tools.trialbox provenance --rebuild` rebuilds them from the chain, and `--check` diffs them against it (the doctor runs the check). The chain stays the one source of truth: if the index and the chain disagree, the chain wins and the doctor fails.
- A `record_ref` names the record as the console and the erasure registry already do: (ruleset, pid, job, crit), (ruleset, version, crit), (draft id, field).

**5. Erasure.** On opt-out, `audit.model_uses` rows that name the patient are deleted, following the erasure registry's rule for the journal. The chain is append-only and keeps its events, as every other audit event does today. The judged-pair rows are already deleted on opt-out (D-908).

**6. Export.** Mapping `prov` to FHIR (Provenance with an AI device, per the HL7 AI Transparency on FHIR guide) is a later export. The fields above are chosen so the mapping is direct (agent = the model build, entity = the input hashes, recorded = the time, the confirmer as a second agent). Nothing depends on the guide.

## Open for the integrator

1. Whether the confirmer search belongs on the console audit page (steward and admin), or only on the CLI.
2. Whether S1's SQL-only answers, which use no model, should say "no model" explicitly in the candidate list (proposed: an empty `prov`).
