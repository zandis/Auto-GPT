# Close-out and decommissioning record (終了・廃棄記録 / 結案與除役紀錄)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-11 |
| Version | 0.1 (2026-11-11, T-628, D-413): the empty template |
| For | the site administrator, hospital IT and the trial office, when a study closes or the box is retired |
| How it is used | Copy this file for each close-out and fill it on paper or in the hospital's own system, step by step, along RUNBOOK §20. **A filled copy stays with the hospital**, kept with the archive by the trial office: it names people, so it is never committed to this repository. Only the outcome line of §5 (date, site, counts, no names) may be reported back to Aimedics. |
| Source | RUNBOOK §20; the store list is the output of `python3 -m tools.trialbox decommission-plan`; the certificates are TB-SITE-12 (`purge-certificate.md`) |
| Not here | signing this procedure by each trial office before go-live was the card's acceptance and is dropped (D-311); the site uses it when the time comes |

## 1. What closes (終了の対象 / 結案範圍)

| Item / 項目 | Value / 記入 / 填寫 |
| --- | --- |
| Site / 施設 / 院所 | ☐ Japan (appliance) ☐ CGMH (shared B200 server) ☐ other: |
| Close-out kind / 種類 / 類型 | ☐ one study (steps 1 to 5) ☐ the whole box (steps 1 to 8) |
| Studies closed / 終了する試験 / 結案的試驗 | |
| Close date / 終了日 / 結案日 | YYYY-MM-DD |
| Release installed / 版本 | |
| Decommissioning plan attached / 計画の添付 / 附除役計畫 | ☐ `decommission-plan --json` printed and every **ask** row answered |

## 2. The steps (手順 / 步驟)

| Step | What / 内容 / 內容 | Done (date, role) / 実施 / 完成 | Value to keep / 記録 / 紀錄 |
| --- | --- | --- | --- |
| 1 announce | close date told; study accounts disabled on the close date | | accounts disabled: __ |
| 2 freeze | services stopped; `audit_verify` whole; head signed off the box; `--heads` passes | | head sequence and hash: |
| 3 archive | final backup, audit, audit archive, export ledger, plan in one folder; `SHA256SUMS` written | | sha256 of `SHA256SUMS`: |
| 4 verify | `sha256sum -c`, `backup-verify`, `audit_verify --heads` pass on the hospital's store; a second copy made | | where the two copies are: |
| 5 handover | the trial office has the archive, this record and the backup private key envelope | | kept until (date): |
| 6 crypto-erase | KEK shares, TPM or KMS key, disk keys, other copies of the backup private key destroyed | | |
| 7 purge | every **purge** row of the plan done, host disks last | | rows: __ of __ |
| 8 certificate | one certificate (TB-SITE-12) per medium or shared store | | certificates: __ |

## 3. Stores (保存先 / 儲存位置)

Copy the stores of the plan here, one row each. A **keep** row is a record the hospital keeps; a **purge** row has a
certificate number.

| Plan row / 計画の行 / 計畫列 | Where / 場所 / 位置 | keep or purge | Certificate no. / 証明書番号 / 證明書編號 |
| --- | --- | --- | --- |
| | | | |

## 4. Gaps (不備 / 缺漏)

| Gap / 不備 / 缺漏 | Action / 対応 / 處理 | Who (role) / 担当 / 負責 |
| --- | --- | --- |
| | | |

## 5. Outcome (結果)

One line that may be sent to Aimedics, with no names / 氏名を含まない一行 / 可送交 Aimedics 的一行摘要（不含姓名）：

`SITE, YYYY-MM-DD: close-out kind __; archive verified yes/no; stores purged __ of __; certificates __.`
