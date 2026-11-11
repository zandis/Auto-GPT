"""Day 2 on the platform (T-633, D-416; OPS-050, OPS-068, OPS-069, OPS-070), without a cluster: the CronJobs, the
claims and their classes, the update and rollback overlays, the log job, the database spool, and the checks of
``doctor --platform`` that fail when the backup job is missing. The same flows on a kind cluster are
``deploy/platform/kind-day2.sh`` (RUNBOOK §26); the backup and restore commands against a real database are in
``test_day2_db.py``."""

from __future__ import annotations

import copy
import gzip
import io
import json
import os
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common.audit import AuditLog

from tests.platform.kustomize_lite import build
from tools.trialbox import platform as pf
from tools.trialbox import platform_day2 as d2
from tools.trialbox.__main__ import main as cli

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "deploy" / "platform"
OVERLAYS = ("shared-quota", "interim-cloud", "update")
DATA_CLAIMS = ("lake-data", "objects-data", "audit-data", "rulesets-data", "orch-data", "mail-data", "tb-secrets",
               "console-data")  # fmt: skip
NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
DIGEST = "sha256:" + "ab" * 32
PINNED = ("trialbox-py", "trialbox-jvm", "trialbox-postgres", "vllm")  # unreleased in deploy/platform/release.json


def _objs(overlay: str = "shared-quota") -> list[dict[str, Any]]:
    return build(PLATFORM / "overlays" / overlay)


def _named(objs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(o for o in objs if o["kind"] == kind and o["metadata"]["name"] == name)


def _pod(cj: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    return spec


def _inputs(objs: list[dict[str, Any]], source: str = "manifests", **env: str) -> pf.PlatformInputs:
    return pf.PlatformInputs(
        pf.PlatformState(copy.deepcopy(objs), source, "trialbox"),
        pf.load_release(),
        {"TB_ENV": "TEST", **env},
        connect=lambda h, p: None,
        sntp=lambda s: 0.0,
        resolve=lambda h: ["10.96.0.1"] if h else [],
        now=NOW,
    )


# ------------------------------------------------------------------------------------------------ the manifests
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_day2_jobs_and_claims_are_in_every_overlay(overlay: str) -> None:
    objs = _objs(overlay)
    backup = _named(objs, "CronJob", "trialbox-backup")
    assert backup["spec"]["concurrencyPolicy"] == "Forbid" and not backup["spec"].get("suspend")
    pod = _pod(backup)
    init = {c["name"]: c for c in pod["initContainers"]}
    assert init["prepare"]["command"][-3:] == ["snapshot-prepare", "--spool", "/spool"]
    assert init["snapshot"]["image"].startswith("trialbox-postgres")  # psql and pg_dump of the database image
    assert init["snapshot"]["command"] == ["sh", "/scripts/pg-snapshot.sh", "/spool"]
    main = pod["containers"][0]
    assert main["command"][3:5] == ["platform-day2", "backup"] and "/backup/trialbox" in main["command"]
    env = {e["name"]: e for e in main["env"]}
    assert env["TB_PG_DUMP_DIR"]["value"] == "/spool"
    names = {p.partition("=")[0] for p in env["TB_BACKUP_DIRS"]["value"].split(",")}
    from tools.trialbox import backup as bk

    assert names == set(bk.DEFAULT_DIRS)  # the appliance's names: a backup restores on either form
    assert env["TB_HAPI_DB_URL"]["valueFrom"]["secretKeyRef"]["optional"] is True
    claims = {v["name"]: v["persistentVolumeClaim"] for v in pod["volumes"] if "persistentVolumeClaim" in v}
    assert claims["backup-share"] == {"claimName": "backup-share"}
    for c in DATA_CLAIMS:  # the backup only reads the data claims
        assert claims[c]["readOnly"] is True, c
    assert all(m.get("readOnly") for m in main["volumeMounts"] if m["mountPath"].startswith("/vol/"))
    share = _named(objs, "PersistentVolumeClaim", "backup-share")
    assert share["metadata"]["labels"]["trialbox.io/storage"] == "backup-share"
    logs = _named(objs, "CronJob", "trialbox-logs")
    assert _pod(logs)["serviceAccountName"] == "trialbox-ops"
    role = _named(objs, "Role", "trialbox-ops")
    assert role["rules"] == [
        {"apiGroups": [""], "resources": ["pods"], "verbs": ["list"]},
        {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
    ]  # nothing else: never a Secret
    restore = _named(objs, "CronJob", "trialbox-restore")
    assert restore["spec"]["suspend"] is True  # runs only as `kubectl create job --from=cronjob/...`
    rpod = _pod(restore)
    rmain, spool = rpod["containers"]
    renv = {e["name"]: e.get("value") for e in rmain["env"]}
    assert renv["TB_PG_RESTORE_CMD"] == renv["TB_PG_DUMP_CMD"].replace("pg_dump", "pg_restore")
    assert renv["TB_PG_SPOOL"] == "/spool/pg" and spool["command"] == ["sh", "/scripts/pg-spool.sh", "/spool/pg"]
    assert {"name": "restore-key", "secret": {"secretName": pf.RESTORE_KEY_SECRET, "defaultMode": 0o400}} in rpod[
        "volumes"
    ]
    # the database's claim is block storage (OPS-069)
    tmpl = _named(objs, "StatefulSet", "db")["spec"]["volumeClaimTemplates"][0]
    assert tmpl["metadata"]["name"] == pf.DB_CLAIM and tmpl["spec"]["accessModes"] == ["ReadWriteOnce"]
    # the scripts the database image runs are the files in the repository
    scripts = _named(objs, "ConfigMap", "trialbox-day2-scripts")["data"]
    for f in ("pg-snapshot.sh", "pg-spool.sh"):
        assert scripts[f] == (PLATFORM / "base" / "day2" / f).read_text(encoding="utf-8")
    # the jobs reach the database and nothing else; the database takes them on 5432 only
    to_db = _named(objs, "NetworkPolicy", "trialbox-day2-to-db")["spec"]
    assert to_db["egress"] == [
        {"to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/component": "db"}}}],
         "ports": [{"protocol": "TCP", "port": 5432}]}
    ]  # fmt: skip
    assert not pf.open_rules([o for o in objs if o["kind"] == "NetworkPolicy"])


