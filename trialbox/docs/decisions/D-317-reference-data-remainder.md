**D-317 Reference data remainder: the full CT.gov download, the NHI service list and full drug list, Taiwan 2014
codes read at ingest, withdrawing a source, the hospital's jRCT download, UCUM, and a cassette fetch test for every
list.** Card T-618 of TB-PLAN-06 (`docs/plan/28-master-plan-v6.md` §6.2, WS-08.8), after PR #76. Builds on D-140,
D-170 to D-175. Branch `agent/T-618-refdata`. Date: 2026-11-10. Licences and files read at the source on the same
day, from a cloud container with network access through a proxy.

*What was open.* D-140 and D-172 left these "not done": the full ClinicalTrials.gov pack was never built; the NHI
醫療服務給付項目 list (beyond the 53 lab codes of the PAS map) had no fetcher; the full NHI drug list was never fetched
in one piece (info.nhi.gov.tw cut the 97 MB transfer three times); a Taiwan 2014 code in an old record was not read
through the 2014 <-> 2023 map at ingest; a source dropped from a later pack kept its rows (only a manual delete); jRCT
had no loader. The baseline review's P0 list also named UCUM.

*Decisions.*

1. **One HTTP client and cassettes.** Every network read of the vendor's fetch (downloads, the CT.gov API, the MHLW
   index, the data.gov.tw records, the licence pages) goes through `refdata.http_client()`. A test replays a
   `refdata.Cassette` (recorded answers in `tests/fixtures/refdata/cassettes/`, bodies from the committed excerpts;
   workbooks and archives built at replay time so no binary is committed) in its place; a request the cassette did
   not record fails and never reaches the network. `tests/unit/test_refdata_fetch.py` fetches **every** shipped
   item that has a fetcher from the cassette, builds it and checks the manifest's URL, sha256, licence, attribution
   and version; a version-pinned item (the PAS package, CTCAE, UCUM) is first refused because the excerpt is not the
   pinned file. The two account downloads (LOINC, the NHIA ICD workbook) take `--file` and have no cassette.
2. **Downloads are retried and resumed.** Five tries with a growing pause (5, 10, 20, 40 s). A cut transfer is known
   by its `content-length` or, for a zip without one (CT.gov), by the zip's directory, and is never kept. The next
   try asks for the rest with `Range` when the server gave a length; info.nhi.gov.tw and clinicaltrials.gov ignore
   the range (checked: 200 and the whole file), so they start again. A local `--file` is copied and hashed in
   streams (the CT.gov zip is about 3 GB).
3. **The full CT.gov download.** Before the zip is made, fetch reads `/api/v2/version` (the data timestamp and API
   version: the pack's version of the CT.gov part, since the zip names none) and `/api/v2/stats/size` (611,234
   studies on 2026-11-10). The build stops when the zip holds more than 2 % fewer studies than that count (a short
   or wrong file). Checked here: the endpoint streams about 26 MB/s with no length; the full fetch and build need
   about 8 GB of free disk (zip, pack and tar) and were not run on this shared machine (7 GB free).
4. **NHI 醫療服務給付項目及支付標準** (`nhi_services`, kind term, ship). data.gov.tw 174450, the NHIA CSV
   `A21030000I-D20021-001`; dataset API `license` = 1 (OGDL 1.0), and the record lists the URL fetched. Today 6,175
   codes, 1.7 MB, 4,341 with an English name. One term per 診療項目代碼 (the newest 生效起日 when a code has several),
   system the TW Core code system of the service items (`NHI_SERVICE`, already used by the PAS map), display the
   Chinese name, `extra` the English name, points, dates and note. Version: the dataset's modified date.
5. **The full NHI drug list.** Fetched whole here (96,575,677 bytes, sha256 `e168cfb2...6ddaac`, 2026-11-10): 45,224
   codes, 45,214 with an ATC code (42,747 level 5, 2,210 level 4, 255 level 3, 2 level 2). Not committed: the vendor
   fetches it at build time.
6. **Taiwan 2014 codes at ingest.** `refdata_tw.tw_icd_edition(date)` gives the edition a record of that date
   carries (2014 before 2025-01-01). `tw_icd_at_ingest(code, date)` keeps the record's own code under its edition's
   system (a 2014 code is never read as a 2023 code), with the 2023 rows of the loaded map, and names the 2023 code
   only when the map says the meaning is the same (one `equivalent` target). `tw_code_in_list` answers a list of
   2023 codes: a 2023 code as it is (`no` only when the list speaks its system), a 2014 code through
   `in_set_via_map` (a split or an inexact row is `unknown`, never `no`). The adapter and lake call is not wired here:
   `services/adapter/pipeline.py` is held by a fix group.
7. **Withdrawing a source.** A pack's manifest may list `withdrawn: [{id, reason}]` (`build --withdraw ID=REASON`); a
   pack may only withdraw. Loading it deletes those sources' rows and records each in the new table `withdrawn`
   (schema `refdata` version 3: source, name, pack, reason, rows removed, when, by). A vendor pack never withdraws the
   hospital's own site-fetch rows. `python -m tb_common.refdata withdraw ID --reason R` does the same by hand. A pack
   made before a withdrawal and loaded again (a restore reloads the kept packs) skips the withdrawn source, so it
   does not come back; a newer pack that ships it again loads it. The pack's `created_at` now has microseconds for
   that order. The status lists withdrawals, `NOTICE.md` names them, and the sources page shows only sources whose
   rows are in the box (a replaced or withdrawn source's old manifest entry is no longer listed).
8. **jRCT** (`jrct`, kind trial, site-fetch, loader only). jRCT has no API; its search page offers a CSV download
   after the user accepts the terms, and bulk or comprehensive use needs the help desk's permission (still pending).
   TrialBox never fetches or ships jRCT data. The hospital downloads its own search (UTF-8 or Shift_JIS CSV, or
   XLSX) and runs `site-load jrct --file`; columns are matched by Japanese or English alias (check them against the
   first real download); a row without a jRCT-shaped id is left out and counted.
9. **UCUM** (`ucum`, kind term, ship). `ucum-essence.xml` at the `v2.2` tag of ucum-org/ucum (2024-06-17), pinned to
   sha256 `dfccea1b...b4fd0b61`; 305 units, 24 prefixes, 7 base units. Licence: the UCUM Copyright Notice and
   License 1.1 at the same tag, read by the item's page reader at each fetch: no-charge, royalty-free licence to
   reproduce and distribute and to build interoperating software; the content may not be changed and no derivative
   work made; copies carry the copyright notice, the licence (or its URL) and its disclaimer of warranties. So each
   prefix and unit is one record with every field exactly as the file gives it (codes, names, print symbol,
   property, value with its unit), nothing added or dropped; the attribution carries the notice, the licence URL and
   the disclaimer. The test fixture is a synthetic file in the same shape, not UCUM content.

*Not done (left for other cards).* The full CT.gov fetch and build were not run (disk); a vendor runs `fetch ctgov`
and `build` on a machine with about 8 GB free. The ingest call of item 6 in the adapter and lake (fix-group files).
The backup carries the `withdrawn` table with the rest of the `refdata` schema (it is not one of the bulk vendor
tables the dump leaves out); no restore test covers a withdrawal yet (`tools/trialbox/backup*.py` is held). P0 lists still missing: MHLW 一般名処方マスタ, the 薬効分類 -> drug-class table, ECOG PS and Karnofsky, the JSN eGFR
formulas, CTCAE v6.0, Hyakuyaku (D-175 item 2). The jRCT column aliases need a real download to confirm.
