"""H-10 (D-1121): a new study from its first step, walked in a browser on a box in steps mode, and the tester's page
that says the same steps.

The walk (``test_a_new_study_from_its_first_step``, marked e2e) starts the steps-mode box locally: ``tools.demo``,
which is what the preview VM runs (D-1062): demo mode off, the stub model, the synthetic hospital. It then walks
``tests/e2e/new_study_walk_plan.py`` in Chromium (``tests/e2e/new_study_walk.js``, Node Playwright, preinstalled
browser) once per page language, each under its own new ruleset id: the coordinator pastes the SITE5B criteria, the
data steward names the PI, the PI approves, the coordinator runs FEAS and SCREEN and reads the candidate list. It
fails when a page, its heading, a link or button text, or a role boundary differs from the plan.

    TB_INTEGRATION=1 TB_ENV=TEST PYTHONPATH=libs:services:. .venv/bin/python -m pytest tests/e2e/test_new_study_walk.py -m e2e
    make walk-new-study                                  # the same

Parameters, from the environment (all optional):

* ``TB_WALK_ACCOUNTS``: JSON. ``{"coordinator": u, "steward": u, "investigator": u, "operator": u}`` signs each role
  in with its own account (four-account mode; the default is the box's seeded accounts crc, stw, pi, admin).
  ``{"person": u}`` signs one person in who switches the acting role (D-1063, one-account mode); a box that offers no
  acting role skips the walk with what it showed.
* ``TB_WALK_BASE`` and ``TB_WALK_PASSWORD``: walk a box that is already running instead of starting one (the
  accounts' password; never printed). ``TB_WALK_ID``: the new ruleset id (default ``WALKNEW``; the zh-TW and ja walks
  add ``ZH`` and ``JA``), which must be new to that box.

The other tests here need no box: the tester's pages hold exactly the steps the walk clicks (one source), and the
facts the pages state about the stub model are the stub's.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.e2e import new_study_walk_plan as wp

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("new_study_walk.js")
STUB = ROOT / "services" / "llm_stub" / "handlers.py"
RULESET_ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}$")  # console.app._RULESET_ID
SEED_BUDGET_S = 1500  # the seed took 410 to 430 s on a 4-core container (2026-11-17); CI's demo-boot budget is 600 s
WALK_BUDGET_S = 900
#: H-25 (D-1124): set while a box this module started runs: the folder of its audit log
AUDIT_DIR_ENV = (
    "TB_WALK_AUDIT_DIR"  # one language's walk took 65 to 71 s there, SCREEN of the whole hospital about 40 s of it
)


# ------------------------------------------------------------------------------------------------- the browser walk
def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def accounts(environ: dict[str, str] | os._Environ[str], password: str) -> dict[str, str]:
    """The walk's accounts from ``TB_WALK_ACCOUNTS`` (see the module's text), with the password."""
    raw = (environ.get("TB_WALK_ACCOUNTS") or "").strip()
    given = json.loads(raw) if raw else dict(wp.SEEDED_ACCOUNTS)
    if not isinstance(given, dict):
        raise ValueError("TB_WALK_ACCOUNTS is a JSON object")
    if "person" in given:
        person = str(given["person"])
        return {"mode": "one", "person": person, "investigator": person, "password": password}
    missing = [r for r in wp.ROLES if not given.get(r)]
    if missing:
        raise ValueError(f"TB_WALK_ACCOUNTS names no account for {', '.join(missing)}")
    return {"mode": "four", **{r: str(given[r]) for r in wp.ROLES}, "password": password}


def ruleset_ids(environ: dict[str, str] | os._Environ[str]) -> dict[str, str]:
    base = (environ.get("TB_WALK_ID") or "").strip().upper()
    if not base:
        return dict(wp.RULESETS)
    return {"en": base, "zh-TW": base + "ZH", "ja": base + "JA"}


@pytest.fixture(scope="module")
def box() -> Iterator[tuple[str, str]]:
    """(base address, password) of a box in steps mode: the one TB_WALK_BASE names, or a fresh local one."""
    given = os.environ.get("TB_WALK_BASE", "").strip()
    if given:
        password = os.environ.get("TB_WALK_PASSWORD", "")
        if not password:
            pytest.fail("TB_WALK_BASE is set: TB_WALK_PASSWORD must hold the accounts' password")
        yield given.rstrip("/"), password
        return
    from tools import pglocal

    # not pytest's tmp_path: the box's PostgreSQL runs as another user on a root container and must reach its folder
    pglocal.scratch_root().mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tb-walk-new-study-", dir=pglocal.scratch_root()))
    work.chmod(0o755)
    password = secrets.token_urlsafe(18)
    port = _free_port()
    env = {**os.environ, "TB_DEMO_PASSWORD": password, "TB_ENV": "DEV", "PYTHONPATH": "libs:services:."}
    env.pop("TB_DEMO_ACCOUNTS", None)  # steps mode: the seed's own accounts, demo mode off (D-1062)
    log_path = work / "box.log"
    log = log_path.open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.demo", "--dir", str(work / "box"), "--lang", "en", "--day", "data",
         "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + SEED_BUDGET_S
        while True:  # the state waited on: the console answers its sign-in page
            assert proc.poll() is None, log_path.read_text(encoding="utf-8")[-3000:]
            try:
                if httpx.get(base + "/login", timeout=5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"the steps-mode box did not answer within {SEED_BUDGET_S} s")
            time.sleep(2)
        # H-25 (D-1124): where this box writes its audit log, for a walk that reads what the box recorded
        os.environ[AUDIT_DIR_ENV] = str(work / "box" / "box" / "audit")
        yield base, password
    finally:
        os.environ.pop(AUDIT_DIR_ENV, None)
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        shutil.rmtree(work, ignore_errors=True)


@pytest.mark.e2e
@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
@pytest.mark.parametrize("lang", wp.LANGS)
def test_a_new_study_from_its_first_step(box: tuple[str, str], lang: str) -> None:
    base, password = box
    rs = ruleset_ids(os.environ)[lang]
    assert RULESET_ID.match(rs), rs
    plan = wp.plan_json(lang, rs, accounts(os.environ, password))
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
    assert out["checks"] >= 60, out


# ------------------------------------------------------------------------------- the tester's pages and the plan
def _page(lang: str) -> str:
    return wp.PAGES[lang].read_text(encoding="utf-8")


def _shape(text: str) -> tuple[list[int], int, int, int, int]:
    lines = text.splitlines()
    return (
        [ln.count("#") for ln in lines if ln.startswith("#")],
        sum(ln.startswith("- ") for ln in lines),
        sum(bool(re.match(r"[1-9][0-9]?\. ", ln)) for ln in lines),
        sum(ln.startswith("| ") for ln in lines),
        sum(ln.startswith("```") for ln in lines),
    )


@pytest.mark.parametrize("lang", wp.LANGS)
def test_the_page_holds_the_steps_the_walk_clicks(lang: str) -> None:
    """One source: the part between the marker lines is what new_study_walk_plan writes from the console's catalogue.
    After a change of the plan or of a product text: python -m tests.e2e.new_study_walk_plan --write."""
    assert wp.block_of(_page(lang)) == wp.render_block(lang), (
        f"docs/handover/new-study-walk.{lang}.md differs from the walk: "
        "PYTHONPATH=libs:services:. python -m tests.e2e.new_study_walk_plan --write"
    )


@pytest.mark.parametrize("lang", wp.LANGS)
def test_every_text_the_walk_clicks_is_on_every_page(lang: str) -> None:
    """The texts of the browser's plan in ``lang`` (links, buttons, fields, headings) are on all three pages."""
    plan = wp.plan_json(lang, wp.SHOWN_ID, wp.SEEDED_ACCOUNTS)
    pages = {lg: _page(lg) for lg in wp.LANGS}
    for st in plan["steps"]:
        for a in st["acts"]:
            for text in (a["text"], a.get("label", "")):
                if not text or a["do"] in ("see", "language"):
                    continue
                for lg, page in pages.items():
                    assert text.replace("|", "\\|") in page, (lg, st["n"], a["do"], text)
    for page in pages.values():
        assert plan["signin"] in page and plan["forbidden"] in page and plan["more"] in page


