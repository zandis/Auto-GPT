"""UI text completeness (lane H, item 4): no raw text key and no catalogue English on a ja or zh-TW page.

``tools.text_keys`` holds the catalogues apart and checks every literal key; this test reads what it cannot: the
pages as rendered. Every GET page each role can open (the pages of ``test_wording_walk``) is fetched in ja and zh-TW
and the visible text is read for

* a **raw key**: a word shaped like a catalogue key (``wb.n_open``) whose first part is one the catalogue uses;
* **English left in place**: a text that is exactly a catalogue key's English words where that key has other words
  in the page's language.

Synthetic data only."""

from __future__ import annotations

import html
import importlib
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from console.auth import ROLES
from console.i18n import CATALOGUES
from tb_common.egress_edge import ROUTES
from tb_common.flags import DECLARED

from tests.console.test_console_app import _done_case, _done_feas, login, name_pi
from tests.console.test_excluded_page import _with_excluded
from tests.console.test_wording_walk import PW, VALUES, _pages

importlib.import_module("console.app")  # every page module joins its catalogue when the app is imported
LANGS = ("ja", "zh-TW")
_KEYISH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[A-Za-z0-9_-]+)+$")
_ATTRS = ("title", "placeholder", "aria-label", "alt", "value")


_VOID = frozenset(
    ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr")
)


