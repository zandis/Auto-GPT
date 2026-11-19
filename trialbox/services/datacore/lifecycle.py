"""Trial lifecycle v1 (TB-PLAN-04 step 5, D-134): the subject's state, the schedule of events and the visit windows.

**States.** candidate -> approached -> consented -> enrolled -> on study -> completed, or withdrawn, or screen-fail.
``NEXT`` is the only list of legal steps; anything else is refused with a plain reason (``LifeError.why``). The three
end states take no further step; a mistake is put right with ``undo`` (the last step is reversed, as a new step, and
the trail keeps both).

**Where a state comes from.** First the data core's own answers (``derive``): the built-in screening log
(``sl_approached``, ``sl_eligible``), consent (``ic_date``), enrolment (``en_date`` with ``en_eligible``), a visit
done (``vs_status`` 1) and withdrawal (``wd_date``, ``wd_reason``). A step that the answers imply but no form records
(a visit done means the subject was enrolled) is taken too and says so (``implied``). Second, the screening log's
status (the candidate registry, which the REDCap read-back also feeds): for a sponsor study the sponsor's CRF holds
consent and enrolment, TrialBox does not, and the state still follows (labelled ``implied by screening_log``).
Consent is never implied by a TrialBox form (T-516, LIFE-019): an enrolment or a visit without a consent form holds
the subject before ``consented`` (``held`` with ``consent_missing``) until the consent form is saved. Third, a
person's step on the subject page or through ``/api/v1``. Derivation never moves a subject backwards and never past
an end state: what does not fit is reported (``held``), not forced.

**Consent** (D-399, T-302a): every consent a subject gave is read from the forms (the consent form, its old
re-consent slot and each re-consent on an ``rcN`` event); an enrolment or a visit dated before the first consent is
flagged, never moved; a consent's version is checked against the study's approved ICF versions (``icf_check``), and a
new version that asks for re-consent lists the subjects on study still on an older one (``reconsent_due``).

**Every change** is a row in ``subject_step`` (old, new, the day it happened, reason, note, who, when, source); the
callers add the audit record.

**Schedule of events** (``schedule``): per study, each visit with its day after enrolment (or consent) and its window
(days before and after). Defined in TrialBox or read from REDCap's arms and events (``day_offset``, ``offset_min``,
``offset_max``). A visit's answers are the built-in visit form on the event named like the visit.

**Visit windows** (``visit_status``) are computed for a given day (the site's local date), so a test can step through
them: *due* (the window has not opened), *open* (today is in the window), *overdue* (the window has closed), *done*,
*missed* (the visit form says so), *stopped* (the subject left the study before it).

**Working days** (10C-14, JP-15): a visit whose protocol counts its window in working days (``working_days``) has
its days before and after counted in the site's working days (``tb_common.workdays``: Monday to Friday less the
public holidays and New Year break of a country with a holiday list), so a window of 3 working days after a Friday
in Golden Week runs past the holidays. The due day is still the protocol's day number in calendar days. A visit
without the flag counts calendar days, as before.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from tb_common.workdays import WEEKDAYS_ONLY, Calendar

from datacore.forms import XML_ILLEGAL
from datacore.store import DataCore

STATES = ("candidate", "approached", "consented", "enrolled", "on_study", "completed", "withdrawn", "screen_fail")
LINE = ("candidate", "approached", "consented", "enrolled", "on_study", "completed")  # the main line, in order
FINAL = ("completed", "withdrawn", "screen_fail")
NEXT: dict[str, tuple[str, ...]] = {
    "candidate": ("approached", "screen_fail"),
    "approached": ("consented", "screen_fail"),
    "consented": ("enrolled", "screen_fail", "withdrawn"),
    "enrolled": ("on_study", "withdrawn"),
    "on_study": ("completed", "withdrawn"),
    "completed": (),
    "withdrawn": (),
    "screen_fail": (),
}
SCREEN_FAIL_REASONS = ("not_eligible", "declined", "lost_contact", "other")
WITHDRAW_REASONS = ("1", "2", "3", "4", "5", "6")  # the built-in withdrawal form's codes (wd_reason)
# the screening log's status for each state (the candidate registry; the REDCap write-back's tb_status follows it)
REGISTRY_OF = {"candidate": "candidate", "approached": "contacted", "consented": "consented", "enrolled": "enrolled",
               "on_study": "enrolled", "completed": "enrolled", "withdrawn": "withdrawn",
               "screen_fail": "screen_fail"}  # fmt: skip
FROM_REGISTRY = {"candidate": "candidate", "contacted": "approached", "consented": "consented", "enrolled": "enrolled",
                 "screen_fail": "screen_fail", "declined": "screen_fail", "withdrawn": "withdrawn"}  # fmt: skip
ANCHORS = ("enrolment", "consent")
VISIT_STATES = ("due", "open", "overdue", "done", "missed", "stopped")
AE_EVENT = re.compile(r"^ae(\d{1,3})$")
DV_EVENT = re.compile(r"^dv(\d{1,3})$")
_VISIT = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
# D-387 (LIFE-016): the criterion a screen failure ("not_eligible") did not meet, and the criteria version it was judged
# under, as the approved ruleset names them (``GZQO-EXC-06``, ``3.0.0``)
CRITERION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,47}$")
CRITERIA_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,23}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS subject (study TEXT NOT NULL, record TEXT NOT NULL, pid TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL, since TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', changed_by TEXT NOT NULL,
  changed_at TEXT NOT NULL, PRIMARY KEY (study, record));
CREATE TABLE IF NOT EXISTS subject_step (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, old TEXT, new TEXT NOT NULL, on_day TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '', who TEXT NOT NULL, at TEXT NOT NULL, source TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS subject_step_rec ON subject_step (study, record);
CREATE TABLE IF NOT EXISTS schedule (study TEXT NOT NULL, visit TEXT NOT NULL, seq INTEGER NOT NULL,
  labels TEXT NOT NULL DEFAULT '{}', anchor TEXT NOT NULL, day INTEGER NOT NULL, win_before INTEGER NOT NULL,
  win_after INTEGER NOT NULL, origin TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (study, visit))
"""

# review 2026-11-09 P-02/P-03 (D-143): an investigator acknowledges every serious AE (version 3 of the schema)
SAE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ae_ack (study TEXT NOT NULL, record TEXT NOT NULL, event TEXT NOT NULL,
  who TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (study, record, event))
"""
# D-277 (LIFE-023): the study's SAE rule set, chosen on the study set-up page; who confirmed it and when (version 4)
SAE_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS sae_rule (study TEXT NOT NULL PRIMARY KEY, rule_set TEXT NOT NULL,
  confirmed_by TEXT NOT NULL, confirmed_at TEXT NOT NULL)
"""
# D-364 (LIFE-012): every saved schedule is kept as a numbered version with the day it takes effect (version 5); the
# ``schedule`` table stays the newest one saved. A visit done is judged by the version in force on the visit day.
SCHEDULE_VERSIONS = """
CREATE TABLE IF NOT EXISTS schedule_version (study TEXT NOT NULL, version INTEGER NOT NULL,
  effective_from TEXT NOT NULL DEFAULT '', visits TEXT NOT NULL, origin TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY (study, version))
"""
# D-387 (T-623, LIFE-016): a screen failure for "not eligible" keeps the criterion not met and its criteria version
# (version 6, additive: steps made before have none)
SCREEN_FAIL_DETAIL = """
ALTER TABLE subject_step ADD COLUMN IF NOT EXISTS criterion TEXT NOT NULL DEFAULT '';
ALTER TABLE subject_step ADD COLUMN IF NOT EXISTS criteria_version TEXT NOT NULL DEFAULT ''
"""
# D-407 (T-620, LIFE-017, LIFE-025): the study's contact-attempt rule, and the coordinator's answer to each possible
# deviation the box proposes (confirmed as a deviation entry, or dismissed with a reason) (version 7)
CONTACT_AND_DEVIATIONS = """
CREATE TABLE IF NOT EXISTS contact_rule (study TEXT NOT NULL PRIMARY KEY, max_attempts INTEGER NOT NULL,
  min_days INTEGER NOT NULL, set_by TEXT NOT NULL, set_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deviation_call (study TEXT NOT NULL, record TEXT NOT NULL, key TEXT NOT NULL,
  decision TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', event TEXT NOT NULL DEFAULT '', who TEXT NOT NULL,
  at TEXT NOT NULL, PRIMARY KEY (study, record, key))
"""
# 10C-14 (JP-15): a visit whose window the protocol counts in working days (the data core's version 11, after
# ``CONSENT_AGE_RULE``, D-1232; additive: every schedule saved before counts calendar days)
SCHEDULE_WORKING_DAYS = "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS working_days BOOLEAN NOT NULL DEFAULT FALSE"
# the lifecycle's migrations after its base schema, in order (the name is from the first two; never edit an applied one)
SAE_MIGRATIONS = (SAE_SCHEMA, SAE_SCHEMA_V2, SCHEDULE_VERSIONS, SCREEN_FAIL_DETAIL, CONTACT_AND_DEVIATIONS)
# 10C-19 (D-1232): the study's ages for consent by a representative and for assent (version 10, after the sponsor's
# layout and the history's reason); a study with no row has the default (``datacore.proxy_consent.rule``). And which
# recorded decline of assent each reasoned step answered (the store's own order: the history's id, the step's id)
CONSENT_AGE_RULE = """
CREATE TABLE IF NOT EXISTS consent_age_rule (study TEXT NOT NULL PRIMARY KEY, majority INTEGER NOT NULL,
  assent_from INTEGER NOT NULL, assent_to INTEGER NOT NULL, set_by TEXT NOT NULL, set_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assent_proceed (study TEXT NOT NULL, record TEXT NOT NULL, step_id BIGINT NOT NULL,
  decline_id BIGINT NOT NULL, PRIMARY KEY (study, record, step_id))
"""

