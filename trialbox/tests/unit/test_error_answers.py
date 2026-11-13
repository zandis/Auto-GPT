"""NEW-TRUST-3 (D-555): an error answer built from an exception's own text carries no value of the request.

Three rules, held by reading the code (so a new route cannot slip past) and by a few calls:

* the orchestrator puts an exception's text into an answer only for the error classes listed here, whose texts are
  written in this repository;
* every text of those classes is a fixed sentence, or names only the values listed here (a status, a role, a job
  type, a limit: the box's own words, never what the caller typed);
* the console never shows a service's own error text: a page that could not reach a service says which service
  and with what status, nothing else.

Synthetic data only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "services"

#: error classes whose text may go into an answer, with where they are raised and what a text may name
OWN_TEXT: dict[str, tuple[str, frozenset[str]]] = {
    "ActorError": ("../libs/tb_common/service_auth.py", frozenset()),
    "RegistryError": ("orchestrator/candidates.py", frozenset({"prev['status']", "upd.status"})),
    "Rejected": ("orchestrator/core.py", frozenset({"role", "jtype", "limit", "role or 'unnamed'"})),
    "NotRetryable": ("orchestrator/core.py", frozenset({"failed.type", "busy[0]"})),
}


def _is_text_of_exc(node: ast.AST) -> bool:
    """``str(exc)``, ``f"...{exc}..."`` or ``exc.args``: the caught error's own text."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("str", "repr"):
            if n.args and isinstance(n.args[0], ast.Name) and n.args[0].id in ("exc", "e", "err"):
                return True
        if isinstance(n, ast.FormattedValue) and isinstance(n.value, ast.Name) and n.value.id in ("exc", "e", "err"):
            return True
    return False


def _caught(handler: ast.ExceptHandler) -> list[str]:
    t = handler.type
    items = t.elts if isinstance(t, ast.Tuple) else [t]
    return [ast.unparse(i).split(".")[-1] for i in items if i is not None]


def _answers_with_exc_text(folder: str, raisers: tuple[str, ...]) -> list[tuple[str, int, list[str]]]:
    """Every ``raise <raiser>(... the caught error's text ...)`` under ``folder``: file, line, the classes caught."""
    found = []
    for f in sorted((ROOT / folder).glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
            for n in ast.walk(handler):
                if not (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)):
                    continue
                name = ast.unparse(n.exc.func)
                if name.split(".")[-1] in raisers and _is_text_of_exc(n.exc):
                    found.append((f.name, n.lineno, _caught(handler)))
    return found


def test_the_orchestrator_answers_with_an_errors_text_only_for_the_listed_classes() -> None:
    found = _answers_with_exc_text("orchestrator", ("HTTPException",))
    assert len(found) >= 8, found  # the registry's, the job routes', the two signed-person checks
    bad = [(f, line, classes) for f, line, classes in found if not set(classes) <= set(OWN_TEXT)]
    assert bad == [], f"an answer repeats the text of an error not written here: {bad}"


@pytest.mark.parametrize("cls", sorted(OWN_TEXT))
def test_every_text_of_a_listed_class_names_only_the_boxs_own_words(cls: str) -> None:
    rel, may_name = OWN_TEXT[cls]
    tree = ast.parse((ROOT / rel).resolve().read_text(encoding="utf-8"))
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
              and ast.unparse(n.exc.func) == cls]  # fmt: skip
    assert raises, cls
    for r in raises:
        assert isinstance(r.exc, ast.Call)
        for arg in r.exc.args:
            assert isinstance(arg, ast.Constant | ast.JoinedStr), (cls, r.lineno, ast.unparse(arg))
            named = {ast.unparse(v.value) for v in ast.walk(arg) if isinstance(v, ast.FormattedValue)}
            assert named <= may_name, f"{rel}:{r.lineno}: the text names {sorted(named - may_name)}"


def test_the_console_never_shows_a_services_own_error_text() -> None:
    found = _answers_with_exc_text("console", ("problem", "HTTPException"))
    assert len(found) >= 10, found  # the console's own error classes (a refused form, a team rule): its own words
    service = {"Unavailable", "Problem", "ServiceError"}  # what another service said, as text
    bad = [x for x in found if service & set(x[2])]
    assert bad == [], f"a page repeats a service's error text: {bad}"


def test_a_ruleset_id_that_is_not_one_is_not_repeated() -> None:
    from orchestrator.candidates import RegistryError, check_ruleset

    with pytest.raises(RegistryError) as e:
        check_ruleset("A1234567 x")
    assert "A1234567" not in str(e.value)


def test_what_the_console_says_of_a_service_that_failed() -> None:
    from console.backend import Unavailable, service_and_status

    # the text of a failed call is "<service> returned <status>: <what the service said>"
    exc = Unavailable('orchestrator returned 500: {"detail":"no row for chart A1234567"}')
    assert service_and_status(exc) == "orchestrator (500)"
    assert service_and_status(Unavailable("connection refused to http://10.0.0.5:8000/studies/GZQO")) == "-"
