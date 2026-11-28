# 9. Proof of concept with Docker

**Reader:** Aimedics (an other install form: a proof of concept on any Docker host).

`deploy/poc.sh` (`make poc`; Windows: `powershell -ExecutionPolicy Bypass -File deploy\poc.ps1`) runs the whole box on
synthetic data with test mail servers. It builds images when missing, writes random passwords, starts the stack,
creates the administrator (password printed once), ingests a 600-patient synthetic site and prints the URLs:
console <http://127.0.0.1:8090>, web mail (MailHog) <http://127.0.0.1:8025>, mail to the box on SMTP port 3025
(`tools/send_test_mail.py "FEAS GZQO" --sender admin@hospa.test`). `deploy/poc.sh status|down|reset`.

- **Modes** (`TB_LLM_MODE`): `stub` (default, no GPU), `openrouter` (DEV, D0 data only, gateway key), `gpu` (needs the pin of §8).
  For OpenRouter, enter the key in your own Bash shell. Using `sudo VAR=value command` shows the value in the process list.

  ```bash
  read -rs OPENROUTER_API_KEY; export OPENROUTER_API_KEY
  sudo --preserve-env=OPENROUTER_API_KEY TB_LLM_MODE=openrouter deploy/poc.sh
  unset OPENROUTER_API_KEY
  ```
- **The weights folder (gpu mode, D-896):** the weights go in `deploy/models`, or anywhere with
  `TB_MODELS_DIR=<folder>` given once: `poc.sh` keeps it in `deploy/.env`, so a restart, the next run, `trialbox
  doctor` and `deploy/check_weights.sh` read the same folder. Do not bind-mount the weights onto `deploy/models` by
  hand: the bind is gone after a reboot and the models start on an empty folder (`poc.sh` warns on one).
- **A real mailbox:** set `IMAP_*`, `SMTP_*`, `MAIL_INTAKE_ADDR`, `MAIL_FROM_ADDR`, `TB_MAIL_AUTHSERV_ID` and app
  passwords in `deploy/.env` (mode 600), then `TB_POC_MAIL=real deploy/poc.sh`.
- **Remote access:** the console binds to 127.0.0.1. Put a TLS proxy in front (Caddy: `reverse_proxy 127.0.0.1:8090`;
  nginx: `proxy_set_header X-Forwarded-Proto https`), set `TB_CONSOLE_SECURE_COOKIE=1`, and limit it to a VPN.
- **Checks:** `make test-console`, and with the POC up `make test-console-e2e`.
- **The developer test stack** (Docker 27+, about 15 GB): `make images`, `make up-test` (box, stub, GreenMail on
  IMAP 3143 and SMTP 3025, MailHog on 8025), `make ingest-test`, then `.venv/bin/python tools/send_test_mail.py "FEAS
  GZQO"`; the reply with the PDF and XLSX shows in MailHog within seconds. `make test-integration` and `make test-e2e`
  run against it; `make down` stops it.
- Ports taken: `TB_HOST_CONSOLE_PORT`, `TB_HOST_MAILHOG_PORT`, `TB_HOST_SMTP_PORT`. "No snapshot": run the ingest
  (`console.cli ingest`).
- **Loading one workbook** (proof of concept): fill the template `services/adapter/mapping/jp_core/poc_workbook_template.xlsx`
  (nine sheets with Japanese headers, one example row each, all marked `SYN-`: replace them), then
  `adapter run --source xlsx --path <workbook.xlsx> --mapping mapping/jp_core/poc_workbook.yaml`. The case number
  (症例番号) is the patient key; the birth is the year and month (生年月, e.g. 1948-05). A cell that is a formula leaves
  its row out and the run report says so; a sheet the workbook lacks is reported as missing. The example rows are test
  data: do not load the template into a box that holds real patients.
