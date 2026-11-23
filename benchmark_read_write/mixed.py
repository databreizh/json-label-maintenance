"""Indexed label lookups, descendant ranges and successive array edits."""
import csv
import random
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from additional_schemes import dde_between
from labeling import JsonTree, SCHEMES, between_ordpaths, load_json, preorder
from local import collect

EXACT = "SELECT uid FROM nodes WHERE label = ?"
RANGE = "SELECT uid FROM nodes WHERE label > ? AND label < ?"
REPEATS = 7


def key(scheme, label):
    if scheme.name == "dde":
        denominator = label[0]
        label = (str(Fraction(component, denominator)).replace("/", "_")
                 for component in label)
    return ("/".join(map(str, label)) + "/").encode("ascii")


def edit_delta(tree, scheme, labels, path, position, insert):
    parent = tree.at(path)
    parent_label = labels[parent.uid]
    if insert:
        tree.insert(path, position, {"payload": list(range(24))})
        child = parent.children[position][1]
        removed = []
    else:
        removed = [node.uid for node in preorder(parent.children[position][1])]
        tree.delete((*path, position))
    added, changed = {}, {}
    if scheme.name == "dewey":
        for index in range(position, len(parent.children)):
            collect(parent.children[index][1], (*parent_label, index + 1),
                    added if insert and index == position else changed)
    elif insert:
        left = labels[parent.children[position - 1][1].uid] if position else None
        right = (labels[parent.children[position + 1][1].uid]
                 if position + 1 < len(parent.children) else None)
        if scheme.name == "ordpath":
            depth = len(parent_label)
            left = left[depth:] if left is not None else None
            right = right[depth:] if right is not None else None
            new_label = parent_label + between_ordpaths(left, right)
        else:
            new_label = dde_between(parent_label, left, right)
        collect(child, new_label, added, scheme.name == "ordpath")
    return added, changed, removed


def trial(db_path, records, scheme, corpus, repeat):
    tree = JsonTree({"records": records, "target": [{"payload": list(range(24))}
                                                   for _ in range(32)]})
    labels = scheme.labels(tree)
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE nodes(uid INTEGER PRIMARY KEY,label BLOB NOT NULL)")
        db.execute("CREATE INDEX by_label ON nodes(label)")
        with db:
            db.executemany("INSERT INTO nodes VALUES (?,?)",
                           [(uid, key(scheme, label)) for uid, label in labels.items()])
        for query, params in ((EXACT, (b"1/",)), (RANGE, (b"1/", b"10"))):
            plan = db.execute("EXPLAIN QUERY PLAN " + query, params).fetchall()
            assert any("SEARCH" in row[3] and "by_label" in row[3] for row in plan), plan

        for stage in range(4):
            if stage < 3:
                # Insert, delete an existing object, then insert again in the same zone.
                for insert in (True, False, True, False):
                    parent = tree.at(("target",))
                    size = len(parent.children)
                    pos = (0, size // 2, size)[stage] if insert else (1, size // 2 + 1, size - 2)[stage]
                    start = perf_counter_ns()
                    added, changed, removed = edit_delta(tree, scheme, labels, ("target",), pos, insert)
                    after_label = perf_counter_ns()
                    with db:
                        db.executemany("DELETE FROM nodes WHERE uid=?", [(uid,) for uid in removed])
                        db.executemany("INSERT INTO nodes VALUES (?,?)",
                                       [(uid, key(scheme, label)) for uid, label in added.items()])
                        db.executemany("UPDATE nodes SET label=? WHERE uid=?",
                                       [(key(scheme, label), uid) for uid, label in changed.items()])
                    for uid in removed:
                        del labels[uid]
                    labels.update(added)
                    labels.update(changed)
                    elapsed = perf_counter_ns() - start
                    assert scheme.labels(tree, labels) == labels
                    assert len(set(key(scheme, v) for v in labels.values())) == len(labels)
                    assert dict(db.execute("SELECT uid,label FROM nodes")) == {
                        uid: key(scheme, label) for uid, label in labels.items()}
                    yield (corpus, repeat, scheme.name, "insert" if insert else "delete",
                           ("head", "middle", "tail")[stage], 0, len(changed), elapsed,
                           after_label - start, max(len(key(scheme, v)) for v in labels.values()))
            else:
                for name, node in (
                    ("record", tree.at(("records", 0))),
                    ("edited", tree.at(("target",))),
                    ("edited_child", tree.at(("target", 16))),
                    ("dataset", tree.at(("records",))),
                ):
                    prefix = key(scheme, labels[node.uid])
                    # '/' terminates every complete component; '0' is its byte successor.
                    upper = prefix[:-1] + b"0"
                    for op, query, params, expected in (
                        ("exact", EXACT, (prefix,), {node.uid}),
                        ("descendants", RANGE, (prefix, upper),
                         {n.uid for n in preorder(node)} - {node.uid}),
                    ):
                        actual = {uid for uid, in db.execute(query, params)}
                        assert actual == expected
                        start = perf_counter_ns()
                        for _ in range(50):
                            db.execute(query, params).fetchall()
                        elapsed = (perf_counter_ns() - start) // 50
                        yield (corpus, repeat, scheme.name, op, name, len(actual), 0, elapsed, 0, 0)


def main(paths):
    rng = random.Random(2027)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("corpus","repeat","scheme","operation","target","returned","rewrites",
                     "total_ns","edit_and_label_ns","max_key_bytes"))
    with TemporaryDirectory() as directory:
        database = Path(directory) / "index.sqlite"
        for corpus, path in zip(("Flask", "NYC 311"), paths, strict=True):
            with open(path, encoding="utf-8-sig") as source:
                records = load_json(source)
            for repeat in range(REPEATS):
                schemes = [s for s in SCHEMES if s.name in ("dde", "dewey", "ordpath")]
                rng.shuffle(schemes)
                for scheme in schemes:
                    writer.writerows(trial(database, records, scheme, corpus, repeat))
                    database.unlink()


if __name__ == "__main__":
    main(sys.argv[1:])