class _Text(HTMLParser):
    """The text a reader sees: text nodes outside script and style, and the words of a few attributes. Left out: an
    element that says it is English (``lang="en"``: an original quoted beside its translation) and an option whose
    words are its own value (a setting's technical value)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[tuple[str, bool]] = []  # (text, in code type: a technical id or value)
        self._stack: list[bool] = []  # per open element: it hides its text
        self._opt: str | None = None
        self._mono: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        hide = tag in ("script", "style") or a.get("lang", "").lower().startswith("en")
        if tag not in _VOID:
            self._stack.append(hide)
            self._mono.append("mono" in a.get("class", "").split())
        if tag == "option":
            self._opt = a.get("value")
        if any(self._stack[:-1]) or (hide and tag not in _VOID):
            return
        for k in _ATTRS:
            if a.get(k) and not (k == "value" and not (tag == "button" or a.get("type") == "submit")):
                self.parts.append((a[k], False))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "option":
            self._opt = None
        if self._stack:
            self._stack.pop()
            self._mono.pop()

    def handle_data(self, data: str) -> None:
        if any(self._stack) or (self._opt is not None and data.strip() == self._opt):
            return
        self.parts.append((data, any(self._mono)))


def texts(page: str) -> list[tuple[str, bool]]:
    p = _Text()
    p.feed(page)
    return [(" ".join(html.unescape(t).split()), mono) for t, mono in p.parts if t.strip()]


#: the route ids the egress page names (``egress.<route>``, ``tb_common.egress_edge.ROUTES``) and the feature flags
#: the flags page names (``tb_common.flags.DECLARED``): technical ids, not catalogue keys; and file names pages quote
TECHNICAL = frozenset(f"egress.{k}" for k in ROUTES) | {"egress.tripwire"} | frozenset(DECLARED)
#: a feature flag's value, written as the flag's own word in a sentence of the flags page ("初期値: – → off")
FLAG_VALUES = frozenset(("on", "off"))
_FILE = re.compile(r"\.(csv|json|xml|html|yaml|yml|pdf|txt|md|py|sh|env)$")


def _prefixes() -> frozenset[str]:
    return frozenset(k.split(".")[0] for k in CATALOGUES["en"] if "." in k)


def findings(page: str, lang: str) -> list[str]:
    """Each raw key and each catalogue English text on ``page`` (in ``lang``), as a line to read."""
    en, cat = CATALOGUES["en"], CATALOGUES[lang]
    english: dict[str, str] = {}
    for k, v in en.items():
        if isinstance(v, str) and cat.get(k) not in (None, v) and re.search(r"[A-Za-z]{3}", v):
            english.setdefault(" ".join(v.split()), k)
    prefixes = _prefixes()
    out: list[str] = []
    for t, mono in texts(page):
        for word in t.split():
            w = word.strip(".,;:()[]\"'")
            if (
                _KEYISH.match(w)
                and w not in TECHNICAL
                and not _FILE.search(w)
                and (w in en or w.split(".")[0] in prefixes)
            ):
                out.append(f"raw key {w!r} in …{t[:80]}…")
        if t in english and not mono and t not in FLAG_VALUES:
            out.append(f"English {t!r} (key {english[t]})")
    return out


def _walk(b: dict[str, Any], user: str, lang: str, tag: str = "") -> tuple[list[str], list[str]]:
    c, csrf = login(b["app"], user, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    paths = _pages(b["app"], VALUES)
    for job in list(b["backend"].jobs):
        paths += _pages(b["app"], {**VALUES, "job_id": job})
    seen, bad = [], []
    dump = os.environ.get("TB_PAGE_DUMP")
    for path in sorted(set(paths)):
        r = c.get(path)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        seen.append(r.url.path)
        if dump:
            Path(dump, f"{tag or user}-{lang}-{path.strip('/').replace('/', '_') or 'home'}.html").write_text(
                r.text, "utf-8"
            )
        bad += [f"{path}: {f}" for f in findings(r.text, lang)]
    return seen, bad


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("role", ROLES)
def test_no_raw_key_or_catalogue_english_on_any_role_page(box: dict[str, Any], role: str, lang: str) -> None:
    _with_excluded(box)
    _done_feas(box["backend"])
    _done_case(box["backend"])
    box["users"].create("walker", role, PW, "walker@hospa.test")
    if role == "investigator":
        name_pi(box, "walker")
    seen, bad = _walk(box, "walker", lang, role)
    assert len(seen) >= 5
    assert bad == []


# ------------------------------------------------------------------------------------------------ the templates
TEMPLATES = Path(__file__).resolve().parents[2] / "services" / "console" / "templates"
#: what a template may say in plain English words: a key name, a format, a sample value typed into a field as an example
#: ("main": the menu's landmark name; four console tests find the menu by ``<nav aria-label="main"`` in every language,
#: so it stays until the lead rules on them: UITEXT-03)
TECHNICAL_TEXT = frozenset(("main", "Ctrl+P", "male=1,female=2", "LEQ-301,DNB-204", "event_1_arm_1"))
#: a sample request line typed into a field as an example (a command, in the three languages by design)
SAMPLE = "GZQO 這個試驗做得起來嗎？ / Is GZQO feasible here? / FEAS GZQO lookback=36"
_WORD = re.compile(r"\b[A-Za-z][a-z]{2,}\b")
_ELEMENT_TEXT = ("code", "pre", "kbd", "samp")


def _written(raw: str) -> list[str]:
    """What a template writes itself, outside every Jinja tag, comment, script, style and code element: its text
    nodes and the words of ``title``, ``placeholder``, ``aria-label`` and ``alt``."""
    s = re.sub(r"\{%-?\s*set\s+\w+\s*-?%\}.*?\{%-?\s*endset\s*-?%\}", "", raw, flags=re.S)  # an attribute block
    s = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}|<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<(script|style|code|pre|kbd|samp)\b.*?</\1>", "", s, flags=re.S | re.I)
    found = [html.unescape(m.group(2)) for m in re.finditer(r'\b(title|placeholder|aria-label|alt)="([^"]*)"', s)]
    found += [html.unescape(t) for t in re.split(r"<[^>]*>", s)]
    return [" ".join(t.split()) for t in found if t.strip()]


def hard_coded(raw: str) -> list[str]:
    out = []
    for t in _written(raw):
        for tech in (*TECHNICAL_TEXT, SAMPLE):
            t = t.replace(tech, "").strip(" :")
        if _WORD.search(t):
            out.append(t)
    return out


def test_no_template_writes_visible_english_words_of_its_own() -> None:
    bad = {p.name: hard_coded(p.read_text("utf-8")) for p in sorted(TEMPLATES.rglob("*.html"))}
    assert {k: v for k, v in bad.items() if v} == {}


def test_the_template_rule_finds_a_planted_word() -> None:
    assert hard_coded('<h1>{{ t("a.b") }}</h1><p>Save the form</p>') == ["Save the form"]
    assert hard_coded('<nav aria-label="main menu">{{ x }}</nav>') == ["main menu"]
    assert hard_coded('<input placeholder="Name">') == ["Name"]
    assert hard_coded('{# a note #}<p>{{ t("a.b") }}</p><code>1=inclusion</code><script>var open = 1</script>') == []


# ------------------------------------------------------------------------------------------------ the egress page
@pytest.mark.parametrize("lang", LANGS)
def test_the_egress_page_says_its_rules_and_its_rows_in_the_readers_language(tmp_path: Path, lang: str) -> None:
    from console import i18n_egress
    from tb_common import egress_edge, egress_record

    from tests.console.test_console_app import login as sign_in
    from tests.console.test_egress_page import _app

    b = _app(tmp_path)
    c, csrf = sign_in(b["app"])
    h = b["app"].state.rc1_guard.h
    egress_record.write(h.au, actor="t", route="mail.staff", destination="mail:hospa.test", kind="Message", items=1,
                        rule="mask", size=3, sha256="0" * 64, result="masked", reason="")  # fmt: skip
    c.post("/lang", data={"lang": lang, "csrf": csrf})
    page = c.get("/admin/egress").text
    words = {"ja": i18n_egress.JA, "zh-TW": i18n_egress.ZH}[lang]
    for kind in ("mask", "tripwire_on"):
        assert egress_edge.DOCTOR_WORDS[kind] not in page, kind  # the English sentence of a rule
    assert words["egress.rule.mask"] in page or words["egress.rule.unread"].split("{")[0] in page
    assert '<td class="mono">mail.staff</td>' in page  # the route the line names, not "None"
    assert "None" not in page
    assert findings(page, lang) == []
