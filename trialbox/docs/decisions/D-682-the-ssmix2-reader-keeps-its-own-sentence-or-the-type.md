# D-682 The SS-MIX2 reader keeps its own sentence or an error's type; the rest of the adapter's kept texts, judged

- **Task:** the integrator's order of 2026-11-13, from lane C2's across-services test (#505, D-700) and what lane
  B2's #516 (D-669) lists as not changed
- **PR:** this branch (`agent/ADP-error-text-kept`), cut from #516's head
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-700 (a general error's text is used only in listed places), D-669 (a line of the night's
  validation messages never holds the validator's sentence), D-681 (an OMOP refusal names no record), D-588 (the
  share report's two nets), STD-020 (a file no codec reads is quarantined)

## Context

D-700's test lists, for the adapter's folders of this lane, `adapter/mapping/sharereport.py` and
`adapter/sources/ssmix2/source.py`. #516 lists three things it left: `ValidationResult.per_file`, the night's
`omop.error`, and a line with a code in it in `tests/unit/test_japan_completeness.py`.

## Decision

1. **A quarantined SS-MIX2 file's reason is the reader's own sentence or the error's type.** The reader's own
   class (`hl7.Undecodable`) keeps its sentence: which reading failed. Any other error (a file that cannot be
   opened, a text that is not HL7) is kept as `not an HL7 message: <type>`: an OS error's text holds the whole
   path. The two are caught apart, so the place is off D-700's list.
2. **The reader's sentence quotes MSH-18 only when it names character sets** (HL7 table 0211 and the names vendors
   write). A damaged message has anything in that place: the sentence then says `MSH-18 names no character set of
   HL7 table 0211`.
3. **A lookup that failed in the extended ISO-2022-JP reader is not quoted** (its text is the bytes looked up):
   `ISO-2022-JP: a character outside the code tables`. A codec's own reason is one of its fixed phrases and is kept.

## Judged and kept

- **The share report's refusal reason** (`sharereport.map_rows`): the text of the mapping's `ValueError` goes
  through `scrub_reason`, which keeps the leading words that the engine's own source writes and stops at the
  first that is not one (D-588); any other error is counted by its type. It stays on D-700's list as: *the
  mapping's refusal, reduced to the engine's own words*.
- **`ValidationResult.per_file`** keeps the validator's sentences, and they do quote values (seen by one run of
  the validator, below). Inside the adapter nothing reads them. TW-PAS (`orchestrator/scenarios/twpas.py`) puts
  them on the row of the patient whose bundle it is and into the bundle report, published as `phi`: beside that
  patient's own data, for the steward who must correct the bundle and cannot without the sentence. Kept; where
  `precheck.issues` travels after that is the orchestrator lane's to hold.
- **`omop.error`** (`adapter.dual_write`) keeps an `OmopError`'s text: since D-681 no refusal of the store is
  built from a record's id or a row's value. Held by a test that reads every `raise OmopError` of `services/omop`.
- **`tests/unit/test_japan_completeness.py:96`** (`code 'TOOLONG' is not a MEDIS ... code`): not the validator's;
  it is `adapter/licensed.py`'s list of skipped rows when an operator loads a licensed master file. The code is
  a cell of a vocabulary release, read by the person who holds that file; no patient's record is involved. Kept.

## One run of the HL7 validator (the real jar, synthetic resources, R4 core only)

- The night's lines (#516's `_issue_line`) held no value: `r00000-Patient.json Patient.gender: code-invalid
  (Terminology_TX_NoValid_16)`, `... Patient.birthDate: invalid (Type_Specific_Checks_DT_Date_Valid)`.
- The validator's sentences (`per_file`) quote what they refuse: the wrong gender code, the wrong date and the
  wrong decimal each appeared in quotes.
- **For lane B2 (not changed here):** three of six lines had `?` for the element, because the validator writes
  `Observation.value[x].value` and `Observation.value.ofType(Quantity)`, shapes `_PLACE` does not take. No value
  can pass by it; the line only says less than it could.

## Evidence

`tests/unit/test_adapter_kept_reasons.py` (six cases failed before the change); `tests/unit/test_ssmix2_hardening.py`
unchanged and green.
