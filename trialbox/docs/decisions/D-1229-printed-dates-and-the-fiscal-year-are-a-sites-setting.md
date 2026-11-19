# D-1229 Printed dates (Western, 和暦 or both) and the fiscal year 年度 are a site's setting, set at install (10C-13, 10C-15)

- **Task:** cards 10C-13 and 10C-15 of plan 10, Track C (review 11, JP-14 and JP-16), lane J; amended by the lane J
  coordinator's review of PR #1125. · **Date:** 2026-11-19
- **Decision:** two settings of the site, `site.printed_dates` (`western` | `era` | `both`) and `site.year_basis`
  (`calendar` | `fiscal`), read by one function, `tb_common.dates.site_dates`.
  - **Who sets them.** The set-up wizards (`tools.settings_wizard`, and the box's first-run page with the country,
    10K-1) ask both. The default shown is the site's country's, from `tb_common.site_country.TABLE`: Japan `both` and
    `fiscal`; every other country `western` and `calendar`. For a site with a country, the answer is written into
    the settings explicitly.
  - **Unset means as before.** A settings file without the keys (every installed box, and every answers file without
    a country) reads `western` and `calendar`, which is exactly what it printed and counted before. Nothing is
    guessed from the zone or the report language at run time. An upgrade therefore changes no installed site's prints
    or report year. This has the same effect as writing the old values into the file on upgrade, and no migration can
    fail. A site that wants the Japanese forms sets the keys in `deploy/settings.yaml`, and they apply when the box
    restarts. There is no console page to change them after install.
  - **Printed only.** `tb_common.dates.printed` writes a date as `2026-11-18` (western, byte for byte as before),
    `令和8年11月18日` (era) or `2026年（令和8年）11月18日` (both). The first year of an era is 元年. The eras are the
    table `tb_common.dates.ERAS` (its public sources are cited there); a new era is one row. The function takes a
    `date` or a plain `YYYY-MM-DD`. A time stamp is printed only with the site's zone. Anything else, such as
    `20261118`, a number or text, is printed unchanged. It is used by the feasibility PDF (run date, snapshot), the
    NHI navigation summary, the NHI application form (every day in every field, through `printed_in`), the CASE
    sheet (checked-on, snapshot, quotes, chart spans) and the released consent page.
  - **Where dates stay ISO.** Stored values, exports for machines (XLSX, CSV, FHIR), audit records, mail, screens,
    and the identifier line of a print (the footer's snapshot id).
  - **年度.** Under `fiscal`, 年度N is 1 April N to 31 March N+1. A stamp's day is its day in `site.tz`: an aware
    stamp is moved to the zone, a naive console stamp is UTC, and a plain day stays that day. The research office
    counts (page, XLSX, default year, every column) are the one yearly report shown to people, and they follow it.
    The heading, the help line, the year links and the XLSX "about" line say 年度 in en, zh-TW and ja. A
    `calendar` site's page and XLSX are as before, and keep the old rule: the stamp's first four characters.
- **Why:** JP-14 and JP-16. The owner's frame is that the Japan profile is data (C-7) and that the work is not
  over-built. The coordinator ruled that an existing install must not change on upgrade without someone choosing,
  and that the default comes from the country, not from the zone or the language.
- **Not decided here:** whether a `calendar` site should also bucket UTC console stamps by the site's day. That
  would change what non-Japanese sites count, so it is left to the owner.
