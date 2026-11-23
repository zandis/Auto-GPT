# A hospital installs TrialBox without an engineer: the audit and the design

**Reader:** the owner first, then the integrator and lanes H, K and R for the cards in section 5.
**Card:** U1 (lane U; docs only). **Master read:** `85401c90` (train 131), 2026-11-22.
**How it was made:** read in code and documents. No install was run, no box was started, nothing was measured. A
line marked "read" was read in a file at the line named; nothing here was seen on a running box.

## 日本語の要約

病院の IT 担当者（開発者ではない）と臨床研究コーディネーターが、技術者なしで TrialBox を導入・設定できるようにする。これは第0圏の約束（「作っていない人による導入」、D-1070、rc1 の 6 行目）そのものである。

- **今日：** リリースバンドルから最初のスクリーニングの夜までに、人が手を動かす箇所が **76**（コマンド入力、フラグ、ファイルの手編集、技術的なメッセージ、機械が検出できる選択、二度目または途中での質問）。これに加えて端末のウィザードが英語で約 45 問を聞く。エラーメッセージはほぼすべて英語のみで、環境変数名、ファイルパス、D 番号を含む。
- **目標：** IT が 1 つのコマンド（Windows ではダブルクリック）を実行し、署名の確認と「この機械でよいか」の確認を 1 行ずつ行う。その後はすべてブラウザで行う。施設のデータは最初に 1 つのウィザードで 1 回だけ聞き、途中では聞かない。ハードウェア、ティア、鍵の保管方式、タイムゾーンは自動で検出し、1 行で確認する。拒否やエラーは画面の言語で平易に書き、次にすることを 1 つだけ示す。技術的な詳細はサポートファイルにだけ入れる。通常の導入にフラグは要らない（リハーサルとテストのフラグは残すが、病院向けの経路からは隠す）。PoC はプレースホルダーのデータを使い、病院の実データは使わない。
- **安全のための拒否はすべて残す。** 変わるのは見せ方だけである。
- **目標の手順数：19**（IT 8、施設の設定 5、最初の試験の設定 6）。ウィザードの答えは約 21 で、すべて最初に聞く。
- **カード：** 14 枚。最も多くの手順を減らすものから順に並べる（第 5 節）。

## 繁體中文摘要

讓醫院的資訊人員（不是開發者）和研究協調員，在沒有工程師的情況下完成 TrialBox 的安裝和設定。這正是第 0 圈的承諾（「由不是作者的人安裝」，D-1070，rc1 第 6 行）。

- **現況：** 從發行包到第一個篩選夜，總共有 **76** 個需要人動手的地方：輸入指令、給參數、手動改檔案、讀技術訊息、選擇機器本來就能偵測的東西、同一筆資料問兩次或在中途才問。另外，終端機精靈還會用英文問大約 45 題。錯誤訊息幾乎全是英文，裡面夾著環境變數名稱、檔案路徑和 D 編號。
- **目標：**
  - 資訊人員只執行一個指令（Windows 上是按兩下），確認簽章一行、確認「是這台機器」一行，之後全部在瀏覽器完成。
  - 院所資料在一開始用一個精靈只問一次，中途不再問。
  - 硬體、等級、金鑰保管方式和時區自動偵測，再用一行讓人確認。
  - 每個拒絕或錯誤都用畫面的語言、白話說明，只給一件下一步要做的事；技術細節只放進支援檔案。
  - 一般安裝不需要任何參數。演練和測試用的參數保留，但不出現在醫院走的路徑上。
  - PoC 一律用預設的示範資料，不用醫院的真實資料。
- **所有安全性拒絕都保留，** 改的只是呈現方式。
- **目標步驟數：19**（資訊人員 8 步、院所設定 5 步、第一個試驗的設定 6 步）。精靈大約有 21 個答案，全部在一開始就問完。
- **卡片：** 14 張，依「先拿掉最多步驟」的順序排列（第 5 節）。

## 1. What a hospital meets today

There are two install routes on master, and a hospital reads the first one:

- **The IT form**, `docs/runbook/01-install-a-new-site.md`. Hospital IT writes `site.yaml` by hand, verifies the
  bootstrap by hand, and runs `deploy/bootstrap.sh`, which runs `deploy/install.sh`. The install starts
  `tools/settings_wizard.py` on the terminal, or reads the hand-written answers.
- **The box form**, `deploy/box-install.sh` (RUNBOOK §16). The box detects its own hardware (`tools/box/plan.py`).
  The person answers a single question on the terminal, and the rest goes through the browser's first-run page
  (`services/console/firstrun.py`, answers checked by `libs/tb_common/box_answers.py`).

**The box form is already close to the target, and the design builds on it.** Its gaps are listed in the tables below.

