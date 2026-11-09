"""``trialbox doctor`` for v4 (spec v4 §18.1, §9.5, §17.8; S1-16, HER-18, OPS-02, NFR-B9, ENG-16).

Each check returns PASS, WARN or FAIL; any FAIL makes the command exit 1, and a check that raises is a FAIL (fail
closed). Checks:

* ``topology``: ``TB_TOPOLOGY`` (A/B/C) and ``TB_ENV`` (DEV/TEST/VALIDATION/PRODUCTION) are valid;
* ``env_class_ceiling``: no configured data store (``settings.data_stores``), dataset (``eval/DATASETS.yaml``, in
  DEV and TEST) or ``TB_DATA_CLASS`` exceeds the environment ceiling of §17.8 (D3 data in DEV fails);
* ``routing_perimeter``: ``models/routing.yaml`` has no row, and no lookup, that sends D3/D4 outside the perimeter;
* ``gateway_only_model_reach``: the egress allowlist (``deploy/egress.py``) gives a model host to the gateway only;
* ``channel_engine``: ``channels.engine`` is valid (native is the only engine, D-121);
* ``secure_cookie``: the console session cookie is marked Secure (``TB_CONSOLE_SECURE_COOKIE=1``). FAIL in
  PRODUCTION and VALIDATION, WARN elsewhere (a DEV/TEST box may serve plain http on localhost; D-121);
* ``publish_gate``: the data platform has a current signed snapshot and the last gate decision is known;
* ``note_block``: ``TB_NOTE_BLOCK=both_agree`` (the default, D-95) needs a verifier build (``TB_GATEWAY_VERIFIER_MODEL``
  or ``LLM_VERIFIER_BASE_URL``) and ``TB_SCREEN_JUDGE`` other than ``single``; otherwise the box runs single-model
  and SCREEN falls back to ``never`` (a note answer may send a patient to review, never out: D-97). WARN in
  DEV/TEST, FAIL in VALIDATION/PRODUCTION, since the site then believes two models agree when one did;
* ``registry_pins``: the committed registry with the site override (``TB_REGISTRY_OVERRIDE``, default
  ``deploy/site/registry.site.yaml``) loads; lists the site-pinned builds. WARN when no model build is pinned
  (production routes nothing) or, in VALIDATION/PRODUCTION, when no pinned build is ``champion``.

``--live`` adds one check that talks to the model servers, so it runs where the gateway's network is (install.sh
runs it in a one-off container on ``trialbox-model-net``; ``--serving`` runs it alone):

* ``serving`` (D-177): for each on-box endpoint (``models/routing.yaml``, zone ``perimeter``) that a pinned build is
  served on, ``GET <url>/models`` with the endpoint's key (``api_key_env``, ``TB_LLM_API_KEY``) must answer 200 and list
  every pinned served name, and the same call without the key must be refused. FAIL when a server is down, refuses
  the key (401/403) or does not serve a pinned name (vLLM would answer every call 404); a server that runs without a
  key, or a box with no key, is a FAIL in VALIDATION and PRODUCTION and a WARN elsewhere. WARN when nothing local is
  pinned (nothing to check).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
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
    return Check("channel_engine", "PASS", f"engine {cfg.engine}")


def check_secure_cookie(inp: DoctorInputs) -> Check:
    on = inp.env.get("TB_CONSOLE_SECURE_COOKIE", "0").lower() in ("1", "true")
    if on:
        return Check("secure_cookie", "PASS", "console session cookie is Secure (https only)")
    env = inp.env.get("TB_ENV", "DEV")
    status: Status = "FAIL" if env in ("VALIDATION", "PRODUCTION") else "WARN"
    why = f"TB_CONSOLE_SECURE_COOKIE is off in {env}: the session cookie can travel on http"
    return Check("secure_cookie", status, why)


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


def _override(inp: DoctorInputs) -> Path:
    raw = inp.env.get("TB_REGISTRY_OVERRIDE")
    return Path(raw) if raw else ROOT / "deploy" / "site" / "registry.site.yaml"


def check_registry_pins(inp: DoctorInputs) -> Check:
    from registry.registry import DEFAULT_PATH, Registry, Status

    override = _override(inp)
    try:
        reg = Registry.load(DEFAULT_PATH, override)
    except (ValueError, OSError, yaml.YAMLError) as e:
        return Check("registry_pins", "FAIL", f"registry with site override {override} does not load: {e}")
    pinned = [b for b in reg.builds if b.pinned and b.serving != "stub"]
    if not pinned:
        where = f"override {override}" if override.is_file() else f"no override at {override}"
        return Check("registry_pins", "WARN", f"no model build pinned ({where}): only the DEV/TEST stub routes")
    names = ", ".join(f"{b.build_id} ({b.status.value}, {b.sha256[:12] if b.sha256 else ''})" for b in pinned)
    env = inp.env.get("TB_ENV", "DEV")
    if env in ("VALIDATION", "PRODUCTION") and not any(b.status == Status.CHAMPION for b in pinned):
        return Check("registry_pins", "WARN", f"pinned: {names}; none is champion, so {env} roles route nothing")
    return Check("registry_pins", "PASS", f"{reg.version}: pinned {names}")


def check_note_block(inp: DoctorInputs) -> Check:
    policy = (inp.env.get("TB_NOTE_BLOCK") or "both_agree").strip().lower()
    if policy == "never":
        return Check("note_block", "PASS", "TB_NOTE_BLOCK=never: note answers route to review, never exclude")
    if policy != "both_agree":
        return Check("note_block", "FAIL", f"TB_NOTE_BLOCK={policy!r} is not one of both_agree, never")
    mode = (inp.env.get("TB_SCREEN_JUDGE") or "agreement").strip().lower()
    gw = bool(inp.env.get("TB_GATEWAY_VERIFIER_MODEL")) and bool(
        inp.env.get("TB_GATEWAY_VERIFIER_URL") or inp.env.get("TB_GATEWAY_URL")
    )
    direct = bool(inp.env.get("LLM_VERIFIER_BASE_URL"))
    if mode != "single" and (gw or direct):
        via = "gateway verifier build" if gw else "LLM_VERIFIER_BASE_URL"
        return Check("note_block", "PASS", f"both_agree with a verifier ({via}): two models must agree to exclude")
    why = "TB_SCREEN_JUDGE=single" if mode == "single" else "no verifier configured"
    env = inp.env.get("TB_ENV", "DEV")
    status: Status = "FAIL" if env in ("VALIDATION", "PRODUCTION") else "WARN"
    return Check(
        "note_block",
        status,
        f"TB_NOTE_BLOCK=both_agree but {why}: SCREEN runs single-model and falls back to never-exclude "
        f"(D-97); set TB_NOTE_BLOCK=never on purpose or add a verifier build",
    )


def _get_models(url: str, key: str, timeout: float = 10.0) -> tuple[int | None, Any]:
    """(HTTP status, JSON body or error text); status None when the server cannot be reached."""
    req = urllib.request.Request(f"{url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except (OSError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"


def check_serving(inp: DoctorInputs) -> Check:
    from gateway.policy import RoutingPolicy
    from registry.registry import DEFAULT_PATH, Registry

    env = dict(inp.env)
    strict = env.get("TB_ENV", "DEV") in ("VALIDATION", "PRODUCTION")
    reg = Registry.load(DEFAULT_PATH, _override(inp))
    policy = RoutingPolicy.load(inp.routing_path)
    want: dict[str, list[tuple[str, str]]] = {}
    for b in reg.builds:
        if not b.pinned or b.serving in ("stub", "hosted"):
            continue
        for ep_name, name in sorted(b.served.items()):
            ep = policy.endpoints.get(ep_name)
            if name and ep is not None and ep.zone == "perimeter":
                want.setdefault(ep_name, []).append((b.build_id, name))
    if not want:
        return Check("serving", "WARN", "no pinned on-box build: no model server to check")
    fails: list[str] = []
    warns: list[str] = []
    good: list[str] = []
    for ep_name, builds in sorted(want.items()):
        ep = policy.endpoints[ep_name]
        url = ep.url(env)
        key_var = ep.api_key_env or "api_key_env (not set in routing.yaml)"
        key = env.get(ep.api_key_env, "") if ep.api_key_env else ""
        if not key:
            (fails if strict else warns).append(
                f"{ep_name}: no key, {key_var} is empty: anyone on model-net may call it"
            )
        status, doc = _get_models(url, key)
        if status is None:
            fails.append(f"{ep_name} ({url}) not reachable: {doc}")
            continue
        if status in (401, 403):
            why = f"{key_var} is missing or is not the server's key (deploy/.env; restart the gateway and the server)"
            fails.append(f"{ep_name}: the model server refused the key (HTTP {status}): {why}")
            continue
        if status != 200 or not isinstance(doc, dict):
            fails.append(f"{ep_name}: GET {url}/models answered HTTP {status}")
            continue
        served = [str(m.get("id")) for m in doc.get("data") or [] if isinstance(m, dict)]
        for build, name in builds:
            if name not in served:
                fix = "restore JUDGE_MODEL / VERIFIER_MODEL in deploy/.env or re-pin (tools/pin_model.py, RUNBOOK §8)"
                fails.append(
                    f"{ep_name}: {build} is pinned to the served name {name!r} but the server serves {served}, "
                    f"so every call would be refused 404: {fix}"
                )
        if key and _get_models(url, "")[0] == 200:
            (fails if strict else warns).append(f"{ep_name}: the server answers without the key (VLLM_API_KEY unset)")
        good.append(f"{ep_name} serves {', '.join(repr(n) for _, n in builds)}")
    if fails:
        return Check("serving", "FAIL", "; ".join(fails))
    if warns:
        return Check("serving", "WARN", "; ".join(warns))
    return Check("serving", "PASS", "; ".join(good) + "; key required")


CHECKS: tuple[Callable[[DoctorInputs], Check], ...] = (
    check_topology,
    check_env_class_ceiling,
    check_routing_perimeter,
    check_gateway_only_model_reach,
    check_channel_engine,
    check_secure_cookie,
    check_publish_gate,
    check_note_block,
    check_registry_pins,
)


LIVE: tuple[Callable[[DoctorInputs], Check], ...] = (check_serving,)


def run(inp: DoctorInputs, checks: tuple[Callable[[DoctorInputs], Check], ...] = CHECKS) -> list[Check]:
    out: list[Check] = []
    for fn in checks:
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
    keep = ("CLOUD_LLM_BASE_URL", "EGRESS_EXTRA", "COMPOSE_FILE")
    env.update({k: v for k, v in os.environ.items() if k.startswith("TB_") or k in keep})
    if env.get("COMPOSE_FILE") and not env.get("TB_GATEWAY_URL"):
        # an installed box's deploy/.env (install.sh writes COMPOSE_FILE): compose itself gives the orchestrator this
        # gateway address, so note_block judges the box as it runs (found by the box rehearsal, D-176)
        env["TB_GATEWAY_URL"] = "http://gateway:8020/v1"
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
