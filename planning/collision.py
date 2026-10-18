"""Conservative configuration grid and independent continuous segment checking."""
from __future__ import annotations

import math
from dataclasses import replace

from .models import PlanningError


class CollisionGrid:
    def __init__(self, context, clearance_m):
        self.context = context
        self.grid = context.grid
        self.clearance = clearance_m
        w, h = self.grid.width, self.grid.height
        # Unknown and ambiguous occupancy are obstacles. Only 0..19 is free.
        self.prefix = [0] * ((w+1)*(h+1))
        for y in range(h):
            running = 0
            for x in range(w):
                running += not 0 <= self.grid.cells[y*w+x] <= 19
                self.prefix[(y+1)*(w+1)+x+1] = running+self.prefix[y*(w+1)+x+1]

    def count(self, left, bottom, right, top):
        stride = self.grid.width+1
        p = self.prefix
        return p[top*stride+right]-p[bottom*stride+right]-p[top*stride+left]+p[bottom*stride+left]

    def configuration_grid(self):
        """A square superset of the circular clearance, plus one cell margin.

        This deliberately sacrifices narrow passages; no vehicle motion model
        or orientation-specific footprint feasibility is claimed.
        """
        g = self.grid
        k = math.ceil(self.clearance/g.resolution_m)+1
        cells = tuple(100 if x < k or y < k or x+k >= g.width or y+k >= g.height
                      or self.count(x-k, y-k, x+k+1, y+k+1) else 0
                      for y in range(g.height) for x in range(g.width))
        return replace(g, cells=cells)

    @staticmethod
    def intersects(a, b, left, bottom, right, top):
        # Slab clipping checks the whole segment, including grazing contact.
        lo, hi = 0., 1.
        for start, end, low, high in ((a.x, b.x, left, right), (a.y, b.y, bottom, top)):
            delta = end-start
            if abs(delta) < 1e-15:
                if start < low or start > high:
                    return False
            else:
                t0, t1 = (low-start)/delta, (high-start)/delta
                if t0 > t1:t0, t1 = t1, t0
                lo, hi = max(lo, t0), min(hi, t1)
                if lo > hi:return False
        return True

    def validate(self, poses):
        g, radius = self.grid, self.clearance+1e-9
        local = tuple(self.context.to_local(p) for p in poses)
        for p in local:
            if not radius < p.x < g.width*g.resolution_m-radius or not radius < p.y < g.height*g.resolution_m-radius:
                raise PlanningError("INVALID_PATH", "path footprint touches the map boundary")
        length, work = 0., 0
        for a, b in zip(local, local[1:] or local):
            length += math.hypot(b.x-a.x, b.y-a.y)
            if length > 1000:
                raise PlanningError("INVALID_PATH", "path exceeds the one kilometre bound")
            # Include cells ending exactly on the lower bounding edge too.
            x0, x1 = max(0, math.floor((min(a.x,b.x)-radius)/g.resolution_m)-1), min(g.width-1, math.floor((max(a.x,b.x)+radius)/g.resolution_m))
            y0, y1 = max(0, math.floor((min(a.y,b.y)-radius)/g.resolution_m)-1), min(g.height-1, math.floor((max(a.y,b.y)+radius)/g.resolution_m))
            if not self.count(x0,y0,x1+1,y1+1):continue
            work += (x1-x0+1)*(y1-y0+1)
            if work > 2_000_000:
                raise PlanningError("INVALID_PATH", "path collision-check work bound exceeded")
            for y in range(y0,y1+1):
                for x in range(x0,x1+1):
                    if 0 <= g.cells[y*g.width+x] <= 19:continue
                    if self.intersects(a,b,x*g.resolution_m-radius,y*g.resolution_m-radius,
                                       (x+1)*g.resolution_m+radius,(y+1)*g.resolution_m+radius):
                        raise PlanningError("INVALID_PATH", "path footprint intersects occupied, uncertain or unknown cells")
        return length
