"""Positional access (k-th element of an array) after the insertion sequences of space.py.

Dewey  : the k-th element has key parent/(k+1)/, one equality probe on the label index.
ORDPATH: sibling codes are order-preserving under a byte encoding; an auxiliary index on
         (parent, code) answers ORDER BY code LIMIT 1 OFFSET k.
DDE    : sibling order compares the rationals a_d/a_1. With an order-preserving key for
         exact rationals (ordkeys.rational_key), the same (parent, key) index answers
         OFFSET k. A naive baseline (dde-sort) fetches all children and sorts fractions.
Each query is checked against the in-memory tree.
"""
import csv
import statistics
import sys
from fractions import Fraction
from time import perf_counter_ns

from space import Run, SCHEMES, STEPS
from mixed import key
from ordkeys import ordpath_key, rational_key

PATTERNS = (("uniform", 1), ("head", 0), ("hotspot", 0), ("zigzag", 0))
REPEATS, INNER = 7, 50


def prepare(run, variant):
    scheme, db, labels = run.scheme, run.db, run.labels
    parent = run.tree.at(("items",))
    plabel = labels[parent.uid]
    if variant in ("ordpath", "dde"):
        def order_key(label):
            if variant == "ordpath":
                return ordpath_key(label[len(plabel):])
            return rational_key(Fraction(label[-1], label[0]))
        db.execute("CREATE TABLE sib(parent INTEGER, skey BLOB, uid INTEGER)")
        db.executemany("INSERT INTO sib VALUES (?,?,?)",
                       [(parent.uid, order_key(labels[c.uid]), c.uid)
                        for _, c in parent.children])
        db.execute("CREATE INDEX sib_order ON sib(parent, skey)")
        plan = db.execute("EXPLAIN QUERY PLAN SELECT uid FROM sib WHERE parent=? "
                          "ORDER BY skey LIMIT 1 OFFSET ?", (parent.uid, 0)).fetchall()
        assert any("sib_order" in row[-1] for row in plan), plan

        def query(k):
            return db.execute("SELECT uid FROM sib WHERE parent=? ORDER BY skey LIMIT 1 OFFSET ?",
                              (parent.uid, k)).fetchone()[0]
    elif variant == "dde-sort":
        db.execute("CREATE TABLE sib(parent INTEGER, num TEXT, den TEXT, uid INTEGER)")
        db.executemany("INSERT INTO sib VALUES (?,?,?,?)",
                       [(parent.uid, str(labels[c.uid][-1]), str(labels[c.uid][0]), c.uid)
                        for _, c in parent.children])
        db.execute("CREATE INDEX sib_parent ON sib(parent)")

        def query(k):
            rows = db.execute("SELECT uid, num, den FROM sib WHERE parent=?", (parent.uid,)).fetchall()
            rows.sort(key=lambda r: Fraction(int(r[1]), int(r[2])))
            return rows[k][0]
    else:
        prefix = plabel

        def query(k):
            return db.execute("SELECT uid FROM nodes WHERE label=?",
                              (key(scheme, (*prefix, k + 1)),)).fetchone()[0]
    return parent, query


def main():
    schemes = {s.name: s for s in SCHEMES if s.name in ("dewey", "dde", "ordpath")}
    out = csv.writer(sys.stdout, lineterminator="\n")
    out.writerow(("pattern", "variant", "children", "k", "median_us", "min_us", "max_us"))
    for pattern, seed in PATTERNS:
        for variant in ("dewey", "dde", "dde-sort", "ordpath"):
            name = variant.split("-")[0]
            run = Run(schemes[name], pattern, seed)
            for step in range(STEPS):
                run.step(step)
            run.verify()
            parent, query = prepare(run, variant)
            n = len(parent.children)
            for k in (0, n // 4, n // 2, n - 1):
                assert query(k) == parent.children[k][1].uid
                samples = []
                for _ in range(REPEATS):
                    start = perf_counter_ns()
                    for _ in range(INNER):
                        query(k)
                    samples.append((perf_counter_ns() - start) / INNER / 1e3)
                out.writerow((pattern, variant, n, k, round(statistics.median(samples), 2),
                              round(min(samples), 2), round(max(samples), 2)))
                sys.stdout.flush()
            run.db.close()


if __name__ == "__main__":
    main()
