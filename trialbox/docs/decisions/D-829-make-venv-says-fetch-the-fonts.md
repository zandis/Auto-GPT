# D-829 make venv says to fetch the report fonts

- **Task:** DEV-FONTS, the integrator's note of 2026-11-15 from the CGRD-side host run (#639)
- **PR:** this branch (`agent/DEV-FONTS-venv-says-fetch-the-fonts`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

1. On a fresh checkout, `make venv` prints one line when `.cache/fonts` lacks the report fonts: run `make fonts`
   once before the first SCREEN job. A host run had 3 of 8 SCREEN jobs fail at the report (ReportError) first.
2. `make venv` downloads nothing: CI runs it in every job. The README's setup lists `make fonts`.
3. An installed box is not affected: `make images` needs the fonts and the trialbox-py image carries them in
   `/opt/trialbox/fonts`, so every bundle has them.

## Test

`tests/unit/test_dev_fonts_hint.py`: before, the missing-fonts case failed; after, all three pass.
