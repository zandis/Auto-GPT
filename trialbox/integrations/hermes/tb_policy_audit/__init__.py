"""``tb_policy_audit``: Hermes' ``pre_tool_call`` hook (spec v4 §9.6 items 8–9, HER-1, HER-21; S1-11 skeleton).

One of the three independent layers that keep Hermes to the front-door tools (HER-1): the profile's tool list, the
policy decision (``tb_common.policy`` through the orchestrator) and the audit write. It blocks on a deny, on any
error and on a decision slower than 5 s (``plugins.hook_callback_timeout: 5``); block beats approve. It logs hashes,
never arguments.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol

Decision = Literal["allow", "block"]
HOOK_TIMEOUT_S = 5.0


class AuditSink(Protocol):
    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


class TbPolicyAudit:
    def __init__(
        self,
        profile_tools: frozenset[str],
        decide: Callable[[str, Mapping[str, Any], Mapping[str, Any]], bool],
        audit: AuditSink,
        timeout_s: float = HOOK_TIMEOUT_S,
    ) -> None:
        self.profile_tools = profile_tools
        self.decide = decide
        self.audit = audit
        self.timeout_s = timeout_s
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="tb_policy")

    def pre_tool_call(self, tool: str, args: Mapping[str, Any], context: Mapping[str, Any]) -> Decision:
        reason = "allow"
        decision: Decision = "block"
        try:
            if tool not in self.profile_tools:
                reason = "not_in_profile"
            elif not context.get("assertion"):
                reason = "assertion_missing"
            else:
                fut = self._pool.submit(self.decide, tool, args, context)
                ok = fut.result(timeout=self.timeout_s)
                decision, reason = ("allow", "allow") if ok is True else ("block", "policy_deny")
        except concurrent.futures.TimeoutError:
            decision, reason = "block", "policy_timeout"
        except Exception:
            decision, reason = "block", "policy_error"
        args_sha = hashlib.sha256(json.dumps(dict(args), sort_keys=True, default=str).encode()).hexdigest()
        try:
            self.audit.append(
                "hermes.pre_tool_call",
                actor=str(context.get("sub") or "?"),
                detail={"tool": tool, "decision": decision, "reason": reason, "args_sha256": args_sha},
            )
        except Exception:
            return "block"  # no audit, no tool
        return decision
