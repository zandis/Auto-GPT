# TrialBox site survey (TB-SITE-01) · サイト調査票 · 場域調查表

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-01 |
| Version | 0.2 (2026-11-09; v0.1 rewritten after the independent plan review PR-16, PR-21, PR-25, PR-29, PR-30, PR-32) |
| Owner | Changfu Kuo (Aimedics) |
| Filled by | the site's IT contact, the data-feed owner, the privacy office and the PI, with Changfu (CGMH) or Makoto (Japan) |
| Status | Draft. One copy per site. The signed copy is the entry condition for design freeze (G2) and the basis of the site mapping, the IQ protocol, the hospital IT security pack and the IRB amendment. Questions marked **by 2026-11-20** decide the plan's clock and are answered first. |
| Languages | One table, three languages, one answer column, so the numbering and the content cannot drift. A native reader (Makoto for 日本語, a CGMH CRC for 繁體中文) signs the language columns. |

## 1. How to use this form · 使い方 · 使用方式

**English.** Answer every question. "Unknown" is an answer; write who can find out and by when. Attach documents where asked. **No patient data goes on this form, in any attachment or to anyone outside the hospital** (data-handling rule TB-SITE-03): structure and code lists only. The real 10-patient sample is read on the hospital's hardware by the steward after the DPA is signed; only the adapter's report leaves. The filled form is signed by the hospital IT lead, the PI and the steward.

**日本語.** すべての質問に答えてください。「不明」も回答です。その場合は誰がいつまでに確認するかを書いてください。求められた箇所には資料を添付してください。**この用紙、添付資料、院外の誰にも患者情報を渡さないでください**（データ取扱規則 TB-SITE-03）。テーブル構造とコード一覧のみです。実患者 10 名分のサンプルは、データ処理契約の締結後に院内の機器上でデータスチュワードが読み込み、アダプタの報告書だけが院外に出ます。記入済みの用紙は医療情報部責任者、治験責任医師、データスチュワードが署名します。

**繁體中文.** 請回答每一題。「不確定」也是答案，請寫明由誰在何時確認。要求附件處請附上文件。**本表、附件與院外任何人皆不得取得病人資料**（資料處理規則 TB-SITE-03）：僅提供欄位結構與代碼清單。真實 10 位病人樣本於資料處理契約簽署後，由資料管理人在院方硬體上讀取，只有轉接層的報告離開醫院。填妥後由資訊室主管、試驗主持人與資料管理人簽署。

## 2. Questions · 質問 · 問題

Deadline marks: **①** by 2026-11-20 (the clock); **②** by the survey sign-off (W4). Attach: **A**.

### 2.1 Contacts · 連絡先 · 聯絡人

| # | English | 日本語 | 繁體中文 | Answer · 回答 · 回答 |
| --- | --- | --- | --- | --- |
| 1 ① | Principal investigator(s) for the pilot studies, department, mail | 対象試験の治験責任医師、診療科、メール | 本次試驗之主持人、科別、電子郵件 | |
| 2 ① | Data steward: the hospital's named person who holds the TrialBox repository (CGMH: the PI for the pilot, plus the independent second reviewer who co-signs validation and release records) | データスチュワード：TrialBox のデータベースを預かる当院の担当者 | 資料管理人：院方指定、掌管 TrialBox 資料庫的人員（長庚：本試行期間為主持人，另加一名共同簽署驗證與發布紀錄的獨立第二審核人） | |
| 3 | Trial office / research office contact (delegation log, IRB filings, invoicing) | 治験事務局・研究支援部門の窓口（分担医師リスト、IRB 申請、請求） | 臨床試驗中心／研究部窗口（授權名冊、IRB 送件、請款） | |
| 4 ① | Hospital IT: device registration, network, directory (AD/LDAP), certificates | 医療情報部：端末登録、ネットワーク、ディレクトリ（AD/LDAP）、証明書 | 資訊室：設備登錄、網路、目錄服務（AD/LDAP）、憑證 | |
| 5 ① | Hospital IT: security review, vulnerability scan (if required), incident reporting | 医療情報部：セキュリティ審査、脆弱性診断（必要な場合）、インシデント報告 | 資訊室：資安審查、弱點掃描（如需要）、事件通報 | |
| 6 ① | Data-feed owner: the team that produces the EMR export, SS-MIX2 storage, HIS views or FHIR, and who can build a new export | データ提供元：電子カルテ出力、SS-MIX2 ストレージ、HIS ビュー、FHIR を出す部門と、新しい出力を作れる担当 | 資料來源負責單位：產出 HIS 匯出、SQL 檢視表或 FHIR 的團隊，以及可建置新匯出的人員 | |
| 7 ① | Privacy office / 個人情報保護管理者 / 個資保護人員 | 個人情報保護管理者 | 個資保護人員 | |
| 8 | REDCap administrator (if REDCap is used) and the owner of the REDCap API token for the pilot projects | REDCap 管理者（使用する場合）と対象プロジェクトの API トークンの保有者 | REDCap 管理者（如使用）及本次試驗專案 API token 的持有人 | |
| 9 | Pharmacy contact (only for the dispensing-date input) | 薬剤部窓口（治験薬の調剤日の入力のみ） | 藥局窗口（僅供試驗用藥給藥日期的輸入） | |
| 10 ① | Who signs the data-processing agreement and the platform licence for the hospital; which contract instrument the hospital already uses (research collaboration agreement, 業務委託 template, other) and the usual signature path and time | 病院側でデータ処理契約とプラットフォーム利用契約に署名する人。病院が既に持つ契約様式（共同研究契約、業務委託契約の標準様式、その他）と通常の決裁経路・所要期間 | 代表醫院簽署資料處理契約與平台授權契約的人；院方既有的契約形式（共同研究契約、委託契約範本、其他）及一般簽署流程與時程 | |
| 11 | Shared GPU platform team (CGMH) or the private-cloud team: contact and the person who grants namespaces and GPU quotas | 共用 GPU 基盤チームまたはプライベートクラウド担当：連絡先とネームスペース・GPU クォータの付与者 | 共用 GPU 平台團隊（長庚）或私有雲團隊：聯絡人及核發 namespace 與 GPU 配額的人員 | |

