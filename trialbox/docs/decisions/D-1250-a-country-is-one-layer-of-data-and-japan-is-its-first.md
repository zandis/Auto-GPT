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
   `tb_common.country_layer` loads it (standard library only) and refuses a file that is not whole: a part missing or
   misnamed, an unknown key, a declared part with values, a value with no reader, a part not wholly built that does
   not say what is missing, two layers for one country.
2. **The site's country turns it on.** The country is the one the site profile is checked against
   (`tb_common.derived.country_of`, D-1233). A country without a layer gets `None` from every reader, and the reader
   then gives its other-country default: the value a site with no layer had before.
3. **Every reader asks the layer by part and key** (`country_layer.value(country, "P9", "new_year_break")`): the
   set-up defaults (`site_country.from_layer`: P1, P5, P9, P11, P14), the committees (P3), the SAE rule set shown
   before a study chooses one (P2, `lifecycle.country_default`), the YJ stems (P7), the eGFR equation (P8), the
   holiday list and the New Year break (P9, `workdays.holidays`, `workdays.country_break`). The values are the ones
   the code held before, so a Japanese site behaves exactly as on master.
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
   - The schedule page's "Days off at this site" section (shown only at a site with a holiday list) says where the
     holidays and the New Year break come from (the country profile, its version) and, when the site set its own
     break, that the site's setting is used instead of the profile's, in en, ja and zh-TW.
6. **Versions and audit.** The layer ships in the signed update bundle, as the holiday list does (D-1230). Its
   version and digest are recorded with the site profile (`adapter.site_profile.activate`): the
   `terminology.site_profile_load` event and the active record carry `layer` (and `old_layer`). A load of the same
   profile under another layer version is recorded as a change. A country without a layer records exactly what it
   recorded before (no new key).
7. **No seventeenth switch unnoticed.** `tests/unit/test_japan_profile_layer.py` lists P1 to P16 by name, names the
   parts declared but not built (P4 Roles, P6 Forms, P12 Money, P13 Registries, P15 Procurement and security), and
   scans product code (`libs/`, `services/`, the box's set-up tools) for every string that names Japan (`JP`, `jp`,
   `jpn`, `Japan`, `Asia/Tokyo`). Each one left is listed with its reason (the zone reading, data labels, the
   country answers); a new one fails the test with the instruction to put the behaviour in the layer.

## What this does not change

No behaviour, default or stored value of any site. Each part not built stays declared (the card that builds it adds
its values and readers). The guard (P10), the device-claims lint (P5) and the CJK layout rules (P16) stay on for
every site, as the layer says (`everywhere`). No route, export, role or reader of patient data is added.

## Open questions with the owner (the layer carries today's behaviour)

- Whether the head-of-institution permission applies to all three Japanese study kinds (P3; today: both records for
  every kind, the lane J lead's ruling of 2026-11-19).
- Whether a running study is stopped when the Japan rule arrives (P3; today: a study open before the rule is marked
  `before_rule` and not held for a kind not chosen, D-1227).
- What a missing assent does (P11; today: a minor's record without assent warns, D-1232).

## Consequences

The next Japan card adds its data to its part and reads it with `country_layer.value`; a second country is one more
file in `country_layer.FILES` and its own parts. Known limit: the console and the orchestrator read the layer from
the image, while the night stamps it at the profile's load, so after an update brings a new layer version the site
profile's record names the earlier one until a person loads the profile again (the new version is in force from the
update, as the holiday list is).
