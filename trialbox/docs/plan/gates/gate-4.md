## Gate 4: what it guarantees, what calls it, what is still in the ratchet

Admission matches the site's inventory to individual lake, OMOP and derived rows. Every row must carry its owner's stamp and a released review status. Admission checks the trusted and site-accepted rule digest, recipients and scope, then records permission in the audit log.
篩選前逐筆核對院方清冊與資料湖、OMOP 及衍生資料。每筆都須有擁有者標記且已解除保留。系統核對可信且經院方接受的規則摘要、收件人與範圍，再將許可寫入稽核紀錄。
施設の目録とデータレイク、OMOP、派生データの各行を照合する。全行に所有者印と保留解除の記録が必要になる。信頼済みで施設が承認した規則のダイジェスト、宛先、対象範囲を確認し、許可を監査記録に書き込む。

SCREEN jobs, including replays, pin the generation, rule version, stored-score setting and hash of the reviewed record. First installation enrolls the new site key. For a passed mapped feed, the adapter checks every emitted row before merging duplicates. It binds the complete resource content and each authorized requester’s delivery route to the site-approved rule at `$TB_DATA_DIR/screening-inputs/<generation>/<study>/<version>.json` and adds its hash to `$TB_DATA_DIR/screening-inputs/screening-clearance.json`, on a volume outside database and secrets restores. Carried rows need an accepted review of exactly the same content from the merge base. A missing opt-out register or a stored-score batch with failed patients stops SCREEN. An older site may need to rebuild before it can list patients.
SCREEN 作業及重跑會固定資料世代、規則版本、衍生分數讀取設定及審查紀錄雜湊。首次安裝會登錄新院區金鑰。夜間匯入通過後，配接器依逐筆對應版本與院方核准標籤，為每位獲准申請者記錄預設範圍與寄送對象，並在合併重複資料前檢查保留狀態。沿用的資料須與前次核准的內容雜湊一致。即時許可存放於資料庫與密鑰還原範圍之外。其他收件人或範圍須另行核准。
SCREEN の実行と再実行では、データ世代、規則版、保存済みスコアの読み取り設定、審査記録のハッシュを固定する。初回インストールで施設鍵を登録する。夜間取込の合格後、アダプターは各行のマッピング版と施設の承認タグに基づき、許可された依頼者ごとに対象範囲と宛先を記録する。重複行を統合する前に保留状態を確認し、前回から引き継ぐ行は承認済みの内容ハッシュと照合する。現行の許可はデータベースとシークレットの復元対象外に置く。ほかの宛先や範囲には個別の承認が必要となる。

The ratchet lists the remaining paths. Migrate the lake and OMOP builders and derived rows first, then rebuild and promotion, backfill, steward acceptance, rule import and the remaining readers. Restore operators must revoke external clearance before replacement and grant it again after review.
待移轉清單涵蓋資料湖、OMOP 與衍生資料建置、重建與發布、回填、管理者核准、規則匯入及其他讀取路徑。還原前須撤銷外部許可，審查後再核准。
残る経路はレイク・OMOP・派生データの構築、再構築と公開、過去分の取り込み、管理者承認、規則の取り込み、その他の読み取りの順に移す。復元前に外部の許可を取り消し、審査後に再承認する。

## Open for later slices

- **Rebuild and promotion (3).** `Lake._rebuild` already refuses a non-promoting rebuild of the served date. Builds with promotion still replace the alias without Gate 4. The ratchet includes the swap and the promotion entry points.
- **Restore clearance (4).** `tools/trialbox/backup.py:restore` can restore the database release and the site secrets. The live grant and its enrollment marker now survive outside both volumes, so restoring a revoked grant from those stores fails. Restore still needs to revoke a currently active grant before replacement, including when its hold audit fails. Round 2 finding 7 remains open. A backup of the currently cleared night reproduces the release event ID and timestamp. If the hold audit fails, the surviving external grant can still authorize SCREEN once audit access returns. The restore slice must invalidate that grant durably before replacing data.
- **Restored generation (9).** A restored date alias can have matching generation metadata and no generation file. Ordinary generation lookups encounter this missing file. SCREEN now asks the lake to reattach a uniquely hash-verified file. Restore still leaves recovery to its first reader.
- **Remaining producers.** The adapter can attest its own released feed. Site additions, OMOP inventory and stored-score batches require independent owner review. A build, steward decision, backfill or rule import still needs its own gate migration.
