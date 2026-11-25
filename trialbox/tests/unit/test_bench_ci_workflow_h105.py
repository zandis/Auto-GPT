"""H-105 (the owner's rulings, the integrator's comments 7117447272 and 7117870645 item 8 on #639): what code can
reach the bench host's self-hosted runner. The repository is public: a self-hosted runner runs strangers' code if any
trigger a fork or a pull request can fire reaches it. So the jobs that can run on the bench label are reachable from
a push to this repository's train and lane branches (``train/*``, ``agent/*``, ``claude/*``, ``lane-*``: a push
needs write access here; a fork's pull request does not) and from a run by hand by the repository's owner only, and
no other workflow names the label. A lane branch's older run is cancelled by its newer push; a train's never.

The check reads EVERY workflow file in .github/workflows. A job "can run on the bench" when its ``runs-on`` is not a
hosted image label it can prove (a self-hosted label, the bench label, a runner group, an expression it cannot
resolve, or a reusable workflow of another repository). The planted cases below are the mutants it must catch."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.bench_ci import launcher

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
BENCH = "trialbox-bench-ci.yml"
LABEL = "tb-bench"
BENCH_NAME = "TrialBox bench CI"
BRANCHES = ["train/*", "agent/*", "claude/*", "lane-*"]  # the allow-list: exactly these, in this order
SWITCH = "vars.TB_BENCH_CI == 'on'"  # the owner's switch: a repository variable only an admin sets; unset: nothing runs
OWNER = (
    "(github.event_name == 'workflow_dispatch' && github.actor == github.repository_owner && "
    "github.triggering_actor == github.repository_owner && (github.ref == 'refs/heads/master' || "
    + " || ".join(f"startsWith(github.ref, 'refs/heads/{b.removesuffix('*')}')" for b in BRANCHES)
    + "))"
)  # 1448-16: a run by hand on a ref the gate would refuse is not even scheduled
PUSH_ANY = (
    "(github.event_name == 'push' && ("
    + " || ".join(f"startsWith(github.ref, 'refs/heads/{b.removesuffix('*')}')" for b in BRANCHES)
    + "))"
)
PUSH_TRAIN = "(github.event_name == 'push' && startsWith(github.ref, 'refs/heads/train/'))"
GUARD = f"{SWITCH} && ({PUSH_ANY} || {OWNER})"  # a lane push, a train push, the owner's run by hand
HEAVY_GUARD = f"{SWITCH} && ({PUSH_TRAIN} || {OWNER})"  # a train push, the owner's run by hand: never a lane push
HEAVY = {
    "gpu-suites",
    "full-set",
    "rehearse-box",
    "rehearse-gpu-box",
}  # never a lane push: the engine and GPU profiles (F5), 600 min
CONCURRENCY = {
    "group": "trialbox-bench-ci-${{ github.ref }}-${{ startsWith(github.ref, 'refs/heads/train/') && github.run_id "
    "|| 'latest' }}",
    "cancel-in-progress": "${{ !startsWith(github.ref, 'refs/heads/train/') }}",
}
HOSTED = re.compile(r"^(ubuntu|windows|macos)-(latest|[0-9][0-9a-z.]*)(-arm)?$")
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
MATRIX_REF = re.compile(r"^\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}$")
FROM_JSON = re.compile(r"^\$\{\{\s*fromJSON\((.*)\)\s*\}\}$", re.S)
# what a matrix expression may hold besides its string literals: the event's name, compared and combined
SAFE_EXPR = re.compile(r"^(\s|''|github\.event_name|==|!=|&&|\|\||\(|\))*$")

pytestmark = pytest.mark.nodb


def _on(doc: dict[Any, Any]) -> dict[str, Any]:
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on if isinstance(on, dict) else {}


def _norm(text: Any) -> str:
    return " ".join(str(text).split())


def _matrix_values(job: dict[str, Any], key: str) -> list[Any] | None:
    """Every value ``matrix.<key>`` can take, or None when the file does not prove it."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return None
    values: list[Any] = []
    plain = matrix.get(key)
    if isinstance(plain, list):
        values += plain
    elif plain is not None:
        return None
    include = matrix.get("include")
    if isinstance(include, list):
        values += [row[key] for row in include if isinstance(row, dict) and key in row]
    elif isinstance(include, str):
        m = FROM_JSON.match(include.strip())
        if not m or not SAFE_EXPR.match(re.sub(r"'[^']*'", "''", m.group(1))):
            return None
        for literal in re.findall(r"'([^']*)'", m.group(1)):
            if not literal.startswith("["):
                continue  # an event name compared, not a candidate matrix
            try:
                rows = json.loads(literal)
            except ValueError:
                return None
            values += [row[key] for row in rows if isinstance(row, dict) and key in row]
    elif include is not None:
        return None
    return values or None


