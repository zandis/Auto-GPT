# D-694 A source that changed since the decision holds the value

- **Task:** NEW-EDC-4 (deep-review finding EDC-004, **High**: new source data after a confirmation is never shown)
- **PR:** this branch (`agent/NEW-EDC-4-source-changed`), cut from NEW-EDC-8b (#609): the send's results change
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-160 (a value always has a citation), D-281 (signed values are locked), D-684 (one snapshot per
  draft run), T-115 (what a value was built under)

## Context

A draft run skipped every item a person had already confirmed or edited. When the source changed afterwards (a late
lab correction, 72.5 kg became 82.5 kg), the review page still said "confirmed 72.5"; it was signed and sent. The
signature says "I compared each value with the source cited", and nobody was told the source had changed. Review
case 1d; shown by tests before the change.

## Decision

1. **Each draft run reads the source of every item, decided or not.** For a decided item it compares what it read
   with the source the decision was made against: the drafted value and the row it came from (table, row, day,
   quote; not the snapshot, so the same row and value read on another night is the same source; not the
   citation's kind, so a site fact confirmed since is the same row). That is the source drafted then, or the one
   a person last kept or changed the value under. A run that could not read the source (no model; notes past
   what one call takes) marks nothing.
2. **When it differs, the decided value is marked "source changed since"**, with what the source says now and its
   citation, and a `source_changed` line in the decisions (the old and the new value). The decision itself is not
   changed; the same change read again marks nothing new.
3. **A marked value is held**: it cannot be signed (`edc.source_changed`, naming the items); a signed one is not
   sent (the send lists it, `source_changed`, with a ledger line; an opted-out patient's says `opted_out`), not
   offered on the copy-assist sheet (a send by hand), and the ODM export waits (`edc.source_changed`, audited: a
   file a person can import into REDCap, and never a silent gap, E-22).
4. **A person answers the mark**: **keep** the value with a reason (a `keep` decision; for a signed value the
   password again, as for any change of a signed value, audited `unlocked`; the signature stays, the value is
   unchanged), or **change** it (an edit that names its own source: the machine's citation is of the source before
   it changed) or withdraw it. A keep names the mark the person saw (its id); a mark made since refuses it
   (`edc.mark_changed`). The source answered becomes the one the next run compares with.
5. The review page shows the mark with what the source says now and a keep form; the send pages count it; the
   trail names `source_changed` and `keep` (three languages; lane C2's files).
6. Database: `edc` version 6 adds two columns to `draft` (`source_changed`, `source_seen`), pinned in
   `tests/unit/test_migrations.py`.

## Not in this card

- A value imported from an outside ODM file (D-435) is not re-read; only draft runs from the box's record compare.
- A source that changes back to the one decided keeps the mark until a person answers it.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| A marked value still reached the copy-assist sheet and the ODM export | high | fixed, test first (point 3) |
| A run with no model, or notes past the window, marked every decided note value | medium | fixed, test first (point 1) |
| A keep answered a mark made after the page was shown | medium | fixed, test first: the keep names the mark's id |
| Confirming a site fact changed the citation's kind and marked the value | low-medium | fixed, test first: kind is not compared |
| A new large note pushing the cited note out of the window | low | covered by "too long" marking nothing |
| A keep of a signed value not audited `unlocked` | low | fixed, test first |
| An edit back to the drafted value reused the old machine citation and cleared the mark | low | fixed, test first |
| An opted-out patient's marked value listed as `source_changed` | low | fixed, test first |

## Evidence

`tests/unit/test_edc_source_changed.py`: case 1d (marked, held from the send, the line in the trail); an unsigned
value cannot be signed; keep needs a reason and, signed, the password; keep only for a marked value; a change clears
the mark and the next change marks again; the same source on every run marks nothing; a new snapshot of the same row
and value is not a change; the review page and the three languages; the review's seven cases. The first eight failed before the change;
the review's failed before its fixes.
