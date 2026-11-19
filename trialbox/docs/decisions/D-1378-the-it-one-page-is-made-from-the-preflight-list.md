# D-1378 The one page for hospital IT is made from the preflight's check list, one per delivered form (10K-18)

- **Task:** lane K, plan 10 row 10K-18 (review 18 SO-18: "the IT one-page generated from the preflight's check list,
  per delivered form"; proved by "doclint compares the page with the list"). · **Date:** 2026-11-19
- **Why:** review 18 (1.2) counted twelve prerequisites in the IT form while the IT one-page told IT it was asked
  "only three things"; true of the box form only. The page was written by hand, so it could not follow the list the
  box checks (D-1361).
- **Decision:**
  - **Made, not written:** `tools/it_one_page.py` renders the page from `tb_common.preflight.ITEMS`: each item asked of
    IT is one line, its label and the next action the box shows when that line is not green (the list's own texts,
    without "then run the check again"), grouped as the list groups them, in en, ja and zh-TW. The count IT is told
    ("the N things below") is the count of those lines. Only the page's frame (title, reader line, the address and
    firewall line, whom to ask) is written in the tool, in the three languages; no item text is written anywhere but
    the list.
  - **Per delivered form (`FORMS`):** the box form (the supplier-prepared machine, decision 96, ruled) asks IT for six
    items (name and certificate, clock, mail relay, backup share, audit share, feed) and lists the other three (disk,
    key protection, graphics card) as the supplier's, with their labels only: the box form seals its keys to the TPM or
    the owner's passphrase, and Tang is the IT-installed form's (`tools/box/plan.py`, T-634). The IT form asks IT for
    all nine, after RUNBOOK §1's own prerequisites, which the page names and does not repeat. The box form's pages
    keep the name `docs/handover/it-one-page.<lang>.md` (linked by the RUNBOOK and the network sheet); the IT form's
    are `docs/handover/it-one-page.it-form.<lang>.md`.
  - **doclint compares the page with the list** (check `one-page`, failing): every id of the list placed exactly
    once per form (asked of IT or prepared by the supplier), no id a form names that the list lacks, every frame text
    and every item's label and action present in each language, and each committed page equal to what the list
    makes (missing, edited by hand, or stale after a list change: "run `python -m tools.it_one_page`"). A check added
    to the list therefore fails doclint until a form places it. `python -m tools.it_one_page --check` prints the
    same.
- **Not in this card:** a site's own page (with its name and shares filled in) at install; the page in the offline
  media's `docs/` (`tools/linux_media.py` copies the network sheet only); the page as a console download.
- **Held by:** `tests/unit/test_it_one_page_10k18.py` (the committed pages clean; a list label changed fails both
  pages of that language through doclint; a page edited by hand or missing; a check added to the list and placed in
  no form; an id the list lacks or placed twice; a text missing in a language; each page holds its form's items in
  its own language and no English item text in ja or zh-TW; the count 6 and 9; one page, its reader line, doclint's
  document checks; the command line run once without `PYTHONUNBUFFERED`), `tests/unit/test_runbook_readers.py` (IT has
  one page in each language).
