# A one-shot Parquet read that aborts at exit (card H-52, 2026-11-19)

Lane H. Finding H52-01 ([findings JSON](parquet-exit-abort-2026-11-19.json)).

## What CI saw

The box rehearsal (`tools/rehearse_box/box.sh`, the terminology check) failed now and then with
`terminate called without an active exception`, then
`REHEARSAL FAIL: <service> does not read the table loaded at install`, in runs 44440588251, 44454437549 and
44478886311. The check runs a short `python -c` in three containers. It calls
`criteria_compiler.terminology.installed.status(...)`, which reads a Parquet table with pyarrow's threaded reader
(`pq.read_table(...)`, `use_threads` on by default; pyarrow 26.0.1, Python 3.12). The read succeeds and prints its row
count. The process then aborts at interpreter exit with status 134 (SIGABRT).

On a real box the same module is read by `trialbox doctor`'s terminology check. `deploy/check_host.sh` runs the doctor
as a one-shot container and judges it by exit status. So every line can say PASS, and the check still says FAIL.

## Reproduction (lane H, this container, 4 CPUs)

Steps: a synthetic 2-row site list loaded with `install_site_list`, then the rehearsal's exact command run as a
subprocess. There were 3 loops of 200 in parallel, beside a 4-process CPU burner. The scripts are outside the repo.

| Variant | Failures | Exit status, stderr |
|---|---|---|
| master (`read_table`, threaded) | 40 / 600 (6.7 %) | 134; `site_rehearsal 2 rows` then `terminate called without an active exception` |
| master + `pa.set_cpu_count(1)` before the read | 25 / 600 | the same |
| `use_threads=False` at `installed.py:99` | 0 / 600 | |
| one-shot writes (`installed._write` through `install_site_list`, and `lake.store._write_parquet`), fixed tree | 0 / 600 | |

The earlier diagnosis on another machine found: 0/300 when idle, and 11/600 under load. Thread-count environment
variables did not help, and a plain `import pyarrow.parquet` never failed.

## The fix

Every `pq.read_table` in `libs/`, `services/` and `tools/` now passes `use_threads=False`. The change adds that keyword
and nothing else. One line was re-wrapped by the formatter.

We tried two central guards and dropped both:
- `pa.set_cpu_count(1)` at the entry of each process did not stop the abort (25/600 above).
- A helper in `libs/tb_common` would still need an edit at each site, and it would add a module.

The keyword is the smallest change that the loop shows at 0 failures. There is no `os._exit` workaround.

Read cost, measured median over repeated reads on an idle machine:
- `icd10cm_full.parquet` (98,186 rows, 1.0 MB), the largest shipped terminology table: `read_table` took 22.3 ms
  threaded and 20.9 ms single-threaded. The whole call including `to_pylist` took 107 ms and 95 ms.
- A synthetic 1,000,000-row, 4-column table with 10 row groups (a size above any lake table read by the tools here):
  106.9 ms threaded and 117.7 ms single-threaded.

The lake service's own reads go through DuckDB (`read_parquet`), not pyarrow, so this card does not touch them.

## Every site and its verdict

"One-shot" means reached from a process that ends normally: a CLI, `docker run`/`exec`, install, the doctor, the
nightly's steps, or `tools/*`.

| Site | Reached from | Verdict |
|---|---|---|
| `services/criteria_compiler/terminology/installed.py:99` (`read_table`) | doctor, rehearsal `docker exec`, `deploy/terminology.sh`, criteria-compiler service | fixed |
| `services/criteria_compiler/terminology/mapper.py:311, 317, 349, 360` (`Terminology`) | `tools/*` (bench, scenarios, e2e, public_accuracy, terminology_coverage, ...), orchestrator and criteria-compiler services | fixed |
| `services/adapter/sources/ssmix2/source.py:248` | `adapter.cli` (one-shot) and the adapter service | fixed |
| `services/adapter/validate/jpcore.py:119` | `adapter.cli` and the adapter service | fixed |
| `services/omop/vocab_load.py:374` | `python -m omop` (one-shot) | fixed |
| `tools/data_scan.py:510` | `make data-scan` | fixed |
| `tools/goldens.py:251` | tools, nightly | fixed |
| `tools/imperfect_feed.py:1282` | tools, nightly | fixed |
| `tools/omop_parity.py:373` | tools, nightly | fixed |
| `tools/public_accuracy/sets.py:1057, 1131` | tools | fixed |
| `tools/public_e2e.py:422` | tools | fixed |
| `services/criteria_compiler/terminology/installed.py:191` (`pq.write_table`) | `tools.terminology_install`, `deploy/terminology.sh` | write; 0/600 in the loop; left alone |
| `services/lake/store.py:784` (`ParquetWriter`) | lake service; `adapter.cli` in-process | write; 0/600 in the loop; left alone |
| `services/criteria_compiler/terminology/resolver.py:120`, `tools/build_terminology.py:39, 48, 61` (`pq.write_table`) | build tools | write; same path as above; left alone |
| `services/lake/app.py:76` (Arrow IPC stream writer) | lake service (long-running) | not Parquet; left alone |
| `services/lake/store.py:1437, 1446`, `tools/erasure_reach.py:371` (DuckDB `read_parquet`) | lake service, tool | not pyarrow; outside this card |

In pyarrow 26.0.1, neither `pq.write_table` nor `pq.ParquetWriter` takes a `use_threads` argument. The write loop never
aborted, so the write sites are unchanged.

No read site is reached only from a long-running service, so none was left threaded.

## The test

`tests/unit/test_parquet_read_exit_abort_h52.py`:

- A `guard` test parses `libs/`, `services/` and `tools/`. It fails on any `pq.read_table` (any import alias of
  `pyarrow.parquet`) without `use_threads=False`. It also requires at least the 15 sites above, so an empty scan cannot
  pass. On master's tree it finds 15 of 15 threaded.
- A `slow` test loads a synthetic table, then runs the rehearsal's exact command 40 times in 2 workers and requires
  exit 0 and the row line each time. It takes about 14 s. On a loaded machine it would likely catch a regression of
  that one site. On an idle machine it likely would not, and a pass never proves the abort absent. The static guard
  is the real protection.

## The rehearsal's log (not changed by this card)

`box.sh` is unchanged; the integrator has not yet ruled on lane H editing it. If allowed, the failing check would log
the exit status and the captured output, with no assertion changed:

```sh
    out="$(dc exec -T "$svc" python -c "$read_it" 2>&1)"; rc=$?
    [ "$rc" = 0 ] || { printf '%s\n' "$out" >&2; fail "$svc does not read the table loaded at install (exit $rc)"; }
```

## What is inference

The cause is inferred: probably pyarrow's worker threads (started by the threaded read) are still alive or being torn
down when the interpreter finalizes, and a `std::thread` destructor or exit handler calls `std::terminate`. This
matches the evidence: the read completes, the abort happens at exit, it needs load, and single-threaded reads stop it.
We did not read pyarrow's source or debug the core, and we cite no upstream issue.