def runner_labels(job: dict[str, Any]) -> list[str] | None:
    """The labels a job can ask for, or None when the file cannot prove them (counted as the bench)."""
    if "runs-on" not in job:
        return None  # a reusable workflow: its own file is read, but one of another repository is not
    ro = job["runs-on"]
    if isinstance(ro, str):
        m = MATRIX_REF.match(ro.strip())
        if m:
            values = _matrix_values(job, m.group(1))
            if values is None or not all(isinstance(v, str) and "${{" not in v for v in values):
                return None
            return [str(v) for v in values]
        return None if "${{" in ro else [ro]
    if isinstance(ro, list) and all(isinstance(v, str) and "${{" not in v for v in ro):
        return list(ro)
    if isinstance(ro, dict) and set(ro) == {"labels"}:
        return runner_labels({"runs-on": ro["labels"]})
    return None  # a runner group, or anything else


def can_run_on_bench(job: dict[str, Any]) -> bool:
    got = runner_labels(job)
    return got is None or any(not HOSTED.match(label) for label in got)


def _bench_problems(text: str, doc: dict[Any, Any]) -> list[str]:
    out: list[str] = []
    on = _on(doc)
    if set(on) != {"push", "workflow_dispatch"}:
        out.append(f"{BENCH}: triggers {sorted(on)}: only push to the train and lane branches and workflow_dispatch")
    if on.get("push") != {"branches": BRANCHES}:
        out.append(f"{BENCH}: the push trigger is {on.get('push')!r}, not branches {BRANCHES} alone")
    if doc.get("concurrency") != CONCURRENCY:
        out.append(
            f"{BENCH}: concurrency is {doc.get('concurrency')!r}: a lane's older run is cancelled, a train's never"
        )
    if on.get("workflow_dispatch") not in (None, {}):
        out.append(f"{BENCH}: workflow_dispatch carries settings ({on.get('workflow_dispatch')!r})")
    if doc.get("permissions") != {"contents": "read"}:
        out.append(f"{BENCH}: permissions are {doc.get('permissions')!r}, not contents: read")
    if re.search(r"\bsecrets\b", text):
        out.append(f"{BENCH}: names secrets: no secret is passed to a bench job")
    if re.search(r"github\.token|toJSON\(\s*github\s*\)", text):  # F6: the job's token, or the context holding it
        out.append(f"{BENCH}: hands a job the workflow token (github.token or toJSON(github))")
    for ref in re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, re.M):
        if not PINNED.match(ref):
            out.append(f"{BENCH}: action {ref} is not pinned by its full commit id")
    for name, job in (doc.get("jobs") or {}).items():
        cond = _unwrap(_norm(job.get("if", "")))
        want = HEAVY_GUARD if name in HEAVY else GUARD
        if cond not in (want, f"always() && ({want})", f"!cancelled() && ({want})"):
            out.append(f"{BENCH}: job {name}'s if is not the switch and the branch-or-owner guard: {cond!r}")
        if can_run_on_bench(job) and cond.startswith("always()"):  # M-1448-4: always() also runs after a cancel
            out.append(f"{BENCH}: job {name} on the bench starts even after the run was cancelled (always())")
        if "permissions" in job:
            out.append(f"{BENCH}: job {name} sets its own permissions")
        if "uses" in job or "container" in job or "services" in job:
            out.append(f"{BENCH}: job {name} calls a workflow or a container the file does not show")
        for step in job.get("steps") or []:
            checkout = str(step.get("uses", "")).startswith("actions/checkout@")
            if checkout and (step.get("with") or {}).get("persist-credentials") is not False:
                out.append(f"{BENCH}: job {name}'s checkout keeps a credential (persist-credentials: false)")
        got = runner_labels(job)
        if name == "rehearse-gpu-box" and got != ["self-hosted", LABEL, f"{LABEL}-gpu"]:
            out.append(f"{BENCH}: job {name} is not on a GPU slot ({got!r})")
        if can_run_on_bench(job) and name not in HEAVY and (got is None or got[2:] != [f"{LABEL}-cpu"]):
            out.append(f"{BENCH}: job {name} reaches a lane push on {got!r}: a lane push gets the CPU profile only")
        if can_run_on_bench(job):
            profiles = {f"{LABEL}-{p}" for p in launcher.PROFILES}
            if got is None or len(got) != 3 or got[:2] != ["self-hosted", LABEL] or got[2] not in profiles:
                out.append(f"{BENCH}: job {name} asks for {got!r}, not [self-hosted, {LABEL}, {LABEL}-<profile>]")
    return out


