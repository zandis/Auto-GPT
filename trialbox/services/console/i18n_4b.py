"""Strings of TB-PLAN-04 step 4b, easy for novices (D-133), merged last into ``console.i18n`` (en, ja, zh-TW).

New keys for the one-time password hand-over, the "Not suitable" reason, Undo, the patient sheet, the sign-in page
(language, lockout), the error pages, the audit pager and the one-form study set-up; and the plain words of the
review's glossary (``docs/reviews/2026-11-08-ux-review-novice.md`` §4), which replace earlier entries here so that a
concept has one name on every page. Japanese and Taiwanese wording follows the hospital terms of the field research
(``docs/reviews/2026-11-08-field-research-tw-jp-sites.md``): ログイン, 治験依頼者 / 試驗委託者, 選択・除外基準 /
納入／排除條件, 処理 / 作業. Same parity rule: every language has every key.
"""

from __future__ import annotations

EN: dict[str, str] = {
    # words from the study or the data, shown as written
    "given.mark": "as given",
    # one name per page (review F-20): menu, tab, title and heading say the same
    "nav.week": "This week's patients",
    "week.title": "This week's patients",
    "wb.title": "This week's patients",
    "nav.patients": "Candidate registry",  # T-684: the name the page itself has
    "nav.jobs": "Runs",
    # header
    "menu": "Menu",
    "pilot.banner.short": "Test site · no real patients",
    # the one-time password (review F-02)
    "users.made": "Account {user} is ready",
    "users.pw.aloud": "One-time password, in groups of four",
    "users.pw.copy_label": "One-time password (select it to copy)",
    "users.pw.copy": "Copy",
    "users.pw.copied": "Copied",
    "users.handover.1": "Tell {user} the password in person or by phone, never by e-mail or chat. Read it in groups of "
    "four; it has no 0, O, 1, l or i, and the dashes are part of it.",
    "users.handover.2": "Ask them to sign in now and to change it at once under My account → Password.",
    "users.handover.3": "Close this page. The password is not shown again; if it is lost, use Reset password.",
    "users.pw.once": "Shown once. It is not kept in the address, the audit trail or any log.",
    "users.username.rule": "Lower-case letters a–z, digits and . _ - only, up to 32 characters (for example: "
    "tanaka.k).Lower-case letters a–z, digits and . _ - only, up to 32 characters (for example: tanaka.k).",
    "users.help": "Accounts of this TrialBox. A new account gets a one-time password, shown once; the person changes "
    "it under My account after the first sign-in. Disabling signs the person out everywhere.",
    "users.role.investigator": "read everything a viewer reads, plus candidate rows and patient checks, and decide "
    "which patients to contact; may show the study's chart numbers (recorded with your name); no runs",
    # marks (glossary: one vocabulary)
    "mark.reason.for": "Reason (needed for “Not suitable now”)",
    "mark.reason.choose": "Choose a reason",
    "mark.reason_needed": "Choose a reason first. “Not suitable now” is recorded only with the reason the investigator "
    "chose.",
    "mark.undo": "Undo",
    "mark.undo_none": "There is no mark of yours to undo on this patient.",
    "wb.done.undo": "Undone. The patient is back as before.",
    "wb.done.not_suitable": "Set aside for now, with your reason. The patient leaves your lists.",
    "outcome.wait_pi": "Not recorded: the investigator has not marked this patient “Approach” yet. Contact outcomes "
    "are recorded only after that.",
    "outcome.wait_pi.hint": "Waiting for the investigator's decision. You can record a call once the investigator "
    "marks the patient “Approach”.",
    "sheet.back": "Back to the list",
    "sheet.next": "Next patient",
    "reveal.title": "Chart number",
    "patient.reveal.audited": "Show chart number (recorded with your name)",
    # sign-in (review F-05)
    "login.title": "Sign in",
    "login.locked": "This account is locked for {n} more minute(s), until {until}, after 5 failed tries in a row.",
    "login.locked.wait": "Wait until then and try again, checking Caps Lock. If you have forgotten the password, ask "
    "the administrator to reset it.",
    "login.ask": "Cannot sign in? Ask your TrialBox administrator.",
    "login.ask.mail": "Cannot sign in? Ask your TrialBox administrator: {mail}",
    # error pages (review F-12)
    "problem.h.notfound": "Page not found",
    "problem.h.forbidden": "This page needs another role",
    "problem.h.csrf": "The form expired",
    "problem.h.unavailable": "A service did not answer",
    "problem.h.other": "This could not be done",
    "problem.why.notfound": "The address may have changed, or the study is not one of yours.",
    "problem.why.forbidden": "If you need it, ask the TrialBox administrator to change your role.",
    "notfound": "This page does not exist.",
    "forbidden": "Your role cannot open this page or do this action.",
    "login": "Sign in first: this address needs a signed-in session or a valid access token.",
    "problem.home": "My home page",
    "problem.back": "Go back",
    "problem.help": "Help",
    "problem.ask": "Need help? Ask your TrialBox administrator.",
    "problem.ask.mail": "Need help? Ask your TrialBox administrator: {mail}",
    # audit pager (review F-07)
    "audit.newer": "Newer",
    "audit.page": "Page {n}",
    # study set-up in one form (review F-04, F-11)
    "setup.help": "One form for the study. Fill in what you know and press Save at the bottom: everything on the page "
    "is saved together. You can come back any time.",
    "setup.step.study": "Study",
    "setup.step.log": "Numbering",
    "setup.step.redcap": "REDCap (optional)",
    "setup.step.save": "Save",
    "setup.s2": "3 · REDCap (optional)",
    "setup.s3": "2 · Numbering and reasons",
    "setup.save_all": "Save the set-up",
    "setup.unsaved": "Changes on this page are saved only when you press “Save the set-up”.",
    "setup.saved": "Saved. Everything on this page is stored.",
    "rc.wiz.1": "Choose the REDCap access key the administrator added.",
    "rc.wiz.2": "Press “Read the fields from REDCap”: TrialBox reads the project's data dictionary (nothing is "
    "changed).",
    "rc.wiz.3": "Pick each field from the list, then press “Save the set-up”.",
    "rc.read_fields": "Read the fields from REDCap",
    "rc.dict.ok": "Project {p} “{title}”: {n} fields read. Pick them from the lists below.",
    "rc.dict.none": "Fields not read yet. Press “Read the fields from REDCap” to choose them from a list instead of "
    "typing.",
    "rc.pick.none": "— not used —",
    "rc.more": "More options (multi-site projects, write-back)",
    "rc.token": "REDCap access key",
    "rc.token.none": "No REDCap access key yet. Ask the administrator to add one on the REDCap connection page; then "
    "come back here.",
    "rc.err.RC-LINK-FIELD": "Not in the REDCap data dictionary: {fields}. Pick the field from the list (press “Read "
    "the fields from REDCap”). The link stays off until it is corrected.",
    "rc.err.RC-LINK-FIELD.none": "A field of the link is not in this REDCap project's data dictionary. Check the "
    "project id, then pick the fields from the list.",
    "rc.err.RC-UPSTREAM": "REDCap answered with an error ({msg}). Check the address and the access key with the "
    "administrator, then try again.",
    # help built from the user's own studies (review F-10)
    "help.yours": "Try with your own studies",
    "help.yours.none": "You have no study yet. Ask the coordinator to send the protocol.",
    "help.ex.study": "{rs} — opens the study",
    "help.ex.week": "{rs} this week — the patients to decide",
    "help.ex.feas": "{rs} feasibility — the patient count report",
    "help.steps": "What to do on this page",
    "help.ask": "Still stuck? Ask your TrialBox administrator.",
    # home
    "home.setup": "Study set-up",
    "home.clinic.all": "Show all {n}",
    # 9k-7 (D-1388): the toast's Undo of a mark: this person's, for a stated time, once, and refused with what is true
    "mark.undo_until": "You can undo this until {until}.",
    "mark.undo_not_yours": "Only {by}, who made this mark, can undo it. Nothing was undone.",
    "mark.undo_changed_by": (
        "This patient's mark has changed since: {by} recorded a newer one at {at}. Nothing was undone."
    ),
    "mark.undo_changed": "This patient's mark has changed since. Nothing was undone.",
    "mark.undo_expired": (
        "The time to undo this mark ended at {until}. Nothing was undone: mark the patient again instead."
    ),
    "mark.undo_outcome": "A contact outcome was recorded after this mark. Nothing was undone.",
    "mark.undo_list": (
        "The mark before this one was made on an earlier list. Nothing was undone: mark the patient again."
    ),
}