def test_doctor_reads_cronjobs() -> None:
    assert ("CronJob", "/apis/batch/v1/namespaces/{ns}/cronjobs") in pf.KubeApi.PATHS
    role = yaml.safe_load_all((PLATFORM / "base" / "doctor.yaml").read_text(encoding="utf-8"))
    rules = next(r for r in role if r and r["kind"] == "Role")["rules"]
    assert any(r["apiGroups"] == ["batch"] and "cronjobs" in r["resources"] for r in rules)


# ------------------------------------------------------------------------------------------------ doctor --platform
def test_doctor_platform_fails_when_no_backup_job_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 4: without the CronJob trialbox-backup the check backup_job fails in every environment, and the
    command exits 1."""
    objs = _objs()
    assert pf.check_backup_job(_inputs(objs)).status != "FAIL"
    gone = [o for o in objs if (o["kind"], o["metadata"]["name"]) != ("CronJob", "trialbox-backup")]
    for env in ("TEST", "DEV", "VALIDATION", "PRODUCTION"):
        c = pf.check_backup_job(_inputs(gone, TB_ENV=env))
        assert c.status == "FAIL" and "no backup job" in c.detail, env
    for k in list(os.environ):
        if k.startswith(("TB_", "SMTP_", "IMAP_")) or k == "KUBERNETES_SERVICE_HOST":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TB_ENV", "TEST")
    quota = {"kind": "ResourceQuota", "metadata": {"name": "q"}, "spec": {"hard": {"requests.cpu": "64"}}}
    for name, docs, want in (("with", objs, "PASS"), ("without", gone, "FAIL")):
        man = tmp_path / f"{name}.yaml"
        man.write_text(yaml.safe_dump_all([*docs, quota]), encoding="utf-8")
        ev = tmp_path / f"{name}.json"
        rc = cli(["doctor", "--platform", "--no-gpu", "--manifests", str(man), "--evidence", str(ev)])
        by = {c["name"]: c for c in json.loads(ev.read_text(encoding="utf-8"))["checks"]}
        assert {"backup_job", "log_job", "db_storage", "pod_limits"} <= set(by)
        if want == "FAIL":
            assert rc == 1 and by["backup_job"]["status"] == "FAIL"
        else:
            assert by["backup_job"]["status"] in ("PASS", "WARN")


def test_backup_job_check_follows_the_job() -> None:
    objs = _objs()
    tz = {"TB_TZ": "Asia/Taipei"}
    c = pf.check_backup_job(_inputs(objs, **tz))
    assert c.status == "WARN" and "timeZone" in c.detail  # the base leaves the zone to the site overlay
    assert pf.check_backup_job(_inputs(objs, TB_ENV="PRODUCTION", **tz)).status == "FAIL"
    cj = _named(objs, "CronJob", "trialbox-backup")
    cj["spec"]["timeZone"] = "Asia/Taipei"
    assert pf.check_backup_job(_inputs(objs, TB_ENV="PRODUCTION", **tz)).status == "PASS"
    # suspended, or writing elsewhere than the share
    sus = copy.deepcopy(objs)
    _named(sus, "CronJob", "trialbox-backup")["spec"]["suspend"] = True
    assert pf.check_backup_job(_inputs(sus, **tz)).status == "FAIL"
    noshare = [o for o in copy.deepcopy(objs) if o["metadata"]["name"] != "backup-share"]
    assert "backup share" in pf.check_backup_job(_inputs(noshare, **tz)).detail
    # in a cluster: the last success, the FHIR store's URL, a restore key left behind
    live = copy.deepcopy(objs)
    cjl = _named(live, "CronJob", "trialbox-backup")
    cjl["metadata"]["creationTimestamp"] = (NOW - timedelta(days=10)).isoformat()
    cjl["status"] = {"lastSuccessfulTime": (NOW - timedelta(hours=5)).isoformat().replace("+00:00", "Z")}
    live.append(
        {"kind": "Secret", "metadata": {"name": "trialbox-db"}, "data": {"TB_DB_URL": "", "TB_HAPI_DB_URL": ""}}
    )
    prod = {"TB_ENV": "PRODUCTION", **tz}
    assert pf.check_backup_job(_inputs(live, "cluster", **prod)).status == "PASS"
    cjl["status"] = {"lastSuccessfulTime": (NOW - timedelta(hours=40)).isoformat()}
    c = pf.check_backup_job(_inputs(live, "cluster", **prod))
    assert c.status == "FAIL" and "40 h ago" in c.detail
    assert pf.check_backup_job(_inputs(live, "cluster", TB_BACKUP_MAX_AGE_HOURS="48", **prod)).status == "PASS"
    cjl["status"] = {}
    assert "has not succeeded" in pf.check_backup_job(_inputs(live, "cluster", **prod)).detail
    cjl["metadata"]["creationTimestamp"] = (NOW - timedelta(hours=2)).isoformat()
    assert pf.check_backup_job(_inputs(live, "cluster", **prod)).status == "WARN"  # not run yet
    cjl["status"] = {"lastSuccessfulTime": NOW.isoformat()}
    _named(live, "Secret", "trialbox-db")["data"].pop("TB_HAPI_DB_URL")
    c = pf.check_backup_job(_inputs(live, "cluster", **prod))
    assert c.status == "FAIL" and "hapi" in c.detail
    _named(live, "Secret", "trialbox-db")["data"]["TB_HAPI_DB_URL"] = ""
    live.append({"kind": "Secret", "metadata": {"name": pf.RESTORE_KEY_SECRET}, "data": {"backup.key": ""}})
    c = pf.check_backup_job(_inputs(live, "cluster", **prod))
    assert c.status == "FAIL" and "D-126" in c.detail
    assert pf.check_backup_job(_inputs(live, "cluster", **{**prod, "TB_ENV": "TEST"})).status == "WARN"
    # the compose form: the platform declares the host's schedule
    comp = pf.PlatformState([], "compose")
    inp = _inputs([], "compose")
    inp.state = comp
    assert pf.check_backup_job(inp).status == "FAIL"
    inp.env = {**inp.env, "TB_PLATFORM_BACKUP_JOB_EVIDENCE": "cron on host-7"}
    assert pf.check_backup_job(inp).status == "PASS"


def test_log_job_check() -> None:
    objs = _objs()
    tz = {"TB_TZ": "Asia/Taipei"}
    for cj in (o for o in objs if o["kind"] == "CronJob"):
        cj["spec"]["timeZone"] = "Asia/Taipei"
    assert pf.check_log_job(_inputs(objs, **tz)).status == "PASS"
    gone = [o for o in objs if o["metadata"]["name"] != "trialbox-logs"]
    assert pf.check_log_job(_inputs(gone)).status == "WARN"
    assert pf.check_log_job(_inputs(gone, TB_ENV="VALIDATION")).status == "FAIL"
    live = copy.deepcopy(objs)
    cj = _named(live, "CronJob", "trialbox-logs")
    cj["status"] = {"lastSuccessfulTime": (NOW - timedelta(days=3)).isoformat()}
    assert pf.check_log_job(_inputs(live, "cluster", TB_ENV="PRODUCTION", **tz)).status == "FAIL"


def test_db_storage_wants_block_storage_for_the_database() -> None:
    """OPS-069: the database's claim is ReadWriteOnce on a block class that is not the shared file system class."""
    objs = _objs()
    assert pf.check_db_storage(_inputs(objs)).status == "WARN"  # TEST: not declared yet
    assert pf.check_db_storage(_inputs(objs, TB_ENV="PRODUCTION")).status == "FAIL"
    block = copy.deepcopy(objs)
    tmpl = _named(block, "StatefulSet", "db")["spec"]["volumeClaimTemplates"][0]
    tmpl["spec"]["storageClassName"] = "enc-block"
    decl = {"TB_PLATFORM_DB_STORAGE_CLASS": "enc-block", "TB_PLATFORM_DB_STORAGE_EVIDENCE": "SC-BLK-1",
            "TB_PLATFORM_STORAGE_CLASS": "enc-rwx"}  # fmt: skip
    assert pf.check_db_storage(_inputs(block, TB_ENV="PRODUCTION", **decl)).status == "PASS"
    c = pf.check_db_storage(_inputs(block, TB_ENV="PRODUCTION", **{**decl, "TB_PLATFORM_STORAGE_CLASS": "enc-block"}))
    assert c.status == "FAIL" and "file system" in c.detail
    rwx = copy.deepcopy(block)
    _named(rwx, "StatefulSet", "db")["spec"]["volumeClaimTemplates"][0]["spec"]["accessModes"] = ["ReadWriteMany"]
    c = pf.check_db_storage(_inputs(rwx, **decl))
    assert c.status == "FAIL" and "OPS-069" in c.detail
    made = [*copy.deepcopy(block), {"kind": "PersistentVolumeClaim", "metadata": {"name": "db-pg-db-0"},
                                    "spec": {"storageClassName": "enc-rwx", "accessModes": ["ReadWriteOnce"]}}]  # fmt: skip
    c = pf.check_db_storage(_inputs(made, "cluster", **decl))
    assert c.status == "FAIL" and "never moves class" in c.detail
    # storage_encryption holds the database's claims to the block class and leaves the backup share out
    enc = copy.deepcopy(block)
    for o in enc:
        if o["kind"] == "PersistentVolumeClaim" and o["metadata"]["name"] != "backup-share":
            o["spec"]["storageClassName"] = "enc-rwx"
    enc_env = {**decl, "TB_PLATFORM_STORAGE_ENCRYPTED": "yes", "TB_PLATFORM_STORAGE_EVIDENCE": "SC-1"}
    assert pf.check_storage_encryption(_inputs(enc, TB_ENV="PRODUCTION", **enc_env)).status == "PASS"
    enc.append({"kind": "PersistentVolumeClaim", "metadata": {"name": "db-pg-db-0"},
                "spec": {"storageClassName": "enc-block"}})  # fmt: skip
    assert pf.check_storage_encryption(_inputs(enc, TB_ENV="PRODUCTION", **enc_env)).status == "PASS"


