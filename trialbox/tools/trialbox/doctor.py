"""``trialbox doctor`` for v4 (spec v4 §18.1, §9.5, §17.8; S1-16, HER-18, OPS-02, NFR-B9, ENG-16).

Each check returns PASS, WARN or FAIL; any FAIL makes the command exit 1, and a check that raises is a FAIL (fail
closed). Checks:

* ``topology``: ``TB_TOPOLOGY`` (A/B/C) and ``TB_ENV`` (DEV/TEST/VALIDATION/PRODUCTION) are valid;
* ``env_class_ceiling``: no configured data store (``settings.data_stores``), dataset (``eval/DATASETS.yaml``, in
  DEV and TEST) or ``TB_DATA_CLASS`` exceeds the environment ceiling of §17.8 (D3 data in DEV fails);
* ``routing_perimeter``: ``models/routing.yaml`` has no row, and no lookup, that sends D3/D4 outside the perimeter;
* ``gateway_only_model_reach``: the egress allowlist (``deploy/egress.py``) gives a model host to the gateway only;
* ``channel_engine``: ``channels.engine`` is valid and the fallback is native;
* ``hermes_pin``: ``hermes.lock`` pins tag + commit SHA + mirrored digest ≥ v0.21.6. FAIL when the engine is
  ``hermes``; WARN when Hermes is disabled (``native``), which is the install default (OPS-02);
* ``publish_gate``: the data platform has a current signed snapshot and the last gate decision is known.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import yaml

ROOT = Path(__file__).resolve().parents[2]
Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


@dataclass
class DoctorInputs:
    env: Mapping[str, str] = field(default_factory=dict)
    settings: Mapping[str, Any] = field(default_factory=dict)
    routing_path: Path = ROOT / "models" / "routing.yaml"
    datasets_path: Path = ROOT / "eval" / "DATASETS.yaml"
    dataplat_workdir: Path | None = None
    hermes_running_digest: str | None = None


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress_doctor", ROOT / "deploy" / "egress.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------ checks
def check_topology(inp: DoctorInputs) -> Check:
    from tb_common.policy.classes import Environment, Topology

    topo, env = inp.env.get("TB_TOPOLOGY", "A"), inp.env.get("TB_ENV", "DEV")
    if topo not in Topology.__members__:
        return Check("topology", "FAIL", f"TB_TOPOLOGY={topo!r} is not A, B or C")
    if env not in Environment.__members__:
        return Check("topology", "FAIL", f"TB_ENV={env!r} is not DEV, TEST, VALIDATION or PRODUCTION")
    return Check("topology", "PASS", f"topology {topo}, environment {env}")


def check_env_class_ceiling(inp: DoctorInputs) -> Check:
    from tb_common.policy.classes import ENV_CEILING, Environment
    from tb_contracts.dataclass import parse_class

    env = Environment(inp.env.get("TB_ENV", "DEV"))
    ceiling = ENV_CEILING[env]
    sources: list[tuple[str, object]] = []
    for store in inp.settings.get("data_stores") or []:
        sources.append((f"data store {store.get('name', '?')}", store.get("data_class")))
    if inp.env.get("TB_DATA_CLASS"):
        sources.append(("TB_DATA_CLASS", inp.env["TB_DATA_CLASS"]))
    if env in (Environment.DEV, Environment.TEST) and inp.datasets_path.exists():
        doc = yaml.safe_load(inp.datasets_path.read_text(encoding="utf-8")) or {}
        for name, d in sorted((doc.get("datasets") or {}).items()):
            sources.append((f"dataset {name}", (d or {}).get("data_class")))
    bad: list[str] = []
    for what, cls in sources:
        try:
            dc = parse_class(cls)
        except ValueError:
            bad.append(f"{what}: unknown or missing class {cls!r}")
            continue
        if dc.rank > ceiling.rank:
            bad.append(f"{what}: {dc.value} data in {env.value} (ceiling {ceiling.value})")
    if bad:
        return Check("env_class_ceiling", "FAIL", "; ".join(bad))
    return Check("env_class_ceiling", "PASS", f"{len(sources)} sources at or below {ceiling.value} in {env.value}")


def check_routing_perimeter(inp: DoctorInputs) -> Check:
    from gateway.policy import ALL_LABELS, Refusal, RoutingPolicy, violations
    from tb_common.policy.classes import Environment, Topology
    from tb_contracts.dataclass import DataClass

    policy = RoutingPolicy.load(inp.routing_path)
    problems = [v for v in violations(policy) if "D3/D4" in v or "dev endpoint" in v]
    roles = [*policy.roles, *(f"shadow:{r}" for r in policy.roles)]
    for role in roles:
        for label in ALL_LABELS:
            if label.data_class not in (DataClass.D3, DataClass.D4):
                continue
            for topo in Topology:
                for env in Environment:
                    for profile in policy.profiles or ("P-GB10",):
                        for opt_in in (False, True):
                            try:
                                _, cands = policy.candidates(
                                    role,
                                    label,
                                    topo,
                                    env,
                                    profile,
                                    cloud_opt_in=opt_in,
                                    flags=frozenset({"sponsor_consent"}),
                                )
                            except Refusal:
                                continue
                            for c in cands:
                                if c.endpoint.zone != "perimeter":
                                    problems.append(f"{role} {label.tag} {topo}/{env}: {c.alias}@{c.endpoint.name}")
    if problems:
        return Check("routing_perimeter", "FAIL", "D3/D4 route outside the perimeter: " + "; ".join(problems[:5]))
    return Check("routing_perimeter", "PASS", f"{policy.version}: 0 D3/D4 routes outside the perimeter")


def check_gateway_only_model_reach(inp: DoctorInputs) -> Check:
    eg = _egress()
    env = {k: v for k, v in inp.env.items()}
    try:
        allows = eg.allowlist(env, inp.routing_path)
    except SystemExit as e:
        return Check("gateway_only_model_reach", "FAIL", str(e))
    hosts = eg.model_hosts(env, inp.routing_path)
    leaks = [f"{a.service} -> {a.host}:{a.port}" for a in allows if a.host in hosts and a.service != eg.GATEWAY]
    if leaks:
        return Check(
            "gateway_only_model_reach", "FAIL", "model host reachable outside the gateway: " + ", ".join(leaks)
        )
    n = sum(1 for a in allows if a.service == eg.GATEWAY)
    return Check("gateway_only_model_reach", "PASS", f"only {eg.GATEWAY} reaches model hosts ({n} egress rules)")


def check_channel_engine(inp: DoctorInputs) -> Check:
    from channels.config import ChannelsConfig, ChannelsConfigError

    try:
        cfg = ChannelsConfig.from_settings(inp.settings)
    except ChannelsConfigError as e:
        return Check("channel_engine", "FAIL", str(e))
    return Check("channel_engine", "PASS", f"engine {cfg.engine}, fallback {cfg.fallback}, Teams {cfg.teams_mode}")


def check_hermes_pin(inp: DoctorInputs) -> Check:
    from channels.config import ChannelsConfig, ChannelsConfigError

    from integrations.hermes.lock import HermesLock, pin_problems

    try:
        cfg = ChannelsConfig.from_settings(inp.settings)
    except ChannelsConfigError as e:
        return Check("hermes_pin", "FAIL", f"channels config invalid: {e}")
    problems = pin_problems(HermesLock.load(cfg.hermes_lock), running_digest=inp.hermes_running_digest)
    if not problems:
        return Check("hermes_pin", "PASS", "hermes.lock pins tag, commit SHA and mirrored digest")
    if cfg.engine == "hermes":
        return Check("hermes_pin", "FAIL", "Hermes must not start: " + "; ".join(problems))
    return Check("hermes_pin", "WARN", "Hermes disabled (engine native); pin incomplete: " + "; ".join(problems[:3]))


def check_publish_gate(inp: DoctorInputs) -> Check:
    wd = inp.dataplat_workdir
    if wd is None:
        return Check("publish_gate", "WARN", "no data-platform workdir configured (TB_DATAPLAT_DIR)")
    pointer = wd / "l5" / "CURRENT.json"
    gates = sorted((wd / "gates").glob("*.json")) if (wd / "gates").is_dir() else []
    last = json.loads(gates[-1].read_text(encoding="utf-8")) if gates else None
    if not pointer.exists():
        outcome = last.get("outcome") if last else "none"
        return Check("publish_gate", "FAIL", f"no current snapshot pinned (last gate outcome: {outcome})")
    cur = json.loads(pointer.read_text(encoding="utf-8"))
    if last is None:
        return Check("publish_gate", "WARN", f"snapshot {cur.get('snapshot_id')} pinned but no gate record found")
    if last.get("outcome") == "HOLD":
        reasons = ", ".join(last.get("blocking_reasons") or [])
        return Check("publish_gate", "WARN", f"last cycle held ({reasons}); serving stays on {cur.get('snapshot_id')}")
    return Check("publish_gate", "PASS", f"snapshot {cur.get('snapshot_id')} current; last gate {last.get('outcome')}")


CHECKS: tuple[Callable[[DoctorInputs], Check], ...] = (
    check_topology,
    check_env_class_ceiling,
    check_routing_perimeter,
    check_gateway_only_model_reach,
    check_channel_engine,
    check_hermes_pin,
    check_publish_gate,
)


def run(inp: DoctorInputs) -> list[Check]:
    out: list[Check] = []
    for fn in CHECKS:
        name = fn.__name__.removeprefix("check_")
        try:
            out.append(fn(inp))
        except Exception as e:  # fail closed: a check that cannot run is a failure
            out.append(Check(name, "FAIL", f"check error: {type(e).__name__}: {e}"))
    return out


def ok(checks: list[Check]) -> bool:
    return all(c.status != "FAIL" for c in checks)


def inputs_from(
    *, env_file: Path | None, settings: Path | None, routing: Path | None, dataplat: Path | None
) -> DoctorInputs:
    env: dict[str, str] = {}
    if env_file is not None and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update(
        {k: v for k, v in os.environ.items() if k.startswith("TB_") or k in ("CLOUD_LLM_BASE_URL", "EGRESS_EXTRA")}
    )
    doc: dict[str, Any] = {}
    if settings is not None:
        doc = yaml.safe_load(settings.read_text(encoding="utf-8")) or {}
    wd = dataplat or (Path(env["TB_DATAPLAT_DIR"]) if env.get("TB_DATAPLAT_DIR") else None)
    return DoctorInputs(
        env=env, settings=doc, routing_path=routing or ROOT / "models" / "routing.yaml", dataplat_workdir=wd
    )


def render(checks: list[Check]) -> str:
    lines = [f"{c.status:<5} {c.name:<26} {c.detail}" for c in checks]
    fails = sum(c.status == "FAIL" for c in checks)
    lines.append("---")
    lines.append("doctor passed" if not fails else f"{fails} check(s) failed")
    return "\n".join(lines)
