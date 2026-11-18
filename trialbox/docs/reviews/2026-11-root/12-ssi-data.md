# Root review 12: the first hospital's data (SSI, SS-MIX2, REDCap and everything patient finding can use)

**Reader:** the owner (a clinician) first, then the builders who write plan 10, then whoever talks to the hospital's
IT and its vendor.

**Date and scope:** 2026-11-18, lane J, round 3, job B13. This review covers the hospital's data and how it gets into
the box. Review 11 covers Japanese regulation, code masters in general, language and culture. This review cites 01,
06, 10 and plan 9 revision 2 by id and does not repeat them. No real hospital data, no hospital-internal document and
no non-public source was used. The first site is not named here (the owner has not agreed to publish it): it is
"the first site (a general hospital in Japan)".

**Marks.** **[M n]** measured (the command and the number are in the measurement list, section 15). **[R file:line]**
read in this repository at `origin/master` 7da6edd38. **[S n]** a public source I opened (section 16: link, date,
terms). **[O]** opinion. **[NV]** not verified: I could not open it, or only a search summary saw it.

---

## 1. One page for the owner

**Who the vendor is.** "SSI" is 株式会社ソフトウェア・サービス (Software Service, Inc., Osaka). Its electronic chart is
**新版e-カルテ** and its order-entry and billing system is **NEWTONS2**. They are sold as one system with its own
nursing, laboratory, pathology, transfusion, rehabilitation, dialysis, DPC, cancer-registry, check-up and PACS
(Seavo) modules. The vendor counts **1,066 hospitals** (31 October 2026). It ranks itself **second in Japan** by
hospital installations, after Fujitsu Japan [S1, S2, S3, S9, S10].

**Does the first site (a general hospital in Japan) run it?** The owner has not agreed to publish the site's name,
so the public evidence on this question is kept outside the repository, in the site notes handed to the coordinator.
In this document the answer is **"not confirmed here"**: the site's IT confirms it in the questionnaire (section 9).

**Good enough today?** Yes, for a CSV hand-off. Partly, for SS-MIX2: the reader is careful about bytes, versions and
deletions, but it was built and tested against message shapes TrialBox wrote itself, not the published specification.

Reading the specification line by line (Ver.1.2i, 16 May 2024 [S20]) against the code found four faults. **Any one of
them would give wrong patient counts at an SSI hospital, and no current test would notice** [R, M]:

1. **Most outpatient visits disappear.** By default, every outpatient visit of a patient that is filed under the
   specification's numbering is collapsed into one. On three visits, the reader kept 1 [M4]. Admissions and
   discharges are affected the same way.
2. **The diagnosis list is read wrongly.**
   - The specification puts ICD-10 in PRB-10, outcome (転帰) in PRB-14/15, end date in PRB-9, the main diagnosis (主診断)
     in PRB-18 and deletions in PRB-1. The reader reads none of these.
   - So a cured or deleted diagnosis is counted as active, and "main diagnosis" cannot be asked [R `source.py:602-642`; S20].
   - The PRB-10 gap has been known and open since 2026-11-09 (MR-017).
3. **Medicines: one dose read as a day's dose, and YJ codes missed.** The reader stores the dose of one
   administration as the daily dose, so any dose criterion is wrong by the number of doses a day. It also never looks
   in RXE-31, the field where the specification puts YJ codes [R `source.py:694`; S20].
4. **Documents: none read.** The reader expects discharge summaries and reports one folder level too shallow, and
   expects document-type names the specification does not use. On a storage laid out to the guideline it read **0
   of 1** documents [M5; S24].

**What is not in SS-MIX2 at all, and matters for patient finding:** free-text notes (unless the vendor exports them
to extended storage); DPC 様式1 (main diagnosis, TNM stage, ADL, JCS, NYHA, smoking index, height and weight); the DPC
EF files (every procedure and drug billed, by day); レセプト (receipt) files; the cancer registry; vital signs and
nursing records; chemotherapy regimens. SSI has modules that hold each of these [S2, S3]. The vendor also says it will **disclose its database structure to
a hospital under a confidentiality agreement** [S2, S14]. The database is **Microsoft SQL Server** [S14, S17], and
TrialBox has no SQL Server driver today [M7].

**The five changes that matter most** [O]:

1. **Read SS-MIX2 the way the specification writes it.** Fix the record key, the diagnosis fields, the medicine
   fields and the extended-storage layout. Re-write the synthetic storage to the specification, so that the tests
   check the standard and not the reader's own assumptions (cards 12-1 to 12-6 and 12-10).
2. **Read DPC 様式1 and the EF files.** Every DPC hospital already makes them each month for the ministry, in a
   published layout [S26]. They answer the criteria SS-MIX2 cannot: stage, performance status, operations, and drugs
   given in hospital (cards 12-11, 12-12).
3. **A site profile.** Folders of tables the steward fills: local codes, document types, usage codes, units,
   templates, note sections. One hospital's habits then become data, not code (card 12-14, section 7).
4. **A synthetic Japanese hospital that looks like an SSI hospital.** It needs a storage to the specification,
   DPC and receipt files, and Japanese notes with sections and family-history traps. Today's synthetic notes are all
   one type and have no sections [M3] (card 12-17).
5. **A questionnaire, and synthetic sample exports from the vendor, before any visit** (section 9). We have never
   seen a real vendor's storage (STD-014, 01 §1.3 item f).

**What it costs.** Builders: 5 L, 12 M and 5 S cards (section 12). Money: no purchase for the work above. The
hospital's side may have costs that are not public: SSI charges for interfaces it does not ship as standard
("追加対応：可、追加費用：有") [S14]; an SS-MIX2 or DPC export already in place is usually free to read [O]; a database
replica is the vendor's decision and price [NV].

---

## 2. The vendor and its products, from public sources

| Fact | Value | Mark |
| --- | --- | --- |
| Company | 株式会社ソフトウェア・サービス, 大阪市淀川区西宮原 2-6-1; founded 1969 [NV: search summary of the annual report]; moved to the Tokyo Stock Exchange Standard market on 2022-04-04 | S13, S14 |
| Size | Revenue ¥38,425 million, FY ending 31 Oct 2024; 1,706 staff (consolidated); research and development ¥545 million | S18 (EDINET text as an aggregator shows it; the filing itself was not opened) |
| Hospitals | 1,066 hospitals and inpatient clinics as of 2026-10-31. The page lists 1,041 rows | S9; rows counted [M8] |
| Market position | Second in Japan, after Fujitsu Japan, 3rd CSI, 4th NEC. The vendor's own count from 月刊新医療『医療機器システム白書2026』, installations at end of March 2025, clinics excluded | S10 |
| Electronic chart | **新版e-カルテ** ("e-カルテ" is a registered trademark): a single chart for doctors, nursing, rehabilitation and nutrition; templates, word palette, schema drawings, pen input; "XML (HL7) 出力に対応" | S2, S14 |
| Order entry and billing | **NEWTONS2**: inpatient and outpatient full ordering with billing (医事会計) as one system. Orders: 投薬, 注射, 検査, 処置, 手術, 輸血, 食事, 看護指示, リハビリ, 服薬指導, 栄養指導. Also 次回来院時オーダ and conditional orders (疼痛時, 発熱時) | S2, S15 |
| Functions on the core system page | Portal; SOFA severity scoring; early-warning orders; referral management; appointments; **文書管理**; **NST and 栄養指導**; **手術/手術室管理 (手術記事)**; **簡易RIS (所見入力)**; **スキャナ取り込み画像管理**; **感染症情報, 食物・薬物等の禁忌情報管理**; DI search; 持参薬鑑別; risk management; **治験管理**; **SSI SCOPE (SSIデータ検索)** | S2 |
| Nursing | 看護業務支援システム: ward map, ICU 経過表 (vitals, fluid balance, infusion rates), automatic capture of vitals from monitors, nursing plans (NANDA, Gordon), 看護必要度, 転倒転落, 褥瘡, nursing summary | S2, S16 |
| Departmental systems (over 100, the vendor says) | クリティカルパス (BOM); **抗がん剤プロトコルシステム (regimens)**; dental chart; ER chart (JTAS); ophthalmology chart and tests; 麻酔記録; 統合参照; NEWTONS Mobile2; 連携ナビ; 入退院支援; incidents; 分娩管理; 感染管理; **臨床検査, 細菌検査, 病理検査 (cytology CSV output), 輸血管理, 検体管理 (with 同意書管理)**; 採血; **リハビリ**; 給食; **透析管理**; ME equipment; PACS; dose management; **病歴管理 (profiles, admissions, operations, discharge summaries)**; web appointments; **がん登録 (全国がん登録の届け出, TNM master)**; PokeMed; **医事会計, DPC関連システム, レセプトチェックDB, レセプト院内審査** | S3 |
| Check-ups | ドック・健診 (特定健診, 協会けんぽ), 特定保健指導, 巡回健診. They share the chart's patient ID | S4 |
| Regional network | CareMill (ケアミル). The vendor's example: an **SS-MIX** copy held off site for disaster reference | S5 |
| Imaging | Seavo series (SeavoPACS, SeavoView), approved medical-device software 230ALBZX00006000; report-writing support included | S6 |
| Data reuse | A dashboard on chart data with more than 100 management indicators. A medical-information data centre (ISMS since 2015) with remote backup and database replication monitoring | S7 |
| Secondary use of the database | "データベース構造の公開(守秘契約必要)により、病院様による独自の情報収集・情報利用が可能" [S2]. The 2022 catalogue says "情報ソースの公開（守秘契約必要）…（ＥＵＣの実現）" [S14] | S2, S14 |
| Database and platform | SQL Server 2016 Enterprise on Windows Server 2016 (2022 catalogue). SQL Server 2012/2016 in 2020. Current versions are not public | S14, S17 [NV for today] |
| Standards claimed (2022 catalogue) | Masters: MEDIS 標準病名 (ICD10), 標準手術・処置, 看護実践用語, レセプト電算 codes (standard); HOT, JLAC10, JJ1017, BOM ("コードに対応"); JAMI 標準用法. Exchange: JAHIS 病名 3.1C, 処方 3.0, 注射 2.1C, 放射線 3.1C, 臨床検査 4.0C as HL7 v2.5 output. HL7J-CDA 電子紹介状. Methods: TCP/IP socket, SOAP, XML file. **HS026 SS-MIX2: "ストレージ作成、データ連携（参照含む）／標準化ストレージ、拡張ストレージ（退院サマリ、診療情報提供書、医師カルテ、看護カルテなど）"**. HS032 CDA 退院時サマリ. HS008 電子紹介状 | S14, S15 |
| IHE | Integration statement "Newtons2 V1.0, 1-Dec-2020": SWF Order Placer, PAM, PDQ, CT, PIXv3, PDQv3. Connectathon participation for LTW, LTW-MB, LBL (2019) and ATNA, XDS.b, XCA (2018) | S11, S14 |
| FHIR | No FHIR product on the pages I opened. The annual report mentions HL7 FHIR only as government policy | S1–S8, S18 |
| Trials | A **治験管理** function in NEWTONS2. Its content is not described publicly | S2 [NV for content] |
| Cloud | "NEWTONS Light", a cloud chart that passed HISPRO evaluation (2022-12-08) | S13 |
| Anonymised data | Since 2025-10-01 SSI states it makes 匿名加工情報 (anonymously processed information) for benchmarking and research. The listed items include receipts, prescriptions, **DPC 様式1/3/4, D, inpatient and outpatient EF, H files**, lab, pathology, ophthalmology results, cancer registry and death certificates | S12 |
| Maintenance and user group | All maintenance by SSI's own staff; remote login over a closed IP network. Yearly SSユーザー会, with sub-groups for directors, nursing, system administrators and pharmacy (2026-08-26) | S8, S13 |
| Go-live effort (2022 catalogue) | 5 to 6 months before go-live, an engineer on site 2 to 3 months after. Example price: a 200-bed chart package from ¥20 million, before hardware and other systems | S14 |
| The first site | Not stated in this document: the owner has not agreed to publish the site's name. The public evidence is in the site notes kept outside the repository | – |