def test_every_text_is_a_key_of_the_console_catalogue() -> None:
    """A text the walk uses is the product's: its key is in the served console's catalogue (no key falls back to
    itself), and the step tables mark any text the product has in English only (none on 2026-11-17)."""
    _, cat = wp.catalogue()
    for t in wp.all_texts():
        if t.key is not None:
            assert t.key in cat["en"], t.key
    for lang in wp.LANGS:
        for finding in wp.findings():
            assert wp.WORDS[lang]["none"] in _page(lang), (lang, finding)


def test_the_pages_have_the_same_parts_in_three_languages() -> None:
    from tb_common.wording import check

    from tools.e2e_simple import SITE_CRITERIA

    shapes = {}
    for lang in wp.LANGS:
        page = _page(lang)
        assert page.splitlines()[2].startswith("**Reader:**"), lang
        # the protocol's own words are quoted as written; the page's own words give no verdict (TB-IU-01 §2)
        assert "```text\n" + SITE_CRITERIA + "```" in page, lang
        assert check(re.sub(r"```text\n.*?```", "", page, flags=re.S)) == [], lang
        for must in ("D-1121", "D-1062", "D-1063", "services/llm_stub/handlers.py", "make walk-new-study"):
            assert must in page, (lang, must)
        shapes[lang] = _shape(page)
    assert shapes["en"] == shapes["zh-TW"] == shapes["ja"], shapes


