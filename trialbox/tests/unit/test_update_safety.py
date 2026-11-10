"""T-111 / D-210: update safety. The manifest's new fields (each one required), ``not_after``, the trust (two keys,
a rotation accepted once, a retired key), anti-rollback with an audited ``--allow-downgrade``, the compatibility
table checked before anything is staged, release.json's digests against images.lock (null refused, before
extraction), the marker (refusal while it exists, ``status``, recovery), the free-space preflight with numbers,
services started again when the rollback point fails, sealed dumps, and the rulesets repository put back to its tag.
The whole path with real bundles, the kill -9 cases and the db image is ``tools/update_drill.py``."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tools import update_status as us
from tools.sign_bundle import build, keygen, permissive_compat, rotation_for
from tools.trialbox import update as up
from tools.verify_update import Rejected, key_id, load_public_key, summary, verify

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64


@pytest.fixture()
def v(tmp_path: Path) -> dict[str, Any]:
    priv, pub = keygen(tmp_path / "k1")
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "notes.txt").write_text("release notes\n", encoding="utf-8")
    (payload / "img.tar").write_bytes(b"image bytes")
    return {"priv": priv, "pub": pub, "tmp": tmp_path, "payload": payload, "updates": tmp_path / "updates"}


def _bundle(v: dict[str, Any], bid: str = "B2", **kw: Any) -> Path:
    items = kw.pop("items", None) or [("other", v["payload"] / "notes.txt", "notes.txt")]
    key: Path = kw.pop("key", v["priv"])
    out: Path = v["tmp"] / f"{bid}-{len(list(v['tmp'].glob('*.tar')))}.tar"
    build(key, bid, items, out, **kw)
    return out


def _verify(v: dict[str, Any], bundle: Path, stage: Path | None = None, **kw: Any) -> dict[str, Any]:
    u = v["updates"]
    return verify(bundle, v["pub"], stage, trust_file=u / "trust.json", installed_file=u / "installed.json", **kw)


def _installed(v: dict[str, Any], seq: int, state: dict[str, Any] | None = None) -> None:
    us.write_atomic(v["updates"] / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": seq,
                                                  "bundle_id": "X", "state": state or {}})  # fmt: skip


def _resign(v: dict[str, Any], bundle: Path, edit: Any, key: Path | None = None) -> Path:
    """The bundle with its manifest edited and signed again by a trusted key (a vendor mistake, not tampering)."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    with tarfile.open(bundle) as tf:
        mem = {m.name: (tf.extractfile(m).read() if m.isfile() else b"") for m in tf.getmembers()}  # type: ignore[union-attr]
    m = json.loads(mem["manifest.json"])
    edit(m)
    body = json.dumps(m).encode()
    sk = load_pem_private_key((key or v["priv"]).read_bytes(), password=None)
    mem["manifest.json"] = body
    mem["manifest.json.sig"] = base64.b64encode(sk.sign(body))  # type: ignore[union-attr,call-arg]
    out = bundle.with_name(bundle.stem + "-edited.tar")
    with tarfile.open(out, "w") as tf:
        for name, data in mem.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return out


# ------------------------------------------------------------------------------------------------ manifest fields
@pytest.mark.parametrize("field", ["release_seq", "min_installed_version", "key_id", "not_after", "compat_sha256"])
def test_each_new_manifest_field_missing_is_refused(v: dict[str, Any], field: str) -> None:
    good = _bundle(v)
    assert _verify(v, good)["release_seq"] == 1
    with pytest.raises(Rejected, match=f"schema.*'{field}' is a required property"):
        _verify(v, _resign(v, good, lambda m: m.pop(field)))


def test_a_payload_size_is_required_too(v: dict[str, Any]) -> None:
    with pytest.raises(Rejected, match="'size' is a required property"):
        _verify(v, _resign(v, _bundle(v), lambda m: m["files"][0].pop("size")))


def test_not_after_passed_is_refused(v: dict[str, Any]) -> None:
    b = _bundle(v, created_at="2026-01-01T00:00:00+00:00", not_after="2026-02-01T00:00:00+00:00")
    with pytest.raises(Rejected, match="expired at 2026-02-01"):
        _verify(v, b)
    assert _verify(v, b, now=datetime(2026, 1, 15, tzinfo=UTC))["bundle_id"] == "B2"


def test_key_id_must_name_the_signing_key(v: dict[str, Any]) -> None:
    with pytest.raises(Rejected, match="is not the key that signed it"):
        _verify(v, _resign(v, _bundle(v), lambda m: m.update(key_id="ed25519:" + "0" * 16)))


def test_two_trusted_keys_either_signs(v: dict[str, Any]) -> None:
    priv2, pub2 = keygen(v["tmp"] / "k2")
    b = _bundle(v, key=priv2)
    with pytest.raises(Rejected, match="does not verify with a trusted vendor key"):
        verify(b, v["pub"])
    assert verify(b, [v["pub"], pub2])["key_id"] == key_id(load_public_key(pub2))
    with pytest.raises(Rejected, match="at most 2"):
        verify(b, [v["pub"], pub2, pub2])


def test_trust_json_replaces_the_key_files(v: dict[str, Any]) -> None:
    """Once trust.json exists, --pubkey (TB_VENDOR_PUBKEY) no longer adds trust: no environment downgrade."""
    priv2, pub2 = keygen(v["tmp"] / "k2")
    trust = verify(_bundle(v), v["pub"])["trust_after"]
    us.write_atomic(v["updates"] / us.TRUST, trust)
    with pytest.raises(Rejected, match="does not verify with a trusted vendor key"):
        verify(_bundle(v, key=priv2), pub2, trust_file=v["updates"] / us.TRUST)


