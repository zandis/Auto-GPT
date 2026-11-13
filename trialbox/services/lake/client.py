"""Lake access for other services: HTTP client and in-process implementation share one interface."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import httpx
import pyarrow as pa
from embed_service.embedder import Embedder
from tb_common.http import ServiceError
from tb_contracts import ChunkSearchRequest, LakeQuery, dump


class LakeAPI(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table: ...

    def chunks_search(
        self,
        pid: str,
        query: str,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def snapshot(self) -> str | None: ...


class LakeUnhealthy(ServiceError):
    """The lake answered, but not with a health answer that says which snapshot it serves (D-672). Never to be read
    as "the lake holds no data". A service's failure (``tb_common.http.ServiceError``), so a job that meets it ends
    "The lake service failed." with the status, not as an internal error."""

    def __init__(self, status: int) -> None:
        super().__init__(
            "lake",
            status,
            "its health answer does not say which snapshot it serves: the lake is not healthy or could not read "
            "its snapshot. This is not a lake without data",
        )


class LakeBadAnswer(ServiceError):
    """The lake answered 200 with something that is not its answer to the call: not JSON, not an object, without
    the key the call reads, or the key of another kind (NEW-B-32, D-673). An error of the lake: never read as "no",
    "not known" or a name. The message says what is missing, never the body."""

    def __init__(self, status: int, what: str) -> None:
        super().__init__("lake", status, f"its answer {what}; this is not the lake's answer to the call")


class LakeQueryFailed(ServiceError):
    """A query the lake service did not answer with a table (D-673): a failure of the lake service with its
    status, so a caller can tell it from a fault of the code (it was a plain ``RuntimeError``). Its words are as
    before, ``lake query failed (<status>): <the lake's sentence>``: callers read the engine's sentence in them."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__("lake", status, detail)
        self.args = (f"lake query failed ({status}): {detail}",)


_MISSING: Any = object()


