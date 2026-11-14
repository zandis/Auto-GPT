# D-687 The feasibility pack's PDF draws through the reports' glyph fallback

- **Task:** the last of the three places the PDF fallback of #477 left out (the reports, the NAV summary, the
  deliverables); `services/deliverables/render.py` given to lane E by the owner on 2026-11-13
- **PR:** this branch (`agent/UX-002-deliverables-pdf-glyph-fallback`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** the reports' fallback (`orchestrator.reports.common`: `with_fallback`, `common.Paragraph`,
  `draw_string`; #477) and the NAV summary's use of it

## Context

The feasibility pack (DL-1) is set in Noto Sans TC. A site's name, a table cell or a section title written with a
character only the Japanese font has was a blank box, in the heading, the table and the footer: the pack built its
PDF with reportlab's own `Paragraph` and `canvas.drawString`. Shown by a test before the change.

## Decision

1. **Every paragraph of the pack is `common.Paragraph`, and the footer is drawn with `common.draw_string`**: a
   character the page's font lacks and the other family has is drawn in the other family; a run in one script
   embeds one family, as before.
2. **Nothing else of the renderer changes**: the frozen object, the check of its hash and trace, the layout. A
   pack whose text the page's font holds is drawn as it was, and the bytes stay deterministic (rendered twice,
   the same bytes, with and without a character of the other family).
3. **Not changed:** the pack's page is always set in the Traditional Chinese family, whatever the site's
   language (the fallback draws the Japanese characters it lacks); a locale for the pack is its own card.

## Evidence

`tests/unit/test_deliverables_pdf_glyph_fallback.py`: a Japanese-only character in the heading, a table cell, a
section title and the footer (each a box before); a Japanese-only and a zh-TW-only character on one page; one
family for one script; the same bytes twice; the renderer holds no `Paragraph` of reportlab's own and no
`drawString`.
