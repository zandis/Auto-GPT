"""Recompute the TrialBox audit hash chain (SPEC §10.2). Exit 0 when intact, 1 otherwise.

Usage::

    python tools/audit_verify.py <audit_dir> [--json] [--anchor FILE] [--no-head]
    python tools/audit_verify.py <audit_dir> --find-ids [--json]
    python tools/audit_verify.py <audit_dir> --reanchor "why" --actor NAME
    python tools/audit_verify.py <audit_dir> --heads ANCHOR_DIR [--pubkey FILE ...]
    python tools/audit_verify.py <audit_dir> --init-key [--secrets DIR]
    python tools/audit_verify.py <audit_dir> --sign-head [--to ANCHOR_DIR ...] [--secrets DIR]
    python tools/audit_verify.py <audit_dir> --rotate-key "why" --actor NAME [--to ANCHOR_DIR ...] [--secrets DIR]

* The chain must end where its head anchor (``<audit_dir>/HEAD.json``) says (D-272, register CR-054). ``--anchor``
  also checks an anchor kept elsewhere, such as the audit archive's ``HEAD.json``: that catches a chain rewritten
  together with its own anchor. ``--no-head`` checks a copy that has no anchor (a decompressed archive).
* ``--find-ids`` lists the events that hold a chart number in clear (written before D-272, register CR-016): file,
  line, time, event, job and the field, never the value. They stay in the chain until the owner rules (OD-7); this
  is the list for that ruling. It also counts, per event, the rows that name a patient pseudonym (DATA-013).
  Exit 0 when none is found, 1 otherwise.
* ``--reanchor`` is for a person who has looked at a chain that does not match its anchor: it records the old
  anchor, the chain as found and the reason as an ``audit.reanchored`` event, and anchors the chain where it ends.
  No line is changed or removed.
* Signed heads and off-box anchors (T-211a, D-355, register CR-042). ``--init-key`` makes the site's Ed25519 audit
  key (``audit_sign.key``) in the secrets folder (``--secrets``, else ``TB_SECRETS_DIR``), wrapped under the KEK when
  the folder has one (T-210b) and refused plain in VALIDATION and PRODUCTION; its public key is ``audit_sign.pub``.
  ``--sign-head`` (the nightly timer) signs where the chain stands and writes the signed head, write-once, to every
  anchor folder (``--to``, else ``TB_AUDIT_ANCHOR_TARGETS``: local paths such as the mounted hospital share). It
  exits 1 when a folder did not take it. ``--heads`` checks the chain against every signed head of an anchor folder:
  a line removed and the rest recomputed fails even when ``HEAD.json`` was rewritten too. The trusted public keys are
  ``--pubkey`` (files or folders); without it, the anchor folder's ``keys/`` (said in a note). ``--rotate-key``
  records a hand-over to a new key, endorsed by the old one, then signs with the new key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from tb_common import audit
from tb_common.audit import AuditLog, clear_ids, verify

_PID = re.compile(r"\b[0-9a-f]{32}\b")


def find_ids(directory: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rows that hold a chart number in clear, and per event the rows that name a 32-hex pseudonym."""
    rows: list[dict[str, Any]] = []
    pids: Counter[str] = Counter()
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                body = {k: v for k, v in rec.items() if k not in ("hash", "prev_hash", "input_sha", "output_sha")}
                where = clear_ids(body)
                if where:
                    rows.append({"file": path.name, "line": lineno, "ts": rec.get("ts"), "event": rec.get("event"),
                                 "job_id": rec.get("job_id"), "hash": rec.get("hash"), "fields": where})  # fmt: skip
                if _PID.search(json.dumps(rec.get("detail") or {}, ensure_ascii=False)):
                    pids[str(rec.get("event"))] += 1
    return rows, dict(sorted(pids.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audit_dir", type=Path)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--anchor", type=Path, help="a head anchor kept elsewhere (the archive's HEAD.json)")
    ap.add_argument("--no-head", action="store_true", help="the folder is a copy without HEAD.json")
    ap.add_argument("--find-ids", action="store_true", help="list events holding a chart number in clear")
    ap.add_argument("--foreign", action="store_true",
                    help="list events the drain marked: a name its sending database role does not write, or a time "
                         "far from the journal's (T-721)")  # fmt: skip
    ap.add_argument("--reanchor", metavar="REASON", help="record the gap and anchor the chain where it ends")
    ap.add_argument("--actor", default="", help="who runs --reanchor or --rotate-key")
    ap.add_argument("--heads", type=Path, action="append", help="an anchor folder whose signed heads are checked")
    ap.add_argument("--pubkey", type=Path, action="append", help="a trusted public key file (or folder of .pub)")
    ap.add_argument("--init-key", action="store_true", help="make the audit signing key in the secrets folder")
    ap.add_argument("--sign-head", action="store_true", help="sign the chain's head into the anchor folders")
    ap.add_argument("--rotate-key", metavar="REASON", help="hand over to a new signing key, then sign")
    ap.add_argument("--to", type=Path, action="append", help="an anchor folder (default TB_AUDIT_ANCHOR_TARGETS)")
    ap.add_argument("--secrets", type=Path, help="the secrets folder (default TB_SECRETS_DIR)")
    args = ap.parse_args(argv)
    if not args.audit_dir.is_dir():
        print(f"no such directory: {args.audit_dir}", file=sys.stderr)
        return 2
    secrets_dir = args.secrets or Path(os.environ.get("TB_SECRETS_DIR") or "/run/secrets/trialbox")
    if args.init_key:
        return init_key(secrets_dir)
    if args.sign_head or args.rotate_key is not None:
        targets = args.to or audit.anchor_targets()
        if not targets:
            print(f"no anchor folder: give --to or set {audit.ANCHOR_TARGETS_ENV}", file=sys.stderr)
            return 2
        if args.rotate_key is not None:
            return rotate_key(args.audit_dir, secrets_dir, targets, args.rotate_key, args.actor)
        return sign_head(args.audit_dir, secrets_dir, targets, "audit_verify:sign-head")
    if args.reanchor is not None:
        if not args.actor.strip() or not args.reanchor.strip():
            print("--reanchor needs a reason and --actor", file=sys.stderr)
            return 2
        rec = AuditLog(args.audit_dir).reanchor(f"audit_verify:{args.actor.strip()}", args.reanchor)
        print(f"audit.reanchored written: {canonical_detail(rec)}")
        return 0
    if args.foreign:
        from tb_common.audit_writer import flagged

        marked = flagged(args.audit_dir)
        if args.json:
            print(json.dumps({"flagged": marked}, ensure_ascii=False))
        else:
            print(f"{len(marked)} audit events are marked by the drain (D-488)")
            for r in marked:
                print(f"  journal {r['seq']} from {r['role']}: {r['event']} at {r['ts']} (received {r['at']}): "
                      f"{', '.join(r['flag'])}")  # fmt: skip
        return 1 if marked else 0
    if args.find_ids:
        rows, pids = find_ids(args.audit_dir)
        if args.json:
            print(json.dumps({"rows": rows, "pseudonym_rows_by_event": pids}, ensure_ascii=False))
        else:
            print(f"{len(rows)} audit events hold a chart number in clear (the value is not printed)")
            for r in rows:
                print(f"  {r['file']}:{r['line']} {r['ts']} {r['event']} job={r['job_id']} {', '.join(r['fields'])}")
            print(f"events naming a patient pseudonym: {sum(pids.values())}")
            for event, n in pids.items():
                print(f"  {event}: {n}")
        return 1 if rows else 0
    anchor = json.loads(args.anchor.read_text(encoding="utf-8")) if args.anchor else None
    heads: list[dict[str, Any]] | None = None
    trusted: dict[str, bytes] = {}
    trust_note = None
    if args.heads:
        heads = [h for d in args.heads for h in audit.read_signed_heads(d)]
        trusted = audit.read_public_keys(args.pubkey or [d / "keys" for d in args.heads if (d / "keys").is_dir()])
        if not args.pubkey:
            trust_note = "signed heads: the trusted keys were taken from the anchor folder (give --pubkey to pin them)"
    res = verify(args.audit_dir, anchor=anchor, require_head=not args.no_head, signed_heads=heads, trusted_keys=trusted)
    if trust_note:
        res.notes.append(trust_note)
    if not args.heads:
        res.notes.append("signed heads were not checked (give --heads ANCHOR_DIR): a chain re-made together with its "
                         "head anchor passes this check")  # fmt: skip
    if args.json:
        print(
            json.dumps(
                {
                    "ok": res.ok,
                    "files": res.files,
                    "lines": res.lines,
                    "last_hash": res.last_hash,
                    "head": res.head,
                    "errors": res.errors,
                    "notes": res.notes,
                },
                ensure_ascii=False,
            )
        )
    else:
        status = "PASS" if res.ok else "FAIL"
        print(f"audit chain {status}: {res.files} files, {res.lines} events, head {res.last_hash[:16]}…")
        for err in res.errors[:50]:
            print(f"  {err}")
        for note in res.notes[:20]:
            print(f"  note: {note}")
    return 0 if res.ok else 1


def _env() -> str:
    return (os.environ.get("TB_ENV") or "PRODUCTION").strip().upper()


def _store_private(path: Path, private_pem: bytes) -> Path:
    """Write a signing key: wrapped under the KEK when the folder has one, else plain (DEV and TEST only)."""
    from tb_common import kek

    if kek.read_meta(path.parent) is not None:
        return kek.store_key(path, private_pem, kek.load_kek(path.parent))
    if _env() in kek.STRICT_ENVS:
        raise kek.KekError(f"{path.parent} has no KEK: in {_env()} the audit key is kept only under it (T-210b)")
    return kek.store_key(path, private_pem, None)


def _write_public(path: Path, public_pem: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(public_pem)
    tmp.chmod(0o644)
    os.replace(tmp, path)


def _load_pair(secrets_dir: Path, name: str = audit.SIGN_KEY_FILE) -> tuple[bytes, bytes]:
    """The signing key and its public key. The key is opened through the KEK when it is wrapped (T-210d): a KEK not
    unsealed, another box's KEK or a damaged file is ``KekError`` and nothing is signed; a plain copy beside the
    wrapped one is refused too. A plain key still loads (DEV, TEST; ``doctor`` FAILs it in VALIDATION and
    PRODUCTION and ``python -m tools.keys wrap`` wraps it)."""
    from tb_common import kek

    return kek.load_key_file(secrets_dir / name), (secrets_dir / (name.removesuffix(".key") + ".pub")).read_bytes()


def init_key(secrets_dir: Path) -> int:
    from tb_common import kek
    from tb_common.crypto import ed25519_generate

    path = secrets_dir / audit.SIGN_KEY_FILE
    if kek.key_present(path):
        print(f"{path} is already there: it is never replaced (use --rotate-key)", file=sys.stderr)
        return 1
    secrets_dir.mkdir(parents=True, exist_ok=True)
    private_pem, public_pem = ed25519_generate()
    try:
        where = _store_private(path, private_pem)
    except kek.KekError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    _write_public(secrets_dir / audit.SIGN_PUB_FILE, public_pem)
    print(f"audit signing key {audit.signing_key_id(public_pem)} made: {where.name}, {audit.SIGN_PUB_FILE}")
    return 0


def sign_head(audit_dir: Path, secrets_dir: Path, targets: list[Path], actor: str) -> int:
    from tb_common.crypto import KeyMissingError
    from tb_common.kek import KekError

    try:
        private_pem, public_pem = _load_pair(secrets_dir)
        rec = AuditLog(audit_dir).sign_head(private_pem, public_pem, targets, actor=actor)
    except (KeyMissingError, FileNotFoundError, KekError, audit.AuditSignError, audit.AuditAnchorBroken) as exc:
        print(f"not signed: {exc}", file=sys.stderr)
        return 1
    print(f"signed head: event {rec['lines']} ({rec['hash'][:16]}…), key {rec['key_id']}, "
          f"{len(targets) - len(rec['failed'])} of {len(targets)} anchor folders")  # fmt: skip
    for f in rec["failed"]:
        print(f"  not written: {f}", file=sys.stderr)
    return 1 if rec["failed"] else 0


def rotate_key(audit_dir: Path, secrets_dir: Path, targets: list[Path], reason: str, actor: str) -> int:
    """Hand over to a new key. The new key is kept as ``audit_sign.next.key`` until the hand-over is in the chain, so
    a run cut short is finished by running it again with the same key."""
    from tb_common import kek
    from tb_common.crypto import KeyMissingError, ed25519_generate

    if not actor.strip() or not reason.strip():
        print("--rotate-key needs a reason and --actor", file=sys.stderr)
        return 2
    nxt = "audit_sign.next.key"
    try:
        old_priv, old_pub = _load_pair(secrets_dir)
        if kek.key_present(secrets_dir / nxt):
            new_priv, new_pub = _load_pair(secrets_dir, nxt)
        else:
            new_priv, new_pub = ed25519_generate()
            _store_private(secrets_dir / nxt, new_priv)
            _write_public(secrets_dir / "audit_sign.next.pub", new_pub)
        AuditLog(audit_dir).rotate_signing_key(old_priv, old_pub, new_pub, actor=f"audit_verify:{actor.strip()}",
                                               reason=reason)  # fmt: skip
        _write_public(secrets_dir / f"audit_sign.{audit.signing_key_id(old_pub)}.pub", old_pub)
        _store_private(secrets_dir / audit.SIGN_KEY_FILE, new_priv)
        _write_public(secrets_dir / audit.SIGN_PUB_FILE, new_pub)
        for f in (nxt, nxt + kek.WRAPPED_SUFFIX, "audit_sign.next.pub"):
            (secrets_dir / f).unlink(missing_ok=True)
    except (KeyMissingError, FileNotFoundError, kek.KekError, audit.AuditAnchorBroken, ValueError) as exc:
        print(f"not rotated: {exc}", file=sys.stderr)
        return 1
    print(f"audit signing key {audit.signing_key_id(old_pub)} handed over to {audit.signing_key_id(new_pub)}")
    return sign_head(audit_dir, secrets_dir, targets, f"audit_verify:{actor.strip()}")


def canonical_detail(rec: dict[str, Any]) -> str:
    return json.dumps(rec.get("detail") or {}, sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
