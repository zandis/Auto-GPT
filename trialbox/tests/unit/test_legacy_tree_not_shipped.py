"""The repository's top-level legacy code (everything outside ``trialbox/`` and ``.github/``) is never part of the
release build or its SBOM inputs (hygiene item 3). Read-only: the build commands, contexts and Dockerfiles of every
shipped image, the SBOM inputs and the host tree the bundle carries are read from the tree; no image is built.

Every shipped image is built from a context inside ``trialbox/``; a Docker context cannot reach above itself, so no
file of the legacy tree can enter an image. The legacy tree is not deleted: its history stays."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.nodb, pytest.mark.guard]

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
MAKEFILE = ROOT / "Makefile"
# the release targets that build a shipped image (make release-images runs `images` and `demo-bundle`)
RELEASE_TARGETS = ("images", "images-multiarch", "demo-bundle")
KEEP_TOP = {"trialbox", ".github"}


def _legacy_top() -> set[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    tops = {p.split("/", 1)[0] for p in out.decode("utf-8", "surrogateescape").split("\0") if p}
    return tops - KEEP_TOP


def _make_var(name: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    m = re.search(rf"^{re.escape(name)}\s*[:?]?=\s*(.*)$", text, re.MULTILINE)
    assert m, f"Makefile has no {name}"
    return m.group(1)


def _recipe(target: str) -> list[str]:
    """The recipe lines of a Makefile target, continuation lines joined."""
    lines = MAKEFILE.read_text(encoding="utf-8").replace("\\\n", " ").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"^{re.escape(target)}:", line))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line.strip())
    return body


def _inside_trialbox(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def _build_contexts(cmd: str) -> list[str]:
    """The context argument of each ``docker build`` / ``docker buildx build`` in one shell line."""
    out = []
    for part in re.split(r"&&|;|\|", cmd):
        words = shlex.split(re.sub(r"\$\([^)]*\)", "", part))
        if "docker" not in words or "build" not in words:
            continue
        args = words[words.index("build") + 1 :]
        positional, skip = [], False
        for word in args:
            if skip:
                skip = False
                continue
            if word.startswith("-"):
                skip = "=" not in word and word not in ("--push", "--load", "-q", "--quiet", "--no-cache", "--pull")
                continue
            positional.append(word)
        if positional:
            out.append(positional[-1])
    return out


def test_the_legacy_tree_is_there_and_is_not_trialbox() -> None:
    legacy = _legacy_top()
    assert legacy, "the repository has no top-level legacy tree any more: drop this test's premise with a ruling"
    assert not any(name.startswith("trialbox") for name in legacy)


@pytest.mark.parametrize("target", RELEASE_TARGETS)
def test_every_release_image_build_runs_in_a_context_inside_trialbox(target: str) -> None:
    contexts = [c for line in _recipe(target) for c in _build_contexts(line)]
    assert contexts, f"make {target} builds no image any more: this test must follow it"
    for context in contexts:
        assert _inside_trialbox(ROOT / context), f"make {target}: build context {context} is outside trialbox/"
        assert not context.startswith(("/", "..")), f"make {target}: build context {context}"


def test_the_database_image_script_builds_inside_trialbox() -> None:
    lines = (ROOT / "deploy" / "build_db_image.sh").read_text(encoding="utf-8").splitlines()
    assert 'cd "$(dirname "$0")/.."' in lines  # the script's folder's parent: trialbox/
    build = next(line for line in lines if line.startswith("exec docker build"))
    assert build.split()[-1] == "deploy/docker"


def test_every_compose_build_context_is_inside_trialbox() -> None:
    seen = 0
    for compose in sorted((ROOT / "deploy").glob("docker-compose*.yml")):
        # compose's own merge tags (!reset, !override) are dropped: only the build keys are read here
        text = re.sub(r"!(reset|override)\b", "", compose.read_text(encoding="utf-8"))
        doc = yaml.safe_load(text) or {}
        for name, svc in (doc.get("services") or {}).items():
            build = (svc or {}).get("build")
            if build is None:
                continue
            context = build if isinstance(build, str) else build.get("context", ".")
            seen += 1
            assert _inside_trialbox(compose.parent / context), f"{compose.name}: {name} builds from {context}"
    assert seen, "no compose file builds an image any more: this test must follow them"


def _copy_sources(dockerfile: Path) -> list[str]:
    text = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ")
    sources = []
    for line in text.splitlines():
        words = line.strip().split()
        if not words or words[0].upper() not in ("COPY", "ADD"):
            continue
        args = [w for w in words[1:] if not w.startswith("--")]
        if any(w.startswith("--from=") for w in words[1:]):
            continue
        sources.extend(args[:-1])
    return sources


def test_no_shipped_dockerfile_copies_from_outside_its_context() -> None:
    dockerfiles = _make_var("RELEASE_DOCKERFILES").split()
    assert len(dockerfiles) >= 6
    for rel in dockerfiles:
        sources = _copy_sources(ROOT / rel)
        assert sources, f"{rel} copies nothing from its context?"
        for src in sources:
            assert not src.startswith(("/", "..")) and "/../" not in src, f"{rel}: COPY {src} leaves the context"


def test_the_scanned_images_are_the_release_images_and_their_dockerfiles() -> None:
    own = set(_make_var("SC_OWN_IMAGES").split())
    pairs = dict(item.split("=", 1) for item in _make_var("IMAGE_SCAN_IMAGES").split())
    assert set(pairs) == own
    assert set(pairs.values()) == set(_make_var("RELEASE_DOCKERFILES").split())


def test_the_sbom_inputs_are_inside_trialbox() -> None:
    # the lock's SBOM: an environment installed from trialbox's own lock, never the legacy requirements
    env = " ".join(_recipe("lock-env"))
    assert "-r deploy/requirements.lock" in env
    assert not re.search(r"(^|\s)(\.\./|/)\S*requirements", env)
    lock_sbom = " ".join(_recipe("lock-sbom"))
    assert "--env .cache/lock-env" in lock_sbom and "--out dist/sbom/" in lock_sbom
    # the release gates' SBOMs: one per image of SC_IMAGES (the images above) and the lock's SBOM
    gates = " ".join(_recipe("release-gates"))
    assert "--lock-sbom dist/sbom/requirements.lock.cdx.json" in gates
    assert "$(foreach i,$(SC_IMAGES),--image $(i))" in gates
    assert "dir:" not in gates
    # the licence report reads those SBOMs and nothing else
    assert _recipe("licences") == ["$(SC) licences dist/sbom/*.cdx.json --out dist/sbom/licences.md"]


def test_the_bundles_host_tree_is_packed_from_trialbox() -> None:
    text = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"' in text  # tools/..: trialbox/
    assert re.search(r'-m tools\.host_tree pack --root "\$ROOT"', text)
