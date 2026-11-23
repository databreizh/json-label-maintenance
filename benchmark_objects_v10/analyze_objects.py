"""Validate and summarize the object-key campaign (three schemes, four maintenance modes).

Output 1 (stdout): paired Dewey-minus-X total latency per condition, with the
order-statistic confidence interval for the median (ranks 4 and 12 of 15).
Output 2 (--phases FILE): median phase times per scheme and mode.
"""
import argparse
import csv
from collections import defaultdict
from itertools import product
from math import comb
from statistics import median

from objects import MODES, PAYLOADS, REPEATS, SCHEME_NAMES, SIZES, methods_for

parser = argparse.ArgumentParser()
parser.add_argument("measurements")
parser.add_argument("--phases")
args = parser.parse_args()

rows = defaultdict(dict)
with open(args.measurements, newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        size, p, rep = int(row["size"]), int(row["payload"]), int(row["repeat"])
        scheme, mode = row["scheme"], row["mode"]
        assert int(row["rewrites"]) == (p + 2 if scheme == "dewey" else 0)
        parts = [int(row[k]) for k in ("edit_ns", "labels_ns", "compare_ns", "sqlite_ns")]
        assert abs(sum(parts) - int(row["total_ns"])) < 1000
        assert (scheme, mode) not in rows[size, p, rep]
        rows[size, p, rep][scheme, mode] = [v / 1e6 for v in (*parts, int(row["total_ns"]))]
expected = {(s, m) for s in SCHEME_NAMES for m in methods_for(s)}
assert rows.keys() == set(product(SIZES, PAYLOADS, range(REPEATS)))
assert all(block.keys() == expected for block in rows.values())

rank = max(k for k in range(1, (REPEATS + 1) // 2)
           if 1 - 2 * sum(comb(REPEATS, j) for j in range(k)) / 2**REPEATS >= .95)
coverage = 1 - 2 * sum(comb(REPEATS, j) for j in range(rank)) / 2**REPEATS

COMPARISONS = [  # (label, Dewey mode, other scheme, other mode)
    ("global", "global", "dde", "global"),
    ("global", "global", "ordpath", "global"),
    ("global-spec", "global-spec", "dde", "global-spec"),
    ("global-spec", "global-spec", "ordpath", "global-spec"),
    ("global-reuse", "global-reuse", "dde", "global-spec"),
    ("global-reuse", "global-reuse", "ordpath", "global-spec"),
    ("local", "local", "dde", "local"),
    ("local", "local", "ordpath", "local"),
]
writer = csv.writer(__import__("sys").stdout, lineterminator="\n")
writer.writerow(("size", "rewrites", "comparison", "other", "pairs", "median_ms",
                 "ci_low_ms", "ci_high_ms", "dewey_ms", "other_ms", "coverage"))
for size, p in product(SIZES, PAYLOADS):
    for label, dmode, other, omode in COMPARISONS:
        diffs = sorted(rows[size, p, r][("dewey", dmode)][4] - rows[size, p, r][(other, omode)][4]
                       for r in range(REPEATS))
        writer.writerow((size, p + 2, label, other, REPEATS,
                         *(round(v, 3) for v in (median(diffs), diffs[rank - 1], diffs[-rank],
                           median(rows[size, p, r][("dewey", dmode)][4] for r in range(REPEATS)),
                           median(rows[size, p, r][(other, omode)][4] for r in range(REPEATS)))),
                         round(coverage, 4)))

if args.phases:
    with open(args.phases, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out, lineterminator="\n")
        w.writerow(("size", "rewrites", "scheme", "mode", "edit_ms", "labels_ms",
                    "compare_ms", "sqlite_ms", "total_ms"))
        for size, p in product(SIZES, PAYLOADS):
            for scheme, mode in sorted(expected):
                values = [rows[size, p, r][scheme, mode] for r in range(REPEATS)]
                w.writerow((size, p + 2, scheme, mode,
                            *(round(median(v[i] for v in values), 3) for i in range(5))))
