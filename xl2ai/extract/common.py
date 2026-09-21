"""Constants shared by the extraction modules and the console logger."""
from __future__ import annotations

import sys
import time

try:
    import pythoncom
    import pywintypes
    import win32api
    import win32com.client as win32
    import win32gui
    import win32process
except ImportError:
    print("ERROR: pywin32 is not installed. Run:  pip install pywin32")
    sys.exit(1)

SCHEMA_VERSION = 1
XL_CALC_MANUAL = -4135
XL_WORKSHEET = -4167
XL_FORMULAS, XL_PART, XL_BYROWS, XL_BYCOLS, XL_NEXT, XL_PREV = -4123, 2, 1, 2, 1, 2
VISIBILITY = {-1: "visible", 0: "hidden", 2: "very hidden"}
ERROR_TEXT = {-2146826288: "#NULL!", -2146826281: "#DIV/0!", -2146826273: "#VALUE!", -2146826265: "#REF!",
              -2146826259: "#NAME?", -2146826252: "#NUM!", -2146826246: "#N/A", -2146826245: "#GETTING_DATA"}
ERR_LO, ERR_HI = -2146826300, -2146826200
MAX_SAFE_INT = 2 ** 53
HEADER_SCAN_ROWS = 30
PROCESS_TERMINATE, PROCESS_QUERY_LIMITED = 0x0001, 0x1000
STILL_ACTIVE = 259
BUSY_CODES = {-2147418111, -2147417846}                                  # call rejected / retry later
DEAD_CODES = {-2147023174, -2147023170, -2147023169, -2147417848, -2147417836}  # RPC unavailable/failed/disconnected
NoneType = type(None)


def log(level, msg):
    print(f"[{time.strftime('%H:%M:%S')}] {level:<5} {msg}", flush=True)
