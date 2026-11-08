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

    def _tb(self, rc_field: str) -> str:
        return self.field_map.get(rc_field, rc_field)

    def fields(self) -> list[str]:
        return [self._tb(f) for f in self.field_map] if self.field_map else []

    def pull(self) -> list[Row]:
        with self.client() as rc:
            meta = rc.metadata()
            self.id_field = str(meta[0]["field_name"])
            wanted = [self.id_field, self.key_field, *self.field_map]
            rows = rc.records(fields=list(dict.fromkeys(wanted)), dags=bool(self.dag))
        keys: dict[str, str] = {}
        for r in rows:  # the key field may live on another event than the data (longitudinal)
            if str(r.get(self.key_field) or "").strip():
                keys[str(r[self.id_field])] = str(r[self.key_field]).strip().upper()
        out = []
        for r in rows:
            if self.dag and str(r.get("redcap_data_access_group") or "") != self.dag:
                continue
            rid = str(r.get(self.id_field) or "")
            key = keys.get(rid)
            if not key:
                continue
            ev = str(r.get("redcap_event_name") or "")
            if self.event and ev and ev != self.event:
                vals = {}
            else:
                vals = {self._tb(f): str(r.get(f) or "") for f in self.field_map if f in r}
            out.append(Row(key, "", vals, rid))
        return out

    def push(self, rows: list[Row]) -> dict[str, str]:
        back = {v: k for k, v in self.field_map.items()}
        upd: list[dict[str, str]] = []
        new: list[tuple[str, dict[str, str]]] = []
        for r in rows:
            vals = {back.get(f, f): v for f, v in r.values.items()}
            base: dict[str, str] = {"redcap_event_name": self.event} if self.event else {}
            if r.source_id:
                upd.append({self.id_field: r.source_id, **base, **vals})
            elif self.create:
                if self.dag:
                    base["redcap_data_access_group"] = self.dag
                new.append((r.record, {self.id_field: f"tb-new-{len(new) + 1}", **base, self.key_field: r.record,
                                       **vals}))  # fmt: skip
        out: dict[str, str] = {}
        with self.client() as rc:
            if upd:
                rc.import_records(upd)
                out.update({r.record: r.source_id for r in rows if r.source_id})
            if new:
                ids = rc.import_records([n[1] for n in new], auto_number=True)
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
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DataError("DATA-SHEET", "the file is not UTF-8, Shift_JIS or Big5 text")
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

    def fields(self) -> list[str]:
        return list(self.columns.values())

    def pull(self) -> list[Row]:
        rows = read_sheet(self.path)
        if not rows:
            return []
        head = list(rows[0])
        self.dropped = [h for h in head if IDENTIFIER.match(h) and h not in (self.key_column, self.mrn_column)]
        bad = [c for c in self.columns if IDENTIFIER.match(c)]
        if bad:
            raise DataError("DATA-PHI", f"identifier columns cannot be imported: {', '.join(bad)}")
        missing = [c for c in [*self.columns, self.key_column or self.mrn_column] if c and c not in head]
        if missing:
            raise DataError("DATA-SHEET", f"columns not in the sheet: {', '.join(missing)}")
        out = []
        for r in rows:
            if self.mrn_column:
                if self.pseudonymise is None:
                    raise DataError("DATA-SHEET", "a chart-number column needs the site key")
                raw = r.get(self.mrn_column, "")
                key = self.pseudonymise(raw) if raw else ""
            else:
                key = r.get(self.key_column, "").upper()
            if not key:
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
