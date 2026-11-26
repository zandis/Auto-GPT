"""Strings of M8: the page "Screen now" (``console.screen_now``)."""

from __future__ import annotations

EN: dict[str, str] = {
    "screennow.title": "Screen now",
    "screennow.intro": "Screen this study's patients now instead of waiting for the night. The list appears on this "
    "page. It does not replace what the night made; the next night makes its own.",
    "screennow.scope.known": "{n} patients were in scope in the last run.",
    "screennow.scope.unknown": "The number of patients in scope is not known: no earlier run counted them.",
    "screennow.time.known": "Expected time: about {minutes} minutes, from the last measured runs ({per} seconds per "
    "1,000 patients).",
    "screennow.time.unknown": "No run of this study has been measured yet, so the time is not known. This run is "
    "measured.",
    "screennow.ask_scope": "The scope could not be counted. Screening then reads all patients of the study's "
    "departments. Press the button to confirm.",
    "screennow.all_dept": "Screen all patients of the study's departments",
    "screennow.start": "Screen now",
    "screennow.running": "A screening of this study is running (state: {state}). This page refreshes by itself; "
    "you may leave it.",
    "screennow.progress": "The patients done and the notes read are not reported while it runs; the state is the "
    "job's.",
    "screennow.joined": "A screening of this study was already running: your request joined it.",
    "screennow.queued": "The night is running ({n} jobs ahead). Your screening is queued behind them.",
    "screennow.wait.known": "Expected wait: about {minutes} minutes.",
    "screennow.wait.unknown": "The wait is not known: a job ahead has no earlier run to go by.",
    "screennow.done": "Screened now at {at}.",
    "screennow.open_list": "Open the list",
    "screennow.stale": "The data of the last run is from {day}: older than a day.",
    "screennow.failed": 'The last screening failed at the step "{step}". The previous list is kept.',
    "screennow.no_ruleset": "This study has no approved criteria version, so nothing can be screened. Approve its "
    "criteria first.",
    "screennow.not_allowed": "Your role may not start a screening of this study.",
}

JA: dict[str, str] = {
    "screennow.title": "今すぐスクリーニング",
    "screennow.intro": "夜間を待たずに、この試験の患者を今すぐスクリーニングします。一覧はこのページに表示されます。"
    "夜間に作られた一覧は置き換わらず、次の夜間にはその分が作られます。",
    "screennow.scope.known": "前回の実行の対象は {n} 人でした。",
    "screennow.scope.unknown": "対象患者数は不明です。これまでに数えた実行がありません。",
    "screennow.time.known": "見込み時間: 約 {minutes} 分(直近の実測、1,000 人あたり {per} 秒)。",
    "screennow.time.unknown": "この試験の実測がまだないため、時間は不明です。今回の実行を計測します。",
    "screennow.ask_scope": "対象範囲を数えられませんでした。その場合、試験の診療科の全患者を読み込みます。"
    "確認のためボタンを押してください。",
    "screennow.all_dept": "試験の診療科の全患者をスクリーニングする",
    "screennow.start": "今すぐスクリーニング",
    "screennow.running": "この試験のスクリーニングが実行中です(状態: {state})。このページは自動で更新されます。"
    "離れても構いません。",
    "screennow.progress": "実行中は、処理済みの患者数や読み込んだ記録の数"
    "は表示されません。状態は処理そのものの状態です。",
    "screennow.joined": "この試験のスクリーニングはすでに実行中だったため、依頼はそれに合流しました。",
    "screennow.queued": "夜間の処理が実行中です(先行 {n} 件)。スクリーニングはその後に待機します。",
    "screennow.wait.known": "見込み待ち時間: 約 {minutes} 分。",
    "screennow.wait.unknown": "待ち時間は不明です。先行する処理に過去の実行がありません。",
    "screennow.done": "{at} に今すぐスクリーニングを実施しました。",
    "screennow.open_list": "一覧を開く",
    "screennow.stale": "前回の実行のデータは {day} のもので、1 日以上前です。",
    "screennow.failed": "直近のスクリーニングは「{step}」の段階で失敗しました。前の一覧は保たれています。",
    "screennow.no_ruleset": "この試験には承認済みの基準版がないため、スクリーニングできません。"
    "先に基準を承認してください。",
    "screennow.not_allowed": "あなたの役割では、この試験のスクリーニングを開始できません。",
}

ZH: dict[str, str] = {
    "screennow.title": "立即篩選",
    "screennow.intro": "不必等到夜間,現在就篩選此試驗的病人。名單會顯示在此頁。"
    "夜間產生的名單不會被取代,下一個夜間仍會產生自己的名單。",
    "screennow.scope.known": "上次執行的範圍為 {n} 位病人。",
    "screennow.scope.unknown": "範圍內的病人數不明:先前沒有任何執行計算過。",
    "screennow.time.known": "預計時間:約 {minutes} 分鐘,依據最近的實測(每 1,000 位病人 {per} 秒)。",
    "screennow.time.unknown": "此試驗尚無實測,因此時間不明。這次執行會被計時。",
    "screennow.ask_scope": "無法計算範圍。此時會讀取試驗所屬科別的所有病人。請按下按鈕以確認。",
    "screennow.all_dept": "篩選試驗所屬科別的所有病人",
    "screennow.start": "立即篩選",
    "screennow.running": "此試驗的篩選正在執行(狀態:{state})。本頁會自動更新,您可以離開。",
    "screennow.progress": "執行中不會回報已處理的病人數與已讀的紀錄數;狀態為處理本身的狀態。",
    "screennow.joined": "此試驗的篩選原本就在執行,您的要求已併入其中。",
    "screennow.queued": "夜間作業正在執行(前面有 {n} 項)。您的篩選排在它們之後。",
    "screennow.wait.known": "預計等待:約 {minutes} 分鐘。",
    "screennow.wait.unknown": "等待時間不明:前面的處理沒有先前的執行可供參考。",
    "screennow.done": "已於 {at} 立即篩選。",
    "screennow.open_list": "開啟名單",
    "screennow.stale": "上次執行的資料來自 {day},已超過一天。",
    "screennow.failed": "最近一次篩選在「{step}」步驟失敗。先前的名單仍保留。",
    "screennow.no_ruleset": "此試驗沒有已核准的準則版本,無法篩選。請先核准其準則。",
    "screennow.not_allowed": "您的角色不能啟動此試驗的篩選。",
}
