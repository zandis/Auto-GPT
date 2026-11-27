# D-1351 The audit writer opens its folder once and follows no link in it

- **Task:** lane H, card H-68 (high-risk; lane K's finding on #639, 2026-11-20 04:02 UTC, given to lane H at 04:04)
- **PR:** this branch (`claude/lane-h-68-audit-files-no-links`)
- **Date:** 2026-11-20
- **Status:** proposed
- **Builds on:** D-127 (the torn line repaired), D-272 (the head anchor), D-394 (one writer), D-724 (the restore gives
  root's files back), D-1323 (the services run as 10001)

## Decision

1. **The folder is opened once.** `AuditLog` opens the audit folder with `O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` when
   it takes the writer's lock. It refuses a folder that is a link or not a folder, one writable by every account, and,
   when the writer is not root, one owned by an account that is neither the writer nor root.
2. **Every file goes through that descriptor.** `.lock`, the day files, `.HEAD.json.tmp`, `HEAD.json` and the
   `.torn-<n>` evidence are created and opened relative to the folder (`dir_fd`) with `O_NOFOLLOW | O_CLOEXEC |
   O_NONBLOCK`. A new `.torn-<n>` is made with `O_EXCL`. Nothing is reopened by path. The head's rename and the
   folder's fsync use the same descriptor.
3. **What is opened is checked.** After each open, `fstat` must show a plain file with one link, owned by the
   folder's owner or by the writing process. A file is truncated only after that check.
4. **A refusal stops the write.** It raises `AuditAnchorBroken`, names the file and the reason (never a link's
   target), and is logged on `tb_common.audit`. Nothing is written until a person has looked at the folder.
5. **Nothing a verifier reads changes.** The format, the hash chain, the file names and the file modes stay byte for
   byte what they were. A test compares a fixed run with master's.
6. **Root commands appending as the folder's owner** is recommended as a second layer and left open (finding
   H68-02). No root command needs root for the write. The cost is a privilege-dropping child process.

## Why

The volume belongs to uid 10001, the audit writer's account, and root commands on the host (a restore, a key
ceremony, a reanchor) write the same chain. A name planted as a link in that folder made root write a file outside
it: a write from the container to host root. `fs.protected_symlinks` does not apply to a folder that is neither
sticky nor world-writable, and a fix may not depend on a host setting. The page
`docs/handover/audit-files-no-links-2026-11-20.md` has the facts and the threat note.

## Checks

`tests/unit/test_audit_files_no_links.py`: 22 tests. Each plants a name and checks the refusal and that the file
outside is unchanged: a symbolic link, a dangling link, a hard link, a FIFO, a folder, a file of another owner (by a
stand-in for the allowed owners), a link as the folder, a world-writable folder. The last test is the byte test.
21 of the 22 fail on master's code, and all 22 pass with this change, as root and as a user who is not root.
