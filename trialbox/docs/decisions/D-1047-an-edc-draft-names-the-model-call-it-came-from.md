# D-1047 An EDC draft names the model call it came from

- **Task:** E-PROV-1 (D-989's pre-fill pointer, handed to lane E by the integrator after lane A2's step 1, #946)
- **PR:** this branch (`agent/E-PROV-1-edc-draft-prov`)
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** D-989 (the owner's ruling D-1037), D-160, D-694

## Decision

1. **A draft carries `prov`, a list of call ids.**
   - A draft decided by the note drafter's answer takes `prov: [call_id]`. The id is the gateway's call id from the
     answer's `LlmResult.call_id` (D-989 step 1).
   - This holds for an unknown too: when the model answered but its quote was not in the note, or the note said
     no, that answer still decided the draft, so the draft names the call.
   - A draft read from the record (patient, observation, condition, medication), a field that is not mapped, and a
     note field with no model all carry an explicit `[]`. The empty list says "no model"; it is not left out.
   - An answer that names no call id gets `[]`. No id is ever made up.
2. **The note drafter returns the call id.** `NoteDrafter` now returns `(answer, version, call_id)`.
   `gateway_drafter` reads `call_id` from the gateway's result, or `""` when the result has none. It is the only
   drafter in the code.
3. **The edc store keeps it: version 8 adds `draft.prov`**, a JSON list. A row written before version 8, or a
   value proposed from an ODM file (D-435), has NULL there and is read as `[]`. The drafts the service returns,
   and the drafts API, carry the list.
4. **The signature does not cover `prov`.** `draft_sha` is unchanged. A signature covers the value, its subject,
   its citation and what it was built under; the pointer is where the value came from, kept beside it. A signed
   value keeps the same hash it had before this version.

## Not in this card

- The `ai.used` and `ai.confirmed` events, and the `audit.model_uses` index, come with D-989's step 2.
- When they come, a draft's decision becomes an `ai.confirmed` event that names these calls.
