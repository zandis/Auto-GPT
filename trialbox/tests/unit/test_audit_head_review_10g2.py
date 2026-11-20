"""The independent review of card 10G-2 (PR #1261 at 7933ba72): one test per finding, written before its fix, each
failing there; plus the link-following hole (lane K's finding) for the files this card's code opens. Time is a
parameter; keys are made in the test's own folder; synthetic events only."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit
from tb_common.audit import AuditLog

from tools import audit_verify
from tools.trialbox import audit_heads, doctor

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 19, 8, tzinfo=UTC)
SIGNED = datetime(2026, 11, 19, 9, 50, tzinfo=UTC)
HEAD = "20261119T095000+0000-000000000003.json"

pytestmark = pytest.mark.nodb


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", audit.ANCHOR_TARGETS_ENV, "TB_LOG_DIR"):
        monkeypatch.delenv(var, raising=False)
    paths = {name: tmp_path / name for name in ("audit", "share", "secrets", "run", "deploy")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setenv("TB_SECRETS_DIR", str(paths["secrets"]))
    monkeypatch.setenv("TB_KEK_FILE", str(paths["run"] / "kek"))
    monkeypatch.setenv("TB_ENV", "DEV")
    assert audit_verify.init_key(paths["secrets"]) == 0
    old = (SIGNED - timedelta(days=2)).timestamp()
    os.utime(paths["secrets"] / audit.SIGN_PUB_FILE, (old, old))
    log = AuditLog(paths["audit"])
    for i in range(3):
        log.append("test.event", ts=T0 + timedelta(minutes=i), actor="tester", detail={"n": i})
    return paths


def _sign(box: dict[str, Path], now: datetime = SIGNED) -> None:
    night = audit_heads.sign_night(box["audit"], box["secrets"], [box["share"]], record=lambda *_: None, now=now)
    assert night.ok, night.problems


def _state(box: dict[str, Path], ok: bool = True, **more: Any) -> None:
    path = audit_heads.state_file(box["deploy"], {})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"at": SIGNED.isoformat(), "ok": ok, "problems": [], "lines": 3, "kind": "ok" if ok else "refused", **more}
    path.write_text(json.dumps(doc), encoding="utf-8")


def _doctor(box: dict[str, Path], now: datetime, env: str = "PRODUCTION", **more: str) -> doctor.Check:
    e = {"TB_ENV": env, "TB_SECRETS_HOST_DIR": str(box["secrets"]), "TB_AUDIT_HOST_DIR": str(box["audit"]),
         "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]), **more}  # fmt: skip
    return doctor.check_audit_heads(doctor.DoctorInputs(env=e, deploy=box["deploy"]), now=now)


def _inner(box: dict[str, Path], monkeypatch: pytest.MonkeyPatch, env: str, capsys: Any) -> dict[str, Any]:
    monkeypatch.setenv("TB_ENV", env)
    argv = ["--inner", "--audit", str(box["audit"]), "--secrets", str(box["secrets"]), "--to", str(box["share"])]
    assert audit_heads.main(argv) == 0
    doc: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return doc


def _heads_dir(folder: Path) -> Path:
    (folder / "heads").mkdir(exist_ok=True)
    return folder / "heads"


def _refuse_all(monkeypatch: pytest.MonkeyPatch, **allow: bool) -> None:
    """Each write a probe tries refused (a WORM file, chattr +i, a squashed root), except those named in ``allow``."""
    for op in ("overwrite", "rename", "unlink"):
        verdict = allow.get(op, False)
        monkeypatch.setattr(audit_heads, f"_try_{op}", lambda _fd, _name, _v=verdict: _v)


# ------------------------------------------------------------------------------------------------ the 11 findings
def test_f1_a_share_that_lets_root_delete_a_head_is_not_root_proof(box: dict[str, Path], monkeypatch: Any) -> None:
    """Finding 1 (High): heads that cannot be overwritten, in a folder whose files root can delete and write again."""
    (_heads_dir(box["share"]) / HEAD).write_text("{}\n", encoding="utf-8")
    _refuse_all(monkeypatch, unlink=True)
    proof = audit_heads.root_proof(box["share"], HEAD, fs=lambda _p: "nfs4")
    assert not proof.ok and "delete" in proof.why


def test_f2_a_folder_on_the_boxs_own_disk_is_never_root_proof(box: dict[str, Path], monkeypatch: Any) -> None:
    """Finding 2 (High): chattr +i refuses every write, and root can clear it; a local disk cannot be shown safe."""
    (_heads_dir(box["share"]) / HEAD).write_text("{}\n", encoding="utf-8")
    _refuse_all(monkeypatch)
    for name in ("ext4", "xfs", "btrfs", "tmpfs", "overlay", "zfs"):

        def local(_p: Path, _name: str = name) -> str | None:
            return _name

        proof = audit_heads.root_proof(box["share"], HEAD, fs=local)
        assert not proof.ok and "own disk" in proof.why and "chattr +i" in proof.why
    proof = audit_heads.root_proof(box["share"], HEAD, fs=lambda _p: None)
    assert not proof.ok and "cannot be shown root-proof" in proof.why


def test_f3_no_service_account_can_open_the_audit_signing_key(box: dict[str, Path]) -> None:
    """Finding 3 (High): seal_keys.sh gave every root-owned file of the secrets folder to uid 10001, the adapter's
    and the orchestrator's account, which also have the KEK. The private audit key stays root's, 0600, and doctor
    FAILs it when it is not."""
    seal = (ROOT / "deploy" / "hardening" / "seal_keys.sh").read_text(encoding="utf-8")
    chown = next(ln for ln in seal.splitlines() if '-exec chown "$OWNER"' in ln)
    assert "! -name 'audit_sign*.key*'" in chown
    assert seal.count("\n  audit_key_root_only\n") + seal.count("\naudit_key_root_only\n") == 2
    key = box["secrets"] / (audit.SIGN_KEY_FILE)
    key = key if key.exists() else key.with_name(key.name + ".wrapped")
    key.chmod(0o640)
    inp = doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_SECRETS_HOST_DIR": str(box["secrets"])})
    c = doctor.check_audit_key_root(inp)
    assert c.status == "FAIL" and key.name in c.detail and "chmod 600" in c.detail


def test_f4_doctor_fails_when_the_hourly_result_is_missing(box: dict[str, Path]) -> None:
    """Finding 4 (High): with no result file a fresh head gave PASS, whatever the hourly run had said."""
    _sign(box)
    c = _doctor(box, SIGNED + timedelta(minutes=10))
    assert c.status == "FAIL" and "no result of the hourly audit-sign" in c.detail
    text = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    assert "LOG_HOST" in text and "-e TB_LOG_DIR=$LOG_HOST" in text  # the in-image doctor sees the result file


def test_f5_production_does_not_write_a_head_where_root_could_change_it(
    box: dict[str, Path], monkeypatch: Any, capsys: Any
) -> None:
    """Finding 5 (High): the judgement came after the head was published. Now the folder is judged first; in
    PRODUCTION a folder that cannot be shown root-proof gets no head (refused), elsewhere it gets one and the run
    says why it does not count as root-proof."""
    doc = _inner(box, monkeypatch, "PRODUCTION", capsys)
    assert doc["ok"] is False and doc["open_to_root"] and not list((box["share"] / "heads").glob("*.json"))
    assert "refused" in doc["open_to_root"][0]
    doc = _inner(box, monkeypatch, "VALIDATION", capsys)
    assert doc["ok"] is False and doc["open_to_root"] and len(list((box["share"] / "heads").glob("*.json"))) == 1


def test_f6_doctor_never_counts_a_head_it_could_not_check(box: dict[str, Path], monkeypatch: Any) -> None:
    """Finding 6 (High): a key that could not be read made doctor count heads by their date alone."""
    _state(box)
    heads = _heads_dir(box["share"])
    (heads / HEAD).write_text(json.dumps({"ts": SIGNED.isoformat(), "key_id": "x", "lines": 3}), encoding="utf-8")

    def broken(_s: Path) -> dict[str, bytes]:
        raise OSError("a dangling audit_sign.old.pub")

    monkeypatch.setattr(audit_heads, "own_keys", broken)
    c = _doctor(box, SIGNED + timedelta(minutes=10))
    assert c.status == "FAIL" and "cannot be read" in c.detail and "no head can be checked" in c.detail


def test_f7_the_head_judged_is_the_one_just_written_by_name(box: dict[str, Path], monkeypatch: Any) -> None:
    """Finding 7 (High): the last name in sort order was judged; after a clock moved back that is an older head."""
    heads = _heads_dir(box["share"])
    (heads / "20261119T105000+0000-000000000002.json").write_text("{}\n", encoding="utf-8")  # older, sorts later
    (heads / HEAD).write_text("{}\n", encoding="utf-8")
    asked: list[str] = []

    def overwrite(_fd: int, name: str) -> bool:
        asked.append(name)
        return name == HEAD

    _refuse_all(monkeypatch)
    monkeypatch.setattr(audit_heads, "_try_overwrite", overwrite)
    proof = audit_heads.root_proof(box["share"], HEAD, fs=lambda _p: "nfs4")
    assert not proof.ok and HEAD in proof.why and asked[0] == HEAD


def test_f8_a_limit_that_is_not_a_positive_finite_number_fails(box: dict[str, Path]) -> None:
    """Finding 8 (Medium): NaN made both age comparisons false and a week-old head passed."""
    _state(box)
    _sign(box, SIGNED - timedelta(days=7))
    for bad in ("NaN", "nan", "inf", "-1", "0", "two"):
        c = _doctor(box, SIGNED, TB_AUDIT_HEAD_MAX_AGE_H=bad)
        assert c.status == "FAIL" and "TB_AUDIT_HEAD_MAX_AGE_H" in c.detail, bad


def test_f9_a_head_dated_ahead_of_the_clock_has_a_tight_bound(box: dict[str, Path]) -> None:
    """Finding 9 (Medium): a head dated up to the whole window ahead passed, hiding a stopped signer for hours."""
    _state(box)
    _sign(box)
    assert _doctor(box, SIGNED - timedelta(minutes=4)).status == "PASS"
    c = _doctor(box, SIGNED - timedelta(minutes=90))
    assert c.status == "FAIL" and "ahead of this box's clock" in c.detail and "5 min" in c.detail


def test_f10_the_judgement_is_made_by_root_in_the_signer_not_by_the_invoking_account(
    box: dict[str, Path], monkeypatch: Any
) -> None:
    """Finding 10 (Medium): the host asked access(2) as whoever ran the command. Now only the signer's container,
    which runs as root, judges; the host never asks."""

    def no(*_a: Any, **_k: Any) -> bool:
        raise AssertionError("the host asked access(2)")

    monkeypatch.setattr(os, "access", no)
    _heads_dir(box["share"])
    (box["share"] / "heads" / HEAD).write_text("{}\n", encoding="utf-8")

    def run(argv: list[str], **_kw: Any) -> str:
        if "run" in argv[:3]:
            assert "--user" in argv and argv[argv.index("--user") + 1] == "0:0"
            return json.dumps({"ok": True, "problems": [], "signed": {"lines": 3, "hash": "ab" * 32, "key_id": "k"},
                               "detail": {"lines": 3, "head": "ab" * 32, "key_id": "k", "anchors": 1},
                               "open_to_root": [], "root_proof": {str(box["share"]): "a nfs4 share ..."}})  # fmt: skip
        return ""

    env = {"TB_AUDIT_HOST_DIR": str(box["audit"]), "TB_SECRETS_HOST_DIR": str(box["secrets"]),
           "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]), "TB_ENV": "PRODUCTION"}  # fmt: skip
    assert audit_heads.sign_on_box(box["deploy"], env, run=run).ok


def test_f11_the_update_moves_the_cron_file_where_the_installer_wrote_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 11 (Medium): the update's step looked in /etc/cron.d only; install.sh honours TB_CRON_DIR."""
    from tools.trialbox import prestart

    cron = tmp_path / "srv-cron.d"
    cron.mkdir()
    line = ("20 0 * * * root cd /opt/trialbox && { python3 -m tools.trialbox logs daily; python3 -m tools.trialbox "
            "audit-sign; } >> /var/log/trialbox-retention.log 2>&1\n")  # fmt: skip
    (cron / audit_heads.CRON_NAME).write_text(line, encoding="utf-8")
    monkeypatch.setenv("TB_CRON_DIR", str(cron))
    assert "every hour" in dict(prestart.STEPS)["hourly audit head"](None)  # type: ignore[arg-type]
    assert "50 * * * *" in (cron / audit_heads.CRON_NAME).read_text(encoding="utf-8")


