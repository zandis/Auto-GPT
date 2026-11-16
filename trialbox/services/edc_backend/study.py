"""The study link and the nightly read, when ``TB_EDC_BACKEND`` is set (D-916).

Unset, :func:`open_client` returns ``None`` and the caller keeps the URL and token saved on S36.
``content=user`` is never requested: a user export can carry staff e-mail addresses.
"""

from __future__ import annotations

from typing import Any

from rc_bridge.client import INPROC_PREFIX, RcError, RedcapClient, major_of

from edc_backend.config import load_config
from edc_backend.connection import ACCEPTED_MAJORS, Pace

_pace: Pace | None = None
_pace_key: tuple[int, int] | None = None


def _shared_pace(min_interval_ms: int, max_per_minute: int) -> Pace:
    global _pace, _pace_key
    key = (min_interval_ms, max_per_minute)
    if _pace is None or _pace_key != key:
        _pace = Pace(min_interval_ms, max_per_minute)
        _pace_key = key
    return _pace


def backend_on() -> bool:
    return bool(load_config().kind)


def accept_version(rc: RedcapClient) -> str:
    """13 through 17 when the backend is on; the study link's own list (14 through 17) when it is not."""
    if not backend_on():
        return rc.check_version()
    version = rc.version()
    if major_of(version) not in ACCEPTED_MAJORS:
        raise RcError("RC-VERSION", f"REDCap {version} is outside the majors this backend accepts (13 through 17)")
    return version


def open_client(store: Any, token_ref: str) -> RedcapClient | None:
    """The connector's client for this token name, or ``None`` when the backend is off."""
    cfg = load_config()
    if not cfg.kind:
        return None
    if not cfg.url:
        which = "TB_EDC_INTERNAL_URL" if cfg.kind == "internal" else "TB_REDCAP_API_URL"
        raise RcError("RC-UPSTREAM", f"{which} is not set")
    token = cfg.tokens.get(token_ref.strip().lower()) or ""
    if not token and store is not None:
        saved = store.token(token_ref)
        token = saved or ""
    if not token:
        token = cfg.default_token
    if not token:
        raise RcError("RC-TOKEN", "the EDC backend is on and this link has no token")
    _shared_pace(cfg.min_interval_ms, cfg.max_per_minute).wait()
    if cfg.url.startswith(INPROC_PREFIX):
        return RedcapClient(cfg.url, token)
    return RedcapClient(cfg.url, token, loopback_http=cfg.loopback_http, declare_host=True)
