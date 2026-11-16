"""``python -m tools.keys ceremony-record`` (TB-SOP-03, D-893): the record the key custodians sign at the key ceremony
(IQ-05: the site key made on the box, the KEK held as the site chose, the shares handed to named custodians).

It holds fingerprints and names only, never a key, a share or a passphrase: each wrapped key's fingerprint, the KEK's
back end and id (for shamir the threshold, the count and which custodian took which share, with each share file's
fingerprint when the files are given), the backup key's fingerprint, the box, the release and the date, and a
signature line for each custodian and the witness. It is refused before ``python -m tools.keys init`` and while any
key is still plain or the custody has a problem. A passphrase box (a proof of concept or a validation run) gets a
record marked as such: it is not a site's ceremony. The record goes to ``deploy/site/key-ceremony-<time>.md`` and
``.json`` (``trialbox doctor`` reads the newest), and the ceremony is an audit event ``keys.ceremony``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common import kek as K

FORMAT = "tb-key-ceremony/1"
EVENT = "keys.ceremony"
ACTOR = "python -m tools.keys ceremony-record"
PREFIX = "key-ceremony-"

#: what each back end means for the site, after a power loss and when a custodian leaves (TB-SOP-03 §3)
MEANING = {
    "file": "the KEK sealed to this machine's TPM (systemd-creds) or the Windows host (DPAPI): the box unseals itself "
    "after a power loss; it is bound to this board, so a moved disk opens nothing",
    "shamir": "the KEK split into steward shares: after a power loss the box waits until {threshold} of the {count} "
    "custodians bring their share (python -m tools.keys unseal); when a custodian leaves, rotate-kek with new shares",
    "passphrase": "PASSPHRASE back end: a proof of concept or a validation run (TB_HOST_PROFILE=poc). This is not a "
    "site's key ceremony; a site box is made again with the TPM or steward shares before real data",
    "kms": "the KEK sealed by the hospital platform's KMS: the box unseals when the KMS answers",
}


def share_fingerprint(text: str) -> str:
    """A share's fingerprint: tells the shares apart on the record, says nothing of the share."""
    return hashlib.sha256(b"trialbox share fingerprint\x00" + text.strip().encode()).hexdigest()[:16]


def _shares(meta: Mapping[str, Any], custodians: Sequence[str], shares_dir: Path | None) -> list[dict[str, Any]]:
    count, set_id = int(meta.get("count") or 0), str(meta.get("set_id") or "")
    if len(custodians) != count:
        raise K.KekError(f"{count} shares were made and {len(custodians)} custodians are named: each share needs "
                         "one named custodian, in the order of the share numbers")  # fmt: skip
    prints: dict[int, str] = {}
    if shares_dir is not None:
        for f in sorted(shares_dir.glob(f"share-{set_id}-*-of-{count}.txt")):
            s = K.parse_share(f.read_text(encoding="utf-8"))  # refuses a damaged or foreign share
            if s.set_id != set_id:
                raise K.KekError(f"{f.name} is a share of another KEK (set {s.set_id}, the box's is {set_id})")
            prints[s.index] = share_fingerprint(f.read_text(encoding="utf-8"))
    return [{"share": i, "of": count, "custodian": name, "fingerprint": prints.get(i, "not read at the ceremony")}
            for i, name in enumerate(custodians, start=1)]  # fmt: skip


