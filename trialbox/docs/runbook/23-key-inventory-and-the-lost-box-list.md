# 23. Key inventory and the lost-box list

**Reader:** the box owner.

*T-635, D-390. Closes OPS-044. The keys on the box, their holders and rotation rules are in code: `python -m
tools.keys inventory` (D-347) prints them, and SECURITY §4 says where each secret is kept. This page adds what that
list does not cover: what to revoke **outside** the box when the box, a disk or a backup is lost, and who does it.*

**Drill (T-213b):** `test_runbook_23_lost_box` (in process: `python -m tools.keys inventory --json` lists every
key of the box this page names, each command the lost-box list gives for one is the inventory's own and the
tools take it, and `site_hmac.key` is never rotated). The tabletop (the box reported stolen at 10:00; every
row assigned and timed) is a meeting and is not rehearsed by a test.

## The inventory on the box

```sh
python -m tools.keys inventory          # every key: where, what it protects, holder, rotation, compromise action
python -m tools.keys inventory --json
python3 -m tools.trialbox secrets status  # tokens: file, mode, age; never a value
```

Check the printout with hospital IT at IQ and once a year. A key whose holder has left is rotated (§25).

## The lost-box list

Use it when the box, one of its disks, or an unencrypted copy of its secrets folder is lost or stolen. It applies too
when a backup file **and** the backup private key are lost together. Start within the hour; the clock is the
incident plan's (T-318). Change each secret at its source, not on the lost box.

