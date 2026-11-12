"""T-632 (D-382; review OPS-011, OPS-012, OPS-013, OPS-014): site inputs and a finished install.

* The adapter finds the site's own mapping in the site mapping folder (``deploy/site/mapping``, mounted at
  ``/etc/trialbox/mapping``) before the image, and ingests from the feed folder the wizard named. The drill uses the
  box rehearsal's site mapping (``tools/rehearse_box/mapping``), which is not in the image, and a temporary folder
  standing in for the mounted feed.
* The wizard writes the feed folder and TLS settings; the RUNBOOK's answers example works.
* ``install.sh`` turns TLS on, installs both cron files, prints the enrolment code, names the judge from the
  configuration and ends with an ``https://`` URL it checked; a FAIL line ends it with exit 1.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import pin_model, settings_wizard

ROOT = Path(__file__).resolve().parents[2]
REHEARSAL = ROOT / "tools/rehearse_box"
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
ANSWERS_C = ROOT / "tests/fixtures/onboarding/site_c_answers.yaml"
INSTALL = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")


def _compose_adapter() -> dict[str, Any]:
    svc: dict[str, Any] = yaml.safe_load((ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))["services"][
        "adapter"
    ]
    return svc


@pytest.fixture()
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_url: str) -> dict[str, Path]:
    """A site as the box holds it: deploy/site/mapping (a copy of the rehearsal's) and a feed folder."""
    mapping = tmp_path / "deploy/site/mapping"
    shutil.copytree(REHEARSAL / "mapping", mapping)
    feed = tmp_path / "his-export"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.sqlite"))
    answers = yaml.safe_load((REHEARSAL / "site_answers.yaml").read_text(encoding="utf-8"))
    # in the container the feed is mounted at data_source_path; here the folder itself stands in for the mount
    answers.update({"data_source_path": str(feed), "data_source_host_dir": str(feed), "llm_mode": "stub"})
    settings, env, warnings = settings_wizard.build(answers, [mapping])
    # the rehearsal uses Caddy's internal CA on purpose (OPS-060 warns about it); no other TLS warning
    assert not [w for w in warnings if "tls" in w and not w.startswith("tls_mode internal")]
    settings_wizard.write(settings, env, tmp_path / "deploy/settings.yaml", tmp_path / "deploy/.env")
    for k in ("TB_SETTINGS", "TB_SETTINGS_FILE"):
        monkeypatch.setenv(k, str(tmp_path / "deploy/settings.yaml"))
    monkeypatch.setenv("TB_MAPPING_DIR", str(mapping))
    monkeypatch.setenv("TB_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("TB_SECRETS_DIR", str(tmp_path / "secrets"))
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("TB_ADAPTER_LAKE", "local")
    monkeypatch.setenv("TB_LAKE_EMBEDDER", "hash")
    return {"tmp": tmp_path, "mapping": mapping, "feed": feed, "env": tmp_path / "deploy/.env"}


# ---------------------------------------------------------------------------------- acceptance: mapping and feed


def test_the_adapter_ingests_from_the_mounted_feed_with_a_mapping_not_in_the_image(
    site: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from adapter import cli

    name = "mapping/tw_core/rehearsal_a.yaml"
    assert not (ROOT / "services/adapter" / name).exists()  # the site's mapping is not in the image
    ac, kind, path = cli.build_config()
    assert ac.mapping_path == site["mapping"] / "tw_core/rehearsal_a.yaml"
    assert (kind, path) == ("csv", str(site["feed"]))
    assert cli.main(["keys-init"]) == 0
    capsys.readouterr()
    rc = cli.main(["run", "--snapshot", "2026-10-04", "--no-fhir", "--no-validate"])
    out = capsys.readouterr().out
    report = json.loads(out[out.index("{\n") :])  # the report, after the service's one-line log records
    assert rc == 0, report.get("errors")
    assert report["passed"] and report["counts"].get("Patient", 0) > 0, report["counts"]


def test_the_adapter_tells_a_busy_lake_from_a_refusal_over_http(
    site: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-722 (D-462): the lake service's 409 with ``X-TB-Lake-Busy`` is ``LakeBusy`` (retried, as in process); a 409
    without it stays a refusal of the data (``RebuildRefused``, a held night)."""
    import httpx
    from adapter import cli
    from adapter.pipeline import RebuildRefused
    from lake.store import LakeBusy

    answer: dict[str, Any] = {}

    def post(url: str, **k: Any) -> httpx.Response:
        return httpx.Response(409, json={"detail": answer["detail"]}, headers=answer["headers"],
                              request=httpx.Request("POST", url))  # fmt: skip

    monkeypatch.setenv("TB_ADAPTER_LAKE", "http")
    monkeypatch.setattr(httpx, "post", post)
    ac, _, _ = cli.build_config()
    assert ac.rebuild is not None
    answer.update(detail="lake snapshot 2026-10-04 is already building", headers={"X-TB-Lake-Busy": "building"})
    with pytest.raises(LakeBusy, match="already building"):
        ac.rebuild("2026-10-04", site["tmp"])
    answer.update(detail="would tombstone person: 600 of 600", headers={})
    with pytest.raises(RebuildRefused, match="600 of 600"):
        ac.rebuild("2026-10-04", site["tmp"])


def test_a_missing_site_mapping_is_a_configuration_error(site: dict[str, Path]) -> None:
    from adapter import cli
    from tb_common.config import ConfigError

    (site["mapping"] / "tw_core/rehearsal_a.yaml").unlink()
    with pytest.raises(ConfigError, match="deploy/site/mapping"):
        cli.build_config()


def test_the_site_folder_comes_before_the_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter.mapping import site as ms

    monkeypatch.delenv("TB_MAPPING_DIR", raising=False)
    shipped = ms.resolve("mapping/tw_core/demo_his.yaml", [tmp_path])
    assert shipped == ROOT / "services/adapter/mapping/tw_core/demo_his.yaml" and ms.where(shipped) == "image"
    own = tmp_path / "tw_core/demo_his.yaml"
    own.parent.mkdir(parents=True)
    own.write_text("version: 1\n", encoding="utf-8")
    assert ms.resolve("mapping/tw_core/demo_his.yaml", [tmp_path]) == own  # a site's own copy wins
    assert ms.resolve(str(own)) == own  # an absolute path is taken as it is
    # a relative extends finds the image's shared mapping when the site folder has none
    base = ms.resolve_extends(tmp_path / "tw_core/site.yaml", "../tw_core/lab_local_to_loinc.csv")
    assert base == ROOT / "services/adapter/mapping/tw_core/lab_local_to_loinc.csv"


def test_compose_mounts_the_site_mapping_and_the_feed_where_the_settings_say() -> None:
    from adapter.mapping.site import SITE_MOUNT

    vols = [str(v) for v in _compose_adapter()["volumes"]]
    assert f"${{TB_MAPPING_HOST_DIR:-./site/mapping}}:{SITE_MOUNT}:ro" in vols
    feed = next(v for v in vols if v.startswith("${TB_SOURCE_DIR"))
    assert feed.endswith(":${TB_SOURCE_MOUNT:-/data/source/site-a}:ro")  # the mount point follows the wizard


# ---------------------------------------------------------------------------------- wizard


def test_the_runbook_answers_example_works(tmp_path: Path) -> None:
    """OPS-012: RUNBOOK §1 step 3's example, as written, writes a valid settings file."""
    out, env = tmp_path / "settings.yaml", tmp_path / ".env"
    assert settings_wizard.main(["--answers", str(ANSWERS_C), "--out", str(out), "--env-out", str(env)]) == 0
    assert settings_wizard.main(["--check", str(out)]) == 0
    e = dict(ln.split("=", 1) for ln in env.read_text(encoding="utf-8").splitlines() if "=" in ln and ln[0] != "#")
    assert e["TB_SOURCE_DIR"] == "/srv/hospc/his-export" and e["TB_SOURCE_MOUNT"] == "/data/source/site-c"
    assert e["TB_TLS_HOSTNAME"] == "trialbox.hospc.test" and e["TB_TLS_MODE"] == "hospital"
    assert yaml.safe_load(out.read_text(encoding="utf-8").split("\n", 3)[3])["data_source"]["mapping"] == (
        "mapping/tw_core/site_c.yaml"
    )


def test_the_wizard_checks_tls_answers() -> None:
    a = yaml.safe_load(ANSWERS_C.read_text(encoding="utf-8"))
    dirs = [ANSWERS_C.parent / "mapping"]
    with pytest.raises(settings_wizard.WizardError, match="needs tls_cert_file"):
        settings_wizard.build({**a, "tls_mode": "hospital", "tls_cert_file": ""}, dirs)
    with pytest.raises(settings_wizard.WizardError, match="not a DNS name"):
        settings_wizard.build({**a, "tls_hostname": "https://x"}, dirs)
    _, env, warnings = settings_wizard.build({**a, "tls_hostname": ""}, dirs)
    assert "TB_TLS_HOSTNAME" not in env and any("install.sh asks for it" in w for w in warnings)
    _, env, _ = settings_wizard.build(
        {**a, "tls_mode": "hospital", "tls_cert_file": "/etc/tb/site.crt", "tls_key_file": "/etc/tb/site.key"}, dirs
    )
    assert env["TB_TLS_CERT_FILE"] == "/etc/tb/site.crt" and env["TB_TLS_MODE"] == "hospital"


def test_the_wizard_makes_the_hospital_certificate_the_first_choice() -> None:
    """OPS-060: the hospital's certificate is the default; Caddy's internal CA is allowed with a warning."""
    assert settings_wizard.TLS_MODES[0] == "hospital"
    (q,) = [q for q in settings_wizard.QUESTIONS if q[0] == "tls_mode"]
    assert q[2] == "hospital" and "first choice" in q[1]
    a = yaml.safe_load(ANSWERS_C.read_text(encoding="utf-8"))
    for k in ("tls_mode", "tls_cert_file", "tls_key_file"):
        a.pop(k)
    dirs = [ANSWERS_C.parent / "mapping"]
    with pytest.raises(settings_wizard.WizardError, match=r"hospital \(the default\) needs tls_cert_file"):
        settings_wizard.build(a, dirs)
    _, env, warnings = settings_wizard.build(
        {**a, "tls_cert_file": "/etc/tb/site.crt", "tls_key_file": "/etc/tb/site.key"}, dirs
    )
    assert env["TB_TLS_MODE"] == "hospital" and not any("tls_mode internal" in w for w in warnings)
    _, env, warnings = settings_wizard.build({**a, "tls_mode": "internal"}, dirs)
    assert env["TB_TLS_MODE"] == "internal"
    assert any("every clinic PC" in w and "personal devices" in w for w in warnings)


def test_the_wizard_refuses_a_mapping_in_neither_place() -> None:
    a = yaml.safe_load(ANSWERS_C.read_text(encoding="utf-8"))
    with pytest.raises(settings_wizard.WizardError, match="site mapping folder"):
        settings_wizard.build(a, [])  # site_c.yaml is in the answers' mapping/ only


# ---------------------------------------------------------------------------------- install.sh


def _after(marker: str, text: str = INSTALL) -> str:
    assert marker in text, marker
    return text[text.index(marker) :]


def test_install_mounts_the_site_mapping_into_the_wizard_and_requires_a_feed_in_production() -> None:
    assert 'MAPPING_MOUNT=(-v "$ROOT/deploy/site/mapping:/etc/trialbox/mapping:ro")' in INSTALL
    assert INSTALL.count('"${MAPPING_MOUNT[@]}"') == 2  # answers and questions
    assert "cp -rn" in INSTALL  # the kit's mapping/ is copied, never over the site's own files
    feed = _after('SRC_DIR="$(envget TB_SOURCE_DIR)"')[:1200]
    assert '[ "$TB_ENV_SITE" != PRODUCTION ] || die "no feed folder' in feed
    assert "is not a folder on this host" in feed


def test_install_turns_tls_on_before_the_stack_starts() -> None:
    tls = _after('TLS_HOST="$(envget TB_TLS_HOSTNAME)"')
    assert 'die "no TLS host name: a PRODUCTION box runs only behind https' in tls[:1200]
    check = INSTALL.index("python -m console.cli check-tls")
    overlay = INSTALL.index("COMPOSE+=(-f deploy/docker-compose.identity.yml)")
    up = INSTALL.index('"${COMPOSE[@]}" up -d')
    assert check < overlay < up
    assert 'die "the TLS settings do not pass' in INSTALL[check : check + 400]


def test_install_installs_both_cron_files_or_stops_in_production() -> None:
    cron = _after('CRON_DIR="${TB_CRON_DIR:-/etc/cron.d}"')
    assert '"$CRON_DIR/trialbox-retention"' in cron[:900]
    assert 'die "the cron files cannot be installed' in cron[:1200]
    assert 'if [ "$CAN_CRON" = 1 ]; then\n  say "backups: cron' in INSTALL


def test_install_prints_the_enrolment_code_and_names_the_judge_from_the_configuration() -> None:
    boot = INSTALL.index("console.cli bootstrap-admin --username admin --mailbox")
    enrol = INSTALL.index("console.cli enrol-code admin")
    assert boot < enrol
    assert "python -m tools.pin_model --name-judge" in INSTALL
    reg = yaml.safe_load((ROOT / "models/registry.yaml").read_text(encoding="utf-8"))
    for b in reg["builds"]:  # the installer names the judge from the registry, never by a written-in model name
        for key in ("model_name", "repository"):
            if b.get(key):
                assert str(b[key]) not in INSTALL, f"install.sh names {b[key]!r}: read it from the registry"


def test_install_ends_with_an_https_url_it_checked_and_exit_1_on_a_fail() -> None:
    end = _after("# T-632 (OPS-013): the https:// URL must answer")
    assert 'URL="https://$TLS_HOST"' in end and "--resolve" in end and "caddy-root.crt" in end
    assert 'FAILS+=("$URL/login does not answer' in end
    assert "Console:            $URL" in end
    assert end.rstrip().endswith("printf 'install: FAIL: %s\\n' \"${FAILS[@]}\" >&2\n  exit 1\nfi")
    assert '>/dev/null 2>&1 && echo "    network sheet' not in INSTALL  # OPS-014: the error is never hidden


def test_the_judge_is_named_by_role_and_registry_label(tmp_path: Path) -> None:
    reg = yaml.safe_load((ROOT / "models/registry.yaml").read_text(encoding="utf-8"))
    for gpu, pairs in pin_model.PROFILE_PAIRS.items():
        build = next(b for b, ep, *_ in pairs if ep == "serving")
        entry = next(b for b in reg["builds"] if b["build_id"] == build)
        line = pin_model.judge_line(gpu, tmp_path / "none.yaml")
        assert line.startswith(f"judge ({entry['alias']}): {entry.get('model_name') or build}; build {build}")
        assert line.endswith("not pinned (routes nothing yet)")
    out = tmp_path / "registry.site.yaml"
    build = pin_model.PROFILE_PAIRS["rtxpro6000"][0][0]
    out.write_text(yaml.safe_dump({"kind": "registry-site-override", "builds": {build: {"sha256": "ab" * 32}}}))
    assert pin_model.judge_line("rtxpro6000", out).endswith("pinned " + "ab" * 6)
    assert pin_model.main(["--name-judge", "nope", "--out", str(out)]) == 2


def test_no_model_name_is_written_into_the_new_install_code() -> None:
    """The card's rule: the judge comes from the configuration, so the new code carries no model name."""
    new = _after("# T-632 (D-382): the judge, named from the configuration")
    assert not re.search(r"(?i)gemma|qwen|llama|gpt-", new)
    assert os.access(ROOT / "deploy/install.sh", os.X_OK)
