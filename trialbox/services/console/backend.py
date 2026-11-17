"""What the console reads and calls. No side doors: every request the console starts is a ``JobCreate`` on the
orchestrator's ``POST /jobs``, the same call the mail gateway makes for an e-mail, so permissions
(``settings.permissions``), the per-sender rate limit, the job audit events and the delivery routing rule all apply
unchanged. The console adds its own audit events (``console.*``) to the same hash chain.

:class:`HttpBackend` is the compose wiring; the unit tests use an in-memory implementation of :class:`Backend`.
"""

from __future__ import annotations

import json
import re
import smtplib
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Protocol

import httpx
from tb_common.audit import AuditLog
from tb_common.config import Config
from tb_common.crypto import sha256_bytes
from tb_common.http import ServiceClient, ServiceError
from tb_common.objstore import ObjectStore
from tb_common.ruleset import RulesetNotApproved, list_rulesets, load_approved, seed_working_copy
from tb_common.service_auth import actor_header
from tb_contracts import (
    Job,
    JobCreate,
    JobFile,
    RegistryEntry,
    RegistryPromote,
    RegistrySummary,
    RegistryUpdate,
    dump,
)

from console import ruleset_labels


class Refused(RuntimeError):
    """The orchestrator refused the request (permission, rate limit, invalid request)."""


class Unavailable(RuntimeError):
    """A service the console needs did not answer."""


_CODE = re.compile(r"^[A-Z][A-Z0-9-]{1,30}$")


def failed(exc: ServiceError) -> Unavailable:
    """A call to a service that failed, as the console keeps it (NEW-TRUST-3, D-555): the service and its status
    ("orchestrator returned 500"). Not the text the service answered with: that text can repeat what was sent (a
    record, a chart number of a path), and an ``Unavailable`` is shown on pages and in ``/api/v1`` answers."""
    return Unavailable(f"{exc.service} returned {exc.status}")


def service_and_status(exc: Exception) -> str:
    """What a page may say of a call that failed or was refused: a refusal's code when it has the shape of one of
    the orchestrator's codes (``RC-FIELD``), else the error's own text when it is an ``Unavailable`` (which never
    holds a service's text, see :func:`failed`), else "-"."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _CODE.match(code):
        return code
    return str(exc)[:80] if isinstance(exc, Unavailable) else "-"


class Problem(Refused):
    """A structured refusal from the orchestrator's study API (D-109): an ICD error code, a message, fields."""

    def __init__(self, status: int, code: str, message: str, fields: list[str] | None = None,
                 problems: list[dict[str, str]] | None = None,
                 detail: dict[str, Any] | None = None) -> None:  # fmt: skip
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.fields = list(fields or [])
        self.problems = list(problems or [])  # per field {field, code, ...} (a whole-form save, D-129)
        self.detail = dict(detail or {})  # the whole answer (a lifecycle refusal's why, state and allowed steps)


def problem_of(status: int, text: str) -> Exception:
    """The console's view of an orchestrator error answer: ``Problem`` when it carries a code, else Unavailable."""
    try:
        detail = json.loads(text).get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, dict) and detail.get("code"):
        return Problem(
            status,
            str(detail["code"]),
            str(detail.get("message") or ""),
            detail.get("fields") or [],
            [p for p in detail.get("problems") or [] if isinstance(p, dict)],
            detail,
        )
    if status == 0 or status >= 500:
        return Unavailable(f"orchestrator returned {status}" if status else "orchestrator did not answer")
    return Problem(status, "REFUSED", str(detail or text)[:200])


@dataclass(frozen=True)
class MailItem:
    direction: str  # "in" | "out"
    at: str
    subject: str
    party: str  # sender (in) or recipients (out)
    tag: str  # aggregate | phi | job | reject | pending
    message_id: str
    note: str = ""


@dataclass(frozen=True)
class RulesetInfo:
    id: str
    version: str | None
    status: str
    kind: str


@dataclass(frozen=True)
class Health:
    service: str
    ok: bool
    detail: str = ""