def test_pod_limits_on_a_shared_host() -> None:
    """OPS-070: every container states its requests and a memory limit."""
    objs = _objs()
    assert pf.check_pod_limits(_inputs(objs)).status == "PASS"
    loose = copy.deepcopy(objs)
    _pod(_named(loose, "CronJob", "trialbox-logs"))["containers"][0]["resources"] = {"requests": {"cpu": "1"}}
    c = pf.check_pod_limits(_inputs(loose))
    assert c.status == "WARN" and "CronJob/trialbox-logs logs: no requests.memory, limits.memory" in c.detail
    assert pf.check_pod_limits(_inputs(loose, TB_ENV="PRODUCTION")).status == "FAIL"


def test_the_log_jobs_egress_is_the_api_server_only() -> None:
    env = {"TB_PLATFORM_API_SERVER": "10.96.0.1:6443"}
    pol, warn = pf.render_ops_policy(env, lambda h: [h])
    assert pol is not None and not warn
    assert pol["spec"]["podSelector"] == {"matchLabels": {"app.kubernetes.io/component": "logs"}}
    assert pol["spec"]["egress"] == [{"to": [{"ipBlock": {"cidr": "10.96.0.1/32"}}], "ports": [{"protocol": "TCP",
                                                                                                "port": 6443}]}]  # fmt: skip
    assert pf.render_ops_policy({}, lambda h: [h])[0] is None
    objs = [*_objs(), pol]
    inp = _inputs(objs, **env)
    inp.resolve = lambda h: [h]
    c = pf.check_network_policy(inp)
    assert c.status == "PASS" and "log job egress as declared" in c.detail
    wide = copy.deepcopy(pol)
    wide["spec"]["egress"][0]["to"][0]["ipBlock"]["cidr"] = "10.96.0.0/16"
    inp.state = pf.PlatformState([*_objs(), wide], "manifests", "trialbox")
    c = pf.check_network_policy(inp)
    assert c.status == "FAIL" and "trialbox-egress-ops" in c.detail


