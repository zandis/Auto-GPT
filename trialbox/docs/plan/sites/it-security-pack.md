# TrialBox hospital IT security pack (TB-PLAN-05 WS-13.8)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-02 |
| Version | 0.2 (2026-11-09; revised after the independent plan review PR-10, PR-13, PR-19, PR-28, PR-30) |
| Owner | Changfu Kuo (Aimedics) |
| For | the hospital's IT department (医療情報部 / 資訊室), its security officer and its privacy office |
| Status | Draft. Handed over in W1 as the basis of the IT review; completed with the site's own values and the generated sheets before IQ. Items marked *(generated)* come from the box or the release record; items marked *(at IQ)* are filled on site. |
| Languages | English first; 日本語 in §B and 繁體中文 in §C with the same section numbers. |

## A. English

### A.1 What TrialBox is, in one paragraph

TrialBox is research-support software run inside the hospital. It reads a copy of the hospital's own records (a nightly export, SS-MIX2 storage, HIS views or a FHIR export), replaces chart numbers by pseudonyms at the door, keeps a pseudonymised research repository, counts and lists patients who may meet a study's eligibility criteria, writes cited summaries for study staff, and drafts research-record values for a coordinator to confirm. Two language models run on the hospital's GPU; no text leaves the hospital. The investigator decides; TrialBox never writes to the EMR and never contacts a patient. It is not a medical device (本ソフトウェアは医療機器ではありません / 本軟體非醫療器材，不作為診斷依據).

### A.2 Deployment forms

