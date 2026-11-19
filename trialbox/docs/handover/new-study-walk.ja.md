# 最初の一歩からの新しい試験：テスター向けの操作手順

**Reader:** the box owner and the trial team（steps モードのプレビュー機でテストする人）。

このページは、新しい試験を最初の一歩から、4 人の立場で進めます：治験コーディネーター、データスチュワード、
試験の治験責任医師（PI）になる医師、管理者。自動化されたブラウザー操作（D-1121）の手作業版です。下の各手順の表は、
その自動操作の計画がコンソール自身のメッセージカタログから書き出したもので、リンクとボタンの文言は製品が英語・
中国語（台湾）・日本語で表示するとおりです。このページと自動操作が食い違うと、テストが失敗します。

## 始める前に

- 機械は steps モード（D-1062）です：デモモードがオフなので、プロトコルを貼り付けられます。テスト用モデル（stub）と
  合成病院だけで動きます。貼り付けるのは合成または公開の文章だけにし、実在の患者の記録は決して貼り付けません。
- アカウントが 4 つ必要です：治験コーディネーター、データスチュワード、医師、管理者。1 人 1 アカウントで役割を切り替える
  仕組み（D-1063）はまだ機械にありません。入ったあとは、同じ人が各手順の前に役割を切り替えます。
- 新しい基準 ID を決めます：大文字の英字・数字・「-」・「_」で 1〜16 文字、機械にまだないもの。表では `MYSTUDY` と
  示します。`SITE5B` や `SITE5B-` で始まる ID は使いません：stub はその ID でこの文章を見たことがあり、この操作は
  stub が見たことのない文章についてのものです。
- 新しい試験は「準備中」から始まります（D-1153）：募集中になるまでリストは作られず、SAE 報告の種類を選ぶまで募集中に
  できません（D-415）。手順 9 で設定（「SAE の報告規定」）から種類を選び、手順 10 ではまず SCREEN を実行して理由付きで
  失敗するのを確かめ、試験を募集中にしてからもう一度 SCREEN を実行します。
- 各手順に役割があります。その役割でログイン（または切り替え）し、表のとおりに操作します。表に `pi` とあれば、医師の
  アカウントを選びます。
- 「拒否される」には、その役割ができてはならない操作を挙げています。ボタンがないこと、または自分でそのアドレスを開くと
  「このページには別の役割が必要です」のページが出ることで確かめます。

## 貼り付けるプロトコルの文章

SITE5B プロトコルの基準。ビルド時の検査が貼り付けるものと同じです（`tools/e2e_simple.py`、`SITE_CRITERIA`）：

```text
Inclusion Criteria
1. Aged 18 years or older.
2. Diagnosis of gout (ICD-10-CM M10 or M1A).
3. Most recent serum urate in the last year at least 7.0 mg/dL.

Exclusion Criteria
1. Any history of malignancy.
```

## 手順

<!-- new-study-walk: steps, written by tests/e2e/new_study_walk_plan.py; do not edit by hand -->

### 手順 1 · CRC

ログインし、画面の言語を選びます。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| ユーザー名とパスワードでログイン | Sign in | 登入 | ログイン |
| 言語を選び、次をクリック | Language / Change | 語言 / 切換 | 言語 / 変更 |

表示されるもの: あなたの作業ページ。

### 手順 2 · CRC

プロトコルのページを開きます。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| メニューを開き、次をクリック | More → Protocol | 更多 → 計畫書 | その他 → プロトコル |

表示されるもの: プロトコルの基準を貼り付けるページ。

### 手順 3 · CRC

新しい基準 ID を入力し、SITE5B の基準（下記）を貼り付けて送ります。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 次の欄に `MYSTUDY` を入力 | New ruleset id (e.g. GZQO-DEMO) | 新的納入／排除條件代碼（例如 GZQO-DEMO） | 新しい選択・除外基準 ID（例：GZQO-DEMO） |
| 次の欄に `SITE5B` を入力 | Or paste the criteria | 或貼上收案條件 | または基準を貼り付ける |
| クリック | Compile | 讀取 | 読み込み |

