"""H-20 (D-1135): the whole life of a study, walked in a browser on a box in steps mode, by the role that owns each
step, and the findings list by step it reports.

The walk (``test_the_whole_life_of_a_study``, marked e2e) starts the steps-mode box as H-10's walk does (its
``box`` fixture: ``tools.demo``, demo mode off, the stub model, the synthetic hospital) and walks
``tests/e2e/life_cycle_walk_plan.py`` in Chromium (``tests/e2e/life_cycle_walk.js``) once per page language, each
under its own new ruleset id: H-10's eleven steps unchanged, then the weekly page, Approach, the contact outcome,
consent and enrolment, the withdrawal, the close, the opt-out and the erase. It writes a JSON log per language
(outside the repository: ``TB_WALK_LOG_DIR``, else the box's scratch folder) with, per step, the page reached, the
clicks, the time, the guesses and the refusals. It fails when a page, a text or a role boundary differs from the plan.
A step that stops is a reasoned stop read from the product (a finding of the plan that blocks the step); it never
passes a fault as correct.

    TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/e2e/test_life_cycle_walk.py -m e2e
    make walk-life-cycle                                 # the same

The parameters are H-10's (``TB_WALK_ACCOUNTS``, ``TB_WALK_BASE``, ``TB_WALK_PASSWORD``), with ``TB_WALK_ID`` for
this walk's ids (default ``LIFEWALK``; the zh-TW and ja walks add ``ZH`` and ``JA``).

The other tests need no box: the plan continues H-10's steps unchanged, each step's role owns its step in the
permission matrix and each refusal's role does not, every text is the console's, and the findings page holds exactly
the plan's findings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.e2e import life_cycle_walk_plan as lp
from tests.e2e import new_study_walk_plan as nw
from tests.e2e.test_new_study_walk import RULESET_ID, _node_playwright, accounts, box  # noqa: F401 (the fixture)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("life_cycle_walk.js")
WALK_BUDGET_S = 900  # one language's whole walk took 110 to 140 s on a 4-core container (2026-11-17)


def ruleset_ids(environ: dict[str, str] | os._Environ[str]) -> dict[str, str]:
    base = (environ.get("TB_WALK_ID") or "").strip().upper()
    if not base:
        return dict(lp.RULESETS)
    return {"en": base, "zh-TW": base + "ZH", "ja": base + "JA"}


def log_dir(environ: dict[str, str] | os._Environ[str]) -> Path:
    """Where the walk writes its logs: ``TB_WALK_LOG_DIR``, else a folder of the box's scratch root (never the repo)."""
    given = (environ.get("TB_WALK_LOG_DIR") or "").strip()
    if given:
        out = Path(given)
    else:
        from tools import pglocal

        out = pglocal.scratch_root() / "life-cycle-walk"
    out.mkdir(parents=True, exist_ok=True)
    if ROOT in out.resolve().parents or out.resolve() == ROOT:
        raise ValueError(f"the walk's logs stay outside the repository: {out}")
    return out


# ------------------------------------------------------------------------------------------------- the browser walk
@pytest.mark.e2e
@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
@pytest.mark.parametrize("lang", lp.LANGS)
def test_the_whole_life_of_a_study(box: tuple[str, str], lang: str) -> None:  # noqa: F811 (the fixture)
    base, password = box
    rs = ruleset_ids(os.environ)[lang]
    assert RULESET_ID.match(rs), rs
    log = log_dir(os.environ) / f"life-cycle-walk-{lang}.json"
    plan = lp.plan_json(lang, rs, accounts(os.environ, password), str(log))
    plan["base"] = base
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps(plan)],
        cwd=ROOT, capture_output=True, text=True, timeout=WALK_BUDGET_S, check=False,
    )  # fmt: skip
    lines = r.stdout.strip().splitlines()
    assert lines, r.stderr[-3000:]
    out = json.loads(lines[-1])
    if out["skipped"]:
        pytest.skip(out["skipped"])  # the box's own answer (one-account mode on a box without D-1063)
    assert r.returncode == 0 and out["failed"] == 0, (out, r.stderr[-3000:])
    steps = json.loads(log.read_text(encoding="utf-8"))["steps"]
    assert [s["n"] for s in steps] == [st.n for st in lp.all_steps()], [s["n"] for s in steps]
    for s in steps:
        if s["stopped"] and s["stopped"].get("finding"):
            # a reasoned stop: a finding of the plan that blocks the step, with the product's own words
            f = lp.finding(s["stopped"]["finding"])
            assert f.step == s["n"] and f.severity == "blocks the step", (s["n"], f)
            assert s["stopped"]["page"], s
        elif s["stopped"]:
            # stands on a stopped step
            st = next(lf for lf in lp.LIFE if lf.step.n == s["n"])
            assert any(n in out["stopped"] for n in st.after), s
        else:
            assert (s["path"] and s["heading"]) or s["n"] == 21, s
    refused = [x for s in steps for x in s["refusals"]]
    assert refused and all(x["status"] == 403 for x in refused), refused
    assert out["checks"] >= 90, out


