# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of D-192 (the TOTP step, the OIDC sign-in, the recovery page). Joined into ``console.i18n`` by
``console.identity`` when it is imported."""

from __future__ import annotations

EN: dict[str, str] = {
    "identity.mfa.totp": "authenticator app (TOTP)",
    "identity.mfa.off": "off (build and synthetic data only)",
    "identity.oidc.on": "on",
    "identity.oidc.off": "off",
    "login.oidc": "Sign in with the hospital account",
    "login.oidc.failed": "The hospital sign-in did not complete. Try again, or ask the administrator to check your "
    "groups.",
    "login.oidc.clash": "Your hospital account is in two groups that give different TrialBox roles: “{a}” and “{b}”. One account holds one role, so the sign-in was refused.",
    "login.oidc.clash.do": "Ask the hospital's IT to remove you from one of these two groups, then sign in again. Nothing was changed in TrialBox.",
    "idle.soon.title": "You will be signed out in one minute",
    "idle.soon.text": "Nothing has reached TrialBox from this page for {n} minutes. To keep working, choose Stay signed in. What you typed stays on this page.",
    "idle.limit.title": "This session ends in one minute",
    "idle.soon.title.s": "You will be signed out in {s} seconds",
    "idle.limit.title.s": "This session ends in {s} seconds",
    "idle.limit.text": "The session has reached the longest time it may last and cannot be extended. Save what you typed now, then sign in again.",
    "idle.locked.title": "You have been signed out",
    "idle.locked.text": "What you typed is still on this page. Press Save: you are asked to sign in again, and an entry form (an adverse event, a visit) or a mark's note is put back after the sign-in.",
    "idle.stay": "Stay signed in",
    "idle.close": "Close",
    "login.local": "Or sign in with a TrialBox account",
    "totp.title": "Second step: authenticator code",
    "totp.code": "6-digit code from your authenticator app",
    "totp.submit": "Continue",
    "totp.enrol.title": "Set up your authenticator",
    "totp.enrol.key": "Key",
    "totp.enrol.link": "Link for the authenticator app",
    "totp.failed.wrong": "That code is not right. Check the phone's clock and try the newest code.",
    "totp.failed.replay": "That code was used already. Wait for the next code.",
    "totp.cancel": "Start again",
    "oidc.done": "Signed in. Opening TrialBox.",
    "oidc.continue": "Continue",
    "identity.title": "Sign-in and recovery",
    "identity.policy": "Second factor: {mfa}. Hospital sign-in (OIDC): {oidc}. Sessions end after {idle} minutes idle "
    "or {hours} hours.",
    "identity.col.user": "Account",
    "identity.col.kind": "Signs in with",
    "identity.col.totp": "Authenticator",
    "identity.col.lock": "Locked until",
    "identity.kind.local": "TrialBox password",
    "identity.kind.idp": "hospital account",
    "identity.yes": "set up",
    "identity.no": "not yet",
    "identity.unlock": "Unlock",
    "identity.reset": "Reset authenticator",
    "identity.done.unlock": "The account is unlocked.",
    "identity.confirm.reset": "Reset the authenticator of {user}? They are signed out and set up a new authenticator "
    "at their next sign-in. Check who is asking before you do this.",
}
JA: dict[str, str] = {
    "identity.mfa.totp": "認証アプリ（TOTP）",
    "identity.mfa.off": "なし（開発環境と合成データのみ）",
    "identity.oidc.on": "使用する",
    "identity.oidc.off": "使用しない",
    "login.oidc": "病院アカウントでログイン",
    "login.oidc.failed": "病院アカウントでのログインが完了しませんでした。もう一度試すか、管理者にグループの確認を依頼してください。",
    "login.oidc.clash": "病院アカウントが、TrialBox で異なる役割になる 2 つのグループ「{a}」と「{b}」に属しています。1 つのアカウントが持てる役割は 1 つのため、ログインは拒否されました。",
    "login.oidc.clash.do": "病院の IT 担当者に、この 2 つのグループのどちらかから外すよう依頼し、もう一度ログインしてください。TrialBox では何も変更されていません。",
    "idle.soon.title": "1 分後にログアウトされます",
    "idle.soon.text": "このページから {n} 分間 TrialBox に何も送られていません。作業を続けるには「ログインを続ける」を選んでください。入力した内容はこのページに残ります。",
    "idle.limit.title": "このセッションは 1 分後に終了します",
    "idle.soon.title.s": "{s} 秒後にログアウトされます",
    "idle.limit.title.s": "このセッションは {s} 秒後に終了します",
    "idle.limit.text": "セッションが続けられる最長の時間に達したため、延長できません。入力した内容を今すぐ保存し、もう一度ログインしてください。",
    "idle.locked.title": "ログアウトされました",
    "idle.locked.text": "入力した内容はこのページに残っています。「保存」を押すと再ログインを求められ、入力フォーム（有害事象、来院）やマークのメモはログイン後に戻されます。",
    "idle.stay": "ログインを続ける",
    "idle.close": "閉じる",
    "login.local": "または TrialBox アカウントでログイン",
    "totp.title": "第 2 段階：認証アプリのコード",
    "totp.code": "認証アプリに表示される 6 桁のコード",
    "totp.submit": "続ける",
    "totp.enrol.title": "認証アプリの設定",
    "totp.enrol.key": "キー",
    "totp.enrol.link": "認証アプリ用のリンク",
    "totp.failed.wrong": "コードが正しくありません。スマートフォンの時刻を確認し、最新のコードを入力してください。",
    "totp.failed.replay": "このコードは使用済みです。次のコードを待ってください。",
    "totp.cancel": "最初からやり直す",
    "oidc.done": "ログインしました。TrialBox を開いています。",
    "oidc.continue": "続ける",
    "identity.title": "ログインと復旧",
    "identity.policy": "第二要素：{mfa}。病院アカウント（OIDC）：{oidc}。セッションは {idle} 分の無操作または {hours} 時間で終了します。",
    "identity.col.user": "アカウント",
    "identity.col.kind": "ログイン方法",
    "identity.col.totp": "認証アプリ",
    "identity.col.lock": "ロック解除予定",
    "identity.kind.local": "TrialBox パスワード",
    "identity.kind.idp": "病院アカウント",
    "identity.yes": "設定済み",
    "identity.no": "未設定",
    "identity.unlock": "ロック解除",
    "identity.reset": "認証アプリをリセット",
    "identity.done.unlock": "アカウントのロックを解除しました。",
    "identity.confirm.reset": "{user} の認証アプリをリセットしますか？ログアウトされ、次回のログイン時に新しい認証アプリを設定します。"
    "依頼者が本人であることを確認してから実行してください。",
}
ZH: dict[str, str] = {
    "identity.mfa.totp": "驗證器 App（TOTP）",
    "identity.mfa.off": "未啟用（僅限開發環境與合成資料）",
    "identity.oidc.on": "啟用",
    "identity.oidc.off": "未啟用",
    "login.oidc": "以醫院帳號登入",
    "login.oidc.failed": "醫院帳號登入未完成。請再試一次，或請管理者確認您的群組。",
    "login.oidc.clash": "您的醫院帳號屬於兩個在 TrialBox 中對應不同角色的群組：「{a}」與「{b}」。一個帳號只能有一個角色，因此登入被拒絕。",
    "login.oidc.clash.do": "請醫院資訊部門將您從這兩個群組之一移除，然後再登入一次。TrialBox 中沒有任何變更。",
    "idle.soon.title": "一分鐘後將登出",
    "idle.soon.text": "此頁面已有 {n} 分鐘未傳送任何內容至 TrialBox。若要繼續工作，請選擇「保持登入」。您輸入的內容會留在此頁面上。",
    "idle.limit.title": "此工作階段將於一分鐘後結束",
    "idle.soon.title.s": "{s} 秒後將登出",
    "idle.limit.title.s": "此工作階段將於 {s} 秒後結束",
    "idle.limit.text": "此工作階段已達可持續的最長時間，無法延長。請立即儲存您輸入的內容，然後再登入一次。",
    "idle.locked.title": "您已被登出",
    "idle.locked.text": "您輸入的內容仍在此頁面上。請按「儲存」：系統會要求您重新登入，登入後會放回輸入表單（不良事件、訪視）或標記的備註。",
    "idle.stay": "保持登入",
    "idle.close": "關閉",
    "login.local": "或以 TrialBox 帳號登入",
    "totp.title": "第二步：驗證器代碼",
    "totp.code": "驗證器 App 顯示的 6 位數代碼",
    "totp.submit": "繼續",
    "totp.enrol.title": "設定驗證器",
    "totp.enrol.key": "金鑰",
    "totp.enrol.link": "驗證器 App 的連結",
    "totp.failed.wrong": "代碼不正確。請確認手機時間並輸入最新的代碼。",
    "totp.failed.replay": "此代碼已使用過。請等待下一個代碼。",
    "totp.cancel": "重新開始",
    "oidc.done": "已登入。正在開啟 TrialBox。",
    "oidc.continue": "繼續",
    "identity.title": "登入與復原",
    "identity.policy": "第二因子：{mfa}。醫院帳號（OIDC）：{oidc}。閒置 {idle} 分鐘或登入滿 {hours} 小時即自動登出。",
    "identity.col.user": "帳號",
    "identity.col.kind": "登入方式",
    "identity.col.totp": "驗證器",
    "identity.col.lock": "鎖定至",
    "identity.kind.local": "TrialBox 密碼",
    "identity.kind.idp": "醫院帳號",
    "identity.yes": "已設定",
    "identity.no": "未設定",
    "identity.unlock": "解除鎖定",
    "identity.reset": "重設驗證器",
    "identity.done.unlock": "帳號已解除鎖定。",
    "identity.confirm.reset": "要重設 {user} 的驗證器嗎？該帳號將被登出，並於下次登入時設定新的驗證器。執行前請確認提出要求的人。",
}

# review H2 (D-192): a new authenticator needs the administrator's one-time enrolment code
EN.update(
    {
        "totp.enrol.help": "This account has no authenticator yet. In an authenticator app (on your phone or a hospital device), add an account by key and type the key below, or open the link on the phone. Then enter the enrolment code your administrator gave you and the code the app shows.",
        "totp.enrol.code": "Enrolment code from your administrator",
        "totp.enrol.none": "This account has no authenticator and no valid enrolment code. Ask an administrator for an enrolment code (it is valid for 24 hours), then sign in again.",
        "totp.failed.enrol_code": "The enrolment code is not right, was used, or has expired. Ask your administrator for a new one.",
        "identity.help": "Lift a lock after failed sign-ins, give an enrolment code to an account that has no authenticator, or reset an authenticator when a phone is lost. Every action is recorded in the audit trail; a reset signs the account out.",
        "identity.done.reset_totp": "The authenticator is reset and the account is signed out. Give the person the enrolment code below.",
        "identity.code.title": "Enrolment code for {user}",
        "identity.code.label": "Enrolment code (valid 24 hours, works once)",
        "identity.code.once": "This code is shown only now. Hand it over in person or read it out on a call-back to the person's extension.",
        "identity.code.live": "enrolment code issued",
        "identity.code.issue": "Enrolment code",
        "identity.unenrolled.title": "{n} accounts cannot sign in yet: no authenticator",
        "identity.unenrolled.help": "Each needs an enrolment code from an administrator to set up an authenticator.",
    }
)
JA.update(
    {
        "totp.enrol.help": "このアカウントにはまだ認証アプリが登録されていません。認証アプリ（スマートフォンまたは病院の認証機器）でキーを使ってアカウントを追加し、下のキーを入力するか、スマートフォンでリンクを開いてください。その後、管理者から受け取った登録コードと、アプリに表示されたコードを入力してください。",
        "totp.enrol.code": "管理者から受け取った登録コード",
        "totp.enrol.none": "このアカウントには認証アプリも有効な登録コードもありません。管理者に登録コード（24 時間有効）を依頼し、もう一度ログインしてください。",
        "totp.failed.enrol_code": "登録コードが正しくないか、使用済みか、期限切れです。管理者に新しいコードを依頼してください。",
        "identity.help": "ログイン失敗によるロックの解除、認証アプリのないアカウントへの登録コードの発行、スマートフォン紛失時の認証アプリのリセットを行います。すべて監査記録に残り、リセットするとそのアカウントはログアウトされます。",
        "identity.done.reset_totp": "認証アプリをリセットし、アカウントをログアウトしました。下の登録コードを本人に渡してください。",
        "identity.code.title": "{user} の登録コード",
        "identity.code.label": "登録コード（24 時間有効、1 回のみ）",
        "identity.code.once": "このコードは今だけ表示されます。直接手渡すか、本人の内線にかけ直して読み上げてください。",
        "identity.code.live": "登録コード発行済み",
        "identity.code.issue": "登録コード",
        "identity.unenrolled.title": "{n} 件のアカウントはまだログインできません：認証アプリ未登録",
        "identity.unenrolled.help": "認証アプリを設定するには、それぞれ管理者からの登録コードが必要です。",
    }
)
ZH.update(
    {
        "totp.enrol.help": "此帳號尚未設定驗證器。請在驗證器 App（手機或醫院發放的驗證裝置）以金鑰新增帳號並輸入下方金鑰，或在手機上開啟連結。然後輸入管理者給您的註冊碼與 App 顯示的代碼。",
        "totp.enrol.code": "管理者提供的註冊碼",
        "totp.enrol.none": "此帳號沒有驗證器，也沒有有效的註冊碼。請向管理者索取註冊碼（24 小時內有效），然後再次登入。",
        "totp.failed.enrol_code": "註冊碼不正確、已使用或已過期。請向管理者索取新的註冊碼。",
        "identity.help": "解除登入失敗造成的鎖定、為沒有驗證器的帳號發放註冊碼，或在手機遺失時重設驗證器。每個動作都記錄於稽核紀錄；重設會使該帳號登出。",
        "identity.done.reset_totp": "驗證器已重設，帳號已登出。請將下方註冊碼交給本人。",
        "identity.code.title": "{user} 的註冊碼",
        "identity.code.label": "註冊碼（24 小時內有效，僅能使用一次）",
        "identity.code.once": "此代碼只在此時顯示。請當面交付，或回撥本人分機唸出。",
        "identity.code.live": "已發放註冊碼",
        "identity.code.issue": "註冊碼",
        "identity.unenrolled.title": "{n} 個帳號尚無法登入：未設定驗證器",
        "identity.unenrolled.help": "每個帳號都需要管理者發放的註冊碼才能設定驗證器。",
    }
)

# D-279: the forced first change, the per-address wait, the second factor at signing
EN.update(
    {
        "login.slowed": "Too many failed sign-ins from this computer's address. Wait {n} second(s) and try again. No account was locked by this.",
        "account.must_change": "An administrator set this password, so only you may choose the next one: set your own password now. Nothing else opens until you do.",
        "problem.h.account.must_change": "Set your own password first",
        "problem.why.account.must_change": "Open My account (/account) and set your own password.",
        "account.err.same": "Choose a new password, not the one you were given.",
        "edc.sign.otp": "Code from your authenticator app",
        "edc.err.edc.otp": "The authenticator code is not right, or it was used already. Nothing was signed.",
        "edc.err.edc.must_change": "Set your own password on My account before you sign. Nothing was signed.",
    }
)
JA.update(
    {
        "login.slowed": "このコンピューターのアドレスからのログイン失敗が多すぎます。{n} 秒待ってからもう一度お試しください。これによってロックされたアカウントはありません。",
        "account.must_change": "このパスワードは管理者が設定したものです。次のパスワードはご本人だけが決めます。今すぐご自分のパスワードを設定してください。設定するまで他の画面は開きません。",
        "problem.h.account.must_change": "まずご自分のパスワードを設定してください",
        "problem.why.account.must_change": "「マイアカウント」（/account）を開き、ご自分のパスワードを設定してください。",
        "account.err.same": "渡されたパスワードではなく、新しいパスワードを選んでください。",
        "edc.sign.otp": "認証アプリのコード",
        "edc.err.edc.otp": "認証コードが違うか、すでに使われています。署名していません。",
        "edc.err.edc.must_change": "署名の前に「マイアカウント」でご自分のパスワードを設定してください。署名していません。",
    }
)
ZH.update(
    {
        "login.slowed": "此電腦位址的登入失敗次數過多。請等待 {n} 秒後再試。沒有任何帳號因此被鎖定。",
        "account.must_change": "此密碼由管理者設定，下一個密碼只能由您本人決定：請立即設定您自己的密碼。設定完成前無法開啟其他頁面。",
        "problem.h.account.must_change": "請先設定您自己的密碼",
        "problem.why.account.must_change": "請開啟「我的帳號」（/account）並設定您自己的密碼。",
        "account.err.same": "請選擇新密碼，而不是您收到的密碼。",
        "edc.sign.otp": "驗證器 App 的代碼",
        "edc.err.edc.otp": "驗證碼不正確或已被使用。未簽章。",
        "edc.err.edc.must_change": "簽章前請先在「我的帳號」設定您自己的密碼。未簽章。",
    }
)

# D-447 (T-109b): password history and the operator's breached-password list
EN.update(
    {
        "account.err.reused": "You used this password recently. Choose one that is not among your last five.",
        "account.err.breached": "This password is on a list of passwords known from data breaches. Choose another one.",
        "account.err.breached_list": "The list of breached passwords on this box cannot be read, so no new password can be checked. Ask the box's operator.",
    }
)
JA.update(
    {
        "account.err.reused": "このパスワードは最近使われました。直近5回に使っていないパスワードを選んでください。",
        "account.err.breached": "このパスワードは、情報漏えいで知られたパスワードの一覧にあります。別のパスワードを選んでください。",
        "account.err.breached_list": "このボックスの漏えいパスワード一覧を読めないため、新しいパスワードを確認できません。運用担当者に連絡してください。",
    }
)
ZH.update(
    {
        "account.err.reused": "您最近使用過此密碼。請選擇不在最近五次之中的密碼。",
        "account.err.breached": "此密碼在已知外洩密碼的清單中。請選擇其他密碼。",
        "account.err.breached_list": "無法讀取此設備上的外洩密碼清單，因此無法檢查新密碼。請聯絡設備管理者。",
    }
)
