"""Render only detections from this exact inference/image pair."""
from vehicle_autonomy.world.sensors.camera.packet import encode


def annotated_packet(image,metadata,detections,names,*,epoch,world_generation,model_sha256,captured_host_ns,started_ns,completed_ns):
    import cv2
    frame=image.copy();objects=[]
    for detection,backend in detections:
        x0,y0,x1,y1=detection.xyxy
        label=names[detection.class_id]
        color=(60,220,70) if backend=='pt' else (255,210,40)
        title=('YOLO '+label if backend=='pt' else 'H marker')+' '+format(detection.confidence,'.2f')
        left,top,right,bottom=map(int,(x0,y0,x1,y1))
        cv2.rectangle(frame,(left,top),(right,bottom),color,2)
        baseline=max(17,min(frame.shape[0]-5,top-6))
        cv2.putText(frame,title,(max(0,left),baseline),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),3,cv2.LINE_AA)
        cv2.putText(frame,title,(max(0,left),baseline),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1,cv2.LINE_AA)
        objects.append(dict(label=label,confidence=detection.confidence,detector=backend,xyxy=list(detection.xyxy)))
    cv2.rectangle(frame,(0,0),(frame.shape[1]-1,28),(25,30,35),-1)
    banner='YOLO | '+str(sum(backend=='pt' for _,backend in detections))+' detections'
    banner+=' | '+str(round((completed_ns-started_ns)/1e6))+' ms'
    cv2.putText(frame,banner,(8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(240,245,240),1,cv2.LINE_AA)
    ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,85])
    if not ok:raise ValueError('YOLO preview encode failed')
    header=dict(metadata,kind='yolo',display_name='YOLO 识别画面',original_kind=metadata['kind'],
        original_received_ns=metadata['received_ns'],captured_host_ns=captured_host_ns,
        inference_started_ns=started_ns,inference_completed_ns=completed_ns,
        model_sha256=model_sha256,detector_epoch=epoch,world_generation=world_generation,
        detections=objects,frame_role='annotated_inference')
    # received_ns remains the original camera receipt, never the new JPEG time.
    return encode(header,jpeg.tobytes())
