"""10G-2 (review 16-19, D-1345): the head of the audit chain is signed every hour; an anchor folder whose heads the
box's root could overwrite fails the run; ``doctor`` FAILs a head older than 2 h (a 3-hour-old head fails, a 1-hour-old
one passes), WARNs while a new box has no head yet, and FAILs a head dated more than 2 h ahead of the clock. Time is a
parameter here, never a sleep. Keys are made in the test's own folder; synthetic events only."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import audit
from tb_common.audit import AuditLog

from tools import audit_verify
from tools.trialbox import audit_heads, doctor

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 19, 8, tzinfo=UTC)
SIGNED = datetime(2026, 11, 19, 9, 50, tzinfo=UTC)

pytestmark = pytest.mark.nodb


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", audit.ANCHOR_TARGETS_ENV):
        monkeypatch.delenv(var, raising=False)
    paths = {name: tmp_path / name for name in ("audit", "share", "secrets", "run", "deploy")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setenv("TB_SECRETS_DIR", str(paths["secrets"]))
    monkeypatch.setenv("TB_KEK_FILE", str(paths["run"] / "kek"))
    monkeypatch.setenv("TB_ENV", "DEV")
    assert audit_verify.init_key(paths["secrets"]) == 0
    log = AuditLog(paths["audit"])
    for i in range(3):
        log.append("test.event", ts=T0 + timedelta(minutes=i), actor="tester", detail={"n": i})
    return paths


def _sign(box: dict[str, Path], now: datetime = SIGNED) -> audit_heads.Night:
    night = audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=lambda *_: None, now=now)
    assert night.ok, night.problems
    return night


def _key_made(box: dict[str, Path], at: datetime) -> None:
    os.utime(box["secrets"] / audit.SIGN_PUB_FILE, (at.timestamp(), at.timestamp()))


def _doctor(box: dict[str, Path], now: datetime, env: str = "PRODUCTION") -> doctor.Check:
    e = {"TB_ENV": env, "TB_SECRETS_HOST_DIR": str(box["secrets"]), "TB_AUDIT_HOST_DIR": str(box["audit"]),
         "TB_AUDIT_ANCHOR_TARGETS": str(box["share"])}  # fmt: skip
    return doctor.check_audit_heads(doctor.DoctorInputs(env=e, deploy=box["deploy"]), now=now)


# ------------------------------------------------------------------------------------------------ doctor: the age
def test_the_limit_is_two_hours_by_default() -> None:
    from tb_common.config import DECLARED

    assert doctor.HEAD_MAX_AGE_H == 2.0
    assert float(DECLARED["TB_AUDIT_HEAD_MAX_AGE_H"].default) == doctor.HEAD_MAX_AGE_H


def test_a_three_hour_old_head_fails_and_says_since_when_and_what_to_do(box: dict[str, Path]) -> None:
    _key_made(box, SIGNED - timedelta(days=2))
    _sign(box)
    c = _doctor(box, SIGNED + timedelta(hours=3))
    assert c.status == "FAIL", c.detail
    assert "3 h old, signed 2026-11-19T09:50+00:00 (limit 2 h)" in c.detail
    assert "python3 -m tools.trialbox audit-sign" in c.detail and "trialbox-retention.log" in c.detail
    assert _doctor(box, SIGNED + timedelta(hours=3), env="DEV").status == "WARN"


@pytest.mark.parametrize("after", [timedelta(minutes=1), timedelta(hours=1), timedelta(hours=2)])
def test_a_head_up_to_two_hours_old_passes(box: dict[str, Path], after: timedelta) -> None:
    _key_made(box, SIGNED - timedelta(days=2))
    _sign(box)
    c = _doctor(box, SIGNED + after)
    assert c.status == "PASS", c.detail


def test_a_head_dated_ahead_of_the_clock_fails_beyond_the_limit_only(box: dict[str, Path]) -> None:
    """Clock skew: a head up to 2 h ahead of this box's clock passes; more than that FAILs and names both times."""
    _key_made(box, SIGNED - timedelta(days=2))
    _sign(box)
    assert _doctor(box, SIGNED - timedelta(hours=1)).status == "PASS"
    c = _doctor(box, SIGNED - timedelta(hours=3))
    assert c.status == "FAIL" and "3 h ahead of this box's clock (2026-11-19T06:50+00:00" in c.detail
    assert "timedatectl" in c.detail