def _object(resp: httpx.Response) -> dict[str, Any]:
    """The answer's JSON object, after the status was checked."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise LakeBadAnswer(resp.status_code, "is not a JSON object")
    return body


def _key(resp: httpx.Response, key: str, kinds: tuple[type, ...], none: bool = False) -> Any:
    """The value of ``key`` in the answer: there, and of one of ``kinds`` (``none``: null is an answer too). A
    bool is not taken for a number, nor an empty text for a name."""
    got = _object(resp).get(key, _MISSING)
    if got is None and none:
        return None
    ok = got is not _MISSING and isinstance(got, kinds) and not (isinstance(got, bool) and bool not in kinds)
    if not ok or got == "":
        raise LakeBadAnswer(resp.status_code, f"has no usable '{key}'")
    return got


def _table(resp: httpx.Response) -> pa.Table:
    try:
        return pa.ipc.open_stream(resp.content).read_all()
    except Exception:
        raise LakeBadAnswer(resp.status_code, "is not a table") from None


class LakeHttp:
    def __init__(self, base_url: str, timeout: float = 330, poll: Any = None) -> None:
        self.base = base_url.rstrip("/")
        from tb_common.service_auth import auth_headers

        self.client = httpx.Client(timeout=timeout, headers=auth_headers())  # D-127 (F-11)
        self._poll = poll  # T-690 (D-472): how a rebuild job is followed (tb_common.jobpoll.Poll); settings if None

    @staticmethod
    def _named(snapshot: str | None) -> tuple[date | None, dict[str, str]]:
        """T-724 (D-490): a snapshot name as the request's date and, for a generation (``<date>.g<n>``), the header
        that carries its number: the request contracts are unchanged."""
        if not snapshot:
            return None, {}
        from lake.store import GENERATION_HEADER, split_generation

        snap, seq = split_generation(snapshot)
        return date.fromisoformat(snap), ({GENERATION_HEADER: str(seq)} if seq is not None else {})

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        day, headers = self._named(snapshot)
        body = dump(LakeQuery(sql=sql, params=params or [], snapshot=day))
        resp = self.client.post(f"{self.base}/query", json=body, headers=headers)
        if resp.status_code != 200:
            raise LakeQueryFailed(resp.status_code, _detail(resp))
        return _table(resp)

    def chunks_search(
        self,
        pid: str,
        query: str,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
    ) -> list[dict[str, Any]]:
        day, headers = self._named(snapshot)
        req = ChunkSearchRequest(pid=pid, query=query, k=k, date_from=date_from, date_to=date_to, snapshot=day)
        resp = self.client.post(f"{self.base}/chunks/search", json=dump(req), headers=headers)
        resp.raise_for_status()
        hits: list[dict[str, Any]] = _key(resp, "hits", (list,))
        return hits

    def vec_s2b(self, pid: str, dids: list[str], query: str, snapshot: str | None = None) -> dict[str, Any]:
        """T-203b (D-449): S2b's ranking from the vector store on the lake service. Any failure to get an answer is
        the fallback answer (the cascade then ranks on the fly and records it), never an error of the run."""
        from vec.s2b import UNAVAILABLE, fallback

        body = {"pid": pid, "dids": dids, "query": query, "snapshot": snapshot}
        try:
            resp = self.client.post(f"{self.base}/vec/s2b", json=body)
        except httpx.HTTPError:
            return fallback(UNAVAILABLE)
        if resp.status_code != 200:
            return fallback(f"{UNAVAILABLE} (lake {resp.status_code})")
        try:
            out: dict[str, Any] = _object(resp)
        except LakeBadAnswer:  # D-673: an answer that cannot be read is no answer: the fallback, as the docstring says
            return fallback(f"{UNAVAILABLE} (lake answered something else)")
        ranked = out.get("state") == "vec"
        if not isinstance(out.get("state"), str) or (ranked and not isinstance(out.get("model"), str)):
            return fallback(f"{UNAVAILABLE} (lake answered something else)")  # the cascade reads a ranking's model
        return out

    def put_site(self, resources: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """D-135: replace the site's own inputs on the lake service (the next rebuild joins them)."""
        resp = self.client.post(f"{self.base}/site", json={"resources": resources})
        resp.raise_for_status()
        out: dict[str, int] = _key(resp, "counts", (dict,))
        return out

    def start_rebuild(self, snapshot: str, allow_empty: bool = False, promote: bool = True) -> dict[str, Any]:
        """T-690 (D-472): start a rebuild job on the lake service and answer its state (202). A refusal known at once
        (busy, a missing feed) is the service's 409, raised as ``httpx.HTTPStatusError`` (the header
        ``X-TB-Lake-Busy`` says busy). ``allow_empty`` is the in-process lake's; the service decides it itself.
        ``promote`` false (T-723, D-489): build and judge, do not serve yet (:meth:`promote`)."""
        body: dict[str, Any] = {"snapshot": snapshot} if promote else {"snapshot": snapshot, "promote": False}
        resp = self.client.post(f"{self.base}/rebuild", json=body)
        resp.raise_for_status()
        return _object(resp)

    def promote(self, snapshot: str, generation: str | None = None) -> bool:
        """T-723 (D-489): make the built ``snapshot`` the served one; False when a newer night is served.
        ``generation``: the one the caller built; refused (409) when the date names another one now."""
        body = {"snapshot": snapshot, **({"generation": generation} if generation else {})}
        resp = self.client.post(f"{self.base}/promote", json=body)
        resp.raise_for_status()
        return bool(_key(resp, "promoted", (bool,)))  # D-673: a missing key is not "a newer night is served"

    def rebuild_state(self, snapshot: str) -> dict[str, Any]:
        """The state of the snapshot's last rebuild job on the lake service (T-690, D-472)."""
        resp = self.client.get(f"{self.base}/rebuild/{snapshot}")
        resp.raise_for_status()
        return _object(resp)

    def rebuild(self, snapshot: str, promote: bool = True) -> dict[str, Any]:
        """Rebuild ``snapshot`` and answer its counts: the job is started and followed to its end (T-690, D-472), never
        timed (OD-10). Busy (held, already building, held at the swap) raises :class:`lake.store.LakeBusy`; a refusal
        of the data :class:`lake.store.RebuildError`; a failed, interrupted or lost job ``RuntimeError``."""
        return follow_rebuild(
            lambda: self.start_rebuild(snapshot, promote=promote),
            lambda: self.rebuild_state(snapshot),
            snapshot,
            self._poll,
        )

    def hold(self, snapshot: str, holder: str, pin: bool = False) -> str:
        """T-305b (D-403): ``holder`` (a job) reads ``snapshot`` to its end: not rebuilt, not pruned. With ``pin``
        (T-724, D-490) it pins a generation, which is returned: see :meth:`lake.store.Lake.hold`."""
        resp = self.client.post(f"{self.base}/holds", json={"snapshot": snapshot, "holder": holder, "pin": pin})
        resp.raise_for_status()
        got = _key(resp, "generation", (str,), none=True)  # D-673: null is "held, not pinned"; missing is not
        return str(got) if got else snapshot

    def generation(self, snapshot: str | None = None) -> str | None:
        """T-724 (D-490): the generation the date ``snapshot`` (default the served one) names now; None when the
        lake has no snapshot, or the date was built before generations."""
        snap = snapshot or self.snapshot()
        if not snap:
            return None
        resp = self.client.get(f"{self.base}/generations/{snap}")
        resp.raise_for_status()
        got = _key(resp, "generation", (str,), none=True)  # D-673: null is "built before generations"
        return str(got) if got else None

    def site_in_sync(self, snapshot: str | None = None) -> bool | None:
        """T-724: whether the generation the date names was built with the site's inputs the lake holds now (None:
        not known). See :meth:`lake.store.Lake.site_in_sync`."""
        snap = snapshot or self.snapshot()
        if not snap:
            return None
        resp = self.client.get(f"{self.base}/generations/{snap}")
        resp.raise_for_status()
        got = _key(resp, "site_in_sync", (bool,), none=True)  # D-673: null is the lake's "not known"
        return None if got is None else bool(got)

    def release(self, holder: str) -> bool:
        resp = self.client.delete(f"{self.base}/holds/{holder}")
        resp.raise_for_status()
        return bool(_key(resp, "released", (bool,)))

    def holds(self) -> dict[str, str]:
        resp = self.client.get(f"{self.base}/holds")
        resp.raise_for_status()
        return {str(k): str(v) for k, v in _key(resp, "holds", (dict,)).items()}

    def snapshot(self) -> str | None:
        """The snapshot the lake serves, from its ``/healthz``. **None only for a healthy lake that has none**
        (NEW-B-31, D-672): callers read None as "this lake holds no data".

        * a name under ``checks.snapshot``: that name, also from a lake that answers 503 because another of its
          checks failed (its snapshot check did not: the name is the served night);
        * ``"none"`` from a healthy lake (200): None;
        * anything else raises :class:`LakeUnhealthy`: the lake's snapshot check failed (``/healthz`` then answers
          503 and names the check in place of its key), ``"none"`` from a lake that is not healthy, an answer that
          is not the lake's health answer (a proxy's page, another status). The error carries the status, never
          the body. A lake that cannot be reached raises the transport's error, as before."""
        resp = self.client.get(f"{self.base}/healthz")
        try:
            body = resp.json()
        except ValueError:
            body = None
        checks = body.get("checks") if isinstance(body, dict) else None
        snap = checks.get("snapshot") if isinstance(checks, dict) else None
        if isinstance(snap, str) and snap and snap != "none":
            return snap
        if snap == "none" and resp.status_code == 200:
            return None
        raise LakeUnhealthy(resp.status_code)


