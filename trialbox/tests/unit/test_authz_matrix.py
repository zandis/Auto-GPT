"""T-102a (D-366): one permission function ``tb_common.authz.permit`` over the matrix ``authz_matrix.yaml``.

The matrix is total and checked at load; a role or an action not in it is refused; every older helper and every
``console.auth.User`` property gives the same answer as before T-102a (the reference rules below are copied from master
before the change, D-280 and T-512 included, with T-102b's one meant change: D-380 closes the delegation bootstrap, so
an investigator has no study task while the log names no PI); the three deprecated wrappers get no new caller."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from tb_common import authz
from tb_common.authz import (
    EDC_ACTIONS,
    MATRIX,
    MATRIX_ROLES,
    STUDY_TASKS,
    Decision,
    MatrixError,
    Standing,
    load_matrix,
    permit,
)

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
ROLES = ("admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy")
ODD_ROLES = ("", "ADMIN", "root", "breakglass", "monitor")


# ---------------------------------------------------------------------------------------------- the rules before T-102a
# Copied from libs/tb_common/authz.py and services/console/auth.py on master before T-102a (after D-280 and T-512).
_PREPARE = {
    "FEAS",
    "SCREEN",
    "COHORT",
    "NAV",
    "MICROBATCH",
    "STATUS",
    "CANCEL",
    "CONSENT",
    "RELEASE",
    "CASE",
    "FEEDBACK",
}
_RUNS = {"pi": {"FEAS", "SCREEN", "CASE"}, "run": {"FEAS", "SCREEN", "CASE"}}
_INV = {"APPROVE", "STATUS"}
_ROLE_COMMANDS = {"admin": _PREPARE, "coordinator": _PREPARE, "investigator": _INV | _RUNS["pi"] | _RUNS["run"]}
# D-380 (ROLE-008): the investigator's "unlogged" row (screen, approach, refer) is gone; nobody acts as PI unnamed
_ROLE_TASKS = {"coordinator": {"screen", "enter_data"}}


def old_can_request(role: str, cmd: str, is_pi: bool, tasks: frozenset[str]) -> bool:
    if role != "investigator":
        return cmd in _ROLE_COMMANDS.get(role, set())
    if cmd in _INV:
        return True
    if is_pi:
        return cmd in _RUNS["pi"]
    return "run" in tasks and cmd in _RUNS["run"]


def old_study_tasks(role: str, log_names_pi: bool, is_pi: bool, ticked: frozenset[str]) -> frozenset[str]:
    if role != "investigator" or not log_names_pi:
        return frozenset(_ROLE_TASKS.get(role, set()))
    return frozenset(STUDY_TASKS) if is_pi else ticked & frozenset(STUDY_TASKS)


def old_edc_allowed(role: str, action: str, tasks: frozenset[str], is_pi: bool) -> bool:
    if action not in EDC_ACTIONS or role in ("viewer", "cro"):
        return False
    if role in ("admin", "steward", "privacy") and action != "switch_off":  # D-380: never a study task (D-280)
        return False
    if action == "switch_on":
        return role == "investigator" and is_pi
    if action == "switch_off":
        return (role == "investigator" and is_pi) or role == "admin"
    if action == "view":
        return "enter_data" in tasks or (role == "investigator" and is_pi)
    return "enter_data" in tasks


OLD_USER: dict[str, Callable[[str], bool]] = {
    "can_request": lambda r: r in ("admin", "coordinator"),
    "can_view_phi": lambda r: r in ("coordinator", "investigator"),
    "can_reveal": lambda r: r in ("coordinator", "investigator"),
    "can_mark": lambda r: r == "investigator",
    "can_approve": lambda r: r == "investigator",
    "aggregate_only": lambda r: r in ("viewer", "cro"),
}


def _task_sets() -> list[frozenset[str]]:
    pool = (*STUDY_TASKS, "x")
    return [frozenset(c) for n in range(len(pool) + 1) for c in itertools.combinations(pool, n)]


# ---------------------------------------------------------------------------------------------- the matrix as data
def test_the_matrix_roles_are_the_console_roles() -> None:
    from console.auth import ROLES as CONSOLE_ROLES

    assert tuple(MATRIX_ROLES) == tuple(CONSOLE_ROLES) == ROLES


def test_the_matrix_is_total() -> None:
    assert MATRIX
    for action, row in MATRIX.items():
        assert set(row) == set(MATRIX_ROLES), action
        for role, cell in row.items():
            assert cell is True or cell is False or (isinstance(cell, tuple) and cell), (action, role)


def test_every_helper_action_is_a_matrix_row() -> None:
    for a in EDC_ACTIONS:
        assert f"edc.{a}" in MATRIX
    for a in authz.SAE_ACTIONS:
        assert f"sae.{a}" in MATRIX
    for a in authz.ADMIN_ACTIONS:
        assert a in MATRIX
    for t in STUDY_TASKS:
        assert f"task.{t}" in MATRIX
    assert set(authz.COMMANDS) == _PREPARE | _INV


@pytest.mark.parametrize(
    ("text", "msg"),
    [
        ("roles: [a, b]\nactions:\n  x.y: {what: w, a: true}\n", "total"),
        ("roles: [a]\nactions:\n  x.y: {what: w, a: [someone]}\n", "unknown condition"),
        ("roles: [a]\nactions:\n  x.y: {what: w, a: [logged_tick]}\n", "unknown condition"),
        ("roles: [a]\nactions:\n  x.y: {what: w, a: []}\n", "list of conditions"),
        ("roles: [a]\nactions:\n  x.y: {a: true}\n", "says what"),
        ("roles: [a, a]\nactions: {}\n", "without repeats"),
    ],
)
def test_a_broken_matrix_does_not_load(tmp_path: Path, text: str, msg: str) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(text)
    with pytest.raises(MatrixError, match=msg):
        load_matrix(p)


# ---------------------------------------------------------------------------------------------- permit
def test_a_role_or_an_action_not_in_the_matrix_is_refused() -> None:
    best = authz.BEST_STANDING
    for role in ODD_ROLES:
        for action in MATRIX:
            d = permit(role, action, best)
            assert not d and d.basis == "unknown role", (role, action)
    for role in ROLES:
        d = permit(role, "phi.delete", best)
        assert not d and d.basis == "unknown action"


def test_permit_says_its_basis() -> None:
    assert permit("coordinator", "phi.view") == Decision(True, "coordinator", "phi.view", "role")
    assert permit("admin", "phi.view") == Decision(False, "admin", "phi.view", "role")
    d = permit("investigator", "command.SCREEN", Standing(tasks=frozenset({"run"})))
    assert d and d.basis == "task:run"
    d = permit("investigator", "command.SCREEN", Standing(is_pi=True))
    assert d and d.basis == "pi"
    d = permit("investigator", "command.SCREEN", Standing(tasks=frozenset({"screen"})))
    assert not d and d.basis == "standing"


def test_d280_the_administrator_has_no_patient_row() -> None:
    """D-280 (OD-5): no patient-level action for the administrator; break-glass is its own row."""
    patient = ("phi.view", "id.reveal", "list.mark", "sae.view", "sae.record", *(f"task.{t}" for t in STUDY_TASKS))
    for action in patient:
        assert not permit("admin", action, authz.BEST_STANDING), action
    assert permit("admin", "breakglass.open") and not permit("admin", "breakglass.review")
    assert permit("steward", "breakglass.review") and not permit("steward", "breakglass.open")
    assert permit("investigator", "breakglass.study", Standing(is_pi=True))  # T-309: a study's grants, its PI
    assert not permit("investigator", "breakglass.study", Standing(tasks=frozenset(STUDY_TASKS)))
    # T-309 (D-430): one rule for the administrator and an investigator outside its own rights; never the steward
    assert permit("investigator", "breakglass.open") and permit("investigator", "breakglass.read")
    assert not any(permit("steward", f"task.{t}", authz.BEST_STANDING) for t in STUDY_TASKS)


# ---------------------------------------------------------------------------------------------- same answers as before
def test_can_request_and_role_allowed_are_unchanged() -> None:
    cmds = (*sorted(_PREPARE | _INV), "BOGUS", "approve", "feas")
    for role, cmd, is_pi, tasks in itertools.product(ROLES, cmds, (False, True), _task_sets()):
        want = old_can_request(role, cmd.upper(), is_pi, tasks)
        assert authz.can_request(role, cmd, is_pi=is_pi, tasks=tasks) == want, (role, cmd, is_pi, tasks)
    for role, cmd in itertools.product((*ROLES, *ODD_ROLES), cmds):
        assert authz.role_allowed(role, cmd) == (cmd.upper() in _ROLE_COMMANDS.get(role, set())), (role, cmd)
    assert {r: set(v) for r, v in authz.ROLE_COMMANDS.items()} == _ROLE_COMMANDS
    assert {k: set(v) for k, v in authz.INVESTIGATOR_RUNS.items()} == _RUNS


def test_study_tasks_are_unchanged() -> None:
    for role, logged, is_pi, ticked in itertools.product(ROLES, (False, True), (False, True), _task_sets()):
        want = old_study_tasks(role, logged, is_pi, ticked)
        assert authz.study_tasks(role, log_names_pi=logged, is_pi=is_pi, ticked=ticked) == want
    assert {r: set(v) for r, v in authz.ROLE_STUDY_TASKS.items()} == _ROLE_TASKS


def test_edc_rules_are_unchanged() -> None:
    for role, action, is_pi, tasks in itertools.product(ROLES, (*EDC_ACTIONS, "bogus"), (False, True), _task_sets()):
        want = old_edc_allowed(role, action, tasks, is_pi)
        assert authz.edc_allowed(role, action, tasks=tasks, is_pi=is_pi) == want, (role, action, is_pi, tasks)
    for role, action in itertools.product(ROLES, EDC_ACTIONS):
        inv = role == "investigator"
        want = old_edc_allowed(role, action, old_study_tasks(role, False, inv, frozenset()), inv)
        assert authz.edc_role_may(role, action) == want, (role, action)


def test_sae_and_operations_rules_are_unchanged() -> None:
    sae = {"coordinator": {"view", "record"}, "investigator": {"view"}}
    for role, action in itertools.product((*ROLES, *ODD_ROLES), (*authz.SAE_ACTIONS, "delete")):
        assert authz.sae_allowed(role, action) == (action in sae.get(role, set())), (role, action)
    for role, action in itertools.product((*ROLES, *ODD_ROLES), (*authz.ADMIN_ACTIONS, "ops.root")):
        assert authz.admin_allowed(role, action) == (role == "admin" and action in authz.ADMIN_ACTIONS)
    assert {r: set(v) for r, v in authz.ROLE_SAE_ACTIONS.items()} == sae
    assert {"admin": frozenset(authz.ADMIN_ACTIONS)} == authz.ROLE_ADMIN_ACTIONS


def test_the_console_role_properties_are_unchanged_wrappers() -> None:
    from console.auth import User

    for role in ROLES:
        u = User(role, role, None)  # type: ignore[arg-type]
        for prop, old in OLD_USER.items():
            assert getattr(u, prop) == old(role), (role, prop)


# ---------------------------------------------------------------------------------------------- the deprecated three
# T-102a: ``study_tasks``, ``edc_allowed`` and ``edc_role_may`` stay as thin wrappers for their present callers only
# (T-102c moves those to ``permit``). A new caller fails here; call ``permit`` instead.
WRAPPER_CALLERS = {
    "study_tasks": set(),
    "edc_allowed": set(),
    "edc_role_may": {"services/orchestrator/edc_api.py"},
}


def test_no_new_caller_of_the_deprecated_wrappers() -> None:
    found: dict[str, set[str]] = {k: set() for k in WRAPPER_CALLERS}
    for base in ("services", "libs", "tools"):
        for path in (ROOT / base).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "libs/tb_common/authz.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in WRAPPER_CALLERS:
                if re.search(rf"\b{name}\(", text):
                    found[name].add(rel)
    for name, allowed in WRAPPER_CALLERS.items():
        assert found[name] <= allowed, f"new caller of the deprecated authz.{name}: {sorted(found[name] - allowed)}"


# ---------------------------------------------------------------------------------------------- T-102b (D-380)
def test_d380_registers_are_kept_by_the_steward_and_the_privacy_office_only() -> None:
    for action in ("optout.keep", "staff.keep"):
        assert {r for r in ROLES if permit(r, action, authz.BEST_STANDING)} == {"steward", "privacy"}, action


def test_d380_no_pi_named_means_nobody_acts_as_pi() -> None:
    unlogged = Standing(is_pi=False, tasks=frozenset(), log_names_pi=False)
    for t in STUDY_TASKS:
        assert not permit("investigator", f"task.{t}", unlogged), t
    assert not permit("investigator", "delegation.keep", unlogged)
    assert permit("investigator", "delegation.keep", Standing(is_pi=True, log_names_pi=True))
    assert {r for r in ROLES if permit(r, "delegation.name_pi")} == {"steward"}


def test_d380_irb_dates_and_the_monitor_grant() -> None:
    assert {r for r in ROLES if permit(r, "irb.edit", authz.BEST_STANDING)} == {"coordinator", "investigator"}
    assert not permit("investigator", "irb.edit", Standing(is_pi=False, log_names_pi=True))
    assert {r for r in ROLES if permit(r, "monitor.read", Standing(monitor=True))} == {"cro"}
    assert not permit("cro", "monitor.read", Standing(monitor=False))
    assert authz.monitor_may_see({"state": "enrolled"}) and authz.monitor_may_see({"state": "on_study"})
    for state in ("candidate", "approached", "consented", "screen_fail", "withdrawn", ""):
        assert not authz.monitor_may_see({"state": state}), state
    assert authz.monitor_may_see({"state": "withdrawn", "enrolment": "2026-05-01"})
    # D-436: the data core's subject list gives the enrolment step's day as ``enrolled``; the whole reply of
    # ``GET /studies/{rs}/subjects/{record}`` (the subject nested under "subject") is never read as a subject
    assert authz.monitor_may_see({"state": "withdrawn", "enrolled": "2026-05-01"})
    assert not authz.monitor_may_see({"state": "withdrawn", "enrolled": ""})
    assert not authz.monitor_may_see({"study": "GZQO", "subject": {"state": "enrolled"}})
    assert {r for r in ROLES if permit(r, "monitor.visit", Standing(monitor=True))} == {"cro"}
    assert not permit("cro", "monitor.visit", Standing(monitor=False))


def test_d380_the_administrator_reads_no_patient_row_at_all() -> None:
    patient = [a for a in MATRIX if a.split(".")[0] in ("phi", "id", "list", "task", "sae", "optout", "monitor")]
    patient += ["audit.ids", "irb.edit"]
    for action in patient:
        assert not permit("admin", action, authz.BEST_STANDING), action


def test_d380_role_rights_are_the_matrix_rows() -> None:
    best = Standing(is_pi=True, tasks=frozenset(STUDY_TASKS), log_names_pi=True, monitor=True)
    for role in ROLES:
        rights = authz.role_rights(role)
        assert {a for a, _, _ in rights} == {a for a in MATRIX if permit(role, a, best)}, role
        for action, what, conditional in rights:
            assert what, (role, action)
            assert conditional == isinstance(MATRIX[action][role], tuple)
    assert authz.role_rights("root") == []
