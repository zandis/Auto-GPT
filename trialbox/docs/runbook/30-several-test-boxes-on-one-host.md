# 30. Several test boxes on one host

**Reader:** the people who build TrialBox, on the bench host (card H-106; the owner's ruling, relayed as
7117794599). Synthetic data only: a test box never holds a site's patients.

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
`--box` refuses to guess), or `cd /opt/trialbox-test/NAME && sudo python3 -m tools.trialbox doctor --env-file deploy/.env`.

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
