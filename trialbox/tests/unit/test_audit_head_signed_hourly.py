"""10G-2 (review 16-19, D-1345): the head of the audit chain is signed every hour; an anchor folder whose heads the
box's root could overwrite fails the run; ``doctor`` FAILs a head older than 2 h (a 3-hour-old head fails, a 1-hour-old
one passes), WARNs while a new box has no head yet, and FAILs a head dated more than 2 h ahead of the clock. Time is a
parameter here, never a sleep. Keys are made in the test's own folder; synthetic events only."""

from __future__ import annotations

import json
import os
import stat
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
    """Doctor's line; an ok result of the hourly run is written first unless the test wrote its own (doctor fails
    closed without one: tests/unit/test_audit_head_review_10g2.py)."""
    state = audit_heads.state_file(box["deploy"], {})
    if not state.exists():
        audit_heads.write_state(state, audit_heads.Night(True))
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


def test_a_head_dated_ahead_of_the_clock_fails_beyond_five_minutes(box: dict[str, Path]) -> None:
    """Clock skew: a head up to 5 min ahead of this box's clock passes; more FAILs and names both times."""
    _key_made(box, SIGNED - timedelta(days=2))
    _sign(box)
    assert _doctor(box, SIGNED - timedelta(minutes=5)).status == "PASS"
    c = _doctor(box, SIGNED - timedelta(minutes=6))
    assert c.status == "FAIL" and "6 min ahead of this box's clock (2026-11-19T09:44+00:00" in c.detail
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


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes a read-only file on a local disk: the stand-in needs a user")
def test_on_a_stand_in_a_share_that_refuses_every_write_is_root_proof(tmp_path: Path) -> None:
    """The kernel's own answers, not modes read by hand: on a stand-in for a share (the type given, the refusals
    real: a read-only head, a read-only test file, a folder that refuses delete and rename) the judgement passes;
    the same head made writable fails it. On a box the account is root and the refusals come from the share."""
    head = _head(tmp_path)
    probe = tmp_path / "heads" / audit_heads.PROBE
    probe.write_text("probe\n", encoding="utf-8")
    for f in (head, probe):
        f.chmod(0o444)
    (tmp_path / "heads").chmod(0o555)
    try:
        proof = audit_heads.root_proof(tmp_path, head.name, fs=lambda _p: "nfs4")
        assert proof.ok, proof.why
        head.chmod(0o644)
        proof = audit_heads.root_proof(tmp_path, head.name, fs=lambda _p: "nfs4")
        assert not proof.ok and "overwrite the head just written" in proof.why
    finally:
        (tmp_path / "heads").chmod(0o755)


