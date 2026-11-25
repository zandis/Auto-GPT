"""``trialbox doctor`` for v4 (spec v4 §18.1, §9.5, §17.8; S1-16, HER-18, OPS-02, NFR-B9, ENG-16).

Each check returns PASS, WARN or FAIL; any FAIL makes the command exit 1, and a check that raises is a FAIL (fail
closed). Checks:

* ``inputs`` (OPS-016): one FAIL line per input that cannot be read (a ``--settings`` file that is missing or does not
  parse); the other checks still run, on empty settings;
* ``tls_old_clients`` (H-48, D-1328): only while ``TB_TLS_OLD_CLIENTS=cbc`` relaxes 443 for a hospital's old
  client, one WARN line saying so; a value other than off or cbc, or one not audited by deploy/install.sh, is FAIL;
* ``topology``: ``TB_TOPOLOGY`` (A/B/C) and ``TB_ENV`` (DEV/TEST/VALIDATION/PRODUCTION) are valid;
* ``terminology`` (D-1028, D-858): the code systems loaded on the box (``TB_TERMINOLOGY_DIR``), each with its rows and
  version; a table without its manifest line, or with other bytes, is FAIL; none loaded is WARN;
* ``env_class_ceiling``: no configured data store (``settings.data_stores``), dataset (``eval/DATASETS.yaml``, in
  DEV and TEST) or ``TB_DATA_CLASS`` exceeds the environment ceiling of §17.8 (D3 data in DEV fails);
* ``routing_perimeter``: ``models/routing.yaml`` has no row, and no lookup, that sends D3/D4 outside the perimeter;
* ``gateway_only_model_reach``: the egress allowlist (``deploy/egress.py``) gives a model host to the gateway only;
* ``channel_engine``: ``channels.engine`` is valid (native is the only engine, D-121);
* ``named_choices`` (10K-21, D-1365): on a PRODUCTION box the chart-number rule was chosen, the health page as the
  backup alert route names who opens it, and Caddy's own CA has IT's confirmation that its root is on the clinic PCs;
  WARN with the next action for each one missing (a site installed before keeps starting), PASS elsewhere;
* ``secure_cookie``: the console session cookie is marked Secure (``TB_CONSOLE_SECURE_COOKIE=1``, or unset or empty in
  PRODUCTION, the console's default since D-192). FAIL in
  PRODUCTION and VALIDATION, WARN elsewhere (a DEV/TEST box may serve plain http on localhost; D-121);
* ``phi_tripwire`` (9g-11, D-1348): the gateway's PHI tripwire (``TB_GATEWAY_PHI_TRIPWIRE``, D-506) is on. FAIL when it
  is off in PRODUCTION, WARN when it is off elsewhere; the line says how to turn it on;
* ``console_mfa`` (D-447, CR-033 rest; D-192 "Open"): every way into the console asks for a second factor:
  ``TB_CONSOLE_MFA`` resolves to ``totp`` (the console's default outside DEV and TEST), OIDC, when on, keeps
  ``TB_OIDC_REQUIRE_MFA``, and no trusted identity header (``TB_CONSOLE_SSO_HEADER``, D-93) signs people in. FAIL in
  PRODUCTION and VALIDATION, WARN elsewhere;
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
  ``site/registry.site.yaml`` in the deploy folder of ``--env-file``, else the repository's ``deploy/``; OPS-016)
  loads; lists the site-pinned builds. WARN when no model build is pinned
  (production routes nothing) or, in VALIDATION/PRODUCTION, when no pinned build is ``champion``;
* ``site_tz`` (D-315; STD-016, OPS-056): the site's time zone is one setting. ``site.tz`` (settings.yaml), ``TB_TZ``
  (the containers' zone), the ``tz`` of the data source mapping (``data_source.mapping``) and the host's zone (cron
  runs the backup and the log jobs in it; ``TB_HOST_TZ`` when doctor runs in a container) must name the same zone.
  FAIL when none is set, one is not a zone, or two differ; the host is not compared when it cannot be read;
* ``flags``: a seed variable such as ``TB_LAKE_SOURCE`` that disagrees with its feature flag is ignored since the
  box's first start (T-008, D-207): WARN, naming the flag's value and where to change it;
* ``restore_hold`` (D-522, H-136): the hold after a restore, read through the box (``compose exec db``, never the
  host's own Python): held is a WARN with the reason, released a PASS, a hold that cannot be read a FAIL with the cause;
* ``backup`` (D-274; CR-058, OPS-028, OPS-048): read from the deploy folder of ``--env-file``. FAIL in PRODUCTION
  (WARN elsewhere) when there is no target, no off-box target, no alert route (``TB_BACKUP_ALERT_CMD``,
  ``TB_BACKUP_MAILTO`` or ``TB_BACKUP_ALERT_ROUTE=health-page``, D-735), no schedule that fires (H-92: the
  ``trialbox-backup-nightly`` timer where systemd is the init, else ``/etc/cron.d/trialbox-backup`` and a cron
  daemon; both at once is a problem too), no good backup or one
  older than ``TB_BACKUP_MAX_AGE_HOURS`` (``backup-status``'s rules); WARN in PRODUCTION when WAL archiving is off;
  on a platform it passes and points to ``backup_target`` and ``backup_job``;
* ``site_key`` (T-612, DATA-004): ``site_hmac.key`` is in the secrets folder (``TB_SECRETS_DIR``) and its fingerprint
  is the one recorded in the lake (``site_key.json``) and in the pid map. FAIL when it is missing or another key (the
  ingest then refuses every night); WARN when the folder is not on this host. Prints the fingerprint, never the key;
* ``chartno_rule`` (D-621): every service of the box that can make a pseudonym is started with one chart-number
  rule (``TB_CHARTNO_RULE``, read from the rendered compose files and from the running containers), and it is the
  rule the pid map recorded (D-595). FAIL when a service differs, a rule cannot be read, or the rule is not the pid
  map's: an opt-out registered by such a service would be filed under a pseudonym the feed never produces. Where
  the running containers or the pid map were not read (no docker, no database from here) the line says NOT CHECKED
  and is a WARN on a box that may hold real data; ``deploy/check_host.sh`` hands both in to the doctor's container;
* ``negated_inclusions`` (card 10A-1): an approved ruleset on ``main`` with an inclusion whose line may negate what
  its logic asks the presence of is a WARN that names it: it keeps running until a person recompiles and approves
  it. Read-only; NOT CHECKED without a ruleset repository or the compiler package;
* ``key_custody`` (T-210b, CR-041, D-347): the site keys are wrapped under the KEK (``tb_common.kek``). FAIL when a key
  is both plain and wrapped, a wrapped key has no ``kek.json`` or names another KEK, the KEK file is in the secrets
  folder or is not this box's KEK, or (in VALIDATION and PRODUCTION) a site key is a plain file; WARN for a plain key
  in DEV/TEST and when the keys are wrapped but the KEK is not unsealed where doctor runs. Opens no key.
* ``clock`` (T-211a, OPS-055, REG-026): the audit chain's times need a true clock. FAIL when the clock is more than
  ``TB_CLOCK_MAX_SKEW_S`` (default 60) seconds from the site's time server (``TB_NTP_SERVER``, one SNTP exchange); in
  VALIDATION and PRODUCTION also FAIL when the kernel clock is not NTP-synchronised, when the time server does not
  answer, or when neither can be read. WARN for those in DEV and TEST.
* ``db_passwords`` (T-712, D-481; D-378): a service container holds its own database role's password and no other.
  Read from ``deploy/.env`` (every service role has a password of its own; none is the example value or shared with
  another role), from the box's compose files rendered with the box's values (``COMPOSE_FILE``;
  ``tools/trialbox/db_secrets.py``) and from the environment of the containers that run now. FAIL in VALIDATION and
  PRODUCTION, WARN in DEV and TEST; not judged without ``--env-file``. No password is printed.

* ``wsl2_memory`` (NEW-WIN-3, D-601): on a WSL2 kernel, the sum of the memory caps of the services that run (the
  box's ``COMPOSE_FILE`` read as compose reads it: a later file overrides, a service behind a profile counts only
  when ``COMPOSE_PROFILES`` names it, each ``${TB_MEM_*:-default}`` from ``--env-file``; the model servers at their
  caps, since no serving record carries their measured host memory yet) against the memory WSL2 was given
  (``.wslconfig``, read as ``MemTotal``). FAIL when the caps do not fit (the kernel would kill a service at night),
  when a compose file is missing or a cap is not a size; WARN when a service has no cap or no ``--env-file`` was
  given; PASS on a plain Linux host.

* ``update_window`` (NEW-WIN-5, D-606): on a WSL2 kernel, the hours in which Windows Update may restart the
  workstation (``TB_WIN_UPDATE_WINDOW_START`` and ``TB_WIN_UPDATE_WINDOW_HOURS``, the installer's
  ``-UpdateWindowStart`` and ``-UpdateWindowHours``) against the night's start (``data_source.nightly_at``). FAIL
  when the night starts inside the window, or when a recorded night (``tools/night_length.py``, NEW-B-20) ran
  into it (to the end of the orchestrator's work where that was measured, NEW-B-26). PASS when every recorded
  night was measured to the end of the night's work and each ended before the window opens; the line gives the
  least margin. WARN otherwise: no recorded night (the time between the night's start and the window), or nights
  measured only to the end of ingest (what the orchestrator did after it is then not known). The window is the
  one the Windows installer
  recorded (``deploy/site/box/windows-update-window``);
  without that file the declared one, said as unconfirmed; "kept" (the site's IT holds the policy) is a WARN. That
  Windows really holds this window is judged from Windows' side by ``deploy/windows/wsl2_policy.py``.
* ``backup_speed`` (NEW-WIN-7, D-608; D-455): on a WSL2 kernel, ``TB_BACKUP_MIN_MBPS`` (the speed below which a
  backup step counts as hung) against the write speed measured for each target's path
  (``deploy/windows/wsl-setup.sh backup-speed``, ``deploy/site/box/backup-speed``): a path through Windows is far
  slower than a box disk. FAIL when the setting is above the measured speed, WARN when it is above a tenth of it
  (D-455's margin) or a target was not measured; PASS on a plain Linux host.
* ``wsl2_versions`` (NEW-WIN-5, D-606): on a WSL2 kernel, the NVIDIA driver the card answers with against the
  driver of the box's serving record (``TB_GPU_PROFILE``'s, else the one naming that card; ``deploy/site`` before
  ``deploy/measured``; WARN when there is none or two, so the check says nothing until a record exists): FAIL
  when they differ (Windows Update or a person changed the driver the box was measured with), or when the card
  does not answer. The WSL2 kernel against the record's ``wsl_kernel``: FAIL when they differ, WARN while the
  record names none. PASS on a plain Linux host.

* ``postgres_memory`` (T-703, D-751, scale review F-19): FAIL when ``shared_buffers`` is PostgreSQL's default on a
  host of 64 GB or more (``tools.trialbox.pgsize``; ``deploy/install.sh`` sizes it from ``TB_MEM_DB``).
* ``memory_caps`` (T-692, D-473, scale review F-05): ``TB_MEM_ADAPTER`` and ``TB_MEM_LAKE`` (``--env-file``, else the
  compose defaults) against what the patient count needs (``tools/trialbox/memcaps.py``: the measured record
  ``measured/ingest_memory.json`` of the deploy folder). The count is the lake's ``CURRENT`` snapshot, else
  ``TB_SITE_PATIENTS``. FAIL when a cap is below the need (the night's ingest or rebuild may be killed); WARN when there
  is no count or no record.
* ``release_tree`` (H-144): on an installed release, the install folder holds no copy of a folder the box image
  carries and the signed host tree does not (``services/``, ``models/``, ``rulesets/``, ``catalogue/``, ``eval/``:
  ``host_tree.IMAGE_ONLY``). An update neither replaces nor checks such a copy: WARN, naming it and the command that
  removes it (never removed for the operator); FAIL when this command's import path holds it (a caller's PYTHONPATH:
  a host command run so would import it). PASS on a source checkout; WARN in the box image (not seen there).
* ``prefix_cache`` (H-146, D-1462): the judge and verifier servers' prefix cache (``TB_LLM_PREFIX_CACHING``). PASS
  off (the default), WARN on (``enable``: runs may differ), FAIL another value; with ``--compose-config``, FAIL a
  server whose rendered command does not carry the flag the setting names.

On a host's own Python (H-144), the checks of ``IMAGE_CHECKS`` (the ones that import pydantic, httpx or the services'
code, or read ``models/``) run in a one-off container of the box's own image (``tools/trialbox/doctor_image.py``) and
their verdicts join the host's in order; a container that does not run, or an import error in it, is that check's
FAIL with the reason, never a PASS or a skip.

A system module (F0, the modules framework section 6) adds its rows from its own file ``tools/trialbox/doctor_m<n>.py``
(``MODULE_CHECKS``): ``doctor_checks(inp)`` returns rows ``(key, state, text)``, state PASS, WARN or FAIL. A function
there named like a check this file opened to it (``_supplied``) is that check's body and returns one such row. A file
that is not there adds nothing; one that raises or returns anything else is a FAIL that says so, and every other row
stays. One that does not import because a third-party package is missing on a host's own python (never in the box
image) is a WARN "cannot look here: <package>"; every other import failure is a FAIL. A check that cannot look returns
WARN with the reason.

``--verify-all`` adds one check that hashes the model weights (minutes for tens of GB; ``--weights`` runs it alone,
as the ``trialbox-weights`` timer before the night's runs and an update after its restart do; T-677, D-393):

* ``weights`` (LLM-008, SEC-64): every build pinned in the site override (``TB_REGISTRY_OVERRIDE``, default
  ``site/registry.site.yaml`` in the deploy folder) still hashes to its pin under the models folder (``TB_MODELS_DIR``,
  default ``models/`` in the deploy folder of ``--env-file``, else the repository's ``deploy/models``;
  ``tools/pin_model.py --verify-all``). FAIL on any difference: it writes the weights flag
  ``weights_changed.json`` beside the override (``TB_WEIGHTS_FLAG`` moves it), and the gateway refuses every model
  call while the flag is there (``gateway.app.StartCheck``). A pass removes the flag. WARN when nothing is pinned.

``--two-device`` adds one check, for a device of the GB10 two-device form (T-214, D-373; ``deploy/two-device/``):

* ``two_device``: ``TB_LINK_ROLE`` (spark or workstation) names this device; its rendered compose (``--compose-config``,
  else ``docker compose config --format json`` of the device's services in the deploy folder) runs only what the GB10
  profile (``deploy/gb10-profile.yaml``) puts on it, the link is the only port the Spark publishes and only on the
  link address (a gateway or any listener on 0.0.0.0 there is a FAIL), the link has its certificates, its peer and
  its route alias, and the Spark's memory limits are the profile's. WARN when the driver hold's re-test is past due.
* ``poc_stop`` (H-94): with ``--env-file``, one WARN line per stop a PoC box's install, start or update warned instead
  of stopping (``deploy/site/poc-stops.jsonl``, ``tools/trialbox/stops.py``), each with its action; never a FAIL.

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

import contextlib
import functools
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
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
    resolver: Callable[[str], list[str]] | None = None  # check perimeter_addresses; None: the system resolver
    compose_config: Mapping[str, Any] | None = None  # doctor --two-device: the device's rendered compose (D-373)
    input_errors: tuple[str, ...] = ()  # OPS-016: a settings file that is missing or does not parse is a FAIL line
    timer_state: Callable[[str], str | None] | None = None  # check ops_runner; None: ask systemctl where it exists
    cron_running: Callable[[], bool] | None = None  # H-92: a cron daemon runs; None: not asked (inputs_from asks)
    backup_timers: Callable[[str], str | None] | None = None  # D-1090: each backup timer's word; None: not asked
    proc: Path = Path("/proc")  # NEW-WIN-3: the kernel's name and MemTotal (check wsl2_memory)
    gpu_query: Callable[[], tuple[str, str] | None] | None = None  # NEW-WIN-5: (card, driver); None: nvidia-smi
    box: Path | None = None  # H-136: the box whose hold is read through compose on its host; None: ``deploy``
    in_image: bool | None = None  # H-136: doctor runs in the box image; None: asked (``launch.in_box_image``)


def _site_dir(inp: DoctorInputs) -> Path:
    """The site folder: ``site/`` beside ``--env-file`` when it is given, else the repository's (OPS-016)."""
    return (inp.deploy or ROOT / "deploy") / "site"


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress_doctor", ROOT / "deploy" / "egress.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------- module checks (F0)
MODULE_CHECKS: tuple[str, ...] = tuple(f"tools.trialbox.doctor_m{n}" for n in range(1, 10))  # M1 to M9; M10 has none


