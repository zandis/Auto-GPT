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
   (`phi_guard.japanese_names`): loaded lazily, one tokenizer per thread, only for Japanese text (a language, not a
   country; see the second round); no import when the guard loads; offline after install. `NOTE_MASK_VERSION` 8.
   Apache-2.0 code and dictionary (UniDic's words, BSD-3-Clause, whose notice `NOTICE` must carry). Wheels for
   x86-64 and aarch64, no compiler, offline after install, no neural model. About 115 MB installed per image (also
   the embed image, whose lock carries the runtime set), 44 MB to download. Round one measured 58 of 75 unlabelled
   names of the card's lines and 26 of 30 of a held-out set masked (rules alone: none), no ordinary line changed of
   266; round two's figures are below.
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

## Second round (the coordinator's independent measurement)

On 400 invented chart lines the coordinator wrote before reading the rule, round one masked 123 of 174 names on
plain lines and 33 of 40 on near-misses, with no over-masking on 150 lines without a name; 57 of 214 names leaked, by
class. The second round changes the rule by class (`tb_common.ja_names`, its docstring states each step):

- **Language from the site and the text, not a guess from kana** (`phi_guard.japanese_text`): kana, 歳 or a kanji
  only Japanese writes is Japanese at any site; other Han text is read when the site declares Japanese notes
  (`settings.site.notes_language: ja`), never when it declares Chinese or English, and, when it declares nothing,
  unless the text holds a character only Chinese writes. A Chinese note with such a character is not read.
- **Hiragana names**, a given name after a surname and a surname by its reading.
- **By position**: the word before a title or an honorific, after a name label, before an age or a sex.
- **Katakana foreign names** joined across ・ in this module's own code (the analyser returns ・ as a word of its own:
  round one's "joined across a middle dot" was not true); eponyms as diseases stay.
- **Never half a name**: a name that starts inside a run of kanji takes the run (四月一日 君子).
- **Romaji**: two Hepburn words, one a surname by its reading; a Latin word before a title or after a label. On
  1,506 files of the repository (20 MB, English notes and documents) the pair rule found 6 spans, all of them names.
- **Over-masking removed**: 井上看護師 masks 井上 only (round one took 看護), 太田胃散 is a medicine.
- **Memory**: 28 MB after import, about 73 MB after the first Japanese text, 135 MB after 1,000 notes and 137 MB after
  50,000; the heap stays at 31 MB from 1,000 to 50,000 notes and the rest is the memory-mapped dictionary's pages
  (file-backed, at most its 110 MB file). No growth to bound; the one cache of the module is bounded (4,096 readings).

Development figures (the lane's own sets, not the coordinator's): the class fixtures
`eval/phi_synth/ja_name_classes.json` 43 of 51 names leaked with the rules alone, 42 after round one, 3 after round two
(the 3 stated limits), no counter-case changed; the card's lines 17 → 11 of 75 and the earlier held-out set 4 → 2 of
30 (no longer held out: its misses were read in round two), no ordinary line changed of 266.

**Limits after round two**: a kanji surname alone with nothing beside it (浅野: a place as often); a hiragana surname
the analyser does not know by its reading (すどう); a romaji surname alone (Kimura), and, in a text that is not
Japanese, a romaji pair whose surname is not one of the guard's 57 listed surnames; initials; a name inside a
clinic's name; rare surnames the dictionary does not hold (四十物, 勅使河原, 小鳥遊) with no title, label or age beside
them; a kanji-only line at a site that declares Chinese or English notes. Two over-masks of master's rules remain
(赤ちゃん → ○ちゃん, 校長先生 → ○○先生): not this card's.

## Third round

On the coordinator's 400 held-out lines, round two leaked 18 of 214 names (master 83, round one 57) and over-masked
none of 150 no-name lines, with the notes language `ja` and with `auto`. Of the 18, 13 were a surname beside a
clinical title or role. The third round, by class (fixtures and counter-cases of the lane's own, not the
coordinator's lines, in `eval/phi_synth/ja_name_classes.json`; each class has rows that fail on round two's head
81f91352):

- **A surname beside a title or a role, in either order and any spacing, kanji or romaji** (Dr. 石川へ, Dr.Sakamoto,
  藤田Drに, 小西 Dr., 今井Ns.へ, Ishida Ns., 担当OT：宮田, 主治医 は 岡田 です, 看護師　森田　より). The titles, the
  roles, the particles between them and the words that stand in a name's place but are none are **data**,
  `libs/tb_common/ja_name_cues.json` (`tb-ja-name-cues/1`), keyed by the language of the text like the rest of the
  guard's Japanese rules (country layer part P10: on everywhere), not by a country.
- **A name with its reading in brackets** (工藤（くどう）様, すだ（須田）様) and **a name masked once, masked at its
  other bare occurrences in the same note** (菅野さんへ電話。菅野は外出中。), never inside a longer word or before a
  term (菅野病院, 河合町); an out-of-dictionary surname before a given name and 氏 with spaces (勅使河原 誠 氏).
- **Mixed forms**: a kanji name with its romaji (石井 Ishii 様), a kana name with its kanji in brackets and the given
  name after (かとう(加藤)　ゆうき), two katakana or kanji words after an age and a sex (72歳女性 ハネダ ミク; not two
  drugs: 70歳女性 アムロジピン ロキソニン).
- **Not names**: a role word in a name's place (担当医：当直医, 主治医：未定, 担当：同上, 主治医：交代予定; the last one
  was masked by master's staff-colon rule and is now dropped), a nationality or a home after a name (金さん、韓国籍、
  42歳), the 先生 of 鈴木一郎先生 never split, a patient number before a half-width kana name never part of it
  (12345 ﾔﾏﾀﾞ ﾀﾛｳ masks the name only).

