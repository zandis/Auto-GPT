"""Code catalog for the synthetic hospital (HIS-side codes). Codes marked SYN are synthetic placeholders.

ICD-10-CM and ATC codes are real classification codes. NHI drug and order codes follow the NHI format but are
synthetic (SYN) — a site replaces them through its terminology tables. LOINC codes marked ``verify`` should be
confirmed by the site's laboratory (see docs/DECISIONS.md D-24).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Drug:
    key: str
    nhi_code: str  # SYN
    atc: str
    name: str
    dose: float
    unit: str


DRUGS: dict[str, Drug] = {
    d.key: d
    for d in [
        Drug("allopurinol", "AC00001100", "M04AA01", "Allopurinol 100mg", 300, "mg"),
        Drug("febuxostat", "BC00002100", "M04AA03", "Febuxostat 80mg", 80, "mg"),
        Drug("benzbromarone", "AC00003100", "M04AB03", "Benzbromarone 50mg", 50, "mg"),
        Drug("colchicine", "AC00004100", "M04AC01", "Colchicine 0.5mg", 1, "mg"),
        Drug("semaglutide", "KC00005209", "A10BJ06", "Semaglutide 1mg/pen", 1, "mg"),
        Drug("liraglutide", "KC00006209", "A10BJ02", "Liraglutide 18mg/3mL", 1.2, "mg"),
        Drug("dulaglutide", "KC00007209", "A10BJ05", "Dulaglutide 1.5mg", 1.5, "mg"),
        Drug("tirzepatide", "KC00008209", "A10BX16", "Tirzepatide 5mg", 5, "mg"),
        Drug("metformin", "AC00009100", "A10BA02", "Metformin 500mg", 1000, "mg"),
        Drug("amlodipine", "AC00010100", "C08CA01", "Amlodipine 5mg", 5, "mg"),
        Drug("atorvastatin", "AC00011100", "C10AA05", "Atorvastatin 20mg", 20, "mg"),
        Drug("methotrexate", "AC00012100", "L04AX03", "Methotrexate 2.5mg", 15, "mg/wk"),
        Drug("hydroxychloroquine", "AC00013100", "P01BA02", "Hydroxychloroquine 200mg", 400, "mg"),
        Drug("sulfasalazine", "AC00014100", "A07EC01", "Sulfasalazine 500mg", 2000, "mg"),
        Drug("leflunomide", "BC00015100", "L04AA13", "Leflunomide 20mg", 20, "mg"),
        Drug("prednisolone", "AC00016100", "H02AB06", "Prednisolone 5mg", 5, "mg"),
        Drug("adalimumab", "KC00017248", "L04AB04", "Adalimumab 40mg/0.4mL", 40, "mg/2wk"),
        Drug("etanercept", "KC00018248", "L04AB01", "Etanercept 50mg", 50, "mg/wk"),
        Drug("tocilizumab", "KC00019248", "L04AC07", "Tocilizumab 162mg", 162, "mg/wk"),
        Drug("isoniazid", "AC00020100", "J04AC01", "Isoniazid 300mg", 300, "mg"),
        Drug("rifapentine", "AC00021100", "J04AB05", "Rifapentine 150mg", 900, "mg/wk"),
        Drug("entecavir", "BC00022100", "J05AF10", "Entecavir 0.5mg", 0.5, "mg"),
        Drug("tenofovir", "BC00023100", "J05AF07", "Tenofovir DF 300mg", 300, "mg"),
        Drug("osimertinib", "KC00024238", "L01EB04", "Osimertinib 80mg", 80, "mg"),
    ]
}

BIOLOGICS = ("adalimumab", "etanercept", "tocilizumab")

# ICD-10-CM (NHI edition) codes used by the generator: key -> (code, display)
DX: dict[str, tuple[str, str]] = {
    "gout": ("M10.9", "Gout, unspecified"),
    "gout_foot": ("M10.071", "Idiopathic gout, right ankle and foot"),
    "gout_chronic": ("M1A.9XX0", "Chronic gout, unspecified, without tophus"),
    "ra_seropos": ("M05.79", "Rheumatoid arthritis with rheumatoid factor of multiple sites"),
    "ra_other": ("M06.9", "Rheumatoid arthritis, unspecified"),
    "t1dm": ("E10.9", "Type 1 diabetes mellitus without complications"),
    "t2dm": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "obesity": ("E66.9", "Obesity, unspecified"),
    "htn": ("I10", "Essential (primary) hypertension"),
    "hld": ("E78.5", "Hyperlipidemia, unspecified"),
    "ckd3": ("N18.30", "Chronic kidney disease, stage 3 unspecified"),
    "pancreatitis_acute": ("K85.90", "Acute pancreatitis without necrosis or infection, unspecified"),
    "pancreatitis_chronic": ("K86.1", "Other chronic pancreatitis"),
    "mtc": ("C73", "Malignant neoplasm of thyroid gland"),
    "men2": ("E31.22", "Multiple endocrine neoplasia [MEN] type IIA"),
    "breast_ca": ("C50.911", "Malignant neoplasm of unspecified site of right female breast"),
    "colon_ca": ("C18.9", "Malignant neoplasm of colon, unspecified"),
    "lung_ca": ("C34.90", "Malignant neoplasm of unspecified part of unspecified bronchus or lung"),
    "skin_bcc": ("C44.91", "Basal cell carcinoma of skin, unspecified"),
    "pregnancy": ("Z33.1", "Pregnant state, incidental"),
    "ami": ("I21.9", "Acute myocardial infarction, unspecified"),
    "stroke": ("I63.9", "Cerebral infarction, unspecified"),
    "tb_pulm": ("A15.0", "Tuberculosis of lung"),
    "latent_tb": ("R76.11", "Nonspecific reaction to tuberculin skin test without active tuberculosis"),
    "hbv_chronic": ("B18.1", "Chronic viral hepatitis B without delta-agent"),
    "sepsis": ("A41.9", "Sepsis, unspecified organism"),
    "pneumonia": ("J18.9", "Pneumonia, unspecified organism"),
    "hf": ("I50.9", "Heart failure, unspecified"),
    "oa_knee": ("M17.11", "Unilateral primary osteoarthritis, right knee"),
    "lbp": ("M54.50", "Low back pain, unspecified"),
    "gerd": ("K21.9", "Gastro-esophageal reflux disease without esophagitis"),
    "osteoporosis": ("M81.0", "Age-related osteoporosis without current pathological fracture"),
    "nsclc_egfr": ("C34.11", "Malignant neoplasm of upper lobe, right bronchus or lung"),
}

# HIS local lab codes (mapped to LOINC by mapping/tw_core/lab_local_to_loinc.csv)
LABS: dict[str, tuple[str, str]] = {
    "UA": ("Uric acid", "mg/dL"),
    "CRE": ("Creatinine", "mg/dL"),
    "HBA1C": ("HbA1c", "%"),
    "ALT": ("ALT (GPT)", "U/L"),
    "ESR": ("ESR", "mm/hr"),
    "CRP": ("CRP", "mg/dL"),  # HIS reports mg/dL; canonical UCUM mg/L (factor 10)
    "HBSAG": ("HBsAg", ""),
    "AHBC": ("Anti-HBc", ""),
    "IGRA": ("QuantiFERON-TB", ""),
    "HCGU": ("Urine hCG", ""),
    "TJC28": ("Tender joint count (28)", "{count}"),
    "SJC28": ("Swollen joint count (28)", "{count}"),
    "PTGA": ("Patient global assessment VAS", "mm"),
    "EGFRT": ("EGFR mutation", ""),
}

PROCS: dict[str, tuple[str, str]] = {
    "bariatric_sleeve": ("75614B", "Laparoscopic sleeve gastrectomy (SYN)"),
    "bariatric_bypass": ("75613B", "Laparoscopic gastric bypass (SYN)"),
    "cxr": ("32001C", "Chest X-ray PA view"),
    "knee_inj": ("39014C", "Intra-articular injection (SYN)"),
}

REPORT_EXAMS: dict[str, tuple[str, str]] = {"CXR": ("RAD-CXR", "Chest X-ray PA")}

DEPTS = ("RHEU", "META", "NEPH", "CARD", "FM", "ONC", "ORTH")
PRACTITIONERS: list[tuple[str, str, str]] = [
    ("P12345", "示範醫師甲", "RHEU"),
    ("P23456", "示範醫師乙", "RHEU"),
    ("P34567", "示範醫師丙", "META"),
    ("P45678", "示範醫師丁", "NEPH"),
    ("P56789", "示範醫師戊", "CARD"),
    ("P67890", "示範醫師己", "FM"),
    ("P78901", "示範醫師庚", "ONC"),
    ("P89012", "示範醫師辛", "ORTH"),
]

# ------------------------------------------------------------------------------------------------ Alzheimer's (T-503)
# Codes of the ``ad`` archetype (scenario J1: early Alzheimer's disease trial AD-MAB, registry NEUR-COH). Kept apart
# from the tables above so the default site draws, and the committed fixtures, do not change. ICD-10-CM codes as the
# rest of the catalog (the compiler's value sets use ICD-10-CM); a Japanese site maps its 標準病名 / ICD-10 (WHO) codes
# through its terminology tables. Drug codes follow the same synthetic NHI-format scheme; ATC codes are real.
AD_DRUGS: dict[str, Drug] = {
    d.key: d
    for d in [
        Drug("warfarin", "AC00090100", "B01AA03", "Warfarin 1mg", 3, "mg"),
        Drug("apixaban", "BC00091100", "B01AF02", "Apixaban 5mg", 10, "mg"),
        Drug("rivaroxaban", "BC00092100", "B01AF01", "Rivaroxaban 15mg", 15, "mg"),
        Drug("edoxaban", "BC00093100", "B01AF03", "Edoxaban 30mg", 30, "mg"),
        Drug("dabigatran", "BC00094100", "B01AE07", "Dabigatran 110mg", 220, "mg"),
        Drug("aspirin", "AC00095100", "B01AC06", "Aspirin 100mg", 100, "mg"),
        Drug("donepezil", "AC00096100", "N06DA02", "Donepezil 5mg", 5, "mg"),
        Drug("memantine", "BC00097100", "N06DX01", "Memantine 20mg", 20, "mg"),
    ]
}
ANTICOAGULANTS = ("warfarin", "apixaban", "rivaroxaban", "edoxaban", "dabigatran")

AD_DX: dict[str, tuple[str, str]] = {
    "mci": ("G31.84", "Mild cognitive impairment of uncertain or unknown etiology"),
    "ad_late": ("G30.1", "Alzheimer's disease with late onset"),
    "ad_unspecified": ("G30.9", "Alzheimer's disease, unspecified"),
    "memory_complaint": ("R41.3", "Other amnesia"),
    "tia": ("G45.9", "Transient cerebral ischemic attack, unspecified"),
    "stroke": ("I63.9", "Cerebral infarction, unspecified"),
    "af": ("I48.91", "Unspecified atrial fibrillation"),
    "dvt": ("I82.409", "Acute embolism and thrombosis of unspecified deep veins of unspecified lower extremity"),
    "htn": ("I10", "Essential (primary) hypertension"),
    "hld": ("E78.5", "Hyperlipidemia, unspecified"),
    "t2dm": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "ckd3": ("N18.30", "Chronic kidney disease, stage 3 unspecified"),
}

# report exams of the ``ad`` archetype: local exam code -> (name, modality text used in the report header)
AD_REPORT_EXAMS: dict[str, tuple[str, str]] = {
    "MRI-BRAIN": ("MRI brain", "頭部MRI"),
    "PET-AMY": ("Amyloid PET", "アミロイドPET"),
    "CSF-AB": ("CSF amyloid beta 42/40", "脳脊髄液検査"),
}

# the memory clinic: neurology (脳神経内科) and psychiatry (もの忘れ外来). Names are drawn from names_ja on a JP site.
AD_DEPTS = ("NEUR", "PSY")
AD_PRACTITIONERS: list[tuple[str, str, str]] = [
    ("P90001", "合成医師A", "NEUR"),
    ("P90002", "合成医師B", "NEUR"),
    ("P90003", "合成医師C", "PSY"),
]

# ------------------------------------------------------------------------------------------- RA-JAK trial (T-504)
# Codes of the ``rajak`` archetype (scenario T2: the synthetic RA JAK-inhibitor trial RA-JAK at the Taiwanese site).
# Kept apart from the tables above, as the Alzheimer's codes, so the default site draws and the committed fixtures do
# not change. JAK inhibitors carry their real ATC codes (L04AF); the NHI-format drug codes are synthetic.
RAJAK_DRUGS: dict[str, Drug] = {
    d.key: d
    for d in [
        Drug("tofacitinib", "BC00101100", "L04AF01", "Tofacitinib 5mg", 10, "mg"),
        Drug("baricitinib", "BC00102100", "L04AF02", "Baricitinib 4mg", 4, "mg"),
        Drug("upadacitinib", "BC00103100", "L04AF03", "Upadacitinib 15mg", 15, "mg"),
        Drug("valacyclovir", "AC00104100", "J05AB11", "Valacyclovir 500mg", 3000, "mg"),
    ]
}
JAK_INHIBITORS = ("tofacitinib", "baricitinib", "upadacitinib")
RAJAK_DX: dict[str, tuple[str, str]] = {
    "zoster": ("B02.9", "Zoster without complications"),
    "zoster_eye": ("B02.39", "Other herpes zoster eye disease"),
    "dvt": ("I82.409", "Acute embolism and thrombosis of unspecified deep veins of unspecified lower extremity"),
    "pe": ("I26.99", "Other pulmonary embolism without acute cor pulmonale"),
}
