# Media sanitization certificate (データ消去証明書 / 資料清除證明書)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-12 |
| Version | 0.1 (2026-11-11, T-628, D-413): the empty template |
| For | the person who sanitizes one medium or one shared store of a TrialBox site, at step 8 of RUNBOOK §20 |
| How it is used | One copy per medium (a box disk, a USB disk, a stick) or per shared store (a NAS share, the pgBackRest repository, the platform volumes). **A filled copy stays with the hospital**, with the close-out record (TB-SITE-11): it names people and serial numbers, so it is never committed to this repository. Only the outcome line of the close-out record goes back to Aimedics. |
| Source | NIST SP 800-88 Rev. 1, *Guidelines for Media Sanitization*, Appendix G (the sample certificate): the same fields, in the same order. The categories Clear, Purge and Destroy are those of its §2.5; a site that follows Rev. 2 (2025) uses the same three. |
| Languages | A. English, B. 日本語, C. 繁體中文: the same fields. Fill the one the hospital uses; the field numbers are the same in all three. |

## A. English

### A.1 Person performing sanitization

| # | Field | Value |
| --- | --- | --- |
| 1 | Name | |
| 2 | Title or role | |
| 3 | Organization | |
| 4 | Location | |
| 5 | Phone | |

### A.2 Media information

| # | Field | Value |
| --- | --- | --- |
| 6 | Make or vendor | |
| 7 | Model | |
| 8 | Serial number | |
| 9 | Media property number (asset tag) | |
| 10 | Media type | ☐ NVMe SSD ☐ SATA SSD ☐ hard disk ☐ USB flash ☐ shared store (folder) ☐ platform volume ☐ paper ☐ other: |
| 11 | Source (the store on the decommissioning plan) | the plan row, e.g. `volume db-pg`, `backup target`, `host disks` |
| 12 | Data class held | ☐ D3 pseudonymised ☐ D4 identified ☐ keys ☐ D0 to D2 only |
| 13 | Data backed up | ☐ yes: in the close-out archive ☐ no ☐ unknown |
| 14 | Backup location | the close-out archive and its `SHA256SUMS` sum |

### A.3 Sanitization details

| # | Field | Value |
| --- | --- | --- |
| 15 | Method type | ☐ Clear ☐ Purge ☐ Destroy |
| 16 | Method used | ☐ crypto erase ☐ block erase ☐ overwrite ☐ degauss ☐ shred or disintegrate ☐ delete (logical, after crypto-erase) ☐ other: |
| 17 | Method details | e.g. `nvme sanitize -a 4`; the keys destroyed at step 6 |
| 18 | Tool used, with version | |
| 19 | Verification method | ☐ full ☐ quick sampling ☐ the device's sanitize log ☐ the destroyer's or platform's record ☐ other: |
| 20 | Post-sanitization data class | ☐ none (D0) ☐ other: |
| 21 | Notes | |

### A.4 Media destination

| # | Field | Value |
| --- | --- | --- |
| 22 | Destination | ☐ reused inside the hospital ☐ reused outside ☐ returned to the vendor ☐ recycling ☐ destroyed ☐ other: |

### A.5 Signature

| # | Field | Value |
| --- | --- | --- |
| 23 | I attest that the sanitization above was done as described. Name, title, date, signature | |

### A.6 Validation (optional, where the hospital asks for a second person)

| # | Field | Value |
| --- | --- | --- |
| 24 | Name, title, organization, phone, date, signature | |

## B. 日本語

### B.1 消去作業者

| # | 項目 | 記入 |
| --- | --- | --- |
| 1 | 氏名 | |
| 2 | 役職または役割 | |
| 3 | 所属 | |
| 4 | 場所 | |
| 5 | 電話番号 | |

### B.2 媒体情報

| # | 項目 | 記入 |
| --- | --- | --- |
| 6 | メーカーまたは販売元 | |
| 7 | 型番 | |
| 8 | シリアル番号 | |
| 9 | 資産管理番号 | |
| 10 | 媒体の種類 | ☐ NVMe SSD ☐ SATA SSD ☐ ハードディスク ☐ USB フラッシュ ☐ 共有ストレージ（フォルダ） ☐ プラットフォームのボリューム ☐ 紙 ☐ その他： |
| 11 | 出所（廃棄計画の保存先） | 計画の行、例：`volume db-pg`、`backup target`、`host disks` |
| 12 | 保存していたデータ区分 | ☐ D3 仮名化 ☐ D4 識別可能 ☐ 鍵 ☐ D0〜D2 のみ |
| 13 | バックアップの有無 | ☐ あり：終了時アーカイブ内 ☐ なし ☐ 不明 |
| 14 | バックアップの場所 | 終了時アーカイブと `SHA256SUMS` のハッシュ値 |

