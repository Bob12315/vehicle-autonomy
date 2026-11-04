"""Optional local YOLO11 .pt adapter; Torch is loaded only in inference workers."""
import hashlib
from pathlib import Path
from .yolox import PixelDetection


class PtDetector:
    def __init__(self,path,expected_sha256,*,device='cpu',threshold=.3,iou=.45):
        path=Path(path)
        if path.suffix!='.pt' or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha256:
            raise ValueError('regular checksum-pinned PT weights required')
        if device not in ('cpu','0') or not .1<=threshold<=1 or not .1<=iou<=.9:raise ValueError('explicit CPU/GPU0 and bounded confidence/IoU required')
        from ultralytics import YOLO
        self.model=YOLO(str(path),task='detect')
        self.names=tuple(self.model.names[i] for i in range(len(self.model.names)))
        if self.names!=('bucket','H'):raise ValueError('rescue detector must declare exactly bucket/H classes')
        self.device=device;self.threshold=threshold;self.iou=iou

    def detect(self,bgr):
        import numpy as np
        if not isinstance(bgr,np.ndarray) or bgr.dtype!=np.uint8 or bgr.ndim!=3 or bgr.shape[2]!=3:
            raise ValueError('uint8 BGR image required')
        result=self.model.predict(source=bgr,imgsz=640,conf=self.threshold,iou=self.iou,
            device=self.device,verbose=False,max_det=128)[0]
        boxes=result.boxes.cpu()
        return tuple(PixelDetection(int(c),float(score),tuple(map(float,xyxy)))
            for c,score,xyxy in zip(boxes.cls.tolist(),boxes.conf.tolist(),boxes.xyxy.tolist()))
