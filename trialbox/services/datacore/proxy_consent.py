"""10C-19 (JP-20, D-1232): consent given by a representative (代諾者) and the participant's own assent (アセント) on the
consent record, and the warnings they raise. Warnings only: nothing here refuses a save or moves a participant.

**Switched by one setting.** ``TB_CONSENT_PROXY``: ``on``, else off (unset is off). The Japan profile switches it on
through the site's country (``tb_common.site_country``, card 10K-1: the box's plan writes it for Japan); it is never
inferred from the time zone, so an installed box keeps today's behaviour until someone sets it. Off, the consent
form, the participant page, the lists and the exports are what they were before this card: no field, no key, no
column.

**On the consent form** (the built-in ``tb_consent``; :data:`FIELDS`, their words in ``builtin/forms.csv``): the age at
consent in whole years; whether a representative gave the consent (``ic_lar``, already on the form); the
representative's relation as a code only (:data:`RELATIONS`, "other" included: no free text); the assent obtained or
not, and why not as a code (:data:`ASSENT_WHY`); the day of assent. Never the representative's name, address or
contact: this is a de-identified system, and the form says so. The form's earlier free-text relation
(``ic_lar_relation``) stays on the form and in the exports, read only (:data:`READ_ONLY`): what was recorded is not
hidden, and nothing new is written there. Who recorded each answer is the data core's own record of the save.

**The rules** (per study, :func:`rule`; :data:`DEFAULT_MAJORITY` 18, Japan's age of majority since 2022): a
participant younger than the age of majority whose consent names no representative warns ``no_representative``; one
in the assent age range (by default :data:`DEFAULT_ASSENT_FROM` to the year before majority) with no assent entry
warns ``no_assent``; an assent declined (reason 3) on the consent in force is ``assent_declined``, shown as an alert.
A declined assent holds the participant (``datacore.lifecycle.Lifecycle.assent_hold``): no form then moves the
participant to "consented" or any later step, whatever the order of the saves, the corrections or the setting; only
a person's reasoned step (:func:`reasoned`: a code of :data:`PROCEED_REASONS` and a note) moves the participant on,
audited ``life.assent_proceed``.

**Age.** The participant record holds no date of birth (it is de-identified), so the age is the age at consent the
form records, in whole years. With no age at consent the record warns ``no_age`` (never guessed from a later age).
A participant who comes of age during the study is not prompted for a consent of their own: the rules read the
consent in force, so a re-consent recorded by the participant at that point clears the warnings (a known gap).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

ENV = "TB_CONSENT_PROXY"
#: the consent-form fields this card adds (in the order of the form); ``ic_lar`` is the form's own
FIELDS = ("ic_age", "ic_lar_rel", "ic_assent", "ic_assent_why", "ic_assent_date")
#: the form's earlier free-text relation: kept, read only and never required while the setting is on (free text could
#: hold a name; what was recorded stays shown and exported)
READ_ONLY = ("ic_lar_relation",)
#: the representative's relation to the participant (GCP 第50条 代諾者; review 11, JP-20): codes as the form's data
RELATIONS = ("1", "2", "3", "4", "9")  # parent (親権者), guardian (後見人), spouse, adult child, other
#: why assent was not obtained: too young to understand, lacks the capacity, declined
ASSENT_WHY = ("1", "2", "3")
DECLINED = "3"
FLAGS = ("no_representative", "no_assent", "assent_declined", "no_age")
#: 10C-19 (D-1232): why a person goes on after a declined assent (a code, as break-glass names its reason; the note
#: says the rest, at least :data:`PROCEED_NOTE_MIN` characters): the ethics committee's decision, the investigator's
#: judgement in the participant's interest, the participant's assent given later (recorded on paper), another reason
PROCEED_REASONS = ("committee", "investigator", "assent_given", "other")
PROCEED_NOTE_MIN = 10  # as BREAK_GLASS_NOTE_MIN and the IRB record's reason
#: the main-line steps the reasoned step can go to
FORWARD = ("consented", "enrolled", "on_study", "completed")
DEFAULT_MAJORITY = 18
DEFAULT_ASSENT_FROM = 7
MAJORITY_BOUNDS = (16, 21)


def is_on(environ: Mapping[str, str] | None = None) -> bool:
    """The setting: ``on``, else off. Unset is off: an installed box keeps today's behaviour until someone chooses.
    The Japan profile switches it on through the site's country (``tb_common.site_country``: the box's plan writes
    ``TB_CONSENT_PROXY=on`` for a country whose ``consent_proxy`` is set), never from the time zone."""
    env = os.environ if environ is None else environ
    return (env.get(ENV) or "").strip().lower() in ("on", "1", "true", "yes")


def read_only_now() -> tuple[str, ...]:
    """The fields no route may write while the setting is on (:data:`READ_ONLY`); none while it is off."""
    return READ_ONLY if is_on() else ()


def rule(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """The study's rule (a stored row, or None for the default): ``majority``, ``assent_from``, ``assent_to`` (the
    oldest age still asked for assent; by default the year before majority), who set it and when."""
    r = row or {}
    majority = int(r.get("majority") or DEFAULT_MAJORITY)
    lo = r.get("assent_from")
    hi = r.get("assent_to")
    return {"majority": majority, "assent_from": int(lo) if lo is not None else DEFAULT_ASSENT_FROM,
            "assent_to": int(hi) if hi is not None else majority - 1, "set_by": str(r.get("set_by") or ""),
            "set_at": str(r.get("set_at") or "")}  # fmt: skip


def check_rule(majority: Any, assent_from: Any, assent_to: Any) -> str | None:
    """The plain reason a rule is refused, or None: whole numbers only, the age of majority 16 to 21, the assent ages
    from the youngest to the oldest, inside 0 and below the age of majority."""
    if not all(type(x) is int for x in (majority, assent_from, assent_to)):
        return "the ages are whole numbers"
    lo, hi = MAJORITY_BOUNDS
    if not lo <= majority <= hi:
        return f"the age of majority is {lo} to {hi}"
    if not 0 <= assent_from <= assent_to < majority:
        return "the assent ages run from the youngest to the oldest, from 0 and below the age of majority"
    return None


def _age(text: str) -> int | None:
    try:
        n = int(str(text).strip())
    except ValueError:
        return None
    return n if 0 <= n <= 120 else None


def declined(once: Mapping[str, str]) -> bool:
    """The consent form records the participant's assent as declined."""
    return once.get("ic_assent") == "0" and once.get("ic_assent_why") == DECLINED


