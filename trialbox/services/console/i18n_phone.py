# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of J-3 (D-1222): the phone-first layout behind the flag ``layout.phone_first`` (the week page's one "Study"
fold, the menu's groups under "More"), the page for a link that came from another site, and the notice of a form
restored after a session ended. Merged by ``console.phone`` (en, ja, zh-TW); every language has every key."""

from __future__ import annotations

EN: dict[str, str] = {
    "pf.study": "Study: steps, team and links",
    "pf.study.attn": "Study: steps, team and links. Waiting for you: {n}.",
    "nav.grp.site": "Site",
    "nav.grp.study": "{rs} · study pages",
    "nav.grp.registers": "Registers",
    "nav.grp.box": "Administration",
    "nav.grp.lists": "Lists and requests",
    "nav.grp.settings": "Settings",
    "link.title": "Open this page in TrialBox",
    "link.lead": "You followed a link from another site to this page of TrialBox: {page}",
    "link.file": "That link opens a file or starts an action. TrialBox does that only from its own pages, so Continue opens your home page.",
    "link.why": "TrialBox asks for this tap so that a page on another site cannot act in your name.",
    "link.continue": "Continue",
    "form.restored": "Fields restored from before your session ended: {n}. Check them, then save.",
    "form.discard": "Discard",
}

JA: dict[str, str] = {
    "pf.study": "試験：手順・チーム・リンク",
    "pf.study.attn": "試験：手順・チーム・リンク。うち {n} 件はあなたの対応が必要です。",
    "nav.grp.site": "施設",
    "nav.grp.study": "{rs} · 試験のページ",
    "nav.grp.registers": "台帳",
    "nav.grp.box": "管理",
    "nav.grp.lists": "一覧とリクエスト",
    "nav.grp.settings": "設定",
    "link.title": "TrialBox でこのページを開く",
    "link.lead": "他のサイトのリンクから、TrialBox の次のページを開こうとしています：{page}",
    "link.file": "このリンクはファイルを開くか操作を始めるものです。TrialBox はそれを自分のページからしか行わないため、「続ける」でホームページを開きます。",
    "link.why": "他のサイトのページがあなたの名前で操作できないよう、TrialBox はこのタップをお願いしています。",
    "link.continue": "続ける",
    "form.restored": "セッションが切れる前に入力した項目を復元しました：{n} 項目。確認してから保存してください。",
    "form.discard": "破棄",
}

ZH: dict[str, str] = {
    "pf.study": "試驗：步驟、團隊與連結",
    "pf.study.attn": "試驗：步驟、團隊與連結。其中 {n} 項需要您處理。",
    "nav.grp.site": "院所",
    "nav.grp.study": "{rs} · 試驗頁面",
    "nav.grp.registers": "名冊",
    "nav.grp.box": "管理",
    "nav.grp.lists": "清單與請求",
    "nav.grp.settings": "設定",
    "link.title": "在 TrialBox 開啟此頁",
    "link.lead": "您從其他網站的連結前往 TrialBox 的這一頁：{page}",
    "link.file": "這個連結會開啟檔案或啟動操作。TrialBox 只從自己的頁面這麼做，因此「繼續」會開啟您的首頁。",
    "link.why": "TrialBox 請您點這一下，讓其他網站的頁面無法以您的名義操作。",
    "link.continue": "繼續",
    "form.restored": "已還原登入結束前填寫的欄位：{n} 個。請確認後再儲存。",
    "form.discard": "捨棄",
}
