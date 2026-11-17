# The field: open projects, products and competitors against TrialBox, part by part (lane J, job B-3, 2026-11-17)

**Reader:** the owner first (the one-page summary), then the builders (one section per part), then plan 9 (the
component table in section 9).

**What this page answers.** The owner asked: which open components or products are better than ours, for serving,
language processing, the data pipeline, structured data and notes ("not all by LLM but a mixture"), seeding,
database management, flexibility, the vector database; and said that data connectors must be complete, with SS-MIX2
a must. This page answers the system analysis of job B-1 (branch `agent/B1-root-system`,
`docs/reviews/2026-11-root/01-system.md` on that branch, called **B-1** below), whose fix table names where TrialBox
is weak. It updates, and does not repeat, the literature and competitor review of 2026-10-17
(`docs/research/2026-10_literature_competitors.md`, called **LIT** below) and the build-versus-reuse review of
2026-11-12 (`docs/reviews/2026-11-12-build-vs-reuse.md`, called **BVR**). Where those already settled a question
this page cites them and adds only what changed.

**How it was done.** Every open-source repository named in a table was opened on 2026-11-17 (rows that were not
say so): its repository metadata
(last push, latest release and date, stars, default branch) through the public `ungh.cc` mirror of GitHub's
metadata, its open-issue count through `api.deps.dev`, and its licence **from the LICENSE file itself** fetched raw
from the default branch [M 1]. READMEs and docs were read where a claim depends on them [M 2]; Python packages were
checked on PyPI [M 3]. The GitHub API itself was not reachable from this session, so the **issue trend** (as opposed
to today's count) and the last commit on the default branch (as opposed to the last push on any branch) are not
verified. Products and papers were opened through their own pages where marked [S]; where only a search summary was
read, the row says so and the item counts as not verified. No new dependency was added (only `make venv` from the lock), no model
downloaded, no hospital data read; nothing here cost money.

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[S]** | Source: a public link follows, opened today unless the row says "search summary only" |
| **[R]** | Read: a TrialBox file and line, or B-1, LIT or BVR by section |
| **[M n]** | Measured: row n of the measurement log (section 10) |
| **[O]** | Opinion: the analyst's judgement, to be argued with |
| **not verified** | Could not be checked here; section 11 lists each |

Licence and offline operation are first-class criteria: the box runs offline in a hospital and ships in a signed
bundle with a supply-chain allow-list [R `deploy/supply-chain-allowlist.yaml:1-12`]. **AGPL, SSPL, BUSL, FSL,
non-commercial or "research only" terms, and anything that phones home, are findings.**

---

## Summary (one page, plain words)

**The field has no product that does what TrialBox does on one offline box in Taiwan and Japan; it does have
better parts for four of TrialBox's weak spots: database drivers, code tables, the HL7 v2 edge and name detection
in Japanese and Chinese.** [O]

### Five things worth adopting

| # | What | Why it is better than what TrialBox has | Licence | Size | Measure first, on TrialBox's own data |
| --- | --- | --- | --- | --- | --- |
| A1 | **The vendors' own Python drivers**: `python-oracledb` in thin mode (no Oracle client to install) and Microsoft's `mssql-python` or `pyodbc` for SQL Server | The SQL reader cannot open the Oracle or SQL Server it says it reads (B-1 §1.1, M 18); these are the maintained drivers, released 2026-10-27 and 2026-11-17 [M 3] | UPL-1.0 or Apache-2.0; MIT; MIT-0 [M 1, M 3] | S | a CGRD-type view read through each driver in a container test (B1-D1) |
| A2 | **The public code systems, loaded at install**: the OHDSI Standardized Vocabularies (via Athena) for RxNorm, LOINC and ICD-10-CM; the NHI drug and order code files; the ATC index bought once | The compiler's tables hold 33 ATC, 27 LOINC and 24 NHI drug rows, so the large model was asked 676 times to pick a code (B-1 §1.5, M 5, M 6). The loader exists [R `services/omop/vocab_load.py:1-25`]; the content does not | varies per vocabulary: LOINC and RxNorm free with registration; SNOMED CT needs a membership or affiliate licence; ATC/DDD electronic index is sold (€200 on the order page) [S] | M | the share of concept names resolved by table before and after, on the sigir and P1b protocol sets (B1-M2) |
| A3 | **SMART Bulk Data reference server as a test fixture**, plus a small Python REST client (`fhir-py`) for `$export` kick-off and polling | The FHIR reader takes files only (B-1 §1.1, STD-013); US hospitals deliver through Bulk Data; the reference server is the yardstick every certified EHR is tested against | Apache-2.0; MIT [M 1] | M | one `$export` against the reference server, read end to end, counts filed |
| A4 | **Open Integration Engine** (the community fork of Mirth Connect 4.5.2) **at the site's edge**, documented as "the site's engine writes HL7 v2 messages to a folder"; only if a site refuses that, an MLLP listener inside the box built on `hl7apy` | Mirth Connect went closed-source from 4.6 [S]; the fork keeps MPL-2.0 and released v4.7.0 on 2026-10-21 [M 1]. TrialBox already parses HL7 v2.5 for SS-MIX2 [R `services/adapter/sources/ssmix2/hl7.py:1-60`], so a file drop needs no new parser | MPL-2.0; MIT [M 1] | S (docs and one feed) / M (listener) | one ADT and one ORU feed from the engine into the existing reader on the synthetic site |
| A5 | **A Japanese morphological analyser (SudachiPy with its dictionary) and a Chinese segmenter (jieba or HanLP) inside the one identifier detector** of B1-P1, with Presidio's recogniser structure as the model | B-1 measured three detectors catching 5, 13 and 14 of 18 probes; a katakana name and a full-width Taiwan ID passed (B-1 §7.1, M 15). Presidio has US, Korean, Indian and Singapore recognisers but **no Taiwan or Japan** ones [M 2]; a tokeniser knows where a name starts, a regex guesses (BVR already said "measure before writing more patterns") | Apache-2.0 (SudachiPy, sudachi.rs); MIT (jieba); Apache-2.0 (HanLP). **Not CKIP Transformers: GPL-3.0** [M 1] | S to M | the 18 B-1 probes plus a full-width and a katakana set; false positives on 1,000 synthetic notes |

### Five things worth learning from (not taking whole)

| # | What | The lesson |
| --- | --- | --- |
| L1 | **medspaCy's ConText and section rules** (MIT) | Negation, uncertainty, experiencer ("mother had ...") and section ("family history") are a rule tier in the field, before any model. TrialBox has negation words in the compiler [R `services/criteria_compiler/ir_extract/postprocess.py:404`] but none on note sentences before the judge reads them. medspaCy ships no Japanese or Chinese rules [M 2]: TrialBox would write them, using medspaCy's rule format. |
| L2 | **SQL on FHIR v2 ViewDefinitions** (HL7, implemented by Pathling and Google's FHIR Data Pipes) | A declarative FHIR-to-table view replaces a hand-written flattener; B-1 counted one new field touching five places (B-1 §2.4). The spec is at 3.0.0-ballot (2026-08-13) [M 1]; the engines are Spark/Java, too heavy to ship, but the view format is the lesson. |
| L3 | **OHDSI CIRCE, Capr and the new Python port Circepy** | The field's compile target for cohort logic over OMOP is CIRCE JSON (LIT §1.2 said so); a Python port now exists (v0.3.0, 2026-10-09, "under development") [M 1]. A third engine for the equivalence differential, not a run-time engine (BVR agreed). |
| L4 | **TrialMatchAI and TrialGPT** | Both local-capable, both open (MIT; US public domain) [M 1]. TrialMatchAI's hybrid lexical + dense retrieval and criterion-level reasoning, and TrialGPT's ranking, are the published designs to benchmark the cascade against on TREC Clinical Trials (already in `tools/trec_ct_eval.py`). |
| L5 | **llama.cpp** (MIT) as the CPU-only server for a GPU-less box | It serves quantised models on a CPU with grammar-constrained output (GBNF and JSON schema) [M 2]; vLLM also has an x86 CPU build [M 2]. Today a GPU-less box waits and stops on note criteria (B-1 §3.4); a CPU path for a small verifier is worth one timed run before it is designed. |

### What TrialBox already does better than the field

| Area | What TrialBox has | What the field has |
| --- | --- | --- |
| SS-MIX2 | A tested reader of standardised and extended storage, ten message types, five character-set variants, versioning by timestamp and deletion flags (B-1 §1.3) | **No open SS-MIX2 reader was found** on GitHub or in Japanese searches; published converters (Tohoku on InterSystems IRIS, an IBM facade server) are not open [S, search summaries; section 3.4] |
| Taiwan and Japan identifiers | Recognisers with check digits for the Taiwan ID, ARC and My Number [R `services/guard/recognisers.py:7-8`] | Presidio, the most used open detector, has none for Taiwan or Japan [M 2]; Philter is English [M 1] |
| Per-criterion evidence and recall | A quote checked by string match for each "met", and a recall certificate (LIT §4) | No open matcher reports either (LIT §2.6, unchanged today) [O] |
| Code-mixed synthetic hospital with gold | JA / zh-TW / EN notes, planted PHI, SS-MIX2 output, gold files [R `tools/synth_hospital/__init__.py:1-15`] | Synthea has a Japan configuration in `synthea-international` but no Taiwan one, and no notes in either language [M 2] |
| Offline validation | The HL7 validator runs with `-tx n/a -no-http-access` [R `services/adapter/validate/validator.py:242-244`] | The validator's default calls the public terminology server; many projects leave it on [O] |
| Signed EDC values | ODM 1.3.2 export of values a person confirmed and signed, with CDASH tags [R `services/edc/odm.py:1-5`; `services/edc/cdash.py:1-15`] | Open EDCs (OpenClinica 3, LibreClinica) capture data; none drafts from a hospital record with citations [O] |

**What the field does that TrialBox should not copy** [O]: a separate vector database (Qdrant, Milvus, Chroma,
LanceDB) at 5,000 to 50,000 patients; Snowstorm as the terminology server (it sits on Elasticsearch, whose licence
is AGPL / SSPL / Elastic) [M 1, M 2]; Liquibase for migrations (now under the Functional Source License) [M 1];
Ollama on the box (its cloud features are on until switched off) [M 2]; REDCap inside a commercial product (its
licence is for non-profits only) [S].

---

## 1. Trial matching and eligibility

TrialBox today [R]: the compiler turns protocol text into criterion logic with the large model, resolves concepts by
table, then by the model, and compiles SQL and CQL (B-1 §1.5 steps 6 to 10); the cascade screens with SQL (S0, S1),
a lexicon (S2), an embedder (S2b), a judge with verified quotes (S3) and a second model (S4) (steps 11 to 15). The
weak points are 43 % of criteria ending "a person decides" and pre-filters that filtered nothing in P2b (B-1 M 7,
M 8).

| Project | Link | Licence [M 1] | Activity [M 1] | What it does better or differently | Verdict |
| --- | --- | --- | --- | --- | --- |
| TrialGPT (NCBI) | https://github.com/ncbi-nlp/TrialGPT | US Government work, public domain (LICENSE) | release v1.0.0 2024-08-08; last push 2025-01-24; NCBI | Retrieval, criterion-level judgement and trial ranking with a cloud model; synthetic patients; the reference for "LLM matcher" (LIT §1.1). LIT's "licence unchecked" is now closed: public domain. TrialGPT 2.0 has no public repository under that organisation (`ncbi-nlp/TrialGPT-2` does not exist) [M 1] | **learn from** (ranking design; yardstick in `tools/trialgpt_compare.py`) |
| TrialMatchAI (Bordeaux) | https://github.com/cbib/TrialMatchAI | MIT (LICENSE; deps.dev says "non-standard") | v0.9.1 2026-09-19; push 2026-11-06; 2 open issues; university bioinformatics centre | Fully local: fine-tuned open models, hybrid lexical + dense retrieval, criterion-level reasoning, Phenopackets input; 92 % had a relevant trial in the top 20 (LIT §1.1) | **learn from**: run as a second matcher on the public sets [O] |
| MedCPT (NCBI) | https://github.com/ncbi/MedCPT | public domain (LICENSE) | no release; last push 2024-03-24 | Biomedical retriever and cross-encoder from PubMed click logs; LIT §0.7 proposed it as an ablation | **learn from** (one ablation against the pinned embedder; weights' own terms not verified) |
| Criteria2Query (OHDSI) | https://github.com/OHDSI/Criteria2Query | Apache-2.0 | no release; push 2026-03-01; README "[In Development]" | Free-text criteria to OMOP cohort JSON with rules + NER; C2Q 3.0 adds a model (LIT §1.2) | **learn from** (its error classes); not a run-time part |
| CIRCE (OHDSI) | https://github.com/OHDSI/circe-be | Apache-2.0 | v1.14.2 2026-10-01 | The cohort-definition JSON and its SQL compiler, the field's standard over OMOP | **learn from** (L3); a third engine for the differential |
| Circepy (OHDSI) | https://github.com/OHDSI/Circepy | Apache-2.0 | v0.3.0 2026-10-09; push today | Python port of CIRCE: the first way to compile CIRCE JSON without Java or R | **learn from**; revisit when it leaves "under development" [O] |
| Capr, CohortGenerator (OHDSI) | https://github.com/OHDSI/Capr ; https://github.com/OHDSI/CohortGenerator | Apache-2.0 (LICENSE.md; DESCRIPTION) | v3.0.0 2026-09-23; v1.1.1 2026-07-10 | Cohort definitions as code (R) and generation on any OMOP database | **ignore** for the box (R); use beside for parity runs |
| ATLAS (OHDSI) | https://github.com/OHDSI/Atlas | Apache-2.0 | v2.15.0 2025-07-25; push 2026-09-16; 259 open issues | Web cohort builder over OMOP: the clinician-facing query builder the field uses | **learn from** (its concept-set editor is the model for the code-review page) [O] |
| Leaf (UW) | https://github.com/uwrit/leaf | MPL-2.0 | v3.11.4 2024-11-06; push 2026-05-06 | Drag-and-drop cohort builder over any SQL warehouse; a site-side feasibility tool | **ignore** (TrialBox's feasibility funnel covers it; activity low) |
| MatchMiner API (Dana-Farber) | https://github.com/dfci/matchminer-api | not verified (no LICENSE at the root) | no release; last push 2023-12-05 | Genomic matching with Clinical Trial Markup Language | **ignore** (oncology genomics, dormant); MatchMiner-AI's repository not found [M 1] |
| TREC Clinical Trials 2021 to 2023 | https://pages.nist.gov/trec-browser/trec32/trials/overview | NIST track data terms (not read) | 2023 was the last year | Public topics and trial judgements; BM25 baselines rival LLM reranking (LIT §1.6) | **adopt as a benchmark** (already: `tools/trec_ct_eval.py`) |
| n2c2 2018 cohort selection | https://n2c2.dbmi.hms.harvard.edu (not opened today) | data use agreement (not verified) | static | 13 criteria on 288 longitudinal records; the standard criterion benchmark (LIT §0.8) | **learn from**; needs a signed agreement, so not in CI [O] |

**What the field does at each step that TrialBox does differently** [O]:

- **Criteria parsing**: every open system (Criteria2Query, AutoCriteria in LIT) still uses a model or NER to read
  criteria, then rules and a vocabulary to code them. None has TrialBox's "the model never writes SQL" plus an
  equivalence gate. The difference that matters is the vocabulary: Criteria2Query and ATLAS resolve against the full
  OHDSI vocabulary, TrialBox against tables of a few dozen rows. A2 closes that gap; nothing else in this section
  does more for accuracy.
- **Pre-filters**: the field's cheap first stage is BM25 or a dense retriever over trials (TREC, TrialGPT,
  TrialMatchAI). TrialBox's S2 lexicon and S2b threshold act on patients' notes per criterion, which is harder: in
  P2b they passed 788 of 788 pairs (B-1 M 7). The field offers no ready filter for this shape; B1-L2 (refit or drop
  S2b) stands.
- **Benchmarks for Traditional Chinese or Japanese eligibility**: none exists (LIT §1.5, unchanged today: no new
  one found) [O].

---

## 2. Clinical NLP and de-identification in English, Traditional Chinese and Japanese

### 2.1 The ladder: what the field uses at each rung, and where TrialBox stands

| Rung | What the field uses (open) | TrialBox today [R] | Gap [O] |
| --- | --- | --- | --- |
| **Rules** | regex and check digits for identifiers (Presidio, Philter); ConText for negation, uncertainty, experiencer, history; section detection (medspaCy); unit normalisation (UCUM) | identifier regexes with check digits (`services/guard/recognisers.py:7-8`); negation words in the compiler (`postprocess.py:404`) and in chart facts (`services/sitesetup/charts.py:182-188`); CJK bigram tokens (`services/lake/textproc.py:1-14`); UCUM units (B-1 M 17) | no ConText-style rule pass on note sentences before the judge; no section detection |
| **Terminology** | QuickUMLS and MedCAT (UMLS/SNOMED dictionaries), scispaCy linkers (UMLS), MANBYO / J-MeDic for Japanese disease names, OHDSI vocabulary for mapping | exact name, synonyms, a dictionary and the ICD-10-CM index (`criteria_compiler/terminology/mapper.py:1-20`); tables of 24 to 186 rows (B-1 M 5) | the tables are demo-sized; no Japanese disease dictionary on the note side |
| **Small model** | spaCy/stanza NER (English clinical models in stanza), GLiNER (zero-shot NER), MedNERN-CR-JA (Japanese case-report NER with ICD normalisation), BERT-family de-identification | the embedder ranks note sentences (S2b) (B-1 step 13); no small NER model | an NER pass for Japanese disease and drug names is available under CC BY 4.0 (MedNERN-CR-JA) [S] |
| **Large model** | criterion reading, note reading against a question, code choice among candidates | protocol reading (`ir_extract`), code choice (`concept_map`, 676 calls), judge and verifier (B-1 §1.5) | `concept_map` is a large-model call that a table should mostly make (A2) |

**The answer to "a mixture, not all LLM"** [O]: the field's working systems (cTAKES, MedCAT, medspaCy pipelines,
UTSW's production RAG in LIT §0.4) put rules and terminology first and keep the model for reading prose against a
question. TrialBox's design already has every rung (B-1 §1.5); what is missing is **content** on the two middle
rungs (code tables, a Japanese and Chinese name and negation lexicon), not more architecture.

### 2.2 Projects

| Project | Link | Licence [M 1] | Activity [M 1] | What it does better or differently | Verdict |
| --- | --- | --- | --- | --- | --- |
| medspaCy | https://github.com/medspacy/medspacy | MIT | 1.3.1 2024-11-21; push 2026-06-04; 40 open issues; academic (VA / Utah lineage) | ConText (negation, uncertainty, experiencer), sectionizer, QuickUMLS bridge on spaCy. **ConText and section rules for English (and partly French, Dutch) only; none for Japanese or Chinese** [M 2] | **learn from** (L1): copy the rule format, write ja/zh rules |
| negspaCy | https://github.com/jenojp/negspacy | MIT | v1.1.0 2026-04-20 | NegEx on spaCy entities | **ignore** (medspaCy's ConText is the superset) |
| Apache cTAKES | https://github.com/apache/ctakes | Apache-2.0 | ctakes-6.0.0 2024-09-16; push 2026-11-04; Apache Software Foundation | UIMA pipeline, UMLS dictionary lookup, negation, temporality; English | **ignore** (Java/UIMA, English, UMLS licence) |
| MedTagger (Mayo, OHNLP) | https://github.com/ohnlp/MedTagger | Apache-2.0 | v1.0.85 2025-05-05 | Rule-based concept and criteria extraction on UIMA | **ignore** (same reasons) |
| MedCAT (CogStack, now in cogstack-nlp) | https://github.com/CogStack/cogstack-nlp | Apache-2.0 | medcat/v2.10.1 2026-10-29; push today; the old `CogStack/MedCAT` repository last pushed 2025-07-25 | Dictionary + context-vector concept linking to SNOMED/UMLS with active learning; models need the terminology's licence | **learn from** (its supervised-review loop resembles the code-review page); not adopted: the value is the SNOMED/UMLS models [O] |
| QuickUMLS | https://github.com/Georgetown-IR-Lab/QuickUMLS | MIT | 1.4.0 2020-05-13; push 2024-08-12 | Fast approximate string matching to UMLS | **ignore** (dormant; UMLS licence) |
| scispaCy | https://github.com/allenai/scispacy | Apache-2.0 | v0.6.2 2025-10-01 | English biomedical spaCy models with UMLS/RxNorm linkers | **ignore** for notes (English, literature-trained) |
| Stanza | https://github.com/stanfordnlp/stanza | Apache-2.0 (LICENSE; deps.dev "non-standard") | v1.15.1 2026-11-14 | 60+ languages incl. Japanese and Chinese; English clinical NER packages (i2b2-style) [M 2] | **learn from** (English clinical NER only) |
| GLiNER | https://github.com/urchade/GLiNER | Apache-2.0 | v0.2.30 2026-11-02 | Zero-shot NER for any label set; a small-model rung between rules and the large model | **learn from**: one measured run on the synthetic notes' planted PHI before any adoption; the weights' terms are per model (not verified) |
| Presidio (Microsoft) | https://github.com/microsoft/presidio | MIT | 2.2.366 2026-10-27; push 2026-11-14; 263 open issues | Recogniser framework (pattern + context + checksum + NER), anonymiser; recognisers for US (SSN, ITIN), UK, Singapore, India, Korea, **none for Taiwan or Japan** [M 2] | **learn from** (A5's structure, and as the yardstick BVR named) |
| Philter (UCSF) | https://github.com/BCHSI/philter-ucsf | BSD-3-Clause | no release; push 2024-08-20 | Rule-based English clinical de-identification with high recall | **ignore** (English, dormant) |
| SudachiPy / sudachi.rs | https://github.com/WorksApplications/sudachi.rs | Apache-2.0 | v0.7.0 2026-09-24 (PyPI sudachipy 0.7.0 the same day) [M 3]; Works Applications | Japanese morphological analysis with a large dictionary; name and katakana segmentation | **adopt** (A5) |
| GiNZA | https://github.com/megagonlabs/ginza | MIT | v5.3.1 2026-11-12; Megagon Labs | spaCy pipeline for Japanese on Sudachi, with NER | **learn from** (heavier than Sudachi alone) |
| jieba | https://github.com/fxsjy/jieba | MIT | v0.42.1 2020-01-20; push 2024-08-21; 707 open issues | Chinese segmentation with a user dictionary | **adopt** for segmentation only (A5); dormant, so pin and vendor the dictionary [O] |
| HanLP | https://github.com/hankcs/HanLP | Apache-2.0 | v2.1.1 2025-01-13; push 2026-11-07 | Chinese segmentation, NER, Traditional/Simplified conversion | **learn from** (its 2.x models are heavy; jieba is enough for A5) |
| CKIP Transformers (Academia Sinica) | https://github.com/ckiplab/ckip-transformers | **GPL-3.0** | 0.3.4 2023-04-09 | The Traditional Chinese segmenter and NER of Taiwan's research community | **ignore**: GPL in a shipped bundle is a finding, and the project is dormant |
| OpenCC | https://github.com/BYVoid/OpenCC | Apache-2.0 (deps.dev; no root LICENSE fetched) | ver.1.4.2 2026-08-22 | Traditional/Simplified conversion with Taiwan phrasing | **learn from** (only if a site's notes mix Simplified; not seen yet) |
| MANBYO / J-MeDic (NAIST) | https://sociocom.naist.jp/manbyo-dic-en/ | **no licence stated**; the page says "feel free to use it" and points commercial users to "JMED-DICT mini" [S] | MANBYO_202106 (2021-06-02) | 7,683 disease concepts, 51,784 written forms, linked to ICD-10 | **learn from** until the licence is written; JMED-DICT mini's terms not verified |
| MedNERN-CR-JA (NAIST) | https://huggingface.co/sociocom/MedNERN-CR-JA | CC BY 4.0 (model card) [S] | 2023 revision | Japanese disease, drug and time NER on case reports, ICD normalisation by the MANBYO dictionary | **learn from**: one evaluation on the JP synthetic notes (`tools/medtxt_eval.py` already reads MedTxt) before adoption [O] |
| Docling | https://github.com/docling-project/docling | MIT | v2.150.1 2026-11-14 | Layout-aware PDF and Word parsing | **already reused** [R `services/doc_parser/parser.py:5`] |

### 2.3 De-identification: where TrialBox stands

[O, from B-1 §7.1 and the projects above] The field's open detectors are English-first. For Taiwan and Japan,
TrialBox's recognisers are ahead of anything open; its weakness is that three detectors disagree and none
normalises full-width text (B-1 M 15). The field's lesson is structural, not a library: Presidio runs every
recogniser on normalised text and maps offsets back. A5 plus B1-P1 do exactly that.

---

## 3. Data connectors and pipelines

TrialBox today [R, B-1 §1.1]: CSV files; a SQL replica (PostgreSQL and SQLite only, no Oracle or SQL Server driver);
FHIR Bulk Data **files** (no `$export` client); SS-MIX2 storage (strong partial); REDCap; spreadsheets; charts one by
one; no HL7 v2 live feed, no OMOP input, no NHI claims, no CDA.

### 3.1 HL7 v2 engines and MLLP listeners

| Project | Link | Licence [M 1] | Activity [M 1] | What it does | Verdict |
| --- | --- | --- | --- | --- | --- |
| Mirth Connect (NextGen) | https://github.com/nextgenhealthcare/connect | MPL-2.0 for the public code (4.5.2 and before); **closed and commercial from 4.6** [S https://docs.nextgen.com/en-US/mirthc2ae-connect-by-nextgen-healthcare-user-guide-3273569/4-6-0-upgrade-notes-203222, search summary] | last public release 4.5.2 2024-09-23; 411 open issues | The integration engine most hospitals already run | **ignore** the public 4.5.2 (no fixes); a site that owns a licence is the A4 path |
| Open Integration Engine | https://github.com/OpenIntegrationEngine/engine | MPL-2.0 | v4.7.0 2026-10-21; push 2026-11-11; community fork | Mirth 4.5.2 continued in the open: channels, MLLP, transforms, file writers | **adopt at the site's edge** (A4), S |
| BridgeLink (Innovar) | https://github.com/Innovar-Healthcare/BridgeLink | MPL-2.0 | v26.9.0 2026-10-01 | A second Mirth fork, vendor-backed | **learn from** (watch which fork the sites choose) |
| HAPI HL7v2 | https://github.com/hapifhir/hapi-hl7v2 | not verified (no LICENSE at the root; historically MPL/GPL dual) | v2.6.0 2025-02-05; push 2026-03-26; 88 open issues | Java parser, validator and MLLP for every v2 version | **ignore** (Java; TrialBox's v2.5 parser covers SS-MIX2) |
| hl7apy (CRS4) | https://github.com/crs4/hl7apy | MIT | v1.3.5 2024-03-13; push 2026-11-16 | Python v2 parsing and validation by version, ER7 encoding, a simple MLLP server [M 2] | **adopt if** a site must push MLLP to the box (A4's fallback), M |
| python-hl7 | https://github.com/johnpaulett/python-hl7 | BSD (LICENSE) | PyPI 0.4.5 2022-03-31 [M 3]; push 2025-06-09 | Minimal parser; `hl7.mllp` asyncio streams marked "experimental" [M 2] | **ignore** (experimental MLLP, old release) |
| Microsoft FHIR Converter | https://github.com/microsoft/FHIR-Converter | MIT | v5.1.0 2022-11-29; push 2026-11-06 | Liquid templates: HL7 v2, C-CDA and JSON to FHIR [M 2]; .NET | **learn from** (its v2 templates as a mapping checklist; .NET is a new runtime) |
| LinuxForHealth HL7v2-FHIR converter | https://github.com/LinuxForHealth/hl7v2-fhir-converter | Apache-2.0 | v1.1.1 2024-09-18; push 2026-02-11 | YAML-template v2 to FHIR (Java) | **ignore** (low activity) |

### 3.2 FHIR servers, clients, Bulk Data, profiles

| Project | Link | Licence [M 1] | Activity [M 1] | What it does | Verdict |
| --- | --- | --- | --- | --- | --- |
| HAPI FHIR and its JPA starter | https://github.com/hapifhir/hapi-fhir-jpaserver-starter | Apache-2.0 | image/v8.12.0-2 2026-10-02 (the pinned image [R `deploy/docker-compose.yml:149`] is current); hapi-fhir v8.10.3 2026-11-13; 1,697 open issues | The reference Java FHIR server | **already reused**; plan 8 moves it off the box (B-1 §2.2) |
| Blaze (Samply) | https://github.com/samply/blaze | Apache-2.0 | v1.13.0 2026-10-30; push 2026-11-15 | FHIR server with a built-in fast CQL engine; used by German research networks | **learn from**: if a FHIR store returns to the box, Blaze evaluates CQL where the data lives [O] |
| Microsoft FHIR Server | https://github.com/microsoft/fhir-server | MIT | release/5.2.84 2026-11-15 | .NET FHIR server with `$export` | **ignore** (.NET, SQL Server) |
| Medplum | https://github.com/medplum/medplum | Apache-2.0 | v5.2.17 2026-11-11; 775 open issues; Medplum Inc. | TypeScript FHIR platform with bots and auth | **ignore** (a platform, not a part) |
| fhir-py (Beda) | https://github.com/beda-software/fhir-py | MIT | v2.3.2 2026-10-27 | Async Python FHIR REST client | **adopt** for A3's REST calls, S |
| SMART client-py | https://github.com/smart-on-fhir/client-py | Apache-2.0 | v4.4.0 2026-02-10 | Python SMART client with models | **learn from** (SMART Backend Services signing pattern) |
| fhir.resources | https://github.com/nazrulworld/fhir.resources | BSD | PyPI 8.3.0 2026-07-03 [M 3] | Pydantic FHIR models | **already reused** (`fhir-resources` in `uv.lock`) |
| SMART Bulk Data server | https://github.com/smart-on-fhir/bulk-data-server | Apache-2.0 | no release; push 2026-09-15 | Reference `$export` server with synthetic data | **adopt as a test fixture** (A3) |
| SMART Bulk Data client | https://github.com/smart-on-fhir/bulk-data-client | Apache-2.0 | no release; push 2026-10-23 | Reference `$export` client; Node.js 22+ [M 2] | **learn from** (Node is a new runtime; port its flow) |
| HL7 FHIR core / validator | https://github.com/hapifhir/org.hl7.fhir.core | Apache-2.0 | 7.0.6 2026-11-13 | The validator TrialBox runs offline | **already reused** |
| US Core IG | https://github.com/HL7/US-Core | (HL7 IG) | 9.0.0 2026-06-01 | US profiles every certified EHR exposes | **adopt when the US is in scope** (B1-D7, M) |
| JP Core IG | https://github.com/jami-fhir-jp-wg/jp-core-v1x | (JAMI IG) | **1.2.0 released 2025-09-26**; push 2026-11-16 | Japanese FHIR profiles | B-1's open question answered in part: a 1.2.0 release exists; TrialBox checks 1.1.0 (B-1 §8.2). **Measure** which a Japanese site expects |
| TW Core IG build source | https://github.com/cctwFHIRterm/MOHW_TWCoreIG_Build | not verified (no LICENSE fetched) | last push 2025-05-19 | The CI build source of TW Core | TrialBox checks 1.0.0 (B-1 §8.1); nothing newer seen [O] |
| NHI FHIR IGs (PAS, CI, base) | https://github.com/TWNHIFHIR/pas | not verified | `pas` pushed 2026-11-17; `ci`, `base` 2026-10-19 | The NHI's own FHIR guides (pre-authorisation, cancer imaging) | **learn from**: the NHI publishes in FHIR and moves fast; TWPAS validation is already in the JVM image [R `deploy/docker/jvm.Dockerfile:2-3`] |

### 3.3 FHIR-to-OMOP and OMOP ETL tooling

| Project | Link | Licence [M 1] | Activity [M 1] | What it does | Verdict |
| --- | --- | --- | --- | --- | --- |
| OMOP CDM | https://github.com/OHDSI/CommonDataModel | not verified at the root (OHDSI, Apache-2.0 in practice) | v5.5.0 2026-08-25 tagged; push 2026-10-28 | The DDLs; **CDM 5.5 is tagged** while TrialBox pins 5.4 (B-1 §2.1) | **learn from**: read the 5.4 to 5.5 changes before any OMOP work [O] |
| WhiteRabbit / Rabbit-in-a-Hat | https://github.com/OHDSI/WhiteRabbit | Apache-2.0 | v1.0.0 2024-08-05; push 2026-10-13 | Profiles a source database and drafts the ETL map | **use beside** (BVR agreed) |
| Usagi | https://github.com/OHDSI/Usagi | not verified (no LICENSE at the root) | v1.4.3 2021-04-09; push 2026-05-26 | Source term to standard concept mapping with a reviewer | **learn from** (TrialBox's code-mapping page does this in the browser) |
| ETL-Synthea | https://github.com/OHDSI/ETL-Synthea | not verified | v2.1.1 2026-03-23 | Synthea CSV to OMOP | **ignore** (no Synthea in the box) |
| ETL-German-FHIR-Core | https://github.com/OHDSI/ETL-German-FHIR-Core | not verified | v3.0.0 2023-09-08; push 2024-03-11 | FHIR (German MII profiles) to OMOP, Java/Spring Batch | **learn from** (the only national-profile FHIR→OMOP ETL; dormant) |
| FhirToCdm | https://github.com/OHDSI/FhirToCdm | Apache-2.0 | no release; push 2025-01-29 | FHIR to OMOP (.NET) | **ignore** |
| NACHC fhir-to-omop | https://github.com/NACHC-CAD/fhir-to-omop | Apache-2.0 | v1.7.053 2024-07-26 | FHIR to OMOP (Java) | **ignore** |
| Pathling (CSIRO) | https://github.com/aehrc/pathling | Apache-2.0 (with EPL parts) | v10.0.0 2026-10-21; push today; 162 open issues | FHIR analytics on Spark, SQL on FHIR views, terminology functions | **learn from** (L2) |
| FHIR Data Pipes (Google) | https://github.com/google/fhir-data-pipes | Apache-2.0 | 0.5.0 2024-10-30; push 2026-11-10 | FHIR to Parquet with SQL on FHIR views | **learn from** (L2) |
| SQL on FHIR v2 spec | https://github.com/FHIR/sql-on-fhir-v2 | CC0 / public domain (LICENSE.md) | 3.0.0-ballot 2026-08-13 | The ViewDefinition standard | **learn from** (L2) |
| DataQualityDashboard | https://github.com/OHDSI/DataQualityDashboard | not verified at the root | v2.9.1 2026-10-17 | The community's full OMOP data-quality check set | **adopt after go-live** (BVR; TrialBox runs a subset [R `services/omop/dqd.py:1-25`]) |
| Achilles | https://github.com/OHDSI/Achilles | not verified | v1.7.2 2023-05-18; push 2026-10-09 | OMOP characterisation | **use beside** (BVR) |

### 3.4 SS-MIX2 readers and converters (Japanese sources searched)

| Item | Link | What was found | Verdict |
| --- | --- | --- | --- |
| The specification | https://www.jami.jp/wp-content/uploads/2024/05/SS-MIX2-標準化ストレージ-仕様書-Ver.1.2i_コード表.pdf (opened, 200, 1.0 MB [M 6]) | The current edition is **Ver.1.2i (May 2024)**, published by JAMI as MHLW standard HS026; the change from 1.2h is an MSH-7 correction and regimen unit codes [S, search summary of the JAMI page; the page itself answered 404 today] | **measure**: diff the code table of 1.2i against the reader's tables [R `services/adapter/sources/ssmix2/source.py:58-64`] |
| SS-MIX consortium site | https://www.ss-mix.org/ | HTTP 503 today [M 6]; sample storage data: **not verified** (B-1 §1.3 left it open too) | not verified |
| Open SS-MIX2 reader or SS-MIX2 → FHIR / JP Core converter | GitHub and Japanese web searches [S, search summaries] | **None found.** Published conversions use closed pipelines: a Tohoku study on InterSystems IRIS with JP Core; an IBM facade FHIR server over SS-MIX2 "provisionally" JP Core 1.1.1; an MHLW research group's converter-plus-repository design (IRIS Health or Smile CDR) [S https://link.springer.com/content/pdf/10.1007/s10916-023-01993-6.pdf; https://mhlw-grants.niph.go.jp/system/files/report_pdf/202203007B-sougou.pdf, search summaries] | TrialBox's reader is **ahead of anything open** [O]; the gaps are B-1's list (ADT-61, ADT transfers, OML-01/OMG, `_contents.xml`, one vendor storage) |
| JAHIS | https://www.jahis.jp (not opened) | JAHIS standards for prescriptions, lab and reports in HL7 v2.5 are the message rules SS-MIX2 storage holds | not verified today |

**What "SS-MIX2 complete" needs from the field** [O]: nothing to adopt; one vendor's sample storage (B1-D3) and the
1.2i code table (above). The owner's "must" is met better by TrialBox than by any open project found.

### 3.5 Taiwan, the US, SQL replicas, terminology servers

| Item | Link | Licence | Activity | What it offers | Verdict |
| --- | --- | --- | --- | --- | --- |
| NHI claims formats (點數清單 XML) | NHI path 醫事機構 → 醫療費用支付 → 醫療費用申報規定 → XML 申報格式; MOHW research-database handbooks (https://www.mohw.gov.tw/dl-95531-87f2c312-99b1-43ef-ab6a-4555773dd108.html) [S, search summary only] | public documents | the handbook's outpatient detail file revised 2026-01-27 (search summary) | Field definitions of claims; no open reader found | **build** (B1-D10, M) from the published format; not verified |
| NHI MediCloud | – | – | – | a per-patient look-up behind the NHI card reader | **ignore** (B-1 agreed) |
| python-oracledb | https://github.com/oracle/python-oracledb | UPL-1.0 or Apache-2.0 | v26.1.0 2026-10-27; Oracle | Thin mode needs no Oracle client [M 2] | **adopt** (A1), S |
| mssql-python | https://github.com/microsoft/mssql-python | MIT | v1.16.0 2026-10-13 tagged; PyPI 1.18.0 2026-11-17 [M 3]; Microsoft | SQL Server driver without a system ODBC install; the ODBC binaries ride in a companion package `mssql-python-odbc` [M 2] whose licence is **not verified** | **adopt** (A1) after the companion's licence is read; else `pyodbc` (MIT-0) with the site's ODBC driver |
| pymssql | (PyPI) | **LGPL** [M 3] | 2.4.6 2026-10-27 | FreeTDS-based | **ignore** (needs an allow-list entry for LGPL; two better options) |
| Snowstorm (SNOMED Intl) | https://github.com/IHTSDO/snowstorm | Apache-2.0 | 11.0.0 2026-09-02 | SNOMED terminology server **on Elasticsearch** [M 2], whose licence is AGPL-3.0 / SSPL / Elastic 2.0 [M 1] | **ignore** (finding: the store under it) |
| Snowstorm Lite | https://github.com/IHTSDO/snowstorm-lite | Apache-2.0 | 3.0.0 2026-11-05 | Small FHIR terminology server for SNOMED, no Elasticsearch | **learn from**: only if SNOMED is licensed for a site [O] |
| OHDSI Athena | https://github.com/OHDSI/Athena | not verified | v1.16.0 2026-08-29 | Download site for the Standardized Vocabularies (bundles by vocabulary, licence-gated ones marked) | **adopt the content** (A2), M |
| WHO ATC/DDD index | https://atcddd.fhi.no/atc_ddd_index_and_guidelines/order (search summary) | sold; €200 per electronic file on the order page (2024 listing) [S, search summary] | Index 2026 published | the full ATC with DDDs | **buy once per release** if A2 needs ATC names [O] |
| SNOMED CT | https://www.snomed.org/members (search summary) | members' countries free; others need an affiliate licence; 54 members in 2026 [S, search summary] | – | Taiwan's and Japan's status **not verified** | **measure first**: membership status before any SNOMED plan |

### 3.6 B-1's connector gaps, each against the field's best option

The rows are B-1 §1.4's gap table (need by country and size are B-1's); the last three columns are this survey's.

| Connector (B-1 id) | TW | JP | US | Field's best option found | Licence and offline | Verdict, size [O] |
| --- | --- | --- | --- | --- | --- | --- |
| Oracle / SQL Server driver (B1-D1) | must | often | often | python-oracledb thin; mssql-python or pyodbc | permissive; local database connections only [O] | adopt, S |
| SS-MIX2 remaining types, `_contents.xml`, delta (B1-D2) | – | must | – | none open; the 1.2i code table | public specification | build, M; diff against 1.2i first |
| One SS-MIX2 vendor storage (B1-D3) | – | must | – | none open; sample data not verified | – | needs a hospital or vendor sample, M |
| NHI drug code to ATC nightly (B1-D4) | must | – | – | NHI code files (data.gov.tw) + the ATC index | public / sold | build, S, with A2's content |
| `IU/L` ↔ `U/L` (B1-D5) | – | often | – | UCUM treats them as different units; no library resolves it for enzyme activity [O] | – | build, S (a rule per LOINC analyte) |
| FHIR REST, SMART Backend Services, `$export` (B1-D6) | rare | rare | must | fhir-py + SMART reference server; client-py for signing | permissive | adopt, M |
| US Core input (B1-D7) | – | – | must | US Core 9.0.0 IG | HL7 IG | build when the US is in scope, M |
| HL7 v2 MLLP (B1-D8) | often | often | must | Open Integration Engine at the edge; hl7apy in the box | MPL-2.0; MIT | adopt A4, S (edge) or M (listener) |
| OMOP as an input (B1-D9) | rare | rare | often | OHDSI DatabaseConnector shows the shape; TrialBox's own OMOP loader already knows the tables | permissive | build, M (read path reuses `services/omop/schema.py`) |
| NHI claims reader (B1-D10) | often | – | – | none open; the published XML format | public | build, M, after a site says which extracts it can give |
| CDA R2 / C-CDA | rare | rare | often | Microsoft FHIR Converter's C-CDA templates | MIT, .NET | learn from; out of 1.0 |
| JP-CLINS (3文書6情報) | – | later | – | JP Core 1.2.0 profiles | JAMI IG | later |
| Terminology content (B1-M2) | must | must | must | OHDSI vocabularies, NHI files, ATC index, LOINC | mixed; SNOMED gated | adopt A2, M |

---

## 4. Stores

TrialBox today [R, B-1 §2.1]: NDJSON per night (7 × the CSV), Parquet with checksums, one DuckDB file per night, a
DuckDB embedding cache, an unused pgvector schema, HAPI and OMOP off in the demo, PostgreSQL 16 with inline
checksummed migrations, rulesets in a git repository.

| Project | Link | Licence [M 1] | Activity [M 1] | What it does better or differently | Verdict |
| --- | --- | --- | --- | --- | --- |
| DuckDB | https://github.com/duckdb/duckdb | MIT | **v2.0.0 2026-10-21**; v1.5.6 2026-09-28; 1,215 open issues; DuckDB Labs and Foundation | TrialBox pins 1.5.5 [R `uv.lock:700-701`]; a 1.5.x patch and a major release are out | **keep**; B1-Q1 (parity run on 2.0) stands; take 1.5.6 meanwhile [O] |
| DuckLake | https://github.com/duckdb/ducklake | MIT | no GitHub release; push 2026-11-13 | Snapshots, time travel, catalog in a SQL database, Parquet data | **learn from** (BVR: after go-live; erasure under time travel first) |
| Delta Lake (delta-rs) | https://github.com/delta-io/delta-rs | Apache-2.0 | rust-v1.0.0 2026-09-28 | Table format with a Rust core and Python binding | **ignore** (DuckLake is the smaller step on the engine already used) |
| PyIceberg | https://github.com/apache/iceberg-python | Apache-2.0 | 0.12.0 2026-09-01 | Iceberg tables from Python | **ignore** at this scale |
| pgvector | https://github.com/pgvector/pgvector | PostgreSQL licence | push today; 17 open issues | HNSW and IVFFlat in PostgreSQL; TrialBox's `vec` schema uses `halfvec` HNSW [R `services/vec/store.py:32-37`] | **keep for later**; B1-S2 (retire `vec` for 1.0) agreed |
| DuckDB VSS | https://github.com/duckdb/duckdb-vss | MIT | no release; push 2026-10-14 | HNSW inside DuckDB; README: "**experimental** … proof of concept" [M 2] | **ignore** for 1.0 (brute-force cosine is enough at 5,000; B-1 §2.3) |
| pgvectorscale | https://github.com/timescale/pgvectorscale | PostgreSQL licence | 0.9.1 2026-09-04 | DiskANN index for pgvector | **ignore** at this scale |
| Qdrant / Milvus / Chroma / LanceDB | https://github.com/qdrant/qdrant ; https://github.com/milvus-io/milvus ; https://github.com/chroma-core/chroma ; https://github.com/lancedb/lancedb | Apache-2.0 each | all active (Qdrant v1.20.2 2026-11-16; Milvus v3.0.6 2026-11-11; Chroma 1.5.9 2026-05-05; LanceDB v0.41.0 2026-10-29) | Dedicated vector stores for millions to billions of vectors | **ignore**: a separate server for tens of thousands of note chunks is one more store to validate, back up and erase [O] |
| sqlite-vec | https://github.com/asg017/sqlite-vec | Apache-2.0 | v0.1.9 2026-03-31; 250 open issues | Vector search in SQLite | **ignore** |
| Alembic | https://github.com/sqlalchemy/alembic | MIT | rel_1_20_1 2026-10-22 | Python migrations with autogenerate and down-migrations | **ignore**: TrialBox's inline checksummed scripts with no down path are a deliberate, tested choice (B-1 §2.1) [O] |
| Flyway (Redgate) | https://github.com/flyway/flyway | Apache-2.0 (the open edition) | flyway-13.12.1 2026-11-05 | Versioned SQL migrations (Java) | **ignore** (Java; same function) |
| Liquibase | https://github.com/liquibase/liquibase | **Functional Source License 1.1 (FSL-1.1-ALv2)** in the LICENSE today [M 1] | v5.0.4 2026-08-20 | Changelog-based migrations | **ignore**: licence finding |
| Sqitch | https://github.com/sqitchers/sqitch | MIT | v1.6.1 2026-01-06 | Dependency-ordered SQL changes (Perl) | **ignore** |
| Synthea | https://github.com/synthetichealth/synthea | Apache-2.0 | v4.0.0 2026-03-05; push 2026-10-21; 295 open issues; MITRE | Synthetic US patients to FHIR, C-CDA, CSV | **keep ours** (BVR); Synthea for a US-site demo only [O] |
| Synthea International | https://github.com/synthetichealth/synthea-international | Apache-2.0 | push 2026-10-15 | Country configurations: **Japan yes** (by region and city), Taiwan not listed [M 2] | **learn from** (its Japanese demographics as a check on `tools/synth_hospital`) |
| OHDSI DatabaseConnector | https://github.com/OHDSI/DatabaseConnector | not verified | v8.0.0 2026-10-01 | OHDSI's R database layer; its DESCRIPTION now lists `duckdb` [M 2] | **learn from**: OMOP on DuckDB is now a path the OHDSI tools themselves take, which supports keeping the lake on DuckDB [O] |

**Is a vector database needed?** [O, agreeing with B-1 §2.3] No, not at 5,000 to 50,000 patients. The field's
dedicated stores solve a scale TrialBox does not have; the in-database options (pgvector HNSW, DuckDB VSS) exist
when it does. Measure first: S2b's share of SCREEN time at 50,000 patients with the chosen embedder (B-1 run G-3).

---

## 5. Model serving

TrialBox today [R]: vLLM `v0.32.0` pinned by digest, two models resident, CUDA graphs off (`--enforce-eager`),
16 sequences each, JSON-schema response formats checked by the gateway [R `deploy/docker-compose.rtxpro6000.yml:32,
70,83`; B-1 §3.1]; embeddings from a local sentence-transformers service, TEI tested and not adopted (D-577)
[R `docs/reviews/2026-11-12-tei-parity.md:1-12`].

| Project | Link | Licence [M 1] | Activity [M 1] | What it does better or differently | Verdict |
| --- | --- | --- | --- | --- | --- |
| vLLM | https://github.com/vllm-project/vllm | Apache-2.0 | **v0.34.0 2026-11-16**; v0.32.0 2026-10-18; 10,358 open issues; vllm-project (multi-company) | The engine in use; structured outputs through xgrammar or guidance backends, chosen with `--structured-outputs-config.backend` [S https://docs.vllm.ai/en/latest/features/structured_outputs/, search summary]; x86 and ARM CPU builds [M 2] | **keep**; move with B1-M5 and G-1 |
| SGLang | https://github.com/sgl-project/sglang | Apache-2.0 | v0.5.23 2026-11-02; 6,549 open issues | Fast prefix (radix) caching, constrained decoding | **learn from**: worth one A/B only if G-2 shows prefix caching is where time goes [O] |
| llama.cpp | https://github.com/ggml-org/llama.cpp | MIT | push today; releases as build tags; 2,620 open issues | CPU and small-GPU serving of quantised models, GBNF and JSON-schema grammars [M 2] | **learn from** (L5): one timed run of the verifier on CPU |
| Text Generation Inference | https://github.com/huggingface/text-generation-inference | Apache-2.0 | v3.3.7 2025-12-19; README: "**now in maintenance mode**" [M 2] | – | **ignore** |
| Text Embeddings Inference | https://github.com/huggingface/text-embeddings-inference | Apache-2.0 | v1.9.4 2026-09-15; CPU images for x86 and ARM [M 2] | One image for embeddings | **keep ours** (D-577); reopen only on a measured CPU speed need |
| Ollama | https://github.com/ollama/ollama | MIT | v0.40.16 2026-11-09 | Easy local serving; **cloud models and web search are on unless `disable_ollama_cloud` or `OLLAMA_NO_CLOUD=1` is set; desktop builds auto-update** [M 2] | **ignore**: phones home by default |
| LMCache | https://github.com/LMCache/LMCache | Apache-2.0 | rc tags 2026-11-13 | KV-cache offload and reuse across requests | **ignore** for 1.0 (one box, two models) |
| xgrammar | https://github.com/mlc-ai/xgrammar | Apache-2.0 | v0.2.9 2026-11-09 | Grammar engine inside vLLM and SGLang | **already used** through vLLM [O] |
| llguidance | https://github.com/guidance-ai/llguidance | MIT | push 2026-11-11; PyPI 1.9.1 2026-09-30 [M 3] | The other vLLM backend | **learn from** (a fallback backend if a schema trips xgrammar) |
| Outlines | https://github.com/dottxt-ai/outlines | Apache-2.0 | 1.3.3 2026-08-06 | Structured generation library | **ignore** (the engine already does it) |
| LLM Compressor | https://github.com/vllm-project/llm-compressor | Apache-2.0 | 0.10.0.5 2026-11-09 | Quantisation (AWQ, GPTQ, FP8, NVFP4) for vLLM | **learn from**: the provenance of a site's 4-bit weights should name the tool and recipe [O] |
| OpenVINO GenAI | https://github.com/openvinotoolkit/openvino.genai | Apache-2.0 | 2026.4.1.0 2026-10-01 | CPU / integrated-GPU serving on Intel | **learn from** (only if a site's box is Intel without a GPU) |
| lm-evaluation-harness | https://github.com/EleutherAI/lm-evaluation-harness | MIT | v0.4.13 2026-08-31 | Benchmark harness | **ignore** (multiple-choice benchmarks, not TrialBox's tasks) |
| Inspect | https://github.com/UKGovernmentBEIS/inspect_ai | MIT | 0.3.290 2026-11-14; UK AI Security Institute | Task-based evaluation with scorers and logs | **use beside** (BVR agreed) |
| HELM | https://github.com/stanford-crfm/helm | Apache-2.0 | v0.5.16 2026-04-30 | Holistic evaluation incl. MedHELM | **learn from** |

**Batching and flags** [O]: nothing in the field changes B-1's order: G-1 (CUDA graphs on) and G-2 (prefix caching)
on the GPU VM decide more than a change of engine would. **CPU-only box**: vLLM's CPU build and llama.cpp both exist;
neither has been timed on TrialBox's prompts, so the claim "a GPU-less box can read notes" stays unproven.

---

## 6. EDC, eConsent, CTMS, eTMF

TrialBox today [R]: an EDC prefill that drafts eCRF values from the record with citations, signed by a person
before a REDCap write or an ODM 1.3.2 export with CDASH tags [R `services/edc/__init__.py:1-2`;
`services/edc/odm.py:1-5`; `services/edc/cdash.py:1-15`]; a selectable EDC backend that talks to REDCap or to the
owner's EDC through a REDCap-compatible API [R `services/edc_backend/__init__.py:1-5`].

**The owner's EDC, as TrialBox's own docs describe it** (the EDC's repository was not read, per D-1060) [R
`docs/data/14-edc-integration-handoff.md:15-75`]: a Rust server as the system of record on PostgreSQL, a FHIR R4
view, a REDCap-compatible `/api/` (version 14.0.0), signed event delivery from a durable outbox with retries, OIDC
sign-in, account lock after five failures, idle logout, a password policy, FHIR changes written to a hash-chained
audit log as the real user, SMART 2.x scopes and refresh-token rotation; measured release timings (one Patient POST
p50 1.75 ms; 10,000 Patients in 3.3 s). Still open on the EDC side by that note: persisting MLLP PID and OBX, a
full Synthea re-import, strict CI lint gates.

| Project or product | Link | Licence | Activity [M 1] | Audit, signature, CDISC | Verdict |
| --- | --- | --- | --- | --- | --- |
| OpenClinica 3 (open) | https://github.com/OpenClinica/OpenClinica | not verified (no LICENSE at the root; historically LGPL) | 3.17.2 2024-08-02; push 2025-10-28; 101 open issues | Audit trail, e-signature, ODM 1.3 import/export; the company's current product (OC4) is SaaS [S, search summary: third-party prices from $750 a month] | **learn from** (ODM extensions) |
| LibreClinica | https://github.com/reliatec-gmbh/LibreClinica | **GPL** (LICENSE) | v1.4.0rc1 2025-06-13; push 2026-11-01 | OpenClinica 3 continued by the community | **ignore** for the bundle (GPL); learn from its ODM handling |
| OpenEDC (Münster) | https://github.com/imi-muenster/OpenEDC | MIT | no release; push 2025-03-05; README says "Unmaintained" | ODM-native browser EDC | **ignore** |
| REDCap (Vanderbilt) | https://projectredcap.org/join/termsofuse/ (search summary) | **not open source**: licence free to non-profit institutions only; for-profit organisations may not hold a licence or self-host [S, search summary of the terms and FAQ] | – | Audit log, e-consent framework, Part 11 options | **keep as a site's EDC only**: TrialBox must never bundle it [O] |
| CDISC Rules Engine | https://github.com/cdisc-org/cdisc-rules-engine | MIT | **v1.0.0 2026-11-03** | Conformance rules for SDTM, ADaM, SEND, USDM | **learn from**: plan 8 lists USDM checking as "candidate to leave out"; v1.0.0 makes it cheaper if the owner keeps it [O] |
| odmlib | https://github.com/swhume/odmlib | MIT | v0.2.1 2026-08-27 | Python ODM 1.3 / 2.0 and Define-XML models with validation | **learn from**: a second reader of TrialBox's ODM export in a test [O] |
| OpenMRS | https://github.com/openmrs/openmrs-core | MPL-2.0 (with health-care disclaimer) | 2.8.10 2026-10-06 | Open EMR | **ignore** (an EMR, not an EDC) |
| Medidata Rave, Veeva Vault EDC / SiteVault, Castor, Viedoc | vendor sites (search summaries only) | commercial | – | Part 11 audit and signatures; Veeva SiteVault free to sites with eSource (LIT §0.13); no public price lists for Castor and Viedoc [S, search summary] | **learn from** (SiteVault eSource is the free competitor to prefill, LIT) |
| eConsent, CTMS, eTMF (open) | – | – | – | No maintained open eConsent, CTMS or eTMF project was found in this pass; the TMF Reference Model (CDISC) is a specification, not software | **not verified** beyond this |

**Where the owner's EDC stands** [O, from TrialBox's docs only]: on audit (hash-chained, as the real user), sign-in
hardening and an API others already speak, it is at or above the open EDCs above, which are either dormant, GPL or
unmaintained. What the open and commercial systems have and the handoff note does not mention: a CDISC ODM / Define
export of the EDC's own data, an e-signature manifestation per record (Part 11 §11.50), and a validation package
(IQ/OQ/PQ). Those are questions for the integrator, not findings.