JA: dict[str, str] = {
    "given.mark": "原文",
    "nav.week": "今週の患者",
    "week.title": "今週の患者",
    "wb.title": "今週の患者",
    "nav.patients": "候補者レジストリ",
    "nav.jobs": "処理",
    "menu": "メニュー",
    "pilot.banner.short": "テスト環境・実在の患者なし",
    "users.made": "アカウント {user} を作成しました",
    "users.pw.aloud": "初期パスワード（4 文字ずつ）",
    "users.pw.copy_label": "初期パスワード（選択してコピー）",
    "users.pw.copy": "コピー",
    "users.pw.copied": "コピーしました",
    "users.handover.1": "{user} さんに口頭または電話で伝えてください（メールやチャットは不可）。4 "
    "文字ずつ読み上げます。0・O・1・l・i は含まれず、ハイフンも入力します。",
    "users.handover.2": "すぐにログインし、「マイアカウント → パスワード」で変更してもらってください。",
    "users.handover.3": "このページを閉じてください。パスワードは再表示されません。"
    "分からなくなったら「パスワード再発行」を使います。",
    "users.pw.once": "表示はこの 1 回だけです。アドレス・監査証跡・ログには残りません。",
    "users.username.rule": "半角小文字 a〜z、数字、. _ - のみ、32 文字まで（例：tanaka.k）。",
    "users.help": "この TrialBox のアカウント。新規アカウントには 1 回だけ表示される初期パスワードが発行され、"
    "本人が初回ログイン後に「マイアカウント」で変更します。無効化すると全端末からログアウトされます。",
    "users.role.investigator": "閲覧者の権限に加え、候補者の行と患者ごとの確認を閲覧し、声をかける患者を決めます。"
    "担当試験のカルテ番号を表示できます（氏名とともに記録）。処理の開始は不可",
    "mark.reason.for": "理由（「今回は見合わせる」に必須）",
    "mark.reason.choose": "理由を選んでください",
    "mark.reason_needed": "先に理由を選んでください。「今回は見合わせる」は、医師が選んだ理由と一緒にだけ記録されます。"
    "先に理由を選んでください。「今回は見合わせる」は、医師が選んだ理由と一緒にだけ記録されます。",
    "mark.undo": "元に戻す",
    "mark.undo_none": "この患者さんには、元に戻せるあなたの判断がありません。",
    "wb.done.undo": "元に戻しました。患者さんは前の状態に戻りました。",
    "wb.done.not_suitable": "理由とともに今回は見合わせました。この患者さんはリストから外れます。",
    "outcome.wait_pi": "記録していません：医師がまだこの患者さんを「声をかける」としていません。"
    "連絡結果はその後にだけ記録できます。",
    "outcome.wait_pi.hint": "医師の判断待ちです。医師が「声をかける」とした後に、連絡結果を記録できます。",
    "sheet.back": "リストに戻る",
    "sheet.next": "次の患者さん",
    "reveal.title": "カルテ番号",
    "patient.reveal.audited": "カルテ番号を表示（あなたの名前で記録されます）",
    "login.title": "ログイン",
    "login.locked": "5 回続けて失敗したため、このアカウントはあと {n} 分（{until} まで）ロックされています。",
    "login.locked.wait": "時間が過ぎてから Caps Lock を確認して再度お試しください。"
    "パスワードを忘れた場合は管理者に再発行を依頼してください。",
    "login.ask": "ログインできない場合は、TrialBox の管理者に連絡してください。",
    "login.ask.mail": "ログインできない場合は、TrialBox の管理者に連絡してください：{mail}",
    "problem.h.notfound": "ページが見つかりません",
    "problem.h.forbidden": "このページには別の役割が必要です",
    "problem.h.csrf": "フォームの有効期限が切れました",
    "problem.h.unavailable": "サービスが応答しません",
    "problem.h.other": "実行できませんでした",
    "problem.why.notfound": "アドレスが変わったか、担当の試験ではない可能性があります。",
    "problem.why.forbidden": "必要な場合は、TrialBox の管理者に役割の変更を依頼してください。",
    "notfound": "このページは存在しません。",
    "forbidden": "あなたの役割では、このページを開くこと・この操作はできません。",
    "login": "先にログインしてください。このアドレスにはログイン中のセッションか有効なアクセストークンが必要です。",
    "problem.home": "ホームへ",
    "problem.back": "前のページへ",
    "problem.help": "ヘルプ",
    "problem.ask": "困ったときは TrialBox の管理者に連絡してください。",
    "problem.ask.mail": "困ったときは TrialBox の管理者に連絡してください：{mail}",
    "audit.newer": "新しい記録",
    "audit.page": "{n} ページ目",
    "setup.help": "試験ごとに 1 つのフォームです。分かるところを入力し、最後に一番下の「保存」を押してください。"
    "ページ全体がまとめて保存されます。いつでも戻って直せます。",
    "setup.step.study": "試験",
    "setup.step.log": "番号の付け方",
    "setup.step.redcap": "REDCap（任意）",
    "setup.step.save": "保存",
    "setup.s2": "3 · REDCap（任意）",
    "setup.s3": "2 · 番号の付け方と理由",
    "setup.save_all": "設定を保存",
    "setup.unsaved": "このページの変更は「設定を保存」を押したときにだけ保存されます。",
    "setup.saved": "保存しました。このページの内容はすべて保存されています。",
    "rc.wiz.1": "管理者が登録した REDCap の API キーを選びます。",
    "rc.wiz.2": "「REDCap から項目を読む」を押すと、TrialBox がプロジェクトのデータ辞書を読み込みます（何も変更しません"
    "）。",
    "rc.wiz.3": "各フィールドを一覧から選び、「設定を保存」を押します。",
    "rc.read_fields": "REDCap から項目を読む",
    "rc.dict.ok": "プロジェクト {p}「{title}」：{n} 項目を読み込みました。下の一覧から選んでください。",
    "rc.dict.none": "まだ項目を読み込んでいません。「REDCap から項目を読む」を押すと、入力せずに一覧から選べます。",
    "rc.pick.none": "— 使わない —",
    "rc.more": "その他の設定（多施設プロジェクト・書き戻し）",
    "rc.token": "REDCap の API キー",
    "rc.token.none": "REDCap の API キーがまだありません。管理者に「REDCap 接続」ページで追加してもらい、"
    "その後このページに戻ってください。",
    "rc.err.RC-LINK-FIELD": "REDCap のデータ辞書にありません：{fields}。一覧から選び直してください（「REDCap "
    "から項目を読む」）。直すまで連携はオフのままです。",
    "rc.err.RC-LINK-FIELD.none": "連携のフィールドが、この REDCap プロジェクトのデータ辞書にありません。プロジェクト "
    "ID を確認し、一覧から選んでください。",
    "rc.err.RC-UPSTREAM": "REDCap がエラーを返しました（{msg}）。アドレスと API キーを管理者と確認してから、"
    "もう一度お試しください。",
    "help.yours": "ご自分の試験で試す",
    "help.yours.none": "まだ担当の試験がありません。CRC にプロトコルの送付を依頼してください。",
    "help.ex.study": "{rs} — 試験を開く",
    "help.ex.week": "{rs} 今週 — 判断する患者さん",
    "help.ex.feas": "{rs} 実施可能性 — 患者数のレポート",
    "help.steps": "このページですること",
    "help.ask": "解決しない場合は、TrialBox の管理者に連絡してください。",
    "home.setup": "試験の設定",
    "home.clinic.all": "{n} 件すべて表示",
    "mark.undo_until": "{until} まで元に戻せます。",
    "mark.undo_not_yours": "この判断を元に戻せるのは、判断した {by} さんだけです。何も元に戻していません。",
    "mark.undo_changed_by": (
        "この患者さんの判断はその後変わりました（{at} に {by} さんが新しい判断を記録）。何も元に戻していません。"
    ),
    "mark.undo_changed": "この患者さんの判断はその後変わりました。何も元に戻していません。",
    "mark.undo_expired": (
        "この判断を元に戻せる時間は {until} に終わりました。何も元に戻していません。もう一度判断してください。"
    ),
    "mark.undo_outcome": "この判断の後に連絡結果が記録されました。何も元に戻していません。",
    "mark.undo_list": "前の判断は以前のリストで行われました。何も元に戻していません。もう一度判断してください。",
}