def _module(name: str) -> ModuleType | None:
    """A module's check file, or None while the module has not brought it."""
    return None if importlib.util.find_spec(name) is None else importlib.import_module(name)


#: the packages of pyproject's dependencies, by import name: a host's own python may lack them (the box image never)
_THIRD_PARTY = frozenset({
    "pydantic", "yaml", "jsonschema", "jinja2", "httpx", "fastapi", "uvicorn", "multipart", "duckdb", "pyarrow",
    "sqlglot", "sqlalchemy", "psycopg", "openpyxl", "reportlab", "matplotlib", "docxtpl", "docx", "pypdf", "py7zr",
    "cryptography", "apscheduler", "numpy", "fhir", "dateutil", "tzdata", "markdown", "dulwich", "zstandard",
})  # fmt: skip


def _host_lacks(e: ModuleNotFoundError) -> bool:
    """A third-party package missing on a host's own python (not the box image): the check could not look, nothing is
    wrong. Anything else that does not import (syntax, the box's own module, any error in the image) stays a FAIL."""
    from tools.trialbox import launch

    return (e.name or "").partition(".")[0] in _THIRD_PARTY and not launch.in_box_image()


def _row(row: Any) -> Check:
    key, state, text = row
    if state not in ("PASS", "WARN", "FAIL") or not (isinstance(key, str) and key and isinstance(text, str)):
        raise ValueError(f"not a row (key, PASS, WARN or FAIL, text): {row!r}")
    return Check(key, state, text)


def module_rows(inp: DoctorInputs, out: list[Check]) -> list[Check]:
    """``out`` with each module's rows after it. A row that takes another row's key is a FAIL, never a replacement."""
    out = list(out)
    for name in MODULE_CHECKS:
        own = name.rpartition(".")[2]
        try:
            try:
                mod = _module(name)
            except ModuleNotFoundError as e:
                if not _host_lacks(e):
                    raise
                out.append(Check(own, "WARN", f"cannot look here: {e.name}"))
                continue
            for c in map(_row, mod.doctor_checks(inp) if mod is not None and hasattr(mod, "doctor_checks") else ()):
                if any(c.name == o.name for o in out):
                    out.append(Check(own, "FAIL", f"its row {c.name!r} ({c.status}: {c.detail}) takes the name of "
                                     "another row"))  # fmt: skip
                else:
                    out.append(c)
        except Exception as e:  # fail closed, and the other modules' rows still come
            out.append(Check(own, "FAIL", f"check error: {type(e).__name__}: {e}"))
    return out


def _supplied(name: str) -> Callable[[Callable[..., Check]], Callable[..., Check]]:
    """The check keeps its place and its name; its body is the module's function of the same name once the module's
    file has one (framework section 6: M2 and M4 change these checks without editing this file)."""

    def opened(fn: Callable[..., Check]) -> Callable[..., Check]:
        @functools.wraps(fn)
        def check(inp: DoctorInputs, *args: Any, **kwargs: Any) -> Check:
            try:
                body = getattr(_module(name), fn.__name__, None)
            except ModuleNotFoundError as e:
                if not _host_lacks(e):
                    raise
                return Check(fn.__name__.removeprefix("check_"), "WARN", f"cannot look here: {e.name}")
            if body is None:
                return fn(inp, *args, **kwargs)
            c = _row(body(inp, *args, **kwargs))
            if c.name != fn.__name__.removeprefix("check_"):
                raise ValueError(f"{name}.{fn.__name__} returned the row of {c.name!r}")
            return c

        return check

    return opened


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


def check_perimeter_addresses(inp: DoctorInputs) -> Check:
    """T-604 (D-388; review LLM-036): each perimeter endpoint's host and the addresses it resolves to now. In
    PRODUCTION on topology A an address off the box is a FAIL (the gateway refuses to start on it); elsewhere a WARN.
    Run on the host, a compose service name does not resolve: it is shown as such (the gateway resolves it on the
    box network when it starts)."""
    from gateway.policy import RoutingPolicy, perimeter_addresses, perimeter_checked, resolve_host
    from tb_common.policy.classes import Environment, Topology

    env = {k: v for k, v in inp.env.items()}
    environment = (env.get("TB_ENV") or "DEV").strip().upper()
    topo = env.get("TB_TOPOLOGY", "A")
    rows = perimeter_addresses(RoutingPolicy.load(inp.routing_path), env, environment, inp.resolver or resolve_host)
    shown = "; ".join(f"{r.endpoint} {r.host} -> {', '.join(r.addresses) or 'compose service'}" for r in rows)
    problems = [r.problem for r in rows if r.problem]
    if not problems:
        return Check("perimeter_addresses", "PASS", f"on the box: {shown or 'no perimeter endpoint set'}")
    strict = (
        topo in Topology.__members__
        and environment in Environment.__members__
        and perimeter_checked(Topology(topo), Environment(environment))
    )
    return Check("perimeter_addresses", "FAIL" if strict else "WARN", "; ".join(problems))


def check_channel_engine(inp: DoctorInputs) -> Check:
    from channels.config import ChannelsConfig, ChannelsConfigError

    try:
        cfg = ChannelsConfig.from_settings(inp.settings)
    except ChannelsConfigError as e:
        return Check("channel_engine", "FAIL", str(e))
    return Check("channel_engine", "PASS", f"engine {cfg.engine}")


def check_sae_mailbox(inp: DoctorInputs) -> Check:
    """D-736 (LIFE-007): on a PRODUCTION box the trial office is mailed at once when a serious adverse event is
    entered (``TB_SAE_OFFICE_MAILBOX``, one mail address); without it nobody is told until the next working day. A box
    installed by ``box-install.sh`` starts without it, so this is a WARN, never a FAIL."""
    import re

    from tools.settings_wizard import MAILBOX_RE

    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    to = (inp.env.get("TB_SAE_OFFICE_MAILBOX") or "").strip()
    if to and re.fullmatch(MAILBOX_RE, to):
        return Check(
            "sae_mailbox", "PASS", f"the trial office is mailed at {to} when a serious adverse event is entered"
        )
    if env != "PRODUCTION":
        return Check("sae_mailbox", "PASS", f"{env}: no SAE office mailbox needed")
    why = (f"TB_SAE_OFFICE_MAILBOX {to!r} is not one mail address" if to else "no TB_SAE_OFFICE_MAILBOX") + (
        ": nobody is mailed when a serious adverse event is entered; set it in deploy/.env (D-736, RUNBOOK §1)"
    )
    return Check("sae_mailbox", "WARN", why)


def check_named_choices(inp: DoctorInputs) -> Check:
    """10K-21 (D-1365): three choices a PRODUCTION site may not leave silent. The chart-number rule was chosen
    (``TB_CHARTNO_RULE_ANSWERED=yes``, or a rule other than ``asis``, which only an answer gives); the health page as
    the backup alert route names who opens it every working day (``TB_BACKUP_ALERT_WATCHER``); Caddy's own CA has
    hospital IT's confirmation that its root is on the clinic PCs (``TB_TLS_ROOT_CONFIRMED_BY`` and ``_ON``). A WARN
    with the next action, never a FAIL: a site installed before 10K-21 keeps starting. PASS outside PRODUCTION."""
    from tb_common.config import environment_name

    def val(k: str) -> str:
        return (inp.env.get(k) or "").strip().strip('"').strip("'").strip()

    gaps: list[str] = []
    said: list[str] = []
    rule = val("TB_CHARTNO_RULE").lower() or "asis"
    if rule == "asis" and val("TB_CHARTNO_RULE_ANSWERED").lower() != "yes":
        gaps.append("the chart-number rule asis was never chosen (the question was left empty): ask the hospital how "
                    "it writes chart numbers; if they are taken exactly as written, add TB_CHARTNO_RULE_ANSWERED=yes "
                    "to deploy/.env; another rule only on a box that has loaded no patient (RUNBOOK §1)")  # fmt: skip
    else:
        said.append(f"chart-number rule {rule} chosen")
    if val("TB_BACKUP_ALERT_ROUTE").lower() == "health-page":
        who = val("TB_BACKUP_ALERT_WATCHER")
        if who:
            said.append(f"{who} opens the health page every working day")
        else:
            gaps.append("the backup alert route is the health page and nobody is named to open it every working day: "
                        "set TB_BACKUP_ALERT_WATCHER in deploy/.env to that person's name (RUNBOOK §5)")  # fmt: skip
    if val("TB_TLS_HOSTNAME") and (val("TB_TLS_MODE").lower() or "internal") != "hospital":
        by, on = val("TB_TLS_ROOT_CONFIRMED_BY"), val("TB_TLS_ROOT_CONFIRMED_ON")
        if by and on:
            said.append(f"the box's root certificate is on the clinic PCs (confirmed by {by} on {on})")
        else:
            gaps.append("no confirmation from hospital IT that the box's root certificate (Caddy's own CA) is on "
                        "every clinic PC: once IT has pushed it, set TB_TLS_ROOT_CONFIRMED_BY (who) and "
                        "TB_TLS_ROOT_CONFIRMED_ON (YYYY-MM-DD) in deploy/.env (RUNBOOK §12)")  # fmt: skip
    env = environment_name(inp.env)
    if gaps and env == "PRODUCTION":
        return Check("named_choices", "WARN", "; ".join(gaps))
    if gaps:
        return Check("named_choices", "PASS", f"{env}: not required ({'; '.join(gaps)})")
    return Check("named_choices", "PASS", "; ".join(said))


def check_mail_auth(inp: DoctorInputs) -> Check:
    """D-825 (D-369): the mail gateway trusts sender results only from the MTA ``TB_MAIL_AUTHSERV_ID`` names; empty, it
    refuses every request mail (fails closed). WARN on a site box (VALIDATION, PRODUCTION), never a FAIL: a box
    without mail is a box, and the refusal is the safe side."""
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    if (inp.env.get("TB_MAIL_AUTHSERV_ID") or "").strip():
        return Check("mail_auth", "PASS", f"sender results trusted from {inp.env['TB_MAIL_AUTHSERV_ID'].strip()}")
    if env not in ("VALIDATION", "PRODUCTION"):
        return Check("mail_auth", "PASS", f"{env}: no MTA named; mail intake stays closed")
    return Check(
        "mail_auth",
        "WARN",
        "no TB_MAIL_AUTHSERV_ID: every mailed FEAS or SCREEN request is refused until the "
        "hospital MTA's authserv-id is set (the box answers' mta_authserv_id, or deploy/.env; D-369, D-825)",
    )


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


def check_mail_tls(inp: DoctorInputs) -> Check:
    """H-137 (the owner's decision, #639 7156806411 item 6; the integrator's ruling 7165038321 item 4): a WARN in every
    environment while a mail server is spoken to without a verified certificate, naming the server and the setting
    (``mail_gateway.tls``: SMTP_TLS_VERIFY, SMTP_STARTTLS, IMAP_TLS_VERIFY, IMAP_SSL); the gateway audits each start
    so. The IMAP server counts only when a mailbox is polled (IMAP_USER)."""
    from pathlib import Path as _Path

    from mail_gateway import tls
    from tb_common.config import load_env

    env = load_env(_Path("/nonexistent"), {k: str(v) for k, v in inp.env.items()})
    off = tls.unverified(env, imap_used=bool(env.imap_user))
    if not off:
        return Check("mail_tls", "PASS", "the mail servers' certificates are verified")
    said = "; ".join(f"{s} {h}: {setting}" for s, h, _m, setting in off)
    return Check("mail_tls", "WARN", f"mail without a verified certificate ({said}): each start is audited")


def check_trusted_proxy(inp: DoctorInputs) -> Check:
    """H-137 (the owner's decision, #639 7156806411 item 7): the one list of proxies the console trusts for forwarded
    headers (``tb_common.trusted_proxy``). "All" is a FAIL in PRODUCTION (the console refuses to start with it) and a
    WARN elsewhere; behind Caddy (``TB_TLS_HOSTNAME`` set) a list without Caddy's fixed address is a WARN: every browser
    is then one address to the sign-in lock (ASVS V3-01)."""
    from tb_common import trusted_proxy as tp
    from tb_common.config import environment_name

    env = environment_name(inp.env)
    value = (inp.env.get(tp.NAME) or "").strip()
    if tp.trusts_all(value):
        status: Status = "FAIL" if env == "PRODUCTION" else "WARN"
        return Check("trusted_proxy", status, f"{tp.NAME}={value!r} trusts every sender's X-Forwarded-For: a client "
                     "chooses its own address for the sign-in lock and the audit")  # fmt: skip
    proxy = (inp.env.get("TB_PROXY_ADDR") or "").strip() or tp.DEFAULT_PROXY_ADDR
    if (inp.env.get("TB_TLS_HOSTNAME") or "").strip() and proxy not in tp.entries(value):
        return Check("trusted_proxy", "WARN", f"behind Caddy ({proxy}) the console trusts {value or 'no proxy'}: every "
                     "browser is Caddy's one address to the sign-in lock; re-run the installer")  # fmt: skip
    if not value:
        return Check("trusted_proxy", "PASS", "no proxy trusted: each browser is the address it connects from")
    return Check("trusted_proxy", "PASS", f"forwarded headers trusted from {value} only")


