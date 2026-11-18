# Security and certification in depth; an interface customisable on desktop and phone (lane J, root review 16, 2026-11-18)

*Branch `agent/B17-root-security-custom`, from master `7da6edd3`. Reader: the owner first, then lanes C2, D, J and the
integrator. An engineer's reading, not legal advice and not an auditor's opinion. Nothing here was attacked; the only
checks run were the repository's own read-only scans.*

**Marks.** [R `file:line`] read in this repository; [M n] measured, the command in the measurement log (section 13);
[S link, opened 2026-11-18] a source opened for this review; [S2 link] a secondary source (a vendor or consultancy
page) used only for costs or dates and named as such; [O] opinion; **not verified** where a source could not be opened.

**Read first and not repeated:** review 01 sections 7 and 8 (identifier guard, regulation tables); the full review's
areas J and K (`docs/reviews/2026-11-17-full-review.md:185-425`, ASVS by chapter, Part 11 table, GAMP 5 deliverables,
the validation pack); the ASVS Level 2 checklist of V2 to V4 (`docs/plan/measurements/asvs-l2-checklist-2026-11-17.md`,
findings V3-01 to V3-19); review 07 (validation), review 09 (design system DS-1 to DS-20), review 10 (architecture,
AQ cards); plan 9 revision 2 (bands 9h to 9m, its card 9i-20 "ASVS V5 to V14 and the pen-test scope"). Their ids are
cited, not restated.

**Lane boundary.** Sign-in, accounts, roles, the permission matrix, audit and break-glass are lane C2's. This document
reviews and proposes there; it never says what a role may do. Every card that touches those is marked "C2 decides".

---

## Summary for the owner (one page, plain words)

**Part I. Is TrialBox secure enough, and can it be certified?** The product's own engineering is better than most
first products a hospital meets: updates are signed and refuse old or expired bundles [R `tools/verify_update.py:243-283`],
the box sends nothing out by default, patient identifiers are replaced at the door, the audit trail is a hash chain
with one writer, and the repository's secret and code scans pass with every exception reviewed [M 1, M 2]. What it
lacks is mostly **paper and proof owned by the company, not code**:

1. **A Japanese hospital's IT department will ask for about fourteen documents before it signs.** Five exist in some
   form, six exist only in English or in part, and three do not exist at all: the **サービス仕様適合開示書** (the
   conformance sheet the MIC/METI provider guideline asks every vendor to hand over), the **MDS/SDS** security
   disclosure, and a **責任分界表** (who is responsible for what) (section 4). The provider guideline applies to
   TrialBox: its FAQ says an on-premises system is in scope as soon as there is a maintenance or remote-support
   contract [S soumu FAQ draft, section 1.3], and TrialBox has both (RUNBOOK 21).
2. **No certificate is legally required of the company for the first Japanese site**, but ISMS (ISO/IEC 27001) or
   プライバシーマーク is *expected* in procurement, and Taiwan's EMR regulation **requires** a recognised security
   certification of any vendor that builds or manages the hospital's record system (Art. 6) [S law.moj.gov.tw]. An
   ISO 27001 statement of applicability already exists in the repository (93 controls) [R `docs/validation/soa.csv`];
   the company's ISMS does not.
3. **The security of the code has five holes worth closing before real patients**, none dramatic: only 1 of 15
   containers drops privileges [M 3]; the audit head is signed once a night, so a day of events can be rewritten by
   whoever holds root [R `deploy/install.sh:810`]; database and key passwords live in an environment file (V3-13);
   the vendor's signing key is a file on a laptop, not in a hardware token [R `tools/make_bundle.sh:6`]; and no outside
   penetration test has been done. Two security documents are out of date and now *under*-state the product
   (section 5.6).
4. **Prompt injection through a chart note is contained, not solved.** A note cannot run code, call the network or
   draw an image that leaks data (the content policy forbids outside images, [R `services/console/app.py:111`]), but
   it can still try to bend a model's answer; the defence is the two-model agreement rule and the injection suite,
   which has never run on the real model pair (full review J-5).

**Part II. Can the interface be made "fully customisable"?** Today almost nothing is: a person can choose the language
and the role to act in, and an administrator can flip a phone-first layout for the whole box [R
`services/console/auth.py:83-101`, `libs/tb_common/flags.py:112-121`]. There is no saved view, no choice of columns,
no per-site wording, no per-study list design. **The right design is not "anything goes" but "configuration as
data"**: each list, card, home page and phone bar is a small versioned definition with a default per role; a site
or a person may change what is shown, in what order and how dense, but never what is recorded, who may do it,
consent, safety clocks or validated wording. Every change is audited and exportable, and the site's validation
record names the definitions in force (section 10).

**The five changes that matter most:** (1) the three missing Japanese vendor documents and a ja copy of the patch,
recovery and support pages (company work, about 10 days); (2) container hardening on all 15 services and hourly
signed audit heads (S each); (3) the vendor key into a hardware token, with SLSA provenance and a signed SBOM/VEX in
the bundle (M); (4) a scoped outside penetration test before the first real patient (¥1.5–4 M [O]); (5) the
view-definition model, built on review 09's design system, starting with per-user density, columns and saved views on
the three work lists (M then L).

**What it costs.** The code cards here are about 6 S, 11 M and 4 L. The company items are money: ISMS certification
in Japan roughly ¥0.5–1.5 M a year for the audit plus 6–12 months of effort [S2], プライバシーマーク about ¥0.34 M
for a small company [S2], an outside penetration test ¥1.5–4 M [O], SOC 2 Type II or HITRUST only if a US customer
asks (US$20 k–200 k) [S2].

---

# Part I. Security and certification

## 1. Every certification, registration and conformity claim that may be asked

**Applies to:** P = the on-premises product; V = the vendor organisation (Aimedics); H = the hospital's own use.
**Status:** M = mandatory by law or regulation for this case; E = expected in procurement or by a sponsor; O =
optional, or only if the product becomes something else. "TrialBox today" is what the repository shows.
Costs come from public pages, often secondary; treat them as orders of magnitude [O].

### 1.1 Japan (first site)

