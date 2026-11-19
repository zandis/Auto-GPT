"""9k-3 (D-1375): every button is a target of at least 44 x 44 px, measured in Chromium.

The rule-block count and the stylesheet's sizes are read in ``tests/unit/test_buttons_9k3.py``; here eight pages (the
PI's week page, patient sheet and full patient page; the coordinator's week page, registry, SAE register, set-up and
help) are drawn with the in-process box in en, ja and zh-TW at 1280 and 390 px wide, written with ``console.css`` into
one folder, and every visible ``button`` and button-styled link on the whole page is measured
(``tests/console/button_targets_9k3.js``). A planted rule that shrinks the small size is caught. Skipped where Node
Playwright is missing (as ``test_cjk_layout``). Synthetic data only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_cjk_layout import LANGS, B, _as, _node_playwright, _setup
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("button_targets_9k3.js")
SIZES = {"desktop": (1280, 860), "phone": (390, 844)}
# (name, user, path)
PAGES = (
    ("pi-week", "drsato", "/studies/GZQO/week"),
    ("pi-sheet", "drsato", f"/studies/GZQO/week?pid={B}"),
    ("pi-patient", "drsato", f"/studies/GZQO/patients/{B}"),
    ("crc-week", "crc", "/studies/GZQO/week"),
    ("crc-registry", "crc", "/pilot/registry/GZQO"),
    ("crc-sae", "crc", "/sae"),
    ("crc-setup", "crc", "/studies/GZQO/setup"),
    ("crc-help", "crc", "/help"),
)


def _measure(out: Path, pages: list[dict[str, Any]]) -> dict[str, Any]:
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages})],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    res: dict[str, Any] = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 or res["small"], (res, r.stderr[-3000:])
    return res


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_9k3_every_button_on_the_first_screens_is_at_least_44px(box: dict[str, Any], tmp_path: Path) -> None:  # noqa: F811
    _setup(box)
    box["users"].create("stew", "steward", "cjk-layout-password-0001", "stew@hospa.test")
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    css = ""
    for lang in LANGS:
        clients: dict[str, Any] = {}
        for name, user, path in PAGES:
            c = clients.setdefault(user, _as(box, user, lang))
            r = c.get(path)
            assert r.status_code == 200, (path, r.status_code)
            fname = f"{name}-{lang}.html"
            (out / fname).write_text(
                r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8"
            )
            css = css or c.get("/static/console.css").text
            for size, (w, h) in SIZES.items():
                pages.append({"name": f"{name}-{lang}-{size}", "file": fname, "width": w, "height": h})
    (out / "console.css").write_text(css, encoding="utf-8")
    assert len(pages) == len(PAGES) * len(LANGS) * len(SIZES)
    got = _measure(out, pages)
    assert got["failed"] == {} and got["small"] == {} and got["measured"] > 0, got
    # the measure is not blind: the small size planted at 28 px is found on a page that has small buttons
    (out / "console.css").write_text(
        css + "\nbutton, .button { min-height: 28px; min-width: 0; padding: 2px 6px; }\n", encoding="utf-8"
    )
    planted = _measure(out, [p for p in pages if p["name"] == "pi-sheet-ja-phone"])
    assert planted["failed"] == {} and planted["small"].get("pi-sheet-ja-phone"), planted