def test_platform_egress_prints_the_log_jobs_policy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = tmp_path / "site.env"
    site.write_text("TB_ENV=TEST\nTB_PLATFORM_API_SERVER=10.96.0.1:6443\n", encoding="utf-8")
    assert cli(["platform-egress", "--env-file", str(site)]) == 0
    docs = [d for d in yaml.safe_load_all(capsys.readouterr().out) if d]
    assert pf.OPS_POLICY in {d["metadata"]["name"] for d in docs}


# ------------------------------------------------------------------------------------------------ update, rollback
def _release(tmp_path: Path, name: str, **digests: str) -> Path:
    rel = json.loads(pf.RELEASE.read_text(encoding="utf-8"))
    for img, dg in digests.items():
        rel["images"][img]["digest"] = dg
    rel["release_id"] = name
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(rel), encoding="utf-8")
    return p


def _images(objs: list[dict[str, Any]]) -> set[str]:
    return {c["image"] for _, spec, _ in pf.pod_specs(pf.PlatformState(objs)) for c in pf.containers(spec)}


def test_a_digest_update_and_its_rollback(tmp_path: Path) -> None:
    """Acceptance 3, structurally: the update overlay pins the changed images by their new digests and carries the
    new release.json (what doctor compares the running images with); the rollback overlay renders what ran before."""
    site = PLATFORM / "overlays" / "shared-quota"
    before = build(site)
    hapi = pf.load_release().images["hapi"]
    d1, d2_ = "sha256:" + "11" * 32, "sha256:" + "22" * 32
    pinned = {"trialbox-py": d1, "trialbox-jvm": d1, "trialbox-postgres": d1, "vllm": d1}
    cur = _release(tmp_path, "r1", **pinned)
    new = _release(tmp_path, "r2", **{**pinned, "trialbox-py": d2_})
    # 1. from the unreleased build to r1 (tags become digests)
    plan1 = d2.update_overlay(site, cur, tmp_path / "u1")
    assert {c["image"] for c in plan1["changes"]} == {"trialbox-py", "trialbox-jvm", "trialbox-postgres", "vllm"}
    after1 = build(tmp_path / "u1" / "next")
    assert all("@" in i for i in _images(after1)) and f"hapiproject/hapi@{hapi.digest}" in _images(after1)
    # 2. r1 to r2, from the overlay applied now (u1/next): only trialbox-py moves
    plan2 = d2.update_overlay(site, new, tmp_path / "u2", current_release=cur, current=tmp_path / "u1" / "next")
    assert [c["image"] for c in plan2["changes"]] == ["trialbox-py"]
    after2 = build(tmp_path / "u2" / "next")
    imgs2 = _images(after2)
    assert f"trialbox-py@{d2_}" in imgs2 and f"trialbox-py@{d1}" not in imgs2 and f"trialbox-jvm@{d1}" in imgs2
    rel_cm = _named(after2, "ConfigMap", "trialbox-release")["data"]["release.json"]
    assert json.loads(rel_cm)["release_id"] == "r2"
    st = pf.PlatformState(after2)
    assert pf.check_image_digests(pf.PlatformInputs(st, pf.load_release(tmp_path / "u2/next/release.json"),
                                                    {"TB_ENV": "PRODUCTION"})).status == "PASS"  # fmt: skip
    # 3. the rollback renders what ran before the update
    back = build(tmp_path / "u2" / "previous")
    assert _images(back) == _images(after1)
    assert json.loads(_named(back, "ConfigMap", "trialbox-release")["data"]["release.json"])["release_id"] == "r1"
    assert _images(build(tmp_path / "u1" / "previous")) == _images(before)
    plan_doc = json.loads((tmp_path / "u2" / "plan.json").read_text(encoding="utf-8"))
    assert "create job --from=cronjob/trialbox-backup" in plan_doc["steps"][0]  # the dump first


