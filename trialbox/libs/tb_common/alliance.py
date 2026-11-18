"""The signature of a site's alliance count table (D-1226; D-144: "counts travel as signed files").

A member box signs the table it sends to the alliance root with its Ed25519 site key; the root verifies the
signature against the key registered for that site before the table is stored or merged. The signature is a small
JSON file sent beside the CSV (``cohort_table_<…>.sig.json``); the CSV itself is unchanged, so a spreadsheet still
reads it.

What is signed (:func:`canonical`, the JSON of every field but ``signature``, keys sorted):

* ``site_id``, and the table's scope: its definitions (``definition_version``, ``<ruleset>@<version>``), its diseases
  and its quarters (the time window);
* ``table_sha256``: the hash of the table's rows as the root parses them (:func:`table_sha256`; the order of the
  rows is not in it);
* ``seq`` and ``signed_at``: the sequence of the table, taken from the time the job was received, so a later table
  of a site has a higher sequence and an old one sent again is told from a new one;
* ``key_sha256`` and ``public_key``: the key that signed, whose fingerprint must be the one the root's register holds
  for the site.

The register is the opportunity feed's site key register (``tb_common.opportunity.load_register``; the operator's
entry line comes from ``python -m tools.opportunity_feed keygen``), with the site ids ``settings.yaml`` allows. Every
refusal is a sentence that names the site and never an address or another value of the request (D-555).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common import opportunity as opp
from tb_common.crypto import ed25519_public_of, ed25519_sign, ed25519_verify

SCHEMA = "tb-alliance-table-signature/1"
SUFFIX = ".sig.json"
#: the site ids of ``settings.yaml`` (``site.id``), which the alliance tables carry
SITE_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
COLUMNS = (
    "site_id",
    "disease",
    "quarter",
    "criterion_id",
    "criterion_label",
    "n",
    "n_contactable",
    "definition_version",
)
#: the settings (``tb_common.config.DECLARED``): the member's key file, the root's register file
KEY_FILE = "TB_ALLIANCE_SIGNING_KEY_FILE"
REGISTER_FILE = "TB_ALLIANCE_SITE_KEYS_FILE"
#: what the store writes in ``verified_by`` for the root's own table, made in the box and never mailed
OWN = "own"
MAX_SEQ = 2**62
MAX_SIG_BYTES = 64 * 1024
_KEYS = frozenset(
    {
        "schema",
        "site_id",
        "studies",
        "diseases",
        "quarters",
        "table_sha256",
        "rows",
        "seq",
        "signed_at",
        "key_sha256",
        "public_key",
        "signature",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TableRefused(ValueError):
    """A table the root does not store; the message is the sentence for the sender and the job's record."""


# ---------------------------------------------------------------------------------------------- the table
def table_sha256(rows: Iterable[Mapping[str, Any]]) -> str:
    """The hash of one site's table: every column of every row, the rows in a fixed order (the formula of the
    store's record, ``orchestrator.db.cohort_table_hash``)."""
    cells = sorted(json.dumps([r[c] for c in COLUMNS], ensure_ascii=False) for r in rows)
    return hashlib.sha256("\n".join(cells).encode("utf-8")).hexdigest()


