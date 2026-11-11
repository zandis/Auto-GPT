# APPI and PDPA mapping (個人情報保護法・個人資料保護法の対応表 / 個資法對照表)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-07 |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| Source | TB-PLAN-05 §9.3, moved here and brought to master's state; SECURITY §7 (laws a site must check); the regulatory review `docs/reviews/2026-11-10-deep-review/05b-regulatory-standards.md` |
| Status | Draft, not legal advice. The legal basis (row 1) is the open question of REG-007; the memo slot is TB-PRV-03. |

TB-PLAN-05 §9.3 becomes a pointer to this file at its next version (the plan document is not edited by this card).

| Duty | Japan (APPI, 3省2ガイドライン 7.0, 倫理指針, J-GCP) | Taiwan (PDPA, 人體研究法, 醫療法 and the EMR 辦法, 資安法) | How TrialBox meets it | Where |
| --- | --- | --- | --- | --- |
| Legal basis for identified pre-screening | the hospital's published 利用目的 and the IRB-approved protocol; opt-out with notice for research on existing information; 仮名加工情報 never used to contact (Art. 41) | Art. 6 lists the allowed cases for medical data; IRB approval alone is not one; 人體研究法 Art. 12 consent or an announced waiver class | the legal-basis memo per site (slot); the IRB pack names TrialBox; contact only after the treating physician agrees | TB-PRV-03, TB-PRV-04 |
| Special data and security measures | 要配慮個人情報; 安全管理措置; two factors from FY2027; lockout; no reuse; immutable backups; SBOM; 責任分界 | Art. 6 special data; Art. 27 security plan; the EMR 辦法's contract clauses, encryption, domestic storage, disposal; 資安法 vendor duties | second factor on every sign-in route; lockout; password history; encrypted backups off the box; SBOM; the responsibility-boundary sheet; no remote access by design | SECURITY §1 to §6, §8 |
| Processor contract | 委託 with supervision of the vendor | PDPA processor terms; the EMR 辦法's outsourcing clauses | the data-processing agreement per site; Aimedics never holds patient data | data-handling rule; TB-PRV-01 §1 |
| Breach notification | PPC 速報 about 3 to 5 days, 確報 30 or 60 days; notice to the person | subjects after the facts are established (72 h in the draft rules); EMR 辦法 72 h; 資安法 1 h for designated agencies | the incident plan with its clocks, the first-hour list, the templates and the tabletop | TB-SITE-11 |
| Access logs and retention | access-log authenticity and retention | the EMR 辦法's full access log for the retention period | hash-chained audit of every view, 10 years on the box; retention per data kind | SECURITY §6; TB-PRV-01 §2 |
| Pseudonymisation and de-identification | 仮名加工 and 匿名加工情報 rules for third-party provision | "cannot identify" standard; 人體研究法 Art. 19(3) for material abroad | HMAC pseudonyms at the door; k = 5 small-cell suppression; no cross-border export in the pilot | SECURITY §5 |
| Opt-out | the notice for research on existing information (the 2026-12-01 guideline) | the opt-out right after the 2022 Constitutional Court judgment | the opt-out register and worker; the notice per site | TB-PRV-05; T-206a, T-206b |
| Disposal | 安全管理措置 for disposal | the EMR 辦法's disposal clause; 人體研究法 Art. 19 | the destruction procedure with a certificate | TB-PRV-08 |
| Trial records | J-GCP and ER/ES: ALCOA+, audit trail, e-signature where records are kept | GCP source-document rules | the prefill path's controls; the record inventory | `docs/validation/record-inventory.md` |
| Device status | 該当性 guideline: intended use as presented | 醫療器材管理法 and the medical software guidance | the intended-use statement on every page and report | TB-IU-01 |
