"""Split the global preparation time for the 100k-node, 514-rewrite fixture."""
import csv
import random
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from objects import SCHEMES, measure

writer = csv.writer(sys.stdout, lineterminator="\n")
writer.writerow(("repeat", "scheme", "edit_ns", "labels_ns", "compare_ns", "sqlite_ns"))
schemes = [scheme for scheme in SCHEMES if scheme.name in ("dewey", "dde")]
rng = random.Random(2028)
with TemporaryDirectory() as directory:
    database = Path(directory) / "profile.sqlite"
    for repeat in range(9):
        rng.shuffle(schemes)
        for scheme in schemes:
            phases = []
            _, delta, sqlite, total = measure(database, 100000, 512, scheme, "global", phases)
            assert sum(phases[:3]) == delta and phases[3] == sqlite and sum(phases) == total
            writer.writerow((repeat, scheme.name, *phases))
            database.unlink()