ZH: dict[str, str] = {
    "given.mark": "原文",
    "nav.week": "本週病人",
    "week.title": "本週病人",
    "wb.title": "本週病人",
    "nav.patients": "候選者登錄",
    "nav.jobs": "作業",
    "menu": "選單",
    "pilot.banner.short": "測試環境・無真實病人",
    "users.made": "帳號 {user} 已建立",
    "users.pw.aloud": "一次性密碼（每 4 字一組）",
    "users.pw.copy_label": "一次性密碼（選取即可複製）",
    "users.pw.copy": "複製",
    "users.pw.copied": "已複製",
    "users.handover.1": "請當面或以電話告知 {user}，不可用電子郵件或通訊軟體。每 4 字一組唸出；密碼不含 0、O、1、l、i，"
    "連字號也要輸入。",
    "users.handover.2": "請對方立即登入，並到「我的帳號 → 密碼」更改。",
    "users.handover.3": "關閉此頁。密碼不會再次顯示；若遺失，請使用「重設密碼」。",
    "users.pw.once": "只顯示這一次，不會留在網址、稽核軌跡或任何紀錄中。",
    "users.username.rule": "只能用小寫英文字母 a–z、數字與 . _ -，最多 32 字（例如：lin.yt）。",
    "users.help": "此 TrialBox 的帳號。新帳號會取得只顯示一次的一次性密碼，本人第一次登入後在「我的帳號」更改。"
    "停用會使該人員在所有裝置登出。",
    "users.role.investigator": "檢視者的權限，加上候選者列與病人檢核，並決定要聯絡哪些病人；可顯示所負責試驗的病歷號"
    "（連同您的姓名記錄），不可啟動作業",
    "mark.reason.for": "原因（「暫不邀請」必填）",
    "mark.reason.choose": "請選擇原因",
    "mark.reason_needed": "請先選擇原因。「暫不邀請」只會連同主持人選的原因一起記錄。",
    "mark.undo": "復原",
    "mark.undo_none": "這位病人沒有您可以復原的標記。",
    "wb.done.undo": "已復原，病人回到先前的狀態。",
    "wb.done.not_suitable": "已連同原因標記為暫不邀請，這位病人將離開您的清單。",
    "outcome.wait_pi": "未記錄：主持人尚未將這位病人標記為「邀請」。聯絡結果只能在那之後記錄。",
    "outcome.wait_pi.hint": "等待主持人決定。主持人標記「邀請」後，即可記錄聯絡結果。",
    "sheet.back": "回到清單",
    "sheet.next": "下一位病人",
    "reveal.title": "病歷號",
    "patient.reveal.audited": "顯示病歷號（以您的名字記錄）",
    "login.title": "登入",
    "login.locked": "連續失敗 5 次，此帳號還要鎖定 {n} 分鐘（至 {until}）。",
    "login.locked.wait": "請等到那時，確認 Caps Lock 後再試。若忘記密碼，請請管理者重設。",
    "login.ask": "無法登入？請聯絡 TrialBox 管理者。",
    "login.ask.mail": "無法登入？請聯絡 TrialBox 管理者：{mail}",
    "problem.h.notfound": "找不到這個頁面",
    "problem.h.forbidden": "這個頁面需要其他角色",
    "problem.h.csrf": "表單已過期",
    "problem.h.unavailable": "服務沒有回應",
    "problem.h.other": "無法完成",
    "problem.why.notfound": "網址可能已變更，或這不是您負責的試驗。",
    "problem.why.forbidden": "若您需要使用，請聯絡 TrialBox 管理者變更角色。",
    "notfound": "這個頁面不存在。",
    "forbidden": "您的角色無法開啟此頁面或執行此操作。",
    "login": "請先登入：此網址只開放給已登入的人員，或附有效存取金鑰的請求。",
    "problem.home": "回到首頁",
    "problem.back": "回上一頁",
    "problem.help": "說明",
    "problem.ask": "需要協助？請聯絡 TrialBox 管理者。",
    "problem.ask.mail": "需要協助？請聯絡 TrialBox 管理者：{mail}",
    "audit.newer": "較新的紀錄",
    "audit.page": "第 {n} 頁",
    "setup.help": "每個試驗一份表單。填入您知道的部分，最後按最下方的「儲存」：整頁會一起儲存。隨時可以回來修改。",
    "setup.step.study": "試驗",
    "setup.step.log": "編號方式",
    "setup.step.redcap": "REDCap（選填）",
    "setup.step.save": "儲存",
    "setup.s2": "3 · REDCap（選填）",
    "setup.s3": "2 · 編號方式與原因",
    "setup.save_all": "儲存設定",
    "setup.unsaved": "此頁的變更只有按下「儲存設定」時才會儲存。",
    "setup.saved": "已儲存，此頁的內容都已存好。",
    "rc.wiz.1": "選擇管理者加入的 REDCap API 金鑰。",
    "rc.wiz.2": "按「從 REDCap 讀取欄位」：TrialBox 會讀取專案的資料字典（不會更改任何內容）。",
    "rc.wiz.3": "從清單選擇各欄位，再按「儲存設定」。",
    "rc.read_fields": "從 REDCap 讀取欄位",
    "rc.dict.ok": "專案 {p}「{title}」：已讀取 {n} 個欄位，請從下方清單選擇。",
    "rc.dict.none": "尚未讀取欄位。按「從 REDCap 讀取欄位」即可從清單選擇，不必手動輸入。",
    "rc.pick.none": "— 不使用 —",
    "rc.more": "其他選項（多中心專案、回寫）",
    "rc.token": "REDCap API 金鑰",
    "rc.token.none": "尚無 REDCap API 金鑰。請管理者在「REDCap 連線」頁加入後，再回到此頁。",
    "rc.err.RC-LINK-FIELD": "不在 REDCap 資料字典中：{fields}。請從清單重新選擇（按「從 REDCap 讀取欄位」）。"
    "修正前連結保持關閉。",
    "rc.err.RC-LINK-FIELD.none": "連結的欄位不在此 REDCap 專案的資料字典中。請確認專案 ID，再從清單選擇欄位。",
    "rc.err.RC-UPSTREAM": "REDCap 回傳錯誤（{msg}）。請與管理者確認網址與 API 金鑰後再試。",
    "help.yours": "用您自己的試驗試試看",
    "help.yours.none": "您還沒有負責的試驗。請請研究護理師送出計畫書。",
    "help.ex.study": "{rs} — 開啟試驗",
    "help.ex.week": "{rs} 本週 — 需要決定的病人",
    "help.ex.feas": "{rs} 可行性 — 病人數報告",
    "help.steps": "在這一頁要做的事",
    "help.ask": "仍無法解決？請聯絡 TrialBox 管理者。",
    "home.setup": "試驗設定",
    "home.clinic.all": "顯示全部 {n} 筆",
    "mark.undo_until": "可在 {until} 前復原。",
    "mark.undo_not_yours": "只有做出此標記的 {by} 可以復原。未復原任何內容。",
    "mark.undo_changed_by": "此病人的標記之後已變更：{by} 於 {at} 記錄了新的標記。未復原任何內容。",
    "mark.undo_changed": "此病人的標記之後已變更。未復原任何內容。",
    "mark.undo_expired": "此標記可復原的時間已於 {until} 結束。未復原任何內容，請重新標記。",
    "mark.undo_outcome": "此標記之後已記錄聯絡結果。未復原任何內容。",
    "mark.undo_list": "前一個標記是在較早的名單上做的。未復原任何內容，請重新標記。",
}
