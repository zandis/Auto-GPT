# D-1390 A PRODUCTION install finishes only with a backup off the box and an audit anchor folder of its own (10K-4)

- **Task:** lane K, plan 10 row 10K-4 (review 18, SO-4): "Backup, anchor and log folders chosen in the wizard; a
  PRODUCTION install refuses to finish with on-box-only backups or an unmountable anchor". Proved by: "The install
  test exits before 'finished' in both cases". Builds on D-1361 (10K-3: its preflight page is a snapshot taken
  before these answers, and named this card for the folder choice and the refusal) and D-1365 (10K-21: the box's
  first-run page as the box's wizard, `production_gaps`, the box plan's `env_extra`). Reworked after the independent
  review of #1303 (2 High, 4 Medium, 8 Low). · **Date:** 2026-11-21
- **What the card asks:**
  1. the backup folder chosen in the wizard;
  2. the audit anchor folder chosen in the wizard;
  3. the log folder chosen in the wizard;
  4. a PRODUCTION install that refuses to finish when its backups are only on the box;
  5. a PRODUCTION install that refuses to finish when its anchor cannot be mounted;
  6. an install test that exits before "finished" in both cases.
- **For the owner: what a person at the first-run page can make the console read.** One folder of the host, the
  audit anchor folder, bind-mounted into the console read-only (`deploy/site/compose.anchors.yml`, D-638), and nothing
  else of the host. The folder is given only when all of this holds: it is written as one plain full path; it is
  not `/` and does not equal, sit inside or contain a system folder (`/bin`, `/boot`, `/dev`, `/etc`, `/home`,
  `/opt`, `/proc`, `/root`, `/run`, `/sbin`, `/snap`, `/sys`, `/tmp`, `/usr`, `/var/lib`, `/var/run`, `/var/tmp`,
  every top folder whose name starts with `lib`; so `/var` and `/` are refused too); it is there and its real path is
  the path written (no link anywhere in it: `/proc/<pid>/root` and a link to `/etc` are refused); it does not
  overlap the install folder, `deploy/secrets`, the feed folder (`TB_SOURCE_DIR`), the audit volume and archive
  (`TB_AUDIT_HOST_DIR`, `TB_AUDIT_ARCHIVE_DIR`), the host's secrets and key folders (`TB_SECRETS_HOST_DIR`,
  `TB_KEK_HOST_DIR`), any backup target or the log folder; and it is on a disk or a share (the file systems below).
  The page checks the text part of this; the box installer checks all of it on the host before it mounts the folder,
  in every environment, and then asks the console's own image whether it can read it (as install.sh does).
