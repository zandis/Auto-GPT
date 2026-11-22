"""Decode, then scrub (H-79, D-1358): the one place that undoes an encoding before a scrub reads a line.

Both scrubs that leave the box's text readable call it: the service log line (``tb_common.logging.redact``) and the
support bundle's scrub (its ``Scrubber.decoded``, under ``tools/``). Standard library only, so the host's python3 can
run it.

An encoding hides a value from a rule that reads the text as written: ``password%253DS``, ``password&#61;S``,
``a.b%40example.org``, ``a.b&#64;example.org``, ``\\u0040``, ``=3D``. :func:`decode_then_scrub` gives each line
that holds an encoded character to the caller's rules a second time, decoded; when the rules change the decoded
line, the line is kept decoded and scrubbed (its escapes are gone). A line the rules leave alone keeps its escapes.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import unquote

#: how many times an encoding is undone: ``%25252540`` is four layers of ``%`` round ``@``
LAYERS = 8

#: what an encoding makes of a character. Percent (``%40``, ``%2540``), a backslash escape (``\\x40``, ``\\u0040``,
#: ``\\U00000040``), an HTML entity named or numeric with or without its ``;`` (``&#64``, ``&#x40;``, ``&commat;``)
#: and a quoted-printable ``=`` or ``@`` (``=3D``, ``=40``). A false hit costs one decode, never a change.
ENCODED = re.compile(
    r"%[0-9A-Fa-f]{2}"
    r"|\\(?:u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2}|U[0-9A-Fa-f]{8})"
    r"|&#[0-9]{1,7}|&#[xX][0-9A-Fa-f]{1,6}|&[A-Za-z][A-Za-z0-9]{1,31};?"
    r"|=(?:3D|40)"
)
#: a backslash escape behind any number of backslashes: ``repr()`` and JSON double the backslash (``\\\\x3d``), a layer
_BACKSLASH = re.compile(r"\\+(?:u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|U([0-9A-Fa-f]{8}))")
_QP = re.compile(r"=([0-9A-F]{2})")


def _char(code: int) -> str:
    """A code point as a character: a surrogate or a value past Unicode is U+FFFD, so the line can be written."""
    if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
        return "�"
    return chr(code)


def _backslash(m: re.Match[str]) -> str:
    return _char(int(m.group(1) or m.group(2) or m.group(3), 16))


#: a numeric entity with no ``;`` read short: ``&#61`` then a digit is ``=`` and the digit, ``&#x40`` then ``e`` is
#: ``@e`` (an HTML reader takes every digit, ``&#611``). Only an ASCII character; never one a ``;`` closes.
_SHORT_ENTITY = re.compile(r"&#(?:[xX]([2-7][0-9A-Fa-f])(?![0-9A-Fa-f]*;)|(1[01][0-9]|12[0-6]|[3-9][0-9])(?![0-9]*;))")


def _short(m: re.Match[str]) -> str:
    return chr(int(m.group(1), 16)) if m.group(1) else chr(int(m.group(2)))


def decode(text: str, layers: int = LAYERS, *, short: bool = False) -> str:
    """``text`` with every encoding of :data:`ENCODED` undone, up to ``layers`` times (each pass undoes one layer of
    each kind, so a percent-encoded entity takes two). ``short`` reads a numeric entity without its ``;`` as the
    shortest ASCII character it can be. Linear in the text's length for each layer."""
    for _ in range(layers):
        new = unquote(text, errors="replace") if "%" in text else text
        if short and "&#" in new:
            new = _SHORT_ENTITY.sub(_short, new)
        if "&" in new:
            new = html.unescape(new)
        if "\\" in new:
            new = _BACKSLASH.sub(_backslash, new)
        if "=3D" in new or "=40" in new:
            new = _QP.sub(lambda m: chr(int(m.group(1), 16)), new)
        if new == text:
            break
        text = new
    return text


def decode_then_scrub(
    text: str, rules: Callable[[str], str], keep: Callable[[str, str, str], bool] | None = None
) -> tuple[str, int]:
    """``text`` with each line that holds an encoded character decoded and given to ``rules``; a line is replaced by
    its decoded, scrubbed form only when ``rules`` changed the decoded line and ``keep(line, decoded, scrubbed)``,
    when given, does not say the line may keep its own form (the bundle's H-76 rule). Returns the text and how many
    lines were replaced. A text with no encoded character costs one search."""
    if not ENCODED.search(text):
        return text, 0
    lines = text.split("\n")
    replaced = 0
    for k, line in enumerate(lines):
        if not ENCODED.search(line):
            continue
        for short in (False, True):  # the reading an HTML reader makes, then the short reading of ``&#61``
            if short and "&#" not in line and "%26%23" not in line.upper():
                break
            plain = decode(line, short=short)
            if plain == line:
                continue
            clean = rules(plain)
            if clean != plain:
                if keep is None or not keep(line, plain, clean):
                    lines[k] = clean
                    replaced += 1
                break
    return "\n".join(lines), replaced
