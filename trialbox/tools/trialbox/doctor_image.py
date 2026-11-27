"""H-144: ``trialbox doctor``'s checks that need the box image, run in it from a host's own Python (stdlib only).

The integrator's ruling 7159506328: on a host (``trialbox doctor`` installed, or ``python3 -m tools.trialbox doctor``
from the install folder) 16 of the doctor's checks failed as import errors: no pydantic, no httpx, no ``services/``
on the path, no ``models/routing.yaml`` or ``models/registry.yaml`` (none of them is in the signed host tree, the box
image carries all of them). Those checks (``doctor.IMAGE_CHECKS``) run here in one-off containers of the box's own
image, as ``deploy/check_host.sh`` runs the whole doctor at install time. The integrator's 7159790789 set the rest:

* **The image and the runtime** are the box file's ``TB_IMAGE`` (else ``launch.DEFAULT_IMAGE``) and ``TB_DOCKER``,
  never a caller's; ``--pull never``, ``--cap-drop ALL``, no new privileges.
* **A network only for a check that needs one** (``NETWORK``): ``perimeter_addresses`` resolves each perimeter
  endpoint as the gateway does, so it runs on the box's own model network (``launch.MODEL_NETWORK``, the project's
  name); every other check here only reads files and runs with ``--network none``. A box whose network is not there
  (not running) makes that check a FAIL that says so.
* **Only what a check reads, read-only**: the box's deploy folder at ``/app/deploy`` with its secret and data folders
  (``HIDDEN``: secrets, keys, backups, the update's rollback points, the models' weights, ...) covered by an empty
  read-only folder; the release tree its shipped files link to at ``/app/current``; the code systems' volume; a compose
  file outside the deploy folder and the files the doctor's own options name, at their own paths. The settings come
  by ``--env-file`` (never a value on a command line).
* **What the container cannot see is handed in**, as check_host.sh hands it: ``docker inspect`` of the project's
  running containers on standard input (it holds passwords: a pipe, never a file), and the pid map's row for the site
  (its fingerprint and chart-number rule, no secret).
* **No secret in what comes back**: every value of a secret-named setting of the box's file (``SECRET_NAME``) is
  replaced by ``[redacted]`` in each verdict and in any error text, before anything is printed.

Each answers ``doctor --only NAMES --json``. Each verdict is that check's own; when a container cannot be started,
answers nothing that parses, or leaves a check out, each check it did not answer is a FAIL with the reason. Never a
PASS, never a skip.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Runner = Callable[..., subprocess.CompletedProcess[str]]
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")
IMAGE_DEPLOY = "/app/deploy"
TIMEOUT_S = 900
#: the checks that need a network, and which (``launch``'s names; the box's own project's network)
NETWORK = {"perimeter_addresses": "trialbox-model-net"}
#: the deploy folder's parts no image check reads: covered (secrets, keys, backups and dumps, weights, logs)
HIDDEN = ("secrets", "keys", "backups", "updates", "pgbackrest", "models", "ops", "logs", "refdata")
SECRET_NAME = re.compile(r"PASSWORD|PASSWD|SECRET|TOKEN|_KEY$|_KEY_|APIKEY|PRIVATE|CREDENTIAL|_PW_|_PW$", re.I)


@dataclass
class Request:
    """What the host's doctor was given, for the image's part of the run."""

    names: tuple[str, ...]
    deploy: Path | None  # the box's deploy folder (``--env-file``'s, else the install folder's own)
    env_file: Path | None  # ``--env-file`` as given (None: the image's doctor gets none either)
    settings: Path | None = None
    routing: Path | None = None
    box: Mapping[str, str] = field(default_factory=dict)  # the box file's settings (launch.box_file)


def _env_values(path: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if path is None or not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _under(p: Path, folder: Path) -> str | None:
    try:
        return p.resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return None


def secrets_of(values: Mapping[str, str]) -> list[str]:
    """The values of the box's secret-named settings, longest first (so a value inside another is not left half)."""
    return sorted({v for k, v in values.items() if SECRET_NAME.search(k) and len(v) >= 4}, key=len, reverse=True)


def redact(text: str, secrets: Sequence[str]) -> str:
    for s in secrets:
        text = text.replace(s, "[redacted]")
    return text


def network_of(name: str, project: str) -> str:
    """The network a check runs on: ``none``, or the box's own project's network (``launch.container_argv``)."""
    net = NETWORK.get(name, "none")
    if net.startswith("trialbox-"):  # H-106: the box's own project's network (the H-75 names)
        net = project + net.removeprefix("trialbox")
    return net


