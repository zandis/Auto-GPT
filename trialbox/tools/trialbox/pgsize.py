"""PostgreSQL sized from the memory the box gives it (T-703, D-751; scale review F-19, OD-10).

PostgreSQL ran on its own defaults (128 MB of buffers, 1 GB of WAL, 64 MB of maintenance memory, docker's 64 MB
``/dev/shm``, no limit on a session idle in a transaction). The settings here follow the published sizing rules the
community tools apply (PGTune), from the database's memory cap ``TB_MEM_DB``:

* ``shared_buffers`` a quarter of the cap; ``effective_cache_size`` three quarters;
* ``maintenance_work_mem`` a sixteenth, at most 2 GB (index builds of the FHIR store and the vector index);
* ``max_wal_size`` 16 GB, ``min_wal_size`` 4 GB: the rule for bulk writes, which the night's ingest is (at 1 GB it
  forced a checkpoint every few seconds);
* ``/dev/shm`` (``shm_size``) as large as the buffers: parallel queries and index builds keep their shared state
  there; it is counted against the cap only while used;
* ``idle_in_transaction_session_timeout`` twice the longest lake query a job may wait on (``TB_LAKE_QUERY_LIMITS``,
  D-746): a session idle in a transaction longer than that holds its locks and stops vacuum for nothing.

``deploy/install.sh`` calls ``--write``: the values go into ``deploy/.env`` unless the operator set one by hand (a
value that is not the one this tool wrote, recorded in its marker line). ``trialbox doctor`` (``postgres_memory``)
fails when ``shared_buffers`` is PostgreSQL's default on a host of 64 GB or more (the card's test).

    python -m tools.trialbox.pgsize --env-file deploy/.env [--write]
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from tools.trialbox.memcaps import COMPOSE, _parse_env, compose_default, size_mb

__all__ = ["PG", "POSTGRES_DEFAULTS", "check", "main", "plan", "settings", "size_mb", "write"]

ROOT = Path(__file__).resolve().parents[2]
MARKER = "# pgsize:"
#: PostgreSQL's setting -> the variable compose passes it in
PG = {
    "shared_buffers": "TB_PG_SHARED_BUFFERS",
    "effective_cache_size": "TB_PG_EFFECTIVE_CACHE_SIZE",
    "maintenance_work_mem": "TB_PG_MAINTENANCE_WORK_MEM",
    "max_wal_size": "TB_PG_MAX_WAL_SIZE",
    "min_wal_size": "TB_PG_MIN_WAL_SIZE",
    "idle_in_transaction_session_timeout": "TB_PG_IDLE_TX_TIMEOUT",
}
#: what PostgreSQL and docker use when nothing is set: compose's defaults, so a dev or test stack is unchanged
POSTGRES_DEFAULTS = {
    "TB_PG_SHARED_BUFFERS": "128MB",
    "TB_PG_EFFECTIVE_CACHE_SIZE": "4GB",
    "TB_PG_MAINTENANCE_WORK_MEM": "64MB",
    "TB_PG_MAX_WAL_SIZE": "1GB",
    "TB_PG_MIN_WAL_SIZE": "80MB",
    "TB_PG_IDLE_TX_TIMEOUT": "0",
    "TB_PG_SHM": "64m",
}
LARGE_HOST_GB = 64  # T-703's test: below it PostgreSQL's defaults are said, not failed
MAINTENANCE_MAX_MB = 2048  # PGTune: maintenance_work_mem gains nothing above 2 GB


# D-832: install.sh runs this module with the host's python3, which has no tb_common.config (pydantic, jsonschema);
# the declared default is copied here and a test keeps the two equal
LAKE_QUERY_LIMITS_DEFAULT = "FEAS=1800,COHORT=1800"


def _longest_lake_query_s(env: Mapping[str, str]) -> int:
    text = env.get("TB_LAKE_QUERY_LIMITS") or LAKE_QUERY_LIMITS_DEFAULT
    secs = [int(p.split("=", 1)[1]) for p in text.split(",") if "=" in p and p.split("=", 1)[1].strip().isdigit()]
    if not secs:
        raise ValueError(f"TB_LAKE_QUERY_LIMITS={text!r}: no limit to size the idle-transaction limit from")
    return max(secs)


def settings(cap_mb: int, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The settings for a database capped at ``cap_mb`` (the rules above)."""
    quarter = cap_mb // 4
    return {
        "TB_PG_SHARED_BUFFERS": f"{quarter}MB",
        "TB_PG_EFFECTIVE_CACHE_SIZE": f"{cap_mb * 3 // 4}MB",
        "TB_PG_MAINTENANCE_WORK_MEM": f"{min(cap_mb // 16, MAINTENANCE_MAX_MB)}MB",
        "TB_PG_MAX_WAL_SIZE": "16GB",
        "TB_PG_MIN_WAL_SIZE": "4GB",
        "TB_PG_IDLE_TX_TIMEOUT": f"{2 * _longest_lake_query_s(env or {})}s",
        "TB_PG_SHM": f"{quarter}m",
    }


