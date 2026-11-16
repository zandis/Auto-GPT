"""Sources the data core imports from and syncs with (D-123): REDCap, a PI's spreadsheet, a FHIR bundle.

Each maps the source's own names to TrialBox field names and keys rows by the TrialBox record (the screening number
or the pseudonym). Direct identifiers (names, phone numbers, addresses) are never imported; a chart-number column is
turned into the pseudonym by the site key before anything is stored.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from rc_bridge.link import GROUP_COLUMN, in_group
from tb_common import encoding

from datacore.store import DataError
from datacore.sync import Row

# column headers that are direct identifiers in EN/JA/zh-TW sheets: dropped, and the import says so
IDENTIFIER = re.compile(r"(?i)^(name|patient.?name|full.?name|first.?name|last.?name|kana|phone|tel|mobile|e-?mail|"
                        r"address|postcode|zip|氏名|患者名|名前|カナ|フリガナ|電話|住所|郵便番号|姓名|病人姓名|電話號碼|地址|"
                        r"身分證|身份證|マイナンバー)")  # fmt: skip


@dataclass
class RedcapSource:
    """A REDCap project through its API (the client is made per call; the token stays in the secret store)."""

    client: Callable[[], Any]
    key_field: str = "tb_screening_no"
    field_map: dict[str, str] = field(default_factory=dict)  # REDCap field -> TrialBox field (identity if absent)
    event: str = ""  # longitudinal: the event TrialBox's fields live on
    create: bool = False  # push may create a REDCap record for a TrialBox record REDCap lacks
    dag: str = ""
    name: str = "redcap"
    id_field: str = "record_id"
    pid_field: str = ""  # a field holding TrialBox's pseudonym: the key when the screening number is blank
    refused: list[dict[str, str]] = field(default_factory=list)
    group_bound: bool = False  # RC13-D (D-849): the token is a group user's (read from the last pull)

    def _tb(self, rc_field: str) -> str:
        return self.field_map.get(rc_field, rc_field)

    def fields(self) -> list[str]:
        return [self._tb(f) for f in self.field_map] if self.field_map else []

    def pull(self) -> list[Row]:
        with self.client() as rc:
            meta = rc.metadata()
            self.id_field = str(meta[0]["field_name"])
            wanted = [self.id_field, self.key_field, *([self.pid_field] if self.pid_field else []), *self.field_map]
            rows = rc.records(fields=list(dict.fromkeys(wanted)), dags=bool(self.dag))
        rows, self.group_bound = in_group(rows, self.dag)  # RC13-D (D-849): a group user's token
        keys: dict[str, str] = {}
        for r in rows:  # the key field may live on another event than the data (longitudinal)
            if str(r.get(self.key_field) or "").strip():
                keys[str(r[self.id_field])] = str(r[self.key_field]).strip().upper()
        if self.pid_field:  # second: the pseudonym, only where no screening number was given
            for r in rows:
                rid = str(r.get(self.id_field) or "")
                if rid not in keys and str(r.get(self.pid_field) or "").strip():
                    keys[rid] = str(r[self.pid_field]).strip()
        self.refused = []
        out = []
        merged: dict[str, Row] = {}  # longitudinal, no event configured: one row per record (D-142, review B-03)
        spread: dict[str, dict[str, set[str]]] = {}
        for r in rows:
            rid = str(r.get(self.id_field) or "")
            key = keys.get(rid)
            if not key:
                if rid and not any(x["at"] == f"record {rid}" for x in self.refused):
                    self.refused.append({"at": f"record {rid}", "reason": "no screening number and no pseudonym"})
                continue
            ev = str(r.get("redcap_event_name") or "")
            repeat = str(r.get("redcap_repeat_instrument") or "") or str(r.get("redcap_repeat_instance") or "")
            if self.event and ev and ev != self.event:
                vals = {}
            else:
                vals = {self._tb(f): str(r.get(f) or "") for f in self.field_map if f in r}
            if self.event or not (ev or repeat):
                out.append(Row(key, "", vals, rid))
                continue
            # one row per record x event (or repeat instance): a field lives on one event and comes back blank on
            # every other one. A blank there is never a value: the record's value is its non-blank cell
            row = merged.get(rid)
            if row is None:
                row = merged[rid] = Row(key, "", {}, rid)
                out.append(row)
            for f, v in vals.items():
                row.values.setdefault(f, "")
                if v.strip():
                    spread.setdefault(rid, {}).setdefault(f, set()).add(v)
        for rid, fields in spread.items():
            row = merged[rid]
            for f, seen in fields.items():
                if len(seen) == 1:
                    row.values[f] = next(iter(seen))
                else:  # two events disagree: TrialBox cannot tell which one is meant, so it takes neither
                    del row.values[f]
                    self.refused.append(
                        {"at": f"record {rid}", "reason": f"{f} differs between events: set the REDCap event"}
                    )
        return out

    def _homes(self, rc: Any) -> dict[str, str]:
        """REDCap field -> the event it lives on, for a longitudinal project linked with no event (D-142, review B-03):
        the first event whose forms include the field's form (REDCap refuses a row with no event, or a field on an
        event its form is not designated for). Empty for a classic project or when an event is set."""
        if self.event:
            return {}
        try:
            events = [str(e["unique_event_name"]) for e in rc.events()]
        except Exception:  # a classic project: REDCap answers events for a longitudinal project only
            return {}
        if not events:
            return {}
        try:
            mapping = rc.form_event_mapping()
        except Exception:
            mapping = []
        forms: dict[str, list[str]] = {}
        for m in mapping:
            forms.setdefault(str(m.get("unique_event_name")), []).append(str(m.get("form")))
        home: dict[str, str] = {}
        for m in rc.metadata():
            f, form = str(m["field_name"]), str(m.get("form_name") or "")
            home[f] = next((e for e in events if form in forms.get(e, [])), events[0])
        return home

    def push(self, rows: list[Row]) -> dict[str, str]:
        back = {v: k for k, v in self.field_map.items()}
        out: dict[str, str] = {}
        with self.client() as rc:
            homes = self._homes(rc)

            def split(rid: str, vals: dict[str, str], base: dict[str, str]) -> list[dict[str, str]]:
                if not homes:
                    return [{self.id_field: rid, **base, **vals}]
                by: dict[str, dict[str, str]] = {}
                for f, v in vals.items():
                    by.setdefault(homes.get(f) or next(iter(homes.values())), {})[f] = v
                return [{self.id_field: rid, "redcap_event_name": ev, **base, **v} for ev, v in by.items()]

            upd: list[dict[str, str]] = []
            new: list[tuple[str, list[dict[str, str]]]] = []
            for r in rows:
                vals = {back.get(f, f): v for f, v in r.values.items()}
                base: dict[str, str] = {"redcap_event_name": self.event} if self.event else {}
                if r.source_id:
                    upd += split(r.source_id, vals, base)
                elif self.create:
                    if self.dag and not self.group_bound:  # a group user's import may not carry the column
                        base[GROUP_COLUMN] = self.dag
                    new.append((r.record, split(f"tb-new-{len(new) + 1}", {self.key_field: r.record, **vals}, base)))
            if upd:
                rc.import_records(upd)
                out.update({r.record: r.source_id for r in rows if r.source_id})
            if new:  # rows of one new record (one per event) share its temporary name: REDCap gives it one id
                ids = rc.import_records([x for _rec, part in new for x in part], auto_number=True)
                out.update({rec: rid for (rec, _), rid in zip(new, ids, strict=False)})
        return out


def read_sheet(path: Path) -> list[dict[str, str]]:
    """CSV (UTF-8 or Shift_JIS/Big5 as saved by Excel) or XLSX -> rows of strings."""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True, data_only=True).active
        if ws is None:
            return []
        it = ws.iter_rows(values_only=True)
        head = [str(h or "").strip() for h in next(it, [])]
        rows = []
        for vals in it:
            if not any(v not in (None, "") for v in vals):
                continue
            row = {}
            for h, v in zip(head, vals, strict=False):
                if isinstance(v, datetime):
                    v = v.date().isoformat()
                elif isinstance(v, date):
                    v = v.isoformat()
                row[h] = "" if v is None else str(v).strip()
            rows.append(row)
        return rows
    try:  # D-215: the one detector; a Big5 sheet tried as CP932 first read as mojibake without an error
        text, _ = encoding.decode(path.read_bytes())
    except encoding.EncodingRefused as exc:
        raise DataError("DATA-SHEET", f"the file is not readable UTF-8, Shift_JIS or Big5 text ({exc})") from None
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


@dataclass
class SheetSource:
    """A PI's patient spreadsheet: ``key_column`` holds the screening number, or ``mrn_column`` a chart number that
    ``pseudonymise`` turns into the pseudonym. ``push`` writes TrialBox's fields to ``out_path`` (a CSV the PI opens
    in Excel), next to the PI's own file; the PI's file itself is never rewritten."""

    path: Path
    columns: dict[str, str]  # sheet column -> TrialBox field
    key_column: str = ""
    mrn_column: str = ""
    pseudonymise: Callable[[str], str] | None = None
    out_path: Path | None = None
    name: str = "sheet"
    dropped: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)

    def fields(self) -> list[str]:
        return list(self.columns.values())

    def pull(self) -> list[Row]:
        rows = read_sheet(self.path)
        if not rows:
            return []
        head = list(rows[0])
        self.dropped = [h for h in head if IDENTIFIER.match(h) and h not in (self.key_column, self.mrn_column)]
        bad = [c for c in self.columns if IDENTIFIER.match(c)]
        if self.mrn_column and self.mrn_column in self.columns:
            bad.append(self.mrn_column)  # the chart number is turned into the pseudonym, never stored as a value
        if bad:
            raise DataError("DATA-PHI", f"identifier columns cannot be imported: {', '.join(bad)}")
        if not (self.key_column or self.mrn_column):
            raise DataError("DATA-SHEET", "name the screening-number column or the chart-number column")
        missing = [c for c in [*self.columns, self.key_column, self.mrn_column] if c and c not in head]
        if missing:
            raise DataError("DATA-SHEET", f"columns not in the sheet: {', '.join(missing)}")
        if self.mrn_column and self.pseudonymise is None:
            raise DataError("DATA-SHEET", "a chart-number column needs the site key")
        self.refused = []
        out = []
        for n, r in enumerate(rows, start=2):  # row 1 is the header, as Excel numbers it
            key = r.get(self.key_column, "").strip().upper() if self.key_column else ""
            if not key and self.mrn_column and r.get(self.mrn_column, "").strip():
                key = self.pseudonymise(r[self.mrn_column].strip()) if self.pseudonymise else ""
            if not key:
                self.refused.append({"at": f"row {n}", "reason": "no screening number and no chart number"})
                continue
            out.append(Row(key, "", {f: r.get(c, "") for c, f in self.columns.items()}, key))
        return out

    def push(self, rows: list[Row]) -> dict[str, str]:
        if self.out_path is None:
            return {}
        have: dict[str, dict[str, str]] = {}
        if self.out_path.exists():
            have = {r["record"]: r for r in csv.DictReader(self.out_path.open(encoding="utf-8-sig"))}
        for r in rows:
            have.setdefault(r.record, {"record": r.record}).update(r.values)
        cols = ["record", *sorted({k for v in have.values() for k in v} - {"record"})]
        with self.out_path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for k in sorted(have):
                w.writerow(have[k])
        return {r.record: r.source_id or r.record for r in rows}


@dataclass
class FhirBundleSource:
    """QuestionnaireResponses in a FHIR Bundle (another FHIR system's export). The record is the subject's id
    (a pseudonym); answers are raw codes or values by ``linkId``. ``push`` writes TrialBox's answers to ``out_path``
    as a transaction Bundle."""

    path: Path
    fields_carried: list[str]
    out_path: Path | None = None
    name: str = "fhir"

    def fields(self) -> list[str]:
        return list(self.fields_carried)

    def pull(self) -> list[Row]:
        bundle = json.loads(self.path.read_text(encoding="utf-8"))
        if bundle.get("resourceType") != "Bundle":
            raise DataError("DATA-FHIR", "not a FHIR Bundle")
        out = []
        for e in bundle.get("entry", []):
            qr = e.get("resource") or {}
            if qr.get("resourceType") != "QuestionnaireResponse":
                continue
            ref = str((qr.get("subject") or {}).get("reference") or "")
            key = ref.rsplit("/", maxsplit=1)[-1]
            if not key:
                continue
            vals = {}
            for it in qr.get("item", []):
                if it.get("linkId") in self.fields_carried and it.get("answer"):
                    vals[it["linkId"]] = answer_value(it["answer"][0])
            out.append(Row(key, "", vals, str(qr.get("id") or key)))
        return out

    def push(self, rows: list[Row]) -> dict[str, str]:
        if self.out_path is None:
            return {}
        entries = [{"resource": {"resourceType": "QuestionnaireResponse", "status": "completed",
                                 "subject": {"reference": f"Patient/{r.record}"},
                                 "item": [{"linkId": f, "answer": [{"valueString": v}]} for f, v in r.values.items()]},
                    "request": {"method": "POST", "url": "QuestionnaireResponse"}} for r in rows]  # fmt: skip
        self.out_path.write_text(json.dumps({"resourceType": "Bundle", "type": "transaction", "entry": entries},
                                            ensure_ascii=False, indent=1), encoding="utf-8")  # fmt: skip
        return {r.record: r.source_id or r.record for r in rows}


def answer_value(ans: dict[str, Any]) -> str:
    for k, v in ans.items():
        if k == "valueCoding":
            return str(v.get("code") or "")
        if k.startswith("value"):
            if isinstance(v, bool):
                return "1" if v else "0"
            return str(v)
    return ""
