"""``trialbox secrets``: one token per service, generated at install, rotated with one command (D-128, D-138).

    sudo python3 -m tools.trialbox secrets init                  # install.sh runs this; safe to re-run
    sudo python3 -m tools.trialbox secrets status                # names, files, modes, ages: never a value
    sudo python3 -m tools.trialbox secrets rotate                # every token and the database passwords
    sudo python3 -m tools.trialbox secrets rotate --service orchestrator [--service console ...]
    sudo python3 -m tools.trialbox secrets rotate --service db   # the two database passwords only
    sudo python3 -m tools.trialbox secrets rotate --service model  # the on-box model servers' key only (D-437)

**Files** (all under ``deploy/secrets/services/``, the folder 0700, owned by root):

* ``<service>.token``: the token of one service, mode 0600, owned by the service's user in the container (uid
  10001, ``TB_SERVICE_UID``). ``deploy/docker-compose.secrets.yml`` mounts it into that service only, at
  ``/run/secrets/tb_service_token`` (``TB_SERVICE_TOKEN_FILE``).
* ``operator.token``: the administrator's token for scripts and ``curl`` on the host; never mounted into a container.
* ``public/tokens.json``: the sha256 of each token (``tb-service-tokens/1``), mounted read-only into every service
  (``TB_SERVICE_TOKENS``); the callers each service accepts are ``tb_common.service_auth.CALLERS``. A hash of a
  256-bit random token reveals nothing, so this file is not secret.
* ``actor-sign.key``: the key the console signs the signed-in user with (T-717, D-485): 32 random bytes, hex, mode
  0600, a compose secret of the console only (``TB_ACTOR_SIGN_KEY_FILE``). It is a secret of its own, not derived
  from the console's token (every service the console calls receives that token). ``rotate --service actor``
  makes a new one.
* ``actor/keys``: the same key (hex; the current one and, during a rotation of it, the previous one), mode 0600 in
  a 0700 folder, mounted into the orchestrator only (``TB_ACTOR_KEYS_FILE``), which verifies
  ``X-TB-Actor-Assertion`` with it (review 2026-11-09 S-09, D-143).

**The model key** (T-212b, D-437; review LLM-039): the key of the on-box model servers (D-177) is
``deploy/secrets/model/llm.key`` (0600, the service user, in a 0700 folder), made by ``init`` (from the
``TB_LLM_API_KEY`` that install.sh or an older box put in ``deploy/.env``, else new). The secrets overlay mounts it
into the gateway and model-guard only, as a compose secret (``TB_LLM_API_KEY_FILE``). vLLM has no ``*_FILE``
setting, so the vLLM servers read ``deploy/secrets/model/vllm.env`` (``VLLM_API_KEY=<key>``, 0600), their own env
file in every compose file that defines them, written here with ``llm.key`` and rewritten from it when it is missing
or differs (T-212d, D-450). ``deploy/.env`` keeps a copy (``TB_LLM_API_KEY``) only for a box started without the
secrets overlay, where model-guard reads it; ``init`` and ``rotate`` keep it equal to the file, and a copy that
differs is refused (D-445). ``rotate --service model`` writes a new key and recreates the model servers,
model-guard and the gateway in one command: the old key is refused from then on.

The database passwords (``POSTGRES_PASSWORD`` for HAPI, ``POSTGRES_WF_PASSWORD``, ``TB_DB_PW_<SERVICE>`` and
``TB_DB_URL`` for the trial database) stay in ``deploy/.env`` (0600, root), which compose reads. The base compose
file clears every database password in every service but its own role's (T-712, D-481;
``tests/unit/test_compose_db_passwords.py``); the overlay clears the mail passwords, the cloud-model keys, the KEK
passphrase and the host tools' keys in every container that does not need them (D-450;
``tests/unit/test_compose_secret_reach.py``).

**Migration.** A box installed before step 8 has one shared ``TB_SERVICE_TOKEN`` in ``deploy/.env``. ``init`` keeps
it working: its hash goes into ``tokens.json`` as ``legacy`` (accepted from any caller, with a warning in the
service log). ``rotate`` of every token removes it from both files: from then on only per-service tokens work.

**Rotation** writes the new token, puts both the old and the new hash in ``tokens.json`` (callers re-read it when it
changes), recreates the rotated services so they read their new file, then drops the old hash. The restart command is
``docker compose --project-directory deploy up -d --no-deps --force-recreate --wait <services>`` (the compose files
come from ``COMPOSE_FILE`` in ``deploy/.env``, written by install.sh; ``TB_COMPOSE`` overrides the command). A
database rotation runs ``ALTER ROLE`` through ``psql`` in the ``db`` container with the password on standard input,
never on a command line, then recreates every service that reads ``deploy/.env``.

Nothing here prints, logs or returns a token or a password. Standard library only (runs with the host's python3).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shlex
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "tb-service-tokens/1"
# the TrialBox services in deploy/docker-compose.yml that call or are called with a token (llm-stub stands in for
# vLLM and has none); ``operator`` is the administrator on the host
SERVICES: tuple[str, ...] = (
    "lake",
    "embed-service",
    "doc-parser",
    "criteria-compiler",
    "adapter",
    "orchestrator",
    "mail-gateway",
    "gateway",
    "console",
)
OPERATOR = "operator"
IDENTITIES: tuple[str, ...] = (*SERVICES, OPERATOR)
DB = "db"
MODEL = "model"  # the on-box model servers' key (D-177, D-437): ``rotate --service model``
ACTOR = "actor"  # the console's key that signs people (T-717, D-485): ``rotate --service actor``
MODEL_KEY_ENV = "TB_LLM_API_KEY"
DB_USERS: tuple[str, ...] = (*SERVICES, "fhir-store")  # every service that reads deploy/.env's database settings
SERVICE_UID = 10001  # the ``tb`` user of trialbox-py / trialbox-jvm (deploy/docker/python.Dockerfile)


class SecretsError(RuntimeError):
    pass


def secrets_dir(deploy: Path) -> Path:
    return deploy / "secrets" / "services"


def token_path(deploy: Path, name: str) -> Path:
    return secrets_dir(deploy) / f"{name}.token"


def registry_path(deploy: Path) -> Path:
    return secrets_dir(deploy) / "public" / "tokens.json"


ACTOR_SIGNER = "console"  # the one service that names a signed-in user to the orchestrator
ACTOR_LABEL = b"tb-actor-assertion/1"  # tb_common.service_auth.ACTOR_LABEL


def actor_keys_path(deploy: Path) -> Path:
    return secrets_dir(deploy) / "actor" / "keys"


def model_key_path(deploy: Path) -> Path:
    return deploy / "secrets" / "model" / "llm.key"


def vllm_env_path(deploy: Path) -> Path:
    """The vLLM servers' env file (``VLLM_API_KEY``; T-212d, D-450): compose reads it, no service mounts it."""
    return deploy / "secrets" / "model" / "vllm.env"


