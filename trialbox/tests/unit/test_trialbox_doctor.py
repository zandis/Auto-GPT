"""``trialbox doctor`` for v4 (spec v4 §18.1; S1-16).

Done-when: doctor fails closed on a D3/D4 route outside the perimeter, a non-Secure cookie in PRODUCTION, or D3 data in DEV.
Also: gateway-only model reach from ``deploy/egress.py``, channel engine and fallback, publish-gate state, and a
check that cannot run counts as a failure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import doctor
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "ab" * 32


def status(checks: list[doctor.Check], name: str) -> doctor.Check:
    return next(c for c in checks if c.name == name)


def inputs(**kw: Any) -> doctor.DoctorInputs:
    env = kw.pop("env", {"TB_ENV": "DEV", "TB_TOPOLOGY": "A", "TB_TZ": "Asia/Taipei"})
    kw.setdefault("host_tz", "Asia/Taipei")  # never the test machine's own zone
    return doctor.DoctorInputs(env=env, **kw)


@pytest.mark.req("S1-16", "OPS-02")
def test_default_install_passes() -> None:
    checks = doctor.run(inputs())
    assert doctor.ok(checks), doctor.render(checks)
    assert status(checks, "channel_engine").status == "PASS"
    assert status(checks, "secure_cookie").status == "WARN"  # DEV may serve http on localhost
    assert {c.name for c in checks} == {
        "topology",
        "env_class_ceiling",
        "routing_perimeter",
        "gateway_only_model_reach",
        "perimeter_addresses",
        "channel_engine",
        "secure_cookie",
        "console_mfa",
        "ldap_ca",  # D-722
        "publish_gate",
        "note_block",
        "judge_route",
        "registry_pins",
        "site_tz",
        "backup",
        "flags",
        "restore_hold",
        "site_key",
        "chartno_rule",  # D-621
        "key_custody",
        "key_ceremony",  # D-893
        "db_passwords",
        "clock",
        "ops_runner",
        "audit_heads",
        "anchor_mount",  # D-638
        "rehearsal",  # D-726
        "sae_mailbox",  # D-736
        "mail_auth",  # D-825
        "memory_caps",
        "postgres_memory",  # D-751
        "wsl2_memory",
        "update_window",
        "wsl2_versions",
        "backup_speed",
    }


@pytest.mark.req("S1-16", "PRIV-15", "LLM-4")
@pytest.mark.parametrize(("cls", "endpoint"), [("D3", "external_x"), ("D4", "openrouter"), ("D3", "openrouter")])
def test_fails_closed_on_d3_d4_route_outside_the_perimeter(tmp_path: Path, cls: str, endpoint: str) -> None:
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    alias = "x-external" if endpoint == "external_x" else "j-workhorse"
    doc["routes"].insert(
        0,
        {
            "id": "rogue",
            "roles": ["judge"],
            "classes": [cls],
            "topologies": ["A", "B", "C"],
            "environments": ["DEV", "TEST", "VALIDATION", "PRODUCTION"],
            "builds": [f"{alias}@{endpoint}"],
        },
    )
    rogue = tmp_path / "routing.yaml"
    rogue.write_text(yaml.safe_dump(doc), encoding="utf-8")
    checks = doctor.run(inputs(routing_path=rogue))
    c = status(checks, "routing_perimeter")
    assert c.status == "FAIL" and "outside the perimeter" in c.detail and "rogue" in c.detail
    assert not doctor.ok(checks)
    assert cli(["doctor", "--routing", str(rogue)]) == 1


@pytest.mark.req("S1-16")
@pytest.mark.parametrize(
    ("env", "want"), [("DEV", "WARN"), ("TEST", "WARN"), ("VALIDATION", "FAIL"), ("PRODUCTION", "FAIL")]
)
def test_secure_cookie_is_required_in_production(env: str, want: str) -> None:
    off = doctor.run(inputs(env={"TB_ENV": env, "TB_TOPOLOGY": "A", "TB_CONSOLE_SECURE_COOKIE": "0"}))
    assert status(off, "secure_cookie").status == want
    on = doctor.run(inputs(env={"TB_ENV": env, "TB_TOPOLOGY": "A", "TB_CONSOLE_SECURE_COOKIE": "1"}))
    assert status(on, "secure_cookie").status == "PASS"


@pytest.mark.req("S1-16")
@pytest.mark.parametrize(
    ("env", "value", "want"),
    [
        ("PRODUCTION", None, "PASS"),  # unset: the console makes the cookie Secure in PRODUCTION (D-192)
        ("PRODUCTION", "", "PASS"),  # the base compose file passes it empty
        ("PRODUCTION", "0", "FAIL"),  # an explicit off stays a FAIL (and the console refuses to start)
        ("PRODUCTION", "1", "PASS"),
        ("VALIDATION", None, "FAIL"),  # the console's default is Secure only in PRODUCTION
        ("VALIDATION", "", "FAIL"),
        ("TEST", "", "WARN"),
        ("DEV", None, "WARN"),
    ],
)
def test_secure_cookie_follows_the_console_default(env: str, value: str | None, want: str) -> None:
    from console.identity import IdentityConfigError, secure_cookie_default

    e = {"TB_ENV": env, "TB_TOPOLOGY": "A", **({} if value is None else {"TB_CONSOLE_SECURE_COOKIE": value})}
    assert status(doctor.run(inputs(env=e)), "secure_cookie").status == want
    try:  # the doctor and the console agree on what the console will do
        console_secure = secure_cookie_default(e, env)
    except IdentityConfigError:
        console_secure = False
    assert console_secure == (want == "PASS")


@pytest.mark.req("S1-16")
def test_hermes_engine_is_refused_with_its_removal_named() -> None:
    c = status(doctor.run(inputs(settings={"channels": {"engine": "hermes"}})), "channel_engine")
    assert c.status == "FAIL" and "D-121" in c.detail


@pytest.mark.req("S1-16", "ENG-16", "ENG-09")
def test_fails_closed_on_d3_data_in_dev() -> None:
    store = doctor.run(inputs(settings={"data_stores": [{"name": "research_db", "data_class": "D3"}]}))
    c = status(store, "env_class_ceiling")
    assert c.status == "FAIL" and "D3 data in DEV" in c.detail and not doctor.ok(store)
    env = doctor.run(inputs(env={"TB_ENV": "DEV", "TB_DATA_CLASS": "D3"}))
    assert status(env, "env_class_ceiling").status == "FAIL"
    test_env = doctor.run(inputs(env={"TB_ENV": "TEST"}, settings={"data_stores": [{"name": "x", "data_class": "D1"}]}))
    assert status(test_env, "env_class_ceiling").status == "FAIL"
    unknown = doctor.run(inputs(settings={"data_stores": [{"name": "x"}]}))
    assert status(unknown, "env_class_ceiling").status == "FAIL"
    prod = doctor.run(
        inputs(env={"TB_ENV": "PRODUCTION"}, settings={"data_stores": [{"name": "research_db", "data_class": "D3"}]})
    )
    assert status(prod, "env_class_ceiling").status == "PASS"


@pytest.mark.req("S1-16", "NFR-B9")
def test_gateway_only_model_reach() -> None:
    leak = doctor.run(inputs(env={"TB_ENV": "DEV", "EGRESS_EXTRA": "orchestrator=openrouter.ai:443"}))
    c = status(leak, "gateway_only_model_reach")
    assert c.status == "FAIL" and "only gateway may" in c.detail
    ok = doctor.run(inputs(env={"TB_ENV": "DEV", "EGRESS_EXTRA": "orchestrator=nhi.example.test:443"}))
    assert status(ok, "gateway_only_model_reach").status == "PASS"


@pytest.mark.req("S1-16")
def test_channel_engine_and_topology_checks() -> None:
    bad = doctor.run(inputs(settings={"channels": {"engine": "slack"}}))
    assert status(bad, "channel_engine").status == "FAIL"
    topo = doctor.run(inputs(env={"TB_ENV": "DEV", "TB_TOPOLOGY": "Z"}))
    assert status(topo, "topology").status == "FAIL"


@pytest.mark.req("S1-16", "DP-25")
def test_publish_gate_state(tmp_path: Path) -> None:
    """T-659b: the adapter's lake, its CURRENT and its one gate record per night."""
    lake = tmp_path / "lake"
    (lake / "gates").mkdir(parents=True)
    none = doctor.run(inputs(ingest_lake=lake))
    assert status(none, "publish_gate").status == "FAIL"  # nothing ever published
    (lake / "CURRENT").write_text("2026-10-04", encoding="utf-8")
    (lake / "gates" / "2026-10-04.json").write_text(json.dumps({"outcome": "PUBLISH"}), encoding="utf-8")
    assert status(doctor.run(inputs(ingest_lake=lake)), "publish_gate").status == "PASS"
    (lake / "gates" / "2026-10-05.json").write_text(
        json.dumps({"outcome": "HOLD", "blocking_reasons": ["RECON_ROW_COUNT"]}), encoding="utf-8"
    )
    held = status(doctor.run(inputs(ingest_lake=lake)), "publish_gate")
    assert held.status == "WARN" and "RECON_ROW_COUNT" in held.detail and "2026-10-04" in held.detail


