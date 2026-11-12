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
# * D-394 (T-211b): the audit journal (schema `audit`) and its roles, at the end; see tb_common/audit_writer.py.
# * D-465 (T-727): the orchestrator runs the opt-out worker, which erases the twin (`profile`, which it also builds)
#   and the vector store (`vec`, the lake's); so both are on its list.
# * D-486 (T-718): a schema on the `owned` list has three roles instead of the one group. `tbo_<schema>` owns it and
#   everything in it; its one member is `trialbox`. `tbw_<schema>` reads and writes its tables, `tbr_<schema>` reads
#   them; neither can create, alter or drop anything there, so a trigger that makes a table append-only holds
#   against the service that writes it. A service with the schema on its list is a member of `tbw_<schema>`. The
#   tables of such a schema are made by the install step (`python -m orchestrator.migrate`, as `trialbox`), not by
#   the service at start. First on the list: `edc`.
# * `tuned` (tb_common.notmatched: the not-matched reasons) is read and written by the orchestrator and the console.
# * D-541 (NEW-TRUST-1): the FHIR store signs in as `tb_fhir_store`, a role of its own (no superuser, no CREATEDB,
#   no CREATEROLE) that owns the database `hapi` and what is in it and reaches nothing else. Before, it signed in
#   as the cluster's superuser. Its password is read by psql from the environment (\getenv), not given on the
#   command line. On a box installed before D-541 the second part below moves what HAPI made as the superuser.
# The list is the one place that says which service reaches which schema; tests/unit/test_db_roles.py reads it.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${TB_WF_DB:-trialbox_wf}" \
  -v pw_lake="${TB_DB_PW_LAKE:-}" \
  -v pw_criteria_compiler="${TB_DB_PW_CRITERIA_COMPILER:-}" \
  -v pw_adapter="${TB_DB_PW_ADAPTER:-}" \
  -v pw_orchestrator="${TB_DB_PW_ORCHESTRATOR:-}" \
  -v pw_mail_gateway="${TB_DB_PW_MAIL_GATEWAY:-}" \
  -v pw_gateway="${TB_DB_PW_GATEWAY:-}" \
  -v pw_console="${TB_DB_PW_CONSOLE:-}" \
  -v pw_audit_writer="${TB_DB_PW_AUDIT_WRITER:-}" <<'SQL'
\set pw_fhir_store ''
\getenv pw_fhir_store TB_DB_PW_FHIR_STORE
ALTER ROLE trialbox NOCREATEDB;
-- BEGIN FHIR STORE ROLE (D-541)
DO $fhir$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tb_fhir_store') THEN
    CREATE ROLE tb_fhir_store LOGIN;
  END IF;
  ALTER ROLE tb_fhir_store NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = 'hapi') THEN
    ALTER DATABASE hapi OWNER TO tb_fhir_store;
  END IF;
END
$fhir$;
ALTER ROLE tb_fhir_store PASSWORD :'pw_fhir_store';
-- END FHIR STORE ROLE
DO $roles$
DECLARE
  -- BEGIN SERVICE SCHEMAS (D-378)
  -- D-461 (T-720): edc is the orchestrator's alone; the console reaches the EDC only through its routes
  access CONSTANT jsonb := '{
    "tb_lake": ["app", "omop", "refdata", "terminology", "vec"],
    "tb_criteria_compiler": ["app", "derived", "library", "omop", "refdata", "terminology"],
    "tb_adapter": ["app", "dataops", "derived", "mpi", "omop", "pidmap", "refdata", "sitesetup", "terminology"],
    "tb_orchestrator": ["app", "datacore", "dataops", "derived", "edc", "library", "mail", "mpi", "omop", "optout",
                        "orch", "pidmap", "profile", "recall", "refdata", "site", "sitesetup", "study", "terminology",
                        "tuned", "vec", "wf"],
    "tb_mail_gateway": ["app", "mail"],
    "tb_gateway": ["app", "trace"],
    "tb_console": ["app", "auth", "breakglass", "datacore", "dataops", "derived", "feedback", "library", "mpi", "omop",
                   "optout", "orch", "pidmap", "recall", "refdata", "sae", "site", "sitesetup", "study", "team",
                   "terminology", "tuned", "wf"]
  }';
  -- END SERVICE SCHEMAS
  -- BEGIN OWNED SCHEMAS (D-486)
  owned CONSTANT text[] := ARRAY['edc'];
  -- END OWNED SCHEMAS
  wr text;
  rd text;
  svc text;
  sch text;
  grp text;
  obj record;
