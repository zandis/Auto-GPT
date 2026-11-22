"""Gate 2's small adversarial hospital (review 2026-11-22 §3.5): synthetic people who exist to collide.

Every person here is made up: no name, made-up chart numbers in the synthetic ranges, made-up national identifiers
of a shape no real register issues (a ``Z`` and nine digits), and birth dates that only tell the people apart.
Nothing is read from anywhere; :func:`hospital` builds the rows, the writers put them where a road reads them.

The pairs (the §3.5 table):

* **A, B**: the same visit number and the same order numbers on different days.
* **C, D**: the same record id ``1`` for every record type, from two source systems (``sysA`` and ``sysB``).
* **E, F**: E's chart ``00000123`` arrives as ``123``, in full-width digits and with blanks; F's ``00001230`` holds the
  same digits with a zero in another place. E is one person, F another (site rule ``digits:8``).
* **G**: chart ``30000007`` is corrected to ``30000077`` (a recorded merge, reason ``correction``); a correction of a
  lab then arrives under the old number, and a new lab under the new one.
* **H, I**: chart ``30000009`` (I) is merged into ``30000008`` (H); I's lab, carried over, is then corrected under H.
* **J, K**: the same chart ``40000010`` with different birth dates (same national identifier): must be held.
* **M, N**: the same chart ``40000011`` with different national identifiers (same birth date): must be held.
* **L**: opted out under chart ``50000012``; the chart is merged into ``50000013`` and L appears again under it.

Ground truth travels in the clinical values, never in an identifier: each record carries a marker no other record
carries (a birth date, a visit time, a diagnosis code, a lab value), so a published row says whose record it is
whatever key or pseudonym the box gave it.
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

#: the site's chart-number rule for every road (``tb_common.chartno``): leading zeros are not significant
CHART_RULE = "digits:8"
TYPES = ("Patient", "Encounter", "Condition", "Observation")
#: the canonical CSV hospital's tables (``tests/fixtures/synthetic_patients``): the ones a person fills, and the rest
#: written with their header only so every source reads a whole hospital
COLUMNS: dict[str, list[str]] = {
    "patient": ["mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"],
    "practitioner": ["staff_id", "name", "dept_code"],
    "encounter": ["enc_no", "mrn", "visit_datetime", "dept_code", "staff_id", "enc_type", "updated_at"],
    "diagnosis": ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "updated_at", "deleted"],
    "lab": [
        "lab_no",
        "mrn",
        "local_code",
        "item_name",
        "result_value",
        "unit",
        "sample_datetime",
        "updated_at",
        "deleted",
    ],
    "appointment": ["appt_no", "mrn", "appt_datetime", "duration_min", "staff_id", "dept_code", "status"],
    "claim": [
        "claim_no",
        "mrn",
        "created_date",
        "product_code",
        "apply_type",
        "outcome",
        "approval_start",
        "approval_end",
    ],
    "medication": [
        "rx_no",
        "mrn",
        "nhi_drug_code",
        "atc",
        "drug_name",
        "order_date",
        "start_date",
        "end_date",
        "daily_dose",
        "dose_unit",
        "status",
        "dept_code",
        "updated_at",
    ],
    "note": ["note_no", "mrn", "enc_no", "note_datetime", "note_type", "text", "updated_at"],
    "procedure": ["proc_no", "mrn", "order_code", "proc_name", "proc_date", "updated_at"],
    "report": ["rpt_no", "mrn", "exam_code", "exam_name", "exam_date", "conclusion", "updated_at"],
    "vital": ["vital_no", "mrn", "measure_datetime", "height_cm", "weight_kg", "sbp", "dbp", "updated_at"],
    "registry": ["mrn", "consent_contact", "consent_date"],
}
STAFF = "SYN-DOC-1"
#: diagnosis codes, one per person: the marker of a Condition (all ICD-10 shapes; none is about the person)
DX_CODES = (
    "E11.9",
    "I10",
    "M10.9",
    "K21.9",
    "J45.9",
    "N18.3",
    "E78.5",
    "G43.9",
    "L40.0",
    "M81.0",
    "F32.9",
    "H40.10",
    "K58.9",
    "D50.9",
    "E03.9",
    "J30.9",
)


@dataclass(frozen=True)
class Rec:
    """One source record of one person, as one night sends it."""

    person: str
    table: str  # encounter | diagnosis | lab
    number: str  # the source's own record number
    chart: str  # the chart number as written on this row
    when: str  # YYYY-MM-DD or YYYY-MM-DD HH:MM:SS
    marker: str  # the ground truth: this record and no other carries it
    source: str = "sysA"
    deleted: bool = False
    visit: str = ""  # a diagnosis: its visit's number (the reference a published Condition carries)


@dataclass(frozen=True)
class Person:
    letter: str
    chart: str  # the chart number written the site's way
    birth: str  # the marker of the Patient record
    national: str
    sex: str = "F"
    source: str = "sysA"


@dataclass
class Night:
    """What one night's source holds: patient rows and records (a full night: everything; a delta: the changes)."""

    patients: list[tuple[Person, str]] = field(default_factory=list)  # (person, chart as written on the row)
    records: list[Rec] = field(default_factory=list)


