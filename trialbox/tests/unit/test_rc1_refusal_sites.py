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
from tb_common.audit import AuditLog

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


@pytest.mark.parametrize(("box", "caller"), [("PRODUCTION", "DEV"), ("DEV", "PRODUCTION"), ("", "DEV"),
                                             ("PILOT", "TEST")])  # fmt: skip
def test_a_support_export_asks_with_the_stricter_of_the_box_and_its_caller(
    box: str, caller: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review of R22-34: ``TB_ENV=DEV trialbox support-bundle`` on a PRODUCTION box is refused, and so is a box
    whose ``deploy/.env`` writes no ``TB_ENV`` (PRODUCTION by the one rule) whatever its caller says."""
    from tools import support_bundle as sb

    deploy = _deploy(tmp_path, box)
    monkeypatch.setenv("TB_ENV", caller)
    with pytest.raises(sb.BundleRefused) as got:
        sb.build(deploy, tmp_path / "usb", commands=False, say=lambda _: None)
    assert str(got.value) == _said("rc1.support_exports", box if box != "DEV" else caller)
    assert not (tmp_path / "usb").exists()


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
    r.box.env = {**{k: v for k, v in ENV.items() if k != "TB_ENV"}, **({"TB_ENV": env} if env else {})}  # its .env
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


def test_an_unattended_update_asks_with_the_callers_stricter_tb_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M13: the runner's own TB_ENV counts too: a DEV box's file and a PRODUCTION caller are refused."""
    from tests.unit.test_ops_update_in_the_quiet_hour import ENV, Runner

    monkeypatch.setenv("TB_ENV", "PRODUCTION")

    class Box(Runner):
        def audit(self, res: Any) -> None:
            return None

    r = Box(tmp_path)
    r.box.env = {**ENV, "TB_ENV": "DEV"}
    quiet = r.ops.submit("update_apply", "admin:owner", {"bundle": "trialbox-2026.11-2.tar", "when": "quiet"})
    (res,) = r.run_pending()
    assert res["id"] == quiet and not res["ok"] and r.applied == []
    assert res["lines"] == ["rc1.unattended_updates: PRODUCTION"]


# ---------------------------------------------------------------------------------------------- key ceremonies
def _KEY_COMMANDS(tmp: Path) -> list[list[str]]:
    """``tools.keys``'s ceremony commands (its ``init`` is not one: it stays allowed), on a bare folder."""
    sec = ["--secrets", str(tmp / "sec")]
    return [["rotate-kek", *sec, "--backend", "file", "--audit-dir", str(tmp / "audit")],
            ["ceremony-record", *sec, "--deploy", str(tmp / "deploy-k"), "--audit-dir", str(tmp / "audit")],
            ["escrow-shares", *sec, "--escrow-out", str(tmp / "media"), "--audit-dir", str(tmp / "audit")],
            ["restic-key", *sec],
            ["rotate", "pid_map", *sec]]  # fmt: skip


@pytest.mark.parametrize("env", ENVS)
def test_no_key_ceremony_on_a_production_box(
    env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ceremony (its checks, as root) and ``trialbox backup-keygen`` (the command's entry; the library function
    ``keygen`` the drills use is not refused)."""
    from tools import backup_key_ceremony as bkc
    from tools.keys import main as keys_main
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
        for argv in _KEY_COMMANDS(tmp_path):
            assert keys_main(argv, env={"TB_ENV": env} if env else {}) == 1, argv
            assert capsys.readouterr().err.strip() == "keys: " + _said("rc1.key_ceremonies", env), argv
        assert not (tmp_path / "sec").exists() and not (tmp_path / "media").exists()  # nothing made
    else:
        assert got.value.text is bkc.SAME_PERSON and passed == ["operator"]
        assert trialbox_main(["backup-keygen", "--private", str(priv), "--public", str(pub)]) == 0
        assert priv.is_file() and pub.is_file()
        for argv in _KEY_COMMANDS(tmp_path):  # past the refusal: each stops later, on this bare folder, for its own
            keys_main(argv, env={"TB_ENV": env})  # reason (no KEK, no custodian), never with rc1's words
            assert "rc1" not in capsys.readouterr().err, argv


# ---------------------------------------------------------------------------------------------- the MVP walk
def test_the_mvp_walk_is_not_refused_on_a_validation_box(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The integrator's ruling: the MVP walk runs on a VALIDATION rehearsal box, and no step of it meets an rc1
    refusal (D-1072: VALIDATION is allowed)."""
    import ast

    from orchestrator.scheduler import require_open, require_released

    from tools import backup_key_ceremony as bkc
    from tools.trialbox.__main__ import main as trialbox_main

    monkeypatch.setenv("TB_ENV", "VALIDATION")
    validation = {"TB_ENV": "VALIDATION"}
    for r in rc1_refusals.REFUSALS:  # every row
        rc1_refusals.check(r.name, validation)
        assert not rc1_refusals.refused(r.name)
    # step 1, the install: the backup key pair and the ceremony's own checks
    priv, pub = tmp_path / "it" / "backup.key", tmp_path / "box" / "backup.pub"
    assert trialbox_main(["backup-keygen", "--private", str(priv), "--public", str(pub)]) == 0 and pub.is_file()
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    with pytest.raises(bkc.Stop) as got:
        bkc.run(tmp_path / "stick", "operator", "operator", validation)  # past rc1, the ceremony's own next check
    assert got.value.text is bkc.SAME_PERSON and "rc1" not in capsys.readouterr().err
    # step 5, a screening night: the first step of SCREEN and MICROBATCH (require_open asks require_released)
    monkeypatch.delenv("TB_DB_URL", raising=False)  # a bare stack: no restore hold, the study open
    require_released()
    require_open("GZQO")
    monkeypatch.setenv("TB_DB_URL", db_url)
    # step 6, the console, with real pages: the week's list (page and API), one patient, the screening log, a file
    from console.app import create_app
    from console.auth import UserStore

    from tests.console.test_console_app import PILOT_ENV, FakeBackend, _done_screen, _ulid, login_totp

    backend = FakeBackend()
    backend.audit_dir = tmp_path / "console-audit"
    users = UserStore()
    pw = "mvp-walk-password-0001"
    users.create("admin", "admin", pw, "admin@hospa.test")
    users.create("stw", "steward", pw, "stw@hospa.test")
    users.create("drsato", "investigator", pw, "drsato@hospa.test")
    app = create_app({**PILOT_ENV, **validation, "TB_CONSOLE_DIR": str(tmp_path / "console")}, backend=backend,
                     audit=AuditLog(backend.audit_dir), users=users)  # fmt: skip
    job = _done_screen(backend, _ulid(951))
    stw, csrf = login_totp(app, "stw", pw)  # VALIDATION: the second factor, as on a box
    r = stw.post("/studies/GZQO/team", data={"csrf": csrf, "username": "drsato", "role": "pi", "start": "2026-01-01",
                                             "training_day": "2025-06-01"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]  # D-380: the steward names the PI
    pi, _ = login_totp(app, "drsato", pw)
    listed = "a" * 32
    files = [o.filename for o in job.outputs or [] if o.tag == "aggregate"]
    walk = [
        "/studies/GZQO/week",
        f"/studies/GZQO/patients/{listed}",
        "/studies/GZQO/screening-log",
        f"/pilot/jobs/{job.job_id}",
        f"/pilot/jobs/{job.job_id}/files/{files[0]}",
    ]
    for path in walk:
        r = pi.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[-300:])  # every page answers
        assert "rc1" not in r.text, path
    assert "row-aaaaaaaa" in pi.get("/studies/GZQO/week").text  # the list itself, not a page about it
    assert app.state.rc1_guard.refusal_of("GET", "/api/v1/studies/GZQO/patients") is None  # the week's API too
    # step 7, the audit: the steward (audit.browse) reads one patient's log (refused on PRODUCTION, R2234-14)
    for path in (f"/audit?pid={listed}", "/audit"):
        r = stw.get(path)
        assert r.status_code == 200 and "rc1" not in r.text, (path, r.status_code, r.text[-300:])
    # step 8, the scheduled backup and its restore: nothing there asks the table
    sites = {s.partition(":")[0] for r in rc1_refusals.REFUSALS for s in r.sites}
    backup = ("tools.trialbox.backup", "tools.trialbox.backup_schedule", "tools.trialbox.restore_drill")
    assert not sites & set(backup)
    root = Path(__file__).resolve().parents[2]
    for mod in backup:
        tree = ast.parse((root / Path(*mod.split("."))).with_suffix(".py").read_text(encoding="utf-8"))
        assert "rc1_refusals" not in ast.unparse(tree), mod  # no import, no call
