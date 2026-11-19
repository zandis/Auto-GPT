"""Plan 10 row 10E-17 (D-1244): a capability this box's tier does not include is a status, never an error.

Exit: a home-page text test per tier, in en, ja and zh-TW. The administrator's home (``/home``, the health tab of
``/admin``) shows the 32 GB site box's absences (``models/tiers/rtx5090.json``: no protocol reading on the box, a
question to the models waits while a run holds the card) as plain lines ending "nothing is wrong"; the RTX PRO 6000
box (the full tier) and a box with no tier record show nothing new, byte for byte. A capability the tier does include
and that is broken keeps its warning or error. No other role sees the tile. Synthetic accounts only."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from console import tier_words
from console.auth import ROLES
from console.backend import Health
from console.i18n import translate
from tb_common import tier_value

from tests.console.test_console_app import ADMIN_PW, box, login  # noqa: F401 - the fixture is used by name

LANGS = ("en", "ja", "zh-TW")
#: TB_PROFILE label -> the record it reads (None: no record on file, as on a GB10 or a stub box)
TIERS = {"P-5090": "rtx5090", "P-PRO6000": "rtxpro6000", "P-GB10": None}
NOTHING_WRONG = {"en": "Nothing is wrong.", "ja": "異常ではありません。", "zh-TW": "這不是故障。"}
TITLE = {
    "en": "What this box&#39;s tier includes",
    "ja": "このボックスの構成に含まれる機能",
    "zh-TW": "這台機器的等級包含哪些功能",
}
LACKS = {
    "en": (
        "Protocol reading: this box&#39;s tier does not include it.",
        "Questions to the models during a screening run",
    ),
    "ja": ("プロトコルの読み取り：このボックスの構成には含まれていません。", "スクリーニング実行中のモデルへの質問"),
    "zh-TW": ("計畫書判讀：這台機器的等級不包含此功能。", "篩選執行期間向模型提問"),
}
#: the qualifier of a line worded from a declared field (D-1244): never presented as a measured fact
DECLARED = {
    "en": "As declared for this tier; not yet measured on this hardware.",
    "ja": "この構成について宣言された内容で、このハードウェアではまだ測定されていません。",
    "zh-TW": "此為該等級所宣告的內容，尚未在這台硬體上量測。",
}
_CSRF = re.compile(r'name="csrf" value="[^"]+"')
_LINE = re.compile(
    r'<li data-testid="tier-status-([a-z_]+)" data-level="status">([^<]+?)'
    r'(?: <span class="hint" data-basis="declared">([^<]+)</span>)?</li>'
)


def _tile(page: str) -> str:
    start = page.index('data-testid="tile-tier"')
    return page[start : page.index("</section>", start)]


def _home(c: Any, csrf: str, lang: str) -> str:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    r = c.get("/home")
    assert r.status_code == 200
    return str(r.text)


def _admin(b: dict[str, Any]) -> tuple[Any, str]:
    return login(b["app"], "admin", ADMIN_PW)


# ---------------------------------------------------------------------------------------- the exit: a test per tier
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("label", list(TIERS))
def test_the_home_page_words_each_tier_in_each_language(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    lang: str,
) -> None:
    monkeypatch.setenv("TB_PROFILE", label)
    c, csrf = _admin(box)
    page = _home(c, csrf, lang)
    assert 'data-testid="admin-health"' in page  # the administrator's home is the health tab
    if TIERS[label] != "rtx5090":
        assert 'data-testid="tile-tier"' not in page and TITLE[lang] not in page
        return
    tile = _tile(page)
    assert TITLE[lang] in tile
    lines = _LINE.findall(tile)
    assert [cap for cap, _, _ in lines] == ["protocol_reading", "chat_during_a_screening_run"]
    for (_, text, qualifier), start in zip(lines, LACKS[lang], strict=True):
        assert text.startswith(start) and text.endswith(NOTHING_WRONG[lang]), text
        # the shipped record declares console_promises: each line says it is declared, not measured (D-1244)
        assert qualifier == DECLARED[lang], qualifier
    # a status, not an error: no warning or error pill, no alert, no error class in the tile
    for mark in ("pill", "warn", "bad", "error", 'role="alert"', "attention"):
        assert mark not in tile, mark


# ------------------------------------------- a measured row is worded without the qualifier, a declared one with it
def _site_record(tmp_path: Path, basis: str) -> Path:
    """The shipped 32 GB record with ``console_promises`` given ``basis`` (synthetic: a measured promise is a test's)."""
    doc = json.loads((Path(tier_value.TIERS_DIR) / "rtx5090.json").read_text(encoding="utf-8"))
    field = doc["fields"]["console_promises"]
    field["basis"] = basis
    d = tmp_path / f"tiers-{basis}"
    d.mkdir()
    (d / "rtx5090.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


@pytest.mark.parametrize("basis", ["measured", "declared"])
def test_only_a_declared_row_says_it_is_declared_and_not_measured(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    basis: str,
) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    monkeypatch.setattr(tier_value, "TIERS_DIR", _site_record(tmp_path, basis))
    c, csrf = _admin(box)
    for lang in LANGS:
        tile = _tile(_home(c, csrf, lang))
        lines = _LINE.findall(tile)
        assert [cap for cap, _, _ in lines] == ["protocol_reading", "chat_during_a_screening_run"], lang
        for _, text, qualifier in lines:
            assert text.endswith(NOTHING_WRONG[lang])
            assert qualifier == (DECLARED[lang] if basis == "declared" else ""), (lang, qualifier)
        assert (DECLARED[lang] in tile) == (basis == "declared")
        assert ('data-basis="declared"' in tile) == (basis == "declared")


# ------------------------------------------------------------------------ the full tier and no record: byte for byte
def _pages(c: Any, csrf: str) -> dict[str, str]:
    return {lang: _CSRF.sub("csrf", _home(c, csrf, lang)) for lang in LANGS}


def test_the_full_tier_and_a_box_with_no_record_render_the_home_page_as_before(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, csrf = _admin(box)
    monkeypatch.setattr(tier_words, "lacks", lambda *a, **k: [])  # the page with no tier line: master's page
    before = _pages(c, csrf)
    monkeypatch.undo()
    for label in ("P-PRO6000", "P-GB10", ""):
        monkeypatch.setenv("TB_PROFILE", label)
        assert _pages(c, csrf) == before, label
    # the 32 GB site box's page is the same page with the one tile added after the Models tile
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    site = _pages(c, csrf)
    for lang in LANGS:
        tile = re.search(r'<section class="card tile" data-testid="tile-tier">.*?</section>', site[lang], re.S)
        assert tile and site[lang].replace(tile.group(0), "", 1) == before[lang], lang


# --------------------------------------------------- a broken capability the tier does include stays an error
@pytest.mark.parametrize("label", ["P-5090", "P-PRO6000"])
def test_a_broken_capability_the_tier_includes_still_shows_as_an_error(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    monkeypatch.setenv("TB_PROFILE", label)
    bk = box["backend"]
    # both tiers include judging notes and the gateway: no model answering and the gateway down are errors on both
    bk.models_info = {**bk.models_info, "mode": "none", "judge_model": None, "may_block": False}
    monkeypatch.setattr(
        bk, "health", lambda: [Health("orchestrator", True, ""), Health("gateway", False, "ConnectError")]
    )
    c, csrf = _admin(box)
    broken = _pages(c, csrf)
    with monkeypatch.context() as m:  # the same broken box with no tier line: the page master renders
        m.setattr(tier_words, "lacks", lambda *a, **k: [])
        as_master = _pages(c, csrf)
    for lang in LANGS:
        # unchanged from master: the errors are byte for byte the same, only the status tile is added on the site box
        tile_html = re.search(r'<section class="card tile" data-testid="tile-tier">.*?</section>', broken[lang], re.S)
        assert (tile_html is not None) == (label == "P-5090"), lang
        assert (broken[lang].replace(tile_html.group(0), "", 1) if tile_html else broken[lang]) == as_master[lang]
        page = broken[lang]
        models = page[page.index('data-testid="tile-models"') :]
        models = models[: models.index("</section>")]
        assert f'<span class="pill warn">{translate(lang, "overview.models.no_judge")}</span>' in models, lang
        system = page[page.index('data-testid="tile-system"') :]
        system = system[: system.index("</section>")]
        assert 'data-level="bad"' in system and "gateway · " in system, lang
        assert f'<span class="pill bad">{translate(lang, "health.down")}</span>' in system, lang
        if label == "P-5090":  # the tier's own absences stay statuses beside the errors
            tile = _tile(page)
            assert "pill" not in tile and NOTHING_WRONG[lang] in tile
        else:
            assert 'data-testid="tile-tier"' not in page
    # note exclusion is included on both tiers: when it may not exclude, its warning stays
    bk.models_info = {**bk.models_info, "mode": "single", "judge_model": "j", "may_block": False}
    page = _home(c, csrf, "en")
    assert f'<span class="pill warn">{translate("en", "overview.models.never")}</span>' in page


# ----------------------------------------------------------------------------- no role sees what it did not see
def test_no_other_role_sees_the_tiers_lines(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    pw = "a-long-synthetic-password-10e17"
    for role in ROLES:
        if role == "admin":
            continue
        name = f"t-{role}"[:16]
        box["users"].create(name, role, pw, f"{name}@hospa.test")
        c, _ = login(box["app"], name, pw)
        for path in ("/home", "/admin", "/"):
            r = c.get(path)
            assert 'data-testid="tile-tier"' not in r.text and "tier.lacks" not in r.text, (role, path)


# -------------------------------------------------------------------------------------------- the reader itself
def _record(tmp_path: Path, rows: Any, basis: str = "declared") -> Path:
    d = tmp_path / "tiers"
    d.mkdir(exist_ok=True)
    field = {"basis": basis, "value": rows, "source": "x"}
    (d / "rtx5090.json").write_text(json.dumps({"fields": {"console_promises": field}}), encoding="utf-8")
    return d


def test_the_reader_keeps_only_the_worded_absences_in_the_records_order(tmp_path: Path) -> None:
    env = {"TB_PROFILE": "P-5090"}
    shipped = tier_words.lacks(env)
    assert [r["capability"] for r in shipped] == ["protocol_reading", "chat_during_a_screening_run"]
    assert {r["basis"] for r in shipped} == {"declared"}  # the shipped record declares it
    assert tier_words.lacks({"TB_PROFILE": "P-PRO6000"}) == []  # every row available or not measured
    assert tier_words.lacks({"TB_PROFILE": "P-GB10"}) == [] and tier_words.lacks({}) == []
    rows = [
        {"capability": "chat_during_a_screening_run", "status": "busy_until_the_run_releases_the_card"},
        {"capability": "protocol_reading", "status": "available"},  # included: never a status line
        {"capability": "card_memory_error_correction", "status": "not_measured"},  # unknown, not absent
        {"capability": "a_new_capability", "status": "not_on_this_box"},  # no words yet: nothing shown
        {"capability": "chat_during_a_screening_run", "status": "busy_until_the_run_releases_the_card"},
        "not a row",
    ]
    d = _record(tmp_path, rows)
    assert tier_words.lacks(env, d) == [
        {
            "capability": "chat_during_a_screening_run",
            "status": "busy_until_the_run_releases_the_card",
            "basis": "declared",
        }
    ]
    assert [r["basis"] for r in tier_words.lacks(env, _record(tmp_path, rows, "measured"))] == ["measured"]
    assert tier_words.lacks(env, _record(tmp_path, rows, "not_measured")) == []
    assert tier_words.lacks(env, _record(tmp_path, "not a list")) == []
    (d / "rtx5090.json").write_text("{", encoding="utf-8")
    assert tier_words.lacks(env, d) == []  # malformed: nothing, never an error
    assert tier_words.lacks(env, tmp_path / "nowhere") == []


def test_every_worded_capability_has_its_words_in_three_languages() -> None:
    for cap in tier_words.WORDED:
        for lang in LANGS:
            text = translate(lang, f"tier.lacks.{cap}")
            assert text != f"tier.lacks.{cap}" and text.endswith(NOTHING_WRONG[lang]), (cap, lang)
    for lang in LANGS:
        assert translate(lang, "tier.declared") == DECLARED[lang]
