"""Shared report plumbing (SPEC §9): embedded Noto fonts, the mandatory footer, deterministic charts and workbooks."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

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

    @property
    def footer(self) -> str:
        return (
            f"TrialBox {self.site_id} · ruleset {self.ruleset} v{self.version} · model {self.model} · "
            f"snapshot {self.snapshot} · job {self.job_id}"
        )


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
            "font.family": _mpl_font(locale),
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
