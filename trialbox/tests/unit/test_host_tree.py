"""T-631 (D-367; review OPS-010, OPS-020): the host tree is in the signed release. The compose files, host tools and
configuration ride as one payload of kind ``host``; install and update unpack it to ``<install>/releases/<id>`` and
``<install>/current`` names the release; a rollback switches back.

The drill runs the real verifier, the real update path (``tools/trialbox/update.py`` ``main_apply`` and the site's
``ComposeBox``) and a stand-in ``docker`` on ``PATH``: each ``compose up`` reads the compose file of the project folder
as compose would and records the value of the drill's compose variable, so the test sees which compose file ran. No
container runs. Acceptance:

* an update that changes a compose variable takes effect, and one whose check fails rolls back to the previous value;
* a changed compose byte on the media is refused before anything is staged or switched.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tools import host_tree as ht
from tools.sign_bundle import build, keygen
from tools.trialbox import update as up
from tools.verify_update import Rejected, summary, verify

ROOT = Path(__file__).resolve().parents[2]

STAND_IN_DOCKER = r"""#!PYTHON
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
if args[:1] == ["compose"]:
    proj = args[args.index("--project-directory") + 1]
    rest = args[args.index("--project-directory") + 2:]
    cmd = rest[0] if rest else ""
    if cmd == "ps":
        print("db\norchestrator" if os.path.exists(os.environ["FAKE_RUNNING"]) else "")
    elif cmd == "up":  # what compose would run: the compose file of the project folder (through its links)
        text = open(os.path.join(proj, "docker-compose.yml")).read()
        level = re.search(r"TB_DRILL_LEVEL: \"([^\"]*)\"", text).group(1)
        with open(os.environ["FAKE_UP_LOG"], "a") as fh:
            fh.write(level + "\n")
        if "--wait" in rest and level == os.environ.get("FAKE_UNHEALTHY"):
            sys.exit("container trialbox-orchestrator-1 is unhealthy")
    elif cmd == "exec" and "pg_dump" in rest:
        sys.stdout.write("PGDMP synthetic dump")
    elif cmd == "run" and "snapshot" in rest:
        print("{}")
    elif cmd == "exec" and any("pg_database_size" in a for a in rest):  # H-121: the size check reads a size
        print("1000")
    elif cmd == "exec":
        sys.stdin.read() if not sys.stdin.isatty() else None
elif args[:1] == ["info"]:
    print(os.environ["FAKE_DOCKER_ROOT"])
elif args[:2] == ["image", "inspect"]:
    sys.exit("no such image")
"""


def _source(tmp: Path, level: str) -> Path:
    """A release's source tree: a compose file with the drill's variable, a host tool, an executable script, and a
    site file (deploy/site) that must never ride in the tree."""
    src = tmp / f"src-{level}"
    (src / "deploy/docker").mkdir(parents=True)
    (src / "deploy/docker-compose.yml").write_text(
        "services:\n  orchestrator:\n    image: trialbox-py:1.0.0\n    environment:\n"
        f'      TB_DRILL_LEVEL: "{level}"\n', encoding="utf-8")  # fmt: skip
    (src / "deploy/docker/db-init.sql").write_text("SELECT 1;\n")
    (src / "deploy/network.sh").write_text("#!/bin/sh\necho egress\n")
    (src / "deploy/network.sh").chmod(0o755)
    (src / "deploy/site").mkdir()
    (src / "deploy/site/registry.site.yaml").write_text("site: own\n")
    (src / "tools").mkdir()
    (src / "tools/hello.py").write_text(f"LEVEL = {level!r}\n")
    (src / ".env.example").write_text("TB_ENV=DEV\n")
    return src


def _bundle(tmp: Path, key: Path, bid: str, seq: int, level: str, *, tamper: Any = None) -> Path:
    tar = tmp / f"host-{bid}.tar"
    ht.pack(_source(tmp, level), tar)
    if tamper is not None:
        tamper(tar)
    out = tmp / f"{bid}.tar"
    build(key, bid, [("host", tar, ht.HOST_TAR)], out, release_seq=seq)
    return out


@pytest.fixture()
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    keys = tmp_path / "vendor"
    priv, pub = keygen(keys)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(STAND_IN_DOCKER.replace("#!PYTHON", f"#!{sys.executable}"), encoding="utf-8")
    docker.chmod(0o755)
    base = tmp_path / "opt-trialbox"
    deploy = base / "deploy"
    deploy.mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nPOSTGRES_PASSWORD=synthetic-only\n", encoding="utf-8")
    # an install made the old way: a copied (unsigned) compose file the release replaces
    (deploy / "docker-compose.yml").write_text('services: {}\n# TB_DRILL_LEVEL: "copied"\n', encoding="utf-8")
    for k, v in {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                 "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"), "FAKE_UP_LOG": str(tmp_path / "up.log"),
                 "FAKE_RUNNING": str(tmp_path / "running"), "FAKE_DOCKER_ROOT": str(tmp_path / "docker-root"),
                 "TB_MODELS_DIR": str(deploy / "models")}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    for k in ("TB_COMPOSE", "TB_DOCKER", "TB_UPDATE_CHECK_CMD", "TB_SKIP_AUDIT", "FAKE_UNHEALTHY"):
        monkeypatch.delenv(k, raising=False)
    return {"tmp": tmp_path, "priv": priv, "pub": pub, "base": base, "deploy": deploy}


def _verify(b: dict[str, Any], bundle: Path, stage: Path) -> dict[str, Any]:
    """As apply_update.sh calls it: the box's trust.json once there is one, its installed.json."""
    updates = b["deploy"] / "updates"
    trust = updates / "trust.json"
    return verify(bundle, b["pub"], stage, trust_file=trust if trust.is_file() else None,
                  installed_file=updates / "installed.json")  # fmt: skip


