# The rehearsal's host image (H-54), 2026-11-19

**Reader:** the people who build TrialBox

**Is 500 s a cap of ours?** No. Nothing in the rehearsal capped step `host-image` before this card; 500 s is the
elapsed time of a failed `docker build`. Job 135547205491 logs, at 497.6 s into the build: `E: Failed to fetch
http://archive.ubuntu.com/ubuntu/pool/main/libs/libssh/libssh-4_0.10.6-2ubuntu0.5_amd64.deb  Unable to connect to
archive.ubuntu.com:80`: apt's own connect timeouts and retries running out (inference: apt's default retries and
timeout add up to about that; not measured).
**Does the build depend on an outside mirror at run time?** Yes, on a cache miss: the base image from Docker Hub
(`FROM ubuntu:24.04`, not pinned) and every deb from archive.ubuntu.com over plain HTTP (`apt-get update`, `apt-get
install`, tools/rehearse_box/host.Dockerfile). There was no cache: `tools/rehearse_box/rehearse.sh` built the image
on every run and its teardown removed it.

## What failed

Train 98 (#1190), run 44520360544: the test leg failed `host-image` at 500 s (above); the validation leg (job
135547205395) at 112 s with `E: Unable to locate package nftables`, `cron`, `curl`...: `apt-get update` could not read
the indexes but exits 0 on that, so the install found nothing. Lane J's run 44473366274 (#1137): the test leg's
`host-image` took 2758 s (06:49:01 to 07:34:59) and then succeeded: a mirror that trickles never trips apt's timeout
(it applies only while nothing arrives), and the step had no cap, so the job hit its 60 minutes. The 11 successful
legs read (runs 44515438004 to 44527359028 and 44473366274's validation leg): the build took 14 to 51 s, once 197 s and
once 222 s.

## The fix

- `host.Dockerfile`: the base pinned by digest (`ubuntu:24.04@sha256:73b99939…`, the multi-arch index read on
  2026-11-19); apt with `Acquire::Retries "5"`, `Acquire::Retries::Delay "true"` (backoff), `Acquire::http(s)::
  Timeout "20"`; `apt-get update --error-on=any`, so unread indexes fail the update and apt's retries apply.
- `rehearse.sh` `host_image`: each build attempt runs under `timeout` at `HOST_IMAGE_CAP_S` (600 s, overridable by
  `TB_REHEARSE_HOST_IMAGE_CAP_S`; about 2.7 times the slowest successful build read, 222 s), 2 attempts
  (`HOST_IMAGE_ATTEMPTS`). A stopped or failed attempt prints `host-image: attempt N of 2 stopped at its cap of 600 s
  (HOST_IMAGE_CAP_S) while fetching: <the last apt or registry line>`. Worst case about 20 minutes, not 46.
- The cache: with `TB_REHEARSE_HOST_CACHE` set, the image is loaded from `host-<sha256 of host.Dockerfile>.tar` when
  its label `org.trialbox.rehearsal.host-dockerfile-sha256` matches, else built and saved there (never when
  `TB_EXTRA_CA` was given). The workflow restores it with `actions/cache/restore` and saves it with `actions/cache/save`
  (same pinned commit as the other workflows), key `tb-rehearsal-host-${{ hashFiles(host.Dockerfile) }}`, saved even
  when a later step failed. A changed Dockerfile is a new key and a cold build.
- Not changed: what the rehearsal asserts, the step's fatality, the job's 60 minutes.

Limits. On a miss the archive is still needed, bounded as above. The debs in a cached image stay at the versions of
its build until the Dockerfile changes (a rehearsal host, not a site's). The rehearsal runs on pull requests and by
hand only: a PR's cache is its own, so each PR's first run is cold until a `workflow_dispatch` on master fills the
cache every PR can read. Tests: tests/unit/test_rehearsal_host_image_cache.py (no Docker here: a fake `docker`).

## What the next runs must show

No Docker daemon here, so CI is the proof. The first run after the merge on a PR (cold): `| 4 | host-image | PASS |`
in about 15 to 220 s, `ok: host image saved to …`, and the cache saved in the job's log. The next push (warm):
`ok: host image … from the cache … nothing fetched`, step 4 in a few seconds (a `docker load`; expect under 30 s).
A mirror outage on a cold run: a FAIL at about 600 s or less per attempt naming the fetch, never 46 minutes.
