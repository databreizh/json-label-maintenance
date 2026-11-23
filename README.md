# Artifact for "Scheme or Implementation? Attributing the Maintenance Cost of JSON Structural Labels" (DASFAA 2027 submission)

This archive contains the code, raw measurements, and summaries behind every number in the paper. All scripts use the Python standard library only; Matplotlib is optional and only regenerates the figure of Section 6.

## Hosts

Every campaign was run on two hosts:

- **Host B**: Linux kernel 6.18, Intel Xeon at 2.10 GHz (2 logical cores), 8 GiB of memory, ext4, Python 3.13.18, SQLite 3.53.1. Results are in the `benchmark_*` folders (`benchmark_global/hostB` for Section 5.1).
- **Host W**: Windows 11, Intel Core Ultra 7 165U (14 logical cores), 32 GiB of memory, 512 GB NVMe SSD, Python 3.14.0, SQLite 3.50.4. Results are in `hostW_replay/`.

Label sizes, index sizes, rewrite counts, and query results are identical on both hosts. Only timings differ.

Measurements from an earlier, undocumented Linux environment are kept in `legacy_hostA/` for reference. The paper no longer cites them.

## Repository layout

Each `benchmark_*` folder is self-contained: it holds its scripts, the shared modules it imports, and the host-B results. The modules `labeling.py` (Dewey, DDE, ORDPATH, and the exploratory schemes), `additional_schemes.py`, `benchmark_index.py`, and `run.py` (corpus loading and SQLite helpers) appear in several folders as identical copies.

```
replay_all.bat          replays every campaign on Windows into replay\

benchmark_global/       Section 5.1, paired Dewey-DDE crossover, generic whole-tree constructor
  run.py                  campaign driver (two exports as arguments)
  analyze.py              paired summary, run from the results folder
  hostB/                  measurements.csv, summary.csv
benchmark_local/        Section 5.2, local maintenance by insertion position
  local.py, summarize.py  campaign and summary; measurements.csv, summary.csv
benchmark_scale/        Section 6, factorial design (tree size x rewrite volume)
  scale.py, analyze_scale.py; measurements.csv, summary.csv, environment.txt
  scale_tradeoff.pdf      Figure 1 of the paper (host B)
benchmark_objects_v10/  Section 7, object-key insertions and constructor ablation
  objects.py              generic, specialized, and reuse constructors, local mode
  analyze_objects.py      paired medians and order-statistic intervals
  measurements.csv, summary.csv, phases.csv, environment.txt
benchmark_space/        Sections 8 and 9
  space.py, summarize_space.py   label and index sizes under five insertion patterns
  btree_size.py                  portable index B-tree size (equals SQLite dbstat)
  positional.py                  k-th element access
  ordkeys.py                     order-preserving keys (ORDPATH codes, rationals via continued fractions)
  sibling_index_size.py          size of the auxiliary sibling-order index
  sizes.csv, summary.csv, positional.csv
benchmark_read_write/   Section 9, mixed edits with exact and descendant reads
  mixed.py, summarize_mixed.py; measurements.csv, summary.csv

hostW_replay/           host-W results of every campaign (file names prefixed by campaign)
legacy_hostA/           superseded results from an undocumented environment, not cited in the paper
data/                   the two input exports used by Sections 5.1, 5.2, and the reads of Section 9
```

All other campaigns generate their inputs.

## Input data

| File | Content | Source | SHA-256 |
|---|---|---|---|
| `data/github_issues.json` | 32 issues of the `pallets/flask` repository (pull requests filtered out), created between July and November 2026; 3,047 source nodes | GitHub REST API, issues endpoint | `87ca6b6be34061d7f40eecfdb504305511106b0e507455066144fd5fde6b5b85` |
| `data/nyc311_200.json` | 200 NYC 311 service requests, created between 2020 and 2025; 6,500 source nodes | NYC Open Data, 311 Service Requests | `b536cec331eb7ef75cf442f8ace28e031cf5cb14f58817f8f20e81cb54956f36` |

The files are redistributed unchanged for reproducibility only; their content remains subject to the terms of the original sources. Re-downloading them today would give different records, and the analysis scripts check the node counts of these exact files.

## Replaying everything on Windows

Use the Command Prompt (cmd.exe), not PowerShell, because Windows PowerShell 5.1 writes `>` redirections in UTF-16. From this folder, with Python 3.10 or later:

    replay_all.bat

