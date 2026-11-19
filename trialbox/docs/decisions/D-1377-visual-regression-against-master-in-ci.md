# D-1377 Visual regression in CI: 72 first screens of the pull request against its base, no picture in git (9k-17)

- **Task:** plan 10 track F, the carried card 9k-17 (DS-17) of plan 9 rev 2 §3.5, from review 09
  (`docs/reviews/2026-11-root/09-ux.md` §5.3). Waits for 9k-1 (D-1368, on master since train 99). · **Date:** 2026-11-19
- **Decision:**
  - **What is shot:** twelve pages, each in en, ja and zh-TW at 1280 x 860 and 390 x 844: the four roles' homes
    (investigator, coordinator, steward, administrator), the week page, the patient sheet, the full patient page, the
    candidate registry, the SAE register, study set-up, the administrator's page and help: 72 first screens (the
    window, not the whole page). Review 09 named the participant page, the AE form, the SAE case and the review queue;
    the test box has no EDC record or form for them, so the registry, the SAE register, the patient page and help stand
    in (the list is one tuple in `tests/console/visual_pages.py`; a later card adds a page by adding a row). The
    account page was left out: it shows the real time of the last sign-in.
  - **How:** `tests/console/visual_pages.py` runs in the tree being shot, with that tree's console and its in-process
    test box (`tests/console/test_console_app.py`: a fake orchestrator, the synthetic study GZQO, the account store in
    a throwaway PostgreSQL of `tools/pglocal.py`), the console's clock pinned to 2026-10-07 09:30 UTC, the form tokens
    blanked; it writes each page with that tree's `console.css`. `tests/console/visual_shots.js` photographs them in
    Chromium through the locked Node Playwright of `tools/package.json` (light scheme, reduced motion, animations
    stopped, caret hidden, scale 1). Two shootings of one tree on one machine gave the same 72 pictures.
  - **Compared with master, nothing stored:** the job (`.github/workflows/trialbox-visual.yml`) checks the base branch
    out beside the pull request (`git worktree`), shoots both with the pull request's scripts on one runner, so the
    browser and fonts are the same on both sides, and compares (`tools/visual_regression.py run`). No baseline image is
    committed; a font or browser update on the runner changes both sides alike.
  - **A difference** is a shot with more than 0.1 % of its pixels changed (review 09), a shot on one side only, or a
    page that could not be drawn (a page the pull request cannot draw stops the job with exit 2: it cannot judge).
    Each is shown in `index.html` of the job's files: master, the pull request, and the changed pixels in red over the
    faded new screen, with `report.md` in the job's summary.
  - **Reviewed** means the file `tests/console/visual_accepted.txt` holds `<shot> <hash>  # reason`, the hash being the
    sha256 of the new picture's size and RGBA pixels (not of the PNG bytes): a person looks at the side-by-side page and
    commits the lines the job printed. A line accepts that picture only; the next change to the page differs again,
    and a line for a picture no longer drawn is harmless. **The job fails on any unreviewed difference** (exit 1).
  - **When it runs:** on a pull request that touches `trialbox/services/console/`, the scripts or the workflow, in a
    workflow of its own with a `paths` filter, 30 minutes at most (about 20 seconds per side measured here, plus the
    environment and Chromium install). It is not a required check: whether it becomes one is the owner's choice, and a
    required check would have to move into `trialbox-ci.yml` behind its `changes` job (a paths-filtered workflow that
    never starts blocks a required check). No new dependency: Pillow is already installed (reportlab's), Playwright is
    the walks' locked one; on a GitHub-hosted runner of a public repository it costs nothing.
  - **Not dark mode:** the 72 are the light scheme, as review 09 counted them; D-1368's contrast test holds both
    schemes' colours. A dark set doubles the job and is left to a later card if a dark-mode regression is ever missed.
- **The proof:** `tests/console/test_visual_regression_9k17.py`: the comparison (same, under 0.1 %, over it, one side
  only, not drawn; exit 1; a reviewed line accepts its picture only; the hash is the pixels'), the 72 names, the
  workflow (pull request trigger, base checkout, the tool's exit code is the job's, the files kept), and in Chromium
  two shootings giving the same 72 pictures and a planted style change failing the comparison until each of its lines
  is accepted. Run here against master: 72 of 72 the same, with 9k-3 (D-1375) on top.
- **Not verified:** the job has not run on GitHub yet (its first run is this pull request's); the runner's fonts are
  those `playwright install --with-deps` brings, not a hospital's; no native reader has read the ja and zh-TW shots.
- **Held by:** `tests/console/test_visual_regression_9k17.py`; `tools/visual_regression.py`;
  `.github/workflows/trialbox-visual.yml`.
