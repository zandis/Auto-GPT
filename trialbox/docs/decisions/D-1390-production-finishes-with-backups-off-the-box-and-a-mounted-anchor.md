# D-1390 A PRODUCTION install finishes only with its backups off the box and its audit anchor folder mounted (10K-4)

- **Task:** lane K, plan 10 row 10K-4 (review 18, SO-4): "Backup, anchor and log folders chosen in the wizard; a
  PRODUCTION install refuses to finish with on-box-only backups or an unmountable anchor". Proved by: "The install
  test exits before 'finished' in both cases". Builds on D-1361 (10K-3: its preflight page is a snapshot taken
  before these answers, and named this card for the folder choice and the refusal) and D-1365 (10K-21: the box's
  first-run page as the box's wizard, `production_gaps`, the box plan's `env_extra`). · **Date:** 2026-11-21
- **What the card asks:**
  1. the backup folder chosen in the wizard;
  2. the audit anchor folder chosen in the wizard;
  3. the log folder chosen in the wizard;
  4. a PRODUCTION install that refuses to finish when its backups are only on the box;
  5. a PRODUCTION install that refuses to finish when its anchor cannot be mounted;
  6. an install test that exits before "finished" in both cases.
- **Decision (what was built):**
  - **The wizard** is the box's first-run page (D-466, D-1365) and the unattended answers file that shares its
    schema (D-898). `tb_common.box_answers` has three new answers, each optional for the parser: `backup_dir` (the
    folder where the second disk or the share is mounted on the box; empty keeps the plan's fixed mount point,
    `/srv/trialbox-backup` or `/mnt/trialbox-share`; with "later" there is no place to name, so it is dropped),
    `anchor_dir` (the audit record share's folder, `TB_AUDIT_ANCHOR_TARGETS`) and `log_dir` (`TB_LOG_DIR`; empty:
    `deploy/logs`, as before). One rule for all three, `box_answers.host_dir`: a full path of letters, digits, `.`,
    `_`, `-` and `/` (the existing `_ROOT_DIR`), not `/`, no `.`, `..` or empty part, at most 255 characters (a longer
    one is refused, never cut), a trailing `/` dropped. Refused: `firstrun.err.host_dir` at the field. Only a chosen
    folder is written to the answers file, so a box that was not asked writes what it wrote before. `tools.box.plan`
    writes them into `env_extra` (`TB_BACKUP_TARGETS`, and `TB_BACKUP_OFFBOX` for a second disk, as before;
    `TB_AUDIT_ANCHOR_TARGETS`; `TB_LOG_DIR`), only when chosen.
  - **The page asks; the box decides.** The console cannot see the host's mount table, so the page checks only how a
    folder is written. On a PRODUCTION box it says, beside the folders, that the set-up does not finish until a
    backup place off the box and the audit record folder are mounted, and that the box shows what is missing on its
    own screen. `production_gaps` (D-1365) is unchanged: a folder is not made a required field of the page.
  - **One check:** `tools/trialbox/finish_check.py`, `python3 -m tools.trialbox finish-check --deploy deploy`. In
    PRODUCTION (`TB_ENV` of `deploy/.env`; no value is PRODUCTION, D-127) it refuses (exit 1, each reason on stderr):
    - **on-box-only backups:** no target, or no target of `TB_BACKUP_TARGETS` off the box by the rule the nightly
      backup already counts a good PRODUCTION backup by (`backup_schedule.Config.classify`: a network share, a USB
      disk, or a folder `TB_BACKUP_OFFBOX` declares on another device or marked `.trialbox-offbox`). A folder that is
      not mounted is a folder of the box's own disk, so a second disk or a share that nobody mounted is refused too.
      One target off the box is enough (the nightly's rule);
    - **an unmountable anchor:** `TB_AUDIT_ANCHOR_TARGETS` names no folder, a name the installer's mount refuses
      (`anchors.plan`: not a plain absolute folder), or a folder that is not there (`anchors.missing`). "Names none"
      is read as unmountable: there is nothing to mount, and `doctor` FAILs it in PRODUCTION already (`audit_heads`).
    Outside PRODUCTION it refuses nothing. It reads `deploy/.env`, the mount table and the folders, and writes nothing.
  - **`deploy/install.sh`, block FINISH-GATE**, after the backup target's default is written and before the stack
    starts: in PRODUCTION, unless `TB_BOX=1`, the check runs and a refusal `die`s ("not started: ..."), so the IT
    form and the box's unattended install (`TB_BOX=0`) stop before "TrialBox is running". No `python3` in PRODUCTION
    is a refusal too. `TB_BOX=1` (a box's own install before its first-run page) is not checked: the owner has not
    chosen the folders yet.
  - **`deploy/box-install.sh`**, after the owner's answers are applied (and on a `--firstrun` after an earlier apply),
    before the restart, the backup schedule and the last line: the same check with `--mount-anchors`. A refusal stops
    with "the set-up is not finished ... Then: sudo deploy/box-install.sh --firstrun"; nothing is restarted on the
    refused settings, and a later `--firstrun` (BOX-APPLIED, D-576) asks nothing again and finishes once the share
    or disk is mounted. `--mount-anchors` writes `deploy/site/compose.anchors.yml` with `anchors.write` (as
    install.sh's ANCHOR-MOUNT block, D-638, which did not run after the apply) and keeps `COMPOSE_FILE` naming it (or
    no longer naming it when no folder is set); `deploy/.env` is rewritten through `mkstemp` in its own folder (0600
    from creation) and renamed over, so a failed write leaves the old file. A `deploy/.env` without a
    `COMPOSE_FILE` line (install.sh always writes one) is left as it is with a note, never guessed; `doctor`'s
    `anchor_mount` check reports it. Unattended (`--answers`) it is not run here: install.sh ran
    the check before it started the stack.
- **What was left out, and why:**
  - **An anchor on the box's own disk is not refused** here: the card says "unmountable", and a local folder mounts.
    The preflight's `audit_share` line (D-1361) and `doctor` already show it red; a stricter refusal would be a card.
  - **The console's readability of the anchor folder** is not checked by box-install.sh (install.sh's ANCHOR-MOUNT
    asks the console's image with `docker run`; the box form leaves it to `doctor`'s `anchor_mount` check).
  - **The log folder is not refused**: the card asks for a refusal for backups and the anchor only. Its folder is not
    made or checked; `trialbox logs` writes there as before.
  - **The terminal settings wizard** (`tools/settings_wizard.py`) asks no new question: the IT form names the folders
    in `deploy/.env` or the answers file's `env_extra`, as before, and is refused by install.sh's block.
  - **A first-run page refusal**: not added, so D-1365's PRODUCTION cases and `production_gaps` stay as they are; the
    page cannot see the disks, and the box's check is the guarantee.
  - The `backup-keygen` wording of the install and runbook 05 is untouched (a later docs card).
- **Another lane's files (lane G's box run):** its local rehearsal (`tests/rehearsal/box-run/rehearse-box-run.sh`,
  run by `tests/unit/test_g1_box_install_run.py`) answered a PRODUCTION first run with a second disk that nobody
  mounted and no anchor folder, and expects "TrialBox is ready": ten of its cases stopped at 03-wizard. Its synthetic
  answers now name a backup folder declared off the box (with the mark) and an anchor folder, both made by the
  rehearsal, as IT would mount them; nothing else of it changed. The paid run's VM script
  (`deploy/gcp/box-install-run.sh`) is not changed: the answers it posts come from its operator's secret, which must
  name the same two folders (mounted on the VM) or say VALIDATION, or its first run now stops at this check.
