"""Deep review 2026-11-13 (operations): the gateway's slots per endpoint (D-445) must be the model server's
``--max-num-seqs`` on every GPU form. No compose file gave the gateway ``TB_GATEWAY_SLOTS`` or a serving record, so
it ran with its built-in 16 everywhere: 4 times the rtx5090 server's 4 sequences and twice the GB10's 8. Calls
beyond the server's sequences then queued inside vLLM with the gateway's read clock running, and an interactive
call queued behind the night's batch instead of hearing ``model_busy``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FORMS = ("rtxpro6000", "rtx5090", "gb10", "shared-quota")


def _load(form: str) -> dict[str, Any]:
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    path = ROOT / "deploy" / f"docker-compose.{form}.yml"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=Loader) or {}


def _seqs(spec: dict[str, Any]) -> str:
    """The value the judge's server is started with for ``--max-num-seqs`` (a compose expression)."""
    for arg in spec.get("command") or []:
        m = re.fullmatch(r"--max-num-seqs=(.+)", str(arg))
        if m:
            return m.group(1)
    raise AssertionError("no --max-num-seqs")


@pytest.mark.parametrize("form", FORMS)
def test_the_gateway_slots_are_the_judge_servers_sequences(form: str) -> None:
    services = _load(form)["services"]
    seqs = _seqs(services["llm-service"])
    env = (services.get("gateway") or {}).get("environment") or {}
    assert str(env.get("TB_GATEWAY_SLOTS")) == seqs, (form, env.get("TB_GATEWAY_SLOTS"), seqs)


@pytest.mark.parametrize("form", FORMS)
def test_the_verifier_server_has_as_many_sequences_as_the_judge_by_default(form: str) -> None:
    """``TB_GATEWAY_SLOTS`` is one number for every endpoint: it is right for the verifier only while both servers
    default to the same sequences (a per-endpoint setting is a decision for lane D, recorded in the review)."""
    services = _load(form)["services"]
    if "llm-verifier" not in services:
        pytest.skip("no verifier on this form")

    def default(expr: str) -> str:
        m = re.fullmatch(r"\$\{\w+:?[-?](.*)\}", expr)
        return m.group(1) if m else expr

    assert default(_seqs(services["llm-verifier"])) == default(_seqs(services["llm-service"]))
