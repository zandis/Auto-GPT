# The exit abort after H-52: the IO pool and a Python buffer (card H-62, 2026-11-19)

**Reader:** the people who build TrialBox

Lane H. Finding H62-01 ([findings JSON](exit-abort-third-sighting-2026-11-19.json)). It follows
[card H-52](parquet-exit-abort-2026-11-19.md).

## What was reported

Lane J reported a third sighting on its PR #1220's CI:
`test_rehearsal_read_exits_zero_every_time` in `tests/unit/test_parquet_read_exit_abort_h52.py` failed with 1 of 40 runs
dead by signal 6, after H-52's `use_threads=False` was on master.

We did not find that job's log. We searched the 38 failed or cancelled jobs and the 16 finished unit jobs of the PR's
workflow runs (public API), and none holds the test's name or `terminate called`. The cause below comes from our own
runs, not from that log.

## What still aborts

The child is the rehearsal's command (`criteria_compiler.terminology.installed.status`). It reads the table with
`pq.read_table(pa.BufferReader(data), use_threads=False)`. Here `data` is the Python `bytes` that were hashed against
the manifest.

These are shown in this container (4 CPUs, pyarrow 26.0.1, Python 3.12):

1. **What is alive at exit.** After that read, the child has 6 threads: the main thread, jemalloc's background
   thread, three OpenBLAS threads (numpy, imported by pyarrow), and one `arrow::internal::ThreadPool` worker (gdb
   `thread apply all bt`). That worker is new. It appears only after the read, and the read added it even with
   `use_threads=False`. `pq.read_table` always goes through the dataset scanner, which uses Arrow's IO pool.
   `pq.ParquetFile(...).read(use_threads=False)` on the same bytes adds no thread.
2. **How a worker kills the process (the H-52 form, caught live).** We installed a `std::set_terminate` handler with
   `LD_PRELOAD` that prints the backtrace of the thread that calls `terminate`. A threaded read under load died with
   status 134 and `terminate called without an active exception`. The backtrace is from a pool worker, not the main
   thread:
   `ThreadPool worker -> parquet column reader released -> BufferReader::~BufferReader -> arrow::py::PyBuffer::~PyBuffer
   -> PyGILState_Ensure -> PyEval_RestoreThread -> pthread_exit -> _Unwind_ForcedUnwind -> std::terminate`.
   The worker dropped the last reference to the buffer that wraps the Python `bytes`. To release it, the worker takes
   the GIL. The interpreter was already finalizing, so Python ends that thread with `pthread_exit`. The forced
   unwind then meets a `noexcept` C++ destructor, and the C++ runtime calls `std::terminate`.
3. **The same release on master's single-threaded read.** We set a gdb breakpoint on `arrow::py::PyBuffer::~PyBuffer`
   and ran master's read (`use_threads=False`) 6 times. In 1 of the 6 runs the destructor ran on the IO pool's worker
   (a future's callback that destroyed `parquet::SerializedFile`), not on the main thread.

4. **Master's single-threaded read, caught live.** In the loop below, one master child died with status 134 (signal
   6). Its backtrace is from the IO pool's worker:
   `ThreadPool worker -> Future callback -> FileReaderImpl::~FileReaderImpl -> SerializedFile::~SerializedFile ->
   BufferReader::~BufferReader -> PyBuffer::~PyBuffer -> PyGILState_Ensure -> pthread_exit -> _Unwind_ForcedUnwind ->
   std::terminate`.

So the abort that remains after H-52 is item 2's mechanism, through the one worker of item 3. This is shown, once.
It is much rarer than H-52's form, because only one thread can do it, and only in a short window. That the CI
sighting was this same path is likely, but we did not see its log.

Not the cause, as far as this card looked:
- **Arrow's pool shutdown at exit.** Both global pools (CPU and IO) are destroyed by exit handlers. Their
  `Shutdown(false)` waits for each worker and joins it (Arrow 26.0.1 `thread_pool.cc`). A C exit handler that held
  the process for 200 ms after the pools' destructors gave 0 aborts in 60 runs (20 each for the threaded, single-threaded and `ParquetFile` reads).
