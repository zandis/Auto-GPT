# The install's questions, cut: card U-5, part 1b

**Reader:** the integrator and the owner, then whoever builds part 2.
**Card:** U-5 (lane U), part 1b. Docs only; nothing was run.
**Master read:** `b6d79842`.
**Ruling:** the owner's, as the integrator relayed it (#639, after 7105989411):

- **The flow.** Four questions, then the install starts. While it runs, the same screen shows the rest, so they are
  answered while waiting. The answers apply when the install ends. Anything unanswered goes to "Information still
  needed", and nothing waits on it.
- **The cut.** Each question meets the rules in this order: drop it if nothing reads it; detect it from the machine
  or the network; derive it from another answer; give it a default the person only confirms; merge it with its kin
  into one small form; defer it to the step that needs it.
- **The target.** At most 12 questions during the install, each with a default filled in.

**Builds on** part 1 (#1408, `install-first-information-after.md`), which is not yet on master.

**Where the evidence comes from.** For each answer, "Read by" names a reader at run time, outside the wizard, its
schema, the tests and the docs. It comes from a read of the tree; nothing was run.

## 日本語の要約

- 今日の端末の経路は **57 問**です：ウィザード 53 問、インストーラーの途中の質問 4 問。
- これを **12 問**にします。最初の 4 問の後にインストールが始まり、残りはインストール中の同じ画面で聞きます。12 問すべてに既定値が入っていて、確認するだけです。
- 57 問のそれぞれに、次の規則を一つ当てます：
  - 何も読まないので削除
  - 機械やネットワークから検出
  - 他の答えから導出
  - 既定値
  - 似たものをまとめて一つの小さなフォームに
  - それを必要とする手順まで後回し（「まだ必要な情報」ページ）
- 安全のための停止はそのままです。

## 繁體中文摘要

- 現行的終端機路徑有 **57 題**：精靈 53 題，加上安裝程式中途的提問 4 題。
- 縮減為 **12 題**：前 4 題答完就開始安裝，其餘在安裝進行中、同一畫面上詢問。12 題都已預填預設值，只需確認。
- 57 題各套用以下其中一條規則：
  - 沒有程式讀取，直接刪除
  - 由機器或網路偵測
  - 由其他答案推導
  - 給預設值
  - 同類合併為一個小表單
  - 延到需要它的步驟（「尚需填寫的資料」頁面）
- 安全性停止全部保留。

## 1. After: the 12 questions

**Before the install starts (A).** These are asked first; the install cannot run without them.

| # | Question | Default filled in | The fields it replaces |
| ---: | --- | --- | --- |
| A1 | Is this the machine? (the line about the card, memory and security chip) | Yes | `deploy/box-install.sh:130` |
| A2 | The screen language | the media's language, else the browser's | `locale`; the first-run language |
| A3 | The time zone | the host's zone | `tz`; the first-run tz |
| A4 | Your account: full name, user name, mail, password twice, authenticator code | the user name from the mail's local part | the owner fields |

The key passphrase, twice, is asked inside A4's form, and only when the board has no TPM. It is not a separate
question.

**While the install runs (B).** The same screen shows these, and the install does not wait for them. An unanswered
one keeps its default or goes to the page.

| # | Question | Default filled in | The fields it replaces |
| ---: | --- | --- | --- |
| B1 | The hospital's name | "TrialBox" (marked as a placeholder) | `site_name` |
| B2 | The box's name on the network | the host name | `box_name`, `tls_hostname`, `console_url` |
| B3 | Where the records come from: the kind and the folder (or "the sample hospital for now") | the country's kind (SS-MIX2 in Japan, CSV in Taiwan); a detected mounted storage, else the sample hospital | `data_source_type`, `data_source_host_dir`, the first-run source and SS-MIX2 root |
| B4 | How a chart number is written: one example, as printed | read from the first records when the folder is there, else "as written" | `chartno_rule`, the first-run kind and width |
| B5 | Storage: where backups go; the audit share | a detected second disk or mounted share; else "on this machine for now" | backup kind, disk, share and folder; `anchor_dir`; `log_dir` (default) |
| B6 | Mail and notices: the mail relay; the trial office's mailbox; who reads the backup alarm | the relay found in the network, else "no mail for now"; the owner's mail; the owner | `smtp_host`, `smtp_port`, `sae_office_mailbox`, `health_page_person` |
| B7 | The certificate: the box's own, or the hospital's two files; if the box's own, who pushed its root to the clinic PCs | the box's own | `tls_mode`, `tls_cert_file`, `tls_key_file`, `tls_root_confirmed_by` |
| B8 | Opening the box for staff: done now, or later | later | none today; it records that the five steps below wait for go-live |

**Count: 12** (A1 to A4, B1 to B8). Every one has its default filled in.

B8 is optional to show; without it the count is 11. It makes the go-live gate visible from the first screen.

## 2. Before and after: every question today, with its rule

**The rules:** drop, detect, derive, default, merge, defer. The first rule that fits is the one named.

**Where the questions are.** Wizard lines are in `tools/settings_wizard.py`. The installer's lines are in
`deploy/install.sh` on master `b6d79842`; they have moved since part 1 was written.

### 2.1 The terminal wizard: 53 entries

| Line | Question | Read by | Rule | After |
| ---: | --- | --- | --- | --- |
| 60 | country | nothing: run time uses `country_of(tz)` (`libs/tb_common/committees.py:71`) | drop | – |
| 61 | site_id | `services/adapter/dual_write.py:111` | derive | from the name (`tools/box/plan.py:391`) |
| 62 | site_name | `services/orchestrator/scenarios/feas.py:103` | default | B1 |
| 63 | tz | `libs/tb_common/config.py:50` | detect | A3 |
| 64 | locale | `services/orchestrator/core.py:653` | merge | A2 |
| 67 | printed_dates | `libs/tb_common/dates.py:326` | derive | from the country of the zone |
| 73 | year_basis | `libs/tb_common/dates.py:327` | derive | as above |
| 78 | contact | `services/orchestrator/core.py:671` | derive | the owner's mail (A4) |
| 79 | internal_domains | `services/orchestrator/core.py:606` | derive | the domain of the owner's mail |
| 80 | intake_address | `services/mail_gateway/gateway.py:403` | derive | `trialbox@` that domain |
| 81 | senders | `libs/tb_common/authz.py:21` | derive | the owner's mail |
| 82 | physicians | `libs/tb_common/authz.py:22` | derive | as above; the console's accounts later |
| 83 | reviewers | `libs/tb_common/authz.py:24` | derive | as above |
| 84 | alliance_sites | `libs/tb_common/authz.py:23` | default | none; the page (ring 3) |
| 85 | data_source_type | `services/adapter/cli.py:208` | merge | B3 |
| 87 | data_source_path | `services/adapter/cli.py:207` | derive | a constant (`tools/box/plan.py:60`) |
| 94 | data_source_host_dir | `deploy/docker-compose.yml:305` | merge | B3 |
| 103 | ssmix2 order numbers | `services/adapter/sources/ssmix2/source.py:117` | defer | the first SS-MIX2 night: found by reading the storage, else asked there |
| 106 | data_source_dsn_env | `services/adapter/cli.py:59` | derive | a constant |
| 107 | mapping | `services/adapter/mapping/site.py:44` | derive | the country and the source kind (`tools/box/plan.py:427`) |
| 108 | mrn_regex | `services/orchestrator/scenarios/case.py:184` | derive | the chart rule (`tools/box/plan.py:403`) |
| 111 | chartno_rule | `libs/tb_common/chartno.py:93` | merge | B4 |
| 116 | registry_type | `services/orchestrator/scenarios/cohort.py:152` | default | none |
| 117 | registry_path | `services/adapter/cli.py:58` | default | none |
| 118 | departments | no reader of the settings key found | drop | – (departments come from the records) |
| 119 | practitioners | `services/orchestrator/scenarios/screen.py:449` | defer | "who to screen" by doctor, picked from the records' names |
| 120 | llm_mode | `libs/tb_common/config.py:190` | detect | the card |
| 121 | cloud_enabled | `libs/tb_common/llm.py:301` | default | no; the page |
| 123 | attachment_encryption | `services/mail_gateway/gateway.py:170` | default | link |
| 124 | console_url | `services/mail_gateway/gateway.py:347` | derive | from B2 |
| 125 | twpas_enabled | `services/orchestrator/scenarios/twpas.py:50` | default | off; the page (Taiwan only) |
| 126 | twpas_org_id | `services/orchestrator/scenarios/twpas.py:103` | defer | when TWPAS is turned on |
| 127 | alliance_root | `services/orchestrator/scenarios/cohort.py:310` | default | no; the page (ring 3) |
| 128 | alliance_root_address | `services/orchestrator/scenarios/cohort.py:340` | defer | as above |
| 129 | cohort_rulesets | `services/orchestrator/scheduler.py:402` | default | every approved one |
| 130 | smtp_host | `services/mail_gateway/app.py:45` | detect | the domain's mail exchanger, probed; shown in B6 |
| 131 | smtp_port | `services/mail_gateway/app.py:45` | detect | probed (587, 465, 25) |
| 132 | imap_host | `services/mail_gateway/gateway.py:453` | defer | reading request mail: found from the domain, else asked there |
| 133 | imap_port | `services/mail_gateway/gateway.py:453` | detect | probed (993, 143) |
| 134 | imap_user | `services/mail_gateway/gateway.py:456` | derive | the local part of the intake address |
| 135 | mta_authserv_id | `services/mail_gateway/app.py:34` | defer | reading request mail: read from a test mail's header, then confirmed |
| 137 | tls_hostname | `services/console/identity.py:172` | derive | from B2 |
| 139 | sae_office_mailbox | `services/console/sae_pages.py:220` | merge | B6 (the owner's mail by default) |
| 142 | new_year_break | `libs/tb_common/workdays.py:48` | derive | the country's default (wizard :832) |
| 146 | tls_mode | `services/console/identity.py:171` | merge | B7 |
| 151 | tls_cert_file | `services/console/identity.py:182` | merge | B7 |
| 152 | tls_key_file | `services/console/identity.py:183` | merge | B7 |
| 155 | retention_rules | nothing: it only picks the default days | drop | – |
| 160 | logs_days | `tools/trialbox/platform_day2.py:446` | default | the rules' |
| 161 | mail_log_days | `services/orchestrator/scenarios/retention.py:187` | default | the rules' |
| 163 | outputs_days | `services/orchestrator/scenarios/retention.py:34` | default | the rules' |
| 164 | attachments_days | `services/orchestrator/scenarios/retention.py:34` | default | the rules' |
| 166 | ctgov_mode | `services/criteria_compiler/ctgov.py:221` | detect | the installer's reachability probe (`deploy/install.sh:273`) |

### 2.2 The installer's prompts: 4

| Line | Question | Rule | After |
| ---: | --- | --- | --- |
| 656 | ClinicalTrials.gov offline or live | detect | the probe |
| 784 | the console's DNS name | derive | from B2 |
| 810 | the trial office's mailbox | merge | B6 |
| 1062 | "Start the stack now?" | drop | an install starts |

### 2.3 The first-run page

Every field maps to A1 to A4 or B1 to B8, or is derived as in section 2.1. Its backup disk and share fields are not
stored; only the folder is (`tools/box/plan.py:538`), so they merge into B5's one choice.

### 2.4 The count

| Rule | Questions | Which (wizard key, or installer prompt) |
| --- | ---: | --- |
| drop | 4 | country, departments, retention_rules; the prompt "Start the stack now?" |
| detect | 7 | tz, llm_mode, smtp_host, smtp_port, imap_port, ctgov_mode; the ClinicalTrials.gov prompt |
| derive | 18 | site_id, printed_dates, year_basis, contact, internal_domains, intake_address, senders, physicians, reviewers, data_source_path, data_source_dsn_env, mapping, mrn_regex, console_url, imap_user, tls_hostname, new_year_break; the DNS name prompt |
| default | 13 | site_name (shown as B1), alliance_sites, registry_type, registry_path, cloud_enabled, attachment_encryption, twpas_enabled, alliance_root, cohort_rulesets, logs_days, mail_log_days, outputs_days, attachments_days |
| merge | 9 | locale, data_source_type, data_source_host_dir, chartno_rule, sae_office_mailbox, tls_mode, tls_cert_file, tls_key_file; the mailbox prompt |
| defer | 6 | ssmix2 order numbers, practitioners, twpas_org_id, alliance_root_address, imap_host, mta_authserv_id |
| **total** | **57** | 53 wizard entries and 4 installer prompts |

Some of these are still shown, with their default, as one of the 12: tz (A3), locale (A2), site_name (B1), and the
merged groups behind B3, B4, B6 and B7.

**Before: 57 on the terminal route** (53 wizard entries and 4 installer prompts; part 1 said "about 55"), and 24
fields on the first-run route. **After: 12**, all with a default.

## 3. What part 2 needs for the cut, beyond part 1's cards

1. **Detection that is not built yet:**
   - the mail relay and its port from the domain and a probe;
   - the IMAP port by probe;
   - a chart number's form from the first records;
   - the mounted storage for backups, the audit share and an SS-MIX2 root.

   Each is a body change in `tools/box/plan.py` (`detect`), with a test on a fixture host.
2. **The screen that asks B1 to B8 while the install runs.** The first-run page today opens only after the install
   (the code is shown at the end). It needs to open as soon as the console image is loaded, while the rest loads.
   This changes the order in `deploy/box-install.sh` and `deploy/install.sh`. Both wait for V-18 and H-99 (the
   integrator's order).
3. **The terminal route.** `tools/settings_wizard.py` keeps its questions for the vendor and for an unattended
   install, unchanged. The hospital's path no longer runs it interactively; it is fed the answers the screen
   collected, as `tools/box/plan.py` already does.

## 4. Questions

1. Is B8 kept, which makes 12, or dropped, which makes 11?
2. Should the trial office's mailbox default to the owner's mail (B6)? The owner would then receive the pseudonymous
   SAE notice until the office's mailbox is given. The alternative is no default, with the item on the page.
3. Should B4 read the chart-number form from the first records when the folder is already there? It reads only the
   form of the number (its width, digits or hexadecimal), never a value it keeps.
