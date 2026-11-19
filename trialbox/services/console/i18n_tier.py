# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of the administrator's home tile "What this box's tier does not include" (plan 10 row 10E-17, D-1244;
``console.tier_words``). Joined into ``console.i18n`` when ``console.tier_words`` is imported. The box is the
catalogue's "この機器" (ja) and "本機" (zh-TW); "nothing is wrong" is its "異常ではありません。" and "並非故障。"
(``feas.ct.none.*``). The hardware tier is 構成 (ja) and 等級 (zh-TW), not ``col.tier``'s 区分 and 分級, which name a
patient's candidate tier on a run's list."""

from __future__ import annotations

EN: dict[str, str] = {
    "tier.title": "What this box's tier does not include",
    "tier.lacks.protocol_reading": "Protocol reading: this box's tier does not include it. Protocols are read on the coordinating box and arrive here as a signed package. Nothing is wrong.",
    "tier.lacks.chat_during_a_screening_run": "Questions to the models during a screening run: this box's tier keeps one model awake at a time, so a question waits until the run releases the GPU. Nothing is wrong.",
    "tier.declared": "As declared for this tier; not yet measured on this hardware.",
}

JA: dict[str, str] = {
    "tier.title": "この機器の構成に含まれない機能",
    "tier.lacks.protocol_reading": "プロトコルの読み取り：この機器の構成には含まれていません。プロトコルは取りまとめ側の機器で読み取られ、署名付きのパッケージとしてここに届きます。異常ではありません。",
    "tier.lacks.chat_during_a_screening_run": "スクリーニング実行中のモデルへの質問：この機器の構成では一度に一つのモデルだけが起動しているため、質問は実行が GPU を解放するまで待ちます。異常ではありません。",
    "tier.declared": "この構成で申告された値です。このハードウェアでは未測定です。",
}

ZH: dict[str, str] = {
    "tier.title": "本機等級不包含的功能",
    "tier.lacks.protocol_reading": "計畫書判讀：本機的等級不包含此功能。計畫書在協調端的機器上判讀，以簽署過的套件送到本機。並非故障。",
    "tier.lacks.chat_during_a_screening_run": "篩選執行期間向模型提問：本機的等級一次只讓一個模型運作，提問會等到執行釋出 GPU 後再處理。並非故障。",
    "tier.declared": "此為本等級所宣告的值，尚未在本機硬體上量測。",
}
