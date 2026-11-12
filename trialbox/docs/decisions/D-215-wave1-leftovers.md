**D-215 Wave-1 leftovers: a lab row's own unit, one encoding detector, one dates module, two reason codes.**

Task: T-118 (WS-01.2, WS-01.4 modules). PR: this branch (`agent/T-118-wave1-leftovers`). Date: 2026-11-09.
Status: proposed; the Fable adversarial review (§3.0 rule 6) rejected the first version, and its findings are fixed
below (B1, H1, H2, M2, M3, L3).
Source: `docs/reviews/2026-11-09-assessment-and-tasks.md` card T-118; MR-002 (R-31), MR-013 (R-33), MR-015 (R-95),
MR-018; review part 04 E-05 and E-15.

*Unit mismatch (R-31).* `tb_common.labvalue.read(text, row_unit, lookup_unit)` returns `Reading(value, comparator,
reason)`. A value comes back only in the lookup's unit and only when **no conversion is needed**: the row names no
unit (the site's declared unit, as D-149's `unit_defaults`), or both units are the same UCUM code or one of its
spellings in `labvalue.UCUM` (`mg/dl` is `mg/dL`, `µmol/L` is `umol/L`, `ug/mL` is `mg/L` by definition). Everything
else is no value with `unit_mismatch`: a different unit even a factor away (a CRP in mg/L against an mg/dL lookup is
not divided by 10), a unit the table lacks on either side (even spelled the same), a row unit with a lookup that
declares none. Case is folded only for quotients (`MG/DL`), never for a bare symbol (`M` molar, `m` metre); `U` and
`[IU]` are kept apart. The units are judged first (`labvalue.units_agree`), whatever the text; a reading is
`labvalue.parse` only (no exponent, no `5.`, no `1_5`, no `NaN` or infinity: Fable B1). No value is unknown to the engines and never excludes (D-130). The adapter's `lab_value`
builder takes an optional `unit_column` and the lab lookup an optional `source_unit` column (the unit the source
reports before the lookup's `factor`; without it, `ucum` when the factor is 1, else nothing to check against, so a
row unit gives no value). A mismatch writes no `value[x]` but `dataAbsentReason` (`error`, text `unit_mismatch`) and
the row's text as a `note`; a declared `unit_column` the source rows lack stops the mapping (`MappingError`). The
shipped TW Core mapping (`tw_core/demo_his.yaml`, which the JP SS-MIX2 site and the CSV and CGRD templates extend)
now names `unit_column: unit`; both lab lookups gained `source_unit` (CRP `mg/dL` before its factor 10; the joint
counts `{count}`). The synthetic hospital's rows all agree with their lookups, so every golden, snapshot and
regression test is unchanged. Without `unit_column` the builder reads as before, except that `NaN` and infinity are
now text, not values.

*One encoding detector (R-33, MR-013).* `tb_common.encoding.detect(bytes, candidates=("cp932", "big5"))` returns
`(codec, confidence)`; its contract is the right text or a refusal, never wrong text. A BOM, ASCII, or valid UTF-8
with at least three usual non-ASCII characters is UTF-8; shorter UTF-8 is weighed with the legacy readings. Each
candidate that decodes the whole file strictly, and each rival nobody asked for (EUC-JP, GB18030, CP932, Big5), is
scored on what it decodes to (JIS level-1 kanji and kana for CP932, the frequent-hanzi block for Big5, GB2312 level 1
for GB18030; half-width katakana only in runs that can start a word, whatever stands next to them). The best
candidate must lead the other candidates (`best * (1 - (second / best) ** 4)` at least 0.6) and no rival may read
the file better; a non-UTF-8 file whose lines are read clearly by different candidates, or that mixes UTF-8 and
non-UTF-8 lines, is refused with the line. Otherwise `EncodingRefused` (`FORM-ENCODING`). The reader is strict; a
U+FFFD in the result is refused too. A sheet with only a few short cells can be read alike by two character sets
and is refused (the seeded sweeps: under 1 % of sheets with text in every row, up to 20-40 % of sheets with one short
cell); the person re-saves it as UTF-8. The sheet and chart readers of site set-up, the licensed
masters and SS-MIX2 extended storage call it; each keeps its own page-facing error code (`SHEET-READ`, `CHART-TEXT`,
`LIC-ENCODING`) with the refusal's text, because the console's i18n files are not this card's.

*One dates module (E-05, MR-015).* `tb_common.dates`: `parse(text, lang, era=True)` reads one date (ISO, `YYYYMMDD`,
和暦 with era bounds, 民國, `112/03/15`, `1120315`, and `112年3月15日` without 民國); `read` returns `(None,
"check_dates")` for written but unreadable text; a two-digit year with 年 and no era is ROC only for `zh-TW` (1999 in
Japan), a three-digit 1xx always; a four-digit year is read only from 1900 to 2099 (Fable M2). `find` is CASE's in-text finder; `CHART_SPAN`, `PHI_SPAN`, `DOB_SPAN` are the
detectors' patterns. The six modules (PHI guard, the stub chart reader, CASE, site set-up's chart date, the messy
sheet reader, the guard's DOB recogniser) take them from here **unchanged**: a corpus recorded from master before the
module existed (`tests/fixtures/dates/six_modules.json`, committed first) is replayed byte for byte, and the pattern
strings are asserted equal. The one intended change: the sheet reader reads `112年3月15日` (kind `minguo`). Fable
diffed about 68,000 inputs through all six modules on master and on this branch: only that change, and no
difference in what the PHI scrubbers find.

*Reason codes.* `reasons.py` gains `unit_mismatch` and `unknown_value` with en / ja / zh-TW words; the candidate page
and the site set-up patient page already render reasons through `reasons.py`.

*Not done here.* (1) Acceptance (1) is **partial**: a CRP in mg/L against an mg/dL lookup is unknown, and the words
exist in three languages, but the SQL template does not yet write `unit_mismatch:` / `unknown_value:` into an
unknown value atom's evidence (the `derived_*` precedent). That changes the IR snapshot
`tests/fixtures/ir/snapshots/ATOMS.sql` and every committed ruleset's SQL, golden fixtures owned by another session
(coordinator ruling: not changed here); so the page shows the row as unknown with `data_gap`, not yet with its own
words. The goldens' owner regenerates them with that template change. (2) `hypothesis` is not a dev dependency: the
property tests skip cleanly (they pass with it installed); seeded sweeps run without it. (3) `services/datacore/
sources.py` and the console's REDCap dictionary import (`errors="replace"`) still decode on their own. (4)
`site.err.FORM-ENCODING` words need the console i18n file. (5) The detectors' span patterns differ from one another
(the PHI guard misses 和暦 dates): unifying them changes what is scrubbed and needs its own review.
