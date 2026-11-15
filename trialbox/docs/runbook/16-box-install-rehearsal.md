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
request that touches the installer (`.github/workflows/trialbox-rehearse-box.yml`). It needs a Docker host with no other TrialBox stack and port
8090 free. The box container uses the host's Docker through its socket, so the work folder has the same path inside.
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
no `bootstrap-admin`), prints the address `https://<name>.local/login/first-run` and a one-time code (also on the
box's own screen, `/etc/issue.d/trialbox-firstrun.issue`) and waits. The owner answers the first-run wizard
(site name, time zone, language, their account and authenticator, the box's name, where backups go, the kind of data
source); the console makes the owner's accounts (steward and `<name>-admin`) and hands the answers over the tmpfs
folder `/run/trialbox-firstrun`; the script then applies them (`python -m tools.box apply` in the image: settings
and `deploy/.env` rewritten from the answers, the install's passwords kept), sets the host's zone, restarts the stack,
installs the backup schedule and runs the host check. On a box the inner install does not stop when the backup
schedule cannot be installed yet (a fresh host has no alert route): it is a line in the install's FAIL list, the
stack runs and the wizard is served (OPS-003, D-566); `install.sh` without `TB_BOX` still stops there.
Under WSL2 (the Windows form; the script reads the kernel's release) the address and the code are
printed and not written to the box's screen file, and the host's time zone is left to Windows (D-571).
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
first boot runs `deploy/box-install.sh --firstrun` (the code on the screen, the wizard, the apply). The rehearsal of
this path without Docker is `tests/console/test_box_install_rehearsal.py` (the real script, stand-ins for the inner
install, compose and the host check, the wizard in process); what only a real box proves is listed in D-466 for
T-213b's rental-workstation and Spark runs.
