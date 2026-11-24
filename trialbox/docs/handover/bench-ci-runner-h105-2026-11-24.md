# H105: the bench host's CI runner

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-105 (the owner's ruling, the integrator's comment 7117447272 on #639, widened by 7117870645 item 8):
  the bench host runs CI jobs beside the hosted runners, for trains and this repository's lane branches, made safe
  for a public repository
- **Date:** 2026-11-24
- **Install page:** [RUNBOOK §13 part: the bench host's CI runner](../runbook/13-bench-ci-runner.md)
- **Findings:** [`bench-ci-runner-h105-2026-11-24/findings.json`](bench-ci-runner-h105-2026-11-24/findings.json)
  (H105-01 to H105-09)
- **Files:** `.github/workflows/trialbox-bench-ci.yml` (new), `tools/bench_ci/` (new: the launcher, the cards' check,
  the egress proxy, the job image, the units, the install script, the example settings),
  `tests/unit/test_bench_ci_workflow_h105.py`, `tests/unit/test_bench_ci_launcher_h105.py`, the install page, this
  page and its findings, and `docs/RUNBOOK.md` (the generated index line of §13 only). Outside `trialbox/`: the
  new workflow and a new `.github/actionlint.yaml`, which declares the four bench labels so that the `checks` job's
  workflow linter knows them (a test holds it to the launcher's labels; question 5). No existing workflow changes.

## What was built

1. **Triggers.** A workflow of its own, `TrialBox bench CI`. Its triggers are exactly a push to `train/*`, `agent/*`,
   `claude/*` or `lane-*` (a push needs write access to this repository; a fork's pull request does not) and
   `workflow_dispatch`; every job's `if` repeats the guard: a push to one of those refs, or a run by hand whose actor
   and triggering actor are the repository's owner (`github.repository_owner`, no name written). Concurrency: one
   group per lane branch, whose newer push cancels the older run; a train's run has a group of its own and is never
   cancelled or replaced.
   **The owner's switch:** every job also needs the repository variable `TB_BENCH_CI` to be `on` (only an admin sets
   it): unset, every bench job is skipped, so before the install or while the bench is down no lane branch or train
   waits a day for a runner. **Weight:** a lane push gets the unit shards, the integration run, the GPU suites and the
   box rehearsal; `make full-set` runs only for a train and the owner's run by hand. The test evaluates every job's
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
| Install, token, verify, remove | shellcheck and the script's text | every step: the walk runs them first |

## Questions

1. The GPU suites' model endpoint on the bench (H105-03): may a GPU job fetch the pinned public weights through the
   proxy and serve them on its own cards with its nested engine, or is a read-only volume of public weights wanted
   (a host folder the ruling does not allow today)?
2. The real-model rehearsal (H105-04): wire it as a bench job on the GPU slot (H-89's probe on the job's card), as a
   later card?
3. The minting token (H105-01): the owner's choice of credential and expiry.
4. A RUNBOOK number of its own for the install page (H105-07)?
Answered by the lead: `.github/actionlint.yaml` (the four bench labels, so that the workflow linter knows them) is
configuration, not a scan allow-list entry; it stays, named under the files outside `trialbox/`. The linter was not
run in the card's container; CI's `checks` job runs it.

## The security review of #1448 (fix first): what changed, and the test of each

The review (the newest comment on #1448, 2026-11-24) found that the workflow and its test schedule the bench but do
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
