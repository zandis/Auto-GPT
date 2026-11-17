"""T-721 (D-488; trust review F10, TR-10): the audit says who wrote it.

The journal records the database role that sent each event. The drain now reads it: an event whose family is not
one its sending role writes, or whose own time is far from the time the journal received it, is marked in the chain
record it is written in. The table of who writes what (``audit_writer.ROLE_EVENTS``) is held against the code, so a
service that starts to write a new family fails here until its row has it (a missing row would mark honest events).
"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit_writer as aw
from tb_common.audit import verify

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "services"
#: the folder of each service that has a database role of its own (D-378)
ROLE_OF = {"console": "tb_console", "orchestrator": "tb_orchestrator", "mail_gateway": "tb_mail_gateway",
           "gateway": "tb_gateway", "lake": "tb_lake", "adapter": "tb_adapter",
           "criteria_compiler": "tb_criteria_compiler"}  # fmt: skip
HOST_ONLY = {"backup", "ops", "update"}  # written by the host's `trialbox` tools (the administrator's role)
WRITE = re.compile(r"""\.append\(\s*f?["']([a-z_]+)\.[a-z_.{}]+["']""")
HOSTS = ("tb_console", "tb_orchestrator")  # they import the shared libraries and helpers of each other


def _modules() -> dict[str, Path]:
    out = {}
    for f in SERVICES.rglob("*.py"):
        rel = f.relative_to(SERVICES).with_suffix("")
        out[".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)] = f
    return out


def _imports(f: Path, mods: dict[str, Path], nested: bool = True) -> set[str]:
    """The modules of ``services/`` a file imports. ``nested=False``: at module level only, which is what runs when
    the module is loaded; an import inside a function runs only when that function is called."""
    tree = ast.parse(f.read_text(encoding="utf-8"))
    named: set[str] = set()
    for n in ast.walk(tree) if nested else _module_level(tree):
        if isinstance(n, ast.Import):
            named |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            named |= {n.module, *(f"{n.module}.{a.name}" for a in n.names)}
    return {".".join(m.split(".")[:i]) for m in named for i in range(1, m.count(".") + 2)} & set(mods)


def _module_level(tree: ast.Module) -> list[ast.stmt]:
    """The statements that run at import: the module's body, and what sits in its ``if`` / ``try`` blocks."""
    out: list[ast.stmt] = []
    todo = list(tree.body)
    while todo:
        n = todo.pop()
        out.append(n)
        if isinstance(n, (ast.If, ast.Try, ast.With)):
            todo += [*n.body, *getattr(n, "orelse", []), *getattr(n, "finalbody", []),
                     *(s for h in getattr(n, "handlers", []) for s in h.body)]  # fmt: skip
    return out


def _closure(service: str, mods: dict[str, Path]) -> set[str]:
    """Every module of ``services/`` the service's process can run. Its own package's imports are followed wherever
    they stand (a page imports a store inside its function and calls it). In another package only the imports at
    module level are followed: those run when the service loads the module; an import inside a function of another
    package runs only if the service calls that function, which a reading of the text cannot know. Found on train
    4: the console imports ``orchestrator.candidates`` for two constants, and a chain of imports inside the
    orchestrator's own functions led from there to ``orchestrator.app`` and its ``service.route_refused``."""
    seen: set[str] = set()
    todo = {m for m in mods if m == service or m.startswith(service + ".")}
    while todo:
        m = todo.pop()
        seen.add(m)
        own = m == service or m.startswith(service + ".")
        todo |= _imports(mods[m], mods, nested=own) - seen
    return seen


def test_the_closure_follows_what_a_process_runs() -> None:
    mods = _modules()
    console = _closure("console", mods)
    # a module the console's own page imports inside a function is the console's (D-1221: the registry page no
    # longer imports orchestrator.candidates; the language guess of the command field is such an import)
    assert "channels.native.engine" in console
    # NEW-ARCH-3 slice 2 (D-865): the clinical conflicts are the orchestrator's; the console imports none of them
    assert "omop.conflicts" not in console
    # NEW-ARCH-3 (D-761): the night's data operations are the orchestrator's; the console imports none of them
    assert "datacore.dataops" not in console
    # the orchestrator's app, reached only through imports inside the orchestrator's own functions, is not
    assert "orchestrator.app" not in console and "orchestrator.callers" not in console
    assert "orchestrator.callers" in _closure("orchestrator", mods)
    assert aw.foreign("tb_console", "service.route_refused") == "role"  # the console does not send the gate's event


def _written(files: list[Path]) -> set[str]:
    return {fam for f in files for fam in WRITE.findall(f.read_text(encoding="utf-8"))}


def _named(files: list[Path]) -> set[str]:
    """The families of every labelled event name written out anywhere in ``files`` (an event sent through a helper
    is not an ``append("...")`` call; in an edge service's own folder a labelled name is an event it sends)."""
    from console.i18n_audit import EVENTS

    out: set[str] = set()
    for f in files:
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in EVENTS:
                out.add(n.value.split(".")[0])
    return out


def _constants(files: list[Path]) -> set[str]:
    """Review M1: the families of event names held in a module-level constant whose name says it is an event
    (``EVENT_DECIDE = "dataops.decide"``, ``ACK_EVENT = "demo.ack"``): such a name is passed to ``append`` as a
    variable, which the ``append("...")`` pattern never sees."""
    out: set[str] = set()
    for f in files:
        for n in ast.parse(f.read_text(encoding="utf-8")).body:
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                    and re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", n.value.value)
                    and any(isinstance(t, ast.Name) and "EVENT" in t.id for t in n.targets)):  # fmt: skip
                out.add(n.value.value.split(".")[0])
    return out


def _host_tool_events() -> set[str]:
    """Review H1: the events the host's tools send through the orchestrator's container
    (``compose exec -T orchestrator python -c "... open_audit().append(...)"``): the journal records them under the
    orchestrator's role, not the administrator's. Every labelled event name written out in a tool that does so."""
    from console.i18n_audit import EVENTS

    out: set[str] = set()
    for f in [*sorted((ROOT / "tools" / "trialbox").glob("*.py")), ROOT / "deploy" / "install.sh"]:
        text = f.read_text(encoding="utf-8")
        if "open_audit(" not in text or "orchestrator" not in text:
            continue
        out |= {m for m in re.findall(r"""["']([a-z_]+(?:\.[a-z_]+)+)["']""", text) if m in EVENTS}
    return out


def test_the_host_tools_events_are_the_orchestrators() -> None:
    events = _host_tool_events()
    assert {"backup.done", "update.applied", "console.ops"} <= events, sorted(events)  # the scan finds them
    marked = sorted(e for e in events if aw.foreign("tb_orchestrator", e))
    assert marked == [], f"sent through the orchestrator's container and marked on every box: {marked}"
    # an exact event, not its family: the orchestrator does not speak for the console
    assert aw.foreign("tb_orchestrator", "console.user") == "role"
    assert all(why.strip() for row in aw.EXACT_EVENTS.values() for why in row.values())


def test_every_family_a_service_writes_is_in_its_row() -> None:
    mods = _modules()
    for name, role in ROLE_OF.items():
        files = sorted((SERVICES / name).rglob("*.py"))
        own = _written(files) | (set() if role in HOSTS else _named(files))  # the console names others' events to read
        if role in HOSTS:
            own |= _constants([mods[m] for m in _closure(name, mods)])
        assert own <= aw.ROLE_EVENTS[role], f"{role} writes {sorted(own - aw.ROLE_EVENTS[role])} in services/{name}"
        if role in HOSTS:  # everything its process can run
            hosted = _written([mods[m] for m in _closure(name, mods)])
            assert hosted <= aw.ROLE_EVENTS[role], (
                f"{role} hosts code that writes {sorted(hosted - aw.ROLE_EVENTS[role])}"
            )
        else:  # an edge service: exactly its own events, and the named extras
            extra = set(aw.EDGE_EXTRA.get(role, {}))
            assert aw.ROLE_EVENTS[role] == own | extra, f"{role}: the row is not what services/{name} writes"
            assert all(why.strip() for why in aw.EDGE_EXTRA.get(role, {}).values())
    lib = _written(sorted((ROOT / "libs").rglob("*.py")))
    # what tb_common writes for whoever calls it; and the chain's own records, which its writers write themselves
    # (the drain, the file writer, the host's signer) and no service sends (D-718)
    assert lib <= {*aw._SHARED, aw.RESERVED}, lib
    assert all(set(aw._SHARED) <= aw.ROLE_EVENTS[role] for role in HOSTS)


def test_every_labelled_family_has_a_writer_and_the_edge_roles_write_only_their_own() -> None:
    from console.i18n_audit import EVENTS

    labelled = {e.split(".")[0] for e in EVENTS}
    written = set().union(*aw.ROLE_EVENTS.values())
    assert labelled - written - HOST_ONLY == set(), "a labelled event family that no role may write"
    # the services that read outside input hold the narrowest rows: none may speak for the console or the orchestrator
    for role in ("tb_mail_gateway", "tb_gateway", "tb_lake", "tb_adapter", "tb_criteria_compiler"):
        assert not aw.ROLE_EVENTS[role] & {"console", "screen", "registry", "edc", "life", "job", "data", "actor",
                                           "study", "optout", "audit"}, role  # fmt: skip
    assert set(aw.ROLE_EVENTS) == {*ROLE_OF.values(), "tb_audit_writer"}


def test_foreign_and_time() -> None:
    now = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert aw.foreign("tb_orchestrator", "screen.reveal") == "" == aw.foreign("tb_console", "console.reveal_patient")
    assert aw.foreign("tb_mail_gateway", "screen.reveal") == "role" == aw.foreign("tb_gateway", "console.user")
    assert aw.foreign("tb_console", "screen.reveal") == "role"  # the console does not speak for the orchestrator
    assert aw.foreign("tb_somebody", "mail.in") == "unknown role" and aw.foreign("trialbox", "anything.at_all") == ""
    assert aw.flags_of("tb_orchestrator", "screen.reveal", now, now + timedelta(seconds=2)) == []
    assert aw.flags_of("tb_orchestrator", "screen.reveal", now - timedelta(days=7), now) == ["time"]
    assert aw.flags_of("tb_orchestrator", "screen.reveal", now + timedelta(hours=1), now.isoformat()) == ["time"]
    assert aw.flags_of("tb_mail_gateway", "screen.reveal", now - timedelta(days=7), now) == ["role", "time"]
    assert aw.flags_of("tb_orchestrator", "screen.reveal", now, "not a time") == ["time"]


@pytest.mark.parametrize("value", ["inf", "-inf", "nan", "1e400", "abc"])
def test_an_allowance_that_is_not_a_number_of_seconds_is_the_default(monkeypatch: pytest.MonkeyPatch,
                                                                    value: str) -> None:  # fmt: skip
    """Review L1: ``inf`` switched the time mark off without a word."""
    monkeypatch.setenv(aw.SKEW_ENV, value)
    assert aw.max_skew() == 300.0
    now = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert aw.flags_of("tb_orchestrator", "screen.reveal", now - timedelta(days=7), now) == ["time"]


def test_the_allowance_is_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert aw.max_skew() == 300.0
    monkeypatch.setenv(aw.SKEW_ENV, "30")
    assert aw.flags_of("tb_orchestrator", "job.state", now - timedelta(seconds=31), now) == ["time"]
    assert aw.flags_of("tb_orchestrator", "job.state", now - timedelta(seconds=29), now) == []
    monkeypatch.setenv(aw.SKEW_ENV, "nonsense")
    assert aw.max_skew() == 300.0


class _Journal:
    """A stand-in for the journal table's connection: the rows a drain would read, in ``seq`` order."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, q: str, args: tuple[Any, ...] = ()) -> Any:
        if "WHERE seq > %s" in q:
            out: list[tuple[Any, ...]] = [r for r in self.rows if r[0] > args[0]][: args[1]]
        elif "WHERE seq = %s" in q:
            out = [(r[1],) for r in self.rows if r[0] == args[0]]
        else:
            out = []
        return type("R", (), {"fetchall": lambda _s: out, "fetchone": lambda _s: out[0] if out else None})()


def test_the_drain_marks_a_foreign_event_in_the_record_it_writes(tmp_path: Path) -> None:
    """The acceptance: the mail gateway's role sends ``screen.reveal`` under a doctor's name, dated last week."""
    at = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    fields = {"actor": "dr_tanaka", "job_id": "J1", "detail": {"pid": "a" * 32, "found": True}}
    rows = [
        (1, at, "tb_orchestrator", "job.state", at.isoformat(), {"actor": "crc1@hospa.test"}),
        (2, at, "tb_mail_gateway", "screen.reveal", (at - timedelta(days=7)).isoformat(), fields),
        (3, at, "tb_mail_gateway", "mail.in", at.isoformat(), {"actor": "mail"}),
        (4, at, "tb_console", "console.reveal_patient", (at - timedelta(minutes=30)).isoformat(), {"actor": "x"}),
    ]
    chain = tmp_path / "audit"
    drain = aw.Drain("postgresql://x@db/x", chain, "Asia/Taipei", connect=lambda: _Journal(rows))
    drain.open()
    assert drain.step() == 4
    recs = [json.loads(line) for f in sorted(chain.glob("*.jsonl")) for line in f.read_text().splitlines()]
    by_seq = {r["journal"]["seq"]: r for r in recs}
    assert "flag" not in by_seq[1]["journal"] and "flag" not in by_seq[3]["journal"]
    assert by_seq[2]["journal"] == {"seq": 2, "role": "tb_mail_gateway", "at": at.isoformat(), "flag": ["role", "time"]}
    assert by_seq[2]["event"] == "screen.reveal" and by_seq[2]["actor"] == "dr_tanaka"  # kept as it was sent
    assert by_seq[4]["journal"]["flag"] == ["time"]  # the console's own family, half an hour off
    assert verify(chain).ok  # the mark is under the chain's hash like every other field
    marked = aw.flagged(chain)
    assert [(m["seq"], m["role"], m["event"], m["flag"]) for m in marked] == [
        (2, "tb_mail_gateway", "screen.reveal", ["role", "time"]),
        (4, "tb_console", "console.reveal_patient", ["time"]),
    ]
    again = aw.Drain("postgresql://x@db/x", chain, "Asia/Taipei", connect=lambda: _Journal(rows))
    again.open()  # a restart reads where it stands from the chain: a marked record is a drained record
    assert again.cursor is not None and again.cursor.seq == 4 and again.step() == 0


def test_audit_verify_lists_the_marked_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tools import audit_verify

    at = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    rows = [(1, at, "tb_gateway", "console.user", at.isoformat(), {"actor": "console:bootstrap"})]
    chain = tmp_path / "audit"
    d = aw.Drain("postgresql://x@db/x", chain, "Asia/Taipei", connect=lambda: _Journal(rows))
    d.open()
    d.step()
    assert audit_verify.main([str(chain), "--foreign"]) == 1
    out = capsys.readouterr().out
    assert "1 audit events are marked" in out and "journal 1 from tb_gateway: console.user" in out and "role" in out
    assert audit_verify.main([str(chain), "--foreign", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["flagged"][0]["flag"] == ["role"]
    clean = tmp_path / "clean"
    d2 = aw.Drain("postgresql://x@db/x", clean, "Asia/Taipei",
                  connect=lambda: _Journal([(1, at, "tb_gateway", "llm.call", at.isoformat(), {})]))  # fmt: skip
    d2.open()
    d2.step()
    assert audit_verify.main([str(clean), "--foreign"]) == 0