def test_no_head_on_a_fresh_box_is_a_warning_in_its_first_two_hours_then_a_failure(box: dict[str, Path]) -> None:
    made = datetime(2026, 11, 19, 9, 5, tzinfo=UTC)
    _key_made(box, made)
    c = _doctor(box, made + timedelta(minutes=40))
    assert c.status == "WARN" and "no signed head" in c.detail and "first hourly run" in c.detail
    c = _doctor(box, made + timedelta(hours=3))
    assert c.status == "FAIL" and "no signed head" in c.detail


# ------------------------------------------------------------------------------------------------ the root's write
def _head(folder: Path, name: str = "20261119T095000+0000-000000000003.json") -> Path:
    (folder / "heads").mkdir(exist_ok=True)
    path = folder / "heads" / name
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_overwritable_names_the_newest_head_only_when_the_account_can_write_it(tmp_path: Path) -> None:
    assert audit_heads.overwritable(tmp_path, lambda _p: True) is None  # no head yet: nothing to show
    _head(tmp_path, "20261119T085000+0000-000000000002.json")
    newest = _head(tmp_path)
    asked: list[Path] = []

    def yes(p: Path) -> bool:
        asked.append(p)
        return True

    assert audit_heads.overwritable(tmp_path, yes) == newest
    assert asked == [newest]
    assert audit_heads.overwritable(tmp_path, lambda _p: False) is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes a read-only file on a local disk: the stand-in needs a user")
def test_on_a_stand_in_a_head_the_account_cannot_write_is_refused_to_it(tmp_path: Path) -> None:
    """The kernel's own answer, not a mode read by hand: a head this account may not write is not "overwritable";
    the same file made writable is. On a box the account is root and the refusal comes from the share or chattr +i."""
    head = _head(tmp_path)
    head.chmod(0o444)
    assert audit_heads.overwritable(tmp_path) is None
    with pytest.raises(PermissionError):
        head.open("w", encoding="utf-8")
    head.chmod(0o644)
    assert audit_heads.overwritable(tmp_path) == head


