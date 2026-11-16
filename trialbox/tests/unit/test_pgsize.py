"""T-703 (D-751): PostgreSQL sized from the memory the box gives it (scale review F-19)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.trialbox import pgsize

ROOT = Path(__file__).resolve().parents[2]


def test_the_settings_follow_the_published_rules() -> None:
    s = pgsize.settings(16384)  # a 16 GB cap
    assert s["TB_PG_SHARED_BUFFERS"] == "4096MB"  # a quarter
    assert s["TB_PG_EFFECTIVE_CACHE_SIZE"] == "12288MB"  # three quarters
    assert s["TB_PG_MAINTENANCE_WORK_MEM"] == "1024MB"  # a sixteenth
    assert s["TB_PG_MAX_WAL_SIZE"] == "16GB" and s["TB_PG_MIN_WAL_SIZE"] == "4GB"  # bulk writes at night
    assert s["TB_PG_SHM"] == "4096m"
    assert pgsize.settings(65536)["TB_PG_MAINTENANCE_WORK_MEM"] == "2048MB"  # at most 2 GB


def test_the_idle_transaction_limit_is_twice_the_longest_lake_query() -> None:
    assert pgsize.settings(4096, {"TB_LAKE_QUERY_LIMITS": "FEAS=1800,COHORT=600"})["TB_PG_IDLE_TX_TIMEOUT"] == "3600s"
    assert pgsize.settings(4096, {"TB_LAKE_QUERY_LIMITS": "FEAS=7200"})["TB_PG_IDLE_TX_TIMEOUT"] == "14400s"


def test_install_writes_them_and_keeps_a_value_set_by_hand(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_MEM_DB=8g\nTB_PG_SHARED_BUFFERS=1GB\n", encoding="utf-8")
    assert pgsize.main(["--env-file", str(env), "--write"]) == 0
    text = env.read_text(encoding="utf-8")
    assert "TB_PG_SHARED_BUFFERS=1GB" in text and "TB_PG_EFFECTIVE_CACHE_SIZE=6144MB" in text
    env.write_text(text.replace("TB_MEM_DB=8g", "TB_MEM_DB=16g"), encoding="utf-8")
    pgsize.main(["--env-file", str(env), "--write"])  # a re-run follows a new cap, what it wrote itself
    text = env.read_text(encoding="utf-8")
    assert "TB_PG_EFFECTIVE_CACHE_SIZE=12288MB" in text and "TB_PG_SHARED_BUFFERS=1GB" in text
    assert sum(ln.startswith("TB_PG_EFFECTIVE_CACHE_SIZE=") for ln in text.splitlines()) == 1
    assert "tools.trialbox.pgsize --env-file deploy/.env --write" in (ROOT / "deploy" / "install.sh").read_text(
        encoding="utf-8"
    )


def test_compose_passes_each_setting_with_postgres_own_default() -> None:
    db = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["db"]
    cmd = " ".join(db["command"])
    for pg, var in pgsize.PG.items():
        assert f"{pg}=${{{var}:-{pgsize.POSTGRES_DEFAULTS[var]}}}" in cmd, pg
    assert db["shm_size"] == "${TB_PG_SHM:-64m}"


def test_the_platform_manifest_carries_the_sizes_of_its_own_limit() -> None:
    docs = list(yaml.safe_load_all((ROOT / "deploy" / "platform" / "base" / "db.yaml").read_text(encoding="utf-8")))
    pod = next(d for d in docs if d and d.get("kind") == "StatefulSet")["spec"]["template"]["spec"]
    c = pod["containers"][0]
    cap = pgsize.size_mb(c["resources"]["limits"]["memory"].replace("Gi", "g"))
    want = pgsize.settings(cap)
    args = " ".join(c["args"])
    for pg, var in pgsize.PG.items():
        assert f"{pg}={want[var]}" in args, pg
    shm = next(v for v in pod["volumes"] if v["name"] == "shm")
    assert shm["emptyDir"] == {"medium": "Memory", "sizeLimit": want["TB_PG_SHM"].replace("m", "Mi")}
    assert {"name": "shm", "mountPath": "/dev/shm"} in c["volumeMounts"]


@pytest.mark.parametrize(
    ("host_gb", "env", "status"),
    [
        (128, {}, "FAIL"),  # PostgreSQL's defaults on a large host
        (128, {"TB_PG_SHARED_BUFFERS": "128MB"}, "FAIL"),
        (128, {"TB_PG_SHARED_BUFFERS": "2048MB"}, "PASS"),
        (16, {}, "WARN"),  # a small box: said, not failed
    ],
)
def test_doctor_fails_on_the_defaults_of_a_large_host(
    tmp_path: Path, host_gb: int, env: dict[str, str], status: str
) -> None:
    (tmp_path / "meminfo").write_text(f"MemTotal: {host_gb * 1048576} kB\n", encoding="utf-8")
    got, detail = pgsize.check(env, tmp_path)
    assert got == status, detail
    assert "shared_buffers" in detail


def test_every_setting_is_declared() -> None:
    from tb_common.config import DECLARED

    for var in [*pgsize.PG.values(), "TB_PG_SHM"]:
        assert var in DECLARED, var


def test_doctor_judges_only_a_box_with_its_env_file(tmp_path: Path) -> None:
    from tools.trialbox import doctor

    (tmp_path / "meminfo").write_text(f"MemTotal: {128 * 1048576} kB\n", encoding="utf-8")
    without = doctor.check_postgres_memory(doctor.DoctorInputs(env={}, proc=tmp_path))
    assert without.status == "WARN"
    box = doctor.check_postgres_memory(doctor.DoctorInputs(env={}, proc=tmp_path, deploy=tmp_path))
    assert box.status == "FAIL" and box.name == "postgres_memory"