def test_what_is_not_a_digest_update_is_refused(tmp_path: Path) -> None:
    site = PLATFORM / "overlays" / "shared-quota"
    with pytest.raises(d2.Day2Error, match="changes no digest"):
        d2.update_overlay(site, _release(tmp_path, "a"), tmp_path / "o")  # unreleased on both sides
    pinned = _release(tmp_path, "p", **{"trialbox-py": DIGEST})
    with pytest.raises(d2.Day2Error, match="no digest"):  # an update never unpins an image
        d2.update_overlay(site, _release(tmp_path, "a2"), tmp_path / "o", current_release=pinned)
    every = dict.fromkeys(PINNED, DIGEST)
    rel = json.loads(_release(tmp_path, "b", **{**every, "trialbox-py": "sha256:" + "ef" * 32}).read_text())
    rel["images"]["trialbox-py"]["image"] = "registry.example/other-py:1.0.0"
    other = tmp_path / "other.json"
    other.write_text(json.dumps(rel), encoding="utf-8")
    cur = _release(tmp_path, "c", **every)
    with pytest.raises(d2.Day2Error, match="not a digest update"):
        d2.update_overlay(site, other, tmp_path / "o", current_release=cur)
    del rel["images"]["trialbox-jvm"]
    other.write_text(json.dumps(rel), encoding="utf-8")
    with pytest.raises(d2.Day2Error, match="images differ"):
        d2.update_overlay(site, other, tmp_path / "o", current_release=cur)
    with pytest.raises(d2.Day2Error, match="changes no digest"):
        d2.update_overlay(site, cur, tmp_path / "o", current_release=cur)


