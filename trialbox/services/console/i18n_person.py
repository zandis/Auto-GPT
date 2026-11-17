"""The words of a person's state (D-1221): ``person.state.<name>`` for every name of ``console.person_state.STATES``,
in en, zh-TW and ja. The older key families that name the same states (the participant record's ``life.state.*`` and
the screening log's ``registry.status.*``) are written here with the same words (literals, as ``tools.text_keys``
reads them; a test holds them equal), so one state reads the same on every page, sheet and mail. Joined into
``console.i18n`` (merged with plain ``dict.update``)."""

from __future__ import annotations

EN: dict[str, str] = {
    # the participant record's and the screening log's own key families, in the same words (one state, one
    # name; tests/unit/test_person_state.py holds them equal)
    "life.state.candidate": "On the list",
    "life.state.approached": "Contacted",
    "life.state.consented": "Consented",
    "life.state.enrolled": "Enrolled",
    "life.state.on_study": "On study",
    "life.state.completed": "Completed",
    "life.state.withdrawn": "Withdrawn",
    "life.state.screen_fail": "Screen failure",
    "registry.status.candidate": "On the list",
    "registry.status.contacted": "Contacted",
    "registry.status.consented": "Consented",
    "registry.status.enrolled": "Enrolled",
    "registry.status.screen_fail": "Screen failure",
    "registry.status.declined": "Declined",
    "registry.status.withdrawn": "Withdrawn",
    "person.state.listed": "On the list",
    "person.state.need_info": "Waiting for information",
    "person.state.set_aside": "Set aside",
    "person.state.to_contact": "To contact",
    "person.state.contacted": "Contacted",
    "person.state.not_approached": "Not approached",
    "person.state.declined": "Declined",
    "person.state.screen_fail": "Screen failure",
    "person.state.consented": "Consented",
    "person.state.enrolled": "Enrolled",
    "person.state.on_study": "On study",
    "person.state.completed": "Completed",
    "person.state.withdrawn": "Withdrawn",
    "person.counts": "People by state",
    "person.counts.none": "Nobody has been reviewed, contacted or consented yet.",
    "person.counts.unread": "The state of this study's people could not be read for your account.",
    "person.col.state": "State",
    "person.col.since": "Since",
    "person.state.unknown": "State unknown",
    "outcome.closed": "Not recorded: the study is closed. No contact step is taken in a closed study.",
    "registry.add.exists": "Nothing changed: this person is already on the screening log, in the state “{state}”. "
    "Their state follows the steps that record it; open their row below.",
    "registry.add.no_status": "Not recorded: a state is not chosen here. Add the person without one; their state "
    "then follows the steps that record it.",
    "registry.office.aggregate": "Totals for the whole study; yearly figures need a role that reads the study's list.",
    "outcome.participant": "Not recorded: this person has consented and is a participant. Contact outcomes are for "
    "candidates; record the participant's steps on the participant's page.",
    "outcome.state_unknown": "Not recorded: this person's state could not be read just now, so no contact step is "
    "taken. Try again in a moment.",
    "person.no_contact": "No contact step: this person is {state}.",
}