@dataclass
class Story:
    """A scenario: its nights, the merges recorded between them, the opt-outs, and what each person should end with."""

    people: dict[str, Person]
    nights: list[Night]
    merges: dict[int, list[tuple[str, str, str]]] = field(default_factory=dict)  # before night i: (old, new, why)
    optouts: list[str] = field(default_factory=list)  # charts typed into the register before night 2
    held: set[str] = field(default_factory=set)  # letters whose chart must be held (publishes nothing)
    #: (person, type) -> how many records the published stores hold after the last night
    expected: Counter[tuple[str, str]] = field(default_factory=Counter)
    #: markers that must be gone after the last night (deleted at the source, or replaced by a correction)
    gone: set[str] = field(default_factory=set)

    def owner_of(self) -> dict[str, str]:
        """marker -> person letter, for every marker any night sends."""
        out = {p.birth: p.letter for p in self.people.values()}
        for n in self.nights:
            for r in n.records:
                out[r.marker] = r.person
        return out


def _lab_value(i: int, r: int, corrected: bool = False) -> str:
    """A lab result no other record has: person i, record r (a correction adds a half)."""
    return f"{i * 10 + r}.50" if corrected else f"{i * 10 + r}.00"


def people() -> dict[str, Person]:
    rows = [
        ("A", "20000001"),
        ("B", "20000002"),
        ("C", "20000003"),
        ("D", "20000004"),
        ("E", "00000123"),
        ("F", "00001230"),
        ("G", "30000007"),
        ("H", "30000008"),
        ("I", "30000009"),
        ("L", "50000012"),
        ("J", "40000010"),
        ("K", "40000010"),
        ("M", "40000011"),
        ("N", "40000011"),
    ]
    out: dict[str, Person] = {}
    for i, (letter, chart) in enumerate(rows, start=1):
        birth = f"19{40 + i:02d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
        national = f"Z{100000000 + i:09d}"
        out[letter] = Person(
            letter, chart, birth, national, sex="F" if i % 2 else "M", source="sysB" if letter == "D" else "sysA"
        )
    # J and K: one chart, one national identifier, two birth dates; M and N: one chart, one birth date, two
    # national identifiers
    out["K"] = replace(out["K"], national=out["J"].national)
    out["N"] = replace(out["N"], birth=out["M"].birth[:5] + "07-07")
    out["M"] = replace(out["M"], birth=out["N"].birth)
    return out


