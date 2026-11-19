"""J-7 (D-1251; the journey review's R22): what a clinical page may show, decided by an allow-list.

A page's visible text is split in two by marking every text of the console's catalogue (each literal part of each
catalogue text is wrapped in two private-use characters while a test runs, :func:`mark_catalogues`):

* **catalogue text** (inside the marks) may hold no identifier-shaped token (an upper-case code such as ``FEAS``, a
  ``snake_case`` or ``TB_*`` name, a dotted key) other than the plain acronyms of :data:`ACRONYMS`;
* **everything else** (outside the marks: a value put into a text, a value a template writes as it is) must be a
  data value (:func:`data_value`): a number, a date or a time, a range, a pseudonym, a study code, a criterion id, a
  criteria version, an e-mail address, a person's account name, or a value the test box's fixtures wrote
  (:data:`FIXTURE_DATA`).

Nothing is decided by a list of forbidden words. Text a page does not show is not read: a hidden field's value, a
``<script>`` or ``<style>``, an ``<option>``'s value (its label is read)."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import pytest

OPEN, CLOSE = "", ""
_PLACEHOLDER = re.compile(r"(\{[^{}]*\})")

#: plain acronyms a clinical page may show in catalogue text (each a word a clinical reader knows, or a product name)
ACRONYMS = frozenset(
    {
        "AE", "AI", "AIS", "ALCOA", "API", "ATC", "BMI", "CDAI", "CDASH", "CDISC", "CRA", "CRC", "CRF", "CRO", "CSV",
        "CTCAE", "CTR", "DAS", "DOCX", "DPO", "ECG", "EDC", "EHR", "EMR", "FAQ", "FHIR", "GCP", "GPU", "HIS", "HTML",
        "ICD", "ICF", "ICH", "IRB", "JRCT", "JSON", "LOINC", "MRN", "NCT", "NHI", "OCR", "ODM", "OMOP", "PDF", "PHI",
        "PI", "PII", "PMDA", "QR", "README", "SAE", "SDAI", "SDV", "SHA", "SIV", "SMO", "SMTP", "SNOMED", "SOP",
        "SUSAR", "TFDA", "TREC", "TXT", "UMIN", "UTC", "UTF", "XLSX", "YYYY", "ZIP", "Shift_JIS",
    }
)  # fmt: skip
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|[a-z]+(?:\.[a-z_]+){2,}|\b[A-Z][A-Z0-9]{2,}\b")

#: values the test box's fixtures wrote that a page shows as they are (criterion labels, a doctor, a department, a site)
FIXTURE_DATA = frozenset(
    {
        "Gout", "Flares", "Dialysis", "Dr Lin", "DR-LIN", "RHEU", "Dr L", "TrialBox", "GZQO", "RA-BIO",
        "two flares this spring", "confirm flare dates with patient", "Asia/Taipei", "CTCAE v5.0",
        # the IRB's own sentence, kept in English as the IRB form writes it (console.sitestore.IRB_SENTENCE_EN)
        "Identified pre-screening across departments by the investigator before referral",
        # the test box's account names (tests.console.test_role_route_matrix.COLUMNS)
        "admin", "crc", "pi", "lpi", "smo", "cra", "viewer", "stw", "dpo",
    }
)  # fmt: skip
#: the language names of the language switch, written in their own language on every page
LANGUAGE_NAMES = frozenset({"English", "日本語", "繁體中文"})
_DATA = re.compile(
    r"[<>≤≥~±+−-]?\d[\d.,:/\-–~]*%?"  # a number, a date, a time, a range, a count
    r"|[0-9a-f]{8}|[0-9a-f]{32}"  # a pseudonym
    r"|v\d+(?:\.\d+)*"  # a criteria version
    r"|[A-Z0-9]{2,16}-(?:INC|EXC)-\d{1,3}"  # a criterion id
    r"|[A-Z0-9]{2,16}-\d{0,6}"  # a screening or participant number, or its prefix
    r"|[\w.+-]+@[\w.-]+"  # an e-mail address
    r"|…[0-9A-Z]{4,26}|(?=[0-9A-Z]*\d)[0-9A-HJKMNP-TV-Z]{26}"  # an id cut short, an id
    r"|[A-Z]"  # a key of the keyboard (an access key)
    r"|[^\w\s]+"  # punctuation and symbols only
)


def mark(text: str) -> str:
    """``text`` with each literal part (not a ``{placeholder}``) wrapped in the marks."""
    return "".join(p if _PLACEHOLDER.fullmatch(p) or not p else f"{OPEN}{p}{CLOSE}" for p in _PLACEHOLDER.split(text))


def mark_catalogues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every text of every catalogue marked, for this test only (the dictionaries are changed in place, so every
    module's reference sees the marks)."""
    from console.i18n import CATALOGUES
    from tb_common import reasons

    for cat in (*CATALOGUES.values(), *reasons.LABELS.values()):  # the console's catalogue; the reasons' words
        for key, value in list(cat.items()):
            if isinstance(value, str):
                monkeypatch.setitem(cat, key, mark(value))


