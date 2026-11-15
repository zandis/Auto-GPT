"""D-838: `trialbox eval qualify --box` runs in the trialbox-py image, so the image carries every file qualify opens,
and the pair gate says it is alive.

On lane G's box four steps stopped with FileNotFoundError: pin (tests/fixtures/llm/judge_set.jsonl), serving_record
(deploy/images.lock), licence (docs/licences/register.csv), schema (eval/qualification/schema_probes.yaml); the
injection suite and the model change protocol were missing too. This test lays out a folder exactly as
deploy/docker/python.Dockerfile's COPY lines fill /app and runs qualify's stub pair in it: a file qualify opens that the
image lacks fails the test, whichever step opens it. The pair gate printed nothing for 20 minutes and lane G's
watchdog powered the VM off: it now prints its progress while it asks."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tools import qualify as q

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "docker" / "python.Dockerfile"

pytestmark = pytest.mark.nodb


def _image_tree(out: Path) -> list[str]:
    """/app as the Dockerfile's COPY lines fill it (copies: qualify finds its root from its own file)."""
    copied = []
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("COPY "):
            continue
        *srcs, dest = [p for p in shlex.split(s[5:]) if not p.startswith("--")]
        if not dest.startswith("/app"):
            continue
        for src in srcs:
            target = out / dest.removeprefix("/app").lstrip("/")
            if dest.endswith("/"):
                target = target / Path(src).name
            target.parent.mkdir(parents=True, exist_ok=True)
            if (ROOT / src).is_dir():
                shutil.copytree(ROOT / src, target, ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
            else:
                shutil.copy2(ROOT / src, target)
            copied.append(src)
    return copied


def test_qualify_finds_every_file_it_opens_in_the_image(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _image_tree(app)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    env.update(TB_ENV="TEST", TB_SERVICE_TOKEN="synthetic-test-token", PYTHONPATH="libs:services:.")
    res = subprocess.run(
        [sys.executable, "-m", "tools.qualify", "--stub", "--profile", "ci", "--items", "3", "--repeat-items", "3",
         "--workers", "2", "--out", str(tmp_path / "out")],
        cwd=app, env=env, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    missing = [ln for ln in res.stderr.splitlines() if re.search(r"FileNotFoundError|No such file|is missing", ln)]
    assert not missing, "\n".join(missing)
    for step in ("pin", "licence", "schema", "injection"):
        assert f"qualify: {step}: passed" in res.stderr, res.stderr


def test_the_image_copies_the_files_lane_g_found_missing() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    for src in ("tests/fixtures/llm/judge_set.jsonl", "deploy/images.lock", "docs/licences/register.csv",
                "eval/qualification/schema_probes.yaml", "eval/injection", "docs/validation/model-change-protocol.md"):  # fmt: skip
        assert f"COPY --chown=tb:tb {src} /app/{src}" in text, src
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert not {"tests", "eval", "docs", "deploy/images.lock"} & set(ignored)


def test_the_pair_gate_says_it_is_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def slow(_j: Any, _v: Any, it: Any) -> Any:
        if it == 0:
            release.wait(5)  # the first item is the slow one: progress must not wait for it
        return it

    monkeypatch.setattr(q, "pair_item", slow)
    said: list[str] = []
    nobody: Any = None  # pair_item is replaced: no client is called

    def go() -> None:
        said.append(repr(q.run_pair(nobody, nobody, list(range(6)), 3, say=said.append, every_s=0.05)))

    t = threading.Thread(target=go)
    t.start()
    time.sleep(0.4)
    release.set()
    t.join(10)
    progress = [s for s in said if s.startswith("qualify: pair_gate:")]
    assert len(progress) >= 2, said
    assert any("5/6" in s for s in progress[:-1]) and "6/6" in progress[-1]
    assert said[-1] == repr(list(range(6)))  # the rows keep the items' order
