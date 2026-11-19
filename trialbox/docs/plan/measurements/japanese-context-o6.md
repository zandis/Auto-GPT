# O-6 / A6

## English

Run from `trialbox/` on the same synthetic-only validation box for both arms. Use the existing on-box gateway and its orchestrator service authentication. Set `TB_ENV=VALIDATION` in the shell and on the gateway. Capture discovers the running Compose gateway on the local Docker socket and uses its container address for model calls and GPU controls. Point `TB_ORCH_DIR` at the validation orchestrator directory containing the current passing pair report (`selftest.json`). Wake checks use the canary cases shipped in this repository. Keep gateway prompt and response tracing disabled.

For the first arm, hold the ballast using the [O-6 ballast procedure](ballast-stand-in-2026-11-18.md) and start the 8,192-token pair with the shell settings for that procedure. Use `hold` without `--env-file` to keep installation files intact. For the second arm, release the ballast and use the unballasted 32,768-token head-box pair. Run each capture only after its gateway and model settings are ready. The capture checks both advertised contexts and checks the local ballast container before and after SCREEN.

Each capture generates the same 2,500-chart `JP=ja:1.0` cohort from the supplied seed and screens it with the checked-in GZQO rules using the default cascade and local hash retrieval. It retains aggregate observations, the fixture and rule digests, and completion status. The report divides truncated judge calls by judge calls with both upstream usage fields. Verifier calls and evaluations that issue no judge call contribute zero to that denominator. A6 uses the exact signed difference between the two shares and accepts an increase of at most two percentage points.

Use a fresh output folder for each paired rehearsal. If a retry is incomplete, capture preserves the completed arm and saves the attempt as `<profile>.incomplete.json`.

This workspace had no visible NVIDIA device or local Docker daemon. Both captures produced zero judge calls, leaving the rates, difference and A6 verdict unavailable. [Filed report](japanese-context-o6-incomplete.md)

## 繁體中文

兩組都須在同一台僅使用合成資料的驗證設備上執行。請從 `trialbox/` 執行，使用設備現有的閘道及協調服務驗證。請在命令殼層及閘道設定 `TB_ENV=VALIDATION`。工具透過本機 Docker 通訊端尋找執行中的 Compose 閘道，並使用該容器的位址呼叫模型與控制 GPU。請將 `TB_ORCH_DIR` 指向驗證設備上存放有效雙模型測試報告（`selftest.json`）的協調服務目錄。喚醒檢查使用版本庫內的測試案例。請維持閘道的提示與回應追蹤停用。

第一組請依照 [O-6 顯示記憶體預留程序](ballast-stand-in-2026-11-18.md) 保持預留，並使用該程序的命令殼層設定啟動 8,192 權杖的模型組。使用不帶 `--env-file` 的 `hold`，以保留安裝設定檔。第二組請釋放預留記憶體，改用不預留記憶體的 32,768 權杖主工作站模型組。等各組的閘道和模型設定就緒後再擷取。工具會核對兩個模型宣告的上下文長度，並在 SCREEN 前後檢查本機預留容器。

兩組都使用指定種子產生相同的 2,500 份 `JP=ja:1.0` 病歷，並以版本庫中的 GZQO 規則、預設級聯流程及本機雜湊檢索進行篩選。擷取檔僅保留彙總觀測值、測試資料與規則的雜湊值，以及完成狀態。截斷比例的分母為具備兩個上游用量欄位的判定呼叫數。覆核呼叫和未發出判定呼叫的評估均不計入分母。A6 使用兩組比例的精確帶符號差值，增幅最多兩個百分點即通過。

每次成對演練請使用新的輸出目錄。若重試未完成，工具會保留已完成的擷取檔，並將重試結果存為 `<profile>.incomplete.json`。

此工作環境無可用的 NVIDIA 裝置或本機 Docker 服務。兩組的判定呼叫數均為零，因此無法計算截斷比例與差值，也無法判定 A6。[已歸檔報告](japanese-context-o6-incomplete.md)

## 日本語

両条件とも同一の合成データ専用検証環境で実行します。`trialbox/` から実行し、既存のオンボックスゲートウェイとオーケストレーターのサービス認証を使用します。シェルとゲートウェイの両方で `TB_ENV=VALIDATION` を設定します。記録ツールはローカルの Docker ソケットで稼働中の Compose ゲートウェイを特定し、そのコンテナのアドレスでモデル呼び出しと GPU 制御を行います。`TB_ORCH_DIR` には、有効なモデルペアの合格報告（`selftest.json`）がある検証用オーケストレーターのディレクトリを指定します。復帰時の検査にはリポジトリに同梱されたテストケースを使います。ゲートウェイのプロンプトと応答のトレースは無効のままにします。

最初の条件では [O-6 の GPU メモリ予約手順](ballast-stand-in-2026-11-18.md) に従い、メモリを予約した状態で、手順どおりのシェル設定で 8,192 トークンのモデルペアを起動します。インストール設定ファイルを保持するため、`hold` には `--env-file` を付けません。次の条件では予約を解除し、主任端末で 32,768 トークンのモデルペアを使用します。各条件でゲートウェイとモデルの準備が整ってから記録します。記録ツールは両モデルが通知するコンテキスト長を確認し、SCREEN の前後にローカルのメモリ予約コンテナを確認します。

両条件で指定したシードから同じ 2,500 件の `JP=ja:1.0` の合成カルテを生成します。リポジトリ内の GZQO ルール、既定のカスケード、ローカルのハッシュ検索を使い、スクリーニングします。記録に残るのは集計値、試験データとルールのハッシュ値、完了状態です。切り詰め率の分母は、上流から入力と出力の使用量を取得できた判定呼び出し数です。検証呼び出しと判定呼び出しが発生しなかった評価は分母に含まれません。A6 は丸める前の符号付きの差を使い、増加が 2 パーセントポイント以内なら合格です。

一組の試験ごとに新しい出力ディレクトリを使います。再試行が未完了の場合、完了済みの記録を保持し、再試行の結果を `<profile>.incomplete.json` に保存します。

この作業環境では NVIDIA デバイスとローカルの Docker デーモンを利用できませんでした。どちらの条件でも判定呼び出しはゼロ件で、切り詰め率とその差は算出できず、A6 は未判定です。[保存済みの報告書](japanese-context-o6-incomplete.md)

```sh
TB_PY=${TB_PY:-python}
PYTHONPATH=libs:services:. "$TB_PY" -m tools.japanese_context capture ballast o6-results 42
PYTHONPATH=libs:services:. "$TB_PY" -m tools.japanese_context capture head-box o6-results 42
for locale in en zh-TW ja
do
  TB_REPORT_LANG="$locale" PYTHONPATH=libs:services:. "$TB_PY" -m tools.japanese_context report o6-results > "o6-results/$locale.md"
done
```