def unmark(text: str) -> str:
    return text.replace(OPEN, "").replace(CLOSE, "")


_SKIP_ELEMENTS = re.compile(r"<(script|style|head|template)\b.*?</\1>", re.S | re.I)
_HIDDEN_INPUT = re.compile(r'<input[^>]*type="hidden"[^>]*>', re.I)
_ATTR = re.compile(r'\s(title|placeholder|alt)="([^"]*)"')
_BUTTON_VALUE = re.compile(r'<input[^>]*type="(?:submit|button)"[^>]*value="([^"]*)"', re.I)


def visible(page: str) -> list[str]:
    """The texts a reader sees on ``page`` (text nodes and the attributes a browser shows), each unescaped."""
    page = _HIDDEN_INPUT.sub("", _SKIP_ELEMENTS.sub("", page))
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    out = [html.unescape(m.group(2)) for m in _ATTR.finditer(page)]
    out += [html.unescape(v) for v in _BUTTON_VALUE.findall(page)]
    out += [html.unescape(m) for m in re.findall(r">([^<>]+)<", page)]
    return [re.sub(r"\s+", " ", t).strip() for t in out if t.strip()]


def data_value(chunk: str) -> bool:
    chunk = chunk.strip()
    if not chunk or chunk in FIXTURE_DATA or chunk in LANGUAGE_NAMES or chunk in ACRONYMS:
        return True
    for token in re.split(r"[\s,;:()（）、，：／/·・|]+", chunk):
        token = token.strip(".")
        if token and not (token in ACRONYMS or _DATA.fullmatch(token) or token in _fixture_words()):
            return False
    return True


def _fixture_words() -> frozenset[str]:
    return FIXTURE_DATA | frozenset(w for v in FIXTURE_DATA for w in v.split())


def problems(text: str) -> list[str]:
    """What ``text`` (one visible text, marked) shows that is neither plain catalogue text nor a data value."""
    out: list[str] = []
    for m in re.finditer(f"{OPEN}(.*?){CLOSE}", text, re.S):
        for code in _CODE.findall(m.group(1)):
            if code not in ACRONYMS and code not in FIXTURE_DATA:
                out.append(f"code {code!r} in catalogue text {unmark(text)[:120]!r}")
    rest = re.sub(f"{OPEN}.*?{CLOSE}", " ", text, flags=re.S)
    for chunk in re.split(r"\s{2,}", rest):
        if not data_value(unmark(chunk)):
            out.append(f"not catalogue text nor a data value: {unmark(chunk).strip()[:80]!r} in {unmark(text)[:120]!r}")
    return out


#: pages a walk does not open: Help, Ask and the command field (the journey review's R20, another card), a file, a
#: sign-out or a language change
WALK_SKIP = re.compile(
    r"^/(help|ask|cmd|logout|lang|login|static|role|feedback)(/|$|\?)|\.(xlsx|csv|pdf|zip|json|ics)(\?|$)|/files/"
)


def walk(client: Any, seeds: Iterable[str] = ("/home",), depth: int = 2, limit: int = 150) -> dict[str, list[str]]:
    """Every page reached from ``seeds`` by the links of the pages (``depth`` links deep, at most ``limit`` pages, each
    once), with what each shows that it may not."""
    out: dict[str, list[str]] = {}
    queue = [(s, 0) for s in seeds]
    seen = {s for s in seeds}
    while queue and len(out) < limit:
        path, d = queue.pop(0)
        r = client.get(path)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        found = sorted({p for t in visible(r.text) for p in problems(t)})
        out[path] = found
        if d >= depth:
            continue
        for href in re.findall(r'<a [^>]*href="(/[^"#]*)"', r.text):
            href = html.unescape(href)
            if WALK_SKIP.search(href) or href in seen or urlsplit(href).path.startswith("//"):
                continue
            seen.add(href)
            queue.append((href, d + 1))
    return out
