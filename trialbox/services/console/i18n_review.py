"""Strings of the pre-release review fixes of 2026-11-09, wave 1b (D-143): the "Excluded patients and why" page
(P-04) and the confirmation steps (P-10). Every key in all three languages, from the glossary's words."""

from __future__ import annotations

EN: dict[str, str] = {
    "ex.title": "Criteria not matched",
    "ex.help": "Every patient whose records did not match a criterion on the latest screening run, with the criterion, "
    "where the answer came from and its evidence. The investigator decides; this list is an input to that decision. "
    "Look through some of them each week; if one looks wrong, send it to review.",
    "ex.none": "On the latest screening run no patient's records failed to match a criterion.",
    "ex.no_run": "No screening run with a criteria-not-matched list yet. Run screening again to see it.",
    "ex.run": "Run of {day} (records of {snapshot}): criteria not matched for {n} patients.",
    "ex.col.patient": "Patient",
    "ex.col.criterion": "Criterion not matched",
    "ex.col.source": "Where the answer came from",
    "ex.col.evidence": "Evidence",
    "ex.src.coded": "the coded records",
    "ex.src.fact": "a confirmed fact",
    "ex.src.notes": "the notes, which may speak against the criterion",
    "ex.src.rule": "a rule of the run",
    "ex.src.records": "the records (whether a person confirmed them could not be read)",
    "ex.unread.facts": "For this run it could not be read whether an answer came from a fact that a person "
    'confirmed. Such answers are marked "the records".',
    "ex.unread.values": "For this run the values behind the coded answers could not be read. The answers stand.",
    "ex.rule.consent": "no research-contact consent (never listed)",
    "ex.rule.scope": "outside the run's scope (clinic, doctor or visit window)",
    "ex.filter": "Show:",
    "ex.filter.all": "all",
    "ex.records": "{n} records",
    "ex.wrong": "This is wrong, send to review",
    "ex.wrong.note": "What looks wrong (optional)",
    "ex.sent": "Sent to review by {who} at {at}",
    "ex.sent.done": "Sent to review. It is recorded with your name; the study team sees it at the top of this page, "
    "and the patient is on the weekly list again until a mark is recorded.",
    "ex.sent.title": "Sent to review: {n}",
    "ex.link": "Criteria not matched",
    "confirm.title": "Please confirm",
    "confirm.yes": "Yes, do it",
    "confirm.no": "No, go back",
    "confirm.disable": "Disable the account {user}? They are signed out everywhere at once and cannot sign in until "
    "an administrator enables the account again.",
    "confirm.keep": "Keep TrialBox's value? On the next sync TrialBox writes its value over the one in {source}.",
    "confirm.take": "Take the value from {source}? TrialBox's value is replaced; the old value stays in the history.",
    "confirm.detach": "Detach REDCap from this study? TrialBox stops reading from and writing to the project. The "
    "data already in TrialBox stays.",
    "confirm.approve_all": "Approve all {n} criteria in one step? Each criterion is recorded as approved with your "
    "name.",
    # T-507 (D-309): criterion words in the page language, the label step at approval, the test model
    "crit.original": "As written in the protocol",
    # T-515 (D-323, review UX-007): where a first or second check came from, and what the two checks are
    "note.against": "A note may speak against {criterion}. Not excluded. Please check.",
    "note.against.count": "Patients with a note that may speak against a criterion: {n}. None is excluded.",
    "opinion.explain": "First check and second check: two different models read the same notes, each on its own. "
    "When they disagree the answer stays unknown and a person decides.",
    "opinion.disagree": "the two checks disagree",
    "opinion.src.synthetic": "synthetic example",
    "opinion.src.synthetic.why": "Made up for the demonstration to show how the two checks look. No model wrote it.",
    "opinion.src.recorded": "recorded run",
    "opinion.src.recorded.why": "Recorded from a run of the real model pair on the demonstration records, "
    "not answered on this box.",
    "model.test": "test model",
    "model.test.why": "This answer comes from the test model, which gives fixed answers to the demonstration notes. "
    "It says nothing about how well a real model reads notes.",
    "model.unqualified": "model not qualified on this hardware",
    "model.unqualified.why": "The model pair that read the notes has no qualification record on this box yet. It is "
    "triage only: a person decides on every patient.",
    "s20.labels.missing": "Give a short label in {language} to the {n} criteria marked below before approving; "
    "the lists show the label with the study's own words.",
    "s20.label.missing": "No label in {language} yet",
    "s20.label.shipped": "Label that comes with the study's criteria; save it as is or change it.",
}

