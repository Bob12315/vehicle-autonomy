"""Best-effort cyclic-GC maintenance before opt-in native owner cycles.

Never disables GC or changes its thresholds. This is not a hard real-time
guarantee: all existing deadlines and Guard budgets still apply. Collection
time is paid before the owner processes ingress and samples write fences.
"""
import gc
from threading import Lock
import time

_collection_lock = Lock()


class CycleMaintenance:
    def __init__(self):
        self.collections = 0
        self.max_duration_ns = 0

    def run(self):
        if not gc.isenabled():
            return
        threshold = gc.get_threshold()[2]
        if threshold <= 0 or gc.get_count()[2] < max(1, threshold // 2):
            return
        if not _collection_lock.acquire(blocking=False):
            return
        try:
            started = time.monotonic_ns()
            gc.collect(2)
            self.collections += 1
            self.max_duration_ns = max(self.max_duration_ns, time.monotonic_ns() - started)
        finally:
            _collection_lock.release()

    def diagnostics(self):
        return dict(collections=self.collections, max_duration_ns=self.max_duration_ns,
                    automatic_gc_enabled=gc.isenabled())
