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

## Card 10H-1 (2026-11-19): decisions for the owner

Card 10H-1 (plan 10, Track H; review 20 item 20-2) finished what H-37 began. It corrected the remaining labels,
added register rows for MedTxt, JMED-DICT mini, MANBYO and the MIMIC-IV FHIR demo, and added the build check: every
text file that names the SIGIR notes, or holds their text, passes `python -m tools.licence_register --check`. Its
pull request carries the inventory and the sources read. The readings below are **the project's reading, for the
owner to confirm, not legal advice**. Nothing was removed, moved or re-licensed: each item is yours to decide.

1. **The demo image and the bundle rows (first).** The SIGIR notes and this project's ja, zh-TW and mixed
   translations of them are CC BY-SA 4.0.
   - Where they ship today: `demo/Dockerfile` copies all of `trialbox/` minus `.dockerignore`. So
     `eval/criterion_ml` and `docs/plan/measurements/back-translation-check-2026-11-18/*.json` are in the demo
     image. `TB_DEMO_TOOL=public_e2e` serves the notes as a public-data site.
   - The product image (`deploy/docker/python.Dockerfile`) copies only `eval/qualification/*` and
     `eval/injection`, which hold none of this text.
   - Spec v4 appendix rows (`spec/v4/19_positioning_plan_appendices.md`) said "Bundle: Yes" for both. They now say
     "Owner decides".
   - Not done: excluding the two folders from the demo image with `.dockerignore`. It would break
     `TB_DEMO_TOOL=public_e2e`, which reads `eval/criterion_ml/notes_en.json`.
   - The demo NOTICE now says what the image carries.
   - Shipping is allowed by the licence if the files keep the licence, the attribution and the change note, and
     nothing restricts them further. Decide: keep them in the demo image, exclude them (and drop or change
     `public_e2e`), or keep them only in the repository.
2. **Which licence covers `trialbox/`.**
   - The repository root `LICENSE` is MIT, inherited from the repository's origin.
   - `trialbox/pyproject.toml` declares "Proprietary", and CONTRIBUTING.md says no licence is named yet.
   - The CC BY-SA files cannot be under "Proprietary" or under MIT: CC BY-SA §3(b)(3) forbids adding restrictions,
     and the files must keep CC BY-SA 4.0.
   - Name the licence of `trialbox/`, and state that `eval/criterion_ml` and its copies keep CC BY-SA 4.0 whatever
     it is.
3. **MedTxt: reports withdrawn for licensing.**
   - The publisher's page now offers 100 MedTxt-CR reports "due to licensing issues"; the zip `tools/medtxt_eval.py`
     used held 148.
   - Row `medtxt` is now `permission-to-ask`, not `cleared`.
   - Ask NAIST (card 20-3) which reports the CC BY 4.0 release covers. Until the answer, do not publish
     per-report results from the other 48.
4. **`eval/bakeoff`**: results (scores, predictions, evidence sentence ids) on the SIGIR notes. It had no
   DATASETS entry or licence statement, and has both now.
   - Reading: scores and ids are not the notes' text, so publishing them with the citation is allowed.
   - Decide whether the bake-off results are published.
5. **A threshold fitted on these notes** (`services/matching/cascade/s2b_semantic.py:9`: the LTT fit of the S2b
   threshold on `eval/criterion_ml`).
   - Reading: a number fitted on the data (a threshold, a weight, a calibration) is not the notes' text or an
     adaptation of it. Share-alike does not bind it; the product may ship it under any licence.
   - Text built from the notes does stay CC BY-SA 4.0: prompts, few-shot examples, the translations, rewritten
     notes.
   - Confirm, or ask counsel.
6. **MANBYO** (`permission-to-ask`): its page grants only "feel free to use it" and sends commercial users to
   JMED-DICT mini.
   - Send the NAIST request (card 20-3).
   - Until then, use it for evaluation only, never ship it, and use JMED-DICT mini.
7. **JMED-DICT mini**: the dictionary is CC BY 4.0, but its link columns follow each resource's terms (SNOMED CT
   IPS, WHO ICD-10, MEDIS standard disease names, JLAC10, HOT).
   - Ship only its own columns, or wait for each linked resource's clearance? Its disease normalised forms are MEDIS
     names (D-173).
8. **Records that still call MANBYO "CC BY 4.0"**: `docs/DECISIONS.md` D-175 item 2 and root review 06. They are
   records and were not edited. A superseding note may be wanted.
9. **Who wrote the SIGIR topics** (H-37's open question): if they are U.S. Government works (TREC CDS 2014/15),
   CSIRO's licence may not reach their text. The labels follow the publisher until a person checks.

### Found on the way (not changed by this card)

- `catalogue/scores/recist_response.yaml:36` and `libs/tb_common/score_defs.json:1401` say RECIST 1.1 is "free to
  use", in a shipped file, with no licence named or source cited.
- KPS, mRS and Child-Pugh are called "public domain" second-hand in `catalogue/items.csv` and `score_defs.json`
  ("'Public Domain'" from the CDISC QRS table; "public domain per CDISC QRS table"): the CDISC table, not the scales'
  publishers, is the source.
- `docs/licences/register.csv` will need a merge with pull request #1093 (new column `athena_never`; the four new rows will be one field short when it lands, and the two edited rows will conflict textually).
