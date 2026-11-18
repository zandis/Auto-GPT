# ruff: noqa: E501 - one string per line, as in the other catalogues
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
    "people.view.log": "Screening log",
    "people.view.enrolment": "Enrolment and withdrawals",
    "people.pick.title": "{list}: choose a study",
    "people.pick.lead": "Open the list of one study.",
    "people.pick.none": "No study of yours has this list for your role.",
    "people.filter.all": "All states",
    "people.filter.lead": "Show only:",
    "people.view.before": "Before consent",
    "people.view.from": "Consented",
    "people.view.records": "Every record",
    "people.week_all": "This week, all studies",
    "people.working": "A working view: it can show people before and after consent.",
    "people.side.candidates": "Every person of this study with a recorded step before consent (a mark, a contact, a screening-log row, a record). Each is here or under Participants, never both. The patients a screening run found and nobody has acted on yet are under This week.",
    "people.side.participants": "Every person of this study who has consented. Each is here or under Candidates, never both.",
}

JA: dict[str, str] = {
    "people.candidates": "候補者",
    "people.participants": "被験者",
    "people.lists": "人の一覧 · {rs}",
    "people.views": "{list}の表示",
    "people.view.week": "今週",
    "people.view.cohort": "新しいメンバー",
    "people.view.referrals": "主治医と了承依頼",
    "people.view.log": "スクリーニングログ",
    "people.view.enrolment": "登録と中止",
    "people.pick.title": "{list}：試験を選ぶ",
    "people.pick.lead": "試験を選んで一覧を開きます。",
    "people.pick.none": "あなたの役割でこの一覧を開ける試験はありません。",
    "people.filter.all": "すべての段階",
    "people.filter.lead": "絞り込み：",
    "people.view.before": "同意前",
    "people.view.from": "同意後",
    "people.view.records": "全記録",
    "people.week_all": "今週（全試験）",
    "people.working": "作業用の表示：同意の前と後の人が含まれることがあります。",
    "people.side.candidates": "この試験で、同意前の段階が記録された全員です（マーク、連絡、スクリーニングログ、記録）。一人ひとりはここか「被験者」のどちらか一方にだけ載ります。スクリーニングで見つかり、まだ誰も対応していない患者は「今週」にあります。",
    "people.side.participants": "この試験で同意した全員です。一人ひとりはここか「候補者」のどちらか一方にだけ載ります。",
}

ZH: dict[str, str] = {
    "people.candidates": "候選者",
    "people.participants": "受試者",
    "people.lists": "人員清單 · {rs}",
    "people.views": "{list}的檢視",
    "people.view.week": "本週",
    "people.view.cohort": "新成員",
    "people.view.referrals": "主治醫師與同意徵詢",
    "people.view.log": "篩選紀錄",
    "people.view.enrolment": "收案與退出",
    "people.pick.title": "{list}：選擇試驗",
    "people.pick.lead": "選擇一個試驗以開啟清單。",
    "people.pick.none": "以您的角色，沒有可開啟此清單的試驗。",
    "people.filter.all": "所有階段",
    "people.filter.lead": "只顯示：",
    "people.view.before": "同意前",
    "people.view.from": "已同意",
    "people.view.records": "所有紀錄",
    "people.week_all": "本週（所有試驗）",
    "people.working": "工作檢視：可能包含同意前與同意後的人。",
    "people.side.candidates": "本試驗所有已記錄同意前步驟的人（標記、聯絡、篩選紀錄或紀錄）；每個人只會出現在這裡或「受試者」其中之一。篩選找到但尚無人處理的病人在「本週」。",
    "people.side.participants": "本試驗所有已同意的人；每個人只會出現在這裡或「候選者」其中之一。",
}
