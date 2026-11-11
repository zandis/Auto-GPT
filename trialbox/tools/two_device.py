"""The two-device form of the GB10 profile (plan TB-PLAN-05 §1.5 form A, T-214, D-373): ``python -m tools.two_device``.

Form A puts the gateway and the two vLLM servers on the DGX Spark and everything else (the trial database, the lake,
HAPI, the console, the services) on a CPU workstation. The two devices talk over one **link**: mutual TLS 1.3, both
ends holding a certificate of the link CA made at the install ceremony (``certs``), each end checking that the peer
is the other device (the certificate names ``trialbox-link-spark`` or ``trialbox-link-workstation``). A peer without
such a certificate gets no byte through.

The link is a small relay, one container per device (``link`` in ``deploy/two-device/``). Each device **exports**
named routes to its peer and **imports** the peer's routes as local listeners on the box network, under the service
name the callers already use:

* the Spark exports ``gateway`` (``gateway:8020``); the workstation's link answers to ``gateway`` on trialbox-net, so
  every ``TB_GATEWAY_URL=http://gateway:8020/v1`` keeps working;
* the workstation exports ``db`` (``db:5432``); the Spark's link answers to ``db``, so the gateway's trace store
  (``TB_DB_URL``) keeps working.

Nothing else crosses. On the Spark the link is the only published port, bound to the link address
(``TB_LINK_ADDR``), never to every address: ``doctor --two-device`` and ``check`` fail otherwise.

Commands:

* ``link``: run the relay (in the ``link`` container; ``TB_LINK_ROLE``, ``TB_LINK_PEER``, ``TB_LINK_PORT``,
  ``TB_LINK_CERTS``);
* ``certs --out DIR``: the install ceremony: a new link CA and one certificate per device. The CA key is never written,
  so a new device means a new ceremony;
* ``check --role spark|workstation --compose-config FILE``: the device's rendered compose (``docker compose config
  --format json <its services>``) against the GB10 profile (``deploy/gb10-profile.yaml``): what runs where, what is
  published where, the memory limits;
* ``profile``: the GB10 profile's own checks (memory budget, driver-hold dates, every number marked unmeasured until
  the benchmark record on a Spark replaces it);
* ``selftest``: both relays on this host with fresh certificates: a round trip through the link, then an
  unauthenticated peer, a peer of another CA and an unknown route, each refused. CI runs it in the arm64 and amd64
  images (``trialbox-images.yml``).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import functools
import json
import os
import ssl
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "deploy" / "gb10-profile.yaml"
PROFILE_SCHEMA = "tb-gb10-profile/1"
ROLES = ("spark", "workstation")
LINK_PORT = 8443
HELLO = b"TBLINK/1 "
HEADER_MAX = 64
HEADER_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 10.0
# what each device offers its peer: route name -> (host, port) on its own box network. The peer's link listens on
# the same port under the route name (a network alias), so callers keep their addresses.
ROUTES: dict[str, dict[str, tuple[str, int]]] = {
    "spark": {"gateway": ("gateway", 8020)},
    "workstation": {"db": ("db", 5432)},
}
ANY_ADDRESS = ("", "0.0.0.0", "::", "[::]")  # nosec B104: the addresses a published port must never bind to here


def peer_of(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"link role must be one of {', '.join(ROLES)}, not {role!r}")
    return ROLES[1] if role == ROLES[0] else ROLES[0]


def link_name(role: str) -> str:
    """The name in a device's link certificate (its DNS subjectAltName), checked by the peer."""
    return f"trialbox-link-{role}"


# ------------------------------------------------------------------------------------------------ the profile
def load_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: not a mapping")
    return doc


