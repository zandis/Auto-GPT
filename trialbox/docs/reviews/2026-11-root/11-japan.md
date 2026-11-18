# Japan, in full: the first site, the rules, the codes, the language, the trial world and the customs (lane J, root review 11, 2026-11-18)

**Reader:** the owner first (the one-page summary). Then the builders (sections 1 to 8) and plan 10 (sections 9 to 13).

**What was analysed:** master `7da6edd38`. Read: the ja message catalogue (all 44 `services/console/i18n*.py` modules,
3,099 keys in the merged ja catalogue), the Japan reference-data code (`libs/tb_common/refdata_jp.py`,
`services/adapter/licensed.py`, `services/adapter/validate/jpcore.py`, `libs/tb_common/dates.py`,
`libs/tb_common/phi_guard.py`, `services/console/notify.py`), the intended-use statement
(`docs/plan/intended-use.md`), the laws page (`docs/security/07-laws-a-site-must-check.md`), the Japanese clinical-text
benchmark (`eval/medtxt/`), reviews 01, 02, 03 and 05 on master, and 06, 07 and 09 and plan 9 revision 2 on their
branches. Opened for this page (Japanese originals, 2026-11-18): the first site's public pages and PDFs (kept outside the
repository, [SN]); the e-Gov text of 個人情報保護法, GCP省令, 臨床研究法, 次世代医療基盤法 and 薬機法; the 2026 revision of the
生命・医学系指針 and its consolidated text; the PPC/MHLW medical guidance (令和8年4月 revision); the MHLW program
medical-device guideline, its case examples and its case database (updated 2026-10-14); the security guideline 第7.0版
(two parts); PMDA's 2026 briefing on the GCP amendment; the MHLW standards list (HS001 to HS043); MEDIS terms; JP Core;
UMIN-CTR; the MHLW 先進医療 page; the Cabinet Office holiday file; a university press release on Japanese medical
models. No hospital-internal document, no real patient data, nothing non-public. No product code was changed.

**Scope.** Review 12 covers the SSI hospital system's data and SS-MIX2 in depth; this page points there for the feed.
"SSI" as 株式会社ソフトウェア・サービス is the coordinator's reading, **not confirmed** by the owner; nothing below
depends on it except where said.

**What this page does not repeat.** 06's general code-system tables (cited **06** with its card ids T6-n and O-n),
07's validation design (**07**), 09's typography and term table (**09**, DS-n), 02's role words for non-治験 research
(**02** J-7) and plan 9 revision 2's bands 9h to 9m and decisions 1 to 46 (**P9r2**).

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[R]** | Read: the file and line follow in backticks |
| **[S n]** | Source: row n of the source list (section 14); opened for this page on 2026-11-18 |
| **[M n]** | Measured: row n of the measurement log (section 15) |
| **[O]** | Opinion: the analyst's judgement, to be argued with |
| **[SN]** | From the first site's public pages; kept outside this public repository in the site notes (the owner has not agreed to publish the name) |
| **not verified** | Could not be checked here; section 13 lists each |

---

## Summary for the owner (one page, plain words)

**The first site** is a general hospital in Japan (its name is not published here, at the owner's request). Its
public pages show what is typical of a private Japanese general hospital of its kind: no IRB of its own for 治験
(an external IRB per trial), a research ethics committee meeting monthly, one opt-out notice per study on its
website, company trials and many post-marketing surveys, paper and seals still used for some forms, and part of
the older records outside the current chart [SN] (section 1).

**What is good enough today.** TrialBox already reads Japanese dates in all their forms (令和, R5.3.1, 元年) [R], keeps
a 疑い diagnosis from counting as a diagnosis [R], loads the hospital's own MEDIS, HOT/YJ and JLAC files without
shipping them [R], has the Japanese eGFR equation [R], keeps the jRCT file a hospital downloads [R], and its intended
use is written the way the Japanese device guideline asks [R]. The Japanese interface is complete (no English
fall-backs) and mostly polite in register [M 1].

**What is not good enough.**
1. **The legal path for screening charts before consent is not written down for Japan.** The law allows it, but only
   inside the hospital's published purposes of use, or under a research plan with an opt-out notice; the standard
   purposes list in the national guidance does not name "searching for trial candidates" [S 11]. The hospital has to
   add one line to its notice. TrialBox should ship that line and the opt-out template.
2. **The research ethics rules change on 2026-12-01** (two weeks from today): opt-out becomes the default for research
   on existing records, single-committee review becomes required for multicentre intervention studies, and the
   wording "適切な同意" disappears [S 13]. The **GCP ordinance is being amended** (planned in force 2027-04):
   被験者 becomes 治験参加者, the case report form becomes a "data acquisition tool", single IRB becomes the norm, and
   sponsors gain oversight of SMOs [S 16]. TrialBox's Japanese words follow neither yet (0 of 3,099 strings use
   治験参加者 or 研究対象者) [M 1].
3. **The privacy guard misses Japanese names written in katakana, old-form kanji names and the insurance 記号**
   (4 of 10 synthetic probe lines kept an identifier unmasked) [M 2].
4. **Japanese clinical text is harder for the models than English:** on 215 public Japanese case and radiology
   reports, the best single engine wrongly treated a finding the report said was absent as present in about one case
   in five, and treated a suspected finding as present in about four in five [M 3]. Rules for Japanese negation and
   疑い must come before the model, and Japanese gold data must be bought (P9r2 decision 19).
5. **The Japanese trial world is not modelled:** no 治験事務局, no 実施医療機関の長 (病院長) step, no external-IRB
   record, no SMO, no 統一書式, no 負担軽減費, no 和暦 display, no Japanese public holidays (working days are
   Monday to Friday only) [R], [M 1].

**The five changes that matter most** (cards in section 10): (1) a Japan legal pack: the 利用目的 line, the opt-out
template under the 2026 guideline, the access rule "PI, sub-I and listed 治験協力者 only", a memo per study type
(JP-1, JP-2); (2) the Japanese term set for the 2026–2027 rule changes, decided with the two clinician readers
(JP-5); (3) the guard fixed for カナ, 旧字体 and insurance numbers (JP-8); (4) Japanese negation and 疑い rules and a
Japanese abbreviation table before any model (JP-11, JP-12); (5) a "Japan site profile" switch: 統一書式 numbering,
external-IRB and 病院長 steps, 和暦 display, Japanese holidays and fiscal year, the 治験事務局 role (JP-14 to JP-20).

**What it costs.** No licence fee found for the masters a hospital loads itself (MEDIS is free to download; a vendor
that distributes it must apply) [S 22]. Money is needed for: the regulatory reader in Japan (P9r2 decision 21, by
quote), the Japanese gold set (P9r2 decision 19), and the two clinician readers (P9r2 decision 35). Everything else is
build work: 10 S, 11 M, 3 L cards.

---

## 1. The first site: what a Japanese general hospital of its kind typically has

The first site is a general hospital in Japan. The owner has not agreed to publish its name, so what its own public
pages say is kept outside this repository, in the site notes the coordinator holds (cited **[SN]**). This section keeps
only what a private Japanese general hospital of this kind typically has, and what that means for TrialBox. Where the
first site's pages confirm a row, the row says [SN] and nothing more.

| Item | Typical for a private general hospital in Japan | What it means for TrialBox | Mark |
| --- | --- | --- | --- |
| Legal form | A 医療法人 (medical corporation; private, not distributing profit): a 個人情報取扱事業者 under APPI, supervised by the PPC, not by public-sector rules | APPI applies directly (section 2.1); the academic exception is not available by default | [S 9], [S 11], [SN] |
| Size and designations | Several hundred beds, an ICU, 40 or more departments, cancer-care and emergency designations, often a DPC hospital (it publishes 病院指標) | DPC files (様式1, EF) are a likely second data source (review 12) | [O], [SN] |
| Research office | A 臨床研究センター with a 治験管理室 (the 治験事務局) and a research-support office | The 治験事務局 is a real user with its own work (section 6.4) | [S 10 第38条], [SN] |
| IRB for 治験 | Many mid-sized private hospitals have **no IRB of their own** and send each trial to an external IRB chosen by the 病院長 under GCP 第27条 | The IRB record must name an external committee, its 設置者, the contract and its SOP and roster versions; single IRB becomes the rule with the GCP amendment [S 16] | [S 10], [SN] |
| Research ethics committee | Its own committee for 指針 research, meeting monthly, with a cap on new applications per meeting; roster and minutes on the MHLW 倫理審査委員会報告システム | An IRB-pack export (02 J-13) shortens the queue | [O], [SN] |
| Opt-out notices | One notice per study on the hospital's website, refusals to the study's contact person | Ship the 2026 template (card JP-1) | [O], [SN] |
| Trial SOP | Based on the 統一書式 notices; 押印省略 allowed by agreement but some forms (SAE, deviation) still sealed on paper; 直接閲覧 accepted; 治験協力者 named on 書式2 | Print 統一書式-shaped PDFs with a seal box; do not try to replace paper | [S 10], [SN] |
| Electronic trial documents | An SOP for a 治験クラウドシステム (the site's or the sponsor's), with validation records, per-person accounts and 真正性・見読性・保存性 | TrialBox's own validation pack must answer the same checklist | [SN] |
| Current studies | Company trials (phase III), investigator-initiated trials, and many post-marketing surveys (使用成績調査, all-case surveys), often in rare and pediatric disease | Patient finding for a survey is "every patient started on drug X": structured, not a note question. The registry and PMS scenario (02 section 4b) is a first use, not a side case. Pediatric work means 代諾 and アセント; cohorts of one to ten patients mean small-cell suppression must never hide the only candidate from the PI | [O], [SN] |
| Record history | Hospitals that merged or changed systems keep part of the old records outside the current chart, read on separate terminals | A look-back criterion may reach data the box never sees: the feed must mark where the record starts so that silence is "unknown", not "absent" (card JP-24; review 12) | [O], [SN] |
| SMO, CRB, EHR vendor | Often an SMO for CRCs; rarely an own CRB; the EHR vendor is rarely named on public pages | Ask the site (section 12) | not verified |

## 2. The rules a patient-finding and trial-support product must fit

### 2.1 The central question: on what basis may the hospital screen its own charts before consent?

A 医療法人 is a private 個人情報取扱事業者; APPI applies directly [S 9, 第16条2項]. Screening charts for eligibility is
the hospital **using** information it already holds, not **providing** it to anyone. So:

