"""Write the synthetic source documents the compiler is tested on (fictional; modelled on public trial designs).

* ``GZQO_protocol_v3.pdf`` / ``.docx`` — retatrutide-in-gout phase 3 protocol excerpt (English), §5 eligibility.
* ``GZQO_questions.xlsx`` — a sponsor feasibility question list (FEAS input variant).
* ``AD-MAB_治験実施計画書_v1.pdf`` / ``.docx`` — a fictional early Alzheimer's disease anti-amyloid antibody phase 3
  protocol excerpt in Japanese (synthetic sponsor; scenario J1, T-503), §5 選択基準 / 除外基準.
* ``NEUR-COH_登録計画書_v1.pdf`` / ``.docx`` — a fictional MCI and dementia registry (observational, opt-out) in
  Japanese (scenario J2, T-503).
* ``RA-JAK_試驗計畫書_v1.pdf`` / ``.docx`` — a fictional rheumatoid arthritis JAK-inhibitor phase 3 protocol excerpt
  with a Traditional Chinese cover and the eligibility criteria in English, as sponsors send them (synthetic sponsor;
  scenario T2, T-504). Noto Sans TC.

The Japanese documents embed Noto Sans JP from ``.cache/fonts`` (``python -m tools.fetch_fonts``). Their criteria
are the stub cassettes' texts, so a compile of the document reproduces the cassette extraction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASSETTE = ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract"

FRONT = [
    (
        "1 Protocol Summary",
        "Protocol J1I-MC-GZQO (synthetic excerpt). A Phase 3, randomized, double-blind, "
        "placebo-controlled study of once-weekly retatrutide in participants with gout and obesity or overweight. "
        "This document is a fictional excerpt produced for TrialBox testing; it is not the sponsor's protocol.",
    ),
    (
        "2 Objectives and Endpoints",
        "Primary: proportion of participants with serum urate below 6.0 mg/dL at week "
        "52. Key secondary: gout flare rate, change in body weight.",
    ),
    (
        "3 Study Design",
        "Approximately 900 participants will be randomized 1:1:1 to retatrutide 4 mg, 8 mg or placebo "
        "for 52 weeks after a 4-week screening period.",
    ),
]


def criteria(ruleset: str) -> tuple[list[str], list[str]]:
    data = json.loads((CASSETTE / f"{ruleset}.json").read_text(encoding="utf-8"))["criteria"]
    inc = [c["text"] for c in data if c["kind"] == "inclusion"]
    exc = [c["text"] for c in data if c["kind"] == "exclusion"]
    return inc, exc


def write_pdf(path: Path, title: str, inc: list[str], exc: list[str]) -> None:
    from reportlab import rl_config

    rl_config.invariant = 1  # byte-reproducible PDF (no timestamps / random ids)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for head, body in FRONT:
        story += [Paragraph(head, styles["Heading1"]), Paragraph(body, styles["BodyText"]), Spacer(1, 8)]
    story.append(Paragraph("5 Study Population", styles["Heading1"]))
    for head, items in (("5.1 Inclusion Criteria", inc), ("5.2 Exclusion Criteria", exc)):
        story.append(Paragraph(head, styles["Heading2"]))
        story.append(
            ListFlowable(
                [ListItem(Paragraph(t, styles["BodyText"])) for t in items],  # type: ignore[misc]
                bulletType="1",
                bulletFormat="%s.",
            )
        )
    story += [
        Paragraph("6 Study Intervention", styles["Heading1"]),
        Paragraph("Retatrutide is administered subcutaneously once weekly.", styles["BodyText"]),
    ]
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=title,
        author="TrialBox synthetic",
        subject="test",
        creator="TrialBox",
        producer="TrialBox",
    )
    doc.build(story)


def write_docx(path: Path, title: str, inc: list[str], exc: list[str]) -> None:
    import docx

    d = docx.Document()
    d.core_properties.author = "TrialBox synthetic"
    d.add_heading(title, 0)
    for head, body in FRONT:
        d.add_heading(head, 1)
        d.add_paragraph(body)
    d.add_heading("5 Study Population", 1)
    for head, items in (("5.1 Inclusion Criteria", inc), ("5.2 Exclusion Criteria", exc)):
        d.add_heading(head, 2)
        for i, t in enumerate(items, start=1):
            d.add_paragraph(f"{i}. {t}")
    d.save(str(path))


def write_question_xlsx(path: Path, inc: list[str], exc: list[str]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Feasibility"
    ws.append(["#", "Section", "Question / criterion", "Site answer"])
    n = 1
    for sec, items in (("Inclusion Criteria", inc), ("Exclusion Criteria", exc)):
        for t in items:
            ws.append([n, sec, t, ""])
            n += 1
    wb.save(str(path))


# ------------------------------------------------------------------------------------------------ Japanese (T-503)
FONT_DIR = ROOT / ".cache" / "fonts"

JA_DOCS: dict[str, dict[str, object]] = {
    "AD-MAB": {
        "file": "AD-MAB_治験実施計画書_v1",
        "title": "AD-MAB 治験実施計画書 第1.0版（合成抜粋）",
        "front": [
            (
                "1 概要",
                "早期アルツハイマー病（アルツハイマー病による軽度認知障害および軽度のアルツハイマー型認知症）患者を"
                "対象とした、抗アミロイドβ抗体 AD-MAB の多施設共同、無作為化、二重盲検、プラセボ対照、並行群間"
                "比較第III相試験。本書は TrialBox の試験用に作成した架空の抜粋であり、実在の治験依頼者"
                "（合成製薬株式会社は架空の会社）の治験実施計画書ではない。",
            ),
            (
                "2 目的",
                "主要評価項目：投与78週時点のCDR-SB（Clinical Dementia Rating Sum of Boxes）の"
                "ベースラインからの変化量。",
            ),
            ("3 試験デザイン", "約1,200例を AD-MAB 群とプラセボ群に1:1で割り付け、2週に1回点滴静注で78週間投与する。"),
        ],
        "population": "5 対象被験者",
        "sections": ("5.1 選択基準", "5.2 除外基準"),
        "after": (
            "6 治験薬",
            "AD-MAB は2週に1回、約1時間かけて点滴静注する。投与期間中は定期的に頭部MRIでARIAを監視する。",
        ),
    },
    "NEUR-COH": {
        "file": "NEUR-COH_登録計画書_v1",
        "title": "もの忘れ外来 MCI・認知症レジストリ（NEUR-COH）登録計画書 第1版（合成）",
        "front": [
            (
                "1 概要",
                "当院もの忘れ外来に通院する軽度認知障害および認知症の患者を対象とした観察研究（レジストリ）。"
                "診療録の情報を用い、オプトアウトにより実施する。研究対象者への連絡は行わない。本書は TrialBox の"
                "試験用に作成した架空の文書である。",
            ),
        ],
        "population": "2 研究対象者",
        "sections": ("2.1 選択基準", None),
        "after": ("3 収集する情報", "病名、受診歴、認知機能検査、処方（抗凝固薬を含む）、血清クレアチニン値（eGFR）。"),
    },
}


def _ja_fonts(script: str = "JP") -> tuple[str, str]:
    """Register Noto Sans JP (or TC, ``script="TC"``) and return the regular and bold font names."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    reg, bold = FONT_DIR / f"NotoSans{script}-Regular.ttf", FONT_DIR / f"NotoSans{script}-Bold.ttf"
    if not reg.exists() or not bold.exists():
        raise SystemExit(f"Noto Sans {script} is missing: run python -m tools.fetch_fonts first")
    pdfmetrics.registerFont(TTFont(f"Noto{script}", str(reg)))
    pdfmetrics.registerFont(TTFont(f"Noto{script}-Bold", str(bold)))
    return f"Noto{script}", f"Noto{script}-Bold"


