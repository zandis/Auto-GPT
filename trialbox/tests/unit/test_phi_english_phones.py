"""NEW-B-43 (D-744): an English phone number is PHI in every door of the guard.

NEW-B-42's review (D-743): on an English site with planted PHI, the 555-01xx phones in the notes were masked in 0 of
357 spans by the note masker (what the lake applies before the full-text index and the embeddings), not found by
``scan`` (the gate before any call leaves the box) and not found by the guard service's recognisers; every planted
Taiwanese and Japanese phone was. The three doors knew Taiwanese and Japanese forms only. Synthetic numbers only: the
555-01xx range and the UK drama ranges are kept for fiction."""

from __future__ import annotations

import pytest
from guard.guard import Guard
from tb_common import phi_guard
from tb_common.phi_guard import MASK_CHAR, NOTE_MASK_VERSION, mask_note, note_spans, scan

G = Guard("^\\d{8}$")

# (note text, the phone in it)
PHONES = [
    ("Contact 555-0133. Gout flare settled.", "555-0133"),  # the synthetic hospital's English sentence (D-743)
    ("Tel: (555) 010-0133, after 5 pm.", "(555) 010-0133"),
    ("Phone 555-010-0133 for results.", "555-010-0133"),
    ("Daughter asks us to call +1 555 010 0199 tomorrow.", "+1 555 010 0199"),
    ("Mobile: 555.010.0150", "555.010.0150"),
    ("Wife's number is 555-0101.", "555-0101"),
    ("Fax 555-010-0177 to the GP.", "555-010-0177"),
    ("Next of kin on +44 20 7946 0958 (London).", "+44 20 7946 0958"),
    ("Mobile 07700 900123, prefers texts.", "07700 900123"),
    ("tel. 01632 960999", "01632 960999"),  # the range kept for drama
    # review: forms a clinician writes that the first version missed
    ("Phone no: 555-0133 (mother).", "555-0133"),
    ("Tel. no. 555-0142", "555-0142"),
    ("Contact details: 555-0150.", "555-0150"),
    ("Mobile 07700900123, prefers texts.", "07700900123"),
    ("Home (01632) 960 123 after six.", "(01632) 960 123"),
    ("Mob: 07700-900123", "07700-900123"),
    ("Tel: 555\u2013010\u20130133", "555\u2013010\u20130133"),
    ("Call 5550100133 to rebook.", "5550100133"),
    ("Ph 555 0133", "555 0133"),
    ("Tel 5550133", "5550133"),
    ("Pager 555-0177", "555-0177"),
    ("T: 555-0188", "555-0188"),
    ("Dial 001 555 010 0133 from abroad.", "001 555 010 0133"),
    ("Helpline 1-800-555-0199.", "1-800-555-0199"),
    ("Tel 555-0133-ext 4", "555-0133"),
]

# clinical text an English note holds: none of it is a phone number
CLINICAL = [
    "BP 120/80 mmHg, HR 72. Allopurinol 100-300 mg daily; review on 2026-11-01.",
    "WBC 4.5-11.0, Hb 13.2, LDL 130-160 mg/dL, eGFR 60-89. HbA1c 7.2% (ICD-10 E11.9).",
    "Contact dermatitis on both hands. Call back in 2 weeks if worse; seen at 10:30-11:00.",
    "Target 1200-1500 kcal, walk 3-4 times a week. Serum urate 540-600 umol/L last year.",
    "NCT04157751 screening; visit 3 of 12. Creatinine 1.2 mg/dL on 2025-03-04, 2025-06-10.",
    "Phoned about the results. Contact the rheumatology clinic for the next dose.",
    "HbA1c NGSP JLAC10 3D046 0000 019 (a lab code, spaced as the design documents write it).",
    # review: false positives of the first version
    "HbA1c JLAC10 3D046 0000 019 062 02; creatinine 3C015 0000 023 271 01.",
    "3D046\t0000\t023\t271\t01",
    "Protocol number: 202-1234. Site number 840-0001. Lot number: 234-5678. Kit number 123.4567.",
    "Insulin at %s; obs at %s." % (" ".join(["0800", "1200", "1800"]), " ".join(["0600", "1400", "2200"])),  # noqa: UP031
    "Stamp 251103 1430. Dose cohorts 250 500 1000 mg; N = 300 600 1200.",
    "Titre +100000; change +12 345 678 cells.",
    "Scores 0.0031023784901758012 and 0.007998569807607214; p 0.025 100 1000.",
    "Encounter/0020305175026d62da8d342 (a resource id).",
]


@pytest.mark.parametrize(("text", "phone"), PHONES, ids=[p for _, p in PHONES])
def test_the_note_masker_masks_an_english_phone(text: str, phone: str) -> None:
    out = mask_note(text)
    start = text.index(phone)
    assert len(out) == len(text)
    assert all(out[i] == MASK_CHAR or text[i].isspace() for i in range(start, start + len(phone))), out
    assert [k for k, s, e in note_spans(text) if s <= start < e] == ["phone"]
    assert out[:start].rstrip(" :.(") == text[:start].rstrip(" :.(")  # the label is kept


@pytest.mark.parametrize(("text", "phone"), PHONES, ids=[p for _, p in PHONES])
def test_the_gate_before_a_call_finds_an_english_phone(text: str, phone: str) -> None:
    got = scan(text)
    assert got.hit and got.clearance is None
    assert "phone" in {kind for kind, _ in got.findings}, got.findings


@pytest.mark.parametrize(("text", "phone"), PHONES, ids=[p for _, p in PHONES])
def test_the_guard_service_redacts_an_english_phone(text: str, phone: str) -> None:
    assert "PHONE" in {f.kind for f in G.detect(text)}, G.detect(text)
    assert phone not in G.redact(text)


@pytest.mark.parametrize("text", CLINICAL)
def test_english_clinical_text_is_left_alone(text: str) -> None:
    assert note_spans(text) == [], note_spans(text)
    assert not scan(text).hit, scan(text).findings
    assert [f for f in G.detect(text) if f.kind == "PHONE"] == []


def test_numbers_on_separate_lines_are_not_one_phone() -> None:
    """The gate scans a prompt's variables one per line (``variables_text``): three numbers are not a phone."""
    from tb_common.phi_guard import variables_text

    assert not scan(variables_text({"a": 250, "b": 300, "c": 1000})).hit


@pytest.mark.parametrize(("text", "phone"), PHONES[:3], ids=[p for _, p in PHONES[:3]])
def test_the_guard_service_redacts_the_number_and_keeps_its_word(text: str, phone: str) -> None:
    red = G.redact(text)
    label = text[: text.index(phone)].strip(" :.(")
    assert phone not in red and label in red, red


def test_the_masks_version_says_the_masking_changed() -> None:
    """Chunks masked by the old recognisers say so: the vector index and the lake re-mask a note whose chunks carry
    another version (D-337)."""
    assert int(NOTE_MASK_VERSION) >= 2  # 2: this card; D-745 (3) changes the masking again


def test_one_english_phone_form_serves_every_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard service reads the v1 guard's form at each call, not a copy: replacing it changes what is found."""
    import re

    assert phi_guard.EN_PHONE in [rx for _kind, rx in phi_guard._NOTE_PATTERNS]
    monkeypatch.setattr(phi_guard, "EN_PHONE", re.compile(r"(?P<v>zz-phone-zz)"))
    assert "PHONE" in {f.kind for f in Guard("^\\d{8}$").detect("call zz-phone-zz")}
