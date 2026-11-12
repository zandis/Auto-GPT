# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of the PoC demonstration mode (T-502, D-328): the banner, the footer line, the refusal page and the
acknowledgement of ``docs/plan/27-poc-plan.md`` §9.3. Joined into ``console.i18n`` by ``console.demo_guard``.

The Japanese and Traditional Chinese acknowledgement lines are the drafts of 27-poc-plan §9.3."""

from __future__ import annotations

EN: dict[str, str] = {
    "demo.banner": "Demonstration with synthetic data only. Not for clinical use. Not a medical device. Do not enter any patient information.",
    "demo.foot": "Proof-of-concept demonstration · synthetic data only · not for clinical use · not a medical device",
    "demo.refused": "This demonstration does not accept uploaded files or pasted chart text. Every patient in it is synthetic; nothing from a real record may be entered here.",
    "problem.h.demo.refused": "Not accepted in the demonstration",
    "problem.why.demo.refused": "Nothing was stored. Use the synthetic patients that are already loaded.",
    "demo.ack.need": "Accept the demonstration acknowledgement first.",
    "problem.h.demo.ack.need": "Acknowledgement needed",
    "demo.ack.title": "Before you start: the acknowledgement",
    "demo.ack.intro": "I have read the TrialBox proof-of-concept data-handling statement ({version}).",
    "demo.ack.i1": "I understand that all patient data in the demonstration is synthetic or public.",
    "demo.ack.i2": "I will not enter, paste, upload or describe any real patient's information.",
    "demo.ack.i3": "I will not use any output for patient care, eligibility decisions, consent or trial records.",
    "demo.ack.i4": "I understand the software is pre-release, not validated and not a medical device, and that its outputs may be wrong.",
    "demo.ack.i5": "I agree that my account data, activity logs and feedback are used to run the test and improve the product, as the statement says.",
    "demo.ack.o1": "(optional) I agree to screen recording in feedback sessions.",
    "demo.ack.o2": "(optional) I agree that my feedback may be quoted with my name.",
    "demo.ack.who": "Accepted as {user} ({role}). The time and the statement's version are kept with your account.",
    "demo.ack.accept": "I accept",
    "demo.ack.missing": "Tick each of the five statements to go on. The two optional ones may stay empty.",
}

JA: dict[str, str] = {
    "demo.banner": "合成データのみのデモ環境です。診療には使用できません。医療機器ではありません。患者さんの情報は入力しないでください。",
    "demo.foot": "概念実証用デモ · 合成データのみ · 診療用ではありません · 医療機器ではありません",
    "demo.refused": "このデモ環境ではファイルのアップロードとカルテ本文の貼り付けを受け付けません。登録されている患者はすべて合成データです。実在の記録の内容はここに入力できません。",
    "problem.h.demo.refused": "デモ環境では受け付けません",
    "problem.why.demo.refused": "何も保存されていません。登録済みの合成患者をお使いください。",
    "demo.ack.need": "先にデモ環境の確認事項に同意してください。",
    "problem.h.demo.ack.need": "確認事項への同意が必要です",
    "demo.ack.title": "開始前の確認事項",
    "demo.ack.intro": "TrialBox 概念実証のデータ取扱説明（{version}）を読みました。",
    "demo.ack.i1": "本デモ環境の患者データはすべて合成データまたは公開データであることを理解しています。",
    "demo.ack.i2": "実在の患者さんの情報は、入力・貼り付け・アップロード・記述のいずれも行いません。",
    "demo.ack.i3": "出力を診療、適格性の判断、同意取得、治験記録に用いません。",
    "demo.ack.i4": "本ソフトウェアは開発中であり、バリデーション未了で、医療機器ではなく、出力が誤っている可能性があることを理解しています。",
    "demo.ack.i5": "アカウント情報、操作ログ、フィードバックが、説明のとおり試用の運営と製品改善のために利用されることに同意します。",
    "demo.ack.o1": "（任意）フィードバックの場での画面録画に同意します。",
    "demo.ack.o2": "（任意）フィードバックを氏名付きで引用することに同意します。",
    "demo.ack.who": "{user}（{role}）として同意します。日時と説明の版はアカウントとともに記録されます。",
    "demo.ack.accept": "同意する",
    "demo.ack.missing": "続けるには 5 つの項目すべてにチェックを入れてください。任意の 2 項目は空欄でもかまいません。",
}

ZH: dict[str, str] = {
    "demo.banner": "本展示環境僅含合成資料。不得用於臨床。非醫療器材。請勿輸入任何病人資訊。",
    "demo.foot": "概念驗證展示 · 僅含合成資料 · 不得用於臨床 · 非醫療器材",
    "demo.refused": "本展示環境不接受檔案上傳或貼上病歷文字。其中所有病人皆為合成資料，不得在此輸入任何真實紀錄的內容。",
    "problem.h.demo.refused": "展示環境不接受此操作",
    "problem.why.demo.refused": "未儲存任何內容。請使用已載入的合成病人。",
    "demo.ack.need": "請先接受展示環境的確認聲明。",
    "problem.h.demo.ack.need": "需要確認聲明",
    "demo.ack.title": "開始前的確認聲明",
    "demo.ack.intro": "本人已閱讀 TrialBox 概念驗證資料處理說明（{version}）。",
    "demo.ack.i1": "本人了解本展示環境之病人資料皆為合成資料或公開資料。",
    "demo.ack.i2": "本人不輸入、貼上、上傳或描述任何真實病人之資訊。",
    "demo.ack.i3": "本人不將任何輸出用於病人照護、決定收案資格、同意取得或試驗紀錄。",
    "demo.ack.i4": "本人了解本軟體為開發中版本，尚未完成確效，非醫療器材，其輸出可能有誤。",
    "demo.ack.i5": "本人同意帳號資料、操作紀錄與回饋意見依說明用於本次試用之執行與產品改善。",
    "demo.ack.o1": "（選填）本人同意回饋會議中錄製螢幕。",
    "demo.ack.o2": "（選填）本人同意回饋意見得具名引用。",
    "demo.ack.who": "以 {user}（{role}）身分接受。時間與說明版本隨帳號記錄。",
    "demo.ack.accept": "我接受",
    "demo.ack.missing": "請勾選全部五項聲明後繼續。兩個選填項目可不勾選。",
}
