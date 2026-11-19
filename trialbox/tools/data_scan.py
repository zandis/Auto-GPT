"""The data-handling scan (D-203, WS-13.10, TB-SITE-03 §2, TST-SEC-10): no real identifier in the repository or a log.

    python -m tools.data_scan                      # every file git tracks under this folder; exit 0 clean, 2 on a hit
    python -m tools.data_scan PATH ...             # files, folders, archives (.tar, .tgz, .zip, .gz, .xlsx, .docx)
    python -m tools.data_scan --log make-test.log  # a log (the same scan; the name says what it is)
    python tools/data_scan.py --staged             # the files staged for the next commit (their staged content)

What it looks for is data (``tools/data_scan_patterns.yaml``): a chart number after its label or in an HL7 PID
segment, a Taiwan ID or resident certificate with a valid check digit, a マイナンバー with a valid check digit, a
Japanese insurer number, Taiwanese and Japanese phone numbers, and a Chinese, Japanese or katakana name beside a
date (western, compact, ROC or wareki). Each line is normalised first (NFKC: full-width digits, half-width katakana;
format characters and variation selectors out; dash variants between digits made a hyphen), and digits may be split
by spaces, hyphens, dots, slashes or tabs. Name and date may sit on neighbouring lines. Tables (``.csv``, ``.tsv``,
``.xlsx``, ``.parquet``) are also read row by row with their header as labels, so a column named ``mrn`` or ``氏名``
labels its values. Archives and office files are read member by member, by content (magic bytes) as well as by
name, with bounded decompression; a text file in another encoding is decoded as UTF-8, UTF-16 (BOM or NUL pattern),
or every one of cp932, cp950, EUC-JP and GB18030 that decodes it. A file that cannot be read as text, an archive or
a table, and is not of a known binary kind (images, fonts, PDF, compiled code), is reported as ``unscanned``: a hit.

A file whose ``tb-data`` git attribute is set (``.gitattributes``: data file types outside the fixture, eval,
catalogue and refdata folders) is itself a hit. A hit prints the file, the line, the pattern and, for a value of ten
characters or more, its first and last two characters, else its first only; never the whole value. Known synthetic
values and the planted test positives are listed, each with its reason, in ``tools/data_scan_allow.txt``.

Exit codes: 0 clean, 2 at least one hit, 1 a broken pattern or allowlist file.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import os
import re
import subprocess
import sys
import tarfile
import unicodedata
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "libs") not in sys.path:  # run as a script by the pre-commit hook, from the repository root
    sys.path.insert(0, str(ROOT / "libs"))

from tb_common import phi_guard  # noqa: E402  (the surname lists and the phone pattern: imported, not copied)

PATTERNS = ROOT / "tools" / "data_scan_patterns.yaml"
ALLOW = ROOT / "tools" / "data_scan_allow.txt"
MAX_BYTES = 32 * 2**20  # a file, archive member or decompressed stream larger than this is "unscanned", a hit
NEAR_LINES = 3  # a name and a date may sit on up to three consecutive lines (pretty-printed JSON, a form)
NEAR_WINDOW = 64  # and then may be this many characters apart ("name": ..., "gender": ..., "birthDate": ...)
# other dashes between two digits become a hyphen
DASH_IN_NUMBER = re.compile(r"(?<=\d)[\u2010-\u2015\u2212\u30fc\uff0d\uff70\ufe58\ufe63](?=\d)")
INVISIBLE = re.compile(r"[\u034f\ufe00-\ufe0f\U000e0100-\U000e01ef]")  # CGJ and variation selectors
# known binary kinds, by name and by magic bytes: nothing a person's record hides in as text
BINARY_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".ttf", ".otf", ".woff", ".woff2",
              ".class", ".pyc", ".so", ".jar")  # fmt: skip
BINARY_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"%PDF", b"\x00\x01\x00\x00", b"OTTO", b"wOFF", b"wOF2",
                b"\xca\xfe\xba\xbe")  # fmt: skip

CJK = "\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3005\u3006"  # CJK ideographs, the iteration and closing marks
KANA = "\u3040-\u30ff\u31f0-\u31ff"  # hiragana, katakana
KATAKANA = "\u30a1-\u30fa\u30fc"  # katakana letters and the long-vowel mark
EAST_ASIAN = re.compile(f"[{CJK}{KANA}]")
DATE = (
    r"(?:(?<!\d)(?:1[89]|20)\d{2}\s?[-/年.]\s?\d{1,2}(?!\d)"  # 1960-05-04, 1960/5/4, 1960年5月, 1960.05
    r"|(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)"  # 19600504
    r"|(?<!\d)\d{1,2}/\d{1,2}/(?:19|20)\d{2}(?!\d)"  # 04/05/1960
    r"|民國\s?\d{2,3}\s?年|(?:明治|大正|昭和|平成|令和)\s?(?:\d{1,2}|元)\s?年"  # ROC and wareki years
    r"|(?<![A-Za-z])[MTSHR]\s?\d{1,2}\.\d{1,2}\.\d{1,2}(?!\d))"  # S35.5.4
)


def _placeholders() -> dict[str, str]:
    roc = (
        "|".join(sorted(phi_guard.ROC_COMPOUND, key=len, reverse=True))
        + "|["
        + "".join(sorted(phi_guard.ROC_SURNAMES))
        + "]"
    )
    # single-character Japanese surnames (林, 森) are on the ROC list too and take its one or two given characters
    jp = "|".join(sorted((n for n in phi_guard.JP_SURNAMES if len(n) > 1), key=len, reverse=True))
    return {
        "roc_surname": f"(?:{roc})",
        "jp_surname": f"(?:{jp})",
        "honorific": phi_guard.HONORIFIC,
        "patient_word": phi_guard.PATIENT_WORD,
        "cjk": CJK,
        "kana": KANA,
        "katakana": KATAKANA,
        "date": DATE,
        "sep": r"(?:[ \t.\-/]{1,2})",  # inside a labelled number
        "sep_id": r"(?:[ \t\-]{1,2})",  # an unlabelled ID: no dot or slash (drawing coordinates)
    }


# ------------------------------------------------------------------ check digits
TW_LETTERS = dict(zip("ABCDEFGHJKLMNPQRSTUVXYWZIO", range(10, 36), strict=True))


def tw_id_ok(s: str) -> bool:
    """Taiwan ID / new resident certificate: letter value (two digits) and nine digits, weights 1 9 8 7 ... 1 1."""
    s = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    if not re.fullmatch(r"[A-Z][1289]\d{8}", s):
        return False
    n = TW_LETTERS[s[0]]
    digits = [n // 10, n % 10, *map(int, s[1:])]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
    return sum(d * w for d, w in zip(digits, weights, strict=True)) % 10 == 0


def my_number_ok(s: str) -> bool:
    """マイナンバー: check = 11 - (sum P_n * Q_n mod 11), 0 when the remainder is 0 or 1 (P_1 next to the check)."""
    d = re.sub(r"\D", "", s)
    if len(d) != 12:
        return False
    body = [int(c) for c in reversed(d[:11])]
    total = sum(p * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(body, 1))
    r = total % 11
    return int(d[11]) == (0 if r <= 1 else 11 - r)


def luhn_ok(s: str) -> bool:
    """The Japanese insurer number's check digit (検証番号) is Luhn's."""
    d = [int(c) for c in re.sub(r"\D", "", s)]
    total = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x *= 2
            x = x - 9 if x > 9 else x
        total += x
    return bool(d) and total % 10 == 0


CHECKS: dict[str, Callable[[str], bool]] = {"tw_id": tw_id_ok, "my_number": my_number_ok, "luhn": luhn_ok}


# ------------------------------------------------------------------ patterns and the allowlist
@dataclass
class Pattern:
    id: str
    rx: re.Pattern[str]
    group: int | None = None
    check: Callable[[str], bool] | None = None
    digits: tuple[int, int] | None = None
    not_words: frozenset[str] = field(default_factory=frozenset)
    alone: bool = False
    needs: re.Pattern[str] | None = None
    near: re.Pattern[str] | None = None
    window: int = 24

    def _matches(self, line: str, window: int | None = None) -> Iterator[re.Match[str]]:
        if self.near is None:
            yield from self.rx.finditer(line)
            return
        seen: set[int] = set()  # the pattern only within `window` characters of a `near` match (a name by a date)
        for nm in self.near.finditer(line):
            lo, hi = max(0, nm.start() - (window or self.window)), nm.end() + (window or self.window)
            for m in self.rx.finditer(line, lo, min(len(line), hi + 16)):  # room for a token and its lookahead
                if m.start() <= hi and m.start() not in seen:
                    seen.add(m.start())
                    yield m

    def hits(self, line: str, window: int | None = None) -> Iterator[str]:
        if self.needs is not None and not self.needs.search(line):
            return
        for m in self._matches(line, window):
            if self.alone and _touches(line, m.start(), m.end()):
                continue
            if self.group is not None:
                text = m.group(self.group)
            else:
                text = next((g for g in m.groups() if g), None) or m.group(0)
            if not text or text.strip() in self.not_words:
                continue
            if self.digits:
                n = len(re.sub(r"\D", "", text))
                if not self.digits[0] <= n <= self.digits[1]:
                    continue
            if self.check and not self.check(text):
                continue
            yield text.strip()


PHONE_LABEL = re.compile(r"(?i)(?<![A-Za-z])(?:tel|phone|mobile|cell|fax|contact)[._:#-]*$")


def _word(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")  # a CJK label before a number (電話0912...) is no token


def _touches(line: str, start: int, end: int) -> bool:
    """The match is part of a longer token: a letter, digit or underscore beside it, a decimal point or a hyphen
    before it (``0.021020637``, ``TB-08-2026-0001``), or a dot between it and a digit (``0912345678.5``)."""
    before = line[start - 1] if start else ""
    after = line[end] if end < len(line) else ""
    if (_word(before) or before in (".", "-")) and PHONE_LABEL.search(line[:start]):
        before = ""  # tel0912..., phone_0912..., TEL-0912...: a label, not a longer token
    if _word(before) or before in (".", "-") or _word(after):
        return True
    return after == "." and line[end + 1 : end + 2].isdigit()


class ConfigError(ValueError):
    pass


def _fill(src: str, ph: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ph.get(m.group(1), m.group(0)), src)


def load_patterns(path: Path = PATTERNS, *, exits: bool = False) -> list[Pattern]:
    """The scan's patterns. ``exits``: also the patterns marked ``exit`` (D-747), for the scans of what leaves the
    box (a support bundle, the comment export, the demo guard); the repository scan leaves them out, because the
    repository's tests and evaluation sets hold synthetic values of those shapes by design."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ph = _placeholders()
    out: list[Pattern] = []
    for p in doc["patterns"]:
        pid = p["id"]
        if p.get("exit") and not exits:
            continue
        try:
            if "phi_guard" in p:
                rx = getattr(phi_guard, p["phi_guard"])
                if not isinstance(rx, re.Pattern):
                    raise ConfigError(f"{pid}: tb_common.phi_guard.{p['phi_guard']} is not a compiled pattern")
            else:
                rx = re.compile(_fill(p["regex"], ph))
            needs = re.compile(_fill(p["needs"], ph)) if p.get("needs") else None
            near = re.compile(_fill(p["near"], ph)) if p.get("near") else None
        except (re.error, AttributeError, KeyError) as e:
            raise ConfigError(f"{path.name}: pattern {pid}: {e}") from e
        check = p.get("check")
        if check and check not in CHECKS:
            raise ConfigError(f"{path.name}: pattern {pid}: unknown check {check!r}")
        digits = p.get("digits")
        out.append(Pattern(pid, rx, p.get("group"), CHECKS[check] if check else None,
                           (int(digits[0]), int(digits[1])) if digits else None,
                           frozenset(unicodedata.normalize("NFKC", w) for w in p.get("not", [])),
                           bool(p.get("alone")), needs, near, int(p.get("window", 24))))  # fmt: skip
    ids = [p.id for p in out]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"{path.name}: a pattern id twice")
    return out


