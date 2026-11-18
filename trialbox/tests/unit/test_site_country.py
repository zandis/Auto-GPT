"""10K-1: the set-up wizards' defaults follow the site's country, and SS-MIX2 is a source in both.

The settings wizard (``tools.settings_wizard``) asks the country first and takes every later default from one table
(``tb_common.site_country.TABLE``); the box's plan (``tools.box.plan``) reads the same table. An answers file without
a country, and the plan of a box whose answers have none, read exactly as before: three answers files are compared
with the settings the wizard on master wrote for them (``tests/fixtures/onboarding/legacy_settings.json``).
All data is synthetic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.sources.ssmix2.source import ORDER_KEYS, Ssmix2Source
from tb_common import site_country
from tb_common.box_answers import SourceKind, parse
from tb_common.config import load_settings
from tb_common.retention import DEFAULTS, OVERRIDABLE

from tools import settings_wizard
from tools.box import plan as bp
from tools.ssmix2_export import hard_cases

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "onboarding"
# a site's answers with nothing the country decides: no zone, language, source, mapping or retention
SITE: dict[str, Any] = {
    "site_id": "DEMO-K", "site_name": "Demo K (synthetic)", "internal_domains": ["hospk.test"],
    "senders": ["crc@hospk.test"], "physicians": ["pi@hospk.test"], "reviewers": ["crc@hospk.test"],
    "llm_mode": "stub", "chartno_rule": "digits:8", "mrn_regex": r"^\d{8}$", "mta_authserv_id": "mx.hospk.test",
    "console_url": "https://trialbox.hospk.test", "tls_hostname": "trialbox.hospk.test", "tls_mode": "internal",
    "sae_office_mailbox": "trial-office@hospk.test",
}  # fmt: skip
DAYS = {"logs_days": "400", "mail_log_days": "2200", "outputs_days": "300", "attachments_days": "60"}


def _build(**over: Any) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    return settings_wizard.build({**SITE, **over})


# ------------------------------------------------------------------------------------- the table, one country each
def test_japan_gives_japanese_reports_japans_zone_and_retention_and_an_ssmix2_source() -> None:
    s, env, _ = _build(country="jp")
    assert s["site"]["locale"] == "ja" and s["site"]["tz"] == "Asia/Tokyo" and env["TB_TZ"] == "Asia/Tokyo"
    assert s["retention"] == DEFAULTS["jp"] and s["retention"]["mail_log_days"] == 5 * 365
    assert s["data_source"]["type"] == "ssmix2"
    assert s["data_source"]["mapping"] == "mapping/jp_core/ssmix2_site.yaml"
    assert s["twpas"] == {"enabled": False, "dry_run": True}
    with pytest.raises(settings_wizard.WizardError, match="TWPAS is Taiwan's"):
        _build(country="jp", twpas_enabled="yes", twpas_org_id="0123456789")


def test_taiwan_gives_the_defaults_the_wizard_always_had() -> None:
    s, env, _ = _build(country="tw")
    assert s["site"]["locale"] == "zh-TW" and s["site"]["tz"] == "Asia/Taipei" and env["TB_TZ"] == "Asia/Taipei"
    assert s["retention"] == DEFAULTS["tw"] and s["retention"]["mail_log_days"] == 7 * 365
    assert s["data_source"]["type"] == "csv" and s["data_source"]["mapping"] == "mapping/tw_core/demo_his.yaml"
    s, _, _ = _build(country="tw", twpas_enabled="yes", twpas_org_id="0123456789")
    assert s["twpas"]["enabled"] and s["twpas"]["org_id"] == "0123456789"


def test_the_united_states_gives_english_reports_and_asks_what_the_repository_does_not_hold() -> None:
    with pytest.raises(settings_wizard.WizardError) as exc:
        _build(country="us")
    for what in ("tz is required", "mapping is required", "data_source_type is required", "no retention rules"):
        assert what in str(exc.value), what
    assert "locale" not in str(exc.value)  # English is the United States' report language
    # a shipped template states Taiwan's zone: the zone check refuses it, as for every source
    with pytest.raises(settings_wizard.WizardError, match="differs from the mapping's tz"):
        _build(country="us", tz="America/New_York", data_source_type="csv",
               mapping="mapping/templates/csv_site.yaml", **DAYS)  # fmt: skip


def test_the_united_states_with_its_own_answers_builds_with_the_sites_own_retention(tmp_path: Path) -> None:
    mapping = tmp_path / "mapping" / "us_site.yaml"
    mapping.parent.mkdir()
    mapping.write_text("version: 1\nname: us_site\nextends: ../tw_core/demo_his.yaml\ntz: America/Chicago\n")
    s, env, _ = settings_wizard.build(
        {**SITE, "country": "us", "tz": "America/Chicago", "data_source_type": "csv", "mapping": "us_site.yaml",
         **DAYS}, [tmp_path / "mapping"]
    )  # fmt: skip
    assert s["site"]["locale"] == "en" and s["site"]["tz"] == "America/Chicago" and env["TB_TZ"] == "America/Chicago"
    assert {k: s["retention"][k] for k in OVERRIDABLE} == {k: int(v) for k, v in DAYS.items()}
    with pytest.raises(settings_wizard.WizardError, match="give attachments_days"):
        settings_wizard.build(
            {**SITE, "country": "us", "tz": "America/Chicago", "data_source_type": "csv", "mapping": "us_site.yaml",
             **{k: v for k, v in DAYS.items() if k != "attachments_days"}}, [tmp_path / "mapping"]
        )  # fmt: skip
    # a site may still choose one of the two rule sets the repository holds
    s, _, _ = settings_wizard.build(
        {**SITE, "country": "us", "tz": "America/Chicago", "data_source_type": "csv", "mapping": "us_site.yaml",
         "retention_rules": "tw"}, [tmp_path / "mapping"]
    )  # fmt: skip
    assert s["retention"] == DEFAULTS["tw"]


def test_another_country_assumes_nothing() -> None:
    with pytest.raises(settings_wizard.WizardError) as exc:
        _build(country="other")
    for what in ("tz is required", "mapping is required", "data_source_type is required", "locale is required",
                 "no retention rules"):  # fmt: skip
        assert what in str(exc.value), what
    with pytest.raises(settings_wizard.WizardError, match="country 'xx'"):
        _build(country="xx")


def test_the_table_is_the_one_place_and_takes_its_zones_from_the_shipped_mappings() -> None:
    assert tuple(site_country.TABLE) == site_country.COUNTRIES
    for c, cd in site_country.TABLE.items():
        if cd.mapping:
            text = yaml.safe_load((site_country.MAPPING_ROOT / cd.mapping).read_text(encoding="utf-8"))
            assert cd.tz == text["tz"], c
        if cd.retention_rules:
            assert cd.retention_rules in DEFAULTS, c
    assert site_country.SSMIX2_ORDER_NUMBERS == ORDER_KEYS  # the reader's keys (D-594)
    assert set(site_country.QUESTION) == {"en", "ja", "zh-TW"}


# ---------------------------------------------------------------------------------------- the interactive wizard
def _interactive(country: str, replies: dict[str, str] | None = None) -> tuple[dict[str, Any], list[str]]:
    asked: list[str] = []

    def prompt(q: str) -> str:
        asked.append(q)
        if q.startswith("Country"):
            return country
        return next((v for k, v in (replies or {}).items() if q.startswith(k)), "")

    return settings_wizard.ask({}, prompt=prompt), asked


def test_the_country_is_the_first_question_and_the_defaults_shown_follow_it() -> None:
    jp, asked = _interactive("jp", {"HIS source type": ""})
    assert asked[0].startswith("Country")
    assert (jp["locale"], jp["tz"], jp["data_source_type"], jp["mapping"], jp["retention_rules"]) == (
        "ja", "Asia/Tokyo", "ssmix2", "mapping/jp_core/ssmix2_site.yaml", "jp"
    )  # fmt: skip
    assert any(q.startswith("SS-MIX2 order numbers") for q in asked) and jp["ssmix2_order_numbers"] == "unique"
    assert not any("TWPAS" in q or "NHI" in q for q in asked)  # Taiwan's insurer: not asked in Japan
    assert not any(q.startswith(("Days to keep job outputs", "Days to keep inbound")) for q in asked)
    tw, asked = _interactive("tw")
    assert (tw["locale"], tw["tz"], tw["data_source_type"]) == ("zh-TW", "Asia/Taipei", "csv")
    assert any("TWPAS" in q for q in asked) and not any(q.startswith("SS-MIX2") for q in asked)
    other, asked = _interactive("other")
    assert other["locale"] == "" and other["tz"] == "" and other["mapping"] == ""
    assert any("[no default for this country: please answer]" in q for q in asked if q.startswith("Report"))
    assert any(q.startswith("Days to keep job outputs") for q in asked)  # no rules here: the days are asked


def test_enter_at_the_country_question_is_not_an_answer() -> None:
    with pytest.raises(settings_wizard.WizardError, match="country: one of jp, tw, us, other"):
        settings_wizard.ask({}, prompt=lambda _q: "")


# ------------------------------------------------------------------------------------------------ SS-MIX2, end to end
def test_ssmix2_chosen_reaches_the_written_settings_and_the_reader_reads_the_folder(tmp_path: Path) -> None:
    storage = tmp_path / "ssmix2"
    hard_cases(storage)  # a synthetic SS-MIX2 standardized storage
    answers = tmp_path / "site.yaml"
    answers.write_text(yaml.safe_dump({**SITE, "country": "jp", "data_source_host_dir": str(storage),
                                       "ssmix2_order_numbers": "per_day"}), encoding="utf-8")  # fmt: skip
    out, env_out = tmp_path / "settings.yaml", tmp_path / ".env"
    assert settings_wizard.main(["--answers", str(answers), "--out", str(out), "--env-out", str(env_out)]) == 0
    s = load_settings(out)  # the services' own validation
    assert s.data_source.type == "ssmix2" and s.data_source.path == "/data/source/site"
    assert s.data_source.mapping == "mapping/jp_core/ssmix2_site.yaml"
    env = dict(ln.split("=", 1) for ln in env_out.read_text(encoding="utf-8").splitlines() if "=" in ln)
    assert env["TB_SOURCE_DIR"] == str(storage) and env["TB_SOURCE_MOUNT"] == "/data/source/site"
    assert env["TB_SSMIX2_ORDER_NUMBERS"] == "per_day"
    compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert (
        "${TB_SOURCE_DIR:-../tests/fixtures/synthetic_patients/site-a}:${TB_SOURCE_MOUNT:-/data/source/site-a}:ro"
        in compose
    )
    # what the adapter is given: the folder the settings name (mounted from TB_SOURCE_DIR) and the order key
    src = Ssmix2Source(Path(env["TB_SOURCE_DIR"]), licensed={}, order_key=env["TB_SSMIX2_ORDER_NUMBERS"])
    assert {r["mrn"] for r in src.rows("patient", "patient", None, None)} >= {"99000001", "99000007"}


def test_ssmix2_answers_get_the_checks_the_other_sources_get() -> None:
    with pytest.raises(settings_wizard.WizardError, match="ssmix2_order_numbers must be unique or per_day"):
        _build(country="jp", ssmix2_order_numbers="sometimes")
    with pytest.raises(settings_wizard.WizardError, match="data_source_type must be one of"):
        _build(country="jp", data_source_type="hl7v2")
    with pytest.raises(settings_wizard.WizardError, match="differs from the mapping's tz"):
        _build(country="jp", tz="Asia/Taipei")  # the Japanese mapping states Japan's zone
    _, _, warnings = _build(country="jp")
    assert any("SS-MIX2 storage's root folder" in w for w in warnings)


# -------------------------------------------------------------------------------- old answers files and boxes
@pytest.mark.parametrize("name", ["site_c_answers.yaml", "legacy_ja_answers.yaml", "legacy_minimal_answers.yaml"])
def test_an_answers_file_without_a_country_reads_exactly_as_before(name: str) -> None:
    """The rule: no ``country`` key, no table. The report language is ``locale`` else zh-TW; retention is
    ``retention_rules`` else from the report language (ja -> jp, else tw); the source and mapping are the file's,
    else csv and the Taiwan mapping; TWPAS is asked. legacy_settings.json is what the wizard on master wrote."""
    a = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
    assert "country" not in a
    s, env, _ = settings_wizard.build(a, [FIXTURES / "mapping"])
    want = json.loads((FIXTURES / "legacy_settings.json").read_text(encoding="utf-8"))[name]
    got = {"site": s["site"], "data_source": s["data_source"], "retention": s["retention"], "twpas": s["twpas"],
           "env": {k: env.get(k) for k in want["env"]}}  # fmt: skip
    assert got == want


OWNER: dict[str, Any] = {
    "site_name": "Demo box (synthetic)", "tz": "Asia/Tokyo", "language": "ja",
    "owner": {"full_name": "Dr Owner", "username": "owner", "email": "owner@hospa.test"},
    "box_name": "trialbox", "backup": {"kind": "later"}, "source": "spreadsheet",
}  # fmt: skip
HW = bp.Hardware(arch="x86_64", cpu_count=32, ram_gib=128.0, disk_free_gib=1800.0, tpm=True, lan="192.0.2.0/24",
                 hostname="box1", host_tz="Asia/Tokyo")  # fmt: skip


def _box(tmp_path: Path, **over: Any) -> tuple[bp.BoxPlan, dict[str, Any], dict[str, str]]:
    a, problems = parse(OWNER | over)
    assert a is not None, problems
    p = bp.plan(a, HW)
    for rel, text in p.files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    s, env, _ = settings_wizard.build(json.loads(json.dumps(p.wizard_answers)), [tmp_path / "site" / "mapping"])
    return p, s, env


def test_a_box_without_a_country_is_planned_as_before(tmp_path: Path) -> None:
    p, s, _ = _box(tmp_path)
    assert "country" not in p.wizard_answers and p.wizard_answers["mapping"] == bp.BOX_MAPPING
    assert p.wizard_answers["retention_rules"] == "jp"  # from the zone, as before (D-138)
    assert p.files[f"site/{bp.BOX_MAPPING}"] == bp.mapping_text("Asia/Tokyo")
    assert s["data_source"]["type"] == "csv" and s["site"]["locale"] == "ja"


def test_a_japanese_box_with_ssmix2_is_planned_from_the_table(tmp_path: Path) -> None:
    p, s, env = _box(tmp_path, country="jp", source="ssmix2", ssmix2_root="/mnt/ssmix2")
    # the shipped JP mapping by name (it extends the shared one; the loader takes one level), no site file for it
    assert s["data_source"]["type"] == "ssmix2" and s["data_source"]["mapping"] == "mapping/jp_core/ssmix2_site.yaml"
    assert set(p.files) == {"site/hardening.conf"}
    assert env["TB_SOURCE_DIR"] == "/mnt/ssmix2" and env["TB_SSMIX2_ORDER_NUMBERS"] == "unique"
    assert s["retention"] == DEFAULTS["jp"] and s["site"]["locale"] == "ja"
    assert not any("T-731" in w and "ssmix2" in w for w in p.warnings)  # SS-MIX2 is no longer "set up later"


def test_a_box_in_the_united_states_takes_the_owners_retention_days(tmp_path: Path) -> None:
    a, problems = parse(OWNER | {"country": "us", "tz": "America/Chicago", "language": "en"})
    assert a is None and {p.field for p in problems} == set(OVERRIDABLE)
    p, s, _ = _box(tmp_path, country="us", tz="America/Chicago", language="en", **DAYS)
    assert {k: s["retention"][k] for k in OVERRIDABLE} == {k: int(v) for k, v in DAYS.items()}
    assert any("ships no mapping" in w for w in p.warnings)


def test_the_box_answers_refuse_what_the_reader_cannot_use() -> None:
    jp = {"country": "jp", "source": "ssmix2"}
    for over, field in (
        (jp, "ssmix2_root"),
        (jp | {"ssmix2_root": "relative/path"}, "ssmix2_root"),
        (jp | {"ssmix2_root": "/mnt/a b"}, "ssmix2_root"),
        (jp | {"ssmix2_root": "/mnt/../etc"}, "ssmix2_root"),
        (jp | {"ssmix2_root": "/mnt/s", "ssmix2_order_numbers": "x"}, "ssmix2_order_numbers"),
        ({"country": "fr"}, "country"),
        # review of #1088, items 1, 2 and 5: SS-MIX2 only where a shipped mapping reads it; Japan's one zone;
        # retention days bounded
        ({"source": "ssmix2", "ssmix2_root": "/mnt/s"}, "source"),
        ({"country": "tw", "source": "ssmix2", "ssmix2_root": "/mnt/s"}, "source"),
        (jp | {"ssmix2_root": "/mnt/s", "tz": "Asia/Taipei"}, "tz"),
        ({"country": "us", "tz": "America/Chicago"} | DAYS | {"logs_days": "36501"}, "logs_days"),
    ):
        a, problems = parse(OWNER | over)
        assert a is None and field in {p.field for p in problems}, over
    assert SourceKind.SSMIX2.value == "ssmix2"


@pytest.mark.parametrize("country", ["", *site_country.COUNTRIES])
@pytest.mark.parametrize("source", [k.value for k in SourceKind])
def test_every_planned_box_mapping_loads(country: str, source: str, tmp_path: Path) -> None:
    """Review of #1088, item 1: the mapping a box is planned with is loaded with the adapter's own loader (a base
    mapping cannot extend another one), for every country and source the box answers allow."""
    from adapter.mapping.engine import Mapping

    from tools.settings_wizard import find_mapping

    tz = site_country.defaults(country).tz or "Asia/Tokyo"
    over: dict[str, Any] = {"country": country, "tz": tz, "source": source}
    if source == "ssmix2":
        over["ssmix2_root"] = "/mnt/ssmix2"
    if country and not site_country.defaults(country).retention_rules:
        over |= DAYS
    a, problems = parse(OWNER | over)
    if a is None:  # a source the country does not offer: refused, so never planned
        assert source == "ssmix2" and {p.field for p in problems} == {"source"}, problems
        return
    p, s, _ = _box(tmp_path, **over)
    path = find_mapping(s["data_source"]["mapping"], [tmp_path / "site" / "mapping"])
    Mapping.load(path)
