# D-1250 A country is one layer of data above the site profile; Japan's lists P1 to P16 and every behaviour reads it

- **Task:** card 10C-25 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C, commitment C-7; source review 11
  section 8, `docs/reviews/2026-11-root/11-japan.md`, parts P1 to P16)
- **Date:** 2026-11-19
- **Status:** accepted; the number is reserved for this card (lane J's block D-1220 to D-1319)
- **Builds on:** D-1233 (the site profile and its `country`), D-1227 (the committees part, the first in the layer
  file), D-1228 (the Japanese device-claims rule), D-1229 (printed dates and the year are a site's setting, unset
  means as before), D-1230 (holidays in the working days), D-1232 (consent by a representative and assent), D-277 and
  D-766 (the SAE rule set shown before one is chosen), D-138 (retention rules)

## Context

Each Japan behaviour had been added card by card, each with its own switch or table: the committees read
`japan_profile.json`, the New Year break was a `{"JP": ...}` table in `tb_common.workdays`, the eGFR equation and the
SAE rule set were `{"JP": ...}` tables in `tb_common.derived` and `datacore.lifecycle`, the YJ ingredient stems were
switched on by `country == "JP"` in the compiler's resolver, and the set-up defaults (report language, retention, the
SS-MIX2 source and mapping, printed dates, the fiscal year, consent by a representative) were one literal row of
`tb_common.site_country.TABLE`. Nothing listed what "a site in Japan" gets, and the next card could add a
seventeenth switch without anyone noticing.

## Decision

