"""Require actual IMU coverage across every rendered scan slice before admission."""
from bisect import bisect_left,bisect_right


def scan_coverage(imu_times,capture_times,*,return_times=None,pose_time_ns=None,max_gap_ns=20_000_000):
    imu=list(imu_times);captures=list(capture_times)
    if len(captures)!=5 or captures!=sorted(set(captures)) or any(type(v) is not int or v<0 for v in captures):
        raise ValueError('five actual ordered scan capture times required')
    used=captures if return_times is None else list(return_times)
    if not used or used!=sorted(set(used)) or not set(used)<=set(captures):raise ValueError('returned-point times must be actual acquisitions')
    bound=list(used)
    if pose_time_ns is not None:
        if type(pose_time_ns) is not int or not captures[0]-2<=pose_time_ns<=captures[-1]+2:raise ValueError('pose timestamp outside capture interval')
        bound.append(pose_time_ns)
    if not imu:raise LookupError('awaiting IMU history')
    if any(b<=a for a,b in zip(imu,imu[1:])):raise ValueError('IMU capture timestamps regressed/reused')
    first=bisect_right(imu,min(bound))-1;last=bisect_left(imu,max(bound))
    if first<0:raise TimeoutError('scan predates observed IMU history; not admitted')
    if last>=len(imu):raise LookupError('awaiting IMU sample after final scan capture')
    gap=max((imu[i+1]-imu[i] for i in range(first,last)),default=0)
    if gap>max_gap_ns:raise ValueError('IMU gap inside actual scan interval exceeds qualification limit')
    skew=0
    for value in used:
        index=bisect_left(imu,value)
        nearest=min(abs(imu[i]-value) for i in (index-1,index) if 0<=i<len(imu))
        skew=max(skew,nearest)
    return dict(imu_bracket_max_gap_ns=gap,point_imu_max_skew_ns=skew,
        first_capture_ros_ns=captures[0],last_capture_ros_ns=captures[-1],imu_samples=last-first+1,
        actual_acquisition_count=len(captures),retained_point_capture_count=len(used))


def capture_trace(value):
    """Validate actual renderer events, including zero-return acquisitions."""
    times=value['capture_times_ns'];counts=value['return_counts'];base=value['timebase_ns'];points=value['points']
    if type(base) is not int or base<0 or type(points) is not int or not 0<=points<=20000:raise ValueError('capture trace dimensions')
    if not isinstance(times,list) or len(times)!=5 or times!=sorted(set(times)) or times[0]!=base or times[-1]-base>200_000_000:
        raise ValueError('five actual renderer capture events required')
    if any(type(t) is not int or t<0 for t in times):raise ValueError('invalid capture times')
    if not isinstance(counts,list) or len(counts)!=5 or any(type(n) is not int or n<0 for n in counts) or sum(counts)!=points:
        raise ValueError('actual return count mismatch')
    return value
