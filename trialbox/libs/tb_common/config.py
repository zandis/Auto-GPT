"""Configuration: environment variables (SPEC §2) and ``settings.yaml`` (SPEC §10.4).

``load()`` validates ``settings.yaml`` against ``schemas/settings.schema.json`` and raises
:class:`ConfigError` (listing every violation) so that services refuse to start on a bad configuration.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from tb_contracts import Settings, schema_errors

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised when the environment or settings.yaml is invalid; services must not start."""


# ------------------------------------------------------------------------------------------------ the site's zone
# D-315 (STD-016, OPS-056): the site's time zone is one setting. settings.yaml ``site.tz`` is the source; install.sh
# and the settings wizard copy it to ``TB_TZ`` in deploy/.env, which every container reads. No code carries a zone of
# its own: a box without one stops with this message instead of reading Taiwan's day in Japan. ``trialbox doctor``
# (check ``site_tz``) fails when site.tz, TB_TZ, the data source mapping's ``tz`` and the host's zone differ.
NO_SITE_TZ = (
    "the site's time zone is not set: set site.tz in deploy/settings.yaml and TB_TZ in deploy/.env to the same IANA "
    "zone (for example Asia/Tokyo)"
)


def _check_zone(what: str, name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"{what}={name!r} is not a valid IANA time zone") from exc


def site_tz(tz: str | None = None, environ: Mapping[str, str] | None = None) -> str:
    """The site's IANA zone name: ``tz`` when a caller has it (``cfg.env.tz``, a mapping's ``tz``), else ``TB_TZ``.

    There is no default zone (D-315): neither given raises :class:`ConfigError`, as does a name that is not a zone.
    """
    name = (tz or (environ if environ is not None else os.environ).get("TB_TZ") or "").strip()
    if not name:
        raise ConfigError(NO_SITE_TZ)
    _check_zone("TB_TZ" if not tz else "tz", name)
    return name


def site_zone(tz: str | None = None, environ: Mapping[str, str] | None = None) -> ZoneInfo:
    """:func:`site_tz` as a :class:`ZoneInfo`."""
    return ZoneInfo(site_tz(tz, environ))


def adopt_site_tz(settings_path: Path | None = None) -> str:
    """For a tool that runs a synthetic site in one process (e2e, demo, goldens, drills): when ``TB_TZ`` is unset,
    set it from that site's ``site.tz`` (default ``deploy/settings.example.yaml``), as install.sh does on a box.
    The zone still comes from settings, never from code (D-315)."""
    if os.environ.get("TB_TZ"):
        return site_tz()
    path = settings_path or REPO_ROOT / "deploy" / "settings.example.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str((doc.get("site") or {}).get("tz") or "")
    os.environ["TB_TZ"] = site_tz(name or None, {})
    return os.environ["TB_TZ"]


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


@dataclass(frozen=True)
class Env:
    """Process environment (``.env`` loaded first, real environment wins)."""

    site_id: str = "DEV"
    tz: str = ""  # the site's zone: TB_TZ, then site.tz from settings.yaml in load(); no code default (D-315)
    service_name: str = "trialbox"
    imap_host: str = "localhost"
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    imap_ssl: bool = True
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_starttls: bool = True
    mail_intake_addr: str = "trialbox@localhost"
    mail_from_addr: str = "trialbox@localhost"
    fhir_base_url: str = "http://fhir-store:8080/fhir"
    lake_url: str = "http://lake:8013"
    orchestrator_url: str = "http://orchestrator:8010"
    mail_gateway_url: str = "http://mail-gateway:8015"
    doc_parser_url: str = "http://doc-parser:8011"
    compiler_url: str = "http://criteria-compiler:8012"
    adapter_url: str = "http://adapter:8016"
    llm_base_url: str = "http://llm-service:8000/v1"
    llm_model: str = "qwen3.5-35b-a3b-q4"
    llm_mode: str = "vllm"
    cloud_llm_base_url: str = ""
    cloud_llm_api_key: str = ""
    embed_url: str = "http://embed-service:8014"
    embed_mode: str = "bge-m3"
    object_store: str = "fs:/data/objects"
    nhi_twpas_base_url: str = ""
    attach_password_mode: str = "zip"
    log_level: str = "INFO"
    settings_path: str = ""
    data_dir: str = "/data"
    rulesets_dir: str = ""
    audit_dir: str = ""
    secrets_dir: str = "/run/secrets/trialbox"
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def zone(self) -> ZoneInfo:
        if not self.tz:
            raise ConfigError(NO_SITE_TZ)
        return ZoneInfo(self.tz)

    @property
    def audit_path(self) -> Path:
        return Path(self.audit_dir) if self.audit_dir else Path(self.data_dir) / "audit"

    @property
    def rulesets_path(self) -> Path:
        return Path(self.rulesets_dir) if self.rulesets_dir else REPO_ROOT / "rulesets"


