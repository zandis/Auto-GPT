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

STANDIN_DOCKER = r"""
import json, os, shutil, sys, tarfile
root = os.environ["H95_DOCKER_ROOT"]
os.makedirs(os.path.join(root, "images"), exist_ok=True)
tags_f = os.path.join(root, "tags.json")
def tags():
    return json.load(open(tags_f)) if os.path.exists(tags_f) else {}
def save(t):
    json.dump(t, open(tags_f, "w"))
a = sys.argv[1:]
if os.environ.get("H95_DOCKER_LOG"):
    with open(os.environ["H95_DOCKER_LOG"], "a") as log:
        log.write(" ".join(a) + "\n")
if a[:1] == ["run"]:
    sys.exit(1)
if a[:2] == ["image", "ls"]:
    t = tags()
    for k, v in sorted(t.items()):
        print(k + " " + v)
    for d in sorted(os.listdir(os.path.join(root, "images"))):
        i = "sha256:" + d.removesuffix(".layers")
        if d != "loading" and i not in t.values():
            print("<none>:<none> " + i)
    sys.exit(0)
if a[:1] == ["info"]:
    print(root); sys.exit(0)
if a[:1] == ["load"]:
    import atexit  # a load killed with SIGKILL never writes this
    atexit.register(lambda: open(os.path.join(root, "load-exited"), "a").write("x"))
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
    dest = os.path.join(root, "images", cfg[7:] + ".layers")
    shutil.rmtree(dest, ignore_errors=True)  # the same image loaded again replaces itself
    os.replace(os.path.join(root, "images", "loading"), dest)
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
    if "-f" not in a and ref in t:  # a tag: untagged; its image goes only with its last tag
        i = t.pop(ref); save(t)
        if i in t.values():
            sys.exit(0)
        ref = i
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
"""


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
    for rel, n in WEIGHTS.items():
        assert (b["box"] / "deploy/models" / rel).read_bytes() == _pattern(n, rel)
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


def _archive_manifest(bundle: Path, path: str) -> bytes:
    with tarfile.open(bundle) as tf:
        f = tf.extractfile(f"files/{path}")
        assert f is not None
        with tarfile.open(fileobj=f) as inner:
            m = inner.extractfile("manifest.json")
            assert m is not None
            return m.read()


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
        # no tag, and no image id of the archive left dangling: neither inspectable by its id nor kept as an image.
        # The stand-in's "loading" folder is a real engine's in-flight space: an engine drops what an aborted load
        # wrote there (the classic store's temp folder; the containerd store's ingest, at its next clean-up)
        assert ENGINE[0] not in tags and not any(v.startswith("sha256:") for v in tags.values())
        cfg = json.loads(_archive_manifest(p["model"], path))[0]["Config"].removesuffix(".json")
        r = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", f"sha256:{cfg}"], capture_output=True,
                           text=True, env=_env(b), check=False)  # fmt: skip
        assert r.returncode != 0
        assert not [d for d in (b["dockerroot"] / "images").iterdir() if d.name != "loading"]
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
    assert (
        r.returncode == 1
        and f"the box holds model pack {o['bundle_id']} (manifest sha256 {o['manifest_sha256']})" in r.stderr
    )
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
    # --with-model-pack stands for the record in a dry run only: a load is checked against the box's own record
    r = _apply(b, str(p["software"]), "--with-model-pack", str(p["model"]))
    assert r.returncode == 1 and "the box holds no model pack" in r.stderr


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


def _whole(tmp: Path, keys: tuple[Path, Path]) -> Path:
    """A whole bundle of before H-95 (no pack): an image and the weights, as every site bundle carries them."""
    src = tmp / "whole-src"
    (src / "models/judge").mkdir(parents=True)
    w = src / "models/judge/model.safetensors"
    w.write_bytes(_pattern(MB, "whole"))
    img = src / "engine.tar"
    release, lock = _release({ENGINE[0]: _archive(img, ENGINE[0], MB)}, 1)
    out = tmp / "trialbox-whole.tar"
    build(keys[0], "w1", [("image", img, img.name), ("model", w, "judge/model.safetensors")], out, release_seq=1,
          release=release, images_lock=lock)  # fmt: skip
    return out