def test_the_committed_update_overlay_is_a_no_op(tmp_path: Path) -> None:
    assert _images(_objs("update")) == _images(_objs("shared-quota"))
    k = yaml.safe_load((PLATFORM / "overlays" / "update" / "kustomization.yaml").read_text(encoding="utf-8"))
    assert k["images"] == [] and k["resources"] == ["../shared-quota"]


def test_update_overlay_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    new = _release(tmp_path, "r9", **dict.fromkeys(PINNED, DIGEST))
    site = PLATFORM / "overlays" / "shared-quota"
    assert cli(["platform-day2", "update-overlay", "--site", str(site), "--release", str(new), "--out",
                str(tmp_path / "u")]) == 0  # fmt: skip
    assert json.loads(capsys.readouterr().out)["to_release"] == "r9"
    assert cli(["platform-day2", "update-overlay", "--site", str(site), "--release", str(new), "--out",
                str(tmp_path / "u"), "--current-release", str(new)]) == 1  # fmt: skip
    assert "changes no digest" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ the spool
def test_spool_arguments_never_carry_a_connection_string() -> None:
    env = {"TB_DB_URL": "postgresql://tb:pw@db:5432/trialbox_wf", "TB_HAPI_DB_URL": "postgresql://hapi:pw@db:5432/hapi"}
    lines = d2.spool_args("pg_restore", ["--clean", "--dbname", env["TB_DB_URL"]], env)
    assert lines == ["pg_restore", "--clean", "--dbname", "@TB_DB_URL"]
    assert d2.spool_args("pg_dump", [f"--dbname={env['TB_HAPI_DB_URL']}"], env)[-1] == "@TB_HAPI_DB_URL"
    assert "pw" not in "".join(lines)
    with pytest.raises(d2.Day2Error, match="refused"):
        d2.spool_args("pg_dump", ["--dbname", "postgresql://x:y@elsewhere/db"], env)
    with pytest.raises(d2.Day2Error, match="only psql"):
        d2.spool_args("sh", ["-c", "true"], env)
    with pytest.raises(d2.Day2Error, match="line break"):
        d2.spool_args("psql", ["a\nb"], env)