### 2.2 IRB and legal basis · 倫理審査と法的根拠 · IRB 與法律依據

| # | English | 日本語 | 繁體中文 | Answer |
| --- | --- | --- | --- | --- |
| 12 ① | IRB approval number and date for the pilot; approval end date | 倫理審査の承認番号、承認日、有効期限 | 本次試行的 IRB 核准編號、日期與到期日 | |
| 13 ① A | Does the approved protocol name TrialBox's screen of the hospital's records as the recruitment method? (yes / no / unsure: attach the text) | 承認済みプロトコルに「TrialBox による院内記録のスクリーニング」が募集方法として明記されているか（はい／いいえ／不明：該当文を添付） | 核准的計畫書是否載明「以 TrialBox 篩選院內病歷」為收案方法（是／否／不確定：附上原文） | |
| 14 ① | Does the approval cover **whole-hospital screening** (patients of any department) and **identified candidate views by the PI before the treating physician agrees**? Quote the sentence | 承認は**病院全体のスクリーニング**（他科の患者を含む）と、**主治医の了承前に責任医師が識別可能な候補を閲覧すること**を対象としているか。該当文を引用 | 核准是否涵蓋**全院篩選**（任何科別的病人）及**主治醫師同意前由主持人檢視可識別候選病人**？請引述原文 | |
| 15 ① | Does the approval cover **patient profiles** (a model-written, cited summary per study patient), **vectors and "patients like this one"**, the **clinician role** and the **steward's full note access**? | 承認は**患者プロファイル**（モデルが作成し引用付きの要約）、**ベクトルと類似患者検索**、**主治医の役割**、**スチュワードのカルテ全文閲覧**を対象としているか | 核准是否涵蓋**病人概況**（模型撰寫、逐句引用）、**向量與相似病人**、**主治醫師角色**與**資料管理人之病歷全文讀取** | |
| 16 ① | Does the approval cover the opt-out notice for research use of existing records, and where is the notice posted? | 既存情報の研究利用に関するオプトアウト通知が承認に含まれ、どこに掲示されているか | 核准是否包含既有病歷研究使用的退出公告，公告於何處 | |
| 17 ① | The committee's next meeting dates and submission deadlines (December, January, February); whether December or late January meetings are held | 委員会の次回以降の開催日と提出締切（12 月、1 月、2 月）。12 月や 1 月下旬の開催があるか | 委員會接下來的會議日期與送件截止（12 月、1 月、2 月）；12 月或 1 月下旬是否開會 | |
| 18 | Approved ICF versions for each pilot study (version, date, language) | 各試験の承認済み説明同意文書の版（版、日付、言語） | 各試驗核准的受試者同意書版本（版本、日期、語言） | |
| 19 | The hospital's rule for identified pre-screening (who may open which chart, per project application if any) | 同定可能な状態での事前スクリーニングに関する院内規則（誰がどのカルテを開けるか、課題ごとの申請の有無） | 院內關於可識別狀態下預先篩選的規定（誰可開啟哪些病歷，是否需按專案申請） | |
| 20 ① | The legal basis the privacy office relies on for (a) pre-screening with re-identification and (b) a PI viewing another department's identified records before referral (care relationship + IRB; other); whether the hospital's published 利用目的 (Japan) or its PDPA Art. 27 security plan (Taiwan) needs an update for research-support processing by a vendor's software | 個人情報保護担当が依拠する法的根拠：(a) 再識別を伴う事前スクリーニング、(b) 紹介前に責任医師が他科の識別可能な記録を閲覧すること（診療関係＋倫理審査、その他）。供給者ソフトウェアによる研究支援処理のために当院の公表する利用目的の更新が必要か | 個資保護人員對 (a) 含再識別之預先篩選、(b) 轉介前主持人檢視他科可識別病歷所依據的法律基礎（醫療關係加 IRB；其他）；院方 PDPA 第 27 條安全維護計畫是否需納入 TrialBox | |
| 21 | SAE reporting rules at this site: to the sponsor, to the IRB / head of institution, to the regulator, in days (fatal or life-threatening / other serious); the trial office's SAE log stays the system of record and TrialBox is a reminder | この施設の SAE 報告規則：依頼者、IRB・病院長、規制当局への日数（死亡・生命を脅かす／その他の重篤）。治験事務局の SAE 台帳が正式記録であり TrialBox はリマインダー | 本院 SAE 通報規則：對試驗委託者、IRB／機構負責人、主管機關的天數（死亡或危及生命／其他嚴重）；試驗辦公室的 SAE 紀錄為正式紀錄，TrialBox 僅為提醒 | |
| 22 | Record retention rule per study (years after the end of the study or after approval of the drug) | 試験ごとの記録保存期間（試験終了後または承認後の年数） | 各試驗的紀錄保存年限（試驗結束後或藥品核准後的年數） | |
| 23 | Sponsors of the pilot studies: who at each sponsor acknowledges in writing that TrialBox is in the source-data chain (prefill is switched on per study only after that) | 対象試験の依頼者：TrialBox が原資料の連鎖に入ることを書面で確認する担当（確認後にのみ試験ごとにプレフィルを有効化） | 本次試驗的委託者：由誰以書面確認 TrialBox 進入來源資料鏈（確認後才逐研究開啟預填） | |

