"""Release identity and bundle gates (T-110b, D-340; CR-046, CR-081, OPS-017, OPS-018, ENG-007, ENG-014, ENG-024).

The acceptance tests of the card:

* a bundle without its checks cannot be built: ``tools/make_bundle.sh`` refuses to run without ``--gates``, and refuses
  any image that is not a passing image of the record (also one that passed only in report mode);
* ``release.json`` in the bundle names every component: every payload file with the sha256 the signed manifest gives
  it, every image by its config digest with its SBOM inside the bundle; ``verify_update.py`` accepts the bundle.

``make_bundle.sh`` runs for real against a stand-in ``docker`` (compose config, image inspect, tag, save), so no
Docker daemon is needed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tools import release
from tools.supply_chain import allowlist, vulns
from tools.supply_chain import release as gates_mod

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "make_bundle.sh"
HAPI = "hapiproject/hapi:v8.12.0-2@sha256:" + "a" * 64
VLLM = "vllm/vllm-openai:v0.32.0"
OWN = ("trialbox-py:1.0.0", "trialbox-jvm:1.0.0", "trialbox-postgres:16-1")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# a stand-in docker: image ids are the sha256 of the repository name, so a digest reference and the tag it is saved
# under are the same image (as for docker save of a pulled image)
FAKE_DOCKER = r"""#!PYTHON
import hashlib, io, json, os, sys, tarfile
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
def repo(ref):
    ref = ref.split("@", 1)[0]
    head, _, last = ref.rpartition("/")
    return (head + "/" if head else "") + last.split(":", 1)[0]
def image_id(ref):
    return hashlib.sha256(repo(ref).encode()).hexdigest()
if args[:1] == ["compose"]:
    print("\n".join(os.environ["FAKE_COMPOSE_IMAGES"].split()))
elif args[:2] == ["image", "inspect"]:
    ref = args[-1]
    if args[2:3] == ["-f"]:
        print("sha256:" + image_id(ref))
    else:
        print(json.dumps([{"Id": "sha256:" + image_id(ref), "RepoDigests": [], "Os": "linux",
                           "Architecture": "amd64"}]))
elif args[:1] in (["tag"], ["pull"]):
    pass
