"""T-712 (D-481): which database password reaches which container.

D-378 gives every service its own PostgreSQL role. That means something only when a service's container holds its
own role's password and no other: not another service's, not the administrators' (``POSTGRES_PASSWORD``,
``POSTGRES_WF_PASSWORD``). Every TrialBox service reads ``deploy/.env`` through ``env_file``, so the compose files
must clear in each service what it must not hold. This module is the one check of that, used three ways:

* ``tests/unit/test_compose_db_passwords.py`` renders every compose file set of the tree with :func:`render` (pure
  Python: no ``docker`` needed, so the test cannot be skipped) and fails on a foreign password;
* ``trialbox doctor`` (check ``db_passwords``) renders the box's own compose files (``COMPOSE_FILE`` of
  ``deploy/.env``) with the box's values, and
* reads the environment of the containers that are running (:func:`running_config`), because a container started
  before a change keeps what it was given.

:func:`render` follows compose for the three things that decide a container's environment: the merge of several
files (a service's ``environment`` key by key, its ``env_file`` lists joined), the files of ``env_file``, and
``${NAME}`` interpolation with its ``:-``, ``-``, ``:?``, ``?``, ``:+`` and ``+`` forms. Where the ``docker compose``
plugin exists the test holds :func:`render` against ``docker compose config``.

No function here prints or returns a secret's value: findings name the variable and the service.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404: fixed argv, no shell
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

#: the names of the database passwords of a box (deploy/.env): one per service role and the two administrators
DB_SECRET = re.compile(r"^(TB_DB_PW_[A-Z0-9_]+|POSTGRES_PASSWORD|POSTGRES_WF_PASSWORD)$")
ADMIN = ("POSTGRES_PASSWORD", "POSTGRES_WF_PASSWORD")
#: who may hold an administrator password, and why. Everything else holds its own role's password only.
ADMIN_HOLDERS: dict[str, set[str]] = {
    "POSTGRES_PASSWORD": {"db", "fhir-store"},  # the server itself; HAPI's own database `hapi`
    # the server; `doctor` of the platform compose form is the operator's own one-shot tool (it reads the flags and
    # the site key record as the host's `trialbox doctor` does) and mounts no patient data
    "POSTGRES_WF_PASSWORD": {"db", "doctor"},
}
#: a value shorter than this is not searched for (it would be found by accident inside other values)
MIN_LEN = 8
ROLE_PREFIX = "TB_DB_PW_"


def role_secret(service: str) -> str:
    """The password name of a service's own role: ``mail-gateway`` -> ``TB_DB_PW_MAIL_GATEWAY``."""
    return ROLE_PREFIX + service.replace("-", "_").upper()


def may_hold(service: str, name: str) -> bool:
    if service == "db":  # the server makes the roles (docker/db-init/30-service-roles.sh)
        return True
    if name in ADMIN_HOLDERS:
        return service in ADMIN_HOLDERS[name]
    return name == role_secret(service)


# ---------------------------------------------------------------------------------------------- compose, rendered
class RenderError(ValueError):
    """A compose file set that cannot be rendered (a required variable is missing, a file is not a mapping)."""


