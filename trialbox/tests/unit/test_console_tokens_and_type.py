"""9k-1 and 9k-2 (D-1368; review 09 DS-1, DS-2, absorbing 9g-17 and 9g-18): the console's colours and type are tokens.

9k-1: every colour ``console.css`` paints is a custom property on ``:root`` (light) or its dark twin under
``prefers-color-scheme: dark``; no literal colour (hex, a colour function, a named colour) stands outside ``:root``
in the style sheet or in any template. The contrast of the pairs that matter is computed here with the WCAG 2.2
formula, in pure Python, in both modes: text 4.5:1, a field's border 3:1 (1.4.11, A11Y-1), the amber row's text on
``--warn-bg`` (A11Y-2). This file is a guard (it reads the tree; no database), so CI runs it on every tier.

9k-2: the type scale and line heights are tokens; Japanese and Traditional Chinese pages get their own line height,
``line-break: strict`` and the word-break rules, and no italic for Han emphasis. System fonts only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"
CSS = CONSOLE / "static" / "console.css"
TEMPLATES = CONSOLE / "templates"

#: the CSS named colours (CSS Color 4), less the keywords a rule may use: transparent, currentColor, inherit
NAMED = frozenset(
    re.findall(
        r"[a-z]+",
        """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood
    cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod
    darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon
    darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray
    dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green
    greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon
    lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon
    lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta
    maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen
    mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive
    olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru
    pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen
    seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato
    turquoise violet wheat white whitesmoke yellow yellowgreen""",
    )
)
HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\(", re.I)
#: a ``:root`` rule whose selector is ``:root`` alone (a list such as ``.x, :root`` is an ordinary rule)
ROOT_BLOCK = re.compile(r"(?:^|(?<=[{}]))\s*:root\s*\{[^{}]*\}")
JS = CONSOLE / "static" / "console.js"
DARK = "@media (prefers-color-scheme: dark)"
#: colour tokens deliberately the same in both modes, so the dark block need not repeat them: the banner's own ink and
#: the production banner (both already dark on light), the black shadows, and print (paper is light in either mode)
SAME_IN_BOTH = frozenset({"--on-banner", "--banner-prod", "--shadow", "--shadow-low", "--print-bg", "--print-ink", "--print-line"})  # fmt: skip


def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def _value_literals(prop: str, value: str) -> list[str]:
    """The literal colours in one declaration's value (font names in quotes and token names left out)."""
    value = re.sub(r"\"[^\"]*\"|'[^']*'|var\(--[\w-]+", "", value)
    found = [f"{prop}: {m}" for m in HEX.findall(value)]
    found += [f"{prop}: {m}" for m in FUNC.findall(value)]
    found += [f"{prop}: {w}" for w in re.findall(r"(?<![\w-])[A-Za-z]+(?![\w-])", value) if w.lower() in NAMED]
    return found


def literal_colours(css: str) -> list[str]:
    """Every literal colour in ``css`` except a custom property's value in a rule whose selector is ``:root`` alone:
    hex, a colour function, a named colour in a declaration's value. A ``:root`` rule's ordinary property (``color``)
    and a selector list that holds ``:root`` among others are checked like any rule."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: list[str] = []
    for selector, body in re.findall(r"([^{}]*)\{([^{}]*)\}", css):  # the innermost blocks: declarations
        is_root = selector.strip() == ":root"
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = (x.strip() for x in decl.split(":", 1))
            if not (is_root and prop.startswith("--")):
                found += _value_literals(prop, value)
    return found


#: where a page can paint in a template: a style attribute (either quote), a style element, an SVG paint attribute
TEMPLATE_PAINT = re.compile(
    r"""\sstyle\s*=\s*"([^"]*)"|\sstyle\s*=\s*'([^']*)'|<style[^>]*>(.*?)</style>"""
    r"""|\s(fill|stroke|stop-color|flood-color|lighting-color|color)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.S | re.I,
)


def template_literals(name: str, text: str) -> list[str]:
    """The literal colours in one template's text: any hex (but a fragment link), and a colour function or name where
    a page could paint (Jinja has its own lab(...) and red words in prose)."""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    bad: list[str] = []
    for m in HEX.finditer(text):
        if not re.search(r"""href\s*=\s*["']$""", text[: m.start()]):  # a link to a fragment (#add) is not a colour
            bad.append(f"{name}: {m.group(0)}")
    for m in TEMPLATE_PAINT.finditer(text):
        dq, sq, element, attr, adq, asq = m.groups()
        if attr is not None:
            value = adq if adq is not None else asq
            if "{{" not in value and value.strip().lower() not in ("none", "currentcolor", "inherit", "transparent"):
                bad += [f"{name}: {x}" for x in _value_literals(attr, value) or [f"{attr}: {value}"]]
        else:
            bad += [f"{name}: {x}" for x in literal_colours("x {" + (dq or sq or element or "") + "}")]
    return bad


