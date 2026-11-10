"""The ``ad`` archetype: early Alzheimer's disease and MCI at a Japanese memory clinic (T-503, scenario J1).

Every patient is fictional. One planted state per attribute (weights in ``rates.yaml`` ``ad``) decides one criterion
of the synthetic trial AD-MAB and of the registry NEUR-COH, so each criterion has true / false / (where it can be)
unknown cases:

* coded: age band, MCI or Alzheimer's diagnosis, anticoagulant in 90 days, stroke or TIA in 12 months, creatinine
  (eGFR by the Japanese equation, JSN 2009);
* notes: MMSE (an HDS-R score alone never answers it), CDR global score, amyloid status from a PET or CSF report,
  microbleeds and superficial siderosis from a brain MRI report. Reports are written twice, as a report row (exam
  code and conclusion) and as a radiology note, because the note judge reads notes only;
* a person: the study partner (``human_truth``).

Amyloid status is unknown for most patients (no PET or CSF test yet), as at a real memory clinic. The list must
keep them under "needs information", never under "criteria not matched".

The Generator calls :func:`ad_patient` only when the site's mix holds ``ad`` (``Generator(mix="mix_jp_ad")``), so
the default sites and the committed fixtures do not change. Notes are written in Japanese or English (the site's
language mix); a zh-TW site is refused, so a Japanese site never carries Chinese note text.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import ModuleType
from typing import TYPE_CHECKING, Any

from tools.synth import notes_en, notes_ja
from tools.synth.catalog import AD_REPORT_EXAMS, ANTICOAGULANTS

if TYPE_CHECKING:
    from tools.synth.generator import Generator

TRIAL, REGISTRY = "AD-MAB", "NEUR-COH"
NEUR_DOCTORS = ("P90001", "P90002")  # P90001 is the trial's investigator in the demo (tools.list_demo)
PSY_DOCTOR = "P90003"
EGFR_MARGIN = 3.0  # planted eGFR stays this far from the 30 mL/min/1.73 m2 threshold (integer vs decimal age)


def egfr_jsn(scr: float, age: int, female: bool) -> float:
    """JSN 2009, as ``tb_common.derived.egfr_jsn`` (kept here so the generator needs no service library)."""
    val = 194.0 * scr**-1.094 * age**-0.287
    return float(val * 0.739 if female else val)


# criterion id -> (planted attribute, state -> expected answer). Structured: True / False / None (unknown).
STRUCTURED: dict[str, tuple[str, dict[str, bool | None]]] = {
    "AD-MAB-INC-01": ("age_band", {"in": True, "young": False, "old": False}),
    "AD-MAB-INC-02": ("ad_dx", {"mci": True, "ad": True, "uncoded": False}),
    "AD-MAB-EXC-01": ("anticoag", {"current": True, "past": False, "none": False}),
    "AD-MAB-EXC-03": ("stroke", {"recent": True, "old": False, "none": False}),
    "AD-MAB-EXC-04": ("creatinine", {"normal": False, "low": True, "missing": None}),
    "NEUR-COH-INC-01": ("ad_dx", {"mci": True, "ad": True, "uncoded": False}),
    "NEUR-COH-INC-02": ("archetype", {"ad": True}),  # every ad patient visits the memory clinic within 12 months
    "NEUR-COH-INC-03": ("archetype", {"ad": True}),  # every ad patient is 40 or older
}
# note criteria: planted attribute, state -> yes / no / unknown (what a careful reader of the notes answers)
NOTES: dict[str, tuple[str, dict[str, str]]] = {
    "AD-MAB-INC-03": ("mmse", {"in_range": "yes", "low": "no", "hdsr_only": "unknown", "absent": "unknown"}),
    "AD-MAB-INC-04": ("cdr", {"half": "yes", "one": "yes", "two": "no", "absent": "unknown"}),
    "AD-MAB-INC-05": (
        "amyloid",
        {"pet_pos": "yes", "csf_pos": "yes", "pet_neg": "no", "not_done": "unknown", "absent": "unknown"},
    ),
    "AD-MAB-EXC-02": ("microbleeds", {"many": "yes", "siderosis": "yes", "few": "no", "no_mri": "unknown"}),
}
HUMAN = {"AD-MAB-INC-06": "partner"}
TRIAL_KINDS = {
    "AD-MAB-INC-01": "inclusion",
    "AD-MAB-INC-02": "inclusion",
    "AD-MAB-INC-03": "inclusion",
    "AD-MAB-INC-04": "inclusion",
    "AD-MAB-INC-05": "inclusion",
    "AD-MAB-INC-06": "inclusion",
    "AD-MAB-EXC-01": "exclusion",
    "AD-MAB-EXC-02": "exclusion",
    "AD-MAB-EXC-03": "exclusion",
    "AD-MAB-EXC-04": "exclusion",
}


def _rate(archetype: str, attribute: str) -> dict[str, float]:
    from tools.synth.generator import rate

    return rate(archetype, attribute)


def _mod(g: Generator) -> ModuleType:
    if g.L.code == "ja":
        return notes_ja
    if g.L.code == "en":
        return notes_en
    raise ValueError("the ad archetype writes Japanese or English notes only (a Japanese site, T-503)")


def ad_patient(g: Generator, i: int) -> None:
    st = g.state
    sex = "F" if g.rng.random() < 0.6 else "M"
    band = g.pick(_rate("ad", "age_band"))
    age = {"in": g.rng.randint(55, 83), "young": g.rng.randint(42, 47), "old": g.rng.randint(88, 93)}[band]
    mrn = g.patient(i, sex, age)
    mod = _mod(g)
    st(mrn, "archetype", "ad")
    st(mrn, "age_band", band)
    doctor = g.rng.choice(NEUR_DOCTORS)
    # the first memory-clinic visit and its diagnosis
    first = g.days_ago(200, 1500)
    enc = g.encounter(mrn, first, "NEUR", doctor)
    dx = st(mrn, "ad_dx", g.pick(_rate("ad", "ad_dx")))
    key = {"mci": "mci", "ad": g.rng.choice(["ad_late", "ad_unspecified"]), "uncoded": "memory_complaint"}[dx]
    g.dx(mrn, key, first, "NEUR", enc)
    if dx == "ad" and g.rng.random() < 0.6:
        g.rx_course(mrn, "donepezil", g.days_ago(100, 600), 2000, 0, "NEUR")
    # follow-up visits within 12 months (the scope of AD-MAB and NEUR-COH INC-02)
    visits = sorted(g.days_ago(20, 330) for _ in range(g.rng.randint(1, 4)))
    for d in visits:
        staff = PSY_DOCTOR if g.rng.random() < 0.1 else doctor
        enc = g.encounter(mrn, d, "PSY" if staff == PSY_DOCTOR else "NEUR", staff)
        if dx != "uncoded":
            g.dx(mrn, key, d, "NEUR", enc)
    for k in ("htn", "hld", "t2dm"):
        if g.rng.random() < 0.3:
            g.dx(mrn, k, g.days_ago(100, 3000), "FM")
    _anticoagulant(g, mrn, st(mrn, "anticoag", g.pick(_rate("ad", "anticoag"))))
    stroke = st(mrn, "stroke", g.pick(_rate("ad", "stroke")))
    if stroke != "none":
        d = g.days_ago(30, 300) if stroke == "recent" else g.days_ago(450, 2500)
        g.dx(mrn, g.rng.choice(["stroke", "tia"]), d, "NEUR", g.encounter(mrn, d, "NEUR", doctor))
    _creatinine(g, mrn, sex, st(mrn, "creatinine", g.pick(_rate("ad", "creatinine"))))
    # notes: cognitive tests (MMSE, HDS-R, CDR) at one visit, reports, the study partner
    truth = g.data.note_truth.setdefault(mrn, {})
    mmse = st(mrn, "mmse", g.pick(_rate("ad", "mmse")))
    cdr = st(mrn, "cdr", g.pick(_rate("ad", "cdr")))
    body: list[Any] = []
    tested = g.days_ago(10, 150)
    when = g.L.fmt_date(tested)
    hdsr = g.rng.randint(15, 27) if g.rng.random() < 0.5 else None
    if mmse in ("in_range", "low"):
        score = g.rng.randint(22, 29) if mmse == "in_range" else g.rng.randint(12, 20)
        body.append(_find(mod.mmse_sentence(when, score, hdsr), "AD-MAB-INC-03", "yes" if mmse == "in_range" else "no"))
    elif mmse == "hdsr_only":
        body.append(mod.hdsr_only_sentence(when, g.rng.randint(15, 27)))  # never answers the MMSE criterion
    if cdr != "absent":
        value = {"half": "0.5", "one": "1", "two": "2"}[cdr]
        body.append(_find(mod.cdr_sentence(value), "AD-MAB-INC-04", "no" if cdr == "two" else "yes"))
    if body:
        _note(g, mrn, tested, doctor, body)
    amy = st(mrn, "amyloid", g.pick(_rate("ad", "amyloid")))
    if amy in ("pet_pos", "pet_neg"):
        d = g.days_ago(20, 300)
        text = mod.amyloid_pet_report(g.L.fmt_date(d), amy == "pet_pos")
        _report(g, mrn, d, doctor, "PET-AMY", _find(text, "AD-MAB-INC-05", "yes" if amy == "pet_pos" else "no"))
    elif amy == "csf_pos":
        d = g.days_ago(20, 300)
        _report(g, mrn, d, doctor, "CSF-AB", _find(mod.csf_report(g.L.fmt_date(d)), "AD-MAB-INC-05", "yes"))
    elif amy == "not_done":
        _note(g, mrn, g.days_ago(10, 200), doctor, [mod.amyloid_not_done_sentence()])
    mb = st(mrn, "microbleeds", g.pick(_rate("ad", "microbleeds")))
    if mb != "no_mri":
        d = g.days_ago(20, 300)
        n = {"few": g.rng.randint(0, 2), "many": g.rng.randint(5, 9), "siderosis": g.rng.randint(0, 3)}[mb]
        text = mod.mri_report(g.L.fmt_date(d), n, mb == "siderosis")
        _report(g, mrn, d, doctor, "MRI-BRAIN", _find(text, "AD-MAB-EXC-02", "no" if mb == "few" else "yes"))
    partner = g.pick(_rate("ad", "partner"))
    if partner != "no_info":
        _note(
            g,
            mrn,
            g.days_ago(10, 200),
            doctor,
            [_find(mod.partner_sentence(partner == "yes"), "AD-MAB-INC-06", partner)],
        )
    g.data.human_truth.setdefault(mrn, {})["AD-MAB-INC-06"] = partner
    for crit, (attr, answers) in NOTES.items():
        truth[crit] = answers[g.data.states[mrn][attr]]
    st(mrn, "partner", partner)
    appt = st(mrn, "appointment", g.pick(_rate("ad", "appointment")))
    if appt != "none":
        ahead = g.rng.randint(0, 13) if appt == "soon" else g.rng.randint(14, 120)
        weekday = (g.ref + timedelta(days=ahead)).weekday()
        if weekday >= 5:  # the memory clinic runs on weekdays: a weekend booking moves to the Monday
            ahead += 7 - weekday
        g.appointment(mrn, ahead, "NEUR", doctor)


def _find(text: str, criterion: str, value: str) -> Any:
    from tools.synth.generator import Find

    return Find(text, criterion, value)


def _anticoagulant(g: Generator, mrn: str, state: str) -> None:
    if state == "current":
        g.dx(mrn, "af", g.days_ago(200, 2000), "CARD")
        g.rx_course(mrn, g.rng.choice(ANTICOAGULANTS), g.days_ago(150, 700), 2000, 0, "CARD")
    elif state == "past":  # a finished course: the last refill ends more than 200 days before the data date
        g.dx(mrn, "dvt", g.days_ago(520, 900), "CARD")
        g.rx_course(mrn, g.rng.choice(ANTICOAGULANTS), g.days_ago(520, 900), g.rng.randint(90, 300), 0, "CARD")
    elif g.rng.random() < 0.3:  # an antiplatelet drug is not an anticoagulant
        g.rx_course(mrn, "aspirin", g.days_ago(100, 500), 2000, 0, "NEUR")


def _creatinine(g: Generator, mrn: str, sex: str, state: str) -> None:
    if state == "missing":
        return
    age = int(g.age_of(mrn))
    female = sex == "F"
    scr = 1.0
    for _ in range(500):
        scr = round(g.rng.uniform(0.5, 1.4) if state == "normal" else g.rng.uniform(2.0, 4.5), 2)
        e = egfr_jsn(scr, age, female)
        if (state == "normal" and e >= 30 + EGFR_MARGIN) or (state == "low" and e <= 30 - EGFR_MARGIN):
            break
    g.lab(mrn, "CRE", scr, g.days_ago(5, 300))


def _note(g: Generator, mrn: str, d: date, staff: str, body: list[Any], note_type: str = "progress") -> str:
    """A memory-clinic note: the visit's own filler sentences around the finding sentences."""
    mod = _mod(g)
    enc = g.encounter(mrn, d, "NEUR", staff)
    pool: list[str] = mod.AD_FILLER
    parts: list[Any] = ["".join(g.rng.sample(pool, k=g.rng.randint(1, 3)))]
    parts.extend(body)
    parts.append("".join(g.rng.sample(pool, k=g.rng.randint(1, 3))))
    return _write_note(g, mrn, d, enc, parts, note_type)


