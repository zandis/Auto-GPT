"""The one-pager of T-318 (TB-PRV-06, D-411) renders in three languages from the synthetic site's settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from tb_common import wording
from tb_common.config import load_settings

from tools import onepager

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "deploy" / "settings.example.yaml"


@pytest.mark.parametrize("lang", onepager.LANGS)
def test_renders_each_language_from_the_test_site(lang: str) -> None:
    settings = load_settings(EXAMPLE)
    page = onepager.render(settings, lang)
    assert page.startswith("# ")
    assert settings.site.name in page.splitlines()[0]
    assert wording.statement(lang) in page
    assert f"<{settings.thresholds.small_cell}" in page
    assert settings.retention is not None
    assert str(settings.retention.audit_years) in page
    assert str(settings.retention.outputs_days) in page
    assert settings.site.contact and settings.site.contact in page
    assert page.count("\n## ") == 8
    assert not wording.check(page), "the one-pager uses a verdict word"


def test_languages_differ_and_use_their_script() -> None:
    settings = load_settings(EXAMPLE)
    pages = {lang: onepager.render(settings, lang) for lang in onepager.LANGS}
    assert len(set(pages.values())) == 3
    assert wording.text_lang(pages["ja"]) == "ja"
    assert wording.text_lang(pages["zh-TW"]) == "zh-TW"


def test_cloud_setting_changes_the_page() -> None:
    settings = load_settings(EXAMPLE)
    assert settings.models is not None and settings.models.cloud_enabled is False
    off = onepager.render(settings, "en")
    on = onepager.render(
        settings.model_copy(update={"models": settings.models.model_copy(update={"cloud_enabled": True})}), "en"
    )
    assert "No cloud service is used" in off
    assert "No cloud service is used" not in on


def test_cli_writes_the_file_in_the_site_locale(tmp_path: Path) -> None:
    out = tmp_path / "page.md"
    assert onepager.main(["--settings", str(EXAMPLE), "--out", str(out)]) == 0
    assert wording.statement("zh-TW") in out.read_text(encoding="utf-8")  # the synthetic site's locale


def test_unknown_language_is_refused() -> None:
    settings = load_settings(EXAMPLE)
    with pytest.raises(ValueError):
        onepager.render(settings, "fr")
