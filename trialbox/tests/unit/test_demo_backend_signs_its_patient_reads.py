"""NEW-SEC-1 (D-717), train 15's e2e-simple: the in-process demo backend (``tools/role_demo.InprocBackend``) signs a
patient read the way the console's real backend does (``console.actor.read_headers``), so the orchestrator's check
on ``GET /registry/{ruleset}`` holds in the demo as on a box; the demo's weekly list (built with no session, as the
morning mail is) reads as the mail's principal. The check is not weakened."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from console import actor
from tb_common import actor_v3


class _Client:
    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, str]]] = []

    def get(self, path: str, headers: dict[str, str] | None = None) -> Any:
        self.seen.append((path, dict(headers or {})))

        class R:
            status_code = 200

            @staticmethod
            def json() -> list[Any]:
                return []

        return R()


def _backend(client: _Client) -> Any:
    from tools.role_demo import InprocBackend

    box = type("Box", (), {"orch": type("O", (), {"cfg": None})()})()
    return InprocBackend(box, client, Path("."))


def test_the_demo_backend_signs_a_registry_read_as_the_reader_bound() -> None:
    client = _Client()
    with actor.reading_as(actor.NOTIFY):
        _backend(client).registry_rows("GZQO")
    path, headers = client.seen[-1]
    claim = actor_v3.verify(headers[actor_v3.HEADER])
    assert path == "/registry/GZQO" and claim.sub == actor.NOTIFY and claim.action == "phi.view"


def test_a_read_that_is_no_patient_read_carries_nothing() -> None:
    client = _Client()
    _backend(client).registry_summaries()  # counts, not a patient read: nothing to sign
    assert actor_v3.HEADER not in client.seen[-1][1]


def test_the_tools_build_the_weekly_list_as_the_mail_reads_it() -> None:
    """No tool builds the weekly list with no reader: each asks ``h.mail_week``, signed as the mail's principal."""
    tools = Path(__file__).resolve().parents[2] / "tools"
    bare = [f.name for f in tools.glob("*.py") if "week_bundle(None" in f.read_text(encoding="utf-8")]
    assert bare == []
    home = (Path(__file__).resolve().parents[2] / "services" / "console" / "home.py").read_text(encoding="utf-8")
    assert "with console_actor.reading_as(console_actor.NOTIFY):\n            return week_bundle(None, rs)" in home


def test_a_drills_own_read_is_signed_for_the_demo_coordinator_on_the_routes_study() -> None:
    client = _Client()
    _backend(client).registry_rows("GZQO")  # nobody bound: a drill's own read
    claim = actor_v3.verify(client.seen[-1][1][actor_v3.HEADER])
    assert (claim.sub, claim.role, claim.study, claim.action) == ("console:crc1", "coordinator", "GZQO", "phi.view")
