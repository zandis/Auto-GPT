"""H-13 (D-1125): every call the GPU driver makes into the orchestrator is made by a service the orchestrator's own
table lets onto that route.

Launch P2 (run box-20261117T041407Z-fae5c1f7) stopped at 07g-gate: the step read ``GET /models`` from the mail
gateway's container, and the orchestrator answers 403 to that caller (``route_callers.yaml``, T-713: ``models_read``
is the console's and the operator's). The rehearsal's stand-in took any token, so nothing caught it before the VM.

This test reads ``deploy/gcp/box-install-run.sh`` for every snippet it runs in a service's container (``in_svc``)
and ``tools/public_accuracy/onbox.py`` for the accuracy set's reads, and holds each call (the service, the method,
the path) against the orchestrator app in process: its real routes, its real table, each service's own token.
Synthetic data only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_orchestrator_callers import _token, box  # noqa: F401  (the fixture: the app, registry tokens)

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "deploy" / "gcp" / "box-install-run.sh"
VM = ROOT / "deploy" / "gcp" / "box_vm.py"
ONBOX = ROOT / "tools" / "public_accuracy" / "onbox.py"
ORCH = "http://orchestrator:8010"

_SNIPPET = re.compile(r"^(d_\w+)\(\) \{ in_svc ([a-z-]+) <<EOF\n(.*?)\nEOF$", re.S | re.M)
_CALL = re.compile(r'httpx\.(get|post|put|delete)\(\s*f?"' + re.escape(ORCH) + r'([^"]*)"')


def driver_calls() -> list[tuple[str, str, str, str]]:
    """(the function, the service whose container runs it, the method, the path) of every HTTP call into the
    orchestrator in the driver's in_svc snippets. A shell argument or an f-string field stands for one path part."""
    out = []
    for name, svc, body in _SNIPPET.findall(DRIVER.read_text(encoding="utf-8")):
        for method, path in _CALL.findall(body):
            out.append((name, svc, method.upper(), re.sub(r"\$\w+|\{[^}]*\}", "X1", path)))
    return out


def onbox_calls() -> list[tuple[str, str, str, str]]:
    """The accuracy set's reads of the orchestrator: every ``_orch_get(path)`` in onbox.py, reached from an onbox
    command directly or through a helper (``_job``), run in the container of the service box_vm.py names for that
    command."""
    text = ONBOX.read_text(encoding="utf-8")
    vm = VM.read_text(encoding="utf-8")
    funcs = dict(re.findall(r"^def (\w+)\(.*?\n(.*?)(?=^def |\Z)", text, re.S | re.M))
    paths: dict[str, set[str]] = {
        f: set(re.findall(r'_orch_get\(f?"([^"]*)"', body)) for f, body in funcs.items() if f != "_orch_get"
    }
    for _ in funcs:  # a helper's reads are its callers' reads
        for f, body in funcs.items():
            for g, got in list(paths.items()):
                if g != f and got and re.search(rf"\b{g}\(", body):
                    paths.setdefault(f, set()).update(got)
    out = []
    for f, got in sorted(paths.items()):
        if not f.startswith("cmd_") or not got:
            continue
        cmd = f[4:]
        svcs = set(re.findall(r'\(\s*"([a-z-]+)",\s*"' + cmd + '"', vm))
        assert svcs, f"onbox {cmd} reads the orchestrator, and box_vm.py runs it in no service this test can name"
        out += [
            (f"onbox {cmd}", s, "GET", re.sub(r"\{[^}]*\}", "X1", path)) for s in sorted(svcs) for path in sorted(got)
        ]
    assert text.count("_orch_get(") - 1 == sum(len(v) for k, v in paths.items() if not k.startswith("cmd_")) + sum(
        1 for k, v in paths.items() if k.startswith("cmd_") for _p in re.findall(r"_orch_get\(", funcs[k])
    ), "a read of the orchestrator in onbox.py this test does not follow"
    return out


CALLS = driver_calls() + onbox_calls()


def test_the_driver_calls_are_found() -> None:
    """The reading itself: the gate's read, the study's read and the screen's start and status are all seen, so a
    snippet written another way cannot leave this test empty."""
    names = {c[0] for c in CALLS}
    assert {"d_gate_read", "d_study_ready", "d_screen_start", "d_screen_status"} <= names, names
    assert any(n.startswith("onbox ") for n in names), names
    # every in_svc snippet that names the orchestrator's address is one this test read a call from
    text = DRIVER.read_text(encoding="utf-8")
    for name, _svc, body in _SNIPPET.findall(text):
        if ORCH in body:
            assert name in names, f"{name} calls the orchestrator in a form this test does not read"
    assert text.count(ORCH) == sum(1 for c in CALLS if c[0].startswith("d_")), (
        "a call into the orchestrator outside in_svc"
    )