| # | Claim | Issuer | Applies to | Status | Evidence a buyer asks for | Cost, duration | TrialBox today | Gap card |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| J1 | 医療情報システムの安全管理に関するガイドライン **第7.0版** (概説, 経営管理, 企画管理, システム運用 June 2026; 企画管理 May 2026; Q&A Sept 2026) [S https://www.mhlw.go.jp/stf/shingi/0000516275_00006.html] | MHLW | H (the hospital's duty), P through the vendor's disclosure | M for H | the vendor's 開示書 mapping each control; two factors (by FY2027) | none to the vendor; mapping work ~5 days [O] | mapped control by control in `docs/plan/design/03-security-privacy.md` (SC-13 to SC-90) [R]; written against v6.0 and "v7.0 (2026)" by repository text [R `docs/security/07-laws-a-site-must-check.md:16`]; not re-mapped to the June 2026 text | 16-1 |
| J2 | 医療情報を取り扱う情報システム・サービスの提供事業者における安全管理ガイドライン **第2.0版** (MIC/METI, 2025-03-28), with 別紙1: サービス仕様適合開示書 example and SLA参考例, and an FAQ [S https://www.soumu.go.jp/menu_news/s-news/01ryutsu06_02000427.html] | MIC, METI | V | M for V once a maintenance or remote-maintenance contract exists | サービス仕様適合開示書; SLA; risk assessment shared with the hospital; 責任分界 | ~5–10 days of company work [O] | **none**: no 開示書, no SLA in that form, no 責任分界表 (grep of `docs/` finds the words only in `docs/research/2026-10_cybersecurity.md:72-79`) [M 9] | 16-2, 16-3 |
| J2a | Scope of J2 for an on-premises box | FAQ (案, 令和6年) | – | – | – | – | The FAQ: a system installed inside the hospital is in scope "if there is a contract" for operation, management or maintenance; a sale with no maintenance is out; remote maintenance written into service terms counts as a maintenance contract; a vendor that only supplies security patches as product warranty is out [S https://www.soumu.go.jp/main_content/000970147.pdf, FAQ 1, 1.1, 1.3; the final FAQ `04faq_20250328.pdf` returned 403: **not verified** against the final] | TrialBox's support model has a supervised remote session (RUNBOOK 21) [R], so **in scope** [O] | 16-2 |
| J3 | 医療機関等におけるサイバーセキュリティ対策チェックリスト (令和7年度版 merged into one form for 医療機関・薬局 in the 第7.0版 set, June 2026) [S MHLW page above; S2 https://www.mhlw.go.jp/content/10808000/001450189.pdf, not opened] | MHLW | H, with a 事業者 column | M for H (used in 医療法 立入検査 since April 2023) [S2 search summary of MHLW material] | the vendor's answers for its system: accounts, admin rights, 2FA, USB control, logs, backup offline | – | partly answerable from the IT pack [R `docs/plan/sites/it-security-pack.md:126-166`]; no filled 事業者 answer sheet | 16-4 |
| J4 | ISMS: ISO/IEC 27001:2022 (+ 27017 cloud, 27018 PII in cloud, 27701 privacy) | accredited CBs under ISMS-AC | V | E (procurement); 27017/27018 not applicable to an on-prem box [O] | certificate and scope | audit 数十万円〜100万円超 per year, 6–12 months to first certificate [S2 https://www.elecom.co.jp/biz/solution/column/00285/] | a Statement of Applicability for the product and vendor, 93 controls, with "applies: product; vendor; hospital" [R `docs/validation/soa.csv:1-94`]; the vendor ISMS "is a company record outside the repository" [R `soa.csv:2`]; no security officer named (REG-031) [R `soa.csv:3`] | 16-5 |
| J5 | プライバシーマーク (JIS Q 15001) | JIPDEC and designated bodies | V | E (common in Japanese procurement where personal data is handled) | registration; PMS documents | small company ¥336,600 incl. tax new, after the October 2026 fee revision [S2 search summary; JIPDEC fee page returned 404: **not verified**]; ~6–12 months [O] | none | 16-5 |
| J6 | ISMAP | ISMAP steering committee | cloud services for central government | **does not apply**: ISMAP registers cloud services procured by government bodies [S2 https://www.oracle.com/jp/cloud/compliance/ismap/; the ISMAP portal did not render: **not verified**]; an on-prem box in a private hospital is outside it [O] | – | – | – | none |
| J7 | ER/ES指針 (医薬品等の承認又は許可等に係る申請等における電磁的記録及び電子署名の利用について, 2005) | MHLW/PMDA | P when its records are 治験 records | M if the box's records become trial records | assessment against the guideline | ~3 days to write [O] | "NO EVIDENCE FOUND of an assessment" (full review K) [R `docs/reviews/2026-11-17-full-review.md:318-320`] | 16-6 |
| J8 | コンピュータ化システム適正管理ガイドライン (CSV, 2010) and GAMP 5 second edition (2022) | MHLW; ISPE | P (supplier evidence), H/sponsor (validation) | E for GxP use | IQ/OQ records, supplier assessment, category per component | GAMP 5 book ~US$500 [O] | VMP and GAMP deliverables listed, nothing executed (full review K-1; review 07) [R] | as 9i-14, 9i-15 |
| J9 | SaMD 該当性 (プログラム医療機器) | MHLW/PMDA | P | O while not a device | intended-use statement and reasoning | consultation fees vary [O] | intended use and standards position [R `docs/validation/standards-position.md:1-60`]; **review 11 holds this question** | review 11 |
| J10 | JIS X 8341-3:2016 (WCAG 2.0 equivalent) | JSA | P | E for public hospitals; O for private [O] | 試験結果表示 (a conformance statement) | self-test ~5 days [O] | contrast and target work in review 09 (A11Y-1 to A11Y-7) [R 09 §1.3-1.4]; no conformance statement | 16-7 |
| J11 | Vulnerability handling: 情報セキュリティ早期警戒パートナーシップ (IPA receives, JPCERT/CC coordinates, published on JVN) | IPA, JPCERT/CC | V | E: a vendor contact for 脆弱性届出 | a published security contact and disclosure policy | none | patch policy with 14-day critical SLA [R `docs/runbook/24-patch-policy.md:20-25`]; **no public security contact, no `SECURITY` disclosure policy, no CSAF advisories** [M 9] | 16-8 |
| J12 | SBOM guidance: ソフトウェア管理に向けたSBOMの導入に関する手引 ver2.0 (METI, 2024, with SBOM 取引モデル for contracts) [S2 https://www.meti.go.jp/policy/netsecurity/wg1/SBOMv2.pdf, not opened] | METI | V | E | an SBOM per release, its format, who receives it | none | CycloneDX SBOMs per image and per lock ride in the signed bundle [R `tools/make_bundle.sh:14-18`]; no VEX | 16-9 |
| J13 | APPI (要配慮個人情報), 生命・医学系指針, 次世代医療基盤法 | PPC, MHLW | H; V as 委託先 | M | 委託契約 safety measures | – | mapping and privacy pack [R `docs/plan/sites/privacy/appi-pdpa-mapping.md`] | – (full review J) |
| J14 | J-GCP and ICH E6(R3) computerised systems (see I1) | MHLW/PMDA | sponsor, H | M when in a 治験 | – | – | full review K | – |

### 1.2 Taiwan

| # | Claim | Issuer | Applies to | Status | Evidence | Cost, duration | TrialBox today | Gap card |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | 醫療機構電子病歷製作及管理辦法 (last amended 2022-07-18) [S https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020121] | MOHW | H; V if the vendor "builds or manages" the EMR system (Art. 6) | M | Art. 6(3): the vendor passes an information-security certification recognised by the central authority; Art. 7: contract terms incl. no subcontracting without approval and immediate notice of anomalies; Art. 13: complete access records; Art. 5(2): incident to the local authority within 72 h; Art. 8: cloud data stored in Taiwan | ISO 27001 as for J4 | TrialBox reads copies and never writes back [R `docs/data/01-what-the-box-reads.md`]; whether a copy-holding screening box counts as part of the EMR system is a legal question [O]; no vendor certification | 16-5, 16-10 |
| T2 | 個人資料保護法 (PDPA) and its 2025 amendment (PDPC) | MOJ / PDPC | H; V as 受託者 | M | breach notice, purpose | – | full review J privacy table | – |
| T3 | 資通安全管理法, amended and promulgated 2025-09-24, in force 2025-12-01 [S2 search summary of president.gov.tw and moda.gov.tw] | MODA (資安署) | H if designated critical infrastructure (medical centres); V as 受託者 | M for designated H; flows down to V by contract | 受託者 with a complete security management mechanism **or third-party certification**; written contract [S2 same] | as J4 | supplier statement idea in review 01 §8.1 [R]; none | 16-5, 16-10 |
| T4 | TFDA 電腦化系統與電子數據應用於藥品臨床試驗指引 (draft announced 2023-05-16; a 2024-05 version circulates; final status **not verified**) [S2 https://www.fda.gov.tw/tc/newsContent.aspx?cid=5072&id=28815]; TFDA 2026 draft revision of the GCP guideline to E6(R3) Annex 1 [S2 search summary] | TFDA | sponsor, H, P (supplier evidence) | M when a trial record | validation, audit trail, access | – | D-859's reading [R `docs/validation/edc-data-flow.md`]; no assessment against the final text | 16-6 |
| T5 | CNS 27001 (= ISO/IEC 27001) | BSMI accredited CBs | V | E; M via T1/T3 | certificate | as J4 | as J4 | 16-5 |
| T6 | 電子簽章法 | MODA | P when signatures are trial records | M then | assessment | – | none (full review K) | 16-6 |

### 1.3 United States

| # | Claim | Issuer | Applies to | Status | Evidence | Cost, duration | TrialBox today | Gap card |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| U1 | HIPAA Security Rule (45 CFR 164 Subpart C); the NPRM of 2025-01-06 is **not final**; HHS moved final action to July 2027 [S2 https://www.fiercehealthcare.com/health-tech/feds-push-back-hipaa-security-rule-overhaul-july-2027] | HHS OCR | H (covered entity); V as business associate (BAA) | M with a BAA | BAA, risk analysis, safeguards; the NPRM would add asset inventory, MFA, encryption, 72 h restore | – | not mapped; no BAA template; no US breach clocks in the incident plan [R `docs/plan/sites/incident-response.md:53-65`] | 16-11 |
| U2 | 21 CFR Part 11 | FDA | P when its records are submitted | M then | assessment, validation | – | full review K table | as there |
| U3 | FDA guidance *Electronic Systems, Electronic Records, and Electronic Signatures in Clinical Investigations: Q&A* (October 2024, final; supersedes the 2007 computerised systems guidance) [S2 https://www.govinfo.gov/content/pkg/FR-2024-10-02/html/2024-22562.htm] | FDA | sponsor, investigator; P via supplier evidence | E for any US trial | risk-based validation, audit trail, the sponsor's oversight of the vendor | – | not assessed | 16-6 |
| U4 | FDA *Computer Software Assurance for Production and Quality System Software* (final 2025-09-24) [S2 https://www.federalregister.gov/api/v1/documents/2025-18468.json] | FDA | device makers' QS software | O: TrialBox is not production or QS software [O]; its risk-based method is worth adopting for the IQ/OQ pack | – | – | – | learn (07) |
| U5 | SOC 2 Type II (AICPA TSC) | CPA firms | V | E for a US SaaS; rarely for on-prem [O] | report over a 6–12 month window | auditor ~US$20–50 k, first year all-in US$25 k–200 k [S2 https://blog.getagency.com/articles/soc-2-audit-cost] | none | wait |
| U6 | HITRUST e1 / i1 / r2 | HITRUST | V | E by some US health systems | assessment | e1 ~US$20–70 k, i1 ~US$60–200 k, r2 ~US$150 k+ [S2 https://www.accountablehq.com/post/hitrust-certification-cost-in-2026-price-ranges-key-factors-and-how-to-budget] | none | wait |
| U7 | NIST SP 800-53 r5, SP 800-66 r2 (HIPAA implementation, 2024), SP 800-218 SSDF | NIST | V (SSDF attestation for federal buyers), H | O; SSDF E for federal | self-attestation | – | many SSDF practices exist (pinned actions, hashed locks, scans) [R `.github/workflows/trialbox-supply-chain.yml:2-5`]; no SSDF mapping | 16-12 |
| U8 | FDA SaMD / CDS criteria (CDS guidance revised 2026-01-06) [S2 https://www.cooley.com/news/insight/2026/2026-01-20-automation-bias-and-clinical-practice-fda-makes-incremental-updates-to-clinical-decision-support-software-guidance] | FDA | P | O while not a device | – | – | review 11 | review 11 |
| U9 | Section 508 / WCAG 2.x AA | US Access Board | P for federal buyers; E elsewhere | E | VPAT / ACR | ~5 days [O] | as J10 | 16-7 |

### 1.4 International

| # | Claim | Issuer | Applies to | Status | Evidence | TrialBox today | Gap card |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I1 | ICH E6(R3), principles and Annex 1, computerised systems (final January 2025) [S2 Taiwan TFDA notice summary citing ICH 2025-01] | ICH | sponsor, investigator; P as a computerised system | M in trials | risk-proportionate validation, audit trail review, access, vendor oversight | full review K E6 table [R] | as there |
| I2 | IEC 62304, IEC 82304-1, ISO 13485 | IEC, ISO | P | O (trigger written) | – | position page with triggers [R `docs/validation/standards-position.md:50-60`] | none now |
| I3 | ISO 14155 | ISO | device investigations | O: only if TrialBox supports a device trial's records [O] | – | none | wait |
| I4 | IEC 81001-5-1:2021 (security in the health-software life cycle) | IEC | P, V | E: recognised by FDA and referenced in Japan's device cyber requirements [O, not opened] | process evidence | 08-supply-chain and the patch policy cover parts [R `docs/security/08-supply-chain.md`]; no mapping | 16-12 |
| I5 | OWASP ASVS | OWASP | P | E for a pen-test scope | L2 self-assessment | V2-V4 done; this review samples V10-V13 (section 3); ASVS 5.0.0 (May 2025, 17 chapters, renumbered) [S https://github.com/OWASP/ASVS/tree/master/5.0/en] is current; the repository uses 4.0.3 | 16-13 |
| I6 | CIS Benchmarks (Ubuntu, Docker) | CIS | P (host, containers) | E | a scan result | `deploy/check_host.sh` and `deploy/hardening/apply.sh` [R]; no CIS-mapped scan | 16-14 |
| I7 | SLSA v1.x provenance; Sigstore (cosign) signatures | OpenSSF | P (bundle, images) | E by sponsors' supplier audits [O] | provenance attestation per artefact | Ed25519 file signature over the manifest [R `tools/verify_update.py:243`]; no provenance attestation; no image signatures | 16-15 |
| I8 | CycloneDX / SPDX SBOM | OWASP / Linux Foundation | P | E | SBOM per release | CycloneDX from Syft [R `.github/workflows/trialbox-images.yml:4-5`] | – |
| I9 | VEX (CSAF 2.0 VEX or OpenVEX) | OASIS / OpenSSF | P | E | VEX with each release | none; reviewed findings live in `deploy/supply-chain-allowlist.yaml` (94 waivers, J-1) [R] | 16-9 |
| I10 | ISO/IEC 42001 (AI management) | ISO | V | O [O] | – | `docs/validation/ai-governance.md` [R] | wait |

**[O] Reading of the table.** Of 39 rows, the ones mandatory for the first Japanese site are J1 (the hospital's), J2
(the vendor's, because of remote support), J3 (the hospital's, with vendor answers), J13. Expected in procurement:
J4 or J5, J10, J11, J12. Everything US waits for a US site; nothing in section 1.4 is mandatory today.

---

## 2. Security in depth: the threat model for a hospital deployment

No threat model is on file (ASVS 1.1.2, V3-16) [R `docs/plan/measurements/asvs-l2-checklist-2026-11-17.md:262`].
This section is a first one, written from the code; card 16-16 turns it into a maintained file.

### 2.1 Assets, actors and paths

| Threat (actor, path) | Asset | What stops it today | Gap | Severity [O] |
| --- | --- | --- | --- | --- |
| Insider with a clinical account bulk-reads patients | pseudonymised lake, candidate lists | role matrix; small-cell rule; reveal rate-limited and audited [R `services/console/auth.py:352`]; audit search audited | no alert on unusual volume (ASVS 11.1.7; section 3) | Medium |
| Insider with host root | everything | LUKS; KEK sealed; one audit writer | root can rewrite up to a day of audit before the nightly signed head [R `deploy/install.sh:810`]; the signing key is on the same box | High (J-M2 still open) |
| Stolen GPU workstation (desk-side 5090 or 6000 Pro) | disks | `luks_policy.py` FAILs a TPM-only unlock, PASSes Tang or TPM+PIN [R `deploy/hardening/luks_policy.py:1-15`] | `check_host` reports; nothing stops an installer from choosing TPM-only on a VALIDATION box [O] | Medium |
| Stolen backup medium | backups | encrypted to a key the box does not hold [R `docs/security/04-secrets.md:8`] | restore never measured on hardware [R `docs/runbook/22-disaster-recovery-with-measured-rpo-and-rto.md:22-25`] | Medium |
| Malicious update | the whole box | Ed25519 signature checked before parsing; key id, not_after, release_seq above installed, member sha256 [R `tools/verify_update.py:186-310`] | the signing key is a file passed as `--key` [R `tools/make_bundle.sh:6,64`]; one person can sign; no provenance | High |
| Supply chain (a poisoned package or image) | build | hashed locks, pinned actions, offline Trivy, pip-audit, Syft [R `.github/workflows/trialbox-supply-chain.yml:2-5`; `trialbox-images.yml:4-5`] | 94 waivers with no owner (J-1); no image signature; no reproducible-build check | Medium |
| Hostile document (protocol PDF, consent form, uploaded chart) | parser, model | parser isolated; type by extension and `%PDF` sniff [R `services/doc_parser/parser.py:97`; `services/console/app.py:97-98`]; 50 MB cap | no antivirus scan (ASVS 12.4.2); ruleset zip has no size or count cap [R `services/criteria_compiler/import_ruleset.py:29-41`] | Low-Medium |
| Prompt injection in chart text into the model | screening verdict | fenced data blocks; hidden text flagged; two different models must agree on a verified quote to exclude [R `docs/security/05-data-protection.md:12-17`] | suite never run on the real pair (J-5); protocol-text attacks thin (9i-17) | Medium |
| Model output as an injection into the console | browser | Jinja autoescape; CSP `default-src 'self'; img-src 'self' data:`; script by hash only [R `services/console/app.py:111`]; no `urlize` filter (grep) [M 9] | none found: a model cannot make the page fetch an outside image or run script [O] | Low |
| Model output into exports and spreadsheets | sponsor's PC | xlsx exports neutralise formulas [R `services/datacore/export.py:141`]; audit CSV prefixes `= + - @` [R `services/console/audit_page.py:295-303`] | the REDCap import CSV writes values raw [R `services/datacore/export.py:106-112`]: right for REDCap, a formula risk if opened in Excel | Low |
| Exfiltration through the model | patient data | model networks `internal: true` [R `deploy/docker-compose.yml:493-499`]; `VLLM_NO_USAGE_STATS=1`, `HF_HUB_OFFLINE=1` in all GPU overlays [R `deploy/docker-compose.rtx5090.yml:55-56`] | DNS open (J-M7) | Medium |
| Exfiltration through logs, traces, support bundles | identifiers | scrubber on in every service; support bundle fixed; traces 7 days | identifiers in audit free text (V3-14, High); the audit is never erased | High (C2) |
| Telemetry | – | install.sh "no registry, no download, no telemetry" [R `deploy/install.sh:58`]; embed image disables HF telemetry [R `deploy/docker/embed.Dockerfile:29`] | no test proves no outbound packet in a full night (the egress test needs root, full review J) | Low |
| Remote support session | admin access | supervised session (RUNBOOK 21) | 2省GL counts it as maintenance; its log must be handed to the hospital [O] | Medium |

### 2.2 Secrets and key custody

| Item | Today | Gap |
| --- | --- | --- |
| Lake, PostgreSQL at rest | full-disk LUKS (no database-level encryption) [R `deploy/hardening/luks_policy.py`] | acceptable for one box [O]; the hospital's checklist asks "暗号化": answer "LUKS2, AES-XTS" in the 開示書 |
| Site keys (pseudonym HMAC, pid map) | wrapped under a KEK (TPM, Shamir or passphrase) [R `docs/security/04-secrets.md:12-20`] | good; rotation of the HMAC key changes every pseudonym (by design) |
| Database, mail, KEK passphrase | environment file (V3-13) | secret files, as the model key already is (C2/D) |
| Audit signing key | on the box's secrets volume [R `tools/trialbox/audit_heads.py:1-20`] | the off-box anchor must be write-once to someone other than box root, or the key must live off the box [O] |
| Vendor update key | a file key; a `.next` key supported for rotation [R `tools/apply_update.sh:71-72`] | hardware token (YubiKey/HSM), two-person release; the escrow in `docs/security/10-key-ceremony-and-escrow.md` covers site keys, not the vendor's |
| Backups | public key on box, private on a stick with hospital IT [R `docs/security/04-secrets.md:9`] | a measured restore with the key holder present |

### 2.3 TLS, containers, host, least privilege

- **TLS.** TLS 1.2/1.3 at Caddy; inside the box plain HTTP on internal networks, a recorded rationale [R
  `docs/security/02-network.md:41`]. Acceptable on one host [O]; the two-device form (`docs/runbook/08-two-device.md`)
  crosses a physical cable and needs mTLS or WireGuard there (not verified whether it has it).
- **Containers.** 15 services in the base compose; 1 drops all capabilities, runs read-only with
  `no-new-privileges` and a fixed user (model-guard) [M 3; R `deploy/docker-compose.yml:466-470`]. The three
  Python/JVM/embed images do set a non-root `USER tb` [M 4]. Every service has memory limits [M 3]. **16-17**: the
  same four lines on every service, with `tmpfs` for the few that write.
- **Least privilege between services.** Per-service tokens; an unlisted callee accepts any token (V3-15, latent);
  console and orchestrator both own 17 schemas (review 01 §7.2) [R]. Both are in plan 9 rev 2 (9g-11, AQ-19).
- **Host.** `check_host.sh` and `apply.sh` exist; no CIS benchmark mapping (I6).

### 2.4 The update channel and offline bundle, read in full

`tools/apply_update.sh` refuses during an unfinished update [R `:75-80`], checks site keys first [R `:81-85`],
verifies with `tools/verify_update.py` before staging anything [R `:108-121`], and keeps a backup and rollback point.
The verifier checks the signature over the manifest bytes before parsing [R `tools/verify_update.py:243`], that
`key_id` names the signer [R `:257-258`], expiry [R `:260-264`], `release_seq` above the installed one unless an
audited `--allow-downgrade REASON` [R `:268-283`], and every member's sha256 [R `:289-294`]. This answers ASVS 10.3.1
and closes review F-15. **Two residues:** `--no-backup` exists on the production path [R `tools/apply_update.sh:65`]
(it should be refused in PRODUCTION or need a reason, as downgrade does); `TB_VENDOR_PUBKEY` lets the caller name the
key file [R `:71`] (root only, so Low). **Stale document:** `docs/security/06-audit-retention-updates.md:22` still
says "Not done: anti-rollback, key id and expiry"; all three are done. A hospital reading it will under-rate the
product (16-18).

### 2.5 Logging, audit tamper evidence, backup and continuity

- Logs carry pseudonyms; the scrubber covers JP and TW IDs [R `docs/security/05-data-protection.md:3-8`]; the
  identifier guard misses full-width IDs and SSNs (B1-P1).
- The audit chain verifies and detects a rewrite [R `docs/plan/measurements/asvs-l2-checklist-2026-11-17.md:302`];
  heads are signed at 00:20 each night [R `deploy/install.sh:810`]. **16-19**: hourly, and the anchor folder on a
  share the box's root cannot overwrite (WORM or the hospital's).
- RPO 24 h (5 min with WAL), RTO 4 h (software), 5 working days (hardware): **all "not measured yet"** [R
  `docs/runbook/22-disaster-recovery-with-measured-rpo-and-rto.md:22-25`]. CI runs a backup-and-restore drill on
  demand [R `.github/workflows/trialbox-e2e.yml:86-91`]; no record on the box hardware. A Japanese hospital's BCP
  checklist asks for exactly these numbers (J3).

### 2.6 Vulnerability management as configured in CI

| Gate | Where | Schedule | Measured here |
| --- | --- | --- | --- |
| Secret scan (detect-secrets) | `trialbox-ci.yml:702-703` | every full tier | 6 findings, all reviewed, PASS [M 1] |
| Static scan (bandit, medium+) | `trialbox-ci.yml:704-705` | every full tier | 89 findings in 12 rules, all reviewed, PASS [M 2] |
| pip-audit on the hashed lock | `trialbox-supply-chain.yml:68-69` | on change and weekly (Mon 03:17) | not run (network) |
| Trivy (offline DB), Syft SBOM, licence gate | `trialbox-images.yml:127-162` | on change and weekly (Mon 04:41) | not run |
| Container config scan (hadolint) | Makefile "images (if hadolint is installed)" | optional | – |
| CodeQL / Semgrep, OSV for npm, dynamic scan (ZAP) | – | **none** | – |

[O] The gates are strong for a team this size. Missing: a dynamic scan of the running console (a ZAP baseline against
the demo stack in the nightly is cheap), and a time-bound owner for waivers (J-1). The 14-day critical SLA [R
`docs/runbook/24-patch-policy.md:20-25`] is in English only.

### 2.7 Penetration test scope for the first site (proposed; one page for the tester)

1. **In scope:** the console through Caddy (authenticated as each of the seven roles, with test accounts), the sign-in
   and second factor, break-glass, the EDC sign and send, uploads (protocol, consent, charts, data dictionary, ruleset
   zip), exports, `/healthz`, `/metrics`; the update path with crafted bundles; host hardening (CIS Level 1 diff);
   container escape attempts from the console container; LLM injection through chart text in ja (with the qualified
   pair); egress (DNS included).
2. **Out of scope:** the hospital's EMR, SS-MIX2 store, directory; denial of service; physical attack beyond a powered-off
   stolen box.
3. **Standard:** ASVS 4.0.3 L2 (or 5.0 L2 if 16-13 lands first); OWASP LLM Top 10 2025 for the model path.
4. **Box:** a VALIDATION box on the 5090 tier with synthetic data; one day on the no-GPU tier.
5. **Effort and cost:** 8–10 tester days, ¥1.5–4 M in Japan [O; no quote obtained].

### 2.8 Incidents, breach clocks, retention, tiers

- Clocks for Japan (C2-C5) and Taiwan (C6-C8) exist, marked "counsel confirms" [R
  `docs/plan/sites/incident-response.md:53-65`]; **no US clocks** (HIPAA breach notice: individuals without unreasonable
  delay and within 60 days; HHS; the BAA's clock) — **not verified** against 45 CFR 164.404 in this session (16-11).
  Tabletop records exist for CGMH and Japan [R `docs/plan/sites/tabletop-record-japan.md`].
- Retention and deletion: country defaults and the erasure registry (28 owed, J-2) [R].
- **Per tier [O].** No-GPU box (1U or mini PC): in a server room; TPM+Tang. Spark: small enough to carry away — treat
  as a laptop: TPM+PIN, Kensington lock, no unattended unlock. 5090 / 6000 Pro under a desk: the riskiest physically;
  require a locked room or a locked case, Tang unlock (the disk opens only on the hospital network), and BIOS
  password; `check_host` should report the tier and FAIL a desk-side box with TPM-only unlock (16-20).

---

## 3. ASVS 4.0.3 Level 2, the chapters nobody scored: V10, V11, V12, V13 (sampled, from the code)

Requirement wording from the 4.0.3 files [S https://raw.githubusercontent.com/OWASP/ASVS/v4.0.3/4.0/en/0x18-V10-Malicious.md,
`0x19-V11-BusLogic.md`, `0x20-V12-Files-Resources.md`]. Basis: read (hypothesis), not run, unless stated.

| Req | Paraphrase | Verdict | Evidence |
| --- | --- | --- | --- |
| 10.2.1 | No unauthorised data collection or phone-home | **meets** (read) | `VLLM_NO_USAGE_STATS`, `HF_HUB_OFFLINE` [R `deploy/docker-compose.gb10.yml:67-68`]; `HF_HUB_DISABLE_TELEMETRY` [R `deploy/docker/embed.Dockerfile:29`]; internal networks [R `deploy/docker-compose.yml:493-499`]; no packet capture run |
| 10.2.2 | No unnecessary permissions | partly | only model-guard drops capabilities [M 3] |
| 10.3.1 | Updates over a secure channel, signature checked before install | **meets** | [R `tools/verify_update.py:243-294`] |
| 10.3.2 | Integrity protection; no code from untrusted sources | **meets** | script by CSP hash, no CDN [R `services/console/app.py:111`; `templates/base.html:71`] |
| 10.3.3 | Subdomain takeover | not applicable | on-prem names |
| 11.1.1 | Steps in order | **meets** | decide, sign, send; signed value locked (full review K 11.10(f)) |
| 11.1.3 | Per-user limits on actions | partly | reveal and job rate limits [R `services/console/auth.py:352`; `app.py:969`]; no limit on export count |
| 11.1.4 | Anti-automation (bulk extraction) | partly | sign-in throttle (V3-01 caveat); no limit on exports |
| 11.1.5 | Limits follow the threat model | does not meet | no threat model (V3-16) |
| 11.1.6 | Race conditions on sensitive operations | **meets** for EDC | `FOR UPDATE` on draft and signature rows [R `services/edc/store.py:763`, `:904`] |
| 11.1.7 | Monitor unusual business activity | does not meet | lock-out alert only [R `services/console/identity.py:290`] |
| 11.1.8 | Configurable alerting | partly | daily health mail; no rule set |
| 12.1.1 | Large files refused | meets | 50 MB [R `services/console/app.py:98`] (checklist) |
| 12.1.2 | Compressed files: uncompressed size and count checked | **does not meet** | `z.read(n)` for every member, no cap [R `services/criteria_compiler/import_ruleset.py:41`] (review 01 §7.2) |
| 12.1.3 | Per-user quota | does not meet | none found [M 9] |
| 12.2.1 | Type by content | partly | `%PDF` sniff or `.pdf` suffix [R `services/doc_parser/parser.py:97`]; `.docx` by suffix [R `services/console/app.py:97`] |
| 12.3.1 | No user filename in file-system calls | **meets** | filename reduced to `[\w.-]` and 120 chars [R `services/console/app.py` chart upload, line 2182 by offset] |
| 12.3.6 | No code from unverified sources | meets | hashed locks; pinned images |
| 12.4.1 | Untrusted files outside web root | meets | stored by the orchestrator, served through pages |
| 12.4.2 | Antivirus on untrusted files | **does not meet** | no scanner in the stack [M 9]; the hospital's endpoint AV is the usual answer [O] |
| 12.5.2 | Uploaded files never served as HTML | meets | attachment view under `default-src 'none'; sandbox` [R `services/console/app.py:1605`] |
| 12.6.1 | Outbound allow-list | **meets** | default-deny egress (`deploy/egress.py`); REDCap host by name owed (review 01) |
| 13.1.3 | No secrets in API URLs | meets | (checklist) |
| 13.2.1 | Only allowed HTTP methods | meets (read) | FastAPI routes per method |
| 13.2.2 | JSON validated against a schema | meets (read) | generated contracts `libs/tb_contracts/generated/models.py` [R] |
| 13.2.3 | CSRF on changing API calls | meets | (checklist) |

**Count (26 lines):** 14 meets, 6 partly, 5 does not meet, 1 not applicable. New findings: 12.1.2 (S, B2), 12.1.3 and
11.1.4 (export limits, S, C2 decides), 11.1.7 (an unusual-activity rule set, M, C2 decides), 12.4.2 (a document for the
hospital, or ClamAV in the parser container: owner decision 16-D4).

---

## 4. The certification path, in order

### 4.1 Before the first Japanese hospital signs: the documents the 情報システム部門 will ask for

| # | Document (Japanese name) | Exists? | Where, or what is missing | Who |
| --- | --- | --- | --- | --- |
| 1 | システム概要・構成図 | yes (ja) | IT pack §B.1-B.2 [R `docs/plan/sites/it-security-pack.md:126-135`] | – |
| 2 | ネットワーク構成・ポート一覧 | yes (ja) | `docs/handover/network-sheet.ja.md` [R] | – |
| 3 | サービス仕様適合開示書 (2省GL 別紙1 form) | **no** | answer each item of the form from the IT pack and design 03 | company (16-2) |
| 4 | MDS/SDS (JAHIS/JIRA 製造業者/サービス事業者による医療情報セキュリティ開示書) | **no** | current form version **not verified** | company (16-2) |
| 5 | 責任分界表 (hospital / Aimedics / sub-suppliers: GPU vendor, OS) | **no** | build from the RACI in RUNBOOK 07 and 21 | company (16-3) |
| 6 | SLA (2省GL SLA参考例 form) | partly (ja) | support sheet has 18 ja lines [M 10]; no availability, RTO, response targets in that form | company (16-3) |
| 7 | リスクアセスメント結果 (vendor's, shared) | partly (en) | `docs/plan/design/11-risk-management.md` is product hazards; no security risk register | company + D (16-16) |
| 8 | 脆弱性・パッチ対応方針 | en only | RUNBOOK 24, 0 ja lines [M 10] | J (16-21) |
| 9 | バックアップ・復旧手順と RTO/RPO 実績 | en only, unmeasured | RUNBOOK 22 [R] | D + integrator |
| 10 | リモート保守の手順・記録 | en only | RUNBOOK 21, 0 ja lines [M 10] | J (16-21) |
| 11 | 事故対応体制・連絡先 | yes (ja §B) | incident plan [R] | – |
| 12 | 個人情報の取扱い (委託先の安全管理措置) | yes | privacy pack, APPI mapping [R] | – |
| 13 | サイバーセキュリティ対策チェックリスト (事業者確認用の回答) | **no** | a filled answer per item | company (16-4) |
| 14 | 第三者認証 (ISMS / Pマーク) or a written plan to obtain | no | – | company (16-5) |
| 15 | SBOM | yes | in the bundle [R] | – |
| 16 | ペネトレーションテスト結果 (summary) | no | section 2.7 | company (16-22) |

### 4.2 Before a sponsor-run multicentre trial uses it

Supplier audit by the sponsor (GAMP 5 / E6(R3) Annex 1 vendor oversight): the IQ/OQ pack (9i-14), the traceability
chain (9i-15), the release record (K-1), Part 11 / ER/ES / TFDA assessments (16-6), a QMS (qms-lite is enough for a
non-device [R `docs/validation/standards-position.md:5-13`]), the penetration-test summary, ISO 27001 or a dated plan,
a disclosure policy and VEX (16-8, 16-9). Every site of a multicentre trial gets the same signed release and its own
site validation record (section 10.6).

### 4.3 What waits

SOC 2, HITRUST, HIPAA BAA template (a US site), ISO 13485 / 62304 certification (a device trigger), ISO 42001, ISMAP
(never, on-prem).

### 4.4 Who and what it costs (company, not code)

| Item | Who | Cost [O unless marked] | Effort |
| --- | --- | --- | --- |
| Name a security officer (REG-031) | owner | – | – |
| 開示書, MDS/SDS, 責任分界表, SLA, checklist answers | security officer with lane J | – | ~10 days |
| Outside penetration test | a Japanese security firm | ¥1.5–4 M | 2 weeks incl. retest |
| ISMS (27001) certification | company, a CB under ISMS-AC | audit 数十万円〜100万円超/year [S2] + consultant ¥1–3 M | 6–12 months |
| プライバシーマーク | company | ~¥0.34 M (small) [S2] | 6–12 months |
| Vendor signing key in a hardware token (two tokens) | company | ~¥30 k | 1 day + ceremony |
| Counsel reading of clocks and legal basis (D-311 B26) | owner | not estimated | – |

---

# Part II. An interface customisable on desktop and phone

## 5. What "fully customisable according to needs" should mean, and where it must stop

The owner's words are right for a clinic: a PI on a phone between patients, a CRC at a desk with two monitors and a
steward reviewing 469 items need different screens [R 09 §2]. "Fully" must still stop where a change would alter the
record or what a person is allowed to do, because a configurable screen must stay validated (review 07; GAMP 5
category 4: configuration is validated as data) [O].

### 5.1 Levels

| Level | Who sets it | May change | Examples | Validation weight [O] |
| --- | --- | --- | --- | --- |
| Per user | the person | how things look and what they see first, inside what their role already shows | density (comfortable / compact), text size (100–150 %), colour mode (system / light / dark / high contrast), language, home blocks order and hidden blocks, saved views (filter + sort + columns), column choice on lists, notification rules (which events mail them, quiet hours), default study | none: preference, not configuration; kept per user, audited as `pref.set` |
| Per role (site default) | administrator, by a reviewed change | the default home, default columns, the phone bottom bar's four items | PI home: "Needs you today" + week list; CRC home: clinic list + visits | light: a definition version with a reason |
| Per study | study administrator | list columns from the study's own fields, which statuses appear in filters, form layout and wording of the study's own forms (REDCap dictionary), visit names | an oncology study shows ECOG and line of therapy as columns | **validated**: part of the study's set-up record, versioned with the protocol amendment |
| Per site | site administrator | terms (院内用語), branding (name, logo, colour within contrast limits), document templates (letters, notices), approval chains for *documents*, working calendar (holidays, clinic days), local code mappings (already exist) | 「被験者」 vs 「参加者」; the hospital's logo; 祝日 | **validated**: the site validation record lists every definition version in force |
| Per deployment tier | the release | what is offered at all (e.g. no live "Ask" on the no-GPU box) | – | release-level |

### 5.2 What may never be customised, and why

| Never | Why | Enforced by [O] |
| --- | --- | --- |
| What a role may do, the permission matrix, delegation | lane C2's; Part 11 11.10(d), (g) | definitions cannot name an action; the server checks `permit()` regardless of what is shown |
| The audit trail, its fields and who reads it | 11.10(e), E6(R3) | no definition targets audit pages |
| Consent state, withdrawal effect | K-4, APPI/PDPA | consent widgets are fixed components; a definition may place them, never hide them on a participant page |
| Safety clocks (SAE deadlines, banners by severity) | patient safety; DS-9 | the urgent banner and SAE line are pinned: a home definition without them is refused |
| Validated text: intended-use statement, signature meaning, consent wording, the twenty core terms in their clinical meaning | 11.50; DS-16 | site terms may *add* a local synonym shown beside, never replace a signature meaning |
| Data recorded: fields, units, rounding | the record | lists display; they never compute or write |
| Security headers, scripts, outside content | CSP; ASVS 10.3.2 | no HTML, no script, no URL in a definition; a whitelist of components only |

## 6. What exists today (read and counted)

| Kind | Count or state | Evidence |
| --- | --- | --- |
| Per-user stored preferences | **2**: language (session and cookie) and the remembered acting role | [R `services/console/auth.py:94-101`, `:880`; `app.py:95`] |
| Per-user columns, density, text size, saved views, notification rules | **0** | no table or field found [M 11] |
| Colour mode | follows the system only (`prefers-color-scheme`) | [R `services/console/static/console.css:8`] |
| Work lists | 7 fixed lists, 25 rows a page, order fixed in code | [R `services/console/studies.py:682-684`] |
| Role homes | 2 dedicated home templates (`home_admin`, `home_crc`) + the week page | [M 11] |
| Box-wide flags | 7, one of them layout (`layout.phone_first`, off by default, administrator with reason) | [R `libs/tb_common/flags.py:112-121`; `services/console/phone.py:1-12`] |
| Site settings | 26 top-level keys in `settings.schema.json`; site name, time zone, locale, notes language; nothing about screens, terms or branding | [M 12; R `schemas/settings.schema.json`] |
| Text catalogue | 3,099 keys × 3 languages in code; **no site override path**: `lookup()` reads only the built-in dictionaries | [M 5; R `services/console/i18n.py:1141-1155`] |
| Per-study forms | the study's REDCap data dictionary drives EDC forms (fields, choices, translations) | [R `services/datacore/forms.py`, 536 lines] |
| Templates and stylesheet | 135 templates, 106 extend `base.html`; 65 contain a `<table>`; one stylesheet of 645 lines with 23 `@media` blocks; one script of 182 lines | [M 6] |
| Browser-side state | session storage for typed notes and form drafts | [R `services/console/static/console.js:49-94`] (V3-19) |

[O] Against section 5, TrialBox is today at "per-user: language; per-box: one layout switch". The foundation for more
is good: server-rendered pages, one stylesheet, an audited flag table, versioned settings checked by a schema.

## 7. How good products do it (sources opened 2026-11-18 unless marked)

| Product / standard | What it does for configurable screens | Licence (as read) | Verdict |
| --- | --- | --- | --- |
| OpenMRS 3 (O3) configuration and extension system [S https://o3-docs.vercel.app/docs/configure-o3/overview, https://openmrs.atlassian.net/wiki/spaces/docs/pages/150930332/Configuration+System] | each module declares a **config schema** with defaults and validators; implementers override in JSON; **extension slots** take `add`, `remove`, `order`, `configure` per slot; the in-browser Implementer Tools edits are temporary and must be downloaded and committed to the distribution's config | MPL 2.0 with healthcare disclaimer (not re-opened this session) | **Learn from (closest model)**: schema-declared config, slots with add/remove/order, "edit in UI, commit as file" |
| DHIS2 metadata-as-configuration [S https://docs.dhis2.org/en/use/user-guides/dhis-core-version-240/exchanging-data/metadata-synchronization.html] | dashboards, forms, indicators are **metadata**; each export snapshot is a metadata version; packages import with a **dry run** first; a newer package overwrites the old objects | BSD-3 (not re-opened) | **Learn from**: dry-run import, version per snapshot, packages per programme |
| REDCap (reports, project dashboards, Data Access Groups) | per-project reports with chosen fields and filters; dashboards built from Smart Charts; DAGs restrict rows per site | proprietary, consortium licence | **Learn from** the vocabulary sites already know; public documentation of dashboards **not opened** |
| Medplum apps [S https://raw.githubusercontent.com/medplum/medplum/main/LICENSE.txt] | FHIR-native; screens from Questionnaire and resource definitions | Apache-2.0 (read) | Learn from; React runtime: ignore as a dependency |
| FHIR SDC (Questionnaire rendering, adaptive forms, population/extraction) [S https://build.fhir.org/ig/HL7/sdc/ (CI build 4.0.0)] | form definition as a resource; rendering extensions | CC0 (HL7 specs; not re-opened) | **Adopt the idea** for site document templates and per-study forms where not REDCap |
| CDISC ODM forms | metadata for CRFs; TrialBox already writes ODM 1.3.2 | CDISC terms | already in use |
| JSON Forms (EclipseSource) [S https://jsonforms.io/docs/uischema/] | a **UI schema** separate from the data schema: layouts, controls bound by scope, rules SHOW/HIDE/ENABLE/DISABLE | MIT (repository, not re-opened) | **Adopt the shape** of the UI schema (layout + control + rule) in Jinja; ignore the React/Angular/Vue renderers |
| react-jsonschema-form | same idea, React | Apache-2.0 (not re-opened) | ignore |
| Odoo views / ERPNext (Frappe) Customize Form | XML/JSON view definitions with inheritance; per-user list column choice and saved filters ("favourites"); Frappe stores customisation as **Property Setters** that export as fixtures | LGPL-3 / MIT (not re-opened) | **Learn from**: customisation as a diff over a shipped default, exportable |
| Superset / Metabase / Grafana dashboards | JSON dashboard models, versioned (Grafana provisioning from files) | Apache-2.0 / AGPL-3.0 / AGPL-3.0 (not re-opened) | Learn from Grafana's "provisioned from file, editable copy in UI"; ignore as runtime (AGPL, JavaScript) |
| Directus / NocoDB views | per-user saved views, column order, density | Directus BSL 1.1 (2023; a 2026 change reported, not verified) [S2 https://directus.com/resources/why-we-are-relicensing-directus]; NocoDB AGPL→Sustainable Use License from 2026-01-09 [S2 https://nocodb.com/docs/self-hosting/license] | **Ignore** (source-available, licence findings); learn the per-user view menu |
| Backstage plugins | front-end plugin model with extension points | Apache-2.0 (not re-opened) | ignore: a plugin runtime is a security cost TrialBox should not take |
| GOV.UK, NHS, USWDS, デジタル庁デザインシステム | patterns and tokens | as review 09 §4 | already adopted by DS-1 to DS-20 |

**Responsive patterns for one definition on phone and desktop [O].** A list definition names columns with a
*priority* (1 = always, 2 = desktop, 3 = wide only) and a *card role* (title, subtitle, badge, meta); the same
definition renders a table at ≥ 760 px and a person card (DS-14) below, with priority-1 fields on the card. The phone
bottom bar (DS-12) is a list of at most four actions chosen from the page's own permitted actions. No client framework
is needed: CSS container queries or the existing `@media` breakpoints.

**Widget and plugin models: the security cost [O].** Any model that lets a site ship code (plugins, custom HTML, script
widgets, Grafana-style panels with HTML) breaks CSP-by-hash, adds a supply-chain path past the signed bundle and
makes per-site validation impossible. TrialBox should allow **only declarative definitions over a closed set of
components it ships**.

**Published rule sets worth adopting.** The ones review 09 adopted (GOV.UK, NHS, USWDS, DADS, Carbon) cover screens;
for configurable screens add OpenMRS's config-schema conventions and DHIS2's dry-run import. "Skills" or design
rule collections for building screens with a coding agent were searched for in review 09; none was opened here
(**not verified**).

**No new runtime dependency is proposed.** JSON Schema validation of definitions uses `jsonschema`, already used by the
settings check (not re-verified in the lock) [O]; if it is not in the console image, adding it is owner decision 16-D6.

## 8. The design: a view-definition model

### 8.1 What a definition is

A **view definition** is a small YAML or JSON document, validated by a JSON Schema the console ships, naming one of five
kinds: `list`, `card`, `detail`, `home`, `phonebar`. Example (illustrative, not code):

```yaml
kind: list
id: worklist.ready            # the page it serves
version: 3
scope: {level: site, role: crc}   # or user:<name>, study:<id>
extends: builtin:worklist.ready@1.0
columns:
  - {field: patient.display, priority: 1, card: title}
  - {field: fit.open_count, priority: 1, card: badge, label_key: list.col.open}
  - {field: next_visit.date, priority: 2, card: meta}
  - {field: study.ecog, priority: 3}          # a study field, allowed only if the study exposes it
sort: [{field: fit.open_count, dir: asc}]
density: compact
page_size: 25                 # within 10..100
```

**Rules [O]:** `field` comes from a catalogue of exposed fields per page (generated from the page's own query, the same
for every role); the server still filters rows by role and scope; labels are catalogue keys or site terms, never
free text on clinical pages; a definition may hide a column but never a pinned component (section 5.2); limits:
≤ 12 columns, ≤ 8 home blocks, ≤ 4 phone actions, page size 10–100.

### 8.2 Storage, versioning, audit, export

- Tables `view_def` (id, scope, version, body, sha256, status: draft/active/retired, by, at, reason) and `user_pref`
  (user, key, value, at). Activation of a site or study definition is a change with a reason, as flags are today
  [R `services/console/admin_flags.py:1-12`], and one audit event `view.activate` with the sha256.
- **File-based and in-product, both [O]:** built-in defaults ship in the signed bundle as files; a site's definitions
  are exported and imported as one signed-by-the-site package (`trialbox views export|import --dry-run`, the DHIS2
  pattern). The in-product editor writes drafts; activation needs a second person for site and study scope (C2 decides
  who). Per-user preferences save immediately.
- **Migration on upgrade:** each built-in has a version; a site definition `extends` one. On upgrade, a migration
  script per built-in version maps renamed fields; a definition that no longer validates is set to `retired`, the
  built-in serves, and the health page lists it (never a broken page).

### 8.3 Tests: keeping walks and visual checks meaningful when screens vary

1. The walks and DS-17's visual regression run on **built-in definitions** only; they prove the product.
2. A **definition linter** in CI and on import: schema, field catalogue, limits, pinned components, contrast of a
   site colour against DS-1's tokens.
3. A **render test per definition**: every active definition renders each page empty, with 1 row and with 100 rows at
   390 px and 1280 px: no sideways scroll, one `h1`, the pinned components present (DS-5, DS-8 checks reused).
4. **Per-site validation record**: `trialbox validate --stage pq` (9i-14) lists the sha256 of every active definition;
   a change of an active site or study definition is a change-control event that re-runs test 3 for that page and
   appends to the record (review 07's change classes).

### 8.4 How review 09's design system becomes the foundation

DS-1 (tokens) gives the only colours and sizes a definition may choose (density = a token set; text size = the type
scale of DS-2). DS-4 (one state pill) is the `badge` role. DS-5 (page header) and DS-8/DS-9 (empty states, banners) are
the pinned components. DS-12 (bottom bar) is the `phonebar` kind. DS-13 (task line, "Needs you today") is the first
`home` block. DS-14 (person card) is the `card` rendering of a `list`. DS-15 (five templates) are the five kinds.
**So the order is: DS-1 → DS-4/5 → DS-14/12 → the definition model on the three work lists → DS-15 everywhere.**
Building customisation before DS-15 would freeze today's 60 state classes into configuration [O].

---

## 9. (a) Gap table: what the product does today / what is needed / evidence

| Area | Today | Needed | Evidence |
| --- | --- | --- | --- |
| Japanese vendor documents | IT pack, network sheet, incident plan in ja | 開示書, MDS/SDS, 責任分界表, SLA form, checklist answers, ja RUNBOOK 21/22/24 | [R it-security-pack; M 9, M 10] |
| Company certification | SoA for 27001 (93 controls) | an ISMS or Pマーク, or a dated plan; a named security officer | [R `docs/validation/soa.csv:2-3`] |
| Threat model | none | maintained file (section 2 as v1) | [R checklist:262] |
| Container hardening | 1 of 15 services | 15 of 15 | [M 3] |
| Audit tamper evidence | nightly signed head, key on the box | hourly, anchor off root's reach | [R `deploy/install.sh:810`] |
| Vendor signing | file key, one person | hardware token, two-person, provenance | [R `tools/make_bundle.sh:6`] |
| SBOM / VEX | CycloneDX in bundle; no VEX | VEX per release; disclosure policy | [R `make_bundle.sh:14-18`] |
| Pen test | none | scoped test before first real patient | full review J-M8 |
| Dynamic scan | none | ZAP baseline nightly | [M 9] |
| Restore measured | CI drill only | on box hardware, RPO/RTO recorded | [R runbook 22:22-25] |
| US clocks, BAA | none | before a US site | [R incident-response:53-65] |
| Stale security docs | anti-rollback "not done" | corrected | [R `docs/security/06-audit-retention-updates.md:22`] |
| Per-user customisation | language, acting role | density, text size, colour mode, columns, saved views, home order, notification rules | [R auth.py:94-101] |
| Per-site wording and branding | none | site terms layer and logo within limits | [R `i18n.py:1141-1155`] |
| Per-study list design | none (forms only) | study columns from exposed fields | [R `studies.py:682-684`] |
| Configuration as validated data | flags only | view definitions, versioned, audited, in PQ record | section 8 |

## 10. (b) Cards, in the order of what waits for what

Size: S a day or less, M a few days, L a week or more. "C2 decides" marks anything near roles, audit or break-glass.

| Card | What | Size | Lane | Waits for | Proving test or measurement |
| --- | --- | --- | --- | --- | --- |
| 16-18 | Correct `docs/security/06` (anti-rollback, key id, expiry done) and add `--no-backup` refused in PRODUCTION unless a reason is given | S | D | – | the doc lint passes; a test: `apply_update.sh --no-backup` without reason exits 2 under `TB_ENV=PRODUCTION` |
| 16-17 | `cap_drop: [ALL]`, `no-new-privileges`, `read_only` + `tmpfs`, fixed `user` on all 15 services | M | D | – | a compose test counts 15/15; e2e-simple green |
| 16-19 | Audit head signed hourly; anchor target refused if writable by box root; doctor FAILs a head older than 2 h | S | C2 decides, D builds | – | doctor test with a 3 h old head; [M] the cron line |
| 16-16 | Threat model file (section 2 as v1), reviewed per release; ASVS 1.1.2 to "meets" | S | D | – | the checklist line flips; release record cites its version |
| 16-13 | ASVS: score V10–V13 lines of section 3 into `checklist.json`; plan the move to ASVS 5.0 L2 | M | D, C2 | 16-16 | `tools.asvs_checklist --check` passes with the new lines |
| 16-23 | Ruleset zip: cap members (≤ 2,000) and total uncompressed size (≤ 200 MB) before reading (12.1.2) | S | B2 | – | a zip-bomb fixture refused |
| 16-15 | Vendor key in a hardware token, two-person signing; SLSA provenance and cosign signatures for images, verified offline at install | M | D | owner 16-D2 | a bundle signed with a file key is refused by policy; provenance verifies offline |
| 16-9 | VEX (OpenVEX or CSAF) generated from the waivers file per release; each waiver gets an owner and date (J-1) | M | D | – | release record carries VEX; a waiver without owner fails CI |
| 16-8 | Public security contact, disclosure policy (`SECURITY.md` at the product root), IPA/JVN route described | S | J | owner names the officer | file exists; contact answers |
| 16-24 | ZAP baseline scan of the demo stack in the nightly | S | D | – | nightly report, zero High |
| 16-20 | `check_host` knows the tier; FAIL TPM-only unlock on desk-side tiers in VALIDATION/PRODUCTION | S | D | – | luks_policy fixtures per tier |
| 16-25 | Unusual-activity rules (export volume, off-hours reveal, many patients in a short time) on the health page (11.1.7, 11.1.8) | M | C2 decides | 16-16 | a synthetic burst raises the line |
| 16-2 | サービス仕様適合開示書 and MDS/SDS, ja, from the IT pack and design 03 | M | J + company | 16-16 | the hospital's 情報システム部門 accepts; every item answered or "not applicable, because" |
| 16-3 | 責任分界表 and SLA in the 2省GL form, ja | S | J + company | – | as above |
| 16-4 | Answers to the MHLW cybersecurity checklist's vendor items; re-map design 03 to 第7.0版 (June 2026) | M | J | – | every checklist item has an answer and a file:line |
| 16-21 | ja versions of RUNBOOK 21, 22, 24 | M | J | clinician readers (ruling) | 0 → full ja coverage [M 10] |
| 16-6 | Assessments: ER/ES指針, TFDA computerised systems (final text), FDA 2024 Q&A, 電子簽章法; one table each | M | J + consultant | counsel (D-311 B26) | four files, each row with evidence |
| 16-22 | Pen test (section 2.7), retest, summary for the pack | L | company | 16-17, 16-19, V3-14/V3-18 fixed | report with zero open High |
| 16-14 | CIS Level 1 diff for the host and Docker, in `check_host` output | M | D | – | report per tier |
| 16-11 | US: breach clocks, BAA template, HIPAA Security Rule mapping | M | J | a US site decision | – |
| 16-12 | SSDF (800-218) and IEC 81001-5-1 mapping table | S | J | – | every practice row cites a file |
| 16-7 | JIS X 8341-3 / WCAG conformance statement after DS-1 to DS-8 | S | J | DS-8 | 試験結果表示 published |
| 16-26 | Per-user preferences: density, text size, colour mode (incl. high contrast), language, quiet hours; `user_pref` table; audited | M | C2a (console) | DS-1, DS-2 | a user's choice survives sign-out; pages pass contrast in all modes |
| 16-27 | View-definition schema, field catalogue per page, linter (section 8.1, 8.3 test 2) | M | J | DS-4, DS-5 | linter refuses a pinned component hidden, a 13th column, HTML |
| 16-28 | `list` and `card` kinds on the three work lists (clinic, ready, needs) with saved views and column choice | L | C2a | 16-26, 16-27, DS-14 | render test 3 on 390/1280 px; walk unchanged on built-ins |
| 16-29 | `home` and `phonebar` kinds; role defaults | M | C2a | 16-28, DS-12, DS-13 | home per role ≤ 5 lines; phone primary act visible at 390 × 844 |
| 16-30 | Site terms layer (add a local synonym beside a core term; never replace) and branding (name, logo, accent colour within DS-1 limits) | M | J | DS-16, decision 2 of 09 | the catalogue check refuses a replaced core term; contrast holds |
| 16-31 | Per-study list columns from study fields; definitions in the study's set-up record | M | C2a, E | 16-28 | an amendment creates a new definition version |
| 16-32 | Export/import with dry run; activation with reason and second person (C2 decides); PQ record lists sha256 of active definitions | L | D, C2 | 16-27, 9i-14 | a dry run lists diffs; the PQ record changes when a definition does |
| 16-5 | ISMS (27001) programme, or Pマーク, with a dated plan the pack can cite | L | company | owner 16-D1 | certificate or a CB's stage-1 report |
| 16-10 | Taiwan supplier statement under EMR regulation Art. 6–7 and 資通安全管理法 contracts | S | J + company | 16-5 plan | statement filed in the TW pack |

**Count:** 32 cards: 11 S, 16 M, 5 L (including the company's 16-5 and 16-22).

## 11. (c) Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 16-D1 | ISO 27001 or プライバシーマーク first (or both) | **ISO 27001 first**: it serves Japan, Taiwan (Art. 6, 資通安全管理法 受託者) and a sponsor's audit; Pマーク only if a Japanese hospital insists |
| 16-D2 | Hardware tokens and two-person signing for releases | **Yes**, before the first real-patient bundle; two tokens, kept apart |
| 16-D3 | Commission an outside penetration test before the first real patient (¥1.5–4 M) | **Yes**, after 16-17 and the two High audit findings are fixed, so money is not spent finding known holes |
| 16-D4 | Antivirus in the box (ClamAV in the parser container) or rely on the hospital's | **Rely on the hospital**, said plainly in the 開示書; revisit if a hospital asks |
| 16-D5 | How far "fully customisable" goes | **Per-user and per-site display only, as section 5**; never roles, audit, consent, clocks or validated text |
| 16-D6 | Allow a JSON Schema validator in the console image if it is not already there | **Yes** if needed; no other runtime dependency; no client framework |
| 16-D7 | Who may activate site and study definitions (C2 decides the role; the owner decides whether a second person is required) | **Second person required** for site and study scope; none for per-user |
| 16-D8 | Name the company's security officer (REG-031) | **Now**; every company item above waits for this person |

## 12. (d) What the owner or the first hospital must supply

1. The owner: the security officer's name and contact (16-D8); the decision on ISO 27001 (16-D1); a budget line for
   the penetration test.
2. The hospital (public or blank forms only): the hospital's own 開示書 / MDS/SDS form version if it uses a specific
   one; its 責任分界 template if it has one; the list of documents its 情報システム部門 requires for a new system;
   whether it is designated under any critical-infrastructure regime; whether remote maintenance is allowed and how
   it is logged; its BCP target RTO for a non-clinical research system.
3. A synthetic sample of the hospital's site settings (language, holidays, clinic days) to test the per-site layer.
4. Counsel: confirmation of the breach clocks (C2–C9) and, for Taiwan, whether a copy-holding screening box falls
   under EMR regulation Art. 6.

## 13. Measurement log

| # | Command (from `trialbox/` of this worktree, the main checkout's interpreter) | Result |
| --- | --- | --- |
| M 1 | `python -m tools.security_scan secrets > /var/tmp/trialbox-0/b17/secrets.txt` | 6 findings (5 Basic Auth, 1 Private Key), 6 in reviewed ignores, PASS |
| M 2 | `python -m tools.security_scan sast > /var/tmp/trialbox-0/b17/sast.txt` | 89 findings, 12 rules (B608 39, B108 16, B310 10, B314 6, …), all reviewed, PASS |
| M 3 | `yaml.safe_load(deploy/docker-compose.yml)['services']`: count keys | 15 services; cap_drop 1, read_only 1, user 1, memory limit 15; 3 internal networks |
| M 4 | `grep -n '^USER' deploy/docker/*.Dockerfile` | `USER tb` in python, jvm and embed images |
| M 5 | `len(console.i18n.EN/JA/ZH)` | 3,099 each |
| M 6 | `ls templates | wc -l`; `grep -l '<table'`; `wc -l static/*`; `grep -c '@media'` | 135 templates, 106 extend base, 65 with a table; css 645 lines, 23 media blocks; js 182 lines |
| M 7 | ASVS 4.0.3 V10–V12 files opened | requirement lists used in section 3 |
| M 8 | `python tools/doclint.py`; `python -m tools.data_scan` on this branch | doclint clean (6 warnings, none in this file); data_scan clean (4,756 files, 10 patterns) |
| M 9 | greps: `開示書|責任分界` in `docs/`; `clamav|antivirus`; `urlize`; `quota`; `SECURITY.md` at product root; ZAP/CodeQL in workflows | only research mentions; none; none; none; none; none |
| M 10 | count of lines with kana in RUNBOOK 21, 22, 24, support sheet, risk file | 0, 0, 0, 18, 2 |
| M 11 | `grep -iE 'prefer|density|saved.?view'` in console; `ls templates | grep home` | no preference store beyond language and role; 2 home templates |
| M 12 | `settings.schema.json` top-level properties | 26 |

## 14. (e) What this document did not verify

- The final text of the 2省GL 2.0 FAQ and 別紙1 (METI pages returned 403); the scope reading rests on the draft FAQ on
  soumu.go.jp.
- The MHLW checklist PDF itself, the JAHIS/JIRA MDS/SDS current version, the METI SBOM guide's final text, ISMAP's own
  scope page (the portal did not render).
- Exact fees: JIPDEC's fee page (404), ISMS, SOC 2 and HITRUST costs come from secondary pages; the pen-test cost is
  an estimate with no quote.
- TFDA's computerised-systems guideline: whether the 2024 version is final.
- US breach-notice periods (45 CFR 164.404–408) and the HIPAA NPRM text; FDA 2024 Q&A and CSA texts were not opened,
  only their notices.
- Repository licences and activity of the products in section 7 (the GitHub API was closed to this session); licences
  marked "not re-opened" are from memory and must be checked before any adoption.
- Whether the two-device form encrypts its cable link; whether `jsonschema` is in the console image.
- Nothing was run against a live stack; no scanner other than the repository's own two ran; no packet capture.