_ENV_MAP: dict[str, str] = {
    "TB_SITE_ID": "site_id",
    "TB_TZ": "tz",
    "TB_SERVICE_NAME": "service_name",
    "IMAP_HOST": "imap_host",
    "IMAP_PORT": "imap_port",
    "IMAP_USER": "imap_user",
    "IMAP_PASS": "imap_pass",
    "IMAP_SSL": "imap_ssl",
    "SMTP_HOST": "smtp_host",
    "SMTP_PORT": "smtp_port",
    "SMTP_USER": "smtp_user",
    "SMTP_PASS": "smtp_pass",
    "SMTP_STARTTLS": "smtp_starttls",
    "MAIL_INTAKE_ADDR": "mail_intake_addr",
    "MAIL_FROM_ADDR": "mail_from_addr",
    "FHIR_BASE_URL": "fhir_base_url",
    "LAKE_URL": "lake_url",
    "ORCHESTRATOR_URL": "orchestrator_url",
    "MAIL_GATEWAY_URL": "mail_gateway_url",
    "DOC_PARSER_URL": "doc_parser_url",
    "COMPILER_URL": "compiler_url",
    "ADAPTER_URL": "adapter_url",
    "LLM_BASE_URL": "llm_base_url",
    "LLM_MODEL": "llm_model",
    "TB_LLM_MODE": "llm_mode",
    "CLOUD_LLM_BASE_URL": "cloud_llm_base_url",
    "CLOUD_LLM_API_KEY": "cloud_llm_api_key",
    "EMBED_URL": "embed_url",
    "TB_EMBED_MODE": "embed_mode",
    "TB_OBJECT_STORE": "object_store",
    "NHI_TWPAS_BASE_URL": "nhi_twpas_base_url",
    "ATTACH_PASSWORD_MODE": "attach_password_mode",
    "LOG_LEVEL": "log_level",
    "TB_SETTINGS": "settings_path",
    "TB_DATA_DIR": "data_dir",
    "TB_RULESETS_DIR": "rulesets_dir",
    "TB_AUDIT_DIR": "audit_dir",
    "TB_SECRETS_DIR": "secrets_dir",
}

_BOOL_TRUE = {"1", "true", "yes", "on"}


def load_env(dotenv: Path | None = None, environ: dict[str, str] | None = None) -> Env:
    """Build :class:`Env` from ``.env`` (optional) overlaid by ``environ`` (default ``os.environ``)."""
    merged: dict[str, str] = {}
    dotenv_path = dotenv if dotenv is not None else Path(os.environ.get("TB_DOTENV", ".env"))
    merged.update(_read_dotenv(dotenv_path))
    merged.update(environ if environ is not None else dict(os.environ))
    kwargs: dict[str, object] = {}
    defaults = Env()
    for var, attr in _ENV_MAP.items():
        if var not in merged or merged[var] == "":
            continue
        raw = merged[var]
        current = getattr(defaults, attr)
        if isinstance(current, bool):
            kwargs[attr] = raw.strip().lower() in _BOOL_TRUE
        elif isinstance(current, int):
            try:
                kwargs[attr] = int(raw)
            except ValueError as exc:
                raise ConfigError(f"{var} must be an integer, got {raw!r}") from exc
        else:
            kwargs[attr] = raw
    kwargs["extra"] = {k: v for k, v in merged.items() if k.startswith("TB_") and k not in _ENV_MAP}
    env = Env(**kwargs)  # type: ignore[arg-type]
    if env.tz:  # unset is allowed here: load() takes site.tz from settings.yaml (D-315)
        _check_zone("TB_TZ", env.tz)
    if env.attach_password_mode not in ("zip", "smime"):
        raise ConfigError("ATTACH_PASSWORD_MODE must be zip or smime")
    if env.llm_mode not in ("vllm", "llamacpp", "stub", "openai"):
        raise ConfigError("TB_LLM_MODE must be vllm, llamacpp, openai or stub")
    return env


