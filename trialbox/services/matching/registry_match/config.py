"""Settings from the environment (``TB_MATCH_*``). Nothing here names a network endpoint: models are reached only
through an injected client (:mod:`matching.registry_match.llm`) and trials only through the local mirror."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


@dataclass(frozen=True)
class Settings:
    # label of the model behind the injected client: part of the cache key and of result folder names
    model: str = field(default_factory=lambda: _env("TB_MATCH_MODEL", "unspecified"))
    # live | cassette (tests: replay recorded responses, fail on a miss) | record (live + save)
    llm_mode: str = field(default_factory=lambda: _env("TB_MATCH_LLM_MODE", "live"))
    cassette_dir: Path = field(
        default_factory=lambda: Path(
            _env("TB_MATCH_CASSETTE_DIR", str(ROOT / "tests" / "fixtures" / "match_cassettes"))
        )
    )
    data_dir: Path = field(
        default_factory=lambda: Path(_env("TB_MATCH_DATA_DIR", str(ROOT / ".cache" / "match_registry")))
    )
    cache_dir: Path = field(
        default_factory=lambda: Path(_env("TB_MATCH_CACHE_DIR", str(ROOT / ".cache" / "match_registry" / "cache")))
    )
    results_dir: Path = field(
        default_factory=lambda: Path(_env("TB_MATCH_RESULTS_DIR", str(ROOT / ".cache" / "match_registry" / "results")))
    )
    device: str = field(default_factory=lambda: _env("TB_MATCH_DEVICE", "cpu"))

    @property
    def model_tag(self) -> str:
        """File-name safe model label (``a:b/c`` -> ``a-b-c``)."""
        return "".join(c if c.isalnum() or c in "._-" else "-" for c in self.model)


def settings() -> Settings:
    return Settings()
