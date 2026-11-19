# D-1375 One button: four variants, one small size, and the D-133 override layer folded away (9k-3)

- **Task:** plan 10 track F, the carried card 9k-3 (DS-3) of plan 9 rev 2 §3.5, from review 09
  (`docs/reviews/2026-11-root/09-ux.md` §1.1, §1.2, §3.2 component 2, §5.4). Waits for 9k-1 (D-1368, on master since
  train 99). · **Date:** 2026-11-19
- **Decision:**
  - **Six rules paint a button, and no others:** the base (primary: filled `--accent`), `secondary` (outline),
    `quiet` (text only, underlined; new, for the Cancel and Back acts of 9k-5 and 9k-7), `danger` (red outline: in
    the templates always `secondary danger`, so a harmful act is never a filled block beside the page's one primary
    act), the one small size `small`, and one disabled or busy look (`[disabled]`, `aria-busy="true"`, a link's
    `aria-disabled="true"`). Each variant is spelled for `<button>` and for a link styled as one (`.button`): a button
    acts, a link goes. "Paints" means it declares background, colour, border, radius, font, padding, opacity, cursor,
    text decoration or shadow on a selector whose subject is a button; a container still places its buttons (margin,
    flex, width), which is layout. By that count the sheet had 9 such rules (review 09 counted 32 with every rule that
    touched a button, layout included); the shared focus ring (every control, held by D-1368's contrast test) and the
    CJK no-wrap rule for pills and buttons (T-684) are rules for more than buttons and stay.
  - **The class names stay** (`secondary`, `small`, `danger`; review 09 proposed `.btn`, `.sec`, `.sm`): renaming
    them touches about 180 tags in 60 templates that the open lane pull requests also edit, for no change a person
    sees. `small-btn`, a class nothing styled (two links), became `small`.
  - **Every target is at least 44 px** in the base itself (`min-height` and `min-width`), the small size included
    (8 px 14 px padding, as D-133 made it); no rule that reaches a button sets a pixel size under 44.
  - **The D-133 layer is folded into the rules it re-set**, value for value, so the pages look as they did: field
    heights 44 px, the select's 44 px width, `form.inline select` and the mark row's select, the menu links, `.rail`,
    `.more-items`, `.pager`, `.tasks` and `.pipe` links, `details > summary` and "More", the help button, the brand,
    the skip link, pill and badge padding, the mark row's gap (the first of its two rules removed), `th`'s letter
    spacing, the search field. Removed as re-setting nothing: the second `body { font-size }` (the print rule's 15 px,
    which that line overrode, went too: print stays 16 px as it was) and the repeated `font-size: var(--t-meta)` list.
    Two rules stay under the old heading because rules above them of equal weight must not win: the 22 px check box
    and radio (over `.markform input`'s width) and the list of links that are targets on their own.
  - **Looked at:** the 72 first screens of 9k-17 (12 pages, desktop and phone, en, ja, zh-TW), shot before and after on
    this machine: 72 of 72 the same pixels. Off those pages, three small changes are meant: the "Next step" link of a
    coordinator's study card (`small` now: 8 px 14 px and weight 500, it was 8 px 14 px and 600), the "Open" link of
    the approval page (`button small` was never small: now it is, without the top margin), and `.pipe` counts, which
    D-133 had already turned from a grid into a row (kept as a row).
- **The proof:** `tests/unit/test_buttons_9k3.py` (a guard, no database): the six rules by name and in order, the
  counter catching a container that paints its buttons, no pixel size under 44 on a button rule, the re-set sizes
  declared once, what is left under the D-133 heading, no class of look in a template but the variants, danger always
  secondary. `tests/console/test_button_targets_9k3.py`: every visible button and button-styled link on the 72 pages
  measured in Chromium at 44 x 44 px or more, and a planted 28 px rule caught. `tests/unit/test_console_tokens_and_type.py`
  now holds that no body rule sets a second font size (it pinned the line the layer had).
- **Not in this card:** the page header and one primary act (9k-5), the confirm and Undo pages (9k-7), the bottom bar
  (9k-12), the template rewrites of 9k-15. **Not verified:** a native reader has not read the ja and zh-TW pages;
  the pages off the 72 shots were checked by reading the cascade, not by pixels.
- **Held by:** `tests/unit/test_buttons_9k3.py`, `tests/console/test_button_targets_9k3.py`.
