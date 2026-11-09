# TrialBox ネットワーク・ポート・秘密情報一覧

下記の compose ファイルから tools/network_sheet.py で生成（D-138）。コンソールのポート以外、外部から到達できるものはありません。秘密情報の値はこの一覧に載せていません。

**compose ファイル:** `deploy/docker-compose.yml`, `deploy/docker-compose.secrets.yml`, `deploy/docker-compose.rtx5090.yml`, `deploy/docker-compose.gb10.yml`, `deploy/docker-compose.rtxpro6000.yml`

## 待ち受けポート

| サービス | ポート | ホスト側 | ネットワーク | 接続できるもの | 起動条件 |
| --- | --- | --- | --- | --- | --- |
| adapter | 8016 | 公開なし | trialbox-net | 自身のトークンを持つ次のみ: console, orchestrator; ホスト上の管理者（operator トークン） | 常時 |
| console | 8090 | 127.0.0.1:8090:8090 | trialbox-net | 職員のブラウザ: 既定は 127.0.0.1 のみ。院内 LAN からは施設の TLS プロキシ経由のみ | 常時 |
| criteria-compiler | 8012 | 公開なし | egress-net, trialbox-net | 自身のトークンを持つ次のみ: orchestrator; ホスト上の管理者（operator トークン） | 常時 |
| db | 5432 | 公開なし | trialbox-net | TrialBox の各サービスと fhir-store（パスワード） | 常時 |
| doc-parser | 8011 | 公開なし | trialbox-net | 自身のトークンを持つ次のみ: orchestrator; ホスト上の管理者（operator トークン） | 常時 |
| embed-service | 8014 | 公開なし | trialbox-net | 自身のトークンを持つ次のみ: lake; ホスト上の管理者（operator トークン） | 常時 |
| fhir-store | 8080 | 公開なし | trialbox-net | adapter、orchestrator、criteria-compiler（ネットワーク分離のみ、トークンなし） | 常時 |
| gateway | 8020 | 公開なし | egress-net, model-net, trialbox-net | 自身のトークンを持つ次のみ: console, criteria-compiler, doc-parser, orchestrator; ホスト上の管理者（operator トークン） | 常時 |
| judge-sleep-init | なし（一回限りの処理） | 公開なし | model-net | - | GPU プロファイル (rtx5090) |
| judge-wake-init | なし（一回限りの処理） | 公開なし | model-net | - | GPU プロファイル (rtx5090) |
| lake | 8013 | 公開なし | trialbox-net | 自身のトークンを持つ次のみ: adapter, criteria-compiler, orchestrator; ホスト上の管理者（operator トークン） | 常時 |
| llm-service | 8000 | 公開なし | model-net | gateway のみ（model-net） | GPU プロファイル |
| llm-stub | 8000 | 公開なし | model-net | gateway のみ（model-net） | GPU なしプロファイル |
| llm-verifier | 8000 | 公開なし | model-net | gateway のみ（model-net） | GPU プロファイル (rtx5090, gb10, rtxpro6000) |
| mail-gateway | 8015 | 公開なし | egress-net, trialbox-net | 自身のトークンを持つ次のみ: console, orchestrator; ホスト上の管理者（operator トークン） | 常時 |
| model-swap-init | なし（一回限りの処理） | 公開なし | model-net | - | GPU プロファイル (rtx5090) |
| orchestrator | 8010 | 公開なし | egress-net, trialbox-net | 自身のトークンを持つ次のみ: console, mail-gateway; ホスト上の管理者（operator トークン） | 常時 |

## ネットワーク

| ネットワーク |  |
| --- | --- |
| trialbox-egress | 外部へは下表の宛先のみ（nftables、deploy/network.sh） |
| trialbox-model-net | 内部専用: 外部への経路なし |
| trialbox-net | 内部専用: 外部への経路なし |

## 外部への通信