| Secret outside the box | Where it is changed | Who | Within |
| --- | --- | --- | --- |
| AD or LDAP bind account (hospital sign-in, §12) | the hospital directory: disable the account, make a new one for the new box | hospital IT | 4 hours |
| OIDC client secret (Authelia or the hospital's provider) | the identity provider: delete the client, register a new one | hospital IT | 4 hours |
| SMTP and IMAP passwords of the box's mailbox | the hospital mail server | hospital IT | 4 hours |
| REDCap API tokens (one per CRF project, §2 EDC prefill) | REDCap: delete each project's token | the REDCap administrator | 4 hours |
| a cloud-model API key, if one is set | the cloud provider's console | the hospital account owner | 4 hours |
| the hospital's TLS certificate and key (§12, hospital mode) | the hospital CA: revoke, issue a new one | hospital IT | 1 working day |
| staff second-factor (TOTP) secrets | every account enrols again on the new box (`console.cli reset-totp NAME`, §12) | site administrator | before the new box opens |
| staff passwords of local accounts | reset on the new box; tell staff who used the same password elsewhere | site administrator | before the new box opens |
| the backup key pair | `trialbox backup-keygen` on the new box; old backups stay readable with the old private key | hospital IT | 1 working day |
| the KEK (steward shares, passphrase) | `python -m tools.keys rotate-kek` on the restored box; old shares stop working | key stewards | at the restore |
| `pid_map.key` | `python -m tools.keys rotate pid_map` on the restored box | site administrator | at the restore |
| vendor update key | not on the box (public key only): nothing to do | | |
| the alliance signing key (a member box of a COHORT alliance, D-1226) | the alliance root's register: the root's operator replaces the site's line, which also leaves the tables signed with the old key out of every merge; the new box makes a new key and sends its line ("Alliance site keys" below) | the root's operator, the site administrator | 1 working day |
| share credentials for the backup target (NAS, SMB) | the hospital file server | hospital IT | 4 hours |

**Not rotated:** `site_hmac.key`. A new key gives every patient a new pseudonym and loses the opt-outs (T-612). If it
may have been read, it is a breach under the incident plan, not a rotation.

**What makes a lost box less bad.** The site keys are wrapped under the KEK (D-347), and the KEK is not on the disk:
a stolen disk without the shares, the passphrase or the TPM does not open the pid map. The disk opens only with the TPM and a hospital Tang server (D-408), so a box carried out of the hospital stops at
the passphrase prompt. `deploy/.env` is still readable by anyone who gets into the running system: assume a stolen
box that was running exposes every password in it, and every row above applies.

## Rotate the KEK passphrase

*H-96 (F-45; the integrator's ruling 7094934985). For a box whose KEK is under a passphrase (`KEK_BACKEND=passphrase`:
a proof of concept, a validation run, a board without a TPM). Hospital IT does it, with the box owner.*

**When.** Every box installed with the passphrase in the environment (`sudo --preserve-env=...`, `sudo -E`, the form
`install.sh`, `box-install.sh` and §16 showed before H-96): sudo wrote the variable with its value to the system
journal, which root and the `adm` group can read. Treat that passphrase as exposed and rotate it. Rotate it too when
someone who knew it leaves (§25). Since H-96 every installer and `tools.keys` refuse a passphrase in the
environment, on every box: it protects a key, so it is not one of the four things a proof-of-concept box may stop for.

**1. Is the KEK unsealed?** `sudo env PYTHONPATH=libs:services:. python3 -m tools.keys status` names the KEK and
whether it is open (`/run/trialbox/kek`). A box that was restarted and not opened since is opened first with
`sudo env PYTHONPATH=libs:services:. python3 -m tools.keys unseal`, which asks for the current passphrase (not shown).

**2. The new passphrase** (12 characters or more, one line) goes in a file only root can read. After sudo's own
password prompt, type it, then press Enter (nothing is shown):

```sh
cd /opt/trialbox
sudo bash -c 'umask 077; IFS= read -rs p; printf "%s\n" "$p" > /root/trialbox-kek-new.pass'
```

**3. Rotate.** Every wrapped key is re-wrapped under the new KEK, and the open KEK in `/run/trialbox/kek` is replaced.
The file is removed when the rotation succeeds (`--keep-passphrase-files` keeps it). On a terminal,
`--new-passphrase-stdin` asks for it twice instead of the file.

```sh
sudo env PYTHONPATH=libs:services:. python3 -m tools.keys rotate-kek --backend passphrase --new-passphrase-file /root/trialbox-kek-new.pass
sudo systemctl restart trialbox
```

**On a PRODUCTION box** the box rotates itself (D-1092; the integrator's ruling 7101844662). rc1 refuses the key
ceremonies there (R22-34), but rotating an exposed passphrase is a safety action: `rotate-kek --backend passphrase`
with the new passphrase from the file or from stdin goes through, as an audit event `keys.rotate_kek` (who, when,
the box, the old and the new KEK's ids; never a passphrase). Name the audit folder, or nothing is changed:

```sh
sudo env PYTHONPATH=libs:services:. python3 -m tools.keys rotate-kek --backend passphrase --new-passphrase-file /root/trialbox-kek-new.pass --audit-dir "$(sudo docker volume inspect -f '{{.Mountpoint}}' trialbox_audit-data)"
sudo systemctl restart trialbox
```

Every other `rotate-kek` (to the TPM, to steward shares, with an escrow set, or with the new passphrase typed at the
prompt without `--new-passphrase-stdin`) and the other key ceremonies stay refused there. A passphrase KEK is still
not a PRODUCTION site's back end: plan the move to the TPM or steward shares (SECURITY §10).

**4. Keep the new passphrase** where the old one was kept (the sealed envelope); destroy the old copy. Then make a
backup (`trialbox backup`, §5): backups made before the rotation hold the old `kek.json`, so they open with the old
passphrase **and** the backup private key together; a backup made now does not need the old passphrase.

**5. Look for passphrase lines in the logs, without printing one.** Each command prints a count only:

```sh
sudo journalctl --no-pager -o cat | grep -c 'KEK_[A-Z_]*PASSPHRASE[=]'
sudo zgrep -c 'KEK_[A-Z_]*PASSPHRASE[=]' /var/log/auth.log*
```

`0` everywhere: no log on this host holds a passphrase. A count above 0 is the exposed (now old) passphrase. The
journal cannot remove single lines: whether to rotate and vacuum the journal (`journalctl --rotate`, then
`journalctl --vacuum-time=`) and the old `auth.log` files is hospital IT's decision under its log policy. After the
rotation those lines open the box's keys only together with a backup made before step 4 and the backup private key.

**Where the passphrase still is.** Nowhere on disk once the install or the rotation is done: the installers hold it
in a shell variable that is never exported and hand it on by a pipe (to the seal step, to the keys commands in the
trialbox-py image by the container's stdin), and the operator's file is removed. The open KEK in `/run/trialbox/kek`
(tmpfs) is derived from it, not the passphrase. A box set up on its first-run page keeps the owner's passphrase in the
first-run folder (`/run/trialbox-firstrun`, tmpfs) until the apply step has sealed the keys. Nothing takes it from an
environment (H-97): every service, the nightly audit signer and the backup open the KEK from `/run/trialbox/kek`, which
`tools.keys unseal` writes after each restart; a `TB_KEK_PASSPHRASE` with a value in a caller's environment is refused
by the key library too, and the signer's container is never given it. Never export it: unseal with the passphrase typed,
or from a root-only file (`--passphrase-file`) or stdin (`--passphrase-stdin`).

## Alliance site keys

*D-1226 (card 10D-1). In a COHORT alliance each member box signs the count table it mails to the alliance root, and
the root merges a member's table only when the signature holds for the key its register holds for that site. The
register has the form of the opportunity feed's site key register (D-467) and its key is made the same way.*

On the member box, once (the site administrator). The orchestrator sees the box's secrets volume at
`/run/secrets/trialbox` (`deploy/docker-compose.yml`); on the host it is the volume `trialbox_tb-secrets`:

```sh
sudo python -m tools.opportunity_feed keygen --out /var/lib/docker/volumes/trialbox_tb-secrets/_data/alliance
#   writes site.key and band.secret with mode 600 from the start, and site.pub
```

The command prints one register line: `"<site_id>": {"name": "<registered name>", "key_sha256": "<64 hex>"}`. Put the
box's `site.id` from `settings.yaml` for `<site_id>` and the site's name for `<registered name>`. Give `site.key` the
owner of the other files in that volume and keep its mode 600. Set
`TB_ALLIANCE_SIGNING_KEY_FILE=/run/secrets/trialbox/alliance/site.key` in `deploy/.env` and restart the orchestrator.
A setting that names a missing file, or a file its group or others may read, stops the COHORT job with a sentence
saying so. Keep `site.key` on the box: it is never mailed, printed or copied to the root. (`band.secret`, also
written, is the opportunity feed's and is not used here.) The key is not wrapped under the KEK (D-1226, "What is not
done here").

Give the register line to the root's operator by a channel both sites trust (in person, or read out on the telephone
and compared): the line is not secret, but a wrong line lets someone else's key speak for the site. On the alliance
root (the root's operator):

1. Add the line under `"sites"` in the register file, for example `/run/secrets/trialbox/alliance-site-keys.json`:
   `{"sites": {"HOSP-B": {"name": "Hospital B", "key_sha256": "…"}}}`.
2. Set `TB_ALLIANCE_SITE_KEYS_FILE` to that file in `deploy/.env` and restart the orchestrator. The file is read at
   each merge, so later edits need no restart.
3. Check: the next `COHORT MERGE` from that site ends done; a refusal names the site and says why (not signed, no key
   in the register, a key not registered for the site, signed for another study or time window, changed, not newer
   than the table already stored).

A member box without `TB_ALLIANCE_SIGNING_KEY_FILE` still runs COHORT for itself and says in its summary that nothing
was sent to the root. Tables a root stored before this version are kept, marked unverified, and left out of every
merge until their site sends them signed; the merge's summary names those sites.

**A new key** (a new box, a lost box, a key that may have been read): the site runs `keygen` again; the root's
operator replaces the site's line. From the next merge, the site's tables signed with the old key are kept but left
out, and the summary names the site, until the site sends its tables under the new key; the old key can sign nothing
that is taken after its line is gone.
