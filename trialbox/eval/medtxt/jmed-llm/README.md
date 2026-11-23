# JMED-LLM datasets used by the public-data walk

These two files are copied unchanged from JMED-LLM (https://github.com/sociocom/JMED-LLM, `datasets/`): `mrner_disease.csv`
(100 rows: 50 case reports and 50 radiology reports) and `mrner_medicine.csv` (100 rows from case reports; 75 distinct
reports, 25 of them also in the first file). Together they hold the 100 case reports and the 50 radiology reports that
`tools/public_site.py` reads (`medtxt_docs`). SHA-256 pins: `SHA256SUMS` here and `JMED_PINS` in `tools/public_site.py`.

Below, verbatim from JMED-LLM's README of the copy the owner shared: the table row of each dataset used, and its
License section. See `ATTRIBUTION.md`.

## Table of JMED-LLM's README (the rows of the two datasets used)

|Task|Dataset|License|Original Resouce|
|---|---|---|---|
|固有表現抽出|**MRNER-disease**|CC-BY-4.0|NTCIR-16 Real-MedNLP MedTxt-CR Corpus, MedTxt-RR Corpus|
||**MRNER-medicine**|CC-BY-4.0|NTCIR-16 Real-MedNLP MedTxt-CR Corpus|

(Named entity extraction heads the group; the second row continues it, as in the original.)

## License
The license for each dataset follows the terms of the original dataset's license. All other components are licensed under a <a rel="license" href="https://creativecommons.org/licenses/by/4.0/">Creative Commons Attribution 4.0 International License</a>.

<a rel="license" href="http://creativecommons.org/licenses/by/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by/4.0/88x31.png" /></a><br />
