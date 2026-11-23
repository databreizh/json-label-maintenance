"""Factorial test of document size, shifted suffix, and label maintenance."""
import argparse
import csv
import platform
import random
import sqlite3
import sys
from contextlib import closing
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from labeling import JsonTree, SCHEMES
from mixed import edit_delta, key

SIZES = (1024, 4096, 16384)
PAYLOADS = (0, 64, 256, 512)
REPEATS = 9
MODES = ("global", "local")


def fixture(size, payload):
    # Same depth histogram at fixed size. Transfer leaves between sibling branches.
    return {"background": [{"payload": list(range(payload, size - 9))}],
            "target": [{"payload": list(range(payload))}, {"payload": []}]}


def measure(database, size, payload, scheme, mode):
    tree = JsonTree(fixture(size, payload))
    labels = scheme.labels(tree)
    assert len(labels) == size
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE nodes(uid INTEGER PRIMARY KEY,label BLOB NOT NULL)")
        db.execute("CREATE INDEX by_label ON nodes(label)")
        with db:
            db.executemany("INSERT INTO nodes VALUES (?,?)",
                           [(uid, key(scheme, label)) for uid, label in labels.items()])
        start = perf_counter_ns()
        if mode == "global":
            tree.insert(("target",), 0, {"payload": list(range(24))})
            snapshot = scheme.labels(tree, labels)
            added = {uid: label for uid, label in snapshot.items() if uid not in labels}
            changed = {uid: label for uid, label in snapshot.items()
                       if uid in labels and labels[uid] != label}
        else:
            added, changed, removed = edit_delta(tree, scheme, labels, ("target",), 0, True)
            assert not removed
        after_delta = perf_counter_ns()
        with db:
            db.executemany("INSERT INTO nodes VALUES (?,?)",
                           [(uid, key(scheme, label)) for uid, label in sorted(added.items())])
            db.executemany("UPDATE nodes SET label=? WHERE uid=?",
                           [(key(scheme, label), uid) for uid, label in sorted(changed.items())])
        end = perf_counter_ns()
        expected = scheme.labels(tree, labels)
        assert expected == {**labels, **added, **changed}
        assert len(added) == 26
        assert len(changed) == (payload + 4 if scheme.name == "dewey" else 0)
        actual = dict(db.execute("SELECT uid,label FROM nodes INDEXED BY by_label"))
        assert actual == {uid: key(scheme, label) for uid, label in expected.items()}
        return len(changed), after_delta - start, end - after_delta, end - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path)
    args = parser.parse_args()
    if args.environment:
        args.environment.write_text(
            f"{platform.platform()}\nPython {platform.python_version()}\n"
            f"SQLite {sqlite3.sqlite_version}\n", encoding="utf-8")
    schemes = {s.name: s for s in SCHEMES if s.name in ("dewey", "dde")}
    rng = random.Random(2027)
    conditions = list(product(SIZES, PAYLOADS))
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("size", "payload", "repeat", "scheme", "mode",
                     "rewrites", "delta_ns", "sqlite_ns", "total_ns"))
    with TemporaryDirectory() as directory:
        db = Path(directory) / "scale.sqlite"
        for repeat in range(REPEATS):
            rng.shuffle(conditions)
            for size, payload in conditions:
                methods = list(product(schemes, MODES))
                rng.shuffle(methods)
                for scheme, mode in methods:
                    metrics = measure(db, size, payload, schemes[scheme], mode)
                    writer.writerow((size, payload, repeat, scheme, mode, *metrics))
                    db.unlink()


if __name__ == "__main__":
    main()