**What the vendor facts mean for patient finding** [O]:

- **SSI ships an SS-MIX2 writer**, standardised and extended storage alike [S14]. Whether the first site bought
  and switched it on is not public. It is question 1 of section 9.
- **SSI already extracts everything we need.** Its anonymised-data statement shows it has extraction routines for
  receipts, DPC files and clinical results across its customers [S12]. The question for SSI is therefore not "can
  you" but "on what terms".
- **The database door exists, but it is the vendor's.**
  - It needs an NDA and a SQL Server driver in the box.
  - It is the richest source and the most fragile: the schema can change with a version.
- **The 治験管理 and SSI SCOPE functions may already hold trial flags and saved patient searches.** Ask about them
  (question 30).

---

## 3. Every category of data such a hospital holds

**How to read the table.**

- **Leaves as** names the standard form. SS-MIX2 data types come from table 3.1-2 of the guideline [S22].
- **Timely** means how fast the data reaches a reader:
  - SS-MIX2 is written as messages are sent, minutes after the event at most hospitals [O; S22 3.1.4];
  - DPC and receipt files are monthly;
  - registries lag months.
- **TrialBox today** gives file and line under `trialbox/`.

**Paths used in the table.**

- `src` is `services/adapter/sources/ssmix2/source.py`.
- The canonical tables are in `services/adapter/mapping/templates/CANONICAL.md`.

| # | Category | Where it lives at an SSI hospital [S2, S3] | Leaves as | Codes | Complete / timely [O unless marked] | Patient finding uses it for | TrialBox today | Missing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 患者基本 | NEWTONS2 | SS-MIX2 **ADT-00** (ADT^A08; A23 delete) | Local ID (PID-3 PI), JIS names, PID-29/30 death | Full; real time | Age, sex, death, contact | ADT-00 read [R `src`:529-546] | ADT^A23 delete is read only through flag 0; the 住所 in PID-11 is not used (good for privacy) |
| 2 | 保険 | NEWTONS2 医事 | IN1 in ADT-00 (Ver.1.2g: 記号~番号~枝番) [S20]; receipt HO/KO records | Insurer numbers, 公費 codes | Full; real time | Exclusions on insurance (自費, 公費 for 難病 or 生活保護); age-band sanity | Not read [R `src`:529] | IN1 kind only (never numbers); 公費 types from receipt KO |
| 3 | 受診歴 / 入退院 | NEWTONS2 | **ADT-12** (A04), **ADT-21** planned admission, **ADT-22** (A01 / A11), **ADT-31/32** leave, **ADT-41/42** transfer, **ADT-51/52** (A16 / A03 / A13) | Dept (PV1-10), ward, doctor | Full; real time | "Seen in the last 12 months", inpatient now, length of stay, department | ADT-12/22/52 [R `src`:548-600]; **collapses visits by default [M4]** | Card 12-1 (key); ADT-21/31/32/41/42/51, A11/A13 cancellations (card 12-6) |
| 4 | 病名 (主病名, 疑い, 転帰, start and end) | NEWTONS2 病名 | **PPR-01** (PPR^ZD1): one file per patient, day "-", order ALL9 [S22]; PRB-3 病名管理番号 MDCDX2; **PRB-10 ICD-10**; PRB-13 疑い (JHSD0005); PRB-14 転帰 (HL70241 / JHSD0006); PRB-15 転帰日; PRB-16 開始日; PRB-7 診断日; PRB-9 終了日; PRB-18 主/副 (JHSD0007); ZPR modifiers [S20, S21] | MEDIS 標準病名, ICD-10 (2013), レセ電 傷病名 | Complete for billed diagnoses. **Over-coded "保険病名"** (a 病名 written to justify a test or drug) is common [O; S33 shows PPV 20–45 % for some diseases on 病名 alone] | Inclusion and exclusion diagnoses, "history of", "active", "suspected" | Read in a non-standard shape [R `src`:602-642] | Card 12-2; "保険病名" handling in the ladder (confirm with labs or drugs, as S33 and S35 do) |
| 5 | 処方 / 注射 (オーダ and 実施) | NEWTONS2 投薬・注射; nursing barcode 実施 | **OMP-01/02** (RDE^O11), **OMP-11/12** (RAS^O17) | HOT (RXE-2), **YJ or 厚労省コード in RXE-31**, JAMI 標準用法 in TQ1-3, RXE-3 dose per time, RXE-12 refills [S20] | Full; real time; 院外処方 included as orders | Current or prior drug, washout, dose, line of therapy | Orders and 実施 read [R `src`:686-727]; YJ, HOT and ATC resolution [R `src`:221-238] | Card 12-3 (RXE-31, per-time dose, frequency). 持参薬 are outside SS-MIX2 (DPC EF carries them [S26]) |
| 6 | 検体検査 | 臨床検査システム | **OML-11** (OUL^R22) results; **OML-01** (OML^O33) orders | JLAC10 (JC10) / JLAC11 (JC11), local codes | Full for in-house; outsourced tests are present when the LIS imports them [O] | Lab thresholds (eGFR, HbA1c, ANC), "measured within 28 days" | Results read, corrections and deletions too [R `src`:729-814] | OML-01 orders (card 12-7); JLAC10 coverage at MID-NET sites was only 29 % [S29] |
| 7 | 細菌 | 細菌検査システム | OML-11 (Ver.1.2c change to OBR-26 for susceptibility [S20]) or extended storage (微生物学的検査報告書 18725-2 [S25]) | JLAC10 material and organism codes | Partial [O] | Infection exclusions, colonisation | Only as ordinary OBX rows | Organism and susceptibility shape (with card 12-7) |
| 8 | 病理 | 病理検査システム | Extended storage: 病理検査報告書 11526-1, 細胞診 47526-9 [S25]; CSV for the cytology society [S3] | Free text; ICD-O sometimes [O] | Full text; days after the specimen | Histology, grade, receptor status, PD-L1 (from text) | Notes, if the layout were read [M5] | Card 12-4; section detector (card 12-15) |
| 9 | 生理検査 (ECG, echo, spirometry) | 生理 / 簡易 RIS | **OMG-03** order, **OMG-13** (ORU^R01) result; extended storage reports 28010-7, 12132-7, 59281-6 [S25] | JJ1017, local | Order full; results often PDFs [O; the circulatory society says such results sit in extended storage, not standardised (search summary, NV)] | EF %, QTc, FEV1 | Not read | Card 12-7; text from reports (card 12-4) |
| 10 | 画像 orders and 読影レポート | NEWTONS2 簡易RIS, Seavo | **OMG-01** order, **OMG-11** (OMI^Z23) 実施; reports in extended storage (18748-4, 18747-6 CT, 18755-9 MRI, 18758-3 PET) | JJ1017 Ver.3 | Orders full; reports same day | "Measurable disease", RECIST baseline, brain metastases | Not read (orders); reports [M5] | Cards 12-7, 12-4 |
| 11 | 手術 / 処置 | NEWTONS2 手術, 手術室管理 (手術記事) | Not SS-MIX2 standardised; extended storage 手術記録 34874-8; DPC 様式1 A007010 and EF (K codes) [S26]; receipt SI | レセ電 診療行為 (K codes), MEDIS 標準手術・処置 (ICD9CM) [S14] | EF monthly and complete for billed procedures | Prior surgery, "no major surgery within 28 days" | Extended CSV `procedure` only [R `src`:67-68] | Card 12-11 (EF and 様式1) |
| 12 | 輸血 | 輸血管理システム | Order in NEWTONS2 (輸血 order [S15]); 実施 via barcode; EF (血液製剤 codes) | レセ電 drug codes | EF monthly | "Transfusion within 2 weeks" (haematology trials) | Not read | Card 12-11 |
| 13 | バイタル / 看護記録 / 経過表 | 看護業務支援 (ICU 経過表, monitor capture) | Not SS-MIX2 standardised (JLAC10 9N001/9N006 height and weight can be OBX [S20]); extended storage 看護記録 28623-7; DPC H file (看護必要度) | Local | Full in the system; seldom exported [O] | BP thresholds, weight and BMI, ECOG-like function (看護必要度, ADL) | Extended CSV `vital` [R `src`:67-68] | Ask SSI for a 経過表 export (question 14); H file (card 12-11) |
| 14 | 診療録 SOAP | 新版e-カルテ | Extended storage 外来診療録 34108-1, 入院診療録 34112-3, 経過記録 11506-3 (if the vendor exports "医師カルテ" [S14]); DB | Free text, templates | Full; real time in the DB; export varies by site [O] | Everything not coded: symptoms, PS, history, refusals | Notes from the CSV, or extended storage of the old layout | Cards 12-4, 12-15, 12-16 |
| 15 | 退院サマリ | e-カルテ, 病歴管理 | Extended storage 退院時サマリ 18842-5; HS032 CDA [S14, S25] | Text; CDA sections | Complete for inpatients; days after discharge | Past history, the course of illness | Read only with a 6-level layout | Card 12-4 (CDA too) |
| 16 | 紹介状 / 診療情報提供書 | e-カルテ 文書管理, 連携ナビ | Extended storage 診療情報提供書 57133-1; HL7J-CDA 電子紹介状 (HS008) [S14, S25] | Text | Per referral | Referred patients, prior treatment elsewhere | As 14 | Card 12-4 |
| 17 | 同意書 and scanned documents | 文書管理, スキャナ取り込み | Extended storage 同意書 59284-0, 臨床研究同意書 77602-1, 手術同意書 61358-8 [S25]; PDF and images | None | Full; often a scan without text [O] | Prior research consent; opt-out flags | PDFs without text are counted [R `src`:283-291] | OCR (`services/sitesetup/ocr.py` exists for intake; not wired to extended storage) [R] |
| 18 | アレルギー / 禁忌 | NEWTONS2 禁忌情報管理 | **ADT-61** (ADT^A60, IAM: allergen code HOT9 / JLAC10 / 99XYZ, IAM-6 action) [S20] | HOT9, local | Full; real time | Hypersensitivity exclusions | Not read [R `src`:94-100] | Card 12-5 (also 01 (a)) |
| 19 | 問診 | e-カルテ templates, 外来問診票 | Extended storage 外来問診票 89430-3 [S25]; templates in DB | Local template items | Variable | Smoking, alcohol, pregnancy, symptoms | Not read | Template registry (card 12-16) |
| 20 | 栄養 | 給食, NST, 栄養指導 | **OMD** (OMD^O03) diet orders [S22]; 栄養指導書 78451-2; DPC 様式1 A004030 栄養情報 [S26] | Local | Full | Tube feeding, NPO, "able to swallow tablets" | Not read | Card 12-8 |
| 21 | リハビリ | リハビリシステム | Extended storage 理学療法記録 28579-1; EF (H codes); DPC ADL and FIM [S26] | Local, レセ電 | EF monthly | Functional status | Not read | Card 12-11 |
| 22 | 化学療法レジメン | 抗がん剤プロトコルシステム | OMP-02 lines (one per drug); Ver.1.2i adds regimen unit codes [S20]; regimen name not standard | HOT/YJ per drug; local regimen ID | Full in the module | Line of therapy, prior platinum, cycles | Drugs only, as orders | Ask for a regimen export (question 17); regimen table in the site profile |
| 23 | がん登録 (院内 / 全国) | がん登録システム | 全国がん登録 届出 (an electronic file, 29 items [NV]); 院内がん登録 標準登録様式 2016 (99 items [NV]); ICD-O-3, UICC TNM | ICD-O-3, TNM | Complete for cancers seen; months of lag | Primary site, histology, stage at diagnosis, first treatment | Not read | Card 12-13 |
| 24 | DPC (様式1, D, EF, H, K) | DPC関連システム | FF1 様式1 (payload codes A000010 … M180021), D, EF統合 (31 columns, EF-1 … EF-31), H, K [S26] | ICD-10 (2013), レセ電 傷病名 and 修飾語, K codes, UICC TNM, JCS, Hugh-Jones, NYHA, mRS, Barthel, SOFA | Complete for inpatients; monthly | Stage, ADL, main diagnosis (主傷病), comorbidities, every billed drug and procedure | Not read | Cards 12-11, 12-12 |
| 25 | レセプト (医科, DPC) | 医事会計 | UKE file: records IR, RE, HO, KO, SN, JD, MF, GR, **SY, SI, IY, TO, CO, SJ** [S28] | レセ電 7-digit 傷病名, 9-digit 診療行為 and 医薬品 | Complete for billed care; monthly | Long history (outpatients too); 公費; 主傷病 (SY 主傷病 field) | Not read. The `claim` table is Taiwan's prior-approval shape [M6] | Card 12-12 |
| 26 | 健診 | ドック・健診 | Its own system; extended storage 検診・健診報告書 53576-5 [S25]; 特定健診 XML (the ministry's format) [NV] | JLAC10 for items | Annual | Baseline values, smoking, healthy-volunteer trials | Not read | Ask (question 18) |
| 27 | 予約 | NEWTONS2 予約管理, Web 予約 | Not in SS-MIX2 standardised storage; DB; IHE SWF for radiology [S11] | Local | Real time | "Next visit date" for the coordinator's contact plan | Extended CSV `appointment` [R `src`:67-68] | Ask for an export (question 15) |
| 28 | 治験 flags | NEWTONS2 治験管理 [S2] | Not standardised | Local | Real time | "Not in another trial" | Not read | Ask (question 30) |

---

## 4. SS-MIX2 in depth, from the published specification

### 4.1 The documents and their versions

All JAMI documents were downloaded on 2026-11-18. Each is "Copyright © JAMI". I read the terms of reuse nowhere, so
this review cites them and copies no text beyond short quotations.

| Document | Version, date | Where |
| --- | --- | --- |
| SS-MIX2 標準化ストレージ仕様書 (data storage and message definitions), 169 pages | **Ver.1.2i, 2024-05-16** | S20 |
| …コード表, 52 pages | Ver.1.2i, 2024-05-16 | S21 |
| 標準化ストレージ 構成の説明と構築ガイドライン, 44 pages | Ver.1.2h, 2022-03-31 | S22 |
| …別添 複数ボリューム管理 | Ver.1.2h, 2022-03-31 | S23 |
| 拡張ストレージ 構成の説明と構築ガイドライン, 27 pages | Ver.1.2h, 2022-03-31 | S24 |
| …別紙 標準文書コード表 | Ver.1.2h, 2023-08-30 | S25 |

It is an MHLW standard (HS026), listed in SSI's catalogue [S14]; ISO/TS 24289:2021 was seen only in a search
summary [NV]. The consortium site www.ss-mix.org failed its TLS certificate check on 2026-11-18, so its sample data is
unseen [NV]. The reader's docstring cites "仕様書 v1.2" and "v1.2h 表 3-47" [R `src`:4, 603]; Ver.1.2i changed only an
MSH-7 typo and added regimen unit codes [S20, revision history].

### 4.2 Folder layout and file names [S22 2.2, 3.1]

```
<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日 YYYYMMDD | ->/<データ種別>/<pid>_<診療日>_<データ種別>_<オーダNo>_<発生日時 17>_<診療科>_<flag>
```

- The root's name is free (the guideline recommends the 10-digit 医療施設 ID). No file extension; JIS (ISO-2022-JP).
- **Order No is "ALL9"** for data not managed by an order (患者基本, 病名, アレルギー). For admissions and transfers that
  can happen more than once a day it is **a number that tells the day's events apart**.
- The 診療日 is fixed by table 3.1-1: PPR-01 and ADT-00 "-"; ADT-12 PV1-44; OML-11 SPM-17; OMP-01 ORC-9 (the day the
  order was entered, not the day the drug starts); OMP-11 RXA-3.
- **Very large storages may be split into several roots** (by year or type) named in a 「マニフェスト」; a reader "must
  search all root folders" [S23].

### 4.3 The full list of message types in 標準化ストレージ [S22 table 3.1-2]

| Type | Name | HL7 | Type | Name | HL7 |
| --- | --- | --- | --- | --- | --- |
| ADT-00 | 患者基本情報の更新 / 削除 | ADT^A08 / A23 | OMP-01 | 処方オーダ | RDE^O11 |
| ADT-01 | 担当医の変更 / 取消 | ADT^A54 / A55 | OMP-11 | 処方実施通知 | RAS^O17 |
| ADT-12 | 外来診察の受付 | ADT^A04 | OMP-02 | 注射オーダ | RDE^O11 |
| ADT-21 | 入院予定 / 取消 | ADT^A14 / A27 | OMP-12 | 注射実施通知 | RAS^O17 |
| ADT-22 | 入院実施 / 取消 | ADT^A01 / A11 | OML-01 | 検体検査オーダ | OML^O33 |
| ADT-31 | 外出泊実施 / 取消 | ADT^A21 / A52 | OML-11 | 検体検査結果通知 | OUL^R22 |
| ADT-32 | 外出泊帰院実施 / 取消 | ADT^A22 / A53 | OMG-01 | 放射線検査オーダ | OMG^O19 |
| ADT-41 | 転科・転棟予定 / 取消 | ADT^A15 / A26 | OMG-11 | 放射線検査の実施通知 | OMI^Z23 |
| ADT-42 | 転科・転棟実施 / 取消 | ADT^A02 / A12 | OMG-02 | 内視鏡検査オーダ | OMG^O19 |
| ADT-51 | 退院予定 / 取消 | ADT^A16 / A25 | OMG-12 | 内視鏡検査の実施通知 | OMI^Z23 |
| ADT-52 | 退院実施 / 取消 | ADT^A03 / A13 | OMG-03 | 生理検査オーダ | OMG^O19 |
| ADT-61 | アレルギー情報の登録 / 更新 | ADT^A60 | OMG-13 | 生理検査結果通知 | ORU^R01 |
| PPR-01 | 病名（歴）情報の登録 / 更新 | PPR^ZD1 | OMD | 食事オーダ | OMD^O03 |

That makes 26 types. The ADT-52 row in TrialBox's docstring adds A06/A07 class changes [R `src`:17-21]. The
specification's table has no class-change type.

### 4.4 Transactions, snapshots, deletions and corrections [S22 3.1.2–3.1.4]

**Every change is a new file.** Files are never deleted. The record's key is **(patient ID, 診療日, データ種別,
オーダNo)**, and the 診療日 is part of it [S22 3.1.4 (2)⑥].

