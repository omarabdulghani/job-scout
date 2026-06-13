"""Conservative process identity checks for dashboard-managed scout runs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import signal
import sys
from typing import Any


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001


def inspect_process(process_id: int) -> dict[str, Any]:
    """Return enough identity data to distinguish a live process from PID reuse."""
    process_id = int(process_id or 0)
    if process_id <= 0:
        return {"alive": False, "process_id": process_id}
    if sys.platform == "win32":
        return _inspect_windows_process(process_id)
    return _inspect_posix_process(process_id)


def terminate_process(process_id: int) -> bool:
    """Terminate a process previously verified by the dashboard controller."""
    process_id = int(process_id or 0)
    if process_id <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, process_id)
        if not handle:
            return False
        try:
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return False
    return True


def _inspect_windows_process(process_id: int) -> dict[str, Any]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return {"alive": False, "process_id": process_id}
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return {"alive": False, "process_id": process_id}

        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        executable = ""
        if kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            ctypes.byref(size),
        ):
            executable = str(Path(buffer.value).resolve()).lower()

        creation_token = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        return {
            "alive": True,
            "process_id": process_id,
            "creation_token": str(creation_token),
            "executable": executable,
        }
    finally:
        kernel32.CloseHandle(handle)


def _inspect_posix_process(process_id: int) -> dict[str, Any]:
    try:
        os.kill(process_id, 0)
    except (OSError, ProcessLookupError):
        return {"alive": False, "process_id": process_id}

    creation_token = ""
    executable = ""
    stat_path = Path("/proc") / str(process_id) / "stat"
    exe_path = Path("/proc") / str(process_id) / "exe"
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
        creation_token = fields[21] if len(fields) > 21 else ""
    except OSError:
        pass
    try:
        executable = str(exe_path.resolve()).lower()
    except OSError:
        pass
    return {
        "alive": True,
        "process_id": process_id,
        "creation_token": creation_token,
        "executable": executable,
    }