表示されるもの: ジョブのページ：新しい ID の FEAS、バージョン 1.0.0、承認待ち。

### 手順 4 · CRC

承認ページを開きます。見ることはできますが、承認はできません。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| クリック | Open the approval page | 開啟核准頁面 | 承認ページを開く |

表示されるもの: 4 件の基準：固定フィルター 1 件、担当者 3 件。承認ボタンはありません。

- CRC: 治験コーディネーターは承認できない: `POST /pilot/jobs/<job>/approve` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- CRC: 治験コーディネーターは責任医師を登録できない: `POST /studies/MYSTUDY/team` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 手順 5 · 治験責任医師／分担医師

治験責任医師として：承認待ちの基準を開きます。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| ユーザー名とパスワードでログイン | Sign in | 登入 | ログイン |
| 言語を選び、次をクリック | Language / Change | 語言 / 切換 | 言語 / 変更 |
| 上部のバーでクリック | This week's patients | 本週病人 | 今週の患者 |
| クリック | Criteria waiting for your approval: MYSTUDY v1.0.0 | 等待您核准的條件：MYSTUDY v1.0.0 | 承認待ちの基準：MYSTUDY v1.0.0 |

表示されるもの: まだ誰も承認できません：リストに責任医師がいません。

- 治験責任医師／分担医師: データスチュワードが責任医師を登録するまで誰も承認できない: `POST /pilot/jobs/<job>/approve` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- 治験責任医師／分担医師: 治験責任医師はプロトコルを送れない: `POST /pilot/protocol` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 手順 6 · データ管理責任者

データスチュワードとして：リストで治験責任医師を登録します。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| ユーザー名とパスワードでログイン | Sign in | 登入 | ログイン |
| 言語を選び、次をクリック | Language / Change | 語言 / 切換 | 言語 / 変更 |
| クリック | MYSTUDY: name the principal investigator | MYSTUDY：登記試驗主持人 | MYSTUDY：治験責任医師を登録する |
| 次の欄で `pi` を選択 | TrialBox account | TrialBox 帳號 | TrialBox アカウント |
| 次の欄で `pi` を選択 | Role | 角色 | 役割 |
| 次の欄に `2025-06-01` を入力 | GCP training | GCP 訓練 | GCP 研修 |
| クリック | Add and sign | 加入並簽署 | 追加して署名 |

表示されるもの: 記載が追加・署名され、タスクが消えます。

- データ管理責任者: データスチュワードは実行を開始できない: `POST /pilot/request` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 手順 7 · 治験責任医師／分担医師

治験責任医師として：各行を開いて確認し、すべて承認します。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 上部のバーでクリック | This week's patients | 本週病人 | 今週の患者 |
| クリック | Criteria waiting for your approval: MYSTUDY v1.0.0 | 等待您核准的條件：MYSTUDY v1.0.0 | 承認待ちの基準：MYSTUDY v1.0.0 |
| 中国語と日本語の画面のみ：各基準に短い表示名を付け、次をクリック | Save label | 儲存標籤 | 表示名を保存 |
| 各行でクリック | Open | 開啟 | 開く |
| クリック | Approve all | 全部核准 | すべて承認 |
| クリック | Yes, do it | 是，執行 | はい、実行します |

表示されるもの: 確認ページのあと、APPROVE ジョブが完了します。

### 手順 8 · CRC

新しい試験で FEAS を実行します。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| メニューを開き、次をクリック | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| このボタンのフォームで `MYSTUDY` を選び、次をクリック | Count eligible patients | 統計合格病人數 | 適格患者数を集計 |

表示されるもの: FEAS ジョブが完了し、4 件の基準のファネルが出ます。

### 手順 9 · CRC

