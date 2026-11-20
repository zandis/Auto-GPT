# D-1264 The opening page's flag-off byte test strips the idle warning's seconds left, as its neighbours do (J-8)

- **Task:** lane J, card J-8: `tests/console/test_home_today.py::test_with_the_flag_off_the_home_is_byte_for_byte_the_page_without_this_card`
  (J-6, D-1225) failed now and then on 2026-11-19/20: once in a whole-tree run, once in a reviewer's parallel run,
  2 of 6 runs of lane H between 23:38 and 23:44 UTC; it passed alone every time. · **Date:** 2026-11-20
- **Cause (found, not guessed):** the idle warning of D-1370 (9g-19) puts the session's seconds left on every
  signed-in page: `data-idle-left` and `data-abs-left` in `_idle_warn.html`, from `UserStore.session_left`. That reads
  the sign-in store's clock (`UserStore.clock`, the wall clock in the test box), not the console's clock the test
  pins (`lb["clock"]`), and truncates to whole seconds: `data-abs-left` is 28800 minus the whole seconds since that
  render's own sign-in. The test signs in afresh before each of its six renders (three languages, with and without
  the J-6 parts), so a render that takes a second boundary longer after its sign-in than its counterpart differs in
  that one attribute. The test stripped the CSRF token only; it predates D-1370. The differing bytes, the only line
  that differs, in each language:

  ```
  -  data-idle="600" data-lead="60" data-idle-left="600" data-abs-left="28800" data-stay-url="/help"
  +  data-idle="600" data-lead="60" data-idle-left="600" data-abs-left="28799" data-stay-url="/help"
  ```

  A slow or loaded run makes the second boundary likely; the time of day does not matter. No date, hour, relative
  time, ordering of rows or flag value differs: the page's dates all come from the pinned console clock. Checked by
  (scratch, not committed) a loop of the test's two renders under four pytest workers that saves both bodies on a
  mismatch, and a wall clock run through UTC midnight, Taipei midnight and 23:30 to 00:30 UTC at 1x, 60x, 3600x and
  86400x (60x and faster: the differing line above, nothing else). A late background read of the layout flags
  (`console.phone`) landing after the next test's `clear_cache` was also checked and was not the cause.
- **Decision:** the page is right (it says how long the session has left, as D-1370 asks); the test was wrong. The
  test:
  - pins the sign-in clock (`monkeypatch` of `lb["users"].clock`) and lets exactly one second pass between the
    sign-in and the page in the renders without the J-6 parts only. That is the failure made deterministic: with the
    CSRF-only comparison of master it fails every time (`28800` against `28799`, as above);
  - takes out the CSRF token and `data-(idle|abs)-left="N"` with the same pattern as its neighbours
    (`test_plain_menu.py`, `test_people_lists.py`, `test_tier_status_words.py` `_CSRF`, and the 9g-19 fix of three
    more, commit 478b7193). Everything else stays byte for byte; the test also asserts the idle warning is on each
    page compared, so the stripping cannot hide a page without it.
- **Evidence:** the test passes on this head; 200 runs of it under four pytest workers (`-p xdist -n 4`): 200 passed,
  0 failed; 10 more under the 60x wall clock that breaks the old comparison: 10 passed.
- **The same pattern elsewhere** (byte comparisons of two signed-in renders in `tests/console` that keep the live
  seconds):
  - lane J: none left. `test_plain_menu.py` (J-7) and `test_people_lists.py` (J-5) already strip them;
    its line 483 compares `<main>` only, where the warning is not.
  - other lanes, for the coordinator, not touched: `test_dates_setting_and_nendo.py` line 215 (10C-15:
    `c.get(path).text == before`, the whole page twice in one session) and `test_committees_10c4.py` line 589 (10C-4:
    the signed-in browser's 404 page for `committee` against `no-such-route`, whole text). Both can differ by one in
    `data-abs-left` when a second boundary falls between the two asks.
  - not affected: `test_japan_profile_layer_page.py` (one section against stored master bytes),
    `test_consent_by_a_representative_and_assent.py` (no second render), `test_console_timing.py`,
    `test_job_page_progress.py`, `test_header_search_off_log.py` (already strip them).
- **Not changed:** the page, the idle warning, `session_left`, what any role may do or read.