@pytest.mark.parametrize("answer", [{}, {"root_proof": None}, {"root_proof": "x"}, {"root_proof": {"/other": "ok"}}])
def test_an_older_signer_answer_without_a_judgement_fails_closed(box: dict[str, Path], answer: dict[str, Any]) -> None:
    """The lead's addition: an older signer image beside newer host tools (mid-update) answers in the old shape.
    The host never reads that as a pass and never crashes: the run fails with a line that says why and what to do."""

    def run(argv: list[str], **_kw: Any) -> str:
        if "run" in argv[:3]:
            return json.dumps({"ok": True, "problems": [], "signed": {"lines": 3, "hash": "ab" * 32, "key_id": "k"},
                               "detail": {"lines": 3, "head": "ab" * 32, "key_id": "k", "anchors": 1}, **answer})  # fmt: skip
        return ""

    env = {"TB_AUDIT_HOST_DIR": str(box["audit"]), "TB_SECRETS_HOST_DIR": str(box["secrets"]),
           "TB_AUDIT_ANCHOR_TARGETS": str(box["share"]), "TB_ENV": "VALIDATION"}  # fmt: skip
    night = audit_heads.sign_on_box(box["deploy"], env, run=run)
    assert not night.ok and audit_heads.kind(night) == "open_to_root"
    said = night.problems[0]
    assert "has no root-proof judgement" in said and "older than the host tools" in said
    assert "tools/apply_update.sh status" in said