@pytest.mark.parametrize("call", CALLS, ids=[f"{c[0]}-{c[1]}-{c[2]}" for c in CALLS])
def test_each_driver_call_is_made_by_a_service_the_route_allows(call: tuple[str, str, str, str]) -> None:
    from orchestrator.app import CALLER_GATE

    name, svc, method, path = call
    key = CALLER_GATE.resolve(method, path)
    assert key is not None, f"{name}: {method} {path} is no route of the orchestrator"
    why = CALLER_GATE.decide(svc, key)
    assert why is None, f"{name} runs in the {svc} container, and the orchestrator refuses it: {why}"


def test_the_gate_is_read_by_a_caller_the_orchestrator_lets_in_and_not_by_the_mail_gateway(box: Any) -> None:  # noqa: F811
    """In process, with each service's own token, as the box runs (PRODUCTION rules, a token registry): the console
    reads ``GET /models``; the mail gateway, which read it on launch P2, gets the 403 that stopped the launch."""
    client, events, _state = box
    gate = next(c for c in CALLS if c[0] == "d_gate_read")
    assert (gate[1], gate[2], gate[3]) == ("console", "GET", "/models")
    r = client.get("/models", headers={"X-TB-Service-Token": _token("mail-gateway")})
    assert r.status_code == 403 and "route_not_allowed" in r.text, r.text
    assert any(e["kind"] == "caller.refused" or "refus" in e["kind"] for e in events), events
    r = client.get("/models", headers={"X-TB-Service-Token": _token(gate[1])})
    assert r.status_code != 403 and "route_not_allowed" not in r.text, (r.status_code, r.text[:200])


def test_the_screens_start_and_read_pass_the_job_rules_for_their_caller() -> None:
    """``POST /jobs`` and ``GET /jobs/{job_id}`` have rules beyond the route: the mail gateway starts only its mail
    commands, as a mailed job, and reads only such a job. The driver's SCREEN carries a message id."""
    from orchestrator.app import CALLER_GATE

    start = next(c for c in CALLS if c[0] == "d_screen_start")
    body = _SNIPPET.search(DRIVER.read_text(encoding="utf-8"))
    text = next(b for n, _s, b in _SNIPPET.findall(DRIVER.read_text(encoding="utf-8")) if n == "d_screen_start")
    assert body is not None and '"type": "SCREEN"' in text and '"message_id"' in text
    assert CALLER_GATE.job_start(start[1], "SCREEN", "crc@hospa.test", "<boxrun-x@trialbox.invalid>") is None
    assert CALLER_GATE.job_start(start[1], "SCREEN", "crc@hospa.test", None) is not None  # the rule is real
    assert CALLER_GATE.job_read(start[1], "<boxrun-x@trialbox.invalid>") is None


def test_the_rehearsals_stand_in_refuses_a_caller_the_table_refuses() -> None:
    """The stand-in that let launch P2's fault through took any token. It now asks the same table."""
    import importlib.util
    import os

    os.environ.setdefault("BR_S", "/nonexistent-br-s")
    spec = importlib.util.spec_from_file_location("h13_box_standin", ROOT / "tests/rehearsal/box-run/standins/box.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.may_call("console", "GET /models") and mod.may_call("operator", "GET /models")
    assert not mod.may_call("mail-gateway", "GET /models")
    assert mod.may_call("mail-gateway", "POST /jobs") and mod.may_call("mail-gateway", "GET /jobs/{job_id}")
    assert mod.may_call("console", "GET /rulesets/{ruleset}") and not mod.may_call("gateway", "GET /models")


def test_a_filter_on_a_set_whose_ids_are_not_known_here_is_refused(tmp_path: Path) -> None:
    """D-1125: sigir's and trec2023's protocols are sampled from source files the VM fetches. With no local cache the
    free listing knew only the prefix and took any id that carried it; the VM then stopped on the filter after the
    install was paid for. A filter that cannot be checked for free is not accepted for free."""
    from tools import box_run

    empty = tmp_path / "no-cache"
    empty.mkdir()
    r = box_run.acc_ids("sigir,tcga", "m3", "sigir:Sm3NCT00000000 tcga:Gm3TCGA-BRCA", cache=empty)
    assert r["sets"]["sigir"]["ids"] is None and r["sets"]["sigir"]["matches"] == []
    assert any(x.startswith("sigir: a filter on this set cannot be checked here") for x in r["refused"]), r["refused"]
    assert r["sets"]["tcga"]["matches"] == ["Gm3TCGA-BRCA"]  # a set of fixed protocols is still checked exactly
    assert not any(x.startswith("tcga") for x in r["refused"])
    # with no filter on it, the unknown set is listed and nothing is refused
    assert box_run.acc_ids("sigir,tcga", "m3", "tcga:Gm3TCGA-BRCA", cache=empty)["refused"] == []
