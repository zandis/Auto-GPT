"""H-146 (D-1462): the model servers' prefix cache, one setting for the judge and the verifier.

The integrator's bench found that the model server's prefix cache makes runs differ: the same extraction calls gave
different answers from one run to the next with it on, and the same answers every run with it off. So the judge and
verifier servers start with ``--no-enable-prefix-caching`` unless the box chooses the cache.

The setting is ``TB_LLM_PREFIX_CACHING`` in deploy/.env. Compose can only tell a variable set from unset, so the
value is the flag's own first word, and every GPU overlay's server command carries one line::

    - --${TB_LLM_PREFIX_CACHING:-no-enable}-prefix-caching

* absent, empty or ``no-enable``: ``--no-enable-prefix-caching`` (off, the default);
* ``enable``: ``--enable-prefix-caching`` (on, the explicit choice: runs may then differ);
* anything else renders an argument the model server refuses, so it does not start; doctor names the value.

Standard library only (doctor reads it on the host).
"""

from __future__ import annotations

from collections.abc import Mapping

SETTING = "TB_LLM_PREFIX_CACHING"
DEFAULT = "no-enable"
VALUES = ("no-enable", "enable")
WORDS = {"no-enable": "off", "enable": "on"}


def value(env: Mapping[str, str]) -> str:
    """The setting as compose reads it from deploy/.env: blanks and one pair of quotes dropped; empty is the
    default."""
    raw = (env.get(SETTING) or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    return raw or DEFAULT


def state(env: Mapping[str, str]) -> str:
    """``off`` or ``on``; :class:`ValueError` for a value that is neither (the server would not start)."""
    got = value(env)
    if got not in WORDS:
        raise ValueError(f"{SETTING}={got} is not no-enable or enable")
    return WORDS[got]


def flag(word: str) -> str:
    """The argument the servers render for ``off`` or ``on``."""
    return "--no-enable-prefix-caching" if word == "off" else "--enable-prefix-caching"
