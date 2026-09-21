"""Console logger shared by every stage."""
from __future__ import annotations

import time


def log(level, msg):
    print(f"[{time.strftime('%H:%M:%S')}] {level:<5} {msg}", flush=True)
