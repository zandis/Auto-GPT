# D-1235 A Japanese name analyser for the guard: SudachiPy with SudachiDict-small, approved and added

- **Task:** card 10C-1b of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C; follow-up of 10C-1, PR #1091)
- **Date:** 2026-11-19
- **Status:** accepted (lane J's block D-1220 to D-1319). The owner said yes on 2026-11-19 to exactly `sudachipy==0.7.0`
  with `sudachidict-small==20261015`, pinned with hashes, from the package index the build already uses; recorded on
  PR #1149 in a comment posted from the repository owner's account by lane J's coordinator (2026-11-19 22:42Z). The
  yes covers nothing else: no other package, no model download, no allow-list or scan exception entry. (The file
  name keeps the slug the number was reserved with.)
- **Builds on:** D-647 (the tripwire unchanged; a tokeniser measured and not merged), the 10C-1 rules
  (`libs/tb_common/phi_guard.py`), the supply-chain gates (D-185, D-186)
- **Assessment:** `docs/research/2026-11-19-japanese-name-analyser.md`

## Context

The guard's Japanese rules find a name by a label, an honorific, a title or a listed surname. A name with none of
these beside it is missed (見本太郎は本日来院, 68歳男性 ミホン タロウ): the probe file keeps such lines as strict known
gaps. The owner approved in principle a mature open Japanese morphological analyser with person-name tagging, and
asked for one choice with its licence and size before it becomes a dependency.

## Decision

1. **Chosen:** SudachiPy 0.7.0 with SudachiDict-small 20261015, runtime dependencies (`pyproject.toml`, `uv.lock`,
   `deploy/requirements.lock`, so the `trialbox-py` and demo images), registered in the guard by default
   (`phi_guard.japanese_names`): loaded lazily, one tokenizer per thread, only for a text with kana or 歳 (a language,
   not a country); no import when the guard loads; offline after install. `NOTE_MASK_VERSION` 8. Apache-2.0 code and dictionary (UniDic's words,
   BSD-3-Clause, whose notice `NOTICE` must carry). Wheels for x86-64 and aarch64, no compiler, offline after
   install, no neural model. About 115 MB installed per image, 44 MB to download, about 9 ms per 10 kB note.
   Measured: 58 of 75 unlabelled names of the card's lines and 26 of 30 of a held-out set masked (rules alone: none),
   no ordinary line changed of 266.
2. **Runner-up:** the same engine with SudachiDict-core 20261015: two more names of 75, 83 MB more, and a part of
   NEologd in the dictionary (its sources include the Hatena keyword list, whose terms were not read).
3. **The combination rule:** the analyser proposes, the guard decides: a name run of the analyser's tags with its
   other half; never a lone surname or katakana word; never before a word of a disease, sign, procedure, scale,
   institution or place; never a word the rules already say is no name; only Japanese text (kana or 歳).
4. **Not chosen:** SudachiDict-full (an sdist that downloads its dictionary at build: the images install wheels only);
   MeCab with unidic-lite, IPADIC or UniDic (fewer names, dictionaries without wheels or downloaded after install,
   UniDic 2.1.2 of 2013, IPADIC of 2007 with no licence metadata on the package index); NEologd (not on the index,
   built by script, Hatena-sourced); Janome (ten times slower, IPADIC); GiNZA (a trained model; requires SudachiPy
   below 0.7); Lindera and Vibrato (dictionaries downloaded separately; Vibrato has no aarch64 wheel); Kuromoji
   (Java).

## What landed

First (before the owner's yes): the hook `phi_guard.NAME_RECOGNISERS` read by `note_spans`; `tb_common.ja_names` (the
analyser loaders and the rule); the harness `tools/ja_name_eval.py`; 210 synthetic lines; tests. Then, on the yes: the
two packages in `pyproject.toml`, `uv.lock` and `deploy/requirements.lock` (`make lock`, uv 0.13.7; the export also
reaches `deploy/requirements-embed.lock`, which installs the runtime set with the embed extra); the analyser
registered by default; `NOTE_MASK_VERSION` 8; the known-gap probe 68歳男性 ミホン タロウ moved to `masked`; the test that
every 10C-1 rule is needed runs the rules alone; the register row `sudachidict-small` and UniDic's BSD-3-Clause notice
in `NOTICE` section 7. No entry in `deploy/supply-chain-allowlist.yaml`.

## Consequences

- With the analyser on, names that the dictionary does not hold (rare surnames, invented given names), a romaji name
  and a name in a kanji-only text are still missed; addresses without 市, pension and passport numbers remain gaps for
  rules.
- The numbers are synthetic, written by the lane that wrote the rule; a site's own sample is the real test.