def _gib(value: Any) -> float | None:
    """A compose memory value (``42g``, ``512m``, or bytes as compose renders it) in GiB; None when unset."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return float(value) / 2**30
    s = str(value).strip().lower().removesuffix("b")
    units = {"k": 2**10, "m": 2**20, "g": 2**30, "t": 2**40}
    if s and s[-1] in units:
        return float(s[:-1]) * units[s[-1]] / 2**30
    return float(s) / 2**30


def memory_limits(profile: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(v["limit_gib"]) for k, v in (profile.get("memory") or {}).items()}


def _unmeasured_problems(profile: Mapping[str, Any]) -> list[str]:
    """Every measured value is null while the profile is unmeasured, and a number once it is measured."""
    measured = profile.get("status") == "measured"
    out: list[str] = []
    values: list[tuple[str, Any]] = [
        ("device.unified_memory_measured_gib", profile["device"].get("unified_memory_measured_gib"))
    ]
    values += [(f"memory.{k}.measured_peak_gib", v.get("measured_peak_gib")) for k, v in profile["memory"].items()]
    values += [(f"decision_gate.{g.get('id')}.result", g.get("result")) for g in profile.get("decision_gate") or []]
    for where, v in values:
        if measured and v is None:
            out.append(f"{where} is empty, but the profile says measured")
        if not measured and v is not None:
            out.append(f"{where} has a value, but the profile says unmeasured (status: measured needs the record)")
    if measured and not profile.get("record"):
        out.append("a measured profile names its benchmark record (record:)")
    return out


def profile_problems(profile: Mapping[str, Any]) -> list[str]:
    """What is wrong with the GB10 profile data; empty when it holds together."""
    out: list[str] = []
    if profile.get("schema") != PROFILE_SCHEMA:
        return [f"schema is {profile.get('schema')!r}, not {PROFILE_SCHEMA}"]
    if profile.get("status") not in ("unmeasured", "measured"):
        out.append("status must be unmeasured or measured")
    for key in ("device", "driver_hold", "memory", "devices", "decision_gate"):
        if not profile.get(key):
            out.append(f"{key} is missing")
    if out:
        return out
    dev, hold, devices = profile["device"], profile["driver_hold"], profile["devices"]
    limits = memory_limits(profile)
    total, reserve = float(dev["unified_memory_gib"]), float(dev["os_reserve_gib"])
    one = sum(v for k, v in limits.items() if k != "link")
    if one + reserve > total:
        out.append(f"one-device form: limits {one:g} GiB + OS {reserve:g} GiB > {total:g} GiB unified memory")
    spark = sum(limits.get(s, 0.0) for s in devices.get("spark") or [])
    if spark + reserve > total:
        out.append(f"two-device form: Spark limits {spark:g} GiB + OS {reserve:g} GiB > {total:g} GiB")
    for role in ROLES:
        if not devices.get(role):
            out.append(f"devices.{role} is empty")
        elif "link" not in devices[role]:
            out.append(f"devices.{role} has no link")
    both = set(devices.get("spark") or []) & set(devices.get("workstation") or [])
    if both - {"link"}:
        out.append(f"on both devices: {', '.join(sorted(both - {'link'}))}")
    for s in devices.get("spark") or []:
        if s not in limits:
            out.append(f"Spark service {s} has no memory limit")
    decided, every = hold.get("decided"), hold.get("retest_every_days")
    nxt = hold.get("next_retest_by")
    if not (isinstance(decided, dt.date) and isinstance(nxt, dt.date) and isinstance(every, int) and every > 0):
        out.append("driver_hold needs decided and next_retest_by (dates) and retest_every_days (days)")
    elif nxt > decided + dt.timedelta(days=every):
        out.append(f"driver_hold.next_retest_by {nxt} is later than decided + {every} days")
    for k in ("version", "decision", "retest_by"):
        if not hold.get(k):
            out.append(f"driver_hold.{k} is missing")
    ids = [g.get("id") for g in profile["decision_gate"]]
    if len(set(ids)) != len(ids) or None in ids:
        out.append("decision_gate ids must be set and unique")
    return out + _unmeasured_problems(profile)


def driver_hold_overdue(profile: Mapping[str, Any], today: dt.date | None = None) -> str | None:
    """A note when the held driver's re-test is past due (doctor shows it as a WARN), else None."""
    hold = profile.get("driver_hold") or {}
    nxt = hold.get("next_retest_by")
    today = today or dt.date.today()
    if isinstance(nxt, dt.date) and today > nxt:
        return f"driver {hold.get('version')} hold: re-test was due {nxt} ({hold.get('decision')})"
    return None