@pytest.mark.req("S1-16")
def test_note_block_without_a_verifier_warns_in_test_and_fails_in_production() -> None:
    base = {"TB_TOPOLOGY": "A", "TB_GATEWAY_URL": "http://tb-gateway:8000"}
    warn = status(doctor.run(inputs(env={**base, "TB_ENV": "TEST"})), "note_block")
    assert warn.status == "WARN" and "never-exclude" in warn.detail
    fail = status(doctor.run(inputs(env={**base, "TB_ENV": "PRODUCTION"})), "note_block")
    assert fail.status == "FAIL"
    single = status(
        doctor.run(
            inputs(env={**base, "TB_ENV": "PRODUCTION", "TB_GATEWAY_VERIFIER_MODEL": "v", "TB_SCREEN_JUDGE": "single"})
        ),
        "note_block",
    )
    assert single.status == "FAIL" and "single" in single.detail
    ok = status(
        doctor.run(inputs(env={**base, "TB_ENV": "PRODUCTION", "TB_GATEWAY_VERIFIER_MODEL": "v"})), "note_block"
    )
    assert ok.status == "PASS"
    never = status(doctor.run(inputs(env={**base, "TB_ENV": "PRODUCTION", "TB_NOTE_BLOCK": "never"})), "note_block")
    assert never.status == "PASS"
    bad = status(doctor.run(inputs(env={**base, "TB_ENV": "DEV", "TB_NOTE_BLOCK": "sometimes"})), "note_block")
    assert bad.status == "FAIL"


