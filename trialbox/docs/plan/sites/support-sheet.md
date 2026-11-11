# TrialBox support sheet (サポート案内 / 支援說明)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-08 |
| Version | 0.1 (2026-11-11, T-635, D-390) |
| Owner | Aimedics |
| For | the site administrator and the trial office of each hospital: one page by the box |
| Status | Draft. The names, mail addresses and phone numbers are written on the site's printed copy at IQ, never in this repository (TB-PLAN-06 §10.4 Q-21). |
| Source | RUNBOOK §21 (support model and the supervised remote session), §23 (lost-box list); the incident plan is T-318 |
| Languages | English first; 日本語 in §B for the Japan head hospital; 繁體中文 in §C for CGMH. The three parts say the same. |

Items marked *(default)* hold until the owner answers TB-DR-09 Q2 (remote session) and Q6 (names): they are the
recommended answers of the operations review, not the owner's.

## A. English

### A.1 Who to contact

| Tier | Who | Contact |
| --- | --- | --- |
| 1 | your site administrator | name: ______ extension: ______ |
| 2 | Aimedics support, your country *(default: the Aimedics owner of record; backup not named yet)* | name: ______ backup: ______ mail: ______ phone: ______ |
| 3 | Aimedics engineering | through tier 2 |

Hours *(default)*: Japan 08:30 to 19:00 JST, CGMH 07:30 to 18:00 TST, working days. Outside them the ticket is read
the next working morning; the box keeps running on its own.

### A.2 How fast

| Priority | Example | First answer | Fix or work-around |
| --- | --- | --- | --- |
| P1 | console down for everyone; no morning mail at all; backup red over a day; the box lost | 1 working hour | next working day |
| P2 | one run type fails; notes not judged (GPU); certificate ends within 7 days | 4 working hours | 3 working days |
| P3 | a question; one user cannot sign in | 1 working day | the next release |

A suspected privacy problem (a list to a wrong person, a lost box) also goes to the hospital's incident procedure at
once, whatever its priority.

### A.3 What to send, and what never to send

Send: the site, the priority, what you saw and when, the job id, and the output of `ops status` and `doctor`.
**Never send** a patient list, a chart number, a screenshot of a patient page, an export, the pid map or a key.

### A.4 A supervised remote session *(default)*

Aimedics has no standing remote access. If needed, **the hospital** starts a screen share with its own tool, for one
ticket. The hospital's person types; Aimedics only watches and speaks. Only the terminal, the Operations, Jobs and
health pages and logs are shown; never a patient page. No recording, no file transfer. The hospital person writes in
the ticket: ticket number, start and end time, who was there, what was done. The hospital person ends the session.

### A.5 If the box is lost or stolen

Tell tier 2 and the hospital's incident contact at once. Hospital IT starts the lost-box list (RUNBOOK §23): the
directory bind account, the sign-in client secret, the mail passwords, the REDCap tokens, the backup share account,
the certificate.

## B. 日本語（国内基幹病院）

### B.1 連絡先

| 段階 | 担当 | 連絡先 |
| --- | --- | --- |
| 1 | 院内のシステム管理者 | 氏名：______ 内線：______ |
| 2 | Aimedics サポート（日本） *(既定：Aimedics の責任者。代理は未定)* | 氏名：______ 代理：______ メール：______ 電話：______ |
| 3 | Aimedics 開発 | 段階 2 を通して |

受付時間 *(既定)*：平日 08:30〜19:00（日本時間）。時間外のチケットは翌営業日の朝に確認します。装置は無人で動き続けます。

### B.2 対応の速さ

| 優先度 | 例 | 初回回答 | 復旧または回避 |
| --- | --- | --- | --- |
| P1 | 全員がコンソールを使えない／朝のメールが誰にも届かない／バックアップが1日以上赤／装置の紛失 | 1 営業時間 | 翌営業日 |
| P2 | 一部の実行が失敗／ノート判定が止まる（GPU）／証明書の期限まで7日以内 | 4 営業時間 | 3 営業日 |
| P3 | 質問／一人だけサインインできない | 1 営業日 | 次のリリース |

