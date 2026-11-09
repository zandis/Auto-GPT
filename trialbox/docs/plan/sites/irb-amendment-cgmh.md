# IRB amendment draft, CGMH: TrialBox research repository, patient profiles and whole-hospital pre-screening (TB-SITE-04)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-04 |
| Version | 0.1 draft (2026-11-09) for the PI and the 臨床試驗中心 to adapt to the committee's template |
| File by | **2026-11-20** (owner decision, D-145) for the December meeting; withdraw the parts the committee confirms are already covered |
| Covers | the model-written cited patient profile; the vector store and "patients like this one"; cross-department identified candidate views by the PI and delegated sub-investigators before the treating physician is asked; the clinician (treating physician) role; the data steward's note access; the opt-out notice; the data-handling rule |
| Languages | 繁體中文 (the submission text) with the English source beside it |

## A. 繁體中文（送審文字）

### A.1 修正案標題

「TrialBox 研究資料庫、病人概況與全院預先篩選」之計畫書修正案（版本 2，2026 年 11 月）。

### A.2 修正目的

本院已核准以 TrialBox 軟體於院內預先篩選可能符合臨床研究收案條件之病人。本修正案補充核准範圍，涵蓋 2026 年 11 月 9 日定案之下列功能：（一）以假名化資料建立之全院研究資料庫（OMOP CDM v5.4）；（二）由本地語言模型撰寫、逐句引用病歷之病人概況；（三）病歷文字向量索引與「相似病人」檢索；（四）跨科別之可識別候選名單檢視；（五）主治醫師角色；（六）資料管理人之病歷全文讀取；（七）退出（opt-out）公告與資料處理規則。

### A.3 修正內容

| # | 項目 | 修正後內容 |
| --- | --- | --- |
| 1 | **研究資料庫** | 本院 HIS 之病人紀錄（結構化資料與病歷文字，含既往全部年度）以每夜匯出方式複製至本院自有伺服器上之 TrialBox 容器，於入口以院方金鑰將病歷號轉為假名；姓名、身分證號、電話等直接識別碼不進入資料庫。資料庫為 OMOP CDM v5.4 格式，僅供本院核准之研究使用，不離開本院。 |
| 2 | **病人概況** | 對參與研究之病人，TrialBox 以本院 GPU 上執行之語言模型撰寫一頁概況（紀錄摘要、時間線、表現型、研究資格），每一句皆引用病歷原文並經第二模型核對；引用不足 95 % 時不產出。概況僅供研究人員（主持人、協同主持人、研究協調員、資料管理人）閱讀，標示「研究用途，非診斷依據」；無人可編輯；醫師可附加簽署之註記。個人化檢驗基準值與「缺口規則」兩層僅供主持人與資料管理人在研究用途下閱讀，主治醫師預設不可見。 |
| 3 | **向量索引與相似病人** | 病歷文字分段後以嵌入模型轉為向量，存於本院伺服器之資料庫（pgvector）。「相似病人」檢索先以結構化項目比對，再以向量重排，每一筆結果附說明；檢索範圍限於使用者所屬研究或照護關係之病人；向量不離開本院。 |
| 4 | **全院可識別預先篩選與跨科候選檢視** | 研究之收案條件對本院全部病人之假名化資料執行。主持人及經授權名冊授權之協同主持人，對篩選所得之候選病人（含非本科病人）可檢視決定所需之資訊，包括病歷號與引用之病歷內容，**於徵得主治醫師同意前即可檢視**；每次檢視均記錄研究、目的與使用者並有速率限制。病人僅於主治醫師同意後由主持人接觸。本院對此跨科可識別檢視之法律依據為本院之醫療關係與本委員會之核准。 |
| 5 | **轉介流程** | 主持人或協同主持人透過 TrialBox 向主治醫師提出轉介請求；主治醫師不明時，由職員名冊選擇、手動輸入、「於 TrialBox 外安排」或科別聯絡人處理；主治醫師回覆（同意介紹／拒絕並附理由／討論）由研究協調員登錄；每一步驟留下紀錄並計入篩選紀錄。 |
| 6 | **主治醫師角色** | 非研究成員之主治醫師得登入檢視其自身病人（近 24 個月內看診或開單，或未來 90 天內有預約；個資保護單位得加入其病房住院病人）之紀錄、時間線、表現型與研究資格層，並附加簽署註記；每次檢視均留下稽核紀錄。 |
| 7 | **資料管理人** | 本院指定之資料管理人（本試行期間為計畫主持人，另設一名獨立之院內第二審核人共同簽署驗證與發布紀錄）得隨時讀取全部病歷文字以進行代碼對應、衝突處理與資料品質工作；每次讀取均留下稽核紀錄並保存十年。 |
| 8 | **退出（opt-out）** | 本院於（公告位置）公告研究使用之退出方式。病人退出後數分鐘內自篩選、概況、向量與未來匯出中移除並留下紀錄；退出之病人不出現於任何名單。 |
| 9 | **資料處理規則** | 真實病人資料僅於本院硬體（本院 B200 平台之 TrialBox 容器或本院核准之私有雲）處理；供應商 Aimedics 不持有病人資料；開發人員與自動化代理不接觸真實資料，僅使用合成資料與本院之欄位結構及代碼清單；任何離開研究團隊之統計以 k = 5 抑制；詳見資料處理規則 TB-SITE-03。 |
| 10 | **稽核與保存** | 每次病人資料檢視、病歷號揭露、匯出與簽署均記錄人員、角色、理由與時間，保存十年；稽核鏈每日簽署並副本存放於本院共享儲存。 |
| 11 | **非醫療器材聲明** | TrialBox 不診斷、不治療、不判定研究資格、不建議治療、不警示醫師、不聯繫病人；所有輸出由合格人員審閱；本軟體非醫療器材，不作為診斷依據。本院將於正式使用前取得書面法規見解。 |