def _box_env(box: dict[str, Path]) -> dict[str, str]:
    return {"TB_AUDIT_HOST_DIR": str(box["audit"]), "TB_SECRETS_HOST_DIR": str(box["secrets"]),
            "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]), "TB_ENV": "PRODUCTION"}  # fmt: skip


def _signer(box: dict[str, Path]) -> Any:
    """The signer's container, replaced: it writes a head into the folder, as the real one does, and answers."""

    def run(argv: list[str], **_kw: Any) -> str:
        if "run" in argv[:3]:
            _head(box["share"])
            return json.dumps({"ok": True, "problems": [], "signed": {"lines": 3, "hash": "ab" * 32, "key_id": "k"},
                               "detail": {"lines": 3, "head": "ab" * 32, "key_id": "k", "anchors": 1}})  # fmt: skip
        return ""

    return run


def test_a_folder_the_boxs_root_can_write_over_fails_the_run_and_doctor(box: dict[str, Path]) -> None:
    night = audit_heads.sign_on_box(box["deploy"], _box_env(box), run=_signer(box), writable=lambda _p: True)
    assert not night.ok
    assert any("lets this box's root overwrite a signed head" in p and str(box["share"]) in p for p in night.problems)
    assert any("overwrite" in f for f in (night.detail or {}).get("failed", []))  # the event says so too
    state = audit_heads.state_file(box["deploy"], {})
    audit_heads.write_state(state, night)
    c = _doctor(box, SIGNED + timedelta(minutes=10))
    assert c.status == "FAIL" and "overwrite a signed head" in c.detail


def test_a_folder_the_boxs_root_cannot_write_over_passes(box: dict[str, Path]) -> None:
    night = audit_heads.sign_on_box(box["deploy"], _box_env(box), run=_signer(box), writable=lambda _p: False)
    assert night.ok, night.problems


# ------------------------------------------------------------------------------------------------ schedule and key
def test_the_installer_signs_every_hour_and_collects_logs_once_a_night() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    block = text[text.index('CRON_DIR="${TB_CRON_DIR:-/etc/cron.d}"') :].split('> "$CRON_DIR/trialbox-retention"')[0]
    lines = [ln for ln in block.splitlines() if "root cd $ROOT" in ln]
    sign = [ln for ln in lines if "tools.trialbox audit-sign" in ln]
    assert len(sign) == 1 and '"50 * * * * root cd $ROOT' in sign[0]
    daily = [ln for ln in lines if "tools.trialbox logs daily" in ln]
    assert len(daily) == 1 and '"20 0 * * * root cd $ROOT' in daily[0] and "audit-sign" not in daily[0]


def test_the_account_that_writes_the_audit_volume_cannot_reach_the_signing_key() -> None:
    """The separation the hourly head rests on: the only service that writes the audit volume mounts neither the
    secrets volume (the audit signing key) nor the KEK that unwraps it; a service that can read the key mounts the
    audit volume read-only. So the audit writer's account can rewrite rows, never sign a head for them."""
    services = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    writers, key_readers = [], []
    for name, svc in services.items():
        vols = [str(v) for v in svc.get("volumes") or []]
        if any(v.startswith("audit-data:") and not v.endswith(":ro") for v in vols):
            writers.append(name)
        if any(v.startswith("tb-secrets:") for v in vols):
            key_readers.append(name)
            assert any(v.startswith("audit-data:") and v.endswith(":ro") for v in vols) or not any(
                v.startswith("audit-data:") for v in vols
            ), name
    assert writers == ["audit-writer"]
    vols = [str(v) for v in services["audit-writer"].get("volumes") or []]
    assert not any("secrets" in v or "/run/trialbox" in v for v in vols), vols
    assert "audit-writer" not in key_readers


OLD_LINE = ("20 0 * * * root cd /opt/trialbox && { python3 -m tools.trialbox logs daily; python3 -m tools.trialbox "
            "audit-sign; } >> /var/log/trialbox-retention.log 2>&1")  # fmt: skip
BEFORE = b'SHELL=/bin/sh\nMAILTO=""\n# a line the site added  \n'  # every byte of these must stay
AFTER = b"15 3 * * * root true\r\n"


def test_the_installers_lines_are_the_ones_an_update_writes() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    block = text[text.index("printf '%s\\n' \"SHELL=/bin/sh\"") :].split('> "$CRON_DIR/trialbox-retention"')[0]
    quoted = [q for q in block.split('"')[1::2] if "root cd" in q]
    assert quoted == audit_heads.cron_lines("$ROOT")


def test_an_update_moves_a_nightly_cron_file_to_exactly_one_hourly_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import prestart

    cron = tmp_path / "cron.d"
    cron.mkdir()
    path = cron / audit_heads.CRON_NAME
    path.write_bytes(BEFORE + OLD_LINE.encode() + b"\n" + AFTER)
    monkeypatch.setattr(prestart, "CRON_DIR", cron)
    step = dict(prestart.STEPS)["hourly audit head"]
    assert "every hour (it was once a night)" in step(None)  # type: ignore[arg-type]  # the step reads no box
    after = path.read_bytes()
    lines = "".join(ln + "\n" for ln in audit_heads.cron_lines("/opt/trialbox")).encode()
    assert after == BEFORE + lines + AFTER  # the other lines byte for byte
    assert sum(b"audit-sign" in ln for ln in after.splitlines()) == 1
    assert oct(path.stat().st_mode & 0o777) == "0o644"
    assert not list(cron.glob(".*"))  # no temporary file left where cron reads
    assert "already" in step(None)  # type: ignore[arg-type]  # again: nothing changes
    assert path.read_bytes() == after


def test_the_step_never_fails_an_update_and_leaves_what_it_does_not_know(tmp_path: Path) -> None:
    assert "install.sh writes it" in audit_heads.hourly_cron(tmp_path)  # no file
    (tmp_path / audit_heads.CRON_NAME).mkdir()
    assert "cannot be read" in audit_heads.hourly_cron(tmp_path)  # not a file
    (tmp_path / audit_heads.CRON_NAME).rmdir()
    for odd in (b"SHELL=/bin/sh\n15 3 * * * root /usr/local/bin/something\n", b"\xff\xfe not UTF-8\n",
                b"SHELL=/bin/sh\n" + (OLD_LINE.encode() + b"\n") * 2):  # fmt: skip
        (tmp_path / audit_heads.CRON_NAME).write_bytes(odd)
        said = audit_heads.hourly_cron(tmp_path)
        assert "left as it is" in said
        assert (tmp_path / audit_heads.CRON_NAME).read_bytes() == odd


def test_a_cron_folder_that_cannot_be_written_is_said_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / audit_heads.CRON_NAME).write_bytes(OLD_LINE.encode() + b"\n")

    def refuse(self: Path, data: bytes) -> int:
        raise PermissionError("read-only file system")

    monkeypatch.setattr(Path, "write_bytes", refuse)
    assert "cannot be written (PermissionError)" in audit_heads.hourly_cron(tmp_path)
    assert (tmp_path / audit_heads.CRON_NAME).read_bytes() == OLD_LINE.encode() + b"\n"


def test_the_step_runs_before_the_stack_and_before_the_last_refusal() -> None:
    from tools.trialbox import prestart

    names = [n for n, _ in prestart.STEPS]
    assert names.index("hourly audit head") == len(names) - 2 and names[-1] == "hospital directory CA"
