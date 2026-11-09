"""The offline reference data pack (TB-PLAN-04, D-140): public registry and terminology data the box reads with no
outbound access.

**Format** (``trialbox-refdata/1``). A pack is a directory ``trialbox-refdata-<YYYYMMDD>/`` (shipped as one ``.tar``
inside the signed update bundle, payload kind ``refdata``)::

    manifest.json        format, pack_id, data_as_of, created_at, sample, and one entry per source:
                         id, name, kind (ctgov | trial | term), url, downloaded_at, download_sha256, records,
                         licence, licence_url, terms, attribution, refresh, distribution (ship | site-fetch),
                         files [{path, sha256, bytes, records}]
    NOTICE.md            the attribution and licence text of every source, generated from the manifest
    <source>/<file>.jsonl.gz   one JSON object per line:
        ctgov:  {"nct_id", "study": <ClinicalTrials.gov API v2 study record, unchanged>}
        trial:  {"registry", "trial_id", "title", "status", "phase", "sponsor", "conditions": [], "countries": [],
                 "inclusion", "exclusion", "start", "end", "updated", "codes": [], "record": {<source row>}}
        term:   {"system", "code", "display", "extra": {}}

:func:`verify` checks every file's size, sha256 and record count against the manifest. The update bundle's Ed25519
signature covers the tar, so the manifest itself is authentic when it arrives through ``apply_update``.

**Store**. :class:`RefStore` loads a pack into the schema ``refdata`` of the trial database (D-126), so the box's
backup carries it. A pack replaces the rows of its own sources in one transaction; parts a hospital loads itself
(``distribution: site-fetch``, e.g. UMIN-CTR, whose terms forbid redistribution) live beside the vendor's pack and a
vendor update does not touch them. :meth:`RefStore.ctgov_search` answers what ``TB_CTGOV_MODE=live`` answers: by NCT
id, by condition, by status and by country (Japan or Taiwan sites); it returns the full API v2 record, which
``criteria_compiler.ctgov.to_study`` turns into the eligibility text the criteria are drafted from.

    python -m tb_common.refdata verify PACK            # a directory or a .tar
    python -m tb_common.refdata load PACK [--by NAME]  # into TB_DB_URL's schema refdata
    python -m tb_common.refdata status
    python -m tb_common.refdata notice PACK            # print NOTICE.md from the manifest
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "trialbox-refdata/1"
KINDS = ("ctgov", "trial", "term")
REQUIRED = ("id", "name", "kind", "url", "downloaded_at", "download_sha256", "records", "licence", "terms",
            "attribution", "distribution", "files")  # fmt: skip
PACK_ID = re.compile(r"^trialbox-refdata-\d{8}(-[a-z0-9-]+)?$")
SCHEMA = "refdata"
TRIAL_COLS = ("registry", "trial_id", "title", "status", "conditions", "countries", "record", "source_id")

DDL = """
CREATE TABLE IF NOT EXISTS pack (pack_id TEXT PRIMARY KEY, data_as_of TEXT NOT NULL, origin TEXT NOT NULL,
  sample BOOLEAN NOT NULL DEFAULT FALSE, manifest JSONB NOT NULL, loaded_at TEXT NOT NULL, loaded_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source (source_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL, distribution TEXT NOT NULL, records BIGINT NOT NULL, url TEXT NOT NULL,
  downloaded_at TEXT NOT NULL, licence TEXT NOT NULL, attribution TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ctgov_study (nct_id TEXT PRIMARY KEY, title TEXT NOT NULL, overall_status TEXT NOT NULL,
  conditions TEXT NOT NULL, countries TEXT NOT NULL, last_update TEXT NOT NULL, study JSONB NOT NULL,
  source_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ctgov_study_status ON ctgov_study (overall_status);
CREATE TABLE IF NOT EXISTS trial (registry TEXT NOT NULL, trial_id TEXT NOT NULL, title TEXT NOT NULL,
  status TEXT NOT NULL, conditions TEXT NOT NULL, countries TEXT NOT NULL, record JSONB NOT NULL,
  source_id TEXT NOT NULL, PRIMARY KEY (registry, trial_id));
CREATE TABLE IF NOT EXISTS term (system TEXT NOT NULL, code TEXT NOT NULL, display TEXT NOT NULL,
  extra JSONB NOT NULL, source_id TEXT NOT NULL, PRIMARY KEY (system, code))
"""


class PackError(ValueError):
    """The pack is malformed, or a file does not match the manifest."""


# ------------------------------------------------------------------------------------------------ writing a pack
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl_gz(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Deterministic gzip (no name, mtime 0), so the same rows give the same sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        for r in rows:
            gz.write(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
            n += 1
    return n


def file_entry(pack: Path, rel: str, records: int) -> dict[str, Any]:
    p = pack / rel
    return {"path": rel, "sha256": sha256_file(p), "bytes": p.stat().st_size, "records": records}


def write_manifest(pack: Path, data_as_of: str, sources: list[dict[str, Any]], sample: bool = False) -> dict[str, Any]:
    m = {
        "format": FORMAT,
        "pack_id": pack.name,
        "data_as_of": data_as_of,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sample": sample,
        "sources": sources,
    }
    check_manifest(m)
    (pack / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (pack / "NOTICE.md").write_text(notice(m), encoding="utf-8")
    return m


def notice(m: dict[str, Any]) -> str:
    """The pack's attribution page: what each source is, where it came from, its licence and its terms."""
    out = [f"# {m['pack_id']}: sources, licences and attribution", "",
           f"Data as of {m['data_as_of']}." + (" SAMPLE pack for tests; not for use." if m.get("sample") else ""),
           ""]  # fmt: skip
    for s in m["sources"]:
        out += [
            f"## {s['name']} (`{s['id']}`)",
            "",
            f"* Source: {s['url']}",
            f"* Downloaded: {s['downloaded_at']}; {s['records']:,} records; sha256 of the download "
            f"`{s['download_sha256']}`",
            f"* Licence: {s['licence']}" + (f" ({s['licence_url']})" if s.get("licence_url") else ""),
            f"* Terms: {s['terms']}",
            f"* Attribution: {s['attribution']}",
            "",
        ]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ reading a pack
def check_manifest(m: dict[str, Any]) -> None:
    if m.get("format") != FORMAT:
        raise PackError(f"not a {FORMAT} manifest (format {m.get('format')!r})")
    if not PACK_ID.match(str(m.get("pack_id", ""))):
        raise PackError(f"bad pack id {m.get('pack_id')!r} (trialbox-refdata-YYYYMMDD)")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(m.get("data_as_of", ""))):
        raise PackError("data_as_of must be YYYY-MM-DD")
    ids = set()
    for s in m.get("sources") or []:
        missing = [k for k in REQUIRED if s.get(k) in (None, "")]
        if missing:
            raise PackError(f"source {s.get('id')!r}: missing {', '.join(missing)}")
        if s["kind"] not in KINDS:
            raise PackError(f"source {s['id']}: kind {s['kind']!r} is not one of {', '.join(KINDS)}")
        if s["distribution"] not in ("ship", "site-fetch"):
            raise PackError(f"source {s['id']}: distribution must be ship or site-fetch")
        if s["id"] in ids:
            raise PackError(f"source {s['id']} twice")
        ids.add(s["id"])
        if sum(int(f["records"]) for f in s["files"]) != int(s["records"]):
            raise PackError(f"source {s['id']}: the files' records do not add up to {s['records']}")
    if not ids:
        raise PackError("the pack has no source")


@contextmanager
def opened(path: Path) -> Iterator[Path]:
    """A pack directory as is, or a ``.tar`` unpacked into a temporary directory (members checked first)."""
    if path.is_dir():
        yield path
        return
    tmp = Path(tempfile.mkdtemp(prefix="tb-refdata-"))
    try:
        with tarfile.open(path, "r:*") as tf:
            for mem in tf.getmembers():
                name = Path(mem.name)
                if name.is_absolute() or ".." in name.parts or not (mem.isfile() or mem.isdir()):
                    raise PackError(f"unsafe member in {path.name}: {mem.name}")
            tf.extractall(tmp, filter="data")
        tops = [p for p in tmp.iterdir() if p.is_dir()]
        if len(tops) != 1:
            raise PackError(f"{path.name}: expected one top directory trialbox-refdata-<date>/")
        yield tops[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_manifest(pack: Path) -> dict[str, Any]:
    try:
        m: dict[str, Any] = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"{pack}: no readable manifest.json ({exc})") from exc
    check_manifest(m)
    if m["pack_id"] != pack.name:
        raise PackError(f"the directory {pack.name} does not match the pack id {m['pack_id']}")
    return m


def rows(pack: Path, rel: str) -> Iterator[dict[str, Any]]:
    with gzip.open(pack / rel, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def verify(pack: Path) -> dict[str, Any]:
    """Every file present, of its size and sha256, with its record count. Returns the manifest."""
    m = read_manifest(pack)
    for s in m["sources"]:
        for f in s["files"]:
            p = pack / f["path"]
            if Path(f["path"]).is_absolute() or ".." in Path(f["path"]).parts or not p.is_file():
                raise PackError(f"{s['id']}: file {f['path']} is missing")
            if p.stat().st_size != int(f["bytes"]) or sha256_file(p) != f["sha256"]:
                raise PackError(f"{s['id']}: {f['path']} does not match its sha256 (a damaged or changed pack)")
            n = sum(1 for _ in rows(pack, f["path"]))
            if n != int(f["records"]):
                raise PackError(f"{s['id']}: {f['path']} has {n} records, the manifest says {f['records']}")
    return m


def pack_tar(pack: Path, out: Path) -> Path:
    """The pack directory as one deterministic tar (sorted names, no owners, mtime 0)."""
    out.parent.mkdir(parents=True, exist_ok=True)

    def norm(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        ti.mtime = 0
        return ti

    with tarfile.open(out, "w") as tf:
        for p in [pack, *sorted(pack.rglob("*"))]:
            tf.add(p, arcname=p.relative_to(pack.parent).as_posix(), recursive=False, filter=norm)
    return out


# ------------------------------------------------------------------------------------------------ the store
def _bar(values: Iterable[str]) -> str:
    """``|a|b|`` lower case: a column searched with LIKE for whole values (countries) or parts (conditions)."""
    vals = [v.strip().lower() for v in values if v and v.strip()]
    return "|" + "|".join(vals) + "|" if vals else ""


def ctgov_row(rec: dict[str, Any], source_id: str) -> tuple[str, ...]:
    study = rec["study"]
    ps = study.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    status = ps.get("statusModule") or {}
    locs = (ps.get("contactsLocationsModule") or {}).get("locations") or []
    nct = str(rec.get("nct_id") or ident.get("nctId") or "")
    if not nct.startswith("NCT"):
        raise PackError(f"a ClinicalTrials.gov record without an NCT id: {nct!r}")
    conds = list((ps.get("conditionsModule") or {}).get("conditions") or [])
    conds += list((ps.get("conditionsModule") or {}).get("keywords") or [])
    return (
        nct,
        str(ident.get("briefTitle") or ident.get("officialTitle") or nct),
        str(status.get("overallStatus") or "").upper(),
        _bar(conds),
        _bar(str(x.get("country") or "") for x in locs),
        str((status.get("lastUpdatePostDateStruct") or {}).get("date") or ""),
        json.dumps(study, ensure_ascii=False),
        source_id,
    )


@dataclass(frozen=True)
class LoadResult:
    pack_id: str
    data_as_of: str
    counts: dict[str, int]


class RefStore:
    """The ``refdata`` schema of the trial database."""

    def __init__(self, url: str | None = None) -> None:
        from tb_common.db import ENV, Database

        self.db = Database.connect(url or os.environ.get(ENV), SCHEMA)
        self.db.migrate([DDL])

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> RefStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def load(self, pack: Path, by: str = "operator", origin: str | None = None) -> LoadResult:
        """Verify, then replace the rows of the pack's sources in one transaction."""
        m = verify(pack)
        origin = origin or ("site" if all(s["distribution"] == "site-fetch" for s in m["sources"]) else "vendor")
        counts: dict[str, int] = {}
        with self.db.transaction() as tx:
            for s in m["sources"]:
                sid = s["id"]
                for table in ("ctgov_study", "trial", "term"):
                    tx.execute(f"DELETE FROM {table} WHERE source_id = ?", (sid,))
                tx.execute("DELETE FROM source WHERE source_id = ?", (sid,))
                n = 0
                for f in s["files"]:
                    recs = rows(pack, f["path"])
                    if s["kind"] == "ctgov":
                        n += tx.copy_rows("ctgov_study", ("nct_id", "title", "overall_status", "conditions",
                                                          "countries", "last_update", "study", "source_id"),
                                          (ctgov_row(r, sid) for r in recs))  # fmt: skip
                    elif s["kind"] == "trial":
                        n += tx.copy_rows(
                            "trial",
                            TRIAL_COLS,
                            ((str(r["registry"]), str(r["trial_id"]), str(r.get("title") or ""),
                              str(r.get("status") or ""), _bar(r.get("conditions") or []),
                              _bar(r.get("countries") or []), json.dumps(r, ensure_ascii=False), sid)
                             for r in recs),
                        )  # fmt: skip
                    else:
                        n += tx.copy_rows(
                            "term",
                            ("system", "code", "display", "extra", "source_id"),
                            ((str(r["system"]), str(r["code"]), str(r.get("display") or ""),
                              json.dumps(r.get("extra") or {}, ensure_ascii=False), sid) for r in recs),
                        )  # fmt: skip
                tx.execute(
                    "INSERT INTO source (source_id, pack_id, name, kind, distribution, records, url, downloaded_at, "
                    "licence, attribution) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sid, m["pack_id"], s["name"], s["kind"], s["distribution"], n, s["url"], s["downloaded_at"],
                     s["licence"], s["attribution"]),
                )  # fmt: skip
                counts[sid] = n
            tx.execute("DELETE FROM pack WHERE pack_id = ?", (m["pack_id"],))
            tx.execute(
                "INSERT INTO pack (pack_id, data_as_of, origin, sample, manifest, loaded_at, loaded_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (m["pack_id"], m["data_as_of"], origin, bool(m.get("sample")), json.dumps(m, ensure_ascii=False),
                 datetime.now(UTC).isoformat(timespec="seconds"), by),
            )  # fmt: skip
            tx.execute("DELETE FROM pack WHERE pack_id NOT IN (SELECT DISTINCT pack_id FROM source)")  # replaced
        return LoadResult(m["pack_id"], m["data_as_of"], counts)

    # -------------------------------------------------------------------- queries
    def ctgov_study(self, nct_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT study FROM ctgov_study WHERE nct_id = ?", (nct_id.strip().upper(),))
        return _json(row[0]) if row else None

    def ctgov_search(
        self,
        condition: str = "",
        locations: Iterable[str] = (),
        status: str | None = "RECRUITING",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Full API v2 records: condition (part of a condition or keyword, any case), any of the countries, the
        overall status; newest update first."""
        where, args = [], []
        if condition.strip():
            where.append("(conditions LIKE ? OR lower(title) LIKE ?)")
            like = f"%{_esc(condition.strip().lower())}%"
            args += [like, like]
        locs = [c.strip().lower() for c in locations if c.strip()]
        if locs:
            where.append("(" + " OR ".join("countries LIKE ?" for _ in locs) + ")")
            args += [f"%|{_esc(c)}|%" for c in locs]
        if status:
            where.append("overall_status = ?")
            args.append(status.upper())
        sql = "SELECT study FROM ctgov_study" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY last_update DESC, nct_id LIMIT ?"
        return [_json(r[0]) for r in self.db.fetchall(sql, (*args, int(limit)))]

    def trials(self, registry: str = "", condition: str = "", limit: int = 50) -> list[dict[str, Any]]:
        where, args = [], []
        if registry:
            where.append("registry = ?")
            args.append(registry)
        if condition.strip():
            where.append("(conditions LIKE ? OR lower(title) LIKE ?)")
            like = f"%{_esc(condition.strip().lower())}%"
            args += [like, like]
        sql = "SELECT record FROM trial" + (" WHERE " + " AND ".join(where) if where else "")
        return [_json(r[0]) for r in self.db.fetchall(sql + " ORDER BY trial_id LIMIT ?", (*args, int(limit)))]

    def term(self, system: str, code: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT display, extra FROM term WHERE system = ? AND code = ?", (system, code))
        return {"system": system, "code": code, "display": row[0], "extra": _json(row[1])} if row else None

    def status(self) -> dict[str, Any] | None:
        """What the admin page shows: the vendor pack's date ("data as of"), every source with its records and
        licence, and the parts the hospital loaded itself. None when nothing is loaded."""
        packs = self.db.fetchdicts("SELECT pack_id, data_as_of, origin, sample, loaded_at, loaded_by FROM pack "
                                   "ORDER BY loaded_at DESC, data_as_of DESC")  # fmt: skip
        if not packs:
            return None
        srcs = self.db.fetchdicts("SELECT source_id, pack_id, name, kind, distribution, records, downloaded_at, "
                                  "licence, attribution FROM source ORDER BY source_id")  # fmt: skip
        vendor = next((p for p in packs if p["origin"] == "vendor"), packs[0])
        return {
            "pack_id": vendor["pack_id"],
            "data_as_of": vendor["data_as_of"],
            "loaded_at": vendor["loaded_at"],
            "sample": bool(vendor["sample"]),
            "packs": packs,
            "sources": srcs,
        }

    def notices(self) -> list[dict[str, Any]]:
        """Every loaded source as its manifest states it (licence, terms, attribution): the NOTICE page."""
        out = []
        for (m,) in self.db.fetchall("SELECT manifest FROM pack ORDER BY origin DESC, pack_id"):
            man = _json(m)
            for s in man.get("sources") or []:
                out.append({k: s.get(k, "") for k in ("id", "name", "url", "downloaded_at", "records", "licence",
                                                      "licence_url", "terms", "attribution", "distribution")}
                           | {"pack_id": man.get("pack_id", "")})  # fmt: skip
        return out


def notices_or_empty(url: str | None = None) -> list[dict[str, Any]]:
    try:
        with RefStore(url) as st:
            return st.notices()
    except Exception:
        return []


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str | bytes) else v


def status_or_none(url: str | None = None) -> dict[str, Any] | None:
    """:meth:`RefStore.status`, or None when the database is not configured or not reachable (a page never fails
    because of it)."""
    try:
        with RefStore(url) as st:
            return st.status()
    except Exception:
        return None


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tb_common.refdata", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "load", "notice"):
        p = sub.add_parser(name)
        p.add_argument("pack", type=Path)
        if name == "load":
            p.add_argument("--by", default="operator")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status":
            st = status_or_none()
            print(json.dumps(st, ensure_ascii=False, indent=1, default=str) if st else "no reference data loaded")
            return 0
        with opened(a.pack) as pack:
            if a.cmd == "verify":
                m = verify(pack)
                print(f"OK {m['pack_id']}: data as of {m['data_as_of']}, "
                      + ", ".join(f"{s['id']} {s['records']}" for s in m["sources"]))  # fmt: skip
            elif a.cmd == "notice":
                print(notice(read_manifest(pack)))
            else:
                with RefStore() as store:
                    res = store.load(pack, by=a.by)
                print(f"loaded {res.pack_id} (data as of {res.data_as_of}): "
                      + ", ".join(f"{k} {v}" for k, v in res.counts.items()))  # fmt: skip
    except (PackError, OSError, tarfile.TarError) as exc:
        print(f"refdata: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
