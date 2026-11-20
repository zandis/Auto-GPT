# The audit writer follows no link: card H-68 (2026-11-20)

**Reader:** the people who build TrialBox: lane H, lane K, the integrator, and the owner of the restore
(`tools/trialbox/backup.py`). Findings for builders, so in one language.

Card H-68, high-risk, decision D-1351. Found by lane K while reviewing #1228 and given to lane H by the integrator on
#639 (2026-11-20, 04:02 and 04:04 UTC). Findings in the register's `--add-from` form:
`audit-files-no-links-2026-11-20/findings.json`.

## The hole

`libs/tb_common/audit.py` on master (dfb92007) opened every file of the chain by path, and the open followed a
symbolic link: `write_head` (`.HEAD.json.tmp`, lines 219-220, opened `"w"`, which truncates), `AuditLog._locked`
(`.lock`, lines 266-267, `"a+"`, which creates), `_repair_torn` (the newest day file read at 287, a `.torn-<n>` name
checked with `exists()` and opened `"wb"` at 308-312, the day file truncated at 316) and `_write` (the day file,
333-334, `"a"`). An account that can write the audit folder can plant one of those names as a link, or a hard link,
beforehand. The next command that writes the chain as root then writes the file the link names. No race is needed.

`tests/unit/test_audit_files_no_links.py` shows it on master's code. Run against master's `audit.py`, 21 of its 22
tests fail, as root and as `nobody`. The 22nd, the byte test, passes on both. A probe through master's code, with a
0600 file beside the folder standing in for root's file:

| Planted in the audit folder | What master's writer did to the file outside |
| --- | --- |
| `2026-11-20.jsonl` -> the file | moved its last line to `.torn-1` (0644, readable by all), cut the file, then wrote audit lines into it |
| `.HEAD.json.tmp` -> the file | replaced its content with the head anchor's JSON |
| `.lock` -> a name that is not there | made that file, as root |
| a hard link of the file as `2026-11-20.jsonl` | the same as the symbolic link |
| a FIFO as a day file | the writer hung for good |

## Step 1: the facts

### a. Who owns the audit folder and who writes there

- **The folder.** On a box it is the named volume `audit-data` (`deploy/docker-compose.yml`, volume list, line
  569). The host path is `/var/lib/docker/volumes/trialbox_audit-data/_data` (`tools/trialbox/backup.py:98`,
  `tools/trialbox/audit_heads.py:185`). Docker seeds it from the image, and `deploy/docker/python.Dockerfile:18-20`
  makes `/data/audit` and gives it to `tb`. **So the folder belongs to uid 10001 (gid 10001), mode 0755**: not
  sticky, not writable by every account. Its files are 10001's, except those a root command made and has not given
  back yet. `/var/lib/docker/volumes` is root's (0701), so no other host account reaches it.
- **Who mounts it read-write.** Only `audit-writer` (`deploy/docker-compose.yml:320`). It runs as `10001:10001`
  under the 10G-1 controls (D-1323, `x-py`, line 39). The other seven services mount it `:ro` (lines 275, 303, 353,
  371, 397, 424). So the account that could plant a link is uid 10001: a compromised `audit-writer`, or any host
  process running as uid 10001. A link written inside the container names a host path when root on the host follows
  it.
- **The code paths that open a file in the folder to write or append** (all through `AuditLog`, so all fixed here):

