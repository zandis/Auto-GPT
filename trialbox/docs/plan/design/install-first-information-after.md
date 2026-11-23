# Install first, then the information: card U-5, part 1

**Reader:** the integrator and the owner, then lanes H, K and R for part 2.
**Card:** U-5 (lane U), part 1: research and proposal. Docs only.
**Master read:** `b6d79842` (train 145), 2026-11-23.
**Ruling:** the owner's, as the integrator relayed it on #639 (comments 7105516148 and 7105617639):

- No missing site information stops the install, on PRODUCTION or on a PoC box.
- The hard stops stay: signature or hashes, a machine that cannot run it, root, and a secret where others can read it.
- In PRODUCTION the gate moves to go-live: a step that needs a missing item is refused by name until the item is
  filled in.

**How it was made:** read in code; nothing was run. The comparison in section 2 is from general knowledge of those
products, not from a test.

## 日本語の要約

- **今日：** インストールは最大で約 55 の質問をします（端末のウィザード、インストーラーの途中の質問、初回ページ）。施設の情報が欠けているとインストール、起動、試験の開始、または夜間処理を止める箇所が 36 あります（第 4 節）。
- **提案：** インストールで聞くのは、それがないと動かない **4 つ**だけです。
  1. 画面の言語
  2. タイムゾーン（機械から読み取り、確認だけ）
  3. 最初の管理者（氏名、ユーザー名、パスワード、認証アプリ）
  4. TPM がない機械でだけ、鍵のパスフレーズ
- **その後：** 残りはインストールの後、**「まだ必要な情報」ページ**で一度に入力します。
  - 各項目には「何の前に必要か」を書きます。
  - 欠けている間は、目印の付いた仮の値で動きます。
- **PRODUCTION：** 実データの最初の夜、実患者向けの試験の開始、SAE の通知、メールの送信といった手順は、必要な項目が入るまで、項目名を示して拒否されます。インストールと起動は止まりません。
- **安全のための停止は残します：** 署名・ハッシュ、動かない機械、root、他人が読める場所の秘密。
- 画面の案は第 6 節に英語・繁体字中国語・日本語で示します。

## 繁體中文摘要

- **現況：** 安裝最多會問約 55 題（終端機精靈、安裝程式中途的提問、首次啟動頁）。缺少院所資料就會讓安裝、啟動、試驗開放或夜間作業停下的地方有 36 處（第 4 節）。
- **提案：** 安裝時只問少了就無法運作的 **4 件事**：
  1. 畫面語言
  2. 時區（由機器讀取，只需確認）
  3. 第一位管理員（姓名、帳號、密碼、驗證器）
  4. 機器沒有 TPM 時，金鑰的密語
- **之後：** 其餘資料在安裝完成後，於 **「尚需填寫的資料」頁面**一次填完。
  - 每一項都標明「在哪一步之前需要」。
  - 缺少期間先以標記過的暫定值運作。
- **PRODUCTION：** 會拒絕需要該項資料的步驟，直到資料填好為止，並指名缺的是哪一項。這些步驟包括：真實資料的第一個夜間作業、對真實病人開放試驗、SAE 通知、寄信。安裝和啟動都不會停。
- **安全性停止全部保留：** 簽章與雜湊、機器無法執行、root、密鑰放在他人可讀的位置。
- 頁面草圖見第 6 節，有英文、繁體中文與日文三種版本。

## 1. Every question the install asks today

Kind:

- **E** essential: the install or the box cannot run without it.
- **L** needed later, before the step named.
- **O** optional: a safe default exists.
- **D** detected or derived: it should not be asked at all.

### 1.1 The terminal wizard (`tools/settings_wizard.py`)

