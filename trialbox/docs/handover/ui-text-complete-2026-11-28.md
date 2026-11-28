# UITEXT: Japanese and Chinese UI text completeness

**Reader:** the people who build TrialBox: the lane H lead and the lanes whose files are touched (the egress page's
lane, the console's text). One language.

- **Card:** UITEXT (lane H)
- **Date:** 2026-11-28
- **Findings:** [`ui-text-complete-2026-11-28/findings.json`](ui-text-complete-2026-11-28/findings.json)
  (UITEXT-01 to UITEXT-03)
- **Tests:** `tests/console/test_page_text_complete.py`

## What was already there

`tools.text_keys` holds the catalogues apart and checks every literal key; in the test process a key no catalogue has
raises. What neither sees is what a page shows: a word a template or Python writes itself, and a text a page builds
from something that is not in a catalogue.

## What the new test reads

- **Rendered pages.** Every GET page each role can open (the pages of `test_wording_walk`), in ja and zh-TW. A word
  shaped like a catalogue key whose first part the catalogue uses is a raw key; a text equal to a catalogue key's
  English words, where that key has other words in the page's language, is English left in place. Left out, each
  with its reason in the test: route ids and feature-flag names (technical ids), file names, text in code type, an
  element marked `lang="en"` (an original quoted beside its translation), an option whose words are its value, and a
  flag's own `on` and `off`.
- **Templates.** Every template, outside its Jinja tags, comments, script, style and code elements: the text and the
  `title`, `placeholder`, `aria-label` and `alt` words may hold no English word. A short list of technical texts is
  allowed (a key name, a sample value). The rule is itself tested with planted words.

## What was found and changed

- UITEXT-01: the rule table of `/admin/egress` came from `egress_edge.doctor_checks` in English. `doctor_facts` now
  gives each row as a kind and its arguments, `doctor_text` puts words to it, and the page takes the words from the
  catalogue (`egress.rule.*`, `egress.state.*`). `doctor_checks` keeps its English output.
- UITEXT-02: `egress_page.events` now reads the whole detail of an egress line (`shown=False`), as the published page
  does for the feeds; route, result and reason are the line's own fields and name no one.
- UITEXT-03 (not changed, open for a ruling): the menu's `aria-label` is the English `main` in every language. Four
  console tests find the menu by `<nav aria-label="main"` on ja and zh-TW pages too (`test_plain_menu`,
  `test_entry_pages`, `test_data_pages`, and `test_role_pages`); making the label a key changes
  what they match. The template rule lists `main` as allowed until that ruling.

## Terms a native reader should check

ja: 問題なし / 要確認 / 要対応 (the three states of a rule row), 伏せ字 (masked), 持ち出し (leaving the
box), 監視 (the tripwire), ゲートウェイ. zh-TW: 正常 / 請確認 / 需處理, 遮蔽 (masked), 外送 (leaving the box),
監控 (the tripwire), 閘道 (gateway).

## Not covered

States a page shows only with data the walk does not make; text a service writes into a file or a mail; the walk's
pages are those it can open with its fixed ids.
