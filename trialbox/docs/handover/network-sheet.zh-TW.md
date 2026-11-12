# TrialBox 網路、連接埠與機密資訊一覽

由下列 compose 檔以 tools/network_sheet.py 產生（D-138）。除主控台連接埠外，外部無法連到本機任何服務。本表不含任何機密的值。

**compose 檔:** `deploy/docker-compose.yml`, `deploy/docker-compose.secrets.yml`, `deploy/docker-compose.identity.yml`, `deploy/docker-compose.rtx5090.yml`, `deploy/docker-compose.gb10.yml`, `deploy/docker-compose.rtxpro6000.yml`

## 監聽連接埠

| 服務 | 連接埠 | 主機端 | 網路 | 可連線者 | 啟動條件 |
| --- | --- | --- | --- | --- | --- |
| adapter | 8016 | 未對外 | trialbox-net | 僅限持有自身權杖者: console, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| audit-writer | 無（不監聽） | 未對外 | trialbox-net | - | 常駐 |
| authelia | 9091 | 未對外 | egress-net, trialbox-net | 僅主控台與 Caddy（以醫院帳號登入） | oidc (identity) |
| caddy | 443 | 0.0.0.0:443:443 | edge-net, trialbox-net | 院內網路的診間電腦，僅 443（https://TB_TLS_HOSTNAME） | 常駐 |
| console | 8090 | 未對外 | console-net, trialbox-net | 院內人員瀏覽器: 預設僅 127.0.0.1；院內網路僅經由院方 TLS 代理 | 常駐 |
| criteria-compiler | 8012 | 未對外 | egress-net, trialbox-net | 僅限持有自身權杖者: orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| db | 5432 | 未對外 | trialbox-net | TrialBox 各服務與 fhir-store（需密碼） | 常駐 |
| doc-parser | 8011 | 未對外 | trialbox-net | 僅限持有自身權杖者: orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| embed-service | 8014 | 未對外 | trialbox-net | 僅限持有自身權杖者: lake; 主機上的管理者（operator 權杖） | 常駐 |
| fhir-store | 8080 | 未對外 | trialbox-net | adapter、orchestrator、criteria-compiler（僅網路隔離，尚無權杖） | 常駐 |
| gateway | 8020 | 未對外 | egress-net, model-net, trialbox-net | 僅限持有自身權杖者: console, criteria-compiler, doc-parser, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| judge-sleep-init | 無（不監聽） | 未對外 | model-backend-net | - | GPU 設定 (rtx5090) |
| judge-wake-init | 無（不監聽） | 未對外 | model-backend-net | - | GPU 設定 (rtx5090) |
| lake | 8013 | 未對外 | trialbox-net | 僅限持有自身權杖者: adapter, criteria-compiler, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| llm-service | 8000 | 未對外 | model-backend-net | 僅 model-guard（model-backend-net；每次呼叫皆需金鑰，D-177） | GPU 設定 |
| llm-stub | 8000 | 未對外 | model-net | 僅 gateway（model-net） | 無 GPU 設定 |
| llm-verifier | 8000 | 未對外 | model-backend-net | 僅 model-guard（model-backend-net；每次呼叫皆需金鑰，D-177） | GPU 設定 (rtx5090, gb10, rtxpro6000) |
| mail-gateway | 8015 | 未對外 | egress-net, trialbox-net | 僅限持有自身權杖者: console, orchestrator; 主機上的管理者（operator 權杖） | 常駐 |
| model-guard | 8000 | 未對外 | model-backend-net, model-net | 僅 gateway（model-net） | GPU 設定 |
| model-swap-init | 無（不監聽） | 未對外 | model-backend-net | - | GPU 設定 (rtx5090) |
| orchestrator | 8010 | 未對外 | egress-net, trialbox-net | 僅限持有自身權杖者: console, mail-gateway; 主機上的管理者（operator 權杖） | 常駐 |

## 網路

| 網路 |  |
| --- | --- |
| trialbox-console | 僅供主控台的公開埠: 不做對外 NAT、不解析外部名稱，其餘由 nftables 阻擋（deploy/network.sh） |
| trialbox-edge | 對外僅限下表目的地（nftables，deploy/network.sh） |
| trialbox-egress | 對外僅限下表目的地（nftables，deploy/network.sh） |
| trialbox-model-backend | 內部專用: 無對外路由 |
| trialbox-model-net | 內部專用: 無對外路由 |
| trialbox-net | 內部專用: 無對外路由 |