def load_settings(path: Path) -> Settings:
    """Parse and validate ``settings.yaml``; raise :class:`ConfigError` with every violation."""
    if not path.exists():
        raise ConfigError(f"settings file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"settings.yaml is not valid YAML: {exc}") from exc
    errors = schema_errors("settings", data)
    if errors:
        raise ConfigError("settings.yaml invalid:\n  " + "\n  ".join(errors))
    settings = Settings.model_validate(data)
    if not settings.site.tz:
        raise ConfigError(NO_SITE_TZ)
    _check_zone("site.tz", settings.site.tz)
    for cmd, groups in settings.permissions.items():
        for g in groups:
            if g not in ("senders", "reviewers", "physicians", "alliance_sites") and "@" not in g:
                raise ConfigError(f"permissions.{cmd}: unknown group {g!r}")
    return settings


def default_settings_path(env: Env) -> Path:
    if env.settings_path:
        return Path(env.settings_path)
    return REPO_ROOT / "deploy" / "settings.example.yaml"


@dataclass(frozen=True)
class Config:
    env: Env
    settings: Settings


def load(dotenv: Path | None = None, settings_path: Path | None = None) -> Config:
    """Load and validate the full configuration (SPEC §10.4 ``tb_common.config.load()``)."""
    env = load_env(dotenv)
    settings = load_settings(settings_path or default_settings_path(env))
    if settings.site.tz != env.tz:
        env = Env(**{**env.__dict__, "tz": settings.site.tz})
    return Config(env=env, settings=settings)


# Review F-14 (D-130): APScheduler drops a cron run missed while the process was down (default grace 1 s). The box is a
# Windows workstation that reboots for updates, so a run missed by up to six hours still runs once when the box is back,
# and several missed runs of one job coalesce into one. Both schedulers (orchestrator, console timers) use these.
SCHEDULER_JOB_DEFAULTS: dict[str, Any] = {"misfire_grace_time": 6 * 3600, "coalesce": True, "max_instances": 1}


def environment_name(env: Mapping[str, str]) -> str:
    """The one rule for ``TB_ENV`` in every service (D-127, review F-06): upper-cased, PRODUCTION when unset, so an
    install that forgets to set it keeps its nightly schedule, its mail, its REDCap read and its ethics gate."""
    return (env.get("TB_ENV") or "PRODUCTION").strip().upper()


def tb_env(env: Env) -> str:
    """:func:`environment_name` of a loaded :class:`Env`."""
    return environment_name(env.extra)


def ethics_gate_on(settings: Settings, environment: str) -> bool:
    """The study ethics gate (FR-STUDY-06; 20-build-map F6-03): always off with ``TB_ENV`` DEV or TEST, so the build
    and the synthetic hospital never wait for one; elsewhere ``settings.ethics_gate``, on when unset."""
    if environment.upper() in ("DEV", "TEST"):
        return False
    return True if settings.ethics_gate is None else bool(settings.ethics_gate)


def schedule_on_demand(settings: Settings, environment: str) -> bool:
    """FR-OPS-12: with ``schedule.mode`` auto (the default) DEV runs on demand (no timed jobs); ``nightly`` and
    ``on_demand`` force either way."""
    mode = settings.schedule.mode if settings.schedule else "auto"
    if mode == "auto":
        return environment.upper() == "DEV"
    return mode == "on_demand"


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Process-wide cached configuration."""
    return load()
