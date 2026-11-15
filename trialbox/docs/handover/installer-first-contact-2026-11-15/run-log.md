# PoC-1 Step 1 (EVIDENCE on the GPU VM): lane G running log

Budget: limit US$150; spent before this step US$59.00; left US$91.00. Price spot US$2.74/h.

| Time (UTC) | What | Decision / why | Run id | Hours | US$ | Running total |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-15 | Step 0: merged origin/master bf8021bd into claude/lane-g-box-accuracy (clean merge) | - | - | 0 | 0 | 59.00 |
| 2026-11-15 | validation-check on the merged tree: can_run true, no blockers (exit 0) | free | - | 0 | 0 | 59.00 |

## Driver adaptations to train 20 (Step 0)
- qualify: `trialbox eval qualify --box` in the box's python image (host tree has no services/), with the host docker CLI/socket mounted so --box asks the running box; gateway http://gateway:8020/v1 on trialbox-net with the operator token. Decision: image, because qualify imports gateway/orchestrator code.
- promote / resolve / verify-all: pin_model in the box's image with --out /d/site/registry.site.yaml (as install.sh does); resolve parses the D-738 text lines (judge, second_opinion on D3).
- pin step: install.sh already pins; step 04 checks the site pins are there (no second pin).
- Full G-1: token identity through model-guard's keyed /tokenize (from the gateway container) vs the weights folder tokenizer in the vLLM image.
- Tripwire: TB_GATEWAY_PHI_TRIPWIRE=off by default for a validation acc run (box-run.sh --acc-tripwire to change); recorded at 51.
- Validation mode: a failed qualify gate is a result (no stop); promote only from a passed record; resolve recorded, no stop; doctor without output is noted, not a stop.
- Raw answers: onbox `traces` (trace store read API, access-logged) per set into the set's tgz (bucket + local run folder, never committed).
- --resume now re-sends this tree's startup script and helper with a new tb-retry: a STOPPED step runs again; finished steps kept.
- Install route kept: install.sh --answers (validation-site-answers.yaml env_extra TB_ENV: VALIDATION); the box form (D-822) not used.
| 2026-11-15 06:01 | Step 0 checks: ruff, mypy, shellcheck, data-scan clean; units 107 passed; box rehearsal 21/21 | pushed f6bcc1761a59d6e56fb78408e5919e170f709f63 | - | 0 | 0 | 59.00 |
| 2026-11-15 06:05 | Step 1 validation-check: can_run true (posted #639) | - | - | 0 | 0 | 59.00 |
| 2026-11-15 06:08 | Removed stale metadata keys of earlier lane G runs (tb-door-*, tb-only, ...; names only) | the leftover door keys would have started a door from an old secret | - | 0 | 0 | 59.00 |
| 2026-11-15 06:08 | L1 build launched (val-f6bcc1761a59, src.bundle uploaded), estimate 0.65 h known, cap 2 h US$5.48 | - | box-20261115T060826Z-f6bcc176 | running | | |
| 06:12 | L1 attempt 1 STOP at b03-images: mvn not found (fetch_jvm_deps.sh:64). VM ~06:08:30-06:12:45 (0.07 h, ~US$0.20) | fix 1: build VM installs maven + openjdk-21 (commits 3b4adb40, c67e96f8), rehearsed 21/21 | box-20261115T060826Z-f6bcc176 | 0.07 | 0.20 | 59.20 |
| 06:25 | L1 resumed (retry) from c67e96f8 | b01, b02 kept | same | running | | |
| 06:29 | L1 resume 1 did nothing: the collect's reset_vm had removed the launch's metadata; VM 06:25:20-06:29:33 (0.07 h) | fix 2: --resume re-sends the launch metadata (e7d6bfd3), dry-run checked | same | 0.07 | 0.19 | 59.39 |
| 06:30 | L1 resume 2 from e7d6bfd3 | - | same | running | | |
| 06:42 | L1 resume 2: b03 done (images built), STOP at b04-gates: demo image not built; test-only mailpit/greenmail new CVEs. VM 06:30:40-06:42 (0.20 h) | fix 3 (a441cecd): demo image built in b03; validation build uses gates' report mode (test-only images only), bundle.json says NOT all green; posted red: for lane D | same | 0.20 | 0.55 | 59.94 |
| 06:5x | L1 resume 3 from a441cecd | b01-b03 kept | same | running | | |
| 07:01 | L1 resume 3: report mode deferred the mail images; STOP b04 again: demo image missing (b03 kept). VM 06:53:48-~07:00 (0.11 h) | fix 4 (70d10eba): b04 builds the demo image when missing | same | 0.11 | 0.30 | 60.24 |
| 07:0x | L1 resume 4 from 70d10eba | - | same | running | | |
| 07:17 | L1 resume 4: b04 PASSED (report mode), STOP b05: make_bundle lists no image (TB_TZ unset in its staged .env, tools/make_bundle.sh:104). VM 07:07:34-~07:17 (0.16 h) | fix 5 (2214674b): TB_TZ=UTC for that call; red posted lane D | same | 0.16 | 0.44 | 60.67 |
| 07:30 | Lead: rebuild from train 22 (d2302999). Merged (merge commit message carries a "# Conflicts" note after the trailers: git kept it; not amended per the no-rewrite rule). Adapted: TB_JOBS_PER_SENDER_PER_DAY=0 via answers env_extra (D-775), MTA id from answers (D-825); BOM kept (verified D-805 does not cover é/µ); n12 SCREEN evidence needs TREC 21/22 (not in phase) | e7504de38b3a8f2362a83d78024eb0cb147c9b0e pushed; checks + rehearsal 21/21 | - | 0 | 0 | 60.67 |

## Fault table (time UTC, step, cause, whose, fix / red, VM minutes lost)
| # | Time | Step | Cause | Whose | Fix / red | VM min lost |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | 06:12 | b03-images (build f6bcc176) | build VM had no mvn/JDK (fetch_jvm_deps.sh:64) | lane G (driver) | 3b4adb40, c67e96f8 | 4 |
| F2 | 06:29 | resume | collect's reset_vm removed launch metadata; resume booted without run id | lane G (driver) | e7d6bfd3 | 4 |
| F3 | 06:42 | b04-gates | demo image not built (CI builds it); test-only mailpit/greenmail new CVEs | lane G (demo image); lane D (CVEs, red #639) | a441cecd (report mode for test-only images, bundle says NOT all green) | 11 |
| F4 | 07:00 | b04-gates | demo image still missing (b03 kept on resume) | lane G | 70d10eba | 6 |
| F5 | 07:17 | b05-sign | make_bundle.sh staged .env lacks TB_TZ; compose lists no image (make_bundle.sh:104) | lane D (red #639) | 2214674b (TB_TZ=UTC for the listing call) | 4 (b04 work was useful) |
| F6 | 07:52 | b05-sign (build e7504de3) | bundle-check uses local Id only; containerd store Id = index digest, gate record = config digest (supply_chain/__main__.py:113) | lane D (red #639) | 5618bd84 (classic image store on the build VM) | 13 (whole attempt) |
| 07:52 | L2 build e7504de3: b01-b04 done, STOP b05 (F6). VM 07:39-07:53 (0.22 h) | fresh build from 5618bd84 so bundle and driver name one commit | box-20261115T073901Z-e7504de38 | 0.22 | 0.60 | 61.27 |

## Lead's change of method (08:15): pre-flight review before the install launch
Own pre-flight, read against the real product scripts (uncommitted until the reviewer's batch):
- PF1 install.sh:743-749: backup-install on a non-box (TB_BOX unset) VALIDATION install dies without an alert route -> env_extra TB_BACKUP_ALERT_ROUTE=health-page (declared, config.py:405). Applied.
- PF2 install.sh:87-97 (OPS-004): deploy/ files are links into ../current after a bundle install; img_tool mounted /d only -> now mounts the release tree at /current as install.sh tree_args does. Applied.
- PF3 seal_keys.sh:65-80: VALIDATION seals site keys with systemd-creds host+tpm2; VM has a vTPM (checked) and Ubuntu 24.04 systemd >= 250 (assumed, to probe).
- PF4 models: the VM keeps the pair as HF snapshots; compose/pin need flat folders + chat template + embedder -> models-place (commit 58787f0d).
- PF5 qualify n12 evidence must say source screen (D-826): not available in this phase -> n12 step will fail: a result.
- PF6 install.sh runs host python3 for tools.trialbox db-up/backup-install/secrets: VM python3 deps (yaml) assumed present (cloud-init), to probe.
| F7 | 08:21 | b05-sign (build 5618bd84) | classic store fix WORKED (bundle-check PASS 8 images); then make_bundle staging: "no space left on device" writing the vLLM image tar to /tmp/tb-bundle.* | lane G (VM disk layout; facts unknown) | not relaunched (lead's order); probe mode to read the disk first | 9 (b05 part) |
| 08:21 | L3 build 5618bd84: b01-b04 done, b05 STOP F7. VM 08:00:45-08:21:44 (0.35 h). VM TERMINATED (checked) | wait for the reviewer's chain review; build probe mode | box-20261115T080047Z-5618bd840 | 0.35 | 0.96 | 62.23 |

## Chain review (agent ad4a30a9ece3362f3), 12 predicted faults, and what lane G did (08:40-09:00)
| # | Predicted | Applied | Status after the run (fill in) |
| --- | --- | --- | --- |
| B1 | disk: bundle up to 4 copies | patch 01 applied (b07 removes local copy, 01 frees build tree, 1.1x free check) + lane G's own TMPDIR/builder prune (F7) | |
| B2 | install.sh silent 13-20 min -> watchdog | patch 02 applied (stdbuf, disk I/O liveness) | |
| B3 | host python3 lacks PyYAML | patch 03 applied (d_host_prereq); red posted (install.sh:498,567) | |
| B4 | no vTPM / systemd-creds -> seal dies | patch 03 preflight; vTPM confirmed True (free read) | |
| B5 | acc waits not streamed -> watchdog | patch 04 applied | |
| B6 | 51 recreates model servers | patch 05 hunk applied by hand (tree mount part was already in) | |
| B7 | img_tool lacks /current | already applied (PF2) | |
| B8 | doctor --live from host: serving FAIL not real | no patch: validation does not stop on doctor; to be read in its record | |
| B9 | e-embed-1.sha256 in bucket? | yes (checked) | |
| B10 | serving capture hashes whole /models | no patch: probe reads du /models first | |
| B11 | old judge/verifier/front containers | lane G fix: d_old_servers removes them (and probe lists docker ps -a) | |
| B12 | 01 re-downloads the bundle | kept (B1 removal wins) | |
Also: probe group (--steps probe, facts only) and --probe on start (facts after install, then stop); acc sets run in the given order (cheapest first); acc cap at most 24 h.
| 08:55 | L4 probe (876ff650): VM 08:50:14-~08:55:30 (0.09 h). Facts: disk 193G, 44G free; /var/lib/containerd 47G (old containerd-store images, unused since the classic switch), /var/lib/docker 29G (build images), /models 48G (HF cache; pair snapshots a19cfe00 and e4d2d39c present; bge-m3 only at 5617a9f/9a0624b, not 7b44 -> fetched by models-place), /tmp on root disk; Docker 29.9.3 overlay2 classic; python3 3.12 yaml 6.0.1 cryptography 41; systemd 255 + systemd-creds + /dev/tpmrm0; nft present, cron absent (patch 03 installs); no old containers; GPU idle 97.9 GB, driver 580.178 | fix F7: d_old_store removes the containerd store's images (ctr -n moby) before b02/b05 and at 01; B3 disproved (yaml present), B4 OK (TPM + creds), B11 disproved (no containers), B10 small risk (/models 48G) | box-20261115T085016Z-876ff6506 | 0.09 | 0.25 | 62.48 |
| F8 | 09:31 | b05-sign (build ac36aa21) | ENOSPC in sign_bundle (51 GB free at b05; old-store removal freed only 9 GB; the online disk grow at 09:21 not yet in the fs) | lane G | grow_root each boot (commit after ac36aa21); resume | ~10 |
| 09:31 | L5 build ac36aa21: b01-b04 done, b05 F8. VM 09:10:35-~09:31 (0.34 h) | resume with grow_root | box-20261115T091037Z-ac36aa21f | 0.34 | 0.93 | 63.41 |
| 09:21 | Disk enlarged by the lead 200 -> 400 GB (hyperdisk-balanced). Extra capacity billed per GB-month whether the VM runs or not: separate line, rate to verify | - | - | - | separate | |
| 09:47 | L5 build ac36aa21 COMPLETE after resume (b05 521 s, b06 51 s, b07 73 s). Bundle val-ac36aa21fdc1, 29.6 GB, sha256 2288a81b..., not a release, gates NOT all green (report mode, test-only mail images). Disk: the image's own boot (cloud-init growpart) had already grown the root fs to 415 GB before grow_root (its growpart was a no-op). VM 09:33:10-09:47:00 (0.23 h) | build total for ac36aa21: 0.57 h vs estimate 0.65 h known / 2 h cap | box-20261115T091037Z-ac36aa21f | 0.23 | 0.63 | 64.04 |
| 09:47 | L6 start (install..doctor) launched; bundle val-ac36aa21fdc1, driver 4c7c4701 | estimate 0.34 h known / 4 h cap | box-20261115T094747Z-4c7c47017 | running | | |
| F9 | 09:58 | 02-install (seal_keys.sh) | systemd-creds: "Failed to create TPM2 context: Operation not supported" (TSS2 libs absent on the image) | lane G host prep / product: seal before proof | d647434b, 5f71ffb8 (tpm2-tools, round trip) then owner: seal not needed -> TB_BOX_DEFER_SEAL=1 (commit after 5f71ffb8) | 11 |
| 09:58 | L6 attempt 1: 01 done, 02 stopped F9. VM 09:47:45-09:58:39 (0.18 h) | half install cleared at next 02 (d_half_install) | box-20261115T094747Z-4c7c47017 | 0.18 | 0.50 | 64.54 |
| ~10:45 | L6 resume (last chance for the installer route, per the lead) | if it stops: abandon installer route, direct compose route | same | running | | |
