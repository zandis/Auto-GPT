"""Lake access for other services: HTTP client and in-process implementation share one interface."""

from __future__ import annotations

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
    def __init__(self, base_url: str, timeout: float = 330) -> None:
        self.base = base_url.rstrip("/")
        from tb_common.service_auth import auth_headers

        self.client = httpx.Client(timeout=timeout, headers=auth_headers())  # D-127 (F-11)

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        body = dump(
            LakeQuery(sql=sql, params=params or [], snapshot=date.fromisoformat(snapshot) if snapshot else None)
        )
        resp = self.client.post(f"{self.base}/query", json=body)
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
        req = ChunkSearchRequest(
            pid=pid,
            query=query,
            k=k,
            date_from=date_from,
            date_to=date_to,
            snapshot=date.fromisoformat(snapshot) if snapshot else None,
        )
        resp = self.client.post(f"{self.base}/chunks/search", json=dump(req))
        resp.raise_for_status()
        hits: list[dict[str, Any]] = resp.json()["hits"]
        return hits

    def put_site(self, resources: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """D-135: replace the site's own inputs on the lake service (the next rebuild joins them)."""
        resp = self.client.post(f"{self.base}/site", json={"resources": resources})
        resp.raise_for_status()
        out: dict[str, int] = resp.json()["counts"]
        return out

    def rebuild(self, snapshot: str) -> dict[str, Any]:
        resp = self.client.post(f"{self.base}/rebuild", json={"snapshot": snapshot})
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body

    def snapshot(self) -> str | None:
        body = self.client.get(f"{self.base}/healthz").json()
        snap = body.get("checks", {}).get("snapshot")
        return None if snap in (None, "none") else str(snap)


class LakeLocal:
    """In-process lake (tests, single-host tools)."""

    def __init__(self, lake_dir: Path, embedder: Embedder, tz: str | None = None) -> None:
        from lake.store import Lake

        self.lake = Lake(lake_dir, tz)
        self.embedder = embedder

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

    def rebuild(self, snapshot: str, allow_empty: bool = False) -> dict[str, Any]:
        st = self.lake.rebuild(snapshot, self.embedder, allow_empty=allow_empty)
        return {"snapshot": st.snapshot, "tables": st.tables, "chunks": st.chunks, "seconds": st.seconds}
