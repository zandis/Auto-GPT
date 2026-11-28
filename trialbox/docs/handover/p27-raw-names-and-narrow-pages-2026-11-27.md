# P-27: raw event names on /audit, and pages cut off between 310 and 640 px

**Reader:** the people who build TrialBox: the integrator and the lane H lead. Findings for builders.

- **Card:** P-27, the integrator's R1+1 batch D, part H (7210967559, PR #1504). Base: `int/r1plus1` (3390bf74).
- **Date:** 2026-11-27
- **Findings:** [`p27-raw-names-and-narrow-pages-2026-11-27/findings.json`](p27-raw-names-and-narrow-pages-2026-11-27/findings.json)
  (P27-01 to P27-03)
- **Files:** `services/console/i18n_audit.py` (twelve labels), `services/console/static/console.css` (one phone
  block at its end), the new `tests/console/test_untranslated_and_narrow_p27.py`.
- **Files outside the card:** none.

## 1. Raw event names (flow.export)

`/audit` shows an event by its label, and by its bare name when it has none. `test_audit_browser`'s label walk reads
only the literal first argument of an `append`. So twelve events were missed, because their writers name them
through a module constant (`flowledger.EVENT` = `flow.export`, `egress_record.EVENT`, `acting.AUDIT` and others).
They showed as raw names on the page and in its event filter.

The new walk resolves a constant of the same module, `from <module> import NAME` and `<module>.NAME`. Each of the
twelve now has a label in three languages. A test renders `/audit` in en, ja and zh-TW with every such event and
finds no bare name: neither in a label cell (the code beside it is D-451's hint) nor in the filter.

## 2. The catalogue

A test checks that ja and zh-TW hold every English key, and that neither holds English text, in either of two ways:
- a text equal to the English one with a lower-case word in it;
- three lower-case words in a row, outside a command (`trialbox`, `docker` or `python`), placeholders, tags, paths
  and code.

The catalogue passes as it stands. The 24 texts equal to the English one are names (TrialBox, REDCap, CDASH,
English, WHO ICTRP). A second test proves that the rule fails on English left in place.

## 3. Narrow windows

Below 640 px, `html` and `body` clip sideways (T-684, so that sticky bars keep sticking). Whatever is wider than the
window is cut off, not scrolled, so `scrollWidth` reads as if nothing were wrong. A browser walk measured every GET
page that the administrator and the coordinator can open on the test box, in three languages, at 310, 360, 414,
480, 540 and 619 px. It counted every element that ends past the window's edge with no scrolling box around it.

- **On the base:** 31 of the 345 pages cut something off. Most were tables with no scroll box; the others were a
  form field, a select inside a label, a Japanese button label, the setup page's save bar (its negative side
  margins) and the code sheet's file field.
- **Now:** none. One phone block at the end of `console.css` does it:
  - a table with no `.scroll` box of its own scrolls in itself;
  - a field, a pill, a button and an inline form's items keep to the window's width;
  - the file field takes the width;
  - the save bar loses its side margins.
- A table inside `.scroll` keeps that box, with its focus ring (10F-1's test).

The committed layout test runs everywhere and reads the stylesheet:
- the phone rules are there, under the clip;
- no rule fixes a width of 310 px or more outside a wide-window query.

The browser walk is not committed. CI has no browser outside the visual job, and a new browser test would have to
skip there (P27-03).

## 4. Not done, not verified

- Only the test box's pages were walked, with its synthetic data. Pages that need a study store or a job state the
  box does not have were not reached.
- The visual-regression job (not required) will show the phone shots changed. A person accepts the lines.