| Form | Where | What the hospital provides | What Aimedics provides |
| --- | --- | --- | --- |
| **Appliance** (Japan site; the form is decided after the DGX Spark benchmark, TB-PLAN-05 §1.6) | either a DGX Spark (the model pair) linked by an encrypted link to a CPU workstation (Postgres, DuckDB, the console, backups), or one RTX PRO 6000 class workstation; RAM 128 or 256 GB and disk 2 × 2 TB or 2 × 4 TB per the survey's volumes (question 25, 54); UPS; Windows 11 Pro or Enterprise with WSL2 on the workstation; the Spark runs its own Linux | rack or desk, power, network port, device registration for one or two devices, BitLocker recovery-key escrow, NTP, a backup share | the devices pre-installed from signed offline media; the install checklist; the printed sheets |
| **Host OS lifecycle** (appliance) | the Windows host receives security updates as a monthly offline bundle delivered with the TrialBox release (or through the hospital's WSUS if the device may reach it); the hospital's EDR or antivirus agent is allowed on the host with a documented WSL2 exclusion list; the Windows administrator account is held by hospital IT with the password in the key envelope; the Spark's Linux is updated by the same signed release | WSUS or none; the EDR agent and its exclusion list; the administrator account custody | the monthly bundle; the exclusion list; a line in the responsibility-boundary sheet |
| **Containers on the hospital's shared GPU server** (CGMH: the B200 server, shared with other work) | the hospital's container platform with a **dedicated MIG partition** for TrialBox (memory-isolated; a time-slice of SMs is not accepted for patient data), a namespace or project, an encrypted storage class, network policy; the model pair qualified beforehand on a rented cloud B200 with the same MIG profile | the platform, the MIG partition, patching of host OS, runtime and GPU driver, the namespace, storage, isolation from other tenants, the approval for identified patient data on that host, a KMS or HSM for the key-encryption key where the hospital has one | the signed container images and compose or Kubernetes manifests, the install checks that run on the platform (IQ), the network policy the images need, the release record, the B200 qualification record |
| **Interim hosting on the hospital's private cloud with GPU** | until the appliance or the quota is ready, where the site has a private cloud approved for patient data | the same as for the shared server, plus a migration window | the same images; a backup-and-restore migration to the final host |

### A.3 Network and ports *(generated: `docs/handover/network-sheet.*`)*

Only the console port is reachable, and only from the hospital's clients through TLS on 443. Every internal service listens on an internal container network with its own token. Outbound traffic is nothing by default (registries come from the offline reference pack); the hospital may allow its SMTP relay, its NTP server, its directory server and, if it chooses, ClinicalTrials.gov. The egress rules are enforced on the host (appliance) or by the platform's network policy (shared server) and are listed in the generated network sheet with the hosts and the setting that opens each. DNS answers only the allowlist.

| Direction | From | To | Port | Why | Opened by |
| --- | --- | --- | --- | --- | --- |
| in | clinic PCs, PI devices on the hospital network | console (TLS proxy) | 443 | the web console | the hospital firewall rule |
| out | mail service | the hospital SMTP relay | 25 / 587 | the morning mail and notices (pseudonyms and links only) | site setting |
| out | all | the hospital NTP | 123 | time for the audit chain (a FAIL without it) | site setting |
| out | console | the hospital AD/LDAP or OIDC provider | 636 / 443 | sign-in | site setting |
| out | backup job | the hospital NAS share | 445 / 2049 | the encrypted nightly backup | site setting |
| out (optional) | criteria compiler | clinicaltrials.gov | 443 | the live registry, only if chosen at install | `TB_CTGOV_MODE=live` |

No inbound connection from outside the hospital exists. Aimedics has no remote access. Updates arrive as signed files on USB or a file share.

### A.4 Identity and access

Sign-in through the hospital's directory (AD/LDAP or OIDC) with a second factor (TOTP or WebAuthn), or local accounts with TOTP where the directory is not available. Roles: steward, principal investigator, sub-investigator (by delegation), coordinator, clinician, monitor, viewer, administrator. The administrator sees no patient data. Every view of a patient, every reveal of a chart number, every export and every signature is audited with the person, the role, the reason and the time, and kept 10 years. Reveals are rate-limited; access outside a person's lists needs a second person (break-glass) and expires in 24 hours. Study-scoped, expiring accounts fit SMO staff and monitors.

### A.5 Data protection

| Topic | Control |
| --- | --- |
| Pseudonymisation | chart numbers become HMAC pseudonyms at the door with a site key; names, phones and IDs never pass the adapter; the pid map is encrypted per row |
| Data classes | D0 synthetic, D1 study material, D2 aggregate, D3 pseudonymised patient data, D4 identified; D3 and D4 never leave the box; model prompts are refused for any external route |
| At rest | appliance: BitLocker (TPM+PIN) on the host, wrapped site keys, encrypted outputs and uploads; shared server: the platform's encrypted storage class plus the same application-level encryption; backups AES-256-GCM to a key the hospital holds and the box cannot read |
| In transit | TLS 443 to the console; internal tokens per service; no PHI by mail (pseudonyms and links only) |
| Retention | audit 10 years; service logs 365 days; mail logs 5 years (JP) or 7 years (TW); patient data per the hospital's policy; chart originals 1 year after their facts are decided; a written retention table per data kind |
| Opt-out | a consent register the research office maintains; an opt-out removes the patient from screening, profiles, vectors and future exports within minutes and is logged |
| De-identification | anything that leaves the study team is suppressed at k = 5 with controlled rounding; research exports use project pseudonyms, date shifts and k = 5 over quasi-identifiers |
| Destruction | study-level identified lists destroyed at study end; decommissioning by NIST 800-88 purge with a certificate |

### A.6 Shared-host rules (CGMH B200 and any private cloud)

| Topic | Rule | Who |
| --- | --- | --- |
| Isolation | TrialBox runs in its own namespace or project; network policy allows only §A.3; storage is its own encrypted volume; no other tenant can read TrialBox volumes; TrialBox cannot read other tenants' | hospital platform team sets; Aimedics **verifies what it can reach** (egress, an inbound probe from a second namespace, the quota refusal, the image digests) and **receives evidence for the rest** (the storage class specification and its encryption setting, a CIS Kubernetes or Docker benchmark output, a sample of the platform audit log showing a root access to the volume, the MIG configuration dump), attached to the signed supplier assessment at IQ |
| GPU partition | a dedicated MIG partition (memory-isolated) reserved for TrialBox's two models and nightly jobs; recorded in the release record; a change is change-controlled and re-runs the install checks and the canary | hospital platform team |
| Key custody | the key-encryption key for the pid map, the site keys and the `phi` files is never a plain platform Secret: where the hospital operates a KMS or HSM, the KEK lives there and the pod unwraps at start under the platform's audit; otherwise the steward (and at CGMH the second reviewer, 2-of-3 shares with the 資訊室) unseals the key at pod start, the key lives only in the pod's memory (tmpfs, no Secret object), and a restart needs a steward; platform administrators who can read pod memory are named individually in the DPA and the responsibility-boundary sheet, and every secret read the platform logs is alerted to the steward | hospital (KMS) or steward (unseal); Aimedics builds the unseal path |
| Root and administration | the hospital's platform administrators have root on the host; they are named in the responsibility-boundary sheet and their access to TrialBox volumes is logged by the platform; the first-call contact when the morning mail does not arrive is named there too | hospital |
| Patching | host OS, container runtime, GPU driver and platform: the hospital, in announced windows; TrialBox images: Aimedics by signed release; a driver or runtime change re-runs the install checks and the model canary | both, per the responsibility-boundary sheet |
| Install checks | the IQ protocol runs on the platform: image digests, the MIG partition, network policy, NTP, directory, mail relay, backup target, the serving record on the partition, the canary with the other tenants running; storage encryption and root logging by evidence (above) | Aimedics executes (a person who is not the approver of the release record), hospital IT witnesses |
| Incidents | a platform incident that could touch TrialBox volumes is reported to Aimedics and the privacy office within the hospital's clock; TrialBox incidents the other way | both |
| Supplier assessment | the hospital platform is a GAMP 5 category 1 (infrastructure) or 4 (configured platform) component owned by the hospital; its configuration is recorded and verified at IQ, not functionally tested | Aimedics records; hospital confirms |
| Manifests | what the platform team applies (D-211): `deploy/platform/overlays/shared-quota` (the MIG instances; `interim-cloud` for a private cloud with whole cards), built from `deploy/platform/base` (the services and stores, their claims, the NetworkPolicies: default deny, inside the namespace, DNS, only the gateway to the models, the console from the hospital's proxy) with `components/gpu-pair` (judge and verifier, one device each, and the canary job) and `components/release-images` (every image by its `release.json` digest); the egress allowlist and the install-check job's egress (only the declared API server, NTP, directory, mail relay and backup hosts) rendered as NetworkPolicies by `python -m tools.trialbox platform-egress`; on a Docker host instead, `deploy/docker-compose.shared-quota.yml` and `deploy/platform/docker-compose.platform.yml`; the install checks are the `trialbox-doctor` job, which writes `iq-evidence.json` | Aimedics supplies; hospital platform team applies |

### A.7 Release, update and supply chain

Every release has an identity (`release.json`: release id, git commit, image digests, model hashes, schema versions, vocabulary release), a changelog in three languages, a CycloneDX SBOM per image and for the Python dependencies, a third-party notices file, a vulnerability scan result, a test summary and signed images. Updates are signed (Ed25519), verified before anything changes, backed up first, applied whole and rolled back whole; an older release is refused. The hospital's IT officer can verify the signature and the hashes.

### A.8 Monitoring, backup, support

The administrator page shows health, disk, GPU, the last backup and its age, the last ingest, the audit chain verification and every timer's last run; a daily health mail; an optional `/metrics` endpoint and a syslog forwarder for the hospital's monitoring or SIEM (JSON lines, no patient data). Backups run nightly to the hospital's share, compressed and encrypted; **RPO 24 hours** (what is lost in the worst case: one night's ingest, which the next feed replays, and one day's marks and entries, which the audit chain lists); **RTO 4 hours** on the same hardware from the hospital's share and key (measured in the restore drill), longer if the hardware must be replaced; a restore drill runs at IQ and quarterly with hospital IT. Support: a named contact per country, business hours in the site's language, a ticket channel, a PHI-free support bundle the administrator generates; no remote access.

### A.8a Operations and people

| Topic | Answer |
| --- | --- |
| Session controls | sessions end after 8 hours; an idle lock after 10 minutes on shared clinic PCs (configurable per site, never longer than the hospital's policy); re-authentication before a reveal, an export and a signature; one person per account, never a shared account |
| Password policy | at least 12 characters, a breached-password list, last-5 history, a forced change at first sign-in, per-IP delay and lockout with an alert; with the hospital's directory, its policy applies instead |
| Account lifecycle | with AD/LDAP or OIDC, leaving staff lose access when the directory disables them; with local accounts, the trial office's monthly delegation-log comparison lists accounts to close and the administrator closes them the same day; accounts for SMO staff and monitors expire with the contract |
| Vendor people on site | named in the survey (question 69): who, for which steps (install, IQ, OQ, training, PQ support), with the hospital's visitor badge and accounts the hospital issues and closes; no standing vendor account; no remote access |
| Support organisation | a Japanese-speaking first line in JST business hours and a zh-TW line in Taiwan hours, each one named person with a named backup; a ticket channel; severity-based response and resolution times in the SLA; a hardware RMA path; the on-call rota for the first month after go-live is attached to the responsibility-boundary sheet |
| AI in development | TrialBox is developed with AI coding agents under human review; **no agent, developer, repository, build system or log ever receives hospital data** (the data-handling rule TB-SITE-03); agents work from synthetic data and from the hospital's schema and code lists only |
| Logs to the hospital | service logs (patient-data scrubbed) can be forwarded as syslog or JSON lines to the hospital's SIEM; the audit chain's daily signed head is written to the hospital's share |

### A.9 Evidence in the pack *(attached before IQ)*

| Item | Source |
| --- | --- |
| Device security sheet (appliance) or platform description (shared host) | this document §A.2, §A.6 with the site's values |
| Network, port and secret sheet in the site's language | generated by `tools/network_sheet.py` *(generated)* |
| SBOM, third-party notices, vulnerability scan | the release record *(generated)* |
| Release notes and `release.json` | the release record *(generated)* |
| Install, update, backup, restore and decommission procedures | RUNBOOK extracts in the site's language |
| Penetration test letter and remediation | the external pentest *(at G3)* |
| OWASP ASVS 5.0 L2 self-assessment and CIS benchmark output | the acceptance box *(at G2)* |
| Service specification disclosure sheet (サービス仕様適合開示書) and SLA (Japan); SSDLC evidence pack and scan result (Taiwan) | Aimedics |
| ISMS statement mapped to ISO 27002 themes | Aimedics |
| Incident-response plan with the legal clocks; tabletop record | Aimedics and the site *(at PQ)* |
| Data-processing agreement and responsibility-boundary sheet | counsel |
| Intended-use statement and non-device position | TB-DS-16 |
| IRB pack's one-page system description | WS-13.6 |
| Executed IQ and OQ protocols | *(at IQ)* |

### A.10 Answers to the usual questionnaire

| Question | Answer |
| --- | --- |
| Does patient data leave the hospital? | No. Nothing leaves the box or the hospital's platform. Mail carries pseudonyms and links. Aimedics has no remote access and never holds patient data. During the build, developers and AI agents never receive hospital data: they work from synthetic data and the hospital's schema and code lists; the real samples are read on the hospital's hardware by the steward after the agreement is signed and only the adapter's report (counts, no values) leaves (data-handling rule TB-SITE-03). |
| Does the AI send text to a cloud? | No. Two open-weight models run on the hospital's GPU; prompts with patient text are refused for any external route by a policy the box enforces. |
| Who can see chart numbers? | The steward, and the study's PI, sub-investigators and coordinators within their studies, after sign-in with a second factor, with a reason, rate-limited and audited. Viewers, sponsors and administrators never. |
| Can we audit who read a chart and why? | Yes: a report per patient and period from the signed audit chain, kept 10 years. |
| How are updates delivered and verified? | Signed files on USB or a file share; signature and hashes checked before anything changes; one-step rollback. |
| What happens if the box is lost or the disk is removed? | Appliance: BitLocker with the hospital's escrowed key and wrapped application keys; shared host: the platform's encrypted storage. Backups are encrypted to a key only the hospital holds. |
| Is it a medical device? | No. It does not diagnose, treat, decide eligibility, recommend treatment, alert clinicians or contact patients; every output is reviewed by a qualified person. A written regulatory view is being sought. |
| What standards does it follow? | GAMP 5 validation with IQ, OQ and PQ at the site; ISO 14971-style risk file; IEC 62304-style records for the profile module; ER/ES and Part 11-style controls for the research-record path; MHLW 安全管理ガイドライン 7.0 and the 3省2ガイドライン, APPI; Taiwan PDPA, 醫療法 and the EMR regulation, 資通安全管理法 vendor duties; ICH E6(R3). |

## B. 日本語

### B.1 TrialBox とは

TrialBox は病院内で動く臨床研究支援ソフトウェアです。病院自身の記録の複製（夜間出力、SS-MIX2 ストレージ、HIS ビュー、FHIR 出力）を読み、入口で患者番号を仮名に置き換え、仮名化した研究用リポジトリを保持し、研究の参加条件に合う可能性のある患者を数え・一覧にし、研究スタッフ向けに引用付きの要約を作成し、コーディネーターが確認するための研究記録値の下書きを作ります。2 つの言語モデルは病院の GPU 上で動き、文章は病院外に出ません。判断は医師が行います。TrialBox は電子カルテに書き込まず、患者に連絡しません。本ソフトウェアは医療機器ではありません。

### B.2 導入形態

アプライアンス（日本サイト）：院内ネットワーク内の専用ワークステーション（RTX PRO 6000 級 GPU、256 GB RAM、2 TB NVMe × 2 ミラー、UPS、Windows 11 Pro/Enterprise と WSL2、2 枚目の GPU 用の余裕）。病院側は設置場所、電源、ネットワークポート、端末登録、BitLocker 回復キーの預託、NTP、バックアップ共有を用意します。Aimedics は署名付きオフライン媒体で事前インストールした本体、導入チェックリスト、印刷シートを提供します。病院の共用 GPU サーバ上のコンテナ（長庚：他業務と共用の B200 サーバ）：病院のコンテナ基盤、固定 GPU クォータ、TrialBox 用ネームスペース、暗号化ストレージ、ネットワークポリシー。病院側は基盤、クォータ、ホスト OS・ランタイム・GPU ドライバのパッチ、分離、識別可能な患者データの取り扱い承認を担い、Aimedics は署名付きイメージとマニフェスト、基盤上で動く導入チェック（IQ）、必要なネットワークポリシー、リリース記録を提供します。ハードウェア準備までの暫定ホスティング：患者データの取り扱いが承認された病院プライベートクラウド（GPU 付き）。同じイメージを使い、バックアップと復元で最終ホストへ移行します。

### B.3 ネットワークとポート（生成物：network-sheet.ja）

外部から到達できるのはコンソールのポートのみで、院内の端末から TLS（443）経由に限られます。内部サービスはコンテナ内部ネットワークで各自のトークンにより通信します。外向き通信は既定でなし（登録情報はオフラインの参照データパックから）。病院の判断で SMTP リレー、NTP、ディレクトリサーバ、必要なら ClinicalTrials.gov を許可できます。外向き規則はホスト（アプライアンス）または基盤のネットワークポリシー（共用サーバ）で強制され、生成されるネットワークシートに宛先と設定が列挙されます。DNS は許可リストのみに応答します。院外からの着信接続はありません。Aimedics のリモートアクセスはありません。更新は USB またはファイル共有の署名付きファイルで届きます。

### B.4 認証とアクセス

病院のディレクトリ（AD/LDAP または OIDC）と第二要素（TOTP または WebAuthn）でサインイン。ディレクトリがない場合はローカルアカウントと TOTP。役割：データスチュワード、治験責任医師、分担医師（委任による）、コーディネーター、主治医、モニター、閲覧者、管理者。管理者は患者データを見ません。患者の閲覧、患者番号の表示、出力、署名はすべて人物・役割・理由・時刻とともに監査記録され、10 年保存されます。表示には回数制限があり、自分のリスト外の患者へのアクセスは第二の承認者が必要で 24 時間で失効します。期限付き・試験限定のアカウントは SMO スタッフとモニターに適合します。

### B.5 データ保護

仮名化：患者番号は入口でサイト鍵による HMAC 仮名に置き換え、氏名・電話・ID はアダプタを通過しません。pid マップは行ごとに暗号化。データ区分：D0 合成、D1 研究資料、D2 集計、D3 仮名化患者データ、D4 識別可能。D3・D4 はボックス外に出ず、モデルへの入力は外部経路では拒否されます。保存時：アプライアンスでは BitLocker（TPM+PIN）とラップされたサイト鍵、暗号化された出力とアップロード。共用サーバでは基盤の暗号化ストレージに加え同じアプリ側暗号化。バックアップは病院のみが持つ鍵への AES-256-GCM で、ボックス自身は復号できません。通信時：コンソールは TLS 443、内部はサービスごとのトークン、メールに患者情報なし。保存期間：監査 10 年、サービスログ 365 日、メールログ 5 年、患者データは病院の方針、カルテ原本は事実確定後 1 年、データ種別ごとの保存表。オプトアウト：研究事務局が管理する同意台帳。登録後数分以内にスクリーニング、プロファイル、ベクトル、今後の出力から除外され記録されます。匿名化：研究チーム外に出るものは k=5 と丸めで抑制。廃棄：試験終了時に識別可能リストを廃棄、撤去時は NIST 800-88 準拠の消去と証明書。

### B.6 共用ホストの規則（長庚 B200 および私設クラウド）

分離：TrialBox 専用のネームスペース、§B.3 のみを許すネットワークポリシー、専用の暗号化ボリューム、他テナントとの相互読み取り不可（病院の基盤チームが設定。Aimedics は IQ で到達できる範囲（外向き通信、別ネームスペースからの探査、クォータの拒否、イメージのダイジェスト）を検証し、残り（ストレージクラスの暗号化設定、CIS ベンチマーク結果、ボリュームへの root アクセスを示す基盤監査ログの抜粋、MIG 設定の出力）は基盤側の証拠として署名済み供給者評価に添付）。GPU パーティション：2 モデルと夜間処理のための**専用 MIG パーティション**（メモリ分離。SM の時分割は患者データには不可）をリリース記録に記載、変更は変更管理の対象で導入チェックとカナリアを再実行。鍵の保管：pid マップ、サイト鍵、`phi` ファイルの鍵暗号化鍵を基盤の Secret に平文で置かない。病院に KMS または HSM があればそこに保管し起動時に基盤の監査下で復号する。なければスチュワード（長庚では第二審査者と情報室で 2-of-3 分散）が pod 起動時に解錠し、鍵はメモリ（tmpfs）にのみ存在し、再起動にはスチュワードが必要。pod メモリを読める基盤管理者は DPA と責任分界表に個人名で記載し、基盤が記録するすべての secret 読み取りをスチュワードに通知する。root と管理：病院の基盤管理者がホストの root を持ち、責任分界表に氏名を記載、TrialBox ボリュームへのアクセスは基盤側で記録。パッチ：ホスト OS・ランタイム・GPU ドライバ・基盤は病院が予告した時間帯に、TrialBox イメージは Aimedics が署名付きリリースで。ドライバやランタイムの変更後は導入チェックとモデルのカナリアを再実行。導入チェック（IQ）：イメージのダイジェスト、クォータ、ネットワークポリシー、ストレージ暗号化、NTP、ディレクトリ、メールリレー、バックアップ先、クォータ上でのサービング記録、カナリア。インシデント：TrialBox のボリュームに影響しうる基盤側インシデントは病院の期限内に Aimedics と個人情報保護管理者へ、逆も同様。供給者評価：病院の基盤は GAMP 5 カテゴリ 1（インフラ）または 4（構成済み基盤）の病院所有コンポーネントとして構成を記録し IQ で検証、機能試験は行いません。

### B.7 リリース、更新、サプライチェーン

各リリースは識別情報（release.json：リリース ID、コミット、イメージダイジェスト、モデルハッシュ、スキーマ版、語彙リリース）、3 言語の変更履歴、イメージごとと Python 依存の CycloneDX SBOM、第三者ライセンス一覧、脆弱性スキャン結果、試験サマリ、署名付きイメージを持ちます。更新は Ed25519 署名で検証後に適用、事前バックアップ、一括適用と一括ロールバック、古いリリースは拒否。病院の IT 担当者が署名とハッシュを検証できます。

### B.8 監視、バックアップ、保守

管理者ページに健全性、ディスク、GPU、最終バックアップとその経過時間、最終取り込み、監査チェーン検証、各タイマーの最終実行を表示。日次のヘルスメール。病院監視向けの任意の /metrics。バックアップは毎夜、病院の共有へ圧縮・暗号化して保存。復元訓練は IQ 時と四半期ごとに病院 IT と実施。保守：国ごとの担当者、サイト言語での営業時間対応、チケット窓口、管理者が生成する患者情報を含まない保守バンドル。リモートアクセスなし。

### B.9 パックに含める証拠

§A.9 の表と同じ：端末セキュリティシート（アプライアンス）または基盤説明（共用ホスト）、ネットワーク・ポート・秘密情報シート（日本語）、SBOM・第三者ライセンス・脆弱性スキャン、リリースノートと release.json、導入・更新・バックアップ・復元・撤去手順、ペネトレーションテスト報告書、OWASP ASVS 5.0 L2 自己評価と CIS ベンチマーク結果、サービス仕様適合開示書と SLA、ISMS 宣言、インシデント対応計画と机上訓練記録、データ処理契約（委託契約）と責任分界表、使用目的の記載と非医療機器の立場、倫理審査向けの一枚のシステム説明、実施済み IQ・OQ プロトコル。

### B.10 よくある質問への回答

患者データは病院外に出ますか：出ません。開発中も開発者と AI エージェントは病院のデータに触れず、合成データと病院のテーブル構造・コード一覧のみを使います。実サンプルは契約締結後に院内機器上でスチュワードが読み込み、数値を含まない報告書だけが院外に出ます（データ取扱規則 TB-SITE-03）。AI は文章をクラウドに送りますか：送りません。2 つのオープンウェイトモデルが病院の GPU で動き、患者文章を含む入力は外部経路では拒否されます。患者番号を見られるのは誰ですか：スチュワードと、当該試験の責任医師・分担医師・コーディネーターが、第二要素サインイン後、理由を記録し、回数制限と監査のもとで。閲覧者、依頼者、管理者は見られません。誰がどのカルテをなぜ読んだか監査できますか：できます。署名付き監査チェーンから患者・期間ごとの報告を出せ、10 年保存します。更新はどう届き検証されますか：USB またはファイル共有の署名付きファイル。変更前に署名とハッシュを検証、一手順でロールバック。本体やディスクが失われたら：アプライアンスは BitLocker と預託鍵、ラップされたアプリ鍵。共用ホストは基盤の暗号化ストレージ。バックアップは病院のみが持つ鍵で暗号化。医療機器ですか：いいえ。診断・治療・適格性判定・治療推奨・医師への警告・患者連絡を行わず、すべての出力は有資格者が確認します。該当性に関する文書化された見解を取得中です。準拠する基準：GAMP 5（施設での IQ/OQ/PQ）、ISO 14971 型のリスク文書、プロファイルモジュールの IEC 62304 型記録、研究記録経路の ER/ES 指針と Part 11 型管理、医療情報システムの安全管理に関するガイドライン 7.0 と 3省2ガイドライン、個人情報保護法、ICH E6(R3)。

## C. 繁體中文

### C.1 TrialBox 是什麼

TrialBox 是在醫院內運行的臨床研究支援軟體。它讀取醫院自有病歷的副本（每夜匯出、HIS 檢視表或 FHIR 匯出），在入口將病歷號換成假名，維護**假名化**（而非去識別化）的研究資料庫：經授權的角色（資料管理人、該研究的主持人、協同主持人與研究協調員）可透過保存在院方平台的金鑰再識別病人，每次再識別皆留下稽核紀錄；「去識別化」僅適用於 §C.5 所述離開研究團隊的匯出。它計算並列出可能符合研究收案條件的病人，為研究人員撰寫逐句引用的摘要，並草擬研究紀錄值供研究協調員確認。兩個語言模型在醫院的 GPU 上執行，文字不離開醫院。由主持人判斷；TrialBox 不寫入電子病歷，不聯繫病人。本軟體非醫療器材，不作為診斷依據。

### C.2 佈署形式

專用主機（日本站）：院內網路中的專用工作站（RTX PRO 6000 級 GPU、256 GB RAM、2 TB NVMe × 2 鏡射、UPS、Windows 11 Pro/Enterprise 與 WSL2，預留第二張 GPU）；院方提供機櫃或桌面、電源、網路埠、設備登錄、BitLocker 復原金鑰託管、NTP、備份共享；Aimedics 提供以簽署離線媒體預先安裝的主機、安裝檢核表與列印表單。醫院共用 GPU 伺服器上的容器（長庚：與其他工作共用的 B200 伺服器）：醫院的容器平台、固定 GPU 配額、TrialBox 專用 namespace、加密儲存、網路政策；院方負責平台、配額、主機作業系統、容器執行環境與 GPU 驅動程式的更新、與其他租戶的隔離，以及該主機處理可識別病人資料的核准；Aimedics 提供簽署的容器映像與部署描述檔、可在平台上執行的安裝檢查（IQ）、所需的網路政策與發布紀錄。硬體就位前的暫時主機：院方已核准處理病人資料、具 GPU 的私有雲；使用相同映像，之後以備份還原遷移至最終主機。

### C.3 網路與連接埠（產生物：network-sheet.zh-TW）

僅主控台連接埠可被連入，且只接受院內端末經 TLS（443）連線。內部服務在容器內部網路以各自的 token 通訊。對外連線預設為無（登錄資料來自離線參考資料包）；院方可選擇允許 SMTP 中繼、NTP、目錄伺服器，以及必要時的 ClinicalTrials.gov。對外規則由主機（專用主機）或平台網路政策（共用伺服器）強制執行，產生的網路表列出每個目的地與開啟它的設定。DNS 只回應允許清單。沒有來自院外的連入連線。Aimedics 沒有遠端存取。更新以 USB 或檔案共享上的簽署檔案送達。

### C.4 身分與存取

透過醫院目錄服務（AD/LDAP 或 OIDC）加第二因子（TOTP 或 WebAuthn）登入；無目錄服務時使用本地帳號加 TOTP。角色：資料管理人、試驗主持人、協同主持人（依授權）、研究協調員、主治醫師、監測員、檢視者、管理者。管理者看不到病人資料。限定試驗且有期限的帳號適用於 SMO 人員與監測員。每次檢視病人、揭露病歷號、匯出與簽署都連同人員、角色、理由與時間留下稽核紀錄，保存 10 年。揭露有速率限制；存取名單外的病人需第二人核准（break-glass）且 24 小時失效。限定試驗且有期限的帳號適用於監測員。

### C.5 資料保護

假名化：病歷號在入口以院方金鑰 HMAC 換成假名；姓名、電話與身分證號不通過轉接層；pid 對照表逐列加密。資料分級：D0 合成、D1 研究文件、D2 彙總、D3 假名化病人資料、D4 可識別；D3 與 D4 不離開主機，含病人文字的模型提示在任何外部路徑都被拒絕。靜態：專用主機以 BitLocker（TPM+PIN）與包裝後的站點金鑰、加密的輸出與上傳；共用伺服器以平台加密儲存加上相同的應用層加密；備份以 AES-256-GCM 加密至僅院方持有的金鑰，主機本身無法解密。傳輸：主控台 TLS 443；內部各服務 token；郵件不含病人資料。保存：稽核 10 年；服務日誌 365 天；郵件日誌 7 年（台灣）；病人資料依院方政策；病歷原件於事實確認後 1 年；每種資料的保存表。退出：由研究辦公室維護的同意登錄；登錄後數分鐘內自篩選、概況、向量與未來匯出移除並留下紀錄。去識別化：離開研究團隊的任何資料以 k=5 與控制四捨五入抑制；研究匯出使用專案假名、日期位移與準識別碼的 k=5。銷毀：試驗結束銷毀可識別名單；汰除依 NIST 800-88 清除並出具證明。

### C.6 共用主機規則（長庚 B200 與任何私有雲）

隔離：TrialBox 使用專用 namespace；網路政策僅允許 §C.3；專用加密儲存卷；其他租戶無法讀取 TrialBox 的儲存卷，TrialBox 亦無法讀取他人的（院方平台團隊設定；Aimedics 於 IQ 驗證其可觸及的部分（對外連線、自另一 namespace 的探測、配額拒絕、映像摘要），其餘（儲存類別的加密設定、CIS 基準結果、平台稽核紀錄中 root 存取儲存卷的樣本、MIG 設定輸出）由平台提供證據並附於簽署的供應商評估）。GPU 分割：為兩個模型與夜間作業保留**專用 MIG 分割**（記憶體隔離；SM 時間切片不適用於病人資料），記錄於發布紀錄；變更屬變更管制事件並重跑安裝檢查與金絲雀測試。金鑰保管：pid 對照表、站點金鑰與 `phi` 檔案的金鑰加密金鑰不以平台 Secret 明文存放；院方如有 KMS 或 HSM 則存於其中並在平台稽核下於啟動時解封；否則由資料管理人（長庚另加第二審核人，與資訊室 2-of-3 分持）於 pod 啟動時解封，金鑰僅存在記憶體（tmpfs），重啟需資料管理人；可讀取 pod 記憶體的平台管理者於 DPA 與責任分界表逐一列名，平台記錄的每次 secret 讀取皆通知資料管理人。Root 與管理：院方平台管理者擁有主機 root，列名於責任分界表，其對 TrialBox 儲存卷的存取由平台記錄。更新：主機作業系統、容器執行環境、GPU 驅動程式與平台由院方在公告時段更新；TrialBox 映像由 Aimedics 以簽署發布更新；驅動程式或執行環境變更後重新執行安裝檢查與模型金絲雀測試。安裝檢查（IQ）：映像摘要、配額、網路政策、儲存加密、NTP、目錄服務、郵件中繼、備份目標、配額上的服務紀錄、金絲雀測試。事件：可能影響 TrialBox 儲存卷的平台事件在院方時限內通報 Aimedics 與個資保護人員，反之亦然。供應商評估：院方平台視為 GAMP 5 第 1 類（基礎設施）或第 4 類（已設定平台）的院方自有元件，記錄其設定並於 IQ 驗證，不做功能測試。

### C.7 發布、更新與供應鏈

每次發布具備識別資訊（release.json：發布代號、提交碼、映像摘要、模型雜湊、資料結構版本、詞彙版本）、三語變更紀錄、每個映像與 Python 依賴的 CycloneDX SBOM、第三方授權清單、弱點掃描結果、測試摘要與簽署映像。更新以 Ed25519 簽署，變更前驗證，先備份，整體套用與整體回復，拒絕較舊版本。院方資安人員可驗證簽章與雜湊。

### C.8 監控、備份、支援

管理者頁面顯示健康狀態、磁碟、GPU、最後備份與其時間、最後匯入、稽核鏈驗證、各排程最後執行；每日健康郵件；可供院方監控的選用 /metrics。備份每夜壓縮加密後存至院方共享；還原演練於 IQ 與每季與院方資訊室執行。支援：各國指定聯絡人、以站點語言的上班時間支援、工單管道、由管理者產生且不含病人資料的支援包；無遠端存取。

### C.9 資料包所含證據

與 §A.9 相同：設備資安表（專用主機）或平台說明（共用主機）、網路與連接埠與機密表（繁體中文）、SBOM、第三方授權、弱點掃描、發布說明與 release.json、安裝、更新、備份、還原與汰除程序、滲透測試報告、OWASP ASVS 5.0 L2 自評與 CIS 基準結果、SSDLC 證據包與掃描結果、ISMS 聲明、事件應變計畫與桌上演練紀錄、資料處理契約與責任分界表、預期用途聲明與非醫療器材立場、IRB 用的一頁系統說明、已執行的 IQ 與 OQ 程序。

### C.10 常見問題的回答

病人資料會離開醫院嗎：不會；開發期間開發人員與 AI 代理亦不接觸院方資料，僅使用合成資料與院方的欄位結構及代碼清單，真實樣本由資料管理人於契約簽署後在院方硬體上讀取，只有不含數值的報告離開（資料處理規則 TB-SITE-03）。本系統為假名化而非去識別化：經授權角色可在稽核下再識別。AI 會把文字送到雲端嗎：不會；兩個開放權重模型在院方 GPU 上執行，含病人文字的提示在任何外部路徑都被拒絕。誰能看到病歷號：資料管理人，以及該試驗的主持人、協同主持人與研究協調員，在第二因子登入、記錄理由、速率限制與稽核下；檢視者、委託者與管理者不能。能否稽核誰為何讀了哪份病歷：能，自簽署的稽核鏈產出每位病人、每段期間的報告，保存 10 年。更新如何送達與驗證：USB 或檔案共享上的簽署檔案，變更前驗證簽章與雜湊，一步回復。主機或磁碟遺失怎麼辦：專用主機有 BitLocker 與託管金鑰及包裝的應用金鑰；共用主機有平台加密儲存；備份以僅院方持有的金鑰加密。是醫療器材嗎：不是；不診斷、不治療、不判定資格、不建議治療、不警示醫師、不聯繫病人；所有輸出由合格人員審閱；正在尋求書面的法規見解。遵循哪些標準：GAMP 5（院內 IQ/OQ/PQ）、ISO 14971 型風險檔、概況模組的 IEC 62304 型紀錄、研究紀錄路徑的 ER/ES 與 Part 11 型控制、個人資料保護法、醫療法與電子病歷辦法、資通安全管理法的供應商義務、ICH E6(R3)。
