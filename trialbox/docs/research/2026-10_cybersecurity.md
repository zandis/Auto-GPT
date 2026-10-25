# TrialBox Cybersecurity Design (v4 research input)

*Research date: 2026-10-17. Scope: TrialBox is an on-prem-first AI appliance installed inside hospitals. It launches in Taiwan, with Japan to follow, and hybrid cloud is optional. It processes PHI and runs local LLMs on an NVIDIA GB10 (DGX Spark-class) or x86 GPU box. It is reached through email and Microsoft Teams channels, and also has an admin console, a signing page, model/software updates, and optional cloud LLM calls. Claims carry source URLs. **[Unverified]** marks anything I could not confirm against a primary source in this session. The web-search budget ran out before every item could be checked, so items marked [Unverified] need a primary-source check before they go into a contract or regulatory filing.*

---

## 0. System context and assumptions

For security allocation, the appliance breaks down into these components (they are used in §6):

| ID | Component | Notes |
|---|---|---|
| C1 | Hardware platform (GB10 / x86 + GPU), firmware, BMC/EC | Physically inside the hospital data centre or IT room |
| C2 | Host OS (DGX OS / Ubuntu LTS), kernel, drivers (CUDA, NIC) | |
| C3 | Container runtime and orchestration (Podman/containerd, k3s optional) | |
| C4 | LLM inference service (vLLM/TensorRT-LLM/Triton/llama.cpp) + model weights | Local weights, possibly LoRA adapters fine-tuned on site data |
| C5 | Agent orchestrator + MCP tool servers (document parsing, CTMS/EDC/HIS read connectors, drafting, scheduling) | The highest-risk logic component |
| C6 | Data stores: relational DB, object store, vector store/RAG index, site lexicon and exemplar library | Contains PHI and trial-confidential data |
| C7 | Channel connectors: email (SMTP/IMAP or Microsoft Graph), Teams bot (Bot Framework / Graph) | Untrusted input ingress |
| C8 | Admin console (web UI + API) | Privileged plane |
| C9 | Signing page (sign-off/attestation of generated documents by investigators/staff) | Integrity- and non-repudiation-critical |
| C10 | Update/model-delivery pipeline (vendor build system → signed bundles → online or offline import) | Supply-chain root |
| C11 | Optional cloud LLM gateway / hybrid cloud tenancy | Egress of data |
| C12 | Observability: audit log, security log forwarder to hospital SOC/SIEM | |
| C13 | Backup/restore subsystem | Ransomware resilience |
| C14 | Vendor remote support path | Historically the No. 1 hospital-breach entry point |

Assumptions: the hospital remains the data controller (醫療機構 / 医療機関). The TrialBox vendor is a processor/outsourced IT provider (受託者 / 医療情報システム提供事業者). TrialBox is not marketed as a medical device. It is a clinical-research operations tool, but medical-device security frameworks are used as a benchmark (§1.4).

---

## 1. Applicable frameworks and laws

### 1.1 Taiwan

