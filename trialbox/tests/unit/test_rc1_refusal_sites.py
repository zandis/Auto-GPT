"""rc1's refusals at their command-line and service sites (the owner's ruling of 2026-11-20; review R22-34).

One test per row of ``tb_common.rc1_refusals.REFUSALS`` that is not the console's (those are in
``tests/console/test_rc1_guard.py``): on a box with ``TB_ENV`` unset, PRODUCTION or unknown nothing is written, exported,
applied or generated and the row's message is what the person reads; on DEV and TEST the site's guard lets the action
through (VALIDATION too, D-1072). Where an audit writer is reachable at the site, its event is checked. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tb_common import rc1_refusals

ENVS = ("", "PRODUCTION", "PILOT", "DEV", "TEST", "VALIDATION")


def _env(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)


def _refused(env: str) -> bool:
    return env not in rc1_refusals.ALLOWED


def _said(key: str, env: str, lang: str = "en") -> str:
    return rc1_refusals.text(key, lang, environment=env or "PRODUCTION")


# ---------------------------------------------------------------------------------------------- EDC writes
class _Source:
    """A source that records what is pushed to it (an EDC stand-in)."""

    name = "redcap"

    def __init__(self) -> None:
        self.pushed: list[Any] = []

    def fields(self) -> list[str]:
        return ["consent_date"]

    def pull(self) -> list[Any]:
        return []

    def push(self, rows: list[Any]) -> dict[str, str]:
        self.pushed += rows
        return {r.record: f"rc-{r.record}" for r in rows}


@pytest.mark.parametrize("env", ENVS)
def test_no_edc_write_from_screening_on_a_production_box(
    env: str, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore.rc1_refused import EdcWriteRefused
    from datacore.sync import enter, sync
    from rc_bridge.client import RcError

    from tests.unit.test_datacore import AT, core

    dc = core(tmp_path)
    enter(dc, "GZQO", "GZQO-0001", "", {"consent_date": "2026-11-01"}, "crc", AT)  # a person's own entry: allowed
    src = _Source()
    _env(monkeypatch, env)
    if _refused(env):
        with pytest.raises(RcError) as got:  # the bridge's error: a REDCap read that writes back keeps its read
            sync(dc, "GZQO", src, "sync", AT)
        assert isinstance(got.value, EdcWriteRefused) and got.value.refused and got.value.status == 403
        assert got.value.key == "rc1.edc_writes_from_screening" and got.value.code == "RC-RC1"
        assert got.value.environment == (env or "PRODUCTION") and src.pushed == []  # nothing reached the EDC
        assert got.value.message == _said("rc1.edc_writes_from_screening", env)
    else:
        res = sync(dc, "GZQO", src, "sync", AT)
        assert [r.record for r in src.pushed] == ["GZQO-0001"] and res.created == {"GZQO-0001": "rc-GZQO-0001"}


# ---------------------------------------------------------------------------------------------- support exports
def _deploy(tmp_path: Path, tb_env: str) -> Path:
    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / ".env").write_text(f"TB_TZ=Asia/Taipei\nTB_LOG_DIR={tmp_path / 'logs'}\n"
                                 + (f"TB_ENV={tb_env}\n" if tb_env else ""), encoding="utf-8")  # fmt: skip
    (deploy / "settings.yaml").write_text('mrn_regex: "^\\\\d{8}$"\n', encoding="utf-8")
    return deploy


@pytest.mark.parametrize("env", ENVS)
def test_no_support_export_on_a_production_box(
    env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The box's environment is its ``deploy/.env`` (the host's shell sets no ``TB_ENV``)."""
    from tools import support_bundle as sb

    for k in ("TB_ENV", "TB_LOG_DIR", "TB_AUDIT_HOST_DIR"):
        monkeypatch.delenv(k, raising=False)
    deploy = _deploy(tmp_path, env)
    usb = tmp_path / "usb"
    if _refused(env):
        with pytest.raises(sb.BundleRefused) as got:
            sb.build(deploy, usb, commands=False, say=lambda _: None)
        assert str(got.value) == _said("rc1.support_exports", env)
        assert not usb.exists()  # nothing written
        assert sb.main(["--out", str(usb), "--deploy", str(deploy), "--no-commands"]) == 2
        assert "rc1 makes no support bundle" in capsys.readouterr().err and not usb.exists()
    else:
        out = sb.build(deploy, usb, commands=False, say=lambda _: None)
        assert out.is_file() and out.parent == usb


