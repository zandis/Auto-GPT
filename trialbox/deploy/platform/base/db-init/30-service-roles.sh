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
# * D-872 (NEW-ARCH-3, after D-864 and D-865): `omop` and `sitesetup` are off the console's list: the console reads
#   the clinical conflicts and the instrument switches over the orchestrator's routes and opens neither store.
# * D-543 (NEW-ARCH-18): `profile` (the patient twin, built by the orchestrator) is on the console's list too: the
#   console reads it for `GET /api/v1/studies/{rs}/patients/{pid}/twin` (it could not open the store on a box).
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
-- an empty variable sets nothing: a run without it (the script by hand, in a database container started before the
-- variable existed) must not take away a password that is set
SELECT :'pw_fhir_store' <> '' AS has_fhir_pw \gset
\if :has_fhir_pw
ALTER ROLE tb_fhir_store PASSWORD :'pw_fhir_store';
\endif
-- END FHIR STORE ROLE
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
    "tb_console": ["app", "auth", "breakglass", "datacore", "derived", "edcdoor", "feedback", "library", "mpi",
                   "optout", "orch", "pidmap", "profile", "recall", "refdata", "sae", "site", "study",
                   "team", "terminology", "tuned"]
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
    -- D-683: a store that works in temporary tables (the OMOP load) does so as its group (tb_common.db sets the
    -- role), and PUBLIC loses the right below: the tbs_ group holds it, as its member services do. TEMPORARY only,
    -- never CREATE. Not an owned schema's roles (D-486): a service's session there stays the service itself
    IF NOT sch = ANY(owned) THEN
      EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO %I', current_database(), grp);
    END IF;
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
    IF sch = ANY(owned) THEN
      -- D-486: its functions are the owner's already (the loop above): a writer cannot replace a trigger's body
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
-- D-989 step 2c (D-997): the provenance index, derived from the audit chain and rebuilt from it
-- (tb_common.provenance_index). Its own schema, owned like the journal by audit_writer. The drain
-- (tb_audit_writer) writes the rows; the console and the orchestrator read them; the orchestrator, which runs the
-- opt-out worker (D-465), deletes a patient's use rows; trialbox (the host's rebuild and check) acts as the owner,
-- audit_writer, whose one member it is (as for the journal).
-- Kept equal to tb_common.provenance_index.INDEX_SQL.
-- BEGIN PROVENANCE INDEX (D-989)
CREATE SCHEMA IF NOT EXISTS provenance;
SET search_path = provenance, pg_catalog;
CREATE TABLE IF NOT EXISTS model_calls (
  rec_hash text NOT NULL,
  call_id text NOT NULL,
  model text NOT NULL DEFAULT '',
  build_sha text NOT NULL DEFAULT '',
  prompt_id text NOT NULL DEFAULT '',
  prompt_version text NOT NULL DEFAULT '',
  prompt_sha text NOT NULL DEFAULT '',
  at timestamptz NOT NULL,
  PRIMARY KEY (rec_hash, call_id)
);
CREATE INDEX IF NOT EXISTS model_calls_call ON model_calls (call_id);
CREATE INDEX IF NOT EXISTS model_calls_build ON model_calls (build_sha);
CREATE INDEX IF NOT EXISTS model_calls_prompt_sha ON model_calls (prompt_sha);
CREATE INDEX IF NOT EXISTS model_calls_prompt ON model_calls (prompt_id, prompt_version);
CREATE INDEX IF NOT EXISTS model_calls_model ON model_calls (model);
CREATE TABLE IF NOT EXISTS model_uses (
  rec_hash text NOT NULL,
  call_id text NOT NULL,
  event text NOT NULL CHECK (event IN ('used', 'confirmed')),
  record_kind text NOT NULL,
  record_ref text NOT NULL,
  pid text,
  decision text,
  by_whom text,
  at timestamptz NOT NULL,
  PRIMARY KEY (rec_hash, call_id)
);
CREATE INDEX IF NOT EXISTS model_uses_call ON model_uses (call_id);
CREATE INDEX IF NOT EXISTS model_uses_pid ON model_uses (pid);
RESET search_path;
-- P-19: the opt-out register (optout.optout_events) is the one authority on which use rows stay out, asked inside
-- the database on every insert. The role script gives the three functions to provenance_keeper, the one role that
-- may read the register here, and grants EXECUTE (D-997's grants live there, as the tables' owner does).
-- A use row of time p_at is withheld while the patient's opt-out is in force, and when its event is not after the
-- latest lift (rows erased before a lift stay erased; a back-dated row falls on the withheld side). No register
-- table yet: nobody has opted out (tb_common.optout.opted_out reads it the same way)
CREATE OR REPLACE FUNCTION provenance.withheld(p_pid text, p_at timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  last_action text;
BEGIN
  IF p_pid IS NULL OR NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                  WHERE n.nspname = 'optout' AND c.relname = 'optout_events') THEN
    RETURN false;
  END IF;
  SELECT e.action INTO last_action FROM optout.optout_events e WHERE e.pid = p_pid ORDER BY e.at DESC, e.id DESC
    LIMIT 1;
  IF last_action IS NULL THEN
    RETURN false;
  END IF;
  RETURN last_action = 'opt_out' OR coalesce(p_at <= (SELECT max(e.at)::timestamptz FROM optout.optout_events e
                                                       WHERE e.pid = p_pid AND e.action = 'lift'), true);