elif args[:1] == ["save"]:
    ref, out = args[1], args[args.index("-o") + 1]
    manifest = json.dumps([{"Config": image_id(ref) + ".json", "RepoTags": [ref], "Layers": []}]).encode()
    with tarfile.open(out, "w") as tf:
        for name, data in (("manifest.json", manifest), (image_id(ref) + ".json", b"{}")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
else:
    sys.exit("fake docker: unsupported " + " ".join(args))
"""


def _iid(ref: str) -> str:
    return "sha256:" + hashlib.sha256(release.repository(ref).encode()).hexdigest()


def _sbom_name(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", release.repository(ref)) + ".cdx.json"


def _gate_record(tmp: Path, refs: list[str], *, report_mode: tuple[str, ...] = ()) -> tuple[Path, Path]:
    """A passing gate record for ``refs`` (as ``make release-gates`` writes it) and its SBOM folder."""
    sbom_dir = tmp / "dist" / "sbom"
    sbom_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for ref in refs:
        f = sbom_dir / _sbom_name(ref)
        f.write_text(json.dumps({"bomFormat": "CycloneDX", "subject": ref}), encoding="utf-8")
        images.append(
            {
                "ref": ref,
                "platform": "linux/amd64",
                "image_id": _iid(ref),
                "repo_digests": [],
                "ok": True,
                "sbom": f.name,
                "sbom_sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                "report_mode_findings": [{"id": "CVE-1"}] if ref in report_mode else [],
            }
        )
    for name in release.SBOM_EXTRAS:
        (sbom_dir / name).write_text("{}\n" if name.endswith(".json") else "# licences\n", encoding="utf-8")
    gates = tmp / "build" / "supply-chain" / "gates.json"
    gates.parent.mkdir(parents=True, exist_ok=True)
    record = {"created": dt.datetime.now(dt.UTC).isoformat(), "ok": True, "vuln_mode": "report", "images": images}
    gates.write_text(json.dumps(record), encoding="utf-8")
    return gates, sbom_dir


@pytest.fixture()
def kit(tmp_path: Path) -> dict[str, Any]:
    from tools.sign_bundle import keygen

    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER.replace("PYTHON", sys.executable), encoding="utf-8")
    docker.chmod(0o755)
    priv, pub = keygen(tmp_path / "keys")
    return {"tmp": tmp_path, "bin": bindir, "key": priv, "pub": pub, "log": tmp_path / "docker.log"}


def _make(
    kit: dict[str, Any], *extra: str, compose: tuple[str, ...] = (*OWN, HAPI, VLLM)
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{kit['bin']}{os.pathsep}{os.environ.get('PATH', '')}",
        "PY": sys.executable,
        "TMPDIR": str(kit["tmp"]),
        "FAKE_DOCKER_LOG": str(kit["log"]),
        "FAKE_COMPOSE_IMAGES": " ".join(compose),
    }
    cmd = [
        "bash",
        str(SCRIPT),
        "--key",
        str(kit["key"]),
        "--id",
        "2026.11-1",
        "--out",
        str(kit["tmp"] / "out.tar"),
        *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300, check=False)


# ---------------------------------------------------------------------------------------------- acceptance 1


def test_a_bundle_without_its_checks_cannot_be_built(kit: dict[str, Any]) -> None:
    res = _make(kit, "--release-seq", "1")
    assert res.returncode == 2
    assert "--gates is required" in res.stderr
    assert not (kit["tmp"] / "out.tar").exists()
    assert not kit["log"].exists()  # refused before any image is touched
    script = SCRIPT.read_text(encoding="utf-8")
    assert "WARNING no --gates" not in script  # the old warn-and-continue path is gone


def test_an_image_outside_the_gate_record_is_refused(kit: dict[str, Any]) -> None:
    gates, sbom = _gate_record(kit["tmp"], [*OWN, HAPI])  # vLLM was never gated
    res = _make(kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "not a passing image of this record" in res.stderr
    assert not (kit["tmp"] / "out.tar").exists()


def test_an_image_that_passed_only_in_report_mode_is_refused(kit: dict[str, Any]) -> None:
    gates, sbom = _gate_record(kit["tmp"], [*OWN, HAPI, VLLM], report_mode=(VLLM,))
    res = _make(kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom))
    assert res.returncode == 1
    assert not (kit["tmp"] / "out.tar").exists()


def test_release_build_rechecks_the_saved_archives(tmp_path: Path) -> None:
    """tools/release.py refuses by itself too: the gate rule is applied to the digest inside each saved archive."""
    gates, sbom = _gate_record(tmp_path, ["trialbox-py:1.0.0"])
    archive = _archive(tmp_path / "py.tar", "trialbox-py:1.0.0", config="b" * 64)  # not the gated image
    with pytest.raises(release.ReleaseError, match="not a passing image"):
        release.build(release_id="r1", release_seq=1, gates=gates, sbom_dir=sbom, out_dir=tmp_path / "meta",
                      images=[("trialbox-py:1.0.0", archive)], items=[("image", archive, "py.tar")])  # fmt: skip
    assert not (tmp_path / "meta" / "release.json").exists()


# ---------------------------------------------------------------------------------------------- acceptance 2


def test_release_json_in_the_bundle_names_every_component(kit: dict[str, Any]) -> None:
    from tools.verify_update import verify

    gates, sbom = _gate_record(kit["tmp"], [*OWN, HAPI, VLLM])
    res = _make(kit, "--release-seq", "4", "--gates", str(gates), "--sbom-dir", str(sbom))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "release check: PASS" in res.stdout
    bundle = kit["tmp"] / "out.tar"
    assert release.check_bundle(bundle) == []

    with tarfile.open(bundle) as tf:
        manifest = json.loads(tf.extractfile("manifest.json").read())  # type: ignore[union-attr]
        rel = json.loads(tf.extractfile("release.json").read())  # type: ignore[union-attr]
        lock = json.loads(tf.extractfile("images.lock").read())  # type: ignore[union-attr]
    files = {f["path"]: f for f in manifest["files"]}
    assert {c["path"]: c["sha256"] for c in rel["components"]} == {p: f["sha256"] for p, f in files.items()}
    # every image: its archive, its config digest, its SBOM in the bundle
    assert set(rel["images"]) == {"py", "jvm", "db", "hapi", "vllm-openai"}
    for img in rel["images"].values():
        assert img["archive"] in files and files[img["archive"]]["kind"] == "image"
        assert img["sbom"] in files and files[img["sbom"]]["sha256"] == img["sbom_sha256"]
        assert img["digest"] == _iid(img["source"])
    assert rel["images"]["hapi"]["image"] == "hapiproject/hapi:v8.12.0-2" and rel["images"]["hapi"]["source"] == HAPI
    assert {"sbom/requirements.lock.cdx.json", "sbom/licences.md", "sbom/index.json", "sbom/gates.json"} <= set(files)
    assert {"NOTICE", "CHANGELOG.md", "install.sh", "RUNBOOK.md"} <= set(files)
    # T-631 (D-367): the host tree rides in every bundle, as one payload of kind host
    assert files["trialbox-host.tar"]["kind"] == "host"
    assert [c["kind"] for c in rel["components"] if c["path"] == "trialbox-host.tar"] == ["host"]
    # the whole runbook: docs/RUNBOOK.md while doclint has no --whole (T-669 adds it and joins the sections)
    if "--whole" not in (ROOT / "tools" / "doclint.py").read_text(encoding="utf-8"):
        want = hashlib.sha256((ROOT / "docs" / "RUNBOOK.md").read_bytes()).hexdigest()
        assert files["RUNBOOK.md"]["sha256"] == want
    assert rel["version"] == release.version() and rel["release_seq"] == 4 == manifest["release_seq"]
    assert rel["gates"]["record_sha256"] == hashlib.sha256(gates.read_bytes()).hexdigest()
    # the release's images.lock agrees with release.json and keeps the db entry's pins
    assert lock["images"]["db"]["digest"] == rel["images"]["db"]["digest"]
    assert lock["images"]["db"]["base"]["ref"].startswith("postgres:")
    # the box's own check accepts it
    out = verify(bundle, kit["pub"], installed_file=kit["tmp"] / "installed.json")
    assert out["bundle_id"] == "2026.11-1"


def test_no_test_mail_server_in_a_bundle(kit: dict[str, Any]) -> None:
    """OPS-017: the bundle takes the box's compose file only (profiles stub and gpu), never the test file."""
    gates, sbom = _gate_record(kit["tmp"], [*OWN, HAPI, VLLM])
    assert _make(kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom)).returncode == 0
    compose_calls = [ln for ln in kit["log"].read_text(encoding="utf-8").splitlines() if ln.startswith("compose")]
    assert compose_calls and all(
        "docker-compose.test.yml" not in c and "--profile test" not in c for c in compose_calls
    )
    assert "--profile stub --profile gpu" in compose_calls[0]


