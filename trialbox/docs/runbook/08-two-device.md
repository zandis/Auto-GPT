# RUNBOOK §8 section: the Spark and a workstation, two devices (D-373)

Form A of the Japan hardware (TB-PLAN-05 §1.5): the DGX Spark runs the gateway and the two models; a CPU workstation
runs the database, the lake, HAPI, the services and the console. One encrypted link joins them. Not yet run on a real
Spark: every limit in `deploy/gb10-profile.yaml` is unmeasured until the benchmark record replaces it.

## The install ceremony (once, both devices present)

```sh
python -m tools.two_device certs --out /media/usb/link      # ca.pem, spark.pem/.key, workstation.pem/.key
```

Copy `ca.pem` and the Spark's own pair to `deploy/secrets/link/` on the Spark, and `ca.pem` and the workstation's
pair to the same folder on the workstation. Each key file is `0600`, owned by uid 10001 (`sudo chown 10001:10001`).
The CA key is never written: a replaced device means a new ceremony on both. Wipe the stick afterwards.

## deploy/.env on each device

| Variable | Spark | Workstation |
| --- | --- | --- |
| `TB_LINK_ROLE` | `spark` | `workstation` |
| `TB_LINK_ADDR` | the Spark's address on the hospital network | the workstation's |
| `TB_LINK_PEER` | the workstation's address | the Spark's |
| `TB_LINK_PORT` | 8443 unless hospital IT gives another | the same |

Ask hospital IT for one rule each way: the peer's address only, to `TB_LINK_PORT` only.

## Start and check

```sh
# Spark
cd deploy && docker compose -f docker-compose.yml -f docker-compose.secrets.yml -f docker-compose.gb10.yml \
    -f two-device/docker-compose.spark.yml --profile gpu up -d --wait gateway model-guard llm-service llm-verifier link
# workstation
cd deploy && docker compose -f docker-compose.yml -f docker-compose.secrets.yml \
    -f two-device/docker-compose.workstation.yml up -d --wait db fhir-store lake embed-service doc-parser \
    criteria-compiler adapter orchestrator mail-gateway console link
# each device: put the same -f list in COMPOSE_FILE (deploy/.env, separated by ':'), then
python -m tools.trialbox doctor --env-file deploy/.env --two-device
```

`doctor --two-device` fails when anything but the link publishes a port on the Spark (a gateway on 0.0.0.0 among
them), when the database runs on the Spark or a model on the workstation, when the link has no peer, certificates or
route, or when a Spark memory limit differs from the profile. It warns when the driver re-test of D-373 is past due.

| Symptom | Fix |
| --- | --- |
| `link: refused: the certificate does not name the peer device` | the other device holds the wrong pair: copy its own from the ceremony |
| link log shows `SSLError` on every call | the two devices hold pairs of different ceremonies: run the ceremony again |
| gateway calls from the workstation time out | the hospital rule for `TB_LINK_PORT`, or `TB_LINK_PEER` on the workstation |
| a service is killed with exit 137 on the Spark | its memory limit: record the peak (`docker stats`) for the benchmark record, then raise it in the profile and the compose file together |
