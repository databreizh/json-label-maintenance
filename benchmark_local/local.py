"""Local label and SQLite maintenance for insertions into JSON arrays."""
import csv
import random
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from additional_schemes import dde_between
from benchmark_index import apply_delta
from labeling import JsonTree, SCHEMES, load_json, between_ordpaths
from run import LEVELS, REPEATS


def collect(node, label, result, odd=False):
    result[node.uid] = label
    for rank, (_, child) in enumerate(node.children, 1):
        collect(child, (*label, 2 * rank - 1 if odd else rank), result, odd)


def insert_and_measure(db, tree, scheme, labels, path, position, value):
    """Apply an insertion to a fresh in-memory fixture and commit the label delta."""
    start = perf_counter_ns()
    tree.insert(path, position, value)
    parent = tree.at(path)
    after_edit = perf_counter_ns()
    child = parent.children[position][1]
    added, changed = {}, {}
    if scheme.name == "dewey":
        for index in range(position, len(parent.children)):
            current = parent.children[index][1]
            delta = added if index == position else changed
            collect(current, (*labels[parent.uid], index + 1), delta)
    else:
        left = labels[parent.children[position - 1][1].uid] if position else None
        right = (labels[parent.children[position + 1][1].uid]
                 if position + 1 < len(parent.children) else None)
        parent_label = labels[parent.uid]
        if scheme.name == "ordpath":
            depth = len(parent_label)
            left_code = None if left is None else left[depth:]
            right_code = None if right is None else right[depth:]
            label = parent_label + between_ordpaths(left_code, right_code)
        else:
            label = dde_between(parent_label, left, right)
        collect(child, label, added, scheme.name == "ordpath")
    after_labels = perf_counter_ns()
    with db:
        db.executemany("INSERT INTO nodes VALUES (?, ?)",
                       [(uid, scheme.serialize(label)) for uid, label in sorted(added.items())])
        db.executemany("UPDATE nodes SET label = ? WHERE uid = ?",
                       [(scheme.serialize(label), uid) for uid, label in sorted(changed.items())])
    end = perf_counter_ns()

    expected = scheme.labels(tree, labels)
    assert added == {uid: expected[uid] for uid in expected.keys() - labels.keys()}
    assert changed == {uid: label for uid, label in expected.items()
                       if uid in labels and labels[uid] != label}
    assert dict(db.execute("SELECT uid, label FROM nodes INDEXED BY by_label")) == {
        uid: scheme.serialize(label) for uid, label in expected.items()
    }
    return {"rewritten": len(changed), "inserted": len(added),
            "edit_ns": after_edit - start, "label_ns": after_labels - after_edit,
            "index_ns": end - after_labels, "total_ns": end - start}


def main(flask_path, nyc_path):
    sources = {}
    for name, path in (("Flask", flask_path), ("NYC 311", nyc_path)):
        with open(path, encoding="utf-8-sig") as file:
            sources[name] = load_json(file)
    schemes = [s for s in SCHEMES if s.name in ("dde", "dewey", "ordpath")]
    conditions = [(corpus, level, position) for corpus in sources
                  for level in LEVELS for position in range(3)]
    rng = random.Random(2026)
    writer = None
    with TemporaryDirectory() as directory:
        database = Path(directory) / "index.sqlite"
        for repeat in range(REPEATS):
            rng.shuffle(conditions)
            for corpus, level, position in conditions:
                document = {"background": sources[corpus],
                            "control": [{"payload": list(range(level, 512))}],
                            "target": [{"payload": list(range(level // 2))},
                                       {"payload": list(range(level // 2, level))}]}
                methods = list(schemes)
                rng.shuffle(methods)
                for scheme in methods:
                    tree = JsonTree(document)
                    labels = scheme.labels(tree)
                    with closing(sqlite3.connect(database)) as db:
                        db.execute("PRAGMA journal_mode = DELETE")
                        db.execute("PRAGMA synchronous = FULL")
                        db.execute("CREATE TABLE nodes(uid INTEGER PRIMARY KEY, label BLOB NOT NULL)")
                        db.execute("CREATE INDEX by_label ON nodes(label)")
                        apply_delta(db, scheme, {}, labels)
                        row = insert_and_measure(db, tree, scheme, labels, ("target",), position, {"_probe": 0})
                    database.unlink()
                    assert row["rewritten"] == ((level + 4, level - level // 2 + 2, 0)[position]
                                                if scheme.name == "dewey" else 0)
                    entry = {"corpus": corpus, "payload_nodes": level, "repeat": repeat,
                             "position": ("head", "middle", "tail")[position],
                             "scheme": scheme.name, "nodes_before": len(labels), **row}
                    if writer is None:
                        writer = csv.DictWriter(sys.stdout, fieldnames=entry, lineterminator="\n")
                        writer.writeheader()
                    writer.writerow(entry)


if __name__ == "__main__":
    main(*sys.argv[1:])