JA: dict[str, str] = {
    "ex.title": "基準に合致しない患者",
    "ex.help": "最新のスクリーニングで記録が基準に合致しなかったすべての患者を、合致しなかった基準、"
    "判断の出どころ、根拠とともに表示します。判断するのは研究責任者で、この一覧はその材料です。"
    "毎週いくつか確認し、誤りと思われるものは確認に回してください。",
    "ex.none": "最新のスクリーニングで基準に合致しなかった患者はいません。",
    "ex.no_run": "基準に合致しない患者の一覧があるスクリーニングはまだありません。"
    "もう一度スクリーニングを行うと表示されます。",
    "ex.run": "{day} の処理（{snapshot} 時点の記録）：基準に合致しない患者 {n} 名。",
    "ex.col.patient": "患者",
    "ex.col.criterion": "合致しなかった基準",
    "ex.col.source": "判断の出どころ",
    "ex.col.evidence": "根拠",
    "ex.src.coded": "コード化データ（病名・検査・処方）",
    "ex.src.fact": "確認済みの情報",
    "ex.src.notes": "カルテ記載（基準に反する可能性）",
    "ex.src.rule": "処理の規則",
    "ex.src.records": "記録（人が確認したかどうかは読めませんでした）",
    "ex.unread.facts": "この処理では、判断が人が確認した情報によるものかどうかを読めませんでした。"
    "該当する判断は「記録」と表示しています。",
    "ex.unread.values": "この処理では、コード化データの値を読めませんでした。判断は変わりません。",
    "ex.rule.consent": "研究への連絡の同意なし（一覧に載せない）",
    "ex.rule.scope": "処理の範囲外（外来、医師、来院の期間）",
    "ex.filter": "表示：",
    "ex.filter.all": "すべて",
    "ex.records": "記録 {n} 件",
    "ex.wrong": "誤りなので確認に回す",
    "ex.wrong.note": "誤りと思われる点（任意）",
    "ex.sent": "{who} が {at} に確認に回しました",
    "ex.sent.done": "確認に回しました。氏名とともに記録され、試験チームにはこのページの上部に表示されます。"
    "患者は印が記録されるまで週次リストに再び表示されます。",
    "ex.sent.title": "確認に回した患者：{n} 名",
    "ex.link": "基準に合致しない患者",
    "confirm.title": "確認してください",
    "confirm.yes": "はい、実行します",
    "confirm.no": "いいえ、戻ります",
    "confirm.disable": "アカウント {user} を無効にしますか？すべての端末から直ちにログアウトし、"
    "管理者が再び有効にするまでログインできません。",
    "confirm.keep": "TrialBox の値を残しますか？次の同期で TrialBox の値が {source} の値を上書きします。",
    "confirm.take": "{source} の値を取り込みますか？TrialBox の値は置き換わり、以前の値は履歴に残ります。",
    "confirm.detach": "この試験から REDCap を切り離しますか？TrialBox はプロジェクトの読み取りと書き込みをやめます。"
    "TrialBox にあるデータはそのまま残ります。",
    "confirm.approve_all": "{n} 件の基準をまとめて承認しますか？各基準があなたの氏名で承認として記録されます。",
    "crit.original": "プロトコルの原文",
    # T-515 (D-323): 1回目・2回目の確認の出どころ
    "note.against": "記録の文章が{criterion}に反する可能性があります。除外していません。確認してください。",
    "note.against.count": "記録の文章が基準に反する可能性がある患者：{n}名。いずれも除外していません。",
    "opinion.explain": "1回目の確認と2回目の確認：異なる 2 つのモデルが同じ記録をそれぞれ独立に読みます。"
    "読み取りが分かれたときは「不明」のままとし、担当者が判断します。",
    "opinion.disagree": "2 つの確認で読み取りが分かれています",
    "opinion.src.synthetic": "合成した例",
    "opinion.src.synthetic.why": "2 つの確認の見え方を示すためにデモ用に作成した例です。"
    "モデルが書いたものではありません。",
    "opinion.src.recorded": "記録済みの実行結果",
    "opinion.src.recorded.why": "実際のモデルの組でデモ用の記録を読んだ実行結果を記録したもので、"
    "この環境で回答したものではありません。",
    "model.test": "テスト用モデル",
    "model.test.why": "この回答は、デモ用の記録に固定の回答を返すテスト用モデルによるものです。"
    "実際のモデルがカルテ記載をどの程度正しく読めるかは示しません。",
    "model.unqualified": "このハードウェアで適格性未確認のモデル",
    "model.unqualified.why": "カルテ記載を読んだモデルの組には、この環境での適格性確認の記録がまだありません。"
    "候補の振り分けのみに使い、判断はすべて人が行います。",
    "s20.labels.missing": "承認の前に、下の印のある {n} 件の基準に{language}の短い表示名を付けてください。"
    "一覧では表示名と試験の原文が並べて表示されます。",
    "s20.label.missing": "{language}の表示名がまだありません",
    "s20.label.shipped": "試験の基準に付属する表示名です。そのまま保存するか、変更してください。",
}

