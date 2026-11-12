"""Synthetic patient charts with known facts, for the chart scenarios of the complete run (TB-PLAN-04 step 9, D-141).

Each chart is the text a coordinator would copy from an EMR screen (ja or zh-TW): a visit header, date of birth and
sex, the diagnosis, labs and medicines, and the traps a careful reader must not turn into facts:

* **negation**: 悪性腫瘍なし / 否認惡性腫瘤病史, 痛風は否定的 (a ruled-out diagnosis);
* **family history**: 家族歴：父 大腸癌 / 家族史：母親 乳癌 (a relative's disease, not the patient's);
* **past history**: 既往：胃癌（2018年3月1日 手術）/ 過去病史：乳癌（2019年5月2日 手術） is a true fact of the
  patient, dated on its own day and not on the visit day.

A patient may have a second chart (a lab report on a later day) that joins by pseudonym. :func:`truth` gives the
facts the chart states (domain, code, day, value) and :func:`score` compares the facts a model proposed against them
(precision and recall per domain). :func:`docx`, :func:`pdf` and :func:`scan` render the same text as a Word file, a
PDF with a text layer and a scanned image (PNG, or a PDF with no text layer) for the chart-file scenario.

Every patient is fictional (seeded, ``random.Random``); chart numbers start at 3, never a real range.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / ".cache" / "fonts"
URATE = "3084-1"
CREAT = "2160-0"
GOUT, HTN, T2DM = "M10.9", "I10", "E11.9"
CANCER = {"ja": ("胃癌", "C16.9"), "zh-TW": ("乳癌", "C50.919")}
DRUGS = {
    "allopurinol": ("M04AA01", "アロプリノール", "別嘌呤醇"),
    "febuxostat": ("M04AA03", "フェブキソスタット", "febuxostat"),
}
ERAS = (("令和", date(2019, 5, 1)), ("平成", date(1989, 1, 8)), ("昭和", date(1926, 12, 25)))


@dataclass
class Fact:
    domain: str  # condition | observation | medication | birth_date | sex
    code: str = ""
    day: str = ""
    value: str = ""

    def key(self) -> tuple[str, ...]:
        if self.domain == "observation":
            return (self.domain, self.code, self.day, f"{float(self.value):.1f}")
        if self.domain in ("birth_date", "sex"):
            return (self.domain, self.value)
        return (self.domain, self.code, self.day)


@dataclass
class Chart:
    chart_no: str
    lang: str
    kind: str  # note | labs
    text: str
    facts: list[Fact] = field(default_factory=list)
    traps: list[str] = field(default_factory=list)


@dataclass
class Patient:
    chart_no: str
    lang: str
    birth: date
    sex: str
    charts: list[Chart] = field(default_factory=list)

    def facts(self) -> list[Fact]:
        return [f for c in self.charts for f in c.facts]


def era(d: date) -> str:
    for name, start in ERAS:
        if d >= start:
            return f"{name}{d.year - start.year + 1}年{d.month}月{d.day}日"
    return f"{d.year}年{d.month}月{d.day}日"


def minguo(d: date) -> str:
    return f"民國{d.year - 1911}年{d.month}月{d.day}日"


def ymd(d: date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def patients(n: int, seed: int = 20261109, today: date = date(2026, 11, 2), first: int = 30000001) -> list[Patient]:
    """``n`` synthetic patients, half ja and half zh-TW, each with one chart and a quarter with a second one."""
    rng = random.Random(seed)
    out: list[Patient] = []
    for i in range(n):
        lang = "ja" if i % 2 == 0 else "zh-TW"
        birth = date(rng.randint(1940, 2010), rng.randint(1, 12), rng.randint(1, 28))
        p = Patient(f"{first + i:08d}", lang, birth, rng.choice(("male", "female")))
        visit = today - timedelta(days=rng.randint(5, 300))
        p.charts.append(_note(rng, p, visit))
        if rng.random() < 0.25:
            p.charts.append(_labs(rng, p, visit + timedelta(days=rng.randint(1, 4))))
        out.append(p)
    return out


def _note(rng: random.Random, p: Patient, visit: date) -> Chart:
    ja = p.lang == "ja"
    c = Chart(p.chart_no, p.lang, "note", "")
    sex_word = ("男性" if p.sex == "male" else "女性") if ja else ("男" if p.sex == "male" else "女")
    lines = [
        f"外来記録　{ymd(visit)}" if ja else f"門診紀錄 {ymd(visit)}",
        f"患者 カルテ番号 {p.chart_no}" if ja else f"病歷號 {p.chart_no}",
        f"生年月日 {era(p.birth)}　性別 {sex_word}" if ja else f"出生日期：{minguo(p.birth)}",
    ]
    c.facts.append(Fact("birth_date", value=p.birth.isoformat()))
    if ja:
        c.facts.append(Fact("sex", value=p.sex))
    else:
        lines.append(f"性別：{sex_word}")
        c.facts.append(Fact("sex", value=p.sex))
    gout = rng.random() < 0.7
    if gout:
        lines.append("診断：痛風（右第1MTP関節）。" if ja else "診斷：痛風（右第一蹠趾關節）。")
        c.facts.append(Fact("condition", GOUT, visit.isoformat()))
    else:
        lines.append("関節痛あり、痛風は否定的。" if ja else "關節痛，已排除痛風（ruled out）。")
        c.traps.append("ruled-out gout")
    if rng.random() < 0.3:
        lines.append("併存症：高血圧。" if ja else "合併症：高血壓。")
        c.facts.append(Fact("condition", HTN, visit.isoformat()))
    urate = round(rng.uniform(4.5, 10.5), 1)
    lines.append(f"検査：尿酸 {urate} mg/dL" if ja else f"檢驗：尿酸 {urate} mg/dL")
    c.facts.append(Fact("observation", URATE, visit.isoformat(), f"{urate}"))
    if gout and rng.random() < 0.5:
        code, jname, zname = DRUGS["allopurinol"]
        lines.append(f"処方：{jname} 100mg 1日1回" if ja else f"處方：{zname} 100mg 每日一次")
        c.facts.append(Fact("medication", code, visit.isoformat()))
    roll = rng.random()
    name, code = CANCER[p.lang]
    if roll < 0.2:  # past history: a true fact of the patient, dated on its own day
        when = date(rng.randint(2012, 2024), rng.randint(1, 12), rng.randint(1, 28))
        lines.append(f"既往：{name}（{ymd(when)} 手術）" if ja else f"過去病史：{name}（{ymd(when)} 手術）")
        c.facts.append(Fact("condition", code, when.isoformat()))
    elif roll < 0.6:  # negation trap
        lines.append("既往：悪性腫瘍なし。" if ja else "否認惡性腫瘤病史。")
        c.traps.append("negated malignancy")
    if rng.random() < 0.35:  # family history trap
        rel = "父 大腸癌" if ja else "母親 乳癌"
        lines.append(f"家族歴：{rel}" if ja else f"家族史：{rel}")
        c.traps.append("family history")
    c.text = "\n".join(lines) + "\n"
    return c


def _labs(rng: random.Random, p: Patient, day: date) -> Chart:
    ja = p.lang == "ja"
    urate = round(rng.uniform(4.5, 10.5), 1)
    cre = round(rng.uniform(0.5, 1.6), 1)
    head = f"検査報告　{ymd(day)}" if ja else f"檢驗報告 {ymd(day)}"
    no = f"カルテ番号 {p.chart_no}" if ja else f"病歷號 {p.chart_no}"
    body = (
        [f"尿酸 {urate} mg/dL", f"クレアチニン {cre} mg/dL"] if ja else [f"尿酸 {urate} mg/dL", f"肌酸酐 {cre} mg/dL"]
    )
    c = Chart(p.chart_no, p.lang, "labs", "\n".join([head, no, *body]) + "\n")
    c.facts += [
        Fact("observation", URATE, day.isoformat(), f"{urate}"),
        Fact("observation", CREAT, day.isoformat(), f"{cre}"),
    ]
    return c


# ------------------------------------------------------------------------------------------------ scoring
def proposed_key(f: dict[str, Any]) -> tuple[str, ...]:
    """A stored fact (``sitesetup.store``) in the same key as :meth:`Fact.key`."""
    dom = str(f.get("domain") or "")
    if dom == "demographic":
        return (str(f.get("code")), str(f.get("value") or ""))
    if dom == "observation":
        try:
            v = f"{float(f.get('value') or 'nan'):.1f}"
        except ValueError:
            v = "?"
        return (dom, str(f.get("code") or ""), str(f.get("day") or ""), v)
    return (dom, str(f.get("code") or ""), str(f.get("day") or ""))


def score(truth: dict[str, list[Fact]], got: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Precision and recall of the proposed facts per domain, against the facts the charts state. ``truth`` and
    ``got`` are keyed by pseudonym. A proposed fact matches a true fact of the same patient with the same key."""
    per: dict[str, dict[str, int]] = {}
    wrong: list[str] = []
    missed: list[str] = []
    for pid in sorted(set(truth) | set(got)):
        want = [f.key() for f in truth.get(pid, [])]
        left = list(want)
        for f in got.get(pid, []):
            k = proposed_key(f)
            row = per.setdefault(k[0], {"truth": 0, "proposed": 0, "matched": 0})
            row["proposed"] += 1
            if k in left:
                left.remove(k)
                row["matched"] += 1
            else:
                wrong.append(f"{pid[:8]} {k}")
        for k in want:
            per.setdefault(k[0], {"truth": 0, "proposed": 0, "matched": 0})["truth"] += 1
        missed += [f"{pid[:8]} {k}" for k in left]
    tot = {k: sum(r[k] for r in per.values()) for k in ("truth", "proposed", "matched")}
    p = tot["matched"] / tot["proposed"] if tot["proposed"] else 1.0
    r = tot["matched"] / tot["truth"] if tot["truth"] else 1.0
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        **tot,
        "by_domain": per,
        "wrong": wrong[:20],
        "missed": missed[:20],
    }


