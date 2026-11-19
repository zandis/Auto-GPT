"""DS-9 coverage using synthetic notices."""

import re
from functools import partial
from html import unescape
from pathlib import Path

import pytest
from console.backend import RulesetInfo
from console.i18n import translate
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tests.console.test_cjk_layout import _as, _setup, box  # noqa: F401
from tests.console.test_home_today import _flag


@pytest.mark.parametrize("lang", ["en", "zh-TW", "ja"])
def test_coordinator_groups_notices_and_keeps_study_links(box, monkeypatch, lang):  # noqa: F811
    _setup(box)
    box["users"].set_scope("crc", affiliation="smo", studies="A,B,C", expires="2099-12-31")
    h = box["app"].state.helpers
    backend = box["backend"]
    monkeypatch.setattr(backend, "rulesets", lambda: [RulesetInfo(rs, "1.0.0", "approved", "trial") for rs in "ABC"])

    def study_api(method, path, body, headers=None):
        if method == "GET" and re.fullmatch(r"/studies/[AB]/subjects/S-0001\?today=[\d-]+", path):
            return {"subject": {"record": "S-0001", "state": "completed", "since": "2026-10-01"}}
        return {}

    monkeypatch.setattr(backend, "study_api", study_api, raising=False)
    rows = [
        dict(rs=rs, record="S-0001", event="ae1", ae_term="Synthetic event", ae_onset="2026-10-01", fatal=False)
        for rs in ("A", "B")
    ]
    report = dict(rows[0], party="sponsor", due="2026-10-03")
    monkeypatch.setattr(h, "life_home", lambda _: dict(studies=[], sae_failed=["C"], sae=rows, reports=[report]))
    client = _as(box, "crc", lang)
    response = client.get("/home")
    assert response.status_code == 200
    page = unescape(response.text)
    assert page.count('role="alert"') == 1
    assert re.findall(r'data-sev="(\w+)"', page) == ["urgent", "warn"]
    t = partial(translate, lang)
    assert t("home.smo_banner", studies="A, B, C", until="2099-12-31") in page
    assert t("sae.home_failed", studies="C") in page
    for row in rows:
        rs = row["rs"]
        assert t("life.sae.row", r=row["record"], rs=rs, term=row["ae_term"], day=row["ae_onset"]) in page
        href = f"/studies/{rs}/subjects/S-0001"
        assert page.count(f'href="{href}">{t("life.sae.open")}</a>') == (2 if rs == "A" else 1)
        subject = client.get(href)
        assert subject.status_code == 200
        assert 'data-testid="life-now"' in subject.text
        assert f'href="/studies/{rs}/subjects" data-testid="to-subjects"' in subject.text
    assert (
        t("life.reports.row", r=report["record"], rs="A", party=t("life.clock.party.sponsor"), day=report["due"])
        in page
    )


def test_read_failure_stays_inside_needs_you_today(box, monkeypatch):  # noqa: F811
    _setup(box)
    box["users"].set_scope("crc", affiliation="smo", studies="GZQO", expires="2099-12-31")
    h = box["app"].state.helpers
    monkeypatch.setattr(h, "home_saes", lambda _: dict(unacked=[], reports=[], failed=True))
    _flag(box, "on")
    response = _as(box, "crc", "en").get("/home")
    assert response.status_code == 200
    page = unescape(response.text)
    failure = translate("en", "sae.home_failed", studies="GZQO")
    assert page.count(failure) == 1
    today = page.split('data-testid="today"', 1)[1].split("</section>", 1)[0]
    assert failure in today
    assert re.findall(r'data-sev="(\w+)"', page) == ["urgent", "warn"]
    assert page.count('role="alert"') == 1