BEGIN
  FOR sch IN SELECT DISTINCT jsonb_array_elements_text(v) FROM jsonb_each(access) AS e(k, v) ORDER BY 1 LOOP
    grp := CASE WHEN sch = ANY(owned) THEN 'tbo_' ELSE 'tbs_' END || sch;
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
    IF sch = ANY(owned) THEN
      -- D-486: functions too (a trigger's function belongs to the owner, or its writer could replace its body)
      FOR obj IN
        SELECT p.oid::regprocedure::text AS sig FROM pg_proc p
        WHERE p.pronamespace = sch::regnamespace AND p.proowner <> grp::regrole
      LOOP
        EXECUTE format('ALTER ROUTINE %s OWNER TO %I', obj.sig, grp);
      END LOOP;
      wr := 'tbw_' || sch;
      rd := 'tbr_' || sch;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = wr) THEN
        EXECUTE format('CREATE ROLE %I NOLOGIN', wr);
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = rd) THEN
        EXECUTE format('CREATE ROLE %I NOLOGIN', rd);
      END IF;
      EXECUTE format('GRANT %I, %I TO trialbox', wr, rd);
      EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', sch);
      EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I, %I', sch, wr, rd);
      EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I, %I', sch, wr, rd);
      -- a table with an append-only trigger (the migrate step made it a trail) takes INSERT only, and the version
      -- table no write: a rerun of this script must not give the writer back what that step took
      FOR obj IN
        SELECT c.relname AS name,
               EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND NOT t.tgisinternal
                       AND t.tgname = c.relname || '_append_only') AS trail
        FROM pg_class c WHERE c.relnamespace = sch::regnamespace AND c.relkind IN ('r', 'p')
      LOOP
        IF obj.name = '_schema_version' THEN
          EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON %I.%I FROM %I', sch, obj.name, wr);
        ELSIF obj.trail THEN
          EXECUTE format('GRANT INSERT ON %I.%I TO %I', sch, obj.name, wr);
          EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %I.%I FROM %I', sch, obj.name, wr);
        ELSE
          EXECUTE format('GRANT INSERT, UPDATE, DELETE ON %I.%I TO %I', sch, obj.name, wr);
        END IF;
      END LOOP;
      EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', sch, wr);
      -- what the migrate step makes later (as the owner) gets the same rights; the step narrows a trail table
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO %I, %I',
                     grp, sch, wr, rd);
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT INSERT, UPDATE, DELETE ON TABLES TO %I',
                     grp, sch, wr);
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
                     grp, sch, wr);
      -- the owner has exactly one member, the host tools' admin: no service can become it
      FOR obj IN SELECT pg_get_userbyid(member) AS who, pg_get_userbyid(grantor) AS by FROM pg_auth_members
                 WHERE roleid = grp::regrole AND member <> 'trialbox'::regrole LOOP
        EXECUTE format('REVOKE %I FROM %I GRANTED BY %I', grp, obj.who, obj.by);
      END LOOP;
    END IF;
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
      EXECUTE format('GRANT %I TO %I', CASE WHEN sch = ANY(owned) THEN 'tbw_' ELSE 'tbs_' END || sch, svc);
    END LOOP;
    -- a schema taken off a service's list is taken from the role on the next run
    FOR grp IN
      SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
      WHERE m.member = svc::regrole AND r.rolname LIKE 'tbs\_%'
        AND (NOT ((access -> svc) ? substr(r.rolname, 5)) OR substr(r.rolname, 5) = ANY(owned))
    LOOP
      EXECUTE format('REVOKE %I FROM %I', grp, svc);
      -- D-486: a session the service opened as a member of the old group of an owned schema still works as that
      -- group (SET ROLE), which has lost the schema: end it, so the service reconnects with the writer's role
      IF substr(grp, 5) = ANY(owned) THEN
        PERFORM pg_terminate_backend(a.pid) FROM pg_stat_activity a
          WHERE a.usename = svc AND a.pid <> pg_backend_pid();
      END IF;
    END LOOP;
    -- D-486: and a writer's or reader's role of a schema that left the service's list
    FOR grp IN
      SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
      WHERE m.member = svc::regrole AND (r.rolname LIKE 'tbw\_%' OR r.rolname LIKE 'tbr\_%')
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
-- D-394 (T-211b, CR-042): one audit writer. The services may only call audit.append; the journal is append-only and
-- belongs to audit_writer, which nobody signs in as and no service can become (trialbox, the host admin, is its one
-- member); tb_audit_writer (the audit-writer service, which copies the journal into the hash chain) only reads it. Kept equal to tb_common.audit_writer.JOURNAL_SQL.
-- BEGIN AUDIT WRITER (D-394)
DO $aw$
DECLARE
  m record;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'audit_writer') THEN
    CREATE ROLE audit_writer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tb_audit_writer') THEN
    CREATE ROLE tb_audit_writer LOGIN;
  END IF;
  -- no service acts as the journal's owner: its one member is trialbox, the host tools' admin (backup, restore),
  -- as for every store group of D-378
  FOR m IN SELECT pg_get_userbyid(member) AS who, pg_get_userbyid(grantor) AS by FROM pg_auth_members
           WHERE roleid = 'audit_writer'::regrole AND member <> 'trialbox'::regrole LOOP
    EXECUTE format('REVOKE audit_writer FROM %I GRANTED BY %I', m.who, m.by);
  END LOOP;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO tb_audit_writer', current_database());
