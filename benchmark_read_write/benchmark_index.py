"""Measure JSON edits, label maintenance and commits to a SQLite secondary index."""
import argparse
import csv
import json
import random
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from labeling import JsonTree, SCHEMES, load_json


def edit(tree, path, workload, step):
    size = len(tree.at(path).children)
    if workload == "mixed":
        phase = step % 4
        position = size // 2 if phase == 0 else (size - 1) // 2
        if phase == 0:
            tree.insert(path, position, {"_probe": step})
        elif phase == 1:
            tree.modify_scalar((*path, position, "_probe"), -step)
        elif phase == 2:
            return tree.move(path, position, 0)
        else:
            tree.delete((*path, 0))
    else:
        position = {"head": 0, "middle": size // 2, "hotspot": min(1, size)}[workload]
        tree.insert(path, position, {"_probe": step})
    return ()


def apply_delta(db, scheme, old, new):
    added = new.keys() - old.keys()
    removed = old.keys() - new.keys()
    changed = sorted(uid for uid in new.keys() & old.keys() if new[uid] != old[uid])
    with db:
        db.executemany("DELETE FROM nodes WHERE uid = ?", [(uid,) for uid in sorted(removed)])
        db.executemany("INSERT INTO nodes VALUES (?, ?)",
                       [(uid, scheme.serialize(new[uid])) for uid in sorted(added)])
        db.executemany("UPDATE nodes SET label = ? WHERE uid = ?",
                       [(scheme.serialize(new[uid]), uid) for uid in changed])
    return len(added), len(removed), len(changed)


def run_scheme(document, path, workload, steps, scheme, filename, verify):
    tree = JsonTree(document)
    with closing(sqlite3.connect(filename)) as db:
        db.execute("PRAGMA journal_mode = DELETE")
        db.execute("PRAGMA synchronous = FULL")
        db.execute("CREATE TABLE nodes(uid INTEGER PRIMARY KEY, label BLOB NOT NULL)")
        db.execute("CREATE INDEX by_label ON nodes(label)")
        previous = scheme.labels(tree)
        apply_delta(db, scheme, {}, previous)

        for step in range(steps):
            start = perf_counter_ns()
            invalidated = edit(tree, path, workload, step)
            after_edit = perf_counter_ns()
            current = scheme.labels(tree, previous, invalidated)
            after_labels = perf_counter_ns()
            inserted, deleted, updated = apply_delta(db, scheme, previous, current)
            end = perf_counter_ns()
            if verify:
                rows = dict(db.execute("SELECT uid, label FROM nodes INDEXED BY by_label"))
                expected = {uid: scheme.serialize(label) for uid, label in current.items()}
                if rows != expected:
                    raise AssertionError(f"Incorrect SQLite index after {scheme.name} step {step}")
            sizes = sorted(map(scheme.storage_bytes, current.values()))
            yield {
                "scheme": scheme.name, "step": step,
                "operation": ("insert", "modify", "move", "delete")[step % 4]
                if workload == "mixed" else "insert",
                "nodes_before": len(previous), "inserted": inserted, "deleted": deleted,
                "updated_existing": updated, "label_bytes_max": sizes[-1],
                "label_bytes_median": (sizes[(len(sizes) - 1) // 2] + sizes[len(sizes) // 2]) / 2,
                "edit_ns": after_edit - start,
                "label_ns": after_labels - after_edit,
                "index_ns": end - after_labels, "total_ns": end - start,
            }
            previous = current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=100)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--workload", choices=("head", "middle", "mixed", "hotspot"), default="head")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--array-path", default='["items"]')
    parser.add_argument("--db-dir", type=Path, help="Parent directory for temporary SQLite files")
    parser.add_argument("--verify", action="store_true", help="Check SQLite after each timed edit")
    args = parser.parse_args()
    if args.width < 0 or args.steps < 1 or args.repeats < 1:
        parser.error("Expected width >= 0, steps >= 1 and repeats >= 1")
    path = json.loads(args.array_path)
    if not isinstance(path, list):
        parser.error("--array-path must be a JSON array")
    if args.input:
        with args.input.open(encoding="utf-8") as file:
            document = load_json(file)
    else:
        document = {"items": [{"id": index, "value": [index, False]}
                              for index in range(args.width)]}
    if JsonTree(document).at(path).kind != "array":
        parser.error("The target must be an array")

    rng = random.Random(2026)
    writer = None
    with TemporaryDirectory(dir=args.db_dir) as directory:
        for repetition in range(args.repeats):
            schemes = list(SCHEMES)
            rng.shuffle(schemes)
            for scheme in schemes:
                filename = Path(directory) / f"{scheme.name}-{repetition}.sqlite"
                for metrics in run_scheme(document, path, args.workload, args.steps,
                                          scheme, filename, args.verify):
                    row = {"workload": args.workload, "repetition": repetition, **metrics}
                    if writer is None:
                        writer = csv.DictWriter(sys.stdout, fieldnames=list(row), lineterminator="\n")
                        writer.writeheader()
                    writer.writerow(row)
                filename.unlink()


if __name__ == "__main__":
    main()