END
$fn$;
-- the lock (apart from audit.append's 211394) orders an insert against the console's opt-out transaction
CREATE OR REPLACE FUNCTION provenance.withhold() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  PERFORM pg_advisory_xact_lock(211989);
  IF NEW.pid IS NOT NULL AND provenance.withheld(NEW.pid, NEW.at) THEN
    RETURN NULL;
  END IF;
  RETURN NEW;
END
$fn$;
CREATE OR REPLACE TRIGGER model_uses_withhold BEFORE INSERT ON provenance.model_uses
  FOR EACH ROW EXECUTE FUNCTION provenance.withhold();
-- what pg_restore loaded before the trigger existed, and what slipped in before a register row committed
CREATE OR REPLACE FUNCTION provenance.sweep() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  n integer := 0;
BEGIN
  PERFORM pg_advisory_xact_lock(211989);
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'optout' AND c.relname = 'optout_events') THEN
    DELETE FROM provenance.model_uses u
      WHERE u.pid IN (SELECT e.pid FROM optout.optout_events e) AND provenance.withheld(u.pid, u.at);
    GET DIAGNOSTICS n = ROW_COUNT;
  END IF;
  RETURN n;
END
$fn$;
REVOKE ALL ON FUNCTION provenance.withheld(text, timestamptz), provenance.withhold(), provenance.sweep()
  FROM PUBLIC;
-- END PROVENANCE INDEX
ALTER SCHEMA provenance OWNER TO audit_writer;
ALTER TABLE provenance.model_calls OWNER TO audit_writer;
ALTER TABLE provenance.model_uses OWNER TO audit_writer;
REVOKE ALL ON SCHEMA provenance FROM PUBLIC;
REVOKE ALL ON provenance.model_calls, provenance.model_uses FROM PUBLIC;
GRANT USAGE ON SCHEMA provenance TO tb_audit_writer, tb_console, tb_orchestrator;
GRANT SELECT, INSERT ON provenance.model_calls, provenance.model_uses TO tb_audit_writer;
GRANT SELECT ON provenance.model_calls, provenance.model_uses TO tb_console, tb_orchestrator;
GRANT DELETE ON provenance.model_uses TO tb_orchestrator;
-- P-19: the index's three functions (withheld, the trigger's withhold, sweep) run as provenance_keeper, the one
-- role here that may read the opt-out register: it reads the register and deletes the use rows the register
-- withholds; no login role is a member. The register's schema is made above (SERVICE SCHEMAS); its table by its
-- group when a service first opens it, so its group's later tables are readable too
DO $keeper$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'provenance_keeper') THEN
    CREATE ROLE provenance_keeper NOLOGIN NOINHERIT;
  END IF;
  IF to_regclass('optout.optout_events') IS NOT NULL THEN
    GRANT SELECT ON optout.optout_events TO provenance_keeper;
  END IF;
END
$keeper$;
GRANT USAGE ON SCHEMA optout TO provenance_keeper;
ALTER DEFAULT PRIVILEGES FOR ROLE tbs_optout IN SCHEMA optout GRANT SELECT ON TABLES TO provenance_keeper;
GRANT USAGE ON SCHEMA provenance TO provenance_keeper;
GRANT SELECT, INSERT, DELETE ON provenance.model_uses TO provenance_keeper;
ALTER FUNCTION provenance.withheld(text, timestamptz) OWNER TO provenance_keeper;
ALTER FUNCTION provenance.withhold() OWNER TO provenance_keeper;
ALTER FUNCTION provenance.sweep() OWNER TO provenance_keeper;
-- review P19-X6: withheld() answers for any pseudonym, so only the administrator's check asks it (the trigger and the
-- sweep run as its owner); the register's group sweeps in its own opt-out transaction (review P19-X2). The REVOKE
-- takes back the earlier script's grants on a box that ran it
REVOKE EXECUTE ON FUNCTION provenance.withheld(text, timestamptz) FROM tb_audit_writer, tb_orchestrator, tb_console;
GRANT EXECUTE ON FUNCTION provenance.withheld(text, timestamptz) TO trialbox;
GRANT USAGE ON SCHEMA provenance TO tbs_optout;
GRANT EXECUTE ON FUNCTION provenance.sweep() TO tb_audit_writer, tb_orchestrator, tbs_optout, trialbox;
ALTER ROLE tb_audit_writer PASSWORD :'pw_audit_writer';
SQL
# D-541: inside `hapi`, what HAPI made while it signed in as the superuser becomes the FHIR store's own (tables with
# their indexes, sequences, views, the schema `public`, large objects). Idempotent; a new box has nothing to move.
has_hapi="$(psql -tA -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${TB_WF_DB:-trialbox_wf}" \
  -c "SELECT count(*) FROM pg_database WHERE datname = 'hapi'")"  # a failed question stops the script (set -e)
if [ "$has_hapi" = 1 ]; then
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
END
$own$;
-- large objects, in committed batches: each ALTER takes a lock held to the end of its transaction, and a store with
-- many of them would run out of lock table in one (and fail the same way at every rerun)
DO $lo$
DECLARE
  obj record;
  n int := 0;
BEGIN
  FOR obj IN SELECT oid FROM pg_largeobject_metadata WHERE lomowner <> 'tb_fhir_store'::regrole LOOP
    EXECUTE format('ALTER LARGE OBJECT %s OWNER TO tb_fhir_store', obj.oid);
    n := n + 1;
    IF n % 1000 = 0 THEN
      COMMIT;
    END IF;
  END LOOP;
END
$lo$;
SQL
fi