試験のレポート、次に試験の設定を開き、スクリーニングの対象で病院全体を選びます。次に試験の状態を開きます。試験は準備中で、SAE 報告の種類を選ぶまで募集中にできません。設定に戻り、SAE の報告規定で種類を選んで保存します。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 上部のバーでクリック | Reports | 報告 | レポート |
| その試験の行でクリック | Open report | 開啟報告 | レポートを開く |
| メニューを開き、次をクリック | More → MYSTUDY · Study set-up | 更多 → MYSTUDY · 試驗設定 | その他 → MYSTUDY · 試験の設定 |
| 選択 | The whole hospital: every patient with a booked appointment in the coming months or a visit in the last 12 months | 全院：未來數個月有預約，或過去 12 個月內有就診的所有病人 | 病院全体：今後数か月に予約がある、または過去12か月に受診したすべての患者 |
| クリック | Save who to screen | 儲存篩選對象 | スクリーニングの対象を保存 |
| クリック | Study state and identifiers | 試驗狀態與識別編號 | 試験の状態と識別番号 |
| 次の欄で `open` を選択 | Move to | 變更為 | 変更先 |
| クリック | Change state | 變更狀態 | 状態を変更 |
| クリック | Study set-up | 試驗設定 | 試験の設定 |
| 次の欄で `tw_trial` を選択 | Rule set | 規定 | 規定 |
| クリック | Save and confirm | 儲存並確認 | 保存して確認 |

表示されるもの: スクリーニングの対象：病院全体。試験は準備中で、募集中への変更は拒否され、設定ページに案内されます。その後、試験に SAE 報告の種類が設定されます。

- 治験責任医師／分担医師: 治験責任医師は SAE 報告の種類を選べない: `POST /studies/MYSTUDY/setup/sae` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- データ管理責任者: データスチュワードは SAE 報告の種類を選べない: `POST /studies/MYSTUDY/setup/sae` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 手順 10 · CRC

新しい試験で SCREEN を実行します。試験がまだ募集中でないため失敗します。試験の状態ページで募集中にし、もう一度 SCREEN を実行します。1 分ほどかかります。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| メニューを開き、次をクリック | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| このボタンのフォームで `MYSTUDY` を選び、次をクリック | Find candidates for the next visits | 找出近期回診的候選者 | 次回受診の候補者を抽出 |
| 上部のバーでクリック | Reports | 報告 | レポート |
| その試験の行でクリック | Open report | 開啟報告 | レポートを開く |
| メニューを開き、次をクリック | More → MYSTUDY · Study set-up | 更多 → MYSTUDY · 試驗設定 | その他 → MYSTUDY · 試験の設定 |
| クリック | Study state and identifiers | 試驗狀態與識別編號 | 試験の状態と識別番号 |
| 次の欄で `open` を選択 | Move to | 變更為 | 変更先 |
| クリック | Change state | 變更狀態 | 状態を変更 |
| メニューを開き、次をクリック | More → New request | 更多 → 新請求 | その他 → 新規リクエスト |
| このボタンのフォームで `MYSTUDY` を選び、次をクリック | Find candidates for the next visits | 找出近期回診的候選者 | 次回受診の候補者を抽出 |

表示されるもの: 最初の SCREEN ジョブは理由付きで失敗します（試験が募集中でない。CRC が状態を変える）。試験は募集中になります。2 回目の SCREEN ジョブが完了し、リストが出ます。

- データ管理責任者: データスチュワードは試験を募集中にできない: `POST /studies/MYSTUDY/state` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".
- 管理者: 管理者は試験を募集中にできない: `POST /studies/MYSTUDY/state` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

### 手順 11 · CRC

新しい試験の候補者リストを読みます。

| 操作 | en | zh-TW | ja |
| --- | --- | --- | --- |
| 上部のバーでクリック | This week's patients | 本週病人 | 今週の患者 |
| クリック | MYSTUDY | MYSTUDY | MYSTUDY |
| クリック | Candidates | 全院候選者 | 院内の候補者 |

表示されるもの: 院内の候補者とその人数。

- 管理者: 管理者は候補者リストを開けない: `GET /studies/MYSTUDY/candidates` 拒否される：403 とページ "This page needs another role / 這個頁面需要其他角色 / このページには別の役割が必要です".

<!-- new-study-walk: end of steps -->

## stub モデルは見たことのない文章をどう扱うか