# ------------------------------------------------------------------------------- the plan and the findings page
def test_the_new_study_steps_are_h10s_unchanged() -> None:
    """Steps 1 to 11 are H-10's, as H-10's walk clicks them; the life-cycle steps follow, numbered on."""
    acc = {"mode": "four", **nw.SEEDED_ACCOUNTS, "password": "-"}
    mine = lp.plan_json("en", "LIFEWALK", acc)["steps"]
    h10 = nw.plan_json("en", "LIFEWALK", acc)["steps"]
    keep = ("n", "role", "acts", "refusals")
    assert [{k: s[k] for k in keep} for s in mine[: len(h10)]] == [{k: s[k] for k in keep} for s in h10]
    assert [s["n"] for s in mine] == list(range(1, len(mine) + 1))
    assert [lf.step.n for lf in lp.LIFE] == list(range(len(h10) + 1, len(mine) + 1))


@pytest.mark.parametrize("n", sorted(lp.OWNER_ROW))
def test_each_step_is_done_by_the_role_that_owns_it(n: int) -> None:
    """The step's role holds the step's matrix row (the investigator through the delegation log, as the PI); every
    refusal's role does not hold it."""
    from tb_common.authz import conditional, permit

    st = next(lf.step for lf in lp.LIFE if lf.step.n == n)
    row = lp.OWNER_ROW[n]
    role = nw.CONSOLE_ROLE[st.role]
    assert permit(role, row).allowed or conditional(role, row), (n, role, row)
    for r in st.refusals:
        other = nw.CONSOLE_ROLE[r.role]
        assert not permit(other, row).allowed and not conditional(other, row), (n, other, row)


def test_every_new_role_boundary_has_a_refusal() -> None:
    """Each life-cycle step that a role owns alone has at least one refusal of another role, with its why in three
    languages; step 18 (showing a chart number) and step 20 (reading the lists) cross no new boundary."""
    for lf in lp.LIFE:
        if lf.step.n in (18, 20):
            continue
        assert lf.step.refusals, lf.step.n
        for r in lf.step.refusals:
            assert set(r.why) == set(lp.LANGS) and all(r.why.values()), (lf.step.n, r)


def test_every_text_is_a_key_of_the_console_catalogue() -> None:
    _, cat = nw.catalogue()
    for st in lp.all_steps():
        for t in lp.texts_of(st):
            if t.key is not None:
                assert t.key in cat["en"], (st.n, t.key)
    for lf in lp.LIFE:
        for lang in lp.LANGS:
            assert lp.untranslated(lf.step, lang) == [], (lf.step.n, lang)


