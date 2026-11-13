"""One pinned file from the network, for an image build (D-632).

    python tools/fetch_pinned.py URL OUT SHA256

The file is asked for up to three times (waiting 2, then 5 seconds) when the transfer fails: a refused connection, a
timeout, an HTTP error, a short read. A mirror that answers 404 once and 200 a minute later does not fail a build.
What is written is the pinned sha256, or nothing is written; a file with another sha256 is refused at once and not
asked for again (that is not the network's fault). ``SSL_CERT_FILE`` names the build's CA file, as before.
Standard library only: the demo image runs it before anything is installed for it.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

WAITS = (2, 5)  # seconds before the second and the third ask; three asks in all, never more
TRANSFER_FAULTS = (urllib.error.URLError, OSError, http.client.HTTPException, TimeoutError)


class FetchError(RuntimeError):
    """The transfer failed on every try."""


class PinError(RuntimeError):
    """A download whose sha256 is not the pinned one."""


def _https(url: str) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise FetchError(f"{url}: only an https address is fetched")


def _get(url: str) -> bytes:
    """The bytes at an https address. The opener speaks https only (through the build's proxy, when one is set):
    no ``file:`` or ``ftp:`` handler is in it, and an answer that ended at another scheme after a redirect is
    refused."""
    _https(url)
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPRedirectHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    with opener.open(url, timeout=120) as resp:
        _https(resp.geturl())
        data: bytes = resp.read()
    return data


def fetch_bytes(
    url: str,
    sha256: str,
    *,
    get: Callable[[str], bytes] = _get,
    sleep: Callable[[float], None] = time.sleep,
    waits: tuple[float, ...] = WAITS,
) -> bytes:
    """The bytes at ``url`` when their sha256 is ``sha256``. :class:`FetchError` after the last failed try, with each
    try's reason; :class:`PinError` at once for other bytes."""
    _https(url)
    reasons: list[str] = []
    for n in range(len(waits) + 1):
        if n:
            sleep(waits[n - 1])
        try:
            data = get(url)
        except TRANSFER_FAULTS as exc:
            reasons.append(f"try {n + 1}: {type(exc).__name__}: {exc}")
            continue
        got = hashlib.sha256(data).hexdigest()
        if got != sha256:
            raise PinError(f"{url}: sha256 {got} is not the pinned {sha256}; refusing it")
        return data
    raise FetchError(f"{url}: not fetched in {len(waits) + 1} tries ({'; '.join(reasons)})")


def fetch(url: str, out: Path, sha256: str, **kw: object) -> None:
    """:func:`fetch_bytes` written to ``out``, only once the sha256 matched (no partial or unpinned file is left)."""
    data = fetch_bytes(url, sha256, **kw)  # type: ignore[arg-type]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("out", type=Path)
    ap.add_argument("sha256")
    ap.add_argument("--wait", type=float, default=None, help="seconds between tries (default: 2, then 5)")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{64}", a.sha256):
        print(f"fetch_pinned: {a.sha256!r} is not a sha256", file=sys.stderr)
        return 2
    waits = WAITS if a.wait is None else (a.wait,) * len(WAITS)
    try:
        fetch(a.url, a.out, a.sha256, waits=waits)
    except (FetchError, PinError) as exc:
        print(f"fetch_pinned: {exc}", file=sys.stderr)
        return 1
    print(f"{a.sha256}  {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
