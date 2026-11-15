# 9. Proof of concept with Docker

**Reader:** Aimedics (an other install form: a proof of concept on any Docker host).

`deploy/poc.sh` (`make poc`; Windows: `powershell -ExecutionPolicy Bypass -File deploy\poc.ps1`) runs the whole box on
synthetic data with test mail servers. It builds images when missing, writes random passwords, starts the stack,
creates the administrator (password printed once), ingests a 600-patient synthetic site and prints the URLs:
console <http://127.0.0.1:8090>, web mail (MailHog) <http://127.0.0.1:8025>, mail to the box on SMTP port 3025
(`tools/send_test_mail.py "FEAS GZQO" --sender admin@hospa.test`). `deploy/poc.sh status|down|reset`.

- **Modes** (`TB_LLM_MODE`): `stub` (default, no GPU), `openrouter` (DEV, D0 data only, key in `OPENROUTER_API_KEY`
  or `deploy/poc/secrets/openrouter_api_key`, given to the gateway only), `gpu` (needs the pin of §8).
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
