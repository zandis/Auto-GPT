# H105: the bench host's CI runner

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-105 (the owner's ruling, the integrator's comment 7117447272 on #639, widened by 7117870645 item 8;
  the security review 7118916382; the weights ruling 7118754451; the ninety-minute ruling 7119929149):
  the bench host runs CI jobs beside the hosted runners, for trains and this repository's lane branches, made safe
  for a public repository
- **Date:** 2026-11-24
- **Install page:** [RUNBOOK §13 part: the bench host's CI runner](../runbook/13-bench-ci-runner.md)
- **Findings:** [`bench-ci-runner-h105-2026-11-24/findings.json`](bench-ci-runner-h105-2026-11-24/findings.json)
  (H105-01 to H105-10)
- **Files:** `tools/bench_ci/` (new: the launcher, the gate, the cards' check, the egress proxy, the one-job
  configuration's unpacker, the job image, the units, the install script, the example settings), the tests
  `tests/unit/test_bench_ci_{workflow,launcher,gate,unpack_jit,review}_h105.py`, the install page, this page and its
  findings. No existing workflow's jobs change. The files outside the card are listed below.

## Files outside the card

Named here as the rule asks (each change is the card's own, or a line a ruling asked for):

- `.github/workflows/trialbox-bench-ci.yml` (new);
- `.github/actionlint.yaml` (new: the four bench labels, so that the workflow linter knows them; the lead's answer:
  configuration, not a scan allow-list entry);
- `trialbox/docs/RUNBOOK.md` (the generated index line of §13 only);
- `trialbox/Makefile` (the job image's Dockerfile added to `HADOLINT_REPORT`, the red of train 161);
- `trialbox/tests/unit/test_ci_jobs_inside_ninety.py` (the full-set entry the ninety-minute ruling 7119929149 named,
  and its docstring);
- `trialbox/tests/unit/test_image_config_scans.py` (its docstring only: six report-only files, not five).

## What was built

1. **Triggers.** A workflow of its own, `TrialBox bench CI`. Its triggers are exactly a push to `train/*`, `agent/*`,
   `claude/*` or `lane-*` (a push needs write access to this repository; a fork's pull request does not) and
   `workflow_dispatch`; every job's `if` repeats the guard: a push to one of those refs, or a run by hand whose actor
   and triggering actor are the repository's owner (`github.repository_owner`, no name written). Concurrency: one
   group per lane branch, whose newer push cancels the older run; a train's run has a group of its own and is never
   cancelled or replaced.
   **The owner's switch:** every job also needs the repository variable `TB_BENCH_CI` to be `on` (only an admin sets
   it): unset, every bench job is skipped, so before the install or while the bench is down no lane branch or train
   waits a day for a runner. **Weight:** A lane push gets the unit shards and the integration run (the CPU
   profile); the GPU suites, `make full-set` and the box rehearsal run only for a train and the owner's run by hand
   (the security review's F5). That is less than the owner's ruling (item 8: every lane PR gets the GPU suites):
   finding H105-09, not met, for the reason given there. The test evaluates every job's
   condition for 13 events with the switch on, unset, off or misspelt. `permissions:
   contents: read`, no secret named, every action pinned by its full commit id, every checkout without a kept
   credential. The test reads every workflow file in `.github/workflows` and fails when a job that can run on a
   self-hosted runner is in any other workflow, when another workflow names the label `tb-bench` or waits for this
   one, or when this one gains any trigger (`pull_request`, `pull_request_target`, `issue_comment`, `workflow_run`,
   ...), branch, tag, input, permission, secret, unpinned action, job guard or concurrency change.
   A `runs-on` it cannot prove (a runner group, an expression that is not a matrix of literals, a reusable workflow
   of another repository) counts as the bench.
2. **Isolation.** `tools/bench_ci/launcher.py`, run by one service unit per slot as the `tb-bench` user (no login,
   no other group): each start registers one one-job runner and runs it in a fresh container of a rootless engine,
   as the image's user 1001, with one host folder (the job's scratch folder, made for it and deleted after it), no
   engine socket, the internal jobs network (no route out) and the egress proxy as the only way out (CONNECT to 443,
   the allow-listed names, never an address that is not public). CPU slots: read-only root, every capability
   dropped, no new privileges. Engine and GPU slots: a nested rootless engine of the job's own (H105-02).
3. **GPUs.** The CI cards, their cap and the reserved cards (card 1, the walk's, which the settings must hold, and the
   bench's) are in the host's settings file; the repository has an example with placeholders. The GPU slots share
   the CI cards (the lead's relay of the ruling: several jobs at once, under caps). A CI card that is reserved,
   missing or busy beyond its cap (more memory or load than the settings allow, or a reading the tool cannot give)
   stops the GPU slot before any registration, with a message naming the card; the job checks the same cards again,
   by UUID, as the runner's job-started hook. Tested with a stand-in for the card query tool.
4. **Jobs.** Unit shards (8) and the integration run on CPU slots, the GPU suites and `make full-set` on the GPU slot,
   the box rehearsal on an engine slot. The hosted runners keep the gate: this is **a separate workflow no branch
   rule requires**, not `continue-on-error`, so a failing bench job shows red (its result and time are the measure)
   and an outage of the bench blocks nothing. Nothing moved off the hosted runners.
5. **Install.** The page: prerequisites, install as the temporary sudo user, the token typed or pasted at a prompt
   into a root-only file (handed to the units as a credential of the service manager), verify (the named folders as `tb-bench`, a
   probe container with the CPU jobs' arguments exactly), and removal of everything, with what the owner removes on
   the code host.
6. **Times.** Each bench job writes its wall time to its summary and a small record; the hosted job `bench times`
   puts them in one table, to read against the hosted runners' times of the same train.

## What is proven by tests, and what only by the walk's install

| Part | Held by | Not shown |
| --- | --- | --- |
| No trigger but a push to a train or lane branch, or the owner's run by hand, reaches the bench label | `test_no_other_trigger_reaches_the_bench_label` and 35 planted mutants | the code host honouring the guard |
| The job container's arguments, per profile | the launcher tests (26 planted mutants caught) | the engine honouring them; the image building |
| The CI cards' check | a stand-in for the card query tool | the real tool's output on the bench's cards |
| The token's way | the code host's API host only, whatever a caller's proxy says; the configuration on stdin | the code host's answer (no call was made) |
| The egress proxy | the allow-list and a loopback socket (403 for plain HTTP, an unlisted host, a private address) | the allow-list being enough (H105-05) |
| Install, token, verify, remove | shellcheck; the install's image and scratch steps, the token step and verify before the token, run with stand-ins (`tests/unit/test_bench_ci_host_h105.py`) | every step on the host: the walk's run of `host_test.sh` |

## Questions

1. Answered (7118754451): the weights folder read-only at `/weights`. Open: the step that serves them (H105-03).
2. The real-model rehearsal (H105-04): wire it as a bench job on the GPU slot (H-89's probe on the job's card), as a
   later card?
3. Answered by the owner: a fine-grained token, this repository only, Administration: write, 30 days, root-only.
4. A RUNBOOK number of its own for the install page (H105-07)?
Answered by the lead: `.github/actionlint.yaml` (the four bench labels, so that the workflow linter knows them) is
configuration, not a scan allow-list entry; it stays, named under the files outside the card. The workflow linter
was not run in the card's container (CI's `checks` job runs it); the external review ran it clean, and ran the image
linter on the job image's Dockerfile: two report-only warnings (DL3008 unpinned packages, DL3010 an archive copied
then unpacked).

## The security review of #1448 (fix first): what changed, and the test of each

The review (its page on #1448, comment 7118916123; the integrator's line 7118916382 on #639, 2026-11-24) found that the workflow and its test schedule the bench but do
not guard it: a fork's pull request brings its own workflow files. Each fix, and what holds it (every test id under
`tests/unit/`; each fix also has planted mutants, all caught):

| Finding | The fix | Held by |
| --- | --- | --- |
| F1 (critical) | the host's gate, `tools/bench_ci/gate.py`, run by the runner's job-started hook before any step: push or the owner's run by hand; this repository, not a fork; an allowed branch; the bench workflow at that ref; its file the same blob as master's (read by the host) | `test_bench_ci_gate_h105.py::test_a_forks_pull_request_is_refused_before_anything_is_read`, `::test_each_condition_broken_alone_refuses_the_job` (18 cases), `::test_the_event_payload_must_be_this_repository`, `::test_a_branch_whose_workflow_file_differs_from_masters_is_refused`, `::test_a_branch_on_an_older_master_with_the_same_file_runs`, `::test_an_unreadable_file_refuses_and_a_missing_fact_refuses`, `test_bench_ci_launcher_h105.py::test_the_image_runs_as_its_own_user_and_takes_its_config_from_a_file` (the hook runs the gate first) |
| F2 (high) | the long-lived token is read by the units' root steps only (mint, cleanup); no unit hands a copy; the jobs' user gets one job's configuration | `test_bench_ci_launcher_h105.py::test_the_root_mint_step_gives_the_jobs_user_one_jobs_configuration_and_never_the_token`, `::test_the_jobs_users_step_never_reads_the_token`, `::test_only_the_units_root_steps_read_the_token_and_the_jobs_user_runs_the_job`, `::test_the_token_file_must_be_the_root_steps_own_and_private`, `::test_the_mint_step_refuses_to_run_as_another_user` |
| F3 | the page and the workflow's header say it: the gate is the control; the switch and the guards only schedule; who is trusted; what to do in an incident | the page (harm 1), the workflow's header comment |
| F4 | exact host names (no storage or user-content wildcard, no upload host); no name service in jobs (`--dns none`, networks with names off); the probe checks it | `test_bench_ci_launcher_h105.py::test_the_allow_list_names_hosts_not_wildcards_and_no_upload_host`, `::test_the_job_network_is_internal_without_a_name_service_and_the_proxy_joins_it`, `::test_no_profile_sees_a_socket_a_home_the_host_network_or_any_folder_but_its_own`, `::test_verify_checks_the_named_folders_as_the_runners_user_and_runs_the_probe` |
| F5 | every profile read-only, all capabilities dropped, no fuse or tun; engine and GPU keep SETUID and SETGID only (the nested engine's id mapping) and run on trains and the owner's runs only; each profile probed | `test_bench_ci_launcher_h105.py::test_no_profile_sees_a_socket_a_home_the_host_network_or_any_folder_but_its_own`, `::test_an_engine_or_gpu_job_keeps_only_the_set_id_pair_for_its_nested_engine`, `::test_the_verify_probe_runs_with_each_profiles_arguments_exactly`, `test_bench_ci_workflow_h105.py::test_which_jobs_each_event_runs_with_the_switch_on_or_not` |
| F6 | the schedule test refuses `github.token` and `toJSON(github)` | `test_bench_ci_workflow_h105.py::test_planted_trigger_mutants_are_caught[the workflow token]`, `[the whole context]` |
| F7 | one internal network per slot (a /24 of its own), the proxy joined to it at a fixed address for the job's life | `test_bench_ci_launcher_h105.py::test_each_slot_has_its_own_network_and_address`, `::test_the_proxy_container_sits_on_its_way_out_only` |
| F8 | a unit stop sends TERM to the run step, which stops the container and removes the network; the root cleanup (also after a failure or a stop) removes the registration and the folder; a new job starts from an empty folder | `test_bench_ci_launcher_h105.py::test_a_unit_stop_stops_the_container`, `::test_a_stop_or_a_failure_takes_the_registration_and_the_scratch_folder_away`, `::test_a_new_job_never_finds_an_earlier_jobs_files` |
| F9 | the one-job configuration is a file (0600) the entry point reads, deletes and unpacks into the runner's files | `test_bench_ci_unpack_jit_h105.py::test_the_configuration_becomes_the_runners_three_files`, `::test_any_other_form_is_refused_and_nothing_is_written`, `test_bench_ci_launcher_h105.py::test_the_image_runs_as_its_own_user_and_takes_its_config_from_a_file` |
| H105-03 (ruled) | the weights folder, read-only at `/weights`, for the GPU profile only | `test_bench_ci_launcher_h105.py::test_only_a_gpu_job_gets_the_ci_cards_and_the_weights_read_only` |

Unproven until the walk's install (H105-08 and the page's last section): that the runner hands the hook the
`GITHUB_*` variables and the payload; the three-file form of the one-job configuration; that the rootless engine
honours `--dns none`, the per-slot networks and the proxy's fixed address; that the nested engine runs with the set-id
pair alone, plain-folder storage and no tun device; that a unit stop cleans up.

## The external review of #1448 at a5297c6 (fix first): the Mediums, the Lows

The review (#639, 7121436588 and 7121438419; the integrator's line 7121445727) found no High, seven Medium and
twelve Low. Every Medium is fixed with a test that fails at a5297c6 (`tests/unit/test_bench_ci_review_h105.py`, run
there before the fix: 29 of its tests failed):

| Finding | The fix | Held by |
| --- | --- | --- |
| M-1448-1 | root makes the slot's folder and its subfolders new, each step relative to an open folder, never following a link; the job's files are written into the open folder; each part is handed to the jobs' user by descriptor, the top last; the registration is on record before the folder step | `::test_m1448_1_a_link_planted_at_the_slots_name_after_the_removal_is_not_followed` (fails at a5297c6); the two race variants guard the new code (they passed at a5297c6, re-review 1448-23) |
| M-1448-2 | the gate leaves a `started` mark when it accepts a job; the run step counts BENCH_JOB_HOURS from it (until then it is the longest a runner waits: an idle runner is recycled) | `::test_m1448_2_a_job_accepted_late_in_the_runners_wait_gets_its_whole_limit`, `::test_m1448_2_the_gate_marks_an_accepted_job_and_only_that` |
| M-1448-3 | the example's BENCH_JOB_HOURS is 11 (full-set's 600 minutes); the test holds it to the bench workflow's longest timeout | `::test_m1448_3_the_example_job_hours_cover_the_longest_bench_job` |
| M-1448-4 | full-set is `${{ !cancelled() && (...) }}`; no job on the bench may use `always()` (the schedule test refuses it); the times table keeps `always()` | `::test_m1448_4_no_job_on_the_bench_starts_after_a_cancel`, `test_bench_ci_workflow_h105.py::test_planted_trigger_mutants_are_caught[full-set after a cancel]` |
| M-1448-5 | while it waits or runs, the slot joins the egress proxy to its network again every 30 s (a restarted proxy is on none) | `::test_m1448_5_a_waiting_slot_joins_the_proxy_to_its_network_again` |
| M-1448-6 | the gate reads master's file itself at the job's start, by master's current commit from the code host's ref list, and compares the job's file with it; the mint step no longer reads master (no stale blob, no failing starts before the merge) | `::test_m1448_6_a_train_carrying_masters_new_file_runs_on_a_runner_minted_before_the_change`, `::test_m1448_6_a_branch_still_on_the_old_file_is_refused_whatever_the_runner_saw`, `::test_m1448_6_masters_commit_is_read_from_the_code_hosts_refs`, `::test_m1448_6_the_mint_step_no_longer_reads_masters_file` |
| M-1448-7 | this page (what a lane push gets, the files outside the card, the rulings cited), the two docstrings (the ninety-minute list grows only by a ruling; six report-only files); the PR body is the lead's to correct | `::test_m1448_7_the_card_page_says_what_a_lane_push_gets`, `::test_m1448_7_the_docstrings_say_what_their_lists_now_hold`, `::test_m1448_7_the_rulings_the_page_cites_are_the_threads` |

Lows fixed (same file): L-1448-8 (a private IPv4 address inside IPv6 is judged as IPv4), L-1448-9 (the proxy tries
each checked address), L-1448-10 (a private /16 only, BENCH_JOB_HOURS at least 1, ASCII digits), L-1448-11 (the
token's temporary copy goes on any exit), L-1448-12 (the page: changing the token restarts running slots too),
L-1448-13 (a container that never took a job fails the unit; the stop handler comes first), L-1448-14 (the page:
"no upload host" said as what the proxy can tell), L-1448-17 (no huge wall time after an early cancel), L-1448-18
(the install stops before any change when the service manager is not the running init), L-1448-19 (1) (the switch's
comparison ignores case, as the code host's does).
Left for a named follow-up: L-1448-15 (a GPU job refused for busy cards ends red instead of waiting), L-1448-16 (an
owner's run by hand on a branch the gate refuses is scheduled first; the job `if` could hold the gate's ref rule),
L-1448-19 (3) (install.sh and the units are tested as text). The review's note on `pytest -n auto` under a CPU quota
(each shard may start more workers than its share) is not acted on: the first bench runs show it.

## The re-review of #1448 at 0624f4f (fix first): 1448-20 and the Lows

The re-review (#639, 7123982226; the integrator's line 7123983927) found no High, one Medium and ten Lows.

- **1448-20 (Medium):** a signal during `install.sh token` ran the trap, then went on to say the token was kept,
  restarted the slots and ended 0; a signal before the write could leave the copy readable by others. Now every file
  of the step is made under umask 077, a signal removes the copy and ends the step (exit 130), and a failed move is a
  failure. Held by `test_m1448_20_a_signal_in_the_token_step_ends_it` in `tests/unit/test_bench_ci_review_h105.py` (a
  signal after each line of the step, for INT, TERM and HUP: 15 of its cases fail at 0624f4f), with
  `::test_m1448_20_without_a_signal_the_token_is_kept_root_only` and `::test_m1448_20_a_failed_move_is_a_failure_not_a_kept_token`.
  The earlier L-1448-11 test, which read the trap's text, now runs the step (1448-23).
- **Lows fixed:** 1448-21 (an IPv4-translated address judged by its IPv4 address); 1448-22 (the install refuses a
  scratch folder under a link, a folder not root's, or one others can write, and the scratch root is opened without
  following a link); 1448-23 (the subfolder race tests match by the name's last part; the token test runs the step);
  1448-24 (an idle runner recycled at the limit ends its unit as no failure); 1448-25 (no real address in the bench
  tests: documentation ranges, or one built in code; a test holds it); 1448-14's rest (the settings example's
  comment says "no upload host the proxy can tell from a download host").
- **Left for the follow-up card H-105b:** L-1448-15, L-1448-16, L-1448-19 (2: the evaluator models no cancel; a
  structural rule refuses `always()` instead) and (3), and the question 1448-14 raised: do the CI weights need to be
  secret (a GPU job reads the weights folder, and its code can send what it reads through an allowed host)?

## H-105b: the GPU box rehearsal, and the Lows of the review at bfc1408

The integrator sent the review's six open Lows (7126710814: 1448-14, 1448-15, 1448-16, 1448-19, 1448-26, 1448-27) to
this follow-up, with the GPU box rehearsal (the lead's part b). Each is held by a test in
`tests/unit/test_bench_ci_review_h105.py` (or the workflow and launcher tests):

- **The GPU box rehearsal:** the job `rehearse-gpu-box` (a GPU slot; a train or the owner's run by hand) runs
  `tools/bench_ci/gpu_box.sh`: the TPM fact, the GPU record (no serial or UUID), the weights folder mounted read-only
  (read from the mount's options, which holds for root as for any user), the job's own engine; NOT RUN for the box
  install under a real init, the first-run step and the unit start (H105-10) and for the serving step (H105-03).
- **1448-15:** a GPU job waits up to 30 minutes for busy CI cards, checking every 30 seconds, before it refuses;
  wrong cards are refused at once (`test_1448_15_*`).
- **1448-16:** a run by hand is scheduled only on master or an allowed branch, as the gate requires
  (`test_bench_ci_workflow_h105.py`: the owner's run on a lane branch, on another branch, on a tag).
- **1448-19 (2):** the schedule test models a cancelled run: only the hosted times table starts
  (`test_after_a_cancel_no_bench_job_starts_and_only_the_times_table_does`). **(3):** the token step and the scratch
  folders' check now run in tests; the units, verify and remove are shown on the bench host by the real-host test
  (the integrator's ruling: below).
- **1448-26:** a signal after the token was moved into place says the new token is kept and the slots may not all
  be restarted; before the move it says no token was kept (`test_1448_26_a_signal_says_whether_the_token_was_kept`,
  every line of the step, INT, TERM and HUP).
- **1448-27:** a failed chown or chmod (not only a failed move) ends the step (`test_1448_27_any_failed_step_of_the_keep_is_a_failure`);
  the scratch folders' check is run on a shared sticky folder, a link and root's own folders
  (`test_1448_27_the_scratch_check_*`). The wall-time test counts the bench jobs instead of a fixed five.
- **1448-14:** ruled by the integrator (7129040734): not secret. The CI weights are public and mounted read-only; it
  rides with a follow-up.

## The walk's red on the bench host (7129020102, 7129040734): the first real install, at 1fc6579e

The walk's first install on the bench host found faults the text tests passed (H105-11). Each is fixed and held by a
test that runs the step (`tests/unit/test_bench_ci_host_h105.py`); none is shown on the host until the walk's
real-host test is clean:

- **The scratch folder:** the install refused any folder whose name starts with `/var/lib/tb-bench` (a folder
  beside the user's home); it now refuses only the home and what is in it.
- **"ctx: unbound variable" after "installed":** the image step's clean-up trap stayed set after the step and fired
  again when the install returned, with the step's folder gone; the trap now clears itself.
- **The runtime folder:** a system unit's `%U` is 0, so the units sent the engine to root's runtime folder. The units
  name none; each step of the `tb-bench` user sets it from its own user id, with its home from the user database, and
  drops the variables that would point the engine at another store.
- **The proxy's network (integrator 7129534370, walk 7129516517):** reproduced in the card's container on the same
  distribution's packages (engine 4.9.3, netavark 1.4, a system user with its home under `/var/lib`, the runtime
  folder a tmpfs as the service manager makes it): every network the user made is "not found" (exit 127) while the
  default network works. The cause: without `/var/lib/cni`, the engine mounts an empty folder over `/var/lib` while it
  sets up the user's network, hiding the user's home and its network files. With an empty `/var/lib/cni` the same
  runs pass: the proxy on `tb-bench-egress`, a job on an internal network reaching the proxy at its fixed address,
  and the job's direct way out refused. Setting pasta in the user's own `containers.conf` changed nothing either way,
  so the install does not set it; no engine build is pinned. The install makes `/var/lib/cni` (and remove takes it
  away if it made it and it is empty); the proxy's step refuses to start the engine without it; the proxy's own
  step also makes `tb-bench-egress` if its engine does not see it. The jobs never fall back to the default network.
  Not reproduced here: the service manager's units themselves (the container has none); the real-host test shows
  them.
- **The prerequisites:** the runbook names the two packages a fresh host lacks (the rootless engine and `uidmap`),
  and the install's refusal says to install them from the distribution.
- **Found here as well:** `install.sh` was committed without its execute bit, though the runbook runs it by path; it
  now has it, and a test holds every script of the runner executable.
- **Verify before the token:** the token's lines and the slots' say NOT RUN (no token, no runner), and are counted in
  verify's last line, instead of failing; with a token they run as before. Before, a missing token file also passed
  the "cannot read the token file" line.

The integrator's ruling on 1448-19 (3): #1466 rides only after a clean real-host test of install, verify and remove.
`tools/bench_ci/host_test.sh FOLDER...` is that test, one command for the walk: install, the proxy started and
holding with no restart in the user's own store and runtime folder, verify, remove, and nothing left; a line of
counts; exit 1 on any failure. It uses no token and refuses to start while one is installed; its report names no
folder, path or host, so it can be posted as it is. Its report's own parts are tested here; the run itself is the
walk's.

## The external review of #1466 at d48a56e (fix first): the Highs, the Medium, the Lows

The review (7132109781, verdict 7132117189) and the integrator's ruling (7132140169). Each is held by a test in
`tests/unit/test_bench_ci_host_h105.py` (the GPU box's in `test_bench_ci_launcher_h105.py`):

- **1466-1 (High):** a step's log was named after the step, and the CNI folder's step name holds a "/": the redirect
  failed, the step said FAIL with the folder there, and the failed tail ended the test before verify and remove. Each
  step's log is now named by its number (`test_a_step_whose_name_holds_a_slash_is_run_and_the_test_goes_on`).
- **1466-2 (High), as ruled:** remove deletes only what install recorded that it made. The record
  (`/etc/tb-bench-ci/made`, root's, 0600) gets each thing's line before the thing is made, always written whole
  (a copy, synced, renamed). A scratch folder install refused, the operator's settings, a user or folder of the same
  name that was there before, all stay; with no record remove deletes nothing and exits 1. The host test never runs
  remove (or anything else) after a failed install
  (`test_a_planted_folder_of_another_owner_survives_install_and_remove`,
  `test_remove_without_a_record_deletes_nothing_and_says_so`,
  `test_the_host_test_never_runs_remove_after_a_failed_install`).
- **1466-3 (Medium), H105-11:** stays open until the walk's run of `host_test.sh` at a head the review says rides is
  clean.
- **1466-4:** the GPU record is a FAIL when the card tool's answer cannot be read, names no card or has a short row.
- **1466-5:** the report also stands in for the checkout's path, the operator's user name and home, and every
  address (a time of day is kept).
- **1466-6:** the units' check fails when no unit was laid out; "nothing left" reads the record; verify's NOT RUN lines
  are counted as not run.
- **1466-7:** a signal ends the host test with the step it stopped in and what to run next; the record line comes
  before the thing, so a cut install leaves nothing unrecorded.
- **1466-8:** remove keeps the settings file (and gives it back to root's own group when the user goes).
- **1466-9:** install no longer takes an existing folder of another owner, even empty, as scratch; an existing one is
  taken only if install recorded it, or it is `tb-bench`'s and empty (an earlier install's, then not recorded: kept
  by remove).
- **1466-10:** the pull request's body is the lead's: the corrected lines are in the report to the lead.

Not shown here: any of it on the bench host. An install made before the record (the walk's first, at 1fc6579) has no
record, so the new remove deletes none of it: what goes from it is the owner's decision (a question to the lead).

