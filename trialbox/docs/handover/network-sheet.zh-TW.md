# TrialBox 網路、連接埠與機密資訊一覽

由下列 compose 檔以 tools/network_sheet.py 產生（D-138）。除主控台連接埠外，外部無法連到本機任何服務。本表不含任何機密的值。

**compose 檔:** `deploy/docker-compose.yml`, `deploy/docker-compose.secrets.yml`, `deploy/docker-compose.rtx5090.yml`, `deploy/docker-compose.gb10.yml`, `deploy/docker-compose.rtxpro6000.yml`

## 監聽連接埠

| 服務 | 連接埠 | 主機端 | 網路 | 可連線者 | 啟動條件 |
| --- | --- | --- | --- | --- | --- |
| adapter | 8016 | 未對外 | trialbox-net | 僅限持有自身權杖者: console, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| console | 8090 | 127.0.0.1:8090:8090 | trialbox-net | 院內人員瀏覽器: 預設僅 127.0.0.1；院內網路僅經由院方 TLS 代理 | 常駐 |
| criteria-compiler | 8012 | 未對外 | egress-net, trialbox-net | 僅限持有自身權杖者: orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| db | 5432 | 未對外 | trialbox-net | TrialBox 各服務與 fhir-store（需密碼） | 常駐 |
| doc-parser | 8011 | 未對外 | trialbox-net | 僅限持有自身權杖者: orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| embed-service | 8014 | 未對外 | trialbox-net | 僅限持有自身權杖者: lake; 主機上的管理者（operator 權杖） | 常駐 |
| fhir-store | 8080 | 未對外 | trialbox-net | adapter、orchestrator、criteria-compiler（僅網路隔離，尚無權杖） | 常駐 |
| gateway | 8020 | 未對外 | egress-net, model-net, trialbox-net | 僅限持有自身權杖者: console, criteria-compiler, doc-parser, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| judge-sleep-init | 無（一次性工作） | 未對外 | model-net | - | GPU 設定 (rtx5090) |
| judge-wake-init | 無（一次性工作） | 未對外 | model-net | - | GPU 設定 (rtx5090) |
| lake | 8013 | 未對外 | trialbox-net | 僅限持有自身權杖者: adapter, criteria-compiler, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| llm-service | 8000 | 未對外 | model-net | 僅 gateway（model-net） | GPU 設定 |
| llm-stub | 8000 | 未對外 | model-net | 僅 gateway（model-net） | 無 GPU 設定 |
| llm-verifier | 8000 | 未對外 | model-net | 僅 gateway（model-net） | GPU 設定 (rtx5090, gb10, rtxpro6000) |
| mail-gateway | 8015 | 未對外 | egress-net, trialbox-net | 僅限持有自身權杖者: console, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| model-swap-init | 無（一次性工作） | 未對外 | model-net | - | GPU 設定 (rtx5090) |
| orchestrator | 8010 | 未對外 | egress-net, trialbox-net | 僅限持有自身權杖者: console, mail-gateway; 主機上的管理者（operator 權杖） | 常駐 |

## 網路

| 網路 |  |
| --- | --- |
| trialbox-egress | 對外僅限下表目的地（nftables，deploy/network.sh） |
| trialbox-model-net | 內部專用: 無對外路由 |
| trialbox-net | 內部專用: 無對外路由 |

## 對外連線

未做院方設定時，本機不對外連線；唯一例外是 TB_CTGOV_MODE=live 時 criteria-compiler 連 ClinicalTrials.gov（公開登錄，無病人資料；設 TB_CTGOV_MODE=cassette 即關閉）。下表每一列僅在填入該設定後開放。

| 服務 | 目的地 | 用途 | 開放條件 |
| --- | --- | --- | --- |
| mail-gateway | SMTP_HOST:SMTP_PORT | outbound mail (hospital SMTP / Exchange) | SMTP_HOST |
| mail-gateway | IMAP_HOST:IMAP_PORT | intake mailbox | IMAP_HOST |
| gateway | external model endpoints of models/routing.yaml | model endpoint (refused for D3/D4 data) | the endpoint's URL |
| gateway | CLOUD_LLM_BASE_URL | cloud model, through the gateway only | CLOUD_LLM_BASE_URL |
| criteria-compiler | clinicaltrials.gov:443 | ClinicalTrials.gov public registry (COHORT) | TB_CTGOV_MODE=live |
| orchestrator | NHI_TWPAS_BASE_URL | NHI TWPAS (SUBMIT only) | NHI_TWPAS_BASE_URL |
| any | EGRESS_EXTRA | site additions | EGRESS_EXTRA |

## 機密資訊（僅名稱與位置）

| 機密 | 存放位置 | 提供給 |
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
| operator token | deploy/secrets/services/operator.token (0600) | 僅主機（不進容器） |
| token registry (sha256 of each token) | deploy/secrets/services/public/tokens.json | 所有 TrialBox 服務（僅雜湊，非機密） |
| POSTGRES_PASSWORD (role hapi) | deploy/.env (0600, root) | db, fhir-store |
| POSTGRES_WF_PASSWORD, TB_DB_URL (role trialbox) | deploy/.env (0600, root) | db; adapter, console, criteria-compiler, gateway, lake, mail-gateway, orchestrator |
| IMAP_PASS, SMTP_PASS | deploy/.env (0600, root) | mail-gateway |
| CLOUD_LLM_API_KEY (empty by default) | deploy/.env (0600, root) | gateway |
| site_hmac.key, pid_map.key, REDCap API tokens | volume tb-secrets (/run/secrets/trialbox) | adapter, orchestrator |
| backup public key | deploy/secrets/backup.pub | the backup (encrypts only) |
| backup private key | USB stick | 醫院資訊室密封保管；不放在本機 |
| vendor update key (public) | deploy/keys/vendor_ed25519.pub | tools/apply_update.sh |

輪替: sudo python3 -m tools.trialbox secrets rotate [--service 名稱]（RUNBOOK §5「Secrets」）。
