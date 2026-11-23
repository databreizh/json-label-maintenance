"""Validate and summarize matched object-key insertions."""
import csv
import sys
from collections import defaultdict
from itertools import product
from math import comb
from statistics import median, quantiles

from objects import MODES, PAYLOADS, REPEATS, SIZES

pairs = defaultdict(dict)
with open(sys.argv[1], newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        size, p, repeat = (int(row[k]) for k in ("size", "payload", "repeat"))
        pair = pairs[size, p, row["mode"], repeat]
        scheme = row["scheme"]
        assert scheme in {"dewey", "dde"} and scheme not in pair
        assert int(row["rewrites"]) == (p + 2 if scheme == "dewey" else 0)
        times = tuple(int(row[k]) for k in ("delta_ns", "sqlite_ns", "total_ns"))
        assert times[0] + times[1] == times[2]
        pair[scheme] = times
assert pairs.keys() == set(product(SIZES, PAYLOADS, MODES, range(REPEATS)))
writer = csv.writer(sys.stdout, lineterminator="\n")
writer.writerow(("size","rewrites","mode","pairs","delta_ms","sqlite_ms",
                 "total_ms","q1_ms","q3_ms","ci_low_ms","ci_high_ms","dewey_ms","dde_ms"))
# Narrowest symmetric order-statistic interval with at least 95% coverage.
rank = max(k for k in range(1, (REPEATS + 1) // 2)
           if 1 - 2 * sum(comb(REPEATS, j) for j in range(k)) / 2**REPEATS >= .95)
for size, p, mode in product(SIZES, PAYLOADS, MODES):
    group = [pairs[size, p, mode, i] for i in range(REPEATS)]
    assert all(pair.keys() == {"dewey", "dde"} for pair in group)
    diff = [[(a-b)/1e6 for a,b in zip(pair["dewey"], pair["dde"])] for pair in group]
    lbl, sql, total = zip(*diff)
    q1, _, q3 = quantiles(total, n=4, method="inclusive")
    ordered = sorted(total)
    interval = ordered[rank - 1], ordered[-rank]
    writer.writerow((size,p+2,mode,REPEATS,*[round(v,4) for v in
                     (median(lbl),median(sql),median(total),q1,q3,*interval,
                      median(pair["dewey"][2] for pair in group)/1e6,
                      median(pair["dde"][2] for pair in group)/1e6)]))
