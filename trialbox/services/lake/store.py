"""Lake storage: NDJSON snapshot -> Parquet (partitioned by snapshot) -> per-snapshot DuckDB with FTS (SPEC §3.2, §4.5).

Layout under ``<lake_dir>``::

    ndjson/<snapshot>/<Type>.ndjson           written by the adapter
    parquet/snapshot=<snapshot>/<table>.parquet
    db/<snapshot>.duckdb                     tables + document_chunk(embedding FLOAT[1024]) + FTS index
    embed_cache.duckdb                       sha256(chunk text) -> embedding (embed new chunks only)
    CURRENT                                  snapshot served by default
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from embed_service.embedder import Embedder
from tb_common.crypto import sha256_text

from lake.flatten import SCHEMAS, Flattener
from lake.textproc import chunk, token_string

log = logging.getLogger("lake")
DIM = 1024
_ARROW = {
    "VARCHAR": pa.string(),
    "DATE": pa.date32(),
    "TIMESTAMP": pa.timestamp("us"),
    "DOUBLE": pa.float64(),
}


_CONNECT_LOCK = threading.Lock()


def fts_extension_path() -> str:
    import duckdb_extension_fts as ext

    candidates = sorted(Path(ext.__file__).parent.glob("extensions/*/fts.duckdb_extension"))
    if not candidates:
        raise RuntimeError("duckdb-extension-fts wheel has no extension binary")
    return str(candidates[-1])


@dataclass
class RebuildStats:
    snapshot: str
    tables: dict[str, int]
    chunks: int
    embedded_new: int
    seconds: float


class Lake:
    def __init__(self, lake_dir: Path, tz: str = "Asia/Taipei") -> None:
        self.dir = lake_dir
        self.tz = tz
        self._lock = threading.Lock()
        for sub in ("ndjson", "parquet", "db"):
            (lake_dir / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ snapshots
    def current(self) -> str | None:
        p = self.dir / "CURRENT"
        return p.read_text().strip() if p.exists() else None

    def snapshots(self) -> list[str]:
        return sorted(p.stem for p in (self.dir / "db").glob("*.duckdb"))

    def db_path(self, snapshot: str | None = None) -> Path:
        snap = snapshot or self.current()
        if not snap:
            raise FileNotFoundError("lake has no snapshot yet (run adapter / rebuild)")
        path = self.dir / "db" / f"{snap}.duckdb"
        if not path.exists():
            raise FileNotFoundError(f"no lake snapshot {snap}")
        return path

    # ------------------------------------------------------------------ rebuild
    def rebuild(self, snapshot: str, embedder: Embedder, ndjson_dir: Path | None = None) -> RebuildStats:
        t0 = time.perf_counter()
        src = ndjson_dir or self.dir / "ndjson" / snapshot
        by_type: dict[str, list[dict[str, Any]]] = {}
        for f in sorted(src.glob("*.ndjson")):
            with f.open(encoding="utf-8") as fh:
                by_type[f.stem] = [json.loads(line) for line in fh if line.strip()]
        rows = Flattener(self.tz).flatten(by_type)
        pdir = self.dir / "parquet" / f"snapshot={snapshot}"
        pdir.mkdir(parents=True, exist_ok=True)
        for name, cols in SCHEMAS.items():
            schema = pa.schema([(c, _ARROW[t]) for c, t in cols])
            table = pa.Table.from_pylist(rows[name], schema=schema)
            pq.write_table(table, pdir / f"{name}.parquet")
        # chunks
        chunk_rows: list[dict[str, Any]] = []
        for doc in sorted(rows["document"], key=lambda r: r["did"]):
            for i, text in enumerate(chunk(doc["text"] or "")):
                chunk_rows.append(
                    {
                        "did": doc["did"],
                        "chunk_no": i,
                        "pid": doc["pid"],
                        "date": doc["date"],
                        "type": doc["type"],
                        "text": text,
                        "tok": token_string(text),
                        "sha": sha256_text(text),
                    }
                )
        vectors, new = self._embed(chunk_rows, embedder)
        db_path = self.dir / "db" / f"{snapshot}.duckdb"
        tmp = db_path.with_suffix(".building")
        tmp.unlink(missing_ok=True)
        con = duckdb.connect(str(tmp))
        try:
            con.execute(f"LOAD '{fts_extension_path()}'")
            for name in SCHEMAS:
                con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet(?)", [str(pdir / f"{name}.parquet")])
            con.execute(
                f"CREATE TABLE document_chunk (did VARCHAR, chunk_no INTEGER, pid VARCHAR, date TIMESTAMP, "
                f"type VARCHAR, text VARCHAR, tok VARCHAR, embedding FLOAT[{DIM}], chunk_key VARCHAR)"
            )
            if chunk_rows:
                arrow = pa.Table.from_pylist(
                    [
                        {
                            **{k: r[k] for k in ("did", "chunk_no", "pid", "date", "type", "text", "tok")},
                            "embedding": vectors[r["sha"]],
                            "chunk_key": f"{r['did']}#{r['chunk_no']}",
                        }
                        for r in chunk_rows
                    ]
                )
                con.register("chunks_arrow", arrow)
                con.execute(
                    f"INSERT INTO document_chunk SELECT did, chunk_no, pid, date, type, text, tok, "
                    f"embedding::FLOAT[{DIM}], chunk_key FROM chunks_arrow"
                )
                con.unregister("chunks_arrow")
                con.execute(
                    "PRAGMA create_fts_index('document_chunk', 'chunk_key', 'tok', stemmer='none', "
                    "stopwords='none', ignore='\\s+', strip_accents=0, lower=1, overwrite=1)"
                )
            con.execute(
                "CREATE TABLE lake_meta AS SELECT ? AS snapshot, ? AS built_at",
                [snapshot, time.strftime("%Y-%m-%dT%H:%M:%S")],
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()
        tmp.replace(db_path)
        (self.dir / "CURRENT").write_text(snapshot)
        counts = {name: len(rows[name]) for name in SCHEMAS}
        return RebuildStats(snapshot, counts, len(chunk_rows), new, round(time.perf_counter() - t0, 2))

    def _embed(self, chunk_rows: list[dict[str, Any]], embedder: Embedder) -> tuple[dict[str, list[float]], int]:
        cache = duckdb.connect(str(self.dir / "embed_cache.duckdb"))
        try:
            cache.execute(
                f"CREATE TABLE IF NOT EXISTS cache (sha VARCHAR, model VARCHAR, vec FLOAT[{DIM}], "
                "PRIMARY KEY (sha, model))"
            )
            shas = sorted({r["sha"] for r in chunk_rows})
            have: dict[str, list[float]] = {}
            if shas:
                cache.register("want", pa.table({"sha": shas}))
                for sha, vec in cache.execute(
                    "SELECT c.sha, c.vec FROM cache c JOIN want w USING (sha) WHERE c.model = ?",
                    [embedder.model],
                ).fetchall():
                    have[sha] = list(vec)
                cache.unregister("want")
            missing = [s for s in shas if s not in have]
            text_by_sha = {r["sha"]: r["text"] for r in chunk_rows}
            for i in range(0, len(missing), 64):
                batch = missing[i : i + 64]
                vecs = embedder.embed([text_by_sha[s] for s in batch])
                for s, v in zip(batch, vecs, strict=True):
                    have[s] = v
                cache.register("newvecs", pa.table({"sha": batch, "model": [embedder.model] * len(batch), "vec": vecs}))
                cache.execute(f"INSERT OR REPLACE INTO cache SELECT sha, model, vec::FLOAT[{DIM}] FROM newvecs")
                cache.unregister("newvecs")
            return have, len(missing)
        finally:
            cache.close()

    # ------------------------------------------------------------------ query
    def connect(self, snapshot: str | None = None) -> duckdb.DuckDBPyConnection:
        """Read-only connection with FTS loaded, external file access disabled and configuration locked."""
        # DuckDB shares one database instance per file inside a process: a concurrent connection finds the
        # instance already hardened (FTS loaded, external access off, configuration locked) and must not re-set it.
        with _CONNECT_LOCK:
            con = duckdb.connect(str(self.db_path(snapshot)), read_only=True)
            row = con.execute("SELECT current_setting('lock_configuration')").fetchone()
            if not (row and row[0]):
                con.execute(f"LOAD '{fts_extension_path()}'")
                con.execute("SET enable_external_access = false")
                con.execute("SET lock_configuration = true")
        return con

    def query(
        self, sql: str, params: list[Any] | None = None, snapshot: str | None = None, timeout_s: int = 300
    ) -> pa.Table:
        from lake.sqlguard import check_select

        check_select(sql)
        con = self.connect(snapshot)
        timer = threading.Timer(timeout_s, con.interrupt)
        timer.start()
        try:
            return con.execute(sql, params or []).to_arrow_table()
        finally:
            timer.cancel()
            con.close()

    def search(
        self,
        pid: str,
        query: str,
        embedder: Embedder,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
        depth: int = 50,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieval restricted to ``pid`` and a date window: BM25 ∪ cosine, reciprocal-rank fusion."""
        con = self.connect(snapshot)
        try:
            where = "c.pid = ?"
            args: list[Any] = [pid]
            if date_from:
                where += " AND c.date::DATE >= ?"
                args.append(date_from)
            if date_to:
                where += " AND c.date::DATE <= ?"
                args.append(date_to)
            bm25 = con.execute(
                f"SELECT chunk_key, score FROM (SELECT c.chunk_key, "
                f"fts_main_document_chunk.match_bm25(c.chunk_key, ?) AS score FROM document_chunk c WHERE {where}) "
                f"WHERE score IS NOT NULL ORDER BY score DESC, chunk_key LIMIT {int(depth)}",
                [token_string(query), *args],
            ).fetchall()
            qvec = embedder.embed([query])[0]
            dense = con.execute(
                f"SELECT c.chunk_key, array_cosine_similarity(c.embedding, ?::FLOAT[{DIM}]) AS score "
                f"FROM document_chunk c WHERE {where} ORDER BY score DESC, chunk_key LIMIT {int(depth)}",
                [qvec, *args],
            ).fetchall()
            fused: dict[str, float] = {}
            for ranking in (bm25, dense):
                for rank, (key, _) in enumerate(ranking, start=1):
                    fused[key] = fused.get(key, 0.0) + 1.0 / (60 + rank)
            top = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
            if not top:
                return []
            keys = [kk for kk, _ in top]
            rows = {
                r[0]: r
                for r in con.execute(
                    "SELECT chunk_key, did, chunk_no, text, date, type FROM document_chunk WHERE chunk_key IN "
                    f"({', '.join('?' for _ in keys)})",
                    keys,
                ).fetchall()
            }
            return [
                {
                    "did": rows[kk][1],
                    "chunk_no": rows[kk][2],
                    "text": rows[kk][3],
                    "date": rows[kk][4].date().isoformat(),
                    "score": round(score, 6),
                    "note_type": rows[kk][5],
                }
                for kk, score in top
            ]
        finally:
            con.close()