| Question | The rule's text | What it means for screening | Mark |
| --- | --- | --- | --- |
| Is the use within the purpose? | 第18条1項: no handling beyond the purpose specified under 第17条 without prior consent | The hospital's published 利用目的 must cover "searching records for research and trial candidates"; otherwise consent or an exception is needed | [S 9] |
| Do the standard hospital purposes cover it? | The national medical guidance's 別表2 lists, as internal non-care uses, "医療機関等の内部において行われる観察研究や症例報告" and service improvement; **trial-candidate search is not listed** | A hospital relying only on the standard notice is covered for internal observational research, not clearly for screening for a 治験. Add one line to the 院内掲示 and website: "治験・臨床研究への参加をご検討いただける方を探すための診療記録の確認" | [S 11], [O] |
| Must purposes be posted? | 第21条1項: notify or 公表 at acquisition unless published beforehand; the guidance asks hospitals to post even the care purposes (院内掲示) | The line is added to the existing 院内掲示 and website; it applies to records from then on and, the analyst believes, to existing records only through 第18条 (consent or exception) | [S 9], [S 11]; the retroactivity point is [O] and needs counsel |
| Academic exception? | 第18条3項5号, 第20条2項5号, 第27条1項5–7号 apply to a 学術研究機関等 (大学その他の学術研究を目的とする機関); the guidance: a private body's research unit qualifies only if its main purpose is academic research | A 医療法人 hospital is not, by default, a 学術研究機関等. **Do not rely on the academic exception** for the first site unless counsel says its research centre qualifies | [S 9], [S 11 p.21], [O] |
| 要配慮個人情報? | 第2条3項 (病歴 etc.); 第20条2項: acquisition needs prior consent unless an exception applies | Chart data is 要配慮. Screening re-uses data already acquired for care; no new acquisition. Copying it into a separate research repository (TrialBox's lake) is still use, inside the same 事業者 | [S 9], [O] |
| Who may see the candidate list? | GCP 第44条: "治験責任医師等" select candidates (健康状態, 症状, 年齢, 同意の能力); a typical site SOP: work shared only with those on 書式2 (分担医師・治験協力者リスト) approved by the 病院長 [SN] | For a 治験: PI, sub-Is and the 治験協力者 on 書式2 for **that** trial; an SMO-employed CRC is an outside contractor under GCP 第39条の2 and APPI 第27条5項1号 (委託, not a third party) only if the site–SMO contract covers pre-consent screening | [S 10], [S 9], [SN], [O] |
| May the sponsor or CRO see it? | 第27条1項: no provision of personal data to a third party without consent | Never before consent. Counts and reasons only (the screening log the sponsor asks for). TrialBox already sends patient-level data out only through the EDC [R 02 1.2] | [S 9] |
| May the monitor see records? | GCP 第37条2項: the 病院長 makes 原資料 available to monitor, auditor, IRB | After consent and for enrolled participants. Pre-screening lists of non-consenting patients are not 原資料 of the trial [O] | [S 10] |
| Pseudonymised data? | 第41条: 仮名加工情報 may not be re-identified (7項) and may not be used to contact the person (8項); 第41条6項 forbids providing it to third parties | TrialBox re-identifies by design (it must, to approach a patient), so its data is ordinary personal information, not 仮名加工情報. The repository's wording already says this (plan 28 REG-008) [R `docs/plan/28-master-plan-v6.md:1601`] | [S 9] |
| Data abroad? | 第28条: providing personal data to a third party in a foreign country (outside the PPC's list) needs consent, unless the recipient has an equivalent system; information to the person on request | The box runs in the hospital; the vendor's remote support must not see patient data. If a vendor outside Japan ever needs screen access with patient data, 第28条 applies. Keep "no remote access to patient data" [R `docs/plan/28-master-plan-v6.md:1602`] | [S 9]; whether 委託 abroad falls under 第28条 is **not verified** in the PPC's guidance text |
| Leaks | 第26条: report to the PPC and notify the person for leaks the rules name | The incident plan must have the PPC report path in Japanese | [S 9] |

**Per study type** (the legal basis for the screening step and its notice) [O, built from the rows above and 2.2]:

| Study type | Rule set | Basis for screening the chart | Notice the patient can see | Who sees names | Committee |
| --- | --- | --- | --- | --- | --- |
| 治験 (company or 医師主導) | 薬機法, GCP省令; the 指針 does not apply (指針 第3の1ア/イ) | APPI 第18条 within published 利用目的 (add the line) | 院内掲示 and website line; trial recruitment material approved by the IRB | PI, sub-I, 書式2 治験協力者 of that trial | IRB (external at the first site [SN]) |
| 製造販売後臨床試験, 使用成績調査 (GPSP) | GPSP省令 (survey); GCP for post-marketing trials | As 治験; for a survey, the sponsor's contract defines the cases to register | As above | As above | Per the sponsor's contract; IRB for post-marketing trials |
| 特定臨床研究 | 臨床研究法 (CRB review, jRCT registration, 第5条 実施計画, 第9条 consent) | APPI 第18条 within 利用目的 | As 治験 | 研究責任医師 and 分担医師 | CRB |
| Other intervention or observational research | 生命・医学系指針 (2026 revision from 2026-12-01) | Under the research plan approved by the 研究機関の長 after committee review; existing records with notice and opt-out (指針 第8の2⑶ウ, read in 2.2) | The study's opt-out notice (one per study on the hospital's website is usual [SN]) | 研究者等 named in the plan | 観察・介入研究倫理審査委員会 |
| Feasibility counts for a sponsor | No personal data leaves; aggregate counts | Internal use; the count is not personal data if no cell identifies anyone | None needed for the count [O] | Nobody outside sees names | None, unless the site's SOP asks |
| Multicentre research sharing records | 指針 第8 (provision to another 研究機関) or APPI 第27条 | Consent, or 指針 opt-out provision with the items of 第8の7 | Opt-out notice naming the recipients | – | One committee (一括審査), required for intervention studies from 2026-12-01 |

### 2.2 Each rule, its text, and what it asks of TrialBox

| Rule (edition) | What its text says that matters here | What it asks of TrialBox | Today | Mark |
| --- | --- | --- | --- | --- |
| 個人情報保護法 (e-Gov current) | 第2条3項 要配慮; 第17–18条 purpose; 第20条2項 要配慮 acquisition; 第21条 notice; 第26条 leak report; 第27条 third party, incl. 5項3号 共同利用; 第28条 abroad; 第41条 仮名加工; 第43条 匿名加工 | The 利用目的 line (2.1); access only to named study staff; no sponsor sight before consent; leak report path; no foreign access | Access by delegation log [R 02 1.1]; opt-out register [R 02 1.1]; the legal-basis memo for Japan was struck from the plan (T-646) [R `docs/plan/28-master-plan-v6.md:470`] and does not exist | [S 9] |
| 医療・介護関係事業者ガイダンス (平成29年, 令和8年4月一部改正) | 別表2 purposes; section 9: for 治験 follow the PMD Act and GCP and the guidelines of bodies; for research follow 別表5 guidelines | A ready Japanese 院内掲示 line and a short letter to the privacy officer | None | [S 11] |
| 生命・医学系指針 (令和8年8月27日告示, applies 2026-12-01) | Research classified as (1) invasive or intervention, (2) using specimens, (3) not using specimens; for existing information, notice and "研究対象者等が拒否できる機会を保障" in principle; 仮名加工・匿名加工・個人関連情報 follow APPI only; 一括審査 required for multicentre invasive or intervention research, the rule for others; 研究機関の長の許可 before any research; studies running under the old text may continue "従前の例" if APPI is kept | Opt-out notice template with the items of 第8の7; a record of the 研究機関の長's permission per study; a multicentre study's single committee; the words 研究対象者, 研究責任者, 研究機関の長 | No 研究機関の長 step; 0 strings say 研究対象者 or 研究機関の長 [M 1]; opt-out register exists [R 02] | [S 13], [S 14] |
| 臨床研究法 (平成29年法律第16号) | 第2条 臨床研究 excludes 治験; 特定臨床研究 = company-funded or unapproved/off-label; 第5条 実施計画 to MHLW (published on jRCT); 第9条 consent; 第23条 CRB | For 特定臨床研究: CRB in place of IRB; jRCT number; 研究責任医師 words | jRCT file loader exists [R `libs/tb_common/refdata_jp.py:593`]; no CRB as a committee type | [S 15]; the 2024 amendment's details **not verified** |
| GCP省令 (平成9年厚生省令第28号, as in force) | 第27条 IRB set up by the 病院長 or by listed outside bodies; 第35条 site requirements; 第37条 monitoring, audit, 直接閲覧; 第38条 治験事務局; 第39条の2 outsourcing contract (SMO); 第41条 記録保存責任者 and retention to approval or 3 years after end; 第44条 candidate selection; 第50条 written explanation and consent, 代諾 | Roles: 病院長 (実施医療機関の長), 治験事務局, 記録保存責任者; external IRB; SMO contract; consent with 代諾 record; retention clock tied to the sponsor's notice | Roles 治験事務局, 病院長, 記録保存責任者 absent; 3 strings mention 治験事務局 [M 1]; consent form has 説明者/補助説明者 [R `services/datacore/builtin/forms.csv:13-21`] | [S 10] |
| GCP amendment (draft; promulgation planned 2026-09, in force 2027-04) | New 治験の基本原則; 被験者 → 治験参加者; 症例報告書 → データ取得媒体 (Data Acquisition Tool); 原資料/原記録 defined medium-independent; アセント defined; single IRB as the rule with the sponsor able to ask the IRB; 実施医療機関の長 reviewed; DCT and drug delivery via 治験支援薬局; sponsor oversight of SMOs added to 第39条の2 contract items; information-system requirements written in | The term set changes in 2027; the "site head" step may shrink; TrialBox's computerised-system dossier must answer the new system requirements | Uses 被験者 in 34 strings, 参加者 in 14, 治験参加者 in 0 [M 1] | [S 16]; promulgation **not verified** (e-Gov still shows the old text) |
| GCP 運用通知 | Defines 治験協力者 and 原資料 practice; lists documents to the IRB | The recruitment method (incl. chart search) goes to the IRB | Not addressed | **not verified** (not opened) |
| ER/ES 指針 (平成17年 薬食発0401022号) and "治験関連文書における電磁的記録の活用に関する基本的考え方" (平成26年7月1日 事務連絡) | 真正性・見読性・保存性; electronic signatures; the 2014 note is what PMDA cites for trial documents | The EDC module's signature and audit trail (P9r2 9m-12) in Japanese; a site's 電磁化 SOP asks for a validation record and a 治験クラウドシステムチェックリスト from the vendor [SN] | TB-DS-16 has no Japanese section (07 row 19) | ER/ES text **not verified**; the 2014 note [S 16] |
| e文書法 and its MHLW ordinance | Electronic storage of documents a law requires to be kept; cited by the security guideline for 見読性 | Only if TrialBox holds a legally required record (the consent record, the screening log in the site file) | – | [S 17 a.txt:1190] |
| 医療情報システムの安全管理に関するガイドライン 第7.0版 (2026-06; five parts, a new 保守委託機関編) | Two-factor authentication for systems running at 令和9年4月1日 at their next renewal; client app login and server OS both; passwords 8+; screen lock; access logs collected and reviewed; remote maintenance logged; 責任分界 documented | TOTP exists; WebAuthn is a card (02); a 責任分界表 and the HS040 security disclosure sheet for procurement | TOTP and lockout exist (02); no Japanese 責任分界表; no HS040 sheet | [S 17], [S 18] |
| 提供事業者ガイドライン 第2.0版 (総務省・経済産業省, 2025-03-28) | The vendor's risk assessment, service specification, SLA and 責任分界 | The vendor documents in Japanese | `docs/security/` in English | [S 19]; body text **not verified** |
| 次世代医療基盤法 (now titled for 匿名加工医療情報 **and 仮名加工医療情報**) | Provision to certified makers, with the person's right to refuse (第52条) | Out of scope for one hospital's own screening; in scope only if a certified maker's data is a source | Nothing; correct | [S 20] |
| GPSP省令 | Post-marketing surveys and trials | Registry and PMS patient finding: "every patient started on X" | 02 section 4b; no PMS form | Ordinance text **not verified** |
| eConsent guidance (令和5年3月30日) | Electronic explanation and consent allowed if equal to face-to-face, with remote identity check, signer authentication and delivery of the documents | TrialBox records consent facts, not the consent itself [R 02 2.2]; keep it so; link to the sponsor's eConsent | – | [S 21 search summary]; text **not verified** |
| DCT | Part of the GCP amendment (治験支援薬局) | Visits at home or at a pharmacy appear in the participant's visit plan | No visit location field | [S 16] |
| 患者申出療養, 先進医療, 保険外併用療養 | 先進医療: 評価療養 within 保険外併用療養; 70 technologies as of 2026-10; 先進医療B reviewed with CRB-approved research | A "patients who may fit 先進医療 X" list is patient finding for reimbursement (02 4e); the technology list as reference data | Nothing | [S 23]; 患者申出療養 **not verified** |
| 薬機法 第2条, 第68条 | Device definition includes programs; advertising an unapproved device is forbidden to "何人も" | The claims rule of section 3 | Intended-use statement exists [R] | [S 24] |
| JIS X 8341-3:2016 (= WCAG 2.0) | Revision to match ISO/IEC 40500:2025 (WCAG 2.2) expected from 2026-04 onward | Design to WCAG 2.2 AA (09 already does) and state conformance in the JIS form | 09 targets WCAG 2.2 | [S 25 search summary]; revision **not verified** |

---

## 3. Is it a medical device in Japan?

**The test.** 薬機法 第2条 makes a program a device when it is intended for diagnosis, treatment or prevention; the
MHLW guideline (2021, revised 2023-03-31) asks two questions: the intended use (judged from labelling and advertising)
and the risk to life and health if it fails; one device function makes the whole program a device [S 24], [S 26]; the
intended-use statement already maps them as J1 and J2 [R `docs/plan/intended-use.md:34`].

**What the guideline and its case database say about programs like TrialBox** [S 26], [S 27]:

| Case (source) | What it does | Ruling | What it means for TrialBox |
| --- | --- | --- | --- |
| Guideline, non-device (2)① | "医療関係者が患者の健康記録等を閲覧等するプログラム" | Not a device | Showing record passages to research staff is this |
| Guideline, non-device (2)② | Hospital administrative work support | Not a device | Visit scheduling, logs, the delegation log |
| Case DB No.107 (2026) | "レセプトデータ抽出プログラム": narrows receipt data to people matching conditions **disclosed to the user** and outputs a list | **非該当** | The closest case to criteria-based patient finding. Keep the criteria visible to the user on every list |
| Case DB No.223 | Generative-model literature search | 非該当 | Retrieval with a model is not by itself a device |
| Case DB No.251 | Shows vitals and record data for bed control, no real-time monitoring | 非該当 | Display for operations |
| Case DB No.93 | Collects questionnaire answers in a research study | 非該当 | Data collection for research |
| Case DB No.74 | From EHR labs, a model computes a patient's risk of acute kidney injury and shows it to doctors, even "to identify high-risk patients for in-hospital work support" | **該当** (all four variants) | A per-patient risk score shown to a clinician is a device, even when framed as work support |
| Case DB No.243 | Compares EHR data to typical cases of a rare disease (hereditary angioedema) to support diagnosis | 未判断 (internal use only); "社外へ流通させる場合…医療機器に該当する可能性" | **"Find patients who may have undiagnosed rare disease X" is on the device side.** Sites with rare-disease work will ask for it |
| Guideline example 1)⑥ | Shows an identified individual's disease candidates or risk | Device | Never show "this patient may have X" |

