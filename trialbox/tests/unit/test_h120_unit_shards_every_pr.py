"""H-120 (D-1357): the unit shards run on every pull request. The policy fails when any pull request can skip them.

The owner's rule (integrator 7125828711, item 1): whatever a pull request touches, its draft state, its labels or the
tier it gets, the matrix `unit-shard` and its aggregate `unit` run. Before H-120 a card's pull request on no
full-tier path, a draft, a docs-only one and one with no change under trialbox/ skipped them, and four reds on trains
came from such pull requests.

Two halves, both read from the tree as it is:

* the real tier code: ``tools/ci_tier.py`` run as the `changes` job runs it (its standard input the changed paths,
  ``DOCS_ONLY`` from ``tools/ci_docs_only.py``, ``trialbox`` from the diff step's own pattern) over a table of path
  sets, draft states, labels and ``CARD_TIER`` values;
* the workflow itself: each unit job's ``if`` evaluated with those outputs (and with none, as when `changes` failed)
  by a small evaluator of GitHub's expression syntax, plus every other way a job can be left out: the triggers' filters,
  ``needs`` on a job that can be skipped, the matrix, a step's own ``if``, ``continue-on-error``.

A condition this file cannot evaluate (an unknown function or context) fails it: a new skip cannot hide in syntax.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import ci_docs_only, ci_tier

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"
UNIT_JOBS = ("unit-shard", "unit")
#: the one context a unit job's condition may read: the tier code's answer. A draft flag, a label, a branch name or
#: `full` read in the workflow itself would be a rule beside the tier code's, and the table below could miss it.
EXPLAINED = {"needs.changes.outputs.unit"}

pytestmark = pytest.mark.nodb


# ---------------------------------------------------------------------------- a GitHub expression evaluator (subset)

_TOKEN = re.compile(
    r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>&&|\|\||==|!=|<=|>=|[!()<>,])|(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<name>[A-Za-z_][\w-]*(?:\.[A-Za-z_*][\w-]*)*))"
)


class Unknown(Exception):
    """A function or context the evaluator does not know: the policy refuses to guess."""


def _tokens(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise Unknown(f"cannot read {text[pos:]!r}")
        kind = m.lastgroup
        assert kind is not None
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def _truthy(v: Any) -> bool:
    return v not in (None, False, "", 0)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()  # GitHub compares strings ignoring case
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower() == str(b).lower()
    return bool(a == b)


#: the functions a condition may call, as GitHub defines them (ignoring case)
FUNCS: dict[str, Any] = {
    "startswith": lambda a, b: str(a).lower().startswith(str(b).lower()),
    "endswith": lambda a, b: str(a).lower().endswith(str(b).lower()),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
}


class _Parser:
    def __init__(self, text: str, ctx: dict[str, Any], status: dict[str, bool], allowed: set[str] | None) -> None:
        self.toks, self.i, self.ctx, self.status, self.allowed = _tokens(text), 0, ctx, status, allowed

    def peek(self) -> str | None:
        return self.toks[self.i][1] if self.i < len(self.toks) else None

    def take(self) -> tuple[str, str]:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def parse(self) -> Any:
        v = self.or_()
        if self.i != len(self.toks):
            raise Unknown(f"trailing {self.toks[self.i :]}")
        return v

    def or_(self) -> Any:
        v = self.and_()
        while self.peek() == "||":
            self.take()
            r = self.and_()
            v = v if _truthy(v) else r
        return v

    def and_(self) -> Any:
        v = self.cmp()
        while self.peek() == "&&":
            self.take()
            r = self.cmp()
            v = r if _truthy(v) else v
        return v

    def cmp(self) -> Any:
        v = self.unary()
        while self.peek() in ("==", "!="):
            op = self.take()[1]
            r = self.unary()
            v = _eq(v, r) if op == "==" else not _eq(v, r)
        if self.peek() in ("<", ">", "<=", ">="):
            raise Unknown("ordering comparison")
        return v

    def unary(self) -> Any:
        if self.peek() == "!":
            self.take()
            return not _truthy(self.unary())
        return self.atom()

    def atom(self) -> Any:
        kind, val = self.take()
        if val == "(":
            v = self.or_()
            assert self.take()[1] == ")"
            return v
        if kind == "str":
            return val[1:-1].replace("''", "'")
        if kind == "num":
            return float(val)
        if kind != "name":
            raise Unknown(f"unexpected {val!r}")
        if val in ("true", "false"):
            return val == "true"
        if val == "null":
            return None
        if self.peek() == "(":
            self.take()
            args = []
            while self.peek() != ")":
                args.append(self.or_())
                if self.peek() == ",":
                    self.take()
            self.take()
            name = val.lower()
            if name in self.status:
                assert not args
                return self.status[name]
            if name in FUNCS:
                return FUNCS[name](*args)
            raise Unknown(f"function {val}()")
        root = val.split(".", 1)[0]
        if root not in ("github", "needs", "env", "vars"):
            raise Unknown(f"context {val}")
        if root in ("env", "vars"):
            raise Unknown(f"{val}: a unit job may not depend on a variable set outside the tier code")
        if self.allowed is not None and val not in self.allowed:
            raise Unknown(f"{val}: a condition the tier code does not explain")
        return self.ctx.get(val, "")


def evaluate(cond: Any, ctx: dict[str, Any], *, deps_ok: bool, allowed: set[str] | None = None) -> bool:
    """A job's ``if`` as GitHub decides it: no ``if`` means ``success()``; a status function anywhere replaces the
    implied ``success()``. ``allowed``: the only contexts the condition may read."""
    text = "success()" if cond is None else str(cond).strip()
    if isinstance(cond, bool):
        return cond
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    status = {"success": deps_ok, "failure": not deps_ok, "always": True, "cancelled": False}
    value = _truthy(_Parser(text, ctx, status, allowed).parse())
    if not re.search(r"\b(success|failure|always|cancelled)\s*\(", text, re.IGNORECASE):
        value = value and deps_ok
    return value


# ---------------------------------------------------------------------------------------------- the workflow read


def _wf() -> dict[Any, Any]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _jobs() -> dict[str, Any]:
    jobs = _wf()["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _needs(job: dict[str, Any]) -> list[str]:
    n = job.get("needs", [])
    return [n] if isinstance(n, str) else list(n)


def _trialbox_pattern() -> str:
    run = next(s for s in _jobs()["changes"]["steps"] if s.get("id") == "diff")["run"]
    m = re.search(r"grep -qE '([^']+)'", run)
    assert m, "the diff step's pattern for `trialbox` moved: read it here again"
    return m.group(1)


# ---------------------------------------------------------------------------------------- the tier code, as CI runs


def _tier(env: dict[str, str], paths: list[str]) -> dict[str, str]:
    """``tools/ci_tier.py`` run as the `changes` job's tier step runs it: changed paths on standard input."""
    full_env = {**{k: v for k, v in os.environ.items() if k not in ("LABELS", "DRAFT", "DOCS_ONLY", "PROVED")}, **env}
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "ci_tier.py")], input="".join(f"{p}\n" for p in paths),
                         env=full_env, capture_output=True, text=True, check=True)  # fmt: skip
    return dict(ln.split("=", 1) for ln in res.stdout.split())


