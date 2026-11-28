"""The support bundle's scrub (H-71, D-1354): the one function every byte of text in a support bundle passes through.

    from tools.bundle_scrub import scrub_text, Scrubber
    clean = scrub_text(text)                      # the rules, no per-bundle tag
    s = Scrubber.for_bundle(mrn=pattern)          # a bundle's scrubber: a fresh tag key, the site's chart number
    name, text = s.member(name, text)             # a member's name and its text

It is pure: the same text and the same scrubber always give the same result, and it reads nothing but the egress
edge's rules (asked of the box image when the host's python3 cannot load them: :class:`_Image`) and the
declarations of ``libs/tb_common/config.py`` and ``libs/tb_common/crypto.py`` (parsed, not imported: the bundle is
made by the host's python3, standard library only). Gate 5's ``prepare_output`` can call :func:`scrub_text` as it is.

What it replaces, in this order (the page ``docs/handover/support-bundle-scrub-2026-11-22.md`` lists what it does
not catch):

1. PEM blocks, whole (``[pem block removed]``), and credentials of a well-known shape (``CREDENTIALS``).
2. Secrets by their form: ``Bearer``/``Basic``/``Digest``/``Token`` values; URL userinfo (a user and a password
   between ``://`` and ``@``, plain and percent-encoded); every ``name=value``, ``name: value``, ``"name": value``
   and ``\\"name\\": value`` whose name is a secret's (a query string, a form body, a header, an
   ``.env`` or YAML line, JSON, a Python repr), with quoted values that run over several lines and YAML block values;
   ``Authorization``/``Cookie`` headers to the end of the line. A secret's name: any setting that
   ``libs/tb_common/config.py`` declares as a secret, a declared family marked so, and any name whose words say
   secret (:func:`secret_name`).
3. Patient tokens: the pseudonym (``PID_HEX_LEN`` hex digits, any case, ``tb_common.crypto.pid_for_mrn``) and its
   short form (8 hex digits and ``…``), and the screening number (``services/console/sitestore.py``: a prefix and at
   least four digits), each as ``[pseudonym]`` / ``[screening-no]``; a bundle's scrubber adds a tag (``#bcdfg``)
   from a key made for that bundle and never stored, so lines of one patient can be read together in one bundle and
   in no other.
4. The log scrubber's patterns (``tb_common.logging._PHI_PATTERNS``), the site's chart number, when given, and
   every named form of the egress edge (``tb_common.egress_edge.spans``, M3: the one rule set of what leaves).
"""

from __future__ import annotations

import ast
import base64
import binascii
import hashlib
import hmac
import html
import importlib
import itertools
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "libs" / "tb_common" / "config.py"
CRYPTO = ROOT / "libs" / "tb_common" / "crypto.py"

REDACTED = "[redacted]"
PEM_GONE = "[pem block removed]"


class ScrubError(RuntimeError):
    """The scrub cannot know its rules (a declaration it reads is missing): nothing may be scrubbed with fewer."""