def build(
    secrets: Path,
    env: Mapping[str, str],
    custodians: Sequence[str],
    witness: str,
    *,
    shares_dir: Path | None = None,
    backup_pub: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The record, or :class:`tb_common.kek.KekError` when the box is not ready for one."""
    custodians = [c.strip() for c in custodians if c.strip()]
    witness = witness.strip()
    if not custodians or not witness:
        raise K.KekError("name every custodian (--custodian, repeat) and the witness (--witness)")
    if witness in custodians:
        raise K.KekError("the witness is not one of the custodians")
    c = K.custody(secrets, env)
    if c.backend is None:
        raise K.KekError("no KEK yet: python -m tools.keys init first (the ceremony records what it made)")
    if c.plain:
        raise K.KekError(f"{', '.join(c.plain)} still plain: python -m tools.keys wrap first")
    if c.problems:
        raise K.KekError("the custody has a problem: " + "; ".join(c.problems))
    meta = K.read_meta(secrets) or {}
    kek: dict[str, Any] = {"backend": c.backend, "kek_id": c.kek_id}
    if c.backend == "shamir":
        kek.update(threshold=int(meta.get("threshold") or 0), count=int(meta.get("count") or 0))
    kek["meaning"] = MEANING.get(c.backend, c.backend).format(**{"threshold": "?", "count": "?", **kek})
    rec: dict[str, Any] = {
        "format": FORMAT,
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "site": env.get("TB_SITE_ID") or "",
        "environment": (env.get("TB_ENV") or "PRODUCTION").strip().upper(),
        "release": _release(),
        "kek": kek,
        "keys": {n: c.fingerprints.get(n, "") for n in c.wrapped},
        "custodians": custodians,
        "witness": witness,
        "shares": _shares(meta, custodians, shares_dir) if c.backend == "shamir" else [],
        "not_a_site_ceremony": c.backend == "passphrase",
    }
    if backup_pub is not None and backup_pub.is_file():
        from tools.trialbox import backup as bk

        rec["backup_key"] = bk.fingerprint(bk.load_public(backup_pub).public_bytes_raw())
    return rec


def _release() -> str:
    try:
        from tb_common import __version__

        return str(__version__)
    except Exception:  # the host's python without the libs: said, never guessed
        return "unknown"


def render(rec: Mapping[str, Any]) -> str:
    k = rec["kek"]
    lines = [f"# Key ceremony record ({rec['site'] or 'this box'}, {rec['at']})", ""]
    if rec.get("not_a_site_ceremony"):
        lines += ["**NOT A SITE'S KEY CEREMONY**: the passphrase back end (a proof of concept or a validation run).",
                  ""]  # fmt: skip
    lines += [
        f"- Environment: {rec['environment']}; release {rec['release']}",
        f"- KEK: {k['backend']} {k['kek_id']}" + (f", {k['threshold']} of {k['count']} shares" if "count" in k else ""),
        f"- What it means: {k['meaning']}",
    ]
    if rec.get("backup_key"):
        lines.append(f"- Backup key: {rec['backup_key']} (the private half in hospital IT's sealed envelope)")
    lines += ["", "| Key | Fingerprint |", "| --- | --- |"]
    lines += [f"| {n} | `{fp}` |" for n, fp in rec["keys"].items()]
    if rec["shares"]:
        lines += ["", "| Share | Custodian | Share fingerprint |", "| --- | --- | --- |"]
        lines += [f"| {s['share']} of {s['of']} | {s['custodian']} | `{s['fingerprint']}` |" for s in rec["shares"]]
    lines += ["", "No key, share or passphrase is in this record. Signed by:", ""]
    lines += [f"- Custodian {name}: ____________________ date ______" for name in rec["custodians"]]
    lines += [f"- Witness {rec['witness']}: ____________________ date ______", ""]
    return "\n".join(lines)


def write(deploy: Path, rec: Mapping[str, Any]) -> Path:
    """``deploy/site/key-ceremony-<time>.md`` and ``.json``; returns the Markdown file."""
    site = deploy / "site"
    site.mkdir(parents=True, exist_ok=True)
    stem = PREFIX + str(rec["at"]).replace(":", "").replace("-", "").replace("+0000", "Z")
    md = site / f"{stem}.md"
    if md.exists():
        raise K.KekError(f"{md} exists: a ceremony record is never overwritten")
    md.write_text(render(rec), encoding="utf-8")
    (site / f"{stem}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return md


def audit(env: Mapping[str, str], rec: Mapping[str, Any], audit_dir: Path | None) -> str:
    where = audit_dir or (Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None)
    if where is None or not where.is_dir():
        return "not written: no audit folder (TB_AUDIT_DIR, --audit-dir)"
    from tb_common.audit import AuditLog

    detail = {k: rec[k] for k in ("at", "kek", "keys", "custodians", "witness", "shares", "not_a_site_ceremony")}
    AuditLog(where).append(EVENT, actor=ACTOR, input_sha="", detail=detail)
    return str(where)


def newest(deploy: Path) -> dict[str, Any] | None:
    """The newest ceremony record of the box (``trialbox doctor``), or None."""
    files = sorted((deploy / "site").glob(f"{PREFIX}*.json")) if (deploy / "site").is_dir() else []
    for f in reversed(files):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("format") == FORMAT:
            return doc
    return None


def default_backup_pub(env: Mapping[str, str], deploy: Path) -> Path:
    return Path(env.get("TB_BACKUP_PUBKEY") or deploy / "secrets" / "backup.pub")
