# Offline media layout (D-125, D-138)

The Windows workstation never reaches the internet, at install or after (D-125). Everything comes on one USB disk
or a hospital file share, made by Aimedics from a signed release. This is the layout the offline installer will read;
the installer itself is built after the platform (after plan v4 step 9). Until then an Aimedics engineer follows
`WINDOWS-INSTALL-CHECKLIST.md` with these files.

```
TRIALBOX-<version>/                      one folder per release, read-only on the disk
  README.txt                             version, date, sha256 of every file below, who built it
  SHA256SUMS                             sha256 of every file; SHA256SUMS.sig: Ed25519 by the vendor key
  windows/
    preflight.ps1                        deploy/windows/preflight.ps1
    wsl/wsl.<version>.x64.msi            WSL itself (the Store is not used)
    wsl/ubuntu-24.04-wsl-amd64.tar.gz    the Linux root file system, imported with `wsl --import`
    wsl/wslconfig.template               .wslconfig: memory, swap=0, processors
    nvidia/<driver>-win11-win10-...exe   the NVIDIA Windows driver (WSL2 uses it; no Linux driver)
  linux/
    debs/                                Docker Engine, compose plugin, nvidia-container-toolkit, nftables, cron,
                                         and their dependencies, for Ubuntu 24.04 (apt-get install ./*.deb)
    trialbox-<version>.tar               the signed bundle of tools/make_bundle.sh (below)
    trialbox-<version>.tar.sha256
    vendor_ed25519.pub                   also given out of band; the installer compares both
  measured/
    serving_config.<gpu>.json            the vendor's serving record of each tier's card (tools/tiers.py)
  docs/
    network-sheet.{en,ja,zh-TW}.html     docs/handover/, printed for the hospital's IT
    RUNBOOK.pdf, WINDOWS-INSTALL-CHECKLIST.pdf
```

**The bundle** (`trialbox-<version>.tar`, `tools/make_bundle.sh`, verified by `tools/verify_update.py`; D-125
estimated 30 GB, the sizes below make it nearer 40 GB, so plan a 128 GB disk):

| Kind | What | About |
| --- | --- | --- |
| `image` | `trialbox-py`, `trialbox-jvm` (`docker save`), Postgres, HAPI, vLLM, all digest-pinned | 12 GB |
| `model` | the pair's weights: judge Gemma 4 26B-A4B 4-bit (17 GB), verifier Qwen3.5-9B 4-bit (7.5 GB); bge-m3 (2 GB) | 27 GB, the same files for every tier |
| `ruleset` | approved rulesets (zip), imported with the approval and equivalence gates | < 10 MB |
| `host` | the host tree, `trialbox-host.tar`: the compose files, the host tools (`tools/`, `libs/`, `schemas/`) and the release's configuration (Caddyfile, `db-init`, `egress.py`, `network.sh`, `images.lock`, measured serving records), with its own `HOST-SHA256SUMS` (T-631, D-367) | < 10 MB |
| `other` | wheels of the host tools (`cryptography`, `psycopg`, `pyyaml`) for `python3 -m tools.trialbox` | < 50 MB |

Python wheels the services need are inside the images; nothing is installed from PyPI on site. An update is the
same `linux/trialbox-<version>.tar` on a new disk, applied with `tools/apply_update.sh` (backup first, rollback on
failure; RUNBOOK §5).

**The host tree on the box** (T-631, D-367). Compose files, host tools and configuration come only from the signed
bundle, and an update changes them. The copy of the release on the media is only the bootstrap that runs
`deploy/install.sh` the first time. The installer verifies the bundle, unpacks its host tree and then runs again
from the signed tree. The install folder then looks like this:

```
/opt/trialbox/
  releases/<bundle id>/        the host tree of each installed release, exactly as signed
  releases/.replaced-<time>/   files of the copied bootstrap that the signed tree replaced (kept, never deleted)
  current -> releases/<bundle id>
  tools, libs, schemas, ...    links to current/...
  deploy/                      the site's own files: .env, settings.yaml, secrets/, keys/, updates/, refdata/,
                               models/, site/, ops/, logs/, backups/, image-pins.json, pgbackrest/repo
  deploy/docker-compose.yml    ... and every other release file of deploy/: links to ../current/deploy/...
```

An update unpacks its tree to `releases/<bundle id>` and switches `current` before the restart. The restart and the
health check therefore run the new compose files. Any failure switches `current` back before the services start
again. A changed byte anywhere in the tree on the disk is refused at the signature check, and nothing is staged.
`python3 -m tools.host_tree status` names the current release and checks it against its `HOST-SHA256SUMS`. A box
whose verifier is older than manifest 1.3.0 refuses kind `host`. Install the first such release with
`deploy/install.sh`.