def test_the_findings_are_well_formed() -> None:
    steps = {st.n: st for st in lp.all_steps()}
    ids = [f.id for f in lp.FINDINGS]
    assert ids == sorted(set(ids)) and ids == [f"F-{i:02d}" for i in range(1, len(ids) + 1)], ids
    for f in lp.FINDINGS:
        assert f.step in steps and f.severity in lp.SEVERITIES and f.lane in lp.LANES, f
        assert f.role in nw.ROLES and f.path.startswith("/") and f.showed and f.expected and f.source, f
        assert f.kind in ("label", "testid", "address", "confirmation", "way back", "required", "language", "term",
                          "other", "stop"), f  # fmt: skip
        assert (f.kind == "stop") == (f.severity == "blocks the step"), f
    used = {a.finding for lf in lp.LIFE for a in lf.step.acts if isinstance(a, (lp.Act, lp.Stop)) and a.finding}
    assert used - {"F-00"} <= set(ids), used
    for n, what, why in lp.NOT_COMPLETED:
        assert n in steps and what and why, n


def test_the_page_holds_the_findings_the_plan_has() -> None:
    """One source: the table between the marker lines is what life_cycle_walk_plan writes. After a change of the
    findings: PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --write."""
    page = lp.FINDINGS_PAGE.read_text(encoding="utf-8")
    assert lp.block_of(page) == lp.render_findings(), (
        "docs/handover/life-cycle-walk-findings-2026-11-17.md differs from the plan: "
        "PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --write"
    )
    assert page.splitlines()[2].startswith("**Reader:**")
    for must in ("D-1135", "D-1121", "D-1062", "make walk-life-cycle", "## Steps a steps-mode box cannot complete",
                 "## Counts"):  # fmt: skip
        assert must in page, must
    for n, what, _why in lp.NOT_COMPLETED:
        assert what in page, (n, what)
    for sev in lp.SEVERITIES:
        count = sum(f.severity == sev for f in lp.FINDINGS)
        assert f"| {sev} | {count} |" in page, (sev, count)


def test_the_new_ids_are_new_to_the_stub_and_the_box() -> None:
    stems = {p.stem for p in (ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract").glob("*.json")}
    for rs in lp.RULESETS.values():
        assert RULESET_ID.match(rs), rs
        assert not (ROOT / "rulesets" / rs).exists(), rs
        assert rs not in stems and not any(rs.startswith(s + "-") for s in stems), rs
        assert rs not in nw.RULESETS.values(), rs  # never H-10's: the two walks may share one box


def test_the_summary_of_a_log() -> None:
    log = {"steps": [{"n": 12, "role": "coordinator", "lang": "en", "path": "/x", "heading": "h", "seconds": 2.0,
                      "clicks": ["a", "b"], "guesses": [{"finding": "F-01"}], "refusals":
                      [{"role": "steward", "request": "GET /x", "status": 403}], "stopped": None}]}  # fmt: skip
    got = lp.summarise([log, log])[12]
    assert got["clicks"] == 2 and got["click_texts"] == ["a", "b"] and got["guesses"] == ["F-01"]
    assert got["refusals"] == ["steward GET /x 403"] and got["runs"] == 2 and got["seconds"] == 2.0


def test_the_logs_stay_outside_the_repository(tmp_path: Path) -> None:
    assert log_dir({"TB_WALK_LOG_DIR": str(tmp_path / "logs")}) == tmp_path / "logs"
    with pytest.raises(ValueError, match="outside the repository"):
        log_dir({"TB_WALK_LOG_DIR": str(ROOT / "tests" / "e2e")})
    assert ruleset_ids({"TB_WALK_ID": "trylife"}) == {"en": "TRYLIFE", "zh-TW": "TRYLIFEZH", "ja": "TRYLIFEJA"}


def test_the_driver_knows_every_act_of_the_plan() -> None:
    """Every act kind the plan sends is one the browser driver handles (a case of its switch)."""
    code = SCRIPT.read_text(encoding="utf-8")
    cases = set(re.findall(r'case "([a-z0-9_]+)"', code))
    acc = {"mode": "four", **nw.SEEDED_ACCOUNTS, "password": "-"}
    for st in lp.plan_json("en", "LIFEWALK", acc)["steps"]:
        for a in st["acts"]:
            assert a["do"] in cases | {"stop"}, a["do"]
            if a["do"] in ("see", "stop"):
                assert a["kind"] in cases, a["kind"]