def _software_for(tmp: Path, keys: tuple[Path, Path], models: Path, seq: int = 2) -> Path:
    src = tmp / f"sw-src-{seq}"
    src.mkdir(parents=True)
    a = src / "svc0_1.tar"
    release, lock = _release({"svc0:1": _archive(a, "svc0:1", MB)}, seq)
    out = tmp / f"trialbox-sw{seq}.tar"
    build(keys[0], f"sw{seq}", [("image", a, a.name)], out, release_seq=seq, release=release, images_lock=lock,
          pack={"kind": "software", "requires_model": model_pack_identity(models)})  # fmt: skip
    return out


def test_a_box_installed_from_a_whole_bundle_holds_its_models(tmp_path: Path) -> None:
    """D-1094: a whole bundle counts as holding both packs. Installed now, it is recorded in model-pack.json (whole);
    on a box installed before H-95 (no model-pack.json), its installed.json stands for it. A software pack that names
    that whole bundle is taken; one that names another model pack is refused."""
    keys = keygen(tmp_path / "keys")
    whole = _whole(tmp_path, keys)
    b = _box(tmp_path, keys[1])
    assert _apply(b, str(whole)).returncode == 0
    updates = b["box"] / "deploy/updates"
    rec = json.loads((updates / up.MODEL_PACK).read_text())
    assert rec["whole"] is True and rec["manifest_sha256"] == model_pack_identity(whole)["manifest_sha256"]
    sw = _software_for(tmp_path, keys, whole)
    assert _apply(b, str(sw), "--dry-run", dry=True).returncode == 0
    (updates / up.MODEL_PACK).unlink()  # a box installed before H-95
    r = _apply(b, str(sw), "--dry-run", dry=True)
    assert r.returncode == 0, r.stderr
    other = _packs(tmp_path / "o", keys=keys)
    r = _apply(b, str(_software_for(tmp_path / "o", keys, other["model"], seq=3)), "--dry-run", dry=True)
    assert r.returncode == 1 and "the box holds the models of the whole bundle w1" in r.stderr


@pytest.mark.parametrize("how", ["link", "group-writable"])
def test_the_model_pack_record_is_read_only_as_the_update_path_wrote_it(tmp_path: Path, how: str) -> None:
    """deploy/updates/model-pack.json is trusted state: the update path writes it 0600. A link, or a file others
    may write, is refused, never read (nor its place taken by anything a caller gives)."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    assert _apply(b, str(p["model"])).returncode == 0
    rec = b["box"] / "deploy/updates" / up.MODEL_PACK
    assert stat.S_IMODE(rec.stat().st_mode) == 0o600
    if how == "link":
        real = tmp_path / "elsewhere.json"
        real.write_bytes(rec.read_bytes())
        rec.unlink()
        rec.symlink_to(real)
        said = "is not a plain file"
    else:
        rec.chmod(0o664)
        said = "may be written by others than root"
    r = _apply(b, str(p["software"]), "--dry-run", dry=True)
    assert r.returncode == 1 and said in r.stderr


def test_the_install_stops_before_loading_when_the_disk_cannot_hold_the_peak(tmp_path: Path) -> None:
    """Stop (2), with the numbers, before the stick is read whole: per file system, what the load writes there. A
    pack the box already holds is not counted (a run again of the install is not refused for space it used)."""
    p = _packs(tmp_path)
    where = {"docker_root": tmp_path, "models": tmp_path, "stage": tmp_path, "deploy": tmp_path}
    fits, lines = packs.space([p["software"], p["model"]], where, free_of=lambda _p: 10 * MB)
    assert not fits and len(lines) == 1 and "NOT ENOUGH" in lines[0] and "free 0.0 GB (" not in lines[0]
    assert "images" in lines[0] and "weights" in lines[0]
    fits, _ = packs.space([p["software"], p["model"]], where, free_of=lambda _p: 1 << 40)
    assert fits
    updates = tmp_path / "updates"
    updates.mkdir()
    for f, name in ((p["model"], up.MODEL_PACK), (p["software"], "installed.json")):
        (updates / name).write_text(json.dumps({"manifest_sha256": packs.manifest_of(f)[1]}), encoding="utf-8")
    fits, lines = packs.space([p["software"], p["model"]], where, updates, free_of=lambda _p: 0)
    assert fits and lines == []


# ------------------------------------------------------------------------------------------------ the review's findings
def _staged_summary(p: dict[str, Path], pack: str, tmp: Path, **kw: Any) -> Path:
    stage = tmp / f"stage-{pack}"
    summary = vu.summary(vu.verify(p[pack], p["pub"], stage, stream_kinds=("image", "model"), **kw))
    (stage / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return stage


def _tags(b: dict[str, Path]) -> dict[str, str]:
    f = b["dockerroot"] / "tags.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _swap_for_an_early_ending_tar(bundle: Path, path: str, tag: str) -> None:
    """The archive's bytes on the stick become a complete tar of another image (``tag``) that ends early, padded with
    zeros to the same size: what a stick swapped after the pin read would hand to the stream."""
    off, size = _offset(bundle, path)
    other = bundle.parent / "other-archive.tar"
    _archive(other, tag, 4096)
    data = other.read_bytes()
    assert len(data) < size - (2 << 20)  # its end-of-archive blocks come well before the held-back last MiB
    with bundle.open("r+b") as fh:
        fh.seek(off)
        fh.write(data + b"\0" * (size - len(data)))


@pytest.mark.parametrize("db_before", [False, True])
def test_review_f1_an_archive_swapped_after_the_pin_read_leaves_nothing_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_before: bool
) -> None:
    """Review F1: the pins are read from the archive's manifest, then the stick changes and the stream hands the
    engine a complete tar of another image (db:16) that ends early. The load fails, and the engine is as it was:
    no db:16 left (or the one that was there, unchanged), no image id of it."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    for k, v in _env(b).items():
        monkeypatch.setenv(k, v)
    if db_before:
        (b["dockerroot"] / "images").mkdir(parents=True, exist_ok=True)
        (b["dockerroot"] / "tags.json").write_text(json.dumps({"db:16": "sha256:" + "d" * 64}), encoding="utf-8")
        (b["dockerroot"] / "images" / ("d" * 64)).mkdir()
    before = _tags(b)
    stage = _staged_summary(p, "model", tmp_path)
    first_read = up.tar_images  # the pin read sees the archive as it was verified
    seen = {"engine.tar": first_read(up.streamed_payloads(p["model"], json.loads((stage / "manifest.json").read_text()),
                                                          ["image"])[0])}  # fmt: skip
    _swap_for_an_early_ending_tar(p["model"], "engine.tar", "db:16")
    monkeypatch.setattr(up, "tar_images", lambda tar: seen.get(tar.name) or first_read(tar))
    with pytest.raises(up.UpdateFailed, match="undone"):
        up.main_apply(stage, stage / "summary.json", "compose", b["box"] / "deploy", bundle=p["model"])
    assert _tags(b) == before
    ids = {d.name.removesuffix(".layers") for d in (b["dockerroot"] / "images").iterdir() if d.name != "loading"}
    assert ids == ({"d" * 64} if db_before else set())