個人情報の漏えいが疑われるとき（誤送信、装置の紛失など）は、優先度にかかわらず、直ちに病院のインシデント手順にも従ってください。

### B.3 送るもの・送ってはいけないもの

送るもの：施設名、優先度、見た内容と時刻、ジョブID、`ops status` と `doctor` の出力。
**送ってはいけないもの**：患者一覧、カルテ番号、患者画面のスクリーンショット、エクスポート、pid map、鍵。

### B.4 立会いのもとでのリモート対応 *(既定)*

Aimedics は常設のリモートアクセスを持ちません。必要なときは**病院側が**、病院の承認済みツールで、チケット1件に限り画面共有を始めます。操作は病院の担当者が行い、Aimedics は見て指示するだけです。表示するのは端末、運用・ジョブ・ヘルス画面とログのみで、患者画面は表示しません。録画とファイル転送はしません。病院の担当者がチケットにチケット番号、開始・終了時刻、参加者、実施内容を記録し、共有を終了します。

### B.5 装置の紛失・盗難

段階 2 と病院のインシデント窓口へ直ちに連絡してください。病院の情報システム部門が紛失時リスト（RUNBOOK §23）に沿って、ディレクトリ接続用アカウント、サインインのクライアントシークレット、メールのパスワード、REDCap トークン、バックアップ共有のアカウント、証明書を無効にします。

## C. 繁體中文（長庚紀念醫院 CGMH）

### C.1 聯絡窗口

| 層級 | 負責人 | 聯絡方式 |
| --- | --- | --- |
| 1 | 院內系統管理者 | 姓名：______ 分機：______ |
| 2 | Aimedics 支援（台灣） *(預設：Aimedics 負責人；代理人尚未指定)* | 姓名：______ 代理人：______ 電子郵件：______ 電話：______ |
| 3 | Aimedics 工程團隊 | 經由第 2 層 |

服務時間 *(預設)*：工作日 07:30 至 18:00（台灣時間）。非服務時間的工單於下一個工作日早上處理；系統會自行持續運作。

### C.2 回應時間

| 優先級 | 例子 | 首次回應 | 修復或替代方案 |
| --- | --- | --- | --- |
| P1 | 所有人都無法使用主控台／早晨郵件無人收到／備份紅燈超過一天／設備遺失 | 1 個工作小時 | 下一個工作日 |
| P2 | 某類執行失敗／病歷判讀停止（GPU）／憑證於 7 天內到期 | 4 個工作小時 | 3 個工作日 |
| P3 | 問題諮詢／單一使用者無法登入 | 1 個工作日 | 下一個版本 |

疑似個資外洩（寄錯名單、設備遺失等）時，不論優先級，請同時立即依醫院的資安事件程序處理。

### C.3 請提供與請勿提供

請提供：院區、優先級、看到的狀況與時間、工作編號、`ops status` 與 `doctor` 的輸出。
**請勿提供**：病人名單、病歷號、病人頁面截圖、匯出檔、pid map、金鑰。

### C.4 在院方監督下的遠端協助 *(預設)*

Aimedics 沒有常設的遠端存取。需要時由**院方**使用院方核准的工具、針對單一工單發起螢幕分享。由院方人員操作鍵盤，Aimedics 只觀看並口頭說明。只顯示終端機、營運、工作與健康狀態頁面及日誌，不顯示任何病人頁面。不錄影、不傳檔。院方人員於工單記錄工單編號、開始與結束時間、參與者及處理內容，並由院方結束分享。

### C.5 設備遺失或遭竊

請立即通知第 2 層與醫院的資安事件窗口。資訊室依遺失清單（RUNBOOK §23）停用目錄連線帳號、登入用用戶端密鑰、郵件密碼、REDCap 權杖、備份共用資料夾帳號與憑證。
