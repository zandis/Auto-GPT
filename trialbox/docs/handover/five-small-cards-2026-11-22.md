# H-87: five small parts (2026-11-22)

**Reader:** the people who build TrialBox.

**Pull request body (draft).** Card H-87, lane H. Five small parts, one commit each (part 2 has a second commit for
the workstation follower). It merges #1340's branch (H-81) for part 5, so it rides after #1340. D-1086 is not added
here: #1346 (H-83) is not on master.

- **Card:** H-87 (not high-risk)
- **Decision:** none new. Part 3 cites the owner's ruling D-1075 (its record is not in the tree; not created here).
- **Files outside the card:** `tools/runbook_workstation.py` (the follower's table `KNOWN`: two rows for the new
  commands of page 27 step 7); `docs/security/02-network.md` and `docs/runbook/04-troubleshooting.md` (one paragraph
  each, as the ruling asks).

## Part 1: the commands put back the logging level they found

`backup_drill.main()`, `update_drill.main()`, `e2e_simple.main()`, `demo.main()` and `complete_run.run_part()` call
`logging.disable(logging.INFO)` and left it on (`demo` switched it back only on its serving path). In a test process
that broke every later test reading an INFO record: the polluter
`test_the_command_prints_them_and_where_the_folder_is` of `tests/unit/test_backup_drill_says_why.py`, the victims the five
INFO tests of `tests/unit/test_access_log_route.py`. `tools/logging_level.py` holds one wrapper,
`restores_logging_level`, a `try`/`finally` that puts back the level found on entry on a return, an exception and
`SystemExit`; the five use it. `update_drill.py`'s call in its child process is left (a process of its own). Nothing
under `services/` calls it. No lane R branch for card 9i-1 was found on the remote; the conftest fixture is not touched.

Tests: `tests/unit/test_logging_level_restored.py`, 13 cases (each command returns and raises; the drills also exit).
On the old code 12 of 13 fail. The polluter then the victims in one process: 5 failed before, 8 passed after.

## Part 2: the runbook pages name one card and take a backup

- Pages 28 and 29: the engine probe is `python3 tools/engine_probe.py run --gpu-args "--gpus device=0"`, with how to
  find the index (`nvidia-smi -L`) and that `all` (the command's default) is never used on a host with other work on
  other cards.
- Pages 27 (step 7) and 08 (the symptom table): before `nvidia-ctk runtime configure` rewrites
  `/etc/docker/daemon.json`, a dated copy when the file exists, and the command that puts it back.
- Page 28: the stale sentence ("the embedder has no such record") is corrected: the record
  `deploy/measured/embedder_files.e-embed-1.json` is on master and `tools/fetch_weights.py --embedder` fetches it, but
  only with a GPU profile's two models, so the manual download stays on that page.
- The pages have no ja or zh-TW copies. The test
  `test_the_follower_knows_every_command_of_section_27_and_no_other` holds page 27's commands equal to the follower's
  table (`tools/runbook_workstation.py` `KNOWN`): two rows are added there for step 7.

## Part 3: F-16's sentence

One paragraph in `docs/security/02-network.md` and one in `docs/runbook/04-troubleshooting.md`: `docker.service`
requires `trialbox-egress.service`, so when the egress table cannot be loaded Docker does not start, and every
container on the host stays stopped, others' too; fail closed, the owner's decision D-1075, not a defect; what an
operator sees and does. Neither "F-16" for the egress filter nor D-1075 was found in `docs/` on master or on #1333's
branch (which holds D-1069 to D-1071 only): the text cites them as relayed.

## Part 4: records

(a) `docs/handover/host-run-bench-exception-2026-11-22.json`: H74-02 and H74-04 take the basis `hypothesis`, the
register's "read from code or text, not run" (H74-02 was read in the code; H74-04 was reported by another session, not
measured). `findings_register --add-from` of the file passes in a scratch worktree (4 rows added there, `--check`
well formed); no register change is committed.

(b) Skipped: #1346 (`claude/lane-h-83-unit-split-measured-again`) is not on master, so D-1086 is not added.

## Part 5: the docs-only selection matches the strings of a test's code only

`tools/ci_docs_only.py` parses each test file with `ast` and matches the needles only against the string constants of
its code (an f-string's literal parts included), not the docstrings of the module, a class or a function; comments are
not code. A file that does not parse is matched on its whole text. `test_the_tool_needs_only_the_standard_library`
gets `ast` (ruled 11:56 UTC). New tests: `test_only_the_strings_of_a_tests_code_select_it`,
`test_on_this_tree_a_review_page_cited_in_a_docstring_selects_no_property_test`. This answers H81-01's open half.

Selected test files on this tree, H-81's rule (before) and this one (after):

| changed | before | after | dropped | added |
|---|---:|---:|---|---|
| a new page under `docs/reviews/` | 2 | 2 | – | – |
| a new page under `docs/handover/` | 5 | 5 | – | – |
| `docs/plan/47-plan-10-2026-11-18.md` | 2 | 2 | – | – |
| `D-1119-...md` and `REGISTRY.md` | 3 | 3 | – | – |
| `docs/runbook/21-...md` | 4 | 4 | – | – |
| `docs/reviews/2026-11-12-architecture/decision.md` | 5 | 1 | `tests/property/test_judge_in_loop.py`, `tests/property/test_path_independence.py`, `tests/unit/test_decision_context_lint.py`, `tests/unit/test_pool_version_basis.py` | – |

Each of the four dropped files cites the page in a docstring or a comment only; nothing that reads a page in code drops
out.
