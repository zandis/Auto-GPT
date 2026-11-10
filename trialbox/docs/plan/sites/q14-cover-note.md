# Cover note to the committees and hospital IT (TB-SITE-07, owner answer Q-14)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-07 |
| Version | 0.1 draft (2026-11-10), card T-641 |
| From | the product owner, through each site's PI |
| To | the CGMH committee, the Japan site's committee, and each hospital's IT department and privacy office |
| Send by | Fri 2026-11-20 (plan v6 §10.4, Q-14) |
| Attachments | the commitments register `docs/validation/commitments.csv` (as a table); the supplement TB-SITE-06 (to the committees) |
| Languages | English (source); 日本語 and 繁體中文 below, **each needs a native read before it is sent** |
| Placeholders | [Hospital], [committee], [amendment reference], [date]: filled by the site. No personal names or contact details are written here. |

## A. English

**Subject: TrialBox, amendment [amendment reference]: controls in build, and the commitments register**

To the [committee] of [Hospital], and to the hospital's IT department and privacy office

The amendment filed on 2026-11-10 and the hospital IT security pack describe TrialBox as it will be when it is used
with patient data. Some of the controls they describe are still being built. We are telling you now, before the
committee meets, so that the approved text and the system stay the same.

1. **The controls marked \* below are in build.** Each is verified at the operational qualification (OQ) at the
   hospital **before any patient data is used**. If a function is not ready at go-live, its switch stays off and we tell
   the committee in writing.
2. **The commitments register is attached.** It lists every promise in the amendment, the IT pack and the opt-out
   notice, with the code and the test that keep it, or the work that finishes it, or a correction. It is checked
   automatically: a promise with no row stops the build.
3. **A short supplement to the amendment is attached** for the committee. It corrects five statements and adds the
   administrator's break-glass access.

Controls in build (\*):

- \* Masking of names, ID numbers and phone numbers in note text before indexing.
- \* The patient profile, its second-model check and physicians' annotations (switched off until verified).
- \* The "patients like this one" page (switched off until verified).
- \* The data-steward role, separate from the system administrator.
- \* The system administrator sees no patient data in routine work; patient data only by break-glass (a reason, one
  patient or one job, 60 minutes, audited, reviewed by the steward).
- \* Removal of an opted-out patient's stored note vectors and profiles by the opt-out worker (screening, lists and
  exports already exclude the patient from the moment the opt-out is recorded).
- \* A reason recorded with every view, and the daily signature of the audit chain with its copy on the hospital's share
  (the hash-chained audit log and its archive to the share are in place).
- \* Re-entry of the password before a chart-number reveal and an export (sign-in with a second factor is in place).
- \* No file with chart numbers sent by mail; such files are fetched in the console after sign-in. Until then none is
  mailed.
- \* Disk encryption checks, wrapped keys and encrypted outputs on the TrialBox host (backups are already encrypted to a
  key only the hospital holds).

Two items are **narrowed**, not built later: the treating physician's view is off at go-live and, when switched on,
shows the record and study names only, with no phenotype or eligibility layer; the setpoint and gap-rule layers are not
part of the first release.

\* Prompts and answers of model calls about patients are **not stored** by default (the default is being changed now).
A debug switch that stores them runs for at most 24 hours and is audited.

Nothing in this note or the supplement widens the use of patient data beyond the filed amendment.

[date]

## B. 日本語（要ネイティブ確認）

**件名：TrialBox 研究計画変更［変更申請番号］：構築中の管理策とコミットメント台帳について**

［病院名］［委員会名］御中、ならびに院内の情報システム部門・個人情報保護担当 御中

2026 年 11 月 10 日に提出した変更申請と院内向け IT セキュリティ資料は、患者データを用いて運用する時点の TrialBox を記載しています。記載した管理策の一部は現在構築中です。委員会の審議前にお知らせし、承認される文書とシステムの内容を一致させます。

1. **下記の \* 印の管理策は構築中です。** いずれも院内での運用時適格性確認（OQ）で検証し、**患者データを用いる前に**確認します。運用開始時に準備が整わない機能は、その機能を無効のままとし、委員会に書面でお知らせします。
2. **コミットメント台帳を添付します。** 変更申請、IT 資料、オプトアウト通知に記載したすべての約束について、それを担保するプログラムと試験、または完成させる作業、または訂正を一覧にしています。台帳は自動で照合され、行のない約束があるとビルドが止まります。
3. **委員会向けに短い補足を添付します。** 5 つの記載の訂正と、システム管理者の緊急時アクセス（ブレークグラス）の追記です。

構築中の管理策（\*）：

