# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings around the live preflight on the box's first-run page (10K-3, D-1361; ``console.firstrun``). The lines'
own labels and next actions are the check list's (``tb_common.preflight``), never here. Joined into the catalogue by
``console.firstrun``."""

from __future__ import annotations

EN: dict[str, str] = {
    "firstrun.preflight": "Checks of this box",
    "firstrun.preflight.help": "The box checked its network, storage, data feed and hardware at {at} (UTC). A red line says what to do; the set-up can go on while it is done.",
    "firstrun.preflight.none": "The box has not run its checks yet. They run when the box shows its set-up code; ask the box's supplier if this stays empty.",
    "firstrun.preflight.pass": "OK",
    "firstrun.preflight.warn": "Check",
    "firstrun.preflight.fail": "Not ready",
    "firstrun.preflight.action": "What to do:",
}

JA: dict[str, str] = {
    "firstrun.preflight": "このボックスの確認",
    "firstrun.preflight.help": "ボックスは {at}（UTC）にネットワーク、保存先、データの受け取り、ハードウェアを確認しました。赤い行には次にすることが書かれています。その対応を待たずに設定を続けられます。",
    "firstrun.preflight.none": "ボックスはまだ確認を行っていません。確認は設定用コードを表示するときに行われます。空のままの場合はボックスの納入業者に連絡してください。",
    "firstrun.preflight.pass": "OK",
    "firstrun.preflight.warn": "要確認",
    "firstrun.preflight.fail": "未完了",
    "firstrun.preflight.action": "次にすること：",
}

ZH: dict[str, str] = {
    "firstrun.preflight": "本機檢查",
    "firstrun.preflight.help": "本機已於 {at}（UTC）檢查網路、儲存、資料來源與硬體。紅色的一行會寫出該怎麼做；處理期間設定仍可繼續。",
    "firstrun.preflight.none": "本機尚未執行檢查。檢查會在本機顯示設定碼時執行；若一直是空的，請聯絡主機供應商。",
    "firstrun.preflight.pass": "正常",
    "firstrun.preflight.warn": "請確認",
    "firstrun.preflight.fail": "未就緒",
    "firstrun.preflight.action": "該怎麼做：",
}
