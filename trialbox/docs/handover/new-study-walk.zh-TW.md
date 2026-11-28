# 從第一步開始的新試驗：給測試人員的操作步驟

**Reader:** the box owner and the trial team（在 steps 模式預覽機上測試的人員）。

本頁以四個人的身分，從第一步開始走完一個新試驗：研究協調員、資料管理員、成為本試驗試驗主持人（PI）的主持人，以及管理者。
這是自動化瀏覽器操作（D-1121）的人工版本。下方各步驟的表格由該自動化操作的計畫依主控台本身的訊息目錄寫出，
因此連結與按鈕文字就是產品以英文、中文（台灣）與日文顯示的文字。本頁與自動化操作不一致時，測試會失敗。

## 開始之前

- 機器處於 steps 模式（D-1062）：示範模式關閉，因此可以貼上計畫書。它只執行測試用模型（stub）與合成醫院。
  只貼上合成或公開的文字；絕不貼上真實病人的紀錄。
- 需要四個帳號：研究協調員、資料管理員、主持人與管理者。每人一個帳號並切換執行角色（D-1063）目前尚未在機器上；
  上線後，同一人在每個步驟前切換角色。
- 選一個新的條件代碼：1 到 16 個大寫英文字母、數字、「-」或「_」，且機器上尚未存在。表格中以 `MYSTUDY` 表示。
  不要使用 `SITE5B` 或以 `SITE5B-` 開頭的代碼：stub 在該代碼下看過這段文字，而本操作要看的是它沒看過的文字。
- 新試驗從「準備中」開始（D-1153）：收案中之前不產生名單，且要先有 SAE 通報類型才能改為收案中（D-415）。步驟 9 在
  試驗設定（「SAE 通報規定」）選擇類型；步驟 10 先執行 SCREEN，作業失敗並附原因，再將試驗改為收案中並再執行一次 SCREEN。
- 每個步驟都註明角色。以該角色登入（或切換到該角色），再依步驟的表格操作。表格中出現 `pi` 時，選擇主持人的帳號。
- 步驟中「被拒絕」列出該角色不得執行的請求。您會看到按鈕不存在，或自行開啟該網址時出現「這個頁面需要其他角色」頁面。

## 要貼上的計畫書文字

SITE5B 計畫書的收案條件，與建置檢查貼上的相同（`tools/e2e_simple.py`，`SITE_CRITERIA`）：

```text
Inclusion Criteria
1. Aged 18 years or older.
2. Diagnosis of gout (ICD-10-CM M10 or M1A).
3. Most recent serum urate in the last year at least 7.0 mg/dL.

Exclusion Criteria
1. Any history of malignancy.
```

## 步驟

<!-- new-study-walk: steps, written by tests/e2e/new_study_walk_plan.py; do not edit by hand -->

### 步驟 1 · 研究護理師（CRC）

登入並選擇頁面語言。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 以您的使用者名稱和密碼登入 | Sign in | 登入 | ログイン |
| 選擇語言，然後點選 | Language / Change | 語言 / 切換 | 言語 / 変更 |

應看到: 您的工作頁面。

### 步驟 2 · 研究護理師（CRC）

開啟計畫書頁面。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 開啟選單，然後點選 | More → Protocol | 更多 → 計畫書 | その他 → プロトコル |

應看到: 貼上計畫書收案條件的頁面。

### 步驟 3 · 研究護理師（CRC）

輸入新的條件代碼，貼上 SITE5B 的收案條件（見下方），然後送出。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 在此欄輸入 `MYSTUDY` | New ruleset id (e.g. GZQO-DEMO) | 新的納入／排除條件代碼（例如 GZQO-DEMO） | 新しい選択・除外基準 ID（例：GZQO-DEMO） |
| 在此欄輸入 `SITE5B` | Or paste the criteria | 或貼上收案條件 | または基準を貼り付ける |
| 點選 | Compile | 讀取 | 読み込み |

