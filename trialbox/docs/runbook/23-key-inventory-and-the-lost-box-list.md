# 23. Key inventory and the lost-box list

**Reader:** the box owner.

*T-635, D-390. Closes OPS-044. The keys on the box, their holders and rotation rules are in code: `python -m
tools.keys inventory` (D-347) prints them, and SECURITY §4 says where each secret is kept. This page adds what that
list does not cover: what to revoke **outside** the box when the box, a disk or a backup is lost, and who does it.*

**Drill (T-213b):** `test_runbook_23_lost_box` (tabletop: the box is reported stolen at 10:00; every row of the
lost-box list is assigned, and the time each would take is written; Docker part: `python -m tools.keys inventory
--json` lists every key this page names).

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
| the alliance signing key (a member box of a COHORT alliance, D-1223) | the alliance root's register: the root's operator replaces the site's line, which also leaves the tables signed with the old key out of every merge; the new box makes a new key and sends its line ("Alliance site keys" below) | the root's operator, the site administrator | 1 working day |
| share credentials for the backup target (NAS, SMB) | the hospital file server | hospital IT | 4 hours |

**Not rotated:** `site_hmac.key`. A new key gives every patient a new pseudonym and loses the opt-outs (T-612). If it
may have been read, it is a breach under the incident plan, not a rotation.

**What makes a lost box less bad.** The site keys are wrapped under the KEK (D-347), and the KEK is not on the disk:
a stolen disk without the shares, the passphrase or the TPM does not open the pid map. The disk opens only with the TPM and a hospital Tang server (D-408), so a box carried out of the hospital stops at
the passphrase prompt. `deploy/.env` is still readable by anyone who gets into the running system: assume a stolen
box that was running exposes every password in it, and every row above applies.

## Alliance site keys

*D-1223 (card 10D-1). In a COHORT alliance each member box signs the count table it mails to the alliance root, and
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
written, is the opportunity feed's and is not used here.) The key is not wrapped under the KEK (D-1223, "What is not
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
