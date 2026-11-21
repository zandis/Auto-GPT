"""Ownership and stable keys for patient-owned source records."""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tb_common import chartno
from tb_common.crypto import PID_HEX_LEN, pid_for_mrn


@dataclass(frozen=True)
class Identifier:
    value: str
    kind: Literal["opaque", "chart"] = "opaque"


@dataclass
class IdentityState:
    """Owner evidence for one publication attempt, shared across all its tables."""

    held: set[str] = field(default_factory=set)
    evidence: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    def check_detail(self, key: bytes, owner: str, label: str, value: str) -> None:
        if value:
            digest = _digest(key, [label, owner, value])
            if self.evidence.setdefault((owner, label), digest) != digest:
                self.held.add(owner)
                raise HeldOwner("Conflicting patient details / 病人資料不一致 / 患者情報が一致しません")


@dataclass(frozen=True)
class ResolvedRecord:
    owner: str
    record_key: str
    previous_key: str | None
    namespace: str
    resource_type: str
    table: str


class MissingIdentity(ValueError):
    """One of the required parts of the source identity was absent."""


class MissingRecordID(MissingIdentity):
    """Owner evidence was checked, but the source occurrence has no usable key."""


class HeldOwner(RuntimeError):
    """Abort publication, including records already staged in this batch."""


RECORD_RULE = "1"
SCOPE_FILE = "record_identity.json"
BULK_SCOPE = json.dumps(["fhir_bulk", "1"])
SNAPSHOT_REFUSAL = (
    "record_identity.snapshot_scope: Delta refused. Decide how to migrate the snapshot's record IDs. / "
    "已拒絕差異匯入。請決定快照紀錄識別碼的遷移方式。 / "
    "差分取込を拒否しました。スナップショットの記録IDの移行方法を決定してください。"
)
_DIGEST_KEY = re.compile(rf"[0-9a-f]{{{PID_HEX_LEN}}}")


def check_unscoped_key(key: str) -> None:
    """Plain-ID merges can only prove disjointness outside the gate's key space.

    A digest's spelling cannot establish its provenance. Require a receipt for every
    such delta, including callers passing serialized tombstones directly to the writer.
    """
    if _DIGEST_KEY.fullmatch(key):
        raise HeldOwner(SNAPSHOT_REFUSAL)


def check_snapshot_scope(base: Path, scope: str | None) -> None:
    """Only merge key spaces with matching publication receipts."""
    try:
        previous = (base / SCOPE_FILE).read_bytes()
    except FileNotFoundError:
        previous = None
    except OSError as exc:
        raise HeldOwner(SNAPSHOT_REFUSAL) from exc
    if previous != (scope.encode("utf-8") if scope is not None else None):
        raise HeldOwner(SNAPSHOT_REFUSAL)


def _digest(key: bytes, parts: list[object]) -> str:
    body = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    # Chart pseudonyms historically MAC unframed input. A subkey separates the new domains
    # even if an actual chart number is itself the JSON representation of one of our inputs.
    subkey = hmac.digest(key, b"TrialBox record identity", "sha256")
    return hmac.digest(subkey, body, "sha256").hex()[:PID_HEX_LEN]


def resolve_record(
    site_key: bytes,
    namespace: str,
    patient_ids: tuple[Identifier, ...],
    resource_type: str,
    record_ids: tuple[Identifier, ...],
    *,
    occurrence: str = "",
    rule_version: str = RECORD_RULE,
    table: str = "",
    previous: ResolvedRecord | None = None,
    state: IdentityState,
    birth_date: str = "",
    national_id: str = "",
) -> ResolvedRecord:
    """Resolve all owner evidence together before issuing a key.

    A chart is in the site's existing pseudonym domain (including its opt-outs). Server IDs are
    opaque within their source namespace. Table, type and occurrence distinguish separate records.
    The rule version names the key format, independent of mapping-file edits and ingest time.

    Share state across the batch. Compare nonempty Patient birth dates and declared national IDs
    across all tables. Conflicting evidence holds every implicated owner and aborts publication.
    The caller supplies the publication receipt for the record being corrected.
    A missing ledger entry never authorizes guessing a key to delete.
    """
    if len(site_key) < 16 or not namespace or not rule_version or not resource_type:
        raise ValueError("Invalid identity configuration / 識別設定無效 / 識別設定が無効です")
    claims = patient_ids + record_ids if resource_type == "Patient" else patient_ids
    owners = {
        pid_for_mrn(site_key, p.value) if p.kind == "chart" else _digest(site_key, ["owner", namespace, p.value])
        for p in claims
        if p.value.strip()
    }
    if previous is not None:
        if (namespace, resource_type, table) != (previous.namespace, previous.resource_type, previous.table):
            raise MissingIdentity("Publication scope mismatch / 發布範圍不符 / 公開範囲が一致しません")
        owners.add(previous.owner)
    if len(owners) > 1 or not owners.isdisjoint(state.held):
        state.held.update(owners)
        raise HeldOwner("Patient ownership unresolved / 無法確認病人歸屬 / 患者を特定できません")
    if not patient_ids or any(not p.value.strip() for p in patient_ids):
        raise MissingIdentity("Missing patient ID / 缺少病人識別碼 / 患者IDがありません")
    if not record_ids or any(not i.value.strip() for i in record_ids):
        raise MissingRecordID("Missing record ID / 缺少紀錄識別碼 / 記録IDがありません")
    if resource_type == "Patient" and len(record_ids) != 1:
        raise MissingIdentity("Expected one patient ID / 需要一個病人識別碼 / 患者IDは一つ必要です")
    owner = owners.pop()
    if resource_type == "Patient":
        state.check_detail(site_key, owner, "birth", birth_date)
        state.check_detail(site_key, owner, "national", national_id)
        key = owner
    else:
        parts = [chartno.normalise(None, i.value) if i.kind == "chart" else i.value for i in record_ids]
        key = _digest(site_key, ["record", rule_version, namespace, table, resource_type, owner, parts, occurrence])
    return ResolvedRecord(owner, key, previous.record_key if previous else None, namespace, resource_type, table)