### 2.3 Data feed and volumes · データフィードと規模 · 資料來源與規模

| # | English | 日本語 | 繁體中文 | Answer |
| --- | --- | --- | --- | --- |
| 24 ① | Which input will the site start with? (database export CSV / HIS SQL views / SS-MIX2 storage / FHIR bulk export / spreadsheets / charts pasted or uploaded / a mix) | 最初に使う入力（データベースの CSV 出力／HIS の SQL ビュー／SS-MIX2 ストレージ／FHIR 一括出力／表計算ファイル／カルテの貼り付けやアップロード／組み合わせ） | 起始輸入方式（資料庫 CSV 匯出／HIS SQL 檢視表／SS-MIX2／FHIR 批次匯出／試算表／逐份貼上或上傳病歷／混合） | |
| 25 ① | **Volumes**: distinct patients in the record system; patients with an encounter in the last 24 months; encounters per year; diagnosis rows per year; lab result rows per year; drug orders per year; notes per year and their text volume (GB); the current EMR database size | **規模**：登録患者数、過去 24 か月に受診のある患者数、年間受診件数、年間病名件数、年間検査結果件数、年間処方件数、年間記録件数と文章量（GB）、現在のカルテ DB の容量 | **規模**：病歷系統中的病人數；近 24 個月有就診的病人數；每年就診次數；每年診斷列數；每年檢驗結果列數；每年用藥醫令數；每年病歷文字則數與容量（GB）；目前電子病歷資料庫大小 | |
| 26 ① | **Does an export that TrialBox can read exist today?** If not: who builds it, the earliest delivery date, and the tiers the hospital can deliver in order: tier 1 structured data for the participating departments; tier 2 all departments; tier 3 free-text notes and reports | **TrialBox が読める出力は今あるか。** ない場合：誰が作るか、最短の納期、段階（第 1 段階：参加診療科の構造化データ、第 2 段階：全診療科、第 3 段階：カルテ文章と報告書） | **目前是否已有 TrialBox 可讀的匯出？** 若無：由誰建置、最早交付日期，以及院方可依序交付的階段：第 1 階段參與科別的結構化資料；第 2 階段全院；第 3 階段病歷文字與報告 | |
| 27 | EMR vendor and version; HIS self-built or vendor | 電子カルテベンダーと版、HIS は自社開発かベンダー製か | 電子病歷廠商與版本；HIS 為自建或廠商 | |
| 28 A | For SS-MIX2: storage root path, vendor, standardized storage version, extended storage present (yes / no) and **whether it carries progress notes, summaries and reports**, 標準病名 and JLAC10 codes present (always / sometimes / never), deletion flags used | SS-MIX2：ストレージのルートパス、ベンダー、標準化ストレージの版、拡張ストレージの有無と**経過記録・サマリ・報告書が含まれるか**、標準病名と JLAC10 の有無（常に／時々／なし）、削除フラグの使用 | SS-MIX2（如適用）：儲存根路徑、廠商、版本、延伸儲存有無及**是否含病程、摘要與報告**、標準病名與 JLAC10 的有無、刪除旗標 | |
| 29 A | For CSV or SQL views: table list, one header row per table (no data), date format (ISO / era / ROC 7-digit), encoding (UTF-8 / Shift_JIS / CP932 / Big5), delimiter | CSV・SQL ビュー：テーブル一覧、各テーブルのヘッダ行のみ（データなし）、日付形式（ISO／和暦）、文字コード（UTF-8／Shift_JIS／CP932）、区切り文字 | CSV 或 SQL 檢視表：資料表清單、每表一列欄位名（不含資料）、日期格式（ISO／民國 7 碼）、編碼（UTF-8／Big5）、分隔符 | |
| 30 A | For FHIR: base URL or export path, FHIR version, profiles (JP Core / TW Core), bulk export supported (yes / no), authentication | FHIR：ベース URL または出力パス、FHIR の版、プロファイル（JP Core）、一括出力の可否、認証 | FHIR：基底 URL 或匯出路徑、FHIR 版本、profile（TW Core）、是否支援批次匯出、認證方式 | |
| 31 | How often can the feed be produced? (nightly / weekly / one-time) Who runs it? How does it reach TrialBox? (LAN share / SFTP / USB) | フィードの頻度（毎夜／毎週／一回限り）、実行者、TrialBox への受け渡し方法（LAN 共有／SFTP／USB） | 匯出頻率（每夜／每週／一次性）、執行者、送達方式（LAN 共享／SFTP／USB） | |
| 32 | Which years of history exist, and from which year are records electronic (EMR since)? Are earlier records paper or scanned? | 保有する履歴の年数と、電子化が始まった年（EMR since）。それ以前は紙かスキャンか | 保有的歷史年份，以及電子病歷起始年；更早的紀錄為紙本或掃描 | |
| 33 | Does the feed carry the attending or ordering physician per encounter? How reliable is it? Can the site export a staff directory (id, name, department)? | 受診ごとの主治医・オーダー医の有無と信頼性。職員名簿（ID、氏名、診療科）を出力できるか | 每次就診是否含主治或開單醫師，可靠程度；是否可匯出人員名冊（代號、姓名、科別） | |
| 34 | Does the feed carry an appointment or booking source (future visits)? | 予約情報（将来の受診）の有無 | 是否含預約（未來就診）來源 | |
| 35 ① | **Note types in the feed** (progress, discharge, consult, nursing, reports), their text encoding, mixed-language notes (yes / no). **If the feed carries no notes, say so: the profile, note criteria and embeddings then wait for tier 3 of question 26** | **フィードに含まれる記録の種類**（経過記録、退院サマリ、コンサルト、看護記録、報告書）と文字コード、言語の混在。**記録が含まれない場合はその旨：プロファイル、記録に基づく条件、埋め込みは質問 26 の第 3 段階を待つ** | **匯出中的病歷文字類型**（病程、出院摘要、會診、護理、報告）、編碼、是否中英夾雜。**若不含病歷文字請註明：病人概況、文字條件與向量將等待第 26 題的第 3 階段** | |
| 36 A | Laboratory: local test codes (JLAC10, NHI order codes, hospital codes); units per analyte as reported (CRP mg/dL or mg/L; creatinine mg/dL or µmol/L; HbA1c NGSP or JDS before 2012); a lab table export (code, name, unit) | 検査：ローカル検査コード（JLAC10、院内コード）、分析項目ごとの報告単位（CRP mg/dL か mg/L、クレアチニン mg/dL か µmol/L、2012 年以前の HbA1c は JDS か）、検査マスタの出力（コード、名称、単位） | 檢驗：本地檢驗代碼（健保醫令碼、院內碼）；各項目報告單位（CRP mg/dL 或 mg/L；肌酸酐 mg/dL 或 µmol/L）；檢驗項目表匯出（代碼、名稱、單位） | |
| 37 | Diagnoses: ICD-10-CM edition(s) by year (Taiwan 2014 / 2023), 標準病名 with or without ICD-10, suspected-diagnosis flag present | 病名：ICD-10 の版、標準病名の ICD-10 付与の有無、疑い病名フラグの有無 | 診斷：各年度使用的 ICD-10-CM 版本（2014／2023）、疑似診斷旗標 | |
| 38 | Medicines: code system (YJ / HOT / NHI drug code / local), ATC present (yes / no) | 薬剤：コード体系（YJ／HOT／院内）、ATC の有無 | 藥品：代碼系統（健保藥品碼／院內碼）、是否含 ATC | |
| 39 | Opt-out: where the hospital keeps research opt-outs (EMR flag exported / vendor field not exported / paper at the records office / none) | オプトアウト：研究利用拒否の記録場所（カルテのフラグが出力される／ベンダー項目で出力されない／医事課の紙／なし） | 退出（opt-out）：研究使用退出登錄於何處（病歷旗標且有匯出／廠商欄位未匯出／病歷室紙本／無） | |
| 40 | Deaths: how the feed shows a death; whether deaths outside the hospital are recorded | 死亡：フィードでの死亡の表現、院外死亡の記録の有無 | 死亡：匯出中如何呈現死亡；院外死亡是否記錄 | |
| 41 ① | The 10-patient mapping sample and a **different** 10 to 20 patient OQ sample: read on the hospital's hardware by the steward after the DPA (date), under (agreement); only the adapter's report leaves (TB-SITE-03) | 10 名分の対応付け用サンプルと、**別の** 10〜20 名分の OQ 用サンプル：データ処理契約の締結後（日付）、（契約）のもとで院内機器上でスチュワードが読み込み、アダプタの報告書のみ院外へ（TB-SITE-03） | 10 位病人的對應樣本與**另一組** 10 至 20 位的 OQ 樣本：於資料處理契約簽署後（日期）、依據（契約），由資料管理人在院方硬體上讀取；只有轉接層報告離開（TB-SITE-03） | |
| 42 | Known data quality issues (missing codes, department master gaps, date gaps, wording drift) | 既知のデータ品質の問題（コード欠落、部門マスタの不備、日付の欠落、表記の揺れ） | 已知的資料品質問題（代碼缺漏、科別主檔不全、日期缺漏、用語漂移） | |