@dataclass
class Allow:
    values: dict[str, set[str]]  # pattern id ("*" any) -> exact normalised values
    paths: list[tuple[str, str]]  # (glob on the repository-relative path, pattern id or "*")


SPECIAL = {"*", "data_file", "unscanned"}


def load_allow(path: Path = ALLOW) -> Allow:
    """``value | <pattern> | <the value> | <reason>`` or ``path | <pattern or *> | <glob> | <reason>`` per line; a
    line without a reason, an unknown kind or a pattern id the scan does not have is refused."""
    known = {p.id for p in load_patterns()} | SPECIAL
    allow = Allow({}, [])
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) != 4 or not all(parts[:3]):
            raise ConfigError(f"{path.name}:{n}: want 'kind | pattern | value or glob | reason'")
        kind, pid, what, reason = parts
        if len(reason) < 8:
            raise ConfigError(f"{path.name}:{n}: an allowlist entry needs its reason")
        if pid not in known:
            raise ConfigError(f"{path.name}:{n}: unknown pattern {pid!r}")
        if kind == "value":
            allow.values.setdefault(pid, set()).add(_norm(what))
        elif kind == "path":
            allow.paths.append((what, pid))
        else:
            raise ConfigError(f"{path.name}:{n}: kind is 'value' or 'path', not {kind!r}")
    return allow