# ------------------------------------------------------------------------------------------------ declarations
def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _assigned(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    return None


#: how a declaration's doc marks a secret: ``(secret)``, ``(secret; T-319)``, ``(D-1226; secret)``
SECRET_MARK = re.compile(r"[(;]\s*secret\s*[;),]")


@dataclass(frozen=True)
class Declarations:
    secret: frozenset[str]  # declared settings whose doc marks them secret
    families: tuple[str, ...]  # declared families (a prefix) marked secret or with a secret's name
    names: frozenset[str]  # every declared name and every name the Env map reads


@lru_cache(maxsize=8)
def declarations(config: Path = CONFIG) -> Declarations:
    """The secret settings as ``libs/tb_common/config.py`` declares them, read from its source (never imported)."""
    try:
        tree = ast.parse(config.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ScrubError(f"the setting declarations cannot be read ({type(exc).__name__})") from None
    declared, families, env_map = (_assigned(tree, n) for n in ("DECLARED", "DECLARED_FAMILIES", "_ENV_MAP"))
    if not isinstance(declared, ast.Dict) or not isinstance(families, ast.Dict):
        raise ScrubError("the setting declarations (DECLARED, DECLARED_FAMILIES) are not where the scrub reads them")
    secret: set[str] = set()
    names: set[str] = set()
    for k, v in zip(declared.keys, declared.values, strict=True):
        key = _const_str(k)
        if key is None:
            continue
        names.add(key)
        doc = ""
        if isinstance(v, ast.Call):
            parts = [*v.args, *(kw.value for kw in v.keywords if kw.arg == "doc")]
            doc = " ".join(s for s in (_const_str(p) for p in parts) if s)
        if SECRET_MARK.search(doc):
            secret.add(key)
    fams = []
    for k, v in zip(families.keys, families.values, strict=True):
        key, doc = _const_str(k), _const_str(v) or ""
        if key and (SECRET_MARK.search(doc) or secret_words(key)):
            fams.append(key)
    if isinstance(env_map, ast.Dict):
        names |= {s for s in (_const_str(k) for k in env_map.keys) if s}
    return Declarations(frozenset(secret), tuple(sorted(fams)), frozenset(names))


@lru_cache(maxsize=8)
def pid_hex_len(crypto: Path = CRYPTO) -> int:
    """``tb_common.crypto.PID_HEX_LEN``: how many hex digits a pseudonym has (D-09), read from its source."""
    try:
        node = _assigned(ast.parse(crypto.read_text(encoding="utf-8")), "PID_HEX_LEN")
    except (OSError, SyntaxError) as exc:
        raise ScrubError(f"the pseudonym's length cannot be read ({type(exc).__name__})") from None
    if not (isinstance(node, ast.Constant) and isinstance(node.value, int) and node.value >= 16):
        raise ScrubError("PID_HEX_LEN is not where the scrub reads it")
    return node.value


# ------------------------------------------------------------------------------------------------ secret names
#: words that make a name a secret's (a name is split at ``_ - . [ ]``, spaces and camelCase)
SECRET_WORDS = frozenset({
    "password", "passwd", "pass", "pwd", "pw", "secret", "token", "passphrase", "credential", "cookie", "session",
    "sessionid", "sid", "login", "auth", "authorization", "signature", "sig", "dsn", "salt", "pepper", "pin", "otp",
    "totp", "bearer", "jwt", "csrf", "xsrf", "apikey",
})  # fmt: skip
#: two words that make one: ``api_key``, ``privateKey``, ``X-Access-Key``
SECRET_PAIRS = frozenset({"apikey", "privatekey", "accesskey", "secretkey", "clientsecret", "authkey", "signingkey"})
#: a single word that ends so: ``csrftoken``, ``authtoken``, ``dbpassword``
SECRET_ENDINGS = ("token", "password", "passwd", "secret", "apikey", "passphrase", "cookie", "sessionid")
#: a name that ends so holds where a secret is or a number, never the secret (the builder's own rule, kept)
SAFE_NAME = re.compile(r"[_.\-](?:FILE|PATH|DIR|DAYS|HOURS|MODE|TARGETS)$", re.I)


def _words(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


@lru_cache(maxsize=4096)
def secret_words(name: str) -> bool:
    words = _words(name)
    singles = {w[:-1] if w.endswith("s") and w[:-1] in SECRET_WORDS else w for w in words}
    if singles & SECRET_WORDS or any(w.endswith(SECRET_ENDINGS) for w in words):
        return True
    if any(a + b in SECRET_PAIRS for a, b in itertools.pairwise(words)):
        return True
    # #1354 round 3: a secret's name under any case (``pAssWord``, ``ToKeN``): the camel-case split above cuts it, so
    # the whole name, lower case and without separators, is read as one word too
    whole = "".join(words)
    return whole in SECRET_WORDS or whole in SECRET_PAIRS or whole.endswith(SECRET_ENDINGS)


def secret_name(name: str, decl: Declarations | None = None) -> bool:
    """Whether the value next to ``name`` is a secret's: a setting declared secret, a secret family, or its words."""
    name = name.strip()
    upper = name.upper()
    if decl is not None and (upper in decl.secret or upper.startswith(decl.families)):
        return True  # declared secret: even a ``_FILE`` name (TB_ALLIANCE_SIGNING_KEY_FILE)
    if not name or SAFE_NAME.search(name):
        return False
    return secret_words(name)


#: values that say nothing about the secret (a flag, an empty value): kept, so the bundle still says it was set off
NOT_A_VALUE = frozenset({"", "true", "false", "yes", "no", "on", "off", "none", "null", "~", REDACTED.lower(),
                         "''", '""', "{}", "[]"})  # fmt: skip


def _keeps(value: str) -> bool:
    return value.strip().lower() in NOT_A_VALUE


# ------------------------------------------------------------------------------------------------ the rules
#: credentials of a well-known shape that no setting names (detect-secrets' core plugins, standard library only). A
#: private key is a whole block, so it is replaced as one, never line by line.
CREDENTIALS: dict[str, re.Pattern[str]] = {
    "private key": re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY"
        r"(?: BLOCK)?-----|\Z)",
        re.S,
    ),
    "AWS access key": re.compile(r"(?<![A-Z0-9])(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "GitHub token": re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"),
    "Slack token": re.compile(r"(?<![A-Za-z0-9])xox[abposr]-[A-Za-z0-9-]{10,}"),
    "JSON web token": re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
}


def hide_credentials(text: str) -> tuple[str, Counter[str]]:
    """Every credential of :data:`CREDENTIALS` becomes ``[credential removed: <kind>]``; the text and the counts."""
    found: Counter[str] = Counter()
    for kind, rx in CREDENTIALS.items():
        text, k = rx.subn(f"[credential removed: {kind}]", text)
        if k:
            found[kind] += k
    return text, found


PEM = re.compile(r"-----BEGIN [A-Z0-9 ]{1,64}-----.*?(?:-----END [A-Z0-9 ]{1,64}-----|\Z)", re.S)
SCHEME_TOKEN = re.compile(r"(?i)(?<![A-Za-z0-9])(bearer|basic|digest|token|negotiate)([ \t]+)([A-Za-z0-9._~+/=\-]{8,})")
#: URL userinfo up to the LAST ``@`` of the address: a password may hold ``/`` or ``@`` (review M1). The scheme
#: starts where no scheme character stands before it and the userinfo is at most 256 characters: one pass is linear
#: on a long run of letters or digits (review: the unanchored scheme took 32 s on a 100 KB line)
USERINFO = re.compile(
    r"(?i)(?<![A-Za-z0-9+.\-])([A-Za-z][A-Za-z0-9+.\-]{0,31}://)"
    r"([^\s\"'<>/@]{0,256}:[^\s\"<>]{0,256}|[^\s\"'<>/@]{1,256})(@)"
)
USERINFO_ENCODED = re.compile(r"(?i)(%3A%2F%2F)((?:(?!%2F|%40)[^/@\s\"'<>]){1,256})(%40)")
#: a command line's ``--password VALUE`` / ``-token VALUE`` (the ``=`` form is a pair)
FLAG = re.compile(r"(?<![\w\-])(?P<dash>--?)(?P<key>[A-Za-z][A-Za-z0-9_\-]{0,40})(?P<sep>[ \t]+)")
#: H76-05: a flag and its value as two items of a list: ``["--password", "X"]``, ``- --password`` then ``- X``
LIST_FLAG = re.compile(
    r"(?<![\w\-])(?P<q>[\"']?)--?(?P<key>[A-Za-z][A-Za-z0-9_\-]{0,40})(?P=q)"
    r"(?P<sep>[ \t]*,[ \t]*|[ \t]*\r?\n[ \t]*-[ \t]+)(?P<val>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'"
    r"|[^\"'\s,\[\]\-][^\"'\s,\]]*)"
)
#: ``curl -u user:password``, ``--user``, ``--proxy-user``
CLI_USER = re.compile(r"(?<![\w\-])(?P<key>-u|--user|--proxy-user|-U)(?P<sep>[ \t]+|=)(?P<user>[^\s:]*):(?P<val>\S+)")
#: ``<password>VALUE</password>`` (any namespace, any attributes)
XML = re.compile(r"<(?P<key>[^\W\d][\w.\-:]{0,80})(?P<attrs>\s[^<>]{0,512})?>(?P<val>[^<]{1,4096})</(?P=key)\s*>")
#: what an encoding makes of a character: ``%2F``, ``%252F``, ``\u002F``, ``\x2F``, ``&#x2F;``, ``&quot;``, ``=3D``
ENCODED = re.compile(
    "%u[0-9A-Fa-f]{4}|\\\\[0-3][0-7]{2}|[\uff10-\uff19\uff20-\uff3a\uff41-\uff5a]|%[0-9A-Fa-f]{2}|\\\\+[uxU][0-9A-Fa-f]{2}|&#?[A-Za-z0-9]{1,8};"
    "|&#[xX]?[0-9A-Fa-f]{1,6}|=[0-9A-F]{2}=[0-9A-F]{2}|=3D|[A-Za-z0-9]=40[A-Za-z0-9]"
    "|[\u200b-\u200d\u2060\ufeff\u00ad]"
)
#: H76-04: characters a reader does not see, which split a token in two for every rule
_FULL_WIDTH = re.compile("[\uff10-\uff19\uff20-\uff3a\uff41-\uff5a]")
INVISIBLE = re.compile("[\u200b-\u200d\u2060\ufeff\u00ad]")
#: H76-03: a pseudonym straight after what an encoding leaves of a character, whatever the layers: ``%2F``,
#: ``%25252F``, ``=B0`` (quoted-printable), ``&#47``/``&#x2f`` with or without ``;``, ``\\x2f``, ``\\u002f``. The
#: encoding's hex digits join the pseudonym's, so the plain rule (no hex digit beside it) cannot see it.
ENC_PID = (
    r"(?:%(?:25){0,16}[0-9A-Fa-f]{2}|=[0-9A-F]{2}|&#[0-9]{2,3};?|&#[xX][0-9A-Fa-f]{2};?"
    r"|\\+x[0-9A-Fa-f]{2}|\\+u[0-9A-Fa-f]{4}|\\+U[0-9A-Fa-f]{8}|%u[0-9A-Fa-f]{4}|\\+[0-3][0-7]{2})"
)
_BACKSLASH = re.compile(r"\\+(?:u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|U([0-9A-Fa-f]{8}))")
_QP = re.compile(r"=([0-9A-F]{2})")
_QP_RUN = re.compile(r"(?:=[0-9A-F]{2})+")
#: the review of #1354's list: ``%u002F`` (an old JavaScript escape) and a C octal escape (``\\057``)
_PCT_U = re.compile(r"%u([0-9A-Fa-f]{4})")
_OCTAL = re.compile(r"\\([0-3][0-7]{2})")
_QP_AT = re.compile(r"(?<=[A-Za-z0-9._%+\-])=40(?=[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){0,7}\.[A-Za-z]{2,24}\b)")
#: H76-09: a run that may be base64 (either alphabet, with or without padding); bounded so that one pass is linear
B64_RUN = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{8,4194304}={0,2}")
#: a PEM block's END line whose BEGIN is not in the text (a cut, a rotated log): the base64 lines before it go too
PEM_END = re.compile(r"-----END [A-Z0-9 ]{1,64}-----")
_B64 = re.compile(r"[A-Za-z0-9+/=]{16,}")
_KEY = r"[A-Za-z_][A-Za-z0-9_.\-\[\]]{0,80}"
#: a whole ``.env``/YAML/ini line: ``  - export NAME = value``, also commented out (``# NAME=value``: an old password)
LINE = re.compile(
    rf"^(?P<lead>\s*(?:(?:#+|//|;|>|[\w.\-]{{1,64}}[ \t]*\|)[ \t]*)?-?\s*(?:export\s+)?)"
    rf"(?P<key>{_KEY})(?P<sep>\s*[:=]\s*)(?P<val>.*)$"
)
#: ``name=value`` anywhere: a query string (also percent-encoded inside another URL), a form body, a log's pairs
PAIR = re.compile(rf"(?:(?<=%3[Ff])|(?<=%26)|(?<![A-Za-z0-9_.%]))(?P<key>{_KEY})(?P<sep>[ \t]*(?:=|%3[Dd])[ \t]*)")
VIEW_VALUE = re.compile(r"[^\n]+")
WORD = re.compile(r"\S+")
#: review 1634.1 R1: a flag's value: quoted (escaped quotes inside), to the line's end when the quote does not close
FLAG_VALUE = re.compile(r"\"(?:\\.|[^\"\\\n])*(?:\"|$)|'(?:\\.|[^'\\\n])*(?:'|$)|\S+", re.M)
PAIR_VALUE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|(?:(?!%26)[^\s&;,\"'<>(){}\[\]])+")
#: ``"name": value`` and ``'name': value`` (JSON, a Python repr), the value a string, a number, a word or a list
QUOTED = re.compile(
    r"(?P<q>[\"'])(?P<key>[^\"'\\\s]{1,80})(?P=q)"
    r"(?P<sep>[ \t]*(?::|=>|=)[ \t]*(?:\r?\n[ \t]*(?:(?:#+|//|;|>)[ \t]*)?)?)"
    r"(?P<val>\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|\[[^\]\n]*\]|-?\d[\d.eE+\-]*|[A-Za-z0-9_./+=~\-]+)"
)
#: the same inside a JSON string: ``\"name\": \"value\"``
ESCAPED = re.compile(r"(?P<q>\\+\")(?P<key>[^\"\\\s]{1,80})(?P=q)(?P<sep>\s*:\s*)(?P=q)(?P<val>.*?)(?P=q)")
#: ``name: value`` inside a line (a header, a log's words), to the end of the line or a quote
#: round 3: a key after ``/`` (``/token: v``) and a quoted value after an unquoted key (``{password: "S"}``, a JS
#: object, a YAML mapping) are taken too; round 4: an encoded space before the quote (``key:+"S"``, ``key:%20"S"``)
#: an encoded space a form or a URL writes before a quoted value
ENCODED_SPACE = re.compile(r"(?:\+|%20|%09)*")
COLON = re.compile(
    rf"(?<![A-Za-z0-9_.@\-])(?P<key>{_KEY})(?P<sep>[ \t]*:[ \t]*)(?!//)"
    r"(?P<val>(?:\+|%20|%09)*(?:\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*')|[^\r\n\"']+)"
)
HEADER = re.compile(
    r"(?im)(?<![A-Za-z0-9_\-])(?P<key>authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token)"
    r"(?P<sep>[ \t]*:[ \t]*)(?P<val>[^\r\n\"']+)"
)
UUID = re.compile(r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])")
DIGEST = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{40,}(?![0-9A-Za-z])")
COMMENT = re.compile(r"^\s*(?:#+|//|;|>|[\w.\-]{1,64}[ \t]*\|)")
SINGLE = re.compile(r"[ \t]*[^\s:]+[ \t]*")
MAPPING_KEY = re.compile(r"^\s*-?\s*[A-Za-z_\"'][\w.\-\"' ]{0,80}:(?:\s|$)")
YAML_BLOCK = re.compile(r"^[|>][+\-]?\d*\s*(?:#.*)?$")

#: H-76 round B: an e-mail address, masked as ``[email]``. Left alone (each tested): a package and its version
#: (``lodash@4.17.21``: no top-level name), an scp-style git address (``git@github.com:org/repo``: ``:`` and a path
#: after the host), an image digest (``name@sha256:...``: no dot), a user at a host with no top-level name
#: (``root@box01``), and a DSN's userinfo (already a secret's form).
EMAIL = re.compile(
    r"(?<![\w.+%\-@])[A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.){1,8}"
    r"[A-Za-z]{2,24}(?![\w\-@]|:[\w/~])"
)
#: H-76 round B: the labels of a person's identifiers in the box's three languages; the VALUE after them is masked
LABELS_CJK = {
    "患者氏名": "name", "病患姓名": "name", "病人姓名": "name", "患者姓名": "name", "患者名": "name", "氏名": "name",
    "名前": "name", "姓名": "name", "出生年月日": "birth date", "出生日期": "birth date", "生年月日": "birth date",
    "誕生日": "birth date", "出生": "birth date", "生日": "birth date", "聯絡地址": "address", "通訊地址": "address",
    "住所": "address", "地址": "address", "住址": "address",
}  # fmt: skip
#: round B: a date-shaped value within a few characters after a word of birth, in prose (``born 1990-01-02``,
#: ``DOB 02/01/1990``, ``生年月日 1990年1月2日``); a date with no such word before it stays (a log is full of dates)
_DATE = (
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{1,2}\s+[A-Z][a-z]{2,8}\.?\s+\d{4}|[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})"
)
BORN_DATE = re.compile(
    rf"(?i)(?P<word>\b(?:born|birth|birthday|dob|d\.o\.b\.?)\b|生年月日|出生日期|出生|生日|誕生日)(?P<gap>[^\n\d]{{0,16}}?)"
    rf"(?P<val>{_DATE})"
)
_LABEL_SEP = r"(?P<sep>[ \t]*(?::|\uff1a|=>|=)[ \t]*)"
LABEL_LATIN = re.compile(rf"(?<![\w.\-])(?P<q>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.\-]{{0,60}})(?P=q){_LABEL_SEP}")
LABEL_CJK = re.compile(
    rf"(?P<q>[\"']?)(?P<key>{'|'.join(sorted(LABELS_CJK, key=len, reverse=True))})(?P=q){_LABEL_SEP}"
)
#: the value after a label: quoted; after ``=``, up to the next ``name=`` or a separator; after ``:``, to the line's end
_LABEL_QUOTED = re.compile(r"\"(?:\\.|[^\"\\\n])*(?:\"|$)|'(?:\\.|[^'\\\n])*(?:'|$)", re.M)
_LABEL_EQ = re.compile(r"[^\s\"'<>{}\[\],;&](?:(?!\s+[A-Za-z_][\w.\-]*=)[^\n\"'<>{}\[\];&])*")
_LABEL_COLON = re.compile(r"[^\s\"'<>{}\[\],;&][^\n\"'<>{}\[\];&]*")
_NAME_WITH = frozenset({"first", "last", "full", "given", "family", "patient", "pt", "middle", "maiden", "kana",
                        "kanji", "legal", "display", "person"})  # fmt: skip
_NOT_A_HOME = frozenset({"ip", "mac", "email", "mail", "bind", "listen", "remote", "server", "host", "proxy", "gateway",
                         "local", "public", "private", "peer", "node", "pod", "container", "dns", "smtp", "imap", "web",
                         "url", "socket", "broadcast", "wallet", "ether", "hw", "inet", "net", "network", "memory",
                         "mem", "return", "base", "start", "end", "physical", "virtual", "link", "from",
                         "to"})  # fmt: skip
#: an address value that is a machine's, not a person's: an IP, a host and port (docker inspect's ``address``)
_MACHINE_ADDRESS = re.compile(r"[A-Za-z0-9.\-\[\]%]*[0-9.:][A-Za-z0-9.\-:\[\]%]*")


def _a_person(kind: str, value: str) -> bool:
    """Whether a labelled value is to be masked: not empty, not a mark already, not a flag, and for an address not a
    machine's (an IP, a host and port)."""
    v = value.strip()
    if not v or v.startswith("[") or _keeps(v):
        return False
    return not (kind == "address" and _MACHINE_ADDRESS.fullmatch(v))


@lru_cache(maxsize=4096)
def identifier_kind(key: str) -> str | None:
    """``name``, ``birth date`` or ``address`` when ``key`` labels a person's identifier, else None."""
    if key in LABELS_CJK:
        return LABELS_CJK[key]
    words = _words(key)
    w = set(words)
    joined = "".join(words)
    if (
        w & {"dob", "birthdate", "birthday", "born"}
        or joined in {"dateofbirth", "birthdate"}
        or ("birth" in w and not w & {"rate", "place", "limit", "weight", "order", "control"})
    ):
        return "birth date"
    if w & {"surname", "forename", "fullname", "firstname", "lastname", "givenname", "familyname", "patientname"} or (
        "name" in w and w & _NAME_WITH
    ):
        return "name"
    if w & {"address", "street", "addr", "streetaddress", "homeaddress"} and not w & _NOT_A_HOME:
        return "address"
    return None


_TAG_LETTERS = "bcdfghjkmnpqrstvwxz"  # no digit, no hex letter: a tag is never a token of any rule


@dataclass
class Scrubber:
    """The rules with what one bundle adds: the site's chart-number pattern and a tag key made for this bundle
    (never stored, never written: two bundles' tags of one patient differ). ``credentials`` is the pass for
    well-known credential shapes; the bundle passes its own so its last look stays a second, separate check."""

    mrn: re.Pattern[str] | None = None
    tag_key: bytes | None = None
    decl: Declarations = field(default_factory=declarations)
    credentials: Callable[[str], tuple[str, Counter[str]]] = hide_credentials
    found: Counter[str] = field(default_factory=Counter)
    #: H76-02: True while a decoded view is scrubbed: a secret pair's value then runs to the end of the line, since a
    #: separator there may be one the decoding made of a character inside the value
    view: bool = field(default=False, compare=False)

    @classmethod
    def for_bundle(
        cls,
        mrn: re.Pattern[str] | None = None,
        credentials: Callable[[str], tuple[str, Counter[str]]] = hide_credentials,
    ) -> Scrubber:
        return cls(mrn=mrn, tag_key=secrets.token_bytes(32), credentials=credentials)

    # -------------------------------------------------------------------------------- patient tokens
    @property
    def patterns(self) -> dict[str, re.Pattern[str]]:
        return token_patterns(pid_hex_len())

    def _mask(self, kind: str, token: str) -> str:
        self.found[kind] += 1
        if self.tag_key is None:
            return f"[{kind}]"
        digest = hmac.new(self.tag_key, f"{kind}\0{token.lower()}".encode(), hashlib.sha256).digest()
        return f"[{kind} #{''.join(_TAG_LETTERS[b % len(_TAG_LETTERS)] for b in digest[:5])}]"

    def tokens(self, text: str) -> str:
        return self.screening(self.pseudonyms(text))

    def pseudonyms(self, text: str) -> str:
        enc = _enc_pid(pid_hex_len())  # H76-03: a pseudonym right after an encoding's hex digits
        text = enc.sub(lambda m: m.group(0)[: m.start("t") - m.start(0)] + self._mask("pseudonym", m.group("t")), text)
        return self._kinds(text, "pseudonym")

    def screening(self, text: str) -> str:
        return self._kinds(text, "screening-no")

    def _kinds(self, text: str, which: str) -> str:
        for kind, rx in self.patterns.items():
            if not kind.startswith(which):
                continue
            label = "pseudonym" if kind.startswith("pseudonym") else "screening-no"

            def one(t: str, rx: re.Pattern[str] = rx, label: str = label) -> str:
                return rx.sub(lambda m: self._mask(label, m.group(0)), t)

            text = _held(UUID, text, one)
        return text

    # -------------------------------------------------------------------------------- secrets
    def _xml(self, m: re.Match[str]) -> str:
        kind = identifier_kind(m["key"].split(":")[-1])
        if kind is not None and _a_person(kind, m["val"]):
            self.found[f"identifier ({kind})"] += 1
            return m.group(0)[: m.start("val") - m.start(0)] + f"[{kind}]" + m.group(0)[m.end("val") - m.start(0) :]
        return self._value(m, "xml")

    def _value(self, m: re.Match[str], rule: str) -> str:
        val = m.group("val")
        # #1354 round 4: an encoded space before a quoted value (``key:+"S"``, ``key:%20"S"``) stays before it; a value
        # that decodes to nothing (the encoded space alone) is no value: masking it left the quoted value after it on
        # the line, and the decoded view then saw the key already masked
        spaced = ENCODED_SPACE.match(val) if rule == "colon" else None
        lead = spaced.group(0) if spaced else ""
        rest = val[len(lead) :]
        core = rest.strip("\"'")
        if not secret_name(m.group("key"), self.decl) or _keeps(_decode(core)) or core.strip() == REDACTED:
            return m.group(0)
        if rule == "quoted" and _a_count(val):
            return m.group(0)
        self.found[f"secret ({rule})"] += 1
        q = rest[:1] if rest[:1] and rest[:1] in "\"'" and rule != "escaped" else ""
        if rule == "quoted" and not q:
            q = '"'  # a bare JSON value becomes a JSON string: the document stays JSON
        new = f"{lead}{q}{REDACTED}{q}"
        return m.group(0)[: m.start("val") - m.start(0)] + new + m.group(0)[m.end("val") - m.start(0) :]

    def _lines(self, text: str) -> str:
        """Whole-line assignments, with a quoted value that runs over lines and a YAML block value."""
        lines = text.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            m = LINE.match(line)
            i += 1
            if not m or not secret_name(m["key"], self.decl):
                out.append(line)
                continue
            val = m["val"].strip()
            if YAML_BLOCK.match(val):  # key: |  -> every more-indented line after it is the value
                mark = COMMENT.match(line)
                body = line[mark.end() :] if mark else line
                indent = len(body) - len(body.lstrip())
                while i < len(lines):
                    nxt = COMMENT.match(lines[i]) if mark else None
                    if mark and not nxt:  # a commented-out block ends where the comment does
                        break
                    rest = lines[i][nxt.end() :] if nxt else lines[i]
                    if rest.strip() and len(rest) - len(rest.lstrip()) <= indent:
                        break
                    i += 1
                out.append(f"{m['lead']}{m['key']}{m['sep']}{REDACTED}")
                self.found["secret (block)"] += 1
                continue
            if val[:1] and val[:1] in "\"'" and not _closed(val):
                while i < len(lines) and not _closes(lines[i], val[0]):
                    i += 1
                i = min(i + 1, len(lines))
                out.append(f"{m['lead']}{m['key']}{m['sep']}{val[0]}{REDACTED}{val[0]}")
                self.found["secret (multi-line)"] += 1
                continue
            if not val or val.startswith("#"):  # key:  -> the value may be on the lines below (review M1)
                taken, i = self._below(lines, i, line)
                if not taken and not val and i < len(lines):  # H76-05: ``password:`` then the value, not indented
                    mark = COMMENT.match(lines[i]) if COMMENT.match(line) else None
                    rest = lines[i][mark.end() :] if mark else lines[i]
                    if SINGLE.fullmatch(rest) and not LINE.match(lines[i]):
                        taken, i = [lines[i][: len(lines[i]) - len(rest)] + REDACTED], i + 1
                        self.found["secret (value below)"] += 1
                out += [line, *taken]
                continue
            if _keeps(val.strip("\"'")) or val == REDACTED or (val.endswith(":") and " " not in val):
                out.append(line)
                continue
            out.append(f"{m['lead']}{m['key']}{m['sep']}{REDACTED}")
            self.found["secret (line)"] += 1
        return "\n".join(out)

    def _below(self, lines: list[str], i: int, key_line: str) -> tuple[list[str], int]:
        """The lines under ``key:`` that are its value (more indented, not a ``name:`` of a nested mapping): each
        becomes ``[redacted]`` at its indent (a list item keeps its ``- ``). A nested mapping is left to the rules."""
        mark = COMMENT.match(key_line)
        body = key_line[mark.end() :] if mark else key_line
        indent = len(body) - len(body.lstrip())
        taken: list[str] = []
        while i < len(lines):
            nxt = COMMENT.match(lines[i]) if mark else None
            if mark and not nxt:
                break
            rest = lines[i][nxt.end() :] if nxt else lines[i]
            if not rest.strip():
                break
            if len(rest) - len(rest.lstrip()) <= indent or MAPPING_KEY.match(rest):
                break
            head = lines[i][: len(lines[i]) - len(rest.lstrip())]
            item = re.match(r"-\s+", rest.lstrip())
            taken.append(f"{head}{item.group(0) if item else ''}{REDACTED}")
            self.found["secret (value below)"] += 1
            i += 1
        return taken, i

    def _flags(self, text: str) -> str:
        """``--name VALUE``: after a secret's name the value is the next word, even one that starts with ``-``
        (H76-05); after any other name the search goes on, so ``--verbose --token X`` still finds the token."""
        out: list[str] = []
        at = 0
        for m in FLAG.finditer(text):
            if m.start() < at or not secret_name(m["key"], self.decl):
                continue
            v = FLAG_VALUE.match(text, m.end())
            if v is None or _keeps(v.group(0).strip("\"'")) or v.group(0) == REDACTED:
                continue
            out += [text[at : m.end()], REDACTED]
            at = v.end()
            self.found["secret (flag)"] += 1
        return "".join([*out, text[at:]])

    def identifiers(self, text: str) -> str:
        """H-76 round B: e-mail addresses, and the values of labelled identifiers (a name, a date of birth, an
        address) in key and value, JSON and form forms, with English, Japanese and Chinese labels."""
        if "@" in text:
            text, n = EMAIL.subn("[email]", text)
            self.found["email"] += n
        return self._labelled(self._labelled(text, LABEL_LATIN), LABEL_CJK)

    def born(self, text: str) -> str:
        """H-76 round B: a date after a word of birth in prose. It runs after the screening numbers: a date they
        already mask (day-month-year) keeps that mark, the page's on-purpose over-mask."""
        text, n = BORN_DATE.subn(lambda m: m.group(0)[: m.start("val") - m.start(0)] + "[birth date]", text)
        self.found["identifier (birth date)"] += n
        return text

    def _labelled(self, text: str, rx: re.Pattern[str]) -> str:
        out: list[str] = []
        at = 0
        for m in rx.finditer(text):
            if m.start() < at:
                continue
            kind = identifier_kind(m["key"])
            if kind is None:
                continue
            q = text[m.end() : m.end() + 1]
            val_rx = _LABEL_QUOTED if q in "\"'" and q else _LABEL_EQ if "=" in m["sep"] else _LABEL_COLON
            v = val_rx.match(text, m.end())
            if v is None:
                continue
            val = v.group(0)
            inner = val[1:-1] if val[:1] in "\"'" else val
            if not _a_person(kind, inner):
                continue
            qq = val[0] if val[:1] in "\"'" else ""
            out += [text[at : m.end()], f"{qq}[{kind}]{qq}"]
            at = v.end()
            self.found[f"identifier ({kind})"] += 1
        return "".join([*out, text[at:]])

    def _pairs(self, text: str) -> str:
        """``name=value`` pairs. Only a secret's value is taken as a whole; after any other name the search goes on
        right after its ``=``, so ``next=%2Flogin%3Ftoken%3D…`` still finds the token inside."""
        out: list[str] = []
        at = 0
        for m in PAIR.finditer(text):
            if m.start() < at or not secret_name(m["key"], self.decl):
                continue
            v = (VIEW_VALUE if self.view else PAIR_VALUE).match(text, m.end())
            if v is None:
                continue
            val = v.group(0)
            if _keeps(val.strip("\"'")) or val.startswith(REDACTED):
                continue
            q = val[0] if val[0] in "\"'" else ""
            out += [text[at : m.end()], f"{q}{REDACTED}{q}"]
            at = v.end()
            self.found["secret (pair)"] += 1
        return "".join([*out, text[at:]])

    def secrets(self, text: str) -> str:
        text, creds = self.credentials(text)
        self.found.update({f"credential ({k})": v for k, v in creds.items()})
        text, n = PEM.subn(PEM_GONE, text)
        self.found["pem block"] += n
        text, n = SCHEME_TOKEN.subn(rf"\1\2{REDACTED}", text)
        self.found["secret (scheme token)"] += n
        text = _orphan_pem(text, self.found)
        text, n = USERINFO.subn(rf"\1{REDACTED}\3", text)
        self.found["secret (url userinfo)"] += n
        text, n = USERINFO_ENCODED.subn(rf"\1{REDACTED}\3", text)
        self.found["secret (url userinfo)"] += n
        text, n = CLI_USER.subn(rf"\g<key>\g<sep>\g<user>:{REDACTED}", text)
        self.found["secret (cli user)"] += n
        text = XML.sub(self._xml, text)
        text = ESCAPED.sub(lambda m: self._value(m, "escaped"), text)
        text = QUOTED.sub(lambda m: self._value(m, "quoted"), text)
        text = self._lines(text)
        text = HEADER.sub(lambda m: self._value(m, "header"), text)
        text = self._pairs(text)
        text = LIST_FLAG.sub(lambda m: self._value(m, "list flag"), text)
        text = self._flags(text)
        text = COLON.sub(lambda m: self._value(m, "colon"), text)
        return text

    # -------------------------------------------------------------------------------- the log scrubber
    def phi(self, text: str) -> str:
        """The log scrubber's patterns and the chart number. A digest (40 or more lowercase hex digits: a sha1, a
        sha256, the manifest's own checksums) is held out of them, so a run of digits inside it is not taken for a
        phone number; a digest is no patient token (the pseudonym rule has already run)."""
        from tb_common.logging import _PHI_PATTERNS  # the same patterns the services log through

        return _held(DIGEST, text, lambda t: self._phi(t, _PHI_PATTERNS))

    def _phi(self, text: str, patterns: list[tuple[re.Pattern[str], str]]) -> str:
        for pat, repl in patterns:
            text, k = pat.subn(repl, text)
            self.found[f"log scrubber {repl}"] += k
        if self.mrn is not None:
            text, k = self.mrn.subn("[MRN]", text)
            self.found["chart number"] += k
        return text

    def edge(self, text: str) -> str:
        """Every named form of the egress edge (M3), the digests held out as for :meth:`phi`. It runs after the
        screening numbers, as on master, so a number they mask keeps that mark."""
        return _held(DIGEST, text, self._edge)

    def _edge(self, text: str) -> str:
        for kind, s, e in reversed(egress_rules()(op="spans", text=text)):
            label = f"[{kind.upper()}]"
            if text[s:e] != label[1:-1] and text[s:e] != label:  # a label already there is not masked again
                text = text[:s] + label + text[e:]
                self.found[f"egress edge {label}"] += 1
        return text

    # -------------------------------------------------------------------------------- the one function
    def _rules(self, text: str) -> str:
        # pseudonyms before the log scrubber (its phone pattern must not cut one), screening numbers after it (a
        # Taiwan ID or an insurer number keeps its own, more exact, mark), the egress edge's forms after them, then a
        # date after a word of birth
        return self.born(self.edge(self.screening(self.phi(self.identifiers(self.pseudonyms(self.secrets(text)))))))

    def decoded(self, text: str) -> str:
        """Review H1: an encoding puts a hex digit or a letter next to a token (``%2F<pid>``, ``%22<pid>%22``,
        ``\\u002F``, ``&#x2F;``, ``=3D``), and a key or value of a secret can be encoded whole. Each line that holds an
        encoded character is decoded (percent, twice-percent, ``\\u``/``\\x``/``\\U``, HTML entities, ``=3D``) and
        scrubbed; if that changes anything, the line is kept decoded and scrubbed."""
        lines = text.split("\n")
        cand = []
        for k, line in enumerate(lines):
            if ENCODED.search(line):
                plain = _decode(line)
                if plain != line:
                    cand.append((k, line, plain))
        if not cand:
            return text
        # the views, then the raw lines, each scrubbed as one text (H-76: one call, not one a line, for speed); #1354
        # round 3 (H2): a view is read from the raw line with its secrets masked first, so a mask only the raw line
        # gets (a value an encoded separator cuts in the view) is not lost when the view is written instead
        # where the raw line's secret rule cuts a value the view would have masked whole (``password=a&shy;b``: the
        # raw value stops at ``&``), the plain view is kept: of the two views, the one that leaves less text is written
        plains = self._batch(self._view_rules, [p for _, _, p in cand])
        firsts = [(i, _decode(self.secrets(line))) for i, (_, line, plain) in enumerate(cand)]
        firsts = [(i, f) for i, f in firsts if f != cand[i][2]]
        cleans = list(plains)
        for (i, _f), first in zip(firsts, self._batch(self._view_rules, [f for _, f in firsts]), strict=True):
            if _unmasked(first) <= _unmasked(plains[i]):
                cleans[i] = first
        changed = [
            (k, line, plain, clean) for (k, line, plain), clean in zip(cand, cleans, strict=True) if clean != plain
        ]
        short = [(line, plain) for _, line, plain, _ in changed if len(line) <= 65536]
        raws = iter(self._batch(self._rules, [line for line, _ in short]))
        stricts = iter(self._batch(self._rules, [plain for _, plain in short]))
        for k, line, _plain, clean in changed:
            # H-76a (the review of #1354): the line keeps its own (encoded) form only when the raw rules, decoded, give
            # the decoded view text for text, the view read without the long value of H76-02 (where that long value
            # matters, a secret's name is hidden from the raw rules, so the two differ and the long value is written)
            if len(line) <= 65536 and _same_masks(_decode(next(raws)), next(stricts)):
                continue
            lines[k] = clean
            self.found["decoded line"] += 1
        return "\n".join(lines)

    @staticmethod
    def _batch(rules: Callable[[str], str], items: list[str]) -> list[str]:
        """``rules`` over each item: as one text when that gives back as many lines, else one item at a time."""
        if not items:
            return []
        if not any("\n" in x for x in items):
            out = rules("\n".join(items)).split("\n")
            if len(out) == len(items):
                return out
        return [rules(x) for x in items]

    def _view_rules(self, plain: str) -> str:
        self.view = True
        try:
            return self._rules(plain)
        finally:
            self.view = False

    def soft(self, text: str) -> str:
        """H76-04: lines joined by a quoted-printable soft break (a line that ends in ``=``) are read as one line;
        when the raw rules would leave a fragment of what that line holds, they are written as one, scrubbed."""
        if "=\n" not in text and "=\r\n" not in text:
            return text
        lines = text.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            j = i
            while (
                j < len(lines) - 1
                and j - i < 4096
                and lines[j].rstrip("\r").endswith("=")
                and not lines[j].rstrip("\r").endswith("==")
            ):
                j += 1
            region = lines[i : j + 1]
            i = j + 1
            if len(region) == 1:
                out += region
                continue
            plain = _decode("".join(x.rstrip("\r")[:-1] for x in region[:-1]) + region[-1])
            clean = self._view_rules(plain)
            if clean != plain:
                raw_view = _decode(self._rules("\n".join(region)).replace("=\r\n", "").replace("=\n", ""))
                if not _same_masks(raw_view, self._rules(plain)):
                    out.append(clean)
                    self.found["soft-broken lines"] += 1
                    continue
            out += region
        return "\n".join(out)

    def b64(self, text: str, depth: int = 0) -> str:
        """H76-09: a base64 run (either alphabet, padded or not) that decodes to text is scrubbed as text, and
        written back in its own alphabet when that changes anything; base64 inside base64 once more. A run that
        decodes to bytes that are not text (an image, compressed data, a hash) is left as it is."""
        if depth > 1:
            return text

        def one(m: re.Match[str]) -> str:
            run = m.group(0)
            url = "-" in run or "_" in run
            body = run.rstrip("=")
            try:
                raw = (base64.urlsafe_b64decode if url else base64.b64decode)(body + "=" * (-len(body) % 4))
                plain = raw.decode("utf-8")
            except (binascii.Error, ValueError):
                return run
            if len(run) < 24 and not EMAIL.search(plain):  # review 1634.1 R4: a short run, for an e-mail only
                return run
            if len(plain) < 6 or _CONTROL.search(plain) or not plain.strip():
                return run
            clean = self._rules(self.decoded(self.b64(plain, depth + 1)))
            if clean == plain:
                return run
            self.found["base64 run"] += 1
            enc = (base64.urlsafe_b64encode if url else base64.b64encode)(clean.encode()).decode()
            return enc if run.endswith("=") else enc.rstrip("=")

        return B64_RUN.sub(one, text)

    def text(self, text: str) -> str:
        """Every rule, until the text no longer changes (at most three passes; a fourth change is refused).

        H-76: the decoded view of a line is taken BEFORE the raw rules run. Run after them, a rule that did not see a
        token on the raw line (``%2F`` joins its hex digit to a pseudonym) could still cut into it (the log
        scrubber's phone pattern took digits from its middle), and the decoded view then saw only fragments: the
        flake of ``test_the_extended_corpus_still_holds_the_invariant``, about 1 corpus in 60."""
        for _ in range(3):
            new = self._rules(self.b64(self.decoded(self.soft(text))))
            if new == text:
                return new
            text = new
        if self._rules(self.b64(self.decoded(self.soft(text)))) != text:
            raise ScrubError("the scrub does not settle on this text: it is not written")
        return text

    def json_value(self, key: str | None, v: object) -> object:
        """One JSON value: a secret's name makes its scalar ``[redacted]``; a string is scrubbed as text; a number
        whose text the scrub would change becomes the scrubbed string; keys are scrubbed too."""
        if isinstance(v, dict):
            return {self.text(str(k)): self.json_value(str(k), x) for k, x in v.items()}
        if isinstance(v, list):
            if v and all(isinstance(x, str) and "\n" not in x for x in v):
                # a list of lines (a log's lines, a file's lines): scrubbed as one text, so a PEM block or a quoted
                # value that runs over several elements goes whole; the list may come back shorter
                if key is not None and secret_name(key, self.decl):
                    self.found["secret (json)"] += 1
                    return [REDACTED]
                return self.text("\n".join(v)).split("\n")
            return [self.json_value(key, x) for x in v]
        if isinstance(v, bool) or v is None:
            return v
        counted = isinstance(v, (int, float)) and _a_count(str(v))
        if (
            key is not None
            and secret_name(key, self.decl)
            and not _keeps(str(v))
            and str(v) != REDACTED
            and not counted
        ):
            self.found["secret (json)"] += 1
            return REDACTED
        kind = identifier_kind(key) if key is not None else None
        if kind is not None and _a_person(kind, str(v)):
            self.found[f"identifier ({kind})"] += 1
            return f"[{kind}]"
        if isinstance(v, str):
            return self.text(v)
        t = self.text(str(v))
        return v if t == str(v) else t

    def json_text(self, text: str, *, lines: bool = False) -> str:
        """A JSON document (``lines``: one per line) kept JSON: scrubbed value by value, written back in the bundle's
        form, then scrubbed once more as text. Text that is not JSON is scrubbed as text."""

        def dump(obj: object, indent: int | None) -> str:
            return json.dumps(obj, indent=indent, ensure_ascii=False, sort_keys=True, default=str)

        try:
            if lines:
                rows = [json.loads(x) for x in text.splitlines() if x.strip()]
                out = "".join(dump(self.json_value(None, r), None) + "\n" for r in rows)
            else:
                out = dump(self.json_value(None, json.loads(text)), 1) + "\n"
        except ValueError:
            return self.text(text)
        return self.text(out)

    def content(self, name: str, text: str) -> str:
        """A member's text by its kind: ``.json`` and ``.jsonl`` stay JSON; everything else is text."""
        if name.endswith(".json"):
            return self.json_text(text)
        if name.endswith(".jsonl"):
            return self.json_text(text, lines=True)
        return self.text(text)

    def name(self, name: str) -> str:
        """A member's name: scrubbed as text, then only letters, digits and ``._-/[]#`` (a space becomes ``_``)."""
        clean = self.text(name)
        return re.sub(r"[^A-Za-z0-9._\-/\[\]#]", "_", clean)

    def member(self, name: str, text: str) -> tuple[str, str]:
        clean = self.name(name)
        return clean, self.content(clean, text)

    def is_clean(self, name: str, text: str) -> bool:
        """Whether a member is as the scrub leaves it (the archive writer's check): scrubbing changes nothing."""
        probe = Scrubber(self.mrn, self.tag_key, self.decl, self.credentials)
        return probe.member(name, text) == (name, text)


_PRIVATE = re.compile("[\U000f0000-\U000ffffd]")


def _held(rx: re.Pattern[str], text: str, rules: Callable[[str], str]) -> str:
    """``rules`` over ``text`` with every match of ``rx`` held out (a digest, a UUID): each stands in as one
    private-use character that no rule reads, and is put back after. A text that already has such a character is
    given to the rules whole."""
    if _PRIVATE.search(text):
        return rules(text)
    held: list[str] = []

    def hold(m: re.Match[str]) -> str:
        held.append(m.group(0))
        return chr(0xF0000 + len(held) - 1)

    text = rules(rx.sub(hold, text))
    return _PRIVATE.sub(lambda m: held[ord(m.group(0)) - 0xF0000], text) if held else text


def _same_masks(raw_view: str, clean: str) -> bool:
    """Whether the raw line's scrub, decoded, is the decoded view's scrub: the same text and the same marks in the
    same places (one bundle's tags are the same for one token, so the marks are equal too). Linear in the line."""
    return raw_view == clean


#: a mask the scrub writes (``[redacted]``, ``[pseudonym #abcde]``, ``[PHONE]``)
_A_MASK = re.compile(r"\[[^\[\]\n]{1,40}\]")


def _unmasked(text: str) -> int:
    """How much of ``text`` no mask covers: of two views of one line, the one that leaves less is written."""
    return len(_A_MASK.sub("", text))


def _qp_octets(m: re.Match[str]) -> str:
    """Review 1634.1 R6: a run of quoted-printable octets read as UTF-8 (``=E6=82=A3`` is one character)."""
    raw = bytes.fromhex(m.group(0).replace("=", ""))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _decode(line: str) -> str:
    """``line`` with every encoding undone, up to sixteen layers (``%252F`` is ``/``; H76-03: five layers and more,
    an entity without ``;``, quoted-printable when the line has ``=3D`` or two ``=XX``), and the characters a reader
    does not see taken out (H76-04: zero-width space, soft hyphen, word joiner, byte order mark)."""
    for _ in range(16):
        new = _PCT_U.sub(lambda m: chr(int(m.group(1), 16)), line)
        new = unquote(new, errors="replace")
        new = html.unescape(new)
        new = _BACKSLASH.sub(lambda m: chr(int(m.group(1) or m.group(2) or m.group(3), 16) % 0x110000), new)
        if "=3D" in new or len(_QP.findall(new)) >= 2:
            new = _QP_RUN.sub(_qp_octets, new)
        new = _QP_AT.sub("@", new)  # round B: a lone quoted-printable at sign, between an e-mail's two halves only
        new = _OCTAL.sub(lambda m: chr(int(m.group(1), 8)), new)
        new = INVISIBLE.sub("", new)
        new = unicodedata.normalize("NFKC", new) if _FULL_WIDTH.search(new) else new  # full-width letters and digits
        if new == line:
            break
        line = new
    return line


@lru_cache(maxsize=4)
def _enc_pid(hex_len: int) -> re.Pattern[str]:
    return re.compile(ENC_PID + rf"(?P<t>[0-9A-Fa-f]{{{hex_len}}})(?![0-9A-Fa-f])")


def _seg_start(text: str, lo: int, k: int) -> int:
    """Where the segment that ends at ``k`` starts: after the last newline or literal ``\\n`` before it."""
    nl = text.rfind("\n", lo, k)
    esc = text.rfind("\\n", lo, k)
    return max(lo, nl + 1 if nl >= 0 else lo, esc + 2 if esc >= 0 else lo)


def _orphan_pem(text: str, found: Counter[str]) -> str:
    """An END line of a PEM block whose BEGIN is not in the text (a cut, a rotated log, a day's boundary) and the
    base64 lines before it: each line's last word, separated by newlines or by ``\\n`` inside a string, so a log's
    prefix on each line does not stop the walk back. Whole blocks are gone before this runs."""
    if "-----END " not in text:
        return text
    out: list[str] = []
    at = 0
    for m in PEM_END.finditer(text):
        if m.start() < at:
            continue
        start = m.start()
        line_start = _seg_start(text, at, start)
        while True:
            k = line_start
            if k - 2 >= at and text[k - 2 : k] == "\\n":
                k -= 2
            elif k - 1 >= at and text[k - 1] == "\n":
                k -= 1
            else:
                break
            seg = _seg_start(text, at, k)
            word = re.search(r"([A-Za-z0-9+/=]+)[ \t\r]*$", text[seg:k])
            if not word or not _B64.fullmatch(word.group(1)):
                break
            start = seg + word.start(1)
            line_start = seg
        out += [text[at:start], PEM_GONE]
        at = m.end()
        found["pem block (no begin)"] += 1
    return "".join([*out, text[at:]])


def _a_count(val: str) -> bool:
    """A whole number of at most three digits: a count (``"secrets_hidden": 3``), kept next to a secret's name."""
    return bool(re.fullmatch(r"\d{1,3}", val.strip()))


def _closed(val: str) -> bool:
    q = val[0]
    body = val[1:]
    return bool(re.search(rf"(?<!\\){re.escape(q)}", body))


def _closes(line: str, q: str) -> bool:
    return bool(re.search(rf"(?<!\\){re.escape(q)}", line))


@lru_cache(maxsize=4)
def token_patterns(hex_len: int) -> dict[str, re.Pattern[str]]:
    """The patient tokens' shapes (the page says why each boundary is where it is):

    * ``pseudonym``: exactly ``hex_len`` hex digits, any case, with no hex digit either side (``pid=…``, ``"…"``,
      ``/patients/…``, ``0x…`` and ``pid_…`` all match; a 64-digit sha256 and a 40-digit commit do not);
    * ``pseudonym short``: the first 8 hex digits and ``…`` (``pidmap.PidCollision``), always; ``pid[:8]`` bare
      (the console's short form) when it holds a hex letter (eight decimal digits are a date or a count far more
      often than a pseudonym);
    * ``screening-no``: a study's number as ``sitestore._number`` makes it, ``<prefix><seq:04d>``, where the prefix
      is the ruleset id and ``-`` or the site's prefix, which the console takes as any 16 characters
      (``study_setup.py``: ``.strip()[:16]``). Masked: a prefix of letters (any script), digits, ``_`` and ``-``
      ending in ``-`` or ``_``; capital letters and digits then ``.``, ``#``, ``/``, ``:`` or a space; a capital and
      letters straight before the digits (``Scr0042``). Inside a name joined by ``-`` or ``_``
      (``report-RA01-0042-x.txt``) too; not before ``-`` and a digit (``iso-8859-1``).

    A UUID is held out of all of these (its groups have those shapes and are no token). An encoded neighbour
    (``%2F``, ``\\u002F``) is handled by :meth:`Scrubber.decoded`."""
    return {
        "pseudonym": re.compile(rf"(?<![0-9A-Fa-f])[0-9A-Fa-f]{{{hex_len}}}(?![0-9A-Fa-f])"),
        "pseudonym short": re.compile(
            r"(?<![0-9A-Fa-f])[0-9a-f]{8}…|(?<![0-9A-Fa-f])(?=[0-9]{0,7}[a-f])[0-9a-f]{8}(?![0-9A-Fa-f])"
        ),
        "screening-no": re.compile(r"(?<![^\W_])[^\W_][\w\-]{0,15}[\-_]\d{4,}(?![^\W_]|[\-_]\d)"),
        "screening-no separated": re.compile(r"(?<![^\W_])[A-Z][A-Za-z0-9]{0,15}[.#/:]\d{4,}(?![^\W_]|[\-_.:/]\d)"),
        "screening-no spaced": re.compile(
            r"(?<![^\W_])[A-Z][A-Z0-9]{1,15}(?: [A-Z0-9]{1,15}){0,3} \d{4,}(?![^\W_]|[\-_.:/ ]\d)"
        ),
        "screening-no spaced short": re.compile(r"(?<![^\W_])[A-Z][A-Z0-9]{1,15} \d{4,}(?![^\W_]|[\-_.:/]\d)"),
        "screening-no letters": re.compile(r"(?<![^\W_])[A-Z][A-Za-z]{0,15}\d{4,}(?![^\W_]|[\-_]\d)"),
        "screening-no other script": re.compile(r"(?<![^\W_])[^\W\dA-Za-z_]{1,16}\d{4,}(?![^\W_]|[\-_]\d)"),
    }


def scrub_text(text: str, scrubber: Scrubber | None = None) -> str:
    """The scrub (H-71, D-1354): patient tokens masked, secrets in every form replaced, the log scrubber's patterns.
    Without a scrubber, the rules alone (no tag, no site chart number)."""
    return (scrubber or Scrubber()).text(text)


# ------------------------------------------------------------------------------------------------ the egress rules
class _Line:
    """The egress record's line, held until the caller writes it."""

    def __init__(self) -> None:
        self.line: dict[str, Any] = {}

    def append(self, event: str, **fields: Any) -> None:
        self.line = {"event": event, **fields}


def answer(op: str, **ask: Any) -> Any:
    """One question of the egress edge (``tb_common.egress_edge``), here: ``spans`` of a text, or ``leave`` of a
    bundle's members (the members as they may leave, why they may not, and the record's line)."""
    from tb_common import egress_edge

    if op == "spans":
        return [list(s) for s in egress_edge.spans(ask["text"], own_ids=True)]
    if op != "leave":
        raise ValueError(op)
    files = tuple((n, t.encode("utf-8")) for n, t in ask["files"])
    held, why = _Line(), ""
    try:
        files = egress_edge.leave(
            ask["route"], ask["destination"], egress_edge.Message("", "", files), audit=held, actor=ask["actor"]
        ).files
    except egress_edge.Refused as exc:
        why = exc.reason
    return {"files": [[n, d.decode("utf-8")] for n, d in files], "refused": why, "line": held.line}


class _Image:
    """The same questions, asked of one container of the box's own image (H-88, ``tools.trialbox.launch``): the
    host's python3 lacks a library the rules need. No network, no mount, nothing on a command line; an answer that
    does not come is a refusal by name."""

    def __init__(self, missing: str) -> None:
        from tools.trialbox import launch

        try:
            box = launch.box_file()
        except launch.BoxFileError as exc:
            raise ScrubError(str(exc)) from None
        self.said = (
            f"the egress rules need {missing}, which this host's python3 does not have, and the box image "
            f"({box.get('TB_IMAGE') or launch.DEFAULT_IMAGE}) could not run them"
        )
        docker = shlex.split(box.get("TB_DOCKER") or "docker")
        need = launch.Need(launch.IMAGE, (missing,))
        argv = launch.container_argv([], need, box, Path.cwd(), os.getuid(), os.getgid(), docker)
        try:
            self.p = subprocess.Popen(
                [*argv[:-1], "tools.bundle_scrub"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                encoding="utf-8",
            )  # fmt: skip
        except OSError:
            raise ScrubError(self.said) from None

    def __call__(self, op: str, **ask: Any) -> Any:
        assert self.p.stdin is not None and self.p.stdout is not None
        try:
            print(json.dumps({"op": op, **ask}), file=self.p.stdin, flush=True)
            got = json.loads(self.p.stdout.readline())
        except (OSError, ValueError):
            raise ScrubError(self.said) from None
        return got["answer"]


@lru_cache(maxsize=1)
def egress_rules() -> Callable[..., Any]:
    try:
        importlib.import_module("tb_common.egress_edge")
    except ImportError as exc:
        return _Image(str(exc.name))
    return answer


def serve() -> None:
    """In the box image: one question a line on standard input, one answer a line on standard output."""
    for line in sys.stdin:
        print(json.dumps({"answer": answer(**json.loads(line))}), flush=True)


def scrub_lines(lines: Iterable[str], scrubber: Scrubber | None = None) -> list[str]:
    s = scrubber or Scrubber()
    return [s.text(x) for x in lines]


# ------------------------------------------------------------------------------------------------ text or not
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]")  # \t \n \r and ESC (a log's colours) are text


def as_text(data: bytes | str, *, cut: bool = False) -> str | None:
    """The member's text, or None when it is not text the scrub can read (not UTF-8, a NUL or other control byte,
    as UTF-16 or a binary file would be): such a member is left out and listed, never copied unscrubbed. Only when
    the caller cut the bytes at its read limit (``cut``) is a last character cut there dropped (review L3)."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            if not cut or exc.reason != "unexpected end of data" or exc.start < len(data) - 3:
                return None
            text = data[: exc.start].decode("utf-8")
    else:
        text = data
    if _CONTROL.search(text) or "�" in text:
        return None
    return text


# ------------------------------------------------------------------------------------------------ the update history
#: the fields of an update history line that are the updater's own words (``tools.trialbox.update._history``)
HISTORY_KEEP = frozenset({"at", "bundle", "box", "step", "ok"})
_ERROR_TYPE = re.compile(r"^\s*([A-Z][A-Za-z0-9_]*(?:Error|Exception|Refused|Failed|Timeout|Expired|Exit))\b")


def error_shape(text: object) -> dict[str, object]:
    """An error's type and length, never its text (the integrator's order of 2026-11-20 09:41)."""
    s = "" if text is None else str(text)
    m = _ERROR_TYPE.match(s)
    return {"type": m.group(1) if m else ("empty" if not s else "text"), "length": len(s)}


def history_text(text: str) -> str:
    """The update history as the bundle holds it: each line's own fields, and every other field (the ``detail``
    the step wrote, often an error's text) as its type and length. A line that is not a JSON object is its length."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            d = None
        if not isinstance(d, dict):
            out.append(json.dumps({"unreadable_line": error_shape(line)}, sort_keys=True))
            continue
        row = {k: (v if k in HISTORY_KEEP and isinstance(v, (str, int, float, bool)) else error_shape(v))
               for k, v in d.items()}  # fmt: skip
        out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return "\n".join(out) + ("\n" if out else "")


def free_text_out(obj: object, keys: Iterable[str] = ("detail", "error")) -> object:
    """``obj`` with every ``detail`` and ``error`` string (at any depth) as its type and length (the ops snapshot's
    update rows carry each step's detail)."""
    wanted = frozenset(keys)
    if isinstance(obj, dict):
        return {k: (error_shape(v) if k in wanted and isinstance(v, str) else free_text_out(v, wanted))
                for k, v in obj.items()}  # fmt: skip
    if isinstance(obj, list):
        return [free_text_out(v, wanted) for v in obj]
    return obj


if __name__ == "__main__":
    serve()