Who: **IT** = hospital IT; **CO** = the trial coordinator or the box's owner (a research lead); **V** = the vendor.
Kind: **a** type a command, **b** give a flag, **c** edit a file by hand, **d** read a technical message,
**e** choose what the machine could detect, **f** give the same data twice, or give it mid-way.

### 1.1 Before the one command

| # | Where | What the person meets | Kind | Who |
| ---: | --- | --- | --- | --- |
| 1 | `docs/runbook/01-install-a-new-site.md:123` | Host preparation by hand: OS, disk encryption, TPM, swap off, container engine, driver held | a | IT |
| 2 | `docs/runbook/01-install-a-new-site.md:66` | `TB_SITE_PATIENTS` written into `deploy/.env` before the first install, when that file does not exist yet | c, f | IT |
| 3 | `docs/runbook/01-install-a-new-site.md:85` | `site.yaml` and a mapping file written by hand | c | IT |
| 4 | `docs/runbook/01-install-a-new-site.md:91` | The export folder must exist and hold the first export, or a PRODUCTION install stops | a | IT |
| 5 | `docs/runbook/01-install-a-new-site.md:128` | `SSH=off` in `hardening.conf`, or the flag `--ssh-off-over-ssh` | b, c | IT |
| 6 | `deploy/install.sh:945` | "copy deploy/hardening/hardening.example.conf, fill it in with hospital IT, re-run": clinic ranges, SSH, the key back end. The box form detects the ranges | c, e | IT |
| 7 | `docs/runbook/01-install-a-new-site.md:30` | Mount the stick and put the vendor key, which came separately, at a fixed path | a | IT |
| 8 | `docs/runbook/01-install-a-new-site.md:34` | One line of about 300 characters: a signature check, `&&`, the bootstrap, `--pub`, `--`, `--tier`, `--answers` | a, b | IT |
| 9 | `docs/runbook/01-install-a-new-site.md:36` | The person reads the signature tool's own output for one exact sentence | d | IT |
| 10 | `docs/runbook/01-install-a-new-site.md:5` | Choose `--tier small\|medium\|large`. The installer then checks that choice against the card it can see | b, e | IT |
| 11 | `docs/runbook/01-install-a-new-site.md:47` | `--mode stub` on a machine with no GPU, which the machine can see for itself | b, e | IT |
| 12 | `deploy/install.sh:10` | No TPM: a four-line shell recipe to set a passphrase in the environment | a, b, d, e | IT |

### 1.2 During the install

| # | Where | What the person meets | Kind | Who |
| ---: | --- | --- | --- | --- |
| 13 | `deploy/install.sh:445` | "no deploy/settings.yaml and no terminal for the questions: pass --answers site.yaml (RUNBOOK §1 step 3)" | b, d | IT |
| 14 | `tools/settings_wizard.py:59` | About 45 questions on the terminal (section 1.6), in English except two. Examples: "Env var holding the SQL DSN" (:106), "MRN pattern (regular expression)" (:108), "authserv-id your MTA writes first in Authentication-Results" (:135) | d, e, f | IT, CO |
| 15 | `deploy/install.sh:461` | The ClinicalTrials.gov question again, when the settings lack it | f | IT |
| 16 | `deploy/install.sh:566` | "The console's DNS name for https" asked mid-way when the wizard's answer was empty | f | IT |
| 17 | `deploy/install.sh:591` | The trial office's mailbox asked mid-way when the wizard's answer was empty | f | IT |
| 18 | `deploy/install.sh:818` | "Start the stack now with profile %s? [Y/n]", asked after a 10 to 20 minute load | d, f | IT |
| 19 | `deploy/install.sh:810` | The finish gate runs after the load: "Change what the lines above name in deploy/.env, then re-run" | c, f | IT |
| 20 | `deploy/install.sh:570` | Stops that name settings to put in `deploy/.env` (also :555, :601): `TB_TLS_HOSTNAME`, `TB_SOURCE_DIR`, `TB_SAE_OFFICE_MAILBOX` | c, d | IT |
| 21 | `deploy/install.sh:629` | Memory sizing failed: "set TB_MEM_ADAPTER, TB_MEM_LAKE and TB_MEM_ORCH" (also :636 for the database) | c, d | IT |
| 22 | `deploy/install.sh:772` | A permission change on the anchor folder, typed by hand, then a re-run | a, d | IT |
| 23 | `deploy/install.sh:1054` | "With hospital IT: python3 -m tools.trialbox backup-keygen --private … --public …" | a, d | IT |
| 24 | `deploy/install.sh:1066` | The backup alert route as one of three settings in `deploy/.env` | c, d | IT |
| 25 | `deploy/install.sh:1155` | Add users "on the console's Users page, or: docker compose exec console python -m console.cli add-user" | a, d | IT |
| 26 | `deploy/install.sh:1216` | The first ingest by a compose command | a, d | IT |
| 27 | `deploy/check_host.sh` | Every PASS, WARN and FAIL line is in English, with D and T numbers, firewall table names and system commands | d | IT |
| 28 | `deploy/install.sh:90` | Almost every stop line, in all the deploy scripts, is English only and names a RUNBOOK section, a D number, a path or a setting. Only four install lines are in three languages (:158, :869, :1071, :1074) | d | IT |
| 29 | `deploy/install.sh:89` | `--help` prints the script's own comments, D numbers and test knobs included | d | IT |

