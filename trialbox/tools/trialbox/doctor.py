"""``trialbox doctor`` for v4 (spec v4 §18.1, §9.5, §17.8; S1-16, HER-18, OPS-02, NFR-B9, ENG-16).

Each check returns PASS, WARN or FAIL; any FAIL makes the command exit 1, and a check that raises is a FAIL (fail
closed). Checks:

* ``topology``: ``TB_TOPOLOGY`` (A/B/C) and ``TB_ENV`` (DEV/TEST/VALIDATION/PRODUCTION) are valid;
* ``env_class_ceiling``: no configured data store (``settings.data_stores``), dataset (``eval/DATASETS.yaml``, in
  DEV and TEST) or ``TB_DATA_CLASS`` exceeds the environment ceiling of §17.8 (D3 data in DEV fails);
* ``routing_perimeter``: ``models/routing.yaml`` has no row, and no lookup, that sends D3/D4 outside the perimeter;
* ``gateway_only_model_reach``: the egress allowlist (``deploy/egress.py``) gives a model host to the gateway only;
* ``channel_engine``: ``channels.engine`` is valid (native is the only engine, D-121);
* ``secure_cookie``: the console session cookie is marked Secure (``TB_CONSOLE_SECURE_COOKIE=1``, or unset or empty in
  PRODUCTION, the console's default since D-192). FAIL in
  PRODUCTION and VALIDATION, WARN elsewhere (a DEV/TEST box may serve plain http on localhost; D-121);
* ``publish_gate``: the data platform has a current signed snapshot and the last gate decision is known;
* ``note_block``: ``TB_NOTE_BLOCK=both_agree`` (the default, D-95) needs a verifier build (``TB_GATEWAY_VERIFIER_MODEL``
  or ``LLM_VERIFIER_BASE_URL``) and ``TB_SCREEN_JUDGE`` other than ``single``; otherwise the box runs single-model
  and SCREEN falls back to ``never`` (a note answer may send a patient to review, never out: D-97). WARN in
  DEV/TEST, FAIL in VALIDATION/PRODUCTION, since the site then believes two models agree when one did;
* ``judge_route`` (T-601; D-142 "not done"): the gateway built from this box's settings (routing file, registry with
  the site pins, ``TB_ENV``, ``TB_TOPOLOGY``, ``TB_PROFILE``, no step confirmer, as compose runs it) takes one
  synthetic judge call as the orchestrator sends it (``TB_GATEWAY_MODEL``, ``TB_DATA_CLASS`` or D3), and one verifier
  call when ``TB_GATEWAY_VERIFIER_MODEL`` is set, against a stand-in model server. FAIL in VALIDATION and PRODUCTION
  (WARN in DEV and TEST) when it would refuse either (no route, an unpinned or non-champion build, a D3 call with
  no step outside the box policy) or another alias answers: the box would screen no note. PASS when the judge does
  not use the gateway;
* ``registry_pins``: the committed registry with the site override (``TB_REGISTRY_OVERRIDE``, default
  ``deploy/site/registry.site.yaml``) loads; lists the site-pinned builds. WARN when no model build is pinned
  (production routes nothing) or, in VALIDATION/PRODUCTION, when no pinned build is ``champion``;
* ``site_tz`` (D-315; STD-016, OPS-056): the site's time zone is one setting. ``site.tz`` (settings.yaml), ``TB_TZ``
  (the containers' zone), the ``tz`` of the data source mapping (``data_source.mapping``) and the host's zone (cron
  runs the backup and the log jobs in it; ``TB_HOST_TZ`` when doctor runs in a container) must name the same zone.
  FAIL when none is set, one is not a zone, or two differ; the host is not compared when it cannot be read;
* ``flags``: a seed variable such as ``TB_LAKE_SOURCE`` that disagrees with its feature flag is ignored since the
  box's first start (T-008, D-207): WARN, naming the flag's value and where to change it;
* ``backup`` (D-274; CR-058, OPS-028, OPS-048): read from the deploy folder of ``--env-file``. FAIL in PRODUCTION
  (WARN elsewhere) when there is no target, no off-box target, no alert route (``TB_BACKUP_ALERT_CMD`` or
  ``TB_BACKUP_MAILTO``), no ``/etc/cron.d/trialbox-backup`` on a host with ``/etc/cron.d``, no good backup or one
  older than ``TB_BACKUP_MAX_AGE_HOURS`` (``backup-status``'s rules); WARN in PRODUCTION when WAL archiving is off;
  on a platform it passes and points to ``backup_target``;
* ``site_key`` (T-612, DATA-004): ``site_hmac.key`` is in the secrets folder (``TB_SECRETS_DIR``) and its fingerprint
  is the one recorded in the lake (``site_key.json``) and in the pid map. FAIL when it is missing or another key (the
  ingest then refuses every night); WARN when the folder is not on this host. Prints the fingerprint, never the key;
* ``key_custody`` (T-210b, CR-041, D-347): the site keys are wrapped under the KEK (``tb_common.kek``). FAIL when a key
  is both plain and wrapped, a wrapped key has no ``kek.json`` or names another KEK, the KEK file is in the secrets
  folder or is not this box's KEK, or (in VALIDATION and PRODUCTION) a site key is a plain file; WARN for a plain key
  in DEV/TEST and when the keys are wrapped but the KEK is not unsealed where doctor runs. Opens no key.
* ``clock`` (T-211a, OPS-055, REG-026): the audit chain's times need a true clock. FAIL when the clock is more than
  ``TB_CLOCK_MAX_SKEW_S`` (default 60) seconds from the site's time server (``TB_NTP_SERVER``, one SNTP exchange); in
  VALIDATION and PRODUCTION also FAIL when the kernel clock is not NTP-synchronised, when the time server does not
  answer, or when neither can be read. WARN for those in DEV and TEST.

``--two-device`` adds one check, for a device of the GB10 two-device form (T-214, D-373; ``deploy/two-device/``):

* ``two_device``: ``TB_LINK_ROLE`` (spark or workstation) names this device; its rendered compose (``--compose-config``,
  else ``docker compose config --format json`` of the device's services in the deploy folder) runs only what the GB10
  profile (``deploy/gb10-profile.yaml``) puts on it, the link is the only port the Spark publishes and only on the
  link address (a gateway or any listener on 0.0.0.0 there is a FAIL), the link has its certificates, its peer and
  its route alias, and the Spark's memory limits are the profile's. WARN when the driver hold's re-test is past due.

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
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import yaml

ROOT = Path(__file__).resolve().parents[2]
Status = Literal["PASS", "WARN", "FAIL", "SKIP"]  # SKIP: doctor --platform --no-gpu (D-211)


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
    ingest_lake: Path | None = None  # T-659b: the adapter's lake folder (its CURRENT and gates/), when given
    host_tz: str | None = None  # the host's zone; None: TB_HOST_TZ, else read from /etc (check site_tz)
    platform: bool = False  # doctor --platform: pods on a cluster, no host cron, so no host zone to compare
    deploy: Path | None = None  # the deploy folder (from --env-file): the backup record and the cron file (D-274)
    cron_dir: Path = Path("/etc/cron.d")
    compose_config: Mapping[str, Any] | None = None  # doctor --two-device: the device's rendered compose (D-373)


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
    """The console's own rule (``console.identity.secure_cookie_default``, D-192): an explicit value wins; unset or
    empty means Secure in PRODUCTION (the base compose file passes it empty) and off elsewhere."""
    env = inp.env.get("TB_ENV", "DEV")
    raw = (inp.env.get("TB_CONSOLE_SECURE_COOKIE") or "").strip().lower()
    on = raw in ("1", "true", "on", "yes") if raw else env.strip().upper() == "PRODUCTION"
    if on:
        why = "console session cookie is Secure (https only)" + ("" if raw else ", the PRODUCTION default")
        return Check("secure_cookie", "PASS", why)
    status: Status = "FAIL" if env in ("VALIDATION", "PRODUCTION") else "WARN"
    why = f"TB_CONSOLE_SECURE_COOKIE is off in {env}: the session cookie can travel on http"
    return Check("secure_cookie", status, why)


def check_publish_gate(inp: DoctorInputs) -> Check:
    """T-659b (D-370): the adapter's lake: its ``CURRENT`` and the newest of its one-per-night gate records
    (``gates/<night>.json``)."""
    lake = inp.ingest_lake
    if lake is None:
        return Check("publish_gate", "WARN", "no ingest lake given (--lake-dir or TB_LAKE_DIR)")
    pointer = lake / "CURRENT"
    gates = sorted((lake / "gates").glob("*.json")) if (lake / "gates").is_dir() else []
    last = json.loads(gates[-1].read_text(encoding="utf-8")) if gates else None
    cur = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else ""
    if not cur:
        outcome = last.get("outcome") if last else "none"
        return Check("publish_gate", "FAIL", f"no current snapshot (last gate outcome: {outcome})")
    if last is None:
        return Check("publish_gate", "WARN", f"snapshot {cur} current but no gate record found")
    if last.get("outcome") == "HOLD":
        reasons = ", ".join(last.get("blocking_reasons") or [])
        return Check("publish_gate", "WARN", f"last night held ({reasons}); the box stays on {cur}")
    return Check("publish_gate", "PASS", f"snapshot {cur} current; last gate {last.get('outcome')}")


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


def verifier_is_the_judge(env: Mapping[str, str]) -> str | None:
    """Why the configured verifier is the judge's own model, read from the settings alone (the running box checks
    the served models too: ``tb_common.pair.same_model`` and ``combine``); None when the names differ.

    The orchestrator builds the judge from ``TB_GATEWAY_URL`` / ``TB_GATEWAY_MODEL`` (else ``LLM_BASE_URL`` /
    ``LLM_MODEL``) and the verifier from ``TB_GATEWAY_VERIFIER_MODEL`` (else ``LLM_VERIFIER_BASE_URL`` /
    ``LLM_VERIFIER_MODEL``, which falls back to ``LLM_MODEL``)."""

    def key(v: str | None) -> str:
        return " ".join((v or "").split()).casefold()

    def url(v: str | None) -> str:
        return (v or "").strip().rstrip("/").casefold()

    from tb_common.pair import gateway_default_alias

    judge_gw = url(env.get("TB_GATEWAY_URL"))
    v_alias = key(env.get("TB_GATEWAY_VERIFIER_MODEL"))
    v_gw = url(env.get("TB_GATEWAY_VERIFIER_URL")) or judge_gw
    if v_alias and v_gw:
        if not judge_gw:  # the judge goes straight to an endpoint: the two cannot be told apart (D-276, F-02)
            return "the verifier goes through the gateway and the judge does not, so they cannot be told apart"
        if judge_gw != v_gw:
            return None
        default = gateway_default_alias(env.get("TB_ENV", "DEV"))
        j_alias = key(env.get("TB_GATEWAY_MODEL")) or default
        if j_alias == v_alias:
            return f"TB_GATEWAY_VERIFIER_MODEL={v_alias} is the build the judge gets (TB_GATEWAY_MODEL, or the default)"
        return None
    if env.get("LLM_VERIFIER_BASE_URL"):
        if judge_gw:
            return "the judge goes through the gateway and the verifier (LLM_VERIFIER_BASE_URL) does not"
        v_model = key(env.get("LLM_VERIFIER_MODEL"))
        if not v_model:
            return "LLM_VERIFIER_MODEL is not set, so the verifier asks for the judge's model (LLM_MODEL)"
        if v_model == key(env.get("LLM_MODEL")):
            return f"LLM_VERIFIER_MODEL={v_model} is the judge's model (LLM_MODEL)"
    return None


def _judge_answer(served: str) -> dict[str, Any]:
    """What a model server sends back to a judge call: the served name it was asked under and a valid judge answer."""
    content = json.dumps({"verdict": "unknown", "confidence": 0.0, "quote": None, "quote_date": None, "reason": "-"})
    return {
        "model": served,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def check_judge_route(inp: DoctorInputs) -> Check:
    """T-601 (D-142 "not done"): put one synthetic judge call, and one verifier call when a gateway verifier is named,
    to the gateway built from this box's settings (routing file, registry with the site pins, environment, topology,
    profile, no step confirmer as compose runs it), with a stand-in model server that answers under the pinned served
    name. FAIL when the gateway refuses either call or another alias answers: the box would then screen no note."""
    import httpx
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from guard.guard import Guard
    from registry.registry import DEFAULT_PATH, Registry
    from tb_common.audit import AuditLog
    from tb_common.config import environment_name
    from tb_common.llm import load_prompt, render
    from tb_contracts import inline_schema
    from tb_llm import GatewayClient, GatewayError, GatewayRefused, json_schema_format
    from tb_llm.client import v1_labels

    url = (inp.env.get("TB_GATEWAY_URL") or "").strip()
    if not url:
        return Check("judge_route", "PASS", "the judge does not go through the gateway (no TB_GATEWAY_URL)")
    env = dict(inp.env)
    # FAIL where the box screens real notes; WARN in DEV and TEST (synthetic data, a box being set up)
    bad: Status = "FAIL" if env.get("TB_ENV", "DEV") in ("VALIDATION", "PRODUCTION") else "WARN"
    with tempfile.TemporaryDirectory(prefix="tb-doctor-") as tmp:

        def upstream(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_judge_answer(str(json.loads(req.content).get("model") or "")))

        gw = Gateway(
            RoutingPolicy.load(inp.routing_path),
            Registry.load(Path(env.get("TB_REGISTRY_PATH") or DEFAULT_PATH), _override(inp)),
            AuditLog(Path(tmp) / "audit"),
            GatewayConfig.from_env(env),
            http=httpx.Client(transport=httpx.MockTransport(upstream)),
            guard=Guard(None),
            env=env,
        )

        def gateway(req: httpx.Request) -> httpx.Response:
            res = gw.chat(dict(req.headers), json.loads(req.content))
            return httpx.Response(res.status, json=res.body, headers=res.headers)

        http = httpx.Client(transport=httpx.MockTransport(gateway))
        p = load_prompt("judge", environment_name(env))  # the version this box's environment serves (D-359)
        labels = v1_labels(
            p.meta.id,
            p.meta.version,
            phi=bool(p.meta.phi),
            study_id="doctor",
            data_class=env.get("TB_DATA_CLASS") or ("D3" if p.meta.phi else "D1"),
            prompt_sha=p.sha256,
        )
        labels = replace(labels, step_id=env.get("TB_STEP_ID", ""))
        variables = {"criterion_text": "x", "note_question": "x?", "index_date": "2026-01-01", "excerpts": []}
        asks = [("judge", env.get("TB_GATEWAY_MODEL") or "")]
        v_alias = (env.get("TB_GATEWAY_VERIFIER_MODEL") or "").strip()
        if v_alias:
            asks.append(("verifier", v_alias))
        got: list[str] = []
        for who, alias in asks:
            client = GatewayClient("http://gateway/v1", "orchestrator", http=http)  # the judge's caller
            try:
                res = client.chat(
                    render(p, variables),
                    labels,
                    response_format=json_schema_format(p.meta.id, inline_schema(p.meta.output_schema)),
                    max_tokens=p.meta.max_tokens,
                    model=alias or None,
                )
            except GatewayRefused as e:
                return Check(
                    "judge_route",
                    bad,
                    f"the gateway would refuse the {who} ({labels.data_class}, role {labels.role}"
                    f"{', ' + alias if alias else ''}): {e.reason}: {str(e)[:300]}",
                )
            except GatewayError as e:
                return Check("judge_route", bad, f"the {who}'s call through the gateway fails: {str(e)[:300]}")
            got.append(f"{who} {res.alias} ({res.payload.get('tb', {}).get('build_id', '?')})")
    return Check("judge_route", "PASS", f"the gateway takes the {labels.data_class} judge call: " + "; ".join(got))


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
        one = verifier_is_the_judge(inp.env)
        if one:  # D-276 (review S-2): a verifier that is the judge again agrees with it every time
            return Check(
                "note_block",
                "FAIL",
                f"TB_NOTE_BLOCK=both_agree but the verifier is not a second model: {one}. The box treats this as "
                f"one model and never excludes on a note answer; name a different verifier model",
            )
        env = inp.env.get("TB_ENV", "DEV")
        if not gw and env in ("VALIDATION", "PRODUCTION"):  # D-276 (review F-02): fail closed on the direct path
            return Check(
                "note_block",
                "FAIL",
                "TB_NOTE_BLOCK=both_agree with a direct verifier (LLM_VERIFIER_BASE_URL): which weights each endpoint "
                "serves is known only from its /models at start, so this check cannot confirm two models. Use the "
                "gateway verifier build (TB_GATEWAY_VERIFIER_MODEL), whose build hash is compared on every answer",
            )
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, never followed: the model key must not travel to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _get_models(url: str, key: str, timeout: float = 10.0) -> tuple[int | None, Any]:
    """(HTTP status, JSON body or error text); status None when the server cannot be reached."""
    req = urllib.request.Request(f"{url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except (OSError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"


# vLLM routes outside /v1 that answer without the key (vLLM checks it on /v1, /v2, /inference, /cohere only)
UNKEYED_PROBES = ("/invocations", "/tokenize")


def _post_open(url: str, timeout: float = 10.0) -> int | None:
    """HTTP status of an empty-keyed POST (a tiny chat body), None when unreachable. Redirects are answers."""
    body = json.dumps({"messages": [{"role": "user", "content": "doctor probe"}], "prompt": "doctor probe"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except (OSError, ValueError):
        return None


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
        root = url.rstrip("/").removesuffix("/v1")
        for path in UNKEYED_PROBES:  # vLLM answers these with no key at all: only model-guard keeps them away
            st = _post_open(root + path)
            if st is not None and st not in (401, 403, 404, 405, 501):
                (fails if strict else warns).append(
                    f"{ep_name}: POST {path} without the key answered HTTP {st}: the model is reachable without "
                    "the key (model-guard missing in front of the server? docker-compose.yml model-guard, D-177)"
                )
        good.append(f"{ep_name} serves {', '.join(repr(n) for _, n in builds)}")
    if fails:
        return Check("serving", "FAIL", "; ".join(fails))
    if warns:
        return Check("serving", "WARN", "; ".join(warns))
    return Check("serving", "PASS", "; ".join(good) + "; key required")


MAPPING_ROOT = ROOT / "services" / "adapter"
ETC = Path("/etc")


def _host_zone(inp: DoctorInputs) -> str | None:
    """The host's zone name: given, ``TB_HOST_TZ``, else /etc/timezone or the /etc/localtime link. None inside a
    container (its /etc is the image's, not the host's) or when it cannot be read."""
    given = inp.host_tz or inp.env.get("TB_HOST_TZ")
    if given:
        return given.strip()
    if inp.platform or Path("/.dockerenv").exists() or os.environ.get("KUBERNETES_SERVICE_HOST"):
        return None
    try:
        name = (ETC / "timezone").read_text(encoding="utf-8").strip()
        if name:
            return name
    except OSError:
        pass
    try:
        link = str((ETC / "localtime").readlink())
    except (OSError, ValueError):
        return None
    return link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else None


def _mapping_zone(settings: Mapping[str, Any]) -> tuple[str | None, str]:
    ds = settings.get("data_source") or {}
    raw = ds.get("mapping") if isinstance(ds, Mapping) else None
    if not raw:
        return None, ""
    path = Path(str(raw))
    if not path.is_absolute():
        # T-632: the site's mapping folder first, then the image's, as the adapter looks it up (adapter.mapping.site;
        # not imported: the host tree has no services/)
        site = ROOT / "deploy" / "site" / "mapping" / Path(*path.parts[(1 if path.parts[:1] == ("mapping",) else 0) :])
        path = site if site.is_file() else MAPPING_ROOT / path
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (str(doc["tz"]) if doc.get("tz") else None), path.name


def _same_zone(a: str, b: str) -> bool:
    """Two names are the same zone when they agree on the UTC offset every day for a year (Japan == Asia/Tokyo)."""
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    if a == b:
        return True
    za, zb = ZoneInfo(a), ZoneInfo(b)
    t = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    days = [t + timedelta(days=d) for d in range(366)]
    return all(d.astimezone(za).utcoffset() == d.astimezone(zb).utcoffset() for d in days)


def check_site_tz(inp: DoctorInputs) -> Check:
    """D-315: site.tz, TB_TZ, the mapping's tz and the host's zone name one zone; there is no default zone."""
    from zoneinfo import ZoneInfo

    site = inp.settings.get("site")
    mapped, mapping_name = _mapping_zone(inp.settings)
    sources: dict[str, str | None] = {
        "site.tz": str((site if isinstance(site, Mapping) else {}).get("tz") or "").strip() or None,
        "TB_TZ": (inp.env.get("TB_TZ") or "").strip() or None,
        f"mapping tz ({mapping_name})": mapped,
    }
    if not sources["site.tz"] and not sources["TB_TZ"]:
        return Check("site_tz", "FAIL", "no site time zone: set site.tz in settings.yaml and TB_TZ in deploy/.env")
    host = _host_zone(inp)
    if host:
        sources["host zone"] = host
    given = {k: v for k, v in sources.items() if v}
    for k, v in given.items():
        try:
            ZoneInfo(v)
        except Exception:
            return Check("site_tz", "FAIL", f"{k}={v!r} is not an IANA time zone")
    first = next(iter(given.values()))
    if any(not _same_zone(first, v) for v in given.values()):
        names = ", ".join(f"{k} {v}" for k, v in given.items())
        return Check("site_tz", "FAIL", f"the site's time zone differs: {names}; records near midnight move a day")
    unread = "" if host else ("; no host on a platform" if inp.platform else "; host zone not read (set TB_HOST_TZ)")
    return Check("site_tz", "PASS", f"{first} ({', '.join(given)}){unread}")


def check_flags(inp: DoctorInputs) -> Check:
    """T-008 (D-207): a seed variable (``TB_LAKE_SOURCE``) seeds its flag at the first start only; one that now says
    something else than the flag is ignored, which an operator must know: WARN."""
    url = inp.env.get("TB_DB_URL", "")
    if not url:
        return Check("flags", "PASS", "no trial database configured here (TB_DB_URL): the flags were not read")
    try:
        from tb_common.flags import env_drift

        drift = env_drift(dict(inp.env), url)
    except Exception as e:  # the flags live on the box: unreadable from here is worth a look, not a failure
        return Check("flags", "WARN", f"cannot read the feature flags ({type(e).__name__})")
    if drift:
        return Check("flags", "WARN", "; ".join(drift))
    return Check("flags", "PASS", "every seed variable that is set agrees with its flag")


def check_site_key(inp: DoctorInputs) -> Check:
    """T-612 (DATA-004): the site key is in the secrets folder and is the key the box's data was made with (the
    fingerprint in ``<lake>/site_key.json`` and in the pid map's ``site_key`` table). Shows the fingerprint, never
    the key."""
    from tb_common.crypto import SITE_KEY_FILE, KeyMissingError, key_fingerprint, load_key

    sec = Path(inp.env.get("TB_SECRETS_DIR") or "/run/secrets/trialbox")
    if not sec.is_dir():
        return Check("site_key", "WARN", f"the secrets folder {sec} is not here (TB_SECRETS_DIR): the key was not read")
    try:
        key = load_key(sec / SITE_KEY_FILE)
    except KeyMissingError as exc:
        return Check(
            "site_key",
            "FAIL",
            f"{exc}: the ingest refuses every night. Put the site's key back from the backup; only a new box makes "
            f"one (deploy/install.sh, `python -m adapter.cli keys-init`)",
        )
    except PermissionError:
        return Check("site_key", "WARN", f"{sec / SITE_KEY_FILE} cannot be read by this user: the key was not checked")
    fp = key_fingerprint(key)
    lake = Path(inp.env.get("TB_LAKE_DIR") or Path(inp.env.get("TB_DATA_DIR") or "/data") / "lake")
    seen: list[str] = []
    record = lake / "site_key.json"  # adapter.pipeline.SITE_KEY_RECORD
    if record.is_file():
        stored = str(json.loads(record.read_text(encoding="utf-8")).get("fingerprint"))
        if stored != fp:
            return Check("site_key", "FAIL", f"key {fp} is not the lake's {stored}: the ingest refuses every night")
        seen.append("the lake")
    site_id = str((inp.settings.get("site") or {}).get("id") or "")
    url = inp.env.get("TB_DB_URL", "")
    if url and site_id:
        try:
            from tb_common.db import Database

            with Database.connect(url, "pidmap") as db:
                row = db.fetchone("SELECT fingerprint FROM site_key WHERE site_id = ?", (site_id,))
        except Exception as e:  # the pid map lives on the box: unreadable from here is worth a look
            return Check("site_key", "WARN", f"key {fp}; the pid map's record cannot be read ({type(e).__name__})")
        if row is not None and row[0] != fp:
            return Check("site_key", "FAIL", f"key {fp} is not the pid map's {row[0]}: the ingest refuses every night")
        if row is not None:
            seen.append("the pid map")
    where = f"; the same as {' and '.join(seen)}" if seen else "; no night has recorded one yet"
    return Check("site_key", "PASS", f"key {fp}{where}")


def check_backup(inp: DoctorInputs) -> Check:
    """D-274 (CR-058, OPS-028, OPS-048): targets, an off-box one, an alert route, the cron file, the newest good
    backup's age, WAL archiving. In PRODUCTION every problem is a FAIL except archiving off (WARN)."""
    if inp.platform:
        return Check("backup", "PASS", "not a host check on a platform: see backup_target (no host cron)")
    from tools.trialbox import backup_schedule as bs

    prod = (inp.env.get("TB_ENV") or "PRODUCTION").upper() == "PRODUCTION"
    if inp.deploy is None:
        why = "the deploy folder is not known: run with --env-file deploy/.env"
        return Check("backup", "FAIL" if prod else "WARN", why)
    cfg = bs.config(inp.deploy, dict(inp.env), process_env=False)
    st = bs.status(cfg)
    fails = list(st["problems"])
    if inp.cron_dir.is_dir() and not (inp.cron_dir / bs.CRON_NAME).is_file():
        fails.append(f"no {inp.cron_dir / bs.CRON_NAME}: python3 -m tools.trialbox backup-install (RUNBOOK §5)")
    warns = []
    if not cfg.archive_on:
        warns.append("WAL archiving is off: a crash loses up to a day (TB_PG_ARCHIVE_MODE, RUNBOOK §5)")
    off = sum(t["offbox"] for t in st["targets"])
    good = st["newest_good"]
    facts = f"{len(cfg.targets)} target(s), {off} off-box; newest good " + (
        f"{Path(good['path']).name} ({st['age_hours']} h old)" if good else "none")  # fmt: skip
    if fails:
        return Check("backup", "FAIL" if prod else "WARN", "; ".join(fails) + f" ({facts})")
    if warns and prod:
        return Check("backup", "WARN", "; ".join(warns) + f" ({facts})")
    return Check("backup", "PASS", facts)


