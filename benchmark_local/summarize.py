"""Summarize paired incremental insertions for all positions."""
import csv
import sys
from collections import defaultdict
from itertools import product
from statistics import median, quantiles

from run import LEVELS, REPEATS

corpora = ("Flask", "NYC 311")
positions = ("head", "middle", "tail")
methods = ("dewey", "dde", "ordpath")
pairs = defaultdict(dict)
with open(sys.argv[1], newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        corpus, position, scheme = (row[key] for key in ("corpus", "position", "scheme"))
        level, repeat = int(row["payload_nodes"]), int(row["repeat"])
        expected = {"head": level + 4, "middle": level - level // 2 + 2, "tail": 0}
        assert int(row["rewritten"]) == (expected[position] if scheme == "dewey" else 0)
        assert int(row["inserted"]) == 2
        total = int(row["total_ns"])
        assert total == sum(int(row[f"{phase}_ns"]) for phase in ("edit", "label", "index"))
        pair = pairs[corpus, position, level, repeat]
        assert scheme not in pair
        pair[scheme] = total / 1e6
assert set(pairs) == set(product(corpora, positions, LEVELS, range(REPEATS)))
assert all(set(pair) == set(methods) for pair in pairs.values())
writer = csv.writer(sys.stdout, lineterminator="\n")
writer.writerow(("corpus", "position", "payload_nodes", "pairs", *[f"{s}_ms" for s in methods],
                 "dewey_minus_dde_ms", "q1_ms", "q3_ms", "dewey_minus_ordpath_ms",
                 "ordpath_minus_dde_ms"))
for corpus, position, level in product(corpora, positions, LEVELS):
    block = [pairs[corpus, position, level, repeat] for repeat in range(REPEATS)]
    dd = [r["dewey"] - r["dde"] for r in block]
    q1, _, q3 = quantiles(dd, n=4, method="inclusive")
    writer.writerow((corpus, position, level, REPEATS, *(round(x, 5) for x in
                    [*(median(r[s] for r in block) for s in methods), median(dd), q1, q3,
                     median(r["dewey"] - r["ordpath"] for r in block),
                     median(r["ordpath"] - r["dde"] for r in block)])))
