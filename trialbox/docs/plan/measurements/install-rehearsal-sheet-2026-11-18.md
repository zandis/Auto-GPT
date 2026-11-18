# The install rehearsal on the GPU VM, on paper, 2026-11-18 (card H-38)

**Reader:** the integrator, who launches it; lane D, who owns the installer, the bundle and the runbook; lane W, if
the workstation runs Windows

This page is the launch sheet for one rehearsal: a fresh GPU VM is installed from the signed site bundle by RUNBOOK
§1 alone, followed by `tools/runbook_install.py` (H-22, H-24), as the dress rehearsal for the owner's RTX PRO 6000
workstation next week. Lane H launched nothing, spent nothing and made no cloud call. Every figure says where it comes
from; a figure that was not measured says so. Read on master `312eca7c7` (train 84) and this card's branch
`claude/lane-h-38-install-rehearsal-sheet`.

**State of the findings on master.** `runbook-install-2026-11-17/findings.json` holds one open finding,
`stub-production-embedder` (a no-GPU PRODUCTION box), and eleven closed. No clean-VM run has closed it. It does not
touch this rehearsal: a GPU box pins the embedder with the pair (`pin_model --install`). This rehearsal may add
findings of its own (`vm` in `seen_on`).

## 1. What the rehearsal proves, and what it cannot

It proves, on a machine nobody has installed on before:

- §1's one command from the stick, as written, with the large tier (`--tier large`): the bootstrap's signature, the
  bundle's signature, the host tree unpacked, the key placed, the installer through settings, keys sealed under a
  real TPM (the VM's vTPM), the pair and the embedder pinned from the bundle's weights, the stack started with the
  real model servers, the serving check and the canary;
- the later steps the runbook names (4: the mapping check; 6: the key in place; 7: the first ingest and its report;
  8: the host check), the doctor, the self-test with the real models, the console's sign-in page over TLS;
- the time of each step, to set the workstation's install against, step by step.

It cannot prove (a GPU VM is not the workstation):

- the disk's unlock: LUKS2 with TPM2 (a cloud image has no LUKS root; the host check will FAIL those lines);
- Secure Boot with the NVIDIA modules (off on this VM, as on `tb-gpu-sim`);
- the vendor's driver install on the workstation (here the driver comes from Ubuntu's packages, by hand);
- Windows and WSL2, if the workstation runs Windows (lane W's path, `docs/handover/WINDOWS-INSTALL-CHECKLIST.md`);
- the workstation's own disk speed, memory and card cooling;
- the hospital's network: its DNS name, its CA's certificate, its mail relay, its proxy, its HIS export.

## 2. The machine

The GPU VM shape the repository already uses (`docs/handover/gpu-vm-handover-2026-11-16.md`, the table at its top;
`deploy/gcp/box-run.sh` line 5): `g4-standard-48` with one RTX PRO 6000 (96 GB), zone `asia-east1-a`, SPOT, stop on
pre-emption. A **new VM**, not `tb-gpu-sim`: its disk holds the driver's work and its model cache, and `/opt/trialbox`
there is not empty.

| | This rehearsal | Why |
| --- | --- | --- |
| Name | `tb-install-rehearsal` (new) | `tb-gpu-sim`, `tb-demo-vm` and `tb-preview-vm` are not touched |
| Boot disk | 250 GiB `hyperdisk-balanced`, fresh, plain Ubuntu 24.04 LTS (`ubuntu-2404-lts-amd64`, `ubuntu-os-cloud`) | the follower's preflight wants 2.2 x the bundle and 10 GiB free on `/` (section 3) |
| Media disk | 100 GiB `hyperdisk-balanced`, mounted read-only at `/media/usb` | stands for the USB stick: the one command starts `cd /media/usb` |
| Shielded VM | vTPM on, integrity monitoring on, Secure Boot off | the TPM seal is real; Secure Boot as on `tb-gpu-sim` |
| `/opt/trialbox`, `/root/site`, `/srv/his-export`, `/root/vendor_ed25519.pub` | absent | the follower refuses a first follow otherwise |

## 3. The bundle

A site bundle for the large tier, signed, with the pair's weights and the embedder (D-998: `release check` refuses a
site bundle without the embedder).

**What it carries.** The images of the box's compose files (profiles stub and gpu, which includes the vLLM image the
rtxpro6000 profile runs) and, with `--models`, a models folder laid out as `deploy/docker-compose.rtxpro6000.yml`
reads it: the judge's folder (`JUDGE_MODEL_DIR`), the verifier's (`VERIFIER_MODEL_DIR`), the judge's chat template
(`JUDGE_CHAT_TEMPLATE`, the file `models/registry.yaml` names with its sha256) and `embedder/` (`e-embed-1`).

