# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of D-387 (T-623, LIFE-015, LIFE-016): the pre-screen log on the screening-log page (one row per
investigator mark, approached or not), the five added screening-log columns, and the criterion not met on a screen
failure. Words as on the lists (声をかける / 邀請) and the lifecycle pages (スクリーニング不適格 / 篩選失敗). A patient's
records "did not meet" a criterion; no verdict word (T-116). Joined into the console's catalogues by ``console.i18n``."""

from __future__ import annotations

EN: dict[str, str] = {
    "pre.title": "Pre-screen log",
    "pre.help": "One row for every mark the investigator made, whether the patient was approached or not. No screening number is needed. Pseudonymous, like the screening log; the XLSX has it as a second sheet.",
    "pre.empty": "No marks yet.",
    "pre.col.version": "Criteria version",
    "pre.col.later": "Later",
    "pre.col.consent": "Consent",
    "pre.col.enrolled": "Enrolled",
    "pre.later.withdrawn": "mark taken back",
    "pre.later.replaced": "a newer mark",
    "pre.under": "(v{version})",
    "pre.failed": "Criterion not met: {c}",
    "pre.icf": "(form {v})",
    "life.step.criterion": "Criterion not met",
    "life.step.criterion.help": "For a screen failure because a criterion was not met: choose the criterion. The criteria version {version} is kept with it.",
    "life.trail.criterion": "criterion not met: {c}",
    "life.why.criterion": "choose the criterion not met from the approved criteria.",
    "life.why.criterion_only": "only a screen failure for the reason Not eligible names a criterion.",
}

JA: dict[str, str] = {
    "pre.title": "プレスクリーニングログ",
    "pre.help": "責任医師の判断を、声をかけたかどうかにかかわらず 1 件ずつ記録します。スクリーニング番号は不要です。スクリーニングログと同じく仮名のみで、XLSX では 2 枚目のシートになります。",
    "pre.empty": "まだ判断はありません。",
    "pre.col.version": "基準の版",
    "pre.col.later": "その後",
    "pre.col.consent": "同意",
    "pre.col.enrolled": "登録",
    "pre.later.withdrawn": "判断を取り消し",
    "pre.later.replaced": "新しい判断あり",
    "pre.under": "（第 {version} 版）",
    "pre.failed": "満たさなかった基準：{c}",
    "pre.icf": "（説明文書 {v}）",
    "life.step.criterion": "満たさなかった基準",
    "life.step.criterion.help": "基準を満たさなかったためのスクリーニング不適格では、その基準を選んでください。基準の版 {version} も一緒に記録します。",
    "life.trail.criterion": "満たさなかった基準：{c}",
    "life.why.criterion": "承認された基準から、満たさなかった基準を選んでください。",
    "life.why.criterion_only": "基準を記録できるのは、理由が「不適格」のスクリーニング不適格だけです。",
}

ZH: dict[str, str] = {
    "pre.title": "預篩選紀錄",
    "pre.help": "主持人的每一次判斷各佔一列，不論是否已邀請病人，不需要篩選編號。與篩選紀錄一樣只用代號；在 XLSX 檔中為第二張表。",
    "pre.empty": "尚無判斷。",
    "pre.col.version": "條件版本",
    "pre.col.later": "之後",
    "pre.col.consent": "同意",
    "pre.col.enrolled": "收案",
    "pre.later.withdrawn": "判斷已撤回",
    "pre.later.replaced": "已有較新的判斷",
    "pre.under": "（第 {version} 版）",
    "pre.failed": "未符合的條件：{c}",
    "pre.icf": "（同意書 {v}）",
    "life.step.criterion": "未符合的條件",
    "life.step.criterion.help": "因未符合某一條件而篩選失敗時，請選擇該條件。條件版本 {version} 會一併記錄。",
    "life.trail.criterion": "未符合的條件：{c}",
    "life.why.criterion": "請從已核准的條件中選擇未符合的條件。",
    "life.why.criterion_only": "只有原因為「不符合資格」的篩選失敗可以記錄條件。",
}