def _records(
    p: Person, i: int, day: str, numbers: tuple[str, str, str, str], spellings: tuple[str, ...] = ()
) -> list[Rec]:
    """A person's four records: one visit, one diagnosis, two labs."""
    sp = list(spellings) or [p.chart] * 4
    enc, dx, lab1, lab2 = numbers
    return [
        Rec(p.letter, "encounter", enc, sp[0], f"{day} 09:{i:02d}:01", f"{i:02d}:01", p.source),
        Rec(p.letter, "diagnosis", dx, sp[1], day, DX_CODES[i - 1], p.source, visit=enc),
        Rec(p.letter, "lab", lab1, sp[2], f"{day} 10:{i:02d}:00", _lab_value(i, 1), p.source),
        Rec(p.letter, "lab", lab2, sp[3], f"{day} 11:{i:02d}:00", _lab_value(i, 2), p.source),
    ]


def _index(ps: dict[str, Person]) -> dict[str, int]:
    return {letter: i for i, letter in enumerate(ps, start=1)}


def base_night(ps: dict[str, Person]) -> Night:
    """Night 1, a full night: A to I and L, every record once."""
    ix = _index(ps)
    n = Night()
    plan: dict[str, tuple[str, tuple[str, str, str, str], tuple[str, ...]]] = {
        "A": ("2026-09-01", ("V1", "O1", "O1", "O2"), ()),
        "B": ("2026-09-02", ("V1", "O1", "O1", "O2"), ()),
        "C": ("2026-09-03", ("1", "1", "1", "2"), ()),
        "D": ("2026-09-04", ("1", "1", "1", "2"), ()),
        "E": ("2026-09-05", ("7", "7", "7", "8"), ("123", "０００００１２３", " 00000123 ", "0000123")),
        "F": ("2026-09-06", ("7", "7", "7", "8"), ()),
        "G": ("2026-09-07", ("G1", "G1", "G1", "G2"), ()),
        "H": ("2026-09-08", ("H1", "H1", "H1", "H2"), ()),
        "I": ("2026-09-09", ("I1", "I1", "I1", "I2"), ()),
        "L": ("2026-09-10", ("L1", "L1", "L1", "L2"), ()),
    }
    for letter, (day, numbers, spellings) in plan.items():
        p = ps[letter]
        n.patients.append((p, p.chart))
        n.records += _records(p, ix[letter], day, numbers, spellings)
    return n


def _base_expected(ps: dict[str, Person], letters: Iterable[str]) -> Counter[tuple[str, str]]:
    out: Counter[tuple[str, str]] = Counter()
    for letter in letters:
        out[(letter, "Patient")] += 1
        out[(letter, "Encounter")] += 1
        out[(letter, "Condition")] += 1
        out[(letter, "Observation")] += 2
    return out


BASE = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "L")


def one_night_story(letters: Iterable[str] = BASE) -> Story:
    """One full night of the people named (C and D included: the record id ``1`` twice)."""
    ps = people()
    keep = set(letters)
    night = base_night(ps)
    night.patients = [(p, c) for p, c in night.patients if p.letter in keep]
    night.records = [r for r in night.records if r.person in keep]
    return Story(ps, [night], expected=_base_expected(ps, [x for x in BASE if x in keep]))


def conflict_story(pair: tuple[str, str]) -> Story:
    """Night 1 as :func:`base_night`; night 2 the same hospital with the pair added under their one chart. The
    second night must be held whole (the conflict stops the batch), so the stores keep night 1."""
    ps = people()
    ix = _index(ps)
    first = base_night(ps)
    second = Night(list(first.patients), list(first.records))
    for k, letter in enumerate(pair):
        p = ps[letter]
        second.patients.append((p, p.chart))
        second.records += _records(
            p, ix[letter], f"2026-09-{11 + k:02d}", (f"{letter}V", f"{letter}D", f"{letter}1", f"{letter}2")
        )
    return Story(ps, [first, second], held=set(pair), expected=_base_expected(ps, BASE))


