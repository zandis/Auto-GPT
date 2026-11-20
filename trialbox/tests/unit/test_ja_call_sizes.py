"""O-6 (plan 10 row 10E-38, D-1346): the share of Japanese judge calls the excerpt budget cuts, counted offline.

The first tests need no database: the contexts come from the registry, the budget follows the context, impossible
counts and unlike arms are refused, A6 is compared unrounded, the run opens no network socket and needs no test
suite, and a stopped run leaves no scratch behind. The last ones run the tool on a small synthetic Japanese site.
"""

from __future__ import annotations

import ast
import json
import os
import signal
import socket
import stat
import subprocess
import sys
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from tools import ja_call_sizes as o6
from tools.ja_call_sizes import Arm, Call, SizesError, SizingJudge, arm_contexts, compare

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools" / "ja_call_sizes.py"


def _criterion() -> Any:
    from tools.cascade_e2e import load_trial

    rs = load_trial("GZQO")
    return next(c for c in rs.active() if c.note_question)


def _call(n: int, prompt: int = 900, fixed: int = 400, role: str = "judge", pid: str = "p") -> Call:
    return Call(f"o6-{n}", role, pid, "h", prompt, fixed, 1, 10)


def _arm(profile: str, cut: list[bool]) -> Arm:
    a = Arm(profile, {})
    a.add("S", [(f"C{i}", _call(i, pid=f"p{i}"), c) for i, c in enumerate(cut)], [])
    return a


# ---------------------------------------------------------------------------------------- the contexts (High 2)
def test_the_arms_contexts_are_the_registered_builds_of_each_profile() -> None:
    small, large = arm_contexts("rtx5090"), arm_contexts("rtxpro6000")
    assert {r: c["context"] for r, c in small.items()} == {"judge": 8192, "verifier": 8192}
    assert {r: c["context"] for r, c in large.items()} == {"judge": 32768, "verifier": 32768}
    # the record names the alias and the profile only: no build id, no repository
    assert {k for c in (*small.values(), *large.values()) for k in c} == {"alias", "profile", "context"}


def test_a_profile_with_no_registered_context_is_refused() -> None:
    import yaml

    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text("utf-8"))
    for b in doc["builds"]:
        if str(b.get("build_id", "")).endswith("-rtx5090"):
            b["context_length"] = None
    with pytest.raises(SizesError, match="no context"):
        arm_contexts("rtx5090", doc)
    with pytest.raises(SizesError, match="unknown profile"):
        arm_contexts("not-a-profile")


# ---------------------------------------------------------------------------------------- the budget (review Low)
def test_the_excerpt_budget_follows_the_context_not_the_profile_name() -> None:
    c = _criterion()
    day = date(2026, 11, 1)

    def budget(judge: int, verifier: int, name: str) -> int:
        ctx = {"judge": {"alias": "j", "profile": name, "context": judge},
               "verifier": {"alias": "v", "profile": name, "context": verifier}}  # fmt: skip
        room = SizingJudge(ctx).excerpt_budget(c, day)
        assert isinstance(room, int)
        return room

    assert budget(8192, 8192, "rtx5090") == budget(8192, 8192, "rtxpro6000")
    assert budget(8192, 8192, "x") < budget(32768, 32768, "x")
    assert budget(32768, 8192, "x") == budget(8192, 8192, "x")  # the smaller of the two models decides


def test_the_same_window_is_cut_at_8k_and_whole_at_32k() -> None:
    from matching.excerpts import Note, build, note_tokens

    c = _criterion()
    day = date(2026, 11, 1)
    rooms: list[int] = []
    for n in (8192, 32768):
        room = SizingJudge(
            {r: {"alias": r, "profile": "x", "context": n} for r in ("judge", "verifier")}
        ).excerpt_budget(c, day)
        assert isinstance(room, int)
        rooms.append(room)
    text = "右第一中足趾節関節に急性の発赤・腫脹・疼痛あり、急性痛風発作中である。" * 20
    # each note its own text: a copy of a newer note's text is not left out (D-905)
    notes = [Note(f"n{i}", date(2026, 10, 1 + i), "progress", f"第{i + 1}回。{text}") for i in range(12)]
    assert rooms[0] < sum(note_tokens(n.text) for n in notes) < rooms[1]
    small, large = (build(notes, {}, room) for room in rooms)
    assert small.left_out > 0 and large.left_out == 0


