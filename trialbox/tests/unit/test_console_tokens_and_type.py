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
ROOT_BLOCK = re.compile(r":root\s*\{[^{}]*\}")


def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def literal_colours(css: str) -> list[str]:
    """Every literal colour in ``css`` outside a ``:root { ... }`` block: hex, a colour function, a named colour in a
    declaration's value."""
    css = ROOT_BLOCK.sub("", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    found: list[str] = []
    for body in re.findall(r"\{([^{}]*)\}", css):  # the innermost blocks: declarations
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = (x.strip() for x in decl.split(":", 1))
            value = re.sub(r"\"[^\"]*\"|'[^']*'|var\(--[\w-]+", "", value)  # font names, token names
            found += [f"{prop}: {m}" for m in HEX.findall(value)]
            found += [f"{prop}: {m}" for m in FUNC.findall(value)]
            found += [f"{prop}: {w}" for w in re.findall(r"(?<![\w-])[A-Za-z]+(?![\w-])", value) if w.lower() in NAMED]
    return found


def tokens() -> tuple[dict[str, str], dict[str, str]]:
    """The light tokens (the top-level ``:root``) and the dark ones (light, overridden by the ``:root`` inside
    ``@media (prefers-color-scheme: dark)``)."""
    css = _css()
    dark_at = css.index("@media (prefers-color-scheme: dark)")
    light_block = ROOT_BLOCK.search(css)
    dark_block = ROOT_BLOCK.search(css, dark_at)
    assert light_block and dark_block and light_block.start() < dark_at < dark_block.start()

    def parse(block: str) -> dict[str, str]:
        return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;{}]+)", block)}

    light = parse(light_block.group(0))
    return light, {**light, **parse(dark_block.group(0))}


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


def test_no_literal_colour_in_any_template() -> None:
    """A page names no colour: ``theme-color`` comes from ``console.phone.THEME`` (the same value as ``--banner``)."""
    bad: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
        for m in HEX.finditer(text):
            if not text[: m.start()].endswith(('href="', "href='")):  # a link to a fragment (#add) is not a colour
                bad.append(f"{path.name}: {m.group(0)}")
        # a colour function or name only where a page could paint: a style attribute or a style element (Jinja has
        # its own lab(...) and red words in prose)
        for style in re.findall(r"style=\"([^\"]*)\"|<style[^>]*>(.*?)</style>", text, flags=re.S):
            bad += [f"{path.name}: {x}" for x in literal_colours("x {" + "".join(style) + "}")]
    assert bad == []


def test_every_token_used_is_defined_and_the_page_colours_match_python() -> None:
    from console import phone

    light, dark = tokens()
    used = set(re.findall(r"var\((--[\w-]+)", _css()))
    assert used - set(light) == set()
    assert set(dark) == set(light)
    assert light["--banner"] == phone.THEME and light["--bg"] == phone.BACKGROUND  # the manifest and theme-color


# ------------------------------------------------------------------------------------------- 9k-1: contrast

#: (foreground, background, minimum): text 4.5:1 (1.4.3), a field's border 3:1 (1.4.11)
PAIRS = [
    ("--ink", "--bg", 4.5),
    ("--ink", "--card", 4.5),
    ("--muted", "--bg", 4.5),
    ("--muted", "--card", 4.5),
    ("--accent", "--bg", 4.5),
    ("--accent", "--card", 4.5),
    ("--accent-ink", "--accent", 4.5),
    ("--ok", "--ok-bg", 4.5),
    ("--bad", "--bad-bg", 4.5),
    ("--warn", "--warn-bg", 4.5),
    ("--ink", "--warn-bg", 4.5),  # the amber row's text (A11Y-2, 9g-18)
    ("--muted", "--warn-bg", 4.5),
    ("--on-banner", "--banner", 4.5),
    ("--on-banner", "--banner-prod", 4.5),
    ("--print-ink", "--print-bg", 4.5),
    ("--control", "--card", 3.0),  # a field's border (A11Y-1, 9g-17)
    ("--control", "--bg", 3.0),
]


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS)
def test_contrast_of_each_pair_in_each_mode(mode: str, fg: str, bg: str, minimum: float) -> None:
    light, dark = tokens()
    t = light if mode == "light" else dark
    ratio = contrast(t[fg], t[bg])
    assert ratio >= minimum, f"{mode}: {fg} {t[fg]} on {bg} {t[bg]} is {ratio:.2f}:1, under {minimum}:1"


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
    assert re.search(r"\nbody \{ font-size: var\(--t-body\); \}", css)
    assert re.search(r"\nh1 \{ font-size: var\(--t-h1\); line-height: var\(--lh-head\);", css)
    assert re.search(r"\nh2 \{ font-size: var\(--t-h2\); line-height: var\(--lh-head\);", css)
    assert "font-size: 15px" not in css and "font-size: 16px" not in css


def test_japanese_and_chinese_pages_have_their_line_rules() -> None:
    css = _css()
    rule = re.search(r"body:lang\(ja\), body:lang\(zh-TW\) \{([^}]*)\}", css)
    assert rule
    for decl in ("line-break: strict", "line-height: var(--lh-cjk)", "word-break: normal", "overflow-wrap: break-word"):
        assert decl in rule.group(1), decl
    em = re.search(r":lang\(ja\) em, :lang\(zh-TW\) em \{([^}]*)\}", css)
    assert em and "font-style: normal" in em.group(1)
    for lang in ("ja", "zh-TW"):  # a font stack of its own per language, system fonts only
        assert re.search(rf'body:lang\({lang}\), body \[lang[|]?="{lang}"\] \{{ font-family: ', css), lang
    assert "@font-face" not in css and "url(" not in css
