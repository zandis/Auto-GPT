# Attribution: JMED-LLM datasets (CC BY 4.0)

**Files:** `mrner_disease.csv`, `mrner_medicine.csv` and `CRNER.csv` (JMED-LLM's `datasets/all/CRNER.csv`), unchanged, in this folder.

**Work:** JMED-LLM, Japanese Medical Evaluation Dataset for Large Language Models, Social Computing Laboratory
(Sociocom), Nara Institute of Science and Technology (NAIST). Source: https://github.com/sociocom/JMED-LLM
(`datasets/mrner_disease.csv`, `datasets/mrner_medicine.csv`, `datasets/all/CRNER.csv`).

**Original data:** NTCIR-16 Real-MedNLP test collection, MedTxt-CR (case reports) and MedTxt-RR (radiology reports),
Sociocom NAIST.

**Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/.
JMED-LLM's README gives the first two datasets CC-BY-4.0 by name (`README.md` here, verbatim); CRNER is the same task over the whole corpus, committed on the owner's ruling of 2026-11-23 (academic development may use the CC BY 4.0 data directly). Nothing licensed
NC or NC-SA (NRNER, JCSTS, PseudoNursingRecords) and none of JMED-LLM's other files is in this repository.

**Changes:** none to the files. The tool `tools/public_site.py` reads each question's quoted report, joins its
sentences, and uses the text as a patient's note; it derives age, sex and diagnoses from the text by fixed rules, as
`PROVENANCE.md` of a built site says. No answer column of the datasets is used.

**Pins:** `SHA256SUMS`, and `JMED_PINS` in `tools/public_site.py` (the loader refuses a file that is not the pinned
one). Register row: `jmed-llm-mrner` in `docs/licences/register.csv`.

**What this does not cover:** the Real-MedNLP XML (the eval, the gate and the `public-medtxt` scenario read it, for the
negative and suspicious tags); it is not committed.
