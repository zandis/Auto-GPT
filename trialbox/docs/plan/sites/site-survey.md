# TrialBox site survey (TB-PLAN-05 WS-10.2, WS-11.2)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-01 |
| Version | 0.1 (draft, 2026-11-09) |
| Owner | Changfu Kuo (Aimedics) |
| Filled by | the site's IT contact, the data-feed contact, the privacy office and the PI, with Changfu (CGMH) or Makoto (Japan) |
| Status | Draft. One copy per site. The signed copy is the entry condition for design freeze (G2) and the basis of the site mapping, the IQ protocol and the hospital IT security pack. |
| Languages | English first; 日本語 and 繁體中文 follow in §B and §C with the same question numbers. |

## A. English

### A.1 How to use this form

Answer every question. "Unknown" is an answer; write who can find out and by when. Attach documents where asked. No patient data goes on this form or in any attachment; a 10-patient sample is handed over separately under the data-processing agreement, de-identified where the site requires it. The filled form is signed by the hospital IT lead and the PI and kept in the site's release record.

### A.2 Contacts

| # | Question | Answer |
| --- | --- | --- |
| 1 | Principal investigator(s) for the pilot studies, department, mail | |
| 2 | Data steward (the hospital's named person who holds the TrialBox repository) | |
| 3 | Trial office / research office contact (delegation log, IRB filings, invoicing) | |
| 4 | Hospital IT: device registration, network, directory (AD/LDAP), certificates | |
| 5 | Hospital IT: security review, vulnerability scan (if required), incident reporting | |
| 6 | Data-feed owner (the team that produces the EMR export, SS-MIX2 storage, HIS views or FHIR) | |
| 7 | Privacy office / 個人情報保護管理者 / 個資保護人員 | |
| 8 | REDCap administrator (if REDCap is used) | |
| 9 | Pharmacy contact (only for the dispensing-date input) | |
| 10 | Who signs the data-processing agreement and the platform licence for the hospital | |

### A.3 IRB and legal basis

| # | Question | Answer |
| --- | --- | --- |
| 11 | IRB approval number and date for the pilot; approval end date | |
| 12 | Does the approved protocol name TrialBox's screen of the hospital's records as the recruitment method? (yes / no / unsure: attach the text) | |
| 13 | Does the approval cover **whole-hospital screening** (patients of any department, not only the PI's)? | |
| 14 | Does the approval cover **patient profiles** (a cited summary per study patient, written by the model, read by study staff)? | |
| 15 | Does the approval cover the opt-out notice for research use of existing records, and where is the notice posted? | |
| 16 | If 12 to 15 are not all "yes": the next IRB meeting date and the submission deadline for an amendment | |
| 17 | Approved ICF versions for each pilot study (version, date, language) | |
| 18 | The hospital's rule for identified pre-screening (who may open which chart, per project application if any) | |
| 19 | Which legal basis the privacy office relies on for pre-screening with re-identification (care relationship + IRB; other) | |
| 20 | SAE reporting rules at this site: to the sponsor, to the IRB / head of institution, to the regulator, in days (fatal or life-threatening / other serious) | |
| 21 | Record retention rule per study (years after the end of the study or approval) | |

### A.4 Data feed

| # | Question | Answer |
| --- | --- | --- |
| 22 | Which input will the site start with? (hospital database export CSV / HIS SQL views / SS-MIX2 storage / FHIR bulk export / spreadsheets / charts pasted or uploaded one by one / a mix) | |
| 23 | EMR vendor and version; HIS self-built or vendor | |
| 24 | For SS-MIX2: storage root path, vendor, standardized storage version, extended storage present (yes / no), 標準病名 and JLAC10 codes present (always / sometimes / never), deletion flags used | |
| 25 | For CSV or SQL views: table list, one header row per table (no data), date format (ISO / era / ROC 7-digit), encoding (UTF-8 / Shift_JIS / CP932 / Big5), delimiter | |
| 26 | For FHIR: base URL or export path, FHIR version, profiles (JP Core / TW Core), bulk export supported (yes / no), authentication | |
| 27 | How often can the feed be produced? (nightly / weekly / one-time dump) Who runs it? How does it reach the box? (LAN share / SFTP / USB) | |
| 28 | Which years of history exist in the feed, and from which year are records electronic (EMR since)? Are earlier records paper or scanned? | |
| 29 | Does the feed carry the attending or ordering physician per encounter? How reliable is it? Is there a staff directory the site can export (id, name, department)? | |
| 30 | Does the feed carry an appointment or booking source (future visits)? | |
| 31 | Note types in the feed (progress, discharge, consult, nursing, reports) and their text encoding; mixed-language notes (yes / no) | |
| 32 | Laboratory: local test codes (JLAC10, NHI order codes, hospital codes), units per analyte as reported (e.g. CRP mg/dL or mg/L; creatinine mg/dL or µmol/L; HbA1c NGSP or JDS before 2012), a lab table export (code, name, unit) | |
| 33 | Diagnoses: ICD-10-CM edition(s) in use by year (Taiwan 2014 / 2023), 標準病名 with or without ICD-10, suspected-diagnosis flag present | |
| 34 | Medicines: code system (YJ / HOT / NHI drug code / local), ATC present (yes / no) | |
| 35 | Opt-out: where the hospital keeps research opt-outs (EMR flag exported / vendor field not exported / paper at the records office / none) | |
| 36 | Deaths: how the feed shows a death; whether deaths outside the hospital are recorded | |
| 37 | A de-identified 10-patient sample of the real feed can be provided by (date), under (agreement) | |
| 38 | Known data quality issues (missing codes, department master gaps, date gaps, wording drift) | |

### A.5 Trial systems

| # | Question | Answer |
| --- | --- | --- |
| 39 | REDCap: version, URL, test project available (yes / no), API enabled (yes / no), who issues API tokens, longitudinal projects and repeating instruments used | |
| 40 | Sponsor EDCs in use for the pilot studies (name, ODM import supported, weekly export available) | |
| 41 | Where the screening log and enrolment log are kept today (Excel / REDCap / paper) and in which column layout (attach a blank template) | |
| 42 | Delegation log: who keeps it, format, training records (GCP certificates) format | |
| 43 | How the treating physician is asked today before a patient is approached (phone / in person / EMR message) | |
| 44 | Pharmacy: can dispensing dates for study drugs be exported (yes / no / later)? | |

### A.6 Hospital IT and network

| # | Question | Answer |
| --- | --- | --- |
| 45 | **Hosting**: an appliance box supplied by Aimedics (Japan) / the hospital's own GPU server shared with other work (CGMH: the B200 server) / the hospital's private cloud with GPU as interim hosting | |
| 46 | For a shared or private-cloud host: container platform (Docker / Kubernetes / other), GPU type and count, the **fixed GPU quota** for TrialBox (memory in GB, share of SMs or MIG slice), CPU and RAM quota, storage class and size (2 TB needed at 50,000 patients with all history), who creates the namespace or project | |
| 47 | For a shared or private-cloud host: who patches the host OS, the container runtime, the GPU driver; maintenance windows; how TrialBox is told before a change | |
| 48 | For a shared or private-cloud host: isolation between TrialBox and other tenants (separate namespace, network policy, storage encryption, who else has root on the host); whether the host is approved for identified patient data (document the approval) | |
| 49 | For an appliance box: delivery address, receiving contact, rack or desk, power and UPS, Windows 11 edition the hospital requires, BitLocker recovery-key escrow procedure | |
| 50 | Device registration: the hospital's form for a new device on the clinical network; lead time; security software the hospital requires on the box | |
| 51 | Network: which segment or VLAN TrialBox sits in; which clients (clinic PCs, PI phones) must reach the console; firewall change process and lead time | |
| 52 | A DNS name for the console inside the hospital, and a certificate (hospital CA / public CA / Caddy internal CA accepted on the clinic PCs) | |
| 53 | Directory: AD/LDAP available for sign-in (yes / no); a service account for the bind; group names for roles (steward, PI, CRC, admin); MFA policy of the hospital | |
| 54 | Mail: SMTP relay host and port for outbound mail from the box; whether a mailbox for the intake exists; whether mail with links is allowed | |
| 55 | NTP server inside the hospital | |
| 56 | Backup target: a hospital NAS share or USB disk for the encrypted nightly backup; who keeps the backup private key envelope | |
| 57 | Internet from the box: none (default; registries from the offline pack) / ClinicalTrials.gov allowed | |
| 58 | Remote assistance policy: none / screen-share without patient data approved by | |
| 59 | PI device path: how investigators open the console (clinic PC beside the EMR / hospital phone / personal phone on hospital Wi-Fi or VPN); is a TOTP app allowed on that device | |
| 60 | EMR launch: can the EMR open a patient by chart number from a URL or a copied id? (vendor / version / not possible) | |
| 61 | Vulnerability scan or security review before go-live: required (yes / no), by whom, lead time, acceptance criteria | |
| 62 | Incident reporting: the hospital's contact and clock for a security or privacy incident; whether the hospital is a designated agency under 資通安全管理法 (Taiwan) | |
| 63 | Decommissioning: the hospital's media-disposal rule for disks and backups | |

### A.7 Operations

| # | Question | Answer |
| --- | --- | --- |
| 64 | Clinic-PC layout: can the TrialBox page be open beside the EMR window? | |
| 65 | Printing: a printer the CRC can use for the reminder card and the clinic-day slip | |
| 66 | Two normal weeks for the workload baseline (not 年末年始, not Lunar New Year) | |
| 67 | Training dates for steward, CRC, PI, admin and IT | |
| 68 | Preferred go-live week within the plan (CGMH before 2027-02-05; Japan the week after) | |

### A.8 Attachments and signatures

Attachments: the IRB approval letter and protocol text about recruitment (12 to 15); the ICF version list (17); table headers or a storage listing without data (24 to 26); the lab table (32); the staff directory export format (29); the screening-log template (41); the device registration form (50); the platform description for a shared host (46 to 48).

| Role | Name | Date | Signature |
| --- | --- | --- | --- |
| Hospital IT lead | | | |
| Principal investigator | | | |
| Data steward | | | |
| Aimedics | | | |

## B. 日本語

### B.1 使い方

すべての質問に答えてください。「不明」も回答です。その場合は誰がいつまでに確認するかを書いてください。求められた箇所には資料を添付してください。この用紙と添付資料に患者情報を書かないでください。10名分のサンプルは、データ処理契約のもとで別途、病院が求める場合は匿名化して渡します。記入済みの用紙は医療情報部の責任者と治験責任医師が署名し、サイトのリリース記録に保管します。

### B.2 連絡先（質問 1〜10）

1 治験責任医師、診療科、メール。2 データスチュワード（TrialBox のデータベースを預かる病院の担当者）。3 治験事務局・研究支援部門の窓口（分担医師リスト、IRB 申請、請求）。4 医療情報部：端末登録、ネットワーク、ディレクトリ（AD/LDAP）、証明書。5 医療情報部：セキュリティ審査、脆弱性診断（必要な場合）、インシデント報告。6 データ提供元（電子カルテ出力、SS-MIX2 ストレージ、HIS ビュー、FHIR を出す部門）。7 個人情報保護管理者。8 REDCap 管理者（使用する場合）。9 薬剤部窓口（治験薬の調剤日の入力のみ）。10 病院側でデータ処理契約とプラットフォーム利用契約に署名する人。

### B.3 倫理審査と法的根拠（質問 11〜21）

11 倫理審査の承認番号、承認日、有効期限。12 承認済みプロトコルに「TrialBox による院内記録のスクリーニング」が募集方法として明記されているか（はい／いいえ／不明：該当文を添付）。13 承認が**病院全体のスクリーニング**（責任医師の診療科以外の患者を含む）を対象としているか。14 承認が**患者プロファイル**（モデルが作成し研究スタッフが読む、引用付きの患者要約）を対象としているか。15 既存情報の研究利用に関するオプトアウト通知が承認に含まれ、どこに掲示されているか。16 12〜15 のいずれかが「はい」でない場合：次回委員会の日程と変更申請の締切。17 各試験の承認済み説明同意文書の版（版、日付、言語）。18 同定可能な状態での事前スクリーニングに関する院内規則（誰がどのカルテを開けるか、課題ごとの申請の有無）。19 再識別を伴う事前スクリーニングについて個人情報保護担当が依拠する法的根拠。20 この施設の SAE 報告規則：依頼者、IRB・病院長、規制当局への日数（死亡・生命を脅かす／その他の重篤）。21 試験ごとの記録保存期間。

### B.4 データフィード（質問 22〜38）

22 最初に使う入力（病院データベースの CSV 出力／HIS の SQL ビュー／SS-MIX2 ストレージ／FHIR 一括出力／表計算ファイル／カルテの貼り付けやアップロード／組み合わせ）。23 電子カルテベンダーと版、HIS は自社開発かベンダー製か。24 SS-MIX2：ストレージのルートパス、ベンダー、標準化ストレージの版、拡張ストレージの有無、標準病名と JLAC10 コードの有無（常に／時々／なし）、削除フラグの使用。25 CSV・SQL ビュー：テーブル一覧、各テーブルのヘッダ行のみ（データなし）、日付形式（ISO／和暦）、文字コード（UTF-8／Shift_JIS／CP932）、区切り文字。26 FHIR：ベース URL または出力パス、FHIR の版、プロファイル（JP Core）、一括出力の可否、認証。27 フィードの頻度（毎夜／毎週／一回限り）、実行者、ボックスへの受け渡し方法（LAN 共有／SFTP／USB）。28 フィードに含まれる履歴の年数と、電子化が始まった年（EMR since）。それ以前は紙かスキャンか。29 受診ごとの主治医・オーダー医の有無と信頼性。職員名簿（ID、氏名、診療科）を出力できるか。30 予約情報（将来の受診）の有無。31 フィードに含まれる記録の種類（経過記録、退院サマリ、コンサルト、看護記録、レポート）と文字コード。32 検査：ローカル検査コード（JLAC10、院内コード）、分析項目ごとの報告単位（CRP mg/dL か mg/L、クレアチニン mg/dL か µmol/L、2012 年以前の HbA1c は JDS か）、検査マスタの出力（コード、名称、単位）。33 病名：ICD-10 の版、標準病名の ICD-10 付与の有無、疑い病名フラグの有無。34 薬剤：コード体系（YJ／HOT／院内）、ATC の有無。35 オプトアウト：研究利用拒否の記録場所（カルテのフラグが出力される／ベンダー項目で出力されない／医事課の紙／なし）。36 死亡：フィードでの死亡の表現、院外死亡の記録の有無。37 匿名化した 10 名分のサンプルの提供可能日と契約。38 既知のデータ品質の問題（コード欠落、部門マスタの不備、日付の欠落、表記の揺れ）。

### B.5 治験システム（質問 39〜44）

39 REDCap：版、URL、テスト用プロジェクトの有無、API の有効化、API トークンの発行者、縦断プロジェクトと反復インストゥルメントの使用。40 対象試験で使用する依頼者 EDC（名称、ODM 取込の可否、週次出力の可否）。41 スクリーニングログと登録ログの現在の保管方法（Excel／REDCap／紙）と列構成（空のテンプレートを添付）。42 分担医師・協力者リストの管理者、形式、GCP 研修記録の形式。43 現在、患者に声をかける前に主治医へどのように了承を得ているか（電話／対面／カルテのメッセージ）。44 薬剤部：治験薬の調剤日を出力できるか。

### B.6 医療情報部とネットワーク（質問 45〜63）

45 **ホスティング**：Aimedics が納入するアプライアンス（日本）／病院の共用 GPU サーバ／暫定ホスティングとしての病院プライベートクラウド（GPU 付き）。46 共用・クラウドの場合：コンテナ基盤（Docker／Kubernetes／その他）、GPU の種類と数、TrialBox に割り当てる**固定 GPU クォータ**（メモリ GB、SM の割合または MIG）、CPU と RAM のクォータ、ストレージの種類と容量（全履歴・5 万人で 2 TB）、ネームスペースの作成者。47 共用・クラウドの場合：ホスト OS、コンテナランタイム、GPU ドライバのパッチ適用者、保守時間帯、変更前の TrialBox への通知方法。48 共用・クラウドの場合：他テナントとの分離（ネームスペース、ネットワークポリシー、ストレージ暗号化、ホストの root 権限者）、識別可能な患者データの取り扱いが承認されたホストか（承認文書）。49 アプライアンスの場合：納入先住所、受領担当、設置場所、電源と UPS、病院が求める Windows 11 のエディション、BitLocker 回復キーの預託手順。50 端末登録：臨床ネットワークへの新規端末の申請様式、所要期間、病院が求めるセキュリティソフト。51 ネットワーク：TrialBox を置くセグメント／VLAN、コンソールに到達する端末（外来 PC、医師の端末）、ファイアウォール変更の手続きと所要期間。52 院内でのコンソールの DNS 名と証明書（院内 CA／公的 CA／Caddy 内部 CA を外来 PC に配布）。53 ディレクトリ：AD/LDAP でのサインインの可否、バインド用サービスアカウント、役割ごとのグループ名、病院の多要素認証の方針。54 メール：ボックスからの送信に使う SMTP リレーのホストとポート、受付用メールボックスの有無、リンク付きメールの可否。55 院内の NTP サーバ。56 バックアップ先：暗号化した夜間バックアップ用の NAS 共有または USB ディスク、バックアップ秘密鍵の封筒の保管者。57 ボックスからのインターネット接続：なし（既定、登録情報はオフラインパックから）／ClinicalTrials.gov のみ許可。58 リモート支援の方針：なし／患者データを含まない画面共有を承認する者。59 医師の端末経路：コンソールの開き方（電子カルテ横の外来 PC／病院の端末／院内 Wi-Fi または VPN の私用端末）、その端末で TOTP アプリが使えるか。60 電子カルテ連携：URL または ID のコピーで患者を開けるか（ベンダー／版／不可）。61 稼働前の脆弱性診断・セキュリティ審査：要否、実施者、所要期間、合格条件。62 インシデント報告：病院の窓口と報告期限。63 廃棄：ディスクとバックアップ媒体の廃棄規則。

### B.7 運用（質問 64〜68）

64 外来 PC で電子カルテの横に TrialBox の画面を開けるか。65 CRC が案内カードと外来日のスリップを印刷できるプリンタ。66 業務量ベースライン測定に使える通常の 2 週間（年末年始を除く）。67 スチュワード、CRC、医師、管理者、IT の研修日程。68 計画内で希望する稼働開始週（日本は CGMH の翌週）。

### B.8 添付と署名

添付：倫理審査承認書と募集方法に関するプロトコル本文（12〜15）、説明同意文書の版一覧（17）、データを含まないテーブルヘッダまたはストレージ一覧（24〜26）、検査マスタ（32）、職員名簿の出力形式（29）、スクリーニングログのテンプレート（41）、端末登録様式（50）、共用ホストの基盤説明（46〜48）。署名：医療情報部責任者、治験責任医師、データスチュワード、Aimedics。

## C. 繁體中文

### C.1 使用方式

請回答每一題。「不確定」也是答案，請寫明由誰在何時確認。要求附件處請附上文件。本表與附件不得含任何病人資料；10 位病人的樣本依資料處理契約另行交付，院方要求時先去識別化。填妥後由資訊室主管與試驗主持人簽署，存入該院的發布紀錄。

### C.2 聯絡人（問題 1〜10）

1 試驗主持人、科別、電子郵件。2 資料管理人（院方指定、掌管 TrialBox 資料庫的人員）。3 臨床試驗中心／研究部窗口（授權名冊、IRB 送件、請款）。4 資訊室：設備登錄、網路、目錄服務（AD/LDAP）、憑證。5 資訊室：資安審查、弱點掃描（如需要）、事件通報。6 資料來源負責單位（產出 HIS 匯出、SQL 檢視表或 FHIR 的團隊）。7 個資保護人員。8 REDCap 管理者（如使用）。9 藥局窗口（僅供試驗用藥給藥日期的輸入）。10 代表醫院簽署資料處理契約與平台授權契約的人。

### C.3 IRB 與法律依據（問題 11〜21）

11 本次試行的 IRB 核准編號、日期與到期日。12 核准的計畫書是否載明「以 TrialBox 篩選院內病歷」為收案方法（是／否／不確定：附上原文）。13 核准是否涵蓋**全院篩選**（含主持人科別以外的病人）。14 核准是否涵蓋**病人概況**（由模型撰寫、研究人員閱讀、逐句引用病歷的病人摘要）。15 核准是否包含既有病歷研究使用的退出（opt-out）公告，公告於何處。16 若 12〜15 任一非「是」：下次 IRB 會議日期與修正案送件截止日。17 各試驗核准的受試者同意書版本（版本、日期、語言）。18 院內關於可識別狀態下預先篩選的規定（誰可開啟哪些病歷，是否需按專案申請）。19 個資保護人員對含再識別之預先篩選所依據的法律基礎（醫療關係加 IRB 核准；其他）。20 本院 SAE 通報規則：對試驗委託者、IRB、主管機關的天數（死亡或危及生命／其他嚴重）。21 各試驗的紀錄保存年限。

### C.4 資料來源（問題 22〜38）

22 起始輸入方式（院內資料庫 CSV 匯出／HIS SQL 檢視表／SS-MIX2／FHIR 批次匯出／試算表／逐份貼上或上傳病歷／混合）。23 電子病歷廠商與版本；HIS 為自建或廠商。24 SS-MIX2（如適用）：儲存根路徑、廠商、版本、延伸儲存、標準病名與 JLAC10 的有無、刪除旗標。25 CSV 或 SQL 檢視表：資料表清單、每表一列欄位名（不含資料）、日期格式（ISO／民國 7 碼）、編碼（UTF-8／Big5）、分隔符。26 FHIR：基底 URL 或匯出路徑、FHIR 版本、profile（TW Core）、是否支援批次匯出、認證方式。27 匯出頻率（每夜／每週／一次性）、執行者、送達方式（LAN 共享／SFTP／USB）。28 匯出涵蓋的年份，以及電子病歷起始年；更早的紀錄為紙本或掃描。29 每次就診是否含主治或開單醫師，可靠程度；是否可匯出人員名冊（代號、姓名、科別）。30 是否含預約（未來就診）來源。31 病歷文字類型（病程、出院摘要、會診、護理、報告）與編碼；是否中英夾雜。32 檢驗：本地檢驗代碼（健保醫令碼、院內碼）、各項目的報告單位（CRP mg/dL 或 mg/L；肌酸酐 mg/dL 或 µmol/L）、檢驗項目表匯出（代碼、名稱、單位）。33 診斷：各年度使用的 ICD-10-CM 版本（2014／2023）、疑似診斷旗標。34 藥品：代碼系統（健保藥品碼／院內碼）、是否含 ATC。35 退出（opt-out）：研究使用退出登錄於何處（病歷旗標且有匯出／廠商欄位未匯出／病歷室紙本／無）。36 死亡：匯出中如何呈現死亡；院外死亡是否記錄。37 可提供去識別化 10 位病人樣本的日期與依據契約。38 已知的資料品質問題。

### C.5 試驗系統（問題 39〜44）

39 REDCap：版本、URL、測試專案、API 是否開啟、API token 核發者、縱貫型專案與重複表單使用情形。40 本次試驗使用的委託者 EDC（名稱、是否支援 ODM 匯入、是否可每週匯出）。41 目前篩選紀錄與收案紀錄的保存方式（Excel／REDCap／紙本）與欄位格式（附空白範本）。42 授權名冊由誰保管、格式、GCP 訓練證明格式。43 目前接觸病人前如何徵得主治醫師同意（電話／當面／病歷訊息）。44 藥局：是否可匯出試驗用藥給藥日期。

### C.6 資訊室與網路（問題 45〜63）

45 **主機方式**：Aimedics 供應的專用主機（日本）／院方與其他工作共用的 GPU 伺服器（長庚：B200 伺服器）／暫時使用院方具 GPU 的私有雲。46 共用或私有雲：容器平台（Docker／Kubernetes／其他）、GPU 型號與數量、分配給 TrialBox 的**固定 GPU 配額**（記憶體 GB、SM 比例或 MIG 切片）、CPU 與 RAM 配額、儲存類別與容量（5 萬病人全部歷史需 2 TB）、由誰建立 namespace 或專案。47 共用或私有雲：主機作業系統、容器執行環境、GPU 驅動程式由誰更新；維護時段；變更前如何通知 TrialBox。48 共用或私有雲：與其他租戶的隔離（獨立 namespace、網路政策、儲存加密、誰擁有主機 root）；該主機是否已核准處理可識別病人資料（附核准文件）。49 專用主機：送達地址、收貨人、機櫃或桌面、電源與 UPS、院方要求的 Windows 11 版本、BitLocker 復原金鑰託管程序。50 設備登錄：臨床網路新設備的申請表、前置時間、院方要求安裝的資安軟體。51 網路：TrialBox 所在網段／VLAN；需連到主控台的端末（門診電腦、醫師手機）；防火牆變更流程與前置時間。52 院內主控台的 DNS 名稱與憑證（院內 CA／公開 CA／Caddy 內部 CA 佈署至門診電腦）。53 目錄服務：是否可用 AD/LDAP 登入；綁定用服務帳號；各角色群組名稱；院方多因子驗證政策。54 郵件：主機對外寄信的 SMTP 中繼主機與連接埠；是否有收件信箱；是否允許含連結的郵件。55 院內 NTP 伺服器。56 備份目標：加密每夜備份用的 NAS 共享或 USB 磁碟；備份私鑰信封由誰保管。57 主機對外網際網路：無（預設；登錄資料來自離線資料包）／僅允許 ClinicalTrials.gov。58 遠端協助政策：無／不含病人資料之螢幕分享由誰核准。59 主持人裝置路徑：如何開啟主控台（電子病歷旁的門診電腦／院方手機／院內 Wi-Fi 或 VPN 的個人手機）；該裝置可否安裝 TOTP 應用程式。60 電子病歷連動：能否以 URL 或複製的病歷號開啟病人（廠商／版本／不可）。61 上線前弱點掃描或資安審查：是否需要、執行者、前置時間、通過標準。62 事件通報：院方窗口與時限；醫院是否為資通安全管理法之特定非公務機關。63 汰除：磁碟與備份媒體的銷毀規則。

### C.7 營運（問題 64〜68）

64 門診電腦能否將 TrialBox 頁面開在電子病歷旁。65 CRC 可用於列印提醒卡與門診日清單的印表機。66 可供工作量基準量測的兩個正常週（避開農曆新年）。67 資料管理人、CRC、主持人、管理者、IT 的訓練日期。68 計畫內偏好的上線週（長庚於 2027-02-05 前）。

### C.8 附件與簽署

附件：IRB 核准函與計畫書中有關收案方法的原文（12〜15）、同意書版本清單（17）、不含資料的資料表欄位名或儲存清單（24〜26）、檢驗項目表（32）、人員名冊匯出格式（29）、篩選紀錄範本（41）、設備登錄表（50）、共用主機的平台說明（46〜48）。簽署：資訊室主管、試驗主持人、資料管理人、Aimedics。
