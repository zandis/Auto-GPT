"""D-1253: the rule a store's lake ids were made under, recorded with the store, and never mixed.

A lake id of a record that belongs to a patient is made from the source's number **and** the patient (rule 2,
``adapter.mapping.engine.patient_resource_id``); before D-1253 it was made from the number alone (rule 1), and two
patients sharing a number were one record. Every id of a patient's record changed once with rule 2. A store that
keeps such ids and was written under rule 1 would hold ids no rule-2 night gives again: it is never added to.

* **Where the rule is kept.** Each NDJSON snapshot carries :data:`SNAPSHOT_RECORD` (written by
  ``adapter.ndjson.write_snapshot``); a snapshot without it was written under rule 1. Each store of the trial
  database that keeps lake ids (:data:`STORES`) has a ``tb_id_rule`` table (:data:`DDL`, a migration of its own):
  a row with :data:`RULE` says its ids are rule 2.
* **When a store is stamped.** :func:`ensure` runs in the store's own write transaction, before it writes lake ids:
  a store that already says :data:`RULE` goes on; one that holds no lake ids yet is stamped and goes on; one that
  holds lake ids and does not say :data:`RULE` is refused with :class:`IdRuleError`, naming the store and the
  runbook step. Nothing is written to it.
* **The night's check.** The adapter refuses a night, before it reads or writes anything, when the lake's snapshots
  or a store it can read (:func:`probe`) are of another rule, or when that cannot be read
  (``adapter.pipeline.check_id_rule``). The adapter's role reads only its own schemas (D-378): the vector store, the
  patient twin and the candidate pool are caught at their own first write after the night, not before it, so a
  night can complete while those three still hold old ids; their first write refuses, so no store is ever written
  under two rules. A store or snapshot of a newer rule (a later release's) is refused with "update the box".
* **Readers.** No lake reader opens a snapshot whose NDJSON is not this rule (``lake.store.Lake.db_path``).
* **EDC keeps the rule per study** (``edc.store``): a rule-1 study whose decided, signed or sent values cite lake rows
  is frozen on every write path; its records stay. The one place old ids stay on a box, by design.
* Old data stays in place. A full ingest from the source into empty storage uses the current rule.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RULE = 2
SNAPSHOT_RECORD = "id_rule.json"
RUNBOOK = "docs/runbook/05-updates-backup-restore-secrets.md, Lake ids per patient (D-1253)"
# Shared with the console catalogue. The CLI has no active user locale.
EN = {
    "dataops.ids.bulk_patient_id": (
        "FHIR bulk Patient IDs changed by chart-number normalisation are not supported in this release."
    ),
    "dataops.ids.multiple_patients": "Multiple Patient mappings are not supported in this release.",
    "dataops.ids.chart_owner": "A chart-number ID with a separate patient reference is not supported in this release.",
    "dataops.ids.patient_id": "A Patient ID without id.pid is not supported in this release.",
    "dataops.ids.bulk_chart_rule": "FHIR bulk with a non-asis chart-number rule is not supported in this release.",
    "dataops.ids.kind.review": "Records awaiting steward review",
    "dataops.ids.order_change": "SS-MIX2 order keys differ or were not recorded. Run a full ingest from the source",
    "edc.err.edc.id_rule_newer": (
        "This study uses a newer ID rule. Update the box to the release that wrote these drafts."
    ),
    "edc.err.edc.id_rule_frozen": (
        "These data were made under the earlier rule for record IDs (D-1253). "
        "A full ingest from the source rebuilds them under the current rule."
    ),
}
ZH = {
    "dataops.ids.bulk_patient_id": ("此版本不支援正規化後會改變的 FHIR 大量匯入病人 ID。"),
    "dataops.ids.multiple_patients": "此版本不支援多個 Patient 對應。",
    "dataops.ids.chart_owner": "此版本不支援以病歷號產生 ID 並從另一欄參照病人。",
    "dataops.ids.patient_id": "此版本不支援未使用 id.pid 的 Patient ID。",
    "dataops.ids.bulk_chart_rule": "此版本的 FHIR 大量匯入僅支援 asis 病歷號規則。",
    "dataops.ids.kind.review": "待資料管理員審查的紀錄",
    "dataops.ids.order_change": "SS-MIX2 訂單鍵不符或未記錄。請從來源完整匯入",
    "edc.err.edc.id_rule_newer": "本試驗使用較新的 ID 規則。請將系統更新至建立這些草稿的版本。",
    "edc.err.edc.id_rule_frozen": (
        "這些資料的紀錄 ID 是依舊規則產生的（D-1253）。從來源完整匯入即可依現行規則重建資料。"
    ),
}
JA = {
    "dataops.ids.bulk_patient_id": ("本版の FHIR 一括取り込みは正規化で変化する患者 ID に対応していません。"),
    "dataops.ids.multiple_patients": "このリリースでは複数の Patient マッピングはサポートされていません。",
    "dataops.ids.chart_owner": "本版では患者番号を ID に使い、別の列で患者を参照する形式は未対応です。",
    "dataops.ids.patient_id": "このリリースでは id.pid を使わない Patient ID はサポートされていません。",
    "dataops.ids.bulk_chart_rule": "本版の FHIR 一括取り込みは asis 以外の患者番号ルールに対応していません。",
    "dataops.ids.kind.review": "担当者による確認が必要な記録",
    "dataops.ids.order_change": "SS-MIX2 オーダーキーが異なるか未記録です。ソースから全件取り込みを実行してください",
    "edc.err.edc.id_rule_newer": (
        "この試験は新しい ID 規則を使用しています。下書きを作成したバージョンに更新してください。"
    ),
    "edc.err.edc.id_rule_frozen": (
        "このデータの記録 ID は以前の規則で作成されました（D-1253）。"
        "ソースから全件を取り込むと、現在の規則で再構築されます。"
    ),
}
REFUSAL_KEY = "edc.err.edc.id_rule_frozen"
COMMAND = EN[REFUSAL_KEY]  # the recovery instruction exposed to existing callers


def message(key: str) -> str:
    return " / ".join(cat[key] for cat in (EN, ZH, JA))


EARLIER_RULE = message(REFUSAL_KEY)
NEWER_STUDY = message("edc.err.edc.id_rule_newer")
REVIEW_NEEDED = message("dataops.ids.kind.review")

#: the table each store keeps its rule in (one row per rule the store was stamped with)
DDL = (
    "CREATE TABLE IF NOT EXISTS tb_id_rule (rule INTEGER PRIMARY KEY CHECK (rule > 0), "
    "recorded_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)


@dataclass(frozen=True)
class Store:
    """A store of the trial database that keeps lake ids: its schema name (without the box's prefix) and the query
    that says whether it holds any (a Patient's id is not a lake id of this rule: a patient's pseudonym is the same
    under both rules)."""

    name: str
    schema: str
    table: str
    where: str
    #: the store's own question, written out (no SQL is built from strings here): any lake id of its table
    holds: str


OMOP = Store("omop", "omop", "tb_record", "source_kind = 'feed' AND resource_type <> 'Patient'",
             "SELECT 1 FROM tb_record WHERE source_kind = 'feed' AND resource_type <> 'Patient' LIMIT 1")  # fmt: skip
DERIVED = Store("derived", "derived", "score_row", "TRUE", "SELECT 1 FROM score_row LIMIT 1")
VEC = Store("vec", "vec", "note_chunk", "TRUE", "SELECT 1 FROM note_chunk LIMIT 1")
TWIN = Store("profile", "profile", "tb_patient_profile", "TRUE", "SELECT 1 FROM tb_patient_profile LIMIT 1")
POOL = Store("orch", "orch", "pool", "TRUE", "SELECT 1 FROM pool LIMIT 1")
STORES = (OMOP, DERIVED, VEC, TWIN, POOL)
#: the EDC drafts keep the rule per study (``edc.store``'s ``tb_id_rule_study``): every earlier-rule study refuses new
#: writes and retains its drafts and audit history


class IdRuleError(RuntimeError):
    """The rule of existing data is incompatible or cannot be verified."""

    def __init__(
        self,
        stores: Iterable[str],
        newer: Iterable[str] = (),
        unreadable: Iterable[str] = (),
        inaccessible: Iterable[str] = (),
    ) -> None:
        self.stores = sorted(set(stores))
        self.newer = sorted(set(newer))
        self.unreadable = sorted(set(unreadable))
        words = sorted(set(inaccessible))
        if self.unreadable:
            words.append(unreadable_words(self.unreadable))
        if self.stores:
            words.append(f"{', '.join(self.stores)}: {EARLIER_RULE} (nothing was written; {RUNBOOK})")
        if self.newer:
            words.append(
                f"{', '.join(self.newer)} hold{'s' if len(self.newer) == 1 else ''} lake ids of a newer rule than "
                f"this release's (rule {RULE}): nothing was written. Update the box to the release that wrote them; "
                "do not rebuild"
            )
        super().__init__("; ".join(words))


def stamped(tx: Any) -> bool:
    """Whether the store of ``tx`` (its search path) says :data:`RULE` and no newer rule."""
    return tx.fetchone("SELECT 1 FROM tb_id_rule WHERE rule = ?", (RULE,)) is not None and not _newer(tx)


def _newer(tx: Any) -> bool:
    return tx.fetchone("SELECT 1 FROM tb_id_rule WHERE rule > ?", (RULE,)) is not None


#: the advisory lock two first writes of one store take before one of them stamps it (pg_advisory_xact_lock)
LOCK = 1253


def ensure(tx: Any, store: Store) -> None:
    """In the store's write transaction, before lake ids are written: go on, stamp an empty store, or refuse. Two
    first writes of one empty store meet at an advisory lock: one stamps, the other then reads the stamp."""
    if _newer(tx):
        raise IdRuleError([], newer=[store.name])
    if stamped(tx):
        return
    tx.execute("SELECT pg_advisory_xact_lock(?, hashtext(current_schema()))", (LOCK,))
    if _newer(tx):
        raise IdRuleError([], newer=[store.name])
    if stamped(tx):
        return
    if tx.fetchone(store.holds) is not None or tx.fetchone("SELECT 1 FROM tb_id_rule WHERE rule = ?", (1,)) is not None:
        raise IdRuleError([store.name])
    tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (RULE,))


# ------------------------------------------------------------------------------------------------ read-only checks
CURRENT, EMPTY, OLD, NEWER, UNREAD = "current", "empty", "old", "newer", "not readable"


def probe(url: str, store: Store, schema: str | None = None) -> str:
    """The rule state of ``store`` in the trial database at ``url``, read only (no schema or table is made):
    :data:`CURRENT`, :data:`EMPTY` (no schema, no table, or no lake id), :data:`OLD`, :data:`NEWER` (stamped by a
    later release), or :data:`UNREAD` (this role may not read it: D-378 gives each service the schemas of its own
    work only)."""
    import psycopg
    from psycopg import sql

    from tb_common.db import split_url

    dsn, prefix = split_url(url)
    name = prefix + (schema or store.schema)
    missing = (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
        if store == DERIVED and name == "derived" and con.info.user == "tb_lake":
            # The deployed lake role can read the rule, never the score rows.
            row = con.execute("SELECT derived.lake_id_rule()").fetchone()
            assert row is not None
            rule = row[0]
            if rule > RULE:
                return NEWER
            return {0: EMPTY, RULE: CURRENT}.get(rule, OLD)
        try:  # the store's own tables, read as they are: a schema or a table that is not there holds no lake id
            holds = con.execute(
                sql.SQL("SELECT 1 FROM {}.{} WHERE {} LIMIT 1").format(
                    sql.Identifier(name), sql.Identifier(store.table), sql.SQL(store.where)
                )
            ).fetchone()
        except missing:
            return EMPTY
        except psycopg.errors.InsufficientPrivilege:
            return UNREAD
        try:
            rules = {
                r[0]
                for r in con.execute(sql.SQL("SELECT rule FROM {}.tb_id_rule").format(sql.Identifier(name))).fetchall()
            }
        except missing:  # a store not yet migrated to D-1253's version: written under rule 1
            rules = set()
        except psycopg.errors.InsufficientPrivilege:
            return UNREAD
        if any(r > RULE for r in rules):
            return NEWER
        if 1 in rules and RULE not in rules:
            return OLD
        if holds is None:
            return EMPTY
        return CURRENT if RULE in rules else OLD


def unreadable_words(snapshots: Iterable[str]) -> str:
    """D-1253 deep review: the one instruction for a snapshot whose id-rule record cannot be read, said alike by the
    night, the readers and the rebuild. The record is written first, atomically, so one that cannot be read is a
    write cut short (or a damaged disk): the snapshot was never finished, and neither a rebuild nor an update is the
    answer."""
    names = ", ".join(sorted(set(snapshots)))
    return (
        f"the id-rule record of {names} cannot be read (D-1253): that snapshot was never finished (its first write was "
        f"cut short, or the disk is damaged): nothing was written. Move that folder out of the lake and run the night "
        f"again; do not rebuild and do not update for it ({RUNBOOK})"
    )


def write_snapshot_record(directory: Path) -> None:
    """The snapshot's id rule, written atomically (a temporary file, synced, renamed into place, the folder synced): a
    crash, a power cut or a full disk never leaves a cut record that would read as another rule (D-1253 deep
    review)."""
    tmp = directory / f".{SNAPSHOT_RECORD}.tmp"
    tmp.write_text(json.dumps({"rule": RULE}) + "\n", encoding="utf-8")
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)  # the bytes on disk before the name points at them
    finally:
        os.close(fd)
    tmp.replace(directory / SNAPSHOT_RECORD)
    dfd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dfd)  # the rename itself survives a crash
    finally:
        os.close(dfd)


def record_keys(directory: Path, keys: dict[str, str]) -> None:
    """D-1253 ruling 11: add to the snapshot's record the form of the source numbers its ids were made from (the
    SS-MIX2 order key), written as the record is: atomically, synced."""
    _amend(directory, lambda body: body.update(keys=dict(sorted({**(body.get("keys") or {}), **keys}.items()))))


def record_source(directory: Path, source_kind: str, keys: dict[str, str] | None = None) -> None:
    """D-1253 second review, finding 7: add to the snapshot's record the source kind it was read from (a night's and
    a back-fill's alike), so a delta night over it from another source is held."""
    _amend(directory, lambda body: body.update(source=source_kind, **({"keys": keys} if keys else {})))