# ------------------------------------------------------------------------------------------------ rotation
def test_a_key_rotation_bundle_is_accepted_once_and_the_retired_key_is_refused(v: dict[str, Any]) -> None:
    priv2, pub2 = keygen(v["tmp"] / "k2")
    _priv3, pub3 = keygen(v["tmp"] / "k3")
    k1, k2, k3 = (key_id(load_public_key(p)) for p in (v["pub"], pub2, pub3))
    rot = _bundle(v, "ROT1", release_seq=2, rotation=rotation_for(pub2))  # k1 adds k2
    m = _verify(v, rot)
    assert set(m["trust_after"]["keys"]) == {k1, k2} and m["manifest_sha256"] in m["trust_after"]["rotations"]
    us.write_atomic(v["updates"] / us.TRUST, m["trust_after"])  # what a completed apply writes
    _installed(v, 2)
    with pytest.raises(Rejected, match="already applied"):  # accepted once, even as an audited downgrade
        _verify(v, rot, allow_downgrade="again")
    m = _verify(v, _bundle(v, "ROT2", release_seq=3, key=priv2, rotation=rotation_for(pub3, retire=k1)))
    assert set(m["trust_after"]["keys"]) == {k2, k3} and k1 in m["trust_after"]["retired"]
    us.write_atomic(v["updates"] / us.TRUST, m["trust_after"])
    _installed(v, 3)
    with pytest.raises(Rejected, match="does not verify with a trusted vendor key"):
        _verify(v, _bundle(v, "OLDKEY", release_seq=4))  # the retired key signs nothing any more
    assert _verify(v, _bundle(v, "NEWKEY", release_seq=4, key=priv2))["bundle_id"] == "NEWKEY"
    with pytest.raises(Rejected, match="retired and is never trusted again"):
        _verify(v, _bundle(v, "BACK", release_seq=4, key=priv2, rotation=rotation_for(v["pub"], retire=k3)))


def test_a_rotation_may_not_leave_three_keys(v: dict[str, Any]) -> None:
    _p2, pub2 = keygen(v["tmp"] / "k2")
    _p3, pub3 = keygen(v["tmp"] / "k3")
    with pytest.raises(Rejected, match="would trust 3 keys"):
        verify(_bundle(v, rotation=rotation_for(pub3)), [v["pub"], pub2])


# ------------------------------------------------------------------------------------------------ anti-rollback
def test_an_older_release_seq_is_refused_and_allow_downgrade_needs_a_reason(v: dict[str, Any]) -> None:
    _installed(v, 5)
    old = _bundle(v, release_seq=4)
    with pytest.raises(Rejected, match="release_seq 4 is not above the installed 5"):
        _verify(v, old)
    with pytest.raises(Rejected, match="not above"):
        _verify(v, _bundle(v, release_seq=5))  # a repeat is refused too
    with pytest.raises(Rejected, match="not above"):
        _verify(v, old, allow_downgrade="  ")
    m = _verify(v, old, allow_downgrade="vendor ticket 42")
    assert m["downgrade"] == {"from_release_seq": 5, "to_release_seq": 4, "reason": "vendor ticket 42"}


def test_min_installed_version_is_never_overridden(v: dict[str, Any]) -> None:
    _installed(v, 2)
    with pytest.raises(Rejected, match="needs at least 3 installed first"):
        _verify(v, _bundle(v, release_seq=9, min_installed_version=3), allow_downgrade="x")


def test_allow_downgrade_is_audited_before_anything_else(tmp_path: Path) -> None:
    box = Recorder()
    updates = tmp_path / "updates"
    us.write_atomic(updates / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 5, "state": {}})
    plan = _plan(tmp_path, seq=4)
    with pytest.raises(up.UpdateRefused, match="not above the installed 5"):
        up.Updater(box, updates, say=lambda _m: None).run(plan)
    assert box.calls == [] and box.audits == []
    plan.downgrade = {"from_release_seq": 5, "to_release_seq": 4, "reason": "ticket 42"}
    assert up.Updater(box, updates, say=lambda _m: None).run(plan)["ok"]
    assert [e for e, _ in box.audits] == ["update.downgrade", "update.applied"]
    assert box.audits[0][1]["reason"] == "ticket 42" and us.installed(updates)["release_seq"] == 4


# ------------------------------------------------------------------------------------------------ compat, images
def test_the_compatibility_table_is_checked_before_anything_is_staged(v: dict[str, Any]) -> None:
    compat = permissive_compat("B2")
    compat["rows"] = [{"schema": {"site": {"min": 1, "max": 3}}, "model_pin": ["judge@2"], "prompt_registry": "*"}]
    b = _bundle(v, compat=compat)
    _installed(v, 0, {"schema": {"site": 4}, "model_pin": "judge@2"})
    stage = v["tmp"] / "stage"
    with pytest.raises(Rejected, match="schema site is at version 4, newer than this bundle knows"):
        _verify(v, b, stage)
    assert not stage.exists()
    _installed(v, 0, {"schema": {"site": 2}, "model_pin": "judge@1"})
    with pytest.raises(Rejected, match="model_pin 'judge@1' is not one of"):
        _verify(v, b, stage)
    _installed(v, 0, {"schema": {"site": 2}, "model_pin": "judge@2"})  # no prompt registry recorded: not compared
    m = _verify(v, b, stage)
    assert any("prompt_registry" in n for n in m["compat_notes"]) and (stage / "other/notes.txt").is_file()


def test_compat_json_must_be_for_this_bundle_and_bound_by_its_sha(v: dict[str, Any]) -> None:
    with pytest.raises(Rejected, match="compat.json is for bundle 'OTHER'"):
        _verify(v, _bundle(v, compat=permissive_compat("OTHER")))
    with pytest.raises(Rejected, match="compat.json: sha256 mismatch"):
        _verify(v, _resign(v, _bundle(v), lambda m: m.update(compat_sha256="0" * 64)))


def _image_items(v: dict[str, Any]) -> list[tuple[str, Path, str]]:
    return [("image", v["payload"] / "img.tar", "img.tar")]