この機械のモデルの回答はすべて stub、`services/llm_stub/handlers.py` から来ます（機械は `TB_LLM_MODE=stub` で動き、
モードを設定しない DEV や TEST の機械は同じ stub をプロセス内で動かします。`services/console/studies.py`、
`test_model_in_use`）。同じ入力には同じ回答を返し、機械の外には何も呼び出しません。

- 基準の読み取り（`ir_extract`）：stub は `services/llm_stub/cassettes/ir_extract/<id>.json` にその基準 ID の
  録画済みの回答を探すか、新しい ID が「その ID-」で始まるものを探します。新しい ID にはないので、各行は
  `_heuristic_criterion` に渡ります。
- `_heuristic_criterion` が知っている型はわずかです：BMI、eGFR、DAS28、HbA1c、serum urate（または uric acid、sUA）
  のあとに比較記号（≥、>、≤、<）と数値が続くもの、そして年齢（「aged 18 years or older」、「age ≥ 18」）。合う行は
  コード化データへの固定フィルターになります。それ以外の行はスクリーニング時に担当者に回り、「Confirm with the
  patient/clinician: 」とその行が問いになります。短い表示名はその行の最初の 40 文字です。
- 新しい ID の下の SITE5B の文章は、こうしてフィルター 1 件と担当者 3 件になります：年齢の行は合う。痛風の行は型がない。
  尿酸の行は「at least 7.0」で比較記号がないので合わない。悪性腫瘍の行は型がない。承認ページがそう示し（「4 件：
  固定フィルター 1 · 記録をモデルが読む 0 · フィルター後に記録 0 · 担当者 3」）、FEAS は年齢の行だけを数え、尿酸の行の
  表示名は「Most recent serum urate in the last year」になります。
- ID が `SITE5B` のときは、stub は録画済みの回答を使い、4 行ともコード化されます。
- 概念からコードへの対応（`concept_map`）：stub は名前が概念と最も多く語を共有する候補を選びます。共有する語がなければ
  選ばず、確認を求めます。
- 記録の読み取り（`judge`）：stub が知っているのは合成病院の記録の文型（中国語と、機械が日本語を挙げるときの日本語）と
  記載された BMI や HbA1c だけです。ほかの文章にはすべて「unknown」と答え、患者は確認待ちに回り、「合致しない」には
  なりません。この操作では記録から読む基準はありません。
- 記録から読んだ回答には、どのページでも「テスト用モデル」と表示されます。ここで実際のモデルを測るものは何もありません。

## 操作の実行方法

- テスターは：プレビュー機で上の手順を手で行います。
- 自動で、リポジトリのある任意のコンピューターで：`make walk-new-study`（`trialbox/` で、先に `make venv`、`make
  fonts`、`make jvm-deps`）。steps モードの機械をローカルで起動し（`tools/demo.py`、プレビュー VM と同じ）、
  Chromium で 3 回、言語ごとに 1 回ずつ、それぞれ新しい ID で操作します。機械のデータ作成に約 7 分、各操作に約 70 秒。
- `TB_WALK_ACCOUNTS` でほかのアカウント（または役割を切り替える 1 人）を指定し、`TB_WALK_BASE` と
  `TB_WALK_PASSWORD` ですでに動いている機械を操作します（方法は `tests/e2e/test_new_study_walk.py`）。
- 手順や製品の文言を変えたら：`PYTHONPATH=libs:services:. .venv/bin/python -m tests.e2e.new_study_walk_plan --write`
  で 3 ページの手順の表を書き直します。

## 出典

- D-1121（この操作）、D-1062（steps モード）、D-1063（1 人 1 アカウントで役割を切り替える）、D-540（最初の承認の前に
  データスチュワードが責任医師を登録する）、D-309（中国語・日本語の画面での基準ごとの短い表示名）、D-1153（新しい試験は
  準備中から始まる）、D-415（SAE 報告の種類を選んでから募集中にする）、D-386（リストは募集中の試験だけ）、D-1106（この
  操作は D-1153 に合わせる）。
- 自動操作：`tests/e2e/new_study_walk_plan.py`、`tests/e2e/new_study_walk.js`、`tests/e2e/test_new_study_walk.py`。