**Conclusion** [O]: TrialBox's screening (criteria the user sees, applied to the record, a list of candidates with the
passages they rest on, the PI deciding) sits with case No.107 and the record-viewing category: **not a device**,
provided the claims stay as the intended-use statement words them [R `docs/plan/intended-use.md:16`]. Three things
would move it across: (a) a list for a condition the patient is not diagnosed with ("possible undiagnosed X"), (b) a
per-patient score or probability shown to a treating doctor, (c) marketing "見逃し防止" or "AIが適格患者を発見".
The forbidden-word list already holds 診断, 判定, 見逃し [R `docs/plan/intended-use.md:27`]; add **発見**, **予測**,
**リスク**, **疑い患者**, **未診断**, **スコア** for Japanese marketing and pages (card JP-4). The repository's R1 item
("a search of the guideline's case examples") is answered by the table above; the consultant still signs (P9r2
decision 21). The MHLW offers a free 該当性 consultation by mail [S 26b]; filing one with the claims table would turn
the position into a recorded answer (decision JP-D3).

**Wording that keeps it on the right side** (ja) [O]: 「研究計画書の選択・除外基準に照らして、記録上の該当状況を
一覧にします。参加の可否は治験責任医師が判断します。」 Avoid: 「適格患者を自動で抽出」, 「AIが判定」,
「見逃しを防ぐ」, 「疾患の可能性がある患者を発見」.

---

## 4. Japanese code systems and masters

06 gives the general picture (its rows 321–341). This table goes one level deeper and adds what a Japanese chart and
claim actually carry. "Ship" means it may sit in TrialBox's signed bundle; "site" means the hospital loads its own copy.

