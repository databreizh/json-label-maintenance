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
from mixed import collect, dde_between, key

SIZES = (4096, 100000)
PAYLOADS = (0, 64, 512)
REPEATS = 15
MODES = ("global", "local")


def fixture(size, payload):
    return {"background": {"payload": list(range(payload, size - 8))},
            "target": {"a": {"payload": []},
                       "z": {"payload": list(range(payload))}}}


def measure(database, size, payload, scheme, mode, profile=None):
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
        if profile is not None and mode != "global":
            raise ValueError("Profiling requires global maintenance")
        start = perf_counter_ns()
        if mode == "global":
            tree.insert(("target",), "m", {"payload": list(range(24))})
            if profile is not None:
                after_edit = perf_counter_ns()
            snapshot = scheme.labels(tree, labels)
            if profile is not None:
                after_labels = perf_counter_ns()
            added = {uid: label for uid, label in snapshot.items() if uid not in labels}
            changed = {uid: label for uid, label in snapshot.items()
                       if uid in labels and labels[uid] != label}
        else:
            tree.insert(("target",), "m", {"payload": list(range(24))})
            parent = tree.at(("target",))
            left, inserted, right = (node for _, node in parent.children)
            added, changed = {}, {}
            prefix = labels[parent.uid]
            if scheme.name == "dde":
                collect(inserted, dde_between(prefix, labels[left.uid], labels[right.uid]), added)
            else:
                collect(inserted, (*prefix, 2), added)
                collect(right, (*prefix, 3), changed)
        after_delta = perf_counter_ns()
        with db:
            db.executemany("INSERT INTO nodes VALUES (?,?)",
                           [(uid, key(scheme, label)) for uid, label in sorted(added.items())])
            db.executemany("UPDATE nodes SET label=? WHERE uid=?",
                           [(key(scheme, label), uid) for uid, label in sorted(changed.items())])
        end = perf_counter_ns()
        if profile is not None:
            profile.extend((after_edit - start, after_labels - after_edit,
                            after_delta - after_labels, end - after_delta))
        expected = scheme.labels(tree, labels)
        assert expected == {**labels, **added, **changed}
        assert len(added) == 26
        assert len(changed) == (payload + 2 if scheme.name == "dewey" else 0)
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
