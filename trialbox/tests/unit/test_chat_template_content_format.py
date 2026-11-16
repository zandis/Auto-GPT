"""D-880: the judge's server renders message content as strings, as the pinned template's string path and the offline
tokenizer do.

G-1 on lane G's VM: the server's token ids had one token more than the folder tokenizer's on every prompt with a
system message (position 22). vLLM detected the Gemma 4 template as taking content as a list of parts and wrapped
each string; the template's list branch for the system turn is ``item['text'] | trim + ' '``, a trailing space before
``<turn|>`` that its string branch does not write. Every server started with the pinned ``--chat-template`` (the
judge, which also answers the front desk) now gets ``--chat-template-content-format=string``; the serving record
reads it into a field of its own and the template check requires it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[2]
STARTERS = [
    "deploy/docker-compose.rtxpro6000.yml",
    "deploy/docker-compose.gb10.yml",
    "deploy/docker-compose.rtx5090.yml",
    "deploy/docker-compose.shared-quota.yml",
    "deploy/platform/components/gpu-pair/llm.yaml",
]

pytestmark = pytest.mark.nodb


def test_every_server_with_the_pinned_template_renders_strings() -> None:
    found = []
    for path in sorted(ROOT.glob("deploy/**/*.y*ml")):
        text = path.read_text(encoding="utf-8")
        n = len(re.findall(r"--chat-template=", text))
        if n:
            found.append(path.relative_to(ROOT).as_posix())
            assert len(re.findall(r"--chat-template-content-format=string\b", text)) == n, path
    assert sorted(found) == sorted(STARTERS)


def test_the_serving_record_reads_the_content_format() -> None:
    args = ["--model=/models/j", "--chat-template=/models/t.jinja", "--chat-template-content-format=string"]
    rec = sc.parse_args(args)
    assert rec["chat_template_content_format"] == "string"
    assert "--chat-template-content-format=string" not in rec["extra_args"]
    assert sc.parse_args(["--model=/m"])["chat_template_content_format"] is None


def _record(fmt: str | None) -> dict[str, object]:
    server = {"role": "judge", "chat_template": "/models/t.jinja", "chat_template_sha256": "a" * 64,
              "chat_template_content_format": fmt}  # fmt: skip
    return {"servers": [server]}


def test_the_template_check_requires_string_rendering() -> None:
    assert sc.template_problems(_record("string"), "a" * 64) == []
    assert any("content-format" in p for p in sc.template_problems(_record(None), "a" * 64))
    assert any("content-format" in p for p in sc.template_problems(_record("openai"), "a" * 64))
