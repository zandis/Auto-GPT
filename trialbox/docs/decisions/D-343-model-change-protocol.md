# D-343 Model change protocol, N-12 unadjusted, and the record that cites the protocol

- **Task:** T-649b (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-649b-ai-governance`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** REG-006, REG-030, REG-032

## Context

The deep review found three gaps. No text mapped TrialBox to GMLP, Taiwan's AI Basic Act or Japan's AI Guidelines
for Business (REG-006). The N-12 gate result was the audit-adjusted figure, and an AI assistant had checked the
sampled labels behind it, not a clinician (REG-030). Model changes had tools but no single protocol: no list of
foreseen changes, and no test and threshold for each one (REG-032). D-311 removed human sign-off gates, so the
protocol cannot rest on approvals.

## Decision

1. **N-12 gates on the unadjusted figure.** `docs/VALIDATION.md` §3 reports 9.4 % (95 % 7.9–11.2), which fails the
   5 % gate. The adjusted 3.1 % is a note until a clinician repeats the label sample. The `n12` step of
   `tools/qualify.py` accepts only evidence that says `"basis": "unadjusted"`.
2. **Model change protocol.** `docs/validation/model-change-protocol.md` lists the foreseen changes MC-0 to MC-8.
   Each has its automated test and threshold, and the protocol also covers the impact check, rollback and who is
   told. No person signs a change. A new kind of change is a new row, added to the protocol, to
   `tools.qualify.CHANGE_TYPES` and to its test in the same pull request.
3. **The record cites the protocol.** Every qualification record has a required `change_protocol` field: the
   protocol's path, the sha256 of its text and the change id (`--change`, default `MC-0`). The record schema refuses
   a record without it.
4. **AI governance note.** `docs/validation/ai-governance.md` maps TrialBox to GMLP, the Taiwan AI Basic Act and
   Japan's guideline v1.2. It names a control already in the code or in CI for each principle.

## Consequences

- The model gate in `docs/VALIDATION.md` §3 now shows a failing N-12 for the deployed pair. The fixes proposed in
  `eval/trec_ct/AUDIT.md`, a new judge prompt version (MC-1), come under the protocol.
- `tests/unit/test_model_change_protocol.py` holds the protocol against the code: the change ids, the step names and
  the numbers in its threshold table.
- Records written before this decision have no `change_protocol` field and fail the schema. None is committed.