def argv(req: Request, network: str = "none", pidmap_row: str = "", name: str = "") -> list[str]:
    """The ``docker run`` of one part of the image's checks: see the module's text for what is mounted and why."""
    docker = shlex.split(req.box.get("TB_DOCKER") or "docker")
    image = req.box.get("TB_IMAGE") or "trialbox-py:1.0.0"
    mounts: list[str] = []
    seen: set[str] = set()

    def mount(src: str, dst: str) -> None:
        if dst not in seen:
            seen.add(dst)
            mounts.extend(["-v", f"{src}:{dst}:ro"])

    envf: list[str] = []
    args = ["doctor", "--only", ",".join(req.names), "--json"]
    if req.deploy is not None and req.deploy.is_dir():
        deploy = req.deploy.resolve()
        mount(str(deploy), IMAGE_DEPLOY)
        for part in HIDDEN:  # covered by an empty read-only folder: never read, never mounted in
            if (deploy / part).is_dir() and not (deploy / part).is_symlink():
                mounts.extend(["--tmpfs", f"{IMAGE_DEPLOY}/{part}:ro,size=4k,mode=0555"])
        current = deploy.parent / "current"
        if current.exists():  # OPS-004: the shipped files under deploy/ are links into ../current
            mount(str(current.resolve()), "/app/current")
        own = req.env_file or deploy / ".env"
        if own.is_file():
            envf = ["--env-file", str(own)]
        for cf in [c for c in _env_values(own).get("COMPOSE_FILE", "").split(":") if c.startswith("/")]:
            if _under(Path(cf), deploy) is None and Path(cf).is_file():
                mount(cf, cf)
    if req.env_file is not None:
        rel = _under(req.env_file, req.deploy) if req.deploy is not None else None
        if rel is not None:
            args += ["--env-file", f"{IMAGE_DEPLOY}/{rel}"]
        else:
            mount(str(req.env_file.resolve()), str(req.env_file.resolve()))
            args += ["--env-file", str(req.env_file.resolve())]
    for flag, p in (("--settings", req.settings), ("--routing", req.routing)):
        if p is None:
            continue
        rel = _under(p, req.deploy) if req.deploy is not None else None
        if rel is not None:
            args += [flag, f"{IMAGE_DEPLOY}/{rel}"]
        else:  # a file that is not there stays named: the image's doctor says so (its own inputs line)
            if p.exists():
                mount(str(p.resolve()), str(p.resolve()))
            args += [flag, str(p.resolve())]
    project = (req.box.get("COMPOSE_PROJECT_NAME") or "trialbox").strip() or "trialbox"
    terminology = req.box.get("_TB_TERMINOLOGY_VOLUME", "")  # filled by verdicts() when the volume is there
    if terminology:
        mounts.extend(["-v", f"{terminology}:/data/terminology:ro"])
    named = ["--name", name] if name else []
    return [*docker, "run", "--rm", "-i", *named, "--pull", "never", "--network", network, "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--user", "0:0", "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "TB_DOCTOR_RUNNING_INSPECT=stdin", "-e", f"TB_DOCTOR_PIDMAP_ROW={pidmap_row}",
            "-e", f"COMPOSE_PROJECT_NAME={project}", *envf, *mounts, "-w", "/app", image,
            "python", "-m", "tools.trialbox", *args]  # fmt: skip


def _quiet(run: Runner, cmd: Sequence[str], **kw: Any) -> subprocess.CompletedProcess[str] | None:
    try:
        return run(list(cmd), capture_output=True, text=True, check=False, timeout=60, **kw)
    except (OSError, subprocess.SubprocessError):
        return None


def running_inspect(docker: Sequence[str], project: str, run: Runner = subprocess.run) -> str:
    """``docker inspect`` of the project's running containers, as check_host.sh hands it in; ``[]`` when none."""
    ps = _quiet(run, [*docker, "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"])
    ids = ps.stdout.split() if ps is not None and ps.returncode == 0 else []
    if not ids:
        return "[]"
    got = _quiet(run, [*docker, "inspect", *ids])
    return got.stdout if got is not None and got.returncode == 0 and got.stdout.strip() else "[]"


#: the pid map's row for the site (``:'site'``), the same text as check_host.sh's. P-30: before the first night there is
#: no ``pidmap.site_key``; the catalog is asked first, so a box's boot logs no error and the answer is "no row"
PIDMAP_ROW_SQL = """SELECT to_regclass('pidmap.site_key') IS NOT NULL AS tb_has_pidmap \\gset
\\if :tb_has_pidmap
SELECT fingerprint || '|' || coalesce(chartno_rule, '') FROM pidmap.site_key WHERE site_id = :'site';
\\endif
"""


def pidmap_row(docker: Sequence[str], deploy: Path | None, values: Mapping[str, str], running: str,
               run: Runner = subprocess.run) -> str:  # fmt: skip
    """The pid map's row for the site (``fingerprint|chartno_rule``), as check_host.sh reads it; empty when unread,
    ``none`` when the site has no row (or no night has made the table yet)."""
    site = (values.get("TB_SITE_ID") or "").strip()
    if deploy is None or not site or running.strip() in ("", "[]"):
        return ""
    sql = PIDMAP_ROW_SQL
    got = _quiet(run, [*docker, "compose", "--project-directory", str(deploy), "exec", "-T", "db", "psql", "-X", "-q",
                       "-tA", "-v", "ON_ERROR_STOP=1", "-v", f"site={site}", "-U", "trialbox", "-d", "trialbox_wf"],
                 input=sql)  # fmt: skip
    if got is None or got.returncode != 0:
        return ""
    return got.stdout.strip() or "none"