1. **One file per country, versioned.** Japan's is `libs/tb_common/japan_profile.json` (the file D-1227 began),
   now `format: tb-country-layer/1` with `country`, `version` (MAJOR.MINOR.PATCH) and `parts` P1 to P16 by the
   review's names. Each part says its kind (behaviour, wording, document), its state (built, partly built,
   declared, not built), its cards and decisions, its `values`, the `readers` that read them, what is on for every
   site regardless (`everywhere`), what is missing (`not_built`) and the owner's open questions it touches.
   `tb_common.country_layer` loads it (standard library only). It refuses a file whose bytes are not UTF-8 JSON (a
   byte-order mark included); a part missing or misnamed; an unknown key; a declared part with values; values
   without readers; a part not wholly built that does not say what is missing; and any value a reader asks for
   (`country_layer.READ`: P1, P2, P3, P5, P7, P8, P9, P11, P14) that is missing, of another type or of another shape
   (the holiday list's file name, the New Year break). `country_layer.FILES` names the country of each shipped file,
   and a file that names another country is refused as well. Every check the
   tests list is one a tampered file is tested against (point 9); the loader proves the file is the shape the
   readers need, not that its values are right (point 8 holds those to master's).
2. **The site's country turns it on.** The country is the one the site profile is checked against
   (`tb_common.derived.country_of`, D-1233). A country without a layer gets `None` from every reader, and the reader
   then gives its other-country default: the value a site with no layer had before. A layer is read the first time a
   site of its country asks, never at import and never for another country: a site of Taiwan, of the United States
   or with no country set never opens Japan's file.
3. **Every reader asks the layer by part and key** (`country_layer.value(country, "P9", "new_year_break")`): the
   set-up defaults (`site_country.from_layer`: P1, P5, P9, P11, P14), the committees (P3), the SAE rule set shown
   before a study chooses one (P2, `lifecycle.country_default`), the YJ stems (P7), the eGFR equation (P8), the
   holiday list and the New Year break (P9, `workdays.holidays`, `workdays.country_break`). The values are the ones
   the code held before, so with the shipped file a Japanese site behaves as on master (point 8; the lane J lead's
   review compared both trees on every reader).
4. **Same calls for every country.** A test runs every reader with the layer on and off: Japan with the layer off
   runs the same functions and gets the same results as a country without one, and the same layer under a made-up
   country code runs the same functions and gets the same results as Japan. The functions that run only with the
   layer on are the ones that read the data it turns on (the break, the site's changes to it).
5. **A setting a person made wins.** Where the site sets a value by hand (`site.printed_dates`, `site.year_basis`,
   `TB_CONSENT_PROXY`, `TB_NEW_YEAR_BREAK`, `TB_DAYS_OFF`, `TB_DAYS_OPEN`, `TB_JP_INGREDIENT_ATC`), that value is the one
   read, as the site set-up store wins over the site profile's table (D-1233): it is a named person's recorded
   choice, and the layer is the project's general reading. The layer's set-up values (`printed_dates`, `year_basis`,
   `consent_proxy`, the language, the source and mapping) stay what the wizards offer and write into a new site's
   settings. They are **not** run-time defaults, so a box whose settings do not name them prints, counts and records
   consent exactly as before (D-1229's rule; no installed box changes on upgrade).
   - **Shown per setting.** A night's "Site profile" section on the data-operations page (`/data-ops/batches/<id>`,
     D-1233), read by the same accounts that read that record, has the country layer's lines, only at a site whose
     country has a layer: its country, version and digest (12 characters), and one row per setting it offers or
     turns on. Each row gives the value in force, "set by the site", "from the Japan profile" or "not set: as before
     the profile", and the profile's value (`console.country_profile.in_force`), in en, ja and zh-TW. The country is
     read as the compiler reads it (`country_of` of the box's zone and the site's language). A site without a layer
     sees master's section byte for byte (a test holds it to master's rendered bytes in the three languages). No
     route, no API field, no patient data.
   - Not built, for the owner: a "Country profile" card on the site set-up overview (`/site`), which every account
     that opens the overview would see. That is a new reader of the configuration, and this card does not add it.
6. **Versions and audit.** The layer ships with the release, as the holiday list does (D-1230), so its version is
   the release's. Its country, version and digest are written in the site profile's record (`site_profile.json`,
   `active.layer`, by `adapter.site_profile.activate`) at each load of a profile. Reloading the same profile writes
   nothing, as on master, whatever the layer's version now: no record is written without its event, and the event is
   not changed. **The `terminology.site_profile_load` audit event is unchanged** for every country:
   the audit's shape is lane C2's (the lane J lead's ruling of 2026-11-19); a test holds a Japanese load's event to
   master's keys. A country without a layer writes nothing new.
7. **No seventeenth switch unnoticed.** `tests/unit/test_japan_profile_layer.py` lists P1 to P16 by name, names the
   parts declared but not built (P4 Roles, P6 Forms, P12 Money, P13 Registries, P15 Procurement and security), and
   scans product code (`libs/`, `services/`, the box's set-up tools) for every string that names Japan (`JP`, `jp`,
   `jpn`, `Japan`, `Asia/Tokyo`, in any case, whole, implicitly concatenated or added from two pieces). Each one left
   is pinned by its file and whole line with its reason (the zone reading, data labels, the country answers). A new
   line, or a pinned line changed, fails with its file and line and how to register a reader in the layer. Reusing a
   pinned line's place for a new test does not pass.
8. **The values moved are master's.** One test per moved value compares the layer with master's constant (the
   committees by the digest of master's block), and the goldens are unchanged.
9. **A layer that cannot be used reaches its own country only, and says so.** A missing, unreadable or refused file
   (point 1) makes that country's layer *broken*: `country_layer.layer` returns it with its `problem` and never
   raises, and asking it a value raises `country_layer.LayerBroken` (the file and what is wrong). Nothing at import
   reads a layer, so every service starts. A site of another country, or with none, answers exactly as with the
   shipped file. A Japanese site is never quietly given another country's values. Instead:
   - **The box's health:** one red line, "the JP country layer japan_profile.json cannot be used (...)", naming
     what is wrong (`workdays.health`, on the metrics page). The night's "Site profile" section shows the same in
     red, in place of the rows.
   - **eGFR (P8):** no equation. `derived.egfr_for_site` raises, so a compile that needs a plain `egfr` is refused
     with the reason. It never becomes CKD-EPI.
   - **YJ ingredient stems (P7):** the compiler does not start (`resolver.jp_ingredients` raises). It is never
     started without the stems, which would leave Japanese drug codes unmatched without saying so.
   - **Holidays and the New Year break (P9):** Monday to Friday only, as for a damaged holiday list (D-1230), said
     by the red line above.
   - **The SAE rule set shown before a study chooses one (P2):** none. `lifecycle.clock_rules` says `unconfirmed`
     with no regulator shown, so the study must name its set. No deadline comes from a guessed set.
   - **Committees (P3):** the rule stays on (`committees.on` is true) and its record cannot be read
     (`committees.profile` raises). A move into open stops with an error and the study is not opened. The
     scheduler's timer holds the lists (D-1227's "a record that cannot be read holds the list"), and a list run
     stops with the reason. Nothing opens or lists without the record.
   - **The set-up defaults (P1, P5, P9, P11, P14):** none to offer. `site_country.defaults("jp")` raises with the
     reason, the wizards say it, and SS-MIX2 is not offered.
   - **The site profile's record:** no layer is named (nothing was read from it).

   `tests/unit/test_japan_profile_layer.py` tampers the file 19 ways and runs every reader for JP, TW, US and a box
   with no country. The 19 ways: missing, empty, truncated, bad JSON, a byte-order mark, an extra key, the country
   TW, the country US, each read part's values removed, and a bad holiday list name.

## What this does not change

No behaviour, default or stored value of any site. Each part not built stays declared (the card that builds it adds
its values and readers). The guard (P10), the device-claims lint (P5) and the CJK layout rules (P16) stay on for
every site by the text's characters or language: the layer lists them as "On everywhere, not switched by country". No route, export, role or reader of patient data is added.

## Open questions with the owner (the layer carries today's behaviour)

- Whether the head-of-institution permission applies to all three Japanese study kinds (P3; today: both records for
  every kind, the lane J lead's ruling of 2026-11-19).
- Whether a running study is stopped when the Japan rule arrives (P3; today: a study open before the rule is marked
  `before_rule` and not held for a kind not chosen, D-1227).
- What a missing assent does (P11; today: a minor's record without assent warns, D-1232).

## Consequences

The next Japan card adds its data to its part and reads it with `country_layer.value`; a second country is one more
file in `country_layer.FILES` and its own parts. Known limit: the record's layer is written at a load of the site
profile, so after an update brings a new layer version the record names the earlier one until a person loads the
profile again; the version in force is the release's, shown in the night's "Site profile" section.
