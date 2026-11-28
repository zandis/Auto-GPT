"""``python -m tools.keys``: the site keys under a KEK, the unseal, the key inventory and rotation (T-210b; D-347).

Run on the host as root (the secrets volume), from the install folder with ``PYTHONPATH=libs:services:.``::

    python -m tools.keys init --backend shamir --threshold 2 --shares 3 --shares-out /media/stewards
    python -m tools.keys init --backend passphrase --passphrase-file /root/trialbox-kek.pass   # or typed twice
    python -m tools.keys init --backend file --kek-out /media/usb/trialbox.kek   # then seal it to the TPM
    python -m tools.keys init --backend kms --kms-url https://kms.hosp/v1/transit --kms-key trialbox  # a platform
    python -m tools.keys wrap                               # wrap any key still plain (after keys-init)
    python -m tools.keys unseal [--share FILE ...]          # writes the KEK to /run/trialbox/kek (TB_KEK_FILE)
    python -m tools.keys status [--json] [--audit-dir DIR]  # wrapped or plain, fingerprints, the KEK: never a key
    python -m tools.keys check [--for-update]               # exit 1 on a custody problem (apply_update.sh runs it)
    python -m tools.keys inventory [--json]                 # every key of the box: holder, rotation, compromise
    python -m tools.keys rotate-kek --backend ...           # a new KEK; every wrapped key re-wrapped
    python -m tools.keys rotate-kek --backend passphrase --new-passphrase-file F [--passphrase-file OLD]
    python -m tools.keys rotate pid_map                     # a new pid_map.key; every pid map row re-encrypted
    python -m tools.keys seal-objects [--store DIR]         # T-210c: uploads and outputs sealed under objects.key
    python -m tools.keys seal-objects --check               # exit 1 when the store is not sealed or a file is plain
    python -m tools.keys restic-key                         # D-968: the incremental backup's password, under the KEK
    python -m tools.keys ceremony-record --custodian A --custodian B --custodian C --witness W [--shares-dir DIR]
                                                            # TB-SOP-03 (D-893): the record the custodians sign
    python -m tools.keys escrow-shares --threshold 2 --shares 3 --escrow-out /media/usb --custodian A ... (x3)
                                                            # D-894: the escrow copy of a TPM-sealed KEK
    python -m tools.keys unseal --share FILE --share FILE --witness W   # a TPM box on a new board, from escrow

The secrets folder is ``--secrets``, else ``TB_SECRETS_DIR``, else the compose volume on the host. Nothing here prints
a key, a share or a passphrase: shares go to files (0600) for the stewards to take away, one each. ``init`` refuses a
folder that already has a KEK; the site key itself is never made here (``adapter.cli keys-init``, T-612).

A passphrase (H-96, F-45; the integrator's ruling 7094934985) comes from a file only root can read
(``--passphrase-file``, ``--new-passphrase-file``: one line in a regular file, not a link, owned by the user that runs
this, mode 0600; removed once used unless ``--keep-passphrase-files``), from stdin (``--passphrase-stdin``,
``--new-passphrase-stdin``: one line each, the old first; on a terminal they are asked, not shown), or is asked on the
terminal. ``TB_KEK_PASSPHRASE`` or ``TB_KEK_NEW_PASSPHRASE`` in the environment is refused by every command: sudo logs
the variables it keeps, with their values (``RUNBOOK §23, rotate the KEK passphrase``).

rc1 refuses the key ceremonies on a PRODUCTION box (R22-34), rotate-kek among them, with one exception (D-1092; the
integrator's ruling 7101844662): a box sealed under a passphrase rotates it to a new passphrase given by the file or
stdin form, with no escrow set, and the rotation is the audit event ``keys.rotate_kek`` (who, when, the box, the two
KEK ids; never a value) in ``--audit-dir`` or ``TB_AUDIT_DIR``, without which it is refused. Every rotate-kek, on every
box, is that audit event and is refused without its folder (the integrator's ruling 7114085298).

The review of #1429: the folder must hold the box's chain; ``keys.rotate_kek_started`` comes before any change and a
rotation whose started event fails is refused; appends made as root go through the folder's owner; a journal
(``kek-rotation.json``) lets the next ``status --audit-dir`` or ``rotate-kek`` finish or roll back a rotation cut
short; and an exclusive lock on the secrets folder runs one rotation at a time.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import getpass
import hmac
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tb_common import kek as K

HOST_SECRETS = "/var/lib/docker/volumes/trialbox_tb-secrets/_data"
HOST_OBJECTS = "/var/lib/docker/volumes/trialbox_objects-data/_data"
DEFAULT_DEPLOY = str(Path(__file__).resolve().parents[1] / "deploy")

#: OPS-058: every key of a box. "code" is the command that rotates it, or None where the rule is a procedure.
INVENTORY: tuple[dict[str, Any], ...] = (
    {"key": "KEK (key-encryption key)", "where": "not on the box's disks: steward shares, a passphrase, or a "
     "TPM-sealed credential; unsealed into /run/trialbox/kek (tmpfs)",
     "protects": "site_hmac.key, pid_map.key, objects.key, audit_sign.key, edc_sign.key, restic.key",
     "holder": "the site's key stewards (shares) or hospital IT (TPM, passphrase); a TPM KEK's escrow shares with "
     "their custodians (escrow-shares, D-894)",
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
    {"key": "alliance signing key", "where": "a member box of a COHORT alliance only: the file "
     "TB_ALLIANCE_SIGNING_KEY_FILE names, mode 600, plain (not under the KEK); its fingerprint in the alliance "
     "root's register (TB_ALLIANCE_SITE_KEYS_FILE)", "protects": "that the root takes the site's count tables as the "
     "site's (D-1226)", "holder": "the box; the root's operator holds the fingerprint", "rotation": "on compromise "
     "or a new box (runbook 23, Alliance site keys)", "code": None,
     "breaks": "the site's tables signed with the old key are left out of merges until it sends them again",
     "compromise": "the root's operator removes the site's register line; keygen on the box; the new line added"},
    {"key": "restic.key", "where": "secrets volume, wrapped (restic.key.wrapped); beside each restic repository on "
     "the backup targets, trialbox-restic.key.json: the wrapped key and the KEK's share set (no salt, no names), "
     "written only for a shamir KEK or a TPM KEK with current escrow shares", "protects": "the "
     "incremental backup's repository (D-968)", "holder": "the box; the custodians through the KEK's escrow shares "
     "(D-894) and the copy on the target", "rotation": "never in place: a new key means a new repository (the old "
     "one stays readable with the old key)", "code": None, "breaks": "every snapshot of the repository it opens",
     "compromise": "rotate-kek; a new repository under a new key, the old one destroyed with hospital IT"},
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


def own_volume(name: str) -> str:
    """H-106: the host folder of this box's own compose volume: a test box's record (``deploy/site/test-box.env``
    beside this release folder) names its project; any other box's is ``trialbox``, as before."""
    project = "trialbox"
    for deploy in (Path(__file__).absolute().parents[1] / "deploy", Path(DEFAULT_DEPLOY)):
        try:
            lines = (deploy / "site" / "test-box.env").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        project = next((ln.split("=", 1)[1].strip() for ln in lines if ln.startswith("COMPOSE_PROJECT_NAME=")), project)
        break
    return f"/var/lib/docker/volumes/{project}_{name}/_data"


def secrets_dir(arg: str | None, env: Mapping[str, str]) -> Path:
    return Path(arg or env.get("TB_SECRETS_DIR") or own_volume("tb-secrets"))


def runtime_kek_path(arg: str | None, env: Mapping[str, str]) -> Path:
    return Path(arg or env.get("TB_KEK_FILE") or K.DEFAULT_KEK_FILE)


def _say(msg: str) -> None:
    print(msg, flush=True)


def _err(msg: str) -> None:
    print(f"keys: {msg}", file=sys.stderr, flush=True)


PASSPHRASE_VARS = ("TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE")
ROTATE_PAGE = "RUNBOOK §23, rotate the KEK passphrase"