# D-407 (LIFE-017): contact attempts per study. An attempt is a contact outcome that tried to reach the patient; the
# outcomes that close the contact without a call ("not approached", "lost contact") are never refused. Until the
# study sets its own, three attempts at least one day apart; after the limit the investigator decides.
CONTACT_ATTEMPTS = ("reached_booked", "reached_declined", "not_reached")
CONTACT_DEFAULT = (3, 1)  # (maximum attempts, minimum days between two attempts)
CONTACT_BOUNDS = ((1, 20), (0, 60))
# D-407 (LIFE-025): the kinds of possible deviation the box proposes from its own facts, with the deviation form's
# kind (``dv_kind``) each one becomes when confirmed
PROPOSAL_KINDS = {"visit_window": "3", "consent_version": "2", "consent_after": "2", "consent_after_visit": "2",
                  "eligibility": "1"}  # fmt: skip
DECISIONS = ("confirm", "dismiss")
# D-407 (LIFE-020): randomisation is the sponsor's IRT's act; the enrolment form records that it happened, the day and
# the randomisation number. No arm is ever stored (blinding).
RAND_FIELDS = ("en_rand", "en_rand_date", "en_rand_no")

# The SAE reporting clock (P-03, D-143, D-277): from the moment the site learned of a serious AE (``ae_aware`` and
# ``ae_aware_time``, else the onset) to each report, as (fatal or life-threatening, other serious); 0 = no report to
# that party. A one-day rule is the "at once" report (直ちに; 立即): it is counted in hours, 24 h from the time learned
# (LIFE-022), and when no time was entered from the start of the day learned, the strictest reading. Longer rules are
# calendar days. Each study names one of the sets below on its set-up page (LIFE-023); they are plain defaults that
# the study confirms with its IRB SOP and the protocol (the page records who confirmed and when):
# * ``jp_gcp`` 治験 (J-GCP art. 48), company sponsor: the sponsor and the head of the institution at once; the sponsor
#   reports to PMDA, so no regulator clock at the site.
# * ``jp_gcp_ii`` 医師主導治験: the same, and the investigator reports to PMDA in 7 days (death or a threat to life) or
#   15 days (other).
# * ``jp_crb`` 特定臨床研究 (臨床研究法): the certified review board and MHLW in 7 or 15 days.
# * ``jp_guideline`` 指針 research (生命・医学系指針): the head of the institution at once.
# * ``tw_trial`` 人體試驗 (藥品優良臨床試驗作業準則): the sponsor at once, the IRB and TFDA in 7 or 15 days.
# * ``tw_research`` 人體研究 (人體研究法): the IRB in 7 or 15 days.
# The regulator's name comes from the set, so from the country (UX-005): the same word in every language.
REPORT_PARTIES = ("sponsor", "irb", "regulator")
REPORT_FIELDS = {"sponsor": "ae_rep_sponsor", "irb": "ae_rep_irb", "regulator": "ae_rep_reg"}
HOUR_RULE = 1  # a rule of one day is the 24-hour report, counted in hours


#: NEW-LIFE-8 (D-766): the regulator's days for an EXPECTED reaction (fatal or life-threatening, other), where a set has
#: them; an expected reaction otherwise needs no regulator report (LIFE-024). Not a party: no report row of its own
EXPECTED_REGULATOR = "regulator_expected"


@dataclass(frozen=True)
class RuleSet:
    name: str
    country: str  # JP or TW
    regulator: str  # the regulator's name, the same in every language
    parties: dict[str, tuple[int, int]]


RULE_SETS: dict[str, RuleSet] = {
    "jp_gcp": RuleSet("jp_gcp", "JP", "PMDA", {"sponsor": (1, 1), "irb": (1, 1), "regulator": (0, 0)}),
    # NEW-LIFE-8 (D-766): an expected fatal or life-threatening reaction still has a 15-day PMDA report here
    "jp_gcp_ii": RuleSet(
        "jp_gcp_ii", "JP", "PMDA", {"sponsor": (1, 1), "irb": (1, 1), "regulator": (7, 15), EXPECTED_REGULATOR: (15, 0)}
    ),
    "jp_crb": RuleSet("jp_crb", "JP", "MHLW", {"sponsor": (0, 0), "irb": (7, 15), "regulator": (7, 15)}),
    "jp_guideline": RuleSet("jp_guideline", "JP", "MHLW", {"sponsor": (0, 0), "irb": (1, 1), "regulator": (0, 0)}),
    "tw_trial": RuleSet("tw_trial", "TW", "TFDA", {"sponsor": (1, 1), "irb": (7, 15), "regulator": (7, 15)}),
    "tw_research": RuleSet("tw_research", "TW", "TFDA", {"sponsor": (0, 0), "irb": (7, 15), "regulator": (0, 0)}),
    # NEW-LIFE-8 (D-766): a sponsor's trial at a Taiwan site: the TFDA report is the sponsor's, the site tells the
    # sponsor (24 hours) and the IRB
    "tw_trial_sponsor": RuleSet(
        "tw_trial_sponsor", "TW", "TFDA", {"sponsor": (1, 1), "irb": (7, 15), "regulator": (0, 0)}
    ),
}
RULE_ALIASES = {"jp": "jp_gcp_ii", "tw": "tw_trial"}  # the box-wide names before D-277 (TB_SAE_RULES)
# the country's strictest set: only its regulator's name is shown before a set is chosen (D-766); a country with a
# layer names its own (tb_common.country_layer P2 ``sae_rule_set``, D-1250: Japan's is jp_gcp_ii)
COUNTRY_DEFAULT = {"TW": "tw_trial"}
REPORT_RULES: dict[str, dict[str, tuple[int, int]]] = {k: dict(RULE_SETS[v].parties) for k, v in RULE_ALIASES.items()}
# what the resolved rules can say is wrong; every one is an alert, never a quiet fallback (CR-009)
# NEW-LIFE-8 (D-766): ``unconfirmed``: the study has not chosen its set, so no deadline is shown (an alert; it was the
# country's default with a note, ``default_rules``)
RULE_PROBLEMS = ("unknown_rules", "no_country", "other_country", "bad_override", "noclock", "unconfirmed")
RULE_ALERTS = ("unknown_rules", "no_country", "other_country", "bad_override", "noclock", "unconfirmed")
SERIOUS_WHY = ("1", "2", "3", "4", "5", "6")
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def country_default(country: str) -> str:
    """The rule set whose regulator is shown for a site of ``country`` before a study chooses one: its layer's (P2
    ``sae_rule_set``), else :data:`COUNTRY_DEFAULT`; "" for none, and "" for a site whose country's layer is broken
    (no regulator is shown: :func:`clock_rules` says ``unconfirmed``, the study names its set; D-1250)."""
    from tb_common import country_layer

    try:
        return str(country_layer.value(country, "P2", "sae_rule_set") or COUNTRY_DEFAULT.get(country, ""))
    except country_layer.LayerBroken:
        return ""


def _layer_broken(country: str) -> bool:
    from tb_common import country_layer

    return country_layer.layer(country).broken


def _site_country(tz: str) -> str:
    from tb_common.derived import country_of

    return country_of(tz) or ""


def apply_override(parties: dict[str, tuple[int, int]], override: str) -> list[str]:
    """``TB_SAE_REPORT_DAYS`` (``sponsor=1,irb=7/15,regulator=0``; one number is both) on top of ``parties``; returns
    the parts it could not read, which the caller turns into an alert (CR-009: never ignored silently)."""
    bad: list[str] = []
    for part in (override or "").split(","):
        if not part.strip():
            continue
        key, _, val = part.partition("=")
        key, val = key.strip().lower(), val.strip()
        a, _, b = val.partition("/")
        try:
            if key not in REPORT_PARTIES or not val:
                raise ValueError(part)
            parties[key] = (max(0, int(a)), max(0, int(b or a)))
        except ValueError:
            bad.append(part.strip()[:40])
    return bad


def clock_rules(study_set: str = "", tz: str = "", override: str = "", box_set: str = "") -> dict[str, Any]:
    """The clock in force for one study: the study's named set, then ``override``; with none named, no clock and the
    ``unconfirmed`` alert (D-766), the regulator's name from the box's ``TB_SAE_RULES`` or the site's country. Returns
    ``name``, ``country``, ``regulator``,
    ``parties`` (party -> (fatal or life-threatening, other) days), ``source`` (study, box, country) and
    ``problems`` (:data:`RULE_PROBLEMS`). An unknown name, a zone of no known country or an unreadable override is
    a problem the pages show as an alert, never the Taiwan clock (CR-009)."""
    country = _site_country(tz)
    # the review of D-766: only the study's own set runs a clock ("confirmed by each trial office"); a box-wide
    # ``TB_SAE_RULES`` is named on the page but gives no deadline (it put a TFDA clock on every sponsor trial)
    asked = (study_set or "").strip().lower()
    name = RULE_ALIASES.get(asked, asked)
    source = "study" if study_set else ("box" if box_set else "country")
    problems: list[str] = []
    if apply_override({}, override):  # said whatever the set, also before one is chosen
        problems.append("bad_override")
    if name:
        rs = RULE_SETS.get(name)
        if rs is None:
            problems.append("unknown_rules")
    else:  # NEW-LIFE-8 (D-766): no deadline until the study names its set
        rs = None
        problems.append("unconfirmed" if country_default(country) or _layer_broken(country) else "no_country")
    if rs is not None and country and rs.country != country:
        problems.append("other_country")
    parties = dict(rs.parties) if rs is not None else {}
    if rs is not None:
        apply_override(parties, override)
        if parties.get("regulator") == (0, 0):  # an override that turns the regulator off turns the expected row off
            parties.pop(EXPECTED_REGULATOR, None)
    if "unconfirmed" not in problems and not any(max(v) > 0 for k, v in parties.items() if k in REPORT_PARTIES):
        problems.append("noclock")
    boxed = RULE_SETS.get(RULE_ALIASES.get(box_set.strip().lower(), box_set.strip().lower())) if box_set else None
    shown = rs if rs is not None else boxed or RULE_SETS.get(country_default(country)) if not name else None
    return {"name": rs.name if rs is not None else name[:40], "country": rs.country if rs is not None else country,
            "regulator": shown.regulator if shown is not None else "", "parties": parties, "source": source,
            "problems": problems}  # fmt: skip