def matches(truth: list[Fact], f: dict[str, Any]) -> bool:
    return proposed_key(f) in {t.key() for t in truth}


# ------------------------------------------------------------------------------------------------ rendering
def _font(lang: str) -> Path:
    return FONTS / ("NotoSansJP-Regular.ttf" if lang == "ja" else "NotoSansTC-Regular.ttf")


def fonts_ok() -> bool:
    return all(_font(lang).exists() for lang in ("ja", "zh-TW"))


def docx(c: Chart) -> bytes:
    import docx as _docx

    d = _docx.Document()
    for line in c.text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def pdf(c: Chart) -> bytes:
    """A PDF with a text layer (the CJK font embedded, so the text extracts)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    name = f"tb-{c.lang}"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(_font(c.lang))))
    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    cv.setFont(name, 11)
    y = 780
    for line in c.text.splitlines():
        cv.drawString(60, y, line)
        y -= 18
    cv.save()
    return buf.getvalue()


def png(c: Chart, scale: int = 2) -> bytes:
    """The chart as a scanned page: black text on white, 150 dpi-like, for OCR."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(_font(c.lang)), 22 * scale)
    lines = c.text.splitlines()
    img = Image.new("L", (900 * scale, (60 + 40 * len(lines)) * scale), 255)
    dr = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        dr.text((30 * scale, (30 + 40 * i) * scale), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def scan_pdf(c: Chart) -> bytes:
    """A PDF with no text layer: one page image, as a scanner makes it."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    cv.drawImage(ImageReader(io.BytesIO(png(c))), 30, 300, width=540, height=480)
    cv.save()
    return buf.getvalue()


class FakeOcr:
    """OCR for a laptop without tesseract (``--ocr fake``): returns the text each rendered image was made from."""

    name = "fake"

    def __init__(self) -> None:
        self.by_image: dict[bytes, str] = {}

    def remember(self, c: Chart) -> None:
        self.by_image[png(c)] = c.text

    def available(self) -> bool:
        return True

    def image_text(self, data: bytes) -> str:
        if data in self.by_image:
            return self.by_image[data]
        from PIL import Image  # a page image pulled out of a PDF is re-encoded: match it by its pixels

        try:
            px = Image.open(io.BytesIO(data)).convert("L").tobytes()
        except Exception:
            return ""
        for img, text in self.by_image.items():
            if Image.open(io.BytesIO(img)).convert("L").tobytes() == px:
                return text
        return ""