def test_a_check_that_cannot_run_fails(tmp_path: Path) -> None:
    checks = doctor.run(inputs(routing_path=tmp_path / "missing.yaml"))
    assert status(checks, "routing_perimeter").status == "FAIL" and not doctor.ok(checks)


@pytest.mark.req("S1-16")
def test_check_host_runs_doctor() -> None:
    text = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    assert "tools.trialbox doctor" in text


# ------------------------------------------------------------------------------------------------ site_tz (D-315)
JP_MAPPING = {"mapping": "mapping/jp_core/ssmix2_site.yaml"}
JP_SETTINGS = {"site": {"id": "JP-A", "tz": "Asia/Tokyo"}, "data_source": JP_MAPPING}


@pytest.mark.req("OPS-02")
def test_site_tz_passes_when_settings_env_mapping_and_host_agree() -> None:
    env = {"TB_ENV": "DEV", "TB_TOPOLOGY": "A", "TB_TZ": "Asia/Tokyo"}
    c = status(doctor.run(inputs(env=env, settings=JP_SETTINGS, host_tz="Japan")), "site_tz")
    assert c.status == "PASS" and c.detail.startswith("Asia/Tokyo"), c.detail  # Japan is Asia/Tokyo's alias


@pytest.mark.req("OPS-02")
@pytest.mark.parametrize(
    ("tb_tz", "host", "settings"),
    [
        ("Asia/Taipei", "Asia/Tokyo", JP_SETTINGS),  # TB_TZ left at Taiwan's on a Japan box
        ("Asia/Tokyo", "UTC", JP_SETTINGS),  # a host left on UTC runs the 04:45 backup at 13:45
        ("Asia/Tokyo", "Asia/Tokyo", {**JP_SETTINGS, "site": {"id": "JP-A", "tz": "Asia/Taipei"}}),
        ("Asia/Taipei", "Asia/Taipei", {"site": {"id": "X", "tz": "Asia/Taipei"}, "data_source": JP_MAPPING}),
    ],
)
def test_site_tz_fails_when_any_zone_differs(tb_tz: str, host: str, settings: dict[str, Any]) -> None:
    env = {"TB_ENV": "DEV", "TB_TOPOLOGY": "A", "TB_TZ": tb_tz}
    checks = doctor.run(inputs(env=env, settings=settings, host_tz=host))
    c = status(checks, "site_tz")
    assert c.status == "FAIL" and "differs" in c.detail and not doctor.ok(checks), c.detail


