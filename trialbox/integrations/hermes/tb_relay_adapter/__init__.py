"""``tb_relay_adapter``: the only way messages reach Hermes (spec v4 §9.2, HER-6, HER-7; S1-11 skeleton).

channel-relay calls this platform plugin over mTLS after sender authentication, grammar diversion and tokenisation.
The adapter re-checks every envelope before dispatch (§9.6 item 10: it must come from the relay and carry an identity
assertion; the check has a 2 s internal budget and fails closed) and sends replies back to the relay only.

Hermes' platform-plugin interface may change between releases *(stability uncertain)*, so the hooks this adapter
relies on are declared in :data:`REQUIRED_HOOKS` and checked by :func:`contract_problems` against the API surface
extracted from the pinned release (HER-7). No release is pinned in this build, so that contract test is skipped
with the S1-11 blocked reason; the envelope checks below are tested now.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# hook name -> parameter names this adapter needs from Hermes' platform-plugin API (to confirm at pinning, §9.12)
REQUIRED_HOOKS: dict[str, tuple[str, ...]] = {
    "register_platform": ("name", "adapter"),
    "deliver_inbound": ("platform", "chat_id", "text", "metadata"),
    "send_outbound": ("platform", "chat_id", "text"),
    "pre_gateway_dispatch": ("event",),
}
DISPATCH_BUDGET_S = 2.0


class EnvelopeRefused(PermissionError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RelayEnvelope:
    conv: str
    msg_sha256: str
    channel: str
    assertion: str
    text: str


class TbRelayAdapter:
    name = "tb_relay"

    def __init__(self, reply: Callable[[str, str], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.reply = reply  # (conv, text) -> back to channel-relay over mTLS
        self.clock = clock

    def accept(self, envelope: Mapping[str, Any]) -> RelayEnvelope:
        """``pre_gateway_dispatch`` re-check: relay origin, assertion present, fields typed. Fails closed."""
        t0 = self.clock()
        try:
            if envelope.get("origin") != "channel-relay":
                raise EnvelopeRefused("not_from_relay")
            fields = {k: envelope.get(k) for k in ("conv", "msg_sha256", "channel", "assertion", "text")}
            if not all(isinstance(v, str) and v for v in fields.values()):
                raise EnvelopeRefused("envelope_incomplete")
            if str(fields["assertion"]).count(".") != 2:
                raise EnvelopeRefused("assertion_missing")
            if fields["channel"] == "line":
                raise EnvelopeRefused("line_never_reaches_hermes")  # profile tb-line: canned pointer at the relay
            env = RelayEnvelope(**{k: str(v) for k, v in fields.items()})
        except EnvelopeRefused:
            raise
        except Exception as e:  # any surprise blocks the dispatch
            raise EnvelopeRefused("adapter_error") from e
        if self.clock() - t0 > DISPATCH_BUDGET_S:
            raise EnvelopeRefused("dispatch_timeout")
        return env

    def send_outbound(self, conv: str, text: str) -> None:
        self.reply(conv, text)


def contract_problems(api: Mapping[str, Callable[..., Any]]) -> list[str]:
    """Compare the pinned release's platform-plugin hooks (name -> callable) with :data:`REQUIRED_HOOKS`."""
    out: list[str] = []
    for hook, params in REQUIRED_HOOKS.items():
        fn = api.get(hook)
        if fn is None:
            out.append(f"hook {hook} missing")
            continue
        have = set(inspect.signature(fn).parameters)
        missing = [p for p in params if p not in have]
        if missing:
            out.append(f"hook {hook} lacks parameters {missing}")
    return out