@dataclass
class AuditRecord:
    ts: str
    event: str
    actor: str | None
    job_id: str | None
    ruleset: str | None
    hash: str
    detail: dict[str, Any] = field(default_factory=dict)


#: T-716 (D-484): how a backend gets the header of a call that names a person: ``(method, path, body)`` to the
#: headers of ``console.actor.assert_for``. The backend builds the request; the console's one minting place signs it.
Signer = Callable[[str, str, Any], dict[str, str]]


class Backend(Protocol):
    def list_jobs(self, limit: int = 100, state: str | None = None) -> list[Job]: ...
    def waiting_studies(self) -> list[str]: ...
    def get_job(self, job_id: str) -> Job | None: ...
    def create_job(self, req: JobCreate, by: str = "", role: str = "") -> Job: ...
    def put_input(self, job_id: str, filename: str, data: bytes, content_type: str) -> JobFile: ...
    def get_object(self, key: str) -> bytes: ...
    def thread(self, job_id: str) -> list[MailItem]: ...
    def audit(self, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]: ...
    def recheck_share(self, job_id: str) -> dict[str, Any] | None: ...
    def rulesets(self) -> list[RulesetInfo]: ...
    def health(self) -> list[Health]: ...
    def models(self) -> dict[str, Any] | None: ...

    def run_canary(self) -> bool: ...
    def ruleset_detail(self, ruleset: str) -> dict[str, Any] | None: ...
    def ingest(self) -> dict[str, Any]: ...
    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str: ...
    def registry_summaries(self) -> list[RegistrySummary]: ...
    def registry_rows(self, ruleset: str) -> list[RegistryEntry]: ...
    def registry_update(self, ruleset: str, upd: RegistryUpdate, sign: Signer) -> RegistryEntry: ...
    def registry_promote(self, ruleset: str, req: RegistryPromote, sign: Signer) -> int: ...
    def registry_export(self, ruleset: str, by: str, role: str = "", scope: str = "") -> bytes: ...
    def reveal(self, job_id: str, pid: str, sign: Signer, purpose: str = "", reason: str = "") -> str | None: ...
    def send_notice(self, kind: str, to: list[str], subject: str, body_md: str, by: str) -> str: ...


def registry_update_body(upd: RegistryUpdate) -> dict[str, Any]:
    """What the orchestrator's registry route takes (T-715b, D-550): the change, without a person; and without a
    source (T-715c, D-552): the route sets it."""
    return {k: v for k, v in dump(upd).items() if k not in ("by", "source")}


def registry_promote_body(req: RegistryPromote) -> dict[str, Any]:
    return {"tiers": list(req.tiers)}


def criteria_of(rulesets_dir: Path, ruleset: str) -> list[dict[str, Any]]:
    """Inclusion and exclusion criteria of the approved ruleset, in protocol order (id, kind, class, label, text):
    what the role pages (D-104) print next to a verdict. Empty when there is no approved version. T-507 (D-309):
    ``action`` is the criterion's to-do and ``i18n`` the label, text and to-do the ruleset ships per language for
    exactly this text (``console.ruleset_labels``)."""
    try:
        rs = load_approved(rulesets_dir, ruleset)
    except (RulesetNotApproved, FileNotFoundError, ValueError):
        return []
    shipped = ruleset_labels.shipped(ruleset, rulesets_dir)
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "class": c.class_,
            "label": c.label or c.text[:60],
            "text": c.text,
            "action": c.action or "",
            "i18n": ruleset_labels.words(shipped.get(c.id), c.text, c.action or ""),
        }
        for c in rs.active()
        if c.kind in ("inclusion", "exclusion")
    ]


