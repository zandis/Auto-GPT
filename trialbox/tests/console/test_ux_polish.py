"""T-685 (D-402): the clinical UX polish of the 2026-11-10 deep review (the Lows UX-024 to UX-041), in en, ja and
zh-TW. Each test names the finding it closes."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES
from console.i18n_polish import EN as POLISH_EN
from console.i18n_polish import JA as POLISH_JA
from console.i18n_polish import ZH as POLISH_ZH
from jinja2 import Environment, FileSystemLoader
from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput, RegistryEntry

from tests.console.test_cjk_layout import B, _as, _main, _setup
from tests.console.test_console_app import _T0, box  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
TPL = ROOT / "services" / "console" / "templates"
LANGS = ("en", "ja", "zh-TW")


def test_every_language_has_every_new_string() -> None:
    assert set(POLISH_EN) == set(POLISH_JA) == set(POLISH_ZH)
    for lang in LANGS:
        for k in POLISH_EN:
            assert CATALOGUES[lang][k] and CATALOGUES[lang][k] != k, (lang, k)


# ------------------------------------------------------------------------------------------- UX-041 the banner
@pytest.mark.parametrize("lang", LANGS)
def test_desktop_banner_is_plain_and_the_footer_keeps_the_details(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    """UX-041: the desktop banner has the phone banner's plain words: no TB_ENV, no data class; the footer names
    both."""
    _setup(box)
    page = _as(box, "drsato", lang).get("/studies/GZQO/week").text
    banner = re.search(r'data-testid="banner"><span class="long">([^<]+)</span>', page)
    assert banner
    words = html.unescape(banner.group(1))
    assert "TB_ENV" not in words and "D0" not in words and words == CATALOGUES[lang]["pilot.banner"]
    footer = page[page.index("<footer>") :]
    assert "TEST" in footer and "D0" in footer  # the box fixture runs TB_ENV=TEST


# ------------------------------------------------------------------------------------------- UX-035 role words
@pytest.mark.parametrize("lang", LANGS)
def test_coordinator_worklist_help_has_the_coordinator_words(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    """UX-035: on the approached list the coordinator reads "the investigator approved contact, or you have contacted
    them"; the investigator keeps "you approved contact"."""
    _setup(box)
    t = CATALOGUES[lang]
    for user, key in (("crc", "wb.list.approached.help.coordinator"), ("drsato", "wb.list.approached.help")):
        page = _as(box, user, lang).get("/studies/GZQO/week?list=approached").text
        m = re.search(r'data-testid="list-help">([^<]+)</span>', page)
        assert m and html.unescape(m.group(1)) == t[key], (user, m and m.group(1))
    assert t["wb.list.approached.help.coordinator"] != t["wb.list.approached.help"]


# ------------------------------------------------------------------------------------------- UX-026 access keys
def test_mark_bar_has_unique_access_keys_for_approach_and_need_info(box: dict[str, Any]) -> None:  # noqa: F811
    """UX-026 (the rest after T-684's skip link): A for Approach, I for Need info, once per page, named in the
    title."""
    _setup(box)
    c = _as(box, "drsato", "ja")
    for path in (f"/studies/GZQO/week?pid={B}", f"/studies/GZQO/patients/{B}"):
        page = c.get(path).text
        keys = re.findall(r'accesskey="([a-z])"', page)
        assert sorted(keys) == ["a", "i"], (path, keys)
        s = B[:8]
        assert re.search(rf'accesskey="a" title="アクセスキー：A" data-testid="approach-{s}"', page), path
        assert re.search(rf'accesskey="i" title="アクセスキー：I" data-testid="need_info-{s}"', page), path


# ------------------------------------------------------------------------------------------- UX-027 table headers
def test_no_template_has_an_empty_table_header() -> None:
    """UX-027 (axe ``empty-table-header``): an action or bar column has screen-reader text."""
    empty = []
    for p in sorted(TPL.glob("*.html")):
        text = p.read_text(encoding="utf-8")
        empty += [f"{p.name}: {m}" for m in re.findall(r"<th[^>]*>\s*</th>", text)]
    assert empty == []
    feas = (TPL / "feasibility.html").read_text(encoding="utf-8")
    assert '<th class="barcol"><span class="sr">{{ t(\'col.bar\') }}</span></th>' in feas


# ------------------------------------------------------------------------------------------- UX-038 date format
def test_every_date_field_shows_its_format() -> None:
    """UX-038: a native date field follows the browser's locale; the expected format stands beside every one."""
    missing = []
    for p in sorted(TPL.glob("*.html")):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r'type="date"[^>]*>', text):
            after = text[m.end() : m.end() + 200]
            if "datefmt" not in after:
                missing.append(f"{p.name}:{text[: m.start()].count(chr(10)) + 1}")
    assert missing == []
    assert CATALOGUES["en"]["date.fmt"] == "YYYY-MM-DD"
    assert "西暦" in CATALOGUES["ja"]["date.fmt"] and "西元" in CATALOGUES["zh-TW"]["date.fmt"]  # UX-039: western


