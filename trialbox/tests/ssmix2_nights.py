"""Two nights of an SS-MIX2 storage: what a full rebuild holds against what a delta night leaves (D-1252, D-1257).

``full``: night 2's storage read whole into an empty lake. ``delta``: night 1's lake, then night 2's window merged
over it. The full lake is never seeded with night 1's rows (review of #1189): a record night 2 neither sends nor
tombstones is in ``delta`` and not in ``full``, and the comparison fails.

The lake is keyed by the ids the adapter itself gives (deep review of #1238, H3): ``Mapper.row_id`` of the JP site
mapping for a live row, ``Mapper.tombstones`` for a deleted one. It is merged as ``ndjson.write_snapshot`` merges a
night: live rows over the lake; a tombstone removes an id the night did not send. While the adapter's id is made of
the key column alone, two patients' records with one number are ONE lake row here, as they are in the box (D-1253,
pull request #1192, makes the id per patient; this harness follows whatever ``row_id`` does). What the two functions
return is shown as ``<mrn>/<key>`` of the row each lake id holds.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapter.mapping.engine import Mapper, Mapping
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
#: the delta column of each table in the JP site mapping (jp_core/ssmix2_site.yaml, through tw_core/demo_his.yaml)
DELTA = {
    "diagnosis": "recorded_date",
    "medication": "order_date",
    "lab": "sample_datetime",
    "encounter": "visit_datetime",
    "note": "note_datetime",
}
KEY = {"diagnosis": "diag_no", "medication": "rx_no", "lab": "lab_no", "encounter": "enc_no", "note": "note_no"}
D1, D2 = "20261110", "20261117"  # night 1 writes on D1, night 2 on D2
SINCE = "2026-11-16"
Lake = dict[str, dict[str, Any]]
_MAPPING = Path(__file__).resolve().parents[1] / "services/adapter/mapping/jp_core/ssmix2_site.yaml"
_MAPPER: list[Mapper] = []


def lake_ids(table: str, row: dict[str, Any]) -> list[str]:
    """The lake ids of one source row, as the adapter gives them: ``<resource type>/<id>``."""
    if not _MAPPER:
        _MAPPER.append(Mapper(Mapping.load(_MAPPING), b"k" * 32, "s"))
    return [f"{typ}/{rid}" for typ, rid in _MAPPER[0].tombstones(table, iter([row]))]
Reader = Callable[[Path], Ssmix2Source]


def reader(root: Path) -> Ssmix2Source:
    return Ssmix2Source(root, licensed=EMPTY, today="20261231")


def night(src: Ssmix2Source, table: str, since: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    live = list(src.rows(table, table, DELTA[table], since))
    dead = list(src.deleted_rows(table, table, DELTA[table], since))
    return live, dead


def apply(lake: Lake, table: str, live: list[dict[str, Any]], dead: list[dict[str, Any]]) -> None:
    """One night merged into ``lake`` (keyed by the adapter's ids)."""
    sent = set()
    for row in live:
        for rid in lake_ids(table, row):
            lake[rid] = row
            sent.add(rid)
    for row in dead:
        for rid in lake_ids(table, row):
            if rid not in sent:
                lake.pop(rid, None)


def shown(lake: Lake, table: str) -> Lake:
    """The lake by ``<mrn>/<key>`` of the row each id holds."""
    return {f"{row['mrn']}/{row[KEY[table]]}": row for row in lake.values()}


def two_nights(
    tmp_path: Path,
    table: str,
    night1: Callable[[kit.Storage], None],
    night2: Callable[[kit.Storage], None],
    *,
    read1: Reader = reader,
    read2: Reader = reader,
    since: str = SINCE,
) -> tuple[Lake, Lake]:
    """``(full, delta)`` after night 2; ``read1`` / ``read2`` build each night's reader (its licensed tables)."""
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True, exist_ok=True)
    night1(st)
    delta: Lake = {}
    apply(delta, table, *night(read1(st.root), table, None))
    night2(st)
    full: Lake = {}
    apply(full, table, *night(read2(st.root), table, None))
    apply(delta, table, *night(read2(st.root), table, since))
    return shown(full, table), shown(delta, table)


def rename_to_past(path: Path) -> None:
    """The guideline's procedure for a new version (構築ガイドライン 3.1.4 (2) ⑥ 1)): the earlier file becomes flag 2."""
    path.rename(path.with_name(path.name[:-1] + "2"))