def _apply(b: dict[str, Any], bundle: Path, *, first: bool = False, mp: pytest.MonkeyPatch) -> int:
    """apply_update.sh's two steps: verify and stage, then the update path with the summary in the stage folder."""
    stage = b["tmp"] / f"stage-{bundle.stem}"
    m = _verify(b, bundle, stage)
    (stage / "summary.json").write_text(json.dumps(summary(m)), encoding="utf-8")
    with mp.context() as m2:
        if first:
            m2.setenv("TB_SKIP_AUDIT", "1")
        return up.main_apply(stage, stage / "summary.json", "compose", b["deploy"], backup=False)


def _ups(b: dict[str, Any]) -> list[str]:
    f = b["tmp"] / "up.log"
    return f.read_text().split() if f.is_file() else []


def _compose_level(b: dict[str, Any]) -> str:
    deploy: Path = b["deploy"]
    return (deploy / "docker-compose.yml").read_text().split('TB_DRILL_LEVEL: "')[1].split('"')[0]


# ---------------------------------------------------------------------------------------------- acceptance 1 (drill)


def test_drill_a_compose_variable_change_takes_effect_and_rolls_back(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    b, base, deploy = box, box["base"], box["deploy"]
    # first install (install.sh's load: the box is not running yet): the signed tree replaces the copied one
    assert _apply(b, _bundle(b["tmp"], b["priv"], "R1", 1, "one"), first=True, mp=monkeypatch) == 0
    assert os.readlink(base / "current") == "releases/R1"
    assert (deploy / "docker-compose.yml").is_symlink() and _compose_level(b) == "one"
    assert os.readlink(base / "tools") == "current/tools" and (base / "tools/hello.py").read_text() == "LEVEL = 'one'\n"
    assert os.access(deploy / "network.sh", os.X_OK)
    assert (deploy / ".env").read_text().startswith("TB_ENV=PRODUCTION") and not (deploy / ".env").is_symlink()
    assert not (base / "releases/R1/deploy/site").resolve().is_relative_to(base / "releases")  # never the vendor's
    assert (base / "releases/R1/deploy/.env").read_text().startswith("TB_ENV=PRODUCTION")  # back-link to the site
    aside = next((base / "releases").glob(".replaced-*"))
    assert "copied" in (aside / "deploy/docker-compose.yml").read_text()  # set aside, never deleted
    assert ht.status(base)["problems"] == []
    (b["tmp"] / "running").touch()  # install.sh started the stack

    # an update that changes the compose variable: it takes effect (the restart and the check ran the new file)
    assert _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, "two"), mp=monkeypatch) == 0
    assert os.readlink(base / "current") == "releases/R2" and _compose_level(b) == "two"
    assert _ups(b)[-2:] == ["two", "two"]  # migrate-and-restart, then the health check
    assert json.loads((deploy / "updates/installed.json").read_text())["release_seq"] == 2
    assert (base / "releases/R1").is_dir()  # the previous release stays for a later rollback

    # an update whose new compose value leaves a service unhealthy: rolled back to the previous release
    monkeypatch.setenv("FAKE_UNHEALTHY", "three")
    assert _apply(b, _bundle(b["tmp"], b["priv"], "R3", 3, "three"), mp=monkeypatch) == 1
    ups = _ups(b)
    assert "three" in ups and ups[-1] == "two"  # it ran, failed its check, the previous compose file runs again
    assert os.readlink(base / "current") == "releases/R2" and _compose_level(b) == "two"
    assert not (base / "releases/R3").exists()  # the failed release is removed
    assert json.loads((deploy / "updates/installed.json").read_text())["release_seq"] == 2
    assert not (deploy / "updates/IN_PROGRESS.json").exists()
    hist = (deploy / "updates/history.jsonl").read_text()
    assert "host tree, images, models, database, rulesets and update state put back" in hist