**Its size, from the repository's own byte counts:**

| Part | Bytes | Source |
| --- | --- | --- |
| The judge's weights, 12 files | 18,825,679,760 | `deploy/measured/serving_config.rtxpro6000.json`, `servers[0].model_files` |
| The verifier's weights, 17 files | 9,091,720,350 | the same, `servers[1].model_files` |
| The embedder, 18 files | 2,295,165,682 | `models/registry.yaml`, the `e-embed-1` row |
| **The weights** | **30,212,565,792** (28.1 GiB) | |
| The images, the vLLM image included | about 29.6 GB | the one complete GPU build, `val-ac36aa21fdc1` (launch L5), made without `--models` (the hand-over, section 4.3) |
| The vLLM image alone, compressed, 40 layers | 9,205,727,079 | the registry's manifest of the pinned `linux/amd64` image, read here (no pull) |
| **The bundle** | **about 60 GB** | the two rows in bold, rounded |

**The disk to build it.** `tools/bundle_space.py` (which `make_bundle.sh` runs first) asks for twice (payload x 1.1
+ 0.5 GiB) on one disk. Its payload is Docker's unpacked size of each image plus the models folder. With the vLLM
image counted only at its compressed size (its unpacked size is not known here), the floor is about **110 GB free**.
`make_bundle.sh` prints the real figure on the build VM before it saves the first image.

**Where it is built, and how.** On the GPU VM, by the integrator (the brief), from a clean commit. The exact line is
lane D's to give (blocker D1, section 6). The form `make release-bundle` takes:

```sh
# on the build VM, from trialbox/ at the release commit, after make images and make trivy-db; not run by lane H
make release-bundle BUNDLE_ARGS="--key <vendor key> --id <id> --release-seq <N> \
    --out <out>/trialbox-<id>.tar --models <models folder, laid out as above> --refdata <reference data pack>"
```

It writes the four files the stick carries: `trialbox-<id>.tar`, its `.sha256`, `trialbox-bootstrap.sh` and its
`.sig` (D-996). The follower's own `python -m tools.runbook_install bundle --models <dir>` builds the same thing for
the stub images only (the container machine), so it is not this bundle.

**For the rehearsal**, a bundle signed with a throwaway key is enough: the follower takes any key, and the install
checks the bundle against it. The owner's workstation needs the release key. Which key signs the rehearsal is the
integrator's choice (question 2).

## 4. The exact run

All of it is the integrator's. Lane H ran none of it. Commands marked "free" read only. `<id>` is the bundle's id,
and `<commit>` the commit the bundle was built from: the follower refuses a checkout at any other commit.

**Free checks first (from the integrator's machine):**

```sh
gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project ubuntu-os-cloud --format='value(name)'   # free
gcloud compute machine-types describe g4-standard-48 --zone asia-east1-a --format='value(name,guestCpus)'           # free
gcloud storage ls -l gs://trialbox-demo-runs/rehearsal/<id>/                     # free: the four files and the key
```

**1. Create the VM** (no script in `deploy/gcp/` makes a fresh, plain one; every flag is shown; not run by lane H):

```sh
gcloud compute instances create tb-install-rehearsal --zone asia-east1-a --machine-type g4-standard-48 \
  --provisioning-model SPOT --instance-termination-action STOP --max-run-duration 3h \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 250GB --boot-disk-type hyperdisk-balanced \
  --create-disk name=tb-install-rehearsal-media,size=100GB,type=hyperdisk-balanced,auto-delete=yes \
  --shielded-vtpm --shielded-integrity-monitoring --no-shielded-secure-boot \
  --scopes cloud-platform --labels trialbox=install-rehearsal --metadata enable-oslogin=TRUE
```

**2. Step 1's prerequisites, by hand, as the site's IT would do them** (`gcloud compute ssh tb-install-rehearsal
--zone asia-east1-a`, then `sudo -i`). Time each line. They are not the follower's: it only checks them.

```sh
apt-get update && ubuntu-drivers install --gpgpu nvidia:580-server && reboot      # the driver; then ssh again
nvidia-smi -L                                                                     # must list the RTX PRO 6000
apt-get install -y docker.io docker-compose-v2 nftables python3-yaml python3-cryptography curl cron openssl git
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y nvidia-container-toolkit && nvidia-ctk runtime configure --runtime=docker \
  && systemctl restart docker
swapoff -a                                                                        # step 1: swap off
```

**3. The stick and the key** (the media disk, then read-only; the key apart from it):

```sh
mkfs.ext4 -q /dev/disk/by-id/google-tb-install-rehearsal-media && mkdir -p /media/usb \
  && mount /dev/disk/by-id/google-tb-install-rehearsal-media /media/usb
gcloud storage cp 'gs://trialbox-demo-runs/rehearsal/<id>/trialbox-*' /media/usb/
mount -o remount,ro /media/usb && ls -l /media/usb        # four files: the bundle, .sha256, bootstrap, .sig
mkdir -p /root/given && gcloud storage cp gs://trialbox-demo-runs/rehearsal/<id>/vendor_ed25519.pub /root/given/
```

**4. The follower's checkout** (the repository is public; the follower needs only Python's standard library):