def test_week_compact_sae_contains_original_notice_and_subject_link(box):  # noqa: F811
    _setup(box)
    response = _as(box, "drsato", "en").get("/studies/GZQO/week")
    assert response.status_code == 200
    page = unescape(response.text)
    fold = re.search(r'<details data-testid="sae-fold"><summary>(.*?)</summary>(.*?)</details>', page, re.S)
    assert fold
    t = partial(translate, "en")
    assert f"{t('life.sae.title')} · 1" in fold[1]
    assert t("life.sae.help") in fold[2]
    assert t("life.sae.row", r="S-0001", rs="GZQO", term="synthetic event", day="2026-10-01") in fold[2]
    assert f'href="/studies/GZQO/subjects/S-0001">{t("life.sae.open")}</a>' in fold[2]


@pytest.fixture
def templates():
    root = Path(__file__).resolve().parents[2] / "services/console/templates"
    return Environment(loader=FileSystemLoader(root), autoescape=select_autoescape())


@pytest.mark.nodb
@pytest.mark.parametrize(
    ("tone", "style", "role"),
    [("info", "card", ""), ("warn", "warn", ""), ("urgent", "error", "alert"), ("done", "ok", "status")],
)
def test_each_tone_uses_its_token_backed_class_and_role(templates, tone, style, role):
    render = templates.get_template("_severity.html").module.severity_banners
    assert not render([]).strip()
    assert not render([(tone, "")]).strip()
    page = render([(tone, "Synthetic notice")]).strip()
    role_attr = f' role="{role}"' if role else ""
    assert page.startswith(f'<div class="bn {style}" data-sev="{tone}"{role_attr}>')
    assert "Synthetic notice" in page


@pytest.mark.nodb
def test_overflow_keeps_all_bodies_and_actions_in_priority_order(templates):
    page = templates.from_string("""
        {% from "_severity.html" import severity_banners %}
        {{ severity_banners(notices) }}
    """)
    # Use Jinja-rendered markup to exercise its normal auto-escaping boundary.
    action = templates.from_string("""
        {% macro link(i) %}<a href="/action/{{ i }}">Message {{ i }}</a>{% endmacro %}
    """).module.link
    tones = ["done", "urgent", "info", "urgent", "warn"]
    rendered = page.render(notices=[(tone, action(i)) for i, tone in enumerate(tones)])
    assert rendered.count('role="alert"') == 1
    assert rendered.count('role="status"') == 1
    banners = re.split(r'<div class="bn [^>]+>', rendered)[1:]
    assert [re.findall(r'<a href="/action/(\d+)">Message \1</a>', body) for body in banners] == [
        ["1", "3"],
        ["4", "2", "0"],
    ]


@pytest.mark.nodb
def test_environment_notice_and_inline_feedback_stay_in_place(templates):
    # Coordinator home has no field validation path. Render a synthetic inline
    # error alongside the component and the real global notice from base.html.
    page = templates.from_string("""
        {% extends "base.html" %}
        {% from "_severity.html" import severity_banners %}
        {% block content %}
        {{ severity_banners([('urgent', 'Urgent notice'), ('warn', 'Warning notice'),
                             ('info', 'Information notice')]) }}
        <form id="synthetic-field">
          <label for="id-protocol">{{ t('sid.protocol_no') }}</label>
          <input id="id-protocol" aria-describedby="id-protocol-hint" aria-invalid="true">
          <p class="error" id="id-protocol-hint">{{ t('date.fmt') }}</p>
        </form>
        {% endblock %}
    """).render(
        t=partial(translate, "en"),
        lang="en",
        settings=dict(environment_label="REHEARSAL", environment="test", data_class="D1"),
    )
    header, main = page.split('<main id="main">', 1)
    assert 'role="note" data-testid="banner"' in header
    form = main.split('<form id="synthetic-field">', 1)[1].split("</form>", 1)[0]
    assert 'aria-describedby="id-protocol-hint" aria-invalid="true"' in form
    assert f'id="id-protocol-hint">{translate("en", "date.fmt")}</p>' in form
    assert "data-sev=" not in form
    assert re.findall(r'data-sev="(\w+)"', main) == ["urgent", "warn"]
    assert main.count('role="alert"') == 1
