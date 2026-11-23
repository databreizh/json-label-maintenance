"""Size of the auxiliary sibling-order index (Section 9, cost scope).

Run from the archive root. Prints pattern, scheme, sibling-index bytes, label-index bytes.
"""
import sys
sys.path[:0] = ["benchmark_read_write", "benchmark_space"]

from btree_size import index_bytes
from positional import prepare
from space import Run, SCHEMES, STEPS

schemes = {s.name: s for s in SCHEMES}
for pattern, seed in (("uniform", 1), ("zigzag", 0)):
    for variant in ("dde", "ordpath"):
        run = Run(schemes[variant], pattern, seed)
        for step in range(STEPS):
            run.step(step)
        prepare(run, variant)
        print(pattern, variant, index_bytes(run.db, "sib_order"), index_bytes(run.db, "by_label"))