**Known behaviour**: the brackets around a name's reading are masked with it (工藤（くどう）様 -> ○○○○○○○様); a
bracketed note directly after a name can be masked with it (妻・遠藤 由紀子（同居） loses （同居）; a bracket that
holds a role, a relative or a sex stays: 山田（主治医）); the guard's redaction may take the honorific with the name
(鈴木一郎先生 -> [NAME]) while the masker keeps it (○○○○先生). Master's rule masks the word after `Dr. ` (Dr. 回診 ->
Dr. ○○): not this card's.

Development figures: class fixtures (70 name lines, 3 limits) all names masked but the 3 limits, no counter-case
changed of 46, pinned outputs 10 of 10; the card's lines 11 of 75 and 2 of 30 missed as in round two; no ordinary
line changed of 266. Time 36.6 ms per 10 kB note (round two 31.1); 400 kB of distinct lines in 3.1 s.

**Fourth round** (the coordinator's run on 8bd8a99d: 1 of 214 names leaked, 0 of 150 no-name lines over-masked):
a katakana eponym, with or without ・, directly before a clinical head word is no name (ホーン・ヤール分度,
グラスゴー・コーマ・スケール, ブルンストローム・ステージ): the head words are data (`terms_after_name` in the cue file;
分度, 変法, 基準, 指数, 検査, ステージ and others added), and a katakana name with ・ before an honorific or an age
stays masked (ホーン・ヤール氏, マリア・サントス様). A word between a role with の and 先生 or 医師 is a name even when
the analyser reads it as a common noun (前医の平野先生の記載: 平野 is tagged "plain"); 前医の先生 (no name) stays.
Each has fixtures that fail on 8bd8a99d.

**Whole tree on fe5f1d4d** (the first whole-tree run with the analyser on) found what the card's own sets did not:
Chinese lines read as Japanese at a site that declares no note language (家屬林淑芬來電 lost 家屬, 值班護理師 became
○○○○師, 胸部 X 光未見明顯浸潤 lost 光未見明顯; the guard's false-positive rate on its zh-TW negatives rose past 5%),
呼吸音清 read as a surname and given name (音清), 一位老先生 masked as a name before 先生, 佐藤翔太検査結果 left
unmasked as an eponym, and a search over two Latin words that took 3.8 s on 30,000 letters with no space. Fixed:
- **Language**: at a site that declares nothing, a text of Han characters with no sign only Japanese writes (kana, a
  kanji form or word Chinese never uses: 歳, 様, 辺, 氏名, 旧姓) is read only when it holds no letter or word only
  Chinese writes (這, 們) and every one of its kanji is one of everyday Japanese (JIS X 0208 level 1, 2,965
  characters, from the standard library's EUC-JP codec). Chinese writes 顯, 屬, 來, 值 outside it. So 森本裕子 alone is
  still read; a kanji-only Japanese line with a kanji outside level 1 and no Japanese sign is not (a limit, stated).
- **Prefixes before a title** are no name (老先生, 一位老先生): `prefixes_before_title` in the cue file. Master's own
  rules still mask some of them (故先生 -> ○先生, 同先生 -> ○先生): not this card's.
- **A one-kanji surname glued to a common noun** is the end of that word, not a name (呼吸音清); a title, a label or
  an age beside it still marks a name.
- **A surname with its given name**, both in kanji, is a person even directly before a clinical head word
  (佐藤翔太検査結果); a surname alone there stays an eponym (橋本病の検査).
- The two-Latin-word search starts only at a word's start (linear).
- The planted-identifier harness (V-5) now masks 7 Japanese name forms it recorded as leaking (kanji, kanji with a
  space, katakana and hiragana with a space, kanji before 様, free or after a line break), for the masker and the
  tripwire: their 14 strict expected failures are removed.

**Sixth round** (the coordinator's run on 35c8936e: 0 of 214 names leaked, 0 of 150 no-name lines over-masked; at a
site that declares no note language, 2 of 20 fresh Traditional Chinese no-name lines lost words, 病人今日精神佳 ->
病人今日○○○ and 護理長交班 -> ○○長交班, and at a declared zh-TW site 担当医：当番医 -> 担当医：○○○). Kanji that both
languages share cannot be told apart line by line, so the site decides:
- **The site's language** (`phi_guard.site_notes_language`): the declared `settings.site.notes_language`; when it is
  `auto`, the language of the site's country, by the reading every other country behaviour uses
  (`tb_common.derived.country_of`, from `site.tz` and `site.locale`): the country layer's language (`P5
  report_language`) where the country has a layer, else the language of the site's locale. No country word in the
  guard; a broken layer counts as no known language. No set-up step writes `notes_language`: it is `auto` (the
  settings schema's default) unless a person sets it in `settings.yaml`, so an installed site resolves through its
  country.
- **No known language** (no declaration, no country): a note with no kana in it is read for names only beside a cue
  (a title or honorific after the word, a label or a role before it, from the cue data), never on the analyser's
  tags or an age alone.
- **A role word in a name's place is no name in any language setting** (担当医：当番医 stays at a zh-TW site too): the
  `not_a_name` filter runs on every text, the repeats only on Japanese.
- **At a site whose notes are Chinese (declared `zh-TW`, or `auto` at a site of the Taiwan reading), kanji-only
  Japanese names are not read**: bare 森本裕子, 宮本 修 医師, 百目鬼 透 氏, 野村 Dr., 担当PT：浅野 (7 of the
  coordinator's 214). This is intended: there the kanji are Chinese, and reading them as Japanese takes Chinese words
  (精神, 護理, 長庚) for names; the guard's Chinese rules cover the names of Chinese notes. A name with kana or a
  Japanese-only form beside it (森本さん, 森本様, 歳) is read at any site.
- Fixtures: 40 Traditional Chinese no-name lines of the lane's own (`eval/phi_synth/zh_tw_no_name_lines.json`) lose
  nothing at a Taiwan site and at a site of no country, but 2 that master's own Chinese rules change with the analyser
  off (家屬陳述 -> 家屬○○○, 照護理師訪視 -> 照護理師○○): strict expected failures, not this card's. On 35c8936e 7 of
  the 40 changed. The Japanese fixtures run at a Japan site, unchanged. The guard's false-positive measure on its
  negatives: 0 of 29 (zh-TW 0 of 8) before and after.

**Limit added**: a bare kanji-only name in a note with no kana at a site of no known language (森本裕子 alone).

**The three named limits** remain: a bare surname with no cue (浅野 alone), a hiragana surname the analyser does not
know by its reading (すどう alone), a romaji surname alone (Kimura alone).

## Consequences

- With the analyser on, names that the dictionary does not hold (rare surnames, invented given names), a romaji name
  and a name in a kanji-only text are still missed; addresses without 市, pension and passport numbers remain gaps for
  rules.
- The numbers are synthetic, written by the lane that wrote the rule; a site's own sample is the real test.
