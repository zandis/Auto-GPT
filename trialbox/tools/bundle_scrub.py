"""The support bundle's scrub (H-71, D-1354): the one function every byte of text in a support bundle passes through.

    from tools.bundle_scrub import scrub_text, Scrubber
    clean = scrub_text(text)                      # the rules, no per-bundle tag
    s = Scrubber.for_bundle(mrn=pattern)          # a bundle's scrubber: a fresh tag key, the site's chart number
    name, text = s.member(name, text)             # a member's name and its text

It is pure: the same text and the same scrubber always give the same result, and it reads nothing but the
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
4. The log scrubber's patterns (``tb_common.logging._PHI_PATTERNS``) and the site's chart number, when given.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import html
import itertools
import re
import secrets
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
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


def secret_words(name: str) -> bool:
    words = _words(name)
    singles = {w[:-1] if w.endswith("s") and w[:-1] in SECRET_WORDS else w for w in words}
    if singles & SECRET_WORDS or any(w.endswith(SECRET_ENDINGS) for w in words):
        return True
    return any(a + b in SECRET_PAIRS for a, b in itertools.pairwise(words))


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
    r"([^\s\"'<>/@]{0,256}:[^\s\"'<>]{0,256}|[^\s\"'<>/@]{1,256})(@)"
)
USERINFO_ENCODED = re.compile(r"(?i)(%3A%2F%2F)((?:(?!%2F|%40)[^/@\s\"'<>]){1,256})(%40)")
#: a command line's ``--password VALUE`` / ``-token VALUE`` (the ``=`` form is a pair)
FLAG = re.compile(r"(?<![\w\-])(?P<dash>--?)(?P<key>[A-Za-z][A-Za-z0-9_\-]{0,40})(?P<sep>[ \t]+)(?P<val>[^\s\-]\S*)")
#: ``curl -u user:password``, ``--user``, ``--proxy-user``
CLI_USER = re.compile(r"(?<![\w\-])(?P<key>-u|--user|--proxy-user|-U)(?P<sep>[ \t]+|=)(?P<user>[^\s:]*):(?P<val>\S+)")
#: ``<password>VALUE</password>`` (any namespace, any attributes)
XML = re.compile(r"<(?P<key>[A-Za-z_][\w.\-:]{0,80})(?P<attrs>\s[^<>]{0,512})?>(?P<val>[^<]{1,4096})</(?P=key)\s*>")
#: what an encoding makes of a character: ``%2F``, ``%252F``, ``\u002F``, ``\x2F``, ``&#x2F;``, ``&quot;``, ``=3D``
ENCODED = re.compile(r"%[0-9A-Fa-f]{2}|\\[uxU][0-9A-Fa-f]{2}|&#?[A-Za-z0-9]{1,8};|=3D")
_BACKSLASH = re.compile(r"\\(?:u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|U([0-9A-Fa-f]{8}))")
_QP = re.compile(r"=([0-9A-F]{2})")
#: a PEM block's END line whose BEGIN is not in the text (a cut, a rotated log): the base64 lines before it go too
PEM_END = re.compile(r"-----END [A-Z0-9 ]{1,64}-----")
_B64 = re.compile(r"[A-Za-z0-9+/=]{16,}")
_KEY = r"[A-Za-z_][A-Za-z0-9_.\-\[\]]{0,80}"
#: a whole ``.env``/YAML/ini line: ``  - export NAME = value``, also commented out (``# NAME=value``: an old password)
LINE = re.compile(
    rf"^(?P<lead>\s*(?:(?:#+|//|;|>)\s*)?-?\s*(?:export\s+)?)(?P<key>{_KEY})(?P<sep>\s*[:=]\s*)(?P<val>.*)$"
)
#: ``name=value`` anywhere: a query string (also percent-encoded inside another URL), a form body, a log's pairs
PAIR = re.compile(rf"(?:(?<=%3[Ff])|(?<=%26)|(?<![A-Za-z0-9_.%]))(?P<key>{_KEY})(?P<sep>[ \t]*(?:=|%3[Dd])[ \t]*)")
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
COLON = re.compile(rf"(?<![A-Za-z0-9_./@\-])(?P<key>{_KEY})(?P<sep>[ \t]*:[ \t]*)(?!//)(?P<val>[^\r\n\"']+)")
HEADER = re.compile(
    r"(?im)(?<![A-Za-z0-9_\-])(?P<key>authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token)"
    r"(?P<sep>[ \t]*:[ \t]*)(?P<val>[^\r\n\"']+)"
)
UUID = re.compile(r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])")
DIGEST = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{40,}(?![0-9A-Za-z])")
COMMENT = re.compile(r"^\s*(?:#+|//|;|>)")
MAPPING_KEY = re.compile(r"^\s*-?\s*[A-Za-z_\"'][\w.\-\"' ]{0,80}:(?:\s|$)")
YAML_BLOCK = re.compile(r"^[|>][+\-]?\d*\s*(?:#.*)?$")

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
        for kind, rx in self.patterns.items():
            label = "pseudonym" if kind.startswith("pseudonym") else "screening-no"

            def one(t: str, rx: re.Pattern[str] = rx, label: str = label) -> str:
                return rx.sub(lambda m: self._mask(label, m.group(0)), t)

            text = _held(UUID, text, one)
        return text

    # -------------------------------------------------------------------------------- secrets
    def _value(self, m: re.Match[str], rule: str) -> str:
        val = m.group("val")
        if not secret_name(m.group("key"), self.decl) or _keeps(val.strip("\"'")) or val.strip() == REDACTED:
            return m.group(0)
        if rule == "quoted" and _a_count(val):
            return m.group(0)
        self.found[f"secret ({rule})"] += 1
        q = val[:1] if val[:1] and val[:1] in "\"'" and rule != "escaped" else ""
        if rule == "quoted" and not q:
            q = '"'  # a bare JSON value becomes a JSON string: the document stays JSON
        return m.group(0)[: m.start("val") - m.start(0)] + f"{q}{REDACTED}{q}" + m.group(0)[m.end("val") - m.start(0) :]

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

    def _pairs(self, text: str) -> str:
        """``name=value`` pairs. Only a secret's value is taken as a whole; after any other name the search goes on
        right after its ``=``, so ``next=%2Flogin%3Ftoken%3D…`` still finds the token inside."""
        out: list[str] = []
        at = 0
        for m in PAIR.finditer(text):
            if m.start() < at or not secret_name(m["key"], self.decl):
                continue
            v = PAIR_VALUE.match(text, m.end())
            if v is None:
                continue
            val = v.group(0)
            if _keeps(val.strip("\"'")) or val == REDACTED:
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
        text = XML.sub(lambda m: self._value(m, "xml"), text)
        text = ESCAPED.sub(lambda m: self._value(m, "escaped"), text)
        text = QUOTED.sub(lambda m: self._value(m, "quoted"), text)
        text = self._lines(text)
        text = HEADER.sub(lambda m: self._value(m, "header"), text)
        text = self._pairs(text)
        text = FLAG.sub(lambda m: self._value(m, "flag"), text)
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

    # -------------------------------------------------------------------------------- the one function
    def _rules(self, text: str) -> str:
        return self.phi(self.tokens(self.secrets(text)))

    def decoded(self, text: str) -> str:
        """Review H1: an encoding puts a hex digit or a letter next to a token (``%2F<pid>``, ``%22<pid>%22``,
        ``\\u002F``, ``&#x2F;``, ``=3D``), and a key or value of a secret can be encoded whole. Each line that holds an
        encoded character is decoded (percent, twice-percent, ``\\u``/``\\x``/``\\U``, HTML entities, ``=3D``) and
        scrubbed; if that changes anything, the line is kept decoded and scrubbed."""
        lines = text.split("\n")
        for k, line in enumerate(lines):
            if not ENCODED.search(line):
                continue
            plain = _decode(line)
            if plain == line:
                continue
            clean = self._rules(plain)
            if clean != plain:
                lines[k] = clean
                self.found["decoded line"] += 1
        return "\n".join(lines)

    def text(self, text: str) -> str:
        """Every rule, until the text no longer changes (at most three passes; a fourth change is refused).

        H-76: the decoded view of a line is taken BEFORE the raw rules run. Run after them, a rule that did not see a
        token on the raw line (``%2F`` joins its hex digit to a pseudonym) could still cut into it (the log
        scrubber's phone pattern took digits from its middle), and the decoded view then saw only fragments: the
        flake of ``test_the_extended_corpus_still_holds_the_invariant``, about 1 corpus in 60."""
        for _ in range(3):
            new = self._rules(self.decoded(text))
            if new == text:
                return new
            text = new
        if self._rules(self.decoded(text)) != text:
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
        if isinstance(v, str):
            return self.text(v)
        t = self.text(str(v))
        return v if t == str(v) else t

    def json_text(self, text: str, *, lines: bool = False) -> str:
        """A JSON document (``lines``: one per line) kept JSON: scrubbed value by value, written back in the bundle's
        form, then scrubbed once more as text. Text that is not JSON is scrubbed as text."""
        import json

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


def _decode(line: str) -> str:
    """``line`` with every encoding undone, up to four layers (``%252F`` is ``/``)."""
    for _ in range(4):
        new = unquote(line, errors="replace")
        new = html.unescape(new)
        new = _BACKSLASH.sub(lambda m: chr(int(m.group(1) or m.group(2) or m.group(3), 16) % 0x110000), new)
        if "=3D" in new:
            new = _QP.sub(lambda m: chr(int(m.group(1), 16)), new)
        if new == line:
            break
        line = new
    return line


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
        "screening-no separated": re.compile(r"(?<![^\W_])[A-Z][A-Z0-9]{1,15}[ .#/:]\d{4,}(?![^\W_]|[\-_.:/]\d)"),
        "screening-no letters": re.compile(r"(?<![^\W_])[A-Z][A-Za-z]{0,15}\d{4,}(?![^\W_]|[\-_]\d)"),
    }


def scrub_text(text: str, scrubber: Scrubber | None = None) -> str:
    """The scrub (H-71, D-1354): patient tokens masked, secrets in every form replaced, the log scrubber's patterns.
    Without a scrubber, the rules alone (no tag, no site chart number)."""
    return (scrubber or Scrubber()).text(text)


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
    import json

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
