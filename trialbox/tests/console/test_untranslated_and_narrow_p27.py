"""P-27 (R1+1 batch D): no untranslated text on the console, and nothing wider than a phone from 310 to 640 px.

* **Raw event names on /audit.** ``console.audit_page`` shows an event by its label (``i18n_audit.EVENTS``) and by its
  bare name when it has none. The label walk of ``test_audit_browser`` reads the literal first argument of an
  ``append`` only, so twelve events their writers name through a module constant (``flowledger.EVENT`` =
  ``flow.export`` ...) showed as raw names. The walk here resolves those constants too.
* **The catalogue.** Every key the English catalogue has, ja and zh-TW have; neither holds English words: a text
  equal to the English one with a lower-case word in it, or three lower-case words in a row outside a command
  (``trialbox ...``, ``docker ...``, ``python ...``) and outside placeholders, tags, paths and code.
* **Narrow windows.** Below 640 px ``html`` and ``body`` clip sideways (T-684), so whatever is wider than the window
  is cut off, not scrolled. The phone rules here keep a table scrolling inside its own box, a field, a pill and a
  button to the window's width and the save bar inside the page; and no rule gives an element a fixed width of
  310 px or more outside a wide-window media query.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from console import i18n_audit
from console.app import create_app  # noqa: F401 - imported for its side effect: every page joins its catalogue
from console.i18n import CATALOGUES

from tests.console.test_audit_browser import _CALLS, _NAME, _NOT_EVENTS
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "services" / "console" / "static" / "console.css"
LANGS = ("en", "ja", "zh-TW")


# ------------------------------------------------------------------------------------------------ event labels
def _constants(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        value = getattr(n, "value", None)
        for t in targets:
            if isinstance(t, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
                out[t.id] = value.value
    return out


def constant_event_names() -> dict[str, str]:
    """Every event name an ``append``/``audit``/``_audit`` call takes through a module constant: ``NAME`` of the same
    module or imported ``from <module> import NAME``, or ``<module>.NAME``. Name -> first place found."""
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for top in ("services", "libs", "tools")
             for p in sorted((ROOT / top).rglob("*.py"))}  # fmt: skip
    by_module: dict[str, list[dict[str, str]]] = {}
    for p, t in trees.items():
        by_module.setdefault(p.stem, []).append(_constants(t))
    found: dict[str, str] = {}
    for p, t in trees.items():
        own = _constants(t)
        alias: dict[str, str] = {}
        imported: dict[str, tuple[str, str]] = {}
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                for a in n.names:
                    alias[a.asname or a.name.split(".")[-1]] = a.name.split(".")[-1]
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    alias[a.asname or a.name] = a.name
                    imported[a.asname or a.name] = ((n.module or "").split(".")[-1], a.name)
        for n in ast.walk(t):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            f = n.func
            if (f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else "") not in _CALLS:
                continue
            arg, values = n.args[0], []
            if isinstance(arg, ast.Name):
                if arg.id in own:
                    values = [own[arg.id]]
                elif arg.id in imported:
                    mod, name = imported[arg.id]
                    values = [c[name] for c in by_module.get(mod, []) if name in c]
            elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                values = [
                    c[arg.attr] for c in by_module.get(alias.get(arg.value.id, arg.value.id), []) if arg.attr in c
                ]
            for v in values:
                if _NAME.match(v) and not _NOT_EVENTS.search(v):
                    found.setdefault(v, f"{p.relative_to(ROOT)}:{n.lineno}")
    return found


def test_every_event_written_through_a_constant_has_a_label() -> None:
    found = constant_event_names()
    assert {"flow.export", "egress.leave", "role.acting"} <= set(found)  # the walk reached the constants
    missing = sorted(f"{name} ({where})" for name, where in found.items() if name not in i18n_audit.EVENTS)
    assert not missing, "event names with no label in console/i18n_audit.py EVENTS:\n" + "\n".join(missing)


@pytest.mark.parametrize("lang", LANGS)
def test_the_audit_page_shows_no_raw_event_name(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    names = sorted(constant_event_names())
    for name in names:
        box["audit"].append(name, actor="console:t", detail={"action": "p27"})
    c = _user(box, f"dpo-{lang}", "privacy")
    c.post("/lang", data={"csrf": _csrf(c.get("/").text), "lang": lang, "back": "/"})
    page = c.get("/audit", params={"limit": "500"})
    assert page.status_code == 200
    # the code stays beside its label as a hint (D-451); a label that fell back to the bare name repeats it, and an
    # option of the event filter is the bare name
    raw = [n for n in names if f"<td>{n} <span" in page.text or f">{n}</option>" in page.text]
    assert not raw, f"raw event names on /audit ({lang}): {raw}"
    assert i18n_audit.event_label(lang, "flow.export") in page.text


# ------------------------------------------------------------------------------------------------ the catalogue
_CLEAN = re.compile(r"<[^>]+>|\{[^}]*\}|https?://\S+|`[^`]*`|\S+\.\S+|\S*[/_=@]\S*")
_LOWER_WORD = re.compile(r"(?<![A-Za-z])[a-z]{2,}\b")
_PHRASE = re.compile(r"\b[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}\b")
_COMMAND = re.compile(r"^(?:trialbox|docker|python)\b")


def untranslated(lang: str) -> list[str]:
    en, other = CATALOGUES["en"], CATALOGUES[lang]
    out = [f"{k}: missing" for k in sorted(set(en) - set(other))]
    for k, text in sorted(other.items()):
        bare = _CLEAN.sub("", text)
        if text == en.get(k) and _LOWER_WORD.search(bare):
            out.append(f"{k}: the English text {text[:60]!r}")
        elif (m := _PHRASE.search(bare)) and not _COMMAND.match(m.group(0)):
            out.append(f"{k}: English words {m.group(0)!r}")
    return out


@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
def test_no_untranslated_key_in_ja_or_zh(lang: str) -> None:
    assert len(CATALOGUES[lang]) > 4000  # every page's catalogue joined
    bad = untranslated(lang)
    assert not bad, f"{lang}: untranslated texts:\n" + "\n".join(bad)


def test_the_catalogue_rule_finds_english_left_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CATALOGUES["ja"], "p27.probe", "Export recorded for this study")
    monkeypatch.setitem(CATALOGUES["en"], "p27.probe", "Export recorded for this study")
    monkeypatch.setitem(CATALOGUES["zh-TW"], "p27.probe", "匯出 the file was not sent")
    assert untranslated("ja") == ["p27.probe: the English text 'Export recorded for this study'"]
    assert untranslated("zh-TW") == ["p27.probe: English words 'the file was'"]


# ------------------------------------------------------------------------------------------------ narrow windows
def _blocks(css: str, query: str) -> list[str]:
    """The bodies of every ``@media <query>`` block (one level of nesting)."""
    out = []
    for m in re.finditer(re.escape(f"@media {query}") + r"\s*\{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end() : i - 1])
    return out


def _decl(body: str, selector: str) -> str:
    m = re.search(r"(?:^|[}\n])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", body)
    assert m, selector
    return m.group(1)


def test_below_640_px_nothing_is_wider_than_the_window() -> None:
    css = CSS.read_text(encoding="utf-8")
    phone = "\n".join(_blocks(css, "(max-width: 640px)"))
    assert "overflow-x: clip" in _decl(phone, "html, body")  # T-684: wider is cut off, so nothing may be wider
    table = _decl(phone, "main > table, main :not(.scroll) > table")
    assert "display: block" in table and "max-width: 100%" in table and "overflow-x: auto" in table
    assert "max-width: 100%" in _decl(phone, "main input, main select, main textarea")
    assert "max-width: 100%" in _decl(phone, "main .button, main form.inline > *")
    assert "width: 100%" in _decl(phone, "main input[type=file]")
    assert "margin-left: 0" in _decl(phone, ".savebar") and "margin-right: 0" in _decl(phone, ".savebar")
    assert "max-width: 100%" in _decl(phone, ".pill")


def test_no_rule_fixes_a_width_of_310_px_or_more_outside_a_wide_window() -> None:
    css = CSS.read_text(encoding="utf-8")
    for wide in _blocks(css, "(min-width: 641px)") + _blocks(css, "print"):
        css = css.replace(wide, "")
    css = re.sub(r"/\*.*?\*/|@media[^{]*", "", css, flags=re.S)  # comments and media queries' own conditions
    wide_px = re.findall(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", css)
    assert not [w for w in wide_px if int(w) >= 310], wide_px
