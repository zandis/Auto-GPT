"""9k-3 (D-1375; review 09 DS-3): the console's button. Four variants, one small size, the D-133 override layer gone.

The plan's proof, read from ``console.css``:

* **at most six rule blocks paint a button.** A block paints a button when one of its selectors ends on a button (the
  element ``button``, or the class ``button``, ``secondary``, ``quiet``, ``danger`` or ``small``) and it declares a
  property of look: background, colour, border, radius, font, padding, opacity, cursor, text decoration or shadow
  (review 09 counted 32). A container may still set a button's margin, flex or width: that is the container's layout.
  The focus ring is one rule for every control (links and fields too) and is held by D-1368's contrast test;
* **every target at least 44 px.** The base sets ``min-height`` and ``min-width`` of 44 px, and no rule that reaches a
  button sets a height or width in pixels under 44; the rendered check of every visible button on the first screens
  is ``tests/console/test_button_targets_9k3.py``;
* **the D-133 layer is gone:** none of the sizes it re-set is declared twice outside a media query, and what is left
  under its heading is the two rules that must come after the rules above them (the 22 px check box and the links
  that are targets on their own).

A guard: it reads the tree, no database, so CI runs it on every tier.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"
CSS = CONSOLE / "static" / "console.css"
TEMPLATES = CONSOLE / "templates"
LOOK = re.compile(r"^(background|color|border|font|padding|opacity|cursor|text-decoration|box-shadow)")
BUTTON_CLASSES = frozenset({"button", "secondary", "quiet", "danger", "small"})
#: the six blocks, in order: primary (the base), secondary, quiet, danger, small, disabled or busy
SIX = (
    "button, .button",
    "button.secondary, .button.secondary",
    "button.quiet, .button.quiet",
    "button.danger, .button.danger",
    "button.small, .button.small, .next .button",  # the next-step link of a study card is small (9k-3)
    'button[disabled], button[aria-busy="true"], .button[aria-disabled="true"]',
)


def blocks(css: str) -> list[tuple[str, str, str]]:
    """``(selector list, enclosing at-rules, declarations)`` of every rule, comments removed."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[tuple[str, str, str]] = []
    stack: list[str] = []
    buf = ""
    for ch in css:
        if ch == "{":
            stack.append(buf.strip())
            buf = ""
        elif ch == "}":
            head = stack.pop()
            if not head.startswith("@") and buf.strip():
                out.append((head, " ".join(stack), buf.strip()))
            buf = ""
        else:
            buf += ch
    return out