def check_phi_tripwire(inp: DoctorInputs) -> Check:
    """9g-11 (D-1348; review 01 B1-P2): the gateway's PHI tripwire (D-506, D-792), read by the gateway's own rule
    (``gateway.core.GatewayConfig.from_env``: off, 0, false or no turns it off; unset or anything else keeps it on) in
    the gateway's environment (``TB_ENV``, PRODUCTION when unset). Off is a FAIL in PRODUCTION and a WARN elsewhere (a
    VALIDATION or DEV run on public data may set it off, as the P2b launch did)."""
    from gateway.core import GatewayConfig
    from tb_common.config import environment_name

    env = environment_name(inp.env)
    raw = inp.env.get("TB_GATEWAY_PHI_TRIPWIRE")
    if GatewayConfig.from_env({} if raw is None else {"TB_GATEWAY_PHI_TRIPWIRE": raw}).phi_tripwire:
        return Check("phi_tripwire", "PASS", "the PHI tripwire is on for calls that leave the box")
    status: Status = "FAIL" if env == "PRODUCTION" else "WARN"
    value = (raw or "").strip()
    why = (
        f"the PHI tripwire is off in {env} (TB_GATEWAY_PHI_TRIPWIRE={value}): calls that leave the box are not "
        "checked for patient identifiers; to turn it on, set TB_GATEWAY_PHI_TRIPWIRE=on in deploy/.env (or remove the "
        "line) and restart the gateway"
    )
    return Check("phi_tripwire", status, why)


def check_console_mfa(inp: DoctorInputs) -> Check:
    """The console's own rules (``console.identity.IdentitySettings.from_env``, ``console.oidc.OidcSettings``; D-192,
    D-447), read from the settings as compose passes them: a box with no second factor on some way in fails in
    PRODUCTION and VALIDATION (the console also refuses to start there; doctor says why before it is started)."""
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    dev = env in ("DEV", "TEST")
    off = ("1", "true", "on", "yes")
    mfa = (inp.env.get("TB_CONSOLE_MFA") or ("off" if dev else "totp")).strip().lower()
    gaps = []
    if mfa != "totp":
        gaps.append(f"TB_CONSOLE_MFA={mfa}: local accounts sign in with a password alone")
    oidc_on = (inp.env.get("TB_OIDC_ENABLED") or "").strip().lower() in off
    if oidc_on and (inp.env.get("TB_OIDC_REQUIRE_MFA") or "1").strip().lower() in ("0", "false", "off", "no"):
        gaps.append("TB_OIDC_REQUIRE_MFA=0: a directory sign-in without a second factor is accepted")
    if (inp.env.get("TB_CONSOLE_SSO_HEADER") or "").strip():
        gaps.append("TB_CONSOLE_SSO_HEADER is set: a trusted header signs people in with no second factor")
    if not gaps:
        return Check("console_mfa", "PASS", "every console sign-in asks for a second factor"
                     + (" (TOTP; OIDC with a second factor)" if oidc_on else " (TOTP)"))  # fmt: skip
    status: Status = "WARN" if dev else "FAIL"
    return Check("console_mfa", status, f"{env}: " + "; ".join(gaps))


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
    return Path(raw) if raw else _site_dir(inp) / "registry.site.yaml"


def placeholder_note(reg: Any) -> str:
    """D-887: the box rehearsal's placeholder pins, named wherever pins are shown ("" when there is none)."""
    names = [b.build_id for b in reg.builds if getattr(b, "rehearsal_placeholder", False)]
    if not names:
        return ""
    return f"; {', '.join(names)}: rehearsal placeholder (not a model: proves the path, never promoted)"


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
    # D-823: a VALIDATION box runs its candidate pair; only PRODUCTION routes champions alone
    if env == "PRODUCTION" and not any(b.status == Status.CHAMPION for b in pinned):
        return Check("registry_pins", "WARN", f"pinned: {names}; none is champion, so {env} roles route nothing")
    return Check("registry_pins", "PASS", f"{reg.version}: pinned {names}{placeholder_note(reg)}")


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
    from gateway.policy import RoutingPolicy, endpoint_key
    from registry.registry import DEFAULT_PATH, Registry

    env = dict(inp.env)
    strict = env.get("TB_ENV", "DEV") in ("VALIDATION", "PRODUCTION")
    reg = Registry.load(DEFAULT_PATH, _override(inp))
    policy = RoutingPolicy.load(inp.routing_path)
    want: dict[str, list[tuple[str, str]]] = {}
    for b in reg.builds:
        if not b.pinned or b.serving in ("stub", "hosted"):
            continue
        if b.family == "embedder":  # ENG-003 (D-563): the embed service is not a model server: it has no
            continue  # /v1/models and no key; its own /healthz names the pinned weights (D-429)
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
        # the key file (TB_LLM_API_KEY_FILE, deploy/secrets/model/llm.key; D-437, D-450) first, else the variable
        key = endpoint_key(ep.api_key_env, env) if ep.api_key_env else ""
        if not key:
            (fails if strict else warns).append(
                f"{ep_name}: no key, {key_var} is empty: anyone on model-net may call it"
            )
        status, doc = _get_models(url, key)
        if status is None:
            fails.append(f"{ep_name} ({url}) not reachable: {doc}")
            continue
        if status in (401, 403):
            why = (
                f"{key_var} is missing or is not the server's key (deploy/secrets/model/llm.key and vllm.env, "
                "`trialbox secrets rotate --service model`)"
            )
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
    return Check("serving", "PASS", "; ".join(good) + "; key required" + placeholder_note(reg))


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


def _mapping_zone(settings: Mapping[str, Any], site_dir: Path = ROOT / "deploy" / "site") -> tuple[str | None, str]:
    ds = settings.get("data_source") or {}
    raw = ds.get("mapping") if isinstance(ds, Mapping) else None
    if not raw:
        return None, ""
    path = Path(str(raw))
    if not path.is_absolute():
        # T-632: the site's mapping folder first, then the image's, as the adapter looks it up (adapter.mapping.site;
        # not imported: the host tree has no services/)
        site = site_dir / "mapping" / Path(*path.parts[(1 if path.parts[:1] == ("mapping",) else 0) :])
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
    mapped, mapping_name = _mapping_zone(inp.settings, _site_dir(inp))
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


def check_restore_hold(inp: DoctorInputs) -> Check:
    """NEW-B-3 (D-522), H-136: a restore that was not complete holds the box's list jobs until a person releases the
    hold (the flag ``screening.after_restore``) on ``/ops/flags``. Three readings, each its own line: held is a WARN
    with who held it, when and the reason the restore gave (counts and times); released (or never set) is a PASS; a
    hold that cannot be read is a FAIL naming the cause, never a pass: an operator told nothing is held while the
    screening hold is on would wait for lists that never come.

    Where it is read (H-136): on the box's host, through the box (``box_hold.read``: ``compose exec db psql``, with
    the box file's runtime and project, never the host's own Python, a host database address or a caller's
    variable). In the box image (the host check, the rehearsal), what the host read that way and handed in
    (``TB_DOCTOR_RESTORE_HOLD``); without it, the image's own database address, as the console reads it (a hospital
    platform's doctor job). A process with no box at all (no ``deploy/.env``: a developer's tree, the test cluster)
    reads its own ``TB_DB_URL`` the same way; where there is a box, its compose project decides, never that."""
    from tools.trialbox import box_hold, launch

    name = "restore_hold"
    asked = getattr(inp, "in_image", None)
    in_image = launch.in_box_image() if asked is None else asked
    box = getattr(inp, "box", None) or getattr(inp, "deploy", None)
    if not in_image and box is not None:  # a box's host: through the box, whatever TB_DB_URL or a hand-in says
        got = box_hold.read(box)
    elif in_image and inp.env.get("TB_DOCTOR_RESTORE_HOLD", "").strip():  # the host check's reading, through the box
        try:
            handed = json.loads(inp.env["TB_DOCTOR_RESTORE_HOLD"])
        except ValueError:
            handed = None
        got = handed if isinstance(handed, dict) else box_hold.unread("the host's reading of the hold is not one")
        if got.get("state") not in ("held", "released", "unread"):
            got = box_hold.unread("the host's reading of the hold is not one")
    elif inp.env.get("TB_DB_URL", ""):
        try:
            from tb_common.flags import Flags

            flags = Flags(url=inp.env["TB_DB_URL"])
            value = flags.row(box_hold.FLAG)
            got = {"state": "released", "stored": value is not None}
            if value == "held":
                last = next(iter(flags.events(box_hold.FLAG, limit=1)), {})
                got = {
                    "state": "held",
                    "stored": True,
                    "by": str(last.get("actor") or ""),
                    "at": str(last.get("at") or ""),
                    "reason": str(last.get("reason") or ""),
                }
            elif value not in (None, "released"):
                got = box_hold.unread(f"the hold holds {str(value)[:40]!r}, not a value the box declares")
        except Exception as e:  # never a pass: the hold may be on
            got = box_hold.unread(f"{type(e).__name__} from the trial database (TB_DB_URL)")
    else:
        return Check(name, "PASS", "no trial database configured here (TB_DB_URL): there is no hold to read")
    return _hold_line(got)


def _hold_line(got: Mapping[str, Any]) -> Check:
    """H-136: one line per reading of the hold (``box_hold.read``)."""
    name = "restore_hold"
    release = "set screening.after_restore to released on /ops/flags with the reason, then confirm"
    if got.get("state") == "held":
        since = " ".join(
            x for x in (f"since {got['at']}" if got.get("at") else "", f"by {got['by']}" if got.get("by") else "") if x
        )
        return Check(
            name,
            "WARN",
            f"HELD{f' {since}' if since else ''}: the box's list jobs are held after a restore "
            f"({got.get('reason') or 'no reason recorded'}): no patient list is made. Re-apply the events "
            f"the restore listed, then {release} (RUNBOOK §5, step 4)",
        )
    if got.get("state") == "released":
        if not got.get("stored"):
            return Check(name, "PASS", "released: the hold after a restore was never set on this box")
        since = f" (last change {got.get('at') or '?'} by {got.get('by') or '?'})"
        return Check(name, "PASS", f"released{since}: no restore is waiting for its events to be re-applied")
    cause = got.get("cause") or "no cause"
    return Check(
        name,
        "FAIL",
        f"UNREADABLE: the hold after a restore cannot be read ({cause}); "
        "the box may be held (no patient list). Read screening.after_restore on /ops/flags, then run "
        "trialbox doctor again on the box's host (RUNBOOK §5, step 4)",
    )


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
    """D-274 (CR-058, OPS-028, OPS-048): targets, an off-box one, an alert route, the schedule (H-92), the newest good
    backup's age, WAL archiving. In PRODUCTION every problem is a FAIL except archiving off (WARN)."""
    if inp.platform:
        return Check(
            "backup", "PASS", "not a host check on a platform: see backup_target and backup_job (no host cron)"
        )
    from tools.trialbox import backup_schedule as bs

    prod = (inp.env.get("TB_ENV") or "PRODUCTION").upper() == "PRODUCTION"
    if inp.deploy is None:
        why = "the deploy folder is not known: run with --env-file deploy/.env"
        return Check("backup", "FAIL" if prod else "WARN", why)
    cfg = bs.config(inp.deploy, dict(inp.env), process_env=False)
    st = bs.status(cfg)
    fails = list(st["problems"])
    # H-92: the timer where systemd is the init, else the cron file and a cron daemon; one action when none fires
    running = inp.cron_running() if inp.cron_running is not None else None
    # every backup timer, enabled and running (D-1090); the host is asked only from the command line (inputs_from)
    word = inp.timer_state or inp.backup_timers or (lambda unit: None)
    sched = bs.schedule_state(inp.cron_dir, {t: word(t) for t in bs.TIMERS}, running)
    if sched["problem"]:
        fails.append(sched["problem"])
    warns = [sched["warn"]] if sched["warn"] else []
    old_form = ""
    with contextlib.suppress(OSError):  # H-88: a schedule installed before the tools brought their own environment
        old_form = bs.cron_old_form((inp.cron_dir / bs.CRON_NAME).read_text(encoding="utf-8"))
        if old_form:
            warns.append(f"{inp.cron_dir / bs.CRON_NAME} is of the old form ({old_form}): run python3 -m "
                         "tools.trialbox backup-install --deploy deploy again to replace it (RUNBOOK §5)")  # fmt: skip
    if cfg.page_only(bs.has_mta()):
        warns.append("the only backup alert route is the health page: nobody is mailed, someone must open /admin "
                     "every working day (TB_BACKUP_ALERT_ROUTE, D-735; RUNBOOK §5); " + cfg.page_watch())  # fmt: skip
    if not cfg.archive_on:
        warns.append("WAL archiving is off: a crash loses up to a day (TB_PG_ARCHIVE_MODE, RUNBOOK §5)")
    off = sum(t["offbox"] for t in st["targets"])
    good = st["newest_good"]
    facts = f"schedule: {sched['active']}; {len(cfg.targets)} target(s), {off} off-box; newest good " + (
        f"{Path(good['path']).name} ({st['age_hours']} h old)" if good else "none")  # fmt: skip
    if fails:
        return Check("backup", "FAIL" if prod else "WARN", "; ".join(fails + warns) + f" ({facts})")
    if warns and (prod or old_form):  # H-88: the old-form schedule is said in every environment
        return Check("backup", "WARN", "; ".join(warns) + f" ({facts})")
    return Check("backup", "PASS", facts)


def _tenth_below(speed: float) -> str:
    """A tenth of ``speed`` rounded DOWN to two significant digits: a value that, once set, clears the warning."""
    import math

    tenth = speed / 10
    if tenth <= 0:
        return "0"
    step = 10 ** (math.floor(math.log10(tenth)) - 1)
    return f"{math.floor(tenth / step) * step:.10g}"


