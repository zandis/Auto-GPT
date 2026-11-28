"""The words of every refusal the console gives, in the page's language (TB-PLAN-03 step 4, D-119).

A refusal is raised as ``problem(status, "request.refused", reason="<English sentence>")``; the problem page puts the
reason into the catalogue's ``request.refused`` text. :func:`localize` swaps the English sentence for its Japanese or
Chinese words. A reason the table does not hold (an exception's own text, a backend message) is never shown on a
Japanese or Chinese page: the page says the request could not be done and to ask the administrator, and the English
detail stays in the log (Fable review 2026-11-08, finding 6).
"""

from __future__ import annotations

from collections.abc import Mapping

#: E2E P-14/P-24: EDC refusals that name a gap in the box's set-up, not a fault of a service: the signature key the
#: orchestrator cannot make or open (a VALIDATION or PRODUCTION box without a KEK). The console answers them as a
#: refusal with the orchestrator's own reason and next step (409), never as "a TrialBox service did not answer" (502)
EDC_SETUP_GAPS = frozenset({"edc.sign_key"})

# English sentence -> (Japanese, Traditional Chinese)
REFUSALS: dict[str, tuple[str, str]] = {
    # 1523 ruling (review round 3, M3): the sponsor pack packs only what the job recorded
    "a file of the job is not what the job recorded when it built it": (
        "ジョブのファイルが、ジョブが作成時に記録したものと一致しません",
        "此工作的檔案與工作產生時記錄的內容不符",
    ),
    # D-719 (NEW-SEC-3): the account requests page
    "an account with this name exists": ("この名前のアカウントはすでにあります", "已有此名稱的帳號"),
    "this request is no longer waiting": ("この依頼はもう待っていません", "此申請已不在等待中"),
    "unknown decision": ("不明な決定です", "未知的決定"),
    "the other factor was set within 30 days": (
        "もう一方の認証要素が30日以内に設定されています",
        "另一項驗證因素已於 30 天內設定",
    ),
    # DEMO-JA: a monitor grant names the field it lacks (the rehearsal saw only "could not be done")
    "a monitor grant needs the last day of the monitoring visit": (
        "モニターの許可には、モニタリング訪問の最終日が必要です",
        "監測員授權需要監測訪視的最後一天",
    ),
    "a monitor grant needs the visit id of the monitoring visit": (
        "モニターの許可には、モニタリング訪問の ID が必要です",
        "監測員授權需要監測訪視的編號",
    ),
    "a monitor grant needs the last day and the visit id of the monitoring visit": (
        "モニターの許可には、モニタリング訪問の最終日と ID が必要です",
        "監測員授權需要監測訪視的最後一天與編號",
    ),
    "a monitor grant names a CRO account of this study": (
        "モニターの許可には、この試験の CRO アカウントを選んでください",
        "監測員授權須選擇本試驗的 CRO 帳號",
    ),
    # D-380 (FIT-002): the monitor's read of the data core
    "the data core refused the subject": ("データコアがこの被験者を拒否しました", "資料核心拒絕了這位受試者"),
    "the data core did not answer": ("データコアが応答しませんでした", "資料核心沒有回應"),
    # D-436 (T-303): the monitor's SDV pages read the data core and the EDC
    "the data core refused the request": ("データコアが要求を拒否しました", "資料核心拒絕了此要求"),
    "the EDC refused the request": ("EDC が要求を拒否しました", "EDC 拒絕了此要求"),
    "the EDC did not answer": ("EDC が応答しませんでした", "EDC 沒有回應"),
    # D-192: sign-in and recovery (/ops/identity, the TOTP step)
    "no such account": ("そのアカウントはありません", "沒有此帳號"),
    "this account signs in through the identity provider": (
        "このアカウントは病院アカウントでログインします",
        "此帳號以醫院帳號登入",
    ),
    "the authenticator key file does not match; ask an administrator": (
        "認証アプリの鍵ファイルが一致しません。管理者に連絡してください",
        "驗證器金鑰檔案不符，請聯絡管理者",
    ),
    "another administrator does this for your account": (
        "ご自身のアカウントには別の管理者が行います",
        "您自己的帳號須由另一位管理者處理",
    ),
    "choose the page language the label is in first": (
        "先に表示名の言語をページの言語として選んでください",
        "請先將頁面語言切換為標籤的語言",
    ),
    "approve the criteria first": ("先に選択基準を承認してください", "請先核准收案條件"),
    "give every criterion a short label first: ": (
        "先にすべての基準に短いラベルを付けてください：",
        "請先為每一項條件填寫簡短標籤：",
    ),
    "attach a protocol file": ("プロトコルのファイルを添付してください", "請附上計畫書檔案"),
    "attach the informed-consent form": ("同意説明文書を添付してください", "請附上受試者同意書"),
    "attachments are at most 50 MB": ("添付ファイルは50 MBまでです", "附件最大 50 MB"),
    "bad pseudonym": ("仮名IDの形式が正しくありません", "假名代碼格式不正確"),
    "this is a pseudonym, not a chart number: put it in the pseudonym field": (
        "これは仮名IDで、カルテ番号ではありません。仮名IDの欄に入力してください",
        "這是假名代碼，不是病歷號：請填入假名代碼欄位",
    ),
    "type the whole pseudonym (32 characters), or the chart number: the 8 characters a page shows name no patient": (
        "仮名IDは全体（32文字）を入力するか、カルテ番号を入力してください。画面に表示される8文字だけでは患者を特定できません",
        "請輸入完整的假名代碼（32 個字元）或病歷號：畫面上顯示的 8 個字元無法指明病人",
    ),
    "too many exports with chart numbers in the last hour": (
        "この 1 時間のカルテ番号付きの書き出しが上限に達しました",
        "過去一小時內含病歷號的匯出已達上限",
    ),
    "choose why you need the chart number": ("カルテ番号が必要な理由を選んでください", "請選擇需要病歷號的原因"),
    "chart numbers are letters, digits or '-'": ("カルテ番号は英数字と「-」のみです", "病歷號只能包含英數字與「-」"),
    "chart numbers are revealed for finished screening jobs only": (
        "カルテ番号は完了したスクリーニングでのみ表示できます",
        "只有已完成的篩選作業才能顯示病歷號",
    ),
    "charts are PDF, DOCX, TXT or MD, at most 50 MB each": (
        "カルテはPDF・DOCX・TXT・MDで、1件50 MBまでです",
        "病歷須為 PDF、DOCX、TXT 或 MD，每份最大 50 MB",
    ),
    "choose Approach, Need info, Not suitable now or Not now": (
        "「声をかける」「情報が必要」「今回は見合わせる」「後日再確認」から選んでください",
        "請選擇「邀請」「需要更多資訊」「暫不邀請」或「稍後再評估」",
    ),
    "choose FEAS or SCREEN and an approved ruleset": (
        "実施可能性調査かスクリーニングと、承認済みの基準を選んでください",
        "請選擇可行性評估或篩選，以及已核准的條件",
    ),
    "choose a ruleset": ("基準を選んでください", "請選擇條件"),  # J-2 (D-1221): the add no longer takes a status
    "choose the whole hospital or some doctors": (  # D-146 (J-26): the study's screening scope
        "病院全体か、一部の医師の患者かを選んでください",
        "請選擇全院或部分醫師的病人",
    ),
    "choose a staged bundle": ("取り込み済みの更新ファイルを選んでください", "請選擇已放入的更新檔"),  # D-178
    "choose an approved ruleset": ("承認済みの基準を選んでください", "請選擇已核准的條件"),
    "choose en, ja or zh-TW": ("英語・日本語・中国語（繁体字）から選んでください", "請選擇英文、日文或繁體中文"),
    "choose one of the contact outcomes": ("連絡結果を一つ選んでください", "請選擇一項聯絡結果"),
    "consent forms are PDF, DOCX, TXT or MD, at most 50 MB": (
        "同意説明文書はPDF・DOCX・TXT・MDで、50 MBまでです",
        "同意書須為 PDF、DOCX、TXT 或 MD，最大 50 MB",
    ),
    "give the re-check date as YYYY-MM-DD": (
        "再確認日は YYYY-MM-DD で入力してください",
        "請以 YYYY-MM-DD 輸入再評估日期",
    ),
    "attempts and days are whole numbers": ("回数と日数は整数で入力してください", "次數與天數請輸入整數"),
    # 10C-19 (D-1232): the study's ages for consent by a representative and for assent
    "the ages are whole numbers": ("年齢は整数で入力してください", "年齡請輸入整數"),
    "the age of majority is 16 to 21": ("成年年齢は 16〜21 歳です", "成年年齡為 16 至 21 歲"),
    "the assent ages run from the youngest to the oldest, from 0 and below the age of majority": (
        "アセントの年齢は下限から上限の順で、0 歳以上・成年年齢未満です",
        "須取得贊同的年齡由低至高，自 0 歲起且低於成年年齡",
    ),
    "consent by a representative is not recorded on this box": (
        "この TrialBox では代諾者による同意を記録していません",
        "此 TrialBox 不記錄法定代理人同意",
    ),
    "consent by a representative is not recorded on this box: turned on at install (--consent-proxy on)": (
        "この TrialBox では代諾者による同意を記録していません。病院の IT 担当がインストール時に有効にします"
        "（install.sh --consent-proxy on）",
        "此 TrialBox 不記錄法定代理人同意；由醫院資訊人員於安裝時開啟（install.sh --consent-proxy on）",
    ),
    "give the retry date as YYYY-MM-DD": (
        "再連絡日は YYYY-MM-DD で入力してください",
        "請以 YYYY-MM-DD 輸入再聯絡日期",
    ),
    "item ids look like I03 or Q2, separated by commas": (
        "項目IDは I03 や Q2 の形で、カンマで区切ってください",
        "項目代碼格式如 I03 或 Q2，以逗號分隔",
    ),
    "only a finished consent explainer can be released": (
        "公開できるのは完成した同意説明だけです",
        "只有完成的同意說明才能發布",
    ),
    "open every amber row first: ": ("先に黄色の行をすべて開いてください：", "請先打開所有黃色的列："),
    "practitioner ids are letters and digits, comma separated": (
        "医師IDは英数字で、カンマで区切ってください",
        "醫師代碼為英數字，以逗號分隔",
    ),
    "protocols are PDF, DOCX, TXT or MD, at most 50 MB": (
        "プロトコルはPDF・DOCX・TXT・MDで、50 MBまでです",
        "計畫書須為 PDF、DOCX、TXT 或 MD，最大 50 MB",
    ),
    "ruleset ids are 1-16 letters, digits, '-' or '_'": (
        "基準IDは1〜16文字の英数字・「-」・「_」です",
        "條件代碼為 1–16 個英數字、「-」或「_」",
    ),
    "screen failure must be 0 to 99 %": ("スクリーニング脱落率は0〜99 %です", "篩選失敗率須為 0–99 %"),
    "study codes are 1-16 letters, digits, '-' or '_'": (
        "試験コードは1〜16文字の英数字・「-」・「_」です",
        "試驗代碼為 1–16 個英數字、「-」或「_」",
    ),
    "target and screen failure must be numbers": ("目標数と脱落率は数字で入力してください", "目標數與失敗率須為數字"),
    "target must be between 1 and 10,000 patients": ("目標数は1〜10,000人です", "目標數須為 1–10,000 人"),
    "target period must be 1 to 120 months": ("目標期間は1〜120か月です", "目標期間須為 1–120 個月"),
    "the practitioner id is letters and digits": ("医師IDは英数字です", "醫師代碼為英數字"),
    "the proposal expired; propose again": (
        "提案の期限が切れました。もう一度提案してください",
        "提案已過期，請重新提案",
    ),
    "the re-check date must be within the next year": ("再確認日は1年以内にしてください", "再評估日期須在一年內"),
    "watch a criterion of this patient's list": (
        "この患者のリストにある基準を選んでください",
        "請選擇此病人清單上的條件",
    ),
    "keep is trialbox or theirs": (
        "TrialBox の値を残すか、ソースの値を採用するかを選んでください",
        "請選擇保留 TrialBox 的值或採用來源的值",
    ),
    "there is no mark to withdraw": ("取り消す判断がありません", "沒有可撤回的標記"),
    "this account has no mailbox (console.cli set-mailbox)": (
        "このアカウントにはメールアドレスがありません。管理者に連絡してください",
        "此帳號沒有電子郵件信箱，請聯絡管理員",
    ),
    "this job is not waiting for approval": ("このジョブは承認待ちではありません", "此作業並非等待核准"),
    "the page language changed since this page was shown": (
        "このページを表示してから言語が変わりました。ページを開き直してください",
        "顯示此頁後語言已變更，請重新開啟頁面",
    ),
    "a JSON object": ("JSON のオブジェクトを送ってください", "請傳送 JSON 物件"),
    "unknown action": ("この操作はありません", "沒有此操作"),
    "unknown study type or cohort kind": (
        "試験の種類またはコホートの種類が正しくありません",
        "試驗類型或世代類型不正確",
    ),
    "unknown trial": ("この試験はありません", "沒有此試驗"),
    "version is x.y.z": ("バージョンは x.y.z の形です", "版本格式為 x.y.z"),
    # D-147: the delegation log, referral, IRB record, staff directory and opt-out register
    "dates are YYYY-MM-DD": ("日付は YYYY-MM-DD で入力してください", "請以 YYYY-MM-DD 輸入日期"),
    "choose the role: PI, sub-investigator, CRC or other": (
        "役割を選んでください：責任医師・分担医師・CRC・その他",
        "請選擇角色：試驗主持人、協同主持人、研究護理師或其他",
    ),
    "give the person's name": ("氏名を入力してください", "請輸入姓名"),
    "give the start date": ("開始日を入力してください", "請輸入開始日"),
    "the end date is before the start date": ("最終日が開始日より前です", "最後一天早於開始日"),
    "no such entry in this study's log": ("この試験の委任リストにその行はありません", "本試驗的授權紀錄表沒有這一筆"),
    "say whether the copy matches the signed log": (
        "署名済みリストと一致しているかを選んでください",
        "請選擇是否與已簽署的授權紀錄表一致",
    ),
    "no such person in the directory": ("職員名簿にその人はいません", "人員名冊中沒有此人"),
    "give the department and who answers for it": (
        "診療科と、その窓口の人を入力してください",
        "請輸入科別與該科聯絡人",
    ),
    "choose how the treating doctor is asked": ("主治医への依頼方法を選んでください", "請選擇詢問主治醫師的方式"),
    "choose the doctor's answer: agree, decline or discuss": (
        "主治医の返事を選んでください：了承・見送り・相談",
        "請選擇醫師的回覆：同意、婉拒或討論",
    ),
    "no such referral in this study": ("この試験にその紹介依頼はありません", "本試驗沒有這筆轉介請求"),
    "this referral has its answer already; ask again with a new request": (
        "この依頼にはすでに返事があります。あらためて依頼してください",
        "這筆請求已有回覆；請重新提出請求",
    ),
    "the approval expires before it was given": ("承認の有効期限が承認日より前です", "核准有效期限早於核准日期"),
    # D-399 (T-302a): the approved consent-form versions and the one way to record consent
    "the version is letters, digits, spaces and . _ / ( ) -, at most 40": (
        "版は英数字・空白・. _ / ( ) - で40文字までです",
        "版本為英數字、空白及 . _ / ( ) -，最多 40 字",
    ),
    "a version is used only from its IRB approval date": (
        "版はIRB承認日から使用できます",
        "版本須自 IRB 核准日起才能使用",
    ),
    "that version is not on the list": ("その版は一覧にありません", "清單中沒有此版本"),
    "say why the version is taken off the list": (
        "版を一覧から外す理由を書いてください",
        "請說明將此版本移出清單的原因",
    ),
    "record consent on the participant page: it opens the consent form": (
        "同意は参加者のページで記録してください（同意書フォームが開きます）",
        "請在受試者頁面記錄同意（會開啟同意書表單）",
    ),
    "no such account for this study": ("この試験にそのアカウントはありません", "本試驗沒有此帳號"),
    "a sub-investigator signs in with an investigator account": (
        "分担医師は医師アカウントでログインします",
        "協同主持人須以醫師帳號登入",
    ),
    "give a chart number or a pseudonym": ("カルテ番号か仮名IDを入力してください", "請輸入病歷號或假名代碼"),
    # NEW-DIN-3 (D-544): console.team.CANNOT_CHECK
    "TrialBox cannot check this chart number now: to register it without the check, write why "
    "(at least 10 characters)": (
        "TrialBoxは今このカルテ番号を確認できません。確認なしで登録する場合は、理由を10文字以上で書いてください",
        "TrialBox 目前無法核對此病歷號。若要不經核對而登記，請寫明理由（至少 10 個字）",
    ),
    # NEW-DIN-3 (D-544): console.team.NOT_A_PATIENT
    "this chart number is not a patient of this box: check the number; to register it anyway, write why "
    "(at least 10 characters)": (
        "このカルテ番号はこのTrialBoxの患者さんのものではありません。番号を確かめてください。それでも登録する場合は、理由を10文字以上で書いてください",
        "此病歷號不是本 TrialBox 的病人，請核對號碼。若仍要登記，請寫明理由（至少 10 個字）",
    ),
    "the box could not turn the chart number into a pseudonym": (
        "カルテ番号を仮名IDに変えられませんでした",
        "無法將病歷號轉為假名代碼",
    ),
    "the box holds no patient under this chart number": (  # NEW-JRN-6 (D-771): the disclosure report's lookup
        "このカルテ番号の患者はこのボックスにいません",
        "此裝置中沒有此病歷號的病人",
    ),
}

UNTRANSLATED: dict[str, str] = {
    "ja": "この依頼は実行できませんでした。続く場合は管理者に連絡してください",
    "zh-TW": "無法執行此請求；若持續發生，請聯絡管理員",
}


def localize_reason(reason: str, lang: str) -> str:
    """The reason in ``lang``: English as given; Japanese and Chinese from :data:`REFUSALS` (a known sentence with a
    detail after it keeps the detail when the detail has no Latin words), else the generic sentence."""
    if lang not in ("ja", "zh-TW"):
        return reason
    i = 0 if lang == "ja" else 1
    hit = REFUSALS.get(reason)
    if hit is not None:
        return hit[i]
    for en, words in REFUSALS.items():
        if en.endswith(": ") and reason.startswith(en):
            return words[i] + reason[len(en) :]
    return UNTRANSLATED[lang]


def localize(values: Mapping[str, object], lang: str) -> dict[str, object]:
    out = dict(values)
    if isinstance(out.get("reason"), str):
        out["reason"] = localize_reason(str(out["reason"]), lang)
    return out


__all__ = ["REFUSALS", "UNTRANSLATED", "localize", "localize_reason"]
