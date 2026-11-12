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
# * `tuned` (tb_common.notmatched: the not-matched reasons) is read and written by the orchestrator and the console.
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
ALTER ROLE trialbox NOCREATEDB;
DO $roles$
DECLARE
  -- BEGIN SERVICE SCHEMAS (D-378)
  -- D-461 (T-720): edc is the orchestrator's alone; the console reaches the EDC only through its routes
  access CONSTANT jsonb := '{
    "tb_lake": ["app", "omop", "refdata", "terminology", "vec"],
    "tb_criteria_compiler": ["app", "derived", "library", "omop", "refdata", "terminology"],
    "tb_adapter": ["app", "dataops", "derived", "mpi", "omop", "pidmap", "refdata", "sitesetup", "terminology"],
    "tb_orchestrator": ["app", "breakglass", "datacore", "dataops", "derived", "edc", "library", "mail", "mpi",
                        "omop", "optout", "orch", "pidmap", "profile", "recall", "refdata", "site", "sitesetup",
                        "study", "team", "terminology", "tuned", "vec"],
    "tb_mail_gateway": ["app", "mail"],
    "tb_gateway": ["app", "trace"],
    "tb_console": ["app", "auth", "breakglass", "datacore", "dataops", "derived", "feedback", "library", "mpi", "omop",
                   "optout", "orch", "pidmap", "recall", "refdata", "sae", "site", "sitesetup", "study", "team",
                   "terminology", "tuned"]
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
    -- D-573: functions, procedures and aggregates too (a restore makes them trialbox's, as it does the tables);
    -- what an extension owns stays the extension's
    FOR obj IN
      SELECT p.oid::regprocedure::text AS sig, p.prokind FROM pg_proc p
      WHERE p.pronamespace = sch::regnamespace AND p.proowner <> grp::regrole
        AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                                                    AND d.deptype = 'e')
    LOOP
      EXECUTE format('ALTER %s %s OWNER TO %I',
                     CASE obj.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END,
                     obj.sig, grp);
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
