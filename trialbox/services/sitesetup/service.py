"""The site set-up service the orchestrator's API calls (D-131, D-132, D-135).

One object per box: the ``sitesetup`` store, the protected data folder (``<orchestrator data>/sitesetup``, in every
backup), the lake of each workspace, the local model, OCR, the audit log and the site key.

**Workspaces.** ``main`` is the hospital: its facts go to the box's own lake, beside the nightly feed. Any other
name is a separate site space with its own lake folder under the data folder: the synthetic practice site
(``practice``, loaded and reset in one tap) and the end-to-end check's new site. Nothing of one workspace is ever
read by another.

Every decision (a fact confirmed, corrected or rejected; a code mapped; a check answered; a disagreement resolved;
the remote-help switch) is in the hash-chained audit with who and when. Chart numbers and names never reach the
audit, a log line or the lake: a chart number is turned into the pseudonym on arrival, and chart text is redacted
before it becomes a note in the lake.
"""

from __future__ import annotations

import base64
import contextlib
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tb_common import chartno, dates
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn, sha256_bytes

from sitesetup import charts, intake, mapping, messy, publish
from sitesetup.ocr import Ocr, default_ocr
from sitesetup.store import COUNTED, SetupError, SetupStore

_WS = re.compile(r"^[a-z][a-z0-9]{0,15}$")
SAFE_NAME = re.compile(r"[^\w.\-]+")
KEEP_IN_QUOTES = ("DOB",)  # a quote shown to the coordinator keeps a date of birth; names and numbers are redacted


def ws_ok(ws: str) -> str:
    if not _WS.match(ws or ""):
        raise SetupError("SETUP-WS", "a site space is 1-16 lower-case letters or digits")
    return ws


