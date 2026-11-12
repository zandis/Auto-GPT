# TB-DS-05 Open-source reuse survey

| Field | Value |
| --- | --- |
| Document ID | TB-DS-05 (formerly TB-OSS-05) |
| Version | 0.5 (reference; build tags per TB-DS-00 §2 (S0–S5 / H / L); additions from TB-REV-006f §6 and the 2026-11-07 LLM survey) |
| Date | 2026-11-07 |
| Owner | Changfu Kuo (Aimedics) |
| Related | TB-DS-00 (baseline, wins on conflict), TB-DS-01 (requirements), TB-DS-02 (architecture), TB-DS-03 (security and privacy), TB-DS-04 (verification and operations), TB-PLAN-01 (project plan) |
| Approvals | Product owner: ______ · Engineer: ______ |
| Status | Research; no code changed |

## How to read this document

Changfu asked: "have you done an open ecosystem search, what can be used?" This document answers that for every layer in the architecture (TB-DS-02 §5). For each layer it gives 3–6 candidates, then a one-line pick.

**How the facts were checked (2026-11-07).** Licence, stars and the last push date come from the GitHub search API. Latest versions come from PyPI, npm, Maven Central, Docker Hub, Quay, the FHIR package registry (packages.fhir.org) or Hugging Face. CPU architecture (amd64/arm64) comes from Docker Hub image manifests. Anything not checked this way is marked **(unverified)**. "Stars" and "last push" show activity, not quality.

**Evaluation criteria (applied in this order).** (1) Licence class: permissive first; weak copyleft only unmodified as a separate component; strong copyleft or non-commercial only with a written reason (§20). (2) Maintenance: a release or push within the last 12 months and more than one maintainer where visible. (3) Runs on-prem without internet, on amd64 and, for the DGX Spark option, arm64. (4) Japan and Taiwan fit: Japanese and Traditional Chinese text, JP Core / TW Core, SS-MIX2. (5) Maintenance load for one small team: fewer services and no new language runtime win ties. A verdict is the first criterion a candidate fails, or **Use** if it fails none and beats the alternatives on (4) and (5).

**Checked column.** Each candidate row ends with the date its licence, version and activity were read from the sources above, or *unverified* when one of those facts was not read from a primary source; an unverified fact is confirmed in the spike that adopts the candidate (§20 "Items to verify in a spike").

**Verdict values.** **Use**: adopt or keep. **Evaluate**: worth a spike before deciding. **Reject**: don't adopt, with the reason.

**Licence shorthand.** Permissive = Apache-2.0, MIT or BSD: safe to ship inside a commercial on-prem appliance. Weak copyleft = LGPL or MPL: safe if used unmodified as a separate component. Strong copyleft = AGPL or GPL: see §20 before shipping. "Source-available" = not open source; read the terms.

### Surprises found in this survey

1. **MinIO is archived.** The GitHub repository `minio/minio` (AGPL-3.0, 61k stars) is read-only since 25 April 2026, after maintenance mode in December 2025. TrialBox ships MinIO today. It needs replacing (§13).
2. **JMedRoBERTa is non-commercial** (CC BY-NC-SA 4.0), and **YomiToku** (Japanese OCR) needs a paid commercial licence. That applies even for paid proofs of concept and for workflow integration. Neither can go into the product as is.
3. **Japan and Taiwan are not SNOMED International members** on the evidence found so far: neither appears as a member in secondary sources, and SNOMED International's own member list ([snomed.org/our-members](https://www.snomed.org/our-members)) and the SNOMED glossary entry for "member territory" ([docs.snomed.org](https://docs.snomed.org/snomed-international-documents/snomed-ct-glossary/m/member-territory)) are the sources to confirm against. **Status: unverified; confirm from the official list and the MLDS before any OMOP export (§20 "Items to verify in a spike", item 8).** No pick in this document depends on it until then. If it holds, SNOMED CT use in Japan and Taiwan needs a paid affiliate licence. That matters for the OMOP export (§9).
4. **Medplum has moved on to v5.2.15** (6 November 2026). The report cited v5.1.x from July.
5. **Zitadel is AGPL-3.0**, and **authentik** has an enterprise directory under a subscription licence. Keycloak is the only fully Apache-2.0 option among the large identity servers.
6. **The FHIR package registry carries JP Core 1.1.0**, but jpfhir.jp publishes **JP Core 1.2.0 (July 2025)**. Pin the newer package from the JAMI source.

---

## 1. FHIR servers

