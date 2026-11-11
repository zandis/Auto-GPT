# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of D-396 (T-619b, STD-050, STD-051, STD-063): the CTCAE version an oncology study names when it adds the
built-in forms, the AE terms kept as written (MedDRA coding is the sponsor's), and the CDISC export with the CDASH IE
and DS rows. CTCAE grade words as JCOG's Japanese translation (グレード) and 等級 in Traditional Chinese. Joined into
the console's catalogues by ``console.i18n``."""

from __future__ import annotations

EN: dict[str, str] = {
    "dc.ctcae.label": "CTCAE grading (oncology studies)",
    "dc.ctcae.none": "Not used: severity as mild, moderate or severe",
    "dc.ctcae.help": "An oncology study grades every adverse event 1 to 5 by CTCAE and names the version it uses; the adverse event form then records the grade with that version. Adverse event terms are kept as written: MedDRA coding is done by the sponsor or the data centre.",
    "dc.ctcae.added": "CTCAE grading: {v}.",
    "dc.export.cdisc": "CDISC ODM with CDASH IE and DS",
    "dc.export.cdisc.help": "The CDISC file adds the CDASH tags of the built-in items and, from the screening log, the criterion a screen failure did not meet (IE) and consent, screen failure, completion and withdrawal (DS). It is for a sponsor or an EDC that reads CDASH; a REDCap project takes the plain ODM.",
}

JA: dict[str, str] = {
    "dc.ctcae.label": "CTCAE によるグレード評価(がん領域の研究)",
    "dc.ctcae.none": "使用しない: 重症度を軽度・中等度・高度で記録",
    "dc.ctcae.help": "がん領域の研究では、すべての有害事象を CTCAE でグレード1から5に評価し、使用する版を定めます。有害事象フォームはその版とともにグレードを記録します。有害事象名は記載どおりに保持し、MedDRA へのコーディングは治験依頼者またはデータセンターが行います。",
    "dc.ctcae.added": "CTCAE によるグレード評価: {v}",
    "dc.export.cdisc": "CDISC ODM(CDASH の IE と DS 付き)",
    "dc.export.cdisc.help": "CDISC 形式のファイルには、標準フォームの項目の CDASH タグと、スクリーニング記録から、スクリーニング不適格で満たさなかった基準(IE)と、同意・スクリーニング不適格・完了・中止(DS)が加わります。CDASH を読む治験依頼者や EDC 向けです。REDCap プロジェクトには通常の ODM を取り込みます。",
}

ZH: dict[str, str] = {
    "dc.ctcae.label": "CTCAE 等級評定(腫瘤科研究)",
    "dc.ctcae.none": "不使用: 嚴重程度以輕度、中度、重度記錄",
    "dc.ctcae.help": "腫瘤科研究依 CTCAE 將每一件不良事件評為第1級至第5級，並指定所用的版本；不良事件表單會將等級連同該版本一起記錄。不良事件名稱依原文保留，MedDRA 編碼由試驗委託者或資料中心進行。",
    "dc.ctcae.added": "CTCAE 等級評定: {v}",
    "dc.export.cdisc": "CDISC ODM(含 CDASH 的 IE 與 DS)",
    "dc.export.cdisc.help": "CDISC 檔案另含內建表單項目的 CDASH 標籤，以及取自篩選紀錄的篩選失敗未符合條件(IE)與同意、篩選失敗、完成、退出(DS)。供讀取 CDASH 的試驗委託者或 EDC 使用；REDCap 專案請匯入一般的 ODM。",
}
