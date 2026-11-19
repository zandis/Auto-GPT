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
    篩檢, 授權表 / 授權紀錄, 委託者, 資料管理人; en sub-I, enroll / enrolls / enrollment(s). ja スチュワード alone (the
    short form beside データ管理責任者 in the break-glass and data-operations texts) is refused with データスチュワード.
  - **The zh-TW steward:** review 09 proposed 資料管理人, but the catalogues wrote 資料管理員 on 17 lines
    against 5. The chosen spelling is the majority form 資料管理員; 資料管理人 is refused and its 5 strings changed.
  - **Allowed ordinary words:** zh-TW 受委託者 (a contractor), ja 役割分担表 (a table of who does what) and zh-TW
    癌症篩檢 (cancer screening, the ordinary Taiwanese word) hold a refused spelling and are not findings.
  - **The check:** `tools/core_words.py` checks the file's shape (twenty words, three languages, ids unique, no word
    refusing its own spelling or a spelling inside another word's, an allowed phrase holding a refused spelling) and
    reads every definition `tools.text_keys` reads (the loser of an override included) and, from the source with
    `ast` only, the catalogues of user-visible text outside the console's i18n modules (`SERVICE_CATALOGUES`): the
    refusal sentences (`services/console/refusals.py`), the job mails with the report and PDF titles
    (`services/orchestrator/i18n.py`), the eligibility sheet (`services/orchestrator/reports/case_html.py`), the
    opportunity board (`services/opportunity_hub/dashboard.py`) and the site-setup sheet's help
    (`services/sitesetup/help.py`). Every text and spelling is folded to NFKC first (full-width and half-width forms
    are the plain ones). en matches whole words, ignoring case, a plural ending included and a hyphen a boundary
    (Sub-Is, re-enroll, enrollment-based are found); ja and zh-TW match anywhere. The word's own spelling and its allowed phrases are masked first, so
    授權紀錄 inside 授權紀錄表 is not a finding; the longest refused spelling is looked for first. A finding names the
    language, key, place, the spelling found and the one to write. `python -m tools.text_keys` (`make lint`) reports
    its findings as problems (two added lines); `python -m tools.core_words` runs it alone. An unreadable, empty or
    malformed data file, or a `refused:` / `allowed:` that is not a list, is one plain problem line and a non-zero
    exit, never a traceback.
  - **The catalogues:** 44 strings in 17 modules changed by spelling substitution only, no rewording (the pull
    request lists them by key), and one refusal message of `services/console/refusals.py` ("請選擇是否與已簽署的授權紀錄表一致"), which the
    reader of `tools.text_keys` does not read, changed to match `team.log.result.match`. With the wider check: the
    four Japanese feasibility texts of the job mail and the PDF title (フィージビリティ → 実施可能性), five ja
    スチュワード → データ管理責任者, five zh-TW 資料管理人 → 資料管理員, and one string master added
    (`today.line.delegation`). Three zh-TW sentences that would have said 授權紀錄表 twice (`team.log.check_due`,
    `wb.task.delegation`, `today.line.delegation`) say "the signed one" as 已簽署的版本, as en and ja do ("the
    office's signed log", 署名済みリスト). The role guides (`docs/guides`) and the new-study walk pages
    (`docs/handover/new-study-walk.*.md`) are regenerated from the catalogues.
- **Not in this card:** the readers' reading (decision 35); the ja term set per study kind (10C-6); the site terms
  layer (10F-5).
- **Not checked, and why:** the e2e walk plans' step texts (test prose, still saying データスチュワード); the command
  palette's search words (`services/console/command.py`: what a user may type, refused spellings on purpose); the
  stub model's canned answers (`services/llm_stub`: test data, never shown); the detection lists
  (`libs/tb_common/wording.py`, `libs/tb_common/phi_guard.py`, `services/guard`: words looked for, not shown).
  Simplified-Chinese characters are not checked: a zh-TW text written in simplified characters (候选病人) is not
  a finding.
- **Not yet in use:** four chosen spellings are used by no catalogue string (counted over every text the check
  reads, on this card's merge with master): en "Enrol" (the texts say "enrolled"), ja 患者コード, zh-TW 確認知悉 and
  zh-TW 納入排除條件. The review named a fifth, en "Study criteria"; two strings master added
  (`today.next.approve.*`) now use it. Review 09's ja coordinator is CRC（治験コーディネーター）; the file has CRC.
  10F-5 and the readers should know these are proposals only.
- **Not read:** no native reader has read the 44 substitutions of this card, nor the later ones above.
- **Held by:** `tests/unit/test_core_words.py`; `tests/unit/test_text_keys.py` (`problems()` is empty).
