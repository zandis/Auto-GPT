"""TrialBox's OMOP CDM v5.4 core (D-144, D-151): the store of record for clinical facts in the trial database.

* :mod:`omop.schema` the ``omop`` schema: the pinned official DDL and TrialBox's ``tb_*`` extension tables;
* :mod:`omop.vocab` standard, shared and local concepts (local ids >= 2,000,000,000);
* :mod:`omop.load` the normalized feed (FHIR NDJSON) into OMOP: idempotent, tombstones, status, provenance;
* :mod:`omop.export` the lake tables exported from OMOP (``TB_LAKE_SOURCE=omop``);
* :mod:`omop.dqd` OHDSI Data Quality Dashboard-style checks on the loaded data.
"""