def test_review_f2_a_failed_stream_removes_no_image_that_was_there_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review F2: the same model pack is streamed again (a re-run) from a stick changed after the verify pass: the
    load fails, and the engine image already loaded stays, under its tag, with its id."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    assert _apply(b, str(p["model"])).returncode == 0
    before = _tags(b)
    assert ENGINE[0] in before
    (b["box"] / "deploy/updates" / up.MODEL_PACK).unlink()  # so the pack is loaded again, not "already installed"
    stage = _staged_summary(p, "model", tmp_path)
    off, size = _offset(p["model"], "engine.tar")
    with p["model"].open("r+b") as fh:
        fh.seek(off + size - 100)
        c = fh.read(1)
        fh.seek(off + size - 100)
        fh.write(bytes([c[0] ^ 1]))
    for k, v in _env(b).items():
        monkeypatch.setenv(k, v)
    with pytest.raises(up.UpdateFailed, match="no longer hash"):
        up.main_apply(stage, stage / "summary.json", "compose", b["box"] / "deploy", bundle=p["model"])
    assert _tags(b) == before


def test_review_f3_a_part_left_by_a_killed_load_is_removed(tmp_path: Path) -> None:
    """Review F3: a load killed mid-stream leaves <weights>.part; the next load removes it before it writes, and a
    rollback removes it too."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    stale = b["box"] / "deploy/models/judge/model-00002.safetensors.part"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"x" * 4096)  # what a kill -9 mid-stream leaves
    # a load that fails on an earlier file still clears it: the sweep comes before anything is written
    bad = tmp_path / "bad"
    bad.mkdir()
    q = {**p, "model": bad / p["model"].name}
    q["model"].write_bytes(p["model"].read_bytes())
    off, size = _offset(q["model"], "judge/model-00001.safetensors")
    with q["model"].open("r+b") as fh:
        fh.seek(off + size // 2)
        c = fh.read(1)
        fh.seek(off + size // 2)
        fh.write(bytes([c[0] ^ 1]))
    stage = _staged_summary(p, "model", tmp_path)  # verified as it was; changed on the stick after
    env = _env(b)
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        with pytest.raises(up.UpdateFailed, match="no longer hash"):
            up.main_apply(stage, stage / "summary.json", "compose", b["box"] / "deploy", bundle=q["model"])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert not stale.exists()
    assert _apply(b, str(p["model"])).returncode == 0
    assert not list((b["box"] / "deploy/models").rglob("*.part"))
    dest = tmp_path / "models"
    (dest / "a").mkdir(parents=True)
    (dest / "a/w.bin.part").write_bytes(b"x")
    up.restore_models(dest, tmp_path / "rb", up.Point(models_new=["a/w.bin"]))
    assert not (dest / "a/w.bin.part").exists()


def test_review_f4_a_model_pack_alone_must_be_the_one_the_software_needs(tmp_path: Path) -> None:
    """Review F4: a model pack applied on its own is refused unless the software on the box names it, or the
    software pack loaded straight after it does (--for-software); on a box that holds a whole bundle, a model pack
    is ordered by that bundle's release_seq (an older one needs --allow-downgrade)."""
    p = _packs(tmp_path, seq=2)
    b = _box(tmp_path, p["pub"])
    _install_load(b, p)
    keys = (p["priv"], p["pub"])
    other = _packs(tmp_path / "next", seq=3, tag_suffix="-next", keys=keys)
    r = _apply(b, str(other["model"]), "--dry-run", dry=True)
    assert r.returncode == 1 and "is not the one the software on this box needs (r2-models" in r.stderr
    r = _apply(b, str(other["model"]), "--dry-run", "--for-software", str(other["software"]), dry=True)
    assert r.returncode == 0, r.stderr
    w = _box(tmp_path / "w", keys[1])
    whole = _whole(tmp_path / "w", keys)
    assert _apply(w, str(whole)).returncode == 0  # a whole bundle at release_seq 1
    old = _packs(tmp_path / "old", seq=1, tag_suffix="-old", keys=keys)
    r = _apply(w, str(old["model"]), "--dry-run", "--for-software", str(old["software"]), dry=True)
    assert r.returncode == 1 and "release_seq 1 is not above the installed 1" in r.stderr


