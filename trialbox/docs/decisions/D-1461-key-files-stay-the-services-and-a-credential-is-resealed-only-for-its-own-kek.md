# D-1461 Key files stay the services', and a TPM credential is resealed only for its own KEK (H-133)

- **Task:** lane H, card H-133 (the integrator's 7136231344, item 2; lane LR's review, LR-3, LR-4, LR-6)
  · **Date:** 2026-11-24
- **Status:** reserved for H-133 (the integrator flips the row when merged)
- **Builds on:** D-887 (the installer hands the sealed files to the secrets folder's owner), D-836 (the KEK sealed
  before any key is wrapped under it), D-894 (a TPM box's escrow shares), D-1092 (every rotation audited, resumable,
  locked)

## Context

The key commands run as root and wrote every file root's, mode 0600. D-887 handed them to the services' account
(the secrets folder's owner, uid 10001 on a box) only at the end of the first seal, so `rotate-kek` and an `unseal`
after a restart left the services unable to open any key (LR-3, LR-4). `rotate-kek --backend file` on a TPM box left
`/etc/credstore.encrypted/trialbox-kek` sealing the old KEK, so the next boot's unseal was refused (LR-6).

## Decision

1. **Files for the services are theirs before they take their name.** Run as root against a secrets folder another
   account owns, a key command gives each file it writes there that the services read (`kek.json`, the wrapped and
   plain keys, a rotation's staged keys) and the runtime KEK to the folder's owner on the temporary file, before the
   rename (`tb_common.kek._write_private(owner=)`, `services_owner()`). A runtime folder the command makes
   (`/run/trialbox` after a restart) is that owner's too, mode 0700; one already there keeps its owner. Modes stay
   0600. The rotation's journal stays root's.
2. **The owner comes from the folder.** `services_owner()` reads the secrets folder's owner with `stat`, only when the
   command runs as root and the owner is not root. No variable of the caller or of the command's mapping decides it.
3. **A KEK file the account cannot read is a custody problem.** `load_kek` turns the error into a `KekError`, so
   `custody()` and the doctor report it instead of failing.
4. **The TPM credential follows its own KEK only.** `rotate-kek --backend file` seals the new KEK to the TPM when the
   credential opens to the secrets folder's KEK at that moment, or when none is there and `--seal-tpm` asks for one
   (a new board). A credential sealing another KEK (another folder's, another box's) is never replaced; with
   `--seal-tpm` the rotation is refused. The new KEK is sealed to `trialbox-kek.next` and opened again before the
   commit; the roll-forward swaps the credential first, then the keys, `kek.json` last; the roll-back removes
   `.next`. With no `systemd-creds` where a seal is needed, nothing changes. The credential's place and the folders
   the tool is looked for in are fixed in the code. The boot unit stays `seal_keys.sh`'s (LR-45).

## Consequences

At every instant each site key either is still as it was or opens with the KEK sealed in the credential in place,
and every key file the services read stays readable by them. An ordinary user cannot look in the credential folder:
its `rotate-kek` seals nothing and says so. A rotation from a TPM box to another back end still leaves the
credential and unit on the old KEK (H133-05, open).
