**D-215 Wave-1 leftovers: a lab row's own unit, one encoding detector, one dates module, two reason codes.**

Task: T-118 (WS-01.2, WS-01.4 modules). PR: this branch (`agent/T-118-wave1-leftovers`). Date: 2026-11-09.
Status: proposed (Fable adversarial review of `labvalue.py` pending, §3.0 rule 6).
Source: `docs/reviews/2026-11-09-assessment-and-tasks.md` card T-118; MR-002 (R-31), MR-013 (R-33), MR-015 (R-95),
MR-018; review part 04 E-05 and E-15.

*Unit mismatch (R-31).* `tb_common.labvalue.read(text, row_unit, lookup_unit)` returns `Reading(value, comparator,
reason)`. A value comes back only in the lookup's unit and only when **no conversion is needed**: the row names no
unit (the site's declared unit, as D-149's `unit_defaults`), or both units are the same UCUM code or one of its
spellings in `labvalue.UCUM` (`mg/dl` is `mg/dL`, `µmol/L` is `umol/L`, `ug/mL` is `mg/L` by definition). Everything
else is no value with `unit_mismatch`: a different unit even a factor away (a CRP in mg/L against an mg/dL lookup is
not divided by 10), a unit the table lacks on either side (even spelled the same), a row unit with a lookup that
declares none. Case is folded only for quotients (`MG/DL`), never for a bare symbol (`M` molar, `m` metre); `U` and
`[IU]` are kept apart. No value is unknown to the engines and never excludes (D-130). The adapter's `lab_value`
builder takes an optional `unit_column` and the lab lookup an optional `source_unit` column (the unit the source
reports before the lookup's `factor`; without it, `ucum` when the factor is 1, else nothing to check against, so a
row unit gives no value). A mismatch writes no `value[x]` but `dataAbsentReason` (`error`, text `unit_mismatch`) and
the row's text as a `note`. A mapping without `unit_column` (every shipped mapping) maps exactly as before.

*One encoding detector (R-33, MR-013).* `tb_common.encoding.detect(bytes, candidates=("cp932", "big5"))` returns
`(codec, confidence)`. A BOM, or valid UTF-8 that reads as usual text, is UTF-8. Otherwise each candidate that decodes
the whole file strictly is scored on what it decodes to (JIS level-1 kanji and kana for CP932, the frequent-hanzi
block for Big5, half-width katakana only in runs that can start a word): Big5 read as CP932 is half-width katakana
glued to ASCII and scores near zero. Confidence is `best * (1 - (second / best) ** 4)`; below 0.6, or when nothing
decodes, or when the file mixes UTF-8 and non-UTF-8 lines, `EncodingRefused` (`FORM-ENCODING`, with the line). The
reader is strict; a U+FFFD in the result is refused too. The sheet and chart readers of site set-up, the licensed
masters and SS-MIX2 extended storage call it; each keeps its own page-facing error code (`SHEET-READ`, `CHART-TEXT`,
`LIC-ENCODING`) with the refusal's text, because the console's i18n files are not this card's.

*One dates module (E-05, MR-015).* `tb_common.dates`: `parse(text, lang, era=True)` reads one date (ISO, `YYYYMMDD`,
和暦 with era bounds, 民國, `112/03/15`, `1120315`, and `112年3月15日` without 民國); `read` returns `(None,
"check_dates")` for written but unreadable text; a two-digit year with 年 and no era is ROC only for `zh-TW` (1999 in
Japan), a three-digit 1xx always. `find` is CASE's in-text finder; `CHART_SPAN`, `PHI_SPAN`, `DOB_SPAN` are the
detectors' patterns. The six modules (PHI guard, the stub chart reader, CASE, site set-up's chart date, the messy
sheet reader, the guard's DOB recogniser) take them from here **unchanged**: a corpus recorded from master before the
module existed (`tests/fixtures/dates/six_modules.json`, committed first) is replayed byte for byte, and the pattern
strings are asserted equal. The one intended change: the sheet reader reads `112年3月15日` (kind `minguo`).

*Reason codes.* `reasons.py` gains `unit_mismatch` and `unknown_value` with en / ja / zh-TW words; the candidate page
and the site set-up patient page already render reasons through `reasons.py`.

*Not done here.* (1) The SQL template does not yet write `unit_mismatch:` / `unknown_value:` into an unknown value
atom's evidence (the `derived_*` precedent): that changes the IR snapshot `tests/fixtures/ir/snapshots/ATOMS.sql` and
every committed ruleset's SQL, which are golden fixtures owned elsewhere this wave; so a mismatched row is unknown on
the page with today's reason (`data_gap`), not yet with its own words. (2) `hypothesis` is not a dev dependency: the
property tests skip cleanly (they pass with it installed); seeded sweeps run without it. (3) `services/datacore/
sources.py` and the console's REDCap dictionary import (`errors="replace"`) still decode on their own. (4)
`site.err.FORM-ENCODING` words need the console i18n file. (5) The detectors' span patterns differ from one another
(the PHI guard misses 和暦 dates): unifying them changes what is scrubbed and needs its own review.
