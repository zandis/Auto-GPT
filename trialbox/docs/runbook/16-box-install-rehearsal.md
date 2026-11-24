# 16. Box-install rehearsal: the gate before a site's IQ

**Reader:** the people who build TrialBox.

Before any site's installation qualification (IQ), and before a release goes on a site's media, run
`make rehearse-box` on any Docker host (no GPU; the network only to build the images; D-176). A
FAIL stops the release: no site visit until it passes. Keep `report.md` with the release record.

**What it does.** It makes offline media the way the vendor does: a bundle signed with a throwaway vendor key
(`tools/make_bundle.sh` with the images, placeholder weights for the large tier's pair and the reference data pack),
the release tree, the vendor key and `SHA256SUMS`. It removes the box images from the Docker host, so only the media
can bring them back. Then it runs the real `deploy/install.sh --tier large` inside a clean Ubuntu 24.04 container
(`tools/rehearse_box/host.Dockerfile`: Docker CLI and compose, python3, nftables, cron). An `nvidia-smi` stand-in
names one RTX PRO 6000. The two model servers are the strict vLLM stand-in `tools/vllm_standin.py`
(`tools/rehearse_box/standins.yml`, given as `TB_COMPOSE_OVERRIDE`). The stand-in takes vLLM's command line from the
profile's compose file. It answers only the exact served name (404 otherwise, as vLLM) and refuses every `/v1` call
without the key (401). It never starts without a key (D-177).

**What must pass** (each is a step in the report):

| Step | Proves |
| --- | --- |
| `wsl2` | `deploy/windows/preflight.sh` passes on a WSL2-like host (WSL2 kernel, systemd, Windows build through a `cmd.exe` stand-in) and fails on plain Linux. Windows itself (`preflight.ps1`, BitLocker, `wsl --import`) cannot run here: do it on a Windows test machine before a Windows site. |
| `media-negative` | missing media ("no such bundle"), a forged bundle ("not a valid signed TrialBox release") and a missing vendor key each stop the installer, and nothing is written |
| `install` | the installer exits 0: bundle verified and loaded, settings, the model key, the pins, the stack healthy, the serving check |
| `doctor` | `trialbox doctor --live` passes, with the `serving` check (below) |
| `served` | the pinned served names in `deploy/site/registry.site.yaml` are exactly what the two servers serve |
| `offline` | every running container runs an image the bundle loaded, the third-party ones (`postgres`, `hapi`) too, and the Docker daemon pulled nothing; the CQL translator jars in `criteria-compiler` are byte for byte the vendor's and translate; the media's reference data pack is loaded; ClinicalTrials.gov is offline; the box has no route out |
| `egress-override` | no route out of the box **with the rehearsal's own internal `egress-net`** (`tools/rehearse_box/standins.yml`). The shipped `egress-net` with `deploy/network.sh` is not rehearsed (no `NET_ADMIN`): check it at the site's IQ |
| `guard` | on `model-net` only `model-guard` answers to the model servers' names: `/invocations`, `/collective_rpc`, `/metrics` and the rest are 404 with or without the key, `/v1` and `/tokenize` need the key, nothing reached the stand-ins' open routes, and the servers are only on `trialbox-model-backend` |
| `console` | the console answers `/healthz` and its sign-in page; inside it no outside name resolves and no outside address answers, while the box's own names do (`console-net`, below) |
| `screen` | SCREEN GZQO on synthetic hospital A ends `done`, its model calls go through the gateway to both pinned builds, with no 401 and no 404, and it mails its results to the site's relay (a plain SMTP sink, `tools/rehearse_box/smtp_sink.py`, stands in for it) |
| `power-cycle`, `after-restart` | every box process killed (as in a power loss), the host restarted: the box comes back healthy with its data, the doctor passes, the console answers, a second SCREEN runs |
| `wrong-name` | a server that serves another name than the pin: the doctor (the installer's check) FAILs and names both, and the gateway refuses the call |
| `missing-key` | the gateway without the key: the doctor FAILs with "refused the key (HTTP 401)", and both calls are refused |
| `no-registry-pull` | the Docker daemon's image events, from the moment the images were removed to the end of the run: every bundle image loaded, no pull |

**Knobs.** `TB_REHEARSE_DIR` (default a fresh private `mktemp` folder; a given one must be absolute, three levels
deep, not a system folder, and new or this user's earlier rehearsal folder; the report and logs stay there),
`TB_REHEARSE_SKIP_BUILD=1` (use the images already built), `TB_REHEARSE_KEEP=1` (leave the box running for a look),
`TB_EXTRA_CA` (a PEM for apt and pip behind a TLS proxy), `TB_REHEARSE_VARIANT=validation` (D-887: a root-owned
`deploy/site` and the same bundle installed twice). Every rehearsal box is VALIDATION (D-887, so that SCREEN's D3
note checks reach both pinned builds on the box) and runs as a validation run on a plain VM: the passphrase KEK with
no TPM and the poc host profile; it mounts the Docker host's `/run/trialbox` and volumes folder in the box
container, as on a site's host. Its doctor step names what only a site's host has (`clock`, `ops_runner`,
`audit_heads`) as not reached by a rehearsal and fails on any other FAIL. CI runs both variants by hand and on every pull
request that touches the installer (`.github/workflows/trialbox-rehearse-box.yml`); its `rehearse-result` check passes
when they passed or were skipped (no installer change), so a branch rule can require it (D-891). It needs a Docker
host with no other TrialBox stack and port 8090 free. The box container uses the host's Docker through its socket, so the work folder has the same path inside.
`DOCKER_HOST=unix:///path/docker.sock` rehearses on another daemon. Run it on both Docker image stores before a
release: the containerd store (the default of new Docker installs) and the classic `overlay2` store (older hosts,
and hosts upgraded from them). The classic store keeps no image digests (below).
At the end it removes the box, its volumes and the media, and loads the images back from the media if a failed run
left them removed.

**Not rehearsed** (do these at the site's IQ): a real GPU, driver and model weights (the canary and the serving
record, §8); the egress rules (`deploy/network.sh apply` needs `NET_ADMIN`, which the rehearsal does not give: the
rehearsal makes the outbound network internal instead); LUKS, TPM, swap and the other host hardening lines of
`deploy/check_host.sh`; the bge-m3 embedder (the hash embedder runs instead); the hospital's mail server (a sink without TLS stands in).

**Images come only from the bundle** (D-176). `install.sh` starts the stack with `--pull never` and first checks
that every image of the stack is on the box: a missing one stops the install with its name, and nothing is pulled.
The compose files pin `postgres` and `hapi` by digest. Docker's containerd image store keeps that digest when the
bundle is loaded; the classic `overlay2` store does not, so `tools/image_pins.py` points the image's compose variable
(`POSTGRES_IMAGE`, `HAPI_IMAGE`) in `deploy/.env` at the image id the signed bundle names (`image-pins.json`; an
image id is its content). Updates do the same before they restart the box. A site that mirrors the third-party
images itself (`make_bundle.sh --no-third-party`) sets `TB_INSTALL_PULL=missing`, and a variable it set to its own
mirror is left alone.

**`console-net`** (D-176). Docker publishes no port of a container that is only on internal networks, so the
console is also on `trialbox-console`, which is not internal. It is closed by hand: no NAT out (no reply ever comes
back from outside), no IPv6, published ports on 127.0.0.1 unless `TB_CONSOLE_BIND` says otherwise, and the console
sends outside names to an address that is never assigned (`dns: 192.0.2.53`; the box's own names still resolve).
Without NAT a packet from the console can still leave the host, though no answer comes back: `deploy/network.sh
apply` (run by `install.sh` as root) drops it. Keep the egress rules applied on every box. `network.sh` also drops
every connection into a box network that is not to a published port (a neighbour on the hospital LAN that routes to
a container address directly, possible on Docker before 28).

**`model-guard`** (D-177). vLLM checks its key only on paths under `/v1` (and `/v2`, `/inference`, `/cohere`).
`POST /invocations` (chat), `/tokenize`, `/score`, `/pooling`, `/metrics` and, in dev mode, `/collective_rpc` answer
without it. So the vLLM servers are only on `trialbox-model-backend`, and `model-guard` (`services/model_guard`) is
what `llm-service` and `llm-verifier` mean on `trialbox-model-net`. It passes, with the key only, `GET /v1/models`,
`POST /v1/chat/completions`, `POST /v1/completions` and `POST /tokenize` (D-739: G-1 counts tokens on the shipped
server; the key already opens chat completions, which do more); on the RTX 5090 profile also the gateway's `/sleep`,
`/wake_up` and `/is_sleeping`; and `/health` without the key. Everything else is 404. `trialbox doctor --serving`
also checks that `/invocations` and `/tokenize` refuse a call without the key.

**The host itself.** `deploy/network.sh apply` also drops every new connection from a box network to the host
(sshd, a database), except an allowed destination that is on the host.

**The model key** (D-177, D-437). `trialbox secrets init` (run by the installer) writes the key to
`deploy/secrets/model/llm.key` (0600), taking the `TB_LLM_API_KEY` that `install.sh` or an older box put in
`deploy/.env`. The secrets overlay gives the file to the gateway and model-guard only, as a compose secret
(`TB_LLM_API_KEY_FILE`), and clears `TB_LLM_API_KEY` in every container. The vLLM servers read their own env file
`deploy/secrets/model/vllm.env` (`VLLM_API_KEY`), which `trialbox secrets` writes with the key file (D-450); the copy
in `deploy/.env` reaches no container under the overlay and is kept equal to the file. Only the gateway sends the
key (`models/routing.yaml`, endpoints `serving` and `verifier`). After the stack starts, the installer runs `trialbox doctor
--serving` on the model network and stops when a server is down, refuses the key, does not serve a pinned name, or
answers without the key in PRODUCTION. An update (`trialbox update`) makes the key on a GPU box that has none and runs
the same check after the restart (reading the key file); a FAIL rolls the update back; on a GPU box or one with
per-service tokens it also makes the key file and `vllm.env` from `deploy/.env` when they are missing. The rehearsal's
`missing-key` drill empties the key file, not `deploy/.env`, because that is what the gateway reads. To change the key: `trialbox secrets rotate --service model` (the old key
is refused from then on). Do not change the key in `deploy/.env` by hand: the gateway and model-guard read the file.

**The box form** (T-729, D-466; developer note: the owner's set-up page is T-735's). A box (a GPU workstation or a
DGX Spark, plan v6.1 OD-11) is installed by `sudo deploy/box-install.sh trialbox-<version>.tar`, a thin script over
`install.sh`: it detects the machine (`python3 -m tools.box detect`), asks only whether that is the machine, plans
the settings from the hardware (`tools/box/plan.py`: the GPU profile from `deploy/gpu_profile.sh`, the memory caps
from the RAM, TLS `internal` under the box's name, `deploy/site/hardening.conf` with the KEK on the TPM or, without
one, a passphrase the owner sets), runs `install.sh` with `TB_BOX=1` (the overlay `deploy/docker-compose.box.yml`,
no `bootstrap-admin`), prints the address `https://<name>.local/login/first-run`, shows a one-time code once, and
waits. The owner answers the first-run wizard
(site name, time zone, language, their account and authenticator, the box's name, where backups go, the kind of data
source); the console makes the owner's accounts (steward and `<name>-admin`) and hands the answers over the tmpfs
folder `/run/trialbox-firstrun`; the script then applies them (`python -m tools.box apply` in the image: settings
and `deploy/.env` rewritten from the answers, the install's passwords kept), sets the host's zone, restarts the stack,
installs the backup schedule and runs the host check. On a box the inner install does not stop when the backup
schedule cannot be installed yet (a fresh host has no alert route): it is a line in the install's FAIL list, the
stack runs and the wizard is served (OPS-003, D-566); `install.sh` without `TB_BOX` still stops there.
Under WSL2 (the Windows form; the script reads the kernel's release) the host's time zone is left to Windows (D-571).

**Where the one-time code is** (H-97; the integrator's ruling 7101844662). The code is never in the script's output
(the boot's `trialbox-firstrun.service` sends that output to the system journal, and `install.log` keeps the install's)
and never in a file other users can read; `/etc/issue.d` is no longer used, and an earlier version's
`/etc/issue.d/trialbox-firstrun.issue` is removed. The person at the box gets it this way:

- **At a terminal** (`sudo deploy/box-install.sh <bundle>` typed on the box, or over SSH with a terminal): on that
  terminal, once, under the address. The output piped to a log holds only "shown on this terminal only".
- **The Windows form (WSL2):** in the Windows installer's window, which is the script's terminal.
- **A prepared box's first boot, at a physical console:** on the box's screen (the text console, written directly,
  not through the journal), and in `/root/trialbox-firstrun-code`.
- **A headless box, or a desktop whose screen shows the graphical login:** over SSH, `sudo cat
  /root/trialbox-firstrun-code` (root only, mode 0600; the output names the file, never the code).

The file is made new for each code (a link or anything but a regular file at its name is refused, never followed)
and is removed when the owner's answers are in. Five wrong codes void a code: a new code replaces the file and is
shown again. With no terminal, no screen and no such file the script stops and says to run it on a terminal.
When the answers are applied the script writes `deploy/site/box/applied`; a start that finds it (the window
closed before the last line) shows no new code and finishes the set-up (D-576).
**A rehearsal box** (D-726, D-887). `deploy/install.sh <bundle> --rehearsal` (or `deploy/box-install.sh <bundle>
--rehearsal`, which hands it on) makes a box that says it is a rehearsal: it is TEST from before the bundle loads (the
mark `deploy/site/rehearsal.json`, recorded in `deploy/updates/installed.json`), and deploy/.env then gets
`TB_ENV=VALIDATION` and `TB_REHEARSAL=1` (VALIDATION keeps D3 on the box, so SCREEN reaches the pinned builds). The
installer refuses it on a PRODUCTION box, on a VALIDATION box without the mark, and on a box whose Docker volumes
hold data from no rehearsal. The model stand-ins (`tools/rehearse_box/standins.yml`, the default override of a
rehearsal; `TB_COMPOSE_OVERRIDE=` set empty keeps the real model servers, for an unmeasured card's trial boot) and
`TB_ACCEPT_UNMEASURED_GPU=1` work on a rehearsal box only. `trialbox doctor` carries the standing line "REHEARSAL BOX:
placeholder models, synthetic data only" (WARN), the console's banner says `VALIDATION REHEARSAL`, qualify and
`pin_model --promote` refuse on it, and the doctor fails a rehearsal mark on any other box. A bundle built with
`tools/make_bundle.sh --rehearsal` says `"rehearsal": true` in its release.json; a PRODUCTION box, and a VALIDATION
box without the mark, refuse it at install and at update. A rehearsal box never becomes a site box: before a site's
install on the same machine, empty it: `docker compose --project-directory deploy down -v`, then remove what the
rehearsal's install wrote: `deploy/.env`, `deploy/settings.yaml`, `deploy/updates/`, `deploy/secrets/`,
`deploy/site/registry.site.yaml` and `deploy/site/rehearsal.json` (keep `deploy/site/serving_config.<profile>.json`
from a trial boot). Until the mark and `TB_REHEARSAL=1` are gone, `deploy/install.sh` without `--rehearsal` refuses the
box, and doctor fails the stand-ins in the compose files of any box that is not a rehearsal box.

**Prepared image:** Aimedics runs the same script with
`--prepare` before shipping; it stops before the code and enables `trialbox-firstrun.service`, which at the site's
first boot runs `deploy/box-install.sh --firstrun` (the code on the screen and in the root-only file, the wizard, the
apply). The rehearsal of
this path without Docker is `tests/console/test_box_install_rehearsal.py` (the real script, stand-ins for the inner
install, compose and the host check, the wizard in process); what only a real box proves is listed in D-466 for
T-213b's rental-workstation and Spark runs.

**Unattended (D-898):** `sudo deploy/box-install.sh trialbox-<version>.tar --answers owner.json` installs a box with no
question, no first-run code and no wait. Use it for the hospital's own unattended install, or for a run on a VM.
- `owner.json` holds the first-run form's fields:
  - `site_name`, `tz`, `language`;
  - `owner_full_name`, `owner_username`, `owner_email`;
  - `box_name`;
  - `backup_kind` with `backup_disk` or `backup_share`;
  - `source`;
  - optionally `chartno_rule`, `mta_authserv_id`, and `environment` (`PRODUCTION`, or `VALIDATION` for public or
    synthetic data).
- The plan is made from that file. The install then makes the first administrator as the IT form does: the password
  and enrolment code are shown once on the terminal, never in `deploy/site/box/install.log` (H-96); with no terminal
  they are in `/root/trialbox-admin-first-sign-in` (root only), to read once, hand on and remove.
- After the install it sets the host's time zone, installs the backup schedule and runs the host check.
- A password or passphrase in the answers file is refused.
- A file that does not parse changes nothing.
- It cannot be combined with `--prepare`, `--rehearsal` or `--firstrun`.

Without a usable TPM, set `bundle` to the signed bundle’s path. The KEK passphrase (12 characters or more, one
line) goes in a file only root can read: after sudo's own password prompt, type the passphrase, then press Enter
(nothing is shown). The file must be a regular file owned by root with mode 0600; the install removes it once the
keys are sealed (`--keep-kek-passphrase-file` keeps it). Instead of the file, `--kek-passphrase-stdin` asks for the
passphrase twice on the terminal.

```bash
sudo bash -c 'umask 077; IFS= read -rs TB_KEK_PASSPHRASE; printf "%s\n" "$TB_KEK_PASSPHRASE" > /root/trialbox-kek.pass'
sudo deploy/box-install.sh "$bundle" --answers owner.json --kek-passphrase-file /root/trialbox-kek.pass
```

A passphrase in the environment (`sudo --preserve-env`, `sudo -E`, a root shell that exported it) is refused by
`box-install.sh`, `install.sh`, the bootstrap, `seal_keys.sh` and `tools.keys` (H-96): sudo writes a variable it
keeps, with its value, to the system journal. A box installed that way before H-96 rotates its passphrase (§23,
"Rotate the KEK passphrase"). This refusal stands on every box, a proof of concept too: it protects a key.

**The box's name (OPS-005):** a box named `<name>.local` answers that name on the clinic's network.
- `hardening.conf` says `MDNS=on`, and the input firewall then lets mDNS (UDP 5353) in from the box's own network only.
- The apply step sets the host name to the owner's choice and starts `avahi-daemon`. When the responder is not
  installed, it says so.
- The first-run screen also prints the box's address, for a computer that cannot resolve `.local`. The browser then
  warns, because the certificate names the box, not its address.
- A box with a name in the hospital's DNS keeps `MDNS=off`.

**A bare Ubuntu box from the media (OPS-006, D-966):** a machine with only Ubuntu 24.04 on it gets Docker, the NVIDIA
driver and toolkit and the host's libraries from the offline media, not by hand.
- The vendor builds the media: `python3 -m tools.linux_media debs` (online, on any Debian or Ubuntu machine) collects
  the packages; `make media-linux MEDIA_ARGS="..."` lays out `dist/media/TRIALBOX-<version>/`; `python3 -m
  tools.linux_media sign` signs its `SHA256SUMS` on the signing machine; `python3 -m tools.linux_media check` reads it
  back before it leaves.
- On the box: `sudo bash <media>/linux/box-prepare.sh <media> --pub <the vendor key given apart from the disk>`. It
  refuses another system, a key other than the one given, a bad signature, a changed byte and an unlisted file before
  it installs anything; then it installs the packages, starts Docker with the nvidia runtime and puts the host tree in
  `/opt/trialbox`. It prints what to run next: a restart when the driver is not loaded yet, then
  `sudo /opt/trialbox/deploy/box-install.sh <media>/linux/trialbox-<version>.tar`.
- `box-install.sh` on a machine without Docker says to run this step first.
- The disk's unlock rule (HW-010) is not set here: it waits on the owner's decision. The run on a real bare box is
  T-213b's.

## A rehearsal with the real model servers (H-89, D-1087)

On a bench host whose cards and driver are not the rtxpro6000 profile's, the install walk can run the real model
servers on one whole card, as a rehearsal box only (it says "rehearsal: driver below the minimum, not this profile's
card, not valid for a site" and never starts as PRODUCTION). Reload the driver first (skip it when the driver was
loaded just now and nothing has used the card since, as after a fresh boot), then, as root:

    sudo install -d -m 0700 -o root -g root /var/lib/trialbox/rehearsal
    sudo python3 tools/engine_probe.py run --gpu-index 1 --out /var/lib/trialbox/rehearsal/engine-probe.json
    sudo deploy/install.sh trialbox-<version>.tar --rehearsal --rehearsal-real-servers --gpu rtxpro6000 \
        --gpu-index 1 --engine-probe /var/lib/trialbox/rehearsal/engine-probe.json --yes

The probe file and its folder must be root's and writable by no one else; a probe of another card or host, older than
7 days, or of another image is refused. The page: docs/handover/rehearsal-real-servers-h89-2026-11-22.md.

Each opened profile is held to its own card's memory on the bench's card (its utilisations scaled into deploy/.env):
`--gpu rtxpro6000` (96 GB) or `--gpu rtx5090` (32 GB, a whole card), with `--gpu-index N` naming the card the probe was
taken on. The 32 GB profile on a split card's slice, dgpu48, gb10 and the Windows (WSL2) host are not opened; the
page says why.

## Several test boxes on one host (H-106)

"One box per host" is a production rule. On a test host (the bench host's eight cards) several TEST boxes run side
by side, each installed by the real installer with `--test-box NAME --port-offset N`, each with its own folder,
compose project (`tbt-<name>-<6 hex of its folder>`), networks and volumes (its site keys among them), published
ports (each base port plus 10 x N: the console at 8090 + 10N), cards (`--gpus`) and memory cap a card
(`--gpu-mem-gb`). Three commands, run as root from any release folder (`tools/testboxes.sh`):

```sh
# 1. bring up boxes from one signed bundle: NAME:OFFSET[:CARDS[:GB[:PROFILE]]], one after another
sudo tools/testboxes.sh up <bundle>.tar --pub <vendor key> --answers <answers>.yaml \
  walk:1:0 p32:2:1:32:rtx5090 p48:3:2:48:dgpu48 p96:4:3:96:rtxpro6000
# 2. list every box on this host (name, project, folder, console port, cards, cap)
sudo tools/testboxes.sh list
# 3. remove one test box whole: its containers, networks, volumes and folder (without --yes: what it would remove)
sudo tools/testboxes.sh remove p48 --yes
```

Each box goes to `/opt/trialbox-test/NAME` (`--parent` moves it); its output is `/opt/trialbox-test/NAME.install.log`.
A box's own commands: `sudo trialbox --box NAME doctor` (with more than one box on a host, `trialbox` without
`--box` refuses to guess), or `cd /opt/trialbox-test/NAME && sudo python3 -m tools.trialbox doctor`.

What a test box is, and is not:

- **It says so** on every console page (the banner "TEST TEST BOX NAME: one of several boxes on this host"), in
  `trialbox doctor` (a standing WARN line "TEST BOX NAME: ...") and in the install's last lines.
- **TEST only.** `--test-box` with `--environment PRODUCTION` or `VALIDATION` is refused; a folder installed as
  anything else is never made a test box; a test box is never installed on a host that holds a PRODUCTION box.
- **PRODUCTION is unchanged:** a PRODUCTION install refuses a host where a test box runs (read from the container
  engine, whatever any variable says), and still refuses a second ordinary box as before.
- **Its secrets are its own:** its site keys are never sealed (the KEK folder and the host baseline are the host's);
  `TB_SECRETS_HOST_DIR` and `TB_KEK_BACKEND` are refused; its first sign-in file is
  `trialbox-admin-first-sign-in-NAME`.
- **Nothing of the host's is its:** no `trialbox` command on the PATH, no systemd unit or timer, no cron file, no
  logrotate file, no egress table. A test box does not come back by itself after a reboot: run `up` again, or
  `docker compose --project-directory /opt/trialbox-test/NAME/deploy up -d`. It has no backup: `trialbox backup`,
  `restore`, `restore-drill`, `logs` and the platform commands are refused on it (they name the ordinary box's
  volumes); a test box is removed and installed again.
- **The memory cap is the serving engine's,** not the container engine's: each model server's
  `--gpu-memory-utilization` is scaled so that it asks its card for what it would ask of a card of the cap. Docker
  has no per-container card memory limit. The cap is shown only on the bench host's own cards.
