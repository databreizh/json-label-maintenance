"""Object-key insertion with three schemes and an ablation of whole-tree maintenance.

Maintenance modes
  global       reference whole-tree recomputation (generic Scheme.labels)
  global-spec  specialized whole-tree pass: Dewey recomputes ranks without prior state;
               DDE and ORDPATH copy each surviving label from the prior map by node ID
               and allocate only for nodes absent from it (no sibling-code or anchor lists)
  global-reuse Dewey only: specialized pass that reuses a prior label when the parent
               label and the sibling rank are unchanged
  local        explicit edit: label the inserted subtree (and, for Dewey, the shifted suffix)
"""
import argparse
import csv
import os
import platform
import random
import sqlite3
import subprocess
import tempfile
import sys
from contextlib import closing
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from labeling import JsonTree, SCHEMES, between_ordpaths
from mixed import collect, dde_between, key

SIZES = (4096, 100000)
PAYLOADS = (0, 64, 512)
REPEATS = 15
SCHEME_NAMES = ("dewey", "dde", "ordpath")
MODES = ("global", "global-spec", "global-reuse", "local")


def methods_for(scheme):
    return [m for m in MODES if scheme == "dewey" or m != "global-reuse"]


def fixture(size, payload):
    return {"background": {"payload": list(range(payload, size - 8))},
            "target": {"a": {"payload": []},
                       "z": {"payload": list(range(payload))}}}


def dewey_snapshot(tree):
    """Dense ranks recomputed from the current snapshot, without prior state."""
    labels = {}

    def visit(node, label):
        labels[node.uid] = label
        for rank, (_, child) in enumerate(node.children, 1):
            visit(child, (*label, rank))

    visit(tree.root, (1,))
    return labels


def dewey_reuse_snapshot(tree, old):
    """Dense ranks that reuse a prior label when the parent label and rank are unchanged."""
    labels = {}
    get = old.get

    def visit(node, label, same):
        labels[node.uid] = label
        for rank, (_, child) in enumerate(node.children, 1):
            prior = get(child.uid) if same else None
            if prior is not None and prior[-1] == rank:
                visit(child, prior, True)
            else:
                visit(child, (*label, rank), False)

    visit(tree.root, (1,), True)
    return labels


def dde_allocate(parent, left, right):
    return dde_between(parent, left, right)


def ordpath_allocate(parent, left, right):
    depth = len(parent)
    return parent + between_ordpaths(None if left is None else left[depth:],
                                     None if right is None else right[depth:])


def dynamic_snapshot(tree, old, allocate):
    """Carry surviving labels by node ID; allocate only for new nodes (insert-only edits)."""
    labels = {}
    get = old.get

    def visit(node, label, survived):
        labels[node.uid] = label
        children = node.children
        left = None
        for index, (_, child) in enumerate(children):
            code = get(child.uid)
            if code is None:
                right = None
                if survived:
                    for _, sibling in children[index + 1:]:
                        right = get(sibling.uid)
                        if right is not None:
                            break
                code = allocate(label, left, right)
                visit(child, code, False)
            else:
                visit(child, code, True)
            left = code

    visit(tree.root, get(tree.root.uid, (1,)), tree.root.uid in old)
    return labels


def snapshot(scheme, mode, tree, previous):
    if mode == "global":
        return scheme.labels(tree, previous)
    if scheme.name == "dewey":
        return dewey_snapshot(tree) if mode == "global-spec" else dewey_reuse_snapshot(tree, previous)
    return dynamic_snapshot(tree, previous,
                            dde_allocate if scheme.name == "dde" else ordpath_allocate)


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
        tree.insert(("target",), "m", {"payload": list(range(24))})
        after_edit = perf_counter_ns()
        if mode != "local":
            new = snapshot(scheme, mode, tree, labels)
            after_labels = perf_counter_ns()
            added = {uid: label for uid, label in new.items() if uid not in labels}
            changed = {uid: label for uid, label in new.items()
                       if uid in labels and labels[uid] != label}
        else:
            parent = tree.at(("target",))
            left, inserted, right = (node for _, node in parent.children)
            added, changed = {}, {}
            prefix = labels[parent.uid]
            if scheme.name == "dde":
                collect(inserted, dde_between(prefix, labels[left.uid], labels[right.uid]), added)
            elif scheme.name == "ordpath":
                collect(inserted, ordpath_allocate(prefix, labels[left.uid], labels[right.uid]),
                        added, True)
            else:
                collect(inserted, (*prefix, 2), added)
                collect(right, (*prefix, 3), changed)
            after_labels = perf_counter_ns()
        after_delta = perf_counter_ns()
        with db:
            db.executemany("INSERT INTO nodes VALUES (?,?)",
                           [(uid, key(scheme, label)) for uid, label in sorted(added.items())])
            db.executemany("UPDATE nodes SET label=? WHERE uid=?",
                           [(key(scheme, label), uid) for uid, label in sorted(changed.items())])
        end = perf_counter_ns()
        # Verification, outside the timed interval.
        expected = scheme.labels(tree, labels)
        assert expected == {**labels, **added, **changed}
        assert len(added) == 26
        assert len(changed) == (payload + 2 if scheme.name == "dewey" else 0)
        actual = dict(db.execute("SELECT uid,label FROM nodes INDEXED BY by_label"))
        assert actual == {uid: key(scheme, label) for uid, label in expected.items()}
        assert len(set(actual.values())) == len(actual)
        return (len(changed), after_edit - start, after_labels - after_edit,
                after_delta - after_labels, end - after_delta, end - start)


def environment():
    """Describe the host; works on Linux, macOS and Windows (missing fields become '?')."""
    def run(command):
        try:
            return subprocess.run(command, capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return ""
    cpu = next((line.split(":", 1)[1].strip() for line in run(["lscpu"]).splitlines()
                if line.startswith("Model name")), "") or platform.processor() or "?"
    memory = "?"
    try:
        with open("/proc/meminfo") as info:
            memory = f"{int(next(l.split()[1] for l in info if l.startswith('MemTotal'))) // 1024} MiB"
    except (OSError, StopIteration, ValueError):
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                memory = f"{status.ullTotalPhys // 2**20} MiB"
    disk = run(["df", "-hT", tempfile.gettempdir()]).splitlines()[-1:] or [tempfile.gettempdir()]
    return (f"{platform.platform()}\nCPU {cpu} ({os.cpu_count()} logical)\n"
            f"Memory {memory}\nTemp filesystem {' '.join(disk)}\n"
            f"Python {platform.python_version()}\nSQLite {sqlite3.sqlite_version}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args()
    if args.environment:
        args.environment.write_text(environment(), encoding="utf-8")
    schemes = {s.name: s for s in SCHEMES if s.name in SCHEME_NAMES}
    rng = random.Random(2029)
    conditions = list(product(SIZES, PAYLOADS))
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("size", "payload", "repeat", "scheme", "mode", "rewrites",
                     "edit_ns", "labels_ns", "compare_ns", "sqlite_ns", "total_ns"))
    with TemporaryDirectory() as directory:
        db = Path(directory) / "objects.sqlite"
        for repeat in range(args.repeats):
            rng.shuffle(conditions)
            for size, payload in conditions:
                methods = [(s, m) for s in SCHEME_NAMES for m in methods_for(s)]
                rng.shuffle(methods)
                for scheme, mode in methods:
                    metrics = measure(db, size, payload, schemes[scheme], mode)
                    writer.writerow((size, payload, repeat, scheme, mode, *metrics))
                    sys.stdout.flush()
                    db.unlink()


if __name__ == "__main__":
    main()