#: the path sets of a pull request (H-120's table): each one skipped the shards on a card before, or could have
PATHS: dict[str, list[str]] = {
    "a docs page": ["trialbox/docs/RUNBOOK.md"],
    "a document code reads": ["trialbox/docs/validation/model-change-protocol.md"],
    "a markdown file outside docs": ["README.md"],
    "a test file only": ["trialbox/tests/unit/test_site_tz.py"],
    "a shell script": ["trialbox/deploy/install.sh"],
    "a tool": ["trialbox/tools/make_bundle.sh"],
    "a service on no full-tier path": ["trialbox/services/lake/build.py"],
    "a full-tier path": ["trialbox/services/matching/engine.py"],
    "this workflow": [".github/workflows/trialbox-ci.yml"],
    "another workflow": [".github/workflows/trialbox-e2e.yml"],
    "a workflow of another project": [".github/workflows/ci.yml"],
    "a file outside trialbox/": ["classic/original_autogpt/README.txt"],
    "an empty diff": [],
}
#: what the tier step reads from the labels: none, an unrelated one, the full-tier label, and "could not read"
LABELS = {"no label": "", "another label": "bug\nci:fullish", "ci:full": "ci:full", "labels unreadable": "ci:full"}
DRAFTS = ("false", "true")
HEADS = ("claude/lane-x-1-a-card", "train/7", "agent/train/7")
CARD_TIERS = ("fast", "touched", "", "Fast")


def _outputs(paths: list[str], draft: str, labels: str, head: str, card_tier: str) -> dict[str, str]:
    """The `changes` job's outputs for one pull request: `trialbox` by the diff step's pattern, `docs_only` by
    ci_docs_only, the tier by ci_tier."""
    trialbox = "true" if any(re.match(_trialbox_pattern(), p) for p in paths) else "false"
    docs_only = "true" if ci_docs_only.docs_only(paths) else "false"
    env = {"EVENT": "pull_request", "DRAFT": draft, "HEAD_REF": head, "PROVED": "", "DOCS_ONLY": docs_only,
           "LABELS": labels, "CARD_TIER": card_tier}  # fmt: skip
    return {"trialbox": trialbox, "docs_tests": "", **_tier(env, paths)}


