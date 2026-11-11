# D-361 Clinical layout in Japanese and Traditional Chinese: font stacks, line breaking, the mark bar, the first screen

- **Task:** T-684 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5; "Clinical UX Mediums")
- **PR:** this branch (`agent/T-684-cjk-ux`), built on T-116 (D-351)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** UX-023, UX-025, UX-037; the font part of UX-024, the word part of UX-033 and the skip-link part of
  UX-026 (the rest of those three stays with T-685)

## Context

The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/02a-ux-clinical-journeys.md`) ran the console in
ja and zh-TW on a desktop and a phone. Status pills in the week table broke one character per line (確/認/待/ち), the
EDC "退回" button broke 退/回. The full patient page had its mark bar below the fold. The patient panel's "ask the
treating doctor" link sat on the panel's edge. On a desktop the PI's first patient row started at y≈700 of 860,
under the six-step procedure, the SAE banner and the delegation-log reminder. One font stack served every language,
with Noto Sans TC before Noto Sans JP, so Japanese could take Chinese glyph forms.

## Decision

1. **One font stack per language, system fonts only.** `body:lang(ja)` names Japanese faces (Hiragino, Yu Gothic,
   Meiryo, Noto Sans JP, IPA), `body:lang(zh-TW)` Taiwanese faces (PingFang TC, Microsoft JhengHei, Noto Sans TC);
   an element with its own `lang` takes its language's stack. The base stack names no CJK face. The console ships no
   font file: the CSP is `default-src 'self'` and the report fonts of `tools/fetch_fonts.py` are for PDFs, not pages.
2. **CJK words are kept whole.** Pills, badges and buttons take `word-break: keep-all` with `overflow-wrap:
   break-word` (never `anywhere`, which lowers the minimum width and caused the one-character columns). A CJK label
   has no break inside it; an English label may wrap at a space. Japanese and Chinese pages use `line-break: strict`.
   A count pill ("不明 1") does not wrap. The week table's visit cell wraps between date and time only.
3. **The full patient page has the week sheet's sticky mark bar.** The bar is the last element of `main` and sticks
   to the window's bottom; its buttons reach the mark forms with the `form` attribute, as on the sheet. On phones
   `overflow-x: clip` replaces `hidden` on `html, body`: `hidden` made `body` a scroll box and no sticky bar stuck.
4. **The week page's first screen.** Once the study is set up (step 3 of 6 or later) the procedure folds to one line
   naming the current step; on the week page the SAE banner and the overdue-report banner fold to one line each with
   their count, still red-framed alerts, the acknowledgement one tap away. These and the delegation-log reminder sit
   in one row. Home and the study picker keep the full banners.
5. **Registry words.** The menu item has the page's own name (候補者レジストリ, 候選者登錄, Candidate registry), so the
   week panel no longer shows two links called "Screening log". The take-over help names the tiers with their screen
   words, not `tier high or review`; the chart-number field has no English abbreviation.
6. **Keyboard.** A second skip link goes to the patient list; the menu checkbox is a tab stop only on phones, where
   its Menu button shows.
7. **Checked in a browser.** `tests/console/test_cjk_layout.py` renders the pages in ja, zh-TW and en and measures
   them in Chromium at 1280 and 390 px (`tests/console/cjk_layout.js`): no pill or button line with one character,
   no CJK pill wrapping, no sideways scroll, no clipped link, the worklist fitting its box, the mark bar on the full
   page's first screen and the first patient row on the week page's first screen. CI has no Node Playwright, so the
   page and style-sheet tests of the same file carry the rules there.

## Consequences

- A long English pill can take two lines in a narrow cell; a CJK one widens its column instead.
- The IRB and referral warnings of the mark bar move with it into the sticky dock on the full page.
- Access keys for the mark buttons, the in-panel keyboard path and one consent action (UX-012) stay with T-685.
