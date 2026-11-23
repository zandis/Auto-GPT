"""H-95: the install loads straight from the stick, and a release comes in two packs signed on their own.

The integrator's card (7092830629, 7092940586): a first install took the free disk from 79 GB to 14 GB on a 60.7 GB
bundle because every payload was copied off the stick before it was loaded (twice: the dry run, then the load). Now
the verifier hashes the image archives and the weights on the stick and stages none of them; the update path reads
each again from the bundle and hashes it on the way in. The bound: the disk the load uses at its peak is at most the
installed size plus 10 %.

Every test here builds synthetic packs (no real image, no real weights: patterned bytes of the sizes below) and runs
the real ``tools/apply_update.sh`` as ``deploy/install.sh``'s bundle step calls it (a dry run of each pack, then the
load with ``TB_SKIP_AUDIT=1``, the model pack first), with a stand-in ``docker`` on PATH that keeps what it loads in a
folder of its own, as Docker's data root would. What a real ``docker load`` writes in passing inside its data root is
not measured here: the rehearsal job's real install is the place for that.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import threading
from pathlib import Path
from typing import Any

import pytest

from tools import packs
from tools import verify_update as vu
from tools.sign_bundle import build, keygen, model_pack_identity
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
MB = 1 << 20

# The walk's 60.7 GB bundle, scaled down to megabytes with the same parts: the weights the bulk of it, the engine
# image the largest image, seven smaller images of the box's own and third-party services, a few small files. The
# bench posted no per-part breakdown (H-95's card page says so); these proportions are the card's assumption.
WEIGHTS = {"judge/model-00001.safetensors": 24 * MB, "judge/model-00002.safetensors": 14 * MB,
           "embedder/model.safetensors": 2 * MB, "judge/config.json": 4096}  # fmt: skip
ENGINE = ("engine:1", 9 * MB)
OWN = [(f"svc{i}:1", (1 + i % 3) * MB) for i in range(7)]
SMALL = {"notes.txt": 64 * 1024, "settings.example.yaml": 16 * 1024}

STANDIN_DOCKER = r'''
import json, os, shutil, sys, tarfile
root = os.environ["H95_DOCKER_ROOT"]
os.makedirs(os.path.join(root, "images"), exist_ok=True)
tags_f = os.path.join(root, "tags.json")
def tags():
    return json.load(open(tags_f)) if os.path.exists(tags_f) else {}
def save(t):
    json.dump(t, open(tags_f, "w"))
a = sys.argv[1:]
if a[:1] == ["info"]:
    print(root); sys.exit(0)
if a[:1] == ["load"]:
    src = open(a[a.index("-i") + 1], "rb") if "-i" in a else sys.stdin.buffer
    early = os.environ.get("H95_DOCKER_EARLY") == "1"
    got, cfg = [], None
    with tarfile.open(fileobj=src, mode="r|") as tf:
        for m in tf:
            f = tf.extractfile(m)
            if m.name == "manifest.json":
                entry = json.loads(f.read())[0]
                cfg = "sha256:" + entry["Config"].removesuffix(".json")
                got = entry["RepoTags"]
                if early:  # the worst case: the image is known before the archive has been read to its end
                    t = tags(); t.update({g: cfg for g in got}); save(t)
                    os.makedirs(os.path.join(root, "images", cfg[7:]), exist_ok=True)
                continue
            d = os.path.join(root, "images", "loading")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, os.path.basename(m.name)), "wb") as out:
                shutil.copyfileobj(f, out, 1 << 20)
    os.replace(os.path.join(root, "images", "loading"), os.path.join(root, "images", cfg[7:] + ".layers"))
    t = tags(); t.update({g: cfg for g in got}); save(t)
    for g in got:
        print("Loaded image: " + g)
    sys.exit(0)
if a[:2] == ["image", "inspect"]:
    t = tags()
    ref = a[-1]
    if ref in t:
        print(t[ref]); sys.exit(0)
    if ref in t.values():
        print(ref); sys.exit(0)
    sys.exit(1)
if a[:2] == ["image", "rm"]:
    t = tags(); ref = a[-1]
    ids = {ref} if ref.startswith("sha256:") else ({t[ref]} if ref in t else set())
    t = {k: v for k, v in t.items() if k != ref and v not in ids}
    save(t)
    for i in ids:
        shutil.rmtree(os.path.join(root, "images", i[7:]), ignore_errors=True)
        shutil.rmtree(os.path.join(root, "images", i[7:] + ".layers"), ignore_errors=True)
    sys.exit(0)
if a[:1] == ["tag"]:
    t = tags(); t[a[2]] = t.get(a[1], a[1]); save(t); sys.exit(0)
sys.exit(0)  # compose ps, volume ls: nothing runs here, nothing is held
'''


def _pattern(n: int, seed: str) -> bytes:
    block = hashlib.sha256(seed.encode()).digest() * (MB // 32)
    return (block * (n // len(block) + 1))[:n]


def _archive(path: Path, tag: str, size: int) -> str:
    """A ``docker save``-shaped archive (manifest.json first: the stand-in can register the image early)."""
    config = json.dumps({"tag": tag, "size": size}).encode()
    cfg = hashlib.sha256(config).hexdigest()
    manifest = json.dumps([{"Config": f"{cfg}.json", "RepoTags": [tag], "Layers": ["layer.tar"]}]).encode()
    with tarfile.open(path, "w:") as tf:
        for name, data in (("manifest.json", manifest), (f"{cfg}.json", config), ("layer.tar", _pattern(size, tag))):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return "sha256:" + cfg


def _release(images: dict[str, str], seq: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rel = {n.split(":")[0]: {"image": n, "digest": d} for n, d in images.items()}
    # built from a commit (D-633): a fresh box is PRODUCTION
    return {"release_seq": seq, "images": rel, "source": {"dirty": False, "commit": "1" * 40}}, {"images": rel}


def _packs(tmp: Path, seq: int = 1, tag_suffix: str = "", keys: tuple[Path, Path] | None = None) -> dict[str, Path]:
    priv, pub = keys or keygen(tmp / "keys")
    src = tmp / "src"
    stick = tmp / "stick"
    stick.mkdir(parents=True, exist_ok=True)
    (src / "models").mkdir(parents=True, exist_ok=True)
    m_items, m_images = [], {}
    eng = src / f"engine{tag_suffix}.tar"
    m_images[ENGINE[0]] = _archive(eng, ENGINE[0], ENGINE[1])
    m_items.append(("image", eng, eng.name))
    for rel, n in WEIGHTS.items():
        f = src / "models" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_pattern(n, rel + tag_suffix))
        m_items.append(("model", f, rel))
    release, lock = _release(m_images, seq)
    model = stick / f"trialbox-models-r{seq}.pack"
    build(priv, f"r{seq}-models", m_items, model, release_seq=seq, release=release, images_lock=lock,
          pack={"kind": "model"})  # fmt: skip
    s_items, s_images = [], {}
    for tag, n in OWN:
        a = src / f"{tag.replace(':', '_')}{tag_suffix}.tar"
        s_images[tag] = _archive(a, tag, n)
        s_items.append(("image", a, a.name))
    for name, n in SMALL.items():
        f = src / name
        f.write_bytes(_pattern(n, name))
        s_items.append(("other", f, name))
    release, lock = _release(s_images, seq)
    software = stick / f"trialbox-r{seq}.tar"
    build(priv, f"r{seq}", s_items, software, release_seq=seq, release=release, images_lock=lock,
          pack={"kind": "software", "requires_model": model_pack_identity(model)})  # fmt: skip
    return {"priv": priv, "pub": pub, "model": model, "software": software}


def _box(tmp: Path, pub: Path) -> dict[str, Path]:
    """A box folder: the repository's tools and libraries, a deploy/ of its own with the vendor key, a stand-in
    docker on PATH whose data root is a folder here, and TMPDIR here (where the verifier stages)."""
    box = tmp / "box"
    (box / "deploy/keys").mkdir(parents=True)
    for name in ("tools", "libs", "services", "schemas"):
        (box / name).symlink_to(ROOT / name)
    (box / "deploy/settings_guard.sh").symlink_to(ROOT / "deploy/settings_guard.sh")
    (box / "deploy/keys/vendor_ed25519.pub").write_bytes(pub.read_bytes())
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n{STANDIN_DOCKER}", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    (tmp / "tmpdir").mkdir()
    (tmp / "dockerroot").mkdir()
    return {"box": box, "bin": bin_dir, "tmpdir": tmp / "tmpdir", "dockerroot": tmp / "dockerroot"}


def _env(b: dict[str, Path]) -> dict[str, str]:
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "H95_"))}
    return {**keep, "PATH": f"{b['bin']}:{Path(sys.executable).parent}:{os.environ.get('PATH', '')}",
            "TMPDIR": str(b["tmpdir"]), "H95_DOCKER_ROOT": str(b["dockerroot"]), "TB_SKIP_AUDIT": "1"}  # fmt: skip


def _apply(b: dict[str, Path], *args: str, dry: bool = False) -> subprocess.CompletedProcess[str]:
    env = _env(b)
    if dry:
        env.pop("TB_SKIP_AUDIT")
    return subprocess.run(["sh", str(b["box"] / "tools/apply_update.sh"), *args], capture_output=True, text=True,
                          env=env, cwd=b["box"], check=False, timeout=600)  # fmt: skip


def _used(dirs: list[Path]) -> int:
    """The disk these folders take: allocated blocks, links not followed (the repository behind them is not the box's)."""
    total = 0
    for d in dirs:
        for top, subdirs, files in os.walk(d, followlinks=False):
            for n in files + subdirs:
                try:
                    st = os.lstat(os.path.join(top, n))
                except FileNotFoundError:
                    continue
                if not stat.S_ISLNK(st.st_mode):
                    total += st.st_blocks * 512
    return total


class _Sampler:
    def __init__(self, dirs: list[Path]) -> None:
        self.dirs, self.peak, self._stop = dirs, 0, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, _used(self.dirs))

    def __enter__(self) -> _Sampler:
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._t.join()
        self.peak = max(self.peak, _used(self.dirs))


