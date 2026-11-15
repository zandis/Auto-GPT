# D-885 the JVM fetch names Maven and the JDK before it starts

- **Task:** I-7 (Maven/JDK check and docs; F1 of the installer first contact, 2026-11-15)
- **PR:** this branch (`agent/I-7e-the-jvm-fetch-names-maven-and-the-jdk`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

`tools/fetch_jvm_deps.sh`, before it calls Maven for the CQL translator jars, checks `mvn` on PATH and `mvn -v`
(which fails without a JDK) and says what to install: Maven and the JDK of `.java-version` (Ubuntu package names), or
deploy/poc.sh's builder container. A cached jar folder needs neither. RUNBOOK §1 step 2 lists the build host's needs.

## Test

`tests/unit/test_fetch_jvm_deps.py`: the two new tests failed before (exit 127, a bare JAVA_HOME line); now 11 passed.
