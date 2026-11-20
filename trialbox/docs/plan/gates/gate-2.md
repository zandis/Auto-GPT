# Gate 2: what it guarantees, what calls it, what is still in the ratchet
## 病人歸屬、呼叫端與待遷移項目 ／ 患者の特定、呼び出し元、未移行の箇所

The mapping engine passes patient-owned rows and their references through `resolve_record`. It keeps opaque IDs distinct within their source, normalizes declared chart numbers and scopes each event to its owner. Conflicting patient evidence stops the whole batch before screening can read it. Corrections can carry the key from an earlier publication. The inventory covers remaining import, deletion, backfill, lake, OMOP, EDC and patient-registry paths. Reconciling existing IDs and opt-outs precedes the two-patient delta versus full-rebuild comparison.

對映引擎透過 `resolve_record` 處理病人紀錄與參照。它保留來源識別碼的差異，只正規化已宣告的病歷號，並依病人區分事件。病人證據矛盾時，整批停止發布，篩選無法讀到這批資料。更正可帶入上次發布的鍵。清單列出匯入、刪除、回填、資料湖、OMOP、EDC 及病人登錄中待遷移之處。先核對既有識別碼與退出紀錄，再比較兩名病人的差異更新與完整重建。

マッピングエンジンは患者に属する記録と参照を `resolve_record` に渡す。ソース内の識別子の違いを保持し、明示された診察券番号だけを正規化して、患者ごとにイベントを識別する。患者情報の矛盾を検出すると、スクリーニングに公開する前にバッチ全体を停止する。訂正時は以前の公開キーを渡せる。取込、削除、再取込、データレイク、OMOP、EDC、患者台帳に残る処理は一覧で管理する。既存IDと同意撤回を照合した後、患者二人の差分更新と全件再構築を比較する。