JA: dict[str, str] = {
    # the participant record's and the screening log's own key families, in the same words (one state, one
    # name; tests/unit/test_person_state.py holds them equal)
    "life.state.candidate": "リスト掲載",
    "life.state.approached": "連絡済み",
    "life.state.consented": "同意取得",
    "life.state.enrolled": "登録",
    "life.state.on_study": "試験参加中",
    "life.state.completed": "試験終了",
    "life.state.withdrawn": "中止",
    "life.state.screen_fail": "スクリーニング不適格",
    "registry.status.candidate": "リスト掲載",
    "registry.status.contacted": "連絡済み",
    "registry.status.consented": "同意取得",
    "registry.status.enrolled": "登録",
    "registry.status.screen_fail": "スクリーニング不適格",
    "registry.status.declined": "辞退",
    "registry.status.withdrawn": "中止",
    "person.state.listed": "リスト掲載",
    "person.state.need_info": "情報待ち",
    "person.state.set_aside": "見合わせ",
    "person.state.to_contact": "連絡予定",
    "person.state.contacted": "連絡済み",
    "person.state.not_approached": "声かけせず",
    "person.state.declined": "辞退",
    "person.state.screen_fail": "スクリーニング不適格",
    "person.state.consented": "同意取得",
    "person.state.enrolled": "登録",
    "person.state.on_study": "試験参加中",
    "person.state.completed": "試験終了",
    "person.state.withdrawn": "中止",
    "person.counts": "状態ごとの人数",
    "person.counts.none": "まだ確認・連絡・同意取得をした人はいません。",
    "person.counts.unread": "このアカウントでは、この試験の人の状態を読めませんでした。",
    "person.col.state": "状態",
    "person.col.since": "この状態になった日",
    "person.state.unknown": "状態不明",
    "outcome.closed": "記録していません：この試験は終了しています。終了した試験では連絡の記録はしません。",
    "registry.add.exists": "変更していません：この人はすでにスクリーニングログにあり、状態は「{state}」です。"
    "状態はそれを記録する手順に従います。下の行を開いてください。",
    "registry.add.no_status": "記録していません：ここでは状態を選びません。状態なしで追加してください。"
    "状態はそれを記録する手順に従います。",
    "registry.office.aggregate": "試験全体の合計です。年ごとの件数は、試験の一覧を読める役割で見てください。",
    "outcome.participant": "記録していません：この人は同意済みの参加者です。連絡結果は候補者のためのものです。"
    "参加者の手順は参加者のページで記録してください。",
    "outcome.state_unknown": "記録していません：いまこの人の状態を読めなかったため、連絡の記録はしません。"
    "少し待ってからもう一度試してください。",
    "person.no_contact": "連絡の記録はありません：この人は「{state}」です。",
}

ZH: dict[str, str] = {
    # the participant record's and the screening log's own key families, in the same words (one state, one
    # name; tests/unit/test_person_state.py holds them equal)
    "life.state.candidate": "在名單上",
    "life.state.approached": "已聯絡",
    "life.state.consented": "已同意",
    "life.state.enrolled": "已收案",
    "life.state.on_study": "試驗進行中",
    "life.state.completed": "已完成試驗",
    "life.state.withdrawn": "退出",
    "life.state.screen_fail": "篩選失敗",
    "registry.status.candidate": "在名單上",
    "registry.status.contacted": "已聯絡",
    "registry.status.consented": "已同意",
    "registry.status.enrolled": "已收案",
    "registry.status.screen_fail": "篩選失敗",
    "registry.status.declined": "婉拒",
    "registry.status.withdrawn": "退出",
    "person.state.listed": "在名單上",
    "person.state.need_info": "等待資料",
    "person.state.set_aside": "暫緩",
    "person.state.to_contact": "待聯絡",
    "person.state.contacted": "已聯絡",
    "person.state.not_approached": "未邀請",
    "person.state.declined": "婉拒",
    "person.state.screen_fail": "篩選失敗",
    "person.state.consented": "已同意",
    "person.state.enrolled": "已收案",
    "person.state.on_study": "試驗進行中",
    "person.state.completed": "已完成試驗",
    "person.state.withdrawn": "退出",
    "person.counts": "各狀態人數",
    "person.counts.none": "尚無人經過審閱、聯絡或同意。",
    "person.counts.unread": "您的帳號無法讀取此試驗人員的狀態。",
    "person.col.state": "狀態",
    "person.col.since": "起始日",
    "person.state.unknown": "狀態不明",
    "outcome.closed": "未記錄：此試驗已結束。已結束的試驗不記錄聯絡。",
    "registry.add.exists": "未變更：此人已在篩選紀錄上，狀態為「{state}」。"
    "狀態依記錄它的步驟而定；請開啟下方此人的列。",
    "registry.add.no_status": "未記錄：此處不選擇狀態。請不帶狀態加入；狀態之後依記錄它的步驟而定。",
    "registry.office.aggregate": "整個試驗的總數；年度數字需要能讀取試驗清單的角色。",
    "outcome.participant": "未記錄：此人已同意，是受試者。聯絡結果只用於候選者；受試者的步驟請在受試者頁面記錄。",
    "outcome.state_unknown": "未記錄：目前無法讀取此人的狀態，因此不記錄聯絡。請稍後再試。",
    "person.no_contact": "不需聯絡步驟：此人目前為「{state}」。",
}
