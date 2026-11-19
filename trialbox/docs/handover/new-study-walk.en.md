# A new study from its first step: the walk for testers

**Reader:** the box owner and the trial team, who test a preview box in steps mode.

This page walks one new study from its first step, as four people would: the study coordinator, the data steward,
the investigator who becomes the study's principal investigator (PI), and the administrator. It is the hand version
of an automated browser walk (D-1121). The step tables below are written by that walk's plan from the console's own
message catalogue, so the link and button texts are the ones the product shows, in English, Chinese (Taiwan) and
Japanese. A test fails when this page and the walk differ.

## Before you start

- The box is in steps mode (D-1062): demo mode is off, so a pasted protocol is accepted. It runs the stub model and
  the synthetic hospital only. Paste synthetic or public text only; never a real patient's record.
- You need four accounts: a study coordinator, a data steward, an investigator and an administrator. One sign-in per
  person with an acting role (D-1063) is not on the box yet; when it is, one person switches role before each step.
- Choose a new ruleset id: 1 to 16 capital letters, digits, "-" or "_", that the box does not have yet. The tables
  show it as `MYSTUDY`. Do not use `SITE5B` or an id that starts with `SITE5B-`: the stub has seen that text under
  that id, and the walk is about text it has not seen.
- A new study starts in start-up (D-1153): no list runs for it until it is open, and it opens only once it has its
  type for SAE reporting (D-415). Step 9 chooses that type on set-up (the "SAE reporting rules"); step 10 first runs
  SCREEN, which fails with the reason, then opens the study and runs SCREEN again.
- Each step names its role. Sign in as that role (or switch to it), then do what the step's table says. Where a
  table names `pi`, choose the investigator's account.
- Under "refused" a step names a request the role must not be able to make. You see it as a missing button, or as
  the page "This page needs another role" if you open the address yourself.

## The protocol text to paste

The SITE5B protocol's criteria, as the build gate pastes them (`tools/e2e_simple.py`, `SITE_CRITERIA`):

```text
Inclusion Criteria
1. Aged 18 years or older.
2. Diagnosis of gout (ICD-10-CM M10 or M1A).
3. Most recent serum urate in the last year at least 7.0 mg/dL.

Exclusion Criteria
1. Any history of malignancy.
```

## The steps

<!-- new-study-walk: steps, written by tests/e2e/new_study_walk_plan.py; do not edit by hand -->

### Step 1 · study coordinator

Sign in and choose the page language.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Sign in with your user name and password | Sign in | 登入 | ログイン |
| Choose the language, then click | Language / Change | 語言 / 切換 | 言語 / 変更 |

You should see: Your work page.

### Step 2 · study coordinator

Open the protocol page.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Open the menu, then click | More → Protocol | 更多 → 計畫書 | その他 → プロトコル |

You should see: The page to paste a protocol's criteria.

### Step 3 · study coordinator

Type a new ruleset id, paste the SITE5B criteria (below), and send them.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Type `MYSTUDY` into | New ruleset id (e.g. GZQO-DEMO) | 新的納入／排除條件代碼（例如 GZQO-DEMO） | 新しい選択・除外基準 ID（例：GZQO-DEMO） |
| Type `SITE5B` into | Or paste the criteria | 或貼上收案條件 | または基準を貼り付ける |
| Click | Compile | 讀取 | 読み込み |

You should see: A job page: FEAS for the new id at version 1.0.0, waiting for approval.

### Step 4 · study coordinator

Open the approval page. Look, but you cannot approve.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Click | Open the approval page | 開啟核准頁面 | 承認ページを開く |

You should see: Four criteria: one by a fixed filter, three by a person. No approve button.

- study coordinator: the coordinator cannot approve: `POST /pilot/jobs/<job>/approve` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- study coordinator: the coordinator cannot name the PI: `POST /studies/MYSTUDY/team` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### Step 5 · investigator (PI / sub-investigator)

As the investigator: open the criteria waiting for approval.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Sign in with your user name and password | Sign in | 登入 | ログイン |
| Choose the language, then click | Language / Change | 語言 / 切換 | 言語 / 変更 |
| In the top bar, click | This week's patients | 本週病人 | 今週の患者 |
| Click | Criteria waiting for your approval: MYSTUDY v1.0.0 | 等待您核准的條件：MYSTUDY v1.0.0 | 承認待ちの基準：MYSTUDY v1.0.0 |

You should see: Nobody can approve yet: the delegation log names no PI.

- investigator (PI / sub-investigator): nobody approves before the steward names the PI: `POST /pilot/jobs/<job>/approve` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- investigator (PI / sub-investigator): the investigator cannot send a protocol in: `POST /pilot/protocol` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### Step 6 · data steward