# ------------------------------------------------------------------------------------------------ links (H-68)
def _victim(tmp_path: Path) -> Path:
    v = tmp_path / "victim.txt"
    v.write_bytes(b"not yours\n")
    return v


@pytest.mark.parametrize("plant", ["symlink", "hardlink", "fifo"])
@pytest.mark.parametrize("where", ["probe", "head"])
def test_the_probe_never_follows_a_link_planted_in_its_place(
    box: dict[str, Path], tmp_path: Path, monkeypatch: Any, plant: str, where: str
) -> None:
    heads = _heads_dir(box["share"])
    victim = _victim(tmp_path)
    name = audit_heads.PROBE if where == "probe" else HEAD
    if where == "probe":
        (heads / HEAD).write_text("{}\n", encoding="utf-8")
    spot = heads / name
    if plant == "symlink":
        spot.symlink_to(victim)
    elif plant == "hardlink":
        os.link(victim, spot)
    else:
        os.mkfifo(spot)
    _refuse_all(monkeypatch)
    proof = audit_heads.root_proof(box["share"], HEAD, fs=lambda _p: "nfs4")
    assert not proof.ok and "cannot be shown root-proof" in proof.why
    assert victim.read_bytes() == b"not yours\n" and stat.S_ISREG(victim.lstat().st_mode)


