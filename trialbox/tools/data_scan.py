"""The data-handling scan (D-203, WS-13.10, TB-SITE-03 §2, TST-SEC-10): no real identifier in the repository or a log.

    python -m tools.data_scan                      # every file git tracks under this folder; exit 0 clean, 2 on a hit
    python -m tools.data_scan PATH ...             # files, folders, archives (.tar, .tgz, .zip, .gz, .xlsx, .docx)
    python -m tools.data_scan --log make-test.log  # a log (the same scan; the name says what it is)
    python tools/data_scan.py --staged             # the pre-commit hook: the files staged for the next commit

What it looks for is data (``tools/data_scan_patterns.yaml``): a chart number after its label, a Taiwan ID or
resident certificate with a valid check digit, a マイナンバー with a valid check digit, a Japanese insurer number,
Taiwanese and Japanese phone numbers, and a Chinese, Japanese or katakana name beside a date. Each line is normalised
first (NFKC: full-width digits; zero-width characters out), and digits may be split by a space or a hyphen. A file
whose ``tb-data`` git attribute is set (``.gitattributes``: data file types outside the fixture, eval, catalogue
and refdata folders) is itself a hit. A hit prints the file, the line, the pattern and the first and last two
characters of what matched, never the whole of it. Known synthetic values and the planted test positives are listed,
each with its reason, in ``tools/data_scan_allow.txt``.

Exit codes: 0 clean, 2 at least one hit, 1 a broken pattern or allowlist file.
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import io
import os
import re
import subprocess
import sys
import tarfile
import unicodedata
import zipfile
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "libs") not in sys.path:  # run as a script by the pre-commit hook, from the repository root
    sys.path.insert(0, str(ROOT / "libs"))

from tb_common import phi_guard  # noqa: E402  (the surname lists and the phone pattern: imported, not copied)

PATTERNS = ROOT / "tools" / "data_scan_patterns.yaml"
ALLOW = ROOT / "tools" / "data_scan_allow.txt"
MAX_BYTES = 32 * 2**20  # a file or archive member larger than this is reported as unscanned, not skipped silently
ARCHIVES = (".tar", ".tgz", ".tar.gz", ".zip", ".xlsx", ".docx")
ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
DASH_IN_NUMBER = re.compile(r"(?<=\d)[\u2010-\u2015\u2212\u30fc\uff70](?=\d)")  # 090‐1234−5678

CJK = "\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3005\u3006"  # CJK ideographs, 々 〆
KANA = "\u3040-\u30ff\u31f0-\u31ff"  # hiragana, katakana
KATAKANA = "\u30a1-\u30fa\u30fc"  # katakana letters and the long-vowel mark


def _placeholders() -> dict[str, str]:
    roc = (
        "|".join(sorted(phi_guard.ROC_COMPOUND, key=len, reverse=True))
        + "|["
        + "".join(sorted(phi_guard.ROC_SURNAMES))
        + "]"
    )
    jp = "|".join(sorted(phi_guard.JP_SURNAMES, key=len, reverse=True))
    return {
        "roc_surname": f"(?:{roc})",
        "jp_surname": f"(?:{jp})",
        "cjk": CJK,
        "kana": KANA,
        "katakana": KATAKANA,
        "date": r"(?<!\d)(?:1[89]|20)\d{2}\s?[-/年.]\s?\d{1,2}(?!\d)",
        "sep": r"[ \-]",
    }


# ------------------------------------------------------------------ check digits
TW_LETTERS = dict(zip("ABCDEFGHJKLMNPQRSTUVXYWZIO", range(10, 36), strict=True))


def tw_id_ok(s: str) -> bool:
    """Taiwan ID / new resident certificate: letter value (two digits) and nine digits, weights 1 9 8 7 ... 1 1."""
    s = re.sub(r"[ \-]", "", s).upper()
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

    def _matches(self, line: str) -> Iterator[re.Match[str]]:
        if self.near is None:
            yield from self.rx.finditer(line)
            return
        seen: set[int] = set()  # the pattern only within `window` characters of a `near` match (a name by a date)
        for nm in self.near.finditer(line):
            lo, hi = max(0, nm.start() - self.window), nm.end() + self.window
            for m in self.rx.finditer(line, lo, min(len(line), hi + 4)):
                if m.start() <= hi and m.start() not in seen:
                    seen.add(m.start())
                    yield m

    def hits(self, line: str) -> Iterator[str]:
        if self.needs is not None and not self.needs.search(line):
            return
        for m in self._matches(line):
            if self.alone and _touches(line, m.start(), m.end()):
                continue
            if self.group is not None:
                text = m.group(self.group)
            else:
                text = next((g for g in m.groups() if g), None) or m.group(0)
            if not text or text in self.not_words:
                continue
            if self.digits:
                n = len(re.sub(r"\D", "", text))
                if not self.digits[0] <= n <= self.digits[1]:
                    continue
            if self.check and not self.check(text):
                continue
            yield text


def _word(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")  # a CJK label before a number (電話0912...) is no token


def _touches(line: str, start: int, end: int) -> bool:
    """The match is part of a longer token: a letter, digit or underscore beside it, or a decimal point before it
    (``0.021020637``) or between it and a digit after it (``0912345678.5``); a full stop ending a sentence is fine."""
    before = line[start - 1] if start else ""
    after = line[end] if end < len(line) else ""
    if _word(before) or before == "." or _word(after):
        return True
    return after == "." and line[end + 1 : end + 2].isdigit()


class ConfigError(ValueError):
    pass


def load_patterns(path: Path = PATTERNS) -> list[Pattern]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ph = _placeholders()
    out: list[Pattern] = []
    for p in doc["patterns"]:
        pid = p["id"]
        try:
            if "phi_guard" in p:
                rx = getattr(phi_guard, p["phi_guard"])
                if not isinstance(rx, re.Pattern):
                    raise ConfigError(f"{pid}: tb_common.phi_guard.{p['phi_guard']} is not a compiled pattern")
            else:
                src = re.sub(r"\{(\w+)\}", lambda m: ph.get(m.group(1), m.group(0)), p["regex"])
                rx = re.compile(src)
        except (re.error, AttributeError, KeyError) as e:
            raise ConfigError(f"{path.name}: pattern {pid}: {e}") from e
        check = p.get("check")
        if check and check not in CHECKS:
            raise ConfigError(f"{path.name}: pattern {pid}: unknown check {check!r}")
        digits = p.get("digits")
        try:
            needs = re.compile(p["needs"]) if p.get("needs") else None
            near = re.compile(re.sub(r"\{(\w+)\}", lambda m: ph.get(m.group(1), m.group(0)), p["near"])) \
                if p.get("near") else None  # fmt: skip
        except re.error as e:
            raise ConfigError(f"{path.name}: pattern {pid}: needs/near: {e}") from e
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


def load_allow(path: Path = ALLOW) -> Allow:
    """``value | <pattern> | <the value> | <reason>`` or ``path | <pattern or *> | <glob> | <reason>`` per line; a
    line without a reason, an unknown kind or a pattern id the scan does not have is refused."""
    known = {p.id for p in load_patterns()} | {"*", "data_file"}
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
@dataclass(frozen=True)
class Hit:
    where: str
    line: int
    pattern: str
    shown: str

    def __str__(self) -> str:
        return f"{self.where}:{self.line}: {self.pattern}: {self.shown}"


def _norm(s: str) -> str:
    return DASH_IN_NUMBER.sub("-", unicodedata.normalize("NFKC", s).translate(ZERO_WIDTH))


def mask(s: str) -> str:
    """The first and last two characters, never the whole: a short match shows one character."""
    s = s.strip()
    if len(s) <= 5:
        return s[:1] + "*" * (len(s) - 1)
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


def scan_text(text: str, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = _norm(raw)
        if not line.strip():
            continue
        for p in patterns:
            if _path_allowed(where, p.id, allow):
                continue
            for text_hit in p.hits(line):
                v = _norm(text_hit)
                if v in allow.values.get(p.id, set()) or v in allow.values.get("*", set()):
                    continue
                out.append(Hit(where, n, p.id, mask(v)))
    return out


def _path_allowed(where: str, pid: str, allow: Allow) -> bool:
    return any((ap == "*" or ap == pid) and fnmatch.fnmatch(where, glob) for glob, ap in allow.paths)


def _decode(data: bytes) -> str | None:
    if b"\0" in data[:8192]:
        return None
    for enc in ("utf-8", "utf-16", "cp950", "cp932", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def scan_bytes(data: bytes, where: str, patterns: list[Pattern], allow: Allow) -> list[Hit]:
    """A file's content: an archive's members one by one, a gzip's content, a text file's lines; binaries skipped."""
    low = where.lower()
    if len(data) > MAX_BYTES:
        return [Hit(where, 0, "unscanned", f"larger than {MAX_BYTES >> 20} MB")]
    if low.endswith((".tar", ".tgz", ".tar.gz")):
        out = []
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            for m in tf.getmembers():
                f = tf.extractfile(m) if m.isfile() else None
                if f is not None:
                    out += scan_bytes(f.read(), f"{where}!{m.name}", patterns, allow)
        return out
    if low.endswith((".zip", ".xlsx", ".docx")):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    body = zf.read(info)
                    if info.filename.endswith(".xml"):  # xlsx/docx text: drop the tags, keep the cells' text
                        body = re.sub(rb"<[^>]+>", b"\n", body)
                    out += scan_bytes(body, f"{where}!{info.filename}", patterns, allow)
        return out
    if low.endswith(".gz"):
        return scan_bytes(gzip.decompress(data), where[:-3] + "!gunzip", patterns, allow)
    text = _decode(data)
    return [] if text is None else scan_text(text, where, patterns, allow)


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
        try:
            data = p.read_bytes()
        except OSError:
            return []
    try:
        return scan_bytes(data, where, patterns, allow)
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as e:
        return [Hit(where, 0, "unscanned", f"unreadable archive ({type(e).__name__})")]


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
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path, help="files, folders or archives (default: git ls-files here)")
    ap.add_argument("--log", type=Path, action="append", default=[], help="a log file to scan (repeatable)")
    ap.add_argument("--staged", action="store_true", help="the files staged for the next commit (pre-commit hook)")
    a = ap.parse_args(argv)
    try:
        patterns, allow = load_patterns(), load_allow()
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
