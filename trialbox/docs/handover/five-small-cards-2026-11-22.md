# H-87: five small parts (2026-11-22)

**Reader:** the people who build TrialBox.

**Pull request body (draft).** Card H-87, lane H. Parts 2 to 6, a commit or two each; part 1 was dropped
(lane R's card 9i-1, ruled 13:11 UTC) and its commit is taken back out by a later commit, so its files are as on
master. It merges #1340's branch (H-81) for part 5, so it rides after #1340.

- **Card:** H-87 (not high-risk)
- **Decision:** D-1086 recorded (the integrator's number for H-83's decision). Part 3 cites the owner's ruling
  D-1075 (its record is not in the tree; not created here).
- **Findings:** [`five-small-cards-2026-11-22/findings.json`](five-small-cards-2026-11-22/findings.json) (H87-01)
- **Files outside the card:** `tools/runbook_workstation.py` (the follower's table `KNOWN`: two rows for the new
  commands of page 27 step 7); `docs/security/02-network.md` and `docs/runbook/04-troubleshooting.md` (one paragraph
  each, as the ruling asks); `docs/decisions/REGISTRY.md` (one row, at the end of the file).

## Part 1: dropped

The commands' logging level is lane R's card 9i-1 (ruled 13:11 UTC). The part's commit (`tools/logging_level.py`, its
test and the five commands' wrappers) is taken back out by a later commit; the five files are as on master.

## Part 2: the runbook pages name one card and take a backup

- Pages 28 and 29: the engine probe is `python3 tools/engine_probe.py run --gpu-args "--gpus device=0"`, with how to
  find the index (`nvidia-smi -L`) and that `all` (the command's default) is never used on a host with other work on
  other cards.
- Pages 27 (step 7) and 08 (the symptom table): before `nvidia-ctk runtime configure` rewrites
  `/etc/docker/daemon.json`, a dated copy when the file exists, and the command that puts it back.
- Page 28: the stale sentence ("the embedder has no such record") is corrected: the record
  `deploy/measured/embedder_files.e-embed-1.json` is on master and `tools/fetch_weights.py --embedder` fetches it, but
  only with a GPU profile's two models, so the manual download stays on that page.
- Page 29: the step that switched the host to `multi-user.target` was there to free the card's memory the desktop
  holds. It now has the operator see what holds the card first (`nvidia-smi`'s "Processes"; anything but the desktop:
  stop and send the lines), and stops and starts `display-manager` only. Nothing host-wide is switched; the page names
  `systemctl isolate multi-user.target` as what is not done (`test_dgpu48_draft.py` reads that name: unchanged).
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

(b) D-1086: `docs/decisions/D-1086-eight-unit-shards-pinned-from-a-measured-table.md`, pointing at H-83's page
(on master since 5cca57cb), with a `reserved` row at the end of `REGISTRY.md`, away from #1333's rows after D-1068.

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

## Part 6: the unit-shard pins looked at again (train 125)

The eight unit-shard jobs of train 125 (run 45024159918, the first run of H-83's split), from the public API and the
job logs; minutes of pytest, and the cost table's estimate under the same pins:

| shard | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| measured (pytest minutes) | 13.7 | 15.5 | 15.1 | 29.5 | 19.8 | 23.3 | 11.6 | 30.1 |
| H-83's table, estimated | 16.8 | 16.8 | 16.8 | 16.1 | 16.2 | 16.7 | 16.4 | 16.1 |
| seconds a test outside the slowest 30 | 0.74 | 1.01 | 1.02 | 2.25 | 1.44 | 1.39 | 0.58 | 2.48 |

The listed files explain part of it: `tests/console/test_prefs_10f1.py` 1,943 s (the table: 1,345),
`tests/integration/test_e2e_simple.py` 711 s (480), `tests/console/test_orch_box.py` 342 s (141). Most of the
excess of shards 4 and 8 is in tests below their 30 slowest. A local collection with CI's markers gives each shard's
test count to within 4 of CI's.

**The pins are left as they are.** A table refreshed from this run (each listed file at its measured time, every
other test at its shard's seconds a test) reproduces the eight measured shards exactly, but its plan (20 pins) pins
files whose cost is only their test count times their shard's average:
`tests/unit/test_negated_inclusion_never_compiles_as_presence.py` comes out at 1,097 s with none of it listed, and
seven more like it. Its estimate, 19.3 to 22.1 minutes a shard, is still 11.4 % over the mean for one shard (30
pins: 7.6 %, mostly on such inferred costs). One run with the slowest 30 tests a shard cannot say which files are
heavy, so a new plan would move guesses. What would: every test's time from CI (H87-01).