def test_an_anchor_folder_that_is_a_link_is_not_followed(box: dict[str, Path], tmp_path: Path) -> None:
    real = tmp_path / "elsewhere"
    real.mkdir()
    _heads_dir(real)
    (box["share"] / "heads").symlink_to(real / "heads")
    proof = audit_heads.root_proof(box["share"], HEAD, fs=lambda _p: "nfs4")
    assert not proof.ok and "cannot be shown root-proof" in proof.why
    assert not list((real / "heads").iterdir())


def test_the_result_file_is_never_written_through_a_link(box: dict[str, Path], tmp_path: Path) -> None:
    victim = _victim(tmp_path)
    state = audit_heads.state_file(box["deploy"], {})
    state.parent.mkdir(parents=True)
    (state.parent / f".{state.name}.tmp").symlink_to(victim)
    audit_heads.write_state(state, audit_heads.Night(True))
    assert victim.read_bytes() == b"not yours\n" and json.loads(state.read_text(encoding="utf-8"))["ok"] is True


def test_doctor_reads_no_result_file_through_a_link(box: dict[str, Path], tmp_path: Path) -> None:
    _sign(box)
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({"at": SIGNED.isoformat(), "ok": True, "problems": [], "kind": "ok"}))
    state = audit_heads.state_file(box["deploy"], {})
    state.parent.mkdir(parents=True)
    state.symlink_to(fake)
    c = _doctor(box, SIGNED + timedelta(minutes=10))
    assert c.status == "FAIL" and "result" in c.detail


def test_the_writers_lock_file_is_not_followed(box: dict[str, Path], tmp_path: Path) -> None:
    victim = _victim(tmp_path)
    lock = box["audit"] / ".lock"
    if lock.exists():
        lock.unlink()
    lock.symlink_to(victim)
    night = audit_heads.check_and_sign(box["audit"], box["secrets"], [box["share"]], SIGNED)
    assert not night.ok and "lock" in night.problems[0] and victim.read_bytes() == b"not yours\n"