@pytest.mark.parametrize(
    ("release", "lock", "why"),
    [
        (None, None, "no release.json"),
        ({"images": {"db": {"image": "pg:1", "digest": DIGEST}}}, None, "no images.lock"),
        ({"images": {"db": {"image": "pg:1", "digest": DIGEST}}},
         {"images": {"db": {"image": "pg:1", "digest": None}}}, "images.lock has no digest"),
        ({"images": {"db": {"image": "pg:1", "digest": DIGEST}}},
         {"images": {"db": {"image": "pg:1", "digest": "sha256:" + "b" * 64}}}, "differs from images.lock"),
        ({"images": {"db": {"image": "pg:1", "digest": None}}},
         {"images": {"db": {"image": "pg:1", "digest": DIGEST}}}, "release.json has no digest"),
        ({"images": {"db": {"image": "pg:1", "digest": DIGEST}, "py": {"image": "py:1", "digest": DIGEST}}},
         {"images": {"db": {"image": "pg:1", "digest": DIGEST}}}, "in release.json but not in images.lock"),
        ({"images": {"db": {"image": "pg:2", "digest": DIGEST}}},
         {"images": {"db": {"image": "pg:1", "digest": DIGEST}}}, "release.json names 'pg:2'"),
    ],
)  # fmt: skip
def test_release_digests_differing_from_images_lock_are_refused_before_extraction(
    v: dict[str, Any], release: Any, lock: Any, why: str
) -> None:
    stage = v["tmp"] / "stage"
    with pytest.raises(Rejected, match=why):
        _verify(v, _bundle(v, items=_image_items(v), release=release, images_lock=lock), stage)
    assert not stage.exists()  # refused before any payload was read or staged


def test_matching_digests_pass_and_the_box_lock_is_the_fallback(v: dict[str, Any]) -> None:
    rel = {"images": {"db": {"image": "pg:1", "digest": DIGEST}}}
    assert _verify(v, _bundle(v, items=_image_items(v), release=rel, images_lock=rel))["release"] == rel
    box_lock = v["tmp"] / "images.lock"
    box_lock.write_text(json.dumps(rel))
    assert _verify(v, _bundle(v, items=_image_items(v), release=rel), images_lock=box_lock)["release"] == rel
    real = ROOT / "deploy" / "images.lock"  # T-104's lock: the db digest is null until T-110 pins it
    with pytest.raises(Rejected, match="images.lock has no digest"):
        _verify(v, _bundle(v, items=_image_items(v), release=rel), images_lock=real)


def test_unsafe_payload_paths_are_refused(v: dict[str, Any]) -> None:
    f = v["payload"] / "notes.txt"
    for dest, why in (("a.part", "may not end in .part"), ("../x", "unsafe path")):
        with pytest.raises(Rejected, match=why):
            _verify(v, _bundle(v, items=[("other", f, dest)]))
    with pytest.raises(Rejected, match="also used as a folder"):
        _verify(v, _bundle(v, items=[("other", f, "a"), ("other", f, "a/b")]))


def test_the_staging_preflight_refuses_with_the_numbers(v: dict[str, Any]) -> None:
    stage = v["tmp"] / "stage"
    with pytest.raises(Rejected, match=r"needs 0\.00 GB \(14 bytes\).*free 0\.00 GB \(3 bytes\)"):
        _verify(v, _bundle(v), stage, disk_free=lambda _p: 3)
    assert not stage.exists()


