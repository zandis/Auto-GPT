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

1. **A second look, for the tripwire only** (`guard.names.Look`; `Guard.tripwire`). It can only take a NAME
   finding in Chinese or Japanese writing away. Every other kind of finding stands, a name in Latin letters
   stands. The callers that take it: the gateway's tripwire, the guard service's `/v1/scan`, the test bench.
2. **Who does not take it** (every pattern match counts, as before): redaction at the trace store; the document
   parser's mask of a protocol's contact and subject lines (`mask_contacts`: the second review found subject
   lines the look would let through, 受試者…簽名); the older scan's other callers (the cloud clearance, consent,
   site set-up); note masking.
3. **What always keeps a finding** (both languages): an honorific inside the match or right after it, a sex
   after it, a surname of more than one character (歐陽, 山口), or a boundary after it: the text's end or any
   character that is not kana or Han (punctuation, a space, a line end of any kind, a digit, a Latin letter, the
   middle dot ・).
4. **Else, on a line with kana**: the finding stands if the tokeniser tags a token inside it as a proper noun
   (split mode C). If not, it is ordinary Japanese when a word of the tokeniser's dictionary, longer than one
   character, holds the surname's place (高血圧, 林檎), or when the match itself holds kana; else rule 5 decides
   (a Chinese name beside a Japanese drug name is not in a Japanese dictionary). Each line is put to the
   tokeniser once per call; nothing of the text is kept after it.
5. **Else, on a line without kana**, no tokeniser: the finding stands unless it reads as words: it begins a
   common word (高血壓, 許可, and so 王家 in 王家豪), or its surname character is an ordinary one-character word
   followed by a common word, with or without one short word between (曾｜使用, 曾｜有｜出現, and so 黃｜志豪).
   It never reads as words when every character after the surname is one of the 136 that stand after the first
   in at least 200 of the dictionary's person-name entries (高｜建國).
6. **The older scan** (`tb_common.phi_guard.scan`, which the tripwire also runs) takes the same look through a
   parameter: its name findings and its "date near a name" finding count only names that stand.
