# Operations tabletop record: CGMH (營運桌上演練紀錄：長庚紀念醫院)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-10 |
| Version | 0.1 (2026-11-11, T-635, D-390): the empty template |
| For | the site administrator, hospital IT (資訊室) and Aimedics tier 2, once before go-live and then yearly |
| How it is used | Copy this file for each run and fill it on paper or in the hospital's own system. **A filled copy stays with the hospital**: it names people, so it is never committed to this repository (TB-PLAN-06 §10.4 Q-21). Only the outcome line of §4 (date, scenarios run, gaps found, no names) may be reported back to Aimedics. |
| Source | RUNBOOK §21 to §25 and the parts of §4, §12 and §22 written by T-635, and §20 (T-628, scenario 12); each scenario names its drill in T-213b |
| Form | TrialBox runs in containers on CGMH's shared B200 server (RUNBOOK §17). The hospital runs the platform, so scenarios 3, 4, 10 and 11 are mostly the hospital's own procedure; the tabletop checks the hand-over points with TrialBox. |
| Not covered | the incident plan's tabletop (severity, notification clocks, the six cases) is T-318's |

## 1. The run (演練概要)

| Item / 項目 | Value / 填寫 |
| --- | --- |
| Date and time (TST) / 日期時間 | YYYY-MM-DD hh:mm to hh:mm |
| Place or call / 地點或會議方式 | |
| Facilitator (role) / 主持人（角色） | |
| Hospital roles present / 院方出席者（角色） | site administrator ☐ hospital IT ☐ platform team ☐ key steward ☐ backup-key holder ☐ trial office ☐ |
| Aimedics roles present / Aimedics 出席者（角色） | tier 2 ☐ tier 3 ☐ |
| Release installed / 已安裝版本 | |

## 2. Scenarios (情境)

For each scenario the facilitator reads the inject, the team says what it does, step by step, from the RUNBOOK page
alone. Write the time each step would take and every gap (a step missing from the page, a person or item not
available, a target that cannot hold). 每個情境由主持人宣讀狀況，參與者僅依 RUNBOOK 頁面逐步說明處理方式，並記錄所需時間與缺漏。

| # | Scenario / 情境 | Inject / 狀況 | RUNBOOK | Drill (T-213b) | Time said / 預估時間 | Target / 目標 | Gaps / 缺漏 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Storage volume lost / 儲存磁區遺失 | 10:00: the platform team reports the TrialBox volumes were deleted by mistake / 10:00 平台團隊回報 TrialBox 的磁區被誤刪 | §23, §22 | `test_runbook_23_lost_box` | | lost-box list judged (which rows apply) within 1 hour | |
| 2 | Restore on the same platform / 在同一平台還原 | the database volume is corrupt / 資料庫磁區損毀 | §22 | none (not rehearsed by a test) | | RTO 4 hours (target, not measured) | |
| 3 | GPU partition gone / GPU 分割區失效 | the MIG instance is not seen after platform work / 平台維護後看不到 MIG 執行個體 | §4 GPU fault, §22 replacing hardware | none (not rehearsed by a test) | | the platform team restores the partition or gives one on another card; canary passes | |
| 4 | Planned power or platform outage / 計畫性停電或平台停機 | platform maintenance Saturday 08:00 to 17:00 / 週六 08:00 至 17:00 平台維護 | §22 planned power cut | none (not rehearsed by a test) | | no data lost; morning mail on Monday | |
| 5 | No morning mail / 早晨郵件未送達 | 07:45: no coordinator got the mail / 07:45 所有研究協調員都沒收到郵件 | §4 morning mail | none (not rehearsed by a test) | | cause found and notices sent by 10:00 | |
| 6 | Volume full / 磁區已滿 | `backup-status` red; the data volume at 97 % / `backup-status` 紅燈，資料磁區 97 % | §4 disk full | none (not rehearsed by a test) | | space freed safely the same day | |
| 7 | Supervised remote session / 院方監督的遠端協助 | tier 2 must see `doctor` output to fix a P2 / 處理 P2 時需要看 `doctor` 的輸出 | §21 | none (not rehearsed by a test) | | session by the rules; recorded in the ticket *(default, TB-DR-09 Q2)* | |
| 8 | Key steward leaves / 金鑰保管人離職 | a steward holding a KEK share leaves on Friday / 持有 KEK 分持金鑰的保管人週五離職 | §25 | `test_runbook_25_leaver` | | KEK rotated before the leaving day | |
| 9 | Certificate ends / 憑證到期 | `check-tls` warns: 20 days left / `check-tls` 警告剩 20 天 | §12 certificate renewal | `test_runbook_12_certificate_renewal` | | new certificate in before the end | |
| 10 | Platform patch / 平台修補 | the platform team plans a node upgrade / 平台團隊預定升級節點 | §24, §17 | none (not rehearsed by a test) | | `doctor --platform` and the canary pass after | |
| 11 | New address / 位址變更 | the console's host name changes / 主控台主機名稱變更 | §22 moving the box | `test_runbook_22_moving_the_box` | | console answers on the new name | |
| 12 | Study close-out and volumes retired / 試驗結案與磁區除役 | the last study closes on the 30th; the platform team will reclaim the volumes / 最後一個試驗於 30 日結案，平台團隊將回收磁區 | §20 | `test_runbook_20_decommission` | | archive verified and handed to the trial office before any purge; certificate from the platform team | |

## 3. Gaps and actions (缺漏與改善)

| # | Gap / 缺漏 | Page to change or item to get / 需修改的頁面或準備事項 | Who (role) / 負責（角色） | By / 期限 |
| --- | --- | --- | --- | --- |
| | | | | |

## 4. Outcome (結果)

One line that may be sent to Aimedics, with no names / 可送交 Aimedics 的一行摘要（不含姓名）：

`CGMH, YYYY-MM-DD: scenarios run __ of 12; gaps __; actions open __.`