# ------------------------------------------------------------------------------------------------ the update path
class Recorder:
    name = "recorder"

    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[str] = []
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError(f"{name} broke")

    def running(self) -> bool:
        return True

    def backup(self, plan: up.Plan, rb: Path) -> str:
        self._step("backup")
        return "nas"

    def resume(self, plan: up.Plan) -> None:
        self._step("resume")

    def snapshot(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self._step("snapshot")
        f = rb / "trialbox_wf.dump"
        f.write_text("PHI dump")
        point.dumps["trialbox_wf"] = str(up.seal(f, rb))

    def apply(self, plan: up.Plan, rb: Path, point: up.Point) -> list[str]:
        self._step("apply")
        return []

    def restart(self, plan: up.Plan) -> None:
        self._step("restart")

    def post_apply(self, plan: up.Plan) -> list[str]:
        self._step("post_apply")
        return []

    def check(self, plan: up.Plan) -> str:
        self._step("check")
        return "healthy"

    def rollback(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self._step("rollback")

    def audit(self, event: str, plan: up.Plan, detail: dict[str, Any]) -> None:
        self.audits.append((event, detail))


def _plan(tmp: Path, seq: int | None = 2, bid: str = "B1") -> up.Plan:
    stage = tmp / f"stage-{bid}"
    stage.mkdir(parents=True, exist_ok=True)
    compat = {"format": us.COMPAT_FORMAT, "bundle_id": bid, "rows": [{}], "provides": {"model_pin": "judge@2"}}
    return up.Plan(bid, "f" * 64, "vendor", [], stage, release_seq=seq, compat=compat,
                   trust_after={"format": us.TRUST_FORMAT, "keys": {"ed25519:" + "1" * 16: {}}})  # fmt: skip


def test_a_completed_update_records_itself_and_removes_marker_and_dumps(tmp_path: Path) -> None:
    updates = tmp_path / "updates"
    seen: list[dict[str, Any] | None] = []
    upd = up.Updater(Recorder(), updates, say=lambda _m: None, on_step=lambda _s: seen.append(us.marker(updates)))
    assert upd.run(_plan(tmp_path))["ok"]
    assert [m["step"] for m in seen if m] == list(up.STEPS)
    assert us.marker(updates) is None and not (updates / "B1/rollback").exists()
    inst = us.installed(updates)
    assert inst["release_seq"] == 2 and inst["state"]["model_pin"] == "judge@2"
    assert us.trust(updates) is not None


def test_the_marker_refuses_a_second_update_and_status_reports_it(tmp_path: Path) -> None:
    updates = tmp_path / "updates"

    class Stop(BaseException):  # like a kill: nothing in the updater catches it
        pass

    def stop(step: str) -> None:
        if step == "apply":
            raise Stop

    with pytest.raises(Stop):  # an interrupted update (the drill does it with kill -9)
        up.Updater(Recorder(), updates, say=lambda _m: None, on_step=stop).run(_plan(tmp_path))
    st = us.status(updates)
    assert st["in_progress"] and st["update"]["step"] == "apply" and st["update"]["bundle_id"] == "B1"
    assert st["update"]["state"] == "interrupted" and "rollback B1" in st["next"]
    assert st["update"]["steps_done"] == ["backup", "rollback point"]
    box = Recorder()
    with pytest.raises(up.UpdateRefused, match="B1 is unfinished"):
        up.Updater(box, updates, say=lambda _m: None).run(_plan(tmp_path, seq=3, bid="B2"))
    assert box.calls == []
    r = subprocess.run([sys.executable, "-m", "tools.update_status", "--deploy", str(tmp_path), "check"],
                       cwd=ROOT, capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == us.EXIT_IN_PROGRESS and "B1 is unfinished" in r.stderr
    sealed = updates / "B1/rollback/trialbox_wf.dump.enc"
    assert sealed.is_file() and b"PHI" not in sealed.read_bytes()  # sealed at rest while the marker stands
    rec = Recorder()
    with pytest.raises(up.UpdateFailed, match="not B9"):
        up.Updater(rec, updates, say=lambda _m: None).recover("B9")
    assert up.Updater(rec, updates, say=lambda _m: None).recover("B1")["from_step"] == "apply"
    assert rec.calls == ["rollback", "check"] and [e for e, _ in rec.audits] == ["update.rolled_back"]
    assert us.marker(updates) is None and not (updates / "B1/rollback").exists()
    assert not (updates / us.INSTALLED).exists()  # the state files are as before the update (none)


def test_a_running_update_holds_the_lock(tmp_path: Path) -> None:
    updates = tmp_path / "updates"
    with us.locked(updates):
        assert us.lock_held(updates)
        with pytest.raises(up.UpdateRefused, match="another update or rollback is running"):
            up.Updater(Recorder(), updates, say=lambda _m: None).run(_plan(tmp_path))
    assert not us.lock_held(updates)


@pytest.mark.parametrize("fail", ["snapshot", "backup"])
def test_rollback_restarts_stopped_services_when_the_rollback_point_fails(tmp_path: Path, fail: str) -> None:
    box = Recorder(fail=fail)
    updates = tmp_path / "updates"
    with pytest.raises(up.UpdateFailed, match="nothing was changed"):
        up.Updater(box, updates, say=lambda _m: None).run(_plan(tmp_path))
    assert box.calls[-1] == "resume" and us.marker(updates) is None


def test_compose_box_starts_the_services_again_when_the_rollback_point_fails(tmp_path: Path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / "secrets/backup.pub").write_text("pub")
    (deploy / ".env").write_text(f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n")
    monkeypatch.setenv("TB_COMPOSE", "dc")
    monkeypatch.setenv("TB_UPDATE_BACKUP_CMD", "true")
    calls: list[str] = []

    def run(argv: list[str], stdin_file: Path | None = None, stdout_file: Path | None = None, **_kw: Any) -> str:
        line = " ".join(argv)
        calls.append(line)
        if stdout_file:
            stdout_file.write_text("dump")
        if "image inspect" in line or "criteria-compiler python -c" in line:
            raise up.UpdateFailed("docker broke")
        return ""

    stage = tmp_path / "stage"
    (stage / "image").mkdir(parents=True)
    with tarfile.open(stage / "image/py.tar", "w") as tf:
        body = json.dumps([{"RepoTags": ["trialbox-py:1.0.0"]}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    plan = up.Plan("B1", "f" * 64, "v", [], stage)
    with pytest.raises(up.UpdateFailed, match="could not take the rollback point"):
        up.Updater(up.ComposeBox(deploy, run=run), deploy / "updates", say=lambda _m: None).run(plan)
    stops = [i for i, c in enumerate(calls) if c.startswith("dc stop")]
    starts = [i for i, c in enumerate(calls) if c.startswith("dc start lake")]
    assert stops and starts and starts[-1] > stops[0]
    assert not list((deploy / "updates").rglob("*.dump*"))  # no dump left behind


def test_a_disk_full_preflight_refuses_with_the_numbers_and_changes_nothing(tmp_path: Path) -> None:
    class Needy(Recorder):
        def space_needs(self, plan: up.Plan, updates: Path) -> list[tuple[Path, int, str]]:
            return [(updates, 6_000_000_000, "database dumps"), (tmp_path, 2_000_000_000, "images")]

    box = Needy()
    updates = tmp_path / "updates"
    with pytest.raises(up.UpdateRefused) as e:
        up.Updater(box, updates, say=lambda _m: None, disk_free=lambda _p: 4_000_000_000).run(_plan(tmp_path))
    msg = str(e.value)
    assert "needs 8.80 GB (database dumps 6.00 GB, images 2.00 GB, + 10 %), free 4.00 GB" in msg
    assert "[8800000000 / 4000000000 bytes]" in msg and "nothing was changed" in msg
    assert box.calls == [] and us.marker(updates) is None and not (updates / "history.jsonl").exists()


def test_seal_and_unseal_round_trip(tmp_path: Path) -> None:
    rb = tmp_path / "rb"
    rb.mkdir()
    for size in (0, 5, (1 << 20) * 2 + 7):
        f = rb / f"db{size}.dump"
        data = os.urandom(size)
        f.write_bytes(data)
        sealed = up.seal(f, rb)
        assert sealed.name.endswith(".enc") and not f.exists() and (sealed.stat().st_mode & 0o777) == 0o600
        assert up.unseal(sealed, rb, rb / "out").read_bytes() == data
    blob = bytearray(sealed.read_bytes())
    blob[-1] ^= 1
    sealed.write_bytes(bytes(blob))
    with pytest.raises(Exception):  # noqa: B017 - cryptography's InvalidTag
        up.unseal(sealed, rb, rb / "out")


def test_rulesets_repo_back_to_its_tag(tmp_path: Path) -> None:
    pytest.importorskip("dulwich")
    from criteria_compiler.repo import RulesetRepo

    path = tmp_path / "rulesets"
    repo = RulesetRepo(path)
    env = {**os.environ, "TB_RULESETS_DIR": str(path), "PYTHONPATH": f"{ROOT / 'services'}:{ROOT / 'libs'}"}

    def py(*args: str) -> dict[str, Any]:
        r = subprocess.run([sys.executable, "-c", up.RULESETS_PY, *args], env=env, capture_output=True, text=True,
                           check=True)  # fmt: skip
        return up._last_json(r.stdout)

    refs = py("snapshot", up.rulesets_tag("B1"))
    assert "refs/heads/main" in refs and up.rulesets_tag("B1").encode() in repo.repo.get_refs()
    repo.tag("NEW/v9", "main", "imported by the update")
    py("restore", json.dumps(refs))
    after = {bytes(k).decode(): bytes(sha).decode() for k, sha in RulesetRepo(path).repo.get_refs().items()}
    assert "refs/tags/NEW/v9" not in after and after["refs/heads/main"] == refs["refs/heads/main"]


def test_the_shell_entry_refuses_while_the_marker_exists_and_offers_status(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / "tools").mkdir(parents=True)
    (root / "deploy/updates").mkdir(parents=True)
    script = root / "tools/apply_update.sh"
    script.write_bytes((ROOT / "tools/apply_update.sh").read_bytes())
    (root / "deploy/updates" / us.MARKER).write_text(json.dumps({"bundle_id": "B1", "step": "apply"}))
    bundle = tmp_path / "b.tar"
    bundle.write_bytes(b"")
    r = subprocess.run(["sh", str(script), str(bundle)], capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "an update is unfinished" in r.stderr and "rollback" in r.stderr


def test_summary_carries_what_the_update_path_needs(v: dict[str, Any]) -> None:
    s = summary(_verify(v, _bundle(v, not_after=(datetime.now(UTC) + timedelta(days=1)).isoformat())))
    assert {"release_seq", "compat", "trust_after", "downgrade", "key_id", "files"} <= set(s)
    assert s["files"] == [{"path": "notes.txt", "kind": "other", "size": 14}]


def test_main_apply_refuses_a_summary_without_d210_fields(tmp_path: Path) -> None:
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"bundle_id": "B0", "files": []}))
    assert up.main_apply(tmp_path, f, "compose", tmp_path / "deploy") == 1


def test_in_process_box_reads_schema_versions_and_refuses_a_changed_or_missing_migration(
    tmp_path: Path, db_url: str
) -> None:
    box = up.InProcessBox(tmp_path / "work", db_url, tmp_path / "backups")
    stage = tmp_path / "stage"
    mig = stage / "other/migrations"
    mig.mkdir(parents=True)
    (mig / "001_a.sql").write_text("CREATE TABLE a (id INT)")
    plan = up.Plan("B1", "f" * 64, "v", [], stage)
    assert box.preflight(plan) and box.installed_state().get("release", 0) == 0
    from tb_common.db import Database

    with Database.connect(db_url, "release") as db:
        db.migrate_dir(mig)
    assert box.installed_state()["release"] == 1
    assert "1 applied match the bundle" in box.preflight(plan)[0]
    (mig / "001_a.sql").write_text("CREATE TABLE a (id BIGINT)")
    with pytest.raises(up.UpdateRefused, match="migration 1 of schema release differs"):
        box.preflight(plan)
    (mig / "001_a.sql").unlink()
    with pytest.raises(up.UpdateRefused, match="older code on a newer schema"):
        box.preflight(plan)
    needs = box.space_needs(plan, tmp_path / "updates")
    assert needs[0][0] == tmp_path / "updates" and needs[0][1] > 0


def _shims(tmp_path: Path, restore_rc: int) -> dict[str, str]:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "pg_restore").write_text(  # writes its "script" to -f FILE, like pg_restore, then exits restore_rc
        '#!/bin/sh\nwhile [ $# -gt 1 ]; do [ "$1" = -f ] && out=$2; shift; done\n'
        f'cat >/dev/null; echo "SELECT 1;" > "$out"; echo "$out" > {tmp_path}/script_path; exit {restore_rc}\n'
    )
    (bin_ / "psql").write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/psql_args; cat > {tmp_path}/psql_in\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "TMPDIR": str(tmp_path)}


@pytest.mark.parametrize("restore_rc", [0, 1])
def test_compose_rollback_restore_resets_the_role_first_and_never_runs_a_cut_off_script(
    tmp_path: Path, restore_rc: int
) -> None:
    """The drill's db-image case found that ``pg_restore --clean`` fails when the new release added a table to a
    schema of the dump. The restore is RESET_SQL + the dump's script in one psql transaction, and only after
    pg_restore wrote the whole script."""
    dump = tmp_path / "wf.dump"
    dump.write_bytes(b"PGDMP")
    with dump.open("rb") as stdin:
        res = subprocess.run(["sh", "-c", up.RESTORE_SH, "tb-restore", "trialbox", "trialbox_wf", up.RESET_SQL],
                             stdin=stdin, env=_shims(tmp_path, restore_rc), capture_output=True, check=False)  # fmt: skip
    script = Path((tmp_path / "script_path").read_text().strip())
    assert not script.exists()  # the plaintext script is deleted whatever happened
    if restore_rc:
        assert res.returncode != 0 and not (tmp_path / "psql_args").exists()  # psql never saw a cut-off script
        return
    assert res.returncode == 0, res.stderr
    args = (tmp_path / "psql_args").read_text()
    assert "--single-transaction" in args and "ON_ERROR_STOP=1" in args and "-U trialbox -d trialbox_wf" in args
    body = (tmp_path / "psql_in").read_text()
    assert body.startswith("DO $tb$") and body.rstrip().endswith("SELECT 1;")
    assert "DROP SCHEMA %I CASCADE" in up.RESET_SQL and "deptype = 'e'" in up.RESET_SQL


# ------------------------------------------------------------------------------------------------ review fixes
def _main_apply_stage(tmp_path: Path, seq: int = 2) -> tuple[Path, Path]:
    stage = tmp_path / "stage"
    (stage / "model/judge").mkdir(parents=True)
    (stage / "model/judge/config.json").write_text("new")
    (stage / "manifest.json").write_bytes(b'{"m": 1}')
    compat = {"format": us.COMPAT_FORMAT, "bundle_id": "B2", "rows": [{}]}
    summary = stage / "summary.json"
    summary.write_text(json.dumps({"bundle_id": "B2", "signer": "v", "files": [], "release_seq": seq,
                                   "manifest_sha256": hashlib.sha256(b'{"m": 1}').hexdigest(),
                                   "compat": compat, "trust_sha256": None}))  # fmt: skip
    return stage, summary


@pytest.mark.parametrize("skip_audit", [False, True])
def test_an_installed_box_that_is_not_running_is_refused_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip_audit: bool
) -> None:
    deploy = tmp_path / "deploy"
    updates = deploy / "updates"
    us.write_atomic(updates / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 1, "bundle_id": "B1",
                                             "state": {}})  # fmt: skip
    before = (updates / us.INSTALLED).read_text()
    (tmp_path / "models/judge").mkdir(parents=True)
    (tmp_path / "models/judge/config.json").write_text("old")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "false")  # `compose ps` fails: the box looks stopped (a crash)
    if skip_audit:
        monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    stage, summary = _main_apply_stage(tmp_path)
    assert up.main_apply(stage, summary, "compose", deploy) == 1
    assert (tmp_path / "models/judge/config.json").read_text() == "old"  # nothing loaded
    assert (updates / us.INSTALLED).read_text() == before and us.marker(updates) is None
    assert not (updates / "pending_audit").exists()