def js_literals(js: str) -> list[str]:
    """The literal colours in the console's script: a hex or a colour function in a string, and any colour (a name
    too) given to an element's style or to a paint attribute."""
    js = re.sub(r"/\*.*?\*/|(?<![:\\])//[^\n]*", "", js, flags=re.S)
    bad: list[str] = []
    for s in re.findall(r"\"([^\"\n]*)\"|'([^'\n]*)'|`([^`]*)`", js):
        s = "".join(s)
        bad += [f"string: {m}" for m in HEX.findall(s)] + [f"string: {m}" for m in FUNC.findall(s)]
    for prop, value in re.findall(r"""\.style\.(\w+)\s*=\s*["'`]([^"'`]*)""", js):
        bad += _value_literals(prop, value)
    for prop, value in re.findall(r"""\.style\.setProperty\(\s*["']([\w-]+)["']\s*,\s*["'`]([^"'`]*)""", js):
        bad += _value_literals(prop, value)
    for attr, value in re.findall(
        r"""setAttribute\(\s*["'](style|fill|stroke|stop-color|color)["']\s*,\s*["'`]([^"'`]*)""", js
    ):
        bad += literal_colours("x {" + value + "}") if attr == "style" else _value_literals(attr, value)
    return sorted(set(bad))


def root_blocks(css: str) -> tuple[str, str]:
    """The top-level ``:root`` rule (light) and the ``:root`` inside ``@media (prefers-color-scheme: dark)``."""
    dark_at = css.index(DARK)
    light_block = ROOT_BLOCK.search(css)
    dark_block = ROOT_BLOCK.search(css, dark_at)
    assert light_block and dark_block and light_block.start() < dark_at < dark_block.start()
    return light_block.group(0), dark_block.group(0)


def _decls(block: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;{}]+)", block)}


