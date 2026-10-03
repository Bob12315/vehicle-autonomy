"""Validated pinhole/plane geometry; pixel labels alone cannot create a target."""
from dataclasses import dataclass
import hashlib,math,tomllib
from contracts.core.geometry import Vector3,Transform3,Quaternion
from core.transform import rotate_vector

@dataclass(frozen=True,slots=True)
class PlaneCalibration:
    width:int
    height:int
    fx:float
    fy:float
    cx:float
    cy:float
    camera_to_odom:Transform3
    plane_z:float
    source:str
    version:str
    max_distance_m:float=4.0
    def __post_init__(self):
        if type(self.width) is not int or type(self.height) is not int or min(self.width,self.height)<=0 or not self.source or not self.version:raise ValueError('explicit calibration dimensions/source/version required')
        if not all(math.isfinite(x) for x in (self.fx,self.fy,self.cx,self.cy,self.plane_z,self.max_distance_m)) or min(self.fx,self.fy,self.max_distance_m)<=0 or not 0<=self.cx<=self.width or not 0<=self.cy<=self.height:raise ValueError('invalid pinhole calibration')
    @classmethod
    def load(cls,path):
        if not path.is_file():raise ValueError('regular calibration file required')
        raw=path.read_bytes();d=tomllib.loads(raw.decode())
        if set(d)!={'schema','frame','width','height','fx','fy','cx','cy','translation','rotation','plane_z','source','max_distance_m'} or d['schema']!=1 or d['frame']!='odom':raise ValueError('invalid calibrated odom plane schema')
        return cls(d['width'],d['height'],d['fx'],d['fy'],d['cx'],d['cy'],Transform3(Vector3(*d['translation']),Quaternion(*d['rotation'])),d['plane_z'],d['source'],hashlib.sha256(raw).hexdigest(),d['max_distance_m'])
    def project(self,detection,image_size):
        if image_size!=(self.width,self.height):raise ValueError('calibration resolution mismatch')
        x0,y0,x1,y1=detection.xyxy
        if not (0<=x0<x1<=self.width and 0<=y0<y1<=self.height):raise ValueError('pixel box outside calibrated image')
        u=(x0+x1)/2;v=y1
        ray=rotate_vector(self.camera_to_odom.rotation,Vector3((u-self.cx)/self.fx,(v-self.cy)/self.fy,1))
        origin=self.camera_to_odom.translation
        if abs(ray.z)<1e-6:raise ValueError('unlocated horizontal ray')
        scale=(self.plane_z-origin.z)/ray.z
        if scale<=0 or scale*math.sqrt(ray.x**2+ray.y**2+ray.z**2)>self.max_distance_m:raise ValueError('unlocated ray intersection')
        return Vector3(origin.x+scale*ray.x,origin.y+scale*ray.y,self.plane_z)