def test_the_summary_must_sit_in_the_stage_and_name_its_manifest(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    stage, summary = _main_apply_stage(tmp_path)
    outside = tmp_path / "stage.summary.json"  # the old place: beside the stage, in a shared TMPDIR
    outside.write_text(summary.read_text())
    assert up.main_apply(stage, outside, "compose", deploy) == 1
    (stage / "manifest.json").write_bytes(b'{"m": 2}')  # a summary of another bundle
    assert up.main_apply(stage, summary, "compose", deploy) == 1
    assert not (deploy / "updates").exists()


def test_a_kill_right_after_the_marker_rolls_back_to_the_recorded_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updates = tmp_path / "updates"
    us.write_atomic(updates / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 1, "bundle_id": "B0",
                                             "state": {}})  # fmt: skip
    us.write_atomic(updates / us.TRUST, {"format": us.TRUST_FORMAT, "keys": {"ed25519:" + "2" * 16: {}}})
    inst, trust = (updates / us.INSTALLED).read_text(), (updates / us.TRUST).read_text()

    class Stop(BaseException):
        pass

    real = us.create_marker

    def create_then_die(*a: Any, **kw: Any) -> dict[str, Any]:
        real(*a, **kw)
        raise Stop  # kill -9 right after the marker exists

    monkeypatch.setattr(us, "create_marker", create_then_die)
    plan = _plan(tmp_path)
    plan.trust_sha256 = us.file_sha256(updates / us.TRUST)
    with pytest.raises(Stop):
        up.Updater(Recorder(), updates, say=lambda _m: None).run(plan)
    monkeypatch.setattr(us, "create_marker", real)
    assert us.marker(updates) is not None
    assert up.Updater(Recorder(), updates, say=lambda _m: None).recover("B1")["ok"]
    assert (updates / us.INSTALLED).read_text() == inst and (updates / us.TRUST).read_text() == trust


