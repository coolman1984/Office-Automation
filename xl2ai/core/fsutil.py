"""Filesystem helpers: atomic writes, hashing, slugs."""
from __future__ import annotations

import hashlib
import json
import os
import re


def atomic_write_text(path, text):
    """Write so that readers see either the old complete file or the new complete file, never a partial one."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path, quick_above=None, chunk=1024 * 1024):
    """(hexdigest, mode). Full SHA-256 is the safe default; quick mode is explicit opt-in.

    Incremental refresh uses this fingerprint as a correctness boundary: if it says a source is unchanged, Excel may
    not be opened at all. A first/last-chunk fingerprint is therefore not strong enough as the default, especially for
    large business workbooks where changes can occur anywhere in the file.
    """
    size = os.path.getsize(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if quick_above is None or size <= quick_above:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
            return h.hexdigest(), "full"
        h.update(str(size).encode())
        h.update(f.read(chunk))
        f.seek(max(0, size - chunk))
        h.update(f.read(chunk))
    return h.hexdigest(), "quick"


def slug(text, maxlen=40):
    s = re.sub(r"[^\w]+", "-", str(text).strip(), flags=re.UNICODE).strip("-").lower()
    return (s or "source")[:maxlen].strip("-") or "source"
