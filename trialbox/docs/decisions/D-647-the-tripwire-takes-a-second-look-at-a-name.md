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

Not taken: fugashi with UniDic (measured; dictionary terms and a native build), jieba as a run-time tokeniser
(measured: 94.8 % of names kept, worse than the rule below), Presidio (a yardstick outside the lock only).

**What the gates said** (by running, before the lock changed): `make lock-check` PASS with uv 0.13.7; allow-list
check PASS, no entry needed; pip-audit "No known vulnerabilities found", gate PASS; the licence gate on the lock's
SBOM PASS, both packages Apache-2.0. Installed size: the dictionary 193 MB, the tokeniser 4.9 MB.

## Context

The name recognisers are patterns: a surname character, one or two more characters and a cue (a label, an
honorific, a sex). In running text that shape is everywhere: 個案曾使用…, 病人高血壓…, 患者 高血圧…. Measured on
synthetic sets (`tests/fixtures/guard`), the tripwire refused every sentence of the Chinese set of ordinary
clinical text and 72.7 % of the Japanese one. A refused judge call is an unknown; a refused criterion line is
masked in the compiler.

## Decision

1. **A second look, for the tripwire only** (`guard.names.stands`). It can only take a NAME finding in Chinese or
   Japanese writing away. Every other kind of finding stands, a name in Latin letters stands, and redaction at
   the trace store keeps masking every match.
2. **Japanese** (the finding's line holds kana): the finding stands only if the tokeniser tags a token inside it
   as a proper noun (split mode C).
3. **Chinese** (no kana on the line), no tokeniser: the finding stands when a boundary follows it (the end,
   punctuation, a space, an honorific, a sex). Else it stands unless it begins a common word, or its surname
   character is an ordinary one-character word followed by a common word, with or without one short word between
   (曾｜使用, 曾｜有｜出現).
4. **The older scan** (`tb_common.phi_guard.scan`, which the tripwire also runs) takes the same look through a
   parameter: its name findings and its "date near a name" finding count only names that stand.
5. **It fails closed.** When the tokeniser or its dictionary cannot be loaded, raises, or the line is longer
   than 4,000 characters (`MAX_LINE`: not prose, and the tokeniser's time grows with the line), the finding
   stands as before this card. When the word list cannot be read, every Chinese finding stands.
   `trialbox doctor` has the check `tripwire_names`: WARN with the reason, since nothing is let through.
6. **The dictionary is pinned and named** (`guard.names.DICTIONARY`, the lock). Another dictionary, another word
   list or other frequencies are a re-measurement on the sets, as a model change is a requalification; the tests
   hold the figures as gates.

## Measured, with the code of this card

| Set | Sentences | Refused before | Refused after |
| --- | --- | --- | --- |
| Chinese, ordinary clinical text | 84 | 84 (100 %) | 15 (17.9 %) |
| Chinese, with a synthetic name | 191 | 191 | 187 (97.9 % kept) |
| Japanese, ordinary text | 132 | 96 (72.7 %) | 4 (3.0 %) |
| Japanese, with a synthetic name | 83 | 83 | 81 (97.6 % kept) |

Time: Chinese 0.09 ms a sentence; Japanese 2 to 5 ms, and about 4 s once per process to load the dictionary.

## The trade, and the limits

- **A name the second look does not confirm is now let through where it was refused before**: 2.1 % of the
  labelled Chinese names and 2.4 % of the Japanese ones on these sets (a name followed directly by text that
  makes a common word with it; a name the tokeniser does not tag). The owner accepted this trade.
- **LLM-004's unlabelled names are not addressed**: a name with no label, honorific or sex beside it was not found
  by the patterns before this card and is not found now.
- The sets are synthetic and small; real notes will differ. The word list is general Chinese, not clinical.
- A Japanese line with no kana is judged by the Chinese rule.

## Test

`tests/unit/test_tripwire_name_second_look.py` (nine of its tests fail with the second look switched off); the
Japanese sets' test runs wherever the tokeniser is installed.