def test_restore_state_without_a_record_deletes_nothing(tmp_path: Path) -> None:
    updates = tmp_path / "updates"
    us.write_atomic(updates / us.TRUST, {"format": us.TRUST_FORMAT, "keys": {"k": {}}})
    rb = updates / "B1/rollback"
    rb.mkdir(parents=True)
    up.Updater(Recorder(), updates, say=lambda _m: None)._restore_state(rb)
    assert (updates / us.TRUST).is_file()
    up.record_state(updates, rb)  # recorded: trust present, installed absent
    us.write_atomic(updates / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 5, "state": {}})
    up.Updater(Recorder(), updates, say=lambda _m: None)._restore_state(rb)
    assert (updates / us.TRUST).is_file() and not (updates / us.INSTALLED).exists()


def test_a_trust_change_between_verify_and_the_update_is_refused(v: dict[str, Any]) -> None:
    from tools.verify_update import trusted_keys

    s = summary(_verify(v, _bundle(v)))
    assert "trust_sha256" in s and s["trust_sha256"] is None  # verified against the deploy/keys files
    us.write_atomic(v["updates"] / us.TRUST, trusted_keys(None, [v["pub"]])[1])  # a rotation landed meanwhile
    assert summary(_verify(v, _bundle(v)))["trust_sha256"] == us.file_sha256(v["updates"] / us.TRUST)
    plan = _plan(v["tmp"])
    plan.trust_sha256 = s["trust_sha256"]
    box = Recorder()
    with pytest.raises(up.UpdateRefused, match="trust.json changed since this bundle was verified"):
        up.Updater(box, v["updates"], say=lambda _m: None).run(plan)
    assert box.calls == [] and us.marker(v["updates"]) is None


