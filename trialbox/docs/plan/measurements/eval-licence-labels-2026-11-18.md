# Licence labels of the criterion-annotation set: card H-37, 2026-11-18

Lane H, card H-37, on lane J's point in root review 20 (`docs/reviews/2026-11-root/20-gold-data-open-sources.md`,
finding 1 and card 20-2): `eval/criterion_ml/README.md` and `eval/DATASETS.yaml` call the SIGIR notes and their
translations "public domain", while the SIGIR 2016 collection is CC BY-SA 4.0. Worked on master `a4aa0be1`.

## Verdict

**Lane J is right about the notes.** The set has four parts, and only the criterion labels are public domain:

| Part | Files | Licence | Source (read 2026-11-18) |
| --- | --- | --- | --- |
| 53 patient notes (SIGIR 2016 topics) | `notes_en.json` | CC BY-SA 4.0; "All Rights (including copyright) CSIRO, U.S. National Institute of Standards, U.S. National Institutes of Health 2016"; creators Koopman B., Zuccon G.; publisher CSIRO | https://researchdata.edu.au/a-test-collection-clinical-trials/664508 |
| zh-TW, ja, mixed translations | `notes_zh-TW.json`, `notes_ja.json`, `notes_mixed.json` | CC BY-SA 4.0 (adaptations of the notes, made for TrialBox in Oct 2026) | as above; https://creativecommons.org/licenses/by-sa/4.0/ |
| Physician criterion labels, evidence ids, GPT-4 labels, `training` flag | `annotations.jsonl` | U.S. Government work, NCBI public domain notice | https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations (card: `license: other`, `license_name: public-domain`, `license_link: LICENSE`; LICENSE is the NCBI notice, the same text as `LICENSE.NCBI`); https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/LICENSE (same notice) |
| Trial titles and criterion text | `annotations.jsonl` (`trial_title`, `criterion_text`) | ClinicalTrials.gov terms and conditions; the eligibility text is the sponsors' | https://clinicaltrials.gov/about-site/terms-conditions (register row `ctgov-public-protocols`, checked 2026-11-13; not re-read here) |

NCBI's release puts its public domain notice over a file that also holds the SIGIR notes (`note` field). NCBI can
release its own labels into the public domain; it cannot do that for text CSIRO publishes under CC BY-SA 4.0. The
labels in this repository now follow the original publisher for the notes.

## What was labelled before, and what changed

