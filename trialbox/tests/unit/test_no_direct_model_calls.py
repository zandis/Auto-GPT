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
    "tests/unit/test_pin_model.py": "drives the stub app in-process as the gateway's upstream (no network)",
    "tests/unit/test_context_budgets.py": "T-603: shows the in-process stub enforces a context (no network)",
    "tests/unit/test_no_direct_model_calls.py": "holds the patterns of this check",
    "tests/unit/test_perimeter.py": "T-604: calls the gateway app in-process (TestClient) to show its refusal",
    "tests/unit/test_gateway_verified_caller.py": "T-212b: calls the gateway app in-process (TestClient) with "
    "synthetic service tokens to show the caller binding (no network)",
    "tools/vllm_standin.py": "D-177: the box rehearsal's stand-in for a vLLM server: serves the model API, calls none",
    "tests/unit/test_gateway_under_load.py": "T-608: posts to the gateway app in-process against a local silent "
    "socket and the in-process stub (no model, no network)",
    "tests/unit/test_vllm_standin.py": "drives the vLLM stand-in on a local port (no model, no network)",
    "services/model_guard/__init__.py": "D-177: the key and path allowlist in front of vLLM: forwards the gateway's calls",
    "tests/unit/test_model_guard.py": "drives model-guard against a local recording upstream (no model, no network)",
    "tests/unit/test_doctor_serving.py": "the doctor's serving check against local vLLM stand-ins (no network)",
    "deploy/gcp/gpu-fit-test.sh": "runs on the GPU VM: a one-line smoke prompt (no patient data) to its own servers",
    "tests/unit/test_model_swap.py": "fake vLLM servers behind an httpx.MockTransport (no network)",
    "libs/tb_testkit/scale.py": "T-687: counts the slow stub stand-in's calls in its own request log (no model)",
    "tests/unit/test_scale_gate_logic.py": "T-687: drives the stub stand-in on a local port (no model, no network)",
    "tools/phi_synth_eval.py": "survey 2026-11-07 PHI check on fictional D0 notes (Z-DEV, OpenRouter); not shipped",
    "tools/phi_synth_gen.py": "writes the fictional D0 notes for phi_synth_eval (Z-DEV); not shipped",
    "tools/bench_profile.py": "D-148 cost bench on fictional patients (Z-DEV); calls the judge directly only when the "
    "gateway refuses, and records that it did; not shipped",
    "tools/trialbox/noisy_neighbour.py": "D-432: times a fixed short prompt on the model server under a neighbour's "
    "load (the serving measurement itself); no patient text; the operator's URL",
    "tests/platform/test_isolation_drill.py": "D-432: drives noisy_neighbour against an in-process fake on the loopback",
    "tests/unit/test_gpu_prep.py": "drives bench_profile against an in-process stub (no network)",
    "tests/unit/test_served_names.py": "a fake vLLM behind an httpx.MockTransport, strict about the served name "
    "(no network)",
    "tests/unit/test_llm_stub_served_names.py": "D-276 drives the stub app in-process: the 404 for a name it does not "
    "serve (no network)",
    "tests/unit/test_gateway_box_phi.py": "an in-process strict vLLM stand-in (served name only) behind the installed "
    "box's gateway, answering from the stub (no network)",
    "deploy/gcp/complete-run-vm.sh": "D-150 runs on the GPU VM: one smoke prompt (no patient data) to each of its own "
    "servers before READY, to prove the served names and the key",
    "tests/unit/test_weights_verified.py": "D-393 posts to the gateway app in-process (refused before any model) and "
    "fakes vLLM's GET /v1/models (no network)",
    "tests/rehearsal/": "D-150 the rehearsal's vLLM stand-in serves the API (the repository stub behind it); "
    "it calls nothing",
    "tools/g_probes.py": "G-4 (plan section 13.1) times the judge's own server with guided decoding on and off, "
    "which the gateway does not switch per call (the serving measurement itself); synthetic excerpts only, the "
    "run's own server on the GPU VM; not shipped on a box",
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