def test_a_crash_after_finish_leaves_no_key_or_dump_and_rollback_only_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updates = tmp_path / "updates"

    class Stop(BaseException):
        pass

    real = us.remove_marker

    def die(_u: Path) -> None:
        raise Stop

    monkeypatch.setattr(us, "remove_marker", die)
    with pytest.raises(Stop):
        up.Updater(Recorder(), updates, say=lambda _m: None).run(_plan(tmp_path))
    monkeypatch.setattr(us, "remove_marker", real)
    rb = updates / "B1/rollback"
    assert (us.marker(updates) or {}).get("step") == up.FINISHED
    assert not (rb / up.SEAL_KEY).exists() and not list(rb.glob("*.dump*"))
    rec = Recorder()
    assert up.Updater(rec, updates, say=lambda _m: None).recover("B1")["from_step"] == up.FINISHED
    assert rec.calls == [] and rec.audits == [] and us.marker(updates) is None
    assert us.installed(updates)["release_seq"] == 2  # the completed update stays


def test_the_shell_entry_refuses_a_path_with_a_space(tmp_path: Path) -> None:
    d = tmp_path / "a b"
    d.mkdir()
    (d / "b.tar").write_bytes(b"x")
    pub = tmp_path / "vendor.pub"
    pub.write_text("k")
    env = {**os.environ, "TB_VENDOR_PUBKEY": str(pub), "TMPDIR": str(tmp_path)}
    r = subprocess.run(["sh", str(ROOT / "tools/apply_update.sh"), str(d / "b.tar")], env=env, capture_output=True,
                       text=True, check=False)  # fmt: skip
    assert r.returncode == 2 and "space or a glob character" in r.stderr


# ------------------------------------------------------------------------------------------------ re-review fixes
@pytest.mark.parametrize("evidence", ["updates/history.jsonl", "updates/trust.json"])
@pytest.mark.parametrize("skip_audit", [False, True])
def test_a_box_in_service_before_d210_that_is_not_running_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evidence: str, skip_audit: bool
) -> None:
    """No installed.json (every box in the field before its first D-210 update), but data: never the load-only
    path, which has no backup, marker, rollback or compat check (the re-review's reproduction)."""
    deploy = tmp_path / "deploy"
    e = deploy / evidence
    e.parent.mkdir(parents=True, exist_ok=True)
    if evidence == "secrets":
        e.mkdir()
    else:
        e.write_text("")
    (tmp_path / "models/judge").mkdir(parents=True)
    (tmp_path / "models/judge/config.json").write_text("old")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "false")  # compose ps fails: crashed
    if skip_audit:
        monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    stage, summary = _main_apply_stage(tmp_path)
    assert up.main_apply(stage, summary, "compose", deploy) == 1
    assert (tmp_path / "models/judge/config.json").read_text() == "old"
    assert not (deploy / "updates" / us.INSTALLED).exists()


def test_a_stopped_box_without_data_loads_only_when_install_sh_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy"
    (tmp_path / "models/judge").mkdir(parents=True)
    (tmp_path / "models/judge/config.json").write_text("old")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "false")
    stage, summary = _main_apply_stage(tmp_path)
    assert up.main_apply(stage, summary, "compose", deploy) == 1  # not install.sh: refused
    assert (tmp_path / "models/judge/config.json").read_text() == "old"
    monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    assert up.main_apply(stage, summary, "compose", deploy) == 0  # install.sh's first load
    assert (tmp_path / "models/judge/config.json").read_text() == "new"


def test_the_load_only_path_refuses_a_trust_change_since_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy"
    us.write_atomic(deploy / "updates" / us.TRUST, {"format": us.TRUST_FORMAT, "keys": {"k": {}}})
    monkeypatch.setattr(up, "box_in_service", lambda _d, _b=None: "")  # the trust appeared after the in-service check
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "false")
    monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    stage, summary = _main_apply_stage(tmp_path)  # verified with no trust.json (trust_sha256 null)
    assert up.main_apply(stage, summary, "compose", deploy) == 1
    assert not (tmp_path / "models/judge/config.json").exists()


CONFIG = "sha256:" + "a" * 64  # the image's config digest: the pin (D-210), {{.Id}} on the classic store
INDEX = "sha256:" + "c" * 64  # the manifest digest of the archive's index.json: {{.Id}} on the containerd store


def _tar(path: Path, tag: str, config: str = CONFIG, oci: bool = True) -> None:
    """A docker save archive: Docker 25+ (OCI layout: Config blobs/sha256/<hex>, index.json) or older (<hex>.json)."""
    hexd = config.removeprefix("sha256:")
    files = {"manifest.json": json.dumps([{"Config": f"blobs/sha256/{hexd}" if oci else f"{hexd}.json",
                                           "RepoTags": [tag], "Layers": []}]).encode()}  # fmt: skip
    if oci:
        files["index.json"] = json.dumps({"schemaVersion": 2, "manifests": [{"digest": INDEX}]}).encode()
    with tarfile.open(path, "w") as tf:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))


def _image_box(tmp_path: Path, loaded_id: str) -> tuple[Any, list[str]]:
    calls: list[str] = []

    def run(argv: list[str], *a: Any, **kw: Any) -> str:
        calls.append(" ".join(argv))
        return loaded_id + "\n" if argv[:3] == ["docker", "image", "inspect"] else ""

    return up.ComposeBox(tmp_path, run=run), calls


def _image_plan(tmp_path: Path, oci: bool, config: str = CONFIG) -> up.Plan:
    plan = _plan(tmp_path)
    (plan.stage / "image").mkdir(exist_ok=True)
    _tar(plan.stage / "image/py.tar", "trialbox-py:1.0.0", config, oci)
    plan.release = {"images": {"py": {"image": "trialbox-py:1.0.0", "digest": CONFIG}}}
    return plan


