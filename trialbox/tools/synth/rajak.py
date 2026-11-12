"""The ``rajak`` archetype: rheumatoid arthritis at a Taiwanese rheumatology clinic, screened for a JAK-inhibitor
trial (T-504, scenario T2 of the clinician PoC: the synthetic trial RA-JAK).

Every patient is fictional. One planted state per attribute (weights in ``rates.yaml`` ``rajak``) decides one RA-JAK
criterion, so each criterion has true, false and (where it can be) unknown cases:

* coded: age band, RA diagnosis and its age, methotrexate course, DAS28 components (a derived score, from one visit),
  prior biologic or JAK inhibitor, HBsAg, IGRA and tuberculosis preventive therapy, serious infection, malignancy,
  heart failure, pregnancy, creatinine (eGFR by CKD-EPI 2021);
* the two states planted for this trial, each coded, written only in the notes, or denied in the notes:
  **herpes zoster** in the last 12 months and **venous thromboembolism** (deep vein thrombosis or pulmonary
  embolism) at any time. RA-JAK checks both as ``mixed`` criteria: the codes settle a coded case, the notes the rest;
* a person: the response to a conventional DMARD and anti-HBc with HBV DNA (``human_truth``; anti-HBc is planted
  as a lab result so the page has something to show).

The Generator calls :func:`rajak_patient` only when the site's mix holds ``rajak`` (``Generator(mix="mix_tw_ra")``),
so the default sites and the committed fixtures do not change. Notes are in Traditional Chinese or English.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from tools.synth.catalog import BIOLOGICS, JAK_INHIBITORS

if TYPE_CHECKING:
    from tools.synth.generator import Generator

TRIAL = "RA-JAK"
RHEU_DOCTORS = ("P12345", "P23456")  # P12345 is the trial's investigator in the demo (tools.cgmh_demo)
EGFR_CUT = 40.0
EGFR_MARGIN = 3.0  # planted eGFR stays this far from the cut (integer vs decimal age)

# criterion id -> (planted attribute, state -> what the coded data answers): True / False / None (unknown)
STRUCTURED: dict[str, tuple[str, dict[str, bool | None]]] = {
    "RA-JAK-INC-01": ("age_band", {"in": True, "young": False, "old": False}),
    "RA-JAK-INC-02": ("ra_dx", {"long": True, "recent": False}),
    "RA-JAK-INC-03": ("mtx", {"long": True, "short": False, "none": False}),
    "RA-JAK-INC-04": (
        "das28",
        {"high": True, "moderate": True, "low": False, "missing_component": None, "none": None},
    ),
    "RA-JAK-EXC-01": ("prior", {"biologic": True, "jak": True, "none": False}),
    "RA-JAK-EXC-02": ("hbsag", {"pos": True, "neg": False, "missing": None}),
    "RA-JAK-EXC-04": (
        "tb",
        {"igra_pos_untreated": True, "igra_pos_treated": False, "igra_neg": False, "none": None},
    ),
    "RA-JAK-EXC-05": ("infection", {"recent": True, "old": False, "none": False}),
    # the two planted states: the coded half of a mixed criterion (the notes decide the rest)
    "RA-JAK-EXC-06": (
        "zoster",
        {"coded_recent": True, "coded_old": False, "note_recent": False, "negated": False, "none": False},
    ),
    "RA-JAK-EXC-07": (
        "vte",
        {"coded_dvt": True, "coded_pe": True, "note_only": False, "negated": False, "none": False},
    ),
    "RA-JAK-EXC-08": ("malignancy", {"recent": True, "old": False, "none": False}),
    "RA-JAK-EXC-09": ("hf", {"yes": True, "no": False}),
    "RA-JAK-EXC-10": ("pregnancy", {"dx": True, "no": False, "na": False}),
    "RA-JAK-EXC-11": ("creatinine", {"normal": False, "low": True, "missing": None}),
}
# what a careful reader of the notes answers for the two mixed criteria: yes / no / unknown
NOTES: dict[str, tuple[str, dict[str, str]]] = {
    "RA-JAK-EXC-06": (
        "zoster",
        {"coded_recent": "yes", "coded_old": "no", "note_recent": "yes", "negated": "no", "none": "unknown"},
    ),
    "RA-JAK-EXC-07": (
        "vte",
        {"coded_dvt": "yes", "coded_pe": "yes", "note_only": "yes", "negated": "no", "none": "unknown"},
    ),
}
HUMAN = {"RA-JAK-INC-05": "csdmard_response", "RA-JAK-EXC-03": "ahbc"}
KINDS = {c: ("inclusion" if "-INC-" in c else "exclusion") for c in [*STRUCTURED, *HUMAN]}

# finding sentences (fictional), per note language; dates are passed in already written
SENTENCES: dict[str, dict[str, str]] = {
    "zh-TW": {
        "zoster": "{d}右側胸壁出現帶狀皰疹，給予 valacyclovir 治療七日後結痂癒合。",
        "zoster_old": "{d}曾患帶狀皰疹，已痊癒，之後未再復發。",
        "zoster_no": "病人否認曾罹患帶狀皰疹。",
        "dvt": "{d}因左下肢腫痛經超音波診斷為深部靜脈栓塞，接受抗凝血治療六個月。",
        "pe": "{d}因呼吸喘經電腦斷層確診肺栓塞，已完成抗凝血治療。",
        "vte_note": "過去病史：{d}曾發生深部靜脈栓塞，於外院治療。",
        "vte_no": "病人無深部靜脈栓塞或肺栓塞病史。",
    },
    "en": {
        "zoster": "Herpes zoster of the right chest wall on {d}, treated with valacyclovir for seven days; healed.",
        "zoster_old": "Past herpes zoster on {d}, resolved without recurrence.",
        "zoster_no": "The patient denies any history of herpes zoster.",
        "dvt": "Left leg deep vein thrombosis confirmed by ultrasound on {d}; anticoagulated for six months.",
        "pe": "Pulmonary embolism confirmed by CT on {d}; anticoagulation completed.",
        "vte_note": "Past history: deep vein thrombosis on {d}, treated at another hospital.",
        "vte_no": "No history of deep vein thrombosis or pulmonary embolism.",
    },
}


def _rate(attribute: str) -> dict[str, float]:
    from tools.synth.generator import rate

    return rate("rajak", attribute)


def _say(g: Generator, key: str, d: date | None = None) -> str:
    if g.L.code not in SENTENCES:
        raise ValueError("the rajak archetype writes Traditional Chinese or English notes only (a Taiwanese site)")
    text = SENTENCES[g.L.code][key]
    out = text.format(d=g.L.fmt_date(d)) if d is not None else text
    return out if g.L.code != "en" else out + " "


def _find(text: str, criterion: str, value: str) -> Any:
    from tools.synth.generator import Find

    return Find(text, criterion, value)


def rajak_patient(g: Generator, i: int) -> None:
    from tools.synth.generator import egfr_ckd_epi_2021

    st = g.state
    sex = "F" if g.rng.random() < 0.75 else "M"
    band = g.pick(_rate("age_band"))
    age = {"in": g.rng.randint(25, 72), "young": g.rng.randint(15, 16), "old": g.rng.randint(78, 86)}[band]
    mrn = g.patient(i, sex, age)
    st(mrn, "archetype", "rajak")
    st(mrn, "age_band", band)
    doctor = g.rng.choice(RHEU_DOCTORS)
    # the RA diagnosis: long-standing, or made in the last five months (INC-02: at least six months)
    dx_state = st(mrn, "ra_dx", g.pick(_rate("ra_dx")))
    first = g.days_ago(250, 3000) if dx_state == "long" else g.days_ago(20, 140)
    g.dx(mrn, g.rng.choice(["ra_seropos", "ra_other"]), first, "RHEU", g.encounter(mrn, first, "RHEU", doctor))
    for d in sorted(g.days_ago(10, 330) for _ in range(g.rng.randint(1, 3))):
        if d > first:
            g.dx(mrn, "ra_other", d, "RHEU", g.encounter(mrn, d, "RHEU", doctor))
    # methotrexate: a long course (at least three months, refills without gaps) or a short one
    mtx = st(mrn, "mtx", g.pick(_rate("mtx")))
    if mtx == "long":
        g.rx_course(mrn, "methotrexate", g.days_ago(200, 330), g.rng.randint(200, 400), 0, "RHEU")
    elif mtx == "short":
        g.rx_course(mrn, "methotrexate", g.days_ago(70, 200), g.rng.randint(28, 56), 0, "RHEU")
    if g.rng.random() < 0.4:
        g.rx_course(mrn, g.rng.choice(["hydroxychloroquine", "sulfasalazine"]), g.days_ago(100, 400), 120, 0, "RHEU")
    # DAS28 from one visit in the last 90 days (a missing component leaves the score unknown)
    das = st(mrn, "das28", g.pick(_rate("das28")))
    g.das28_assessment(mrn, das, g.days_ago(3, 80), g.rng.random() < 0.5)
    # prior biologic or JAK inhibitor (ever)
    prior = st(mrn, "prior", g.pick(_rate("prior")))
    if prior != "none":
        drug = g.rng.choice(BIOLOGICS if prior == "biologic" else JAK_INHIBITORS)
        g.rx_course(mrn, drug, g.days_ago(400, 1500), g.rng.randint(90, 300), 0, "RHEU")
    _screening_labs(g, mrn)
    _infection_and_history(g, mrn, sex, age)
    _zoster(g, mrn, doctor, st(mrn, "zoster", g.pick(_rate("zoster"))))
    _vte(g, mrn, doctor, st(mrn, "vte", g.pick(_rate("vte"))))
    _creatinine(g, mrn, sex, egfr_ckd_epi_2021, st(mrn, "creatinine", g.pick(_rate("creatinine"))))
    # a person: the response to a conventional DMARD (INC-05) and HBV DNA for an anti-HBc positive patient (EXC-03)
    resp = st(mrn, "csdmard_response", g.pick(_rate("csdmard_response")))
    human = g.data.human_truth.setdefault(mrn, {})
    human["RA-JAK-INC-05"] = resp
    human["RA-JAK-EXC-03"] = g.data.states[mrn]["ahbc"]
    truth = g.data.note_truth.setdefault(mrn, {})
    for crit, (attr, answers) in NOTES.items():
        truth[crit] = answers[g.data.states[mrn][attr]]
    appt = st(mrn, "appointment", g.pick(_rate("appointment")))
    if appt != "none":
        ahead = g.rng.randint(0, 13) if appt == "soon" else g.rng.randint(14, 120)
        weekday = (g.ref + timedelta(days=ahead)).weekday()
        if weekday >= 5:  # the clinic runs on weekdays: a weekend booking moves to the Monday
            ahead += 7 - weekday
        g.appointment(mrn, ahead, "RHEU", doctor)


def _screening_labs(g: Generator, mrn: str) -> None:
    st = g.state
    hbsag = st(mrn, "hbsag", g.pick(_rate("hbsag")))
    if hbsag != "missing":
        g.lab(mrn, "HBSAG", "POS" if hbsag == "pos" else "NEG", g.days_ago(20, 300))
    ahbc = st(mrn, "ahbc", g.pick(_rate("ahbc")))
    if ahbc != "missing":
        g.lab(mrn, "AHBC", "POS" if ahbc == "pos" else "NEG", g.days_ago(20, 300))
    tb = st(mrn, "tb", g.pick(_rate("tb")))
    if tb.startswith("igra_pos"):
        g.lab(mrn, "IGRA", "POS", g.days_ago(20, 300))
        if tb == "igra_pos_treated":
            g.rx_course(mrn, "isoniazid", g.days_ago(15, 120), 270, 0, "FM")
    elif tb == "igra_neg":
        g.lab(mrn, "IGRA", "NEG", g.days_ago(20, 300))


def _infection_and_history(g: Generator, mrn: str, sex: str, age: int) -> None:
    st = g.state
    inf = st(mrn, "infection", g.pick(_rate("infection")))
    if inf != "none":
        d = g.days_ago(3, 25) if inf == "recent" else g.days_ago(60, 400)
        g.dx(mrn, g.rng.choice(["sepsis", "pneumonia"]), d, "FM")
    mal = st(mrn, "malignancy", g.pick(_rate("malignancy")))
    if mal == "recent":
        g.dx(mrn, g.rng.choice(["breast_ca", "colon_ca", "lung_ca"]), g.days_ago(60, 1500), "ONC")
    elif mal == "old":
        g.dx(mrn, g.rng.choice(["breast_ca", "colon_ca"]), g.days_ago(1950, 3000), "ONC")
    if st(mrn, "hf", g.pick(_rate("hf"))) == "yes":
        g.dx(mrn, "hf", g.days_ago(60, 2000), "CARD")
    # drawn only for women of 18 to 45 (no state otherwise: ``expected`` reads it as "na")
    if sex == "F" and 18 <= age <= 45 and st(mrn, "pregnancy", g.pick(_rate("pregnancy"))) == "dx":
        g.dx(mrn, "pregnancy", g.days_ago(10, 200), "FM")


def _rheu_note(g: Generator, mrn: str, d: date, doctor: str, body: list[Any]) -> None:
    """A rheumatology progress note with the finding sentence among the usual filler (written by the visit's doctor
    at the visit's encounter)."""
    enc = g.encounter(mrn, d, "RHEU", doctor)
    parts: list[Any] = [g.L.filler(g.rng, g.rng.randint(2, 5)), *body, g.L.filler(g.rng, g.rng.randint(2, 5))]
    note_no = g.nid("n")
    g.t["note"].append(
        {
            "note_no": note_no,
            "mrn": mrn,
            "enc_no": enc,
            "note_datetime": g.dt(d),
            "note_type": "progress",
            "text": g.assemble(note_no, mrn, d, parts),
        }
    )


def _zoster(g: Generator, mrn: str, doctor: str, state: str) -> None:
    crit = "RA-JAK-EXC-06"
    if state in ("coded_recent", "note_recent"):
        d = g.days_ago(30, 300)
        if state == "coded_recent":
            g.dx(mrn, g.rng.choice(["zoster", "zoster", "zoster_eye"]), d, "FM")
            g.rx(mrn, "valacyclovir", d, d + timedelta(days=6), "FM")
        _rheu_note(g, mrn, d, doctor, [_find(_say(g, "zoster", d), crit, "yes")])
    elif state == "coded_old":
        d = g.days_ago(430, 1500)
        g.dx(mrn, "zoster", d, "FM")
        _rheu_note(g, mrn, g.days_ago(30, 300), doctor, [_find(_say(g, "zoster_old", d), crit, "no")])
    elif state == "negated":
        _rheu_note(g, mrn, g.days_ago(10, 300), doctor, [_find(_say(g, "zoster_no"), crit, "no")])


def _vte(g: Generator, mrn: str, doctor: str, state: str) -> None:
    crit = "RA-JAK-EXC-07"
    if state in ("coded_dvt", "coded_pe"):
        d = g.days_ago(200, 3000)
        g.dx(mrn, "dvt" if state == "coded_dvt" else "pe", d, "CARD")
        g.rx_course(mrn, "rivaroxaban", d, 180, 0, "CARD")
        key = "dvt" if state == "coded_dvt" else "pe"
        _rheu_note(g, mrn, g.days_ago(10, 300), doctor, [_find(_say(g, key, d), crit, "yes")])
    elif state == "note_only":  # treated at another hospital: in the notes, never coded here
        d = g.days_ago(400, 3000)
        _rheu_note(g, mrn, g.days_ago(10, 300), doctor, [_find(_say(g, "vte_note", d), crit, "yes")])
    elif state == "negated":
        _rheu_note(g, mrn, g.days_ago(10, 300), doctor, [_find(_say(g, "vte_no"), crit, "no")])


def _creatinine(g: Generator, mrn: str, sex: str, egfr: Any, state: str) -> None:
    if state == "missing":
        return
    age = int(g.age_of(mrn))
    female = sex == "F"
    scr = 1.0
    for _ in range(500):
        scr = round(g.rng.uniform(0.5, 1.3) if state == "normal" else g.rng.uniform(1.8, 4.5), 2)
        e = egfr(scr, age, female)
        if (state == "normal" and e >= EGFR_CUT + EGFR_MARGIN) or (state == "low" and e <= EGFR_CUT - EGFR_MARGIN):
            break
    g.lab(mrn, "CRE", scr, g.days_ago(5, 300))


# ------------------------------------------------------------------------------------------------ the gold
def expected(states: dict[str, str]) -> dict[str, bool | str | None]:
    """What each RA-JAK criterion should answer for one ``rajak`` patient, from the planted states: the coded answer
    under the criterion id, the notes' answer of a mixed criterion under ``<id>/notes``, a person's under the id."""
    out: dict[str, bool | str | None] = {}
    for crit, (attr, answers) in STRUCTURED.items():
        out[crit] = answers[states.get(attr, "na")]
    # D-442: no eGFR under 18 (an adult equation): a patient of the young band (15-16) has no eGFR, unknown
    if states.get("age_band") == "young":
        out["RA-JAK-EXC-11"] = None
    for crit, (attr, note_answers) in NOTES.items():
        out[crit + "/notes"] = note_answers[states[attr]]
    for crit, attr in HUMAN.items():
        out[crit] = states[attr]
    return out


def coded_candidate(states: dict[str, str]) -> bool:
    """SPEC §8.2 on the gold: every coded inclusion true or unknown, no coded exclusion true (a mixed exclusion
    present in the codes rules the patient out, D-98)."""
    exp = expected(states)
    for crit in STRUCTURED:
        v = exp[crit]
        if KINDS[crit] == "inclusion" and v is False:
            return False
        if KINDS[crit] == "exclusion" and v is True:
            return False
    return True
