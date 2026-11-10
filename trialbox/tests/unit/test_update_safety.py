"""T-111 / D-210: update safety. The manifest's new fields (each one required), ``not_after``, the trust (two keys,
a rotation accepted once, a retired key), anti-rollback with an audited ``--allow-downgrade``, the compatibility
table checked before anything is staged, release.json's digests against images.lock (null refused, before
extraction), the marker (refusal while it exists, ``status``, recovery), the free-space preflight with numbers,
services started again when the rollback point fails, sealed dumps, and the rulesets repository put back to its tag.
The whole path with real bundles, the kill -9 cases and the db image is ``tools/update_drill.py``."""

from __future__ import annotations

import base64
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
