# D-435 ODM import as proposals; the sponsor's weekly CSV and the sponsor's screening-log columns

- **Task:** T-302d (fourth part of T-302; `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-302d-odm-import-sponsor-readers`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-160 (EDC prefill: drafts, decisions, signatures), D-215 (one character-set detector), D-281 and
  D-391 (signatures), D-368 (what a draft was built under), D-387 (the screening log's columns), D-396 (CDASH IE
  and DS), D-414 (visit names of arms, events and repeating instruments; ODM repeat keys)
- **Closes:** no finding id (the row's "Closes" is empty); TB-ASSESS-01 T-302's "ODM import", "the sponsor weekly
  CSV reader" and "the screening-log layout mapping"

## Context

TrialBox wrote CDISC ODM (D-160, D-396, D-414) but could not read one: a site whose other system exports ODM, or a
sponsor that sends its EDC's ODM back, had the values typed again. The sponsor's weekly subject-status sheet was read
by eye, and the screening log left in TrialBox's own column names, which each sponsor renames.

An ODM file and a sponsor sheet are outside data. ElementTree on an outside document is bandit B314; a waiver needs
the owner. An OID is only a name the sender chose, and two elements can carry the same one.

## Decision

1. **An imported ODM value is a proposal, never a record.** `edc.odm_import` reads the file; `EdcService.import_odm`
   makes each value an open draft (`fate` `open`, state `drafted`) with the file as its citation (`kind` `odm`:
   the file's sha256, its name, the path of the value in it). A person confirms, edits or rejects each one and
   signs, as for a drafted value (D-160). No decision, signature or sent row is written by the import. The switch
   must be on (as for drafting); an opted-out patient's record is refused.
2. **Only the items of the value's own draft are replaced.** A new import supersedes the open or rejected draft of
   the same subject, visit and item only (`EdcStore.add_proposals`); a value a person already confirmed or edited
   keeps its decision and is listed as `decided`; the same value from the same file is listed as `same`.
3. **The subject must be known.** The ODM `SubjectKey` is the record key (the screening number). Its pseudonym is
   the one its drafts were made for, else the lifecycle subject's; a record TrialBox does not know is refused
   (`odm.unknown_subject`). A record key stays bound to one subject (D-162).
4. **Parsed defensively, all or nothing.** The reader takes bytes up to `TB_EDC_ODM_MAX_BYTES` (default 5 MB),
   decodes them with `tb_common.encoding.decode` (D-215), and parses with expat directly: a document type
   declaration, an entity declaration or an external entity reference stops the parse (`odm.dtd`); there is no
   ElementTree parse of the file. Depth, element count and value length are bounded. The file is refused whole,
   with a named reason, when: it is not ODM 1.3 (`odm.not_odm`, `odm.version`); a transaction is not an insert or
   an upsert (`odm.transaction`: TrialBox never deletes from an import); the study OID is not this study's
   (`odm.study`); two definitions or two values carry the same key (`odm.duplicate_oid`, `odm.duplicate_value`:
   an OID is never trusted to be unique); a repeat key is not a positive integer, or a non-repeating form or event
   carries a key other than 1 (`odm.repeat_key`); an item is not in the study's map, is a calculated field, or
   sits on another form than the dictionary's (`odm.unknown_item`, `odm.wrong_form`); a value fails its field's
   own check (`odm.invalid`). Every refusal is audited (`edc.odm_import`, the code and the file's sha256; never a
   value).
5. **Visits use D-414's names.** `Event.<event>` with a `FormRepeatKey` `n` on a form whose `FormDef` says
   `Repeating="Yes"` is the visit `<event>__<form>__<n>`; a `StudyEventRepeatKey` `n` on a repeating
   `StudyEventDef` is `<event>__<n>`. A REDCap checkbox's `field___code` items are read back into the several-choices
   value. So TrialBox's own export (`edc.odm.build`) re-imports equal, an AE on a repeating instrument included.
6. **The sponsor's layout is data.** `datacore.sponsor`: per study one JSON layout, kept in `sponsor_layout`
   (datacore version 8, append-only by code: the newest row is in force, every earlier one is kept; record
   inventory R-10 beside the lifecycle). It names the
   screening log's columns in the sponsor's words and order (`log`: a TrialBox column key, the sponsor's heading,
   optional value words and a date format), and how to read the sponsor's weekly sheet (`weekly`: the subject column,
   the status column, the date column and its format, the reason column, and the sponsor's status words mapped to
   a lifecycle state). A layout naming a column TrialBox does not have, a state not in the lifecycle or an unknown
   date format is refused when saved.
7. **The screening log in the sponsor's columns.** `GET /studies/{rs}/screening-log.xlsx?layout=sponsor` writes the
   same rows as the site's log under the sponsor's headings, in the sponsor's order, with only the columns the
   layout names. The route and its permission question are the log's own (ROLE-017); the chart number is in
   neither.
8. **The weekly sheet proposes lifecycle steps.** `read_weekly` reads the sheet (CSV with a comma, semicolon or
   tab, through the same decoder; at most `TB_SPONSOR_WEEKLY_MAX_BYTES`, default 2 MB); a missing column, an unknown status word, a date that does not
   parse or a subject listed twice with two statuses refuses the sheet whole. `weekly_proposals` compares each
   subject's sponsor status with its state: equal is `same`, a legal next step is a `step` proposal, anything else
   is `held` with the reason (`LifeError.why`), and a subject TrialBox does not know is `unknown`. A step is taken
   only when a person confirms it (`POST /studies/{rs}/sponsor/weekly/confirm`), as a lifecycle step whose source is
   `sponsor_weekly` and whose note names the file's sha256; it is mirrored to the screening log and audited
   (`life.step`). The confirm route reads the sheet again and checks every record it names before it takes any step,
   so a confirmation never rests on a proposal the sheet does not make. Nothing is ever written to the sponsor's EDC.

## Not in this decision

- A console page for the ODM import, the layout and the weekly proposals (the orchestrator routes and the rules are
  here; the EDC pages are T-302c's next).
- ODM `ClinicalData` with `TransactionType="Remove"` or `"Context"`, `AnnotatedData`, `ReferenceData`, and
  `ItemGroupRepeatKey` above 1 (item groups never repeat in TrialBox's export, T-115): refused.
- A weekly sheet as XLSX (the sponsor saves it as CSV); the sheet itself is not kept, only its sha256.
- Reading the datacore's own `cdisc` export back (its IE and DS form is TrialBox's own derivation, not data).