def _ctx(outputs: dict[str, str], *, draft: str = "false", head: str = "claude/lane-x-1-a-card") -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "github.event_name": "pull_request",
        "github.head_ref": head,
        "github.event.pull_request.draft": draft == "true",
        "github.event.action": "synchronize",
        "needs.unit-shard.result": "success",
    }
    ctx.update({f"needs.changes.outputs.{k}": v for k, v in outputs.items()})
    return ctx


def _runs(name: str, ctx: dict[str, Any], *, deps_ok: bool = True) -> bool:
    return evaluate(_jobs()[name].get("if"), ctx, deps_ok=deps_ok, allowed=EXPLAINED if name in UNIT_JOBS else None)


CASES = [
    pytest.param(paths, draft, label, id=f"{paths} | draft={draft} | {label}")
    for paths, draft, label in itertools.product(PATHS, DRAFTS, LABELS)
]


@pytest.mark.parametrize(("paths", "draft", "label"), CASES)
def test_every_pull_request_runs_the_unit_shards(paths: str, draft: str, label: str) -> None:
    """The table: every path set, draft or not, with each label. The tier code says `unit=true` and both unit jobs'
    conditions hold with the outputs it gives."""
    out = _outputs(PATHS[paths], draft, LABELS[label], "claude/lane-x-1-a-card", "fast")
    assert out["unit"] == "true", out
    ctx = _ctx(out, draft=draft)
    for job in UNIT_JOBS:
        assert _runs(job, ctx), (job, out)


@pytest.mark.parametrize(("card_tier", "head"), list(itertools.product(CARD_TIERS, HEADS)))
def test_no_card_tier_and_no_branch_name_skips_them(card_tier: str, head: str) -> None:
    for paths in ("a docs page", "a service on no full-tier path", "an empty diff"):
        out = _outputs(PATHS[paths], "true", "", head, card_tier)
        assert out["unit"] == "true", (paths, out)
        for job in UNIT_JOBS:
            assert _runs(job, _ctx(out, draft="true", head=head)), (job, paths, out)


def test_a_changes_job_that_failed_or_said_nothing_runs_them() -> None:
    """`changes` failed (no outputs, result failure) or its tier step printed nothing: the shards run, and `unit`
    turns red when they do not pass, never skipped."""
    for outputs in ({}, {"trialbox": "true"}, {"trialbox": "true", "full": "false", "scenarios": "false"}):
        ctx = _ctx(outputs)
        ctx["needs.changes.result"] = "failure"
        for job in UNIT_JOBS:
            assert _runs(job, ctx, deps_ok=False), (job, outputs)


def test_the_unit_aggregate_runs_when_a_shard_failed_and_then_fails() -> None:
    ctx = _ctx(_outputs(PATHS["a docs page"], "true", "", "claude/lane-x-1-a-card", "fast"))
    ctx["needs.unit-shard.result"] = "failure"
    assert _runs("unit", ctx, deps_ok=False)
    first = _jobs()["unit"]["steps"][0]
    assert 'needs.unit-shard.result }}" != "success"' in first["run"] and "exit 1" in first["run"]
    assert "if" not in first and not first.get("continue-on-error")


def test_the_tier_code_says_unit_for_every_pull_request_and_full_elsewhere() -> None:
    """``unit_shards`` itself, beside the command line: a pull request always; a push and a run by hand as `full`
    (so a proved master push, D-578, still skips them: the evaluator says false there, it is not blind)."""
    for full in (True, False):
        assert ci_tier.unit_shards({"EVENT": "pull_request"}, full)[0] is True
        assert ci_tier.unit_shards({"EVENT": "push"}, full)[0] is full
    out = _tier({"EVENT": "push", "PROVED": "true", "CARD_TIER": "fast"}, [])
    assert out == {"full": "false", "scenarios": "false", "unit": "false"}
    push = {"github.event_name": "push", "needs.unit-shard.result": "skipped"}
    push.update({f"needs.changes.outputs.{k}": v for k, v in {"trialbox": "true", **out}.items()})
    assert not _runs("unit-shard", push) and not _runs("unit", push)
    out = _tier({"EVENT": "push", "PROVED": "false", "CARD_TIER": "fast"}, [])
    assert out["unit"] == "true"


def test_the_changes_job_hands_the_tier_codes_unit_on() -> None:
    changes = _jobs()["changes"]
    assert changes["outputs"]["unit"] == "${{ steps.tier.outputs.unit }}"
    tier = next(s for s in changes["steps"] if s.get("id") == "tier")
    assert "tools/ci_tier.py" in tier["run"] and '>> "$GITHUB_OUTPUT"' in tier["run"]
    assert "if" not in tier and not tier.get("continue-on-error")


# ------------------------------------------------------------------------------- the other ways a job is left out


def _on() -> dict[str, Any]:
    doc = _wf()
    on = doc.get("on") or doc.get(True)
    assert isinstance(on, dict)
    return on


