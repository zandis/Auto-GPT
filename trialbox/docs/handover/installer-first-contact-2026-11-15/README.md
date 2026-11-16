# Evidence: the installer's first contact on a GPU VM (2026-11-15)

This folder holds the evidence behind
[installer-first-contact-2026-11-15.md](../installer-first-contact-2026-11-15.md), so that the integrator and lane D
can examine what happened, not only read a summary.

## Where it comes from

Each launch's results archive (`results.tgz`, a few tens of KB) in the private bucket
`gs://trialbox-demo-runs/boxruns/<run id>/`, read on 2026-11-15 after the last launch. The 29.6 GB bundle itself was not
downloaded and is not here. For the install launch, the first attempt's install log also came from lane G's local copy
(the bucket's copy holds both attempts).

## How it was cleaned

Every file was passed through a line filter before it was committed. A line that contained any of these was replaced
by `[line removed: <kind>]`:

| Kind | What it catches |
| --- | --- |
| key fingerprint | the site keys' fingerprints, the signing key's id and its public key hash |
| KEK id | the id of the key-encryption key and its files |
| password, token, secret or code | the words password, passphrase, token, secret, credential, private, one-time, enrol, administrator, code (logs); in the prose files only a value written after such a word |
| redacted marker | lines the driver had already redacted, and the line on each side of them |
| e-mail address | any address (the synthetic site's too) |
| IP address | any IPv4 or IPv6 address |

In `chain-review.md` the loopback address was written out as words instead of removing two table rows. Log files keep
their last 80 lines only (the first line says how many were left out). Nothing else was changed. The files were
checked with `make -s data-scan` and `python -m tools.security_scan secrets` (both pass, no new allow-list entry).

## The launches

| Run id | What it was | Driver commit | Outcome |
| --- | --- | --- | --- |
| `box-20261115T060826Z-f6bcc176` | build L1 (5 boots: 1 start, 4 resumes) | f6bcc176, resumed from c67e96f8, e7d6bfd3, a441cecd, 70d10eba | stopped at b05 (F1 to F5) |
| `box-20261115T073901Z-e7504de38` | build L2 | e7504de3 | stopped at b05 (F6) |
| `box-20261115T080047Z-5618bd840` | build L3 | 5618bd84 | stopped at b05 (F7, disk) |
| `box-20261115T085016Z-876ff6506` | probe L4 (facts only) | 876ff650 | done: the VM's facts |
| `box-20261115T091037Z-ac36aa21f` | build L5 (2 boots) | ac36aa21, then 4c7c4701 | complete: bundle `val-ac36aa21fdc1` |
| `box-20261115T094747Z-4c7c47017` | install L6 (2 boots) | 4c7c4701, then 7cd0250c | stopped at 02-install (F9, F10, then F11) |

## Files

| Path | What it is |
| --- | --- |
| `run-log.md` | lane G's running log of the step: every launch, fault F1 to F8, fix commits, VM hours and US$ (as it stood at 09:47; the install launch's lines are in the hand-over report) |
| `chain-review.md` | the deep review of 08:40: 12 predicted faults B1 to B12 against the product code, what the rehearsal stand-ins hid, and section F (how to stop it recurring) |
| `chain-review-patches/*.diff.txt` | the review's five patches to lane G's driver (applied in 876ff650), and all five stacked |
| `launches/<run id>/state.json.txt` | the VM's step state: each step's status, attempts, boots, seconds, and how the run ended |
| `launches/<run id>/vm.log.tail.txt` | the VM's own log (every boot, every step start and stop) |
| `launches/<run id>/step-parts/<step>.json.txt` | each step's part result: times, what it recorded, and for a stop the reason and the log's last lines |
| `launches/<run id>/step-parts/<step>.stop-<time>.json.txt` | the part of an earlier attempt of that step, kept when a resume ran it again |
| `launches/<run id>/step-logs/<step>.log.tail.txt` | the last 80 lines of each step's log |
| `launches/box-20261115T085016Z-876ff6506/facts-vm.txt` | the probe's facts: disk, Docker store, python modules, systemd, TPM device, GPU |
| `launches/box-20261115T094747Z-4c7c47017/step-logs/02-install.attempt1.log.tail.txt` | the first install attempt's log: the pin error (F10) and the TPM error (F9) |
| `launches/box-20261115T094747Z-4c7c47017/step-logs/02-install.log.tail.txt` | the end of both attempts: the second one refused as a repeat (F11) |

The VM's folders `logs/` and `parts/` are named `step-logs/` and `step-parts/` here (the repository ignores the
first two names).

Not included: the box's facts file of the install launch (it lists the box's settings file), the gates' full JSON
records, and the step notes (their content is in the part files).
