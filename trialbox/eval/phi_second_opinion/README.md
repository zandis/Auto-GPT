# A second opinion on the note masker (D-1037)

`tools/phi_second_opinion.py` runs Presidio (MIT) beside `tb_common.phi_guard` (note masking version 5) offline. Presidio is a measurement tool here, never a dependency of the box. The run uses Presidio's English recognisers (spaCy `en_core_web_lg`) and four of the tool's own for Taiwan charts: a Han name (spaCy `zh_core_web_sm`), the national ID's shape, a Taiwan phone and a Taiwan address. It also adds a labelled chart number. `results.json` holds the counts and the shape of every span the two disagree on, never its value. Every set is synthetic or public.

A planted identifier is *found* when the flagged spans cover all its characters.

## Planted identifiers found in full (phi_guard / Presidio)

| Category | `tw-en` (60 English Taiwan charts, generated) | `phi_synth-en` (40 English notes) |
| --- | --- | --- |
| Name, Latin script | **0 / 152** of 167 (76 partial, 91 missed) | **33 / 97** of 117 |
| Name, Han script | 73 / 82 of 149 | — |
| National ID | 60 / 60 of 60 | 40 / 36 of 43 |
| Chart number (labelled) | 60 / 60 of 60 | (in ID) |
| Phone | 60 / 60 of 60 | 39 / 40 of 40 |
| Address | **34 / 60** of 60 (26 partial) | 38 / 0 of 40 (40 partial) |
| Date of birth | 60 / 29 of 60 | 40 / 40 of 40 |
| E-mail | — | 38 / 37 of 38 |

The public SIGIR notes have no identifier in them (53 English and 53 code-mixed). On them phi_guard flagged nothing, and Presidio flagged 240 spans.

## Differences, judged

| Difference | Judged | Why |
| --- | --- | --- |
| Latin-script names phi_guard misses or cuts short | **real miss** | It masks a Latin name only after a title (`Mr`, `Dr`, ...), `Patient:` or a role word, and only as capitalised words. So `Chang Mei` is masked and `-Ling` leaks; `CHEN, MEI-LING`, `Linda Ellison-Ward` and a relative's name after `son` or `daughter,` are missed. |
| Han names after an English label or word (`Name: 黃家豪`, `son 曾冠宇`) | **real miss** | The Han name rules take a Chinese or Japanese label or role word. |
| English-form Taiwan addresses (`13F., No. 322, Minsheng Rd., Da'an Dist., Taipei City`) | **real miss** | Only `13F.` is masked. |
| A British phone with a five-digit area code after `reachable at` | **real miss** (one) | — |
| `MRN 48-releases-7731` (3) | not a miss | An odd value in the generated set. |
| Han names before `醫師`; ROC and 民國 dates of birth; Western street addresses; IDs with letters and dashes; beds | Presidio's misses | phi_guard's own rules hold. |
| Dates of care, ages, durations (`3 days`, `92-year-old`, `11/02/2024`) | not PHI here | The note masker keeps the dates of care by design; a date of birth is masked. |
| Abbreviations, departments, drugs and eponyms (`HTN`, `OPD`, `Foley`, `Cushing`, `Augmentin`, `Neurology`) flagged by Presidio | false | — |
| Chinese phrases as names in the code-mixed notes (`病人將簽署`) | false | Presidio's Chinese model on narrative text. |
| `Cardiology` (3) and `Pulmonology` (1) masked by phi_guard | false (over-masking) | Over-masking costs a word, not a leak. |
| A bare surname (`Huang family`) flagged by Presidio | real but minor | Not planted; the masker does not mask a surname alone. |

The real misses are fixed in a masking card with its adversarial review (lane B2).

## After the fix: note masking version 6 (NEW-B-55, D-923)

`results.json` is now the run against version 6 (each set names its `note_mask_version`). Planted identifiers found in full by phi_guard:

| Category | `tw-en` (version 5 → 6) | `phi_synth-en` (version 5 → 6) |
| --- | --- | --- |
| Name, Latin script | 0 → **167** of 167 | 33 → **97** of 117 |
| Name, Han script | 73 → **149** of 149 | — |
| Address | 34 → **60** of 60 | 38 → 38 of 40 |

The 20 Latin names of `phi_synth-en` still counted partial are labelled with their title (`Dr. Samuel Okafor`). The masker masks the name and keeps the title, as before; Presidio does the same.

On the 106 public notes, phi_guard still flags nothing, and no decoy of either labelled set is newly hit. The adversarial review's leaks, over-masking and timing cases are tests in `tests/unit/test_phi_english_taiwan_charts.py`.
