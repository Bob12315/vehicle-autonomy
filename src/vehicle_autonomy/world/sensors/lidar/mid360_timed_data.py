"""Preserve physically acquired slice times from the external Gazebo plugin."""
import math,struct


def stamp_ns(message):
    s=message.header.stamp
    return s.sec*1_000_000_000+(s.nanosec if hasattr(s,'nanosec') else s.nsec)


def packed_capture_times(message,frame):
    """Audit preserved CustomMsg times in packed data, without Python points."""
    import numpy as np
    begin=stamp_ns(message)
    if (message.header.frame_id!=frame or message.is_bigendian or message.height!=1 or message.point_step!=40 or
        not 0<message.width<=20000 or message.row_step!=message.width*40 or len(message.data)!=message.width*40):
        raise ValueError('source timing cloud layout/frame budget')
    fields={f.name:(f.offset,f.datatype,f.count) for f in message.fields}
    # Standard PointField UINT32=6 / FLOAT64=8; no ROS import in this helper.
    if len(fields)!=len(message.fields) or fields.get('offset_time')!=(28,6,1) or fields.get('timestamp')!=(32,8,1):
        raise ValueError('original packed point timing fields missing')
    offsets=np.ndarray((message.width,),dtype='<u4',buffer=message.data,offset=28,strides=(40,))
    absolute=np.ndarray((message.width,),dtype='<f8',buffer=message.data,offset=32,strides=(40,))
    if np.any(offsets>200_000_000) or np.any(np.diff(offsets.astype(np.int64))<0) or not np.all(absolute==begin+offsets.astype(np.int64)):
        raise ValueError('original packed point timing disagrees with capture header')
    times,counts=np.unique(offsets,return_counts=True)
    return begin,[begin+int(t) for t in times],{begin+int(t):int(n) for t,n in zip(times,counts)}


def convert_custom(message,frame):
    begin=stamp_ns(message)
    if message.header.frame_id!=frame or message.timebase!=begin:raise ValueError('timed cloud frame/timebase mismatch')
    if not 0<message.point_num<=20000 or len(message.points)!=message.point_num:raise ValueError('invalid timed cloud size')
    output=bytearray();times=set();previous=-1;ranges=[];elevations=[]
    for point in message.points:
        offset=int(point.offset_time)
        if not previous<=offset<=200_000_000 or point.line>=4:raise ValueError('invalid slice timing/line')
        previous=offset
        xyz=(point.x,point.y,point.z)
        if not all(math.isfinite(v) for v in xyz):raise ValueError('nonfinite timed point')
        distance=math.sqrt(sum(v*v for v in xyz))
        if not .099<=distance<=40.1:continue
        output.extend(struct.pack('<fffffH2xfId',*xyz,float(point.reflectivity),distance,int(point.line),offset/1e9,offset,float(begin+offset)))
        times.add(offset);ranges.append(distance);elevations.append(math.degrees(math.atan2(xyz[2],math.hypot(*xyz[:2]))))
    return bytes(output),dict(stamp_ns=begin,end_stamp_ns=begin+previous,points=len(output)//40,
        source_width=message.point_num,source_height=1,capture_offsets_ns=sorted(times),
        range_min_m=min(ranges) if ranges else None,range_max_m=max(ranges) if ranges else None,
        elevation_min_deg=min(elevations) if elevations else None,elevation_max_deg=max(elevations) if elevations else None,
        intensity_available=True,timing='five_actual_Gazebo_render_capture_times_per_frame')
