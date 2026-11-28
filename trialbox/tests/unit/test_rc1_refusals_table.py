"""The table of rc1's refusals is whole (``tb_common.rc1_refusals``; the owner's ruling of 2026-11-20; R22-34).

Every row's sites ask the table with the row's name, every row's test exists and is collected, every message is in
en, ja and zh-TW and the console shows the same words, every row's environments are known ones; and the reverse:
every question asked of the table anywhere in ``libs``, ``services`` and ``tools`` names a row with a literal. So a
seventh refusal cannot be added at a site without its row, nor a row without its site and its test."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from tb_common import rc1_refusals as rr

ROOT = Path(__file__).resolve().parents[2]
ASKS = ("check", "refused")


def _module_file(module: str) -> Path:
    rel = Path(*module.split("."))
    for base in (ROOT / "libs", ROOT / "services", ROOT):
        for f in (base / rel.with_suffix(".py"), base / rel / "__init__.py"):
            if f.is_file():
                return f
    raise AssertionError(f"no module {module}")


def _module_of(f: Path) -> str:
    rel = f.relative_to(ROOT)
    if rel.parts[0] in ("libs", "services"):
        rel = Path(*rel.parts[1:])
    return ".".join(rel.with_suffix("").parts)


def _function(tree: ast.Module, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    body: list[ast.stmt] = tree.body
    node: ast.AST | None = None
    for part in qualname.split("."):
        node = next((n for n in body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                     and n.name == part), None)  # fmt: skip
        assert node is not None, f"no {qualname}"
        body = node.body
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef), qualname
    return node


def _asks(tree: ast.AST) -> list[ast.Call]:
    """Every call of ``check`` or ``refused`` made through the module ``rc1_refusals`` (``rc1_refusals.check``)."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ASKS and isinstance(n.func.value, ast.Name)
            and n.func.value.id in ("rc1_refusals", "rr")]  # fmt: skip


def _name_of(call: ast.Call) -> str | None:
    arg = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "name"), None)
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def test_the_table_has_the_six_refusals_of_the_ruling_and_one_answer_for_the_environments() -> None:
    assert [r.name for r in rr.REFUSALS] == ["live_patient_lists", "edc_writes_from_screening",
                                             "patient_mail_and_downloads", "support_exports", "unattended_updates",
                                             "key_ceremonies"]  # fmt: skip
    assert len({r.key for r in rr.REFUSALS}) == len(rr.REFUSALS) and len({r.test for r in rr.REFUSALS}) == 6
    assert sorted(rr.ALLOWED) == ["DEV", "TEST", "VALIDATION"]  # D-1072
    for r in rr.REFUSALS:  # SAFE-1 A2: three rows are allowed in every known environment, the other three keep D-1072
        if r.name in A2_ALLOWED_EVERYWHERE:
            assert r.allowed == rr.KNOWN_ENVIRONMENTS, r.name
        else:
            assert r.allowed is rr.ALLOWED and "PRODUCTION" not in r.allowed, r.name
        assert r.allowed <= rr.KNOWN_ENVIRONMENTS and r.sites and r.what, r.name
        assert r.audit.strip(), f"{r.name}: say which audit event records the refusal, or none and why"
        events = ("console.denied", "mail.failed", "console.ops", "screen.reveal_refused", "registry.export_refused")
        assert r.audit.startswith("none (") or any(e in r.audit for e in events), r.audit


def test_the_rule_and_the_environments_are_the_boxs_own() -> None:
    """The table's copy of the one rule (kept here for the host's python3) answers as ``environment_name`` does."""
    from tb_common.config import environment_name
    from tb_common.policy.classes import Environment

    assert {e.value for e in Environment} == rr.KNOWN_ENVIRONMENTS
    for env in ({}, {"TB_ENV": ""}, {"TB_ENV": " dev "}, {"TB_ENV": "Validation"}, {"TB_ENV": "PILOT"}):
        assert rr.environment(env) == environment_name(env), env
    assert rr.label({"TB_ENV": "validation"}) == {"rc1": "validation"}
    assert rr.label({"TB_ENV": "DEV"}) == rr.label({"TB_ENV": "TEST"}) == rr.label({"TB_ENV": "PILOT"}) == {}


#: SAFE-1 A2 (the owner's decision of 2026-11-28): allowed on PRODUCTION, and everywhere a box's name is known
A2_ALLOWED_EVERYWHERE = ("live_patient_lists", "support_exports", "key_ceremonies")
#: and these stay refused on PRODUCTION (A2 keeps EDC writes and unattended updates; mail and downloads are not flipped)
A2_KEPT = ("edc_writes_from_screening", "unattended_updates", "patient_mail_and_downloads")


