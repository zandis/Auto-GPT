#!/bin/sh
# D-378 (T-212c, CR-037): one PostgreSQL role per TrialBox service, each reaching only its own schemas of
# `trialbox_wf`. Runs once on an empty volume, after 10-trialbox-wf.sh and 20-extensions.sh; idempotent, so
# deploy/install.sh runs it again on every install or upgrade (an older volume gets the roles, and schemas made
# before D-378 move to their groups).
#
# * Every store schema below is owned by a group role `tbs_<schema>` (NOLOGIN). A service role `tb_<service>` (LOGIN,
#   no CREATEDB, CREATEROLE, REPLICATION or BYPASSRLS) is a member of the groups of the schemas in its list and of no
#   other: it cannot read or change another service's schema. tb_common.db sets the role to the group on connect, so
#   the tables a migration makes belong to the group.
# * `trialbox` (the host tools: backup, update, doctor) keeps the database and is a member of every group and every
#   service role, so a dump and a restore still see everything. CREATEDB is taken from it (CR-037).
# * Each service role's password comes from the environment (TB_DB_PW_<SERVICE>, deploy/.env; never committed). An
#   empty one leaves the role without a password (it cannot sign in over TCP).
# * Nobody but its owner connects to `hapi` (the FHIR store); only `trialbox` and the roles here connect to
#   `trialbox_wf`.
# The list is the one place that says which service reaches which schema; tests/unit/test_db_roles.py reads it.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${TB_WF_DB:-trialbox_wf}" \
  -v pw_lake="${TB_DB_PW_LAKE:-}" \
  -v pw_criteria_compiler="${TB_DB_PW_CRITERIA_COMPILER:-}" \
  -v pw_adapter="${TB_DB_PW_ADAPTER:-}" \
  -v pw_orchestrator="${TB_DB_PW_ORCHESTRATOR:-}" \
  -v pw_mail_gateway="${TB_DB_PW_MAIL_GATEWAY:-}" \
  -v pw_gateway="${TB_DB_PW_GATEWAY:-}" \
  -v pw_console="${TB_DB_PW_CONSOLE:-}" <<'SQL'
ALTER ROLE trialbox NOCREATEDB;
DO $roles$
DECLARE
  -- BEGIN SERVICE SCHEMAS (D-378)
  access CONSTANT jsonb := '{
    "tb_lake": ["app", "omop", "refdata", "terminology"],
    "tb_criteria_compiler": ["app", "derived", "library", "omop", "refdata", "terminology"],
    "tb_adapter": ["app", "derived", "mpi", "omop", "pidmap", "refdata", "sitesetup", "terminology"],
    "tb_orchestrator": ["app", "datacore", "derived", "edc", "library", "mail", "mpi", "omop", "optout", "orch",
                        "pidmap", "recall", "refdata", "site", "sitesetup", "study", "terminology", "wf"],
    "tb_mail_gateway": ["app", "mail"],
    "tb_gateway": ["app", "trace"],
    "tb_console": ["app", "auth", "breakglass", "datacore", "derived", "edc", "feedback", "library", "mpi", "omop",
                   "optout", "orch", "pidmap", "recall", "refdata", "sae", "site", "sitesetup", "study", "team",
                   "terminology", "wf"]
  }';
  -- END SERVICE SCHEMAS
  svc text;
  sch text;
  grp text;
  obj record;
BEGIN
  FOR sch IN SELECT DISTINCT jsonb_array_elements_text(v) FROM jsonb_each(access) AS e(k, v) ORDER BY 1 LOOP
    grp := 'tbs_' || sch;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = grp) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', grp);
    END IF;
    EXECUTE format('GRANT %I TO trialbox', grp);
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I', sch, grp);
    EXECUTE format('ALTER SCHEMA %I OWNER TO %I', sch, grp);
    -- what an earlier release made in the schema (as trialbox) moves to the group; owned sequences follow their table
    FOR obj IN
      SELECT c.relname, c.relkind FROM pg_class c
      WHERE c.relnamespace = sch::regnamespace AND c.relowner <> grp::regrole
        AND (c.relkind IN ('r', 'p', 'v', 'm', 'f')
             OR (c.relkind = 'S' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                                                 AND d.objid = c.oid AND d.deptype IN ('a', 'i'))))
    LOOP
      EXECUTE format('ALTER %s %I.%I OWNER TO %I',
                     CASE obj.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE'
                                      WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END,
                     sch, obj.relname, grp);
    END LOOP;
  END LOOP;
  FOR svc IN SELECT jsonb_object_keys(access) LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = svc) THEN
      EXECUTE format('CREATE ROLE %I LOGIN', svc);
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', svc);
    EXECUTE format('GRANT %I TO trialbox', svc);
    -- CREATE: a service may make a new schema of its own (a rerun's scratch schema); it reads no other
    EXECUTE format('GRANT CONNECT, TEMPORARY, CREATE ON DATABASE %I TO %I', current_database(), svc);
    FOR sch IN SELECT jsonb_array_elements_text(access -> svc) LOOP
      EXECUTE format('GRANT %I TO %I', 'tbs_' || sch, svc);
    END LOOP;
    -- a schema taken off a service's list is taken from the role on the next run
    FOR grp IN
      SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
      WHERE m.member = svc::regrole AND r.rolname LIKE 'tbs\_%'
        AND NOT ((access -> svc) ? substr(r.rolname, 5))
    LOOP
      EXECUTE format('REVOKE %I FROM %I', grp, svc);
    END LOOP;
  END LOOP;
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = 'hapi') THEN
    REVOKE ALL ON DATABASE hapi FROM PUBLIC;
  END IF;
END
$roles$;
ALTER ROLE tb_lake PASSWORD :'pw_lake';
ALTER ROLE tb_criteria_compiler PASSWORD :'pw_criteria_compiler';
ALTER ROLE tb_adapter PASSWORD :'pw_adapter';
ALTER ROLE tb_orchestrator PASSWORD :'pw_orchestrator';
ALTER ROLE tb_mail_gateway PASSWORD :'pw_mail_gateway';
ALTER ROLE tb_gateway PASSWORD :'pw_gateway';
ALTER ROLE tb_console PASSWORD :'pw_console';
SQL
