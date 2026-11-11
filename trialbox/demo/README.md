# TrialBox demo (synthetic hospital)

One container runs the whole box on the synthetic hospital (made-up patients, studies GZQO and GOUT-COH). The default
tool (`TB_DEMO_TOOL=demo`) seeds and checks the whole step 1 to 4 flow, then serves the console with one sign-in per
role: `admin`, `crc` (study coordinator), `pi` (investigator), `subpi` (sub-investigator on GZQO), `cra` (CRO,
aggregate reports only) and `viewer`. All share one password: `TB_DEMO_PASSWORD`, or a random one printed in the log
when it is not set. It uses a stub language model, so no API key is needed and nothing leaves the container. Without
`TB_DEMO_KEEP=1` every restart rebuilds the data, so the demo resets. For the clinician PoC use per-tester accounts and
a kept data folder (next section).

The older role-only demo (`TB_DEMO_TOOL=role_demo`, 600 patients, study GZQO) has `smo` (SMO coordinator, GZQO only,
ends 2027-03-31) in place of `subpi`.

Never load real patient data into it: it runs TB_ENV=DEV, data class D0. It is not a product image: it carries the
test helpers (the in-process box lives in `tests/`), which is why it sits outside `deploy/`, where every Dockerfile
is a product image that must never contain the Test Bench. It does not carry `docs/reviews`.

## Per-tester accounts and persistence (the PoC, T-505b)

Give each tester their own accounts and keep their work across restarts:

    docker volume create tb-demo-data
    docker run -d -p 8080:8080 -v tb-demo-data:/data \
      -e TB_DEMO_KEEP=1 -e TB_DEMO_DIR=/data/demo -e TB_DEMO_ACCOUNTS=/run/demo-accounts.json \
      -v /srv/demo-accounts.json:/run/demo-accounts.json:ro trialbox-demo

* **`TB_DEMO_KEEP=1`** (`--keep`): the first start seeds (3 to 6 minutes) and writes `demo-state.json`; every later
  start reopens the same folder in seconds: accounts, authenticators, marks, notes, the delegation log, jobs and the
  audit log are kept, and the trial database lives in the folder (`<dir>/pg`). The REDCap simulator keeps its records
  from the last clean stop. To reset a site, start it once without `TB_DEMO_KEEP` (that deletes the folder).
* **`TB_DEMO_ACCOUNTS`** (`--accounts`): a JSON file kept outside the image and outside the repository (tester names
  never enter it). One entry per tester and role, never shared. Example with placeholder names:

      {"accounts": [
        {"username": "tester1.pi", "name": "Tester 1", "role": "investigator", "language": "ja",
         "expires": "2027-01-31", "delegation": [{"study": "GZQO", "role": "pi"}]},
        {"username": "tester1.subpi", "role": "investigator", "language": "ja", "expires": "2027-01-31",
         "delegation": [{"study": "GZQO", "role": "sub_pi", "tasks": ["screen", "refer"]}]},
        {"username": "tester1.crc", "role": "coordinator", "language": "ja", "expires": "2027-01-31",
         "delegation": [{"study": "GZQO", "role": "crc"}]},
        {"username": "owner", "role": "admin", "language": "en", "password_env": "TB_DEMO_OWNER_PASSWORD"}
      ]}

  `role` is the console role (admin, coordinator, investigator, viewer, cro); `language` (ja, zh-TW, en) is where the
  account lands after sign-in (`/lang` still changes it); `expires` ends the account and its log entries;
  `delegation` adds the account to a study's delegation log: `pi` (all tasks; one PI per study), `sub_pi` with only
  the ticked tasks (screen, approach, refer, enter_data), `crc` or `other`. The account sees only the studies it is
  logged on (or the `studies` list). A sub-investigator without the `approach` tick gets 403 on Approach, and only the
  logged PI approves criteria. The file holds no passwords: each account gets a random one, or the value of the
  environment variable its `password_env` names.
* **Second factor and first sign-in.** With an accounts file TOTP is on (`TB_CONSOLE_MFA=totp`). Each new account
  gets a one-time enrolment code for its authenticator. New passwords and codes are written to
  `<dir>/issued-credentials.txt` (owner-only file, never the log): hand each tester theirs out of band, then delete
  the file (`docker exec <id> rm /data/demo/issued-credentials.txt`). The first sign-in asks for the password, the
  enrolment code and a code from the authenticator, then a new password. A restart issues nothing again; the owner's
  admin account resets a lost authenticator or a lock on `/ops/identity`.