def corrections_story() -> Story:
    """Night 1 full; then G's chart is corrected, I is merged into H, L opts out and is merged into a new chart;
    night 2 is a delta: G's lab corrected under the old chart and a new lab under the new one, I's lab corrected
    under H, a new lab of L under the new chart, A's diagnosis deleted at the source."""
    ps = people()
    ix = _index(ps)
    first = base_night(ps)
    g_new, l_new = "30000077", "50000013"
    second = Night()
    g, h, i_, l_ = ps["G"], ps["H"], ps["I"], ps["L"]
    second.records = [
        Rec("G", "lab", "G2", g.chart, "2026-09-07 11:07:00", _lab_value(ix["G"], 2, corrected=True)),
        Rec("G", "lab", "G3", g_new, "2026-09-20 10:07:00", _lab_value(ix["G"], 3)),
        Rec("I", "lab", "I1", h.chart, "2026-09-09 10:09:00", _lab_value(ix["I"], 1, corrected=True)),
        Rec("L", "lab", "L3", l_new, "2026-09-20 10:10:00", _lab_value(ix["L"], 3)),
        Rec("A", "diagnosis", "O1", ps["A"].chart, "2026-09-01", DX_CODES[ix["A"] - 1], deleted=True),
    ]
    expected = _base_expected(ps, BASE)
    expected[("G", "Observation")] += 1
    expected[("L", "Observation")] += 1
    expected[("A", "Condition")] -= 1
    gone = {_lab_value(ix["G"], 2), _lab_value(ix["I"], 1), DX_CODES[ix["A"] - 1]}
    # the Patient records of the merged charts: the survivor holds the person (I under H: one person from now on)
    expected[("I", "Patient")] = 0
    return Story(
        ps,
        [first, second],
        merges={1: [(g.chart, g_new, "correction"), (i_.chart, h.chart, "merge"), (l_.chart, l_new, "new chart")]},
        optouts=[l_.chart],
        expected=expected,
        gone=gone,
    )


# ---------------------------------------------------------------------------------------------- orders
ORDERS = ("as_written", "reversed", "interleaved")


def ordered(night: Night, order: str) -> Night:
    """The night's rows in one of three orders: as written, reversed, or interleaved by person (one record of each
    person in turn)."""
    if order == "as_written":
        return night
    if order == "reversed":
        return Night(night.patients[::-1], night.records[::-1])
    if order != "interleaved":
        raise ValueError(order)
    by: dict[str, list[Rec]] = {}
    for r in night.records:
        by.setdefault(r.person, []).append(r)
    out: list[Rec] = []
    while any(by.values()):
        for letter in sorted(by, reverse=True):
            if by[letter]:
                out.append(by[letter].pop(0))
    pats = sorted(night.patients, key=lambda pc: pc[0].letter, reverse=True)
    return Night(pats, out)


# ---------------------------------------------------------------------------------------------- writers
def table_rows(night: Night, ps: dict[str, Person], *, delta_at: str = "") -> dict[str, list[dict[str, str]]]:
    """The night as the canonical CSV hospital's tables."""
    rows: dict[str, list[dict[str, str]]] = {t: [] for t in COLUMNS}
    rows["practitioner"].append({"staff_id": STAFF, "name": "SYN-DOC", "dept_code": "MED"})
    for p, chart in night.patients:
        rows["patient"].append(
            {
                "mrn": chart,
                "name": "",
                "id_no": p.national,
                "birth_date": p.birth,
                "sex": p.sex,
                "death_date": "",
                "phone": "",
            }
        )
    for r in night.records:
        if r.table == "encounter":
            rows["encounter"].append(
                {
                    "enc_no": r.number,
                    "mrn": r.chart,
                    "visit_datetime": r.when,
                    "dept_code": "MED",
                    "staff_id": STAFF,
                    "enc_type": "OPD",
                    "updated_at": delta_at,
                }
            )
        elif r.table == "diagnosis":
            rows["diagnosis"].append(
                {
                    "diag_no": r.number,
                    "enc_no": r.visit,
                    "mrn": r.chart,
                    "icd10": r.marker,
                    "diag_date": r.when,
                    "recorded_date": r.when,
                    "status": "A",
                    "updated_at": delta_at,
                    "deleted": "1" if r.deleted else "",
                }
            )
        else:
            rows["lab"].append(
                {
                    "lab_no": r.number,
                    "mrn": r.chart,
                    "local_code": "UA",
                    "item_name": "Urate",
                    "result_value": r.marker,
                    "unit": "mg/dL",
                    "sample_datetime": r.when,
                    "updated_at": delta_at,
                    "deleted": "1" if r.deleted else "",
                }
            )
    return rows