def test_every_pull_request_starts_the_workflow() -> None:
    """No path, branch or type filter can keep the workflow (and so the shards) from a pull request. A draft that
    is marked ready starts it again (``ready_for_review``)."""
    pr = _on()["pull_request"]
    assert set(pr) <= {"types"}, f"a filter on pull_request: {sorted(set(pr) - {'types'})}"
    assert {"opened", "synchronize", "reopened", "ready_for_review"} <= set(pr["types"])


def test_the_unit_jobs_wait_only_for_jobs_that_always_run() -> None:
    """``needs`` on a job that can be skipped skips the dependent too (unless it says ``!cancelled()``, which both
    do; this holds the rest in case that goes)."""
    jobs = _jobs()
    assert _needs(jobs["unit-shard"]) == ["changes"]
    assert _needs(jobs["unit"]) == ["changes", "unit-shard"]
    changes = jobs["changes"]
    assert "if" not in changes and not changes.get("continue-on-error") and not _needs(changes)
    for name in UNIT_JOBS:
        assert not jobs[name].get("continue-on-error"), name  # a red shard is red, never a pass


def test_the_matrix_is_every_shard_and_cannot_be_emptied() -> None:
    from tools import test_shard

    strategy = _jobs()["unit-shard"]["strategy"]
    matrix = strategy["matrix"]
    assert set(matrix) == {"shard"}, "no include, exclude or other axis can drop a shard"
    shards = matrix["shard"]
    assert isinstance(shards, list) and shards == list(range(1, len(shards) + 1)) and len(shards) >= 2
    assert test_shard.pins().count == len(shards)
    assert strategy["fail-fast"] is False and "max-parallel" not in strategy


def test_no_step_of_the_shards_is_skipped_before_the_tests_ran() -> None:
    """A step's own ``if`` (or continue-on-error) on the way to pytest would skip the tests inside a green job."""
    steps = _jobs()["unit-shard"]["steps"]
    run = next(i for i, s in enumerate(steps) if "make test " in str(s.get("run", "")))
    for step in steps[: run + 1]:
        assert "if" not in step and not step.get("continue-on-error"), step.get("name") or step.get("uses")
    assert "SHARD=${{ matrix.shard }}/${{ strategy.job-total }}" in steps[run]["run"]
    unit = _jobs()["unit"]["steps"]
    gates = [s for s in unit if any(k in str(s.get("run", "")) for k in ("test_shard check", "coverage_ratchet"))]
    assert len(gates) == 2 and all("if" not in s and not s.get("continue-on-error") for s in gates)


def test_the_evaluator_refuses_what_it_cannot_read() -> None:
    """The evaluator's own check: it says false where GitHub would, and refuses a context it does not know."""
    ctx = {"needs.changes.outputs.full": "false", "github.event_name": "pull_request"}
    assert not evaluate("needs.changes.outputs.full == 'true'", ctx, deps_ok=True)
    assert not evaluate("${{ !cancelled() && needs.changes.outputs.unit == 'true' }}", ctx, deps_ok=False)
    assert evaluate("${{ !cancelled() && needs.changes.outputs.unit != 'false' }}", ctx, deps_ok=False)
    assert not evaluate("needs.changes.outputs.unit != 'false'", ctx, deps_ok=False)  # no status function: success()
    assert not evaluate("github.event.pull_request.draft == false", {"github.event.pull_request.draft": True},
                        deps_ok=True)  # fmt: skip
    assert evaluate("'false'", {}, deps_ok=True)  # a non-empty string is true, as on GitHub
    assert not evaluate("false", {}, deps_ok=True)
    assert evaluate("startsWith(github.head_ref, 'train/')", {"github.head_ref": "train/3"}, deps_ok=True)
    for bad in ("hashFiles('x') != ''", "vars.SKIP_UNIT != 'true'", "matrix.shard > 0", "inputs.x"):
        with pytest.raises(Unknown):
            evaluate(bad, ctx, deps_ok=True)
    for unexplained in ("!github.event.pull_request.draft", "needs.changes.outputs.full == 'true'",
                        "!contains(github.event.pull_request.labels.*.name, 'x')"):  # fmt: skip
        with pytest.raises(Unknown):
            evaluate(f"!cancelled() && needs.changes.outputs.unit != 'false' && {unexplained}", ctx, deps_ok=True,
                     allowed=EXPLAINED)  # fmt: skip


def test_a_unit_jobs_condition_reads_only_the_tier_codes_answer() -> None:
    """Every context the two conditions name is the tier code's `unit` (status functions aside)."""
    for name in UNIT_JOBS:
        cond = str(_jobs()[name]["if"])
        names = {v for k, v in _tokens(cond.removeprefix("${{").removesuffix("}}")) if k == "name"}
        assert names - {"cancelled", "true", "false"} == EXPLAINED, (name, cond)