def parse(names: Sequence[str], text: str) -> dict[str, dict[str, str]]:
    """The image's ``--json`` answer: each line kept only when it names one of ``names`` (or ``inputs``) with a
    status."""
    doc = json.loads(text)
    if not isinstance(doc, list):
        raise ValueError("not a list of checks")
    out: dict[str, dict[str, str]] = {}
    for c in doc:
        if not isinstance(c, dict):
            continue
        name, status, detail = c.get("name"), c.get("status"), c.get("detail")
        if (name in names or name == "inputs") and status in STATUSES and isinstance(detail, str):
            out.setdefault(str(name), {"name": str(name), "status": str(status), "detail": detail})
    return out


def _part(req: Request, names: tuple[str, ...], network: str, pidmap: str, running: str,
          run: Runner) -> tuple[dict[str, dict[str, str]], str]:  # fmt: skip
    """One container's verdicts, and why it gave none (empty when it answered)."""
    image = req.box.get("TB_IMAGE") or "trialbox-py:1.0.0"
    name = f"tb-doctor-{os.getpid()}-{network}"  # OCR 1512-3: named, so a container past its time can be removed
    cmd = argv(Request(names, req.deploy, req.env_file, req.settings, req.routing, req.box), network, pidmap, name)
    try:
        got = run(cmd, input=running, capture_output=True, text=True, check=False, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # the engine's client is killed, not the container: remove it, so no hung check stays behind
        gone = _quiet(run, [*shlex.split(req.box.get("TB_DOCKER") or "docker"), "rm", "-f", name])
        removed = "removed" if gone is not None and gone.returncode == 0 else "could not be removed: remove it by hand"
        return {}, f"the box image {image} did not answer within {TIMEOUT_S} s (container {name} {removed})"
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, f"the box image {image} could not be started here ({type(exc).__name__}: {exc})"
    try:
        return parse(names, got.stdout), ""
    except ValueError as exc:  # json's own error is a ValueError
        tail = " ".join((got.stderr or "").split())[-300:]
        net = f" on network {network}" if network != "none" else ""
        return {}, (f"the box image {image} gave no verdicts{net} (exit {got.returncode}; {type(exc).__name__}: {exc}"
                    + (f"; {tail}" if tail else "") + ")")  # fmt: skip


def verdicts(req: Request, run: Runner = subprocess.run) -> list[dict[str, str]]:
    """Each check of ``req.names``: its verdict from the box image, or a FAIL that says why the image gave none.
    One container per network the checks need (most need none); every text that comes back is redacted."""
    docker = shlex.split(req.box.get("TB_DOCKER") or "docker")
    image = req.box.get("TB_IMAGE") or "trialbox-py:1.0.0"
    project = (req.box.get("COMPOSE_PROJECT_NAME") or "trialbox").strip() or "trialbox"
    values = _env_values(req.env_file or (req.deploy / ".env" if req.deploy is not None else None))
    secrets = secrets_of({**values, **req.box})
    running = running_inspect(docker, project, run)
    box = dict(req.box)
    probe = _quiet(run, [*docker, "volume", "inspect", f"{project}_tb-terminology"])
    if probe is not None and probe.returncode == 0:
        box["_TB_TERMINOLOGY_VOLUME"] = f"{project}_tb-terminology"
    req = Request(req.names, req.deploy, req.env_file, req.settings, req.routing, box)
    pidmap = pidmap_row(docker, req.deploy, values, running, run)
    groups: dict[str, list[str]] = {}
    for name in req.names:
        groups.setdefault(network_of(name, project), []).append(name)
    answered: dict[str, dict[str, str]] = {}
    why: dict[str, str] = {}
    for network, names in groups.items():
        got, reason = _part(req, tuple(names), network, pidmap, running, run)
        if "inputs" in got and "inputs" not in answered:
            answered["inputs"] = got["inputs"]
        answered.update({n: v for n, v in got.items() if n != "inputs"})
        why.update({n: reason for n in names if reason})
    out = [answered["inputs"]] if "inputs" in answered else []
    for name in req.names:
        if name in answered:
            out.append(answered[name])
        else:
            reason = why.get(name) or f"the box image {image} answered, but not for this check"
            out.append({"name": name, "status": "FAIL",
                        "detail": f"not run: {reason}. This check needs the box image (pydantic, httpx, the "
                                  f"services' code or models/, none of them on the host's own Python)"})  # fmt: skip
    return [{**v, "detail": redact(v["detail"], secrets)} for v in out]


def own_deploy(env_file: Path | None) -> Path | None:
    """The deploy folder the image's part mounts: ``--env-file``'s, else the install folder's own when it has a
    ``.env`` (the folder the launcher took the box's settings from)."""
    if env_file is not None:
        return env_file.resolve().parent if env_file.exists() else None
    from tools.trialbox import launch

    return launch.DEPLOY if (launch.DEPLOY / ".env").is_file() else None


def box_settings() -> dict[str, str]:
    """The box file's own settings (the runtime and the image), never a caller's (launch.box_file)."""
    from tools.trialbox import launch

    try:
        return dict(launch.box_file(launch.DEPLOY))
    except launch.BoxFileError:
        return {}
