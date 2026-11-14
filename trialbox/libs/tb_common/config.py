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
    embed_mode: str = "model"
    object_store: str = "fs:/data/objects"
    nhi_twpas_base_url: str = ""
    attach_password_mode: str = "link"  # D-369: patient files by a sign-in link, not a password zip
    log_level: str = "INFO"
    settings_path: str = ""
    data_dir: str = "/data"
    rulesets_dir: str = ""
    audit_dir: str = ""
    secrets_dir: str = "/run/secrets/trialbox"
    # T-305a (D-383): a job refuses to pin a lake snapshot more than this many days older than its run date; 0 = no
    # check (the code default: tests and demos run old synthetic nights). The production compose file sets 3.
    lake_max_snapshot_age_days: int = 0
    # T-305b (D-403): site-setup decisions on the hospital's lake within this many seconds of the last publish wait
    # and are published as one batch; 0 = every decision publishes at once (the code default). Compose sets 300.
    site_publish_batch_seconds: int = 0
    # T-624 (D-397): the most patients the micro-batch jobs of one night evaluate, every study together (pool
    # re-checks and new patients); the rest carry over to the next run. 0 = no limit.
    microbatch_night_budget: int = 2000
    # D-646: the part of a weekly micro-batch job's allowance kept for screening its excluded patients again, in
    # percent; kept only as far as such patients are in scope. 0 = nothing kept (they come after everybody else).
    microbatch_excluded_percent: int = 25
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
        """D-469: the working copy of the rulesets, ``<TB_DATA_DIR>/rulesets`` unless ``TB_RULESETS_DIR`` names another
        folder (the compose files and the platform manifests name ``/data/rulesets``, which is the same). Never the
        checkout's ``rulesets/``: that folder is the read-only seed (``tb_common.ruleset.SEED_RULESETS``)."""
        return Path(self.rulesets_dir) if self.rulesets_dir else Path(self.data_dir) / "rulesets"


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
    "TB_LAKE_MAX_SNAPSHOT_AGE_DAYS": "lake_max_snapshot_age_days",
    "TB_SITE_PUBLISH_BATCH_SECONDS": "site_publish_batch_seconds",
    "TB_MICROBATCH_NIGHT_BUDGET": "microbatch_night_budget",
    "TB_MICROBATCH_EXCLUDED_PERCENT": "microbatch_excluded_percent",
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
    if env.lake_max_snapshot_age_days < 0:
        raise ConfigError("TB_LAKE_MAX_SNAPSHOT_AGE_DAYS must be 0 (no check) or a number of days")
    if env.site_publish_batch_seconds < 0:
        raise ConfigError("TB_SITE_PUBLISH_BATCH_SECONDS must be 0 (publish every decision) or a number of seconds")
    if env.microbatch_night_budget < 0:
        raise ConfigError("TB_MICROBATCH_NIGHT_BUDGET must be 0 (no limit) or a number of patients")
    if not 0 <= env.microbatch_excluded_percent <= 100:
        raise ConfigError("TB_MICROBATCH_EXCLUDED_PERCENT must be a percentage from 0 (nothing kept) to 100")
    if env.attach_password_mode not in ("link", "smime", "zip"):
        raise ConfigError("ATTACH_PASSWORD_MODE must be link, smime or zip")
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

    def __post_init__(self) -> None:
        # an env without TB_TZ takes the site's zone from site.tz, wherever the Config is built (D-315)
        if not self.env.tz and self.settings.site.tz:
            object.__setattr__(self, "env", Env(**{**self.env.__dict__, "tz": self.settings.site.tz}))


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


# ------------------------------------------------------------------------------------- the declared TB_* list
# T-108d (D-389, the T-108 contract of TB-ASSESS-01): every ``TB_*`` setting a service, library, tool or deploy
# script reads is declared here once, with its type, its default ("" when unset means "off", "none" or the reading
# code's own constant) and one doc line. ``tests/unit/test_config_declared.py`` greps the code for ``"TB_..."`` string
# literals and fails on a name missing here, and on a name declared here that nothing reads any more. A new setting:
# add its row in the same PR. Variables only the compose files read are not listed, except as a family below.
# Kinds: str, int, float, bool ("1"/"true"/"yes"/"on" is on) and path. A secret's value never appears here.


@dataclass(frozen=True)
class Declared:
    """One declared ``TB_*`` setting."""

    kind: str
    default: str
    doc: str


# Families: a name that starts with one of these is declared by the family (the name is built at run time).
DECLARED_FAMILIES: dict[str, str] = {
    "TB_DB_PW_": "compose: the password of one service's database role, TB_DB_PW_<SERVICE> (D-378, D-481)",
    "TB_EP_": "egress: one allowed endpoint per variable (deploy/egress.py, D-140)",
    "TB_MEM_": "compose: memory cap of one service, TB_MEM_<SERVICE> (D-360)",
}