**Cyber Security Management Act (資通安全管理法), 2025 amendment.** The Legislative Yuan passed the amendment on 29 August 2025 and the President promulgated it on 24 September 2025 ([uanalyze summary](https://uanalyze.com.tw/articles/8088433846); [Baker McKenzie alert](https://www.bakermckenzie.com/en/insight/publications/alerts/2025/10/taiwan-amendment-to-cybersecurity-management-act)). The Ministry of Digital Affairs (MODA) is now the competent authority and its Administration for Cyber Security (資安署, ACS) executes the Act. The main changes are:
- A CISO (資通安全長) and dedicated full-time security staff are now required for government agencies **and specific non-government agencies (特定非公務機關)** ([iThome](https://www.ithome.com.tw/news/163804)).
- Tighter outsourcing obligations, and powers for MODA to restrict products that endanger national cybersecurity ([Baker McKenzie](https://connectontech.bakermckenzie.com/taiwan-amendment-to-cybersecurity-management-act/)).
- Higher penalties. The cap for a specific non-government agency failing to report an incident is reported as **NT$10 million** ([search summary of uanalyze/cnyes coverage](https://m.cnyes.com/news/id/6166189)). Obstructing ACS investigation of a major incident can cost up to NT$1 million ([iThome](https://www.ithome.com.tw/news/163804)).
- Effective date: a Taipei City law-database record cites Executive Yuan order 院臺安字第1141033966號 setting **1 December 2025** ([laws.gov.taipei record](https://laws.gov.taipei/law/LawSearch/LawExport/FL088622?type=0)). Another record still showed "not yet in force", so **[Unverified]** whether every article took effect on that date.

**Hospitals as critical infrastructure (CI).** MOHW designates certain public and private medical centres and regional hospitals as CI providers, with Executive Yuan approval, and the designated private hospitals thereby become specific non-government agencies. Reported counts are 46, 60 and 64 hospitals at different times ([iThome 148548](https://www.ithome.com.tw/news/148548); [iThome 175668](https://www.ithome.com.tw/news/175668)). Audit documents state that private medical centres are assigned **security responsibility level A (資安責任等級 A級)**, the same as public hospitals, while MOHW-affiliated regional/district hospitals are level B ([Control Yuan audit doc](https://cybsbox.cy.gov.tw/CYBSBoxSSL/edoc/download/67857)). CI hospitals must have a deputy-head-level CISO. On 15 August 2025, MOHW and ACS announced a "medical CI security strengthening" programme with realistic drills, talent development, guidance and stronger audits, and they plan to bring cybersecurity into hospital accreditation ([MOHW press release](https://mohw.gov.tw/cp-16-83515-1.html); [UDN](https://udn.com/news/story/7266/8942237)). Hospital accreditation has used ISO 27001 as a key indicator since 2019 and has checked membership of the medical H-ISAC ([iThome 129459](https://www.ithome.com.tw/news/129459)).

**Incident reporting.** The subsidiary regulation is now titled 資通安全事件通報應變及演練辦法, last amended **5 January 2026** ([laws.gov.taipei FL089967](https://laws.gov.taipei/Law/LawSearch/LawArticleContent/FL089967)). Its key rules:
- Art. 11: a specific non-government agency must report **within 1 hour of becoming aware** of an incident, through the method its sector authority (MOHW) designates.
- Art. 13: damage control or recovery must be finished **within 72 hours** for level 1–2 incidents and **within 36 hours** for "major" (重大) incidents.
- Art. 2 defines four incident levels. Level 3–4 incidents involve CI core-business information or disruption.
- MOHW must then confirm the level, within 8 hours for level 1–2 and within 2 hours for major incidents ([MODA doc](https://www-api.moda.gov.tw/File/Get/acs/zh-tw/BEhQqY8TPULrRuE)).

**Other Taiwan instruments.**
- *Security responsibility levels and system protection baseline* (資通安全責任等級分級辦法 and its annexed 資通系統防護基準). Systems are rated high/medium/low on the 防護需求等級 scale and must meet baseline control sets derived from NIST SP 800-53 families. A clinical-trial system holding PHI in a level-A hospital will almost certainly be rated **high** **[Unverified: hospital-specific rating]**.
- *Medical Institutions Electronic Medical Record Regulation* (醫療機構電子病歷製作及管理辦法, amended July 2022). It allows outsourcing and cloud hosting of EMR systems but requires a written contract, a contractor certified to an MOHW-recognised information-security standard, encrypted transmission, and **storage in Taiwan unless MOHW approves otherwise** ([iThome 152315](https://www.ithome.com.tw/pr/152315); [CIO Taiwan](https://www.cio.com.tw/107975/)).
- *Personal Data Protection Act* amendment, promulgated 11 November 2025. It creates the independent Personal Data Protection Commission (個資會), an explicit obligation to notify the Commission of breaches, and fines up to NT$10 million for serious security failures. The effective date and notification deadline are still set by implementing rules ([Lee and Li](https://www.leeandli.com/TW/NewslettersDetail/7532.htm)) **[Unverified: final deadline; drafts used 72 h]**.
- *Government AI restrictions*: MODA has restricted public-sector use of DeepSeek and other products regarded as endangering national security. The amended Act lets MODA extend product restrictions to specific non-government agencies **[Unverified: whether any open-weight model family is formally listed]**.

**Implications for the spec**
- Treat every CI hospital customer as subject to a **1-hour incident notification clock**. TrialBox must detect, triage and hand the hospital a structured incident record (what, when, which data, which systems) fast enough for the hospital to meet it. Contracts should commit the vendor to notify the hospital within **≤30 minutes** of vendor awareness.
- Design TrialBox as a "high" protection-need system under 資通系統防護基準: MFA, audit logging, encryption, vulnerability management and change control are mandatory.
- The vendor must hold **ISO/IEC 27001** (ideally with 27701) and have a named security contact. The outsourcing (委外) clauses of the Act require hospitals to vet the vendor's security capability, personnel and sub-processors.
- Data stays in Taiwan by default. Any cloud egress needs MOHW-aligned justification and must be off unless enabled (§5).
- Keep a **model provenance register** (country of origin, licence, publisher) so CI hospitals can exclude restricted products. Ship a default model set that avoids publishers on government restriction lists.

### 1.2 Japan

**MHLW Guidelines for the Security Management of Medical Information Systems, v6.0** (医療情報システムの安全管理に関するガイドライン 第6.0版). Published 31 May 2023 and restructured into an overview plus three volumes: management, planning and system operation. It covers cloud services, zero-trust thinking, and preparations for ransomware ([MHLW notice](https://www.mhlw.go.jp/content/10808000/001102596.pdf); [MHLW guideline page](https://www.mhlw.go.jp/stf/shingi/0000516275_00006.html)).

**Legal hook.** Ordinance for Enforcement of the Medical Care Act Art. 14(2) has applied since 1 April 2023 and obliges hospital administrators to take cybersecurity measures by reference to the latest guideline. Prefectural on-site inspections use the **MHLW cybersecurity checklist for medical institutions**, which is revised each fiscal year. The FY2025 revision added items such as password length, restrictions on external devices and two-factor authentication ([MHLW material](https://www.mhlw.go.jp/content/10808000/001450188.pdf); [Nagasaki notice](https://www.pref.nagasaki.lg.jp/shared/uploads/2025/07/1752371647-3.pdf); [Trend Micro JP](https://www.trendmicro.com/ja_jp/jp-security/23/d/securitytrend-20230404-01.html)). The checklist also has a vendor-side confirmation sheet **[Unverified: FY2026 version contents]**.

**"3 ministries, 2 guidelines" (3省2ガイドライン).** Vendors follow the MIC/METI *Guidelines for Safety Management by Providers of Information Systems and Services Handling Medical Information*. Version 2.0 was published on 28 March 2025 after public comment ([MIC press release](https://www.soumu.go.jp/menu_news/s-news/01ryutsu06_02000427.html)). It requires the vendor to:
- run a risk assessment;
- agree a responsibility split with the medical institution;
- provide service-specification disclosures. In practice this is the JAHIS/JIRA "製造業者/サービス事業者による医療情報セキュリティ開示書" (MDS/SDS) **[Unverified: current MDS/SDS version]**.

**Critical infrastructure.** The Act on Strengthening Cyber Response Capabilities (サイバー対処能力強化法, "active cyber defence") was enacted 16 May 2025. Its main provisions, including incident reporting and asset notification by core-infrastructure operators, are reported to take effect **1 October 2026** ([PwC JP](https://www.pwc.com/jp/ja/knowledge/column/awareness-cyber-security/active-cyber-defense-impact1.html); [Trend Micro JP](https://www.trendmicro.com/ja_jp/jp-security/26/h/securitytrend-20260814-01.html)). Cabinet Office material describes adding the **medical sector**, including "medical services provided by hospitals", to the core-infrastructure (特定社会基盤事業) regime of the Economic Security Promotion Act, limited to hospitals with advanced capabilities designated by ministerial ordinance ([Cabinet Office bill summary](https://www.cao.go.jp/houan/pdf/221/221_1gaiyou.pdf); [MHLW Dec 2025 material](https://www.mhlw.go.jp/content/10801000/001565765.pdf)) **[Unverified: enactment status and designation criteria as of Oct 2026]**. If a hospital is designated, introducing or outsourcing maintenance of "specified critical equipment" needs prior notification and a review by the competent minister, normally 30 days.

**APPI.** Leaks of special-care-required personal information (medical data) must be reported to the Personal Information Protection Commission: a preliminary report within roughly 3–5 days and a final report within 30 days, or 60 days for unauthorised-access cases ([PPC guidance](https://www.ppc.go.jp/personalinfo/legal/leakAction/)) **[Unverified: re-check current PPC text]**.

**Implications for the spec**
- Ship a **Japanese MDS/SDS disclosure** and a responsibility-split matrix (責任分界表) with every Japanese deployment. Map controls to guideline v6.0 system-operation volume items and to the current MHLW checklist, including the vendor-side checklist.
- Japanese default: an **offline/immutable backup** and a documented recovery runbook, because the guideline and checklist specifically ask for backups that survive ransomware.
- Remote maintenance needs individually issued accounts, MFA, session recording and **no always-on VPN appliances** (see the Osaka case, §2.6).
- Design the update/maintenance outsourcing so that a designated hospital can file a pre-introduction notification. That means a stable bill of materials, the supplier list, and the country of origin of key components.

### 1.3 International security management frameworks

- **NIST CSF 2.0** (Feb 2024) adds a *Govern* function. It is the common language for hospital CISOs and for NIST SP 800-61r3 ([NIST CSF](https://www.nist.gov/cyberframework); [CSWP 29](https://doi.org/10.6028/NIST.CSWP.29)).
- **NIST SP 800-53 Rev. 5** is the control catalogue. Taiwan's 防護基準 is derived from it ([CSRC](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)). NIST's **COSAIS** project (Control Overlays for Securing AI Systems) is building 800-53 overlays for generative AI, predictive AI, single-agent and multi-agent systems; the concept paper is dated August 2025 ([Campus Technology](https://campustechnology.com/articles/2025/08/19/nist-proposes-new-cybersecurity-guidelines-for-ai-systems.aspx)) **[Unverified: public draft status]**.
- **NIST SP 800-171 Rev. 3** (May 2024) is a compact CUI baseline and a useful "minimum control set" checklist for a small vendor ([CSRC](https://csrc.nist.gov/pubs/sp/800/171/r3/final)).
- **ISO/IEC 27001:2022** is the ISMS certification Taiwanese hospital procurement expects ([ISO](https://www.iso.org/standard/27001)). **ISO/IEC 27017** covers cloud controls and **ISO/IEC 27018** covers PII protection in public clouds; both are relevant when hybrid mode is on ([27017](https://www.iso.org/standard/43757.html), [27018](https://www.iso.org/standard/76559.html)). **ISO/IEC 27701** is the privacy information management extension ([ISO](https://www.iso.org/standard/71670.html)); a 2025 standalone edition was expected **[Unverified]**. **ISO 27799:2016** is 27002 guidance for health ([ISO](https://www.iso.org/standard/62777.html)). **ISO/IEC 42001:2023** is the AI management system ([ISO](https://www.iso.org/standard/81230.html)).
- **IEC 62443.** Part 4-1 (secure product development lifecycle) and part 4-2 (component technical requirements, SL1–SL4) apply to the appliance as a product. Part 3-3 (system security requirements) applies to the deployed system, and part 2-4 to service providers ([ISA overview](https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards)).
- **IEC 81001-5-1:2021** is the security lifecycle for health software and health IT. It is modelled on 62443-4-1 and recognised by FDA and the EU MDR ecosystem ([IEC webstore](https://webstore.iec.ch/en/publication/62343)) **[Unverified: URL]**.
- **FDA premarket cybersecurity guidance.** The September 2023 final guidance was superseded on **27 June 2025** by a version that adds Section VII on §524B "cyber devices". FDA's own text says a **February 2026** retitled version ("Quality Management System Considerations…") superseded the June 2025 one ([FDA guidance page](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/cybersecurity-medical-devices-quality-management-system-considerations-and-content-premarket); [Health-ISAC](https://health-isac.org/fda-expands-premarket-medical-device-cyber-guidance/); [Hogan Lovells](https://www.hoganlovells.com/en/publications/fda-finalizes-cyber-device-select-updates-guidance)). Its expectations work as a quality benchmark even for a non-device:
  - a Secure Product Development Framework (SPDF);
  - threat modelling;
  - a security risk assessment separate from safety risk;
  - an SBOM including support status;
  - security architecture views (global, multi-patient, updatability, security use-case);
  - testing (penetration, fuzzing, SCA);
  - labelling;
  - a postmarket vulnerability plan.
- **MDS2** (ANSI/NEMA HN 1-2019) is the hospital-procurement security questionnaire. A revision, HN 1-202X, is planned for end-2026 ([NEMA standards plan](https://www.nema.org/standards/standards-plan)).
- **HITRUST**: CSF v11.x and the **HITRUST AI Security Assessment and Certification** launched December 2024 with up to 44 AI-specific controls ([HITRUST blog](https://hitrustalliance.net/blog/building-trust-in-ai-introducing-the-hitrust-ai-security-assessment-and-certification)). It matters mostly for US/multinational sponsors and CROs.
- **AI-specific references**: [NIST AI 100-2 E2025](https://csrc.nist.gov/pubs/ai/100/2/e2025/final) (adversarial ML taxonomy, March 2025), [NIST SP 800-218A](https://csrc.nist.gov/pubs/sp/800/218/a/final) (SSDF profile for generative AI), [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework).

**Implications for the spec**
- Adopt **IEC 81001-5-1 + IEC 62443-4-1** as the vendor SDLC and target **62443-4-2 SL2** for the appliance, with SL3 for identification/authentication and data confidentiality. That mapping answers both Taiwan and Japan procurement questions.
- Produce, per release: an **FDA-style security package** (threat model, architecture views, SBOM with support dates, VEX, pentest summary), an **MDS2** and a **Japanese MDS/SDS**.
- Certify the vendor on **ISO 27001 + 27701** in year 1. Add **ISO 42001** or the **HITRUST AI Security** certification when sponsors ask for it.
- Use **NIST CSF 2.0** as the top-level mapping in the security whitepaper, cross-walked to 800-53 (Taiwan baseline) and the MHLW checklist (Japan).

---

## 2. Threat model

### 2.1 Method

Four lenses are applied to a data-flow diagram of C1–C14. **STRIDE** is applied per element and per trust-boundary crossing. **LINDDUN** covers privacy threats ([linddun.org](https://linddun.org)). Techniques are labelled with **MITRE ATT&CK** for enterprise intrusion ([attack.mitre.org](https://attack.mitre.org)) and **MITRE ATLAS** for AI-specific attacks ([atlas.mitre.org](https://atlas.mitre.org)). LLM/agent threats are categorised with **OWASP Top 10 for LLM Applications 2025** ([genai.owasp.org](https://genai.owasp.org/llm-top-10/)) and the **OWASP Top 10 for Agentic Applications 2026**, published 9 December 2025 ([OWASP GenAI](https://genai.owasp.org/); [Cycode summary](https://cycode.com/blog/owasp-top-10-agentic-applications/)). The model is re-run at every release that adds a tool, connector or data source.

### 2.2 Trust boundaries

- TB1 Internet ↔ hospital perimeter (email, Teams/M365 cloud, vendor update server, cloud LLM).
- TB2 Hospital LAN ↔ TrialBox appliance (users, HIS/EMR, AD/Entra ID, SIEM).
- TB3 Inside the appliance: channel connectors ↔ agent orchestrator ↔ MCP tools ↔ data stores ↔ inference engine.
- TB4 LLM ↔ everything. Model output is treated as untrusted. This is the boundary most often forgotten.
- TB5 Vendor build/release ↔ appliance (supply chain).
- TB6 Appliance ↔ backup target.

### 2.3 STRIDE highlights

| Threat | Example against TrialBox | Primary mitigations (§3–4) |
|---|---|---|
| **S**poofing | Spoofed email from a "PI" asks the agent to send a subject list; a forged Teams identity; a stolen admin session | DMARC/SPF/DKIM enforcement, sender allow-lists bound to directory identity, Entra ID SSO + phishing-resistant MFA, mTLS between services |
| **T**ampering | Altered model weights or LoRA; poisoned site lexicon; edited audit log; altered document after signature | Signed models and images, hash-chained audit log, WORM backup, signature-binding of document hash |
| **R**epudiation | Investigator denies approving a generated document | Signing page with strong authentication, signed timestamp, immutable audit trail |
| **I**nformation disclosure | PHI exfiltrated via prompt injection → email reply; PHI in logs; cloud LLM retention | Output egress filter, recipient policy, PHI-aware logging, de-identification before cloud, ZDR |
| **D**enial of service | Ransomware on the hospital network encrypts the appliance; prompt floods; GPU exhaustion (OWASP LLM10) | Segmentation, immutable OS, rate limits, token budgets, offline backup |
| **E**levation of privilege | Agent tool used as confused deputy; container escape; admin console RCE | Least-privilege tools, per-user authorisation on every tool call, rootless + seccomp, WAF-grade input validation |

### 2.4 LINDDUN highlights

- **Linking/Identifying**: free-text trial documents re-identify subjects even after pseudonymisation; embeddings in the vector store hold PHI that is recoverable via similarity search.
- **Detecting**: knowing a patient is in a trial's corpus discloses enrolment, which is itself sensitive. Membership inference against fine-tuned adapters is the technical form of this (§4.6).
- **Data disclosure**: over-collection by connectors (whole mailbox rather than a dedicated mailbox), prompts retained in logs, cloud vendor retention.
- **Unawareness/Non-compliance**: subjects are unaware their data is processed by AI. Consent forms and IRB approvals may need an AI-processing statement **[Unverified: Taiwan/Japan IRB expectations]**.

### 2.5 LLM, agentic and MCP threats

- OWASP LLM 2025: LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Supply Chain, LLM04 Data and Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption ([HCL AppScan mapping](https://help.hcl-software.com/appscan/Enterprise/10.10.0/topics/r_owasp_top_10_for_llm.html)).
- OWASP Agentic 2026 starts with **ASI01 Agent Goal Hijack**: the agent's objective is redirected through content it reads (emails, PDFs, tool outputs). It also covers tool misuse, identity/privilege abuse, agentic supply chain, memory and context poisoning, cascading failures and rogue agents ([guptadeepak ASI01](https://guptadeepak.com/agent-security/threats/asi01/)). The EchoLeak zero-click exfiltration via an email to an M365 Copilot user is the canonical real-world example, cited as CVSS 9.3 ([Polygraf](https://www.polygraf.ai/?p=28067)) **[Unverified: CVE number]**.
- **MCP-specific** threats ([MCP security best practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices); [OWASP MCP cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html)):
  - *tool poisoning*: hidden instructions in tool descriptions;
  - *rug pull*: tool definitions change after approval;
  - *confused deputy*: an MCP proxy with a static OAuth client ID, or a server acting with super-user credentials;
  - *token passthrough*: accepting tokens not issued for the server;
  - *session hijacking*;
  - *cross-server shadowing*: one server's description influencing use of another;
  - over-broad local server privileges.
- ATLAS techniques in scope: AML.T0051 LLM Prompt Injection (direct/indirect), AML.T0054 LLM Jailbreak, AML.T0020 Poison Training Data, AML.T0010 ML Supply Chain Compromise, AML.T0024 Exfiltration via ML Inference API (membership inference/inversion), AML.T0057 LLM Data Leakage **[Unverified: exact current technique IDs; ATLAS renumbers periodically]**.

### 2.6 Ransomware and hospital intrusion patterns

- **Mackay Memorial Hospital, Taiwan, February 2025.** The CrazyHunter group encrypted 500+ PCs across the Taipei and Tamsui campuses and offered allegedly 16.6 million patient records for sale. Taiwan's CIB named a PRC-based suspect ([Taiwan News](https://www.taiwannews.com.tw/en/news/6053546); [Taiwan News](https://www.taiwannews.com.tw/en/news/6075420)). Analysts report the ransomware was built from the open-source "Prince" builder ([SOCRadar](https://socradar.io/blog/dark-web-profile-crazyhunter-ransomware/)), and that Active Directory GPO distribution and BYOVD (bring-your-own-vulnerable-driver) were used to kill EDR **[Unverified]**. Changhua Christian Hospital was compromised in the same campaign with admin privileges obtained.
- **Osaka General Medical Center, Japan, October 2022.** Attackers entered via a VPN appliance vulnerability at a **catering contractor**, used RDP into the hospital's catering server, and moved laterally through **shared/reused credentials** until they encrypted the EMR ([investigation report summary](https://www.gh.opho.jp/pdf/reportgaiyo_v01.pdf); [MHLW notice](https://www.mhlw.go.jp/content/10808000/001024395.pdf)).
- ATT&CK techniques to design against: T1133 External Remote Services, T1190 Exploit Public-Facing Application, T1078 Valid Accounts, T1021.001 RDP, T1484.001 Group Policy Modification, T1068 / BYOVD, T1486 Data Encrypted for Impact, T1490 Inhibit System Recovery, T1567 Exfiltration Over Web Service.

### 2.7 Supply chain, insider and email-borne threats

- **Supply chain**:
  - malicious or typosquatted PyPI packages in the inference/agent stack;
  - compromised base images;
  - models in pickle format executing code on load;
  - trojaned LoRA adapters;
  - malicious MCP servers;
  - poisoned Hugging Face repos;
  - firmware vulnerabilities. The GB10/DGX Spark firmware had 14 CVEs (CVE-2025-33187…33200), many in SROOT firmware, fixed in a DGX OS OTA update ([Rewterz advisory](https://rewterz.com/?p=42503)); a DGX OS image issue shipped identical SSH host keys to multiple systems ([vulners](https://vulners.com/search/vendors/nvidia/products/dgx%20os)) **[Unverified: CVE-2026-24218 details]**.
- **Insider**:
  - a hospital admin bulk-exporting PHI through the console;
  - a vendor support engineer abusing remote access;
  - a research coordinator using the agent to query patients outside their trial;
  - ML engineers retaining training data.
- **Email**:
  - phishing to steal admin credentials;
  - malicious attachments (macro, PDF exploit, HTML smuggling) parsed by the document pipeline;
  - indirect prompt injection in the body or attachments;
  - reply-chain hijacking to redirect the agent's outputs to an external address.

**Implications for the spec**
- Keep a **living threat model** (DFD + STRIDE/LINDDUN tables + ATLAS/OWASP mapping) in the repository, versioned per release. It is a release gate.
- Treat **every byte from email, Teams, attachments, HIS documents and tool outputs as untrusted instructions** (TB4), whatever the sender's authentication status.
- Make the **remote-support path (C14)** and **directory integration** first-class threat surfaces. No persistent inbound VPN, no shared credentials, no domain-admin service accounts.
- Explicitly design for **"hospital AD is compromised"**. TrialBox must not fall if the domain falls: local break-glass, no GPO-managed agents on the appliance, independent backup credentials.

---

## 3. Controls by layer

### 3.1 Hardware root of trust, secure boot, TPM

- Enable **UEFI Secure Boot** with vendor-controlled keys (custom db/KEK), signed kernel and modules. Enrol a measured boot chain into a **TPM 2.0**, discrete or firmware. On DGX Spark, NVIDIA documents a dTPM that is **off by default on first-party systems** but can be enabled with signed driver/kernel components. Firmware updates come as secure UEFI capsules via LVFS/fwupd ([NVIDIA DGX Spark porting guide](https://docs.nvidia.com/dgx/dgx-spark-porting-guide/porting/software-requirements.html); [NVIDIA forum](https://forums.developer.nvidia.com/t/the-dgx-spark-firmware-stack/384721)). On x86, require TPM 2.0, Secure Boot, BMC (iDRAC/iLO/XCC) on an isolated management VLAN with default credentials removed, and firmware resilience per [NIST SP 800-193](https://csrc.nist.gov/pubs/sp/800/193/final).
- Use **remote attestation**: the appliance produces a TPM quote over PCRs and the release manifest hash, which the admin console shows and the update service checks before delivering model bundles.
- Physical security: chassis-intrusion detection where available, disabled unused USB/Thunderbolt ports (kernel lockdown, USBGuard), locked rack. The FY2025 MHLW checklist calls for restricting external devices.

### 3.2 Disk encryption

- **LUKS2** full-disk encryption on all data partitions, unlocked by **TPM-sealed keys bound to PCRs** (secure-boot state + kernel). This is Clevis/systemd-cryptenroll, optionally Tang for network-bound unlock inside the hospital. A recovery key is escrowed with the hospital, never only with the vendor.
- Separate encrypted volumes for: OS (read-only), models (integrity-verified with dm-verity, since weights are not secret but must be authentic), PHI data stores (encrypted, with application-level envelope encryption for the most sensitive tables) and logs.
- Crypto-shred on decommission: destroy the TPM-sealed keys and keep a certificate of destruction for the hospital.

### 3.3 OS hardening

- Base on Ubuntu LTS / DGX OS hardened to the **CIS Benchmark Level 1 Server**, plus selected Level 2 items ([CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks)), checked with OpenSCAP/`usg` in CI and on the device.
- **Immutable/A-B image** model: read-only root, atomic updates and rollback. This also defends against T1490.
- Minimal packages, no compilers in production, AppArmor/SELinux enforcing, auditd, kernel lockdown, `sysctl` hardening, SSH disabled by default (break-glass only, with FIDO2 keys), unique host keys generated on first boot.
- Time sync to hospital NTP with authentication where possible. Signatures and audit timestamps depend on it.

### 3.4 Container and workload security

- **Rootless** containers (Podman or rootless containerd), user namespaces, **seccomp** default-deny profiles, dropped capabilities, `no-new-privileges`, **read-only root filesystem** with explicit tmpfs/volume mounts. GPU access only for the inference container, via the NVIDIA Container Toolkit with the device restricted.
- **Signed images** with **Sigstore/cosign**. For air-gapped hospitals, use key-based signing with keys in an HSM and an offline-verifiable bundle. An admission policy (policy-controller/Kyverno, or a podman policy.json) rejects unsigned or unattested images ([Sigstore](https://www.sigstore.dev)).
- Build to **SLSA Build L3**: a hardened, isolated build platform, provenance generated by the platform and non-forgeable by build steps ([SLSA v1.1 levels](https://slsa.dev/spec/v1.1/)).
- **SBOM** per image and per appliance release in **CycloneDX** (with ML-BOM for models and datasets) and/or **SPDX** ([CycloneDX](https://cyclonedx.org); [SPDX](https://spdx.dev)). Each component carries a support/EOL date, as the FDA guidance expects. **VEX** (OpenVEX or CSAF 2.0 VEX) records exploitability so hospitals are not swamped by unreachable CVEs ([CSAF 2.0](https://docs.oasis-open.org/csaf/csaf/v2.0/csaf-v2.0.html); [OpenVEX](https://github.com/openvex/spec)).
- Pin Python dependencies by hash (`--require-hashes`) and mirror them in an internal proxy with malware scanning. Ban `pickle` model formats and load **safetensors/GGUF** only.

### 3.5 Network segmentation and egress control

- The appliance sits in a dedicated **hospital VLAN/zone**. Inbound is limited to HTTPS (443) from user subnets for the console and signing page, and to specific integration endpoints. Outbound is default deny, with an allow-list for: the hospital mail gateway/Graph endpoint, Teams/Bot Framework endpoints if used, the update server (or none in offline mode), the SIEM collector, NTP, the backup target and the cloud LLM gateway if enabled.
- **On-box egress proxy**: every outbound call from the agent/tools goes through a single proxy that enforces destination allow-lists, TLS, and DLP/PHI checks. Containers get **no direct internet route**.
- Management plane (BMC, SSH, console admin API) on a separate interface/VLAN.
- Follow [NIST SP 800-207](https://csrc.nist.gov/pubs/sp/800/207/final) zero-trust principles: identity-based access, not network location.

### 3.6 Zero-trust service identity

- **mTLS** between all internal services, with workload identities issued by **SPIFFE/SPIRE** (SVIDs bound to container image digest + node attestation via TPM) ([SPIFFE](https://spiffe.io)). Short-lived certificates (≤24 h) and automatic rotation.
- Each MCP tool server has its own identity and its own authorisation policy (OPA/Cedar). The orchestrator presents **the end-user's delegated identity** plus its own workload identity. Tools authorise on both, which defeats confused-deputy attacks.

### 3.7 Secrets management

- Secrets (DB credentials, Graph app secrets/certificates, cloud API keys, signing keys) live in **HashiCorp Vault/OpenBao** on the appliance, auto-unsealed by TPM, or in systemd-creds/TPM-sealed files for the minimal edition. They never go in images, env files or the repository.
- Prefer **certificate-based** credentials for Microsoft Graph (app certificates in the TPM/PKCS#11) over client secrets. Rotate every 90 days or less. Graph permissions are scoped by **Application Access Policy / RBAC for Applications** to a single dedicated mailbox, not tenant-wide `Mail.Read` **[Unverified: current Exchange Online RBAC-for-apps naming]**.
- The vendor release-signing keys are in an offline HSM and require two-person control.

### 3.8 Identity and access

- **SSO** via the hospital IdP (Entra ID, AD FS, or SAML/OIDC). **Phishing-resistant MFA** (FIDO2/WebAuthn passkeys, smart cards/Taiwan healthcare professional cards **[Unverified: HCA integration options]**) for admins and signers. TOTP is a minimum for general users. This aligns with the [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html) AAL2/AAL3 concepts and the FIDO2 standard ([FIDO Alliance](https://fidoalliance.org/fido2/)).
- RBAC with trial-scoped ABAC: a user only sees trials they are delegated on (delegation log), and the agent inherits that scope.
- **Privileged access management**: no standing admin. Just-in-time elevation with approval and an expiry. Vendor support sessions are hospital-initiated, time-boxed, recorded (screen + command), with MFA and per-person accounts, brokered through the hospital's PAM tool where one exists.
- **Break-glass**: two sealed local accounts (FIDO2 key + PIN, kept in the hospital safe). Every use raises a SIEM alert and forces a credential rotation afterwards. It works when AD/Entra is down.
- Joiner/mover/leaver: SCIM provisioning from the IdP where available, quarterly access reviews exported for the hospital.

### 3.9 Logging, audit and SIEM integration

- Three log classes:
  - **Security events**: authentication, admin actions, policy denials, egress blocks, integrity failures, tool calls.
  - **Clinical audit trail**: who viewed/generated/signed which document, model and prompt-template versions. This is ALCOA+-style for GCP **[Unverified: ICH E6(R3) wording]**.
  - **Operational telemetry**.
- Forward security events to the hospital SOC over **syslog over TLS (RFC 5425)** in **CEF** or JSON (ECS/OCSF). Ship parsers/content packs for common SIEMs. Logs must contain **no PHI payload**: use identifiers and hashes, with prompt content kept only in the on-box encrypted audit store (§4.8).
- The audit store is append-only, **hash-chained**, periodically anchored (signed checkpoint) and exported to WORM storage.
- Shipped detections:
  - impossible-travel/MFA failures;
  - bulk export;
  - agent tool-call anomalies (volume, new recipients);
  - egress denials;
  - integrity-check failures;
  - break-glass use;
  - model hash mismatch.

### 3.10 Backup and recovery (3-2-1-1-0)

- **3** copies, **2** media, **1** off-site, **1** offline/immutable (object lock or WORM tape), **0** errors on verified restore tests. Back up configuration, the DB, the vector index (or rebuild it from sources), site lexicon/exemplars, the audit store and signed-document archives. Encrypt backups with keys held separately from production, and hold backup credentials outside hospital AD.
- Restore test every quarter, and before go-live, with documented RTO/RPO (suggest RTO ≤ 24 h, RPO ≤ 4 h). Taiwan's 36/72-hour recovery deadlines (§1.1) bound these. Models and images are re-deployable from signed release bundles, so they do not need backup beyond the offline bundle cache.

### 3.11 Patch management and offline updates

- Follow [NIST SP 800-40r4](https://csrc.nist.gov/pubs/sp/800/40/r4/final) on preventive maintenance. Ship a monthly security release, with out-of-band releases for **KEV-listed or CVSS ≥9 exploitable** issues within 14 days, or 72 h with active exploitation ([CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog)).
- **Update bundle** = signed manifest (TUF-style roles: root/targets/snapshot/timestamp; [TUF](https://theupdateframework.io)) + OS image delta + container images + models + SBOM + VEX + release notes. Delivered **online** (pull-only from the vendor, appliance-initiated, mTLS) or **offline** (encrypted USB/portal download → hospital staging host → import). Both paths verify the signatures, provenance and rollback-protection version counter. A/B partitioning allows automatic rollback.
- Hospitals get a maintenance-window scheduler and a pre-update compatibility check. Unsupported versions are flagged in the console.

### 3.12 Vulnerability disclosure

- Publish a **coordinated vulnerability disclosure policy** aligned with **ISO/IEC 29147:2018** (disclosure) and **ISO/IEC 30111:2019** (handling) ([29147](https://www.iso.org/standard/72311.html); [30111](https://www.iso.org/standard/69725.html)), with a `security.txt` and a PGP/HTTPS intake. Issue **CSAF 2.0 advisories**. Consider becoming a **CVE Numbering Authority** in year 2. Join the **Taiwan medical H-ISAC** and **Health-ISAC** for threat intel, and notify customers through them.

### 3.13 Penetration testing and red teaming

- An independent annual pentest of the appliance plus a pentest per major release: web console, signing page, APIs, connectors, container escape, network, firmware/boot.
- Use OWASP **ASVS** Level 2 (Level 3 for the signing page and admin console) as the test basis ([OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)).
- **LLM red teaming** each release (§4.9), with automated suites (garak, PyRIT, promptfoo **[Unverified: tool versions]**) plus human red-team exercises against agent goal hijack via email/Teams/attachments.
- Fuzz document parsers (PDF/DOCX/HL7/FHIR inputs) continuously, as the FDA guidance expects.

### 3.14 Incident response

- The IR plan is aligned with **NIST SP 800-61r3** (April 2025), which recasts incident response as a CSF 2.0 community profile across Govern/Identify/Protect/Detect/Respond/Recover ([CSRC](https://csrc.nist.gov/pubs/sp/800/61/r3/final); [NIST news](https://nist.gov/news-events/news/2025/04/nist-revises-sp-800-61-incident-response-recommendations-and-considerations)).
- A joint vendor–hospital RACI and playbooks for:
  1. ransomware in the hospital network;
  2. appliance compromise;
  3. PHI disclosure via the agent (mis-sent email);
  4. prompt-injection campaign;
  5. malicious model/update;
  6. cloud LLM provider incident;
  7. insider misuse.
- Regulatory clocks: Taiwan **1 h** report via the MOHW channel and 36/72 h recovery; Taiwan PDPA notification; Japan PPC preliminary and final reports, plus MHLW/prefecture contact (MHLW asks hospitals to contact it on cyber incidents) **[Unverified: MHLW contact rule specifics]**.
- **Forensic readiness**: a one-click evidence bundle (logs, hashes, running containers, memory capture option) and a **kill switch** that disables all outbound actions (email send, Teams post, cloud calls) while keeping read-only access.

### 3.15 Business continuity and disaster recovery

- TrialBox is not life-critical, but trial operations have regulatory deadlines (SAE reporting timelines). The BCP defines **manual fallback** (templates and checklists exported regularly), degraded mode (no LLM, document storage only), and a hot-spare or cold-spare appliance option for large sites.
- Annual joint tabletop exercise with the hospital, aligned with MOHW's drill programme in Taiwan and the guideline v6.0 BCP expectation in Japan.

**Implications for the spec**
- Make these **non-negotiable product requirements** for v1: Secure Boot + TPM-sealed LUKS, immutable A/B OS, rootless/read-only containers, signed images with provenance, egress proxy with default deny, SSO + FIDO2 for admins and signers, CEF/syslog-TLS forwarding, offline-immutable backup with tested restore, signed offline update bundles, CVD policy, and an IR playbook with a 1-hour hospital-notification path.
- Write **CIS/IEC 62443-4-2/Taiwan 防護基準/MHLW checklist** mappings into the compliance matrix and keep it machine-checkable (OpenSCAP + policy-as-code).
- Remote support must be **hospital-initiated, time-boxed, recorded and MFA-protected**. No standing VPN.

---

## 4. LLM and agent-specific controls

### 4.1 Prompt-injection defences (LLM01 / ASI01)

No single defence is sufficient. The design assumes injection *will* occur and limits what a hijacked agent can do.

- **Architecture first**:
  - *Dual-LLM / quarantined-LLM*: a privileged planner never sees raw untrusted content, and a quarantined model extracts structured fields from it.
  - *Plan-then-execute*: the tool plan is fixed before untrusted content is read.
  - *Capability tokens*: data from untrusted sources is tainted and cannot flow into sensitive sinks (email to new recipients, external URLs) without human approval. This is CaMeL-style information-flow control **[Unverified: specific paper citation]**.
- **Input hygiene**: strip and normalise HTML, hidden text, zero-width characters, white-on-white, alt-text and metadata. Render attachments to text in a sandbox (gVisor/Firecracker, no network). Content-disarm-and-reconstruct (CDR) for Office/PDF.
- **Spotlighting/delimiting** untrusted content with explicit provenance tags, plus a **prompt-injection classifier** (guardrail model, §4.7) on all inbound content and tool outputs.
- **Channel authentication**: email instructions are acted on only if DMARC passes *and* the sender maps to an authorised directory identity with a trial role. Unknown senders get a "cannot process" auto-reply with no content echo.

### 4.2 Tool permissioning and agency limits (LLM06, ASI02/03)

- Tool manifest per deployment: each MCP tool declares its scope (read/write), data classes, rate limits and whether it is **"consequential"** (sends externally, modifies records, signs, deletes). Consequential tools require **human-in-the-loop confirmation** in the console or Teams card, showing the exact payload and recipients.
- **Per-call authorisation** using the end-user's delegated identity (§3.6). No tool runs with super-user credentials. MCP servers accept only tokens whose **audience is that server**, and there is no token passthrough ([MCP best practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices)).
- **Pin and hash MCP tool definitions**. Any change to a tool's description or schema needs re-approval, which defends against rug pulls. Only vendor-signed MCP servers are installed. No dynamic tool discovery from the network.
- Hard limits: max tool calls per task, max recipients, recipients restricted to hospital domain + approved sponsor/CRO domains, attachment classes allowed, and token/time budgets (LLM10).

### 4.3 Output handling (LLM05, LLM09)

- Treat model output as untrusted. Context-encode it in the UI (no raw HTML/Markdown images or links rendered from model output without sanitisation; block auto-loading remote images to stop exfiltration via URL parameters). Validate structured outputs against schemas. Never pass output to shells/SQL without parameterisation.
- **Outbound DLP**: before email/Teams send, scan for PHI patterns (national ID formats, chart numbers, DOB + name), compare against the trial's allowed data classes, and block or route for review.
- **Grounding and citation**: generated regulatory documents cite source passages. Confidence/uncertainty flags appear on the signing page. The signer attests to review, so the AI is not the author of record.

### 4.4 Model integrity (LLM03)

- Every model artefact (base weights, quantised variants, LoRA adapters, tokenizer, prompt templates, guardrail models) is **hashed, signed and listed in the ML-BOM**. Verify at load time against the signed manifest. Use the OpenSSF model-signing approach (Sigstore-based) where publishers support it **[Unverified: OMS v1.0 status]**.
- Load only **safetensors/GGUF**. Scan with model scanners (e.g. ModelScan, picklescan) at intake. Evaluate each new model on a fixed security and quality regression suite before promotion.
- Keep a model provenance register (publisher, licence, country of origin, training-data statement) for CI-hospital procurement (§1.1).

### 4.5 Poisoning of site lexicon and exemplars (LLM04, LLM08, ASI06)

- The site lexicon (local abbreviations, drug names, investigator names) and exemplar library (approved past documents used as few-shot or RAG) are **write-controlled**. Changes go through a two-person review with diff view, and each entry is signed with author and timestamp. Entries learned automatically from emails are **quarantined** until approved.
- Vector store: per-trial namespaces with ACLs enforced at retrieval time (not just in the prompt), provenance metadata on every chunk, periodic integrity re-hash, and injection scanning of chunks at ingestion.
- Anomaly detection on lexicon/exemplar changes (bulk edits, entries containing imperative instructions or URLs).

### 4.6 Membership inference and memorisation in fine-tuned models

- Evidence: clinical-LLM membership-inference studies report "non-trivial yet bounded" leakage ([arXiv 2510.18674](https://arxiv.org/html/2510.18674v1)). Fine-tuning on medical data shows memorisation that grows with LoRA rank ([arXiv 2507.21009](https://arxiv.org/abs/2507.21009v2)). Fragment-specific extraction attacks work against fine-tuned LLMs in medical settings ([ICML 2025](https://icml.cc/virtual/2025/poster/45801)). Earlier work on clinical masked LMs reached a membership-inference AUC of 0.90 (cited in the same search corpus) **[Unverified: original paper]**.
- Controls:
  1. **Prefer RAG over fine-tuning on PHI**. Fine-tune only on de-identified or synthetic text and on style/format, not patient content.
  2. If PHI fine-tuning is unavoidable, use low LoRA rank, deduplication, DP-SGD where feasible, and canary insertion with exposure testing.
  3. Treat a PHI-trained adapter as PHI: site-bound, encrypted, never exported to the vendor or other hospitals, and destroyed at contract end.
  4. Run a pre-deployment **MIA/extraction test** (LiRA-style and prefix-completion) and record it.
  5. No cross-site federated weight sharing without a separate privacy review.

### 4.7 Guardrail models

- Layered guardrails: an input classifier (prompt injection/jailbreak), a PHI detector (NER tuned for zh-TW and ja-JP), an output policy classifier (disallowed content, off-topic, unsupported medical advice) and a tool-call validator. Use local guardrail models (e.g. Llama Guard-class, Prompt Guard-class, NeMo Guardrails rails) **[Unverified: current versions/licences]**. Run them on the appliance so they do not create a new egress path.
- Guardrails are tuned, versioned and regression-tested like any model. Their false-negative rate on the red-team corpus is a tracked release metric.

### 4.8 Logging of prompts containing PHI

- Prompts and completions are **PHI** and are stored only in the encrypted on-box audit store. Retention follows the trial-record retention policy set by the hospital, with access limited to designated auditors and a full access log. Logs forwarded to the SIEM carry hashes, IDs, policy decisions and metadata only.
- Debug logging of prompt content is **off by default**. Turning it on needs admin approval with an expiry and is itself logged. Vendor support sees redacted views by default.
- System-prompt confidentiality (LLM07): system prompts are not treated as secrets. No credentials or access logic go in prompts.

### 4.9 LLM security testing

Use a red-team corpus built from OWASP LLM/Agentic categories and ATLAS techniques, in zh-TW, ja-JP and English, covering:
- injection via email body, quoted reply chains, PDF hidden text, DOCX comments, image text (OCR) and Teams adaptive cards;
- exfiltration via markdown images/links;
- tool-misuse chains;
- lexicon poisoning;
- MIA on adapters.

Pass criteria are agreed per release (e.g. zero successful exfiltration to non-allow-listed recipients; ≥95% blocked or neutralised injections on the known corpus).

**Implications for the spec**
- Specify a **"lethal trifecta" rule**: no single agent run may combine (a) access to PHI, (b) exposure to untrusted content and (c) an external communication tool without a human confirmation step on the outbound action.
- Make the **tool manifest, consequential-action confirmation, recipient allow-lists, PHI-DLP on outbound and pinned MCP definitions** explicit v1 requirements.
- Prefer **RAG over PHI fine-tuning**. Any PHI-trained adapter is site-bound PHI with mandatory MIA testing.
- Site lexicon/exemplar changes go through **reviewed, signed change control**.

---

## 5. Hybrid cloud security

Hybrid is **off by default** and enabled per hospital and per use case by a hospital-signed configuration.

1. **Data classification**: four classes. C0 public/sponsor-public, C1 trial-confidential (protocol, budgets), C2 pseudonymised clinical, C3 identifiable PHI. Policy: C3 never leaves the appliance. C2 leaves only to approved in-country regions under contract. C0/C1 may go to approved cloud LLMs. The classifier runs on the egress proxy, and an uncertain classification fails closed.
2. **De-identification before egress**: deterministic pseudonymisation with on-box re-identification maps, using locale-aware NER for Chinese and Japanese names, IDs, addresses and dates (date shifting) and free-text scrubbing. Re-identification happens only on return, on-box. Measure residual identifiers on a test set; Taiwan and Japan re-identification risk standards differ, and HIPAA Safe Harbor is a reference only.
3. **Private connectivity**: use provider private endpoints (AWS PrivateLink, Azure Private Link, Google Private Service Connect) over the hospital's existing dedicated line or IPsec VPN, not the public internet, with mTLS and certificate pinning at the egress proxy.
4. **Keys**: customer-managed keys (CMK/BYOK, or HYOK where offered) in the cloud KMS/HSM for any stored data (logs, files, vector indexes). Key ownership stays with the hospital or the vendor's in-country tenant per contract.
5. **Zero data retention and abuse monitoring**: Azure OpenAI keeps abuse monitoring on by default, and turning it off needs an approved "modified abuse monitoring" application via Limited Access ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/abuse-monitoring)). Get **contractual ZDR** or modified abuse monitoring from any LLM API provider, plus no training on customer data, and record the approval artefact in the deployment record.
6. **Region pinning**: AWS opened its **Taipei region (ap-east-2)** in mid-2025, with Amazon Bedrock runtime listed as available there ([AWS blog](https://aws.amazon.com/de/blogs/aws/now-open-aws-asia-pacific-taipei-region/); [Bedrock regions](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints-region-availability.html)). Avoid "global" or cross-region inference profiles and Azure Global/Data Zone deployment types where strict residency is required, because they can route prompts across regions ([Microsoft Q&A guidance](https://learn.microsoft.com/en-us/answers/questions/2286499/azure-openai-abuse-monitoring)). Japan: Tokyo/Osaka regions. Taiwan EMR data needs MOHW approval to leave Taiwan (§1.1).
7. **Confidential computing**: for cloud hosting of PHI workloads, prefer confidential VMs (AMD SEV-SNP / Intel TDX) with **confidential GPUs** (NVIDIA H100/Blackwell CC mode) and remote attestation checked by the appliance before any data is released ([NVIDIA confidential computing](https://www.nvidia.com/en-us/data-center/solutions/confidential-computing/)). GB10/DGX Spark is not documented as supporting GPU confidential-computing mode **[Unverified]**. On-prem protection therefore relies on physical and OS controls, not TEE.
8. **Shared-responsibility and certifications**: the provider holds ISO 27001/27017/27018 (and SOC 2). The vendor's cloud tenancy is covered by its own 27001 scope and 27017 controls. The Japanese 3-ministry guideline requires the responsibility split to be documented.
9. **Cloud LLM gateway controls**: per-tenant API keys in Vault, request/response logging (metadata only), cost and rate caps, a model allow-list, and a kill switch. Responses are treated as untrusted (§4.3).

**Implications for the spec**
- Ship hybrid as an **opt-in, policy-driven egress capability** with classification, de-identification, private connectivity, CMK, ZDR evidence and region pinning as **preconditions enforced in code**, not documentation.
- Provide a per-hospital **"data egress register"** in the admin console listing every external destination, the data class and the legal basis. It feeds Taiwan's 委外 audits and Japan's 責任分界表.
- **No C3 PHI to cloud LLMs in v1.** Revisit only with confidential-GPU hosting in-country and hospital/MOHW sign-off.

---

## 6. Component security allocation and release testing plan

### 6.1 Component-by-component allocation

| Component | Key threats | Required controls | Evidence / standard mapping |
|---|---|---|---|
| C1 Hardware/firmware/BMC | Firmware implant, BMC takeover, physical theft | Secure Boot (custom keys), TPM 2.0 measured boot + attestation, signed capsule firmware, BMC on mgmt VLAN, port lockdown | SP 800-193; 62443-4-2 CR 3.4/3.14; DGX Spark CVE tracking |
| C2 Host OS | Kernel exploit, persistence, T1490 | CIS L1(+L2) hardening, immutable A/B root, LUKS2+TPM, AppArmor/SELinux, auditd, unique host keys | CIS Benchmark; 防護基準 SC/SI; MHLW checklist |
| C3 Container runtime | Escape, unsigned image | Rootless, seccomp, read-only FS, cap drop, cosign verify at admission, SLSA L3 provenance | SLSA v1.1; SP 800-190 |
| C4 Inference + weights | Trojaned model, pickle RCE, DoS, MIA | Signed weights + ML-BOM, safetensors only, dm-verity, token budgets, MIA tests for adapters | OWASP LLM03/04/10; ATLAS |
| C5 Agent + MCP tools | Goal hijack, confused deputy, rug pull, excessive agency | Dual-LLM/plan-execute, taint tracking, per-call user-delegated authZ, pinned tool hashes, HITL for consequential tools, budgets | OWASP Agentic ASI01–10; MCP best practices |
| C6 Data stores / RAG / lexicon | PHI disclosure, poisoning, cross-trial leakage | Envelope encryption, per-trial ACL at retrieval, signed lexicon/exemplar change control, provenance on chunks | LLM08; 27701; ISO 27799 |
| C7 Email/Teams connectors | Spoofing, phishing, injection, attachment exploits | DMARC enforcement, identity mapping, dedicated mailbox with scoped Graph RBAC, CDR + sandboxed parsing, outbound DLP + recipient allow-list | ATT&CK T1566; LLM01/05 |
| C8 Admin console | Credential theft, RCE, insider bulk export | SSO + FIDO2, JIT PAM, ASVS L3, CSP/CSRF, export approvals + alerts, break-glass | ASVS; 800-53 AC/IA; 62443 SL3 IAC |
| C9 Signing page | Forgery, repudiation, post-sign tampering | AAL3-style authentication (FIDO2/smart card), signer intent screen, signed hash of exact document + trusted timestamp (RFC 3161), immutable archive | Taiwan Electronic Signatures Act / Japan e-signature law **[Unverified: applicability]**; GCP audit trail |
| C10 Update/model pipeline | Supply-chain compromise | SLSA L3 builds, HSM keys, two-person release, TUF metadata, SBOM+VEX, offline bundle verification, rollback protection | SP 800-218/218A; 81001-5-1; FDA SBOM |
| C11 Cloud LLM gateway | PHI egress, retention, cross-region routing | Classification + de-id, private endpoints, CMK, ZDR evidence, region pinning, kill switch | 27017/27018; §5 |
| C12 Logging/SIEM | Log tampering, PHI in logs | Hash-chained append-only store, PHI-free forwarding, syslog-TLS/CEF, detection content | 800-92; 800-61r3 |
| C13 Backup | Ransomware deletion | 3-2-1-1-0, immutable copy, separate credentials, quarterly restore tests | MHLW guideline v6.0; Taiwan 36/72 h recovery |
| C14 Remote support | VPN exploit, credential reuse (Osaka pattern) | Hospital-initiated, time-boxed, recorded, per-person MFA, no standing tunnel | MHLW checklist; 3-ministry guideline |

### 6.2 Security testing plan by release

| Release | Scope | Security testing and gates |
|---|---|---|
| **R0 – Pilot (internal/single friendly site, synthetic data only)** | Core appliance, local LLM, console | Threat model v1; SAST (Semgrep/CodeQL), SCA + SBOM, secret scanning, container scanning (Trivy/Grype); CIS scan; baseline LLM red-team (OWASP LLM01/02/05/06); no PHI until R1 gates pass |
| **R1 – Taiwan GA (on-prem, email channel, signing page)** | Production PHI | Independent pentest (ASVS L2, L3 for console/signing); firmware/boot review incl. Secure Boot + TPM sealing; supply-chain gate (signed images, SLSA L3 provenance, VEX); LLM red-team incl. email/attachment injection in zh-TW; MIA test if any adapter; backup restore drill; IR tabletop with hospital including the 1 h report path; MDS2 + Taiwan 防護基準 mapping; ISO 27001 vendor certification |
| **R2 – Teams channel + admin delegation + offline update** | New ingress and update path | Threat-model delta; Teams/Bot Framework auth tests; Graph permission-scope review; offline-update tamper/rollback tests; MCP rug-pull and confused-deputy tests; fuzzing of parsers (continuous) |
| **R3 – Japan launch** | ja-JP, Japanese hospitals | Map to MHLW guideline v6.0 + current checklist; Japanese MDS/SDS and 責任分界表; ja-JP red-team corpus; remote-maintenance assessment; APPI breach-process drill; check whether the hospital is designated under the core-infrastructure regime (pre-notification) |
| **R4 – Hybrid cloud (opt-in)** | Cloud LLM gateway, cloud hosting option | Cloud config review (CIS cloud benchmarks), private-endpoint verification, de-identification residual-risk test, egress classifier evaluation, ZDR/region evidence audit, 27017/27018 alignment; confidential-computing attestation tests if PHI hosting is offered |
| **Every release** | All | Regression of the security test suite; LLM red-team regression (pass thresholds); SBOM/VEX publish; CSAF advisories for fixed vulns; release sign-off by security lead (two-person) |
| **Annually** | All | Full external pentest + human red-team (incl. physical/remote-support paths); ISO 27001 surveillance; DR test; HITRUST AI / ISO 42001 readiness when demanded |

**Implications for the spec**
- Adopt the §6.1 table as the **security requirements traceability matrix**. Each row becomes testable requirements with IDs, linked to the threat model and to evidence artefacts.
- Release gates in §6.2 are **blocking**. A release cannot ship PHI-handling features without passing pentest, supply-chain and LLM red-team gates and producing the SBOM/VEX/MDS2 package.

---

## Appendix A. Items marked [Unverified] to confirm before contract/regulatory use

1. Whether every article of the amended Taiwan Cyber Security Management Act took effect on 1 Dec 2025, and the current CI hospital count and levels.
2. The final PDPA breach-notification deadline under the 2025 amendment and its effective date.
3. Whether MODA product restrictions extend to particular open-weight model families for CI hospitals.
4. The Japanese Economic Security Promotion Act amendment adding hospitals to core infrastructure: enactment and designation criteria.
5. The current MHLW checklist version (FY2026) and the JAHIS/JIRA MDS/SDS version.
6. APPI reporting deadlines as currently worded by PPC.
7. The FDA February 2026 guidance version as the current one.
8. ISO/IEC 27701 2025 edition status; the IEC 81001-5-1 webstore URL.
9. DGX Spark/GB10 TPM, Secure Boot custom-key and confidential-computing support; CVE-2026-24218 details.
10. MITRE ATLAS technique IDs, the EchoLeak CVE number, OpenSSF model-signing v1.0 status, guardrail model versions.

*Note: the session's web-search budget ran out before these items could be checked further. They are listed so a follow-up research pass can close them.*