As the data steward: name the investigator as the study's PI on its delegation log.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Sign in with your user name and password | Sign in | 登入 | ログイン |
| Choose the language, then click | Language / Change | 語言 / 切換 | 言語 / 変更 |
| Click | MYSTUDY: name the principal investigator | MYSTUDY：登記試驗主持人 | MYSTUDY：治験責任医師を登録する |
| Choose `pi` in | TrialBox account | TrialBox 帳號 | TrialBox アカウント |
| Choose `pi` in | Role | 角色 | 役割 |
| Type `2025-06-01` into | GCP training | GCP 訓練 | GCP 研修 |
| Click | Add and sign | 加入並簽署 | 追加して署名 |

You should see: The entry is added and signed; the task is gone.

- data steward: the steward cannot start a run: `POST /pilot/request` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### Step 7 · investigator (PI / sub-investigator)

As the investigator: open each row to check, then approve all.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| In the top bar, click | This week's patients | 本週病人 | 今週の患者 |
| Click | Criteria waiting for your approval: MYSTUDY v1.0.0 | 等待您核准的條件：MYSTUDY v1.0.0 | 承認待ちの基準：MYSTUDY v1.0.0 |
| zh-TW and ja pages only: give each criterion a short label, then click | Save label | 儲存標籤 | 表示名を保存 |
| On each row that has it, click | Open | 開啟 | 開く |
| Click | Approve all | 全部核准 | すべて承認 |
| Click | Yes, do it | 是，執行 | はい、実行します |

You should see: A confirmation page, then the APPROVE job, done.

### Step 8 · study coordinator

Run FEAS on the new study.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Open the menu, then click | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| In the form of this button, choose `MYSTUDY`, then click | Count eligible patients | 統計合格病人數 | 適格患者数を集計 |

You should see: The FEAS job, done, with its funnel of the four criteria.

### Step 9 · study coordinator

Open the study's report, then its set-up, and choose the whole hospital under who to screen. Then open the study's state: it is in start-up, and Open is refused until the study has its type for SAE reporting. Back on set-up, choose the type under the SAE reporting rules and save it.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| In the top bar, click | Reports | 報告 | レポート |
| On the study's row, click | Open report | 開啟報告 | レポートを開く |
| Open the menu, then click | More → MYSTUDY · Study set-up | 更多 → MYSTUDY · 試驗設定 | その他 → MYSTUDY · 試験の設定 |
| Choose | The whole hospital: every patient with a booked appointment in the coming months or a visit in the last 12 months | 全院：未來數個月有預約，或過去 12 個月內有就診的所有病人 | 病院全体：今後数か月に予約がある、または過去12か月に受診したすべての患者 |
| Click | Save who to screen | 儲存篩選對象 | スクリーニングの対象を保存 |
| Click | Study state and identifiers | 試驗狀態與識別編號 | 試験の状態と識別番号 |
| Choose `open` in | Move to | 變更為 | 変更先 |
| Click | Change state | 變更狀態 | 状態を変更 |
| Click | Study set-up | 試驗設定 | 試験の設定 |
| Choose `tw_trial` in | Rule set | 規定 | 規定 |
| Click | Save and confirm | 儲存並確認 | 保存して確認 |

You should see: Who to screen: the whole hospital. The study is in start-up; Open is refused with words that send you to set-up; then the study has its type for SAE reporting.

- investigator (PI / sub-investigator): the investigator cannot choose the type for SAE reporting: `POST /studies/MYSTUDY/setup/sae` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- data steward: the steward cannot choose the type for SAE reporting: `POST /studies/MYSTUDY/setup/sae` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### Step 10 · study coordinator

Run SCREEN on the new study: it fails, since the study is not open yet. Open the study on its state page, then run SCREEN again. It takes about a minute.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| Open the menu, then click | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| In the form of this button, choose `MYSTUDY`, then click | Find candidates for the next visits | 找出近期回診的候選者 | 次回受診の候補者を抽出 |
| In the top bar, click | Reports | 報告 | レポート |
| On the study's row, click | Open report | 開啟報告 | レポートを開く |
| Open the menu, then click | More → MYSTUDY · Study set-up | 更多 → MYSTUDY · 試驗設定 | その他 → MYSTUDY · 試験の設定 |
| Click | Study state and identifiers | 試驗狀態與識別編號 | 試験の状態と識別番号 |
| Choose `open` in | Move to | 變更為 | 変更先 |
| Click | Change state | 變更狀態 | 状態を変更 |
| Open the menu, then click | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| In the form of this button, choose `MYSTUDY`, then click | Find candidates for the next visits | 找出近期回診的候選者 | 次回受診の候補者を抽出 |

