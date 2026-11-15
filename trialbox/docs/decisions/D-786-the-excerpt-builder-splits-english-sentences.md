# D-786 The excerpt builder splits English sentences

- **Task:** A-SENT-EN (found by the NEW-LLM-6 review, 2026-11-14)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-14
- **Status:** reserved
- **Builds on:** D-479 (one excerpt builder), D-641 (a long note is cut around its evidence)

## Decision

`matching.excerpts.sentences` also splits English text after a full stop followed by white space and a capital
letter, a digit or an opening bracket or quote (a closing bracket or quote may follow the stop). It never splits:

- after a short form that does not end a sentence (Dr., Mr., Mrs., Ms., Prof., St., Sr., Jr., vs., e.g., i.e., cf.,
  approx., Fig., et al., Pt., Hx., Dx., Rx., Sx., Tx., vit., Wd., and the month abbreviations);
- after "No." before a number, a list number ("1."), an initial ("J. Smith"), or inside a number;
- from the first sentence of a line that carries a label ("Family history: …", "Denies: …") to the end of that
  line: the label and its items are one unit, so a relative's condition or a denied symptom is never shown without
  its label (the review of this card);
- in a line with Japanese or Chinese characters: such text splits exactly as before.

The word before a stop is read from a bounded look back, so the split is linear in a note's length.

Before, an English note written as a paragraph was one "sentence": the cascade's lexicon hit and S2b ranking pointed
at the whole paragraph, and a paragraph longer than half the excerpt budget was cut to nothing, so the models read
nothing and the answer was unknown ("notes over budget"). It failed safe, but lost the evidence of English notes.

## Not changed

The goldens are identical, and they do not exercise this path: the synthetic hospital writes zh-TW notes by
default, and the English notes (`tools/synth/notes_en.py`) are used only by runs with `--langs en`. The rule is a
fixed list, not a trained tokenizer: the registry matcher's `sent_tokenize` depends on whether NLTK is
installed, and the excerpts must be the same on every box.

## Test

`tests/unit/test_excerpt_sentences_en.py`.