### 1.3 After the install (the runbook's steps)

| # | Where | What the person meets | Kind | Who |
| ---: | --- | --- | --- | --- |
| 30 | `docs/runbook/01-install-a-new-site.md:153` | Run the settings wizard again with `--out`, `--env-out` and `--check`, although the one command already did | a | IT |
| 31 | `docs/runbook/01-install-a-new-site.md:165` | Copy a mapping template, then run a long container command; it "must report 0 missing columns" | a, c, d | IT, CO |
| 32 | `docs/runbook/01-install-a-new-site.md:171` | Steps the installer already does (secrets, compose up, the firewall, services) are still listed as steps | a | IT |
| 33 | `docs/runbook/01-install-a-new-site.md:185` | The first ingest by command, then the person reads a JSON report for `passed: true` | a, d | IT |
| 34 | `docs/runbook/01-install-a-new-site.md:190` | `check_host.sh [--gb10]`, which the machine could detect, then `doctor --preflight --env-file deploy/.env --lang ja` | a, b, e | IT |
| 35 | `docs/runbook/01-install-a-new-site.md:197` | Single sign-on as four settings in `deploy/.env` | c | IT |
| 36 | `tools/trialbox/doctor.py:383` | `named_choices` prints "add TB_CHARTNO_RULE_ANSWERED=yes to deploy/.env" and similar lines to add | c, d | IT |
| 37 | `tools/trialbox/doctor.py:875` | The time zone must agree in four places: `settings.yaml`, `deploy/.env`, the mapping and the host. The host's zone is detected and still asked | c, e, f | IT |
| 38 | `tools/trialbox/__main__.py:64` | `doctor` has no default settings file. A bare `trialbox doctor` judges only the exported variables (`doctor.py:2274`). `pyproject.toml:74` installs no `trialbox` command; `install.sh:403` links one only when run as root | a, b, d | IT |
| 39 | `docs/runbook/12-identity-and-tls.md:18` | TLS settings in `deploy/.env` and an overlay added to `COMPOSE_FILE`, then compose up. The installer already turned TLS on | a, c, f | IT |
| 40 | `docs/runbook/12-identity-and-tls.md:25` | Copy the internal root certificate out of a container | a | IT |
| 41 | `docs/runbook/12-identity-and-tls.md:44` | The first administrator's code by a console command. The installer already printed it once (`install.sh:1151`) | a, f | IT |
| 42 | `docs/runbook/12-identity-and-tls.md:62` | A breached-password list downloaded, copied in and named in `deploy/.env` | a, c | IT |
| 43 | `docs/runbook/05-updates-backup-restore-secrets.md:91` | Backup targets in `deploy/.env`, or a marker file made by hand | c, d | IT |
| 44 | `docs/runbook/05-updates-backup-restore-secrets.md:99` | `backup-install` run again after the key exists, because the installer ran before the key did | a | IT |
| 45 | `docs/runbook/05-updates-backup-restore-secrets.md:105` | The backup time is edited by hand in the cron file, although the box knows its night's jobs | c, e | IT |
| 46 | `docs/runbook/05-updates-backup-restore-secrets.md:135` | Database archiving: "on by default", followed by four steps by hand | a, c | IT |
| 47 | `docs/runbook/06-go-live-acceptance.md:7` | Nine acceptance commands with JSON and CSV paths | a | V |
| 48 | `docs/runbook/06-go-live-acceptance.md:32` | "ask the site's REDCap administrator for the version", which the bridge reads when it connects | e | CO |
| 49 | `docs/handover/OFFLINE-MEDIA.md:145` | Terminology loaded by about eight commands with `--accepted-by` and `--accepted-on` | a, b | IT |
| 50 | `docs/runbook/18-site-mapping-without-site-data.md:167` | The site profile: fill, edit, check, copy, load. The answers come from a questionnaire the hospital already filled | a, c, f | CO |
| 51 | `docs/handover/it-one-page.en.md:34` | "the owner writes it as `TB_TLS_HOSTNAME`" | c, d | CO |
| 52 | `docs/handover/network-sheet.en.md:16` | The sheet hospital IT reads is written in setting names (`SMTP_HOST`, `EGRESS_EXTRA`) | d | IT |

### 1.4 The box form's own gaps

