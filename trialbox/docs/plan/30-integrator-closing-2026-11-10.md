# TB-HANDOFF-02a: integrator closing report, 2026-11-10

The integrator session (`session_013CtyYQZ6yK86d9MUZJtkSY`) stops here at the owner's request. This report covers
what it finished after the hand-off (`29-handoff-2026-11-10.md`) and what it leaves open. The build session that
took over is from now on the only integrator.

## 1. G1: rehearsed, not launched

**No paid run was started today, and nothing was billed.** The owner approved the full G1 run (50,000 patients, parts
g1, embed and profile; one RTX PRO 6000 spot VM in asia-east1-a; estimate US$25.89, cap US$35.62). It was held for two
reasons. The first launch from master was refused by the pre-flight quota check, which #90 fixed. Then the deep review
found LLM-002: a judge outage made the verifier answer for the judge, so a G1 result would not count until D-276 (#101)
was in. The owner then asked this session to rehearse, push, report and stop, without launching.

**The commit to launch** is branch `g1/rehearsed-2026-11-10`, commit `4f03d5a`. It is master `7d5b4ac` with #101's final
commit `5497ce9` (D-276, the LLM-002 fix and the consent fix of its second review) merged in.

**Rehearsal on that exact tree, 15:34 UTC: passed.**

| Case | Result |
| --- | --- |
| run-a | 36/36 |
| run-b | 33/33 |
| served (wrong served name is caught) | 7/7 |
| no-upload | 5/5 |
| hang | 6/6 |
| busy | 7/7 |

The evidence was kept on the integrator's machine (`/tmp/tb-rehearsal/evidence`, the newest two per case). It is not
committed.

**To launch**, after the owner says yes to the estimate again:

1. Check out `g1/rehearsed-2026-11-10`. Do not use master: master has moved since, and only this commit is rehearsed.
2. Use a private gcloud config and the service-account key from the environment; unset `CLOUDSDK_AUTH_ACCESS_TOKEN`.
   Never print the key.
3. Run `deploy/gcp/complete-run.sh --patients 50000 --parts g1,embed,profile --estimate`, show the estimate to the
   owner, then run the same command with `--no-wait`.
4. Run `--collect <id>` when it ends.
5. Stop the VM and verify that `gcloud compute instances describe` shows `TERMINATED`.
6. Report the actual cost and the checks.

Expect about 9.5 hours on one VM. `GPUS_ALL_REGIONS` is 1; the owner is re-asking for 2.

If master must be rehearsed instead (for example once #101 is merged), run `make rehearse` on the master commit and
launch from it. A launch from a commit that was not rehearsed is not allowed.

## 2. Merged by this session after the hand-off

| PR | What |
| --- | --- |
| #73 | critical-issues register (docs) |
| #87 | deep review, PoC plan TB-POC-01, master plan TB-PLAN-06 (docs) |
| #89 | T-104 Postgres image and checksummed migrations. Two fixes on integration: the site store's version 3 added to the D-204 baseline; the box media ships the built database image |
| #91 | the hand-off file |
| #97 | fix group D-271 (data pipeline) |
| #102 | D-271 moved to a decision file. The log had frozen at D-270 (D-306) before #97 merged, which turned master's `docs` job red |
| #111 | NOTICE names the catalogue verification folders. #80 and #99 together turned master's `unit` job red |

Earlier on 11-10: #64 #65 #66 #68 #70 #76 #79 #81 #84 #86 #88 #90.

## 3. Left open, now the build session's

| Item | State | Next step |
| --- | --- | --- |
| #101 D-276 (LLM-002, two-model check, consent fallback) | final `5497ce9`; reviewed twice; its CI was red only on the #80/#99 NOTICE test that #111 has fixed | merge master into it, merge when green, then tell the critical-issues session |
| G1 | rehearsed, not launched (§1) | owner's yes, then launch from `g1/rehearsed-2026-11-10` |
| FG-F D-275 | being fixed in the critical-issues session (`session_013CtyYQRc2DVQMHAWRSdGZS`); uses a decision file | merge when its PR is green |
| Other critical-issues PRs: #107 (D-279 identity), #108 (D-273 console privacy) | open | review and merge as usual |
| The critical-issues session | still running | archive it when D-275 and #101 are merged |

## 4. Lessons for the integrator role

* **A green PR can still break master** when master moves under it. Before each merge, run the new gates of the
  base on the merged tree (`decisions_index --check`, `test_notice.py`), or merge master into the branch first.
* **A G1-style paid run needs a fixed commit**: rehearse it, push it to a named branch, and launch from that branch,
  not from a master that moves every few minutes.
* **Docs-heavy PRs collide.** Decisions are now files (D-306), which removes the worst source of conflicts.
