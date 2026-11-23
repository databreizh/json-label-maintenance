"""Validate the factorial experiment and plot paired Dewey-minus-DDE gaps."""
import csv
import sys
from collections import defaultdict
from itertools import product
from pathlib import Path
from statistics import median, quantiles

from scale import MODES, PAYLOADS, REPEATS, SIZES

PHASES = ("delta_ns", "sqlite_ns", "total_ns")


def summarize(path):
    pairs = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            size, payload, repeat = (int(row[k]) for k in ("size", "payload", "repeat"))
            pair = pairs[size, payload, row["mode"], repeat]
            scheme = row["scheme"]
            assert scheme in {"dewey", "dde"} and scheme not in pair
            times = tuple(int(row[k]) for k in PHASES)
            assert times[0] + times[1] == times[2]
            assert int(row["rewrites"]) == (payload + 4 if scheme == "dewey" else 0)
            pair[scheme] = times
    assert set(pairs) == set(product(SIZES, PAYLOADS, MODES, range(REPEATS)))
    points = []
    for size, payload, mode in product(SIZES, PAYLOADS, MODES):
        matches = [pairs[size, payload, mode, repeat] for repeat in range(REPEATS)]
        assert all(set(pair) == {"dewey", "dde"} for pair in matches)
        delta = [[(a - b) / 1e6 for a, b in zip(pair["dewey"], pair["dde"])]
                 for pair in matches]
        label, sqlite, total = zip(*delta)
        q1, _, q3 = quantiles(total, n=4, method="inclusive")
        points.append(dict(size=size, rewrites=payload + 4, mode=mode, pairs=REPEATS,
                           delta_ms=median(label), sqlite_ms=median(sqlite),
                           total_ms=median(total), total_q1_ms=q1, total_q3_ms=q3,
                           dewey_total_ms=median(p["dewey"][2] for p in matches) / 1e6,
                           dde_total_ms=median(p["dde"][2] for p in matches) / 1e6))
    return points


def plot(points, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(7.5, 4.8), sharex=True, layout="constrained")
    for col, mode in enumerate(MODES):
        for row, (metric, title) in enumerate((("total_ms", "Total"), ("sqlite_ms", "SQLite phase"))):
            ax = axes[row, col]
            for size, marker in zip(SIZES, ("o", "s", "^")):
                subset = [p for p in points if p["size"] == size and p["mode"] == mode]
                ax.plot([p["rewrites"] for p in subset], [p[metric] for p in subset],
                        marker=marker, ms=4, label=f"{size:,} nodes")
            ax.axhline(0, color="#555", lw=.8)
            ax.grid(axis="y", alpha=.25)
            ax.tick_params(labelsize=10)
            ax.set_title(f"{mode.title()} maintenance · {title}", fontsize=12)
            if row:
                ax.set_xlabel("Existing entries rewritten by Dewey", fontsize=11)
            if not col:
                ax.set_ylabel("Dewey − DDE (ms)", fontsize=11)
    for row in axes:
        lo, hi = zip(*(ax.get_ylim() for ax in row))
        for ax in row:
            ax.set_ylim(min(lo), max(hi))
    axes[0, 1].legend(frameon=False, fontsize=10)
    fig.savefig(output)


if __name__ == "__main__":
    points = summarize(sys.argv[1])
    writer = csv.DictWriter(sys.stdout, fieldnames=points[0], lineterminator="\n")
    writer.writeheader()
    writer.writerows(points)
    if len(sys.argv) == 3:
        plot(points, Path(sys.argv[2]))