**Condition flags:** **1** valid, **0** invalid or deleted, **2** past history (過去履歴: an earlier valid result kept
as history, as opposed to a correction). **The gateway:** on an INS it **renames** the current flag-1 file to 2, then
writes the new file with flag 1; on a DEL it renames flag-1 and flag-2 files to 0 and writes the cancelling message
with flag 0; a correction is a DEL then an INS.

So the newest timestamp per key gives the state, and flag 0 on the newest file is a delete. That is how the reader
works, except for the key (4.10 F1) [R `src`:362-397].

**PPR-01 is a snapshot, not a transaction.** One file holds **all** of a patient's diagnoses [S22 3.1.2 (2)]. Whether
each PRB is added, updated or deleted is said by **PRB-1** (HL7 table 0287) [S20 表 3-47].

**OML-11 corrections are carried by OBX-11**, which the reader handles [R `src`:801-814].

**Extended storage keeps the same flags**, on the **content folder** [S24 2.2 (5)④].

### 4.5 What 拡張ストレージ carries, and how it varies [S24, S25]

**Layout:**

```
<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別 folder>/<content folder>/<files, optional _contents.xml>
```

**The data-type folder** is named like a CWE:
`[local code]^local name^[local system]^LOINC document code^standard name^LN`. For example:
`L010234^牽引療法記録^99H16^28579-1^理学療法記録^LN`.

The LOINC part is mandatory since 1.2d; readers must also accept local-only names; search should use the LOINC
code.

**The content folder** is named like a standardised file:
`pid_診療日_文書コード_特定キー_発生日時_診療科_flag`. It is mandatory, but old storages may lack it.

**The 診療日 may be YYYYMM** (monthly items such as receipts), **YYYY**, or "-" (bulk scans).

**The standard document codes** are 120 distinct LOINC codes [M12] grouped as 指導書, 証明書, 同意書, 処方箋, 指示書,
問診票, 報告書, 記録, 歴, 要約, 計画書 [S25]. The vendor lists 退院サマリ, 診療情報提供書, 医師カルテ and 看護カルテ as what SSI writes
there [S14].

