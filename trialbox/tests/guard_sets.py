"""Synthetic name sets for the tripwire's standing gate (D-647): every name is a listed surname joined to a
made-up given name, set into the shapes notes, contact lines and subject lines use. Nothing here is a person.

The first sets of the card were too easy (most names ended at a boundary; a dozen given names, none a common
word; no compound surname, no line mixing Chinese and kana), and two reviews in a row measured 7 % to 40 % of
names let through in shapes those sets did not hold. These are the reviews' shapes. A new rule for the tripwire is
measured on all of them, per shape, before anyone is asked to approve it.
"""

from __future__ import annotations

from collections.abc import Iterator

from tb_common import phi_guard

ZH_SURNAMES = sorted(phi_guard.ROC_SURNAMES) + sorted(phi_guard.ROC_COMPOUND)
#: two-character given names; many are common words too (志豪, 建國, 美麗, 文化, 明亮): the hard case
ZH_GIVEN = [
    "家豪",
    "志明",
    "俊傑",
    "建宏",
    "俊宏",
    "志豪",
    "志偉",
    "文雄",
    "金龍",
    "志強",
    "淑芬",
    "淑惠",
    "美玲",
    "雅婷",
    "美惠",
    "麗華",
    "淑娟",
    "淑貞",
    "怡君",
    "淑華",
    "雅惠",
    "怡婷",
    "冠宇",
    "承恩",
    "宗翰",
    "家瑋",
    "建志",
    "柏翰",
    "冠廷",
    "彥廷",
    "建國",
    "國華",
    "國強",
    "明亮",
    "文化",
    "美麗",
    "曉燕",
    "子豪",
    "子涵",
    "立偉",
    "明輝",
    "玉蘭",
    "秀英",
    "春嬌",
    "大偉",
    "小明",
    "天成",
    "正義",
    "光明",
    "永福",
]
ZH_GIVEN_ONE = list("森明雪華強偉芳敏靜傑軍平")
JA_SURNAMES = sorted(phi_guard.JP_SURNAMES)
JA_GIVEN = [
    "太郎",
    "一郎",
    "健一",
    "翔太",
    "大輔",
    "拓也",
    "直樹",
    "花子",
    "陽子",
    "美咲",
    "恵",
    "愛",
    "由美",
    "裕子",
    "誠",
    "学",
]

#: a Chinese name in running Chinese text, with no boundary after it
ZH_RUNNING = {
    "label, then text": "病人{n}今日回診",
    "label, complaint": "個案{n}主訴頭痛三天",
    "label, cause": "患者{n}因胸痛入院",
    "label, place": "受試者{n}於門診追蹤",
    "label with colon, then text": "病人：{n}表示近日食慾不佳",
    "sex and age, no space": "{n}女72歲主訴胸悶",
}
#: a Chinese name with a cue or a boundary
ZH_CUED = {
    "honorific, then text": "{n}先生今日回診",
    "honorific 2": "{n}女士表示頭暈",
    "honorific, comma": "{n}先生，今日回診",
    "sex and age": "{n}，男，65歲，主訴胸悶",
    "line end": "姓名：{n}",
    "line end, more lines": "姓名：{n}\n主訴：頭痛",
    "CRLF": "姓名：{n}\r\n主訴：頭痛",
    "digit after": "病人{n}85歲主訴頭痛",
    "Latin after": "病人{n}DM病史十年",
    "bracket after": "病人{n}【主訴】頭痛",
    "dash after": "病人{n}－主訴頭痛",
    "contact": "如有疑問請洽{n}小姐辦理",
    "contact 2": "聯絡人{n}先生將與您聯繫",
}
#: a Chinese name on a line that also holds kana
ZH_WITH_KANA = {
    "sex and age, kana later": "{n}，男，65歲，服用ロキソニン後改善",
    "label and comma, kana later": "病人{n}，主訴のど痛三天",
    "line end, kana earlier": "ロキソニン過敏 病人：{n}",
    "Japanese honorific": "{n}さんは本日来院した。",
}
#: a Chinese name run into text on a line that holds kana, with no cue and no boundary (the second review)
ZH_RUNNING_WITH_KANA = {
    "text after, kana later": "病人{n}今日回診，服用ロキソニン後改善",
    "kana earlier, text after": "ロキソニン過敏，病人{n}今日回診",
    "Japanese particle after": "患者{n}は発熱のため受診した。",
    "Japanese particle 2": "患者{n}の既往歴を確認した。",
}
#: the middle dot and the long vowel mark after a name: punctuation, not text
ZH_DOTS = {
    "middle dot": "病人{n}・主訴頭痛",
    "long vowel mark": "病人{n}ー主訴頭痛",
    "dot, second name": "病人{n}・{n}今日回診",
}
#: subject lines of a protocol or a consent form
ZH_SUBJECT = {
    "signature": "受試者{n}簽名",
    "signed": "受試者{n}已簽署同意書",
    "agrees": "受試者：{n}同意參加本試驗",
    "physician of": "病人{n}之主治醫師",
}
#: a Japanese name on a line with kana
JA_KANA = {
    "name, san": "{n}さんは本日来院した。",
    "name, sama": "{n}様に検査の説明を行った。",
    "name, shi": "{n}氏より同意を得た。",
    "label, wa": "患者{n}は発熱のため受診した。",
    "label, ga": "患者 {n}が来院した。",
    "label, no": "患者{n}の既往歴を確認した。",
    "long line": "本日の外来にて、採血結果および画像所見を踏まえ、{n}さんに今後の治療方針について説明し、次回の予約を取得した。",
}
#: a Japanese name on a line with no kana
JA_NO_KANA = {
    "line end": "患者：{n}",
    "age after": "患者 {n} 68歳 男性 胸痛",
    "text after": "患者{n}来院 胸痛持続",
    "sama, space": "{n}様 来院",
    "sama, text": "{n}様来院",
    "shi, text": "{n}氏同意取得済",
}


def zh_names(given: list[str] | None = None) -> Iterator[str]:
    for s in ZH_SURNAMES:
        for x in given or ZH_GIVEN:
            yield s + x


def ja_names() -> Iterator[str]:
    for s in JA_SURNAMES:
        for x in JA_GIVEN:
            yield s + x


def rows(shapes: dict[str, str], names: Iterator[str]) -> Iterator[tuple[str, str]]:
    """(shape, text) for every name in every shape."""
    all_names = list(names)
    for shape, template in shapes.items():
        for n in all_names:
            yield shape, template.format(n=n)