應看到: 作業頁面：新代碼的 FEAS，版本 1.0.0，等待核准。

### 步驟 4 · 研究護理師（CRC）

開啟核准頁面。可以查看，但不能核准。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 點選 | Open the approval page | 開啟核准頁面 | 承認ページを開く |

應看到: 四條條件：一條由固定篩選，三條由人員確認。沒有核准按鈕。

- 研究護理師（CRC）: 研究協調員不能核准: `POST /pilot/jobs/<job>/approve` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- 研究護理師（CRC）: 研究協調員不能登記主持人: `POST /studies/MYSTUDY/team` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 步驟 5 · 試驗主持人／協同主持人

以主持人身分：開啟等待核准的條件。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 以您的使用者名稱和密碼登入 | Sign in | 登入 | ログイン |
| 選擇語言，然後點選 | Language / Change | 語言 / 切換 | 言語 / 変更 |
| 在上方列點選 | This week's patients | 本週病人 | 今週の患者 |
| 點選 | Criteria waiting for your approval: MYSTUDY v1.0.0 | 等待您核准的條件：MYSTUDY v1.0.0 | 承認待ちの基準：MYSTUDY v1.0.0 |

應看到: 目前沒有人能核准：授權紀錄表尚未記載主持人。

- 試驗主持人／協同主持人: 管理員登記主持人之前，沒有人能核准: `POST /pilot/jobs/<job>/approve` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- 試驗主持人／協同主持人: 主持人不能送出計畫書: `POST /pilot/protocol` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 步驟 6 · 資料管理員

以資料管理員身分：在授權紀錄表上登記主持人為本試驗的試驗主持人。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 以您的使用者名稱和密碼登入 | Sign in | 登入 | ログイン |
| 選擇語言，然後點選 | Language / Change | 語言 / 切換 | 言語 / 変更 |
| 點選 | MYSTUDY: name the principal investigator | MYSTUDY：登記試驗主持人 | MYSTUDY：治験責任医師を登録する |
| 在此欄選擇 `pi` | TrialBox account | TrialBox 帳號 | TrialBox アカウント |
| 在此欄選擇 `pi` | Role | 角色 | 役割 |
| 在此欄輸入 `2025-06-01` | GCP training | GCP 訓練 | GCP 研修 |
| 點選 | Add and sign | 加入並簽署 | 追加して署名 |

應看到: 紀錄已加入並簽署；待辦事項消失。

- 資料管理員: 資料管理員不能啟動執行: `POST /pilot/request` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 步驟 7 · 試驗主持人／協同主持人

以主持人身分：逐列開啟確認，然後全部核准。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 在上方列點選 | This week's patients | 本週病人 | 今週の患者 |
| 點選 | Criteria waiting for your approval: MYSTUDY v1.0.0 | 等待您核准的條件：MYSTUDY v1.0.0 | 承認待ちの基準：MYSTUDY v1.0.0 |
| 僅中文與日文頁面：為每條條件加上簡短標籤，然後點選 | Save labels and ticks | 儲存標籤與確認 | 表示名と確認を保存 |
| 在每一黃色列打開代碼並勾選 | I have read this row | 我已看過這一列 | この行を確認しました |
| 點選 | Approve all | 全部核准 | すべて承認 |
| 點選 | Yes, do it | 是，執行 | はい、実行します |

應看到: 先出現確認頁面，然後 APPROVE 作業完成。

### 步驟 8 · 研究護理師（CRC）

對新試驗執行 FEAS。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 開啟選單，然後點選 | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| 在此按鈕的表單中選擇 `MYSTUDY`，然後點選 | Count eligible patients | 統計合格病人數 | 適格患者数を集計 |

應看到: FEAS 作業完成，附四條條件的篩選漏斗。

### 步驟 9 · 研究護理師（CRC）

