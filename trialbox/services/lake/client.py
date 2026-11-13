"""Lake access for other services: HTTP client and in-process implementation share one interface."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import httpx
import pyarrow as pa
from embed_service.embedder import Embedder
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
            raise RuntimeError(f"lake query failed ({resp.status_code}): {resp.text[:500]}")
        return pa.ipc.open_stream(resp.content).read_all()

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
        hits: list[dict[str, Any]] = resp.json()["hits"]
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
        out: dict[str, Any] = resp.json()
        return out

    def put_site(self, resources: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """D-135: replace the site's own inputs on the lake service (the next rebuild joins them)."""
        resp = self.client.post(f"{self.base}/site", json={"resources": resources})
        resp.raise_for_status()
        out: dict[str, int] = resp.json()["counts"]
        return out

    def start_rebuild(self, snapshot: str, allow_empty: bool = False, promote: bool = True) -> dict[str, Any]:
        """T-690 (D-472): start a rebuild job on the lake service and answer its state (202). A refusal known at once
        (busy, a missing feed) is the service's 409, raised as ``httpx.HTTPStatusError`` (the header
        ``X-TB-Lake-Busy`` says busy). ``allow_empty`` is the in-process lake's; the service decides it itself.
        ``promote`` false (T-723, D-489): build and judge, do not serve yet (:meth:`promote`)."""
        body: dict[str, Any] = {"snapshot": snapshot} if promote else {"snapshot": snapshot, "promote": False}
        resp = self.client.post(f"{self.base}/rebuild", json=body)
        resp.raise_for_status()
        job: dict[str, Any] = resp.json()
        return job

    def promote(self, snapshot: str, generation: str | None = None) -> bool:
        """T-723 (D-489): make the built ``snapshot`` the served one; False when a newer night is served.
        ``generation``: the one the caller built; refused (409) when the date names another one now."""
        body = {"snapshot": snapshot, **({"generation": generation} if generation else {})}
        resp = self.client.post(f"{self.base}/promote", json=body)
        resp.raise_for_status()
        return bool(resp.json().get("promoted"))

    def rebuild_state(self, snapshot: str) -> dict[str, Any]:
        """The state of the snapshot's last rebuild job on the lake service (T-690, D-472)."""
        resp = self.client.get(f"{self.base}/rebuild/{snapshot}")
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body

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
        return str(resp.json().get("generation") or snapshot)

    def generation(self, snapshot: str | None = None) -> str | None:
        """T-724 (D-490): the generation the date ``snapshot`` (default the served one) names now; None when the
        lake has no snapshot, or the date was built before generations."""
        snap = snapshot or self.snapshot()
        if not snap:
            return None
        resp = self.client.get(f"{self.base}/generations/{snap}")
        resp.raise_for_status()
        got = resp.json().get("generation")
        return str(got) if got else None

    def site_in_sync(self, snapshot: str | None = None) -> bool | None:
        """T-724: whether the generation the date names was built with the site's inputs the lake holds now (None:
        not known). See :meth:`lake.store.Lake.site_in_sync`."""
        snap = snapshot or self.snapshot()
        if not snap:
            return None
        resp = self.client.get(f"{self.base}/generations/{snap}")
        resp.raise_for_status()
        got = resp.json().get("site_in_sync")
        return None if got is None else bool(got)

    def release(self, holder: str) -> bool:
        resp = self.client.delete(f"{self.base}/holds/{holder}")
        resp.raise_for_status()
        return bool(resp.json().get("released"))

    def holds(self) -> dict[str, str]:
        resp = self.client.get(f"{self.base}/holds")
        resp.raise_for_status()
        return {str(k): str(v) for k, v in resp.json()["holds"].items()}

    def snapshot(self) -> str | None:
        body = self.client.get(f"{self.base}/healthz").json()
        snap = body.get("checks", {}).get("snapshot")
        return None if snap in (None, "none") else str(snap)


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


def _refusal(resp: httpx.Response, snapshot: str) -> Exception:
    """The lake service's answer to a rebuild it would not start, as the in-process lake raises it (D-462, D-271)."""
    from lake.store import BUSY_HEADER, RebuildError, SnapshotBuilding, SnapshotHeld

    try:
        detail = str(resp.json().get("detail"))
    except ValueError:
        detail = resp.text[:500]
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
