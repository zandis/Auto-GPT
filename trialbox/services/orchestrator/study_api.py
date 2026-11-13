"""Orchestrator API for the S-28 study store and the REDCap read-back (build step 3, D-109).

Routes (the console edits S-28 only through these):

* ``GET/PUT /studies/{rs}/settings``: study type, cohort kind, "Not suitable" reasons, screening-number format
  (S21 sections "Study" and "Screening log"; FR-STUDY-07).
* ``GET /redcap/connections``, ``PUT /redcap/connections/{ref}`` (base URL and token; the token is write-only),
  ``POST /redcap/connections/{ref}/test`` (R1 version + R2 project; S36, FR-PLAT-10).
* ``GET /redcap/connections/{ref}/dictionary`` (the project and its fields, for the set-up page's pickers, D-133),
* ``GET/PUT /studies/{rs}/redcap-link`` (the project link, validated against the data dictionary, RC-LINK-FIELD),
  ``POST /studies/{rs}/redcap-link/test`` (reads three records and shows the join; S21 "Test link").
* ``POST /studies/{rs}/redcap-read`` (Run now / nightly: R7 since the watermark, join on ``tb_screening_no``,
  registry statuses with ``source=import``; RC-LINK-DUP and conflicts listed, never resolved automatically; then,
  when the link's write-back is on, TrialBox's own instrument is imported for every changed screening number, D-123),
  ``GET /studies/{rs}/redcap-records`` (record id and subject number per pid for the screening log).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from datacore import sync
from datacore.store import TRIALBOX, DataCore
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from rc_bridge import writeback
from rc_bridge.client import RcError, RedcapClient, api_url, check_token
from rc_bridge.link import WRITE_FIELDS, LinkError, ProjectLink, read_back, validate
from tb_common.audit import AuditLog
from tb_contracts import RegistryUpdate

from orchestrator.actor import person_of
from orchestrator.candidates import FORWARD, CandidateRegistry, RegistryError
from orchestrator.studystore import StudyStore

STUDY_TYPES = ("trial", "registry", "observational")
COHORT_KINDS = ("enrolled", "dynamic")
ALL_REASONS = ("stage", "partner", "activity", "biologic", "comorbidity", "unlikely", "other")
CONSENT_SCOPES = ("opt-in", "opt-out", "waiver")
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_PREFIX = re.compile(r"^[A-Za-z0-9_-]{0,16}$")
OVERLAP = timedelta(days=1)  # the R7 watermark goes back a day so clock or zone skew never loses a change
BOT = "rc-bridge"


@dataclass
class StudyService:
    store: StudyStore
    registry: CandidateRegistry
    audit: AuditLog
    now: Callable[[], datetime]
    dc: DataCore | None = None  # the data core (one writer for TrialBox's REDCap fields, D-134); TB_DB_URL if None

    def datacore(self) -> DataCore:
        if self.dc is None:
            self.dc = DataCore()
        return self.dc

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def client(self, token_ref: str) -> RedcapClient:
        conn = self.store.connection(token_ref)
        token = self.store.token(token_ref)
        if conn is None or token is None:
            raise RcError("RC-TOKEN", f"no REDCap token named {token_ref!r} is set (S36)")
        return RedcapClient(str(conn["url"]), token)

    # ------------------------------------------------------------------ S36
    def test_connection(self, token_ref: str) -> dict[str, Any]:
        at = self.stamp()
        try:
            with self.client(token_ref) as rc:
                version = rc.check_version()
                project = rc.project()
        except RcError as exc:
            if self.store.connection(token_ref) is not None:
                self.store.record_check(token_ref, at, exc.code)
            self.audit.append("redcap.test", actor="admin", detail={"token_ref": token_ref, "result": exc.code})
            raise
        self.store.record_check(token_ref, at, "ok", version, project)
        self.audit.append("redcap.test", actor="admin", detail={"token_ref": token_ref, "result": "ok"})
        return {"ok": True, "version": version, "project_id": project.get("project_id"),
                "project_title": project.get("project_title"), "checked_at": at}  # fmt: skip

    def dictionary(self, token_ref: str) -> dict[str, Any]:
        """The project behind a token and its data dictionary, for the set-up page's field pickers (D-133, review
        F-11: the coordinator picks a field from a list instead of typing a REDCap variable name). Read only."""
        with self.client(token_ref) as rc:
            rc.check_version()
            project = rc.project()
            meta = rc.metadata()
        fields = [
            {
                "name": str(m.get("field_name") or ""),
                "label": _plain(str(m.get("field_label") or ""))[:80],
                "form": str(m.get("form_name") or ""),
                "type": str(m.get("field_type") or ""),
            }
            for m in meta
            if m.get("field_name") and m.get("field_type") != "descriptive"
        ]
        return {"project_id": project.get("project_id"), "project_title": project.get("project_title"),
                "fields": fields}  # fmt: skip

    # ------------------------------------------------------------------ S21 REDCap link
    def check_link(self, link: ProjectLink) -> tuple[RedcapClient, dict[str, Any], list[dict[str, Any]]]:
        rc = self.client(link.token_ref)
        try:
            rc.check_version()
            project = rc.project()
            meta = rc.metadata()
            validate(link, meta, project)
        except Exception:
            rc.close()
            raise
        return rc, project, meta

    def save_link(self, rs: str, body: dict[str, Any], by: str) -> dict[str, Any]:
        link = ProjectLink.from_dict({**body, "ruleset": rs})
        rc, _project, _meta = self.check_link(link)
        rc.close()
        self.store.save_link(rs, link.as_dict(), True, None, by, self.stamp())
        self.audit.append("redcap.link", ruleset=rs, actor=by, detail={"project_id": link.project_id})
        out = self.store.link(rs)
        assert out is not None
        return out

    def link_of(self, rs: str) -> ProjectLink:
        row = self.store.link(rs)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "RC-LINK-NONE", "message": "no REDCap link"})
        return ProjectLink.from_dict(row["link"])

    def test_link(self, rs: str, screening: dict[str, str]) -> dict[str, Any]:
        link = self.link_of(rs)
        rc, project, meta = self.check_link(link)
        with rc:
            rows = rc.records(fields=link.fields(), dags=bool(link.dag))
        id_field = str(meta[0]["field_name"])
        rb = read_back(link, rows, screening, id_field)
        sample = [asdict(j) for j in rb.joined[:3]]
        return {"project_id": project.get("project_id"), "project_title": project.get("project_title"),
                "records": len({str(r.get(id_field)) for r in rows}), "sample": sample,
                "duplicates": rb.duplicates, "unmatched": len(rb.unmatched)}  # fmt: skip

    # ------------------------------------------------------------------ read-back (Run now / nightly)
    def write(
        self,
        rs: str,
        link: ProjectLink,
        id_field: str,
        screening: dict[str, str],
        issued: dict[str, str],
        by: str,
        at: str,
    ) -> dict[str, Any]:
        """TrialBox's instrument through the data core (D-134): the three values are TrialBox-owned fields of the
        study's data core and the S21 link is their one source; a value goes to REDCap when it changed since the last
        push, a REDCap-side edit of one is listed as a conflict (Conflicts page), never overwritten."""
        dc = self.datacore()
        owners = dc.owners(rs)
        other = [s["name"] for s in dc.sources(rs)
                 if set((s["body"].get("field_map") or {}).values()) & set(WRITE_FIELDS)]  # fmt: skip
        taken = [f for f in WRITE_FIELDS if owners.get(f, TRIALBOX) != TRIALBOX]
        if other or taken:
            raise RcError("RC-WRITE-OWNER", "another data source writes TrialBox's REDCap fields of this study; "
                          f"one writer per field ({', '.join(other or taken)})")  # fmt: skip
        reg = {e.pid: e for e in self.registry.rows(rs)}
        entries = []
        for no, pid in screening.items():
            e = reg.get(pid)
            day = (issued.get(no) or at)[:10]
            entries.append(writeback.Entry(no=no.strip().upper(), issued=day, status=e.status if e else "candidate",
                                           status_at=e.updated_at.date().isoformat() if e else day))  # fmt: skip
        src = writeback.LinkSource(lambda: self.client(link.token_ref), link, {x.no for x in entries}, id_field)
        first = sync.sync(dc, rs, src, by, at, push=False)  # what REDCap holds: the start where TrialBox has none
        for ent in entries:
            for f, v in writeback.values(ent).items():
                dc.write(rs, ent.no, "", f, v, BOT, at, TRIALBOX)
        res = sync.sync(dc, rs, src, by, at)
        written = {**src.updated, **src.created}
        for no, rid in written.items():
            vals = dc.record(rs, no)
            self.store.put_written(rs, no, rid, writeback.digest({f: vals.get(f, "") for f in WRITE_FIELDS}), at)
        unchanged = sum(1 for no in src.record_of if no not in written)
        out = {"updated": len(src.updated), "created": len(src.created), "unchanged": unchanged,
               "waiting": sorted(n for n in res.waiting if n not in src.duplicates), "duplicates": src.duplicates,
               "conflicts": len(first.conflicts) + len(res.conflicts), "records": written}  # fmt: skip
        self.audit.append("redcap.write", ruleset=rs, actor=by,
                          detail={"updated": out["updated"], "created": out["created"],
                                  "fields": list(WRITE_FIELDS)})  # fmt: skip
        return out

    def lifecycle(self, rs: str, screening: dict[str, str], by: str) -> dict[str, Any]:
        """Each screening number is a subject that follows the screening log the read just updated (D-134)."""
        from orchestrator.lifecycle_api import LifeHost, refresh

        try:
            out = refresh(LifeHost(self.datacore(), self.registry, self.audit, self.now), rs, screening, by)
        except Exception as exc:
            return {"error": str(exc)[:200]}
        return {"made": len(out["made"]), "held": out["held"]}

    def read(
        self, rs: str, screening: dict[str, str], by: str, full: bool = False, issued: dict[str, str] | None = None,
        life_by: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """``life_by``: who the participants' steps derived from the read name (T-715: the verified person of the
        call, given by the route); ``by`` when a caller in this process gives none."""
        row = self.store.link(rs)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "RC-LINK-NONE", "message": "no REDCap link"})
        link = ProjectLink.from_dict(row["link"])
        started = self.now()
        at = started.isoformat(timespec="seconds")
        since = None
        if row.get("last_read") and not full:
            since = (datetime.fromisoformat(row["last_read"]) - OVERLAP).strftime("%Y-%m-%d %H:%M:%S")
        try:
            rc, _project, meta = self.check_link(link)
            with rc:
                rows = rc.records(fields=link.fields(), since=since, dags=bool(link.dag))
        except LinkError as exc:
            self.store.disable_link(rs, f"{exc.code}: {exc.message} {', '.join(exc.fields)}".strip())
            self.store.log_read(rs, at, by, False, {"code": exc.code, "message": exc.message, "fields": exc.fields})
            self.audit.append("redcap.read", ruleset=rs, actor=by, detail={"result": exc.code})
            raise
        except RcError as exc:
            self.store.log_read(rs, at, by, False, {"code": exc.code, "message": exc.message})
            self.audit.append("redcap.read", ruleset=rs, actor=by, detail={"result": exc.code})
            raise
        id_field = str(meta[0]["field_name"])
        rb = read_back(link, rows, screening, id_field)
        # a link value already joined to another record in an earlier read is a duplicate too (join rule)
        known = {r["link_value"]: r["record_id"] for r in self.store.records(rs)}
        dup_values = {d["link_value"] for d in rb.duplicates}
        joined = []
        for j in rb.joined:
            other = known.get(j.link_value)
            if other is not None and other != j.record_id:
                rb.duplicates.append({"code": "RC-LINK-DUP", "link_value": j.link_value,
                                      "record_ids": sorted([other, j.record_id])})  # fmt: skip
                dup_values.add(j.link_value)
                continue
            joined.append(j)
        current = {e.pid: e.status for e in self.registry.rows(rs)}
        changes: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for j in joined:
            assert j.pid is not None
            self.store.put_record(rs, asdict(j), at)
            if j.status is None:
                continue
            cur = current.get(j.pid)
            if cur == j.status:
                continue
            path = plan(cur, j.status)
            if path is None:
                conflicts.append({"link_value": j.link_value, "record_id": j.record_id, "pid": j.pid,
                                  "trialbox": cur, "redcap": j.status})  # fmt: skip
                continue
            for step in path:
                reason = j.reason if step == j.status else None
                note = f"REDCap record {j.record_id}" + (f" ({reason})" if reason else "")
                try:
                    self.registry.update(
                        rs,
                        RegistryUpdate.model_validate(
                            {"pid": j.pid, "status": step, "reason": note, "by": BOT, "source": "import"}
                        ),
                        self.now(),
                    )
                except RegistryError as exc:
                    conflicts.append({"link_value": j.link_value, "record_id": j.record_id, "pid": j.pid,
                                      "trialbox": cur, "redcap": j.status, "error": str(exc)})  # fmt: skip
                    break
            else:
                changes.append({"link_value": j.link_value, "record_id": j.record_id, "pid": j.pid,
                                "from": cur, "to": j.status})  # fmt: skip
        self.store.mark_read(rs, at)
        life = self.lifecycle(rs, screening, life_by or by)
        result: dict[str, Any] = {"at": at, "since": since, "rows": len(rows), "linked": len(joined),
                                  "changes": changes,
                  "duplicates": rb.duplicates, "unmatched": rb.unmatched, "conflicts": conflicts,
                  "no_link_value": rb.no_link_value, "outside_dag": rb.outside_dag, "life": life}  # fmt: skip
        if link.write_mode != "off":
            try:
                result["write"] = self.write(rs, link, id_field, screening, issued or {}, by, at)
            except RcError as exc:  # the read stands; the write is retried next run (nothing was recorded)
                result["write"] = {"error": exc.code, "message": exc.message}
        self.store.log_read(rs, at, by, True, result)
        self.audit.append("redcap.read", ruleset=rs, actor=by,
                          detail={"result": "ok", "changes": len(changes), "duplicates": len(rb.duplicates),
                                  "conflicts": len(conflicts),
                                  # FR-AUD-01e: every registry status change, by pseudonym (no chart number)
                                  "status_changes": [{"pid": c["pid"], "from": c["from"], "to": c["to"],
                                                      "record_id": c["record_id"]} for c in changes]})  # fmt: skip
        return result


def plan(cur: str | None, want: str) -> list[str] | None:
    """Registry steps from ``cur`` to REDCap's ``want`` (REDCap wins for its four statuses): direct when the
    registry records that transition, else through ``consented`` (a consent precedes enrolment); None = conflict."""
    base = cur or "candidate"  # a patient new to the registry starts as a candidate
    if want in FORWARD[base]:
        return [want]
    if "consented" in FORWARD[base] and want in FORWARD["consented"]:
        return ["consented", want]
    return None


# ---------------------------------------------------------------------------------------------------------- routes
class SettingsBody(BaseModel):
    study_type: str
    cohort_kind: str
    not_suitable_reasons: list[str]
    screening_no_format: str = ""
    screening_no_next: int = Field(1, ge=1, le=999999)
    consent_scope: str | None = None
    introduce_rule: str | None = None
    explainer_on: bool = False
    by: str


class ScreenScopeBody(BaseModel):
    """D-146 (review J-26): who the study's screening runs look at."""

    mode: str  # "hospital" (every patient of the hospital) | "practitioners"
    practitioners: list[str] = Field(default_factory=list, max_length=200)
    by: str


_PRACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")


class ConnectionBody(BaseModel):
    url: str
    token: str | None = None  # write-only; omitted = keep the stored one
    by: str


class LinkBody(BaseModel):
    link: dict[str, Any]
    by: str


class ReadBody(BaseModel):
    screening: dict[str, str] = Field(default_factory=dict)  # screening number -> pid (the console holds these)
    issued: dict[str, str] = Field(default_factory=dict)  # screening number -> when it was issued (write-back)
    by: str = BOT
    full: bool = False


def _plain(label: str) -> str:
    """A REDCap field label without its HTML (labels may carry rich text)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", label)).strip()


def _rs(rs: str) -> str:
    rid = rs.strip().upper()
    if not _RS.match(rid):
        raise HTTPException(status_code=400, detail={"code": "BAD-STUDY", "message": "not a study id"})
    return rid


def _fail(exc: RcError | LinkError) -> HTTPException:
    status = exc.status if isinstance(exc, RcError) else 409
    fields = exc.fields if isinstance(exc, LinkError) else []
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message, "fields": fields})


def router(get: Callable[[], StudyService]) -> APIRouter:
    r = APIRouter()

    @r.get("/studies/{rs}/settings")
    def get_settings(rs: str) -> dict[str, Any]:
        row = get().store.settings(_rs(rs))
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "STUDY-UNSET", "message": "no settings saved yet"})
        return row

    @r.put("/studies/{rs}/settings")
    def put_settings(rs: str, body: SettingsBody) -> dict[str, Any]:
        if body.study_type not in STUDY_TYPES or body.cohort_kind not in COHORT_KINDS:
            raise HTTPException(status_code=400, detail={"code": "STUDY-FIELD", "message": "unknown type or kind"})
        if not body.not_suitable_reasons or any(x not in ALL_REASONS for x in body.not_suitable_reasons):
            raise HTTPException(status_code=400, detail={"code": "STUDY-FIELD", "message": "unknown reason"})
        if not _PREFIX.match(body.screening_no_format):
            raise HTTPException(status_code=400, detail={"code": "STUDY-FIELD", "message": "bad number format"})
        if body.consent_scope is not None and body.consent_scope not in CONSENT_SCOPES:
            raise HTTPException(status_code=400, detail={"code": "STUDY-FIELD", "message": "unknown consent scope"})
        svc = get()
        rid = _rs(rs)
        row = svc.store.save_settings(rid, body.model_dump(exclude={"by"}), body.by, svc.stamp())
        svc.audit.append("study.settings", ruleset=rid, actor=body.by, detail={"study_type": body.study_type})
        return row

    @r.get("/studies/{rs}/screen-scope")
    def get_screen_scope(rs: str) -> dict[str, Any]:
        """D-146 (review J-26): who a screening run of the study looks at; ``mode`` None until it is set."""
        row = get().store.screen_scope(_rs(rs))
        return row or {"ruleset": _rs(rs), "mode": None, "practitioners": []}

    @r.put("/studies/{rs}/screen-scope")
    def put_screen_scope(rs: str, body: ScreenScopeBody) -> dict[str, Any]:
        pract = [p.strip() for p in body.practitioners if p.strip()]
        if body.mode not in ("hospital", "practitioners"):
            raise HTTPException(status_code=400, detail={"code": "STUDY-FIELD", "message": "unknown screening scope"})
        if body.mode == "practitioners" and (not pract or not all(_PRACT.match(p) for p in pract)):
            raise HTTPException(
                status_code=400, detail={"code": "STUDY-PRACT", "message": "practitioner ids are letters and digits"}
            )
        svc = get()
        rid = _rs(rs)
        row = svc.store.save_screen_scope(rid, body.mode, pract, body.by, svc.stamp())
        svc.audit.append("study.screen_scope", ruleset=rid, actor=body.by,
                         detail={"mode": body.mode, "practitioners": len(pract)})  # fmt: skip
        return row

    @r.get("/redcap/connections")
    def connections() -> dict[str, Any]:
        svc = get()
        return {"connections": svc.store.connections(), "links": svc.store.links()}

    @r.put("/redcap/connections/{ref}")
    def put_connection(ref: str, body: ConnectionBody) -> dict[str, Any]:
        svc = get()
        try:
            svc.store.token_path(ref)
            url = api_url(body.url)[: -len("/api")]
            token = check_token(body.token) if body.token else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "RC-FIELD", "message": str(exc)}) from exc
        except RcError as exc:
            raise _fail(exc) from exc
        if token is None and svc.store.token(ref) is None:
            raise HTTPException(status_code=400, detail={"code": "RC-TOKEN", "message": "enter the token once"})
        svc.store.save_connection(ref, url, body.by, svc.stamp())
        if token is not None:
            svc.store.put_token(ref, token)
        svc.audit.append("redcap.connection", actor=body.by, detail={"token_ref": ref, "token_changed": bool(token)})
        conn = svc.store.connection(ref)
        assert conn is not None
        return conn

    @r.post("/redcap/connections/{ref}/test")
    def test_connection(ref: str) -> dict[str, Any]:
        try:
            return get().test_connection(ref)
        except RcError as exc:
            raise _fail(exc) from exc

    @r.get("/redcap/connections/{ref}/dictionary")
    def dictionary(ref: str) -> dict[str, Any]:
        try:
            get().store.token_path(ref)  # a token name, never a path
            return get().dictionary(ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "RC-FIELD", "message": str(exc)}) from exc
        except RcError as exc:
            raise _fail(exc) from exc

    @r.get("/studies/{rs}/redcap-link")
    def get_link(rs: str) -> dict[str, Any]:
        svc = get()
        rid = _rs(rs)
        row = svc.store.link(rid)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "RC-LINK-NONE", "message": "no REDCap link"})
        return {**row, "reads": svc.store.last_reads(rid)}

    @r.put("/studies/{rs}/redcap-link")
    def put_link(rs: str, body: LinkBody) -> dict[str, Any]:
        try:
            return get().save_link(_rs(rs), body.link, body.by)
        except (RcError, LinkError) as exc:
            raise _fail(exc) from exc

    @r.post("/studies/{rs}/redcap-link/test")
    def test_link(rs: str, body: ReadBody) -> dict[str, Any]:
        try:
            return get().test_link(_rs(rs), body.screening)
        except (RcError, LinkError) as exc:
            raise _fail(exc) from exc

    @r.post("/studies/{rs}/redcap-read")
    def run_read(rs: str, body: ReadBody, request: Request) -> dict[str, Any]:
        # T-715 (D-483): a step derived from the read names the verified person (or the console's nightly timer)
        life_by = person_of(request, "request.prepare", service=True)
        try:
            return get().read(_rs(rs), body.screening, body.by, body.full, body.issued, life_by)
        except (RcError, LinkError) as exc:
            raise _fail(exc) from exc

    @r.get("/studies/{rs}/redcap-records")
    def records(rs: str) -> list[dict[str, Any]]:
        return get().store.records(_rs(rs))

    return r