def reasoned(step: Mapping[str, Any]) -> bool:
    """A step that goes on after a declined assent: a person's (manual) step forward, with a reason code of
    :data:`PROCEED_REASONS` and a note."""
    if str(step.get("source")) != "manual" or str(step.get("new")) not in FORWARD:
        return False
    return str(step.get("reason") or "") in PROCEED_REASONS and bool(str(step.get("note") or "").strip())


def proceed_problem(reason: str, note: str) -> str | None:
    """Why a step after a declined assent is refused (a code and a real note are needed), or None."""
    if reason not in PROCEED_REASONS:
        return "assent_reason"
    if len(" ".join(note.split())) < PROCEED_NOTE_MIN:
        return "assent_note"
    return None


def review(vals: Mapping[str, Mapping[str, str]], consents: list[dict[str, str]], study_rule: Mapping[str, Any],
           by: Mapping[tuple[str, str], str] | None = None) -> dict[str, Any] | None:  # fmt: skip
    """What the consent in force (the last one recorded) says of the representative and the assent, and the
    warnings (:data:`FLAGS`); None when no consent is recorded. ``by``: who saved each (event, field)."""
    if not consents:
        return None
    ev = consents[-1].get("event", "")
    v = vals.get(ev, {})
    age = _age(v.get("ic_age", ""))
    lar = v.get("ic_lar", "")
    assent = v.get("ic_assent", "")
    out: dict[str, Any] = {
        "event": ev,
        "given_by": "representative" if lar == "1" else "participant" if lar == "0" else "",
        "relation": v.get("ic_lar_rel", "") if lar == "1" else "",
        "assent": assent,
        "assent_why": v.get("ic_assent_why", "") if assent == "0" else "",
        "assent_day": v.get("ic_assent_date", "")[:10] if assent == "1" else "",
        "assent_by": (by or {}).get((ev, "ic_assent"), ""),
        "age": age,
        **{k: study_rule[k] for k in ("majority", "assent_from", "assent_to")},
    }
    warn: list[str] = []
    if declined(v):
        warn.append("assent_declined")
    if age is None:
        warn.append("no_age")
    if age is not None and age < int(study_rule["majority"]) and lar != "1":
        warn.append("no_representative")
    if age is not None and int(study_rule["assent_from"]) <= age <= int(study_rule["assent_to"]) and not assent:
        warn.append("no_assent")
    out["warnings"] = warn
    return out