def test_check_finds_a_file_release_json_does_not_name(tmp_path: Path) -> None:
    from tools.sign_bundle import build, keygen

    gates, sbom = _gate_record(tmp_path, ["trialbox-py:1.0.0"])
    archive = _archive(
        tmp_path / "py.tar", "trialbox-py:1.0.0", config=_iid("trialbox-py:1.0.0").removeprefix("sha256:")
    )
    items = [("image", archive, "py.tar")]
    rel = release.build(release_id="r1", release_seq=1, gates=gates, sbom_dir=sbom, out_dir=tmp_path / "meta",
                        images=[("trialbox-py:1.0.0", archive)], items=items)  # fmt: skip
    extra = [tuple(ln.split(":", 1)[0:1]) + tuple(ln.split(":", 1)[1].split("=")) for ln in
             (tmp_path / "meta" / "items.txt").read_text(encoding="utf-8").splitlines()]  # fmt: skip
    payload = items + [(k, Path(s), d) for k, s, d in extra]
    lock = json.loads((tmp_path / "meta" / "images.lock").read_text(encoding="utf-8"))
    key, _ = keygen(tmp_path / "keys")
    good = tmp_path / "good.tar"
    build(key, "r1", payload, good, release_seq=1, release=rel, images_lock=lock)
    assert release.check_bundle(good) == []
    sneaked = tmp_path / "sneaked.txt"
    sneaked.write_text("not in the release record\n", encoding="utf-8")
    bad = tmp_path / "bad.tar"
    build(key, "r1", [*payload, ("other", sneaked, "sneaked.txt")], bad, release_seq=1, release=rel, images_lock=lock)
    assert any("sneaked.txt: in the bundle but not named" in p for p in release.check_bundle(bad))
    no_sbom = tmp_path / "no-sbom.tar"
    build(key, "r1", items, no_sbom, release_seq=1, release=rel, images_lock=lock)
    assert any("SBOM sbom/" in p and "not in the bundle" in p for p in release.check_bundle(no_sbom))


