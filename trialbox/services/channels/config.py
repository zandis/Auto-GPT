"""``channels`` site configuration (spec v4 §3.4.1, §9, §18.1; S1-10, OPS-02).

    channels:
      engine: native          # hermes | native; Hermes is installed disabled (OPS-02)
      fallback: native        # the only fallback; switching mid-conversation loses no request (FR-CONV-6)
      hermes_lock: integrations/hermes/hermes.lock
      teams: {mode: fake}     # MS0: fake transport only; live Teams is MS4 (FR-UX-11)

The block is read from the site settings mapping. Unknown keys and values fail closed. (The block is not yet part of
``schemas/settings.schema.json``; see the S1-10 report.)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = ROOT / "integrations" / "hermes" / "hermes.lock"
Engine = Literal["hermes", "native"]
_KEYS = {"engine", "fallback", "hermes_lock", "teams"}


class ChannelsConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ChannelsConfig:
    engine: Engine = "native"
    fallback: Literal["native"] = "native"
    hermes_lock: Path = DEFAULT_LOCK
    teams_mode: Literal["fake"] = "fake"

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any] | None) -> ChannelsConfig:
        block = dict((settings or {}).get("channels") or {})
        unknown = set(block) - _KEYS
        if unknown:
            raise ChannelsConfigError(f"channels: unknown keys {sorted(unknown)}")
        engine = block.get("engine", "native")
        if engine not in ("hermes", "native"):
            raise ChannelsConfigError(f"channels.engine must be hermes or native, got {engine!r}")
        fallback = block.get("fallback", "native")
        if fallback != "native":
            raise ChannelsConfigError("channels.fallback must be native")
        teams = dict(block.get("teams") or {})
        if teams.get("mode", "fake") != "fake":
            raise ChannelsConfigError("channels.teams.mode must be fake until live Teams (MS4, FR-UX-11)")
        lock = Path(str(block.get("hermes_lock") or DEFAULT_LOCK))
        if not lock.is_absolute():
            lock = ROOT / lock
        return cls(engine=engine, fallback="native", hermes_lock=lock, teams_mode="fake")