def _find_close(text: str, start: int) -> int:
    """The index of the ``}`` that closes the ``${`` whose body starts at ``start``."""
    depth, i = 1, start
    while i < len(text):
        if text.startswith("${", i):
            depth, i = depth + 1, i + 2
            continue
        if text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise RenderError(f"unclosed ${{ in {text!r}")


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def interpolate(text: str, env: Mapping[str, str]) -> str:
    """``text`` with compose's variable forms replaced from ``env``."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != "$":
            out.append(text[i])
            i += 1
            continue
        if text.startswith("$$", i):
            out.append("$")
            i += 2
            continue
        if text.startswith("${", i):
            end = _find_close(text, i + 2)
            out.append(_braced(text[i + 2 : end], env))
            i = end + 1
            continue
        m = _NAME.match(text, i + 1)
        if m is None:
            out.append("$")
            i += 1
            continue
        out.append(env.get(m.group(0), ""))
        i = m.end()
    return "".join(out)


def _braced(body: str, env: Mapping[str, str]) -> str:
    m = _NAME.match(body)
    if m is None:
        raise RenderError(f"not a variable: ${{{body}}}")
    name, rest = m.group(0), body[m.end() :]
    value = env.get(name)
    if not rest:
        return value or ""
    for op in (":-", ":?", ":+", "-", "?", "+"):
        if rest.startswith(op):
            arg = rest[len(op) :]
            break
    else:
        raise RenderError(f"unknown form: ${{{body}}}")
    present = value is not None and (value != "" or len(op) == 1)  # the ':' forms treat an empty value as unset
    if op[-1] == "-":
        return (value or "") if present else interpolate(arg, env)
    if op[-1] == "?":
        if present:
            return value or ""
        raise RenderError(f"{name} is required: {interpolate(arg, env)}")
    return interpolate(arg, env) if present else ""


def _walk(node: Any, env: Mapping[str, str]) -> Any:
    if isinstance(node, str):
        return interpolate(node, env)
    if isinstance(node, dict):
        return {k: _walk(v, env) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, env) for v in node]
    return node


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _environment(node: Any) -> dict[str, str | None]:
    """A service's ``environment`` as a mapping (compose allows a mapping or a list of ``NAME=value``)."""
    if node is None:
        return {}
    if isinstance(node, dict):
        return {str(k): _scalar(v) for k, v in node.items()}
    out: dict[str, str | None] = {}
    for item in node:
        name, sep, value = str(item).partition("=")
        out[name] = value if sep else None
    return out


def read_env_file(path: Path) -> dict[str, str]:
    """``NAME=value`` lines of an env file (comments and blank lines skipped, one pair of quotes removed)."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[name.removeprefix("export ").strip()] = value
    return out


class _Tagged:
    """A node under compose's ``!reset`` (drop what the earlier files gave) or ``!override`` (replace it)."""

    def __init__(self, kind: str, value: Any) -> None:
        self.kind, self.value = kind, value


class _Loader(yaml.SafeLoader):
    """YAML as compose reads it: the two merge tags are kept, everything else is plain."""