def _marker(text: str) -> dict[str, str]:
    for line in text.splitlines():
        if line.startswith(MARKER):
            return dict(p.split("=", 1) for p in line[len(MARKER) :].split() if "=" in p)
    return {}


def plan(env_text: str, compose: Path = COMPOSE) -> dict[str, str]:
    """What ``--write`` sets: the sized values, except one the operator set by hand (kept)."""
    env = _parse_env(env_text)
    ours = _marker(env_text)
    cap = size_mb(env.get("TB_MEM_DB") or compose_default("TB_MEM_DB", compose))
    return {k: v for k, v in settings(cap, env).items() if env.get(k) is None or ours.get(k) == env.get(k)}


def write(env_file: Path, values: Mapping[str, str]) -> None:
    text = env_file.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith(MARKER) and ln.split("=", 1)[0].strip() not in values]
    lines += [f"{k}={v}" for k, v in values.items()]
    recorded = {**_marker(text), **values}
    lines.append(f"{MARKER} " + " ".join(f"{k}={v}" for k, v in sorted(recorded.items())))
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check(env: Mapping[str, str], proc: Path = Path("/proc")) -> tuple[Literal["PASS", "WARN", "FAIL"], str]:
    """``(status, detail)`` for ``trialbox doctor``: FAIL when ``shared_buffers`` is PostgreSQL's default on a large
    host; WARN when it is the default on a smaller one."""
    try:
        line = next(
            ln for ln in (proc / "meminfo").read_text(encoding="utf-8").splitlines() if ln.startswith("MemTotal:")
        )
        host_gb = int(line.split()[1]) / 1048576
    except (OSError, StopIteration, ValueError, IndexError):
        return "WARN", f"the host's memory could not be read from {proc}/meminfo: shared_buffers was not judged"
    have = env.get("TB_PG_SHARED_BUFFERS") or POSTGRES_DEFAULTS["TB_PG_SHARED_BUFFERS"]
    default = size_mb(have) <= size_mb(POSTGRES_DEFAULTS["TB_PG_SHARED_BUFFERS"])
    if not default:
        return "PASS", f"shared_buffers {have} on a host of {host_gb:.0f} GB"
    fix = "re-run deploy/install.sh (it sizes PostgreSQL from TB_MEM_DB) or set TB_PG_SHARED_BUFFERS in deploy/.env"
    if host_gb >= LARGE_HOST_GB:
        return "FAIL", f"shared_buffers is PostgreSQL's default ({have}) on a host of {host_gb:.0f} GB: {fix}"
    return "WARN", f"shared_buffers is PostgreSQL's default ({have}) on a host of {host_gb:.0f} GB: {fix}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pgsize", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=ROOT / "deploy" / ".env")
    ap.add_argument("--write", action="store_true", help="write the settings into --env-file")
    a = ap.parse_args(argv)
    text = a.env_file.read_text(encoding="utf-8") if a.env_file.is_file() else ""
    values = plan(text)
    print("pgsize: " + (", ".join(f"{k}={v}" for k, v in values.items()) or "every setting set by hand"))
    if a.write and values:
        write(a.env_file, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
