# D-1368 The console's colours and type are tokens; Japanese and Chinese pages get their own line rules (9k-1, 9k-2)

- **Task:** plan 10 track F, the carried cards 9k-1 (DS-1, with 9g-17 and 9g-18 merged into it) and 9k-2 (DS-2) of
  plan 9 rev 2 §3.5, from review 09 (`docs/reviews/2026-11-root/09-ux.md` §1.1, §1.3, §3.1; A11Y-1, A11Y-2 of
  review 02). · **Date:** 2026-11-19
- **Decision:**
  - **Every colour `console.css` paints is a custom property on `:root`**, light, with its dark value under
    `@media (prefers-color-scheme: dark)` as before (the console keeps following the system; review 09 §3.1). The
    literals and `rgba` shadows outside `:root` became tokens of the same value: `--on-banner`, `--banner-prod`,
    `--shadow`, `--shadow-low`, `--print-bg`, `--print-ink`, `--print-line`; the fallbacks in `var(--line, #ddd)`,
    `var(--warn-bg, #fff6db)` and `var(--muted, #555)` went (the tokens are always defined). The existing names stay
    (`--bg`, `--ink`, `--line` …): review 09's `--c-*` renaming is left to the cards that rewrite the components
    (9k-3 onward), so the open lane J pull requests and this one meet in few lines.
  - **A field's border is `--control`** (`#7b8594` light, `#7c8797` dark: 3.73 and 3.48:1 on `--card` and `--bg`
    light, 4.45 and 4.99:1 dark), review 09's values; `--line` (1.3 to 1.5:1) stays for decorative rules only
    (WCAG 1.4.11; A11Y-1, 9g-17).
  - **The amber row is `--warn-bg` in both modes** (`tr.amber td`), as `table.approval tr.amber` already was. The
    `color-mix` with a literal amber gave dark mode a light row under light text (2.95 and 2.64:1; A11Y-2, 9g-18).
    In light mode the row is the paler `#fff4dc` instead of the mixed `#f6e3b0`: the one change of look in light
    mode besides the field borders.
  - **No page names a colour:** `base.html`'s `theme-color` is `console.phone.THEME` through a template global; a
    test holds it equal to the light `--banner`, and the manifest's background to `--bg`.
  - **The type scale is tokens at today's sizes:** `--t-meta` 15 px (the D-133 floor), `--t-body` 16, `--t-h2` 17,
    `--t-lead` 18, `--t-h1` 22, `--t-num` 26; line heights `--lh` 1.5, `--lh-head` 1.5, `--lh-cjk` 1.7 (DADS: 170 %
    at 16–17 px). Body, headings and every 15 and 16 px text use them. Review 09's larger scale (16/18/20/24/28 with
    a 14 px meta) is not taken: it changes every page's look, and 14 px breaks D-133's 15 px floor. The few sizes
    outside the scale (the 11 px chart axis, the 22 px tile count on a phone, `.otp`, `1.5em`) are untouched.
  - **Japanese and Traditional Chinese** (`body:lang(ja)`, `body:lang(zh-TW)`): line height `--lh-cjk`,
    `line-break: strict` (as T-684 set it), `word-break: normal`, `overflow-wrap: break-word` (a long code or
    address breaks rather than widening the page; break-word, not anywhere, so no minimum width shrinks), and no
    italic for emphasis (`em` upright and bold; CLReq, JLReq). Headings keep `--lh-head` 1.5 in every language. The
    per-language font stacks of T-684 (D-361) stay: system fonts only, no font file, no download.
  - **The proof is a guard test** (`tests/unit/test_console_tokens_and_type.py`, marked `guard` and `nodb`, so the
    guard step runs it on every CI tier and the unit shards run it again): the stylesheet lint (no hex, colour
    function or named colour outside a rule whose selector is `:root` alone; the same in templates' `style`, in
    either quote, and in SVG `fill` and `stroke`, no hex in a template, and none in `console.js`), every `var()`
    defined, every colour token set for light and for dark (the names compared; banner ink, shadows and print are
    named as the same in both), the WCAG contrast of 28 pairs in each mode computed in pure Python (text 4.5:1,
    links on the amber and ok backgrounds, warning and error text on a card, a field's border 3:1 also in the amber
    row, the focus ring 3:1 against the backgrounds next to it, the amber row's text on `--warn-bg`; the link and
    focus tokens read from their rules), and the type and CJK rules (`em:lang(ja)`, so an English `em` keeps its
    italic). No new dependency; no workflow change.
- **Not in this card:** button structure (9k-3), the state badge's classes (9k-4: their colours were already
  tokens), visual regression in CI (9k-17). **Not verified:** the ja and zh-TW rendering has not been read by a
  native reader (the card's sign-off; it blocks nothing); the screenshots were taken in this box's Chromium with the
  fonts installed here, not the faces a site's browsers have.
- **Held by:** `tests/unit/test_console_tokens_and_type.py`; `tests/console/test_tokens_and_type_pages.py` (pages
  carry their `lang` and the `theme-color` from Python); `tests/console/test_cjk_layout.py` (the stacks, the CJK
  screenshots); `tests/console/test_phone_first.py` (the `theme-color` meta).
