"""SQLite helpers with explicit lifetime control.

sqlite3.Connection context managers commit or roll back, but do not close the file handle. Explicit closing matters
on Windows where an open handle blocks replacing or deleting run artifacts.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import sqlite3


@contextmanager
def ro_connection(path):
    con = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    try:
        yield con
    finally:
        con.close()
