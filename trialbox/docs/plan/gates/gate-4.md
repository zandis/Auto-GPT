## Gate 4: what it guarantees, what calls it, what is still in the ratchet

Admission matches the site's inventory to individual lake, OMOP and derived rows. Every row must carry its owner's stamp and a released review status. Admission checks the trusted and site-accepted rule digest, recipients and scope, then records permission in the audit log.
篩選前逐筆核對院方清冊與資料湖、OMOP 及衍生資料。每筆都須有擁有者標記且已解除保留。系統核對可信且經院方接受的規則摘要、收件人與範圍，再將許可寫入稽核紀錄。
施設の目録とデータレイク、OMOP、派生データの各行を照合する。全行に所有者印と保留解除の記録が必要になる。信頼済みで施設が承認した規則のダイジェスト、宛先、対象範囲を確認し、許可を監査記録に書き込む。

SCREEN jobs, including replays, pin the admitted generation and rule version. The site supplies the record at `$TB_DATA_DIR/screening-inputs/<generation>/<study>/<version>.json` and explicitly clears its hash in `$TB_SECRETS_DIR/screening-clearance.json`, outside the restored database. An older site may need to rebuild before it can list patients.
SCREEN 作業及重跑都使用核准的資料與規則版本。院方須在還原的資料庫外明確核准紀錄的雜湊值。較舊的院區可能須先重建才能列出病人。
SCREEN の実行と再実行には承認済みの世代と規則版を使う。施設は復元対象のデータベースの外で記録のハッシュを明示的に承認する。旧環境では一覧作成の前に再構築が必要な場合がある。

The ratchet lists the remaining paths. Migrate the lake and OMOP builders and derived rows first, then rebuild and promotion, backfill, steward acceptance, rule import and the remaining readers. Restore operators must revoke external clearance before replacement and grant it again after review.
待移轉清單涵蓋資料湖、OMOP 與衍生資料建置、重建與發布、回填、管理者核准、規則匯入及其他讀取路徑。還原前須撤銷外部許可，審查後再核准。
残る経路はレイク・OMOP・派生データの構築、再構築と公開、過去分の取り込み、管理者承認、規則の取り込み、その他の読み取りの順に移す。復元前に外部の許可を取り消し、審査後に再承認する。