def test_the_shim_hands_a_call_to_the_spool_and_returns_its_answer(tmp_path: Path) -> None:
    spool = tmp_path / "pg"
    env = {"TB_PG_SPOOL": str(spool), "TB_DB_URL": "postgresql://tb:pw@db:5432/trialbox_wf"}
    seen: dict[str, Any] = {}

    def serve() -> None:  # the database image's side, as pg-spool.sh does it
        while True:
            reqs = list(spool.glob("*.req")) if spool.is_dir() else []
            if reqs:
                rid = str(reqs[0])[: -len(".req")]
                seen["args"] = Path(rid + ".args").read_text(encoding="utf-8").splitlines()
                seen["in"] = Path(rid + ".in").read_bytes()
                Path(rid + ".out").write_bytes(b"restored\n")
                Path(rid + ".err").write_bytes(b"a warning\n")
                Path(rid + ".rc").write_text("0\n", encoding="utf-8")
                return
            time.sleep(0.02)

    spool.mkdir()
    t = threading.Thread(target=serve)
    t.start()
    out, err = io.BytesIO(), io.BytesIO()
    rc = d2.pg_call(["pg_restore", "--dbname", env["TB_DB_URL"]], env, io.BytesIO(b"DUMP"), out, err, poll=0.02)
    t.join(5)
    assert rc == 0 and out.getvalue() == b"restored\n" and err.getvalue() == b"a warning\n"
    assert seen == {"args": ["pg_restore", "--dbname", "@TB_DB_URL"], "in": b"DUMP"}
    assert list(spool.iterdir()) == []  # the request's files are gone
    with pytest.raises(d2.Day2Error, match="TB_PG_SPOOL"):
        d2.pg_call(["psql"], {}, io.BytesIO(), io.BytesIO(), io.BytesIO())
    with pytest.raises(d2.Day2Error, match="not running"):
        d2.pg_call(["psql"], {"TB_PG_SPOOL": str(tmp_path / "none")}, io.BytesIO(), io.BytesIO(), io.BytesIO())
    with pytest.raises(d2.Day2Error, match="no answer"):
        d2.pg_call(["psql", "-c", "select 1"], env, io.BytesIO(), io.BytesIO(), io.BytesIO(), poll=0.01, timeout=0.05)


