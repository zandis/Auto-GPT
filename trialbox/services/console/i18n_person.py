"""The words of a person's state (D-1221): ``person.state.<name>`` for every name of ``console.person_state.STATES``,
in en, zh-TW and ja. The older key families that name the same states (the participant record's ``life.state.*`` and
the screening log's ``registry.status.*``) are not written again: :func:`alias`
copies these words under them, so one state reads the same on every page, sheet and mail. Joined into
``console.i18n`` (merged with plain ``dict.update``)."""

from __future__ import annotations

from console.person_state import FROM_LIFE, FROM_REGISTRY

EN: dict[str, str] = {
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
    "person.no_contact": "No contact step: this person is {state}.",
}

JA: dict[str, str] = {
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
    "person.no_contact": "連絡の記録はありません：この人は「{state}」です。",
}

ZH: dict[str, str] = {
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
    "person.no_contact": "不需聯絡步驟：此人目前為「{state}」。",
}

#: the older key families and the person state each of their names is
ALIASES: dict[str, dict[str, str]] = {
    "life.state.": FROM_LIFE,
    "registry.status.": FROM_REGISTRY,
}


def alias(cat: dict[str, str], words: dict[str, str]) -> None:
    """Write ``words``' state names under the older keys of ``cat``."""
    for prefix, names in ALIASES.items():
        for old, name in names.items():
            cat[prefix + old] = words["person.state." + name]
