"""Strings of M5's support session page (``console.support_page``)."""

from __future__ import annotations

EN: dict[str, str] = {
    "supportpage.title": "Support session",
    "supportpage.intro": "Turn this on when the supplier helps you. While it is on, no role can open a patient page "
    "or download a patient file. It ends by itself after {hours} hours.",
    "supportpage.on": "A support session is on. {by} started it at {started}; it ends by itself at {until}.",
    "supportpage.off": "No support session is on.",
    "supportpage.last": "The last session ended at {ended}.",
    "supportpage.confirm.start": "The supplier is helping us now: close the patient pages.",
    "supportpage.confirm.end": "The supplier's work is done: open the patient pages again.",
    "supportpage.confirm.missing": "Tick the box to say so first.",
    "supportpage.start": "Start a support session",
    "supportpage.end": "End the support session",
    "support.refused": "A support session is on: patient pages are closed until it ends.",
    "problem.h.support.refused": "Closed during a support session",
}

JA: dict[str, str] = {
    "supportpage.title": "サポートセッション",
    "supportpage.intro": "供給元の支援を受けるときにオンにします。オンの間は、どの役割も患者のページを開けず、患者の"
    "ファイルもダウンロードできません。{hours} 時間後に自動で終了します。",
    "supportpage.on": "サポートセッションがオンです。{by} が {started} に開始し、{until} に自動で終了します。",
    "supportpage.off": "サポートセッションはオフです。",
    "supportpage.last": "前回のセッションは {ended} に終了しました。",
    "supportpage.confirm.start": "供給元が今支援しています。患者のページを閉じます。",
    "supportpage.confirm.end": "供給元の作業は終わりました。患者のページを再び開きます。",
    "supportpage.confirm.missing": "先にチェックボックスにチェックを入れてください。",
    "supportpage.start": "サポートセッションを開始",
    "supportpage.end": "サポートセッションを終了",
    "support.refused": "サポートセッション中のため、終了するまで患者のページは閉じています。",
    "problem.h.support.refused": "サポートセッション中は閉じています",
}

ZH: dict[str, str] = {
    "supportpage.title": "支援模式",
    "supportpage.intro": "供應商協助時請開啟。開啟期間，任何角色都不能開啟病人頁面或下載病人檔案。{hours} 小時後會"
    "自動結束。",
    "supportpage.on": "支援模式已開啟。由 {by} 於 {started} 開始，將於 {until} 自動結束。",
    "supportpage.off": "沒有開啟中的支援模式。",
    "supportpage.last": "上一次支援模式於 {ended} 結束。",
    "supportpage.confirm.start": "供應商正在協助我們：關閉病人頁面。",
    "supportpage.confirm.end": "供應商的協助已完成：重新開啟病人頁面。",
    "supportpage.confirm.missing": "請先勾選此方塊。",
    "supportpage.start": "開始支援模式",
    "supportpage.end": "結束支援模式",
    "support.refused": "支援模式進行中：病人頁面在結束前關閉。",
    "problem.h.support.refused": "支援模式期間關閉",
}