def scope(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the table is of: its site, its definitions (the study's rule set and version), diseases and quarters."""
    return {
        "site_id": str(rows[0]["site_id"]),
        "studies": sorted({str(r["definition_version"]) for r in rows}),
        "diseases": sorted({str(r["disease"]) for r in rows}),
        "quarters": sorted({str(r["quarter"]) for r in rows}),
    }


def seq_of(at: datetime) -> int:
    """A table's sequence: the time its job was received, in milliseconds since 1970 (UTC). A re-run of the same
    job signs the same bytes; a later job of the site signs a higher number."""
    return int(at.astimezone(UTC).timestamp() * 1000)


# ---------------------------------------------------------------------------------------------- signing
def canonical(doc: Mapping[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign(rows: Sequence[Mapping[str, Any]], private_pem: bytes, seq: int, signed_at: datetime) -> dict[str, Any]:
    """The signature file of one site's table. ``rows`` are the table as the root will parse it (the caller passes
    the CSV it sends through the same reader)."""
    if not rows or len({str(r["site_id"]) for r in rows}) != 1:
        raise ValueError("a signature covers one site's table")
    if not 0 < seq < MAX_SEQ:
        raise ValueError("the sequence must be a positive whole number")
    public = ed25519_public_of(private_pem)
    body: dict[str, Any] = {
        "schema": SCHEMA,
        **scope(rows),
        "table_sha256": table_sha256(rows),
        "rows": len(rows),
        "seq": seq,
        "signed_at": signed_at.astimezone(UTC).isoformat(timespec="seconds"),
        "key_sha256": opp.key_fingerprint(public),
        "public_key": public.decode("ascii"),
    }
    sig = ed25519_sign(private_pem, canonical(body))
    return {**body, "signature": {"alg": "ed25519", "sig": base64.b64encode(sig).decode("ascii")}}


def to_bytes(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("a member is written twice")
    return dict(pairs)


def read(data: bytes) -> dict[str, Any] | None:
    """A signature file as a dict, or None when the bytes are not one (the caller says so for the site)."""
    if len(data) > MAX_SIG_BYTES:
        return None
    try:
        doc = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        return None  # not JSON, or a member written twice (two readers could take different ones)
    if not isinstance(doc, dict) or set(doc) != _KEYS or doc.get("schema") != SCHEMA:
        return None  # a member unknown or missing
    sig = doc.get("signature")
    ok = (
        isinstance(doc["site_id"], str)
        and all(
            isinstance(doc[k], list) and doc[k] and all(isinstance(x, str) for x in doc[k])
            for k in ("studies", "diseases", "quarters")
        )
        and isinstance(doc["table_sha256"], str)
        and isinstance(doc["key_sha256"], str)
        and _HEX64.match(doc["key_sha256"]) is not None
        and isinstance(doc["public_key"], str)
        and isinstance(doc["signed_at"], str)
        and isinstance(doc["rows"], int)
        and isinstance(doc["seq"], int)
        and not isinstance(doc["seq"], bool)
        and 0 < doc["seq"] < MAX_SEQ
        and isinstance(sig, dict)
        and set(sig) == {"alg", "sig"}
        and sig.get("alg") == "ed25519"
        and isinstance(sig.get("sig"), str)
    )
    return doc if ok else None


# ---------------------------------------------------------------------------------------------- verifying
@dataclass(frozen=True)
class Verified:
    """A table whose signature held: the key that signed it (its fingerprint) and its sequence."""

    site_id: str
    key_sha256: str
    seq: int
    table_sha256: str


def load_register(path: str | Path) -> dict[str, dict[str, str]]:
    """The root's register of member site keys, in the form of the opportunity feed's hub register."""
    return opp.load_register(Path(path), SITE_ID)


def _verdict(
    rows: Sequence[Mapping[str, Any]],
    doc: Mapping[str, Any] | None,
    register: Mapping[str, Mapping[str, str]] | None,
) -> Verified | str:
    """The table's signature holds, by the key registered for its site, over this table and its scope; else the
    sentence that refuses it. ``doc`` None: the table came with no signature file of its own."""
    site = str(rows[0]["site_id"])
    if doc is None:
        return (
            f"the table of site {site} is not signed; the alliance root takes a table only with the signature file "
            "the site's box makes beside it"
        )
    if register is None:
        return (
            f"this alliance root has no readable register of site keys, so the table of site {site} cannot be verified"
        )
    if doc["site_id"] != site:
        return f"the table of site {site} carries a signature made for another site"
    if {k: doc[k] for k in ("studies", "diseases", "quarters")} != {
        k: v for k, v in scope(rows).items() if k != "site_id"
    }:
        return f"the table of site {site} carries a signature made for another study, version or time window"
    entry = register.get(site)
    if entry is None:
        return f"site {site} has no key in this alliance root's register"
    public = str(doc["public_key"]).encode("ascii", "replace")
    if doc["key_sha256"] != entry["key_sha256"] or opp.key_fingerprint(public) != entry["key_sha256"]:
        return f"the table of site {site} is signed by a key that is not the one registered for the site"
    if doc["table_sha256"] != table_sha256(rows) or doc["rows"] != len(rows):
        return f"the table of site {site} is not the table its signature covers; it was changed"
    try:
        raw = base64.b64decode(str(doc["signature"]["sig"]), validate=True)
        good = ed25519_verify(public, canonical(doc), raw)
    except (ValueError, binascii.Error):
        good = False
    if not good:
        return f"the signature on the table of site {site} does not verify"
    return Verified(site, str(doc["key_sha256"]), int(doc["seq"]), str(doc["table_sha256"]))


def verify(
    rows: Sequence[Mapping[str, Any]],
    doc: Mapping[str, Any] | None,
    register: Mapping[str, Mapping[str, str]] | None,
) -> Verified:
    """:func:`_verdict`, a refusal raised as :class:`TableRefused` with its sentence."""
    got = _verdict(rows, doc, register)
    if isinstance(got, str):
        raise TableRefused(got)
    return got


def checked(
    rows: Sequence[Mapping[str, Any]],
    docs: Sequence[Mapping[str, Any]],
    register: Mapping[str, Mapping[str, str]] | None,
) -> Verified | str:
    """:func:`_verdict` for each candidate signature in turn, the first that holds; else the sentence refusing the
    first candidate (written in this module; it names the site only). No candidate: unsigned. Trying each one means a
    forged second signature file (the same hash, a higher sequence) cannot push out the good one."""
    candidates: list[Mapping[str, Any] | None] = list(docs) if docs else [None]
    verdicts = [_verdict(rows, doc, register) for doc in candidates]
    good = [v for v in verdicts if isinstance(v, Verified)]
    return good[0] if good else verdicts[0]


def ruleset_of(definition_version: str) -> str:
    """The rule set of a definition (``GOUT-COH@1.0.0`` -> ``GOUT-COH``): freshness is kept per site and rule set,
    so an older table of an older version or an older quarter cannot come in beside a newer one."""
    return definition_version.split("@", 1)[0]


def stale_refusal(site: str, seq: int, table: str, held: Mapping[Any, tuple[int | None, str | None]]) -> str | None:
    """Whether a verified table may be stored. ``held``: for each (site, rule set) of the table, the highest signed
    sequence the store holds and that table's hash (None, None: nothing signed stored). Newer is taken; the same
    table sent again (same sequence, same hash) is taken as it is; anything else is an older table, or a second
    table under one sequence, and is refused."""
    for old_seq, old_sha in held.values():
        if old_seq is None or seq > old_seq:
            continue
        if seq == old_seq and table == old_sha:
            continue
        return (
            f"the table of site {site} is not newer than the one already stored for the site; an older table is not "
            "taken again"
        )
    return None


def unverified_note(sites: Iterable[str]) -> str:
    """The sentence of the merge's summary for tables stored before signatures were required."""
    names = ", ".join(sorted(set(sites)))
    return (
        f"Not merged: the tables of {names} were stored before tables were signed and are kept, marked unverified; "
        "each is merged again once its site sends it signed."
    )


def revoked_note(sites: Iterable[str]) -> str:
    """The sentence of the merge's summary for tables signed by a key the register no longer holds for the site."""
    names = ", ".join(sorted(set(sites)))
    return (
        f"Not merged: the tables of {names} were signed by a key that is no longer the one registered for the site; "
        "they are kept, and each is merged again once its site sends it signed with its registered key."
    )


class KeyFileRefused(RuntimeError):
    """The signing key setting names a file that is missing or readable by others; nothing is signed."""


# ---------------------------------------------------------------------------------------------- settings
def signing_key(extra: Mapping[str, str]) -> bytes | None:
    """The member box's site key (``TB_ALLIANCE_SIGNING_KEY_FILE``); None when the setting is not set. A setting
    that names a missing file, or a file its group or others may read, is :class:`KeyFileRefused` (never read as
    "no key"). The key is never printed."""
    named = (extra.get(KEY_FILE) or "").strip()
    if not named:
        return None
    path = Path(named)
    try:
        mode = path.stat().st_mode
    except OSError:
        raise KeyFileRefused(f"{KEY_FILE} names a key file that is not there") from None
    if not path.is_file():
        raise KeyFileRefused(f"{KEY_FILE} names something that is not a file")
    if mode & 0o077:
        raise KeyFileRefused(f"the file {KEY_FILE} names may be read by its group or others: make it mode 600")
    return path.read_bytes()


def register_of(extra: Mapping[str, str]) -> dict[str, dict[str, str]] | None:
    """The root's register (``TB_ALLIANCE_SITE_KEYS_FILE``); None without one (every table is then refused)."""
    path = (extra.get(REGISTER_FILE) or "").strip()
    if not path or not Path(path).is_file():
        return None
    return load_register(path)