def approval_state_of(rulesets_dir: Path, ruleset: str) -> dict[str, Any] | None:
    """Whether the approved version still stands as the investigator approved it (D-318): ``approval_needed`` with
    the reasons (a newer prompt, a changed pinned prompt, another terminology release); None when nothing is
    approved. The page shows the state only; the run itself enforces the pins."""
    from tb_common.ruleset import approval_state

    try:
        rs = load_approved(rulesets_dir, ruleset)
    except (RulesetNotApproved, FileNotFoundError, ValueError):
        return None
    try:
        from criteria_compiler.terminology import resolver

        release: str | None = resolver.current_release()
    except Exception:  # the console may not read the vocabulary: no terminology reason (the run still refuses)
        release = None
    return approval_state(rs.manifest, terminology_release=release)


# ---------------------------------------------------------------------------------------------- audit reading
_SHOWN_DETAIL = (
    "from", "to", "type", "filename", "tag", "bytes", "subject", "reason", "action", "line", "role", "run",
    "source", "validation_error_pct", "intent",  # S24 ingest rows, the header command field (step 4)
    "via", "purpose",  # T-103 (D-438): where a chart number was shown and what for
)  # fmt: skip


#: NEW-RUN-1 (D-558): the figures of a weekly run's ``microbatch.budget`` event the run page says in words. They
#: are patient counts, so they are NOT among the keys every reader of the audit table sees (``_SHOWN_DETAIL``): the
#: page asks for them here and shows them only to an account that reads the study's list.
RECHECK_SHARE = ("left", "excluded_in_scope", "excluded_rescreened", "excluded_kept", "excluded_percent",
                 "excluded_full_pass_runs", "excluded_carried")  # fmt: skip


def read_recheck_share(directory: Path, job_id: str) -> dict[str, Any] | None:
    """The last ``microbatch.budget`` event of a job: its trigger and the whole numbers of :data:`RECHECK_SHARE`
    (a figure that is absent or not a whole number is left out). None when the job wrote no such event."""
    found: dict[str, Any] | None = None
    for path in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                if '"microbatch.budget"' not in raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                det = rec.get("detail")
                if rec.get("event") != "microbatch.budget" or rec.get("job_id") != job_id or not isinstance(det, dict):
                    continue
                found = {"trigger": str(det.get("trigger") or "")}
                for key in RECHECK_SHARE:
                    v = det.get(key)
                    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                        found[key] = v
    return found


def read_audit(directory: Path, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]:
    """Newest first. Only metadata keys of ``detail`` are kept (no free text, no options payloads)."""
    out: deque[AuditRecord] = deque(maxlen=limit)
    files = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
    for path in files:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if job_id and rec.get("job_id") != job_id:
                    continue
                det = rec.get("detail") or {}
                shown = {k: det[k] for k in _SHOWN_DETAIL if k in det and isinstance(det[k], str | int | float)}
                counts = det.get("counts")
                if isinstance(counts, dict):  # an ingest's resource counts: totals only (S24)
                    nums = {str(k): v for k, v in counts.items() if isinstance(v, int)}
                    shown["records"] = sum(nums.values())
                    if "Patient" in nums:
                        shown["patients"] = nums["Patient"]
                out.append(
                    AuditRecord(
                        ts=str(rec.get("ts", "")),
                        event=str(rec.get("event", "")),
                        actor=rec.get("actor"),
                        job_id=rec.get("job_id"),
                        ruleset=rec.get("ruleset"),
                        hash=str(rec.get("hash", ""))[:12],
                        detail=shown,
                    )
                )
    return list(reversed(out))


def ruleset_infos(rulesets_dir: Path) -> list[RulesetInfo]:
    out = []
    for rid in list_rulesets(rulesets_dir):
        try:
            rs = load_approved(rulesets_dir, rid)
            out.append(RulesetInfo(rid, rs.version, "approved", str(rs.manifest.kind or "")))
        except (RulesetNotApproved, FileNotFoundError, ValueError):
            out.append(RulesetInfo(rid, None, "draft", ""))
    return out


