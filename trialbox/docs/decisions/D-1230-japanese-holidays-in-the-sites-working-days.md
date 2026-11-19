# D-1230 Japanese holidays and the New Year break in the site's working days

- **Task:** card 10C-14 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C, commitment C-7; review card
  JP-15, `docs/reviews/2026-11-root/11-japan.md`)
- **Date:** 2026-11-19
- **Status:** accepted; the number is reserved for this card (lane J's block D-1220 to D-1319)
- **Builds on:** D-134 (visit windows on the site's date), D-270 (the site's "today"), D-277 and D-766 (the SAE
  clocks count calendar days), D-315 (the site's zone is one setting), D-764 (a weekend digest carries the overdue
  SAE reports only)

## Context

A working day was decided in one place, the coordinator's digest (`console.notify`: Monday to Friday). Visit windows
counted calendar days. Japan's public holidays and the New Year break (年末年始) were nowhere in the product; the
holiday list existed only for plan dates (`tools/gen_calendar.py`).

## Decision

1. **One calendar, as data.** `tb_common.workdays` decides whether a day is a working day: Monday to Friday less the
   days off of the site's country. A country's holidays are a reference file, `libs/tb_common/refdata_src/
   holidays_<country>.csv` (`date,name,kind`); Japan's is the Cabinet Office's list for 2025 to 2027
   (`syukujitsu.csv`, read 2026-11-18, PDL 1.0, licence register row `jp-holidays`), names unchanged, with a kind
   (holiday, substitute, citizens). It ships inside the images of the signed update bundle beside TrialBox's other
   own reference files; it is read from there, not from the reference-data pack in the database, because its readers
   (the console's mails, the orchestrator's visit windows) run on every request and the pack is optional on a box.
   A new year's list comes with an update; the schedule page says how far the list goes.
2. **The country is the site's** (`derived.country_of(site.tz)`). A site with no country, or of a country with no
   file, has Monday to Friday exactly as before, and the site's changes below are not read.
3. **The New Year break** is the country's default (Japan: 12-29 to 01-03) and the site's to change, with its own
   days off and the holidays it works: `TB_NEW_YEAR_BREAK` (`MM-DD/MM-DD` or `none`), `TB_DAYS_OFF`,
   `TB_DAYS_OPEN` (declared settings in `deploy/.env`). The settings wizard asks the break for a country with a
   holiday list and writes it only when it differs; the other two go through the answers file's `env_extra`. A value
   that cannot be read is shown on the schedule page and not used.
4. **The mails.** On a day off the coordinator's digest is what a weekend gives (the overdue SAE reports only, logged
   `N2-SAE`), and the full digest comes on the next working day; the investigator's weekly list (clinic days
   unknown) goes on the week's first working day. The administrators' health mail stays daily.
5. **Safety is not delayed.** The SAE clocks never read the calendar: deadlines stay calendar days, and the SAE mails
   (N1's count, N2's reports, the case mailed at once) go every day.
6. **Visit windows** count working days only for a visit the protocol counts that way (a per-visit choice on the
   schedule page, stored with the schedule: the data core's version 10). Its days before and after are the site's
   working days; the due day stays the protocol's day number. Other visits count calendar days as before. The
   possible-deviation check reads the same windows.

## Consequences

A fuller page (a site editing its days off in the console, with an audit trail) is not built: the settings are set at
installation, as the other site settings are. Taiwan or another country is one more file and, where it has one, a
default break.