def test_a2_production_allows_lists_support_exports_and_key_ceremonies_with_the_validation_label() -> None:
    production = ({}, {"TB_ENV": ""}, {"TB_ENV": "PRODUCTION"}, {"TB_ENV": " production "})  # unset is PRODUCTION
    assert sorted(A2_ALLOWED_EVERYWHERE + A2_KEPT) == sorted(r.name for r in rr.REFUSALS)
    for name in A2_ALLOWED_EVERYWHERE:
        for env in (*production, {"TB_ENV": "VALIDATION"}, {"TB_ENV": "DEV"}, {"TB_ENV": "TEST"}):
            assert rr.refused(name, env) is False, (name, env)
            rr.check(name, env)  # no raise
        with pytest.raises(rr.Rc1Refused):  # an unknown name is still allowed nowhere
            rr.check(name, {"TB_ENV": "PILOT"})
    for name in A2_KEPT:
        for env in production:
            assert rr.refused(name, env) is True, (name, env)
            with pytest.raises(rr.Rc1Refused):
                rr.check(name, env)
    for env in production:  # an allowed act carries on PRODUCTION the label it carries on VALIDATION
        assert rr.label(env) == rr.label({"TB_ENV": "VALIDATION"}) == {"rc1": "validation"}, env


@pytest.mark.parametrize(
    ("box", "caller", "asked"),
    [("PRODUCTION", "PILOT", "PILOT"), ("PILOT", "PRODUCTION", "PILOT"), ("PRODUCTION", "DEV", "PRODUCTION"),
     ("DEV", "PRODUCTION", "PRODUCTION"), ("", "DEV", "PRODUCTION"), ("DEV", "TEST", "DEV")],
)  # fmt: skip
def test_a_host_tool_asks_with_the_stricter_name_and_an_unknown_one_is_stricter_than_production(
    box: str, caller: str, asked: str
) -> None:
    """SAFE-1 A2: PRODUCTION allows three rows and an unknown name none, so the unknown name is the stricter."""
    assert rr.host_env({"TB_ENV": box}, {"TB_ENV": caller}) == {"TB_ENV": asked}


def test_every_site_asks_the_table_with_its_rows_name() -> None:
    for r in rr.REFUSALS:
        for site in r.sites:
            module, _, qualname = site.partition(":")
            fn = _function(ast.parse(_module_file(module).read_text(encoding="utf-8")), qualname)
            assert r.name in [_name_of(c) for c in _asks(fn)], f"{site} does not ask rc1_refusals about {r.name}"


def _enclosing(tree: ast.Module) -> dict[int, str]:
    """``id(call)`` -> the qualified name of the function the call is in ("" at module level)."""
    out: dict[int, str] = {}

    def walk(node: ast.AST, names: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                walk(child, [*names, child.name])
            else:
                if isinstance(child, ast.Call):
                    out[id(child)] = ".".join(names)
                walk(child, names)

    walk(tree, [])
    return out


def test_nothing_imports_the_question_by_its_name() -> None:
    """A call ``check(...)`` imported by name would hide from the walk below: only ``rc1_refusals.check`` is asked."""
    bad = []
    for top in ("libs", "services", "tools", "tests"):
        for f in sorted((ROOT / top).rglob("*.py")):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("rc1_refusals"):
                    bad += [f"{f.relative_to(ROOT)}:{n.lineno} {a.name}" for a in n.names if a.name in ASKS]
                if isinstance(n, ast.Import | ast.ImportFrom):
                    for a in n.names:
                        if a.name.endswith("rc1_refusals") and a.asname not in (None, "rr"):
                            bad.append(f"{f.relative_to(ROOT)}:{n.lineno} as {a.asname}")
    assert bad == [], bad


def test_every_question_asked_anywhere_names_a_row() -> None:
    names = {r.name for r in rr.REFUSALS}
    sites = {s for r in rr.REFUSALS for s in r.sites}
    asked: dict[str, set[str]] = {}
    for top in ("libs", "services", "tools"):
        for f in sorted((ROOT / top).rglob("*.py")):
            if f.resolve() == Path(rr.__file__).resolve():
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            where = _enclosing(tree)
            for call in _asks(tree):
                name = _name_of(call)
                assert name is not None, f"{f.relative_to(ROOT)}:{call.lineno} asks rc1_refusals with no literal name"
                assert name in names, f"{f.relative_to(ROOT)}:{call.lineno} asks about {name!r}, not a row"
                asked.setdefault(name, set()).add(str(f.relative_to(ROOT)))
                module = _module_of(f)
                site = f"{module}:{where[id(call)]}"
                assert site in rr.row(name).sites, f"{site} asks about {name} and is not one of its row's sites"
    assert set(asked) == names  # every row is asked somewhere
    files = {str(_module_file(s.partition(":")[0]).relative_to(ROOT)) for s in sites}
    assert set().union(*asked.values()) == files  # and only at the table's sites' modules


def test_every_rows_test_exists_and_is_collected() -> None:
    tests = sorted({r.test for r in rr.REFUSALS})
    for t in tests:
        path, _, name = t.partition("::")
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), t
        # collected by pytest's default rules (test_*.py, test_* at module level), read from the tree so the
        # check does not depend on what an earlier test in the same run did to the process
        p = ROOT / path
        assert p.parts[len(ROOT.parts)] == "tests" and p.name.startswith("test_") and p.suffix == ".py", t
        assert name.startswith("test_"), t