def env_passphrase_refusal(env: Mapping[str, str]) -> str | None:
    """H-96, H-94 (5): why a passphrase in the environment is refused (None when there is none). Never the value."""
    for var in PASSPHRASE_VARS:
        if env.get(var):
            return (f"{var} is set in the environment: refused, nothing was changed. A passphrase given by the "
                    "environment can be in the system journal (sudo logs the variables it keeps, with their values): "
                    f"treat that passphrase as exposed and rotate it ({ROTATE_PAGE}). Give it in a file only root can "
                    "read (--passphrase-file FILE: a regular file, owned by root, mode 0600) or on stdin "
                    f"(--passphrase-stdin). Then unset {var}.")  # fmt: skip
    return None


def _one_line(text: str, where: str) -> str:
    line = text[:-1] if text.endswith("\n") else text
    if not line:
        raise K.KekError(f"the passphrase from {where} is empty")
    if any(ord(c) < 32 or ord(c) == 127 for c in line):
        raise K.KekError(f"the passphrase from {where} holds a line break or another control character: one line")
    return line


def _safe_folders(real_dir: str, path: str, fix: str) -> None:
    """H-94 (5), M-1 of the review of #1398: the file's own folder and every folder above it (real paths) are owned by
    root (the user that runs this) and writable by no one else; above the file's own folder a shared folder with the
    sticky bit (/tmp) is allowed, as no one else can rename what is root's there."""
    euid, d, own = os.geteuid(), real_dir, True
    while True:
        try:
            st = os.stat(d)
        except OSError as exc:
            raise K.KekError(
                f"the passphrase file {path}: the folder {d} cannot be read ({type(exc).__name__})"
            ) from None
        if st.st_uid not in (0, euid):
            raise K.KekError(f"the passphrase file {path}: the folder {d} is owned by uid {st.st_uid}, not root: "
                             f"refused; {fix}")  # fmt: skip
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and (own or not st.st_mode & stat.S_ISVTX):
            raise K.KekError(f"the passphrase file {path}: the folder {d} can be written by others (mode "
                             f"{stat.S_IMODE(st.st_mode):o}): refused; {fix}")  # fmt: skip
        if d == "/":
            return
        d, own = os.path.dirname(d), False


def read_passphrase_file(path: str) -> str:
    """The passphrase of ``path`` (see :func:`read_passphrase_file_at`)."""
    return read_passphrase_file_at(path)[0]


def read_passphrase_file_at(path: str) -> tuple[str, str]:
    """One line of a regular file owned by the user that runs this (root), mode 0600, one name, in folders only root
    can write; else refused. It is opened once without following a link and checked and read on that descriptor
    (fstat), never by its name again.
    Also the real path it was read from: the file is removed by that name, never the one given (R2-1 of #1398)."""
    fix = ("a regular file owned by root with mode 0600, in a folder only root can write (sudo install -m 0600 -o root "
           "-g root /dev/null /root/trialbox-kek.pass)")  # fmt: skip
    real_dir = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    _safe_folders(real_dir, path, fix)
    name = os.path.join(real_dir, os.path.basename(path))
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOCTTY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise K.KekError(f"the passphrase file {path} is a link: refused; {fix}") from None
        raise K.KekError(f"the passphrase file {path} cannot be read ({type(exc).__name__}): {fix}") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise K.KekError(f"the passphrase file {path} is not a regular file: refused; {fix}")
        if st.st_uid != os.geteuid():
            raise K.KekError(f"the passphrase file {path} is owned by uid {st.st_uid}, not root (the user that runs "
                             f"this): refused; {fix}")  # fmt: skip
        if stat.S_IMODE(st.st_mode) != 0o600:
            raise K.KekError(f"the passphrase file {path} has mode {stat.S_IMODE(st.st_mode):o}, not 0600: refused; "
                             f"{fix}")  # fmt: skip
        if st.st_nlink != 1:
            raise K.KekError(
                f"the passphrase file {path} has {st.st_nlink} names (hard links), not one: refused; {fix}"
            )
        chunks: list[bytes] = []
        while chunk := os.read(fd, 4096):
            chunks.append(chunk)
            if sum(map(len, chunks)) > 65536:
                raise K.KekError(f"the passphrase file {path} is too long for a passphrase: one line")
    finally:
        os.close(fd)
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        raise K.KekError(f"the passphrase file {path} is not UTF-8 text: refused; write it again on one line") from None
    if text.count("\n") > 1 or (text.count("\n") == 1 and not text.endswith("\n")):
        raise K.KekError(f"the passphrase file {path} holds more than one line: the passphrase is one line")
    return _one_line(text, f"the file {path}"), name


