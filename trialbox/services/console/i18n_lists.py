"""Strings of J-5 (D-1223): the two lists of people, Candidates and Participants, behind the flag
``layout.people_lists``: their names, their views, the study picker and the participants' state filter. Merged by
``console.people_lists`` (en, ja, zh-TW); every language has every key."""

from __future__ import annotations

EN: dict[str, str] = {
    "people.candidates": "Candidates",
    "people.participants": "Participants",
    "people.lists": "Lists of people · {rs}",
    "people.views": "Views of {list}",
    "people.view.week": "This week",
    "people.view.cohort": "New members",
    "people.view.referrals": "Doctors and referrals",
    "people.view.registry": "Add and export",
    "people.view.log": "Screening log",
    "people.view.list": "Everyone",
    "people.view.enrolment": "Enrolment and withdrawals",
    "people.pick.title": "{list}: choose a study",
    "people.pick.lead": "Open the list of one study.",
    "people.pick.none": "No study of yours has this list for your role.",
    "people.filter.all": "All states",
    "people.filter.lead": "Show only:",
}

JA: dict[str, str] = {
    "people.candidates": "候補者",
    "people.participants": "被験者",
    "people.lists": "人の一覧 · {rs}",
    "people.views": "{list}の表示",
    "people.view.week": "今週",
    "people.view.cohort": "新しいメンバー",
    "people.view.referrals": "主治医と了承依頼",
    "people.view.registry": "追加と書き出し",
    "people.view.log": "スクリーニングログ",
    "people.view.list": "全員",
    "people.view.enrolment": "登録と中止",
    "people.pick.title": "{list}：試験を選ぶ",
    "people.pick.lead": "試験を選んで一覧を開きます。",
    "people.pick.none": "あなたの役割でこの一覧を開ける試験はありません。",
    "people.filter.all": "すべての段階",
    "people.filter.lead": "絞り込み：",
}

ZH: dict[str, str] = {
    "people.candidates": "候選者",
    "people.participants": "受試者",
    "people.lists": "人員清單 · {rs}",
    "people.views": "{list}的檢視",
    "people.view.week": "本週",
    "people.view.cohort": "新成員",
    "people.view.referrals": "主治醫師與同意徵詢",
    "people.view.registry": "新增與匯出",
    "people.view.log": "篩選紀錄",
    "people.view.list": "全部",
    "people.view.enrolment": "收案與退出",
    "people.pick.title": "{list}：選擇試驗",
    "people.pick.lead": "選擇一個試驗以開啟清單。",
    "people.pick.none": "以您的角色，沒有可開啟此清單的試驗。",
    "people.filter.all": "所有階段",
    "people.filter.lead": "只顯示：",
}