def check_key_custody(inp: DoctorInputs) -> Check:
    """T-210b (CR-041, D-347): the site keys are kept under a KEK held outside the secrets folder."""
    from tb_common import kek

    sec = Path(inp.env.get("TB_SECRETS_DIR") or "/run/secrets/trialbox")
    if not sec.is_dir():
        return Check("key_custody", "WARN", f"the secrets folder {sec} is not here (TB_SECRETS_DIR): not checked")
    c = kek.custody(sec, {**os.environ, **inp.env})
    if c.problems:
        return Check("key_custody", "FAIL", "; ".join(c.problems))
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    if c.plain:
        how = "python -m tools.keys init (the KEK ceremony), then the keys stay wrapped"
        status: Status = "FAIL" if env in kek.STRICT_ENVS else "WARN"
        return Check("key_custody", status, f"{', '.join(c.plain)} plain on disk in {env}: {how}")
    if not c.wrapped:
        return Check("key_custody", "PASS", "no site key in the secrets folder yet (made by the install ceremony)")
    where = f"KEK {c.kek_id} ({c.backend})"
    if c.kek == "locked":
        return Check("key_custody", "WARN", f"{', '.join(c.wrapped)} wrapped under {where}; not unsealed here")
    return Check("key_custody", "PASS", f"{', '.join(c.wrapped)} wrapped under {where}, unsealed")