def write_pdf_ja(path: Path, spec: dict[str, Any], inc: list[str], exc: list[str]) -> None:
    from reportlab import rl_config

    rl_config.invariant = 1
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    reg, bold = _ja_fonts(str(spec.get("script", "JP")))
    body = ParagraphStyle("b", fontName=reg, fontSize=10.5, leading=15, wordWrap="CJK")
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=13, leading=18, spaceBefore=8)
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=11.5, leading=16, spaceBefore=6)
    title = ParagraphStyle("t", parent=body, fontName=bold, fontSize=15, leading=21)
    story: list[Any] = [Paragraph(str(spec["title"]), title), Spacer(1, 10)]
    for head, text in spec["front"]:
        story += [Paragraph(head, h1), Paragraph(text, body)]
    story.append(Paragraph(str(spec["population"]), h1))
    for head, items in zip(spec["sections"], (inc, exc), strict=True):
        if head is None:
            continue
        story.append(Paragraph(head, h2))
        story += [Paragraph(f"{i}. {t}", body) for i, t in enumerate(items, start=1)]
    after_head, after_text = spec["after"]
    story += [Paragraph(after_head, h1), Paragraph(after_text, body)]
    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=str(spec["title"]),
        author="TrialBox synthetic",
        subject="test",
        creator="TrialBox",
        producer="TrialBox",
    ).build(story)