def test_a_support_export_asks_with_the_callers_tb_env_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process that sets ``TB_ENV`` itself (a test box's shell) is that environment, as the key ceremony reads."""
    from tools import support_bundle as sb

    deploy = _deploy(tmp_path, "DEV")
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    with pytest.raises(sb.BundleRefused):
        sb.build(deploy, tmp_path / "usb", commands=False, say=lambda _: None)


# ---------------------------------------------------------------------------------------------- unattended updates
@pytest.mark.parametrize("env", ENVS)
def test_no_unattended_update_on_a_production_box(env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_ops_update_in_the_quiet_hour import ENV, Runner

    monkeypatch.delenv("TB_ENV", raising=False)

    class Box(Runner):
        audited: list[dict[str, Any]]

        def audit(self, res: Any) -> None:  # the console.ops event the compose box sends
            self.audited.append(dict(res))

    r = Box(tmp_path)
    r.audited = []
    r.box.env = {**ENV, **({"TB_ENV": env} if env else {})}  # the box's deploy/.env
    quiet = r.ops.submit("update_apply", "admin:owner", {"bundle": "trialbox-2026.11-2.tar", "when": "quiet"})
    res = r.run_pending()
    assert [x["id"] for x in res] == [quiet]
    if _refused(env):
        assert r.applied == [] and not res[0]["ok"]  # nothing applied
        assert res[0]["summary"] == "refused: " + _said("rc1.unattended_updates", env)
        assert res[0]["lines"] == [f"rc1.unattended_updates: {env or 'PRODUCTION'}"]
        assert [(a["id"], a["ok"]) for a in r.audited] == [(quiet, False)]  # one audited event
        now = r.ops.submit("update_apply", "admin:owner", {"bundle": "trialbox-2026.11-3.tar"})
        assert [x["id"] for x in r.run_pending()] == [now] and len(r.applied) == 1  # a person's update runs now
    else:
        assert res[0]["ok"] and r.applied == [{"bundle": "trialbox-2026.11-2.tar", "when": "quiet"}]


# ---------------------------------------------------------------------------------------------- key ceremonies
@pytest.mark.parametrize("env", ENVS)
def test_no_key_ceremony_on_a_production_box(
    env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ceremony (its checks, as root) and ``trialbox backup-keygen`` (the command's entry; the library function
    ``keygen`` the drills use is not refused)."""
    from tools import backup_key_ceremony as bkc
    from tools.trialbox.__main__ import main as trialbox_main

    _env(monkeypatch, env)
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    passed: list[str] = []

    def person(name: str | None) -> str:  # the ceremony's next check: reached only past the refusal
        passed.append(str(name))
        raise bkc.Stop(bkc.SAME_PERSON)

    monkeypatch.setattr(bkc, "person", person)
    stick = tmp_path / "stick"
    priv, pub = tmp_path / "it" / "backup.key", tmp_path / "box" / "backup.pub"
    with pytest.raises(bkc.Stop) as got:
        bkc.run(stick, "operator", "witness", {"TB_ENV": env} if env else {})
    if _refused(env):
        assert got.value.text is rc1_refusals.TEXTS["rc1.key_ceremonies"] and passed == []
        for lang in rc1_refusals.LANGS:
            assert got.value.say(lang) == _said("rc1.key_ceremonies", env, lang)
        capsys.readouterr()
        assert trialbox_main(["backup-keygen", "--private", str(priv), "--public", str(pub)]) == 1
        assert capsys.readouterr().err.strip() == "backup-keygen: " + _said("rc1.key_ceremonies", env)
        assert not priv.exists() and not pub.exists() and not priv.parent.exists()  # nothing generated
    else:
        assert got.value.text is bkc.SAME_PERSON and passed == ["operator"]
        assert trialbox_main(["backup-keygen", "--private", str(priv), "--public", str(pub)]) == 0
        assert priv.is_file() and pub.is_file()
