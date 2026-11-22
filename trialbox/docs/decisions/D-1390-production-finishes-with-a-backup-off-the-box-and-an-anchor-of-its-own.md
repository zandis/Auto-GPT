# D-1390 A PRODUCTION install finishes only with a backup shown to be off the box and the audit share as anchor (10K-4)

- **Task:** lane K, plan 10 row 10K-4 (review 18, SO-4): "Backup, anchor and log folders chosen in the wizard; a
  PRODUCTION install refuses to finish with on-box-only backups or an unmountable anchor". Proved by: "The install
  test exits before 'finished' in both cases". Builds on D-1361 (10K-3: the preflight; it named this card) and D-1365
  (10K-21: the first-run page as the box's wizard, the box plan's `env_extra`). Reworked after two independent reviews
  of #1303 (first: 2 High, 4 Medium, 8 Low; second: 2 High, 7 Medium, 7 Low) and a third (M1, M2, M3, the test gap
  M19, one Low fixed; three Lows listed below as not told). · **Date:** 2026-11-21
- **What the card asks:** 1. the backup folder, 2. the audit anchor folder, 3. the log folder chosen in the wizard;
  4. a PRODUCTION install that refuses to finish with on-box-only backups; 5. or with an unmountable anchor; 6. an
  install test that exits before "finished" in both cases.
- **The principle:** the check accepts only what it can show. Whatever it cannot tell is refused as "cannot be told",
  with a true message, never taken as probably fine.
