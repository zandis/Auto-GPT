# D-402 Clinical UX polish: plain banner, short codes, date format and the western calendar

- **Task:** T-685 (wave 3 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; "Clinical UX polish (Lows)")
- **PR:** this branch (`agent/T-685-ux-polish`), built on T-684 (D-361)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** UX-024, UX-026, UX-027, UX-030, UX-031, UX-033, UX-035, UX-036, UX-038, UX-039, UX-041 of the deep
  review (`docs/reviews/2026-11-10-deep-review/02a-ux-clinical-journeys.md`); UX-024 and part of UX-026 and UX-033
  were done by T-684 (D-361)

## Context

The deep review of 2026-11-10 listed eleven Low findings on the clinical pages in ja and zh-TW: repeated reasons on
the not-matched list, internal codes and service ids beside clinical words, investigator wording on the coordinator's
worklist, a 32-character pseudonym as the patient's identifier, empty table headers, a long way by keyboard to the
mark buttons, native date fields that follow the browser's locale and not the page's, no 和暦, and a desktop banner
that still read "TB_ENV=DEV · 合成データのみ (D0)".

## Decision

1. **Plain banner.** The desktop banner says what the phone banner says, in the reader's language: a test site,
   synthetic (or public) data only, no real patients, every action recorded. The environment and the data class stay
   in the footer, which already names both.
2. **Codes under "Technical details".** An EDC refusal shows the sentence; its code is folded under "Technical
   details". The registry names the REDCap link as an author in words, not as `rc-bridge`, and shows its time in the
   site's time.
3. **One line per patient, criterion and source** on the not-matched list. A run's own rule (scope, research-contact
   consent) is listed once per patient, not once per action.
4. **Role words.** The worklist help on the week page has coordinator wording where the investigator's would be wrong
   ("The investigator approved contact, or you have contacted them").
5. **The 8-character code.** The candidate page shows the 8-character code, like every other page; the full
   pseudonym is folded under "Full pseudonym (to copy)" in a read-only field.
6. **Keyboard and screen readers.** The mark bar's Approach and Need info buttons have access keys A and I (one mark
   bar per page, so each key is unique), named in the button's title. Every header cell of an action or bar column
   has screen-reader text ("Actions", "Bar"), so no table header is empty.
7. **Date fields show their format.** Every date field has its format beside it ("YYYY-MM-DD"; ja "西暦 年-月-日",
   zh-TW "西元 年-月-日"), whatever the browser's own picker shows. The field stays a native date input: it sends
   ISO dates in every locale.
8. **The western calendar (UX-039, the review's owner question Q3).** Screens, exports and the screening log use ISO
   dates in the western calendar. No 和暦 is built now. If a Japanese site's 治験事務局 asks for 和暦, it is added
   to the screening-log XLSX export only, as a second column beside the ISO date, never on screens and never as the only
   date. This follows the review's recommended answer; nothing waits on it.

## Consequences

- Tests that read the banner for "TB_ENV" or "D0" read the footer instead.
- An access key's modifier differs by browser (Alt, Alt+Shift, Ctrl+Option); the title names the letter only.
- A 和暦 column is a later, separate change if a site asks; it does not change any stored date.