```sh
git clone https://github.com/zandis/Auto-GPT.git /root/tb-follower && git -C /root/tb-follower checkout <commit>
cd /root/tb-follower/trialbox
```

**5. The strict follow** (no lifts: the verdict as the runbook alone gives it):

```sh
python3 -m tools.runbook_install follow --machine vm --strict \
  --bundle /media/usb/trialbox-<id>.tar --vendor-pub /root/given/vendor_ed25519.pub \
  --out /root/run-vm-strict.json --raw-dir /root/tb-raw
```

It refuses before anything slow, and names what is missing, when: it is not root; the stick is not at `/media/usb`
or lacks one of the four files; the key is missing; `/opt/trialbox`, `/root/site`, `/srv/his-export` or
`/root/vendor_ed25519.pub` exists; `/` has less than 2.2 x the bundle and 10 GiB free; or the bundle was built from
another commit than the checkout. With the RTX PRO 6000 listed by `nvidia-smi`, it runs `--tier large` as written.

**6. Only if the verdict names a runbook stop:** the same follow again with the named lifts. §1 says that an install
that stopped is run again by the same command:

```sh
python3 -m tools.runbook_install follow --machine vm --rerun \
  --bundle /media/usb/trialbox-<id>.tar --vendor-pub /root/given/vendor_ed25519.pub \
  --out /root/run-vm.json --raw-dir /root/tb-raw
python3 -m tools.runbook_install compare /root/run-vm.json   # every finding seen here is listed as "now shows on vm"
```

When the box installed, the follower itself runs steps 4 (the mapping check in the image), 6 (the key in place) and
7 (the first ingest and its report). The `timings` list in the record holds each step's commands and seconds.

**7. The checks the runbook names after the install** (from `/opt/trialbox`, as root; record each output):

```sh
cd /opt/trialbox
deploy/check_host.sh | tee /root/host-check.txt                    # step 8: LUKS, Secure Boot lines will FAIL here
python3 -m tools.trialbox doctor --json > /root/doctor.json        # §2 and §6: "trialbox doctor"
python3 -m tools.trialbox selftest | tee /root/selftest.txt        # §4: the pair canary with the real models
curl -fsS -o /dev/null -w '%{http_code}\n' --resolve trialbox.hospa.test:443:127.0.0.1 \
  --cacert deploy/secrets/tls/caddy-root.crt https://trialbox.hospa.test/login   # the console over TLS: 200
```

The first administrator's sign-in is optional and by hand. The password and the enrolment code are only in
`/root/tb-raw` (mode 0600; never in the record). Open an SSH tunnel to port 443 and sign in through a browser, or
leave it as "not done". If `python3 -m tools.trialbox` stops on a missing module, that is a finding: write it down
as it printed.

**8. What to send back**, then delete the VM:

```sh
# from the VM to the bucket; then from the integrator's machine
gcloud storage cp /root/run-vm-strict.json /root/run-vm.json /root/doctor.json /root/host-check.txt \
  /root/selftest.txt gs://trialbox-demo-runs/rehearsal/<id>/results/
gcloud compute instances delete tb-install-rehearsal --zone asia-east1-a --quiet    # deletes the media disk too
```

The records hold no secret: `redact` drops the administrator's password and enrolment code, every value printed after
a secret's name, and key ids. `/root/tb-raw` is never sent back and goes with the VM. `doctor.json` and the host check
print no secret by design. Look at them before you send them anyway.

## 5. The estimate

US$2.74 a VM hour, SPOT (`tools/complete_run.py`, `PRICE_PER_HOUR`); US$8.22 on demand (`ON_DEMAND_PRICE_PER_HOUR`).

| Stage | Low | Estimate | High | Source |
| --- | --- | --- | --- | --- |
| 1. VM created and booted | 0.10 h | 0.15 h | 0.25 h | `BOOT_HOURS` 0.25 h (a start with both models resident) as the high; a plain boot is not measured |
| 2. Step 1's prerequisites by hand, one reboot | 0.15 h | 0.25 h | 0.40 h | **not measured** |
| 3. The media (about 60 GB) to the media disk | 0.05 h | 0.10 h | 0.15 h | lane G's in-region upload, 29.6 GB in 73 s (b07); the disk's 140 MB/s baseline writes 60 GB in about 430 s |
| 4. The checkout | 0.02 h | 0.02 h | 0.05 h | |
| 5. The strict follow: the one command, the install | 0.39 h | 0.55 h | 0.75 h | the parts below |
| 6. The follow again with lifts, if the strict one stops | 0 | 0.25 h | 0.75 h | it verifies and loads the bundle again |
| 7. The later checks | 0.15 h | 0.25 h | 0.35 h | **not measured** |
| 8. Results out, VM deleted | 0.03 h | 0.05 h | 0.10 h | |
| **In all** | **0.89 h, US$2.44** | **1.62 h, US$4.44** | **2.80 h, US$7.67** | |