def _report(g: Generator, mrn: str, d: date, staff: str, exam: str, finding: Any) -> None:
    """A report row (exam code, conclusion) and the same report as a radiology note (the judge reads notes)."""
    name, _ = AD_REPORT_EXAMS[exam]
    g.t["report"].append(
        {
            "rpt_no": g.nid("r"),
            "mrn": mrn,
            "exam_code": exam,
            "exam_name": name,
            "exam_date": d.isoformat(),
            "conclusion": finding.text.strip(),
        }
    )
    enc = g.encounter(mrn, d, "NEUR", staff)
    _write_note(g, mrn, d, enc, [finding], "radiology")


def _write_note(g: Generator, mrn: str, d: date, enc: str, parts: list[Any], note_type: str) -> str:
    note_no = g.nid("n")
    g.t["note"].append(
        {
            "note_no": note_no,
            "mrn": mrn,
            "enc_no": enc,
            "note_datetime": g.dt(d),
            "note_type": note_type,
            "text": g.assemble(note_no, mrn, d, parts),
        }
    )
    return note_no


# ------------------------------------------------------------------------------------------------ the gold
def expected(states: dict[str, str]) -> dict[str, bool | str | None]:
    """What each AD-MAB and NEUR-COH criterion should answer for one ``ad`` patient, from the planted states."""
    out: dict[str, bool | str | None] = {}
    for crit, (attr, answers) in STRUCTURED.items():
        out[crit] = answers[states[attr]]
    for crit, (attr, note_answers) in NOTES.items():
        out[crit] = note_answers[states[attr]]
    for crit, attr in HUMAN.items():
        out[crit] = states[attr]
    return out


def structured_candidate(states: dict[str, str]) -> bool:
    """SPEC §8.2 on the gold: every coded inclusion true or unknown, no coded exclusion true."""
    exp = expected(states)
    coded = [c for c in STRUCTURED if c.startswith(TRIAL + "-")]
    for crit in coded:
        v = exp[crit]
        if TRIAL_KINDS[crit] == "inclusion" and v is False:
            return False
        if TRIAL_KINDS[crit] == "exclusion" and v is True:
            return False
    return True


def tier(states: dict[str, str], notes_read: bool) -> str:
    """The list a careful reader would build: ``excluded`` (criteria not matched), ``review`` (needs information) or
    ``high``. ``notes_read=False`` is a judge that answers every note criterion "unknown" (the test model today)."""
    if not structured_candidate(states):
        return "excluded"
    if not notes_read:
        return "review"
    exp = expected(states)
    answers = {c: exp[c] for c in NOTES}
    if any(
        (TRIAL_KINDS[c] == "inclusion" and a == "no") or (TRIAL_KINDS[c] == "exclusion" and a == "yes")
        for c, a in answers.items()
    ):
        return "excluded"
    if exp["AD-MAB-EXC-04"] is None or any(a == "unknown" for a in answers.values()):
        return "review"
    return "high"