施設設定がなければ外部には何も接続しません。例外は TB_CTGOV_MODE=live の間の criteria-compiler から ClinicalTrials.gov（公開レジストリ、患者データなし。TB_CTGOV_MODE=cassette で閉じる）。下表の各行は、その設定を入れたときだけ開きます。

| サービス | 宛先 | 用途 | 開く設定 |
| --- | --- | --- | --- |
| mail-gateway | SMTP_HOST:SMTP_PORT | outbound mail (hospital SMTP / Exchange) | SMTP_HOST |
| mail-gateway | IMAP_HOST:IMAP_PORT | intake mailbox | IMAP_HOST |
| gateway | external model endpoints of models/routing.yaml | model endpoint (refused for D3/D4 data) | the endpoint's URL |
| gateway | CLOUD_LLM_BASE_URL | cloud model, through the gateway only | CLOUD_LLM_BASE_URL |
| criteria-compiler | clinicaltrials.gov:443 | ClinicalTrials.gov public registry (COHORT) | TB_CTGOV_MODE=live |
| orchestrator | NHI_TWPAS_BASE_URL | NHI TWPAS (SUBMIT only) | NHI_TWPAS_BASE_URL |
| any | EGRESS_EXTRA | site additions | EGRESS_EXTRA |

## 秘密情報（名前と場所のみ）

| 秘密情報 | 保管場所 | 渡す先 |
| --- | --- | --- |
| service token: adapter | deploy/secrets/services/adapter.token (0600) | adapter only, at /run/secrets/tb_service_token |
| service token: console | deploy/secrets/services/console.token (0600) | console only, at /run/secrets/tb_service_token |
| service token: criteria-compiler | deploy/secrets/services/criteria-compiler.token (0600) | criteria-compiler only, at /run/secrets/tb_service_token |
| service token: doc-parser | deploy/secrets/services/doc-parser.token (0600) | doc-parser only, at /run/secrets/tb_service_token |
| service token: embed-service | deploy/secrets/services/embed-service.token (0600) | embed-service only, at /run/secrets/tb_service_token |
| service token: gateway | deploy/secrets/services/gateway.token (0600) | gateway only, at /run/secrets/tb_service_token |
| service token: lake | deploy/secrets/services/lake.token (0600) | lake only, at /run/secrets/tb_service_token |
| service token: mail-gateway | deploy/secrets/services/mail-gateway.token (0600) | mail-gateway only, at /run/secrets/tb_service_token |
| service token: orchestrator | deploy/secrets/services/orchestrator.token (0600) | orchestrator only, at /run/secrets/tb_service_token |
| operator token | deploy/secrets/services/operator.token (0600) | ホストのみ（コンテナには渡さない） |
| token registry (sha256 of each token) | deploy/secrets/services/public/tokens.json | 全 TrialBox サービス（ハッシュのみ、秘密ではない） |
| POSTGRES_PASSWORD (role hapi) | deploy/.env (0600, root) | db, fhir-store |
| POSTGRES_WF_PASSWORD, TB_DB_URL (role trialbox) | deploy/.env (0600, root) | db; adapter, console, criteria-compiler, gateway, lake, mail-gateway, orchestrator |
| IMAP_PASS, SMTP_PASS | deploy/.env (0600, root) | mail-gateway |
| CLOUD_LLM_API_KEY (empty by default) | deploy/.env (0600, root) | gateway |
| site_hmac.key, pid_map.key, REDCap API tokens | volume tb-secrets (/run/secrets/trialbox) | adapter, orchestrator |
| backup public key | deploy/secrets/backup.pub | the backup (encrypts only) |
| backup private key | USB stick | 病院情報部門が封筒で保管。本機には置かない |
| vendor update key (public) | deploy/keys/vendor_ed25519.pub | tools/apply_update.sh |

更新: sudo python3 -m tools.trialbox secrets rotate [--service 名前]（RUNBOOK §5「Secrets」）。
