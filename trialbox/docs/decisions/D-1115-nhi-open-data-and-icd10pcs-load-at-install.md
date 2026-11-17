# D-1115 The NHI open data and ICD-10-PCS load at install through TERM-1's loader

- **Task:** lane H, card H-5 (TERM-2), on D-1028 point 3 (NHI open data may ship with attribution) and D-1029
  (ICD-10-PCS may be committed with a licence-register row)
- **PR:** this branch (`claude/lane-h-5-term2`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-858, D-170 and D-317 (the NHI files' formats as `tb_common.refdata_tw` reads them)

## Decision

1. **The NHI drug list** (健保用藥品項查詢項目檔, data.gov.tw 23715): `nhi-drugs <csv>` reads NHIA's CSV with the
   columns `tb_common.refdata_tw` already requires (藥品代號, 藥品中文名稱, 有效起日, 有效迄日, ATC代碼; also 藥品英文名稱 and
   成分). It keeps one row per 藥品代號, the newest validity period, in `nhi_drug_list`, with its ATC代碼 when ATC-shaped.
   A medication's name that equals a drug's ingredient (成分 without salt or strength; never a combination) resolves to
   that ingredient's ATC codes, for review.
2. **The NHI service and order codes** (醫療服務給付項目及支付標準, data.gov.tw 174450): `nhi-services <csv>` reads the
   CSV `tb_common.refdata_tw` reads into `nhi_service_list`. A procedure's name equal to an item's Chinese or English
   name resolves to its code, in the system of the shipped NHI order codes (`nhi_order`).
3. **ICD-10-PCS**: `icd10pcs <zip or txt> [--year]` reads CMS's order file (fixed columns) or codes file into
   `icd10pcs`. A procedure's name equal to a valid code's long or short description resolves to it, under
   `http://www.cms.gov/Medicare/Coding/ICD10` (the adapter's ICD-10-PCS URI).
4. **Attribution.** Each NHI table's manifest line carries the provider's attribution statement (`attribution`),
   which is also in `docs/licences/nhi-open-data-attribution.md`. Licence register rows: `nhi-open-data-full` and
   `icd10pcs-full`.
5. **Nothing is committed that could not be verified.** No full NHI list and no ICD-10-PCS release is in the
   repository or this session's caches, and nothing was downloaded. D-1028 and D-1029 allow committing them; that
   waits for a verified copy. The tests use the committed public NHI samples and made-up PCS lines.
