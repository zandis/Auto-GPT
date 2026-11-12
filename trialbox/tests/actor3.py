"""T-715 (D-483): a person for the tests that call the orchestrator's routes themselves.

A route with ``require_actor`` takes no person from the body, so a test that posts to it must send a v3 assertion.
``SignedClient`` is a test client that mints one for each such call, with the real ``actor_v3.mint``: for the
route's own declared action, the study of the path, this request and this body. The person is ``sub`` (or, for the
older tests that still write ``"by"`` in a body, that name, taken out of the body), with a role the matrix allows
the action. The route verifies everything as it does on a box: the client signs, it does not switch anything off.
A call that already carries an assertion (the console's own) goes through untouched.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient
from tb_common import actor_v3
from tb_common.authz import MATRIX_ROLES, Standing, permit


def role_for(action: str) -> str:
    """A role the matrix allows ``action`` with no standing (the coordinator first, as most routes are theirs)."""
    for role in ("coordinator", "investigator", *sorted(MATRIX_ROLES)):
        if permit(role, action).allowed:
            return role
    raise AssertionError(f"no role may take {action} without standing")


def signed(action: str, study: str, method: str, path: str, body: Any = None, *, sub: str = "console:crc",
           role: str = "", standing: Standing | None = None, **kw: Any) -> dict[str, str]:  # fmt: skip
    """The header of one call by ``sub``."""
    return {actor_v3.HEADER: actor_v3.mint(sub=sub, role=role or role_for(action), action=action, method=method,
                                           path=path, body=body, study=study, standing=standing, **kw)}  # fmt: skip


class SignedClient(TestClient):
    def __init__(self, app: Any, *args: Any, sub: str = "console:crc", role: str = "", **kw: Any) -> None:
        super().__init__(app, *args, **kw)
        from orchestrator.actor import walk

        self.sub, self.role = sub, role
        self._actions = [
            (m, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$"), action,
             p.split("/").index("{rs}") if "{rs}" in p.split("/") else -1)
            for m, p, stage, action, _ in walk(app) if stage == "refuse"
        ]  # fmt: skip

    def request(self, method: str, url: Any, **kw: Any) -> Any:
        headers = dict(kw.get("headers") or {})
        full = str(url)
        path = full.split("?", 1)[0]
        hit = next(((a, i) for m, rx, a, i in self._actions if m == method.upper() and rx.match(path)), None)
        if hit is not None and actor_v3.HEADER not in headers:
            action, at = hit
            sub = self.sub
            body = kw.get("json")
            if isinstance(body, dict) and "by" in body:  # an older test's way to name the person
                body = dict(body)
                name = str(body.pop("by"))
                sub = name if name.startswith(("console:", "service:")) else f"console:{name}"
                kw["json"] = body
            study = path.split("/")[at].upper() if at >= 0 else ""
            role = actor_v3.SERVICE_ROLE if sub.startswith("service:") else self.role
            headers.update(signed(action, study, method, full, body, sub=sub, role=role))
            kw["headers"] = headers
        return super().request(method, url, **kw)


def reveal_headers(study: str, job_id: str, body: Any, *, sub: str = "console:crc", role: str = "coordinator",
                   grant: dict[str, Any] | None = None, standing: Standing | None = None,
                   **kw: Any) -> dict[str, str]:  # fmt: skip
    """The assertion of one ``POST /jobs/{job_id}/reveal`` (T-716, D-484): the person, the role, the job's study
    and, under break-glass, the grant's id."""
    return signed("id.reveal", study, "POST", f"/jobs/{job_id}/reveal", body, sub=sub, role=role, standing=standing,
                  grant=grant, **kw)  # fmt: skip


def signer(study: str, *, sub: str = "console:crc", role: str = "coordinator", action: str = "id.reveal",
           grant: dict[str, Any] | None = None, standing: Standing | None = None) -> Any:  # fmt: skip
    """A ``console.backend.Signer`` for a test that calls a backend's ``reveal`` itself."""

    def sign(method: str, path: str, body: Any) -> dict[str, str]:
        return signed(action, study, method, path, body, sub=sub, role=role, standing=standing, grant=grant)

    return sign


def log_pi(username: str, study: str) -> None:
    """Name ``username`` the study's PI in the delegation log (the trial database of this test): what an
    investigator needs before the orchestrator gives them a chart number by their own rights (T-716, D-484)."""
    from console.teamstore import TeamStore

    team = TeamStore()
    team.add_entry(study, username=username, name=username, role="pi", tasks=(), start="2026-01-01", end=None,
                   training_day="2025-06-01", training_ref=None, by="stw-setup", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    team.close()