def write_docx_ja(path: Path, spec: dict[str, Any], inc: list[str], exc: list[str]) -> None:
    import io

    import docx
    from tb_common.deterministic import normalize_ooxml

    d = docx.Document()
    d.core_properties.author = "TrialBox synthetic"
    d.add_heading(str(spec["title"]), 0)
    for head, text in spec["front"]:
        d.add_heading(head, 1)
        d.add_paragraph(text)
    d.add_heading(str(spec["population"]), 1)
    for head, items in zip(spec["sections"], (inc, exc), strict=True):
        if head is None:
            continue
        d.add_heading(head, 2)
        for i, t in enumerate(items, start=1):
            d.add_paragraph(f"{i}. {t}")
    after_head, after_text = spec["after"]
    d.add_heading(after_head, 1)
    d.add_paragraph(after_text)
    buf = io.BytesIO()
    d.save(buf)
    path.write_bytes(normalize_ooxml(buf.getvalue()))


def write_ja(out: Path) -> list[Path]:
    paths = []
    for rid, spec in JA_DOCS.items():
        inc, exc = criteria(rid)
        stem = out / str(spec["file"])
        write_pdf_ja(stem.with_suffix(".pdf"), spec, inc, exc)
        write_docx_ja(stem.with_suffix(".docx"), spec, inc, exc)
        paths += [stem.with_suffix(".pdf"), stem.with_suffix(".docx")]
    return paths


# ------------------------------------------------------------------------------- Traditional Chinese cover (T-504)
TW_DOCS: dict[str, dict[str, object]] = {
    "RA-JAK": {
        "file": "RA-JAK_試驗計畫書_v1",
        "script": "TC",
        "title": "RA-JAK 試驗計畫書 第1.0版（合成摘錄）",
        "front": [
            (
                "1 計畫摘要",
                "針對對傳統型疾病修飾抗風濕藥物反應不佳之中度至重度活動性類風濕關節炎病人，評估口服 JAK 抑制劑"
                " RA-JAK 之多中心、隨機分派、雙盲、安慰劑對照第三期試驗。本文件為 TrialBox 測試用之虛構摘錄，"
                "試驗委託者「合成藥業股份有限公司」為虛構公司，並非任何實際試驗之計畫書。",
            ),
            ("2 試驗目的", "主要療效指標：第 12 週達到 ACR20 反應之受試者比例。"),
            (
                "3 試驗設計",
                "約 600 位受試者以 2:1 比例分派至 RA-JAK 每日一次或安慰劑組，皆併用穩定劑量之 methotrexate。",
            ),
        ],
        "population": "5 Study Population 研究族群",
        "sections": ("5.1 Inclusion Criteria 納入條件", "5.2 Exclusion Criteria 排除條件"),
        "after": ("6 試驗藥品", "RA-JAK 每日口服一次，治療期間定期監測血球、肝功能、血脂與感染徵候。"),
    },
}


def write_tw(out: Path) -> list[Path]:
    paths = []
    for rid, spec in TW_DOCS.items():
        inc, exc = criteria(rid)
        stem = out / str(spec["file"])
        write_pdf_ja(stem.with_suffix(".pdf"), spec, inc, exc)
        write_docx_ja(stem.with_suffix(".docx"), spec, inc, exc)
        paths += [stem.with_suffix(".pdf"), stem.with_suffix(".docx")]
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "protocols")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    inc, exc = criteria("GZQO")
    title = "J1I-MC-GZQO Protocol v3.0 (synthetic excerpt)"
    write_pdf(args.out / "GZQO_protocol_v3.pdf", title, inc, exc)
    write_docx(args.out / "GZQO_protocol_v3.docx", title, inc, exc)
    write_question_xlsx(args.out / "GZQO_questions.xlsx", inc, exc)
    write_ja(args.out)
    write_tw(args.out)
    print(f"wrote protocol documents to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