def test_review_f6_a_box_installed_before_h95_takes_its_second_software_pack(tmp_path: Path) -> None:
    """Review F6: on a box installed from a whole bundle before H-95 (no model-pack.json), the first software pack
    is recorded: the whole bundle's models are written down as the model pack held, so the second software pack
    that names the same whole bundle is taken too."""
    keys = keygen(tmp_path / "keys")
    whole = _whole(tmp_path, keys)
    b = _box(tmp_path, keys[1])
    assert _apply(b, str(whole)).returncode == 0
    updates = b["box"] / "deploy/updates"
    (updates / up.MODEL_PACK).unlink()  # a box installed before H-95
    sw2, sw3 = _software_for(tmp_path, keys, whole, seq=2), _software_for(tmp_path, keys, whole, seq=3)
    stage = tmp_path / "stage-sw2"
    m = vu.verify(sw2, keys[1], stage, installed_file=updates / "installed.json",
                  model_pack_record=updates / up.MODEL_PACK, stream_kinds=("image", "model"))  # fmt: skip
    plan = up.Plan.load(stage, vu.summary(m))
    plan.pack = m["pack"]
    up.Updater(up.ComposeBox(b["box"] / "deploy"), updates, say=lambda _m: None)._record(plan, live=False)
    assert json.loads((updates / "installed.json").read_text())["bundle_id"] == "sw2"
    assert json.loads((updates / up.MODEL_PACK).read_text())["bundle_id"] == "w1"
    vu.verify(sw3, keys[1], tmp_path / "stage-sw3", installed_file=updates / "installed.json",
              model_pack_record=updates / up.MODEL_PACK)  # fmt: skip


def test_review_f5_the_space_stop_counts_the_engines_working_space(tmp_path: Path) -> None:
    p = _packs(tmp_path)
    where = {"docker_root": tmp_path, "models": tmp_path, "stage": tmp_path, "deploy": tmp_path}
    _fits, lines = packs.space([p["software"], p["model"]], where, free_of=lambda _p: 1 << 40)
    assert "the engine's working space (largest image)" in lines[0]
    assert packs.sizes([p["model"]])["engine"] == _offset(p["model"], "engine.tar")[1]


