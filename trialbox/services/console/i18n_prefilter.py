"""The words of a nightly job's pre-filter funnel on its job page (10E-12, D-1259): the night's patients of one study,
stage by stage, each counted once. In en, zh-TW and ja. Joined into ``console.i18n`` (merged with plain
``dict.update``)."""

from __future__ import annotations

EN: dict[str, str] = {
    "job.prefilter.title": "The night's screening, stage by stage",
    "job.prefilter.what": "{study}, the night of {date}, from the study's {jobs} finished nightly runs. Within a run "
    "each patient is counted once, at their last evaluation.",
    "job.prefilter.sums": "The figures are the runs' counts added together: a patient two runs of the night both "
    "looked at is counted twice.",
    "job.prefilter.stage": "Stage",
    "job.prefilter.removed": "Removed",
    "job.prefilter.left": "Left",
    "job.prefilter.in_scope": "In scope",
    "job.prefilter.opted_out": "Opted out, refused, or not in the records on the day",
    "job.prefilter.not_due": "Not due on this night",
    "job.prefilter.carried": "Left for a later night by the night budget",
    "job.prefilter.coded_excluded": "The coded records did not match a criterion",
    "job.prefilter.no_model": "Answered without the model reading notes, not listed",
    "job.prefilter.model_not_listed": "Notes read by the model, not listed",
    "job.prefilter.listed": "Listed",
}

JA: dict[str, str] = {
    "job.prefilter.title": "その夜のスクリーニング（段階ごと）",
    "job.prefilter.what": "{study}、{date} の夜。この研究の終了した夜間実行 {jobs} 件から。1 回の実行の中では、"
    "各患者を最後の評価で 1 回だけ数えます。",
    "job.prefilter.sums": "数値は各実行の数を足し合わせたものです。"
    "その夜の 2 つの実行がどちらも見た患者は 2 回数えられます。",
    "job.prefilter.stage": "段階",
    "job.prefilter.removed": "除かれた数",
    "job.prefilter.left": "残った数",
    "job.prefilter.in_scope": "対象範囲",
    "job.prefilter.opted_out": "オプトアウト、拒否、またはその日の記録にない",
    "job.prefilter.not_due": "この夜は確認の時期ではない",
    "job.prefilter.carried": "夜間の上限により後の夜に持ち越し",
    "job.prefilter.coded_excluded": "コード化された記録が条件に合致しない",
    "job.prefilter.no_model": "モデルが記録文を読まずに回答、リストに載らない",
    "job.prefilter.model_not_listed": "モデルが記録文を読んだ、リストに載らない",
    "job.prefilter.listed": "リストに掲載",
}

ZH: dict[str, str] = {
    "job.prefilter.title": "當晚的篩選（逐階段）",
    "job.prefilter.what": "{study}，{date} 當晚，取自本研究已完成的 {jobs} 次夜間執行。在同一次執行中，"
    "每位病人只在最後一次評估時計算一次。",
    "job.prefilter.sums": "數字是各次執行的數目相加：當晚兩次執行都看過的病人會被計算兩次。",
    "job.prefilter.stage": "階段",
    "job.prefilter.removed": "移除",
    "job.prefilter.left": "剩下",
    "job.prefilter.in_scope": "納入範圍",
    "job.prefilter.opted_out": "已退出、拒絕，或當日不在紀錄中",
    "job.prefilter.not_due": "本晚未到期",
    "job.prefilter.carried": "因夜間上限留待之後的夜晚",
    "job.prefilter.coded_excluded": "編碼紀錄未符合某條件",
    "job.prefilter.no_model": "模型未讀病歷文字即已回答，未列入名單",
    "job.prefilter.model_not_listed": "模型已讀病歷文字，未列入名單",
    "job.prefilter.listed": "列入名單",
}
