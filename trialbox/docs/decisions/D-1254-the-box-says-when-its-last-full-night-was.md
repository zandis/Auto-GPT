# D-1254 The box says when its last full night was (10B-23)

- **Card:** 10B-23 (lane J; first announced as 10B-20, an id the plan already uses) · **PR:** #1233 (branch `agent/10b20-last-full-night`) · **Date:** 2026-11-19
- **Status:** proposed.
- **Why:** a delta night reads only a window. Some changes are outside every window: a record the hospital re-files
  from one patient to another, a chart merge followed by re-filing, an SS-MIX2 file back-filed with an old 発生日時
  (D-1252 section D: "a site that back-files runs full nights"). Each is corrected by the next **full** night. Nothing
  told the site how long ago that was.
- **Decision:**
  - **The record.** The lake keeps `full_nights.json` beside the snapshots (`adapter.full_nights`): `last_full`, the
    snapshot date of the last full night that completed, and `deltas`, the snapshot dates of the delta nights that
    completed after it (the page shows their count; a night run again is counted once). Dates only, no patient data.
    Written atomically (a temporary file, then a rename), only when a night **completes**: it ends published on its
    own run (`adapter.pipeline`, `passed and not held`), or the steward's accept publishes it while held
    (`adapter.publish.publish_held`, whether it read whole from its own `ingest_report.json`; unreadable: not moved).
    A night that fails, is refused (a future date, no room, the site key) or ends held changes nothing. A full night
    is one run without `since` (also a delta night read whole because the site profile changed, 10B-6). An older
    night never moves the record back. A record that cannot be written is logged and never fails the night.
  - **Not known, never a guess.** A lake without the file (installed before this card) has no record. Its first
    completed delta night writes `last_full: null` with itself counted, so the page says "not known" only once a
    delta night has run. A file of another shape is not read (the next completed night writes it anew).
  - **To the page without a new reader.** Each night's audit event (`ingest.done`, `ingest.held`, `ingest.failed`)
    carries the record as it stands (`full_night`: the date or null, and the count; a failed night only when the lake has a record, so its event is unchanged otherwise). The batch row keeps it
    (`datacore.dataops.DETAIL_KEYS`), as it keeps the site profile's counts (D-1233). The existing `/data-ops` page
    takes it from the newest row that carries one (by id, among the rows it already reads: the sources and the
    history page), so a running or refused night does not hide it.
  - **The line.** In the *Sources* card's counts area: "Last full night: <date> (N days ago), M nightly updates
    since", or "Last full night: not known, M nightly updates since". In en, ja and zh-TW (`console.i18n_dataops`).
  - **The warning, and the 7.** `console.dataops_page.FULL_NIGHT_STALE_DAYS = 7`, a constant, not a setting. The line
    is in the page's warning style (`class="warn"`), with one sentence on what a full night corrects, when the last
    full night is **more than** 7 days old and a delta night ran since, or not known and a delta night ran since. 7
    days old is not warned; 8 is. Why a week: the night's weekly work (the Monday micro-batch of every study and NAV,
    D-492) then always runs within a week of a full night, so a correction only a full night makes waits at most one
    weekly run. A full night with no delta night since is not warned at any age: nothing it corrects can have been
    missed.
  - **Who sees it.** Exactly the accounts that read the page's counts: `dataops.view` (the steward and the
    administrator). No route, page, export, role or matrix cell is added or changed. `GET /api/v1/data/sources` (the
    same right) answers each row's `detail` whole, as before, so `full_night` is in it for the same accounts.
  - **Not on the home page.** The home page's health (`bk.health`, the administrator's) and the operations tile
    (`ops_summary`, backups and the agent) carry no data-operations warning today. Adding one would be a new
    mechanism, so the line stays on `/data-ops` only.
  - **Master's bytes.** With no record, or a record that says not known with no delta night, no line is rendered and
    the *Sources* card is master's, byte for byte.
- **Not in this decision:** a scheduled full night (the site decides when to run one); the morning mail; the lag of
  an accept: the row of an accepted night keeps the record as it was when the night was held, so the page shows the
  accept's effect from the next night's event.
- **Held by:** `tests/unit/test_full_nights.py` (a full night writes it; delta nights counted once each; held, failed
  and refused nights change nothing; not known; the steward's accept; a damaged file; never moved back) and
  `tests/console/test_dataops_full_night.py` (the line in three languages; the 7-day boundary on both sides; not known;
  the newest row that carries it; another shape; the role walk over every role of the matrix, page and API; master's
  bytes, `dataops_sources_master.json` rendered from master `f6c42230`).
- **How to revert:** `services/adapter/full_nights.py`, its two calls (`pipeline`, `publish`), `full_night` in the
  night events and `DETAIL_KEYS`, `full_night_of` and the template line. The lake's file is then ignored.