def check_backup_speed(inp: DoctorInputs) -> Check:
    """NEW-WIN-7 (D-608; D-455): under WSL2 a backup step's time limit must fit the measured speed of its path."""
    from tb_common.config import DECLARED

    name = "backup_speed"
    if not _wsl2_kernel(inp):
        return Check(name, "PASS", "not WSL2: the backup paths are the box's own disks and mounts (D-455)")
    if inp.deploy is None:
        return Check(name, "WARN", "WSL2: the backup paths were not judged: give --env-file <deploy/.env>")
    from tools.trialbox import backup_schedule as bs

    cfg = bs.config(inp.deploy, dict(inp.env), process_env=False)
    bad = [e for e in cfg.setting_errors if "TB_BACKUP_MIN_MBPS" in e]
    if bad:
        return Check(name, "FAIL", "; ".join(bad))
    if not cfg.targets:
        return Check(name, "WARN", "WSL2: no backup target (TB_BACKUP_TARGETS): no path to measure")
    raw = str(inp.env.get("TB_BACKUP_SPEED_TEST_MIB") or DECLARED["TB_BACKUP_SPEED_TEST_MIB"].default).strip()
    least = int(raw) if raw.isascii() and raw.isdigit() else int(DECLARED["TB_BACKUP_SPEED_TEST_MIB"].default)
    speeds = bs.measured_speeds(inp.deploy)
    fails: list[str] = []
    warns: list[str] = []
    good: list[str] = []
    for target in cfg.targets:
        try:
            real = str(target.resolve())
        except OSError:
            real = str(target)
        got = speeds.get(real, speeds.get(str(target)))
        how = f"wsl-setup.sh backup-speed {target} {least}"
        if got is None:
            warns.append(f"{target}: not measured ({how})")
            continue
        speed, written = got
        to = _tenth_below(speed)
        if written < least:
            # a small write ends in the write cache and reads far too fast: never the ground for a PASS
            warns.append(
                f"{target}: measured with {written} MiB only, which the write cache hides: measure again ({how})"
            )
        elif cfg.min_mbps > speed:
            # the limit assumes the path is faster than it is: every large step would be stopped as hung
            fails.append(f"{target}: measured {speed:g} MB/s, and TB_BACKUP_MIN_MBPS is {cfg.min_mbps:g}: a backup "
                         f"step would be stopped as hung. Set it to {to} (a tenth, D-455)")  # fmt: skip
        elif cfg.min_mbps > speed / 10:
            warns.append(f"{target}: measured {speed:g} MB/s; TB_BACKUP_MIN_MBPS {cfg.min_mbps:g} is more than a "
                         f"tenth of it (D-455): a slow night could be stopped. Set it to {to}")  # fmt: skip
        else:
            good.append(f"{target} {speed:g} MB/s")
    if fails:
        return Check(name, "FAIL", "; ".join(fails + warns))
    if warns:
        return Check(name, "WARN", "; ".join(warns))
    return Check(name, "PASS", f"TB_BACKUP_MIN_MBPS {cfg.min_mbps:g} is at most a tenth of each path's measured "
                 f"speed ({', '.join(good)}). Measure again when a share or a drive is changed")  # fmt: skip


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


def check_key_custody_record(inp: DoctorInputs) -> Check:
    """TB-SOP-03 (D-893): a VALIDATION or PRODUCTION box whose keys are under a KEK has the key ceremony's record
    (IQ-05), made by ``python -m tools.keys ceremony-record`` for that KEK; a TPM box's escrow set (D-894) is of the
    current KEK and on the newest record. A WARN, never a FAIL: no install gate."""
    from tb_common import kek

    from tools import key_ceremony as kc

    name = "key_ceremony"
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    if env not in kek.STRICT_ENVS:
        return Check(name, "PASS", f"{env}: no key ceremony record is asked for")
    sec = Path(inp.env.get("TB_SECRETS_DIR") or "/run/secrets/trialbox")
    c = kek.custody(sec, {**os.environ, **inp.env}) if sec.is_dir() else None
    if c is None or c.backend is None:
        return Check(name, "PASS", "no KEK yet: the ceremony comes with python -m tools.keys init")
    from tools import key_escrow as ke

    try:
        meta = kek.read_meta(sec)
    except kek.KekError:
        meta = None
    esc = ke.current(meta)
    if esc is not None and ke.stale(meta):
        return Check(name, "WARN", f"the escrow set {esc.get('set_id')} is of an older KEK ({esc.get('kek_id')}); the "
                     f"KEK is now {c.kek_id}: its shares open nothing here. A new set: python -m tools.keys "
                     "escrow-shares (TB-SOP-03 §5)")  # fmt: skip
    rec = kc.newest(inp.deploy or ROOT / "deploy")
    how = ("python -m tools.keys ceremony-record --custodian ... --witness ..., printed and signed "
           "(docs/security/10-key-ceremony-and-escrow.md)")  # fmt: skip
    if rec is None:
        return Check(name, "WARN", f"no key ceremony record for KEK {c.kek_id} ({c.backend}) in deploy/site: {how}")
    if (rec.get("kek") or {}).get("kek_id") != c.kek_id:
        return Check(name, "WARN", f"the newest ceremony record is of KEK {(rec.get('kek') or {}).get('kek_id')}; "
                     f"the KEK is now {c.kek_id} (rotate-kek since): a new record, {how}")  # fmt: skip
    if esc is not None and (rec.get("escrow") or {}).get("set_id") != esc.get("set_id"):
        return Check(name, "WARN", f"the escrow set {esc.get('set_id')} was made after the newest ceremony record: "
                     f"a new record lists it and its custodians sign, {how}")  # fmt: skip
    note = "; NOT a site's ceremony (passphrase back end)" if rec.get("not_a_site_ceremony") else ""
    return Check(name, "PASS", f"ceremony record of {str(rec.get('at'))[:10]} for KEK {c.kek_id}, "
                 f"{len(rec.get('custodians') or [])} custodian(s){note}")  # fmt: skip


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


OPS_TIMER = "trialbox-ops.timer"


def _timer_state(unit: str) -> str | None:
    """``systemctl is-enabled``'s word for ``unit`` (enabled, disabled, not-found, ...); None where systemd cannot
    be asked (a container, a platform, a developer's machine)."""
    import shutil
    import subprocess

    if not Path("/run/systemd/system").is_dir() or shutil.which("systemctl") is None:
        return None
    try:
        r = subprocess.run(["systemctl", "is-enabled", unit], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return (r.stdout.strip().splitlines() or ["unknown"])[0]


def check_ops_runner(inp: DoctorInputs, now: datetime | None = None) -> Check:
    """NEW-OPS-8 (OPS-009, D-561): the host runner (``trialbox-ops.timer``) writes the health facts every minute and
    runs the Operations page's requests. Its own record says whether it runs: facts that are missing or older than
    the health line's limit are a FAIL in VALIDATION and PRODUCTION (WARN elsewhere), with the timer's state."""
    if inp.platform:
        return Check("ops_runner", "PASS", "not a host check on a platform (pods; no host timer)")
    from tb_common import metrics

    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    soft: Status = "FAIL" if env in ("VALIDATION", "PRODUCTION") else "WARN"
    raw = (inp.env.get("TB_OPS_DIR") or "").strip()
    if not raw and inp.deploy is None:
        return Check("ops_runner", soft, "the deploy folder is not known: run with --env-file deploy/.env")
    record = (Path(raw) if raw else (inp.deploy or ROOT / "deploy") / "ops") / "status.json"
    seen: datetime | None = None
    try:
        doc = json.loads(record.read_text(encoding="utf-8"))
        at = (doc.get("health") or {}).get("at") if isinstance(doc, dict) else None
        seen = datetime.fromisoformat(str(at)) if at else None
    except (OSError, ValueError):
        seen = None
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    age = (now - seen).total_seconds() / 3600 if seen is not None else None
    if age is not None and abs(age) <= metrics.FACTS_STALE_H:  # a record dated ahead of the clock is not fresh
        return Check("ops_runner", "PASS", f"the runner wrote its record {max(age, 0) * 60:.0f} min ago ({record})")
    state = (inp.timer_state or _timer_state)(OPS_TIMER)
    what = f"the runner has never written {record}" if age is None else f"the runner's record is {age:.0f} h old"
    if age is not None and age < 0:
        what = f"the runner's record is dated {-age:.0f} h after this clock"
    if state == "enabled":
        fix = (
            f"{OPS_TIMER} is enabled: see systemctl status trialbox-ops.service and journalctl -u trialbox-ops.service"
        )
    else:
        is_now = f"{OPS_TIMER} is {state}; " if state else ""
        fix = f"{is_now}turn it on: systemctl enable --now {OPS_TIMER} (RUNBOOK §15)"
    return Check("ops_runner", soft, f"{what}: no health facts, and the Operations page's requests wait; {fix}")


@_supplied("tools.trialbox.doctor_m4")
def check_audit_heads(inp: DoctorInputs, now: datetime | None = None) -> Check:
    """NEW-STD-2 (STD-002, D-562) and M4: the signed audit heads of D-355 against the chain, in the four states of
    the anchor (ok, missing, stale, tampered; a restored trail is named apart). FAIL only for a trail that does not
    agree with a signed head and a missing signing key; losing the anchor is a WARN (PRODUCTION names the gate).
    The body is ``tools.trialbox.audit_heads.doctor_checks``."""
    if inp.platform:  # nothing signs heads on a platform yet: said, not passed (the review's M6)
        return Check("audit_heads", "WARN", "on a platform no host cron signs the audit head: STD-002 is open there")
    from tools.trialbox import audit_heads

    _, status, detail = audit_heads.doctor_checks(inp.env, inp.deploy or ROOT / "deploy", now)[0]
    return Check("audit_heads", status, detail)  # type: ignore[arg-type]


def _public_roots() -> frozenset[bytes]:
    """The public roots this process trusts (DER): what the image, or the host, ships as its bundle."""
    import ssl

    try:
        return frozenset(ssl.create_default_context().get_ca_certs(binary_form=True))
    except (ssl.SSLError, OSError):
        return frozenset()


def check_ldap_ca(inp: DoctorInputs) -> Check:
    """AUTHELIA-CA (D-722): with the hospital sign-in on, Authelia's whole root list is the file ``TB_LDAP_CA``
    (the identity overlay mounts it and points Go's certificate lookup at it). FAIL in VALIDATION and PRODUCTION
    (WARN elsewhere) when it is not set, cannot be read, holds no certificate, holds a private key, or holds a
    certificate that is also one of the public roots this machine trusts (a hospital's own CA never is: the file is
    then a public root list under another name, which undoes the card). The content is read, not the path; a key's
    content is never shown."""
    import ssl

    name = "ldap_ca"
    if (inp.env.get("TB_OIDC_ENABLED") or "").strip().lower() not in ("1", "true", "on", "yes"):
        return Check(name, "PASS", "the hospital sign-in is off: Authelia does not run")
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    bad: Status = "FAIL" if env in ("VALIDATION", "PRODUCTION") else "WARN"
    given = (inp.env.get("TB_LDAP_CA") or "").strip().strip('"').strip("'").strip()
    if not given:
        return Check(name, bad, "the hospital sign-in is on and TB_LDAP_CA is not set: Authelia has no root to check "
                                "the directory's certificate against, so no hospital account signs in. Set it in "
                                "deploy/.env to the hospital's directory CA chain, one PEM file (RUNBOOK section 12, "
                                "D-722)")  # fmt: skip
    if not given.startswith(("/", "./", "../")):
        return Check(name, bad, f"TB_LDAP_CA={given}: write the file's path from / or with ./ in front (from "
                                "deploy/): compose reads a bare name as a volume's name, not as a file")  # fmt: skip
    path = Path(given)
    if not path.is_absolute():
        path = (inp.deploy or ROOT / "deploy") / path
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return Check(name, bad, f"TB_LDAP_CA={given} cannot be read ({type(exc).__name__}): Authelia has no root to "
                                "check the directory's certificate against")  # fmt: skip
    if "PRIVATE KEY-----" in text:
        return Check(name, bad, f"TB_LDAP_CA={given} holds a private key: it is the CA's certificates only (a key "
                                "never belongs in this file)")  # fmt: skip
    ders: list[bytes] = []
    for block in text.replace("\r\n", "\n").split("-----BEGIN CERTIFICATE-----")[1:]:
        body = block.split("-----END CERTIFICATE-----")[0]
        try:
            der = ssl.PEM_cert_to_DER_cert(f"-----BEGIN CERTIFICATE-----{body}-----END CERTIFICATE-----\n")
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=der)  # a certificate, not just base64
        except (ValueError, ssl.SSLError):
            continue
        ders.append(der)
    if not ders:
        return Check(name, bad, f"TB_LDAP_CA={given} holds no certificate (PEM, BEGIN CERTIFICATE): Authelia has no "
                                "root to check the directory's certificate against")  # fmt: skip
    public = sum(1 for der in ders if der in _public_roots())
    if public:
        return Check(name, bad, f"TB_LDAP_CA={given}: {public} of its {len(ders)} certificate(s) are public root "
                                "certificates of this machine's own list. Authelia would trust a public certificate "
                                "authority for the directory's name. Give it the hospital's own directory CA chain "
                                "only (D-722)")  # fmt: skip
    return Check(name, "PASS", f"Authelia's only roots are the {len(ders)} certificate(s) of TB_LDAP_CA: none is a "
                               "public root")  # fmt: skip


def check_anchor_mount(inp: DoctorInputs) -> Check:
    """ANCHOR-MOUNT (D-638): the console's audit page checks the chain against the signed heads only when the anchor
    folders are mounted into the console (``deploy/site/compose.anchors.yml``, written by the installer). WARN when
    folders are set and the console does not get them: the night and ``tools/audit_verify.py --heads`` still check
    the heads; the page then checks the chain against itself only."""
    from tools.trialbox import anchors

    if inp.platform:
        return Check("anchor_mount", "PASS", "on a platform the console's folders are the cluster's to mount")
    why = anchors.problem(inp.deploy or ROOT / "deploy", inp.env)
    if why:
        return Check(
            "anchor_mount",
            "WARN",
            f"the audit page cannot check the signed heads: {why}. Run deploy/install.sh again: it mounts each "
            f"folder of {anchors.ENV} into the console, read-only (D-638)",
        )
    if not (inp.env.get(anchors.ENV) or "").strip():
        return Check("anchor_mount", "PASS", "no anchor folder is set (check audit_heads says what that means)")
    return Check("anchor_mount", "PASS", "the console mounts every anchor folder, read-only")


STANDINS_MARK = "x-trialbox-rehearsal-standins: true"


def _standins_in_compose(inp: DoctorInputs) -> str:
    """The first file of ``COMPOSE_FILE`` that says it is the model stand-ins (D-726), or ``""``."""
    base = inp.deploy or ROOT / "deploy"
    for entry in (inp.env.get("COMPOSE_FILE") or "").split(":"):
        if not entry.strip():
            continue
        path = Path(entry.strip())
        path = path if path.is_absolute() else base / path
        try:
            if STANDINS_MARK in path.read_text(encoding="utf-8").splitlines():
                return str(path)
        except (OSError, UnicodeDecodeError):
            continue
    return ""