def problems(files: dict[str, str]) -> list[str]:
    """Every way a trigger other than a train push or the owner's run by hand reaches the bench label."""
    out: list[str] = []
    if BENCH not in files:
        return [f"{BENCH}: missing"]
    for name, text in sorted(files.items()):
        doc = yaml.safe_load(text)
        if not isinstance(doc, dict):
            out.append(f"{name}: not a workflow")
            continue
        if name == BENCH:
            out += _bench_problems(text, doc)
            continue
        if LABEL in text.lower():
            out.append(f"{name}: names the bench label {LABEL!r}: only {BENCH} may")
        wr = _on(doc).get("workflow_run") or {}
        if BENCH_NAME in (wr.get("workflows") or []):
            out.append(f"{name}: runs after the bench workflow: the gate must not depend on it")
        for job_name, job in (doc.get("jobs") or {}).items():
            if can_run_on_bench(job):
                out.append(f"{name}: job {job_name} can run on a self-hosted runner ({runner_labels(job)!r})")
    return out


def _files() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.y*ml"))}


def test_no_other_trigger_reaches_the_bench_label() -> None:
    """The invariant: no trigger but a push to a train or lane branch of this repository, or the owner's run by hand,
    reaches a job on the bench label."""
    files = _files()
    assert len(files) >= 10  # every workflow file of the folder is read
    assert problems(files) == []


def _sub(old: str, new: str, count: int = 1) -> Callable[[str], str]:
    def go(text: str) -> str:
        assert old in text, old
        return text.replace(old, new, count)

    return go


DISPATCH = "  workflow_dispatch:\n\npermissions:"
BRANCH_LINE = 'branches: ["train/*", "agent/*", "claude/*", "lane-*"]'
CHECKOUT_PIN = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"

