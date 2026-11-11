# ruff: noqa: E501 - one string per line, as in the other catalogues
"""T-511 (D-398): the PoC-path words the walk found missing (TB-DR-02a UX-029 help half, UX-016, UX-010).

The help panel's text for the candidate, referral and EDC pages; the referral form's two select prompts; and the
words the EDC review page shows instead of codes (standard item names, common choice words, readable source lines,
the next step after "no REDCap record"). Joined into ``console.i18n`` by ``console.i18n_home``. Each language has the
same keys."""

from __future__ import annotations

EN: dict[str, str] = {
    # help panel: "This page" for the PoC pages that fell back to the generic text
    "help.page.candidates": "The patients across the hospital who may fit this study. Open one to see each criterion and ask the treating doctor.",
    "help.page.referrals": "Every request to a treating doctor for this study, and the doctor's answer. Approach waits until the doctor agrees.",
    "help.page.edc": "Values TrialBox drafted for REDCap from the hospital record. Check each one against its source, sign, then send.",
    # referral form (UX-016): the prompts of the two selects
    "team.ref.choose_doctor": "Choose a doctor",
    "team.ref.choose_department": "Choose a department",
    # EDC review (UX-010): standard item names by CDASH variable (and test), used when the dictionary has none in the reader's language
    "edc.var.DM.BRTHDAT": "Birth date",
    "edc.var.DM.SEX": "Sex",
    "edc.var.VS.VSORRES.WEIGHT": "Body weight",
    "edc.var.VS.VSORRES.HEIGHT": "Height",
    "edc.var.VS.VSORRES.BMI": "Body mass index",
    "edc.var.VS.VSORRES.SYSBP": "Systolic blood pressure",
    "edc.var.VS.VSORRES.DIABP": "Diastolic blood pressure",
    "edc.var.VS.VSORRES.PULSE": "Pulse",
    "edc.var.VS.VSORRES.TEMP": "Body temperature",
    "edc.var.LB.LBORRES.URATE": "Serum uric acid",
    "edc.var.LB.LBORRES.CREAT": "Serum creatinine",
    # EDC review: common choice words, used when the dictionary has no choice label in the reader's language
    "edc.word.male": "Male",
    "edc.word.female": "Female",
    "edc.word.yes": "Yes",
    "edc.word.no": "No",
    "edc.word.true": "True",
    "edc.word.false": "False",
    "edc.word.unknown": "Unknown",
    # EDC review: where a drafted value came from, in words
    "edc.src.patient": "Patient record",
    "edc.src.observation": "Test or measurement",
    "edc.src.condition": "Condition record",
    "edc.src.medication": "Medication record",
    "edc.src.document": "Clinical note",
    "edc.src.detail": "Record reference",
    "edc.var.name": "REDCap variable",
    # EDC send result (UX-010): what to do when REDCap has no record for the subject
    "edc.sent.no_record_next": "Create the record for this screening number in REDCap first, then send again.",
}

JA: dict[str, str] = {
    "help.page.candidates": "院内でこの試験に合う可能性のある患者です。開くと基準ごとの根拠が見え、主治医に確認を依頼できます。",
    "help.page.referrals": "この試験で主治医に出した確認の依頼と、その回答です。主治医が同意するまで「声をかける」は待ちます。",
    "help.page.edc": "病院の記録から TrialBox が REDCap 用に下書きした値です。一つずつ原資料と照らして確認し、署名してから送信します。",
    "team.ref.choose_doctor": "医師を選んでください",
    "team.ref.choose_department": "診療科を選んでください",
    "edc.var.DM.BRTHDAT": "生年月日",
    "edc.var.DM.SEX": "性別",
    "edc.var.VS.VSORRES.WEIGHT": "体重",
    "edc.var.VS.VSORRES.HEIGHT": "身長",
    "edc.var.VS.VSORRES.BMI": "BMI（体格指数）",
    "edc.var.VS.VSORRES.SYSBP": "収縮期血圧",
    "edc.var.VS.VSORRES.DIABP": "拡張期血圧",
    "edc.var.VS.VSORRES.PULSE": "脈拍",
    "edc.var.VS.VSORRES.TEMP": "体温",
    "edc.var.LB.LBORRES.URATE": "血清尿酸値",
    "edc.var.LB.LBORRES.CREAT": "血清クレアチニン",
    "edc.word.male": "男性",
    "edc.word.female": "女性",
    "edc.word.yes": "はい",
    "edc.word.no": "いいえ",
    "edc.word.true": "真",
    "edc.word.false": "偽",
    "edc.word.unknown": "不明",
    "edc.src.patient": "患者基本情報",
    "edc.src.observation": "検査・測定",
    "edc.src.condition": "病名の記録",
    "edc.src.medication": "処方の記録",
    "edc.src.document": "診療記録",
    "edc.src.detail": "記録の参照番号",
    "edc.var.name": "REDCap の変数名",
    "edc.sent.no_record_next": "先に REDCap でこのスクリーニング番号のレコードを作成してから、もう一度送信してください。",
}

ZH: dict[str, str] = {
    "help.page.candidates": "全院可能符合本試驗的病人。開啟後可看到每項條件的依據，並向主治醫師提出確認。",
    "help.page.referrals": "本試驗向主治醫師提出的每一筆確認請求與醫師的回覆。醫師同意前，「邀請」會暫停。",
    "help.page.edc": "TrialBox 依醫院紀錄為 REDCap 預填的值。請逐一對照原始資料確認、簽章後再送出。",
    "team.ref.choose_doctor": "請選擇醫師",
    "team.ref.choose_department": "請選擇科別",
    "edc.var.DM.BRTHDAT": "出生日期",
    "edc.var.DM.SEX": "性別",
    "edc.var.VS.VSORRES.WEIGHT": "體重",
    "edc.var.VS.VSORRES.HEIGHT": "身高",
    "edc.var.VS.VSORRES.BMI": "身體質量指數",
    "edc.var.VS.VSORRES.SYSBP": "收縮壓",
    "edc.var.VS.VSORRES.DIABP": "舒張壓",
    "edc.var.VS.VSORRES.PULSE": "脈搏",
    "edc.var.VS.VSORRES.TEMP": "體溫",
    "edc.var.LB.LBORRES.URATE": "血清尿酸",
    "edc.var.LB.LBORRES.CREAT": "血清肌酸酐",
    "edc.word.male": "男",
    "edc.word.female": "女",
    "edc.word.yes": "是",
    "edc.word.no": "否",
    "edc.word.true": "是",
    "edc.word.false": "否",
    "edc.word.unknown": "不明",
    "edc.src.patient": "病人基本資料",
    "edc.src.observation": "檢驗或量測",
    "edc.src.condition": "疾病紀錄",
    "edc.src.medication": "用藥紀錄",
    "edc.src.document": "病歷記載",
    "edc.src.detail": "紀錄參照編號",
    "edc.var.name": "REDCap 變數名稱",
    "edc.sent.no_record_next": "請先在 REDCap 建立此篩選編號的紀錄，再重新送出。",
}
