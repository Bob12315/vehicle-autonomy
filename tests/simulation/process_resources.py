"""Kernel process CPU clocks, including all threads, with read uncertainty.

Unlike /proc stat's USER_HZ ticks, this clock resolves short native acceptance
samples without 10 ms quantization. Interrupted reads never advance the previous
cut: their CPU work remains included in the next valid interval.
"""
import ctypes
import time

_libc=ctypes.CDLL(None)
_libc.clock_getcpuclockid.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_int)]
_libc.clock_getcpuclockid.restype=ctypes.c_int


def sample_cpu(pid,identity,previous):
    clock=ctypes.c_int()
    error=_libc.clock_getcpuclockid(pid,ctypes.byref(clock))
    if error:raise OSError(error,'owned process CPU clock unavailable')
    before=time.monotonic_ns();cpu=time.clock_gettime_ns(clock.value);after=time.monotonic_ns()
    span=after-before;wall=(before+after)//2;old=previous.get(identity)
    usage=None
    if span<=1_000_000:
        if old:
            if wall<=old[0] or cpu<old[1]:raise ValueError('resource measurement clock regressed')
            usage=(cpu-old[1])/(wall-old[0])*100
        previous[identity]=(wall,cpu)
    return dict(cpu_percent=usage,cpu_time_ns=cpu,cpu_sample_host_ns=wall,cpu_read_span_ns=span,
        cpu_source='POSIX process CPU clock, all threads, nanoseconds')
