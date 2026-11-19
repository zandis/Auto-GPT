"""10C-19 (JP-20, D-1232): consent given by a representative (代諾者) and the participant's own assent (アセント) on the
consent record, and the warnings they raise. Warnings only: nothing here refuses a save or moves a participant.

**Switched by one setting.** ``TB_CONSENT_PROXY``: ``on`` or ``off``; unset (the default) is on when the site's zone
names Japan (``TB_TZ``, the Japan profile) and off elsewhere. Off, the consent form, the participant page, the lists
and the exports are what they were before this card: no field, no key, no column.

**On the consent form** (the built-in ``tb_consent``; :data:`FIELDS`, their words in ``builtin/forms.csv``): the age at
consent in whole years; whether a representative gave the consent (``ic_lar``, already on the form); the
representative's relation as a code (:data:`RELATIONS`; "other" with one word); the assent obtained or not, and why
not as a code (:data:`ASSENT_WHY`); the day of assent. Never the representative's name, address or contact: this is
a de-identified system, and the form says so. Who recorded each answer is the data core's own record of the save.

**The rules** (per study, :func:`rule`; :data:`DEFAULT_MAJORITY` 18, Japan's age of majority since 2022): a
participant younger than the age of majority whose consent names no representative warns ``no_representative``; one
in the assent age range (by default :data:`DEFAULT_ASSENT_FROM` to the year before majority) with no assent entry
warns ``no_assent``; an assent declined (reason 3) is ``assent_declined``, shown as an alert, and the consent form is
then not taken as consent to proceed (``datacore.lifecycle``): only a person's step to "consented", with the reason in
its note, moves the participant on, and the step is audited (``life.step``) as every step is.

**Age.** The participant record holds no date of birth (it is de-identified): the age is the age at consent the form
records, in whole years, else the age at enrolment (``en_age``), which is on or after the consent day and so can only
be the same or older. The warning's precision is therefore whole years, and an age read from enrolment says so
(``age_from``). No age recorded: no age warning (the page says the age is not recorded).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

ENV = "TB_CONSENT_PROXY"
#: the consent-form fields this card adds (in the order of the form); ``ic_lar`` is the form's own
FIELDS = ("ic_age", "ic_lar_rel", "ic_lar_other", "ic_assent", "ic_assent_why", "ic_assent_date")
#: the field the coded relation replaces on the form while the setting is on (its free text could hold a name)
REPLACED = ("ic_lar_relation",)
#: the representative's relation to the participant (GCP 第50条 代諾者; review 11, JP-20): codes as the form's data
RELATIONS = ("1", "2", "3", "4", "9")  # parent (親権者), guardian (後見人), spouse, adult child, other (one word)
#: why assent was not obtained: too young to understand, lacks the capacity, declined
ASSENT_WHY = ("1", "2", "3")
DECLINED = "3"
FLAGS = ("no_representative", "no_assent", "assent_declined")
DEFAULT_MAJORITY = 18
DEFAULT_ASSENT_FROM = 7
AGE_BOUNDS = (0, 30)


def is_on(environ: Mapping[str, str] | None = None) -> bool:
    """The setting: ``on`` / ``off``; unset, on where the site's zone names Japan (the Japan profile)."""
    env = os.environ if environ is None else environ
    v = (env.get(ENV) or "").strip().lower()
    if v in ("on", "1", "true", "yes"):
        return True
    if v in ("off", "0", "false", "no"):
        return False
    from tb_common.derived import country_of

    return country_of((env.get("TB_TZ") or "").strip() or None) == "JP"


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


def check_rule(majority: int, assent_from: int, assent_to: int) -> str | None:
    """The plain reason a rule is refused, or None."""
    lo, hi = AGE_BOUNDS
    if not all(lo <= x <= hi for x in (majority, assent_from, assent_to)):
        return f"ages are {lo} to {hi}"
    if assent_from > assent_to or assent_to >= majority:
        return "the assent ages run from the youngest to the oldest, below the age of majority"
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


def review(vals: Mapping[str, Mapping[str, str]], consents: list[dict[str, str]], study_rule: Mapping[str, Any],
           by: Mapping[tuple[str, str], str] | None = None) -> dict[str, Any] | None:  # fmt: skip
    """What the consent in force (the last one recorded) says of the representative and the assent, and the
    warnings (:data:`FLAGS`); None when no consent is recorded. ``by``: who saved each (event, field)."""
    if not consents:
        return None
    ev = consents[-1].get("event", "")
    v = vals.get(ev, {})
    once = vals.get("", {})
    age, age_from = _age(v.get("ic_age", "")), "ic_age"
    if age is None:
        age, age_from = _age(once.get("en_age", "")), ("en_age" if _age(once.get("en_age", "")) is not None else "")
    lar = v.get("ic_lar", "")
    assent = v.get("ic_assent", "")
    out: dict[str, Any] = {
        "event": ev,
        "given_by": "representative" if lar == "1" else "participant" if lar == "0" else "",
        "relation": v.get("ic_lar_rel", "") if lar == "1" else "",
        "relation_other": v.get("ic_lar_other", "")[:40] if lar == "1" and v.get("ic_lar_rel") == "9" else "",
        "assent": assent,
        "assent_why": v.get("ic_assent_why", "") if assent == "0" else "",
        "assent_day": v.get("ic_assent_date", "")[:10] if assent == "1" else "",
        "assent_by": (by or {}).get((ev, "ic_assent"), ""),
        "age": age,
        "age_from": age_from,
        **{k: study_rule[k] for k in ("majority", "assent_from", "assent_to")},
    }
    warn: list[str] = []
    if declined(v):
        warn.append("assent_declined")
    if age is not None and age < int(study_rule["majority"]) and lar != "1":
        warn.append("no_representative")
    if age is not None and int(study_rule["assent_from"]) <= age <= int(study_rule["assent_to"]) and not assent:
        warn.append("no_assent")
    out["warnings"] = warn
    return out
