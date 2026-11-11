# D-398 PoC-path words: help names the tester's own study, the referral selects say what to choose, EDC review shows words

- **Task:** T-511 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-511-poc-ux-words`), on top of T-516, T-116 and T-115
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** UX-016, UX-010, UX-029 (help half)

## Context

The 2026-11-10 deep review (TB-DR-02a) walked the PoC path in ja and zh-TW. The help panel's examples named the
first study in alphabetical order, not the study the tester works on (UX-029). On the referral form, the
staff-directory select said "Choose a reason" (UX-016). The EDC review showed codes, not words: "Sex 1" with no
label, the REDCap variable name first, a source line made of a table name and a row hash, item labels in English on
zh-TW, and no next step after "no REDCap record" (UX-010).

## Decision

1. **Help names the tester's own study.** The examples use the study of the page the help was opened from. Opened
   from a page with no study, they use the first study whose delegation log lists the account, else the first study
   in scope. The candidate, referral and EDC pages get their own "This page" text.
2. **The referral selects say what to choose.** The staff-directory select says "Choose a doctor". The department
   select says "Choose a department" when the row names no department.
3. **EDC review shows words.** The item's name comes first, in the reader's language. It is the dictionary's own
   label in that language, else the standard name of its CDASH variable from the console catalogue, else the
   dictionary's label as written, marked "as given". The REDCap variable and CDASH tag are shown small below it. A
   coded value carries its word ("1 · 男性"). The word is the dictionary's choice label in the reader's language,
   else a common word (male, female, yes, no) from the catalogue. The source is one readable line ("検査・測定
   2026-11-01: 72.5 kg"). The table, row and snapshot stay one click away under "Record reference". After a send
   with "no REDCap record", the page says to create the record in REDCap first. The data core's `/sources` call now
   returns each field's choices and their per-language labels. These come from the dictionary, not from a record.

## Consequences

- No value, signature, hash or send path changes. Only what the page shows changes. The signed hash, the citation
  stored with each draft and the ODM export are as before.
- A study whose dictionary has labels in every language shows its own words. The catalogue's standard names are a
  fallback for a few CDASH variables only.
