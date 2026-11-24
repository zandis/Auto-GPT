# LR: the box's lifecycle as a state machine, one deep review

**Reader:** lane H (which fixes from this page in consolidated cards), the integrator, the external reviewer and the
owner. Findings for builders, so in one language.

- **Card:** LR (lane LR, the owner's ruling of 2026-11-24 on pull request #639)
- **Date:** 2026-11-24
- **Base:** master `00bababf8f57df6143b7b47fd36f4c15f5b29e5f`
- **Open pull requests read beside it:** #1455 at `973a87aa`, #1466 at `ee78d84a`, #1469 at `68e67c5b`, #1470 at
  `7831433a`, #1472 at `27e8f0d8`. H-124 is not pushed and #1457 (H-111) was not read; both are named where they apply.
- **Findings:** [`lifecycle-deep-review-2026-11-24/findings.json`](lifecycle-deep-review-2026-11-24/findings.json)
  (LR-1 to LR-70)
- No product file, test or runbook page is changed by this card. Lane H fixes.

## The result in short

- **70 findings: 20 High, 33 Medium, 17 Low.** 33 were reproduced in whole or in part (most with stand-ins for the
  engine, systemd or the TPM; one with a real PostgreSQL), 36 rest on reading only, and 1 is a hypothesis (LR-28: its
  mechanism was reproduced, no failing case was found). Each says which.
- **The matrix has 238 cells: 115 covered on master, 16 covered only by a test in an open pull request, 106 gaps,
  1 not applicable** (there is no uninstall to test). "Covered" is generous: most covering tests drive a stand-in
  engine or an in-process box.
- **Four root causes explain most of it.**
  1. **Nothing runs two different releases.** No test, rehearsal or CI job installs release N-1 and then moves to N.
     Bundle and tree always come from one checkout, and every rehearsal uses release number 1 (LR-20). No job updates
     or rolls back an installed compose box at all (LR-19). Every fault of the "the installed code runs first" kind
     is therefore invisible until the walk box meets it.
  2. **Nothing durable says "an operation was in progress" to the boot path.** The update's marker and the restore's
     work folder exist, but the boot unit reads neither (LR-9, LR-38). A power cut inside an update, a rollback or a
     restore ends with the stack started on a half-changed box.
  3. **The key commands run as root and leave root's files** where a service account must read them, and the TPM
     credential and its boot unit are written once and never again (LR-3 to LR-6, LR-45). The passphrase box is stuck
     here, not only at the missing option of `tools/apply_update.sh`.
  4. **Paths and names are assumed, not asked for:** the engine's volume folder, the project name, the engine itself.
     A data root elsewhere makes a restore report success having restored no folder (LR-15), skips the key check
     before an update (LR-34), and the undo of an image load resets every image on a shared engine (LR-11).
- **Two findings are regressions that the open fixes would bring in:** #1455 switches the release before the bundle
  is verified whole (LR-18), and #1470 starts the whole stack after a refused re-run on a box that was told to stay
  stopped (LR-14). Both should be closed before those pull requests ride.
- **Three to act on today, before any card:** `deploy/poc.sh reset` deletes an installed box's volumes (LR-2); a
  restore onto a mounted data folder deletes the live folder when the rename fails (LR-1); on the bench host,
  master's `tools/bench_ci/install.sh remove` is still the dangerous command until #1466 rides, and the box
  rehearsal would delete that host's unsealed KEK (LR-43).

## How this was done

Six slices were read in parallel, each line by line, by a reviewer that could not change the tree: install and
bootstrap; update and rollback; backup and restore; the key operations; the bench runner; and what the rehearsals and
CI jobs really run. Each slice mapped its tests by opening them, and reproduced what it cheaply could in a scratch
folder with throwaway keys and stand-ins. Lane LR then read the High findings against the code again
(LR-1, LR-2, LR-3, LR-4 and LR-9 by reading the cited lines; the others were not re-run), merged the duplicates and
renumbered. Every test id in the matrix was checked to exist on master or on the named pull request.

**What "reproduced" means here.** A scratch copy of the real script or module was run and showed the stated outcome.
Nothing ran on a real Docker engine, under real systemd, on a real TPM or on the bench host. "Read only" means the
claim rests on the cited lines and was not run. Severity follows the register: High is data loss, a box that cannot
be updated, restored or unlocked, a false "healthy", deletion of something not ours, or code run from a path that is
not the signed release.

**Not read line by line:** `tools/make_bundle.sh`, `tools/sign_bundle.py`, `services/console/ops_pages.py`,
`tools/verify_update.py` after line 415, most of `tools/update_drill.py`, `deploy/check_host.sh`,
`tools/runbook_install.py`, the four large drill tools, `deploy/docker/backup.Dockerfile`, pgBackRest's restore and
`docs/runbook/13-parallel-work-on-one-machine.md`. The KMS back end was not traced.

## The findings

Each finding gives its place on master (or on the pull request named), the starting state and step, what happens,
whether it was reproduced, what already covers it, and a direction. No patch is proposed. "PR" before a line number
means the file at that pull request's head.

### High

**LR-1. A failed rename-aside makes the restore's put-back delete the live data folder.**
`tools/trialbox/backup.py:2519-2520` (the folder is recorded as moved before `dest.rename(aside)`), `:2217-2222`
(the put-back removes `dest` when it exists). State: any box whose data folder is a mount point (EBUSY), sits on
another filesystem, or cannot be renamed; or a signal between the two lines. The restore restores the databases,
fails at the rename, and the put-back, meaning to remove a half-written new folder, removes every file of the
original. No aside exists. With `--no-copy --yes-really` nothing is left. Reproduced: a real tmpfs mounted at the
lake folder, a real PostgreSQL, the real backup and restore; three files before, none after, state
`not_rolled_back`. On a folder that is not a mount point (a rename refused for another reason, or a signal between
the two lines) the put-back deletes the live folder, leaves an empty one and reports "put back as it was before the
restore": a false "put back". That case was reproduced by the external reviewer of this page, by calling the
put-back with the move recorded and the rename not done. Covered: no. Direction: record the move only after the
rename succeeded, and refuse a mount-point target before the first change.

**LR-2. `deploy/poc.sh reset` on an installed box deletes the site's volumes without a check or a question.**
`deploy/poc.sh:207-208`, `:41`, `:173`. The script is in the signed host tree, so it is on every box, and runbook 9
names `deploy/poc.sh status|down|reset`. It reads no `TB_ENV` and no `deploy/updates/installed.json`; `reset` runs
`docker compose ... down -v` on project `trialbox`. Plain `deploy/poc.sh` would start the site's project as a test
box and ingest the synthetic site into it. Reproduced with a stand-in engine on a tree marked PRODUCTION: exit 0 and
the `down -v` line. Covered: no test of `reset`. Direction: refuse on a box that records an install, or give the PoC a
project name of its own, or leave it out of the host tree.

**LR-3. After `rotate-kek` run as root, the services cannot open any key.**
`tools/keys.py:918-921, 938`, through `libs/tb_common/kek.py:117-130`. State: any sealed box; the runbook's own
command (`docs/runbook/23-key-inventory-and-the-lost-box-list.md`, which every box from before H-96 is told to
run). `kek.json`, every wrapped key and `/run/trialbox/kek` are replaced by files owned by root, mode 0600; the
services (uid 10001) get "kek.json cannot be read". The chown of D-887 is only at the end of the first seal
(`deploy/hardening/seal_keys.sh:240-244`). Same class, read only: `escrow-shares`, `rotate pid_map`, `wrap`,
`seal-objects`, `restic-key`. Reproduced: before, a process of uid 10001 opens the key; after `rotate-kek` exit 0 it
cannot. Covered: no. Direction: one place gives every file a key command writes, and the runtime KEK, to the secrets
folder's owner.

**LR-4. A passphrase or share-backed box cannot be opened by the documented step after a restart.**
`tools/keys.py:455-458`; `deploy/hardening/seal_keys.sh:168-179` (the re-run leaves before the chown);
`libs/tb_common/kek.py:431`. State: after a reboot or power cut `/run/trialbox` is gone; the operator runs
`tools.keys unseal` as `docs/runbook/22-planned-power-cut.md` says. The KEK file is root's, 0600; the services' load
raises a bare `PermissionError`, which `custody()` (`kek.py:630-638`) does not catch, so the doctor's key check
raises instead of reporting. Re-running the installer with the passphrase gives the same file. This is where a
passphrase box is really stuck: H-124's passphrase options would go through the same `unseal`. The TPM unit is not
affected (it has the chown). Reproduced, both the direct `unseal` and the installer's re-run. Covered: no.
Direction: `unseal` gives the file and its folder to the secrets folder's owner; an unreadable KEK is a `KekError`.

**LR-5. A signal or a failed `init` during the TPM seal destroys the only KEK after the keys are wrapped (H-111).**
`deploy/hardening/seal_keys.sh:199-206`; `tools/keys.py:394-396`. The trap on EXIT, INT, TERM and HUP removes the
plain KEK and the new credential; `keys init` has by then written `kek.json` and wrapped keys, removing each plain
file. Left: wrapped keys and no KEK; the re-run takes the "KEK exists" branch and cannot open them. Two ways in were
reproduced on master with a stand-in `systemd-creds`: SIGTERM while `init` returns, and an empty key file that stops
`init` after the first key was wrapped (the script then says "nothing was sealed; run this script again"). Known as
H-111, #1457 in flight and not read. Three states a signal handler alone does not close, read only: a KILL or power
cut between `init` and the `mv` (the credential stays as `.new`, which no code looks for); a stop between the `mv`
and the unit (sealed, no boot unit, never written again); either on a box that already made pseudonyms under plain
keys. Direction: once `init` has started never remove the credential; finish from `.new` on a re-run.

**LR-6. `rotate-kek --backend file` leaves the TPM credential sealing the old KEK, and nothing ever re-seals.**
`tools/keys.py:354-363`; `deploy/hardening/seal_keys.sh:168-179`. State: a TPM box after a custodian leaves, or a
new board opened from its escrow shares. The new KEK goes to a plain file the operator is told to seal and remove;
no code writes `/etc/credstore.encrypted/trialbox-kek`. At the next boot the unit fails "is not this box's KEK"; if
no new escrow set was made the keys are lost at that reboot. A restored box that has `kek.json` never gets a
credential or a unit: every boot needs a witnessed unseal. `docs/runbook/22-replacing-hardware.md` step 3 names a
path the code does not have. Reproduced with the stand-in. Covered: no. Direction: a mode that seals a given KEK to
this board, swaps the credential only after it opens, and renders the unit.

**LR-7. `rotate-kek` overwrites and consumes the key an interrupted `rotate pid_map` staged.**
`tools/keys.py:989-990` and `:741-743` build the same name, `pid_map.key.wrapped.next`; the guard at `:868` looks
for another pattern; `:920` replaces the file and `:777-778` unlinks it on rollback. State: `rotate pid_map` killed
(or a power cut) after its database commit and before the rename; then `rotate-kek`, the next command of the
compromise procedure. The only copy of the key the pid-map rows are now under is destroyed; `custody()` reports
nothing in that state. Reproduced for the file half; the database half is read only. Covered: no. Direction:
`rotate-kek` refuses while a staged file it did not journal exists; `rotate pid_map` takes the folder lock and its
own name.

**LR-8. On a PRODUCTION box a TPM-sealed KEK has no recovery copy (a ruling's consequence, for the owner).**
`tools/keys.py:494-498` (`escrow-shares` refused on PRODUCTION), `:855-861`. The KEK then exists only in the
credential bound to this board. A board swap, a replaced system disk, a restore onto another host or a TPM policy
that no longer matches means the site keys cannot be opened; the backup holds only their wrapped form. The restic
increment is also off on such a box (`tools/trialbox/restic_repo.py:11-15`). `seal_keys.sh:202` passes no PCR list,
so the effect of a firmware change is the installed systemd's default; not verified (no TPM). Read only. Direction:
the owner rules whether an escrow set is part of sealing a PRODUCTION TPM box.

**LR-9. After a power cut inside an update, the boot unit starts the stack on a between-releases box.**
`deploy/systemd/trialbox.service:19-21`; `tools/update_status.py:405, 420-426`. Nothing at boot reads
`deploy/updates/IN_PROGRESS.json`. `update_status check` is called a start guard by runbook 5 and is called by no
unit, not by `deploy/settings_guard.sh` and not by `deploy/install.sh`. The unit runs `compose up` with whatever
tree `current` names: new images on a database whose steps never ran, or old images on a migrated database when the
cut came inside a rollback. Services run their own start-time migrations and can report healthy. Read only (the
absence was confirmed by search). Covered: no; the kill drills never boot anything. Direction: the boot unit
refuses while the marker stands and names the two commands.

**LR-10. `rollback` after a kill in "refdata" or "finish" restores the pre-update database over a live, checked
release.** `tools/trialbox/update.py:1328-1353`, `:1543-1551`, `:2445`. After "check" the box is in service; the
reference-data load may run for hours. A KILL, a power cut or a stop of the unit (LR-33) there leaves a marker with
`check` done, and the only command offered is `rollback <bundle>`: both databases are dropped and restored from the
dump taken before the update. Every row written since the restart is lost without a word. Reproduced with the real
`Updater` on a stand-in box. `tools/update_drill.py:202-246` asserts this outcome, so it is by design today.
Direction: a marker whose steps hold `check` is finished forward, not rolled back.

**LR-11. The undo of a streamed image load puts the whole Docker engine back, not the archive's tags.**
`tools/trialbox/update.py:571-593`, `:599-604`, `:1764`, `:2958-2960`. The undo compares every tag and image id of
the engine with a record; it moves tags back and removes every image that was not there with `docker image rm -f`.
It can run days later, at `rollback` or at the next install. On an engine anything else uses (the bench host runs
the bench runner too) their images and tags go. Reproduced with a stand-in engine: the recovery removed an image the
update never loaded. Covered: the one test checks only images that were there before. Direction: undo only the tags
the archive pins and the ids its manifest names.

**LR-12. A failed rollback has no way out.**
`tools/trialbox/update.py:1459-1466, 1558-1559`; `tools/apply_update.sh:177-183`; runbook 5 ("If the rollback
itself fails, the marker stays: restore from the backup"). The restore puts back databases and folders only: images,
host tree and models stay as the failed rollback left them, and the marker stays, so every later update is refused.
The only command that removes the marker runs the failing rollback again, and if it now passes it restores the
rollback point over the restored box. Read only. Covered: no. Direction: an audited "this box was restored; close
update X" command, and a restore that names the marker.

**LR-13. A closed session kills the restore's host step, the container goes on, and the re-run starts a second
restore over it and says healthy.** `tools/trialbox/box_restore.py:602-606` (a print to stderr comes before the
signal is passed on), `:400`, `:362-365` (the sweep of `deploy/.restore-*` asks nobody whether a restore container
still runs), `:389`. State: the SSH session drops during a restore. The print to the dead terminal raises, the
container is never told, the lock is released. The same command again (what #1470's runbook text invites) removes
the first container's work folder, with the dumps its put-back needs, and starts a second restore on the same
databases. Reproduced under a pty with a stand-in container; not on the real engine. #1470 does not change these
lines. Direction: pass the signal on before any print; give the restore container a fixed name and refuse while one
exists.

**LR-14. On #1470 only: a re-run refused before any change starts the whole stack on a box told to stay stopped.**
PR `tools/trialbox/box_restore.py`, `_after` (the branch for a non-zero end with state `unchanged`) and
`start_and_wait`. State: an earlier restore ended `not_rolled_back`, services stopped; the re-run is refused inside
(older than 14 days, wrong site, wrong key, no place for a folder). The pull request runs `up -d --wait` for every
service and prints "healthy: N of N" on half-restored data; master starts nothing. Reproduced with the pull
request's file loaded in place of master's. It may be the external reviewer's Medium on #1470; its text was not
seen. Direction: after `unchanged`, start only what this run stopped.

**LR-15. With the engine's data root elsewhere, the host restore restores the databases, writes every folder into
the container's own layer, and reports the box restored.** `tools/trialbox/box_restore.py:247-248`, `:296-302`
(a volume folder that is not there is skipped silently); `tools/trialbox/backup.py:611`, `:2513-2527`. State: a
data root on the data disk, a rootless engine or a snap engine; no installer writes `TB_DOCKER_VOLUMES`. Databases
are restored, exit 0, "healthy"; lake, objects, audit chain, rule sets and secrets are still the old ones. The
nightly has the same root: `tools/trialbox/backup_schedule.py:1228-1237` skips the Caddy and Authelia volumes
silently. Host half reproduced (no `--dir` and no volume given to the container, exit 0); container half read only.
Covered: no; every test sets the variable. Direction: ask the engine for each volume's folder, and refuse when a
folder the backup holds has no target.

**LR-16. A box whose nightly sends the lake to restic cannot be restored or verified by the documented commands.**
(a) `docs/runbook/05-updates-backup-restore-secrets.md` and the disaster-recovery page never name
`--restic-from-box` or `--restic-share`; without one `tools/trialbox/backup.py:1140-1144` refuses the restore.
(b) `tools/trialbox/launch.py:78, 262-266`: the host's `backup-verify` mounts the file alone, so neither the
repository, the escrow file nor the checksum sidecar is in the container, and the sidecar check silently checks
nothing. (c) `tools/trialbox/box_restore.py:271` binds the backup's folder read-only while
`tools/trialbox/restic_repo.py:350-352` runs `restic restore` without `--no-lock`. (a) and (b) are certain from the
text; (c) was not run (no restic here). Covered: the tests use a fake restic with no locks. Direction: name the
options on the page, mount the repository where restic can lock, run one real restore of a restic backup in the
rehearsal.

**LR-17. A first install that loaded its bundle and then stopped cannot take a corrected release.**
`tools/trialbox/update.py:2915-2920`, `:2813-2822`, reached from `deploy/install.sh:769`. State: a fresh host; step
2 loaded bundle N and wrote `installed.json`; the install stopped before the stack ever ran. The vendor's corrected
N+1 is refused: "the box is installed ... but not running; start it, then run the update again". It never ran and
cannot start. No page says what to remove. Reproduced with the test suite's own harness. Covered: the refusal is
pinned for a box in service, which is right; the never-started case is not told apart. Direction: tell "loaded,
never started" from "installed and has run".

**LR-18. On #1455 only: the bootstrap switches `current` to the new release before the bundle is verified whole,
loaded or given a rollback point.** PR `deploy/bootstrap.sh` (the kept-tree branch), then
`tools/trialbox/update.py:730-746` and `tools/host_tree.py:313-334, 400-428`. State: a running box from N-1; the
stick's one command. The updater then records "previous = N", so a failed update rolls images and databases back to
N-1 and the tree "back" to N, and says the box is back on the release before. Image tags are constant, so the mixed
stack starts. Any stop between the switch and the end of the load (an early check, a refused bundle, a signal, a
power cut) leaves the same mix with no marker, while the timers of N-1 run N's code. Reproduced at the level of the
host-tree record; not end to end. Covered: the pull request's upgrade test uses installers that load nothing.
Direction: make the signed tree available without switching, and leave the switch to the update path.

**LR-19. No CI job or rehearsal updates or rolls back an installed compose box.**
`tools/rehearse_box/rehearse.sh:360-389` (no update step); `tools/update_drill.py:183-196` (an in-process box);
`tools/trialbox/update.py:1772` (`ComposeBox`, driven on a real engine only by an install's first load). A change to
the dump roles, the image load, the restart or the space check passes every check and first fails on the walk box:
H-121 and the passphrase gap are this. Read only. Direction: `update`, `rollback` and `update-again` phases in
`tools/rehearse_box/box.sh` with a second bundle.

**LR-20. Nothing starts from an older release, so "the installed code runs" faults are invisible by construction.**
`tools/rehearse_box/rehearse.sh:196-201, 217`. There is no tag, one version, and release number 1 everywhere, so
"N-1" cannot even be resolved today (LR-69). H-123 and H-124 appear nowhere in the tree. #1455 has the only fixture
of an older release, one option parser at unit level. Read only. Direction: the nightly matrix at the end of this
page.

### Medium

**LR-21. `deploy/box-install.sh <bundle>` run again on a set-up box rewrites the site's host baseline and then waits
for ever.** `deploy/box-install.sh:329, 334, 493-496`; `tools/box/plan.py:626-634`. Before the bundle is verified,
`deploy/site/hardening.conf` is replaced by the provisional one (SSH off, no IT ranges), the answers lose the
owner's host name, the applied mark goes; the installer then applies that baseline and polls for answers the console
will never take. After #1455 this is the upgrade by stick. Reproduced with the test's harness. Covered: only the
`--firstrun` re-run. Direction: on a box with the mark or with users, keep the site's files.

**LR-22. H-110 is not closed by #1455 for the media path; on master a tree cut by power "installs" with exit 0.**
`deploy/box-prepare.sh:95-96` keeps any tree and tells the operator to run that tree's installer with the new
media: the old code runs, as in H-110, and #1455 does not change it. Master `deploy/bootstrap.sh:95-96, 128-131`: a
kept tree whose `deploy/install.sh` is empty after a power cut makes the bootstrap exit 0 with nothing installed,
and any other bytes there run as root. Master case reproduced; #1455 repairs it. Direction: one shared "bring the
signed tree in" step.

**LR-23. There is no uninstall, and removing the folder as the runbook says leaves units that stop Docker at the
next boot.** `deploy/systemd/trialbox-egress.service:21` (required by `docker.service`);
`docs/runbook/20-close-out-and-decommissioning.md:100-102`. On a shared host, after `/opt/trialbox` is removed the
egress unit fails and the engine, which requires it, does not start: every other system there is down. Nothing
removes the units, timers, cron files, the `trialbox` link, the firewall table, the TPM credential or the images.
Read only, not run under systemd. Direction: an uninstall, or a runbook list, that removes the units first.

**LR-24. The decommissioning plan and the "empty a rehearsal box" list miss stores.**
`tools/trialbox/decommission.py:89-127`; `docs/runbook/16-box-install-rehearsal.md:152-156`. The plan lists the
base file's volumes under one fixed project name. Not listed: the identity overlay's volumes (accounts, the internal
CA's key), `deploy/settings.yaml`, `deploy/site/`, `deploy/updates/` (rollback points with dumps), the pgBackRest
repository, the TPM credential, root's first-sign-in files. Runbook 16's list leaves the rehearsal marks and the
kept tree, so the site's install starts from the rehearsal's tree. Reproduced for the plan. Direction: read the
volumes from every compose file and the project's real name.

**LR-25. A lost or rewritten `deploy/.env`, or a half-initialised database volume, is found only as a failed start
and never repaired.** `tools/settings_wizard.py:931-959`; `deploy/install.sh:842-866, 886-905`. Three states, read
only: a cut between the wizard's two writes loses its answers and a VALIDATION box goes on with the example's
values; removing the settings file to change an answer makes new database passwords for an existing volume, so the
database refuses its own services; a power cut during the database's first start leaves a volume whose init scripts
never finish, and every re-run fails the same way. Direction: merge into an existing `.env`; never make a new
database password while the volume exists; a first-start mark.

**LR-26. A console-started update unpacks the new host tree inside the old release.**
`tools/trialbox/ops.py:49, 653`; `tools/trialbox/__main__.py:177`; `tools/apply_update.sh:55, 284-285`;
`tools/trialbox/update.py:2050, 2444`. The runner resolves its own file through `current`, so its root is
`releases/<old>`; the new tree lands in `releases/<old>/releases/<new>` and a second `current` appears inside the
old release, while the real `current` still names the old one. Each later console update nests deeper. Reproduced at
the path level, not through the real runner. `tests/console/test_ops_pages.py` pins the argument and so holds the
fault. **H-124 makes this the default path** if it runs the updater from `releases/<new>`. Direction: never derive
the site's deploy folder from a resolved release path.

**LR-27. A KILL or power cut inside the host-tree switch: `rollback` leaves dangling links.**
`tools/trialbox/update.py:736-744`; `tools/host_tree.py:349-391, 400-428`. The record on disk holds no list of what
was moved, so the recovery cannot undo it; on an install made by copy, `tools` and the compose file stay links to a
removed `current`, and `tools/apply_update.sh` itself is gone. Reproduced with the real module. #1461 fixed a signal
there, not a kill. Direction: save the record at each move.

**LR-28. One updater process holds modules of both releases.**
`tools/trialbox/update.py:1895, 2198, 2090, 2145`; `tools/trialbox/launch.py:42-44, 107-112`. Modules first
imported after the switch come from the new tree while `tb_common` stays the old one. A new module that calls
something an old in-memory module lacks stops every update from that release, and no new bundle can mend it.
Mechanism reproduced; no failing pair found today. Belongs in H-124. Direction: one resolved release folder for a
process's whole life.

**LR-29. Nothing ever removes the rollback image tags or old release folders.**
`tools/trialbox/update.py:1719-1721, 1498-1510`; `docs/runbook/04-disk-full.md:17`. Every update keeps every
replaced image under a `rollback-<bundle>` tag for ever; the runbook's `docker image prune` removes untagged images
only. After some updates the space check refuses the next one, while the audit event says the rollback point was
removed. Reproduced on a stand-in box. Direction: remove this bundle's tags after a good update.

**LR-30. A service a release adds or drops keeps running across an update and a rollback.**
`tools/trialbox/update.py:1930, 2284, 2415, 2441` (no orphan removal; the service list is the running updater's).
A rollback leaves a service only the new release has running against the restored database and says every service
is healthy. Its first command stops the old list on the new compose files: if the new release dropped one, the
rollback fails at its first command on every retry. Read only; no test changes the service list between releases.
Direction: stop by what runs in the project.

**LR-31. The update takes none of the box's other locks.**
`tools/trialbox/update.py:1211`; `tools/trialbox/ops.py:68`; `tools/trialbox/watchdog.py:155`. A quiet-hour update
starts fifteen minutes after the nightly backup and both can run at once; the watchdog may restart a slow service
inside the update's health wait; a restore and an update can run together. Read only. Direction: the update holds
the backup lock and the watchdog's maintenance flag.

**LR-32. "nothing was changed" is said while the services are stopped.**
`tools/trialbox/update.py:1264-1268, 1282-1286, 1485-1496, 1941-1943`. When the backup fails and the services it
stopped cannot be started again, the operator's line is still "backup failed, nothing was changed". Reproduced on a
stand-in box. Direction: say the services are down and name the command.

**LR-33. A stop of the console's update unit kills the rollback after 90 seconds.**
`deploy/systemd/trialbox-ops.service` (no kill mode, no stop limit); `tools/trialbox/procgroup.py:17`. #1472 covers
the runner's own time limit; a `systemctl stop`, a restart or a shutdown signals every process of the unit at once
and kills them after the default limit, mid-rollback. Read only. H-114b is not closed for this case. Direction: a
mixed kill mode and a stop limit sized like the update's.

**LR-34. The key check before an update is skipped silently when the secrets folder is not at one fixed path.**
`tools/apply_update.sh:184-188`; `tools/keys.py:66, 568-570`. A data root elsewhere, another project name or a
non-root caller skips it; the update then restarts services that cannot open their keys and rolls back half way,
the case the check exists for. Read only. Direction: ask the engine; say when it was not checked.

**LR-35. Files a rollback depends on are not synced before the first change.**
`tools/trialbox/update.py:780-782` (the dumps' key), `:519`, `:547`; `tools/image_pins.py:126-136`. A power cut
within seconds can leave a rollback that cannot open its dumps or that puts back a short weight file; it then fails
on every retry (LR-12). `deploy/.env` is rewritten during the restart and is in no rollback point. Read only.

**LR-36. SIGTERM and SIGHUP are dropped for most of a restore; the host says the box is put back and the restore
then replaces the data.** `tools/trialbox/box_restore.py:308-314` (no init process), `:604`;
`tools/trialbox/backup.py:2451` (handlers only from the first change). The restore is process 1 of its container,
so a signal with the default action is not delivered during the unpack, the check and the kept copy. Reproduced for
the process-1 rule in a private process namespace. Direction: install the handlers at the top, or run with an init.

**LR-37. Every container end that is not a known error is read as "NOT as it was; do not start the services".**
`tools/trialbox/box_restore.py:435, 461-465`; `tools/trialbox/__main__.py:752-756`. A backup image that is not on
the box, an image older than the host tree, a full disk during the unpack, or Ctrl-C before the first change: the
box is left stopped though nothing changed. Host half reproduced. H126-05 names one of these cases. Direction: the
container prints a state for every end.

**LR-38. A power cut or KILL inside the restore's window leaves no durable mark; the boot starts every service on
the half-restored box.** `tools/trialbox/backup.py:464-480` (the schema drop commits before the load starts);
`deploy/systemd/trialbox.service:19`; `tools/trialbox/box_restore.py:362-365`. The trial database is empty, the
hold flag (a row of it) is gone; services make their schemas again and can report healthy; the nightly can record a
good backup of it. The pre-restore dumps survive only in a folder the next restore deletes first. Read only; the
power-cut page says "Drill: none". Direction: a marker before the first change that the boot guard, the doctor and
the nightly read.

**LR-39. Restoring a backup taken by an older release does not run this release's database steps.**
`tools/trialbox/backup.py:2453-2501`; `tools/trialbox/box_restore.py:222-227`, against
`tools/trialbox/update.py:2277-2284`. Update on Monday, restore Sunday's backup on Wednesday: the schemas no service
owns are never migrated, and the others migrate under a fixed 600-second wait. Read only. The "previous format" test
writes the old format with today's code. Direction: run the database step before the start.

**LR-40. Restore onto a reinstalled or replaced host: the secrets come back under the old KEK, the host holds the
new one, and the page's order cannot work.** `tools/trialbox/backup.py:100-110`; `libs/tb_common/kek.py:419-431`;
`tools/keys.py:433-459`; `docs/runbook/22-replacing-hardware.md` step 3. Nothing compares the backup's `kek.json`
with the host's KEK. Before the restore the old shares are refused against the new record; after it every boot
unseals the wrong KEK. The same holds on one box when the KEK was rotated since the backup. A TPM-backed old box
with no escrow set cannot be opened at all (LR-8). Read only; both pages say "Drill: none". Direction: compare
before replacing the secrets volume, and say what to unseal.

**LR-41. A setting that is not a number ends `backup-nightly` and `backup-status` with a traceback: no record, no
alert.** `tools/trialbox/backup_schedule.py:790-793` (`TB_BACKUP_KEEP`, `TB_BACKUP_MAX_AGE_HOURS`,
`TB_PGBACKREST_FULL_DAY`). Reproduced with `TB_BACKUP_KEEP=14 nights`. The restore reads the same function.

**LR-42. An interrupted restore drill leaves the decrypted backup and scratch databases behind.**
`tools/trialbox/restore_drill.py:186, 192, 200-241`. The work folder is in the caller's temporary folder, cleanup is
only in a `finally`, and no later drill, nightly or doctor looks for either. Read only.

**LR-43. The box rehearsal overwrites and then deletes the Docker host's `/run/trialbox/kek`.**
`tools/rehearse_box/rehearse.sh:303, 349`. On a machine that is also an installed box (the bench host), the
rehearsal's seal replaces the box's unsealed KEK and the teardown removes it. Read only. Direction: a KEK folder of
the rehearsal's own.

**LR-44. `DRY=1` in the caller's environment turns the seal into a dry run that the installer counts as sealed.**
`deploy/hardening/lib.sh:8`; `deploy/hardening/seal_keys.sh:190-196`; `deploy/install.sh:1369-1376`. Reproduced for
the script (exit 0, key still plain); that the installer then removes the passphrase file is read only.

**LR-45. The boot unseal unit is rendered once, at the first TPM seal, and no update can change it.**
`deploy/hardening/seal_keys.sh:210-216` is its only writer. A fix to the unit does not reach a box sealed by an
older release, and the unit keeps that day's install folder. More widely, an update never renews what the installer
writes outside the tree: units, timers, the cron file, the boot wait. Read only.

**LR-46. On #1466: an install over the unrecorded older layout goes ahead, and `remove` then says "removed" with
almost all of it left.** PR `tools/bench_ci/install.sh:131-137, 145-148, 183-186, 206, 295-356`. With a slot
running, the launcher and units are replaced and the install then dies, so old units start new code. With none, it
completes with a one-line record; `remove` exits 0 leaving the user, home, image, units, id range, scratch and
token. Reproduced with stand-ins, both cases. The ruling says remove the older install by hand first; nothing
enforces or detects it. Direction: refuse before any change when our things exist with no record.

**LR-47. On #1466: the minting token, or a copy, survives `remove` in three cases.**
PR `tools/bench_ci/install.sh:206, 217, 235-238, 319, 353`. An older install's token is never recorded; a token set
before the first install is not either; a KILL between the copy and the rename leaves `.token.XXXXXX`, and `remove`
now keeps the settings folder. The by-hand section does not name the token. Two cases reproduced.

**LR-48. Re-running the bench install after a change does not restart the proxy.**
`tools/bench_ci/install.sh:146-148` (PR `:191-193`). A tightened allow-list or a fixed proxy does not take effect
until the host reboots; `verify` passes. Master and #1466. Read only.

**LR-49. On #1466: a scratch setting that names the install's own folder hands root's code folder to the jobs'
user.** PR `tools/bench_ci/install.sh:142, 145, 158`. The new "we made it" rule skips the owner check; the units'
root steps import from that folder. Master refuses this. It needs a wrong value in a root-only file. Reproduced.

**LR-50. The rehearsal's "power loss" keeps the KEK and never runs the boot path.**
`tools/rehearse_box/rehearse.sh:303, 309-320`; `tools/rehearse_box/box.sh:628-642`. The host's `/run/trialbox` is
bound in, so the unseal after a cut is never run, and power is never cut inside a transition. Read only.

**LR-51. Lifecycle changes reach the train with their unit tests and the rehearsal both skipped.**
`tools/ci_tier.py:40-108, 148-151`. A card that changes only `deploy/bootstrap.sh` or `tools/update_status.py` gets
the fast tier (none of about 150 lifecycle test files) and no rehearsal, since neither file is on the rehearsal's
path list. The tier outcome was reproduced with the tool. For the integrator: lifecycle paths on the full tier.

**LR-52. The bench's rehearse-box job cannot run, and the bench gate refuses a scheduled run.**
`tools/bench_ci/runner.Dockerfile:11-17` (no Docker, no compose); `tools/bench_ci/gate.py:48`. Nothing of the
lifecycle has run on the bench host through CI. Read only.

**LR-53. The rehearsal's own health wait passes with services missing.**
`tools/rehearse_box/box.sh:140-149`: it needs 12 running containers and none unhealthy; the box has 17 services.
The rehearsal has the fault it should catch (H-126's shape). The function's logic was reproduced with a stand-in.

### Low

**LR-54. Small residues of an interrupted install.** `deploy/install.sh:948, 915` (a KILL between the two leaves no
`TB_ENV`; the re-run then takes PRODUCTION, the stricter side); `:207-216` (the heartbeat holds the lock up to a
minute after a KILL; #1455 fixes it); `tools/apply_update.sh:190` (a stage left in the temporary folder that
`clean` does not look for); `deploy/install.sh:1589` (a container removed by bare name);
`tools/trialbox/update.py:2889` (every `*.part` under the models folder). Read only.

**LR-55. The project cleanup takes the whole stack down for one failed container.**
`tools/trialbox/project_check.py:80-95, 125-132`; `deploy/install.sh:1336-1340`. By design (F-19); it knows the
update's and the watchdog's marks and none for a restore under way. Read only.

**LR-56. Caller variables the lifecycle commands obey.** Root's own; `sudo` drops them unless `-E`. Read only except
where said. Install: `DOCKER_HOST` and `DOCKER_CONTEXT` (never cleared), `TB_SECRETS_HOST_DIR`, `TB_BOX`,
`TB_BOX_DEFER_SEAL`, `TB_IMAGE`, `TB_INSTALL_PULL`, `TMPDIR`, `PYTHONPATH`, and test stand-ins a real install
honours (`TB_TIER_TEST_ARCH`, `TB_TEST_MEM_KIB`, `TB_HOST_ROOT`, `TB_BOOTSTRAP_ROOT`). Update:
`TB_UPDATE_BACKUP_CMD` replaces the pre-update backup with any command and no skip is audited, on PRODUCTION too
(reproduced); `TB_COMPOSE`, `TB_DOCKER`, `TB_UPDATE_TARGET`, `TB_PY_IMAGE`; `status`, `rollback` and `clean` do not
read the box's settings as the update does. Backup: `TB_BACKUP_PUBKEY` seals the night's backup to another key and
records it good; `TB_BACKUP_KEEP`, `TB_BACKUP_OFFBOX`. Keys: `TB_KEK_FILE`, `TB_SECRETS_DIR`, `TB_KMS_URL`. Places:
`tools/trialbox/update.py:1782-1785, 1845, 1937-1938`; `tools/trialbox/backup_schedule.py:782-783`;
`deploy/hardening/lib.sh:7`. Direction: H-100's rule (the box's file decides) for every lifecycle command, and test
seams only under a test mark.

**LR-57. Smaller points of the update.** `tools/trialbox/update.py:633` (the image load is in the updater's own
process group and not recorded as running); `tools/apply_update.sh` says "as root" and never checks. Read only.

**LR-58. Three locks that do not know each other.** `tools/trialbox/update.py:1915-1944`;
`tools/trialbox/backup_schedule.py:186-187`; `tools/trialbox/backup.py:1587-1588`. The pre-update backup and the
nightly each remove every `.part` of the site on a target, the other's too. Read only.

**LR-59. The backup container is started without `--pull never`, and one password is not quoted.**
`tools/trialbox/update.py:1964, 1989`. A root container with every volume is started from whatever a pull gives when
the tag is gone; a database password with `@` or `/` breaks the pre-update backup. Fixed names (`trialbox-net`,
`trialbox_<volume>`) also break both under another project name. Read only.

**LR-60. The restore's space check undercounts, and what a restore sets aside is never cleaned or named.**
`tools/trialbox/box_restore.py:501-502`. `docs/runbook/04-disk-full.md` does not name the asides under the volume
folders. Read only.

**LR-61. The nightly has no SIGTERM or SIGHUP handler; two records are not synced.**
`tools/trialbox/backup_schedule.py:1263-1318, 252-258`; `tools/trialbox/backup.py:1282-1286`. With the pause
setting, a stopped nightly leaves the services paused, which the watchdog leaves alone by design. A killed restic
leaves its lock; nothing runs an unlock (not verified). Read only.

**LR-62. A box from before H-96 with the passphrase in `deploy/.env` stops opening itself after the update.**
`deploy/docker-compose.secrets.yml:47-49, 94-101`; `libs/tb_common/kek.py:435-442`;
`tools/trialbox/box_restore.py:259` still forwards the variable. Nothing in the update or the doctor names the line.
Read only.

**LR-63. Key leftovers and unverified commits.** A share-backed `init` cut short leaves a stale share set the re-run
is refused on (`deploy/hardening/seal_keys.sh:223`); `rotate-kek` does not open the staged files before its commit
(`tools/keys.py:775-781`); `tools/trialbox/svc_secrets.py:393-406, 433-436` changes the database passwords before
`deploy/.env` is written. Read only.

**LR-64. The bench `remove` stops dead when `userdel` fails, with no summary.**
`tools/bench_ci/install.sh:254-258` (PR `:324-328`). Reproduced with a failing stand-in; a second run finishes.

**LR-65. The bench image step's build folder is left on any failure or signal.**
`tools/bench_ci/install.sh:128-129` (PR `:167-170`). Reproduced.

**LR-66. On #1466: `remove` takes the engine and the scratch path from today's settings, not from the record.**
PR `tools/bench_ci/install.sh:298, 306-318, 354`. With unreadable or changed settings the scratch folder stays,
owned by an id that no longer exists, and "removed from this host" is still printed. One case reproduced.

**LR-67. Bench leftovers no version of `remove` looks at.** The units' drop-in folders (the real host has one
each), `/run/tb-bench-ci`, a `.made.XXXXXX` file after a KILL, the host test's logs, the image each rebuild
replaces. Read only except the record file.

**LR-68. Key lifecycle beyond the passphrase seal has no end-to-end run.** The TPM seal and boot unseal,
`rotate-kek`, `rotate`, the file and KMS back ends: unit tests with a stand-in only
(`tests/unit/test_host_baseline.py:271-273`). Read only.

**LR-69. "N-1" has no mechanical meaning.** No tag, one version, release number 1 in every rehearsal
(`tools/rehearse_box/rehearse.sh:197`). Direction: a ledger of the bundles handed to a real box.

**LR-70. Fifteen rows of the matrix have no test, or a part with no test, and no fault was shown in them.** Ten
are marked `GAP (LR-70)` in the matrix; five more (three covered in part, two covered only on a pull request) name
LR-70 in their note: a PRODUCTION install end to end, the passphrase unseal on a re-run, the share-backed seal,
`rotate-kek` under INT and on the TPM and share back ends under a kill, a restore under KILL or a power cut, and the
bench runner's install and remove after a cut. They are listed so that the rehearsal plan covers them; none is a
claim of a defect.

## Known items: are they fully fixed?

| Item | State on master and in the open pull requests |
| --- | --- |
| H-124, the installed updater runs | Not fixed. Every step up to and including the host-tree switch, and the control flow after it, is the installed release's. See the next section. |
| The KEK passphrase and the update | Not fixed on master. The installed wrapper refuses a sealed KEK and the variable before any new code could run; and the unseal it needs leaves a file the services cannot read (LR-4). |
| H-121, #1469 | Master already reads each database as the right role; the pull request makes a failed read plain. Its red: a size above 0 reaches `Updater.space`, which stats the engine's volume folder (`tools/trialbox/update.py:958-962, 1190, 2030`), unreadable to a non-root user. LR-15 and LR-34 are the same assumption. |
| H-110, #1455 | Fixes the bootstrap's kept tree. Open after it: the media path (LR-22), the switch before the load (LR-18), the bundle re-run of the box installer (LR-21), the never-started install (LR-17). |
| H-126, #1470 | Fixes the re-run that started nothing and the count called "healthy". Open after it: LR-13, LR-36, LR-37. It adds LR-14. |
| H-114b, #1472 | Fixed for the runner's own limit; not for a stop of the unit (LR-33). |
| H-111, #1457 | Live on master (LR-5); the pull request was not read. Three states a signal handler alone does not close are listed there. |
| The bench runner, #1466 | Master's known faults are fixed only there. Open on its head: LR-46, LR-47, LR-49, LR-66. |

## What H-124 must cover, beyond the two known points

1. **The old wrapper is still the entry.** A box in the field runs its installed `tools/apply_update.sh`: it refuses
   unknown options, runs its own key check and its own verifier. New options cannot reach a new updater through it.
   H-124 needs a stated bridge for boxes installed before it, the bench box included.
2. **The installed verifier stays the gate.** A manifest field or payload kind the N-1 or N-2 verifier does not know
   is refused for ever. A bundle of today must be shown to verify under those verifiers, and be verified again by
   the new one before anything changes.
3. **Where the new code runs from.** Unpacked and checked before it runs, and run from `releases/<new>` before
   `current` moves: exactly the layout of LR-26, where the root and the default deploy folder resolve into the
   release and the host-tree step nests.
4. **One tree per process** (LR-28), and the tree a process runs from must not be removed under it: the host-tree
   restore removes a fresh `releases/<new>` in the middle of the rollback (`tools/host_tree.py:427-428`).
5. **Recovery runs the code that wrote the record.** Today `rollback` is run by whichever tree `current` names. The
   marker should name the tree that recovers it.
6. **New updater, old box.** The new preflight, backup and rollback point run against the old images, the old
   database roles and old or missing records.
7. **Rollback by new code onto an old tree** falls back to in-process steps when the old tree lacks them
   (`tools/trialbox/update.py:2231-2235, 2271-2274`): those would be the new release's.
8. **The first load and the console's path** need the same treatment as the shell path, and the shell's signal trap
   has to hold across the hand-over.
9. **The unseal's owner** (LR-4), or the passphrase options end at services that cannot read the KEK.
10. **A test from N-1 and N-2 with those releases' real trees.** No test today runs two different trees.

## The matrix: transition, starting state, interruption

One row is one cell, or a group of cells that share one answer. "Covered by" names the test, opened and read; a note
says when it is text-only, a stand-in, or covers the cell in part. A gap names its finding. `R` before a file and
line is a step of the box rehearsal; `PR` or `pr/<n>` means the test exists only on that open pull request, so the
cell is a gap on master. Counts: 238 cells, 115 covered on master (5 of them in part), 16 covered only on a pull
request, 106 gaps, 1 not applicable.

The counting rule, by the start of the "Covered by, or gap" cell: `GAP` is a gap, also when a pull request is named
after it; `PR`, `pr/<n>` or `master: GAP` followed by a pull request's test is "only on a pull request", also when a
text-only test on master is named after it; `n/a` is not applicable; anything else, `partly` included, is covered.

### Install, bootstrap, uninstall

| Transition | Starting state | Interruption | Covered by, or gap | Note |
| --- | --- | --- | --- | --- |
| bootstrap, fresh tree | fresh | none | `tests/unit/test_install_bootstrap.py::test_it_unpacks_the_signed_host_tree_places_the_key_and_runs_the_installer` | stub installer |
| bootstrap, fresh tree | fresh | INT/TERM, HUP, KILL, power cut | GAP (LR-22) | no test stops the unpack |
| bootstrap, kept tree, same release | prior run | none | `tests/unit/test_install_bootstrap.py::test_a_second_run_keeps_the_tree_and_runs_the_installer_again` | stub |
| bootstrap, kept tree | N-1 | none | master: GAP (H-110; LR-20). pr/1455: `tests/unit/test_bootstrap_upgrade_h110.py::test_a_box_from_the_release_before_is_reinstalled_by_the_new_bootstrap` | stub installers, no load, no running stack: LR-18 not reached |
| bootstrap, kept tree | N-2 | none | GAP (LR-18) |  |
| bootstrap, kept tree, running box, then update | N-1 | none / any | GAP (LR-18) |  |
| bootstrap, kept tree | prior interrupted op (empty or partial tree) | power cut | master: GAP (LR-22); pr/1455: `tests/unit/test_ocr1455_kept_code.py` (file) | not run by me |
| launcher (`install` on the stick) | fresh | none | `tests/unit/test_hs1_one_command.py::test_a_run_with_only_the_sticks_path_reaches_the_plan` | stub |
| box-prepare (media) | fresh | none | `tests/unit/test_linux_media.py::test_prepare_installs_from_the_media` | stub dpkg, docker |
| box-prepare (media), kept tree | same release | none | `tests/unit/test_linux_media.py::test_prepare_again_keeps_the_host_tree` |  |
| box-prepare (media), kept tree | N-1, N-2 | none | GAP (LR-22) | not in #1455 |
| install.sh | fresh, PoC (VALIDATION rehearsal box) | none | rehearsal: `.github/workflows/trialbox-rehearse-box.yml` job "Box rehearsal (site / validation)", `tools/rehearse_box/box.sh` (first install, `:300`) | real docker in a container; stand-in models |
| install.sh | fresh, PRODUCTION | none | GAP (LR-70) | only stub harness tests, e.g. `tests/unit/test_install_refuses_unsafe_folders_10k4.py::test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor` |
| install.sh | fresh | INT/TERM, HUP | GAP (LR-5, LR-25, LR-54) | pr/1455 adds ticker tests only (`tests/unit/test_ocr1455_ticker_signals.py`) |
| install.sh | fresh | KILL | partly: `tests/unit/test_load_from_the_stick_h95.py::test_rereview_a_load_killed_before_its_undo_is_undone_by_the_rollback_and_the_next_run`, `::test_review_f3_a_part_left_by_a_killed_load_is_removed` | the load step only; every other step GAP (LR-70) |
| install.sh | fresh | power cut | GAP (LR-5, LR-22, LR-25) | the rehearsal's `restart` step cuts power on a finished box only |
| install.sh re-run, same bundle | prior finished install | none | rehearsal validation variant, `tools/rehearse_box/box.sh:328-345`; `tests/unit/test_install_rerun.py::test_apply_update_dry_run_passes_the_installed_bundle_again` (verifier only) |  |
| install.sh re-run, same bundle | prior interrupted op (failed containers) | none | `tests/unit/test_install_cleanup_is_fail_closed.py::test_install_cleanup_removes_only_this_installs_unhealthy_project` and the file's other tests | stand-in docker |
| install.sh re-run, newer bundle | prior interrupted op (loaded, never started) | none | GAP (LR-17) |  |
| install.sh re-run on a live box | N-1 (update through install.sh) | none | GAP (LR-20) | `tests/unit/test_host_tree.py::test_drill_a_compose_variable_change_takes_effect_and_rolls_back` covers the update path below it |
| install.sh, two at once | any | none | `tests/unit/test_install_faults_review_two.py::test_a_second_installer_while_one_runs_refuses_and_changes_nothing` |  |
| install.sh re-run | stale lock after KILL | KILL | GAP on master (LR-54); pr/1455 closes fd 9 |  |
| seal, KEK TPM | fresh | none | `tests/unit/test_seal_keys_order.py::test_the_tpm_path_seals_then_wraps`, `tests/unit/test_host_baseline.py::test_seal_keys_wraps_the_plain_keys_under_a_tpm_sealed_kek` | stand-in systemd-creds; no real TPM anywhere |
| seal, KEK TPM | fresh or plain keys with data | INT/TERM, HUP, KILL, power cut, failed wrap | GAP (LR-5) | `test_a_failed_seal_changes_nothing` covers a failing systemd-creds only |
| seal, KEK passphrase | fresh | none | `tests/unit/test_seal_keys_order.py::test_the_passphrase_path_without_a_hardening_conf`; rehearsal `box.sh:300` |  |
| seal, KEK passphrase | prior interrupted op / restart | none | GAP (LR-70) | the `:172-174` unseal-on-re-run branch has no test |
| seal, KEK file | - | - | not an install back end by itself (the TPM path's inner form) |  |
| box-install.sh | fresh | none | `tests/console/test_box_install_rehearsal.py::test_a_box_installs_from_the_installer_with_only_the_wizards_answers`, `::test_a_box_installs_unattended_from_the_owners_answers_file` | install stub |
| box-install.sh --firstrun | applied, window closed | none | same first test (its second half) |  |
| box-install.sh wait | fresh | INT/TERM/HUP | `tests/unit/test_first_run_code_h97.py::test_a_first_run_stopped_while_it_waits_leaves_no_code_file` | KILL, power cut: GAP (LR-70) |
| box-install.sh, bundle run again | set-up box (same or N-1) | none | GAP (LR-21) | `::test_a_new_install_removes_the_applied_mark` is text-only |
| poc.sh up | fresh, PoC | none | `tests/unit/test_poc_gpu.py::test_a_first_run_makes_its_env_file`, `tests/unit/test_poc_db_image.py::*`, `tests/unit/test_poc_real_embedder.py::*` | stand-in docker |
| poc.sh up / reset / down | installed site box | none | GAP (LR-2) |  |
| uninstall / decommission plan | any | none | `tests/unit/test_runbook_20_decommission.py::test_runbook_20_decommission` | plan and audit steps in process; no removal |
| uninstall by hand (§20 shared host, §16 empty) | PRODUCTION, PoC | none | GAP (LR-23, LR-24) |  |
| any install step as non-root | fresh | none | unit tests run non-root in CI with `TB_BOOTSTRAP_NO_ROOT`, `TB_BOX_NO_ROOT`; the rehearsal runs as root | the root-only branches (units, cron, seal, baseline) run only in the rehearsal |

### Update, rollback, recover

| Transition | Starting state | Interruption | Covered by, or gap | Note |
| --- | --- | --- | --- | --- |
| update, from the shell | fresh (first load) | none | `tests/unit/test_host_tree.py::test_drill_a_compose_variable_change_takes_effect_and_rolls_back`; `tests/unit/test_update_path.py::test_first_install_only_loads_and_defers_the_audit`; rehearsal `tools/rehearse_box` install | the rehearsal covers the first load only |
| update, from the shell | fresh | KILL | `tests/unit/test_load_from_the_stick_h95.py::test_rereview_a_load_killed_before_its_undo_is_undone_by_the_rollback_and_the_next_run` | stand-in engine; scope fault LR-11 |
| update, from the shell | N (same tree) | none | `tests/unit/test_update_path.py::test_a_good_update_backs_up_first_then_applies_migrates_checks_and_audits`, `::test_compose_box_commands_in_order`; `tools/update_drill.py` case 3 (`trialbox-e2e.yml`, `update-drill`) | stand-in or in-process box |
| update, from the shell | N-1 | none | GAP (H-124, LR-28) | `tests/unit/test_load_from_the_stick_h95.py::test_review_f6_a_box_installed_before_h95_takes_its_second_software_pack` and `tests/unit/test_update_dbup.py::test_a_tree_from_before_the_command_gets_the_two_commands_it_always_got` fake an old record or tree with today's code |
| update, from the shell | N-2 | none | GAP (H-124; LR-20) |  |
| update, from the shell | N-1 / N-2 | any | GAP (LR-20) | H-123 is the card; nothing runs two trees |
| update, from the shell | PoC | none | `tests/unit/test_update_poc_box_h99.py::test_h99_a_poc_box_without_a_backup_key_updates_and_lists_it` | stand-in |
| update, from the shell | PRODUCTION | none | `tests/unit/test_update_poc_box_h99.py::test_h99_production_with_the_key_still_backs_up_first`; `tests/unit/test_no_backup_needs_a_reason.py::test_the_shell_entry_refuses_no_backup_without_a_reason_on_a_production_box` |  |
| update, from the shell | KEK passphrase, sealed | none | `tests/unit/test_kek.py::test_apply_update_is_refused_before_anything_when_the_kek_is_locked` | the refusal only; an update of a passphrase box: GAP (H-124; LR-19) |
| update, from the shell | KEK TPM | none | GAP (LR-19) | not looked for beyond `tests/unit/test_kek.py` |
| update, from the shell | KEK file | none | GAP (LR-19) |  |
| update, from the shell | KEK, secrets folder off the fixed path | none | GAP (LR-34) |  |
| update, from the shell | prior interrupted update | none | `tests/unit/test_update_safety.py::test_the_shell_entry_refuses_while_the_marker_exists_and_offers_status`, `::test_the_marker_refuses_a_second_update_and_status_reports_it` |  |
| update, from the shell | prior failed rollback, then restore | none | GAP (LR-12) |  |
| update, before the update path | N | INT/TERM/HUP | `tests/unit/test_update_signals_h114.py::test_s1_a_signal_before_the_update_path_ends_the_script_and_changes_nothing` | real script, stand-in tools |
| update, at each step | N | INT/TERM | `tests/unit/test_update_signals_h114.py::test_b1_a_signal_at_each_step_boundary_leaves_the_box_on_one_release`; `tests/unit/test_update_safety.py::test_ctrl_c_during_apply_rolls_back` | stand-in box |
| update, at each step | N | HUP | `tests/unit/test_update_signals_h114.py::test_h1_a_hangup_whose_terminal_is_gone_still_rolls_back`, `::test_1461_4_a_hangup_the_caller_ignores_never_stops_the_update` |  |
| update, in the host-tree switch | copied install | INT/TERM/HUP | `tests/unit/test_update_signals_h114.py::test_1461_1_a_signal_inside_the_host_tree_switch_is_put_back_whole` | real `host_tree` |
| update, in the host-tree switch | copied install / N | KILL, power cut | GAP (LR-27) |  |
| update, at each step | N | KILL | `tools/update_drill.py` case 7 (step entry only, in-process box); `tests/unit/test_host_tree.py::test_a_crash_after_the_switch_is_rolled_back_from_the_marker`; `tests/unit/test_update_safety.py::test_a_kill_right_after_the_marker_rolls_back_to_the_recorded_state` | never inside a step of a compose box |
| update, after the check | N | KILL | drill case 7 at `refdata` / `finish` | asserts the full rollback: LR-10 |
| update, any step | N | power cut, then boot | GAP (LR-9) | nothing boots a box with a marker |
| update, from the shell | N, services list changed | none | GAP (LR-30) |  |
| update, from the shell | N, engine shared | failed load | GAP (LR-11) |  |
| update, from the shell | N, many updates | none | GAP (LR-29) |  |
| update, from the shell | N, nightly backup or watchdog running | none | GAP (LR-31) |  |
| update, from the shell | N, non-root | none | GAP (LR-19) | #1469's red found one line |
| update, from the console | N | none | `tests/console/test_ops_pages.py::test_update_check_and_apply_ask_first_and_apply_is_refused_off_a_site_box`; `tests/unit/test_ops_update_in_the_quiet_hour.py::test_in_the_quiet_hour_with_no_job_running_it_runs` | stand-in runner: `apply_update.sh` is never run; LR-26 |
| update, from the console | N | time limit | `tests/unit/test_t695_update_stop_boot.py::test_a_limit_kills_the_whole_group_never_an_orphan_left`; #1472 `tests/unit/test_update_grace_h114b.py` | `procgroup` with a stand-in command |
| update, from the console | N | unit stopped, shutdown | GAP (LR-33) |  |
| update, from the console | N | runner restarted | `tests/unit/test_ops_update_in_the_quiet_hour.py::test_an_interrupted_quiet_update_is_never_run_again` | the request, not the box's state |
| rollback, automatic | N | none | `tests/unit/test_update_path.py::test_any_failure_after_the_rollback_point_rolls_back_and_is_audited`, `::test_compose_box_rolls_back_images_models_and_database`, `::test_in_process_box_migrates_and_rolls_back_the_database`; drill case 5 |  |
| rollback, automatic: database restore | N | none | `tests/unit/test_update_safety.py::test_the_rollback_restore_runs_a_real_dump_under_dash_and_a_failed_one_changes_nothing` | real PostgreSQL |
| rollback, automatic | N | INT/TERM/HUP | `tests/unit/test_update_signals_h114.py::test_i1_a_second_signal_never_abandons_the_update_s_rollback`, `::test_i2_two_signals_during_a_rollback_a_failure_started_are_both_ignored` |  |
| rollback, automatic | N | KILL | `tests/unit/test_update_signals_h114.py::test_1461_1_a_rollback_killed_after_a_stop_in_the_switch_is_finished_by_recover` | host tree only |
| rollback, automatic: failed | N | none | `tests/unit/test_update_path.py::test_a_failed_rollback_says_so`; `tests/unit/test_update_signals_h114.py::test_r1_a_rollback_cut_short_is_found_by_the_next_run_and_finished` |  |
| rollback, automatic: backup or point failed | N | none | `tests/unit/test_update_safety.py::test_rollback_restarts_stopped_services_when_the_rollback_point_fails` | a start that fails: GAP (LR-32) |
| rollback, automatic | N-1 / N-2 (rollback onto an older tree) | none | GAP (H-124; LR-20) |  |
| rollback, by command | prior interrupted update | none | drill case 7; `tests/unit/test_host_tree.py::test_a_crash_after_the_switch_is_rolled_back_from_the_marker` | run by the same tree, never by the new tree through the link |
| rollback, by command | prior interrupted update | INT/TERM | `tests/unit/test_update_signals_h114.py::test_r1_a_rollback_cut_short_is_found_by_the_next_run_and_finished` (signals in the recovery ignored) |  |
| rollback, by command | command of the killed run still alive | none | `tests/unit/test_update_signals_h114.py::test_1461_3_a_put_back_left_running_by_a_killed_updater_holds_the_recovery`, `::test_1461_6_a_record_holds_the_recovery_only_for_the_command_it_names` |  |
| rollback, by command | prior interrupted update | KILL, power cut | GAP (LR-19) | a recovery cut and run again is untested |
| rollback, by command | after `finished` | none | `tests/unit/test_update_safety.py::test_a_crash_after_finish_leaves_no_key_or_dump_and_rollback_only_cleans_up` |  |
| rollback, by command | caller's `COMPOSE_*` exported | none | GAP (LR-56) |  |

### Backup and restore

| Transition | Starting state | Interruption | Covered by, or gap | Note |
| --- | --- | --- | --- | --- |
| backup, manual (`backup.backup`) | fresh | none | `tests/unit/test_backup.py::test_round_trip_restores_rows_and_files` | real PostgreSQL, in process |
| backup, manual | fresh | INT/TERM | GAP (LR-61) | no test stops a backup part-way |
| backup, manual | fresh | KILL / power cut | GAP (LR-61) | `.part` and sidecar rules only by `tests/unit/test_backup_schedule.py::test_prune_touches_only_this_sites_files` |
| backup, manual | prior interrupted op | none | `tests/unit/test_backup_verifies_itself.py::test_a_backup_whose_manifest_is_wrong_about_a_file_is_refused_and_leaves_nothing` | a failed run leaves nothing; not a killed one |
| nightly | fresh | none | `tests/unit/test_backup_schedule.py::test_nightly_writes_records_and_audits_a_good_backup`; rehearsal `box.sh live-restore` (`backup-nightly --deploy deploy`) | rehearsal: real engine |
| nightly | PRODUCTION | none | `tests/unit/test_backup_schedule.py::test_in_production_a_box_with_only_local_targets_fails_and_stays_red` |  |
| nightly | PoC | none | `tests/unit/test_box_backup_step.py::test_on_a_poc_box_the_it_form_warns_lists_and_goes_on` | the install step, not a night |
| nightly | KEK passphrase | none | `tests/unit/test_nightly_restic.py::test_a_passphrase_kek_and_no_kek_are_not_covered`; rehearsal `restic-restore` (first part) |  |
| nightly | KEK TPM | none | `tests/unit/test_nightly_restic.py::test_a_tpm_kek_is_covered_only_with_its_current_escrow_set` | decision only; no TPM run |
| nightly | KEK file (shamir) | none | `tests/unit/test_nightly_restic.py::test_covered_makes_the_key_on_the_host_and_chooses_restic`; rehearsal `restic-restore` | throwaway shamir KEK |
| nightly | prior interrupted op | none | `tests/unit/test_backup_schedule.py::test_compose_nightly_takes_one_snapshot_per_database_and_removes_the_plaintext_dumps` (sweep of `.backup-stale`), `::test_a_stale_spool_never_refuses_a_good_backup`, `::test_one_nightly_run_at_a_time` |  |
| nightly | fresh | INT/TERM/HUP | GAP (LR-61) |  |
| nightly | fresh (pause mode) | KILL | part: `tests/unit/test_backup_without_pause.py::test_a_reused_pid_does_not_keep_the_flag_and_paused_services_are_printed` | the flag, not the paused services |
| nightly | fresh | power cut | GAP (LR-61) | no fsync of sidecar and record |
| nightly | N-1, N-2 | none | GAP (LR-20) | old cron form only: text check in `tests/unit/test_backup_schedule_timer.py`; no old box |
| nightly | bad setting | none | part: `tests/unit/test_backup_without_pause.py::test_a_bad_setting_fails_the_run_with_a_record`; GAP (LR-41) for the three `int()`/`float()` settings |  |
| pre-update backup | fresh | none | `tests/unit/test_backup_without_pause.py::test_the_update_paths_dumps_and_container_get_limits_from_size`, `tests/unit/test_backup.py::test_the_update_paths_full_dump_keeps_every_row` | stand-in engine |
| pre-update backup | PRODUCTION, `--no-backup` | none | `tests/unit/test_no_backup_needs_a_reason.py::test_the_python_entry_refuses_no_backup_without_a_reason_on_a_production_box` | `TB_UPDATE_BACKUP_CMD` bypass: GAP (LR-56) |
| pre-update backup | N-1, N-2 | any | GAP (LR-20) | no box of an older release anywhere |
| pre-update backup | beside a nightly | none | GAP (LR-58) |  |
| restore, in the container | fresh | none | `tests/unit/test_backup.py::test_round_trip_restores_rows_and_files`; `tests/platform/test_day2_db.py::test_backup_wipe_and_restore_through_the_job_commands` |  |
| restore, in the container | N-1 / N-2 file format | none | `tests/unit/test_backup.py::test_a_backup_in_a_previous_format_still_restores`, `tests/unit/test_backup_hard_links.py::test_a_backup_written_before_the_fix_is_still_restorable` | written by today's code |
| restore | N-1 / N-2 schema, then start | none | GAP (LR-39) |  |
| restore, in the container | fresh | INT/TERM in the window | `tests/unit/test_restore_from_the_host_h100.py::test_f2_a_restore_that_fails_after_its_first_change_puts_the_box_back_holds_and_audits`, `::test_r1_a_second_signal_during_the_put_back_never_abandons_it`; rehearsal `live-restore` (role step sends INT then TERM to PID 1) | rehearsal: real engine |
| restore, in the container | fresh | TERM/HUP before the window | GAP (LR-36) |  |
| restore, in the container | folder is a mount point | none | GAP (LR-1) |  |
| restore, on the host | fresh | none | `tests/unit/test_restore_from_the_host_h100.py::test_the_one_documented_command_restores_the_last_backup_from_a_bare_sudo`; rehearsal `live-restore` |  |
| restore, on the host | PoC | none | rehearsal `live-restore` | the rehearsal box is `TB_HOST_PROFILE=poc` |
| restore, on the host | PRODUCTION | none | part: `tests/unit/test_restore_roles.py::test_without_the_command_a_production_restore_is_not_complete` | no PRODUCTION host run |
| restore, on the host | KEK passphrase | none | rehearsal `live-restore` | same box, same KEK |
| restore, on the host | KEK TPM / KEK file, restic backup | none | GAP (LR-16) | fake restic only |
| restore, on the host | Docker root not the default | none | GAP (LR-15) |  |
| restore, on the host | fresh | INT/TERM (terminal alive) | `tests/unit/test_restore_from_the_host_h100.py::test_r2_two_signals_on_the_host_pass_one_on_and_wait_for_the_container`, `::test_f3_an_interrupt_while_the_container_runs_is_passed_on_and_waited_for`, `::test_r7_an_interrupt_while_the_services_start_says_the_state` | stand-in |
| restore, on the host | fresh | HUP (terminal gone) | GAP (LR-13) |  |
| restore, on the host | fresh | KILL | GAP (LR-13, LR-38) | `::test_r7_one_restore_at_a_time_and_a_killed_ones_folder_is_swept` pins the sweep itself |
| restore, on the host | fresh | power cut | GAP (LR-38) |  |
| restore, on the host | prior interrupted op | none | master: GAP (H-126); #1470: `tests/unit/test_restore_rerun_h126.py::test_a_rerun_after_a_signal_at_every_step_serves_the_site_or_says_it_does_not` and rehearsal `live-restore` (not run yet, the PR says) | stand-in compose that keeps state |
| restore, on the host | prior op left "do not start", re-run refused | none | GAP (LR-14, #1470 only) |  |
| restore, on the host | container ends without a state | none | GAP (LR-37) |  |
| restore onto a new or replaced host | fresh + old backup | none | part: `tests/unit/test_backup.py::test_restore_refuses_another_site_an_old_or_a_future_backup_before_touching_anything`, `tests/unit/test_backup.py::test_a_restore_without_the_pack_keeps_the_site_rows_and_says_it_is_not_done`; `tools/restore_drill.py` (`make restore-drill`, wipes volumes, keeps `deploy/`) | no second machine |
| restore onto a new host | KEK passphrase / TPM / file | none | GAP (LR-40) | runbook: "Drill: none" |
| restore, hold | prior interrupted op | none | `tests/unit/test_restore_hold.py::test_a_second_restore_never_removes_the_hold`, `::test_a_restore_that_stops_after_the_database_was_replaced_leaves_the_box_held` |  |
| restore, erasures | fresh | none | `tests/unit/test_erasure_reach_restore.py::test_the_restore_keeps_the_opt_out_and_the_next_tick_clears_the_stores` |  |
| restore drill | fresh | none | `tests/unit/test_restore_drill.py::test_a_drill_restores_into_scratch_compares_and_leaves_the_live_database_alone`, `::test_box_restore_with_the_installers_nocreatedb_owner` |  |
| restore drill | fresh | failure (exception) | `tests/unit/test_restore_drill.py::test_a_failure_part_way_still_drops_the_scratch_database_and_the_unpacked_files` |  |
| restore drill | fresh | TERM / HUP / KILL / power cut | GAP (LR-42) |  |
| restore drill | prior interrupted op | none | GAP (LR-42) | nothing sweeps |
| retention | fresh | none | `tests/unit/test_backup_without_pause.py::test_retention_never_prunes_before_the_new_file_is_checked`, `::test_the_size_rule_keeps_two_good_backups_and_says_so`, `tests/unit/test_backup_restic.py::test_a_failed_night_leaves_no_snapshot_and_keep_never_drops_a_needed_one` | by count it always keeps the newest with a sidecar |

### Key operations

| Transition | Starting state | Interruption | Covered by, or gap | Note |
| --- | --- | --- | --- | --- |
| seal at install | fresh, KEK TPM | none | `tests/unit/test_host_baseline.py::test_seal_keys_wraps_the_plain_keys_under_a_tpm_sealed_kek`, `tests/unit/test_seal_keys_order.py::test_the_tpm_path_seals_then_wraps` | real, stand-in `systemd-creds` |
| seal at install | fresh, KEK TPM | seal command fails | `tests/unit/test_seal_keys_order.py::test_a_failed_seal_changes_nothing` | real |
| seal at install | fresh, KEK TPM | INT/TERM | GAP (LR-5) | H-111, #1457 not read |
| seal at install | fresh, KEK TPM | HUP | GAP (LR-5) |  |
| seal at install | fresh, KEK TPM | KILL | GAP (LR-5) |  |
| seal at install | fresh, KEK TPM | power cut | GAP (LR-5) |  |
| seal at install | fresh, KEK passphrase | none | `tests/unit/test_seal_keys_order.py::test_the_passphrase_path_without_a_hardening_conf`; rehearsal step `install` (`tools/rehearse_box/box.sh:330-332`) | real |
| seal at install | fresh, KEK passphrase | INT/TERM/KILL/power cut | GAP (LR-63) | the re-run heals when the passphrase is given; untested |
| seal at install | fresh, KEK file (shamir record) | none | GAP (LR-70) | `seal_keys.sh`'s shamir branch has no test; `tests/unit/test_kek.py::test_init_writes_one_share_file_each_wraps_both_keys_and_prints_no_material` covers `init` only |
| seal at install | fresh | owner of the sealed files | `tests/unit/test_seal_keys_order.py::test_the_sealed_files_belong_to_the_services_user` | real, but `skipif` not root: never runs in CI |
| seal, second run | prior op done, KEK passphrase, KEK still unsealed | none | rehearsal step `reinstall` (validation variant; `box.sh:342`) | real |
| seal, second run | KEK passphrase, after a reboot | none | GAP (LR-4) | reproduced |
| seal, second run | KEK TPM, credential or unit missing | none | GAP (LR-5, LR-6) |  |
| seal | N-1 / N-2 box with data under plain keys | any | GAP (LR-5) |  |
| seal | `DRY` inherited | none | GAP (LR-44) |  |
| init | KEK exists | none | `tests/unit/test_seal_keys_order.py::test_keys_init_takes_a_kek_that_exists` | real |
| unseal at boot | KEK TPM | none | `tests/unit/test_seal_keys_order.py::test_the_boot_unseal_hands_the_kek_to_the_secrets_owner` | text-only (reads the unit file); `tests/unit/test_kek.py::test_a_systemd_credential_is_a_kek_source` is real for the library |
| unseal at boot | KEK TPM, after a PCR or firmware change, a board swap | none | GAP (LR-8) | needs a TPM |
| unseal by hand | KEK passphrase | none | `tests/unit/test_kek.py::test_passphrase_init_then_wrap_and_unseal` | real, same user reads it back |
| unseal by hand | KEK passphrase or shamir, services as another uid | none | GAP (LR-4) |  |
| unseal by hand | KEK shamir | none | `tests/unit/test_kek.py::test_unseal_refuses_a_reused_share_and_a_share_of_another_box` | real |
| unseal from escrow | KEK TPM, new board | none | `tests/unit/test_key_escrow.py::test_a_new_board_opens_the_kek_from_escrow_as_a_witnessed_event_then_rotates_onto_its_tpm` | real for the shares; nothing seals to a TPM (LR-6) |
| boot after power cut | KEK passphrase, KEK gone from tmpfs | power cut | GAP (LR-4) | rehearsal `power-cycle` keeps the Docker host's `/run/trialbox` |
| boot after power cut | N-2, passphrase in `deploy/.env` | power cut | `tests/unit/test_kek_env_refused_h97.py::test_load_kek_refuses_the_process_environment_and_keeps_the_start_path` | real for the library; no box-level test (LR-62) |
| rotate-kek | KEK passphrase | none | `tests/unit/test_kek_passphrase_file_h96.py::test_rotation_takes_the_old_and_the_new_passphrase_from_files_or_stdin` | real |
| rotate-kek | KEK passphrase | KILL / power cut at each rename | `tests/unit/test_rotate_kek_safety_h97.py::test_a_kill_at_any_step_leaves_keys_that_open_and_the_next_command_finishes_or_rolls_back` | real (`os._exit` at each `os.replace`); directory fsync loss is not modelled |
| rotate-kek | KEK passphrase | INT/TERM/HUP | GAP (LR-70) | the KILL test implies TERM and HUP; the INT rollback path (`keys.py:923-928`) has no test |
| rotate-kek | KEK passphrase, runtime KEK present, services as uid 10001 | none | GAP (LR-3) | every test reads as the writer |
| rotate-kek | KEK passphrase, PRODUCTION | none | `tests/unit/test_rotate_exposed_passphrase_h97.py::test_a_production_box_rotates_its_exposed_passphrase_and_the_rotation_is_audited` | real |
| rotate-kek | prior interrupted rotation | none | `tests/unit/test_rotate_kek_safety_h97.py::test_a_rotation_cut_short_is_a_custody_problem_until_finished` | real |
| rotate-kek | two at once | none | `tests/unit/test_rotate_kek_safety_h97.py::test_two_rotations_at_once_never_lose_a_key` | real |
| rotate-kek | KEK shamir | none | `tests/unit/test_kek.py::test_rotate_kek_rewraps_every_key_and_the_old_shares_stop_working` | real |
| rotate-kek | KEK TPM, sealed credential | none | GAP (LR-6) | the escrow test rotates with no credential in play |
| rotate-kek | KEK TPM / shamir | KILL / power cut | GAP (LR-70) | the kill test is passphrase only; `--kek-out` and share leftovers (LR-63) |
| rotate-kek | prior interrupted `rotate pid_map` | none | GAP (LR-7) | `tests/unit/test_sign_keys_kek.py::test_rotate_kek_waits_for_an_audit_key_rotation_cut_short` covers the audit key's name only |
| rotate pid_map | wrapped key | none | `tests/unit/test_kek.py::test_rotate_pid_map_reencrypts_every_row` | real |
| rotate pid_map | wrapped key | KILL / power cut | GAP (LR-7) |  |
| escrow-shares | KEK TPM | none | `tests/unit/test_key_escrow.py::test_escrow_shares_on_media_recorded_by_fingerprint_and_name_only` | real |
| escrow-shares | KEK TPM, PRODUCTION | none | `tests/unit/test_rotate_exposed_passphrase_h97.py::test_the_neighbouring_ceremonies_stay_refused_on_a_production_box` | real: it proves the refusal (LR-8) |
| ceremony record | each back end | none | `tests/unit/test_key_ceremony.py::test_a_shamir_record_names_one_custodian_per_share_with_fingerprints_and_no_material`, `::test_a_passphrase_box_gets_a_record_marked_not_a_site_ceremony` | real |
| backup-key ceremony | fresh / prior interrupted | none, cut short | `tests/unit/test_backup_key_ceremony.py` | not opened test by test |
| update pre-check | KEK locked (shamir) | none | `tests/unit/test_kek.py::test_apply_update_is_refused_before_anything_when_the_kek_is_locked` | real (`apply_update.sh --dry-run`) |
| update | KEK passphrase, from N-1 | none | GAP (LR-4) | the rehearsal has no update step at all |
| update | KEK TPM, from N-1 (older unit) | none | GAP (LR-45) |  |
| update pre-check | secrets folder not visible to the caller | none | GAP (LR-56) |  |
| restore | KEK rotated since the backup | none | GAP (LR-40) | rehearsal `restic-restore` uses a throwaway shamir KEK, same KEK both sides |
| restore to another host | KEK TPM | none | GAP (LR-6, LR-8) | runbook 22 says no drill exists |
| pre-start key steps | fresh / N-1 without the keys | none | `tests/unit/test_actor_key_prestart_step.py::test_the_command_makes_the_key_and_says_so_then_keeps_it`, `tests/unit/test_model_key.py::test_an_update_makes_a_missing_key_and_checks_the_servers` | real |
| service secrets rotate | prior interrupted | KILL | GAP (LR-63) |  |
| object store seal | KEK present / absent | none | `tests/unit/test_objstore_sealed.py::test_seal_objects_converts_older_plain_objects_and_is_idempotent`, `::test_sealing_needs_a_kek_and_the_object_key_is_never_plain` | real |
| compose secret reach | every file set | none | `tests/unit/test_compose_secret_reach.py::test_no_secret_reaches_a_service_off_its_list` | real render; allows the passphrase to two services (LR-62) |
| plain key owned by another uid | PRODUCTION | none | `tests/unit/test_ocr1455_key_owner.py::test_a_plain_site_key_another_user_owns_fails_the_host_check` (on `pr/1455` only) | plain keys only; not the wrapped files of LR-3 |
| rehearsal teardown | a host with its own unsealed KEK | none | GAP (LR-43) |  |

### Bench runner

| Transition | Starting state | Interruption | Covered by, or gap | Note |
| --- | --- | --- | --- | --- |
| install | fresh | none | PR `tests/unit/test_bench_ci_host_h105.py::test_the_install_ends_with_no_unbound_variable_after_the_image_step`, `::test_the_record_is_written_before_the_thing_is_made_and_whole`; master: text-only (`tests/unit/test_bench_ci_launcher_h105.py::test_the_units_run_as_the_unprivileged_user_from_roots_files`) | every step but the image step is a stand-in; the whole install runs only in `host_test.sh` on the host |
| install | fresh, missing packages | none | PR `tests/unit/test_bench_ci_host_h105.py::test_the_install_stops_before_any_change_without_the_networks_helpers` | run with a stand-in PATH |
| install | fresh, scratch slip (another owner's folder) | none | PR `::test_a_planted_folder_of_another_owner_survives_install_and_remove`, `::test_an_empty_folder_of_another_owner_is_not_taken_as_scratch`; master `tests/unit/test_bench_ci_review_h105.py::test_1448_27_the_scratch_check_refuses_a_folder_others_can_change` | run |
| install | fresh, scratch names install's own folder | none | GAP (LR-49) |  |
| install | N-1 (1fc6579e layout, no record) | none | GAP (LR-46) | only the runbook text is tested (`::test_the_runbook_says_how_to_remove_an_install_from_before_the_record`) |
| install | N-1 (PR layout with a record) | none | GAP (LR-48) | re-install idempotence and the proxy restart are not run anywhere |
| install | prior interrupted op (half-done install) | none | GAP (LR-70) | re-run after a cut is not run (LR-67) |
| install | fresh | INT/TERM | GAP (LR-65) |  |
| install | fresh | HUP | GAP (LR-65) |  |
| install | fresh | KILL | PR `::test_the_record_is_written_before_the_thing_is_made_and_whole` (a failing step, not a KILL) | partial: one kind (`dir` cni) |
| install | fresh | power cut | GAP (LR-70) | fsync order is read only |
| token | installed | none | `tests/unit/test_bench_ci_review_h105.py::test_m1448_20_without_a_signal_the_token_is_kept_root_only` | run |
| token | installed | INT/TERM/HUP | `tests/unit/test_bench_ci_review_h105.py::test_m1448_20_a_signal_in_the_token_step_ends_it`, PR `::test_1448_26_a_signal_says_whether_the_token_was_kept` | run, every line |
| token | installed | KILL / power cut | GAP (LR-47) |  |
| token | before install | none | GAP (LR-47) |  |
| verify | installed, no token | none | PR `tests/unit/test_bench_ci_host_h105.py::test_verify_without_a_token_says_not_run_for_the_token_and_the_slots` | run with stand-ins; master: text-only |
| verify | installed, token | none | PR `::test_verify_with_a_token_checks_the_token_and_the_slots` | stand-ins; the probe never runs in CI |
| remove | fresh install (recorded) | none | PR `::test_remove_takes_a_scratch_folder_install_recorded`, `::test_the_install_makes_the_cni_folder_and_remove_takes_it_away_if_empty`, `tests/unit/test_bench_ci_launcher_h105.py::test_removal_takes_away_everything_it_made_and_says_what_is_left_to_the_owner` | one recorded kind per test; user, id range, linger, units never together; master: text-only |
| remove | N-1 (no record) | none | PR `::test_remove_without_a_record_deletes_nothing_and_says_so` | run |
| remove | N-1 overlaid by a new install (partial record) | none | GAP (LR-46) |  |
| remove | recorded, settings unreadable or scratch renamed | none | GAP (LR-66) |  |
| remove | recorded, user still has processes | none | GAP (LR-64) |  |
| remove | prior interrupted op (cut install) | none | PR `::test_a_planted_folder_of_another_owner_survives_install_and_remove` (after a refused install) | a cut between record and make: GAP (scenario C here; LR-70) |
| remove | recorded | INT/TERM, HUP, KILL, power cut | GAP (LR-70) | re-run after an aborted remove is not run (LR-64) |
| host test | fresh | none | PR `::test_the_host_test_runs_install_verify_remove_and_counts_verifys_not_run_lines` | stand-in install.sh |
| host test | failed install | none | PR `::test_the_host_test_never_runs_remove_after_a_failed_install` | run |
| host test | fresh | INT/TERM | PR `::test_a_signal_ends_the_host_test_with_where_it_stopped_and_no_remove` | TERM only |
| host test | N-1 (old layout, no token) | none | GAP (LR-46) |  |
| slot start (mint/run/cleanup) | installed | none | `tests/unit/test_bench_ci_launcher_h105.py::test_the_root_mint_step_gives_the_jobs_user_one_jobs_configuration_and_never_the_token`, `::test_a_new_job_never_finds_an_earlier_jobs_files` | run, stand-in code host |
| slot start | prior interrupted op (planted link, leftover folder) | none | `tests/unit/test_bench_ci_review_h105.py::test_m1448_1_a_link_planted_at_the_slots_name_after_the_removal_is_not_followed`, `::test_m1448_22_the_scratch_root_as_a_link_is_refused` | run |
| slot stop | job running | TERM | `tests/unit/test_bench_ci_launcher_h105.py::test_a_unit_stop_stops_the_container`, `::test_a_stop_or_a_failure_takes_the_registration_and_the_scratch_folder_away` | run |
| slot | job running | KILL / power cut | GAP (LR-70) | `/run/tb-bench-ci` is lost: the registration is never removed (read only) |
| job reaches runner | fork pull request | none | `tests/unit/test_bench_ci_gate_h105.py::test_a_forks_pull_request_is_refused_before_anything_is_read`, `tests/unit/test_bench_ci_workflow_h105.py::test_no_other_trigger_reaches_the_bench_label` | the gate with stand-in variables; the real runner's hook order: GAP (H105-08, open; LR-70) |

### What the rehearsals and CI jobs run end to end

| Transition | Starting state | Interruption | Covered by, or gap | Note |
| --- | --- | --- | --- | --- |
| install | fresh, PoC, KEK passphrase | none | R `rehearse.sh:369`, `box.sh:278` | root, no systemd |
| install | PRODUCTION, KEK TPM | none | GAP (LR-68) | G only (paid) |
| install | fresh | INT/TERM/HUP/KILL/power cut | GAP (LR-50) |  |
| bootstrap | fresh (empty folder) | none | R `box.sh:221` | check-only installer |
| bootstrap over kept tree | N-1, N-2 | none | GAP (LR-20) | pr/1455: unit, same-release rehearsal step |
| reinstall same bundle | prior install, KEK passphrase | none | R `box.sh:327` (validation) |  |
| update | N-1, N-2, any KEK | none | GAP (LR-19, LR-20) |  |
| update | same release | KILL at each step | N `update_drill.py:202` | in-process box only |
| update | any | INT/TERM/HUP | GAP (LR-19) | unit: `test_update_signals_h114.py` |
| rollback / recover | prior interrupted update | none | GAP (LR-19) | in-process in N |
| backup | fresh box, passphrase | none | R `box.sh:777` |  |
| backup (restic) | shamir throwaway | none | R `box.sh:708` |  |
| restore | same box | INT+TERM in the data part | R `box.sh:803` |  |
| restore `--restart` | same box | none | R `box.sh:819` |  |
| restore `--restart` | prior interrupted restore | TERM after data part | pr/1470 only | GAP (LR-70) on master |
| restore | backup of N-1 | none | GAP (LR-20) |  |
| restore | any | KILL / power cut | GAP (LR-70) |  |
| key seal | passphrase | none | R (install) |  |
| key seal / unseal | TPM, file | none | GAP (LR-68) |  |
| rotate-kek | any | any | GAP (LR-68) |  |
| unseal after boot | passphrase, TPM | power cut | GAP (LR-50) |  |
| power cycle at rest | PoC passphrase | KILL | R `rehearse.sh:379` | KEK kept (LR-50), health weak (LR-53) |
| uninstall | any | any | n/a | no script |
| bench runner install/remove | fresh host | none | GAP (LR-52) | pr/1466 `host_test.sh`, by hand |

## The proposed nightly rehearsal: the lifecycle matrix

**Why a new rig.** A bench job is rootless, has no sudo, no systemd, no TPM and no Docker (LR-52), so it cannot run
the installer. The hosted rehearsal has no update step and one release (LR-19, LR-20). The plan below runs on the
bench host, costs no money, and needs the integrator's ruling first, since D-887 says the rehearsal has no schedule.

**Where.** A KVM guest on the bench host, CPU only, started by a root-owned timer on the host and never by a bench
job: real systemd, Docker and compose, a software TPM, two disks (system and "backup share"), a bridge with no route
out. Each cell starts from an overlay of one prepared base image. A power cut is a kill of the guest's process;
signals go to the process in the guest. The guest also keeps the rehearsal away from the host's own
`/run/trialbox` (LR-43) and from the engine the bench runner uses (LR-11).

**Releases N-1 and N-2.** No rebuild of old commits each night. A bundle store on the host holds, per commit, the
rehearsal media signed with a long-lived rehearsal key (never the vendor's). Each night builds N, master's head,
with the night's number as its release number, and keeps it. The "from" releases come from a committed ledger, one
line per bundle handed to a real box (LR-69): N-1 is the newest ledger commit that is not N, N-2 the one before;
"yesterday's green N" is a third, cheap row. A commit whose gates no longer pass is recorded as not buildable and
skipped, never faked.

**Axes.** From-release (N-1, N-2, yesterday's N; N for the fresh row). KEK back end (passphrase, TPM, shares).
Mode: a rehearsal box with stand-in model servers; a PRODUCTION install cannot be rehearsed with a rehearsal bundle
(D-726), and the report says so. Transition and one interruption per cell. Prior state: clean, or a planted
leftover (an update marker, a stale lock, a half-written `installed.json`, stopped services, a restore work folder).

**Each cell.**

1. Boot the overlay. Record a listing (path, owner, mode, size, hash) of everything outside the box's own paths,
   with a second user's folder planted.
2. Install the from-release with its own media and its own bootstrap, as root through real `sudo`. Ingest the
   synthetic site, run one SCREEN, take one nightly backup to the second disk.
3. Run the transition with release N's media: the bootstrap over the kept tree; `tools/apply_update.sh <N>` from
   the shell and from the console; `rollback`; the update again; the nightly backup; `restore --last --restart`,
   and a restore of N-1's backup onto N; `rotate-kek` and `rotate pid_map`; a reboot; the bench runner's install,
   verify and remove on a guest of its own.
4. Interrupt at a named point, found from the step line the product prints or its marker: after the verify, in the
   image load, in the rollback-point dump, between the tree switch and the restart, in the migrate step, in
   "refdata" (LR-10), in the restore's data part and after it, in the re-wrap, in the seal. Kinds: INT, TERM, HUP by
   dropping the session (LR-13), KILL of the top process, power cut.
5. After a power cut: boot, wait for the units, and give the passphrase where the back end needs a person.
6. Recover as the runbook says: `status`, `rollback`, or the same command again.
7. Check the invariants, then one SCREEN and one backup, then the listing again and its difference.

**Invariants after every cell.**

- **Health is honest.** The running, healthy services equal the project's configured services (N of N), or the
  command ended non-zero and `status` or the doctor names what is down.
- **One release.** `current`, `installed.json` and the running containers' images agree, all N or all the
  from-release; no marker left that `status` does not report; no `releases` folder inside a release (LR-26).
- **Host tree.** Every file of `current` matches the signed checksum list of the bundle it claims.
- **Keys.** The key check passes as the services' own user (LR-3, LR-4); every wrapped key opens; after a reboot
  the KEK is back only by the back end's own path; the TPM credential opens the KEK that `kek.json` names (LR-6).
- **Audit.** The chain verifies and grew across the transition.
- **Data.** Row counts and content hashes of every table, and the lake's file hashes, equal the record taken before
  (or the backup's manifest after a restore). The first SCREEN's job is still there.
- **Nothing foreign changed.** The two listings outside the box's paths are equal, the planted folder and any
  foreign image included; no plain dump, passphrase or one-time value is left in a log, the journal or `deploy/.env`.
- **The update works the next day.** After every cell that ends on N, a second update to an N+1 bundle (the same
  tree, the next release number) applies. This is the check that would have shown H-124.

**Size and time, estimated and not measured.** Each night: every transition from N-1 on the passphrase back end
with one interruption each, about 14 cells, plus N-2 and the TPM on the update and reboot cells; the rest rotates by
weekday so the whole table is seen each week. About 15 minutes to build N, about 15 minutes a cell; 14 cells on
three guests in under two hours. The weekly table is about 40 cells, four hours.

**To build first, in order.**

1. The ruling: a scheduled rehearsal on the bench, the ledger of handed-over bundles, the rehearsal key's custody.
2. `update`, `rollback` and `update-again` phases in `tools/rehearse_box/box.sh` with a second bundle. This closes
   LR-19 in the hosted rehearsal too, without a guest.
3. The health wait against the expected service set (LR-53), and a power cycle that loses `/run/trialbox` (LR-50).
4. The media step split out as "build the media for commit X into the store".
5. The guest: base image, software TPM, second disk, the host timer and its root-owned driver, the listing tool.
6. The interruption driver and the invariant checker as one script the cells share.
7. The report and its hand-over to the integrator.

## Not verified

- Nothing ran on a real Docker engine, under real systemd, on a real TPM, with a real restic, or on the bench host.
- Lane LR re-read LR-1, LR-2, LR-3, LR-4 and LR-9 against the code; the other reproductions were run once by the
  slice that found them and not repeated.
- LR-18 was reproduced at the level of the host-tree record, not through the installer and the updater. LR-26 was
  reproduced at the path level, not through the real runner. LR-7's database half and LR-15's container half are
  read only. LR-16 (c) rests on restic's lock rule.
- #1457 and #1336 were not read. The external reviewer's findings on #1466 and #1470 were not seen, so LR-14,
  LR-46, LR-47 and LR-49 may repeat them.
- The lifecycle unit files were run once as root without their database tests (1755 passed, 0 failed, 161 s); the
  database tests and the run as an ordinary user were not done.
- Run time and size of the nightly rehearsal are estimates. Whether an old commit's bundle still builds today was
  not tried.