The steward writes the answers to questions 24 to 38 into the site's `site-schema.yaml` (T-011; schema
`schemas/site_schema.schema.json`, procedure in RUNBOOK §18), from which a synthetic site is built to develop the
mapping. Field names, beside the questions:

| # | `site-schema.yaml` field |
| --- | --- |
| 24 | `feed.layout` (`csv`, `sql`, `ssmix2`) |
| 26 | `identifiers.chart_number` (`letters`, `digits`, `check`): the form only, never a number |
| 28 | `feed.layout: ssmix2`, `feed.encoding` (MSH-18); the extended tables under `tables` |
| 29 | `tables.<table>.source` and `tables.<table>.columns` (header to canonical column), `feed.date_format` (`iso`, `roc7`, `yyyymmdd`, `slash`), `feed.encoding`, `feed.delimiter`, `feed.extension` |
| 33 | `provider.in_encounter`, `provider.directory` |
| 34 | `appointments` |
| 35 | `notes.types` |
| 36 | `code_lists.lab` (code, name, unit, and the range synthetic results are drawn from) |
| 37 | `code_lists.diagnosis` (code, name, and `icd10` beside a 標準病名 code) |
| 38 | `code_lists.drug` (code, name, `atc`) |
| codes on the sheets | `code_lists.sex`, `code_lists.encounter_type`, `code_lists.department` |

