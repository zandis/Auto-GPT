"""H-29 (D-1103): one walk per module of the life cycle that H-10's and H-20's walks do not cover (V16), each for the
roles that use it, in en, zh-TW and ja, with the findings by step it reports. It fixes nothing.

The walks (``test_a_module_walk``, marked e2e) start one steps-mode box as H-10's walk does (its ``box`` fixture:
``tools.demo``, demo mode off, the stub model, the synthetic hospital, ``--day data``) and walk the four plans
(``tests/e2e/module_walk_<module>_plan.py``: feasibility, safety, monitoring, amendment) in Chromium with H-20's
driver (``tests/e2e/module_walk.js`` requires ``life_cycle_walk.js`` and adds its acts through its ``extend``), once per module and page language. Safety and
amendment each begin a new study per language (``SAFEWALK``, ``AMENDWALK``; ``ZH`` and ``JA`` added) from H-20's
steps 1 to 15; feasibility and monitoring walk studies the box seeds (``AD-MAB``, ``GZQO``). Each writes a JSON log per
module and language (outside the repository: ``TB_WALK_LOG_DIR``, else the box's scratch folder) with, per step, the
page reached, the clicks, the time, the guesses, the refusals and any reasoned stop. A walk fails when a page, a text
or a role boundary differs from its plan; a reasoned stop is a finding of the plan that blocks the step, recorded with
the product's own words, never asserted as correct.

    TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/e2e/test_module_walks.py -m e2e
    make walk-modules                                    # the same; make walk-safety (feasibility, monitoring,
                                                         # amendment) walks one module

The parameters are H-10's (``TB_WALK_BASE``, ``TB_WALK_PASSWORD``; the box must run on ``--day data``), with
``TB_WALK_ACCOUNTS`` naming the six roles' accounts (``cro`` and ``viewer`` besides H-10's four) and ``TB_WALK_ID``
another base id for the two walks that begin a new study.

The other tests need no box: each module's steps are done by the role that owns them in the permission matrix and
refused to the roles that do not, every text is the product's in three languages, the plans begin with H-20's steps
unchanged, the driver is H-20's, required and extended, not copied, and the findings page holds exactly the plans' findings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e import life_cycle_walk_plan as lp
from tests.e2e import module_walk_common as mw
from tests.e2e import new_study_walk_plan as nw
from tests.e2e.test_new_study_walk import RULESET_ID, _node_playwright, box  # noqa: F401 (the fixture)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("module_walk.js")
DRIVER = Path(__file__).with_name("life_cycle_walk.js")
WALK_BUDGET_S = 900  # the longest, amendment, took about 3 minutes per language on a 4-core container (2026-11-17)
CASES = [(m, lang) for m in mw.MODULES for lang in mw.LANGS]


def accounts(environ: dict[str, str] | os._Environ[str], password: str) -> dict[str, str]:
    """The walks' accounts: ``TB_WALK_ACCOUNTS`` (a JSON object with an account per role of :data:`mw.ROLES`), else
    the box's seeded accounts. The module walks need an account per role (four-account mode): a CRO account and a
    viewer act besides H-10's four."""
    raw = (environ.get("TB_WALK_ACCOUNTS") or "").strip()
    given = json.loads(raw) if raw else dict(mw.SEEDED_ACCOUNTS)
    if not isinstance(given, dict) or "person" in given:
        raise ValueError("TB_WALK_ACCOUNTS names an account per role for the module walks")
    missing = [r for r in mw.ROLES if not given.get(r)]
    if missing:
        raise ValueError(f"TB_WALK_ACCOUNTS names no account for {', '.join(missing)}")
    return {"mode": "four", **{r: str(given[r]) for r in mw.ROLES}, "password": password}


def log_dir(environ: dict[str, str] | os._Environ[str]) -> Path:
    """Where the walks write their logs: ``TB_WALK_LOG_DIR``, else a folder of the box's scratch root (never the
    repository)."""
    given = (environ.get("TB_WALK_LOG_DIR") or "").strip()
    if given:
        out = Path(given)
    else:
        from tools import pglocal

        out = pglocal.scratch_root() / "module-walks"
    out.mkdir(parents=True, exist_ok=True)
    if ROOT in out.resolve().parents or out.resolve() == ROOT:
        raise ValueError(f"the walk's logs stay outside the repository: {out}")
    return out


