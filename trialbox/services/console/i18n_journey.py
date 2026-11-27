"""Strings of the user-journey review fixes of 2026-11-09, wave 1c (D-146): the request refusals (J-01, J-02), the
viewer's request card (J-04), the criteria approval's "who may" (J-27) and the draft's own words, and the study's
"Who to screen" (J-26). Merged last into ``console.i18n``; every key in all three languages."""

from __future__ import annotations

EN: dict[str, str] = {
    # J-01 / J-02: the orchestrator's refusal of a request, in the page's language
    "problem.h.request.limit": "Today's limit is reached",
    "request.limit": "{n} {kind} runs were started from this account's mailbox in the last 24 hours, the most this box "
    "allows. Case questions, consent drafts and approvals are not counted. Try again tomorrow, or ask the "
    "administrator to raise the limit.",
    "problem.h.request.role": "Your role cannot start this",
    "request.role": "Your account's role may not start {kind}. A coordinator or an administrator starts runs; the "
    "investigator approves the criteria.",
    "problem.h.request.mailbox": "This mailbox may not start this",
    "request.mailbox": "The mailbox {mailbox} may not start {kind}. Ask the administrator to give your account its own "
    "mailbox, or to allow this one.",
    # E2E P-35: an investigator on no study log opens the week page: it says why and what next (status stays 403)
    "problem.h.week.no_log": "No study log is assigned to you",
    "week.no_log": "You are not on the delegation log of study {rs}, so its weekly list is closed to you.",
    "problem.why.week.no_log": 'The study\'s PI adds you to the log and ticks "screen" for you. Ask the PI or the '
    "TrialBox administrator, then sign in again.",
    "week.no_log.request": "Go to the request page",
    # J-04: what a viewer or CRO account can open
    "request.viewer.reports": "the feasibility reports of your studies, in aggregate",
    # J-27: only the investigator ticks and approves; the draft is the protocol's own words
    "s20.who": "Who does what: the study's investigator ticks each criterion's codes as checked and approves. The "
    "coordinator prepares the draft and gives each criterion the site's own label.",
    "s20.only_pi": "Only the study's investigator ticks the criteria and approves them. You can read the draft and "
    "give each criterion the site's label in this page's language.",
    "s20.as_written": "as written in the protocol",
    # J-26: who a study's screening runs look at
    "setup.who.title": "Who to screen",
    "setup.who.help": "Screening looks at the patients chosen here: the whole hospital, or only some doctors' "
    "patients. A request that names doctors (pract=) still uses those for that one run.",
    "setup.who.now.hospital": "Now: the whole hospital (every patient with a booked appointment or a recent visit).",
    "setup.who.now.pract": "Now: these doctors' patients only: {ids}.",
    "setup.who.unset": "Not set yet: a screening run of this study stops until you choose.",
    "setup.who.hospital": "The whole hospital: every patient with a booked appointment in the coming months or a "
    "visit in the last 12 months",
    "setup.who.pract": "Only these doctors' patients",
    "setup.who.ids": "Doctor ids (for 'only these doctors')",
    "setup.who.ids.help": "The ids the hospital system uses, separated by commas, e.g. P12345, P23456.",
    "setup.who.save": "Save who to screen",
}