def _box_env(box: dict[str, Path]) -> dict[str, str]:
    return {"TB_AUDIT_HOST_DIR": str(box["audit"]), "TB_SECRETS_HOST_DIR": str(box["secrets"]),
            "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]), "TB_ENV": "PRODUCTION"}  # fmt: skip


def _signer(box: dict[str, Path], open_to_root: bool = False) -> Any:
    """The signer's container, replaced: the head it would write is signed for real first (``_sign``), so that the
    folder holds one genuine head; the replacement only answers as the container does."""
    _key_made(box, SIGNED - timedelta(days=2))
    _sign(box)

    def run(argv: list[str], **_kw: Any) -> str:
        if "run" in argv[:3]:
            proof = "a nfs4 share that refused this box's root every overwrite, rename and delete tried"
            bad = [f"the anchor folder {box['share']}: cannot be root-proof: a ext4 folder on this box's own disk; "
                   "a head there does not count as root-proof. Make TB_AUDIT_ANCHOR_TARGETS a folder on the hospital's "
                   "share ... root squashed ... (RUNBOOK 02, D-1345)"] if open_to_root else []  # fmt: skip
            return json.dumps({"ok": not bad, "problems": bad, "open_to_root": bad,
                               "root_proof": {str(box["share"]): bad[0] if bad else proof},
                               "signed": {"lines": 3, "hash": "ab" * 32, "key_id": "k"},
                               "detail": {"lines": 3, "head": "ab" * 32, "key_id": "k", "anchors": 1, "failed": bad}})  # fmt: skip
        return ""

    return run


def _open_to_root_run(box: dict[str, Path]) -> audit_heads.Night:
    night = audit_heads.sign_on_box(box["deploy"], _box_env(box), run=_signer(box, open_to_root=True))
    audit_heads.write_state(audit_heads.state_file(box["deploy"], {}), night)
    return night


def test_a_folder_the_boxs_root_can_write_over_fails_the_run_and_says_its_kind(box: dict[str, Path]) -> None:
    night = _open_to_root_run(box)
    assert not night.ok  # the command exits 1 in every environment
    assert any("does not count as root-proof" in p and str(box["share"]) in p for p in night.problems)
    assert any("root-proof" in f for f in (night.detail or {}).get("failed", []))  # the event says so too
    state = json.loads(audit_heads.state_file(box["deploy"], {}).read_text(encoding="utf-8"))
    assert state["ok"] is False and state["kind"] == "open_to_root"


@pytest.mark.parametrize(
    ("env", "status"), [("PRODUCTION", "FAIL"), ("VALIDATION", "WARN"), ("TEST", "WARN"), ("DEV", "WARN")]
)
def test_doctor_fails_a_folder_open_to_root_in_production_and_warns_elsewhere(
    box: dict[str, Path], env: str, status: str
) -> None:
    _open_to_root_run(box)
    c = _doctor(box, SIGNED + timedelta(minutes=10), env=env)
    assert c.status == status, c.detail
    assert "does not count as root-proof" in c.detail and "root squashed" in c.detail and "RUNBOOK 02" in c.detail


def test_a_real_refusal_beside_a_folder_open_to_root_is_still_a_refusal(box: dict[str, Path]) -> None:
    night = audit_heads.sign_on_box(box["deploy"], {**_box_env(box), "TB_AUDIT_ANCHOR_TARGETS": os.pathsep.join(
        [str(box["share"]), str(box["deploy"] / "not-mounted")])}, run=_signer(box, open_to_root=True))  # fmt: skip
    assert audit_heads.kind(night) == "refused"
    audit_heads.write_state(audit_heads.state_file(box["deploy"], {}), night)
    c = _doctor(box, SIGNED + timedelta(minutes=10), env="VALIDATION")
    assert c.status == "FAIL" and "was refused or failed" in c.detail


@pytest.mark.parametrize("kind", [None, "", ["open_to_root"], 7, "something else"])
def test_a_result_file_without_a_known_kind_reads_as_before(box: dict[str, Path], kind: Any) -> None:
    """A result file written before 10G-2 has no "kind": a failed run there is a refusal, as it always was."""
    _key_made(box, SIGNED - timedelta(days=2))
    _sign(box)
    doc: dict[str, Any] = {"at": "2026-11-19T09:50:00+00:00", "ok": False, "problems": ["x"], "lines": None}
    if kind is not None:
        doc["kind"] = kind
    state = audit_heads.state_file(box["deploy"], {})
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(doc), encoding="utf-8")
    for env, status in (("VALIDATION", "FAIL"), ("DEV", "WARN")):
        c = _doctor(box, SIGNED + timedelta(minutes=10), env=env)
        assert c.status == status and "was refused or failed: x" in c.detail


def test_a_folder_the_boxs_root_cannot_write_over_passes(box: dict[str, Path]) -> None:
    night = audit_heads.sign_on_box(box["deploy"], _box_env(box), run=_signer(box))
    assert night.ok, night.problems
    assert audit_heads.kind(night) == "ok" and night.open_to_root == []
    audit_heads.write_state(audit_heads.state_file(box["deploy"], {}), night)
    assert _doctor(box, SIGNED + timedelta(minutes=10)).status == "PASS"