- **Invariant test (the card's central promise):**
  `tests/unit/test_install_refuses_unsafe_folders_10k4.py::test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor`.
  The card's promise is the refusal, and its proof is the install exiting before "finished" in both cases; this test
  is that sentence: each of the two cases, for both installers that can finish a PRODUCTION box (install.sh's block
  as it stands in the file, and box-install.sh run whole after the set-up), asserts exit 1, no "finished" line
  ("TrialBox is running." / "TrialBox is ready"), the reason said, and nothing restarted; and the same box with a
  backup off the box and its anchor folder there finishes, so the test cannot pass by refusing everything.
- **Held by:** `tests/unit/test_install_refuses_unsafe_folders_10k4.py` (the invariant; each way a PRODUCTION box may
  not finish; one target off the box is enough; nothing refused outside PRODUCTION; no `TB_ENV` is PRODUCTION; the
  check writes nothing; `TB_BOX=1` skipped and `TB_BOX=0` checked; the block's place and its fixed command; the
  anchor mounted into the console on a box, the `.env` 0600, a rerun the same; refused, then finished once mounted;
  the folder rule; the plan's values and defaults), `tests/console/test_firstrun_folders_10k4.py` (the fields in
  en, ja, zh-TW; the PRODUCTION hint; the answers file; a refused folder shown at its field; the whole path with the
  real box-install.sh and page: refused, then finished), `tests/console/test_box_install_rehearsal.py` (its
  PRODUCTION owner now names a mounted backup folder and anchor folder).
