"""T-102c (D-425): every console call site asks ``permit``; no page names a role in a comparison.

The grep test reads every console module and fails on a comparison of an account's role with a role name
(``user.role == "cro"``, ``role in ("admin", "viewer")``). A delegation-log entry's role (``pi``, ``sub_pi``,
``monitor``) is not an account role and is not counted. The team fallback (``h.may is None``: every investigator
passes while no log store is wired) is gone. The rows added for the moved call sites give the answers the inline
checks gave (the reference sets below are copied from master before the change)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from tb_common import authz
from tb_common.authz import BEST_STANDING, MATRIX_ROLES, NO_STANDING, Standing, conditional, permit, study_bound

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"
ROLES = frozenset(MATRIX_ROLES)


def _names_role(node: ast.expr) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "role") or (
        isinstance(node, ast.Name) and node.id == "role"
    )


def _role_names(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in ROLES
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return any(isinstance(e, ast.Constant) and e.value in ROLES for e in node.elts)
    return False


def inline_checks(source: str) -> list[int]:
    """Lines where a role is compared with an account role's name."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if any(_names_role(s) for s in sides) and any(_role_names(s) for s in sides):
                out.append(node.lineno)
    return out


def test_the_grep_test_finds_an_inline_check() -> None:
    assert inline_checks('if sess.user.role == "cro": pass') == [1]
    assert inline_checks('ok = role in ("admin", "viewer")') == [1]
    assert inline_checks('x = u.role != "steward"') == [1]
    assert inline_checks('pi = e.role == "pi" or e.role == "monitor"') == []  # log entries, not accounts
    assert inline_checks('ok = permit(user.role, "report.office").allowed') == []


def test_no_inline_role_check_is_left_in_the_console() -> None:
    found = []
    for path in sorted(CONSOLE.glob("*.py")):
        found += [f"{path.name}:{n}" for n in inline_checks(path.read_text(encoding="utf-8"))]
    assert not found, "ask tb_common.authz.permit (or h.permit), not the role name: " + ", ".join(found)


def test_the_team_fallback_is_gone() -> None:
    for path in sorted(CONSOLE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "may is None" not in text and "may is not None" not in text, path.name
        assert 'getattr(h, "may"' not in text, path.name


# ---------------------------------------------------------------------------------------------- the rows that replaced them
def _who(action: str, standing: Standing = NO_STANDING) -> set[str]:
    return {r for r in MATRIX_ROLES if permit(r, action, standing)}


def test_the_new_rows_give_the_old_answers() -> None:
    assert _who("report.sponsor_form") == {"cro"}  # was role == "cro"
    assert _who("report.office") == {"admin", "viewer", "coordinator"}  # was role in (admin, viewer, coordinator)
    assert _who("site.setup") == {"coordinator", "admin"}  # was role in (coordinator, admin)
    assert _who("study.setup") == {"coordinator"}  # was role == "coordinator"
    assert _who("sae.ack") == {"investigator"}  # was role == "investigator"
    assert _who("ops.view") == {"admin"}  # is_admin, an operator account without an end date
    # was: coordinator, or an investigator with "refer" in the log's tasks
    assert _who("referral.answer") == {"coordinator"}
    assert _who("referral.answer", Standing(tasks=frozenset({"refer"}))) == {"coordinator", "investigator"}
    # was: coordinator, or the investigator the log names as PI
    assert _who("delegation.check") == {"coordinator"}
    assert _who("delegation.check", BEST_STANDING) == {"coordinator", "investigator"}


def test_conditional_and_study_bound_read_the_matrix() -> None:
    assert {r for r in MATRIX_ROLES if conditional(r, "task.screen")} == {"investigator"}
    assert {r for r in MATRIX_ROLES if conditional(r, "monitor.read")} == {"cro"}
    assert {r for r in MATRIX_ROLES if study_bound(r, "command.")} == {"investigator"}
    assert not conditional("root", "task.screen") and not conditional("investigator", "no.such")


def test_the_log_accounts_are_the_old_roles() -> None:
    from console.auth import User, is_operator
    from console.team import log_account, monitor_account, on_log

    users = {r: User(r, r, None) for r in MATRIX_ROLES}  # type: ignore[arg-type]
    assert {r for r, u in users.items() if log_account(u)} == {"investigator"}
    assert {r for r, u in users.items() if monitor_account(u)} == {"cro"}
    assert {r for r, u in users.items() if on_log(u)} == {"investigator", "coordinator", "cro"}
    assert {r for r, u in users.items() if u.sponsor_form} == {"cro"}
    assert {r for r in MATRIX_ROLES if is_operator(r)} == {"admin"}


def test_home_and_the_command_bar_send_each_role_where_they_did() -> None:
    from console.home import HOME_STARTS

    def start(role: str) -> str | None:
        return next((s for a, s in HOME_STARTS if permit(role, a)), None)

    old = {"investigator": "/week", "cro": "/reports", "viewer": "/reports", "steward": "/breakglass",
           "privacy": "/site/opt-outs", "admin": None, "coordinator": None}  # fmt: skip
    assert {r: start(r) for r in MATRIX_ROLES} == old


def test_every_new_row_has_its_label_in_three_languages() -> None:
    from console import i18n_roles

    for action in ("report.sponsor_form", "report.office", "study.setup", "site.setup", "referral.answer",
                   "delegation.check", "sae.ack"):  # fmt: skip
        key = i18n_roles.right_key(action)
        assert all(key in cat for cat in (i18n_roles.EN, i18n_roles.JA, i18n_roles.ZH)), action
    assert authz.MATRIX_WHAT["report.office"]
