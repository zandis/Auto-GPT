"""H-113: the model-quality suites' key to the local model servers (``TB_LLM_EVAL_KEY``).

The box's model servers sit behind model-guard, which wants ``Authorization: Bearer <key>`` on every call (D-177),
as the gateway sends it. The suites marked ``llm`` call the endpoint directly, so they take the same key from
``TB_LLM_EVAL_KEY`` through :func:`eval_client`, the one way every such suite builds its client.

* **Unset or empty:** the client is exactly the plain ``LlmClient(url, model)`` of before, byte for byte.
* **Set:** the key goes as a Bearer credential on a request only when that request's host is the host of the suite's
  own endpoint setting *and* that host is local (:func:`is_local`). The check runs on every request, so a call to any
  other host never carries it. :func:`eval_client` refuses a set key with an endpoint that is not local.
* **Local** means exactly one of: a loopback name or address (``localhost``, ``*.localhost``, ``127.0.0.0/8``,
  ``::1``); one of the box's model service names on its compose networks (:data:`SERVICE_NAMES`); a private or
  link-local IP address written as such (``10/8``, ``172.16/12``, ``192.168/16``, ``169.254/16``, ``fc00::/7``,
  ``fe80::/10``). Any other name, dotted or not, and any public address is not local.
* The key must be one printable ASCII token: one with a space, CR, tab or control byte is refused before any call
  (the HTTP layer's own refusal would quote it). It is never in a URL, a log line, an exception text or a repr.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Generator, Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from tb_common.llm import LlmClient

ENV = "TB_LLM_EVAL_KEY"
# model-guard and the names it answers to on model-net, and the model servers' own names (deploy/docker-compose*.yml)
SERVICE_NAMES = frozenset({"model-guard", "llm-service", "llm-verifier", "llm-service-vllm", "llm-verifier-vllm"})
_PRIVATE = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10")
)


def is_local(host: str) -> bool:
    """True when ``host`` is local in the sense above; anything else, the empty host included, is not."""
    h = (host or "").strip().lower().rstrip(".").strip("[]")
    if not h:
        return False
    if h == "localhost" or h.endswith(".localhost") or h in SERVICE_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_loopback or any(ip in net for net in _PRIVATE)


def endpoint_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class _Key:
    """The key's holder: its repr and str never show it."""

    __slots__ = ("_v",)

    def __init__(self, value: str) -> None:
        self._v = value

    def __repr__(self) -> str:
        return "<redacted>"

    __str__ = __repr__

    def header(self) -> str:
        return "Bearer " + self._v


class LocalBearer(httpx.Auth):
    """Adds the Bearer key to a request whose host is ``host`` and local; any other request goes without it."""

    def __init__(self, host: str, key: str) -> None:
        self.host = host.lower()
        self._key = _Key(key)

    def __repr__(self) -> str:
        return f"LocalBearer(host={self.host!r})"

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        host = (request.url.host or "").lower()
        if host == self.host and is_local(host):
            request.headers["Authorization"] = self._key.header()
        yield request


def eval_client(url: str, model: str, env: Mapping[str, str] | None = None) -> LlmClient:
    """The suites' ``LlmClient`` for ``url``: with ``TB_LLM_EVAL_KEY`` set, the key goes to that local host only."""
    from tb_common.llm import LlmClient

    e = os.environ if env is None else env
    client = LlmClient(url, model)
    if not e.get(ENV):
        return client
    host = endpoint_host(url)
    if not is_local(host):
        raise ValueError(
            f"{ENV} is set but the endpoint host {host!r} is not local (loopback, a model service name or a private "
            "address): the key goes nowhere else"
        )
    key = e[ENV]
    if not all("!" <= ch <= "~" for ch in key):  # a space, CR or NUL: the HTTP layer's refusal would quote the key
        raise ValueError(f"{ENV} is set but is not one printable ASCII token (a stray space, CR or control byte?)")
    client.http.auth = LocalBearer(host, key)
    return client
