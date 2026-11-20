"""Language of study-authored names in the site readiness feasibility table."""

from __future__ import annotations

from typing import Any

import pytest
from console.i18n import translate
from fastapi.testclient import TestClient
from lxml import html  # type: ignore[import-untyped]
from sitesetup import help as site_help
from sitesetup import readiness

from tests.console.test_console_app import box, login  # noqa: F401 - sb uses box
from tests.console.test_site_setup_pages import PW, TODAY, sb  # noqa: F401
from tests.unit.test_site_setup import site_ruleset


@pytest.fixture
def reader(sb: dict[str, Any], monkeypatch: pytest.MonkeyPatch, lang: str) -> TestClient:  # noqa: F811
    # Two selected studies share C1. The older rows carry no language metadata.
    studies = {
        "GZQO": [{"id": "C1", "label": "発作の回数", "lang": "ja"}, {"id": "C2", "label": "年齢"}],
        "RA-BIO": [{"id": "C1", "label": "Age at screening"}, {"id": "C2", "label": "篩檢年齡", "lang": "zh-TW"}],
    }
    study_api = sb["backend"].study_api

    def api(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        route, _, study = path.partition("?study=")
        if route == "/setup/main/feasibility":
            steps = [dict(row, remaining=0, coded=0, confirmed=0, proposed=0) for row in studies[study]]
            return {"study": study, "approved": True, "feas": {"start": 1, "steps": steps}}
        return study_api(method, path, *args, **kwargs)

    monkeypatch.setattr(sb["backend"], "study_api", api)
    client, csrf = login(sb["app"], "crc", PW)
    client.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"}).raise_for_status()
    return client


def _read(client: TestClient, study: str) -> html.HtmlElement:
    response = client.get("/site", params={"study": study})
    assert response.status_code == 200
    return html.fromstring(response.text)


@pytest.mark.parametrize("lang", ["en", "zh-TW"])
def test_japanese_name_on_reload(reader: TestClient, lang: str) -> None:
    for _ in range(2):
        page = _read(reader, "GZQO")
        assert page.get("lang") == lang
        (table,) = page.xpath('//table[@data-testid="feas-basis"]')
        headers = table.xpath("thead/tr/th")
        assert [h.text_content() for h in headers] == [
            translate(lang, "site.feas." + key) for key in ("step", "counted", "coded", "confirmed", "proposed")
        ]
        for header in headers:
            assert header.xpath("ancestor-or-self::*[@lang][1]") == [page]
            assert not header.xpath(".//*[@lang]")
        name, remaining, *_ = table.xpath('.//tr[@data-testid="feas-C1"]/td')
        assert [s.text_content() for s in name.xpath('.//*[@lang="ja"]')] == ["発作の回数"]
        assert name.text_content().strip() == "発作の回数 C1"
        assert remaining.text_content() == "0"
        (older,) = table.xpath('.//tr[@data-testid="feas-C2"]/td[1]')
        assert older.text_content().strip() == "年齢 C2"
        assert not older.xpath("descendant-or-self::*[@lang]")
        assert older.xpath("ancestor::*[@lang][1]/@lang") == [lang]


@pytest.mark.parametrize(("lang", "cid", "label"), [("en", "C1", "Age at screening"), ("zh-TW", "C2", "篩檢年齡")])
def test_name_in_page_language(reader: TestClient, lang: str, cid: str, label: str) -> None:
    page = _read(reader, "RA-BIO")
    (cell,) = page.xpath(f'//tr[@data-testid="feas-{cid}"]/td[1]')
    assert cell.text_content().strip() == f"{label} {cid}"
    assert cell.xpath("ancestor-or-self::*[@lang][1]/@lang") == [lang]
    assert all(value == lang for value in cell.xpath(".//@lang"))


@pytest.mark.parametrize("lang", ["zh-TW"])
def test_same_criterion_id_in_two_studies(reader: TestClient) -> None:
    for study, label, lang in (("GZQO", "発作の回数", "ja"), ("RA-BIO", "Age at screening", "en")):
        (cell,) = _read(reader, study).xpath('//tr[@data-testid="feas-C1"]/td[1]')
        assert cell.text_content().strip() == f"{label} C1"
        (span,) = cell.xpath(".//span[@lang]")
        assert (span.text_content(), span.get("lang")) == (label, lang)
        assert "data-authored" in span.attrib and span.get("data-given") == translate("zh-TW", "given.mark")


def test_feasibility_supplies_the_approved_study_language(sb: dict[str, Any]) -> None:  # noqa: F811
    study = site_ruleset()
    study.manifest.language = "ja"
    study.criteria[0].label = "発作の回数"
    name, data = site_help.practice_inputs()["dump"]
    sb["svc"].add_sheet("main", "dump", name, data, {}, "crc")
    result = readiness.feasibility(sb["svc"], "main", study, TODAY)
    assert result is not None
    row = result["steps"][0]
    assert (row["label"], row.get("lang")) == ("発作の回数", "ja")
