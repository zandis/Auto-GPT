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
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tb_common import chartno, dates, instruments
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
    # T-305b (D-403): decisions on ``main`` within this many seconds of the last publish wait and go as one batch
    # (``TB_SITE_PUBLISH_BATCH_SECONDS``; 0 = every decision publishes, as before)
    publish_batch_seconds: int = 0
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
        grid, merged = intake.read_grid(clean_name, data)  # refuse an unreadable file before anything is stored
        # FIT-U09 (T-629): and a chart-number column that Excel turned into numbers, naming the column
        intake.refuse_chart_column(clean_name, data, messy.clean(grid, merged, roles), self.mrn_regex)
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
        data = (self.root / inp["path"]).read_bytes()
        grid, merged = intake.read_grid(inp["name"], data)
        answers = self.store.answers(input_id)
        if roles is not None:
            bad = [r for r in roles.values() if r not in messy.ROLES]
            if bad:
                raise SetupError("SETUP-ROLE", f"not a column role: {', '.join(bad)}")
            # FIT-U09 (T-629): a column made the chart number must not be one Excel turned into numbers
            intake.refuse_chart_column(inp["name"], data, messy.clean(grid, merged, roles, answers), self.mrn_regex)
            self.store.set_input(input_id, roles=roles)
            inp["roles"] = roles
        ws = inp["ws"]
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
        switches = instruments.switches(self.store.setting(instruments.SETTING))  # T-307: the site's licences
        found, dropped = charts.extract(self.llm, ct.text, lang, switches=switches)
        for f in found:
            for k, v in list(f.items()):  # D-146 (J-07): nothing the model wrote back may carry a NUL either
                if isinstance(v, str):
                    f[k] = charts.clean(v)
            f["pid"] = pid
            f["quote"] = self.redact(f["quote"], chart_no, KEEP_IN_QUOTES)
        ids = self.store.add_facts(ws, iid, found, self.stamp())
        # T-208 (D-346): the input of every fact proposed from this chart names its hidden text
        summary = {"method": ct.method, "facts": len(ids), "dropped": dropped, "notes": ct.notes, "day": day,
                   "hidden_text": ct.hidden_chars}  # fmt: skip
        self.store.set_input(iid, summary=summary)
        self.audit.append(
            "setup.chart",
            actor=by,
            detail={
                "ws": ws,
                "input": iid,
                "pid": pid,
                "method": ct.method,
                "proposed": len(ids),
                "dropped": dropped,
                "hidden_text": ct.hidden_chars,
            },
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

    def _batch_wait(self, last: dict[str, Any] | None) -> int:
        """Seconds until the batch window since the last publish of ``main`` closes (0: it is closed)."""
        if self.publish_batch_seconds <= 0 or last is None:
            return 0
        try:
            at = datetime.fromisoformat(str(last["at"]))
            gone = (self.now() - at).total_seconds()
        except (TypeError, ValueError):
            return 0
        return max(0, int(self.publish_batch_seconds - gone + 0.999))

    def _held_by(self, lake: Any, snap: str | None) -> int:
        """How many running jobs hold ``snap`` (T-305b, D-403); 0 for a lake without holds."""
        holds = getattr(lake, "holds", None)
        if not snap or holds is None:
            return 0
        try:
            return sum(1 for s in holds().values() if s == snap)
        except Exception:  # a lake that cannot say: the rebuild itself refuses a held snapshot (SnapshotHeld)
            return 0

    def flush(self, ws: str = "main", by: str = "batch") -> dict[str, Any]:
        """Apply a waiting batch of ``ws`` when its window has closed and no job holds the snapshot (the scheduler
        every minute, and the orchestrator after each job). Nothing waiting: nothing done."""
        return self.publish(ws, by)

    def publish(self, ws: str, by: str, force: bool = False) -> dict[str, Any]:
        """The workspace's facts into its lake (a rebuild); skipped when nothing changed since the last time.

        T-305b (D-403), the hospital's lake (``main``) is published in batches: a decision inside
        ``publish_batch_seconds`` of the last publish waits (``pending``) and the waiting decisions go together when
        the window closes (:meth:`flush`) or a person presses Publish (``force``). Nothing is published while a
        running job holds the snapshot it would rebuild, forced or not: the job reads its snapshot to the end, and
        the batch follows when it ends. What waits is the difference between the facts and the last publish, so a
        restart loses nothing.

        T-690 (D-472), the hospital's lake rebuilds as a polled job: the publish starts it and, while it runs,
        records a publish in progress (``<data>/main/publishing.json``: the job, the snapshot, the digest and counts
        it carries). Every later call follows that job instead of starting another (``pending``, ``building``) and
        records the publish when the job is done; a failed job is recorded and not started again for the same facts
        until a person presses Publish. No time limit on the rebuild (OD-10). A box with no site facts that never
        published starts no rebuild."""
        with self._lock:
            res = publish.resources(self.store.facts(ws), self.store.mapping(ws), self.chart_texts(ws))
            dg = publish.digest(res)
            lake = self.lake(ws)
            rec = self._record(ws)
            if rec is not None and rec.get("state") == "running":
                followed = self._follow(ws, rec, lake, by, dg)
                if followed is not None:
                    return followed
                rec = self._record(ws)
            last = self.store.published(ws)
            if rec is not None and rec.get("state") == "failed" and rec.get("digest") == dg and not force:
                return _failed(last, rec)
            if not force and last is not None and last["digest"] == dg and lake.snapshot():
                return {"snapshot": last["snapshot"], "unchanged": True, "counts": last["counts"]}
            if ws == "main" and last is None and not any(res.values()):
                # F-01 (T-690): a fresh box with no site facts has nothing to publish; no rebuild of the hospital
                return {"snapshot": None, "unchanged": True, "empty": True, "counts": {}}
            snap = (lake.snapshot() if ws == "main" else None) or self.today().isoformat()
            if ws == "main":
                wait = 0 if force else self._batch_wait(last)
                held = self._held_by(lake, snap)
                if wait or held:
                    return _pending(last, wait, held)
            # D-273 (CR-055, DI-5): the audit event goes first; if it cannot be written, nothing is published
            self.audit.append("setup.publish_begin", actor=by, detail={"ws": ws, "snapshot": snap, "digest": dg[:16]})
            lake.put_site(res)
            counts = publish.counts(res)
            start = getattr(lake, "start_rebuild", None) if ws == "main" else None
            job: dict[str, Any] | None = None
            try:
                if start is not None:  # T-690: the hospital's lake, a polled job (never rebuilt from a missing or
                    job = start(snap)  # empty feed once it had one: D-271)
                elif ws == "main":
                    lake.rebuild(snap)
                else:  # a practice site holds the site's own inputs only
                    lake.rebuild(snap, allow_empty=True)
            except Exception as exc:
                if _building_refusal(exc):
                    # D-462: another rebuild of the snapshot runs (another worker, the night's rebuild, a double
                    # click): never a second writer; this publish waits, "building"
                    self.audit.append("setup.publish_building", actor=by, detail={"ws": ws, "snapshot": snap})
                    return _pending(last, 0, 0, building=True)
                if ws != "main" or not _held_refusal(exc):
                    raise
                # a job pinned the snapshot between the check and the rebuild: the batch waits for it (D-403)
                self.audit.append("setup.publish_deferred", actor=by, detail={"ws": ws, "snapshot": snap})
                return _pending(last, 0, max(1, self._held_by(lake, snap)))
            if job is not None:
                rec = {"state": "running", "job": job.get("job"), "snapshot": snap, "digest": dg, "counts": counts,
                       "at": self.stamp(), "by": by}  # fmt: skip
                if job.get("state") == "running":
                    self._set_record(ws, rec)
                    return {**_pending(last, 0, 0, building=True), "running": True}
                self._set_record(ws, rec)  # an in-process lake answers the job's end at once
                followed = self._follow(ws, rec, lake, by, dg, job)
                if followed is not None:
                    return followed
                rec = self._record(ws)
                last = self.store.published(ws)
                if rec is not None and rec.get("state") == "failed":
                    return _failed(last, rec)
                return _pending(last, 0, max(1, self._held_by(lake, snap)))  # held at the swap: waits for the job
            return self._done(ws, snap, dg, counts, by)

    def _done(self, ws: str, snap: str, dg: str, counts: dict[str, int], by: str) -> dict[str, Any]:
        self.store.set_published(ws, self.stamp(), snap, dg, counts)
        self._set_record(ws, None)
        self.audit.append("setup.publish", actor=by, detail={"ws": ws, "snapshot": snap, "counts": counts})
        return {"snapshot": snap, "unchanged": False, "counts": counts}

    def _follow(
        self, ws: str, rec: dict[str, Any], lake: Any, by: str, dg: str, st: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Follow the publish in progress (T-690, D-472): its answer while it runs or once recorded, or None when the
        caller goes on (the job ended otherwise, or the facts changed since; the record says which)."""
        read = getattr(lake, "rebuild_state", None)
        if st is None:
            if read is None:
                self._set_record(ws, None)
                return None
            try:
                st = read(str(rec["snapshot"]))
            except Exception:  # the lake does not answer now: the next call asks again; nothing is started
                return {**_pending(self.store.published(ws), 0, 0, building=True), "running": True}
        state = st.get("state")
        if st.get("job") != rec.get("job"):
            if state == "running":  # another rebuild of the snapshot runs now; ours ended unseen: wait for it
                return {**_pending(self.store.published(ws), 0, 0, building=True), "running": True}
            self._set_record(ws, None)  # ours was replaced by a later job: publish again
            return None
        if state == "running":
            return {**_pending(self.store.published(ws), 0, 0, building=True), "running": True}
        if state == "done":
            out = self._done(ws, str(rec["snapshot"]), str(rec["digest"]), dict(rec.get("counts") or {}), by)
            return out if rec.get("digest") == dg else None
        if state in ("refused", "failed"):
            detail = str(st.get("detail") or state)[:300]
            self._set_record(ws, {**rec, "state": "failed", "detail": detail})
            self.audit.append("setup.publish_failed", actor=by,
                              detail={"ws": ws, "snapshot": rec["snapshot"], "state": state})  # fmt: skip
            return None
        if state == "busy":  # held at the swap: nothing replaced; the batch waits for the job (D-403, D-462)
            self.audit.append("setup.publish_deferred", actor=by, detail={"ws": ws, "snapshot": rec["snapshot"]})
        self._set_record(ws, None)  # busy, interrupted, unknown: published again on the next call
        return None

    def _record_path(self, ws: str) -> Path:
        return self.root / ws / "publishing.json"

    def _record(self, ws: str) -> dict[str, Any] | None:
        """The publish in progress of ``ws`` (T-690): no patient data, the job id, snapshot, digest and counts."""
        try:
            body = json.loads(self._record_path(ws).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def _set_record(self, ws: str, rec: dict[str, Any] | None) -> None:
        p = self._record_path(ws)
        if rec is None:
            p.unlink(missing_ok=True)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")
        tmp.replace(p)

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


def _pending(last: dict[str, Any] | None, wait: int, held: int, building: bool = False) -> dict[str, Any]:
    """What a publish that waits answers (T-305b, D-403): the last published snapshot and why it waits; ``building``
    when another rebuild of the snapshot is running (D-462)."""
    return {
        "snapshot": last["snapshot"] if last else None,
        "unchanged": False,
        "pending": True,
        "wait_seconds": wait,
        "held_by_jobs": held,
        "building": building,
        "counts": last["counts"] if last else {},
    }


def _failed(last: dict[str, Any] | None, rec: dict[str, Any]) -> dict[str, Any]:
    """What a publish whose rebuild failed answers until the facts change or a person presses Publish (T-690)."""
    return {
        "snapshot": last["snapshot"] if last else None,
        "unchanged": False,
        "pending": False,
        "failed": True,
        "detail": str(rec.get("detail") or ""),
        "counts": last["counts"] if last else {},
    }


def _building_refusal(exc: Exception) -> bool:
    """The lake refused the rebuild because another rebuild of the snapshot runs (D-462; in process, or the 409)."""
    if type(exc).__name__ == "SnapshotBuilding":
        return True
    resp = getattr(exc, "response", None)
    if getattr(resp, "status_code", None) != 409:
        return False
    headers = getattr(resp, "headers", None) or {}
    return headers.get("X-TB-Lake-Busy") == "building" or "already building" in str(getattr(resp, "text", ""))


def _held_refusal(exc: Exception) -> bool:
    """The lake refused the rebuild because a running job holds the snapshot (in process, or the service's 409)."""
    if type(exc).__name__ == "SnapshotHeld":
        return True
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) == 409 and "running job" in str(getattr(resp, "text", ""))


def _first_date(text: str) -> str | None:
    for line in text.splitlines():
        for tok in dates.CHART_SPAN.findall(line):  # 和暦, 民國 or Gregorian (D-215)
            if "生年月日" in line or "出生" in line or "birth" in line.lower():
                break
            return str(tok)
    return None


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