#: the coordinator's daily limit of heavy runs on the box the walks start (D-146, D-775: 20 FEAS a day by default).
#: The four walks on one box start about 26 FEAS jobs from one coordinator account (each new study's protocol and
#: its FEAS, the amendments, the feasibility walk's runs, besides the seed's), so the 21st was refused "Today's limit
#: is reached" on the first run. The box is the walks' own; a box given by TB_WALK_BASE keeps its own limit.
JOBS_PER_DAY = "60"


@pytest.fixture(scope="module", autouse=True)
def _a_day_of_walks() -> Iterator[None]:
    """Before the box starts (autouse fixtures come first): the daily limit the box reads from its environment."""
    was = os.environ.get("TB_JOBS_PER_SENDER_PER_DAY")
    os.environ["TB_JOBS_PER_SENDER_PER_DAY"] = was or JOBS_PER_DAY
    yield
    if was is None:
        os.environ.pop("TB_JOBS_PER_SENDER_PER_DAY", None)


# ------------------------------------------------------------------------------------------------- the browser walk
@pytest.mark.e2e
@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
@pytest.mark.parametrize(("module", "lang"), CASES, ids=[f"{m}-{lang}" for m, lang in CASES])
def test_a_module_walk(box: tuple[str, str], module: str, lang: str) -> None:  # noqa: F811 (the fixture)
    base, password = box
    mod = mw.modules()[module]
    rs = mw.ids(mod, os.environ)[lang]
    assert RULESET_ID.match(rs), rs
    log = log_dir(os.environ) / f"module-walk-{module}-{lang}.json"
    plan = mw.plan_json(mod, lang, rs, accounts(os.environ, password), str(log))
    plan["base"] = base
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps(plan)],
        cwd=ROOT, capture_output=True, text=True, timeout=WALK_BUDGET_S, check=False,
    )  # fmt: skip
    lines = r.stdout.strip().splitlines()
    assert lines, r.stderr[-3000:]
    out = json.loads(lines[-1])
    assert not out["skipped"], out
    assert r.returncode == 0 and out["failed"] == 0, (out, r.stderr[-3000:])
    steps = json.loads(log.read_text(encoding="utf-8"))["steps"]
    assert [s["n"] for s in steps] == [st.n for st in mw.all_steps(mod)], [s["n"] for s in steps]
    for s in steps:
        if s["stopped"] and s["stopped"].get("finding"):
            # a reasoned stop: a finding of the plan that blocks the step, with the product's own words
            f = mw.finding(mod, s["stopped"]["finding"])
            assert f.step == s["n"] and f.severity == "blocks the step", (s["n"], f)
            assert s["stopped"]["page"], s
        elif s["stopped"]:
            st = next(x for x in mod.steps if x.n == s["n"])  # stands on a stopped step
            assert any(n in out["stopped"] for n in st.after), s
        else:
            assert s["path"], s
    refused = [x for s in steps for x in s["refusals"]]
    assert refused and all(x["status"] == 403 for x in refused), refused


# ------------------------------------------------------------------------------- the plans and the findings page
def _steps() -> list[tuple[str, mw.Step]]:
    return [(m, st) for m in mw.MODULES for st in mw.modules()[m].steps]


def test_the_driver_is_h20s_required_not_copied() -> None:
    """module_walk.js requires H-20's driver and adds its kinds through the driver's ``extend``; it holds no copy of
    the driver's own functions, and the driver still runs as a script for H-20's walk."""
    driver = DRIVER.read_text(encoding="utf-8")
    mine = SCRIPT.read_text(encoding="utf-8")
    assert 'require("./life_cycle_walk.js")' in mine and "driver.extend(" in mine and "driver.main()" in mine
    assert "module.exports = { extend:" in driver and "if (require.main === module) main();" in driver
    assert "if (extra.acts[a.do]) return extra.acts[a.do](p, a, tag, helpers);" in driver
    assert "if (extra.holds[a.kind]) return extra.holds[a.kind](p, a, helpers);" in driver
    for fn in ("signIn", "actAs", "refuse", "stopIf", "chooseLanguage", "holds"):
        assert f"function {fn}(" in driver and f"function {fn}(" not in mine, fn


def _kinds() -> set[str]:
    driver = set(re.findall(r'case "([a-z0-9_]+)"', DRIVER.read_text(encoding="utf-8")))
    mine = set(re.findall(r"async ([a-z0-9_]+)\(p, a", SCRIPT.read_text(encoding="utf-8")))
    return driver | mine


