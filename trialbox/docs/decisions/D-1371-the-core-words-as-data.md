# D-1371 The twenty core words as data; a catalogue check refuses other spellings (9k-16)

- **Task:** lane K, plan 10 track F (carried 9k-16 of plan 9 revision 2; review 09 DS-16: "Term list of the twenty
  words (1.6) as data, and a catalogue check that refuses the non-preferred spellings per language"; proved by "zero
  refused spellings"). Decisions 35 and 37 (plan 10 section 8.1). · **Date:** 2026-11-19
- **Decision:**
  - **The data:** `services/console/core_words.yaml`, beside the console's catalogues: twenty words, each with an id,
    the concept, `read_by_native_reader`, a note, and per language (en, ja, zh-TW) the one `spelling`, the `refused`
    spellings and the `allowed` phrases (a longer, correct phrase that contains a refused spelling: 預篩檢查 is
    預篩 + 檢查, not 篩檢). Plain YAML, no anchors or tags: 10F-5 (the site terms layer, a local synonym shown
    beside a core word, never replacing it) reads it.
  - **Where the words come from:** the twenty concepts and their spellings are review 09's proposal (section 1.6),
    which itself says it is a proposal for the native readers, not a ruling. Decision 37: the zh-TW coordinator word
    is the owner's to choose; until he does, 研究護理師 (in use) stays and the second word 研究協調員 is refused.
    Decision 38: "patient code" (患者コード, 病人代碼) is the one word for the pseudonym on clinical pages.
    **No row has been read by a native reader** (decision 35, reopened: the owner for zh-TW, the site's coordinator
    or the Japanese support partner for ja); every row says `read_by_native_reader: false`. Nothing waits for that
    reading: a reader's choice changes a row, and the check then holds the catalogues to it.
  - **What is refused:** a row refuses a spelling only where writing the one spelling in its place is a pure
    substitution in every catalogue string today. Where the other spellings carry another meaning (a clinic visit;
    確認 as "check"; 選定 as "selection"; the e-mail subject) or where 10C-6 decides the Japanese word by study kind
    (治験参加者, 研究責任者, 責任医師, 依頼者), the row refuses nothing and its note says why. "Pseudonym" (en) and
    仮名 (ja) are not refused: decision 38 is for clinical pages, and the audit, break-glass and steward pages name
    the 32-character pseudonym itself; a catalogue string does not say which page shows it. Refused today: ja
    候補患者, スポンサー, 責任分担表 / 分担表, データスチュワード, フィージビリティ; zh-TW 候選病人, 病人代號, 研究協調員,
    篩檢, 授權表 / 授權紀錄, 委託者; en sub-I, enroll / enrolls / enrollment(s).
  - **The check:** `tools/core_words.py` checks the file's shape (twenty words, three languages, ids unique, no word
    refusing its own spelling or a spelling inside another word's, an allowed phrase holding a refused spelling) and
    reads every definition `tools.text_keys` reads (the loser of an override included). en matches whole words,
    ignoring case; ja and zh-TW match anywhere. The word's own spelling and its allowed phrases are masked first, so
    授權紀錄 inside 授權紀錄表 is not a finding; the longest refused spelling is looked for first. A finding names the
    language, key, place, the spelling found and the one to write. `python -m tools.text_keys` (`make lint`) reports
    its findings as problems (two added lines); `python -m tools.core_words` runs it alone.
  - **The catalogues:** 44 strings in 17 modules changed by spelling substitution only, no rewording (the pull
    request lists them by key), and one refusal message of `services/console/refusals.py` ("請選擇是否與已簽署的授權紀錄表一致"), which the
    reader of `tools.text_keys` does not read, changed to match `team.log.result.match`.
- **Not in this card:** the readers' reading (decision 35); the ja term set per study kind (10C-6); the site terms
  layer (10F-5); `refusals.py`'s table and the e2e walk plans' step texts are not read by the check.
- **Held by:** `tests/unit/test_core_words.py`; `tests/unit/test_text_keys.py` (`problems()` is empty).
