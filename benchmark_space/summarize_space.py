"""Final-state summary of the storage experiment (median over uniform seeds)."""
import csv
import sys
from collections import defaultdict
from statistics import median

rows = defaultdict(list)
final = max(int(r["inserted"]) for r in csv.DictReader(open(sys.argv[1])))
for r in csv.DictReader(open(sys.argv[1])):
    if int(r["inserted"]) == final:
        rows[r["pattern"], r["scheme"]].append(r)
fields = ("compact_mean", "compact_max", "key_mean", "key_max", "depth_max",
          "rewrites_cumulative", "index_bytes", "rebuilt_bytes")
w = csv.writer(sys.stdout, lineterminator="\n")
w.writerow(("pattern", "scheme", "runs", *fields, "index_vs_dewey", "rewrites_per_insert"))
dewey_index = {p: (median(float(r["index_bytes"]) for r in v) if v[0]["index_bytes"] else float("nan"))
               for (p, s), v in rows.items() if s == "dewey"}
for (pattern, scheme), group in rows.items():
    values = [median(float(r[f]) for r in group) if group[0][f] != "" else float("nan")
              for f in fields]
    w.writerow((pattern, scheme, len(group), *[round(v, 3) for v in values],
                round(values[6] / dewey_index[pattern], 3), round(values[5] / final, 1)))