def report_rules(tz: str = "", override: str = "", rules: str = "") -> dict[str, tuple[int, int]]:
    """The parties of :func:`clock_rules` for a named set (``rules``, as a study names it) in the site's zone; what the
    pages show as a problem is in :func:`clock_rules`. No set named: no parties (D-766)."""
    return dict(clock_rules(rules, tz, override)["parties"])


def is_serious(e: dict[str, Any]) -> bool:
    """Serious by the form's own answer, or by an answer that only a serious AE has (CR-008): a fatal outcome always;
    a "why serious" reason when Serious is not answered (an import, an old record). A fatal AE whose Serious radio
    says No is still an SAE, with its clock and its alert. An explicit No with a "why serious" left over is not: the
    form hides that field once Serious is No and keeps the old value (``datacore.sync.save_form``), so the reason is
    what the AE was, and a correction to "not serious" must be able to take effect (D-277)."""
    if e.get("ae_serious") == "1" or e.get("ae_outcome") == "5":
        return True
    return e.get("ae_serious") != "0" and e.get("ae_serious_why") in SERIOUS_WHY


def grave(e: dict[str, Any]) -> bool:
    """Fatal or life-threatening: the short clock."""
    return e.get("ae_outcome") == "5" or e.get("ae_serious_why") in ("1", "2")