| Candidate | Licence | Latest version (date) | Activity | arm64 | On-prem fit | JP/TW | Verdict | Checked |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [HAPI FHIR JPA](https://github.com/hapifhir/hapi-fhir) | Apache-2.0 | 8.12.1 (Maven, 2026-10-30) | 2.4k stars, push 2026-11-07 | yes (unverified for the JPA image) | Good; Java + Postgres; in use (TB built) | Loads any IG package (JP Core, TW Core) | **Use** (as built; fallback if the Medplum spike fails) | unverified |
| [Medplum](https://github.com/medplum/medplum) | Apache-2.0 | 5.2.15 (Docker/npm, 2026-11-06) | 2.8k stars, push 2026-11-07 | amd64 + arm64 | Good; Node + Postgres + Redis; built-in OAuth2/OIDC, MFA, access policies, AuditEvent, Questionnaire, bots, HL7 agent | IG packages loadable (unverified for JP Core profiles) | **Evaluate** (ADR-14 spike, L; ADR-06 is superseded) | unverified |
| [Blaze (Samply)](https://github.com/samply/blaze) | Apache-2.0 | 1.13.0 (Docker, 2026-10-30) | 231 stars, push 2026-11-06 | amd64 + arm64 | Good; single JVM; built-in fast CQL engine, `$evaluate-measure`, terminology ops; used by Germany's Medical Informatics Initiative | Not specific | **Evaluate** (only as the CQL engine, §2) | 2026-11-07 |
| [LinuxForHealth FHIR (IBM)](https://github.com/LinuxForHealth/FHIR) | Apache-2.0 | (unverified) | 375 stars, **last push 2024-04-18** | (unverified) | Stalled project | — | **Reject**: inactive for 2.5 years | unverified |
| [Aidbox](https://www.health-samurai.io/aidbox) | Proprietary | (n/a) | Commercial | — | Free only for development (no PHI); production is paid ([licensing page](https://www.health-samurai.io/docs/aidbox/overview/licensing-and-support)) | — | **Reject**: not open source; cost per site | 2026-11-07 |
| [Firely Server](https://fire.ly/products/firely-server/) | Proprietary (unverified) | — | Commercial; repository not public | — | .NET | — | **Reject**: commercial | unverified |
| [FRUCtoS (HEMILLIONS)](https://jpfhir.jp/) | Proprietary freeware | (unverified) | Japanese domestic FHIR server; free version usable commercially, per jpfhir.jp | (unverified) | Unknown | Japanese vendor | **Reject** for the core; note it as a Japanese reference point | unverified |

**Validators and IG packages**

| Item | Source | Version | Verdict | Checked |
| --- | --- | --- | --- | --- |
| [HL7 FHIR validator (org.hl7.fhir.core)](https://github.com/hapifhir/org.hl7.fhir.core) | Apache-2.0, push 2026-11-06 | Maven metadata updated 2026-11-05 | **Use** (TB already validates a 1% sample at ingest) | 2026-11-07 |
| [JP Core](https://jpfhir.jp/) ([GitHub jp-core-v1x](https://github.com/jami-fhir-jp-wg/jp-core-v1x)) | JAMI / jpfhir.jp | **1.2.0 (July 2025)** on jpfhir.jp; registry has `jp-core.r4` 1.1.0 | **Use**; pin 1.2.0 from the JAMI source | 2026-11-07 |
| [TW Core IG](https://build.fhir.org/ig/TU9IVy1UV0NvcmVJRw/VFcgQ29yZSBJRyBJVFJJ/ImplementationGuide-tw.gov.mohw.twcore.html) | MOHW (衛生福利部) | `tw.gov.mohw.twcore` 1.0.0 (STU), R4 | **Use** (TB built) | 2026-11-07 |
| [HL7 FHIR-to-OMOP IG](https://hl7.org/fhir/uv/omop/INFORMATIVE1/en/) | HL7 | `hl7.fhir.uv.omop` 1.0.0, CDM v5.4 | **Use** as the mapping reference (§9) | 2026-11-07 |

**Pick:** keep HAPI as built. Run the Medplum spike later (L), not in the build steps (TB-DS-00 BD-01; ADR-14 in TB-DS-02), and switch only if it passes. Don't run two FHIR stores in production.

## 2. CQL engines

TrialBox uses CQL in two places: the v1 SCREEN path, and the compile-time equivalence gate (CQL on HAPI compared with SQL on the lake, ≥98%). The v4 cascade runs on lake SQL, so CQL is no longer on the main runtime path.

| Candidate | Licence | Latest (date) | Activity | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| [cqframework clinical_quality_language (translator + Java engine)](https://github.com/cqframework/clinical_quality_language) | Apache-2.0 | (Maven version unverified) | 338 stars, push 2026-11-05 | Reference implementation; TB uses cql-to-elm 5.4.0 | **Use** (as built, translator) | unverified |
| [cql-execution (JavaScript)](https://github.com/cqframework/cql-execution) | Apache-2.0 | 3.3.2 (npm, 2026-06-03) | 85 stars, push 2026-11-05 | Runs ELM against in-memory FHIR (with cql-exec-fhir); no server needed; same runtime as Medplum (Node) | **Evaluate**: lets the equivalence gate run without HAPI if Medplum replaces it | 2026-11-07 |
| [Blaze built-in CQL](https://github.com/samply/blaze) | Apache-2.0 | 1.13.0 | see §1 | Fast population queries, but you must load data into Blaze | **Evaluate** only if the gate needs population-scale CQL | 2026-11-07 |
| HAPI clinical-reasoning (`$evaluate`) | Apache-2.0 | ships with HAPI 8.12 | see §1 | Built | **Use** while HAPI stays | 2026-11-07 |
| Medplum CQL | — | No CQL engine found in Medplum's documentation (unverified) | — | — | Gap; covered by cql-execution | unverified |

**Pick:** keep the cqframework translator. If Medplum replaces HAPI, run the equivalence gate with cql-execution in the criteria compiler (no second FHIR server).

## 3. Terminology servers and code sets

| Candidate | Licence | Latest / activity | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [Snowstorm (SNOMED International)](https://github.com/IHTSDO/snowstorm) | Apache-2.0 (per README; GitHub shows NOASSERTION) | push 2026-11-03, 400 stars; needs Elasticsearch | Heavy for one box; SNOMED-centred | **Reject** for the box (too heavy; SNOMED licence issue below) | 2026-11-07 |
| HAPI terminology (`$expand`, `$validate-code`) | Apache-2.0 | built in | Enough for TB's ValueSets | **Use** (as built) | 2026-11-07 |
| [Blaze terminology](https://github.com/samply/blaze) | Apache-2.0 | 1.13.0 | LOINC/SNOMED ops | Evaluate only with Blaze | 2026-11-07 |
| [Ontoserver (CSIRO)](https://ontoserver.csiro.au/) | Commercial (unverified) | — | Strong, licensed per site | **Reject** (cost) | unverified |
| [tx.fhir.org](https://tx.fhir.org/) | Public HL7 server | online | Can't be used from an offline hospital box | **Reject** at runtime; use in CI only | 2026-11-07 |
| TrialBox `concept_map` + lake tables | own | built | Offline, small, deterministic | **Use** | 2026-11-07 |

**Japanese and Taiwanese code sets (licences matter more than software)**

| Code set | Owner | Licence / access | Use |
| --- | --- | --- | --- |
| 標準病名マスター (standard disease names, with ICD-10 links) | [MEDIS-DC](https://www.medis.or.jp/) | Downloadable from MEDIS-DC; redistribution terms must be checked per release (unverified) | Diagnosis mapping and 疑い (suspected) modifiers (FR-JP-*) |
| YJ / HOT drug codes | MEDIS-DC (HOT), pharmaceutical code system (YJ) | HOT master from MEDIS-DC (terms unverified) | Ingredient lookup for drug criteria |
| JLAC10 / JLAC11 lab codes | [Japan Society for Laboratory Medicine (JSLM)](https://www.jslm.org/committees/code/jlac11overview.docx) | Published by JSLM; no complete public JLAC→LOINC table was found (gap) | Lab criteria; LOINC mapping needs our own table |
| JP Core terminology (SS-MIX department codes etc.) | [jpfhir.jp terminology IG](https://jpfhir.jp/fhir/core/terminology/ig/CodeSystem-jp-department-ssmix-cs.html) | Published with JP Core | Use |
| TW Core code systems (NHI drug, ICD-10-CM/PCS Taiwan, LOINC TW) | MOHW, in TW Core IG | Published with the IG | Use (built) |
| SNOMED CT | [SNOMED International](https://docs.snomed.org/snomed-ct-practical-guides/vendor-introduction-to-snomed-ct/7-licensing) | Free only in member countries; membership of Japan and Taiwan unverified (see Key finding 3; confirm on the official member list), so an affiliate licence fee may apply | Only for OMOP export; avoid in core |
| LOINC, RxNorm, ICD-10 | Regenstrief, NLM, WHO | Free with registration (LOINC, RxNorm via UMLS), WHO ICD-10 terms | OMOP and TW Core |

**Pick:** no separate terminology server. Keep HAPI terminology plus TB's own offline maps. Get the MEDIS and JSLM terms in writing before shipping the masters inside the box.

## 4. SS-MIX2, Japanese EMRs and HL7 v2

| Candidate | Licence | Activity | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [HAPI HL7v2 (Java)](https://github.com/hapifhir/hapi-hl7v2) | MPL-1.1 / GPL dual (GitHub shows none detected; unverified) | 323 stars, push 2026-03-26; `hapi-base` 2.6.0 | Mature HL7 v2.5 parser; SS-MIX2 messages are HL7 v2.5 | **Evaluate** (JVM side) | unverified |
| [python-hl7](https://github.com/johnpaulett/python-hl7) | BSD (GitHub NOASSERTION; unverified) | 318 stars, push 2025-06-09 | Light parser; enough for ADT/OML/OUL/RDE segments | **Use** (Python ingest) | unverified |
| [nhoHQ/SSMIX2DataTestingTool](https://github.com/nhoHQ/SSMIX2DataTestingTool) | Apache-2.0 | 11 stars, last push 2015 | National Hospital Organization tool to check SS-MIX2 storage | **Use** as a reference and conformance aid, not a dependency | 2026-11-07 |
| [nhoHQ/SSMIX2_support_documents](https://github.com/nhoHQ/SSMIX2_support_documents) | none stated | push 2024-10-09 | NHO SS-MIX2 standardisation documents | **Use** as specification input | 2026-11-07 |
| [tmitanitky/ssmix2jsonizer](https://github.com/tmitanitky/ssmix2jsonizer) | none stated | 1 star, 2021 | SS-MIX2 → JSON keeping structure | **Reject** as dependency (no licence); useful to read | 2026-11-07 |
| [yuakagi/i2b2-ssmix2-etl](https://github.com/yuakagi/i2b2-ssmix2-etl) | MIT | push 2025-10-10, 0 stars | Python SS-MIX2 → i2b2 ETL | **Evaluate** as a code reference for segment handling | 2026-11-07 |
| [Medplum Agent](https://www.medplum.com/blog/july-2026-update) | Apache-2.0 | part of Medplum | On-prem HL7 v2 listener with durable queue | **Evaluate** with the Medplum spike (live HL7 feeds) | 2026-11-07 |
| SS-MIX2 → FHIR study ([Comput Methods Programs Biomed 2021](https://www.sciencedirect.com/science/article/pii/S0169260721003060)) | paper | — | Shows the mapping is done in Japan; code availability not confirmed (page did not load) | Read; unverified | unverified |
| JP-CLINS (電子カルテ情報共有サービス) | [jpfhir.jp](https://jpfhir.jp/) developer reference | IG version not stated on the site | Three documents and six data items as FHIR | **Use** as a second input when hospitals expose it | 2026-11-07 |

No maintained open-source SS-MIX2 → JP Core FHIR converter was found. TrialBox has to write its own reader (FR-ING-*). It's a bounded job: python-hl7 for parsing, the NHO documents for structure, JP Core 1.2.0 as the target.

**Pick:** python-hl7 plus our own SS-MIX2 reader, tested with the NHO testing tool's rules.

## 5. Identity and authentication

| Candidate | Licence | Latest (date) | Activity | arm64 | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [Keycloak](https://github.com/keycloak/keycloak) | Apache-2.0 | 26.8.2 (Quay/Docker, 2026-11-05) | 37.7k stars, push 2026-11-06 | amd64, arm64 | OIDC/SAML, LDAP/AD federation, TOTP/WebAuthn 2FA; Java; heavy (~1 GB RAM) | **Use** if HAPI stays (ADR-14 fallback) | 2026-11-07 |
| [Medplum auth](https://github.com/medplum/medplum) | Apache-2.0 | 5.2.15 | see §1 | yes | OAuth2/OIDC, MFA, external IdPs, access policies, all inside the FHIR server | **Use** if the Medplum spike passes | 2026-11-07 |
| [authentik](https://github.com/goauthentik/authentik) | MIT core + subscription licence for `authentik/enterprise/` ([discussion](https://github.com/goauthentik/authentik/discussions/18682)) | (unverified) | 26k stars, push 2026-11-07 | (unverified) | Good UI; enterprise code loaded in the same app | **Reject**: licence boundary is unclear for an appliance | unverified |
| [Ory Kratos](https://github.com/ory/kratos) + [Hydra](https://github.com/ory/hydra) | Apache-2.0 | (unverified) | 14k / 17.6k stars, push 2026-07-29 | (unverified) | API-only building blocks; you build the screens | **Reject**: more assembly work than Keycloak | unverified |
| [Zitadel](https://github.com/zitadel/zitadel) | **AGPL-3.0** | (unverified) | 15.5k stars, push 2026-11-04 | (unverified) | Good, but AGPL | **Reject**: AGPL in a commercial appliance (§20) | unverified |
| Console accounts (built) + trusted-header SSO | own | built | — | — | No 2FA today | Keep only until one of the above replaces it | 2026-11-07 |

**Pick:** build stage: the built console accounts and trusted-header SSO (S0). Hospital stage (H): console-native TOTP 2FA, as decided in TB-DS-00 BD-01. Later (L): Medplum auth if the spike passes, otherwise Keycloak 26 when hospital AD/SAML is wanted.

## 6. De-identification and PHI detection

| Candidate | Licence | Latest (date) | Language | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| [Microsoft Presidio](https://microsoft.github.io/presidio/) (analyzer + anonymizer) | MIT | 2.2.366 (PyPI, 2026-10-27) | Pluggable NLP engines; spaCy models per language; custom recognizers | Framework for running several detectors, merging spans and replacing them with surrogates | **Use** as the PHI-pass framework (FR-DEID-*) | 2026-11-07 |
| [GiNZA / ja-ginza](https://github.com/megagonlabs/ginza) | MIT | 5.3.0 (PyPI, 2026-09-30) | Japanese spaCy pipeline with NER (person, place, organisation) | Plugs into Presidio as the Japanese NLP engine | **Use** | 2026-11-07 |
| [MedPHINER-Llama-3.1-Swallow-8B](https://huggingface.co/sociocom/MedPHINER-Llama-3.1-Swallow-8B-Instruct-v0.5) | "other" (Hugging Face tag; terms unverified; Llama 3.1 licence applies) | updated 2026-03-21, 9 downloads | Japanese medical PHI tags: age, ID, phone, job, location, person, hospital | LLM tagger layer; no published scores | **Evaluate** (measure on MedTxt; check licence) | unverified |
| [MedNER-CR-JA (sociocom)](https://huggingface.co/sociocom/MedNER-CR-JA) | CC BY-4.0 | updated 2024-07-31 | Japanese clinical NER (medical entities, not PHI) | Useful for finding clinical terms; not a de-identifier | **Evaluate** for clinical extraction, not DEID | 2026-11-07 |
| [JMedRoBERTa](https://huggingface.co/alabnii/jmedroberta-base-sentencepiece) | **CC BY-NC-SA 4.0** | 2023-03-21 | Japanese medical BERT | Non-commercial | **Reject**: non-commercial licence | 2026-11-07 |
| [Philter (UCSF)](https://github.com/BCHSI/philter-ucsf) | BSD-3-Clause | PyPI 1.0.3 (2020); push 2024-08-20 | English rules + POS | Reference for rule design | **Reject** as a dependency (stale, English) | 2026-11-07 |
| [transformer-deid (PhysioNet)](https://physionet.org/content/transformer-deid/1.0.0/) | PhysioNet open licence (unverified) | 1.0.0 | English (i2b2/MIMIC) | Reference | **Reject** (English only) | unverified |
| [medspaCy](https://pypi.org/project/medspacy/) | MIT | 1.3.1 (2024-11-21) | English clinical context (negation) | Not for PHI | **Reject** for DEID | 2026-11-07 |
| [HanLP](https://github.com/hankcs/HanLP) | Apache-2.0 (code; check each pretrained model's terms) | 2.x, active | General Chinese NER (person, place, organisation), simplified and traditional | Candidate general zh NER under Presidio; must be measured on CGMH notes (N-07) | **Evaluate** (licence of the chosen model unverified) | unverified |
| [spaCy zh_core_web_trf](https://spacy.io/models/zh) | MIT (code); model trained on OntoNotes 5 (check terms) | spaCy 3.x | General Chinese NER, mainly simplified Chinese | Fallback zh NER; plugs into Presidio directly | **Evaluate** (traditional-Chinese accuracy unmeasured) | 2026-11-07 |
| [CKIP Transformers](https://github.com/ckiplab/ckip-transformers) | **GPL-3.0** | active | Traditional Chinese NER, strongest fit for zh-TW | Licence conflicts with bundling | **Reject** as a bundled dependency; only as a separate unmodified service with a source offer if counsel agrees (TB-DS-03 OI-8) | 2026-11-07 |
| [OpenMed privacy-filter-multilingual](https://huggingface.co/OpenMed/privacy-filter-multilingual) (v2) | Apache-2.0 | 2026 (model card; no F1 stated) | 16 languages incl. **Japanese and Chinese**, 54 PII types; fine-tuned from `openai/privacy-filter` (1.4B MoE, ~50M active); trained on synthetic data; card says CJK is the main weakness and clinical PHI is a planned separate branch | A second general detector under Presidio for JA and zh-TW | **Evaluate — bake-off 1**: run on the N-07 gate set (TB-DS-21 PHI gold) beside GiNZA and HanLP; adopt only if it adds recall | 2026-11-07 |
| [OpenMed-PII-Chinese-BigMed-Large-278M-v1](https://huggingface.co/OpenMed/OpenMed-PII-Chinese-BigMed-Large-278M-v1) (also SnowflakeMed 568M) | Apache-2.0 | 2026 | Chinese PII NER (XLM-R base), 54 types; micro-F1 0.74 on AI4Privacy + synthetic Chinese; simplified vs traditional script not stated; general PII, not clinical | Could fill the zh-TW gap in the next row, if it handles traditional script | **Evaluate** in bake-off 1 on CGMH-style synthetic notes; traditional-script accuracy must be measured | 2026-11-07 |
| Chinese / Taiwanese clinical PHI | — | No maintained open clinical PHI model found in this search | zh-TW | Gap: rules (national ID `A123456789`, NHI card, phone) + the general zh NER picked above + LLM tagger | **Build** with Presidio recognizers | 2026-11-07 |

**Pick:** Presidio as the framework, with our own rule recognizers (JP and TW identifiers), GiNZA for Japanese names and places, and an LLM tagger as the recall layer behind the rules. Lead candidate: the judge model, Gemma 4 26B-A4B, with a fixed tagging prompt, for JA, zh-TW and EN (2026-11-07 LLM survey: 93–100 % of identifiers found on 120 LLM-written synthetic notes, against 51–64 % for the regex guard; optimistic, because LLM-written notes suit LLM detectors). Comparators in bake-off 1: MedPHINER (after a licence check) and the OpenMed PII models. The pick is confirmed by the N-07 leak rate on planted spans (TB-DS-21).

## 7. Record linkage and the consortium GUID

| Candidate | Licence | Latest (date) | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [anonlink](https://github.com/data61/anonlink) + [clkhash](https://github.com/data61/clkhash) (CSIRO Data61) | Apache-2.0 | anonlink 0.15.3 (PyPI 2023-05); clkhash 0.18.3 (2023-05); repo pushes 2026-05 / 2025-05 | Bloom-filter (CLK) encoding and matching, exactly the design in TB-DS-02 | **Use**, but plan to vendor and maintain it: the releases are old | 2026-11-07 |
| [anonlink-entity-service](https://github.com/data61/anonlink-entity-service) | Apache-2.0 (unverified) | (unverified) | REST service for multi-party linkage | **Evaluate** as the consortium linkage service | unverified |
| [Splink](https://github.com/moj-analytical-services/splink) | MIT | 5.0.0 (PyPI 2026-09-28), push 2026-11-05 | Probabilistic linkage on cleartext; runs on DuckDB | **Use** inside one site (MPI de-duplication), not across sites | 2026-11-07 |
| NIH GUID tool | NIH (closed service) | (unverified) | Concept reference only | **Reject** as software | unverified |

**Pick:** clkhash encoding at each site and anonlink matching at the hub, vendored under our own tests. Splink for in-site de-duplication.

## 8. Trial matching and criteria tools (method references)

| Candidate | Licence | Activity | What to reuse | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [TrialGPT (NCBI)](https://github.com/ncbi-nlp/TrialGPT) | Public domain notice (GitHub NOASSERTION) | push 2025-01-24 | SIGIR data and prompts as the baseline (already used) | **Use** as benchmark only | 2026-11-07 |
| [Criteria2Query (OHDSI)](https://github.com/OHDSI/Criteria2Query) | Apache-2.0 | push 2026-03-01 | Criteria → OMOP cohort JSON; ideas for criteria → ATLAS export | **Evaluate** for the OMOP export path | 2026-11-07 |
| Chia corpus ([figshare 11855817](https://figshare.com/articles/dataset/Chia_Annotated_Datasets/11855817)) | CC BY 4.0 (confirmed in project 2026-11-05) | dataset | Criteria annotation for router tests (already used) | **Use** | 2026-11-07 |
| TREC Clinical Trials 2021–2023 | NIST terms | datasets | Gate sets (already used) | **Use** | 2026-11-07 |
| MedTxt (NTCIR-16 Real-MedNLP) | CC BY 4.0 | dataset | Japanese gate set (already used) | **Use** | 2026-11-07 |
| [LLM-Match (2025)](https://arxiv.org/abs/2503.13281v3) | Code and weights unverified | 2025 preprint | RAG + fine-tuned open LLM with a classification head; evaluated on n2c2, SIGIR and TREC 2021/22; reports results above TrialGPT | **Reference** (method), like TrialGPT | unverified |
| [TrialMatchAI (2025)](https://arxiv.org/pdf/2505.08508) | Zenodo record; licence unverified | 2025 | End-to-end trial recommendation with open-source LLMs | **Reference** | unverified |
| [J-ClinicalBench (LREC 2026)](https://preview.aclanthology.org/ingest-lrec/2026.lrec-main.28/) | Data licence unverified | May 2026 | Nine Japanese clinical tasks, five new datasets, 227 expert-written documents | **Use** as a Japanese evaluation set for the judge and PHI-tagger bake-offs if the licence allows | unverified |

No open project offers the whole TrialBox flow (filter-first, local, Japanese, REDCap). The references above are for benchmarks and ideas.

## 9. OMOP / OHDSI

| Candidate | Licence | Last push | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [OHDSI WhiteRabbit + Rabbit-in-a-Hat](https://github.com/OHDSI/WhiteRabbit) | Apache-2.0 | 2026-10-13 | Source profiling and mapping design | **Use** in the mapping project (not on the box) | 2026-11-07 |
| [Usagi](https://github.com/OHDSI/Usagi) | Apache-2.0 per OHDSI practice (GitHub shows none; unverified) | 2026-05-26 | Mapping local codes (標準病名, YJ, JLAC) to standard concepts | **Use** for vocabulary mapping work | unverified |
| [Achilles](https://github.com/OHDSI/Achilles) | (GitHub none; unverified) | 2026-10-09 | Characterisation of the exported CDM | **Use** on export | unverified |
| [Data Quality Dashboard](https://github.com/OHDSI/DataQualityDashboard) | (GitHub none; unverified) | 2026-10-17 | CDM quality checks | **Use** on export | unverified |
| [ATLAS](https://github.com/OHDSI/Atlas) / [WebAPI](https://github.com/OHDSI/WebAPI) | Apache-2.0 | 2026-09-16 / 2026-11-06 | Cohort tool; heavy (Java + Postgres) | **Reject** on the box; run at the research server if needed | 2026-11-07 |
| [Broadsea](https://github.com/OHDSI/Broadsea) | Apache-2.0 | 2026-05-06 | Docker bundle of ATLAS etc. | **Evaluate** for a hub-side OHDSI node | 2026-11-07 |
| [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea) | (GitHub none; unverified) | 2026-03-23 | Synthetic CDM for tests | **Use** in CI | unverified |
| [OHDSI FhirToCdm](https://github.com/OHDSI/FhirToCdm) | Apache-2.0 | 2025-01-29, 21 stars | FHIR → CDM converter (.NET) | **Reject**: low activity | 2026-11-07 |
| [NACHC fhir-to-omop](https://github.com/NACHC-CAD/fhir-to-omop) | Apache-2.0 | 2025-05-30, 12 stars | FHIR → OMOP (Java) | **Reject** as dependency; read for mapping ideas | 2026-11-07 |
| [HL7 FHIR-to-OMOP IG](https://hl7.org/fhir/uv/omop/INFORMATIVE1/en/) | HL7 | 1.0.0 | Mapping specification, CDM 5.4 | **Use** as the spec | 2026-11-07 |
| [Athena vocabularies](https://athena.ohdsi.org/) | Mixed; some need a licence (SNOMED, CPT-4) | — | Standard concepts | **Use**, with the SNOMED licence issue in §3 | 2026-11-07 |

**Pick:** our own DuckDB SQL export (lake → CDM 5.4) written to the HL7 IG, with Usagi for mappings and DQD/Achilles for checks. No ATLAS on the box.

## 10. EDC and REDCap tooling

| Candidate | Licence | Latest / activity | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [REDCap](https://projectredcap.org/) | Proprietary, free to non-profits only | LTS 16 | The hospital's EDC; we integrate | **Use** via the hospital's licence (TB-DS-02 option A) | 2026-11-07 |
| [PyCap](https://github.com/redcap-tools/PyCap) | MIT | 2.7.0 (PyPI 2025-05-05), push 2026-11-06 | Python REDCap API client | **Use** in rc-bridge | 2026-11-07 |
| [REDCapR](https://github.com/OuhscBbmc/REDCapR) | (GitHub NOASSERTION; unverified) | push 2026-09-21 | R client; reference for API edge cases | Reference only | unverified |
| REDCap mock services, e.g. [mock-redcap-service](https://github.com/Damiennsoh/mock-redcap-service) | MIT | 0 stars, 2026-10 | Toy | **Reject**; write our own simulator from the public API docs (option B) | 2026-11-07 |
| [LibreClinica](https://github.com/reliatec-gmbh/LibreClinica) | LGPL-3.0 | push 2026-11-01, 83 stars | Open EDC (OpenClinica 3 fork); a company may host it | **Evaluate** only if a sponsor demands a validated EDC we host | 2026-11-07 |
| [OpenClinica 3 CE](https://github.com/OpenClinica/OpenClinica) | LGPL per project (GitHub shows none; unverified) | push 2025-10-28 | Community edition, slower; OpenClinica 4 is commercial | **Reject** (LibreClinica is the active fork) | unverified |
| FHIR Questionnaire / SDC on the FHIR store in use (EDC-lite) | Apache-2.0 (HAPI; Medplum) | see §1 | FHIR forms with history; TB-DS-02 option C, ADR-04 | **Use** only if the L item is built (TB-DS-00 §2); HAPI by default, Medplum only if the ADR-14 spike (L) passes | 2026-11-07 |
| REDCap External Module framework | REDCap licence | docs with REDCap | Our PHP module | **Use** (thin module) | 2026-11-07 |
| [Vanderbilt REDCap FHIR Services module](https://github.com/vanderbilt-redcap/fhir-services-module) | Licence unverified | active | REDCap External Module exposing FHIR services | **Reference** for the External Module code base (L) and FR-RC-12 (L) | unverified |

**Pick:** PyCap plus our own REDCap API simulator. EDC-lite on FHIR Questionnaire/SDC on the FHIR store in use (HAPI; Medplum only if ADR-14's spike (L) passes; ADR-04). LibreClinica held in reserve.

## 11. LLM serving, structured output, quantisation, embeddings

| Candidate | Licence | Latest (date) | arm64 | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| [vLLM](https://github.com/vllm-project/vllm) | Apache-2.0 | 0.33.0 (PyPI 2026-11-02) | amd64 + arm64 image | In use; OpenAI API, guided JSON, sleep mode for swapping models, NVFP4/AWQ | **Use** (as built) | 2026-11-07 |
| [SGLang](https://github.com/sgl-project/sglang) | Apache-2.0 | 0.5.23 (2026-10-30) | amd64 + arm64 | Fast structured output, prefix caching | **Evaluate** if vLLM throughput falls short at CGMH | 2026-11-07 |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | MIT | push 2026-11-07 | yes | GGUF, low memory, weaker batching | **Evaluate** for the core-only 1×5090 mode | 2026-11-07 |
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) | Apache-2.0 (PyPI 1.2.1) | push 2026-11-07 | yes | Fastest on NVIDIA, but complex builds per model | **Reject** for now (maintenance) | 2026-11-07 |
| [Ollama](https://github.com/ollama/ollama) | MIT | push 2026-11-07 | yes | Easy, but less control over batching and schema output | **Reject** for production; fine for demos | 2026-11-07 |
| [xgrammar](https://github.com/mlc-ai/xgrammar) | Apache-2.0 | 0.2.8 (2026-09-24) | — | Grammar-constrained JSON used inside vLLM/SGLang | **Use** (via vLLM) | 2026-11-07 |
| [Outlines](https://github.com/dottxt-ai/outlines) | Apache-2.0 | 1.3.3 (2026-08-06) | — | Alternative JSON constraint backend | Fallback | 2026-11-07 |

Quantisation on Blackwell: NVFP4 is native on RTX 5090 and RTX PRO 6000. Our real-card run found one NVFP4 Gemma build bad (11/12 lost), so every quantised build must pass the gate sets (FR-MOD-*). Keep AWQ 4-bit as the alternative and GGUF for llama.cpp.

**Model pick (LLM survey 2026-11-07, report `trialbox-llm-survey/2026-11-07-open-llm-survey.md`, raw results in PR #23):** keep the pair **Gemma 4 26B-A4B** (`nvidia/Gemma-4-26B-A4B-NVFP4`, judge, also drives chat and the PHI tagger) + **Qwen3.5-9B** (`cyankiwi/Qwen3.5-9B-AWQ-4bit`, verifier, thinking off); both must agree before a note criterion excludes (D-97). 15 newer open models were screened; none beat the pair at both keeping eligible patients and catching exclusions in EN and JA. Gemma 4 + LFM2.5-24B lost fewer eligible pairs but caught half as many exclusions, is weaker on Japanese, and its licence excludes organisations over US$10M revenue. The measured hardware baseline (6 Nov 2026, RTX PRO 6000 capped to 5090 limits) used vLLM v0.32.0; the vLLM row above names the current release, and any upgrade must pass the gate sets. Medical and Japanese fine-tunes (Medical-Qwen3-Swallow, MedGemma 27B) were not testable by API and are queued for the step-5 GPU run.

**Embeddings and rerankers**

| Model | Licence | Updated | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT | 2024-07 (30M downloads) | Multilingual, in use | **Use** (built) | 2026-11-07 |
| [Ruri v3 310m (Nagoya Univ.)](https://huggingface.co/cl-nagoya/ruri-v3-310m) | Apache-2.0 | 2025-04 | Japanese retrieval | **Evaluate** against bge-m3 on MedTxt | 2026-11-07 |
| [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Apache-2.0 | 2024-06 | Multilingual reranker | **Evaluate** | 2026-11-07 |
| [Ruri v3 reranker 310m](https://huggingface.co/cl-nagoya/ruri-v3-reranker-310m) | Apache-2.0 | 2025-04 | Japanese reranker | **Evaluate** | 2026-11-07 |

**Pick:** vLLM with xgrammar, as built. Bake off Ruri v3 against bge-m3 for Japanese notes.

## 12. Document parsing and OCR (scanned referral letters, protocols)

| Candidate | Licence | Latest (date) | Japanese | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling) | MIT | 2.148.0 (2026-11-05) | Layout and tables; OCR via plug-ins | **Use** for protocols (already optional in TB) | 2026-11-07 |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Apache-2.0 | 3.7.0 (2026-06-11) | Japanese and Chinese models | **Use** for scanned letters (JA + zh-TW) | 2026-11-07 |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) (jpn, chi_tra) | Apache-2.0 | push 2026-11-02 | Usable, weaker on handwriting and vertical text | Fallback | 2026-11-07 |
| [NDLOCR (National Diet Library)](https://github.com/ndl-lab/ndlocr_cli) | CC BY 4.0 | push 2026-01-05 | Strong Japanese printed text | **Evaluate** | 2026-11-07 |
| [YomiToku](https://github.com/kotaro-kinoshita/yomitoku) | **CC BY-NC-SA 4.0; commercial use needs a paid licence** ([guideline](https://kotaro-kinoshita.github.io/yomitoku/en/commercial_use_guideline)) | 0.15.1 (2026-10-20) | Very good Japanese | **Reject** unless licensed | 2026-11-07 |

**Pick:** Docling for protocols, PaddleOCR for scans, NDLOCR as a Japanese bake-off candidate.

## 13. Data engines and object storage

| Candidate | Licence | Latest (date) | arm64 | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| [DuckDB](https://github.com/duckdb/duckdb) | MIT | 2.0.0 (PyPI 2026-10-21) | yes | Lake engine (built). Version 2.0 is a major jump; test before upgrading | **Use** (pin, test 2.0) | 2026-11-07 |
| PostgreSQL 16 | PostgreSQL licence | — | yes | FHIR store DB (built) | **Use** | 2026-11-07 |
| [MinIO](https://github.com/minio/minio) | AGPL-3.0 | **archived 2026-04-25** ([report](https://pinggy.io/blog/minio_archived_self_hosted_s3_alternatives/)) | — | No more fixes | **Reject**: replace the built component | 2026-11-07 |
| Plain filesystem (TB `objstore` filesystem backend, built) | own | built | yes | One box doesn't need S3; mirrored NVMe | **Use** (pick) | 2026-11-07 |
| [SeaweedFS](https://github.com/seaweedfs/seaweedfs) | Apache-2.0 | push 2026-11-07 | yes | S3-compatible, light | **Evaluate** if S3 is needed (hub) | 2026-11-07 |
| [RustFS](https://github.com/rustfs/rustfs) | Apache-2.0 | push 2026-11-07 | yes | S3-compatible MinIO replacement, young | **Evaluate** (young) | 2026-11-07 |
| [Garage](https://garagehq.deuxfleurs.fr/) | AGPL-3.0 | v2.5.0 (Docker 2026-10-24) | (unverified) | Light S3 | **Reject** (AGPL) | unverified |
| Ceph | LGPL (unverified) | push 2026-11-06 | yes | Far too heavy | **Reject** | unverified |

**Pick:** drop MinIO and use the built filesystem object store. Use SeaweedFS only where S3 is really needed.

## 14. Workflow and scheduling

| Candidate | Licence | Latest (date) | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| TrialBox SQLite job queue (built, 4 workers, fast lane) | own | built | Deterministic, byte-identical re-runs, audited | **Use** | 2026-11-07 |
| [Temporal](https://github.com/temporalio/temporal) | MIT | push 2026-11-07 | Durable workflows; extra server + DB | **Reject** (too much to run on one box) | 2026-11-07 |
| [Prefect](https://github.com/PrefectHQ/prefect) | Apache-2.0 | 3.9.2 (2026-11-06) | Python flows, UI | **Reject** (lean) | 2026-11-07 |
| [Dagster](https://github.com/dagster-io/dagster) | Apache-2.0 | 1.13.29 (2026-11-05) | Data assets, lineage | **Reject** (lean) | 2026-11-07 |
| systemd timers / cron | — | — | Night window triggers | **Use** for scheduling the batch | 2026-11-07 |

**Pick:** keep the built queue. Add a small scheduler for the 22:00–06:00 window and the GPU model swap.

## 15. Mail

| Candidate | Licence | Latest / activity | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| Hospital mail server via SMTP/IMAP (built) | — | — | The box is a client; no mail server on the box | **Use** | 2026-11-07 |
| [Postfix](https://www.postfix.org/) + [Dovecot](https://www.dovecot.org/) | IPL/EPL; MIT/LGPL (unverified) | mature | Only if a site has no mail server | Fallback | unverified |
| [Stalwart](https://github.com/stalwartlabs/mail-server) | **AGPL-3.0 + proprietary SELv2** | weekly releases; Docker 2026-11-04, amd64/arm64 | Modern all-in-one | **Reject** (AGPL) | 2026-11-07 |
| [GreenMail](https://github.com/greenmail-mail-test/greenmail) | Apache-2.0 | push 2026-11-05 | Test IMAP/SMTP (built in test profile) | **Use** in tests | 2026-11-07 |
| [Mailpit](https://github.com/axllent/mailpit) | MIT | push 2026-11-07 | Maintained MailHog replacement | **Use** in tests | 2026-11-07 |
| [MailHog](https://github.com/mailhog/MailHog) | MIT | **last push 2024-02-13** | Stale | **Reject**: replace with Mailpit | 2026-11-07 |

**Pick:** the box stays a mail client of the hospital server. Replace MailHog with Mailpit in tests.

## 16. Observability and backup

| Candidate | Licence | Activity | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- | --- |
| [Prometheus](https://github.com/prometheus/prometheus) | Apache-2.0 | push 2026-11-06 | Metrics for the health page | **Use** | 2026-11-07 |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector) | Apache-2.0 | push 2026-11-07 | Traces/metrics pipeline | **Evaluate** (only if needed) | 2026-11-07 |
| [Grafana](https://github.com/grafana/grafana) | **AGPL-3.0** | push 2026-11-07 | Dashboards | **Evaluate**: fine unmodified for internal use; don't modify or embed it (§20) | 2026-11-07 |
| [Loki](https://github.com/grafana/loki) | **AGPL-3.0** | push 2026-11-07 | Logs | **Reject**: plain JSON log files + diagnostics bundle are enough | 2026-11-07 |
| [Uptime Kuma](https://github.com/louislam/uptime-kuma) | MIT | push 2026-11-07 | Simple up/down checks | **Evaluate** for hub-side checks | 2026-11-07 |
| [restic](https://github.com/restic/restic) | BSD-2-Clause | push 2026-11-06 | Encrypted, deduplicated backup | **Use** | 2026-11-07 |
| [BorgBackup](https://github.com/borgbackup/borg) | BSD-3 (GitHub NOASSERTION) | push 2026-11-06 | Alternative | Fallback | 2026-11-07 |

**Pick:** Prometheus plus our own health page (no Grafana needed in the box), and restic for backups.

## 17. Supply chain and security tooling (CI)

| Candidate | Licence | Activity | Use |
| --- | --- | --- | --- |
| [cosign (Sigstore)](https://github.com/sigstore/cosign) | Apache-2.0 | push 2026-11-05 | Sign images and the offline bundle; verify on the box with a pinned key (no internet) |
| [Syft](https://github.com/anchore/syft) | Apache-2.0 | push 2026-11-07 | SBOM per release |
| [Grype](https://github.com/anchore/grype) | Apache-2.0 | push 2026-11-07 | Vulnerability scan of the SBOM |
| [Trivy](https://github.com/aquasecurity/trivy) | Apache-2.0 | push 2026-11-06 | Image, config and secret scanning (pick one of Grype/Trivy; Trivy covers more) |
| [OpenSSF Scorecard](https://github.com/ossf/scorecard) | Apache-2.0 | push 2026-11-07 | Score our dependencies' project health |

Test and build toolchain for the browser walk, PDFs and the REDCap module (review M-22). Versions are pinned in the repo lock files; licences are from each project's repository and still to be confirmed in the SBOM licence report (NFR-COMP-07).

| Candidate | Licence | Use in TrialBox | Verdict | Checked |
| --- | --- | --- | --- | --- |
| [Playwright](https://github.com/microsoft/playwright) | Apache-2.0 | Browser walk (TB-DS-04 §3.5), already used (PR #20) | **Use** (built) | 2026-11-07 |
| [axe-core](https://github.com/dequelabs/axe-core) + `@axe-core/playwright` | MPL-2.0 | Accessibility checks inside the browser walk (WCAG 2.2 AA, TB-DS-09) | **Use** (test only, not shipped) | 2026-11-07 |
| [WeasyPrint](https://github.com/Kozea/WeasyPrint) | BSD-3-Clause | HTML → PDF for feasibility reports and consent explainers, with embedded CJK fonts | **Evaluate** against the PDF renderer already in the repo; keep one | 2026-11-07 |
| [Noto Sans CJK](https://github.com/notofonts/noto-cjk) | SIL OFL-1.1 | JA and zh-TW fonts embedded in PDFs | **Use** | 2026-11-07 |
| [PHPUnit](https://github.com/sebastianbergmann/phpunit) | BSD-3-Clause | Unit tests of the REDCap External Module (L) | **Use** (test only) | 2026-11-07 |
| [PHPStan](https://github.com/phpstan/phpstan) | MIT | Static analysis of the module | **Use** (CI) | 2026-11-07 |
| [PHP_CodeSniffer](https://github.com/PHPCSStandards/PHP_CodeSniffer) | BSD-3-Clause | Coding standard for the module | **Use** (CI) | 2026-11-07 |

**Pick:** cosign + Syft + Trivy in CI, all **Use**; Playwright + axe-core for the browser walk, one PDF renderer, PHPUnit + PHPStan for the module.

## 18. Chat-style UI

TrialBox's chat is a fixed-command box (FR-CHAT-*). It needs no chat framework. The command parser is the existing mail-subject grammar, and the answer renders the normal page.

| Candidate | Licence | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- |
| Existing console (server-rendered HTML) + a small input component | own | Matches the fixed-command design | **Use** | 2026-11-07 |
| [OpenMausBot](https://github.com/milind-soni/OpenMausBot) | Apache-2.0 (+ source-available `enterprise/`) | Pattern for Allow/Deny approval cards only | **Reject** as a dependency; reuse the idea | 2026-11-07 |
| Medplum React components | Apache-2.0 | Forms and patient widgets for EDC-lite | **Evaluate** only if the ADR-14 spike (L) adopts Medplum | 2026-11-07 |

## 19. Adjacent and competing projects (reference)

| Project | Type | Relevance |
| --- | --- | --- |
| [Lind (lind.care)](https://www.hcinnovationgroup.com/analytics-ai/artifical-intelligence-machine-learning/news/55380471/advocate-health-partners-with-startup-lind-on-clinical-trial-matching) | Commercial, EHR-embedded screening; Lind Asia with PREMIA | Main competitor; reports criterion agreement (94%) |
| [TrialGPT](https://github.com/ncbi-nlp/TrialGPT) | Open method | Our accuracy baseline |
| [OHDSI](https://www.ohdsi.org/) ATLAS / Criteria2Query | Open | Feasibility on OMOP; criteria → cohorts |
| [i2b2](https://www.i2b2.org/) / [Leaf](https://github.com/uwrit/leaf) | Open cohort discovery | Overlaps our feasibility; not reused |
| University of Kentucky REDCap-LLM framework ([arXiv 2512.13700](https://arxiv.org/pdf/2512.13700v1)) | Research | Same pre-fill loop; confirms design and limits |
| [Medplum](https://www.medplum.com/) | Open platform | Candidate core (§1, §5, §10) |

---

## 19a. Synthetic patient generators (for the synthetic hospital, TB-DS-21)

| Candidate | Licence | Fit | Verdict | Checked |
| --- | --- | --- | --- | --- |
| [Synthea](https://github.com/synthetichealth/synthea) and its disease modules | Apache-2.0 | Structured synthetic patients at scale with FHIR and CSV output; already used once (`tools/synthea_ad_cohort.py`). No Japanese or Taiwanese module: names, codes, 和暦 / 民國 dates, 保険病名 and notes need TrialBox's own layer | **Evaluate — bake-off 2**: Synthea for the structured half of the 500,000-patient hospital versus extending `tools/synth`; keep TrialBox's own generator for JA / zh-TW notes, identifiers and planted PHI either way | 2026-11-07 |
| TrialBox `tools/synth` (own) | Project code | Deterministic, planted truth, the landing tables the ingest reads; zh-TW notes only today | **Use** and extend (TB-DS-21) | 2026-11-07 |

## 20. Recommended stack

| Layer | As built | Recommended | Change |
| --- | --- | --- | --- |
| FHIR store | HAPI JPA 8.12 + Postgres 16 | HAPI (S0); Medplum 5.2 later only if the spike passes | Spike (L) |
| CQL | cqframework translator + HAPI `$evaluate` | Same; cql-execution if HAPI goes | Conditional |
| Validation / IGs | HL7 validator, TW Core 1.0.0 | Add JP Core 1.2.0 (JAMI source) | Add |
| Terminology | HAPI + TB concept maps | Same; MEDIS/JSLM masters offline | Add masters |
| SS-MIX2 / HL7 v2 | none | python-hl7 + own reader | New |
| Identity | Console accounts + trusted-header SSO | S0: console accounts; H: + TOTP; L: Medplum auth if adopted, else Keycloak 26 | New |
| PHI detection | `phi_guard` regexes | Presidio + GiNZA + own JP/TW recognizers + LLM tagger | New |
| Linkage | HMAC pid, MPI | + clkhash/anonlink (consortium), Splink (in-site) | New |
| OMOP | none | Own DuckDB export to the HL7 IG; Usagi, DQD, Achilles | Optional |
| REDCap | none | PyCap + own simulator + thin External Module | New |
| EDC-lite | none | FHIR Questionnaire/SDC on the FHIR store in use: HAPI, or Medplum only if ADR-14's spike (L) passes (ADR-04) | New (L, TB-DS-00 §2) |
| LLM serving | vLLM | vLLM 0.33 + xgrammar; SGLang as alternative | Keep |
| Embeddings | bge-m3 | bge-m3; Ruri v3 bake-off | Evaluate |
| OCR / parsing | Docling (optional) | Docling + PaddleOCR; NDLOCR bake-off | Add |
| Object store | **MinIO (archived)** | Filesystem store (built backend); SeaweedFS if S3 needed | **Replace** |
| Lake | DuckDB | DuckDB (test 2.0 before upgrade) | Pin |
| Jobs | SQLite queue | Same + night scheduler | Keep |
| Mail | Hospital SMTP/IMAP; GreenMail/MailHog in tests | Same; Mailpit replaces MailHog | Replace test tool |
| Observability | audit chain, logs | Prometheus + own health page | Add |
| Backup | none documented | restic | Add |
| Supply chain | `make_bundle.sh` | cosign + Syft + Trivy | Add |

### Licence notes for a commercial on-prem appliance

- **Permissive (Apache-2.0, MIT, BSD):** almost the whole recommended stack. Keep the NOTICE and licence files in the bundle and list them in the SBOM.
- **AGPL-3.0 (Zitadel, Stalwart, Grafana, Loki, Garage, MinIO):** AGPL obligations apply when you distribute the software or let users reach a modified version over a network. TrialBox is shipped to hospitals as an appliance, which is distribution. Shipping an unmodified AGPL component means offering its source, which is manageable. Modifying it means publishing our changes. The recommendation avoids AGPL components entirely. Grafana is the only one left as "evaluate", and it would be used unmodified.
- **LGPL (LibreClinica, OpenClinica 3):** fine as a separate, unmodified service.
- **Non-commercial or paid (JMedRoBERTa, YomiToku, Aidbox, Firely, Ontoserver):** excluded.
- **Model licences:** Gemma 4 (Apache-2.0, as listed on Hugging Face for `google/gemma-4-26B-A4B-it`, checked 2026-11-07; earlier Gemma generations used the Gemma terms), Qwen3.5-9B (Apache-2.0, checked 2026-11-07), Llama 3.1 (Llama licence, which MedPHINER inherits), other Qwen sizes (check per model), MedGemma (Health AI Developer Foundations terms). Each pinned model needs its licence recorded with the model gate result.
- **Data and code sets:** SNOMED CT needs an affiliate licence outside member countries. MEDIS and JSLM masters: get the redistribution terms in writing.
- **REDCap:** never ship, copy or name-brand REDCap code. The External Module is our own code, installed by the hospital.

### What not to adopt, and why

| Item | Reason |
| --- | --- |
| MinIO | Archived April 2026; no security fixes |
| MailHog | Unmaintained since February 2024 |
| LinuxForHealth FHIR | No activity since April 2024 |
| Zitadel, Stalwart, Garage, Loki | AGPL in an appliance |
| authentik | Enterprise code under a subscription licence inside the same app |
| JMedRoBERTa | Non-commercial licence |
| YomiToku | Commercial use needs a paid licence |
| Aidbox, Firely, Ontoserver | Paid per site; not open source |
| Temporal, Prefect, Dagster | Too much to run and maintain for one engineer |
| Snowstorm, ATLAS on the box | Heavy; belong on a research server, if anywhere |
| TensorRT-LLM | Per-model engine builds add maintenance for little gain at our load |

### Items to verify in a spike

1. **Medplum 5.2:** load JP Core 1.2.0 and TW Core 1.0.0 profiles, bulk-import 500,000 synthetic patients, MFA, OIDC federation to AD/SAML, access policies by study, Questionnaire for EDC-lite. Check whether any CQL support exists.
2. **cql-execution:** run the existing equivalence gate (≥98%) without HAPI.
3. **Presidio + GiNZA + MedPHINER:** measure the leaked-PHI rate on MedTxt with planted identifiers; confirm MedPHINER's licence terms.
4. **anonlink/clkhash:** they still install and pass tests on Python 3.12/3.13 (releases date from 2023); kana-name normalisation; false-match rate on synthetic consortium data.
5. **Filesystem object store** replacing MinIO in every compose file and in the CI bundle.
6. **DuckDB 2.0:** lake rebuild and SQL rulesets unchanged (byte-identical outputs).
7. **Ruri v3 against bge-m3** on Japanese notes; NDLOCR and PaddleOCR on sample referral letters.
8. **MEDIS and JSLM licence terms** for bundling the masters; **SNOMED** status for Japan and Taiwan in 2026.
9. **HAPI HL7v2 licence** (MPL/GPL dual) if the JVM parser is chosen over python-hl7.
10. **JP-CLINS IG version** and whether the head hospital exposes it.

## References

- ISO/IEC 5230:2020 (OpenChain) — licence-compliance programme fields used for the licence notes.
- SPDX License List (spdx.org/licenses) — licence identifiers.
- Sources of each fact: GitHub search API, PyPI, npm, Maven Central, Docker Hub, Quay, packages.fhir.org, Hugging Face, read on 2026-11-07 (see "How the facts were checked").
- Shared terms: TB-DS-01 Appendix C.

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-11-07 (seq 1) | Claude | First issue (TB-OSS-05). |
| 0.2 | 2026-11-07 (seq 2) | Claude | Renamed TB-DS-05; companion IDs updated; identity, FHIR store and EDC-lite picks aligned to TB-DS-00 BD-01 (pilot HAPI + console TOTP, Medplum M2); MinIO replacement per BD-09; Mailpit per BD-09. |
| 0.2a | 2026-11-07 (seq 3) | Claude | TB-REV-006b: EDC-lite pick is FHIR Questionnaire/SDC on the FHIR store in use, HAPI by default (ADR-04, ADR-14; R2-06); ADR-06 references replaced; SNOMED membership no longer cited from Wikipedia, marked unverified with official sources (F-52); zh-TW NER rows HanLP, spaCy zh, CKIP (F-38); test and build toolchain rows (M-22). |
| 0.2b | 2026-11-07 (seq 4) | Claude | TB-REV-006d D-14: EDC-lite build status tagged C. |
| 0.2c | 2026-11-07 (seq 5) | Claude | TB-REV-006e E-06: EDC-lite pick row follows the C tag. |
| 0.3 | 2026-11-07 (seq 6) | Claude | TB-REV-006f F6-16: OpenMed multilingual and Chinese PII models (bake-off 1), LLM-Match, TrialMatchAI, J-ClinicalBench, Vanderbilt REDCap FHIR Services module, new §19a synthetic generators with Synthea (bake-off 2). No pick changes. |
| 0.4 | 2026-11-07 (seq 7) | Claude | TB-REV-006g Q-18, Q-22, S-06, S-08: H1 in ID form; evaluation criteria stated before the verdicts; Checked column on every candidate table (date read, or unverified); References section; sequence numbers on this history. |
| 0.5 | 2026-11-07 (seq 8) | Claude for Aimedics | TB-REV-006g §R R-24: picks and stack in S0–S5 / H / L terms; TB-REV-006f §8 L8-06, L8-11: model pick from the 2026-11-07 LLM survey, Gemma 4 and Qwen3.5-9B licences Apache-2.0, Gemma 4 as lead PHI-tagger candidate with MedPHINER / OpenMed comparators. |
