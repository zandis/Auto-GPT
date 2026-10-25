## 14. Security

This section replaces v3 §10.1–§10.3 and the anchoring rule of v3 §10.5. It does not redefine functions owned
elsewhere:
- data classes and privacy-enhancing technologies: §7;
- the LLM control plane: §8;
- Hermes: §9;
- approvals and signing: §3 and §11;
- RPO/RTO and availability: §13.

§14 states the objectives, the threat model and the controls, and allocates every control to a component (§14.16). The
allocation also exists as `docs/security/allocation.yaml`. `tools/security_matrix.py` checks it in CI against the
`@req` markers in `tests/security/` and the threat model in `docs/security/threat_model/`.

Milestones follow §20, which governs:

| Milestone | Scope |
| --- | --- |
| MS0 | Foundations; synthetic and open data |
| MS1 | De-identified feasibility at site 1 |
| MS2 | Silent pre-screening; first identifiable PHI; open-study patient → trials (silent) |
| MS3 | Live wave 1 |
| MS4 | Recruitment engine, Teams, registry patient → trials and tumour board, topology C for D1 (if decided) |
| MS5 | Conduct and data, eSource, SAE clocks, CDS Hooks card |
| MS6 | Second site and the Japan profile |

### 14.1 Security objectives, scope and assumptions

| SO | Objective | Measured by |
| --- | --- | --- |
| SO-1 | **D3/D4 confidentiality.** No D3/D4 content leaves the topology's perimeter (§7), except to delegated recipients over approved channels (SEC-10, SEC-13). | Egress tests; outbound DLP; zero capability-bearing `redteam` successes |
| SO-2 | **Integrity of regulated records.** Approvals, signatures, the ledger, rulesets and released packets cannot change undetected. | `audit_verify`; FR-SIG-4 negatives |
| SO-3 | **Artefact provenance.** Code, images, models, adapters, prompts, lexicon, exemplars, skills and MCP tool definitions load only if signed, hash-verified and approved through G5. | Load-time and tamper tests |
| SO-4 | **Bounded agency.** No model or agent, compromised or not, causes a consequential action without deterministic policy. Under the PUX rule (§14.8.1) a human must also approve. | `sec_pux`, `sec_mcp_pin`, `redteam` |
| SO-5 | **Survive hospital compromise.** A fallen directory, LAN ransomware or a compromised vendor laptop neither controls TrialBox nor destroys its records. | AD-down test; full-site restore drill |
| SO-6 | **Detect and report in time.** Every security event reaches the SOC PHI-free within 60 s. The hospital can file within a 1-hour clock. | `sec_siem_contract`; tabletop timings |
| SO-7 | **Evidence by construction.** Each control maps to standards and to a test collected by `trialbox validate`. | Generated trace matrix (§15.2) |

**Assumptions.**
- The hospital is the controller. In Taiwan a hospital may be a critical-infrastructure (CI) provider and therefore a
  specific non-government agency (特定非公務機關).
- The vendor is a processor and outsourced supplier: 委外廠商 in Taiwan, 医療情報システム等の提供事業者 in Japan.
- TrialBox is not a medical device (§15.3). Device security frameworks serve as a benchmark only.
- The hospital normally provides the IdP, mail, SOC/SIEM, NTP, perimeter firewall and physical security. Requirements
  name fallbacks where these are missing.
- TrialBox is designed to the **high** level of the Taiwan 資通系統防護基準. The rating each hospital assigns is
  *(uncertain)*.

**Components** (labels K1–K21, used throughout §14):

| K | Component |
| --- | --- |
| K1 | Hardware, firmware, BMC/EC (GB10-class or x86 + GPU) |
| K2 | Host OS, kernel, drivers |
| K3 | Container runtime (rootless Podman; k3s optional) |
| K4 | Model serving (`llm-service`: vLLM / llama.cpp), weights, adapters, embedder, reranker |
| K5 | LLM control plane: `tb-gateway`, registry, guardrails, trace store (§8) |
| K6 | Orchestrator: workflows, gates, policy module, privacy accountant, outbox |
| K7 | MCP tool servers: front-door server (§9) and internal T0–T3 servers |
| K8 | Hermes Agent |
| K9 | Native channel and mail-gateway, including the CDR sandbox, S/MIME and 7z |
| K10 | Teams and LINE connectors |
| K11 | Ingestion L0–L3: HIS views + CDC, HL7 v2 MLLP listener, FHIR Bulk / SMART Backend Services, CGRD/TRE, CSV/registry, cohort, NHI (§5) |
| K12 | Data stores: L4/L5, OMOP, FHIR store, PostgreSQL, object store, vector index, judgement cache, D4 vault, criterion library, lexicon, exemplars |
| K13 | Admin control plane (console + `trialbox` CLI) |
| K14 | End-user listeners: signing page, review page, CDS Hooks service |
| K15 | Key management and internal PKI (OpenBao) |
| K16 | Network enforcement: nftables per container and the `tb-egress` proxy |
| K17 | Audit ledger, observability, SIEM forwarder |
| K18 | Backup and restore |
| K19 | Build, release, update and model-intake pipeline |
| K20 | Vendor remote-support path |
| K21 | Topology B cloud tenant and topology C cloud model endpoints |

### 14.2 Applicable frameworks

#### 14.2.1 Taiwan

| Instrument | Status | Duty and TrialBox response |
| --- | --- | --- |
| 資通安全管理法 (Cyber Security Management Act), 2025 amendment | Passed 29 Aug 2025; promulgated 24 Sep 2025. Competent authority: MODA, with its Administration for Cyber Security (ACS) executing. Effective 1 Dec 2025 per Executive Yuan order 院臺安字第1141033966號 *(uncertain whether every article)*. | CI hospitals need a CISO (資通安全長) and dedicated staff, outsourcing (委外) supervision and product restrictions. A failure to report can be fined up to NT$10 million *(reported; uncertain)*. **Response:** outsourcing evidence (CMP-54); provenance register (SEC-66). |
| CI hospital designation by MOHW | Reported counts are 46–64 hospitals *(uncertain)*. Private medical centres are responsibility level A. MOHW–ACS medical-CI programme announced 15 Aug 2025. | Deputy-head-level CISO; drills; ISO/IEC 27001 used as an accreditation indicator. **Response:** joint tabletop (SEC-115). |
| 資通安全事件通報應變及演練辦法 (amended 5 Jan 2026; article numbers from the Taipei municipal copy *(uncertain)*) | In force | A specific non-government agency reports **within 1 h of awareness** via the MOHW-designated channel (Art. 11). Recovery is due within **72 h** (levels 1–2) or **36 h** (levels 3–4) (Art. 13). **Response:** vendor notice ≤ 30 min and incident record ≤ 45 min (SEC-111); full restore ≤ 36 h (SEC-97). |
| 資通安全責任等級分級辦法 and 資通系統防護基準 | Baseline derived from NIST SP 800-53 | **Response:** design to "high"; ship a mapping per release (SEC-141). |
| 醫療機構電子病歷製作及管理辦法 (EMR Regulation, 2022) | In force | Cloud or outsourced EMR processing needs a written contract, a certified contractor, encrypted transmission, and **storage in Taiwan unless MOHW approves**. **Response:** topology B in Taiwan regions only (CMP-53). |
| 個人資料保護法 (PDPA), amended 11 Nov 2025 | Effective date and deadline set by implementing rules *(uncertain; drafts used 72 h)* | Notify the new PDPC and data subjects of breaches (Art. 12); keep security measures (Art. 27). **Response:** SEC-113. |
| MODA product restrictions | Public-sector bans (e.g. DeepSeek). Extension to CI hospitals is possible *(uncertain whether any model family is listed)*. | **Response:** model provenance register and site exclusion policy (SEC-66). |

#### 14.2.2 Japan

| Instrument | Status | Duty and TrialBox response |
| --- | --- | --- |
| MHLW 医療情報システムの安全管理に関するガイドライン **第6.0版** | 31 May 2023. A 第7.0版 (June 2026) is reported *(uncertain)*. | Medical Care Act Enforcement Ordinance Art. 14(2) (since 1 Apr 2023) requires measures per the latest guideline. Prefectures inspect with the annual MHLW checklist (FY2025 added password length, external-device limits and 2FA). **Response:** mapping and checklist vendor sheet; gap assessment if 7.0 is confirmed (SEC-142). |
| MIC/METI 医療情報を取り扱う情報システム・サービスの提供事業者における安全管理ガイドライン **v2.0** | 28 Mar 2025 | Vendor risk assessment, responsibility split and service-specification disclosure. **Response:** MDS/SDS and 責任分界表 (SEC-142). |
| サイバー対処能力強化法 and the Economic Security Promotion Act core-infrastructure amendment | Enacted 16 May 2025; main provisions reportedly from 1 Oct 2026. Hospital designation *(uncertain)*. | Designated hospitals report incidents and pre-notify critical equipment (about 30-day review). **Response:** a stable BOM and supplier list with countries of origin (SEC-62, SEC-66). |
| APPI | Leak reports to the PPC: preliminary in about 3–5 days; final in 30 days, or 60 days for unauthorised access *(uncertain)*. Law No. 56 promulgated 17 Jul 2026 *(secondary)*. | **Response:** Japan clock profile (SEC-113). |

#### 14.2.3 International frameworks and target levels

| Framework (version) | Use |
| --- | --- |
| NIST CSF 2.0 (Feb 2024); SP 800-53 Rev. 5; SP 800-171 Rev. 3 (May 2024) | Top-level mapping; control catalogue cross-walked to 防護基準; minimum baseline for the vendor environment (SEC-125). COSAIS AI overlays tracked *(draft status uncertain)*. |
| SP 800-61r3 (Apr 2025); SP 800-218 (SSDF 1.1) and 800-218A (Jul 2024); SP 800-207, 800-193, 800-40r4, 800-63B-4, 800-92 | Incident response; secure SDLC including generative AI; zero trust; firmware resiliency; patching; authenticators; logging. |
| NIST AI 100-2 E2025; AI RMF 1.0 with AI 600-1 | Adversarial-ML taxonomy; AI risk taxonomy (§15.4). |
| ISO/IEC 27001:2022, 27017:2015, 27018:2019, 27701 (2025 standalone edition *(uncertain)*), ISO 27799:2016, ISO/IEC 42001:2023 | Vendor ISMS; cloud controls (B/C); privacy management; health guidance; AI management. |
| IEC 62443-4-1:2018, -4-2:2019, -3-3:2013, -2-4; IEC 81001-5-1:2021 | Product SDL; component and system requirements; service provider (remote support); health-software security life cycle. |
| FDA *Cybersecurity in Medical Devices* premarket guidance (current version reported as Feb 2026 *(uncertain)*) | **Benchmark only**: secure product development framework, threat model, security risk separate from safety, SBOM with support status, architecture views, testing, postmarket plan. |
| ANSI/NEMA HN 1-2019 (MDS2); HITRUST CSF v11 and AI Security Assessment (Dec 2024) | Procurement questionnaire per release; HITRUST on sponsor demand. |
| OWASP ASVS 5.0 (May 2025); OWASP LLM Top 10 2025; OWASP Agentic Top 10 2026 (Dec 2025); OWASP MCP Top 10 (2025, beta); MITRE ATT&CK; MITRE ATLAS | Verification levels and threat categories. |
| CIS Ubuntu benchmark; SLSA v1.1; CycloneDX 1.6 (ECMA-424); SPDX 3.0; CSAF 2.0; OpenVEX; TUF 1.0; Sigstore | Hardening and supply chain (§14.7). |

**Target levels.**
- IEC 62443-4-2 **SL2** for the appliance, with **SL3** for FR1 (identification and authentication) and FR4 (data
  confidentiality).
- OWASP ASVS 5.0 **L3** for the signing page, admin console, authentication and audit modules; **L2** for the review
  page, CDS Hooks and APIs.
- NIST SP 800-63B-4 **AAL3** for admins and signers where the IdP supports it; AAL2 phishing-resistant as the floor.
- 防護基準 **high**.

### 14.3 Threat model

#### 14.3.1 Method

The threat model is code: a pytm model at `docs/security/threat_model/tm.py` renders the data-flow diagram and the
STRIDE findings per element and boundary crossing. Four further lenses are applied:
- privacy: LINDDUN GO;
- intrusion techniques: ATT&CK labels;
- AI attacks: ATLAS labels;
- LLM, agent and MCP threats: OWASP LLM 2025, Agentic 2026 and MCP Top 10.

The model is re-run, and its delta reviewed, whenever a release adds or changes a tool, connector, source, route,
channel, listener or topology. That review is a blocking gate (SEC-120).

#### 14.3.2 Trust boundaries