# ------------------------------------------------------------------------------------------------ compose checks
def _published(svc: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    ports = []
    for p in svc.get("ports") or []:
        if isinstance(p, Mapping):
            if p.get("published") not in (None, ""):
                ports.append(p)
        else:  # short syntax (an unrendered file): [host_ip:]published:target
            parts = str(p).rsplit(":", 2)
            if len(parts) >= 2:
                ports.append({"host_ip": parts[0] if len(parts) == 3 else "", "published": parts[-2]})
    return ports


def _env(svc: Mapping[str, Any]) -> dict[str, str]:
    env = svc.get("environment") or {}
    if isinstance(env, list):
        pairs = (str(e).partition("=") for e in env)
        return {k: v for k, _eq, v in pairs}
    return {str(k): "" if v is None else str(v) for k, v in env.items()}


def _aliases(svc: Mapping[str, Any], network: str) -> list[str]:
    nets = svc.get("networks") or {}
    if isinstance(nets, list):
        return []
    return list((nets.get(network) or {}).get("aliases") or [])


def compose_problems(role: str, config: Mapping[str, Any], profile: Mapping[str, Any]) -> list[str]:
    """What is wrong with one device's rendered compose for the two-device form; empty when it is right.

    ``config`` is ``docker compose config --format json`` for that device's services (compose adds their
    dependencies, so a Spark config that pulls in the database shows up here).
    """
    peer = peer_of(role)
    services: Mapping[str, Any] = config.get("services") or {}
    want = list((profile.get("devices") or {}).get(role) or [])
    theirs = set((profile.get("devices") or {}).get(peer) or []) - {"link"}
    out: list[str] = [f"{s} is not in the {role} config" for s in want if s not in services]
    for name in sorted(services):
        if role == "spark" and name not in want:
            out.append(f"{name} runs on the Spark (the Spark holds the gateway and the models only)")
        elif role == "workstation" and name in theirs:
            out.append(f"{name} runs on the workstation (it belongs on the Spark)")
    link = services.get("link")
    addr = ""
    if link is not None:
        env = _env(link)
        addr = env.get("TB_LINK_ADDR", "")
        if env.get("TB_LINK_ROLE") != role:
            out.append(f"link: TB_LINK_ROLE is {env.get('TB_LINK_ROLE')!r}, not {role}")
        if not env.get("TB_LINK_PEER"):
            out.append("link: TB_LINK_PEER (the other device's address) is not set")
        elif env.get("TB_LINK_PEER") == addr:
            out.append("link: TB_LINK_PEER is this device's own address")
        if addr in ANY_ADDRESS:
            out.append("link: TB_LINK_ADDR must be this device's address on the hospital network, not every address")
        for alias in ROUTES[peer]:
            if alias not in _aliases(link, "trialbox-net"):
                out.append(f"link: does not answer to {alias} on trialbox-net (the {peer}'s route)")
        if not any(
            "tb_link" in str(v.get("target", v) if isinstance(v, Mapping) else v) for v in link.get("volumes") or []
        ):
            out.append("link: the certificates (/run/secrets/tb_link) are not mounted")
    for name, svc in sorted(services.items()):
        if svc.get("network_mode") == "host":
            out.append(f"{name}: network_mode host (it would listen on every address of the {role})")
        for p in _published(svc):
            ip = str(p.get("host_ip") or "")
            if name == "link":
                if ip != addr or ip in ANY_ADDRESS:
                    out.append(f"link: published on {ip or ANY_ADDRESS[1]}, not only on the link address {addr or '?'}")
            elif role == "spark":
                where = ANY_ADDRESS[1] if ip in ANY_ADDRESS else ip
                out.append(f"{name}: a listener on {where}:{p.get('published')} on the Spark (only the link listens)")
            elif ip in ANY_ADDRESS and name != "console":
                out.append(f"{name}: published on every address of the workstation")
    limits = memory_limits(profile)
    for name in want:
        svc = services.get(name)
        if svc is None or name not in limits:
            continue
        got = _gib(
            svc.get("mem_limit") or ((svc.get("deploy") or {}).get("resources") or {}).get("limits", {}).get("memory")
        )
        if role == "spark" and got is None:
            out.append(f"{name}: no memory limit on the Spark (the profile says {limits[name]:g} GiB)")
        elif got is not None and abs(got - limits[name]) > 0.01:
            out.append(f"{name}: memory limit {got:g} GiB, the profile says {limits[name]:g} GiB")
    return out


def compose_config_for(role: str, path: Path | None, deploy: Path) -> dict[str, Any] | None:
    """The device's rendered compose: the file given, else ``docker compose config`` of its services in ``deploy``.

    The deploy folder's ``.env`` names the compose files (``COMPOSE_FILE``). None when it cannot be rendered (no
    docker, a broken file, an unknown role): doctor then fails the check and says so.
    """
    if path is not None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    if role not in ROLES:
        return None
    services = list((load_profile().get("devices") or {}).get(role) or [])
    cmd = ["docker", "compose", "--project-directory", str(deploy), "config", "--format", "json", *services]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)  # nosec B603: fixed argv
        doc = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