def snapshot_source(directory: Path) -> str | None:
    """The source kind a snapshot's record says it was read from; None when it does not say."""
    try:
        said = json.loads((directory / SNAPSHOT_RECORD).read_text(encoding="utf-8")).get("source")
    except (OSError, ValueError, AttributeError):
        return None
    return str(said) if said else None


def _amend(directory: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Change the snapshot's record in place, written as the record is: atomically, synced."""
    path = directory / SNAPSHOT_RECORD
    body = json.loads(path.read_text(encoding="utf-8"))
    change(body)
    tmp = directory / f".{SNAPSHOT_RECORD}.tmp"
    tmp.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(path)


#: Source hashes that require steward review, with the historical decision or disputed-chart status.
REVIEW = "id_rule_review.json"
#: the meta.tag a record carries while a steward has still to review it (with D-135's basis ``proposed``)
REVIEW_TAG = {"system": "urn:trialbox:review", "code": "id-rule-steward-review"}


SHARED_CHART_TAG = {"system": REVIEW_TAG["system"], "code": "shared-chart"}
BASIS = "urn:trialbox:basis"


def tag_for_review(resource: dict[str, Any], *, shared: bool = False) -> None:
    meta = resource.setdefault("meta", {})
    tags = [t for t in meta.get("tag", []) if t.get("system") != BASIS and t != REVIEW_TAG]
    if shared and SHARED_CHART_TAG not in tags:
        tags.append(dict(SHARED_CHART_TAG))
    meta["tag"] = [*tags, {"system": BASIS, "code": "proposed"}, dict(REVIEW_TAG)]


def write_review(path: Path, records: list[tuple[str, str, str]]) -> None:
    """The historical decisions, as ``(resource type, earlier id, status)``, written to ``path`` (the
    lake's :data:`REVIEW`) atomically, synced. Every record of the next nights whose earlier-rule id is one of them is
    marked for a steward's review: when the old id was shared by two patients, both records are (never carried over
    by guess)."""
    body = {"rule": RULE, "records": [{"type": t, "earlier_id": i, "status": s} for t, i, s in sorted(set(records))]}
    _save_review(path, body)


def add_shared_review(lake_dir: Path, charts: set[str], records: set[tuple[str, str]]) -> None:
    """Append chart hashes and the individual records awaiting review, preserving every prior decision."""
    import fcntl

    if not charts and not records:
        return
    path = lake_dir / REVIEW
    fd = os.open(lake_dir, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        body: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rule": RULE, "records": []}
        )
        existing = {(r["type"], r["earlier_id"]) for r in body["records"]}
        missing = (records | {("SharedChart", h) for h in charts}) - existing
        if missing:
            for typ, rid in sorted(missing):
                entry = {"type": typ, "earlier_id": rid, "status": "steward_review_needed"}
                if typ != "SharedChart":
                    entry["reason"] = "shared_chart"
                body["records"].append(entry)
            _save_review(path, body)
    finally:
        os.close(fd)


def _save_review(path: Path, body: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def read_review(lake_dir: Path, *, include_candidates: bool = True) -> frozenset[tuple[str, str]]:
    """Historical decision hashes and source-scoped disputed chart hashes on the steward review list.
    A list that cannot be read stops the night: no record a steward decided is ever coded unreviewed."""
    path = lake_dir / REVIEW
    if not path.exists():
        return frozenset()
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        # A queued candidate is neither a historical decision nor a chart to withhold on another night.
        return frozenset(
            (str(r["type"]), str(r["earlier_id"]))
            for r in body["records"]
            if include_candidates or r.get("reason") != "shared_chart"
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"{REVIEW} in the lake cannot be read (D-1253): it lists the records a steward decided before the id "
            f"rebuild, which are marked for review. Nothing was written. Restore it from the backup ({RUNBOOK})"
        ) from exc


HELD = "held.json"  # written in a snapshot's NDJSON folder when its night was held, with why (T-611)
SOURCE_CHANGE = (
    "a site changes its source only with a full night (run it without since) / "
    "更換來源時必須完整匯入，請勿指定 since / "
    "ソースを変更するには since を指定せずに全件取り込みを実行してください"
)
ORDER_CHANGE = message("dataops.ids.order_change")
HELD_NIGHT = "Night held / 此次匯入已暫停 / 取り込みは保留中です"


def hold_reason(folder: Path, *, accepting: bool = False) -> str | None:
    """The same disk verdict for the lake and the steward, including holds from older releases."""
    try:
        held = json.loads((folder / HELD).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return HELD_NIGHT
    if not isinstance(held, dict) or held.get("writing"):
        return HELD_NIGHT
    if held.get("incompatible") == "order_key":
        return ORDER_CHANGE
    if held.get("requires_full_ingest"):
        return SOURCE_CHANGE
    # Older markers recorded the non-overridable refusal only in their list of errors.
    errors = held.get("errors", [])
    if not isinstance(errors, list):
        return HELD_NIGHT
    for error in errors:
        if isinstance(error, str) and error.startswith("delta night over snapshot ") and "SS-MIX2 orders" in error:
            return ORDER_CHANGE
        if isinstance(error, str) and error.startswith("delta night from ") and "changes its source only" in error:
            return SOURCE_CHANGE
    return None if accepting or held.get("accepted") is True else HELD_NIGHT


def snapshot_keys(directory: Path) -> dict[str, str]:
    """The source-number forms a snapshot's record says (empty: none said)."""
    try:
        got = json.loads((directory / SNAPSHOT_RECORD).read_text(encoding="utf-8")).get("keys") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}


def snapshot_rule(directory: Path) -> int:
    """The rule a snapshot's ids were made under: 1 when it carries no record (written before D-1253); 0 when the
    record is unreadable or not an integer (``2.0``, ``"2"``, ``true`` are not 2): never taken for the current rule.
    A number above :data:`RULE` is a newer release's."""
    try:
        got = json.loads((directory / SNAPSHOT_RECORD).read_text(encoding="utf-8"))["rule"]
    except FileNotFoundError:
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    return got if isinstance(got, int) and not isinstance(got, bool) and got > 0 else 0


def check_snapshot(directory: Path, what: str) -> None:
    """Refuse (:class:`IdRuleError`) a snapshot that is not :data:`RULE`'s: an earlier rule's to rebuild, a newer
    rule's to update the box for."""
    rule = snapshot_rule(directory)
    if rule > RULE:
        raise IdRuleError([], newer=[what])
    if rule == 0:
        raise IdRuleError([], unreadable=[what])
    if rule != RULE:
        raise IdRuleError([what])


def open_snapshot(directory: Path, what: str | None = None) -> Path:
    """D-1253 review round 3: the one way a lake snapshot's NDJSON is opened to be read. Every entry point goes
    through it (D-1253 lists them): the night and the back-fill (their base), the lake build
    (``lake.store.Lake._source_or_refuse``), the OMOP load (``python -m omop load``, ``adapter.dual_write``), the
    FHIR load (``adapter.load_fhir.load_snapshot``) and the snapshot validation (``adapter.validate.jpcore``).
    Refuses (:class:`IdRuleError`) a snapshot of another rule; returns ``directory``."""
    check_snapshot(directory, what or f"the lake snapshot {directory.name}")
    return directory


def served_rule(database: Path) -> int:
    """The build's rule when its NDJSON was pruned. An absent sidecar predates rule 2."""
    try:
        rule = int(database.with_suffix(".duckdb.id_rule").read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return 1
    except (OSError, ValueError):
        return 0
    return max(rule, 0)


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def snapshot_names(root: Path) -> set[str]:
    """Every snapshot (an ISO date) ``root`` holds in any of its places: the NDJSON folder, the DuckDB file and its
    generations, the Parquet folder. A month-end may be served with no NDJSON (the byte budget takes the NDJSON
    first: NEW-B-38), and a rebuild cut short may have moved one part of it and not the others."""
    found: set[str] = set()
    if (root / "ndjson").is_dir():
        found |= {p.name for p in (root / "ndjson").iterdir() if p.is_dir()}
    found |= {p.name[: -len(".duckdb")] for p in (root / "db").glob("*.duckdb")}
    found |= {p.name.split(".g", 1)[0] for p in (root / "db" / "gen").glob("*.g*")}  # <s>.g<n>.duckdb, .json
    found |= {p.name.split("=", 1)[1] for p in (root / "parquet").glob("snapshot=*") if p.is_dir()}
    return {s for s in found if _DATE.fullmatch(s)}


def lake_issues(lake_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Inspect active and retained snapshots before writes or retention can replace them."""
    old: list[str] = []
    newer: list[str] = []
    ndjson = lake_dir / "ndjson"
    rules = {
        path.name: snapshot_rule(path) for path in ndjson.glob("*") if path.is_dir() and not path.name.startswith(".")
    }
    for database in (lake_dir / "db").glob("*.duckdb"):
        if database.stem not in rules:
            rules[database.stem] = served_rule(database)
    for snapshot in snapshot_names(lake_dir) - rules.keys():
        # A stranded Parquet copy or generation may still have the dated build's rule sidecar.
        rules[snapshot] = served_rule(lake_dir / "db" / f"{snapshot}.duckdb")
    for folder in (lake_dir / "ndjson-rerun").glob("*"):
        if folder.is_dir():
            rules[f"ndjson-rerun/{folder.name}"] = snapshot_rule(folder)
    snaps = sorted(rules)
    ahead = [s for s in snaps if rules[s] > RULE]
    unreadable = [f"the lake snapshot {s}" for s in snaps if rules[s] == 0]  # one instruction (D-1253 deep review)
    behind = [s for s in snaps if 0 < rules[s] < RULE]
    if behind:
        old.append(f"the lake ({len(behind)} snapshots, the last {behind[-1]})")
    if ahead:
        newer.append(f"the lake ({len(ahead)} snapshots, the last {ahead[-1]})")
    if snapshot_names(lake_dir / "id_rule_1"):
        old.append("the archived lake")
    return old, newer, unreadable


def check_lake(lake_dir: Path) -> None:
    old, newer, unreadable = lake_issues(lake_dir)
    if old or newer or unreadable:
        raise IdRuleError(old, newer=newer, unreadable=unreadable)
