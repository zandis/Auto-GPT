# D-857 Every refusal of the EDC service is audited, the early ones too

- **Task:** EDC-019 (deep review 2026-11-12, Medium, E-20; wave 6, unfrozen by D-1027)
- **PR:** this branch (`agent/EDC-019-early-refusals-audited`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** SEC-7 (every refusal audited), D-581

## Decision

1. Each entry point of `edc.service.EdcService` (the switch, the re-entry record, the dictionary read, the map, the
   drafts, a decision, a signature, the send, the reconcile, the preview, the erase of hidden values, the ODM export
   and import) is wrapped by `audits_refusals(<its audit event>)`: a refusal (`EdcError`) that the code raising it did
   not audit is audited there, with `refused` and its code, under the entry point's event. Seven early refusals left no
   line before (a REDCap error or an empty project on the dictionary read, a target without a field, a visit date
   that is not a date or in the future, no map, REDCap down on a preview).
2. A refusal the code already audited, with its own detail, is not written twice: the service remembers, per thread,
   the code of the refusal it last audited.
3. Class B (the prefill path): no change to who sees patient data, so no adversarial review in the build phase
   (D-511).
