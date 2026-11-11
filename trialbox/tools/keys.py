"""``python -m tools.keys``: the site keys under a KEK, the unseal, the key inventory and rotation (T-210b; D-347).

Run on the host as root (the secrets volume), from the install folder with ``PYTHONPATH=libs:services:.``::

    python -m tools.keys init --backend shamir --threshold 2 --shares 3 --shares-out /media/stewards
    python -m tools.keys init --backend passphrase          # the passphrase: TB_KEK_PASSPHRASE, else typed twice
    python -m tools.keys init --backend file --kek-out /media/usb/trialbox.kek   # then seal it to the TPM
    python -m tools.keys wrap                               # wrap any key still plain (after keys-init)
    python -m tools.keys unseal [--share FILE ...]          # writes the KEK to /run/trialbox/kek (TB_KEK_FILE)
    python -m tools.keys status [--json]                    # wrapped or plain, fingerprints, the KEK: never a key
    python -m tools.keys check [--for-update]               # exit 1 on a custody problem (apply_update.sh runs it)
    python -m tools.keys inventory [--json]                 # every key of the box: holder, rotation, compromise
    python -m tools.keys rotate-kek --backend ...           # a new KEK; every wrapped key re-wrapped
    python -m tools.keys rotate pid_map                     # a new pid_map.key; every pid map row re-encrypted
    python -m tools.keys seal-objects [--store DIR]         # T-210c: uploads and outputs sealed under objects.key
    python -m tools.keys seal-objects --check               # exit 1 when the store is not sealed or a file is plain

The secrets folder is ``--secrets``, else ``TB_SECRETS_DIR``, else the compose volume on the host. Nothing here prints
a key, a share or a passphrase: shares go to files (0600) for the stewards to take away, one each. ``init`` refuses a
folder that already has a KEK; the site key itself is never made here (``adapter.cli keys-init``, T-612).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tb_common import kek as K

HOST_SECRETS = "/var/lib/docker/volumes/trialbox_tb-secrets/_data"
HOST_OBJECTS = "/var/lib/docker/volumes/trialbox_objects-data/_data"

#: OPS-058: every key of a box. "code" is the command that rotates it, or None where the rule is a procedure.
INVENTORY: tuple[dict[str, Any], ...] = (
    {"key": "KEK (key-encryption key)", "where": "not on the box's disks: steward shares, a passphrase, or a "
     "TPM-sealed credential; unsealed into /run/trialbox/kek (tmpfs)",
     "protects": "site_hmac.key, pid_map.key, objects.key, audit_sign.key, edc_sign.key",
     "holder": "the site's key stewards (shares) or hospital IT (TPM, passphrase)",
     "rotation": "yearly, and when a steward leaves", "code": "python -m tools.keys rotate-kek",
     "breaks": "nothing, when done with the old KEK unsealed; old shares stop working",
     "compromise": "rotate-kek at once; then rotate pid_map (the wrapped files may have been copied)"},
    {"key": "site_hmac.key", "where": "secrets volume, wrapped (site_hmac.key.wrapped)", "protects": "every "
     "pseudonym (HMAC of the chart number)", "holder": "the box; a copy in the hospital's encrypted backup",
     "rotation": "never (T-612): a new key gives every patient a new pseudonym and loses their opt-outs",
     "code": None, "breaks": "every pseudonym, the opt-outs, the lake's history",
     "compromise": "breach plan (pseudonyms can be recomputed from chart numbers); rotate-kek; a new box would "
     "re-pseudonymise from the source"},
    {"key": "pid_map.key", "where": "secrets volume, wrapped (pid_map.key.wrapped)", "protects": "the chart numbers "
     "and identities in schema pidmap", "holder": "the box", "rotation": "yearly, and on compromise",
     "code": "python -m tools.keys rotate pid_map", "breaks": "nothing: the rows are re-encrypted in one transaction",
     "compromise": "rotate pid_map; rotate-kek"},
    {"key": "objects.key", "where": "secrets volume, wrapped (objects.key.wrapped); made by seal-objects",
     "protects": "uploads, chart uploads and every job output on the objects volume (T-210c)", "holder": "the box",
     "rotation": "on compromise (no command yet: a new key means re-sealing every object)", "code": None,
     "breaks": "every upload and output until re-sealed", "compromise": "rotate-kek; re-seal the store "
     "under a new key (a later card); the objects volume may have been copied with it"},
    {"key": "audit_sign.key", "where": "secrets volume, wrapped (audit_sign.key.wrapped); public key "
     "audit_sign.pub beside it and in every anchor folder", "protects": "the signed audit heads (T-211a, D-355)",
     "holder": "the box", "rotation": "yearly, and on compromise (the old key endorses the new one in the chain)",
     "code": "python tools/audit_verify.py <audit_dir> --rotate-key \"why\" --actor NAME",
     "breaks": "nothing: heads signed before stay valid under the old public key",
     "compromise": "rotate the audit key; rotate-kek; check the chain against the off-box heads (--heads)"},
    {"key": "edc_sign.key", "where": "secrets volume, wrapped (edc_sign.key.wrapped), or TB_EDC_SIGN_KEY_FILE; "
     "made on first use", "protects": "the binding of every EDC signature to its values (D-281)",
     "holder": "the orchestrator", "rotation": "on compromise (no command yet)", "code": None,
     "breaks": "every signature made under it stops verifying: its values are not sent until signed again",
     "compromise": "rotate-kek; a new key means the open signatures are signed again (a later card)"},
    {"key": "totp.key", "where": "console data volume (/data/console/totp.key)", "protects": "the second-factor "
     "secrets of the accounts", "holder": "the box", "rotation": "on compromise: every account enrols its second "
     "factor again", "code": None, "breaks": "every second factor until re-enrolled",
     "compromise": "new key, re-enrol every account; not yet under the KEK (a later card)"},
    {"key": "backup key pair", "where": "public: deploy/secrets/backup.pub; private: hospital IT, offline",
     "protects": "every backup", "holder": "hospital IT", "rotation": "every two years, or when a holder leaves",
     "code": "python -m tools.trialbox backup-keygen (a new pair; keep the old private key for old backups)",
     "breaks": "nothing; old backups need the old private key", "compromise": "a new pair now; old backups are "
     "exposed: move or destroy them with hospital IT"},
    {"key": "service tokens", "where": "deploy/secrets/services/", "protects": "service-to-service calls",
     "holder": "the box", "rotation": "yearly, on compromise", "code": "python -m tools.trialbox secrets rotate",
     "breaks": "nothing (rolling)", "compromise": "secrets rotate"},
    {"key": "database passwords", "where": "deploy/.env", "protects": "the trial and HAPI databases",
     "holder": "the box", "rotation": "yearly, on compromise", "code": None,
     "breaks": "the services until restarted", "compromise": "RUNBOOK §5 (Secrets)"},
    {"key": "vendor update key", "where": "deploy/updates/trust.json (public keys only)", "protects": "update "
     "bundles", "holder": "the vendor", "rotation": "by a signed rotation bundle (D-210)", "code": None,
     "breaks": "nothing; the old key is retired once", "compromise": "rotation bundle; retire the key"},
    {"key": "per-update dump key", "where": "deploy/updates/rollback/<bundle>/dump.key", "protects": "the "
     "rollback database dumps of one update", "holder": "the box, for one update", "rotation": "one per update",
     "code": "tools/apply_update.sh clean", "breaks": "nothing", "compromise": "apply_update.sh clean"},
    {"key": "pgBackRest cipher, Caddy internal CA, Authelia secrets, OIDC client secret", "where": "deploy/",
     "protects": "database archive, TLS, sign-in", "holder": "the box", "rotation": "on compromise",
     "code": None, "breaks": "see RUNBOOK §5", "compromise": "RUNBOOK §5; no tool yet"},
)  # fmt: skip


def environment(env: Mapping[str, str]) -> str:
    """``tb_common.config.environment_name`` without its imports (the host python3): PRODUCTION when unset."""
    return (env.get("TB_ENV") or "PRODUCTION").strip().upper()


def secrets_dir(arg: str | None, env: Mapping[str, str]) -> Path:
    return Path(arg or env.get("TB_SECRETS_DIR") or HOST_SECRETS)


def runtime_kek_path(arg: str | None, env: Mapping[str, str]) -> Path:
    return Path(arg or env.get("TB_KEK_FILE") or K.DEFAULT_KEK_FILE)


def _say(msg: str) -> None:
    print(msg, flush=True)


def _err(msg: str) -> None:
    print(f"keys: {msg}", file=sys.stderr, flush=True)


def _passphrase(env: Mapping[str, str], var: str, prompt: str, twice: bool) -> str:
    if env.get(var):
        return env[var]
    if not sys.stdin.isatty():
        raise K.KekError(f"no passphrase: set {var} or run on a terminal")
    first = getpass.getpass(f"{prompt}: ")
    if twice and getpass.getpass(f"{prompt} again: ") != first:
        raise K.KekError("the two passphrases differ")
    return first


def _outside(path: Path, sec: Path, what: str) -> None:
    if K._inside(path, sec):
        raise K.KekError(f"{what} {path} is inside the secrets folder {sec}: it must live elsewhere")


def new_kek(a: argparse.Namespace, sec: Path, env: Mapping[str, str], pass_var: str) -> tuple[bytes, dict[str, Any]]:
    """A new KEK and its kek.json for the back end of ``a``; shares and KEK files are written here."""
    if a.backend == "passphrase":
        params = K.passphrase_params()
        if a.scrypt_n:
            params["n"] = a.scrypt_n
        phrase = _passphrase(env, pass_var, "new KEK passphrase", twice=True)
        if len(phrase) < 12:
            raise K.KekError("the passphrase is shorter than 12 characters")
        kek = K.derive_from_passphrase(phrase, params)
        return kek, K.new_meta("passphrase", kek, **params)
    kek = os.urandom(K.KEK_LEN)
    if a.backend == "shamir":
        if not a.shares_out:
            raise K.KekError("--shares-out DIR is needed: one file per steward")
        out = Path(a.shares_out)
        _outside(out, sec, "the shares folder")
        set_id, shares = K.make_shares(kek, a.threshold, a.shares)
        out.mkdir(parents=True, exist_ok=True)
        for s in shares:
            path = out / f"share-{set_id}-{s.index}-of-{s.count}.txt"
            if path.exists():
                raise K.KekError(f"{path} exists: shares are never overwritten")
            K._write_private(path, (s.text() + "\n").encode())
            _say(f"share {s.index} of {s.count} written to {path} (one steward each; then remove it from here)")
        return kek, K.new_meta("shamir", kek, threshold=a.threshold, count=a.shares, set_id=set_id)
    if not a.kek_out:
        raise K.KekError("--kek-out PATH is needed for the file back end (outside the secrets folder)")
    out = Path(a.kek_out)
    _outside(out, sec, "the KEK file")
    if out.exists():
        raise K.KekError(f"{out} exists: a KEK file is never overwritten")
    K._write_private(out, kek)
    _say(f"KEK written to {out}: seal it (systemd-creds encrypt --with-key=tpm2, or DPAPI on the Windows host), "
         f"then remove the plain file")  # fmt: skip
    return kek, K.new_meta("file", kek)


def wrap_plain(sec: Path, kek: bytes) -> list[str]:
    """Wrap every protected key still plain; each is checked by opening it before the plain file is removed."""
    done: list[str] = []
    for name in K.PROTECTED:
        p = sec / name
        if not p.exists():
            continue
        if K.wrapped_path(p).exists():
            raise K.KekError(f"{name} is there plain and wrapped: compare fingerprints (status) and remove one")
        key = p.read_bytes()
        if not key:
            raise K.KekError(f"{p} is empty: put the key back from the backup first")
        K.store_key(p, key, kek)
        if K.unwrap(kek, K.read_wrapped(p), name) != key:
            K.wrapped_path(p).unlink()
            raise K.KekError(f"{name}: the wrapped key does not open to the same key; left plain")
        p.unlink()
        done.append(f"{name} (fingerprint {K.fingerprint(key)})")
    return done


def cmd_init(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    sec = secrets_dir(a.secrets, env)
    if not sec.is_dir():
        raise K.KekError(f"the secrets folder {sec} is not here (--secrets, TB_SECRETS_DIR)")
    if K.read_meta(sec) is not None:
        raise K.KekError(f"{sec} already has a KEK ({K.META_FILE}): rotate-kek changes it")
    kek, meta = new_kek(a, sec, env, "TB_KEK_PASSPHRASE")
    K.write_meta(sec, meta)
    _say(f"KEK {meta['kek_id']} (back end {meta['backend']}) recorded in {sec / K.META_FILE}")
    for line in wrap_plain(sec, kek):
        _say(f"wrapped {line}")
    return 0


def cmd_wrap(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    sec = secrets_dir(a.secrets, env)
    done = wrap_plain(sec, K.load_kek(sec, env))
    _say("\n".join(f"wrapped {d}" for d in done) if done else "no plain key left to wrap")
    return 0


def _share_texts(a: argparse.Namespace, need: int) -> list[str]:
    if a.share:
        return [Path(f).read_text(encoding="utf-8") for f in a.share]
    if sys.stdin.isatty():
        return [getpass.getpass(f"share {i + 1} of {need}: ") for i in range(need)]
    return [line for line in sys.stdin.read().splitlines() if line.strip()]


def cmd_unseal(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    sec = secrets_dir(a.secrets, env)
    meta = K.read_meta(sec)
    if meta is None:
        raise K.KekError(f"{sec} has no KEK ({K.META_FILE}): nothing to unseal")
    if meta["backend"] == "shamir":
        kek = K.kek_from_shares(meta, _share_texts(a, int(meta["threshold"])))
    elif meta["backend"] == "passphrase":
        kek = K.derive_from_passphrase(_passphrase(env, "TB_KEK_PASSPHRASE", "KEK passphrase", twice=False), meta)
        if kek_id_mismatch(kek, meta):
            raise K.KekError("that is not this box's passphrase")
    else:
        if not a.kek_in:
            raise K.KekError("--from PATH is needed for the file back end (the opened TPM credential or the media)")
        kek = Path(a.kek_in).read_bytes()
        if kek_id_mismatch(kek, meta):
            raise K.KekError(f"{a.kek_in} is not this box's KEK")
    out = runtime_kek_path(a.out, env)
    _outside(out, sec, "the unsealed KEK")
    K._write_private(out, kek)
    _say(f"KEK {meta['kek_id']} unsealed to {out} (mode 0600; on tmpfs it is gone at the next boot)")
    return 0


def kek_id_mismatch(kek: bytes, meta: Mapping[str, Any]) -> bool:
    return len(kek) != K.KEK_LEN or K.kek_id(kek) != meta["kek_id"]


def _status_lines(c: K.Custody) -> list[str]:
    lines = [f"secrets folder: {c.secrets_dir}"]
    lines.append(f"KEK: {c.backend or 'none'} {c.kek_id or ''} ({c.kek}{': ' + c.kek_detail if c.kek_detail else ''})")
    for name, state in c.keys.items():
        fp = c.fingerprints.get(name)
        lines.append(f"{name}: {state}{f' (fingerprint {fp})' if fp else ''}")
    lines += [f"PROBLEM: {p}" for p in c.problems]
    return lines


def cmd_status(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    c = K.custody(secrets_dir(a.secrets, env), env)
    _say(json.dumps(c.as_dict(), indent=1) if a.json else "\n".join(_status_lines(c)))
    return 1 if c.problems else 0


def cmd_check(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    """Exit 1 on a custody problem; with ``--for-update`` also when keys are wrapped and the KEK is not unsealed
    here (the services an update restarts could not open them). Plain keys in VALIDATION or PRODUCTION: a warning."""
    sec = secrets_dir(a.secrets, env)
    if not sec.is_dir():
        _say(f"keys: the secrets folder {sec} is not here: not checked")
        return 0
    c = K.custody(sec, env)
    bad = list(c.problems)
    if a.for_update and c.wrapped and c.kek != "ok":
        bad.append(f"the keys are wrapped and the KEK is not unsealed ({c.kek_detail or c.kek}); the restarted "
                   f"services could not open them")  # fmt: skip
    for p in bad:
        _err(f"REFUSED: {p}")
    if c.plain and environment(env) in K.STRICT_ENVS:
        _err(f"warning: {', '.join(c.plain)} plain in {environment(env)}: python -m tools.keys init (or wrap)")
    if not bad:
        _say(f"keys: {len(c.wrapped)} wrapped, {len(c.plain)} plain, KEK {c.kek}")
    return 1 if bad else 0


def cmd_inventory(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    if a.json:
        _say(json.dumps(list(INVENTORY), indent=1, ensure_ascii=False))
        return 0
    for row in INVENTORY:
        _say(f"{row['key']}\n  where: {row['where']}\n  protects: {row['protects']}\n  holder: {row['holder']}\n"
             f"  rotation: {row['rotation']}\n  how: {row['code'] or 'procedure (no command yet)'}\n"
             f"  what breaks: {row['breaks']}\n  if compromised: {row['compromise']}")  # fmt: skip
    return 0


def cmd_rotate_kek(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    """A new KEK: every wrapped key is opened with the old one and re-wrapped. The new files are written beside the
    old (``.next``) and then renamed, key files first and ``kek.json`` last."""
    sec = secrets_dir(a.secrets, env)
    pending = sorted(f.name for f in sec.glob("*.next.key" + K.WRAPPED_SUFFIX))
    if pending:  # a key rotation cut short (audit_sign.next.key): its staged key would stay under the old KEK
        raise K.KekError(f"{', '.join(pending)} is a key rotation not finished: finish it (run it again), then "
                         f"rotate-kek")  # fmt: skip
    old = K.load_kek(sec, env)
    keys = {n: K.unwrap(old, K.read_wrapped(sec / n), n) for n in K.PROTECTED if K.wrapped_path(sec / n).exists()}
    new, meta = new_kek(a, sec, env, "TB_KEK_NEW_PASSPHRASE")
    staged = []
    for name, key in keys.items():
        nxt = K.wrapped_path(sec / name).with_name(K.wrapped_path(sec / name).name + ".next")
        K._write_private(nxt, (json.dumps(K.wrap(new, key, name), indent=1, sort_keys=True) + "\n").encode())
        staged.append((nxt, K.wrapped_path(sec / name)))
    meta_next = K.write_meta(sec, meta, suffix=".next")
    for nxt, final in staged:
        os.replace(nxt, final)
    os.replace(meta_next, sec / K.META_FILE)
    runtime = runtime_kek_path(a.out, env)
    if runtime.exists() and not K._inside(runtime, sec):
        K._write_private(runtime, new)
        _say(f"the unsealed KEK in {runtime} is now the new one")
    _say(f"KEK {meta['kek_id']} (back end {meta['backend']}) replaces the old one; {len(keys)} key(s) re-wrapped")
    return 0


def cmd_rotate(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    if a.key != "pid_map":
        name = {"site_hmac": "site_hmac.key", "totp": "totp.key", "backup": "backup key pair"}[a.key]
        row = next(r for r in INVENTORY if r["key"] == name)
        _err(f"{row['key']} is not rotated by this tool. Rule: {row['rotation']}. How: {row['code'] or 'procedure'}")
        return 2
    url = a.db_url or env.get("TB_DB_URL")
    if not url:
        raise K.KekError("TB_DB_URL is needed: the pid map rows are in the trial database")
    sec = secrets_dir(a.secrets, env)
    path = sec / "pid_map.key"
    wrapped = K.wrapped_path(path).exists()
    kek = K.load_kek(sec, env) if wrapped else None
    nxt = K.wrapped_path(path).with_name(K.wrapped_path(path).name + ".next") if wrapped else path.with_name(
        path.name + ".next")  # fmt: skip
    if nxt.exists():  # an interrupted rotation: finish it with the key it staged
        new = K.unwrap(kek, json.loads(nxt.read_text(encoding="utf-8")), path.name) if kek else nxt.read_bytes()
    else:
        new = os.urandom(32)
        data = (json.dumps(K.wrap(kek, new, path.name), indent=1, sort_keys=True) + "\n").encode() if kek else new
        K._write_private(nxt, data)
    from adapter.pidmap import PidMap

    pm = PidMap(path, url)
    try:
        moved = pm.rekey(new)
    finally:
        pm.close()
    os.replace(nxt, K.wrapped_path(path) if wrapped else path)
    _say(f"pid_map.key rotated (fingerprint {K.fingerprint(new)}); {moved} row(s) re-encrypted")
    return 0


def objects_dir(arg: str | None, env: Mapping[str, str]) -> Path:
    """``--store``, else the path of ``TB_OBJECT_STORE`` (``fs:<path>``), else the compose volume on the host."""
    if arg:
        return Path(arg)
    spec = env.get("TB_OBJECT_STORE") or ""
    if spec.startswith("fs:") and spec[3:]:
        return Path(spec[3:])
    return Path(HOST_OBJECTS)


def cmd_seal_objects(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    """T-210c: seal the object store (attachments, outputs, TWPAS bundles) under ``objects.key`` (wrapped under the
    KEK); ``--check`` only reports, and exits 1 when the store is not sealed or a file is still plain."""
    from tb_common import objstore as O

    root = objects_dir(a.store, env)
    if not root.is_dir():
        raise K.KekError(f"the object store {root} is not here (--store, TB_OBJECT_STORE)")
    if a.check:
        seal = O.read_seal(root)
        plain = O.plain_objects(root)
        if seal is None:
            _err(f"REFUSED: the object store {root} is not sealed ({len(plain)} plain object(s)): seal-objects")
            return 1
        if plain:
            _err(f"REFUSED: {len(plain)} plain object(s) in the sealed store {root}, e.g. "
                 f"{plain[0].relative_to(root).as_posix()}: run seal-objects again")  # fmt: skip
            return 1
        _say(f"objects: sealed under objects.key {seal['fingerprint']}; no plain object")
        return 0
    rep = O.seal_store(root, secrets_dir(a.secrets, env), env)
    made = "made (wrapped under the KEK)" if rep.key_made else "already there"
    _say(f"objects.key {made}, fingerprint {rep.fingerprint}; {rep.converted} object(s) sealed now, "
         f"{rep.already} already sealed; new uploads and outputs are written sealed")  # fmt: skip
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m tools.keys", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_secrets(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--secrets", help=f"the secrets folder (TB_SECRETS_DIR; default {HOST_SECRETS})")
        return p

    def with_backend(p: argparse.ArgumentParser) -> None:
        p.add_argument("--backend", choices=K.BACKENDS, required=True)
        p.add_argument("--threshold", type=int, default=2, help="shamir: shares needed (default 2)")
        p.add_argument("--shares", type=int, default=3, help="shamir: shares made (default 3)")
        p.add_argument("--shares-out", help="shamir: folder for the share files (outside the secrets folder)")
        p.add_argument("--kek-out", help="file: where the new KEK is written (outside the secrets folder)")
        p.add_argument("--scrypt-n", type=int, help=argparse.SUPPRESS)  # tests: a cheaper scrypt

    with_backend(with_secrets(sub.add_parser("init", help="make the KEK and wrap the site keys")))
    with_secrets(sub.add_parser("wrap", help="wrap every key still plain"))
    u = with_secrets(sub.add_parser("unseal", help="put the KEK in the runtime file"))
    u.add_argument("--share", action="append", help="a share file (repeat); else read from the terminal or stdin")
    u.add_argument("--from", dest="kek_in", help="file back end: the opened KEK file")
    u.add_argument("--out", help=f"the runtime KEK file (TB_KEK_FILE; default {K.DEFAULT_KEK_FILE})")
    s = with_secrets(sub.add_parser("status", help="wrapped or plain, fingerprints, the KEK"))
    s.add_argument("--json", action="store_true")
    c = with_secrets(sub.add_parser("check", help="exit 1 on a custody problem"))
    c.add_argument("--for-update", action="store_true", help="also refuse wrapped keys with no KEK unsealed")
    i = sub.add_parser("inventory", help="every key of the box (OPS-058)")
    i.add_argument("--json", action="store_true")
    r = with_secrets(sub.add_parser("rotate-kek", help="a new KEK; every wrapped key re-wrapped"))
    with_backend(r)
    r.add_argument("--out", help="the runtime KEK file to update (TB_KEK_FILE)")
    k = with_secrets(sub.add_parser("rotate", help="rotate one key"))
    k.add_argument("key", choices=("pid_map", "site_hmac", "totp", "backup"))
    k.add_argument("--db-url", help="the trial database (TB_DB_URL)")
    o = with_secrets(sub.add_parser("seal-objects", help="seal uploads and outputs under objects.key (T-210c)"))
    o.add_argument("--store", help=f"the object store folder (TB_OBJECT_STORE; default {HOST_OBJECTS})")
    o.add_argument("--check", action="store_true", help="only report; exit 1 when not sealed or a file is plain")
    return ap


COMMANDS = {"init": cmd_init, "wrap": cmd_wrap, "unseal": cmd_unseal, "status": cmd_status, "check": cmd_check,
            "inventory": cmd_inventory, "rotate-kek": cmd_rotate_kek, "rotate": cmd_rotate,
            "seal-objects": cmd_seal_objects}  # fmt: skip


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    a = parser().parse_args(argv)
    env = os.environ if env is None else env
    try:
        return COMMANDS[a.cmd](a, env)
    except K.KekError as exc:
        _err(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
