"""Where the EDC backend reads its settings. Tokens stay in the returned config and are never formatted into errors.

The names with a ``TB_`` prefix are the declared settings. ``REDCAP_API_URL``, ``REDCAP_API_TOKEN``,
``REDCAP_TOKEN_<ref>``, ``EDC_BACKEND`` and ``EDC_INTERNAL_URL`` / ``EDC_INTERNAL_TOKEN`` are the same settings
under the shorter names, used only when the ``TB_`` one is empty.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from rc_bridge.client import RcError, check_token
from tb_common.config import DECLARED

_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_TOKEN_PREFIX = "TB_REDCAP_TOKEN_"
_TOKEN_ALIAS = "REDCAP_TOKEN_"


class EdcConfigError(ValueError):
    """The backend was asked for and its settings do not make a connection. The message has no token."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class EdcConfig:
    """One chosen backend. ``tokens`` maps a project ref to its API token; ``default_token`` is the unnamed one."""

    kind: str
    url: str
    default_token: str
    tokens: dict[str, str]
    max_per_minute: int
    min_interval_ms: int
    file_max_bytes: int
    loopback_http: bool

    def __repr__(self) -> str:
        return (f"EdcConfig(kind={self.kind!r}, url_set={bool(self.url)}, "
                f"default_token_set={bool(self.default_token)}, projects={sorted(self.tokens)})")  # fmt: skip

    def token_for(self, project: str | None) -> str:
        if project:
            ref = project.strip().lower()
            if ref not in self.tokens:
                raise EdcConfigError("no API token is set for this project")
            return self.tokens[ref]
        if not self.default_token:
            raise EdcConfigError("no API token is set")
        return self.default_token


def _first(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def _whole(env: Mapping[str, str], name: str) -> int:
    raw = (env.get(name) or DECLARED[name].default).strip()
    try:
        number = int(raw)
    except ValueError as exc:
        raise EdcConfigError(f"{name} must be a whole number") from exc
    if number < 0:
        raise EdcConfigError(f"{name} must be zero or more")
    return number


def _pairs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        ref, sep, tok = part.partition(":")
        ref = ref.strip().lower()
        if not sep or not _REF.fullmatch(ref):
            raise EdcConfigError("a project token is written ref:TOKEN")
        try:
            out[ref] = check_token(tok)
        except RcError as exc:
            raise EdcConfigError(exc.message) from exc
    return out


def _prefixed(env: Mapping[str, str], prefix: str, into: dict[str, str], *, fill_only: bool = False) -> None:
    """The tokens named ``<prefix><ref>``. ``fill_only``: a ref already set keeps its token (the short alias)."""
    for key, val in env.items():
        if not key.startswith(prefix):
            continue
        ref = key[len(prefix) :].strip().lower()
        if not _REF.fullmatch(ref):
            raise EdcConfigError("a project token name is lower-case letters, digits, _ and -")
        try:
            token = check_token(val)
        except RcError as exc:
            raise EdcConfigError(exc.message) from exc
        if not (fill_only and ref in into):
            into[ref] = token


def load_config(environ: Mapping[str, str] | None = None) -> EdcConfig:
    """Read the backend settings. ``kind`` is ``""`` when nothing is selected."""
    env = os.environ if environ is None else environ
    kind = _first(env, "TB_EDC_BACKEND", "EDC_BACKEND").lower()
    if kind == "external":
        kind = "redcap"
    if kind not in ("", "redcap", "internal"):
        raise EdcConfigError("TB_EDC_BACKEND is redcap or internal")
    caps = (
        _whole(env, "TB_REDCAP_MAX_PER_MINUTE"),
        _whole(env, "TB_REDCAP_MIN_INTERVAL_MS"),
        _whole(env, "TB_REDCAP_FILE_MAX_BYTES"),
    )
    if not kind:  # unset: do not read tokens, and do not require a URL
        return EdcConfig("", "", "", {}, *caps, False)
    tokens = _pairs(_first(env, "TB_REDCAP_PROJECT_TOKENS"))
    _prefixed(env, _TOKEN_PREFIX, tokens)
    _prefixed(env, _TOKEN_ALIAS, tokens, fill_only=True)  # H-137: the short name only when no TB_ one names the ref
    if kind == "internal":
        url = _first(env, "TB_EDC_INTERNAL_URL", "EDC_INTERNAL_URL")
        default = _first(env, "TB_EDC_INTERNAL_TOKEN", "EDC_INTERNAL_TOKEN")
        loopback = True
    else:
        url = _first(env, "TB_REDCAP_API_URL", "REDCAP_API_URL")
        default = _first(env, "TB_REDCAP_API_TOKEN", "REDCAP_API_TOKEN")
        loopback = False
    try:
        default_token = check_token(default) if default else ""
    except RcError as exc:
        raise EdcConfigError(exc.message) from exc
    return EdcConfig(kind, url, default_token, tokens, *caps, loopback)