def test_the_new_ids_are_new_to_the_stub_and_the_box() -> None:
    """The walk's ids are valid ruleset ids, no shipped ruleset has them, and the stub has no cassette for them (nor
    one they start with followed by "-", which the stub would reuse): the stub has not seen the pasted text under
    them, which is what the walk shows."""
    stems = {p.stem for p in (ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract").glob("*.json")}
    assert "SITE5B" in stems
    for rs in {*wp.RULESETS.values(), wp.SHOWN_ID}:
        assert RULESET_ID.match(rs), rs
        assert not (ROOT / "rulesets" / rs).exists(), rs
        assert rs not in stems and not any(rs.startswith(s + "-") for s in stems), rs


def _lines(text: str) -> list[dict[str, str]]:
    kind, out = "", []
    for ln in text.splitlines():
        if ln.startswith("Inclusion"):
            kind = "inclusion"
        elif ln.startswith("Exclusion"):
            kind = "exclusion"
        elif m := re.match(r"\d+\.\s+(.*)", ln):
            out.append({"text": m.group(1), "kind": kind})
    return out


def test_what_the_page_says_the_stub_does_with_text_it_has_not_seen() -> None:
    """The stub's criteria reader (``ir_extract``) under a new id: the age line by its pattern (a fixed filter), the
    three others to a person (step 4's split, 1 and 3); under SITE5B it answers from its cassette instead."""
    from llm_stub import handlers

    from tools.e2e_simple import SITE_CRITERIA

    lines = _lines(SITE_CRITERIA)
    assert [ln["kind"] for ln in lines] == ["inclusion", "inclusion", "inclusion", "exclusion"]
    new = handlers.ir_extract({"ruleset": wp.RULESETS["en"], "criteria": lines})["criteria"]
    assert [c["class"] for c in new] == ["structured", "human", "human", "human"]
    assert new[0]["logic"] == {"domain": "demographic", "age": {"min": 18.0}}
    assert all(c["human_question"].startswith("Confirm with the patient/clinician: ") for c in new[1:])
    assert all(c["label"] == c["text"][:40] for c in new)
    seen = handlers.ir_extract({"ruleset": "SITE5B", "criteria": lines})["criteria"]
    assert [c["class"] for c in seen] == ["structured"] * 4  # the cassette codes all four lines
    # the step-4 split the walk asserts is this reading
    split = next(a for a in wp.STEPS[3].acts if isinstance(a, wp.See) and a.text and a.text.key == "s20.split")
    assert split.text is not None and dict(split.text.values) == {"n": "4", "s": "1", "m": "0", "x": "0", "h": "3"}
    # the page's file references name what the stub's code has
    code = STUB.read_text(encoding="utf-8")
    for name in ("def ir_extract", "def _heuristic_criterion", "def judge", "def concept_map", "CASSETTES = "):
        assert name in code, name
    for lang in wp.LANGS:
        for name in ("ir_extract", "_heuristic_criterion", "judge", "concept_map", "cassettes/ir_extract"):
            assert name in _page(lang), (lang, name)


def test_the_accounts_parameter() -> None:
    assert accounts({}, "pw") == {"mode": "four", **wp.SEEDED_ACCOUNTS, "password": "pw"}
    one = accounts({"TB_WALK_ACCOUNTS": '{"person": "tester1"}'}, "pw")
    assert one == {"mode": "one", "person": "tester1", "investigator": "tester1", "password": "pw"}
    with pytest.raises(ValueError, match="operator"):
        accounts({"TB_WALK_ACCOUNTS": '{"coordinator": "a", "steward": "b", "investigator": "c"}'}, "pw")
    assert ruleset_ids({"TB_WALK_ID": "trynew"}) == {"en": "TRYNEW", "zh-TW": "TRYNEWZH", "ja": "TRYNEWJA"}