| Line | Question | Kind | Needed before | Placeholder until filled |
| ---: | --- | --- | --- | --- |
| 60 | country | L | the first real night (retention rules, the SAE rule sets, date style) | none: the generic rules |
| 61 | site_id | D | – | made from the site name |
| 62 | site_name | L | go-live (the name on reports and mail) | "TrialBox (site name needed)" |
| 63 | tz | D | – | the host's zone, confirmed once |
| 64 | locale | E | – | the screen language (one choice) |
| 67, 73 | printed_dates, year_basis | O | – | from the country |
| 78 | contact (operations mail) | L | any mail out | none; no mail is sent to it |
| 79 | internal_domains | L | any mail in or out | `example.invalid` (never routable) |
| 80 | intake_address | L | reading request mail | none; intake off |
| 81 to 83 | senders, physicians, reviewers | L | reading request mail; approving by mail | empty lists; the console's accounts are used |
| 84 | alliance_sites | O | – | none |
| 85 | data_source_type | L | the first real night | the synthetic hospital on a PoC box; none in PRODUCTION |
| 87, 94 | data_source_path, data_source_host_dir | L | the first real night | as above |
| 103 | ssmix2 order numbers | L | the first SS-MIX2 night | asked only for SS-MIX2 |
| 106 | data_source_dsn_env | L | the first database night | asked only for a database source |
| 107 | mapping | L | the first real night | the shipped mapping of the source kind |
| 108 | mrn_regex | D | – | made from the chart rule (`tools/box/plan.py:403` already does) |
| 111 | chartno_rule | L | the first real night (D-579) | `asis` on a PoC box; none in PRODUCTION |
| 116, 117 | registry_type, registry_path | O | – | none |
| 118, 119 | departments, practitioners | L | "who to screen" by doctor | none; the whole hospital can still be chosen |
| 120 | llm_mode | D | – | from the card |
| 121, 123 | cloud_enabled, attachment_encryption | O | – | no, link |
| 124 | console_url | D | – | from the TLS name or the box name |
| 125, 126 | twpas_enabled, twpas_org_id | O | – | off |
| 127 to 129 | alliance_root, its address, cohort_rulesets | O | – | off |
| 130 to 134 | SMTP and IMAP hosts, ports, user | L | any mail out; reading request mail | none; mail off and said so |
| 135 | mta_authserv_id | L | reading request mail (a safety check: sender authentication) | none; request mail refused, as today |
| 137 | tls_hostname | D, then L | staff use from the clinic PCs | the box's own name |
| 139 | sae_office_mailbox | L | a study of an SAE type opens for real patients; an SAE notice | none on a PoC box, with a warning; refused by name in PRODUCTION |
| 142 | new_year_break | O | – | from the country |
| 146, 151, 152 | tls_mode, certificate and key | L | staff use from the clinic PCs | the box's own certificate |
| 155 | retention_rules | D | – | from the country |
| 160 to 164 | log, mail log, output and attachment days | O | – | from the rules |
| 166 | ctgov_mode | O | – | offline |

The wizard never asks the mail passwords or the database address. Today someone edits `deploy/.env` by hand for them.
On the page they are fields stored as secrets.

### 1.2 The installer's own questions

| Where | Question | Kind | Needed before |
| --- | --- | --- | --- |
| `deploy/install.sh:461` | ClinicalTrials.gov offline or live | O | – (offline) |
| `deploy/install.sh:566` | the console's DNS name | D, then L | staff use from the clinic PCs |
| `deploy/install.sh:591` | the trial office's mailbox | L | as row 139 |
| `deploy/install.sh:818` | "Start the stack now?" | – | not a question: an install starts |
| `deploy/box-install.sh:130` | "Is this the machine?" | E | the one confirmation; it stays |

### 1.3 The box form's first-run page (`services/console/firstrun.py:72`)