@pytest.mark.parametrize("lang", LANGS)
def test_a_page_with_a_date_field_shows_the_format(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    _setup(box)
    page = _as(box, "drsato", lang).get(f"/studies/GZQO/patients/{B}").text
    assert f'<span class="hint datefmt">{html.escape(CATALOGUES[lang]["date.fmt"])}</span>' in page


# ------------------------------------------------------------------------------------------- UX-036 short code
def test_candidate_page_shows_the_short_code_and_folds_the_full_one(box: dict[str, Any]) -> None:  # noqa: F811
    """UX-036: the 8-character code as everywhere; the full pseudonym folded, in a read-only field to copy."""
    _setup(box)
    page = _as(box, "drsato", "en").get(f"/studies/GZQO/candidates/{B}?purpose=referral").text
    assert f'<span class="mono" data-testid="pid">{B[:8]}</span>' in page
    full = page.split('data-testid="pid-full"')[1].split("</details>")[0]
    assert "Full pseudonym (to copy)" in full and f'readonly value="{B}"' in full


# ------------------------------------------------------------------------------------------- UX-030 EDC code
def _env(lang: str) -> Environment:
    env = Environment(loader=FileSystemLoader(str(TPL)), autoescape=True)
    cat = CATALOGUES[lang]

    def t(key: str, **values: object) -> str:
        return cat[key].format(**values) if key in cat else key

    env.globals.update(t=t, t_or=cat.get)
    return env


@pytest.mark.parametrize("lang", LANGS)
def test_edc_error_code_only_under_technical_details(lang: str) -> None:
    """UX-030: the sentence first; the code is folded under "Technical details", not beside the sentence."""
    err = {"code": "edc.ack_reference", "fields": [], "problems": []}
    out = _env(lang).get_template("_edc_err.html").render(err=err)
    sentence = out.split("</p>")[0]
    assert "edc.ack_reference" not in sentence
    tech = out.split('data-testid="edc-error-code"')[1].split("</details>")[0]
    assert html.escape(CATALOGUES[lang]["edc.err.details"]) in tech and "edc.ack_reference" in tech
    gone = _env(lang).get_template("_edc_err.html").render(err={"code": "unavailable", "fields": [], "problems": []})
    assert "edc-error-code" not in gone


# ------------------------------------------------------------------------------------------- UX-033 registry
@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
def test_registry_names_the_redcap_link_in_words(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    """UX-033 (the rest after T-684's words): a row last changed by the REDCap link names it in the reader's
    language, not as ``rc-bridge``; its time is in the site's time."""
    _setup(box)
    pid = "ef" * 16
    box["backend"].registry[("GZQO", pid)] = RegistryEntry(
        ruleset="GZQO", pid=pid, status="consented", reason=None, updated_at=_T0, updated_by="rc-bridge",
        source="manual", source_job=None, tier=None, events=1,
    )  # fmt: skip
    main = _main(_as(box, "crc", lang).get("/pilot/registry/GZQO").text)
    assert "rc-bridge" not in main and html.escape(CATALOGUES[lang]["who.rc-bridge"]) in main
    assert "2026-10-25 17:00" in main  # 09:00 UTC in Asia/Taipei


# ------------------------------------------------------------------------------------------- UX-031 one line each
def test_not_matched_list_has_one_line_per_patient_and_criterion(box: dict[str, Any]) -> None:  # noqa: F811
    """UX-031: a run's own rule came once per action, so one reason stood five to seven times; now once. A criterion
    listed twice from the same source is one line with the evidence and the record counts added."""
    _setup(box)
    job = next(iter(box["backend"].jobs.values()))
    doc = {
        "ruleset": "GZQO", "version": "1.0.0", "run_date": "2026-10-05", "snapshot": "2026-10-04",
        "rows": [
            {"pid": "f" * 32, "criteria": [], "actions": [
                "contact: deny (FHIR Consent) — never listed", "contact: no research-contact consent",
                "contact: deny (opt-out register)", "contact: deny (FHIR Consent) — expired",
                "contact: deny (FHIR Consent) — scope"]},
            {"pid": "d" * 32, "actions": [], "criteria": [
                {"id": "GZQO-EXC-01", "source": "coded", "reason": "coded", "resource_refs": ["c-1"]},
                {"id": "GZQO-EXC-01", "source": "coded", "reason": "coded", "resource_refs": ["c-2", "c-3"]},
                {"id": "GZQO-EXC-01", "source": "notes", "reason": "note", "quote": "synthetic note",
                 "resource_refs": ["DocumentReference/d1"]}]},
        ],
    }  # fmt: skip
    data = json.dumps(doc).encode()
    key = f"outputs/{job.job_id}/excluded_GZQO_v1.0.0.json"
    box["backend"].objects[key] = data
    out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key, recipients=[],
                    tag="phi")  # fmt: skip
    box["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})
    c = _as(box, "drsato", "en")
    for path in ("/studies/GZQO/not-matched", "/studies/GZQO/not-matched?src=rule"):
        page = c.get(path).text
        assert 'data-testid="ex-ffffffff"' in page and 'data-testid="ex-ffffffff-2"' not in page, path
        assert page.count(html.escape(CATALOGUES["en"]["ex.rule.consent"])) == 1, path
    page = c.get("/studies/GZQO/not-matched").text
    assert 'data-testid="ex-dddddddd-2"' in page and 'data-testid="ex-dddddddd-3"' not in page  # coded + notes
    assert html.escape(CATALOGUES["en"]["ex.records"].format(n=3)) in page