| TB | Boundary | Crossing |
| --- | --- | --- |
| TB1 | Internet, M365, LINE, vendor ↔ hospital perimeter | Mail, Teams activities, nudges, updates, registry pulls, cloud calls |
| TB2 | Hospital LAN ↔ TrialBox listeners | Users, HIS/LIS/MLLP, IdP, SIEM, NTP |
| TB3 | Channel layer (K8–K10) ↔ orchestrator via the front-door MCP | Typed requests and status; no PHI tools |
| TB4 | Models ↔ everything | **Model output is untrusted** |
| TB5 | D3/D4 data zone ↔ other zones | T2 reads within delegated steps |
| TB6 | Vendor build ↔ appliance | Images, bundles, models, prompts, skills |
| TB7 | Appliance ↔ backup targets | Encrypted backups, anchors |
| TB8 | Perimeter ↔ cloud tenant and endpoints (B/C) | D0–D2 prompts (C); the whole appliance (B) |
| TB9 | Vendor support ↔ appliance | Support sessions |

#### 14.3.3 STRIDE

| Threat | TB | Example | Controls |
| --- | --- | --- | --- |
| Spoofing | TB1/TB2 | A spoofed "PI" email asks for a list; a quoted display name defeats an allowlist (a Hermes 0.21.6 fix class); a forged Teams identity | SEC-4, SEC-21, SEC-13; Level A hash binding; Level B |
| Spoofing | TB3 | A channel process asserts a user it did not authenticate | Signed user assertion (SEC-26) |
| Tampering | TB6/TB5 | Altered weights, LoRA, prompt or image; edited ledger row; record changed after signature | SEC-60–SEC-65; ledger (§11); SEC-90; FR-SIG-4 |
| Repudiation | TB2 | An investigator denies a Level B signature | WebAuthn assertion over the record hash; trusted time (SEC-53) |
| Information disclosure | TB4/TB1/TB8 | Injected instruction exfiltrates PHI in a reply or a markdown-image URL; cloud retention or cross-region routing | SEC-70, SEC-75, SEC-13; §8 class policy; SEC-79 |
| Denial of service | TB2 | LAN ransomware encrypts shares and the backup NAS; mail flood; GPU exhaustion (LLM10) | SEC-95–SEC-99; §8 budgets; segmentation |
| Elevation of privilege | TB3/TB4 | Confused-deputy agent; container escape; console RCE | SEC-25, SEC-71, SEC-52; ASVS L3 |

#### 14.3.4 LINDDUN

| Threat | Instance | Controls |
| --- | --- | --- |
| Linking, identifying | Free-text evidence re-identifies a patient; joins across D2 exports; similarity search over embeddings recovers notes | Per-project keys and the D2 release check (§7); indexes classed D3 with retrieval ACLs (SEC-80) |
| Detecting | Membership in a corpus reveals enrolment; membership inference on adapters | Delegated recipients only; SEC-84 |
| Data disclosure | Whole-mailbox connectors; prompts kept in traces | SEC-27; trace redaction (§8); SEC-83 |
| Unawareness, non-compliance | Patients unaware of AI processing; D2 sent abroad without analysis | AI disclosure for IRB and hospital notices (§7; TW/JP IRB expectations *(uncertain)*); CMP-80, CMP-81 |

#### 14.3.5 ATT&CK techniques from healthcare intrusions

| Technique | Seen in | Design response |
| --- | --- | --- |
| T1133 External Remote Services; T1078 Valid Accounts | **Osaka General Medical Center (Oct 2022)**: entry through a catering contractor's VPN appliance, then lateral movement with shared and reused credentials until the EMR was encrypted | No standing inbound path (SEC-29); per-person, phishing-resistant identities (SEC-20–SEC-23) |
| T1021.001 RDP | Osaka | No RDP; SSH off by default (SEC-41) |
| T1484.001 Group Policy Modification; T1068 with BYOVD | **Mackay Memorial Hospital (Feb 2025)**, CrazyHunter group: over 500 PCs encrypted; 16.6 million records allegedly offered *(GPO and BYOVD details uncertain)* | Not domain-joined; no GPO agents; Secure Boot, kernel lockdown, signed modules (SEC-24, SEC-50) |
| T1190 Exploit Public-Facing Application | Hermes webhook path traversal (CVE-2026-14628) | No internet-facing listener; DMZ proxy for Teams (SEC-43); patch SLAs (SEC-100) |
| T1195 Supply Chain Compromise | Hermes CVE-2026-82021 (a mutable MCP catalogue reference) | SEC-60–SEC-65 |
| T1486, T1490 Encryption for impact; inhibit recovery | Mackay; Osaka | Immutable A/B OS; immutable backup with separate credentials (SEC-95–SEC-97) |
| T1567 Exfiltration over Web Service; T1552 Unsecured Credentials | Double extortion | Default-deny egress (SEC-40); OpenBao (SEC-36) |

#### 14.3.6 LLM, agent and MCP threats

| Category | Exposure | Controls |
| --- | --- | --- |
| LLM01 Prompt Injection; ASI01 Agent Goal Hijack; AML.T0051 | Email bodies, quoted chains, sponsor PDFs, OCR text, registry text, clinical notes, tool outputs | SEC-9, SEC-73, SEC-70; §8 classifiers |
| LLM02 Sensitive Information Disclosure; AML.T0057 | Narratives, Hermes replies, cloud prompts | SEC-75; accountant (§7); §8 class policy |
| LLM03 Supply Chain; MCP04; AML.T0010 | Weights, adapters, Hermes plugins, MCP servers | SEC-60–SEC-65 |
| LLM04 Poisoning; ASI06 Memory and Context Poisoning; AML.T0020 | Lexicon, exemplars, criterion library, Hermes memory and skills, review labels | SEC-81, SEC-82 |
| LLM05 Improper Output Handling; LLM09 Misinformation | Output used as SQL, HTML or a recipient; fabricated quotes | Template SQL; SEC-76; SEC-13; quote verification and `numbers_match` (§8) |
| LLM06 Excessive Agency; ASI02 Tool Misuse; ASI03 Privilege Abuse | Agent tools | SEC-11, SEC-25, SEC-71, SEC-72 |
| LLM07 System Prompt Leakage; LLM10 Unbounded Consumption | Prompts; floods | No secrets in prompts (SEC-36); §8 budgets |
| LLM08 Vector and Embedding Weaknesses | S2b index, criterion-library retrieval | SEC-80 |
| ASI cascading failures, rogue agents | Poisoned output reused downstream | Taint propagation (SEC-70); recorded step outputs |
| MCP01 Token Mismanagement; MCP03 Tool Poisoning; rug pull; MCP08–MCP10 | Front-door and internal servers | SEC-26, SEC-74; minimum-field results (PRIV-5) |
| AML.T0024 Exfiltration via inference API | PHI-trained adapters | SEC-84 |

ATLAS identifiers are *(uncertain)* and are re-checked each release because ATLAS renumbers.

#### 14.3.7 Named threat scenarios

| TS | Scenario | Design response | Residual risk; verification |
| --- | --- | --- | --- |
| TS-1 | **Hermes compromise** (RCE through a webhook or plugin bug, or goal hijack) | No PHI tools, writes, schedules or approvals (§9). Network confined to the front-door MCP and channel endpoints (SEC-42). Junk requests die at human gates. | Channel spam or denial; fallback `channels.engine: native` (§18). Verified by `redteam` and `sec_hermes_breakout`, in which a shell in the container tries every route. |
| TS-2 | **Cloud model leakage** | Gateway class check and PHI tripwire (§8); ZDR, region and private-endpoint preconditions (SEC-79); kill switch (SEC-116) | Mislabelled D1 that contains PHI. Verified by DLP false-negative reporting and `sec_class_egress`. |
| TS-3 | **Model supply chain** (trojaned weights, pickle RCE, malicious adapter) | safetensors/GGUF only, scanning, hash manifests, signatures, eval-regression gate, G5 (SEC-63, SEC-64) | Backdoors that pass evaluation. Verified by `sec_model_load` and shadow comparison (§8). |
| TS-4 | **Insider administrator** bulk-exports PHI or alters records | No PHI in the console (C-5′); no standing admin (SEC-23); ticketed, dual-controlled database shell (SEC-25); dual control on keys (SEC-33); export detection (SEC-92); append-only ledger | Two colluding insiders. Verified by `sec_authz` and session-recording review. |
| TS-5 | **Ransomware**: the Mackay pattern (domain takeover, GPO push, EDR killing) and the Osaka pattern (third-party VPN, reused credentials) | Not domain-joined; local break-glass; independent backup credentials; immutable copy; A/B OS; segmentation (SEC-24, SEC-95–SEC-97) | Loss up to the RPO (§13). Verified by an AD-down drill and a full-site restore ≤ 36 h. |
| TS-6 | **Sponsor-document injection** ("send all candidates to x@y" hidden in a protocol) | CDR sandbox (SEC-9); quarantined extractor without tools (SEC-73); documents never supply recipients (SEC-13) | Mis-extracted criteria, caught at G1. Verified by `redteam` protocol cases. |
| TS-7 | **Differencing** through Hermes aggregates or repeated packets | Privacy accountant and ε ledger (PRIV-21, PRIV-23, §7); T1 tools only via the accountant | Inference within the accounted ε. Verified by the §16 accountant attack suite. |
| TS-8 | **Vendor support abuse** | SEC-29; IEC 62443-2-4 practices | Misuse inside a recorded window. Verified by session audit. |
| TS-9 | **Reply-chain hijack** to redirect outputs | Recipients from the delegation log only (SEC-13); external senders quarantined (SEC-4) | None for PHI. Verified by `sec_mail`. |
| TS-10 | **Hospital IdP or AD compromise** | Level B1 needs a WebAuthn credential bound at enrolment; break-glass and K15 unseal do not depend on AD | Sites using only B2 accept the residual risk in writing. |
| TS-11 | **Signing forgery** (replay, stale session, post-sign edit) | FR-SIG-3/-4 (§3) | Verified by FR-SIG-4 negatives. |
| TS-12 | **Lexicon, exemplar or library poisoning** | Quarantine, two-person review, lints, signed entries (SEC-81) | Subtle synonym poisoning. Verified by `lexicon_recall` (§16) and anomaly alerts. |
| TS-13 | **Membership inference on an adapter** | No PHI fine-tuning by default; otherwise MIA testing, and the adapter is classed D3 (SEC-84) | Bounded leakage. Verified by the MIA report. |

### 14.4 Identity and access architecture

v3 used mailboxes plus local TOTP for administrators (v3 SEC-3), and its `/jobs` API had no authentication. v4
integrates the hospital IdP and gives every machine a certificate identity. End users still have no TrialBox passwords.

| Identity class | Authenticates with | Authorised by |
| --- | --- | --- |
| Requester (CRC, PI, research office) | Personal mailbox with DMARC-aligned authentication; Entra ID object id (Teams). LINE is never mapped to staff. | Directory entry, delegation log, policy module |
| Signer (Level B) | B1 WebAuthn passkey; B2 forced IdP re-authentication at phishing-resistant strength; B3 HCA/MOICA PKI (§3) | Delegation log, gate configuration |
| Reviewer (review page) | IdP OIDC with MFA; 15 min idle timeout | Delegation log |
| Administrator | IdP OIDC with phishing-resistant MFA (FIDO2/WebAuthn, smart card); device compliance where available | Admin role and JIT elevation |
| Break-glass | Two sealed local accounts, each a FIDO2 key with PIN, kept in the hospital safe | Local policy; works when the IdP or AD is down |
| Vendor support | Named per-person account with FIDO2 | Hospital-initiated session ticket |
| Service (container) | X.509 from the internal CA (K15), URI SAN `spiffe://<site>/tb/<service>`, ≤ 24 h. Issued only to image digests in the signed release manifest. | mTLS peer allowlist and policy module |
| Hermes and native channel | Workload certificate plus a per-request **signed user assertion** (JWT, `aud` = front-door MCP, ≤ 5 min, carrying the channel-authenticated sender) | Front-door MCP policy |
| Integration | HIS: SELECT-only role on published views. FHIR: SMART Backend Services `private_key_jwt`. HL7 v2: MLLP over mutual TLS. Graph: application certificate. | Source data contracts (§5) |
| Sponsor / CRA | None: no access into the box (C-5′) | — |

