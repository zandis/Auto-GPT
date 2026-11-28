"""P2-02 (ASSESS-1-ADDENDUM D6): the console's ``/about`` answered 503 on an installed box because the image had no
``/app/NOTICE``; the repo's route test passed, as it reads the repo's own NOTICE.

So the image's layout is checked here, without Docker: every ``COPY`` of python.Dockerfile is read, and the file
``console.about`` opens (``NOTICE``, beside ``pyproject.toml``, at the folder above ``services/``) must be one that the
base image copies to that same place under ``/app``. Every image the box ships (deploy/docker and demo; the test
and CI images are not shipped) is then one of: the base, an image whose last stage is ``FROM ${BASE_IMAGE}`` (embed,
jvm, backup: they inherit it), one that copies the whole folder to ``/app`` (demo), or one named in :data:`NOT_YET`
with the reason; a new Dockerfile is in none and fails. The ``.dockerignore`` the base image's build reads
(``python.Dockerfile.dockerignore`` beside it if there is one, else the
context's) must keep NOTICE, read in order as BuildKit reads it (``!`` takes a file back).
"""

from __future__ import annotations

import posixpath
import re
from fnmatch import fnmatch
from pathlib import Path

from console import about

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "deploy" / "docker"
APP = "/app"
COPY = re.compile(r"^COPY\s+(?:--\S+\s+)*(.+?)\s+(\S+)\s*$")
# P2-02: the db image (PostgreSQL) is built from deploy/docker alone (Makefile, deploy/build_db_image.sh), where NOTICE
# is not, and its digest is pinned in deploy/images.lock (D-204): giving it NOTICE is a new db image release.
NOT_YET = {"deploy/docker/db.Dockerfile": "a new db image release (build context and images.lock pin), not this change"}


def _copies(dockerfile: Path) -> dict[str, str]:
    return _copies_of(dockerfile.read_text(encoding="utf-8"))


def _copies_of(text: str) -> dict[str, str]:
    """source path (relative to the context, cleaned as Docker cleans it) -> destination path, for the plain COPY lines
    (no --from) of the FINAL stage: what an earlier, discarded stage copies is not in the image."""
    out: dict[str, str] = {}
    for line in re.split(r"^(?=FROM\s)", text, flags=re.M)[-1].splitlines():
        m = COPY.match(line.strip())
        if not m or "--from=" in line:
            continue
        srcs, dest = m.group(1).split(), m.group(2)
        for s in srcs:
            s = posixpath.normpath(s).lstrip("/")
            out[s] = dest if not dest.endswith("/") else dest + Path(s).name
    return out


def test_the_base_image_puts_notice_where_the_about_page_reads_it() -> None:
    rel = about.NOTICE.relative_to(ROOT).as_posix()  # "NOTICE": the folder above services/ is /app in the image
    assert about.NOTICE.parent == Path(about.__file__).resolve().parents[2]
    assert _copies(DOCKER / "python.Dockerfile").get(rel) == f"{APP}/{rel}"
    # the version line of the same page reads pyproject.toml beside it: already shipped, same rule
    assert _copies(DOCKER / "python.Dockerfile").get("pyproject.toml") == f"{APP}/pyproject.toml"


def _ships_notice(text: str) -> bool:
    on_base = re.search(r"^ARG BASE_IMAGE=trialbox-py:", text, re.M) is not None
    on_base = on_base and re.findall(r"^FROM\s+(\S+)", text, re.M)[-1] == "${BASE_IMAGE}"
    final = re.split(r"^(?=FROM\s)", text, flags=re.M)[-1]
    whole = re.search(r"^COPY\s+(?:--\S+\s+)*\.\s+/app/?\s*$", final, re.M) is not None
    return on_base or whole or _copies_of(text).get("NOTICE") == f"{APP}/NOTICE"


def test_every_image_carries_notice_or_is_named_with_its_reason() -> None:
    files = sorted(p.relative_to(ROOT).as_posix() for p in [*DOCKER.glob("*Dockerfile"), *ROOT.glob("*/Dockerfile")])
    assert "deploy/docker/python.Dockerfile" in files and "demo/Dockerfile" in files
    for rel in files:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if rel == "deploy/docker/python.Dockerfile" or rel in NOT_YET:
            continue
        assert _ships_notice(text), rel


def _kept(ignore: Path, name: str) -> bool:
    """Whether ``name`` stays in the build context under ``ignore``: the last matching line decides."""
    kept = True
    for line in ignore.read_text(encoding="utf-8").splitlines():
        pat = line.strip()
        if not pat or pat.startswith("#"):
            continue
        back = pat.startswith("!")
        pat = posixpath.normpath(pat.lstrip("!").strip()).lstrip("/").removeprefix("**/")
        if fnmatch(name, pat) or fnmatch(name, pat.rstrip("/")):
            kept = back
    return kept


def test_the_base_images_dockerignore_keeps_notice(tmp_path: Path) -> None:
    own = DOCKER / "python.Dockerfile.dockerignore"
    assert _kept(own if own.is_file() else ROOT / ".dockerignore", "NOTICE")
    probe = tmp_path / "ignore"
    probe.write_text("*\n!NOTICE\n", encoding="utf-8")
    assert _kept(probe, "NOTICE")  # the reader itself: a take-back counts
    probe.write_text("N*\n", encoding="utf-8")
    assert not _kept(probe, "NOTICE")


def test_notice_must_land_at_app_notice_of_the_final_stage() -> None:
    final = "FROM python:3.12-slim\n"
    assert _ships_notice(final + "COPY NOTICE /app/NOTICE\n")
    assert _ships_notice(final + "COPY ./NOTICE /app/\n")  # Docker cleans ./NOTICE to NOTICE
    assert _ships_notice(final + "COPY --chown=tb:tb . /app\n")
    assert not _ships_notice(final + "COPY NOTICE /tmp/NOTICE\n")  # R1: not where about.py reads it
    assert not _ships_notice(final + "COPY NOTICE /app/NOTICE.txt\n")
    assert not _ships_notice(final + "COPY --from=build NOTICE /app/NOTICE\n")  # not the repository's file
    assert not _ships_notice("FROM python:3.12-slim AS build\nCOPY . /app\n" + final + "RUN true\n")  # discarded stage
    assert not _ships_notice("FROM python:3.12-slim AS build\nCOPY NOTICE /app/NOTICE\n" + final + "RUN true\n")


def test_dockerignore_entries_are_cleaned_as_docker_cleans_them(tmp_path: Path) -> None:
    probe = tmp_path / "ignore"
    for entry in ("./NOTICE", "/NOTICE", "NOTICE/", "./**/NOTICE"):
        probe.write_text(f"{entry}\n", encoding="utf-8")
        assert not _kept(probe, "NOTICE"), entry  # R2: all of these drop NOTICE from the context
    probe.write_text("*\n!./NOTICE\n", encoding="utf-8")
    assert _kept(probe, "NOTICE")
