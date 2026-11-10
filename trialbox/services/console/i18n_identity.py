# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of D-192 (the TOTP step, the OIDC sign-in, the recovery page). Joined into ``console.i18n`` by
``console.identity`` when it is imported."""

from __future__ import annotations

EN: dict[str, str] = {
    "login.oidc": "Sign in with the hospital account",
    "login.oidc.failed": "The hospital sign-in did not complete. Try again, or ask the administrator to check your "
    "groups.",
    "login.local": "Or sign in with a TrialBox account",
    "totp.title": "Second step: authenticator code",
    "totp.code": "6-digit code from your authenticator app",
    "totp.submit": "Continue",
    "totp.enrol.title": "Set up your authenticator",
    "totp.enrol.help": "This account has no authenticator yet. In an authenticator app (on your phone or a hospital "
    "token), add an account by key and type the key below, or open the link on the phone. Then enter the code the app "
    "shows.",
    "totp.enrol.key": "Key",
    "totp.enrol.link": "Link for the authenticator app",
    "totp.failed.wrong": "That code is not right. Check the phone's clock and try the newest code.",
    "totp.failed.replay": "That code was used already. Wait for the next code.",
    "totp.cancel": "Start again",
    "oidc.done": "Signed in. Opening TrialBox.",
    "oidc.continue": "Continue",
    "identity.title": "Sign-in and recovery",
    "identity.help": "Lift a lock after failed sign-ins, or reset an authenticator when a phone is lost. Both are "
    "recorded in the audit trail and sign the account out.",
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
    "identity.done.reset_totp": "The authenticator is reset. The person sets up a new one at the next sign-in.",
    "identity.confirm.reset": "Reset the authenticator of {user}? They are signed out and set up a new authenticator "
    "at their next sign-in. Check who is asking before you do this.",
}
JA: dict[str, str] = {
    "login.oidc": "病院アカウントでログイン",
    "login.oidc.failed": "病院アカウントでのログインが完了しませんでした。もう一度試すか、管理者にグループの確認を依頼してください。",
    "login.local": "または TrialBox アカウントでログイン",
    "totp.title": "第 2 段階：認証アプリのコード",
    "totp.code": "認証アプリに表示される 6 桁のコード",
    "totp.submit": "続ける",
    "totp.enrol.title": "認証アプリの設定",
    "totp.enrol.help": "このアカウントにはまだ認証アプリが登録されていません。認証アプリ（スマートフォンまたは病院のトークン）で"
    "キーを使ってアカウントを追加し、下のキーを入力するか、スマートフォンでリンクを開いてください。その後、アプリに表示されたコードを入力してください。",
    "totp.enrol.key": "キー",
    "totp.enrol.link": "認証アプリ用のリンク",
    "totp.failed.wrong": "コードが正しくありません。スマートフォンの時刻を確認し、最新のコードを入力してください。",
    "totp.failed.replay": "このコードは使用済みです。次のコードを待ってください。",
    "totp.cancel": "最初からやり直す",
    "oidc.done": "ログインしました。TrialBox を開いています。",
    "oidc.continue": "続ける",
    "identity.title": "ログインと復旧",
    "identity.help": "ログイン失敗によるロックの解除、またはスマートフォン紛失時の認証アプリのリセットを行います。どちらも監査記録に残り、"
    "そのアカウントはログアウトされます。",
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
    "identity.done.reset_totp": "認証アプリをリセットしました。次回のログイン時に新しい認証アプリを設定します。",
    "identity.confirm.reset": "{user} の認証アプリをリセットしますか？ログアウトされ、次回のログイン時に新しい認証アプリを設定します。"
    "依頼者が本人であることを確認してから実行してください。",
}
ZH: dict[str, str] = {
    "login.oidc": "以醫院帳號登入",
    "login.oidc.failed": "醫院帳號登入未完成。請再試一次，或請管理者確認您的群組。",
    "login.local": "或以 TrialBox 帳號登入",
    "totp.title": "第二步：驗證器代碼",
    "totp.code": "驗證器 App 顯示的 6 位數代碼",
    "totp.submit": "繼續",
    "totp.enrol.title": "設定驗證器",
    "totp.enrol.help": "此帳號尚未設定驗證器。請在驗證器 App（手機或醫院發放的驗證裝置）以金鑰新增帳號並輸入下方金鑰，或在手機上開啟連結。"
    "然後輸入 App 顯示的代碼。",
    "totp.enrol.key": "金鑰",
    "totp.enrol.link": "驗證器 App 的連結",
    "totp.failed.wrong": "代碼不正確。請確認手機時間並輸入最新的代碼。",
    "totp.failed.replay": "此代碼已使用過。請等待下一個代碼。",
    "totp.cancel": "重新開始",
    "oidc.done": "已登入。正在開啟 TrialBox。",
    "oidc.continue": "繼續",
    "identity.title": "登入與復原",
    "identity.help": "解除登入失敗造成的鎖定，或在手機遺失時重設驗證器。兩者都記錄於稽核紀錄，且該帳號會被登出。",
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
    "identity.done.reset_totp": "驗證器已重設。下次登入時將設定新的驗證器。",
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