DECLARED: dict[str, Declared] = {
    "TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD": Declared(
        "str", "", "acceptance overlay: the test mail server's TLS keystore password (tools.acceptance_env; secret)"
    ),
    "TB_ACCEPTANCE_MAIL_PASSWORD": Declared(
        "str", "", "acceptance overlay: the test mail account's password (tools.acceptance_env; secret)"
    ),
    "TB_ACTOR_KEYS_FILE": Declared("path", "", "file of keys that sign the console's user assertions (S-09)"),
    "TB_ACTOR_SIGN_KEY_FILE": Declared("path", "", "the console's own key that signs people (T-717, D-485)"),
    "TB_ADAPTER_RUN": Declared("str", "process", "adapter: the ingest runs as a process of its own, or thread (D-663)"),
    "TB_ADAPTER_LAKE": Declared("str", "http", "adapter CLI: write to the lake over http or in process"),
    "TB_AUDIT_ANCHOR_TARGETS": Declared("str", "", "where the audit chain's head anchor is also written"),
    "TB_AUDIT_ARCHIVE_DIR": Declared("path", "", "host folder of the audit archive (logs archive-audit)"),
    "TB_AUDIT_DIR": Declared("path", "/data/audit", "the audit chain's folder"),
    "TB_AUDIT_HEAD_MAX_AGE_H": Declared("float", "36", "doctor: the newest signed audit head may be this old (D-562)"),
    "TB_AUDIT_HOST_DIR": Declared("path", "", "host path of the audit volume (logs archive-audit)"),
    "TB_AUDIT_MIN_FREE_MB": Declared("int", "64", "audit refuses to write below this free space"),
    "TB_AUDIT_TS_MAX_SKEW_S": Declared(
        "float", "300", "seconds an event's own time may differ from the journal's; a slow transaction (D-488)"
    ),
    "TB_AUDIT_WRITER": Declared("str", "file", "db: send audit events to the journal (D-394); file: write the chain"),
    "TB_AUDIT_WRITER_ALIVE": Declared("path", "", "the audit drain's heartbeat file (default in the temp folder)"),
    "TB_AUTH_HOSTNAME": Declared("str", "", "compose: the identity provider's DNS name (network sheet, T-632)"),
    "TB_B200_STANDIN": Declared(
        "bool", "", "tools/b200_qualify.sh: stand-in nvidia-smi and docker (tests); the record is never passed (T-114)"
    ),
    "TB_BACKUP_ALERT_CMD": Declared("str", "", "command run when the newest good backup is too old"),
    "TB_BACKUP_DIRS": Declared("str", "", "extra host folders put in a backup"),
    "TB_BACKUP_JOB_WAIT_S": Declared(
        "float",
        "21600",
        "backup waits this long for jobs, then goes on anyway: half of (36 h alert - 24 h cron), D-455",
    ),
    "TB_BACKUP_KEEP": Declared("int", "14", "backups kept per target"),
    "TB_BACKUP_KEEP_SHARE": Declared(
        "float", "0.5", "part of a target's capacity this box's backups may fill; the rest is for others (D-455)"
    ),
    "TB_BACKUP_MAILTO": Declared("str", "", "address told when the backup is too old"),
    "TB_BACKUP_MAX_AGE_HOURS": Declared("float", "", "age after which backup-status alerts"),
    "TB_BACKUP_MIN_MBPS": Declared(
        "float", "5", "slowest MB/s a backup step may run before it counts as hung: a tenth of a box disk (D-455)"
    ),
    "TB_BACKUP_OFFBOX": Declared("str", "", "the off-box backup target"),
    "TB_BACKUP_PUBKEY": Declared("str", "deploy/secrets/backup.pub", "public key backups are encrypted to"),
    "TB_BACKUP_QUERY_TIMEOUT_S": Declared(
        "float", "60", "limit of the backup's small queries (sizes, job count); not work sized by data (D-455)"
    ),
    "TB_BACKUP_QUIESCE": Declared("str", "off", "off: the snapshot alone; pause: hold services still (D-455)"),
    "TB_BACKUP_SPEED_TEST_MIB": Declared(
        "int", "1024", "Windows box: least MiB a backup path's speed test writes to count; past the write cache (D-608)"
    ),
    "TB_BACKUP_STEP_START_S": Declared(
        "float", "900", "seconds of a backup step that do not grow with the data (container, connection; D-455)"
    ),
    "TB_BACKUP_TARGETS": Declared("str", "", "backup-nightly target folders"),
    "TB_BAKEOFF_API_KEY": Declared("str", "", "judge bake-off tool: API key of a cloud endpoint (tool only)"),
    "TB_BENCH_EMBED_CMD": Declared("str", "", "complete-run tool: the embedding benchmark command"),
    "TB_CANARY_AT_START": Declared("bool", "1", "run the pair canary when the orchestrator starts"),
    "TB_CANARY_CASES": Declared("str", "", "canary case file"),
    "TB_CANARY_GATE": Declared("bool", "", "note answers gated on a passed canary"),
    "TB_CANARY_MAX_AGE_H": Declared("float", "", "hours a passed canary stays valid"),
    "TB_CANARY_RESULT": Declared("str", "", "platform check: path of the canary result"),
    "TB_CANARY_WHY_CASES": Declared(
        "int", "2", "wrong cases named in a failed canary's line, read on one screen line (the report keeps ten)"
    ),
    "TB_CANARY_WHY_CHARS": Declared(
        "int", "120", "characters of a call error kept in a failed canary's line (the gateway's log has it whole)"
    ),
    "TB_CANDIDATE_VIEWS_PER_HOUR": Declared("int", "", "candidate views allowed per user per hour"),
    "TB_CATALOGUE_DIR": Declared("path", "", "folder of the study catalogue"),
    "TB_DOCTOR_PIDMAP_ROW": Declared("str", "", "doctor: the pid map row the host check read (fingerprint|rule)"),
    "TB_DOCTOR_RUNNING_INSPECT": Declared("str", "", "doctor: `stdin` when the host check pipes docker inspect in"),
    "TB_CHARTNO_RULE": Declared("str", "", "the site's chart-number rule (tb_common.chartno), written at installation"),
    "TB_SSMIX2_ORDER_NUMBERS": Declared("str", "unique", "SS-MIX2 order numbers (D-594): unique, or per_day"),
    "TB_CLOCK_MAX_SKEW_S": Declared("float", "", "largest clock skew the audit accepts, seconds"),
    "TB_CLOUD_OPT_IN": Declared("bool", "", "gateway may use a cloud model (DEV only)"),
    "TB_COMPLETE_DIR": Declared("path", "", "complete-run tool: output folder"),
    "TB_COMPOSE": Declared("str", "", "the docker compose command line of the host tools"),
    "TB_CONSOLE_ADMIN_EMAIL": Declared("str", "", "console: first admin account"),
    "TB_CONSOLE_ADMIN_PASSWORD_FILE": Declared("path", "", "console: file with the first admin's password"),
    "TB_CONSOLE_BIND": Declared("str", "", "network sheet: the console's bind address"),
    "TB_CONSOLE_BREACHED_PASSWORDS_FILE": Declared("path", "", "console: sorted SHA-1 list of breached passwords"),
    "TB_CONSOLE_CONSENT_SAMPLE": Declared("str", "", "console: show the sample consent pages"),
    "TB_CONSOLE_DATA_SOURCE": Declared("str", "", "console: label of the records' source (public or site)"),
    "TB_CONSOLE_DIR": Declared("path", "/data/console", "console: data folder"),
    "TB_CONSOLE_FORWARDED_ALLOW_IPS": Declared("str", "127.0.0.1", "console: proxies trusted for forwarded headers"),
    "TB_CONSOLE_HOST": Declared("str", "127.0.0.1", "console: listen address"),
    "TB_CONSOLE_IDLE_MINUTES": Declared("int", "", "console: idle minutes before sign-out"),
    "TB_CONSOLE_MFA": Declared("str", "totp", "console: second factor (totp or off in DEV)"),
    "TB_CONSOLE_PILOT": Declared("str", "on", "console: pilot banner and limits"),
    "TB_CONSOLE_PUBLIC_URL": Declared("str", "https://trialbox.hospa.test", "console: URL used in mail links"),
    "TB_CONSOLE_SAMPLES_DIR": Declared("path", "", "console: folder of sample files"),
    "TB_CONSOLE_SECURE_COOKIE": Declared("bool", "", "console: secure cookies (behind https)"),
    "TB_CONSOLE_SESSION_HOURS": Declared("int", "", "console: session length in hours"),
    "TB_CONSOLE_SMALL_CELL": Declared("int", "", "console: smallest count shown"),
    "TB_CONSOLE_SNAPSHOT": Declared("str", "", "console: lake snapshot to show (demo)"),
    "TB_CONSOLE_SOURCE_DIR": Declared("path", "", "console: folder of source records (demo)"),
    "TB_CONSOLE_SSO_DEFAULT_ROLE": Declared("str", "viewer", "console SSO: role of a user with no mapped group"),
    "TB_CONSOLE_SSO_HEADER": Declared("str", "", "console SSO: header with the user name"),
    "TB_CONSOLE_SSO_MAILBOX_HEADER": Declared("str", "", "console SSO: header with the mailbox"),
    "TB_CONSOLE_SSO_ROLE_HEADER": Declared("str", "", "console SSO: header with the groups"),
    "TB_CONSOLE_SSO_ROLE_MAP": Declared("str", "", "console SSO: group to role map"),
    "TB_CONSOLE_SSO_TRUSTED_PROXIES": Declared("str", "", "console SSO: proxies allowed to set the headers"),
    "TB_CONSOLE_STUDIES": Declared("str", "", "console: studies shown (demo)"),
    "TB_CONSOLE_TEST_SMTP": Declared("str", "", "console: offer the test-mail button"),
    "TB_CONSOLE_TIMERS": Declared("str", "auto", "console: run the timers (auto, on, off)"),
    "TB_CONSOLE_TOTP_ISSUER": Declared("str", "TrialBox", "console: issuer name in TOTP apps"),
    "TB_CONSOLE_TOTP_KEY_FILE": Declared("path", "", "console: key file that seals TOTP secrets"),
    "TB_CONSOLE_TRIALS": Declared("str", "GZQO", "console: trials shown (demo)"),
    "TB_CONSOLE_URL": Declared("str", "", "mail gateway: console URL in replies"),
    "TB_CONSOLE_WEBMAIL_URL": Declared("str", "", "console: link to the site's webmail"),
    "TB_CONSOLE_WORKSPACE": Declared("str", "", "console: workspace folder (demo)"),
    "TB_CQL_LOCAL_LIB": Declared("str", "", "CQL tool: local library folder"),
    "TB_CQL_TRANSLATOR_LIB": Declared("str", "", "compiler: CQL translator library"),
    "TB_CTGOV_BASE_URL": Declared("str", "", "compiler: ClinicalTrials.gov API base"),
    "TB_CTGOV_MODE": Declared("str", "offline", "ClinicalTrials.gov access (offline or online)"),
    "TB_DATA_CLASS": Declared("str", "", "data class a gateway call names"),
    "TB_DATA_CONTRACTS": Declared("str", "", "adapter: data contracts set name or folder (T-659b, D-370)"),
    "TB_DATA_DIR": Declared("path", "/data", "the services' data folder"),
    "TB_DB_ROLES_CMD": Declared("str", "", "restore: the command that puts the service roles back (D-573)"),
    "TB_DB_URL": Declared("str", "", "the trial database URL"),
    "TB_DEMO_ACCOUNTS": Declared("str", "", "demo: accounts to create"),
    "TB_DEMO_CONTAINER": Declared("str", "trialbox-demo", "demo: container name"),
    "TB_DEMO_DAY": Declared("str", "today", "demo: the day the demo shows"),
    "TB_DEMO_DIR": Declared("path", "", "demo: work folder"),
    "TB_DEMO_HOST": Declared("str", "127.0.0.1", "demo: listen address"),
    "TB_DEMO_IMAGE": Declared("str", "trialbox-demo:step5", "demo: image name"),
    "TB_DEMO_KEEP": Declared("bool", "", "demo: keep the work folder"),
    "TB_DEMO_LANG": Declared("str", "ja", "demo: language"),
    "TB_DEMO_MODE": Declared("str", "", "demo mode flag"),
    "TB_DEMO_OPINIONS": Declared("str", "", "demo: recorded first and second checks"),
    "TB_DEMO_PASSWORD": Declared("str", "", "demo: account password (synthetic)"),
    "TB_DEMO_RUN": Declared("str", "/etc/trialbox-demo/run.sh", "demo: start script"),
    "TB_DEMO_SITE_LANG": Declared("str", "", "demo: hospital records and notes in ja or zh-TW (unset: both campuses)"),
    "TB_DEMO_WAIT_S": Declared("float", "900", "demo: seconds to wait for health"),
    "TB_DIRECTORY_URL": Declared("str", "", "platform check: directory URL"),
    "TB_DOCKER": Declared("str", "docker", "the docker command"),
    "TB_DOCKER_ROOT": Declared("path", "/var/lib/docker", "health: Docker root disk to watch (D-379)"),
    "TB_DOCKER_VOLUMES": Declared("str", "/var/lib/docker/volumes", "host folder of docker volumes"),
    "TB_DOCPARSER_IMAGE": Declared("str", "", "platform: doc-parser image"),
    "TB_DOTENV": Declared("str", ".env", "path of the .env file config reads"),
    "TB_DRILL_DIR": Declared("path", "", "backup drill: work folder"),
    "TB_E2E_DIR": Declared("path", "", "e2e tool: work folder"),
    "TB_EDC_ODM_MAX_BYTES": Declared("int", "5000000", "EDC: largest ODM file an import reads (D-435)"),
    "TB_EDC_SIGN_KEY_FILE": Declared("path", "", "EDC: key that signs eCRF records"),
    "TB_EGRESS_STATE": Declared(
        "str", "/var/lib/trialbox/egress-state.json", "egress: state file of the applied table"
    ),
    "TB_EMBED_DEVICE": Declared("str", "cpu", "embedder device (cpu or cuda)"),
    "TB_EMBED_IMAGE": Declared("str", "", "platform: embedder image"),
    "TB_EMBED_MODE": Declared(
        "str", "hash", "embedder: model or hash (stub, refused in PRODUCTION); unset: model in PRODUCTION (D-429)"
    ),
    "TB_EMBED_MODEL_PATH": Declared("path", "/models/embedder", "embedder weights folder (pinned as e-embed-1)"),
    "TB_ENV": Declared("str", "PRODUCTION", "DEV, TEST or PRODUCTION (unset is PRODUCTION)"),
    "TB_EP_SERVING_URL": Declared("str", "", "scenario tool: judge endpoint"),
    "TB_EP_VERIFIER_URL": Declared("str", "", "scenario tool: verifier endpoint"),
    "TB_EVAL_LIMIT": Declared("int", "", "eval: cases per suite"),
    "TB_EXPORT_MAX_PER_HOUR": Declared("int", "10", "screening-log exports allowed per hour"),
    "TB_EXPORT_MAX_PER_HOUR_PER_SERVICE": Declared(
        "int", "60", "screening-log exports per calling service per hour, every name together (D-438)"
    ),
    "TB_EXTRA_CA_FILE": Declared("path", "", "extra CA bundle the services trust"),
    "TB_FEED_DROP_OVERRIDE": Declared("str", "", "allow one feed load that drops too many rows"),
    "TB_FEED_MAX_DROP_PCT": Declared("float", "", "largest row drop a feed load may make"),
    "TB_FHIR_PACKAGE_HOME": Declared("str", "/opt/hl7/home", "FHIR validator package folder"),
    "TB_FHIR_URL": Declared("str", "", "testbench: FHIR store URL"),
    "TB_FHIR_WORKERS": Declared("int", "8", "compiler: parallel FHIR evaluations"),
    "TB_FIRSTRUN_DIR": Declared("path", "", "console: the box's first-run folder (tmpfs; T-729, D-466)"),
    "TB_FONTS_DIR": Declared("path", "", "report fonts folder"),
    "TB_GATEWAY_BREAKER_FAILURES": Declared("int", "5", "gateway: failures in a row that open an endpoint's breaker"),
    "TB_GATEWAY_BREAKER_OPEN_S": Declared("float", "30", "gateway: seconds a breaker stays open before one try"),
    "TB_GATEWAY_CALL_BUDGET_S": Declared("float", "210", "gateway: seconds one call may take, retry and fallbacks in"),
    "TB_GATEWAY_EXPECT_SHA": Declared("str", "", "cascade e2e: judge build expected"),
    "TB_GATEWAY_INTERACTIVE_TIMEOUT_S": Declared("float", "", "gateway: timeout of an interactive call"),
    "TB_GATEWAY_MAX_INFLIGHT": Declared("int", "64", "gateway: chat calls on threads at once (T-608)"),
    "TB_GATEWAY_MODEL": Declared("str", "", "the alias a judge call asks the gateway for"),
    "TB_GATEWAY_RETRY_DELAY_S": Declared("float", "", "gateway: delay before a retry"),
    "TB_GATEWAY_SLOTS": Declared("int", "16", "gateway: calls at once per endpoint without a serving record"),
    "TB_GATEWAY_STALL_S": Declared("float", "40", "gateway: seconds without an answer before a stall probe"),
    "TB_GATEWAY_UPSTREAM_READ_S": Declared("float", "180", "gateway: read timeout to a model, batch roles"),
    "TB_GATEWAY_URL": Declared("str", "", "the model gateway URL"),
    "TB_GATEWAY_VERIFIER_EXPECT_SHA": Declared("str", "", "cascade e2e: verifier build expected"),
    "TB_GATEWAY_VERIFIER_MODEL": Declared("str", "", "the alias a verifier call asks the gateway for"),
    "TB_GATEWAY_VERIFIER_URL": Declared("str", "", "the gateway URL of the verifier"),
    "TB_GATEWAY_WATCH_S": Declared("float", "5", "gateway: how often the stall watch looks"),
    "TB_GPU_KEY": Declared("str", "", "GPU profile tool: GPU key"),
    "TB_GPU_PROFILE": Declared("str", "", "platform: GPU profile"),
    "TB_GUARD_ADMIN": Declared("bool", "", "model guard: allow admin routes"),
    "TB_GUARD_ROUTES": Declared("str", "", "model guard: host=upstream:port routes, comma-separated (D-177)"),
    "TB_GUARD_TIMEOUT_S": Declared("float", "", "model guard: upstream timeout"),
    "TB_HAPI_DB_URL": Declared("str", "", "backup: HAPI database URL"),
    "TB_HEALTH_CERT_RED_DAYS": Declared("int", "30", "health: certificate red within these days (D-379)"),
    "TB_HEALTH_CERT_WARN_DAYS": Declared("int", "45", "health: certificate warn within these days (D-379)"),
    "TB_HEALTH_DISKS": Declared("str", "", "health: extra disks to watch, comma-separated (D-379)"),
    "TB_HEALTH_DESKTOP_GPU_RED": Declared(
        "int", "85", "health: red when desktop programs hold over this percent of the card's spare memory (D-607)"
    ),
    "TB_HEALTH_DESKTOP_GPU_WARN": Declared(
        "int", "70", "health: warn over this percent of the card's spare memory; until P-11 measures it (D-607)"
    ),
    "TB_HEALTH_DISK_RED": Declared("int", "85", "health: disk red over this percent (D-379)"),
    "TB_HEALTH_DISK_WARN": Declared("int", "70", "health: disk warn over this percent (D-379)"),
    "TB_HEALTH_MAIL_AT": Declared("str", "07:00", "health: daily admin health mail time (D-379)"),
    "TB_HEALTH_VERIFIED_DAYS": Declared("int", "100", "health: backup-verify older than this is red (D-379)"),
    "TB_HL7_VALIDATOR_JAR": Declared("str", "/opt/hl7/validator_cli.jar", "FHIR validator jar"),
    "TB_HOST_CONSOLE_PORT": Declared("str", "", "network sheet: console host port"),
    "TB_HOST_FHIR_PORT": Declared("str", "8080", "bench: FHIR host port"),
    "TB_HOST_LAKE_PORT": Declared("str", "8013", "bench: lake host port"),
    "TB_HOST_SMTP_PORT": Declared("int", "", "test mail: SMTP host port"),
    "TB_HOST_ROOT": Declared("path", "", "host scripts: fake host root for the tests only, empty on the box (D-408)"),
    "TB_HOST_TZ": Declared("str", "", "doctor: the host's zone to compare"),
    "TB_IMAGE": Declared("str", "trialbox-py:1.0.0", "the Python services' image"),
    "TB_INGEST_SORT_MB": Declared(
        "int", "", "ingest: MB of NDJSON lines one sort run of the merge holds (unset: a sixteenth of the cap; D-473)"
    ),
    "TB_INSTALL_PULL": Declared("str", "never", "install: image pull policy"),
    "TB_INSTALL_UP_TIMEOUT": Declared("int", "900", "install: seconds to wait for health"),
    "TB_IRB_TEXT_GATE": Declared(
        "str", "auto", "console: candidate view held until the IRB text is recorded (auto, on, off; D-395)"
    ),
    "TB_JAVA": Declared("str", "java", "java command"),
    "TB_JOB_LOST_SECONDS": Declared(
        "float", "900", "a polled job is lost when its service is silent this long (> a restart; D-472)"
    ),
    "TB_JOB_POLL_SECONDS": Declared("float", "5", "longest pause between reads of a polled job's state (D-472)"),
    "TB_JP_INGREDIENT_ATC": Declared("str", "", "compiler: Japanese ingredient to ATC map"),
    "TB_JVM_IMAGE": Declared("str", "", "platform: JVM image"),
    "TB_JOB_MAX_RESTARTS": Declared(
        "int",
        "3",
        "orchestrator: restarts an interrupted job survives; the job may be what stops the box (D-456)",
    ),
    "TB_KEK_HOST_DIR": Declared("path", "/run/trialbox", "host folder of the unsealed KEK, mounted read-only (D-347)"),
    "TB_KEK_FILE": Declared("path", "", "the key-encryption key file"),
    "TB_KEK_NEW_PASSPHRASE": Declared("str", "", "keys tool: new KEK passphrase (secret)"),
    "TB_KEK_PASSPHRASE": Declared("str", "", "KEK passphrase (secret)"),
    "TB_KMS_TOKEN": Declared("str", "", "kms KEK back end: the hospital KMS token (secret; T-319)"),
    "TB_KMS_URL": Declared("str", "", "kms KEK back end: the KMS transit address when it moved from kek.json's"),
    "TB_LAKE_BUILD": Declared("str", "process", "lake: a rebuild runs as a process of its own, or thread (D-539)"),
    "TB_LAKE_DIR": Declared("path", "/data/lake", "lake folder"),
    "TB_LAKE_EMBEDDER": Declared("str", "http", "embedder of a lake build (lake: http; adapter local build: hash)"),
    "TB_LAKE_MAX_TEMP": Declared("str", "", "lake: temporary space cap"),
    "TB_LAKE_MAX_SNAPSHOT_AGE_DAYS": Declared("int", "0", "oldest lake snapshot a job accepts, days (0: off; D-383)"),
    "TB_LAKE_MEMORY_LIMIT": Declared("str", "", "lake: memory cap"),
    "TB_LAKE_SOURCE": Declared("str", "legacy", "lake source (legacy or omop)"),
    "TB_LAKE_TEMP_DIR": Declared("path", "", "lake: temporary folder"),
    "TB_LINK_ADDR": Declared("str", "", "two-device link: this device's address on the hospital network"),
    "TB_LINK_CERTS": Declared("path", "/run/secrets/tb_link", "two-device link: certificate folder"),
    "TB_LINK_PEER": Declared("str", "", "two-device link: the other device's address"),
    "TB_LINK_PEER_PORT": Declared("int", "", "two-device link: the other device's port (unset: TB_LINK_PORT)"),
    "TB_LINK_PORT": Declared("int", "", "two-device link: this device's port"),
    "TB_LINK_ROLE": Declared("str", "", "two-device link: this device's role"),
    "TB_LLM_API_KEY": Declared("str", "", "gateway: key of the model admin endpoints (secret)"),
    "TB_LLM_STUB_NOTE_LANGS": Declared("str", "", "stub model: note languages it reads besides zh-TW (ja; demo only)"),
    "TB_LLM_API_KEY_FILE": Declared(
        "path", "", "gateway, model-guard: the model key file (compose secret, D-437), read before TB_LLM_API_KEY"
    ),
    "TB_LLM_CONTEXT": Declared("int", "", "direct model call: context size (DEV)"),
    "TB_LLM_MODE": Declared("str", "vllm", "model client (vllm, llamacpp, openai, stub)"),
    "TB_LLM_OUTAGE_WAIT_S": Declared(
        "float",
        "1800",
        "jobs: seconds a job waits in model outages in all; a server reloads in minutes (0: no wait; D-456)",
    ),
    "TB_LLM_TIMEOUT_S": Declared("float", "240", "model callers: read timeout to the gateway (T-608)"),
    "TB_LOG_DIR": Declared("path", "deploy/logs", "host folder of collected logs"),
    "TB_LOG_MAX_FILE": Declared("int", "10", "container log files kept per service (provisional, D-389)"),
    "TB_LOG_MAX_SIZE": Declared("str", "100m", "size of one container log file (provisional, D-389)"),
    "TB_MAIL_AUTHSERV_ID": Declared("str", "", "authserv-id trusted in mail auth results (unset: none, D-369)"),
    "TB_MAIL_DIR": Declared("path", "", "testbench: mail folder"),
    "TB_MAIL_PER_RECIPIENT_PER_DAY": Declared(
        "int", "", "mail gateway: sends per recipient per day; empty = the built-in limit (T-108c)"
    ),
    "TB_MAIL_POLL_SECONDS": Declared("float", "60", "mail gateway poll interval"),
    "TB_MAPPING_DIR": Declared("str", "", "adapter: site mapping folders, colon-separated (T-632)"),
    "TB_MATCH_CACHE_DIR": Declared("path", "", "registry match: cache folder"),
    "TB_MATCH_CASSETTE_DIR": Declared("path", "", "registry match: recorded answers folder"),
    "TB_MATCH_DATA_DIR": Declared("path", "", "registry match: data folder"),
    "TB_MATCH_DEVICE": Declared("str", "cpu", "registry match: device"),
    "TB_MATCH_LLM_MODE": Declared("str", "live", "registry match: live or cassette"),
    "TB_MATCH_MODEL": Declared("str", "unspecified", "registry match: model label in the cache key"),
    "TB_MATCH_RESULTS_DIR": Declared("path", "", "registry match: results folder"),
    "TB_METRICS_TOKEN_FILE": Declared("path", "", "metrics: file holding the scraper token (D-379)"),
    "TB_MICROBATCH_EXCLUDED_PERCENT": Declared(
        "int", "25", "screening cadence: percent of a weekly job's allowance kept for excluded patients (D-646)"
    ),
    "TB_MICROBATCH_NIGHT_BUDGET": Declared(
        "int", "2000", "screening cadence: patients per night at most, 0 = no limit (T-624)"
    ),
    "TB_MIG_PROFILE": Declared("str", "", "platform: GPU MIG profile"),
    "TB_MODELS_DIR": Declared("path", "", "models folder"),
    "TB_MODEL_SWAP": Declared("str", "", "one GPU for two models (sleep) or not"),
    "TB_NOTE_BLOCK": Declared("str", "both_agree", "note-block policy"),
    "TB_NOTICE_N1_AT": Declared("str", "07:00", "console: first notice time"),
    "TB_NOTICE_N2_AT": Declared("str", "07:30", "console: second notice time"),
    "TB_NOT_MATCHED_GATE": Declared(
        "str", "auto", "console, orchestrator: not-matched list held until the site's check (auto, on, off; D-446)"
    ),
    "TB_NPM_REGISTRY": Declared("str", "", "FHIR package fetch: registry"),
    "TB_NTP_MAX_OFFSET_S": Declared("float", "", "platform: largest NTP offset"),
    "TB_NTP_SERVER": Declared("str", "", "NTP server checked for the audit clock"),
    "TB_OBJECT_STORE": Declared("str", "fs:/data/objects", "object store (fs:<path>)"),
    "TB_OIDC_CA_FILE": Declared("path", "", "OIDC: CA file"),
    "TB_OIDC_CLIENT_ID": Declared("str", "", "OIDC: client id"),
    "TB_OIDC_CLIENT_SECRET": Declared("path", "", "OIDC: the file of the client secret (compose secret source)"),
    "TB_OIDC_CLIENT_SECRET_FILE": Declared("path", "", "OIDC: file with the client secret"),
    "TB_OIDC_ENABLED": Declared("bool", "0", "OIDC sign-in on"),
    "TB_OIDC_GROUPS_CLAIM": Declared("str", "groups", "OIDC: groups claim"),
    "TB_OIDC_GROUP_ROLES": Declared("str", "", "OIDC: group to role map"),
    "TB_OIDC_ISSUER": Declared("str", "", "OIDC: issuer"),
    "TB_OIDC_LOGOUT_URL": Declared("str", "", "OIDC: logout URL"),
    "TB_OIDC_REDIRECT_URL": Declared("str", "", "OIDC: redirect URL"),
    "TB_OIDC_REQUIRE_MFA": Declared("bool", "1", "OIDC: the IdP must report MFA"),
    "TB_OIDC_SESSION_MINUTES": Declared("int", "", "OIDC: session minutes"),
    "TB_OIDC_USERNAME_CLAIM": Declared("str", "preferred_username", "OIDC: user name claim"),
    "TB_OMOP_CONCEPT_BLOCK": Declared("int", "", "OMOP: concept id block"),
    "TB_OMOP_DB_URL": Declared("str", "", "OMOP database URL (unset: TB_DB_URL)"),
    "TB_OMOP_DUAL_WRITE": Declared("bool", "", "OMOP dual write on"),
    "TB_OPPORTUNITY_APPROVED_FILE": Declared("path", "", "opportunity feed: steward's approved study list (D-467)"),
    "TB_OPPORTUNITY_PERIOD_DAYS": Declared(
        "int", "30", "opportunity feed: publication period, at least 28 days, so a day's change is not exposed"
    ),
    "TB_OPPORTUNITY_PER_CONDITION": Declared(
        "int", "20", "opportunity feed: studies per condition per feed; bounds what one feed can probe"
    ),
    "TB_OPPORTUNITY_SECRET_FILE": Declared("path", "", "opportunity feed: site secret seeding the band (secret)"),
    "TB_OPS_DEPLOY": Declared("str", "", "ops: deploy folder the console sees"),
    "TB_OPS_DIR": Declared("path", "/data/ops", "ops: request and status folder"),
    "TB_OPS_RUNNER": Declared("str", "host", "ops: who runs requests (host or local)"),
    "TB_OPTOUT_LOOKUPS_PER_HOUR": Declared("int", "", "opt-out lookups per user per hour"),
    "TB_OPTOUT_WORKER_MINUTES": Declared("int", "5", "orchestrator: minutes between opt-out worker ticks (0 off)"),
    "TB_ORCH_DIR": Declared("path", "", "orchestrator: data folder"),
    "TB_PARSER": Declared("str", "auto", "document parser (auto or a named one)"),
    "TB_PERIMETER_RECHECK_S": Declared("float", "60", "gateway: seconds between perimeter address checks (D-388)"),
    "TB_PGBACKREST_FULL_DAY": Declared("int", "", "pgBackRest: weekday of the full backup"),
    "TB_PGBACKREST_REPO": Declared("str", "", "pgBackRest: repository"),
    "TB_PG_ARCHIVE_MODE": Declared("str", "off", "PostgreSQL WAL archiving"),
    "TB_PG_BIN": Declared("str", "", "local PostgreSQL bin folder (tools)"),
    "TB_PG_DIR": Declared("path", "", "local PostgreSQL data folder (demo)"),
    "TB_PG_DSN": Declared("str", "", "testbench: PostgreSQL DSN"),
    "TB_PG_DUMP_CMD": Declared("str", "pg_dump", "pg_dump command"),
    "TB_PG_DUMP_DIR": Declared("path", "", "backup: dump folder"),
    "TB_PG_RESTORE_CMD": Declared("str", "pg_restore", "pg_restore command"),
    "TB_PG_SPOOL": Declared("path", "", "platform restore job: the folder pg-spool.sh serves (T-633)"),
    "TB_PLANNED_FROM": Declared("str", "", "complete-run tool: plan start"),
    "TB_PLATFORM_API_SERVER": Declared("str", "", "platform: API server"),
    "TB_PLATFORM_BACKUP_EVIDENCE": Declared("str", "", "platform: backup evidence file"),
    "TB_PLATFORM_BACKUP_HOST": Declared("str", "", "platform: backup host"),
    "TB_PLATFORM_BACKUP_JOB_EVIDENCE": Declared(
        "str", "", "compose platform: the host schedule of backup-nightly (T-633)"
    ),
    "TB_PLATFORM_DB_STORAGE_CLASS": Declared(
        "str", "", "platform: the block storage class of the database claim (T-633)"
    ),
    "TB_PLATFORM_DB_STORAGE_EVIDENCE": Declared(
        "str", "", "platform: evidence the db class is block and encrypted (T-633)"
    ),
    "TB_PLATFORM_GPU_EVIDENCE": Declared("str", "", "platform check: reference of the MIG configuration dump (D-409)"),
    "TB_PLATFORM_GPU_SHARING": Declared(
        "str", "", "platform check: how the GPU is shared (mig, whole, time-slicing, mps; D-409)"
    ),
    "TB_PLATFORM_GPU_STANDIN": Declared("bool", "", "platform check: stand-in GPU devices on a test cluster (D-409)"),
    "TB_PLATFORM_HOST_FINGERPRINT": Declared(
        "str", "", "platform check: this host's fingerprint file, compared with the serving record's (T-114)"
    ),
    "TB_PLATFORM_NETWORK_POLICY_EVIDENCE": Declared("str", "", "platform: network policy evidence"),
    "TB_PLATFORM_NO_GPU": Declared("bool", "", "platform: test cluster without a GPU"),
    "TB_PLATFORM_QUOTA": Declared("str", "", "platform: quota"),
    "TB_PLATFORM_STORAGE_CLASS": Declared("str", "", "platform: storage class"),
    "TB_PLATFORM_STORAGE_ENCRYPTED": Declared("str", "", "platform: storage is encrypted"),
    "TB_PLATFORM_STORAGE_EVIDENCE": Declared("str", "", "platform: storage evidence"),
    "TB_PROFILE": Declared("str", "P-GB10", "hardware profile"),
    "TB_PSQL_CMD": Declared("str", "psql", "psql command"),
    "TB_PUBLIC_DIR": Declared("path", "", "public e2e: work folder"),
    "TB_RC_CASSETTE_TOKEN": Declared("str", "", "REDCap cassette tool: API token for a recording (secret)"),
    "TB_RC_SIM_HOST": Declared("str", "127.0.0.1", "REDCap simulator: address"),
    "TB_RC_SIM_PORT": Declared("int", "8790", "REDCap simulator: port"),
    "TB_RC_SIM_VERSION": Declared("str", "16.0.10", "REDCap simulator: version shown"),
    "TB_REDCAP_READ_AT": Declared("str", "03:00", "console: REDCap read time"),
    "TB_REDCAP_TEST_DAY": Declared("str", "", "REDCap test instance (D-584): the day a run takes as today"),
    "TB_REDCAP_TEST_PORT": Declared("int", "8791", "REDCap test instance (D-584): its loopback port"),
    # the longest call is R8's single import of 1,000 records on a developer's machine; the run records its time
    "TB_REDCAP_TEST_TIMEOUT_S": Declared("float", "120", "REDCap test instance (D-584): seconds one API call may take"),
    # default deploy/site/redcap/redcap.zip (an ignored folder); never committed, bundled or downloaded
    "TB_REDCAP_ZIP": Declared("str", "", "REDCap test instance (D-584): path of the zip the owner supplies"),
    "TB_REFDATA_DIR": Declared("path", "", "reference data folder"),
    "TB_REGISTRY_OVERRIDE": Declared("str", "", "model registry override"),
    "TB_REGISTRY_PATH": Declared("path", "", "model registry file"),
    "TB_REHEARSAL_DIR": Declared("path", "", "rehearsal work folder (tools)"),
    "TB_RELEASE_FILE": Declared("path", "", "release.json path"),
    "TB_RESTORE_ACTOR": Declared("str", "trialbox restore", "restore: actor in the audit"),
    "TB_RESTORE_FILE": Declared("str", "newest", "platform restore job: the backup on the share to restore (T-633)"),
    "TB_RESTORE_KEEP_DIR": Declared("path", "deploy/pre-restore", "restore: where the old files go"),
    "TB_RESTORE_OLDER_OK": Declared("bool", "", "platform restore job: restore a backup older than 14 days (T-633)"),
    "TB_RESTORE_OTHER_SITE": Declared("bool", "", "platform restore job: restore another site's backup (T-633)"),
    "TB_REVEAL_MAX_PER_HOUR": Declared("int", "60", "chart-number reveals per user per hour"),
    "TB_REVEAL_MAX_PER_HOUR_PER_SERVICE": Declared(
        "int", "600", "chart-number reveals per calling service per hour, every name together (D-438)"
    ),
    "TB_REVISION": Declared("str", "", "about page: git revision"),
    "TB_ROUTING_PATH": Declared("path", "", "gateway: routing file"),
    "TB_RULESETS_DIR": Declared("path", "/data/rulesets", "rulesets folder"),
    "TB_RUN_ID": Declared("str", "", "complete-run tool: run id"),
    "TB_PROVISIONING": Declared("str", "", "complete-run tool: SPOT or STANDARD for every VM (unset: D-468)"),
    "TB_ESTIMATE_LLM_SPEEDUP": Declared(
        "float", "2", "complete-run estimate: most that N model calls in flight cut the screening time by"
    ),
    "TB_SAE_FOLLOWUP_DAYS": Declared("int", "", "SAE: follow-up days"),
    "TB_SAE_OFFICE_MAILBOX": Declared("str", "", "SAE: office mailbox"),
    "TB_SAE_REPORT_DAYS": Declared("int", "", "SAE: report days"),
    "TB_SAE_RULES": Declared("str", "", "SAE: rules file"),
    "TB_SCALE_CAP_BYTES": Declared("int", "", "scale gate: the cap a part runs under, handed to its process (T-687)"),
    "TB_SCALE_ENFORCE": Declared("str", "", "scale gate: cgroup or measure (empty: the best this host has; T-687)"),
    "TB_SCALE_LAKE_TIMEOUT_S": Declared(
        "float", "", "scale gate: the lake client's limit (empty: the product's; T-687)"
    ),
    "TB_SCALE_LATENCY_S": Declared("float", "0", "scale gate: the model stand-in's seconds per call (T-687)"),
    "TB_SCALE_LIMIT_S": Declared(
        "float", "", "scale gate: a time limit of the gate's test on one's own machine (empty: none; D-674)"
    ),
    "TB_SCALE_OUTAGE_AFTER": Declared("int", "0", "scale gate: the call from which the stand-in answers 502 (T-687)"),
    "TB_SCALE_OUTAGE_S": Declared("float", "0", "scale gate: seconds of the stand-in's outage (T-687)"),
    "TB_SCALE_STALL_S": Declared(
        "float",
        "600",
        "scale gate: seconds without progress of any of its processes that end the gate (0: never; D-674)",
    ),
    "TB_SCALE_PATIENTS": Declared("int", "300", "scale gate: synthetic patients (the nightly job: 50000; T-687)"),
    "TB_SCALE_PROFILE": Declared(
        "str", "thin", "scale gate: thin (the generator's hospital) or dense (about 500 records, 40 notes; T-687)"
    ),
    "TB_SCALE_RESTART_AFTER": Declared("int", "0", "scale gate: the call after which the stand-in restarts (T-687)"),
    "TB_SCALE_RESTART_GAP_S": Declared("float", "0", "scale gate: seconds the stand-in is down at its restart (T-687)"),
    "TB_SCALE_VALIDATE": Declared("bool", "1", "scale gate: the HL7 validator in the night (T-687)"),
    "TB_SCHEDULER": Declared("bool", "1", "orchestrator: run the scheduler"),
    "TB_SCHEMAS_DIR": Declared("path", "", "JSON schema folder"),
    "TB_SCRATCH": Declared("str", "", "scratch folder (tools, tests)"),
    "TB_SCREEN_BREAKER_FAILURES": Declared(
        "int", "5", "SCREEN: model failures in a row that open the breaker (0: off)"
    ),
    "TB_SCREEN_BREAKER_WINDOW_S": Declared("float", "300", "SCREEN: seconds the breaker stays open"),
    "TB_SCREEN_ENGINE": Declared("str", "sql", "SCREEN engine (sql or fhir)"),
    "TB_SCREEN_JUDGE": Declared("str", "agreement", "SCREEN judge mode (agreement or single)"),
    "TB_SCREEN_LLM_CONCURRENCY": Declared("int", "", "SCREEN: model calls side by side (1 to 64)"),
    "TB_SCREEN_MAX_PAIRS": Declared(
        "int", "", "SCREEN: model call budget per job (unset: the population's own pairs; D-456)"
    ),
    "TB_SCREEN_PIPELINE": Declared("str", "cascade", "SCREEN pipeline (cascade or v1)"),
    "TB_SCREEN_WORKERS": Declared("int", "", "two-phase: verifier calls side by side"),
    "TB_SECRETS_DIR": Declared("path", "/run/secrets/trialbox", "folder of the services' secrets"),
    "TB_SECRETS_HOST_DIR": Declared("path", "", "support bundle: host secrets folder it must never include (T-209b)"),
    "TB_SELFTEST": Declared("str", "on", "orchestrator self-test at start"),
    "TB_SELFTEST_SECONDS": Declared("float", "300", "complete-run tool: self-test time"),
    "TB_SERVICE_NAME": Declared("str", "", "the service's name (service auth)"),
    "TB_SERVICE_TOKEN": Declared("str", "", "the service's token (secret)"),
    "TB_SERVICE_TOKENS": Declared("str", "", "token registry (secret)"),
    "TB_SERVICE_TOKEN_FILE": Declared("path", "", "file with the service's token"),
    "TB_SERVING_RECORD": Declared("str", "", "platform: serving record"),
    "TB_SETTINGS": Declared("str", "", "settings.yaml path"),
    "TB_SETTINGS_FILE": Declared("path", "settings.yaml", "backup schedule: settings.yaml path"),
    "TB_SITE_ID": Declared("str", "", "the site id"),
    "TB_SITE_PATIENTS": Declared(
        "int", "", "install: the hospital's patients, sizing the memory caps before the first night (D-473)"
    ),
    "TB_SITE_PUBLISH_BATCH_SECONDS": Declared(
        "int", "0", "site decisions on main wait this long and publish as one batch (0: at once; D-403)"
    ),
    "TB_SKIP_AUDIT": Declared("bool", "", "update: skip the audit check (drills)"),
    "TB_SOURCE_DIR": Declared("path", "./site/feed", "compose: host folder of the site feed (settings wizard, T-632)"),
    "TB_SOURCE_DSN": Declared("str", "", "adapter: the read connection of a database source (secret; T-729, T-731)"),
    "TB_SOURCE_MOUNT": Declared("path", "/data/source/site", "compose: where the site feed is mounted (T-632)"),
    "TB_SOURCE_PATH": Declared("path", "", "adapter: source records path"),
    "TB_SPONSOR_WEEKLY_MAX_BYTES": Declared("int", "2000000", "largest sponsor weekly sheet read (D-435)"),
    "TB_STANDIN_LOAD_DELAY": Declared("float", "0", "model stand-in: load delay"),
    "TB_STEP_ID": Declared("str", "", "step id a gateway call names"),
    "TB_STUB_CONTEXT": Declared("int", "", "model stub: context size"),
    "TB_STUB_LATENCY_S": Declared(
        "float", "", "model stub: seconds per answer (the scale gate's slow stand-in, T-687)"
    ),
    "TB_STUB_MODELS": Declared("str", "", "model stub: models served"),
    "TB_STUB_OUTAGE_AFTER": Declared(
        "int", "", "model stub: the call after which the stand-in's outage starts (T-687)"
    ),
    "TB_STUB_OUTAGE_S": Declared("float", "", "model stub: seconds of 502 answers in the stand-in's outage (T-687)"),
    "TB_STUB_OUTAGE_STATUS": Declared("int", "502", "model stub: the HTTP status of the stand-in's outage (T-687)"),
    "TB_SWAP_HOLD_S": Declared("float", "", "gateway swap: hold time"),
    "TB_SWAP_WAKE_TIMEOUT_S": Declared("float", "", "gateway swap: wake timeout"),
    "TB_TERMINOLOGY_SOURCE": Declared("str", "", "compiler: terminology source"),
    "TB_TESTBENCH_E2E": Declared("str", "", "testbench: run the e2e entry point"),
    "TB_TESTBENCH_E2E_STRICT": Declared("bool", "", "testbench: a failing entry point fails the run"),
    "TB_TESTBENCH_HOST": Declared("str", "127.0.0.1", "testbench: address"),
    "TB_TESTBENCH_IN_CONTAINER": Declared("bool", "", "testbench: runs in a container"),
    "TB_TESTBENCH_PORT": Declared("int", "8765", "testbench: port"),
    "TB_TESTBENCH_WORKDIR": Declared("str", "", "testbench: work folder"),
    "TB_TEST_ROOT": Declared("str", "", "test root folder (tools, tests)"),
    "TB_TLS_BIND": Declared("str", "", "compose: address the TLS front binds (network sheet, T-632)"),
    "TB_TLS_CERT_FILE": Declared("path", "", "console TLS certificate"),
    "TB_TLS_HOSTNAME": Declared("str", "", "console TLS host name"),
    "TB_TLS_KEY_FILE": Declared("path", "", "console TLS key"),
    "TB_TLS_MODE": Declared("str", "internal", "console TLS mode (internal or hospital)"),
    "TB_TODAY": Declared("str", "", "pins the clock (test stack)"),
    "TB_TOPOLOGY": Declared("str", "A", "deployment topology (A or B)"),
    "TB_TO_PID_MAX_PER_HOUR": Declared(
        "int", "", "pseudonym lookups by chart number per signed name per hour (D-487); unset: TB_REVEAL_MAX_PER_HOUR"
    ),
    "TB_TRACESTORE": Declared("str", "", "gateway trace store on"),
    "TB_TWPAS_IG": Declared("str", "", "TWPAS implementation guide"),
    "TB_TZ": Declared("str", "", "the site's IANA zone (D-315: no default)"),
    "TB_WIN_UPDATE_WINDOW_HOURS": Declared(
        "int", "6", "Windows box: hours the update window lasts; 6 is the least Windows allows (D-606)"
    ),
    "TB_WIN_UPDATE_WINDOW_START": Declared(
        "int", "19", "Windows box: hour Windows Update may install and restart; after desk hours (D-606)"
    ),
    "TB_WSL_DESKTOP_SHARE_PCT": Declared(
        "int", "25", "Windows box: percent of memory and processors kept for the desktop; WSL2 gets the rest (D-601)"
    ),
    "TB_UPDATE_BACKUP_CMD": Declared("str", "", "update: backup command"),
    "TB_UPDATE_CHECK_CMD": Declared("str", "", "update: health check command"),
    "TB_UPDATE_DRILL_DIR": Declared("path", "", "update drill: work folder"),
    "TB_UPDATE_INCOMING": Declared("str", "", "update: incoming bundle folder"),
    "TB_UPDATE_TARGET": Declared("str", "compose", "update: compose or demo"),
    "TB_VALIDATION_SAMPLE_CAP": Declared(
        "int", "", "ingest gate: most resources of one type validated (unset: from the limit; 0: no cap; D-457)"
    ),
    "TB_VALIDATOR_IGS": Declared("str", "tw.gov.mohw.twcore#1.0.0", "FHIR validator: guides loaded"),
    "TB_VALIDATOR_XMX": Declared("str", "4g", "FHIR validator: Java heap"),
    "TB_VAULT_DIR": Declared("path", "", "testbench: vault folder"),
    "TB_VAULT_URL": Declared("str", "", "testbench: vault URL"),
    "TB_WEIGHTS_FLAG": Declared("path", "", "doctor --verify-all: where the weights flag file goes (D-393)"),
    "TB_WORKERS": Declared("int", "4", "orchestrator: job workers"),
}
