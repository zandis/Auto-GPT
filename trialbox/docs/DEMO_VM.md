# The demo link on the cloud VM (step 5, D-111)

The demo is one image: `tools.demo` seeds the whole step 1–4 flow on the synthetic hospital (5,000 patients, notes in
JA, zh-TW and EN), runs the `e2e_simple` checks, prints them, and serves the console with one sign-in per role
(`admin`, `crc`, `pi`, `cra`, `viewer`; one password). Stub model, no network, no secrets, data class D0. A restart
resets it.

```sh
make demo                 # on any machine with the venv: http://127.0.0.1:8080
make demo-bundle          # Docker: builds trialbox-demo:step5 and writes dist/trialbox-demo.tar.gz
```

## Starting it on GCP (not done in step 5; owner's OK first)

The project already has a small CPU VM for this, `trialbox-demo` (e2-standard-4, asia-east1-b, about US$0.15 an hour
while running, stopped with its disk kept). With the owner's OK:

```sh
make demo-bundle
gcloud storage cp dist/trialbox-demo.tar.gz gs://<bucket>/trialbox-demo.tar.gz
gcloud compute instances add-metadata trialbox-demo --zone asia-east1-b \
  --metadata-from-file startup-script=deploy/gcp/demo-vm-startup.sh,tb-demo-password=/mnt/project-files/trialbox-demo/password.txt \
  --metadata tb-demo-image=gs://<bucket>/trialbox-demo.tar.gz
gcloud compute instances start trialbox-demo --zone asia-east1-b
gcloud compute instances get-serial-port-output trialbox-demo --zone asia-east1-b | grep -E 'TBD|DEMO-STARTUP-DONE'
# the link: http://<external IP>/  (firewall: tcp:80 from the people who should see it)
gcloud compute instances stop trialbox-demo --zone asia-east1-b   # when the demo is over
```

The VM's service account needs read access to the bucket. The startup script installs Docker, loads the image, runs it
on port 80 and logs the check list to the serial port. Plain http, so the image runs with
`TB_CONSOLE_SECURE_COOKIE=0`; put it behind https (a load balancer or Cloud Run) before sharing the link widely.

Cost: about US$0.15 an hour while it runs (US$3.60 a day), a few cents a month for the stopped disk and the image in
the bucket.

Cloud Run works too (`--max-instances 1`, `--memory 2Gi`, the image from the bundle); the first request after
idle waits about 70 seconds while the flow is seeded.
