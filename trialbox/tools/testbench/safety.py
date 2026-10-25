"""Start-up and per-dataset refusals of the Test Bench (docs/HANDOFF.md §5, spec v4 §17.8, ENG-16).

* :func:`bench_environment` accepts ``TB_ENV`` = ``DEV`` or ``TEST`` only; anything else (unset included) refuses.
* :func:`check_no_patient_store` refuses when the environment points at a store that can hold D3/D4 data (a lake,
  the orchestrator or mail state, a FHIR server, a vault or a Postgres DSN), or when ``TB_DATA_CLASS`` is above D0.
* :func:`check_bind_host` refuses a non-loopback bind address unless the bench runs inside its dev container.

Every refusal raises :class:`tb_common.policy.classes.PolicyError`; class checks go through
:func:`tb_common.policy.classes.check_env`, the single environment-ceiling rule.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping

from tb_common.policy.classes import Environment, PolicyError, check_env
from tb_contracts.dataclass import ClassLabel, parse_class

ALLOWED_ENVS = (Environment.DEV, Environment.TEST)
# environment variables that name a store able to hold patient-level (D3/D4) data
PATIENT_STORE_VARS = (
    "TB_LAKE_DIR",
    "TB_ADAPTER_LAKE",
    "TB_ORCH_DIR",
    "TB_MAIL_DIR",
    "TB_SOURCE_PATH",
    "TB_TRACESTORE_PATH",
    "TB_FHIR_URL",
    "FHIR_BASE_URL",
    "TB_VAULT_URL",
    "TB_VAULT_DIR",
    "TB_PG_DSN",
    "DATABASE_URL",
    "HIS_DSN",
)
IN_CONTAINER_VAR = "TB_TESTBENCH_IN_CONTAINER"


def bench_environment(env: Mapping[str, str] | None = None) -> Environment:
    e = os.environ if env is None else env
    raw = e.get("TB_ENV", "")
    if raw not in {x.value for x in ALLOWED_ENVS}:
        raise PolicyError(f"the Test Bench runs only with TB_ENV=DEV or TB_ENV=TEST (got {raw or 'unset'!r})")
    return Environment(raw)


def check_label(data_class: str, env: Environment) -> ClassLabel:
    """Parse a dataset class strictly and apply the environment ceiling (D0 in DEV and TEST)."""
    try:
        label = ClassLabel(data_class=parse_class(data_class))
    except ValueError as exc:
        raise PolicyError(str(exc)) from exc
    check_env(label, env)
    return label


def check_no_patient_store(env: Mapping[str, str] | None = None, environment: Environment = Environment.DEV) -> None:
    e = os.environ if env is None else env
    configured = [k for k in PATIENT_STORE_VARS if e.get(k)]
    if configured:
        raise PolicyError(f"the Test Bench refuses to start while a D3/D4 store is configured: {', '.join(configured)}")
    if e.get("TB_DATA_CLASS"):
        check_label(e["TB_DATA_CLASS"], environment)


def check_bind_host(host: str, env: Mapping[str, str] | None = None) -> None:
    e = os.environ if env is None else env
    if host == "localhost":
        return
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback and e.get(IN_CONTAINER_VAR) != "1":
        raise PolicyError(f"the Test Bench binds 127.0.0.1 only (got {host!r}); see docs/HANDOFF.md §5")


def startup_checks(env: Mapping[str, str] | None = None) -> Environment:
    environment = bench_environment(env)
    check_no_patient_store(env, environment)
    return environment


__all__ = [
    "ALLOWED_ENVS",
    "PATIENT_STORE_VARS",
    "bench_environment",
    "check_bind_host",
    "check_label",
    "check_no_patient_store",
    "startup_checks",
]