* The built-in accounts (one shared password) are switched off when an accounts file is used. Accounts are seeded
  only once: adding an entry and restarting adds that account; editing an existing entry changes nothing.
* `TB_CONSOLE_MFA`, `TB_CONSOLE_IDLE_MINUTES`, `TB_CONSOLE_SESSION_HOURS`, `TB_CONSOLE_TOTP_KEY_FILE`,
  `TB_CONSOLE_TOTP_ISSUER` and `TB_CONSOLE_SECURE_COOKIE` are read from the container's environment.
* **`TB_DEMO_DAY`** (`--day`, T-513, D-329): `today` by default. The demo day is the real day in the site's time zone
  (on a weekend, the Friday before). The synthetic dates are moved to it, and after the seed the pages follow the
  real clock, also after a `TB_DEMO_KEEP` restart. `data` keeps the data's own day (2026-11-02).

## Run it anywhere with Docker

    cd trialbox
    docker build -f demo/Dockerfile -t trialbox-demo .
    docker run -p 8080:8080 trialbox-demo

A fresh clone is enough: the build fetches the one CQL translator jar the compiler reads `FHIRHelpers-4.0.1.cql`
from, and checks the jar and the FHIRHelpers text against pinned sha256 sums. `make demo-bundle` runs `make jvm-deps`
first and uses the jar from `.cache/jvm`. With no `-e` flag the password is printed in the log (`docker logs`); add
`-e TB_DEMO_PASSWORD=...` to choose one. Open http://localhost:8080 when the log says "console on".

Sign-in cookies are Secure (`TB_CONSOLE_SECURE_COOKIE=1`). Browsers accept them on `http://localhost`; on any other
plain-http address add `-e TB_CONSOLE_SECURE_COOKIE=0`, and never share a plain-http link.

## Memory and start time (measured)

| What | Measured (T-501, 2026-11-10) | Budget (CI job `demo-boot` fails above it) |
| --- | --- | --- |
| Peak memory of the demo process (VmHWM) | 1.82 GB while seeding (local and CI); 0.80 GB once it serves | 2.5 GB |
| PostgreSQL in the container | about 0.15 GB | |
| First answer on `/login` after start | 166 s in CI (GitHub runner); 339 s locally under heavy load | 600 s |

Plan the host for 4 GB of memory and give it up to 10 minutes to start. A 2 GB host is too tight (the peak plus
PostgreSQL is close to 2 GB), and a 512 MB or 1 GB host cannot run it. The image is about 410 MB to pull.

## The PoC host on Google Cloud (T-509, D-330)

The clinician PoC runs on one VM (`e2-standard-4`, `asia-east1`) with two sites, `jp` (ja, Asia/Tokyo) and `tw`
(zh-TW, Asia/Taipei), at `https://jp.<domain>` and `https://tw.<domain>`. Everything is one script,
`deploy/gcp/poc-host.sh`; the VM's boot script is `deploy/gcp/hosted-demo-startup.sh`. Each paid step needs the
owner's yes (Q-03): a command without `--yes` only prints what it would run, and `--dry-run` does the same for any
command. `poc-host.sh cost` prints the estimate (about US$120 a month, US$0.17 an hour; prices from memory, check at
order).

* **Front door.** Cloudflare Access lets in only the addresses in `TB_POC_DOOR_EMAILS` (a one-time PIN by mail; no
  account needed). The VM has no open web port: a Cloudflare Tunnel (`cloudflared`) connects out, checks the Access
  token, and passes the request to Caddy, which refuses anything without the token. Without a front-door session
  the URL shows Cloudflare's sign-in page, never `/login`. The console's own sign-in, TOTP and per-tester accounts
  (above) stay behind it. SSH only through Google's IAP.