def rx(st: kit.Storage, number: str, day: str, stamp: str, lines: list[tuple[str, str, str]], *, orc5: str = "IP",
       flag: str = "1", typ: str = "OMP-01", patient: str = kit.P1, placer: str | None = None,
       ordered: str | None = None) -> Path:  # fmt: skip
    """One OMP-01 / OMP-02 order file: ``lines`` are ``(ORC-1, Rp, drug code)``; ORC-2 is ``placer`` (the file's
    number when not given), ORC-9 ``ordered`` (D1 09:00 when not given: an old clinical date on every night)."""
    segs = [kit._msh(f"{day}090000", "RDE^O11^RDE_O11", number), kit._pid(patient)]
    for orc1, rp, drug in lines:
        segs += [f"ORC|{orc1}|{number if placer is None else placer}||{rp}|{orc5}||||{ordered or D1 + '0900'}",
                 "|".join(["RXE", "", f"{drug}^x^HOT9", "1", "", "TAB"] + [""] * 26),
                 f"TQ1|1||U01&1日1回&99XYZ||||{D1}|"]  # fmt: skip
    return kit._write(st, patient, day, typ, number, stamp, segs, flag=flag)


def given(st: kit.Storage, number: str, day: str, stamp: str, drug: str, *, typ: str = "OMP-11",
          patient: str = kit.P1) -> Path:  # fmt: skip
    """One OMP-11 / OMP-12 administration (RAS^O17) of ``drug`` for order ``number``, filed under ``day``."""
    segs = [kit._msh(f"{day}100000", "RAS^O17^RAS_O17", "A" + number), kit._pid(patient),
            f"ORC|RE|{number}||1|CM||||{day}0900", f"RXA|0|1|{day}1000|{day}1000|{drug}^x^HOT9|2|TAB"]  # fmt: skip
    return kit._write(st, patient, day, typ, number, stamp, segs)


def lab(st: kit.Storage, number: str, day: str, stamp: str, results: list[tuple[str, str, str]], *, dept: str = "01",
        flag: str = "1", patient: str = kit.P1, placer: str | None = None) -> Path:  # fmt: skip
    """One OML-11 file: ``results`` are ``(OBX-21 result id, value, OBX-11 status)``, each its own test code so no
    two are one test; OBR-2 / OBR-3 are ``placer`` (the file's number when not given)."""
    order = number if placer is None else placer
    segs = [kit._msh(f"{day}090000", "OUL^R22^OUL_R22", "L"), kit._pid(patient), f"SPM|1|||||||||||||||||{day}0800",
            f"OBR|1|{order}|{order}||||{day}0800"]  # fmt: skip
    for n, (rid, value, status) in enumerate(results, 1):
        obx = ["OBX", str(n), "NM", f"3D01000000192720{n}^T{n}^JC10", "", value, "%", "", "", "", "", status, "", "",
               f"{day}0800"] + [""] * 7  # fmt: skip
        obx[21] = rid
        segs.append("|".join(obx))
    return kit._write(st, patient, day, "OML-11", number, stamp, segs, flag=flag, dept=dept)


def prb(
    no: str, *, action: str = "AD", code: str = "", name: str = "肺炎", outcome: str = "", when: str = "", **fields: str
) -> str:
    """One PRB (as ``kit._prb`` lays it out) with diagnosis number ``no``; ``fields`` are ``f<n>=value``."""
    f = ["PRB", action, when or f"{D1}090000", f"{code or '9999000' + no[-1]}^{name}^MDCDX2", no] + [""] * 14
    f[10], f[14] = "J189^^I10", outcome
    for k, v in fields.items():
        f[int(k[1:])] = v
    return "|".join(f)


def snapshot(st: kit.Storage, stamp: str, prbs: list[str], *, patient: str = kit.P1, pid: str | None = None,
             flag: str = "1", day: str = "-") -> Path:  # fmt: skip
    """One PPR-01 snapshot (PPR^ZD1, "ALL9") of ``patient``; ``pid`` writes another id in PID-3."""
    segs = [kit._msh(f"{stamp[:14]}", "PPR^ZD1^PPR_ZD1", "P"), kit._pid(pid or patient), *prbs]
    return kit._write(st, patient, day, "PPR-01", "ALL9", stamp, segs, flag=flag)
