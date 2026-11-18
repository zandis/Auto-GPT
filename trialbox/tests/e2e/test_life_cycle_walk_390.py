"""H-21 (D-1138): H-20's whole-life-cycle walk on a phone 390 px wide, and the findings by step it reports.

The walk (``test_the_whole_life_of_a_study_on_a_phone``, marked e2e) starts the steps-mode box as H-10's and H-20's
walks do (H-10's ``box`` fixture) and drives ``tests/e2e/life_cycle_walk.js`` (H-20's driver) with the phone's
viewport (``tests/e2e/life_cycle_walk_390_plan.py``): the same steps, roles, three languages and refusals. Its log and
a screenshot per measure go to ``TB_WALK_LOG_DIR`` (else the box's scratch folder), never into the repository.

It fails when a page, a text or a refusal differs from the plan, or when the phone shows a measure (step, kind) or
stops at a step that the plan's findings do not name: a new problem must be read and recorded, never passed over. A
problem the product no longer has does not fail it. It never asserts a fault as correct.

    TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/e2e/test_life_cycle_walk_390.py -m e2e
    make walk-life-cycle-390                             # the same

The parameters are H-10's (``TB_WALK_ACCOUNTS``, ``TB_WALK_BASE``, ``TB_WALK_PASSWORD``), with ``TB_WALK_ID`` for
this walk's ids (default ``LIFEPHONE``; the zh-TW and ja walks add ``ZH`` and ``JA``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.e2e import life_cycle_walk_390_plan as pp
from tests.e2e import life_cycle_walk_plan as lp
from tests.e2e import new_study_walk_plan as nw
from tests.e2e.test_life_cycle_walk import log_dir
from tests.e2e.test_new_study_walk import RULESET_ID, _node_playwright, accounts, box  # noqa: F401 (the fixture)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("life_cycle_walk.js")
PHONE = Path(__file__).with_name("life_cycle_walk_phone.js")  # the phone's measures, loaded by the driver
WALK_BUDGET_S = 1200  # one language's walk on a phone took 140 to 190 s on a 4-core container (2026-11-17)


def ruleset_ids(environ: dict[str, str] | os._Environ[str]) -> dict[str, str]:
    base = (environ.get("TB_WALK_ID") or "").strip().upper()
    if not base:
        return dict(pp.RULESETS)
    return {"en": base, "zh-TW": base + "ZH", "ja": base + "JA"}


def page_of(path: str, rs: str) -> str:
    """A measured page as the findings write it: a job, the study id, a screening number by their names."""
    path = re.sub(r"/pilot/jobs/[0-9A-Z]{26}", "/pilot/jobs/{job}", path)
    path = re.sub(re.escape(rs) + r"-\d{4}", "{record}", path)
    return path.replace(rs, "{rs}")


def recorded(n: int, kind: str, page: str = "") -> bool:
    """Whether the plan's findings name the measure ``kind`` at step ``n`` (and on ``page``, when given)."""
    return any(n in f.steps() and f.kind == kind and (not page or page in f.paths()) for f in pp.FINDINGS)


@pytest.mark.e2e
@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
@pytest.mark.parametrize("lang", pp.LANGS)
def test_the_whole_life_of_a_study_on_a_phone(box: tuple[str, str], lang: str) -> None:  # noqa: F811 (the fixture)
    base, password = box
    rs = ruleset_ids(os.environ)[lang]
    assert RULESET_ID.match(rs), rs
    logs = log_dir(os.environ) / "phone"
    shots = logs / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    log = logs / f"life-cycle-walk-390-{lang}.json"
    plan = pp.plan_json(lang, rs, accounts(os.environ, password), str(log), str(shots))
    plan["base"] = base
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps(plan)],
        cwd=ROOT, capture_output=True, text=True, timeout=WALK_BUDGET_S, check=False,
    )  # fmt: skip
    lines = r.stdout.strip().splitlines()
    assert lines, r.stderr[-3000:]
    out = json.loads(lines[-1])
    if out["skipped"]:
        pytest.skip(out["skipped"])
    assert r.returncode == 0 and out["failed"] == 0, (out, r.stderr[-3000:])
    steps = json.loads(log.read_text(encoding="utf-8"))["steps"]
    pages = {(s["n"], m["kind"], page_of(m["path"], rs)) for s in steps for m in s["layout"]}
    new = sorted(x for x in pages if not recorded(*x))
    assert not new, f"measures the findings do not name yet (read the log {log}): {new}"
    for s in steps:
        stop = s.get("stopped") or {}
        if stop.get("finding") == "phone":
            assert recorded(s["n"], "cannot be reached"), (s["n"], stop)
        elif stop.get("finding"):
            assert lp.finding(stop["finding"]).severity == "blocks the step", s
    refused = [x for s in steps for x in s["refusals"]]
    assert all(x["status"] == 403 for x in refused), refused