- **Decision (what was built):**
  - **The wizard** is the box's first-run page (D-466, D-1365) and the unattended answers file that shares its
    schema (D-898). `tb_common.box_answers` has three optional answers: `backup_dir` (the folder where the second
    disk or the share is mounted; empty keeps the plan's `/srv/trialbox-backup` or `/mnt/trialbox-share`; with
    "later" there is no place to name), `anchor_dir` (`TB_AUDIT_ANCHOR_TARGETS`) and `log_dir` (`TB_LOG_DIR`; empty:
    `deploy/logs`; the audit archive stays in `deploy/logs/audit-archive` either way, as the page says). Each is held
    by one **allow rule**, `tb_common.host_folders.allowed` (standard library; the page and the host use the same
    code): one plain full path of letters, digits, `.`, `_`, `-` and `/`, no `.`, `..` or empty part, at most 255
    characters (a longer one is refused, never cut), not `/`, and no system folder as listed above equal to, inside or
    around it. **The three folders are three separate folders** (`overlapping_pair`): the anchor holds neither
    backups nor logs (the console reads it), and the backup and log folders are pruned by different tools; a refusal
    is `host_dir` or `host_dir_overlap` at the field. Only a chosen folder is written, so a box that was not asked
    writes what it wrote before. `tools.box.plan` writes them into `env_extra` only when chosen.
  - **The page asks; the box decides.** The console cannot see the host. On a PRODUCTION box the page says what the
    box will check: a backup folder on a share or on a disk that is not the system disk, and an audit record folder
    of its own on a disk or a share; and that the web page can read that one folder, read-only.
  - **One check on the host**, `tools/trialbox/finish_check.py` (`python3 -m tools.trialbox finish-check`). Each
    folder `deploy/.env` names is judged by what it is (`folder_problem`): the allow rule; a folder that is there
    whose real path is the path written; no overlap with the folders listed above (the log folder alone may be the
    install's own `deploy/logs`, or below it, and hold the audit archive there); and its mount, the longest mount
    point of `/proc/self/mountinfo` holding its real path, on a file system of the **allowed list: ext4, xfs, btrfs,
    exfat, vfat, ntfs3 (a local disk), nfs, nfs4, cifs, smb3 (a share), and WSL2's 9p and drvfs** (Windows drives,
    judged by `backup_schedule`'s own outside-drive rule, D-608). Every other file system is refused, the memory and
    kernel ones above all (tmpfs, ramfs, proc, sysfs, devtmpfs, overlay, squashfs). The list is what the backup on
    master writes to (its `NETWORK_FS` beyond nfs and cifs, sshfs and the like, is not taken: a box's backup share is
    NFS or SMB).
    - **A backup target is off the box** (`off_the_box`) on a share of that list, or on a local disk whose **whole
      disks** are none of the disks of `/` and of the install folder: `/sys/dev/block/<major:minor>` (or the mount's
      source) names the device, a partition counts as its parent disk, a device-mapper or md device as the disks of
      its members (`slaves`), recursively. **Another partition of the system disk, or an LVM volume on it, is the
      system disk.** When the system disk cannot be told (an overlay root), no local disk is counted, a share still
      is. A target that is not off the box (`deploy/backups`) may stay beside one that is; it is not counted. The
      `.trialbox-offbox` mark no longer satisfies this check (the nightly backup still honours it:
      `backup_schedule.py`, another lane's file, is not changed).
    - **In PRODUCTION** (`TB_ENV`, read as install.sh reads it: quotes, spaces and CR dropped, upper case; no value
      is PRODUCTION, D-127) it refuses: no backup target off the box; no anchor folder; an anchor or log folder that
      breaks the rule. **In every environment** it refuses an anchor folder that breaks the rule (it is about to be
      given to the console). Each refusal names the setting to change in `deploy/.env`.
    - It writes nothing, except `--mount-anchors`, which writes `compose.anchors.yml` (`anchors.write`) and keeps
      `COMPOSE_FILE` naming it: `deploy/.env` is rewritten through `mkstemp` in its own folder with the old file's
      mode (and owner, as root) and each line's own line end, then renamed over it; a `deploy/.env` that is a link is
      refused, and one with no `COMPOSE_FILE` line is left as it is with a note. No lock is taken: at that point no
      other writer runs (box-install.sh is one sequential process, and the apply that wrote `.env` has returned).
    - The host's python3 needs no PyYAML for the check; only `--mount-anchors` imports `anchors` and says so when
      yaml is missing. Stand-ins for the tests only: `TB_FINISH_MOUNTINFO`, `TB_FINISH_SYS` and
      `TB_FINISH_TEST_ROOT` (a folder that stands for `/`: a folder named `/mnt/x` is looked for there and judged as
      `/mnt/x`), as `TB_TIER_TEST_*` stand in for the hardware.
  - **`deploy/install.sh`, FINISH-EARLY**, before the bundle step, on a re-run (a `deploy/.env` already there),
    unless `TB_BOX=1` or `--rehearsal`: the check, with the environment ENV-EARLY read. On a running box the bundle
    step applies the update and restarts the stack, so a refusal here leaves nothing loaded or changed, and says so.
  - **`deploy/install.sh`, FINISH-GATE**, after the backup default is written and before the stack starts, unless
    `TB_BOX=1`: the check (the environment as the tool reads it, so `production` or `"PRODUCTION"` written by hand is
    PRODUCTION too). On a first install the refusal says what is true: the stack was not started, and the bundle and
    settings this run wrote stay for the re-run. No `python3` in PRODUCTION is a refusal.
  - **`deploy/box-install.sh`**, after the owner's answers are applied (and on a `--firstrun` after an earlier apply),
    before the restart and the last line: the check (`--print-anchors`), then the console image's read probe of each
    anchor folder (the same `docker run --network none -v <folder>:/anchor:ro` test install.sh's ANCHOR-MOUNT runs;
    `TB_BOX_DOCKER` stands in for docker in the tests), then `--mount-anchors`. A refusal says how to go on: mount
    the disk or the share at the folder named, or, when a folder was typed wrongly or is mounted elsewhere, change the
    setting each line names in `deploy/.env` (for a second disk `TB_BACKUP_TARGETS` and `TB_BACKUP_OFFBOX` name the
    same folder); the first-run page does not open again (no supported command re-asks a folder after the apply);
    then `sudo deploy/box-install.sh --firstrun`. Unattended (`--answers`) install.sh checked before it started.
- **Two ways the gate is not run, by design (review L3):** `TB_BOX=1` in the installer's environment (root's own
  environment; box-install.sh sets it for the box's install before its first-run page, and checks after the page),
  and VALIDATION, a first-run answer (D-822): whoever fills in the page may make a VALIDATION box, which the backup
  and anchor refusals do not stop. The anchor rule holds in every environment.
- **Runbook steps that run `deploy/install.sh` again** now stop on an installed PRODUCTION site until both are set:
  runbook 02 (after the anchor folders change), runbook 05 (after a restore, for the role script; the EDC tables),
  runbook 12 (the TLS check per release). Runbook 05's paragraph (added after its last line) says so; `trialbox
  update` and `trialbox restore` do not run install.sh.
- **What was left out, and why:**
  - **An anchor on a local disk is allowed** (a folder of its own on a real file system): the card says
    "unmountable", and the preflight's `audit_share` line (D-1361) shows a local anchor red; requiring a share is a
    card of its own.
  - **The log folder's own refusal is PRODUCTION only** on the host (the page refuses a system folder everywhere).
  - **The terminal settings wizard** asks no new question: the IT form names the folders in `deploy/.env` or the
    answers file's `env_extra` and is held by install.sh's two blocks.
  - **A first-run page refusal of a missing folder**: the page cannot see the host; `production_gaps` (D-1365) is
    unchanged.
  - The `backup-keygen` wording of the install and runbook 05 is untouched (a later docs card).
- **Another lane's files (lane G's box run):** its local rehearsal (`tests/rehearsal/box-run/rehearse-box-run.sh`, run
  by `tests/unit/test_g1_box_install_run.py`) answered a PRODUCTION first run with a second disk nobody mounted and no
  anchor folder, and expects "TrialBox is ready". Its synthetic answers now name `/mnt/backup-disk` and
  `/mnt/audit-share`, and it gives the check a host of its own (a mount table where they are a second disk and an NFS
  share, a sysfs, a folder standing for `/`; the three stand-ins above); nothing else of it changed. The paid run's VM
  script (`deploy/gcp/box-install-run.sh`) is not changed: the answers it posts come from its operator's secret, which
  must name a mounted backup folder (on a disk other than the VM's boot disk, or a share) and an anchor folder, or say
  VALIDATION, or its first run now stops at this check.
- **Invariant test (the card's central promise):**
  `tests/unit/test_install_refuses_unsafe_folders_10k4.py::test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor`.
  The card's promise is the refusal, and its proof is the install exiting before "finished" in both cases; this test
  is that sentence. Each of the two cases runs against the real scripts: install.sh whole as an installed box runs
  it again (a stand-in docker engine; it stops at FINISH-EARLY, before the bundle step, and a good box goes on to the
  bundle step), and box-install.sh whole after the set-up (stand-ins for compose, the host check and the image's read
  probe). A first install of install.sh cannot run whole in a test (a signed bundle, its images and a compose stack
  come before its gate), so its FINISH-GATE block runs as it stands in the file, followed by the last banner. Each
  asserts exit 1, no "finished" line ("TrialBox is running." / "TrialBox is ready"), the reason said, nothing
  restarted; and the same box made good gets past, so the test cannot pass by refusing everything.
- **Held by:** `tests/unit/test_install_refuses_unsafe_folders_10k4.py` (the invariant; H1: tmpfs, squashfs,
  `/dev/shm`, `/proc`, `/sys`, `/run`, `/boot`, `/home`, another partition and an LVM volume of the system disk, a
  folder of `/` are not off the box, a second disk and a share are, the mark alone is not, an untold system disk
  counts no local disk; H2: every system folder, the install folder, its secrets, the feed and audit folders and a
  link are never given to the console, in PRODUCTION and VALIDATION, the anchor holds no backup or log; M1: the
  re-run check is before the bundle step and changes nothing, the first-install refusal says what was written; M3:
  the box's refusal says how to correct a folder; M4: runbook 05 names the steps; L1: no PyYAML; L2: TB_ENV read as
  the tools read it; L4: the `.env` keeps its line ends, last line, mode, and a link is refused; L5: the image's read
  probe before the mount, and a refusal when it cannot read; L8: the log folder's rule; the page's allow rule and
  the three separate folders; the plan's values and defaults), `tests/console/test_firstrun_folders_10k4.py` (the
  fields in en, ja, zh-TW; the texts say what is checked; system folders and overlapping folders refused at the
  page; the whole path with the real box-install.sh and page: refused, corrected, finished),
  `tests/console/test_box_install_rehearsal.py` (its PRODUCTION owner names a second-disk folder and a share folder
  on the test's own host).
