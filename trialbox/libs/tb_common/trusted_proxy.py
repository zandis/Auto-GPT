"""The proxies the console trusts for forwarded headers (H-137; the owner's decision on #639, 7156806411 item 7).

One named list, ``TB_CONSOLE_FORWARDED_ALLOW_IPS`` (uvicorn's ``--forwarded-allow-ips``): only a request from an
address on it may say, in ``X-Forwarded-For``, which browser it carries. The per-account-and-address sign-in lock
(D-279) and the audit's source address read what that header gives.

* On a box the front proxy (Caddy, ``deploy/docker-compose.identity.yml``) has a fixed address on the box's internal
  network (:data:`DEFAULT_PROXY_ADDR` in :data:`DEFAULT_SUBNET`), and the installer writes that address into the list.
  The installer stops when the internal network's range clashes with one of the hospital's ranges this host is on.
* On the cluster form the site names its ingress range in ``deploy/platform/base/site.env``.
* "All" (``*``, ``all``, ``0.0.0.0/0``, ``::/0``) lets any client choose its own address: the console refuses to start
  with it in PRODUCTION, and the doctor fails it there.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping

NAME = "TB_CONSOLE_FORWARDED_ALLOW_IPS"
DEFAULT_SUBNET = "172.31.252.0/24"  # the box's internal network (trialbox-net), fixed so the proxy's address is
DEFAULT_PROXY_ADDR = "172.31.252.250"  # Caddy's address on it
ALL = frozenset({"*", "all", "0.0.0.0/0", "::/0"})


def entries(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def trusts_all(value: str | None) -> bool:
    return any(x.lower() in ALL for x in entries(value))


def refusal(env: Mapping[str, str], environment: str) -> str | None:
    """Why the console must not start with this list, or None."""
    value = env.get(NAME)
    if environment == "PRODUCTION" and trusts_all(value):
        return (
            f"{NAME}={value!r} trusts every sender's X-Forwarded-For: any client could choose its own address, past "
            "the sign-in lock and into the audit. PRODUCTION refuses it: name the front proxy's address (a box) or "
            "the ingress range (a cluster)"
        )
    return None


def clashes(subnet: str, host_networks: Iterable[str]) -> list[str]:
    """The host's networks (addresses with their prefix, or routes) that overlap the internal network's range."""
    inner = ipaddress.ip_network(subnet, strict=False)
    out = []
    for raw in host_networks:
        try:
            net = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if net.version == inner.version and net.prefixlen > 0 and net.overlaps(inner):
            out.append(str(net))
    return sorted(set(out))