**Admin roles.** `observer`, `operator`, `security_admin`, `key_custodian`, `qa_approver`. No elevation combines
`security_admin` with `key_custodian`, and nobody approves their own elevation.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-20 | Administrators, reviewers and B2 signers MUST authenticate through the hospital IdP (OIDC; SAML 2.0 alternative). Without an IdP, local accounts MUST use WebAuthn only. Local TOTP for administrators is removed. | T | MS1 |
| SEC-21 | A requester MUST be the channel-authenticated sender: a DMARC-aligned personal mailbox, or an Entra object id. The sender is mapped to exactly one directory entry with active delegation rows. Display names are never matched. Unmapped senders receive a "cannot process" reply that echoes no content. | T | MS1 |
| SEC-22 | Administrator and signer authentication MUST be phishing-resistant: FIDO2/WebAuthn, a platform authenticator or a smart card. Target AAL3; floor AAL2 phishing-resistant. SMS, voice and email codes are refused for these roles. | T | MS2 |
| SEC-23 | No account MAY hold standing admin rights. `trialbox admin elevate --role <r> --reason <ticket> --ttl <≤8h>` needs a second administrator's approval and expires automatically. The terminal session is recorded (tlog or equivalent). | T | MS2 |
| SEC-24 | **Directory independence.** The appliance MUST NOT be domain-joined or GPO-managed. Break-glass, unseal and backup credentials MUST NOT depend on the hospital directory. Each break-glass use raises `TB-BG-001`, forces rotation and is reviewed within 5 working days. | T, D | MS2 |
| SEC-25 | **Authorisation on every call.** The policy module (`libs/tb_common/policy/`) MUST evaluate role × delegation × purpose × data class × channel assurance, defaulting to deny. It runs on every intake command, workflow start, tool call, gateway call, console action and export. No service holds a superuser or tenant-wide credential. SQL on K12 runs only through `trialbox db shell --purpose <ticket>`, which is read-only, dual-controlled and recorded. | T | MS1 |
| SEC-26 | All service traffic, including PostgreSQL and the object store, MUST use mTLS with K15 certificates that rotate automatically. MCP servers accept only tokens issued for themselves (RFC 8707) and never pass tokens through. The front-door MCP requires the signed user assertion and rejects plain-text identity fields. | T | MS1 |
| SEC-27 | Integration identities MUST be least-privilege and per source. Graph access is confined to the dedicated mailbox by Exchange application-access scoping *(feature naming uncertain)*. Tenant-wide `Mail.Read` is forbidden. | I, T | MS1 |
| SEC-28 | Leavers: a disabled directory account or an ended delegation row MUST revoke access within 1 h (SCIM) or 24 h (nightly sync). Quarterly recertification packs go to the research office and IT (§18). | T | MS2 |
| SEC-29 | **Remote support** sessions MUST be hospital-initiated, ≤ 4 h (renewable), per-person, MFA-protected and recorded (screen and commands). They go through the hospital PAM or jump host where one exists. No persistent VPN, tunnel or agent. Views are redacted by default. Any D3/D4 view needs a ticketed purpose, dual approval and in-country staff (§15.5). | T, I | MS1 |

### 14.5 Key management

OpenBao (MPL-2.0, pinned) runs as K15 (`services/keys/`). It provides KV secrets, transit (HMAC and envelope encryption
with non-exportable keys) and the internal CA. It unseals automatically:
- with the TPM in topology A;
- with the hospital's HSM-backed cloud KMS in topology B.

The client library is `libs/tb_security/keys.py`. The file-based `load_or_create_key` in `libs/tb_common/crypto.py`
remains for tests only.

| Key | Purpose; algorithm | Protection; custody | Rotation | Dual control |
| --- | --- | --- | --- | --- |
| Platform root | Seals LUKS and the unseal key; TPM 2.0 PCRs 0, 2, 4, 7 | TPM (A) or cloud KMS HSM CMK (B); hospital | Re-seal on firmware change | — |
| OpenBao recovery | Shamir 3-of-5 shares | Sealed envelopes held by the CISO office, IT and the research office | Yearly and after use | **Yes** |
| `K_pid` | `HKDF-SHA-256(K_root, salt = site_id, info = "tb/pid/v1")`; `pid = hex(HMAC-SHA-256(K_pid, mpi_id))[:32]` (§7.5) | Transit, non-exportable; hospital | Per §7.5: planned key-version change only, with a `pid_alias` table (reason `key_rotation`); on compromise, the §7 re-pseudonymisation migration | **Yes** |
| `K_proj` | Per-project D2 pseudonyms, HKDF-SHA-256 | Derived in transit | Per project | — |
| D4 KEK and DEKs | AES-256-GCM envelopes for identified data, tokenisation tables and the v1 pid map | Transit; hospital | KEK yearly (re-wrap) | Destruction **yes** |
| Volume keys | LUKS2 AES-XTS-512 per volume | TPM-sealed; recovery passphrase in escrow | On re-provisioning | Recovery **yes** |
| Anchor and release-manifest keys | Ed25519 signatures on ledger digests and packet manifests | Transit; public keys in the validation pack | Yearly | — |
| Internal CA | Root ECDSA P-384, kept offline in escrow; intermediate P-256 in OpenBao; leaf certificates ≤ 24 h | Hospital | Root 10 years; intermediate 2 years | Root use **yes** |
| Listener TLS | Signing, review, console and CDS Hooks listeners; hospital enterprise CA preferred | OpenBao KV | ≤ 398 days | — |
| Channel credentials | Graph and Teams bot certificates, LINE token, SMTP | OpenBao | ≤ 90 days | — |
| Cloud credentials (B/C) | Workload identity federation, tokens ≤ 1 h; static keys forbidden unless unavoidable (then ≤ 30 days) | OpenBao | Per token | Enabling **yes** |
| Backup key | restic repository key, AES-256 | OpenBao plus offline escrow, held by custodians separate from production | Yearly | **Yes** |
| Vendor release keys | cosign; TUF root, targets, snapshot, timestamp | Offline HSM (root, targets); vendor | TUF root yearly, threshold 2-of-3 | **Yes** |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-30 | All keys above MUST be generated and used inside K15 or the TPM/HSM. Private key material MUST NOT appear in images, env files, Git, prompts, logs or backups, other than escrowed recovery shares. | I, T | MS1 |
| SEC-31 | Rotation MUST follow the table. `trialbox keys status` reports the age and expiry of every key and certificate, with alerts at 30 and 7 days before expiry. | T | MS1 |
| SEC-32 | `K_pid` (and `K_root`, §7.5) MUST be non-exportable in normal operation. HMAC calls go through transit under a `pseudonymise` policy that only the L3 stage holds. | T | MS1 |
| SEC-33 | **Dual control** (two named, authenticated, recorded custodians) MUST apply to: unseal recovery; `K_pid` or `K_root` export or rotation; KEK destruction; backup-key recovery; CA root use; enabling cloud credentials; vendor TUF root signing. | T, I | MS2 |
| SEC-34 | Cryptography MUST be configured only in `libs/tb_security/cryptopolicy.py`, for crypto agility. TLS 1.3 internally; TLS 1.2 with AEAD suites only for hospital systems that lack 1.3. AES-256-GCM, Ed25519 / ECDSA P-256, SHA-256 or stronger. Hybrid post-quantum key exchange (X25519MLKEM768) SHOULD be enabled where both ends support it *(est.)*. | I, T | MS1 (PQC MS6) |
| SEC-35 | At decommission, destroying the KEK, `K_root` (and with it `K_pid`), the TPM seal and the backup key MUST render every copy unreadable. A destruction certificate is issued (§18). | D | MS3 |
| SEC-36 | Secrets MUST be fetched from K15 at runtime on short leases. Prompts contain no secrets or access logic (LLM07). Secret scanning runs on every commit and every built image. | T | MS0 |
| SEC-37 | Where the hospital has an HSM or a FIPS 140-3 module, K15 SHOULD use it via PKCS#11 for the platform root, the KEK and the anchor keys. | I | MS4 |

### 14.6 Network zones and egress

| Zone | Contents | Connectivity |
| --- | --- | --- |
| Z1 User | Hospital user subnets | → K14 on 443 only |
| Z2 Integration | HIS DB, LIS, interface engine, FHIR server, mail relay, IdP, NTP, SIEM | ↔ named K9, K11 and K17 containers only |
| Z3 Management | Admin workstations, BMC, jump host | → K13 (443); SSH disabled by default |
| Z4a Channel | K8, K9, K10 | → front-door MCP and `tb-egress` only |
| Z4b App | K5, K6, K7 | → Z4c, Z4d (gateway only), `tb-egress` |
| Z4c Data | K12 | ← Z4b only |
| Z4d Model | K4 | ← `tb-gateway` only |
| Z4e Sandbox | CDR, document parsing, OCR | No network; files pass through a spool |
| Z5 Backup | NAS, off-site or tenant target | ← K18 only |
| Z6 External | M365/Teams, LINE, registries, NHI, vendor repository, cloud (B/C) | ← `tb-egress` only |

`deploy/egress_policy.yaml` is enforced twice: by nftables per container (`deploy/egress.py`, extended from v1) and by
`tb-egress`, a pinned Envoy with a host/SNI allowlist and pinned TLS where the destination allows.

| Destination | Caller | A | B | C |
| --- | --- | --- | --- | --- |
| Hospital mail relay or Microsoft Graph (dedicated mailbox) | K9; Hermes email adapter | ✓ | ✓ | ✓ |
| Teams / Bot Framework (MS4) | K10; Hermes Teams adapter | opt. | opt. | opt. |
| LINE Messaging API, push only, fixed templates | K10 notify worker | opt. | opt. | opt. |
| NHI TWPAS | Orchestrator | opt. | opt. | opt. |
| ClinicalTrials.gov API v2, MOHW platform (HTTPS GET, no body) | `registry-sync` | ✓ | ✓ | ✓ |
| Hospital IdP; OCSP/CRL for HCA/MOICA; SIEM; NTP/NTS; backup targets | K13, K14, K17, host, K18 | ✓ | ✓ | ✓ |
| Vendor update repository, pull only (offline import is the default) | Update agent | opt. | opt. | opt. |
| Cloud KMS, storage and logging via in-country private endpoints | K15, K18 | — | ✓ | — |
| Approved cloud model endpoints via private endpoints (D0–D2 per §8) | **`tb-gateway` only** | — | — | ✓ |
| OpenRouter (bake-off) | `tools/bakeoff.py`, **dev environment only** | — | — | — |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-40 | Egress MUST be deny-by-default per container. Every outbound connection passes `tb-egress` and must match the active topology's policy. Denials raise `TB-EGR-001`. Supersedes v3 SEC-1. | T | MS0 |
| SEC-41 | The console and CLI MUST be reachable only from Z3. SSH stays disabled except for break-glass or a support session with FIDO2 keys. No RDP, VNC or remote agents. The BMC sits on Z3 with default credentials removed. | T | MS1 |
| SEC-42 | Hermes MUST run in its own container on Z4a with a read-only root filesystem. Its only routes are the front-door MCP and its enabled channel endpoints through `tb-egress`. It reaches models only through `tb-gateway`. | T | MS0 |
| SEC-43 | Internet traffic MUST NOT reach the appliance directly. Teams Bot Framework traffic terminates at the hospital DMZ reverse proxy or WAF, which validates the Bot Framework JWT and forwards only the messaging path. LINE inbound webhooks stay disabled. | T, I | MS4 |
| SEC-44 | Only `tb-gateway` MAY reach K4 or a cloud model endpoint. Tests MUST show that every other container fails to connect. | T | MS0 |
| SEC-45 | Topology B MUST use private networking (no public IPs), in-country regions and customer-managed keys. The zone model maps to subnets and security groups, and the configuration is checked against the provider's CIS benchmark. | T, I | MS4 |
| SEC-46 | Topology C routes MUST use private endpoints over the hospital's dedicated line or IPsec, pinned TLS at `tb-egress` and private DNS. Global or multi-region inference profiles are forbidden where §15.5 requires residency. | T, I | MS4 |
| SEC-47 | The CDS Hooks service MUST accept only EHR-signed JWTs (CDS Hooks 2.0) from allowlisted sources. Its cards stay within the §15.3 PHI ceiling. | T | MS5 |