# ------------------------------------------------------------------------------------------------ logs
def _chain(audit: Path) -> None:
    log = AuditLog(audit, "UTC")
    for i in range(3):
        log.append("test.event", ts=datetime(2026, 11, 17, 12, tzinfo=UTC) + timedelta(days=i), actor="t", detail={})


def test_the_log_job_collects_the_site_day_and_archives_the_audit(tmp_path: Path) -> None:
    tz = "UTC"
    pods = {"items": [
        {"metadata": {"name": "lake-1", "labels": {"app.kubernetes.io/component": "lake"}},
         "status": {"startTime": "2026-11-10T00:00:00Z"}, "spec": {"containers": [{"name": "lake"}]}},
        {"metadata": {"name": "gateway-1", "labels": {"app.kubernetes.io/component": "gateway"}},
         "status": {"startTime": "2026-11-10T00:00:00Z"}, "spec": {"containers": [{"name": "gateway"}]}},
    ]}  # fmt: skip
    logs = {
        "lake": b"2026-11-18T23:59:59Z late\n2026-11-19T00:00:01Z first\n2026-11-19T10:00:00Z second\n"
        b"2026-11-20T00:00:00Z next day\n",
        "gateway": b"2026-11-19T06:00:00Z only after the rotation\n",
    }
    oldest = {"lake": b"2026-11-01T00:00:00Z old\n", "gateway": b"2026-11-19T06:00:00Z only after the rotation\n"}
    calls: list[str] = []

    def get(path: str) -> bytes:
        calls.append(path)
        if path.endswith("/pods"):
            return json.dumps(pods).encode()
        comp = path.split("/pods/")[1].split("-", maxsplit=1)[0]
        return oldest[comp] if "limitBytes" in path else logs[comp]

    audit, archive, settings = tmp_path / "audit", tmp_path / "logs" / "audit-archive", tmp_path / "settings.yaml"
    _chain(audit)
    settings.write_text("retention:\n  logs_days: 30\n", encoding="utf-8")
    rc, msgs = d2.run_logs(get, "trialbox", tmp_path / "logs", audit, archive, settings, tz, today=date(2026, 11, 20))
    assert rc == 1 and any("LOG GAP" in m and "gateway" in m for m in msgs)  # gateway lost the start of its day
    day = tmp_path / "logs" / "services" / "2026-11-19"
    lake = gzip.decompress((day / "lake.log.gz").read_bytes()).decode()
    assert lake.splitlines() == ["lake-1/lake 2026-11-19T00:00:01Z first", "lake-1/lake 2026-11-19T10:00:00Z second"]
    cov = json.loads((day / "COVERAGE.json").read_text(encoding="utf-8"))
    assert cov["services"]["lake"]["gap"] is False and cov["services"]["gateway"]["gap"] is True
    assert all(c.startswith("/api/v1/namespaces/trialbox/") for c in calls)
    assert (archive / "MANIFEST.sha256").is_file() and len((archive / "MANIFEST.sha256").read_text().splitlines()) == 3
    assert d2.run_logs(get, "trialbox", tmp_path / "logs", audit, archive, settings, "")[0] == 1  # no zone: refused


def test_logs_use_the_site_zone_for_the_day(tmp_path: Path) -> None:
    pods = {"items": [{"metadata": {"name": "lake-1", "labels": {"app.kubernetes.io/component": "lake"}},
                       "status": {}, "spec": {"containers": [{"name": "lake"}]}}]}  # fmt: skip
    text = b"2026-11-18T15:59:59Z before\n2026-11-18T16:00:00Z first of the site day\n"

    def get(path: str) -> bytes:
        return json.dumps(pods).encode() if path.endswith("/pods") else text

    zone = "Asia/Tokyo"  # a site zone, as TB_TZ gives it (UTC+9: the day starts at 15:00 UTC)
    rep = d2.collect_logs(get, "trialbox", date(2026, 11, 19), tmp_path, zone)
    assert rep["since"] == "2026-11-18T15:00:00Z" and rep["services"]["lake"]["lines"] == 2