def test_the_driver_knows_every_act_of_the_plans() -> None:
    cases = _kinds()
    assert {"field", "pick", "choose", "check", "absent"} <= cases, cases
    acc = {"mode": "four", **mw.SEEDED_ACCOUNTS, "password": "-"}
    for m in mw.MODULES:
        mod = mw.modules()[m]
        for st in mw.plan_json(mod, "en", mw.ids(mod, {})["en"], acc)["steps"]:
            for a in st["acts"]:
                assert a["do"] in cases | {"stop"}, (m, a["do"])
                if a["do"] in ("see", "stop"):
                    assert a["kind"] in cases, (m, a["kind"])


@pytest.mark.parametrize("module", mw.MODULES)
def test_a_walk_that_begins_a_study_begins_with_h20s_steps_unchanged(module: str) -> None:
    mod = mw.modules()[module]
    acc = {"mode": "four", **mw.SEEDED_ACCOUNTS, "password": "-"}
    rs = mw.ids(mod, {})["en"]
    mine = mw.plan_json(mod, "en", rs, acc)["steps"]
    keep = ("n", "role", "acts", "refusals")
    if mod.prefix:
        h20 = [s for s in lp.plan_json("en", rs, acc)["steps"] if s["n"] <= mw.PREFIX_LAST]
        assert [{k: s[k] for k in keep} for s in mine[: len(h20)]] == [{k: s[k] for k in keep} for s in h20]
        assert [st.n for st in mod.steps] == list(range(mw.PREFIX_LAST + 1, mw.PREFIX_LAST + 1 + len(mod.steps)))
    else:
        assert [st.n for st in mod.steps] == list(range(1, len(mod.steps) + 1))
    assert [s["n"] for s in mine] == [st.n for st in mw.all_steps(mod)]


@pytest.mark.parametrize(("module", "n"), [(m, st.n) for m, st in _steps()], ids=[f"{m}-{st.n}" for m, st in _steps()])
def test_each_step_is_done_by_the_role_that_owns_it(module: str, n: int) -> None:
    """The step's role holds the step's matrix row (a condition counts: the PI through the delegation log, the CRO
    account through its monitor grant); every refusal's role holds no grant of it."""
    from tb_common.authz import conditional, permit

    st = next(x for x in mw.modules()[module].steps if x.n == n)
    if not st.row:
        assert st.why_no_row, (module, n)
        return
    role = mw.CONSOLE_ROLE[st.role]
    assert permit(role, st.row).allowed or conditional(role, st.row), (module, n, role, st.row)
    for r in st.refusals:
        other = mw.CONSOLE_ROLE[r.role]
        if other == role:
            continue  # the same role refused a page outside the step's row (the monitor's other pages)
        assert not permit(other, st.row).allowed and not conditional(other, st.row), (module, n, other, st.row)


@pytest.mark.parametrize("module", mw.MODULES)
def test_every_text_is_the_products_in_three_languages(module: str) -> None:
    _, cat = nw.catalogue()
    mod = mw.modules()[module]
    for st in mod.steps:
        for t in mw.texts_of(st):
            if isinstance(t, mw.F):
                assert t.key in mw.form_fields(), (module, st.n, t.key)
                assert t.text("en", "") and t.missing() == [], (module, st.n, t.key, t.option)
            elif t.key is not None:
                assert t.key in cat["en"], (module, st.n, t.key)
        for lang in mw.LANGS:
            assert mw.untranslated(st, lang) == [], (module, st.n, lang)


@pytest.mark.parametrize("module", mw.MODULES)
def test_every_role_boundary_has_a_refusal(module: str) -> None:
    """A walk has refusals, each with its reason, and every role of the walk acts or is refused in it."""
    mod = mw.modules()[module]
    refusals = [r for st in mod.steps for r in st.refusals]
    assert refusals and all(r.why.get("en") for r in refusals), module
    seen = {st.role for st in mod.steps} | {r.role for r in refusals}
    assert set(mod.roles) <= seen, (module, set(mod.roles) - seen)


@pytest.mark.parametrize("module", mw.MODULES)
def test_the_findings_are_well_formed(module: str) -> None:
    mod = mw.modules()[module]
    steps = {st.n for st in mw.all_steps(mod)}
    prefix = {"feasibility": "FEA", "safety": "SAF", "monitoring": "MON", "amendment": "AMD"}[module]
    ids = [f.id for f in mod.findings]
    assert ids == [f"{prefix}-{i:02d}" for i in range(1, len(ids) + 1)], ids
    for f in mod.findings:
        assert f.step in steps and f.severity in mw.SEVERITIES and f.lane in mw.LANES, f
        assert f.role in mw.ROLES and f.path.startswith("/") and f.showed and f.expected and f.source, f
        assert f.kind in mw.KINDS and (f.kind == "stop") == (f.severity == "blocks the step"), f
    used = {a.finding for st in mod.steps for a in st.acts if isinstance(a, (mw.Act, mw.Stop)) and a.finding}
    assert used <= set(ids), used - set(ids)
    stops = {a.finding for st in mod.steps for a in st.acts if isinstance(a, mw.Stop)}
    assert stops == {f.id for f in mod.findings if f.kind == "stop"}, stops
    for n, what, why in mod.not_completed:
        assert n in steps and what and why, n