### 14.7 Host, container and supply-chain hardening

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-50 | UEFI Secure Boot MUST be on, with custom db/KEK where supported. Kernel lockdown (integrity mode), signed modules, measured boot into TPM 2.0, and signed capsule firmware via LVFS/fwupd. On GB10-class hardware the dTPM is off by default and MUST be enabled at install; custom-key support is *(uncertain)* and is checked by `trialbox doctor`. On x86 the BMC is hardened and NIST SP 800-193 resiliency features are used where offered. | T | MS1 |
| SEC-51 | Data volumes MUST use LUKS2 with TPM-sealed keys bound to Secure Boot state (systemd-cryptenroll or Clevis; Tang optional). Swap is off or encrypted. Model volumes are integrity-protected with dm-verity or fs-verity. The P-Mac FileVault deviation is retired for production. Supersedes v3 SEC-2. | T | MS1 |
| SEC-52 | **Host:** CIS Ubuntu LTS Level 1 Server plus the Level 2 items in `deploy/hardening/cis_profile.yaml`, checked by OpenSCAP in CI and by `trialbox doctor --security`; immutable A/B image with read-only root; AppArmor enforcing; auditd; USBGuard (storage blocked except the offline-import port, under dual control); SSH host keys unique per first boot. **Containers:** rootless with user namespaces; seccomp default-deny; capabilities dropped; `no-new-privileges`; read-only root; no container-socket mounts; GPU access for K4 only. | T | MS1 |
| SEC-53 | Time MUST come from the hospital NTP, authenticated (NTS or symmetric key) where available. An offset above 2 s raises `TB-INT-010`. Signing and audit refuse to run above 30 s. | T | MS2 |
| SEC-54 | A hospital EDR agent MAY run only inside the read-only image model and only if not GPO-managed. Its presence is recorded in the IQ. | I | MS2 |
| SEC-55 | `trialbox attest` MUST produce a TPM quote over the PCRs and the release-manifest hash, which the console displays. The update agent refuses bundles when the quote does not match an approved state. | T | MS3 |
| SEC-60 | Images, OS deltas, bundles and model packages MUST be built to **SLSA v1.1 Build L3**: an isolated hosted builder, non-forgeable in-toto provenance and two-person-reviewed build definitions. Reproducible builds are a target *(est.)*. Supersedes v3 SEC-5. | I | MS2 |
| SEC-61 | Images MUST be cosign-signed with HSM keys and offline-verifiable bundles. Podman `policy.json` admission rejects anything unsigned or unattested. Bundles carry TUF metadata and a monotonic rollback counter. `tools/sign_bundle.py` and `tools/verify_update.py` are extended to TUF. | T | MS1 |
| SEC-62 | Each release MUST ship three documents. (1) A CycloneDX 1.6 SBOM per image and per bundle (SPDX 3.0 on request), giving supplier, country of origin and support end date per component. (2) An **ML-BOM**: weights, tokenizer, chat template, quantisation, adapters, guardrail models, embedder, prompts, lexicon, exemplars, criterion-library version. (3) **VEX** (CSAF 2.0, with OpenVEX export). | I, T | MS1 |
| SEC-63 | **Model intake** (`tools/model_intake.py`) MUST run isolated and MUST: verify the publisher's hash or signature (OpenSSF model signing where offered *(uncertain)*); accept only safetensors or GGUF; reject `trust_remote_code`; scan with a model scanner; record licence and origin (§8); write the SHA-256 manifest; and pass §16 suites before the build can become `candidate`. | T | MS0 |
| SEC-64 | K4 MUST verify every weight, adapter, tokenizer and template file against the signed manifest at load. On a mismatch it refuses to serve and raises `TB-INT-020`. | T | MS0 |
| SEC-65 | Python dependencies MUST be hash-pinned (`deploy/requirements.lock`, `--require-hashes`) and served from an internal mirror with malware scanning. New versions wait 7 days in quarantine *(est.)*. Hermes is vendored at a pinned tag and digest, with SCA/SAST at every upgrade (§9). | T, I | MS0 |
| SEC-66 | The registry (§8) MUST keep a **provenance register** for every model and key third-party component: publisher, country of origin, licence, training-data statement, restriction status. A site policy MAY exclude publishers or countries, and the gateway enforces it. The default model set avoids publishers on Taiwan government restriction lists. | T, I | MS1 |

### 14.8 LLM and agent controls

§8 builds the gateway, guardrails and evaluation, and §9 builds Hermes. This subsection sets the security rules that
every LLM-using function must meet.

#### 14.8.1 The PUX rule

> **No run may combine PHI access (P), exposure to untrusted content (U) and an outbound or external action (X) unless
> a human confirms that outbound action.**

**P** means the run can read D3/D4 data, through a T2 tool or a D3/D4 input.

**U** means the run has seen any of the following:
- an email or Teams body, or an attachment;
- a sponsor document;
- registry text or clinical-note text;
- a tool result or model output derived from any of these.

**X** means the run can do any of the following:
- send email, Teams or LINE messages;
- write to a release location;
- call a cloud endpoint;
- perform a T3 write.

`libs/tb_security/taint.py` labels values, and model outputs inherit the union of their input labels.

The rule is enforced twice:
- **At registration.** A step that declares P ∧ U ∧ X without `confirm: human` on its X action is rejected.
- **In the outbox.** A payload labelled P and U is sent only if an approval exists for that exact payload hash. The
  approval must be Level A or stronger, given by a delegated person, with recipients taken from the delegation log
  (SEC-13).

Two paths comply by construction:
- the cascade's judging, which has P and U but no X; packets leave only after G3;
- Hermes, which has U and sees D3 only as tokenised conversation text (packet threads and PHI-tolerant channels, on-prem
  routes only; FR-CONV-8), with no PHI tool. Its only direct X is the reply to the authenticated sender in the same
  thread, bound to that sender by channel-relay and passed through outbound DLP (no PHI in bodies, FR-UX-9); every other
  X is a `tb.submit_request` proposal that a human confirms (§9).

#### 14.8.2 Tool manifests and per-call authorisation

Each MCP server ships a signed manifest, `services/mcp/<server>/manifest.yaml`. For each tool it declares:
- name and version;
- the SHA-256 of the description and of the input and output schemas;
- the tier (T0–T3);
- the data classes in and out;
- whether the tool is `consequential`;
- its PUX labels;
- rate limit and maximum result rows and fields;
- the allowed caller workloads and the required user scopes;
- its audit event id, its owner and its G5 approval.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-11 | A model never holds T3. T2 data reaches a model only inside a workflow step started for a study the requesting user is delegated on, and every such call is logged with its purpose. *(v3, unchanged)* | T | MS1 |
| SEC-13 | Recipients, scope and release targets come from the delegation log and the Study Card, never from model output or document content. *(v3, unchanged)* | T | MS1 |
| SEC-70 | The **PUX rule** MUST be enforced at registration and in the outbox. A violation raises `TB-POL-030` and fails closed. | T | MS1 |
| SEC-71 | Every tool MUST have a signed manifest entry; a tool without one cannot be called. Each call is authorised on **both** the caller's workload identity and the end user's delegated identity and purpose (SEC-25, SEC-26). | T | MS0 |
| SEC-72 | Per-run hard limits (manifest and §8 routing policy) MUST cover: tool calls; recipients (default 1 per send, from the delegation log); attachment types; and token, time and cost budgets. Exceeding a limit stops the run (`TB-LLM-040`). | T | MS1 |
| SEC-73 | Untrusted documents (sponsor protocols, external bodies, attachments) MUST pass four steps before any tool-holding step sees them. (1) Conversion in Z4e. (2) A **quarantined extractor**: a tool-less model call whose schema-constrained output is all that passes on. (3) Provenance-delimited spotlighting. (4) The §8 injection classifier. | T | MS1 |
| SEC-74 | **MCP pinning.** Only first-party, inventoried MCP servers run. CI snapshots `tools/list` (names, descriptions, schemas) into `services/mcp/mcp_pins.lock`. Servers and clients (orchestrator, Hermes) verify the snapshot at start-up and refuse on a mismatch (`TB-MCP-001`). Descriptions are linted for imperatives, URLs and invisible Unicode. The protocol revision is pinned (2026-07-28 at writing *(uncertain)*). Sampling, roots and server-initiated elicitation are off. Every call is audited. | T | MS0 |

#### 14.8.3 Outbound checks, retrieval stores and adaptation

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-75 | **Outbound DLP** (`libs/tb_security/dlp.py`) MUST scan every outbound item: bodies, subjects, filenames, attachment text (XLSX, PDF, DOCX, CSV), Teams cards, LINE payloads and cloud-bound prompts. It combines the §7 PHI guard, class labels and the recipient policy. Channel ceilings: LINE D0 fixed templates only; Teams counts and links only; email PHI only in SEC-10 attachments to delegated recipients; cloud per the §8 class policy. A hit blocks the item or sends it to review (`TB-DLP-001`). The false-negative rate on the §7 test set is reported each release. | T | MS1 |
| SEC-76 | Model output rendered on a page, email or card MUST be context-encoded. Remote images and auto-loaded links from model output are never rendered. Structured output is schema-validated before use. | T | MS1 |
| SEC-77 | The channel layer (Hermes or native) sees request text and status only, never patient-level data from tools. Inbound identifiers MUST be tokenised before any model sees them (§9). Conversation text is D3 for every authenticated staff message in a packet thread and for tokenised text from PHI-tolerant channels, and routes on-prem only; cloud routes never receive conversation text (FR-CONV-8, §8.5). LINE inbound text never reaches a model. Grammar lines carrying an MRN bypass the model entirely. Supersedes v3 SEC-12. | T | MS0 |
| SEC-78 | Attachments MUST pass content disarm and reconstruction and anti-malware scanning (ClamAV, signatures delivered in update bundles when offline). Macros, embedded objects, scripts and external references are removed before parsing. | T | MS1 |
| SEC-79 | A topology C route MUST NOT be enabled until the registry records all of the following: region pinning; contractual zero data retention or modified abuse monitoring, with the approval artefact; a no-training clause; the private-endpoint configuration; and the §15.5 cross-border record. Enabling needs dual control (SEC-33) and G5. | T, I | MS4 |
| SEC-80 | Indexes and caches holding D3 text (vector index, judgement cache, library embeddings) MUST be classed D3. They are partitioned per study, ACL-filtered at retrieval (not in the prompt), and carry provenance per chunk, re-hashed weekly. | T | MS2 |
| SEC-81 | Lexicon, exemplar, criterion-library, prompt and skill changes MUST go through change control. Mined or agent-proposed entries wait in quarantine. Each change is reviewed by two people with a diff, signed, and linted for imperatives, URLs, code and invisible Unicode. More than 50 edits a day *(est.)* raises `TB-LLM-050`. | T | MS1 |
| SEC-82 | Hermes memory and skills follow §9. Tests MUST show that no skill or memory entry can add a tool, route or recipient. | T | MS0 |
| SEC-83 | Debug logging of prompt content MUST be off by default. Turning it on needs dual approval, expires in ≤ 24 h, and writes only to the encrypted on-box store. | T | MS1 |
| SEC-84 | Fine-tuning on D3/D4 MUST NOT occur by default; retrieval is preferred. An exception requires all of: G5 with DPO sign-off; deduplication; low LoRA rank; canaries; and a recorded membership-inference and extraction test (LiRA-style and prefix completion), with thresholds fixed in the change record before testing. The adapter is D3: site-bound, encrypted, never exported, destroyed at contract end. | T, I | MS3 |

#### 14.8.4 Channel ingress (v3, unchanged)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-4 | Mail: v1 sender authentication (aligned SPF/DKIM or DMARC, pinned authserv-id); allowlisted internal senders; personal mailboxes only for gates; external senders go to a quarantine workflow that summarises the request for a CRC to adopt. | T | MS1 |
| SEC-9 | Intake hygiene: quoted-text stripping (§3); attachments converted in a network-isolated container; hidden text, comments, metadata, zero-width and Unicode tag characters removed; virus scan. | T | MS1 |
| SEC-10 | PHI attachments go by S/MIME to recipients with certificates. Otherwise they go as AES-256 7z with a per-recipient passphrase issued in person by the research office at delegation. The passphrase is stored in the secrets store, rotated quarterly, and never sent by the box. Passphrase delivery by SMS or Teams is MS4 and needs its own allowlist entry and a dedicated, logged template. | T | MS2 |

### 14.9 Logging, monitoring and the SIEM contract

There are three log classes:
- the clinical **audit ledger** (§11), a regulated record;
- **security events**, the only class forwarded to the SIEM;
- **telemetry and traces** (§8, §18).

**Contract.**
- **Transport:** syslog over TLS (RFC 5425, mutual TLS, RFC 5424 framing). `services/siem_forwarder/` runs pinned
  rsyslog with a 7-day spool and a 60 s heartbeat.
- **Format:** CEF `CEF:0|TrialBox|TrialBox|<version>|<event id>|<name>|<severity>|…`, or JSON with ECS-compatible names.
- **Extensions:** `rt`, `suser` (staff or service id), `src`, `dst`, `act`, `outcome`, `cs1=run_id`, `cs2=study_id`,
  `cs3=data_class`, `cs4=policy_rule`, `cs5=object_sha256`, `cs6=site`.
- **Never forwarded:** patient identifiers, MRN, `pid`, patient names, dates of birth, note or prompt text, attachment
  names.

