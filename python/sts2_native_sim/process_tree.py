"""Own a spawned full-app process and every descendant it creates."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from typing import Any


if os.name == "nt":
    from ctypes import wintypes

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_int64),
            ("per_job_user_time_limit", ctypes.c_int64),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operation_count", ctypes.c_uint64),
            ("write_operation_count", ctypes.c_uint64),
            ("other_operation_count", ctypes.c_uint64),
            ("read_transfer_count", ctypes.c_uint64),
            ("write_transfer_count", ctypes.c_uint64),
            ("other_transfer_count", ctypes.c_uint64),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", _BasicLimitInformation),
            ("io_info", _IoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    _ntdll.NtResumeProcess.restype = ctypes.c_long


class OwnedProcessTree:
    """The process is never allowed to run before its tree has an owner."""

    def __init__(self, process: subprocess.Popen[bytes], job: int | None) -> None:
        self.process = process
        self._job = job

    @classmethod
    def spawn(cls, args: list[str], **options: Any) -> OwnedProcessTree:
        if os.name == "nt":
            job = _kernel32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                limits = _ExtendedLimitInformation()
                limits.basic_limit_information.limit_flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not _kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                    raise ctypes.WinError(ctypes.get_last_error())
                # CREATE_SUSPENDED prevents the child from escaping before assignment.
                process = subprocess.Popen(args, creationflags=options.pop("creationflags", 0) | 0x4, **options)
                owner = cls(process, job)
                job = None  # The owner now holds the only Job Object handle.
                try:
                    process_handle = int(getattr(process, "_handle"))
                    if not _kernel32.AssignProcessToJobObject(owner._job, process_handle):
                        raise ctypes.WinError(ctypes.get_last_error())
                    status = _ntdll.NtResumeProcess(process_handle)
                    if status != 0:
                        raise OSError(f"NtResumeProcess failed with NTSTATUS {status:#x}")
                except BaseException:
                    owner.close()
                    raise
                return owner
            except BaseException:
                if job is not None:
                    _kernel32.CloseHandle(job)
                raise

        process = subprocess.Popen(args, start_new_session=True, **options)
        return cls(process, None)

    def close(self) -> None:
        if os.name == "nt" and self._job is not None:
            _kernel32.CloseHandle(self._job)
            self._job = None
        elif os.name != "nt":
            try:
                getattr(os, "killpg")(self.process.pid, getattr(signal, "SIGKILL"))
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