def check_clock(inp: DoctorInputs) -> Check:
    """T-211a (OPS-055): NTP out of sync is a FAIL, and so is a clock more than the allowed skew from the site's
    time server. ``tb_common.audit.clock_state`` reads both."""
    from tb_common import audit

    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    soft: Status = "FAIL" if env in ("VALIDATION", "PRODUCTION") else "WARN"
    st = audit.clock_state(inp.env)
    limit = audit.max_skew(inp.env)
    if st.offset is not None and abs(st.offset) > limit:
        return Check("clock", "FAIL", f"the clock is {st.offset:+.1f} s from {st.server} (more than {limit:g} s): "
                     "audit times are wrong and sign-in codes fail; fix the host's time sync")  # fmt: skip
    problems: list[str] = []
    if st.synced is False:
        problems.append("the kernel clock is not NTP-synchronised (timedatectl; on WSL2 the host's time sync task)")
    if st.server and st.offset is None:
        problems.append(f"the time server {st.server} did not answer ({st.error})")
    if st.synced is None and st.offset is None:
        problems.append(f"the clock's sync state cannot be read here and no {audit.NTP_SERVER_ENV} is set")
    if problems:
        return Check("clock", soft, "; ".join(problems))
    where = f"; {st.offset:+.2f} s from {st.server}" if st.offset is not None else ""
    return Check("clock", "PASS", f"NTP-synchronised{where}" if st.synced else f"clock checked{where}")


