# D-786 The excerpt builder splits English sentences

- **Task:** A-SENT-EN (found by the NEW-LLM-6 review, 2026-11-14)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-14
- **Status:** reserved
- **Builds on:** D-479 (one excerpt builder), D-641 (a long note is cut around its evidence)

## Decision

`matching.excerpts.sentences` also splits English text after a full stop followed by white space and a capital
letter, a digit or an opening bracket or quote (a closing bracket or quote may follow the stop). It never splits after
a short form that does not end a sentence (Dr., Mr., Mrs., Ms., Prof., St., Sr., Jr., vs., e.g., i.e., cf., approx.,
Fig.), after "No." before a number, after an initial ("J. Smith"), or inside a number. Japanese and Chinese text and
line ends split as before.

Before, an English note written as a paragraph was one "sentence": the cascade's lexicon hit and S2b ranking pointed
at the whole paragraph, and a paragraph longer than half the excerpt budget was cut to nothing, so the models read
nothing and the answer was unknown ("notes over budget"). It failed safe, but lost the evidence of English notes.

## Not changed

The rule is a fixed list, not a trained tokenizer: the registry matcher's `sent_tokenize` depends on whether NLTK is
installed, and the excerpts must be the same on every box.

## Test

`tests/unit/test_excerpt_sentences_en.py`.
