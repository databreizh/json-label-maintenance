"""Label and index size under repeated array insertions (Dewey, DDE, ORDPATH).

Each run starts from an array of INITIAL two-node objects and performs STEPS
local insertions of a two-node object according to a pattern:
  uniform  random position (seeded)
  head     always position 0
  tail     always after the last element
  hotspot  always position 1, i.e. immediately before the previous insertion
  zigzag   always inside the gap between the two most recently created
           neighbours, alternating sides (narrowing gap)
Labels are maintained locally and applied to an SQLite index keyed by the
prefix-preserving encoding of Section 6. At checkpoints we record label sizes
under a common compact encoding (zigzag LEB128 per component) and under the
index key encoding; at the end we record the index B-tree size (btree_size.py), both
after incremental maintenance and after a rebuild from the final labels.
"""
import argparse
import csv
import random
import sqlite3
import sys
from contextlib import closing
from fractions import Fraction
from statistics import mean

from labeling import JsonTree, SCHEMES, between_ordpaths
from additional_schemes import dde_between, dde_order
from mixed import key
from btree_size import index_bytes
from local import collect

INITIAL = 500
STEPS = 2000
CHECKPOINTS = (0, 250, 500, 1000, 2000)
PATTERNS = ("uniform", "head", "tail", "hotspot", "zigzag")
SCHEME_NAMES = ("dewey", "dde", "ordpath")
UNIFORM_SEEDS = (1, 2, 3, 4, 5)


def dbstat_available():
    with closing(sqlite3.connect(":memory:")) as db:
        try:
            db.execute("SELECT 1 FROM dbstat LIMIT 1").fetchall()
            return True
        except sqlite3.OperationalError:
            return False


