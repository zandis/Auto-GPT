"""Compose TrialGPT patient notes from a CGRD-format database, locally.

The note is what TrialGPT reads in place of the cohort summaries: age and sex at the index date, diagnoses with dates,
latest labs, body measures, current and recent medications, procedures, report conclusions and the most recent
clinical notes (verbatim, zh-TW allowed). Identity columns are never read; patients are addressed by a pseudonym
(HMAC of the chart number with a site key that never leaves the box). Nothing here talks to the network.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import os
import secrets
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from trialgpt_local.config import settings

HERE = Path(__file__).resolve().parent


def load_mapping(path: Path | None = None) -> dict[str, Any]:
    p = path or HERE / "mapping.default.yaml"
    m = dict(yaml.safe_load(p.read_text(encoding="utf-8")))
    names = Path(m["icd10_names"])
    m["_icd_path"] = names if names.is_absolute() else p.parent / names
    return m


def site_key() -> bytes:
    """Pseudonymisation key: ``TG_SITE_KEY`` or a random key created once (mode 0600) in the data dir."""
    if os.environ.get("TG_SITE_KEY"):
        return os.environ["TG_SITE_KEY"].encode()
    p = settings().data_dir / "cgrd" / ".site_key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        p.chmod(0o600)
    return p.read_bytes()


def pseudonym(mrn: str) -> str:
    return "P" + hmac.new(site_key(), mrn.encode(), hashlib.sha256).hexdigest()[:11]


def _d(v: Any) -> date | None:
    if v in (None, ""):
        return None
    s = str(v)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    return None


def _unit(u: Any) -> str:
    """UCUM annotations like ``{count}`` are noise in a note."""
    return "" if u in (None, "") or (str(u).startswith("{") and str(u).endswith("}")) else str(u)


@dataclass
class Source:
    """A CGRD-format database: an SQLite file or any SQLAlchemy URL (``postgresql://``, ``mssql+pyodbc://``, ...)."""

    url: str
    mapping: dict[str, Any]

    BATCH = 500  # chart numbers per IN (...): below SQLite's and SQL Server's (2100) parameter limits

    def rows(self, kind: str, mrns: list[str] | None = None) -> list[dict[str, Any]]:
        spec = self.mapping["tables"][kind]
        cols = {k: v for k, v in spec.items() if k != "table"}
        select = ", ".join(f'"{c}" AS "{k}"' for k, c in cols.items())
        sql = f'SELECT {select} FROM "{spec["table"]}"'
        if mrns is None:
            return self._query(sql, [])
        out: list[dict[str, Any]] = []
        for i in range(0, len(mrns), self.BATCH):
            chunk = list(mrns[i : i + self.BATCH])
            out += self._query(sql + f' WHERE "{spec["mrn"]}" IN ({", ".join("?" for _ in chunk)})', chunk)
        return out

    def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        if self.url.endswith((".sqlite", ".db")) or self.url.startswith("sqlite:"):
            path = self.url.removeprefix("sqlite:///")
            con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)  # read only, any OS
            con.row_factory = sqlite3.Row
            try:
                return [dict(r) for r in con.execute(sql, params)]
            finally:
                con.close()
        from sqlalchemy import create_engine, text  # optional dependency for real CGRD databases

        bind = {f"p{i}": v for i, v in enumerate(params)}
        q = sql
        for i in range(len(params)):
            q = q.replace("?", f":p{i}", 1)
        with create_engine(self.url).connect() as con:
            return [dict(r._mapping) for r in con.execute(text(q), bind)]

    def mrns(self) -> list[str]:
        return sorted({str(r["mrn"]) for r in self.rows("patient")})


def icd_names(mapping: dict[str, Any]) -> dict[str, str]:
    p = mapping["_icd_path"]
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fh:
        return {r["code"]: r.get("display") or r.get("display_zh") or "" for r in csv.DictReader(fh)}


