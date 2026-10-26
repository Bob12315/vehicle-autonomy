"""Validate actual YOLO output and its original camera fact before events/UI."""
from vehicle_autonomy.contracts.streams import DataKind,SourceKind
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.world.model.stream_input import observation
from vehicle_autonomy.world.perception.vision.yolox import PixelDetection
from vehicle_autonomy.world.perception.vision.stream_worker import COCO


def validate_detection(item,value,*,camera_source,camera_generation,model_sha256):
    fields={'schema','detections','primary_label','detected','image_header','image_reference','captured_at','source_frame','model_id','model_version','inference_backend','opencv_version','inference_ns','inference_started_ns','completed_ns','world_positions_available'}
    if type(value) is not dict or set(value)!=fields or value['schema']!=1:raise ValueError('strict image detection result required')
    if value['model_id']!='opencv-zoo-yolox-2022nov' or value['model_version']!=model_sha256 or value['inference_backend']!='opencv_dnn_cpu':raise ValueError('unverified detector model/backend')
    if value['world_positions_available'] is not False:raise ValueError('image-only detector cannot publish world positions')
    original=observation(dict(header=value['image_header'],data=value['image_reference']));h=original.header;out=item.header
    if (h.source_id,h.generation,h.sensor_id,h.kind,h.source_kind)!=(camera_source,camera_generation,'camera',DataKind.IMAGE,SourceKind.SIMULATION):raise ValueError('unverified original camera identity/epoch')
    if (out.kind,out.frame.convention,out.frame.units)!=(DataKind.DETECTIONS,'image_pixels','pixels'):raise ValueError('image detection coordinate contract')
    if (h.sequence,h.source_timestamp_ns,h.source_clock_domain,h.captured_at,h.calibration_version,h.frame.origin_id,h.frame.frame_id,h.source_kind)!=(out.sequence,out.source_timestamp_ns,out.source_clock_domain,out.captured_at,out.calibration_version,out.frame.origin_id,out.frame.frame_id,out.source_kind):raise ValueError('detector retimed or re-framed original camera fact')
    if h.received_at>out.received_at or value['captured_at']!=to_json_value(h.captured_at) or value['source_frame']!=h.frame.frame_id:raise ValueError('detector original capture/receipt mismatch')
    if len(original.data.dimensions)!=3 or original.data.dimensions[2]!=3 or original.data.media_type not in ('application/x-raw-rgb8','application/x-raw-bgr8'):raise ValueError('original actual RGB/BGR reference required')
    height,width,_=original.data.dimensions
    if original.data.byte_size!=height*width*3:raise ValueError('original image dimensions/size mismatch')
    boxes=value['detections']
    if type(boxes) is not list or len(boxes)>128 or type(value['detected']) is not bool or value['detected']!=bool(boxes):raise ValueError('detection presence/list mismatch')
    previous=1.
    for box in boxes:
        if type(box) is not dict or set(box)!={'class_id','label','confidence','xyxy'}:raise ValueError('strict pixel detection required')
        if not isinstance(box['xyxy'],list) or any(type(v) not in (int,float) for v in box['xyxy']):raise ValueError('numeric pixel coordinates required')
        d=PixelDetection(box['class_id'],box['confidence'],tuple(box['xyxy']))
        if d.class_id>=len(COCO) or box['label']!=COCO[d.class_id] or type(d.confidence) not in (int,float) or not .5<=d.confidence<=previous:raise ValueError('class/score/model mismatch')
        if not 0<=d.xyxy[0]<d.xyxy[2]<=width or not 0<=d.xyxy[1]<d.xyxy[3]<=height:raise ValueError('pixel coordinates outside original image')
        previous=d.confidence
    if out.confidence!=max((b['confidence'] for b in boxes),default=0.):raise ValueError('header confidence does not reflect actual model output')
    if value['primary_label']!=(boxes[0]['label'] if boxes else None):raise ValueError('primary label does not reflect actual detections')
    if type(value['inference_ns']) is not int or value['inference_ns']<0 or type(value['completed_ns']) is not int or type(value['inference_started_ns']) is not int or value['inference_started_ns']<h.received_at.monotonic_ns or value['completed_ns']!=value['inference_started_ns']+value['inference_ns'] or out.received_at.monotonic_ns!=value['completed_ns']:raise ValueError('original inference timing mismatch')
    return value
