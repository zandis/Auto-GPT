"""J-3 (D-1222): the phone tasks of the journey review, each done on a 390 x 844 phone with the flag
``layout.phone_first`` on, in en, zh-TW and ja.

The walk (``test_the_phone_tasks_on_a_phone``, marked e2e) starts the steps-mode box as H-10's walk does (its ``box``
fixture: ``tools.demo``, demo mode off, the stub model, the synthetic hospital), switches the flag on as the
administrator does on ``/ops/flags``, and runs ``tests/e2e/phone_walk.js`` once per language: the morning mail's link (the console's own page, then Continue; a link to a file downloads nothing)
with a live session (a link on another site's page) and without one, a candidate's evidence, Need info and Not suitable
(undone), the contact outcome after an Approach (undone), the coordinator's task list, a participant looked up, and an
SAE form half filled when the session ends, back after sign-in. It writes a JSON log per language (outside the
repository: ``TB_WALK_LOG_DIR``, else the box's scratch folder) with each task's taps, whether it was done, and its
screenshot.

    TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/e2e/test_phone_walk.py -m e2e

``TB_WALK_BASE`` and ``TB_WALK_PASSWORD`` walk a box already running instead (its flag is switched on). The other tests
need no box: the plan holds every row of the review's table, and the driver knows every task the plan walks."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.e2e import phone_walk_plan as pp
from tests.e2e.test_new_study_walk import _node_playwright, box  # noqa: F401 (the fixture)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("phone_walk.js")
WALK_BUDGET_S = 600  # one language took about 60 s on a 4-core container (2026-11-17)


def log_dir(environ: dict[str, str] | os._Environ[str]) -> Path:
    given = (environ.get("TB_WALK_LOG_DIR") or "").strip()
    if given:
        out = Path(given)
    else:
        from tools import pglocal

        out = pglocal.scratch_root() / "phone-walk"
    out.mkdir(parents=True, exist_ok=True)
    if ROOT in out.resolve().parents or out.resolve() == ROOT:
        raise ValueError(f"the walk's logs stay outside the repository: {out}")
    return out


@pytest.mark.e2e
@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
@pytest.mark.parametrize("lang", pp.LANGS)
def test_the_phone_tasks_on_a_phone(box: tuple[str, str], lang: str) -> None:  # noqa: F811 (the fixture)
    base, password = box
    out_dir = log_dir(os.environ)
    plan = {"base": base, "password": password, "lang": lang, "shots": str(out_dir), "pick": pp.LANGS.index(lang),
            "tasks": [t for t in pp.walked() if t != "not_suitable"]}  # fmt: skip
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps(plan)],
        cwd=ROOT, capture_output=True, text=True, timeout=WALK_BUDGET_S, check=False,
    )  # fmt: skip
    lines = r.stdout.strip().splitlines()
    assert lines, r.stderr[-3000:]
    out = json.loads(lines[-1])
    (out_dir / f"phone-walk-{lang}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    assert r.returncode == 0 and out["failed"] == 0, (out["failures"], r.stderr[-3000:])
    done = {x["task"]: x for x in out["results"]}
    assert set(done) == set(pp.walked()), sorted(done)
    assert all(x["done"] for x in done.values()), done
    assert all(Path(x["shot"]).is_file() for x in done.values() if x["shot"]), done


# ------------------------------------------------------------------------------------------------- the plan
def test_the_plan_holds_every_row_of_the_reviews_table() -> None:
    rows = pp.review_rows()
    assert [(t.task, t.role) for t in pp.TASKS] == rows, rows
    for t in pp.TASKS:
        assert bool(t.walk) != bool(t.other), t  # walked, or the reason it is not


def test_the_driver_knows_every_task_the_plan_walks() -> None:
    code = SCRIPT.read_text(encoding="utf-8")
    known = set(re.findall(r"^  async (\w+)\(browser", code, re.M)) | set(re.findall(r'record\("(\w+)"', code))
    assert set(pp.walked()) <= known, sorted(set(pp.walked()) - known)


def test_the_logs_stay_outside_the_repository(tmp_path: Path) -> None:
    assert log_dir({"TB_WALK_LOG_DIR": str(tmp_path / "logs")}) == tmp_path / "logs"
    with pytest.raises(ValueError, match="outside the repository"):
        log_dir({"TB_WALK_LOG_DIR": str(ROOT / "tests" / "e2e")})