7. **It fails closed.** When the tokeniser or its dictionary cannot be loaded, raises, or the line is longer
   than 4,000 characters (`MAX_LINE`: not prose, and the tokeniser's time grows with the line), the finding
   stands as before this card. When the word list cannot be read, or a kind of it is empty, every Chinese
   finding stands. `trialbox doctor` has the check `tripwire_names`: WARN with the reason (also after a failure
   on a text, until the service restarts), since nothing is let through.
8. **The dictionary is pinned and named** (`guard.names.DICTIONARY`, the lock). Another dictionary, another word
   list or other frequencies are a re-measurement on the sets, as a model change is a requalification.
9. **The standing gate** (the integrator's rule after the first review): `tests/guard_sets.py` and a ceiling per
   shape in `test_tripwire_name_second_look.py`, in the unit suite. No change of the tripwire passes on an
   average or on an easy set; raising a ceiling is the owner's decision.

## Measured, with the code of this card

Today's tripwire (before this card) lets through none of the names below, since every pattern match refuses, and
refuses 84 of 84 ordinary Chinese sentences and 96 of 132 Japanese ones.

**Ordinary text refused** (`tests/fixtures/guard`): Chinese 15 of 84 (17.9 %); Japanese 7 of 132 (5.3 %; 4 of
the 7 are lines of the set that hold a name).

**The price is understated by those two sets** (second review, 564 composed Chinese and 116 Japanese texts: a
label, an ordinary word that begins with a surname character, then what follows): when a digit, a comma, a full
stop, a space or the line's end follows the word, 65 % are refused (病人高血壓，控制不良; 個案曾住院3次; 患者高齢、
独居である。), because a boundary keeps a finding; run into text, 49 %. On clauses of the synthetic note templates
(252 Chinese, 210 Japanese) 0 and 2 are refused.

**Names let through**, per shape (synthetic: 115 listed surnames x 50 made-up given names, Japanese 58 x 16;
"found" per shape):

| Shape | Found | Let through |
| --- | --- | --- |
| Chinese name with a cue or a boundary: honorific inside or after, sex, line end, CRLF, digit, Latin, bracket, dash, contact line (13 shapes) | 5,750 each | 0 |
| Chinese name with a cue or a boundary on a line that also holds kana (4 shapes); the middle dot after it | 5,750 each | 0 |
| Chinese name run straight into text (病人N今日回診; 5 shapes) | 5,750 each | 188 (3.3 %) |
| the same: the sixteen surnames that are ordinary words (黃 許 謝 曾 高 何 余 游 戴 白 古 涂 尤 嚴 于 黄) | 800 | 103 (12.9 %) |
| the same: the ten most frequent surnames | 500 | 13 (2.6 %) |
| the same: given names that are themselves common words (10 of the 50) | 1,150 | 95 (8.3 %) |
| the same: one-character given name | 1,380 | 7 to 23 (0.5 to 1.7 %) |
| Chinese name run into text on a line with kana, or with は / の right after it (4 shapes) | 5,750 each | 140 to 144 (2.5 %) |
| a subject line of a protocol (受試者N簽名; 4 shapes), through the tripwire | 5,750 each | 188 (3.3 %) |
| Japanese name on a line without kana (6 shapes) | 928 each | 0 |
| Japanese name on a line with kana (7 shapes) | 928 each | 0 or 1 (林学) |

**The second review's wider sets** (its own names, by running): with 200 given names that are everyday words
(文明, 和平, 安全, 自強), run into text: 9.6 % let through, 63 % for the sixteen ordinary-word surnames, 6.5 % for
the ten most frequent; with 320 composed given names: 0.8 %, 2.8 % and 0.7 %. So the figure depends strongly on
how word-like the given name is and on the surname: 3.3 % is the middle of a wide spread, not a bound.

Time: Chinese 0.09 ms a sentence; Japanese 2 to 5 ms; about 1 s once per process to load the dictionary and the
word list (about 20 MB).

## What the first forms of this card got wrong

1. The owner approved the trade on "97.9 % of names kept". That figure came from a set that was too easy: most
   of its names ended at a boundary, it had a dozen given names, none a common word, no compound surname and no
   line mixing Chinese and kana. The first review measured that form on harder shapes: 7.2 % let through for a
   Chinese name run into text (100 % for 歐陽 and 上官), 21 % for a Chinese name on a line with kana, 37 to 41 %
   for a Japanese name on a line without kana; a name at a CRLF line end counted as running text.
2. The rework's own table said "0 on a line with kana"; its four shapes all carried a cue or a boundary. The
   second review measured 24 to 27 % for a Chinese name run into text on such a line, and 26 % after a middle dot.
   Rule 4 and the middle dot as a boundary are the answer (2.5 % and 0 now).

## The trade, and the limits

- **A name the second look does not confirm is let through to the model where it was refused before.** After
  this card that is: a Chinese name with no cue and no boundary, run straight into text, that reads as words
  (個案黃志豪主訴頭痛, 病人王家豪今日回診). The table and the wider sets above say how often on synthetic names;
  with a comma, a space, an honorific, a sex or a line end after the name, none was let through.
- **The setting between the two sides** is the number of name characters (`GIVEN_MIN` in the builder; 200 now).
  By experiment (merged findings: close to, not exactly, the built figures), on names run into text and the
  ordinary Chinese set: now 3.3 % let through (ordinary-word surnames 12.8 %) and 17.9 % refused; one step
  2.2 % (4.9 %) and 29.8 %; two steps 1.2 % (2.1 %) and 36.9 %.
- **What the patterns never find**, before or after this card (not a let-through of it): a name with no label,
  honorific or sex beside it (LLM-004); surnames outside the lists (朴, 崔, 武; 五十嵐); most Simplified forms of
  surnames (张: 病人张伟今日复诊 is not found); names in kana only or in Latin letters without a title; a name
  after a role (計畫主持人：N, N醫師, 治験責任医師：N, 担当CRC N).
- The sets are synthetic; real notes will differ. The word list is general Chinese, not clinical.
- For uploaded protocols the document parser's mask keeps every pattern match, so an ordinary criterion line that
  matches a name pattern is still masked there (個案[NAME]任何生物製劑), as before this card: LLM-003 is answered
  for the gateway's refusals, not for that mask.

## Test

`tests/unit/test_tripwire_name_second_look.py` (nine of its first tests failed with the second look switched off;
the per-shape ceilings, the reviews' names, the stated limit and the document parser's mask were added after the
two reviews), `tests/guard_sets.py`.