# ------------------------------------------------------------------------------------------------ the relay
@dataclass
class LinkConfig:
    role: str
    peer_host: str
    certs: Path
    port: int = LINK_PORT
    peer_port: int = LINK_PORT
    bind: str = "0.0.0.0"  # nosec B104: inside the link container; compose publishes it on TB_LINK_ADDR only
    routes: Mapping[str, tuple[str, int]] = field(default_factory=dict)  # exported: name -> (host, port)
    imports: Mapping[str, int] = field(default_factory=dict)  # imported: name -> local port

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> LinkConfig:
        role = env.get("TB_LINK_ROLE", "")
        peer = peer_of(role)
        host = env.get("TB_LINK_PEER", "")
        if not host:
            raise ValueError("TB_LINK_PEER (the other device's address) is not set")
        port = int(env.get("TB_LINK_PORT") or LINK_PORT)
        return cls(
            role=role,
            peer_host=host,
            certs=Path(env.get("TB_LINK_CERTS") or "/run/secrets/tb_link"),
            port=port,
            peer_port=int(env.get("TB_LINK_PEER_PORT") or port),
            routes=ROUTES[role],
            imports={name: p for name, (_h, p) in ROUTES[peer].items()},
        )


def _context(cfg: LinkConfig, server: bool) -> ssl.SSLContext:
    purpose = ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH
    ctx = ssl.create_default_context(purpose, cafile=str(cfg.certs / "ca.pem"))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(str(cfg.certs / f"{cfg.role}.pem"), str(cfg.certs / f"{cfg.role}.key"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = not server
    return ctx


def _peer_is(writer: asyncio.StreamWriter, role: str) -> bool:
    cert = writer.get_extra_info("peercert") or {}
    names = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    return link_name(role) in names


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, ssl.SSLError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def _splice(
    a: tuple[asyncio.StreamReader, asyncio.StreamWriter], b: tuple[asyncio.StreamReader, asyncio.StreamWriter]
) -> None:
    await asyncio.gather(_pipe(a[0], b[1]), _pipe(b[0], a[1]))


class Link:
    """One device's end of the link: the TLS listener for the peer and the plain listeners for the imports."""

    def __init__(self, cfg: LinkConfig) -> None:
        self.cfg = cfg
        self.servers: list[asyncio.Server] = []
        self.refused = 0  # connections that got no route (wrong peer, bad header, unknown route)

    async def start(self) -> None:
        cfg = self.cfg
        srv = await asyncio.start_server(self._from_peer, cfg.bind, cfg.port, ssl=_context(cfg, server=True))
        self.servers.append(srv)
        if cfg.port == 0:  # a test asked for any free port
            cfg.port = srv.sockets[0].getsockname()[1]
        self._client_ctx = _context(cfg, server=False)
        for name, port in cfg.imports.items():
            s = await asyncio.start_server(functools.partial(self._to_peer, name), cfg.bind, port)
            self.servers.append(s)

    def import_port(self, name: str) -> int:
        """The bound port of an import (the configured one, or the free one a test asked for with 0)."""
        names = list(self.cfg.imports)
        return int(self.servers[1 + names.index(name)].sockets[0].getsockname()[1])

    async def close(self) -> None:
        for s in self.servers:
            s.close()
        for s in self.servers:
            with contextlib.suppress(Exception):
                await s.wait_closed()

    async def _refuse(self, writer: asyncio.StreamWriter, why: str) -> None:
        self.refused += 1
        print(f"link: refused: {why}", file=sys.stderr, flush=True)
        with contextlib.suppress(Exception):
            writer.write(b"ERR\n")
            await writer.drain()
            writer.close()

    async def _from_peer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # the TLS handshake already required a certificate of the link CA; it must also name the peer device
        if not _peer_is(writer, peer_of(self.cfg.role)):
            await self._refuse(writer, "the certificate does not name the peer device")
            return
        try:
            line = await asyncio.wait_for(reader.readline(), HEADER_TIMEOUT_S)
        except (TimeoutError, ConnectionError, ssl.SSLError, ValueError, OSError):
            await self._refuse(writer, "no route header")
            return
        name = line[len(HELLO) :].strip().decode("ascii", "replace") if line.startswith(HELLO) else ""
        if len(line) > HEADER_MAX or name not in self.cfg.routes:
            await self._refuse(writer, f"unknown route {name!r}")
            return
        host, port = self.cfg.routes[name]
        try:
            target = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT_S)
        except (TimeoutError, OSError) as exc:
            await self._refuse(writer, f"{name}: {host}:{port} unreachable ({type(exc).__name__})")
            return
        writer.write(b"OK\n")
        await writer.drain()
        await _splice((reader, writer), target)

    async def _to_peer(self, name: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        cfg = self.cfg
        try:
            peer = await asyncio.wait_for(
                asyncio.open_connection(
                    cfg.peer_host, cfg.peer_port, ssl=self._client_ctx, server_hostname=link_name(peer_of(cfg.role))
                ),
                CONNECT_TIMEOUT_S,
            )
            peer[1].write(HELLO + name.encode("ascii") + b"\n")
            await peer[1].drain()
            ok = await asyncio.wait_for(peer[0].readline(), HEADER_TIMEOUT_S)
        except (TimeoutError, ConnectionError, ssl.SSLError, OSError) as exc:
            print(f"link: {name}: peer {cfg.peer_host}:{cfg.peer_port}: {type(exc).__name__}", file=sys.stderr)
            writer.close()
            return
        if ok != b"OK\n":
            print(f"link: {name}: the peer refused the route", file=sys.stderr)
            writer.close()
            peer[1].close()
            return
        await _splice((reader, writer), peer)


async def _serve(cfg: LinkConfig) -> None:
    link = Link(cfg)
    await link.start()
    print(
        f"link: {cfg.role} on :{cfg.port} (exports {', '.join(cfg.routes)}; imports {', '.join(cfg.imports)} "
        f"from {cfg.peer_host}:{cfg.peer_port})",
        flush=True,
    )
    await asyncio.gather(*(s.serve_forever() for s in link.servers))


# ------------------------------------------------------------------------------------------------ the ceremony
def make_certs(out: Path, days: int = 825) -> list[Path]:
    """A new link CA and a certificate per device (EC P-256); the CA key stays in memory and is dropped."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = dt.datetime.now(dt.UTC)
    until = now + dt.timedelta(days=days)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "trialbox link CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(until)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    out.mkdir(parents=True, exist_ok=True)
    written = [out / "ca.pem"]
    written[0].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for role in ROLES:
        key = ec.generate_private_key(ec.SECP256R1())
        name = link_name(role)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(until)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        pem, kfile = out / f"{role}.pem", out / f"{role}.key"
        pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        kfile.touch(mode=0o600)
        kfile.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        os.chmod(kfile, 0o600)
        written += [pem, kfile]
    return written


# ------------------------------------------------------------------------------------------------ selftest
async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await _pipe(reader, writer)


async def _try_raw(port: int, ctx: ssl.SSLContext, header: bytes) -> bytes:
    """Connect to a link's TLS port with ``ctx`` and send ``header``: what came back (empty when refused)."""
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port, ssl=ctx, server_hostname=link_name("spark")), 5
        )
        w.write(header)
        await w.drain()
        got = await asyncio.wait_for(r.readline(), 5)
        w.close()
        return got
    except (TimeoutError, ConnectionError, ssl.SSLError, OSError):
        return b""


