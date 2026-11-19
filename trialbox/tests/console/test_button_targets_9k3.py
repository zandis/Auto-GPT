"""9k-3 (D-1375): every button is a target of at least 44 x 44 px, measured in Chromium on the 72 first screens.

The rule-block count and the stylesheet's sizes are read in ``tests/unit/test_buttons_9k3.py``; here the twelve pages
of the visual regression (``tests/console/visual_pages.py``: each role's home, the week page, the patient sheet and
page, the registry, the SAE register, set-up, the health page, help) are drawn in en, ja and zh-TW at 1280 and 390 px
wide, and every visible ``button`` and button-styled link on the whole page is measured. A planted rule that shrinks
the small size is caught. Skipped where Node Playwright is missing (as ``test_cjk_layout``). Synthetic data only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import visual_regression as vr

ROOT = Path(__file__).resolve().parents[2]


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_9k3_every_button_on_the_72_first_screens_is_at_least_44px(tmp_path: Path, pg_cluster_url: str) -> None:
    os.environ["TB_TEST_DB_URL"] = pg_cluster_url  # read by the renderer's child process
    try:
        m = vr.shoot(ROOT, tmp_path / "s")
    finally:
        os.environ.pop("TB_TEST_DB_URL", None)
    assert m["errors"] == {} and len(m["names"]) == 72
    pages = tmp_path / "s" / "pages"
    shots = json.loads((pages / "pages.json").read_text(encoding="utf-8"))["shots"]
    got = vr.photograph(pages, tmp_path / "png", shots, measure=True)
    assert got["failed"] == {} and got["small"] == {}
    # the measure is not blind: the small size planted at 28 px is found on a page that has small buttons
    css = pages / "console.css"
    css.write_text(
        css.read_text(encoding="utf-8") + "\nbutton, .button { min-height: 28px; min-width: 0; padding: 2px 6px; }\n",
        "utf-8",
    )
    planted = vr.photograph(
        pages, tmp_path / "png2", [s for s in shots if s["name"] == "patient-sheet-ja-phone"], measure=True
    )
    assert planted["failed"] == {} and planted["small"].get("patient-sheet-ja-phone"), planted
