"""D-834: the release's start-up step resolves the image pins for the images the box's stack runs, as install.sh does.

install.sh asks `docker compose config --images` and passes it to tools.image_pins as ``used`` (OPS-004b, D-574): a
pinned image no service runs (Authelia without the identity overlay, vLLM on a box whose override replaces the model
server) is "not needed on this box". Four lines later the pre-start step (ComposeBox.resolve_pins) asked for every
pinned image and stopped: "pinned images neither on the box nor in the bundle: AUTHELIA_IMAGE ... VLLM_IMAGE". A
developer machine that has pulled them never sees it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools import image_pins
from tools.trialbox import update as up

pytestmark = pytest.mark.nodb

USED = "trialbox-py:1.0.0\nhapiproject/hapi:v8.12.0-2@sha256:" + "a" * 64 + "\n"


def _box(tmp_path: Path, answer: str = USED) -> tuple[up.ComposeBox, list[list[str]]]:
    files = f"{tmp_path / 'docker-compose.yml'}:{tmp_path / 'docker-compose.identity.yml'}"  # absolute, as install.sh
    (tmp_path / ".env").write_text(f"COMPOSE_FILE={files}\n", encoding="utf-8")
    seen: list[list[str]] = []

    def run(argv: list[str], *a: Any, **kw: Any) -> str:
        seen.append(list(argv))
        return answer if argv[-2:] == ["config", "--images"] else ""

    return up.ComposeBox(tmp_path, run=run), seen


def test_resolve_pins_passes_the_images_the_stack_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got: dict[str, Any] = {}

    def resolve(deploy: Path, files: list[Path], has: Any = None, used: set[str] | None = None) -> Any:
        got["used"] = used
        return {}, [], []

    monkeypatch.setattr(image_pins, "resolve", resolve)
    monkeypatch.setattr(image_pins, "write_env", lambda *_a: None)
    box, seen = _box(tmp_path)
    box.resolve_pins()
    assert [a for a in seen if a[-2:] == ["config", "--images"]], seen
    assert got["used"] == {"trialbox-py:1.0.0", "hapiproject/hapi:v8.12.0-2@sha256:" + "a" * 64}


def test_an_unused_pinned_image_no_longer_stops_the_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end through image_pins: VLLM_IMAGE is pinned but no service runs it, and the box does not have it."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: ${PY_IMAGE:-trialbox-py:1.0.0}\n"
        "  llm:\n    image: ${VLLM_IMAGE:-vllm/vllm-openai@sha256:" + "b" * 64 + "}\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.identity.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(image_pins, "docker_has", lambda ref: ref == "trialbox-py:1.0.0")
    box, _ = _box(tmp_path, answer="trialbox-py:1.0.0\n")
    box.resolve_pins()  # before: UpdateFailed("pinned images neither on the box nor in the bundle: VLLM_IMAGE ...")


def test_a_used_pinned_image_that_is_missing_still_stops_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  llm:\n    image: ${VLLM_IMAGE:-vllm/vllm-openai@sha256:" + "b" * 64 + "}\n", encoding="utf-8"
    )
    (tmp_path / "docker-compose.identity.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(image_pins, "docker_has", lambda ref: False)
    box, _ = _box(tmp_path, answer="vllm/vllm-openai@sha256:" + "b" * 64 + "\n")
    with pytest.raises(up.UpdateFailed, match="VLLM_IMAGE"):
        box.resolve_pins()
