# TrialBox demo (synthetic hospital)

One container runs the whole box on the synthetic hospital (made-up patients, studies GZQO and GOUT-COH). The default
tool (`TB_DEMO_TOOL=demo`) seeds and checks the whole step 1 to 4 flow, then serves the console with one sign-in per
role: `admin`, `crc` (study coordinator), `pi` (investigator), `subpi` (sub-investigator on GZQO), `cra` (CRO,
aggregate reports only) and `viewer`. All share one password: `TB_DEMO_PASSWORD`, or a random one printed in the log
when it is not set. It uses a stub language model, so no API key is needed and nothing leaves the container. Every
restart rebuilds the data, so the demo resets (persistence is card T-505b).

The older role-only demo (`TB_DEMO_TOOL=role_demo`, 600 patients, study GZQO) has `smo` (SMO coordinator, GZQO only,
ends 2027-03-31) in place of `subpi`.

Never load real patient data into it: it runs TB_ENV=DEV, data class D0. It is not a product image: it carries the
test helpers (the in-process box lives in `tests/`), which is why it sits outside `deploy/`, where every Dockerfile
is a product image that must never contain the Test Bench. It does not carry `docs/reviews`.

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

The repository root has `render.yaml`. It asks for the `pro` plan (4 GB), which is paid: the owner decides on the
cost first (question Q-03). The free plan cannot run this demo (512 MB, and it sleeps after 15 minutes, which resets
the data). In Render: New, Blueprint, pick this repository, type a password for `TB_DEMO_PASSWORD`, Apply. The link
is `https://trialbox-demo-<id>.onrender.com`.

## Public link on Google Cloud Run

    gcloud run deploy trialbox-demo --source trialbox --region asia-northeast1 \
      --set-env-vars TB_DEMO_PASSWORD=choose-one --memory 4Gi --cpu 2 --min-instances 1 --max-instances 1 \
      --allow-unauthenticated

(Cloud Run builds `trialbox/Dockerfile` by default; pass the demo Dockerfile with a `cloudbuild.yaml` or build and
push the image first. The demo listens only after seeding, so give the start-up probe 10 minutes.) `--max-instances 1`
matters: each instance has its own data and sign-ins. Any paid host needs the owner's yes on the cost first.
