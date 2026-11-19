# Incident plan (インシデント対応計画 / 事件應變計畫)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-11 |
| Version | 0.1 (2026-11-11, T-318, D-411): the draft for both sites |
| Owner | Aimedics (the plan); each hospital (its own incident procedure, which this plan feeds) |
| For | the hospital's incident lead, privacy office, site administrator and data steward; Aimedics tier 2 and engineering |
| Status | Draft. The clocks of §A.3 are the plan's reading (TB-PLAN-05 §9.3) and are marked *counsel confirms*: no counsel reading is on file (D-311 B26). Names, phone numbers and mail addresses are written on the hospital's printed copy, never in this repository (TB-PLAN-06 §10.4 Q-21). |
| Source | OPS-041 (`docs/reviews/2026-11-10-deep-review/09-operations.md`); TB-PLAN-05 §9.3 and WS-13.5; RUNBOOK §7, §21, §23; the data-handling rule (`docs/plan/sites/data-handling-rule.md`, rule 7) |
| Languages | English first (§A, the full plan); 日本語 in §B for the Japan head hospital; 繁體中文 in §C for CGMH. §B and §C carry the severity scale, the roles, the clocks, the six cases and the notice templates; the procedures in §A.5 to §A.8 are in English only for now. |
| Tested by | `tests/unit/test_privacy_docs.py` (the six cases, the four severities and the clock rows are in all three languages) |

Who decides. **The hospital is the controller** (個人情報取扱事業者 / 公務・非公務機關): it decides whether an event is a
breach, whom it notifies and when. **Aimedics is the processor** (委託先 / 受託者): it tells the hospital, gives the
evidence the box holds, and helps contain and recover. Aimedics never notifies a regulator, a patient or the press
for the hospital. Only the hospital's incident lead lowers a severity.

## A. English

### A.1 Severity scale

Rate at the first look and again whenever a fact changes. When unsure, take the higher rating.

| Severity | Meaning | Examples | Aimedics tells the hospital (C1) | Legal clocks |
| --- | --- | --- | --- | --- |
| S1 critical | patient data (class D3 or D4) has left, or may have left, the hospital's control; or someone without a right controls an administrator, steward or host account | a patient list mailed outside the internal domains; a box or disk lost while its keys may be readable; an attacker on the host | within 1 hour of knowing | all clocks of §A.3 that apply start at the hospital's first knowledge |
| S2 high | patient data was seen inside the hospital by a person without a need; an ordinary account is taken over; a wrong output was acted on | a candidate list sent to the wrong study team; a coordinator's password used by someone else; a summary with a wrong passage used at a visit | within 24 hours of knowing | the incident lead decides within 24 hours whether any clock of §A.3 runs |
| S3 medium | a fault with no exposure and no wrong output acted on | corruption found before a list went out; a platform event with no access to TrialBox's volumes; a model fault caught by the checks | within 24 hours of knowing | none, unless a fact raises the severity |
| S4 low | a near miss or a slip with no patient data | the data-handling scan stops a file with real-looking data; a support ticket nearly carried a screenshot | in the next working day's ticket | none |

The support priority of a ticket (RUNBOOK §21, P1 to P3) is a different scale: a suspected privacy incident is
rated here at once, whatever its ticket priority.

### A.2 Roles