JA: dict[str, str] = {
    "problem.h.request.limit": "本日の上限に達しました",
    "request.limit": "このアカウントのメールアドレスから過去24時間に {kind} の実行が {n} 件あり、"
    "この TrialBox の上限です。"
    "個別の患者の確認・同意説明の下書き・承認は数えません。明日もう一度実行するか、上限の引き上げを管理者に依頼してください。",
    "problem.h.request.role": "この役割では開始できません",
    "request.role": "このアカウントの役割では {kind} を開始できません。実行を開始するのは CRC か管理者で、"
    "選択・除外基準を承認するのは責任医師です。",
    "problem.h.request.mailbox": "このメールアドレスでは開始できません",
    "request.mailbox": "メールアドレス {mailbox} では {kind} を開始できません。"
    "アカウントに本人のメールアドレスを設定するか、"
    "このアドレスを許可するよう管理者に依頼してください。",
    # E2E P-35: an investigator on no study log opens the week page: it says why and what next (status stays 403)
    "problem.h.week.no_log": "この試験の治験分担医師・治験協力者リストに登録されていません",
    "week.no_log": "あなたは試験 {rs} の治験分担医師・治験協力者リストに載っていないため、週間リストを開けません。",
    "problem.why.week.no_log": "試験の責任医師があなたをリストに登録し「スクリーニング」にチェックを入れます。"
    "責任医師か TrialBox の管理者に依頼し、完了後にサインインし直してください。",
    "week.no_log.request": "リクエストのページへ",
    "request.viewer.reports": "担当試験の実施可能性レポート（集計のみ）",
    "s20.who": "役割：試験の責任医師が各基準のコードを確認済みにして承認します。CRC は下書きを準備し、"
    "各基準に施設での表示名を付けます。",
    "s20.only_pi": "基準の確認と承認ができるのは試験の責任医師のみです。下書きを読み、"
    "このページの言語で施設での表示名を付けることができます。",
    "s20.as_written": "プロトコルの原文のまま",
    "setup.who.title": "スクリーニングの対象",
    "setup.who.help": "スクリーニングはここで選んだ患者を対象にします：病院全体、または一部の医師の患者のみ。"
    "依頼で医師を指定した場合（pract=）は、その回だけその医師の患者を対象にします。",
    "setup.who.now.hospital": "現在：病院全体（予約または最近の受診があるすべての患者）。",
    "setup.who.now.pract": "現在：次の医師の患者のみ：{ids}。",
    "setup.who.unset": "未設定：選ぶまで、この試験のスクリーニングは実行できません。",
    "setup.who.hospital": "病院全体：今後数か月に予約がある、または過去12か月に受診したすべての患者",
    "setup.who.pract": "次の医師の患者のみ",
    "setup.who.ids": "医師ID（「次の医師の患者のみ」の場合）",
    "setup.who.ids.help": "病院システムの医師IDをカンマで区切って入力します。例：P12345, P23456",
    "setup.who.save": "スクリーニングの対象を保存",
}

ZH: dict[str, str] = {
    "problem.h.request.limit": "已達今日上限",
    "request.limit": "過去 24 小時內，此帳號的電子郵件已啟動 {n} 次 {kind}，已達本系統的上限。"
    "個案確認、同意說明草稿與核准不計入。請明天再試，或請管理員提高上限。",
    "problem.h.request.role": "您的角色無法啟動此作業",
    "request.role": "此帳號的角色無法啟動 {kind}。作業由研究護理師或管理員啟動；收案條件由主持人核准。",
    "problem.h.request.mailbox": "此電子郵件無法啟動此作業",
    "request.mailbox": "電子郵件 {mailbox} 無法啟動 {kind}。請管理員為您的帳號設定您自己的電子郵件，或允許此地址。",
    # E2E P-35: an investigator on no study log opens the week page: it says why and what next (status stays 403)
    "problem.h.week.no_log": "您尚未被指派到此試驗的授權紀錄表",
    "week.no_log": "您不在試驗 {rs} 的授權紀錄表上，因此無法開啟其每週名單。",
    "problem.why.week.no_log": "請試驗主持人把您加入授權紀錄表並勾選「篩選」，"
    "或聯絡 TrialBox 管理者；完成後請重新登入。",
    "week.no_log.request": "前往請求頁面",
    "request.viewer.reports": "您負責試驗的可行性報告（僅彙總）",
    "s20.who": "分工：試驗主持人將每條條件的代碼標記為已確認並核准；研究護理師準備草稿，並為每條條件加上本院的名稱。",
    "s20.only_pi": "只有本試驗的主持人可以確認並核准條件。您可以閱讀草稿，並以此頁面的語言為每條條件加上本院的名稱。",
    "s20.as_written": "計畫書原文",
    "setup.who.title": "篩選對象",
    "setup.who.help": "篩選會以此處選擇的病人為對象：全院，或僅部分醫師的病人。請求中指定醫師（pract=）時，"
    "該次篩選只看那些醫師的病人。",
    "setup.who.now.hospital": "目前：全院（所有有預約或近期就診的病人）。",
    "setup.who.now.pract": "目前：僅以下醫師的病人：{ids}。",
    "setup.who.unset": "尚未設定：選擇之前，此試驗的篩選無法執行。",
    "setup.who.hospital": "全院：未來數個月有預約，或過去 12 個月內有就診的所有病人",
    "setup.who.pract": "僅以下醫師的病人",
    "setup.who.ids": "醫師代碼（選「僅以下醫師」時）",
    "setup.who.ids.help": "請輸入院內系統的醫師代碼，以逗號分隔，例如 P12345, P23456。",
    "setup.who.save": "儲存篩選對象",
}