開啟試驗的報告，再開啟試驗設定，在篩選對象選擇全院。接著開啟試驗狀態：試驗為準備中，在選定 SAE 通報類型之前無法改為收案中。回到試驗設定，在 SAE 通報規定選擇類型並儲存。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 在上方列點選 | Reports | 報告 | レポート |
| 在該試驗的列點選 | Open report | 開啟報告 | レポートを開く |
| 開啟選單，然後點選 | More → MYSTUDY · Study set-up | 更多 → MYSTUDY · 試驗設定 | その他 → MYSTUDY · 試験の設定 |
| 選擇 | The whole hospital: every patient with a booked appointment in the coming months or a visit in the last 12 months | 全院：未來數個月有預約，或過去 12 個月內有就診的所有病人 | 病院全体：今後数か月に予約がある、または過去12か月に受診したすべての患者 |
| 點選 | Save who to screen | 儲存篩選對象 | スクリーニングの対象を保存 |
| 點選 | Study state and identifiers | 試驗狀態與識別編號 | 試験の状態と識別番号 |
| 在此欄選擇 `open` | Move to | 變更為 | 変更先 |
| 點選 | Change state | 變更狀態 | 状態を変更 |
| 點選 | Study set-up | 試驗設定 | 試験の設定 |
| 在此欄選擇 `tw_trial` | Rule set | 規定 | 規定 |
| 點選 | Save and confirm | 儲存並確認 | 保存して確認 |

應看到: 篩選對象：全院。試驗為準備中；改為收案中被拒絕，訊息請您先到設定頁面；之後試驗已有 SAE 通報類型。

- 試驗主持人／協同主持人: 主持人不能選擇 SAE 通報類型: `POST /studies/MYSTUDY/setup/sae` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- 資料管理員: 資料管理員不能選擇 SAE 通報類型: `POST /studies/MYSTUDY/setup/sae` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 步驟 10 · 研究護理師（CRC）

對新試驗執行 SCREEN：試驗尚未收案，作業失敗。在試驗狀態頁面將試驗改為收案中，再執行一次 SCREEN，約需一分鐘。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 開啟選單，然後點選 | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| 在此按鈕的表單中選擇 `MYSTUDY`，然後點選 | Find candidates for the next visits | 找出近期回診的候選者 | 次回受診の候補者を抽出 |
| 在上方列點選 | Reports | 報告 | レポート |
| 在該試驗的列點選 | Open report | 開啟報告 | レポートを開く |
| 開啟選單，然後點選 | More → MYSTUDY · Study set-up | 更多 → MYSTUDY · 試驗設定 | その他 → MYSTUDY · 試験の設定 |
| 點選 | Study state and identifiers | 試驗狀態與識別編號 | 試験の状態と識別番号 |
| 在此欄選擇 `open` | Move to | 變更為 | 変更先 |
| 點選 | Change state | 變更狀態 | 状態を変更 |
| 開啟選單，然後點選 | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| 在此按鈕的表單中選擇 `MYSTUDY`，然後點選 | Find candidates for the next visits | 找出近期回診的候選者 | 次回受診の候補者を抽出 |

應看到: 第一個 SCREEN 作業失敗並附原因（試驗尚未收案；由研究協調員變更狀態）。試驗已收案。第二個 SCREEN 作業完成，附名單。

- 資料管理員: 資料管理員不能將試驗改為收案中: `POST /studies/MYSTUDY/state` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- 管理者: 管理者不能將試驗改為收案中: `POST /studies/MYSTUDY/state` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 步驟 11 · 研究護理師（CRC）

閱讀新試驗的候選者名單。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 在上方列點選 | This week's patients | 本週病人 | 今週の患者 |
| 點選 | MYSTUDY | MYSTUDY | MYSTUDY |
| 點選 | Candidates | 全院候選者 | 院内の候補者 |

應看到: 全院候選者與人數。

- 管理者: 管理者不能開啟候選者名單: `GET /studies/MYSTUDY/candidates` 被拒絕：403 與頁面 "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

<!-- new-study-walk: end of steps -->

## stub 模型如何處理沒看過的文字