| Code system | Publisher; standard status | Licence, price | Update; format | Ship? | Maps to | TrialBox today | Needed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ICD10対応標準病名マスター (病名 + 修飾語) | MEDIS-DC; MHLW standard HS005 [S 28] | Free to download and use; use outside a medical institution or for distribution needs 使用許諾申請 [S 22] | Periodic (version 5.x); text files | Site | ICD-10 (WHO 2013) per 病名; レセプト傷病名コード | Loader reads 病名交換用コード → ICD-10, kept only if in the ICD-10-CM list (D-130) [R `services/adapter/licensed.py:8-10`, `libs/tb_common/refdata_jp.py:158-177`] | The **修飾語 master** (接頭語 "右", "急性", 接尾語 "の疑い", "術後") read as attributes, not lost; WHO-only ICD-10 codes kept (the CM-only rule drops Japanese WHO codes such as U-codes) |
| 標準歯科病名マスター | MEDIS; HS013 | As above (listed among the masters needing permission) | – | Site | ICD-10 | Nothing | Only if a dental study comes |
| 医薬品HOTコードマスター | MEDIS; HS001 | As above | Monthly [not verified]; HOT7/9/13 | Site | YJ, 薬価基準, レセプト電算, JAN, GS1 | HOT7/9/13 parsed [R `libs/tb_common/refdata_jp.py:278`] | Keep |
| 個別医薬品コード (YJ) | Listed as HS042 (2025); list provided via CAPS per the HELICS proposal [S 28], [S 29 summary] | Not verified | Monthly with 薬価 | Ship stems (own work) | ATC (own 56-row stem table), RxNorm via ingredient | `jp_yj_atc.csv` 56 rows [M 4]; demo `yj_to_atc.csv` 22 [M 4] | Grow to all ingredients on the 薬価 list (06 T6-3) |
| 薬価基準収載医薬品コード / レセプト電算医薬品コード | MHLW | MHLW PDL 1.0 for the 薬価 list [R register `mhlw-yakka`, 06] | Monthly-ish with revisions | Ship (薬価 list) | YJ | Column names read [R `libs/tb_common/refdata_jp.py:306-315`] | Keep |
| 一般名処方マスタ | MHLW | Not verified | With 薬価 revisions | Ship if PDL | Ingredient (一般名) | Nothing | Read 一般名 orders (common in outpatient prescriptions) to ingredient |
| 臨床検査マスター / JLAC10 | MEDIS (master), JSLM (code); HS014 | Not verified | – | Site | LOINC: **no public map** [R `libs/tb_common/refdata_jp.py:15-16`] | Site-file loader; demo map 14 rows [M 4] | The site's own JLAC10 map plus a per-analyte unit check |
| JLAC11 | JSLM; "厚労省標準規格として…位置付け" (2025-07); JLAC10 and JLAC11 run in parallel; analyte code starts with a letter | Not verified | 2026-04 publication note [S 30 summary] | Site | LOINC (none public) | Nothing | Accept both: a code starting with a letter is JLAC11 |
| 看護実践用語標準マスター | MEDIS; HS024 | Permission for distribution [S 22] | – | Site | – | Nothing | Only for nursing-record criteria (falls, pressure injury) |
| 症状所見マスター | MEDIS | Permission for distribution [S 22] | – | Site | – | Nothing | Symptom terms for notes; P3 |
| 手術・処置マスター | MEDIS | Permission [S 22] | – | Site | K codes | Nothing | Procedures as criteria ("prior gastrectomy") |
| 診療行為コード (医科点数表 K/J/D…) | MHLW 診療報酬情報提供サービス | Site copyright; reuse not licensed (06) | Biennial 改定 (April, even years) plus mid-term | Site | – (no international map) | Nothing | Procedures and tests from claims: K (手術), J (処置), D (検査), E (画像), G (注射), M (放射線) |
| レセプト電算 masters (傷病名, 修飾語, 医薬品, 特定器材, コメント) | MHLW, same service | As above | As above | Site | – | Receipt-code columns read in the MEDIS loader [R `services/adapter/licensed.py:95,130`] | Only with a claims feed (review 12) |
| 電子レセプト (UKE) record types | MHLW/支払基金 spec | Spec public; data is the hospital's | – | – | – | **No reader** [M 5] | IR (医療機関), RE (レセプト共通), HO/KO (保険/公費), SY (傷病名, with 修飾語 and 主病 flag, 疑い flag), SI (診療行為), IY (医薬品), TO (特定器材), CO (コメント), SJ (症状詳記) [record names from analyst's knowledge: **not verified** against the current spec] |
| DPC 様式1, EF, D, H, K files | MHLW DPC survey (事務局 changes yearly) | Spec public | Yearly spec | – | ICD-10 in 様式1 (主傷病, 入院契機, 医療資源最大, 併存症, 続発症) | **No reader** [M 5] | A DPC hospital has these files monthly; 様式1 gives coded diagnoses with roles, EF gives every order and act per day; a cheap, clean second source to the chart (review 12 owns the feed) [S 31 summary] |
| NDB, MID-NET | MHLW; PMDA | Application-based access; not for one hospital's screening | – | No | – | – | Out of scope [O] |
| JP Core (FHIR JP) | 日本医療情報学会 NeXEHRS FHIR working group; current 1.2.0 (2025-07-30); JP-CLINS 1.1.2-clins for 電子カルテ情報共有サービス | Licence not stated on the page | Yearly | Ship (package) | – | Pinned **1.1.0** [R `services/adapter/validate/jpcore.py:5`]; 1.2.0 diff tool exists [R `tools/jpcore_rules.py:15`] | Move to 1.2.0 and add **JP-CLINS** (the 3文書6情報 documents: 診療情報提供書 HS038, 退院時サマリー HS039, 健診結果 HS037) |
| SS-MIX2 | JAMI; HS026 | Spec public | – | – | – | Reader exists [R `services/adapter/sources/ssmix2/source.py`] | Review 12 |
| RFD (HS030) | IHE profile adopted as MHLW standard | – | – | – | – | Nothing | The standard way Japanese EHRs open an EDC form with pre-filled data; a match for TrialBox's prefill (P3) [O] |
| HS040 security disclosure sheet | JAHIS/JIRA "製造業者/サービス事業者による医療情報セキュリティ開示書" | – | – | – | – | Nothing | Fill it for procurement (card JP-21) |
| MANBYO (万病辞書) | NAIST Sociocom | CC BY 4.0 (06) | MANBYO_202106 | Ship | ICD-10 via MEDIS V4.04 | Not loaded (06 P1) | Load for note terms |
| CTCAE v5.0 JCOG 日本語訳 | JCOG | Free for non-commercial trials; commercial use needs a contract [R `libs/tb_common/refdata_jp.py:24-25`] | – | Site | CTCAE | Site-fetch loader | Keep; company 治験 sites need the contract |
| J-MIX | MEDIS (1990s data-item set) | – | – | – | – | – | Superseded by SS-MIX2 and JP Core in practice [O]; **not verified** |
| Units | JSCC/JCCLS conventions; creatinine mg/dL; HbA1c NGSP %; eGFR by the JSN equation | – | – | – | – | Unit ranges incl. HbA1c NGSP [R `libs/tb_common/labvalue.py:162`]; qualitative 陰性/陽性/(-)/2+ read [R `libs/tb_common/labvalue.py:312-347`]; **egfr_jsn** derived [R `services/criteria_compiler/review.py:72`] | Add (±), 1+…4+ in full-width, 定性 vs 定量 pairs; the site's own 臨床検査値一覧 as the reference-range source |

**What a real Japanese chart's structured data looks like** [O, from clinical practice; the SS-MIX2 specifics are
review 12's]: diagnoses are 病名 entries made by the doctor for billing as well as care (保険病名), each with start
date, 転帰 (治癒, 死亡, 中止, 移行), a 主病 flag and a 疑い flag; a drug started off-label often carries a 病名 that
justifies it, so **a 病名 alone is weak evidence** (an ulcer 病名 beside a proton-pump inhibitor; "DIC 疑い" before
heparin). Orders and results are the strongest evidence; notes confirm. TrialBox's rule "疑い never makes a
diagnosis true" [R `services/matching/proposed.py:11-13`] is right; add "a 病名 opened the same day as the drug it
justifies, and closed with 中止, is a billing 病名" as a review flag (card JP-10).

**Names, dates and character forms** [R], [M 2]:

| Item | Japanese practice | TrialBox today | Gap |
| --- | --- | --- | --- |
| 和暦 input | 令和/平成/昭和, R/H/S abbreviations, 元年, 平成31年5月1日 (after the era ended) | All read, with era-end checks [R `libs/tb_common/dates.py:33-73`] | None |
| 和暦 display | Patient-facing documents and many forms use 和暦; staff screens use either | ISO only; 0 ja strings with 令和 [M 1] | Site setting "日付の表示: 西暦 / 和暦 / 併記" for printed letters and forms (JP-16) |
| 氏名 | 姓 名 order; カナ (フリガナ) for identity; 様 in letters, さん on screens | Pseudonyms only; names never stored (02) | The guard misses カナ names and さん-suffixed names with 旧字体 (髙) [M 2] (JP-8) |
| 全角/半角 | Mixed in exports; half-width katakana in older systems; full-width digits | Headers matched after NFKC [R `services/adapter/licensed.py:17-19`]; 0 half-width kana in the catalogue [M 1] | Normalise note text with NFKC before rules (check that it is done everywhere) |
| 保険 | 保険者番号, 記号・番号, 枝番, 公費負担者番号 (難病, 小児慢性) | 保険者番号 and 被保険者番号 masked; **記号 not** [M 2] [R `libs/tb_common/phi_guard.py:301`] | Add 記号, 枝番, 公費負担者番号, 受給者番号 (JP-8) |
| 公費 as a clue | 難病 (指定難病) and 小児慢性 公費 numbers mark a certified rare disease | Not read | A criterion "certified 指定難病 X" can be answered from the 公費 record (review 12 to confirm it is in the feed) |

---

## 5. Japanese clinical language

**How Japanese charts are written** [O, clinician practice; sources for the corpora below]:

| Feature | Examples | Effect on screening |
| --- | --- | --- |
| SOAP in mixed script | S) 胸部不快感なし O) BP 132/80, HR 72 整, 心雑音(-) A) HT, DM コントロール良好 P) Do処方 | English and German-derived abbreviations sit inside Japanese sentences; `(-)` and `(+)` carry polarity |
| Abbreviations | HT, DM, HL, CKD, AF, CHF, ASO, RA, SLE, Ca (がん), Op (手術), Ope, Ent (退院), Kr. (Krankheit), Pat., Ns, Dr, Rp (処方), Do (同処方), BS, HbA1c, Cr, eGFR, PS | Ambiguity: Ca = cancer or calcium; RA = rheumatoid arthritis or right atrium; Op/Ope = operation; Ent = 退院 (from German Entlassung). The synonym list marks RA "ambiguous" already [R `libs/tb_common/refdata_src/ja_clinical_synonyms.csv:5`] |
| Negation | なし, 認めず, 認めない, 否定的, 陰性, (-), 指摘なし, 既往なし, 明らかな〜なし, 〜は否定できない (= cannot be excluded: **not** negation) | "否定できない" and "否定的" differ by one word and mean the opposite; TrialBox's chart rule already excludes "否定できず" from negation [R `services/sitesetup/charts.py:184-193`] |
| Uncertainty | 疑い, の疑い, 疑, r/o, s/o (suspicion of), 可能性, 〜か, 〜の可能性も, 示唆, 考えられる | 疑い as a 病名 suffix (修飾語) and in prose; MedTxt calls it "suspicious" [M 3] |
| Sections | 【主訴】【現病歴】【既往歴】【家族歴】【生活歴】【内服薬】【アレルギー】【身体所見】【検査所見】【評価】【方針】 | Family history must not count as the patient's: TrialBox's heading rule handles 【既往歴】 brackets [R `services/matching/excerpts.py:132`]; family terms 母, 父, 兄 [R `services/matching/inferred.py:106`] |
| Templates | 入院時記録, 退院サマリ (HS039 FHIR), 紹介状 / 診療情報提供書 (HS038), 返書, 手術記録, 読影レポート, 病理診断報告書, 看護記録 (SOAP or フォーカスチャーティング), 服薬指導記録 | Each has its own structure; 読影 and 病理 reports carry the strongest evidence for cancer criteria |
| Readings and conclusions | 読影: 所見 / 診断 (impression); 病理: 組織型, pT/pN, 断端, Grade; 癌 vs がん vs ca vs Krebs | Stage criteria are in 病理 and 読影 text, not in 病名 |
| Numbers | 全角 digits, 〜 ranges, 約, 以上/以下/未満 (以下 includes the bound; 未満 does not) | Criteria parsing and note values |
| Honorific-free style | Notes are terse, plain form | Prompts must not "politely" rephrase quotes |

**Measured: how the engines read real Japanese clinical text** [M 3]. On the public MedTxt corpus (215 case and
radiology reports, NTCIR-16 Real-MedNLP; CC BY 4.0 for the RR part), each tagged finding became "Patients with
<finding>." and was judged on the Japanese original and the clinician's English translation [R `eval/medtxt/README.md:1-6`].
"Block" means the engine said the criterion holds.

| Finding as written | n | Strongest single engine, ja | Same engine, en | Weakest usable engine, ja | What the clinician expects |
| --- | --- | --- | --- | --- | --- |
| Present | 659 | 91.8 % blocked | 96.5 % | 68.0 % | ~100 % |
| Stated absent (negated) | 349 | **21.5 % blocked** | 20.9 % | 10.6 % | ~0 % |
| Suspected (疑い) | 239 | **77.4 % blocked**; 32.2 % with a "suspected is not present" prompt | 71.5 %; 31.0 % | 33.1 % | 0 % (for "has X") |
| Not mentioned | 430 | 7.7 % | 7.2 % | 5.1 % | 0 % |

