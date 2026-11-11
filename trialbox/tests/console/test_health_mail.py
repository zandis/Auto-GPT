"""T-209a (D-379; OPS-027, OPS-032): the health line in the coordinator's morning mail (N2), the administrators'
daily health mail and the console's ``/metrics``, on a frozen clock. Synthetic people and facts only."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from console import notify
from console.auth import User
from console.i18n import CATALOGUES
from console.sitestore import NotifyPerson
from tb_common import metrics

from tests.console.test_console_app import login
from tests.console.test_ops_pages import PW, ob  # noqa: F401 - the fixture is used by name

NOW = datetime(2026, 11, 11, 7, 30, tzinfo=UTC)
DAY = date(2026, 11, 11)  # a Wednesday
CRC = User("crc", "coordinator", "crc1@hospa.test")
ADMIN = User("it", "admin", "it@hospa.test")


def _facts(**over: Any) -> dict[str, Any]:
    f: dict[str, Any] = {
        "at": (NOW - timedelta(minutes=2)).isoformat(),
        "backup": {"level": "ok", "age_hours": 3.0, "problems": []},
        "verified": {"at": (NOW - timedelta(days=5)).isoformat()},
        "disks": [{"path": "/", "used_pct": 40.0}],
        "cert": {"mode": "internal"},
    }
    f.update(over)
    return f


CANARY_OK = {"code": "ok", "ok": True, "at": "2026-11-11T02:10:00"}
CANARY_FAILED = {"code": "failed", "ok": False, "at": "2026-11-11T02:10:00"}


def health(facts: dict[str, Any] | None = None, canary: dict[str, Any] | None = None) -> metrics.Health:
    return metrics.evaluate(facts or _facts(), canary or CANARY_OK, NOW, metrics.Thresholds())


def test_a_failed_canary_sends_the_digest_with_a_red_line_on_an_empty_morning() -> None:
    person = NotifyPerson("crc", None, lang="en")
    assert notify.build_n2(CRC, person, DAY, [], None) is None  # nothing to say, no health: no mail (as before)
    assert notify.build_n2(CRC, person, DAY, [], None, None, health()) is None  # all green: still no mail
    n = notify.build_n2(CRC, person, DAY, [], None, None, health(canary=CANARY_FAILED))
    assert n is not None and n.counts["health_red"] == 1
    lines = n.body.splitlines()
    assert lines[2].startswith("Box health: RED: model self-test failed")  # right under the greeting
    assert "note reading was off last night" in lines[2] and "Tell the administrator" in lines[2]


@pytest.mark.parametrize(
    "facts",
    [
        _facts(backup={"level": "alert", "age_hours": 49.0, "problems": ["the newest good backup is 49 h old"]}),
        _facts(disks=[{"path": "/var/lib/docker", "used_pct": 91.0}]),
        _facts(cert={"mode": "file", "not_after": (NOW + timedelta(days=12)).isoformat()}),
    ],
    ids=["backup-old", "disk-over-85", "cert-within-30-days"],
)
def test_each_red_check_reaches_the_coordinator(facts: dict[str, Any]) -> None:
    n = notify.build_n2(CRC, NotifyPerson("crc", None, lang="en"), DAY, [], None, None, health(facts))
    assert n is not None and "Box health: RED: " in n.body


def test_the_line_is_translated_and_a_green_line_rides_along() -> None:
    rows = [{"pid": "PSEUDO01", "short": "PSEUDO01", "status": "new", "first_at": "2026-11-11T01:00:00+00:00",
             "fit": None, "visit": None, "mark": None}]  # fmt: skip
    n = notify.build_n2(CRC, NotifyPerson("crc", None, lang="ja"), DAY, [("GZQO", rows, {})], None, None, health())
    assert n is not None and n.body.splitlines()[2].startswith("システム状態：すべて正常")
    for lang in ("en", "ja", "zh-TW"):
        for key in ("health.line.ok", "health.line.warn", "health.line.red", "health.subject", "health.why"):
            assert key in CATALOGUES[lang], (lang, key)


def test_the_daily_health_mail_lists_every_check() -> None:
    hl = health(_facts(verified=None), CANARY_FAILED)
    n = notify.build_health(ADMIN, NotifyPerson("it", None, lang="en"), DAY, hl)
    assert n.kind == "HEALTH" and n.subject == "TrialBox health 2026-11-11: RED"
    assert "- [RED] model self-test failed" in n.body
    assert "- [WARN] no backup has been verified" in n.body and "- [ok] backup 3 h old" in n.body
    assert n.counts == {"red": 1, "warn": 1}


class _Store:
    def __init__(self) -> None:
        self.sent: set[tuple[str, str, str]] = set()

    def notify_person(self, username: str) -> NotifyPerson:
        return NotifyPerson(username, None, lang="en")

    def notice_sent(self, kind: str, username: str, day: str) -> bool:
        return (kind, username, day) in self.sent

    def last_notice(self, kind: str, username: str) -> str | None:
        return None


class _Users:
    def users(self) -> list[User]:
        return [ADMIN, CRC, User("pi", "investigator", "pi@hospa.test")]


class _H:
    def __init__(self, hl: metrics.Health | None) -> None:
        self.store, self.users, self.calls = _Store(), _Users(), 0
        self._hl = hl

    def health(self) -> metrics.Health | None:
        self.calls += 1
        return self._hl

    def trials(self, sess: Any) -> list[Any]:
        return []


def test_collect_sends_health_to_admins_and_the_red_line_to_coordinators() -> None:
    h = _H(health(canary=CANARY_FAILED))
    got = notify.collect(h, DAY, ("N1", "N2", "HEALTH"))
    assert [(n.kind, n.username) for n in got] == [("HEALTH", "it"), ("N2", "crc")]
    assert h.calls == 1  # one health for the whole round
    assert [(n.kind, n.username) for n in notify.collect(h, DAY, ("N2",))] == [("N2", "crc")]
    h.store.sent.add(("HEALTH", "it", DAY.isoformat()))
    assert notify.collect(h, DAY, ("HEALTH",)) == []  # once a day
    assert notify.collect(_H(None), DAY, ("N1", "N2", "HEALTH")) == []  # no health: nothing new is sent


# ---------------------------------------------------------------------------------------------- /metrics
def test_metrics_for_the_admin_and_the_scraper_only(
    ob: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    tok = tmp_path / "metrics.token"
    tok.write_text("t" * 64 + "\n", encoding="utf-8")
    monkeypatch.setenv("TB_METRICS_TOKEN_FILE", str(tok))
    anon = TestClient(ob["app"])
    assert anon.get("/metrics", follow_redirects=False).status_code in (303, 401)
    assert anon.get("/metrics", headers={"Authorization": "Bearer " + "x" * 64}).status_code == 401
    r = anon.get("/metrics", headers={"Authorization": "Bearer " + "t" * 64})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert 'tb_health_level{service="console"}' in r.text and 'tb_health_check_level{check="canary"}' in r.text
    assert "tb_disk_used_percent" in r.text  # the inline runner wrote the host facts
    c, _ = login(ob["app"], "coord", PW)
    assert c.get("/metrics").status_code == 403
    admin, _ = login(ob["app"])
    r = admin.get("/metrics")
    assert r.status_code == 200 and "crc" not in r.text and "admin" not in r.text  # no user name in it