@pytest.mark.req("OPS-02")
def test_site_tz_fails_without_any_zone_or_with_a_wrong_name() -> None:
    none = status(doctor.run(inputs(env={"TB_ENV": "DEV", "TB_TOPOLOGY": "A"})), "site_tz")
    assert none.status == "FAIL" and "no site time zone" in none.detail
    bad = status(doctor.run(inputs(env={"TB_ENV": "DEV", "TB_TOPOLOGY": "A", "TB_TZ": "Asia/Nowhere"})), "site_tz")
    assert bad.status == "FAIL" and "not an IANA time zone" in bad.detail


def test_site_tz_reads_the_host_zone_from_tb_host_tz_inside_a_container() -> None:
    env = {"TB_ENV": "DEV", "TB_TOPOLOGY": "A", "TB_TZ": "Asia/Tokyo", "TB_HOST_TZ": "UTC"}
    c = status(doctor.run(doctor.DoctorInputs(env=env)), "site_tz")
    assert c.status == "FAIL" and "host zone UTC" in c.detail


def _backup_box(tmp_path: Path, env: str) -> tuple[Path, Path]:
    deploy = tmp_path / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    (deploy / ".env").write_text(env)
    cron = tmp_path / "cron.d"
    cron.mkdir(exist_ok=True)
    return deploy, cron


