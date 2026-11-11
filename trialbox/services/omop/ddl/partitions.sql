-- TrialBox, not OHDSI (T-106, D-339): migration 4 of the omop schema turns each large CDM table into a table
-- partitioned by the year of its required date. omop.schema fills the template once per table of
-- omop.partitions.PARTITIONED, then adds the table's official indexes from the pinned indices file.
-- Placeholders: {table}, {id} (the table's id column), {date} (its required date column).
-- The official primary key (id) becomes (id, date): PostgreSQL asks that a partitioned table's key holds the
-- partition column. The ids still come from one sequence, and the Data Quality checks still test that the id alone
-- is unique (isPrimaryKey, omop.dqd).
-- Rows already in the table move to the default partition. The loader creates each year's partition before it
-- writes rows of that year and moves any rows of that year out of the default partition first
-- (omop.partitions.ensure_years).
-- No semicolon may appear in a comment here: the migration runner splits on it.
ALTER TABLE {table} RENAME TO tb_unpart_{table};
CREATE TABLE {table} (LIKE tb_unpart_{table} INCLUDING DEFAULTS) PARTITION BY RANGE ({date});
CREATE TABLE {table}_ydefault PARTITION OF {table} DEFAULT;
INSERT INTO {table} SELECT * FROM tb_unpart_{table};
DROP TABLE tb_unpart_{table};
ALTER TABLE {table} ADD CONSTRAINT xpk_{table} PRIMARY KEY ({id}, {date})
