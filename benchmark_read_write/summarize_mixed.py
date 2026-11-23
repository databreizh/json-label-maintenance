"""Aggregate verified measurements by corpus, scheme, operation and target."""
import csv
import sys
from collections import defaultdict
from statistics import median

groups = defaultdict(list)
with open(sys.argv[1], newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        groups[tuple(row[k] for k in ("corpus", "scheme", "operation", "target"))].append(row)
writer = csv.writer(sys.stdout)
writer.writerow(("corpus", "scheme", "operation", "target", "n", "returned",
                 "rewrites_median", "total_us_median", "key_bytes_max"))
for group, rows in sorted(groups.items()):
    writer.writerow((*group, len(rows), median(int(r["returned"]) for r in rows),
                     median(int(r["rewrites"]) for r in rows),
                     median(int(r["total_ns"]) for r in rows) / 1e3,
                     max(int(r["max_key_bytes"]) for r in rows)))
