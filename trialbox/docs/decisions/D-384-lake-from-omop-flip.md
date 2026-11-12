# D-384 The lake from OMOP: both sources in CI, the flip on the box, export as of a time, NOTE_NLP

- **Task:** T-202, lake exported from OMOP: parity in CI, flag flip (`docs/plan/28-master-plan-v6.md` §6.2.5; the
  contract is TB-ASSESS-01 T-202 in `docs/reviews/2026-11-09-assessment-and-tasks.md`)
- **PR:** this branch (`agent/T-202-lake-from-omop`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-060 (second half). T-106 and T-106b closed the first half.
- **Builds on:** D-151 (the OMOP store of record), D-205 (goldens), D-207 (feature flags), D-339 (partitions)

## Context

The OMOP store holds every record, and the lake exported from it equals the flattened lake (T-106, T-106b,
`tools/omop_parity.py`). Three things were missing before the `lake.source` flag could flip. CI built the goldens from
both sources in one job but ran `e2e_simple` on `legacy` only. An older snapshot could not be exported from OMOP
(D-151 refused it). The site's chart facts did not reach NOTE_NLP.

## Decision

1. **Both sources in CI.** The `goldens` and `e2e-simple` jobs of `.github/workflows/trialbox-ci.yml` have a matrix
   `lake_source: [legacy, omop]`. `TB_LAKE_SOURCE` seeds the flag of each run's fresh database. The legacy run keeps
   the job's plain name, which is the required check; the OMOP run is `goldens (omop)` and `e2e-simple (omop)`.
   `e2e_simple` stage 0 checks that the lake recorded the source it was asked for.
2. **The flip.** The flag changes on the acceptance box only through `python -m tools.omop_parity flip <report>
   --actor ops:<name>`. It refuses a report that is not IDENTICAL or that compared nothing. Otherwise it sets
   `lake.source=omop` as an audited flag change whose reason holds the report's sha256. The seed default stays
   `legacy` for new boxes until the flip is proved on the acceptance box. A rebuild reads the flag once at its start
   (D-207), so a running rebuild or SCREEN keeps its source.
3. **Export as of a time.** Migration 6 of the `omop` schema adds `tb_record_event.record_before`: the `tb_record`
   row as it was before each update, restore, tombstone or status change (NULL on an insert). `export_rows(db,
   as_of=...)` winds the store back inside one transaction that is always rolled back, under the loader's lock. It
   restores each changed record and its OMOP row, sets aside records loaded later, puts conflicts back as they stood,
   and derives the person rows again. Nothing is written.
   - The content is that of the time: which records, their values, status, basis and conflicts.
   - An unchanged record's row provenance columns and file position are those of the last night that carried it.
     Keeping them per night would cost one history row per record per night.
   - A time before a change with no record before-image (written before migration 6) is refused.
4. **NOTE and NOTE_NLP from site setup.** A published chart is a `DocumentReference`, and so a NOTE. A fact read from
   a chart carries the extension `urn:trialbox:note-source` (the chart's id and the fact's term). The loader writes
   one NOTE_NLP row per live fact of the site batch whose chart is a live NOTE. The row holds the term, `status=<fact
   status>` in `term_modifiers`, and the chart's day. It is rewritten at every site load. The fact's quote stays in
   site setup, because it is not redacted. The flattener ignores the extension, so the lake does not move.
5. **Publish writes to the CDM.** A site publish rebuilds the lake. With the flag on `omop` that rebuild loads the
   site batch, so the kept facts (coded, confirmed and proposed; never rejected) and the chart notes are in the CDM
   when the publish returns. With the flag on `legacy` the CDM gets them at the next OMOP build.

## Evidence

`tests/unit/test_omop_export_pit.py`:

- two nights; the export as of each night equals that night's flattened lake;
- later decisions do not reach an earlier export; the export writes nothing;
- a naive time and a missing before-image are refused;
- NOTE_NLP from chart facts, and a rejected fact leaves it;
- the flip is refused on a DIFFERENT or empty report, and names the sha256 on an IDENTICAL one;
- a flag flipped during a rebuild takes effect at the next one.

## Open

- The parity report of the acceptance box and the flip itself are steps on that box (`docs/runbook/06-go-live-
  acceptance.md` §6.1). They are not done by this change.
- Per-night provenance of unchanged records in an export as of a time (see 3).
- `lake_meta` does not carry the source yet. `<lake>/source.jsonl` and the audit event are the record.
