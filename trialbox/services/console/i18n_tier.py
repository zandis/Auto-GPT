# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of the administrator's home tile "What this box's tier includes" (plan 10 row 10E-17, D-1244;
``console.tier_words``). Joined into ``console.i18n`` when ``console.tier_words`` is imported."""

from __future__ import annotations

EN: dict[str, str] = {
    "tier.title": "What this box's tier includes",
    "tier.lacks.protocol_reading": "Protocol reading: this box's tier does not include it. Protocols are read on the coordinating box and arrive here as a signed package. Nothing is wrong.",
    "tier.lacks.chat_during_a_screening_run": "Questions to the models during a screening run: this box's tier keeps one model awake at a time, so a question waits until the run releases the GPU. Nothing is wrong.",
}

JA: dict[str, str] = {
    "tier.title": "このボックスの構成に含まれる機能",
    "tier.lacks.protocol_reading": "プロトコルの読み取り：このボックスの構成には含まれていません。プロトコルは取りまとめ側のボックスで読み取られ、署名付きのパッケージとしてここに届きます。異常ではありません。",
    "tier.lacks.chat_during_a_screening_run": "スクリーニング実行中のモデルへの質問：このボックスの構成では一度に一つのモデルだけが起動しているため、質問は実行が GPU を解放するまで待ちます。異常ではありません。",
}

ZH: dict[str, str] = {
    "tier.title": "這台機器的等級包含哪些功能",
    "tier.lacks.protocol_reading": "計畫書判讀：這台機器的等級不包含此功能。計畫書在協調端的機器上判讀，以簽署過的套件送到這裡。這不是故障。",
    "tier.lacks.chat_during_a_screening_run": "篩選執行期間向模型提問：這台機器的等級一次只讓一個模型運作，提問會等到執行釋出 GPU 後再處理。這不是故障。",
}
