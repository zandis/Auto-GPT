# D-481 A service container holds its own database role's password and no other: the clears move into the base compose file, one check for the test and for `doctor`

- **Card:** T-712 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-712-db-passwords-own-role`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-378 (one database role per service), D-394 (the audit journal's one writer), D-450 (T-212d: the
  secrets overlay clears the eight `TB_DB_PW_*`; the rendered-compose test)
- **Closes:** finding F1 and proposal TR-1 of `docs/reviews/2026-11-12-architecture/trust.md` (what D-450 left open)

## The problem

D-378 gives each service its own PostgreSQL role. Its acceptance ("a service role cannot read another service's
schema") is true of the role and was not true of the container: every TrialBox service reads `deploy/.env` through
`env_file`, and that file holds every role's password and both administrator passwords. D-450 cleared them in
`deploy/docker-compose.secrets.yml`. What it left:

1. **The clears live in an overlay.** A stack started without the overlay (the PoC, `make test-compose`, the
   platform compose form, a hand-typed `docker compose up`) gives every container every password, and the
   services that open no database (`embed-service`, `doc-parser`) the host tools' administrator URL.
2. **The test that proves it can be skipped.** `tests/unit/test_compose_secret_reach.py` needs the `docker compose`
   plugin and is skipped without it; it renders eight file sets and not the PoC, the box, the platform or the
   two-device sets.
3. **A missing role password is silent.** Each `TB_DB_URL` falls back to the workflow administrator's password when
   its `TB_DB_PW_<SERVICE>` is not in `deploy/.env`. A box in that state runs, and every service holds the password
   of `trialbox`, the one member of `audit_writer` and of every schema group.
4. **Nothing looks at a box.** `trialbox doctor` does not check what the box's compose files or its running
   containers hold.

## The decision

1. **The clears are in the base file.** `deploy/docker-compose.yml` has one block, `x-no-db-passwords`, that sets
   `POSTGRES_PASSWORD`, `POSTGRES_WF_PASSWORD` and the eight `TB_DB_PW_*` to the empty string, and every TrialBox
   service of the base file merges it into its `environment`. A service receives its own role's password only
   inside its own `TB_DB_URL`. The services that open no database (`embed-service`, `doc-parser`, `llm-stub`) also
   clear `TB_DB_URL`, because `deploy/.env` carries the host tools' administrator URL. The secrets overlay no
   longer repeats these lines: one place, so the two files cannot drift. Every overlay that changes a base service
   (the PoC's console, the box, the GPU files) inherits the clears by compose's key-by-key merge.
2. **The platform compose form's `doctor`** is a container of its own with `env_file`. It is the operator's tool
   (it reads the flags and the site-key record with the host tools' URL, as `trialbox doctor` on the host does) and
   mounts no patient data: it keeps `TB_DB_URL` and is cleared of every service role's password and of HAPI's.
3. **One check, three users** (`tools/trialbox/db_secrets.py`).
   - `render(files, env)` gives the environment each service would be started with: the merge of several compose
     files (a service's `environment` key by key, its `env_file` lists joined, `!reset` and `!override`), the
     files of `env_file`, and `${NAME}` interpolation with its six forms. It is pure Python.
   - `reach_problems(config, secrets)` names every service whose environment holds a database password that is not
     its own, under any variable name, and every `TB_DB_URL` that signs in as another service's role. Holders: `db`
     (all), `fhir-store` (`POSTGRES_PASSWORD`), the platform `doctor` (`POSTGRES_WF_PASSWORD`), and each service
     its own `TB_DB_PW_<SERVICE>`.
   - `env_problems(env, services)` names a service role with no password of its own, an example value, and two
     roles with one password.
   - No function returns a password's value; a finding names the variable and the service.
4. **The test cannot be skipped.** `tests/unit/test_compose_db_passwords.py` renders sixteen file sets (the base
   alone, the test stack, the PoC, every GPU overlay, identity, the box, monitoring, acceptance, both two-device
   devices, the platform form) with `render` and fails on a finding. It needs no `docker`. Where the
   `docker compose` plugin exists, a further test holds `render` against `docker compose config` for the same
   sixteen sets, every service and every profile (plan v6.1 §5.3: a stand-in is made from the real thing). The
   older rendered test of D-450 stays: it covers the other secrets.
5. **`trialbox doctor` has the check `db_passwords`.** It reads `deploy/.env` (`env_problems`), renders the box's
   own compose files (`COMPOSE_FILE`, which `install.sh` writes; `--compose-config` when given) with the box's
   values, and reads the environment of the containers that run now (`docker inspect`), because a container
   started before a change keeps what it was given. FAIL in VALIDATION and PRODUCTION, WARN in DEV and TEST; not
   judged when no `--env-file` is given. This is the guard for problem 3: a box whose role passwords are missing
   fails `doctor` and is told to re-run `install.sh`, which makes them.
6. **`TB_DB_PW_` is a declared family** of settings (`tb_common.config.DECLARED_FAMILIES`).

## What it does not do

- **The passwords stay in `deploy/.env`.** Compose interpolates them into each `TB_DB_URL` and into the `db`
  container, and the host tools read the file. Moving each password to a file of its own (a compose secret per
  role, the URL built at start) removes the shared file as a place where they meet; it changes `install.sh`,
  `trialbox secrets rotate`, the db-init script and `tb_common.db`, and only a compose run on a box can prove
  it. T-718 (owner, writer and reader roles; migrations as an install step) changes the same files and is the
  place for it.
- **The fall-back in `TB_DB_URL` stays** (`${TB_DB_PW_X:-${POSTGRES_WF_PASSWORD:-...}}`): the test stack and the
  PoC run on `.env.example`, which has no role passwords. `doctor` fails a box in that state (5).
- **The Kubernetes form** (`deploy/platform/base/apps.yaml`) gives every pod one `TB_DB_URL` from the secret
  `trialbox-db`: D-378's roles are not in that form at all. It is the second install form (plan v6.1 §4.4, not
  developed further unless a site asks); listed as a finding.
- **A process inside a container still reads its own `TB_DB_URL`.** That is the service's own role, which is what
  D-378 intends; what a role may do to its tables is T-718.

## Consequences

- A stack started from the base file alone (a developer, the PoC, `make test-compose`) no longer hands the
  administrators' passwords to every container.
- A new service with `env_file` and no clears, or a new role with no password line, fails the unit test.
- On an installed box the next `install.sh` or `trialbox update` re-creates the containers with the same
  environment as before (the overlay already cleared these names there); nothing changes at run time.

## Dropped (D-311)

No security sign-off or owner review step.

## Review fixes (adversarial review of PR #308, 2026-11-12)

- **H1.** The doctor check passed without judging anything on the path sites use. Not judged is now WARN, and FAIL
  on a VALIDATION or PRODUCTION box. `deploy/check_host.sh`, which runs the doctor in the box's image, passes
  `--env-file /app/deploy/.env`; an entry of `COMPOSE_FILE` that is the host's absolute path is read as its part
  below `deploy/` in the folder given.
- **H2.** The platform's `doctor` container held the administrator's password and URL although it cannot reach the
  database. Both are cleared; no tool container is a holder of `POSTGRES_WF_PASSWORD`.
- **M1.** An empty `TB_ENV=` is PRODUCTION for this check, as everywhere (`tb_common.config.environment_name`).
- **LOW.** The schema `tuned` (the not-matched reasons) is on the orchestrator's and the console's role lists, both
  copies of the script; a stale paragraph of `svc_secrets.py` is corrected.

Not taken here (see the pull request): passwords on command lines (`psql -v pw_*=`, the backup's `--dbname`),
`secrets rotate --service db`, the role script after a restore or an update, the mode of `site/compose.json`, and
the least length of a value the reach check searches for.

