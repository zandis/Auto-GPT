# R2: the PRODUCTION bundle from master, and a production start (updated 2026-11-15)

Plan only. Nothing was started or created. Code read on PR #649's branch `claude/lane-g-box-accuracy` merged with
master at train 17 (`8a7ad118`). The driver is `deploy/gcp/box-run.sh` (#649); the work runs on the VM
(`deploy/gcp/box-install-run.sh` with `deploy/gcp/box_vm.py`). "Unknown" means nothing measured and no estimate exists.
The owner's steps are in `r2-owner-steps.md` (same folder).

## 1. What changed since 2026-11-14

- Train 16 and train 17 are on master. The build is from a master (or train) commit, clean (D-631, D-633).
- The driver exists (#614 on master; #649 adds validation mode and the accuracy group): build (b01-b07) and start
  (01-12) are written and rehearsed locally (19 cases, US$0). The old P5-P8 (build script, cloud driver, the wizard
  through the console's first-run page, the vendor public key placed in step 01) are done.
- D-505: the spend for R2 is approved (cost estimate posted before each run; stop if more than half over).
- The signed-update route for a study is approved, approver "G-run approver (synthetic)" (section 3).
- Lane Q now owns qualify on a box (`docs/plan/39-lane-q-brief.md`, Q-1 to Q-7).

## 2. Prerequisites for the PRODUCTION bundle

| # | Prerequisite | State on 2026-11-15 | Who |
| --- | --- | --- | --- |
| P1 | The release gates green in enforcing mode | **Not met.** The dated vLLM entry (CVE-2026-128089, waiver to 2026-12-10, owner's yes) is not on master (`git grep` finds it only in plans 37 and 38). Routed to **train 18**. Until then b04 stops the build and the key is never read. | lane D, train 18 |
| P2 | A vendor signing key | **Unknown: does one exist? The owner must say.** None is in the repository: `deploy/keys/` holds no `vendor_ed25519.pub` on master, and `deploy/install.sh` stops without one. If none exists, the owner makes one offline (`r2-owner-steps.md` step 0). | owner |
| P3 | Release id and release seq | **Unknown.** `pyproject.toml` says 1.0.0; the repository has no git tag. A box refuses a seq not above its installed one. The study pack (section 3) needs **seq N+1** after the release's seq N; G-10's update needs another one above that. | owner (lane D advises) |
| P4 | The release commit | master after train 18 (the gates) and after the v5 qualification record is in the release (lane Q, Q-3) if this release is to promote v5 on the box. A release without the record installs, but the box then serves only the old baseline prompts (judge@4 ...). | integrator |
| P5 | The secret, the signer account, the public key in the bucket, the wizard's answers | `r2-owner-steps.md` steps 1-3 | owner |
| P6 | Disk on tb-gpu-sim | **Unknown.** About 12 GB of images, the staged tars and the signed bundle (each ~12 GB): plan on 100 GB free. Free check: `gcloud compute disks describe tb-gpu-sim --zone asia-east1-a --format='value(sizeGb)'` | lead |
| P7 | Doctor's expected FAILs on a fresh cloud box (no hospital CA, no mail, no backup target ...) | **Not stated** (lane Q, Q-7). Without the list `--doctor-expected` is a guess. | lane Q |
| P8 | `qualify` on an installed box | Not possible yet: #642 qualify without git (train 18); box inputs #648/D-737, a D0 route, record -> promote, n12 evidence from SCREEN (train 19). Until then the production start stops at 08. | lanes Q, D, A2 |

## 3. The signed-update route for a study (the earlier blocker 7, D-640)

**The blocker.** A PRODUCTION box starts with no study: D-640 seeds the shipped rulesets only on DEV and TEST, and
`load_approved` refuses, on a site box, any version whose approval names nobody. G-6 and G-9 screen an approved study
(`tb-study`); the driver's step `20-g6-study` only checks `GET /rulesets/<id>` and stops if it is not there. A person
clicking "approve" in the console is not unattended.

**What is in the code today (master).** The offline-update channel of D-77 already carries studies:

- `tools/make_bundle.sh --rulesets <dir>` puts every `*.zip` there into the signed bundle as payload kind `ruleset`.
- On a running box, `tools/apply_update.sh <bundle>` verifies the signature and every hash, then its step
  "rulesets" (`tools/trialbox/update.py` `rulesets()`) runs, inside the criteria compiler,
  `python -m criteria_compiler.import_ruleset /tmp/ruleset-update.zip --by update:<bundle id>`.
- `import_ruleset.install` takes only `status: approved` with `equivalence.overall_pct` at or above the site's gate
  (98 % by default), commits it, and tags it `"<ID>/v<version> (offline update, <by>)"`.
- D-640 section 3: on a site box such a tag is an approval that names who gave it, so `load_approved`, the timers and
  the console accept it. D-640 left open "whether a site box should take any approval but its own PI's": the
  owner's ruling of 2026-11-15 answers it for this run: yes, by this signed route.
- The committed GZQO manifest is `status: approved` with equivalence 100.0 and a `review.approved_by` field.

**What is missing (for lane D; the study pack is a release bundle, which is lane D's):**

1. **The approver's name.** The tag says `update:<bundle id>`, not who approved. The owner wants "G-run approver
   (synthetic)" in the bundle and the run report. Needed: the bundle (or each ruleset zip's manifest
   `review.approved_by`) carries the approver; `import_ruleset` writes it in the tag, e.g.
   `"GZQO/v1.0.0 (offline update, update:<bundle id>, approved by G-run approver (synthetic))"`; the console and the
   audit show it. A bundle whose ruleset names no approver is refused on a site box.
2. **The first install does not import the bundle's rulesets.** On a box that is not running yet, the update path
   prints "rulesets: imported when the box runs (tools/apply_update.sh <bundle> again after the start)"
   (`tools/trialbox/update.py:1950`), but applying the same bundle again is a repeat of its release seq, which
   `verify_update.py` refuses ("a downgrade or a repeat") unless `--allow-downgrade`. (Read from the code; not run.)
   Either `install.sh` imports them after the start, as it already loads `deploy/refdata/pending/*.tar`, or the study
   comes as a separate bundle with seq N+1 (the "study pack"). The second needs nothing new but a second ~12 GB
   bundle unless `make_bundle.sh` can build one without images (today it always adds every image of the compose
   files).
3. **The ruleset's judge prompt.** The committed rulesets pin `judge_v4`; once v5 is qualified they are repinned
   (lane A2). A study pack built before that carries v4.
4. **A test** that a PRODUCTION box takes the study from a signed bundle, refuses one with no approver or below the
   equivalence gate, and names the approver in the tag and the audit.

Lane Q's card Q-5 ("unattended study approval ... refused on production") is a different mechanism (a run profile
that clicks for a person) and does not serve a PRODUCTION start; the signed route above does.

**What lane G's driver then does (no cost to write; after lane D's change lands):**

- `build`: b05 builds and signs, besides the release (seq N), the study pack (seq N+1) from `dist/rulesets/<ID>.zip`
  made from the committed ruleset with `review.approved_by: G-run approver (synthetic)`; b06 verifies both; b07
  uploads both with their sha256. Or, if lane D makes the first install import them, one bundle with `--rulesets`.
- `start`: a new step after 12 (doctor), `13-study`: fetch the study pack, check its sha256 and signature as 01 does,
  `tools/apply_update.sh <pack>`, then read the tag through `GET /rulesets/<ID>` and the compiler's repository and
  record the approver, the tag and the bundle id in `records/study.json`; the report prints "study <ID> approved by
  G-run approver (synthetic), offline update <bundle id>".
- `g6`/`g9`: unchanged (`--study <ID>`).
- A rehearsal case `study-pack` (and `study-pack-no-approver`: refused) in `tests/rehearsal/box-run/`.

## 4. Commands (the #649 driver)

Every command below except `--estimate`, `--dry-run` and the rehearsal starts or uses a paid VM: owner's yes (D-505
given), cost posted first, one VM at a time.

    # 0. free, on the release commit (any host with docker; ~40 GB free for make rehearse-box)
    export CLOUDSDK_CONFIG=<a private folder> TB_SA_KEY_FILE=<the deployer's key file> TB_BUCKET=gs://trialbox-demo-runs
    deploy/gcp/box-run.sh --estimate --steps build
    deploy/gcp/box-run.sh --estimate --steps start
    tests/rehearsal/box-run/rehearse-box-run.sh          # 19 cases, US$0, a few minutes
    make rehearse-box                                    # the real install of a signed bundle (TEST box), stand-in models

    # 1. the source, by commit (the VM clones it; no working tree on the VM)
    git bundle create r2-src.bundle <RELEASE_COMMIT>
    gcloud storage cp r2-src.bundle gs://trialbox-demo-runs/r2/<RELEASE_ID>/src.bundle

    # 2. the build (paid): the VM runs as tb-bundle-signer, the only reader of tb-vendor-signing-key
    deploy/gcp/box-run.sh --dry-run --steps build --release-id <RELEASE_ID> --release-seq <N> \
        --commit <RELEASE_COMMIT> --key-version <V>
    deploy/gcp/box-run.sh --steps build --release-id <RELEASE_ID> --release-seq <N> \
        --commit <RELEASE_COMMIT> --key-version <V> --no-wait
    deploy/gcp/box-run.sh --collect <run id> --follow    # bundle and .sha256 in gs://trialbox-demo-runs/r2/<RELEASE_ID>/

    # 3. the production start (paid): install, wizard, pin, serving record, G-1, canary, qualify, promote, doctor
    deploy/gcp/box-run.sh --dry-run --steps start --release-id <RELEASE_ID> \
        --doctor-expected <names lane Q gives> --qualify-evidence "n12=gs://... public_e2e=gs://... goldens=gs://..."
    deploy/gcp/box-run.sh --steps start --release-id <RELEASE_ID> \
        --doctor-expected <names lane Q gives> --qualify-evidence "n12=gs://... public_e2e=gs://... goldens=gs://..." \
        --no-wait
    deploy/gcp/box-run.sh --collect <run id> --follow
    deploy/gcp/box-run.sh --stop <run id>                # TERMINATED checked; the VM put back as it is kept

    # after the study route lands: G-6, G-9, G-10 on the same box
    deploy/gcp/box-run.sh --steps g6,g9,g10 --release-id <RELEASE_ID> --study GZQO --g10-image <vllm image ref> \
        --g10-bundle gs://.../trialbox-<ID N+2>.tar --g10-bundle-sha256 <hex> --no-wait

### The driver's estimates (run 2026-11-15 on #649 merged with master)

    deploy/gcp/box-run.sh --estimate --steps build
      VM start 900 s (constant); b01 source unknown; b02+b03 make venv scanners, make images 334 s (CI run
      43602503189); b04 trivy-db + release-gates 1123 s (same run; it failed at the end on the vLLM CVE); b05
      make_bundle.sh unknown; b06 verify unknown; b07 upload ~12 GB unknown
      known part 0.65 h (US$1.79 spot); 4 steps unmeasured, bounded by the cap: 2 h = US$5.48 spot / US$16.44 on demand

    deploy/gcp/box-run.sh --estimate --steps start
      VM start 900 s; 01 fetch unknown; 02 installer unknown (of which the model servers ready 199 s, fit.json
      2026-11-08); 03 first run unknown; 04-06 pin, serving record, G-1 unknown; 07 canary 124 s (2026-11-08);
      08 qualify unknown (never run on real weights); 09-12 promote, resolve, doctor unknown
      known part 0.34 h (US$0.93 spot); 6 steps unmeasured, bounded by the cap: 4 h = US$10.96 spot / US$32.88 on demand

R2 in all: known 0.99 h (US$2.72 spot); **at the caps 6 h = US$16.44 spot** (US$49.32 on demand). With a study pack
the build exports and uploads a second bundle: not measured, inside the 2 h cap only if it is quick (unknown).

## 5. Open questions

For the owner: (1) does a vendor key exist, and where; (2) release id and seq, and whether this release goes to a
site or is a production-path rehearsal whose seqs are "spent"; (3) spot (US$16.44 at the caps) or on demand
(US$49.32); (4) keep `tb-vendor-signing-key` between releases (version disabled) or delete it after.

For lane D: (5) the dated vLLM entry (train 18); (6) the study route's gaps 1, 2 and 4 of section 3; (7)
`make_bundle.sh` without `--models`: the bundle carries no weights and the box uses `/models` on tb-gpu-sim: the
intended production form?

For lane Q: (8) the expected doctor FAILs (Q-7); (9) the v5 record in the release (Q-3) and when.
