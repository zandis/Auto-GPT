"""Shared report plumbing (SPEC §9): embedded Noto fonts, the mandatory footer, deterministic charts and workbooks."""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tb_common.wording import statement

if TYPE_CHECKING:  # at run time ``Paragraph`` is the fallback class below, made on first use
    from reportlab.platypus import Paragraph as Paragraph  # noqa: PLC0414

REPO = Path(__file__).resolve().parents[3]
FONT_DIRS = [Path(os.environ["TB_FONTS_DIR"])] if os.environ.get("TB_FONTS_DIR") else []
FONT_DIRS += [Path("/opt/trialbox/fonts"), REPO / ".cache" / "fonts"]
TEMPLATES = Path(__file__).resolve().parent / "templates"


class ReportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReportMeta:
    """Values printed in every footer: ``TrialBox <site> · ruleset <id> v<ver> · model <name> · snapshot <date> ·
    job <id>``."""

    site_id: str
    site_name: str
    ruleset: str
    version: str
    model: str
    snapshot: str
    job_id: str
    run_date: str
    locale: str = "zh-TW"
    contact: str = ""
    clock: str = ""  # non-empty when the box's clock was pinned (test stack): printed so a reader never mistakes it
    notice: str = ""  # D-442: printed under the list's footer, e.g. scores not verified for this snapshot

    @property
    def footer(self) -> str:
        """``model`` names what actually ran on this job (D-101): the judge and verifier of a screening run,
        ``no model (filters only)`` for counts, never a configured-but-unused model name."""
        tail = f" · {self.clock}" if self.clock else ""
        return (
            f"TrialBox {self.site_id} · ruleset {self.ruleset} v{self.version} · model {self.model} · "
            f"snapshot {self.snapshot} · job {self.job_id}{tail}"
        )

    @property
    def statement(self) -> str:
        """The intended-use statement in the report's language (TB-IU-01 §1 condition C1; T-116): every PDF and
        workbook prints it once, from the one source in ``tb_common.wording``."""
        return statement(self.locale)


def font_family(locale: str) -> str:
    return "NotoSansJP" if locale.lower().startswith("ja") else "NotoSansTC"


def font_file(locale: str, weight: str = "Regular") -> Path:
    name = f"{font_family(locale)}-{weight}.ttf"
    for d in FONT_DIRS:
        if (d / name).exists():
            return d / name
    raise ReportError(f"font {name} not found in {', '.join(str(d) for d in FONT_DIRS)} (run tools/fetch_fonts.py)")


