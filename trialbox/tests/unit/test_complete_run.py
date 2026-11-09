"""tools/complete_run.py (TB-PLAN-04 step 9, D-139): the plan of parts, the page per stage and the report.

The run itself is the local done-check (``python -m tools.complete_run``); these tests hold its pieces."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from tools import complete_run as cr

ROOT = Path(__file__).resolve().parents[2]


def _args(**kw: object) -> argparse.Namespace:
    base = {"langs": ["ja", "zh-TW"], "skip": [], "walk": True}
    base.update(kw)
    return argparse.Namespace(**base)


def test_every_part_of_plan_v4_section_5_in_both_languages() -> None:
    parts = cr.plan(_args())
    assert parts[:2] == [("prepare", ""), ("install", "")]
    for part in ("hospital", "public"):
        assert [(p, lang) for p, lang in parts if p == part] == [(part, "ja"), (part, "zh-TW")]
    assert [p for p, _ in parts[-3:]] == ["backup", "update", "scale"]
    assert ("backup", "") not in cr.plan(_args(skip=["backup"]))


def _stage_names(path: Path) -> list[str]:
    return re.findall(r'Stage\("([^"]+)"\)', path.read_text(encoding="utf-8"))


def test_every_stage_has_its_own_page() -> None:
    """A stage that falls through to /home has no screenshot of its own: every e2e and public stage is mapped."""
    for tool, pages in (("e2e_simple.py", cr.HOSPITAL_PAGES), ("public_e2e.py", cr.PUBLIC_PAGES)):
        names = _stage_names(ROOT / "tools" / tool)
        assert names
        for name in names:
            assert any(name.startswith(pre) for pre, _, _ in pages), (tool, name)


def test_page_items_fill_ids_and_name_the_shots() -> None:
    stages = [{"name": "2 investigator approval"}, {"name": "4 list, marks and mail"}, {"name": "something new"}]
    items = cr._page_items("hospital-ja", "ja", stages, cr.HOSPITAL_PAGES, {"feas": "J1", "pid": "abc"})
    assert [i["path"] for i in items] == ["/pilot/jobs/J1/approval", "/studies/GZQO/patients/abc", "/home"]
    assert [i["user"] for i in items] == ["pi", "pi", "admin"]
    assert [s["shot"] for s in stages] == ["hospital-ja-00.png", "hospital-ja-01.png", "hospital-ja-02.png"]


def test_table_page_and_markdown(tmp_path: Path) -> None:
    stages = [{"name": "backup", "ok": False, "seconds": 1.0, "checks": [["restored", False, "<rows differ>"]],
               "shot": "backup.png", "shot_ok": True}]  # fmt: skip
    url = cr.table_page(tmp_path / "t.html", "backup", stages)
    page = (tmp_path / "t.html").read_text(encoding="utf-8")
    assert url.startswith("file://") and "&lt;rows differ&gt;" in page and "FAIL" in page
    rep = {
        "git": {"head": "0123456789abcdef", "subject": "s", "dirty": False},
        "models": ["stub"],
        "patients": 5000,
        "langs": ["ja", "zh-TW"],
        "host": {"machine": "x86_64", "cpus": 4},
        "started": "a",
        "finished": "b",
        "ok": False,
        "checks": 1,
        "failed": 1,
        "shots": 1,
        "shots_ok": 1,
        "seconds": 60.0,
        "parts": [{"tag": "backup", "stages": stages, "seconds_total": 1.0}],
    }
    md = cr.markdown(rep)
    assert "Head `0123456789ab`" in md and "**FAILED**" in md
    assert "| backup | backup | 0/1 | FAIL | 1.0 | `backup.png` |" in md
    assert "- backup / backup: restored: <rows differ>" in md


def test_the_password_and_key_never_reach_a_command_line() -> None:
    src = (ROOT / "tools" / "complete_run.py").read_text(encoding="utf-8")
    assert "TB_SHOT_PASSWORD" in src and '"--password"' not in src
    assert "TB_GPU_KEY" in src and "--key" not in src
    js = (ROOT / "tools" / "stage_shots.js").read_text(encoding="utf-8")
    assert "process.env.TB_SHOT_PASSWORD" in js and "console.log(PASSWORD" not in js