### B.3 消去の詳細

| # | 項目 | 記入 |
| --- | --- | --- |
| 15 | 方式の区分 | ☐ Clear（消去） ☐ Purge（完全消去） ☐ Destroy（破壊） |
| 16 | 使用した方式 | ☐ 暗号消去 ☐ ブロック消去 ☐ 上書き ☐ 消磁 ☐ 粉砕・裁断 ☐ 論理削除（暗号消去の後） ☐ その他： |
| 17 | 方式の詳細 | 例：`nvme sanitize -a 4`、手順 6 で破棄した鍵 |
| 18 | 使用ツールとバージョン | |
| 19 | 検証方法 | ☐ 全数 ☐ 抜き取り ☐ 装置の消去ログ ☐ 破壊業者またはプラットフォームの記録 ☐ その他： |
| 20 | 消去後のデータ区分 | ☐ なし（D0） ☐ その他： |
| 21 | 備考 | |

### B.4 媒体の行き先

| # | 項目 | 記入 |
| --- | --- | --- |
| 22 | 行き先 | ☐ 院内で再利用 ☐ 院外で再利用 ☐ 販売元へ返却 ☐ リサイクル ☐ 破壊済み ☐ その他： |

### B.5 署名

| # | 項目 | 記入 |
| --- | --- | --- |
| 23 | 上記のとおり消去したことを証明します。氏名、役職、日付、署名 | |

### B.6 確認（任意。病院が二人目の確認を求める場合）

| # | 項目 | 記入 |
| --- | --- | --- |
| 24 | 氏名、役職、所属、電話番号、日付、署名 | |

## C. 繁體中文

### C.1 執行清除人員

| # | 欄位 | 填寫 |
| --- | --- | --- |
| 1 | 姓名 | |
| 2 | 職稱或角色 | |
| 3 | 單位 | |
| 4 | 地點 | |
| 5 | 電話 | |

### C.2 媒體資訊

| # | 欄位 | 填寫 |
| --- | --- | --- |
| 6 | 廠牌或供應商 | |
| 7 | 型號 | |
| 8 | 序號 | |
| 9 | 財產編號 | |
| 10 | 媒體類型 | ☐ NVMe SSD ☐ SATA SSD ☐ 硬碟 ☐ USB 隨身碟 ☐ 共用儲存（資料夾） ☐ 平台磁區 ☐ 紙本 ☐ 其他： |
| 11 | 來源（除役計畫中的儲存位置） | 計畫中的列，例如 `volume db-pg`、`backup target`、`host disks` |
| 12 | 存放的資料等級 | ☐ D3 假名化 ☐ D4 可識別 ☐ 金鑰 ☐ 僅 D0 至 D2 |
| 13 | 是否已備份 | ☐ 是：在結案封存內 ☐ 否 ☐ 不明 |
| 14 | 備份位置 | 結案封存及其 `SHA256SUMS` 雜湊值 |

### C.3 清除細節

| # | 欄位 | 填寫 |
| --- | --- | --- |
| 15 | 方法類別 | ☐ Clear（清除） ☐ Purge（徹底清除） ☐ Destroy（銷毀） |
| 16 | 使用的方法 | ☐ 加密抹除 ☐ 區塊抹除 ☐ 覆寫 ☐ 消磁 ☐ 粉碎或碎解 ☐ 邏輯刪除（加密抹除之後） ☐ 其他： |
| 17 | 方法細節 | 例如 `nvme sanitize -a 4`；步驟 6 已銷毀的金鑰 |
| 18 | 使用工具及版本 | |
| 19 | 驗證方法 | ☐ 全部 ☐ 抽樣 ☐ 裝置的清除紀錄 ☐ 銷毀業者或平台的紀錄 ☐ 其他： |
| 20 | 清除後的資料等級 | ☐ 無（D0） ☐ 其他： |
| 21 | 備註 | |

### C.4 媒體去向

| # | 欄位 | 填寫 |
| --- | --- | --- |
| 22 | 去向 | ☐ 院內再利用 ☐ 院外再利用 ☐ 退回供應商 ☐ 回收 ☐ 已銷毀 ☐ 其他： |

### C.5 簽名

| # | 欄位 | 填寫 |
| --- | --- | --- |
| 23 | 茲證明已依上述方式完成清除。姓名、職稱、日期、簽名 | |

### C.6 覆核（選填，院方要求第二人覆核時）

| # | 欄位 | 填寫 |
| --- | --- | --- |
| 24 | 姓名、職稱、單位、電話、日期、簽名 | |
