# A Japanese morphological analyser for the privacy guard: assessment and prototype (card 10C-1b)

*Written 2026-11-19 by lane J for card 10C-1b (plan 10, `docs/plan/47-plan-10-2026-11-18.md`, Track C; follow-up of
10C-1, PR #1091). Decision D-1235, proposed and awaiting the owner. Every package fact below was read from the
Python package index's JSON (`https://pypi.org/pypi/<name>/json`) or the project's own files on 2026-11-19, and the
sizes and figures were measured in this card's scratch environment on that day. GitHub's API was not reachable from
the container, so a repository's last commit could not be read: maintenance is judged by the dates of releases on
the package index. Anything not verified is said so in the last section.*

## Decision for the owner

**Add SudachiPy 0.7.0 with SudachiDict-small 20261015 (both Apache-2.0; the dictionary holds UniDic, BSD-3-Clause)
as an optional extra of the guard?** yes / no

- With it, the guard masks **58 of 75** unlabelled Japanese names of the card's own lines (rules alone: 0 of 75) and
  **26 of 30** of a held-out set written before the rule was tuned (rules alone: 0 of 30); it masks **no** ordinary
  line of the 161 committed ordinary probe lines, the 75 tempting lines or the 30 held-out ones.
- Cost: about **115 MB** more in each image that installs it (`trialbox-py`, and the demo image), 44 MB to
  download; about **9 ms per 10 kB note** on one core of this container; no compiler, no network after install, no
  neural model.
- Runner-up: the same engine with **SudachiDict-core 20261015** (193 MB): two more names on the card's lines (60 of
  75), the same on the held-out set, 83 MB more, and its dictionary holds a part of NEologd, whose sources need care.

## What the rules cannot do

The rules of 10C-1 key on a label, an honorific, a title or a listed surname. A name with none of these (見本太郎は
本日来院, 68歳男性 ミホン タロウ) looks like any other noun. Lane J's independent measurement found about a quarter of
identifiers in hard Japanese text still missed (44 of 169); the committed probe file carries the classes as strict
known gaps (`eval/phi_synth/ja_guard_probes.json`, `known_gaps`). A morphological analyser splits the text into words
and its dictionary marks which words are surnames (姓), given names (名) or other person names (人名).

## The candidates

