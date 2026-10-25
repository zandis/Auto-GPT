"""Generator for the ``deid_synthetic`` suite (spec v4 PRIV-30, S1-08): synthetic clinical sentences in zh-TW, ja
and en with planted identifiers.

Run ``python -m eval.suites.deid_synthetic.generate --out items.jsonl``; tests call :func:`generate`. The output is
fully determined by ``suite.yaml`` (seed, counts), so the set is reproducible and never committed as data. Every
identifier is synthetic: random digits with valid check digits computed here independently of ``services/guard``,
reserved e-mail domains (RFC 2606), invented street numbers. Each item lists what was planted, by type.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SUITE = HERE / "suite.yaml"

# ------------------------------------------------------------------------------------------------ identifiers
_LETTER_CODES = dict(zip("ABCDEFGHJKLMNPQRSTUVXYWZIO", range(10, 36), strict=True))


def _tw_checksum_ok(s: str) -> bool:
    code = _LETTER_CODES[s[0]]
    second = s[1]
    d1 = _LETTER_CODES[second] % 10 if second.isalpha() else int(second)
    nums = [code // 10, code % 10, d1] + [int(c) for c in s[2:]]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
    return sum(n * w for n, w in zip(nums, weights, strict=True)) % 10 == 0


def tw_id(rng: random.Random, second: str) -> str:
    body = rng.choice("ABCDEFGHJKLMNPQRSTUVXYWZIO") + second + "".join(rng.choice("0123456789") for _ in range(7))
    return next(body + d for d in "0123456789" if _tw_checksum_ok(body + d))


def my_number(rng: random.Random) -> str:
    first = "".join(rng.choice("0123456789") for _ in range(11))
    weights = [6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2]  # Q_n for n = 11 … 1 (left to right)
    rem = sum(int(c) * w for c, w in zip(first, weights, strict=True)) % 11
    return first + str(0 if rem <= 1 else 11 - rem)


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


ROC_SURNAMES = list("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余趙盧梁顏柯翁")
ROC_COMPOUND = ["歐陽", "司馬", "張簡", "范姜"]
ROC_GIVEN = ["志明", "淑芬", "雅婷", "家豪", "冠宇", "怡君", "建宏", "美玲", "俊傑", "欣怡", "宗翰", "佩珊"]
JP_SURNAMES = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田"]
JP_GIVEN = ["太郎", "花子", "健一", "美咲", "翔太", "由美", "大輔", "さくら", "直樹", "陽子"]
EN_FIRST = ["John", "Mary", "David", "Linda", "Kevin", "Grace", "Peter", "Susan", "Brian", "Emily"]
EN_LAST = ["Smith", "Chen", "Wang", "Tanaka", "Lin", "Brown", "Huang", "Sato", "Miller", "Wu"]
TW_CITY = ["台北市", "新北市", "台中市", "高雄市", "臺南市", "桃園市"]
TW_DIST = ["大安區", "信義區", "板橋區", "西屯區", "苓雅區", "中壢區", "東區"]
TW_ROAD = ["中山路", "復興南路", "民生東路", "文心路", "自由路", "忠孝東路", "和平街"]
TW_SEC = ["一", "二", "三", "四", "五"]
JP_ADDR = [
    ("東京都", "新宿区", "西新宿"),
    ("大阪府", "大阪市", "北区梅田"),
    ("神奈川県", "横浜市", "中区山下町"),
    ("福岡県", "福岡市", "博多区博多駅前"),
    ("北海道", "札幌市", "中央区北一条西"),
    ("愛知県", "名古屋市", "中村区名駅"),
]
EN_STREET = ["Maple", "Oak", "Cedar", "Pine", "Lakeview", "Sunset", "Hillcrest"]
EN_KIND = ["Street", "Avenue", "Road", "Lane", "Drive", "Boulevard"]
EN_CITY = ["Springfield", "Riverside", "Fairview", "Greenville", "Madison"]
MAIL_DOMAINS = ["example.com", "example.org", "example.net"]


def _phone_tw(rng: random.Random) -> str:
    m = "09" + _digits(rng, 2)
    a, b = _digits(rng, 3), _digits(rng, 3)
    area, la, lb = rng.choice("2345678"), _digits(rng, 4), _digits(rng, 4)
    return rng.choice(
        [
            f"{m}-{a}-{b}",
            f"{m}{a}{b}",
            f"+886-{m[1:]}-{a}-{b}",
            f"+886 {m[1:]} {a} {b}",
            f"(0{area}) {la}-{lb}",
            f"0{area}-{la}-{lb}",
        ]
    )


def _phone_jp(rng: random.Random) -> str:
    mob = rng.choice(["090", "080", "070"])
    a, b = _digits(rng, 4), _digits(rng, 4)
    return rng.choice(
        [
            f"{mob}-{a}-{b}",
            f"{mob}{a}{b}",
            f"+81-{mob[1:]}-{a}-{b}",
            f"03-{a}-{b}",
            f"06-{a}-{b}",
            f"+81-3-{a}-{b}",
        ]
    )


def _address(rng: random.Random, lang: str) -> str:
    if lang == "zh-TW":
        city, dist, road = rng.choice(TW_CITY), rng.choice(TW_DIST), rng.choice(TW_ROAD)
        sec = f"{rng.choice(TW_SEC)}段" if rng.random() < 0.6 else ""
        lane = f"{rng.randint(1, 300)}巷" if rng.random() < 0.4 else ""
        alley = f"{rng.randint(1, 30)}弄" if lane and rng.random() < 0.4 else ""
        floor = f"{rng.randint(2, 20)}樓" if rng.random() < 0.5 else ""
        return f"{city}{dist}{road}{sec}{lane}{alley}{rng.randint(1, 999)}號{floor}"
    if lang == "ja":
        pref, city, town = rng.choice(JP_ADDR)
        if rng.random() < 0.5:
            return f"{pref}{city}{town}{rng.randint(1, 9)}丁目{rng.randint(1, 30)}番{rng.randint(1, 20)}号"
        return f"{pref}{city}{town}{rng.randint(1, 9)}-{rng.randint(1, 30)}-{rng.randint(1, 20)}"
    apt = f", Apt {rng.randint(1, 40)}" if rng.random() < 0.3 else ""
    return f"{rng.randint(1, 9999)} {rng.choice(EN_STREET)} {rng.choice(EN_KIND)}{apt}, {rng.choice(EN_CITY)}"


def _dob(rng: random.Random, lang: str) -> str:
    y, m, d = rng.randint(1930, 2005), rng.randint(1, 12), rng.randint(1, 28)
    if lang == "zh-TW":
        return rng.choice([f"{y}-{m:02d}-{d:02d}", f"民國{y - 1911}年{m}月{d}日", f"{y}年{m}月{d}日"])
    if lang == "ja":
        era = f"昭和{y - 1925}年{m}月{d}日" if y < 1989 else f"平成{y - 1988}年{m}月{d}日"
        return rng.choice([era, f"{y}年{m}月{d}日", f"{y}/{m:02d}/{d:02d}"])
    return rng.choice([f"{m:02d}/{d:02d}/{y}", f"{y}-{m:02d}-{d:02d}"])


def _name(rng: random.Random, lang: str) -> str:
    if lang == "zh-TW":
        sur = rng.choice(ROC_COMPOUND) if rng.random() < 0.1 else rng.choice(ROC_SURNAMES)
        return sur + rng.choice(ROC_GIVEN)
    if lang == "ja":
        sep = " " if rng.random() < 0.4 else ""
        return rng.choice(JP_SURNAMES) + sep + rng.choice(JP_GIVEN)
    return f"{rng.choice(EN_FIRST)} {rng.choice(EN_LAST)}"


# ------------------------------------------------------------------------------------------------ sentences
# (type, {lang: [templates]}) — {v} is the planted value
PHRASES: dict[str, dict[str, list[str]]] = {
    "NAME": {
        "zh-TW": [
            "患者{v}先生今日回診",
            "姓名：{v}",
            "{v}，男，67歲，因胸悶入院",
            "病人{v}主訴咳嗽三天",
            "{v}小姐術後恢復良好",
        ],
        "ja": ["患者 {v}様は外来受診", "氏名：{v}", "{v}さんは昨日から発熱", "{v}様、血圧は安定"],
        "en": [
            "Mr. {v} was admitted for chest pain",
            "Patient: {v} presented with cough",
            "Name: {v}",
            "Ms. {v} reports dizziness",
        ],
    },
    "TW_NATIONAL_ID": {
        "zh-TW": ["身分證字號 {v}", "身分證：{v}", "ID {v} 已核對"],
        "ja": ["台湾の身分証番号 {v}"],
        "en": ["national ID {v} verified", "ID no. {v}"],
    },
    "TW_ARC": {
        "zh-TW": ["居留證號 {v}", "外籍人士居留證 {v}"],
        "ja": ["居留証番号 {v}"],
        "en": ["resident certificate {v}", "ARC {v}"],
    },
    "JP_MY_NUMBER": {
        "zh-TW": ["日本個人編號 {v}"],
        "ja": ["マイナンバー {v}", "個人番号：{v}"],
        "en": ["My Number {v}", "Japanese individual number {v}"],
    },
    "PASSPORT": {
        "zh-TW": ["護照號碼 {v}", "護照 {v}"],
        "ja": ["旅券番号 {v}", "パスポート番号：{v}"],
        "en": ["passport no. {v}", "Passport number {v}"],
    },
    "PHONE_TW": {
        "zh-TW": ["聯絡電話 {v}", "手機：{v}", "請撥 {v} 聯絡家屬"],
        "ja": ["台湾の連絡先 {v}"],
        "en": ["call {v}", "phone: {v}"],
    },
    "PHONE_JP": {
        "zh-TW": ["日本電話 {v}"],
        "ja": ["電話番号 {v}", "連絡先：{v}", "携帯 {v} に連絡"],
        "en": ["Japan phone {v}", "tel. {v}"],
    },
    "ADDRESS": {
        "zh-TW": ["住址：{v}", "住在{v}", "通訊地址 {v}"],
        "ja": ["住所：{v}", "{v}在住"],
        "en": ["lives at {v}", "address: {v}"],
    },
    "MRN": {
        "zh-TW": ["病歷號 {v}", "病歷號碼：{v}"],
        "ja": ["カルテ番号 {v}", "患者ID：{v}"],
        "en": ["MRN {v}", "chart no. {v}", "medical record number {v}"],
    },
    "EMAIL": {
        "zh-TW": ["電子郵件 {v}", "信箱：{v}"],
        "ja": ["メール {v}", "連絡用メール：{v}"],
        "en": ["email {v}", "contact: {v}"],
    },
    "DOB": {
        "zh-TW": ["出生日期：{v}", "生日 {v}"],
        "ja": ["生年月日 {v}", "生年月日：{v}"],
        "en": ["DOB: {v}", "date of birth {v}", "born on {v}"],
    },
}
FILLER: dict[str, list[str]] = {
    "zh-TW": [
        "血壓 132/84 mmHg，心跳 78 次/分。",
        "HbA1c 7.2%，eGFR 45 mL/min/1.73m²。",
        "目前使用 metformin 500 mg bid。",
        "胸部 X 光未見明顯浸潤。",
        "建議三個月後回診追蹤。",
    ],
    "ja": [
        "血圧 128/80 mmHg、脈拍 72 回/分。",
        "HbA1c 6.9%、eGFR 52。",
        "メトホルミン 500 mg を継続。",
        "胸部レントゲンで異常なし。",
        "次回は 4 週間後に受診予定。",
    ],
    "en": [
        "BP 130/82 mmHg, HR 76.",
        "HbA1c 7.4%, eGFR 48 mL/min/1.73m2.",
        "Continue metformin 500 mg twice daily.",
        "Screened for NCT04157751; no exclusion found.",
        "Follow-up in 12 weeks.",
    ],
}
TYPES_BY_LANG: dict[str, list[str]] = {
    "zh-TW": ["NAME", "TW_NATIONAL_ID", "TW_ARC", "PASSPORT", "PHONE_TW", "ADDRESS", "MRN", "EMAIL", "DOB"],
    "ja": ["NAME", "JP_MY_NUMBER", "PASSPORT", "PHONE_JP", "ADDRESS", "MRN", "EMAIL", "DOB"],
    "en": [
        "NAME",
        "TW_NATIONAL_ID",
        "TW_ARC",
        "JP_MY_NUMBER",
        "PASSPORT",
        "PHONE_TW",
        "PHONE_JP",
        "ADDRESS",
        "MRN",
        "EMAIL",
        "DOB",
    ],
}


def _value(kind: str, lang: str, rng: random.Random) -> str:
    if kind == "NAME":
        return _name(rng, lang)
    if kind == "TW_NATIONAL_ID":
        return tw_id(rng, rng.choice("12"))
    if kind == "TW_ARC":
        return tw_id(rng, rng.choice("89ABCD"))
    if kind == "JP_MY_NUMBER":
        n = my_number(rng)
        return rng.choice([n, f"{n[:4]} {n[4:8]} {n[8:]}", f"{n[:4]}-{n[4:8]}-{n[8:]}"])
    if kind == "PASSPORT":
        if lang == "ja" or rng.random() < 0.3:
            return "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2)) + _digits(rng, 7)
        return rng.choice("123") + _digits(rng, 8)
    if kind == "PHONE_TW":
        return _phone_tw(rng)
    if kind == "PHONE_JP":
        return _phone_jp(rng)
    if kind == "ADDRESS":
        return _address(rng, lang)
    if kind == "MRN":
        return rng.choice("123456789") + _digits(rng, 7)
    if kind == "EMAIL":
        user = rng.choice(EN_FIRST).lower() + "." + rng.choice(EN_LAST).lower() + str(rng.randint(1, 99))
        return f"{user}@{rng.choice(MAIL_DOMAINS)}"
    if kind == "DOB":
        return _dob(rng, lang)
    raise ValueError(kind)


@dataclass
class Item:
    id: str
    lang: str
    text: str
    planted: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "lang": self.lang, "text": self.text, "planted": self.planted}


def load_suite(path: Path = SUITE) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


def generate(suite: dict[str, Any] | None = None) -> list[Item]:
    cfg = suite or load_suite()
    rng = random.Random(int(cfg["seed"]))
    sep = {"zh-TW": "", "ja": "", "en": " "}
    joiner = {"zh-TW": "。", "ja": "。", "en": ". "}
    items: list[Item] = []
    for lang in cfg["languages"]:
        for i in range(int(cfg["items_per_language"])):
            planted: list[dict[str, str]] = []
            parts: list[str] = []
            if rng.random() >= float(cfg["negative_share"]):
                kinds = rng.sample(TYPES_BY_LANG[lang], k=rng.randint(2, 4))
                for kind in kinds:
                    value = _value(kind, lang, rng)
                    parts.append(rng.choice(PHRASES[kind][lang]).format(v=value))
                    planted.append({"type": kind, "value": value})
            fillers = rng.sample(FILLER[lang], k=2)
            text = joiner[lang].join(parts) + (joiner[lang] if parts else "") + sep[lang].join(fillers)
            items.append(Item(f"{lang}-{i:03d}", lang, text, planted))
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    items = generate()
    with args.out.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it.to_json(), ensure_ascii=False) + "\n")
    print(f"wrote {len(items)} items to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
