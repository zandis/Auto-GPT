"""The Hermes engine as seen from channel-relay (spec v4 §9.2; S1-11). Blocked in this build.

The relay would hand the tokenised message to Hermes through ``tb_relay_adapter`` over mTLS. Hermes may only run on a
release pinned by tag, commit SHA and mirrored image digest (HER-18). With the shipped ``hermes.lock`` that is not
the case, so :attr:`HermesEngine.available` is ``False`` and the relay falls back to the native engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from channels.native.engine import EngineTurn, EngineUnavailable
from integrations.hermes.lock import HermesLock, pin_problems


class HermesEngine:
    name = "hermes"
    actor_type = "hermes"
    client_id = "hermes"

    def __init__(self, lock_path: Path) -> None:
        self.problems = pin_problems(HermesLock.load(lock_path))
        # even a pinned lock needs the running relay-adapter connection, which this build does not ship
        self.available = False

    def converse(
        self, *, text: str, attachments: tuple[Any, ...], conv: str, assertion: str, data_class: str
    ) -> EngineTurn:
        reason = "; ".join(self.problems) or "Hermes adapter connection not built (S1-11)"
        raise EngineUnavailable(f"Hermes unavailable: {reason}")
