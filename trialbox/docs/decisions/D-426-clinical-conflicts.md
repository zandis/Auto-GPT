# D-426 Clinical conflicts: kept open when a source goes silent; the steward's conflicts page; the study page renamed

- **Task:** T-201 (`docs/plan/28-master-plan-v6.md` §6.2.5, wave 2; as TB-ASSESS-01 T-201)
- **PR:** this branch (`agent/T-201-conflicts`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** DATA-011 (withdrawal on silence; no page for the steward), FIT-018 (two pages sharing one name), the
  conflicts half of CR-061 in part (see Open)
- **Builds on:** D-130 (unknown never excludes), D-144 and D-151 (`tb_conflict`; the lake reads unknown while open),
  D-380 (the steward's rights), owner decision of 2026-11-09 (sheet against feed is a conflict; steward or PI picks)

## Decision

1. **Withdrawal.** The loader withdraws a recorded conflict only when two or more sources give the item and agree.
   A source that sends nothing for the item (a feed that lacks the patient, an empty patient file, a deleted sheet
   row) withdraws nothing: the open conflict stays open and the item stays unknown; a resolved one keeps its
   resolution. Before, the remaining value stood alone (DATA-011's trace: a site-typed birth date became the truth).
2. **The steward's page.** `/data/conflicts` (module `console.conflicts_page`, strings `i18n_conflicts`, store
   functions `omop.conflicts`) lists open conflicts (`?all=1`: every state) with the pseudonym, the item, each
   source's value and source, and when it was found. The steward keeps one claimed value or keeps the item unknown,
   with a reason; a value no source gave is refused (a resolution chooses, it does not type a new fact). The row keeps
   who, when, why and the authority `steward`; the console writes `console.conflict_resolved`.
3. **Who.** One new matrix action `conflicts.resolve`: the steward only. Every other role gets 403 and
   `console.denied`. The PI's own-study view waits until a conflict can be tied to a study (Open).
4. **Names.** The study page `/studies/<study>/conflicts` (TrialBox against REDCap trial values) is titled
   "Trial-record differences" (ja 試験記録の相違, zh-TW 試驗紀錄差異); "Clinical conflicts" (臨床データの矛盾,
   臨床資料矛盾) is the clinical page. Its URL is unchanged.

## Open

- The kinds beyond `source_vs_source` on demographics (sheet against feed for diagnoses and labs; note against code;
  annotation against record), and the `conflict` reason in the engines with FEAS and readiness counts.
- The PI's own-study view and resolution (`pi_clinical_judgement`): `tb_conflict` has no study; a study's patient
  set must be joined first.
- A resolution as a `tb_record_event` row (the event table needs a record key; a conflict has none).
