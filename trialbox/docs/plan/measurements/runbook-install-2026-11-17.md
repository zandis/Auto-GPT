# Install from the bundle by the runbook alone, 2026-11-17 (card H-22, D-1136)

**Reader:** the integrator, and lane D, who own the installer, the bundle and the install runbook

**Verdict.** The runbook alone does not install the box. A reader stops at the one command (§1 line 28) because
`deploy/install.sh` is not on the machine: neither the hub nor §1 says how `/opt/trialbox` gets the release's host
tree. After that stop the follower went on only by named lifts (D-1136, 6). It then met five more stops: two in the
runbook, one in the bundle, one in the installer, and one from the machine (no TPM). The last was on a PRODUCTION box
without a GPU (`--mode stub`, the runbook's own words for such a machine): every service became healthy except
`embed-service`, which refuses to start with no pinned embedder, and the installer pins models only in GPU mode.

## What was followed

- The RUNBOOK hub's opening (`docs/RUNBOOK.md`: "Commands run on the box from `/opt/trialbox` as root unless noted")
  and §1 (`docs/runbook/01-install-a-new-site.md`) at commit `c1cb24aa` (master `57263236` plus this card's
  tool; §1 and the hub are master's).
- The extraction rule, the install path and what the follower may supply: D-1136. `python -m tools.runbook_install
  extract` lists §1's 27 commands with their places; `plan` lists the path.
- The path runs 3 of §1's 27 commands: the one command, step 4's mapping check and step 7's first ingest. It also
  places one file (step 6's vendor key) and checks one output (step 7's report). The other 24 commands are not needed
  by the path, each for the runbook's own reason (`run-container.json`, `not_needed`). For example, steps 2, 3, 5 and
  8 are done by the installer, per the one command's paragraph.

## Where it ran, and what did not run

| Machine | What it is | Ran |
| --- | --- | --- |
| `unit` | `tests/unit/test_runbook_install_follow.py`: a folder for `/opt`, a stand-in `docker` that serves nothing past the host checks, a signed bundle of this checkout's host tree | every test run (3 s); stops when the bundle has no images (a machine stop) |
| `container` | the box rehearsal's own clean host image (`tools/rehearse_box/host.Dockerfile`: Ubuntu 24.04, docker.io 29.1, compose, python3 with PyYAML and cryptography, nftables, cron, curl), started as the rehearsal starts it (the host's Docker through its socket, `--network host`); `/opt/trialbox` empty; the stick at `/media/usb` read-only; the console's name `trialbox.hospa.test` in the machine's hosts file (the site's DNS) | `make runbook-install` once, with the bundle below: 8 commands, 189 s |
| `vm` | a clean VM | **not run** (no cloud here): the request is at the end |

The bundle came from the box's images, made the vendor's way: `make images` from this checkout, then
`make release-gates` over the seven images a box without a GPU runs (`bundle-check: PASS (7 images)`), then
`tools/make_bundle.sh` from the commit, with the reference data pack and without `--allow-dirty`. The result:
`release check: PASS ... gates block`, 2.5 GB. The box images were then removed from the Docker host, so only the
bundle could bring them back; the teardown loads them back. Not in this bundle: the vLLM image and model weights (no
GPU here) and the embedder's weights (2.3 GB, not fetched).

Not run in the container, because a container cannot have them: a GPU (the one command's `--tier large` stops with
exit 3, as §1 says it should); a TPM and LUKS (step 1 names both: the machine stop `no-tpm`); systemd; the egress
table (no `NET_ADMIN`). Not reached, because the install stopped first: steps 4, 6 and 7 (the mapping check, the
vendor key's place and the first ingest). Their findings below are read from the text only.

## Time and commands

| | Value |
| --- | --- |
| §1's commands (the extraction rule) | 27 (24 not needed by the path) |
| Commands the follower ran on the container | 8 (7 attempts of the one command, 1 lift) |
| Wall time of the follow | 189 s |
| The longest attempt (bundle verified and loaded, settings, keys sealed, stack started, health wait) | 112.5 s |
| The attempt that stopped at the TPM (bundle verified and loaded, settings, keys made) | 74.3 s |
| Vendor side: release gates over 7 images, then the bundle | about 5 min, then about 3 min |
| Lifts used, in order | host-tree, drop-tier, vendor-key-first, sidecar-name, no-tpm (machine) |

The record is `runbook-install-2026-11-17/run-container.json` (each attempt's command as written and as run, its
folder, the names of the variables a lift set, its exit, its time, its output with secrets removed). The findings
file is `runbook-install-2026-11-17/findings.json`.

## Findings

Severity: **stops** the install, **slows** the reader, **cosmetic**. "Seen on" names the runs that showed the
finding; "text" means the runbook's text shows it (a check in the tool) and no run reached it.

| # | Place | It says | What happened / what was needed | Kind | Severity | Seen on |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `docs/runbook/01-install-a-new-site.md:28` (and the hub's line 8) | "With the vendor's signed bundle on a USB stick: `sudo deploy/install.sh trialbox-<version>.tar --tier large --answers site.yaml`", from `/opt/trialbox` | `deploy/install.sh: No such file or directory`. The release's host tree must be in `/opt/trialbox` first. The bundle carries it (`files/trialbox-host.tar`), but only the Windows media page (`docs/handover/OFFLINE-MEDIA.md:34`) and the box form (§16) say it is unpacked there | silent | stops | text, unit, container |
| 2 | `01-install-a-new-site.md:111` | step 6: "Install `deploy/keys/vendor_ed25519.pub`, received out of band." | The installer needs the key in its first (host) step: "vendor public key missing: copy vendor_ed25519.pub ... to .../deploy/keys/vendor_ed25519.pub". The one command's paragraph never names the key, and the steps put it after step 5's start | wrong (order) | stops | text, unit, container |
| 3 | `01-install-a-new-site.md:35` | "`--mode stub` installs a box without a GPU." | Added to the one command, the installer refuses it ("--tier needs the GPU: drop --mode stub"). The installer's own exit-3 message, not the runbook, says to install without a tier | silent | slows | text, unit, container |
| 4 | `tools/make_bundle.sh:228` (the bundle, lane D) | `sha256sum "$OUT" \| tee "$OUT.sha256"`, and its closing line says to hand both files over | The sidecar names the bundle by the vendor's `--out` path. The installer checks it from the bundle's folder by bare name, so: "sha256sum: /tmp/.../trialbox-runbook-20261117.tar: No such file or directory", then "install: bundle checksum mismatch". The box rehearsal does not see this because it mounts the media at the vendor's own path | wrong | stops | container |
| 5 | `01-install-a-new-site.md:35` with `deploy/install.sh:506` | "`--mode stub` installs a box without a GPU." | On a PRODUCTION box every service became healthy except `embed-service`: "EmbedderRefused: no pin for e-embed-1 in the site override ... pin them with python -m tools.pin_model --build e-embed-1 --endpoint embed". The installer pins models only in GPU mode, and §1 says nothing of the embedder for a box without a GPU. Then "install: the stack did not become healthy", exit 1 | wrong | stops | container |
| 6 | `01-install-a-new-site.md:28` | the one command, with no `--yes`; §1 names no question | At a terminal the installer asks "Start the stack now with profile <mode>? [Y/n]" (`deploy/install.sh:637`). When the answers lack them, it also asks the ClinicalTrials.gov mode, the console's name and the trial office's mailbox. The follower has no terminal, so its runs cannot see these questions | silent | cosmetic in substance; filed as slows | text |
| 7 | `01-install-a-new-site.md:73` | step 1: "Ubuntu 24.04 LTS on LUKS2 with TPM2 unlock, swap off, Docker Engine 27+, nftables" | The installer also needs the compose plugin and python3 with PyYAML (its HOST-PYTHON check), and curl and cron for its later steps. The rehearsal's clean host installs `docker-compose-v2 python3 python3-yaml python3-cryptography cron curl`. The installer names the first two when they are missing | silent | slows | text |
| 8 | `01-install-a-new-site.md:54` | "A folder with the answers file and the site's mapping beside it" | Where the folder goes is not said. The one command's `--answers site.yaml` is relative to `/opt/trialbox`, so the follower put it there | silent | slows | text |
| 9 | `01-install-a-new-site.md:57` | "The answers name the feed folder on the host (`data_source_host_dir`" | It is not said that the folder must hold an export before the one command, nor who puts it there. A PRODUCTION install stops without the folder | silent | slows | text |
| 10 | `01-install-a-new-site.md:101` | step 4: "check it against an export with `python tools/mapping_check.py --mapping ...`" | Ubuntu 24.04 has `python3` and no `python`. The tool also needs the release's Python packages and `libs/` on the path, which step 1 does not name | wrong | slows | text (not reached) |
| 11 | `01-install-a-new-site.md:112` | step 7: "`docker compose exec adapter python -m adapter.cli run`, or wait for 02:00." | From `/opt/trialbox` compose finds no project. The installer's own closing lines give the working form, `docker compose --project-directory deploy exec adapter python -m adapter.cli run` (`deploy/install.sh:983`) | wrong | slows | text (not reached) |
| 12 | `01-install-a-new-site.md:114` | "Check `/data/lake/ndjson/<date>/ingest_report.json`" | The path is inside the lake's volume, not on the host the reader is on. It is not said how to read it | silent | slows | text (not reached) |

Values the runbook left to the reader, and what the follower used (D-1136, 4): the bundle's path on the stick
(`/media/usb/trialbox-runbook-20261117.tar`); the site's answers and mapping, which are the box rehearsal's synthetic
ones (`tools/rehearse_box/site_answers.yaml`, `tools/rehearse_box/mapping`); `sae_office_mailbox`, which §1 names as
required and those answers lack (`trial-office@hospa.test`); and the feed folder's export (synthetic site A).

What the runbook said and was right about: exit 3 on a machine without the tier's card, the installer's own messages
for the TPM, the vendor key and `--tier` with `--mode`, the bundle verified and loaded with nothing pulled, the
settings from the answers, and the site keys sealed (under the passphrase back end once the machine had no TPM).

## How the test can fail

`tests/unit/test_runbook_install_follow.py` holds the following:

- The extraction equals T-632's `commands()`, on §1 and on a fixture.
- Every quote that makes a step of the path is still in the runbook, and every command off the path has the
  runbook's reason.
- Every finding's quote is still in its file.
- The text checks show exactly the findings marked static.
- The unit machine's run shows exactly the committed findings of `unit` for the steps it reached.
- The committed container record matches the file, and holds nothing `redact` would change.

So a fix to §1, `install.sh` or `make_bundle.sh` that removes a finding fails the test until the file says so. A new
silence on a step a run reaches also fails it until the file holds it. `make runbook-install` makes the same comparison
for the container run and exits 1 on a difference.

## The request for a clean VM (the integrator's decision)

The container cannot measure what a real machine adds: a systemd boot, a real TPM2 (`systemd-creds`), the egress
table and the GPU tier. Two shapes are useful; neither is needed to read the findings above. The second is the
honest measurement of the runbook's own command.

| | A: no GPU (`--mode stub`) | B: the runbook's own `--tier large` |
| --- | --- | --- |
| Machine | e2-standard-4 (4 vCPU, 16 GB), Shielded VM with vTPM, Ubuntu 24.04 LTS, 60 GB pd-balanced, asia-east1 | g4-standard-48 with one RTX PRO 6000 (the `tb-gpu-sim` shape), Ubuntu 24.04 |
| Why this size | §1 names no CPU, memory or disk; this is the smallest shape the repository prices (`deploy/gcp/demo_vm.py`) and it holds the 2.5 GB bundle, the loaded images and the stack | the large tier's card (§1's table) |
| Hours (cap) | 2 | 2 (`tools/complete_run.py`: `BOOT_HOURS` 0.25 to boot, the install about 5 min on that VM per `docs/handover/gpu-vm-handover-2026-11-16.md`, the bundle load 10 to 20 min per the installer) |
| Estimate | US$0.1528 an hour on demand (`deploy/gcp/demo_vm.py`, "from memory; not checked against the pricing page", 2026-11-13): US$0.31, plus disk about US$0.02 and an IPv4 address US$0.01: **about US$0.34** | US$2.74 an hour spot (`tools/complete_run.py` `PRICE_PER_HOUR`): **US$5.48**; on demand US$8.22 an hour: US$16.44 |
| Expected outcome today | stops at finding 5 unless lane D has pinned the embedder in stub mode (it needs the embedder's weights in the bundle) | needs a site bundle with the vLLM image, the pair's weights and the embedder (lane G's R2 bundle), not the one built here |

The commands the integrator would run (A; for B the same with the GPU bundle):

```sh
# on a build machine (no cloud): a site bundle made the vendor's way from a clean commit, with a throwaway key
make images && make trivy-db
PYTHONPATH=libs:services:. .venv/bin/python -m tools.runbook_install bundle --py .venv/bin/python
# copy to the VM: the bundle, its .sha256 (as the vendor hands it over), the key, and a checkout of the commit
# on the VM, as root, with /opt/trialbox absent:
sudo apt-get install -y python3-yaml          # the follower's own needs; the runbook's are not pre-installed
cd <checkout>/trialbox && sudo python3 -m tools.runbook_install follow --machine vm \
    --bundle /media/usb/trialbox-<version>.tar --vendor-pub <key> --out /tmp/run-vm.json
sudo python3 -m tools.runbook_install compare /tmp/run-vm.json
```

What to send back: `/tmp/run-vm.json` and the compare output (every finding seen on the VM is listed as "now shows
on vm" until the findings file names `vm`; that list is the result). The record holds no secret: `redact` drops the
administrator's password and enrolment code and every value printed after a secret's name. The VM must be deleted
after the run.
