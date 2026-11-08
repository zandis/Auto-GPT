"""rc-bridge read connector (TB-DS-08 ICD-04, build step 3): reads version, project info, the data dictionary, DAGs
and flat records from REDCap by HTTPS POST to ``/api/`` (IR-03a), and joins records to TrialBox through the per-study
project link (§4.1a). Read-only: nothing is ever written to REDCap (BD-05)."""
