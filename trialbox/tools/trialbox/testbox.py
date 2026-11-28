"""The multi-box test mode (card H-106; the owner's ruling, relayed as 7117794599 and 7117870645). Standard library
(and PyYAML, which the host's python3 has: install.sh HOST-PYTHON) only: the host's python3 runs it.

"One box per host" is a production rule. Several TEST boxes may run side by side on one host, each with its own

* root folder (the folder its ``deploy/install.sh`` runs from; the plain script puts box NAME at PARENT/NAME);
* compose project, ``tbt-<name>-<6 hex of the root folder's real path>``: two folders never share a project, so
  never a volume (the site keys' ``tb-secrets`` among them), a container or a network (``<project>-net`` and the
  others, H-75);
* port offset N (1-49): every port the box publishes is its base plus 10 x N (the console 8090, the TLS proxy 8443
  in place of 443, the monitoring 9090); offset 0 is the one ordinary box's;
* GPU set (``--gpus 3`` or ``--gpus 2,3``): its model servers get those cards only (a compose file of its own,
  ``deploy/site/test-box.yml``, names them by index);
* memory cap per box (``--gpu-mem-gb G``): its model servers' ``--gpu-memory-utilization`` scaled so each asks the
  card for what it would ask of a G GB card. The serving engine enforces that share; the container engine does not
  (it has no per-container GPU memory limit). Shown only on the bench host's real cards.

THE MODE IS AN INSTALL OPTION, recorded in the box's own settings (``deploy/install.sh --test-box NAME``, written to
``deploy/site/test-box.env``, then to ``deploy/.env``). Every later command reads the box's own record; a caller's
environment variable never makes a box a test box, never names its project and never moves its secrets.

PRODUCTION is unchanged: a PRODUCTION install refuses ``--test-box``, and refuses to go on while a test box runs on
the host (:func:`others`, read from the container engine); a test box refuses a host that holds a PRODUCTION box.

    python3 -m tools.trialbox.testbox record --deploy D --name NAME [--port-offset N] [--gpus L] [--gpu-mem-gb G]
    python3 -m tools.trialbox.testbox env --deploy D [--profile P]     # the deploy/.env lines of the record
    python3 -m tools.trialbox.testbox override --deploy D --files F1:F2  # deploy/site/test-box.yml (GPU set)
    python3 -m tools.trialbox.testbox others --deploy D                # the other boxes on this host
    python3 -m tools.trialbox.testbox list                             # every box on this host
    python3 -m tools.trialbox.testbox remove --name NAME [--yes]        # one test box, whole; never another

Exit codes: 0 done; 2 refused (the reason on stderr, nothing changed); 3 the engine could not be asked.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RECORD = Path("site") / "test-box.env"  # under the deploy folder
OVERRIDE = Path("site") / "test-box.yml"
OVERRIDE_MARK = "x-trialbox-test-box: true"
NAME = re.compile(r"[a-z][a-z0-9]{0,11}")
PROJECT = re.compile(r"tbt-[a-z][a-z0-9]{0,11}-[0-9a-f]{6}")
GPUS = re.compile(r"[0-9]{1,2}(?:,[0-9]{1,2}){0,7}")
DIGITS = re.compile(r"[0-9]{1,4}")  # ASCII only (OCR 1452-7): str.isdigit takes "²" and other scripts' digits
#: each published port of a box: its variable in deploy/.env and its base (the one ordinary box's is offset 0)
PORTS = {"TB_HOST_CONSOLE_PORT": 8090, "TB_TLS_PORT": 8443, "TB_PROMETHEUS_PORT": 9090}
STEP = 10
MAX_OFFSET = 49
UTIL = re.compile(r"--gpu-memory-utilization=\$\{(\w+):-([0-9.]+)\}")
SECRETS_VOLUME = "tb-secrets"  # every box has its own: the compose volume that marks a box in the engine
LABEL_PROJECT = "com.docker.compose.project"
LABEL_DIR = "com.docker.compose.project.working_dir"
LABEL_VOLUME = "com.docker.compose.volume"
WHO = "test-box"

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class Refused(Exception):
    """A refusal: nothing was changed."""


class NoEngine(Exception):
    """The container engine could not be asked."""


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=120, check=False)


def project_for(name: str, root: Path) -> str:
    """The box's compose project: its name and the root folder's real path, so two folders never share one."""
    if not NAME.fullmatch(name):
        raise Refused(f"--test-box {name!r}: a name is a lower-case letter, then up to 11 letters or digits")
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:6]
    return f"tbt-{name}-{digest}"


def ports(offset: int) -> dict[str, int]:
    return {k: base + STEP * offset for k, base in PORTS.items()}


_NET_DEFAULT = re.compile(r"\$\{(TB_NET_SUBNET|TB_PROXY_ADDR):-([^}]+)\}")
_BRIDGES = ("lo", "docker", "br-", "veth")  # the engine's own bridges: other boxes' networks, kept apart by offset


def nets(deploy: Path, offset: int) -> dict[str, str]:
    """H-137: the box's internal range behind the TLS proxy and the proxy's fixed address in it: the overlay's defaults
    (the ordinary box's, deploy/docker-compose.identity.yml) moved down by ``offset`` ranges of their size, so every
    box on the host has its own (the engine refuses a second network on a range another box's network holds: "Pool
    overlaps"). {} without the overlay."""
    try:
        found = dict(_NET_DEFAULT.findall((deploy / "docker-compose.identity.yml").read_text(encoding="utf-8")))
    except FileNotFoundError:
        return {}
    if set(found) != {"TB_NET_SUBNET", "TB_PROXY_ADDR"}:
        return {}
    net = ipaddress.ip_network(found["TB_NET_SUBNET"], strict=False)
    shift = net.num_addresses * offset
    own = ipaddress.ip_network((int(net.network_address) - shift, net.prefixlen))
    return {"TB_NET_SUBNET": str(own), "TB_PROXY_ADDR": str(ipaddress.ip_address(found["TB_PROXY_ADDR"]) - shift)}


def host_ranges(run: Runner | None = None) -> list[str] | None:
    """The ranges this host is on (its addresses with their prefix, and its routes), the engine's bridges left out;
    None when ``ip`` cannot say (as tools/trialbox/preflight.py's name_cert reads them)."""
    try:
        got = [(run or _run)(["ip", "-j", what, "show"]) for what in ("addr", "route")]
        links, routes = (json.loads(g.stdout or "null") if g.returncode == 0 else None for g in got)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(links, list) or not isinstance(routes, list):
        return None
    kept = [link for link in links if not str(link.get("ifname", "")).startswith(_BRIDGES)]
    out = [
        f"{a['local']}/{a.get('prefixlen', 32)}" for link in kept for a in link.get("addr_info") or () if a.get("local")
    ]
    out += [str(r["dst"]) for r in routes if r.get("dst") not in (None, "default")
            and not str(r.get("dev", "")).startswith(_BRIDGES)]  # fmt: skip
    return out


def range_clash(deploy: Path, offset: int, run: Runner | None = None) -> str:
    """Why this box's internal range cannot be used here ("" when it can): it overlaps a range this host is on."""
    own = nets(deploy, offset).get("TB_NET_SUBNET")
    taken = host_ranges(run) if own else None
    if not own or taken is None:
        return ""
    mine = ipaddress.ip_network(own)
    hit = []
    for raw in taken:
        try:
            other = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if other.version == mine.version and other.prefixlen > 0 and other.overlaps(mine):
            hit.append(str(other))
    if not hit:
        return ""
    said = ", ".join(sorted(set(hit)))
    return f"the box's internal range {own} (port offset {offset}) clashes with this host's {said}: choose another one"


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines, as compose reads a plain file (the last line wins); {} when there is none."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


@dataclass(frozen=True)
class Box:
    name: str
    project: str
    offset: int
    gpus: str = ""
    gpu_mem_gb: int = 0
    root: str = ""  # the host folder, as the installer saw it (a container sees the tree elsewhere, at /app)

    def lines(self) -> list[str]:
        return [
            f"TB_TEST_BOX={self.name}",
            f"COMPOSE_PROJECT_NAME={self.project}",
            f"TB_TEST_BOX_PORT_OFFSET={self.offset}",
            f"TB_TEST_BOX_GPUS={self.gpus}",
            f"TB_TEST_BOX_GPU_MEM_GB={self.gpu_mem_gb or ''}",
            f"TB_TEST_BOX_ROOT={self.root}",
        ]

    def words(self) -> str:
        """What the box says it is, on every page and in every operator's output."""
        gpu = f"cards {self.gpus}" if self.gpus else "no card"
        cap = f", capped to {self.gpu_mem_gb} GB a card" if self.gpu_mem_gb else ""
        return (f"TEST BOX {self.name}: one of several boxes on this host (project {self.project}, console port "
                f"{ports(self.offset)['TB_HOST_CONSOLE_PORT']}, {gpu}{cap}); synthetic data only, never a site's "
                "patients")  # fmt: skip


def load(deploy: Path) -> Box | None:
    """The box's own record, or None on a box that is no test box."""
    rec = read_env(deploy / RECORD)
    if not rec:
        return None
    name, project = rec.get("TB_TEST_BOX", ""), rec.get("COMPOSE_PROJECT_NAME", "")
    root = rec.get("TB_TEST_BOX_ROOT", "")
    # the project is the recorded host folder's; a copy is a record whose recorded folder is on this machine and is
    # not this one (inside the box's own container the tree is mounted elsewhere and the host folder is not there)
    folder = Path(root) if root else deploy.parent
    copied = bool(root) and folder.exists() and folder.resolve() != deploy.parent.resolve()
    if copied or project != project_for(name, folder) or not PROJECT.fullmatch(project):
        raise Refused(
            f"{deploy / RECORD} names {name!r} and project {project!r}, which are not this folder's: a "
            "test box record is never copied between folders; remove the box and install it again"
        )
    offset = rec.get("TB_TEST_BOX_PORT_OFFSET", "")
    gpus, cap = rec.get("TB_TEST_BOX_GPUS", ""), rec.get("TB_TEST_BOX_GPU_MEM_GB", "")
    if not DIGITS.fullmatch(offset) or (gpus and not GPUS.fullmatch(gpus)) or (cap and not DIGITS.fullmatch(cap)):
        raise Refused(f"{deploy / RECORD} cannot be read (offset {offset!r}, cards {gpus!r}, cap {cap!r})")
    return Box(name, project, int(offset), gpus, int(cap or 0), root)


def check_values(offset: str, gpus: str, cap: str) -> tuple[int, str, int]:
    if not DIGITS.fullmatch(offset) or not 1 <= int(offset) <= MAX_OFFSET:
        raise Refused(f"--port-offset {offset!r}: a number from 1 to {MAX_OFFSET} (0 is the ordinary box's ports)")
    if gpus and not GPUS.fullmatch(gpus):
        raise Refused(f"--gpus {gpus!r}: card indexes, comma-separated (3, or 2,3)")
    if gpus and len(set(gpus.split(","))) != len(gpus.split(",")):
        raise Refused(f"--gpus {gpus!r} names a card twice")
    if cap and (not DIGITS.fullmatch(cap) or not 1 <= int(cap) <= 1024):
        raise Refused(f"--gpu-mem-gb {cap!r}: whole GB, from 1 to 1024")
    if cap and not gpus:
        raise Refused("--gpu-mem-gb goes with --gpus: a cap is per card the box is given")
    return int(offset), gpus, int(cap or 0)


def clashes(deploy: Path, name: str, offset: int, run: Runner = _run) -> list[str]:
    """OCR 1452-8: what another box on this host already holds of this one: its name (a test box's, or another box's
    project), or its port offset. Read from the engine; an engine that cannot be asked holds nothing here (the host
    step's own listing refuses that case)."""
    own = project_for(name, deploy.parent)  # this box's own project, also before its first record
    try:
        seen = [s for s in boxes(run) if s.project != own]
    except NoEngine:
        return []
    out = []
    for s in seen:
        if s.project == name:
            out.append(f"the name {name!r} is the project of another box ({s.root or 'folder unknown'})")
        if s.kind != "test" or not s.root:
            continue
        try:
            b = load(Path(s.root) / "deploy")
        except Refused:
            continue
        if b is not None and b.name == name:
            out.append(f"test box {name!r} is already at {s.root}")
        if b is not None and b.offset == offset:
            out.append(f"port offset {offset} is test box {b.name!r}'s ({s.root})")
    return out


def record(deploy: Path, name: str, offset: str, gpus: str = "", cap: str = "") -> Box:
    """Write (or keep) the box's record. Its name and project never change; its offset, cards and cap may."""
    project = project_for(name, deploy.parent)
    off, gpus, gb = check_values(offset, gpus, cap)
    old = load(deploy)
    if old is not None and old.name != name:
        raise Refused(f"this folder is test box {old.name!r} (deploy/{RECORD}): a box keeps its name; remove it and "
                      f"install {name!r} in a folder of its own")  # fmt: skip
    box = Box(name, project, off, gpus, gb, str(deploy.parent.resolve()))
    path = deploy / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    with tmp.open("w", encoding="utf-8") as fh:  # on the disk, then renamed (OCR 1452-3): a power cut never empties it
        fh.write("# deploy/install.sh --test-box (H-106): this folder's test box; never copied, never edited\n"
                 + "\n".join(box.lines()) + "\n")  # fmt: skip
        fh.flush()
        os.fsync(fh.fileno())
    tmp.chmod(0o644)
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return box


# ------------------------------------------------------------------------------------------------ the memory cap
def card_mib(index: str, run: Runner = _run) -> int:
    r = run(["nvidia-smi", "-i", index, "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    first = (r.stdout or "").strip().splitlines()[:1]
    if r.returncode != 0 or not first or not first[0].strip().isdigit():
        raise Refused(f"nvidia-smi gives no memory figure for card {index}: the cap cannot be set")
    return int(first[0].strip())


def utils(deploy: Path, profile: str) -> dict[str, float]:
    """The utilisations the box's compose files ask for (the profile's file over the base file)."""
    found: dict[str, float] = {}
    for f in (deploy / "docker-compose.yml", deploy / f"docker-compose.{profile}.yml"):
        if profile and f.is_file():
            found.update({k: float(v) for k, v in UTIL.findall(f.read_text(encoding="utf-8"))})
    return found


def capped(deploy: Path, box: Box, profile: str, run: Runner = _run) -> dict[str, float]:
    """Each utilisation scaled from a card of the cap to the box's first card: the share a G GB card would give."""
    if not box.gpu_mem_gb:
        return {}
    total = card_mib(box.gpus.split(",")[0], run)
    cap = box.gpu_mem_gb * 1024
    if cap > total:
        raise Refused(f"--gpu-mem-gb {box.gpu_mem_gb}: card {box.gpus.split(',')[0]} has {total} MiB")
    return {k: math.floor(u * cap / total * 1000) / 1000 for k, u in utils(deploy, profile).items()}


def env_lines(deploy: Path, profile: str = "", run: Runner = _run) -> list[str]:
    box = load(deploy)
    if box is None:
        return []
    out = [*box.lines(), *(f"{k}={v}" for k, v in sorted(ports(box.offset).items()))]
    out += [f"{k}={v}" for k, v in sorted(nets(deploy, box.offset).items())]  # H-137: a range of its own
    out += [f"{k}={v}" for k, v in sorted(capped(deploy, box, profile, run).items())]
    return out


# ------------------------------------------------------------------------------------------------ the GPU set
_TAG = re.compile(r"!(?:override|reset)\b")  # compose's own tags: read as their plain values


def gpu_services(files: Sequence[Path]) -> list[str]:
    """The services of these compose files that reserve a card."""
    import yaml

    out: set[str] = set()
    for f in files:
        doc = yaml.safe_load(_TAG.sub("", f.read_text(encoding="utf-8"))) or {}
        for svc, spec in (doc.get("services") or {}).items():
            res = ((spec or {}).get("deploy") or {}).get("resources") or {}
            if (res.get("reservations") or {}).get("devices"):
                out.add(str(svc))
    return sorted(out)


def override(deploy: Path, files: Sequence[Path]) -> Path | None:
    """deploy/site/test-box.yml: every service that reserves a card gets the box's cards, by index, and the TLS proxy
    (when the box has one) publishes the box's own TLS port. None (and no file) when there is neither."""
    box = load(deploy)
    path = deploy / OVERRIDE
    given = [f for f in files if f.is_file() and f.resolve() != path.resolve()]
    services = gpu_services(given) if box and box.gpus else []
    tls = box is not None and any(f.name == "docker-compose.identity.yml" for f in given)
    if box is None or not (services or tls):
        path.unlink(missing_ok=True)
        return None
    lines = ["# Written by deploy/install.sh --test-box (H-106): this test box's cards and TLS port; never edited",
             OVERRIDE_MARK, "services:"]  # fmt: skip
    if tls:
        port = ports(box.offset)["TB_TLS_PORT"]
        lines += ["  caddy:", f'    ports: !override ["${{TB_TLS_BIND:-0.0.0.0}}:{port}:443"]']
    ids = ", ".join(json.dumps(i) for i in box.gpus.split(","))
    devices = f"!override [{{driver: nvidia, device_ids: [{ids}], capabilities: [gpu]}}]"
    for svc in services:
        lines += [f"  {svc}:", "    deploy:", "      resources:", "        reservations:"]
        lines += [f"          devices: {devices}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o644)
    return path


# ------------------------------------------------------------------------------------------------ the host's boxes
@dataclass(frozen=True)
class Seen:
    project: str
    kind: str  # test | poc | production
    root: str  # "" when no container says where it was started from


def _lines(run: Runner, argv: Sequence[str]) -> list[str]:
    try:
        r = run(argv)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NoEngine(str(exc)) from exc
    if r.returncode != 0:
        raise NoEngine((r.stderr or "").strip() or f"exit {r.returncode}")
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def boxes(run: Runner = _run) -> list[Seen]:
    """Every box the engine holds: each compose project with a site-keys volume of its own. Its root is the folder
    its containers were started from; its kind is its record's (a test box), else its environment's, read as
    tools/trialbox/stops.py reads it. A box whose folder cannot be found or read counts as PRODUCTION."""
    from tools.trialbox import stops

    projects = sorted(set(_lines(run, ["docker", "volume", "ls", "--filter", f"label={LABEL_VOLUME}={SECRETS_VOLUME}",
                                       "--format", f'{{{{.Label "{LABEL_PROJECT}"}}}}'])))  # fmt: skip
    out = []
    for p in projects:
        dirs = set(_lines(run, ["docker", "ps", "-a", "--filter", f"label={LABEL_PROJECT}={p}",
                                "--format", f'{{{{.Label "{LABEL_DIR}"}}}}']))  # fmt: skip
        root = ""
        if len(dirs) == 1:
            d = Path(next(iter(dirs)))
            root = str(d.parent if d.name == "deploy" else d)
        kind = "production"
        if PROJECT.fullmatch(p):
            kind = "test"  # by its name; its record, where its folder is found, must say the same
            if root:
                try:
                    b = load(Path(root) / "deploy")
                except Refused:
                    b = None
                kind = "test" if b is not None and b.project == p else "production"
        elif root and stops.poc_box(Path(root) / "deploy"):
            kind = "poc"
        out.append(Seen(p, kind, root))
    return out


def others(deploy: Path, run: Runner = _run) -> list[Seen]:
    """Every box on this host but this folder's own (by its record's project, else the ordinary one's)."""
    box = load(deploy)
    own = box.project if box else (read_env(deploy / ".env").get("COMPOSE_PROJECT_NAME") or "trialbox")
    return [s for s in boxes(run) if s.project != own]


def listing(run: Runner = _run) -> list[str]:
    rows = []
    for s in boxes(run):
        b = None
        if s.root:
            try:
                b = load(Path(s.root) / "deploy")
            except Refused:
                b = None
        if b is not None:
            rows.append(f"{b.name}\t{s.project}\t{s.root}\tconsole {ports(b.offset)['TB_HOST_CONSOLE_PORT']}\t"
                        f"cards {b.gpus or '-'}\tcap {b.gpu_mem_gb or '-'} GB")  # fmt: skip
        else:
            rows.append(f"({s.kind})\t{s.project}\t{s.root or '(no container: folder unknown)'}\t-\t-\t-")
    return rows


def remove(name: str, run: Runner = _run, *, yes: bool = False, say: Callable[[str], None] = print) -> int:
    """One test box, whole: its containers, networks and volumes (by its own project's label only), then its folder.
    Refused for any box that is not a test box of that name, so another box is never touched."""
    if not NAME.fullmatch(name):
        raise Refused(f"{name!r} is not a test box name")
    every = boxes(run)
    found = [s for s in every if s.kind == "test" and s.root]
    hits = []
    for s in found:
        b = load(Path(s.root) / "deploy")
        if b is not None and b.name == name and b.project == s.project:
            hits.append((s, b))
    if len(hits) != 1:
        raise Refused(f"no single test box named {name!r} is running or stopped on this host (found {len(hits)}); "
                      "`list` shows them")  # fmt: skip
    seen, box = hits[0]
    root = Path(seen.root)
    if not PROJECT.fullmatch(box.project) or box.project != project_for(name, root):
        raise Refused(f"{root} is not test box {name!r}'s own folder")
    inside = [s.root for s in every if s.project != box.project and s.root
              and Path(s.root).resolve().is_relative_to(root.resolve())]  # fmt: skip
    if inside:  # OCR 1452-5: never another box's folder with this one
        raise Refused(f"{root} holds another box's folder ({', '.join(inside)}): it is never removed with this one")
    if not yes:
        say(f"would remove test box {name}: project {box.project} (its containers, networks, volumes) and {root}; "
            "give --yes")  # fmt: skip
        return 0
    label = f"label={LABEL_PROJECT}={box.project}"
    run(["docker", "compose", "--project-directory", str(root / "deploy"), "-p", box.project, "down", "--volumes",
         "--remove-orphans", "--timeout", "30"])  # fmt: skip
    for kind, ls in (("container", ["ps", "-aq"]), ("network", ["network", "ls", "-q"]),
                     ("volume", ["volume", "ls", "-q"])):  # fmt: skip
        ids = _lines(run, ["docker", *ls, "--filter", label])
        if ids:
            rm = ["rm", "-f"] if kind == "container" else [kind, "rm", *(["-f"] if kind == "volume" else [])]
            r = run(["docker", *rm, *ids])
            if r.returncode != 0:
                raise Refused(f"the {kind}s of {box.project} could not be removed: {(r.stderr or '').strip()}")
    left = [x for ls in (["ps", "-aq"], ["network", "ls", "-q"], ["volume", "ls", "-q"])
            for x in _lines(run, ["docker", *ls, "--filter", label])]  # fmt: skip
    if left:
        raise Refused(f"{len(left)} object(s) of {box.project} are left; its folder {root} is kept")
    shutil.rmtree(root)
    say(f"removed test box {name}: project {box.project} (containers, networks, volumes) and {root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tools.trialbox.testbox", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--deploy", type=Path, required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--port-offset", default="")
    r.add_argument("--gpus", default="")
    r.add_argument("--gpu-mem-gb", default="")
    e = sub.add_parser("env")
    e.add_argument("--deploy", type=Path, required=True)
    e.add_argument("--profile", default="")
    o = sub.add_parser("override")
    o.add_argument("--deploy", type=Path, required=True)
    o.add_argument("--files", required=True, help="the compose files, colon-separated")
    w = sub.add_parser("words")
    w.add_argument("--deploy", type=Path, required=True)
    t = sub.add_parser("others")
    t.add_argument("--deploy", type=Path, required=True)
    sub.add_parser("list")
    m = sub.add_parser("remove")
    m.add_argument("--name", required=True)
    m.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "record":
            old = load(a.deploy)
            offset = a.port_offset or (str(old.offset) if old else "")
            gpus = a.gpus if a.port_offset or a.gpus or not old else old.gpus
            cap = a.gpu_mem_gb if a.port_offset or a.gpus or a.gpu_mem_gb or not old else str(old.gpu_mem_gb or "")
            if not offset:
                raise Refused("--test-box needs --port-offset N (1-49) on its first install")
            clash = clashes(a.deploy, a.name, check_values(offset, gpus, cap)[0])
            if clash:
                raise Refused("; ".join(clash) + ": a test box has a name and a port offset of its own on this host")
            why = range_clash(a.deploy, check_values(offset, gpus, cap)[0])  # H-137: the internal range is free here
            if why:
                raise Refused(why)
            print(record(a.deploy, a.name, offset, gpus, cap).project)
        elif a.cmd == "env":
            print("\n".join(env_lines(a.deploy, a.profile)))
        elif a.cmd == "override":
            p = override(a.deploy, [Path(f) for f in a.files.split(":") if f])
            if p:
                print(p)
        elif a.cmd == "words":
            box = load(a.deploy)
            if box:
                print(box.words())
        elif a.cmd == "others":
            for s in others(a.deploy):
                print(f"{s.project}\t{s.kind}\t{s.root}")
        elif a.cmd == "list":
            print("name\tproject\troot\tports\tcards\tcap")
            print("\n".join(listing()))
        else:
            return remove(a.name, yes=a.yes)
    except Refused as exc:
        print(f"{WHO}: refused: {exc}; nothing was changed", file=sys.stderr)
        return 2
    except NoEngine as exc:
        print(f"{WHO}: the container engine could not be asked ({exc})", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    if not __package__:
        sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    os.umask(0o022)
    raise SystemExit(main())
