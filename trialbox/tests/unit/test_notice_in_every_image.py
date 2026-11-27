"""P2-02 (ASSESS-1-ADDENDUM D6): the console's ``/about`` answered 503 on an installed box because the image had no
``/app/NOTICE``; the repo's route test passed, as it reads the repo's own NOTICE.

So the image's layout is checked here, without Docker: every ``COPY`` of python.Dockerfile is read, and the file
``console.about`` opens (``NOTICE``, beside ``pyproject.toml``, at the folder above ``services/``) must be one that the
base image copies to that same place under ``/app``. The images built on that base (embed, jvm, backup) inherit it
through their last stage's ``FROM ${BASE_IMAGE}``; the demo image copies the whole folder. A ``.dockerignore`` line
that drops NOTICE from the context would empty the copy, so none may.
"""

from __future__ import annotations

import re
from pathlib import Path

from console import about

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "deploy" / "docker"
APP = "/app"
COPY = re.compile(r"^COPY\s+(?:--\S+\s+)*(.+?)\s+(\S+)\s*$")
ON_THE_BASE = ("embed.Dockerfile", "jvm.Dockerfile", "backup.Dockerfile")


def _copies(dockerfile: Path) -> dict[str, str]:
    """source path (relative to the context) -> destination path, for the plain COPY lines (no --from stage)."""
    out: dict[str, str] = {}
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        m = COPY.match(line.strip())
        if not m or "--from=" in line:
            continue
        srcs, dest = m.group(1).split(), m.group(2)
        for s in srcs:
            out[s] = dest if not dest.endswith("/") else dest + Path(s).name
    return out


def test_the_base_image_puts_notice_where_the_about_page_reads_it() -> None:
    rel = about.NOTICE.relative_to(ROOT).as_posix()  # "NOTICE": the folder above services/ is /app in the image
    assert about.NOTICE.parent == Path(about.__file__).resolve().parents[2]
    assert _copies(DOCKER / "python.Dockerfile").get(rel) == f"{APP}/{rel}"
    # the version line of the same page reads pyproject.toml beside it: already shipped, same rule
    assert _copies(DOCKER / "python.Dockerfile").get("pyproject.toml") == f"{APP}/pyproject.toml"


def test_the_images_built_on_the_base_inherit_it() -> None:
    for name in ON_THE_BASE:
        text = (DOCKER / name).read_text(encoding="utf-8")
        assert re.search(r"^ARG BASE_IMAGE=trialbox-py:", text, re.M), name
        assert re.findall(r"^FROM\s+(\S+)", text, re.M)[-1] == "${BASE_IMAGE}", name


def test_no_dockerignore_drops_notice() -> None:
    for ignore in (ROOT / ".dockerignore", DOCKER / "jvm.Dockerfile.dockerignore"):
        lines = [x.strip() for x in ignore.read_text(encoding="utf-8").splitlines()]
        assert not [x for x in lines if x and not x.startswith(("#", "!")) and x.lstrip("/") in ("NOTICE", "*")]