- **OpenBLAS and jemalloc** are C. They are alive at exit, but they cannot raise a C++ `terminate`.
- **Non-daemon Python threads.** There are none, and `threading.enumerate()` shows only the main thread.
- **duckdb, grpc, onnxruntime and faiss** are not loaded by the child.

## The fix

A read whose source is a Python object (`pa.BufferReader(bytes)` or `io.BytesIO`) now uses
`pq.ParquetFile(src).read(use_threads=False)`. That path starts no thread, so only the main thread ever holds the
buffer. It is released there, under the GIL, before finalization. These are the four such sites:

| Site | Before | Reached from |
|---|---|---|
| `services/criteria_compiler/terminology/installed.py:99` | `pq.read_table(pa.BufferReader(data), use_threads=False)` | doctor, rehearsal, `deploy/terminology.sh`, services |
| `tools/data_scan.py:510` | `pq.read_table(io.BytesIO(data), use_threads=False)` | `make data-scan` |
| `tools/public_accuracy/sets.py:1057, 1131` | `pq.read_table(io.BytesIO(...), use_threads=False)` | tools |

The bytes hashed are still the bytes parsed (TERM-2). The 11 `read_table` sites that read a path are unchanged. Their
source is a native Arrow file, so a worker that releases it never takes the GIL.

On all 10 Parquet files tracked in the repository, `ParquetFile(...).read` and `read_table` gave equal tables, with
equal schemas (metadata included) and equal `to_pylist()`.

We considered and dropped these:
- `pa.set_io_thread_count(1)`: the one worker is the problem.
- `os._exit` after the read: it is not allowed, and it skips flushes.
- Copying the bytes into an Arrow-owned buffer: the IO pool would still run, and it would cost a copy.

## Before and after

The rehearsal's exact command was run as a child, with `PYTHONUNBUFFERED` unset and the terminate tracer preloaded.
Each tree was a separate git worktree: origin/master f6c42230, and the fix. The two trees ran at the same time
beside a 4-process CPU burner, so both had the same load.
- Batch 1: 6 loops of 200 per tree, 3 children at a time per loop.
- Batch 2: 15 loops of 200 per tree, 2 children at a time per loop.

| Tree | Batch 1 | Batch 2 | Total | Exit status, stack |
|---|---|---|---|---|
| origin/master (`read_table`, `use_threads=False`) | 1 / 1,200 | 0 / 3,000 | 1 / 4,200 | -6 (SIGABRT); item 4 |
| this card (`ParquetFile(...).read`) | 0 / 1,200 | 0 / 3,000 | 0 / 4,200 | |

The counts alone do not prove the fix. One death in 4,200 against none in 4,200 is within chance. The proof is how the
abort works:
- The dying thread is always a pool worker that releases the Python buffer (items 2 and 4).
- With the fix, the read starts no thread at all (item 1, and the new test below).

The same harness, with the read forced back to threaded (H-52's form), died 4 of 600 here. H-52's container saw 40
of 600, so this container shows the abort less often. A low count for master here does not mean master is safe in
CI.

## The tests

- `tests/unit/test_parquet_single_thread_guard_h52.py` (the `guard` step) now counts
  `pq.ParquetFile(...).read(...)` as a guarded site, next to `read_table`, and still needs `use_threads=False` and at
  least 15 sites. New: `pq.read_table` on an in-memory source fails. That means a `BufferReader`, `BytesIO`,
  `py_buffer`, `memoryview`, `bytes`, `bytearray` or `BufferOutputStream` call, or a bytes literal. A `ParquetFile`
  that is not read at once with `.read(...)` also fails. On master's `installed.py` the new test fails. A source held
  in a variable is not typed statically, so this rule sees only the forms written at the call.
- `test_rehearsal_read_starts_no_thread` in `tests/unit/test_parquet_read_exit_abort_h52.py` (not slow, under 1 s) runs
  the rehearsal's read in a child and counts `/proc/self/task` before and after the read. It is deterministic. On
  master it fails with "the read started 1 thread(s)", and with the fix it passes.

## What is not verified

- The CI log of the third sighting (not found), so we did not see its stderr or exit status.
- The rate of the remaining abort. We caught it once in 4,200 runs, which is too few to give a rate.
- Whether pyarrow or CPython upstream track this. We cite no upstream issue.