ZH: dict[str, str] = {
    "ex.title": "未符合條件之病人",
    "ex.help": "列出最近一次篩選中紀錄未符合某條件的所有病人，以及未符合的條件、判斷的來源與依據。"
    "由試驗主持人判斷，本清單是判斷的參考。請每週抽看幾位；若有看起來不對的，請送回審閱。",
    "ex.none": "最近一次篩選沒有未符合條件的病人。",
    "ex.no_run": "尚無附未符合條件清單的篩選。請重新執行篩選以查看。",
    "ex.run": "{day} 的作業（{snapshot} 的紀錄）：{n} 位病人未符合條件。",
    "ex.col.patient": "病人",
    "ex.col.criterion": "未符合的條件",
    "ex.col.source": "判斷的來源",
    "ex.col.evidence": "依據",
    "ex.src.coded": "編碼病歷",
    "ex.src.fact": "已確認的資料",
    "ex.src.notes": "病歷文字（可能不利於該條件）",
    "ex.src.rule": "作業的規則",
    "ex.src.records": "病歷紀錄（是否經人員確認，無法讀取）",
    "ex.unread.facts": "這次作業無法讀取判斷是否來自人員確認的資料；這類判斷標示為「病歷紀錄」。",
    "ex.unread.values": "這次作業無法讀取編碼病歷的數值；判斷不變。",
    "ex.rule.consent": "無研究聯絡同意（不列入名單）",
    "ex.rule.scope": "不在作業範圍內（門診、醫師或就診期間）",
    "ex.filter": "顯示：",
    "ex.filter.all": "全部",
    "ex.records": "{n} 筆紀錄",
    "ex.wrong": "這是錯的，送回審閱",
    "ex.wrong.note": "看起來不對的地方（選填）",
    "ex.sent": "{who} 已於 {at} 送回審閱",
    "ex.sent.done": "已送回審閱，並連同您的姓名記錄；試驗團隊會在本頁上方看到；"
    "在記錄標記之前，病人會再次出現在每週名單上。",
    "ex.sent.title": "已送回審閱：{n} 位",
    "ex.link": "未符合條件之病人",
    "confirm.title": "請確認",
    "confirm.yes": "是，執行",
    "confirm.no": "否，返回",
    "confirm.disable": "要停用帳號 {user} 嗎？該人員會立即在所有裝置登出，在管理員重新啟用前無法登入。",
    "confirm.keep": "要保留 TrialBox 的數值嗎？下次同步時，TrialBox 的數值會覆寫 {source} 中的數值。",
    "confirm.take": "要採用 {source} 的數值嗎？TrialBox 的數值會被取代，舊數值保留在歷程中。",
    "confirm.detach": "要將 REDCap 從本試驗分離嗎？TrialBox 會停止讀取與寫入該專案。已在 TrialBox 中的資料會保留。",
    "confirm.approve_all": "要一次核准全部 {n} 項條件嗎？每項條件都會以您的姓名記錄為已核准。",
    "crit.original": "計畫書原文",
    # T-515 (D-323)：第一次與第二次確認的來源
    "note.against": "病歷文字可能不利於{criterion}。未排除。請確認。",
    "note.against.count": "病歷文字可能不利於某項條件的病人：{n} 位。皆未排除。",
    "opinion.explain": "第一次確認與第二次確認：兩個不同的模型各自獨立閱讀同一份紀錄。"
    "兩者判斷不一致時，結果維持「不明」，由人員判斷。",
    "opinion.disagree": "兩次確認的判斷不一致",
    "opinion.src.synthetic": "合成範例",
    "opinion.src.synthetic.why": "為示範兩次確認的呈現方式而製作的範例，並非由模型產生。",
    "opinion.src.recorded": "已記錄的執行結果",
    "opinion.src.recorded.why": "以實際的模型組合閱讀示範用紀錄後所記錄的結果，並非在此系統上回答。",
    "model.test": "測試用模型",
    "model.test.why": "此回答來自測試用模型，它對示範用紀錄回傳固定答案，無法說明實際模型閱讀病歷的能力。",
    "model.unqualified": "模型尚未在此硬體完成資格驗證",
    "model.unqualified.why": "閱讀病歷的模型組合在此系統上尚無資格驗證紀錄。僅用於初步分流，每位病人都由人員判斷。",
    "s20.labels.missing": "核准前，請為下方標示的 {n} 項條件加上{language}簡短標籤；名單會將標籤與試驗原文並列顯示。",
    "s20.label.missing": "尚無{language}標籤",
    "s20.label.shipped": "此標籤隨試驗條件提供；可直接儲存或修改。",
}