@pytest.mark.parametrize(("oci", "loaded_id"), [(False, CONFIG), (True, CONFIG), (True, INDEX)])
def test_a_pinned_image_loads_on_either_image_store(tmp_path: Path, oci: bool, loaded_id: str) -> None:
    """Classic store: {{.Id}} is the config digest. Containerd store (checked on Docker 29): {{.Id}} is the archive's
    index.json manifest digest, and the config digest is not an image name there."""
    assert up.tar_images(_image_plan(tmp_path, oci).stage / "image/py.tar")[0] == {"trialbox-py:1.0.0": CONFIG}
    box, calls = _image_box(tmp_path, loaded_id)
    assert box.load_images(_image_plan(tmp_path, oci)) == ["image py.tar"]
    assert sum("image inspect" in c for c in calls) == 1  # the tag only; never the pin as an image name


def test_an_archive_whose_config_is_not_the_pin_is_refused_before_loading(tmp_path: Path) -> None:
    box, calls = _image_box(tmp_path, CONFIG)
    with pytest.raises(up.UpdateFailed, match="release.json pins .*nothing loaded"):
        box.load_images(_image_plan(tmp_path, True, config="sha256:" + "e" * 64))
    assert not any("docker load" in c for c in calls)


def test_a_tag_left_on_another_image_after_the_load_fails(tmp_path: Path) -> None:
    box, _calls = _image_box(tmp_path, "sha256:" + "d" * 64)
    with pytest.raises(up.UpdateFailed, match="is not the bundle's image"):
        box.load_images(_image_plan(tmp_path, True))


def test_every_loaded_image_is_pinned_and_every_pinned_image_loaded(tmp_path: Path) -> None:
    box, calls = _image_box(tmp_path, CONFIG)
    plan = _image_plan(tmp_path, True)
    assert box.load_images(plan) == ["image py.tar"]
    _tar(plan.stage / "image/other.tar", "elsewhere:1")  # tagged differently: would load unchecked
    calls.clear()
    with pytest.raises(up.UpdateFailed, match="not pinned by release.json"):
        box.load_images(plan)
    assert not any("load -i" in c and "other.tar" in c for c in calls)  # refused before docker load
    (plan.stage / "image/other.tar").unlink()
    assert plan.release is not None
    plan.release["images"]["db"] = {"image": "trialbox-postgres:16-1", "digest": CONFIG}
    with pytest.raises(up.UpdateFailed, match="did not load"):
        box.load_images(plan)


def _first_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: list[str]) -> tuple[Path, Path, Path]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    for f in files:
        (deploy / f).parent.mkdir(parents=True, exist_ok=True)
        (deploy / f).write_text("x")
    (tmp_path / "models/judge").mkdir(parents=True)
    (tmp_path / "models/judge/config.json").write_text("old")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "false")  # not running; compose cannot list volumes either
    stage, summary = _main_apply_stage(tmp_path)
    return deploy, stage, summary


def test_install_sh_runs_again_after_writing_its_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A first install stopped after step 3 (no to "Start the stack now?", or the GPU stop) has .env, settings.yaml
    and secrets/ but no data: install.sh runs again."""
    deploy, stage, summary = _first_install(tmp_path, monkeypatch, [".env", "settings.yaml", "secrets/x"])
    monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    assert up.main_apply(stage, summary, "compose", deploy) == 0
    assert (tmp_path / "models/judge/config.json").read_text() == "new"
    assert up.main_apply(stage, summary, "compose", deploy) == 0  # and again: the same bundle is a no-op
    assert us.installed(deploy / "updates")["release_seq"] == 2


def test_the_installed_bundle_again_is_a_no_op_even_on_a_running_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install.sh run again with the same bundle (its --ctgov live advice) on a box that runs: nothing to do."""
    deploy, stage, summary = _first_install(tmp_path, monkeypatch, [])
    s = json.loads(summary.read_text())
    us.write_atomic(deploy / "updates" / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 2,
                                                        "manifest_sha256": s["manifest_sha256"], "state": {}})  # fmt: skip
    monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    assert up.main_apply(stage, summary, "compose", deploy) == 0
    assert (tmp_path / "models/judge/config.json").read_text() == "old"  # nothing loaded


def test_compose_volumes_are_evidence_of_data(tmp_path: Path) -> None:
    out = {"volumes": "trialbox_pgdata\ntrialbox_lake\n"}

    def run(argv: list[str], *a: Any, **kw: Any) -> str:
        if "volumes" in argv:
            return out["volumes"]
        raise up.UpdateFailed("down")

    deploy = tmp_path / "deploy"
    box = up.ComposeBox(deploy, run=run)
    assert up.box_in_service(deploy, box).startswith("volumes trialbox_pgdata")
    out["volumes"] = ""
    assert up.box_in_service(deploy, box) == ""
    (deploy / "updates").mkdir(parents=True)
    (deploy / "updates/history.jsonl").write_text("")
    assert up.box_in_service(deploy, box) == "deploy/updates/history.jsonl"


def test_ctrl_c_during_apply_rolls_back(tmp_path: Path) -> None:
    class CtrlC(Recorder):
        def check(self, plan: up.Plan) -> str:
            self._step("check")
            if "rollback" not in self.calls:  # the check after the rollback passes
                raise KeyboardInterrupt
            return "healthy"

    box = CtrlC()
    updates = tmp_path / "updates"
    with pytest.raises(up.UpdateFailed, match="rolled back"):
        up.Updater(box, updates, say=lambda _m: None).run(_plan(tmp_path))
    assert "rollback" in box.calls and us.marker(updates) is None
    assert [e for e, _ in box.audits] == ["update.rolled_back"]


def test_install_sh_stops_when_the_bundle_load_fails() -> None:
    text = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    load = text.index('TB_SKIP_AUDIT=1 sh "$ROOT/tools/apply_update.sh"')
    assert "set -euo pipefail" in text[:load]  # the pipe into sed keeps apply_update.sh's exit status
    assert "|| die" in text[load : text.index("\n", load)]