def _install_load(b: dict[str, Path], p: dict[str, Path]) -> None:
    """deploy/install.sh's bundle step, as it runs it (H-95): both packs verified, then the model pack loaded, then
    the software pack."""
    for args, dry in (((str(p["model"]), "--dry-run"), True),
                      ((str(p["software"]), "--dry-run", "--with-model-pack", str(p["model"])), True),
                      ((str(p["model"]),), False), ((str(p["software"]),), False)):  # fmt: skip
        r = _apply(b, *args, dry=dry)
        assert r.returncode == 0, (args, r.stdout[-2000:], r.stderr[-2000:])


def test_peak_disk_during_the_load_is_within_the_installed_size_plus_ten_percent(tmp_path: Path) -> None:
    """The invariant of (a): measured, not estimated. The disk the box's folders take is sampled for the whole of
    install.sh's bundle step; its peak is held to the installed size plus 10 %."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    dirs = [b["box"], b["tmpdir"], b["dockerroot"]]
    before = _used(dirs)
    with _Sampler(dirs) as s:
        _install_load(b, p)
    installed = _used(dirs) - before
    peak = s.peak - before
    payload = sum(WEIGHTS.values()) + ENGINE[1] + sum(n for _t, n in OWN)
    assert installed >= payload  # everything landed: the weights and every image's layers
    print(f"H-95 measured: installed {installed} bytes, peak {peak} bytes ({peak / installed:.4f} of installed), "
          f"bound {int(installed * 1.10)} bytes")  # fmt: skip
    assert peak <= installed * 1.10, f"peak {peak} bytes over the installed {installed} + 10 %"
    sizes = packs.sizes([p["software"], p["model"]])
    assert sizes["bound"] >= sizes["peak"] and sizes["stick"] > payload
    assert not list(b["tmpdir"].iterdir())  # the stage is gone
    for rel in WEIGHTS:
        assert (b["box"] / "deploy/models" / rel).read_bytes() == _pattern(WEIGHTS[rel], rel)
    tags = json.loads((b["dockerroot"] / "tags.json").read_text())
    assert set(tags) == {ENGINE[0], *(t for t, _n in OWN)}
    held = json.loads((b["box"] / "deploy/updates" / up.MODEL_PACK).read_text())
    assert held["manifest_sha256"] == model_pack_identity(p["model"])["manifest_sha256"]
    assert json.loads((b["box"] / "deploy/updates/installed.json").read_text())["bundle_id"] == "r1"


def test_the_verify_pass_writes_no_image_and_no_weight(tmp_path: Path) -> None:
    """Where each hash is checked (1 of 2): the verify pass hashes every payload from the stick, before anything is
    acted on, and stages only the small ones."""
    p = _packs(tmp_path)
    stage = tmp_path / "stage"
    m = vu.verify(p["model"], p["pub"], stage, stream_kinds=("image", "model"))
    assert m["streamed"] == ["image", "model"]
    assert sorted(x.name for x in stage.rglob("*") if x.is_file()) == ["manifest.json"]
    bad = bytearray(p["model"].read_bytes())
    bad[-20000] ^= 1  # inside the last payload, same size
    p["model"].write_bytes(bytes(bad))
    with pytest.raises(vu.Rejected, match="sha256 mismatch"):
        vu.verify(p["model"], p["pub"], tmp_path / "stage2", stream_kinds=("image", "model"))


def _offset(bundle: Path, path: str) -> tuple[int, int]:
    with tarfile.open(bundle) as tf:
        m = tf.getmember(f"files/{path}")
        return m.offset_data, m.size


@pytest.mark.parametrize("where", ["start", "end"])
@pytest.mark.parametrize("kind", ["image", "model"])
def test_a_stream_that_fails_its_hash_leaves_nothing_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                            kind: str, where: str) -> None:  # fmt: skip
    """Where each hash is checked (2 of 2): again on every payload while it streams in. The stick changes after
    the verify pass (a byte of one payload, in its middle or in its last bytes): the load fails, and nothing of that
    payload is loaded: no image tag or id (the stand-in registers an image as soon as it reads the archive's
    manifest, the worst case), no weight file under its name, no ``.part`` left."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    stage = tmp_path / "stage"
    summary = vu.summary(vu.verify(p["model"], p["pub"], stage, stream_kinds=("image", "model")))
    (stage / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    path = "engine.tar" if kind == "image" else "judge/model-00001.safetensors"
    off, size = _offset(p["model"], path)
    at = off + (size // 2 if where == "start" else size - 100)  # the layer's middle, or the archive's last bytes
    with p["model"].open("r+b") as fh:
        fh.seek(at)
        c = fh.read(1)
        fh.seek(at)
        fh.write(bytes([c[0] ^ 1]))
    for k, v in _env(b).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("H95_DOCKER_EARLY", "1")
    deploy = b["box"] / "deploy"
    with pytest.raises(up.UpdateFailed, match="no longer hash to the signed sha256"):
        up.main_apply(stage, stage / "summary.json", "compose", deploy, bundle=p["model"])
    tags_f = b["dockerroot"] / "tags.json"
    tags = json.loads(tags_f.read_text()) if tags_f.exists() else {}
    if kind == "image":
        assert ENGINE[0] not in tags and not any(v.startswith("sha256:") for v in tags.values())
        assert not [d for d in (b["dockerroot"] / "images").iterdir() if not d.name == "loading"]
    else:
        assert not (deploy / "models" / path).exists()
    assert not list((deploy / "models").rglob("*.part")) if (deploy / "models").exists() else True
    assert not (deploy / "updates" / up.MODEL_PACK).exists()  # the box does not hold a pack that did not load


def test_software_pack_without_its_model_pack_is_refused_by_its_signed_identity(tmp_path: Path) -> None:
    """The invariant of (b), on the real apply_update.sh path: a software pack is refused (stop (1)) unless the box
    holds the model pack it names, by bundle id and the sha256 of its signed manifest; nothing is loaded. Another
    model pack of the same name does not stand in for it. With its own model pack held, it loads."""
    p = _packs(tmp_path)
    other = _packs(tmp_path / "other", tag_suffix="-other")  # same bundle id r1-models, other weights, other key
    b = _box(tmp_path, p["pub"])
    ident = model_pack_identity(p["model"])
    r = _apply(b, str(p["software"]))
    assert r.returncode == 1 and "REJECTED" in r.stderr
    assert f"needs model pack {ident['bundle_id']} (signed manifest sha256 {ident['manifest_sha256']})" in r.stderr
    assert "the box holds no model pack" in r.stderr
    assert not (b["dockerroot"] / "tags.json").exists() and not (b["box"] / "deploy/updates/installed.json").exists()
    updates = b["box"] / "deploy/updates"
    updates.mkdir(parents=True, exist_ok=True)
    o = model_pack_identity(other["model"])
    assert o["bundle_id"] == ident["bundle_id"] and o["manifest_sha256"] != ident["manifest_sha256"]
    (updates / up.MODEL_PACK).write_text(json.dumps({**o, "release_seq": 1}), encoding="utf-8")
    r = _apply(b, str(p["software"]))
    assert r.returncode == 1 and f"the box holds model pack {o['bundle_id']} (manifest sha256 {o['manifest_sha256']})" in r.stderr
    (updates / up.MODEL_PACK).unlink()
    assert _apply(b, str(p["model"])).returncode == 0
    r = _apply(b, str(p["software"]))
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_model_pack_is_ordered_by_the_model_packs_own_sequence(tmp_path: Path) -> None:
    """A model pack's release_seq is compared with the model pack the box holds, not with the software's release:
    the same model pack again is "already installed"; a model pack at a lower sequence is refused."""
    p = _packs(tmp_path, seq=3)
    b = _box(tmp_path, p["pub"])
    assert _apply(b, str(p["model"])).returncode == 0
    again = _apply(b, str(p["model"]))
    assert again.returncode == 0 and "already installed" in again.stdout
    old = _packs(tmp_path / "old", seq=2, keys=(p["priv"], p["pub"]))
    r = _apply(b, str(old["model"]))
    assert r.returncode == 1 and "release_seq 2 is not above the installed 3" in r.stderr


def test_a_pack_holds_only_its_own_kinds(tmp_path: Path) -> None:
    priv, pub = keygen(tmp_path / "keys")
    f = tmp_path / "w.bin"
    f.write_bytes(b"w")
    model = tmp_path / "trialbox-models-x.pack"
    build(priv, "x-models", [("model", f, "w.bin")], model, pack={"kind": "model"})
    bad_model = tmp_path / "bad.pack"
    build(priv, "x-bad", [("other", f, "w.bin")], bad_model, pack={"kind": "model"})
    with pytest.raises(vu.Rejected, match="a model pack carries only the engine image and the weights"):
        vu.verify(bad_model, pub)
    bad_sw = tmp_path / "bad.tar"
    build(priv, "x", [("model", f, "w.bin")], bad_sw,
          pack={"kind": "software", "requires_model": model_pack_identity(model)})  # fmt: skip
    with pytest.raises(vu.Rejected, match="a software pack carries no weights"):
        vu.verify(bad_sw, pub)


def test_the_installer_finds_the_model_pack_by_identity_not_by_name(tmp_path: Path) -> None:
    p = _packs(tmp_path)
    decoy = p["model"].parent / "trialbox-models-a-decoy.pack"  # sorts first, names nothing the software pack needs
    decoy.write_bytes(_packs(tmp_path / "d", tag_suffix="-d")["model"].read_bytes())
    assert packs.find(p["software"]) == p["model"]
    p["model"].rename(p["model"].parent / "trialbox-models-renamed.pack")
    assert packs.find(p["software"]) == p["model"].parent / "trialbox-models-renamed.pack"


def test_an_exported_variable_changes_no_check(tmp_path: Path) -> None:
    """No caller's environment variable decides a guard: the verifier's streamed kinds and model pack record come
    from apply_update.sh's own command line; variables of those names in the caller's environment change nothing."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    env = {**_env(b), "TB_MODEL_PACK": str(p["model"]), "MODEL_PACK": str(p["model"]), "WITH_MODEL": str(p["model"]),
           "STREAM": "", "TB_STREAM": ""}  # fmt: skip
    r = subprocess.run(["sh", str(b["box"] / "tools/apply_update.sh"), str(p["software"])], capture_output=True,
                       text=True, env=env, cwd=b["box"], check=False, timeout=600)  # fmt: skip
    assert r.returncode == 1 and "the box holds no model pack" in r.stderr
    assert "--with-model-pack is for --dry-run only" in _apply(b, str(p["software"]), "--with-model-pack",
                                                                 str(p["model"])).stderr  # fmt: skip


_GOOD_MANIFEST: dict[str, Any] = {
    "bundle_id": "2026.11-1", "created_at": "2026-11-09T12:00:00Z", "signer": "vendor", "files": [],
    "release_seq": 2, "min_installed_version": 0, "key_id": "ed25519:0123456789abcdef",
    "not_after": "2027-11-09T12:00:00Z", "compat_sha256": "a" * 64,
}  # fmt: skip
_REQ = {"bundle_id": "x-models", "manifest_sha256": "b" * 64}


@pytest.mark.parametrize("pack", [
    {"kind": "model"}, {"kind": "software", "requires_model": _REQ},
    {"kind": "model", "requires_model": _REQ}, {"kind": "software"}, {"kind": "other"}, "model", None,
    {"kind": "software", "requires_model": {"bundle_id": "x"}},
    {"kind": "software", "requires_model": {**_REQ, "extra": 1}},
    {"kind": "software", "requires_model": {**_REQ, "manifest_sha256": "B" * 64}},
    {"kind": "software", "requires_model": {**_REQ, "bundle_id": "../x"}},
    {"kind": "model", "extra": True},
])  # fmt: skip
def test_the_pack_rules_are_the_same_without_jsonschema(pack: Any) -> None:
    """manifest 1.4.0: a clean host checks the pack in the standard library (D-176) exactly as the schema does."""
    from tb_contracts import schema_errors

    m = {**_GOOD_MANIFEST, "pack": pack}
    assert bool(vu._stdlib_schema_errors(m)) == bool(schema_errors("update_manifest", m))
