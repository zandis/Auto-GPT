"""Schema ``sitesetup`` of the trial database (D-126, D-135): what a site put in, and what people decided about it.

* ``input``: each sheet, dump or chart (kind, file name, hash, where the file sits in the protected data folder, who,
  when, the column roles, a summary). The patient of a chart is its pseudonym; a chart number is never stored.
* ``fact``: one fact per row, keyed by the pseudonym, with its *status*: ``coded`` (a sheet or dump, used as is),
  ``proposed`` (read from a chart by the model, beside its ``quote``), ``confirmed`` (a person confirmed or corrected
  it; ``before`` keeps the model's version) or ``rejected``. Only coded and confirmed facts are counted (D-131).
* ``local_code``: the site's own codes (a 病名 code, a JLAC10 or YJ code, a column name, a diagnosis as written), with
  a suggested standard code; a person maps each once, for the whole site.
* ``check_item``: the "please check" list (``sitesetup.messy.Check``) and the answers; ``fix``: the safe fixes made,
  grouped by kind and column.
* ``setting``: box-wide switches (remote help, off by default). ``published``: what the lake last got.

Every write goes through :class:`SetupStore`; the orchestrator's API audits each decision.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from typing import Any

from tb_common.db import ENV, Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS input (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ws TEXT NOT NULL,
  kind TEXT NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL, media TEXT NOT NULL,
  added_by TEXT NOT NULL, at TEXT NOT NULL, roles TEXT NOT NULL DEFAULT '{}', summary TEXT NOT NULL DEFAULT '{}',
  pid TEXT, ref_day TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS fact (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ws TEXT NOT NULL,
  input_id BIGINT NOT NULL, pid TEXT NOT NULL, domain TEXT NOT NULL, term TEXT NOT NULL DEFAULT '',
  code TEXT NOT NULL DEFAULT '', system TEXT NOT NULL DEFAULT '', local_code TEXT NOT NULL DEFAULT '',
  local_system TEXT NOT NULL DEFAULT '', value TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT '',
  day TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, quote TEXT NOT NULL DEFAULT '', at TEXT NOT NULL,
  decided_by TEXT, decided_at TEXT, before TEXT);
CREATE INDEX IF NOT EXISTS fact_ws_pid ON fact (ws, pid);
CREATE TABLE IF NOT EXISTS local_code (ws TEXT NOT NULL, domain TEXT NOT NULL, system TEXT NOT NULL,
  code TEXT NOT NULL, display TEXT NOT NULL DEFAULT '', suggested_system TEXT NOT NULL DEFAULT '',
  suggested_code TEXT NOT NULL DEFAULT '', suggested_display TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '',
  mapped_system TEXT, mapped_code TEXT, mapped_display TEXT, mapped_by TEXT, mapped_at TEXT,
  PRIMARY KEY (ws, domain, system, code));
CREATE TABLE IF NOT EXISTS check_item (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ws TEXT NOT NULL,
  input_id BIGINT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL, column_name TEXT NOT NULL, row_no INTEGER,
  raw TEXT NOT NULL DEFAULT '', suggestion TEXT NOT NULL DEFAULT '', options TEXT NOT NULL DEFAULT '[]',
  answer TEXT, answered_by TEXT, answered_at TEXT, UNIQUE (input_id, key));
CREATE TABLE IF NOT EXISTS fix (input_id BIGINT NOT NULL, kind TEXT NOT NULL, column_name TEXT NOT NULL,
  n INTEGER NOT NULL, examples TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT NOT NULL, set_by TEXT NOT NULL,
  set_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS published (ws TEXT PRIMARY KEY, at TEXT NOT NULL, snapshot TEXT NOT NULL,
  digest TEXT NOT NULL, counts TEXT NOT NULL DEFAULT '{}')
"""
# version 2 (scenario run MAP-01): how sure a suggested code is (0..1), shown beside it
SCHEMA_V2 = "ALTER TABLE local_code ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0"
STATUSES = ("coded", "proposed", "confirmed", "rejected")
_INSERT_FACT = (
    "INSERT INTO fact (ws, input_id, pid, domain, term, code, system, local_code, local_system, value, unit, day, "
    "status, quote, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)
COUNTED = ("coded", "confirmed")
DOMAINS = ("condition", "observation", "medication", "demographic")


class SetupError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class SetupStore:
    def __init__(self, url: str | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), "sitesetup")
        self._db.migrate([SCHEMA, SCHEMA_V2])

    @property
    def db(self) -> Database:
        return self._db

    def close(self) -> None:
        self._db.close()

    def _all(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self._db.fetchdicts(sql, args)

    # ------------------------------------------------------------------ inputs
    def add_input(
        self,
        ws: str,
        kind: str,
        name: str,
        sha256: str,
        path: str,
        media: str,
        by: str,
        at: str,
        roles: dict[str, str] | None = None,
        pid: str | None = None,
        ref_day: str = "",
    ) -> int:
        with self._db.transaction() as tx:
            return int(
                tx.fetchval(
                    "INSERT INTO input (ws, kind, name, sha256, path, media, added_by, at, roles, pid, ref_day) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (
                        ws,
                        kind,
                        name,
                        sha256,
                        path,
                        media,
                        by,
                        at,
                        json.dumps(roles or {}, ensure_ascii=False),
                        pid,
                        ref_day,
                    ),
                )
            )

    def set_input(
        self,
        input_id: int,
        *,
        roles: dict[str, str] | None = None,
        summary: dict[str, Any] | None = None,
        path: str | None = None,
        status: str | None = None,
    ) -> None:
        if roles is not None:
            self._db.execute(
                "UPDATE input SET roles = ? WHERE id = ?", (json.dumps(roles, ensure_ascii=False), input_id)
            )
        if summary is not None:
            self._db.execute(
                "UPDATE input SET summary = ? WHERE id = ?",
                (json.dumps(summary, ensure_ascii=False, default=str), input_id),
            )
        if path is not None:
            self._db.execute("UPDATE input SET path = ? WHERE id = ?", (path, input_id))
        if status is not None:
            self._db.execute("UPDATE input SET status = ? WHERE id = ?", (status, input_id))

    def inputs(self, ws: str, kind: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT * FROM input WHERE ws = ? AND status = 'active'"
            + (" AND kind = ?" if kind else "")
            + " ORDER BY id"
        )
        rows = self._all(sql, (ws, kind) if kind else (ws,))
        for r in rows:
            r["roles"] = json.loads(r["roles"] or "{}")
            r["summary"] = json.loads(r["summary"] or "{}")
        return rows

    def input(self, input_id: int) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM input WHERE id = ?", (input_id,))
        if not rows:
            return None
        r = rows[0]
        r["roles"] = json.loads(r["roles"] or "{}")
        r["summary"] = json.loads(r["summary"] or "{}")
        return r

    def workspaces(self) -> list[str]:
        return [str(r["ws"]) for r in self._all("SELECT DISTINCT ws FROM input ORDER BY ws")]

    # ------------------------------------------------------------------ facts
    def replace_facts(self, ws: str, input_id: int, facts: Iterable[dict[str, Any]], at: str) -> int:
        """The coded facts of a sheet or dump, replaced as a whole when it is read again (with new answers)."""
        rows = list(facts)
        with self._db.transaction() as tx:
            tx.execute("DELETE FROM fact WHERE input_id = ? AND status = 'coded'", (input_id,))
            for f in rows:
                tx.execute(
                    _INSERT_FACT,
                    (
                        ws,
                        input_id,
                        f["pid"],
                        f["domain"],
                        f.get("term", ""),
                        f.get("code", ""),
                        f.get("system", ""),
                        f.get("local_code", ""),
                        f.get("local_system", ""),
                        f.get("value", ""),
                        f.get("unit", ""),
                        f.get("day", ""),
                        f.get("status", "coded"),
                        f.get("quote", ""),
                        at,
                    ),
                )
        return len(rows)

    def add_facts(self, ws: str, input_id: int, facts: Iterable[dict[str, Any]], at: str) -> list[int]:
        out: list[int] = []
        with self._db.transaction() as tx:
            for f in facts:
                out.append(
                    int(
                        tx.fetchval(
                            _INSERT_FACT + " RETURNING id",
                            (
                                ws,
                                input_id,
                                f["pid"],
                                f["domain"],
                                f.get("term", ""),
                                f.get("code", ""),
                                f.get("system", ""),
                                f.get("local_code", ""),
                                f.get("local_system", ""),
                                f.get("value", ""),
                                f.get("unit", ""),
                                f.get("day", ""),
                                f.get("status", "proposed"),
                                f.get("quote", ""),
                                at,
                            ),
                        )
                    )
                )
        return out

    def facts(self, ws: str, status: str | None = None, pid: str | None = None) -> list[dict[str, Any]]:
        sql, args = (
            "SELECT * FROM fact f WHERE ws = ? AND EXISTS (SELECT 1 FROM input i WHERE i.id = f.input_id "
            "AND i.status = 'active')",
            [ws],
        )
        if status:
            sql += " AND status = ?"
            args.append(status)
        if pid:
            sql += " AND pid = ?"
            args.append(pid)
        return self._all(sql + " ORDER BY id", args)

    def fact(self, fid: int) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM fact WHERE id = ?", (fid,))
        return rows[0] if rows else None

    def decide(self, fid: int, status: str, by: str, at: str, changes: dict[str, str] | None = None) -> dict[str, Any]:
        """Confirm, correct (confirm with new values; the model's version is kept in ``before``) or reject one
        fact. A decided fact can be decided again (the latest decision stands; every one is in the audit)."""
        if status not in ("confirmed", "rejected"):
            raise SetupError("SETUP-FACT", "a fact is confirmed or rejected")
        cur = self.fact(fid)
        if cur is None:
            raise SetupError("SETUP-FACT", "no such fact")
        allowed = {"term", "code", "system", "value", "unit", "day"}
        changes = {k: str(v)[:200] for k, v in (changes or {}).items() if k in allowed and str(v) != str(cur[k])}
        before = cur["before"]
        if changes and before is None:
            before = json.dumps({k: cur[k] for k in allowed}, ensure_ascii=False)
        sets = ", ".join(f"{k} = ?" for k in changes)
        self._db.execute(
            f"UPDATE fact SET status = ?, decided_by = ?, decided_at = ?, before = ?{', ' + sets if sets else ''} "
            "WHERE id = ?",
            (status, by, at, before, *changes.values(), fid),
        )
        out = self.fact(fid)
        assert out is not None
        return out

    # ------------------------------------------------------------------ local codes
    def put_local(self, ws: str, domain: str, system: str, code: str, display: str, suggestion: dict[str, str]) -> None:
        self._db.execute(
            "INSERT INTO local_code (ws, domain, system, code, display, suggested_system, suggested_code, "
            "suggested_display, method, confidence) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (ws, domain, system, code) DO UPDATE SET display = excluded.display, "
            "suggested_system = excluded.suggested_system, "
            "suggested_code = excluded.suggested_code, suggested_display = excluded.suggested_display, "
            "method = excluded.method, confidence = excluded.confidence",
            (
                ws,
                domain,
                system,
                code,
                display[:200],
                suggestion.get("system", ""),
                suggestion.get("code", ""),
                suggestion.get("display", "")[:200],
                suggestion.get("method", ""),
                float(suggestion.get("confidence") or 0),
            ),
        )

    def locals(self, ws: str) -> list[dict[str, Any]]:
        """Every local code of the site with how many counted facts use it."""
        return self._all(
            "SELECT l.*, (SELECT count(*) FROM fact f JOIN input i ON i.id = f.input_id WHERE f.ws = l.ws "
            "AND f.domain = l.domain AND f.local_system = l.system AND f.local_code = l.code AND i.status = 'active' "
            "AND f.status IN ('coded', 'confirmed')) AS n FROM local_code l WHERE l.ws = ? "
            "ORDER BY (l.mapped_code IS NOT NULL), l.domain, l.system, l.code",
            (ws,),
        )

    def map_local(
        self, ws: str, domain: str, system: str, code: str, mapped: dict[str, str], by: str, at: str
    ) -> dict[str, Any]:
        rows = self._all(
            "SELECT * FROM local_code WHERE ws = ? AND domain = ? AND system = ? AND code = ?",
            (ws, domain, system, code),
        )
        if not rows:
            raise SetupError("SETUP-CODE", "no such local code")
        if mapped.get("code"):
            self._db.execute(
                "UPDATE local_code SET mapped_system = ?, mapped_code = ?, mapped_display = ?, mapped_by = ?, "
                "mapped_at = ? WHERE ws = ? AND domain = ? AND system = ? AND code = ?",
                (
                    mapped.get("system", ""),
                    mapped["code"],
                    mapped.get("display", "")[:200],
                    by,
                    at,
                    ws,
                    domain,
                    system,
                    code,
                ),
            )
        else:  # mapped to nothing: the code stays in an unknown system (D-130), on purpose; still decided
            self._db.execute(
                "UPDATE local_code SET mapped_system = '', mapped_code = '', mapped_display = '', mapped_by = ?, "
                "mapped_at = ? WHERE ws = ? AND domain = ? AND system = ? AND code = ?",
                (by, at, ws, domain, system, code),
            )
        return self._all(
            "SELECT * FROM local_code WHERE ws = ? AND domain = ? AND system = ? AND code = ?",
            (ws, domain, system, code),
        )[0]

    def mapping(self, ws: str) -> dict[tuple[str, str, str], dict[str, str]]:
        """``(domain, local system, local code) -> {system, code, display}`` of the codes a person mapped."""
        out = {}
        for r in self._all(
            "SELECT * FROM local_code WHERE ws = ? AND mapped_code IS NOT NULL AND mapped_code <> ''", (ws,)
        ):
            out[(r["domain"], r["system"], r["code"])] = {
                "system": r["mapped_system"],
                "code": r["mapped_code"],
                "display": r["mapped_display"] or "",
            }
        return out

    # ------------------------------------------------------------------ checks and fixes
    def put_checks(self, ws: str, input_id: int, checks: Iterable[dict[str, Any]]) -> None:
        """The input's open questions (answered ones are kept with their answers)."""
        rows = list(checks)
        keys = {c["key"] for c in rows}
        with self._db.transaction() as tx:
            have = {r["key"] for r in tx.fetchdicts("SELECT key FROM check_item WHERE input_id = ?", (input_id,))}
            for k in have - keys:
                tx.execute("DELETE FROM check_item WHERE input_id = ? AND key = ? AND answer IS NULL", (input_id, k))
            for c in rows:
                if c["key"] in have:
                    continue
                tx.execute(
                    "INSERT INTO check_item (ws, input_id, key, kind, column_name, row_no, raw, suggestion, options) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        ws,
                        input_id,
                        c["key"],
                        c["kind"],
                        c["column"],
                        c.get("row"),
                        str(c.get("raw", ""))[:120],
                        c.get("suggestion", ""),
                        json.dumps(list(c.get("options") or []), ensure_ascii=False),
                    ),
                )

    def checks(self, ws: str, open_only: bool = False) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT c.* FROM check_item c JOIN input i ON i.id = c.input_id WHERE c.ws = ? AND i.status = 'active'"
            + (" AND c.answer IS NULL" if open_only else "")
            + " ORDER BY c.id",
            (ws,),
        )
        for r in rows:
            r["options"] = json.loads(r["options"] or "[]")
        return rows

    def check(self, cid: int) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM check_item WHERE id = ?", (cid,))
        if not rows:
            return None
        rows[0]["options"] = json.loads(rows[0]["options"] or "[]")
        return rows[0]

    def answer(self, cid: int, answer: str, by: str, at: str) -> None:
        self._db.execute(
            "UPDATE check_item SET answer = ?, answered_by = ?, answered_at = ? WHERE id = ?", (answer, by, at, cid)
        )

    def answers(self, input_id: int) -> dict[str, str]:
        return {
            r["key"]: r["answer"]
            for r in self._all(
                "SELECT key, answer FROM check_item WHERE input_id = ? AND answer IS NOT NULL", (input_id,)
            )
        }

    def put_fixes(self, input_id: int, groups: Iterable[dict[str, Any]]) -> None:
        with self._db.transaction() as tx:
            tx.execute("DELETE FROM fix WHERE input_id = ?", (input_id,))
            for g in groups:
                tx.execute(
                    "INSERT INTO fix (input_id, kind, column_name, n, examples) VALUES (?,?,?,?,?)",
                    (input_id, g["kind"], g["column"], int(g["n"]), json.dumps(g["examples"], ensure_ascii=False)),
                )

    def fixes(self, ws: str) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT x.*, i.name AS input_name, i.kind AS input_kind FROM fix x JOIN input i ON i.id = x.input_id "
            "WHERE i.ws = ? AND i.status = 'active' ORDER BY x.input_id, x.kind, x.column_name",
            (ws,),
        )
        for r in rows:
            r["examples"] = json.loads(r["examples"] or "[]")
        return rows

    # ------------------------------------------------------------------ settings, publishing
    def setting(self, key: str, default: str = "") -> str:
        v = self._db.fetchval("SELECT value FROM setting WHERE key = ?", (key,))
        return default if v is None else str(v)

    def set_setting(self, key: str, value: str, by: str, at: str) -> None:
        self._db.execute(
            "INSERT INTO setting (key, value, set_by, set_at) VALUES (?,?,?,?) ON CONFLICT (key) DO "
            "UPDATE SET value = excluded.value, set_by = excluded.set_by, set_at = excluded.set_at",
            (key, value, by, at),
        )

    def published(self, ws: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM published WHERE ws = ?", (ws,))
        if not rows:
            return None
        rows[0]["counts"] = json.loads(rows[0]["counts"] or "{}")
        return rows[0]

    def set_published(self, ws: str, at: str, snapshot: str, digest: str, counts: dict[str, int]) -> None:
        self._db.execute(
            "INSERT INTO published (ws, at, snapshot, digest, counts) VALUES (?,?,?,?,?) ON CONFLICT "
            "(ws) DO UPDATE SET at = excluded.at, snapshot = excluded.snapshot, digest = excluded.digest, "
            "counts = excluded.counts",
            (ws, at, snapshot, digest, json.dumps(counts)),
        )

    def reset(self, ws: str) -> None:
        """Remove everything of one workspace (the practice site's Reset; never offered for ``main``)."""
        with self._db.transaction() as tx:
            ids = [r["id"] for r in tx.fetchdicts("SELECT id FROM input WHERE ws = ?", (ws,))]
            for i in ids:
                tx.execute("DELETE FROM fix WHERE input_id = ?", (i,))
            for t in ("fact", "check_item", "local_code", "input", "published"):
                tx.execute(f"DELETE FROM {t} WHERE ws = ?", (ws,))