def tokens(css: str | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """The light tokens (the top-level ``:root``) and the dark ones (light, overridden by the ``:root`` inside
    ``@media (prefers-color-scheme: dark)``)."""
    light_block, dark_block = root_blocks(_css() if css is None else css)
    light = _decls(light_block)
    return light, {**light, **_decls(dark_block)}


def _is_colour(value: str) -> bool:
    return bool(HEX.fullmatch(value) or FUNC.match(value) or value.lower() in NAMED)


def mode_gaps(css: str) -> list[str]:
    """What breaks "every colour token is defined in both modes": a light colour token the dark block does not set
    (unless it is one of ``SAME_IN_BOTH``), and a name the dark block sets that light does not define."""
    light_block, dark_block = root_blocks(css)
    light, dark = _decls(light_block), _decls(dark_block)
    colours = {k for k, v in light.items() if _is_colour(v)}
    gaps = [f"not set for dark: {k}" for k in sorted(colours - SAME_IN_BOTH - set(dark))]
    gaps += [f"dark only: {k}" for k in sorted(set(dark) - set(light))]
    gaps += [f"not a colour in dark: {k}" for k in sorted(set(dark) & colours) if not _is_colour(dark[k])]
    return gaps


def luminance(colour: str) -> float:
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    assert re.fullmatch(r"[0-9a-fA-F]{6}", h), colour

    def channel(v: str) -> float:
        c = int(v, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(h[i : i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ------------------------------------------------------------------------------------------- 9k-1: no literal colour


def test_the_lint_finds_a_planted_literal_and_passes_tokens() -> None:
    for planted in (".x { color: #fff; }", ".x { background: rgb(0 0 0 / .1); }", ".x { border: 1px solid red; }",
                    "@media print { .x { color: Black; } }", ".x { background: color-mix(in srgb, var(--bg), #000); }"):  # fmt: skip
        assert literal_colours(planted), planted
    clean = (
        ":root { --a: #fff; --s: rgba(0,0,0,.1); } .x { color: var(--a); white-space: nowrap; background: transparent; "
        'border-color: currentColor; font-family: "Tan Sans", sans-serif; }'
    )
    assert literal_colours(clean) == []


def test_no_literal_colour_outside_root_in_the_style_sheet() -> None:
    assert literal_colours(_css()) == []


def test_the_lint_checks_a_selector_list_holding_root_and_a_root_rule_s_own_colour() -> None:
    assert literal_colours(".x, :root { color: #fff; }") == ["color: #fff"]
    assert literal_colours(":root, .x { --a: red; }") == ["--a: red"]
    assert literal_colours(":root { color: red; --a: #fff; }") == ["color: red"]
    assert literal_colours(".x { --a: #fff; }") == ["--a: #fff"]  # a token set outside :root is a literal too
    assert literal_colours("@media (prefers-color-scheme: dark) { :root { --a: #000; } }") == []


def test_the_template_lint_finds_each_planted_case() -> None:
    planted = {
        '<p style="color: red">': "color: red",
        "<p style='color: red'>": "color: red",
        "<p style='background: rgb(0 0 0)'>": "background: rgb(",
        "<style>.x { color: #fff }</style>": "#fff",
        '<svg><rect fill="#253a5e"/></svg>': "#253a5e",
        "<svg><path stroke='white'/></svg>": "stroke: white",
        '<svg><circle fill="red"/></svg>': "fill: red",
        '<svg><circle fill="rgb(1,2,3)"/></svg>': "fill: rgb(",
    }
    for text, expect in planted.items():
        found = template_literals("t.html", text)
        assert any(expect in x for x in found), (text, found)
    clean = (
        '<a href="#add">x</a><svg><path fill="none" stroke="currentColor"/><rect fill="{{ c }}"/></svg>'
        '<a href="/entry?prefill=done">red</a><p style="font-weight: 600">'
    )
    assert template_literals("t.html", clean) == []


def test_no_literal_colour_in_any_template() -> None:
    """A page names no colour: ``theme-color`` comes from ``console.phone.THEME`` (the same value as ``--banner``)."""
    bad: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        bad += template_literals(path.name, path.read_text(encoding="utf-8"))
    assert bad == []


def test_the_script_lint_finds_each_planted_case() -> None:
    for planted in ("el.style.color = 'red';", 'el.style.background = "#fff";', "x = `rgba(0,0,0,.1)`;",
                    "el.setAttribute('fill', '#253a5e');", "el.setAttribute('style', 'color: navy');",
                    "el.style.setProperty('border-color', 'black');", "const c = '#1d5fa8';"):  # fmt: skip
        assert js_literals(planted), planted
    clean = "el.style.color = 'var(--ink)'; // #fff in a comment\nel.hidden = true; q('a.red');"
    assert js_literals(clean) == []


def test_no_literal_colour_in_the_script() -> None:
    assert js_literals(JS.read_text(encoding="utf-8")) == []


def test_every_token_used_is_defined_and_the_page_colours_match_python() -> None:
    from console import phone

    light, _ = tokens()
    used = set(re.findall(r"var\((--[\w-]+)", _css()))
    assert used - set(light) == set()
    assert light["--banner"] == phone.THEME and light["--bg"] == phone.BACKGROUND  # the manifest and theme-color


def test_every_colour_token_is_defined_for_light_and_for_dark() -> None:
    assert mode_gaps(_css()) == []
    assert set(tokens()[0]) >= SAME_IN_BOTH  # each exemption names a real token


def test_the_mode_check_finds_a_token_missing_from_dark_and_one_only_in_dark() -> None:
    base = ":root { --bg: #fff; --ink: #000; --t-body: 16px; }\n" + DARK + " { :root { --bg: #111; %s } }"
    assert mode_gaps(base % "--ink: #eee;") == []  # a size token needs no dark value
    assert mode_gaps(base % "") == ["not set for dark: --ink"]
    assert mode_gaps(base % "--ink: #eee; --glow: #0f0;") == ["dark only: --glow"]


# ------------------------------------------------------------------------------------------- 9k-1: contrast


def _rule_token(css: str, selector: str, prop: str) -> str:
    """The token a rule paints ``prop`` with (``a { color: var(--accent) }`` gives ``--accent``), so that a rule moved
    onto a new token is checked under its new name."""
    m = re.search(r"(?:^|[{}])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    v = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:[^;]*var\((--[\w-]+)\)", m.group(1))
    assert v, (selector, prop)
    return v.group(1)


LINK = ("a", "color")
#: a pair: the foreground (a token, or a rule and property whose token it is), the background token, the minimum
Pair = tuple[str | tuple[str, str], str, float]
FOCUS = ("button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible",
         "outline")  # fmt: skip

#: (foreground, background, minimum): text 4.5:1 (1.4.3), a field's border and the focus ring 3:1 (1.4.11); LINK and
#: FOCUS stand for the token the rule paints with
PAIRS: list[Pair] = [
    ("--ink", "--bg", 4.5),
    ("--ink", "--card", 4.5),
    ("--muted", "--bg", 4.5),
    ("--muted", "--card", 4.5),
    (LINK, "--bg", 4.5),
    (LINK, "--card", 4.5),
    (LINK, "--warn-bg", 4.5),  # a link in the amber row
    (LINK, "--ok-bg", 4.5),  # a link in an ok note
    ("--accent", "--bg", 4.5),
    ("--accent", "--card", 4.5),
    ("--accent-ink", "--accent", 4.5),
    ("--ok", "--ok-bg", 4.5),
    ("--bad", "--bad-bg", 4.5),
    ("--warn", "--warn-bg", 4.5),
    ("--warn", "--card", 4.5),  # warning text on a card
    ("--bad", "--card", 4.5),  # error text on a card
    ("--ink", "--warn-bg", 4.5),  # the amber row's text (A11Y-2, 9g-18)
    ("--muted", "--warn-bg", 4.5),
    ("--on-banner", "--banner", 4.5),
    ("--on-banner", "--banner-prod", 4.5),
    ("--print-ink", "--print-bg", 4.5),
    ("--control", "--card", 3.0),  # a field's border (A11Y-1, 9g-17)
    ("--control", "--bg", 3.0),
    ("--control", "--warn-bg", 3.0),  # a field in the amber row
    (FOCUS, "--bg", 3.0),  # the focus ring against what lies next to it (2.4.13 / 1.4.11)
    (FOCUS, "--card", 3.0),
    (FOCUS, "--warn-bg", 3.0),
    (FOCUS, "--ok-bg", 3.0),
]


def contrast_failures(css: str, mode: str, pairs: list[Pair] = PAIRS) -> list[str]:
    """Each pair of ``pairs`` under its minimum in ``mode`` of ``css``, as a sentence."""
    light, dark = tokens(css)
    t = light if mode == "light" else dark
    bad: list[str] = []
    for fg, bg, minimum in pairs:
        name = _rule_token(css, *fg) if isinstance(fg, tuple) else fg
        ratio = contrast(t[name], t[bg])
        if ratio < minimum:
            bad.append(f"{mode}: {name} {t[name]} on {bg} {t[bg]} is {ratio:.2f}:1, under {minimum}:1")
    return bad


def _id(p: object) -> str:
    return "link" if p == LINK else "focus" if p == FOCUS else str(p)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS, ids=_id)
def test_contrast_of_each_pair_in_each_mode(mode: str, fg: str | tuple[str, str], bg: str, minimum: float) -> None:
    assert contrast_failures(_css(), mode, [(fg, bg, minimum)]) == []


def test_a_bad_dark_link_colour_fails_and_light_stays_green() -> None:
    css = _css()
    link = _rule_token(css, *LINK)
    _, dark_block = root_blocks(css)
    planted_dark = re.sub(rf"(?<![\w-]){re.escape(link)}\s*:\s*[^;]+", f"{link}: #3d5f88", dark_block)
    assert planted_dark != dark_block
    planted = css.replace(dark_block, planted_dark)
    failing = contrast_failures(planted, "dark")
    assert any(f"{link} #3d5f88 on --warn-bg" in x for x in failing), failing
    assert any(f"{link} #3d5f88 on --card" in x for x in failing), failing
    assert contrast_failures(planted, "light") == []
    # a link moved onto a token of its own is checked under that name
    moved = planted.replace("a { color: var(--accent); }", "a { color: var(--link); }", 1)
    moved = moved.replace(":root {", ":root { --link: #1d5fa8;", 1).replace(
        planted_dark, planted_dark[:-1] + " --link: #3d5f88; }"
    )
    assert any("--link #3d5f88" in x for x in contrast_failures(moved, "dark"))


def test_the_contrast_formula_on_known_values() -> None:
    assert round(contrast("#000", "#fff"), 2) == 21.0
    assert round(contrast("#767676", "#fff"), 2) == 4.54  # the familiar AA grey
    assert contrast("#d8dde4", "#fff") < 3  # --line: why a field needs --control (A11Y-1)


def test_fields_have_the_control_border_and_the_amber_row_its_token() -> None:
    css = _css()
    field = re.search(r"input, select, textarea \{([^}]*)\}", css)
    assert field and "border: 1px solid var(--control)" in field.group(1)
    rows = re.findall(r"tr\.amber td \{([^}]*)\}", css)
    assert rows and all("background: var(--warn-bg)" in r for r in rows)
    assert "color-mix" not in css


# ------------------------------------------------------------------------------------------- 9k-2: type


def _px(value: str) -> int:
    m = re.fullmatch(r"(\d+)px", value)
    assert m, value
    return int(m.group(1))


def test_the_type_scale_is_tokens_used_by_body_and_headings() -> None:
    light, _ = tokens()
    scale = [_px(light[k]) for k in ("--t-meta", "--t-body", "--t-h2", "--t-lead", "--t-h1", "--t-num")]
    assert scale == sorted(scale) and scale[0] >= 15  # D-133: no text under 15 px
    assert float(light["--lh"]) == 1.5 and float(light["--lh-cjk"]) >= 1.6 and float(light["--lh-head"]) >= 1.3
    css = _css()
    assert re.search(r"body \{ margin: 0; font: var\(--t-body\)/var\(--lh\) ", css)
    # 9k-3 (D-1375): one base. The D-133 layer's second `body { font-size: var(--t-body); }` is gone with the layer, and
    # no other rule sets the body's size (print included: it stays 16 px, as the layer made it)
    assert not re.search(r"\bbody \{[^}]*font-size", css)
    assert re.search(r"\nh1 \{ font-size: var\(--t-h1\); line-height: var\(--lh-head\);", css)
    assert re.search(r"\nh2 \{ font-size: var\(--t-h2\); line-height: var\(--lh-head\);", css)
    assert "font-size: 15px" not in css and "font-size: 16px" not in css


def test_japanese_and_chinese_pages_have_their_line_rules() -> None:
    css = _css()
    rule = re.search(r"body:lang\(ja\), body:lang\(zh-TW\) \{([^}]*)\}", css)
    assert rule
    for decl in ("line-break: strict", "line-height: var(--lh-cjk)", "word-break: normal", "overflow-wrap: break-word"):
        assert decl in rule.group(1), decl
    # the em itself in Japanese or Chinese: an English em (lang="en") inside a Japanese page keeps its italic
    em = re.search(r"\nem:lang\(ja\), em:lang\(zh-TW\) \{([^}]*)\}", css)
    assert em and "font-style: normal" in em.group(1)
    assert not re.search(r":lang\([^)]*\)\s+em\b", css)
    for lang in ("ja", "zh-TW"):  # a font stack of its own per language, system fonts only
        assert re.search(rf'body:lang\({lang}\), body \[lang[|]?="{lang}"\] \{{ font-family: ', css), lang
    assert "@font-face" not in css and "url(" not in css
