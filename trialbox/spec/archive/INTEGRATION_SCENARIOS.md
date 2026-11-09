# TrialBox — Hospital integration requirements catalogue (Japan and Taiwan, Alzheimer's focus)

Date: 2026-11-05. Author: clinical-informatics / regulatory requirements analysis (read-only review of
`/home/user/Auto-GPT/trialbox` at the current working tree, plus `/mnt/project-files/trialbox-role-redesign/DESIGN.md` §1, §7, §8).

Owner's brief (verbatim): *"And for it integration to the hospital as an option, there are many compliance, in some
scenario, fully hospital IT EMR integration, PI patient database, consortium, each manual input, you need to consider
all possible scenarios, apart from the main themes, so to find all possible requirements."*

How to read this document:
- §0 is the vocabulary and the common baseline every scenario inherits.
- §A–§F are the scenarios. Each has: data flow, operator, legal basis and consent, compliance, technical, operational,
  what TrialBox already does (file paths), gaps, effort, risks.
- §G is the cross-scenario matrix, §H the ranked gap list with build items, §I the questions for the owner.
- "**needs legal review**" marks a legal interpretation I am not sure of. Dates and article numbers were checked against
  the cited sources on 2026-11-05 unless marked *(from memory; verify)*.
- Effort is in engineer-weeks for one engineer who knows the codebase, excluding hospital-side work and legal work.

---

## 0. Common baseline (inherited by every scenario)

### 0.1 Vocabulary

| Term | Meaning here |
| --- | --- |
| Box | One TrialBox appliance (Docker compose project), on hospital premises unless the scenario says otherwise (`docs/ARCHITECTURE.md` §1). |
| D0–D4 | v4 data classes: D0 public → D4 directly identifying clinical data (`spec/v4/05_data_platform_model_privacy.md` §7.1). |
| pid | HMAC pseudonym of the MRN; reverse map only inside the box, AES-GCM (`services/adapter/pidmap.py`, `services/dataplat/mpi/__init__.py`). |
| Pre-screening | Reading records *before* consent to find candidates. Legally the most sensitive step in every scenario. |
| Feasibility | Aggregate counts only (small cells suppressed). Lower risk, but still secondary use of clinical data. |

### 0.2 Regulatory baseline for the product itself (both countries)

