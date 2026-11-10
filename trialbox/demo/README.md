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

## Public link on Render

The repository root has `render.yaml`. It stays on the free plan, which cannot run this demo (512 MB, and it sleeps
after 15 minutes, which resets the data). A 4 GB plan is paid, and the owner decides on that cost first (question
Q-03); until then the hosted demo runs on the GCP VM. To use Render, change `plan:` to a 4 GB plan first. In Render: New, Blueprint, pick this repository, type a password for `TB_DEMO_PASSWORD`, Apply. The link
is `https://trialbox-demo-<id>.onrender.com`.

## Public link on Google Cloud Run

    gcloud run deploy trialbox-demo --source trialbox --region asia-northeast1 \
      --set-env-vars TB_DEMO_PASSWORD=choose-one --memory 4Gi --cpu 2 --min-instances 1 --max-instances 1 \
      --allow-unauthenticated

(Cloud Run builds `trialbox/Dockerfile` by default; pass the demo Dockerfile with a `cloudbuild.yaml` or build and
push the image first. The demo listens only after seeding, so give the start-up probe 10 minutes.) `--max-instances 1`
matters: each instance has its own data and sign-ins. Any paid host needs the owner's yes on the cost first.