Reading [O]: Japanese is not much worse than English for these engines, but **both** are far from what a screening
step can rely on for negation and suspicion. The prompt variant halves the 疑い error; rules do better: the
`_strict` slice (tags contradicted elsewhere dropped) lowers the negated error to 12.3 % for one engine [M 3], which
says part of the "error" is annotation conflict. **The ladder for Japanese** (review 05's rungs):

1. **Rules first:** Japanese negation and uncertainty cues (the table above), section headings, family-history scope,
   (+)/(-) and 陰性/陽性. Most are partly in code [R `services/criteria_compiler/ir_extract/polarity.py:23`,
   `services/matching/inferred.py:82-110`]; they are scattered over four modules with different lists. One
   `ja_cues` table with tests on MedTxt's negated and suspected items (card JP-11).
2. **Terminology:** MANBYO for disease names in notes; the abbreviation table with ambiguity flags; MEDIS names (site).
3. **Small model:** a Japanese clinical NER with assertion (present / absent / suspected / family). Public bases: the
   MedTxt and Real-MedNLP sets, MANBYO. A trained model is plan 10 work (07 owns its validation).
4. **Large model:** only for what the rules leave "unknown", with the 疑い prompt as default for Japanese.

**Public Japanese clinical NLP resources** (licence as found):

| Resource | What | Licence / access | Mark |
| --- | --- | --- | --- |
| MedTxt-RR (radiology reports), MedTxt-CR (case reports) | NTCIR-16 Real-MedNLP; NER with certainty; English translations | RR and the test collection: CC BY 4.0; CR full set on request (J-Stage terms) | [S 32] |
| MANBYO 万病辞書 | Disease-name dictionary with ICD-10 | CC BY 4.0 (06) | 06 |
| Japanese medical LLMs (2026) | Medical continued-training variants of four open bases, released under MIT or Apache-2.0, one of them the base family TrialBox already serves; a from-scratch 10B model "研究目的で公開"; a red-teaming app and a **PII detection and routing program** for Japanese medical prompts | Model licences MIT / Apache-2.0 per the press release; the PII tool's licence **not verified**; trained on material generated from guidelines, exams and case reports, not on charts | [S 33] |
| SIP-jmed-llm (NII, LLM-jp base) | Japanese medical LLM series | Not verified | search summary only |
| Japanese de-identification corpora | – | None found that is public and licensed for reuse | **not verified** |

**For Japanese gold data (07)** [O]: MedTxt gives a free development set for negation and suspicion but not for trial
criteria; 07's frozen ja set (V3b) still needs synthetic Japanese charts written by Japanese clinicians (P9r2 decision
19). Write them with the features above: SOAP with abbreviations, 保険病名, 疑い 病名, a 読影 and a 病理 report, a
紹介状, and a gap where older records are outside the current chart.

---

## 6. The trial ecosystem in Japan, against TrialBox's life cycle

### 6.1 Kinds of study

| Kind | Law | Committee | Registry | Who runs the site work | Mark |
| --- | --- | --- | --- | --- | --- |
| 企業治験 | 薬機法, GCP | IRB (own or external; single IRB coming) | jRCT (治験 are registered there since 2020 [not verified]) | 治験責任医師, CRC (in-house or SMO), 治験事務局 | [S 10], [S 16] |
| 医師主導治験 | As above; the investigator is "自ら治験を実施する者" | IRB | jRCT | Investigator plus an ARO or CRO | [S 10] |
| 製造販売後臨床試験 | GCP | IRB | jRCT | As 治験 | [S 10] |
| 使用成績調査, 特定使用成績調査, 全例調査 | GPSP | Site contract; IRB per site SOP | – | CRC or doctor; sponsor's EDC | [SN], [O] |
| 特定臨床研究 | 臨床研究法 | CRB | jRCT | 研究責任医師 | [S 15] |
| Other research (intervention, observational) | 生命・医学系指針 | Ethics committee (一括審査 for multicentre) | jRCT, UMIN-CTR | 研究責任者 | [S 13] |
| 先進医療B | 評価療養 + research rules | CRB-approved research | jRCT | 研究責任医師 | [S 23] |
| Registry | 指針 | Ethics committee | UMIN-CTR or none | Registry office | – |

### 6.2 Registries and their data

| Registry | Access | Terms | TrialBox today | Mark |
| --- | --- | --- | --- | --- |
| jRCT | Search pages with a download of results; no public API found | Search summary: "プログラムを使った自動操作などによる意図的な大量データ収集" counts as beyond personal use; bulk use by permission of the help desk | Hospital downloads, TrialBox loads (`parse_jrct`) [R `libs/tb_common/refdata_jp.py:593-600`], D-140, D-317 | Both jrct.mhlw.go.jp (403) and jrct.niph.go.jp (503) refused this session; terms from a search summary only: **not verified** |
| UMIN-CTR | Text-file download "UMIN-CTRの最新データのテキストファイルによるダウンロード提供を開始しました"; a snapshot link; no API | No reuse licence stated; copyright notice only | No loader | [S 34] |
| JAPIC-CTI, JMACCT | Older registries | – | A JAPIC label exists in the catalogue [M 1] | **not verified** whether still active |
| ClinicalTrials.gov | Japanese company trials are usually also there | – | Loader exists (06) | – |

### 6.3 A site's work from request to first patient, and who pre-screens

| Step | Japanese practice (the first site where public, [SN]) | TrialBox today | Gap | Mark |
| --- | --- | --- | --- | --- |
| 1. Feasibility (施設選定調査) | Sponsor mails a questionnaire; the site answers "how many patients a year" | Feasibility counts from coded data, no model [M 1 `feas.method`] | Answer in the sponsor's questionnaire shape; Japanese 年間患者数 per 年度 (April–March) | [SN] |
| 2. Selection visit, 治験責任医師 chosen | Web meetings common | – | – | [SN] |
| 3. 治験依頼書 (書式3), 履歴書 (書式1), 分担医師・協力者リスト (書式2) | 統一書式 (latest 令和4年11月30日) | Delegation log covers 書式2's content [R 02] | Print the delegation log as 書式2 | [S 35 summary], [O] |
| 4. IRB review (書式4 依頼, 書式5 結果) | External IRB; the 病院長 asks and notifies | IRB record, free text | External IRB fields; 書式4/5 dates; the 病院長's instruction (指示・決定通知) | [S 10], [SN] |
| 5. 契約 | Paper, mailed, 押印 | – | Nothing to build; track the date | [SN] |
| 6. Department meetings, start-up | 薬剤部, 医事課 (billing split 治験 vs 保険), 臨床検査部 | – | 医事課 needs the list of enrolled patients' 治験期間 for 保険外併用療養費 billing [O] | [SN] |
| 7. Pre-screening | Today: CRC reads the 電子カルテ by hand, often from the PI's outpatient list, or a DWH query by IT [O]; the IRB-approved recruitment method governs | TrialBox's core | The 利用目的 line (2.1); the list visible only to 書式2 staff | [O] |
| 8. Approach | Through the 主治医 at the next outpatient visit; Japanese patients expect their own doctor to raise it [O] | Referral to the treating doctor [R 02 1.2]; 58 ja strings use 主治医 [M 1] | Align the referral letter with HS038 (診療情報提供書) layout [O] | – |
| 9. 同意 | 説明文書・同意文書 (IRB-approved), written; 代諾 and アセント for children; CRC 補助説明 | Consent record with 説明者/補助説明者 [R `services/datacore/builtin/forms.csv:13-21`] | 代諾者 and relation (GCP 第50条3項); アセント field | [S 10] |
| 10. Screening and 症例登録 | Sponsor's registration (IWRS) and EDC | EDC prefill | – | – |
| 11. Visits, 負担軽減費 | A fixed payment per visit (often ¥7,000 to ¥10,000 per visit) to the participant [O; not verified as a figure] | Nothing | A per-visit "負担軽減費 paid" flag and a monthly list for the accounting office | [O] |
| 12. SAE (書式12–15, 19, 20), 逸脱 (書式8) | Paper with seals in principle at many sites | SAE register; deviation log | Print as 書式12-shaped PDF | [SN] |
| 13. Close, 記録保存 | 記録保存責任者; retention to the sponsor's notice | Close and archive | 記録保存責任者 role; retention date from the sponsor's 書式18 notice | [S 10] |

### 6.4 Roles: TrialBox's against Japan's

| Japanese role | Who | TrialBox role | Mismatch | Mark |
| --- | --- | --- | --- | --- |
| 実施医療機関の長 (病院長) | Approves the trial, chooses the IRB, signs 指示・決定 | None | Add as an approver step, not an account (often delegated to 治験事務局) | [S 10] |
| 治験事務局 (治験管理室) | Runs forms, IRB liaison, contracts, archive | "research office" viewer, read-only | Needs write rights on study set-up, IRB records, documents; no patient rows before consent | [S 10], [R 02 1.1] |
| 治験審査委員会 / CRB / 倫理審査委員会 | Committee | IRB record | Three kinds, with 設置者 and contract | [S 10], [S 15], [S 13] |
| 研究機関の長 | Permits non-治験 research | None | Permission record per study | [S 14] |
| 治験責任医師 / 治験分担医師 | PI / sub-I | Investigator (PI / sub-I) | ja label correct for 治験; 研究責任者 / 研究分担者 for others (02 J-7) | [R `services/console/i18n.py:429`] |
| 治験協力者 / CRC (院内 or SMO) | Coordinator; SMO CRCs are contractors | Coordinator | A field "employer: hospital / SMO (name)"; the SMO contract on file; 0 strings say 治験コーディネーター [M 1] | [S 10] |
| 治験薬管理者 (pharmacist) | Drug accountability | None (02: out of scope) | Keep out; name only | [S 10] |
| 記録保存責任者 | Archive | None | Role on the close step | [S 10] |
| モニター / 監査担当者 (CRA) | 直接閲覧 | CRO monitor | Matches; 直接閲覧 visits booked through 治験事務局 [O] | [S 10] |
| 医事課 | Billing split | None | A list, not an account | [O] |
| 個人情報保護管理者 | Privacy office | Privacy office | Matches | – |

**Tools Japanese sites use** [O; not verified as market facts]: sponsors' EDCs (global platforms) for 治験;
REDCap in academia: about 60 Japanese non-profit institutions by 2021 and a Japan REDCap Consortium
[S 36]; at least one university hospital offers REDCap to other institutions as a service under a published contract template [S 36]. REDCap's own
licence is for non-profit use [not verified for a 医療法人]; **a 医療法人 may need to use a university's REDCap or its
own Vanderbilt licence** (decision JP-D4). Electronic trial-document clouds (治験クラウドシステム) are in use under
site SOPs [SN].