| Candidate | Code licence | Dictionary and its licence | Installed size (code + dictionary) | Wheels, Linux x86-64 and aarch64, Python 3.10 to 3.12 | Last release; state | Native or pure | Person names tagged | Neural model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **SudachiPy** + SudachiDict-**small** | Apache-2.0 | Apache-2.0; its words are UniDic's (BSD-3-Clause, UniDic Consortium; notice in SudachiDict's `LEGAL`) | 4.9 + 110 MB | yes: one abi3 wheel per architecture (cp310-abi3, manylinux_2_28); dictionary py3-none-any | 0.7.0 on 2026-09-24; dictionary 20261015 on 2026-10-15; releases every two to five months | Rust core | 名詞-固有名詞-人名-姓 / 名 / 一般 | no |
| SudachiPy + SudachiDict-**core** | Apache-2.0 | Apache-2.0; UniDic part (BSD-3-Clause) and **a part of NEologd** (Apache-2.0; NEologd's own notice says it uses the Hatena keyword list, whose copyright is Hatena's, under Hatena's terms) | 4.9 + 193 MB | yes (as above) | as above | Rust core | as above | no |
| SudachiPy + SudachiDict-**full** | Apache-2.0 | as core, more proper nouns | 4.9 + 316 MB | **no wheel**: an sdist that downloads the dictionary from a CDN while it builds; the images install `--only-binary=:all:` and could not take it | as above | Rust core | as above | no |
| fugashi + **unidic-lite** (MeCab inside) | MIT (fugashi), BSD-3-Clause (the bundled MeCab, chosen of its GPL/LGPL/BSD) | UniDic 2.1.2 of 2013, BSD-3-Clause; package code MIT or WTFPL | 2.2 + 249 MB | fugashi yes (cp310, cp311, cp312, both); **unidic-lite sdist only** (pure data, built without a compiler, but not a wheel) | fugashi 1.5.2 on 2025-10-24; unidic-lite 1.0.8 on 2021-01-25 | C++ (MeCab) | 名詞-固有名詞-人名-姓 / 名 / 一般 | no |
| fugashi + **unidic** (full UniDic 3.1) | as above | UniDic 3.1, BSD-3-Clause (offered also under GPL or LGPL) | 2.2 + about 770 MB (its README) | the package is an sdist and the dictionary is **downloaded after install** (`python -m unidic download`): not offline | 1.1.0 on 2021-10-10 | C++ | as above | no |
| mecab-python3 or fugashi + **ipadic** | BSD (mecab-python3), MIT (fugashi) | IPADIC 2.7.0 of 2007: NAIST's licence over ICOT free software, permissive with a no-warranty clause that must travel with it; **the PyPI package carries no licence file or field** | 1.8 + 51 MB | binding yes; **ipadic sdist only** | mecab-python3 1.0.12 on 2025-11-25; ipadic 1.0.0 on 2020-07-20 | C++ | 名詞-固有名詞-人名-姓 / 名 / 一般 | no |
| MeCab + **NEologd** (mecab-ipadic-NEologd) | as MeCab | Apache-2.0, built from the Hatena keyword list (Hatena's copyright, used under its terms), Japan Post's postcode data and a station list | not measured; its README asks 2 GB of RAM to build and gives a 1.2 GB binary | **not on the package index**: built by a shell script from GitHub with MeCab's tools | not verified (GitHub not reachable) | C++ | as IPADIC, many more proper nouns | no |
| **Janome** | Apache-2.0 | IPADIC 2.7.0 bundled (NAIST/ICOT notice in its `NOTICE.txt`) | 113 MB | py3-none-any; **0.5.2 needs Python 3.11 or later** (0.5.0 runs on 3.10) | 0.5.2 on 2026-11-10 | pure Python | IPADIC's | no |
| **GiNZA** (ginza + ja-ginza) | MIT | SudachiDict-core (as above) and a trained spaCy pipeline | not installed (ja-ginza wheel 59 MB, plus spaCy and thinc) | wheels yes | ginza 5.3.1 on 2026-11-12; **requires SudachiPy below 0.7.0**, so the old dictionary format, not the current dictionaries | Python on spaCy | named-entity model (Person label) | **yes**: ja-ginza is a trained statistical model, ja-ginza-electra a transformer fetched at first use; the owner's rules treat it as a model download, so not installed |
| **Lindera** (lindera 6.2.0) | MIT | IPADIC, UniDic or others, fetched separately from the project's GitHub releases (`lindera download ipadic`) | 2.4 MB + dictionary | abi3 wheels both architectures; dictionaries not on the package index | 6.2.0 on 2026-09-26 | Rust | the chosen dictionary's | no |
| **Vibrato** 0.2.3 | MIT or Apache-2.0 | dictionaries from the project's GitHub releases | not measured | **x86-64 only: no aarch64 wheel** | 0.2.3 on 2026-05-30 | Rust | the chosen dictionary's | no |
| **Kuromoji** (Lucene `lucene-analysis-kuromoji` 10.4.0) | Apache-2.0 | IPADIC built in | not measured | a Java library: the guard is Python; only the JVM image could run it, behind a service call | 10.4.0 on 2026-02-25 (Maven Central) | Java | IPADIC's | no |
| nagisa 0.3.2 | MIT | its own trained tagger | not installed | wheels yes | 0.3.2 on 2026-11-14 | DyNet | no name class | **yes**: a BiLSTM model; not installed |

Sources read on 2026-11-19: `https://pypi.org/pypi/{sudachipy,sudachidict-small,sudachidict-core,sudachidict-full,
fugashi,unidic-lite,unidic,mecab-python3,ipadic,janome,ginza,ja-ginza,ja-ginza-electra,lindera,vibrato,nagisa}/json`;
`https://raw.githubusercontent.com/WorksApplications/SudachiDict/develop/{README.md,LEGAL,LICENSE-2.0.txt}`;
`https://raw.githubusercontent.com/WorksApplications/sudachi.rs/develop/{README.md,LICENSE}`;
`https://raw.githubusercontent.com/polm/fugashi/main/{README.md,LICENSE,LICENSE.mecab}`;
`https://raw.githubusercontent.com/polm/unidic-lite/master/{README.md,LICENSE}`;
`https://raw.githubusercontent.com/polm/unidic-py/master/README.md`;
`https://raw.githubusercontent.com/neologd/mecab-ipadic-neologd/master/{README.md,COPYING}`;
`https://raw.githubusercontent.com/mocobeta/janome/master/NOTICE.txt`;
`https://raw.githubusercontent.com/megagonlabs/ginza/develop/README.md`;
`https://raw.githubusercontent.com/SamuraiT/mecab-python3/master/README.md`;
`https://raw.githubusercontent.com/lindera/lindera/main/README.md`;
`https://raw.githubusercontent.com/daac-tools/vibrato/main/README.md`;
`https://search.maven.org/solrsearch/select?q=g:org.apache.lucene+AND+a:lucene-analysis-kuromoji`.
The sizes are `du` of the installed folders in a Python 3.12 environment; the licence files are those the installed
wheels carry (`*.dist-info/licenses`).

**What the analysers do with the hard words** (read from their tags on the card's lines): every one tags 橋本 in
橋本病 as a place or a surname and 高安 in 高安動脈炎 as a surname; SudachiDict-core and -full join 川崎病 and
(full) 高安動脈炎 into one common noun; Sudachi's dictionaries and unidic-lite tag パーキンソン as a person name, and
Sudachi's also クッシング and コール. So no analyser can be trusted alone with eponyms: the rule below is what keeps them. On
katakana, Sudachi tags a common given name (タロウ, ハナコ, ケイコ) as 名 and an unknown surname (ミホン, ミヤサカ) as
an ordinary noun, which the rule pairs; IPADIC splits unknown katakana into pieces (ミ ホン) and tags almost no
katakana name, and Janome tags タロウ as an organisation. On rare kanji names (四十物, 勅使河原, 小鳥遊) and invented
given names (架空子, 模擬也) every dictionary fails: they are not in it.

## The measurement

Installed for the measurement only, in a scratch environment outside the repository and its lock (a `uv venv` with
Python 3.12.3), from the public package index with `uv pip install`: sudachipy 0.7.0, sudachidict-small 20261015,
sudachidict-core 20261015, sudachidict-full 20261015 (built from its sdist, which downloaded the dictionary),
fugashi 1.5.2, unidic-lite 1.0.8, mecab-python3 1.0.12, ipadic 1.0.0, janome 0.5.2. Nothing else; no model. The
harness `tools/ja_name_eval.py` ran with the repository's own environment and that folder on the import path.

The sets: the committed probe file (`masked`: 120 lines, 138 identifiers; `known_gaps.missed`: 9 lines; `unchanged`:
161 ordinary lines, 152 of them Chinese or Japanese (the card's brief says 142: the file holds 161); and
`known_gaps.overmasked`: 2), the card's 150 new lines (`eval/phi_synth/ja_name_lines.json`: 75 names, 75 tempting
ordinary lines, committed in 8eb05e15 before the harness first ran) and a held-out set of 60
(`eval/phi_synth/ja_name_lines_holdout.json`, committed in 8fe7596d after the first run and before the rule was
tuned; measured once). An identifier counts as missed when the masker or the guard leaves any character of it (the
test of `tests/unit/test_phi_guard_ja.py`); a line counts as wrongly masked when the masker changes it or the guard
finds anything in it.

**Final rule** (the rule of `tb_common/ja_names.py` as committed):

| Configuration | Probe ids missed | Known-gap ids missed | New ids missed | Held-out ids missed | Probe ordinary changed | Known-gap ordinary changed | New ordinary changed | Held-out ordinary changed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rules alone | 0 / 138 | 9 / 9 | 75 / 75 | 30 / 30 | 0 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| **+ Sudachi small (recommended)** | 0 / 138 | 8 / 9 | 17 / 75 | 4 / 30 | 0 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| + Sudachi core (runner-up) | 0 / 138 | 8 / 9 | 15 / 75 | 4 / 30 | 0 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| + Sudachi full | 0 / 138 | 8 / 9 | 15 / 75 | 4 / 30 | 0 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| + MeCab, unidic-lite | 0 / 138 | 9 / 9 | 29 / 75 | 9 / 30 | 1 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| + MeCab, IPADIC | 0 / 138 | 8 / 9 | 33 / 75 | 9 / 30 | 0 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| + Janome | 0 / 138 | 8 / 9 | 29 / 75 | 8 / 30 | 0 / 161 | 2 / 2 | 0 / 75 | 0 / 30 |
| Sudachi small, every tagged word, no rule | 0 / 138 | 8 / 9 | 44 / 75 | 16 / 30 | 17 / 161 | 2 / 2 | 20 / 75 | 11 / 30 |
| Sudachi core, every tagged word, no rule | 0 / 138 | 8 / 9 | 43 / 75 | 16 / 30 | 15 / 161 | 2 / 2 | 19 / 75 | 11 / 30 |

The known-gap row Sudachi masks is 68歳男性 ミホン タロウ; the two known-gap ordinary lines are the rules' own
over-masks and do not change. The other eight known gaps stay: 見本太郎 written with an ordinary word as a surname
(Sudachi tags 太郎 after 見本 as an ordinary noun), 患者：見本太郎 and 氏名：見本 / 太郎 (no kana and no 歳 in the
text, so the rule does not read it as Japanese), a romaji name, two addresses, a pension and a passport number (no
analyser's job).

**First run** (the rule as first written, before it reused the guard's protections; every figure of the
analysers is also in the harness's JSON): Sudachi small missed 15 of 75 new names and changed 11 of 161 probe
ordinary lines and 4 of 75 new ones; core 13, 11 and 5; full 13, 11 and 1; unidic-lite 27, 10 and 4; IPADIC 31, 7
and 7; Janome 27, 7 and 7. The changed lines were those 10C-1 had already protected (佐藤錦, 山田錦, 松本 歯科,
看護師 小林製薬, 福田分類, 患者：独歩, Dr. コール, クッシング様, 洞調律) and eponyms the first rule's "other half of
the name" swallowed (高安動脈炎, 太田母斑, 森田療法, ギラン・バレー症候群, 原田病, 菊池病, 木村病, 瀬川病). The rule
was then tuned on these sets, which is why the held-out set exists: on it the tuned rule changed no line and missed 4
of 30 names with Sudachi.

**Time** (one core of an Intel Xeon at 2.10 GHz in this container; a 10,000-byte note made of the sets' lines,
4,155 characters; median of seven runs; the analyser's own words and the rule only, on top of the rules' 19 to
20 ms for the same note):

| Analyser | ms per 10 kB note | Load, first call | Resident memory added after one note |
| --- | --- | --- | --- |
| Sudachi small | 8.6 | 0.02 s | 32 MB |
| Sudachi core | 10.3 | 0.04 s | 78 MB |
| Sudachi full | 8.0 | 0.05 s | 128 MB |
| MeCab, unidic-lite | 11.0 | 0.01 s | 4 MB |
| MeCab, IPADIC | 9.0 | 0.00 s | 4 MB |
| Janome | 85.6 | 0.16 s | 75 MB |

Sudachi maps its dictionary from disk, so the load is fast and memory grows with the pages a note touches.

## The combination rule

The analyser proposes; a span is masked only when it is a person name by the analyser, is not inside a medical or
place term, and passes the guard's own protections (`tb_common/ja_names.py`, `name_spans`):

1. **Propose.** A run of words tagged 姓, 名 or 人名, joined directly or across one space or a middle dot; then one
   more word as the other half of the name: before a given name, a noun of one to four kanji or two to eight
   katakana (見本 before 太郎, ミホン before タロウ); after a surname, a katakana word or a kanji word of the guard's
   given-name class (`phi_guard._JA_GIVEN_KANJI`: never 錦, 市, 科, 製薬 ...). A kanji given name outside that class
   is no name (山田錦, 佐藤錦).
2. **Never alone.** A surname alone (松本, 長崎, 岡山 are places too), a katakana name word alone (ミヤ, コール,
   パーキンソン) and anything of one character are dropped; a kanji given name or whole name of two characters or
   more may stand alone.
3. **Not a term.** A span followed (directly, after one space, or after the rest of a katakana compound) by a word
   of a disease, sign, procedure, scale, institution or place (病, 症候群, 炎, 型, 分類, 法, 手術, 反射, 徴候, 母斑,
   療法, 病院, 医院, 歯科, 内科, 科, 市, 区, 調律, 様の ...) is an eponym or a place; an added word that is itself
   such a word, or ends as a disease does, is not taken.
4. **The guard's own words.** A span that is, or starts with, a word the rules already say is no name: a relative,
   a role, a description of the patient (`phi_guard._JA_RELATIVES`, `_JA_NOT_A_NAME_VALUE`, `_JA_LIKE`); a span
   after Dr. (the guard reads none there: Dr. 指示, Dr. コール).
5. **Japanese only.** A text with no kana and no 歳 is not read (Chinese writes 歲 or 岁): the guard also serves
   Taiwanese notes, where a Japanese dictionary would tag Chinese words as names.

Its effect, Sudachi small: with no rule (every tagged word masked) 17 of 161 probe ordinary lines, 20 of 75 new and
11 of 30 held-out ordinary lines are changed and 44 of 75 names are still missed (a tag alone marks only half a
name); with the rule, 0, 0 and 0 lines changed and 17 of 75 names missed.

## What landing the dependency will need

None of this is in this pull request; each step needs the owner's yes first.

- **Packages** (exact): `sudachipy==0.7.0`, `sudachidict-small==20261015`. As an optional extra (`[project.optional-
  dependencies] ja-names = [...]` in `pyproject.toml`), then `make lock` (uv.lock), the export into
  `deploy/requirements.lock` (or a separate image lock), and `tools/supply_chain/pip-audit.lock` unchanged.
- **Images**: `trialbox-py` (`deploy/docker/python.Dockerfile`) and the demo image (`demo/Dockerfile`) install the
  lock with `--only-binary=:all:`: both packages are wheels (sudachipy abi3 manylinux_2_28 for x86-64 and aarch64;
  the dictionary pure data), so no compiler and no network at build beyond the index. Added size: about **115 MB
  installed per image** (4.9 + 110 MB), **44 MB** compressed download (1.7 + 42.5 MB). The embed, backup, JVM and
  database images are unchanged. The base image's glibc must be 2.28 or later (python:3.12-slim is).
- **Licence register** (`docs/licences/register.csv`): one row per package (kind `software`; or the integrator's
  choice of kind for a dictionary): SudachiPy, Apache-2.0, holder Works Applications; SudachiDict-small, Apache-2.0
  with the UniDic BSD-3-Clause notice. The wheel of SudachiDict-small carries only the Apache licence text, not the
  `LEGAL` file with UniDic's notice, so `NOTICE` must reproduce that notice (BSD-3-Clause's condition for
  redistribution in binary form). `python -m tools.licence_register --check` reads `software` rows against
  `deploy/docker/backup.Dockerfile` pins today: a Python package's row may need the check widened (the integrator's
  call).
- **SBOM and licence gate**: both packages declare Apache-2.0 in their metadata (SudachiPy as `License-Expression`,
  SudachiDict as `License`); no copyleft flag is expected. **pip-audit**: no advisory was looked up (the box is
  offline; `make pip-audit` runs on the build side).
- **Allow-list** (`deploy/supply-chain-allowlist.yaml`): no entry is expected to be needed. If a gate flags either
  package, an entry needs the owner's yes and the integrator's hand; this card did not touch the file.
- **Turning it on**: one call at the start of each process that masks or guards Japanese text,
  `ja_names.enable(ja_names.analyser("sudachi-small"))`, at a Japanese site only; `NOTE_MASK_VERSION` goes to 8
  (the lake's masked notes are re-masked as with every rule change). The strict known-gap test row 68歳男性 ミホン
  タロウ then passes and moves to `masked`.

## What lands in this pull request

- `libs/tb_common/phi_guard.py`: `NAME_RECOGNISERS`, an empty list, read by `note_spans` (and so by the guard and
  `scan`). Nothing in the product adds to it.
- `libs/tb_common/ja_names.py`: the analyser loaders (imported only when called), the combination rule,
  `enable` and `disable`. Nothing imports it but its test and the harness.
- `tools/ja_name_eval.py`: the harness; prints that it skipped and exits 0 when no analyser is installed.
- `eval/phi_synth/ja_name_lines.json` (150 lines) and `eval/phi_synth/ja_name_lines_holdout.json` (60 lines).
- `tests/unit/test_ja_names.py`: nothing registered and no analyser imported (in a fresh process); a registered
  recogniser reaches the masker, the guard and the scan and is removed cleanly; the rule on a stub analyser (no
  package needed); the lines well formed and the ordinary ones untouched by the rules; the harness skips; the
  recommended analyser's figures as ceilings where it is installed.

**Master's behaviour unchanged**: on 1,315 texts (every line of the probe file, the card's 210 lines, the 120
synthetic notes whole and line by line) the masker's output, `note_spans`, `scan` (hit and findings), the guard's
redaction, detection and tripwire kinds hash to the same digest on master (a44a39da) and on this branch
(`ebf9289e…`), and none of sudachipy, fugashi or janome is in `sys.modules` after the run.

## Not verified

- A run on aarch64: the wheels are listed for it on the package index; nothing was run on an Arm machine.
- Python 3.10 and 3.11: listed wheels only (the product runs 3.12, where everything was measured).
- Maintenance from the projects' repositories (GitHub's API was not reachable): release dates only. NEologd's last
  update and size: not read.
- The terms of the Hatena keyword list behind NEologd (and so behind SudachiDict-core and -full): not read; the
  recommendation avoids them by taking the small dictionary.
- pip-audit and the image gates on the new packages; the image size measured on a built image (the figures are the
  installed folders).
- GiNZA, Lindera, Vibrato, Kuromoji and nagisa: not installed or not measured (a model, a separate dictionary
  download, no aarch64 wheel, Java, a model).
- Real clinical text: every line is synthetic and written by the same lane that wrote the rule; a site's own sample
  would be the real test. Names the dictionary does not hold (rare surnames, invented given names) are missed by
  every analyser.
