"""Static check (spec v4 ENG-04, LLM-1): no code outside the gateway path calls a model API.

Any string literal in Python code (docstrings excluded), or any non-comment line of a shell or JavaScript file, that
contains a model API path (``/chat/completions``, ``/completions``, ``/embeddings``) fails the test, unless the file
is on the allowlist below with its reason. New exceptions need a reason and a review.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = re.compile(r"/(?:v1/)?(?:chat/)?completions\b|/(?:v1/)?embeddings\b")
SKIP_DIRS = {".venv", ".git", ".cache", "node_modules", "__pycache__", "build", "dist", ".mypy_cache", ".ruff_cache"}
OTHER_SUFFIXES = {".sh", ".js", ".mjs", ".cjs", ".ts", ".ps1"}

# path (relative to the trialbox root; a trailing / means the whole directory) -> reason
ALLOWED: dict[str, str] = {
    "services/gateway/": "tb-gateway: the one door to every model (LLM-1)",
    "libs/tb_llm/": "the only client library; it talks to the gateway's OpenAI-compatible API (ENG-04)",
    "libs/tb_common/llm.py": "v1 entry point; direct path kept for one milestone, gateway shim when TB_GATEWAY_URL",
    "services/llm_stub/": "the deterministic stub serves the API; it calls nothing",
    "tools/mlbench.py": "bake-off harness on D0 data (Z-DEV); moves behind the gateway bakeoff route in S1-14",
    "tests/unit/test_gateway.py": "drives the stub app in-process as the gateway's upstream (no network)",
    "tests/unit/test_no_direct_model_calls.py": "holds the patterns of this check",
}


def _allowed(rel: str) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in ALLOWED)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def python_hits(source: str) -> list[int]:
    """Line numbers of string literals (not docstrings) that contain a model API path."""
    tree = ast.parse(source)
    docs = _docstring_nodes(tree)
    hits: list[int] = []
    for node in ast.walk(tree):
        is_str = isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
        if is_str and MODEL_PATH.search(node.value):  # type: ignore[attr-defined]
            hits.append(node.lineno)  # type: ignore[attr-defined]
    return sorted(set(hits))


def scan(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if _allowed(rel):
            continue
        if path.suffix == ".py":
            try:
                lines = python_hits(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            out.extend(f"{rel}:{n}" for n in lines)
        elif path.suffix in OTHER_SUFFIXES:
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if not line.lstrip().startswith(("#", "//")) and MODEL_PATH.search(line):
                    out.append(f"{rel}:{n}")
    return out


@pytest.mark.req("ENG-04", "LLM-1", "S1-06")
def test_no_model_api_calls_outside_the_gateway_path() -> None:
    hits = scan(ROOT)
    assert hits == [], "direct model API calls outside services/gateway and libs/tb_llm:\n" + "\n".join(hits)
    for rel, reason in ALLOWED.items():  # every exception names something that exists and has a reason
        assert (ROOT / rel.rstrip("/")).exists(), rel
        assert reason.strip()


@pytest.mark.req("ENG-04")
def test_scanner_finds_planted_calls(tmp_path: Path) -> None:
    pkg = tmp_path / "services" / "rogue"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text(
        '"""Mentions /v1/chat/completions in a docstring only."""\n'
        "import httpx\n"
        "def f(base: str) -> None:\n"
        '    httpx.post(f"{base}/chat/completions", json={})\n'
        '    httpx.post("http://x/v1/embeddings")\n',
        encoding="utf-8",
    )
    (pkg / "b.sh").write_text("# curl /v1/completions in a comment\ncurl -s http://m/v1/completions\n")
    (pkg / "c.py").write_text('"""Docstring /v1/completions."""\nX = 1\n', encoding="utf-8")
    assert scan(tmp_path) == ["services/rogue/a.py:4", "services/rogue/a.py:5", "services/rogue/b.sh:2"]