| # | Where | What the person meets | Kind | Who |
| ---: | --- | --- | --- | --- |
| 53 | `deploy/box-install.sh:3` | Its own command and flags (`--yes`, `--prepare`, `--rehearsal`, `--answers`, `--firstrun`). A bare machine also needs `box-prepare.sh <media> --pub <key>` and a restart first | a, b | IT |
| 54 | `tools/box/plan.py:587` | No mail relay field anywhere: `smtp_host` and `imap_host` are written empty, so mail stays closed until someone edits a file by hand. The first-run page has no field for the trial office's mailbox | c, f | IT |
| 55 | `services/console/i18n_firstrun.py:50` | "you connect it on the box after sign-in". No console page connects a research database, own database, hospital feed or SS-MIX2 folder; the connection is made from the command line (RUNBOOK §1 step 4, §18) | a, f | CO |
| 56 | `services/console/templates/firstrun.html:7` | The language is asked twice on one page: the buttons, and a select at line 57 | f | CO |
| 57 | `services/console/i18n_firstrun.py:139` | Linux paths as help text (`/srv/trialbox-backup`, `/mnt/trialbox-audit`) and a list of system folders; the disk picker shows device paths (`firstrun.html:104`) | d | CO |
| 58 | `services/console/templates/firstrun.html:97` | The owner types the name of the IT person who confirmed that the root certificate was pushed, so IT must have done that already | f | CO |
| 59 | `services/console/templates/firstrun.html:35` | The preflight list was written by the installer and cannot be run again from the page; its lines end "run the check again" | a | CO |
| 60 | `deploy/box-install.sh:269` | A refused finish: "change the setting each line names in …/deploy/.env (the first-run page does not open again…). Then: sudo deploy/box-install.sh --firstrun" | a, c, d, f | IT |
| 61 | `deploy/box-install.sh:208` | "run 'python3 -m tools.trialbox doctor --preflight --env-file deploy/.env' after the set-up" | a, d | IT |
| 62 | `deploy/box-install.sh:110` | The unattended form takes `owner.json` written by hand, with the same fields as the first-run page | c, f | IT |
| 63 | `tools/box/plan.py:617` | The host's time zone is detected but used only for the provisional plan; the owner answers it again | e, f | CO |

### 1.5 The first study (console)

| # | Where | What the person meets | Kind | Who |
| ---: | --- | --- | --- | --- |
| 64 | `services/console/app.py:2289` | A ruleset id with a format rule; the refusals are in English inside translated pages (also :2308, :2313) | d | CO |
| 65 | `services/console/templates/study_state.html:69` | Sponsor, protocol number and registry ids typed again, though the protocol carries them | f | CO |
| 66 | `services/console/templates/approval.html:51` | On ja and zh-TW pages, a short label typed for every criterion before approval | f | CO |
| 67 | `services/console/templates/team_log.html:38` | The delegation log asks for a name the account already has | f | CO |
| 68 | `services/console/templates/site_staff.html:18` | Staff typed again: the terminal wizard already asked practitioners and departments (`settings_wizard.py:118`) | f | CO |
| 69 | `services/console/templates/team_irb.html:21` | The IRB number and date asked in three places: here, `study_state.html:78`, and the amendment on `approval.html:71` | f | CO |
| 70 | `services/console/templates/setup.html:53` | The EDC block: raw field names, code values and a `1=inclusion` map. The connection is chosen in five places (also `data_sources.html:41`, `life_schedule.html:45`, `edc_map.html:16`, `redcap.html:25`) | d, f | CO |
| 71 | `services/console/templates/setup.html:113` | The SAE rule set must be chosen, though the site's country fixes the list. The study stops at the screening run until it is chosen | e, f | CO |
| 72 | `services/console/templates/setup.html:138` | "Who to screen" by doctors: practitioner ids typed again | f | CO |
| 73 | `services/console/templates/setup.html:3` | The error box prints the raw code; the reasons are in English (`study_setup.py:305`, :345, :422, :439) | d | CO |
| 74 | `services/console/templates/life_schedule.html:6` | The visit schedule typed again, though the compiled protocol holds it | f | CO |
| 75 | `services/console/study_setup.py:901` | The EDC address and key asked mid-way on an admin page; the installer never asks them | f | IT |
| 76 | `services/console/templates/team_log.html:38` | Approval waits until the steward names the PI on the delegation log, and no page says so | f | CO |

**Count today: 76 points**, plus about 45 terminal questions. IT alone meets 52, CO alone 21, both 2 and the vendor 1.
Rows 47 to 50 are the vendor's and the steward's work as the runbook describes it. They are counted because the runbook hands
them to the site.

### 1.6 The terminal wizard's questions (row 14)

