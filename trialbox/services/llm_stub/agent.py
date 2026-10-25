"""Deterministic tool-calling turn for agent callers (Hermes ``frontdesk_converse``) in the stub stack.

Hermes sends a free-form chat with OpenAI ``tools`` and no ``X-TB-Prompt-Id``. This stand-in makes the POC and the
e2e test exercise the real Hermes loop (tool call -> MCP front door -> tool result -> answer) without a model:

* last message a tool result: answer from it (proposal restatement + lines + confirm instruction; status rows;
  the refusal reason);
* otherwise, from the last user message: a status question calls ``tb.status``; a feasibility question calls
  ``tb.submit_request`` (type FEAS, the first four-letter study code or NEW, look-back in months when stated);
  anything else gets a short help text and no tool.

Keyword rules only; it is not a language model (DECISIONS D-13).
"""

from __future__ import annotations

import json
import re
from typing import Any

_STUDY = re.compile(r"\b([A-Z]{4})\b")
_YEARS = re.compile(r"(\d+)\s*(?:years?|yrs?|年)", re.I)
_MONTHS = re.compile(r"(\d+)\s*(?:months?|個月|か月|ヶ月)", re.I)
_STATUS = re.compile(r"status|progress|狀態|進度|状況", re.I)
_FEAS = re.compile(r"feasib|how many|enrol|recruit|做得起來|可行|何例|実施可能", re.I)
_SKIP = {"FEAS", "HELP", "TEST", "THIS", "WHAT", "WITH", "HOSP", "OVER", "LAST", "MANY"}


def _tool_name(tools: list[dict[str, Any]], suffix: str) -> str | None:
    for t in tools:
        name = str((t.get("function") or {}).get("name") or "")
        if name.endswith(suffix):
            return name
    return None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _find(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    if isinstance(obj, list):
        for v in obj:
            hit = _find(v, key)
            if hit is not None:
                return hit
    if isinstance(obj, str):  # JSON text, possibly inside Hermes' <untrusted_tool_result> wrapper
        start = obj.find("{")
        while start != -1:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(obj, start)
            except ValueError:
                start = obj.find("{", start + 1)
                continue
            return _find(parsed, key)
    return None


def _answer(tool_content: str) -> str:
    refused = _find(tool_content, "refused") or _find(tool_content, "error")
    restatement = _find(tool_content, "restatement")
    if restatement:
        commands = _find(tool_content, "commands") or []
        confirm = _find(tool_content, "confirm_instruction") or ""
        return "\n".join([str(restatement), *[str(c) for c in commands], str(confirm)]).strip()
    items = _find(tool_content, "items")
    if isinstance(items, list):
        rows = [f"{i.get('ticket_id')} {i.get('type')} {i.get('state')}" for i in items if isinstance(i, dict)]
        return "\n".join(["Your requests:", *rows]) if rows else "You have no requests yet."
    if refused:
        return f"The request was refused ({refused})."
    return "Done."


def _call(name: str, args: dict[str, Any], n: int) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": f"call_stub_{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        ],
    }


def agent_turn(body: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """``(assistant message, finish_reason)`` for one chat-completions request with ``tools``."""
    messages = [m for m in body.get("messages") or [] if isinstance(m, dict)]
    tools = [t for t in body.get("tools") or [] if isinstance(t, dict)]
    if messages and messages[-1].get("role") == "tool":
        return {"role": "assistant", "content": _answer(_text(messages[-1].get("content")))}, "stop"
    user = next((_text(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    n = len(messages)
    status_tool = _tool_name(tools, "tb_status")
    submit_tool = _tool_name(tools, "tb_submit_request")
    if _STATUS.search(user) and status_tool:
        return _call(status_tool, {}, n), "tool_calls"
    if _FEAS.search(user) and submit_tool:
        study = next((s for s in _STUDY.findall(user) if s not in _SKIP), "NEW")
        params: dict[str, Any] = {}
        if m := _YEARS.search(user):
            params["lookback"] = f"{int(m.group(1)) * 12}m"
        elif m := _MONTHS.search(user):
            params["lookback"] = f"{int(m.group(1))}m"
        lang = "ja" if re.search(r"[぀-ヿ]", user) else ("zh-TW" if re.search(r"[一-鿿]", user) else "en")
        args = {"type": "FEAS", "study": study, "params": params, "language": lang}
        return _call(submit_tool, args, n), "tool_calls"
    return {
        "role": "assistant",
        "content": "I can start a feasibility request or show the status of your requests. "
        "You can also type a line such as FEAS GZQO.",
    }, "stop"