def test_a_crash_after_the_switch_is_rolled_back_from_the_marker(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """kill -9 after apply: `tools/apply_update.sh rollback <bundle>` reads point.json and names R1 again."""
    b, base = box, box["base"]
    assert _apply(b, _bundle(b["tmp"], b["priv"], "R1", 1, "one"), first=True, mp=monkeypatch) == 0
    (b["tmp"] / "running").touch()

    class Killed(BaseException):
        pass

    def kill(step: str) -> None:
        if step == "migrate and restart":
            raise Killed

    bundle = _bundle(b["tmp"], b["priv"], "R2", 2, "two")
    stage = b["tmp"] / "stage-crash"
    m = _verify(b, bundle, stage)
    plan = up.Plan.load(stage, summary(m))
    updates = b["deploy"] / "updates"
    with pytest.raises(Killed):
        up.Updater(up.ComposeBox(b["deploy"]), updates, say=lambda _m: None, on_step=kill).run(plan, backup=False)
    assert os.readlink(base / "current") == "releases/R2"  # switched, then killed
    up.Updater(up.ComposeBox(b["deploy"]), updates, say=lambda _m: None).recover("R2")
    assert os.readlink(base / "current") == "releases/R1" and _compose_level(b) == "one"
    assert not (base / "releases/R2").exists()


# ---------------------------------------------------------------------------------------------- acceptance 2


def _flip_compose_byte(path: Path, level: str) -> None:
    data = bytearray(path.read_bytes())
    i = data.index(f'TB_DRILL_LEVEL: "{level}"'.encode()) + len('TB_DRILL_LEVEL: "')
    data[i] ^= 0x01
    path.write_bytes(bytes(data))


def test_a_changed_compose_byte_on_the_media_is_refused(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    b, base = box, box["base"]
    assert _apply(b, _bundle(b["tmp"], b["priv"], "R1", 1, "one"), first=True, mp=monkeypatch) == 0
    bundle = _bundle(b["tmp"], b["priv"], "R2", 2, "two")
    _flip_compose_byte(bundle, "two")  # one byte of deploy/docker-compose.yml inside the signed bundle
    stage = b["tmp"] / "stage-bad"
    with pytest.raises(Rejected, match=f"{ht.HOST_TAR}: sha256 mismatch"):
        _verify(b, bundle, stage)
    assert not stage.exists() or not any(stage.rglob("*"))  # nothing staged
    assert os.readlink(base / "current") == "releases/R1" and _compose_level(b) == "one"


def test_a_signed_tree_whose_own_sums_disagree_is_refused(box: dict[str, Any]) -> None:
    """The vendor signed a tree whose compose file differs from its HOST-SHA256SUMS: refused all the same."""
    bundle = _bundle(box["tmp"], box["priv"], "R1", 1, "one", tamper=lambda t: _flip_compose_byte(t, "one"))
    with pytest.raises(Rejected, match="host tree: deploy/docker-compose.yml: sha256 differs"):
        verify(bundle, box["pub"])


def _tar(path: Path, members: list[tuple[str, bytes | None]]) -> Path:
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in members if d is not None)
    with tarfile.open(path, "w") as tf:
        for name, data in [(ht.SUMS, sums.encode()), *members]:
            ti = tarfile.TarInfo(name)
            if data is None:
                ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tf.addfile(ti)
            else:
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return path


@pytest.mark.parametrize(
    ("members", "why"),
    [
        ([("deploy/docker-compose.yml", b"x"), ("deploy/evil", None)], "not a regular file"),
        ([("deploy/docker-compose.yml", b"x"), ("deploy/.env", b"TB_ENV=DEV")], "may not be in a host tree"),
        ([("deploy/docker-compose.yml", b"x"), ("../escape", b"x")], "unsafe path"),
        ([("deploy/docker-compose.yml", b"x"), ("services/x.py", b"x")], "may not be in a host tree"),
        ([("tools/x.py", b"x")], "has no deploy/docker-compose.yml"),
    ],
)
def test_the_tree_rules(tmp_path: Path, members: list[tuple[str, bytes | None]], why: str) -> None:
    with pytest.raises(ht.HostTreeError, match=why):
        ht.check_tar(_tar(tmp_path / "t.tar", members))


def test_two_host_trees_are_refused(box: dict[str, Any]) -> None:
    tar = box["tmp"] / "h.tar"
    ht.pack(_source(box["tmp"], "one"), tar)
    out = box["tmp"] / "two.tar"
    build(box["priv"], "R1", [("host", tar, "a.tar"), ("host", tar, "b.tar")], out)
    with pytest.raises(Rejected, match="more than one host tree"):
        verify(out, box["pub"])


def test_the_repository_tree_packs_and_keeps_site_files_out(tmp_path: Path) -> None:
    """make_bundle.sh's call: the real tree, deterministic, with the compose files and host tools, no site file."""
    a = ht.pack(ROOT, tmp_path / "a.tar")
    b = ht.pack(ROOT, tmp_path / "b.tar")
    assert a == b and a["files"] > 50
    names = ht.check_tar(tmp_path / "a.tar")
    assert {"deploy/docker-compose.yml", "deploy/install.sh", "tools/apply_update.sh", "tools/verify_update.py",
            "tools/host_tree.py", "libs/tb_common/__init__.py"} <= set(names)  # fmt: skip
    assert not [n for n in names if ht.is_state(n) or "__pycache__" in n]
    assert "tools/host_tree.py" in (ROOT / "tools/make_bundle.sh").read_text(encoding="utf-8")
