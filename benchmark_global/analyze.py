"""Validate paired measurements and plot paired median differences with IQRs."""
import csv
import sys
from collections import defaultdict
from itertools import product
from statistics import median, quantiles

from run import LEVELS, REPEATS

groups = defaultdict(list)
pairs = defaultdict(dict)
with open("measurements.csv", newline="", encoding="utf-8") as file:
    for row in csv.DictReader(file):
        corpus, level, repeat = row["corpus"], int(row["payload_nodes"]), int(row["repeat"])
        pair = pairs[corpus, level, repeat]
        scheme = row["scheme"]
        assert scheme not in pair
        values = {key: int(row[key]) for key in
                  ("nodes_before", "updated_existing", "total_ns", "edit_ns", "label_ns", "index_ns")}
        assert values["nodes_before"] == {"Flask": 3568, "NYC 311": 7021}[corpus]
        assert values["updated_existing"] == (level + 4 if scheme == "dewey" else 0)
        assert values["total_ns"] == sum(values[key] for key in ("edit_ns", "label_ns", "index_ns"))
        pair[scheme] = values

assert set(pairs) == set(product(("Flask", "NYC 311"), LEVELS, range(REPEATS)))
for (corpus, level, _), pair in pairs.items():
    assert set(pair) == {"dewey", "dde"}
    groups[corpus, level].append([
        (pair["dewey"][key] - pair["dde"][key]) / 1e6
        for key in ("total_ns", "label_ns", "index_ns")
    ])

writer = csv.writer(sys.stdout, lineterminator="\n")
writer.writerow(("corpus", "dewey_rewrites", "pairs", "total_delta_ms",
                 "total_q1_ms", "total_q3_ms", "label_delta_ms", "index_delta_ms", "dde_faster_pairs"))
results = defaultdict(list)
for (corpus, level), data in sorted(groups.items()):
    total, label, index = map(list, zip(*data))
    q1, _, q3 = quantiles(total, n=4, method="inclusive")
    center = median(total)
    results[corpus].append((level + 4, center, q1, q3, median(label), median(index)))
    writer.writerow((corpus, level + 4, len(data), *(round(value, 4) for value in
                     (center, q1, q3, median(label), median(index))),
                     sum(value > 0 for value in total)))

if "--plot" in sys.argv:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8), sharey=True, layout="constrained")
    for ax, (corpus, data) in zip(axes, results.items()):
        x, total, q1, q3, label, index = zip(*data)
        ax.fill_between(x, q1, q3, color="#245ea9", alpha=.15, label="Total IQR")
        ax.plot(x, total, "o-", color="#245ea9", label="Total")
        ax.plot(x, label, "--", color="#ad541d", label="Label computation")
        ax.plot(x, index, ":", color="#247a66", label="SQLite phase")
        ax.axhline(0, color="#606775", linewidth=.8)
        ax.set_title(corpus)
        ax.set_xlabel("Existing entries rewritten by Dewey")
        ax.grid(axis="y", alpha=.2)
    axes[0].set_ylabel("Paired latency difference (Dewey − DDE), ms")
    axes[1].legend(frameon=False, fontsize=8)
    fig.savefig("dewey_dde_crossover.png", dpi=200)