def write_csv(out: Path, rows: dict[str, list[dict[str, str]]]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for table, cols in COLUMNS.items():
        with (out / f"{table}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows.get(table, []):
                w.writerow({c: r.get(c, "") for c in cols})
    return out


def write_sqlite(path: Path, rows: dict[str, list[dict[str, str]]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        for table, cols in COLUMNS.items():
            con.execute(f'CREATE TABLE "{table}" ({", ".join(f"{c} TEXT" for c in cols)})')
            con.executemany(
                f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in cols)})',
                [tuple(r.get(c, "") for c in cols) for r in rows.get(table, [])],
            )
        con.commit()
    finally:
        con.close()
    return f"sqlite:///{path}"


LOINC_URATE = "3084-1"


def bulk_resources(night: Night, sources: Iterable[str], story: Story | None = None) -> dict[str, list[dict[str, Any]]]:
    """The night as FHIR Bulk Data exports, one per source system: ``{source: [resource, ...]}``. Each system keys
    its own records (C's and D's records are both ``1``); a Patient's id is its chart as the system writes it."""
    want = set(sources)
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in sorted(want)}
    # A server's ids are unique per type within that server: where two of a system's people share a source number
    # (A and B's visit "V1", E and F's "7"), the number stays in the identifier and the second gets an id of its
    # own. Across systems ids repeat freely (C's and D's "1").
    owners: dict[tuple[str, str, str], list[str]] = {}
    for r in [x for n in (story.nights if story else []) for x in n.records] + night.records:
        owners.setdefault((r.source, r.table, r.number), [])
        if r.person not in owners[(r.source, r.table, r.number)]:
            owners[(r.source, r.table, r.number)].append(r.person)

    def rid(r: Rec) -> str:
        first = sorted(owners.get((r.source, r.table, r.number), [r.person]))[0]
        return r.number if r.person == first else f"{r.number}-{r.person}"

    for p, chart in night.patients:
        if p.source not in want:
            continue
        out[p.source].append(
            {
                "resourceType": "Patient",
                "id": chart,
                "birthDate": p.birth,
                "gender": "female" if p.sex == "F" else "male",
                "identifier": [{"system": "urn:synthetic:national-id", "value": p.national}],
            }
        )
    for r in night.records:
        if r.source not in want or r.deleted:
            continue
        subject = {"reference": f"Patient/{r.chart}"}
        ident = [{"system": f"urn:synthetic:{r.source}:{r.table}", "value": r.number}]
        if r.table == "encounter":
            res: dict[str, Any] = {
                "resourceType": "Encounter",
                "id": rid(r),
                "identifier": ident,
                "status": "finished",
                "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
                "subject": subject,
                "period": {"start": r.when.replace(" ", "T") + "+08:00"},
            }
        elif r.table == "diagnosis":
            res = {
                "resourceType": "Condition",
                "id": rid(r),
                "identifier": ident,
                "subject": subject,
                **(
                    {"encounter": {"reference": f"Encounter/{rid(replace(r, table='encounter', number=r.visit))}"}}
                    if r.visit
                    else {}
                ),
                "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": r.marker}]},
                "onsetDateTime": r.when,
                "recordedDate": r.when,
            }
        else:
            res = {
                "resourceType": "Observation",
                "id": rid(r),
                "identifier": ident,
                "status": "final",
                "subject": subject,
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "laboratory",
                            }
                        ]
                    }
                ],
                "code": {"coding": [{"system": "http://loinc.org", "code": LOINC_URATE}]},
                "effectiveDateTime": r.when.replace(" ", "T") + "+08:00",
                "valueQuantity": {
                    "value": float(r.marker),
                    "unit": "mg/dL",
                    "system": "http://unitsofmeasure.org",
                    "code": "mg/dL",
                },
            }
        out[r.source].append(res)
    return out