---

## 7. Culture, customs and sensitivities in the product

### 7.1 The ja catalogue, counted [M 1]

| Check | Count (of 3,099 ja strings) | Reading |
| --- | --- | --- |
| Missing ja (falls back to English) | 0 | Complete |
| Sentence ends in です/ます form | 1,264 of 1,502 sentence-like strings (84 %) | Polite register, good |
| Strings mixing polite and plain clause ends | 43 (e.g. `login.failed`, `feas.validation`) | Fix in the reader pass |
| Plain-form ends (`〜ない`, `〜する`) | 84 | Labels and error lines; some read curt ("この様式は REDCap のこのイベントにない：送信しません") |
| 被験者 / 参加者 / 治験参加者 / 研究対象者 | 34 / 14 / 0 / 0 | Old GCP word dominates; the 2027 word and the 指針 word are absent |
| 患者さん / 患者様 | 37 / 0 | さん is the modern hospital norm; good |
| CRC / 治験コーディネーター | 57 / 0 | Fine for staff; spell out once in help |
| 治験事務局 / 病院長 / 研究機関の長 / 実施医療機関 | 3 / 0 / 0 / 1 | Japanese roles missing (6.4) |
| オプトアウト / 拒否 | 20 / 16 | The word patients see should be 「研究への利用を希望されない場合」, not オプトアウト [O] |
| 辞退 / 撤回 / 同意撤回 | 7 / 2 / 0 | "中止・撤回" merges stopping by the doctor with withdrawal by the person; split (7.2) |
| 令和 / 和暦 shown | 0 / 4 (help mentions it) | No 和暦 display |
| 祝日 / 年度 | 0 / 0 | No holiday or fiscal-year concept |
| 個人情報 / 要配慮 | 0 / 0 | The privacy words a Japanese privacy officer looks for are absent |
| モデル / AI / 人工知能 | 50 / 8 / 0 | Fine for staff; never in patient text |
| 押印 / FAX | 0 / 0 | Expected (no seals in software); but print layouts must leave the seal box (7.2) |
| Full-width ASCII in strings | 900 strings | Mostly full-width brackets and colons, correct in Japanese text; check no full-width digits in codes |
| ja identical to en with Latin words | 12 (e.g. `dc.source.redcap`, `refdata.src.japic_cti`) | Proper names; fine |

### 7.2 Customs and what the product should do

| Topic | Japanese practice | Product rule | Mark |
| --- | --- | --- | --- |
| Register | Staff screens: です/ます, no 尊敬語 overload; patient documents: 丁寧語 plus 謙譲語 for the hospital ("ご説明いたします", "お知らせください") | Staff ja stays as is; patient-facing templates (letters, opt-out notice, visit reminder) written separately by a Japanese writer | [O] |
| Words for the person | 治験: 被験者 → 治験参加者 (2027); 指針: 研究対象者; patients themselves: 患者さん, letters: 〇〇様 | One term table per study type, switched by the study's kind (with 02 J-7) | [S 16], [S 14] |
| Names | 姓 名, カナ, 様 | Pseudonyms in the box; printed letters to the 主治医 use the pseudonym and the chart number only | [O] |
| Dates | 和暦 on patient letters and many forms; 西暦 on trial documents (sponsors work in 西暦) | Setting, default 西暦 for staff and trial documents, 和暦 or 併記 for patient letters | [O] |
| Seals and approvals | 押印 still required for some 統一書式 at many sites; 稟議 for purchases | Printed forms keep a seal box; no electronic "seal" imitation; approvals in TrialBox are records, not 稟議 | [SN], [O] |
| Paper and FAX | Contracts by post [SN]; referrals by paper; FAX for some sponsors | Printable PDFs for every form a Japanese site files; never a FAX gateway | [O] |
| Cancer disclosure | Disclosure is now usual, but family-first disclosure persists for some elderly patients; the 主治医 knows [O] | A candidate list must never be the way a patient or family learns a diagnosis: approach only through the 主治医; a "主治医 says not now" outcome | [O] |
| Psychiatry, HIV, hepatitis, genetics | Highest sensitivity; such studies run at general hospitals too [SN] | A study can mark itself sensitive: list visible to the PI only; notes masked by default | [O] |
| Refusal | Patients rarely say no directly ("考えておきます", "家族と相談します") | Outcome codes: 「保留（家族と相談）」 distinct from 「辞退」; no repeat approach within a set time | [O] |
| Withdrawal | 同意撤回 (the person) vs 中止 (the doctor) vs 脱落 (lost) | Three outcomes, each with the data-use answer (GCP and 指針 both ask what happens to collected data) | [O] |
| Accessibility | JIS X 8341-3:2016 (WCAG 2.0); revision to WCAG 2.2 expected | Conformance statement in the WAIC form | [S 25] |
| Typography | JLReq; 09's DS-2 | As 09 | 09 |
| Holidays | Cabinet Office CSV (`syukujitsu.csv`, CP932, covers 2027: 17 rows) plus 年末年始 | Working days in the product today are Monday to Friday only [R `services/console/notify.py:212`]; the holiday list exists only for plan dates [R `tools/gen_calendar.py:8-10`] | [M 6] |
| Fiscal year | 年度 April–March; IRB yearly reports, hospital counts and budgets by 年度 | Reports by 年度 | [O] |
| Outpatient days | A PI's 外来 is on fixed weekdays; 当直 nights | A PI's clinic days in the profile; tasks due on clinic days | [O] |
| Support | Japanese-language support, phone or mail, during 平日 9–17; written replies | A Japanese support contract and a named contact | [O] |
| Documents and contracts | Japanese contract governs; 仕様書, 見積書, 納品書, 検収 | Japanese procurement pack (JP-21) | [O] |
| Procurement | HS040 security disclosure sheet; 責任分界表; on-site installation; a domestic partner for maintenance | As above | [S 28], [S 17] |

---

## 8. The Japan profile: what "fulfil the Japanese ecosystem at best" means

Each card is one switchable part of a "Japan site profile" (site setting `country=JP` plus per-study kind).

| # | Card | Contents |
| --- | --- | --- |
| P1 | **Legal pack** | 利用目的 line for the 院内掲示; opt-out notice template (指針 2026, 第8の7 items) in patient Japanese; per-study-type memo (2.1); access rule "書式2 staff only"; PPC leak report path |
| P2 | **Study kinds** | 企業治験, 医師主導治験, 製造販売後臨床試験, GPSP survey, 特定臨床研究, 指針 research, 先進医療B, registry; each sets the committee kind, the words, the forms, the registry |
| P3 | **Committees** | External IRB (設置者, contract, SOP and roster versions), CRB, ethics committee with 一括審査; 研究機関の長 permission; 病院長 指示・決定 |
| P4 | **Roles** | 治験事務局 (write, no patient rows before consent), 記録保存責任者, CRC employer (hospital / SMO name), 治験薬管理者 named only |
| P5 | **Words** | Term table per study kind; 治験参加者 switch for 2027; patient-letter register; forbidden marketing words (発見, 予測, 未診断, スコア) |
| P6 | **Forms** | 統一書式 numbers on printed outputs: 書式2 from the delegation log, 書式12-shaped SAE print, 書式8 deviation print; seal box kept |
| P7 | **Masters** | MEDIS 病名 + 修飾語, HOT, YJ, 一般名, JLAC10/11, 手術・処置, site-loaded with version and acceptance record; MANBYO shipped |
| P8 | **Chart reading** | ja cue table (negation, 疑い, sections, family), abbreviation table, 保険病名 flag, 公費 as a rare-disease clue, older-records boundary |
| P9 | **Dates and calendar** | 西暦/和暦/併記; Japanese holidays and 年末年始 in working days; 年度 reports; PI 外来 days |
| P10 | **Privacy guard** | カナ names, 旧字体, 記号・番号・枝番, 公費 and 受給者番号 |
| P11 | **Patient approach** | Through the 主治医; outcomes 保留 (family), 辞退, 主治医 not now; 代諾 and アセント |
| P12 | **Money** | 負担軽減費 per visit; a monthly list for 医事課 (治験期間 for billing) |
| P13 | **Registries** | jRCT and UMIN-CTR loaders from the hospital's downloads; jRCT number on the study |
| P14 | **Interoperability** | JP Core 1.2.0, JP-CLINS documents, SS-MIX2 (review 12), RFD (HS030) later |
| P15 | **Procurement and security** | HS040 sheet, 責任分界表, 安全管理GL 7.0 checklist (2FA by 令和9年度), Japanese support and contract |
| P16 | **Accessibility and type** | JIS X 8341-3 statement; 09's ja typography |

---

## 9. Gap table: today, needed, evidence

| # | Area | What the product does today | What is needed | Evidence |
| --- | --- | --- | --- | --- |
| G1 | Legal basis | One sentence of basis in the plan; the Japan memo struck (T-646) | The pack P1 | [R `docs/plan/28-master-plan-v6.md:470,1600`], [S 9], [S 11] |
| G2 | 2026 指針 | Opt-out register; no 研究機関の長 | 研究機関の長 permission; 一括審査 record; 研究対象者 words | [S 13], [M 1] |
| G3 | GCP amendment | 被験者 in 34 strings | Term switch to 治験参加者 for 2027; single-IRB and SMO-oversight fields | [S 16], [M 1] |
| G4 | External IRB | Free-text IRB record | 設置者, contract, versions | [S 10], [SN] |
| G5 | Japanese roles | No 治験事務局 write role, no 病院長 step | P4 | [S 10], [R 02 1.1] |
| G6 | Device claims | Forbidden words incl. 診断, 判定, 見逃し | Add 発見, 予測, 未診断, スコア; record the No.107 / No.74 / No.243 reasoning | [R `docs/plan/intended-use.md:27`], [S 27] |
| G7 | MEDIS 修飾語 and WHO-only codes | 病名 → ICD-10 kept only if in ICD-10-CM | 修飾語 as attributes; WHO ICD-10 kept | [R `services/adapter/licensed.py:8-10`] |
| G8 | JLAC11 | JLAC10 only | Accept both | [S 30] |
| G9 | Claims and DPC | No reader | With review 12: 様式1 and EF as a second source | [M 5] |
| G10 | JP Core | 1.1.0 | 1.2.0 and JP-CLINS | [R `services/adapter/validate/jpcore.py:5`], [S 37] |
| G11 | Guard | カナ names, 旧字体 + さん, 記号 pass | Fixed | [M 2] |
| G12 | Japanese negation and 疑い | Cues in four modules | One tested cue table; 疑い prompt default | [M 3], [R] |
| G13 | Abbreviations | 70-row synonym list | Abbreviation table with ambiguity (Ca, RA, Ent) | [M 4] |
| G14 | 和暦 display | None | Setting | [M 1] |
| G15 | Holidays, 年度 | Mon–Fri only | Cabinet Office list in the box's calendar | [R `services/console/notify.py:212`], [M 6] |
| G16 | Approach and outcomes | Referral; outcomes 辞退, 中止・撤回 | 保留 (family), 主治医 not now; 同意撤回 vs 中止 split | [M 1] |
| G17 | 代諾, アセント | Not in the consent form | Fields | [S 10], [S 16] |
| G18 | 負担軽減費, 医事課 list | None | P12 | [O] |
| G19 | 統一書式 prints | None | P6 | [SN] |
| G20 | Older-records boundary | Not known to the box | A per-site "record starts" date per source | [SN] |
| G21 | Procurement | English security docs | HS040, 責任分界表, Japanese pack | [S 28], [S 19] |
| G22 | UMIN-CTR | No loader | Loader from the text download | [S 34] |

