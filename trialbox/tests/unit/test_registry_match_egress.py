"""FR-M5-9 for the vendored TrialGPT port: no code path sends patient-derived text to ClinicalTrials.gov (S1-17).

Three layers: the vendored code holds no registry URL and imports no network client; models are reached only through
the injected client in ``llm.call_model``; and a full patient run over the mirror succeeds with sockets disabled.
"""

from __future__ import annotations

import ast
import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from matching.registry_match import pipeline, retrieval
from matching.registry_match.llm import LLMClient
from matching.registry_mirror import RegistryMirror

from tests.registry_match_mock import MockChat

ROOT = Path(__file__).resolve().parents[2]
VENDORED = [ROOT / "services" / "matching", ROOT / "eval" / "match_registry"]
PATIENT_PATH = [ROOT / "services" / "matching" / "registry_match", ROOT / "services" / "matching" / "registry_mirror"]
# a registry URL (scheme or path after the host) or the port's live-search plumbing; the bare name in prose is fine
REGISTRY_URL = re.compile(
    r"https?://[^\s'\"]*clinicaltrials\.gov|clinicaltrials\.gov/|ctgov_base|/api/v2/studies|query\.(cond|term|locn)",
    re.I,
)
NETWORK_MODULES = {"httpx", "requests", "urllib", "urllib3", "aiohttp", "http", "socket", "websockets", "tb_llm"}


def _py_files(dirs: list[Path]) -> list[Path]:
    return sorted(p for d in dirs for p in d.rglob("*.py"))


def test_there_is_vendored_code_to_check() -> None:
    names = {p.name for p in _py_files(PATIENT_PATH)}
    assert {"core.py", "pipeline.py", "retrieval.py", "llm.py", "mirror.py", "convert.py"} <= names


@pytest.mark.parametrize(
    "line",
    [
        'ctgov_base: str = field(default_factory=lambda: _env("TG_CTGOV_BASE", "https://clinicaltrials.gov/api/v2"))',
        'r = client.get(f"{settings().ctgov_base}/studies", params=params)',
        'params: dict[str, Any] = {field: cond, "pageSize": per_condition, "format": "json"}  # query.cond',
        "url = 'https://www.ClinicalTrials.gov/api/v2/studies?query.term=' + keyword",
    ],
)
def test_the_grep_catches_the_ports_live_search(line: str) -> None:
    assert REGISTRY_URL.search(line)


@pytest.mark.req("FR-M5-9")
@pytest.mark.parametrize("path", _py_files(VENDORED), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_registry_url_or_live_search_in_vendored_code(path: Path) -> None:
    hits = [f"{i}: {line.strip()}" for i, line in enumerate(path.read_text("utf-8").splitlines(), 1)]
    hits = [h for h in hits if REGISTRY_URL.search(h.split(": ", 1)[1])]
    assert not hits, f"registry URL or live-search parameter in {path.relative_to(ROOT)}: {hits}"


@pytest.mark.req("FR-M5-9")
@pytest.mark.parametrize("path", _py_files(PATIENT_PATH), ids=lambda p: str(p.relative_to(ROOT)))
def test_patient_path_imports_no_network_client(path: Path) -> None:
    tree = ast.parse(path.read_text("utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                mods.add(arg.value.split(".")[0])
    assert not mods & NETWORK_MODULES, f"{path.name} imports {sorted(mods & NETWORK_MODULES)}"


@pytest.mark.req("FR-M5-9")
def test_models_are_called_only_through_call_model() -> None:
    callers = []
    for path in _py_files(PATIENT_PATH):
        tree = ast.parse(path.read_text("utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "client":
                    callers.append(f"{path.name}:{fn.name}")
    assert callers == ["llm.py:call_model"]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    attempts: list[Any] = []

    def refuse(self: socket.socket, address: Any) -> None:
        attempts.append(address)
        raise OSError(f"network disabled in this test: {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: refuse(None, a))  # type: ignore[arg-type]
    yield attempts


@pytest.mark.req("FR-M5-9")
def test_a_patient_run_over_the_mirror_needs_no_network(
    no_network: list[Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TB_MATCH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        retrieval, "encode_articles", lambda docs, batch=16: np.ones((len(docs), 768), dtype=np.float32)
    )
    monkeypatch.setattr(retrieval, "encode_queries", lambda texts: np.ones((len(texts), 768), dtype=np.float32))
    mirror = RegistryMirror.from_dir(ROOT / "tests" / "fixtures" / "open_data", "ctgov_*.json")
    chat = MockChat()
    note = "A 64-year-old man in the ICU with acute kidney injury, creatinine 4.2 mg/dL, potassium 5.9 mmol/L."
    run = pipeline.run_patient(note, client=LLMClient(chat), mirror=mirror, recruiting_only=False, top_k=2)
    assert run.retrieved and run.ranked and no_network == []
    sent = [m["content"] for c in chat.calls for m in c["messages"]]
    assert any("acute kidney injury" in s for s in sent)  # the note went only to the injected client
    assert not list((tmp_path / "cache").rglob("*.json"))  # and was not written to disk