# ---------------------------------------------------------------------------------------------- compose wiring
class HttpBackend:
    def __init__(
        self,
        cfg: Config,
        store: ObjectStore,
        audit: AuditLog,
        *,
        gateway_url: str = "",
        test_smtp: str = "",
    ) -> None:
        env = cfg.env
        self.cfg = cfg
        self.store = store
        self.audit_log = audit
        self.orch = ServiceClient(env.orchestrator_url, "orchestrator", timeout=60, retries=1)
        # NEW-SEC-4 (D-760, its review): the publish of a held night is started once; a retry after a lost answer
        # met the running publish (409) and read it as "not started", so the night could be rejected while served
        self.orch_once = ServiceClient(env.orchestrator_url, "orchestrator", timeout=60, retries=0, idempotent=False)
        self.mail = ServiceClient(env.mail_gateway_url, "mail-gateway", timeout=15, retries=0)
        # T-690 (D-472): the ingest is started (202) and never waited for here; the request is short
        self.adapter = ServiceClient(env.adapter_url, "adapter", timeout=60, retries=0, idempotent=False)
        self.gateway_url = gateway_url
        self.test_smtp = test_smtp
        seed_working_copy(env.rulesets_path)  # D-469: a first copy of the shipped rulesets; never the checkout
        self.services = {
            "orchestrator": env.orchestrator_url,
            "mail-gateway": env.mail_gateway_url,
            "doc-parser": env.doc_parser_url,
            "criteria-compiler": env.compiler_url,
            "lake": env.lake_url,
            "adapter": env.adapter_url,
        }
        if gateway_url:
            self.services["gateway"] = gateway_url.removesuffix("/v1")

    def list_jobs(self, limit: int = 100, state: str | None = None) -> list[Job]:
        """The newest ``limit`` jobs; ``state``: of that state only (the orchestrator filters, so a job that
        waits behind many newer ones is still found)."""
        try:
            data = self.orch.get_json(f"/jobs?limit={limit}" + (f"&state={state}" if state else ""))
        except ServiceError as exc:
            raise failed(exc) from exc
        return [Job.model_validate(j) for j in data]

    def waiting_studies(self) -> list[str]:
        """NEW-JRN-1b (D-545): the studies with a job waiting for approval, as the orchestrator counts them (one
        row per study; no listing of jobs is read, so none is cut)."""
        try:
            data = self.orch.get_json("/jobs/waiting-studies")
        except ServiceError as exc:
            raise failed(exc) from exc
        return [str(s) for s in data]

    def get_job(self, job_id: str) -> Job | None:
        try:
            return self.orch.get(f"/jobs/{job_id}", Job)
        except ServiceError as exc:
            if exc.status == 404:
                return None
            raise failed(exc) from exc

    def create_job(self, req: JobCreate, by: str = "", role: str = "") -> Job:
        """``POST /jobs``. ``by`` and ``role``: the signed-in person (D-146, review J-01); the orchestrator then
        authorises the request by the role in the signed assertion instead of by the mailbox."""
        try:
            if by and role:
                return Job.model_validate(self.orch.post_raw("/jobs", req, actor_header(by, role=role)).json())
            return self.orch.post("/jobs", req, Job)
        except ServiceError as exc:
            if exc.status in (400, 403, 422):
                try:
                    detail = str(json.loads(exc.detail).get("detail"))
                except (ValueError, AttributeError):
                    detail = exc.detail
                raise Refused(detail) from exc
            raise failed(exc) from exc

    def retry_scheduled_job(
        self, job_id: str, *, reply_to: str, by: str, role: str, headers: dict[str, str] | None = None
    ) -> Job:
        """T-746 (D-474): ``POST /jobs/{job_id}/retry``. The orchestrator copies the failed scheduler job; the call
        names the job, the reply mailbox and the signed person and role, never a type or an option."""
        try:
            # T-715 refuse mode (D-871): the route takes the verified person's v3 assertion (``headers``)
            resp = self.orch.post_raw(f"/jobs/{job_id}/retry", {"reply_to": reply_to}, headers or {})
        except ServiceError as exc:
            if exc.status in (403, 404, 409, 422):
                try:
                    detail = str(json.loads(exc.detail).get("detail"))
                except (ValueError, AttributeError):
                    detail = exc.detail
                raise Refused(detail) from exc
            raise failed(exc) from exc
        return Job.model_validate(resp.json())

    def cancel_job(self, job_id: str, by: str, headers: dict[str, str] | None = None) -> Job:
        """S26 Cancel (step 4, FR-PLAT-12): the orchestrator's ``POST /jobs/{id}/cancel``; a queued job fails at once,
        a running one stops at its next step."""

        try:
            resp = self.orch.post_raw(f"/jobs/{job_id}/cancel", {}, headers or {})  # T-715 refuse mode (D-871)
        except ServiceError as exc:
            if exc.status == 404:
                raise Refused("no such job") from exc
            raise failed(exc) from exc
        return Job.model_validate(resp.json())

    def put_input(self, job_id: str, filename: str, data: bytes, content_type: str) -> JobFile:
        key = f"attachments/{job_id}/{filename}"
        self.store.put(key, data, content_type)
        return JobFile(filename=filename, sha256=sha256_bytes(data), minio_key=key, content_type=content_type)

    def get_object(self, key: str) -> bytes:
        return self.store.get(key)

    def thread(self, job_id: str) -> list[MailItem]:
        try:
            data = self.mail.get_json(f"/threads/{job_id}")
        except ServiceError:
            return []
        return [MailItem(**item) for item in data.get("items", [])]

    def audit(self, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]:
        return read_audit(self.audit_log.directory, job_id, limit)

    def recheck_share(self, job_id: str) -> dict[str, Any] | None:
        return read_recheck_share(self.audit_log.directory, job_id)

    def rulesets(self) -> list[RulesetInfo]:
        return ruleset_infos(self.cfg.env.rulesets_path)

    def criteria(self, ruleset: str) -> list[dict[str, str]]:
        return criteria_of(self.cfg.env.rulesets_path, ruleset)

    def approval_state(self, ruleset: str) -> dict[str, Any] | None:
        return approval_state_of(self.cfg.env.rulesets_path, ruleset)

    def models(self) -> dict[str, Any] | None:
        """The orchestrator's ``GET /models`` (judge, verifier, note-block policy in force); None when it is down."""
        try:
            data = self.orch.get_json("/models")
        except ServiceError:
            return None
        return dict(data) if isinstance(data, dict) else None

    def model_builds(self) -> list[dict[str, Any]] | None:
        """The gateway's registry view (``/registry/v1/builds``: statuses, pins, qualification records; no endpoint
        addresses) for the admin Models tile (T-012b); None without a gateway or when it does not answer."""
        base = self.services.get("gateway")
        if not base:
            return None
        try:
            data = ServiceClient(base, "gateway", timeout=10, retries=0).get_json("/registry/v1/builds")
        except ServiceError:
            return None
        builds = data.get("builds") if isinstance(data, dict) else None
        return [dict(b) for b in builds if isinstance(b, dict)] if isinstance(builds, list) else None

    def run_canary(self) -> bool:
        """Start the pair canary on the orchestrator (``POST /models/canary``); False when it is down or refused."""
        try:
            self.orch.post_raw("/models/canary", {})
        except ServiceError:
            return False
        return True

    def ruleset_detail(self, ruleset: str) -> dict[str, Any] | None:
        """The approved manifest's provenance (version, approval record, population) for the sponsor pack README
        (D-101); None when there is no approved version or the orchestrator is down."""
        try:
            data = self.orch.get_json(f"/rulesets/{ruleset}")
        except ServiceError:
            return None
        return dict(data) if isinstance(data, dict) else None

    def health(self) -> list[Health]:
        def probe(item: tuple[str, str]) -> Health:
            name, base = item
            try:
                resp = httpx.get(f"{base.rstrip('/')}/healthz", timeout=4)
            except httpx.HTTPError as exc:
                return Health(name, False, type(exc).__name__)
            detail = ""
            try:
                checks = resp.json().get("checks", {})
                if name == "lake":
                    detail = f"snapshot {checks.get('snapshot', '?')}"
                elif name == "orchestrator":
                    n_q = int(checks.get("queued_or_running", 0) or 0)
                    detail = "idle" if n_q == 0 else f"{n_q} job{'s' if n_q != 1 else ''} in progress"
            except ValueError:
                pass
            return Health(name, resp.status_code == 200, detail)

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(probe, self.services.items()))

    def ingest(self) -> dict[str, Any]:
        from tb_common.timeutil import now

        snapshot = self.cfg.env.extra.get("TB_CONSOLE_SNAPSHOT") or (now(self.cfg.env.tz).date().isoformat())
        try:
            resp = self.adapter.post_raw("/run", {"source": "csv", "snapshot": snapshot})
        except ServiceError as exc:
            raise failed(exc) from exc
        body = resp.json()  # T-690 (D-472): 202, the run id and "running"; the night's end is the adapter's audit
        return {"run": str(body.get("run") or ""), "state": str(body.get("state") or "")}

    def deceased(self, pids: list[str]) -> set[str]:
        """FIT-U04 (T-629, D-415): which of ``pids`` the lake's current snapshot records as dead (the orchestrator's
        ``POST /patients/deceased``). Raises :class:`Unavailable` when it cannot be asked: the caller then stops
        contacts instead of reading "nobody died"."""
        try:
            data = self.orch.post_raw("/patients/deceased", {"pids": list(pids)}).json()
        except ServiceError as exc:
            raise failed(exc) from exc
        return {str(p) for p in (data.get("deceased") or [])} if isinstance(data, dict) else set()

    # ------------------------------------------------------------------ candidate registry (D-92)
    def _registry_call(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
        try:
            if method == "GET":
                from console.actor import read_headers  # NEW-SEC-1 (D-717): a patient read is signed

                return self.orch._request("GET", path, headers=read_headers("GET", path, headers)).json()
            return self.orch.post_raw(path, body, headers).json()
        except ServiceError as exc:
            if exc.status in (400, 403, 404, 422, 429):
                try:
                    detail = json.loads(exc.detail).get("detail")
                    detail = str(detail.get("message") if isinstance(detail, dict) else detail)
                except (ValueError, AttributeError):
                    detail = exc.detail
                raise Refused(detail) from exc
            raise failed(exc) from exc

    def registry_summaries(self) -> list[RegistrySummary]:
        return [RegistrySummary.model_validate(s) for s in self._registry_call("GET", "/registry")]

    def registry_rows(self, ruleset: str) -> list[RegistryEntry]:
        return [RegistryEntry.model_validate(r) for r in self._registry_call("GET", f"/registry/{ruleset}")]

    def registry_update(self, ruleset: str, upd: RegistryUpdate, sign: Signer) -> RegistryEntry:
        """One registry row. T-715b (D-550): every change carries the v3 assertion ``sign`` mints for exactly this
        request; the orchestrator takes the acting person from it and refuses a call without one (403). ``upd.by``
        does not travel. T-719 (D-487): a row by chart number is also capped per person (429)."""
        path, body = f"/registry/{ruleset}", registry_update_body(upd)
        return RegistryEntry.model_validate(self._registry_call("POST", path, body, sign("POST", path, body)))

    def registry_promote(self, ruleset: str, req: RegistryPromote, sign: Signer) -> int:
        path, body = f"/registry/{ruleset}/promote", registry_promote_body(req)
        return int(self._registry_call("POST", path, body, sign("POST", path, body))["added"])

    def reveal(self, job_id: str, pid: str, sign: Signer, purpose: str = "", reason: str = "") -> str | None:
        """The chart number of one listed pseudonym (D-99): the orchestrator resolves and audits it; None when the
        box has no pid map for it. T-716 (D-484): the call carries the v3 assertion ``sign`` mints for exactly this
        request (the person, the role, the study, the standing, a break-glass grant's id); the orchestrator reads
        the grant and the delegation log itself, and its refusal (403: right, study, grant, opted out, not listed;
        429: its cap) is a refusal here. T-103 (D-438): the purpose and reason go with the request into the
        orchestrator's audit record."""
        path = f"/jobs/{job_id}/reveal"
        body = {"pid": pid, **({"purpose": purpose} if purpose else {}), **({"reason": reason} if reason else {})}
        try:
            data = self.orch.post_raw(path, body, sign("POST", path, body)).json()
        except ServiceError as exc:
            if exc.status == 404:
                return None
            if exc.status in (400, 403, 409, 422, 429):
                raise Refused(exc.detail) from exc
            raise failed(exc) from exc
        mrn = data.get("mrn") if isinstance(data, dict) else None
        return str(mrn) if mrn else None

    def send_notice(self, kind: str, to: list[str], subject: str, body_md: str, principal: str) -> str:
        """A notice (N1, N2, HEALTH, ACCOUNT, BG) through the orchestrator's ``POST /notices`` and the mail gateway;
        the message id. T-715 refuse mode: signed as ``principal``, the sender's own service name (``console.actor``:
        NOTIFY, SAE_SYNC, ACCOUNTS, BREAKGLASS), never a person: the person who caused it is in the console's audit."""
        from console import actor

        body = {"kind": kind, "to": to, "subject": subject, "body_md": body_md}
        headers = actor.assert_service(principal, actor.NOTICE_ACTION[principal], None, "POST", "/notices", body)
        try:
            data = self.orch.post_raw("/notices", body, headers).json()
        except ServiceError as exc:
            if exc.status in (400, 403, 422):
                raise Refused(exc.detail) from exc
            raise failed(exc) from exc
        return str(data.get("message_id") or "")

    def study_api(self, method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        """The orchestrator's S-28 study store and REDCap routes (D-109); ``headers`` carry the signed-in user's
        signed assertion where the orchestrator acts on who the user is (EDC prefill, D-162)."""
        try:
            kw: dict[str, Any] = {} if body is None else {"json": body}
            if headers:
                kw["headers"] = headers
            return self.orch._request(method, path, **kw).json()
        except ServiceError as exc:
            raise problem_of(exc.status, exc.detail) from exc

    def registry_export(self, ruleset: str, by: str, role: str = "", scope: str = "") -> bytes:
        """The screening log with chart numbers; the orchestrator verifies the signed actor, its role and its studies
        (D-273), audits and rate-limits it (S-09)."""
        try:
            hdr = actor_header(by, role=role, scope=scope)
            return self.orch._request("GET", f"/registry/{ruleset}/export.xlsx", headers=hdr).content
        except ServiceError as exc:
            if exc.status in (403, 429):
                raise Refused(exc.detail) from exc
            raise failed(exc) from exc

    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str:
        """Test profile only (GreenMail): what a staff mail client would send. The ``Authentication-Results`` header
        stands in for the hospital MTA, exactly as ``tools/send_test_mail.py`` does."""
        if not self.test_smtp:
            raise Unavailable("no test mail server configured (TB_CONSOLE_TEST_SMTP)")
        host, _, port = self.test_smtp.partition(":")
        m = EmailMessage()
        domain = sender.rsplit("@", 1)[-1]
        m["From"] = sender
        m["To"] = to
        m["Subject"] = subject
        m["Message-ID"] = mid = make_msgid(domain=domain)
        authserv = self.cfg.env.extra.get("TB_MAIL_AUTHSERV_ID") or "mx." + to.rsplit("@", 1)[-1]
        m["Authentication-Results"] = f"{authserv}; spf=pass smtp.mailfrom={domain}; dkim=pass header.d={domain}"
        m.set_content(body or "Sent from the TrialBox console test mailbox.")
        for name, data in files:
            m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
        try:
            with smtplib.SMTP(host, int(port or 25), timeout=30) as s:
                s.send_message(m)
        except OSError as exc:
            raise Unavailable(f"test mail server: {type(exc).__name__}") from exc
        return mid