- \* カルテ文章中の氏名、番号、電話番号を索引作成の前にマスクする処理
- \* 患者プロファイル、第二のモデルによる照合、医師の注記（検証まで無効）
- \* 「類似患者」画面（検証まで無効）
- \* システム管理者とは別のデータスチュワードの役割
- \* システム管理者は通常業務で患者データを見ない。患者データはブレークグラスでのみ（理由、患者 1 名または処理 1 件、60 分、監査記録、スチュワードによる確認）
- \* オプトアウトした患者の保存済みベクトルとプロファイルの削除（スクリーニング、一覧、出力からは記録した時点で除外済み）
- \* すべての閲覧への理由の記録、監査チェーンの毎日の署名と院内共有への写しの保存（ハッシュチェーンによる監査記録と共有への保管は実装済み）
- \* 患者番号の表示と出力の前のパスワード再入力（二要素サインインは実装済み）
- \* 患者番号を含むファイルをメールで送らないこと（サインイン後にコンソールから取得）。それまでの間は送信しません。
- \* TrialBox ホストのディスク暗号化の確認、鍵の保護、出力ファイルの暗号化（バックアップは病院のみが持つ鍵で暗号化済み）

次の 2 点は後日の構築ではなく**範囲を狭めます**。主治医の閲覧は運用開始時は無効とし、有効にする場合も記録と研究名のみを表示し、表現型や適格性の層は表示しません。個人別検査基準値層とギャップ規則層は最初のリリースに含めません。

\* 患者に関するモデル呼び出しの入力と出力は、既定では**保存しません**（既定値は現在変更中です）。保存するデバッグ設定は最長 24 時間で、監査記録が残ります。

本書および補足は、提出した変更申請を超えて患者データの利用を広げるものではありません。

［日付］

## C. 繁體中文（需母語人士審閱）

**主旨：TrialBox 計畫修正案［修正案編號］：建置中之管控措施與承諾登錄表**

［醫院名稱］［委員會名稱］ 鈞鑒，並致本院資訊室與個資保護單位

本計畫於 2026 年 11 月 10 日提出之修正案及院內資訊安全文件，所描述者為 TrialBox 開始使用病人資料時之狀態。其中部分管控措施仍在建置中。謹於委員會審查前先行告知，以使核准之文字與系統內容一致。

1. **下列標示 \* 之管控措施仍在建置中。** 每一項均於本院執行之作業驗證（OQ）中驗證，**於使用任何病人資料之前**完成。若某功能於上線時尚未就緒，該功能維持關閉，並以書面告知委員會。
2. **檢附承諾登錄表。** 表中列出修正案、資訊安全文件及退出公告中之每一項承諾，並註明保障該承諾之程式與測試，或完成該項之工作，或更正內容。登錄表由系統自動核對，若有承諾未列入，建置即停止。
3. **另檢附致委員會之簡短補充說明。** 內容為五項文字更正，以及系統管理者緊急存取（break-glass）之增補。

建置中之管控措施（\*）：

- \* 於建立索引前遮蔽病歷文字中之姓名、證號及電話
- \* 病人概況、第二模型核對及醫師註記（驗證前維持關閉）
- \* 「相似病人」頁面（驗證前維持關閉）
- \* 與系統管理者分離之資料管理人角色
- \* 系統管理者於例行工作中不接觸病人資料；僅能經緊急存取取得（理由、一位病人或一項作業、60 分鐘、留存稽核紀錄、由資料管理人審查）
- \* 退出病人已儲存之向量與概況之刪除（篩選、名單及匯出自登錄退出時即已排除）
- \* 每次檢視均記錄理由，稽核鏈每日簽署並將副本存放於本院共享儲存（雜湊鏈稽核紀錄及其存放於共享儲存已完成）
- \* 揭露病歷號及匯出前重新輸入密碼（雙因子登入已完成）
- \* 含病歷號之檔案不以電子郵件寄送，改於登入後自主控台下載；在此之前不寄送此類檔案
- \* TrialBox 主機之磁碟加密檢查、金鑰保護及輸出檔加密（備份已以僅本院持有之金鑰加密）

以下兩項為**縮小範圍**，而非日後建置：主治醫師檢視功能於上線時關閉，日後開啟時僅顯示病歷紀錄及研究名稱，不顯示表現型或研究資格層；個人化檢驗基準值層與缺口規則層不納入首次發行。

\* 與病人相關之模型呼叫之輸入與輸出，預設**不儲存**（預設值正在變更中）。儲存用之除錯開關最長 24 小時，並留存稽核紀錄。

本函及補充說明均未將病人資料之使用範圍擴大至已提出之修正案以外。

［日期］