def aware_time(e: dict[str, Any]) -> time | None:
    m = _HHMM.match(str(e.get("ae_aware_time") or "").strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def start_at(e: dict[str, Any], tz: tzinfo | None = None) -> datetime | None:
    """The moment the clock starts: the day learned at the time learned (else at 00:00), else the onset at 00:00."""
    aware = _day(str(e.get("ae_aware") or ""))
    if aware is not None:
        return datetime.combine(aware, aware_time(e) or time(0, 0), tzinfo=tz)
    onset = _day(str(e.get("ae_onset") or ""))
    return datetime.combine(onset, time(0, 0), tzinfo=tz) if onset is not None else None


def sent_ok(done: str, today: date, start: date | None) -> bool:
    """A "reported on" day that counts: a real date, not after today, not before day 0 (CR-010: 2099 does not)."""
    d = _day(done) if done else None
    return d is not None and d <= today and (start is None or d >= start)


def report_clock(e: dict[str, Any], today: date, rules: dict[str, tuple[int, int]],
                 now: datetime | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """Each report a serious AE needs: party, days, due day (and for the 24-hour report ``hours`` and ``due_at``, the
    site-local moment), the day it was reported (or ""), and overdue at ``now`` (else on ``today``). A regulator
    report is not needed for an AE expected per the reference safety information (``ae_expected`` 1, LIFE-024). A
    "reported on" day that cannot be right (unreadable, after today, before day 0) does not count as sent and is
    marked ``bad_done`` (CR-010)."""
    if not is_serious(e):
        return []
    start = _day(str(e.get("ae_aware") or "")) or _day(str(e.get("ae_onset") or ""))
    tz = now.tzinfo if now is not None else None
    began = start_at(e, tz)
    expected = e.get("ae_expected") == "1"
    # D-766: a suspected reaction unless the investigator says "not related" and the sponsor does not say related
    # (ICH E2A: either one's judgment of a reasonable possibility); "unknown" (9) or no answer counts as suspected
    unrelated = e.get("ae_related") == "0" and e.get("ae_sponsor_related") != "1"
    out = []
    for party in REPORT_PARTIES:
        days = rules.get(party, (0, 0))[0 if grave(e) else 1]
        if party == "regulator" and unrelated:
            continue  # a regulator report is for a suspected reaction (D-766, LIFE-008 c)
        if party == "regulator" and expected:  # LIFE-024; D-766: unless the set has days for an expected reaction
            days = rules.get(EXPECTED_REGULATOR, (0, 0))[0 if grave(e) else 1]
        if days <= 0:
            continue
        row: dict[str, Any] = {"party": party, "days": days}
        if days == HOUR_RULE:
            due_at = began + timedelta(hours=24) if began is not None else None
            due = due_at.date() if due_at is not None else None
            row.update(hours=24, due_at=due_at.isoformat(timespec="minutes") if due_at is not None else "")
            late = (now > due_at) if (now is not None and due_at is not None) else bool(due and today > due)
        else:
            due = start + timedelta(days=days) if start else None
            late = bool(due and today > due)
        done = str(e.get(REPORT_FIELDS[party]) or "")
        ok = sent_ok(done, today, start)
        row.update(due=due.isoformat() if due else "", done=done, overdue=bool(due and not ok and late),
                   bad_done=bool(done and not ok))  # fmt: skip
        out.append(row)
    return out


class LifeError(ValueError):
    """A refused step. ``why`` is a plain-reason key (``life.why.<why>`` in the console's catalogues)."""

    def __init__(self, why: str, message: str, **detail: str) -> None:
        super().__init__(f"LIFE-{why.upper()}: {message}")
        self.code = "LIFE-STEP"
        self.why = why
        self.message = message
        self.detail = detail
        self.fields = [why]


@dataclass(frozen=True)
class Visit:
    name: str
    day: int
    before: int = 0
    after: int = 0
    anchor: str = "enrolment"
    labels: dict[str, str] = field(default_factory=dict)
    working_days: bool = False  # 10C-14: the window (before, after) counts the site's working days

    def as_dict(self) -> dict[str, Any]:
        out = {"visit": self.name, "day": self.day, "before": self.before, "after": self.after,
               "anchor": self.anchor, "labels": dict(self.labels)}  # fmt: skip
        if self.working_days:  # only when set: a schedule saved before reads and writes as it did
            out["working_days"] = True
        return out


def check_visit(v: Visit) -> None:
    if not _VISIT.match(v.name) or AE_EVENT.match(v.name) or DV_EVENT.match(v.name) or RC_EVENT.match(v.name):
        raise LifeError("visit", f"a visit name is lower-case letters, digits and _ (not ae1, dv1, rc1): {v.name!r}",
                        visit=v.name[:40])  # fmt: skip
    if v.anchor not in ANCHORS:
        raise LifeError("anchor", f"a visit counts from {' or '.join(ANCHORS)}", visit=v.name)
    if not (-3650 <= v.day <= 3650 and 0 <= v.before <= 365 and 0 <= v.after <= 365):
        raise LifeError("window", "the day is -3650 to 3650; the window 0 to 365 days each side", visit=v.name)


# ---------------------------------------------------------------------------------------------- consent (D-399)
# T-302a (FIT-009, LIFE-018, LIFE-019): a re-consent is the consent form again on its own numbered event (rc1, rc2
# ...), so a subject can consent again as often as the IRB approves a new version. The study's approved ICF versions
# are a list with history (the console's team store); these functions read it as plain rows:
# {version, effective_from ('' = from the start), irb_approved_on, reconsent (a new version asks for re-consent)}.
RC_EVENT = re.compile(r"^rc(\d{1,3})$")
ICF_WARNINGS = ("icf_none", "icf_not_listed", "icf_unapproved", "icf_not_yet", "icf_superseded")
CONSENT_FLAGS = ("enrolment_before_consent", "visit_before_consent", "no_consent_form", "consent_in_future")
#: NEW-JRN-7 (D-770): the built-in consent form's dates; one after the site's day is refused when a person enters it
#: (``datacore.sync``) and flagged when it arrives another way (a REDCap read-back)
CONSENT_DATES = ("ic_date", "ic_reconsent_date")
ON_STUDY = ("consented", "enrolled", "on_study")  # who is asked to consent again on a new version


def can_step(cur: str, to: str) -> str | None:
    """The refusal reason key for ``cur -> to``, or None when the step is legal."""
    if to not in STATES:
        return "unknown"
    if cur == to:
        return "same"
    if cur in FINAL:
        return "final"
    if to not in NEXT[cur]:
        return "order"
    return None


def _death_day(v: dict[str, str]) -> str:
    """The day of a death recorded on an AE form: the date of death, else the day learned, else the onset."""
    return next((str(v[k]) for k in ("ae_death_date", "ae_aware", "ae_onset") if _day(str(v.get(k) or ""))), "")


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


class Lifecycle:
    """The lifecycle tables in the data core's schema (one trial database, D-126)."""

    def __init__(self, dc: DataCore) -> None:
        self.dc = dc
        self.db = dc.db

    # ------------------------------------------------------------------ subjects
    def subject(self, study: str, record: str) -> dict[str, Any] | None:
        rows = self.db.fetchdicts("SELECT * FROM subject WHERE study = ? AND record = ?", (study, record))
        return rows[0] if rows else None

    def subjects(self, study: str) -> list[dict[str, Any]]:
        return self.db.fetchdicts("SELECT * FROM subject WHERE study = ? ORDER BY record", (study,))

    def steps(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        if record is None:
            return self.db.fetchdicts("SELECT * FROM subject_step WHERE study = ? ORDER BY id", (study,))
        return self.db.fetchdicts("SELECT * FROM subject_step WHERE study = ? AND record = ? ORDER BY id",
                                  (study, record))  # fmt: skip

    def ensure(self, study: str, record: str, pid: str, by: str, at: str) -> tuple[dict[str, Any], bool]:
        """The subject, made a candidate when TrialBox first sees its screening number (or pseudonym)."""
        cur = self.subject(study, record)
        if cur is not None:
            if pid and not cur["pid"]:
                self.db.execute("UPDATE subject SET pid = ? WHERE study = ? AND record = ?", (pid, study, record))
                cur["pid"] = pid
            return cur, False
        with self.db.transaction() as tx:
            tx.execute("INSERT INTO subject (study, record, pid, state, since, reason, changed_by, changed_at) VALUES "
                       "(?,?,?,?,?,?,?,?) ON CONFLICT (study, record) DO NOTHING",
                       (study, record, pid, "candidate", at[:10], "", by, at))  # fmt: skip
            tx.execute("INSERT INTO subject_step (study, record, old, new, on_day, reason, note, who, at, source) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)", (study, record, None, "candidate", at[:10], "", "", by, at,
                                                        "screening"))  # fmt: skip
        out = self.subject(study, record)
        assert out is not None
        return out, True

    def step(self, study: str, record: str, to: str, *, by: str, at: str, on_day: str = "", reason: str = "",
             note: str = "", source: str = "manual", today: date | None = None, criterion: str = "",
             criteria_version: str = "") -> dict[str, Any]:  # fmt: skip
        """One legal step, or ``LifeError`` with the plain reason. ``on_day``: the day it happened (default: today).
        A screen failure for ``not_eligible`` may name the criterion not met and its criteria version (D-387)."""
        cur = self.subject(study, record)
        if cur is None:
            raise LifeError("none", "no subject with that screening number or patient code in this study")
        why = can_step(str(cur["state"]), to)
        if why is not None:
            raise LifeError(why, f"{cur['state']} -> {to} is not a step of the lifecycle", state=str(cur["state"]),
                            to=to, allowed=", ".join(NEXT.get(str(cur["state"]), ())))  # fmt: skip
        if to == "screen_fail" and reason not in SCREEN_FAIL_REASONS:
            raise LifeError("reason", f"a screen failure needs a reason: {', '.join(SCREEN_FAIL_REASONS)}", to=to)
        if to == "withdrawn" and reason not in WITHDRAW_REASONS:
            raise LifeError("reason", "a withdrawal needs a reason (1 to 6, as on the withdrawal form)", to=to)
        criterion, criteria_version = criterion.strip(), criteria_version.strip()
        check_criterion(to, reason, criterion, criteria_version)
        day = _day(on_day or at)
        if day is None:
            raise LifeError("day", "the day is YYYY-MM-DD", to=to)
        if today is not None and day > today:
            raise LifeError("future", "the day of a step cannot be in the future", to=to)
        self._move(study, record, str(cur["state"]), to, day.isoformat(), reason, note[:300], by, at, source,
                   criterion, criteria_version)  # fmt: skip
        out = self.subject(study, record)
        assert out is not None
        return out

    def _move(self, study: str, record: str, old: str, new: str, day: str, reason: str, note: str, by: str, at: str,
              source: str, criterion: str = "", criteria_version: str = "") -> None:  # fmt: skip
        with self.db.transaction() as tx:
            n = tx.execute("UPDATE subject SET state = ?, since = ?, reason = ?, changed_by = ?, changed_at = ? "
                           "WHERE study = ? AND record = ? AND state = ?",
                           (new, day, reason, by, at, study, record, old))  # fmt: skip
            if n != 1:
                raise LifeError("changed", "the subject changed meanwhile; open it again")
            tx.execute(
                "INSERT INTO subject_step (study, record, old, new, on_day, reason, note, who, at, source, criterion, "
                "criteria_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (study, record, old, new, day, reason, note, by, at, source, criterion, criteria_version),
            )

    def undo(self, study: str, record: str, *, by: str, at: str, note: str = "") -> dict[str, Any]:
        """Reverse the last step (a mistake), as a new step; the trail keeps both, and the reason (D-778)."""
        cur = self.subject(study, record)
        if cur is None:
            raise LifeError("none", "no subject with that screening number or patient code in this study")
        note = " ".join(note.split())
        if not note:  # D-778 (LIFE-011): a recorded step is put right only with the reason, kept in the trail
            raise LifeError("undo_reason", "give the reason for the undo (the step recorded by mistake)")
        live = live_steps(self.steps(study, record))
        if len(live) <= 1 or live[-1]["new"] != cur["state"]:
            raise LifeError("undo", "there is no step to undo", state=str(cur["state"]))
        back = live[-2]
        self._move(study, record, str(cur["state"]), str(back["new"]), str(back["on_day"]), str(back["reason"]),
                   note[:300], by, at, "undo")  # fmt: skip
        out = self.subject(study, record)
        assert out is not None
        return out

    # ------------------------------------------------------------------ derivation
    def evidence(self, study: str, record: str, registry: str | None = None,
                 schedule: list[Visit] | None = None) -> dict[str, dict[str, str]]:  # fmt: skip
        """What the answers (and the screening log) say: state -> {day, reason, note, source}."""
        vals: dict[str, dict[str, str]] = {}
        for r in self.dc.values(study, record):
            vals.setdefault(str(r["event"]), {})[str(r["field"])] = str(r["value"])
        once = vals.get("", {})
        out: dict[str, dict[str, str]] = {}

        def put(state: str, day: str, source: str, reason: str = "", note: str = "", criterion: str = "",
                version: str = "") -> None:  # fmt: skip
            if state not in out and _day(day) is not None:
                out[state] = {"day": day[:10], "source": source, "reason": reason, "note": note[:300]}
                if criterion and CRITERION.match(criterion):  # D-387: the form's criterion not met, when given
                    out[state]["criterion"] = criterion
                    out[state]["criteria_version"] = version if CRITERIA_VERSION.match(version) else ""

        if once.get("sl_eligible") == "0":
            put("screen_fail", once.get("sl_date", ""), "form:tb_screening_log", "not_eligible",
                once.get("sl_reason", ""), once.get("sl_criterion", "").strip(),
                once.get("sl_crit_version", "").strip())  # fmt: skip
        if once.get("sl_approached") == "1":
            put("approached", once.get("sl_date", ""), "form:tb_screening_log")
        if once.get("ic_date"):
            put("consented", once["ic_date"], "form:tb_consent")
        if once.get("en_date") and once.get("en_eligible") == "1":
            put("enrolled", once["en_date"], "form:tb_enrolment")
        elif once.get("en_date") and once.get("en_eligible") == "0":
            put("screen_fail", once["en_date"], "form:tb_enrolment", "not_eligible")
        done = sorted((v.get("vs_date", ""), ev) for ev, v in vals.items() if ev and v.get("vs_status") == "1")
        if done:
            put("on_study", done[0][0], f"form:tb_visit:{done[0][1]}")
        sched = schedule or []
        if sched:
            last = max(sched, key=lambda x: (x.day, x.name))
            ends = [vals.get(v.name, {}).get("vs_status") for v in sched]
            lv = vals.get(last.name, {})
            if all(s in ("1", "2") for s in ends) and lv.get("vs_status") == "1":
                put("completed", lv.get("vs_date", ""), f"form:tb_visit:{last.name}")
        if once.get("wd_date"):
            put("withdrawn", once["wd_date"], "form:tb_withdrawal", once.get("wd_reason", "") or "6",
                once.get("wd_note", ""))  # fmt: skip
        deaths = sorted(
            (_death_day(v), ev) for ev, v in vals.items() if AE_EVENT.match(ev) and v.get("ae_outcome") == "5"
        )
        deaths = [d for d in deaths if d[0]]
        if deaths:  # CR-011 (PR #60 M5): a death ends the participant, as the withdrawal form's reason 5 (Death)
            put("withdrawn", deaths[0][0], f"form:tb_adverse_event:{deaths[0][1]}", "5", "death")
        if registry and registry in FROM_REGISTRY and registry != "candidate":
            want = FROM_REGISTRY[registry]
            reason = "declined" if registry == "declined" else ("other" if want == "screen_fail" else "")
            if want == "withdrawn":
                reason = "6"
            if want not in out:  # the forms' own day wins; the screening log gives no day of its own
                out[want] = {"day": "", "source": "screening_log", "reason": reason, "note": ""}
        return out

    def last_decline(self, study: str, record: str) -> int:
        """The history id of the last declined assent ever saved on the participant (0 for none): any consent event,
        dated or not, later corrected or blanked."""
        from datacore import proxy_consent

        ids = [int(h["id"]) for h in self.dc.history(study, record)
               if str(h["field"]) == "ic_assent_why" and str(h["new"]) == proxy_consent.DECLINED]  # fmt: skip
        return max(ids, default=0)

    def assent_hold(self, study: str, record: str) -> bool:
        """10C-19 (D-1232): from the moment a declined assent is saved on the participant (:meth:`last_decline`),
        the participant is held: no form and no screening-log row moves them to "consented" or any later step. Typed
        dates play no part; the order is the store's own (ids). Only two things lift the hold:

        * the reasoned step (a code of ``PROCEED_REASONS`` and a note, ``proxy_consent.proceed_problem``) taken after
          that decline was saved, while the step still stands (an undo takes it back, and the hold returns); or
        * a consent version that did not exist when the decline was saved (its first save comes later in the
          history), on a consent event (the first consent or a re-consent ``rcN``, never a visit or another event),
          saved with the assent obtained. A correction of a version that existed then lifts nothing.

        It holds whatever the setting: a recorded decline is never released by switching it off."""
        from datacore import proxy_consent

        decline = self.last_decline(study, record)
        if not decline:
            return False
        hist = self.dc.history(study, record)
        now = self.dc.record(study, record, "")
        events = {str(h["event"]) for h in hist if str(h["field"]) == "ic_date"}
        for ev in events:
            if not proxy_consent.consent_event(ev):
                continue  # only a canonical consent version (the first consent or rc1, rc2...; never rc02, a visit)
            born = min(int(h["id"]) for h in hist if str(h["event"]) == ev and str(h["field"]) == "ic_date")
            vals = now if ev == "" else self.dc.record(study, record, ev)
            if born > decline and vals.get("ic_assent") == "1" and vals.get("ic_date"):
                return False
        live = {int(st["id"]) for st in live_steps(self.steps(study, record))}
        rows = self.db.fetchdicts("SELECT step_id, decline_id FROM assent_proceed WHERE study = ? AND record = ?",
                                  (study, record))  # fmt: skip
        return not any(int(r["step_id"]) in live and int(r["decline_id"]) >= decline for r in rows)

    def record_proceed(self, study: str, record: str) -> None:
        """The reasoned step just taken answers the last decline saved (the store's order, never a clock)."""
        step = self.steps(study, record)[-1]
        self.db.execute("INSERT INTO assent_proceed (study, record, step_id, decline_id) VALUES (?,?,?,?)",
                        (study, record, int(step["id"]), self.last_decline(study, record)))  # fmt: skip

    def consent_missing(self, study: str, record: str, state: str) -> str:
        """T-516 (LIFE-019): the form that shows enrolment or a visit while no consent form exists and the subject is
        not yet consented, else "". The subject page and the participants list raise it as an alert."""
        if state not in LINE or LINE.index(state) >= LINE.index("consented"):
            return ""
        ev = self.evidence(study, record)
        if "consented" in ev:
            return ""
        later = [ev[s] for s in LINE[LINE.index("consented") + 1 :] if s in ev]
        return next((str(e["source"]) for e in later if str(e["source"]).startswith("form:")), "")

    def records_consent(self, study: str) -> bool:
        """The study records consent in TrialBox (it has the built-in consent form); else the sponsor's CRF does."""
        return "ic_date" in self.dc.fields(study)

    def consent_record(self, study: str, record: str, state: str = "", here: bool | None = None,
                       today: date | None = None) -> dict[str, Any]:  # fmt: skip
        """D-399 (FIT-009, LIFE-018, LIFE-019): every consent the forms record (the first, the old re-consent slot and
        each ``rcN`` event), oldest first; the last one; what is out of order (an enrolment or a visit dated before
        the first consent, a subject past consent with no consent form in a study that records consent here); and
        the event of the next re-consent. Flags are shown, never forced: the forms stay as entered."""
        from datacore import proxy_consent

        vals: dict[str, dict[str, str]] = {}
        by: dict[tuple[str, str], str] = {}
        for r in self.dc.values(study, record):
            vals.setdefault(str(r["event"]), {})[str(r["field"])] = str(r["value"])
            by[(str(r["event"]), str(r["field"]))] = str(r.get("changed_by") or "")
        cs = consents_of(vals)
        flags = consent_order(vals, cs, today)
        here = self.records_consent(study) if here is None else here
        if here and not cs and state in (*ON_STUDY, "completed", "withdrawn"):
            flags.append({"flag": "no_consent_form", "day": "", "event": "", "consent_day": ""})
        have = [int(m.group(1)) for ev in vals if (m := RC_EVENT.match(ev))]
        out: dict[str, Any] = {"consents": cs, "last": cs[-1] if cs else None, "flags": flags, "here": here,
                               "next_rc": f"rc{max(have, default=0) + 1}"}  # fmt: skip
        if proxy_consent.is_on():  # 10C-19 (D-1232): off, the record is as before (no key)
            out["proxy"] = proxy_consent.review(vals, cs, self.consent_age_rule(study), by)
            if out["proxy"] is not None:  # the participant is held until a person goes on with a reason
                out["proxy"]["hold"] = self.assent_hold(study, record)
        return out

    # ------------------------------------------------------------------ consent by a representative, assent (D-1232)
    def consent_age_rule(self, study: str) -> dict[str, Any]:
        """The study's age of majority and assent ages (the default until a person sets them)."""
        from datacore import proxy_consent

        rows = self.db.fetchdicts("SELECT * FROM consent_age_rule WHERE study = ?", (study,))
        return proxy_consent.rule(rows[0] if rows else None)

    def set_consent_age_rule(self, study: str, majority: int, assent_from: int, assent_to: int, by: str,
                             at: str) -> dict[str, Any]:  # fmt: skip
        from datacore import proxy_consent

        why = proxy_consent.check_rule(majority, assent_from, assent_to)
        if why is not None:
            raise LifeError("consent_ages", why)
        self.db.execute("INSERT INTO consent_age_rule (study, majority, assent_from, assent_to, set_by, set_at) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT (study) DO UPDATE SET majority = excluded.majority, "
                        "assent_from = excluded.assent_from, assent_to = excluded.assent_to, "
                        "set_by = excluded.set_by, set_at = excluded.set_at",
                        (study, majority, assent_from, assent_to, by, at))  # fmt: skip
        return self.consent_age_rule(study)

    def derive(self, study: str, record: str, *, by: str, at: str, registry: str | None = None,
               schedule: list[Visit] | None = None) -> dict[str, Any]:  # fmt: skip
        """Walk the subject forward to what the answers say; never backwards, never past an end state.

        Returns ``{"steps": [made], "held": [{state, why}]}``."""
        cur = self.subject(study, record)
        if cur is None:
            return {"steps": [], "held": []}
        ev = self.evidence(study, record, registry, schedule)
        state = str(cur["state"])
        made: list[dict[str, str]] = []
        held: list[dict[str, str]] = []
        today = at[:10]
        line_target = max((LINE.index(s) for s in ev if s in LINE), default=0)
        stop = LINE.index("consented")
        if line_target >= stop and self.assent_hold(study, record):  # whatever the setting (a recorded decline)
            # 10C-19 (D-1232): a declined assent in force: no form or log row moves the participant to consented or
            # beyond; the hold names the next step and why (a person's step with a reason moves on)
            nxt = max(LINE.index(state) + 1, stop) if state in LINE else stop
            if state in LINE and nxt < len(LINE) and LINE.index(state) < line_target:
                held.append(
                    {"state": LINE[nxt], "why": "assent_declined", "current": state, "source": "form:tb_consent"}
                )
            line_target = min(line_target, max(stop - 1, LINE.index(state) if state in LINE else 0))

        def day_for(s: str, fallback: str) -> str:
            return (ev.get(s) or {}).get("day") or fallback

        if state in LINE and LINE.index(state) < line_target:
            for i in range(LINE.index(state) + 1, line_target + 1):
                s = LINE[i]
                e = ev.get(s)
                implied = e is None
                by_ev = next(ev[x] for x in LINE[i : line_target + 1] if x in ev)  # the nearest later evidence
                src = by_ev["source"]
                if implied and s == "consented" and src.startswith("form:"):
                    # T-516 (LIFE-019, D-385): a TrialBox form never implies consent. The study records consent here,
                    # so an enrolment or a visit without a consent form holds the subject and says why
                    held.append({"state": "consented", "why": "consent_missing", "current": state, "source": src})
                    break
                d = day_for(s, by_ev["day"] or today)
                note = (f"implied by {src}" if implied else (e or {}).get("note", ""))[:300]
                self._move(study, record, state, s, d, (e or {}).get("reason", ""), note, by, at, src)
                made.append({"from": state, "to": s, "day": d, "source": src})
                state = s
        elif state in LINE and line_target and LINE.index(state) > line_target and state not in FINAL:
            pass  # a person moved the subject further than the forms say: nothing to do
        for end in ("withdrawn", "screen_fail"):
            e = ev.get(end)
            if e is None or state == end:
                continue
            why = can_step(state, end)
            if why is not None:
                held.append({"state": end, "why": why, "current": state})
                continue
            d = day_for(end, e["day"] or today)
            self._move(study, record, state, end, d, e["reason"], e["note"], by, at, e["source"],
                       e.get("criterion", ""), e.get("criteria_version", ""))  # fmt: skip
            made.append({"from": state, "to": end, "day": d, "source": e["source"]})
            state = end
            break
        return {"steps": made, "held": held}

    def screen_detail(self, study: str) -> dict[str, dict[str, str]]:
        """Per record, what the screening log adds to each row (D-387, LIFE-015, LIFE-016): the day of consent and
        the consent form version, the day of enrolment (the steps that stand), for a screen failure the criterion
        not met with its criteria version, and the day of randomisation in the sponsor's IRT (D-407, LIFE-020)."""
        by_rec: dict[str, list[dict[str, Any]]] = {}
        for st in self.steps(study):
            by_rec.setdefault(str(st["record"]), []).append(st)
        icf: dict[str, str] = {}
        rand: dict[str, dict[str, str]] = {}  # D-407 (LIFE-020): randomised in the sponsor's IRT, and on which day
        for r in self.dc.values(study):
            if str(r["event"]) == "" and str(r["field"]) == "ic_version":
                icf[str(r["record"])] = str(r["value"])
            elif str(r["event"]) == "" and str(r["field"]) in RAND_FIELDS:
                rand.setdefault(str(r["record"]), {})[str(r["field"])] = str(r["value"])
        out: dict[str, dict[str, str]] = {}
        for rec, steps in by_rec.items():
            live = live_steps(steps)
            day = {str(s["new"]): str(s["on_day"]) for s in live}
            last = live[-1] if live else {}
            failed = last.get("new") == "screen_fail"
            out[rec] = {
                "consented": day.get("consented", ""),
                "icf_version": icf.get(rec, ""),
                "enrolled": day.get("enrolled", ""),
                "criterion": str(last.get("criterion") or "") if failed else "",
                "criteria_version": str(last.get("criteria_version") or "") if failed else "",
                "randomised": randomised(rand.get(rec, {})),
            }
        return out

    # ------------------------------------------------------------------ schedule of events
    def schedule(self, study: str) -> list[Visit]:
        rows = self.db.fetchdicts("SELECT * FROM schedule WHERE study = ? ORDER BY seq, visit", (study,))
        return [Visit(str(r["visit"]), int(r["day"]), int(r["win_before"]), int(r["win_after"]), str(r["anchor"]),
                      dict(json.loads(r["labels"] or "{}")), bool(r.get("working_days")))
                for r in rows]  # fmt: skip

    def set_schedule(self, study: str, visits: list[Visit], origin: str, at: str, effective_from: str = "") -> int:
        """Save a schedule as a new version (D-364, LIFE-012); the versions before it stay. ``effective_from`` is the
        first visit day it applies to: an amendment that moves a window from that day leaves the visits done before
        it judged by the schedule they were done under. Empty: from the start (a correction of the schedule, which
        then judges every visit, as before versions). Returns the version number."""
        seen: set[str] = set()
        for v in visits:
            check_visit(v)
            if v.name in seen:
                raise LifeError("visit", f"the visit {v.name} is listed twice", visit=v.name)
            seen.add(v.name)
        if effective_from and _day(effective_from) is None:
            raise LifeError("effective", "the effective date is YYYY-MM-DD")
        body = json.dumps([v.as_dict() for v in visits], ensure_ascii=False)
        old = self.schedule(study)  # a schedule saved before versions existed becomes version 1, from the start
        with self.db.transaction() as tx:
            rows = tx.fetchall("SELECT max(version) FROM schedule_version WHERE study = ?", (study,))
            last = int(rows[0][0]) if rows and rows[0][0] is not None else 0
            if last == 0 and old:
                first = json.dumps([v.as_dict() for v in old], ensure_ascii=False)
                tx.execute("INSERT INTO schedule_version (study, version, effective_from, visits, origin, at) "
                           "VALUES (?,?,?,?,?,?)", (study, 1, "", first, "before", at))  # fmt: skip
                last = 1
            start = effective_from[:10]
            tx.execute("INSERT INTO schedule_version (study, version, effective_from, visits, origin, at) "
                       "VALUES (?,?,?,?,?,?)", (study, last + 1, start, body, origin, at))  # fmt: skip
            tx.execute("DELETE FROM schedule WHERE study = ?", (study,))
            for i, v in enumerate(visits):
                tx.execute("INSERT INTO schedule (study, visit, seq, labels, anchor, day, win_before, win_after, "
                           "origin, at, working_days) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (study, v.name, i, json.dumps(v.labels, ensure_ascii=False), v.anchor, v.day, v.before,
                            v.after, origin, at, v.working_days))  # fmt: skip
        return last + 1

    def schedule_versions(self, study: str) -> list[dict[str, Any]]:
        """Every saved schedule of the study, oldest first: version, effective_from ('' = from the start), visits."""
        rows = self.db.fetchdicts("SELECT * FROM schedule_version WHERE study = ? ORDER BY version", (study,))
        return [{"version": int(r["version"]), "effective_from": str(r["effective_from"] or ""),
                 "origin": str(r["origin"]), "at": str(r["at"]),
                 "visits": [Visit(str(v["visit"]), int(v["day"]), int(v["before"]), int(v["after"]), str(v["anchor"]),
                                  dict(v.get("labels") or {}), bool(v.get("working_days")))
                            for v in json.loads(r["visits"] or "[]")]}
                for r in rows]  # fmt: skip

    def schedule_on(self, study: str, day: date, versions: list[dict[str, Any]] | None = None) -> list[Visit]:
        """The schedule in force on ``day``: the newest version whose effective date has come (D-364). A study whose
        schedule was never versioned has the one ``schedule`` table."""
        vers = self.schedule_versions(study) if versions is None else versions
        if not vers:
            return self.schedule(study)
        return list(in_force_on(vers, day)["visits"])

    # ------------------------------------------------------------------ visits, AEs, deviations
    def anchors(self, study: str, record: str) -> dict[str, date | None]:
        once = self.dc.record(study, record, "")
        steps = {str(s["new"]): str(s["on_day"]) for s in self.steps(study, record) if s["source"] != "undo"}
        return {
            "enrolment": _day(once.get("en_date", "") or steps.get("enrolled", "")),
            "consent": _day(once.get("ic_date", "") or steps.get("consented", "")),
        }

    def visits(self, study: str, record: str, today: date, schedule: list[Visit] | None = None,
               subject: dict[str, Any] | None = None,
               cal: Calendar = WEEKDAYS_ONLY) -> list[dict[str, Any]]:  # fmt: skip
        vers = self.schedule_versions(study)
        if schedule is not None:
            sched = schedule
        else:
            sched = self.schedule_on(study, today, vers) if vers else self.schedule(study)
        sub = subject or self.subject(study, record) or {"state": "candidate"}
        anchors = self.anchors(study, record)
        vals: dict[str, dict[str, str]] = {}
        for r in self.dc.values(study, record):
            vals.setdefault(str(r["event"]), {})[str(r["field"])] = str(r["value"])
        out = []
        for v in sched:
            row = visit_status(v, anchors.get(v.anchor), vals.get(v.name, {}), str(sub["state"]), today, cal)
            if vers:  # D-364 (LIFE-012): a visit done is judged by the schedule in force on the visit day
                on = _day(row["done_on"]) if row["status"] == "done" else None
                then = in_force_on(vers, on or today)
                was = next((w for w in then["visits"] if w.name == v.name), None)
                if on is not None and was is not None and was != v:
                    row = visit_status(was, anchors.get(was.anchor), vals.get(v.name, {}), str(sub["state"]), today,
                                       cal)  # fmt: skip
                row["schedule_version"] = then["version"] if was is not None else in_force_on(vers, today)["version"]
            out.append(row)
        return out

    def entries(self, study: str, record: str | None, pattern: re.Pattern[str]) -> list[dict[str, Any]]:
        """Repeating entries on numbered events (``ae1``, ``ae2`` ...): one dict per record and event."""
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for r in self.dc.values(study, record):
            m = pattern.match(str(r["event"]))
            if m is None:
                continue
            e = out.setdefault((str(r["record"]), str(r["event"])), {"record": r["record"], "event": r["event"],
                                                                     "n": int(m.group(1))})  # fmt: skip
            e[str(r["field"])] = str(r["value"])
        return sorted(out.values(), key=lambda e: (e["record"], e["n"]))

    def acks(self, study: str) -> dict[tuple[str, str], dict[str, Any]]:
        """The investigator's acknowledgements of serious AEs, by (record, event)."""
        rows = self.db.fetchdicts("SELECT * FROM ae_ack WHERE study = ?", (study,))
        return {(str(r["record"]), str(r["event"])): r for r in rows}

    def ack(self, study: str, record: str, event: str, who: str, at: str) -> dict[str, Any]:
        """One tap: the first acknowledgement stands (who and when); a second is a no-op."""
        self.db.execute("INSERT INTO ae_ack (study, record, event, who, at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT (study, record, event) DO NOTHING", (study, record, event, who, at))  # fmt: skip
        return self.acks(study)[(record, event)]

    def sae_rule(self, study: str) -> dict[str, Any] | None:
        """The study's SAE rule set (D-277), who confirmed it and when; None until the set-up page names one."""
        rows = self.db.fetchdicts("SELECT * FROM sae_rule WHERE study = ?", (study,))
        return rows[0] if rows else None

    def set_sae_rule(self, study: str, rule_set: str, by: str, at: str) -> dict[str, Any]:
        """Name the study's SAE rule set (one of :data:`RULE_SETS`); the person saving it confirms it."""
        if rule_set not in RULE_SETS:
            raise LifeError("rules", f"the SAE rule set is one of {', '.join(RULE_SETS)}")
        self.db.execute("INSERT INTO sae_rule (study, rule_set, confirmed_by, confirmed_at) VALUES (?,?,?,?) "
                        "ON CONFLICT (study) DO UPDATE SET rule_set = excluded.rule_set, "
                        "confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at",
                        (study, rule_set, by, at))  # fmt: skip
        out = self.sae_rule(study)
        assert out is not None
        return out

    def next_event(self, study: str, record: str, prefix: str) -> str:
        pat = AE_EVENT if prefix == "ae" else DV_EVENT
        have = [e["n"] for e in self.entries(study, record, pat)]
        return f"{prefix}{max(have, default=0) + 1}"

    # ------------------------------------------------------------------ contact attempts (D-407, LIFE-017)
    def contact_rule(self, study: str) -> dict[str, Any]:
        """The study's contact-attempt rule: ``max_attempts``, ``min_days``, who set it and when (``set_by`` is ""
        while the default of :data:`CONTACT_DEFAULT` applies)."""
        rows = self.db.fetchdicts("SELECT * FROM contact_rule WHERE study = ?", (study,))
        if not rows:
            return {"max_attempts": CONTACT_DEFAULT[0], "min_days": CONTACT_DEFAULT[1], "set_by": "", "set_at": ""}
        r = rows[0]
        return {"max_attempts": int(r["max_attempts"]), "min_days": int(r["min_days"]), "set_by": str(r["set_by"]),
                "set_at": str(r["set_at"])}  # fmt: skip

    def set_contact_rule(self, study: str, max_attempts: int, min_days: int, by: str, at: str) -> dict[str, Any]:
        (lo_a, hi_a), (lo_d, hi_d) = CONTACT_BOUNDS
        if not (lo_a <= max_attempts <= hi_a and lo_d <= min_days <= hi_d):
            raise LifeError("contact_rule", f"attempts are {lo_a} to {hi_a}; days between attempts {lo_d} to {hi_d}")
        self.db.execute("INSERT INTO contact_rule (study, max_attempts, min_days, set_by, set_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT (study) DO UPDATE SET max_attempts = excluded.max_attempts, "
                        "min_days = excluded.min_days, set_by = excluded.set_by, set_at = excluded.set_at",
                        (study, max_attempts, min_days, by, at))  # fmt: skip
        return self.contact_rule(study)

    # ------------------------------------------------------------------ possible deviations (D-407, LIFE-025)
    def possible_deviations(self, study: str, today: date, icf_version: str = "",
                            cal: Calendar = WEEKDAYS_ONLY) -> list[dict[str, Any]]:  # fmt: skip
        """What the box's own facts say may be a deviation, one proposal per subject and fact, each with the
        coordinator's answer when there is one (``state``: open, confirmed, dismissed). Never a deviation entry by
        itself: a proposal becomes one only when a person confirms it. ``icf_version``: the consent form version in
        force for the study (the study's IRB record), when known."""
        calls = {(str(r["record"]), str(r["key"])): r
                 for r in self.db.fetchdicts("SELECT * FROM deviation_call WHERE study = ?", (study,))}  # fmt: skip
        out: list[dict[str, Any]] = []
        for sub in self.subjects(study):
            rec = str(sub["record"])
            for p in self._proposals(study, rec, sub, today, icf_version, cal):
                c = calls.get((rec, p["key"]))
                out.append({**p, "record": rec, "pid": str(sub["pid"]), "dv_kind": PROPOSAL_KINDS[p["kind"]],
                            "state": {"confirm": "confirmed", "dismiss": "dismissed"}[str(c["decision"])] if c
                            else "open", "reason": str((c or {}).get("reason") or ""),
                            "event": str((c or {}).get("event") or ""), "who": str((c or {}).get("who") or ""),
                            "at": str((c or {}).get("at") or "")})  # fmt: skip
        return out

    def _proposals(self, study: str, rec: str, sub: dict[str, Any], today: date,
                   icf_version: str, cal: Calendar = WEEKDAYS_ONLY) -> list[dict[str, Any]]:  # fmt: skip
        vals: dict[str, dict[str, str]] = {}
        for r in self.dc.values(study, rec):
            vals.setdefault(str(r["event"]), {})[str(r["field"])] = str(r["value"])
        once = vals.get("", {})
        out: list[dict[str, Any]] = []
        for v in self.visits(study, rec, today, subject=sub, cal=cal):
            if v["status"] != "done":
                continue
            said_out = vals.get(str(v["visit"]), {}).get("vs_window") == "0"
            if (v["start"] and v["in_window"] is False) or said_out:
                out.append({"kind": "visit_window", "key": f"visit_window:{v['visit']}", "day": v["done_on"],
                            "detail": {"visit": v["visit"], "done": v["done_on"], "start": v["start"],
                                       "end": v["end"]},
                            "text": f"Visit {v['visit']} done on {v['done_on']}, outside its window "
                                    f"{v['start'] or '?'} to {v['end'] or '?'}."})  # fmt: skip
        icd, icv = once.get("ic_date", ""), once.get("ic_version", "").strip()
        if icd and icv and icf_version.strip() and icv.casefold() != icf_version.strip().casefold():
            out.append({"kind": "consent_version", "key": f"consent_version:{icv[:40]}", "day": icd[:10],
                        "detail": {"version": icv[:40], "in_force": icf_version.strip()[:40], "day": icd[:10]},
                        "text": f"Consent on {icd[:10]} used form version {icv[:40]}; the version in force is "
                                f"{icf_version.strip()[:40]}."})  # fmt: skip
        ic, en = _day(icd), _day(once.get("en_date", ""))
        if ic is not None and en is not None and en < ic:
            out.append({"kind": "consent_after", "key": "consent_after:enrolment", "day": en.isoformat(),
                        "detail": {"enrolled": en.isoformat(), "consented": ic.isoformat()},
                        "text": f"Enrolled on {en.isoformat()}, before consent on {ic.isoformat()}."})  # fmt: skip
        for ev, v in sorted(vals.items()):  # NEW-JRN-7 (D-770): a visit done before consent, as for enrolment
            vd = _day(v.get("vs_date", ""))
            if ev and ic is not None and v.get("vs_status") == "1" and vd is not None and vd < ic:
                out.append({"kind": "consent_after_visit", "key": f"consent_after:visit:{ev[:40]}",
                            "day": vd.isoformat(),
                            "detail": {"visit": ev[:40], "done": vd.isoformat(), "consented": ic.isoformat()},
                            "text": f"Visit {ev[:40]} done on {vd.isoformat()}, before consent on "
                                    f"{ic.isoformat()}."})  # fmt: skip
        if en is not None and once.get("en_eligible") == "1" and once.get("sl_eligible") == "0":
            crit = once.get("sl_criterion", "").strip()
            crit = crit if CRITERION.match(crit) else ""
            out.append({"kind": "eligibility", "key": "eligibility:screening_log", "day": en.isoformat(),
                        "detail": {"enrolled": en.isoformat(), "criterion": crit},
                        "text": f"Enrolled on {en.isoformat()} while the screening log says not eligible"
                                f"{f' (criterion {crit})' if crit else ''}."})  # fmt: skip
        return out

    def decide_deviation(self, study: str, record: str, key: str, decision: str, *, reason: str = "", by: str,
                         at: str, today: date, icf_version: str = "",
                         cal: Calendar = WEEKDAYS_ONLY) -> dict[str, Any]:  # fmt: skip
        """The coordinator's answer to one proposal: ``confirm`` writes a deviation entry (the next ``dvN`` event:
        date, kind, what happened; class and reports are then completed on the form), ``dismiss`` keeps the reason.
        One answer per proposal; a second is refused."""
        if decision not in DECISIONS:
            raise LifeError("decision", "confirm or dismiss the possible deviation")
        reason = reason.strip()[:300]
        if XML_ILLEGAL.search(reason):  # EDC-010 (D-581): it is written into a value and the trail
            raise LifeError("chars", "the reason holds a character that cannot be stored (a control character)")
        if decision == "dismiss" and not reason:
            raise LifeError("dismiss_reason", "say why this is not a deviation")
        one = next((p for p in self.possible_deviations(study, today, icf_version, cal)
                    if p["record"] == record and p["key"] == key), None)  # fmt: skip
        if one is None:
            raise LifeError("proposal", "no such possible deviation for this subject")
        if one["state"] != "open":
            raise LifeError("decided", f"this possible deviation was already {one['state']}", state=one["state"])
        event = self.next_event(study, record, "dv") if decision == "confirm" else ""
        n = self.db.execute("INSERT INTO deviation_call (study, record, key, decision, reason, event, who, at) "
                            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (study, record, key) DO NOTHING",
                            (study, record, key, decision, reason, event, by, at))  # fmt: skip
        if n != 1:
            raise LifeError("decided", "this possible deviation was answered meanwhile")
        if event:
            note = one["text"] + (f" {reason}" if reason else "")
            for f, v in (("dv_date", one["day"]), ("dv_kind", one["dv_kind"]), ("dv_what", note[:1000])):
                self.dc.write(study, record, event, f, v, by, at, "trialbox:proposed")
        return {**one, "state": "confirmed" if event else "dismissed", "reason": reason, "event": event, "who": by,
                "at": at}  # fmt: skip


def randomised(v: dict[str, str]) -> str:
    """The randomisation day the enrolment form gives (``en_rand`` 1 and ``en_rand_date``), "yes" when the day is
    missing, else "" (D-407, LIFE-020)."""
    if v.get("en_rand") != "1":
        return ""
    d = _day(v.get("en_rand_date", ""))
    return d.isoformat() if d else "yes"


def contact_check(attempt_days: list[str], max_attempts: int, min_days: int, today: date) -> dict[str, Any]:
    """D-407 (LIFE-017): may the coordinator record one more contact attempt today? ``attempt_days`` are the days
    (YYYY-MM-DD, site time) of the attempts recorded so far. ``why``: "" (yes), ``limit`` (the study's maximum is
    reached: the investigator decides what follows) or ``too_soon`` (fewer than ``min_days`` since the last; ``next``
    is the first day allowed)."""
    days = sorted(d for d in (_day(x) for x in attempt_days) if d is not None)
    n = len(days)
    out: dict[str, Any] = {"attempts": n, "max": max_attempts, "min_days": min_days, "why": "", "next": ""}
    if n >= max_attempts:
        out["why"] = "limit"
    elif days and min_days > 0 and (today - days[-1]).days < min_days:
        out["why"] = "too_soon"
        out["next"] = (days[-1] + timedelta(days=min_days)).isoformat()
    return out


def in_force_on(versions: list[dict[str, Any]], day: date) -> dict[str, Any]:
    """The schedule version in force on ``day`` (D-364): the newest whose effective date ('' = from the start) has
    come; before every effective date, the first version."""
    best = versions[0]
    for v in versions:
        eff = _day(v["effective_from"]) if v["effective_from"] else None
        if eff is None or eff <= day:
            best = v
    return best


def check_criterion(to: str, reason: str, criterion: str, criteria_version: str) -> None:
    """D-387 (LIFE-016): only a screen failure for ``not_eligible`` names a criterion; a version needs a criterion."""
    if not criterion and not criteria_version:
        return
    if to != "screen_fail" or reason != "not_eligible":
        raise LifeError("criterion_only", "only a screen failure for not_eligible names a criterion", to=to)
    if not CRITERION.match(criterion):
        raise LifeError("criterion", "the criterion is the id the approved criteria give it (for example EXC-06)",
                        to=to)  # fmt: skip
    if criteria_version and not CRITERIA_VERSION.match(criteria_version):
        raise LifeError("criterion", "the criteria version is short: letters, digits, '.', '-', '+' and '_'", to=to)


def failed_label(criterion: str, version: str) -> str:
    """How a log row names the criterion not met: ``EXC-06 (v3.0)`` (D-387)."""
    if not criterion:
        return ""
    return f"{criterion} (v{version})" if version else criterion


def live_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One subject's steps that stand: an ``undo`` takes back the newest step still standing."""
    out: list[dict[str, Any]] = []
    for st in steps:
        if st["source"] == "undo":
            if len(out) > 1:
                out.pop()
        else:
            out.append(st)
    return out


def visit_status(v: Visit, anchor: date | None, vals: dict[str, str], state: str, today: date,
                 cal: Calendar = WEEKDAYS_ONLY) -> dict[str, Any]:  # fmt: skip
    """One visit's window and state on ``today`` (the site's local date); ``cal``, the site's working days, counts
    the window of a visit whose protocol says working days (10C-14)."""
    due = anchor + timedelta(days=v.day) if anchor else None
    start: date | None = None
    end: date | None = None
    if due is not None and v.working_days:
        try:
            start, end = cal.add_working_days(due, -v.before), cal.add_working_days(due, v.after)
        except (ValueError, OverflowError):  # no working day to count to (or past 9999): calendar days, never none
            start, end = due - timedelta(days=v.before), due + timedelta(days=v.after)
    else:
        start = due - timedelta(days=v.before) if due else None
        end = due + timedelta(days=v.after) if due else None
    done_on = vals.get("vs_date", "")
    if vals.get("vs_status") == "1":
        status = "done"
    elif vals.get("vs_status") == "2":
        status = "missed"
    elif state in ("withdrawn", "completed", "screen_fail"):
        status = "stopped"
    elif due is None or start is None or end is None:
        status = "unplanned"
    elif today < start:
        status = "due"
    elif today <= end:
        status = "open"
    else:
        status = "overdue"
    d = _day(done_on)
    in_window = bool(d and start and end and start <= d <= end) if status == "done" else None
    return {
        "visit": v.name,
        "labels": v.labels,
        "day": v.day,
        "anchor": v.anchor,
        "due": due.isoformat() if due else "",
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "status": status,
        "done_on": done_on if status == "done" else "",
        "in_window": in_window,
        "missed_reason": vals.get("vs_missed_reason", "") if status == "missed" else "",
        "days_late": (today - end).days if status == "overdue" and end else 0,
        # 10C-14: a working-days window reaching a year the holiday list does not know (after its last day, or before
        # its first year): its holidays there are not skipped. Only on such a row, so other rows read as before.
        **(
            {"days_off_unknown": True}
            if v.working_days and start and end and cal.has_days_off and not (cal.covers(start) and cal.covers(end))
            else {}
        ),
    }


def in_window_today(row: dict[str, Any], today: date) -> bool:
    s, e = _day(str(row.get("start") or "")), _day(str(row.get("end") or ""))
    return bool(s and e and s <= today <= e)


def worklist(rows: list[dict[str, Any]], today: date) -> dict[str, list[dict[str, Any]]]:
    """The coordinator's visit list: today, this week (the next seven days), overdue."""
    week_end = today + timedelta(days=7)
    out: dict[str, list[dict[str, Any]]] = {"today": [], "week": [], "overdue": []}
    for r in rows:
        if r["status"] == "overdue":
            out["overdue"].append(r)
        elif r["status"] == "open" and (r["due"] == today.isoformat() or r["end"] == today.isoformat()):
            out["today"].append(r)
        elif r["status"] in ("open", "due") and (_day(r["start"]) or week_end) <= week_end:
            out["week"].append(r)
    for rows_k in out.values():
        rows_k.sort(key=lambda r: (r["due"], r["record"], r["visit"]))
    return out


def report(subjects: list[dict[str, Any]], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The investigator's enrolment report: counts per state, per month, screen-fail reasons and withdrawals."""
    counts = {s: 0 for s in STATES}
    for s in subjects:
        counts[str(s["state"])] = counts.get(str(s["state"]), 0) + 1
    by_rec: dict[str, list[dict[str, Any]]] = {}
    for st in steps:
        by_rec.setdefault(str(st["record"]), []).append(st)
    live = [st for rec_steps in by_rec.values() for st in live_steps(rec_steps)]
    months: dict[str, dict[str, int]] = {}
    reached: dict[str, set[str]] = {s: set() for s in STATES}
    for st in live:
        new = str(st["new"])
        reached[new].add(str(st["record"]))
        if new == "candidate":
            continue
        m = months.setdefault(str(st["on_day"])[:7], {s: 0 for s in STATES if s != "candidate"})
        m[new] += 1
    current = {str(s["record"]): s for s in subjects}
    reasons: Counter[str] = Counter()
    withdrawals = []
    for rec, s in sorted(current.items()):
        if s["state"] == "screen_fail":
            reasons[str(s["reason"] or "other")] += 1
        if s["state"] == "withdrawn":
            withdrawals.append({"record": rec, "day": str(s["since"]), "reason": str(s["reason"] or "6")})
    ever = {s: len(reached[s]) for s in STATES}
    return {
        "total": len(subjects),
        "counts": counts,
        "ever": ever,
        "months": [{"month": k, **v} for k, v in sorted(months.items())],
        "screen_fail_reasons": dict(sorted(reasons.items())),
        "withdrawals": withdrawals,
        "registry": dict(Counter(REGISTRY_OF[str(s["state"])] for s in subjects)),
    }


# ---------------------------------------------------------------------------------------------- consent (D-399)
def _ver(text: str) -> str:
    """A version as compared: no spaces, any case (``V2.1`` is ``v 2.1``)."""
    return re.sub(r"\s+", "", str(text or "")).casefold()


def consents_of(vals: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """Every consent the forms record, oldest first: {day, version, event, kind} (kind ``first`` or ``reconsent``)."""
    out: list[dict[str, str]] = []
    once = vals.get("", {})
    if _day(once.get("ic_date", "")) is not None:
        out.append({"day": once["ic_date"][:10], "version": once.get("ic_version", "").strip(), "event": "",
                    "kind": "first"})  # fmt: skip
    if once.get("ic_reconsent") == "1" and _day(once.get("ic_reconsent_date", "")) is not None:
        out.append({"day": once["ic_reconsent_date"][:10], "version": once.get("ic_reconsent_version", "").strip(),
                    "event": "", "kind": "reconsent"})  # fmt: skip
    for ev, v in vals.items():
        if RC_EVENT.match(ev) and _day(v.get("ic_date", "")) is not None:
            out.append({"day": v["ic_date"][:10], "version": v.get("ic_version", "").strip(), "event": ev,
                        "kind": "reconsent"})  # fmt: skip
    out.sort(key=lambda c: (c["day"], c["kind"] != "first", len(c["event"]), c["event"]))
    return out


def consent_order(vals: dict[str, dict[str, str]], consents: list[dict[str, str]],
                  today: date | None = None) -> list[dict[str, str]]:  # fmt: skip
    """LIFE-019: an enrolment or a visit done dated before the first consent. Each is flagged (the subject page
    offers a deviation entry); the dates are never changed. NEW-JRN-7 (D-770): a consent dated after ``today`` (it
    came by a REDCap read-back, which writes REDCap's values as they are) is flagged too."""
    if not consents:
        return []
    first = consents[0]["day"]
    out: list[dict[str, str]] = []
    if today is not None:
        for c in consents:
            if c["day"] > today.isoformat():
                out.append({"flag": "consent_in_future", "day": c["day"], "event": c.get("event", ""),
                            "consent_day": c["day"]})  # fmt: skip
    en = vals.get("", {}).get("en_date", "")
    if _day(en) is not None and en[:10] < first:
        out.append({"flag": "enrolment_before_consent", "day": en[:10], "event": "", "consent_day": first})
    for ev, v in sorted(vals.items()):
        day = v.get("vs_date", "")
        if ev and v.get("vs_status") == "1" and _day(day) is not None and day[:10] < first:
            out.append({"flag": "visit_before_consent", "day": day[:10], "event": ev, "consent_day": first})
    return out


def icf_ordered(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The approved versions in the order they came into force (an empty effective date is from the start)."""
    return sorted(versions, key=lambda v: (str(v.get("effective_from") or ""), int(v.get("seq") or 0)))


def icf_in_force(versions: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    """The ICF version in force on ``day``: the newest whose effective date has come; None before every one."""
    best = None
    for v in icf_ordered(versions):
        eff = _day(str(v.get("effective_from") or ""))
        if eff is None or eff <= day:
            best = v
    return best


def icf_check(versions: list[dict[str, Any]], version: str, day: str) -> list[str]:
    """URS-CRC-07 (FIT-009): why a consent on ``version`` on ``day`` needs a second look; [] when it is fine. A
    warning, never a refusal: the consent happened and the form records it as it was (:data:`ICF_WARNINGS`)."""
    if not versions:
        return ["icf_none"]
    listed = next((v for v in versions if _ver(v.get("version", "")) == _ver(version)), None)
    if listed is None:
        return ["icf_not_listed"]
    approved = _day(str(listed.get("irb_approved_on") or ""))
    if approved is None:
        return ["icf_unapproved"]
    d = _day(day)
    if d is None:
        return []
    eff = _day(str(listed.get("effective_from") or "")) or approved
    if d < approved or d < eff:
        return ["icf_not_yet"]
    now = icf_in_force(versions, d)
    if now is not None and _ver(now.get("version", "")) != _ver(listed.get("version", "")):
        return ["icf_superseded"]
    return []


def reconsent_due(subjects: list[dict[str, Any]], versions: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """LIFE-018: the re-consent worklist. The newest version in force on ``today`` that asks for re-consent is the
    target; every subject on study (consented, enrolled, on study) whose last recorded consent is on an older version,
    or on one not on the list, is listed. Each subject carries ``consent`` (:meth:`Lifecycle.consent_record`); a
    subject with no consent form is not listed here (the subject page raises that)."""
    ordered = icf_ordered(versions)
    asks = [v for v in ordered if v.get("reconsent", True) and icf_in_force([v], today) is not None]
    if not asks:
        return {"target": None, "rows": []}
    target = asks[-1]
    rank = {_ver(v.get("version", "")): i for i, v in enumerate(ordered)}
    goal = rank[_ver(target.get("version", ""))]
    rows = []
    for s in subjects:
        last = (s.get("consent") or {}).get("last")
        if str(s.get("state")) not in ON_STUDY or not last:
            continue
        if rank.get(_ver(last.get("version", "")), -1) >= goal:
            continue
        rows.append({"record": s.get("record"), "pid": s.get("pid") or "", "state": s.get("state"),
                     "version": last.get("version", ""), "day": last.get("day", ""),
                     "listed": _ver(last.get("version", "")) in rank,
                     "next_rc": (s.get("consent") or {}).get("next_rc", "rc1")})  # fmt: skip
    rows.sort(key=lambda r: (str(r["day"]), str(r["record"])))
    return {"target": target, "rows": rows}
