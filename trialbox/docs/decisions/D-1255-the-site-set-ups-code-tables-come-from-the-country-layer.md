# D-1255 The site set-up's code tables come from the country layer (P7 Masters)

- **Task:** card 10C-25b of plan 10 (lane J), the follow-up D-1250 names under "What remains"
- **Date:** 2026-11-19
- **Status:** accepted; the number is reserved for this card (lane J's block D-1220 to D-1319)
- **Builds on:** D-1250 (a country is one layer of data), D-131 and D-135 (the once-per-site mapping), D-1233 (the
  verified state of a shipped table row)

## Context

`services/sitesetup/mapping.py` picked the code tables it suggests standard codes from by folder name, in three
places: 病名 to ICD-10, JLAC10 to LOINC and YJ to ATC from `jp_core/`, and the hospital lab table from `tw_core/`. It
read all four for every site, whatever its country. D-1250 pinned those lines as "not yet a layer reader".

## Decision

1. **What moved.** The list of tables is the value `code_tables` of part P7 (Masters) of the country layer. P7 is
   the part of the code masters (D-137's MEDIS, JLAC10 and YJ). Japan's layer lists the four tables master read, in
   master's order: `jp_core/byomei_to_icd10.csv`, `jp_core/jlac10_to_loinc.csv`, `tw_core/lab_local_to_loinc.csv` and
   `jp_core/yj_to_atc.csv`. The Taiwan lab table stays in Japan's list because master read it for Japanese sites too.
   P7 names the reader `sitesetup.mapping:code_tables`.
2. **One call, the same path for every country.** `mapping.code_tables(country)` asks
   `country_layer.value(country, "P7", "code_tables")`. The look-ups, the not-verified rows and the 病名 names
   (`_lookups`, `_unverified`, `_dx_index`) all read the tables it returns. Each table is read by its format, which
   its file name says (`mapping.FORMATS`). A country without a layer gets `mapping.OTHER_COUNTRY_TABLES`, which is
   master's list in master's order. That list names `jp_core/` files, so three lines are pinned in the guard under
   the existing category "a data label or file name". The "not yet a layer reader" category and its seven pins are
   gone. The guard's scan is unchanged.
3. **The loader refuses a layer without it, whole.** `country_layer.READ` now holds `("P7", "code_tables")` as a list.
   The list must not be empty. Each item must be a text of the shape `<folder>/<table>.csv`, where `<table>` is one of
   the four formats the set-up reads, and no item may appear twice. A list value is checked item by item. The other
   values are checked as before.
4. **A broken layer: the set-up suggests nothing from a table, and says so.** This is the P7 neighbour's way
   (D-1250 point 9: the compiler does not start without the YJ stems). For a Japanese site whose layer is broken,
   `code_tables` raises `country_layer.LayerBroken`, and so does `mapping.suggest`. The reading of a sheet stops at
   its first local code, before any suggestion or fact of it is written. The box's health already shows the red line
   naming the file. A Japanese site is never given another country's tables or the no-layer list. Taiwan, the
   United States and a box with no country answer exactly as with the shipped file.
5. **Version.** The layer file goes from 1.0.0 to 1.1.0. This is a MINOR step: a value and a reader were added and
   nothing was removed or changed. The values of every other part are unchanged. The only other bytes that change are
   the P7 reader entry and the version line. P7's `cards` and `decisions` were not changed, to keep the rest of the
   file byte-stable. The night's "Site profile" section shows the new version (its test now expects 1.1.0). No row was
   added.

## Proof of no behaviour change

`tests/unit/test_sitesetup_code_tables_layer.py` holds master's answers. They were captured from master's tree
(f6c42230, in a separate worktree) by the test's own `answers()` function into
`tests/fixtures/sitesetup_code_tables/master.json`. There are 16 cases: JP, TW, US and a box with no country, each
with the four source types the set-up offers (csv, cgrd_sql, fhir_bulk, ssmix2). Each case records every table row
resolved, the rows marked not verified, the 病名 names taken from the tables, the JLAC10 codes known, and the
suggestion for every code of every table. On this head, each case is equal to master's. The guard test's
every-reader calls now include the code tables, so the existing D-1250 tests also cover this reader: the layer off,
the layer on, and the layer renamed to a made-up country. The tamper tests are the following:

- the value missing;
- the wrong type (a text);
- an empty list;
- an item that is not a text;
- an item outside the folder;
- a table of no known format;
- an item listed twice;
- the country changed to TW;
- the country changed to US.

Each is run for JP, TW, US and a box with no country, with every source type. Only JP is refused. The others equal
master.

## What this does not change

No page, route, text, role or stored value changes. Every country gets the same tables as on master. `site_country`
defaults are unchanged.

## What still remains outside the layer

- Sites without a layer (Taiwan, the United States, no country) still map against Japan's three tables, as on master
  (`OTHER_COUNTRY_TABLES`). Narrowing that by country would change behaviour, so it is the owner's call.
- `suggest()` uses Japan's reference-data maps (`_yj_atc`, `_jlac10_loinc`, `_yj_ingredient`,
  `_jlac10_analyte_material`) and the licensed MEDIS, JLAC10 and YJ releases (`_licensed`) at every site, chosen by
  the code's shape, not by country. P7's "On everywhere" covers the licensed releases.
- The Taiwan 2014 ICD-10-CM step is switched by `site_country() == "TW"` in `suggest()`. Taiwan has no layer, and
  the Japan guard does not look for Taiwan's words.
- The SS-MIX2 source reads `jp_core/` tables by source type (`adapter.sources.ssmix2.source.JP_CORE`, pinned as such
  by D-1250).

## Correction to D-1250 (2026-11-19)

D-1250's "What remains" is done by this decision for the code tables: `services/sitesetup/mapping.py` now reads them
through the layer (P7 `code_tables`), and the "not yet a layer reader" category is no longer in the guard. Its list of
seven categories is now six. The list above is what remains.
