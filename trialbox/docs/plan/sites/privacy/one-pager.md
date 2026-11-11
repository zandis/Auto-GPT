# The one-pager (システムの一枚説明 / 系統一頁說明)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-06 |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| For | patients' representatives on a committee, the privacy office, a department head: "what this system does with charts" on one page |
| Made by | `tools/onepager.py`, from the site's `deploy/settings.yaml` and the intended-use statement of `libs/tb_common/wording.py` |
| Tested by | `tests/unit/test_onepager.py` (renders in en, ja and zh-TW from the synthetic site's settings) |

The page is not kept here as text: it is rendered from each site's settings, so the site name, the data source, the
retention periods, the small-cell threshold and whether any cloud model is allowed are the box's own values.

    python -m tools.onepager --settings deploy/settings.yaml --lang ja --out onepager.ja.md
    python -m tools.onepager --settings deploy/settings.yaml --lang zh-TW --out onepager.zh-TW.md
    python -m tools.onepager --settings deploy/settings.example.yaml --lang en   # the synthetic site, to stdout

The page carries: the intended-use statement in the reader's language; what is read and from where; where it is
processed; who sees what; what leaves the hospital; how long each kind of data is kept; how to opt out; whom to ask.
It uses none of the verdict words of TB-IU-01 §2. A rendered page names the site, so a site's copy is kept by the
site, not in this repository.
