# Operations tabletop record: Japan head hospital (運用机上訓練記録：国内基幹病院)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-09 |
| Version | 0.1 (2026-11-11, T-635, D-390): the empty template |
| For | the site administrator, hospital IT (医療情報部) and Aimedics tier 2, once before go-live and then yearly |
| How it is used | Copy this file for each run and fill it on paper or in the hospital's own system. **A filled copy stays with the hospital**: it names people, so it is never committed to this repository (TB-PLAN-06 §10.4 Q-21). Only the outcome line of §4 (date, scenarios run, gaps found, no names) may be reported back to Aimedics. |
| Source | RUNBOOK §21 to §25 and the parts of §4, §12 and §22 written by T-635, and §20 (T-628, scenario 12); each scenario names its drill in T-213b |
| Not covered | the incident plan's tabletop (severity, notification clocks, the six cases) is T-318's |

## 1. The run (実施概要)

| Item / 項目 | Value / 記入 |
| --- | --- |
| Date and time (JST) / 実施日時 | YYYY-MM-DD hh:mm to hh:mm |
| Place or call / 場所・会議方法 | |
| Facilitator (role) / 進行役（役割） | |
| Hospital roles present / 病院側の出席者（役割） | site administrator ☐ hospital IT ☐ key steward ☐ backup-key holder ☐ trial office ☐ |
| Aimedics roles present / Aimedics 側の出席者（役割） | tier 2 ☐ tier 3 ☐ |
| Box form / 装置の形態 | one-box workstation ☐ DGX Spark ☐ two devices ☐ |
| Release installed / 導入済みリリース | |

## 2. Scenarios (シナリオ)

For each scenario the facilitator reads the inject, the team says what it does, step by step, from the RUNBOOK page
alone. Write the time each step would take and every gap (a step missing from the page, a person or item not
available, a target that cannot hold). 各シナリオについて、進行役が状況を読み上げ、参加者は RUNBOOK のページだけを見て手順を述べます。所要時間と不足点を記入します。

| # | Scenario / シナリオ | Inject / 状況 | RUNBOOK | Drill (T-213b) | Time said / 想定時間 | Target / 目標 | Gaps / 不足点 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Box stolen / 装置の盗難 | 10:00: the box is gone from the server room / 10:00 サーバ室から装置がなくなっている | §23, §22 replacing hardware | `test_runbook_23_lost_box` | | lost-box list started within 1 hour; each row within its time | |
| 2 | Restore on the same hardware / 同一機器での復元 | the database disk failed overnight; the disk is replaced / 夜間にデータベースのディスクが故障し交換済み | §22 | none (not rehearsed by a test) | | RTO 4 hours (target, not measured) | |
| 3 | GPU dead / GPU の故障 | `nvidia-smi` sees no card after a reboot / 再起動後に `nvidia-smi` がカードを認識しない | §4 GPU fault, §22 replacing hardware | none (not rehearsed by a test) | | 5 working days with a loaner *(default, TB-DR-09 Q5)* | |
| 4 | Legal electrical inspection / 法定点検による停電 | power off Saturday 08:00 to 17:00 / 土曜 08:00〜17:00 停電 | §22 planned power cut | none (not rehearsed by a test) | | no data lost; morning mail on Monday | |
| 5 | No morning mail / 朝のメールが届かない | 07:45: no coordinator got the mail / 07:45 どの CRC にもメールが届いていない | §4 morning mail | none (not rehearsed by a test) | | cause found and notices sent by 10:00 | |
| 6 | Disk full / ディスク容量不足 | `backup-status` red; the data disk at 97 % / `backup-status` が赤、データディスク 97 % | §4 disk full | none (not rehearsed by a test) | | space freed safely the same day | |
| 7 | Supervised remote session / 立会いのもとでのリモート対応 | tier 2 must see `doctor` output to fix a P2 / P2 の対応で `doctor` の出力を見る必要がある | §21 | `test_runbook_21_support_session` | | session by the rules; recorded in the ticket *(default, TB-DR-09 Q2)* | |
| 8 | Key steward leaves / 鍵管理者の退職 | a steward holding a KEK share leaves on Friday / KEK の分割鍵を持つ管理者が金曜に退職 | §25 | `test_runbook_25_leaver` | | KEK rotated before the leaving day | |
| 9 | Certificate ends / 証明書の期限切れ | `check-tls` warns: 20 days left / `check-tls` が残り 20 日を警告 | §12 certificate renewal | `test_runbook_12_certificate_renewal` | | new certificate in before the end | |
| 10 | Patch window / パッチ適用 | hospital IT plans the monthly OS window / 病院が月例の OS 更新を予定 | §24 | none (not rehearsed by a test) | | `doctor` and the canary pass after | |
| 11 | Moving the box / 装置の移設 | the server room moves to another building / サーバ室が別棟へ移転 | §22 moving the box | `test_runbook_22_moving_the_box` | | console answers on the new address | |
| 12 | Study close-out and the box retired / 試験終了と装置の廃棄 | the last study closes on the 30th; the box is returned / 最後の試験が 30 日に終了し、装置を返却 | §20 | `test_runbook_20_decommission` | | archive verified and handed to the trial office before any purge; one certificate per disk | |

## 3. Gaps and actions (不足点と対応)

| # | Gap / 不足点 | Page to change or item to get / 修正するページ・準備するもの | Who (role) / 担当（役割） | By / 期限 |
| --- | --- | --- | --- | --- |
| | | | | |

## 4. Outcome (結果)

One line that may be sent to Aimedics, with no names / Aimedics に送ってよい一行（氏名なし）：

`Japan head hospital, YYYY-MM-DD: scenarios run __ of 12; gaps __; actions open __.`