async def selftest_async(tmp: Path) -> list[tuple[str, bool]]:
    """Both ends on 127.0.0.1 with fresh certificates; one (name, passed) per case."""
    good, other = tmp / "good", tmp / "other"
    make_certs(good, days=1)
    make_certs(other, days=1)
    echo = await asyncio.start_server(_echo, "127.0.0.1", 0)
    echo_port = echo.sockets[0].getsockname()[1]
    spark = Link(LinkConfig("spark", "127.0.0.1", good, port=0, bind="127.0.0.1",
                            routes={"gateway": ("127.0.0.1", echo_port)}))  # fmt: skip
    await spark.start()
    ws = Link(LinkConfig("workstation", "127.0.0.1", good, port=0, peer_port=spark.cfg.port, bind="127.0.0.1",
                         routes={}, imports={"gateway": 0}))  # fmt: skip
    await ws.start()
    out: list[tuple[str, bool]] = []
    try:
        r, w = await asyncio.open_connection("127.0.0.1", ws.import_port("gateway"))
        w.write(b"ping through the link\n")
        await w.drain()
        got = await asyncio.wait_for(r.readline(), 5)
        w.close()
        out.append(("an authenticated peer reaches the exported route", got == b"ping through the link\n"))

        bare = ssl.create_default_context(cafile=str(good / "ca.pem"))  # trusts the link CA, has no certificate
        out.append(
            (
                "a peer without a certificate is refused",
                await _try_raw(spark.cfg.port, bare, HELLO + b"gateway\n") != b"OK\n",
            )
        )

        alien = ssl.create_default_context(cafile=str(good / "ca.pem"))
        alien.load_cert_chain(str(other / "workstation.pem"), str(other / "workstation.key"))
        out.append(
            (
                "a peer of another link CA is refused",
                await _try_raw(spark.cfg.port, alien, HELLO + b"gateway\n") != b"OK\n",
            )
        )

        same = ssl.create_default_context(cafile=str(good / "ca.pem"))
        same.load_cert_chain(str(good / "spark.pem"), str(good / "spark.key"))
        out.append(
            (
                "a peer that names this device, not the other, is refused",
                await _try_raw(spark.cfg.port, same, HELLO + b"gateway\n") != b"OK\n",
            )
        )

        right = ssl.create_default_context(cafile=str(good / "ca.pem"))
        right.load_cert_chain(str(good / "workstation.pem"), str(good / "workstation.key"))
        out.append(("an unknown route is refused", await _try_raw(spark.cfg.port, right, HELLO + b"db\n") == b"ERR\n"))
    finally:
        await ws.close()
        await spark.close()
        echo.close()
    return out


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="tb-link-") as tmp:
        results = asyncio.run(selftest_async(Path(tmp)))
    for name, passed in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    return 0 if results and all(p for _n, p in results) else 1


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.two_device", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("link", help="run this device's end of the link (TB_LINK_* from the environment)")
    c = sub.add_parser("certs", help="install ceremony: a link CA and one certificate per device")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--days", type=int, default=825)
    k = sub.add_parser("check", help="one device's rendered compose against the GB10 profile")
    k.add_argument("--role", choices=ROLES, required=True)
    k.add_argument("--compose-config", type=Path, required=True, help="docker compose config --format json <services>")
    k.add_argument("--profile", type=Path, default=PROFILE_PATH)
    p = sub.add_parser("profile", help="the GB10 profile's own checks")
    p.add_argument("--profile", type=Path, default=PROFILE_PATH)
    sub.add_parser("selftest", help="both ends on this host: a round trip, then three refusals")
    a = ap.parse_args(argv)
    if a.cmd == "link":
        asyncio.run(_serve(LinkConfig.from_env(os.environ)))
        return 0
    if a.cmd == "certs":
        for f in make_certs(a.out, a.days):
            print(f"wrote {f}")
        print("the CA key was not kept; copy ca.pem and each device's own pair to that device only")
        return 0
    if a.cmd == "selftest":
        return selftest()
    profile = load_profile(a.profile)
    if a.cmd == "profile":
        bad = profile_problems(profile)
    else:
        bad = compose_problems(a.role, json.loads(a.compose_config.read_text(encoding="utf-8")), profile)
    for line in bad:
        print(f"FAIL  {line}")
    print("ok" if not bad else f"{len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
