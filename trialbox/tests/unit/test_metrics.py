"""T-209a (D-379; OPS-027, OPS-030, OPS-031, OPS-032, OPS-047): the box's health and its thresholds, on a frozen
clock. The acceptance: the health line is red when the canary failed, the backup is old, a disk is over 85 % or the
certificate ends within 30 days. Synthetic facts only."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import metrics

NOW = datetime(2026, 11, 11, 6, 55, tzinfo=UTC)  # the frozen clock: just before the 07:00 health mail
TH = metrics.Thresholds()  # the defaults, whatever the test machine's environment says


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def green_facts() -> dict[str, Any]:
    return {
        "at": _iso(NOW - timedelta(minutes=1)),
        "backup": {"level": "ok", "age_hours": 2.2, "max_age_hours": 36.0, "problems": []},
        "verified": {"at": _iso(NOW - timedelta(days=12)), "file": "trialbox-hospa-20261030T044500Z.tbbak"},
        "disks": [{"path": "/", "used_pct": 41.0}, {"path": "/mnt/nas", "used_pct": 63.5}],
        "cert": {"mode": "file", "not_after": _iso(NOW + timedelta(days=200))},
    }


CANARY_OK = {"gate": "on", "code": "ok", "ok": True, "at": "2026-11-11T02:10:00", "allows_block": True}


def test_all_green_is_one_ok_line() -> None:
    h = metrics.evaluate(green_facts(), CANARY_OK, NOW, TH)
    assert h.level == "ok", h.as_dict()
    line = h.line()
    assert line.startswith("TrialBox health: OK: ")
    assert "model self-test passed" in line and "backup 2 h old" in line and "fullest disk 64 %" in line
    assert "\n" not in line


@pytest.mark.parametrize(
    ("change", "check", "words"),
    [
        (
            lambda f, c: c.update(ok=False, code="failed", at="2026-11-11T02:10:00"),
            "canary",
            "note reading was off last night",
        ),
        (
            lambda f, c: f.update(
                backup={
                    "level": "alert",
                    "age_hours": 50.0,
                    "problems": ["the newest good backup is 50 h old (limit 36 h)"],
                }
            ),
            "backup",
            "50 h old",
        ),
        (
            lambda f, c: f["disks"].append({"path": "/var/lib/docker", "used_pct": 86.0}),
            "disk:/var/lib/docker",
            "86 % full",
        ),
        (
            lambda f, c: f.update(cert={"mode": "file", "not_after": _iso(NOW + timedelta(days=29))}),
            "certificate",
            "ends in 29 days",
        ),
        (lambda f, c: f.update(verified={"at": _iso(NOW - timedelta(days=101))}), "backup_verified", "101 days ago"),
    ],
    ids=["canary-failed", "backup-old", "disk-over-85", "cert-within-30-days", "verified-over-100-days"],
)
def test_each_threshold_turns_the_line_red(change: Any, check: str, words: str) -> None:
    facts, canary = green_facts(), dict(CANARY_OK)
    change(facts, canary)
    h = metrics.evaluate(facts, canary, NOW, TH)
    assert h.level == "red"
    assert [c.name for c in h.worst()] == [check]
    assert h.line().startswith("TrialBox health: RED: ") and words in h.line()


def test_the_edges_of_the_thresholds() -> None:
    def level(**kw: Any) -> str:
        f = green_facts()
        f.update(kw)
        return metrics.evaluate(f, CANARY_OK, NOW, TH).level

    assert level(disks=[{"path": "/", "used_pct": 85.0}]) == "warn"  # "over 85 %": 85 itself is not red
    assert level(disks=[{"path": "/", "used_pct": 85.1}]) == "red"
    assert level(disks=[{"path": "/", "used_pct": 70.5}]) == "warn"
    assert level(cert={"mode": "file", "not_after": _iso(NOW + timedelta(days=30))}) == "red"  # "within 30 days"
    assert level(cert={"mode": "file", "not_after": _iso(NOW + timedelta(days=31))}) == "warn"
    assert level(cert={"mode": "file", "not_after": _iso(NOW - timedelta(days=1))}) == "red"
    assert level(cert={"mode": "internal"}) == "ok"  # Caddy renews its own
    assert level(verified={"at": _iso(NOW - timedelta(days=95))}) == "warn"
    assert level(verified=None) == "warn"  # never verified: warn, not silent
    assert level(backup={"level": "ok", "age_hours": 36.5, "problems": []}) == "red"  # old even if not alerted yet


def test_the_clock_moves_a_check_from_green_to_red() -> None:
    """The same facts, read 100 days later (frozen clock moved): the key check and the facts are now too old."""
    facts = green_facts()
    later = NOW + timedelta(days=89)
    assert metrics.evaluate(facts, CANARY_OK, NOW, TH).level == "ok"
    h = metrics.evaluate(facts, CANARY_OK, later, TH)
    v = next(c for c in h.checks if c.name == "backup_verified")
    assert v.level == "red" and h.level == "red"
    assert any(c.name == "facts" and c.level == "red" for c in h.checks)  # NEW-OPS-8 (D-561): old facts are red


@pytest.mark.parametrize(
    ("canary", "level"),
    [
        (None, "warn"),  # the orchestrator did not answer
        ({"code": "none", "ok": None}, "warn"),
        ({"code": "stale", "ok": True}, "warn"),
        ({"code": "wake", "ok": True}, "red"),
        ({"code": "off", "ok": None}, "ok"),  # a DEV box with the gate off and no canary
        ({"code": "off", "ok": False}, "red"),  # gate off, but the canary that ran failed
    ],
)
def test_canary_states(canary: dict[str, Any] | None, level: str) -> None:
    assert metrics.check_canary(canary).level == level


def test_missing_host_facts_are_red_and_never_raise() -> None:
    h = metrics.evaluate(None, CANARY_OK, NOW, TH)
    assert h.level == "red"  # NEW-OPS-8 (D-561, OPS-009): a runner that never ran is not a warning that never ends
    assert {c.name for c in h.checks} >= {"backup", "backup_verified", "facts"}


def test_thresholds_from_the_environment() -> None:
    th = metrics.Thresholds.from_env({"TB_HEALTH_DISK_RED": "90", "TB_HEALTH_CERT_RED_DAYS": "14",
                                      "TB_HEALTH_VERIFIED_DAYS": "120", "TB_HEALTH_DISK_WARN": "nan"})  # fmt: skip
    assert (th.disk_red_pct, th.cert_red_days, th.verified_red_days, th.verified_warn_days) == (90, 14, 120, 110)
    assert th.disk_warn_pct == 70.0  # a bad value keeps the default
    f = green_facts()
    f["disks"] = [{"path": "/", "used_pct": 88.0}]
    assert metrics.evaluate(f, CANARY_OK, NOW, th).level == "warn"


def test_prometheus_text() -> None:
    f = green_facts()
    f["disks"].append({"path": '/odd"path', "used_pct": 90.0})
    text = metrics.prometheus(metrics.evaluate(f, CANARY_OK, NOW, TH), "console")
    assert 'tb_health_level{service="console"} 2' in text
    assert 'tb_health_check_level{check="canary"} 0' in text
    assert 'tb_disk_used_percent{path="/odd\\"path"} 90' in text
    assert "tb_certificate_days_left 200" in text and "tb_canary_ok 1" in text
    assert "tb_backup_age_hours 2.2" in text and "tb_backup_verified_age_days 12" in text
    for line in text.splitlines():  # every sample line is "name{labels} value"
        if not line.startswith("#"):
            float(line.rsplit(" ", 1)[1])


def _self_signed(path: Path, not_after: datetime) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "trialbox.hospa.test")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(not_after - timedelta(days=365)).not_valid_after(not_after)
            .sign(key, hashes.SHA256()))  # fmt: skip
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))  # the certificate only; the key is discarded


def test_host_facts_read_the_box(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    crt = tmp_path / "site.crt"
    end = (NOW + timedelta(days=20)).replace(microsecond=0)
    _self_signed(crt, end)
    env = {"TB_TLS_MODE": "file", "TB_TLS_CERT_FILE": str(crt), "TB_BACKUP_TARGETS": str(tmp_path)}
    metrics.record_verified(deploy, {"file": "trialbox-hospa-x.tbbak", "sha256": "a" * 64, "site": "hospa"}, NOW)
    assert os.stat(deploy / "site" / metrics.VERIFIED_FILE).st_mode & 0o777 == 0o600
    backup = {"level": "ok", "age_hours": 3.0, "problems": [], "targets": [{"path": "/x"}]}
    facts = metrics.host_facts(deploy, env, backup, NOW)
    json.dumps(facts)  # what the runner writes into status.json
    assert facts["cert"] == {"mode": "file", "not_after": end.isoformat()}
    assert facts["verified"]["at"] == _iso(NOW) and facts["verified"]["sha256"] == "a" * 64
    assert "targets" not in facts["backup"]
    assert facts["disks"] and all(0 <= d["used_pct"] <= 100 for d in facts["disks"])
    assert len({d["path"] for d in facts["disks"]}) == len(facts["disks"])
    h = metrics.evaluate(facts, CANARY_OK, NOW, TH)
    assert next(c for c in h.checks if c.name == "certificate").level == "red"  # 20 days left


def test_an_unreadable_certificate_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "site.crt"
    bad.write_text("not a certificate", encoding="utf-8")
    facts = metrics.cert_facts({"TB_TLS_MODE": "file", "TB_TLS_CERT_FILE": str(bad)})
    assert "not readable" in facts["error"]
    assert metrics.check_cert(facts, NOW, TH).level == "warn"
    assert metrics.cert_facts({"TB_TLS_MODE": "file"})["error"] == "TB_TLS_CERT_FILE is not set"


def test_the_ops_runner_writes_the_health_facts(tmp_path: Path) -> None:
    from tools.trialbox import ops as tb_ops

    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    box = tb_ops.Box.local(deploy, {"TB_ENV": "DEV", "TB_BACKUP_TARGETS": str(tmp_path / "nas")})
    facts = tb_ops.health_facts(box)
    assert set(facts) >= {"at", "backup", "verified", "disks", "cert"}
    assert facts["backup"]["level"] == "alert"  # no good backup on the target yet: T-117b's own status says so
    st = tb_ops.snapshot(box)
    assert st["health"]["cert"] == {"mode": "internal"}


def test_the_metrics_token_is_made_once_and_not_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tools.trialbox import ops as tb_ops

    deploy = tmp_path / "deploy"
    assert tb_ops.main("metrics-token", deploy, None, True, 0) == 0
    f = deploy / "secrets" / "metrics.token"
    tok = f.read_text(encoding="utf-8").strip()
    assert len(tok) == 64 and tok not in capsys.readouterr().out
    assert os.stat(deploy / "secrets").st_mode & 0o777 == 0o700
    tb_ops.metrics_token(deploy)
    assert f.read_text(encoding="utf-8").strip() == tok  # a second run keeps it


def test_the_orchestrator_metrics_carry_a_failed_canary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OPS-032: a failed canary on the orchestrator's own /metrics (behind its service token on a real box)."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from orchestrator import app as orch_app
    from orchestrator import canary_gate

    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setenv("TB_CANARY_AT_START", "0")
    monkeypatch.setenv("TB_ENV", "TEST")  # no service token on a test box (D-114)
    (tmp_path / "selftest.json").write_text(json.dumps({"ok": False, "at": "2026-11-11T02:10:00",
                                                        "at_epoch": 1.0, "problems": ["synthetic"]}))  # fmt: skip
    canary_gate.GATE.path = None
    fake = SimpleNamespace(services=SimpleNamespace(llm=None, verifier=None, lake=None), data_dir=tmp_path, audit=None)
    monkeypatch.setattr(orch_app, "_orch", fake)
    try:
        r = TestClient(orch_app.app).get("/metrics")
    finally:
        canary_gate.GATE.path = None
    assert r.status_code == 200
    assert 'tb_health_level{service="orchestrator"} 2' in r.text and "tb_canary_ok 0" in r.text