# ---------------------------------------------------------------------------------------- the counts (Medium 5)
@pytest.mark.parametrize(
    "call",
    [_call(1, prompt=0, fixed=0), _call(1, prompt=300, fixed=400), _call(1, prompt=900, fixed=0),
     _call(1, role="second_opinion")],
)  # fmt: skip
def test_an_impossible_call_is_refused(call: Call) -> None:
    with pytest.raises(SizesError):
        Arm("rtx5090", {}).add("S", [("C", call, False)], [])


def test_a_question_asked_twice_is_refused() -> None:
    a = Arm("rtx5090", {})
    a.add("S", [("C", _call(1), False)], [])
    with pytest.raises(SizesError, match="asked twice"):
        a.add("S", [("C", _call(2), False)], [])


def test_a_tampered_count_is_refused() -> None:
    a = _arm("rtx5090", [True, False])
    a.truncated = 3
    with pytest.raises(SizesError, match="impossible"):
        _ = a.share


def test_an_arm_with_no_judge_call_is_not_judged() -> None:
    assert compare(Arm("rtx5090", {}), _arm("rtxpro6000", [False]))["result"] == "not judged"


# ---------------------------------------------------------------------------------------- A6, unrounded
def test_a6_is_two_points_unrounded() -> None:
    at_limit = _arm("rtx5090", [True] * 2 + [False] * 98)
    assert compare(at_limit, _arm("rtxpro6000", [False] * 100))["result"] == "pass"
    over = _arm("rtx5090", [True] * 21 + [False] * 979)  # 2.1 points, which rounds to 2
    got = compare(over, _arm("rtxpro6000", [False] * 1000))
    assert got["result"] == "fail" and Fraction(got["difference_points"]) == Fraction(21, 10)


def test_arms_that_asked_different_questions_are_not_compared() -> None:
    a, b = _arm("rtx5090", [False, False]), _arm("rtxpro6000", [False])
    assert compare(a, b)["result"] == "not judged"


def test_s3_calls_refuse_a_call_no_outcome_names() -> None:
    from types import SimpleNamespace

    judge = SizingJudge(arm_contexts("rtx5090"))
    judge.calls["o6-1"] = _call(1)
    res = SimpleNamespace(traces={})
    with pytest.raises(SizesError, match="named by no S3 outcome"):
        o6.s3_calls(res, judge)
    o = SimpleNamespace(stage="S3", evidence=[{"call_id": "o6-9"}])
    res = SimpleNamespace(traces={"p": SimpleNamespace(outcomes={"C": o}, notes_over_budget=[])})
    with pytest.raises(SizesError, match="did not make"):
        o6.s3_calls(res, judge)


# ---------------------------------------------------------------------------------------- the tokenizer
def test_the_record_says_the_count_is_the_estimate_and_bounds_it() -> None:
    got = o6.tokenizer_bound()
    assert got["true_count"] is False
    assert got["ja_excerpts"] == 200
    r = got["judge_over_estimate"]
    assert 0 < r["min"] <= r["median"] <= r["max"] <= 1  # on Japanese excerpts the estimate never undercounts


# ---------------------------------------------------------------------------------------- no network (High 1, 3)
def test_the_judge_opens_no_socket_and_reports_no_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    from matching.cascade.judge import ASKING, Asking

    judge = SizingJudge(arm_contexts("rtx5090"))
    c = _criterion()
    assert judge.excerpt_budget(c, date(2026, 11, 1)) == judge.budgets[c.id] > 0
    token = ASKING.set(Asking("p1", "h1", ("2025-11-01", "2026-11-01"), role="judge", question="q"))
    try:
        reply = judge.judge(role="judge", criterion_text=c.text, note_question=c.note_question, index_date=date(2026, 11, 1),
                            excerpts=[{"date": "2026-10-01", "note_type": "progress", "text": "痛風発作あり。"}])  # fmt: skip
    finally:
        ASKING.reset(token)
    assert reply.verdict == "unknown" and reply.refused is None and reply.reason == "abstained"
    call = judge.calls[reply.call_id]
    assert call.pid == "p1" and call.prompt_tokens > call.fixed_tokens > 0


def test_the_tool_imports_no_gateway_client_no_two_phase_and_no_test_suite() -> None:
    tree = ast.parse(SOURCE.read_text("utf-8"))
    names = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    banned = ("tests", "pytest", "tb_llm.client", "orchestrator.twophase", "httpx", "docker", "requests")
    assert not [m for m in names if any(m == b or m.startswith(b + ".") for b in banned)]


