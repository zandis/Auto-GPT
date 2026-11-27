"""Client for ``POST /api/v1/tools``. De-identified only (D-1043): an answer that does not say ``deidentified:
``true`` is refused. Writes wait for a person to confirm.

The tool token is not the ``/api/`` token. The call is made only when ``GET /api/v1/capabilities`` lists the
``trialbox`` module. With the module off the EDC answers 404, and this client does not send the tool call.
"""

from __future__ import annotations

import os
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


def http_client() -> httpx.Client:
    """The HTTP client for the EDC's tool door (one place, so a test can give its own transport). P-13 ruling: through
    the egress guard, as the study link's client is, with the tool base's own host declared."""
    from tb_common.http import declared_client

    return declared_client(tool_base(), timeout=5.0)


def connection_status(base: str, token: str, http: httpx.Client) -> dict[str, Any]:
    """D-1046: how the connection to the EDC stands, for ``/admin/edc``: set up or not, the capabilities document
    readable, the ``trialbox`` module on. ``pending`` and ``dead_letter`` (the EDC's own counts) are None: their
    shape is not in #813 or #895, and they are not guessed (asked of the owner through the integrator)."""
    out: dict[str, Any] = {"configured": bool(base and token), "reachable": False, "module": False,
                           "pending": None, "dead_letter": None, "reason": ""}  # fmt: skip
    if not out["configured"]:
        out["reason"] = "the EDC's tool URL or token is not set"
        return out
    try:
        doc = ToolClient(base, token, http).capabilities()
    except ToolError as exc:
        out["reason"] = exc.message
        return out
    out["reachable"], out["module"] = True, module_on(doc)
    return out


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
    """A write the UI is holding until the same person confirms it. Nothing is sent before that. Held in the trial
    database (``edc_backend.store``, D-1044): any console process sees it, it is confirmed once, and it expires."""

    def __init__(self, store: Any = None) -> None:
        self._store = store

    def _db(self) -> Any:
        from edc_backend import store as door

        return self._store if self._store is not None else door.default_store()

    def hold(self, actor: str, tool: str, project_id: str, record_id: str) -> str:
        if tool not in WRITE_TOOLS:
            raise ToolError("this tool does not wait for confirmation")
        return str(self._db().hold(actor, tool, project_id, record_id))

    def ids(self) -> list[str]:
        return list(self._db().open_ids())

    def take(self, actor: str, proposal_id: str) -> dict[str, str]:
        row = self._db().take(actor, proposal_id)
        if row is None:
            raise ToolError("this confirmation is not open")
        return dict(row)
