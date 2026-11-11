# 7. Laws a site must check

None of this is legal advice. Items marked *legal review* need the site's counsel.

**Both countries.** ICH E6(R3) data governance (audit trail, validation by risk, provider oversight): the audit chain,
byte-identical re-runs and `tools/acceptance.py` support it; a validation plan is a document, not code. Part 11 and
Annex 11 apply only if the box's records become trial records (a screening log in the TMF, a sheet the PI signs):
*legal review*, sponsor by sponsor. Hospital IT will ask for ISO/IEC 27001 and ISO 27799 (an organisational item).

**Japan.**

| Framework | What it asks of the box |
| --- | --- |
| APPI 個人情報保護法 | medical data is 要配慮個人情報: consent or an exception; 仮名加工情報 supports feasibility but not contacting patients; leak reports to the PPC |
| 生命・医学系指針 (2023) | existing records by opt-out with notice and an ethics committee |
| MHLW 安全管理ガイドライン v7.0 (2026) | two factors from 1 April 2027; lockout; no password reuse |
| MIC/METI provider guideline v2.0 (2025) | the vendor's risk assessment, service specification, SLA and 責任分界 |
| 次世代医療基盤法 | only when data goes through a certified operator; one hospital's own pre-screening is outside it |
| J-GCP, ER/ES guidance | if the box's output becomes a 治験 record |

**Taiwan.**

| Framework | What it asks of the box |
| --- | --- |
| PDPA 個人資料保護法 (2023; 2025 amendment pending) | medical data is special data; the basis for pre-screening with re-identification: *legal review* |
| 人體研究法 | IRB approval; consent or a listed waiver; non-de-linked data destroyed after the study |
| 醫療法 and the EMR regulation (2022) | access control, encrypted transfer, a full access log for the retention period, incidents reported within 72 h, data in Taiwan |
| 資通安全管理法 (2025) | medical centres are critical infrastructure: CISO, SOC, incident reporting |
| 人體生物資料庫管理條例 | when the source is a biobank |
| GCP 藥品優良臨床試驗作業準則 | the IRB approves the recruitment method, EMR search included |

The 2022 Constitutional Court judgment (111年憲判字第13號) means any NHI-sourced data must allow opt-out.

The full catalogue of integration scenarios, with sources, is `spec/archive/INTEGRATION_SCENARIOS.md`. The latest
independent review of standards and security is `docs/reviews/2026-11-08-fable-standards-security-review.md`.