BENCH_SERVING_MARK = "x-trialbox-bench-serving: true"
# the mark as compose still reads it: blanks and a trailing comment allowed (OCR 1459-7)
_BENCH_MARK_LINE = re.compile(r"^x-trialbox-bench-serving:\s*true\s*(?:#.*)?$", re.M)


def check_bench_serving(inp: DoctorInputs) -> Check:
    """H-112: the second serving profile (deploy/docker-compose.serving-second.yml, marked BENCH_SERVING_MARK) runs
    the models with an engine that is in no signed bundle, not in deploy/images.lock and with no key check of its
    own: on a TEST box it is a standing WARN, on a box of any other class (PRODUCTION when unset) a FAIL. It is on
    when its file is in COMPOSE_FILE (a hand edit) or when the switch in deploy/site/serving-second.env says
    ``second`` (tools/serving_profile.py adds the file on the command line, never to COMPOSE_FILE); a switch that
    cannot be read counts as on (OCR 1459-3)."""
    from tools import serving_profile

    base = inp.deploy or ROOT / "deploy"
    found = ""
    for entry in (inp.env.get("COMPOSE_FILE") or "").split(":"):
        if not entry.strip():
            continue
        path = _compose_file(base, entry.strip())
        try:
            if _BENCH_MARK_LINE.search(path.read_text(encoding="utf-8")):
                found = f"{path}, deploy/.env COMPOSE_FILE"
                break
        except (OSError, UnicodeDecodeError):
            continue
    if not found:
        try:
            on = serving_profile.switch(base) == "second"
        except serving_profile.Refused:
            on = True  # a switch that cannot be read, or says something else, is never taken for off
        if on:
            found = f"the switch in {base / serving_profile.SETTINGS}"
    if not found:
        return Check("bench_serving", "PASS", "the models are served by the current serving engine")
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().strip("\"'").strip().upper()
    if env == "TEST":
        return Check("bench_serving", "WARN", f"BENCH SERVING: the second serving engine serves the models ({found}): "
                                              "for the engine comparison only, not a pinned image (H-112)")  # fmt: skip
    return Check("bench_serving", "FAIL", f"the second serving profile is on for a {env} box ({found}): its engine "
                                          "is in no signed bundle and checks no key of its own. Set SERVING_ENGINE "
                                          "to current and take the file out of COMPOSE_FILE (H-112)")  # fmt: skip


def check_prefix_cache(inp: DoctorInputs) -> Check:
    """H-146 (D-1462): the judge and verifier servers' prefix cache, off unless the box chooses it. Off (the
    default: ``TB_LLM_PREFIX_CACHING`` absent, empty or ``no-enable``) is a PASS; ``enable`` a standing WARN (the
    same calls may then answer differently from run to run); another value a FAIL (the servers refuse to start).
    With the box's rendered compose (``--compose-config``), each server there must carry the flag the setting
    names."""
    from tools import prefix_cache

    env = dict(inp.env)
    if inp.deploy is not None and prefix_cache.SETTING not in os.environ:
        # review 1514-1: deploy/.env as compose reads it (an "export", a comment after an unquoted value)
        from tools import rehearsal_real

        env.pop(prefix_cache.SETTING, None)
        env.update({k: v for k, v in rehearsal_real.env_file(inp.deploy / ".env").items() if k == prefix_cache.SETTING})
    try:
        word = prefix_cache.state(env)
    except ValueError as exc:
        detail = f"{exc}: the model servers may refuse to start or run another option; set {prefix_cache.SETTING}"
        return Check("prefix_cache", "FAIL", detail + " to no-enable (off) in deploy/.env (D-1462)")
    if inp.compose_config is not None:
        want = prefix_cache.flag(word)
        services = inp.compose_config.get("services") or {}
        bad = [
            name
            for name in ("llm-service", "llm-verifier")
            if isinstance(services.get(name), Mapping)
            and [a for a in services[name].get("command") or [] if str(a).endswith("prefix-caching")] != [want]
        ]
        if bad:
            return Check("prefix_cache", "FAIL", f"{', '.join(bad)}: the rendered command does not carry {want} "
                                                 f"({prefix_cache.SETTING}); a GPU overlay without the line runs "
                                                 "the model server's own default (D-1462)")  # fmt: skip
    if word == "on":
        return Check("prefix_cache", "WARN", f"prefix caching on ({prefix_cache.SETTING}=enable): runs may differ "
                                             "from run to run on the same calls (D-1462)")  # fmt: skip
    seen = (
        "the rendered servers"
        if inp.compose_config is not None
        else "the setting (--compose-config checks the servers)"
    )
    return Check("prefix_cache", "PASS", f"prefix caching off on the judge and verifier servers: {seen} (D-1462)")


def _real_servers(inp: DoctorInputs) -> tuple[str, str] | None:
    """H-89: (where, what the box says) when this box ran the real model servers as a rehearsal, else None."""
    from tools import rehearsal_real

    deploy = inp.deploy or ROOT / "deploy"
    where = rehearsal_real.real_servers_sign(deploy, dict(inp.env))
    if not where:
        return None
    try:
        said = str(json.loads((deploy / "site" / rehearsal_real.RECORD).read_text(encoding="utf-8"))["words"])
    except (OSError, ValueError, KeyError, TypeError):
        said = rehearsal_real.WORDS  # the record is gone or unreadable: the compose file alone says the most
    return where, said


def check_rehearsal(inp: DoctorInputs) -> Check:
    """REHEARSAL (D-726, D-887): a rehearsal box says so. ``deploy/install.sh --rehearsal`` writes the mark
    ``deploy/site/rehearsal.json``, then ``TB_REHEARSAL=1`` and ``TB_ENV`` to deploy/.env: VALIDATION since the
    integrator's (i) (D3 stays on the box, so SCREEN reaches the pinned builds), TEST before. On a rehearsal box the
    line is a standing WARN no setting turns off: "REHEARSAL BOX: placeholder models, synthetic data only". A
    VALIDATION box needs both marks (TB_REHEARSAL=1 alone, or the file alone, is a site box touched by hand); a mark
    on a box of any other environment FAILs (someone changed TB_ENV of a rehearsal box by hand)."""
    test = check_test_box(inp)  # H-106: a test box (never a rehearsal box) says so on this line
    if test.status != "PASS":
        return test
    flag = (inp.env.get("TB_REHEARSAL") or "").strip() == "1"
    mark = _site_dir(inp) / "rehearsal.json"
    has_mark = mark.is_file()
    # H-89: the real servers' record or compose file is a mark of its own (removing rehearsal.json is not enough)
    real = _real_servers(inp)
    marked = flag or has_mark or bool(real)
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().strip("\"'").strip().upper()
    rehearsal = (env == "TEST" and marked) or (env == "VALIDATION" and flag and has_mark)
    standins = _standins_in_compose(inp)
    if standins and not rehearsal:
        what = env if env != "TEST" else "TEST box that is no rehearsal box"
        return Check(
            "rehearsal",
            "FAIL",
            f"the model stand-ins are in the compose files of a {what} ({standins}, deploy/.env COMPOSE_FILE): "
            "they answer instead of the pinned models. Run deploy/install.sh without TB_COMPOSE_OVERRIDE (D-726)",
        )
    if not marked:
        return Check("rehearsal", "PASS", "not a rehearsal box")
    if real and not (env == "VALIDATION" and flag and has_mark):
        return Check("rehearsal", "FAIL", f"{real[1]}: {real[0]} on a {env} box that is no whole rehearsal box "
                                          "(TB_REHEARSAL=1 and the mark file): install the site's box afresh on an "
                                          "empty box, never this one (H-89)")  # fmt: skip
    if real:
        return Check("rehearsal", "WARN", f"REHEARSAL BOX: {real[1]}; the real model servers ({real[0]}); synthetic "
                                          "data only, never a site's patients; nothing is qualified or promoted on "
                                          "it (H-89, D-726, D-887)")  # fmt: skip
    if not rehearsal:
        half = " (a VALIDATION rehearsal box has both TB_REHEARSAL=1 and the mark file)" if env == "VALIDATION" else ""
        return Check(
            "rehearsal",
            "FAIL",
            f"a rehearsal mark (TB_REHEARSAL=1 or {mark}) on a {env} box{half}: a rehearsal box is made by "
            "deploy/install.sh --rehearsal only. Install the site's box afresh (deploy/install.sh without "
            "--rehearsal, on an empty box), never this one",
        )
    return Check(
        "rehearsal",
        "WARN",
        f"REHEARSAL BOX: placeholder models, synthetic data only (a {env} rehearsal box; the model stand-ins and "
        "an unmeasured card are allowed; never a site's patients; nothing is qualified or promoted on it; D-726, "
        "D-887)",
    )


def check_test_box(inp: DoctorInputs) -> Check:
    """TEST BOX (H-106): one of several test boxes on a host says so, on every run, as a standing WARN no setting
    turns off. Its record (``deploy/site/test-box.env``, written by ``deploy/install.sh --test-box``) and deploy/.env
    must agree on its project, and the box must be TEST or DEV: anything else FAILs (a record copied between folders,
    edited by hand, or a test box turned into another kind)."""
    from tools.trialbox import testbox

    deploy = _site_dir(inp).parent
    try:
        box = testbox.load(deploy)
    except testbox.Refused as exc:
        return Check("rehearsal", "FAIL", str(exc))
    named = (inp.env.get("TB_TEST_BOX") or "").strip()
    if box is None:
        if named:
            return Check("rehearsal", "FAIL", f"TB_TEST_BOX={named} in deploy/.env with no record (deploy/"
                                             f"{testbox.RECORD}): a test box is made by deploy/install.sh "
                                             "--test-box only")  # fmt: skip
        return Check("rehearsal", "PASS", "not a test box")
    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().strip("\"'").strip().upper()
    project = (inp.env.get("COMPOSE_PROJECT_NAME") or "").strip()
    if named != box.name or project != box.project:
        return Check("rehearsal", "FAIL", f"deploy/.env (TB_TEST_BOX={named or '-'}, COMPOSE_PROJECT_NAME="
                                         f"{project or '-'}) is not test box {box.name}'s record (project "
                                         f"{box.project}): its commands would reach another box; run its "
                                         "install again")  # fmt: skip
    if env not in ("DEV", "TEST"):
        return Check("rehearsal", "FAIL", f"test box {box.name} says TB_ENV={env}: a test box is TEST or DEV only")
    return Check("rehearsal", "WARN", box.words())


def check_postgres_memory(inp: DoctorInputs) -> Check:
    """T-703 (D-751, scale review F-19): PostgreSQL's buffers against the host (``tools.trialbox.pgsize``)."""
    from tools.trialbox import pgsize

    if inp.deploy is None:
        return Check("postgres_memory", "WARN", "PostgreSQL's sizes were not judged: give --env-file <deploy/.env>")
    status, detail = pgsize.check(inp.env, inp.proc)
    return Check("postgres_memory", status, detail)


def check_memory_caps(inp: DoctorInputs) -> Check:
    """T-692 (D-473, scale review F-05): the adapter's, the lake's and (H23b-01, D-1005) the orchestrator's memory
    caps against the patient count (``tools.trialbox.memcaps``)."""
    from tools.trialbox import memcaps

    deploy = inp.deploy or ROOT / "deploy"
    record, compose = deploy / "measured" / "ingest_memory.json", deploy / "docker-compose.yml"
    if not record.is_file() or not compose.is_file():
        return Check("memory_caps", "WARN", f"{record} or {compose} is not here: the memory caps were not checked")
    lake = inp.ingest_lake or (Path(inp.env["TB_LAKE_DIR"]) if inp.env.get("TB_LAKE_DIR") else None)
    orch = deploy / "measured" / "orchestrator_memory.json"
    status, detail = memcaps.check(inp.env, lake, record, compose, orch if orch.is_file() else None)
    return Check("memory_caps", "FAIL" if status == "FAIL" else "WARN" if status == "WARN" else "PASS", detail)


_MEM_SIZE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([kmg]?)b?$", re.IGNORECASE)
_MEM_VAR = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}$")


def _mem_gib(raw: str) -> float:
    """A compose memory size in GiB: plain bytes, or a number with k, m or g (an optional b; any case)."""
    m = _MEM_SIZE.match(raw.strip())
    if not m:
        raise ValueError(raw)
    return float(m.group(1)) * {"": 1.0, "k": 1024.0, "m": 1024.0**2, "g": 1024.0**3}[m.group(2).lower()] / 1024.0**3


_COMPOSE_TAG = re.compile(r"(?<=[\s:\[,])!(?:reset|override)\b")  # compose's own YAML tags: the value below is plain


def _service_caps(files: list[Path], env: Mapping[str, str]) -> tuple[dict[str, float], list[str], list[str]]:
    """(the memory cap in GiB of each service that runs, the services with no cap, problems) over the compose files,
    read as compose reads them: a later file's service overrides the same key of an earlier one, a service behind a
    profile counts only when ``COMPOSE_PROFILES`` names it, a ``${VAR:-default}`` takes the box's value."""
    merged: dict[str, dict[str, Any]] = {}
    for f in files:
        doc = yaml.safe_load(_COMPOSE_TAG.sub("", f.read_text(encoding="utf-8"))) or {}
        for svc, body in (doc.get("services") or {}).items():
            if isinstance(body, dict):
                merged.setdefault(svc, {}).update(body)
    active = {p.strip() for p in (env.get("COMPOSE_PROFILES") or "").split(",") if p.strip()}
    caps: dict[str, float] = {}
    uncapped: list[str] = []
    problems: list[str] = []
    for svc, body in sorted(merged.items()):
        profiles = body.get("profiles") or []
        if profiles and not active.intersection(profiles):
            continue
        limits = ((body.get("deploy") or {}).get("resources") or {}).get("limits") or {}
        raw = body.get("mem_limit", limits.get("memory"))
        if raw is None:
            uncapped.append(svc)
            continue
        text = str(raw).strip()
        var = _MEM_VAR.match(text)
        if var:
            text = (env.get(var.group(1)) or "").strip() or (var.group(2) or "").strip()
        try:
            caps[svc] = _mem_gib(text)
        except ValueError:
            problems.append(f"{svc}: '{raw}' is not a memory size" + (f" ({var.group(1)}={text!r})" if var else ""))
    return caps, uncapped, problems