* **TLS.** The browser gets the public certificate of the real host name at Cloudflare's edge; the tunnel reaches
  Caddy over TLS (Caddy's own CA, checked by `cloudflared`). Secure cookies are on.
* **Image by digest.** `poc-host.sh image --yes` builds the image once, here, from a clean export of tag `poc-1`, and
  pushes it to Artifact Registry. The VM pulls that digest and never builds or clones. Caddy and `cloudflared` are
  pinned by digest too.
* **Kept data.** Each site keeps its folder (`TB_DEMO_KEEP=1`) on a separate persistent disk, so a restart, a stop
  or a rebuild of the VM keeps accounts, marks and feedback. A snapshot schedule copies the disk daily at 01:00
  Taipei and keeps 70 days.
* **No second factor on the PoC (D-424).** The owner chose sign-in by password alone for the PoC: the boot script sets
  `TB_DEMO_HOSTED=1` and `TB_CONSOLE_MFA=off`. The console writes `console.mfa_off` to the audit at each start and the
  sign-in page says "Second factor is off on this demo box" (en, ja, zh-TW). The same setting is refused in
  VALIDATION and PRODUCTION. To turn TOTP back on, see the table below; each tester then enrols at the next sign-in.

The owner's steps, once:

    export TB_POC_PROJECT=<project> TB_POC_DOMAIN=<domain on Cloudflare> TB_POC_ACCESS_TEAM=<Zero Trust team>
    export CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_ZONE_ID=... CLOUDFLARE_API_TOKEN=... TB_POC_DOOR_EMAILS=a@...,b@...
    gcloud secrets create tb-poc-accounts-jp --data-file=<the jp accounts file>    # format: section above
    gcloud secrets create tb-poc-accounts-tw --data-file=<the tw accounts file>
    printf %s "$OWNER_PASSWORD" | gcloud secrets create tb-poc-owner-password --data-file=-   # optional
    deploy/gcp/poc-host.sh image --yes     # once, from tag poc-1
    deploy/gcp/poc-host.sh door --yes      # tunnel, DNS names, Access; the tunnel token goes to Secret Manager
    deploy/gcp/poc-host.sh create --yes    # network, disk, snapshot schedule, VM

The first start seeds each site (3 to 6 minutes). The issued passwords and enrolment codes are on the VM in
`/srv/trialbox/<site>/demo/issued-credentials.txt`: read them with `gcloud compute ssh tb-poc --tunnel-through-iap`,
hand them out, then delete the file. Later:

| Need | Command |
| --- | --- |
| Destroy and rebuild the VM from the tag (the data disk stays; a snapshot first) | `poc-host.sh rebuild --yes` |
| Reset one site (it seeds afresh) | `poc-host.sh reset jp --yes` |
| What runs, the disk, the snapshots | `poc-host.sh status` |
| Turn the second factor back on (D-424) | `gcloud compute instances add-metadata tb-poc --zone asia-east1-b --metadata tb-console-mfa=totp`, then `gcloud compute instances reset tb-poc --zone asia-east1-b` (the boot script runs again; data is kept) |
| Pause the cost (disks and snapshots stay, about US$5 a month) | `gcloud compute instances stop tb-poc --zone asia-east1-b` |
| End of life: delete the VM, the disk, every snapshot, the image, the secrets and the Cloudflare entries, check nothing is left, write a record | `poc-host.sh purge --yes` |

Export the feedback before the purge (it is kept without names). The record names what was deleted and holds no
name or secret.

## Public link on Render

The repository root has `render.yaml`. It stays on the free plan, which cannot run this demo (512 MB, and it sleeps
after 15 minutes, which resets the data). A 4 GB plan is paid, and the owner decides on that cost first (question
Q-03); the hosted demo runs on the GCP VM (above). To use Render, change `plan:` to a 4 GB plan first. In Render: New, Blueprint, pick this repository, type a password for `TB_DEMO_PASSWORD`, Apply. The link
is `https://trialbox-demo-<id>.onrender.com`.

## Public link on Google Cloud Run

    gcloud run deploy trialbox-demo --source trialbox --region asia-northeast1 \
      --set-env-vars TB_DEMO_PASSWORD=choose-one --memory 4Gi --cpu 2 --min-instances 1 --max-instances 1 \
      --allow-unauthenticated

(Cloud Run builds `trialbox/Dockerfile` by default; pass the demo Dockerfile with a `cloudbuild.yaml` or build and
push the image first. The demo listens only after seeding, so give the start-up probe 10 minutes.) `--max-instances 1`
matters: each instance has its own data and sign-ins. Any paid host needs the owner's yes on the cost first.
