"""Stream provenance and bounded references; no ROS dependencies or motion authority."""
from dataclasses import dataclass
from enum import Enum
import math
import re

from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.time import TimePoint


class SourceKind(str, Enum):
    LIVE='live'
    SIMULATION='simulation'
    REPLAY='replay'
    TEST_TRUTH='test_truth'


class DataKind(str, Enum):
    IMAGE='image'
    SCAN='laser_scan'
    CLOUD='point_cloud'
    IMU='imu'
    AP_EKF='ardupilot_ekf'
    ODOMETRY='odometry'
    SLAM_POSE='slam_pose'
    DETECTIONS='image_detections'
    MAP='occupancy_grid'
    PATH='navigation_path'


def identity(value, name):
    if not isinstance(value,str) or not 1<=len(value)<=256 or any(ord(c)<32 for c in value):
        raise ValueError('bounded '+name+' identity required')


@dataclass(frozen=True, slots=True)
class FrameDescriptor:
    frame_id: str
    convention: str
    origin_id: str
    units: str='SI'
    altitude_datum: str='not_applicable'

    def __post_init__(self):
        identity(self.frame_id,'frame');identity(self.origin_id,'origin')
        if self.convention not in ('ENU','FLU','NED','FRD','camera_optical','WGS84','image_pixels'):
            raise ValueError('explicit coordinate convention required')
        if self.units not in ('SI','degrees_metres','pixels'):raise ValueError('explicit units required')
        if self.convention=='WGS84' and self.units!='degrees_metres':raise ValueError('WGS84 requires degrees/metres')
        if self.convention=='image_pixels' and self.units!='pixels':raise ValueError('image requires pixel units')
        if self.convention not in ('WGS84','image_pixels') and self.units!='SI':raise ValueError('spatial frame requires SI units')
        if self.altitude_datum not in ('not_applicable','AMSL','relative_home','ellipsoid','local_origin'):
            raise ValueError('explicit altitude datum required')


@dataclass(frozen=True, slots=True)
class DataReference:
    """Logical owned-stream reference, never a fetch instruction or control input."""
    reference_id: str
    sha256: str
    byte_size: int
    media_type: str
    dimensions: tuple[int,...]=()

    def __post_init__(self):
        identity(self.reference_id,'data');identity(self.media_type,'media type')
        if not isinstance(self.sha256,str) or not re.fullmatch('[0-9a-f]{64}',self.sha256):raise ValueError('content digest required')
        if type(self.byte_size) is not int or not 0<=self.byte_size<=64*1024*1024:raise ValueError('data size outside budget')
        if not isinstance(self.dimensions,tuple) or len(self.dimensions)>3 or any(type(v) is not int or not 1<=v<=16384 for v in self.dimensions):
            raise ValueError('bounded immutable dimensions required')


@dataclass(frozen=True, slots=True)
class SampleHeader:
    source_id: str
    sensor_id: str
    kind: DataKind
    generation: str
    sequence: int
    source_timestamp_ns: int
    source_clock_domain: str
    received_at: TimePoint
    captured_at: TimePoint | None
    frame: FrameDescriptor
    calibration_version: str
    source_kind: SourceKind
    quality: QualityState
    confidence: float=1.
    covariance: tuple[float,...]=()

    def __post_init__(self):
        for value,name in ((self.source_id,'source'),(self.sensor_id,'sensor'),(self.generation,'generation'),
                           (self.source_clock_domain,'clock'),(self.calibration_version,'calibration')):identity(value,name)
        if not isinstance(self.kind,DataKind) or not isinstance(self.source_kind,SourceKind) or not isinstance(self.quality,QualityState):
            raise TypeError('typed source, data kind and quality required')
        if any(type(v) is not int or v<0 for v in (self.sequence,self.source_timestamp_ns)):raise ValueError('nonnegative source sequence/time required')
        if not isinstance(self.received_at,TimePoint) or self.captured_at is not None and not isinstance(self.captured_at,TimePoint):raise TypeError('typed timestamps required')
        if not isinstance(self.frame,FrameDescriptor):raise TypeError('typed frame required')
        if type(self.confidence) not in (int,float) or not math.isfinite(self.confidence) or not 0<=self.confidence<=1:raise ValueError('confidence outside bounds')
        if not isinstance(self.covariance,tuple) or len(self.covariance) not in (0,9,36) or any(type(v) not in (int,float) or not math.isfinite(v) for v in self.covariance):
            raise ValueError('finite immutable covariance required')
        n=3 if len(self.covariance)==9 else 6
        if self.covariance and any(self.covariance[i*n+i]<0 for i in range(n)):raise ValueError('negative covariance diagonal')
        if self.captured_at is not None and self.captured_at.clock_domain_id==self.received_at.clock_domain_id and self.captured_at>self.received_at:
            raise ValueError('capture follows receipt')


@dataclass(frozen=True, slots=True)
class StreamObservation:
    header: SampleHeader
    data: DataReference

    def __post_init__(self):
        if not isinstance(self.header,SampleHeader) or not isinstance(self.data,DataReference):raise TypeError('typed sample and data reference required')