The licence register and `NOTICE` were already right: register row `pubacc-sigir-2016` (CC BY-SA 4.0, "data adapted
from the SIGIR notes (eval/criterion_ml translations) shares alike") and row `pubacc-trialgpt-criterion` ("the notes
inside are SIGIR's (CC BY-SA 4.0, CSIRO)"), `NOTICE` lines 238-246 and 282-283, and `tools/public_accuracy/sources.py`
(SIGIR sources, `CC-BY-SA-4.0`). No register row changed.

| Place | Said | Says now |
| --- | --- | --- |
| `eval/criterion_ml/README.md`, Provenance and licence | the whole set "a United States Government Work in the public domain" | a table of the four parts, each with its licence and source; points to `NOTICE.md` |
| `eval/criterion_ml/NOTICE.md` | (none; the folder held only `LICENSE.NCBI`) | new: attribution, copyright notice as published, licence and legal-code links, the changes made (sentence lists; machine translations, not clinician-verified), which files are offered under CC BY-SA 4.0 |
| `eval/DATASETS.yaml` `criterion_ml` | "NCBI TrialGPT data (public domain notice in LICENSE.NCBI); translations by TrialBox" | each part with its licence and the CSIRO source |
| `eval/DATASETS.yaml` `judge_public`, `phi_second_opinion`, `public_site`, `open_cohorts`, `public_accuracy_key`, `match_registry` | SIGIR notes "public domain" (or no word on the notes) | SIGIR notes CC BY-SA 4.0 (CSIRO) |
| `docs/data/06-open-and-public-data.md` row 1 of the table | "US government work, public domain" | CC BY-SA 4.0 for the notes; public domain for the labels |

Test added: `tests/unit/test_sigir_notes_licence.py` (every DATASETS.yaml entry naming the SIGIR notes says
CC BY-SA 4.0; the `criterion_ml` entry names each part and the CSIRO source; the folder carries `NOTICE.md` with the
attribution). `tests/unit/test_chia_licence_one.py`, the other test reading the file, is unchanged and green.

## What CC BY-SA 4.0 requires of this repository, and whether it meets it

The repository is public, so it shares the notes and the translations (licence §2(a)(1)).

| Requirement (CC BY-SA 4.0 legal code) | Met today? |
| --- | --- |
| §3(a)(1)(A): name the creators, keep the copyright notice, the licence notice and the warranty disclaimer | yes, after this card: `eval/criterion_ml/NOTICE.md` and `NOTICE` section 4 |
| §3(a)(1)(B): say that the material was changed | yes, after this card: `NOTICE.md` states the sentence split and the machine translation |
| §3(a)(1)(C): name the licence with its URI | yes (`NOTICE.md`, `NOTICE`, README) |
| §3(b)(1): adapted material (the three translations) under CC BY-SA 4.0 or a BY-SA compatible licence | labelled so now, as the register already said; see question 1 |
| §3(b)(2): give the adapter's licence with the adapted material | yes, after this card (`NOTICE.md` in the same folder) |
| §3(b)(3): add no terms or technical measures that restrict the adapted material | open: `pyproject.toml` declares the `trialbox/` package "Proprietary" (CONTRIBUTING.md "Licence"); if the notes ever ship inside a package or image under that declaration, the files must still carry CC BY-SA 4.0. Today they are evaluation data in the repository, not a product file (not verified for every image build) |

Share-alike binds the notes and their adaptations, not code that reads them or scores computed on them (the review's
own reading, lane J finding 1; not a legal opinion).

## Other sets in DATASETS.yaml (listed, not chased)

- `trec_ct`, `ad`, `open_cohorts`: "TREC Clinical Trials ... topics and qrels (NIST)" with no word on terms; the register
  row `pubacc-trec-ct` says NIST states no terms, status `permission-to-ask`. The entries do not say so. Not changed.
- `medtxt`, `chia`, `mimic_iv_fhir_demo`: labels match their cited sources as the register states; not re-read.
- No other inconsistency was seen.

## Not verified

- The CC BY-SA page was read through a summarising fetch; the licence name, the "All Rights" line, creators and
  publisher are quoted from it. The CSIRO Data Access Portal's own record was not opened.
- Who wrote the SIGIR topics: topic id `sigir-20141` has the form of a TREC Clinical Decision Support 2014 topic,
  and that track's page (https://www.trec-cds.org/2014.html, read 2026-11-18) says the topics are "medical case
  narratives created by expert topic developers", names no author and states no terms. Whether the original
  narratives were written by U.S. Government employees (whose work has no U.S. copyright for a licence to bind) was
  not established.
- Who the physician annotators were (employees or contractors) was not established; the NCBI notice is taken as
  stated.
- No dataset was downloaded; the committed files were only grepped (no SIGIR note text appears outside
  `eval/criterion_ml/notes_en.json`).

## For the owner to decide

- question: The three translations are labelled CC BY-SA 4.0, as the register already said on 2026-11-14. Keep them in
  the public repository under that licence, or remove them? (Keeping them is allowed; it means anyone may reuse
  them under CC BY-SA 4.0.)
- question: If the SIGIR topics are U.S. Government works (TREC CDS), the CC BY-SA claim may not reach the note text.
  The labels follow the publisher's stated licence until a person checks; is that the line you want?
- question: Must the eval data stay out of any image or package declared "Proprietary" (§3(b)(3) above)?