def test_the_tool_runs_without_the_test_suite_importable() -> None:
    code = (
        "import sys, importlib.abc\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name in ('tests', 'pytest') or name.startswith(('tests.', '_pytest')):\n"
        "            raise ImportError(name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "from tools import ja_call_sizes as o6\n"
        "o6.SizingJudge(o6.arm_contexts('rtx5090'))\n"
        "o6.tokenizer_bound()\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))}
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]


# ---------------------------------------------------------------------------------------- scratch (Medium 6, 7)
def test_a_sigterm_leaves_no_scratch_and_restores_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import pglocal

    monkeypatch.setattr(pglocal, "scratch_root", lambda: tmp_path / "scratch")
    monkeypatch.setenv("TB_DB_URL", "postgresql://127.0.0.1:1/x?connect_timeout=1")
    handler = signal.getsignal(signal.SIGTERM)
    seen: list[Path] = []
    with pytest.raises(SystemExit), o6.scratch() as work:
        seen.append(work)
        (work / "charts").mkdir()
        (work / "charts" / "note.csv").write_text("synthetic", "utf-8")
        os.environ["TB_DB_URL"] = "changed"
        os.kill(os.getpid(), signal.SIGTERM)
    assert not seen[0].exists() and list((tmp_path / "scratch").iterdir()) == []
    assert os.environ["TB_DB_URL"] == "postgresql://127.0.0.1:1/x?connect_timeout=1"
    assert signal.getsignal(signal.SIGTERM) == handler


def test_a_failed_run_files_an_incomplete_record_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import pglocal

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    out = home / "o6" / "record.json"
    monkeypatch.setattr(pglocal, "scratch_root", lambda: tmp_path / "scratch")

    def boom(*_: Any) -> Any:
        with o6.scratch() as work:
            assert not work.is_relative_to(home)
            (work / "lake").mkdir()
            raise KeyboardInterrupt

    monkeypatch.setattr(o6, "run", boom)
    assert o6.main(["--out", str(out)]) == 1
    assert json.loads(out.read_text("utf-8"))["complete"] is False
    assert sorted(p.name for p in out.parent.iterdir()) == ["record.json"]
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert list((tmp_path / "scratch").iterdir()) == []


# ---------------------------------------------------------------------------------------- a small run
@pytest.fixture(scope="module")
def small_run(pg_cluster_url: str, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    with pytest.MonkeyPatch.context() as mp:  # module fixtures run before the per-test TB_DB_URL (D-126)
        mp.setenv("TB_ENV", "DEV")
        mp.setenv("TB_SCRATCH", str(tmp_path_factory.mktemp("o6scratch")))
        mp.setenv("TB_DB_URL", f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=m{os.getpid()}o6_")
        return o6.run("jp-a:JP:300", 42, ["GZQO"])


def test_a_small_japanese_site_is_counted_in_both_arms(small_run: dict[str, Any]) -> None:
    rec = small_run
    assert rec["complete"] and rec["charts"]["note_languages"].keys() == {"ja"}
    small, large = rec["arms"]["rtx5090"], rec["arms"]["rtxpro6000"]
    assert small["judge_calls"] == large["judge_calls"] > 0 and rec["same_questions"]
    assert small["excerpt_budget_tokens"]["max"] < large["excerpt_budget_tokens"]["min"]
    assert rec["a6"]["result"] in ("pass", "fail")
    assert rec["tokenizer"]["true_count"] is False


def test_a_small_context_is_seen_to_cut(pg_cluster_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = o6.arm_contexts

    def tiny(profile: str, doc: Any = None) -> dict[str, dict[str, Any]]:
        got = real(profile, doc)
        if profile == "rtx5090":
            for c in got.values():
                c["context"] = 2048
        return got

    monkeypatch.setattr(o6, "arm_contexts", tiny)
    monkeypatch.setenv("TB_ENV", "DEV")
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setenv(
        "TB_DB_URL", f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=m{os.getpid()}o6t_"
    )
    rec = o6.run("jp-a:JP:300", 42, ["GZQO"])
    assert rec["arms"]["rtx5090"]["truncated_calls"] > rec["arms"]["rtxpro6000"]["truncated_calls"] == 0
    assert rec["a6"]["result"] == "fail"