# ------------------------------------------------------------------------------------------------ schedule and key
def test_the_installer_signs_every_hour_and_collects_logs_once_a_night() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    block = text[text.index('CRON_DIR="${TB_CRON_DIR:-/etc/cron.d}"') :].split('> "$CRON_DIR/trialbox-retention"')[0]
    lines = [ln for ln in block.splitlines() if "root cd $ROOT" in ln]
    sign = [ln for ln in lines if "tools.trialbox audit-sign" in ln]
    assert len(sign) == 1 and '"50 * * * * root cd $ROOT' in sign[0]
    daily = [ln for ln in lines if "tools.trialbox logs daily" in ln]
    assert len(daily) == 1 and '"20 0 * * * root cd $ROOT' in daily[0] and "audit-sign" not in daily[0]


def test_who_can_read_the_audit_key_and_the_kek_is_named() -> None:
    """The compose fact the review's finding 3 is about: the only service that writes the audit volume mounts neither
    the secrets volume (the audit key's folder) nor the KEK; the services that mount both are named here, and each
    runs as uid 10001 with the audit volume read-only. They keep the folder and the KEK for their own keys; the
    private audit key's file is root's, 0600 (the next test)."""
    services = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    writers, both = [], []
    for name, svc in services.items():
        vols = [str(v) for v in svc.get("volumes") or []]
        if any(v.startswith("audit-data:") and not v.endswith(":ro") for v in vols):
            writers.append(name)
        if any(v.startswith("tb-secrets:") for v in vols) and any(":/run/trialbox" in v for v in vols):
            both.append(name)
            assert str(svc.get("user")) == "10001:10001", name
            assert all(v.endswith(":ro") for v in vols if v.startswith("audit-data:")), name
    assert writers == ["audit-writer"]
    assert sorted(both) == ["adapter", "orchestrator"]


SERVICE_UID = 10001  # the adapter's and the orchestrator's account (docker-compose.yml, the previous test)


def test_the_services_account_cannot_open_the_private_audit_key(box: dict[str, Path]) -> None:
    """As root: the key made root's, 0600, and a process running as uid 10001 is refused it. As another user (CI):
    a stand-in, the same modes, with the refusal worked out from them (that user cannot become 10001)."""
    names = audit_heads.private_key_files(box["secrets"])
    assert names and not [n for n in names if n.endswith(".pub")]
    key = box["secrets"] / names[0]
    if os.geteuid() != 0:
        key.chmod(0o600)
        st = key.stat()
        assert "not root" in audit_heads.key_root_only(box["secrets"])
        assert st.st_uid != SERVICE_UID and not st.st_mode & 0o077  # owner only, and the owner is not 10001
        return
    os.chown(key, SERVICE_UID, SERVICE_UID)
    key.chmod(0o640)
    assert "root's, 0600" in audit_heads.key_root_only(box["secrets"])
    st = key.stat()
    assert (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (0, 0, 0o600)
    os.chmod(box["secrets"], 0o755)  # the folder as the services see it (theirs on a box): the file decides
    pid = os.fork()
    if pid == 0:  # the child: become the services' account and try
        code = 3
        try:
            os.setgid(SERVICE_UID)
            os.setuid(SERVICE_UID)
            try:
                os.open(key, os.O_RDONLY)
                code = 1
            except PermissionError:
                code = 0
        finally:
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    assert os.WEXITSTATUS(status) == 0, "uid 10001 could open the private audit key"
    inp = doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_SECRETS_HOST_DIR": str(box["secrets"])})
    assert doctor.check_audit_key_root(inp).status == "PASS"


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
    monkeypatch.setenv("TB_CRON_DIR", str(cron))
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

    def refuse(*_a: Any) -> None:
        raise PermissionError("read-only file system")

    monkeypatch.setattr(audit_heads, "replace_plain", refuse)
    assert "cannot be written (PermissionError)" in audit_heads.hourly_cron(tmp_path)
    assert (tmp_path / audit_heads.CRON_NAME).read_bytes() == OLD_LINE.encode() + b"\n"


def test_the_step_runs_before_the_stack_and_before_the_last_refusal() -> None:
    from tools.trialbox import prestart

    names = [n for n, _ in prestart.STEPS]
    assert names[-3:] == ["hourly audit head", "audit key root only", "hospital directory CA"]