---

## 10. Cards for plan 10

Size: S a day or less, M a few days, L a week or more. Lane guesses as in P9r2 (A2 data and terminology, J journeys
and wording, Int integrator, H harness).

| Card | What | Size | Lane | Waits for | Proving test or measurement |
| --- | --- | --- | --- | --- | --- |
| 11/JP-1 | Japan legal pack I: the 利用目的 line, the 指針 2026 opt-out template (第8の7 items) in patient Japanese, the study-kind memo of 2.1, the access rule, the PPC leak path; files under `docs/security/` and a printable notice | M | J, Int | Counsel's reading (P9r2 decision 21) | Counsel's note filed; the notice prints from the box in ja |
| 11/JP-2 | Access rule in code: a pre-consent candidate list is visible only to the study's PI, sub-I and coordinators on its delegation log (書式2 shape); the 治験事務局 sees counts | S | J | – | A permission-matrix test per role; a 治験事務局 account sees no patient row |
| 11/JP-3 | Committees: kinds IRB / CRB / 倫理審査委員会; external flag, 設置者, contract date, SOP and roster versions; 一括審査 for multicentre; 研究機関の長 permission date; 病院長 指示・決定 date | M | J | – | A 指針 study cannot start screening without the permission date; a 治験 without the 病院長 date shows a warning |
| 11/JP-4 | Device-claims guard for Japanese: add 発見, 予測, 未診断, スコア, 疑い患者 to `FORBIDDEN` with allowed negations; the No.107 / No.74 / No.243 reasoning in `intended-use.md` | S | J | – | The wording check fails on a seeded string; R1 marked answered pending the consultant |
| 11/JP-5 | Japanese term set per study kind (治験参加者/被験者 switch dated 2027-04 or by the amendment's actual date, 研究対象者, 研究責任者, 治験協力者/CRC, 同意撤回/中止/脱落), with 09 DS-16 and 02 J-7 | M | J | Clinician readers (P9r2 35) | 0 strings with a refused term per study kind; readers' sign-off |
| 11/JP-6 | Mixed-register fixes: the 43 strings; plain-form error lines made polite | S | J | JP-5 | The counter of [M 1] reports 0 mixed strings |
| 11/JP-7 | Patient-facing Japanese templates (opt-out notice, approach letter via the 主治医, visit reminder) in 丁寧語/謙譲語 with 様 | S | J | JP-1 | A Japanese reader's sign-off |
| 11/JP-8 | Guard: katakana names (with or without 様/さん), 旧字体 (髙, 﨑, 齋, 邊) names with さん/様, 記号・番号・枝番, 公費負担者番号, 受給者番号 | M | A2 | – | The 10 probes of [M 2] plus 40 more synthetic lines: 0 unmasked identifiers; no regression on the zh-TW and en guard tests |
| 11/JP-9 | MEDIS 修飾語 master read as attributes (side, acuity, 疑い, 術後); WHO-only ICD-10 codes kept as WHO codes rather than dropped | M | A2 | – | A synthetic MEDIS file with 20 modifiers: 疑い never asserts; 右/左 kept; a U-code kept |
| 11/JP-10 | 保険病名 review flag: a 病名 opened the same day as a drug it typically justifies and closed with 中止 is shown as "billing diagnosis?" to the reviewer | M | A2 | Review 12 (the feed carries 転帰 and dates) | On a synthetic chart set, every seeded billing 病名 is flagged; no flag on 30 true diagnoses |
| 11/JP-11 | One ja cue table (negation, uncertainty, 否定できない, (+)/(-), sections, family) used by `polarity.py`, `inferred.py`, `charts.py`, the guard | M | A2 | – | MedTxt negated and suspected items: the rules alone reach a stated error target (proposed: negated blocked ≤ 5 %, suspected ≤ 10 %) on the RR set |
| 11/JP-12 | Japanese abbreviation table (≥ 200 entries) with ambiguity flags and section-aware expansion (Ca, RA, Ent, Op, Rp, Do) | M | A2 | – | Each ambiguous entry sends to review, never decides; a test per entry |
| 11/JP-13 | Default the "suspected is not present" prompt for ja note questions | S | A2 | – | MedTxt ja suspected blocked rate on the default path ≤ 35 % (from 77 %) |
| 11/JP-14 | 和暦 display setting (西暦 / 和暦 / 併記) for printed letters and forms | S | J | – | A date in 平成31年4月30日 and 令和元年5月1日 prints right |
| 11/JP-15 | Japanese holidays and 年末年始 in the box's working-day function (Cabinet Office CSV in the signed bundle, yearly), used by the digest, SAE reminders and visit windows | M | J, A2 | – | A digest is not sent on 2027-01-01 or 2027-11-23; a visit window skips holidays when the protocol says working days |
| 11/JP-16 | 年度 (April–March) in yearly reports and feasibility answers | S | J | – | The yearly report for 年度2026 counts 2026-04-01 to 2027-03-31 |
| 11/JP-17 | Roles: 治験事務局 (write on set-up, committees, documents; no patient rows before consent), 記録保存責任者, CRC employer field (hospital / SMO) | M | J | JP-2 | Matrix tests; an SMO CRC without a contract date on file is refused screening rights |
| 11/JP-18 | Printed 統一書式-shaped outputs: 書式2 from the delegation log; SAE and deviation prints with a seal box | M | J | JP-17 | The 書式2 print matches the 令和4年 layout's fields |
| 11/JP-19 | Approach outcomes: 保留（家族と相談）, 主治医判断で見送り, 辞退; withdrawal split 同意撤回 / 中止 / 脱落 with the data-use answer | S | J | JP-5 | Outcome codes in the screening log export; no re-approach before the set date |
| 11/JP-20 | 代諾者 (with relation) and アセント fields on the consent record | S | J | – | GCP 第50条3項 items recorded; a minor's record without アセント warns |
| 11/JP-21 | Japanese procurement and security pack: HS040 disclosure sheet, 責任分界表, 安全管理GL 7.0 checklist (2FA plan by 令和9年度), support terms | L | Int | – | The hospital's IT accepts the pack (the site's checklist signed) |
| 11/JP-22 | JP Core 1.2.0 and JP-CLINS (HS037–HS039 documents) in the validator; JLAC11 accepted beside JLAC10 | L | A2 | Review 12 | 1.2.0 diff shows no unread element; a JLAC11 code (letter-initial) is read |
| 11/JP-23 | UMIN-CTR loader from the text download; jRCT number field on the study | S | A2 | – | A cassette of 20 UMIN rows loads; terms recorded |
| 11/JP-24 | Older-records boundary: a per-source "record starts" date; criteria with a look-back past it say "record incomplete" not "absent" | L | A2, J | Review 12 | A synthetic patient with history only before the boundary is "unknown", never "not matched" |

Count: **24 cards: 10 S** (JP-2, 4, 6, 7, 13, 14, 16, 19, 20, 23), **11 M** (JP-1, 3, 5, 8, 9, 10, 11, 12, 15, 17,
18), **3 L** (JP-21, 22, 24).

---

## 11. Decisions only the owner can make

| # | Decision | Recommendation | Cost |
| --- | --- | --- | --- |
| JP-D1 | Engage a Japanese regulatory reader now (APPI, 指針 2026, GCP amendment, device claims) rather than "before a Japanese site" (P9r2 21): the site is now known | **Yes, now**; scope: section 2.1 and 3 of this page, one memo | By quote |
| JP-D2 | Ask the first site to add the 利用目的 line to its 院内掲示 and website before any real data | **Yes**: one line, the strongest legal footing for 治験 screening | None |
| JP-D3 | File a free MHLW 該当性 consultation with the claims table | **Yes, after JP-4**: a recorded answer protects the position and the hospital | Staff time |
| JP-D4 | REDCap at a 医療法人: use a university's REDCap service, or the site's own licence | **Ask the site what it uses**; prefer its existing arrangement | Not verified |
| JP-D5 | Japanese term for the person in 2027: switch to 治験参加者 on the amendment's date, or now | **On the amendment's date**, with a setting to switch early | None |
| JP-D6 | Patient-facing Japanese text written by a paid Japanese writer, reviewed by the clinician readers | **Yes** | Small, by quote |
| JP-D7 | Rare-disease "possible undiagnosed" lists (case No.243) | **No** in 1.0: device side | – |
| JP-D8 | Japanese support: a domestic partner for on-site work and phone support in Japanese | **Yes** before go-live; hospital procurement expects it | By contract |

---

## 12. What the owner or the first site must supply (exact items)