def bulk_id(r: Rec, story: Story) -> str:
    """The id :func:`bulk_resources` gave ``r`` in its export (the deleted Bundle names the same id)."""
    users = sorted(
        {
            x.person
            for n in story.nights
            for x in n.records
            if (x.source, x.table, x.number) == (r.source, r.table, r.number)
        }
        | {r.person}
    )
    return r.number if r.person == users[0] else f"{r.number}-{r.person}"


def write_bulk(out: Path, by_source: dict[str, list[dict[str, Any]]]) -> Path:
    """One export directory holding every system's files (``<system>-<Type>.ndjson``), as a site that pulls two
    systems' exports into one folder would."""
    out.mkdir(parents=True, exist_ok=True)
    for source, resources in by_source.items():
        by_type: dict[str, list[dict[str, Any]]] = {}
        for r in resources:
            by_type.setdefault(r["resourceType"], []).append(r)
        for rtype, rs in by_type.items():
            with (out / f"{source}-{rtype}.ndjson").open("w", encoding="utf-8") as fh:
                for r in rs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


# ---------------------------------------------------------------------------------------------- the nightly's people
def generated_story(n_people: int, seed: int) -> Story:
    """The bench's larger version: ``n_people`` generated people in generated collision groups (shared record
    numbers, shared visit numbers on other days, chart spellings), one full night. Every marker is still unique."""
    rnd = random.Random(seed)
    ps: dict[str, Person] = {}
    night = Night()
    expected: Counter[tuple[str, str]] = Counter()
    numbers_pool = [str(k) for k in range(1, max(4, n_people // 8))]
    for i in range(1, n_people + 1):
        letter = f"P{i:04d}"
        chart = f"{i:08d}"
        born = (date(1930, 1, 1) + timedelta(days=7 * i)).isoformat()
        p = Person(
            letter,
            chart,
            born,
            f"Z{300000000 + i:09d}",
            sex="F" if i % 2 else "M",
            source="sysA" if rnd.random() < 0.6 else "sysB",
        )
        ps[letter] = p
        spelled = [chart, chart.lstrip("0") or "0", chart.translate(_TO_FULL), f" {chart} "]
        night.patients.append((p, chart))
        day = f"2026-{1 + i % 9:02d}-{1 + rnd.randrange(27):02d}"
        nums = [rnd.choice(numbers_pool) for _ in range(3)]
        night.records += [
            Rec(
                letter,
                "encounter",
                nums[0],
                rnd.choice(spelled),
                f"{day} 10:{i // 60 % 60:02d}:{i % 60:02d}",
                f"{i // 60 % 60:02d}:{i % 60:02d}",
                p.source,
            ),
            Rec(letter, "lab", nums[1], rnd.choice(spelled), f"{day} 10:00:00", f"{i}.25", p.source),
            Rec(letter, "lab", nums[1] + "b", rnd.choice(spelled), f"{day} 11:00:00", f"{i}.75", p.source),
        ]
        expected[(letter, "Patient")] += 1
        expected[(letter, "Encounter")] += 1
        expected[(letter, "Observation")] += 2
    rnd.shuffle(night.records)
    return Story(ps, [night], expected=expected)


_TO_FULL = {ord(c): ord(c) + 0xFEE0 for c in "0123456789"}


def iter_markers(story: Story) -> Iterator[str]:
    yield from story.owner_of()
