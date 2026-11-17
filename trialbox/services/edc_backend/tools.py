"""Client for ``POST /api/v1/tools``. De-identified only (D-1043): an answer that does not say ``deidentified:
``true`` is refused. Writes wait for a person to confirm.

The tool token is not the ``/api/`` token. The call is made only when ``GET /api/v1/capabilities`` lists the
``trialbox`` module. With the module off the EDC answers 404, and this client does not send the tool call.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

READ_TOOLS = frozenset({"find_patient", "explain_field", "draft_form", "quality_check", "summarize_queries"})
WRITE_TOOLS = frozenset({"apply_draft", "open_query"})
TOOLS = READ_TOOLS | WRITE_TOOLS


class ToolError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def tool_token(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_TOOL_TOKEN") or "").strip()


def tool_base(environ: dict[str, str] | None = None) -> str:
    """The EDC origin. ``TB_EDC_TOOL_URL`` wins; otherwise the selected backend URL without ``/api``."""
    env = os.environ if environ is None else environ
    explicit = (env.get("TB_EDC_TOOL_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    from edc_backend.config import load_config

    url = load_config(env).url.rstrip("/")
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url


def module_on(doc: dict[str, Any]) -> bool:
    return any(str(row.get("id") or "") == "trialbox" for row in doc.get("modules") or [] if isinstance(row, dict))


class ToolClient:
    def __init__(self, base: str, token: str, http: httpx.Client) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.http = http

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def capabilities(self) -> dict[str, Any]:
        try:
            resp = self.http.get(self.base + "/api/v1/capabilities", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ToolError(f"the EDC did not answer ({type(exc).__name__})") from exc
        if resp.status_code != 200:
            raise ToolError("the capabilities document was not returned")
        try:
            doc = resp.json()
        except ValueError as exc:
            raise ToolError("the capabilities document is not JSON") from exc
        if not isinstance(doc, dict):
            raise ToolError("the capabilities document is not an object")
        return doc

    def call(self, tool: str, project_id: str, *, record_id: str = "", confirm: bool = False) -> dict[str, Any]:
        if tool not in TOOLS:
            raise ToolError("unknown tool")
        if tool in WRITE_TOOLS and not confirm:
            raise ToolError("a write waits for a person to confirm")
        if not module_on(self.capabilities()):
            raise ToolError("the trialbox module is off")
        body: dict[str, Any] = {"tool": tool, "project_id": project_id, "confirm": confirm}
        if record_id:
            body["record_id"] = record_id
        try:
            resp = self.http.post(self.base + "/api/v1/tools", headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise ToolError(f"the EDC did not answer ({type(exc).__name__})") from exc
        if resp.status_code == 404:
            raise ToolError("the trialbox module is off")
        try:
            out = resp.json()
        except ValueError as exc:
            raise ToolError("the tool answer is not JSON") from exc
        if not isinstance(out, dict):
            raise ToolError("the tool answer is not an object")
        # D-1043 (D-1060): only an answer that says it is de-identified is taken: ``deidentified`` exactly ``true``.
        # No opt-in; nothing of a refused answer is passed on or said
        if out.get("deidentified") is not True:
            raise ToolError("the tool answer does not say it is de-identified; it is not used")
        return out


class Proposals:
    """A write the UI is holding until the same person confirms it. Nothing is sent before that."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, str]] = {}

    def hold(self, actor: str, tool: str, project_id: str, record_id: str) -> str:
        if tool not in WRITE_TOOLS:
            raise ToolError("this tool does not wait for confirmation")
        pid = uuid.uuid4().hex
        self._rows[pid] = {"actor": actor, "tool": tool, "project_id": project_id, "record_id": record_id}
        return pid

    def ids(self) -> list[str]:
        return list(self._rows)

    def take(self, actor: str, proposal_id: str) -> dict[str, str]:
        row = self._rows.get(proposal_id)
        if row is None or row["actor"] != actor:
            raise ToolError("this confirmation is not open")
        del self._rows[proposal_id]
        return row