def _vllm_env_write(deploy: Path, key: str) -> bool:
    """(Re)write the vLLM servers' env file from the key; True when it changed."""
    p = vllm_env_path(deploy)
    want = f"VLLM_API_KEY={key}\n"
    if p.is_file() and p.read_text(encoding="utf-8") == want:
        return False
    _write_private(p, want, None)  # read by compose (root), never by a TrialBox service
    return True


def _model_key_write(deploy: Path, env_file: Path, key: str, uid: int | None) -> None:
    folder = model_key_path(deploy).parent
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    if uid is not None and os.geteuid() == 0:
        os.chown(folder, uid, uid)
    _write_private(model_key_path(deploy), key + "\n", uid)  # the gateway and model-guard run as ``uid``
    _vllm_env_write(deploy, key)  # the vLLM servers' copy (D-450)
    if _read_env(env_file).get(MODEL_KEY_ENV) != key:
        _set_env(env_file, {MODEL_KEY_ENV: key})  # the vLLM servers' copy (compose interpolation), kept equal


def ensure_model_key(deploy: Path, env_file: Path | None = None, uid: int | None = SERVICE_UID) -> bool:
    """Make ``deploy/secrets/model/llm.key`` when it is missing: the key ``deploy/.env`` holds, else a new one (so
    the compose secret always has its file). An empty copy in ``deploy/.env`` is filled from the file. True when made
    now.

    A copy in ``deploy/.env`` that is set and differs from the file is refused (:class:`SecretsError`), never
    overwritten (T-608, D-445): someone changed one of them by hand, and silently undoing that would leave the vLLM
    servers (which read ``.env``) and the gateway (which reads the file) on different keys without a word."""
    env_file = env_file or deploy / ".env"
    p = model_key_path(deploy)
    cur = p.read_text(encoding="utf-8").strip() if p.is_file() else ""
    if cur:
        copy = (_read_env(env_file).get(MODEL_KEY_ENV) or "").strip()
        if copy and copy != cur:
            raise SecretsError(
                f"{MODEL_KEY_ENV} in {env_file} differs from {p}: one of them was changed by hand. Keep the key you "
                f"want in both (or run `trialbox secrets rotate --service model` to make a new one in both); "
                "nothing was changed"
            )
        if not copy:
            _set_env(env_file, {MODEL_KEY_ENV: cur})
        _vllm_env_write(deploy, cur)  # a box from before D-450, or a file lost: the servers' copy from the key file
        return False
    _model_key_write(deploy, env_file, _read_env(env_file).get(MODEL_KEY_ENV) or _new_token(), uid)
    return True