### 2.4 Trial systems · 治験システム · 試驗系統

| # | English | 日本語 | 繁體中文 | Answer |
| --- | --- | --- | --- | --- |
| 43 | REDCap: version, URL, test project available (yes / no), API enabled (yes / no), who issues API tokens (never a shared token), longitudinal projects and repeating instruments used | REDCap：版、URL、テスト用プロジェクトの有無、API の有効化、API トークンの発行者（共有トークンは不可）、縦断プロジェクトと反復インストゥルメントの使用 | REDCap：版本、URL、測試專案、API 是否開啟、API token 核發者（不得共用）、縱貫型專案與重複表單使用情形 | |
| 44 | Sponsor EDCs in use for the pilot studies (name, ODM import supported, weekly export available) | 対象試験で使用する依頼者 EDC（名称、ODM 取込の可否、週次出力の可否） | 本次試驗使用的委託者 EDC（名稱、是否支援 ODM 匯入、是否可每週匯出） | |
| 45 A | Where the screening log and enrolment log are kept today (Excel / REDCap / paper) and in which column layout (attach a blank template) | スクリーニングログと登録ログの現在の保管方法（Excel／REDCap／紙）と列構成（空のテンプレートを添付） | 目前篩選紀錄與收案紀錄的保存方式（Excel／REDCap／紙本）與欄位格式（附空白範本） | |
| 46 | Delegation log: who keeps it, format, training records (GCP certificates) format | 分担医師・協力者リストの管理者、形式、GCP 研修記録の形式 | 授權名冊由誰保管、格式、GCP 訓練證明格式 | |
| 47 | How the treating physician is asked today before a patient is approached (phone / in person / EMR message) | 現在、患者に声をかける前に主治医へどのように了承を得ているか（電話／対面／カルテのメッセージ） | 目前接觸病人前如何徵得主治醫師同意（電話／當面／病歷訊息） | |
| 48 | Pharmacy: can dispensing dates for study drugs be exported (yes / no / later)? | 薬剤部：治験薬の調剤日を出力できるか | 藥局：是否可匯出試驗用藥給藥日期 | |

### 2.5 Hosting, hospital IT and network · ホスティング、医療情報部、ネットワーク · 主機、資訊室與網路