def compose_notes(src: Source, mrns: list[str], index_date: date) -> dict[str, str]:
    """mrn -> English/zh-TW patient note as of ``index_date`` (only data on or before it)."""
    m = src.mapping
    win = index_date - timedelta(days=int(m.get("window_days", 365)))
    names = icd_names(m)
    by: dict[str, dict[str, list[dict[str, Any]]]] = {x: defaultdict(list) for x in m["tables"]}
    for kind in m["tables"]:
        for r in src.rows(kind, mrns):
            by[kind][str(r["mrn"])].append(r)
    notes = {}
    for mrn in mrns:
        pat = (by["patient"].get(mrn) or [{}])[0]
        bd = _d(pat.get("birth_date"))
        age = (index_date.year - bd.year - ((index_date.month, index_date.day) < (bd.month, bd.day))) if bd else None
        sex = m.get("sex_values", {}).get(str(pat.get("sex")), str(pat.get("sex") or "unknown sex"))
        parts = [f"A {age}-year-old {sex} patient." if age is not None else f"A {sex} patient of unknown age."]
        if _d(pat.get("death_date")) and _d(pat.get("death_date")) <= index_date:  # type: ignore[operator]
            parts.append("The patient is deceased.")
        dx: dict[str, date] = {}
        for r in sorted(by["diagnosis"][mrn], key=lambda r: str(r.get("date"))):
            d = _d(r.get("date"))
            if d and d <= index_date and str(r.get("status", "")).lower() not in ("refuted", "entered-in-error"):
                dx.setdefault(str(r["code"]), d)
        if dx:
            parts.append(
                "Diagnoses: "
                + "; ".join(
                    f"{names.get(c, c)} ({c}, since {d.isoformat()})" for c, d in sorted(dx.items(), key=lambda x: x[1])
                )
                + "."
            )
        labs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in by["lab"][mrn]:
            d = _d(r.get("date"))
            if d and win <= d <= index_date:
                labs[str(r["name"])].append(r)
        if labs:
            items = []
            for name, rs in sorted(labs.items()):
                rs.sort(key=lambda r: str(r.get("date")), reverse=True)
                vals = ", ".join(
                    f"{r['value']} {_unit(r.get('unit'))}".strip() + f" on {_d(r['date'])}"
                    for r in rs[: int(m.get("max_labs_per_item", 2))]
                )
                items.append(f"{name} {vals}")
            parts.append("Laboratory results: " + "; ".join(items) + ".")
        vit = sorted(
            (r for r in by["vital"][mrn] if (_d(r.get("date")) or date.max) <= index_date),
            key=lambda r: str(r.get("date")),
            reverse=True,
        )
        if vit:
            v = vit[0]
            bits = []
            try:
                h, w = float(v.get("height_cm") or 0), float(v.get("weight_kg") or 0)
                if h and w:
                    bits.append(f"height {h:g} cm, weight {w:g} kg, BMI {w / (h / 100) ** 2:.1f} kg/m2")
            except ValueError:
                pass
            if v.get("sbp") and v.get("dbp"):
                bits.append(f"blood pressure {v['sbp']}/{v['dbp']} mmHg")
            if bits:
                parts.append(f"Latest measurements ({_d(v['date'])}): " + ", ".join(bits) + ".")
        courses: dict[tuple[str, str], list[list[date]]] = defaultdict(list)  # refills -> courses (gap <= 30 days)
        for r in sorted(by["medication"][mrn], key=lambda r: str(r.get("start") or r.get("order_date"))):
            start = _d(r.get("start")) or _d(r.get("order_date"))
            if not start or start > index_date:
                continue
            end = _d(r.get("end")) or start
            k = (str(r["name"]), f"{r.get('dose') or ''} {_unit(r.get('unit'))}".strip())
            cs = courses[k]
            if cs and (start - cs[-1][1]).days <= 30:
                cs[-1][1] = max(cs[-1][1], end)
            else:
                cs.append([start, end])
        meds_now, meds_past = [], []
        for (name, dose), cs in sorted(courses.items()):
            for start, end in cs:
                if end < win:
                    continue
                if (index_date - end).days <= 30:
                    meds_now.append(f"{name} {dose} (since {start})")
                else:
                    meds_past.append(f"{name} {dose} ({start} to {end})")
        if meds_now:
            parts.append("Current medications: " + "; ".join(meds_now) + ".")
        if meds_past:
            parts.append("Medications in the past year: " + "; ".join(meds_past) + ".")
        procs = [
            f"{r['name']} on {_d(r['date'])}"
            for r in by["procedure"][mrn]
            if (_d(r.get("date")) or date.max) <= index_date
        ]
        if procs:
            parts.append("Procedures: " + "; ".join(sorted(procs)) + ".")
        for r in sorted(by["report"][mrn], key=lambda r: str(r.get("date"))):
            if (_d(r.get("date")) or date.max) <= index_date and r.get("text"):
                parts.append(f"{r['name']} ({_d(r['date'])}): {str(r['text']).strip()}")
        recent = sorted(
            (r for r in by["note"][mrn] if (_d(r.get("date")) or date.max) <= index_date),
            key=lambda r: str(r.get("date")),
            reverse=True,
        )[: int(m.get("max_notes", 3))]
        for r in reversed(recent):
            parts.append(f"Clinical note ({r.get('type') or 'note'}, {_d(r['date'])}): {str(r['text']).strip()}")
        notes[mrn] = "\n".join(parts)
    return notes