**Variation** [O, from the guideline's own escape clauses]: free file formats (PDF, HTML, XML, CDA, images);
per-site "データ種別一覧表" rules for the 診療日; whether a content folder exists; whether local codes start with "L".

The circulatory society found ECG, echo and catheter results in extended storage "in non-standard formats", hard to
reuse [NV, search summary of the JCS data-output guideline]. A study of NEJM trial datasets found SS-MIX2 could supply
only 13 % (dementia) to 62 % (diabetes) of the variables [S32].

### 4.6 Codes in practice

**What the specification recommends** [S20]:

| Data | Recommended code |
| --- | --- |
| 病名 | MEDIS 病名管理番号 (MDCDX2), with ICD-10 in PRB-10 |
| Drugs | HOT (HOTnn) in RXE-2; YJ or 厚労省コード in RXE-31 |
| Labs | JLAC10 (JC10) or JLAC11 (JC11) in OBX-3 |
| Usage (用法) | JAMI 標準用法 (JAMISDP01) in TQ1-3 |
| Elsewhere | Local codes "99XYZ" |

**What sites actually do:** MID-NET's governance centre (18 hospitals, from July 2020) found that after 1.5 years
of monthly feedback only **36 % of drug codes, 29 % of lab codes and 67 % of disease codes** carried the correct
standard code [S29, 2026]; the same group built a real-time 標準病名 validation tool [S31]; MID-NET reports near-100 %
agreement between source and copy **after** that work [S30].

[O] At a single non-MID-NET hospital, expect local codes first and standard codes patchy, above all for labs. The
reader's `unmapped` work list [R `src`:886-910] is the right tool. It needs the site profile (section 7) to close
the loop.

### 4.7 Pitfalls reported in the literature

| Pitfall | Evidence |
| --- | --- |
| Standard codes missing or wrong at source | S29, S31 |
| 病名 alone is a weak case definition. PPV for diabetes from claims 40.7 %, from SS-MIX2 prescriptions 44.7 %; hyperthyroidism from 病名 20–30 %, over 60 % with drugs; acute renal failure up to 80–90 % with creatinine history | S33 |
| DPC diagnoses: specificity above 96 %, but sensitivity under 50 % for 7 of 16 diseases. SS-MIX lab values agree with charts above 95 % | S34 |
| Combining EMR, DPC and claims: PPV 78 % for acute heart failure; the most sensitive algorithm has the lowest PPV | S35 |
| Coverage of trial variables 13–62 % | S32 |
| Some definitions are not even in standardised storage (ORC repetition in OMG^O19 differs from JAHIS) | search summary of a HELICS Q&A [NV] |
| No established quality-verification procedure for vendor SS-MIX2 output; customisation per vendor and per site | AMED report, search summary [NV] |

### 4.8 Update timing [S22 3.1.4; O]

- A gateway receives one message per send and writes it at once, so storage is near real time.
- Some sites build it by batch from the HIS database ("直接アクセスして構築"). Their delay is the batch interval.
- Past data may be bulk-loaded, with transaction times that differ per file.

The reader re-walks the whole tree each night (01 §1.3). For a hospital of several hundred beds that is millions of files [O], so
card 12-9 adds a delta by file stamp.

### 4.9 Conformance: TrialBox's reader against the specification

**Legend:** Parsed = the reader reads it to the specification. Partly = read, but fields or semantics differ. Not =
the type is not read. `src` = `services/adapter/sources/ssmix2/source.py`.

| Type | State | Where (`src`) | What differs or is missing | Card |
| --- | --- | --- | --- | --- |
| Tree, names, flags 0/1 | Partly | 160-165, 362-397 | Flag 2 handled by "newest wins". **The key drops the 診療日 by default** (D-594), against S22 3.1.4 (F1) | 12-1 |
| Multi-volume manifest | Not | 321-326 (one root) | S23 | 12-9 |
| ADT-00 | Partly | 529-546 | IN1 not read; A23 (delete) read only as flag 0 | 12-6 |
| ADT-01 | Not | 94-100 | Doctor in charge | 12-6 |
| ADT-12 | Partly | 548-565 | Collapses under the default key [M4] | 12-1 |
| ADT-21, 31, 32, 41, 42, 51 | Not | 94-100 | Transfers, leave, planned discharge | 12-6 |
| ADT-22 | Partly | 548-565 | A11 cancellation counted only through flag 0 | 12-6 |
| ADT-52 | Partly | 567-600 | A13 (cancel discharge) is not undone; a non-A03 event with PV1-2 is taken as a class change (590-597) | 12-6 |
| ADT-61 | Not | 94-100 | IAM allergies | 12-5 |
| PPR-01 | Partly | 602-642 | F2: PRB-1, PRB-7, PRB-9, PRB-10, PRB-14 (only "R"), PRB-15, PRB-18, ZPR not read | 12-2 |
| OMD | Not | – | Diet | 12-8 |
| OMP-01, OMP-02 | Partly | 686-697 | F3: RXE-31 YJ not read; RXE-3 is per time, stored as `daily_dose`; TQ1-3 用法 not read; RXE-12 refills | 12-3 |
| OMP-11, OMP-12 | Partly | 699-727 | RXA-6 stored as `daily_dose` (it is the amount given) | 12-3 |
| OML-01 | Not | – | Lab orders ("ordered but no result yet") | 12-7 |
| OML-11 | Parsed | 729-814 | JLAC10 / JC11 triples, value types, corrections, tombstones, sample-time fallbacks. Microbiology shape untested | 12-7 |
| OMG-01, 02, 03 | Not | – | Imaging, endoscopy, physiology orders | 12-7 |
| OMG-11, 12 | Not | – | 実施 (OMI^Z23) | 12-7 |
| OMG-13 | Not | – | Physiology results (ORU^R01) | 12-7 |
| 拡張ストレージ | Partly | 817-853 | F4: content folder level, CWE+LOINC folder names, YYYYMM/YYYY days, `_contents.xml` not read [M5] | 12-4 |
| Character sets | Parsed | `hl7.py`:183-214 | Strict decoding with quarantine; ahead of the specification | – |

**Score** [R, counted from the table]: of the 26 types, **1 parsed, 8 partly, 17 not**. On top of that the tree
layout and extended storage are partly done.

Five SS-MIX2-named test files hold 34 tests [M9]. Every SS-MIX2 test builds its messages either from
`tools/ssmix2_export.py` or inline. The export writes:

- PPR-01 as **one file per diagnosis, under its diagnosis day, with PRB-3 "code^name^99XYZ"** [R
  `tools/ssmix2_export.py:175`; M2]. The specification says one file per patient under "-", with MDCDX2 and ICD-10 in
  PRB-10;
- documents under `DSC-01` and `RPT-01` folders [R `tools/ssmix2_export.py:257-265`]. Those are not specification
  names.

So the tests confirm the reader against the exporter, and both share the same misreading [O].

### 4.10 The four findings in detail

**F1. The record key (default `unique`)** [R `src`:373-374; M4; S22 3.1.2–3.1.4].

- **The probe:** three ADT-12 files, on three days, all with order No "ALL9". Under `unique` the reader returned
  **1 visit** (the newest). Under `per_day` it returned 3. The same happens with order No "1" (a per-day sequence).
- **What it breaks:** visit counts ("seen in the last year"), admissions, and ADT-52 discharges (only the newest is
  kept per patient, so earlier admissions stay "in-progress").
- **What D-594 already gives:** a count of order numbers seen on several days, so a site check would see this. But the
  default is the unsafe choice for a specification-conformant storage.
- **Proposal:** default to the specification (`per_day`). Keep `unique` as the site's declared exception, and treat
  ALL9 and ADT types as day-keyed always [O].

**F2. PPR-01** [R `src`:602-642; S20 表 3-46, 3-47; S21 表 95–97].

| Field | What the reader does | What the specification says | What goes wrong |
| --- | --- | --- | --- |
| PRB-1 action | Ignored | DE deletes the diagnosis | A deleted 病名 is read as active |
| PRB-10 ICD-10 | Not read (ICD-10 looked for in PRB-3's alternate) | `K297^^I10^O^外来時^JHSD0004` | A site that writes the standard shape gets ICD-10 only through a licensed MEDIS look-up of PRB-3 (MR-017, open since 2026-11-09) |
| PRB-14 転帰 | Only "R" or "resolved" counts as resolved (640) | HL70241 (D, F, N, P …) or JHSD0006 (I 中止, M 寛解, C 継続, O その他) | Cured (F) and died (D) stay active |
| PRB-9 終了日, PRB-15 転帰日 | Not kept | – | "Resolved before screening" cannot be asked |
| PRB-7 診断日 | Used only as a fallback for `recorded_date` (639) | The diagnosis date | – |
| PRB-16 発生日 | Used as `diag_date` (638) | The onset date | The specification's example: fracture on 7/1 (PRB-16), diagnosed on 7/10 (PRB-7) |
| PRB-18 病名区分 | Not read | 1 主診断 / 2 副診断 | "Primary diagnosis" cannot be asked |
| ZPR modifiers | Not read | Prefix and suffix 修飾語 (the 疑い suffix included) | The fallback "疑い in PRB-3 text" (210) misses it, because PRB-3 is the base name. The written name is PRB-17 |

**F3. Medicines** [R `src`:686-727; S20 RXE-2, RXE-3, RXE-31, Ver.1.2g/1.2h revision notes].

- RXE-3 is "一回分の投薬量" (one dose); the reader stores it as `daily_dose` (694), and RXA-6 likewise (712). The
  doses a day are in TQ1-3 (JAMI 標準用法), not read. Card 9h-8 (dose criteria) would be fed wrong numbers.
- YJ in RXE-31 is not read; a site whose RXE-2 is HOT resolves only through its drug master.

**F4. Extended storage** [R `src`:817-853; M5; S24 2.2].

- The reader globs exactly six levels and expects the file in the data-type folder. The specification has a content
  folder in between, so files sit seven levels deep. They are skipped as directories.
- Folder kinds are matched by prefixes (DSC, SUM, RPT …) [R `src`:139-141]. The specification's folder names begin
  with the local code, or "^", and carry the LOINC code. Every document would become `document`.
- `_contents.xml`, CDA (HS032 summaries, HS008 referrals) and YYYYMM or YYYY days are not handled.

### 4.11 Cards to reach "complete" (detail in section 12)

First 12-1 to 12-4 (they change counts), with 12-10 (a conformant synthetic storage, one fixture per type, so 1 to 4
are proved against the standard); then 12-5 and 12-6; then 12-7, 12-8, 12-9. The vendor sample (plan 9 revision 2, decision 7, and criterion 13 line 10) remains the final proof.

---

## 5. What is not in SS-MIX2, and how else to get it

| Source | What it adds for patient finding | Public layout | Who must agree | Cost and lead time in Japan | Risk | Verdict [O] |
| --- | --- | --- | --- | --- | --- | --- |
| **DPC 様式1 (FF1)** | 主傷病, 入院契機, 医療資源病名, 併存症, 続発症 (ICD-10 plus レセ電 codes and 修飾語); operations; height, weight, smoking index; ADL and Barthel; JCS; mRS; Hugh-Jones; NYHA; UICC TNM and stage; chemotherapy; SOFA; pregnancy; dementia scale [S26 payload codes A000010 … M180021] | Yes: MHLW 2025年度 実施説明資料, 2025-05-30, about 15,700 text lines [S26] | Hospital (医事課 / 診療情報管理室); the files exist already | No vendor work: a copy of the monthly submission. Lead time is the hospital's internal approval [O] | Inpatients only; quarterly or monthly lag; coded by 診療情報管理士 (good quality) | **Do first** |
| **EF統合 (inpatient and outpatient)** | Every billed procedure, drug, material and 持参薬, by day (EF-24 実施年月日), with ward and doctor [S26 EF-1 … EF-31] | Yes [S26] | As above | As above | Billing view; DPC hospitals only for outpatient EF (データ提出加算2) | **Do first** |
| D, H, K files | D: the DPC group. H: daily 看護必要度. K: a hashed common ID from birth date, kana name and sex (for NDB linkage) | Yes [S26] | As above | As above | K is identifying-derived: do not read it [O] | H yes; D optional; K no |
| **レセプト (UKE)** | Long outpatient history; 主傷病; SY 転帰; 公費 | Yes: 記録条件仕様 医科, updated 2026-10-01 [S28]. The レセ電 masters are site-fetch (06 O-4) | Hospital 医事課 | Monthly file already made for the payer | Billing view; 保険病名 | **Second** |
| 院内がん登録 / 全国がん登録 | Site, histology, stage, first treatment | National layout public (29 items) [NV]; hospital-based 2016 format (99 items) [NV] | Hospital がん登録 staff; 全国がん登録 data use is restricted by the cancer registry law [NV, review 11] | Export from SSI's がん登録 module | Months of lag | **Third**, for oncology trials |
| **Vendor DB replica (SQL Server)** | Everything: notes, templates, vitals, 経過表, regimens, appointments, 治験管理 | No. "Disclosed under an NDA" [S2, S14] | **SSI and the hospital**: an NDA, a read-only replica or view, sizing | Not public [NV]. Interfaces outside the standard cost extra [S14] | Schema changes with versions; load on the production DB; each site differs; TrialBox has no SQL Server driver [M7] | **Later, by agreement**, for notes and templates only |
| Vendor DWH and dashboard, SSI SCOPE | Saved searches, indicators | No | SSI | Not public | Aggregates only [O] | Ask; do not build on it |
| HL7 v2 live feed (JAHIS 病名, 処方, 注射, 放射線, 臨床検査 v2.5 over TCP/IP socket) [S14] | Same content as SS-MIX2, real time | JAHIS conventions (member documents, NV) | SSI (interface licence) | "追加費用：有" [S14] | Another listener in the hospital zone; MLLP not built (01) | Not needed if SS-MIX2 is on |
| IHE PDQ, XDS.b document consumer [S11, S14] | Patient lookup; documents from a regional XDS | IHE frameworks | SSI, regional network | Not public | Documents again, by another route | No for 1.0 |
| 電子カルテ情報共有サービス (FHIR, 3文書6情報) | 傷病名, アレルギー, 感染症, 薬剤禁忌, 検査, 処方; 診療情報提供書, 退院時サマリー, 健診結果 [NV, search summary] | MHLW technical guide [NV] | National service; vendor | National programme | A national exchange, not a hospital export [O]; review 11 | Watch; JP Core already read [R `services/adapter/mapping/jp_core/ssmix2_site.yaml`] |
| Document systems (scans) | Consent, outside letters | No | Hospital | OCR on the box | Scans without text | OCR later (card 12-4 counts them) |

---

## 6. REDCap at the site

**What a Japanese site's REDCap usually is** [NV for every item: search summaries only; the pages reset the
connection when I tried to open them]: university or ARO instances run by a clinical research centre (Kobe, Kyoto,
Kyushu, Ryukyu); a Japan REDCap Consortium run from Osaka City University that reported **about 60 non-profit
institutions in Japan in August 2021**; attempts to pull chart data into REDCap through FHIR (Clinical Data Pull)
that hit the separation of hospital networks from the internet.

[O] At the first site, REDCap is most likely one of two things: an ARO's or a partner university's instance reached from the
hospital, or the owner's own (D-1060). Its projects hold CRFs for investigator-initiated studies and registries. The
chart is the source; REDCap is the copy typed by coordinators. That makes **REDCap a second source for patient
finding in registries**: patients already enrolled in a disease registry are candidates.

**What TrialBox's link does today** [R]:

- One `ProjectLink` per study: one REDCap project id, one token ref, **one DAG**, and the fields for screening number,
  consent, enrolment, screen-fail and withdrawal [R `services/rc_bridge/link.py:36-55`].
- Only the screening-number link mode exists; `mrn` is refused [R `services/rc_bridge/link.py:21`].
- Rows outside the link's DAG are counted (`outside_dag`). A group-bound export with no group column is handled
  [R `services/rc_bridge/link.py:209-250`].
- Write-back of three TrialBox-owned fields, with the DAG column set [R `services/rc_bridge/writeback.py:94-95,
  166-167`].
- The EDC door maps a study to a project, **a site to a DAG**, and a subject to a record id [R
  `services/edc_backend/linkmap.py:1-5`; `docs/data/13-redcap-and-the-edc-backend.md:205-207`].
- Version span: 13.7 through 17 on the door, 14 to 17 on the study-link page
  [R `docs/data/13-redcap-and-the-edc-backend.md:53-70`].

**What is missing for multicentre work** [O]:

1. **A link per (study, site)**, not per study. A multicentre project with one DAG per site needs one TrialBox site
   to see only its own DAG, and the coordinating centre to see all of them. Today one link holds one DAG, and the
   coordinating-centre view is not modelled.
2. **Project-per-site studies.** Some Japanese multicentre IITs give each site its own project. That needs N links
   for one study and a merged view.
3. **Record ids across sites.** REDCap's DAG-prefixed auto-numbering (`<dag>-n`) is assumed nowhere. The screening
   number must be unique across sites.
4. **REDCap as a finding source.** A registry project read through the adapter, as candidates with consent already
   given for contact. No `redcap` source exists [R `services/adapter/sources/`].
5. **Japanese privacy wording.** Section 13 names only Taiwan's PDPA for the IRB paragraph
   [R `docs/data/13-redcap-and-the-edc-backend.md:140`]. APPI and the ethics guideline belong to review 11; one line
   should point there.
6. **The 2026 survey-passthrough advisory.** Already noted for 13.7.23 [R `docs/data/13-redcap-and-the-edc-backend.md:84-87`].
   Ask the first site's version (question 28).

The EDC's private repository was not read (D-1060).

---

## 7. "Inherently fulfil the on-site clinical varieties": a site profile

**What the box does today to absorb a site** [R]:

| Variety | Where it is absorbed today | Code change needed for a new site? |
| --- | --- | --- |
| Local diagnosis, lab and drug codes | Mapping YAML `extends` and lookups (`byomei_to_icd10.csv` 32 rows, `jlac10_to_loinc.csv` 14, `yj_to_atc.csv` 22 [M10]); the licensed-master loader; drug master and ingredient-ATC (T-610); the steward confirms suggestions once (D-131, D-135) [R `services/sitesetup/mapping.py:1-15`] | No (data) |
| Messy sheets (era dates, full-width text, units) | `services/sitesetup/messy.py:1-20` (D-132) | No |
| Lab units per analyte | `libs/tb_common/labvalue.py` conversions | Partly: a new unit spelling is a code change [R `libs/tb_common/labvalue.py:86`] |
| SS-MIX2 order-key habit | Environment variable `TB_SSMIX2_ORDER_NUMBERS` [R `src`:102] | No, but it is not in a profile and the default is wrong (F1) |
| Document types | `_DOC_KINDS` prefixes in code [R `src`:139-141] | **Yes** |
| Specimen names | `_MATERIAL`, then the licensed release [R `src`:137] | Partly |
| Note headings | One regular expression for bracket headings, used to cut excerpts [R `services/matching/excerpts.py:132-143`]. No section types, no family-history or negation scope by section | **Yes** |
| 用法 (frequency), templates, order sets, regimens | Not modelled | **Yes** |
| Departments and wards | `dept_code` passed through | No meaning attached |

**Design** [O]. Each site has one versioned folder on the box, beside its mapping YAML. It is filled by the steward
through the site-setup pages, checksummed, and loaded at ingest like the licensed masters. Every table has a reader,
a coverage line in the ingest report and a "not yet mapped" work list. **No table needs code to add a row.**

```
site-profile/<site>/
  profile.yaml          identity (医療機関コード 10 digits), vendor, product, version; storage roots and volume manifest;
                        record-key rule per data type (default: the standard's); time zone; charset expectation;
                        update cadence; which doors are on (ssmix2, dpc, uke, cancer, db)
  codes/diagnosis.csv   院内病名コード -> 病名管理番号 -> ICD-10 (WHO) ; flags: 保険病名-prone (yes/no)
  codes/drug.csv        院内薬剤コード, HOT, YJ, レセ電, ingredient stem, strength, unit, form   (T-610's master, kept)
  codes/lab.csv         院内検査コード, JLAC10/11, LOINC, unit, UCUM, analyte factor, material, ref range
  codes/usage.csv       local 用法 -> JAMI 標準用法 -> doses per day, timing, PRN   (feeds dose criteria, 9h-8)
  codes/dept.csv        診療科コード -> specialty (and the trial teams that care about it)
  codes/units.csv       spelling -> UCUM (e.g. "ｍｇ/ｄＬ", "×10^3/μL", "IU/L" as U/L for enzymes)
  codes/result_words.csv 陽性/陰性/(+)/(2+)/判定保留 -> answer codes   (extends labvalue.presence)
  documents.csv         data-type folder or local doc code -> LOINC doc code -> note_type -> section scheme -> date rule
  sections.yaml         per section scheme: heading patterns (S)(O)(A)(P), 【現病歴】【既往歴】【家族歴】, ＃n problems,
                        templates' fixed labels; each section's role: history | family | plan | finding | negated-list
  templates.csv         template id/name, field -> canonical observation (e.g. ECOG PS -> LOINC 89247-1; NYHA; 喫煙)
  regimens.csv          local regimen id -> name, drugs (stems), line-of-therapy class
  synonyms.csv          院内略語 and words -> concept (DM, HT, RA, CKD, "Ｋ" for 癌 in some wards …)
  order_sets.csv        set id -> what it implies (e.g. "化学療法入院セット" -> chemotherapy admission)
```

**How it works in the code** [O]:

- Ingest loads `profile.yaml` and turns every table into a lookup in the terminology store, as `adapter.licensed`
  does today.
- The SS-MIX2 reader asks `documents.csv` for a note's type and date rule, and `usage.csv` for doses per day.
- The note pipeline asks `sections.yaml` which section a sentence is in. "糖尿病" under 【家族歴】 is then never
  evidence for the patient. A 【既往歴】 item is "history of", not "active".
- `templates.csv` turns template fields into coded facts, not free text.
- Each row has `source`, `confirmed_by` and `confirmed_at`. A change is an audit event and a "re-run" trigger (V30 in
  plan 9 revision 2).

**Proving test** [O]: a second synthetic Japanese hospital is generated from a different profile: other local codes,
document folders, headings, 用法 codes and templates. It must load with **no code change** and give the same
eligibility funnel as the first hospital on the same synthetic patients (card 12-14).

---

## 8. A synthetic Japanese hospital

### 8.1 What exists today [M1–M3, M6, M9]

| Item | Measured |
| --- | --- |
| Generator | `tools.synth_hospital` run with profile `ci` and site `jp-a:JP:400` (400 patients) gave 12 CSV tables in 0.2 s [M1] |
| SS-MIX2 export | `tools.ssmix2_export --hard-cases` |
| ADT-00 | 407 files |
| ADT-12 / ADT-22 / ADT-52 | 2,653 / 68 / 68 |
| PPR-01 | 1,142, **one per diagnosis, dated** |
| OMP-01 / 02 / 11 / 12 | 2,744 / 165 / 1,077 / 109 |
| OML-11 | 1,900 |
| Extended storage | 16 discharge-summary files (`DSC-01`) and 14 report files (`RPT-01`), **no content folders** |
| Extended CSVs | 8 |
| Distinct codes | 32 diagnosis codes, all in the local `99XYZ` style, none MDCDX2; 13 lab codes; 42 drug codes. RXE-2 systems: 1,459 `99YJ`, 1,450 `HOT` [M2] |
| PRB fields | PRB-13 is empty in 1,142 of 1,142 messages; no PRB-10, PRB-14 or PRB-18 [M2] |
| Notes | 703 notes, **703 of 703 typed `progress`**, Japanese prose with no SOAP or 【】 headings in the sample read [M3]. The AD archetype adds 【アミロイドPET】-style report headings [R `tools/synth/notes_ja.py:119-135`] |
| `claim.csv` | 63 rows of Taiwan prior-approval shape (product code `KC…`, apply type, approval dates) [M6]; no Japanese receipt or DPC files anywhere in the repository [M11] |
| Message types never generated | ADT-01, 21, 31, 32, 41, 42, 51, 61; OML-01; all OMG; OMD [M1] |

### 8.2 What the synthetic hospital must contain to prove sections 3 to 7 [O]

1. **A conformant storage**, built from the specification and not from the reader:
   - all 26 types;
   - PPR-01 as one snapshot per patient, with PRB-1 AD/UP/DE, MDCDX2, PRB-10 ICD-10, PRB-13/14/15/18 and ZPR;
   - ADT order No "ALL9" or a per-day sequence;
   - RXE-2 HOT9 with YJ in RXE-31, TQ1-3 JAMI usage, and RXE-3 as one dose;
   - flag-2 history renames and DEL pairs;
   - a two-volume manifest;
   - extended storage with CWE+LOINC folders, content folders, `_contents.xml`, one CDA discharge summary, one CDA
     referral, one text-less PDF scan, YYYYMM and "-" days, and old-layout folders without content folders;
   - a mix of character sets (kept from T-615a).
2. **DPC files** for the same patients:
   - FF1 様式1 with the payload codes of S26, including TNM, ADL and JCS;
   - EF統合 rows (EF-1 … EF-31) for drugs, procedures (K codes) and 持参薬;
   - H file rows.
3. **UKE receipts** with IR, RE, HO, KO, SY (with 主傷病 and 転帰), SI, IY, TO and CO [S28].
4. **A cancer-registry CSV** in the hospital-based 2016 shape, once its item list is read (card 12-13).
5. **Japanese notes** by document type (外来 SOAP, 入院経過, 看護記録, 退院サマリ, 病理, 読影) that include:
   - S/O/A/P sections, 【現病歴】【既往歴】【家族歴】 and ＃problem lists;
   - negation forms (認めない, なし, (-), 否定的);
   - 疑い and r/o;
   - 和暦 dates and half-width kana;
   - in-house abbreviations;
   - template-generated lines (PS: 1, NYHA II);
   - "保険病名" patients whose 病名 is not supported by labs or drugs.

   Every note needs a truth file of which criterion it answers.
6. **Two site profiles** that differ (section 7) over the same patients.

### 8.3 Public synthetic or sample sources

| Source | What | Licence | Use |
| --- | --- | --- | --- |
| JAMI specification appendix 1 "SS-MIX2 サンプル" [S20] | One sample message per type | © JAMI; reuse terms not read | Shape reference only; do not copy into fixtures without permission [O] |
| SS-MIX普及推進コンソーシアム sample data | Sample storage | Not opened (TLS failure) [NV] | Ask the consortium or SSI |
| MHLW DPC 実施説明資料 [S26], 記録条件仕様 [S28] | Layouts and examples | Government publications; terms not read [NV] | Layouts for the generator |
| MANBYO | Japanese disease names with ICD-10 | CC BY 4.0 (06) | Note vocabulary for the generator |
| JP Core IG 1.2.0 examples | FHIR examples | Not verified [NV] | Profile checks (the repository reads 1.1.0 [R `services/adapter/mapping/jp_core/ssmix2_site.yaml`]) |
| MID-NET / NDB open data | Code frequencies | NDB open data terms not read [NV] | Realistic code mix, if allowed |

---

## 9. Site-readiness questionnaire and first-week plan for the first site

### 9.1 Questions for hospital IT (医療情報部) and SSI

**System and versions**

1. Confirm the system: 新版e-カルテ and NEWTONS2. Which versions? Since when?
2. Which SSI departmental systems are in use: 臨床検査, 細菌, 病理, 輸血, リハビリ, 透析, 抗がん剤プロトコル, がん登録,
   DPC関連, 健診, 看護支援, Seavo PACS? And which third-party systems feed the chart (lab outsourcing, PACS, pathology)?
3. Database engine and version (SQL Server?), server OS. Is a read-only replica or a reporting view offered?

**SS-MIX2 standardised storage**

4. **Is the SS-MIX2 output option installed and running?** Standardised, extended, or both? Since when? Built by a
   gateway (real time) or by batch, and at what interval?
5. Storage location, size (files and GB), number of roots or volumes (a 「マニフェスト」?), and the root folder's name.
6. Which data types are written? Ask for the counts per type for one month (ADT-00 … OMD).
7. The order-number rule for ADT, PPR and ADT-61 ("ALL9"?). Are order numbers reused across days?
8. Character set (ISO-2022-JP "~ISO IR87"? Shift_JIS? UTF-8?). Is SS-MIX2 Ver.1.2 the basis, and which letter?
9. PPR-01: is ICD-10 written in PRB-10 or elsewhere? Which PRB-14 table (HL70241 or JHSD0006)? Are PRB-13 疑い and
   PRB-18 主診断 filled? Are ZPR modifiers written?
10. OMP: is RXE-2 HOT or local? Is RXE-31 YJ written? Is TQ1-3 the JAMI 標準用法 or local?
11. OML-11: is OBX-3 local plus JLAC10, and what share has JLAC10? Are outsourced results included? Is
    microbiology here?

**Extended storage and other data**

12. Extended storage: the 「データ種別一覧表」 (document types, LOINC codes, date rules); content folders and
    `_contents.xml`; file formats (text, PDF, CDA, HTML); **is 医師カルテ (SOAP) exported?**
13. Templates: which 問診 and assessment templates are in use (PS, NYHA, smoking)? Can their values be exported?
14. Vitals and 経過表: any export (CSV, HL7 OBX)?
15. Appointments: any export?
16. DPC: is the hospital a DPC hospital? Does it submit outpatient EF (データ提出加算2)? Can a monthly copy of FF1,
    EF, D and H be placed for the box (K excluded)?
17. Regimens: can the 抗がん剤プロトコル module export the regimen master and the patients' regimen courses?
18. 健診: a separate ID? Is linking to the chart allowed?
19. Receipts: can the monthly UKE file (医科, DPC) be copied?
20. Cancer registry: 院内がん登録 export format and refresh.

**Codes and masters**

21. Masters in use, with release dates: MEDIS 標準病名, HOT, JLAC10 or JLAC11, JJ1017, レセ電 masters, 標準用法.
    What share of local codes is mapped?

**Infrastructure and people**

22. Network: which zone can the box sit in? Can it reach the SS-MIX2 share read-only (SMB or NFS)? Is a one-way
    copy possible? Is there internet separation (three-layer separation)?
23. Hardware: where would the box stand; rack, power, UPS; who has physical access?
24. Who operates: 医療情報部 staff, SSI's ss-support staff, or both? Change windows?
25. SSI's maintenance line is a closed IP network with remote login [S8]. May TrialBox's box sit on the same zone,
    or must it be separate?

**Policy, REDCap and trials**

26. Data-use approval path: 倫理審査委員会, 情報管理委員会, opt-out notice (review 11).
27. **SSI**: cost and lead time for (a) SS-MIX2 option activation, (b) extended-storage SOAP export, (c) a DB view,
    (d) a 経過表 export?
28. REDCap: whose instance, which version, where hosted? Projects per study or per site? DAGs? API enabled?
    De-identified export rights?
29. Which coordinators will use the box, and on which terminals (internet-separated)?
30. **NEWTONS2 治験管理**: what does it hold (participation flags, visit schedules)? Can it be read? And SSI SCOPE:
    are saved searches available?

### 9.2 Sample exports to ask for (synthetic content only)

Each export must be made by SSI or the hospital from SSI's **test environment with dummy patients**, never from real
patients [O; owner's rule].

1. A **dummy-patient SS-MIX2 storage** from SSI's test system. At least three patients and one month, every data type
   the site writes, including deletions (flag 0) and corrections (flag 2).
2. **Extended storage** for the same patients: one 退院時サマリ, one 診療情報提供書, one 医師カルテ, one 看護記録, one
   病理 and one 読影 report, with the 「データ種別一覧表」.
3. The **local-code tables** with their mapping columns: 病名, 薬剤 (院内コード, HOT, YJ), 検査 (院内コード, JLAC10),
   用法, 診療科. Structure and a few dummy rows are enough.
4. **DPC sample files** (FF1, EF, H) from the DPC tool's test mode, or the hospital's layout notes if no test mode
   exists.
5. One **UKE** test file (医科), if the billing system has a test mode.
6. The **template list** (names and fields) and the **regimen master** layout.
7. The REDCap **data dictionary** of one current project (no records).

### 9.3 First week on site (ordered by what waits for what, no dates) [O]

| Step | Who | What | Done when |
| --- | --- | --- | --- |
| 1 | Hospital IT, the steward | Walk the questionnaire (9.1); place the box in the agreed zone; read-only mount of the SS-MIX2 root | Mount listed; questionnaire filed |
| 2 | Steward | Run the reader in count-only mode on the real storage, on the box: counts per type, quarantine, order numbers on several days, unmapped codes (`reader.json`). No row leaves the box | Report on the box's data-ops page |
| 3 | Steward, clinician | Compare the counts with the hospital's own: outpatients per day, admissions per month, active 病名 per department (01 §1.3 item f; plan 9 criterion 13 line 10) | Differences explained |
| 4 | Steward | Fill the site profile: codes, documents, usage, sections, from the hospital's tables (9.2 item 3) | Coverage ≥ 90 % for labs and drugs by volume, rest listed |
| 5 | Hospital 医事課 | Place one month of DPC FF1 and EF (K excluded) on the box | Reader counts match the submission's |
| 6 | Coordinator, clinician | One known cohort recount (as WS-10.3 in `docs/plan/25-master-plan.md:251` describes) on one study's criteria | Within ±2 %, every difference explained |
| 7 | REDCap owner | Token for one project, de-identified rights; link per (study, site) | Read-back shows the site's DAG only |

---

## 10. Gap table: what the product does today, what is needed, evidence

| Area | Today | Needed | Evidence |
| --- | --- | --- | --- |
| Vendor identity | "SSI" assumed | Confirmed by SSI's public list; the hospital to confirm | S9 |
| SS-MIX2 record key | Day dropped by default | The specification's key by default | M4; S22 |
| PPR-01 | PRB-3 alternate, PRB-14 "R" only | PRB-1/7/9/10/14/15/18, ZPR, snapshot semantics | R `src`:602-642; S20 |
| Dose | Per-time dose stored as daily | Per-time dose plus frequency from TQ1-3 | R `src`:694; S20 |
| YJ codes | RXE-2 only | RXE-31 too | S20 revision 1.2g |
| Extended storage | 6-level glob, prefix kinds | Content folders, CWE+LOINC kinds, `_contents.xml`, CDA | M5; S24, S25 |
| Message types | 9 of 26 read in any form | All 26 | Section 4.9 |
| Multi-volume | One root | Manifest | S23 |
| Delta | Full re-walk | Stamp-based delta per type | 01 §1.3 (e) |
| Allergies | Not read | ADT-61 into AllergyIntolerance | R `src`:94-100 |
| DPC | Not read | FF1, EF, H readers | S26 |
| Receipts | Taiwan claim shape only | UKE reader | M6; S28 |
| Cancer registry | Not read | CSV reader | Section 5 |
| Vendor DB | No SQL Server driver | Driver and a views-only contract, later | M7; S2 |
| Notes | Bracket headings for excerpts | Section types and scopes per document type | R `services/matching/excerpts.py:132-143` |
| Site variety | Codes yes; documents, usage, templates, sections in code | Site profile (section 7) | Section 7 |
| Synthetic hospital | Reader-shaped storage, one note type, no DPC or UKE | Specification-shaped storage, DPC, UKE, sectioned notes, two profiles | M1–M3, M6 |
| Tests | 34 SS-MIX2 tests against the exporter | A fixture per type from the specification's shapes | M9 |
| REDCap multicentre | One link per study, one DAG | Link per (study, site), coordinating view, REDCap as a finding source | R `services/rc_bridge/link.py:36-55` |
| Japanese privacy wording in data 13 | Taiwan PDPA only | Pointer to APPI (review 11) | R `docs/data/13-redcap-and-the-edc-backend.md:140` |

---

## 11. Notes on how this connects to plan 9 revision 2 [R `46-plan-9-rev-2`]

**Criterion 13** ("SS-MIX2 line 10 on a vendor sample or in site acceptance") needs cards 12-1 to 12-4 and 12-10
first; otherwise a vendor sample fails on day one, or worse, passes with wrong counts. **Decision 7** (ask now for a
vendor sample) becomes concrete with section 9.2. **Decision 39** (first hospital before every connector) supports DPC
and EF before HL7 v2 MLLP. **Card 9h-8** (dose criteria) waits for card 12-3. **Decision 26** (MEDIS and receipt
masters) is unchanged; card 12-12 needs the receipt masters at the site.

---

## 12. Cards, written for plan 10

**Sizes:** S a day or less, M a few days, L a week or more. **Lanes** as plan 9 names them. B2 is the adapter, H the
harness and tools, E reference data, A2 the compiler and matching, J documents, Int the integrator.

| Card | What | Size | Lane | Waits for | Proved by |
| --- | --- | --- | --- | --- | --- |
| 12-1 | SS-MIX2 key: the specification's key (with the 診療日) by default; "ALL9" and ADT types always day-keyed; `unique` stays as a declared site exception (amends D-594) | S | B2 | – | The F1 probe as a test: 3 ADT-12 files on 3 days with "ALL9" and with "1" give 3 visits; ADT-52 discharges each admission |
| 12-2 | PPR-01 to the specification: PRB-1 (DE removes), PRB-10 ICD-10 first, PRB-7 diagnosis date, PRB-16 onset, PRB-9 end, PRB-14 (HL70241 and JHSD0006 maps to clinical status), PRB-15, PRB-18 主診断 to Condition category, ZPR modifiers (疑い from the modifier code), the snapshot read (closes MR-017) | M | B2 | 12-10 fixture | The specification's sample message reads to ICD-10 K29.7, onset 2011-08-31, not resolved, 主診断; a DE row is absent; a 治癒 (F) row is resolved |
| 12-3 | Medicines to the specification: RXE-31 YJ, RXE-3 as one dose, TQ1-3 JAMI 標準用法 to doses per day (site `usage.csv`), RXE-12 refills, RXA-6 as the amount given; rename `daily_dose` where it is not daily | M | B2 | 12-14 (usage table) | A fixture with HOT9 in RXE-2 and YJ in RXE-31 resolves ATC; "1回2錠 1日3回" gives 6 a day; 9h-8 dose rules read it |
| 12-4 | Extended storage to the guideline: content folders, CWE+LOINC data-type folders, local-only names, YYYYMM/YYYY/"-" days, `_contents.xml`, CDA R2 (HS032, HS008) to sections, flags on content folders; LOINC document code to note type through `documents.csv` | M | B2 | 12-14 | The F4 probe as a test reads 2 of 2, typed discharge and pathology |
| 12-5 | ADT-61 (ADT^A60, IAM) into AllergyIntolerance (HOT9, JLAC10 allergen, local), IAM-6 action | S | B2 | 12-10 | A fixture from the specification's IAM example |
| 12-6 | ADT-01, 21, 31, 32, 41, 42, 51; the A11, A13 and A23 cancellations; IN1 kind only | M | B2 | 12-1 | Encounter history fixture: transfer, leave, cancelled discharge |
| 12-7 | OML-01 (lab orders), OMG-01/02/03 orders, OMG-11/12 実施, OMG-13 physiology results into ServiceRequest, Procedure and Observation; a microbiology shape | L | B2 | 12-10 | One fixture per type; "CT ordered within 28 days" answerable |
| 12-8 | OMD diet orders (NPO, tube feeding) | S | B2 | 12-10 | Fixture |
| 12-9 | Multi-volume manifest; delta by file stamp per type; expected-types report (which types the site writes, which never arrived) | M | B2 | 12-1 | A two-volume fixture; a night after one new file reads one file |
| 12-10 | Re-write `tools/ssmix2_export.py` to the specification's shapes (all 26 types, snapshots, flags 0/1/2, ALL9, PRB-10, RXE-31, CWE+LOINC extended storage) and keep the old shapes as a "legacy vendor" variant | L | H | – | The exporter's output passes a shape check written from S20 and S22 tables, not from the reader |
| 12-11 | DPC reader: FF1 様式1 payloads (diagnoses with レセ電 and 修飾語, operations, TNM and stage, ADL, JCS, NYHA, mRS, Barthel, height, weight, smoking index, chemotherapy), EF統合 (EF-1 … EF-31) as procedures and administrations by day, H as daily function; K never read | L | B2 | 12-14 (codes), decision 26 masters | A synthetic FF1, EF and H set for the 400 JP patients loads; a stage criterion and a "no operation within 28 days" criterion answer |
| 12-12 | UKE receipt reader (IR, RE, HO, KO, SY, SI, IY, TO, CO), 公費 kind only, no insurer numbers kept | M | B2 | Decision 26 masters | Synthetic UKE for the same patients; SY 主傷病 and 転帰 read |
| 12-13 | Hospital-based cancer-registry CSV reader (ICD-O-3, TNM, first treatment) | M | B2 | Item list read; hospital's layout (question 20) | Fixture in the 2016 format |
| 12-14 | Site profile (section 7): folder, loader, versioning, audit, coverage lines and work lists, site-setup pages to edit it | L | B2, E | – | A second synthetic profile gives the same funnel with no code change |
| 12-15 | Japanese note section detector: SOAP, 【】, ＃n, template labels, per `sections.yaml`; section roles (family, history, plan) used by matching to scope evidence | M | A2 | 12-14 | Notes with 糖尿病 under 【家族歴】 never give the patient diabetes; a 既往歴 item gives "history of" |
| 12-16 | Document-type registry and template registry (template fields to coded observations: PS, NYHA, smoking) | M | B2, A2 | 12-14 | Template lines in synthetic notes become observations |
| 12-17 | Synthetic Japanese hospital v2: section 8.2 items 1 to 6, truth files, two profiles | L | H | 12-10, 12-14 | Counts per type and per note section reported by the generator; goldens updated |
| 12-18 | REDCap multicentre: link per (study, site) with its DAG, a coordinating-centre view across DAGs, project-per-site studies merged, screening numbers unique across sites | M | B2 | – | rc_sim fixture with two DAGs and two projects |
| 12-19 | REDCap as a finding source: a registry project read through the adapter (de-identified rights, identifiers dropped) as candidate lists | M | B2 | 12-18 | rc_sim registry project gives candidates |
| 12-20 | `docs/data/13-redcap-and-the-edc-backend.md`: the IRB paragraph names APPI and points to review 11 | S | J | Review 11 | Doc check |
| 12-21 | The questionnaire (9.1) and sample list (9.2) as a site-setup form whose answers fill `profile.yaml` | S | J, B2 | 12-14 | The form fills a profile for the synthetic hospital |
| 12-22 | SQL Server read path (driver in the image, views-only, read-only login), only if decision 3 says yes | M | B2, Int | Decision 3, an NDA | A local SQL Server container fixture with a view |

**Count:** **5 L** (12-7, 12-10, 12-11, 12-14, 12-17), **12 M**, **5 S**; 22 cards.

**Order** [O]:

1. 12-10 and 12-1.
2. Then 12-2, 12-3 and 12-4, together with 12-14's skeleton.
3. Then 12-11 and 12-5.
4. The rest follows the hospital's answers.

---

## 13. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Treat "SSI = Software Service, Inc., and the first site runs 新版e-カルテ/NEWTONS2" as the working assumption, on the public evidence in the site notes (kept outside the repository), until the site confirms in the questionnaire | **Yes**, as a working assumption; the committed record keeps "not confirmed" until the site confirms. Separately: rule whether the site's name may ever be published |
| 2 | Change the SS-MIX2 default record key to the specification's (amends D-594) | **Yes** (card 12-1); `unique` only when a site declares it |
| 3 | The second door after SS-MIX2: (a) DPC FF1 and EF from the monthly submission; (b) the vendor's database under NDA; (c) both | **(a) first.** (b) only if the notes and templates are not in extended storage and SSI agrees in writing |
| 4 | Who contacts SSI: the hospital's IT (as the customer) or TrialBox directly | **The hospital**, with our questionnaire; TrialBox joins the call |
| 5 | Pay SSI for interface work if asked (SS-MIX2 activation, extended SOAP export, a DB view) | **Decide on the quote.** Under the US$500 cap, nothing; above it, the owner rules per item |
| 6 | REDCap topology for TrialBox-supported multicentre studies: one project with a DAG per site, or one project per site | **One project per study with DAGs** (card 12-18); accept project-per-site studies read-only |
| 7 | Read REDCap registries as a finding source | **Yes**, de-identified rights only (card 12-19) |
| 8 | Build a SQL Server driver into the image (a new dependency, licence check) | **Not now**; only with decision 3 (b) |
| 9 | Japanese note gold: paid writers or a partner (plan 9 revision 2, decision 19) | Unchanged; card 12-17's notes are the writers' brief |

---

## 14. What the owner or the first site must supply

1. The hospital's **confirmation of the system and versions**, and the **answers to 9.1**: one meeting with 医療情報部
   and one with SSI.
2. **SSI's site-specific SS-MIX2 output specification** (施設別仕様: which types, fields and codes). Many vendors
   write one per site [O].
3. The **sample exports of 9.2** (dummy patients only) and the extended storage's **「データ種別一覧表」**.
4. The **local-code master layouts** (病名, 薬剤, 検査, 用法, 診療科, 文書, テンプレート, レジメン); whether the site is a
   **DPC hospital**, and its 医事課 contact for FF1 and EF.
5. **REDCap**: instance owner, version, one de-identified token for a test project, the data dictionary.
6. Contacts: 医療情報部 lead, SSI account engineer, 診療情報管理士 (DPC coding), がん登録 staff, the REDCap
   administrator, and the clinician who will validate counts.
7. The owner's rulings in section 13.

## 15. Measurements

All were made on 2026-11-18 on the shared 4-core machine. Scratch is under `/var/tmp/trialbox-0/b13/`. Each command
was run from the worktree's `trialbox/` with `PYTHONPATH=libs:services:.` and the main checkout's interpreter.

| Id | Command | Result |
| --- | --- | --- |
| M1 | `python -m tools.synth_hospital --profile ci --sites jp-a:JP:400 --ref-date 2026-11-01 --out …/synth`, then `python -m tools.ssmix2_export --csv …/synth/jp-a --out …/ss --hard-cases`, then `find` counting by the type folder | 400 patients, 703 notes, 0.2 s; files per type as in 8.1 |
| M2 | `grep` of PRB, OBX and RXE segments over the storage | 32 / 13 / 30 + 12 distinct codes; RXE-2 systems 1,459 `99YJ` and 1,450 `HOT`; PRB-13 empty in all 1,142 |
| M3 | `cut` of `note_type` in `note.csv` | 703 of 703 `progress` |
| M4 | `probe_all9.py` (scratch; builds 3 ADT-12 files, reads with both keys) | ALL9: unique 1 visit, per_day 3. Order "1": unique 1, per_day 3 |
| M5 | `probe_ext.py` (scratch; one guideline-layout summary, one old-layout pathology report) | 1 document read (the old layout), typed `document`; the guideline layout 0 |
| M6 | `head` and `wc` of `claim.csv` | 63 rows, product codes `KC…`, apply type, approval dates |
| M7 | `find_spec` for pyodbc, pymssql, oracledb in the venv; `grep` of `pyproject.toml` | All absent; only `psycopg` |
| M8 | `grep -c '<tr class="row-area"'` on SSI's installation page | 1,041 rows (the page states 1,066 hospitals) |
| M9 | `grep "^def test"` over `tests/unit/test_ssmix2_*.py` and `tests/integration/test_ssmix2_path.py` | 34 tests in 5 files |
| M10 | `wc -l` of the three `jp_core` CSVs | 33, 15, 23 lines (32, 14, 22 rows) |
| M11 | `grep -rIl "様式1\|EF統合\|UKE\|レセプト"` over services and libs | Only master-column names in the licensed loaders; no reader |
| M12 | distinct `NNNNN-N` codes in the text of S25 | 120 |

## 16. Sources

All were opened on 2026-11-18 unless marked. Terms: SSI's site terms page ("このサイトのご利用について") was not read;
SSI pages are cited, not copied. Innervision PDFs are vendor-supplied catalogue pages, cited. JAMI documents are © JAMI,
cited. MHLW documents are government publications; their reuse terms were not read. PubMed is cited by PMID and DOI.

| Id | Source |
| --- | --- |
| S1 | SSI, products: https://www.softs.co.jp/business/index.html |
| S2 | SSI, 電子カルテ・オーダリング: https://www.softs.co.jp/business/coresystem.html |
| S3 | SSI, 各種部門システム: https://www.softs.co.jp/business/comedical.html |
| S4 | SSI, 健診・介護: https://www.softs.co.jp/business/healthcare.html |
| S5 | SSI, 地域医療連携 (CareMill): https://www.softs.co.jp/business/ehr.html |
| S6 | SSI, PACS (Seavo): https://www.softs.co.jp/business/pacs.html |
| S7 | SSI, システム・サービス (dashboard, data centre): https://www.softs.co.jp/business/other.html |
| S8 | SSI, 保守サポート: https://www.softs.co.jp/business/mainte.html |
| S9 | SSI, 導入実績 ("※2026年10月31日現在"): https://www.softs.co.jp/business/user/area.html |
| S10 | SSI, 電子カルテのシェア情報: https://www.softs.co.jp/e-map/share.html |
| S11 | SSI, 標準化への取り組み (IHE statement): https://www.softs.co.jp/business/standard.html |
| S12 | SSI, 匿名加工情報の取扱いについて (制定 2025-10-01): https://www.softs.co.jp/other/anonymously.html |
| S13 | SSI, news: https://www.softs.co.jp/news/index.html |
| S14 | Innervision, EMR Components 2022, 新版 e-カルテ: https://www.innervision.co.jp/ressources/pdf/buhin2022/1-17.pdf |
| S15 | Innervision 2022, NEWTONS2: https://www.innervision.co.jp/ressources/pdf/buhin2022/2-44.pdf |
| S16 | Innervision 2022, SSI 看護支援システム: https://www.innervision.co.jp/ressources/pdf/buhin2022/8-181.pdf |
| S17 | Innervision 2020, SSI chart page (SQL Server 2012/2016): https://www.innervision.co.jp/ressources/pdf/buhin2020/1-21.pdf |
| S18 | EDINET text of SSI's FY2024 annual report, via an aggregator: https://edinetdb.jp/company/E05376/text?fy=2024 (the EDINET original was not opened) |
| S20 | JAMI, SS-MIX2 標準化ストレージ仕様書 Ver.1.2i (2024-05-16): https://www.jami.jp/wp-content/uploads/2024/05/ (file "SS-MIX2-標準化ストレージ-仕様書-Ver.1.2i.pdf") |
| S21 | JAMI, same, コード表 Ver.1.2i: same folder, "…Ver.1.2i_コード表.pdf" |
| S22 | JAMI, 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2h (2022-03-31): https://www.jami.jp/wp-content/uploads/2023/11/SS-MIX2_StndrdStrgSpecGuidelinesVer.1.2h.pdf |
| S23 | JAMI, 別添 複数ボリューム管理 Ver.1.2h: https://www.jami.jp/wp-content/uploads/2023/11/SS-MIX2_StndrdStrgSpecGuidelinesVer.1.2hVolume.pdf |
| S24 | JAMI, 拡張ストレージ 構成の説明と構築ガイドライン Ver.1.2h: https://www.jami.jp/wp-content/uploads/2023/11/SS-MIX2_kakuchoStrgGuidelinesVer.1.2h.pdf |
| S25 | JAMI, 拡張ストレージ 標準文書コード表 Ver.1.2h (2023-08-30): https://www.jami.jp/wp-content/uploads/2023/11/SS-MIX2_kakuchoStrgGuidelinesVer.1.2h_CodeTable.pdf |
| S26 | MHLW, 2025年度 DPCの評価・検証等に係る調査（退院患者調査）実施説明資料 (2025-05-30): https://www.mhlw.go.jp/seisakunitsuite/bunya/kenkou_iryou/iryouhoken/dl/dpc_setumeishiryou_r08.pdf; overview https://www.mhlw.go.jp/content/12404000/000687647.pdf |
| S27 | (merged into S26) |
| S28 | MHLW 診療報酬情報提供サービス, 記録条件仕様（医科用）, 令和8年10月1日更新: https://shinryohoshu.mhlw.go.jp/shinryohoshu/file/spec/R08bt1_1_kiroku.pdf |
| S29 | PMID 41736045, doi:10.1186/s12911-026-03397-1 (MID-NET code governance, 2026) |
| S30 | PMID 31464008, doi:10.1002/pds.4879 (MID-NET establishment, 2019) |
| S31 | PMID 31438232, doi:10.3233/SHTI190535 (MID-NET governance tool, 2019) |
| S32 | PMID 35672959, doi:10.3233/SHTI220020 (coverage of SS-MIX2 for trial variables, 2022) |
| S33 | PMID 34495957, doi:10.1371/journal.pone.0255863 (MIHARI, PPV of outcome definitions, 2021) |
| S34 | PMID 28142051, doi:10.1016/j.je.2016.09.009 (validity of DPC diagnoses and SS-MIX labs, 2017) |
| S35 | PMID 41169881, doi:10.3389/fcvm.2025.1642323 (MID-NET heart-failure algorithms, 2025) |
| S36 | PMID 31245595, doi:10.1002/lrh2.10072 (EMR to EDC through SS-MIX2 and IHE RFD, 2018). Relevant to REDCap prefill; abstract only |
| S37 | PMID 30603343, doi:10.1007/s13340-017-0326-y (J-DREAMS: templates, SS-MIX2, MCDRS) |
| S38 | PMID 37740823, doi:10.1007/s10916-023-01993-6; PMID 34174764, doi:10.1016/j.cmpb.2021.106232 (SS-MIX2 to FHIR) |

The PubMed abstracts of S29 to S38 were read through the PubMed service. Full texts were not.

---

## 17. What this document did not verify

- **Whether the first site runs SSI.** Not stated here (the site notes outside the repository hold the public
  evidence); the site's own confirmation is needed.
- **Whether the first site has the SS-MIX2 option**, which types it writes, its extended-storage contents, its update cycle
  and its order-number habit. None is public.
- **SSI's current database and OS versions.** The SQL Server data is from 2020 and 2022 catalogue pages.
- **SSI's prices** for interfaces or exports.
- **What NEWTONS2 治験管理 and SSI SCOPE hold.**
- **www.ss-mix.org.** The TLS certificate failed, so the consortium's sample data and pages were not opened.
- **The ISO/TS 24289 status.** Search summary only.
- **JAHIS data exchange conventions** (member documents). Not opened.
- **The JCS data-output guideline, the HELICS OMG Q&A and the AMED report on SS-MIX2 quality.** Search summaries only.
- **REDCap in Japan** (Japan REDCap Consortium count, university instances). The pages reset the connection; search
  summaries only.
- **Cancer-registry item lists** (29 national, 99 hospital-based) and the cancer-registry law's limits on data use.
  Search summaries only; review 11 is the place.
- **電子カルテ情報共有サービス (3文書6情報) and JP Core 1.2.0 examples and licence.** Search summaries only.
- **Reuse terms** of SSI's site, JAMI's documents and MHLW's documents. Not read; nothing is copied beyond short
  quotations.
- **Realistic message volumes per type** at a hospital of several hundred beds. No public figure found; section 4.8 is opinion.
- **A real vendor storage.** Never seen (STD-014). Every conformance finding is against the published specification
  and synthetic files, not against SSI's output. SSI may write ICD-10 in PRB-3, or skip content folders. Section 9
  asks.
- **The full SS-MIX2 specification.** I read the segments the findings rest on (PPR, PRB, ZPR, RXE-2/3/31, revision
  history, the ADT list, OML-11 OBX-3, IAM); not all 169 pages.
