"""Source file detection from the first bytes (before Excel is started)."""
from __future__ import annotations

# Environment knowledge, not engine logic: files that start with one of these prefixes are wrapped by a corporate
# rights-management agent and can only be opened by Excel itself. Moves to project config in phase 1.
WRAPPER_PREFIXES = (b"<## NASCA DRM",)


def sniff_file(path):
    """'zip' | 'drm' | 'encrypted' | 'other' from the first bytes, so obvious failures are reported without Excel."""
    with open(path, "rb") as f:
        head = f.read(16)
        if head.startswith(b"PK"):
            return "zip"
        if head.startswith(WRAPPER_PREFIXES):
            return "drm"
        if head.startswith(bytes.fromhex("D0CF11E0A1B11AE1")) and not path.lower().endswith(".xls"):
            # an OOXML/xlsb file that is an OLE container = Office password encryption ('EncryptedPackage' stream)
            f.seek(0)
            if "EncryptedPackage".encode("utf-16-le") in f.read(64 * 1024 * 1024):
                return "encrypted"
    return "other"
