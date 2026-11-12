# D-581 A value with a character XML 1.0 does not allow is refused at entry; an ODM file is never written broken

- **Task:** EDC-010 (finding EDC-010 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/10-redcap-edc.md`; plan v7.2 section 5, lane E, wave 0)
- **PR:** this branch (`agent/EDC-010-xml-illegal-characters-refused`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-160 to D-163 (the eCRF pre-fill), D-435 (ODM import), D-396 (the data core's ODM export)

## Context

Text pasted from a hospital note often carries a vertical tab or a form feed. Such a value was accepted, signed and
sent to REDCap, and both ODM writers then wrote a file that no XML reader opens: one value broke the whole study's
export. A NUL raised an uncaught database error.

## Decision

1. **One rule.** A character outside XML 1.0's `Char` (allowed: tab, line feed, carriage return, U+0020 to
   U+D7FF, U+E000 to U+FFFD, U+10000 to U+10FFFF) is refused wherever text enters that an ODM file later carries:
   - a value: `datacore.forms.problem`, code `chars` (a person's entry in the data core, the pre-fill's draft,
     confirm and edit, the ODM import);
   - a value or a record or event key read back from a source such as REDCap: the row or field is refused and
     listed in the sync's result, and the sync goes on;
   - the data core's own door, `DataCore.write` (`DATA-CHARS`), whichever path brought the value;
   - the pre-fill's reason for change and every field of a citation (`edc.chars`);
   - a signature's printed name, role and meaning text (`edc.chars`);
   - the reason typed for a possible deviation (`life.why.chars`).
2. **A value is never altered to make it fit.** It is refused and the person corrects it. A drafted value with such a
   character is `unknown` (`invalid`), as any other value that does not fit its field.
3. **The writers do not write a broken file, and rewrite nothing that is signed or keyed.** Before it builds the
   file, the pre-fill's export checks every text of a signed row (value, reason, citation, record, visit, who
   decided) and of its signature (signer, printed name, role, meaning); the data core's ODM export and its workbook
   check every value and every record and event key. A row from before this rule stops the export with an error
   that names the item or the field, never its text (`edc.odm_chars`, `DATA-CHARS`), and the route answers it as a
   refusal a person reads. Only text that is neither a value, a key nor under a signature (a field's label, a
   choice's label) has the character replaced by U+FFFD, which a reader sees.

## Consequences

- A CRC who pastes a note line with a form feed is told so at entry, in en, ja and zh-TW.
- No box holds real data yet, so no stored value needs repair; rule 3 is the guard if one ever does.