def varint_bytes(label):
    total = 0
    for component in label:
        value = (component << 1) ^ (component >> 63) if -2**63 <= component < 2**63 else None
        if value is None:  # arbitrary precision: zigzag without fixed width
            value = 2 * component if component >= 0 else -2 * component - 1
        total += max(1, (value.bit_length() + 6) // 7)
    return total


def allocate(scheme, parent_label, left, right):
    if scheme.name == "dde":
        return dde_between(parent_label, left, right)
    depth = len(parent_label)
    return parent_label + between_ordpaths(None if left is None else left[depth:],
                                           None if right is None else right[depth:])


def sort_key(scheme, label):
    return dde_order(label) if scheme.name == "dde" else label


class Run:
    def __init__(self, scheme, pattern, seed):
        self.scheme, self.pattern = scheme, pattern
        self.rng = random.Random(seed)
        self.tree = JsonTree({"items": [{"v": i} for i in range(INITIAL)]})
        self.labels = scheme.labels(self.tree)
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE nodes(uid INTEGER PRIMARY KEY, label BLOB NOT NULL)")
        self.db.execute("CREATE INDEX by_label ON nodes(label)")
        with self.db:
            self.db.executemany("INSERT INTO nodes VALUES (?,?)",
                                [(u, key(scheme, l)) for u, l in self.labels.items()])
        self.rewrites = 0
        self.gap = None  # (left uid, right uid) for zigzag

    def position(self, step):
        parent = self.tree.at(("items",))
        n = len(parent.children)
        p = self.pattern
        if p == "uniform":
            return self.rng.randint(0, n)
        if p == "head":
            return 0
        if p == "tail":
            return n
        if p == "hotspot":
            return 1
        if self.gap is None:  # zigzag
            self.gap = (parent.children[0][1].uid, parent.children[1][1].uid)
        left_uid = self.gap[0]
        index = next(i for i, (_, c) in enumerate(parent.children) if c.uid == left_uid)
        return index + 1

    def step(self, step):
        scheme, tree, labels = self.scheme, self.tree, self.labels
        position = self.position(step)
        tree.insert(("items",), position, {"v": INITIAL + step})
        parent = tree.at(("items",))
        child = parent.children[position][1]
        added, changed = {}, {}
        if scheme.name == "dewey":
            for index in range(position, len(parent.children)):
                collect(parent.children[index][1], (*labels[parent.uid], index + 1),
                        added if index == position else changed)
        else:
            left = labels[parent.children[position - 1][1].uid] if position else None
            right = (labels[parent.children[position + 1][1].uid]
                     if position + 1 < len(parent.children) else None)
            collect(child, allocate(scheme, labels[parent.uid], left, right), added,
                    scheme.name == "ordpath")
        if self.pattern == "zigzag":
            left_uid, right_uid = self.gap
            self.gap = (child.uid, right_uid) if step % 2 == 0 else (left_uid, child.uid)
        changed = {u: l for u, l in changed.items() if labels[u] != l}
        self.rewrites += len(changed)
        labels.update(added)
        labels.update(changed)
        with self.db:
            self.db.executemany("INSERT INTO nodes VALUES (?,?)",
                                [(u, key(scheme, l)) for u, l in added.items()])
            self.db.executemany("UPDATE nodes SET label=? WHERE uid=?",
                                [(key(scheme, l), u) for u, l in changed.items()])

    def verify(self):
        scheme, labels = self.scheme, self.labels
        expected = scheme.labels(self.tree, None if scheme.name == "dewey" else labels)
        assert expected == labels
        items = self.tree.at(("items",)).children
        order = [sort_key(scheme, labels[c.uid]) for _, c in items]
        assert all(a < b for a, b in zip(order, order[1:])), "sibling order violated"
        keys = dict(self.db.execute("SELECT uid,label FROM nodes INDEXED BY by_label"))
        assert keys == {u: key(scheme, l) for u, l in labels.items()}
        assert len(set(keys.values())) == len(keys)

    def sizes(self):
        compact = [varint_bytes(l) for l in self.labels.values()]
        encoded = [len(key(self.scheme, l)) for l in self.labels.values()]
        depth = [len(l) for l in self.labels.values()]
        return (len(self.labels), round(mean(compact), 3), max(compact),
                round(mean(encoded), 3), max(encoded), max(depth))

    def index_bytes(self):
        """Index B-tree bytes after incremental maintenance and after a rebuild.

        Sizes use btree_size.index_bytes (portable, equal to dbstat's pgsize total).
        The payload columns need dbstat and stay empty where SQLite lacks it.
        """
        def stat(db):
            payload = ""
            if dbstat_available():
                payload = db.execute("SELECT sum(payload) FROM dbstat WHERE name='by_label'").fetchone()[0]
            return index_bytes(db, "by_label"), payload
        incremental = stat(self.db)
        with closing(sqlite3.connect(":memory:")) as fresh:
            fresh.execute("CREATE TABLE nodes(uid INTEGER PRIMARY KEY, label BLOB NOT NULL)")
            fresh.executemany("INSERT INTO nodes VALUES (?,?)",
                              [(u, key(self.scheme, l)) for u, l in sorted(self.labels.items())])
            fresh.execute("CREATE INDEX by_label ON nodes(label)")
            rebuilt = stat(fresh)
        return (*incremental, *rebuilt)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=STEPS)
    args = parser.parse_args()
    schemes = {s.name: s for s in SCHEMES if s.name in SCHEME_NAMES}
    out = csv.writer(sys.stdout, lineterminator="\n")
    out.writerow(("pattern", "seed", "scheme", "inserted", "nodes", "compact_mean", "compact_max",
                  "key_mean", "key_max", "depth_max", "rewrites_cumulative",
                  "index_bytes", "index_payload", "rebuilt_bytes", "rebuilt_payload"))
    for pattern in PATTERNS:
        for seed in (UNIFORM_SEEDS if pattern == "uniform" else (0,)):
            for name in SCHEME_NAMES:
                run = Run(schemes[name], pattern, seed)
                for step in range(args.steps + 1):
                    if step in CHECKPOINTS or step == args.steps:
                        run.verify()
                        extra = run.index_bytes() if step == args.steps else ("",) * 4
                        out.writerow((pattern, seed, name, step, *run.sizes(),
                                      run.rewrites, *extra))
                        sys.stdout.flush()
                    if step < args.steps:
                        run.step(step)
                run.db.close()


if __name__ == "__main__":
    main()
