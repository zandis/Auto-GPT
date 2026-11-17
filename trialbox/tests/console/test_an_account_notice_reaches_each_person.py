"""NOTICE-ACCOUNT (D-879, the review): D-719's account notice goes to each person in a mail of their own.

The notice goes to every steward (a disabled one too) and the PI of each of the account's studies. A notice takes at
most five recipients, so one mail for all of them was refused once there were six; and an address the orchestrator
refuses (not the hospital's) refused everyone's. Each person now gets a mail of their own, and a refused address
loses only its own, counted in the audit event. Synthetic accounts only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.console.test_identity import Clock, _app


def _box(tmp_path: Path, stewards: int) -> tuple[Any, Any]:
    app, users, _audit = _app(tmp_path, Clock())
    for i in range(stewards):
        users.create(f"stew{i}", "steward", "steward-password-0001", f"stew{i}@hospa.test")
    users.create("crc1", "coordinator", "crc-own-password-0001", "crc1@hospa.test")
    return app, app.state.test_backend


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    return [e for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for line in f.read_text().splitlines()
            if (e := json.loads(line)).get("event") == "console.account_notice"]  # fmt: skip


def test_six_stewards_get_six_mails(tmp_path: Path) -> None:
    app, bk = _box(tmp_path, 6)
    app.state.account_rules.tell_people("crc1", "password", "admin", "")
    sent = [n for n in bk.notices if n[0] == "ACCOUNT"]
    assert sorted(to[0] for _k, to, _s, _b in sent) == [f"stew{i}@hospa.test" for i in range(6)]
    assert all(len(to) == 1 for _k, to, _s, _b in sent)  # one person per mail
    assert _events(tmp_path)[-1]["detail"] == {"user": "crc1", "sent": 6}


def test_a_refused_address_loses_only_its_own_mail(tmp_path: Path) -> None:
    app, bk = _box(tmp_path, 3)
    real = bk.send_notice

    def send(kind: str, to: list[str], subject: str, body: str, by: str) -> str:
        if to == ["stew1@hospa.test"]:
            raise RuntimeError("notices go to hospital addresses only")
        return str(real(kind, to, subject, body, by))

    bk.send_notice = send
    app.state.account_rules.tell_people("crc1", "password", "admin", "")
    assert sorted(to[0] for k, to, _s, _b in bk.notices if k == "ACCOUNT") == ["stew0@hospa.test", "stew2@hospa.test"]
    assert _events(tmp_path)[-1]["detail"] == {"user": "crc1", "sent": 2, "failed": 1, "error": "RuntimeError"}