def test_every_message_is_in_three_languages_with_the_environment() -> None:
    from console import i18n_rc1

    cats = {"en": i18n_rc1.EN, "ja": i18n_rc1.JA, "zh-TW": i18n_rc1.ZH}
    assert set(rr.TEXTS) == {r.key for r in rr.REFUSALS}
    for r in rr.REFUSALS:
        assert set(rr.TEXTS[r.key]) == set(rr.LANGS), r.key
        for lang in rr.LANGS:
            t = rr.TEXTS[r.key][lang]
            assert "{environment}" in t and t == cats[lang][r.key], (r.key, lang)
            assert lang == "en" or not t.isascii(), (r.key, lang)
            assert rr.text(r.key, lang, environment="PRODUCTION").count("PRODUCTION") == 1


@pytest.mark.parametrize(("env", "refused"), [({}, True), ({"TB_ENV": ""}, True), ({"TB_ENV": "PRODUCTION"}, True),
                                              ({"TB_ENV": "VALIDATION"}, False), ({"TB_ENV": "PILOT"}, True),
                                              ({"TB_ENV": "dev"}, False), ({"TB_ENV": " TEST "}, False)])  # fmt: skip
def test_the_one_rule_decides_and_an_unknown_name_fails_closed(env: dict[str, str], refused: bool) -> None:
    for r in rr.REFUSALS:  # SAFE-1 A2: three rows are allowed wherever the name is known, PRODUCTION too
        is_refused = refused and not (r.name in A2_ALLOWED_EVERYWHERE and rr.environment(env) in rr.KNOWN_ENVIRONMENTS)
        assert rr.refused(r.name, env) is is_refused, r.name
        if is_refused:
            with pytest.raises(rr.Rc1Refused) as got:
                rr.check(r.name, env)
            assert got.value.refusal is r and got.value.environment == rr.environment(env)
            assert isinstance(got.value, PermissionError)
        else:
            rr.check(r.name, env)
    with pytest.raises(KeyError):
        rr.refused("a_seventh_refusal", {"TB_ENV": "DEV"})
    with pytest.raises(KeyError):
        rr.check("a_seventh_refusal", {"TB_ENV": "DEV"})


def test_a_host_tool_asks_with_the_stricter_of_the_box_and_its_caller(tmp_path: Path) -> None:
    """The review of R22-34: allowed only when the box's environment (its deploy/.env, when there) and the caller's
    TB_ENV (when set) are both allowed."""
    (tmp_path / ".env").write_text("# TB_ENV=PRODUCTION\nTB_ENV='DEV'\n", encoding="utf-8")
    assert rr.host_env(tmp_path, {}) == {"TB_ENV": "DEV"}
    assert rr.host_env(tmp_path, {"TB_ENV": "PRODUCTION"}) == {"TB_ENV": "PRODUCTION"}
    assert rr.host_env(tmp_path, {"TB_ENV": "validation"}) == {"TB_ENV": "DEV"}
    (tmp_path / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    assert rr.host_env(tmp_path, {"TB_ENV": "DEV"}) == {"TB_ENV": "PRODUCTION"}  # TB_ENV=DEV trialbox ... refused
    (tmp_path / ".env").write_text("TB_TZ=Asia/Taipei\n", encoding="utf-8")
    assert rr.host_env(tmp_path, {"TB_ENV": "DEV"}) == {"TB_ENV": "PRODUCTION"}  # a box that writes none is PRODUCTION
    assert rr.host_env({"TB_ENV": "TEST"}, {}) == {"TB_ENV": "TEST"}
    assert rr.host_env({}, {"TB_ENV": "TEST"}) == {"TB_ENV": "PRODUCTION"}
    assert rr.host_env({"TB_ENV": "TEST"}, {"TB_ENV": "PILOT"}) == {"TB_ENV": "PILOT"}
    assert rr.host_env(tmp_path / "none", {"TB_ENV": "TEST"}) == {"TB_ENV": "TEST"}  # no box file: the caller's
    assert rr.host_env(tmp_path / "none", {}) == {} and rr.refused("unattended_updates", {})  # A2 keeps this row


def test_a_box_file_that_cannot_be_read_is_production_whatever_the_caller_says(tmp_path: Path) -> None:
    """M15: a ``.env`` that is a folder, a dangling link or not text never falls back to the caller's DEV."""
    folder, link, binary = tmp_path / "folder", tmp_path / "link", tmp_path / "binary"
    (folder / ".env").mkdir(parents=True)
    link.mkdir()
    (link / ".env").symlink_to(tmp_path / "gone")
    binary.mkdir()
    (binary / ".env").write_bytes(b"TB_ENV=DEV\n\xff\xfe")
    for box in (folder, link, binary):
        assert rr.host_env(box, {"TB_ENV": "DEV"}) == {"TB_ENV": "PRODUCTION"}, box.name
        assert rr.refused("unattended_updates", rr.host_env(box, {"TB_ENV": "DEV"}))  # A2 keeps this row
