# The audit head signed every hour (card 10G-2, 2026-11-19, reworked 2026-11-20)

**Reader:** the people who build TrialBox, and the two reviewers of this card

Review 16 (card 16-19) asked for three things: the head of the audit chain signed hourly, an anchor folder the box's
root can write refused, and `doctor` failing a head older than 2 h. Decision **D-1345**. The independent review of
PR #1261 at `7933ba72` found seven High and four Medium points; each has a test written before its fix
(`tests/unit/test_audit_head_review_10g2.py`, one test per finding, all failing at `7933ba72`).

## What was there before this card

- `trialbox audit-sign` (D-562, `tools/trialbox/audit_heads.py`): checks the chain against every earlier signed head
  under the box's own public keys, signs where it stands, writes the head write-once to every folder of
  `TB_AUDIT_ANCHOR_TARGETS`, and records `audit.head_signed`. Run once a night at 00:20, and once by the installer.
- `doctor` check `audit_heads`: FAIL when no folder is set, the key is missing, the last run failed, a head is not
  signed by this box's key, or the newest head is older than `TB_AUDIT_HEAD_MAX_AGE_H` (36 h).

## What this card adds

| Part | Where |
| --- | --- |
| `audit-sign` every hour at :50; `logs daily` stays at 00:20 on its own line | `deploy/install.sh`; `audit_heads.cron_lines` |
| an updated box's nightly line moved to the hourly one, in the folder `TB_CRON_DIR` names (else `/etc/cron.d`) | pre-start step "hourly audit head" |
| each anchor folder judged root-proof or not, by the signer as root in its container | `audit_heads.root_proof` |
| PRODUCTION: a folder on the box's own disk (or of a type not told) gets no head; elsewhere it gets one and the run fails | `audit_heads._publish` |
| `doctor` fails closed: no result file, an unreadable key, a limit that is not a positive finite number, a head it cannot check | `doctor.check_audit_heads` |
| a head counts only when its signature verifies under this box's key; one dated more than 5 min ahead of the clock FAILs | `doctor.check_audit_heads` |
| `TB_AUDIT_HEAD_MAX_AGE_H` 36 -> 2; the FAIL line says since when and what to run | `libs/tb_common/config.py`, `doctor` |
| the private audit key root's, 0600; `doctor` FAILs it otherwise | `seal_keys.sh`, `init_key`, pre-start step "audit key root only", `doctor` check `audit_key_root` |
| the in-image doctor sees the result file (its folder mounted read-only) | `deploy/check_host.sh` |

## What the root-proof judgement claims, and what it does not

It is made by the signer, which runs as root in its container (`--user 0:0`): the same power as the box's root, unless
Docker remaps users (`userns-remap`, not used by the installer; then the judgement is of a weaker account). The host
command never judges with its own account. Per folder, in this order:

1. **The file system.** A folder on the box's own disk (ext4, xfs, btrfs, tmpfs, overlay, zfs, anything that is not
   NFS or SMB) is never root-proof: root can change any mode, owner or attribute there, `chattr +i` included. A type
   that cannot be told is "cannot be shown root-proof". In PRODUCTION such a folder gets no head.
2. **The head just written**, by the name the write returned (not by sort order): it must be a regular file with one
   link, and opening it for writing must be refused.
3. **A test file** `heads/.root-probe` (made once, kept; not a head: the readers take `*.json` only): renaming,
   deleting and overwriting it must each be refused. That is the folder's own permission over its files: a share
   that refuses an overwrite but allows a delete lets root delete a head and write another in its place.

A folder passes only when every one of these is refused. That shows the share refused this box's root those
operations at that moment, as the box sees it. It does not show what the share's administrator, a backup restore
or the share itself can do, nor that a WORM retention period has started; it cannot see deletions the share allows
to other accounts. Only a remote share with root squashed and create-only rights, or a write-once store, can pass; a
local folder can never pass, whatever its modes.

## Which key signs, and who can read it

The box's existing audit signing key, `audit_sign.key` (Ed25519), wrapped under the KEK, in the secrets volume. No
new key. In the compose file the services that mount both the secrets volume and the KEK are **adapter** and
**orchestrator** (uid 10001, audit volume read-only); they need both for their own keys (site HMAC, pid map, EDC,
actor keys). `seal_keys.sh` used to give every root-owned file of the folder to uid 10001, the audit key included:
they could open it, unwrap it with the KEK they hold, and sign a head. Now the private audit key's files stay root's,
mode 0600 (`seal_keys.sh` in both branches, `init_key`, the update's pre-start step); `doctor` (`audit_key_root`)
FAILs anything else; a test shows uid 10001 is refused the file (as root, by becoming 10001; as another user, a
stand-in from the modes). **The barrier is that file's permissions only** (finding H10G2-04): the KEK that wraps the
audit key is the same KEK those services hold, so anyone who can read that one file as uid 10001 (a later chown, a
backup restored with other owners) can sign heads. A real separation needs the audit key under a KEK of its own that
only the signer can open, or the key off the box (an HSM, or the hospital signing the heads).

## Links

Wherever this card's code opens, makes, tests or renames a file in an anchor, audit or result folder, it opens the
folder once without following a link (`O_DIRECTORY|O_NOFOLLOW`) and the name through that descriptor with
`O_NOFOLLOW` (`O_EXCL` when it makes one), and refuses anything that is not a regular file with one link:
`audit_heads.root_proof` (folder, head, test file), `reading` (the writer's lock file), `read_plain` and
`replace_plain` (the result file, the cron file), `key_root_only`; `doctor` reads the result file through
`read_plain` and the key files with `lstat`. A test plants a symbolic link, a hard link and a FIFO in each place and
shows the file they point at untouched. `libs/tb_common/audit.py` (`publish_head`, `read_signed_heads`) is card
H-68's and is not changed here.

## Threat note

**What this stops.** Someone holding the audit writer's account (the `audit-writer` container, or the database role
`tb_audit_writer`) can change the chain's files but cannot sign a head for them; the next hourly run refuses the
chain and `doctor` FAILs. Someone holding the adapter's or the orchestrator's account can no longer open the audit
key. Someone holding the box's root can sign a new head, but where the anchor folder passes the judgement above,
cannot change, rename or delete a head already written: a rewrite of anything before the newest head shows in
`tools/audit_verify.py --heads` and in the next run.

**What it does not stop.** The box's root can change events written since the last signed head (at most about an
hour, two with one missed run) and sign over them: the key lives on the box. On an anchor folder that does not pass,
the box's root can do anything to the heads; the run then fails each hour (PRODUCTION: no head there at all), and
`doctor` FAILs in PRODUCTION and WARNs elsewhere. A clock moved back can make the signer stamp heads in the past; a
head more than 5 minutes ahead of the clock FAILs.

## Findings

[findings.json](audit-head-signed-hourly-2026-11-19/findings.json): H10G2-01 (closed by the rework: delete and
rename are judged), H10G2-02 (the judgement not yet run on a real share), H10G2-03 (doctor reads the last run's
result, it cannot judge the folder itself), H10G2-04 (the KEK is shared: file permissions are the only barrier).

## Tests

`tests/unit/test_audit_head_review_10g2.py` (the review's 11 findings and the link tests), `tests/unit/
test_audit_head_signed_hourly.py`, `tests/unit/test_audit_heads_nightly.py`, `tests/unit/test_update_minseq.py`,
`tests/unit/test_trialbox_doctor.py`. Both new files pass as root and as a non-root account (the stand-ins run then).