# ------------------------------------------------------------------------------- the plan and the findings page
def test_the_phone_walks_h20s_plan() -> None:
    """The same steps, roles, acts and refusals as H-20's walk; only the viewport and the screenshots' folder differ."""
    acc = {"mode": "four", **nw.SEEDED_ACCOUNTS, "password": "-"}
    phone = pp.plan_json("en", "LIFEPHONE", acc, "/x.json", "/shots")
    h20 = lp.plan_json("en", "LIFEPHONE", acc, "/x.json")
    assert {k: v for k, v in phone.items() if k not in ("viewport", "shots")} == h20
    assert phone["viewport"] == {"width": 390, "height": 844} and phone["shots"] == "/shots"


def test_the_findings_are_well_formed() -> None:
    steps = {st.n: st for st in lp.all_steps()}
    ids = [f.id for f in pp.FINDINGS]
    assert ids == [f"P-{i:02d}" for i in range(1, len(ids) + 1)], ids
    for f in pp.FINDINGS:
        assert set(f.steps()) <= set(steps) and f.kind in pp.KINDS, f
        assert f.severity in pp.SEVERITIES and f.lane in pp.LANES, f
        assert f.role in nw.ROLES and f.path.startswith("/") and f.showed and f.expected and f.source, f
        assert f.severity != "blocks the step" or f.kind in ("cannot be reached", "off the screen", "covered"), f
    for n, what, why in pp.NOT_COMPLETED:
        assert n in steps and what and why, n


def test_the_page_holds_the_findings_the_plan_has() -> None:
    page = pp.FINDINGS_PAGE.read_text(encoding="utf-8")
    assert pp.block_of(page) == pp.render_findings(), (
        "docs/handover/life-cycle-walk-390-findings-2026-11-17.md differs from the plan: "
        "PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_390_plan --write"
    )
    assert page.splitlines()[2].startswith("**Reader:**")
    for must in ("D-1138", "D-1135", "make walk-life-cycle-390", "## Steps the phone cannot complete", "## Counts"):
        assert must in page, must
    for n, what, _why in pp.NOT_COMPLETED:
        assert what in page, (n, what)
    for sev in pp.SEVERITIES:
        count = sum(f.severity == sev for f in pp.FINDINGS)
        assert f"| {sev} | {count} |" in page, (sev, count)


def test_the_new_ids_are_new_to_the_stub_and_the_box() -> None:
    stems = {p.stem for p in (ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract").glob("*.json")}
    for rs in pp.RULESETS.values():
        assert RULESET_ID.match(rs), rs
        assert not (ROOT / "rulesets" / rs).exists(), rs
        assert rs not in stems and not any(rs.startswith(s + "-") for s in stems), rs
        assert rs not in nw.RULESETS.values() and rs not in lp.RULESETS.values(), rs


def test_the_driver_measures_what_the_plan_names() -> None:
    """Every measure kind of the plan is one the driver writes, and the driver keeps its screenshots in the plan's
    folder (never a path of its own)."""
    code = PHONE.read_text(encoding="utf-8")
    for kind in pp.KINDS:
        assert f'"{kind}"' in code, kind
    assert "plan.shots" in code and "viewport" in code
    driver = SCRIPT.read_text(encoding="utf-8")
    assert 'require("./life_cycle_walk_phone.js")' in driver and "plan.viewport ?" in driver


def test_the_measures_of_a_log() -> None:
    log = {"lang": "en", "steps": [{"n": 13, "role": "investigator", "layout": [
        {"kind": "target under 44 px", "path": "/studies/X/week", "what": "2: a 30x30", "shot": "en-step13.png"}],
        "stopped": None}]}  # fmt: skip
    got = pp.measures([log, {**log, "lang": "ja"}])[13]["layout"][("target under 44 px", "/studies/X/week")]
    assert got["langs"] == {"en", "ja"} and got["what"] == "2: a 30x30"
    assert "target under 44 px" in pp.summary_text([log])


def test_a_measured_page_is_named_as_the_findings_write_it() -> None:
    assert page_of("/pilot/jobs/01M7MNEAR90V1S663SCFNQH17V/approval", "LIFEPHONE") == "/pilot/jobs/{job}/approval"
    assert page_of("/studies/LIFEPHONEJA/subjects/LIFEPHONEJA-0001", "LIFEPHONEJA") == "/studies/{rs}/subjects/{record}"
    assert recorded(15, "table wider than the screen", "/studies/{rs}/subjects")
    assert not recorded(15, "table wider than the screen", "/studies/{rs}/elsewhere")