| Area | Requirement | Status in repo |
| --- | --- | --- |
| Intended use | Not a medical device: investigator decides eligibility; box never diagnoses (`SPEC_v3.md` §2.4). Every report carries the statement. | Spec'd; report footers exist (`DESIGN.md` §7). |
| GCP computerised system | ICH E6(R3) (adopted Jan 2025) Annex 1 data governance: validation proportional to risk, audit trail, record (not document) integrity, oversight of service providers. [Sidley summary](https://www.sidley.com/en/insights/newsupdates/2025/02/international-council-finalizes-modernized-global-good-clinical-practice-guideline). | Audit hash chain (`libs/tb_common/audit.py`), deterministic re-runs (D-82), `tools/acceptance.py`. Validation plan is a document gap, not code. |
| Part 11 / Annex 11 | Relevant **only** if the box's records become trial source or regulated records (e.g. screening log exported to the TMF, eligibility sheet signed by the PI). Pre-screening lists and feasibility packs are usually *not* regulated records (**needs legal review**, sponsor-dependent). | Lightweight approval, explicitly not an e-signature (D-88, `docs/CONSENT.md`). |
| ISO/IEC 27001:2022 + ISO 27799 | Expected by hospital IT procurement in both countries; ISO 27799 is the health-sector control guidance for 27001 ([ISO 27799](https://www.iso.org/standard/62777.html)). Taiwan's EMR regulation requires an outsourced EMR-system contractor to hold a certified information-security standard (see §A.4 Taiwan). | Vendor certificate is an organisational item (spec v4 §14 MS6). |
| HL7/FHIR security | Bulk Data + SMART Backend Services (private_key_jwt, short-lived tokens, `system/*.rs` scopes) ([Bulk Data IG authorization](https://hl7.org/fhir/uv/bulkdata/STU1.0.1/authorization/index.html)). | Spec'd in v4 §5.6.4; `fhir_bulk` source reads NDJSON from disk only (`services/adapter/sources/fhir_bulk/source.py`). No SMART client. |

### 0.3 Japan: the five frameworks that apply to every Japanese scenario

| Framework | What it requires of a box in a hospital | Source |
| --- | --- | --- |
| **APPI 個人情報保護法** (2020 amendment in force Apr 2022; 2021 amendment unified public hospitals/universities under the PPC from Apr 2022/2023) | Medical data is 要配慮個人情報: acquisition needs consent unless an exception applies. Purpose limitation (Art. 18), third-party provision (Art. 27) with academic-research exceptions (Arts. 18/20/27) for institutions doing academic research, but "not where it unduly infringes rights". **仮名加工情報** (pseudonymised information): internal analysis only, no third-party provision, **no contacting the person** — so a pseudonymised dataset can support feasibility but *not* recruitment. Mandatory leak reports to the PPC for sensitive data (preliminary ≈3–5 days, final 30/60 days). | [PPC slides via MHLW](https://www.mhlw.go.jp/content/10904750/000863622.pdf); [PPC medical/care guidance](https://www.ppc.go.jp/personalinfo/legal/iryoukaigo_guidance/) |
| **Ethical Guidelines for Life-Science and Medical Research Involving Human Subjects 生命・医学系指針** (2023 amendment, in force 1 Jul 2023) | Research use of existing information (既存情報) without new consent via **opt-out** when "the research cannot practically be conducted without the existing data", with notice/easy access to information, institution-head duties (web page), ethics-committee review. Anonymised or existing pseudonymised information needs no IC. Overseas provision needs destination-country disclosure. | [MHLW/MEXT/METI 2023 amendment explanation](https://www.mhlw.go.jp/content/001087960.pdf) |
| **MHLW Guidelines for Security Management of Medical Information Systems 安全管理GL** v6.0 (May 2023) → **v7.0 (June 2026)** | Medical Care Act Enforcement Ordinance Art. 14(2) obliges institutions to follow the latest version. v7.0: **two-factor authentication mandatory from FY2027 (1 Apr 2027)** for terminals and servers; password reuse prohibited, account lockout, periodic change removed; vendor responsibility split and risk communication; supply-chain risk; "maintenance-outsourcing" edition for small institutions; cloud encouraged. | [MHLW v7.0 overview slides, 29 May 2026](https://www.mhlw.go.jp/content/10808000/001102596.pdf) |
| **MIC/METI guideline for providers** 医療情報を取り扱う情報システム・サービスの提供事業者における安全管理ガイドライン **v2.0 (28 Mar 2025)** | The vendor (us) must do a risk assessment, publish a service specification and SLA (MDS/SDS reference example attached to the guideline), agree a 責任分界 (responsibility split) with the hospital, and have incident procedures. Together with the MHLW GL these are the "2省GL" hospitals ask vendors to attest to. | [MIC press release and PDF](https://www.soumu.go.jp/menu_news/s-news/01ryutsu06_02000427.html); [METI PDF](https://www.meti.go.jp/policy/mono_info_service/healthcare/01gl_20250328.pdf) |
| **Next-Generation Medical Infrastructure Act 次世代医療基盤法** (2023 amendment, in force 2024) | Creates **仮名加工医療情報** supplied by hospitals to *certified* creators and used by *certified* users; hospital must notify patients in advance (separate notice for pseudonymised use), allow opt-out (≈30-day wait), keep provision records. Relevant only when a hospital's data route to research goes through a certified operator (e.g. a consortium that is a certified user). A single hospital running its own pre-screening is *outside* this Act. | [Cabinet Office leaflet for medical institutions](https://www8.cao.go.jp/iryou/kouhou/pdf/kaisei_jisedaiiryou_iryoukikan.pdf) |

When the data is used **in a 治験** (GCP trial): J-GCP (GCP省令, MHLW Ordinance 28 of 1997, [e-Gov](https://elaws.e-gov.go.jp/document?lawid=409M50000100028) *(URL from memory; verify)*) and the **ER/ES guidance** (薬食発第0401022号, 1 Apr 2005) plus the 2014 notice on electronic trial documents apply if the box's output becomes a trial record ([Kobe University SOP listing these](https://www.hosp.kobe-u.ac.jp/ctrc/client/sop/denjika_sop_20240901.pdf)). The pre-screening itself is done under the PI's delegation; the SMO CRC acts on the delegation log (`DESIGN.md` §1.4).

### 0.4 Taiwan: the six frameworks that apply to every Taiwanese scenario

| Framework | What it requires | Source |
| --- | --- | --- |
| **PDPA 個人資料保護法** (2023 amendment: PDPC as competent authority, fines up to NT$15 M; **2025 amendment promulgated 11 Nov 2025, effective date pending**) | Art. 6: medical, genetic, health-examination data are special data; collection/use only on the listed exceptions, including academic research by a medical/academic institution *when the data, after processing by the provider or as disclosed by the collector, cannot identify the data subject* (**needs legal review** on whether pre-screening with re-identification can ever rest on this exception; I believe it cannot, so the basis must be the institution's statutory/medical-care purpose plus IRB-approved research with consent or waiver). Breach notification to data subjects and (for reportable incidents) the authority (Art. 12 as amended). Cross-border transfer restrictable. | [Chambers 2025 guide](https://practiceguides.chambers.com/practice-guides/data-protection-privacy-2025/taiwan); [Jones Day on the 2025 amendment](https://www.jonesday.com/de/insights/2025/12/taiwan-passes-major-amendments-to-the-personal-data-protection-act); statute [law.moj.gov.tw I0050021](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=I0050021) *(URL from memory; verify)* |
| **Human Subjects Research Act 人體研究法** | Art. 5 IRB approval before research; Art. 12–14 informed consent (content, no coercion); Art. 19 non-de-linked (非去連結) data destroyed after study unless consent or de-linked; new review and consent for use beyond original consent; overseas transfer of non-de-linked data needs written consent + IRB + MOHW. Exemptions and consent waivers only in MOHW-announced categories (2012 announcement: public/non-identifiable, publicly available data, minimal-risk, etc.). | [law.moj.gov.tw L0020176](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020176); [NYCU IRB SOP reproducing the exemption announcement](https://irb.nycu.edu.tw/userfiles/irbch/files/20230930121740655.pdf) |
| **Human Biobank Management Act 人體生物資料庫管理條例** | Applies when the source is a licensed biobank (samples + data): biobank governance, ethics committee, de-linking/encryption, participant consent scope. Relevant to §B (memory-clinic cohorts with biobank samples) and §F (biomarker feeds). | [English text (TMU)](https://ohr.tmu.edu.tw/upload/download_files/172759407119.%20Human%20Biobank%20Management%20Act人體生物資料庫管理條例.pdf) |
| **Medical Care Act 醫療法 + Regulations on Electronic Medical Records 醫療機構電子病歷製作及管理辦法** (amended 18 Jul 2022) | Six management mechanisms (SOP, access control, emergency response, system security incl. backup, encrypted transmission, incident handling), records kept ≥ 5 years; security incidents affecting patients reported to the local authority **within 72 h**; e-signature within 24 h of record creation; **full audit log of every access/copy/transfer for the whole retention period**; outsourced system contractor must hold a **certified information-security standard** and a written contract filed with the authority within 15 days; **cloud: data stored in Taiwan** unless approved; cross-institution exchange needs patient consent. Medical Care Act Art. 70 (7-year record retention) and Art. 72 (confidentiality) *(from memory; verify)*. | [law.moj.gov.tw L0020121](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020121) |
| **Cyber Security Management Act 資通安全管理法** (2025 amendment) + MOHW hospital cyber programme | Medical centres designated critical infrastructure: responsibility levels, CISO, EDR, H-SOC, incident reporting, outsourcing supervision; MOHW adding cyber governance to hospital accreditation (press release 15 Aug 2025). Exact obligations per hospital level: **needs legal review** against the MODA regulations. | [MOHW press release 2025-08-15](https://mohw.gov.tw/cp-7175-83515-1.html) |
| **IRB / TFDA GCP** 藥品優良臨床試驗作業準則 | Trial pre-screening and screening logs are investigator responsibilities under GCP; IRB must approve the recruitment method (including any EMR search) in the protocol/consent documents. | [MOHW on GCP and TFDA inspection](https://www.mohw.gov.tw/fp-16-76653-1.html); statute [law.moj.gov.tw L0030056](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030056) *(URL from memory; verify)* |

Plus the **Constitutional Court judgment 111年憲判字第13號 (12 Aug 2022)**: secondary use of NHI data without an independent supervisory mechanism and without a withdrawal right is unconstitutional; a draft 衛生福利資料管理條例 is pending. Any plan that touches NHI-sourced data (MediCloud, claims) must assume an opt-out right ([judgment PDF](https://cons.judicial.gov.tw/download/download.aspx?id=473975); [commentary on the draft act](https://www.twreporter.org/a/opinion-act-on-health-and-welfare-data)).

### 0.5 Baseline technical controls the repo already has (cited once, reused below)

| Control | Where |
| --- | --- |
| Deny-by-default egress per container, `trialbox-net` internal | `deploy/docker-compose.yml`, `deploy/network.sh`, `deploy/egress.py`, `docs/HARDENING.md` §3 |
| Offline signed install/updates, no telemetry | `deploy/install.sh`, `tools/apply_update.sh`, `tools/sign_bundle.py` |
| LUKS2 + TPM, swap off, TPM-sealed keys | `docs/HARDENING.md` §1–2, `deploy/check_host.sh` |
| Pseudonymisation, MPI with A40 merges, AES-GCM reverse map | `services/dataplat/pseudonymise/`, `services/dataplat/mpi/`, `services/adapter/pidmap.py` |
| Immutable landing, contracts, DQ, publish gate (HOLD keeps last snapshot) | `services/dataplat/landing/zone.py`, `services/dataplat/contracts/demo_his/*.yaml`, `services/dataplat/dq/`, `services/dataplat/pipeline.py` |
| Append-only hash-chained audit, 10-year retention | `libs/tb_common/audit.py`, `tools/audit_verify.py`, `docs/HARDENING.md` §5 |
| Small-cell suppression, aggregate-only routing to external recipients | `libs/tb_common/smallcell.py`, `libs/tb_common/routing.py`, `services/orchestrator/scenarios/feas.py` |
| Console roles (admin/coordinator/investigator/viewer/cro), affiliation (hospital/smo/cro), study scope, expiry, SSO trusted header behind reverse proxy, scrypt, lockout, 30-min idle | `services/console/auth.py`, `services/console/app.py` (D-93, D-104) |
| Retention settings (attachments 90 d, outputs 365 d, logs 180 d, 3 nightly + 36 month-end snapshots) | `schemas/settings.schema.json` `retention`, `libs/tb_common/retention.py` |
| PHI guard before any cloud model; cloud model off by default | `libs/tb_common/phi_guard.py`, `settings.models.cloud_enabled` |
| Candidate registry (screening log) with events; XLS promotion; CASE single-chart sheet | `services/orchestrator/candidates.py`, `services/orchestrator/scenarios/case.py` (D-91, D-92) |
| Data-honesty labels on every report | `DESIGN.md` §7 |

Known baseline gaps that every scenario inherits (detailed in §H): no 2FA in the console (MHLW v7.0 requires it from FY2027; `SPEC_v3.md` SEC-3 promises TOTP but `services/console/auth.py` has none); no erasure/tombstone implementation (spec v4 §5.14.4 only; no code found); no Japanese terminology loaders (MEDIS, JLAC10, HOT); no validation package (IQ/OQ/PQ) in the repo.

---

## A. Full hospital IT / EMR integration

### A.1 Variants

| Variant | Japan | Taiwan |
| --- | --- | --- |
| A1 Read-only replica / DWH views (SQL) | Common at university hospitals with a DWH; vendor EMRs (Fujitsu HOPE LifeMark-HX, NEC MegaOak-HR, SSI/ソフトウェア・サービス, CSI/IBM MIRAIs) expose data mainly through **SS-MIX2** and vendor DWH products, rarely through a raw DB account. | Common: HIS on Oracle/MSSQL/Db2 with DBA-made views; research DWH (CGRD-type at CGMH, NTUH-iMD, etc.). |
| A2 HL7 v2 feeds (ADT/ORU/SIU/MDM) via interface engine | ADT/ORU exist inside SS-MIX2 gateways; **SIU scheduling is rarely available** — appointment data usually comes from the 予約システム table or the SS-MIX2 ADT-12 reception event. | Interface engines (Mirth/OIE, vendor) exist at medical centres; SIU less common than ADT/ORU. |
| A3 FHIR R4 APIs | **JP Core** profiles; the national 電子カルテ情報共有サービス (3文書6情報: referral letter, discharge summary, check-up report; labs, infections, prescriptions, diagnoses, two allergy types) is FHIR-based but is a *care-sharing* network accessed through オンライン資格確認 — **not a research API**; nationwide operation targeted around winter FY2026 ([MHLW](https://www.mhlw.go.jp/content/10808000/001608497.pdf)). | **TW Core IG** (`tw.gov.mohw.twcore`; repo pins 1.0.0; check [history page](https://twcore.mohw.gov.tw/ig/twcore/history.html) for the current release) — hospital FHIR facades exist at large centres for MOHW exchange projects; Bulk `$export` rarely enabled. |
| A4 SS-MIX2 standardised storage (Japan only) | HS026, ISO/TS 24289:2021, spec **v1.2i (16 May 2024)**; HL7 v2.5 text files under patient-ID/date/data-type folders: ADT-00/01/12/21/22/31/32/41/42/51/52/61, PPR-01 (病名), OMP-01/02 (prescription/injection, RDE^O11), OMP-11/12 (administration), OML-01/11 (lab order/result OUL^R22), OMG-01..13 (radiology/endoscopy/physiology), OMD (meals); extended storage for documents/PDF/reports with `_contents.xml` ([JAMI](https://www.jami.jp/jamistd/ssmix2); [spec v1.2i](https://www.jami.jp/wp-content/uploads/2024/05/SS-MIX2-標準化ストレージ-仕様書-Ver.1.2i.pdf); [HELICS overview](https://square.umin.ac.jp/helics/files/event_20190606/2_SS-MIX2_Spec&ImplGuide.pdf)). **Notes (progress notes) are not in standardised storage**; they may be in extended storage or only in the vendor EMR. | n/a |
| A5 DPC data (Japan) | 様式1 (patient attributes, diagnoses with ICD-10, stage, ADL, surgery), EF files (fee-for-service items incl. drugs/tests), D/H/K files; hospitals generate them monthly for MHLW submission (Health Insurance Act Art. 77). The hospital's own copies are an excellent structured inpatient source (diagnosis, procedures, drugs) with ICD-10 already coded ([MHLW DPC DB slides](https://www.mhlw.go.jp/content/12301000/000866817.pdf)). | n/a |
| A6 NHI MediCloud 健保醫療資訊雲端查詢 (Taiwan) | n/a | Point-of-care query with three-card authentication (patient NHI card + physician card + institution SAM); emergency path by national ID for triage 1–3; **every query logged by NHIA and reviewed for purpose** ([MOHW](https://mohw.gov.tw/cp-4633-52691-1.html)). Bulk retrieval for pre-screening is outside its terms; `SPEC_v3.md` FR-M0-12 already gates it on written NHIA permission + IRB. Recommendation: **do not build a MediCloud connector**; at most, a CRC may consult MediCloud for a consented candidate and type the result (§D). |
| A7 Appointments/scheduling feed | 予約 table in the HIS or SS-MIX2 ADT-12 (reception) as a proxy for "visited"; true future appointments need the scheduling DB. | HIS appointment table (`appointment` canonical table already in `services/adapter/mapping/templates/CANONICAL.md`). |

### A.1b Realistic extraction route per EMR vendor (what to ask for in the first IT meeting)

Vendor behaviour below is from general market knowledge, not from vendor documentation fetched today; confirm per site.

| Vendor / system | Typical extraction route for secondary use | Notes and caveats |
| --- | --- | --- |
| Fujitsu HOPE LifeMark-HX / EGMAIN-GX | SS-MIX2 gateway (standard option at most university hospitals); DWH product for reports; CSV export by the vendor SE on paid request | Progress notes usually only via the vendor DWH or a paid extraction; appointment table not in SS-MIX2 |
| NEC MegaOak-HR / MegaOak MI·RA·Is | SS-MIX2 gateway; MegaOak DWH; vendor-run SQL extraction | Same pattern; SS-MIX2 coverage depends on which gateway options were purchased |
| SSI (ソフトウェア・サービス) / CSI MIRAIs (IBM heritage) | SS-MIX2; vendor DWH | Mid-size hospitals; often no DWH, SS-MIX2 only |
| Any JP hospital | DPC 様式1/EF files from the 医事 system (monthly, already ICD-10 coded) | Inpatient only; cheapest structured source; the DPC office owns it |
| Any JP hospital with a 治験管理システム (e.g. vendor CTMS) | CSV export of enrolment/screening history | Feeds M6 / recall certificate known-positives, not pre-screening |
| TW medical centre HIS (in-house or vendor on Oracle/MSSQL/Db2) | DBA-made read-only views on a replica; nightly CSV drop; research DWH (CGRD-type) | Views are the norm; Db2 CDC needs an IBM licence (spec v4 §5.6.2) |
| TW hospital FHIR facade (TW Core, MOHW exchange projects) | FHIR search by patient; Bulk `$export` rarely enabled | Facades often omit notes and pathology |
| TW regional hospitals on vendor HIS | CSV drop produced by the vendor; limited DBA capacity | Expect the §E staged path |

### A.2 Data flow

```
Hospital EMR / HIS / LIS / RIS / 予約            interface engine (ADT/ORU/SIU/MDM copy feed)
   │ nightly RO views or CSV drop (A1)              │ MLLP/TLS, real time (A2)        FHIR server (A3)
   │ SS-MIX2 folder share, read-only mount (A4)     │                                  │ Bulk $export, SMART backend
   │ DPC 様式1/EF monthly files (A5)                 │                                  │
   ▼                                                ▼                                  ▼
 L0 landing (immutable, sha256, control totals) ─► L1 validate/quarantine ─► L2 standardise (site mapping YAML) ─►
 L3 pseudonymise (MPI, HMAC pid; MRN/name/national id stay in the vault) ─► L4 curated FHIR NDJSON + DuckDB lake ─►
 L5 serving pointer ─► FEAS (aggregates) / SCREEN (weekly list, PHI to delegated staff only) / CASE
 Hospital IT: management VLAN for console/CLI; audit chain copied nightly to hospital share
```

### A.3 Who operates it

Hospital IT (DBA/interface team) owns the views, the feed and the firewall rules; the research office / 治験事務局 owns the opt-out notice and the IRB file; a named **data steward** (medical-informatics staff) approves the mapping (G0) and reads DQ notices; CRC/PI consume lists; the vendor is an 委託先 (entrustee) under the hospital's supervision (APPI Art. 25 / PDPA Art. 8 and the EMR regulation's outsourcing clause).

### A.4 Legal basis and consent model

| | Japan | Taiwan |
| --- | --- | --- |
| Feasibility (aggregates) | Secondary use of existing information for research → ethics-guideline **opt-out** (notice on website/in hospital, ethics review, institution-head approval) or treat as 仮名加工情報 for internal analysis (APPI). Where the hospital frames it as *operational* (施設の治験実施体制の評価), some hospitals use the "利用目的の範囲内" argument — **needs legal review** per hospital. | PDPA Art. 6 academic-research exception on de-identified data, or the hospital's own research purpose with IRB approval (HSRA Art. 5; many IRBs classify retrospective aggregate counts as exempt/expedited under the 2012 MOHW announcement — **IRB-specific**). |
| Pre-screening (identifiable list to the PI) | Patient identified → cannot be 仮名加工情報 (contact prohibited). Basis: the treating physician's access to their *own* patients' records for the purpose of offering a trial is widely treated as within the medical-care purpose (院内掲示 of 利用目的 covering 治験・臨床研究の案内), with the IRB-approved protocol describing the recruitment method; staff who are not the treating team (SMO CRC) act under the PI's delegation. **needs legal review**: whether cross-department scans (not the PI's patients) need opt-out notice under the ethics guideline. | Pre-screening is part of the IRB-approved protocol's recruitment plan; access to charts of patients not under the PI's care needs the IRB to approve a chart-review/screening procedure and a consent waiver for the screening step (HSRA Art. 12(2) waiver categories) — **IRB-specific; needs legal review**. The EMR regulation's access-control rules mean the hospital must grant the box a purpose-bound account. |
| Consent registry | Research-contact consent (登録) where the hospital keeps one; `registry` canonical table and `settings.registry_source` already model it. | Same; some hospitals keep a 研究參與意願 flag. |

### A.5 Compliance requirements (beyond §0)

| ID | Requirement | JP / TW basis |
| --- | --- | --- |
| A-C1 | Written 責任分界表 / responsibility matrix, MDS/SDS service specification, SLA, incident clock (hospital-side 72 h TW; PPC preliminary report JP) | MIC/METI v2.0; TW EMR reg. Art. 3–4 |
| A-C2 | Vendor security attestation: ISO 27001 (TW EMR reg. demands certified standard for outsourced EMR contractors — **needs legal review** whether a *read-only secondary-use* box counts as "EMR system"), MHLW GL checklist mapping | TW EMR reg. Art. 6–9; MHLW GL v7.0 |
| A-C3 | 2FA for every interactive login to the box by FY2027 (JP); strong auth expected now at TW medical centres | MHLW GL v7.0 |
| A-C4 | Audit log of every PHI access (who/when/what/purpose) for the full retention period; exportable for authority inspection | TW EMR reg. Art. 3, 11, 13; ICH E6(R3) Annex 1 |
| A-C5 | Patient notice + opt-out mechanism, and a technical way to honour opt-out (exclude from lists; erase on request) | JP ethics GL; TW PDPA/Constitutional Court; HSRA Art. 19 |
| A-C6 | Data stays in-country; no foreign processing (APPI Art. 28; TW EMR reg. Art. 8); cloud LLM must stay off unless a lawful route exists | APPI; TW EMR reg. |
| A-C7 | IRB/倫理委員会 approval record and protocol number stored with each ruleset; box refuses SCREEN without one (configurable) | HSRA Art. 5; JP GL |
| A-C8 | Minimum necessary: the mapping declares which domains/columns are pulled; free text pulled only when note criteria are enabled | APPI Art. 17/18; PDPA Art. 5 |
| A-C9 | For GCP use: screening log export is attributable, contemporaneous, with a human-readable certified copy; the PI's mark is a *record*, not a signature unless ER/ES is implemented | J-GCP, ER/ES 2005; ICH E6(R3) |

### A.6 Technical requirements

| ID | Requirement | Repo status |
| --- | --- | --- |
| A-T1 | SQL source: RO account, read-consistent extract, watermark + overlap window, weekly full-key reconciliation, deletes as tombstones | `cgrd_sql` source does `SELECT * ... WHERE delta >= :since` only (`services/adapter/sources/cgrd_sql/source.py`); reconciliation design in spec v4 §5.6.2, control totals in `services/dataplat/reconcile/`. **Partial.** |
| A-T2 | SS-MIX2 reader: walk standardised storage, parse HL7 v2.5 (ISO IR 87 / Shift_JIS-ish encodings per MSH-18), map PPR-01 → Condition (MEDIS 病名 + ICD-10 in PRB/DG1), OMP → MedicationRequest (HOT/YJ in RXE), OML-11 → Observation (JLAC10 in OBX-3), ADT-12/22/52 → Encounter; extended storage `_contents.xml` → DocumentReference | `services/adapter/sources/ssmix2/source.py` raises NotImplementedError (D-28); `jp_core/README.md` says export to CSV. **Gap (largest Japan item).** |
| A-T3 | HL7 v2 MLLP listener: TLS, durable write before ACK, dedupe on MSH-10, A40 → MPI merge, SIU → `appointment`, ORU → `observation`, MDM → `document` | Spec v4 §5.6.5 only. **Gap.** |
| A-T4 | FHIR client: SMART Backend Services, Group `$export`, `_since`, manifest counts, `deleted[]` tombstones | `fhir_bulk` reads a directory only. **Gap.** |
| A-T5 | JP Core mapping profile (JP_Patient, JP_Condition, JP_MedicationRequest, JP_Observation_LabResult) parallel to `tw_core/demo_his.yaml` | `jp_core/` holds a README only. **Gap.** |
| A-T6 | Japanese terminology packages: MEDIS ICD10対応標準病名マスター (HS005, twice yearly), 臨床検査マスター JLAC10 (HS014, monthly), 医薬品HOTコードマスター (HS001, monthly; HOT13↔YJ↔薬価基準コード), plus a JLAC10→LOINC crosswalk for the IR ([MEDIS overview](https://square.umin.ac.jp/helics/files/event_20210610/5_MEDIS-DC.pdf)). Taiwan: NHI ICD-10-CM 2014/2023 editions, NHI drug codes→ATC, NHI order codes, MOHW LOINC mapping (already listed in `SPEC_v3.md` FR-M0-8) | `tools/build_terminology.py`, `services/adapter/mapping/tw_core/lab_local_to_loinc.csv`, `mimic/tables/*`. No MEDIS/JLAC10/HOT loader. **Gap (JP).** |
| A-T7 | DPC file reader (様式1 fixed layout + EF files) → Condition/Procedure/Medication with ICD-10 and 診療行為コード | None. **Gap (JP, medium value: inpatient-only, monthly).** |
| A-T8 | Appointment feed mapping with status vocabulary (booked/arrived/cancelled/no-show) | `appointment` table in lake (`services/lake/flatten.py`), canonical columns. Labelled "no hospital scheduling feed" until configured (`DESIGN.md` §7 row 2). **Supported via CSV/SQL.** |
| A-T9 | Network: box on a server VLAN; sources reachable only from the adapter container; console only from the management VLAN; mTLS to the interface engine | Compose networks + nftables cover egress; **ingress** (MLLP, SMB mount for SS-MIX2) needs new allow rules and documentation. |
| A-T10 | 2FA (TOTP/WebAuthn) in console or mandatory hospital IdP via the trusted-header SSO | SSO header exists (`services/console/app.py` D-93). No TOTP. **Gap.** |
| A-T11 | Opt-out and erasure: tombstone by pid/MRN, purge across snapshots/FHIR store/caches, purge certificate | Spec v4 §5.14.4; no code. **Gap.** |
| A-T12 | DQ checks specific to JP/TW: 和暦/ROC date parsing, full-width digits, Shift_JIS/Big5 encodings, JLAC10 unit consistency, ICD edition by visit date | ROC dates and Big5 in spec FR-M0-7; dataplat DQ framework exists (`services/dataplat/dq/`). JP-specific rules **gap**. |
| A-T13 | Encryption: TLS 1.3 to sources, LUKS at rest, key custody with hospital | Done (HARDENING §1–2). |
| A-T14 | Data minimisation: contracts flag `direct_identifier`/`quasi_identifier` columns; identity columns never leave the vault | Done (`contracts/demo_his/patient.yaml`, `CANONICAL.md` identity block). |
| A-T15 | Small-cell rules on every external aggregate; complementary suppression | Done (`smallcell.py`, DL-1 pack in `services/deliverables/`). |

### A.7 Operational requirements

- Hospital IT change request + security review (質問票: typically the MHLW checklist or the TW hospital's ISMS vendor questionnaire); firewall and VLAN tickets; DBA view creation; SS-MIX2 share permissions; interface-engine route; service account lifecycle.
- Ethics committee / IRB: one umbrella "pre-screening and feasibility using existing records" protocol per hospital, plus per-trial recruitment-method text; opt-out notice published.
- Contracts: 業務委託契約 with APPI Art. 25 supervision terms and PPC-style breach clauses (JP); outsourcing contract per TW EMR reg. Art. 6–9 filed with the local health bureau (**needs legal review** if applicable); SLA and 責任分界表.
- Runbooks: hospital-side on-call for feed failures; DQ HOLD notices to the steward; annual audit-trail review (ICH E6(R3)).

### A.8 Effort estimate

| Item | Weeks |
| --- | --- |
| SS-MIX2 reader + JP Core mapping + MEDIS/JLAC10/HOT loaders + JP DQ rules | 6–8 |
| HL7 v2 MLLP ingest (ADT/SIU/ORU/MDM, A40) | 4–5 |
| FHIR Bulk + SMART backend client | 2–3 |
| SQL reconciliation (overlap window, weekly key diff, tombstones) | 2 |
| DPC 様式1/EF reader | 2 |
| Console 2FA (TOTP + WebAuthn) | 1.5 |
| Erasure/tombstone pipeline + purge certificate | 3 |
| Compliance pack: MHLW GL checklist mapping, MDS/SDS, 責任分界表, TW outsourcing pack | 2 (writing) |

### A.9 Risks

- Vendor EMR lock-in: Fujitsu/NEC/CSI may charge for DWH or SS-MIX2 extraction licences; many hospitals only have SS-MIX2 for *some* domains. Notes often unreachable → note criteria unusable (DESIGN §7 row 6).
- SS-MIX2 lacks future appointments → weekly lists built on "last visit" only.
- MHLW GL v7.0 2FA deadline (Apr 2027) lands inside the first Japanese deployments.
- TW: hospital legal may read the EMR regulation as requiring ISO 27001 certification of the *vendor* before contract.
- Secondary-use legal basis for cross-department pre-screening is the single biggest legal risk in both countries.

---

## B. PI's own patient database / research registry (periodic import)

### B.1 Variants
Excel/CSV exports (most common in memory clinics), REDCap (API or CSV export; widely used at Japanese ARO/university hospitals, e.g. [Kyushu ARO REDCap](https://www.aro.med.kyushu-u.ac.jp/wp-content/uploads/2024/08/redcappamphlet2024.pdf)), Microsoft Access, FileMaker (common in Japanese clinics), a memory-clinic cohort DB (MMSE/MoCA/CDR, amyloid status, APOE, MRI reads), departmental registries (dialysis, stroke).

| Registry type | Typical fields | Typical problems seen at import |
| --- | --- | --- |
| Memory-clinic Excel | name, MRN, DOB, visit dates, MMSE/MoCA, CDR, diagnosis text (JA/zh-TW free text), MRI/PET note, meds | Names in the file (direct identifiers), merged cells, 和暦/ROC dates, scores as text, one row per visit vs per patient |
| REDCap project | record_id, instruments per event, coded fields with labels, DAG per site | Longitudinal events need flattening; `record_id` ≠ MRN; partial instruments; exported labels vs raw codes |
| Access / FileMaker | relational tables, local code lists | Schema undocumented; ODBC availability; exports lose lookups |
| Cohort DB with biomarkers | APOE, amyloid PET (visual read, centiloid), CSF/plasma assays with lab-specific units | Biobank/genetic rules; assay version drift; results at partner sites |
| Departmental registry (stroke, dialysis) | diagnosis, dates, outcomes | Usually not AD-relevant but a comorbidity/exclusion source |

### B.2 Data flow
```
PI / clinic database  ──export (xlsx/csv, REDCap API JSON, Access/FileMaker ODBC)──►  SFTP or USB drop on the box
   ▼ L0 landing with manifest + sha256 ─► L1 contract validation (column dictionary agreed with the PI) ─► L2 mapping
   (registry columns → Patient/Condition/Observation with LOINC/SNOMED for MMSE, CDR, amyloid PET result) ─►
   L3 pseudonymise (join key = MRN if present, else registry ID; MPI links to EMR pid when both exist) ─► lake ─► FEAS/SCREEN
```

### B.3 Who operates it
The PI or their research assistant exports; the CRC or steward drops the file; the box validates and emails the DQ report. No hospital IT involvement beyond allowing the drop location (which is why PIs like it).

### B.4 Legal basis and consent
- The registry usually exists under its own IRB-approved protocol with consent that often includes "future research / being contacted about studies" (broad consent). Using it to pre-screen for a *new* trial is use within that consent only if the consent said so; otherwise JP: new ethics review + opt-out for existing information (2023 GL); TW: HSRA Art. 19 (use beyond original consent needs new review and consent, or de-linking — and de-linked data cannot produce a contact list).
- Cohorts with **samples** (plasma biomarkers, APOE) fall under the TW Biobank Act if run as a biobank; in JP under the ethics guideline's 試料 rules.
- The PI is the data controller of the registry; the box is the hospital's or the PI's processor — define which (SMO/CRO-owned boxes: §F).

Consent-scope vocabulary proposed for every imported registry (enforced by routing, see §H rank 3):

| Scope value | What the original consent allowed | What the box may produce from it |
| --- | --- | --- |
| `feasibility` | Analysis within the institution, no contact | Aggregates only; rows never appear on a weekly list |
| `contact` | "You may be contacted about future studies" | Weekly list / CASE sheet to delegated staff of *this* institution |
| `third_party` | Provision to other institutions/sponsors named or by category | Referral to another consortium site (§C.2) or sponsor-facing identifiable data (rare; **needs legal review**) |
| `withdrawn` | Participant withdrew | Tombstone; excluded everywhere; purge on request |

### B.5 Compliance requirements
B-C1 Consent-scope field per imported registry (what the consent allowed: `feasibility`, `contact`, `third_party`), enforced by routing (no contact list from a `feasibility`-only registry). B-C2 Registry contract (data dictionary) signed by the PI; schema drift blocks publish. B-C3 Provenance on every report: "registry {name}, export {date}, {n} rows". B-C4 Retention tied to the registry protocol's end date. B-C5 No merging of a registry with EMR data unless the IRB protocol allows the linkage (JP: 個人関連情報 rules; TW: HSRA).

### B.6 Technical requirements and repo status

| Req | Status |
| --- | --- |
| CSV/XLSX drop with manifest and contract | `csv` source + dataplat contracts: **supported** (`services/adapter/sources/csv/source.py`, `services/dataplat/landing/connectors.py`). XLSX not read directly (convert) — small gap. |
| REDCap API pull (`/api/` export records, token in secrets, project-level DAG) | **Gap** (1 week; egress allow rule for the REDCap host, usually on-prem). |
| Access/FileMaker | ODBC via SQLAlchemy DSN works for Access on Windows hosts only; FileMaker needs its Data API or CSV export. Recommend CSV export. |
| Instrument mapping: MMSE/MoCA/CDR-SB/ADAS-Cog/FAQ, amyloid PET visual read, CSF Aβ42/40, p-tau217, APOE genotype → Observation codes; `clinical-score` code system exists (`demo_his.yaml` `score`) | Partial; an **AD instrument code sheet** is needed (0.5 week) and feeds the IR `attribute` atoms. |
| MPI linkage registry ID ↔ MRN when both present; otherwise registry-only pid namespace | MPI supports multiple identifiers (`services/dataplat/mpi/`); namespace per source **needs a small extension**. |
| Consent-scope enforcement in routing | `consent.contact_ok` exists in the lake; scope vocabulary **gap**. |
| Idempotent re-import, diff report to the PI | Landing idempotency exists; human-readable diff **gap** (0.5 week). |

### B.7 Operational
Signed data dictionary; export SOP for the PI's assistant; drop folder permissions; quarterly re-import schedule; IRB amendment to the registry protocol naming TrialBox as a tool.

### B.8 Effort: 2–3 weeks total (REDCap connector, instrument sheet, consent scope, diff report). **Risks:** registry quality (free-text diagnoses, inconsistent dates), consent scope ambiguity, PI-owned data leaving the PI's control when the box is hospital-owned.

---

## C. Consortium / multi-site (trial-ready cohorts, AMED networks, Taiwan academic networks)

### C.1 Variants
- **C1 Federated counts**: each site runs its own box; the consortium root receives only signed aggregate tables (the existing COHORT MERGE model) — e.g. an AMED dementia network, a Taiwan medical-centre alliance.
- **C2 Central registry with per-site boxes**: a J-TRC-like trial-ready cohort (web study + onsite study; 865 onsite participants at 7 sites as of Mar 2026; consent at enrolment covers future AD research with opt-out per new use, data at U-Tokyo, samples at Niigata; [AMED release](https://www.amed.go.jp/news/release_20191031.html), [J-TRC onsite notice 2026](https://plaza.umin.ac.jp/~ueecd/wp-content/uploads/2026/03/J-TRCオンサイト研究_ロシュ共同研究.pdf)) where the central office matches participants to trials and refers them to sites. Here the box at the *central office* holds registry data (§B pattern) and site boxes hold EMR data.
- **C3 Central aggregate only, no site box**: sites send CSV counts by hand; the root box aggregates (lowest footprint).
- **C4 Certified-operator route (Japan)**: the consortium is a 認定利用事業者 under the Next-Generation Medical Infrastructure Act and receives 仮名加工医療情報 from hospitals via a certified creator — feasibility only (contact prohibited), hospital notice + opt-out needed.

### C.2 Data flow (C1)
```
Site A box ─ signed COHORT table (aggregates, small cells suppressed, ε accounted) ─┐
Site B box ─ ... ─────────────────────────────────────────────────────────────────┼─► Root box: verify Ed25519,
Site C box ─ ... ─────────────────────────────────────────────────────────────────┘   merge, differencing check,
                                                                                        consortium feasibility report
Query distribution: root → sites by signed ruleset (same criteria hash at every site)
Referral (C2 only): central registry → "you may be eligible" → participant → site PI (no cross-site PHI transfer)
```

### C.3 Who operates it
A consortium data-coordinating centre (DCC) runs the root; each site's research office runs its box; a data access committee reviews requests; a DUA governs each member.

### C.4 Legal basis and consent
- C1/C3: only aggregates leave each site → not personal data if suppression/noise is adequate (JP 統計情報; TW: non-identifiable). Still: ethics approval at each site for the secondary use, and the DUA must state the suppression rules.
- C2: participants consented to be contacted; cross-site referral carries PHI → needs consent language covering transfer to the trial site, and in TW HSRA Art. 19 for any non-de-linked transfer; overseas sponsor access only with explicit consent (TW: written consent + IRB + MOHW; JP: destination-country disclosure).
- C4: hospital notice (separate pseudonymised-use notice), ≈30-day opt-out window, provision records; certified operators carry the security obligations. TrialBox would *not* claim certification (spec v4 CMP-65).

### C.5 Compliance requirements
C-C1 Data Use Agreement template: purpose, suppression thresholds, ε budget, retention, publication rules, audit rights, breach notice. C-C2 Common ruleset governance: criteria version signed by the DCC; sites cannot alter. C-C3 Privacy accountant across sites (differencing attacks between quarters/requesters). C-C4 Five Safes record per release. C-C5 Secondary-use ethics approval at every site and the DCC (JP: 多機関共同研究 single ethics review allowed under the GL; TW: each hospital's IRB or a joint IRB — **needs legal review** on joint-IRB acceptance). C-C6 For C2 referrals: a participant-facing opt-out that propagates to every site box.

DUA / consortium agreement clause checklist (what the DCC's lawyer will ask the box to support):

| Clause | Box behaviour that evidences it |
| --- | --- |
| Purpose limitation (feasibility / trial-readiness only) | Approval record per ruleset (§H rank 3); planner refuses other purposes |
| Minimum cell size and suppression method | `thresholds.small_cell` per ruleset manifest; suppression flags in the signed table |
| Noise mechanism and ε budget per requester per quarter | Privacy ledger entries (`SPEC_v3.md` §5.11) — not yet implemented |
| No re-identification attempts; no linkage with other data | Root holds aggregates only (D1); audit of merges |
| Retention and deletion of member tables | Retention job; deletion audited with sha256 |
| Publication and sponsor-disclosure rules | DL-1 disclosure profiles (`services/deliverables/`) |
| Breach notification between members (JP PPC and TW PDPC clocks) | Breach runbook (R28) |
| Audit rights | Hash-chained audit export (`tools/audit_verify.py`) |
| Ruleset governance (who may change criteria, versioning) | Signed ruleset bundles; git tags per version |

### C.6 Technical requirements and repo status

| Req | Status |
| --- | --- |
| Signed aggregate tables, merge at root, ownership rules | **Supported** (`services/orchestrator/scenarios/cohort.py`, COHORT MERGE; SPEC §8.3). |
| Ruleset distribution as signed update bundles | **Supported** (`tools/sign_bundle.py`, `tools/apply_update.sh`). |
| DP noise + pairwise masks, ε ledger per requester | Spec FR-M11-3 and privacy ledger §5.11; **not implemented**. |
| OMOP CDM view for OHDSI network studies | Spec FR-M11-2 (R3); **not implemented**. |
| Site-to-root transport | Email today (mail-gateway). Works for air-gapped sites; **SFTP/HTTPS push as option** (1 week). |
| Cross-site opt-out propagation (C2) | **Gap**, depends on erasure pipeline (A-T11). |
| Consortium report with per-site rows suppressed when a site has small cells (complementary suppression across sites) | DL-1 suppression exists per pack; cross-site **gap** (1 week). |

### C.7 Operational
DCC governance charter; data access committee SOP; member onboarding (key exchange out of band, ruleset sign-off); annual re-approval. For C4: engagement with a certified creator (e.g. the existing 認定事業者) and the hospital notice campaign.

### C.8 Effort: C1/C3 ready now apart from DP/ε (3–4 weeks); C2 needs §B + opt-out propagation (+2 weeks); C4 is mostly legal/contractual.
**Risks:** inter-site code-system drift (ICD edition, JLAC10 vs local lab codes) silently changes counts; differencing attacks on small specialist cohorts (early AD counts per site are small); consortium politics on who owns the root.

---

## D. Manual input (CRC single-case entry, referral letters, scanned PDFs/OCR, questionnaires), patient self-referral web forms, clinic referrals

### D.1 Variants
- **D1 CRC single-case entry**: the CRC types the key facts (age, MMSE, amyloid status, meds, comorbidities) for one patient → eligibility sheet. Existing `CASE` command (D-91) covers "known chart number, lake has data"; the *no-lake* variant needs a structured form.
- **D2 Paste or upload of a referral letter 診療情報提供書 / 轉診單** (DOCX/PDF/scan) → OCR → extraction → CASE.
- **D3 Pre-screen questionnaires** (paper → scanned, or web) completed by the patient/family at the clinic.
- **D4 Patient self-referral web form** (public internet: "am I eligible?" questionnaire; the J-TRC web-study model) — **outside the hospital network**, so it breaks the box's no-ingress posture.
- **D5 Referral from an outside clinic/GP** (かかりつけ医 → 認知症疾患医療センター; TW community clinics → medical centre) by letter, fax or the regional network.

### D.2 Data flow
```
D1  CRC console form (structured fields, controlled vocab) ─► case.json ─► CASE sheet (lake joins if MRN known)
D2  PDF/scan ─► doc-parser (pypdf; PaddleOCR optional for ja/zh-TW scans) ─► ir_locate/extract ─► CRC confirms fields ─► CASE
D3  Questionnaire (paper → scan → OCR form template; or console form) ─► Observation(questionnaire) ─► CASE / registry
D4  Public web form (DMZ, separate service) ─► encrypted queue ─► hospital-side CRC pulls into the box (no inbound route to the box)
D5  Letter/fax ─► D2 path; regional-network referral (JP 地域医療連携ネットワーク, TW 電子轉診平台) ─► D2 or FHIR referral bundle
All  ─► candidate registry (screening log) with source = manual/referral/self-referral, entered_by, entered_at
```

### D.3 Who operates it
CRC (hospital or SMO), research nurse, clinic staff for D5, the patient for D4. Research office owns the D4 website and its notice.

### D.4 Legal basis and consent
- D1/D2/D3/D5: data of a patient already under the hospital's care or referred for care → medical-care purpose plus the IRB-approved recruitment procedure; referral letters from other institutions are provided *for care* — using them to pre-screen for research is secondary use (JP: within the receiving institution's notified purpose if 治験案内 is listed; TW: hospital's purpose list) — **needs legal review**.
- D4 (self-referral): the person supplies their own data with explicit consent on the form → clean basis (JP: 本人同意; TW: PDPA Art. 6 written consent for health data). Must state: who holds the data, retention, that it is not medical advice, contact. J-TRC's model (online consent + CFI/Cogstate every 3 months) shows the pattern and the scale (20,000 target).
- Questionnaires with cognitive items are health data (sensitive) in both countries.

### D.5 Compliance requirements
D-C1 Every manual entry attributable (user, time, source document hash), editable only with reason (ALCOA+). D-C2 OCR output is a draft; a human confirms each extracted value before it counts (SAFE rule; also GCP source-verification). D-C3 D4 web form: separate privacy notice, consent checkbox with version, cookie-free, served from hospital or vendor domain with a named controller, data minimisation (no national ID), rate limiting and CAPTCHA, retention ≤ the stated period, no profiling beyond stated purpose. JP: APPI opt-in; TW: PDPA Art. 8 notice items. D-C4 Minors/incapacitated (relevant in dementia): proxy consent rules (TW HSRA Art. 12; JP GL 代諾). D-C5 Fax/paper referrals: scanning SOP, originals retained per hospital rule. D-C6 If the entered data later becomes trial source: ER/ES / Part 11 expectations on the CASE sheet (audit trail, no silent edits).

Manual case form — minimum field set for an early-AD study (D1), all with "unknown / not on record" allowed so the
sheet reports `data_gap` instead of `fail`:

| Group | Fields | Code system |
| --- | --- | --- |
| Identity (vault only) | MRN or registry ID; optional name for the PI's list | pid map |
| Demographics | birth year/month, sex, residence (for travel burden), language | — |
| Cognition | MMSE (date, score), MoCA, CDR global + CDR-SB, ADAS-Cog if known, education years | LOINC / local score codes |
| Biomarkers | amyloid PET (date, visual read ±, centiloid), CSF Aβ42/40, p-tau, plasma p-tau217, APOE | LOINC + local |
| Imaging | MRI date, ARIA-relevant findings (microbleeds count, superficial siderosis), contraindications | SNOMED / local |
| Diagnoses | AD/MCI diagnosis and date, other neuro/psych diagnoses, cancer, cardiac | ICD-10 (MEDIS 病名 in JP; NHI ICD-10-CM in TW) |
| Medications | cholinesterase inhibitors, memantine, anticoagulants, psychotropics with start dates | HOT/YJ (JP), NHI code + ATC (TW) |
| Study partner | availability of a study partner (yes/no) | — |
| Consent/contact | consent-to-contact status, preferred contact, referring clinician | consent scope |

Self-referral web form (D4) — requirement checklist:

| Req | Detail |
| --- | --- |
| Hosting | DMZ host owned by the hospital or an in-country processor; no route into the box; the box *pulls* over an allowlisted egress rule |
| Consent | Versioned consent text approved by the IRB; checkbox + timestamp + version stored with the record; JP 本人同意, TW PDPA Art. 6 written consent (electronic signature acceptable — **needs legal review**) |
| Notice | Controller name, purpose, retention, rights, contact, "not medical advice", intended-use statement |
| Minimisation | No national ID, no address beyond city; age band or DOB only if needed for criteria |
| Security | TLS 1.3, no third-party scripts/analytics, CAPTCHA, rate limit, encryption at rest with the box's public key, 30-day queue retention |
| Accessibility and language | JA/zh-TW plain language, large type, caregiver-assisted completion flag |
| Triage | Deterministic pre-filter (age, self-reported diagnosis) before anything reaches a CRC |
| Audit | Submission id, hash, pull timestamp in the box's audit chain |

### D.6 Technical requirements and repo status

| Req | Status |
| --- | --- |
| CASE one-chart sheet from lake + command line | **Supported** (`services/orchestrator/scenarios/case.py`). |
| Structured manual form (no lake): controlled fields for AD criteria (age, MMSE, CDR, amyloid, MRI, meds, comorbidities) | **Gap** (console form + schema, 1.5 weeks). |
| PDF/DOCX parsing; OCR for scanned JA/zh-TW | doc-parser with optional PaddleOCR (`services/doc_parser/parser.py`); referral-letter templates (JP 診療情報提供書 fixed layout; TW 轉診單) **gap** (1 week). |
| Human confirmation loop on extracted values | Review package pattern exists for criteria; per-case field confirmation **gap** (1 week). |
| Candidate registry with `source` and entered-by | Registry events exist (`services/orchestrator/candidates.py`); add source enum (0.2 week). |
| Questionnaire instruments (CFI, AD8, MoCA) as Observation codes | **Gap**, shares the AD instrument sheet from §B. |
| D4 public web form + queue + pull | **Gap and architectural**: needs a DMZ component outside the box, encrypted at rest, pulled by the box (keeps egress-only posture). 3 weeks incl. security review. |
| Regional referral networks (JP 地域連携: ID-Link/HumanBridge; TW 電子轉診) | **Out of scope v1**; accept as D2 documents. |
| Audit of edits with reason | Audit chain exists; edit-with-reason UI **gap**. |

### D.7 Operational
CRC SOP for manual entry and OCR confirmation; research-office ownership of the web form (JP: 院内掲示 + website notice; TW: privacy notice); IRB approval of questionnaire and website text; hospital IT approval for the DMZ host (or vendor-hosted form in-country with a processor agreement).

### D.8 Effort: D1–D3 3–4 weeks; D4 +3 weeks; D5 0.
**Risks:** OCR errors in Japanese handwriting; CRC time (manual entry is the fallback, not the product); D4 becomes a "medical advice" surface (intended-use statement must be on the form); self-referral floods the CRC with ineligible people without a triage rule.

---

## E. Hybrid / staged (manual or PI DB first, EMR later) and offline / air-gapped boxes

### E.1 Staged adoption path (the recommended commercial path)

| Stage | Sources | What the box must guarantee |
| --- | --- | --- |
| S0 Pilot | §D manual + §B registry CSV | Same reports, labelled "data source: registry/manual" (DESIGN §7 row 1); counts explicitly *not* hospital-wide. |
| S1 | + nightly CSV drop of HIS extracts (A1 by file) | Mapping via `CANONICAL.md`; DQ gate; registry and HIS linked through MPI. |
| S2 | + RO SQL views or SS-MIX2 | Reconciliation; snapshots; historical back-fill without duplicating registry rows. |
| S3 | + HL7 v2 / FHIR for same-day appointments | Intraday overlay; weekly list with next-visit date. |

Requirements specific to staging: E-T1 **source precedence and conflict rules** (registry says MMSE 24 on 2025-03, EMR has 22 on 2025-06 → most-recent-wins per observation, but keep both with provenance). E-T2 **re-pseudonymisation stability**: moving a patient from a registry-ID namespace to an MRN namespace must keep the pid (MPI alias; `pid_alias` exists). E-T3 **report comparability**: when the source set changes, feasibility numbers jump; the pack must show the source-change date (manifest already records sources; a "source changed since last pack" line is a small gap). E-T4 Ethics: the IRB protocol must cover the later stages or be amended; the box should refuse a source not listed in the approval record (configurable).

### E.2 Offline / air-gapped
Already the design centre: offline signed bundles (`deploy/install.sh`, `tools/apply_update.sh`), no registry/download, local models, email as the only channel (`docs/ARCHITECTURE.md` §1). Additional requirements for *truly* air-gapped (no mail either): E-T5 USB/SFTP job intake (the console's "web requests become the exact e-mail line" path already exists, `services/console` pilot workspace) → make the console the primary intake when mail is unavailable; E-T6 outputs via encrypted 7z on removable media with the hospital's media-control SOP (MHLW GL external-device limits; TW EMR reg. media sanitisation); E-T7 terminology and model updates by bundle only; E-T8 time sync without NTP (hospital GPS/NTP appliance) — audit timestamps depend on it (`trialbox doctor` checks clock sync, FR-M0-11); E-T9 CT.gov/jRCT competing-trial data by bundle snapshot (registry-sync offline mirror exists for CT.gov; **jRCT has no API** — DESIGN §9.5).
Cloud-LLM option must be disabled in this profile (`settings.models.cloud_enabled=false`; egress rule absent).

### E.3 Effort: staging rules 1–2 weeks; air-gapped intake/output 1–2 weeks. **Risks:** pilots stall at S0 because the hospital never approves S2 (plan the contract so S0 alone has value); duplicate patients across registry and HIS inflate counts if the MPI linkage key is missing.

---

## F. Other scenarios found

### F.1 Imaging / PET / biomarker and central-lab feeds
- Amyloid PET visual reads and centiloid values, MRI volumetrics, CSF Aβ/p-tau, plasma p-tau217 — often at a partner site or a central lab (DESIGN §7 row 7). Routes: RIS/PACS report text (ORU/MDM or SS-MIX2 OMG-11/extended storage report PDF), DICOM SR (needs a DICOM listener — out of scope; take the report), central-lab CSV/HL7 ORU with LOINC/JLAC10 codes.
- Compliance: results from a *trial's* central lab belong to the sponsor's study and may only be used for that study (protocol/CTA) — never fed back into general pre-screening (**contract requirement**). Genetic data (APOE) is 要配慮/special data in both countries and in TW may trigger the Biobank Act if samples are banked.
- Repo: `report` and `observation` tables exist; `condition_attribute` planned (FR-M0-13). Gap: biomarker code sheet (shared with §B), report-conclusion extraction templates for PET reads in JA/zh-TW (1–2 weeks).

### F.2 Health check-up 健診 data (Japan) / 健康檢查 (Taiwan)
- Japan: 特定健診 results in the HL7 CDA R2 XML format (hc08 schema; one file per examinee per check-up; sent by 健診機関 to insurers; reuse for other check-up types) ([MHLW spec v4](https://www.mhlw.go.jp/content/12400000/3-1A.pdf)); the national EHR-sharing service also distributes 健診結果報告書. Hospitals with a 健診センター hold their own data. For AD trials value is low-moderate (vascular risk, BMI, HbA1c) but it reaches *pre-symptomatic* people — the J-TRC population.
- Legal: 健診 data collected for the insurer's purpose; use for research by the 健診機関 needs opt-out notice (GL) and the spec itself says non-特定健診 sharing needs examinee consent. TW: health-exam data is PDPA Art. 6 special data.
- Repo: a CDA-R2 XML reader is a gap (1.5 weeks), mapping to Observation straightforward.

### F.3 Insurance claims
- Japan: レセプト (electronic claims, 診療報酬明細) held by the hospital's 医事 system and DPC EF files — structured drug/procedure history; NDB access is for approved research only (not an operational source). Taiwan: the hospital's NHI claim files (申報檔) — the existing `claim` table and `demo_his` claim contract already model this; NHIRD/HWDC only as aggregate priors (spec v4 §5.6.9). My Health Bank SDK lets a *citizen* authorise an app to pull their own visit/medication/test records ([MOHW on the SDK](https://www.mohw.gov.tw/fp-5269-70271-1.html)) — a possible **patient-driven** source for D4 self-referral in Taiwan, with consent, but the SDK's terms are health-management oriented (**needs NHIA confirmation**).

### F.4 Wearables / digital cognitive tests
Cogstate, CFI, digital clock drawing, speech-based screens, actigraphy — arrive as vendor CSV/API. Compliance: vendor is usually overseas → cross-border transfer rules (APPI Art. 28; TW PDPA Art. 21); device may be a medical device (SaMD) even if TrialBox is not; results are health data. Repo: CSV path works; no vendor APIs. Treat as §B-type registry drops with a consent-scope flag.

### F.5 Cloud-hosted variant (vendor- or hospital-tenant cloud, in-country)
- Japan: allowed under the MHLW GL (cloud encouraged in v7.0) and the MIC/METI provider GL v2.0, with the "3省2GL" responsibility split and domestic processing (APPI Art. 28 for foreign providers; MHLW v7.1 is still deciding the scope of domestic-law enforcement for data stored abroad). Taiwan: EMR regulation Art. 8 — data in Taiwan unless approved, provider with certified ISMS, exit plan. Both: medical-centre cyber rules (TW CI hospitals) may forbid PHI in public cloud.
- Technical: dedicated tenant, customer-managed keys, private connectivity (no public ingress), the same egress policy, SIEM export to the hospital, full audit, documented subprocessor list, no training on data, deletion certificate at exit.
- Repo: compose is host-oriented; cloud needs an IaC profile, KMS integration instead of TPM, and a pentest. 4–6 weeks + legal. **Recommendation:** keep on-prem as default; cloud only for the §C root or an SMO-owned box with de-identified data.

### F.6 SMO-owned or CRO-owned box
- SMO box inside the hospital network serving several hospitals' delegated CRCs: the hospital remains controller of each hospital's data; the SMO is a processor under each hospital; per-hospital data isolation (separate lake, keys, accounts) is mandatory; SMO contracts must be mirrored in the box's `affiliation`/`studies`/`expires` scoping (already in `services/console/auth.py`). Multi-tenant isolation **not** built (one site per box); run one box per hospital instead.
- CRO box for feasibility across sites: must only ever hold aggregates (the `cro` role is aggregate-only, DESIGN §1.3) — this is §C.3 at the CRO.
- JP: SMO staff see PHI under delegation (DESIGN §1.4 decision); confirm per hospital contract. TW: SMO/CRO staff are "受委託者" — hospital IRB and the CTA must name them.

### F.7 Research-database zone (CGRD-type, de-identified)
Already in spec v4 §5.6.3: feasibility only, never pre-screening (re-identification impossible), separate zone/keys, honest broker outside the box. Not implemented as a separate zone; the lake has no zone concept — **gap** if a TW medical centre offers only its research DB (2 weeks: zone flag on snapshots and a planner refusal for SCREEN).

---

### F.8 Summary table for the §F feeds (same structure as the main scenarios)

| Feed | Data flow | Operator | Legal basis / consent | Key compliance | Repo status | Effort (wk) | Main risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F.1 Imaging/PET/biomarker, central lab | RIS/PACS report text or lab CSV/ORU → `report`/`observation` | Radiology/lab IT; central lab under sponsor contract | Hospital-generated results: same as §A. Sponsor central-lab results: study-only use per CTA | Genetic data = sensitive; TW Biobank Act if samples banked; sponsor data firewall | Tables exist; code sheet + report templates missing | 1.5–2 | Mixing sponsor study data into general pre-screening |
| F.2 健診 / health check-up | 特定健診 CDA R2 XML or 健診センター DB → `observation` | 健診センター / insurer liaison | JP opt-out notice (GL); examinee consent for non-特定健診 sharing; TW PDPA Art. 6 | Purpose originally insurer's; separate notice | No CDA reader | 1.5 | Low AD relevance vs effort; reaches pre-symptomatic people though |
| F.3 Claims (レセプト, NHI 申報檔) | 医事/claims files → `claim`, `medication`, `procedure` | 医事課 / billing IT | Hospital's own data: same as §A. NDB/NHIRD: aggregate priors only | TW Constitutional Court opt-out; My Health Bank SDK only with citizen authorisation | `claim` table + contract exist (TW) | 1 (JP レセプト layout) | Claims lag and coding for billing not diagnosis |
| F.4 Wearables / digital cognition | Vendor CSV/API → registry-type drop | PI / vendor | Participant consent incl. cross-border vendor processing | APPI Art. 28; TW PDPA Art. 21; SaMD status of the device | CSV path works; no vendor APIs | 0.5 per vendor | Vendor overseas; terms change |
| F.5 Cloud-hosted variant | Same pipeline in an in-country tenant | Vendor SRE under hospital supervision | Same as on-prem plus provider GL (JP) / EMR reg. Art. 8 (TW) | Domestic storage, certified ISMS, exit plan, subprocessors | Compose only | 4–6 + legal | CI hospitals may forbid PHI in cloud |
| F.6 SMO/CRO-owned box | One box per hospital (isolation) or aggregate-only CRO box | SMO/CRO IT | Hospital is controller; SMO/CRO processor; CTA names them | Delegation log; expiry; audited affiliation | Roles/affiliation/expiry exist; no multi-tenant | 0 (policy) / 4+ (multi-tenant) | Contract silence on PHI access by SMO staff |
| F.7 Research DB (CGRD-type) | De-identified release → feasibility only | Research-DB office / honest broker | Research-DB access approval; IRB | Never for lists; zone separation | No zone concept | 2 | Numbers from stale cuts shown as current |

---

## G. Cross-scenario requirements matrix

M = must, S = should, – = n/a. Columns: A EMR, B PI DB, C Consortium, D Manual/self-referral, E Hybrid/air-gapped, F Other feeds (imaging/健診/claims/wearables/cloud/SMO).

| # | Requirement | A | B | C | D | E | F |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | Pseudonymisation at ingest; identity only in vault; MPI aliases across sources | M | M | S | M | M | M |
| R2 | Patient notice + opt-out registry; exclusion applied in every run | M | S | M | S | M | M |
| R3 | Erasure/tombstone with purge across snapshots and caches; purge certificate | M | M | S | M | M | M |
| R4 | Per-source lawful-basis + IRB/ethics approval record; box refuses unapproved source/scope | M | M | M | S | M | M |
| R5 | Consent-scope enforcement in routing (feasibility / contact / third party) | M | M | M | M | M | M |
| R6 | Full PHI access audit with purpose, exportable, retained for the record's retention period | M | M | S | M | M | M |
| R7 | 2FA or hospital IdP for every interactive login (JP by Apr 2027) | M | M | M | M | M | M |
| R8 | Deny-by-default egress; documented ingress allow rules (MLLP, SMB, SFTP) | M | S | M | M | M | M |
| R9 | Encryption at rest and in transit; key custody with hospital | M | M | M | M | M | M |
| R10 | Data contracts + DQ gate + control totals + reconciliation | M | M | S | S | M | M |
| R11 | Small-cell suppression and privacy accountant on anything leaving the site | M | M | M | S | M | M |
| R12 | Provenance/data-honesty labels on every report (source, cut, coverage) | M | M | M | M | M | M |
| R13 | Japanese terminology (MEDIS 病名/ICD-10, JLAC10, HOT/YJ) and TW NHI codes with versioned manifests | M | S | S | S | M | S |
| R14 | SS-MIX2 reader + JP Core mapping | M | – | – | – | S | – |
| R15 | HL7 v2 MLLP ingest (ADT/SIU/ORU/MDM, A40) | S | – | – | – | S | S |
| R16 | FHIR Bulk + SMART Backend client | S | – | – | – | S | – |
| R17 | SQL reconciliation (overlap, weekly key diff, tombstones) | M | – | – | – | M | – |
| R18 | Registry connectors (REDCap API, XLSX) and PI data dictionary workflow | – | M | S | S | M | S |
| R19 | AD instrument/biomarker code sheet (MMSE, CDR, MoCA, amyloid PET, p-tau, APOE) | S | M | S | M | S | M |
| R20 | Manual case form + OCR confirmation loop + attributable edits | S | S | – | M | M | – |
| R21 | Public self-referral form in a DMZ with pull-only ingestion | – | – | S | M | – | – |
| R22 | Signed aggregate exchange, DP noise, ε ledger, cross-site suppression | – | – | M | – | – | S |
| R23 | Source precedence/conflict rules and source-change labels | S | S | – | S | M | M |
| R24 | Air-gapped intake/output (console/USB), offline terminology and registry snapshots | S | S | S | S | M | S |
| R25 | Research-DB zone (feasibility only; planner refuses SCREEN) | S | – | S | – | – | M |
| R26 | Vendor compliance pack: MHLW GL checklist, MIC/METI MDS/SDS + 責任分界表, TW outsourcing pack, ISO 27001 evidence, validation package | M | S | M | S | M | M |
| R27 | Per-hospital isolation when one operator (SMO/CRO) serves several hospitals | – | – | S | – | – | M |
| R28 | Breach workflow with JP and TW clocks and tabletop record | M | M | M | M | M | M |
| R29 | Trial-record mode (ER/ES / Part 11 controls on screening log and CASE sheet) when the sponsor treats them as source | S | S | – | S | S | – |
| R30 | Cross-border controls (no foreign processing; cloud LLM off; vendor devices) | M | M | M | M | M | M |

---

## H. Gap list ranked by number of scenarios that need it

| Rank | Gap (scenarios) | Suggested build item | Effort (wk) |
| --- | --- | --- | --- |
| 1 | **Erasure/opt-out pipeline** (R2, R3; A B C D E F) — spec v4 §5.14.4, no code | `services/dataplat/tombstone.py`: opt-out registry table (pid/MRN hash, ticket, scope), L3 drop rule, purge job over snapshots/FHIR store/judgement cache/outputs, signed purge certificate, `replay_degraded` on manifests; console "opt-out" page for the research office | 3 |
| 2 | **2FA in the console** (R7; all) — `services/console/auth.py` has none | TOTP (RFC 6238) + WebAuthn passkeys; enforce for admin/coordinator/investigator; recovery codes; `trialbox doctor` check; SSO path stays for IdP hospitals | 1.5 |
| 3 | **Lawful-basis and approval record per source/ruleset** (R4, R5; all) | `site/approvals.yaml` (IRB number, date, scope: feasibility/contact/third-party, sources allowed, expiry) validated at job start; routing refuses contact lists outside scope; consent-scope vocabulary on registry rows | 1.5 |
| 4 | **Vendor compliance pack** (R26; A C E F, S for B D) | MHLW GL v7.0 checklist mapping, MIC/METI v2.0 MDS/SDS + SLA, 責任分界表, TW EMR-regulation outsourcing pack, breach-clock runbook, validation plan (IQ/OQ/PQ with `tools/acceptance.py`), ISO 27001 roadmap | 3 (writing) |
| 5 | **AD instrument/biomarker code sheet + extraction templates** (R19; B D F, S elsewhere) | `services/adapter/mapping/templates/ad_instruments.csv` (MMSE, MoCA, CDR-SB, ADAS-Cog, FAQ, CFI, amyloid PET read, centiloid, CSF Aβ42/40, p-tau181/217, APOE) with LOINC/SNOMED + local codes; PET/MRI report conclusion templates JA/zh-TW | 1.5 |
| 6 | **Source precedence, MPI namespaces, source-change labels** (R23, R1; B D E F) | Observation-level provenance precedence; registry-ID namespace in MPI with alias on MRN discovery; "sources changed on {date}" line in DL-1 | 1.5 |
| 7 | **Japanese terminology loaders** (R13; A E, S for others) | `tools/build_terminology.py --jp`: MEDIS HS005 病名 (ICD-10 + 修飾語), HS014 JLAC10 (+ JLAC10→LOINC crosswalk), HS001 HOT13↔YJ; versioned in snapshot manifest; licence check for MEDIS redistribution (**needs legal/licence review**) | 2 |
| 8 | **SS-MIX2 reader + JP Core mapping** (R14; A E) | `services/adapter/sources/ssmix2/`: folder walker, HL7 v2.5 parser (hl7apy or own), encodings, data-type → resource mapping, extended-storage documents; `mapping/jp_core/ssmix2.yaml`; fixtures from a synthetic SS-MIX2 tree | 5–6 |
| 9 | **Manual case form + OCR confirmation** (R20; D E, S for A B) | Console form (`/studies/{rs}/case/new`), schema `case_input.schema.json`, referral-letter templates, field-level confirm before CASE; registry `source` enum | 3 |
| 10 | **SQL reconciliation** (R17; A E) | Overlap window, weekly full-key diff, `source_absent` tombstones, DBA read-consistency notes per engine | 2 |
| 11 | **HL7 v2 MLLP ingest** (R15; A E F) | `services/hl7in/`: MLLP/TLS listener, durable L0 write before ACK, MSH-10 dedupe, ADT/SIU/ORU/MDM mappers, A40 → MPI; ingress allow rule in `deploy/egress.py` | 4–5 |
| 12 | **Federated privacy accountant** (R22; C, S for F) | ε ledger per requester, geometric noise, pairwise masks, cross-site complementary suppression; DUA template | 3–4 |
| 13 | **REDCap/XLSX connectors** (R18; B, S for C D F) | `sources/redcap` (API export, DAG filter, token in secrets), XLSX reader via openpyxl into the csv path, PI data-dictionary round trip (reuse the Atlas workbook idea) | 1.5 |
| 14 | **Self-referral DMZ form** (R21; D, S for C) | Separate minimal service (no PHI at rest beyond the queue, encrypted to the box's key), box pulls over an allowlisted egress route; consent text versioning | 3 |
| 15 | **FHIR Bulk + SMART Backend client** (R16; A E) | `sources/fhir_server`: discovery, private_key_jwt, Group `$export`, `_since`, manifest counts, `deleted[]` | 2–3 |
| 16 | **Research-DB zone** (R25; F, S for A C) | Snapshot `zone` attribute; planner refuses SCREEN/CASE on `tre`; DL-1 prints the data cut | 2 |
| 17 | **Air-gapped intake/output** (R24; E) | Console as primary intake without mail; removable-media output SOP; offline jRCT/CT.gov snapshot bundle | 1–2 |
| 18 | **DPC reader, 特定健診 CDA reader** (R13/F2; A F) | Fixed-layout 様式1 + EF parser; CDA R2 XML → Observation | 2 + 1.5 |
| 19 | **Trial-record mode** (R29; A B D E) | Optional ER/ES profile: re-authentication on PI marks, immutable signed CASE sheet/screening log export with manifest, audit-trail review report | 2 |
| 20 | **Cloud/multi-tenant profile** (F5, F6; R27) | IaC profile, KMS, tenant isolation; pentest | 4–6 |

---

## I. Questions for the owner

1. **First customer shape**: Is the first Japanese site a university hospital with SS-MIX2 and a DWH, or a 認知症疾患医療センター / memory clinic with a PI registry? This decides whether rank 8 (SS-MIX2) or rank 13 (REDCap/XLSX) is built first.
2. **Pre-screening legal posture**: Do we sell "pre-screening of the PI's own patients only" (lowest legal risk) or "hospital-wide scan" (needs opt-out notice and broader IRB approval in both countries)? The box should enforce whichever we claim (rank 3).
3. **Who is the controller for PI registries and SMO boxes** — hospital, PI, or SMO? Contract templates and the `affiliation` model depend on it.
4. **Self-referral (J-TRC-style web study)**: in scope for v1.x? It is the only scenario that needs a component outside the hospital network.
5. **Consortium model**: aggregates-only alliance (ready now bar DP), or a referral-capable trial-ready cohort (needs consent and opt-out propagation)? Any plan to work with a Next-Generation-Act certified operator?
6. **2FA**: build TOTP/WebAuthn in the console, or require hospital IdP SSO (trusted header) as the only login for Japanese sites? MHLW v7.0 makes this due by April 2027.
7. **ISO 27001**: is the vendor pursuing certification? Taiwan's EMR regulation and MOHW cyber programme make it a practical gating item at medical centres; Japanese procurement asks for the 2省GL attestation.
8. **MEDIS licence**: redistributing MEDIS masters inside the bundle may need a licence; alternatively the hospital supplies them. Preference?

## Appendix 1 — Hospital IT / security questionnaire items to expect (and the answer the box can give today)

| Question the hospital asks | Japan source | Taiwan source | Answer today | Gap |
| --- | --- | --- | --- | --- |
| Where is the data stored? Does anything leave the hospital? | MHLW GL; APPI Art. 28 | EMR reg. Art. 8; PDPA Art. 21 | On the appliance; deny-by-default egress; no telemetry (`docs/HARDENING.md` §3) | Cloud variant only |
| Is the disk encrypted and how are keys kept? | MHLW GL | EMR reg. Art. 3 | LUKS2 + TPM; TPM-sealed key files | — |
| How do users log in? Is there 2FA? | MHLW GL v7.0 (mandatory FY2027) | Hospital ISMS | Local accounts (scrypt, lockout) or hospital IdP via trusted header | **TOTP/WebAuthn** |
| What is logged and for how long? | MHLW GL; ER/ES | EMR reg. Art. 11/13 (full retention period) | Hash-chained audit, 10 years; PHI reveals audited per row | Purpose field on every PHI read (partial) |
| Which accounts/views does the box need on the HIS? | — | — | Read-only account on DBA views, or file drop, or SS-MIX2 share | SS-MIX2 reader |
| How are patients pseudonymised; who can re-identify? | APPI 仮名加工; GL | HSRA 去連結 vs coded | HMAC pid; AES-GCM reverse map; re-identification only for delegated staff, audited | — |
| How is opt-out/erasure handled? | GL opt-out; APPI | Constitutional Court; HSRA Art. 19 | Consent registry flag only | **Tombstone/purge** |
| What happens on a breach? Who is notified when? | APPI leak report (PPC) | EMR reg. 72 h; PDPA Art. 12 | Spec'd runbook (SEC-14) | Tabletop record; JP/TW clock profile |
| Is the vendor ISO 27001 certified? Does it follow the 2省GL? | MIC/METI GL v2.0 | EMR reg. Art. 6–9 | No certificate yet | **Compliance pack**, certification roadmap |
| Is this a medical device? Is it validated? | PMDA SaMD; GCP | TFDA; GCP | Intended-use statement; deterministic re-runs; acceptance tool | Validation package (IQ/OQ/PQ) |
| Can it be updated without internet? Who approves updates? | MHLW GL change control | Hospital change management | Signed offline bundles; audited apply | — |
| Does it use AI? Where do models run? | MHLW/METI AI guidance | TW AI Basic Act principles | Local models only by default; cloud model off; PHI guard | AI disclosure block in every pack (spec CMP-34) |

## Appendix 2 — Ethics / IRB submission items the box should pre-fill

| Item | Content the box can generate |
| --- | --- |
| Description of the data source and items used | From the mapping YAML and contracts: tables, columns, privacy class, domains, date range |
| De-identification method | Pseudonymisation description (HMAC + MPI; vault custody); small-cell policy |
| Who accesses what | Role × capability table (`DESIGN.md` §1.7), delegation log linkage |
| Recruitment method text (JP 被験者の選定方法; TW 受試者招募方式) | Template paragraph per scenario (§A–§D) with the data-honesty labels |
| Opt-out notice text and web page | Template (JP GL items incl. start date; JP Next-Gen notice if §C.4; TW PDPA Art. 8 items) |
| Data retention and destruction | From `retention` settings and purge certificate design |
| Security summary | Appendix 1 answers |
| AI use disclosure | Models, versions, purpose, human-in-the-loop statement |

### Sources (all cited inline above; key ones repeated)
- MHLW 安全管理GL v7.0 overview (2026-05-29): https://www.mhlw.go.jp/content/10808000/001102596.pdf
- MIC/METI provider GL v2.0 (2025-03-28): https://www.soumu.go.jp/menu_news/s-news/01ryutsu06_02000427.html · https://www.meti.go.jp/policy/mono_info_service/healthcare/01gl_20250328.pdf
- 次世代医療基盤法 2024 amendment leaflet: https://www8.cao.go.jp/iryou/kouhou/pdf/kaisei_jisedaiiryou_iryoukikan.pdf
- 生命・医学系指針 2023 amendment: https://www.mhlw.go.jp/content/001087960.pdf
- APPI 2020/2021 amendments (PPC slides): https://www.mhlw.go.jp/content/10904750/000863622.pdf · PPC medical guidance: https://www.ppc.go.jp/personalinfo/legal/iryoukaigo_guidance/
- ER/ES and GCP references (Kobe SOP): https://www.hosp.kobe-u.ac.jp/ctrc/client/sop/denjika_sop_20240901.pdf
- SS-MIX2: https://www.jami.jp/jamistd/ssmix2 · https://www.jami.jp/wp-content/uploads/2024/05/SS-MIX2-標準化ストレージ-仕様書-Ver.1.2i.pdf · https://square.umin.ac.jp/helics/files/event_20190606/2_SS-MIX2_Spec&ImplGuide.pdf
- MEDIS masters: https://square.umin.ac.jp/helics/files/event_20210610/5_MEDIS-DC.pdf
- 電子カルテ情報共有サービス: https://www.mhlw.go.jp/content/10808000/001608497.pdf
- DPC data: https://www.mhlw.go.jp/content/12301000/000866817.pdf · 特定健診 XML: https://www.mhlw.go.jp/content/12400000/3-1A.pdf
- J-TRC: https://www.amed.go.jp/news/release_20191031.html · https://plaza.umin.ac.jp/~ueecd/wp-content/uploads/2026/03/J-TRCオンサイト研究_ロシュ共同研究.pdf
- REDCap in Japan: https://www.aro.med.kyushu-u.ac.jp/wp-content/uploads/2024/08/redcappamphlet2024.pdf
- Taiwan PDPA: https://practiceguides.chambers.com/practice-guides/data-protection-privacy-2025/taiwan · https://www.jonesday.com/de/insights/2025/12/taiwan-passes-major-amendments-to-the-personal-data-protection-act
- Human Subjects Research Act: https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020176 · exemption categories: https://irb.nycu.edu.tw/userfiles/irbch/files/20230930121740655.pdf
- Human Biobank Management Act (EN): https://ohr.tmu.edu.tw/upload/download_files/172759407119.%20Human%20Biobank%20Management%20Act人體生物資料庫管理條例.pdf
- EMR regulation: https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020121
- MOHW hospital cyber security (2025-08-15): https://mohw.gov.tw/cp-7175-83515-1.html
- NHI MediCloud: https://mohw.gov.tw/cp-4633-52691-1.html · My Health Bank SDK: https://www.mohw.gov.tw/fp-5269-70271-1.html
- Constitutional Court 111憲判13: https://cons.judicial.gov.tw/download/download.aspx?id=473975 · draft act commentary: https://www.twreporter.org/a/opinion-act-on-health-and-welfare-data
- TW Core IG: https://twcore.mohw.gov.tw/ig/twcore/history.html · GCP/TFDA: https://www.mohw.gov.tw/fp-16-76653-1.html
- ICH E6(R3): https://www.sidley.com/en/insights/newsupdates/2025/02/international-council-finalizes-modernized-global-good-clinical-practice-guideline
- ISO 27799: https://www.iso.org/standard/62777.html · FHIR Bulk Data authorization: https://hl7.org/fhir/uv/bulkdata/STU1.0.1/authorization/index.html
