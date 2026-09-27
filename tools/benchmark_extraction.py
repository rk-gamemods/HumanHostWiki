"""Measure a fresh extraction and an unchanged repeat without copying source data.

The isolated result cache stays under .local/benchmarks for inspection. Process
peak memory excludes the Git reader subprocess and is labeled accordingly.
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wikibuild import extraction, snapshots
from wikibuild.storage import writer_lock


def peak_memory():
    if os.name != "nt":
        import resource
        amount = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return amount if sys.platform == "darwin" else amount * 1024

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                      "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def benchmark(source):
    project = json.loads((ROOT / "project.json").read_text())
    parent = ROOT / ".local/benchmarks"
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=parent))
    with writer_lock(work):
        receipt = snapshots.register(work, project, source)
        started = time.perf_counter()
        first, cold = extraction.run(work, project, source, receipt)
        cold["seconds"] = round(time.perf_counter() - started, 3)
        pointer = work / ".local/extraction-latest.json"
        stamp = pointer.stat().st_mtime_ns
        started = time.perf_counter()
        second, repeat = extraction.run(work, project, source, receipt)
        repeat["seconds"] = round(time.perf_counter() - started, 3)
        if first != second or stamp != pointer.stat().st_mtime_ns:
            raise ValueError("Unchanged repeat changed the result or pointer")
    return {"snapshot": receipt["snapshot_id"], "cold": cold, "repeat": repeat,
            "python_peak_working_set_bytes": peak_memory(), "memory_scope": "Python process only; excludes Git subprocess",
            "record_bytes": first["records"]["bytes"], "record_sha256": first["records"]["sha256"],
            "cache": str(work.relative_to(ROOT)), "byte_and_pointer_stability": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT.parent / "HumanHostCodebase")
    print(json.dumps(benchmark(parser.parse_args().source), indent=2))
