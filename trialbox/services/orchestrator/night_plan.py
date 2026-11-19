"""The night plan per tier (plan 10 row 10E-11, review 13 section 7.3).

The scheduler builds one plan from the box's tier record and ``settings.schedule``. The order and the screening
concurrency come from ``models_on_card`` and ``screen_concurrency`` as the record states them, measured or declared:
that is the shape of the box. ``night_budget_patients`` and ``judge_calls_per_second`` are reported only when the
record measured them. Otherwise the plan says "not measured" and does not present the runtime fallback (2,000
patients) as a figure of the tier. An installation with no tier record keeps the ingest time it already has and the
budget it was configured with, including 0 (no limit).

Coded screening is not given a clock of its own. It follows ingest, so a night whose ingest is still running at
02:20 does not start it. On a qualified tier A record whose note model is the CPU, that pass stops at 06:00 local
time and the 06:00–08:00 backup window begins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from tb_common import tier_value

# The micro-batch's code default (orchestrator.scenarios.microbatch.DEFAULT_NIGHT_BUDGET). Duplicated so building a
# plan does not import the screening scenario. A configured TB_MICROBATCH_NIGHT_BUDGET, including 0, still wins.
RUNTIME_FALLBACK_PATIENTS = 2000
BACKUP_WINDOW = ("06:00", "08:00")
_NOTE_START = time(2, 30)
_NOTE_END = time(6, 0)
_BACKUP_START = time(6, 0)
_BACKUP_END = time(8, 0)
_CPU_MODELS = frozenset({"cpu", "cpu_judge", "cpu_note"})
_CODED_ONLY_MODELS = frozenset({"none", "coded_only"})
_NOT_MEASURED = {"en": "not measured", "zh-TW": "尚未測量", "ja": "未測定"}
_NO_RECORD = {"en": "no tier record", "zh-TW": "沒有層級紀錄", "ja": "ティアの記録はない"}


@dataclass(frozen=True)
class Slice:
    """One step of the night, in the order the plan lists them. ``after`` names the step that must finish first."""

    name: str
    after: str | None = None
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class Figure:
    """A tier figure as the plan reports it. ``value`` is set only when the record measured it."""

    basis: str
    value: int | float | None
    unit: str
    label: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {"basis": self.basis, "value": self.value, "unit": self.unit, "label": dict(self.label)}


@dataclass(frozen=True)
class Moment:
    """What the plan is doing at one local time."""

    cpu_note_screening: bool
    stop_cpu_note_screening: bool
    backup_window: tuple[str, str] | None


@dataclass(frozen=True)
class Decision:
    """What advancing the night does at one local time."""

    coded_screening: str
    cpu_note_screening: bool
    stop_cpu_note_screening: bool
    backup_window: tuple[str, str] | None
    started: tuple[str, ...]


@dataclass(frozen=True)
class NightPlan:
    """The night the scheduler will run on this box, and the figures it is willing to state."""

    profile: str | None
    tier: str | None
    letter: str | None
    ingest: str
    slices: tuple[Slice, ...]
    screen_concurrency: int | None
    models_on_card: str | None
    models_resident: bool
    patient_budget: Figure
    judge_calls_per_second: Figure
    runtime_budget: int
    note_model: bool

    @property
    def runtime_unlimited(self) -> bool:
        """A configured budget of 0 is no limit (``TB_MICROBATCH_NIGHT_BUDGET``)."""
        return self.runtime_budget == 0

    @property
    def swap_scheduled(self) -> bool:
        return any(s.name == "swap" for s in self.slices)

    def names(self) -> list[str]:
        return [s.name for s in self.slices]

    def at(self, clock: time) -> Moment:
        """The plan at a local time (already in the site's zone)."""
        clock = clock.replace(tzinfo=None)
        notes = self.note_model and _NOTE_START <= clock < _NOTE_END
        backup = "backup" in self.names() and _BACKUP_START <= clock < _BACKUP_END
        return Moment(
            cpu_note_screening=notes,
            stop_cpu_note_screening=self.note_model and clock >= _NOTE_END,
            backup_window=BACKUP_WINDOW if backup else None,
        )

    def decide(self, clock: time, *, ingest_running: bool) -> Decision:
        """Advance one step. Coded screening does not start while this night's ingest is still running."""
        moment = self.at(clock)
        if ingest_running and "coded" in self.names():
            return Decision(
                "wait_for_ingest",
                moment.cpu_note_screening,
                moment.stop_cpu_note_screening,
                moment.backup_window,
                (),
            )
        started: list[str] = []
        coded = "absent"
        if "coded" in self.names():
            coded = "run"
            started.append("coded")
        if moment.cpu_note_screening:
            started.append("note_cpu")
        if moment.backup_window is not None:
            started.append("backup")
        return Decision(
            coded,
            moment.cpu_note_screening,
            moment.stop_cpu_note_screening,
            moment.backup_window,
            tuple(started),
        )

    def report(self) -> dict[str, Any]:
        """The plan as the scheduler reports it. Unmeasured figures stay labelled, not filled from the fallback."""
        return {
            "profile": self.profile,
            "tier": self.tier,
            "letter": self.letter,
            "ingest": self.ingest,
            "screen_concurrency": self.screen_concurrency,
            "models_on_card": self.models_on_card,
            "models_resident": self.models_resident,
            "swap_scheduled": self.swap_scheduled,
            "slices": self.names(),
            "patient_budget": self.patient_budget.as_dict(),
            "judge_calls_per_second": self.judge_calls_per_second.as_dict(),
            "runtime_budget_patients": self.runtime_budget,
            "note_model": self.note_model,
        }

    def report_line(self) -> str:
        """One log line, in the three languages a person at the box may read."""
        patients = self.patient_budget.label
        rate = self.judge_calls_per_second.label
        return (
            f"ingest {self.ingest}; concurrency {self.screen_concurrency}; "
            f"patients {patients['en']} / {patients['zh-TW']} / {patients['ja']}; "
            f"judge calls per second {rate['en']} / {rate['zh-TW']} / {rate['ja']}"
        )


def _field(record: Mapping[str, Any] | None, name: str) -> tuple[str, Any]:
    if not isinstance(record, Mapping):
        return "no_record", None
    fields = record.get("fields")
    got = fields.get(name) if isinstance(fields, Mapping) else None
    if not isinstance(got, Mapping):
        return "missing", None
    basis = got.get("basis")
    if basis == "not_measured":
        return "not_measured", None
    if basis in ("measured", "declared"):
        return str(basis), got.get("value")
    return "malformed", None


def _layout_text(record: Mapping[str, Any], name: str) -> str | None:
    basis, value = _field(record, name)
    if basis in ("measured", "declared") and isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _layout_int(record: Mapping[str, Any], name: str) -> int | None:
    basis, value = _field(record, name)
    if basis not in ("measured", "declared"):
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _positive(value: Any, *, integral: bool) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        return None
    if integral and not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _shown(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format(value, "g")


def _measured_label(value: int | float, unit: str) -> dict[str, str]:
    shown = _shown(value)
    if unit == "patients":
        return {"en": f"{shown} patients", "zh-TW": f"{shown} 位病人", "ja": f"{shown} 人"}
    return {
        "en": f"{shown} judge calls per second",
        "zh-TW": f"每秒 {shown} 次判定",
        "ja": f"毎秒 {shown} 回の判定",
    }


def _figure(record: Mapping[str, Any] | None, name: str, unit: str, *, integral: bool) -> Figure:
    if record is None:
        return Figure("no_record", None, unit, dict(_NO_RECORD))
    basis, value = _field(record, name)
    number = _positive(value, integral=integral) if basis == "measured" else None
    if number is None:
        return Figure("not_measured", None, unit, dict(_NOT_MEASURED))
    return Figure("measured", number, unit, _measured_label(number, unit))


def _letter(record: Mapping[str, Any]) -> str:
    tier = str(record.get("tier") or "").strip()
    profile = str(record.get("profile") or "").strip()
    models = _layout_text(record, "models_on_card") or ""
    if tier in {"A", "basic", "cpu"} or profile == "cpu":
        return "A"
    if tier in {"C", "medium"} or profile == "gb10":
        return "C"
    if tier in {"D", "large"} or profile == "rtxpro6000":
        return "D"
    if tier in {"B", "small"} or profile == "rtx5090":
        return "B"
    if models in _CPU_MODELS or models in _CODED_ONLY_MODELS:
        return "A"
    if "swap" in models:
        return "B"
    if models == "pair_resident":
        return "D"
    return ""


def _qualified_cpu_notes(record: Mapping[str, Any], letter: str) -> bool:
    """Tier A runs the CPU note pass only once a qualification record exists and the note model is the CPU."""
    if letter != "A" or (_layout_text(record, "models_on_card") or "") not in _CPU_MODELS:
        return False
    measured_on = record.get("measured_on")
    qual = measured_on.get("qualification_record") if isinstance(measured_on, Mapping) else None
    return isinstance(qual, str) and bool(qual.strip())


def _ingest_of(settings: Any) -> str:
    sch = getattr(settings, "schedule", None) if settings is not None else None
    raw = getattr(sch, "ingest", None) if sch is not None else None
    text = str(raw).strip() if raw else ""
    return text or "02:00"


def _plus(hhmm: str, minutes: int) -> str:
    parts = hhmm.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return "02:20"
    total = (int(parts[0]) * 60 + int(parts[1]) + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _load_record(env: Mapping[str, str], tiers_dir: Any) -> Mapping[str, Any] | None:
    profile = tier_value.profile_of(env)
    if profile is None:
        return None
    path = (tiers_dir or tier_value.TIERS_DIR) / f"{profile}.json"
    try:
        doc = tier_value.read_record(path)
    except (FileNotFoundError, tier_value.TierRecordUnreadable, OSError):
        return None
    return doc if isinstance(doc, Mapping) else None


def _configured_budget(env_map: Mapping[str, str], env_obj: Any) -> tuple[int, bool]:
    """The runtime budget and whether a setting chose it. 0 is a choice (no limit), as is an explicit 2000."""
    explicit_raw = (env_map.get("TB_MICROBATCH_NIGHT_BUDGET") or "").strip()
    from_obj = getattr(env_obj, "microbatch_night_budget", None) if env_obj is not None else None
    if from_obj is not None:
        try:
            configured = int(from_obj)
        except (TypeError, ValueError):
            configured = RUNTIME_FALLBACK_PATIENTS
    elif explicit_raw:
        try:
            configured = int(explicit_raw)
        except ValueError:
            configured = RUNTIME_FALLBACK_PATIENTS
    else:
        configured = RUNTIME_FALLBACK_PATIENTS
    explicit = configured != RUNTIME_FALLBACK_PATIENTS or bool(explicit_raw)
    return configured, explicit


def _runtime_budget(env_map: Mapping[str, str], env_obj: Any, record: Mapping[str, Any] | None) -> int:
    configured, explicit = _configured_budget(env_map, env_obj)
    if explicit:
        return configured
    if record is not None:
        basis, value = _field(record, "night_budget_patients")
        number = _positive(value, integral=True) if basis == "measured" else None
        if isinstance(number, int):
            return number
        return configured
    measured = tier_value.positive_int(tier_value.measured("night_budget_patients", env_map))
    return configured if measured is None else measured


def _slices(letter: str, ingest: str, *, swap: bool, resident: bool, cpu_notes: bool) -> tuple[Slice, ...]:
    coded_at = _plus(ingest, 20)
    steps = [
        Slice("embedder", start="00:00", end="02:00"),
        Slice("ingest", start=ingest),
        Slice("coded", after="ingest", start=coded_at),
    ]
    if cpu_notes:
        steps.append(Slice("note_cpu", after="coded", start="02:30", end="06:00"))
    elif swap:
        steps.extend(
            (
                Slice("judge", after="coded"),
                Slice("swap", after="judge"),
                Slice("verifier", after="swap"),
            )
        )
    elif resident and letter in {"C", "D"}:
        steps.append(Slice("delta_screening", after="coded"))
        steps.append(Slice("first_load", after="delta_screening"))
        steps.append(Slice("first_load", after="first_load"))
    elif resident:
        steps.append(Slice("delta_screening", after="coded"))
    steps.append(Slice("backup", start="06:00", end="08:00"))
    return tuple(steps)


def build_night_plan(
    settings: Any = None,
    env: Mapping[str, str] | None = None,
    *,
    record: Mapping[str, Any] | None = None,
    env_obj: Any = None,
    tiers_dir: Any = None,
) -> NightPlan:
    """The night plan for this box. ``record`` is a tier-record fixture; otherwise the box's ``TB_PROFILE`` is read."""
    env_map = dict(env or {})
    loaded = record if record is not None else _load_record(env_map, tiers_dir)
    ingest = _ingest_of(settings)
    runtime = _runtime_budget(env_map, env_obj, loaded)
    patients = _figure(loaded, "night_budget_patients", "patients", integral=True)
    rate = _figure(loaded, "judge_calls_per_second", "judge_calls_per_second", integral=False)
    if loaded is None:
        return NightPlan(
            profile=None,
            tier=None,
            letter=None,
            ingest=ingest,
            slices=(Slice("ingest", start=ingest), Slice("coded", after="ingest", start=_plus(ingest, 20))),
            screen_concurrency=None,
            models_on_card=None,
            models_resident=False,
            patient_budget=patients,
            judge_calls_per_second=rate,
            runtime_budget=runtime,
            note_model=False,
        )
    letter = _letter(loaded)
    models = _layout_text(loaded, "models_on_card")
    swap = bool(models and "swap" in models)
    resident = models == "pair_resident"
    cpu_notes = _qualified_cpu_notes(loaded, letter)
    profile = loaded.get("profile")
    tier = loaded.get("tier")
    return NightPlan(
        profile=profile if isinstance(profile, str) else None,
        tier=tier if isinstance(tier, str) else None,
        letter=letter or None,
        ingest=ingest,
        slices=_slices(letter, ingest, swap=swap, resident=resident, cpu_notes=cpu_notes),
        screen_concurrency=_layout_int(loaded, "screen_concurrency"),
        models_on_card=models,
        models_resident=resident,
        patient_budget=patients,
        judge_calls_per_second=rate,
        runtime_budget=runtime,
        note_model=cpu_notes,
    )


def local_clock(orch: Any, now: datetime | None) -> time:
    """``now`` in the site's zone, as a clock time. A naive ``now`` is read as already local."""
    tzname = getattr(getattr(getattr(orch, "cfg", None), "env", None), "tz", "") or "UTC"
    try:
        zone = ZoneInfo(tzname)
    except Exception:
        zone = ZoneInfo("UTC")
    if now is None:
        now = datetime.now(zone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)
    return now.timetz().replace(tzinfo=None)


def ingest_still_running(orch: Any) -> bool:
    """True when the scheduler's own ingest for this night has not finished."""
    find = getattr(getattr(orch, "db", None), "find", None)
    if not callable(find):
        return False
    try:
        jobs = find(type_="INGEST", limit=50)
    except Exception:
        return False
    if not isinstance(jobs, (list, tuple)):
        return False
    for job in jobs:
        if getattr(job, "state", "") in ("done", "failed"):
            continue
        opts = getattr(job, "options", None) or {}
        if not isinstance(opts, Mapping):
            continue
        if opts.get("chain") == "1" or opts.get("timer") == "1" or getattr(job, "requested_by", "") == "scheduler":
            return True
    return False


__all__ = [
    "BACKUP_WINDOW",
    "Decision",
    "Figure",
    "NightPlan",
    "Slice",
    "build_night_plan",
    "ingest_still_running",
    "local_clock",
]