## 對外連線

未做院方設定時，本機不對外連線。ClinicalTrials.gov 預設為離線：試驗資料來自每次簽章更新附帶的參考資料（TB_CTGOV_MODE=offline）。安裝時選擇 live 的醫院，criteria-compiler 會連 clinicaltrials.gov:443（公開登錄，無病人資料；TB_CTGOV_MODE=live）。下表每一列僅在填入該設定後開放。

| 服務 | 目的地 | 用途 | 開放條件 |
| --- | --- | --- | --- |
| mail-gateway | SMTP_HOST:SMTP_PORT | outbound mail (hospital SMTP / Exchange) | SMTP_HOST |
| mail-gateway | IMAP_HOST:IMAP_PORT | intake mailbox | IMAP_HOST |
| gateway | external model endpoints of models/routing.yaml | model endpoint (refused for D3/D4 data) | the endpoint's URL |
| criteria-compiler | clinicaltrials.gov:443 | ClinicalTrials.gov public registry (COHORT) | TB_CTGOV_MODE=live (chosen at install; the default is offline) |
| orchestrator | NHI_TWPAS_BASE_URL | NHI TWPAS (SUBMIT only) | NHI_TWPAS_BASE_URL |
| any | EGRESS_EXTRA | site additions | EGRESS_EXTRA |

## 主機（容器之外）

| 來源 -> 目的地 | 用途 | 開放條件 |
| --- | --- | --- |
| clinic PCs -> TB_TLS_HOSTNAME:443 (caddy) | the console over https; nothing else is published | docker-compose.identity.yml, TB_TLS_HOSTNAME |
| authelia -> domain controller:636 (LDAPS) | sign-in with the hospital account (optional) | EGRESS_EXTRA authelia=<dc>:636, profile oidc |
| host -> hospital NTP server, UDP 123 | the clock of every audit row (check_host: clock in sync) | the host's time service (systemd-timesyncd or chrony) |
| host -> backup share (TB_BACKUP_TARGETS), NFS 2049 or SMB 445 | the off-box backup copy (RUNBOOK §5) | TB_BACKUP_TARGETS, a share mounted on the host |

## 機密資訊（僅名稱與位置）

| 機密 | 存放位置 | 提供給 |
| --- | --- | --- |
| model key | deploy/secrets/model/llm.key (0600) | gateway, model-guard only, at /run/secrets/tb_llm_key |
| model key, the vLLM servers' copy (VLLM_API_KEY) | deploy/secrets/model/vllm.env (0600, root) | llm-service, llm-verifier only |
| oidc_client_secret | deploy/secrets/authelia/oidc_client_secret.txt (0600, root) | console only, at /run/secrets/oidc_client_secret (OIDC on) |
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
| TB_DB_PW_<SERVICE> (one role per service) | deploy/.env (0600, root) | db; each service its own only |
| IMAP_PASS, SMTP_PASS | deploy/.env (0600, root) | mail-gateway |
| TB_KEK_PASSPHRASE, TB_KMS_TOKEN (if the KEK back end uses them) | deploy/.env (0600, root) | adapter, orchestrator |
| CLOUD_LLM_API_KEY (empty by default) | deploy/.env (0600, root) | gateway |
| site_hmac.key, pid_map.key, REDCap API tokens | volume tb-secrets (/run/secrets/trialbox) | adapter, orchestrator |
| Caddy's internal CA keys (TB_TLS_MODE=internal) | volume caddy-data | caddy only; never copied out |
| Authelia secrets and the LDAP bind password | deploy/secrets/authelia/ (0600, root) | authelia only |
| backup public key | deploy/secrets/backup.pub | the backup (encrypts only) |
| backup private key | USB stick | 醫院資訊室密封保管；不放在本機 |
| vendor update key (public) | deploy/keys/vendor_ed25519.pub | tools/apply_update.sh |

輪替: sudo python3 -m tools.trialbox secrets rotate [--service 名稱]（RUNBOOK §5「Secrets」）。
