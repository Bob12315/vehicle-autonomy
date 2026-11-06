"""Pure-rotation virtual nadir camera in framework ENU / body FLU.

Adapted from CUADC VirtualNadirRectifier: same rotational homography, bounded
valid mask and locked yaw, using the current fixed-down Gazebo calibration.
OpenCV camera axes are right/down/forward; no gimbal or vehicle commands exist.
"""
from dataclasses import dataclass,replace
import math
from uuid import uuid4

from vehicle_autonomy.contracts.core.geometry import Vector3
from vehicle_autonomy.world.transform.tree import rotate_vector

CALIBRATION_ID='cuadc2026-fixed-down-v1'
CAMERA_OFFSET=Vector3(0,-.01,-.124923)


def validate_config(value):
    fields={'calibration_id','yaw_reference_mode','max_sample_distance_ms','max_bracket_span_ms','min_attitude_rate_hz'}
    if (type(value) is not dict or set(value)!=fields or value['calibration_id']!=CALIBRATION_ID
            or value['yaw_reference_mode']!='lock_on_start'):
        raise ValueError('fixed-down virtual camera calibration and lock_on_start required')
    for key,low,high in (('max_sample_distance_ms',25,125),('max_bracket_span_ms',25,150),('min_attitude_rate_hz',8,50)):
        n=value[key]
        if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high:
            raise ValueError('virtual camera timing bound invalid: '+key)
    return dict(value)


def rotation(q):
    import numpy as np
    axes=[rotate_vector(q,v) for v in (Vector3(1,0,0),Vector3(0,1,0),Vector3(0,0,1))]
    return np.array([(v.x,v.y,v.z) for v in axes]).T


@dataclass(frozen=True)
class VirtualCamera:
    origin: Vector3 | None
    rotation_enu_camera: object
    k: object
    reference_id: str
    yaw_ref_rad: float

    def ray(self,u,v):
        import numpy as np
        ray=self.rotation_enu_camera @ np.linalg.solve(self.k,np.array((u,v,1.)))
        return Vector3(*map(float,ray))

    def metadata(self):
        return dict(calibration_id=CALIBRATION_ID,reference_id=self.reference_id,yaw_ref_rad=self.yaw_ref_rad,
            origin_enu=None if self.origin is None else [self.origin.x,self.origin.y,self.origin.z],k=self.k.tolist(),
            rotation_enu_camera=self.rotation_enu_camera.tolist())

    def with_pose(self,pose):
        offset=rotate_vector(pose.orientation,CAMERA_OFFSET);p=pose.position
        return replace(self,origin=Vector3(p.x+offset.x,p.y+offset.y,p.z+offset.z))


@dataclass(frozen=True)
class RectifiedFrame:
    image: object
    valid_mask: object
    camera: VirtualCamera
    homography: object

    def accepts(self,box):
        # Reject detections whose center or material box area lies outside real
        # sensor pixels. Rectification cannot manufacture observations in borders.
        import numpy as np
        x0,y0,x1,y1=box
        height,width=self.valid_mask.shape
        if not 0<=x0<x1<=width or not 0<=y0<y1<=height:return False
        patch=self.valid_mask[int(y0):math.ceil(y1),int(x0):math.ceil(x1)]
        return bool(patch.size and self.valid_mask[int((y0+y1)/2),int((x0+x1)/2)]
            and np.count_nonzero(patch)/patch.size>=.95)


class VirtualNadir:
    def __init__(self):
        import numpy as np
        self.width=640;self.height=480
        f=self.width/(2*math.tan(1.0))
        self.k=np.array(((f,0,320),(0,f,240),(0,0,1.)),dtype=np.float64)
        self.mount=np.array(((0.,-1,0),(-1.,0,0),(0,0,-1.)))
        self.offset=CAMERA_OFFSET
        self.key=None;self.yaw_ref=None;self.reference_id=uuid4().hex

    def rectify(self,image,match):
        frame=self._rectify(image,match.pose.orientation,match.key)
        return replace(frame,camera=frame.camera.with_pose(match.pose))

    def rectify_attitude(self,image,match):
        return self._rectify(image,match.orientation,match.key)

    def _rectify(self,image,orientation,key):
        import cv2,numpy as np
        if image.shape!=(self.height,self.width,3) or image.dtype!=np.uint8:
            raise ValueError('fixed-down calibrated uint8 BGR image required')
        if self.key is not None and key!=self.key:raise ValueError('virtual camera motion epoch changed')
        self.key=key;r=rotation(orientation)
        # Invert only a bounded downward view; large tilts cannot recover a
        # missing nadir field of view and must not enter target control.
        if (r@self.mount)[2,2]>-.5:raise ValueError('camera tilt exceeds virtual nadir bound')
        if self.yaw_ref is None:self.yaw_ref=math.atan2(r[1,0],r[0,0])
        c=math.cos(self.yaw_ref);s=math.sin(self.yaw_ref)
        virtual=np.array(((c,-s,0),(s,c,0),(0,0,1.)))@self.mount
        h=self.k@virtual.T@r@self.mount@np.linalg.inv(self.k)
        if not np.isfinite(h).all() or abs(h[2,2])<1e-12:raise ValueError('invalid virtual camera homography')
        h/=h[2,2]
        frame=cv2.warpPerspective(image,h,(self.width,self.height),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        mask=cv2.warpPerspective(np.full((self.height,self.width),255,np.uint8),h,(self.width,self.height),
            flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)
        if np.count_nonzero(mask)/mask.size<.35:raise ValueError('insufficient virtual camera field of view')
        camera=VirtualCamera(None,virtual,self.k,self.reference_id,self.yaw_ref)
        return RectifiedFrame(frame,mask,camera,h)