# ------------------------------------------------------------------ the scan
@dataclass(frozen=True, order=True)
class Hit:
    where: str
    line: int
    pattern: str
    shown: str

    def __str__(self) -> str:
        return f"{self.where}:{self.line}: {self.pattern}: {self.shown}"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Cf")  # zero-width, LRM/RLM, soft hyphen, BOM ...
    return DASH_IN_NUMBER.sub("-", INVISIBLE.sub("", s))


def mask(s: str) -> str:
    """Never the whole value: the first and last two characters of a value of ten or more, else the first only."""
    s = s.strip()
    if len(s) >= 10:
        return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"
    return s[:1] + "*" * (len(s) - 1)


def _lines(text: str) -> list[str]:
    """Lines on newlines only (``str.splitlines`` also splits on U+2028, U+0085 and FS/GS/RS, cutting a label from
    its value)."""
    return re.split(r"\r\n|\n|\r", text)


def scan_lines(lines: list[str], where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    out: set[Hit] = set()
    norm = [_norm(raw) for raw in lines]
    active = [p for p in patterns if not _path_allowed(where, p.id, allow)]
    letters = [bool(EAST_ASIAN.search(x)) for x in norm]  # a name can only be where CJK or kana is
    for n, line in enumerate(norm, 1):
        if not line.strip():
            continue
        for p in active:
            texts = list(p.hits(line))
            lo = max(0, n - NEAR_LINES)
            if p.near is not None and n > 1 and any(letters[lo:n]):  # a name and a date on neighbouring lines
                texts += list(p.hits(" ".join(norm[lo:n]), window=NEAR_WINDOW))
            for text_hit in texts:
                v = _norm(text_hit)
                if v in allow.values.get(p.id, set()) or v in allow.values.get("*", set()):
                    continue
                out.add(Hit(where, n, p.id, mask(v)))
    return sorted(out)


def scan_text(text: str, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    return scan_lines(_lines(text), where, patterns, allow)


def _path_allowed(where: str, pid: str, allow: Allow) -> bool:
    return any((ap == "*" or ap == pid) and fnmatch.fnmatch(where, glob) for glob, ap in allow.paths)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return str(v.isoformat())[:10]
    return str(v)


def table_lines(rows: Iterable[Iterable[Any]]) -> list[str]:
    """A table as lines: each row once as it is (cells by " | ") and once labelled by the header (``mrn: 12345678 |
    name: ...``), so a column's name stands beside its values as a label would."""
    out: list[str] = []
    header: list[str] | None = None
    for row in rows:
        cells = [_cell(v) for v in row]
        if header is None:
            header = cells
            out.append(" | ".join(cells))
            continue
        out.append(" | ".join(cells))
        out.append(" | ".join(f"{h}: {c}" for h, c in zip(header, cells, strict=False) if c))
    return out


def decodings(data: bytes) -> list[str]:
    """The text(s) a file may be: by BOM; UTF-16 when NULs fall on one byte parity; UTF-8; else every East Asian
    legacy encoding that decodes it (so a Big5 file is not lost to a lucky Shift-JIS decode). [] for binary."""
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            try:
                return [data.decode(enc)]
            except UnicodeDecodeError:
                break
    head = data[:8192]
    if b"\0" in head:
        even, odd = head[0::2].count(0), head[1::2].count(0)
        for share, other, enc in ((odd, even, "utf-16-le"), (even, odd, "utf-16-be")):
            if share > len(head) // 8 and other <= share // 8:
                try:
                    return [data.decode(enc)]
                except UnicodeDecodeError:
                    pass
        return []
    try:
        return [data.decode("utf-8")]
    except UnicodeDecodeError:
        pass
    out: list[str] = []
    for enc in ("cp932", "cp950", "euc_jp", "gb18030"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        if text not in out:
            out.append(text)
    return out


def _gunzip(data: bytes) -> bytes | None:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(data, MAX_BYTES + 1)
    return None if len(out) > MAX_BYTES or d.unconsumed_tail else out


def _known_binary(name: str, data: bytes) -> bool:
    return name.lower().endswith(BINARY_EXT) or data.startswith(BINARY_MAGIC)


def scan_bytes(data: bytes, where: str, patterns: list[Pattern], allow: Allow, name: str | None = None) -> list[Hit]:
    """A file's content by what it is (magic bytes first, then its name): an archive's members one by one, a gzip's
    bounded content, a workbook's or a Parquet file's rows, a text file's lines; a known binary kind is skipped and
    anything else unreadable is an ``unscanned`` hit."""
    name = (name or where).lower()
    if len(data) > MAX_BYTES:
        return [Hit(where, 0, "unscanned", f"larger than {MAX_BYTES >> 20} MB")]
    try:
        if data.startswith(b"\x1f\x8b"):
            inner = _gunzip(data)
            if inner is None:
                return [Hit(where, 0, "unscanned", f"decompresses to more than {MAX_BYTES >> 20} MB")]
            inner_name = name[:-3] if name.endswith(".gz") else name[:-4] + ".tar" if name.endswith(".tgz") else name
            return scan_bytes(inner, f"{where}!gunzip", patterns, allow, inner_name)
        if data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
            return _scan_zip(data, where, patterns, allow)
        if data.startswith(b"PAR1"):
            return _scan_parquet(data, where, patterns, allow)
        if len(data) > 262 and data[257:262] == b"ustar":
            out = []
            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                for m in tf.getmembers():
                    if not m.isfile():
                        continue
                    if m.size > MAX_BYTES:
                        out.append(Hit(f"{where}!{m.name}", 0, "unscanned", "member too large"))
                        continue
                    f = tf.extractfile(m)
                    if f is not None:
                        out += scan_bytes(f.read(), f"{where}!{m.name}", patterns, allow, m.name)
            return out
    except Exception as e:  # any unreadable archive is a hit, never a crash or a pass
        return [Hit(where, 0, "unscanned", f"unreadable ({type(e).__name__})")]
    if _known_binary(name, data):
        return []
    texts = decodings(data)
    if not texts:
        return [Hit(where, 0, "unscanned", "binary of an unknown kind")]
    found: set[Hit] = set()
    for text in texts:
        if name.endswith((".csv", ".tsv")):
            rows = csv.reader(io.StringIO(text), delimiter="\t" if name.endswith(".tsv") else ",")
            found.update(scan_lines(table_lines(rows), where, patterns, allow))
        found.update(scan_text(text, where, patterns, allow))
    return sorted(found)


def _scan_zip(data: bytes, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    out: list[Hit] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        if "xl/workbook.xml" in names:
            return _scan_xlsx(data, where, patterns, allow)
        if "word/document.xml" in names:
            return _scan_docx(data, where, patterns, allow)
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.file_size > MAX_BYTES:
                out.append(Hit(f"{where}!{info.filename}", 0, "unscanned", "member too large"))
                continue
            out += scan_bytes(zf.read(info), f"{where}!{info.filename}", patterns, allow, info.filename)
    return out


def _scan_xlsx(data: bytes, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: list[Hit] = []
    for ws in wb.worksheets:
        out += scan_lines(table_lines(ws.iter_rows(values_only=True)), f"{where}!{ws.title}", patterns, allow)
    wb.close()
    return out


def _scan_docx(data: bytes, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    import docx

    doc = docx.Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        lines += table_lines([c.text for c in row.cells] for row in table.rows)
    return scan_lines(lines, where, patterns, allow)


def _scan_parquet(data: bytes, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    import pyarrow.parquet as pq

    table = pq.read_table(io.BytesIO(data), use_threads=False)
    cols = table.column_names
    rows: list[list[Any]] = [list(cols), *([r.get(c) for c in cols] for r in table.to_pylist())]
    return scan_lines(table_lines(rows), where, patterns, allow)


def tracked(base: Path) -> list[Path]:
    r = subprocess.run(["git", "ls-files", "-z"], cwd=base, capture_output=True, check=True)
    return [base / p for p in r.stdout.decode().split("\0") if p]


def staged(base: Path) -> list[Path]:
    r = subprocess.run(["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", "--relative"],
                       cwd=base, capture_output=True, check=True)  # fmt: skip
    return [base / p for p in r.stdout.decode().split("\0") if p]


def data_files(paths: list[Path], base: Path) -> set[Path]:
    """The paths whose ``tb-data`` attribute is set: a data file type outside the folders that may hold one."""
    if not paths:
        return set()
    rel = "\0".join(str(p.resolve().relative_to(base.resolve())) for p in paths) + "\0"
    r = subprocess.run(["git", "check-attr", "-z", "--stdin", "tb-data"], cwd=base, input=rel.encode(),
                       capture_output=True, check=False)  # fmt: skip
    parts = r.stdout.decode().split("\0")
    return {base / parts[i] for i in range(0, len(parts) - 2, 3) if parts[i + 2] == "set"}


def _expand(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.is_file() and ".git" not in q.parts)
        elif p.is_file():
            out.append(p)
    return out


def _rel(p: Path, base: Path) -> str:
    """The path from ``base`` (trialbox/) whatever the caller's working directory (the hook runs from the root)."""
    try:
        return str(p.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(p)


_WORKER: tuple[list[Pattern], Allow] | None = None


def _init_worker(patterns: list[Pattern], allow: Allow) -> None:
    global _WORKER
    _WORKER = (patterns, allow)


def _scan_one(job: tuple[Path, str, bytes | None]) -> list[Hit]:
    assert _WORKER is not None
    return _scan_file(*job, *_WORKER)


def _scan_file(p: Path, where: str, data: bytes | None, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    if data is None:
        if p.is_symlink():
            return []  # git stores a link's text, not its target; the target is scanned where it lives
        try:
            data = p.read_bytes()
        except OSError:
            return [Hit(where, 0, "unscanned", "unreadable")]
    return scan_bytes(data, where, patterns, allow)


def _index_blob(base: Path, where: str) -> bytes | None:
    """The staged content of a file (what the commit will hold), not the working tree's."""
    r = subprocess.run(["git", "show", f":./{where}"], cwd=base, capture_output=True, check=False)
    return r.stdout if r.returncode == 0 else None


def run(paths: list[Path], base: Path = ROOT, patterns: list[Pattern] | None = None, allow: Allow | None = None,
        in_repo: bool = True, jobs: int = 1, from_index: bool = False) -> list[Hit]:  # fmt: skip
    patterns = patterns if patterns is not None else load_patterns()
    allow = allow if allow is not None else load_allow()
    hits: list[Hit] = []
    if in_repo:
        inside = [p for p in paths if p.resolve().is_relative_to(base.resolve())]
        for p in sorted(data_files(inside, base)):
            where = _rel(p, base)
            if not _path_allowed(where, "data_file", allow):
                hits.append(
                    Hit(where, 0, "data_file", "a data file type outside tests/fixtures, eval, catalogue, refdata")
                )
    work = [(p, _rel(p, base), _index_blob(base, _rel(p, base)) if from_index else None) for p in paths]
    if jobs > 1 and len(work) > 32:
        with ProcessPoolExecutor(jobs, initializer=_init_worker, initargs=(patterns, allow)) as ex:
            for found in ex.map(_scan_one, work, chunksize=8):
                hits += found
    else:
        for job in work:
            hits += _scan_file(*job, patterns, allow)
    return [h for h in hits if not (h.pattern == "unscanned" and _path_allowed(h.where, "unscanned", allow))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path, help="files, folders or archives (default: git ls-files here)")
    ap.add_argument("--log", type=Path, action="append", default=[], help="a log file to scan (repeatable)")
    ap.add_argument("--staged", action="store_true", help="the files staged for the next commit (pre-commit hook)")
    ap.add_argument("--exits", action="store_true", help="a file that leaves the box: the exits' patterns too")
    a = ap.parse_args(argv)
    try:
        patterns, allow = load_patterns(exits=a.exits), load_allow()
    except (ConfigError, OSError, yaml.YAMLError, KeyError, TypeError) as e:
        print(f"data_scan: {e}", file=sys.stderr)
        return 1
    base = ROOT
    if a.staged:
        paths = staged(base)
    elif a.paths or a.log:
        paths = _expand(a.paths)
    else:
        paths = tracked(base)
    jobs = max(1, min(8, os.cpu_count() or 1))
    hits = run(paths, base, patterns, allow, jobs=jobs, from_index=a.staged)
    hits += run(a.log, base, patterns, allow, in_repo=False, jobs=jobs)
    for h in hits:
        print(h)
    n = len(paths) + len(a.log)
    print(f"data_scan: {'clean' if not hits else f'{len(hits)} hit(s)'} ({n} file(s), {len(patterns)} patterns)")
    return 2 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
