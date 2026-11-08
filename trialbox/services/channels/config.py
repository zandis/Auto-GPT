"""``channels`` site configuration (spec v4 §3.4.1; OPS-02; D-121).

    channels:
      engine: native          # the only engine; Hermes was removed in D-121

The block is read from the site settings mapping. Unknown keys and values fail closed, and ``engine: hermes`` names
the removal so a site file written before D-121 gets a clear message.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Engine = Literal["native"]
_KEYS = {"engine", "fallback"}


class ChannelsConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ChannelsConfig:
    engine: Engine = "native"

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any] | None) -> ChannelsConfig:
        block = dict((settings or {}).get("channels") or {})
        unknown = set(block) - _KEYS
        if unknown:
            raise ChannelsConfigError(f"channels: unknown keys {sorted(unknown)} (Hermes and Teams removed, D-121)")
        engine = block.get("engine", "native")
        if engine == "hermes":
            raise ChannelsConfigError("channels.engine hermes was removed (D-121); use native")
        if engine != "native":
            raise ChannelsConfigError(f"channels.engine must be native, got {engine!r}")
        if block.get("fallback", "native") != "native":
            raise ChannelsConfigError("channels.fallback must be native")
        return cls()
