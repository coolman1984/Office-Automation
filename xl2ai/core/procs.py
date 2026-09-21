"""Process helpers without pywin32 (ctypes only).

Never use os.kill(pid, 0) on Windows: it terminates the process instead of probing it.
"""
from __future__ import annotations

import ctypes

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = ctypes.c_void_p
_k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
_k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def memory_status():
    """{'phys_free_mb','commit_free_mb','load_percent'}. commit_free is what a new allocation needs: when it is
    near zero, Python raises MemoryError and Excel dies with RPC errors, regardless of free physical RAM."""
    st = _MemoryStatusEx()
    st.dwLength = ctypes.sizeof(st)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return {}
    return {"phys_free_mb": st.ullAvailPhys // 2 ** 20, "commit_free_mb": st.ullAvailPageFile // 2 ** 20,
            "load_percent": st.dwMemoryLoad}


def pid_alive(pid):
    if not pid:
        return False
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_uint32()
        return bool(_k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        _k32.CloseHandle(h)


def kill_pid(pid):
    """Terminate exactly this process. Only ever call it with a pid this tool started."""
    if not pid:
        return
    h = _k32.OpenProcess(PROCESS_TERMINATE, 0, int(pid))
    if h:
        try:
            _k32.TerminateProcess(h, 1)
        finally:
            _k32.CloseHandle(h)