def _compose_files(deploy: Path, env_file: Path) -> list[Path]:
    """The compose files of this box (``COMPOSE_FILE`` in ``deploy/.env``, written by install.sh)."""
    env = _read_env(env_file)
    raw = env.get("COMPOSE_FILE") or "docker-compose.yml"
    sep = env.get("COMPOSE_PATH_SEPARATOR") or ":"
    return [deploy / f if not Path(f).is_absolute() else Path(f) for f in raw.split(sep) if f.strip()]


def model_services(deploy: Path, env_file: Path | None = None) -> list[str]:
    """The services that hold the model key, in restart order: the vLLM servers and model-guard (GPU boxes, the
    ``gpu`` compose profile; ``llm-verifier`` where a compose file of the box defines it), then the gateway."""
    env_file = env_file or deploy / ".env"
    profiles = (_read_env(env_file).get("COMPOSE_PROFILES") or "").replace(",", " ").split()
    out: list[str] = []
    if "gpu" in profiles:
        out.append("llm-service")
        files = [f for f in _compose_files(deploy, env_file) if f.is_file()]
        if any("\n  llm-verifier:" in f.read_text(encoding="utf-8") for f in files):
            out.append("llm-verifier")
        out.append("model-guard")
    return [*out, "gateway"]


def actor_key_hex(token: str) -> str:
    """The old actor key, a function of the console's token. T-717 (D-485): never written to the keys file again;
    kept so that a test can show it is refused."""
    return hmac.new(token.encode("utf-8"), ACTOR_LABEL, hashlib.sha256).hexdigest()


def actor_sign_key_path(deploy: Path) -> Path:
    """The console's signing key (hex, 32 bytes; 0600): a compose secret of the console only."""
    return secrets_dir(deploy) / "actor-sign.key"


def _actor_sign_key(deploy: Path) -> str:
    p = actor_sign_key_path(deploy)
    try:
        key = p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    try:  # what tb_common.service_auth accepts as a key: 32 bytes of hex, either case
        return key if len(bytes.fromhex(key)) == 32 else ""
    except ValueError:
        return ""


def ensure_actor_sign_key(deploy: Path, uid: int | None = SERVICE_UID) -> bool:
    """Make the console's signing key when the box has none, and the orchestrator's keys file from it. True when the
    key was made now. A random secret of its own: the console's token, which travels to every service the console
    calls, says nothing about it (T-717, D-485)."""
    made = not _actor_sign_key(deploy)
    if made:
        _write_private(actor_sign_key_path(deploy), secrets.token_hex(32) + "\n", uid)
    write_actor_keys(deploy, uid)
    return made


def write_actor_keys(deploy: Path, uid: int | None, previous: str | None = None) -> bool:
    """The orchestrator's verification key(s) for the console's actor assertions: the console's signing key; False
    when the box has none yet. ``previous``: the signing key before a rotation (hex), kept valid until the
    rotated console runs."""
    cur = _actor_sign_key(deploy)
    if not cur:
        return False
    keys = [cur]
    if previous and previous not in keys:
        keys.append(previous)
    folder = actor_keys_path(deploy).parent
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    if uid is not None and os.geteuid() == 0:
        os.chown(folder, uid, uid)
    _write_private(actor_keys_path(deploy), "\n".join(keys) + "\n", uid)  # the folder is mounted: a rename is seen
    return True


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _write_private(path: Path, text: str, uid: int | None) -> None:
    """Write ``path`` 0600 by rename (never a moment with wider permissions); chown to ``uid`` when root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    if uid is not None and os.geteuid() == 0:
        os.chown(tmp, uid, uid)
    os.replace(tmp, path)


def _write_public(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)  # the folder is mounted, not the file, so a rename is seen in the containers


def _read_env(env_file: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _set_env(env_file: Path, updates: dict[str, str | None]) -> None:
    """Set (or, with None, remove) keys in ``deploy/.env`` in place, keeping the rest; the file stays 0600."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    out, seen = [], set()
    for line in lines:
        key = line.partition("=")[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            seen.add(key)
            if updates[key] is not None:
                out.append(f"{key}={updates[key]}")
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if v is not None and k not in seen]
    from tools.trialbox.private_file import replace_private  # OCR 1455-5: the one writer of deploy/.env

    replace_private(env_file, "\n".join(out) + "\n")


