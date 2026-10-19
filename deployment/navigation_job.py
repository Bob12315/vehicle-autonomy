"""Nonblocking vehicle-loop facade over an isolated native Nav2 planning job.

Only immutable map/pose inputs cross to the worker thread. Nav2 itself runs
in the existing owned ROS/native subprocess group; no vehicle object crosses.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import time

from application.planning import ReadOnlyPlanningService
from contracts.core.time import TimePoint
from integrations.ros2.nav2_planner import Nav2Planner


class PlanningJob:
    def __init__(self, context, start, goal, policy, clearance_m, directory, *, backend_factory=None):
        self.cancelled = Event()
        self.directory = Path(directory)
        self.backend = (backend_factory or (lambda: Nav2Planner(self.directory, cancelled=self.cancelled.is_set)))()
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix="vaf-readonly-plan")
        # Preserve the ORIGINAL capture. Admission rechecks the latest map in
        # the main loop; this worker validates only this immutable snapshot.
        context = replace(context,max_age_ns=10_000_000_000)
        clock = lambda: TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),context.captured_at.clock_domain_id)
        self.future = self.executor.submit(ReadOnlyPlanningService(lambda:context,self.backend,clock).plan,
            start,goal,timeout_s=policy.planning_timeout_s,clearance_m=clearance_m)
        self.closed = False

    def cancel(self):
        self.cancelled.set()

    @property
    def done(self):
        return self.future.done()

    def result(self):
        if not self.done:
            raise RuntimeError("planning result is not ready")
        return self.future.result()

    def close(self):
        if self.closed:return
        self.cancel()
        try:
            self.future.result(timeout=8)
        except TimeoutError:
            # A completed backend may itself raise TimeoutError. Only an
            # unfinished future means the worker exceeded this join barrier.
            if not self.future.done():
                raise RuntimeError("planning_worker_shutdown_unconfirmed")
        except Exception:
            pass  # The caller records the job result; cleanup still joins it.
        self.executor.shutdown(wait=True)
        self.closed = True