def test_review_f7_a_model_pack_given_without_a_dry_run_is_not_mounted(tmp_path: Path) -> None:
    """Review F7: --with-model-pack acts in a dry run only; without one it is not passed on, so the verifier's
    container never mounts it (a relative path would have become a named volume)."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    log = tmp_path / "docker.log"
    env = {**_env(b), "TB_VERIFY_IN_DOCKER": "1", "H95_DOCKER_LOG": str(log)}
    rel = os.path.relpath(p["model"], b["box"])
    subprocess.run(["sh", str(b["box"] / "tools/apply_update.sh"), str(p["software"]), "--with-model-pack", rel],
                   capture_output=True, text=True, env=env, cwd=b["box"], check=False, timeout=600)  # fmt: skip
    runs = [ln for ln in log.read_text().splitlines() if ln.startswith("run ")]
    assert runs and all("--model-pack-candidate" not in ln and f"-v {rel}" not in ln for ln in runs)


def test_review_m4_the_bundle_must_be_the_one_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant M4: the update path reads the payloads from the bundle it is given only when that bundle's manifest is
    the verified one."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    stage = _staged_summary(p, "model", tmp_path)
    for k, v in _env(b).items():
        monkeypatch.setenv(k, v)
    other = _packs(tmp_path / "o")["model"]  # the same payloads, another signed manifest (signed another day)
    assert packs.manifest_of(other)[1] != packs.manifest_of(p["model"])[1]
    assert up.main_apply(stage, stage / "summary.json", "compose", b["box"] / "deploy", bundle=other) == 1
    assert not (b["dockerroot"] / "tags.json").exists() and not (b["box"] / "deploy/models").exists()


def test_review_m10_the_load_is_killed_on_a_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutant M10: on a mismatch the load is killed, not left to end on a cut stream: the stand-in's exit marker,
    written by any load that ends by itself, is never written."""
    p = _packs(tmp_path)
    b = _box(tmp_path, p["pub"])
    stage = _staged_summary(p, "model", tmp_path)
    off, size = _offset(p["model"], "engine.tar")
    with p["model"].open("r+b") as fh:
        fh.seek(off + size - 100)
        c = fh.read(1)
        fh.seek(off + size - 100)
        fh.write(bytes([c[0] ^ 1]))
    for k, v in _env(b).items():
        monkeypatch.setenv(k, v)
    with pytest.raises(up.UpdateFailed, match="no longer hash"):
        up.main_apply(stage, stage / "summary.json", "compose", b["box"] / "deploy", bundle=p["model"])
    assert not (b["dockerroot"] / "load-exited").exists()


def test_review_f1_a_load_that_moves_a_tag_the_first_read_did_not_see_is_undone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review F1, the other side: the stream hashes as signed, but the archive's manifest read for the pins was not
    that archive's (the stick changed between the two reads): the load moves a tag the pin check never saw. Every
    tag the load moved must be one the checked manifest named; else the load is undone."""
    keys = keygen(tmp_path / "keys")
    src = tmp_path / "src"
    src.mkdir()
    eng = src / "engine.tar"
    cfg = _archive(eng, ENGINE[0], MB)
    with tarfile.open(eng) as tf:  # the same image under a second tag
        members = [(m, tf.extractfile(m).read()) for m in tf.getmembers()]  # type: ignore[union-attr]
    with tarfile.open(eng, "w:") as tf:
        for m, data in members:
            if m.name == "manifest.json":
                entry = json.loads(data)
                entry[0]["RepoTags"].append("extra:1")
                data = json.dumps(entry).encode()
                m.size = len(data)
            tf.addfile(m, io.BytesIO(data))
    release, lock = _release({ENGINE[0]: cfg, "extra:1": cfg}, 1)
    model = tmp_path / "stick" / "trialbox-models-x.pack"
    model.parent.mkdir()
    build(keys[0], "x-models", [("image", eng, eng.name)], model, release_seq=1, release=release, images_lock=lock,
          pack={"kind": "model"})  # fmt: skip
    b = _box(tmp_path, keys[1])
    stage = tmp_path / "stage"
    summary = vu.summary(vu.verify(model, keys[1], stage, stream_kinds=("image", "model")))
    (stage / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    for k, v in _env(b).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(up, "tar_images", lambda tar: ({ENGINE[0]: cfg}, set()))  # the pin read saw one tag only
    with pytest.raises(up.UpdateFailed, match="moved tags the archive does not pin .extra:1."):
        up.main_apply(stage, stage / "summary.json", "compose", b["box"] / "deploy", bundle=model)
    assert _tags(b) == {}