The questions are at `tools/settings_wizard.py:59` to :166, about 45 to 50 asked depending on the country. Two are in
three languages: the country (:323) and ClinicalTrials.gov (:338). The rest are in English. Pressing Enter keeps the
synthetic demo values of `deploy/settings.example.yaml`.

About 18 are site data: name, contact, addresses, people, departments, the mailbox. About 30 are technical:

- the source type and paths
- a variable name that holds the database address
- the mapping file
- a regular expression
- the chart rule
- the model mode
- encryption
- SMTP and IMAP hosts and ports
- the mail authentication id
- the TLS mode and certificate paths
- retention days and log days

The same fact is asked twice in these places:

- the time zone (:63; the host's zone is detectable)
- `site_id` and `site_name` (:61, :62)
- `console_url` and `tls_hostname` (:124, :137)
- `mrn_regex` and `chartno_rule` (:108, :110); `plan.py:403` makes one from the other
- `llm_mode` (:120; `install.sh` detects the GPU anyway)
- the retention rules and the country (:154)

The mail passwords and the database address are never asked, so someone must edit a file by hand.

## 2. The target path

### 2.1 What a hospital does

**IT, 8 steps:**

1. Plug in the stick. Run one command, or double-click on Windows: `sudo bash /media/<stick>/install`. No option.
2. The screen shows the vendor key's fingerprint as a short code, and the delivery sheet carries the same code
   on paper. IT confirms the match with one line. A mismatch stops the install, and nothing is changed.
3. The screen shows one line about the machine, then asks "Continue?":
   "This machine: RTX PRO 6000 96 GB, 256 GB memory, TPM present → TrialBox large."
   With no GPU, it says "no graphics card → feasibility and coded criteria only".
4. The bundle loads (10 to 20 minutes) and nothing is asked meanwhile. The screen then shows an address and a one-time code.
5. In the browser, the wizard's **network** page: the box's name (suggested), the hospital's certificate or the
   box's own (default), and the mail relay, which may be "no mail for now". The pages are in section 2.2.
6. The wizard's **storage** page: the backup target (picked from the detected disks, or a share address), the
   audit share, and the passphrase when the board has no TPM. Each line is checked live, with "Check again".
7. The hospital's own job, kept: the box's root certificate is pushed to the clinic PCs (only for the box's own
   certificate).
8. Kept for security: the enrolment code is handed to the owner in person.

**The owner or coordinator, 5 steps in the same wizard:**

9. **Language and hospital:** one language choice, which also chooses the date style and the country. The hospital's
   name. The time zone, shown as detected, to confirm.
10. **The owner's account:** name, user name, mail, password, authenticator. Unchanged; it is a safety step.
11. **People:** the trial office's mailbox for SAE notices, and who reads the health page (picked from the people just
    named).
12. **Data:** the kind of source. On a PoC box it is the placeholder hospital, chosen by default. The chart number
    is given as one example as printed, and the box works out the rule.
13. **Review:** every answer on one page in plain words, then "Start". The box applies the answers, restarts, sets
    the backup schedule and ends on the sign-in. No question comes after this page.

**The first study, 6 steps (per study, not site data):**

14. Upload the protocol.
15. Confirm what the box read from it: identifiers, visit schedule. Corrections only, nothing retyped.
16. Approve the criteria.
17. The team: pick accounts; the names come from them.
18. The IRB approval, entered once and used everywhere.
19. Who to screen, picked from the staff list. The SAE rule set is the country's, shown as chosen. The first
    screening night then runs on the schedule.

**Count after: 19 steps, with about 21 answers, all in the wizard at the start.** No typed command but the first.
No file is edited. No setting name, path or D number is shown to the hospital.

### 2.2 The one wizard

The wizard is the box form's first-run page (`services/console/firstrun.py`), extended. The terminal wizard and
the hand-written answers files stay for the vendor and for unattended installs. They leave the hospital's path.

