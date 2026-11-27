# Gate 2: what it guarantees, what calls it, what is still in the ratchet
## 病人歸屬、呼叫端與待遷移項目 ／ 患者の特定、呼び出し元、未移行の箇所

The mapping engine passes patient-owned rows and their references through `resolve_record`. It keeps opaque IDs distinct within their source, normalizes declared chart numbers and scopes each event to its owner. Conflicting patient evidence stops the whole batch before screening can read it. Corrections can carry the key from an earlier publication. The inventory covers remaining import, deletion, backfill, lake, OMOP, EDC and patient-registry paths. Reconciling existing IDs and opt-outs precedes the two-patient delta versus full-rebuild comparison.

對映引擎透過 `resolve_record` 處理病人紀錄與參照。它保留來源識別碼的差異，只正規化已宣告的病歷號，並依病人區分事件。病人證據矛盾時，整批停止發布，篩選無法讀到這批資料。更正可帶入上次發布的鍵。清單列出匯入、刪除、回填、資料湖、OMOP、EDC 及病人登錄中待遷移之處。先核對既有識別碼與退出紀錄，再比較兩名病人的差異更新與完整重建。

マッピングエンジンは患者に属する記録と参照を `resolve_record` に渡す。ソース内の識別子の違いを保持し、明示された診察券番号だけを正規化して、患者ごとにイベントを識別する。患者情報の矛盾を検出すると、スクリーニングに公開する前にバッチ全体を停止する。訂正時は以前の公開キーを渡せる。取込、削除、再取込、データレイク、OMOP、EDC、患者台帳に残る処理は一覧で管理する。既存IDと同意撤回を照合した後、患者二人の差分更新と全件再構築を比較する。

## Open for later slices

- **5 — Chart merges.** `adapter.ndjson._carried_over` rewrites a carried Observation's Patient reference while retaining the key issued under the retired chart. A correction under the surviving chart then leaves two records. Decide how to migrate prior keys, references and tombstones together. The ratchet tracks its call to `alias_references`.
  - 病歷合併會更新 Observation 的病人參照，卻保留舊病歷的鍵；更正後會留下兩筆紀錄。須一併決定既有鍵、參照與刪除標記的遷移方式。清單已追蹤上述呼叫。
  - 診察券番号の統合で Observation の患者参照が変わっても旧キーは残り、訂正後に二件が残る。既存キー、参照、削除マーカーの移行方法を決める。上記の呼び出しは一覧に登録済み。
- **8 — Backfill.** `adapter.backfill._spool` binds charts with `pid_for_mrn`. At the 5,000-row boundary it commits the conflicting national ID before the mapper holds the batch. The hold also bypasses the backfill audit. Stage identity writes through publication and record the hold. The binding is in the ratchet.
  - 歷史回填在第 5,000 列先寫入矛盾的身分證號，之後才中止，且未留下回填稽核紀錄。身分資料應暫存至發布，並記錄中止原因。清單已追蹤病歷綁定。
  - 履歴取込は5,000行目で矛盾する個人識別番号を書き込んでから停止し、監査記録も残さない。公開までは識別情報を仮保存し、停止を記録する。診察券番号の紐付けは一覧に登録済み。

## Decisions for refused declarations ／ 被拒宣告的待決事項 ／ 拒否された宣言の判断事項

Decide how opaque Patient IDs correspond to registered charts and existing opt-outs. For a joined owner or composite reference, identify the ordered source columns and which carry chart numbers. Declare the actual resource type and resolve clinical references using the target's source key under the same patient. A delta over a different or older identity receipt requires a full rebuild or an agreed migration of published keys.

須決定不透明病人識別碼與已登錄病歷、退出紀錄的對應方式。複合病人鍵或參照須指定來源欄位順序及其中的病歷號。請宣告實際資源類型，並在同一病人下用目標來源鍵解析臨床參照。既有識別收據不同或過舊時，須完整重建，或先議定已發布鍵的遷移方式。

不透明な患者IDと登録済み診察券番号・同意撤回の対応を決める。複合患者キーや参照には順序付きのソース列と診察券番号に当たる列を指定する。実際のリソース型を宣言し、同じ患者の下で対象のソースキーから診療記録の参照先を求める。識別規則の記録が異なる場合や古い場合、差分取込には全件再構築または合意済みの公開キー移行が必要となる。