| # | Item | From | Why |
| --- | --- | --- | --- |
| 1 | The hospital's current 個人情報の利用目的 (院内掲示 text and web page) | The site's privacy office | To write the one added line (2.1) |
| 2 | The 治験 SOP's annexes and the 電磁化 SOP's 別紙1 (blank forms only) | 治験管理室 | Form shapes (P6) |
| 3 | Whether the site uses an SMO, which one, and whether the SMO contract covers pre-consent chart review | 治験管理室 | Access rule (JP-2, JP-17) |
| 4 | The external IRBs used now (names, 設置者) | 治験管理室 | Committee record (JP-3) |
| 5 | The ethics committee's SOP for opt-out research and its notice template | 臨床研究支援室 | JP-1 template matched |
| 6 | Sample exports with **synthetic** content: 病名 list with 修飾語 and 疑い flags; order and lab export (JLAC10 or local codes); drug master excerpt (local + YJ + HOT columns); a DPC 様式1 and EF file layout (headers and three fake rows); a SS-MIX2 sample (review 12) | 情報システム部 | Readers tested on real shapes |
| 7 | The site's MEDIS master versions in use and whether the hospital applied for 使用許諾 | 情報システム部 | Site-load record (P7) |
| 8 | The date and scope of any earlier system or merged hospital whose records are only partly in the current chart | 情報システム部 | JP-24 |
| 9 | The hospital's 臨床検査値一覧 confirmed current, and units per test | 臨床検査部 | Units and ranges |
| 10 | The IT department's security checklist for new systems (HS040 or own) and its 責任分界 template | 情報システム部 | JP-21 |
| 11 | Contacts: 治験管理室 lead, 臨床研究支援室 lead, privacy officer, IT lead, one PI and one CRC for usability | The site | Walks and sign-offs |
| 12 | Whether the site is a DPC hospital and whether it submits 様式1/EF monthly | 医事課 | G9 |
| 13 | The owner's confirmation of "SSI" (株式会社ソフトウェア・サービス) | Owner | Review 12 and section 1 |
| 14 | Which REDCap (own licence, a university's) the site would use | 臨床研究支援室 | JP-D4 |

---

## 13. What this document did not verify

- The GCP amendment's promulgation, final text and in-force date (e-Gov still shows the old text; PMDA's slides and
  trade press only); the exact direction of the 原資料/原記録 rename in the PMDA table (the text extraction's column
  order is ambiguous).
- The GCP 運用通知's current text (documents to the IRB, 治験協力者 definition); the ER/ES 指針 text; the eConsent
  guidance text (search summary only); GPSP ordinance text; 臨床研究法's 2024 amendment details; 患者申出療養.
- Whether 委託 to a foreign vendor falls under APPI 第28条 (PPC guidance not opened); whether the site's research centre
  could be a 学術研究機関等.
- jRCT's terms and download (both hosts refused); JAPIC-CTI's status.
- 診療報酬情報提供サービス (host not reachable from this session: `www.shinryohoshu.mhlw.go.jp` must be allowed in the
  session's network settings to check); the 電子レセプト record names in section 4 are from the analyst's knowledge.
- DPC file layouts for 令和8年度 (only the 2023 explanatory document's title seen in search); whether the site is a DPC
  hospital.
- JLAC11 licence and download; HOT and YJ update cadence; the YJ list (HS042) publisher's terms; JP Core's licence;
  J-MIX status; the 一般名処方マスタ's licence.
- The provider-side guideline 第2.0版 body text; the security guideline's other three parts.
- JIS X 8341-3's revision status; REDCap licence terms for a 医療法人.
- The first site: electronic chart vendor, SMO use, CRB, DPC status (details in the site notes).
- Japanese medical LLMs' model cards and the PII tool's licence (press release only); SIP-jmed-llm terms; any public
  Japanese clinical de-identification corpus.
- 負担軽減費 typical amounts; Japanese sites' EDC market shares; how pre-screening is done today at Japanese sites
  (practice described as opinion).
- No Japanese clinician read this page.

---

## 14. Sources (opened 2026-11-18 unless marked)

| n | Source | Link | Terms |
| --- | --- | --- | --- |
| 9 | 個人情報の保護に関する法律 (e-Gov API, law 415AC0000000057) | https://laws.e-gov.go.jp/api/1/lawdata/415AC0000000057 | e-Gov law data, government work |
| 10 | 医薬品の臨床試験の実施の基準に関する省令 (409M50000100028) | https://laws.e-gov.go.jp/api/1/lawdata/409M50000100028 | As above |
| 11 | 医療・介護関係事業者における個人情報の適切な取扱いのためのガイダンス (令和8年4月一部改正) | https://www.mhlw.go.jp/content/001470633.pdf | Government publication |
| 13 | 生命・医学系指針 一部改正 新旧対照表 (令和8年8月27日, applies 2026-12-01); MEXT press release | https://www.mhlw.go.jp/content/001743403.pdf ; https://www.mext.go.jp/b_menu/houdou/mext_01679.html | As above |
| 14 | 生命・医学系指針 本文 (令和8年8月27日一部改正) | https://www.mhlw.go.jp/content/001743409.pdf | As above |
| 15 | 臨床研究法 (429AC0000000016) | https://laws.e-gov.go.jp/api/1/lawdata/429AC0000000016 | As above |
| 16 | PMDA 信頼性保証部説明会 2026初夏 (GCP amendment draft, definitions table) | https://www.pmda.go.jp/files/000281180.pdf | PMDA publication |
| 17 | 医療情報システムの安全管理に関するガイドライン 第7.0版 システム運用編 | https://www.mhlw.go.jp/content/10808000/001716295.pdf | Government publication |
| 18 | 同 保守委託機関編 | https://www.mhlw.go.jp/content/10808000/001716297.pdf | As above |
| 19 | 提供事業者ガイドライン 第2.0版 press release (2025-03-28) | https://www.soumu.go.jp/menu_news/s-news/01ryutsu06_02000427.html | Search result; body not opened |
| 20 | 次世代医療基盤法 (429AC0000000028) | https://laws.e-gov.go.jp/api/1/lawdata/429AC0000000028 | e-Gov |
| 21 | eConsent guidance (令和5年3月30日), PMDA copy | https://www.pmda.go.jp/files/000251967.pdf | Search summary only |
| 22 | MEDIS 標準マスター 利用について | https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html | MEDIS-DC |
| 23 | MHLW 先進医療の概要 (70 technologies, 2026-10) | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryouhoken/sensiniryo/index.html | Government |
| 24 | 薬機法 (335AC0000000145) 第2条, 第68条 | https://laws.e-gov.go.jp/api/1/lawdata/335AC0000000145 | e-Gov |
| 25 | JIS X 8341-3 revision (search summary: issoh.co.jp, MLIT) | https://www.mlit.go.jp/sogoseisaku/barrierfree/content/001903670.pdf | Search summary only |
| 26 | プログラムの医療機器該当性に関するガイドライン (令和5年3月31日) and 判断事例 | https://www.mhlw.go.jp/content/11120000/001082227.pdf ; …/001082229.pdf | Government |
| 26b | Consultation page | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000179749_00004.html | Government |
| 27 | 医療機器プログラム事例データベース (updated 2026-09-08, corrected 2026-10-14) | https://www.mhlw.go.jp/content/11120000/001759227.xlsx | Government |
| 28 | 厚生労働省標準規格 list (HS001–HS043, 2025 revision) | https://www.mhlw.go.jp/content/10800000/001389373.pdf | Government |
| 29 | HELICS HS042 report (search summary) | https://square.umin.ac.jp/helics/html/files/HS042/HS042_report_20240826.pdf | Search summary only |
| 30 | JLAC11 (search summary of JSLM documents) | https://www.jslm.org/committees/code/jlac11overview.docx | Search summary only |
| 31 | DPC survey explanatory documents (search summary) | https://www.mhlw.go.jp/stf/newpage_72638.html | Search summary only |
| 32 | Real-MedNLP / MedTxt | https://sociocom.naist.jp/real-mednlp/ ; https://sociocom.naist.jp/download/real-mednlp-test-collection/ | CC BY 4.0 (test collection); search summary |
| 33 | University of Tokyo press release (2026-07-08) on medical LLMs and safety tools | https://www.t.u-tokyo.ac.jp/hubfs/press-release/2026/0708/001/text.pdf | Press release |
| 34 | UMIN-CTR top | https://www.umin.ac.jp/ctr/index-j.htm | UMIN |
| 35 | 統一書式 一部改正 (令和4年11月30日) | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/touitsu2_00002.html | Search summary only |
| 36 | Japan REDCap Consortium material; several university REDCap pages (search summary) | https://www.aro.med.kyushu-u.ac.jp/wp-content/uploads/2024/08/redcappamphlet2024.pdf | Search summary only |
| 37 | JP Core (1.2.0, 2025-07-30; JP-CLINS 1.1.2-clins) | https://jpfhir.jp/fhir/core/ | Licence not stated |

(Rows 1 to 8 are the first site's pages; they are in the site notes outside the repository. Row 12 is unused.)

---

## 15. Measurement log

All commands ran on master `7da6edd38` in the worktree, with the main checkout's interpreter; outputs under
`/var/tmp/trialbox-0/b12/`.

| n | What | Command | Result |
| --- | --- | --- | --- |
| 1 | ja catalogue counts | `PYTHONPATH=libs:services:. python /var/tmp/trialbox-0/b12/scripts/ja_count2.py` (and `ja_count.py` for endings and samples) | 3,099 ja keys, 0 missing; counts as in 7.1; 43 mixed-register strings; endings: 1,264 polite, 84 plain, 154 other sentences, 2,815 labels (the endings script read 4,317 entries across module dicts, so its denominators are larger than 3,099; the term counts use the merged 3,099) |
| 2 | PHI guard on 10 synthetic Japanese lines | `PYTHONPATH=libs:services:. python /var/tmp/trialbox-0/b12/scripts/guard_probe.py` | Unmasked: "ヤマダ　タロウ様", "（ヤマダ タロウ）" after a masked kanji name, "髙橋 一郎さん" (DOB masked), "記号 ３４５"; masked: kanji name with 様, phone, address, カルテ番号, S45.3.2 date |
| 3 | MedTxt scores | `python -c` over `eval/medtxt/results/scores.json` (`single` block, ja and en) | As in section 5's table; 215 reports, items positive 659, negative 349, suspicious 239, absent 430 |
| 4 | Japan table sizes | `wc -l` / `grep -c ""` on `libs/tb_common/refdata_src/ja_clinical_synonyms.csv`, `jp_yj_atc.csv`, `services/adapter/mapping/jp_core/*.csv` | 71 and 57 lines (70 and 56 rows); demo maps 33, 15, 23 lines (32, 14, 22 rows) |
| 5 | Claims and DPC readers | `grep -rn -i "dpc\|レセプト\|uke" services/adapter libs/tb_common`; `ls services/adapter/sources/` | Only receipt-code column names in the MEDIS and drug loaders; sources: csv, fhir_bulk, ssmix2, cgrd_sql |
| 6 | Holiday file | `curl …/syukujitsu.csv` then `iconv -f CP932` | 2027 has 17 rows; last row 2027/11/23 勤労感謝の日 |
