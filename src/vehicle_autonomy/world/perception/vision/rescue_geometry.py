"""Declared calibration for the SHA-locked fixed-down CUADC camera assembly.

Gazebo camera +X optical forward, -Y image right and -Z image down. The
90/0/90-degree mount and -90-degree sensor yaw give the axes below in FLU.
This calibration is specific to this model and its flat spawn convention.
"""
import math
from vehicle_autonomy.contracts.core.geometry import Vector3
from vehicle_autonomy.world.transform.tree import rotate_vector


def project(detection,pose,label,width=640,height=480):
    if (width,height)!=(640,480) or label not in ('bucket','H'):raise ValueError('fixed rescue optical calibration required')
    x0,y0,x1,y1=detection.xyxy
    if not 0<=x0<x1<=width or not 0<=y0<y1<=height:raise ValueError('box outside calibrated image')
    fx=width/(2*math.tan(1.0));fy=fx
    u=(x0+x1)/2;v=(y0+y1)/2
    q=pose.orientation;p=pose.position
    offset=rotate_vector(q,Vector3(0,-.01,-.124923))
    origin=Vector3(p.x+offset.x,p.y+offset.y,p.z+offset.z)
    ray=rotate_vector(q,Vector3(-(v-height/2)/fy,-(u-width/2)/fx,-1))
    # AP local odom is zero at the base's 0.195 m ground spawn. Express the
    # supplied 0.30 m tube rim / ground H plane in that same odom frame.
    plane=(.3 if label=='bucket' else 0)-.195
    if ray.z>=-.5:raise ValueError('camera not pointing safely toward declared plane')
    distance=(plane-origin.z)/ray.z
    if distance<=0 or distance*math.sqrt(ray.x**2+ray.y**2+ray.z**2)>15:raise ValueError('unlocated rescue ray')
    return Vector3(origin.x+distance*ray.x,origin.y+distance*ray.y,plane)