END
$aw$;
GRANT audit_writer TO trialbox;
ALTER ROLE audit_writer NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE tb_audit_writer LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION audit_writer;
ALTER SCHEMA audit OWNER TO audit_writer;
REVOKE ALL ON SCHEMA audit FROM PUBLIC;
SET search_path = audit, pg_catalog;
CREATE TABLE IF NOT EXISTS journal (
  seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(),
  db_role text NOT NULL,
  event text NOT NULL CHECK (event <> ''),
  ts text NOT NULL,
  fields jsonb NOT NULL
);
RESET search_path;
ALTER TABLE audit.journal OWNER TO audit_writer;
CREATE OR REPLACE FUNCTION audit.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  RAISE EXCEPTION 'audit.journal is append-only (D-394): % refused', TG_OP USING ERRCODE = 'insufficient_privilege';
END
$fn$;
ALTER FUNCTION audit.refuse_change() OWNER TO audit_writer;
DROP TRIGGER IF EXISTS journal_append_only ON audit.journal;
CREATE TRIGGER journal_append_only BEFORE UPDATE OR DELETE ON audit.journal
  FOR EACH ROW EXECUTE FUNCTION audit.refuse_change();
DROP TRIGGER IF EXISTS journal_no_truncate ON audit.journal;
CREATE TRIGGER journal_no_truncate BEFORE TRUNCATE ON audit.journal
  FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_change();
REVOKE ALL ON audit.journal FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON audit.journal FROM audit_writer;
CREATE OR REPLACE FUNCTION audit.append(p_event text, p_ts text, p_fields jsonb) RETURNS bigint
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  n bigint;
BEGIN
  -- one at a time, to the end of the transaction: seq order is commit order, so the drain passes no row over
  PERFORM pg_advisory_xact_lock(211394);
  INSERT INTO audit.journal (db_role, event, ts, fields)
    VALUES (session_user, p_event, p_ts, coalesce(p_fields, '{}'::jsonb)) RETURNING seq INTO n;
  PERFORM pg_notify('tb_audit', n::text);
  RETURN n;
END
$fn$;
ALTER FUNCTION audit.append(text, text, jsonb) OWNER TO audit_writer;
REVOKE ALL ON FUNCTION audit.append(text, text, jsonb), audit.refuse_change() FROM PUBLIC;
GRANT USAGE ON SCHEMA audit TO tb_lake, tb_criteria_compiler, tb_adapter, tb_orchestrator, tb_mail_gateway,
  tb_gateway, tb_console, tb_audit_writer, trialbox;
GRANT EXECUTE ON FUNCTION audit.append(text, text, jsonb) TO tb_lake, tb_criteria_compiler, tb_adapter,
  tb_orchestrator, tb_mail_gateway, tb_gateway, tb_console;
-- the drain reads the journal; trialbox (backups) reads it; nobody else does
GRANT SELECT ON audit.journal TO tb_audit_writer, trialbox;
-- END AUDIT WRITER
ALTER ROLE tb_audit_writer PASSWORD :'pw_audit_writer';
SQL
# D-541: inside `hapi`, what HAPI made while it signed in as the superuser becomes the FHIR store's own (tables with
# their indexes, sequences, views, the schema `public`, large objects). Idempotent; a new box has nothing to move.
if psql -tA --username "$POSTGRES_USER" --dbname postgres -c "SELECT 1 FROM pg_database WHERE datname = 'hapi'" | grep -q 1; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname hapi <<'SQL'
DO $own$
DECLARE
  obj record;
  kinds CONSTANT jsonb := '{"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW", "S": "SEQUENCE", "f": "FOREIGN TABLE"}';
BEGIN
  ALTER SCHEMA public OWNER TO tb_fhir_store;
  GRANT ALL ON SCHEMA public TO tb_fhir_store;
  FOR obj IN
    SELECT n.nspname AS sch, c.relname AS name, c.relkind::text AS kind
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast') AND n.nspname NOT LIKE 'pg\_temp%'
      AND c.relowner <> 'tb_fhir_store'::regrole
      AND (c.relkind IN ('r', 'p', 'v', 'm', 'f') OR (c.relkind = 'S' AND NOT EXISTS (
            SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
              AND d.deptype IN ('a', 'i'))))
      AND NOT EXISTS (SELECT 1 FROM pg_depend e WHERE e.classid = 'pg_class'::regclass AND e.objid = c.oid
                        AND e.deptype = 'e')
  LOOP
    EXECUTE format('ALTER %s %I.%I OWNER TO tb_fhir_store', kinds ->> obj.kind, obj.sch, obj.name);
  END LOOP;
  FOR obj IN SELECT oid FROM pg_largeobject_metadata WHERE lomowner <> 'tb_fhir_store'::regrole LOOP
    EXECUTE format('ALTER LARGE OBJECT %s OWNER TO tb_fhir_store', obj.oid);
  END LOOP;
END
$own$;
SQL
fi