@lru_cache(maxsize=4)
def pdf_fonts(locale: str) -> tuple[str, str]:
    """Register the CJK fonts with reportlab (embedded as subsets); returns (regular, bold) font names."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fam = font_family(locale)
    regular, bold = f"{fam}-Regular", f"{fam}-Bold"
    pdfmetrics.registerFont(TTFont(regular, str(font_file(locale, "Regular"))))
    pdfmetrics.registerFont(TTFont(bold, str(font_file(locale, "Bold"))))
    addMapping(fam, 0, 0, regular)
    addMapping(fam, 1, 0, bold)
    addMapping(fam, 0, 1, regular)
    addMapping(fam, 1, 1, bold)
    return regular, bold


# ------------------------------------------------------------------------------------------------ glyph fallback
# UX-002: a report is set in one Noto family by its language, and each family lacks common characters of the other
# (Noto Sans TC has no 験 検 薬; Noto Sans JP has no 查 值 啟). A Japanese word in an English or zh-TW report, or a
# Taiwan record quoted in a Japanese one, was printed as empty boxes. A character the report's font lacks is set in
# the other family, character by character; one neither has stays with the report's font.
_OTHER = {"NotoSansJP": "zh-TW", "NotoSansTC": "ja"}
_MARKUP = re.compile(r"(<[^>]*>|&#?[A-Za-z0-9]+;)")


@lru_cache(maxsize=8)
def glyphs(font: str) -> frozenset[int]:
    """The code points a registered report font (``NotoSansJP-Regular``, ...) has a glyph for."""
    from reportlab.pdfbase import pdfmetrics

    face: Any = pdfmetrics.getFont(font).face  # type: ignore[attr-defined]
    return frozenset(face.charToGlyph)


def fallback_font(font: str) -> str | None:
    """The same weight of the other family, registered; None for a font that is not one of the report families."""
    family, _, weight = font.partition("-")
    if family not in _OTHER:
        return None
    regular, bold = pdf_fonts(_OTHER[family])
    return bold if weight == "Bold" else regular


def with_fallback(markup: str, font: str) -> str:
    """Paragraph markup in which every run of characters ``font`` lacks and the other family has is wrapped in
    ``<font name="...">``. Tags and entities are kept as they are; text the font has is not touched."""
    other = fallback_font(font)
    if other is None or markup.isascii():
        return markup
    have, alt = glyphs(font), glyphs(other)
    out: list[str] = []
    for part in _MARKUP.split(markup):
        if not part or part.startswith(("<", "&")) or part.isascii():
            out.append(part)
            continue
        run = ""
        for ch in part:
            if ord(ch) not in have and ord(ch) in alt:
                run += ch
                continue
            if run:
                out.append(f'<font name="{other}">{run}</font>')
                run = ""
            out.append(ch)
        if run:
            out.append(f'<font name="{other}">{run}</font>')
    return "".join(out)


def _paragraph_class() -> Any:
    from reportlab.platypus import Paragraph as _Paragraph

    class Paragraph(_Paragraph):
        """reportlab's Paragraph with the glyph fallback: the reports build every paragraph through it."""

        def __init__(self, text: Any, style: Any = None, *args: Any, **kw: Any) -> None:
            # blocker 11: reportlab builds the pieces of a split paragraph through this class with no text (its
            # fragments are already laid out, the fallback already in them): only a text is wrapped
            if isinstance(text, str):
                text = with_fallback(text, getattr(style, "fontName", "") or "")
            super().__init__(text, style, *args, **kw)

    return Paragraph


def __getattr__(name: str) -> Any:  # ``common.Paragraph``: made on first use, reportlab is imported lazily here
    if name == "Paragraph":
        cls = _paragraph_class()
        globals()["Paragraph"] = cls
        return cls
    raise AttributeError(name)


def draw_string(canvas: Any, x: float, y: float, text: str, font: str, size: float) -> None:
    """``canvas.drawString`` with the glyph fallback (a footer drawn on every page)."""
    other = fallback_font(font)
    have = glyphs(font) if other else frozenset()
    alt = glyphs(other) if other else frozenset()
    runs: list[tuple[str, str]] = []
    for ch in text:
        use = other if other and ord(ch) not in have and ord(ch) in alt else font
        if runs and runs[-1][0] == use:
            runs[-1] = (use, runs[-1][1] + ch)
        else:
            runs.append((use, ch))
    for use, run in runs:
        canvas.setFont(use, size)
        canvas.drawString(x, y, run)
        x += canvas.stringWidth(run, use, size)
    canvas.setFont(font, size)


@lru_cache(maxsize=4)
def _mpl_font(locale: str) -> str:
    from matplotlib import font_manager

    path = font_file(locale, "Regular")
    font_manager.fontManager.addfont(str(path))
    return font_manager.FontProperties(fname=str(path)).get_name()


def figure(locale: str, width: float = 7.0, height: float = 3.2) -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            # UX-002: the report's family, then the other one: matplotlib falls back glyph by glyph
            "font.family": [_mpl_font(locale), _mpl_font(_OTHER[font_family(locale)])],
            "font.size": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.hashsalt": "trialbox",
        }
    )
    return plt.figure(figsize=(width, height), dpi=150)


def png(fig: Any) -> bytes:
    """Deterministic PNG (no timestamp / software metadata)."""
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, metadata={"Software": None})
    plt.close(fig)
    return buf.getvalue()


def pdf_invariant() -> None:
    """reportlab: no creation date / random document id, so a rerun yields identical bytes."""
    from reportlab import rl_config

    rl_config.invariant = 1


def fmt_count(v: int | str | None) -> str:
    if v is None:
        return "—"
    return f"{v:,}" if isinstance(v, int) else str(v)
