# D-647 The tripwire takes a second look at a Chinese or Japanese name finding

- **Task:** NEW-LLM-3 and NEW-LLM-4 (plan v7 wave 2; deep review LLM-003): "the PHI tripwire stops refusing ordinary
  zh-TW and ja criteria"
- **PR:** this branch (`agent/NEW-LLM-3-tripwire-tokeniser`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Ruling:** the owner's of 2026-11-13, relayed by the integrator: yes to the trade below; no GPL; the word list a
  shipped data file with a licence-register row; the gates run before the lock changes; an adversarial review.

## Reuse proposal (accepted by the integrator 2026-11-13)

| What | Project | Licence | Pinned | Where |
| --- | --- | --- | --- | --- |
| Japanese part-of-speech tags | SudachiPy | Apache-2.0 | 0.7.0 | inside the tripwire only |
| its dictionary | sudachidict-core | Apache-2.0 | 20261015 | a wheel in the lock; nothing downloaded at run time |
| Chinese common words | the jieba project's word list, read as data at build time; Traditional forms by OpenCC | MIT; Apache-2.0 | jieba 0.42.1, opencc-python-reimplemented 0.1.7 | `services/guard/data/zh_common_words.txt`; neither package is in the lock or an image |

**Rebuilding the word list** (`python -m tools.zh_common_words --dict <jieba>/dict.txt --out ...`, in a scratch
environment with opencc-python-reimplemented 0.1.7): from `jieba/dict.txt` of jieba 0.42.1, sha256
`7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8`, the tool writes
`services/guard/data/zh_common_words.txt` with sha256
`7e25b2267894b3af247ed6e8d0f7eceee0305b11f8a1e195b0621dccb96654ec` (161,721 rows; rebuilt and compared on
2026-11-13). A test holds the file's hash and that neither jieba nor opencc is in a lock.

Not taken: fugashi with UniDic (measured; dictionary terms and a native build), jieba as a run-time tokeniser
(measured: 94.8 % of names kept, worse than the rule below), Presidio (a yardstick outside the lock only).

**What the gates said** (by running, before the lock changed): `make lock-check` PASS with uv 0.13.7; allow-list
check PASS, no entry needed; pip-audit "No known vulnerabilities found", gate PASS; the licence gate on the lock's
SBOM PASS, both packages Apache-2.0. Installed size: the dictionary 193 MB, the tokeniser 4.9 MB (wheels 76.9 MB
and 1.8 MB): about +198 MB in the one Python image, the bundle and the media (for lane D). They are base
dependencies: there is one Python image for the services (the integrator's ruling).

## Context

The name recognisers are patterns: a surname character, one or two more characters and a cue (a label, an
honorific, a sex). In running text that shape is everywhere: 個案曾使用…, 病人高血壓…, 患者 高血圧…. Measured on
synthetic sets (`tests/fixtures/guard`), the tripwire refused every sentence of the Chinese set of ordinary
clinical text and 72.7 % of the Japanese one. A refused judge call is an unknown; a refused criterion line is
masked in the compiler.

## Decision

1. **A second look, for the tripwire only** (`guard.names.Look`). It can only take a NAME finding in Chinese or
   Japanese writing away. Every other kind of finding stands, a name in Latin letters stands, and redaction at
   the trace store keeps masking every match.
2. **What always keeps a finding** (both languages): an honorific inside the match or right after it, a sex
   after it, a surname of more than one character (歐陽, 山口), or a boundary after it: the text's end or any
   character that is not kana or Han (punctuation, a space, a line end of any kind, a digit, a Latin letter).
3. **Else, on a line with kana**: the finding stands only if the tokeniser tags a token inside it as a proper
   noun (split mode C). Each line is put to the tokeniser once per call; nothing of the text is kept after it.
4. **Else, on a line without kana**, no tokeniser: the finding stands unless it reads as words: it begins a
   common word (高血壓, 許可), or its surname character is an ordinary one-character word followed by a common
   word, with or without one short word between (曾｜使用, 曾｜有｜出現). It never reads as words when every
   character after the surname is one that given names are made of (王｜家豪, 高｜建國): the 136 characters that
   stand after the first in at least 200 of the dictionary's person-name entries.
5. **The older scan** (`tb_common.phi_guard.scan`, which the tripwire also runs) takes the same look through a
   parameter: its name findings and its "date near a name" finding count only names that stand. Its other
   callers (the cloud clearance, consent, site set-up, note masking) do not take the look.
6. **It fails closed.** When the tokeniser or its dictionary cannot be loaded, raises, or the line is longer
   than 4,000 characters (`MAX_LINE`: not prose, and the tokeniser's time grows with the line), the finding
   stands as before this card. When the word list cannot be read, or a kind of it is empty, every Chinese
   finding stands. `trialbox doctor` has the check `tripwire_names`: WARN with the reason (also after a failure
   on a text), since nothing is let through.
7. **The dictionary is pinned and named** (`guard.names.DICTIONARY`, the lock). Another dictionary, another word
   list or other frequencies are a re-measurement on the sets, as a model change is a requalification; the tests
   hold the figures as gates.

## Measured, with the code of this card

**Ordinary text** (no name in it; `tests/fixtures/guard`):

| Set | Sentences | Refused before | Refused after |
| --- | --- | --- | --- |
| Chinese, ordinary clinical text | 84 | 84 (100 %) | 15 (17.9 %) |
| Japanese, ordinary text | 132 | 96 (72.7 %) | 4 (3.0 %) |

**Names** (synthetic: every listed surname with made-up given names, in the shapes of notes and contact lines;
`tests/guard_sets.py`). "Let through": the patterns find the name and the tripwire no longer refuses the text.

| Shapes | Names found | Let through |
| --- | --- | --- |
| Chinese name with a cue or a boundary (honorific, sex, line end, CRLF, digit, Latin, bracket; 13 shapes) | 74,750 | 0 |
| Chinese name on a line that also holds kana (4 shapes) | 23,000 | 0 |
| Chinese name run straight into text, two-character given name (6 shapes; 50 given names, many of them common words) | 34,500 | 940 (2.72 %; 3.3 % in each shape with only text after the name) |
| the same, one-character given name | 8,280 | 82 (0.99 %) |
| Japanese name on a line with kana (7 shapes) | 6,496 | 5 (0.08 %) |
| Japanese name on a line without kana (6 shapes) | 5,568 | 0 |
| the card's first, easy sets: Chinese 191, Japanese 83 | 274 | 3 and 2 (98.4 % and 97.6 % kept) |

Time: Chinese 0.09 ms a sentence; Japanese 2 to 5 ms, and about 1 s once per process to load the dictionary and
the word list (about 20 MB).

## What the first form of this card got wrong

The owner approved the trade on "97.9 % of names kept". That figure came from a set that was too easy: most of
its names ended at a boundary, it had a dozen given names, none a common word, no compound surname and no line
mixing Chinese and kana. The adversarial review measured the first form on the shapes above: 7.2 % let through
for a Chinese name run into text (26 % for the sixteen surnames that are ordinary words, 100 % for 歐陽 and 上官),
21 % for a Chinese name on a line with kana, 37 to 41 % for a Japanese name on a line without kana, and a name
at a CRLF line end counted as running text. Items 2 and 4 above are the answer; the false refusals did not
change (17.9 % and 3.0 %).

## The trade, and the limits

- **A name the second look does not confirm is let through where it was refused before.** After this card that
  is one shape: a Chinese name with no cue and no boundary, run straight into text, whose characters read as
  common words and are not all common name characters (個案黃志豪主訴頭痛). On the hard set that is 3.3 % of such
  occurrences; with a comma, a space, an honorific, a sex or a line end after the name it is 0.
- **The setting between the two sides** is the number of name characters (`GIVEN_MIN` in the builder; 200 now).
  Measured by experiment before the port (merged findings, so close to but not the built figures): at 200,
  3.3 % let through and 17.9 % of ordinary Chinese text refused; at 100, 1.5 % and 29.8 %; at 50, about 1 % and
  36.9 %; with no name characters, 5.3 % and 17.9 %. 200 is the largest list that costs nothing on the ordinary
  sets.
- **LLM-004's unlabelled names are not addressed**: a name with no label, honorific or sex beside it was not found
  by the patterns before this card and is not found now.
- The sets are synthetic; real notes will differ. The word list is general Chinese, not clinical, and the given
  names of the hard set were chosen to be hard, not to match how often such names occur.
- The document parser's mask of a protocol's contact lines keys on the tripwire and so takes the look: the
  review's contact lines (聯絡人…先生, 治験責任医師 …氏, 連絡先 …様) are masked as before; an ordinary criterion
  line is no longer masked as a name.

## Test

`tests/unit/test_tripwire_name_second_look.py` (nine of its first tests failed with the second look switched off;
the hard sets, the review's names and the stated limit were added after the review), `tests/guard_sets.py`.