def selectors(sel: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in sel:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [*parts, cur.strip()]


def is_button(sel: str) -> bool:
    """The selector's subject (its last compound, pseudo-classes and attributes set aside) is a button."""
    s = re.sub(r"\[[^\]]*\]", "", re.sub(r"\([^()]*\)", "", sel))
    last = re.sub(r"::?[\w-]+", "", re.split(r"[\s>+~]+", s.strip())[-1])
    return last.split(".")[0] == "button" or bool(set(re.findall(r"\.([\w-]+)", last)) & BUTTON_CLASSES)


def declarations(body: str) -> list[tuple[str, str]]:
    return [(d.split(":", 1)[0].strip(), d.split(":", 1)[1].strip()) for d in body.split(";") if ":" in d]


def painting_blocks(css: str) -> list[str]:
    return [
        sel
        for sel, _, body in blocks(css)
        if any(is_button(s) for s in selectors(sel)) and any(LOOK.match(p) for p, _ in declarations(body))
    ]


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def test_9k3_at_most_six_rule_blocks_paint_a_button() -> None:
    found = painting_blocks(_css())
    assert len(found) <= 6, found
    assert tuple(found) == SIX  # the four variants, the small size and the disabled or busy look, in this order


def test_9k3_the_counter_sees_a_button_painted_in_a_container() -> None:
    """The counter is not blind: a container that paints its buttons (as `.next .button` and `.markbar .danger` did)
    is counted, a container that only places them is not."""
    assert painting_blocks(".next .button { padding: 4px 14px; }") == [".next .button"]
    assert painting_blocks(".markbar .danger, .x a { color: red; }") == [".markbar .danger, .x a"]
    assert painting_blocks(".savebar button { margin: 0; }\n@media (max-width: 760px) { .x button { flex: 1; } }") == []
    assert painting_blocks("a.rowlink { color: red; } .pill { padding: 1px; }") == []


def test_9k3_every_button_target_is_at_least_44px() -> None:
    css = _css()
    base = dict(declarations(next(b for s, _, b in blocks(css) if s == "button, .button")))
    assert base["min-height"] == "44px" and base["min-width"] == "44px"
    small = []
    for sel, ctx, body in blocks(css):
        if not any(is_button(s) for s in selectors(sel)):
            continue
        for prop, value in declarations(body):
            m = re.fullmatch(r"(\d+(?:\.\d+)?)px", value)
            if prop in ("height", "min-height", "width", "min-width", "max-height") and m and float(m.group(1)) < 44:
                small.append((ctx, sel, prop, value))
    assert small == []


def test_9k3_the_d133_layer_re_sets_nothing() -> None:
    css = _css()
    # the sizes the layer re-set are each declared once outside a media query
    once = {
        ("button", "min-height"), (".button", "padding"), ("button.small", "padding"), ("form.inline select", "min-height"),
        (".markrow form.inline select", "min-height"), ("input", "min-height"), ("select", "min-width"),
        ("nav a", "min-height"), (".rail a", "display"), ("details > summary", "min-height"),
        ("details.more > summary", "min-height"), (".helpq", "width"), (".brand", "min-height"), (".skip:focus", "padding"),
        (".pill", "padding"), (".state", "padding"), ("th", "letter-spacing"), (".markrow", "gap"),
        ("form.cmd input[type=search]", "min-height"), ("body", "font-size"),
    }  # fmt: skip
    seen: dict[tuple[str, str], int] = {}
    for sel, ctx, body in blocks(css):
        if ctx:
            continue
        for s in selectors(sel):
            for prop, _ in declarations(body):
                seen[(s, prop)] = seen.get((s, prop), 0) + 1
    assert {k: n for k, n in seen.items() if k in once and n > 1} == {}
    assert "button.small, form.inline select, .markrow form.inline select, .next .button" not in css
    # under the old heading: only the check box and the target links
    i = css.index("D-133 step 4b: easy for novices")
    j = css.index("\n/* the header: a one-line banner", i)
    left = [s for s, _, _ in blocks(css[css.rindex("/*", 0, i) : j])]
    assert left == [
        "input[type=checkbox], input[type=radio]",
        "td a, dd > a:only-child, li > a:only-child, p > a:only-child, .actions > a, .headrow > a, h2 > a, h3 > a, "
        ".chartlinks a, footer a",
    ]


def test_9k3_templates_use_only_the_four_variants_and_the_small_size() -> None:
    """A button or button-styled link in a template takes no class of look but the variants: no second naming of a
    primary, outline, ghost, link-like, tiny or large button. Layout and test classes are free (``small-btn`` of the
    study card's next-step link styles nothing; the rule ``.next .button`` makes it small); literal class lists only."""
    look_like = re.compile(r"(?:^|[-_])(primary|ghost|outline|link-?button|tiny|large|big)(?:$|[-_])")
    bad = []
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for tag in re.finditer(r"<(button|a)\b[^>]*\bclass=\"([^\"{}]*)\"", text):
            classes = tag.group(2).split()
            if tag.group(1) == "a" and "button" not in classes:
                continue
            bad += [(path.name, c) for c in classes if look_like.search(c)]
    assert bad == []


def test_9k3_danger_is_always_a_secondary_button() -> None:
    """The danger variant is a red outline on a secondary button: every use in a template says ``secondary danger``,
    so the act is never a filled red block next to the page's one primary act (review 09 §3.2)."""
    uses = []
    for path in sorted(TEMPLATES.glob("*.html")):
        for m in re.finditer(r"class=\"([^\"]*\bdanger\b[^\"]*)\"", path.read_text(encoding="utf-8")):
            uses.append((path.name, "secondary" in m.group(1).split()))
    assert uses and all(ok for _, ok in uses), uses
