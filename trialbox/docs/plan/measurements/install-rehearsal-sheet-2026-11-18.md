# The trial install on the GPU VM: W-2, from the tag, by the guide alone (2026-11-19); H-38's rehearsal sheet below

**Reader:** the integrator, who launches W-2; lane J, who wrote the guide (runbook §27) and the weights command
(W-1); lane D, who owns the signed site bundle; the owner, whose own install comes next

## W-2: from the tag, by the guide alone (2026-11-19)

Lane H launched nothing, spent nothing and made no cloud call for this page. Every figure says where it comes from; a
figure that was not measured says so. Read on master `a44a39da` (train 90) and this card's branch
`claude/lane-h-w2-trial-install-sheet`. H-38's sheet of 2026-11-18 is kept below as the basis; its section 3 (the
bundle) and section 4 (RUNBOOK §1 from the stick) are **not** W-2's run: see W-2.0.

### W-2.0 Which guide, which bundle, which key

**The guide is runbook §27** (`docs/runbook/27-workstation-rtx-pro-6000.md`), not RUNBOOK §1. Root review 23 names
W-2 as "the tag, and one person who did not write it following runbook 27 once on a GPU host"
(`docs/reviews/2026-11-root/23-first-install-and-january-validation.md`, section 4.1, row 4), and the owner's decision
1 there is "a tag on a green master commit installed by `poc.sh` from a checkout (not a signed bundle)". W-1 (#1085)
changed only §27 (step 10 and its section "The weights") and added `tools/fetch_weights.py` and `make fetch-weights`;
it did not touch §1.

**So W-2 uses no bundle and no key.** §27 clones the repository, checks out the tag (§27:23), fetches the weights
from the model hub (§27:25) and builds and starts the stack with `deploy/poc.sh` (§27:26). Nothing is signed or
verified with the release key or with a throwaway key. The rulings on the keys (the rehearsal bundle with a throwaway
key; the release key only for the bundle the integrator builds from the tag) apply to the signed site bundle, which
is the site box's install (§1, H-38's sheet below), a separate launch that is still blocked (W-2.8, lane D).
**Question 1 for the integrator:** confirm that W-2 is §27 and so builds no bundle.

**The follower** is a new one, `tools/runbook_workstation.py` (this card). `tools/runbook_install.py` follows §1 only
and knows none of §27's commands (W-2.9).

### W-2.1 What W-2 proves, and what it cannot

It proves, on a machine nobody has installed on, by someone who did not write the guide:

- that §27's steps 1 to 11, as written, take a plain Ubuntu 24.04 x86 machine with the RTX PRO 6000 (the one card
  TrialBox has measured) to the started PoC with the real model pair: the tag's checkout, the card and tier check,
  the weights from the hub at the registry's revisions, the image build, the pins, the stack, the canary, the 600
  synthetic patients;
- steps 12 to 15 by hand (the sign-in, a feasibility reply, a screened list, the list again without the network);
- the time of each step, for the owner's install to be set beside it.

It cannot prove:

- **the owner's own machine.** That is Ubuntu 22.04 on Arm (an IGX Orin developer kit, RTX A6000 48 GB, driver 535;
  `docs/reviews/2026-11-root/24-igx-orin-a6000-install.md`, lines 8 to 10). Its guide is runbook §28, the product
  without a model; the real models there are runbook 29 in #1100 (open, a 48 GB class marked UNMEASURED). On that
  machine `sh deploy/gpu_profile.sh` prints `arm64-dgpu` and the PoC refuses GPU mode; driver 535 is below the
  580.65 that step 4 and the model engine need; and its Python 3.10 stops `tools/fetch_weights.py` at import (lane
  J's fault, W-2.8). W-2 is x86 with the measured card only;
- **WSL2 or Windows** (§27's "On Windows instead", "not verified anywhere");
- the vendor's driver on a workstation, Secure Boot with the NVIDIA modules (off on this VM), the workstation's
  disk, memory and cooling, a home or hospital network;
- **the site box:** the signed bundle, the offline install, LUKS, the TPM, PRODUCTION (§1; H-38's sheet below).

### W-2.2 The machine

A **new** VM. Never `tb-gpu-sim`, `tb-demo-vm`, `tb-preview-vm` or `tb-steps-vm`.

| | W-2 | Why |
| --- | --- | --- |
| Name | `tb-w2-trial` (new) | none of the four named above |
| Shape | `g4-standard-48`, one RTX PRO 6000 (96 GB), zone `asia-east1-a`, SPOT, stop on pre-emption | the shape the repository uses (`deploy/gcp/box-run.sh` line 5; the GPU VM hand-over's table) |
| Boot disk | 500 GB `hyperdisk-balanced`, plain Ubuntu 24.04 LTS (`ubuntu-2404-lts-amd64`, `ubuntu-os-cloud`), baseline throughput (140 MB/s, none provisioned) | §27:10 asks for 500 GB free and Ubuntu 24.04 |
| Shielded VM | vTPM on, integrity monitoring on, Secure Boot off | as `tb-gpu-sim`; §27 needs no TPM |
| User | the launcher's own OS Login user with sudo without a password, never root | §27's reader is a user with sudo (steps 3, 4, 6, 7 start `sudo`); the follower refuses root |
| Network | an external address; outbound to the hub, Docker Hub, GitHub, Maven Central, Ubuntu's and NVIDIA's archives | §27:11 "wired internet for the install (about 70 to 90 GB to download)" |
| Media disk, bucket | none | §27 has no stick; the records go back by `gcloud compute scp` |

### W-2.3 The bundle

None (W-2.0). The tag is `v1.0.0-rc1`, cut by the integrator on Monday 2026-11-23 from the master of Sunday
12:00 UTC. The guide's step 8 checks it out from the public repository; the follower checks that the checkout's
`HEAD` is the tag's commit and that the tree is clean, and records the commit. **The follower must be in the tag:**
this branch must be on master by Sunday 12:00 UTC, else the follower runs from a later master checkout and its record
says that its own commit is not the tag's (question 4).

### W-2.4 The exact run

`<you>` is the launcher's user on the VM. Commands marked **launcher** are outside the guide; every other command is
the guide's as written, with its line in §27. "Free" commands only read.

**Free checks first (the integrator's machine; nothing created or changed):**

```sh
git ls-remote --tags https://github.com/zandis/Auto-GPT.git v1.0.0-rc1                                  # free: the tag exists; its commit
gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project ubuntu-os-cloud --format='value(name)'   # free
gcloud compute machine-types describe g4-standard-48 --zone asia-east1-a --format='value(name,guestCpus)'           # free
```

And, from any checkout of the tag (no network, nothing written): `python3 -m tools.fetch_weights --profile
rtxpro6000 --dry-run` prints the three hub addresses (two model folders and the judge's chat template, about 27.9 GB).
For each, `curl -sIL -o /dev/null -w '%{http_code}\n' <address of its config.json or template>` (free, headers only):
200 means no sign-in; 401 or 403 means the hub wants the terms accepted and a read token (§27:67-72). Not run here.

**1. Launcher: create the VM** (no script in `deploy/gcp/` makes a fresh, plain one):

```sh
gcloud compute instances create tb-w2-trial --zone asia-east1-a --machine-type g4-standard-48 \
  --provisioning-model SPOT --instance-termination-action STOP --max-run-duration 4h \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 500GB --boot-disk-type hyperdisk-balanced \
  --shielded-vtpm --shielded-integrity-monitoring --no-shielded-secure-boot \
  --labels trialbox=w2-trial --metadata enable-oslogin=TRUE
gcloud compute ssh tb-w2-trial --zone asia-east1-a          # as <you>; start the stage clock (W-2.7)
```

**2. Steps 1 to 7 by hand, as the guide writes them** (time each step; write every command typed on the form):

| Guide step | Type (§27 as written) | Note |
| --- | --- | --- |
| 1 (§27:16) | `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv` | on a fresh image there is no `nvidia-smi` yet (it comes at step 4): write what it printed (finding W2-step-1-before-driver); the follower runs step 1 again after step 4 |
| 2 (§27:17) | `lsb_release -rs` | `24.04`; the VM's image is the step's install |
| 3 (§27:18) | `sudo apt update && sudo apt install -y git make curl python3-yaml python3-venv` | no `E:` line |
| 4 (§27:19) | `sudo ubuntu-drivers list`; `sudo apt install -y nvidia-driver-580-open` (or the newest `-open` listed: write which); `sudo reboot`; ssh again; `nvidia-smi` | the card; driver 580.65 or newer |
| 5 (§27:20) | **the guide gives a page, not a command:** "Install Docker Engine on Ubuntu" on docs.docker.com, as the page reads on the day; then `docker compose version` | paste the page's commands onto the form; the guide's "v2.x" may differ (finding W2-compose-version, a hypothesis) |
| 6 (§27:21) | `sudo usermod -aG docker $USER`; `exit`, then ssh again (the guide's "sign out and in"); `docker info` | no error |
| 7 (§27:22) | **the guide names "NVIDIA's apt steps" without an address:** find NVIDIA's Container Toolkit install page as the owner would, write its address and commands; then `sudo nvidia-ctk runtime configure --runtime=docker`; `sudo systemctl restart docker`; `docker run --rm --gpus all ubuntu:24.04 nvidia-smi` | the card's table |

**3. Launcher: the follower's own checkout, at the tag** (apart from step 8's clone, which the follower makes):

```sh
git clone https://github.com/zandis/Auto-GPT.git ~/tb-follower && git -C ~/tb-follower checkout v1.0.0-rc1
cd ~/tb-follower/trialbox && python3 -m tools.runbook_workstation diff   # "the follower knows every command ..."
```

**4. The strict follow** (no lift: the verdict as §27 alone gives it). It runs steps 1 to 7's checks and step 3 again
(the guide's commands, idempotent), then steps 8 to 11 exactly as written, in a new folder `~/w2`:

```sh
python3 -m tools.runbook_workstation follow --strict --tag v1.0.0-rc1 --work ~/w2 \
  --out ~/w2-run-strict.json --raw-dir ~/w2-raw
```

It refuses before anything when it is root, when sudo asks for a password, when `~/w2/Auto-GPT` exists, when the
machine is not x86, or when the tag is not a plain name. It stops, and names the step and the evidence, at the first
result that is not the guide's "You should see"; at step 11 it then runs the guide's own `deploy/poc.sh status`. The
start prints the administrator's password once: it is only in `~/w2-raw` (mode 0600), never in the record.

If step 10 is refused by the hub (401 or 403), the guide itself says what to do (§27:67-72): accept the terms on the
model's page, make a read token, `read -rs HF_TOKEN && export HF_TOKEN`, and run the follow again with `--rerun`
(below). The token is never printed or recorded.

**5. The rerun** (always: after a strict stop at step 10 or 11, the guide says both may be run again; after a strict
pass it is cheap, everything is present, and it does steps 13 and 14 by mail):

```sh
python3 -m tools.runbook_workstation follow --rerun --mail --tag v1.0.0-rc1 --work ~/w2 \
  --out ~/w2-run.json --raw-dir ~/w2-raw
```

It reuses `~/w2`'s checkout (still at the tag) and may apply one lift, recorded and marking every later line "after
lifts": the database image, built by the command runbook §28 step 6 gives
(`docker build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker`), only when step 11 stopped
and that image is missing (finding W2-db-image). `--mail` sends steps 13's and 14's subjects with
`tools/send_test_mail.py`, the alternative the start itself prints, and reads the replies from the web mail. A lift
never changes the strict verdict.

**6. Steps 12 to 15 by hand** (from the integrator's machine, through a tunnel):

```sh
gcloud compute ssh tb-w2-trial --zone asia-east1-a -- -L 8090:127.0.0.1:8090 -L 8025:127.0.0.1:8025
```

- Step 12 (§27:27): `http://127.0.0.1:8090`, user `admin`, the password from `~/w2-raw` (the step 11 file); set up
  the second factor with a phone authenticator. Write "done" or what happened.
- Steps 13 and 14 (§27:28-29): the console's "Test mailbox" with `FEAS GZQO`, then `SCREEN GZQO version=1.0.0`; the
  replies in `http://127.0.0.1:8025`. Write the minutes to each reply.
- Step 15 (§27:30): a VM has no cable. **Launcher's stand-in, not the guide's:** cut the stack's way out and keep SSH,
  `sudo iptables -I DOCKER-USER -o "$(ip route show default | awk '{print $5}')" -j DROP`; repeat step 14; then
  `sudo iptables -D DOCKER-USER -o "$(ip route show default | awk '{print $5}')" -j DROP`; then, from
  `~/w2/Auto-GPT/trialbox`, `deploy/poc.sh down` (§27:30).

**7. Launcher: the records back, then the VM deleted** (from the integrator's machine):

```sh
mkdir -p w2 && gcloud compute scp --zone asia-east1-a \
  tb-w2-trial:~/w2-run-strict.json tb-w2-trial:~/w2-run.json ./w2/
gcloud compute instances delete tb-w2-trial --zone asia-east1-a --quiet
```

`~/w2-raw` never leaves the VM and goes with it. The records hold no secret (`redact`: the once-shown password, any
value after a secret's name, any hub token); look at them before posting anyway.

### W-2.5 The weights step

**W-2 walks the network path, because the guide does.** §27 step 10 (§27:25, and "The weights", §27:32-76) fetches
the pair's two folders and the judge's chat template from the model hub with `python3 -m tools.fetch_weights
--profile rtxpro6000`, at the revisions and sha256 of `models/registry.yaml` and the measured record it names; the
start (`deploy/poc.sh`) only checks and pins them. No bundle carries weights in §27, and "Nothing runs this command at
install or start" (§27:76).

| | |
| --- | --- |
| Size | 27.9 GB: 11 files for the judge (18.8 GB), 16 for the verifier (9.1 GB), and the template (the dry run on master, run here; it reads only the repository) |
| Source | `https://huggingface.co/<repository>/resolve/<revision>/<file>`, three repositories the registry names; redirects to the hub's content store, https only |
| Licence | the dry run prints Apache-2.0 and "register cleared" for all three (`docs/licences/register.csv`); whether the hub asks to accept terms (a gated repository) is **not known here**: the free curl check of W-2.4 answers it before the launch |
| Disk | the download plus 1 GB, checked by the tool; the stage `deploy/models/.fetch-weights` is on the same disk |
| Time | **not measured.** The hub's speed into a Google VM is not known; the disk's baseline 140 MB/s caps the write; at 25 to 150 MB/s, 200 to 1,120 s, then `--verify-only` hashes the 27.9 GB again (140 to 440 MB/s: 63 to 200 s) |
| Python | Ubuntu 24.04's Python 3.12: `tools/fetch_weights.py` imports `tools.pin_model`, which imports `datetime.UTC` (`tools/pin_model.py:68`, Python 3.11 or newer). That is still so on master `a44a39da`; the fix is in #1100 (open). It does not touch W-2 (3.12); it stops step 10 on Ubuntu 22.04 (3.10), the owner's Arm machine |
| A hospital box | would not have this network: the site box must install offline from verified files (review 23, section 4.1). Its weights come in the signed site bundle (`tools/make_bundle.sh --models`), which is H-38's path, still blocked by D1 and D2 (W-2.8) |

### W-2.6 The estimate

US$2.74 a VM hour, SPOT (`tools/complete_run.py:1636`, `PRICE_PER_HOUR`); US$8.22 on demand
(`ON_DEMAND_PRICE_PER_HOUR`). **No §27 install has ever been timed on any machine:** `deploy/poc.sh` in GPU mode has
never run on real hardware (review 23, section 1.2). W-2 is the first measurement.

| Stage | Low | Estimate | High | Source |
| --- | --- | --- | --- | --- |
| 1. VM created, booted, SSH | 0.05 h | 0.10 h | 0.25 h | `BOOT_HOURS` 0.25 h as the high (`tools/complete_run.py:1684`); a plain boot not measured |
| 2. Steps 1 to 7 by hand, one reboot | 0.25 h | 0.40 h | 0.75 h | **not measured** |
| 3. The follower's checkout | 0.02 h | 0.03 h | 0.05 h | not measured |
| 4. The strict follow | 0.33 h | 0.87 h | 1.96 h | the parts below |
| 5. The rerun (with the database lift if the tag lacks #1130; with `--mail`) | 0 | 0.35 h | 0.90 h | the database image: "5 to 15 minutes" (§28 step 6, on Arm, not measured); then step 11 again without the build |
| 6. Steps 12 to 15 by hand | 0.15 h | 0.25 h | 0.50 h | **not measured**; the guide allows 10 min a reply (§27:28) |
| 7. Records back, VM deleted | 0.03 h | 0.05 h | 0.10 h | not measured |
| **In all** | **0.83 h, US$2.27** | **2.05 h, US$5.62** | **4.51 h, US$12.36** | |

Stage 4, part by part (h, low / estimate / high):

- steps 1 to 7 again and step 3's apt: 0.02 / 0.03 / 0.05, not measured;
- step 8, a full clone of the public repository: 0.01 / 0.03 / 0.10, not measured;
- step 10: 0.07 / 0.17 / 0.37 (W-2.5), not measured;
- step 11, the image build: 0.05 / 0.25 / 0.60. Measured: `make images` on the GPU VM with Maven on the host, 160 to
  250 s (the GPU VM hand-over, b03). §27 installs no Maven, so the start takes its builder-container path, which is
  not measured; §27 says 10 to 20 min, #1130 says 30 to 60 min for all builds on Arm;
- step 11, the images pulled (the vLLM image alone is 9.2 GB compressed, H-38's section 3): 0.03 / 0.08 / 0.20, not
  measured;
- step 11, the pins hash 27.9 GB: 140 to 430 s at the disk's 140 to 440 MB/s: 0.04 / 0.08 / 0.12;
- step 11, the model servers ready: 199 s measured (`gpu-run-2026-11-08/fit.json`), up to the start's 900 s:
  0.06 / 0.10 / 0.25;
- step 11, the canary: 124 to 260 s (H-15's estimate): 0.03 / 0.05 / 0.07;
- step 11, the 600 synthetic patients: 0.02 / 0.05 / 0.15, not measured.

- **The estimate to post: US$5.6 (2.1 h).**
- **The stop line, 50 % over the estimate: US$8.4 (3.1 h).** At the stop line, stop the VM unless the rerun's step 11
  has reached the stack's start.
- **The cap: `--max-run-duration 4h`**, US$10.96 SPOT; the VM stops (not deleted) at the cap, so the records can still
  be copied; delete it after. The high (4.51 h) is above the cap: it needs every part at its slowest and a full step
  11 twice. On demand the cap is 4 h at US$8.22, US$32.88.
- **Disk:** 500 GB `hyperdisk-balanced` for at most 4.5 h at US$0.093 a GiB-month (the hand-over's Taiwan list price):
  about US$0.29. **Bucket:** none. **Network:** the downloads come in (ingress); the records out are a few kB.
- **Not in these figures:** the external address (not in the repository's price notes); people's time; any build of
  the signed site bundle. That build is not W-2's (W-2.0). If the integrator also builds the release-key bundle from
  the tag on this VM, it is its own line: the only measured GPU build, L5 without weights, took 0.57 h (US$1.56), and a
  bundle with the weights cannot be built until D1 and D2 are closed (W-2.8), so it has no estimate here.

### W-2.7 What to record, for the owner's install later

The follower's two records (`w2-run-strict.json`, `w2-run.json`) hold: the machine's facts (arch, OS, Python, CPUs,
memory, free disk, the card's line); the follower's commit and the checkout's (the tag's); every command as written
and as run, its exit code, seconds and last lines (redacted); the notes (the steps the launcher did, a newer compose);
the lifts; the verdict; and `timings` per guide step. By hand, on the form below: each stage's start and end (W-2.6's
seven stages), steps 1 to 7's commands as typed (step 5's and step 7's outside pages and their addresses), which
driver step 4 installed, steps 12 to 15's results and the minutes to each reply, and anything the guide did not say.

| Stage or step | Start (UTC) | End (UTC) | Typed, seen, or what differed from the guide |
| --- | --- | --- | --- |
| 1 VM | | | |
| 2: guide step 1 / 2 / 3 / 4 / 5 / 6 / 7 | | | |
| 3 follower checkout | | | |
| 4 strict follow (verdict) | | | |
| 5 rerun (lifts, verdict) | | | |
| 6: guide step 12 / 13 / 14 / 15 | | | |
| 7 records, delete | | | |

The owner's install is then §28 (or 29) on the Arm machine with the same form: what W-2 timed on x86 with §27 is the
reference for every step the two guides share (8, the checkout; 11, the start), and a difference elsewhere is the
machine's.

### W-2.8 Blockers, by lane

| Lane | Blocker | Place | State on master `a44a39da` | Question |
| --- | --- | --- | --- | --- |
| J (the register has no lane J: filed under D) | **W2-db-image**: on a machine without Maven, the start builds the Python and JVM images but not the database image; compose's `db` names `trialbox-postgres:16-1`, which has no `build:` entry and is on no registry, so step 11 stops at the stack's start. §28 has a manual build step (step 6); §27 has none | `deploy/poc.sh:202-221`, `deploy/docker-compose.yml:77`, `docs/runbook/27-workstation-rtx-pro-6000.md:26` | open; the fix is #1130 (card 24-2, a draft, behind master) | Will #1130 be on master by Sunday 12:00 UTC? If not, the strict follow stops at step 11 and the rerun's lift adds about 0.35 h |
| J (filed under D) | **W2-step-1-before-driver**: step 1 runs `nvidia-smi` before step 2 installs Ubuntu and step 4 the driver; on a plain Ubuntu it is "command not found" | `docs/runbook/27-workstation-rtx-pro-6000.md:16` | open, not run | Should step 1 read the card another way (`lspci`, or the vendor's sheet), or move after step 4? |
| J (filed under D) | **W2-outside-pages**: steps 5 and 7 give no install command, only a page (step 7 without an address) | `docs/runbook/27-workstation-rtx-pro-6000.md:20`, `:22` | open | Write the commands, or the addresses? |
| J (filed under D) | **W2-compose-version**: "v2.x" may not be what Docker's page installs today (a hypothesis; the start needs only the plugin) | `docs/runbook/27-workstation-rtx-pro-6000.md:20` | not run | Say "a version line" instead? |
| J | Python 3.10: `tools/pin_model.py:68` imports `datetime.UTC`; `tools/fetch_weights.py:82` imports `tools.pin_model` | as named | open; fix in #1100 | Not W-2's (24.04 has 3.12); it stops the owner's step 10 on Ubuntu 22.04. Will #1100 be in the tag? |
| D | **D1** (H-38): the driver's build route calls `tools/make_bundle.sh` without `--models` | `deploy/gcp/box-install-run.sh:1262-1263` (the release key), `:1276-1277` (the throwaway key) | **still open**: no `--models` in either call | Not W-2's: it blocks the signed site bundle for rc1 and H-38's §1 rehearsal. Which line builds the rc1 site bundle with the weights? |
| D | **D2** (H-38): where the build machine's models folder comes from, laid out as `--models` needs | `tools/fetch_weights.py:82` fetches `tools.pin_model.PROFILE_PAIRS` only (`tools/pin_model.py:533`): the pair and the template, **not the embedder** that `release check` requires (D-998); the embedder is placed only by the dev route `deploy/gcp/box_vm.py` `models-place` (line 1674) | **still open** for the embedder; the pair and template now have a route (W-1) | Will `fetch_weights` (or another command) place `embedder/` for the bundle build? |
| Integrator | I1: the right to create an instance; the tag on a commit with both nightlies green (review 23, section 4.1, rows 1 and 2) | | the integrator's | Question 1 (no bundle), question 2 (the VM name `tb-w2-trial`), question 3 (who launches: someone who did not write §27) |
| H | the follower must be in the tag | this branch | this branch | Question 4: merge by Sunday 12:00 UTC |

### W-2.9 The guide against the follower, on paper

`python3 -m tools.runbook_workstation diff` (§27 against the follower's `KNOWN`): the follower knows all 27 commands
of §27's step table, and §27 has none the follower does not; `tests/unit/test_runbook_workstation_w2.py` fails when
that changes. `python3 -m tools.runbook_workstation plan` prints each command's role: 6 `run`, 10 `check`, 5 `host`
(the launcher's by the guide, then checked by the follower), 1 `else` (`deploy/poc.sh status` after a failed step
11), 4 `manual` (steps 12 to 15) and 1 fragment (`--dry-run`). The weights section's table (§27:40-45, with `make
fetch-weights`) and "Every day after" are outside the step table and not followed.

`tools/runbook_install.py` (§1's follower, `python3 -m tools.runbook_install extract`): 28 commands, none of them in
§27; and none of §27's 27 is known to it. W-1 did not change §1, so §1's follower is unchanged and its test
(`tests/unit/test_runbook_install_follow.py`) still holds its path to §1. Every change W-1 made after H-24 is inside
§27 (step 10's three `tools.fetch_weights` commands and the weights section), which only the new follower reads.

### W-2.10 Not shown

- Nothing on this page ran on a GPU, a VM or the hub; the follower is tested on stand-ins only.
- Whether the hub asks for sign-in for any of the three repositories; how fast it serves a Google VM.
- How long the start's builder-container path takes on x86; what Docker's page installs today (the compose version).
- That `nvidia-driver-580-open` from Ubuntu's archive gives a working driver for this card on this image without
  Secure Boot (H-38's sheet ran the `-server` route); step 4 writes the result down.
- That the web mail's API answers as the follower reads it (`--mail`); if not, steps 13 and 14 are by hand.
- The step 15 stand-in (a firewall rule) is not the guide's unplugging; the record says so.

---

## H-38's sheet (2026-11-18), the basis: RUNBOOK §1 from the stick

The text below is H-38's, unchanged but for its headings (one level down). It is the site box's rehearsal (the signed
bundle, RUNBOOK §1), not W-2's run, and it is blocked by D1 and D2 (W-2.8).

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

### 1. What the rehearsal proves, and what it cannot

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

### 2. The machine

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

### 3. The bundle

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

### 4. The exact run

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

### 5. The estimate

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

### 6. What must be on master before the launch

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

### 7. Not shown

- No figure on this page was measured on a GPU VM install: the install's time is a projection from its parts.
- The vLLM image's unpacked size, and so `bundle_space`'s own figure for the build disk.
- That `ubuntu-drivers install --gpgpu nvidia:580-server` gives the driver `deploy/images.lock` asks for on this card,
  without Secure Boot. The step is the integrator's, by hand, and the host check reads the result.
- That `python3 -m tools.trialbox doctor` and `selftest` run on the host's Python as the runbook writes them, rather
  than in the image as the rehearsal's own scripts run them. If they stop, that is a finding.
- Whether the owner's workstation runs Linux or Windows.
- The workstation's disk unlock, Secure Boot, driver route and network (section 1).
