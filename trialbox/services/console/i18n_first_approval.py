"""Strings of NEW-JRN-1 (JRN-001, D-540): a new study's first approval. The steward's task "name the PI", what
the approval page says while no PI is named, and the refusal of a request for a study outside an account's own.
Merged last into ``console.i18n``; every key in all three languages."""

from __future__ import annotations

EN: dict[str, str] = {
    "pi.task.lead": "Criteria are waiting for approval in a study whose delegation log names no principal "
    "investigator yet. Nobody can approve them until you name the PI from the signed log.",
    "pi.task.item": "{rs}: name the principal investigator",
    "pi.needed": "Nobody can approve these criteria yet: the delegation log of {rs} names no principal investigator. "
    "The data steward names the PI from the signed log; then the PI ticks and approves on this page.",
    "pi.needed.link": "Open the delegation log",
    "pi.no_account": "No investigator account can open {rs}, so no PI can be named yet. The administrator creates the "
    "investigator's account, or adds {rs} to the studies of an account that is limited to other studies (Users).",
    "problem.h.request.scope": "Your account cannot start this",
    "request.scope": "Your account is limited to its own studies ({studies}). It cannot start a request for another "
    "study or add a new one. An administrator, or a coordinator whose account is not limited to studies, starts it; "
    "the administrator can add the study to your account afterwards.",
}

JA: dict[str, str] = {
    "pi.task.lead": "治験分担医師・治験協力者リストに治験責任医師がまだ記載されていない試験で、基準が承認待ちです。"
    "署名済みの記録に基づいて治験責任医師を登録するまで、誰も承認できません。",
    "pi.task.item": "{rs}：治験責任医師を登録する",
    "pi.needed": "この基準はまだ誰も承認できません。{rs} の治験分担医師・治験協力者リストに"
    "治験責任医師が記載されていません。"
    "データスチュワードが署名済みの記録に基づいて治験責任医師を登録すると、治験責任医師がこのページで確認・承認できます。",
    "pi.needed.link": "治験分担医師・治験協力者リストを開く",
    "pi.no_account": "{rs} を開ける医師アカウントがないため、まだ治験責任医師を登録できません。"
    "管理者が医師のアカウントを作成するか、ほかの試験に限定されているアカウントの担当試験に"
    " {rs} を追加してください（ユーザー）。",
    "problem.h.request.scope": "このアカウントでは開始できません",
    "request.scope": "このアカウントは担当試験（{studies}）に限定されています。ほかの試験の依頼や新しい試験の追加は"
    "できません。管理者、または試験が限定されていないCRCが開始してください。"
    "その後、管理者がこのアカウントに試験を追加できます。",
}

ZH: dict[str, str] = {
    "pi.task.lead": "有試驗的條件正在等待核准，但其授權紀錄表尚未記載試驗主持人。"
    "在您依已簽署的紀錄登記主持人之前，沒有人可以核准。",
    "pi.task.item": "{rs}：登記試驗主持人",
    "pi.needed": "目前沒有人可以核准這些條件：{rs} 的授權紀錄表尚未記載試驗主持人。"
    "資料管理員依已簽署的紀錄登記主持人後，主持人即可在此頁面確認並核准。",
    "pi.needed.link": "開啟授權紀錄表",
    "pi.no_account": "沒有可開啟 {rs} 的醫師帳號，因此尚無法登記主持人。請管理員建立醫師帳號，"
    "或將 {rs} 加入僅限其他試驗之帳號的試驗清單（使用者）。",
    "problem.h.request.scope": "您的帳號無法啟動此項目",
    "request.scope": "您的帳號僅限於自己的試驗（{studies}），無法為其他試驗提出請求或新增試驗。"
    "請由管理員或未限定試驗的研究護理師（CRC）啟動；之後管理員可將該試驗加入您的帳號。",
}