# (the case, the file it changes, the change, words of the problem it must raise)
PLANTED = [
    ("pull_request", BENCH, _sub(DISPATCH, "  workflow_dispatch:\n  pull_request:\n\npermissions:"), "triggers"),
    ("pull_request_target", BENCH, _sub(DISPATCH, "  workflow_dispatch:\n  pull_request_target:\n\npermissions:"),
     "triggers"),
    ("schedule", BENCH, _sub(DISPATCH, "  workflow_dispatch:\n  schedule:\n    - cron: '0 1 * * *'\n\npermissions:"),
     "triggers"),
    ("workflow_call", BENCH, _sub(DISPATCH, "  workflow_dispatch:\n  workflow_call:\n\npermissions:"), "triggers"),
    ("any branch", BENCH, _sub(BRANCH_LINE, 'branches: ["**"]'), "push trigger"),
    ("another branch too", BENCH, _sub(BRANCH_LINE, BRANCH_LINE.replace('"lane-*"]', '"lane-*", "feature/*"]')),
     "push trigger"),
    ("a deeper lane branch", BENCH, _sub(BRANCH_LINE, BRANCH_LINE.replace('"claude/*"', '"claude/**"')), "push trigger"),
    ("tags", BENCH, _sub(BRANCH_LINE, BRANCH_LINE + '\n    tags: ["*"]'), "push trigger"),
    ("branches-ignore", BENCH, _sub(BRANCH_LINE, 'branches-ignore: ["master"]'), "push trigger"),
    ("issue_comment", BENCH, _sub(DISPATCH, "  workflow_dispatch:\n  issue_comment:\n\npermissions:"), "triggers"),
    ("workflow_run", BENCH, _sub(DISPATCH, '  workflow_dispatch:\n  workflow_run:\n    workflows: ["TrialBox CI"]\n\n'
                                           "permissions:"), "triggers"),
    ("a guard for any branch", BENCH, _sub("startsWith(github.ref, 'refs/heads/lane-')", "startsWith(github.ref, 'refs/')"),
     "guard"),
    ("no switch on one job", BENCH, _sub("if: vars.TB_BENCH_CI == 'on' && (", "if: ("), "guard"),
    ("no switch on the times job", BENCH, _sub("if: always() && (vars.TB_BENCH_CI == 'on' && (", "if: always() && (("),
     "guard"),
    ("a switch that is on when unset", BENCH, _sub("vars.TB_BENCH_CI == 'on'", "vars.TB_BENCH_CI != 'off'"), "guard"),
    ("a caller's variable as the switch", BENCH, _sub("vars.TB_BENCH_CI == 'on'", "env.TB_BENCH_CI == 'on'"), "guard"),
    ("full-set on a lane push", BENCH,
     _sub("(github.event_name == 'push' && startsWith(github.ref, 'refs/heads/train/')) ||",
          "(github.event_name == 'push' && (startsWith(github.ref, 'refs/heads/train/') || "
          "startsWith(github.ref, 'refs/heads/claude/'))) ||"), "guard"),
    ("the workflow token", BENCH, _sub("TB_DATA_DIR: ${{ runner.temp }}/tb-data", "TB_DATA_DIR: ${{ github.token }}"),
     "workflow token"),
    ("the whole context", BENCH, _sub("TB_DATA_DIR: ${{ runner.temp }}/tb-data", "TB_DATA_DIR: ${{ toJSON(github) }}"),
     "workflow token"),
    ("a lane job on the engine profile", BENCH,
     _sub("runs-on: [self-hosted, tb-bench, tb-bench-cpu]", "runs-on: [self-hosted, tb-bench, tb-bench-engine]"),
     "CPU profile only"),
    ("the GPU suites on a lane push", BENCH,
     _sub("name: bench gpu-suites\n    if: vars.TB_BENCH_CI == 'on' && ((github.event_name == 'push' && "
          "startsWith(github.ref, 'refs/heads/train/'))",
          "name: bench gpu-suites\n    if: vars.TB_BENCH_CI == 'on' && ((github.event_name == 'push' && "
          "(startsWith(github.ref, 'refs/heads/train/') || startsWith(github.ref, 'refs/heads/lane-')))"), "guard"),
    ("full-set after a cancel", BENCH, _sub("if: ${{ !cancelled() && (", "if: ${{ always() && ("), "after the run was"),
    ("the GPU box on a lane push", BENCH,
     _sub("name: bench rehearse-gpu-box\n    if: vars.TB_BENCH_CI == 'on' && (",
          "name: bench rehearse-gpu-box\n    if: vars.TB_BENCH_CI == 'on' && "
          "(startsWith(github.ref, 'refs/heads/claude/') || "), "guard"),
    ("the GPU box on a CPU slot", BENCH,
     lambda t: t.replace("    runs-on: [self-hosted, tb-bench, tb-bench-gpu]\n    timeout-minutes: 60  # D-537; no bench",
                         "    runs-on: [self-hosted, tb-bench, tb-bench-cpu]\n    timeout-minutes: 60  # D-537; no bench"),
     "GPU slot"),
    ("a train's run cancelled", BENCH, _sub("cancel-in-progress: ${{ !startsWith(github.ref, 'refs/heads/train/') }}",
                                            "cancel-in-progress: true"), "concurrency"),
    ("a train's run replaced", BENCH, _sub("&& github.run_id || 'latest' }}", "&& 'train' || 'latest' }}"),
     "concurrency"),
    ("dispatch inputs", BENCH, _sub(DISPATCH, "  workflow_dispatch:\n    inputs:\n      x:\n        type: string\n\n"
                                              "permissions:"), "workflow_dispatch carries"),
    ("no owner check", BENCH, _sub(" && github.actor == github.repository_owner", ""), "guard"),
    ("any event", BENCH, _sub("if: vars.TB_BENCH_CI == 'on' && (", "if: always() || vars.TB_BENCH_CI == 'on' && ("),
     "guard"),
    ("write permission", BENCH, _sub("permissions:\n  contents: read", "permissions:\n  contents: write"),
     "permissions"),
    ("a secret", BENCH, _sub("TB_DATA_DIR: ${{ runner.temp }}/tb-data", "TB_DATA_DIR: ${{ secrets.X }}"), "secrets"),
    ("unpinned action", BENCH, _sub(CHECKOUT_PIN, "actions/checkout@v7"), "not pinned"),
    ("checkout keeps the token", BENCH, _sub("persist-credentials: false", "persist-credentials: true"),
     "credential"),
    ("another label", BENCH, _sub("[self-hosted, tb-bench, tb-bench-cpu]", "[self-hosted, gpu-box]"), "asks for"),
    ("the gate on the bench", "trialbox-ci.yml", _sub("runs-on: ubuntu-latest", "runs-on: [self-hosted, tb-bench]"),
     "names the bench label"),
    ("the gate on any self-hosted runner", "trialbox-ci.yml", _sub("runs-on: ubuntu-latest", "runs-on: self-hosted"),
     "self-hosted runner"),
    ("a runner group", "trialbox-visual.yml", _sub("runs-on: ubuntu-24.04", "runs-on:\n      group: bench"),
     "self-hosted runner"),
    ("a matrix leg on the bench", "trialbox-images.yml", _sub('"runner":"ubuntu-24.04-arm"', '"runner":"self-hosted"'),
     "self-hosted runner"),
    ("a matrix from an input", "trialbox-images.yml",
     _sub("include: ${{ fromJSON((github.event_name", "include: ${{ fromJSON(inputs.m || (github.event_name"),
     "self-hosted runner"),
    ("a reusable workflow of another repository", "trialbox-visual.yml",
     lambda t: t + "\n  extra:\n    uses: someone/else/.github/workflows/x.yml@" + "0" * 40 + "\n", "self-hosted runner"),
    ("the gate waits for the bench", "trialbox-visual.yml",
     _sub("  workflow_dispatch:", '  workflow_dispatch:\n  workflow_run:\n    workflows: ["TrialBox bench CI"]'),
     "depend"),
]  # fmt: skip


