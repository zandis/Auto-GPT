"""Synthetic paired coded/note evidence. Run with python -m tools.set_d."""

from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

from tools.imperfect_feed import COLUMNS, TABLES, csv_bytes, mrn
from tools.synth_hospital import roundtrip_notes

DEFAULT_COUNTS = {
    "agreeing": 600,
    "note_adds": 400,
    "conflicting": 500,
    "missing": 300,
    "stale": 300,
    "note_only": 300,
}
CRITERIA = (
    ("gout.diagnosis", "diagnosis", ("M10.9", "M1A.9")),
    ("gout.serum-urate", "lab", ("3084-1", "14933-6")),
    ("ra.diagnosis", "diagnosis", ("M05.9", "M06.9")),
    ("ra.mtx-exposure", "drug", ("L04AX03", "L01BA01")),
)
RANK = {"administration": 4, "dispense": 3, "claim": 3, "order": 2, "statement": 1}
WORDS = {
    "en": (
        "confirmed",
        "absent",
        "suspected",
        "rule out",
        "resolved",
        "pending",
        "as needed",
        "refill",
        "not documented",
        "stopped",
    ),
    "ja": ("確認済み", "なし", "疑い", "除外診断中", "軽快", "結果待ち", "必要時", "再処方", "記載なし", "中止"),
    "zh-TW": ("已確認", "無", "疑似", "待排除", "已緩解", "待報告", "需要時使用", "續方", "未記載", "停用"),
}
STATUSES = ("active", "absent", "suspected", "r/o", "resolved", "pending", "prn", "refill", "missing", "stopped")
SUBJECTS = {
    "en": ("gout", "serum urate", "rheumatoid arthritis", "methotrexate"),
    "ja": ("痛風", "血清尿酸", "関節リウマチ", "メトトレキサート"),
    "zh-TW": ("痛風", "血清尿酸", "類風濕性關節炎", "甲氨蝶呤"),
}


def _event(kind: str, code: str, present: bool, anchor: date, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "date": (anchor - timedelta(days=10)).isoformat(),
        "status": "active" if present else "absent",
        "code": code,
        "value": (9.0 if present else 5.0) if kind == "lab" else present,
        "unit": "mg/dL" if kind == "lab" else "",
        "reference_range": [3.0, 6.0] if kind == "lab" else None,
        "days_supply": 90 if kind == "drug" else 0,
        "stop": None,
    }


def _value(e: dict[str, Any], kind: str, anchor: date) -> bool | float | None:
    if e["status"] not in {"active", "absent", "stopped", "no_history"}:
        return None
    if kind == "lab":
        if not e["date"] or e["unit"] not in {"mg/dL", "umol/L"}:
            return None
        if not 0 <= (anchor - date.fromisoformat(e["date"])).days <= 365:
            return None
        return cast(bool | float, e["value"]) >= 7 * (59.48 if e["unit"] == "umol/L" else 1)
    if kind == "drug":
        if e["stop"] and e["stop"] <= anchor.isoformat():
            return False
        start = date.fromisoformat(e["date"])
        return cast(bool | float, e["value"]) and start <= anchor <= start + timedelta(days=e["days_supply"] + 30)
    return cast(bool | float, e["value"])


def _answer(coded: list[dict[str, Any]], notes: list[dict[str, Any]], kind: str, anchor: date) -> str:
    if kind == "diagnosis":
        dates = [e["date"] for e in notes if e["status"] == "active" and e["value"] is True]
        coded = [e for e in coded if not (e["status"] == "no_history" and dates and e["date"] < max(dates))]

    def best(events: list[dict[str, Any]]) -> bool | float | None:
        usable = [e for e in events if _value(e, kind, anchor) is not None]
        usable.sort(key=lambda e: (RANK.get(e["source"], 0) if kind == "drug" else 0, e["date"]), reverse=True)
        return _value(usable[0], kind, anchor) if usable else None

    c, n = best(coded), best(notes)
    if c is not None and n is not None and c != n:
        return "unknown"
    result = c if c is not None else n
    return "unknown" if result is None else "met" if result else "not_met"