| Page | Asks | Detected or derived, shown to confirm | Who |
| --- | --- | --- | --- |
| 1. Language and hospital | language; hospital name | country and date style from the language and the zone; time zone from the host; the site id from the name | CO |
| 2. Owner | full name, user name, mail, password twice, authenticator code | – | CO |
| 3. People | trial office mailbox; health-page person (pick) | the contact from the owner's mail | CO |
| 4. Network | box name; certificate: the box's own (default) or the hospital's (upload two files); who confirmed the root was pushed (only for the box's own); mail relay host and port, user and password if needed, or "no mail for now" | the clinic network from the box's own network; the mail authentication id from the relay's greeting where it gives one | IT |
| 5. Storage | backup target: a detected disk (shown by size and maker, not device path) or a share address; the audit share; the passphrase twice when there is no TPM | the key back end from the TPM; the memory caps and the database size from the hardware | IT |
| 6. Data | source kind; for SS-MIX2 or CSV the folder, picked; one chart number as printed | placeholder hospital on a PoC box; the chart rule and its pattern from the example; the patient count from the source's first read | CO |
| 7. Review | – | every answer and every detected value in one list, each with "change" | CO |

Rules for the wizard:

- **Everything once, at the start.** A value the installer, `doctor` or a console page needs is asked here or
  derived, never later, and never in a file. Today's stops, prompts and `doctor` lines that send a person to a file
  (rows 2, 15 to 24, 36, 37, 43, 54, 60) become wizard fields.
- **Pages split by who knows the answer.** IT's two pages can be filled first, from the stick's sheet, or by IT
  at the box. The owner's pages follow. The progress is kept, so a page can be left and come back to.
- **Live checks, plainly.** Each storage, network and mail line is checked when it is answered (building on 10K-3),
  shown in the page's language with one next action and a "Check again" button. The detail goes to the support file.
- **The site seed (10K-2) fills it.** When the vendor prepared the box from the hospital's questionnaire, each
  answer is shown filled in, to confirm.

### 2.3 PoC and placeholder data

A PoC box (environment TEST or VALIDATION, which the vendor's media decides, not the person) offers "fill with
placeholder values". The hospital name, people and mailboxes are filled with marked placeholders, and the source is
the synthetic hospital. The owner's ruling holds: a PoC never takes real hospital data.

- **Kept refusal:** a PRODUCTION box refuses any placeholder value. The source of that rule is
  `box_answers` (`libs/tb_common/box_answers.py`).
- **Shown as:** "This is a demonstration value. A live box needs the hospital's own."

### 2.4 Detected, not asked

| Today asked | Detected from | Shown as |
| --- | --- | --- |
| `--tier`, `--gpu`, `--mode` (rows 10, 11) | the card, its memory and the vendor's measured records (`deploy/gpu_profile.sh`, `tools/box/plan.py:160`) | "This machine: … → TrialBox large. Continue?" |
| the key back end (row 12) | the TPM | "Keys are kept in this machine's security chip" or the passphrase field |
| the time zone (rows 14, 37, 63) | the host | the zone, to confirm |
| `--gb10` for the host check (row 34) | the card | nothing |
| the clinic ranges (row 6) | the box's network | the range, to confirm |
| memory caps (row 21), the patient count (row 2) | the hardware; the source's first read | nothing; a stop becomes a plain line |
| the backup time (row 45) | the night's schedule | nothing |
| the EDC version (row 48) | the bridge's first call | nothing |
| the SAE rule set (row 71) | the country | the set, chosen |

### 2.5 Every refusal in plain words

- **One message, three languages, one action.** Each stop and FAIL line in the deploy scripts, the finish check, the
  host check and `doctor` gets a message key in en, ja and zh-TW (the preflight's catalogue, `libs/tb_common/preflight.py`,
  is the model). It says what is wrong in plain words and the one thing to do next.
- **Detail goes to the support file only.** The setting name, the path, the D number and the exception go to the
  install log and the support file, never to the screen.
- **The language** is the stick's language before the wizard, and the wizard's language after it.
- **Kept on the console:** the error box's raw code (row 73) moves to the support file, and every refusal reason
  becomes a catalogue key.

### 2.6 No flags for a normal install

The flags and knobs for rehearsals and tests stay as they are: `--rehearsal`, `--prepare`, `--answers`, the
`TB_TEST_*` and `TB_BOX_*` knobs, `TB_COMPOSE_OVERRIDE` and `TB_ACCEPT_UNMEASURED_GPU`.

- `--help` shows only the hospital's command. A separate `--help-expert` lists the rest.
- The hospital's pages name no flag and no setting.

### 2.7 Every safety refusal is kept

| Refusal (today) | Kept as |
| --- | --- |
| A bootstrap or bundle whose signature fails | The install stops, nothing changed. The fingerprint is compared with the paper sheet, not read from a tool's output |
| A tier whose card has no measured record (exit 3; no override) | Unchanged. Shown as "This card has not been measured for TrialBox. Call the vendor." |
| A PRODUCTION install with backups only on the box, or an anchor that cannot be mounted (10K-4) | Unchanged. Asked on the storage page and checked there, before anything is applied |
| The chart rule required in PRODUCTION; a named health-page person; the internal root confirmed (10K-21) | Unchanged. They become wizard fields |
| No TPM: the keys are sealed under a passphrase | Unchanged. The passphrase is asked in the wizard, never in the environment |
| The first-run code: five wrong tries void it; the first account closes the page | Unchanged |
| A baseline that would cut the SSH session in use | Unchanged. Shown as "This would end your remote session. Finish at the box's own screen." |
| A placeholder value on a PRODUCTION box | New, section 2.3 |
| Removing anything the installer did not make | Unchanged |

## 3. What this design does not do

- No change to any check's rule, any test's assertion, or any security setting. Only the way values are asked and
  messages are shown changes.
- Windows: the double-click already exists (`deploy/windows/Install-TrialBox.cmd`), and its messages are already in three
  languages. The long `wsl` lines after it are lane W's and are not cut here (question 2, section 6).
- Day-2 tasks (update, restore, decommission) are not designed here. The journey review's cards 53 to 58 cover them
  (`docs/reviews/2026-11-17-journey-and-simplicity.md`, section H).
- Real-hardware proof stays 10K-17 (a stranger follows the box form) and rc1 line 6. This design is what that
  stranger should meet.

## 4. Findings

The findings of this audit are in [`hospital-simple-install/findings.json`](hospital-simple-install/findings.json) (card U1, ten findings, six Medium and four Low), in the register's `--add-from` form.
The keeper adds them to the register.

## 5. The cards

They are ordered so that the earliest cards remove the most steps. "Removes" names the rows of section 1. Each card
is small or medium, and each names the test that proves it. The tests are new; no existing test changes what it
asserts.

| # | Card | Removes (rows) | Files | Owner lane | Size | The test that proves it |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **HS-1 One command.** A launcher at the stick's root checks the bootstrap's signature itself, shows the key's fingerprint for comparison with the sheet, and runs the box form. No `--pub`, `--`, `--tier`, `--answers` or mount path | 7, 8, 9, 10, 13, 53 | `deploy/bootstrap.sh`, `deploy/box-install.sh`, the media builder (`tools/windows_media.py`, `tools/make_bundle.sh`) | H | M | A run with only the stick's path on a fake host reaches the plan; a "no" to the fingerprint stops with nothing changed |
| 2 | **HS-2 Detect, then confirm once.** Tier from the card and the measured records; no-GPU form with its line; key back end from the TPM; `--gb10` for the host check; time zone from the host. One confirmation screen | 6, 10, 11, 12, 34, 37 (zone), 45, 63 | `deploy/install.sh`, `deploy/box-install.sh`, `tools/box/plan.py`, `deploy/check_host.sh` | H | M | For each fake card the plan names the tier, and an unmeasured card stops with its plain key and nothing changed; the existing tier tests stay as they are |
| 3 | **HS-3 No question after the start.** In box mode the installer never reads the terminal after the confirmation: the start prompt, the TLS, mailbox and ClinicalTrials.gov prompts and the finish gate move before the load or into the wizard | 15, 16, 17, 18, 19, 60 | `deploy/install.sh`, `deploy/box-install.sh` | H | S | An install in box mode with standard input closed reaches the first-run stage; the finish gate's refusal comes before the load |
| 4 | **HS-4 The wizard asks everything once.** Add the trial office's mailbox, the mail relay (with its secret stored as a secret), the certificate choice and the audit share; drop the second language choice; time zone and site id shown as derived | 2, 14, 20, 24, 36, 43, 54, 56, 57, 58 | `services/console/firstrun.py`, `services/console/templates/firstrun.html`, `services/console/i18n_firstrun.py` (K); `libs/tb_common/box_answers.py`, `tools/box/plan.py` (owner to confirm: question 1) | K, with H | M | After the wizard and `tools.box apply` on a fixture box, `doctor`'s named-choice, mail and time-zone checks pass with no file edited, and no FAIL line names `deploy/.env` |
| 5 | **HS-5 Plain installer messages.** Every stop line of `install.sh`, `box-install.sh`, `bootstrap.sh` and `box-prepare.sh` becomes a key in en, ja and zh-TW with one action; the detail goes to the install log; the closing lines say "add people on the Users page" and "the first read runs tonight", with no command | 21, 22, 25, 26, 28, 29 | the four scripts and one message catalogue beside them | H | M | A test reads every stop call in the four scripts and finds its key in all three catalogues; no shown line holds `TB_`, `deploy/.env`, `RUNBOOK §` or a D number |
| 6 | **HS-6 Check again from the page.** The first-run preflight runs from the page, line by line, with "Check again" and the detail kept for the support file (on 10K-3) | 59, 61, 27 | `services/console/firstrun.py`, `services/console/templates/firstrun.html` | K | S | A failing share in a fixture shows its ja line and action; fixing the fixture and pressing "Check again" turns it green with no shell |
| 7 | **HS-7 The hospital's page.** One install page for a hospital in three languages, with one command; the steps the installer does are removed; the vendor's and builders' steps move to the vendor's pages | 1, 3, 4, 5, 30, 31, 32, 33, 35, 39, 40, 41, 42, 44, 46, 51 | `docs/runbook/01-install-a-new-site.md`, `docs/runbook/16-box-install-rehearsal.md`, `docs/RUNBOOK.md`, `docs/handover/it-one-page.en.md` | H | M | A docs test counts the shell commands on the hospital's page (one) and finds no setting name; the runbook tests (`-k "runbook or planted or restore or findings"`) pass |
| 8 | **HS-8 Hide the expert surface.** `--help` shows the hospital's command only; `--help-expert` the rest; the network sheet written in plain words, with the setting names in an appendix | 29, 52, 62 | `deploy/install.sh`, `deploy/box-install.sh`, the network sheet's generator | H | S | `--help` output holds no `--rehearsal` and no `TB_`; `--help-expert` holds every flag the script parses |
| 9 | **HS-9 Placeholder data for a PoC.** "Fill with placeholder values" on a TEST or VALIDATION box; the synthetic hospital as the source; PRODUCTION refuses a placeholder | 3, 4, 55 (for a PoC), 50 | `libs/tb_common/box_answers.py`, `tools/box/plan.py`, `services/console/firstrun.py` | K, with H | S | A VALIDATION fixture box filled with placeholders reaches its first screening night on the synthetic hospital; the same answers with PRODUCTION are refused with the plain message |
| 10 | **HS-10 Plain doctor and finish check.** Every `doctor`, finish-check and host-check line gets a key in three languages and one action; a `trialbox` command that finds its own settings files | 27, 36, 38, 61 | `tools/trialbox/doctor.py`, `tools/trialbox/finish_check.py`, `tools/trialbox/__main__.py`, `deploy/check_host.sh`, `pyproject.toml` | H | M | Every check name has en, ja and zh-TW text; `trialbox doctor` with no option on an installed fixture reads `deploy/.env` and `deploy/settings.yaml` |
| 11 | **HS-11 Study details once.** The IRB number entered once and shown on the three pages; the delegation log takes the account's name; site staff taken from the accounts, not typed again; who to screen picked from the staff list; the SAE set chosen from the country; the PI-first order said on the approval page | 67, 68, 69, 71, 72, 76 | `services/console/team.py`, `services/console/study_setup.py`, `services/console/approval.py` and their templates | K | M | A console walk of a new study from a synthetic protocol to "ready to screen" counts the fields typed and is at or below the target written in the test; the IRB number typed once shows on all three pages |
| 12 | **HS-12 Read from the protocol.** Identifiers and the visit schedule filled from the compiled protocol, to confirm | 65, 74 | `services/console/study_setup.py`, `services/console/lifecycle_pages.py` and templates | K | M | The synthetic protocol's sponsor, number and visits appear filled on the state and schedule pages with no typing |
| 13 | **HS-13 Plain console refusals.** The protocol, set-up, team and EDC refusals become catalogue keys; the raw code moves to the support file | 64, 73 | `services/console/app.py`, `services/console/study_setup.py`, `services/console/team.py`, `services/console/templates/setup.html` | K | S | A test posts each refused form in ja and finds no English reason and no raw code on the page |
| 14 | **HS-14 One EDC connection per box.** The address and key asked once (wizard page or admin), picked by name everywhere else; the version read, not asked | 48, 70, 75 | `services/console/study_setup.py`, `services/console/data_pages.py`, `services/console/edc_pages.py` and templates | K | M | One connection made once is offered on the set-up, sources, schedule and map pages, and no page asks its address again. Ring 4 (EDC); listed for completeness, not for ring 0 |

**Not in a card here:**

- Row 47 (the vendor's acceptance commands) and row 49 (terminology) are the vendor's.
- Row 66 (labels on ja and zh-TW pages) is a translation choice for the owner (question 3).
- Row 23 (the backup key made on a stick) is the key ceremony of 10K-13.

**Order and the steps it leaves.** These counts are from the rows each card removes; none has been tried on a box.

| After cards | Points left |
| --- | ---: |
| none | 76 |
| 1 to 3 | 57 |
| 1 to 7 | 22 |
| 1 to 10 | 17 |
| 1 to 13 | 7 (rows 47 and 49, the vendor's; 66, the owner's question; 23, card 10K-13; 48, 70 and 75, card 14) |

Card 14 is ring 4. "Points left" counts today's friction. The 19 steps of section 2.1 are what a person still does,
and they include no typed command but the first, no file edit and no technical message.

## 6. Questions for the integrator

1. **Who owns `libs/tb_common/box_answers.py` and `tools/box/plan.py`?** They are shared by lane K's first-run page
   and lane H's installer. Cards 4 and 9 need a change to their bodies. This design assumes lane H, with lane K naming
   the fields. Lane R owns the terminal wizard (`tools/settings_wizard.py`), which this design takes off the hospital's
   path but does not change.
2. **Lane W:** should the Windows path's steps after the double-click follow card 1's form?
3. **The owner:** should a ja or zh-TW page keep asking a short label per criterion (row 66), or take the English
   label until someone writes one?