The script replays every campaign, using the exports in `data\`. Results go to `replay\`; the provided CSV files are not overwritten.

## Replaying on Linux or macOS

Run all commands from the archive root. The paths below write to the provided result files; redirect elsewhere to keep them.

**Section 5.1, paired crossover (generic constructor):**

    mkdir -p out/global
    python benchmark_global/run.py data/github_issues.json data/nyc311_200.json > out/global/measurements.csv
    (cd out/global && python ../../benchmark_global/analyze.py > summary.csv)

**Section 5.2, local maintenance by insertion position:**

    python benchmark_local/local.py data/github_issues.json data/nyc311_200.json > benchmark_local/measurements.csv
    python benchmark_local/summarize.py benchmark_local/measurements.csv > benchmark_local/summary.csv

The campaign uses 15 repetitions, nine payload levels, and the three possible positions in an initial array of two objects: 810 matched triplets, or 2,430 insertions per host. Labels and index are fully verified after each insertion, outside the timed interval.

**Section 6, factorial experiment (tree size × rewrite volume):**

    PYTHONPATH=benchmark_read_write python benchmark_scale/scale.py --environment benchmark_scale/environment.txt > benchmark_scale/measurements.csv
    PYTHONPATH=benchmark_read_write python benchmark_scale/analyze_scale.py benchmark_scale/measurements.csv benchmark_scale/scale_tradeoff.pdf > benchmark_scale/summary.csv

The fixture is generated by the script: 432 verified insertions per host, nine repetitions per combination.

**Section 7, object-key insertions and constructor ablation:**

    PYTHONPATH=benchmark_read_write:benchmark_objects_v10 python benchmark_objects_v10/objects.py --environment benchmark_objects_v10/environment.txt > benchmark_objects_v10/measurements.csv
    PYTHONPATH=benchmark_read_write:benchmark_objects_v10 python benchmark_objects_v10/analyze_objects.py benchmark_objects_v10/measurements.csv --phases benchmark_objects_v10/phases.csv > benchmark_objects_v10/summary.csv

Modes: `global` (generic constructor), `global-spec` (specialized constructors), `global-reuse` (Dewey reusing unchanged labels), and `local`. The campaign covers Dewey, DDE, and ORDPATH at 4,096 and 100,000 nodes, with 2, 66, and 514 Dewey rewrites and 15 repetitions: 900 verified insertions per host. `summary.csv` gives the paired differences, with the median and an interval from the 4th and 12th order statistics (coverage 96.48%). `phases.csv` gives the medians per phase.

**Section 8, space cost:**

    PYTHONPATH=benchmark_read_write:benchmark_space python benchmark_space/space.py > benchmark_space/sizes.csv
    python benchmark_space/summarize_space.py benchmark_space/sizes.csv > benchmark_space/summary.csv

The experiment starts from 500 objects and applies 2,000 local insertions under five patterns: uniform (five seeds), head, tail, hot spot, and zigzag. It records:
- compact label size (zigzag variable-length integer per component);
- prefix-key size;
- index B-tree size after incremental maintenance and after a rebuild;
- cumulative rewrites.

Index sizes come from `benchmark_space/btree_size.py`, which copies the database, drops the index, and counts the freed pages. This matches SQLite's `dbstat` exactly and also works where `dbstat` is unavailable. Every checkpoint is fully verified.

**Section 9, mixed edits and reads:**

    python benchmark_read_write/mixed.py data/github_issues.json data/nyc311_200.json > benchmark_read_write/measurements.csv
    python benchmark_read_write/summarize_mixed.py benchmark_read_write/measurements.csv > benchmark_read_write/summary.csv

The campaign covers 504 edits and 336 query measurements per host, each query averaged over 50 executions. Queries retrieve identifiers using pre-encoded keys. The script validates results by tree traversal and access paths with `EXPLAIN QUERY PLAN`.

**Section 9, positional access (k-th element) and the size of the sibling index:**

    PYTHONPATH=benchmark_read_write:benchmark_space python benchmark_space/positional.py > benchmark_space/positional.csv
    python benchmark_space/sibling_index_size.py

Access methods:
- **Dewey**: an equality probe on the key `parent/(k+1)/`.
- **ORDPATH and DDE**: an index on (parent, order-preserving sibling key), queried with `ORDER BY ... LIMIT 1 OFFSET k`.
- **`dde-sort`**: a naive baseline that sorts exact fractions in the client.

The DDE sibling key uses continued fractions. It is implemented in `benchmark_space/ordkeys.py`, whose self-test runs with `python benchmark_space/ordkeys.py`.

## Timing boundaries by campaign

| Campaign (section) | Script | Interval 1 | Interval 2 | Interval 3 | Key encoding |
|---|---|---|---|---|---|
| Global crossover (5.1) | benchmark_global/benchmark_index.py | in-memory edit | label computation (generic constructor) | SQLite phase: delta detection (snapshot comparison), serialization, SQL, commit | prototype serialization |
| Local by position (5.2) | benchmark_local/local.py | in-memory edit | local delta computation | SQLite: serialization, SQL, commit | prototype serialization |
| Factorial N × R (6) | benchmark_scale/scale.py | T_delta: edit + labels + (global) snapshot comparison | T_SQL: serialization, SQL, commit | — | prefix |
| Objects and ablation (7) | benchmark_objects_v10/objects.py | edit | label construction (or local delta) | snapshot comparison | SQLite (separate columns); prefix |
| Mixed sequence (9) | benchmark_read_write/mixed.py | local delta + SQLite (single interval) | reads: mean of 50 executions | — | prefix |
| Positional access (9) | benchmark_space/positional.py | query only, mean of 50 warm executions | — | — | prefix + sibling index |
| Space (8) | benchmark_space/space.py | not timed | — | — | compact varint + prefix |

Initialization and verification are always outside the timed intervals.