| Family | Covers | Severity |
| --- | --- | --- |
| `TB-AUTH`, `TB-ADM`, `TB-BG` | Logins, MFA failures, lockouts, elevation, configuration and policy changes, break-glass | 3–9 |
| `TB-POL`, `TB-EGR`, `TB-DLP`, `TB-EXP` | Policy and PUX denials, egress denials, outbound blocks, bulk exports | 5–8 |
| `TB-LLM`, `TB-MCP`, `TB-HER` | Injection-classifier hits, class mismatches, budget stops; pin and token failures; Hermes denials and volume spikes | 4–9 |
| `TB-INT`, `TB-KEY`, `TB-BAK` | Ledger break, hash or signature mismatch, attestation, clock skew; dual-control key use; backup or verification failures | 5–10 |
| `TB-SUP`, `TB-KS` | Support sessions and D3/D4 view approvals; kill switch | 6–9 |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-8 | Logs and traces are PHI-redacted. PHI access is recorded in the audit ledger with its purpose. *(v3, unchanged)* | T | MS1 |
| SEC-90 | The daily signed ledger digest MUST go to the QA mailbox, the hospital WORM share **and** the immutable backup copy. `audit_verify` checks continuity against all three. Supersedes the v3 §10.5 anchoring rule. | T | MS1 |
| SEC-91 | Security events MUST be forwarded per the contract within 60 s, using the catalogue in `libs/tb_security/siem/events.py`. A contract test plants PHI and asserts that none of it is forwarded. | T | MS1 |
| SEC-92 | Each release MUST ship Sigma rules (`deploy/siem/sigma/`) covering at least: MFA-failure bursts; break-glass; bulk export; new-recipient or volume anomalies; egress denials; integrity failures; Hermes denial spikes; kill-switch use; support sessions outside the agreed window. | I, T | MS2 |
| SEC-93 | Security events MUST be kept on the box for ≥ 1 year *(est.; hospitals MAY extend)*. Ledger retention follows PRIV-6 (§7). | T | MS2 |
| SEC-94 | A site without a SIEM gets a console alert view and email alerts to IT and the CISO, recorded as a site deviation. | D | MS1 |

### 14.10 Backup and recovery (3-2-1-1-0)

| Element | Implementation |
| --- | --- |
| 3 copies, 2 media | Live data; a nightly encrypted backup on separate local media (NAS or disk in A; object storage in B) |
| 1 off-site | Hospital second site, or a tenant store in-country |
| 1 immutable | Object lock in compliance mode, or a monthly and pre-update offline encrypted disk kept in the hospital safe; retention ≥ 35 days *(est.)* |
| 0 errors | Weekly automated restore verification into scratch (`audit_verify`, row counts, checksums); quarterly full drill |

What is backed up:
- configuration;
- PostgreSQL with WAL;
- L4 snapshots and manifests;
- the D4 vault;
- lexicon, exemplars and the criterion library;
- the ledger and its anchors;
- signed-packet archives;
- the registry.

Models and images are redeployed from signed bundles, and indexes are rebuilt from sources.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-95 | Backups MUST follow 3-2-1-1-0 and be encrypted with the backup key. Writes go to an append-only repository (restic `rest-server --append-only`, or object lock). Appliance credentials MUST NOT be able to delete the immutable copy or shorten its retention. | T | MS1 |
| SEC-96 | Backup credentials and the backup key MUST be independent of the hospital directory and of production admin roles. Changing retention or immutability needs dual control. | T | MS2 |
| SEC-97 | A **full-site restore** from the immutable copy, to a spare appliance (A) or a fresh tenant (B), MUST be demonstrated within **36 h** before MS3 and yearly after. This keeps the hospital inside the Taiwan recovery window. §13 RPO/RTO targets apply in addition. | D | MS3 |
| SEC-98 | Weekly restore verification MUST run. A failure raises `TB-BAK-002` and appears in the QA pack. | T | MS1 |
| SEC-99 | A restore MUST preserve signatures and ledger continuity, shown by `audit_verify` and FR-SIG verification of a restored signed record. | T | MS2 |

### 14.11 Vulnerability management and patch SLAs

**Sources:**
- SCA of the SBOM against OSV, NVD and GHSA;
- CISA KEV;
- vendor advisories (NVIDIA DGX OS and GB10 firmware, Ubuntu USN, PostgreSQL, vLLM);
- the Hermes GHSA feed;
- TWCERT/CC and JPCERT/CC;
- Health-ISAC and the Taiwan medical H-ISAC.

Hermes has a shorter clock because of its history: CVE-2026-82021 was a critical supply-chain flaw, and CVE-2026-14628
had a public exploit with no vendor response.

| Class (reachable per VEX) | Mitigation or VEX | Fixed release |
| --- | --- | --- |
| E: KEV-listed or exploited | ≤ 72 h | ≤ 14 days |
| Critical, CVSS v4 ≥ 9.0 | ≤ 7 days | ≤ 14 days |
| High, 7.0–8.9 | ≤ 14 days | ≤ 30 days (consistent with NFR-14) |
| Medium, 4.0–6.9 | — | ≤ 90 days |
| Low | — | Next release |
| Hermes High/Critical | Switch to `channels.engine: native` (§18) | ≤ 7 days |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-100 | The vendor MUST meet the SLA table. The console flags an installed release with an overdue fix as `security-overdue`. Supersedes v3 SEC-6. | T, I | MS1 |
| SEC-101 | Every Critical or High CVE in the SBOM MUST have a published VEX status within 7 days. | I | MS1 |
| SEC-102 | A monthly security release MUST be produced, plus out-of-band releases per the table. Each passes the security regression suite (§14.17). | T | MS2 |
| SEC-103 | `trialbox doctor` MUST check the CUDA, NIC and GB10 firmware pins against vendor advisories. A pin with an open Critical advisory fails `doctor`. | T | MS1 |

### 14.12 Coordinated vulnerability disclosure

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-105 | The vendor MUST publish a disclosure policy aligned with ISO/IEC 29147:2018 and a handling process aligned with ISO/IEC 30111:2019. It must include `security.txt` (RFC 9116), encrypted intake, acknowledgement within 3 working days, safe harbour, and remediation windows per §14.11. | I | MS2 |
| SEC-106 | Advisories MUST be issued as CSAF 2.0 and sent to the site security contacts and through Health-ISAC and the Taiwan medical H-ISAC. Becoming a CVE Numbering Authority SHOULD be evaluated by MS6. | I | MS3 |
| SEC-107 | Third-party issues (Hermes, vLLM, OpenBao) MUST be reported upstream. If upstream does not respond, compensating controls are documented in VEX. | I | MS2 |

### 14.13 Incident response and breach workflow

The IR plan follows NIST SP 800-61r3. A joint vendor–hospital RACI (`docs/security/ir/raci.md`) ships per site.

Playbooks (`docs/security/ir/playbooks/`):
1. LAN ransomware;
2. appliance compromise;
3. PHI disclosure through the agent or a mis-sent email;
4. a prompt-injection campaign;
5. a malicious model or update;
6. a cloud provider incident;
7. insider misuse;
8. a Hermes vulnerability;
9. key compromise.

| Regime | Clock (the hospital files; TrialBox supplies the data) |
| --- | --- |
| Taiwan CSMA, CI hospital | Report **≤ 1 h** via the MOHW channel. Recovery ≤ 72 h (levels 1–2) or ≤ 36 h (levels 3–4). Non-designated hospitals: applicability *(uncertain)*; TrialBox applies the 1 h target anyway. |
| Taiwan PDPA (2025) | Notify the PDPC and data subjects. Deadline per implementing rules *(uncertain)*; internal target 72 h. |
| Japan APPI | Preliminary report about 3–5 days; final report 30 or 60 days *(uncertain)* |
| Japan MHLW / prefecture; Act on Strengthening Cyber Response Capabilities | Prompt contact *(specifics uncertain)*; designated operators report per the Act from 1 Oct 2026 *(uncertain)* |
| Sponsor CTAs | Per contract |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-110 | The IR plan, RACI and playbooks MUST exist per site before MS2. Each playbook covers detection sources, containment, evidence, communications and recovery verification. | I | MS2 |
| SEC-111 | The vendor MUST notify the hospital security contact **≤ 30 min** after it becomes aware of an incident affecting the site. Within 45 min, `trialbox security incident-record` produces a record (`schemas/security/incident_record.json`) giving: what happened; when (UTC and local); systems, data classes and studies affected; an estimate of records affected; containment state; the evidence-bundle hash. | T (tabletop) | MS2 |
| SEC-112 | Incidents MUST be classified on the Taiwan levels 1–4 and the hospital scale, with the mapping held in site configuration. | I | MS2 |
| SEC-113 | **Breach workflow** (supersedes v3 SEC-14). Detection (SOC, egress or DLP alarm, ledger anomaly, user report) → triage ≤ 15 min → containment playbook → incident record → hospital filing per the clock table → data-subject notification where required → post-incident review ≤ 10 working days, with CAPA in the QA pack. The clock profile (TW or JP) is a site setting. | T (tabletop) | MS2 |
| SEC-114 | `trialbox security evidence-bundle` MUST collect, hash and sign, without altering evidence: the ledger segment; security events; egress logs; image digests; the attestation quote; configuration; and memory capture (optional, under dual control). | T | MS2 |
| SEC-115 | A joint tabletop MUST run before MS2 go-live and yearly after. It covers the 1 h path and ransomware, aligned with the MOHW drill programme (TW) and guideline v6.0 BCP expectations (JP). | D | MS2 |
| SEC-116 | **Kill switch.** `trialbox security killswitch --scope {outbound,cloud,hermes,ingest,all}` MUST stop the scoped functions within 60 s while keeping read access and the ledger, and raise `TB-KS-001`. Any `security_admin` or the hospital SOC (with a signed API token) MAY engage it. Releasing it needs dual control. | T | MS1 |
| SEC-117 | Manual fallback templates (eligibility checklists, logs, safety-clock lists) MUST be exported weekly to the hospital share. Degraded mode (no LLM) MUST be selectable (§18). | D | MS3 |

### 14.14 Secure development life cycle

The SDLC follows IEC 81001-5-1:2021 and IEC 62443-4-1:2018, with NIST SP 800-218/218A as the practice catalogue.

| Practice | Implementation |
| --- | --- |
| Requirements and threat modelling | SEC IDs, `@req` markers and the allocation YAML; pytm deltas per boundary change |
| Design and code review | Security section in every ADR; two-person review; CODEOWNERS for security paths |
| Verification | SAST (CodeQL, Semgrep, Bandit); SCA (Grype/Trivy on the SBOM); secret scanning; DAST (OWASP ZAP) on K13/K14; fuzzing (Atheris) of PDF, DOCX, XLSX, HL7 v2, FHIR NDJSON, CQL and MIME parsers |
| AI-specific (SP 800-218A) | Model intake (SEC-63); prompt and skill change control (SEC-81); red-team CI (§14.15) |
| Release and post-release | SLSA L3 builds; release approved by the security lead and QA; §14.11–§14.12 |
| Training | Annual secure-coding and LLM-security training, with records |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-120 | The threat-model delta review MUST block a release that adds or changes a tool, connector, source, route, channel, listener or topology. | I | MS0 |
| SEC-121 | CI MUST run SAST, SCA, secret scanning, image scanning and the security unit suites on every merge. Critical or High findings block the merge unless a time-limited, recorded exception exists. | T | MS0 |
| SEC-122 | Parsers of untrusted input MUST be fuzzed continuously with corpora in `tests/fuzz/`. Crashes are security defects. | T | MS1 |
| SEC-123 | DAST against K13 and K14 MUST run on every release candidate. | T | MS2 |
| SEC-124 | `libs/tb_security/`, `services/keys/`, `services/mcp/`, `deploy/egress_policy.yaml` and the policy module MUST require security-lead review. | I | MS0 |
| SEC-125 | The vendor build and support environment MUST meet NIST SP 800-171 Rev. 3, be isolated from corporate IT, and give engineers no access to site data. | I | MS2 |

### 14.15 Penetration testing and LLM red team

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-130 | An independent penetration test MUST run before MS2, MS4 and MS6, and yearly after. Scope: K13/K14 (ASVS 5.0 L3); APIs and CDS Hooks (L2); mail and Teams ingress; MCP servers; container escape; segmentation; boot and firmware; backup isolation; remote support. | T | MS2 |
| SEC-131 | The `redteam` suite (`eval/redteam/`) MUST cover the OWASP LLM 2025, Agentic 2026 and MCP Top 10 categories and the §14.3.6 ATLAS techniques, in zh-TW, en, ja and code-mixed. Vectors: email bodies; quoted chains; PDF hidden text; DOCX comments; OCR text; Teams cards; registry and note text; tool output; lexicon entries; markdown-image exfiltration; tool-misuse chains; class-mismatch routing; Hermes skill and memory attempts. | T | MS0 |
| SEC-132 | Release pass criteria: **zero capability-bearing successes**. That means no send to a non-delegated recipient, no PHI above a channel ceiling, no gateway class violation, no unauthorised tool call and no pin bypass. In addition, the classifier layer must detect or neutralise ≥ 95 % of known-corpus injections *(est.; reviewed each release)*. | T | MS1 |
| SEC-133 | garak, PyRIT and promptfoo *(versions pinned; current versions uncertain)* MUST run in CI on every model, prompt, guardrail or Hermes change. A human red team exercising goal hijack through real channels runs yearly and before MS4. | T | MS1 |
| SEC-134 | Guardrail models are versioned and regression-tested like any model. Their false-negative rate on the red-team corpus is a release metric (§8). | T | MS1 |
| SEC-135 | Findings MUST close within the §14.11 SLAs. Pentest summaries go into the release security package (SEC-141). | I | MS2 |