def check_wsl2_memory(inp: DoctorInputs) -> Check:
    """NEW-WIN-3 (D-601): under WSL2 the compose memory caps must fit the memory ``.wslconfig`` gave WSL2."""
    from tb_common.config import DECLARED

    name = "wsl2_memory"
    try:
        kernel = (inp.proc / "sys/kernel/osrelease").read_text(encoding="utf-8").strip().lower()
    except OSError:
        kernel = ""
    if "microsoft" not in kernel or "wsl2" not in kernel:
        return Check(name, "PASS", "not WSL2: the machine's whole memory is the box's")
    if inp.deploy is None:
        return Check(name, "WARN", "WSL2: the memory caps were not judged: give --env-file <deploy/.env>")
    total = 0.0
    try:
        for line in (inp.proc / "meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) / 1048576
    except (OSError, ValueError, IndexError):
        total = 0.0
    if total <= 0:
        return Check(name, "FAIL", f"WSL2's memory could not be read from {inp.proc}/meminfo")
    entries = [e for e in (inp.env.get("COMPOSE_FILE") or "docker-compose.yml").split(":") if e]
    files = [_compose_file(inp.deploy, e) for e in entries]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:  # never a pass on a part of the box: a file that cannot be read may hold the largest cap
        return Check(name, "FAIL", f"compose file(s) not readable, the caps were not summed: {', '.join(missing)}")
    try:
        caps, uncapped, problems = _service_caps(files, inp.env)
    except yaml.YAMLError as exc:
        return Check(name, "FAIL", f"a compose file does not parse, the caps were not summed: {exc}")
    if problems:
        return Check(name, "FAIL", "; ".join(problems))
    need = sum(caps.values())
    said = (
        f"the memory caps of the {len(caps)} services that run sum to {need:.1f} GiB (the model servers at their caps)"
    )
    if uncapped:
        said += f"; no cap on {', '.join(uncapped)}"
    if need > total:
        share = DECLARED["TB_WSL_DESKTOP_SHARE_PCT"].default
        top = ", ".join(f"{k} {v:.1f}" for k, v in sorted(caps.items(), key=lambda kv: -kv[1])[:3])
        return Check(name, "FAIL", f"{said}; WSL2 has {total:.1f} GiB (.wslconfig): a service would be killed. "
                     f"Largest: {top}. Start the Windows installer again (it sets .wslconfig from the hardware; the "
                     f"desktop's share is {share} percent unless the installer was given another, "
                     "TB_WSL_DESKTOP_SHARE_PCT), then restart Windows")  # fmt: skip
    if uncapped:
        return Check(name, "WARN", f"{said}; WSL2 has {total:.1f} GiB")
    return Check(name, "PASS", f"{said}; WSL2 has {total:.1f} GiB")


def _compose_file(deploy: Path, entry: str) -> Path:
    """One entry of ``COMPOSE_FILE`` as this process can read it. ``install.sh`` writes the host's absolute paths
    (``$ROOT/deploy/...``); the doctor may run in the box's image, where the same folder is mounted elsewhere
    (``check_host.sh``): an absolute path that is not here is read as its part below ``deploy/`` in the deploy
    folder given."""
    path = Path(entry)
    if not path.is_absolute():
        return deploy / path
    if path.exists():
        return path
    parts = path.parts
    if "deploy" in parts:
        below = parts[len(parts) - parts[::-1].index("deploy") :]
        return deploy.joinpath(*below) if below else path
    return path


def _wsl2_kernel(inp: DoctorInputs) -> str:
    """The kernel's release when it is a WSL2 kernel, else ``""``."""
    try:
        kernel = (inp.proc / "sys/kernel/osrelease").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return kernel if "microsoft" in kernel.lower() and "wsl2" in kernel.lower() else ""


def check_update_window(inp: DoctorInputs) -> Check:
    """NEW-WIN-5 (D-606): Windows Update may restart the workstation only in a window the night does not start in."""
    from tb_common.config import DECLARED

    name = "update_window"
    if not _wsl2_kernel(inp):
        return Check(name, "PASS", "not WSL2: no Windows Update under the box")
    # what the Windows installer set (deploy/windows/wsl-setup.sh update-window): the window, or "kept"
    told = ""
    if inp.deploy is not None:
        try:
            told = (inp.deploy / "site" / "box" / "windows-update-window").read_text(encoding="utf-8").strip()
        except OSError:
            told = ""
    if told == "kept":
        return Check(name, "WARN", "the site's IT holds the Windows Update policy (the Windows installer kept it): "
                     "the restart hours were not judged against the night here; the host check shows them")  # fmt: skip
    m = re.fullmatch(r"([0-9]{1,2})\+([0-9]{1,2})", told)
    if m:
        raw = {"TB_WIN_UPDATE_WINDOW_START": m.group(1), "TB_WIN_UPDATE_WINDOW_HOURS": m.group(2)}
        confirmed = True
    else:
        raw = {key: str(inp.env.get(key) or DECLARED[key].default).strip()
               for key in ("TB_WIN_UPDATE_WINDOW_START", "TB_WIN_UPDATE_WINDOW_HOURS")}  # fmt: skip
        confirmed = False
    figures: dict[str, int] = {}
    for key, low, high in (("TB_WIN_UPDATE_WINDOW_START", 0, 23), ("TB_WIN_UPDATE_WINDOW_HOURS", 6, 23)):
        if not re.fullmatch(r"[0-9]{1,2}", raw[key]) or not low <= int(raw[key]) <= high:
            return Check(name, "FAIL", f"{key}='{raw[key]}' is not a whole number from {low} to {high}")
        figures[key] = int(raw[key])
    start, hours = figures["TB_WIN_UPDATE_WINDOW_START"], figures["TB_WIN_UPDATE_WINDOW_HOURS"]
    end = (start + hours) % 24
    window = f"Windows Update may restart the workstation from {start:02d}:00 to {end:02d}:00"
    if not confirmed:
        window += (" (the declared window: the Windows installer has not said which window Windows holds; start it "
                   "once more)")  # fmt: skip
    source = inp.settings.get("data_source") if isinstance(inp.settings, Mapping) else None
    at = str(source.get("nightly_at") or "") if isinstance(source, Mapping) else ""
    night_at = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", at)
    if not night_at:
        why = f"nightly_at '{at}' is not HH:MM" if at else "the settings name no nightly_at"
        return Check(name, "WARN", f"{window}; {why}, so the night was not judged against it")
    night = int(night_at.group(1)) * 60 + int(night_at.group(2))
    if (night - start * 60) % 1440 < hours * 60:
        return Check(name, "FAIL", f"{window}, and the night starts at {at}, inside it: a restart would cut the "
                     "night. Move the window (start the Windows installer again with -UpdateWindowStart) or "
                     "nightly_at")  # fmt: skip
    room = (start * 60 - night) % 1440
    # the night starts outside the window; whether it also ends before the window opens is read from the record of
    # the nights that ran (NEW-B-20, D-661: tools/night_length.py, deploy/site/night-length.json)
    from tools.night_length import night_runs

    runs: list[tuple[datetime, datetime, bool]] = []  # began, ended, and whether the end is the whole night's
    for run in night_runs(inp.deploy) if inp.deploy is not None else []:
        try:
            began, ended = datetime.fromisoformat(run["start"]), datetime.fromisoformat(run["end"])
        except (KeyError, ValueError):
            continue
        # NEW-B-26 (D-667): with work_start and work_end the orchestrator's part of the night was measured too, and
        # the night ends when that work ends. Without the two keys only the ingest was measured
        whole = False
        if "work_start" in run and "work_end" in run:
            try:
                work_end = datetime.fromisoformat(run["work_end"])
            except ValueError:
                work_end = None
            if work_end is not None and work_end.utcoffset() is not None and work_end >= ended:
                ended, whole = work_end, True
        runs.append((began, ended, whole))
    if not runs:
        return Check(name, "WARN", f"{window}; the night starts at {at}, {room // 60} h {room % 60:02d} min before "
                     "the window opens. No night's length is recorded on the box yet: keep it shorter")  # fmt: skip
    # each recorded night on the clock of the day it began, in the site's own time (the record carries the offset)
    hit: list[str] = []
    least: int | None = None  # over the nights measured whole
    least_ingest: int | None = None  # over the nights measured to the end of ingest only
    for began, ended, whole in runs:
        first = began.hour * 60 + began.minute
        length = max(0, int((ended - began).total_seconds() // 60))
        into = (first - start * 60) % 1440  # minutes after the window opened that the night began
        before = (start * 60 - first) % 1440  # minutes from the night's start to the window's next opening
        if into < hours * 60 or length > before:
            hit.append(f"{began:%Y-%m-%d} {began:%H:%M} to {ended:%H:%M}")
        elif whole:
            least = before - length if least is None else min(least, before - length)
        else:
            least_ingest = before - length if least_ingest is None else min(least_ingest, before - length)
    if hit:
        return Check(name, "FAIL", f"{window}, and {len(hit)} of the last {len(runs)} recorded nights ran inside it "
                     f"({'; '.join(hit[-3:])}): a restart would have cut the night. Move the window (start the "
                     "Windows installer again with -UpdateWindowStart) or nightly_at")  # fmt: skip
    measured = sum(1 for _b, _e, whole in runs if whole)
    if measured == len(runs) and least is not None:
        # every recorded night was measured to the end of the orchestrator's work, and each ended before the window
        return Check(name, "PASS", f"{window}; the last {len(runs)} recorded nights, measured to the end of the "
                     f"night's work, ended at least {least // 60} h {least % 60:02d} min before it opens")  # fmt: skip
    # not a PASS: some nights are measured only to the end of ingest (the chain did not end, a retry by day), and
    # what the orchestrator did after it is then unknown. The copy on the host is as old as the last backup run
    parts = []
    if least is not None:
        parts.append(f"{measured} measured to the end of the night's work ended at least {least // 60} h "
                     f"{least % 60:02d} min before the window opens")  # fmt: skip
    if least_ingest is not None:
        parts.append(f"{len(runs) - measured} measured only to the end of ingest, at least {least_ingest // 60} h "
                     f"{least_ingest % 60:02d} min before it: the work after ingest is not known for them")  # fmt: skip
    return Check(name, "WARN", f"{window}; of the last {len(runs)} recorded nights, {'; '.join(parts)}")


def _nvidia_smi() -> tuple[str, str] | None:
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
    name, _, driver = line.partition(",")
    return (name.strip(), driver.strip()) if driver.strip() else None


def check_wsl2_versions(inp: DoctorInputs) -> Check:
    """NEW-WIN-5 (D-606): the NVIDIA driver and the WSL2 kernel are the ones the serving record was measured with."""
    name = "wsl2_versions"
    kernel = _wsl2_kernel(inp)
    if not kernel:
        return Check(name, "PASS", "not WSL2: the driver is the Linux host's own (check_host.sh)")
    if inp.deploy is None:
        return Check(name, "WARN", "WSL2: the driver was not judged: give --env-file <deploy/.env>")
    got = (inp.gpu_query or _nvidia_smi)()
    if got is None:
        return Check(name, "FAIL", "WSL2: the card does not answer (nvidia-smi): the Windows NVIDIA driver is missing, "
                     "was replaced, or Windows needs a restart after a driver change")  # fmt: skip
    card, driver = got  # the first card nvidia-smi lists
    # the record of the box's profile (TB_GPU_PROFILE), the site's own first: as deploy/install.sh picks it.
    # Without a profile: the records of this card by name, and never a guess between two
    profile = str(inp.env.get("TB_GPU_PROFILE") or "").strip()
    folders = (inp.deploy / "site", inp.deploy / "measured")
    found: list[tuple[Path, Mapping[str, Any]]] = []
    for folder in folders:
        pattern = f"serving_config.{profile}.json" if profile and profile != "auto" else "serving_config.*.json"
        for path in sorted(folder.glob(pattern)):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and isinstance(doc.get("card"), dict) and doc["card"].get("name") == card:
                found.append((path, doc))
        if found:
            break  # the site's folder wins over the vendor's
    if not found:
        return Check(name, "WARN", f"WSL2: no serving record for the card '{card}' (deploy/site, deploy/measured): "
                     f"driver {driver} and kernel {kernel} were compared with nothing")  # fmt: skip
    if len(found) > 1:
        names = ", ".join(p.name for p, _ in found)
        return Check(name, "WARN", f"WSL2: {len(found)} serving records name the card '{card}' ({names}) and "
                     f"TB_GPU_PROFILE does not say which is the box's: driver {driver} was not compared")  # fmt: skip
    path, doc = found[0]
    where = f"{path.parent.name}/{path.name}"
    measured = str(doc["card"].get("driver") or "").strip()
    if measured != driver:
        return Check(name, "FAIL", f"the NVIDIA driver is {driver}; the serving record ({where}) was measured with "
                     f"{measured or 'no driver named'}. Put the measured driver back (the offline media, "
                     "windows/nvidia), or measure again with this one (tools/serving_config.py measured)")  # fmt: skip
    measured_kernel = str(doc.get("wsl_kernel") or "")
    if not measured_kernel:
        return Check(name, "WARN", f"NVIDIA driver {driver} as measured ({where}); the record names no WSL2 kernel, "
                     f"so the kernel {kernel} was compared with nothing")  # fmt: skip
    if measured_kernel != kernel:
        return Check(name, "FAIL", f"the WSL2 kernel is {kernel}; the serving record ({where}) was measured with "
                     f"{measured_kernel}: WSL was updated. Measure again (tools/serving_config.py)")  # fmt: skip
    return Check(name, "PASS", f"NVIDIA driver {driver} and WSL2 kernel {kernel}, as measured ({where})")


def check_db_passwords(inp: DoctorInputs, running: Callable[[str], Mapping[str, Any] | None] | None = None) -> Check:
    """T-712 (D-481; D-378): a service container holds its own database role's password and no other.

    Three readings, none of which shows a password: the box's ``deploy/.env`` (every service role has a password
    of its own, none is the example value or shared); the box's compose files (``COMPOSE_FILE``, else the base
    file beside ``--env-file``; ``--compose-config`` when given) rendered with the box's values; and the
    environment of the containers that run now. FAIL in VALIDATION and PRODUCTION, WARN elsewhere.
    """
    from tb_common.config import environment_name

    from tools.trialbox import db_secrets as ds

    name = "db_passwords"
    strict = environment_name(inp.env) in ("VALIDATION", "PRODUCTION")  # an empty TB_ENV is PRODUCTION (D-127)
    if inp.deploy is None and inp.compose_config is None:
        # never a pass: nothing was read. A box that may hold real data must be judged
        return Check(name, "FAIL" if strict else "WARN",
                     "the box's database passwords were not judged: give --env-file <deploy/.env>")  # fmt: skip
    deploy = inp.deploy or ROOT / "deploy"
    config = inp.compose_config
    if config is None:
        listed = [f for f in inp.env.get("COMPOSE_FILE", "").split(":") if f]
        files = [_compose_file(deploy, f) for f in listed] or [deploy / "docker-compose.yml"]
        gone = [str(f) for f in files if not f.exists()]
        if gone:
            return Check(name, "FAIL", f"compose file(s) not found: {', '.join(gone)} (COMPOSE_FILE in deploy/.env)")
        config = ds.render(files, inp.env, project_dir=deploy)
    secrets = ds.db_secrets(inp.env)
    roles = ds.database_services(config)
    bad = ds.env_problems(inp.env, roles) + ds.reach_problems(config, secrets)
    live = (running or ds.running_config)(inp.env.get("COMPOSE_PROJECT_NAME", "trialbox"))
    if live is not None:
        bad += [f"running: {p}" for p in ds.reach_problems(live, secrets)]
    seen = f"{len(live['services'])} running container(s) read" if live is not None else "running containers not read"
    if bad:
        fix = "re-run deploy/install.sh (it makes the missing passwords and starts every container again)"
        return Check(name, "FAIL" if strict else "WARN", f"{'; '.join(bad)}; {fix}")
    return Check(name, "PASS", f"{len(roles)} service roles, each container its own password only; {seen}")


def _pid_map_rule(url: str, site_id: str) -> tuple[bool, str | None]:
    """(the pid map has a row for the site, the chart-number rule it recorded) (``adapter.pidmap``, D-595)."""
    from tb_common.db import Database

    with Database.connect(url, "pidmap") as db:
        row = db.fetchone("SELECT chartno_rule FROM site_key WHERE site_id = ?", (site_id,))
    return (row is not None, str(row[0]) if row is not None and row[0] is not None else None)


def _handed_in_containers(inp: DoctorInputs) -> Mapping[str, Any] | None:
    """The running containers' environment as the host check hands it in (``TB_DOCTOR_RUNNING_INSPECT=stdin``:
    ``docker inspect`` of the project's containers on standard input; a pipe, because it holds passwords). The
    doctor's own container has no docker and no network (``deploy/check_host.sh``)."""
    from tools.trialbox import db_secrets as ds

    if inp.env.get("TB_DOCTOR_RUNNING_INSPECT") != "stdin":
        return None
    text = sys.stdin.read()

    def run(argv: list[str]) -> str:
        return "handed-in" if argv[:2] == ["docker", "ps"] else text

    return ds.running_config("handed-in", run=run)


def check_chartno_rule(
    inp: DoctorInputs,
    running: Callable[[str], Mapping[str, Any] | None] | None = None,
    pid_map_rule: Callable[[str, str], tuple[bool, str | None]] = _pid_map_rule,
) -> Check:
    """D-621: one chart-number rule in every service of the box, and it is the pid map's.

    The adapter refuses a night under another rule than the one it recorded (D-595). The other makers of
    pseudonyms (the orchestrator's set-up and opt-out desk, candidates, the data core API) use their own process's
    ``TB_CHARTNO_RULE`` and ask nobody. Read here: the box's compose files rendered with the box's values (as
    ``db_passwords`` reads them), the environment of the containers that run now, and the pid map's record. A
    service is one of ours when it is started with ``TB_SITE_ID``; no rule and ``asis`` are the same rule.

    The rendered files alone cannot differ between services (one env file), so what finds a real difference is
    the running containers and the pid map. Where they were not read the line says so, and on a box that may hold
    real data it is a WARN, never a PASS. The host check hands both in to a doctor that runs in a container
    (``TB_DOCTOR_RUNNING_INSPECT``, ``TB_DOCTOR_PIDMAP_ROW``)."""
    from tb_common import chartno
    from tb_common.config import environment_name

    from tools.trialbox import db_secrets as ds

    name = "chartno_rule"
    strict = environment_name(inp.env) in ("VALIDATION", "PRODUCTION")
    if inp.deploy is None and inp.compose_config is None:
        return Check(name, "FAIL" if strict else "WARN",
                     "the services' chart-number rule was not judged: give --env-file <deploy/.env>")  # fmt: skip
    deploy = inp.deploy or ROOT / "deploy"
    config = inp.compose_config
    if config is None:
        listed = [f for f in inp.env.get("COMPOSE_FILE", "").split(":") if f]
        files = [_compose_file(deploy, f) for f in listed] or [deploy / "docker-compose.yml"]
        gone = [str(f) for f in files if not f.exists()]
        if gone:
            return Check(name, "FAIL", f"compose file(s) not found: {', '.join(gone)} (COMPOSE_FILE in deploy/.env)")
        config = ds.render(files, inp.env, project_dir=deploy)

    def rules(cfg: Mapping[str, Any], label: str) -> tuple[dict[str, str], list[str]]:
        got: dict[str, str] = {}
        bad: list[str] = []
        for svc, body in sorted((cfg.get("services") or {}).items()):
            env = (body or {}).get("environment") or {}
            if isinstance(env, list):
                env = dict(str(item).partition("=")[::2] for item in env)
            if "TB_SITE_ID" not in env:
                continue  # not one of ours (the database, the FHIR store, the TLS front)
            try:
                got[f"{label}{svc}"] = str(chartno.parse_rule(str(env.get("TB_CHARTNO_RULE") or "")))
            except ValueError as exc:
                bad.append(f"{label}{svc}: {exc}")
        return got, bad

    seen, bad = rules(config, "")
    counted = len(seen) + len(bad)
    notes: list[str] = []  # what was not read: never part of a PASS on a box that may hold real data
    if running is not None:
        live = running(inp.env.get("COMPOSE_PROJECT_NAME", "trialbox"))
    else:
        live = _handed_in_containers(inp) or ds.running_config(inp.env.get("COMPOSE_PROJECT_NAME", "trialbox"))
    if live is not None:
        more, worse = rules(live, "running: ")
        seen.update(more)
        bad += worse
        ran = f"{len(more) + len(worse)} running container(s) of ours read"
    else:
        ran = "the running containers were not read"
        notes.append(ran)
    if not counted:
        return Check(name, "FAIL" if strict else "WARN",
                     "no service of the box was judged (none is started with TB_SITE_ID): the chart-number rule "
                     "of the services is not known")  # fmt: skip
    stored: str | None = None
    has_row = False
    asked = False
    site_id = str((inp.settings.get("site") or {}).get("id") or inp.env.get("TB_SITE_ID") or "")
    handed = inp.env.get("TB_DOCTOR_PIDMAP_ROW", "").strip()
    url = inp.env.get("TB_DB_URL", "")
    try:
        if handed:  # the host check asked the box's database: "none", or "<fingerprint>|<rule>"
            asked = True
            if handed != "none":
                has_row = True
                raw = handed.partition("|")[2].strip()
                stored = str(chartno.parse_rule(raw)) if raw else None
        elif url and site_id:
            has_row, raw_rule = pid_map_rule(url, site_id)
            asked = True
            stored = str(chartno.parse_rule(raw_rule)) if raw_rule is not None else None
        else:
            notes.append("the pid map was not asked (no TB_DB_URL or no site id here)")
    except Exception as e:  # the pid map lives on the box: unreadable from here is said, never passed over
        asked = False
        notes.append(f"the pid map's record cannot be read ({type(e).__name__})")
    distinct = sorted(set(seen.values()))
    meaning = "an opt-out or a set-up sheet filed by such a service gets a pseudonym the feed never produces"
    if len(distinct) > 1:
        by_rule = "; ".join(f"{r}: {', '.join(k for k, v in seen.items() if v == r)}" for r in distinct)
        bad.append(f"the services run under {len(distinct)} chart-number rules ({by_rule})")
    if stored is not None and distinct != [stored]:
        bad.append(f"the pid map was built with {stored}, the services run under {', '.join(distinct)}")
    if bad:
        fix = "TB_CHARTNO_RULE is set in deploy/.env only; start every container again (deploy/install.sh)"
        return Check(name, "FAIL", f"{'; '.join(bad)}: {meaning}. {fix}")
    rule = distinct[0]
    said = f"{rule} in {counted} services; {ran}"
    if asked and has_row and stored is None:
        why = "the adapter has not adopted one (D-595), so the rule the patients were loaded under is not known"
        return Check(name, "WARN", f"{said}; the pid map holds the site's key and no rule: {why}")
    if asked:
        said += (
            "; the same as the pid map" if stored is not None else "; no night has recorded a rule in the pid map yet"
        )
    if notes:
        return Check(name, "WARN" if strict else "PASS", f"{said}; NOT CHECKED: {'; '.join(notes)}")
    return Check(name, "PASS", said)


@_supplied("tools.trialbox.doctor_m2")
def check_terminology(inp: DoctorInputs) -> Check:
    """D-1028, D-1029, D-858 (lane E's hunk): the code systems loaded on the box (``TB_TERMINOLOGY_DIR``), each with its
    rows and version. A table without its manifest line, or whose bytes differ from it, is FAIL (it is never read).
    None loaded is PASS: the shipped tables (ICD-10-CM FY2026 with its blocks and index, D-1029) answer."""
    from criteria_compiler.terminology import installed

    where = installed.installed_dir(dict(inp.env))
    tables = installed.status(where)
    bad = [f"{t.name}: {t.problem}" for t in tables if t.problem]
    # H-17 (D-1127): the NHI tables shipped in the image are checked too; a refused one answers nothing
    bad += [f"shipped {p}" for p in installed.shipped_problems()]
    if bad:
        return Check("terminology", "FAIL", "; ".join(bad))
    # TERM-2 (D-1113 to D-1116): every install-time system is named, loaded or not; a licensed one with who accepted
    missing = installed.not_loaded(where)
    rest = f"; not loaded: {', '.join(missing)}" if missing else ""
    shipped = installed.manifest(installed.SHIPPED_DIR)["tables"] if installed.shipped_tables() else {}
    rest += "".join(f"; shipped: {n} {line.get('rows')} rows ({line.get('version')})"
                    for n, line in sorted(shipped.items()))  # fmt: skip
    if not tables:
        return _with_readers(inp, where, f"nothing loaded in {where}: the shipped tables answer (ICD-10-CM "
                             "FY2026 with its blocks and index); python -m tools.terminology_install loads more"
                             + rest)  # fmt: skip
    said = [f"{t.name} {t.rows} rows ({t.version})" + (f", {a}" if (a := installed.accepted(where, t.name)) else "")
            for t in tables]  # fmt: skip
    return _with_readers(inp, where, "; ".join(said) + rest)


def _with_readers(inp: DoctorInputs, where: Path, said: str) -> Check:
    """V-18 (D-1182, DB-C1): the vocabulary and the FHIR store against the same manifest: FAIL when they hold another
    release than the terminology now or one was not loaded; WARN when the folder cannot be read here; else each
    system's version (nothing when the load step never ran)."""
    from tools import terminology_load

    status, readers = terminology_load.doctor_line(_site_dir(inp), where)
    return Check("terminology", status, f"{said}; vocabulary and FHIR store: {readers}" if readers else said)


def check_provenance_index(inp: DoctorInputs) -> Check:
    """D-989 step 2c: the provenance index (``provenance.model_calls``, ``provenance.model_uses``) against the audit
    chain it is derived from. A difference is FAIL: the chain wins, and ``trialbox provenance --rebuild`` writes the
    index again. Not installed yet (the role script creates the tables) is WARN; no database named here is NOT
    CHECKED."""
    from tb_common import provenance_index as idx

    url = str(inp.env.get("TB_DB_URL") or "")
    if not url:
        return Check(
            "provenance_index", "PASS", "NOT CHECKED: no TB_DB_URL (run trialbox provenance --check on the box)"
        )
    from tb_common.audit_writer import _dsn, _psycopg

    from tools.trialbox.provenance import _erased

    try:
        con = _psycopg().connect(_dsn(url), autocommit=True, connect_timeout=10)
    except Exception as exc:
        return Check("provenance_index", "WARN", f"the database did not answer ({type(exc).__name__})")
    try:
        if not idx.installed(con):
            why = ("not installed: the role script creates provenance.model_calls and provenance.model_uses (D-989 "
                   "step 2c); until then the chain is written without the index")  # fmt: skip
            return Check("provenance_index", "WARN", why)
        diff = idx.check(con, Path(str(inp.env.get("TB_AUDIT_DIR") or "/data/audit")), _erased(url))
    finally:
        con.close()
    if not diff.ok:
        return Check("provenance_index", "FAIL", f"{len(diff.missing)} row(s) missing, {len(diff.extra)} extra against "
                     "the chain: the chain wins; run trialbox provenance --rebuild")  # fmt: skip
    return Check("provenance_index", "PASS", "equal to the audit chain")


def check_negated_inclusions(inp: DoctorInputs) -> Check:
    """Card 10A-1: the approved rulesets on ``main`` with an inclusion whose line may negate what its logic asks the
    presence of ("No prior chemotherapy" approved as "any of chemotherapy" before the compiler held such lines). Such
    a line keeps running until a person recompiles the protocol and approves the draft, where it comes back held.
    WARN naming each (ruleset, version, criterion); the check changes nothing. No repository here, or no compiler
    package in this image, is NOT CHECKED (``make negated-inclusion-scan`` on the box)."""
    path = Path(str(inp.env.get("TB_RULESETS_DIR") or "/data/rulesets"))
    if not (path / ".git").exists():
        return Check("negated_inclusions", "PASS", f"NOT CHECKED: no ruleset repository at {path}")
    try:
        from criteria_compiler.negated_inclusions import scan
        from criteria_compiler.repo import RulesetRepo
    except ImportError:
        return Check("negated_inclusions", "PASS", "NOT CHECKED: the compiler is not in this image "
                     "(make negated-inclusion-scan)")  # fmt: skip
    hits = scan(RulesetRepo(path))
    if not hits:
        return Check("negated_inclusions", "PASS", "no approved inclusion negates what its logic asks")
    named = "; ".join(f"{h.ruleset} v{h.version} {h.criterion}" for h in hits[:20])
    more = f" and {len(hits) - 20} more" if len(hits) > 20 else ""
    return Check("negated_inclusions", "WARN", f"{len(hits)} approved inclusion(s) may negate what their logic asks "
                 f"and keep running until recompiled and approved: {named}{more}")  # fmt: skip


def check_release_tree(inp: DoctorInputs) -> Check:
    """H-144 (the integrator's 7159322336): the install folder holds no copy of a folder the box image carries and the
    signed host tree does not (``services/``, ``models/``, ...: ``host_tree.IMAGE_ONLY``). An update neither replaces
    nor checks such a copy. WARN, naming it and the command that removes it (it is never removed for the operator: it
    may hold a change of theirs); FAIL when this command's import path holds it, since a host command run so would
    import code of another release. Judged on the host; in the box image the install folder is not seen."""
    from tools import host_tree as ht
    from tools.trialbox import launch

    name = "release_tree"
    if launch.in_box_image():
        return Check(name, "WARN", "not judged in the box image: the install folder is the host's (trialbox doctor on "
                     "the host judges it)")  # fmt: skip
    base = ht.install_folder(ROOT)
    if base is None:
        return Check(name, "PASS", f"{ROOT} is a source checkout, not an installed release: no install folder to judge")
    note = ht.loose_note(base)
    if not note:
        return Check(name, "PASS", f"{base}: no copy of {', '.join(ht.IMAGE_ONLY)}; the box image carries them")
    # the integrator's 7159790789: a WARN (no host command imports it: the per-command test holds that), a FAIL only
    # when this very command's import path holds it (a caller's PYTHONPATH): a host command run so would import it
    entries = {Path(e or ".").resolve() for e in sys.path}
    on_path = [p for p in ht.loose(base) if any(e == p.resolve() or p.resolve() in e.parents for e in entries)]
    if on_path:
        held = ", ".join(map(str, on_path))
        return Check(name, "FAIL", f"{note}. This command's import path holds {held} (the caller's PYTHONPATH): a "
                     "host command run with it would import that code, not the release's")  # fmt: skip
    return Check(name, "WARN", f"{note}. No host command imports it (the box image carries the release's)")


CHECKS: tuple[Callable[[DoctorInputs], Check], ...] = (
    check_topology,
    check_env_class_ceiling,
    check_routing_perimeter,
    check_gateway_only_model_reach,
    check_perimeter_addresses,
    check_channel_engine,
    check_secure_cookie,
    check_trusted_proxy,
    check_mail_tls,
    check_phi_tripwire,
    check_sae_mailbox,
    check_named_choices,
    check_mail_auth,
    check_console_mfa,
    check_ldap_ca,
    check_publish_gate,
    check_note_block,
    check_judge_route,
    check_registry_pins,
    check_site_tz,
    check_flags,
    check_restore_hold,
    check_site_key,
    check_chartno_rule,
    check_backup,
    check_key_custody,
    check_key_custody_record,
    check_clock,
    check_ops_runner,
    check_audit_heads,
    check_anchor_mount,
    check_rehearsal,
    check_bench_serving,
    check_prefix_cache,
    check_memory_caps,
    check_postgres_memory,
    check_db_passwords,
    check_wsl2_memory,
    check_update_window,
    check_wsl2_versions,
    check_backup_speed,
    check_terminology,
    check_provenance_index,
    check_negated_inclusions,
    check_release_tree,
)


LIVE: tuple[Callable[[DoctorInputs], Check], ...] = (check_serving,)


def _models_root(inp: DoctorInputs) -> Path:
    raw = (inp.env.get("TB_MODELS_DIR") or "").strip()
    return Path(raw) if raw else (inp.deploy or ROOT / "deploy") / "models"


def check_weights(inp: DoctorInputs) -> Check:
    """Every pinned build's weights against its pin; a FAIL sets the flag the gateway refuses on (T-677, D-393)."""
    from gateway.app import weights_flag_path

    from tools import pin_model

    override = _override(inp)
    flag = weights_flag_path({**inp.env, "TB_REGISTRY_OVERRIDE": str(override)})
    assert flag is not None
    root = _models_root(inp)
    try:
        if not (pin_model.load_override(override).get("builds") if override.is_file() else None):
            flag.unlink(missing_ok=True)
            return Check("weights", "WARN", f"no model build pinned in {override}: no weights to check")
        good, lines = pin_model.verify_all(root, override)
    except (pin_model.PinError, OSError, ValueError, yaml.YAMLError) as e:
        good, lines = False, [f"{override}: {type(e).__name__}: {e}"]
    if good:
        flag.unlink(missing_ok=True)
        return Check("weights", "PASS", "; ".join(lines))
    doc = {
        "format": "trialbox-weights-flag/1",
        "override": str(override),
        "models_root": str(root),
        "lines": lines,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        held = f"the gateway refuses every model call while {flag} exists"
    except OSError as e:
        held = f"the weights flag could not be written ({flag}: {e}); stop the gateway by hand"
    fix = "restore the pinned files or re-pin (tools/pin_model.py, RUNBOOK §8), then run doctor --verify-all again"
    return Check("weights", "FAIL", f"{'; '.join(lines)}: {held}; {fix}")


WEIGHTS: tuple[Callable[[DoctorInputs], Check], ...] = (check_weights,)


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


#: H-144 (the integrator's ruling 7159506328): the checks that need the box image. On a host's own Python (the standard
#: library and PyYAML, install.sh HOST-PYTHON) they cannot run: pydantic (``tb_common.config``, ``tb_contracts``),
#: httpx, the services' own code (``services/``) or the release's ``models/routing.yaml`` and ``models/registry.yaml``
#: (neither is in the signed host tree; the image carries both). There they run in a one-off container of the box's
#: own image (``tools/trialbox/doctor_image.py``) and their verdicts join the host's, in this list's order. An import
#: error or a container that does not run is that check's FAIL with the reason: never a PASS, never a skip.
IMAGE_CHECKS = (
    "topology", "env_class_ceiling", "routing_perimeter", "perimeter_addresses", "channel_engine", "trusted_proxy",
    "mail_tls", "phi_tripwire", "named_choices", "note_block", "judge_route", "registry_pins", "chartno_rule",
    "db_passwords", "wsl2_memory", "update_window", "backup_speed", "terminology",
)  # fmt: skip
#: what those checks import beyond the host's Python (the box image has each one)
IMAGE_MODULES = ("pydantic", "httpx", "gateway", "guard", "registry", "channels", "criteria_compiler", "tb_llm",
                 "tb_contracts", "mail_gateway")  # fmt: skip


def needs_image() -> bool:
    """Whether the image checks go to the box image: never inside it; always from an installed release tree (its
    install folder may hold a loose ``services/`` that a caller's PYTHONPATH reaches: never imported, H-144); from a
    source checkout only when its interpreter lacks what they import or the checkout lacks ``models/``."""
    from tools import host_tree as ht
    from tools.trialbox import launch

    if launch.in_box_image():
        return False
    if ht.install_folder(ROOT) is not None:
        return True
    if not (ROOT / "models" / "routing.yaml").is_file():
        return True
    return any(importlib.util.find_spec(m) is None for m in IMAGE_MODULES)


STATUSES: tuple[Status, ...] = ("PASS", "WARN", "FAIL", "SKIP")


def _status(word: str) -> Status:
    return next((s for s in STATUSES if s == word), "FAIL")


def image_part(env_file: Path | None, settings: Path | None,
               routing: Path | None) -> Callable[[tuple[str, ...]], list[Check]]:  # fmt: skip
    """The image's part of a host's run (``run(image=...)``): ``doctor_image.verdicts`` for the box's own deploy
    folder, image and runtime."""
    from tools.trialbox import doctor_image as di

    def ask(names: tuple[str, ...]) -> list[Check]:
        req = di.Request(names, di.own_deploy(env_file), env_file, settings, routing, di.box_settings())
        return [Check(v["name"], _status(v["status"]), v["detail"]) for v in di.verdicts(req)]

    return ask


# D-837: the checks of a host facility a plain VM has not got (the TPM-sealed keys, the off-box anchor folder): under
# TB_HOST_PROFILE=poc on a box that is not PRODUCTION their FAIL is a WARN, and one line lists them. D-887 (the box
# rehearsal on VALIDATION): the ops runner's systemd timer (a poc box installs no units, TB_SYSTEMD=0) and a missing
# anchor folder for the signed heads; a stale or broken head where a folder is set stays a FAIL
HOST_FACILITY_CHECKS = ("key_custody", "anchor_mount", "ops_runner", "audit_heads")
HOST_FACILITY_ONLY: dict[str, str] = {"audit_heads": "no anchor folder"}  # eased only when the FAIL says this


def host_profile(inp: DoctorInputs, out: list[Check]) -> list[Check]:
    # ponytail: called here and not from run(), whose last lines H-144 (#1512) changes; M5 may move it there after.
    # Only for a whole run (its first check is there), never for --weights, --serving or one named check
    if any(c.name == "topology" for c in out):
        out = sorted(module_rows(inp, out), key=lambda c: c.name == "weights")  # its verdict stays last (--verify-all)
    if (inp.env.get("TB_HOST_PROFILE") or "").strip() != "poc":
        return out
    # tb_common.config's rule, without its import (it needs pydantic, which the host's python3 has not): this runs after
    # the checks, where an ImportError ends the whole doctor (H-106: `trialbox --box NAME doctor` on the host)
    if (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper() == "PRODUCTION":
        return [*out, Check("host_profile", "FAIL", "TB_HOST_PROFILE=poc on a PRODUCTION box: never relaxed there")]
    eased = [
        c.name
        for c in out
        if c.name in HOST_FACILITY_CHECKS
        and c.status == "FAIL"
        and c.detail.startswith(HOST_FACILITY_ONLY.get(c.name, ""))
    ]
    out = [replace(c, status="WARN", detail=f"{c.detail} [host profile poc]") if c.name in eased else c for c in out]
    said = ", ".join(eased) if eased else "none failed"
    return [*out, Check("host_profile", "WARN", f"host profile poc: host-facility checks as WARN: {said}")]


def tls_old_clients(inp: DoctorInputs, out: list[Check]) -> list[Check]:
    """H-48 (D-1328): ``TB_TLS_OLD_CLIENTS`` (deploy/.env, or exported, as compose reads it). Off and audited: no
    line. cbc and audited (``deploy/site/tls-old-clients.audited``, written by deploy/install.sh after its
    ``update.tls_relaxed`` event): one WARN line while it is on. A value other than off or cbc, or one that differs
    from the last audited value (switched with no audit event: a plain ``docker compose up``, an exported variable,
    a restore): FAIL."""
    from tools.tls_policy import old_clients_state

    value, _audited, problem = old_clients_state(inp.env, _site_dir(inp), {})
    if problem:
        return [*out, Check("tls_old_clients", "FAIL", problem)]
    if value == "off":
        return out
    why = (
        "TB_TLS_OLD_CLIENTS=cbc (audited): 443 also serves the TLS 1.2 ECDHE AES-CBC-SHA suites to old clients; the "
        "per-release TLS check reports it as an exception; set off in deploy/.env and re-run deploy/install.sh when "
        "the old client is gone (RUNBOOK §12)"
    )
    return [*out, Check("tls_old_clients", "WARN", why)]


def run(
    inp: DoctorInputs,
    checks: tuple[Callable[[DoctorInputs], Check], ...] = CHECKS,
    image: Callable[[tuple[str, ...]], list[Check]] | None = None,
    extras: bool = True,
) -> list[Check]:
    """Each check's verdict, in ``checks``' order. ``image`` (H-144): the checks of ``IMAGE_CHECKS`` are asked of the
    box image (one call), the rest run here; a check the image gave no verdict for is a FAIL. ``extras``: the lines
    that judge the whole run (host profile, old TLS clients, the PoC list); off for the image's part of a run."""
    out: list[Check] = [Check("inputs", "FAIL", why) for why in inp.input_errors]
    names = [fn.__name__.removeprefix("check_") for fn in checks]
    away = tuple(n for n in names if n in IMAGE_CHECKS) if image is not None else ()
    there: dict[str, Check] = {}
    if away and image is not None:
        try:
            answers = image(away)
        except (
            Exception
        ) as e:  # OCR 1512-2, fail closed: an image part that cannot even be prepared is each check's FAIL
            why = f"not run: the box image's part could not be prepared ({type(e).__name__}: {e})"
            answers = [Check(n, "FAIL", why) for n in away]
        for c in answers:
            if c.name == "inputs":  # the image read a settings file the host read (or not): its own line
                out.append(replace(c, name="inputs (box image)"))
            elif c.name in away:
                there.setdefault(c.name, c)
    for fn, name in zip(checks, names, strict=True):
        if name in away:
            out.append(there.get(name) or Check(name, "FAIL", "the box image gave no verdict for this check"))
            continue
        try:
            out.append(fn(inp))
        except Exception as e:  # fail closed: a check that cannot run is a failure
            out.append(Check(name, "FAIL", f"check error: {type(e).__name__}: {e}"))
    if not extras:
        return out
    return poc_stops(inp, tls_old_clients(inp, host_profile(inp, out)))


def poc_stops(inp: DoctorInputs, out: list[Check]) -> list[Check]:
    """H-94 (the owner's ruling 7092087958): each stop a PoC box's install, start or update warned instead of
    stopping (``deploy/site/poc-stops.jsonl``, ``tools/trialbox/stops.py``), as one WARN line with its action; a list
    that cannot be read is a WARN line too, never a FAIL. Only with ``--env-file`` (the box's own deploy folder)."""
    if inp.deploy is None:
        return out
    from tools.trialbox import stops

    return [*out, *(Check(name, "WARN", detail) for name, detail in stops.doctor_lines(inp.deploy))]


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
    errors: list[str] = []
    if settings is not None:
        # OPS-016: a FAIL line, not a traceback, when the settings file is missing or does not parse
        try:
            loaded = yaml.safe_load(settings.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            errors.append(f"settings file {settings} not found: pass the box's settings.yaml with --settings")
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            errors.append(f"settings file {settings} cannot be read: {type(e).__name__}: {e}")
        else:
            if isinstance(loaded, dict):
                doc = loaded
            else:
                errors.append(f"settings file {settings} is not a mapping")
    wd = lake or (Path(env["TB_LAKE_DIR"]) if env.get("TB_LAKE_DIR") else None)
    deploy = env_file.resolve().parent if env_file is not None and env_file.exists() else None
    from tools.trialbox import launch

    # H-136: the hold is read through the box: --env-file's folder, else, on a host, the install folder's own box
    # (deploy/.env, the file the launcher took the settings from); never a folder a variable names
    own = launch.DEPLOY if (launch.DEPLOY / ".env").is_file() and not launch.in_box_image() else None
    return DoctorInputs(
        env=env,
        settings=doc,
        routing_path=routing or ROOT / "models" / "routing.yaml",
        ingest_lake=wd,
        deploy=deploy,
        box=deploy or own,
        input_errors=tuple(errors),
        cron_running=_cron_running,
        backup_timers=_backup_timer,
    )


def _backup_timer(unit: str) -> str | None:
    from tools.trialbox import backup_schedule as bs

    return bs.timer_word(unit)


def _cron_running() -> bool:
    from tools.trialbox import backup_schedule as bs

    return bs.cron_daemon()


def render(checks: list[Check]) -> str:
    lines = [f"{c.status:<5} {c.name:<26} {c.detail}" for c in checks]
    fails = sum(c.status == "FAIL" for c in checks)
    lines.append("---")
    lines.append("doctor passed" if not fails else f"{fails} check(s) failed")
    return "\n".join(lines)
