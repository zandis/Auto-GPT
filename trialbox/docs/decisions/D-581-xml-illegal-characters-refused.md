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

1. **One rule, one place.** `datacore.forms.problem` refuses a value that holds a character outside XML 1.0's `Char`
   (allowed: tab, line feed, carriage return, U+0020 to U+D7FF, U+E000 to U+FFFD, U+10000 to U+10FFFF), with the
   code `chars`. Every way a value enters goes through it: a person's entry in the data core, the pre-fill's draft,
   confirm and edit, the read back from REDCap, the ODM import.
2. **A value is never altered to make it fit.** It is refused and the person corrects it. A drafted value with such a
   character is `unknown` (`invalid`), as any other value that does not fit its field.
3. **The writers do not write a broken file.** Both ODM writers check the text they are about to write. A stored
   value or a signed text with such a character (a row from before this rule) stops the export with an error that
   names the item, never its value. Text that is not a value and not under a signature (a citation's quote, a label)
   has the character replaced by U+FFFD, the replacement character, which a reader sees.

## Consequences

- A CRC who pastes a note line with a form feed is told so at entry, in en, ja and zh-TW.
- No box holds real data yet, so no stored value needs repair; rule 3 is the guard if one ever does.
