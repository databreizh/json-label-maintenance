"""Paired one-insertion experiment with a fixed JSON tree size and depth profile."""
import csv
import random
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark_index import run_scheme
from labeling import JsonTree, SCHEMES, load_json, preorder

LEVELS = (0, 32, 64, 96, 128, 192, 256, 384, 512)
REPEATS = 15


def main(flask_path, nyc_path):
    sources = {}
    for name, path in (("Flask", flask_path), ("NYC 311", nyc_path)):
        with open(path, encoding="utf-8-sig") as file:
            sources[name] = load_json(file)
    methods = {s.name: s for s in SCHEMES if s.name in ("dewey", "dde")}
    rng = random.Random(2026)
    conditions = [(name, level) for name in sources for level in LEVELS]
    writer = None
    with TemporaryDirectory() as directory:
        db = Path(directory) / "index.sqlite"
        for repeat in range(REPEATS):
            rng.shuffle(conditions)
            for name, level in conditions:
                # Same scalar values at the same depth, split between two sibling arrays.
                document = {"background": sources[name],
                            "control": [{"payload": list(range(level, 512))}],
                            "target": [{"payload": list(range(level))}, {"payload": []}]}
                order = list(methods)
                rng.shuffle(order)
                for method in order:
                    row, = run_scheme(document, ("target",), "head", 1,
                                      methods[method], db, True)
                    assert row["updated_existing"] == (level + 4 if method == "dewey" else 0)
                    assert row["inserted"] == 2 and row["deleted"] == 0
                    entry = {"corpus": name, "payload_nodes": level, "repeat": repeat, **row}
                    if writer is None:
                        writer = csv.DictWriter(sys.stdout, fieldnames=entry, lineterminator="\n")
                        writer.writeheader()
                    writer.writerow(entry)
                    db.unlink()


if __name__ == "__main__":
    main(*sys.argv[1:])