You should see: The first SCREEN job failed with the reason (the study is not open; the coordinator changes the state). The study is open. The second SCREEN job, done, with its list.

- data steward: the steward cannot open the study: `POST /studies/MYSTUDY/state` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- administrator: the administrator cannot open the study: `POST /studies/MYSTUDY/state` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### Step 11 · study coordinator

Read the candidate list of the new study.

| What you do | en | zh-TW | ja |
| --- | --- | --- | --- |
| In the top bar, click | This week's patients | 本週病人 | 今週の患者 |
| Click | MYSTUDY | MYSTUDY | MYSTUDY |
| Click | Candidates | 全院候選者 | 院内の候補者 |

You should see: The candidates in the hospital, with their count.

- administrator: the administrator cannot open the candidate list: `GET /studies/MYSTUDY/candidates` refused: 403 and the page "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

<!-- new-study-walk: end of steps -->

## What the stub model does with text it has not seen

Every model answer on this box comes from the stub, `services/llm_stub/handlers.py` (the box runs
`TB_LLM_MODE=stub`; a DEV or TEST box with no mode set runs the same stub in process, `services/console/studies.py`,
`test_model_in_use`). It gives the same answer to the same input, and calls nothing outside the box.

- Reading the criteria (`ir_extract`): the stub looks for a recorded answer for the ruleset id in
  `services/llm_stub/cassettes/ir_extract/<id>.json`, or for an id the new one starts with followed by "-". A new id
  has none, so each line goes to `_heuristic_criterion`.
- `_heuristic_criterion` knows a few patterns: BMI, eGFR, DAS28, HbA1c and serum urate (or uric acid, sUA) followed
  by a comparison sign (≥, >, ≤, <) and a number, and an age ("aged 18 years or older", "age ≥ 18"). A line that
  matches becomes a fixed filter on the coded data. Any other line goes to a person at screening, with the question
  "Confirm with the patient/clinician: " and the line. The short label is the line's first 40 characters.
- For the SITE5B text under a new id this gives one filter and three lines for a person: the age line matches; the
  gout line names no pattern; the urate line says "at least 7.0" with no comparison sign, so it does not match; the
  malignancy line names no pattern. The approval page says so ("4 criteria: 1 by a fixed filter · 0 by the model on
  notes · 0 filter then notes · 3 by a person"), FEAS counts only the age line, and the urate line's label reads
  "Most recent serum urate in the last year".
- Under the id `SITE5B` the stub answers from its recorded cassette instead, and all four lines are coded.
- Mapping a concept to a code (`concept_map`): the stub picks the candidate whose name shares the most words with
  the concept; with no shared word it picks none and asks for review.
- Reading notes (`judge`): the stub knows only the sentence templates of the synthetic hospital's notes (Chinese, and
  Japanese when the box lists it) and a stated BMI or HbA1c. For any other text it answers "unknown", and the patient
  goes to review, never to "did not match". In this walk no criterion is read from notes.
- Pages mark every answer read from notes "test model". Nothing here measures a real model.

## How the walk is run

- By a tester: the steps above, by hand, on the preview box.
- Automated, on any computer with the repository: `make walk-new-study` (from `trialbox/`, after `make venv`, `make
  fonts` and `make jvm-deps`). It starts the steps-mode box locally (`tools/demo.py`, as the preview VM does) and
  walks the steps in Chromium three times, once per language, each under its own new id. The box takes about 7
  minutes to seed; each walk takes about 70 seconds.
- `TB_WALK_ACCOUNTS` names other accounts (or one person with an acting role); `TB_WALK_BASE` and
  `TB_WALK_PASSWORD` walk a box that is already running (`tests/e2e/test_new_study_walk.py` says how).
- After a change of the steps or of a product text: `PYTHONPATH=libs:services:. .venv/bin/python -m
  tests.e2e.new_study_walk_plan --write` rewrites the step tables of the three pages.

## Where this comes from

- D-1121 (this walk), D-1062 (steps mode), D-1063 (one sign-in with an acting role), D-540 (the steward names the PI
  before the first approval), D-309 (a short label per criterion on a Chinese or Japanese page), D-1153 (a new study
  starts in start-up), D-415 (it opens only with its type for SAE reporting), D-386 (lists only for an open study),
  D-1106 (the walk follows D-1153).
- The walk: `tests/e2e/new_study_walk_plan.py`, `tests/e2e/new_study_walk.js`, `tests/e2e/test_new_study_walk.py`.
