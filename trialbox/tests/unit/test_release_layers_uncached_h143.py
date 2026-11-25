"""H-143: a release never ships a security-upgrade layer a build cache kept from an older day.

The signed bundle at c3a5b2b2 failed its gate on a builder with a warm cache: trialbox-py, -backup, -jvm and -embed
still held libzstd1 1.5.7+dfsg-1 (CVE-2026-124851), which they get fixed only through the unpinned
``apt-get upgrade`` of deploy/docker/python.Dockerfile (and demo/Dockerfile). Two halves, both here:

* the release path (``make release-images``, a prerequisite of ``make release-bundle``) pulls the outside bases the
  Dockerfiles pin by digest, then builds every image with ``--no-cache`` and without ``--pull`` (which would look
  for trialbox-py in a registry); ``make images`` (dev) keeps the cache;
* deploy/images.lock ``security_floors`` records the fixed versions, and the release gates refuse an image whose SBOM
  has an older one, or none (tools/supply_chain/floors.py). The gate is shown refusing with a stand-in SBOM and
  stand-in scanners; a real build and scan are CI's.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.supply_chain import allowlist, floors, release, sbom

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
FIX = ROOT / "tests" / "fixtures" / "supply_chain"
STALE = "1.5.7+dfsg-1"  # what the cached layer held
FIXED = "1.5.7+dfsg-1+deb13u1"  # DSA-6657-1
ZLIB = "1:1.3.dfsg+really1.3.1-1+deb13u1"
UPGRADED = ("trialbox-py", "trialbox-backup", "trialbox-jvm", "trialbox-embed", "trialbox-demo")


def _deb(name: str, version: str) -> dict[str, Any]:
    """A CycloneDX component as the SBOM writes a Debian package: the epoch in a qualifier (purl spec)."""
    epoch, _, bare = version.rpartition(":")
    q = f"&epoch={epoch}" if epoch else ""
    enc = bare.replace("+", "%2B")
    return {"type": "library", "name": name, "version": version,
            "purl": f"pkg:deb/debian/{name}@{enc}?arch=amd64&distro=debian-13{q}"}  # fmt: skip


def _sbom(zstd: str | None, zlib: str = ZLIB) -> dict[str, Any]:
    comps = [_deb("zlib1g", zlib)] + ([_deb("libzstd1", zstd)] if zstd else [])
    return {"metadata": {}, "components": comps}


# ------------------------------------------------------------------------------------------- the version order


@pytest.mark.parametrize(
    ("a", "b", "sign"),
    [
        (STALE, FIXED, -1),
        (FIXED, FIXED, 0),
        ("1.5.7+dfsg-1+deb13u2", FIXED, 1),
        ("1.5.8+dfsg-1", FIXED, 1),
        ("1.5.7~rc1+dfsg-1+deb13u1", FIXED, -1),  # ~ sorts before everything
        ("1:1.3.dfsg+really1.3.1-1+b1", ZLIB, -1),
        ("1.3.dfsg+really1.3.1-1+deb13u1", ZLIB, -1),  # no epoch is epoch 0
        ("2:0.1-1", ZLIB, 1),
        ("1.10-1", "1.9-1", 1),  # digit runs by value
        ("1.0a-1", "1.0+-1", -1),  # letters before signs
    ],
)
def test_versions_compare_as_dpkg_does(a: str, b: str, sign: int) -> None:
    got = floors.compare(a, b)
    assert (got > 0) - (got < 0) == sign


def test_the_epoch_qualifier_is_read() -> None:
    assert floors.deb_packages(_sbom(FIXED)) == {"zlib1g": {ZLIB}, "libzstd1": {FIXED}}


# -------------------------------------------------------------------------------------------------- the floors


def test_the_lock_records_the_fixed_versions_for_every_upgraded_image() -> None:
    got = floors.load()
    assert set(got) == set(UPGRADED)
    held = LOCK["images"]["db"]["packages"]  # the db image pins and holds the same fixes
    for image in UPGRADED:
        assert floors.compare(got[image]["libzstd1"], held["libzstd1"]) >= 0, image
        assert floors.compare(got[image]["zlib1g"], held["zlib1g"]) >= 0, image
    own = re.search(r"^SC_OWN_IMAGES \?= (.+)$", MAKEFILE, re.M)
    assert own, "SC_OWN_IMAGES"
    gated = {floors.repository(r) for r in own.group(1).split()}
    assert set(UPGRADED) == gated - {"trialbox-postgres"}  # every gated image of ours but the pinned db


def test_an_older_library_is_refused_the_fixed_one_passes() -> None:
    lock = floors.load()
    for image in UPGRADED:
        ref = f"{image}:1.0.0"
        bad = floors.problems(ref, _sbom(STALE), lock)
        assert len(bad) == 1 and "libzstd1" in bad[0] and STALE in bad[0] and FIXED in bad[0], bad
        assert floors.problems(ref, _sbom(FIXED), lock) == []
        assert floors.problems(ref, _sbom("1.5.7+dfsg-1+deb13u2"), lock) == []
        missing = floors.problems(ref, _sbom(None), lock)
        assert len(missing) == 1 and "not in the image's SBOM" in missing[0]
        old_zlib = floors.problems(ref, _sbom(FIXED, "1:1.3.dfsg+really1.3.1-1+b1"), lock)
        assert len(old_zlib) == 1 and "zlib1g" in old_zlib[0]
    assert floors.problems("localhost:5000/trialbox-py:1.0.0@sha256:ab", _sbom(STALE), lock)
    assert floors.problems("postgres@sha256:ab", _sbom(STALE), lock) == []  # no floor: not this check's


def test_a_lock_without_floors_is_refused(tmp_path: Path) -> None:
    bare = tmp_path / "images.lock"
    bare.write_text(json.dumps({k: v for k, v in LOCK.items() if k != "security_floors"}), encoding="utf-8")
    with pytest.raises(ValueError, match="security_floors"):
        floors.load(bare)


# ------------------------------------------------------------------------------- the release gates refuse it


def _gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc: dict[str, Any], lock: Path | None = None) -> Any:
    tag = "trialbox-py:1.0.0"
    data = json.loads((FIX / "trivy_clean.json").read_text(encoding="utf-8"))
    data["ArtifactName"] = tag
    data["Metadata"].update(ImageID="sha256:cfg", RepoDigests=[], RepoTags=[tag])

    def fake_run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps(data), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_syft(_source: str, out: Path, *_a: Any, **_k: Any) -> dict[str, Any]:
        out.write_text(json.dumps(doc), encoding="utf-8")
        return doc

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        release, "inspect_local", lambda _ref: {"image_id": "sha256:cfg", "repo_digests": [], "platform": "linux/amd64"}
    )
    monkeypatch.setattr(sbom, "run_syft", fake_syft)
    monkeypatch.setattr(release, "identity_problems", lambda *a, **k: [])
    allow, errors = allowlist.parse({}, today=dt.date(2026, 11, 25))
    assert errors == []
    return release.run_gates(
        [release.Target(tag)], cache_dir=tmp_path / "c", out_dir=tmp_path / "o", sbom_dir=tmp_path / "s",
        allow=allow, allow_errors=[], lock_sbom=None, now=dt.datetime(2026, 11, 25, tzinfo=dt.UTC), images_lock=lock,
    )  # fmt: skip


def test_the_release_gates_refuse_the_cached_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _gate(tmp_path, monkeypatch, _sbom(STALE))
    entry = record["images"][0]
    assert entry["ok"] is False and record["ok"] is False
    assert any("libzstd1" in e and "older than" in e for e in entry["errors"]), entry["errors"]
    assert "libzstd1" in release.render(record)


def test_the_release_gates_take_the_fresh_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _gate(tmp_path, monkeypatch, _sbom(FIXED))["images"][0]
    assert entry["errors"] == [] and entry["ok"] is True, entry["errors"]


def test_the_release_gates_fail_closed_on_a_lock_without_floors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = tmp_path / "images.lock"
    bare.write_text(json.dumps({k: v for k, v in LOCK.items() if k != "security_floors"}), encoding="utf-8")
    record = _gate(tmp_path, monkeypatch, _sbom(FIXED), lock=bare)
    assert record["ok"] is False and record["floor_errors"], record.get("floor_errors")


# -------------------------------------------------------------------------- the release path builds afresh
DOCKERFILES = (
    "deploy/docker/python.Dockerfile", "deploy/docker/backup.Dockerfile", "deploy/docker/jvm.Dockerfile",
    "deploy/docker/embed.Dockerfile", "deploy/docker/db.Dockerfile", "demo/Dockerfile",
)  # fmt: skip
PINNED = re.compile(r"[a-z0-9./_-]+:[^\s@\"]*@sha256:[0-9a-f]{64}")


def _dry_run(*goals: str) -> list[str]:
    """The commands ``make -n`` prints, one per line (continuations joined)."""
    proc = subprocess.run(
        ["make", "--no-print-directory", "-n", *goals, "FONTS=pyproject.toml", "TB_REVISION=x"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr[-2000:]
    return re.sub(r"\\\n\s*", " ", proc.stdout).splitlines()


def _builds(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.lstrip().startswith(("docker build ", "deploy/build_db_image.sh "))]


def test_the_release_path_pulls_the_pinned_bases_then_builds_without_cache_or_pull() -> None:
    """The walk (7159322336): --no-cache --pull together sends FROM trialbox-py to a registry; so the release path
    pulls the outside bases by digest first, then builds every image without cache and without --pull."""
    rel = _dry_run("release-images")
    builds = _builds(rel)
    assert len(builds) == 6, builds  # py, backup, jvm, embed, db, demo
    first = rel.index(builds[0])
    pulls = [ln for ln in rel[:first] if "docker pull" in ln]
    assert len(pulls) == 1, rel[:first]
    pulled = set(PINNED.findall(pulls[0]))
    bases = {m for f in DOCKERFILES for m in PINNED.findall((ROOT / f).read_text(encoding="utf-8"))}
    assert bases and pulled == bases  # every outside base, by digest, before any build
    for b in builds:
        assert "--no-cache" in b.split(), b
        assert "--pull" not in b.split() and "--pull=" not in b, b


def test_a_dev_build_keeps_its_cache() -> None:
    dev = _dry_run("images", "demo-bundle")
    builds = _builds(dev)
    assert len(builds) == 6, builds
    assert not any("--no-cache" in b for b in builds)
    assert not any("docker pull" in ln for ln in dev)


def test_release_bundle_builds_the_images_before_its_gates() -> None:
    m = re.search(r"^release-bundle:(.*)$", MAKEFILE, re.M)
    assert m
    prereqs = m.group(1).split()
    assert prereqs.index("release-images") < prereqs.index("release-gates")
    gates = re.search(r"^release-gates:(.*)$", MAKEFILE, re.M)
    assert gates and "$(if $(filter release-bundle,$(MAKECMDGOALS)),release-images,)" in gates.group(1)