本機器上的每個模型回答都來自 stub，`services/llm_stub/handlers.py`（機器以 `TB_LLM_MODE=stub` 執行；未設定模式的
DEV 或 TEST 機器在程序內執行同一個 stub，`services/console/studies.py`，`test_model_in_use`）。相同輸入得到相同回答，
且不呼叫機器以外的任何服務。

- 讀取收案條件（`ir_extract`）：stub 會在 `services/llm_stub/cassettes/ir_extract/<id>.json` 尋找該條件代碼的
  錄製回答，或尋找新代碼以「代碼-」開頭的那一個。新代碼沒有，因此每一行都交給 `_heuristic_criterion`。
- `_heuristic_criterion` 只認得少數樣式：BMI、eGFR、DAS28、HbA1c 與 serum urate（或 uric acid、sUA）後接比較符號
  （≥、>、≤、<）與數字，以及年齡（「aged 18 years or older」、「age ≥ 18」）。符合的行成為結構化資料上的固定篩選。
  其他行在篩選時交給人員確認，並附上問題「Confirm with the patient/clinician: 」與該行。簡短名稱是該行的前 40 個字元。
- 新代碼下的 SITE5B 文字因此得到一條篩選與三條由人員確認：年齡行符合；痛風那一行沒有樣式；尿酸那一行寫的是
  「at least 7.0」，沒有比較符號，所以不符合；惡性腫瘤那一行沒有樣式。核准頁面如此顯示（「4 條：固定篩選 1 · 模型判讀病歷 0 ·
  先篩選再判讀 0 · 由人員確認 3」），FEAS 只計算年齡行，尿酸行的名稱顯示為「Most recent serum urate in the last year」。
- 在代碼 `SITE5B` 下，stub 改用錄製的回答，四行全部是結構化條件。
- 概念對應到代碼（`concept_map`）：stub 選擇名稱與概念共用最多字詞的候選；沒有共用字詞時不選，並要求審閱。
- 讀取病歷（`judge`）：stub 只認得合成醫院病歷的句型（中文，以及機器列出日文時的日文）與記載的 BMI 或 HbA1c。
  其他文字一律回答「unknown」，病人進入待審閱，絕不會成為「不符合」。本操作中沒有任何條件是從病歷判讀。
- 頁面上每個從病歷讀出的回答都標示「測試用模型」。這裡沒有任何東西是在衡量真實模型。

## 如何執行本操作

- 測試人員：在預覽機上依上方步驟以人工操作。
- 自動化，在任何有本儲存庫的電腦上：`make walk-new-study`（在 `trialbox/` 中，先執行 `make venv`、`make fonts` 與
  `make jvm-deps`）。它在本機啟動 steps 模式的機器（`tools/demo.py`，與預覽 VM 相同），並在 Chromium 中操作三次，
  每種語言一次，各用自己的新代碼。機器建立資料約需 7 分鐘；每次操作約 70 秒。
- `TB_WALK_ACCOUNTS` 指定其他帳號（或一位切換執行角色的人）；`TB_WALK_BASE` 與 `TB_WALK_PASSWORD` 則操作一台已在
  執行的機器（說明見 `tests/e2e/test_new_study_walk.py`）。
- 步驟或產品文字改變後：`PYTHONPATH=libs:services:. .venv/bin/python -m tests.e2e.new_study_walk_plan --write`
  會重寫三個頁面的步驟表格。

## 出處

- D-1121（本操作）、D-1062（steps 模式）、D-1063（每人一個帳號並切換執行角色）、D-540（第一次核准前由資料管理員登記
  試驗主持人）、D-309（中文或日文頁面上每條條件的簡短名稱）、D-1153（新試驗從準備中開始）、D-415（有 SAE 通報類型才能
  改為收案中）、D-386（只有收案中的試驗產生名單）、D-1106（本操作依 D-1153 調整）。
- 自動化操作：`tests/e2e/new_study_walk_plan.py`、`tests/e2e/new_study_walk.js`、`tests/e2e/test_new_study_walk.py`。