@pytest.mark.parametrize(("case", "name", "change", "words"), PLANTED, ids=[p[0] for p in PLANTED])
def test_planted_trigger_mutants_are_caught(case: str, name: str, change: Any, words: str) -> None:
    files = _files()
    files[name] = change(files[name])
    got = problems(files)
    assert any(words in p for p in got), (case, got)


def test_planted_bench_workflow_gone_is_caught() -> None:
    files = _files()
    del files[BENCH]
    assert problems(files) == [f"{BENCH}: missing"]


def test_every_bench_job_writes_its_wall_time_and_one_table_holds_them() -> None:
    doc = yaml.safe_load((WORKFLOWS / BENCH).read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    bench = [n for n, j in jobs.items() if can_run_on_bench(j)]
    assert {"unit-shard", "integration", "gpu-suites", "full-set", "rehearse-box", "rehearse-gpu-box"} <= set(bench)
    for name in bench:
        steps = jobs[name]["steps"]
        assert "TB_BENCH_T0" in steps[0]["run"], name  # the clock starts before the checkout
        wall = next(s for s in steps if s.get("name") == "Wall time")
        assert wall["if"] == "always()" and "GITHUB_STEP_SUMMARY" in wall["run"], name
        upload = steps[-1]
        assert upload["if"] == "always()" and upload["with"]["name"].startswith("bench-time-"), name
    times = jobs["bench-times"]
    assert set(times["needs"]) == set(bench) and HOSTED.match(times["runs-on"])
    assert "GITHUB_STEP_SUMMARY" in times["steps"][-1]["run"]


def test_the_hosted_gate_does_not_wait_for_the_bench() -> None:
    gate = yaml.safe_load((WORKFLOWS / "trialbox-ci.yml").read_text(encoding="utf-8"))
    assert all(not can_run_on_bench(j) for j in gate["jobs"].values())
    assert "workflow_run" not in _on(gate)


def test_the_bench_jobs_ask_for_the_labels_the_launcher_registers() -> None:
    s = launcher.Settings({"BENCH_LABEL": LABEL})
    doc = yaml.safe_load((WORKFLOWS / BENCH).read_text(encoding="utf-8"))
    for name, job in doc["jobs"].items():
        got = runner_labels(job)
        if can_run_on_bench(job):
            assert got is not None and got[1:] == launcher.labels(s, got[2].removeprefix(f"{LABEL}-")), name


def test_the_workflow_linter_knows_the_bench_labels_and_no_other() -> None:
    """The workflow linter (the `checks` job) refuses a label it does not know; its config declares the bench's labels, the
    ones the launcher registers, and nothing more."""
    config = yaml.safe_load((ROOT.parent / ".github" / "actionlint.yaml").read_text(encoding="utf-8"))
    assert config == {"self-hosted-runner": {"labels": [LABEL] + [f"{LABEL}-{p}" for p in launcher.PROFILES]}}


def _unwrap(cond: str) -> str:
    """``${{ x }}`` and ``x`` are the same condition."""
    return re.sub(r"^\$\{\{ (.*) \}\}$", r"\1", cond)


def _evaluate(cond: str, ctx: dict[str, str]) -> bool:
    """A job's ``if`` for one event (``ctx["cancelled"] == "yes"``: the run was cancelled): the forms the guard uses
    (&&, ||, ==, startsWith, always(), !cancelled(), contexts). The code host compares strings without case
    (L-1448-19), so both sides are lowered."""
    cancelled = ctx.get("cancelled") == "yes"  # 1448-19 (2): a cancelled run is modelled, not assumed away
    expr = _unwrap(cond).replace("!cancelled()", str(not cancelled)).replace("always()", "True")
    expr = expr.replace("&&", " and ").replace("||", " or ").replace("startsWith(", "_sw(")
    expr = re.sub(r"'[^']*'", lambda m: m.group(0).lower(), expr)
    expr = re.sub(r"\b(github|vars)\.[A-Za-z_]+", lambda m: repr(str(ctx.get(m.group(0), "")).lower()), expr)
    assert re.fullmatch(r"[\s()'A-Za-z0-9_/.,=:-]*", expr.replace("_sw", "")), expr

    def sw(a: object, b: object) -> bool:  # startsWith is case-insensitive
        return str(a).lower().startswith(str(b).lower())

    return bool(eval(expr, {"__builtins__": {}, "_sw": sw, "True": True}))  # the test's own expression forms


def _event(event: str, ref: str = "refs/heads/master", actor: str = "the-owner", by: str = "") -> dict[str, str]:
    return {
        "github.event_name": event,
        "github.ref": ref,
        "github.actor": actor,
        "github.triggering_actor": by or actor,
        "github.repository_owner": "the-owner",
    }


EVENTS = {
    "train push": (_event("push", "refs/heads/train/160"), "all"),
    "owner by hand": (_event("workflow_dispatch"), "all"),
    "lane push claude/": (_event("push", "refs/heads/claude/lane-x"), "light"),
    "lane push agent/": (_event("push", "refs/heads/agent/x"), "light"),
    "lane push lane-": (_event("push", "refs/heads/lane-h-1"), "light"),
    "push to master": (_event("push"), "none"),
    "push to another branch": (_event("push", "refs/heads/feature/x"), "none"),
    "push of a tag": (_event("push", "refs/tags/train/1"), "none"),
    "a pull request": (_event("pull_request", "refs/pull/1/merge", "a-stranger"), "none"),
    "pull_request_target": (_event("pull_request_target", "refs/heads/master", "a-stranger"), "none"),
    "an issue comment": (_event("issue_comment", "refs/heads/master", "a-stranger"), "none"),
    "by hand, not the owner": (_event("workflow_dispatch", actor="a-collaborator"), "none"),
    "re-run by another": (_event("workflow_dispatch", by="a-collaborator"), "none"),
    "owner by hand on a lane branch": (_event("workflow_dispatch", "refs/heads/claude/lane-x"), "all"),
    "owner by hand on another branch": (_event("workflow_dispatch", "refs/heads/feature/x"), "none"),
    "owner by hand on a tag": (_event("workflow_dispatch", "refs/tags/v1"), "none"),
}


@pytest.mark.parametrize("case", sorted(EVENTS))
@pytest.mark.parametrize("switch", ["on", "ON", "", "off", "On "])
def test_which_jobs_each_event_runs_with_the_switch_on_or_not(case: str, switch: str) -> None:
    ctx, weight = EVENTS[case]
    jobs = yaml.safe_load((WORKFLOWS / BENCH).read_text(encoding="utf-8"))["jobs"]
    ran = {n for n, j in jobs.items() if _evaluate(_norm(j["if"]), {**ctx, "vars.TB_BENCH_CI": switch})}
    if switch.lower() != "on":  # the code host's == ignores case: ON is on (L-1448-19); "On " is not
        assert ran == set(), "the switch is not on: no job runs, the bench is never asked for"
    elif weight == "all":
        assert ran == set(jobs)
    elif weight == "light":
        assert ran == set(jobs) - HEAVY
    else:
        assert ran == set()


@pytest.mark.parametrize("case", ["train push", "owner by hand"])
def test_after_a_cancel_no_bench_job_starts_and_only_the_times_table_does(case: str) -> None:
    """1448-19 (2), M-1448-4: with the run cancelled, a job with !cancelled() does not start; always() still does."""
    ctx, _ = EVENTS[case]
    jobs = yaml.safe_load((WORKFLOWS / BENCH).read_text(encoding="utf-8"))["jobs"]
    on = {**ctx, "vars.TB_BENCH_CI": "on", "cancelled": "yes"}
    started = {n for n, j in jobs.items() if _unwrap(_norm(j["if"])).startswith(("always()", "!cancelled()"))}
    ran = {n for n in started if _evaluate(_norm(jobs[n]["if"]), on)}
    assert ran == {"bench-times"}, ran


def test_the_gpu_box_rehearsal_runs_on_a_gpu_slot_and_reports_its_steps() -> None:
    job = yaml.safe_load((WORKFLOWS / BENCH).read_text(encoding="utf-8"))["jobs"]["rehearse-gpu-box"]
    assert runner_labels(job) == ["self-hosted", LABEL, f"{LABEL}-gpu"]
    runs = [s.get("run", "") for s in job["steps"]]
    assert 'tools/bench_ci/gpu_box.sh "$RUNNER_TEMP/gpu-box"' in runs
    report = next(s for s in job["steps"] if s.get("name") == "Report in the job summary")
    assert report["if"] == "always()" and "gpu-box/report.md" in report["run"]