| Path | Account | Folder |
| --- | --- | --- |
| `libs/tb_common/audit_writer.py:514` (and `:449`), the drain's `self.chain.append` | uid 10001, container | the volume |
| `tools/trialbox/backup.py:2038` (`_audit`: `backup.restored` and the restore's events) and `:1976` (`_hold_flags`, the hold's `flag.set`) | **root, host** (`trialbox restore`) | the volume's host path (`layout`, `"audit": "audit-data"`) |
| `tools/key_ceremony.py:195`, `tools/key_escrow.py:149` | the operator, root on the host when `--audit-dir`/`TB_AUDIT_DIR` names the volume | the volume |
| `tools/audit_verify.py:112` (`--reanchor`), `:234` (`--sign-head`), `:263` (`--rotate-key`) | the operator, as root on the host (runbook page 20, close-out) | the volume |
| `tools/trialbox/audit_heads.py:249` (`sign_local`, file mode) | whoever runs it; an in-process box | `TB_AUDIT_DIR` |
| `tools/trialbox/update.py:1882` (`_append_audit`) | root, host | `deploy/updates/audit`, root's own folder, not the volume |
| `tools/trialbox/model_report.py:63`, `tools/omop_parity.py:729` (flags' audit) | the caller | `TB_AUDIT_DIR` |

  These do not write in the folder: `audit-sign` on a box (`audit_heads.py:209` mounts the volume `:ro` into a root
  container, and its event goes through the orchestrator and the journal). The `deploy/install.sh` events (lines
  977-1005) go through the orchestrator and the journal too. `doctor` writes only a temp folder (`doctor.py:596`) and
  reads the volume.
- **Root commands also write anchor folders.** `audit-sign` publishes as root (`--user 0:0`) into
  `TB_AUDIT_ANCHOR_TARGETS` through `publish_head` and `_write_once` (`audit.py:857`, `O_CREAT | O_EXCL`). That does
  not follow a link in the last name. The `heads/` and `keys/` folders are found by path, though (finding H68-03).

### b. Does the host's `fs.protected_*` setting stop it? No.

- **`protected_symlinks`** (Linux `fs/namei.c`, `may_follow_link`). When set, a link is not followed only if all of
  these hold: it lies in a **sticky, world-writable** folder; the follower's fsuid is not the link's owner; and the
  folder's owner is not the link's owner. The audit folder is 0755 and not sticky, so the rule never applies there.
  Also, the planter (uid 10001) owns the folder, so its links would be followed even in a sticky folder.
- **`protected_regular`** and **`protected_fifos`** limit `O_CREAT` opens of files and FIFOs that someone else owns,
  again only in sticky world-writable folders. They do not apply here.
- **`protected_hardlinks`** stops an account linking a file it does not own and cannot read and write. With it on, uid
  10001 cannot hard-link root's 0600 file into the folder. With it off, it can, on the same file system:
  `/var/lib/docker` is often on the root file system. So that setting covers only the hard-link form, and only when on.
- This container has `protected_symlinks=0`, `protected_regular=0`, `protected_fifos=0`, `protected_hardlinks=1`.
  The tests show the hole and the fix with `protected_symlinks` off. The fix does not depend on any of these settings.

### c. The test that plants the link

`tests/unit/test_audit_files_no_links.py`, 22 tests. None needs root. Each test makes a temp folder standing in for
the audit folder and a 0600 "victim" beside it, then plants a name and asserts what happens:

- a link as the day file, `.HEAD.json.tmp`, `.lock` or `HEAD.json`, on a fresh folder and before a later write;
- a dangling link (`.lock`, `.HEAD.json.tmp`, the day file);
- a link in the `.torn-1` evidence name;
- the folder itself a link;
- a hard link;
- a FIFO (the day file, `.lock`, `HEAD.json`, run in a thread with a 20 s limit);
- a folder in a file's place;
- a file of another owner;
- a world-writable folder.

Each is refused, and the victim stays byte-identical. Ownership is checked through a stand-in: the test replaces
`audit._owners_allowed` with a set that leaves out the file's owner. A user who is not root cannot chown a file
to someone else.

## Step 2: the fix

`audit.py` has a private `_Folder`. The writer opens the folder once, in `AuditLog._locked`, with
`O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`. It refuses a folder that is a link or not a folder, one writable
by every account, or, when it is not root, one owned by an account that is neither itself nor root. Every file is
then created and opened relative to that descriptor with `O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`: `.lock`, the day
files, `.HEAD.json.tmp`, `HEAD.json` and the `.torn-<n>` evidence. The new `.torn-<n>` is made with `O_EXCL`, so a
name already there is skipped and never written. After each open, `fstat` must show a plain file with one link,
owned by the folder's owner or by this process.

Nothing is reopened by path. The head's temporary file is truncated only after those checks. The rename into
`HEAD.json` and the folder's fsync use the same descriptor. The day file is read, copied and cut on one descriptor.
The free-space check uses `fstatvfs` on the folder. The public `write_head` goes through the same folder object.
Public signatures are unchanged.

A refusal raises `AuditAnchorBroken`, the module's error for "no write until a person has looked". It names the
file in the folder and why, never a link's target. It is logged on `tb_common.audit` at ERROR. The drain already
logs any `OSError` from the chain as "the audit chain refused a write" and retries in 60 s
(`audit_writer.py:536-539`). The root commands stop with the message.

**Nothing in the format moves.** `test_the_files_written_are_byte_for_byte_what_they_were_before` runs a fixed
sequence through every writing path: adopting a pre-anchor chain, two days, a torn line repaired, a `write_head`
gap, `reanchor`, and a last event. It compares the sha256 of every file with the same run on master. The files of
the two runs were also compared with `diff -r`: identical bytes, identical modes. Every test file that imports
`tb_common.audit` or the audit tools passes, 137 files.

## Should root commands append as the folder's owner instead?

**Yes, as a second layer. It is not built in this card (finding H68-02).**

Dropping to the folder's owner (setgroups, setgid, then setuid to the folder's uid, in a child process, for the
write only) means root's own power is never used inside a folder another account controls. A missed name, a future
path, or a bug in this code could then do no more than uid 10001 can already do. It also makes the root-made files
and their give-back (`backup.py` `_own_writes`, D-724) unnecessary.