def legacy_token(env_file: Path) -> str:
    tok = _read_env(env_file).get("TB_SERVICE_TOKEN", "")
    return "" if not tok or tok.startswith("change-me") else tok


def _load_registry(deploy: Path) -> dict[str, object]:
    p = registry_path(deploy)
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {"schema": SCHEMA, "services": {}}


def _registry(deploy: Path, extra_old: dict[str, str] | None, legacy: str | None) -> dict[str, object]:
    services: dict[str, object] = {}
    for name in IDENTITIES:
        p = token_path(deploy, name)
        if not p.is_file():
            continue
        cur = _sha(p.read_text(encoding="utf-8").strip())
        old = (extra_old or {}).get(name)
        services[name] = [cur, old] if old and old != cur else cur
    data: dict[str, object] = {"schema": SCHEMA, "services": services}
    if legacy:
        data["legacy"] = legacy
    return data


@dataclass
class Result:
    created: list[str]
    rotated: list[str]
    restarted: list[str]
    legacy_kept: bool


def init(deploy: Path, env_file: Path | None = None, uid: int | None = SERVICE_UID) -> Result:
    """Make every missing token and the registry; keep the old shared token (as ``legacy``) when the box has one."""
    env_file = env_file or deploy / ".env"
    d = secrets_dir(deploy)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    created = []
    for name in IDENTITIES:
        p = token_path(deploy, name)
        if not p.is_file() or not p.read_text(encoding="utf-8").strip():
            _write_private(p, _new_token() + "\n", None if name == OPERATOR else uid)
            created.append(name)
    old = _load_registry(deploy).get("legacy")
    legacy = _sha(legacy_token(env_file)) if legacy_token(env_file) else (old if isinstance(old, str) else None)
    _write_public(registry_path(deploy), _registry(deploy, None, legacy))
    if ensure_actor_sign_key(deploy, uid):
        created.append(ACTOR)
    if ensure_model_key(deploy, env_file, uid):
        created.append(MODEL)
    return Result(created, [], [], legacy is not None)


Runner = Callable[[Sequence[str], str | None], None]  # argv, standard input; raises on failure


def run_cmd(argv: Sequence[str], stdin: str | None) -> None:
    out = subprocess.run(list(argv), input=stdin, text=True, capture_output=True, check=False)
    if out.returncode != 0:
        # the output of compose and psql carries no secret (passwords travel on stdin only)
        raise SecretsError(f"{shlex.join(argv[:6])} ... failed ({out.returncode}): {out.stderr.strip()[-400:]}")


def compose_cmd(deploy: Path) -> list[str]:
    return shlex.split(os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}")


def restart(deploy: Path, services: Sequence[str], runner: Runner = run_cmd) -> None:
    if services:
        runner([*compose_cmd(deploy), "up", "-d", "--no-deps", "--force-recreate", "--wait", *services], None)


def _rotate_db(deploy: Path, env_file: Path, runner: Runner) -> list[str]:
    """New passwords for the two database roles: ALTER ROLE first (password on stdin), then deploy/.env."""
    env = _read_env(env_file)
    wf, hapi = _new_token(), _new_token()
    sql = f"ALTER ROLE trialbox PASSWORD '{wf}';\nALTER ROLE hapi PASSWORD '{hapi}';\n"
    runner([*compose_cmd(deploy), "exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-U", "hapi", "-d", "hapi"], sql)
    url = env.get("TB_DB_URL", "postgresql://trialbox:x@db:5432/trialbox_wf")
    scheme, _, rest = url.partition("://")
    host = rest.partition("@")[2] or "db:5432/trialbox_wf"
    _set_env(
        env_file,
        {"POSTGRES_PASSWORD": hapi, "POSTGRES_WF_PASSWORD": wf, "TB_DB_URL": f"{scheme}://trialbox:{wf}@{host}"},
    )
    return list(DB_USERS)