### A.4 風險與保護措施

對受試者之風險為個人資料之隱私風險，無臨床介入。保護措施：入口假名化、院內處理、角色權限與第二因子登入、每次檢視稽核、速率限制、退出機制、k = 5 統計抑制、資料不離院、供應商不持有資料、獨立第二審核人。

### A.5 附件

資料流程圖；退出公告文字；一頁系統說明（TB-SITE-02 §C）；資料處理規則（TB-SITE-03）；篩選紀錄欄位定義；受試者同意書不變（本修正案不涉及介入）。

## B. English source

### B.1 Title

Amendment to the approved protocol: the TrialBox research repository, patient profiles and whole-hospital pre-screening (version 2, November 2026).

### B.2 Purpose

The committee approved the use of TrialBox to pre-screen the hospital's patients for research eligibility. This amendment extends the approval to the functions decided on 2026-11-09: (1) a whole-hospital pseudonymised research repository (OMOP CDM v5.4); (2) a model-written, sentence-cited patient profile; (3) a vector index over note text and "patients like this one"; (4) cross-department identified candidate views; (5) a treating-physician (clinician) role; (6) the data steward's full note access; (7) the opt-out notice and the data-handling rule.

### B.3 Content

| # | Item | Amended text |
| --- | --- | --- |
| 1 | Research repository | The hospital's HIS records (structured data and note text, all years of history) are copied nightly into the TrialBox containers on the hospital's own server; chart numbers become pseudonyms at the door with a hospital-held key; names, national IDs and phones never enter. The repository is OMOP CDM v5.4, used only for approved research, and never leaves the hospital. |
| 2 | Patient profiles | For study patients, TrialBox writes a one-page profile (record summary, timeline, phenotype, eligibility) with a language model running on the hospital's GPU; every sentence cites the record and is checked by a second model; the model abstains under 95 % cited. Profiles are read by research staff only (PI, sub-investigators, CRCs, the steward), labelled "research use, not for diagnosis"; nobody edits them; physicians add signed annotations. The personal lab setpoint and gap-rule layers are shown to the PI and the steward under the research-use label only; treating physicians do not see them by default. |
| 3 | Vector index and similar patients | Note text is chunked and embedded into vectors stored in the hospital's database (pgvector). "Patients like this one" matches structured items first and re-ranks by vectors; every match is explained; the scope is the user's own studies or care relationship; vectors never leave the hospital. |
| 4 | Whole-hospital identified pre-screening and the cross-department candidate view | A study's criteria run over the pseudonymised records of every patient in the hospital. The PI and delegated sub-investigators may view, for a candidate from any department, what is needed to decide, including the chart number and the cited record, **before the treating physician is asked**; every view is logged with study, purpose and user and is rate-limited. The patient is approached only after the treating physician agrees. The legal basis for this cross-department identified view is the hospital's care relationship together with this committee's approval. |
| 5 | Referral | The PI or a sub-investigator sends a referral request through TrialBox; when the treating physician is unknown, the user picks from the staff directory, types a name, chooses "arranged outside TrialBox" or the department contact; the physician's answer (agree, decline with reason, discuss) is recorded by the CRC; every step is logged and counted in the screening log. |
| 6 | Clinician role | A treating physician who is not a study member may sign in to read the record, timeline, phenotype and eligibility layers of their own patients (seen or ordered for in 24 months, or booked within 90 days; the privacy office may add ward inpatients) and add signed annotations; every view is audited. |
| 7 | Data steward | The hospital's named steward (for this pilot the PI, with an independent hospital second reviewer who co-signs validation and release records) may read all note text at any time for code mapping, conflict resolution and data quality; every read is audited and kept 10 years. |
| 8 | Opt-out | The hospital posts the research opt-out notice at (location). An opt-out removes the patient from screening, profiles, vectors and future exports within minutes and is logged; the patient appears on no list. |
| 9 | Data-handling rule | Real patient data is processed only on hospital hardware (the TrialBox containers on the hospital's B200 platform or an approved private cloud); the vendor never holds patient data; developers and automated agents never touch real data and work from synthetic data and the hospital's schema and code lists; any statistic leaving the study team is suppressed at k = 5 (TB-SITE-03). |
| 10 | Audit and retention | Every view, reveal, export and signature is recorded with person, role, reason and time and kept 10 years; the audit chain is signed daily with a copy on the hospital's share. |
| 11 | Non-device statement | TrialBox does not diagnose, treat, decide eligibility, recommend treatment, alert clinicians or contact patients; every output is reviewed by a qualified person; it is not a medical device. A written regulatory view will be sought before formal use. |

### B.4 Risk and protection

The risk to participants is a privacy risk only; there is no clinical intervention. Protections: pseudonymisation at the door, on-premises processing, role permissions and a second factor, audit of every view, rate limits, the opt-out path, k = 5 suppression, no data leaves the hospital, the vendor holds no data, the independent second reviewer.

### B.5 Attachments

Data-flow figure; opt-out notice text; the one-page system description (TB-SITE-02 §C); the data-handling rule (TB-SITE-03); screening-log column definitions; the informed consent form is unchanged (no intervention).