def _finding() -> vulns.Finding:
    return vulns.Finding(source="trivy", target="t", package="openssl", version="1", id="CVE-9", aliases=(),
                         severity="HIGH", fixed="2")  # fmt: skip


def _archive(path: Path, tag: str, *, config: str) -> Path:
    manifest = json.dumps([{"Config": f"{config}.json", "RepoTags": [tag], "Layers": []}]).encode()
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        tf.addfile(info, io.BytesIO(manifest))
    return path


# ---------------------------------------------------------------------------------------------- identity


def test_version_comes_from_pyproject_and_names_the_tag(tmp_path: Path) -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", release.version())
    assert release.tag_for("1.2.3") == "trialbox-v1.2.3"
    bad = tmp_path / "pyproject.toml"
    bad.write_text('[project]\nversion = "next"\n', encoding="utf-8")
    with pytest.raises(release.ReleaseError):
        release.version(bad)
    # the tag pattern the image workflow runs on is the one tools/release.py makes
    images_wf = (ROOT.parent / ".github" / "workflows" / "trialbox-images.yml").read_text(encoding="utf-8")
    assert f'tags: ["{release.TAG_PREFIX}*"]' in images_wf


def test_changelog_has_the_current_version() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {release.version()}" in text and "## Unreleased" in text


def test_image_names_follow_the_lock() -> None:
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    assert release.image_name("trialbox-postgres:16-1", lock) == "db"
    assert release.image_name("trialbox-py:1.0.0", lock) == "py"
    assert release.image_name("hapiproject/hapi:v8.12.0-2", lock) == "hapi"


# ---------------------------------------------------------------------------------------------- ENG-007


def test_every_image_a_bundle_can_carry_blocks() -> None:
    """Report mode is left for the test-only mail servers; HAPI and vLLM findings block unless a dated entry
    accepts them in that image."""
    assert {"axllent/mailpit", "greenmail/standalone"} == gates_mod.VULN_REPORT_ONLY
    test_compose = (ROOT / "deploy" / "docker-compose.test.yml").read_text(encoding="utf-8")
    box_compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    for name in gates_mod.VULN_REPORT_ONLY:
        assert name in test_compose and name not in box_compose
    f = _finding()
    for ref in (HAPI, VLLM, "trialbox-postgres:16-1"):
        assert gates_mod.split_report_mode([f], ref, "report") == ([f], [])


def test_an_image_scoped_exception_accepts_the_finding_in_that_image_only() -> None:
    today = dt.date.today()
    entry = {"id": "CVE-9", "package": "openssl", "image": "hapiproject/hapi", "reason": "x" * 30,
             "review_by": (today + dt.timedelta(days=10)).isoformat()}  # fmt: skip
    allow, errors = allowlist.parse({"vulnerabilities": [entry, entry | {"image": "vllm/vllm-openai"}]}, today=today)
    assert errors == []
    f = _finding()
    assert vulns.gate([f], allow, subject=HAPI).accepted
    assert vulns.gate([f], allow, subject="docker.io/hapiproject/hapi@sha256:" + "c" * 64).accepted
    assert vulns.gate([f], allow, subject="trialbox-py:1.0.0").failing == [f]
    assert vulns.gate([f], allow).failing == [f]  # pip-audit: no image, no scoped entry applies
    _, bad = allowlist.parse({"vulnerabilities": [entry | {"image": "hapiproject/hapi:v8"}]}, today=today)
    assert any("image must be an image repository" in e for e in bad)