- **What an anchor share is, by the card's words:** an anchor that can be "mounted" is the hospital's audit share
  (D-1361's `audit_share`: a write-once share off the box). In PRODUCTION the anchor folder is the share's own mount
  point on the box, on nfs, nfs4, cifs or smb3, served by a host that is not the box. A local folder, a Windows drive,
  removable media, the system's logs are not an anchor share.
- **What the console can reach, before and after this card.** Before: from the host, `settings.yaml` (read-only), the
  ops folder `TB_OPS_DIR` (read-write; requests and status, D-178), on a box the first-run folder (tmpfs), its own
  Docker volumes (console data and objects; audit, rulesets and terminology read-only), and an anchor folder
  read-only only when root had set `TB_AUDIT_ANCHOR_TARGETS` (D-638). After: the same, and the anchor folder the
  first-run page names, read-only, only when it passes the rule below. Of the folders the page asks, the console reads
  that one only (the backup and log folders are the host's). The page and its texts say exactly that.
- **Decision (what was built):**
  - **The wizard** is the box's first-run page (D-466, D-1365) and the unattended answers file (D-898).
    `tb_common.box_answers` has three optional answers: `backup_dir` (where the disk or share is mounted; empty keeps
    `/srv/trialbox-backup` or `/mnt/trialbox-share`; the plan writes it as `TB_BACKUP_TARGETS` and, for a second disk,
    `TB_BACKUP_OFFBOX`, which the nightly backup's rule needs), `anchor_dir` (`TB_AUDIT_ANCHOR_TARGETS`) and `log_dir`
    (`TB_LOG_DIR`; the audit archive stays in `deploy/logs/audit-archive`). One allow rule,
    `tb_common.host_folders.allowed`, at the page and on the host: one plain full path; not `/`; not equal to, inside
    or around a system folder (`/bin /boot /dev /efi /etc /home /media /opt /proc /root /run /sbin /snap /sys /tmp /usr
    /var/backups /var/cache /var/lib /var/log /var/mail /var/run /var/spool /var/tmp`, every top `lib*`); three separate
    folders (`host_dir_overlap`).
  - **The host check**, `tools/trialbox/finish_check.py` (`python3 -m tools.trialbox finish-check`; exit 0 passed, 1
    refused with the setting to change, 2 it could not run). Every folder must be there with its real path the path
    written; a bind mount's source (mountinfo's root field) must be placed on the host and pass the same rule; it may
    not overlap the install folder, `deploy/secrets`, the feed folder, the audit volume and archive, the host's
    secrets and key folders or the other two folders; and its visible mount (a mount hidden under a later one is not
    used) must have a file system of the list: **ext4, xfs, btrfs, exfat, vfat, ntfs3, nfs, nfs4, cifs, smb3**, and
    WSL2's 9p and drvfs for backups only (by `backup_schedule`'s outside-drive rule).
  - **The anchor folder** must also: not be on 9p or drvfs; have every parent owned by root (the installer's user)
    and not writable by group or others, so no other account can put a link in its place; in PRODUCTION be the mount
    point of a network share whose server is not the box. Checked before anything mounts it: install.sh's ANCHOR-GATE
    (before ANCHOR-MOUNT's read probe, whatever `TB_BOX` says), box-install.sh before its read probe and mount, and
    **again at every start of the stack**: `deploy/settings_guard.sh` (the existing `ExecStartPre` of
    `trialbox.service`, also run by `tools/apply_update.sh`) runs `finish-check --anchor-only` when the box mounts an
    anchor and refuses the start when the rule no longer holds. Mount the share `nosuid,nodev` on the host (compose's
    bind gives read-only only).
  - **In PRODUCTION** it refuses: no backup target shown to be off the box; no anchor folder; an anchor or log folder
    that breaks the rule. In every environment it refuses an anchor folder that breaks the rule. `TB_ENV` is read as
    install.sh reads it (only a line starting `TB_ENV=`, the last one; quotes, spaces, CR dropped; none is PRODUCTION).
  - **`deploy/install.sh`:** FINISH-EARLY, before the bundle step, on a re-run (`deploy/.env` there), not for
    `TB_BOX=1`, `--rehearsal`, nor the run from the signed tree after a load: refused there, nothing was loaded or
    changed. That run is told by one test, the one the bundle step uses not to load again: `TB_INSTALL_SIGNED` is the
    release `current` names; any other value (one `sudo -E` carried in) is checked like any re-run (review 3, M2). The
    environment it judges is the stricter of the box's own (`TB_ENV` of `deploy/.env`; none on an installed box, or a
    value that is none of the four, is PRODUCTION) and `--environment`, so a PRODUCTION box run again with
    `--environment VALIDATION` is refused before anything is loaded (review 3, M1; the ENVIRONMENT step refuses the
    change itself later, as before). ANCHOR-GATE before ANCHOR-MOUNT. FINISH-GATE before the stack starts (unless
    `TB_BOX=1`): by then this run loaded the bundle; on a box that was running, `apply_update.sh` applied the release
    and restarted the stack. That is the case of **the first run of this release on an installed site**: the old
    install.sh (with no FINISH-EARLY) loads the bundle, then runs this one from the signed tree. The refusal says
    what is true: the bundle stays loaded (applied and running on a box that was), the settings written stay, the
    install's own start, units, cron and checks were not run; correct `deploy/.env` and run the install again. One
    shell function runs the check and tells a refusal (exit 1) from a check that did not run (any other code).
  - **`deploy/box-install.sh`**, after the owner's answers are applied, before the restart: the check, the console
    image's read probe of the anchor (as install.sh's ANCHOR-MOUNT), the read-only mount (`--mount-anchors`; the
    `.env` rewrite keeps each line's end, the mode and owner, refuses a link). A refusal says how to go on: mount the
    share or disk at the folder named, or correct the line (the first-run page does not open again), then
    `sudo deploy/box-install.sh --firstrun`.
  - **The test stand-ins** (`TB_FINISH_MOUNTINFO` with `hosts`, `own-addresses` and `local-networks` beside it,
    `TB_FINISH_SYS`,
    `TB_FINISH_TEST_ROOT`) are honoured only when `TB_TEST_ROOT` names a folder holding the tests' marker
    (`.tb-test-root`, `tools.pglocal.MARKER`) and every stand-in is inside it. Set any other way (a root shell,
    `sudo -E`, a wrapper) the check refuses and says so. Lane G's box-run rehearsal is a rehearsal: it makes such a
    marked root and says so in its script.
- **What the gate can and cannot tell:**
  - **Accepted (shown):** a backup target on nfs, nfs4, cifs or smb3 whose server's name resolves (or is an address) to
    addresses, with the `addr=` the kernel mounted it from, none of which, an IPv4-mapped IPv6 address read as its IPv4
    address (`[::ffff:127.0.0.1]` is 127.0.0.1), is loopback, unspecified, link-local, multicast, one of the box's own,
    or in a network of a local-only interface of the box (`ip -j -d addr`: loopback; docker0, `br-*`, `virbr*`, veth,
    dummy and other container links; a bridge none of whose ports is a physical device, so a container at 172.17.0.2 is
    the box; review 3, M3), and which the nightly backup also counts; a backup target on ext4, xfs, btrfs, exfat, vfat
    or ntfs3 whose whole-disk chain (a partition's parent; every member of a device-mapper or md device; every device of
    a btrfs file system in `/sys/fs/btrfs/<fsid>/devices`) ends only in physical disks (a `device` entry, not under
    `devices/virtual`, not loop, zram, ram or nbd), none of them a disk of `/`, the install folder, Docker's data root
    (`data-root` of `/etc/docker/daemon.json`, else `/var/lib/docker`: the database and audit volumes),
    `TB_AUDIT_HOST_DIR`, `TB_AUDIT_ARCHIVE_DIR`, `TB_KEK_HOST_DIR` or `TB_SECRETS_HOST_DIR` (the key and secrets
    folders: review 3), named by `TB_BACKUP_OFFBOX`, and counted by the nightly backup; under WSL2 a Windows drive the
    nightly backup counts as an outside drive (D-608). An anchor folder that is the mount point of such a share, under
    root-only parents, with no link and no bind of another folder.
  - **Refused as cannot be told:** a block device /sys does not know, a loop device, zram, a ram disk, nbd, a virtual
    device without members, a disk with no hardware behind it; a btrfs whose devices cannot be read; a disk of `/`, the
    install folder, Docker's data root, the audit folders or the key and secrets folders that cannot be told (then no
    local disk counts; a share still does); a share whose server cannot be read from its source or whose name does not
    resolve; any share when the box's own addresses and networks cannot be read (no `ip`: `hostname -I` no longer stands
    in, it names no network); an address the check cannot read; a bind mount whose source cannot be placed; a folder
    with no visible mount, or a mount with any other file system; the stand-ins set outside a marked test root.
  - **Not told, left as written (review 3's Lows):** Docker's data root set by `--data-root` in the Docker unit's
    command line instead of `daemon.json` is not read (the gate takes `/var/lib/docker`, so a backup on the disk of a
    data root moved that way is not seen as the box's); the stand-ins are trusted once `TB_TEST_ROOT` names a folder
    holding the marker, as the stand-in rule above says (whoever can make that folder and set the environment of a
    root command can already change the box); on a host without `python3`, ANCHOR-GATE does not run (the anchor
    folder is then not mounted into the console either: ANCHOR-MOUNT needs `python3` too, and FINISH-GATE refuses a
    PRODUCTION install there). Also not told: a bridge whose ports are virtual but which is routed to the network
    outside counts as the box's (refused: fail closed), and a share served by a virtual machine of the box on a
    bridge with a physical port counts as off the box.
- **The gate and the nightly backup agree:** a target the gate accepts is one `backup_schedule.target_kind` (the
  nightly backup's rule) counts off the box; the gate is stricter (the `.trialbox-offbox` mark alone is not a disk).
  Both sides are tested: the accepted targets, and targets every other rule of the gate passes but the nightly rule
  does not count (a second disk without its mark, a Windows drive without the outside-drive mark), which the gate
  refuses (review 3, M19).
  `backup_schedule.py`, another lane's file, is not changed.
- **Two ways the gate is not run, by design:** `TB_BOX=1` in the installer's environment (box-install.sh checks after
  the page) for the backup and PRODUCTION refusals (ANCHOR-GATE still runs), and VALIDATION, a first-run answer
  (D-822), which the PRODUCTION refusals do not stop.
- **Runbook steps that run `deploy/install.sh` again** stop on an installed PRODUCTION site until both are set:
  runbook 02 (the anchor folders), 05 (after a restore; the EDC tables), 12 (the TLS check per release). Runbook 05's
  paragraph (after its last line) says so; `trialbox update` and `trialbox restore` do not run install.sh.
- **Noted, not changed:** the anchor and the backups may be folders of one NAS (separate folders; an independent
  witness on another server would be a card of its own). The three stand-ins are declared in `tb_common.config` (the
  declaration test requires it), described there as test-only.
- **What was left out:** a local anchor outside PRODUCTION is allowed (VALIDATION and TEST boxes); the terminal
  settings wizard asks no new question; a first-run page refusal of a missing folder (the page cannot see the host);
  the `backup-keygen` wording (a later docs card).
- **Another lane's files:** lane G's rehearsal (`tests/rehearsal/box-run/rehearse-box-run.sh`) names
  `/mnt/backup-disk` and `/mnt/audit-share` and gives the check a host of its own in a marked test root; the paid run's
  VM script (`deploy/gcp/box-install-run.sh`) is not changed: its answers secret must name a mounted backup folder (a
  share, or a physical disk other than the VM's boot disk) and the audit share's mount point, or say VALIDATION.
  `deploy/settings_guard.sh` (the start hook) gains the anchor check; `libs/tb_common/config.py` the declarations.
- **Invariant test:**
  `tests/unit/test_install_refuses_unsafe_folders_10k4.py::test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor`:
  the card's proof sentence, both cases, against install.sh whole as a re-run (it stops before the bundle step; a
  good box reaches it), box-install.sh whole after the set-up, and install.sh's FINISH-GATE block as it stands (a first
  install cannot run whole in a test: a signed bundle, images and a compose stack come first); each asserts exit 1, no
  "finished" line, the reason, nothing restarted, and the good box gets past.
- **Held by:** that file (H1 and H2 of the first two reviews, every Medium and Low, the third review's M1 to M3, M19
  and the key folders' disks: what a disk is, the box's shares, the
  nightly rule, binds, links, parents, Windows drives, the start hook, the stand-ins, TB_ENV, hidden mounts, the real
  mount table, exit 2, the `.env` rewrite, the page's rule, the plan, the runbook), `tests/console/test_firstrun_folders_10k4.py`
  (the fields and texts in en, ja, zh-TW; refusals at the page; the whole path with the real box-install.sh and page),
  `tests/console/test_box_install_rehearsal.py`.