| # | English | 日本語 | 繁體中文 | Answer |
| --- | --- | --- | --- | --- |
| 49 ① | **Hosting**: an appliance supplied by Aimedics (Japan: a DGX Spark with a CPU workstation, or an RTX PRO 6000 box, decided after the Spark benchmark) / the hospital's own GPU server shared with other work (CGMH: the B200 server) / the hospital's private cloud with GPU as interim hosting | **ホスティング**：Aimedics が納入する専用機（日本：DGX Spark と CPU ワークステーション、または RTX PRO 6000 機。Spark のベンチマーク後に決定）／他業務と共用の病院 GPU サーバ／暫定としての病院プライベートクラウド（GPU 付き） | **主機方式**：Aimedics 供應的專用主機（日本：DGX Spark 加 CPU 工作站，或 RTX PRO 6000 主機，於 Spark 基準測試後決定）／院方與其他工作共用的 GPU 伺服器（長庚：B200）／暫時使用院方具 GPU 的私有雲 | |
| 50 ① | **Does the site have a GPU private cloud approved for identified patient data today?** (yes: attach the approval / no: the fallback is a date slip, not hosting) | **識別可能な患者データの取り扱いが承認された GPU 付きプライベートクラウドが今あるか**（はい：承認文書を添付／いいえ：代替は日程の後ろ倒しであってホスティングではない） | **院方目前是否有已核准處理可識別病人資料、具 GPU 的私有雲？**（是：附核准文件／否：備案為延後日期，而非改用其他主機） | |
| 51 ① | For a shared or private-cloud host: container platform (Docker / Kubernetes / other), GPU type and count, **two dedicated MIG instances for TrialBox**, one for each model (profile and memory in GB of each, for example about 45 GB for the judge and about 23 GB for the verifier; a time-slice of SMs or an MPS share is not acceptable for patient data), CPU and RAM quota, storage class and size (from question 25, not a default), who creates the namespace or project | 共用・クラウドの場合：コンテナ基盤（Docker／Kubernetes／その他）、GPU の種類と数、**TrialBox 専用の MIG インスタンス 2 つ**（モデルごとに 1 つ。それぞれのプロファイルとメモリ GB、例：判定モデル約 45 GB、検証モデル約 23 GB。SM の時分割や MPS 共有は患者データには不可）、CPU と RAM のクォータ、ストレージの種類と容量（質問 25 から算出）、ネームスペースの作成者 | 共用或私有雲：容器平台（Docker／Kubernetes／其他）、GPU 型號與數量、**TrialBox 專用的兩個 MIG 執行個體**（每個模型一個；各自的規格與記憶體 GB，例如判斷模型約 45 GB、驗證模型約 23 GB；SM 時間切片或 MPS 共用不適用於病人資料）、CPU 與 RAM 配額、儲存類別與容量（依第 25 題計算，非預設值）、由誰建立 namespace | |
| 51a ① | For a shared or private-cloud host: **which platform runs the containers**: Kubernetes (distribution and version, for example OpenShift 4.16 or Kubernetes 1.30), plain Docker or Podman on a host the hospital runs, or a batch scheduler (Slurm, PBS, a vendor's job queue)? TrialBox's console, database and model servers run all day: a batch-only scheduler cannot hold them (OPS-066; RUNBOOK §17, §26) | 共用・クラウドの場合：**コンテナを動かす基盤**：Kubernetes（ディストリビューションと版、例 OpenShift 4.16、Kubernetes 1.30）、病院が運用するホスト上の Docker／Podman、またはバッチスケジューラ（Slurm、PBS、ベンダーのジョブキュー）のどれか。TrialBox のコンソール、データベース、モデルサーバは常時稼働するため、バッチ専用のスケジューラでは動かせない | 共用或私有雲：**執行容器的平台**：Kubernetes（發行版與版本，例如 OpenShift 4.16、Kubernetes 1.30）、院方管理主機上的 Docker／Podman，或批次排程器（Slurm、PBS、廠商的工作佇列）？TrialBox 的主控台、資料庫與模型伺服器需全天運作，僅支援批次工作的排程器無法承載 | |
| 51b ① | For a shared or private-cloud host: **who is root and who administers the shared storage**: the names or team of the platform's administrators, who can read TrialBox's volumes, pod memory and Secrets, whether that access is logged and where; who restarts TrialBox's pods at night (the first call when the morning mail does not arrive) | 共用・クラウドの場合：**root 権限者と共有ストレージの管理者**：基盤管理者の氏名またはチーム、TrialBox のボリューム・Pod のメモリ・Secret を読める者、そのアクセスの記録の有無と記録先、夜間に TrialBox の Pod を再起動する者（朝のメールが届かないときの一次連絡先） | 共用或私有雲：**誰擁有 root、誰管理共用儲存**：平台管理者姓名或團隊；誰能讀取 TrialBox 的儲存卷、Pod 記憶體與 Secret；該存取是否留有紀錄及紀錄位置；夜間由誰重新啟動 TrialBox 的 Pod（早晨郵件未送達時的第一聯絡人） | |
| 51c ① | For a shared or private-cloud host: **which storage**: a block storage class (ReadWriteOnce, encrypted) for the database, a shared class (ReadWriteMany, encrypted) for the other volumes, each with its specification; the backup share TrialBox's nightly job writes to (NFS or SMB, bound as a volume claim, size from question 25); how long the platform keeps pod logs and whether it forwards them to the hospital's SIEM | 共用・クラウドの場合：**ストレージ**：データベース用のブロックストレージ（ReadWriteOnce、暗号化）、その他のボリューム用の共有ストレージ（ReadWriteMany、暗号化）と、それぞれの仕様書。TrialBox の夜間ジョブが書き込むバックアップ共有（NFS または SMB、ボリュームクレームとして割り当て、容量は質問 25 から）。基盤が Pod のログを保持する期間と、病院の SIEM への転送の有無 | 共用或私有雲：**儲存**：資料庫用的區塊儲存類別（ReadWriteOnce、加密）、其他儲存卷用的共用類別（ReadWriteMany、加密）及各自規格文件；TrialBox 夜間備份工作寫入的備份共用區（NFS 或 SMB，以 volume claim 掛載，容量依第 25 題）；平台保留 Pod 日誌的期間，以及是否轉送至院方 SIEM | |
| 52 | For a shared or private-cloud host: who patches the host OS, the container runtime, the GPU driver; maintenance windows; how TrialBox is told before a change; who is on call when the morning mail does not arrive | 共用・クラウドの場合：ホスト OS、コンテナランタイム、GPU ドライバのパッチ適用者、保守時間帯、変更前の通知方法、朝のメールが届かないときの当番 | 共用或私有雲：主機作業系統、容器執行環境、GPU 驅動程式由誰更新；維護時段；變更前如何通知；早晨郵件未送達時由誰值班 | |
| 53 A | For a shared or private-cloud host: isolation (separate namespace, network policy, encrypted storage class and its setting, who has root on the host and whether root access to volumes is logged); **does the hospital operate a KMS or HSM that can hold TrialBox's key-encryption key?** (yes / no: the steward unseals at start) | 共用・クラウドの場合：分離（ネームスペース、ネットワークポリシー、暗号化ストレージの種類と設定、ホストの root 権限者とボリュームへのアクセス記録の有無）。**TrialBox の鍵暗号化鍵を保管できる KMS または HSM を病院が運用しているか**（はい／いいえ：起動時にスチュワードが解錠） | 共用或私有雲：隔離（獨立 namespace、網路政策、加密儲存類別及設定、誰擁有主機 root、root 存取儲存卷是否留有紀錄）；**院方是否營運可保管 TrialBox 金鑰加密金鑰的 KMS 或 HSM？**（是／否：由資料管理人於啟動時解封） | |
| 54 ② | For an appliance: delivery address, receiving contact, rack or desk, power and UPS, Windows 11 edition required, BitLocker recovery-key escrow procedure; **the hospital's answer on RAM (128 GB or 256 GB) and disk (2 × 2 TB or 2 × 4 TB) given question 25 and all history**, and who pays the difference | 専用機の場合：納入先住所、受領担当、設置場所、電源と UPS、求める Windows 11 のエディション、BitLocker 回復キーの預託手順。**質問 25 と全履歴を踏まえた RAM（128 GB か 256 GB）とディスク（2 TB×2 か 4 TB×2）の病院の回答**と差額の負担者 | 專用主機：送達地址、收貨人、機櫃或桌面、電源與 UPS、要求的 Windows 11 版本、BitLocker 復原金鑰託管程序；**依第 25 題與全部歷史，院方對 RAM（128 GB 或 256 GB）與磁碟（2 × 2 TB 或 2 × 4 TB）的回答**，差額由誰負擔 | |
| 55 A | Device registration: the hospital's form for a new device on the clinical network; lead time; security software (EDR / antivirus) the hospital requires on the host and in WSL2; how Windows security updates reach an offline host (WSUS / offline bundle / cadence); who holds the Windows administrator account | 端末登録：臨床ネットワークへの新規端末の申請様式、所要期間、病院が求めるセキュリティソフト（EDR／ウイルス対策）のホストと WSL2 への導入、オフライン機への Windows 更新の配布方法（WSUS／オフラインバンドル／頻度）、Windows 管理者アカウントの保有者 | 設備登錄：臨床網路新設備的申請表、前置時間、院方要求安裝於主機與 WSL2 的資安軟體（EDR／防毒）、離線主機如何取得 Windows 安全更新（WSUS／離線套件／頻率）、Windows 管理者帳號由誰持有 | |
| 56 ① | Network: which segment or VLAN TrialBox sits in; which clients (clinic PCs, PI devices) must reach the console; firewall change process and lead time | ネットワーク：TrialBox を置くセグメント／VLAN、コンソールに到達する端末（外来 PC、医師の端末）、ファイアウォール変更の手続きと所要期間 | 網路：TrialBox 所在網段／VLAN；需連到主控台的端末（門診電腦、醫師裝置）；防火牆變更流程與前置時間 | |
| 57 ① | A DNS name for the console inside the hospital, and a certificate (hospital CA / public CA / Caddy internal CA accepted on the clinic PCs) | 院内でのコンソールの DNS 名と証明書（院内 CA／公的 CA／Caddy 内部 CA を外来 PC に配布） | 院內主控台的 DNS 名稱與憑證（院內 CA／公開 CA／Caddy 內部 CA 佈署至門診電腦） | |
| 58 ① | Directory: AD/LDAP available for sign-in (yes / no); a service account for the bind; group names for roles (steward, PI, CRC, admin); the hospital's MFA policy; how accounts are closed when staff leave | ディレクトリ：AD/LDAP でのサインインの可否、バインド用サービスアカウント、役割ごとのグループ名、病院の多要素認証の方針、退職時のアカウント停止手順 | 目錄服務：是否可用 AD/LDAP 登入；綁定用服務帳號；各角色群組名稱；院方多因子驗證政策；人員離職時如何停用帳號 | |
| 59 | Mail: SMTP relay host and port for outbound mail; whether a mailbox for the intake exists; whether mail with links is allowed; the trial office's mailbox for SAE copies | メール：送信に使う SMTP リレーのホストとポート、受付用メールボックスの有無、リンク付きメールの可否、SAE の写しを送る治験事務局のメールボックス | 郵件：對外寄信的 SMTP 中繼主機與連接埠；是否有收件信箱；是否允許含連結的郵件；接收 SAE 副本的試驗辦公室信箱 | |
| 60 | NTP server inside the hospital; syslog or SIEM destination if the hospital requires log forwarding | 院内の NTP サーバ。ログ転送が必要な場合の syslog／SIEM の宛先 | 院內 NTP 伺服器；如需日誌轉送，syslog 或 SIEM 的目的地 | |
| 61 | Backup target: a hospital NAS share or USB disk for the encrypted nightly backup; who keeps the backup private key envelope; the hospital's RPO and RTO expectations | バックアップ先：暗号化した夜間バックアップ用の NAS 共有または USB ディスク、バックアップ秘密鍵の封筒の保管者、病院が求める RPO と RTO | 備份目標：加密每夜備份用的 NAS 共享或 USB 磁碟；備份私鑰信封由誰保管；院方對 RPO 與 RTO 的要求 | |
| 62 | Internet from TrialBox: none (default; registries from the offline pack) / ClinicalTrials.gov allowed | TrialBox からのインターネット接続：なし（既定、登録情報はオフラインパックから）／ClinicalTrials.gov のみ許可 | TrialBox 對外網際網路：無（預設；登錄資料來自離線資料包）／僅允許 ClinicalTrials.gov | |
| 63 | Remote assistance policy: none / screen-share without patient data approved by | リモート支援の方針：なし／患者データを含まない画面共有を承認する者 | 遠端協助政策：無／不含病人資料之螢幕分享由誰核准 | |
| 64 | PI device path: how investigators open the console (clinic PC beside the EMR / hospital phone / personal phone on hospital Wi-Fi or VPN); is a TOTP app allowed on that device; the hospital's session-timeout and idle-lock policy on shared clinic PCs | 医師の端末経路：コンソールの開き方（電子カルテ横の外来 PC／病院の端末／院内 Wi-Fi または VPN の私用端末）、その端末で TOTP アプリが使えるか、共用外来 PC のセッションタイムアウトと画面ロックの方針 | 主持人裝置路徑：如何開啟主控台（電子病歷旁的門診電腦／院方手機／院內 Wi-Fi 或 VPN 的個人手機）；該裝置可否安裝 TOTP 應用程式；共用門診電腦的連線逾時與閒置鎖定政策 | |
| 65 | EMR launch: can the EMR open a patient by chart number from a URL or a copied id? (vendor / version / not possible) | 電子カルテ連携：URL または ID のコピーで患者を開けるか（ベンダー／版／不可） | 電子病歷連動：能否以 URL 或複製的病歷號開啟病人（廠商／版本／不可） | |
| 66 ① | Vulnerability scan or security review before go-live: required (yes / no), by whom, lead time, acceptance criteria | 稼働前の脆弱性診断・セキュリティ審査：要否、実施者、所要期間、合格条件 | 上線前弱點掃描或資安審查：是否需要、執行者、前置時間、通過標準 | |
| 67 | Incident reporting: the hospital's contact and clock for a security or privacy incident; whether the hospital is a designated agency under 資通安全管理法 (Taiwan) | インシデント報告：病院の窓口と報告期限 | 事件通報：院方窗口與時限；醫院是否為資通安全管理法之特定非公務機關 | |
| 68 | Decommissioning: the hospital's media-disposal rule for disks and backups | 廃棄：ディスクとバックアップ媒体の廃棄規則 | 汰除：磁碟與備份媒體的銷毀規則 | |
| 69 | Vendor people on site: which Aimedics persons will work in the hospital, for which steps, with which badge and accounts | 院内で作業する供給者の担当者：誰が、どの工程で、どの入館証とアカウントで | 供應商到院人員：哪些 Aimedics 人員、於哪些步驟、使用何種門禁與帳號 | |

### 2.6 Operations · 運用 · 營運

| # | English | 日本語 | 繁體中文 | Answer |
| --- | --- | --- | --- | --- |
| 70 | Clinic-PC layout: can the TrialBox page be open beside the EMR window? | 外来 PC で電子カルテの横に TrialBox の画面を開けるか | 門診電腦能否將 TrialBox 頁面開在電子病歷旁 | |
| 71 | Printing: a printer the CRC can use for the reminder card and the clinic-day slip | CRC が案内カードと外来日のスリップを印刷できるプリンタ | CRC 可用於列印提醒卡與門診日清單的印表機 | |
| 72 | **The night window**: the hours between the last feed file and the first clinic in which TrialBox may use the GPU and the database at full load (for example 22:00 to 06:00); other nightly jobs on a shared host in that window | **夜間ウィンドウ**：最後のフィード受領から最初の外来までの間で TrialBox が GPU とデータベースを全負荷で使える時間帯（例 22:00〜06:00）。共用ホストでその時間帯に動く他の夜間処理 | **夜間時段**：最後一批匯出到首診之間，TrialBox 可全速使用 GPU 與資料庫的時段（例如 22:00 至 06:00）；共用主機於該時段的其他夜間作業 | |
| 73 ① | Two normal weeks for the workload baseline, **before any training** and not 年末年始, 成人の日 week or Lunar New Year (the plan proposes 2026-11-30 to 2026-12-11) | 業務量ベースライン測定に使える通常の 2 週間。**研修より前**で、年末年始、成人の日の週、旧正月を除く（計画案は 2026-11-30〜12-11） | 可供工作量基準量測的兩個正常週，**在任何訓練之前**，避開農曆新年（計畫建議 2026-11-30 至 12-11） | |
| 74 | Training dates for steward, second reviewer (CGMH), CRC, PI, admin and IT | スチュワード、CRC、医師、管理者、IT の研修日程 | 資料管理人、第二審核人（長庚）、CRC、主持人、管理者、IT 的訓練日期 | |
| 75 | Preferred go-live week within the plan (CGMH about 2027-04-30; Japan about 2027-05-14; never within ten working days before a national holiday period) | 計画内で希望する稼働開始週（CGMH は 2027-04-30 頃、日本は 2027-05-14 頃。連休の前 10 営業日以内は避ける） | 計畫內偏好的上線週（長庚約 2027-04-30；日本約 2027-05-14；不在國定連假前十個工作日內） | |

## 3. Attachments and signatures · 添付と署名 · 附件與簽署

Attachments (**A** above): the IRB approval letter and the protocol text on recruitment (13 to 16); the ICF version list (18); table headers or a storage listing without data (28 to 30); the lab table (36); the staff directory export format (33); the screening-log template (45); the device registration form (55); the platform description and the isolation evidence for a shared host (51 to 53); the private-cloud approval (50).

添付：倫理審査承認書と募集方法に関するプロトコル本文（13〜16）、説明同意文書の版一覧（18）、データを含まないテーブルヘッダまたはストレージ一覧（28〜30）、検査マスタ（36）、職員名簿の出力形式（33）、スクリーニングログのテンプレート（45）、端末登録様式（55）、共用ホストの基盤説明と分離の証拠（51〜53）、プライベートクラウドの承認文書（50）。

附件：IRB 核准函與計畫書中有關收案方法的原文（13〜16）、同意書版本清單（18）、不含資料的資料表欄位名或儲存清單（28〜30）、檢驗項目表（36）、人員名冊匯出格式（33）、篩選紀錄範本（45）、設備登錄表（55）、共用主機的平台說明與隔離證據（51〜53）、私有雲核准文件（50）。

| Role · 役割 · 角色 | Name · 氏名 · 姓名 | Date · 日付 · 日期 | Signature · 署名 · 簽名 |
| --- | --- | --- | --- |
| Hospital IT lead · 医療情報部責任者 · 資訊室主管 | | | |
| Principal investigator · 治験責任医師 · 試驗主持人 | | | |
| Data steward · データスチュワード · 資料管理人 | | | |
| Second reviewer (CGMH) · 第二審核人（長庚） | | | |
| Native reader of the 日本語 column · 日本語欄の確認者 | | | |
| Native reader of the 繁體中文 column · 繁體中文欄位確認者 | | | |
| Aimedics | | | |