def rotate(
    deploy: Path,
    names: Sequence[str] = (),
    env_file: Path | None = None,
    runner: Runner = run_cmd,
    do_restart: bool = True,
    uid: int | None = SERVICE_UID,
) -> Result:
    """Rotate the named tokens (``db``: the database passwords); none named: every token and the database."""
    env_file = env_file or deploy / ".env"
    want = [*IDENTITIES, DB, MODEL, ACTOR] if not names else list(dict.fromkeys(names))
    every = set(IDENTITIES) <= set(want)  # every token rotated: the old shared one can go
    bad = [n for n in want if n not in IDENTITIES and n not in (DB, MODEL, ACTOR)]
    if bad:
        raise SecretsError(f"unknown service {', '.join(bad)}: one of {', '.join((*IDENTITIES, DB, MODEL, ACTOR))}")
    if not registry_path(deploy).is_file():
        init(deploy, env_file, uid)
    reg = _load_registry(deploy)
    raw_legacy = reg.get("legacy")
    legacy: str | None = raw_legacy if isinstance(raw_legacy, str) else None
    tokens = [n for n in want if n not in (DB, MODEL, ACTOR)]
    old = {
        n: _sha(token_path(deploy, n).read_text(encoding="utf-8").strip())
        for n in tokens
        if token_path(deploy, n).is_file()
    }
    # T-717 (D-485): the console's token and its signing key are two secrets; a token rotation leaves the key
    old_actor = _actor_sign_key(deploy) if ACTOR in want else ""
    for n in tokens:
        _write_private(token_path(deploy, n), _new_token() + "\n", None if n == OPERATOR else uid)
    # both hashes while the rotated services restart: a caller still holding its old token is not cut off
    _write_public(registry_path(deploy), _registry(deploy, old, legacy))
    affected = [n for n in tokens if n != OPERATOR]
    if ACTOR in want:  # a new signing key; the orchestrator verifies with the old and the new one meanwhile
        _write_private(actor_sign_key_path(deploy), secrets.token_hex(32) + "\n", uid)
        write_actor_keys(deploy, uid, old_actor or None)
        affected += [s for s in (ACTOR_SIGNER, "orchestrator") if s not in affected]
    if DB in want:
        affected += [s for s in _rotate_db(deploy, env_file, runner) if s not in affected]
    if MODEL in want:
        # T-212b (D-437, LLM-039): a new key in the file and in deploy/.env's copy, then the servers that hold it are
        # recreated together, so the old key is refused from then on
        _model_key_write(deploy, env_file, _new_token(), uid)
        affected += [s for s in model_services(deploy, env_file) if s not in affected]
    if do_restart:
        restart(deploy, affected, runner)
    if every:  # the end of the migration: the old shared token is gone from the registry and from deploy/.env
        legacy = None
        if "TB_SERVICE_TOKEN" in _read_env(env_file):
            _set_env(env_file, {"TB_SERVICE_TOKEN": None})
    _write_public(registry_path(deploy), _registry(deploy, None, legacy))
    if ACTOR in want:
        write_actor_keys(deploy, uid)
    return Result([], want, affected if do_restart else [], legacy is not None)


def status(deploy: Path, env_file: Path | None = None) -> list[dict[str, object]]:
    """One row per identity: file, mode, age, registered. Never a value."""
    env_file = env_file or deploy / ".env"
    reg = _load_registry(deploy)
    raw = reg.get("services")
    hashes: dict[str, object] = raw if isinstance(raw, dict) else {}
    rows: list[dict[str, object]] = []
    now = time.time()
    for name in IDENTITIES:
        p = token_path(deploy, name)
        row: dict[str, object] = {"name": name, "file": str(p), "present": p.is_file()}
        if p.is_file():
            st = p.stat()
            row.update(
                {
                    "mode": oct(st.st_mode & 0o777),
                    "age_days": round((now - st.st_mtime) / 86400, 1),
                    "registered": bool(hashes and name in hashes),
                }
            )
        rows.append(row)
    mk = model_key_path(deploy)
    row = {"name": "model key", "file": str(mk), "present": mk.is_file()}
    if mk.is_file():
        st = mk.stat()
        row.update({"mode": oct(st.st_mode & 0o777), "age_days": round((now - st.st_mtime) / 86400, 1)})
    rows.append(row)
    ak = actor_sign_key_path(deploy)  # T-717 (D-485): the console's signing key; without it nobody is signed
    row = {"name": "actor signing key", "file": str(ak), "present": bool(_actor_sign_key(deploy))}
    if ak.is_file():
        st = ak.stat()
        row.update({"mode": oct(st.st_mode & 0o777), "age_days": round((now - st.st_mtime) / 86400, 1)})
    rows.append(row)
    rows.append(
        {
            "name": "legacy shared token",
            "file": str(env_file),
            "present": bool(legacy_token(env_file)) or isinstance(reg.get("legacy"), str),
        }
    )
    return rows