### 14.16 Component control allocation

This is the security requirements traceability matrix. It is mirrored in `docs/security/allocation.yaml`. Suite names
refer to `tests/security/` (pytest with `@req` markers) or to the §16 suites.

| K | Component | Key threats | Controls | Standards | Test (suite; first milestone) |
| --- | --- | --- | --- | --- | --- |
| K1 | Hardware, firmware, BMC | Firmware implant; BMC takeover; theft; GB10 firmware CVEs (CVE-2025-33187…33200 class) | SEC-50, SEC-51, SEC-55, SEC-41, SEC-103 | NIST SP 800-193; IEC 62443-4-2 CR 3.4, 3.14 | `sec_boot`: Secure Boot state, TPM quote, BMC credential scan; MS1 |
| K2 | Host OS, drivers | Kernel exploit; persistence; T1490; duplicate host keys | SEC-51–SEC-54, SEC-103 | CIS L1(+L2); 防護基準; MHLW checklist | `sec_host_scan`: zero failed L1 items; MS1 |
| K3 | Container runtime | Escape; unsigned image | SEC-52, SEC-61 | NIST SP 800-190; SLSA v1.1 | `sec_images`: unsigned image rejected; capabilities and seccomp audited; MS1 |
| K4 | Model serving, weights | Trojaned weights; pickle RCE; GPU DoS; membership inference | SEC-44, SEC-62–SEC-64, SEC-84 | OWASP LLM03/04/10; ATLAS | `sec_model_load`: one tampered byte → refusal; MS0 |
| K5 | LLM control plane | Class bypass; cloud leakage; budget exhaustion; PHI in traces | SEC-44, SEC-79, SEC-83, SEC-134; §8 class policy | OWASP LLM02/10; ISO/IEC 27017/27018 | `sec_class_egress`: D3 payload on a cloud route → refused; MS0 |
| K6 | Orchestrator, policy, outbox | PUX violation; confused deputy; injected recipients | SEC-11, SEC-13, SEC-25, SEC-70, SEC-72 | OWASP ASI01–ASI03; IEC 62443-4-2 CR 2.1 | `sec_pux`, `sec_authz` (property tests); MS0 |
| K7 | MCP tool servers | Tool poisoning; rug pull; token passthrough; shadow servers; over-sharing | SEC-26, SEC-71, SEC-74, PRIV-5 | OWASP MCP Top 10 | `sec_mcp_pin`: changed description → refusal; MS0 |
| K8 | Hermes | Gateway or plugin RCE; goal hijack; skill or memory poisoning; allowlist bypass | SEC-42, SEC-65, SEC-77, SEC-82, SEC-100 (7-day clock); §9 | OWASP Agentic 2026 | `redteam` front door; `sec_hermes_breakout`; MS0 |
| K9 | Native channel, mail-gateway | Spoofing; malicious attachments; reply-chain hijack | SEC-4, SEC-9, SEC-10, SEC-21, SEC-27, SEC-75, SEC-78 | ATT&CK T1566; OWASP LLM01/05 | `sec_mail`: spoofed sender, quoted display name, macro document; MS1 |
| K10 | Teams, LINE | Forged activity; PHI on a consumer channel | SEC-43, SEC-75; FR-SIG-8 (§3) | Bot Framework authentication; ASVS | `sec_teams_jwt`, `sec_dlp_channels`; MS4 |
| K11 | Ingestion | Malformed HL7/FHIR; credential misuse; over-collection | SEC-26, SEC-27, SEC-122; §5 contracts | HL7 v2 MLLP/TLS; SMART Backend Services | `sec_fuzz`, `sec_ingest_auth`; MS1 |
| K12 | Data stores | Bulk exfiltration; cross-study leakage; embedding recovery; tampering | SEC-25, SEC-30, SEC-32, SEC-80, SEC-90, SEC-92 | ISO 27799; ISO/IEC 27701; OWASP LLM08 | `sec_rls`: cross-study query denied; `audit_verify`; MS1 |
| K13 | Admin control plane | Credential theft; RCE; insider export | SEC-20, SEC-22, SEC-23, SEC-41, SEC-123 | ASVS L3; NIST SP 800-53 AC/IA; 62443 SL3 FR1 | `sec_console`: ZAP scan, authorisation matrix; MS1 |
| K14 | Signing, review, CDS Hooks | Forgery; replay; XSS; PHI in cards | FR-SIG-3/-4, SEC-22, SEC-47, SEC-53, SEC-76 | 21 CFR 11.50/11.70/11.200; ASVS L3/L2; CDS Hooks 2.0 | `sec_signing` (FR-SIG-4 negatives); `sec_cds`; MS2 |
| K15 | Keys and PKI | Key theft; unseal without custodians; expiry | SEC-30–SEC-37 | NIST SP 800-57 Pt 1; IEC 62443-4-2 CR 1.9 | `sec_keys`: non-exportability, dual control, expiry alarms; MS1 |
| K16 | Network enforcement | Direct egress; DNS exfiltration; lateral movement | SEC-40–SEC-46 | NIST SP 800-207; IEC 62443-3-3 SR 5.1 | `sec_egress`: root test per container and topology; MS0 |
| K17 | Audit, SIEM | Log tampering; PHI in logs; a blind SOC | SEC-8, SEC-90–SEC-93 | NIST SP 800-92, 800-61r3 | `sec_siem_contract`: planted PHI never forwarded; 60 s delivery; MS1 |
| K18 | Backup | Ransomware deletion; theft of backup credentials | SEC-95–SEC-99 | MHLW guideline v6.0; Taiwan 36/72 h | `sec_backup_restore`: deletion attempt fails; DR drill; MS1 |
| K19 | Build, update, model intake | Supply-chain compromise; rollback; malicious dependency | SEC-60–SEC-66, SEC-120, SEC-121, SEC-125 | SLSA L3; NIST SP 800-218/218A; IEC 81001-5-1; TUF | `sec_update_tamper`: tampered, replayed or downgraded bundle refused; MS1 |
| K20 | Remote support | VPN exploit; credential reuse (the Osaka pattern) | SEC-24, SEC-29, SEC-92 | IEC 62443-2-4; MIC/METI v2.0 | `sec_support_session`: no standing route; recording present; MS1 |
| K21 | Cloud tenant and endpoints | Residency breach; retention; IAM mis-scoping | SEC-33, SEC-45, SEC-46, SEC-79; CMP-80, CMP-81 | ISO/IEC 27017/27018; CIS cloud benchmarks | `sec_cloud_config`, `sec_class_egress` (C); MS4 |

### 14.17 Security testing plan by milestone

Each milestone re-runs every earlier suite. The gates are **blocking**.

| Milestone | Scope added | Tests and gates | Exit evidence |
| --- | --- | --- | --- |
| MS0 | Gateway, registry, front-door MCP, Hermes with native fallback, egress, CI | Threat model v1; SAST, SCA, secret and image scans; `sec_egress`, `sec_pux`, `sec_authz`, `sec_mcp_pin`, `sec_model_load`, `sec_class_egress`; `redteam` baseline (en, zh-TW) with zero capability-bearing successes; Hermes breakout test | CI green; threat-model review record |
| MS1 | First on-site install (A); D2 in the validation zone; IdP; K15; backup | `sec_boot`, `sec_host_scan`, `sec_images`, `sec_keys`, `sec_update_tamper`, `sec_siem_contract`, `sec_backup_restore`, `sec_console`, `sec_mail`, `sec_fuzz`; DLP false-negative report; 防護基準 and MDS2 drafts | Security section of IQ/OQ; events arriving at the SOC |
| MS2 | D3/D4 live; Level B; D4 vault; IR; open-study matching (silent; M5 analysis signed, CMP-71) | Independent pentest with all Critical/High closed; `sec_signing`; `sec_rls`; DAST; PUX runtime tests on real workflows; IR plan; joint tabletop including the 1 h path; first access recertification | Pentest summary; tabletop record; security package signed off by QA (SEC-141) |
| MS3 | Live wave 1 | Full-site restore ≤ 36 h; attestation check; kill-switch drill; monthly security release; CVD policy live | DR drill record; first VEX-bearing monthly release |
| MS4 | Teams, cloud routes (C, D1), registry patient → trials and tumour board | Threat-model delta; signed M5 intended-use analysis (CMP-71); pentest of the Teams/DMZ path; `sec_teams_jwt`, `sec_dlp_channels`, `sec_cloud_config`; human red team via Teams and email; ZDR, region and private-endpoint evidence audit; cross-border record | Route-enablement G5 record with dual control; red-team report |
| MS5 | eSource, SAE clocks, CDS Hooks, any adapter | `sec_cds` (EHR JWT, card ceiling per §15.3); MIA and extraction test for any PHI adapter; fuzzing of new parsers; CDS-boundary delta | Signed M7 and CDS Hooks analyses (CMP-71); MIA report if applicable |
| MS6 | Second site; Japan | Pentest of the Japanese deployment; ja `redteam` corpus; MHLW v6.0 mapping (v7.0 gap if confirmed); MDS/SDS; 責任分界表; APPI tabletop; check of the hospital's core-infrastructure designation; second install from the bundle with attestation | Japanese security package; vendor ISO/IEC 27001 certificate |
| Each release | All | Security and `redteam` regression; SBOM, ML-BOM, VEX; CSAF advisories; two-person sign-off | Release security package |
| Yearly | All | External pentest and human red team, including the physical and support paths; DR drill; tabletop; ISO surveillance | Annual security report per site |

### 14.18 Governance artefacts and disposition of v3 requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-140 | The vendor MUST name a security lead with authority to block releases, plus a security contact per site. Each site records its CISO or security officer. Security KPIs (SLA adherence, open findings, red-team results, incidents) appear in the monthly QA pack. | I | MS1 |
| SEC-141 | Each release MUST include a **security package**: threat model and delta; architecture views (global, multi-site, update, security use cases); SBOM, ML-BOM and VEX; pentest and red-team summaries; MDS2 (ANSI/NEMA HN 1-2019); the Taiwan 防護基準 mapping; a NIST CSF 2.0 profile cross-walked to SP 800-53 Rev. 5; a support end-of-life statement. | I | MS2 |
| SEC-142 | Japanese deployments MUST also include: a JAHIS/JIRA-format MDS/SDS; a 責任分界表 agreed with the hospital; the MHLW checklist vendor sheet; a guideline v6.0 mapping, with a v7.0 gap assessment if confirmed. | I | MS6 |
| SEC-143 | The vendor MUST hold ISO/IEC 27001:2022 covering development, release, support and any vendor-operated cloud service. It SHOULD do so by MS3 and MUST by MS6. The Statement of Applicability cites SEC IDs. ISO/IEC 27701, and ISO/IEC 42001 or HITRUST AI Security, SHOULD follow when sites or sponsors require them. | I | MS6 |
| SEC-144 | `tools/security_matrix.py` MUST verify in CI that every K row has an owner, at least one control and at least one passing test. | T | MS0 |

| Disposition | v3 requirements |
| --- | --- |
| Kept unchanged | SEC-4 and SEC-9 (§14.8.4); SEC-8 (§14.9); SEC-11 and SEC-13 (§14.8.2); SEC-10 (§14.8.4; only the release tag becomes MS4) |
| Superseded | SEC-1 → SEC-40, SEC-44 · SEC-2 → SEC-51 · SEC-3 → SEC-20, SEC-22, SEC-26 · SEC-5 → SEC-60–SEC-62 · SEC-6 → SEC-100–SEC-103, SEC-130 · SEC-7 → SEC-30–SEC-36 · SEC-12 → SEC-77 · SEC-14 → SEC-110–SEC-116 |

## 15. Compliance

### 15.1 Regulatory position and method

The intended-use statement in §2 is normative. Under it, TrialBox is **not a medical device** in any of the four
jurisdictions:

| Jurisdiction | Instrument |
| --- | --- |
| Taiwan | Medical Devices Act; TFDA medical-software classification guidance (2022) |
| Japan | PMD Act (program medical devices) |
| US | FDA CDS guidance (revised Jan 2026) |
| EU | MDR; MDCG 2019-11 rev. 1 (Jun 2025) |

It **is** a GCP computerised system. The hospital is the regulated user. The vendor is a supplier whose evidence the
hospital leverages (GAMP 5 2nd ed.).

The CMP rows below live in `docs/compliance/trace.yaml`. `tools/trace_matrix.py` joins them with `@req` test results,
and `trialbox validate` (§16) renders the matrix into the validation pack. A CMP row passes only when every implementing
ID it lists has a passing test or an approved inspection record.