CHECKS: tuple[Callable[[DoctorInputs], Check], ...] = (
    check_topology,
    check_env_class_ceiling,
    check_routing_perimeter,
    check_gateway_only_model_reach,
    check_channel_engine,
    check_secure_cookie,
    check_publish_gate,
    check_note_block,
    check_judge_route,
    check_registry_pins,
    check_site_tz,
    check_flags,
    check_site_key,
    check_backup,
    check_key_custody,
    check_clock,
)


LIVE: tuple[Callable[[DoctorInputs], Check], ...] = (check_serving,)


def check_two_device(inp: DoctorInputs) -> Check:
    """The GB10 two-device form on this device (T-214, D-373): what runs here, what listens where, the link."""
    from tools import two_device as td

    role = inp.env.get("TB_LINK_ROLE", "").strip()
    if role not in td.ROLES:
        return Check("two_device", "FAIL", f"TB_LINK_ROLE must be {' or '.join(td.ROLES)} (deploy/.env), not {role!r}")
    profile = td.load_profile()
    bad = [f"profile: {p}" for p in td.profile_problems(profile)]
    if inp.compose_config is None:
        bad.append("no rendered compose (give --compose-config, or run doctor where docker compose works)")
    else:
        bad += td.compose_problems(role, inp.compose_config, profile)
    if bad:
        return Check("two_device", "FAIL", "; ".join(bad))
    late = td.driver_hold_overdue(profile) if role == "spark" else None
    if late:
        return Check("two_device", "WARN", late)
    return Check("two_device", "PASS", f"{role}: {', '.join(profile['devices'][role])}; the link only on its address")


TWO_DEVICE: tuple[Callable[[DoctorInputs], Check], ...] = (check_two_device,)


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
    *, env_file: Path | None, settings: Path | None, routing: Path | None, lake: Path | None
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
    wd = lake or (Path(env["TB_LAKE_DIR"]) if env.get("TB_LAKE_DIR") else None)
    deploy = env_file.resolve().parent if env_file is not None and env_file.exists() else None
    return DoctorInputs(
        env=env,
        settings=doc,
        routing_path=routing or ROOT / "models" / "routing.yaml",
        ingest_lake=wd,
        deploy=deploy,
    )


def render(checks: list[Check]) -> str:
    lines = [f"{c.status:<5} {c.name:<26} {c.detail}" for c in checks]
    fails = sum(c.status == "FAIL" for c in checks)
    lines.append("---")
    lines.append("doctor passed" if not fails else f"{fails} check(s) failed")
    return "\n".join(lines)