@dataclass
class SiteSetup:
    store: SetupStore
    root: Path
    main_lake: Any
    llm: Any
    audit: AuditLog
    now: Callable[[], datetime]
    today: Callable[[], date]
    site_key: Callable[[], bytes]
    ocr: Ocr = field(default_factory=default_ocr)
    mrn_regex: str | None = None
    _lakes: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------------ lakes and files
    def lake(self, ws: str) -> Any:
        if ws == "main":
            return self.main_lake
        if ws not in self._lakes:
            from embed_service.embedder import HashEmbedder
            from lake.client import LakeLocal

            self._lakes[ws] = LakeLocal(self.root / ws / "lake", HashEmbedder())
        return self._lakes[ws]

    def _dir(self, ws: str) -> Path:
        d = self.root / ws / "inputs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(self, ws: str, input_id: int, name: str, data: bytes) -> str:
        ext = Path(name).suffix.lower()[:8] or ".bin"
        rel = f"{ws}/inputs/{input_id}{ext}"
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_bytes(data)
        return rel

    def _guard(self) -> Any:
        from guard.guard import Guard

        return Guard(self.mrn_regex)

    def redact(self, text: str, chart_no: str = "", keep: tuple[str, ...] = ()) -> str:
        """Identifiers out of a chart text: the chart number given with it, and what the box's guard recognises
        (names, other numbers, phones, addresses; dates of birth unless kept)."""
        if chart_no:
            for v in {chart_no, messy.half_width(chart_no)}:
                text = text.replace(v, "[MRN]")
        g = self._guard()
        spans = [f for f in g.detect(text) if f.kind not in keep]
        out, pos = [], 0
        for f in spans:
            out.append(text[pos : f.start])
            out.append(f"[{f.kind}]")
            pos = f.end
        out.append(text[pos:])
        return "".join(out)

    def pseudonym(self, chart_no: str) -> str:
        """The chart number written the site's way (``tb_common.chartno``: width, leading zeros, hex case; R-48),
        then hashed with the site key, as the feed's own chart numbers are."""
        key = self.site_key()
        return pid_for_mrn(key, chartno.normalise(None, chart_no))

    # ------------------------------------------------------------------ sheets and dumps
    def add_sheet(self, ws: str, kind: str, name: str, data: bytes, roles: dict[str, str], by: str) -> dict[str, Any]:
        ws_ok(ws)
        if kind not in ("sheet", "dump"):
            raise SetupError("SETUP-KIND", "a sheet or a dump")
        clean_name = SAFE_NAME.sub("_", Path(name).name)[-80:] or f"{kind}.csv"
        intake.read_grid(clean_name, data)  # refuse an unreadable file before anything is stored
        iid = self.store.add_input(ws, kind, clean_name, sha256_bytes(data), "", "", by, self.stamp(), roles)
        self.store.set_input(iid, path=self._save(ws, iid, clean_name, data))
        out = self.reread(iid, by, first=True)
        self.audit.append(
            "setup.input",
            actor=by,
            detail={"ws": ws, "input": iid, "kind": kind, "rows": out["rows"], "dropped": out["dropped"]},
        )
        return out

    def reread(
        self, input_id: int, by: str, roles: dict[str, str] | None = None, first: bool = False
    ) -> dict[str, Any]:
        """Read a sheet again with the answers given so far (and new column roles): its coded facts are replaced
        as a whole, so the result is always a function of the file and the answers."""
        inp = self.store.input(input_id)
        if inp is None or inp["kind"] not in ("sheet", "dump"):
            raise SetupError("SETUP-INPUT", "no such sheet")
        if roles is not None:
            bad = [r for r in roles.values() if r not in messy.ROLES]
            if bad:
                raise SetupError("SETUP-ROLE", f"not a column role: {', '.join(bad)}")
            self.store.set_input(input_id, roles=roles)
            inp["roles"] = roles
        ws = inp["ws"]
        grid, merged = intake.read_grid(inp["name"], (self.root / inp["path"]).read_bytes())
        answers = self.store.answers(input_id)
        cleaned = messy.clean(grid, merged, inp["roles"], answers)
        facts, locs, pids = intake.sheet_facts(cleaned, self.pseudonym)
        for domain, system, code, display in locs:
            self.store.put_local(ws, domain, system, code, display, mapping.suggest(domain, system, code, display))
        at = self.stamp()
        self.store.replace_facts(ws, input_id, facts, at)
        self.store.put_checks(
            ws,
            input_id,
            [
                {
                    "key": c.key,
                    "kind": c.kind,
                    "column": c.column,
                    "row": c.row,
                    "raw": c.raw,
                    "suggestion": c.suggestion,
                    "options": c.options,
                }
                for c in cleaned.checks
            ],
        )
        self.store.put_fixes(input_id, messy.summarise(cleaned.fixes))
        summary = {
            "rows": len(cleaned.records),
            "patients": len(pids),
            "facts": len(facts),
            "fixes": len(cleaned.fixes),
            "checks": len(cleaned.checks),
            "dropped": cleaned.dropped,
            "held": cleaned.held,
            "header_row": cleaned.header_row,
            "roles": cleaned.roles,
        }
        self.store.set_input(input_id, summary=summary)
        if not first:
            self.audit.append("setup.reread", actor=by, detail={"ws": ws, "input": input_id, "rows": summary["rows"]})
        self.publish(ws, by)
        return {"input": input_id, **summary}

    # ------------------------------------------------------------------ charts
    def add_chart(
        self, ws: str, chart_no: str, name: str, data: bytes, by: str, lang: str = "ja", pasted: bool = False
    ) -> dict[str, Any]:
        ws_ok(ws)
        chart_no = messy.half_width(chart_no or "").strip()
        if not chart_no:
            raise SetupError("SETUP-KEY", "give the patient's chart number: it is turned into a code at once")
        if self.mrn_regex and not re.match(self.mrn_regex, chart_no):
            raise SetupError("SETUP-KEY", "this is not a chart number of this hospital")
        try:
            ct = charts.chart_text("pasted.txt" if pasted else name, data, self.ocr)
        except charts.ChartError as exc:
            raise SetupError(exc.code, exc.message) from exc
        pid = self.pseudonym(chart_no)
        clean_name = "pasted.txt" if pasted else (SAFE_NAME.sub("_", Path(name).name)[-80:] or "chart")
        day = messy.parse_date(_first_date(ct.text) or "").iso or self.today().isoformat()
        iid = self.store.add_input(ws, "chart", clean_name, sha256_bytes(data), "", "", by, self.stamp(), {}, pid, day)
        rel = self._save(ws, iid, clean_name, data)
        (self.root / f"{ws}/inputs/{iid}.txt").write_text(ct.text, encoding="utf-8")
        (self.root / f"{ws}/inputs/{iid}.lake.txt").write_text(self.redact(ct.text, chart_no), encoding="utf-8")
        self.store.set_input(iid, path=rel)
        found, dropped = charts.extract(self.llm, ct.text, lang)
        for f in found:
            for k, v in list(f.items()):  # D-146 (J-07): nothing the model wrote back may carry a NUL either
                if isinstance(v, str):
                    f[k] = charts.clean(v)
            f["pid"] = pid
            f["quote"] = self.redact(f["quote"], chart_no, KEEP_IN_QUOTES)
        ids = self.store.add_facts(ws, iid, found, self.stamp())
        summary = {"method": ct.method, "facts": len(ids), "dropped": dropped, "notes": ct.notes, "day": day}
        self.store.set_input(iid, summary=summary)
        self.audit.append(
            "setup.chart",
            actor=by,
            detail={"ws": ws, "input": iid, "pid": pid, "method": ct.method, "proposed": len(ids), "dropped": dropped},
        )
        self.publish(ws, by)
        return {"input": iid, **summary}  # D-273 (PV-6): no pseudonym back for a chart number; the audit keeps it

    # ------------------------------------------------------------------ decisions
    def decide(self, fid: int, action: str, by: str, changes: dict[str, str] | None = None) -> dict[str, Any]:
        """Confirm, correct or reject one proposed fact (one tap on the review list), or undo the decision; audited."""
        f = self.store.fact(fid)
        if f is None:
            raise SetupError("SETUP-FACT", "no such fact")
        if f["status"] == "coded":
            raise SetupError("SETUP-FACT", "a coded fact from the hospital or a sheet is used as is")
        if action == "undo":  # D-178 (review J-14): the toast's Undo; the fact is proposed again
            out = self.store.undecide(fid)
            self.audit.append("setup.fact", actor=by, detail={"ws": f["ws"], "fact": fid, "action": "undo",
                                                               "domain": f["domain"], "pid": f["pid"],
                                                               "from": f["status"]})  # fmt: skip
            self.publish(f["ws"], by)
            return out
        if action == "correct" and changes:
            if f["domain"] == "observation" and "value" in changes:
                num, _ = messy.parse_number(changes["value"])
                if num is None:
                    raise SetupError("SETUP-VALUE", "the value is not a number")
                changes["value"] = f"{num:g}"
            if changes.get("day"):
                iso = messy.parse_date(changes["day"]).iso
                if iso is None:
                    raise SetupError("SETUP-VALUE", "the date cannot be read")
                changes["day"] = iso
            if f["domain"] == "demographic" and f["code"] == "birth_date" and "value" in changes:
                iso = messy.parse_date(changes["value"]).iso
                if iso is None:
                    raise SetupError("SETUP-VALUE", "the date of birth cannot be read")
                changes["value"] = iso
        status = {"confirm": "confirmed", "correct": "confirmed", "reject": "rejected"}.get(action)
        if status is None:
            raise SetupError("SETUP-FACT", "confirm, correct or reject")
        out = self.store.decide(fid, status, by, self.stamp(), changes if action == "correct" else None)
        self.audit.append(
            "setup.fact",
            actor=by,
            detail={
                "ws": f["ws"],
                "fact": fid,
                "action": action,
                "domain": f["domain"],
                "pid": f["pid"],
                "changed": sorted((changes or {}) if action == "correct" else []),
            },
        )
        self.publish(f["ws"], by)
        return out

    def answer(self, cid: int, answer: str, by: str) -> dict[str, Any]:
        c = self.store.check(cid)
        if c is None:
            raise SetupError("SETUP-CHECK", "no such check")
        if answer not in c["options"]:
            raise SetupError("SETUP-CHECK", f"choose one of: {', '.join(c['options'])}")
        self.store.answer(cid, answer, by, self.stamp())
        self.audit.append(
            "setup.check",
            actor=by,
            detail={"ws": c["ws"], "check": cid, "kind": c["kind"], "column": c["column_name"], "answer": answer},
        )
        return self.reread(int(c["input_id"]), by)

    def map_code(self, ws: str, domain: str, system: str, code: str, target: dict[str, str], by: str) -> dict[str, Any]:
        """Map one local code to a standard code once for the whole site (or to nothing: it then stays unknown)."""
        ws_ok(ws)
        t_code = (target.get("code") or "").strip().upper()
        if t_code and not mapping.valid_target(domain, target.get("system", ""), t_code):
            raise SetupError("SETUP-CODE", "not a standard code for this kind of record")
        out = self.store.map_local(ws, domain, system, code, {**target, "code": t_code}, by, self.stamp())
        self.audit.append(
            "setup.map",
            actor=by,
            detail={
                "ws": ws,
                "domain": domain,
                "local": f"{system}|{code}",
                "to": f"{target.get('system', '')}|{t_code}",
            },
        )
        self.publish(ws, by)
        return out

    def resolve(self, ws: str, pid: str, what: str, keep: str, by: str) -> dict[str, Any]:
        """A disagreement between inputs (two dates of birth): the value kept stays, the others are rejected."""
        rows = [
            f
            for f in self.store.facts(ws, pid=pid)
            if f["domain"] == "demographic" and f["code"] == what and f["status"] in COUNTED
        ]
        if keep not in {f["value"] for f in rows}:
            raise SetupError("SETUP-RESOLVE", "keep one of the values the inputs give")
        at = self.stamp()
        n = 0
        for f in rows:
            if f["value"] != keep:
                self.store.decide(int(f["id"]), "rejected", by, at)
                n += 1
        self.audit.append("setup.resolve", actor=by, detail={"ws": ws, "pid": pid, "what": what, "rejected": n})
        self.publish(ws, by)
        return {"pid": pid, "what": what, "kept": keep, "rejected": n}

    # ------------------------------------------------------------------ publishing
    def chart_texts(self, ws: str) -> list[dict[str, Any]]:
        out = []
        for inp in self.store.inputs(ws, "chart"):
            p = self.root / f"{ws}/inputs/{inp['id']}.lake.txt"
            if p.exists() and inp["pid"]:
                out.append({"id": inp["id"], "pid": inp["pid"], "day": inp["ref_day"], "text": p.read_text("utf-8")})
        return out

    def publish(self, ws: str, by: str, force: bool = False) -> dict[str, Any]:
        """The workspace's facts into its lake (a rebuild); skipped when nothing changed since the last time."""
        with self._lock:
            res = publish.resources(self.store.facts(ws), self.store.mapping(ws), self.chart_texts(ws))
            dg = publish.digest(res)
            last = self.store.published(ws)
            lake = self.lake(ws)
            if not force and last is not None and last["digest"] == dg and lake.snapshot():
                return {"snapshot": last["snapshot"], "unchanged": True, "counts": last["counts"]}
            snap = (lake.snapshot() if ws == "main" else None) or self.today().isoformat()
            # D-273 (CR-055, DI-5): the audit event goes first; if it cannot be written, nothing is published
            self.audit.append("setup.publish_begin", actor=by, detail={"ws": ws, "snapshot": snap, "digest": dg[:16]})
            lake.put_site(res)
            if ws == "main":  # the hospital's lake: never rebuilt from a missing or empty feed once it had one (D-271)
                lake.rebuild(snap)
            else:  # a practice site holds the site's own inputs only
                lake.rebuild(snap, allow_empty=True)
            counts = publish.counts(res)
            self.store.set_published(ws, self.stamp(), snap, dg, counts)
            self.audit.append("setup.publish", actor=by, detail={"ws": ws, "snapshot": snap, "counts": counts})
            return {"snapshot": snap, "unchanged": False, "counts": counts}

    # ------------------------------------------------------------------ the practice site and resets
    def reset(self, ws: str, by: str) -> None:
        if ws == "main":
            raise SetupError("SETUP-WS", "the hospital's own data cannot be reset here")
        ws_ok(ws)
        self.store.reset(ws)
        import shutil

        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(self.root / ws)
        self._lakes.pop(ws, None)
        self.audit.append("setup.reset", actor=by, detail={"ws": ws})


def _first_date(text: str) -> str | None:
    for line in text.splitlines():
        for tok in dates.CHART_SPAN.findall(line):  # 和暦, 民國 or Gregorian (D-215)
            if "生年月日" in line or "出生" in line or "birth" in line.lower():
                break
            return str(tok)
    return None


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