def _damage(
    kind: str, cell: str, index: int, base: dict[str, Any], anchor: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    coded = [dict(base)]
    notes = [dict(base, source="statement")]
    damage = "none"
    if cell == "agreeing" and kind == "drug":
        lower = {"administration": "dispense", "dispense": "order", "claim": "order", "order": "statement"}
        coded.append(
            dict(
                base,
                source=lower[base["source"]],
                value=not base["value"],
                status="absent" if base["value"] else "active",
            )
        )
        damage = "contradict lower ranked source"
    if cell == "conflicting":
        notes[0]["value"] = (5.0 if base["value"] == 9.0 else 9.0) if kind == "lab" else not base["value"]
        notes[0]["status"] = "active" if notes[0]["value"] in (True, 9.0) else "absent"
        notes[0]["date"] = anchor.isoformat()
        damage = "contradict note"
    elif cell in {"missing", "note_only", "note_adds"}:
        coded = []
        damage = "remove coded evidence"
        if cell == "missing":
            notes[0]["status"] = "missing"
        elif cell == "note_adds":
            coded = [dict(base, status="pending" if kind == "lab" else "suspected")]
        elif kind == "drug":
            notes[0]["status"] = (base["status"], "prn", "refill")[index % 3]
        elif kind == "diagnosis":
            notes[0]["status"] = (base["status"], "suspected", "r/o")[index % 3]
    elif cell == "stale":
        damage = "age or qualify evidence"
        if kind == "lab":
            variant = index % 5
            if variant == 0:
                coded[0]["date"] = (anchor - timedelta(days=366)).isoformat()
            elif variant == 1:
                coded[0]["status"] = "pending"
            elif variant == 2:
                coded[0]["date"] = None
            elif variant == 3:
                coded[0]["unit"] = "unconvertible"
            else:
                coded[0]["date"] = (anchor - timedelta(days=365)).isoformat()
            notes = [dict(coded[0], source="statement")]
        elif kind == "diagnosis":
            coded[0].update(value=False, status="no_history", date=(anchor - timedelta(days=700)).isoformat())
            notes[0].update(value=True, status="active", date=anchor.isoformat())
            if index % 3 == 0:
                coded[0]["status"] = "resolved"
                notes[0]["status"] = "resolved"
        else:
            variant = index % 5
            coded[0].update(date=(anchor - timedelta(days=120)).isoformat(), days_supply=90)
            if variant == 0:
                coded[0].update(stop=anchor.isoformat(), status="stopped")
            elif variant == 1:
                coded[0]["days_supply"] = 89
            elif variant == 2:
                coded[0]["days_supply"] = 121
            elif variant == 3:
                coded[0]["status"] = "prn"
            notes = [dict(coded[0], source="statement")]
    return coded, notes, damage


def _row(tables: dict[str, list[dict[str, str]]], table: str, **values: object) -> None:
    row = dict.fromkeys(COLUMNS[table], "")
    row.update({k: str(v) if v is not None else "" for k, v in values.items()})
    tables[table].append(row)


def generate(*, seed: int, anchor: date, counts: dict[str, int] | None = None) -> dict[str, Any]:
    counts = DEFAULT_COUNTS if counts is None else counts
    if set(counts) - set(DEFAULT_COUNTS) or any(type(n) is not int or n < 0 for n in counts.values()):
        raise ValueError("Cell counts must be nonnegative integers with known cell names")
    if not sum(counts.values()) or sum(counts.values()) % 4:
        raise ValueError("Pair count must be positive and divisible by four")
    rng = random.Random(seed)
    cells = [cell for cell, n in counts.items() for _ in range(n)]
    rng.shuffle(cells)
    tables: dict[str, list[dict[str, str]]] = {table: [] for table in TABLES}
    pairs: list[dict[str, Any]] = []
    patients: list[dict[str, Any]] = []
    seen: Counter[str | tuple[str, str]] = Counter()
    for i, cell in enumerate(cells):
        patient = mrn(i // 4 + 1)
        language = ("en", "ja", "zh-TW")[i // 4 % 3]
        j = i % 4
        criterion, kind, codes = CRITERIA[j]
        code = codes[seen[criterion] % len(codes)]
        truth = bool(rng.getrandbits(1))
        if cell == "stale" and kind == "diagnosis":
            truth = True
        source = ("administration", "dispense", "claim", "order")[seen[criterion] % 4] if kind == "drug" else kind
        base = _event(kind, code, truth, anchor, source)
        if kind == "lab" and code == "14933-6":
            base.update(unit="umol/L", value=base["value"] * 59.48, reference_range=[178.44, 356.88])
        # Conflicts use one unit so the reversed threshold is unambiguous.
        if cell == "conflicting" and kind == "lab":
            base.update(code="3084-1", unit="mg/dL", value=9.0 if truth else 5.0, reference_range=[3.0, 6.0])
        index = seen[(criterion, cell)]
        coded, notes, damage = _damage(kind, cell, index, base, anchor)
        seen[(criterion, cell)] += 1
        seen[criterion] += 1
        if j == 0:
            _row(tables, "patient", mrn=patient, birth_date="1970-01-01", sex="F")
            _row(tables, "encounter", enc_no=patient, mrn=patient, visit_datetime=anchor.isoformat(), enc_type="OPD")
            patients.append(
                dict(
                    patient=patient,
                    visits=[dict(date=anchor.isoformat(), code="OPD")],
                    allergies=[dict(code="SYNTHETIC-ALLERGEN", status="active", date=anchor.isoformat())],
                )
            )
        for k, e in enumerate(coded):
            key = f"{i}-{k}"
            if kind == "diagnosis":
                _row(
                    tables,
                    "diagnosis",
                    diag_no=key,
                    mrn=patient,
                    enc_no=patient,
                    icd10=e["code"],
                    diag_date=e["date"],
                    recorded_date=e["date"],
                    status=e["status"],
                )
            elif kind == "lab":
                _row(
                    tables,
                    "lab",
                    lab_no=key,
                    mrn=patient,
                    local_code="UA",
                    item_name="Urate",
                    result_value=e["value"],
                    unit=e["unit"],
                    sample_datetime=e["date"],
                )
            else:
                end = e["stop"] or (date.fromisoformat(e["date"]) + timedelta(days=e["days_supply"])).isoformat()
                _row(
                    tables,
                    "medication",
                    rx_no=key,
                    mrn=patient,
                    atc=e["code"],
                    order_date=e["date"],
                    start_date=e["date"],
                    end_date=end,
                    status=e["status"],
                )
        for k, e in enumerate(notes):
            word = WORDS[language][STATUSES.index(e["status"])]
            text = f"{e['date'] or '?'}: {SUBJECTS[language][j]}: {word}."
            if kind == "lab":
                text += f" {e['value']} {e['unit']}."
            if kind == "drug":
                text += f" [{e['date']}; +{e['days_supply']} d; {e['stop'] or '-'}]."
            e["text"] = text
            _row(
                tables,
                "note",
                note_no=f"N{i}-{k}",
                mrn=patient,
                enc_no=patient,
                note_datetime=e["date"],
                note_type="progress",
                text=text,
            )
        pairs.append(
            dict(
                patient=patient,
                criterion=criterion,
                kind=kind,
                language=language,
                cell=cell,
                truth=truth,
                hidden=base,
                damage=damage,
                coded=coded,
                notes=notes,
                evidence=sorted(coded + notes, key=lambda e: e["date"] or "", reverse=True),
                expected=_answer(coded, notes, kind, anchor),
            )
        )
    assert roundtrip_notes(tables["note"]) == {row["note_no"]: row["text"] for row in tables["note"]}
    return dict(seed=seed, anchor=anchor.isoformat(), counts=counts, tables=tables, patients=patients, pairs=pairs)


def _atomic(path: Path, payload: bytes) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".set-d-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write(data: dict[str, Any], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for table, rows in data["tables"].items():
        _atomic(folder / f"{table}.csv", csv_bytes(table, rows))
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic(folder / "gold.json", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--anchor", required=True, type=date.fromisoformat)
    parser.add_argument("--counts", type=json.loads, help="JSON object of pair counts by cell")
    args = parser.parse_args()
    write(generate(seed=args.seed, anchor=args.anchor, counts=args.counts), args.out)


if __name__ == "__main__":
    main()