def test_the_committed_exceptions_are_scoped_and_dated() -> None:
    allow, errors = allowlist.load(today=allowlist.today())
    assert errors == []
    scoped = [e for e in allow.vulnerabilities if e.image]
    assert scoped and {e.image for e in scoped} == {"hapiproject/hapi", "vllm/vllm-openai", "trialbox-postgres"}
    assert not any(e.image in {"trialbox-py", "trialbox-jvm", "trialbox-demo"} for e in scoped)
    assert all(e.review_by <= dt.date(2026, 12, 10) for e in scoped)
    assert not [e for e in allow.vulnerabilities if not e.image]  # nothing accepted everywhere


def test_the_image_workflow_gates_the_db_image() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    own = re.search(r"^SC_OWN_IMAGES \?= (.*)$", makefile, re.M)
    assert own and "trialbox-postgres:16-1" in own.group(1).split()


# ---------------------------------------------------------------------------------------------- ENG-014, ENG-024


def test_one_java_version() -> None:
    """The JRE the image ships and the JDK CI tests with come from one file (.java-version)."""
    major = (ROOT / ".java-version").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+", major)
    dockerfile = (ROOT / "deploy" / "docker" / "jvm.Dockerfile").read_text(encoding="utf-8")
    jre = re.search(r"^ARG JRE_IMAGE=eclipse-temurin:(\d+)[.\-_]", dockerfile, re.M)
    assert jre and jre.group(1) == major, "the JRE image and .java-version differ"
    for wf in sorted((ROOT.parent / ".github" / "workflows").glob("trialbox-*.yml")):
        text = wf.read_text(encoding="utf-8")
        assert "java-version:" not in text, f"{wf.name} names a Java version of its own"
        if "setup-java" in text:
            assert text.count("java-version-file: trialbox/.java-version") == text.count("actions/setup-java@")


def test_ci_helper_containers_are_pinned_by_digest() -> None:
    for wf in sorted((ROOT.parent / ".github" / "workflows").glob("trialbox-*.yml")):
        for ref in re.findall(r"\b((?:rhysd/actionlint|hadolint/hadolint|python):[\w.-]+(?:@sha256:[0-9a-f]{64})?)",
                              wf.read_text(encoding="utf-8")):  # fmt: skip
            assert "@sha256:" in ref, f"{wf.name}: {ref} is pulled by tag"


# ---------------------------------------------------------------------------------------------- ENG-013


def test_font_downloads_are_pinned() -> None:
    from tools import fetch_fonts

    assert fetch_fonts.COMMIT in fetch_fonts.BASE and "/main/" not in fetch_fonts.BASE
    assert set(fetch_fonts.SHA256) == {*fetch_fonts.FONTS.values(), fetch_fonts.LICENSE}
    with pytest.raises(fetch_fonts.PinError, match="not the pinned"):
        fetch_fonts.checked(fetch_fonts.LICENSE, b"tampered")
    with pytest.raises(fetch_fonts.PinError):
        fetch_fonts.checked("https://example.org/other.ttf", b"")


def test_fhir_package_tarballs_are_pinned() -> None:
    from tools import fetch_fhir_packages as fhir

    pins = fhir.pins()
    for spec in fhir.DEFAULT_PACKAGES:
        assert spec.split("=", 1)[0] in pins, spec
    blob = b"a package"
    ok = {"x#1.0.0": hashlib.sha256(blob).hexdigest()}
    assert fhir.check_tarball("x", "1.0.0", blob, ok) == blob
    with pytest.raises(SystemExit, match="not the pinned"):
        fhir.check_tarball("x", "1.0.0", blob + b"!", ok)
    with pytest.raises(SystemExit, match="not in fhir-packages.sha256"):
        fhir.check_tarball("y", "1.0.0", blob, ok)
