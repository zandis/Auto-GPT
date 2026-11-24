"""The bench CI jobs' one way out (card H-105): an HTTPS tunnel to the hosts on the allow-list, and nothing else.

The jobs' network is internal (no route out); this proxy is on it and on an outward network. It accepts ``CONNECT
host:443`` only, for a host the allow-list names (an exact name, or ``.suffix`` for any name under it), and refuses
an address written as a number and a name that resolves to a private, loopback, link-local or otherwise non-public
address, so that a job cannot reach the bench host, its neighbours or the walk's box through it. It logs the host
and the verdict, never a path or a header. Standard library only: the job image's python3 runs it.

    python3 egress_proxy.py --listen ADDR:PORT --allow github.com,.actions.githubusercontent.com,pypi.org
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import re
import socket
import sys
from collections.abc import Sequence

PORT = 443
HEADER_BYTES = 8192
HEADER_SECONDS = 30
CONNECT_SECONDS = 30
_NAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def parse_allow(text: str) -> tuple[frozenset[str], tuple[str, ...]]:
    """``"a.org,.b.com"`` -> exact names and suffixes; an entry that is not a host name is refused."""
    exact: set[str] = set()
    suffixes: list[str] = []
    for raw in (p.strip().lower() for p in text.split(",")):
        if not raw:
            continue
        name = raw[1:] if raw.startswith(".") else raw
        if not _NAME.match(name):
            raise ValueError(f"not a host name on the allow-list: {raw!r}")
        if raw.startswith("."):
            suffixes.append("." + name)
        else:
            exact.add(name)
    if not exact and not suffixes:
        raise ValueError("the allow-list is empty: a job could reach nothing")
    return frozenset(exact), tuple(suffixes)


def allowed(host: str, exact: frozenset[str], suffixes: Sequence[str]) -> bool:
    host = host.lower().rstrip(".")
    if not _NAME.match(host):
        return False  # an address written as a number, or not a name at all
    return host in exact or any(host.endswith(s) for s in suffixes)


NAT64 = ipaddress.ip_network("64:ff9b::/96")
V4_COMPATIBLE = ipaddress.ip_network("::/96")
SITE_LOCAL = ipaddress.ip_network("fec0::/10")


def public(addr: str) -> bool:
    """A global unicast address. An IPv4 address carried in IPv6 is judged by its IPv4 address (the review of #1448,
    L-1448-8): NAT64 (64:ff9b::/96) and IPv4-mapped; IPv4-compatible (::/96) and site-local (fec0::/10) are refused."""
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        elif ip in V4_COMPATIBLE or ip in SITE_LOCAL:
            return False
    return ip.is_global and not ip.is_multicast


async def connect_any(addrs: Sequence[str]) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Each checked address in turn, the first that answers (L-1448-9: an IPv6 address first on a network with no IPv6
    route must not make the name unreachable)."""
    last: Exception = OSError("no address")
    for addr in addrs:
        try:
            return await asyncio.wait_for(asyncio.open_connection(addr, PORT), CONNECT_SECONDS)
        except (OSError, TimeoutError) as exc:
            last = exc
    raise last


def parse_connect(head: bytes) -> tuple[str, int] | None:
    """The target of ``CONNECT host:port HTTP/1.x``; anything else is None (refused)."""
    try:
        line = head.split(b"\r\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    m = re.fullmatch(r"CONNECT ([A-Za-z0-9.-]+):(\d{1,5}) HTTP/1\.[01]", line)
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def decide(target: tuple[str, int] | None, exact: frozenset[str], suffixes: Sequence[str]) -> str:
    """'' to go on to the address check, else the reason for a refusal."""
    if target is None:
        return "not a CONNECT request"
    host, port = target
    if port != PORT:
        return f"port {port} (only {PORT})"
    if not allowed(host, exact, suffixes):
        return "host not on the allow-list"
    return ""


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


class Proxy:
    def __init__(self, exact: frozenset[str], suffixes: Sequence[str]) -> None:
        self.exact = exact
        self.suffixes = tuple(suffixes)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEADER_SECONDS)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ConnectionError):
            writer.close()
            return
        target = parse_connect(head)
        why = decide(target, self.exact, self.suffixes)
        upstream: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
        if not why and target is not None:
            host = target[0]
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(host, PORT, type=socket.SOCK_STREAM)
                addrs = [str(i[4][0]) for i in infos]
                if not addrs or not all(public(a) for a in addrs):
                    why = "the name resolves to an address that is not public"
                else:
                    upstream = await connect_any(addrs)
            except (OSError, TimeoutError) as exc:
                why = f"no connection ({type(exc).__name__})"
        host_text = target[0] if target else "-"
        if why or upstream is None:
            print(f"egress: refused {host_text}: {why}", flush=True)
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        print(f"egress: allowed {host_text}", flush=True)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        up_reader, up_writer = upstream
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


async def serve(listen: str, proxy: Proxy) -> None:
    host, _, port = listen.rpartition(":")
    server = await asyncio.start_server(proxy.handle, host, int(port), limit=HEADER_BYTES)
    async with server:
        await server.serve_forever()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", required=True, help="ADDR:PORT on the jobs' network")
    ap.add_argument("--allow", required=True, help="comma-separated host names; .suffix for any name under it")
    args = ap.parse_args(argv)
    try:
        exact, suffixes = parse_allow(args.allow)
    except ValueError as exc:
        print(f"egress: {exc}", file=sys.stderr)
        return 2
    print(f"egress: {len(exact)} host(s) and {len(suffixes)} suffix(es) allowed, port {PORT} only", flush=True)
    asyncio.run(serve(args.listen, Proxy(exact, suffixes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