def test_backup_check_fails_in_production_on_a_missing_off_box_target_route_cron_or_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-274 (CR-058, OPS-028, OPS-048): doctor checks the backup age and the off-box target."""
    from datetime import UTC, datetime, timedelta

    from tools.trialbox import backup_schedule as bs

    for k in ("TB_BACKUP_TARGETS", "TB_BACKUP_OFFBOX", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_PG_ARCHIVE_MODE"):
        monkeypatch.delenv(k, raising=False)
    local = tmp_path / "local"
    deploy, cron = _backup_box(tmp_path, f"TB_BACKUP_TARGETS={local}\n")
    prod = {"TB_ENV": "PRODUCTION", "TB_TOPOLOGY": "A", "TB_BACKUP_TARGETS": str(local)}
    c = status(doctor.run(inputs(env=prod, deploy=deploy, cron_dir=cron), (doctor.check_backup,)), "backup")
    assert c.status == "FAIL" and "no off-box backup target" in c.detail and "no alert route" in c.detail
    assert f"no {cron / bs.CRON_NAME}" in c.detail
    dev = status(doctor.run(inputs(env={**prod, "TB_ENV": "DEV"}, deploy=deploy, cron_dir=cron),
                            (doctor.check_backup,)), "backup")  # fmt: skip
    assert dev.status == "WARN"
    # an off-box share, a route, the cron file and a good backup two hours old: PASS, but WARN while archiving is off
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / bs.OFFBOX_MARKER).write_text("")
    good = {**prod, "TB_BACKUP_TARGETS": str(nas), "TB_BACKUP_OFFBOX": str(nas), "TB_BACKUP_MAILTO": "it@x.example"}
    (cron / bs.CRON_NAME).write_text("# installed\n")
    at = datetime.now(UTC) - timedelta(hours=2)
    f = nas / f"trialbox-CGMH-{at.strftime('%Y%m%dT%H%M%SZ')}.tbbak"
    f.write_bytes(b"x")
    bs.sidecar(f).write_text(f"{'a' * 64}  {f.name}\n")
    (deploy / "site").mkdir()
    (deploy / "site" / "backup-last.json").write_text(json.dumps({"ok": True, "good_at": at.isoformat(),
        "good_file": {"name": f.name, "bytes": 1, "sha256": "a" * 64}}))  # fmt: skip
    c = status(doctor.run(inputs(env=good, deploy=deploy, cron_dir=cron), (doctor.check_backup,)), "backup")
    assert c.status == "WARN" and "WAL archiving is off" in c.detail and "1 off-box" in c.detail
    # 40 hours old: too old
    old = datetime.now(UTC) - timedelta(hours=40)
    g = nas / f"trialbox-CGMH-{old.strftime('%Y%m%dT%H%M%SZ')}.tbbak"
    f.rename(g)
    bs.sidecar(f).unlink()
    bs.sidecar(g).write_text(f"{'a' * 64}  {g.name}\n")
    (deploy / "site" / "backup-last.json").write_text(json.dumps({"ok": True, "good_at": old.isoformat(),
        "good_file": {"name": g.name, "bytes": 1, "sha256": "a" * 64}}))  # fmt: skip
    c = status(doctor.run(inputs(env=good, deploy=deploy, cron_dir=cron), (doctor.check_backup,)), "backup")
    assert c.status == "FAIL" and "40 h old" in c.detail
    # the deploy folder comes from --env-file
    assert doctor.inputs_from(env_file=deploy / ".env", settings=None, routing=None, lake=None).deploy == deploy
    nodeploy = status(doctor.run(inputs(env=good), (doctor.check_backup,)), "backup")
    assert nodeploy.status == "FAIL" and "--env-file" in nodeploy.detail


def test_missing_settings_file_is_a_fail_line_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """OPS-016: ``doctor --settings <missing>`` prints a FAIL line and exits 1; the other checks still run."""
    missing = tmp_path / "settings.yaml"
    assert cli(["doctor", "--settings", str(missing)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  inputs" in out and f"settings file {missing} not found" in out
    assert "registry_pins" in out and "Traceback" not in out
    bad = tmp_path / "bad.yaml"
    bad.write_text("site: [unclosed\n", encoding="utf-8")
    inp = doctor.inputs_from(env_file=None, settings=bad, routing=None, lake=None)
    c = status(doctor.run(inp, (doctor.check_channel_engine,)), "inputs")
    assert c.status == "FAIL" and "cannot be read" in c.detail
    listed = tmp_path / "list.yaml"
    listed.write_text("- a\n", encoding="utf-8")
    inp = doctor.inputs_from(env_file=None, settings=listed, routing=None, lake=None)
    assert "is not a mapping" in status(doctor.run(inp, ()), "inputs").detail


def test_registry_pins_and_models_come_from_the_env_file_deploy_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPS-016: the site override and the models folder are read beside ``--env-file``, not from the repository."""
    monkeypatch.delenv("TB_REGISTRY_OVERRIDE", raising=False)
    monkeypatch.delenv("TB_MODELS_DIR", raising=False)
    deploy = tmp_path / "box" / "deploy"
    deploy.mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=DEV\nTB_TOPOLOGY=A\n", encoding="utf-8")
    inp = doctor.inputs_from(env_file=deploy / ".env", settings=None, routing=None, lake=None)
    assert doctor._override(inp) == deploy / "site" / "registry.site.yaml"
    assert doctor._models_root(inp) == deploy / "models"
    c = status(doctor.run(inp, (doctor.check_registry_pins,)), "registry_pins")
    assert c.status == "WARN" and f"no override at {deploy / 'site' / 'registry.site.yaml'}" in c.detail
    (deploy / "site").mkdir()
    (deploy / "site" / "registry.site.yaml").write_text("builds: [unclosed\n", encoding="utf-8")
    c = status(doctor.run(inp, (doctor.check_registry_pins,)), "registry_pins")
    assert c.status == "FAIL" and str(deploy / "site" / "registry.site.yaml") in c.detail
    # without --env-file: the repository's deploy folder, as before
    bare = doctor.inputs_from(env_file=None, settings=None, routing=None, lake=None)
    assert doctor._override(bare) == ROOT / "deploy" / "site" / "registry.site.yaml"
