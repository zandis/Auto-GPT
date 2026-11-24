# H-81: a page under docs/reviews/ no longer pulls a property test into the docs-only cross-card run

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-81 (the integrator's red of 2026-11-22, 11:08 UTC: #1327 and #1332 wait on it)
- **Date:** 2026-11-22
- **Decision:** none; the selection rule of [D-969](../decisions/D-969-a-docs-only-pull-request-runs-the-fast-tier.md)
  is kept and its folder match narrowed (see the question at the end)
- **Findings:** [`docs-only-cross-card-reviews-2026-11-22/findings.json`](docs-only-cross-card-reviews-2026-11-22/findings.json)
  (H81-01 to H81-03)
- **Tests:** `tests/unit/test_ci_docs_only.py` (two new), `tests/property/test_path_independence.py` (two new)
- **Files outside the card:** `tests/property/test_path_independence.py` (T-705, D-459): the fixture body only,
  asked of lane H by the integrator; no assertion changed

## Pull request body (draft)

**The cause, from the logs.** Jobs 137168755036, 137169956446 (#1327) and 137186838469 (#1332) each have 277 errors,
all at the setup of `tests/property/test_path_independence.py` (258 `test_the_same_patient_gets_the_same_answer_on_every_path`,
17 `test_an_opted_out_patient_is_in_no_published_bytes`, `test_the_world_is_not_vacuous`,
`test_a_status_does_not_depend_on_how_many_patients_are_in_the_run`). Both texts are in all three jobs (244 + 33,
244 + 33, 72 + 205): `AssertionError: JobError(step='reporting', ... detail='ReportError')`, whose log line is
`font NotoSansTC-Regular.ttf not found in /opt/trialbox/fonts, .../.cache/fonts`, and
`FileExistsError: .../path-independence/build-<pid>/sec`. Every `FileExistsError` of a job names the same pid
(9860, 10134, 10081). So it is one cause, not workers racing for one folder:

1. The docs-only step selects test files by name (`tools/ci_docs_only.py`, D-969). For a page under `docs/reviews/`
   the folder needle `docs/reviews` matched any test whose text names any review, in a docstring or a comment:
   10 files on #1332, 23 on #1327 (it changed more folders), `tests/property/test_path_independence.py` among them
   (its docstring cites `docs/reviews/2026-11-12-architecture/decision.md`).
2. The `cross-card` job has no fonts and no JVM ("none of them needs one"), so the world's SCREEN job fails in
   reporting. The fixture builds the world once under a file lock; the first build failed.
3. The world fixture is module-scoped. Under `--dist worksteal` (H-73; `make cross-card` runs `test-locked`, the
   logs show it) a worker leaves the module and comes back, and the fixture is asked again. It built again into the
   same `build-<pid>` folder, where `sec` was already made: `FileExistsError`, which hid the font error.

**Fix A** (`tests/property/test_path_independence.py`, fixture body): the locked build is now `shared_build`. Each
attempt builds in a folder of its own (`tempfile.mkdtemp(prefix="build-<pid>-")`); a failure is written to
`world.failed` and raised again, with its text, to every later request of the run instead of a second build. The
world is still built once per run and read by every worker; no assertion changed. Nothing is fetched into the
folder: the fonts are read from `FONT_DIRS`.

**Fix B** (`tools/ci_docs_only.py`): a folder is named by the folder itself (`"docs/runbook"`,
`"docs/runbook/*.md"`, `f"docs/runbook/{page}"`), not by the path of another document in it. A document's own path
and file name match as before. Selected test files, before and after, for one changed page:

| changed | before | after | dropped |
|---|---:|---:|---|
| a new page under `docs/reviews/` | 10 | 1 | 9: both `tests/property` files, `test_step4b` and six unit tests citing a review |
| a new page under `docs/handover/` | 19 | 5 | 14: they name other handover pages (`test_findings_register` keeps its own page) |
| `docs/plan/47-plan-10-2026-11-18.md` | 19 | 2 | 17: they name other plan pages or `docs/plan/measurements/...` |
| `D-1119-...md` and `REGISTRY.md` | 6 | 3 | 3: they name other decisions (D-1343, D-370, D-381, D-1102) |
| `docs/runbook/21-...md` | 18 | 4 | 14: they name other runbook pages (`test_runbook_25_leaver` reads page 25) |

Every dropped file names only other documents of the folder by path; none names the folder itself, so a change to
the page cannot reach what it reads. The lists are on this page's folder in `selection/`.

**Reproduced.** `make cross-card PYTEST_N=auto CROSS_CARD_TESTS=<the list>` (4 workers, a fresh test root):

- before, the 10-file list, no fonts: 247 passed, 1 skipped, 277 errors (CI's counts), `FileExistsError` in it;
- Fix A, the 10-file list, no fonts: 249 passed, 1 skipped, 277 errors; no `FileExistsError`, the 161 later
  requests say "failed to build, not built again: ... ReportError";
- Fix A, the 10-file list, fonts and JVM fetched: 527 passed, twice;
- both fixes, the new 1-file list: 3 passed, 1 skipped (three runs, no fonts); 4 passed with fonts.

The two regression tests fail on the old code: `test_a_failed_build_is_raised_again_not_built_again` with CI's
`FileExistsError ... build-<pid>/sec`; `test_on_this_tree_a_review_page_selects_no_property_test` and
`test_a_folder_is_named_by_itself_not_by_another_document_in_it` on the old selection.
`.github/workflows/trialbox-ci.yml` is not touched, so nothing collides with #1295.

**Question.** A docstring or a comment still selects when it cites the changed page by path or file name:
a change to `docs/reviews/2026-11-12-architecture/decision.md` selects both `tests/property` files again and would
be red the same way. Matching only the strings of a test's code needs `ast`, and
`test_the_tool_needs_only_the_standard_library` lists the imports allowed (`re`, `sys`, ...); adding `ast` to it
changes what it asserts, so it waits on the integrator's ruling.

## Findings

- **H81-01** (Medium, open, H): the docs-only selection pulls tests in by a citation in a docstring or comment;
  narrowed for folders here, not for a cited page's own path (the question above).
- **H81-02** (Medium, open, H): a module-scoped fixture whose build is shared through a file lock is asked again
  under `--dist worksteal`; a failed build was retried into its own leftovers and hid the first error. Fixed for
  `test_path_independence`; other shared builds of the same shape were not looked for.
- **H81-03** (Low, open, Int): the `cross-card` job runs the docs-only list without fonts or JVM; a selected test
  that needs them cannot pass there.