def _tagged(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> _Tagged:
    if isinstance(node, yaml.MappingNode):
        return _Tagged(suffix, loader.construct_mapping(node, deep=True))
    if isinstance(node, yaml.SequenceNode):
        return _Tagged(suffix, loader.construct_sequence(node, deep=True))
    return _Tagged(suffix, loader.construct_scalar(node))  # type: ignore[arg-type]


_Loader.add_multi_constructor("!", _tagged)


def _untag(node: Any) -> tuple[bool, Any]:
    """(start again, the value): ``!reset`` gives (True, None), ``!override`` (True, value), plain (False, value)."""
    if isinstance(node, _Tagged):
        return True, (None if node.kind == "reset" else node.value)
    return False, node


def render(files: Sequence[Path], env: Mapping[str, str], project_dir: Path | None = None) -> dict[str, Any]:
    """The environment every service of the merged ``files`` would be started with, as ``docker compose config
    --format json`` shows it: ``{"services": {name: {"environment": {...}}}}``, services of every profile.

    ``env`` is what compose interpolates with (the project's ``.env`` and the caller's environment). ``env_file``
    paths are read from ``project_dir`` (default: the folder of the first file).
    """
    base = project_dir or files[0].parent
    merged: dict[str, dict[str, Any]] = {}
    for f in files:
        doc = yaml.load(f.read_text(encoding="utf-8"), Loader=_Loader) or {}  # nosec B506: a SafeLoader
        if not isinstance(doc, dict):
            raise RenderError(f"{f} is not a mapping")
        for name, tagged_body in (doc.get("services") or {}).items():
            again, body = _untag(tagged_body)
            if again:
                merged.pop(str(name), None)
            svc = merged.setdefault(str(name), {"environment": {}, "env_file": []})
            body = body or {}
            again, node = _untag(body.get("environment"))
            if again:
                svc["environment"] = {}
            svc["environment"].update(_environment(node))
            again, listed = _untag(body.get("env_file"))
            if again:
                svc["env_file"] = []
            listed = listed or []
            svc["env_file"] += [listed] if isinstance(listed, (str, dict)) else list(listed)
    out: dict[str, Any] = {}
    for name, svc in merged.items():
        got: dict[str, str] = {}
        for item in svc["env_file"]:
            path, required = (item.get("path"), item.get("required", True)) if isinstance(item, dict) else (item, True)
            p = Path(interpolate(str(path), env))
            p = p if p.is_absolute() else base / p
            if p.exists():
                got.update(read_env_file(p))
            elif required:
                raise RenderError(f"{name}: env_file {path} not found")
        for k, v in svc["environment"].items():
            if v is None:  # `NAME:` with no value: passed through from the caller's environment when it is set
                if k in env:
                    got[k] = env[k]
            else:
                got[k] = _walk(v, env)
        out[name] = {"environment": got}
    return {"services": out}


# ------------------------------------------------------------------------------------------------------ the check
def db_secrets(env: Mapping[str, str]) -> dict[str, str]:
    """The database passwords of an environment (``deploy/.env``): name -> value."""
    return {k: v for k, v in env.items() if DB_SECRET.match(k)}


def reach_problems(config: Mapping[str, Any], secrets: Mapping[str, str]) -> list[str]:
    """What is wrong with who holds which database password in a rendered compose (or in running containers).

    A finding per service and password: the password's value is in the service's environment, under any variable
    name (a ``TB_DB_URL`` carries one too), and the service is not its holder; or a service's ``TB_DB_URL`` signs in
    as a role that is not the service's own.
    """
    bad: list[str] = []
    for svc, body in sorted((config.get("services") or {}).items()):
        environ = _environment((body or {}).get("environment"))
        blob = json.dumps(environ, sort_keys=True)
        for name, value in sorted(secrets.items()):
            if len(value) >= MIN_LEN and value in blob and not may_hold(svc, name):
                where = sorted(k for k, v in environ.items() if v and value in v)
                bad.append(f"{svc} holds {name} (in {', '.join(where)})")
        url = environ.get("TB_DB_URL") or ""
        m = re.match(r"^[a-z0-9+]+://([^:/@]*)", url)
        if m and svc != "db":
            want = "trialbox" if svc in ADMIN_HOLDERS["POSTGRES_WF_PASSWORD"] else "tb_" + svc.replace("-", "_")
            if m.group(1) != want:
                bad.append(f"{svc}: TB_DB_URL signs in as {m.group(1) or 'nobody'}, not as {want}")
    return bad


def env_problems(env: Mapping[str, str], services: Sequence[str]) -> list[str]:
    """What is wrong with the passwords of a box's ``deploy/.env``: a role of ``services`` (the services that open
    the trial database) with no password of its own falls back to the workflow administrator's, and two roles with
    one password are one role."""
    bad: list[str] = []
    secrets = db_secrets(env)
    for svc in services:
        name = role_secret(svc)
        if not secrets.get(name):
            bad.append(f"{name} is not set: {svc} would sign in with the workflow administrator's password")
    for name in ADMIN:
        if not secrets.get(name):
            bad.append(f"{name} is not set")
    seen: dict[str, str] = {}
    for name, value in sorted(secrets.items()):
        if not value:
            continue
        if value.startswith("change-me"):
            bad.append(f"{name} is still the example value")
        elif value in seen:
            bad.append(f"{name} and {seen[value]} are the same password")
        else:
            seen[value] = name
    return bad


def database_services(config: Mapping[str, Any]) -> list[str]:
    """The services of a rendered compose that open the trial database with a role of their own."""
    out = []
    for svc, body in (config.get("services") or {}).items():
        url = _environment((body or {}).get("environment")).get("TB_DB_URL") or ""
        if re.match(r"^[a-z0-9+]+://tb_", url):
            out.append(svc)
    return sorted(out)


# ------------------------------------------------------------------------------------------- the running containers
Runner = Callable[[list[str]], str]


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=True).stdout  # nosec B603


def running_config(project: str = "trialbox", run: Runner = _run) -> dict[str, Any] | None:
    """The environment of the project's running containers, in the shape of :func:`render`. None when docker cannot
    be asked (no docker here, no right to use it) or nothing of the project runs."""
    try:
        ids = run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"]).split()
        if not ids:
            return None
        docs = json.loads(run(["docker", "inspect", *ids]))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    services: dict[str, Any] = {}
    for doc in docs if isinstance(docs, list) else []:
        config = doc.get("Config") or {}
        svc = (config.get("Labels") or {}).get("com.docker.compose.service")
        if svc:
            services[svc] = {"environment": _environment(config.get("Env"))}
    return {"services": services} if services else None
