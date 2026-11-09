# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of the feature-flag page ``/ops/flags`` (T-008, D-207, MR-090). Joined into ``console.i18n`` by
``console.admin_flags`` when the page is registered."""

from __future__ import annotations

EN: dict[str, str] = {
    "flags.title": "Feature flags",
    "flags.help": "Switches that change how the box works, for every service, without a restart (within five seconds). Each change needs a reason and is kept in the audit trail with your name. An environment variable can only set a flag's first value, when the box first starts.",
    "flags.name": "Flag",
    "flags.what": "What it does",
    "flags.value": "Value",
    "flags.unset": "not set yet (the box has not started on this database)",
    "flags.changed": "Last changed",
    "flags.by": "by",
    "flags.reason": "Reason",
    "flags.reason.help": "Why the value changes now; name the decision or the ticket.",
    "flags.new": "New value",
    "flags.change": "Change",
    "flags.history": "History",
    "flags.history.none": "No change yet.",
    "flags.kind.seed": "first value",
    "flags.kind.set": "changed",
    "flags.confirm": "Change {flag} from {old} to {new}? Every service uses the new value from its next piece of work (for the lake: the next rebuild). Reason: {reason}",
    "flags.desc.lake.source": "Where the screening lake's rows come from at the next rebuild: legacy (flattened from the hospital's snapshot) or omop (exported from the OMOP store of record).",
}

JA: dict[str, str] = {
    "flags.title": "機能フラグ",
    "flags.help": "ボックス全体の動作を切り替える設定です。再起動なしで、5秒以内にすべてのサービスに反映されます。変更には理由が必要で、あなたの名前とともに監査記録に残ります。環境変数で決められるのは、ボックスを最初に起動したときの初期値だけです。",
    "flags.name": "フラグ",
    "flags.what": "内容",
    "flags.value": "値",
    "flags.unset": "未設定（このデータベースではまだボックスが起動していません）",
    "flags.changed": "最終変更",
    "flags.by": "変更者",
    "flags.reason": "理由",
    "flags.reason.help": "いま値を変える理由。決定番号やチケットを書いてください。",
    "flags.new": "新しい値",
    "flags.change": "変更する",
    "flags.history": "履歴",
    "flags.history.none": "変更はまだありません。",
    "flags.kind.seed": "初期値",
    "flags.kind.set": "変更",
    "flags.confirm": "{flag} を {old} から {new} に変更しますか？各サービスは次の処理から新しい値を使います（レイクの場合は次の再構築から）。理由：{reason}",
    "flags.desc.lake.source": "次の再構築でスクリーニング用レイクの行をどこから作るか：legacy（病院のスナップショットを展開）または omop（OMOP の記録用ストアから書き出し）。",
}

ZH: dict[str, str] = {
    "flags.title": "功能旗標",
    "flags.help": "切換整台系統運作方式的設定，不需重新啟動，五秒內所有服務都會套用。每次變更都須填寫理由，並以您的名字記入稽核紀錄。環境變數只能決定系統第一次啟動時的初始值。",
    "flags.name": "旗標",
    "flags.what": "用途",
    "flags.value": "值",
    "flags.unset": "尚未設定（系統尚未在此資料庫上啟動）",
    "flags.changed": "最後變更",
    "flags.by": "變更者",
    "flags.reason": "理由",
    "flags.reason.help": "為何現在變更此值；請寫明決議編號或工單。",
    "flags.new": "新的值",
    "flags.change": "變更",
    "flags.history": "歷程",
    "flags.history.none": "尚無變更。",
    "flags.kind.seed": "初始值",
    "flags.kind.set": "已變更",
    "flags.confirm": "要將 {flag} 從 {old} 改為 {new} 嗎？各服務會從下一項工作開始使用新值（資料湖：從下一次重建開始）。理由：{reason}",
    "flags.desc.lake.source": "下一次重建時篩選用資料湖的資料來源：legacy（展開醫院的快照）或 omop（從 OMOP 記錄庫匯出）。",
}