---

## 7. Competitors

LIT §2 (2026-10-17) is the full matrix; this table adds what changed or was confirmed today and what TrialBox
should answer. Rows marked "search summary" were not opened and count as not verified.

| Product | Claim | Evidence found today | Price (public) | What TrialBox should answer [O] |
| --- | --- | --- | --- | --- |
| Triomics (Prism) | Generative-AI matching and screening with itemised rationale and source citations | MSK announced deployment across its portfolio in two phases on 2025-11-04; "manual pre-screening up to 45 minutes per patient"; **no accuracy or outcome data**; MSK has institutional financial interests in the company [S https://www.mskcc.org/announcements/msk-to-deploy-triomics-ai-platform-to-improve-clinical-trial-matching-and-screening]. Regenstrief, IU Health and Triomics run a hybrid effectiveness-implementation trial at two satellite sites, funded by an Eli Lilly grant; no results yet (2026-02-05) [S https://regenstrief.org/case-study-ai-enabled-trial-screening] | none | The first independent prospective evaluation will come from Regenstrief; TrialBox's answer is its own prospective protocol on a Taiwan site with a recall certificate (LIT §3) |
| Lind / Lind Asia | All-patients × all-trials screening; JV with PREMIA for Taiwan, Japan, Korea, Singapore, Australia | 2026-05-29 article: **no named hospital, no numbers, deployment model not stated** [S https://biospectrumasia.com/news/123/27694/premia-and-lind-expand-ai-powered-clinical-trial-screening-across-asia-pacific.html] | none | The closest competitor in TrialBox's countries; answer with on-premises, no egress, code-mixed notes, and published Taiwan numbers |
| NTT / NTT DATA × Kindai × Chugai | Rule-based vs a domestic LLM vs hybrid for candidate extraction | Study June 2026 to March 2027 (LIT §1.1); NTT DATA reported a May 2026 technical verification "confirming extraction from RWD", product "in view" [S https://innovatopia.jp/ai/ai-news/111642/, search summary] | none | The Japanese reference design: TrialBox's ladder is the same hybrid; publish first |
| Osaka University Hospital | Feasibility study of AI extraction of eligible patients from the EHR | Research notice for patients seen 2022-04 to 2024-03 [S https://www.hosp.med.osaka-u.ac.jp/research/files/202606.pdf, search summary] | – | A potential Japanese validation partner, not a competitor |
| NEC × Tohoku University Hospital; Fujitsu × Nagoya / Gifu | LLM extraction for endometrial cancer (NEC, March 2025); 64 % PPV on breast-surgery charts (Fujitsu, LIT §1.1) | NEC: search summary only | none | Same as above |
| Taipei Medical University | Lung-cancer decision support that matches patients with global trial databases | search summary only (focustaiwan.tw); no deployment date or numbers | – | The only Taiwanese matching item seen; not verified |
| MOHW AI centres (Taiwan) | Three AI centres; an impact-research centre led by five medical centres, 27 institutions; six AI products in clinical evaluation | search summary only (ithome.com.tw) | – | The route to a Taiwan evaluation of TrialBox [O] |
| Epic | Trial evaluation "in development, 2026" (LIT §0.2) | No source today confirms general availability [S, search summary] | in licence | Unchanged: Epic does not reach a home-grown Taiwanese HIS |
| Paradigm Health | Matching, feasibility, study conduct (ex-Flatiron Clinical Pipe) | $78 M raised and the Flatiron business acquired (search summary; LIT §2.1 has the rest) | sponsor pays | Network-tied, US |
| Massive Bio, Tempus TIME, BEKhealth, Inato, Reify StudyTeam, TriNetX, Medidata, IQVIA, ConcertAI, Truveta | as LIT §2.1 to §2.4 | nothing newer found in this pass | BEKhealth on AWS from about $6k a year (LIT) | as LIT §2.7 |
| Mirth Connect (NextGen), commercial | The integration engine sites already run | closed-source from 4.6 (section 3.1) | quoted per site | A4: the site's engine writes files; TrialBox reads them |

**What the competitors still lack** (LIT §2.7, re-checked against today's items) [O]: none of the products above
publishes a per-criterion evidence quote that is string-verified, a recall bound, Traditional-Chinese or Japanese
code-mixed results, or runs fully offline on the hospital's box. The weakness of TrialBox against all of them is the
same as in October: **no peer-reviewed or prospective result yet**.

---

## 8. Projects the owner named or may name

| Project | What was checked | Finding |
| --- | --- | --- |
| `https://github.com/huggingface/pybot` | `git ls-remote` and the README and LICENSE fetched raw [M 4, M 1] | The address exists: a public Apache-2.0 repository of Hugging Face, last pushed 2026-11-16, describing "a chatbot written in pure Python … no weights, no training, just rules" built by agents. Assessed separately in `05-pybot-assessment.md` (written by another session). |

---

## 9. For each TrialBox component, is an open one better?

| Component | TrialBox today [R] | Best outside candidate | Better / equal / worse, and why [O] | Switching cost | Recommendation |
| --- | --- | --- | --- | --- | --- |
| CSV reader | `services/adapter/sources/csv/source.py`, three encodings, quarantine (B-1 §1.1) | none (generic loaders lack quarantine and per-file encoding) | **TrialBox better** | – | keep |
| SQL replica reader | `services/adapter/sources/cgrd_sql/source.py:1-6`; PostgreSQL and SQLite only | python-oracledb, mssql-python / pyodbc | the drivers are **better** (TrialBox has none for Oracle or SQL Server) | S | **adopt** A1 |
| FHIR Bulk reader | files only, tombstones handled [R `services/adapter/sources/fhir_bulk/source.py:1-6`] | fhir-py + the SMART reference server | **better** for `$export`; TrialBox better on tombstones | M | **adopt** A3 |
| SS-MIX2 reader | 1,161 lines, 10 types, 26 test files (B-1 §1.1, §1.3) | none open | **TrialBox better** | – | keep; finish B1-D2, B1-D3 |
| HL7 v2 live feed | absent | Open Integration Engine at the edge; hl7apy MLLP | **better** (TrialBox has none) | S / M | **adopt** A4 |
| HL7 v2 parser | own v2.5 parser [R `services/adapter/sources/ssmix2/hl7.py:1-60`] | hl7apy, HAPI HL7v2 | **equal** for SS-MIX2's v2.5; outside parsers cover all versions | M | keep; revisit if a non-SS-MIX2 v2 feed arrives |
| Mapping engine (YAML to FHIR) | `services/adapter/mapping/engine.py:546` | Microsoft FHIR Converter (Liquid), OIE channels | **equal**; theirs need .NET or Java | L | keep; use FHIR Converter's v2 templates as a checklist |
| FHIR to lake flattening | `services/lake/flatten.py:718`, schema in code; one field in five places (B-1 §2.4) | SQL on FHIR v2 ViewDefinitions (Pathling, FHIR Data Pipes) | **better design**, heavier engines | M | **learn from** L2: express `SCHEMAS` as ViewDefinitions read by flatten, OMOP export and the compiler |
| FHIR validation | HL7 validator, offline, 1 % sample | same tool | **equal** (already reused) | – | keep |
| FHIR server | HAPI JPA (off in demo) | Blaze | **equal**; Blaze adds in-place CQL | M | keep plan 8 ("off the box") |
| OMOP store and DQD subset | `services/omop/`, about ten checks [R `services/omop/dqd.py:1-25`] | OHDSI DataQualityDashboard, Achilles | DQD is **better** (full set) | M | adopt after go-live (BVR) |
| Terminology content | tables of 24 to 280 rows plus full ICD-10-CM (B-1 M 5) | OHDSI vocabularies via Athena; NHI code files; ATC index | **better** (orders of magnitude more content) | M | **adopt** A2 |
| Terminology service | Parquet tables and OMOP vocabulary schema | Snowstorm (Elasticsearch), Snowstorm Lite | TrialBox's is **better for the box** (no server, no Elasticsearch) | – | keep |
| Criteria compiler | model reads, rules check, SQL/CQL templates, equivalence gate | Criteria2Query, CIRCE/Circepy | **TrialBox better** on safety (no model-written SQL); CIRCE better as a standard target | M | keep; L3 as a third engine |
| Screening cascade | S0 to S4 with quotes and a second model | TrialMatchAI, TrialGPT | **equal or better** on evidence; theirs have published results | – | keep; **benchmark** against both (L4) |
| Note negation and context | words in compiler and chart facts; none on note sentences | medspaCy ConText (English only) | **better method**, no ja/zh content | S to M | **learn from** L1 |
| Identifier detection | three detectors, 5 / 13 / 14 of 18 (B-1 M 15) | Presidio's structure; Sudachi, jieba for names | TrialBox's TW/JP recognisers **better**; its structure **worse** | S to M | **adopt** A5 with B1-P1 |
| Lake (Parquet + DuckDB per night) | B-1 §2.1 | DuckLake | DuckLake **better** on snapshots and storage | M | after go-live (BVR) |
| Vector store | DuckDB cache (live) + pgvector `vec` (unused) | Qdrant, Milvus, DuckDB VSS | **not needed** at this scale | – | retire `vec` (B1-S2) |
| Embedding server | own sentence-transformers service | TEI | **equal** (D-577) | S | keep |
| LLM serving | vLLM 0.32.0, eager mode | vLLM 0.34.0; SGLang; llama.cpp for CPU | same engine, newer; flags matter more | S | G-1, B1-M5; L5 for CPU |
| Structured output | JSON schema per call, gateway re-checks | xgrammar / llguidance inside vLLM | **equal** (TrialBox already uses the engine's) | – | keep |
| Evaluation | own qualification and bake-off tools | Inspect, HELM | **equal**; qualification must stay ours | – | use Inspect beside (BVR) |
| Migrations | inline checksummed, no down path | Alembic, Flyway, Sqitch; not Liquibase (FSL) | **equal** | – | keep |
| Synthetic data | own JA/zh-TW/EN hospital with gold and SS-MIX2 | Synthea (+ Japan config) | **TrialBox better** for its countries | – | keep |
| Protocol parsing | Docling | same | **equal** (reused) | – | keep |
| EDC prefill and export | signed values, ODM 1.3.2, CDASH tags | OpenClinica 3 / LibreClinica (GPL), odmlib, CDISC Rules Engine | **TrialBox better** at drafting from the record; odmlib a useful second reader | S | keep; odmlib in a test |
| Console | FastAPI + Jinja server pages [R `services/console/app.py:37,40`] | ATLAS, Leaf (cohort UIs) | **not comparable** (different job) | – | keep; learn from ATLAS's concept-set editor |

### 9.1 Fixes this survey adds for plan 9

Ids continue B-1's table; lanes are a guess from plan 8 §8b. Each "measure first" runs on TrialBox's own synthetic
or public data, on CPU unless it says GPU.

| Id | Fix | Size | Lane | Measure first |
| --- | --- | --- | --- | --- |
| B3-1 | A1: `python-oracledb` (thin) and `mssql-python` or `pyodbc` in the image, with allow-list entries and a dialect test per database; read the companion ODBC package's licence first | S | E, B2 | a CGRD-type view read through each driver in a container (B1-D1) |
| B3-2 | A2: load the OHDSI vocabularies (RxNorm, LOINC, ICD-10-CM, ATC codes), the NHI drug and order files and, where bought, the ATC names at install; record each source's licence in the licence register | M | E, H | concept names resolved by table, before and after, on sigir and P1b; `concept_map` calls per protocol |
| B3-3 | A3: the SMART Bulk Data reference server as a test fixture; a `$export` kick-off, poll and download in the FHIR source on `fhir-py` | M | E | one export read end to end; tombstones on a `_since` run |
| B3-4 | A4: a runbook section "the site's integration engine writes HL7 v2 to a folder", with an Open Integration Engine channel export as the example; the SS-MIX2 reader's v2 parser reads the folder | S | E, Int | one ADT and one ORU message from the engine through the reader on the synthetic site |
| B3-5 | A5: Sudachi (Japanese) and jieba (Chinese) name segmentation inside B1-P1's single detector; NFKC with offsets mapped back | S to M | B2, A2 | B-1's 18 probes, a full-width set and a katakana set; false positives on 1,000 synthetic notes |
| B3-6 | L1: a ConText-style rule pass (negation, history, family, uncertainty) in ja, zh-TW and en on note sentences before S3; output as a flag the judge sees, never a silent drop | M | A2 | judge calls and accuracy on P2b's note criteria with and without the flags (stub first, then GPU) |
| B3-7 | L2: the lake's table schemas written as SQL on FHIR ViewDefinitions, read by flatten, the OMOP export and the compiler | M | B2 | the five-place field change of B-1 §2.4 made in one place; goldens equal |
| B3-8 | L4: TrialMatchAI and TrialGPT as two more arms of `tools/trialgpt_compare.py` on TREC CT 2022/2023 and sigir | M | H | recall at 10 and criterion accuracy against the cascade, public data only |
| B3-9 | L5: one timed run of the verifier on CPU (llama.cpp or vLLM CPU) on the stub's prompts | S | D | seconds per call and peak memory on a 16-core CPU; schema validity of 100 answers |
| B3-10 | Read the OMOP CDM 5.4 → 5.5 changes and JP Core 1.1.0 → 1.2.0 changes; write which a site will expect | S | B2, E | – (reading) |
| B3-11 | Licence findings into the allow-list's refusal rules: GPL (CKIP), FSL (Liquibase), AGPL/SSPL (Elasticsearch under Snowstorm), non-profit-only (REDCap), "on by default" cloud features (Ollama) | S | security owner | `make allowlist-check` refuses each on a planted entry |

---

## 10. Measurement log

All on 2026-11-17 from this session, scripts in the session's scratch folder (not in the repository). No
dependency installed; outside the TrialBox virtual environment only the standard library was used.

| # | Command | What it gave |
| --- | --- | --- |
| 1 | `python3 -I probe.py <owner/repo> ...` over 130 repository addresses: `https://ungh.cc/repos/<r>` (push date, stars, default branch), `https://ungh.cc/repos/<r>/releases` (latest non-prerelease, date), `https://api.deps.dev/v3/projects/github.com%2F<r>` (open issues, licence as deps.dev reads it), and the LICENSE file fetched raw from the default branch with its text matched for licence names | the Licence and Activity columns; 125 found, 5 returned 404 (`cabrerahector/TrialMatchAI`, `MOHW-TWCoreIG/cctwFHIRterm`, `VectorChord/VectorChord`, `dfci/matchminer-ai`, `ncbi-nlp/TrialGPT-2`) |
| 2 | `python3 -I raw.py -g <regex> <file>` on READMEs and docs: Presidio `docs/supported_entities.md`; medspaCy `README.md`; DuckDB VSS `README.md`; TGI `README.md`; FHIR Converter `README.md`; Ollama `docs/faq.mdx`; vLLM `docs/getting_started/installation/cpu.md`; llama.cpp `README.md`; TEI `README.md`; hl7apy `README.md`; python-hl7 `docs/mllp.rst`; SMART bulk-data-client `README.md`; Snowstorm `README.md`; Elasticsearch `LICENSE.txt`; Liquibase `LICENSE.txt`; mssql-python and python-oracledb `README.md`; Synthea International `README.md`; Stanza `README.md`; DatabaseConnector `DESCRIPTION`; CohortGenerator `DESCRIPTION`; pybot `README.md` | the quoted facts in sections 2 to 5 |
| 3 | `curl https://pypi.org/pypi/<package>/json` for oracledb, pymssql, pyodbc, mssql-python, fhir.resources, fhirpy, hl7apy, hl7, presidio-analyzer, medspacy, sudachipy, ginza, xgrammar, llguidance, duckdb, pgvector, gliner, spacy, fhir-core | version, upload date and declared licence (e.g. oracledb 26.1.0 2026-10-27 "UPL-1.0 OR Apache-2.0"; pymssql 2.4.6 LGPL; pyodbc 5.5.0 MIT-0; duckdb 2.0.0 2026-10-21) |
| 4 | `git ls-remote https://github.com/huggingface/pybot` | HEAD `7d63c7fb`, branch `main`, 11 pull-request refs |
| 5 | `grep` in this checkout: `-tx` in `services/adapter/validate/validator.py`; `name = "duckdb"` in `uv.lock`; `image:` in `deploy/docker-compose*.yml`; `halfvec` in `services/vec/store.py`; negation patterns in `services/` | the [R] cells |
| 6 | `curl -L -w '%{http_code}'` on the JAMI SS-MIX2 1.2i code-table PDF and on `https://www.ss-mix.org/` | 200 and 1,038,448 bytes; 503 |

---

## 11. What this survey could not verify

- **Issue trends and default-branch commit dates.** The GitHub API was not reachable; activity is the last push on
  any branch (ungh.cc) and today's open-issue count (deps.dev). Who maintains a project is read from its
  organisation, not from contributor statistics.
- **Licences with no LICENSE file at the repository root:** HAPI HL7v2, OpenClinica 3, MatchMiner API, Usagi,
  ETL-Synthea, ETL-German-FHIR-Core, OMOP CDM, DataQualityDashboard, Achilles, Athena, DatabaseConnector, the TW
  Core build repository and the NHI FHIR IG repositories. OpenCC's licence is from deps.dev only.
- **Model weights' terms** for MedCPT, GLiNER models and any embedding or NER weights: only code licences were read.
- **The licence of `mssql-python-odbc`**, the companion package that carries Microsoft's ODBC binaries.
- **SS-MIX2:** the JAMI specification page answered 404 and ss-mix.org 503; the 1.2i edition is confirmed by its
  PDF, its change list only by a search summary. Whether the consortium's sample storage exists in a usable form
  (also open in B-1). JAHIS pages were not opened.
- **Taiwan:** the NHI claims XML format document itself (only its location and a research-database handbook were
  seen in a search summary); whether Taiwan and Japan are SNOMED members; the Taipei Medical University and MOHW
  AI-centre items (search summaries only).
- **Prices:** the ATC electronic index (2024 order page), OpenClinica OC4 (third-party listing), Castor and Viedoc
  (none public).
- **Products** marked "search summary" in section 7 (NTT DATA verification, Osaka University, NEC and Tohoku,
  Paradigm, Epic GA status) and the commercial EDC claims in section 6.
- **REDCap terms** were read through a search summary of Vanderbilt's own pages, not the agreement itself.
- **Mirth Connect's licence change** is from a search summary that quotes NextGen's own 4.6.0 upgrade notes; the
  notes were not opened.
- **No performance claim** in this page was measured on a GPU or on TrialBox's prompts: the CPU-serving and
  SGLang remarks are opinions until G-1, G-2 and an L5 run exist.
- **TrialGPT 2.0, LLM-Match, MatchMiner-AI, n2c2 and the ATLAS concept-set editor** were not opened today; they are
  cited from LIT or by name.
- **eConsent, CTMS and eTMF** open projects: none found in this pass, which is not proof that none exists.