v3 CMP IDs are kept where the obligation is unchanged. CMP-16 ("no external models") is superseded by CMP-51, because
cloud use is now allowed under policy. New rows start at CMP-40.

### 15.2 Trace matrix

Each row reads: **source**, then the obligation, then "→" followed by what implements it and the evidence.

#### 15.2.1 Electronic records, signatures and GxP computerised systems

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-01 | **21 CFR 11.10(e); ICH E6(R3) Annex 1 §4.2–4.3; EU GMP Annex 11 §9.** Audit trail: who, what, when (UTC) and why; append-only; hash-chained. → §11 ledger, SEC-90; `audit_verify`. | T | MS1 |
| CMP-02 | **ICH E6(R3).** Periodic audit-trail review. → monthly QA pack (§18). | T | MS2 |
| CMP-03 | **21 CFR 11.10(d),(g).** Unique identities and authority checks. → SEC-20, SEC-21, SEC-25; policy property tests. | T | MS1 |
| CMP-04 | **21 CFR 11.50, 11.70, 11.100, 11.200, 11.300; EMA guideline §4.8; Taiwan ESA 2024.** Level A approvals as operational records; Level B signatures with re-authentication; manifestation; linking; certification letter. → §3 FR-SIG-*, SEC-22, SEC-53; FR-SIG-4; validation pack. | T | MS2 |
| CMP-05 | **ICH E6(R3) §4.3; GAMP 5 2nd ed.; FDA CSA.** Risk-based validation, traceability, change control. → §16 `trialbox validate`; G5. | T | MS1 |
| CMP-08 | **ICH E6(R3) investigator responsibility.** The box never decides eligibility. → G3 semantics; FR-M4 (§10); §15.3. | T, I | MS2 |
| CMP-09 | **ICH E6(R3).** No unblinding data. → FR-M7 (§10). | T, I | MS3 |
| CMP-19 | **ICH E2A; TFDA SUSAR rules.** Safety clocks; the investigator decides. → FR-M7 (§10); §15.3. | T | MS3 |
| CMP-20 | **ICH E6(R3) deviations.** Deviation log plus CAPA, Level B. → FR-M7 (§10). | T | MS3 |
| CMP-21 | **21 CFR 312.62; EU CTR; TFDA GCP.** Retention defaults, legal hold, archive. → PRIV-6 (§7); FR-M9 (§10). | T | MS3 |
| CMP-22 | **ICH E6(R3) §4.3.** Backup and restore. → SEC-95–SEC-99; §13. | T | MS1 |
| CMP-34 | **ICH E6(R3) sponsor oversight.** AI disclosure in every external packet. → §12 provenance block. | T | MS1 |
| CMP-40 | **21 CFR 11.10(b); E6(R3) Annex 1 §4.2 (certified copies).** Accurate and complete copies, human-readable and electronic, for inspection. → audit export; PDF/A archive with manifest hashes. | T | MS2 |
| CMP-41 | **21 CFR 11.10(c).** Records stay protected and retrievable for the retention period. → SEC-95–SEC-99; PRIV-6. | T | MS2 |
| CMP-42 | **21 CFR 11.10(i),(j).** Trained users; written accountability policy for signatures. → training status in the delegation log gates Level B enrolment; signature policy template (FR-SIG-7). | I | MS2 |
| CMP-43 | **21 CFR 11.10(k).** System documentation is controlled (distribution, access, revision history). → Git with signed tags; document versions listed in the validation pack. | I | MS1 |
| CMP-44 | **E6(R3) Annex 1 §4.3; FDA Part 11 Q&A (Oct 2024).** System release, contingency, technical support, and agreements with IT and cloud providers. → SEC-117; support SLA; processor agreement template with audit rights and the subprocessor list. | I | MS2 |
| CMP-45 | **EMA *Guideline on computerised systems and electronic data in clinical trials* (EMA/INS/GCP/112288/2023), Annex 4 A4.12–A4.13.** MFA for remote and privileged access; signature functionality validated; local-law signatures in open systems. → SEC-22, SEC-29; FR-SIG-3, FR-SIG-5. | T | MS2 |
| CMP-46 | **GAMP 5 2nd ed.; ISPE GAMP Guide: Artificial Intelligence (Jul 2025).** TrialBox logic is category 5; configured components are category 4. AI functions follow the GAMP AI life cycle and use supplier evidence. → §15.4; §16. | I | MS1 |
| CMP-47 | **FDA *Computer Software Assurance* (final, 24 Sep 2025).** Assurance effort proportional to process risk: scripted tests for signing, cascade exclusion and release; scenario tests elsewhere; assurance records kept. → risk tags on `@req` tests; the validation pack states the method per function. | I | MS1 |
| CMP-48 | **TFDA 藥品優良臨床試驗作業準則 Art. 55.** Integrity assurance; SOPs; an audit trail that preserves originals; protection against unauthorised use; **a list of people authorised to change data**; backups; integrity across changes. → ledger; `trialbox access list` (roles and elevation register, SEC-23); SEC-95; G5. | T | MS2 |

#### 15.2.2 Taiwan law

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-14 | **PDPA; HSRA.** Aggregates only; rounding; accountant; IRB precondition. → PRIV-20, PRIV-21, PRIV-23, PRIV-9 (§7). | T | MS1 |
| CMP-15 | **PDPA (2025 amendment).** Breach workflow. → SEC-111, SEC-113; tabletop record. | T | MS2 |
| CMP-17 | **Hospital policy; NHI data provisions.** Opt-outs applied before lists are formed. → §7 consent scopes; FR-M4 (§10). | T | MS2 |
| CMP-32 | **NHI rules.** Coverage analysis; research items not billed to NHI. → FR-M7, FR-M10 (§10). | T | MS4 |
| CMP-49 | **PDPA Art. 27; Enforcement Rules Art. 12.** Appropriate security measures by non-government agencies. → §14; SEC-141. | I | MS1 |
| CMP-50 | **PDPA Art. 6; Enforcement Rules Art. 17.** Every purpose (feasibility, pre-screening, validation replay, D2 release) MUST name its lawful basis in the Study Card or site register. IRB approval is not a PDPA basis. → §7; §21 open decision. | I | MS1 |
| CMP-51 | **PDPA Art. 21; EMR Regulation; HSRA Art. 19.** Cross-border and cloud processing only as allowed by §15.5. D3/D4 never leave Taiwan or the perimeter. → §7; SEC-44, SEC-46, SEC-79; CMP-80, CMP-81. Supersedes CMP-16. | T | MS1 |
| CMP-52 | **HSRA Art. 4(3) (去連結).** Keyed pseudonyms are not de-linked while the key exists. No text or output may call D3 "de-linked" or "de-identified". → §7 terminology; `tools/claims_lint.py`. | T | MS1 |
| CMP-53 | **醫療機構電子病歷製作及管理辦法 (2022).** Topology B, or any vendor-hosted processing of EMR-derived data, needs: a written contract; an MOHW-recognised certification (ISO/IEC 27001); encrypted transmission; Taiwan storage unless MOHW approves otherwise. → SEC-26, SEC-45, SEC-143; contract template. | I | MS4 |
| CMP-54 | **資通安全管理法 (2025) outsourcing (委外).** For CI hospitals the vendor MUST supply: security capability evidence (SEC-141, SEC-143); the support personnel list; the subprocessor list; audit and inspection rights; incident notice ≤ 30 min (SEC-111). → `docs/compliance/tw_outsourcing_pack/`. | I | MS2 |
| CMP-55 | **資通安全事件通報應變及演練辦法 (5 Jan 2026).** Support the 1 h report and 36/72 h recovery. → SEC-97, SEC-111, SEC-114; tabletop timings. | T | MS2 |
| CMP-56 | **人工智慧基本法 (AI Basic Act, in force 14 Jan 2026).** Transparency, human oversight, privacy, safety, accountability. Track the MODA risk framework (reported v1.0, 7 Jul 2026 *(uncertain)*) and MOHW rules. Keep high-risk-ready features: AI notices, human in the loop, remedies, minimisation. → CMP-07, CMP-08, §15.4, §15.6. | I | MS1 |
| CMP-61 | **電子簽章法 (amended, promulgated 15 May 2024) Art. 4–6, 8.** Functional equivalence; counterparty consent for external documents (Art. 5); the B3 digital-signature presumption (Art. 6); signing-history retention (Art. 8). → FR-SIG-5, FR-SIG-7 (§3); ledger. | T | MS4 |
| CMP-70 | **資通安全管理法 product restrictions; MODA lists.** Restricted products and model publishers can be excluded. → SEC-66; gateway refusal test. | T | MS1 |

#### 15.2.3 Japan

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-62 | **APPI Art. 23 (security measures), Art. 25 (supervision of entrustees), Art. 26 (leak reports)** *(2022 consolidated numbering)*. The vendor acts as an entrustee under hospital supervision; leak reporting uses the JP clock profile. → SEC-113, SEC-141; entrustment contract template. | I | MS6 |
| CMP-63 | **APPI Art. 28 (foreign third parties).** No personal information is processed by a provider outside Japan unless Art. 28 is met. Whether the PPC cloud exception applies is *(uncertain; legal review)*. → §15.5; Tokyo and Osaka regions only. | I | MS6 |
| CMP-64 | **APPI 仮名加工情報 (Art. 41–42).** No third-party provision; no contact using the data; replacement keys secured. → §7 Japan profile; SEC-32. | T | MS6 |
| CMP-65 | **次世代医療基盤法 (Next-Generation Medical Infrastructure Act; 仮名加工医療情報 amendment reported in force 1 Apr 2024 *(secondary)*).** TrialBox can supply data to, or run under, a certified creator or user with the on-premises usage type. It does not claim certification itself. → §7 export profile. | I | MS6 |
| CMP-66 | **MHLW Guidelines v6.0; Medical Care Act Enforcement Ordinance Art. 14(2); MHLW checklist.** Controls mapped and evidenced per site. → SEC-142. | I | MS6 |
| CMP-67 | **MIC/METI vendor guideline v2.0 (28 Mar 2025).** Risk assessment, responsibility split and service disclosure. → SEC-142. | I | MS6 |

#### 15.2.4 AI governance and export

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-06 | **FDA draft AI credibility guidance (Jan 2025); EMA reflection paper (Sep 2024); FDA–EMA Good AI Practice principles (14 Jan 2026).** A credibility file per AI function. → §15.4. | I | MS1 |
| CMP-07 | **AI Basic Act transparency; CDS principles.** Evidence and uncertainty shown with every output. → §6 evidence model; FR-M4 (§10). | T | MS2 |
| CMP-24 | **OWASP Top 10 for LLM Applications 2025.** LLM controls. → §14.8; `redteam`. | T | MS0 |
| CMP-27 | **ISO/IEC 42001; NIST AI RMF; AI Basic Act.** AI inventory and impact assessment. → registry (§8); §15.4. | I | MS1 |
| CMP-28 | **TFDA SaMD guidance; MDCG 2019-11; FDA CDS.** Intended-use control and written analyses. → §15.3; `claims_lint`. | I | MS4 |
| CMP-57 | **ISO/IEC 42001:2023 cl. 6.1.4; Annex A (A.5 impact, A.6 life cycle, A.7 data, A.10 third parties).** An impact assessment per function; supplier controls over model publishers, Hermes and cloud providers; the AI policy; the registry as the inventory. → §8; §15.4. | I | MS2 |
| CMP-60 | **EU AI Act (Reg. (EU) 2024/1689), with the Digital Omnibus (Reg. (EU) 2026/1744 *(secondary)*), for export.** Record the classification: not Annex III; high-risk only via Art. 6(1) if ever an MDR device. Art. 4 AI-literacy records for users. Art. 50(1) notice that the user is talking to an AI system (Hermes, from 2 Aug 2026). GPAI documentation from model providers. → §9 disclosure line; training records. | I | MS6 |
| CMP-68 | **OWASP Agentic Top 10 2026; OWASP MCP Top 10 (2025).** Agentic and MCP controls. → SEC-70–SEC-74, SEC-82; `redteam`, `sec_mcp_pin`. | T | MS0 |
| CMP-69 | **FDA–EMA principles (life-cycle management); EMA reflection paper (lock models used in high-impact contexts).** Models and prompts are pinned; changes go through G5 with acceptance criteria fixed in advance, after a shadow run. → §8; §11. | T | MS1 |