No root command needs root for the audit write itself. `trialbox restore` needs root to replace the volumes and talk
to Docker. The key ceremony and escrow need it to read the KEK. `audit_verify.py --reanchor` needs it only because
the folder belongs to 10001.

The cost: a fork in processes that hold database connections and threads (the restore). The written record must
come back through a pipe, because `Flags` and the restore use it. Errors must cross the process line. And the
tests in CI run as a user who cannot change uid, so the drop is shown only as root.

That is not small and certain. Lane K is already making the key ceremony append as the folder's owner in #1228. With
this card, root follows no planted name and writes no file but a plain, single-link file in the folder, so the
remaining gain is defence in depth.

## Threat note

- **Who could plant a name:** uid 10001 with the volume read-write, that is a compromised `audit-writer`, or any
  host process running as 10001. Root can too, but it needs no trick. The seven services that mount the volume `:ro`
  cannot.
- **What they gained before this card:** the next root command that writes the chain (a restore, a key ceremony
  or escrow, a reanchor) would truncate, overwrite or append to any file on the host, or make a new root file. That
  is a write from the container to host root, and it can also hang the root command on a FIFO.
- **What this card stops:** every write, read and creation by the writer through a planted symbolic link, hard link,
  FIFO, folder or file of another owner in the audit folder, and the folder itself being a link.
- **What it does not stop:** uid 10001 can still delete or rewrite the chain. That is the signed heads' job, not
  this card's.
- **Readers still open by path:** `verify`, `read_head`, `lines_backward` and the `audit_heads` lock. They do not
  write, but a FIFO there could hang them (H68-04).
- **The anchor folders' subfolders** (H68-03).
- **The restore's give-back `_own_writes`** (`backup.py:2087-2089`) changes the owner of every root-owned file in the
  folder. A hard link to a root file, where `protected_hardlinks` is off, would be given to uid 10001 (H68-05). Now
  that the writer refuses such a link, a restore stops before `_own_writes` runs. But a link planted after the write
  and before the give-back is still a race.

## #1261 (claude/lane-h-10g2-audit-head-signed-hourly, 7933ba72)

It does not change `libs/tb_common/audit.py`. In `tools/trialbox/audit_heads.py` at that head, only one place opens
a file in the audit folder by path: line 74, `reading()`, `os.open(audit_dir / ".lock", os.O_RDONLY)`, a read-only
open that master has too (`reading()`, lines 67-80, the open at 71). It neither creates nor writes. But it follows a link and blocks on a
FIFO, so it needs `O_NOFOLLOW | O_NONBLOCK` and an `fstat` check (H68-04).

Its other writes are outside the audit and anchor folders: the cron file (lines 319-323, `/etc/cron.d`) and the
result file (lines 373-375, `TB_LOG_DIR`). Both are root's own folders. Its `overwritable()` (lines 194-204) uses
`access(2)` and opens nothing. The two cards do not touch the same lines and can land in either order.

## Files outside the card

- `libs/tb_common/audit.py`: shared library code, changed by the integrator's ruling. Bodies only, no public
  signature changed, plus the private `_Folder`, `_owners_allowed`, `_refused`, `_head_record` and `_last_line_of`.
  The by-path `_last_line` and `_count_lines`, used only inside the module, are gone.

## What was not verified

- Nothing was run on a real box or under Docker (no daemon here), so the volume's owner is read from the Dockerfile
  and the compose file, not observed.
- The kernel rule is read from `fs/namei.c` and the sysctl documentation, not tried with `protected_symlinks=1`. The
  container cannot change it.
- macOS and other systems without `O_DIRECTORY` or `dir_fd` were not tried. TrialBox runs on Linux.
