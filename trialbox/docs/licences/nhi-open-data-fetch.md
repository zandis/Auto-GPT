# Fetching and shipping the NHI open data (H-17, D-1127)

**Reader:** the integrator, who fetches the two NHI lists and commits the table built from them; a reviewer who checks
that what ships is what the publisher published, under its licence and with its attribution.

D-1028 point 3 lets the product ship the NHI open data with attribution. This page says exactly what to fetch, how to
build the shipped tables from it, and what each command must print. The attribution itself is in
[nhi-open-data-attribution.md](nhi-open-data-attribution.md). Nothing here has been fetched yet: no lane downloads
these files (only the integrator does), and the repository holds only the public sample rows of licence-register row
`nhi-codes` and the made-up extracts of row `term-synthetic-fixtures`.

"Verified online" below means read on the publisher's pages on 2026-11-17 (data.gov.tw dataset pages and
<https://data.gov.tw/license>). Nothing was downloaded to verify it.

## What to fetch

| | The NHI drug list | The NHI medical service and order codes |
| --- | --- | --- |
| Title as published | 健保用藥品項查詢項目檔 | 醫療服務給付項目及支付標準(csv檔) |
| Publisher | 衛生福利部中央健康保險署 (National Health Insurance Administration, NHIA). Verified online. | the same. Verified online. |
| Data set page | <https://data.gov.tw/dataset/23715>. Verified online (the page with this id carries this title). | <https://data.gov.tw/dataset/174450>. Verified online. |
| Download (the page's CSV resource) | `https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-E41001-001`. Verified online; the same URL is in `libs/tb_common/refdata_tw.py` (item `nhi_drug_atc`). | `https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20021-001`. Verified online; the same URL is in the same file (item `nhi_services`). |
| Formats offered | CSV only on the data set page. Verified online. | CSV only. Verified online. |
| File name | not stated on the page; the download URL names no file. Save it as `nhi_drugs_<fetched on>.csv`. | not stated. Save it as `nhi_services_<fetched on>.csv`. |
| Encoding | not stated on the page: not verified online. The repository's public sample (fetched for D-140, 2026-11-09) is UTF-8 with a BOM. The loader reads UTF-8 (BOM or not) or Big5 (cp950) either way. | not stated: not verified online. The repository's sample is UTF-8 without a BOM. Same loader. |
| Columns as published (主要欄位說明, verified online) | 異動, 藥品代號, 藥品英文名稱, 藥品中文名稱, 成分, 規格量, 規格單位, 單複方, 支付價, 有效起日, 有效迄日, 藥商, 製造廠名稱, 劑型, 藥品分類, 分類分組名稱, ATC代碼, 給付規定章節, 藥品代碼超連結, 給付規定章節連結 | 診療項目代碼, 健保支付點數, 生效起日, 生效迄日, 英文項目名稱, 中文項目名稱, 備註 |
| Columns the loader reads | 藥品代號, 藥品中文名稱, 有效起日, 有效迄日, ATC代碼 (required); 藥品英文名稱, 成分 | 診療項目代碼, 健保支付點數, 生效起日, 生效迄日, 中文項目名稱 (required); 英文項目名稱 |
| Dates | 民國 `YYYMMDD`, sometimes with leading spaces (`  960901`), as in the sample | `YYYYMMDD` (`29101231`: open-ended), as in the sample |
| How often it changes | "每1月" (monthly). Verified online. | "每1日" (daily). Verified online. |
| How a version is named | the page's file update time (檔案更新時間); it read 2026-10-28 07:02:13 on 2026-11-17. The version is that time, written `data.gov.tw 23715, file updated <time>`. | the file update time; it read 2026-11-17 07:01:11. Written `data.gov.tw 174450, file updated <time>`. |
| Size | 45,224 codes in the D-140 fetch (`libs/tb_common/refdata_tw.py`); not re-checked | 6,175 codes, 1.7 MB (2026-11-10, same file); not re-checked |
| sha256 of the file fetched | `<FILL IN at the fetch: sha256sum of the saved file>` | `<FILL IN at the fetch>` |
| Fetched on | `<FILL IN: YYYY-MM-DD>` | `<FILL IN: YYYY-MM-DD>` |

## The licence

- **Name and version:** 政府資料開放授權條款－第1版 (Open Government Data License, version 1.0), at
  <https://data.gov.tw/license>. Verified online. The data set pages give 授權方式 "政府資料開放授權條款-第1版".
- **What it allows:** use, reproduction, distribution, adaptation and any product, commercial included, at no fee
  (as recorded in `libs/tb_common/refdata_tw.py`, read 2026-11-09).
- **Its condition, the attribution (its annex 顯名聲明, article 3.2).** Verified online. Three parts: the provider,
  the year and the data set's name and version; a statement that the data is released under the licence; and the
  link to the licence's full text. A user who does not attribute is treated as never having had the licence. The
  shipped table's manifest line carries this statement (`ogdl_statement`), for the drug list:

  > 衛生福利部中央健康保險署 健保用藥品項查詢項目檔 `<version>`。此開放資料依政府資料開放授權條款 (Open Government
  > Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款：https://data.gov.tw/license

  and the same with 醫療服務給付項目及支付標準 for the service list. The shorter statement of
  [nhi-open-data-attribution.md](nhi-open-data-attribution.md) stays in the line too (`attribution`).
- **What it does not give or forbids** (verified online): no patent or trademark rights (article 2.4); the release
  is no endorsement by the agency, and the product must not imply one (article 6.1); third parties' moral rights are
  respected (article 3.1); the agency may stop a release that infringes a third party's rights or privacy (article
  5.2). The pages do not mention personal data; these lists hold none.

## The commands, after the fetch

From `trialbox/`, with the two files saved outside the repository (for example in a new empty folder):

```
sha256sum nhi_drugs_<day>.csv nhi_services_<day>.csv          # write both into the table above
python -m tools.terminology_install nhi-build drugs nhi_drugs_<day>.csv \
    --version "data.gov.tw 23715, file updated <time>" --fetched-on <day> --sha256 <sha256>
python -m tools.terminology_install nhi-build services nhi_services_<day>.csv \
    --version "data.gov.tw 174450, file updated <time>" --fetched-on <day> --sha256 <sha256>
python -m tools.terminology_install nhi-check
```

What each must print:

- `nhi-build drugs`: `nhi_drug_list: <n> rows built into <the shipped folder>, sha256 <64 hex>` and the attribution
  line. `<n>` is the number of distinct 藥品代號 (about 45,000 in 2026). Exit 0.
- `nhi-build services`: `nhi_service_list: <n> rows built into ...` (about 6,000). Exit 0.
- `nhi-check` before the register row is changed: one `PROBLEM:` line per file, ending "no cleared OGDL row in
  docs/licences/register.csv names it (row nhi-open-data-full)", exit 1. Then, in the same commit, set row
  `nhi-open-data-full` to status `cleared` with the paths
  `services/criteria_compiler/terminology/shipped/*`, and run it again: one line per table (`nhi_drug_list: <n> rows,
  <version>, sha256 <16 hex>, from <16 hex> fetched <day>`), no `PROBLEM:` line, exit 0.
- Then `python -m tools.licence_register --check` (0 problems) and `make goldens-check` (the goldens are drafted
  without the NHI tables' names mattering to them; if one moves, say why in the train).

What refuses, and what to do:

- `refused: <file>: no column ATC代碼 (the header has: ...); if the publisher renamed it, give --column
  ATC代碼=<its header>`: the publisher renamed a column. Give the mapping, for example `--column "ATC代碼=ATC CODE"`,
  and say so in the train. Header spaces, quotes, a BOM and full-width letters are read without it.
- `refused: <file>, row <r> (line <l>): ...`: one row is malformed (a code not shaped as the system's, a date that is
  not one, a row with more or fewer fields than the header). Nothing was written. Report the row; never edit the
  publisher's file by hand.
- `its sha256 is <x>, not the <y> recorded at the fetch`: the file is not the one fetched.

## What the shipped table does

The mapper reads a shipped NHI table when the box loaded none of its own (a table the site's IT loads with
`nhi-drugs` or `nhi-services` is read in its place, as ICD-10-CM's blocks are). An ended code (有效迄日 or 生效迄日
before today) answers nothing. A name several codes share answers with all of them, for review (D-1114 point 3).
`trialbox doctor` no longer lists a shipped NHI table as "not loaded".