def given_passphrases(a: argparse.Namespace, env: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """The passphrases of ``a``'s files or stdin, in memory only, by the variable the code below reads, and the files
    to remove once the command has done its work. A terminal on stdin is left to the prompts (``_passphrase``)."""
    got: dict[str, str] = {}
    used: list[str] = []
    for var, file_opt, stdin_opt in (
        ("TB_KEK_PASSPHRASE", "passphrase_file", "passphrase_stdin"),
        ("TB_KEK_NEW_PASSPHRASE", "new_passphrase_file", "new_passphrase_stdin"),
    ):
        path, from_stdin = getattr(a, file_opt, None), getattr(a, stdin_opt, False)
        if path and from_stdin:
            raise K.KekError(f"--{file_opt.replace('_', '-')} and --{stdin_opt.replace('_', '-')}: give one")
        if path:
            got[var], real = read_passphrase_file_at(path)
            used.append(real)  # the real path it was read from: a parent link re-pointed since cannot redirect it
        elif from_stdin and not sys.stdin.isatty():
            line = sys.stdin.readline()
            if not line:
                raise K.KekError(f"--{stdin_opt.replace('_', '-')}: nothing on stdin")
            got[var] = _one_line(line, "stdin")
    if getattr(a, "keep_passphrase_files", False) and not used:
        raise K.KekError("--keep-passphrase-files goes with --passphrase-file or --new-passphrase-file")
    return got, used


def _passphrase(env: Mapping[str, str], var: str, prompt: str, twice: bool) -> str:
    if env.get(var):
        return env[var]
    if not sys.stdin.isatty():
        opt = (
            "--new-passphrase-file FILE or --new-passphrase-stdin"
            if var == "TB_KEK_NEW_PASSPHRASE"
            else "--passphrase-file FILE or --passphrase-stdin"
        )
        raise K.KekError(f"no passphrase: give {opt}, or run on a terminal")
    first = getpass.getpass(f"{prompt}: ")
    if twice and getpass.getpass(f"{prompt} again: ") != first:
        raise K.KekError("the two passphrases differ")
    return first


def _outside(path: Path, sec: Path, what: str) -> None:
    if K._inside(path, sec):
        raise K.KekError(f"{what} {path} is inside the secrets folder {sec}: it must live elsewhere")


def new_kek(a: argparse.Namespace, sec: Path, env: Mapping[str, str], pass_var: str,
            old: tuple[bytes, Mapping[str, Any] | None] | None = None) -> tuple[bytes, dict[str, Any]]:  # fmt: skip
    """A new KEK and its kek.json for the back end of ``a``; shares and KEK files are written here. ``old``: the KEK
    and kek.json a rotation replaces (H-110 (l): a new passphrase that opens the old KEK is refused)."""
    if a.backend == "passphrase":
        params = K.passphrase_params()
        if a.scrypt_n:
            params["n"] = a.scrypt_n
        phrase = _passphrase(env, pass_var, "new KEK passphrase", twice=True)
        if len(phrase) < 12:
            raise K.KekError("the passphrase is shorter than 12 characters")
        if (
            old is not None
            and old[1] is not None
            and old[1].get("backend") == "passphrase"
            and hmac.compare_digest(K.derive_from_passphrase(phrase, old[1]), old[0])
        ):
            # H-110 (l): a new salt gives a new KEK id, but the box would still open with the old (exposed) passphrase
            raise K.KekError(
                "the new passphrase is the one the box is sealed under now: a rotation to it leaves "
                "the old passphrase opening the box; give a new passphrase (nothing was changed)"
            )
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
    if a.backend == "kms":
        url = a.kms_url or env.get("TB_KMS_URL") or ""
        if not url or not a.kms_key:
            raise K.KekError("--kms-url (or TB_KMS_URL) and --kms-key are needed for the kms back end")
        params = K.kms_seal(kek, url, a.kms_key, env.get("TB_KMS_TOKEN") or "")
        _say(f"KEK sealed by the KMS key {a.kms_key} at {url}; kek.json holds only the KMS ciphertext")
        return kek, K.new_meta("kms", kek, **params)
    if getattr(a, "kek_in", None):
        # D-836: a KEK sealed before any key is wrapped under it (seal_keys.sh): a failed seal changes nothing
        given = Path(a.kek_in)
        _outside(given, sec, "the KEK file")
        kek = given.read_bytes() if given.is_file() else b""
        if len(kek) != K.KEK_LEN:
            raise K.KekError(f"{given} is not a KEK ({K.KEK_LEN} bytes): nothing was changed")
        return kek, K.new_meta("file", kek)
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
        key = p.read_bytes()
        if K.wrapped_path(p).exists():
            # H-111: a run stopped between the wrap and the plain file's removal; the wrapped key opens to this one
            try:
                same = bool(key) and K.unwrap(kek, K.read_wrapped(p), name) == key
            except K.KekError:
                same = False
            if not same:
                raise K.KekError(f"{name} is there plain and wrapped: compare fingerprints (status) and remove one")
            _fsync_dir(sec)  # review of #1457 (1457-3): the wrapped copy's name is on disk before the plain one goes
            p.unlink()
            done.append(f"{name} (fingerprint {K.fingerprint(key)}; its wrap was already done)")
            continue
        if not key:
            raise K.KekError(f"{p} is empty: put the key back from the backup first")
        K.store_key(p, key, kek)
        if K.unwrap(kek, K.read_wrapped(p), name) != key:
            K.wrapped_path(p).unlink()
            raise K.KekError(f"{name}: the wrapped key does not open to the same key; left plain")
        _fsync_dir(sec)  # review of #1457 (1457-3): the wrapped copy's name is on disk before the plain one goes
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


def cmd_restic_key(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    from tb_common import rc1_refusals

    try:  # R22-34 (D-1072): rc1 holds no key ceremony on a PRODUCTION box (the stricter of the box and the caller)
        rc1_refusals.check("key_ceremonies", rc1_refusals.host_env(Path(DEFAULT_DEPLOY), env))
    except rc1_refusals.Rc1Refused as exc:
        _err(exc.say())
        return 1
    from tools.trialbox import restic_repo

    sec = secrets_dir(a.secrets, env)
    made = restic_repo.make_key(sec, env)
    key = K.load_key_file(sec / restic_repo.KEY, env)
    _say(f"{'made' if made else 'kept'} {restic_repo.KEY} under the KEK (fingerprint {K.fingerprint(key)})")
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
    elif meta["backend"] == "kms":
        kek = K.kms_open(meta, env)
    elif a.share:
        return _unseal_escrow(a, env, sec, meta)
    else:
        if not a.kek_in:
            raise K.KekError("--from PATH is needed for the file back end (the opened TPM credential or the media); "
                             "--share FILE (repeat) with --witness opens it from its escrow shares")  # fmt: skip
        kek = Path(a.kek_in).read_bytes()
        if kek_id_mismatch(kek, meta):
            raise K.KekError(f"{a.kek_in} is not this box's KEK")
    out = runtime_kek_path(a.out, env)
    _outside(out, sec, "the unsealed KEK")
    write_runtime_kek(out, kek, sec)
    _say(f"KEK {meta['kek_id']} unsealed to {out} (mode 0600; on tmpfs it is gone at the next boot)")
    return 0


def _unseal_escrow(a: argparse.Namespace, env: Mapping[str, str], sec: Path, meta: Mapping[str, Any]) -> int:
    """D-894: a TPM box's KEK from its escrow shares (a new board): a witnessed event with its own record."""
    from tools import key_escrow as ke

    witness = (a.witness or "").strip()
    if not witness:
        raise K.KekError("opening the KEK from escrow shares is witnessed: --witness NAME (not a custodian)")
    esc = ke.current(meta) or {}
    if witness in {str(r.get("custodian")) for r in esc.get("shares", [])}:
        raise K.KekError("the witness is not one of the escrow custodians")
    where = ke.audit_dir(env, a.audit_dir)
    texts = _share_texts(a, int(esc.get("threshold") or 2))
    kek = K.kek_from_escrow(meta, texts)
    out = runtime_kek_path(a.out, env)
    _outside(out, sec, "the unsealed KEK")
    indices = sorted({K.parse_share(t).index for t in texts if t.strip()})
    md, rec = ke.use_record(Path(a.deploy), esc, indices, witness)
    write_runtime_kek(out, kek, sec)
    ke.audit(where, ke.USE_EVENT, ke.USE_ACTOR, {k: rec[k] for k in ("at", "set_id", "kek_id", "witness", "shares")})
    _say(f"KEK {meta['kek_id']} unsealed from escrow set {esc['set_id']} to {out} (mode 0600)")
    _say(f"escrow-use record written to {md} (and .json): the custodians who came and the witness sign it")
    _say(
        "next: put a new KEK on this board's TPM with a new escrow set: python -m tools.keys rotate-kek --backend "
        "file --kek-out <media> --escrow-out <media> --custodian ... (the old shares then open nothing)"
    )
    return 0


def cmd_escrow_shares(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    """D-894: split a TPM box's unsealed KEK into escrow shares on removable media (``tools/key_escrow.py``)."""
    from tb_common import rc1_refusals

    try:  # R22-34 (D-1072): rc1 holds no key ceremony on a PRODUCTION box (the stricter of the box and the caller)
        rc1_refusals.check("key_ceremonies", rc1_refusals.host_env(Path(DEFAULT_DEPLOY), env))
    except rc1_refusals.Rc1Refused as exc:
        _err(exc.say())
        return 1
    from tools import key_escrow as ke

    sec = secrets_dir(a.secrets, env)
    meta = K.read_meta(sec)
    if meta is None:
        raise K.KekError(f"{sec} has no KEK ({K.META_FILE}): python -m tools.keys init first")
    if meta["backend"] != "file":
        why = {"shamir": "its steward shares are already the KEK's recovery copy",
               "passphrase": "a proof of concept or validation box; a site box uses the TPM or steward shares",
               "kms": "the hospital's KMS keeps the key that seals it"}.get(str(meta["backend"]), "")  # fmt: skip
        raise K.KekError(f"escrow shares are for a TPM-sealed KEK (back end file); this box's is {meta['backend']}: "
                         f"{why}")  # fmt: skip
    old = ke.current(meta)
    if old is not None and not ke.stale(meta):
        raise K.KekError(f"KEK {meta['kek_id']} already has escrow set {old['set_id']}: a second set puts more "
                         "shares of the same KEK about. A lost or doubtful set: rotate-kek --backend file ... "
                         "--escrow-out <media> (a new KEK, so the old shares open nothing)")  # fmt: skip
    names = ke.check(a.threshold, a.shares, a.custodian or [], Path(a.escrow_out) if a.escrow_out else None, sec)
    where = ke.audit_dir(env, a.audit_dir)
    kek = K.load_kek(sec, env)
    esc = ke.split(kek, a.threshold, names, Path(a.escrow_out))
    K.write_meta(sec, {**meta, "escrow": esc})
    ke.audit(where, ke.EVENT, ke.ACTOR, ke.summary(esc))
    for r in esc["shares"]:
        _say(f"escrow share {r['share']} of {r['of']} for {r['custodian']} written to {Path(a.escrow_out) / r['file']}"
             f" (fingerprint {r['fingerprint']}); the custodian takes it away")  # fmt: skip
    _say(
        f"escrow set {esc['set_id']} ({esc['threshold']} of {esc['count']}) recorded in {sec / K.META_FILE}; "
        "then python -m tools.keys ceremony-record lists it"
    )
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
    """With a rotation cut short (its journal) and the audit folder given, status finishes or rolls it back first
    under the folder's lock (the review of #1429, F4); without the folder it says so, as a problem."""
    sec = secrets_dir(a.secrets, env)
    given = getattr(a, "audit_dir", None) or env.get("TB_AUDIT_DIR")
    journal = (sec / JOURNAL).exists()
    if (journal and audit_chain_problem(Path(given) if given else None) is None) or (
        not journal and sec.is_dir() and _partial_writes(sec)
    ):
        with _Locked(sec), _HostLock(_journal_touches_credential(sec)):  # its roll-forward may swap it (LR-6)
            done = resume_rotation(sec, Path(str(given)) if given else None, "status")
        if done is not None:
            _err(done)
    c = K.custody(sec, env)
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


#: the audit events of every KEK rotation, on every box (the integrator's ruling 7114085298; first D-1092's, ruling
#: 7101844662, H96-04): who, when, the box, the environment and the two KEK ids, never a passphrase or a key. The
#: started event is written before anything changes, and a rotation whose started event cannot be written is refused
#: (the review of #1429, F1); the done event (``keys.rotate_kek``) after ``kek.json`` names the new KEK
ROTATE_EVENT = "keys.rotate_kek"
ROTATE_STARTED = "keys.rotate_kek_started"
ROTATE_STOPPED = "keys.rotate_kek_stopped"  # a rotation that failed before its commit, rolled back
ROTATE_ROLLED_BACK = "keys.rotate_kek_rolled_back"  # a rotation killed before its commit, rolled back later
ROTATE_ACTOR = "python -m tools.keys rotate-kek"
#: F4: the rotation's journal in the secrets folder (no key, no passphrase): "staging" until every new file is
#: written, "committing" from then until the done event; the next rotate-kek or status finishes or rolls it back
JOURNAL = K.ROTATION_JOURNAL
JOURNAL_FORMAT = "tb-kek-rotation/1"
#: LR-6: where seal_keys.sh puts a TPM box's sealed KEK, and what trialbox-unseal.service opens at every boot. A fixed
#: place, never one the environment names
CREDENTIAL_FILE = Path("/etc/credstore.encrypted") / K.CREDENTIAL
#: the folders the sealing tool is looked for in (never the caller's PATH)
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def _creds_tool() -> str | None:
    return shutil.which("systemd-creds", path=SYSTEM_PATH)


def _credential_present() -> bool | None:
    """Whether the TPM credential is there; None when this account cannot look in its folder."""
    try:
        return CREDENTIAL_FILE.exists()
    except OSError:
        return None


def _credential_kek() -> bytes:
    """The KEK the TPM credential opens to (held in memory, never written or printed)."""
    got = _creds(["decrypt", f"--name={K.CREDENTIAL}", str(CREDENTIAL_FILE), "-"], b"")
    if got.returncode != 0 or len(got.stdout) != K.KEK_LEN:
        last = (got.stderr.decode(errors="replace").strip().splitlines() or ["no output"])[-1]
        raise K.KekError(f"{CREDENTIAL_FILE} cannot be opened on this board (systemd-creds: {last[:300]}): if it "
                         "is an old board's, move it aside yourself, then run this again; nothing was "
                         "changed")  # fmt: skip
    return got.stdout


def _seal_here(a: argparse.Namespace, old: bytes) -> bool:
    """LR-6: whether this rotation seals its new KEK to the TPM. Only when the credential opens to this secrets
    folder's KEK now (or none is there and --seal-tpm asks for one): a credential sealing another KEK, another
    folder's or another box's, is never replaced. Read only."""
    if a.backend != "file" or getattr(a, "no_tpm", False):  # --no-tpm: no credential is looked for or sealed
        return False
    present = _credential_present()
    if not present:
        return bool(getattr(a, "seal_tpm", False))
    if hmac.compare_digest(_credential_kek(), old):
        return True
    if getattr(a, "seal_tpm", False):
        raise K.KekError(f"{CREDENTIAL_FILE} seals another KEK than this secrets folder's: it is not replaced; "
                         "nothing was changed")  # fmt: skip
    _say(f"{CREDENTIAL_FILE} seals another KEK than this secrets folder's: it is left as it is")
    return False


def _cred_next() -> Path:
    return CREDENTIAL_FILE.with_name(CREDENTIAL_FILE.name + ".next")


def _creds(argv: list[str], data: bytes) -> subprocess.CompletedProcess[bytes]:
    tool = _creds_tool()
    if tool is None:
        raise K.KekError("systemd-creds is not on this host: the new KEK cannot be sealed to the TPM")
    return subprocess.run([tool, *argv], input=data, capture_output=True, check=False, timeout=120,
                          env={"PATH": SYSTEM_PATH}, cwd="/")  # fmt: skip


def seal_to_tpm(kek: bytes) -> None:
    """LR-6: the new KEK sealed to this board's TPM beside the credential (``trialbox-kek.next``), written whole and
    opened again before the rotation's commit. The credential itself is swapped only by the roll-forward."""
    got = _creds(["encrypt", "--with-key=host+tpm2", f"--name={K.CREDENTIAL}", "-", "-"], kek)
    if got.returncode != 0 or not got.stdout:
        last = (got.stderr.decode(errors="replace").strip().splitlines() or ["no output"])[-1]
        raise K.KekError(f"the TPM could not seal the new KEK (systemd-creds: {last[:300]})")
    CREDENTIAL_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    K._write_private(_cred_next(), got.stdout)
    back = _creds(["decrypt", f"--name={K.CREDENTIAL}", str(_cred_next()), "-"], b"")
    if back.returncode != 0 or back.stdout != kek:
        _cred_next().unlink(missing_ok=True)
        raise K.KekError(f"the new KEK sealed to the TPM does not open again from {_cred_next()}")
    _fsync_dir(CREDENTIAL_FILE.parent)


def _cred_leftovers() -> list[Path]:
    """The sealed new KEK a rotation staged and its write's temporary file (never the credential itself)."""
    folder = CREDENTIAL_FILE.parent
    if not folder.is_dir():
        return []
    return sorted({_cred_next(), *folder.glob(f".{_cred_next().name}.*.tmp")})


def write_runtime_kek(out: Path, kek: bytes, sec: Path) -> None:
    """LR-4: the unsealed KEK for the services. Run as root for a secrets folder another account owns, the file is that
    account's before it takes its name, and a folder made for it here (``/run/trialbox`` after a restart) is that
    account's too, mode 0700. A folder that is there already keeps its owner."""
    owner = K.services_owner(sec)
    folder = out.parent
    if not folder.exists():
        folder.parent.mkdir(parents=True, exist_ok=True)
        made = False
        with contextlib.suppress(FileExistsError):
            folder.mkdir(mode=0o700)
            made = True
        if made and owner is not None:
            os.chown(folder, *owner, follow_symlinks=False)
    K._write_private(out, kek, owner)


def exposed_passphrase_rotation(a: argparse.Namespace, sec: Path) -> bool:
    """D-1092: the one rotate-kek rc1 lets through on a PRODUCTION box. A box sealed under a passphrase rotates that
    passphrase (a leaked key rotated is a safety action, not a ceremony): to a new passphrase (``--backend
    passphrase``) given by H-96's file or stdin form only, with no escrow set. Any other rotate-kek stays refused."""
    if a.backend != "passphrase" or a.escrow_out:
        return False
    if not (getattr(a, "new_passphrase_file", None) or getattr(a, "new_passphrase_stdin", False)):
        return False
    try:
        meta = K.read_meta(sec)
    except K.KekError:
        return False
    return meta is not None and meta.get("backend") == "passphrase"


def _who() -> dict[str, Any]:
    """Who ran it: the user it runs as and the kernel's login uid (the person behind sudo), never a variable the
    caller sets."""
    import pwd

    def name(uid: int) -> str:
        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:
            return str(uid)

    euid = os.geteuid()
    who: dict[str, Any] = {"user": name(euid), "uid": euid}
    try:
        login = int(Path("/proc/self/loginuid").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        login = -1
    if 0 <= login < 0xFFFFFFFF:  # 4294967295: no login session (a service)
        who.update(login_user=name(login), login_uid=login)
    return who


def audit_chain_problem(where: Path | None) -> str | None:
    """F3: the audit folder must hold the box's chain (its head anchor, ``HEAD.json``), not be any folder."""
    from tb_common.audit import HEAD, read_head

    if where is None or not where.is_dir():
        return "give the audit folder (--audit-dir, TB_AUDIT_DIR)"
    try:
        head = read_head(where)
    except (OSError, ValueError, UnicodeDecodeError):
        head = None
    if not isinstance(head, dict) or not isinstance(head.get("lines"), int) or not isinstance(head.get("hash"), str):
        return f"{where} holds no audit chain ({HEAD}): give the box's audit folder (--audit-dir, TB_AUDIT_DIR)"
    return None


def _is_root() -> bool:
    return os.geteuid() == 0


def _audit_owner(where: Path) -> tuple[int, int]:
    st = where.stat()
    return st.st_uid, st.st_gid


#: the child that appends as the audit folder's owner: the event's name and detail come on stdin, never on argv
_APPEND_CHILD = (
    "import json, sys; d = json.load(sys.stdin); sys.path[:0] = d['path']; from pathlib import Path; "
    "from tools import key_escrow as ke; ke.audit(Path(d['where']), d['event'], d['actor'], d['detail'])"
)


def _run_append(argv: list[str], data: str, uid: int, gid: int) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in PASSPHRASE_VARS}
    if (uid, gid) == (os.getuid(), os.getgid()):  # already that user: nothing to take on
        return subprocess.run(argv, input=data, capture_output=True, text=True, env=env, cwd="/", check=False,
                              timeout=120)  # fmt: skip
    return subprocess.run(argv, input=data, capture_output=True, text=True, env=env, cwd="/", check=False,
                          user=uid, group=gid, extra_groups=[], timeout=120)  # fmt: skip


def append_audit(where: Path, event: str, detail: Mapping[str, Any]) -> None:
    """F2: run as root against a folder another user owns (the console's audit volume, uid 10001), the append is
    made by that user in a child process, so a day file or lock it creates is that user's and the console can still
    append to it. Raises OSError when the append fails."""
    from tools import key_escrow as ke

    uid, gid = _audit_owner(where)
    if not _is_root() or uid == 0:
        ke.audit(where, event, ROTATE_ACTOR, detail)
        return
    path = [str(Path(p).resolve()) for p in sys.path if p]
    data = json.dumps({"where": str(where.resolve()), "event": event, "actor": ROTATE_ACTOR, "detail": dict(detail),
                       "path": path})  # fmt: skip
    try:
        got = _run_append([sys.executable, "-I", "-c", _APPEND_CHILD], data, uid, gid)
    except (OSError, subprocess.SubprocessError) as e:
        raise OSError(f"the append as uid {uid} could not run: {type(e).__name__}") from None
    if got.returncode != 0:
        last = (got.stderr.strip().splitlines() or ["the writer stopped"])[-1]
        raise OSError(f"the append as uid {uid} failed: {last[:300]}")


class _Locked:
    """F5: one key command at a time on a secrets folder, an exclusive lock on the folder itself (no file is added)."""

    def __init__(self, sec: Path) -> None:
        import fcntl

        self.fd = os.open(sec, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(self.fd)
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise K.KekError(f"another key command holds {sec} (a rotation running): wait for it, then run this "
                                 "again; nothing was changed") from None  # fmt: skip
            raise

    def __enter__(self) -> _Locked:
        return self

    def __exit__(self, *_: object) -> None:
        os.close(self.fd)  # closing the descriptor releases the lock


class _HostLock:
    """LR-6 (with #1457's 1457-1): the TPM credential is the host's, not one secrets folder's. The lock seal_keys.sh
    takes (an exclusive flock on the credential's folder) is held while a rotation reads, stages or swaps the
    credential, so a seal for another secrets folder never writes it at the same time. Taken after the secrets
    folder's lock, as seal_keys.sh does. An account that cannot open the folder cannot write the credential either:
    nothing to hold. Taken only by a rotation that touches the credential (``needed``), so no other rotation waits
    on the host's."""

    def __init__(self, needed: bool) -> None:
        import fcntl

        self.fd: int | None = None
        if not needed:
            return
        folder = CREDENTIAL_FILE.parent
        try:
            fd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except (FileNotFoundError, PermissionError):
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise K.KekError(f"another run of seal_keys.sh or a rotation holds {folder} (the TPM credential): let "
                                 "it finish, then run this again; nothing was changed") from None  # fmt: skip
            raise
        self.fd = fd

    def __enter__(self) -> _HostLock:
        return self

    def __exit__(self, *_: object) -> None:
        if self.fd is not None:
            os.close(self.fd)


def _journal_touches_credential(sec: Path) -> bool:
    """Whether a rotation cut short staged a new KEK beside the TPM credential (its journal says so)."""
    try:
        doc = _read_journal(sec)
    except K.KekError:
        return False
    return bool(doc and doc.get("credential"))


def _fsync_dir(sec: Path) -> None:
    fd = os.open(sec, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _staged(sec: Path, name: str) -> tuple[Path, Path]:
    final = K.wrapped_path(sec / name)
    return final.with_name(final.name + ".next"), final


def _write_journal(sec: Path, doc: Mapping[str, Any]) -> None:
    K._write_private(sec / JOURNAL, (json.dumps({"format": JOURNAL_FORMAT, **doc}, indent=1, sort_keys=True) +
                                     "\n").encode())  # fmt: skip
    _fsync_dir(sec)


def _read_journal(sec: Path) -> dict[str, Any] | None:
    path = sec / JOURNAL
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise K.KekError(f"{path} cannot be read ({type(e).__name__}): see RUNBOOK §23, a rotation cut short") from None
    if (
        not isinstance(doc, dict)
        or doc.get("format") != JOURNAL_FORMAT
        or doc.get("step") not in ("staging", "committing")
    ):
        raise K.KekError(f"{path} is not a rotation journal: see RUNBOOK §23, a rotation cut short")
    return doc


def _partial_writes(sec: Path) -> list[Path]:
    """The temporary files a rotation's write cut short leaves (``K._write_private``: ``.<name>.<hex>.tmp``): a
    staged file's, ``kek.json.next``'s or the journal's; never a key the box opens with."""
    return sorted({*sec.glob(".*.next.*.tmp"), *sec.glob(f".{JOURNAL}.*.tmp")})


def _roll_back(sec: Path, doc: Mapping[str, Any]) -> None:
    """Before the commit nothing the box opens with has changed: the staged files are removed."""
    for name in doc.get("keys", []):
        _staged(sec, str(name))[0].unlink(missing_ok=True)
    (sec / (K.META_FILE + ".next")).unlink(missing_ok=True)
    for f in _partial_writes(sec):
        f.unlink(missing_ok=True)
    if doc.get("credential"):  # LR-6: the new KEK sealed beside the credential; the credential is as it was
        for f in _cred_leftovers():
            f.unlink(missing_ok=True)


def _roll_forward(sec: Path, doc: Mapping[str, Any]) -> None:
    """After the commit every new file is whole: the renames not yet made are made, ``kek.json`` last. LR-6: on a TPM
    box the credential first, so at every instant each key is either as it was or opens with the KEK sealed in the
    credential (a boot in between is refused by kek.json's name until this finishes; no key is lost)."""
    if doc.get("credential") and _cred_next().exists():
        os.replace(_cred_next(), CREDENTIAL_FILE)
        _fsync_dir(CREDENTIAL_FILE.parent)
    for name in doc.get("keys", []):
        nxt, final = _staged(sec, str(name))
        if nxt.exists():
            os.replace(nxt, final)
    meta_next = sec / (K.META_FILE + ".next")
    if meta_next.exists():
        os.replace(meta_next, sec / K.META_FILE)
    meta = K.read_meta(sec) or {}
    if meta.get("kek_id") != doc.get("new_kek_id"):
        raise K.KekError(f"{K.META_FILE} names KEK {meta.get('kek_id')}, the journal {doc.get('new_kek_id')}: see "
                         "RUNBOOK §23, a rotation cut short")  # fmt: skip
    for f in _partial_writes(sec):
        f.unlink(missing_ok=True)
    _fsync_dir(sec)


def resume_rotation(sec: Path, where_audit: Path | None, by: str) -> str | None:
    """F4: a rotation cut short (a kill, a power cut) is finished (its journal says "committing") or rolled back
    ("staging"), and the audit chain says which. Returns what was done, or None without a journal. Called under the
    folder's lock. Without the audit folder nothing is done: the rotation's end is an audit event too."""
    doc = _read_journal(sec)
    if doc is None:  # killed while the journal was first written: nothing else was, and no event
        partial = _partial_writes(sec)
        for f in partial:
            f.unlink(missing_ok=True)
        return f"a rotation killed before it began left {len(partial)} temporary file(s): removed" if partial else None
    problem = audit_chain_problem(where_audit)
    if problem is not None:
        raise K.KekError(f"a KEK rotation was cut short ({JOURNAL}, step {doc['step']}); finishing it is an audit "
                         f"event: {problem}")  # fmt: skip
    assert where_audit is not None
    detail = {k: doc.get(k) for k in ("started_at", "old_kek_id", "new_kek_id", "backend", "box", "environment",
                                      "rule")}  # fmt: skip
    detail.update(at=_now(), who=_who(), by=by, resumed=True)
    if doc["step"] == "staging":
        _roll_back(sec, doc)
        append_audit(where_audit, ROTATE_ROLLED_BACK, detail)
        (sec / JOURNAL).unlink()
        _fsync_dir(sec)
        return f"a KEK rotation cut short before its commit was rolled back: KEK {doc.get('old_kek_id')} stands"
    _roll_forward(sec, doc)
    append_audit(where_audit, ROTATE_EVENT, detail)
    (sec / JOURNAL).unlink()
    _fsync_dir(sec)
    return (f"a KEK rotation cut short after its commit was finished: KEK {doc.get('new_kek_id')} replaces "
            f"{doc.get('old_kek_id')}; unseal again with the new KEK (python -m tools.keys unseal)")  # fmt: skip


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def cmd_rotate_kek(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    """A new KEK: every wrapped key is opened with the old one and re-wrapped. Under the secrets folder's lock (F5):
    a started event (F1), the journal, the new files written beside the old (``.next``), the journal's commit, the
    renames (key files first, ``kek.json`` last), the done event, and the journal removed (F4)."""
    import socket

    from tb_common import rc1_refusals

    from tools import key_escrow as ke

    sec = secrets_dir(a.secrets, env)
    box_env = rc1_refusals.host_env(Path(DEFAULT_DEPLOY), env)
    given = a.audit_dir or env.get("TB_AUDIT_DIR")
    where_audit = Path(given) if given else None
    rule = "7114085298"  # every rotation is an audit event, on every box
    try:  # R22-34 (D-1072): rc1 holds no key ceremony on a PRODUCTION box (the stricter of the box and the caller)
        rc1_refusals.check("key_ceremonies", box_env)
    except rc1_refusals.Rc1Refused as exc:
        if not exposed_passphrase_rotation(a, sec):
            _err(exc.say())
            return 1
        rule = "D-1092"  # an exposed passphrase is rotated there; the rest of rc1's refusals stand
        problem = audit_chain_problem(where_audit)
        if problem is not None:
            raise K.KekError(
                f"on a {exc.environment} box rc1 lets rotate-kek through only to rotate an exposed "
                f"passphrase, as an audit event (D-1092): {problem}; nothing was changed"
            ) from None
    pending = sorted(f.name for f in sec.glob("*.next.key" + K.WRAPPED_SUFFIX))
    if pending:  # a key rotation cut short (audit_sign.next.key): its staged key would stay under the old KEK
        raise K.KekError(f"{', '.join(pending)} is a key rotation not finished: finish it (run it again), then "
                         f"rotate-kek")  # fmt: skip
    names: list[str] = []
    if a.escrow_out:  # the split is checked before anything (read only)
        if a.backend != "file":
            raise K.KekError("--escrow-out is for a TPM-sealed KEK (--backend file)")
        names = ke.check(a.escrow_threshold, a.escrow_shares, a.custodian or [], Path(a.escrow_out), sec)
    problem = audit_chain_problem(where_audit)
    if problem is not None:  # the integrator's ruling 7114085298; F3: the box's chain, not any folder
        raise K.KekError(f"a KEK rotation is an audit event on every box: {problem}; nothing was changed")
    # LR-6: a box whose KEK is sealed by the TPM (or a new board, --seal-tpm) gets the new KEK sealed there too;
    # whether the credential is this folder's is read under the lock, once the old KEK is open
    # Review of #1478 (1478-2): no TPM credential may be assumed but by --no-tpm, and an account that cannot look for
    # one is refused, never told "done" with the credential left on the old KEK
    no_tpm = bool(getattr(a, "no_tpm", False))
    if no_tpm and a.backend != "file":
        raise K.KekError("--no-tpm is for the file back end")
    if no_tpm and getattr(a, "seal_tpm", False):
        raise K.KekError("--no-tpm and --seal-tpm: give one; nothing was changed")
    if a.backend == "file":
        present = _credential_present()
        if no_tpm and present:
            raise K.KekError(f"{CREDENTIAL_FILE} is there: this box's KEK may be sealed to the TPM, so --no-tpm is "
                             "refused; nothing was changed")  # fmt: skip
        if present is None and not no_tpm:
            raise K.KekError(f"{CREDENTIAL_FILE.parent} cannot be looked in by this account, so whether this box's "
                             "KEK is sealed to the TPM there is unknown: run rotate-kek as root (sudo python -m "
                             "tools.keys rotate-kek ...); on a box with no TPM credential, give --no-tpm. Nothing was "
                             "changed")  # fmt: skip
        if not no_tpm and (present or getattr(a, "seal_tpm", False)) and _creds_tool() is None:
            raise K.KekError(f"{CREDENTIAL_FILE} is there or asked for, and systemd-creds is not on this host to "
                             "seal the new KEK: the boot would open the old KEK only; nothing was changed")  # fmt: skip
    assert where_audit is not None
    if getattr(a, "seal_tpm", False):  # a new board: the credential's folder, so its lock can be taken
        CREDENTIAL_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    touches = (
        a.backend == "file" and not no_tpm and (bool(_credential_present()) or bool(getattr(a, "seal_tpm", False)))
    ) or _journal_touches_credential(sec)
    with _Locked(sec), _HostLock(touches):
        done = resume_rotation(sec, where_audit, "rotate-kek")
        if done is not None:
            _say(done)
            _say("run rotate-kek again for a new rotation")
            return 0
        # LR-7: a key another rotation staged (``rotate pid_map`` cut short after its database commit) is the only copy
        # of the key its rows are under; this rotation's staged files take the same name. Without a journal of ours
        # any staged key is that rotation's
        staged = sorted(f.name for f in sec.glob("*" + K.WRAPPED_SUFFIX + ".next"))
        if staged:
            raise K.KekError(f"{', '.join(staged)} is a key a rotation cut short staged (rotate pid_map): finish it "
                             "(python -m tools.keys rotate pid_map, run again), then rotate-kek; nothing was "
                             "changed")  # fmt: skip
        box_name = rc1_refusals.environment(box_env)
        return _rotate_kek_locked(a, env, sec, where_audit, rule, box_name, socket.gethostname(), names)


def _rotate_kek_locked(a: argparse.Namespace, env: Mapping[str, str], sec: Path, where_audit: Path, rule: str,
                       box_env: str, box: str, names: list[str]) -> int:  # fmt: skip
    from tools import key_escrow as ke

    where = ke.audit_dir(env, a.audit_dir) if a.escrow_out else None
    old_meta = K.read_meta(sec)
    old = K.load_kek(sec, env)
    seal = _seal_here(a, old)
    keys = {n: K.unwrap(old, K.read_wrapped(sec / n), n) for n in K.PROTECTED if K.wrapped_path(sec / n).exists()}
    # who, when, the box, the environment; never a value
    base = {"started_at": _now(), "box": box, "environment": box_env, "old_kek_id": (old_meta or {}).get("kek_id", ""),
            "backend": a.backend, "rule": rule}  # fmt: skip
    journal = {**base, "step": "staging", "keys": sorted(keys), "credential": seal}
    _write_journal(sec, journal)  # first, so a kill after the started event is rolled back and said so
    try:  # F1: the started event before anything changes; without it, no rotation
        append_audit(where_audit, ROTATE_STARTED, {**base, "at": base["started_at"], "who": _who()})
    except OSError as e:
        (sec / JOURNAL).unlink(missing_ok=True)
        _err(f"the rotation's started event could not be written to {where_audit} ({e}): nothing was changed, the "
             f"KEK is not rotated")  # fmt: skip
        return 1
    try:
        new, meta = new_kek(a, sec, env, "TB_KEK_NEW_PASSPHRASE", old=(old, old_meta))
        if journal["credential"]:
            seal_to_tpm(new)
        old_esc = ke.current(old_meta)
        if a.escrow_out:
            meta["escrow"] = ke.split(new, a.escrow_threshold, names, Path(a.escrow_out))
        elif old_esc is not None and a.backend == "file":
            meta["escrow"] = old_esc  # kept so doctor can say it is of the old KEK; its shares open the old KEK only
        for name, key in keys.items():
            doc = json.dumps(K.wrap(new, key, name), indent=1, sort_keys=True) + "\n"
            K._write_private(_staged(sec, name)[0], doc.encode(), K.services_owner(sec))  # LR-3
        K.write_meta(sec, meta, suffix=".next")
        _write_journal(sec, {**journal, "step": "committing", "new_kek_id": meta["kek_id"]})  # the commit
    except BaseException:  # before the commit: nothing the box opens with has changed
        _roll_back(sec, journal)
        (sec / JOURNAL).unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            append_audit(where_audit, ROTATE_STOPPED, {**base, "at": _now(), "who": _who()})
        raise
    journal = {**journal, "step": "committing", "new_kek_id": meta["kek_id"]}
    try:
        _roll_forward(sec, journal)
    except OSError as e:
        _err(f"the rotation stopped after its commit ({type(e).__name__}): python -m tools.keys status --audit-dir "
             f"{where_audit} finishes it (RUNBOOK §23, a rotation cut short)")  # fmt: skip
        return 1
    runtime = runtime_kek_path(a.out, env)
    if runtime.exists() and not K._inside(runtime, sec):
        write_runtime_kek(runtime, new, sec)  # LR-3: the services' still
        _say(f"the unsealed KEK in {runtime} is now the new one")
    if journal["credential"]:
        _say(f"the new KEK is sealed to this board's TPM in {CREDENTIAL_FILE}: trialbox-unseal.service opens it at the "
             f"next boot")  # fmt: skip
    _say(f"KEK {meta['kek_id']} (back end {meta['backend']}) replaces the old one; {len(keys)} key(s) re-wrapped")
    detail = {**base, "at": _now(), "who": _who(), "new_kek_id": meta["kek_id"], "backend": meta["backend"]}
    try:
        append_audit(where_audit, ROTATE_EVENT, detail)
    except OSError as e:  # the journal stays: status --audit-dir writes the done event when the folder takes it
        _err(f"the KEK is rotated, but its done event could not be written to {where_audit} ({e}): python -m "
             f"tools.keys status --audit-dir {where_audit} writes it (RUNBOOK §23, a rotation cut short)")  # fmt: skip
        return 1
    (sec / JOURNAL).unlink()
    _fsync_dir(sec)
    _say(
        f"audit: {ROTATE_EVENT} in {where_audit} (started and done)"
        + (" (rc1 lets this rotation through, D-1092)" if rule == "D-1092" else "")
    )
    if "escrow" in meta and meta["escrow"]["kek_id"] == meta["kek_id"] and where is not None:
        ke.audit(where, ke.EVENT, ke.ACTOR, ke.summary(meta["escrow"]))
        for r in meta["escrow"]["shares"]:
            _say(f"escrow share {r['share']} of {r['of']} for {r['custodian']} written to "
                 f"{Path(a.escrow_out) / r['file']} (fingerprint {r['fingerprint']})")  # fmt: skip
    elif old_esc is not None:
        _say(
            f"WARNING: escrow set {old_esc['set_id']} opens the old KEK only: make a new set now "
            "(python -m tools.keys escrow-shares), then a new ceremony record"
        )
    return 0


def cmd_rotate(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    if a.key == "pid_map":  # the pid map's key: a key ceremony (the integrator's ruling 7082962352)
        from tb_common import rc1_refusals

        try:  # R22-34 (D-1072): rc1 holds no key ceremony on a PRODUCTION box (the stricter of the box and the caller)
            rc1_refusals.check("key_ceremonies", rc1_refusals.host_env(Path(DEFAULT_DEPLOY), env))
        except rc1_refusals.Rc1Refused as exc:
            _err(exc.say())
            return 1

    if a.key != "pid_map":
        name = {"site_hmac": "site_hmac.key", "totp": "totp.key", "backup": "backup key pair"}[a.key]
        row = next(r for r in INVENTORY if r["key"] == name)
        _err(f"{row['key']} is not rotated by this tool. Rule: {row['rotation']}. How: {row['code'] or 'procedure'}")
        return 2
    url = a.db_url or env.get("TB_DB_URL")
    if not url:
        raise K.KekError("TB_DB_URL is needed: the pid map rows are in the trial database")
    sec = secrets_dir(a.secrets, env)
    with _Locked(sec):  # LR-7: never beside a KEK rotation, whose staged files take the same names
        if (sec / JOURNAL).exists():
            raise K.KekError(f"a KEK rotation was cut short ({JOURNAL}): python -m tools.keys status --audit-dir DIR "
                             "finishes it or rolls it back, then rotate pid_map; nothing was changed")  # fmt: skip
        return _rotate_pid_map_locked(sec, url, env)


def _rotate_pid_map_locked(sec: Path, url: str, env: Mapping[str, str]) -> int:
    path = sec / "pid_map.key"
    owner = K.services_owner(sec)  # LR-3: the services read the key
    wrapped = K.wrapped_path(path).exists()
    kek = K.load_kek(sec, env) if wrapped else None
    nxt = K.wrapped_path(path).with_name(K.wrapped_path(path).name + ".next") if wrapped else path.with_name(
        path.name + ".next")  # fmt: skip
    if nxt.exists():  # an interrupted rotation: finish it with the key it staged
        new = K.unwrap(kek, json.loads(nxt.read_text(encoding="utf-8")), path.name) if kek else nxt.read_bytes()
    else:
        new = os.urandom(32)
        data = (json.dumps(K.wrap(kek, new, path.name), indent=1, sort_keys=True) + "\n").encode() if kek else new
        K._write_private(nxt, data, owner)
    from adapter.pidmap import PidMap

    pm = PidMap(path, url)
    try:
        moved = pm.rekey(new)
    finally:
        pm.close()
    os.replace(nxt, K.wrapped_path(path) if wrapped else path)
    _fsync_dir(sec)
    _say(f"pid_map.key rotated (fingerprint {K.fingerprint(new)}); {moved} row(s) re-encrypted")
    return 0


def cmd_ceremony_record(a: argparse.Namespace, env: Mapping[str, str]) -> int:
    """TB-SOP-03 (D-893): the key ceremony's record, fingerprints and names only (``tools/key_ceremony.py``)."""
    from tb_common import rc1_refusals

    try:  # R22-34 (D-1072): rc1 holds no key ceremony on a PRODUCTION box (the stricter of the box and the caller)
        rc1_refusals.check("key_ceremonies", rc1_refusals.host_env(Path(a.deploy), env))
    except rc1_refusals.Rc1Refused as exc:
        _err(exc.say())
        return 1
    from tools import key_ceremony as kc

    deploy = Path(a.deploy)
    rec = kc.build(secrets_dir(a.secrets, env), env, a.custodian or [], a.witness or "",
                   shares_dir=Path(a.shares_dir) if a.shares_dir else None,
                   backup_pub=Path(a.backup_pub) if a.backup_pub else kc.default_backup_pub(env, deploy))  # fmt: skip
    md = kc.write(deploy, rec)
    where = kc.audit(env, rec, Path(a.audit_dir) if a.audit_dir else None)
    _say(f"ceremony record written to {md} (and .json): print it, and each custodian and the witness sign it")
    _say(f"audit: {where}")
    if rec["not_a_site_ceremony"]:
        _say("note: the passphrase back end: a proof of concept or validation box, NOT a site's key ceremony")
    return 0


def objects_dir(arg: str | None, env: Mapping[str, str]) -> Path:
    """``--store``, else the path of ``TB_OBJECT_STORE`` (``fs:<path>``), else the compose volume on the host."""
    if arg:
        return Path(arg)
    spec = env.get("TB_OBJECT_STORE") or ""
    if spec.startswith("fs:") and spec[3:]:
        return Path(spec[3:])
    return Path(own_volume("objects-data"))


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
        p.add_argument("--kek-in", help="file: use this KEK, made and sealed already (seal_keys.sh, D-836)")
        p.add_argument("--kms-url", help="kms: the transit address, e.g. https://kms.hosp/v1/transit (TB_KMS_URL)")
        p.add_argument("--kms-key", help="kms: the name of the KMS key that seals the KEK (token: TB_KMS_TOKEN)")
        p.add_argument("--scrypt-n", type=int, help=argparse.SUPPRESS)  # tests: a cheaper scrypt

    def with_passphrase(p: argparse.ArgumentParser, new: bool = False) -> None:  # H-96: a file or stdin, never env
        p.add_argument("--passphrase-file", help="the passphrase: one line of a file only root can read (0600)")
        p.add_argument("--passphrase-stdin", action="store_true", help="the passphrase: one line on stdin")
        if new:
            p.add_argument("--new-passphrase-file", help="the new passphrase: one line of a file only root can read")
            p.add_argument(
                "--new-passphrase-stdin",
                action="store_true",
                help="the new passphrase: one line on stdin (after the old one's line, when both)",
            )
        p.add_argument("--keep-passphrase-files", action="store_true", help="keep the passphrase files once used")

    ini = with_secrets(sub.add_parser("init", help="make the KEK and wrap the site keys"))
    with_backend(ini)
    with_passphrase(ini)
    with_secrets(sub.add_parser("wrap", help="wrap every key still plain"))
    u = with_secrets(sub.add_parser("unseal", help="put the KEK in the runtime file"))
    u.add_argument("--share", action="append", help="a share file (repeat); else read from the terminal or stdin")
    u.add_argument("--from", dest="kek_in", help="file back end: the opened KEK file")
    u.add_argument("--out", help=f"the runtime KEK file (TB_KEK_FILE; default {K.DEFAULT_KEK_FILE})")
    u.add_argument("--witness", help="file back end, escrow shares: the witness's name (D-894)")
    u.add_argument("--audit-dir", help="escrow shares: the audit folder (TB_AUDIT_DIR)")
    u.add_argument("--deploy", default=DEFAULT_DEPLOY, help="escrow shares: the escrow-use record goes to deploy/site")
    with_passphrase(u)
    s = with_secrets(sub.add_parser("status", help="wrapped or plain, fingerprints, the KEK"))
    s.add_argument("--audit-dir", help="a rotation cut short: the audit folder to finish it in (TB_AUDIT_DIR)")
    s.add_argument("--json", action="store_true")
    c = with_secrets(sub.add_parser("check", help="exit 1 on a custody problem"))
    c.add_argument("--for-update", action="store_true", help="also refuse wrapped keys with no KEK unsealed")
    i = sub.add_parser("inventory", help="every key of the box (OPS-058)")
    i.add_argument("--json", action="store_true")
    r = with_secrets(sub.add_parser("rotate-kek", help="a new KEK; every wrapped key re-wrapped"))
    with_backend(r)
    r.add_argument("--out", help="the runtime KEK file to update (TB_KEK_FILE)")
    r.add_argument("--escrow-out", help="file: a new escrow set to this removable media folder (D-894)")
    r.add_argument("--escrow-threshold", type=int, default=2, help="escrow shares needed (default 2)")
    r.add_argument("--escrow-shares", type=int, default=3, help="escrow shares made (default 3)")
    r.add_argument("--custodian", action="append", help="an escrow custodian's name (repeat; share order)")
    r.add_argument("--audit-dir", help="the audit folder (TB_AUDIT_DIR)")
    r.add_argument("--seal-tpm", action="store_true",
                   help=f"file: seal the new KEK to this board's TPM ({CREDENTIAL_FILE}); a box that has that "
                        "credential always does (a new board opened from escrow: give it)")  # fmt: skip
    r.add_argument("--no-tpm", action="store_true",
                   help="file back end: this box has no TPM credential; the rotation does not look for one and "
                        "never seals one (refused together with --seal-tpm)")  # fmt: skip
    with_passphrase(r, new=True)
    k = with_secrets(sub.add_parser("rotate", help="rotate one key"))
    k.add_argument("key", choices=("pid_map", "site_hmac", "totp", "backup"))
    k.add_argument("--db-url", help="the trial database (TB_DB_URL)")
    o = with_secrets(sub.add_parser("seal-objects", help="seal uploads and outputs under objects.key (T-210c)"))
    o.add_argument("--store", help=f"the object store folder (TB_OBJECT_STORE; default {HOST_OBJECTS})")
    o.add_argument("--check", action="store_true", help="only report; exit 1 when not sealed or a file is plain")
    cr = with_secrets(sub.add_parser("ceremony-record", help="the key ceremony's record to sign (TB-SOP-03)"))
    cr.add_argument("--custodian", action="append", help="a custodian's name (repeat; share order for shamir)")
    cr.add_argument("--witness", help="the witness's name (not a custodian)")
    cr.add_argument("--shares-dir", help="shamir: the share files, read only for their fingerprints")
    cr.add_argument("--backup-pub", help="the box's backup public key (TB_BACKUP_PUBKEY; default deploy/secrets)")
    cr.add_argument("--deploy", default=DEFAULT_DEPLOY, help="the box's deploy folder: the record goes to deploy/site")
    cr.add_argument("--audit-dir", help="the audit folder (TB_AUDIT_DIR)")
    with_secrets(sub.add_parser("restic-key", help="the incremental backup's password, under the KEK (D-968)"))
    es = with_secrets(sub.add_parser("escrow-shares", help="the escrow copy of a TPM-sealed KEK (D-894)"))
    es.add_argument("--threshold", type=int, default=2, help="shares needed to open the KEK (default 2)")
    es.add_argument("--shares", type=int, default=3, help="shares made, one per custodian (default 3)")
    es.add_argument("--escrow-out", help="the mounted removable media folder for the share files")
    es.add_argument("--custodian", action="append", help="a custodian's name (repeat; share 1 to the first name)")
    es.add_argument("--audit-dir", help="the audit folder (TB_AUDIT_DIR)")
    return ap


COMMANDS = {"init": cmd_init, "wrap": cmd_wrap, "unseal": cmd_unseal, "status": cmd_status, "check": cmd_check,
            "inventory": cmd_inventory, "rotate-kek": cmd_rotate_kek, "rotate": cmd_rotate,
            "seal-objects": cmd_seal_objects, "ceremony-record": cmd_ceremony_record,
            "escrow-shares": cmd_escrow_shares, "restic-key": cmd_restic_key}  # fmt: skip


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    a = parser().parse_args(argv)
    env = os.environ if env is None else env
    refused = env_passphrase_refusal(env)
    if refused:  # H-96: every command, before anything is read or written
        _err(refused)
        return 2
    try:
        got, used = given_passphrases(a, env)
        rc = COMMANDS[a.cmd](a, {**env, **got} if got else env)
    except K.KekError as exc:
        _err(str(exc))
        return 1
    if rc == 0 and not getattr(a, "keep_passphrase_files", False):
        for path in used:  # the operator's files, once used
            Path(path).unlink(missing_ok=True)
            _say(f"the passphrase file {path} is removed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
