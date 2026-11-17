"""Strings of J-3 (D-1222), the phone-first layout behind the flag ``layout.phone_first``: the week page's one "Study"
fold, the menu's groups under "More", and the labels of a worklist row shown as a card. Merged by ``console.phone``
(en, ja, zh-TW); every language has every key."""

from __future__ import annotations

EN: dict[str, str] = {
    "pf.study": "Study: steps, team and links",
    "nav.grp.site": "Site",
    "nav.grp.study": "{rs} · study pages",
    "nav.grp.registers": "Registers",
    "nav.grp.box": "Administration",
    "nav.grp.lists": "Lists and requests",
    "nav.grp.settings": "Settings",
}

JA: dict[str, str] = {
    "pf.study": "試験：手順・チーム・リンク",
    "nav.grp.site": "施設",
    "nav.grp.study": "{rs} · 試験のページ",
    "nav.grp.registers": "台帳",
    "nav.grp.box": "管理",
    "nav.grp.lists": "一覧とリクエスト",
    "nav.grp.settings": "設定",
}

ZH: dict[str, str] = {
    "pf.study": "試驗：步驟、團隊與連結",
    "nav.grp.site": "院所",
    "nav.grp.study": "{rs} · 試驗頁面",
    "nav.grp.registers": "名冊",
    "nav.grp.box": "管理",
    "nav.grp.lists": "清單與請求",
    "nav.grp.settings": "設定",
}
