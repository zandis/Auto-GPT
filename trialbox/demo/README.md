# TrialBox role demo (synthetic hospital)

One container runs the whole box on the synthetic hospital (600 made-up patients, study GZQO) with one sign-in per
role: `admin`, `crc` (study coordinator), `pi` (investigator), `smo` (SMO coordinator, GZQO only, ends 2027-03-31),
`cra` (CRO, aggregate reports only) and `viewer`. All share `TB_DEMO_PASSWORD`. It uses a stub language model, so no
API key is needed and nothing leaves the container. Every restart rebuilds the data, so the demo resets.

Never load real patient data into it: it runs TB_ENV=DEV, data class D0. It is not a product image: it carries the
test helpers (the in-process box lives in `tests/`), which is why it sits outside `deploy/`, where every Dockerfile
is a product image that must never contain the Test Bench.

## Run it anywhere with Docker

    cd trialbox
    docker build -f demo/Dockerfile -t trialbox-demo .
    docker run -p 8080:8080 -e TB_DEMO_PASSWORD=choose-one -e TB_CONSOLE_SECURE_COOKIE=0 trialbox-demo

Open http://localhost:8080. (`TB_CONSOLE_SECURE_COOKIE=0` only for plain http on your own machine; behind https keep
the default.) About 250 MB of memory; start-up takes about 30 seconds.

## Public link on Render (free plan)

The repository root has `render.yaml`. In Render: New, Blueprint, pick this repository, type a password for
`TB_DEMO_PASSWORD`, Apply. The link is `https://trialbox-demo-<id>.onrender.com`. A free service sleeps after 15
minutes without visits and takes about a minute to wake.

## Public link on Google Cloud Run

    gcloud run deploy trialbox-demo --source trialbox --region asia-northeast1 \
      --set-env-vars TB_DEMO_PASSWORD=choose-one --memory 1Gi --max-instances 1 --allow-unauthenticated

(Cloud Run builds `trialbox/Dockerfile` by default; pass the demo Dockerfile with a `cloudbuild.yaml` or build and
push the image first.) `--max-instances 1` matters: each instance has its own data and sign-ins.