#### 15.2.5 Management-system and data standards

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-10 | **ICH M11; USDM.** Protocol versions and amendment diff. → FR-M1 (§10). | T | MS1 |
| CMP-11 | **FHIR R4; TW Core; JP Core.** Conformance with pinned IGs. → §5; validator runs. | T | MS1 |
| CMP-12 | **CDISC CDASH; ODM v2.** eCRF export with lineage. → FR-M8 (§10). | T | MS5 |
| CMP-13 | **OMOP CDM 5.4; ICH M14.** Counts carry data cut, logic and manifest. → §5, §6. | T | MS1 |
| CMP-25 | **SLSA; CycloneDX.** Signed builds, SBOM, ML-BOM, licence manifests. → SEC-60–SEC-62; §8. | I | MS1 |
| CMP-31 | **42 CFR 11; EU CTR Art. 37.** Registry deadlines (IIT). → FR-M9 (§10). | T | MS5 |
| CMP-33 | **TransCelerate SIP.** Site-profile reuse; answer memory. → FR-M0, FR-M3 (§10). | T | MS1 |
| CMP-58 | **ISO/IEC 27001:2022.** Vendor ISMS certification; SoA cites SEC IDs. → SEC-143. | I | MS6 |
| CMP-59 | **ISO 25237 (health pseudonymisation; 2017 edition *(uncertain)*); ISO/IEC 27701.** Pseudonymisation roles, a written policy, re-identification only via the controlled D4 tokenisation path, and a privacy-management mapping. → §7; SEC-32. | I | MS2 |

### 15.3 Intended-use analyses (CMP-28): M5 and M7

Each feature that could drift into a medical purpose has a written analysis at
`docs/compliance/intended_use/<module>.md`. The analysis covers:
- the function, its outputs, users and setting;
- the data analysed;
- qualification against each jurisdiction's instrument: TFDA 2022 guidance, PMD Act, FDA CDS criteria 1–4, MDCG 2019-11
  rev. 1;
- the conditions that keep it non-device;
- drift triggers;
- residual risk, using ISO 14971:2019 as good practice;
- QA and system-owner sign-off (Level B, G5).

`tools/claims_lint.py` checks strings, prompts, templates and card texts in every language for prohibited claims, for
example 診斷, 建議治療, 推奨治療, "eligible", "recommend treatment" and "diagnosis".

**M5: matching both ways, tumour board, CDS Hooks card.**

| Function | Output and user | Risk | Qualification | Conditions that keep it non-device |
| --- | --- | --- | --- | --- |
| Trial → patients (shared with M4) | Candidate list with evidence, for a delegated CRC or PI | Low | Not a device in TW, JP, US or EU | Investigator decides (CMP-08); `potential:*` labels; no new diagnoses |
| Patient → trials, on request | Trial list showing met, unmet and unknown criteria with evidence, for a delegated investigator or tumour-board coordinator | Medium: could be read as a treatment option | US: CDS criteria 1–4 are met (no image or signal analysis; medical information; supports an HCP; basis reviewable) → non-device CDS. EU: research purpose, no new medical information → not MDSW. TW, JP: research support. | Ranked by criterion fit, never by expected benefit. Evidence and unmet criteria always shown. No inferred diagnosis, stage or line of therapy beyond recorded facts (`potential:data_gap` instead). Intended-use footer. |
| CDS Hooks card in the EHR (opt-in) | Card shown to a clinician who may not be delegated | Highest: inside the clinical workflow | Non-device provided the card stays informational and research-only | Non-delegated users see only "possible research match — contact the research office", with no study, criteria or PHI. Delegated users see the study and a packet link. No urgency language, no "recommended", no order actions. Fixed, linted templates. |

M5 drift triggers:
- analysis of images, waveforms or raw genomic data;
- inferred stage or diagnosis;
- ranking by predicted outcome;
- patient-facing output;
- standard-of-care suggestions;
- auto-enrolment.

**M7: conduct and safety support.**

| Function | Risk | Qualification | Conditions |
| --- | --- | --- | --- |
| Listing abnormal results and hospital-graded events for enrolled participants | Medium: a missed event | GCP support, not individual care → non-device | Lists only events already graded or flagged by hospital systems. No CTCAE grade, causality or expectedness is computed. Completeness and data cut are shown. Labelled "aid; the investigator's safety process is the system of record". |
| SAE/SUSAR clocks (ICH E2A, TFDA) | Medium: a late report | Administrative | The clock starts at the investigator-entered awareness time. Reminders escalate. The box never files or classifies. |
| Visit-window, IP-accountability and lab-kit prompts; deviation log | Low | Administrative or GCP record | No dosing or randomisation data (CMP-09); deviations under CMP-20 |

M7 drift triggers:
- automatic CTCAE grading;
- causality suggestions;
- dose advice;
- unblinded data;
- auto-submission to sponsors or authorities.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-71 | The M5 and M7 analyses MUST be signed (Level B, G5) before those features are enabled at a site: M5 open-study matching before MS2 (silent), registry and tumour board before MS4; M7 safety support and the CDS Hooks card before MS5. The CDS Hooks card also needs sign-off from the hospital's medical-informatics committee. | I | MS4 |
| CMP-72 | `tools/claims_lint.py` MUST run in CI and on site configuration changes. A prohibited claim blocks the change. | T | MS1 |
| CMP-73 | A change that matches a drift trigger MUST reopen the analysis. The feature stays disabled until the analysis is re-signed. | I | MS4 |

### 15.4 AI credibility files

Each registry role (§8) has `docs/compliance/credibility/<role>.md`, regenerated by `trialbox validate --credibility`
from the registry, evaluation results and monitoring.

The file structure follows:
- the seven steps of the FDA Jan 2025 draft: question, context of use (COU), model risk (influence × consequence),
  plan, execution, results and deviations, adequacy;
- the FDA–EMA principles;
- ISO/IEC 42001 A.5–A.7;
- the ISPE GAMP AI guide.

Each file contains:
- the COU;
- the risk tier;
- the data and their licences;
- results per language stratum (zh-TW, en, ja, code-mixed), with confidence intervals;
- known failure modes;
- oversight points;
- the monitoring plan;
- the G5 history.

| Role (§8) | COU (short) | Influence × consequence | Tier | Key evidence (§16) |
| --- | --- | --- | --- | --- |
| `classify_intent` | Propose a typed request; a human confirms | Low × low | 1 | Proposal accuracy ≥ 0.95 *(target)*; `redteam` |
| `extract_criteria`, `concept_select` | Draft IR; G1 review | Medium × medium | 2 | `criteria_extract_public`; concept F1 per domain; CQL≡SQL gate |
| S2b pre-filter and lexicon zero-hit exclusion | May exclude patients unread | High × medium-high | 3 | `lexicon_recall` 95 % lower bound ≥ 0.98 per stratum before zero-hit exclusion (CAS-13); elusion bound |
| `judge`, `second_opinion` | Criterion judgement with quotes; negatives audited by sampling | Medium × medium-high | 3 | `judge_public` (1,015 annotations); `judge_ml` per stratum; abstention calibration; anytime-valid recall certificate |
| Matching ranker (M5) | Order trials or patients for review | Medium × medium | 2 | `match_registry` (TrialGPT cohorts); §15.3 conditions |
| Recruitability model | Projection for sponsors | Medium × medium | 2 | Forecast-ledger calibration slope; Brier score |
| `abstract_field` (M8) | eCRF pre-fill; Level B certification | Medium × high | 3 | Field agreement ≥ 0.95 *(target)*; lineage; certification negatives |
| `draft_narrative`, `map_questionnaire`, `answer_protocol`, `draft_query_answer` | Human-reviewed drafts; numbers injected deterministically | Low × low-medium | 1–2 | `numbers_match`; citation verifier; reviewer edit rate |
| Guardrail classifiers | Security and privacy controls | High × high | 3 | Red-team false-negative rate; de-identification recall ≥ 0.98 for names and IDs |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-74 | Every production role MUST have a current credibility file. A G5 change to a model, prompt, threshold or guardrail regenerates the file, and QA approves it before promotion. | T, I | MS1 |
| CMP-75 | Tier 3 roles MUST have per-stratum results with confidence intervals and live monitoring with control limits. A breach opens a deviation and triggers the §18 rollback for that change class. | T | MS2 |
| CMP-76 | The AI inventory, impact assessments and credibility files MUST be exportable to the hospital AI governance body and attachable to IRB submissions. | I | MS2 |

### 15.5 Cloud and hybrid cross-border analysis per data class

This table states the §7 boundary rules as legal analysis. The gateway (§8), `tb-egress` (SEC-40) and SEC-79 enforce
them. Counsel reviews it before any topology B or C go-live (§21).

| Class | Topology B (hospital tenant, in-country) | Topology C (cloud model calls) | Taiwan | Japan | Preconditions |
| --- | --- | --- | --- | --- | --- |
| D0 public | Allowed | Allowed (approved providers; OpenRouter in dev only) | No personal data | No personal data | Provider allowlist |
| D1 confidential, no PHI | Allowed | Hospital-owned D1 allowed. Sponsor D1 only with written consent per protocol. Default off. | Contract confidentiality, not PDPA | Same | Consent record; ZDR and no-training evidence (SEC-79) |
| D2 de-identified | Allowed under TRE controls | Default off. Allowed only with a documented re-identification risk below the threshold, a PDPA Art. 21 assessment, IRB and DPO sign-off, and an in-country region. | PDPA Art. 6(1)(4) requires non-identifiability; HSRA Art. 19 applies if not de-linked | 匿名加工情報 may be provided after its categories are published. 仮名加工情報 is personal information and Art. 28 applies *(legal review)*. | D2 release certificate (§7); Five Safes; cross-border record |
| D3 pseudonymised | Only in the hospital's own tenant, in Taiwan, with customer-managed keys and no vendor access | **Never** | Personal data; not 去連結 | Personal information | Tenant attestation; CMK evidence; region lock |
| D4 identified | Only where the HIS itself is hosted there | **Never** | Same; EMR storage in Taiwan | Same | — |
| Suppressed aggregates | Allowed | Allowed | Non-personal | Statistical | Accountant record (PRIV-21, PRIV-23) |
| Security events | Hospital SIEM only | — | Staff personal data | Same | No vendor telemetry (§18) |
| Vendor support views | — | — | A D3/D4 view by staff abroad is a cross-border transfer | Same | SEC-29: redacted by default; in-country staff only |

**EU parties.** Taiwan has no GDPR adequacy decision. TrialBox sends no EU personal data abroad, and its aggregates are
non-personal. Personal-data transfers between an EU sponsor and the site fall under those parties' SCCs.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CMP-80 | Each site MUST keep a **data egress register** (`trialbox egress register`, also shown in the console). For every external destination it records: class, legal basis, contract, region, ZDR or abuse-monitoring evidence, approval and review date. The register feeds the Taiwan 委外 audits and the Japanese 責任分界表. | T, I | MS1 |
| CMP-81 | The class rules MUST be enforced in code at the gateway and at `tb-egress`. `sec_class_egress` MUST show that D3/D4 content cannot reach a non-perimeter endpoint in topologies A, B or C. | T | MS0 |
| CMP-82 | Enabling D2, or sponsor-confidential D1, in the cloud MUST require a cross-border record (`docs/compliance/crossborder/<site>/<route>.md`, with legal review), dual control and G5. | I | MS4 |
| CMP-83 | Topology B MUST pin all storage, backups, logs and keys to Taiwan regions (Tokyo or Osaka in Japan), with cross-region replication off. A service that cannot be pinned is disabled. | T, I | MS4 |

### 15.6 Regulatory watch list

These facts are uncertain and affect the design. Each is re-checked by the milestone named, and the result is recorded
in the trace matrix.

| Item | Assumption | Impact if different | By |
| --- | --- | --- | --- |
| CSMA article effectivity; current CI hospital list and levels | In force 1 Dec 2025 | Which sites the clock and outsourcing duties apply to | MS2 |
| Wording and article numbers of the 1 h and 36/72 h rules | Art. 11 and Art. 13 (5 Jan 2026) | Runbook references | MS2 |
| PDPA breach deadline and effective date | Implementing rules; 72 h internal target | Clock profile | MS2 |
| MODA restrictions reaching CI hospitals or model families | Not listed | Default model set | MS1 |
| MODA AI risk framework; MOHW medical-AI rules | Framework reported 7 Jul 2026 | High-risk duties | MS3 |
| MHLW guideline 第7.0版 | Reported June 2026, unconfirmed | Remap SEC-142 | MS6 |
| Japanese core-infrastructure designation of hospitals; APPI deadlines and Law No. 56 | Pending; 3–5 / 30–60 days | Pre-notification; JP clock | MS6 |
| FDA premarket cybersecurity guidance, Feb 2026 version | Benchmark | Package headings | MS2 |
| ISO/IEC 27701:2025; ISO 25237 edition | 2025 standalone; 2017 | Certification scope | MS3 |
| MCP revision; OWASP MCP Top 10 final; ATLAS IDs | 2026-07-28; beta; §14.3.6 | `mcp_pins.lock`; labels | Each release |
| GB10 dTPM, custom-key Secure Boot and confidential computing | dTPM can be enabled; CC not documented | SEC-50 path | MS1 |
| Exchange application-access scoping for Graph | Available | SEC-27 | MS1 |