def test_the_page_holds_the_findings_the_plans_have() -> None:
    """One source: the tables between the marker lines are what module_walk_common writes. After a change of a plan:
    PYTHONPATH=libs:services:. python -m tests.e2e.module_walk_common --write."""
    page = mw.FINDINGS_PAGE.read_text(encoding="utf-8")
    assert mw.block_of(page) == mw.render_findings(), (
        "docs/handover/module-walks-findings-2026-11-17.md differs from the plans: "
        "PYTHONPATH=libs:services:. python -m tests.e2e.module_walk_common --write"
    )
    assert page.splitlines()[2].startswith("**Reader:**")
    for must in (
        "D-1103",
        "D-1135",
        "D-1121",
        "D-1062",
        "D-1066",
        "make walk-modules",
        ": cannot complete on a steps-mode box",
    ):
        assert must in page, must
    for key in mw.MODULES:
        for n, what, _why in mw.modules()[key].not_completed:
            assert what in page, (key, n, what)


def test_the_new_ids_are_new_to_the_stub_and_the_box() -> None:
    stems = {p.stem for p in (ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract").glob("*.json")}
    others = {*nw.RULESETS.values(), *lp.RULESETS.values()}
    for m in mw.MODULES:
        mod = mw.modules()[m]
        if mod.study:
            assert (ROOT / "rulesets" / mod.study).is_dir(), mod.study  # a study the box seeds
            continue
        for rs in mod.rulesets.values():
            assert RULESET_ID.match(rs) and not (ROOT / "rulesets" / rs).exists(), rs
            assert rs not in stems and not any(rs.startswith(s + "-") for s in stems), rs
            assert rs not in others, rs  # never H-10's or H-20's: the walks may share one box
            others.add(rs)


def test_the_accounts_and_the_logs(tmp_path: Path) -> None:
    acc = accounts({}, "-")
    assert acc["cro"] == "cra" and acc["viewer"] == "viewer" and acc["investigator"] == "pi", acc
    with pytest.raises(ValueError, match="no account for"):
        accounts({"TB_WALK_ACCOUNTS": json.dumps(nw.SEEDED_ACCOUNTS)}, "-")
    with pytest.raises(ValueError, match="an account per role"):
        accounts({"TB_WALK_ACCOUNTS": json.dumps({"person": "me"})}, "-")
    assert log_dir({"TB_WALK_LOG_DIR": str(tmp_path / "logs")}) == tmp_path / "logs"
    with pytest.raises(ValueError, match="outside the repository"):
        log_dir({"TB_WALK_LOG_DIR": str(ROOT / "tests" / "e2e")})
    safety = mw.modules()["safety"]
    assert mw.ids(safety, {"TB_WALK_ID": "trysafe"}) == {"en": "TRYSAFES", "zh-TW": "TRYSAFESZH", "ja": "TRYSAFESJA"}
    assert set(mw.ids(mw.modules()["monitoring"], {"TB_WALK_ID": "x"}).values()) == {"GZQO"}


def test_the_findings_file_is_the_registers_form() -> None:
    """The findings beside the page, in the register's ``--add-from`` form (card H29), equal to the plans; their rows
    wait for lane V (the register is pinned to its seed rows), so they are not in the register."""
    from tools import findings_register as fr

    assert mw.FINDINGS_JSON.read_text(encoding="utf-8") == mw.findings_json(), (
        "PYTHONPATH=libs:services:. python -m tests.e2e.module_walk_common --write"
    )
    doc = json.loads(mw.findings_json())
    rows = doc["findings"]
    assert doc["card"] == "H29" and (ROOT / doc["source"]).is_file()
    assert len(rows) == sum(len(mw.modules()[m].findings) for m in mw.MODULES)
    for r in rows:
        assert r["id"].startswith("H29-") and r["lane"] in fr.LANES and r["basis"] == "shown", r
        assert r["severity"] in ("Medium (mapped)", "Low (mapped)") and "\n" not in r["claim"], r
    assert "H29-" not in fr.REGISTER.read_text(encoding="utf-8")
