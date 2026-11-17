# Attribution: Taiwan NHI open data (TERM-2, D-1115)

**Reader:** whoever ships, loads or shows a table built from the NHI open data: the vendor, the site's IT, a reviewer.

The Taiwan National Health Insurance Administration publishes these lists under the Open Government Data License,
version 1.0 (Taiwan), <https://data.gov.tw/license>. The licence allows use, reproduction, distribution and adaptation
for any purpose, commercial included, with no fee, on one condition: the provider's attribution statement. D-1028
point 3 lets TrialBox ship them with this attribution. Licence register rows: `nhi-codes` (the samples and demo rows
in the repository) and `nhi-open-data-full` (the full lists, loaded at install).

| Table the loader writes | Command | Attribution statement |
| --- | --- | --- |
| `nhi_drug_list` | `python -m tools.terminology_install nhi-drugs <csv>` | 健保用藥品項查詢項目檔, National Health Insurance Administration (衛生福利部中央健康保險署), via data.gov.tw (dataset 23715), Open Government Data License 1.0 |
| `nhi_service_list` | `python -m tools.terminology_install nhi-services <csv>` | 全民健康保險醫療服務給付項目及支付標準, National Health Insurance Administration (衛生福利部中央健康保險署), via data.gov.tw (dataset 174450), Open Government Data License 1.0 |

The loader writes the same statement into the table's line in `manifest.json` (field `attribution`), beside the
source file's name and sha256 and the day it was loaded. `trialbox doctor` and
`python -m tools.terminology_install status` name the table and its version.

The ATC codes in the drug list's `ATC代碼` column are read as the NHIA list carries them. No WHO ATC/DDD index text
comes with them (row `atc`; the index itself is loaded only from the site's own copy, row `atc-index`).

**Shipped in the image (H-17, D-1127).** The integrator fetches the two lists as
[nhi-open-data-fetch.md](nhi-open-data-fetch.md) says and builds them with `nhi-build`. The shipped table's manifest
line then also carries the OGDL annex's own statement (field `ogdl_statement`: the provider, the data set and its
version, the release under the licence, and the link to its full text). `NOTICE` section 1 carries both statements
(data sets 23715 and 174450); the integrator adds the shipped folder's line to its section 8 (the fetch page says
which).

Wherever a page or a report shows a code or a name taken from these tables, the attribution goes with it.