| Field | Kind | Needed before |
| --- | --- | --- |
| language | E | – |
| tz | D, confirmed | – |
| owner full name, user name | E | – |
| owner mail | L | the owner's own mail (password reset, notices) |
| password, authenticator | E | – |
| site_name | L | go-live |
| box_name | D | – |
| backup kind, disk, share, folder | L | the first real night (PRODUCTION); a PoC box backs up on the box with a warning |
| anchor and log folders | L | go-live (the audit anchor off the box) |
| source, SS-MIX2 root | L | the first real night |
| chart-number kind and width | L | the first real night |
| retention overrides, printed dates, year basis | O | – |
| health_page_person | L | go-live (who reads the backup alarm) |
| tls_root_confirmed_by | L | staff use from the clinic PCs (only for the box's own certificate) |
| KEK passphrase (no TPM) | E | – |

**Count today:** about 52 wizard entries, of which 45 to 50 are asked depending on the country, plus 4 installer
prompts and 19 first-run fields. Many of these overlap.

**After:** four essential questions (section 3.1) and the machine confirmation. Everything else is detected (D),
moves to the page (L) or takes its default (O), as the tables say.

## 2. How mature on-premises installers do it

The comparison uses products of each kind; it names no product.

| Kind of product | What the install asks | What comes after | How a missing setting shows |
| --- | --- | --- | --- |
| A source-control server sold as one package | one value, its own address; or none | the admin pages; the first visit sets the admin password | a banner on the admin page; the feature that needs it (mail, for example) is off until set |
| A self-hosted file-sharing server | the admin account and the data folder (and its database) | the settings pages | a "set-up warnings" panel on the admin page, which never stops the server |
| A network storage box | the admin account and the network; the time zone detected | a control panel, with a first-use checklist | a notification centre; a feature is refused at its own page with a link to the setting |
| A virtualisation management appliance | stage 1: network and root password. Stage 2: time sync and the sign-in domain | the management pages | a health page with the open items |
| A home automation hub | an account, a location (detected) and units | devices found by themselves, added later | a "repairs" list |

**The common pattern:**

- three to six questions, most of them detected or defaulted;
- one persistent list of what is still to do;
- a feature that needs a setting is refused at that feature, with a link to the setting, and the rest runs.

The hard refusals are signature, hardware, privileges and secrets, which is exactly the owner's list.

## 3. The proposal

### 3.1 The essential list: four questions

1. **The screen language.** One choice, defaulted from the media's language.
2. **The time zone.** Read from the host and shown to confirm. One click unless it is wrong.
3. **The first administrator:**
   - full name and user name;
   - password, twice;
   - authenticator code.

   This is the safety step that already exists.
4. **The key passphrase, twice.** Asked only when the board has no TPM.

**Plus the one confirmation that already exists:** "This machine: … Continue?" (`deploy/box-install.sh:130`).

Everything else is detected (section 1, D) or goes on the page.

The install then runs to the end and opens the console on the page "Information still needed". The box runs with
marked placeholders.

### 3.2 The page "Information still needed"

The page has one list, grouped by the step each item is needed before. Each row shows:

- the item, in plain words;
- why it is needed, in one line;
- who usually knows it (IT, the trial office, the data steward);
- its state: missing, placeholder, or filled and checked;
- a field to fill it in, checked live where a check exists.

The rules for the list:

- **One source of truth.** Every item is defined once, in a list shared by the installer, `doctor`, the page and
  the gates. Each entry gives the key, the step it is needed before, the check, the placeholder and the three
  languages.
- **Filled once.** A value given on the page is written to the box's settings by the host's apply step (as
  `python -m tools.box apply` does for the first-run answers today). Nothing is edited by hand.
- **On a PoC box** each missing item is also a line of `deploy/site/poc-stops.jsonl` (D-1091). `doctor` names it as
  a WARN with the page as its action.
- **In PRODUCTION** `doctor` names it as a WARN too, not a FAIL, so the install's end is not blocked. The gate is at
  the step itself (section 3.3).

### 3.3 The go-live gates (PRODUCTION)

A gate is checked where the step runs. Its refusal names the item and links the page. On a PoC box the same gate
warns, uses the placeholder and goes on.

| Step | Needs | Where the refusal sits |
| --- | --- | --- |
| The first night on real data (ingest and screening) | the data source and its folder or address; the chart-number rule; the country (retention rules); a backup target off the box; the backup key; the backup alert route and its reader; the audit anchor share | the night's start, before the ingest reads the source |
| A study opens for real patients | per study, as today: the SAE rule set, the committee or IRB approval, who to screen. For a study of an SAE type, also the trial office's mailbox | the move to "open" (`services/console/study_setup.py:719`) |
| An SAE notice | the trial office's mailbox and the mail relay | the notice is still recorded and shown on the console; the mail waits, named on the page |
| Any mail out (the morning list, the PI mail) | the mail relay; the operations contact; the console address for link attachments | the mail step; the rest of the night runs |
| Reading request mail | the intake mailbox; the mail authentication id | as today: request mail is refused (a safety check, kept) |
| Staff use from the clinic PCs | the console's name, and the hospital's certificate or the confirmed push of the box's root | a banner on the admin page; the box's own name keeps working |

"Real data" means a source that is not the synthetic hospital. A PoC box never loads real data (D-1091, hard stop 3).

## 4. Where a missing item stops the box today

These rows come from a sweep of the tree. **36 points.** Part 2 hands each one back with the test that proves its
new behaviour.

| # | Where | Missing | What stops | Moves to |
| ---: | --- | --- | --- | --- |
| A1 | `libs/tb_common/config.py:262` | site id, site name, internal domains, senders, data source type (schema) | every service's start | placeholders written at install; never missing |
| A2 | `libs/tb_common/config.py:266` | site.tz | every service's start | the host's zone written at install |
| A4 | `services/console/timefmt.py:18` | the site zone | the console's start | as A2 |
| A5 | `deploy/docker-compose.yml:197` | `TB_TZ` (`${TB_TZ:?}`) | compose start | as A2 |
| A6 | `deploy/docker-compose.identity.yml:45` | `TB_TLS_HOSTNAME` | compose start with the identity overlay | the box's name |
| A7 | `services/adapter/cli.py:133` | the site's mapping file | the night's ingest | the shipped mapping of the source kind; the first-night gate in PRODUCTION |
| A8 | `tools/trialbox/prestart.py:86` | `TB_LDAP_CA` with hospital sign-in on | pre-start and update | hospital sign-in stays off until it is given (a page item) |
| A9 | `deploy/settings_guard.sh:19` | the anchor folder (a bad folder) | start | warn; the go-live gate |
| B1 | `services/console/study_setup.py:683` | the trial office's mailbox | a study's opening; exempts DEV and TEST only, **not VALIDATION** | PoC: warn and open; PRODUCTION: the gate of section 3.3 |
| B2 | `services/console/study_setup.py:688` | the study's SAE rule set | a study's opening | kept: a per-study answer, at the study's own page |
| B3 | `services/console/study_setup.py:721` | committee approval (Japan) | a study's opening | kept: a per-study answer |
| B4 | `services/console/firstrun.py:317` | chart rule, health-page person (PRODUCTION) | the first-run page | the page; the go-live gates |
| B5 | `services/console/firstrun.py:306` | site name, owner mail, backup, SS-MIX2 root, retention | the first-run page | only the section 3.1 four are required there |
| C1 | `services/orchestrator/scenarios/screen.py:574` | who to screen | a SCREEN job | kept: a per-study answer, named on the study's page |
| C2 | `services/orchestrator/scenarios/nav.py:141` | NAV departments | a NAV job | kept: per job |
| C3 | `services/adapter/pipeline.py:109` | the site zone | the night's ingest | as A2 |
| C4 | `services/mail_gateway/outbound.py:243` | the console address with link attachments | mail with patient files | derived from the box's name (D) |
| C5 | `services/mail_gateway/app.py:37`, `intake.py:71` | the mail authentication id | request mail | kept (a safety check); a page item |
| C6 | `tools/trialbox/backup_schedule.py:860` | backup targets, off-box, alert route | the nightly backup records a failure | the go-live gate; on a PoC box the backup stays on the box with a warning |
| D1 | `deploy/box-install.sh:137` | the owner's answers file | an unattended install | only the four are required |
| D2 | `deploy/box-install.sh:245` | the first-run answers; the wizard's errors (no environment passed) | the first-run apply | as D5 |
| D3 | `deploy/box-install.sh:266`, `tools/trialbox/finish_check.py:642` | anchor folder; backup target | the first run's end (PRODUCTION) | warn; the go-live gate |
| D4 | `deploy/box-install.sh:304` | everything `doctor` FAILs on | the install's exit code | `doctor` FAILs only on the hard stops (E rows) |
| D5 | `tools/settings_wizard.py:491` to :664 | internal domains, mapping, source type, source folder, locale, tz | the wizard, so the install | placeholders and page items; locale and tz are the essentials |
| D6 | `tools/settings_wizard.py:506` | chart rule (PRODUCTION) | the wizard | a page item; the first-night gate |
| D7 | `tools/settings_wizard.py:814` | the backup alarm's reader (PRODUCTION) | the wizard | a page item; the go-live gate |
| D8 | `tools/settings_wizard.py:605`, :629, :651 | hospital certificate files; TWPAS code; retention days | the wizard | the box's own certificate; TWPAS off; the generic rules |
| D9 | `tools/settings_wizard.py:330`, :357 | country; required keys after five empty answers | the wizard | not asked at install |
| D10 | `libs/tb_common/box_answers.py:231` | site name, tz, owner, backup, SS-MIX2 root, retention | the first-run answers | only the four |
| D11 | `libs/tb_common/box_answers.py:371` | chart rule, health-page person | the first-run page (PRODUCTION) | page items |
| D12 | `tools/trialbox/backup_schedule.py:1401` | the backup alert route (PRODUCTION) | `backup-install` | a page item; the go-live gate |
| D13 | `deploy/install.sh:523` | as D3 (marked "H-94 depends") | the install | as D3 |
| E1 | `tools/trialbox/doctor.py:892` | site zone | FAIL everywhere | never missing (A2) |
| E3 | `tools/trialbox/doctor.py:1009` | backup targets, alert route | FAIL in PRODUCTION | WARN naming the page |
| E4 | `tools/trialbox/doctor.py:1276` | the anchor share | FAIL in VALIDATION and PRODUCTION | WARN naming the page |
| E5 | `tools/trialbox/doctor.py:1386` | `TB_LDAP_CA` with hospital sign-in on | FAIL in VALIDATION and PRODUCTION | as A8 |

**Kept as they are, because they are hard stops:**

- the signature and hashes;
- the machine's disk, memory and card;
- root;
- a secret where others can read it;
- real data on a PoC box.

**Kept, because they are per-study answers made at the study's own page, not site information:** B2, B3, C1 and
C2.

**Kept, because it is sender authentication:** C5. It stops only request mail, never the box.

## 5. Part 2: the build, by lane

Each card is small or medium, and each names its test.

| Card | What | Files | Lane | Test |
| --- | --- | --- | --- | --- |
| U5-1 | The one list of site items: key, needed before, check, placeholder, three languages | a new module in `libs/tb_common/` | owner to confirm (question 1) | A test that every key the wizard, the first-run page, `doctor` and the gates read is on the list, once |
| U5-2 | The install asks only the four, writes placeholders and never stops on a missing item | `tools/settings_wizard.py` (R); `libs/tb_common/box_answers.py`, `tools/box/plan.py`, `deploy/box-install.sh`, `tools/trialbox/finish_check.py`, `deploy/install.sh` (H) | H, R | An install driven with only the four answers, environment PRODUCTION, reaches the end with exit 0, and the list holds every L item; the same with a missing hard-stop input still stops |
| U5-3 | Start never stops on a missing site item | `libs/tb_common/config.py`, `deploy/docker-compose.yml`, `deploy/docker-compose.identity.yml`, `services/console/timefmt.py` | owner to confirm (question 1) | Every service starts on the placeholder settings; the schema test still refuses a malformed value |
| U5-4 | `doctor`: a missing site item is a WARN naming the page; FAIL stays for the hard stops | `tools/trialbox/doctor.py` | H | Each E row of section 4 is WARN with a missing item and FAIL with a broken one |
| U5-5 | The page "Information still needed", and the host apply of its answers | `services/console/` (a new page) (K); the apply step in `tools/box/` (H) | K, H | A filled item reaches `deploy/.env` or `settings.yaml` through the apply and drops off the list; the page renders in three languages with no setting name shown |
| U5-6 | The go-live gates of section 3.3, by name; on a PoC box they warn | `services/console/study_setup.py` (B1) (K); the night's start and the mail step (owners to confirm, question 1) | K, others | One test per gate: in PRODUCTION the step is refused naming the item; on a VALIDATION box it runs with the placeholder and the list has the line |

## 6. The page: a mock in three languages

### English

> **Information still needed**
> TrialBox is installed and running. Fill these in when you have them. Nothing here stops the box. Each step waits
> only for what it needs.
>
> | Needed before | Item | Why | Usually known by | State |
> | --- | --- | --- | --- | --- |
> | The first night on real data | Where the hospital's records come from | The night reads them | Hospital IT | Missing · [Fill in] |
> | The first night on real data | How a chart number is written | One patient is one number | Medical records | Missing · [Fill in] |
> | The first night on real data | Where backups go (off this machine) | A copy that survives the box | Hospital IT | On this machine only · [Fill in] |
> | A study opens for real patients | The trial office's mailbox | It is told at once of a serious adverse event | Trial office | Missing · [Fill in] |
> | Any mail | The hospital's mail relay | The morning list and notices are mailed | Hospital IT | Missing · [Fill in] |
> | Staff use from clinic PCs | The console's name and certificate | The browser trusts the box | Hospital IT | The box's own · [Fill in] |
> | – | The hospital's name | On reports and mail | Trial office | Placeholder · [Fill in] |

### 繁體中文

> **尚需填寫的資料**
> TrialBox 已安裝並在運作中。有資料時再填即可。這裡的項目都不會讓機器停下，每個步驟只會等它自己需要的資料。
>
> | 在哪一步之前需要 | 項目 | 原因 | 通常由誰提供 | 狀態 |
> | --- | --- | --- | --- | --- |
> | 真實資料的第一個夜間作業 | 醫院病歷資料的來源 | 夜間作業要讀取它 | 資訊室 | 未填 · [填寫] |
> | 真實資料的第一個夜間作業 | 病歷號的寫法 | 一位病人對應一個號碼 | 病歷室 | 未填 · [填寫] |
> | 真實資料的第一個夜間作業 | 備份存放處（本機以外） | 機器故障時仍保有副本 | 資訊室 | 僅在本機 · [填寫] |
> | 對真實病人開放試驗 | 試驗辦公室的信箱 | 發生嚴重不良事件時立即通知 | 試驗辦公室 | 未填 · [填寫] |
> | 任何郵件 | 醫院的郵件轉送伺服器 | 寄送晨間名單與通知 | 資訊室 | 未填 · [填寫] |
> | 院內電腦使用 | 控制台的名稱與憑證 | 讓瀏覽器信任這台機器 | 資訊室 | 本機自有 · [填寫] |
> | – | 醫院名稱 | 顯示於報告與郵件 | 試驗辦公室 | 暫定值 · [填寫] |

### 日本語

> **まだ必要な情報**
> TrialBox はインストールされ、動いています。わかったときに入力してください。ここの項目で機械が止まることはありません。各手順は、その手順に必要なものだけを待ちます。
>
> | 何の前に必要か | 項目 | 理由 | 通常知っている人 | 状態 |
> | --- | --- | --- | --- | --- |
> | 実データの最初の夜間処理 | 病院の診療データの取得元 | 夜間処理が読み込みます | 情報システム部門 | 未入力 · [入力] |
> | 実データの最初の夜間処理 | 患者 ID（カルテ番号）の書き方 | 一人の患者を一つの番号にします | 診療情報管理 | 未入力 · [入力] |
> | 実データの最初の夜間処理 | バックアップの保存先（この機械の外） | 機械が壊れても残る複製 | 情報システム部門 | この機械のみ · [入力] |
> | 実患者向けに試験を開始する | 治験事務局のメールアドレス | 重篤な有害事象をすぐに知らせます | 治験事務局 | 未入力 · [入力] |
> | すべてのメール | 病院のメール中継サーバー | 朝の一覧と通知を送ります | 情報システム部門 | 未入力 · [入力] |
> | 院内の端末から使う | コンソールの名前と証明書 | ブラウザーがこの機械を信頼します | 情報システム部門 | 機械自身のもの · [入力] |
> | – | 病院の名前 | 報告書とメールに表示します | 治験事務局 | 仮の値 · [入力] |

## 7. Questions

1. **Owners.** U5-1 and U5-3 touch `libs/tb_common/config.py`, the compose files and a new module in
   `libs/tb_common/`. U5-6 touches the night's start (`services/orchestrator/`, `services/adapter/`) and the mail step
   (`services/mail_gateway/`). Which lanes own these?
2. **The essential four.** Are they confirmed: language; time zone, detected; the first administrator; the passphrase
   only without a TPM?
3. **The owner's mail.** Should the first administrator's mail move to the page? It is not needed to run, but it is
   needed for the owner's own notices.
4. **The PoC gate.** On a VALIDATION box, B1 refuses today; the ruling makes it a warning. Should DEV and TEST, which
   skip the check entirely today, also list the item?

## 8. Findings

Three findings are in [`install-first-information-after/findings.json`](install-first-information-after/findings.json)
(card U5): two Medium and one Low.