Stage 5, from what is measured:

- verify: every file of a 60 GB bundle hashed, at the disk's 140 to 440 MB/s: 140 to 430 s;
- load: "10-20 minutes for a GPU bundle", the installer's own words, 600 to 1,200 s;
- the pins, and `--verify-all` after them: 30.2 GB of weights hashed twice, 140 to 430 s;
- the model servers ready: 199 s (`gpu-run-2026-11-08/fit.json`);
- the canary: 124 to 260 s (the driver's estimate; H-15);
- the rest of the install: 112 s (H-24's container run; its first attempt, 80 s, stopped at the TPM).

**The install of a bundle on this VM has never been timed.** H-28's page says the same for a `start` launch, and
the driver's `--estimate --steps start` prints it as "unknown". This rehearsal is the first measurement.

- **The estimate to post: US$4.4 (1.6 h).**
- **The stop line, 50 % over the estimate: US$6.7 (2.4 h).** At the stop line, stop the VM if the second follow
  (stage 6) has not reached the stack's start. The high figure goes past the stop line only when a second full
  install runs.
- **The cap: `--max-run-duration 3h`**, US$8.22 SPOT. The worst case on demand is 3 h at US$8.22, US$24.66.
- **Disks:** 350 GiB of `hyperdisk-balanced` for at most 3 h, at US$0.093 a GiB-month (the hand-over's Taiwan list
  price), about US$0.13. Baseline throughput only (140 MB/s): none provisioned.
- **The bucket:** about 60 GB under `rehearsal/<id>/` at US$0.020 a GiB-month, about US$1.1 a month while kept.
- **Not in these figures:** building the bundle on the GPU VM. The only measured GPU build, L5 without weights, took
  0.57 h (US$1.56); its sign step took 521 s for 29.6 GB.

## 6. What must be on master before the launch

| Lane | Blocker | State |
| --- | --- | --- |
| D | D1. A build line for a large-tier site bundle with `--models` (the pair, the template, the embedder). The driver's build route calls `make_bundle.sh` without `--models` (`deploy/gcp/box-install-run.sh:1262`, `:1276`). Since D-998 `release check` refuses that bundle, and it never carried the pair's weights | open (the integrator asked lane D) |
| D | D2. Where the build VM's weights come from, laid out as `--models` needs (the driver's dev route places them: `box_vm.py models-place`) | open |
| H | H1. `follow --machine vm`, which never ran on a real VM: preflight, GPU detection, `--rerun` and `--raw-dir` are on this branch, unit-tested on stand-ins | this branch |
| H | H2. Finding 5 stays open (a no-GPU box). It does not block this rehearsal | no action |
| Integrator | I1. The right to create an instance (`instances create` is a project-level right: the GPU VM hand-over, section 13), and the media's bucket prefix | the integrator's |
| W | W1. Only if the workstation runs Windows: this sheet does not rehearse WSL2 | ask the owner |

**What the rehearsal must record**, so that the workstation's install can be set beside it step by step:

- the machine's facts (the follower's `1-host` note);
- each stage's start and end (section 5's eight stages, by hand);
- the record's `timings`, per step of §1;
- every command as written and as run;
- each question the installer asked;
- the host check's FAIL lines, each named as the machine's (LUKS, Secure Boot) or not;
- the doctor's JSON;
- the self-test's result;
- the verdict.

The workstation's install is then the same command on the owner's machine, with the same records.

## 7. Not shown

- No figure on this page was measured on a GPU VM install: the install's time is a projection from its parts.
- The vLLM image's unpacked size, and so `bundle_space`'s own figure for the build disk.
- That `ubuntu-drivers install --gpgpu nvidia:580-server` gives the driver `deploy/images.lock` asks for on this card,
  without Secure Boot. The step is the integrator's, by hand, and the host check reads the result.
- That `python3 -m tools.trialbox doctor` and `selftest` run on the host's Python as the runbook writes them, rather
  than in the image as the rehearsal's own scripts run them. If they stop, that is a finding.
- Whether the owner's workstation runs Linux or Windows.
- The workstation's disk unlock, Secure Boot, driver route and network (section 1).