| Role | Side | Does |
| --- | --- | --- |
| R1 incident lead | hospital (the privacy office or the person the hospital names; at CGMH the CISO's office under 資通安全管理法) | rates, decides on notices, owns the clocks, closes the incident |
| R2 site administrator | hospital | contains on the box (stop mail, disable accounts), runs the first-hour commands of §A.4, keeps the box running for the evidence |
| R3 data steward | hospital | judges which patients and which data classes are touched; reads the audit and the export ledger; holds the KEK share |
| R4 principal investigators | hospital | judge the effect on each study; tell the IRB and the sponsor where their rules ask |
| R5 hospital IT and the platform team | hospital | network, accounts, the shared host (CGMH), the hospital's own logs |
| R6 Aimedics incident coordinator | Aimedics (tier 2 of RUNBOOK §21; the owner of record until the owner names a person, TB-DR-09 Q6) | starts clock C1, keeps the timeline, brings engineering in, writes the processor's report |
| R7 Aimedics engineering | Aimedics (tier 3) | reads the PHI-free support bundle, finds the cause, builds and signs a fix |

One person may hold several roles at a small site. R1 is never an Aimedics person.

### A.3 Notification clocks

*Counsel confirms (CR-096): the hours below are the plan's reading; no counsel reading is on file (D-311 B26).*

| Clock | Law or rule | From, to | Deadline | Sent by | Applies |
| --- | --- | --- | --- | --- | --- |
| C1 | contract (data-processing agreement); D-411 | Aimedics to the hospital's incident lead | S1: 1 hour from Aimedics knowing; S2 and S3: 24 hours; S4: next working day | R6 | both sites, every incident |
| C2 | APPI Art. 26, PPC rules Art. 7 and 8: 速報 | the hospital to the PPC (個人情報保護委員会) | about 3 to 5 days from the hospital knowing (概ね3〜5日以内) | R1 | Japan: a leak, loss or damage of 要配慮個人情報 (any count), or by an unlawful act |
| C3 | APPI Art. 26, PPC rules Art. 8: 確報 | the hospital to the PPC | 30 days; 60 days when the leak comes from an act for an unlawful purpose | R1 | Japan: as C2 |
| C4 | APPI Art. 26(2): 本人通知 | the hospital to each person | promptly, as the situation allows | R1 | Japan: as C2 |
| C5 | MHLW 安全管理ガイドライン 7.0 | the hospital to MHLW and, for an attack, the police | promptly; the hospital's BCP sets the hour | R1 | Japan: a cyber attack on a medical information system |
| C6 | PDPA Art. 12 (and the draft rules quoted by TB-PLAN-05 §9.3) | the hospital to each person | 72 hours after the facts are established | R1 | Taiwan: personal data stolen, leaked, altered or otherwise infringed |
| C7 | 醫療機構電子病歷製作及管理辦法 | the hospital to the health authority | 72 hours | R1 | Taiwan: an incident touching the electronic medical record system or its copies |
| C8 | 資通安全管理法 and its incident rules | the hospital to the competent authority | 1 hour from knowing | R1 (the CISO's office) | Taiwan: a designated agency or critical-infrastructure provider (a medical centre) |
| C9 | IRB rules; the clinical trial agreement | the investigator to the IRB; to the sponsor | as the committee's SOP and the agreement say | R4 | both sites: when a study's data or a trial record is touched |

Clocks C2 to C9 are the hospital's. Aimedics keeps C1 and gives what each clock's report needs (§A.4, §A.8).

### A.4 What the box gives in the first hour

All of these hold no patient data and may go to Aimedics. Run them on the box as the site administrator.

| # | Step | Command or place | Gives |
| --- | --- | --- | --- |
| F1 | stop outgoing mail (when a mail may be involved) | `docker compose stop mail-gateway` | no further send; the queue stays for the evidence |
| F2 | keep the box running | do not power off, restore or reinstall before R3 agrees | the audit and the volumes as they were |
| F3 | disable an account | `python -m console.cli disable NAME` (console container) | the account cannot sign in; audited |
| F4 | the box's state | `python3 -m tools.trialbox ops status` and `trialbox doctor` | versions, services, backups, health |
| F5 | the support bundle | `sudo python3 -m tools.trialbox support-bundle --out /media/usb` (D-405) | one scrubbed, scanned archive for R7 |
| F6 | the audit chain is whole | `python tools/audit_verify.py` | counts and errors only; a broken chain is itself S2 or higher |
| F7 | what left the box | `python3 -m tools.trialbox exports` (the export ledger, D-149) | every file sent, its sha256, recipients, approval |
| F8 | who read what | the audit chain on the box, read by R3 | every view and reveal with user, time and pseudonym; stays on the box |
| F9 | which model build ran | `release.json` and the Operations page (RUNBOOK §15) | the build of every run in the window |

F8 names patients by pseudonym and stays with the hospital. Only counts and dates from it go to Aimedics.

### A.5 The six cases

| Case | What happens | Default severity | Contain (first hour) | Evidence | Recover | Clocks that may run | RUNBOOK |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IC-1 privacy breach | patient data reaches a person or place without a right: a wrong recipient, a screenshot in a ticket, real data in a repository or log | S1 when it left the hospital; S2 inside it | F1; recall or delete the copy where possible; data-handling rule 7 for a repository or log | F5, F7, F8 | remove the copy and purge its history; fix the routing or the person's rights | C1 to C4, C6, C7, C9 | §7, §21 |
| IC-2 lost or stolen box | the box, a disk, a backup with its private key, or an unencrypted copy of the secrets folder is gone | S1 | the lost-box list, every row within its hours | F4 from the last report; the backup records | restore on a new box (§22); rotate the KEK and `pid_map.key` | C1 to C5, C6 to C8 | §23, §22 |
| IC-3 compromised account | a TrialBox account is used by someone else, or a second factor is lost with its password | S1 for admin or steward; S2 for others | F3; reset the password and the second factor; end its sessions | F8 for the account's window; the hospital's sign-in logs | enrol again; check what the account revealed or exported | C1 to C4, C6, C9 | §3, §12 |
| IC-4 model misbehaviour | a model build gives wrong, unsupported or planted-instruction output that a person saw or used | S2 when acted on; S3 when caught | stop note reading (the switch of T-609; until it lands, stop the `gateway` service); keep the traces | F9; the traces (7 days in PRODUCTION) | find the runs and patients the build touched; re-run on a good build; tell each PI | C1, C9 | §11 (qualify), §15 |
| IC-5 data corruption | stored data is wrong: a bad ingest, a broken migration, a damaged volume, a torn audit line | S3; S2 when a wrong value was used | hold the nightly ingest; do not publish; keep the volume | F4, F6; the ingest report | restore from backup (§22) or re-ingest; check the recount | C1, C7 when the EMR copy is touched, C9 | §4, §22 |
| IC-6 platform incident on the shared host | at CGMH, the hospital's B200 platform has an incident: another tenant, a node compromise, a platform admin error | S3; S1 when TrialBox's volumes or secrets may be read | the platform team isolates the node; R2 stops TrialBox's pods if asked | the platform's audit log; F4, F5 | restore on the same or another node (§22); `doctor --platform` and the canary pass | C1, C7, C8 | §17, §24 |

### A.6 The course of an incident

1. **Know.** Anyone who sees a possible incident tells the site administrator (R2) or the incident lead (R1) at once.
   Aimedics staff tell R6, who starts C1.
2. **Rate.** R1 rates it with §A.1 within the first hour and writes the time of first knowledge: every clock runs
   from it.
3. **Contain.** R2 takes the first-hour steps of §A.4 for the case (§A.5).
4. **Collect.** R3 reads F8 on the box; R7 reads F5. Nothing with patient data leaves the hospital.
5. **Notify.** R1 sends the notices of §A.3 that apply, from the templates of §A.8 and the hospital's own forms.
6. **Recover.** The case's recover step; a fix from Aimedics comes as a signed update (RUNBOOK §5).
7. **Close.** R1 closes it with a short record: timeline, cause, notices sent and when, actions. The record stays at
   the hospital; only the outcome line of §A.9 goes to Aimedics.

### A.7 Disclosure policy

- **Patients and regulators** hear from the hospital, never from Aimedics.
- **Other sites.** When the cause is in TrialBox and can reach another site, Aimedics tells every other site's
  incident lead within 24 hours, without naming the first site or any patient.
- **Security reports from outside.** Anyone may report a weakness to Aimedics; Aimedics confirms within 2 working
  days, fixes by severity, and publishes nothing that would help an attack before every site has the fix. The full
  policy, with the Japan route through IPA and JPCERT/CC, is SECURITY §11 (`docs/security/11-vulnerability-disclosure.md`, D-1239).
- **After the fact.** The release notes of the fixing release say what was fixed, in plain words, with no site and no
  patient.

### A.8 Notice templates

Each template is the processor's notice to the hospital (C1) and a draft the hospital may use in its own report.
The hospital's own forms for the PPC, MHLW or the Taiwan authorities come first; the fields here map to them.

```text
Incident notice (processor to controller)
Incident id: INC-YYYYMMDD-n          Severity: S_          Case: IC-_
Site: ____________                   First known (site time): YYYY-MM-DD hh:mm
What happened: ______________________________________________
Data classes touched: D_  Records or persons (count, not names): ____
Contained by: ______________________ at hh:mm
Evidence held: F_, F_ (on the box); support bundle sha256: ________
Clocks that may run: C_ (deadline YYYY-MM-DD hh:mm)
Next step and time of the next update: ________________________
```

### A.9 Tabletop script

Once before the site reads real data, then yearly, with R1 to R6 present (roles, not names, are recorded). The
facilitator reads each inject; the team says what it does from this plan alone and writes the time each step would
take against the clock.

| # | Inject | Case | Check |
| --- | --- | --- | --- |
| T1 | 09:10: a coordinator says the morning list went to a mail address outside the hospital | IC-1 | rated S1; F1 within 15 minutes; C1 and the right legal clocks named with their deadlines |
| T2 | 18:30 Friday: the box's cabinet is found open and a data disk is missing | IC-2 | lost-box list started within the hour; key state judged; C2 or C6 to C8 deadlines written |
| T3 | a steward's account signs in at 03:00 from an unknown address | IC-3 | F3; F8 for the window; rated S1 |
| T4 | a PI reports a summary citing a passage that is not in the note | IC-4 | note reading stopped; F9; the runs of the build listed |
| T5 | the morning recount differs from yesterday's by a third | IC-5 | ingest held; F6; restore or re-ingest chosen |
| T6 | (CGMH) the platform team reports a compromised node that hosts TrialBox | IC-6 | the hand-over with the platform team; C8 named |

Outcome line (may go to Aimedics, no names): `SITE, YYYY-MM-DD: injects run __ of 6; clocks met __; gaps __.`

## B. 日本語

本計画の判断主体は病院（個人情報取扱事業者）であり、Aimedics は委託先として病院への報告、証拠の提供、封じ込めと
復旧の支援を行います。Aimedics が病院に代わって個人情報保護委員会・本人・報道機関に通知することはありません。

### B.1 重大度

| 重大度 | 意味 | 例 | Aimedics から病院へ (C1) |
| --- | --- | --- | --- |
| S1 重大 | 患者データ（D3・D4）が病院の管理外に出た、または出たおそれがある。権限のない者が管理者・データ管理者・ホストのアカウントを支配している | 院外アドレスへの候補者一覧の送信、鍵が読めるおそれのある状態での装置やディスクの紛失 | 把握から 1 時間以内 |
| S2 高 | 院内で業務上の必要のない者が患者データを見た。一般アカウントの乗っ取り。誤った出力が業務に使われた | 別の研究チームへの一覧送信、他人によるパスワード使用 | 24 時間以内 |
| S3 中 | 漏えいがなく、誤った出力も使われていない障害 | 送信前に見つかったデータ破損、モデル不具合を検査で検出 | 24 時間以内 |
| S4 低 | 患者データを含まないヒヤリハット | データ取扱いスキャンが実データ風のファイルを止めた | 翌営業日のチケット |

迷う場合は高い方に評価します。重大度を下げられるのは病院のインシデント責任者だけです。

### B.2 役割

| 役割 | 所属 | 担当 |
| --- | --- | --- |
| R1 インシデント責任者 | 病院（個人情報保護の担当部署または病院が指名する者） | 評価、通知の判断、期限の管理、終結 |
| R2 サイト管理者 | 病院 | 装置上での封じ込め、§A.4 の初動コマンドの実行、証拠保全のため装置を稼働させたままにする |
| R3 データ管理者 | 病院 | 影響を受けた患者とデータ区分の判断、監査記録と送出台帳の確認、KEK 分割鍵の保管 |
| R4 研究責任者 | 病院 | 各研究への影響の判断、倫理審査委員会と依頼者への報告 |
| R5 医療情報部 | 病院 | ネットワーク、アカウント、病院側のログ |
| R6 Aimedics インシデント調整役 | Aimedics | C1 の開始、経過記録、技術者の招集、委託先報告書の作成 |
| R7 Aimedics 技術者 | Aimedics | 患者情報を含まないサポートバンドルの解析、原因究明、署名付き修正 |

### B.3 通知期限（弁護士確認待ち）

| 期限 | 根拠 | 送り先 | 期限の長さ |
| --- | --- | --- | --- |
| C1 | 委託契約、D-411 | Aimedics → 病院のインシデント責任者 | S1 は 1 時間、S2・S3 は 24 時間、S4 は翌営業日 |
| C2 | 個人情報保護法第26条・規則第7条・第8条（速報） | 病院 → 個人情報保護委員会 | 概ね 3〜5 日以内 |
| C3 | 個人情報保護法第26条・規則第8条（確報） | 病院 → 個人情報保護委員会 | 30 日以内（不正の目的による場合は 60 日以内） |
| C4 | 個人情報保護法第26条第2項（本人通知） | 病院 → 本人 | 状況に応じて速やかに |
| C5 | 医療情報システムの安全管理に関するガイドライン第7.0版 | 病院 → 厚生労働省、攻撃の場合は警察 | 速やかに（病院の BCP が時間を定める） |
| C6 | 台湾 個人資料保護法第12条 | 病院 → 本人 | 事実確認後 72 時間（台湾の施設のみ） |
| C7 | 台湾 電子病歴管理辦法 | 病院 → 衛生主管機関 | 72 時間（台湾の施設のみ） |
| C8 | 台湾 資通安全管理法 | 病院 → 主管機関 | 1 時間（台湾の指定機関のみ） |
| C9 | 倫理審査委員会の手順書、治験契約 | 研究責任者 → 委員会、依頼者 | 委員会の手順書と契約に従う |

### B.4 六つの事例

| 事例 | 内容 | 既定の重大度 | 初動 |
| --- | --- | --- | --- |
| IC-1 個人情報の漏えい | 権限のない者・場所に患者データが届いた（誤送信、チケットへのスクリーンショット添付、リポジトリやログへの実データ混入） | 院外は S1、院内は S2 | メール送信停止 (F1)、複製の回収・削除 |
| IC-2 装置の紛失・盗難 | 装置、ディスク、秘密鍵と一緒のバックアップ、暗号化されていない秘密情報フォルダの喪失 | S1 | RUNBOOK §23 の紛失時リストを 1 時間以内に開始 |
| IC-3 アカウントの不正使用 | TrialBox のアカウントが他人に使われた、またはパスワードと二要素目を同時に失った | 管理者・データ管理者は S1、その他は S2 | アカウント無効化 (F3)、パスワードと二要素認証の再設定 |
| IC-4 モデルの異常動作 | モデルの誤った・根拠のない出力、または文書に仕込まれた指示に従った出力を担当者が見た・使った | 使われた場合は S2、検出された場合は S3 | 記録の読み取りを停止し、トレースを保全 |
| IC-5 データの破損 | 取り込みの失敗、移行の失敗、ボリュームの損傷、監査行の破損 | S3（誤った値が使われた場合は S2） | 夜間取り込みを保留し、ボリュームを保全 |
| IC-6 共用基盤のインシデント | 共用 GPU 基盤（CGMH の B200）でのインシデント | S3（ボリュームや秘密情報が読まれたおそれがあれば S1） | 基盤チームがノードを隔離 |

### B.5 通知の様式

```text
インシデント報告（委託先から病院へ）
インシデント番号: INC-YYYYMMDD-n     重大度: S_     事例: IC-_
施設名: ____________                 把握日時（現地時刻）: YYYY-MM-DD hh:mm
発生した事象: ______________________________________________
影響を受けたデータ区分: D_   件数・人数（氏名は書かない）: ____
封じ込めの措置: ______________________ hh:mm
保全した証拠: F_, F_（装置上）  サポートバンドルの sha256: ________
該当しうる期限: C_（期限 YYYY-MM-DD hh:mm）
次の対応と次回報告の時刻: ________________________
```

## C. 繁體中文

本計畫由醫院（個人資料之蒐集、處理及利用機關）決定；Aimedics 為受託者，負責通知醫院、提供證據並協助控制與復原。
Aimedics 不代替醫院通知主管機關、當事人或媒體。

### C.1 嚴重度

| 嚴重度 | 意義 | 例子 | Aimedics 通知醫院 (C1) |
| --- | --- | --- | --- |
| S1 重大 | 病人資料（D3、D4）已離開或可能離開醫院的管理；或無權限者控制了管理者、資料管理人或主機帳號 | 候選名單寄到院外信箱；主機或磁碟遺失且金鑰可能可讀 | 知悉後 1 小時內 |
| S2 高 | 院內無業務需要者看到病人資料；一般帳號遭盜用；錯誤的輸出已被使用 | 名單寄給別的研究團隊；他人使用某人的密碼 | 24 小時內 |
| S3 中 | 沒有外洩，也沒有錯誤輸出被使用的故障 | 名單送出前發現資料損毀；模型錯誤被檢查攔下 | 24 小時內 |
| S4 低 | 不含病人資料的未遂事件 | 資料處理掃描攔下看似真實資料的檔案 | 下一個工作日的工單 |

無法判斷時取較高者。只有醫院的事件負責人可以調降嚴重度。

### C.2 角色

| 角色 | 所屬 | 職責 |
| --- | --- | --- |
| R1 事件負責人 | 醫院（個資保護單位或醫院指定者；長庚為資通安全長辦公室） | 評級、決定通報、掌握時限、結案 |
| R2 站台管理者 | 醫院 | 在主機上控制事件、執行 §A.4 的第一小時指令、保持主機運作以保全證據 |
| R3 資料管理人 | 醫院 | 判斷受影響的病人與資料等級、查閱稽核紀錄與輸出帳冊、保管 KEK 分持金鑰 |
| R4 計畫主持人 | 醫院 | 判斷對各研究的影響、依規定通知 IRB 與試驗委託者 |
| R5 資訊室與平台團隊 | 醫院 | 網路、帳號、共用主機、醫院端的紀錄 |
| R6 Aimedics 事件協調人 | Aimedics | 啟動 C1、記錄時間軸、召集工程人員、撰寫受託者報告 |
| R7 Aimedics 工程人員 | Aimedics | 分析不含病人資料的支援包、找出原因、製作簽章的修正 |

### C.3 通報時限（待律師確認）

| 時限 | 依據 | 對象 | 期限 |
| --- | --- | --- | --- |
| C1 | 資料處理契約、D-411 | Aimedics → 醫院事件負責人 | S1 為 1 小時；S2、S3 為 24 小時；S4 為下一個工作日 |
| C2 | 日本個人情報保護法第26條（速報） | 醫院 → 個人情報保護委員會 | 約 3 至 5 日（僅日本站台） |
| C3 | 日本個人情報保護法第26條（確報） | 醫院 → 個人情報保護委員會 | 30 日；不正目的者 60 日（僅日本站台） |
| C4 | 日本個人情報保護法第26條第2項（通知本人） | 醫院 → 本人 | 視情況儘速（僅日本站台） |
| C5 | 日本醫療資訊系統安全管理指引第7.0版 | 醫院 → 厚生勞動省，遭攻擊時並報警 | 儘速（僅日本站台） |
| C6 | 個人資料保護法第12條 | 醫院 → 當事人 | 查明後 72 小時 |
| C7 | 醫療機構電子病歷製作及管理辦法 | 醫院 → 衛生主管機關 | 72 小時 |
| C8 | 資通安全管理法 | 醫院 → 主管機關 | 知悉後 1 小時（特定非公務機關或關鍵基礎設施提供者） |
| C9 | IRB 標準作業程序、臨床試驗契約 | 計畫主持人 → IRB、試驗委託者 | 依 IRB 程序與契約 |

### C.4 六種情境

| 情境 | 內容 | 預設嚴重度 | 第一步 |
| --- | --- | --- | --- |
| IC-1 個資外洩 | 病人資料到達無權限的人或地方（寄錯、工單附上截圖、真實資料進入程式庫或紀錄） | 院外為 S1，院內為 S2 | 停止寄信 (F1)，收回或刪除副本 |
| IC-2 主機遺失或遭竊 | 主機、磁碟、連同私鑰的備份，或未加密的機密資料夾遺失 | S1 | 1 小時內啟動 RUNBOOK §23 的遺失清單 |
| IC-3 帳號遭盜用 | TrialBox 帳號被他人使用，或密碼與第二因素同時遺失 | 管理者與資料管理人為 S1，其他為 S2 | 停用帳號 (F3)，重設密碼與第二因素 |
| IC-4 模型異常 | 模型產生錯誤、無依據或遵從文件中植入指令的輸出，且已被人員看到或使用 | 已使用為 S2，被攔下為 S3 | 停止讀取病歷文字，保全追蹤紀錄 |
| IC-5 資料損毀 | 匯入失敗、移轉失敗、磁區損壞、稽核紀錄行損壞 | S3（錯誤數值已被使用為 S2） | 暫停夜間匯入，保全磁區 |
| IC-6 共用平台事件 | 長庚 B200 共用平台發生事件（其他租戶、節點遭入侵、平台管理錯誤） | S3（磁區或機密可能被讀取時為 S1） | 平台團隊隔離節點 |

### C.5 通報範本

```text
事件通報（受託者致醫院）
事件編號: INC-YYYYMMDD-n     嚴重度: S_     情境: IC-_
站台: ____________            知悉時間（當地時間）: YYYY-MM-DD hh:mm
事件經過: ______________________________________________
受影響資料等級: D_   筆數或人數（不寫姓名）: ____
控制措施: ______________________ hh:mm
已保全證據: F_, F_（主機上）  支援包 sha256: ________
可能適用的時限: C_（期限 YYYY-MM-DD hh:mm）
下一步與下次更新時間: ________________________
```
