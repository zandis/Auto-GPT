"""Settings from the environment (``TG_*``). Everything runs on this machine; the only network calls are to the local
LLM endpoint, ClinicalTrials.gov (live mode) and, for the head-to-head only, trialgpt.app."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


@dataclass(frozen=True)
class Settings:
    # "ollama" (native /api/chat: num_ctx and JSON mode honoured) or "openai" (any OpenAI-compatible server: vLLM, ...)
    llm_backend: str = field(default_factory=lambda: _env("TG_LLM_BACKEND", "ollama"))
    llm_base_url: str = field(default_factory=lambda: _env("TG_LLM_BASE_URL", "http://127.0.0.1:11434"))
    llm_model: str = field(default_factory=lambda: _env("TG_LLM_MODEL", "qwen2.5:7b"))
    llm_api_key: str = field(default_factory=lambda: _env("TG_LLM_API_KEY", "ollama"))
    # Ollama's default context (2-4k tokens) silently truncates TrialGPT prompts (patient note + all criteria);
    # every call sets num_ctx explicitly and fails loudly when the prompt does not fit.
    llm_num_ctx: int = field(default_factory=lambda: int(_env("TG_LLM_NUM_CTX", "16384")))
    llm_timeout: float = field(default_factory=lambda: float(_env("TG_LLM_TIMEOUT", "900")))
    llm_seed: int = field(default_factory=lambda: int(_env("TG_LLM_SEED", "42")))
    # live | cassette (tests: replay recorded responses, fail on a miss) | record (live + save)
    llm_mode: str = field(default_factory=lambda: _env("TG_LLM_MODE", "live"))
    cassette_dir: Path = field(default_factory=lambda: Path(_env("TG_CASSETTE_DIR", str(ROOT / "tests" / "cassettes"))))
    data_dir: Path = field(default_factory=lambda: Path(_env("TG_DATA_DIR", str(ROOT / "data"))))
    cache_dir: Path = field(default_factory=lambda: Path(_env("TG_CACHE_DIR", str(ROOT / "data" / "cache"))))
    results_dir: Path = field(default_factory=lambda: Path(_env("TG_RESULTS_DIR", str(ROOT / "results"))))
    ctgov_base: str = field(default_factory=lambda: _env("TG_CTGOV_BASE", "https://clinicaltrials.gov/api/v2"))
    device: str = field(default_factory=lambda: _env("TG_DEVICE", "cpu"))

    @property
    def model_tag(self) -> str:
        """File-name safe model id (``qwen2.5:7b`` -> ``qwen2.5-7b``)."""
        return "".join(c if c.isalnum() or c in "._-" else "-" for c in self.llm_model)


def settings() -> Settings:
    return Settings()
