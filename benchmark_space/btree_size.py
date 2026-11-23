"""Portable B-tree size of an SQLite index, without the dbstat virtual table.

The database is copied with the backup API, the index is dropped in the copy,
and the pages it occupied are counted from the growth of the freelist
(auto_vacuum is off, so dropped pages stay on the freelist). The result equals
the sum of pgsize over the index in dbstat, overflow pages included.
"""
import sqlite3
from contextlib import closing


def index_bytes(db, name):
    if db.in_transaction:  # the backup API waits on an open write transaction
        db.commit()
    with closing(sqlite3.connect(":memory:")) as copy:
        db.backup(copy)
        page_size = copy.execute("PRAGMA page_size").fetchone()[0]
        assert copy.execute("PRAGMA auto_vacuum").fetchone()[0] == 0
        before = copy.execute("PRAGMA freelist_count").fetchone()[0]
        copy.execute(f'DROP INDEX "{name}"')
        after = copy.execute("PRAGMA freelist_count").fetchone()[0]
        return (after - before) * page_size
