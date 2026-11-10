"""English clinical note templates for the synthetic hospital (fictional content, TB-DS-21 §5.1).

Mirrors ``notes.py`` (zh-TW) slot by slot. Every sentence ends with a space so sentences can be joined directly.
"""

from __future__ import annotations

FILLER = [
    "Vital signs stable, alert and oriented. ",
    "Sleeping well, appetite preserved. ",
    "Heart sounds regular, no murmur; chest clear bilaterally. ",
    "Advised to keep taking the medication and attend follow-up. ",
    "Results explained to the patient and family. ",
    "Abdomen soft, non-tender, bowel sounds normal. ",
    "No leg oedema, peripheral pulses palpable. ",
    "Low-purine diet advised; reduce sugary drinks. ",
    "Continue current prescription, review in three months. ",
    "No fever, chills or weight loss. ",
    "Recommended at least 150 minutes of exercise per week. ",
    "Home blood pressure log reviewed, broadly stable. ",
    "Mostly adherent over the last three months with occasional missed doses; dosing times re-explained. ",
    "Occasional post-prandial epigastric discomfort, no melaena or haematemesis; take tablets after food. ",
    "No cervical lymphadenopathy, thyroid not palpable, no crackles on auscultation. ",
    "Results similar to the previous visit; dose to be adjusted if needed. ",
    "Diet discussed: less red meat, offal and seafood, at least two litres of water a day. ",
    "Exercise advice given: walking or swimming rather than high-impact sport. ",
    "Social history: married, lives with spouse, never smoker, occasional alcohol (recently reduced). ",
    "Family history: mother with hypertension and diabetes, father with hyperlipidaemia. ",
]

JOINTS = ["right first MTP joint", "left first MTP joint", "right ankle", "left knee", "right wrist"]


def flare_sentence(date_text: str, joint: str) -> str:
    return f"On {date_text} the {joint} became red, hot, swollen and painful; acute gout flare, settled on colchicine. "


def no_flare_sentence() -> str:
    return "No gout flares in the past year; no red or swollen joints. "


def single_flare_sentence(date_text: str) -> str:
    return f"Only one gout flare in the past year, on {date_text}, with no recurrence since. "


def current_flare_sentence() -> str:
    return "Currently an acute red, swollen, painful right first MTP joint: acute gout flare in progress. "


def no_current_flare_sentence() -> str:
    return "No acute gout flare at present; joints without redness or tenderness. "


def ra_assessment_sentence(tjc: int, sjc: int, ptga: int) -> str:
    return (
        f"Swollen tender PIP joints of both hands: tender joint count {tjc}, swollen {sjc}, patient global {ptga}/100. "
    )


def response_sentence(delta: float, good: bool) -> str:
    if good:
        return f"DAS28 fell by {delta:.1f} from baseline: good response, continue the biologic. "
    return f"DAS28 fell by only {delta:.1f} from baseline: inadequate response, consider switching. "


def injection_willing_sentence(willing: bool) -> str:
    if willing:
        return "Happy to self-inject subcutaneously once a week. "
    return "Afraid of needles and does not want to self-inject. "


ECOG_SENTENCE = "ECOG performance status 1, independent in daily activities. "
CXR_CLEAR = "Both lung fields clear, no sign of active tuberculosis."
LUNG_MASS = "3.2 cm mass in the right upper lobe, suspicious for primary lung cancer; no distant metastasis seen."

NEEDLES: list[tuple[str, str]] = [
    ("First severe ankle pain began while on holiday in Cornwall", "holiday Cornwall ankle pain"),
    ("Father had a tophus surgically removed", "father tophus surgery"),
    ("Drinks three cans of sweetened iced tea every day", "sweetened iced tea three cans"),
    ("Works night shifts as a taxi driver", "night shift taxi driver"),
    ("Had rhabdomyolysis after a marathon", "marathon rhabdomyolysis"),
    ("Rash after sulfonamide antibiotics in the past", "sulfonamide rash"),
]


# ------------------------------------------------------------------------------------------------ Alzheimer's (T-503)
# Memory-clinic notes and reports of the ``ad`` archetype in English (the share of English notes at a Japanese site).
AD_FILLER = [
    "Family report more forgetfulness about dates and appointments; the patient has little insight. ",
    "Neurological examination: cranial nerves intact, no weakness or sensory loss, gait steady. ",
    "Independent in basic activities; family help with money and medicines. ",
    "No low mood or visual hallucinations; sleeping well. ",
    "Conversation and responses much as at the last visit. ",
    "Family note that the same stories are repeated more often. ",
    "Vitamin B12, folate and thyroid function normal. ",
    "Advised to keep active and socially engaged. ",
    "Has stopped driving after discussion with the family. ",
    "Cognitive testing to be repeated at the next visit. ",
]


def mmse_sentence(date_text: str, mmse: int, hdsr: int | None) -> str:
    if hdsr is None:
        return f"Cognitive testing on {date_text}: MMSE {mmse}/30. "
    return f"Cognitive testing on {date_text}: MMSE {mmse}/30, HDS-R {hdsr}/30. "


def hdsr_only_sentence(date_text: str, hdsr: int) -> str:
    return f"HDS-R {hdsr}/30 on {date_text}; MMSE not done today. "


def cdr_sentence(cdr: str) -> str:
    return f"Clinical Dementia Rating (CDR) global score {cdr}. "


def amyloid_pet_report(date_text: str, positive: bool) -> str:
    if positive:
        return f"Amyloid PET {date_text}: diffuse cortical amyloid uptake, visual read positive. "
    return f"Amyloid PET {date_text}: no cortical amyloid uptake, visual read negative. "


def csf_report(date_text: str) -> str:
    return f"CSF {date_text}: low Abeta42/40 ratio and raised p-tau181, consistent with amyloid pathology (positive). "


def amyloid_not_done_sentence() -> str:
    return "No amyloid PET or CSF testing has been done. "


def mri_report(date_text: str, microbleeds: int, siderosis: bool) -> str:
    head = f"MRI brain {date_text}: mild bilateral hippocampal atrophy. "
    mb = f"{microbleeds} cerebral microbleeds on T2* imaging. " if microbleeds else "No cerebral microbleeds on T2*. "
    ss = "Superficial siderosis over the left parietal lobe. " if siderosis else "No superficial siderosis. "
    return head + mb + ss


def partner_sentence(has_partner: bool) -> str:
    if has_partner:
        return "Lives with a daughter, who comes to every visit. "
    return "Lives alone with no family nearby and always attends alone. "