class LakeLocal:
    """In-process lake (tests, single-host tools)."""

    def __init__(
        self,
        lake_dir: Path,
        embedder: Embedder,
        tz: str | None = None,
        vec_store: Any = None,
        mrn_regex: str | None = None,
    ) -> None:
        from lake.store import Lake

        self.lake = Lake(lake_dir, tz, mrn_regex)
        self.embedder = embedder
        self.vec_store = vec_store  # T-203b: a vec.store.VecStore (or a fake) for S2b behind the flag vec.s2b

    def vec_s2b(self, pid: str, dids: list[str], query: str, snapshot: str | None = None) -> dict[str, Any]:
        return self.lake.vec_s2b(pid, dids, query, self.embedder, self.vec_store, snapshot)

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        return self.lake.query(sql, params, snapshot)

    def chunks_search(
        self,
        pid: str,
        query: str,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.lake.search(pid, query, self.embedder, k, date_from, date_to, snapshot)

    def snapshot(self) -> str | None:
        return self.lake.current()

    def put_site(self, resources: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        return self.lake.put_site(resources)

    def hold(self, snapshot: str, holder: str, pin: bool = False) -> str:
        return self.lake.hold(snapshot, holder, pin=pin)

    def generation(self, snapshot: str | None = None) -> str | None:
        return self.lake.generation(snapshot) if (snapshot or self.lake.current()) else None

    def site_in_sync(self, snapshot: str | None = None) -> bool | None:
        return self.lake.site_in_sync(snapshot)

    def release(self, holder: str) -> bool:
        return self.lake.release(holder)

    def holds(self) -> dict[str, str]:
        return self.lake.holds()

    def rebuild(self, snapshot: str, allow_empty: bool = False, promote: bool = True) -> dict[str, Any]:
        st = self.lake.rebuild(snapshot, self.embedder, promote=promote, allow_empty=allow_empty, check=not promote)
        return {"snapshot": st.snapshot, "tables": st.tables, "chunks": st.chunks, "seconds": st.seconds,
                "generation": st.generation}  # fmt: skip

    def promote(self, snapshot: str, generation: str | None = None) -> bool:
        return self.lake.promote_built(snapshot, generation)

    def start_rebuild(self, snapshot: str, allow_empty: bool = False, promote: bool = True) -> dict[str, Any]:
        """The in-process lake runs the job here and answers its end (no client limit to outlast: T-690)."""
        return self.lake.start_rebuild(
            snapshot, self.embedder, promote=promote, allow_empty=allow_empty, check=not promote
        )

    def rebuild_state(self, snapshot: str) -> dict[str, Any]:
        return self.lake.rebuild_state(snapshot)


NOT_THE_LAKES = "an answer without the lake's own sentence; its body is not kept"


def _detail(resp: httpx.Response) -> str:
    """What the lake service said (NEW-B-31, D-672): its ``detail`` when the answer is the lake's own (a JSON
    object whose ``detail`` is a sentence: D-664 made those safe). Any other body (a proxy's page, another
    responder's trace, JSON of another shape) is not repeated: it is not the lake's, and it can hold anything."""
    try:
        body = resp.json()
    except ValueError:
        return NOT_THE_LAKES
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list) and detail:  # the service's answer to a request of the wrong shape (D-551)
        return f"the request was refused as malformed ({len(detail)} problem(s)); its parts are not repeated"
    return detail if isinstance(detail, str) and detail else NOT_THE_LAKES


def _refusal(resp: httpx.Response, snapshot: str) -> Exception:
    """The lake service's answer to a rebuild it would not start, as the in-process lake raises it (D-462, D-271)."""
    from lake.store import BUSY_HEADER, RebuildError, SnapshotBuilding, SnapshotHeld

    detail = _detail(resp)
    if resp.status_code == 409:
        busy = resp.headers.get(BUSY_HEADER)
        if busy == "building":
            return SnapshotBuilding(detail)
        if busy:
            return SnapshotHeld(detail)
        return RebuildError(detail)
    return RuntimeError(f"lake service answered {resp.status_code} for snapshot {snapshot}: {detail}")


def follow_rebuild(
    start: Callable[[], dict[str, Any]], read: Callable[[], dict[str, Any]], snapshot: str, poll: Any = None
) -> dict[str, Any]:
    """Start a rebuild job over HTTP (``start``: the POST, raising ``httpx.HTTPStatusError`` on a refusal) and follow
    its state (``read``: the GET) to its end; the answer as :func:`rebuild_answer` gives it (T-690, D-472). The caller
    chooses the HTTP seam (``LakeHttp``'s client, the adapter's module-level calls); the logic is one."""
    from tb_common.jobpoll import Poll

    try:
        job = start()
    except httpx.HTTPStatusError as exc:
        raise _refusal(exc.response, snapshot) from None
    if job.get("state") == "running":
        job = (poll or Poll()).until_done(read, f"lake rebuild {snapshot}")
    return rebuild_answer(job, snapshot)


def rebuild_answer(job: dict[str, Any], snapshot: str) -> dict[str, Any]:
    """A rebuild job that ended, as its counts or the in-process lake's exception (T-690, D-472)."""
    from lake.store import RebuildError, SnapshotBuilding, SnapshotHeld

    state, detail = job.get("state"), str(job.get("detail") or "")
    if state == "done":
        out: dict[str, Any] = dict(job.get("result") or {})
        out.setdefault("snapshot", snapshot)
        return out
    if state == "busy":
        raise (SnapshotBuilding if job.get("busy") == "building" else SnapshotHeld)(detail or "lake busy")
    if state == "refused":
        raise RebuildError(detail)
    raise RuntimeError(f"lake rebuild of {snapshot} {state}: {detail}")
